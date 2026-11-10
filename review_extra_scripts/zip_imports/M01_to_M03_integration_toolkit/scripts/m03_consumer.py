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
        if catalog.get('validation_status')!='APPROVED' and not allow_provisional_sandbox:
            raise NotApprovedForKPI(f"{catalog['shop_id']}: {catalog.get('validation_status')}")
        version=c.execute('SELECT version_id,status FROM dataset_versions WHERE shop_id=?',(catalog['shop_id'],)).fetchone()
        if version is None or version[0]!=catalog['version_id'] or version[1]!=catalog['validation_status']:
            raise ValueError('Catalog/version inconsistency')
        return c,catalog
    except Exception:
        c.close();raise

def query_entity_count(connection,catalog,entity):
    if entity not in catalog['row_counts']:raise ValueError('Unknown entity')
    if catalog['row_counts'][entity]==0:return None  # unsupported is not zero
    if entity not in {'orders','order_lines','payments','products','customers','service_visits'}:
        raise ValueError('Entity not exposed by this consumer example')
    return connection.execute(f'SELECT COUNT(*) FROM "{entity}" WHERE shop_id=?',(catalog['shop_id'],)).fetchone()[0]
