"""dev001 independent one-file retail KPI semantics and release contract."""
import json,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from openpyxl import Workbook
from scripts.dev001_semantic_release import acceptance,publish,query_kpi,amount
ROOT=Path(__file__).resolve().parents[1]

class RetailSingleExportTests(unittest.TestCase):
 def fixture(self,root):
  folder=root/'public_test/data/dev_001';folder.mkdir(parents=True)
  book=Workbook();ws=book.active;ws.title='Sheet1'
  ws.append(['SỔ CHI TIẾT BÁN HÀNG'])
  ws.append(['Kỳ báo cáo: toàn bộ','Kênh bán: Tất cả'])
  ws.append([])
  ws.append(['Ngày','Mã đơn hàng','Tên hàng hóa','Đơn vị tính','Số lượng',
             'Đơn giá','Thành tiền','Trạng thái','Số lượng quy đổi','Khách hàng'])
  ws.append(['01/01/2025','A01','Coca Cola 330ml','thùng',1,24000,'24,000.0000','Hoàn thành',24,'Khách A'])
  ws.append(['01/01/2025','A01','Pepsi 330ml','lốc',1,6000,'6,000.0000','Hoàn thành',6,'Khách A'])
  ws.append(['01/01/2025','A02','Coca Cola 330ml','lon',2,1000,'2,000.0000','Đã hoàn hàng',2,'Khách B'])
  ws.append([None,None,None,None,None,None,'32,000.0000',None,None,'Cộng ngày 01/01/2025'])
  source=folder/'So_chi_tiet_ban_hang.xlsx';book.save(source)
  config=root/'contracts';config.mkdir()
  (config/'dev_001.json').write_text(json.dumps({
      'shop_id':'dev_001','family':'retail_single_export',
      'approval_status':'CANDIDATE_NOT_APPROVED','official_kpis_approved':[],
      'source_manifest':[{'path':'public_test/data/dev_001/So_chi_tiet_ban_hang.xlsx',
      'object':'Sheet1','format':'xlsx','candidate_role':'order_lines'}]}))
  out=root/'candidate';out.mkdir()
  proc=subprocess.run([sys.executable,str(ROOT/'build_9_shops.py'),
    '--data-root',str(root),'--output',str(out),'--shops','dev_001',
    '--family-config-dir',str(config)],capture_output=True,text=True)
  self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
  return source,out/'dev_001.sqlite'
 def test_vnd(self):
  self.assertEqual(amount('24,000.0000'),24000)
  with self.assertRaises(ValueError):amount('1,2.25')
 def test_business_semantics_and_release(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source,candidate=self.fixture(root)
   qa=acceptance(source,candidate)
   self.assertTrue(qa['accepted'],qa['errors'])
   self.assertEqual(qa['source_line_rows'],3)
   self.assertEqual(qa['daily_subtotal_rows'],1)
   self.assertEqual(qa['kpis']['invoice_count'],2)
   self.assertEqual(qa['kpis']['eligible_order_count'],1)
   self.assertEqual(qa['kpis']['eligible_revenue_vnd'],30000)
   self.assertEqual(qa['kpis']['base_units_sold'],30)
   rel=root/'release';res=publish(source,candidate,rel,'Synthetic reviewer')
   self.assertEqual(res['approval_status'],'PRODUCTION_APPROVED')
   with sqlite3.connect(rel/'dev_001.sqlite') as db:
    self.assertEqual(db.execute('SELECT COUNT(*) FROM family_order_facts').fetchone()[0],2)
    self.assertEqual(query_kpi(db,'invoice_revenue',start_date='2025-01-01',
      end_date='2025-01-01',as_of_date='2025-01-01'),30000)
    self.assertEqual(query_kpi(db,'eligible_order_count',start_date='2025-01-01',
      end_date='2025-01-01',as_of_date='2025-01-01'),1)
    self.assertEqual(query_kpi(db,'returned_order_count',start_date='2025-01-01',
      end_date='2025-01-01',as_of_date='2025-01-01'),1)
    self.assertEqual(query_kpi(db,'units_sold_base',start_date='2025-01-01',
      end_date='2025-01-01',as_of_date='2025-01-01'),30)
 def test_unrecognized_status_blocks(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source,candidate=self.fixture(root)
   from openpyxl import load_workbook
   wb=load_workbook(source);wb.active['H5']='Không rõ';wb.save(source)
   qa=acceptance(source,candidate)
   self.assertFalse(qa['accepted'])
   with self.assertRaises(ValueError):publish(source,candidate,root/'release','Reviewer')

if __name__=='__main__':unittest.main()
