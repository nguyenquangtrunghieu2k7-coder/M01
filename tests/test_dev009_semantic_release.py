"""Source-based regression of dev009 summary-only production acceptance."""
import csv,json,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from scripts.dev009_semantic_release import acceptance,publish,source_rows,money,query_kpi

ROOT=Path(__file__).resolve().parents[1]
HEADERS=['Ngày tháng','Trạng thái đơn','TongTien','Mã hóa đơn','Nợ','Đã thu','Đối tác','Giá trị hàng']
ROWS=[
 ['01/01/2025','Xong','1,150','A01','150','1000','Khách A','1,200'],
 ['2025-01-01 00:00:00','hủy đơn','900','A02','0','0','Khách B','900'],
 ['01/01/2025','Xong','1,150','A01','150','1000','Khách A','1,200'],
 ['','','2,050','','0','1000','Tổng ngày 01/01','2100']
]
class Dev009Semantics(unittest.TestCase):
 def test_money_rejects_ambiguous(self):
  self.assertEqual(money('1,200'),1200)
  self.assertEqual(money('1.200'),1200)
  self.assertEqual(money('500'),500)
  for value in ('1,2','1.20.00','1,2tr',''):
   with self.assertRaises(ValueError):money(value)
 def fixture(self,root,rows=ROWS):
  folder=root/'public_test/data/dev_009';folder.mkdir(parents=True)
  source=folder/'danh_sach_hoa_don.csv'
  with source.open('w',encoding='utf-8-sig',newline='') as stream:
   out=csv.writer(stream);out.writerow(HEADERS);out.writerows(rows)
  contracts=root/'family_contracts';contracts.mkdir()
  (contracts/'dev_009.json').write_text(json.dumps({
   'shop_id':'dev_009','family':'invoice_summary_only',
   'approval_status':'CANDIDATE_NOT_APPROVED','official_kpis_approved':[],
   'source_manifest':[{'path':'public_test/data/dev_009/danh_sach_hoa_don.csv',
     'object':'danh_sach_hoa_don','format':'csv','candidate_role':'orders'}]}))
  output=root/'candidate';output.mkdir()
  proc=subprocess.run([sys.executable,str(ROOT/'build_9_shops.py'),
    '--data-root',str(root),'--output',str(output),'--shops','dev_009',
    '--family-config-dir',str(contracts)],capture_output=True,text=True)
  self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
  return source,output/'dev_009.sqlite'
 def test_summary_duplicates_and_scoped_release(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source,candidate=self.fixture(root)
   before=source.read_bytes()
   qa=acceptance(source,candidate)
   self.assertTrue(qa['accepted'],qa['errors'])
   self.assertEqual(qa['unique_invoice_count'],2)
   self.assertEqual(qa['identical_export_duplicate_copies'],1)
   self.assertEqual(qa['daily_subtotals_not_orders'],1)
   self.assertEqual(qa['kpis']['eligible_revenue_vnd'],1200)
   release_dir=root/'release'
   manifest=publish(source,candidate,release_dir,'Synthetic test owner')
   self.assertEqual(manifest['approval_status'],'PRODUCTION_APPROVED')
   self.assertEqual(source.read_bytes(),before)
   with sqlite3.connect(candidate) as c:
    self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],3)
   with sqlite3.connect(release_dir/'dev_009.sqlite') as c:
    self.assertEqual(c.execute('SELECT COUNT(*) FROM staging_rows').fetchone()[0],4)
    self.assertEqual(c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],2)
    self.assertEqual(c.execute('SELECT COUNT(*) FROM family_invoice_facts').fetchone()[0],2)
    self.assertEqual(query_kpi(c,'invoice_revenue',
       start_date='2025-01-01',end_date='2025-01-01',as_of_date='2025-01-01'),1200)
    self.assertEqual(query_kpi(c,'eligible_order_count',
       start_date='2025-01-01',end_date='2025-01-01',as_of_date='2025-01-01'),1)
    self.assertEqual(query_kpi(c,'cancel_rate',
       start_date='2025-01-01',end_date='2025-01-01',as_of_date='2025-01-01'),50.0)
    self.assertEqual(query_kpi(c,'current_debt_snapshot',as_of_date='2025-01-01'),150)
    with self.assertRaises(ValueError):
     query_kpi(c,'current_debt_snapshot',as_of_date='2025-01-02')
    with self.assertRaises(ValueError):
     query_kpi(c,'invoice_revenue',
       start_date='2024-01-01',end_date='2024-01-31',as_of_date='2025-01-01')
    with self.assertRaises(ValueError):
     query_kpi(c,'product_sales',start_date='2025-01-01',
       end_date='2025-01-01',as_of_date='2025-01-01')
 def test_conflicting_duplicate_blocks(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   rows=ROWS[:2]+[
     ['01/01/2025','Xong','999','A01','0','999','Khách A','999']]
   source,candidate=self.fixture(root,rows)
   qa=acceptance(source,candidate)
   self.assertFalse(qa['accepted'])
   self.assertTrue(any('conflicting' in e for e in qa['errors']))
   with self.assertRaises(ValueError):publish(source,candidate,root/'release','Reviewer')
   self.assertFalse((root/'release').exists())

if __name__=='__main__':unittest.main()
