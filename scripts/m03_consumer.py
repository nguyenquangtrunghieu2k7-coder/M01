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
