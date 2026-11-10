import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from scripts.m03_consumer import NotApprovedForKPI,open_business_dataset,query_entity_count

class M03ContractTests(unittest.TestCase):
 def test_mapped_zero_and_unmapped(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'shop.sqlite'
   with sqlite3.connect(path) as c:
    c.executescript('CREATE TABLE business_catalog(catalog_json TEXT);CREATE TABLE dataset_versions(version_id TEXT,shop_id TEXT,status TEXT);CREATE TABLE orders(shop_id TEXT);')
    catalog={'shop_id':'dev_001','version_id':'v1','validation_status':'APPROVED','approval_status':'PRODUCTION_APPROVED','row_counts':{'orders':0}}
    c.execute('INSERT INTO business_catalog VALUES(?)',(json.dumps(catalog),))
    c.execute('INSERT INTO dataset_versions VALUES(?,?,?)',('v1','dev_001','APPROVED'))
   db,cat=open_business_dataset(path)
   try:
    self.assertEqual(query_entity_count(db,cat,'orders'),0)
    with self.assertRaises(ValueError):query_entity_count(db,cat,'payments')
   finally:db.close()
   catalog['approval_status']='CANDIDATE_NOT_APPROVED'
   with sqlite3.connect(path) as c:c.execute('UPDATE business_catalog SET catalog_json=?',(json.dumps(catalog),))
   with self.assertRaises(NotApprovedForKPI):open_business_dataset(path)
   db,cat=open_business_dataset(path,allow_provisional_sandbox=True);db.close()

if __name__=='__main__':unittest.main()
