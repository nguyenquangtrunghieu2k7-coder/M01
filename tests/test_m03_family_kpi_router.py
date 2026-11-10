"""M03 shared family KPI router is approval-gated and family-correct."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
from scripts.m03_family_kpi_router import query_approved_kpi
from scripts.m03_consumer import NotApprovedForKPI

class FamilyRouterTests(unittest.TestCase):
 def make(self,root,shop,family,metric,create,rows):
  path=root/(shop+'.sqlite')
  with sqlite3.connect(path) as db:
   db.executescript('CREATE TABLE business_catalog(catalog_json TEXT);'
     'CREATE TABLE dataset_versions(version_id TEXT,shop_id TEXT,status TEXT);'+create)
   cat={'shop_id':shop,'version_id':'v1','validation_status':'APPROVED',
        'approval_status':'PRODUCTION_APPROVED','family':family,
        'approved_metrics':[metric]}
   db.execute('INSERT INTO business_catalog VALUES(?)',(json.dumps(cat),))
   db.execute('INSERT INTO dataset_versions VALUES(?,?,?)',('v1',shop,'APPROVED'))
   for stmt,args in rows:db.execute(stmt,args)
  return path
 def test_approved_router_kpis(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   p1=self.make(root,'dev_001','retail_single_export','invoice_revenue',
     'CREATE TABLE family_order_facts(invoice_code TEXT,order_date TEXT,status TEXT,revenue_vnd INTEGER,base_qty INTEGER);',
     [('INSERT INTO family_order_facts VALUES(?,?,?,?,?)',('A','2025-01-01','completed',500,2)),
      ('INSERT INTO family_order_facts VALUES(?,?,?,?,?)',('B','2025-01-01','returned',900,3))])
   self.assertEqual(query_approved_kpi(p1,'invoice_revenue',
      as_of_date='2025-01-01',start_date='2025-01-01',end_date='2025-01-01'),500)
   with self.assertRaises(NotApprovedForKPI):
    query_approved_kpi(p1,'eligible_order_count',as_of_date='2025-01-01',
      start_date='2025-01-01',end_date='2025-01-01')
   p9=self.make(root,'dev_009','invoice_summary_only','invoice_revenue',
     'CREATE TABLE family_invoice_facts(invoice_code TEXT,order_date TEXT,status TEXT,revenue_vnd INTEGER,debt_snapshot_vnd INTEGER);',
     [('INSERT INTO family_invoice_facts VALUES(?,?,?,?,?)',('A','2025-01-01','shipping',1000,0)),
      ('INSERT INTO family_invoice_facts VALUES(?,?,?,?,?)',('B','2025-01-01','cancelled',5000,0))])
   self.assertEqual(query_approved_kpi(p9,'invoice_revenue',
      as_of_date='2025-01-01',start_date='2025-01-01',end_date='2025-01-01'),1000)
   p12=self.make(root,'dev_012','motorcycle_service_ledger','visit_count',
     'CREATE TABLE family_service_facts(visit_date TEXT,warranty INTEGER,amount_vnd INTEGER);',
     [('INSERT INTO family_service_facts VALUES(?,?,?)',('2025-07-01',0,500)),
      ('INSERT INTO family_service_facts VALUES(?,?,?)',('2025-07-01',1,0))])
   self.assertEqual(query_approved_kpi(p12,'visit_count',
      as_of_date='2025-07-01',start_date='2025-07-01',end_date='2025-07-01'),2)
 def test_family_mismatch_and_provisional_closed(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   path=self.make(root,'dev_001','incorrect','invoice_revenue',
     'CREATE TABLE family_order_facts(invoice_code TEXT,order_date TEXT,status TEXT,revenue_vnd INTEGER,base_qty INTEGER);',[])
   with self.assertRaises(NotApprovedForKPI):
    query_approved_kpi(path,'invoice_revenue',as_of_date='2025-01-01',
      start_date='2025-01-01',end_date='2025-01-01')
   with sqlite3.connect(path) as db:
    cat=json.loads(db.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
    cat['approval_status']='CANDIDATE_NOT_APPROVED'
    db.execute('UPDATE business_catalog SET catalog_json=?',(json.dumps(cat),))
   with self.assertRaises(NotApprovedForKPI):
    query_approved_kpi(path,'invoice_revenue',as_of_date='2025-01-01',
      start_date='2025-01-01',end_date='2025-01-01')

if __name__=='__main__':unittest.main()
