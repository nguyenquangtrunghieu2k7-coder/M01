"""Regression tests: candidate mappings must not silently discard invalid rows."""
import csv
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'build_9_shops.py'

class CandidateBuilderIntegrityTests(unittest.TestCase):
    def test_all_nonblank_records_are_staged_before_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shop = root / 'public_test' / 'data' / 'dev_007'
            shop.mkdir(parents=True)
            with (shop / 'chi_tiet_hoa_don.csv').open('w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['Mã bill', 'Tên hàng', 'Thành tiền', 'Ngày'])
                writer.writerow(['A01', 'Hàng A', '1000', '01/01/2025'])
                writer.writerow(['', 'Hàng B', '2000', '01/01/2025'])
                writer.writerow(['A02', '', '3000', '01/01/2025'])
                writer.writerow(['', '', '4000', '01/01/2025'])
                writer.writerow(['Mã bill', 'Tên hàng', 'Thành tiền', 'Ngày'])
            out = root / 'output'
            cmd = [sys.executable, str(SCRIPT), '--data-root', str(root), '--output', str(out), '--shops', 'dev_007']
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            dbpath = out / 'dev_007.sqlite'
            with sqlite3.connect(dbpath) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM staging_rows').fetchone()[0], 5)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM order_lines').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM validation_issues').fetchone()[0], 4)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM staging_rows s WHERE s.issue_count != (SELECT COUNT(*) FROM validation_issues v WHERE v.source_id=s.source_id AND v.source_row=s.source_row)').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM validation_issues v WHERE NOT EXISTS(SELECT 1 FROM staging_rows s WHERE s.source_id=v.source_id AND s.source_row=v.source_row)').fetchone()[0], 0)
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            second = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn('REFUSING TO OVERWRITE', second.stderr + second.stdout)
            with sqlite3.connect(dbpath) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM staging_rows').fetchone()[0], 5)

    def test_dev006_uses_verified_product_and_order_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shop = root / 'public_test' / 'data' / 'dev_006'
            shop.mkdir(parents=True)
            with sqlite3.connect(shop / 'pos.sqlite') as db:
                db.execute('CREATE TABLE san_pham(IDCuaHang TEXT, MaHangHoa TEXT, TenGoi TEXT)')
                db.execute('CREATE TABLE don_hang(IDCuaHang TEXT, MaHoaDon TEXT, ThoiGianLap TEXT, TinhTrang TEXT)')
                db.execute('CREATE TABLE chi_tiet_don(IDCuaHang TEXT, MaHoaDon TEXT, SoThuTu INTEGER, MaHangHoa TEXT, SL INTEGER, TriGia INTEGER)')
                db.execute("INSERT INTO san_pham VALUES('dev_006','SP01','Thuốc A')")
                db.execute("INSERT INTO don_hang VALUES('dev_006','ORD01','2025-04-01 06:00:39','completed')")
                db.execute("INSERT INTO chi_tiet_don VALUES('dev_006','ORD01',1,'SP01',2,5000)")
                db.execute("INSERT INTO chi_tiet_don VALUES('dev_006','ORD01',2,'SP99',1,2000)")
                db.commit()
            out = root / 'output'
            subprocess.run([sys.executable,str(SCRIPT),'--data-root',str(root),'--output',str(out),'--shops','dev_006'],check=True,capture_output=True,text=True)
            with sqlite3.connect(out/'dev_006.sqlite') as db:
                row=db.execute('SELECT source_business_id,display_name,event_date,status_raw,amount,attributes_json FROM order_lines').fetchone()
                self.assertEqual(row[:5],('ORD01','Thuốc A','2025-04-01','completed','5000'))
                import json
                self.assertEqual(json.loads(row[5])['item_sku'],'SP01')
                # Header and line must resolve to the same business document.
                header_doc=db.execute("SELECT document_uid FROM orders WHERE source_business_id='ORD01'").fetchone()[0]
                line_doc=db.execute("SELECT document_uid FROM order_lines WHERE source_business_id='ORD01'").fetchone()[0]
                self.assertEqual(header_doc,line_doc)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM order_lines').fetchone()[0],1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM validation_issues WHERE code='MISSING_ITEM'").fetchone()[0],1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM staging_rows').fetchone()[0],4)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM staging_rows s WHERE s.issue_count!=(SELECT COUNT(*) FROM validation_issues v WHERE v.source_id=s.source_id AND v.source_row=s.source_row)').fetchone()[0],0)

    def test_dev006_reference_objects_are_preserved_with_lineage(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shop = root / 'public_test' / 'data' / 'dev_006'
            shop.mkdir(parents=True)
            with sqlite3.connect(shop / 'pos.sqlite') as db:
                db.execute('CREATE TABLE san_pham(IDCuaHang TEXT,MaHangHoa TEXT,TenGoi TEXT)')
                db.execute('CREATE TABLE don_hang(IDCuaHang TEXT,MaHoaDon TEXT,ThoiGianLap TEXT,TinhTrang TEXT)')
                for obj, key in [('chi_nhanh','MaChiNhanh'), ('nha_cung_cap','MaNhaCungCap'),
                                 ('nhan_vien','MaNhanVien'), ('thong_tin_thuoc','MaHangHoa')]:
                    db.execute(f'CREATE TABLE {obj}(IDCuaHang TEXT,{key} TEXT,TenGoi TEXT)')
                    db.execute(f"INSERT INTO {obj} VALUES('dev_006','K1','Test')")
                db.commit()
            out = root / 'output'
            subprocess.run([sys.executable,str(SCRIPT),'--data-root',str(root),
                            '--output',str(out),'--shops','dev_006'],
                           check=True,capture_output=True,text=True)
            with sqlite3.connect(out/'dev_006.sqlite') as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM source_reference_records').fetchone()[0],4)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM staging_rows').fetchone()[0],4)
                # Both empty POS lookup tables are registered as raw sources too.
                self.assertEqual(db.execute('SELECT COUNT(*) FROM raw_sources').fetchone()[0],6)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM source_lineage WHERE entity_table='source_reference_records'").fetchone()[0],4)
                cat=json.loads(db.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
                self.assertEqual(cat['unmapped_objects'],[])
                self.assertEqual(sum(cat['reference_counts'].values()),4)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM validation_issues').fetchone()[0],0)

    def test_dev006_parity_preserves_repeated_business_line_values(self):
        """Two physical POS rows may have identical invoice, position and SKU."""
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            shop=root/'public_test'/'data'/'dev_006'
            shop.mkdir(parents=True)
            with sqlite3.connect(shop/'pos.sqlite') as db:
                db.execute('CREATE TABLE san_pham(IDCuaHang TEXT,MaHangHoa TEXT,TenGoi TEXT)')
                db.execute('CREATE TABLE don_hang(IDCuaHang TEXT,MaHoaDon TEXT,ThoiGianLap TEXT,TinhTrang TEXT)')
                db.execute('CREATE TABLE chi_tiet_don(IDCuaHang TEXT,MaHoaDon TEXT,SoThuTu INTEGER,MaHangHoa TEXT,SL INTEGER,TriGia INTEGER)')
                db.execute("INSERT INTO san_pham VALUES('dev_006','SP01','Thuốc A')")
                db.execute("INSERT INTO don_hang VALUES('dev_006','ORD01','2025-04-01 06:00:39','completed')")
                db.executemany("INSERT INTO chi_tiet_don VALUES('dev_006','ORD01',1,'SP01',1,5000)",[(),()])
                db.commit()
            out=root/'output'
            subprocess.run([sys.executable,str(SCRIPT),'--data-root',str(root),
                            '--output',str(out),'--shops','dev_006'],
                           check=True,capture_output=True,text=True)
            parity=Path(__file__).resolve().parents[1]/'scripts'/'verify_dev006_m03_parity.py'
            report=root/'parity.json'
            result=subprocess.run([sys.executable,str(parity),'--pos',str(shop/'pos.sqlite'),
                                   '--db',str(out/'dev_006.sqlite'),'--report',str(report)],
                                  capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            data=json.loads(report.read_text())
            self.assertTrue(data['source_vs_mart_parity_pass'],data['sample_failures'])
            self.assertEqual(data['source_order_lines'],2)
            self.assertEqual(data['mart_eligible_revenue_vnd'],10000)

if __name__ == '__main__':
    unittest.main()
