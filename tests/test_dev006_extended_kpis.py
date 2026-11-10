"""Synthetic regressions for pharmacy POS KPI candidate semantics.

These tests do not grant KPI approval. Real-source parity is mandatory.
"""
import json
import sqlite3
import unittest
from scripts.dev006_extended_kpis import METRICS,calculate
from scripts.m03_consumer import NotApprovedForKPI,UnanswerableKPI

class PharmacyKpiTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        for table in ('orders','order_lines','payments','purchase_receipts',
                      'inventory_events','products','price_history','lots',
                      'lot_allocations','returns'):
            self.db.execute(f'CREATE TABLE {table}(shop_id TEXT,event_date TEXT,attributes_json TEXT,status_raw TEXT,amount TEXT)')
        self.db.execute('CREATE TABLE source_reference_records(shop_id TEXT,raw_json TEXT)')
        self.cat={'shop_id':'dev_006','approved_metrics':list(METRICS)}
        self.add('orders','2025-04-01',{'IDCuaHang':'dev_006','MaHoaDon':'A','ThoiGianLap':'2025-04-01 08:00:00','TinhTrang':'completed','TongThanhToan':1000,'PhuongThucTT':'debt','KenhBanHang':'store'})
        self.add('orders','2025-04-02',{'IDCuaHang':'dev_006','MaHoaDon':'B','ThoiGianLap':'2025-04-02 08:00:00','TinhTrang':'returned','TongThanhToan':500,'PhuongThucTT':'cash','KenhBanHang':'store'})
        self.add('orders','2025-04-03',{'IDCuaHang':'dev_006','MaHoaDon':'C','ThoiGianLap':'2025-04-03 08:00:00','TinhTrang':'shipping','TongThanhToan':300,'PhuongThucTT':'cod','KenhBanHang':'store'})
        self.add('order_lines','2025-04-01',{'MaHangHoa':'SP01','SL':2,'SLQuyDoi':20,'GiaVonLucBan':100,'TriGia':500},'completed',500)
        self.add('order_lines','2025-04-03',{'MaHangHoa':'SP02','SL':3,'SLQuyDoi':3,'GiaVonLucBan':50,'TriGia':300},'shipping',300)
        self.add('order_lines','2025-04-02',{'MaHangHoa':'SP01','SL':1,'SLQuyDoi':10,'GiaVonLucBan':100,'TriGia':500},'returned',500)
        self.add('payments','2025-04-02',{'IDCuaHang':'dev_006','MaHoaDon':'A','NgayGioThu':'2025-04-02 09:00:00','SoTienThu':'200đ','PhuongThuc':'cash'})
        self.add('payments','2025-04-03',{'IDCuaHang':'dev_006','MaHoaDon':'B','NgayGioThu':'2025-04-03 09:00:00','SoTienThu':'500đ','PhuongThuc':'transfer'})
        self.add('purchase_receipts','2025-04-01',{'MaPhieuNhap':'P1','MaNhaCungCap':'N1','TinhTrang':'received','TongGiaTriNhap':1000})
        self.add('inventory_events','2025-04-01',{'MaHangHoa':'SP01','MaGiaoDichKho':'MV1','NgayGioPhatSinh':'2025-04-01 10:00:00','TonCuoi':10})
        self.add('inventory_events','2025-04-03',{'MaHangHoa':'SP01','MaGiaoDichKho':'MV2','NgayGioPhatSinh':'2025-04-03 10:00:00','TonCuoi':0})
        self.add('inventory_events','2025-04-02',{'MaHangHoa':'SP02','MaGiaoDichKho':'MV3','NgayGioPhatSinh':'2025-04-02 10:00:00','TonCuoi':4})
        self.add('products',None,{'MaHangHoa':'SP01','GiaVonHang':50})
        self.add('products',None,{'MaHangHoa':'SP02','GiaVonHang':80})
        self.add('price_history','2025-04-01',{'MaHangHoa':'SP01','NgayApDung':'2025-04-01','GiaBanLe':150})
        self.add('price_history','2025-04-03',{'MaHangHoa':'SP01','NgayApDung':'2025-04-03','GiaBanLe':170})
        self.add('lots',None,{'MaLo':'L1','MaHangHoa':'SP01','MaPhieuNhap':'P1','HanSuDung':'2025-04-10','SLNhapQuyDoi':10,'DonGiaNhap':40})
        self.add('lot_allocations',None,{'MaLo':'L1','MaHoaDon':'A','SLQuyDoi':2,'SLTraQuyDoi':0})
        for raw in ({'MaHangHoa':'SP01','BanTheoDon':1,'ThanhPhanChinh':'Alpha + Beta'},
                    {'MaHangHoa':'SP02','BanTheoDon':0,'ThanhPhanChinh':'Beta'}):
            self.db.execute('INSERT INTO source_reference_records VALUES (?,?)',
                            ('dev_006',json.dumps({f'{i}:{key}':val for i,(key,val) in enumerate(raw.items())})))
        self.db.commit()
    def tearDown(self):self.db.close()
    def add(self,table,day,source,status=None,amount=None):
        self.db.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)',
                        ('dev_006',day,json.dumps({'source_values':source}),status,
                         str(amount) if amount is not None else None))
    def ask(self,metric,asof='2025-04-03',start='2025-04-01',end='2025-04-03',**kw):
        snapshot={'receivables_as_of','stock_units_as_of','inventory_value_as_of',
                  'stockout_product_count','expiry_lot_count','expiry_lot_cost_vnd','selling_price_as_of'}
        if metric in snapshot:start=end=None
        return calculate(self.db,self.cat,metric,as_of_date=asof,
                         start_date=start,end_date=end,**kw)
    def test_commerce(self):
        self.assertEqual(self.ask('order_count'),2)
        self.assertEqual(self.ask('cancel_rate'),0.0)
        self.assertEqual(self.ask('gross_profit_by_order_date'),450)
        self.assertEqual(self.ask('units_sold_base'),23)
        self.assertEqual(self.ask('prescription_revenue'),500)
        self.assertEqual(self.ask('ingredient_revenue',ingredient='Alpha + Beta'),500)
        self.assertEqual(self.ask('ingredient_revenue',ingredient='Beta'),300)
        self.assertEqual(self.ask('purchases_by_receipt_date'),1000)
        self.assertEqual(self.ask('supplier_purchase_value',product_id='N1'),1000)
        self.assertEqual(self.ask('returns_count'),1)
    def test_cash_and_debt(self):
        self.assertEqual(self.ask('cash_collected'),200)
        self.assertEqual(self.ask('cash_collected',payment_method='transfer'),500)
        self.assertEqual(self.ask('receivables_as_of',asof='2025-04-03'),800)
    def test_inventory_and_expiry(self):
        self.assertEqual(self.ask('stock_units_as_of',asof='2025-04-01',product_id='SP01'),10)
        self.assertEqual(self.ask('stock_units_as_of',product_id='SP01'),0)
        self.assertEqual(self.ask('inventory_value_as_of'),320)
        self.assertEqual(self.ask('stockout_product_count'),1)
        self.assertEqual(self.ask('selling_price_as_of',product_id='SP01'),170)
        self.assertEqual(self.ask('selling_price_as_of',asof='2025-04-02',product_id='SP01'),150)
        self.assertEqual(self.ask('expiry_lot_count',product_id=7),1)
        self.assertEqual(self.ask('expiry_lot_cost_vnd',product_id=7),320)
    def test_approval_and_coverage_fail_closed(self):
        with self.assertRaises(UnanswerableKPI):
            self.ask('order_count',asof='2025-05-01',start='2025-05-01',end='2025-05-31')
        with self.assertRaises(NotApprovedForKPI):
            calculate(self.db,{'shop_id':'dev_006','approved_metrics':[]},
                      'gross_profit_by_order_date',as_of_date='2025-04-03',
                      start_date='2025-04-01',end_date='2025-04-03')

if __name__=='__main__':unittest.main()
