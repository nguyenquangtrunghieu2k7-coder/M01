"""Fail-closed source-grain family roll-out tests (no fake official KPIs)."""
import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.family_inventory import contract,inventory
from scripts.build_family_staging import build

class FamilyStagingTests(unittest.TestCase):
    def test_summary_only_never_invents_order_lines(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            folder=root/'public_test/data/dev_009'
            folder.mkdir(parents=True)
            (folder/'README.md').write_text('One row per invoice; no SKU lines')
            with (folder/'danh_sach_hoa_don.csv').open('w',newline='',encoding='utf-8') as file:
                writer=csv.writer(file)
                writer.writerows([['Mã hóa đơn','TongTien'],['H001','12000'],
                                  ['H002','5000'],['','']])
            contracts=root/'contracts';contracts.mkdir()
            doc=contract('dev_009',folder)
            (contracts/'dev_009.json').write_text(json.dumps(doc,ensure_ascii=False))
            result=build('dev_009',root,contracts,root/'output')
            self.assertTrue(result['staging_integrity_pass'])
            self.assertEqual(result['source_objects'],1)
            self.assertEqual(result['staged_nonblank_rows'],3)
            self.assertEqual(result['source_role_counts'],{'orders':3})
            with sqlite3.connect(root/'output/dev_009.sqlite') as db:
                cat=json.loads(db.execute('SELECT catalog_json FROM family_catalog').fetchone()[0])
                self.assertEqual(cat['official_kpis_approved'],[])
                self.assertEqual(cat['business_marts_approved'],[])
                self.assertEqual(cat['approval_status'],'CANDIDATE_NOT_APPROVED')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM family_staging_rows').fetchone()[0],3)
            with self.assertRaises(FileExistsError):
                build('dev_009',root,contracts,root/'output')

    def test_shop_specific_joined_csv_source_roles(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            folder=root/'public_test/data/dev_010';folder.mkdir(parents=True)
            (folder/'README.md').write_text('Five linked CSV sources')
            for filename in ('don_hang','chi_tiet_don','thanh_toan','san_pham','khach_hang'):
                (folder/(filename+'.csv')).write_text('id,amount\n1,10\n',encoding='utf-8')
            contracts=root/'contracts';contracts.mkdir()
            doc=contract('dev_010',folder)
            self.assertEqual(len(doc['source_manifest']),5)
            self.assertEqual(set(x['candidate_role'] for x in doc['source_manifest']),
                             {'orders','order_lines','payments','products','customers'})
            (contracts/'dev_010.json').write_text(json.dumps(doc,ensure_ascii=False))
            result=build('dev_010',root,contracts,root/'output')
            self.assertEqual(result['source_objects'],5)
            self.assertEqual(result['staged_nonblank_rows'],10)
            self.assertTrue(result['staging_integrity_pass'])
            self.assertFalse(result['production_approved'])
            # An altered/missing source object must be blocked.
            (folder/'san_pham.csv').unlink()
            with self.assertRaises(ValueError):
                build('dev_010',root,contracts,root/'fresh_output')

    def test_service_visit_months_are_not_order_lines(self):
        import openpyxl
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'public_test/data/dev_012';folder.mkdir(parents=True)
            (folder/'README.md').write_text('One row = one service visit')
            wb=openpyxl.Workbook()
            ws=wb.active;ws.title='T7-2025'
            ws.append(['Ngày','Xe','Tiền']);ws.append(['2025-07-01','Xe A',100])
            ws2=wb.create_sheet('T8-2025')
            ws2.append(['Ngày','Xe','Tiền']);ws2.append(['2025-08-01','Xe B',0])
            wb.save(folder/'SoSuaXe.xlsx')
            wb2=openpyxl.Workbook();wb2.active.title='Thợ'
            wb2.active.append(['Thợ']);wb2.active.append(['Anh A'])
            wb2.save(folder/'DanhSachTho.xlsx')
            configs=root/'contracts';configs.mkdir()
            cfg=contract('dev_012',folder)
            self.assertEqual([x['candidate_role'] for x in cfg['source_manifest']].count('service_visits'),2)
            (configs/'dev_012.json').write_text(json.dumps(cfg,ensure_ascii=False))
            report=build('dev_012',root,configs,root/'output')
            self.assertTrue(report['staging_integrity_pass'])
            self.assertEqual(report['source_objects'],3)
            self.assertNotIn('order_lines',report['source_role_counts'])
            self.assertEqual(report['staged_nonblank_rows'],6)

    def test_all_shops_have_distinct_family_identity(self):
        from scripts.family_inventory import FAMILIES
        self.assertEqual(len(FAMILIES),13)
        self.assertNotIn('dev_006',FAMILIES)
        self.assertEqual(len(set(FAMILIES.values())),13)

if __name__=='__main__':unittest.main()
