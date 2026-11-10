import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from scripts.m03_consumer import NotApprovedForKPI,UnanswerableKPI,open_business_dataset,query_entity_count,query_shop_revenue

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

 def test_approved_revenue_as_of_and_outside_coverage(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'shop.sqlite'
   with sqlite3.connect(path) as db:
    db.executescript('CREATE TABLE business_catalog(catalog_json TEXT);'
                     'CREATE TABLE dataset_versions(version_id TEXT,shop_id TEXT,status TEXT);'
                     'CREATE TABLE orders(shop_id TEXT,event_date TEXT);'
                     'CREATE TABLE order_lines(shop_id TEXT,event_date TEXT,status_raw TEXT,amount TEXT);')
    cat={'shop_id':'dev_006','version_id':'v1','validation_status':'APPROVED',
         'approval_status':'PRODUCTION_APPROVED',
         'approved_metrics':['revenue_by_order_date'],
         'row_counts':{'orders':4,'order_lines':4}}
    db.execute('INSERT INTO business_catalog VALUES(?)',(json.dumps(cat),))
    db.execute('INSERT INTO dataset_versions VALUES(?,?,?)',('v1','dev_006','APPROVED'))
    db.executemany('INSERT INTO orders VALUES(?,?)',[('dev_006','2025-04-01'),
      ('dev_006','2025-04-02'),('dev_006','2025-04-03'),('dev_006','2025-04-04')])
    db.executemany('INSERT INTO order_lines VALUES(?,?,?,?)',[
      ('dev_006','2025-04-01','completed','100'),
      ('dev_006','2025-04-02','shipping','200'),
      ('dev_006','2025-04-03','returned','900'),
      ('dev_006','2025-04-04','cancelled','700')])
   con,cat=open_business_dataset(path)
   try:
    self.assertEqual(query_shop_revenue(con,cat,start_date='2025-04-01',
           end_date='2025-04-04',as_of_date='2025-04-02'),300)
    self.assertEqual(query_shop_revenue(con,cat,start_date='2025-04-03',
           end_date='2025-04-04',as_of_date='2025-04-04'),0)
    with self.assertRaises(UnanswerableKPI):
     query_shop_revenue(con,cat,start_date='2025-05-01',
         end_date='2025-05-10',as_of_date='2025-05-10')
    with self.assertRaises(UnanswerableKPI):
     query_shop_revenue(con,cat,start_date='2025-04-03',
         end_date='2025-04-03',as_of_date='2025-04-02')
    no_cap=dict(cat,approved_metrics=[])
    with self.assertRaises(NotApprovedForKPI):
     query_shop_revenue(con,no_cap,start_date='2025-04-01',
         end_date='2025-04-04',as_of_date='2025-04-04')
   finally: con.close()

if __name__=='__main__':unittest.main()
