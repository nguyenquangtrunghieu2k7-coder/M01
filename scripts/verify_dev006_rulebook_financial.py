#!/usr/bin/env python3
"""Rulebook-grounded dev_006 financial audit. Read-only; does not approve production."""
import argparse,json,sqlite3
from pathlib import Path

def assess(path):
 with sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro',uri=True) as db:
  count=lambda q:db.execute(q).fetchone()[0]
  checks={
   'duplicate_order_keys':"SELECT COUNT(*) FROM (SELECT IDCuaHang,MaHoaDon FROM don_hang GROUP BY 1,2 HAVING COUNT(*)>1)",
   'duplicate_product_keys':"SELECT COUNT(*) FROM (SELECT IDCuaHang,MaHangHoa FROM san_pham GROUP BY 1,2 HAVING COUNT(*)>1)",
   'lines_without_order':"SELECT COUNT(*) FROM chi_tiet_don l LEFT JOIN don_hang d USING(IDCuaHang,MaHoaDon) WHERE d.MaHoaDon IS NULL",
   'lines_without_product':"SELECT COUNT(*) FROM chi_tiet_don l LEFT JOIN san_pham p USING(IDCuaHang,MaHangHoa) WHERE p.MaHangHoa IS NULL",
   'payments_without_order':"SELECT COUNT(*) FROM thanh_toan p LEFT JOIN don_hang d USING(IDCuaHang,MaHoaDon) WHERE d.MaHoaDon IS NULL",
   'invalid_line_formula':"SELECT COUNT(*) FROM chi_tiet_don WHERE SL IS NULL OR GiaDonVi IS NULL OR ChietKhau IS NULL OR TriGia IS NULL OR SL*GiaDonVi-ChietKhau!=TriGia",
   'invalid_header_payment_formula':"SELECT COUNT(*) FROM don_hang WHERE TongTienHang IS NULL OR ChietKhau IS NULL OR PhiVanChuyen IS NULL OR ThueGTGT IS NULL OR TongThanhToan IS NULL OR TongTienHang-ChietKhau+PhiVanChuyen+ThueGTGT!=TongThanhToan",
   'returns_with_unexpected_order_status':"SELECT COUNT(*) FROM tra_hang t JOIN don_hang d USING(IDCuaHang,MaHoaDon) WHERE d.TinhTrang!='returned'",
   'unknown_order_status':"SELECT COUNT(*) FROM don_hang WHERE TinhTrang IS NULL OR TinhTrang NOT IN ('completed','cancelled','returned','shipping')"}
  checked={k:count(q) for k,q in checks.items()}
  differences=db.execute("""WITH lines AS (SELECT IDCuaHang,MaHoaDon,SUM(TriGia) total FROM chi_tiet_don GROUP BY 1,2)
   SELECT SUM(CASE WHEN lines.total!=d.TongTienHang THEN 1 ELSE 0 END),SUM(lines.total-d.TongTienHang)
   FROM don_hang d JOIN lines USING(IDCuaHang,MaHoaDon)""").fetchone()
  revenue=db.execute("""SELECT COUNT(DISTINCT d.IDCuaHang||'|'||d.MaHoaDon),SUM(l.TriGia)
   FROM chi_tiet_don l JOIN don_hang d USING(IDCuaHang,MaHoaDon)
   WHERE d.TinhTrang IN ('completed','shipping')""").fetchone()
  return {'source':'public_test/rulebook.md section 1; dev_006/README.md',
   'checks':checked,'financial_rulebook_checks_pass':all(v==0 for v in checked.values()),
   'header_line_difference':{'mismatching_orders':differences[0],'line_minus_header_vnd':differences[1],
    'classification':'INFORMATIONAL - different metric definitions; do not force equality'},
   'full_source_revenue_before_as_of_filter_vnd':revenue[1],'eligible_order_count_before_as_of_filter':revenue[0],
   'source_orders':count('SELECT COUNT(*) FROM don_hang'),
   'source_order_lines':count('SELECT COUNT(*) FROM chi_tiet_don'),
   'production_approved':False,
   'notes':'M03 must apply question as_of_date, exclude cancelled/returned orders, preserve delivery status; payment receipts are not revenue.'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--pos',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
 a=p.parse_args();report=assess(a.pos);a.output.parent.mkdir(parents=True,exist_ok=True)
 result=json.dumps(report,ensure_ascii=False,indent=2)+'\n';a.output.write_text(result,encoding='utf-8');print(result)
 if not report['financial_rulebook_checks_pass']:raise SystemExit(2)
if __name__=='__main__':main()
