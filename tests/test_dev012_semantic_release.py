"""End-to-end repair-ledger source QA with paid and warranty visit semantics."""
import json,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from openpyxl import Workbook
from scripts.dev012_semantic_release import acceptance,publish,query_kpi,parse_day,parse_money

ROOT=Path(__file__).resolve().parents[1]
class RepairSemanticTests(unittest.TestCase):
 def fixture(self,root):
  folder=root/'public_test/data/dev_012';folder.mkdir(parents=True)
  book=Workbook();ws=book.active;ws.title='T7-2025'
  ws.append(['SỔ SỬA XE'])
  ws.append(['Ngày','Xe','Làm gì','Thợ','Tiền','Ghi chú'])
  ws.append(['01/07/2025','wave 59X1-123.45','Thay dầu','A',120000,''])
  ws.append(['1 thg 7 2025','wave 59X1-123.45','Bảo hành','A','0đ','bảo hành'])
  ws.append([45841,'future 59K1-234.56','Vá lốp','B','2tr638',''])
  ws.append(['Ghi chú: tiền tính bằng đồng'])
  book.save(folder/'SoSuaXe.xlsx')
  contract=root/'contracts';contract.mkdir()
  (contract/'dev_012.json').write_text(json.dumps({
   'shop_id':'dev_012','family':'motorcycle_service_ledger',
   'approval_status':'CANDIDATE_NOT_APPROVED','official_kpis_approved':[],
   'source_manifest':[{'path':'public_test/data/dev_012/SoSuaXe.xlsx',
      'object':'T7-2025','format':'xlsx','candidate_role':'service_visits'}]}))
  dest=root/'candidate';dest.mkdir()
  proc=subprocess.run([sys.executable,str(ROOT/'build_9_shops.py'),
     '--data-root',str(root),'--output',str(dest),'--shops','dev_012',
     '--family-config-dir',str(contract)],capture_output=True,text=True)
  self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
  return folder/'SoSuaXe.xlsx',dest/'dev_012.sqlite'
 def test_money_and_date(self):
  self.assertEqual(parse_money('2tr638'),2638000)
  self.assertEqual(parse_money('270.000đ'),270000)
  self.assertEqual(parse_money('1,086tr'),1086000)
  self.assertEqual(parse_day('1 thg 7 2025'),'2025-07-01')
  with self.assertRaises(ValueError):parse_money('1tr2tr')
 def test_source_acceptance_and_release(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source,candidate=self.fixture(root)
   qa=acceptance(source,candidate)
   self.assertTrue(qa['accepted'],qa['errors'])
   self.assertEqual(qa['repair_visits'],3)
   self.assertEqual(qa['sheet_notes_excluded'],1)
   self.assertEqual(qa['kpis']['warranty_visit_count'],1)
   self.assertEqual(qa['kpis']['service_revenue_vnd'],2758000)
   output=root/'release'
   manifest=publish(source,candidate,output,'Synthetic owner')
   self.assertEqual(manifest['approval_status'],'PRODUCTION_APPROVED')
   with sqlite3.connect(candidate) as conn:
    self.assertEqual(conn.execute('SELECT COUNT(*) FROM staging_rows').fetchone()[0],4)
   with sqlite3.connect(output/'dev_012.sqlite') as conn:
    self.assertEqual(conn.execute('SELECT COUNT(*) FROM family_service_facts').fetchone()[0],3)
    first,last=conn.execute('SELECT MIN(visit_date),MAX(visit_date) FROM family_service_facts').fetchone()
    self.assertEqual(query_kpi(conn,'visit_count',start_date=first,end_date=last,as_of_date=last),3)
    self.assertEqual(query_kpi(conn,'warranty_visit_count',start_date=first,end_date=last,as_of_date=last),1)
    with self.assertRaises(ValueError):
     query_kpi(conn,'product_sales',start_date=first,end_date=last,as_of_date=last)
 def test_warranty_cannot_have_positive_cash(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source,candidate=self.fixture(root)
   from openpyxl import load_workbook
   book=load_workbook(source);book.active['E4']=50000;book.save(source)
   qa=acceptance(source,candidate)
   self.assertFalse(qa['accepted'])
   self.assertTrue(any('Warranty rule contradiction' in x for x in qa['errors']))
   with self.assertRaises(ValueError):publish(source,candidate,root/'release','Synthetic owner')
   self.assertFalse((root/'release').exists())

if __name__=='__main__':unittest.main()
