"""Family-specific candidate ingestion and no-fabrication tests."""
import csv,json,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from openpyxl import Workbook
from scripts.rollout_13_families import inspect

ROOT=Path(__file__).resolve().parents[1]
def build(folder,shop,sources):
    contracts=folder/'contracts';contracts.mkdir(exist_ok=True)
    contract={'shop_id':shop,'family':{'dev_009':'invoice_summary_only',
                                      'dev_012':'motorcycle_service_ledger',
                                      'dev_013':'mother_baby_ledger'}[shop],
              'approval_status':'CANDIDATE_NOT_APPROVED',
              'official_kpis_approved':[],
              'source_manifest':[{'path':f'public_test/data/{shop}/{filename}',
                                  'object':obj,'format':fmt,'candidate_role':role}
                                 for filename,obj,fmt,role in sources]}
    (contracts/(shop+'.json')).write_text(json.dumps(contract))
    output=folder/'outputs'
    result=subprocess.run([sys.executable,str(ROOT/'build_9_shops.py'),
               '--data-root',str(folder),'--output',str(output),
               '--shops',shop,'--family-config-dir',str(contracts)],
               capture_output=True,text=True)
    if result.returncode:raise AssertionError(result.stdout+'\n'+result.stderr)
    return inspect(output/(shop+'.sqlite'),contract),output/(shop+'.sqlite')

class FamilyBuilderTests(unittest.TestCase):
    def test_invoice_summary_no_fake_skus(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'public_test/data/dev_009';source.mkdir(parents=True)
            with (source/'danh_sach_hoa_don.csv').open('w',newline='') as f:
                writer=csv.writer(f);writer.writerow(['Mã hóa đơn','Ngày tháng','TongTien','Trạng thái đơn'])
                writer.writerow(['A01','01/04/2025',10000,'completed'])
            qa,db=build(root,'dev_009',[('danh_sach_hoa_don.csv',
                    'danh_sach_hoa_don','csv','orders')])
            self.assertTrue(qa['structural_pass'],qa['failures'])
            self.assertEqual(qa['mart_row_counts']['order_lines'],0)
            self.assertEqual(qa['mart_row_counts']['orders'],1)
            self.assertFalse(qa['production_approved'])
    def test_repair_visits_not_invoiced_sales(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'public_test/data/dev_012';source.mkdir(parents=True)
            book=Workbook();ws=book.active;ws.title='T7-2025'
            ws.append(['Ngày','Xe','Làm gì','Thợ','Tiền','Ghi chú'])
            ws.append(['01/07/2025','Xe 1','Thay dầu','Thợ A',90000,''])
            book.save(source/'SoSuaXe.xlsx')
            qa,db=build(root,'dev_012',[('SoSuaXe.xlsx','T7-2025','xlsx','service_visits')])
            self.assertTrue(qa['structural_pass'],qa['failures'])
            self.assertEqual(qa['mart_row_counts']['service_visits'],1)
            self.assertEqual(qa['mart_row_counts']['orders'],0)
            self.assertEqual(qa['mart_row_counts']['order_lines'],0)
    def test_unsupported_family_roles_kept_in_source_only_table(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'public_test/data/dev_013';source.mkdir(parents=True)
            book=Workbook();ws=book.active;ws.title='KhuyenMai'
            ws.append(['Mã CT','Giảm giá']);ws.append(['CT01','10%'])
            book.save(source/'QuanLy.xlsx')
            qa,db=build(root,'dev_013',[('QuanLy.xlsx','KhuyenMai','xlsx','promotions')])
            self.assertTrue(qa['structural_pass'],qa['failures'])
            self.assertEqual(qa['source_reference_records'],1)
            self.assertEqual(qa['family_native_records'],1)
            self.assertEqual(qa['family_native_role_counts']['promotions'],1)
            self.assertEqual(qa['mart_row_counts']['orders'],0)
            with sqlite3.connect(db) as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM source_reference_records').fetchone()[0],1)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM staging_rows').fetchone()[0],1)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM family_native_records WHERE family_role=?',('promotions',)).fetchone()[0],1)
                self.assertEqual(c.execute('SELECT COUNT(*) FROM source_lineage').fetchone()[0],2)

if __name__=='__main__':unittest.main()
