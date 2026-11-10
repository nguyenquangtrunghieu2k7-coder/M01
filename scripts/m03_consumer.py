"""Minimal M03 reader with explicit production gate and scoped queries."""
import json
import sqlite3
from pathlib import Path

class NotApprovedForKPI(RuntimeError): pass

def open_business_dataset(db_path, *, allow_provisional_sandbox=False):
    path=Path(db_path)
    if not path.is_file():raise FileNotFoundError(path)
    c=sqlite3.connect(f'file:{path.resolve()}?mode=ro',uri=True)
    try:
        row=c.execute('SELECT catalog_json FROM business_catalog').fetchall()
        if len(row)!=1:raise ValueError('Expected one business catalog')
        catalog=json.loads(row[0][0])
        if not allow_provisional_sandbox and (catalog.get('validation_status')!='APPROVED' or catalog.get('approval_status') not in ('APPROVED','PRODUCTION_APPROVED')):
            raise NotApprovedForKPI(f"{catalog['shop_id']}: {catalog.get('validation_status')}")
        version=c.execute('SELECT version_id,status FROM dataset_versions WHERE shop_id=?',(catalog['shop_id'],)).fetchone()
        if version is None or version[0]!=catalog['version_id'] or version[1]!=catalog['validation_status']:
            raise ValueError('Catalog/version inconsistency')
        return c,catalog
    except Exception:
        c.close();raise

def query_entity_count(connection,catalog,entity):
    """Return verified count. Unmapped is unknown, but a mapped empty table is zero."""
    import re
    if not isinstance(entity,str) or not re.fullmatch(r'[a-z][a-z0-9_]*',entity):
        raise ValueError('Invalid entity name')
    counts=catalog.get('row_counts',{})
    if entity not in counts:raise ValueError('Unmapped entity: '+entity)
    tables={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if entity not in tables:raise ValueError('Missing entity table: '+entity)
    actual=connection.execute(f'SELECT COUNT(*) FROM "{entity}" WHERE shop_id=?',(catalog['shop_id'],)).fetchone()[0]
    if actual!=counts[entity]:raise ValueError(f'Catalog count mismatch: {entity}')
    return actual

class UnanswerableKPI(ValueError):
    """Requested data or covered period cannot support a numerical answer."""

def query_shop_revenue(connection, catalog, *, start_date, end_date, as_of_date):
    """Rulebook §1/§2 revenue from approved line-grain POS mart.

    Inclusive period; limit by question-specific as_of_date; exclude cancelled
    and returned orders even if their return was recorded after as_of_date.
    An interval wholly outside the published order-date range is unanswerable.
    """
    from datetime import date
    if 'revenue_by_order_date' not in catalog.get('approved_metrics', []):
        raise NotApprovedForKPI('Revenue metric not approved for this business family/version')
    start=date.fromisoformat(start_date)
    end=date.fromisoformat(end_date)
    cutoff=date.fromisoformat(as_of_date)
    if end < start:
        raise ValueError('end_date must not precede start_date')
    covered=connection.execute("""
        SELECT MIN(event_date),MAX(event_date) FROM orders WHERE shop_id=?
    """,(catalog['shop_id'],)).fetchone()
    if not covered or not covered[0] or not covered[1]:
        raise UnanswerableKPI('Missing order-date coverage')
    if end.isoformat()<covered[0] or start.isoformat()>covered[1] or start>cutoff:
        raise UnanswerableKPI('Question interval outside available as_of/source coverage')
    effective_end=min(end,cutoff)
    if effective_end < start:
        raise UnanswerableKPI('No dates available by as_of_date')
    result=connection.execute("""
        SELECT COUNT(*),SUM(CAST(amount AS INTEGER))
        FROM order_lines
        WHERE shop_id=?
          AND event_date>=? AND event_date<=?
          AND status_raw IN ('completed','shipping')
    """,(catalog['shop_id'],start.isoformat(),effective_end.isoformat())).fetchone()
    # A covered period with no eligible orders has legitimate revenue 0.
    return int(result[1] or 0)
