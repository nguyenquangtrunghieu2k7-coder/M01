import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from scripts.m03_consumer import NotApprovedForKPI,open_business_dataset,query_entity_count

class M03HandoffTests(unittest.TestCase):
    def test_fail_closed_and_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'pilot.sqlite'
            with sqlite3.connect(db) as c:
                c.execute('CREATE TABLE business_catalog(catalog_key TEXT,catalog_json TEXT)')
                c.execute('CREATE TABLE dataset_versions(version_id TEXT,shop_id TEXT,contract_version TEXT,config_sha256 TEXT,created_at TEXT,status TEXT)')
                c.execute('CREATE TABLE orders(shop_id TEXT)')
                cat={'shop_id':'dev_009','version_id':'v1','validation_status':'PROVISIONAL_NOT_FOR_PRODUCTION','row_counts':{'orders':1,'payments':0}}
                c.execute('INSERT INTO business_catalog VALUES(?,?)',('dev_009',json.dumps(cat)))
                c.execute('INSERT INTO dataset_versions VALUES(?,?,?,?,?,?)',('v1','dev_009','0.2.0','x','now','PROVISIONAL_NOT_FOR_PRODUCTION'))
                c.execute('INSERT INTO orders VALUES(?)',('dev_009',))
            with self.assertRaises(NotApprovedForKPI):open_business_dataset(db)
            c,cat=open_business_dataset(db,allow_provisional_sandbox=True)
            try:
                self.assertEqual(query_entity_count(c,cat,'orders'),1)
                self.assertIsNone(query_entity_count(c,cat,'payments'))
            finally:c.close()
