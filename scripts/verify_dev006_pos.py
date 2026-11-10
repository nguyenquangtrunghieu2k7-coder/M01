#!/usr/bin/env python3
"""Read-only POS source reconciliation evidence for dev_006.

This is a diagnostic, NOT an authorization to change source totals.
No customer records or invoice IDs are written to the report.
"""
import argparse
import json
import sqlite3
from pathlib import Path

def assess(path):
    with sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro',uri=True) as db:
        checks={
          'source_orders': 'SELECT COUNT(*) FROM don_hang',
          'source_order_lines': 'SELECT COUNT(*) FROM chi_tiet_don',
          'source_products': 'SELECT COUNT(*) FROM san_pham',
          'duplicate_order_keys': 'SELECT COUNT(*) FROM (SELECT IDCuaHang,MaHoaDon FROM don_hang GROUP BY 1,2 HAVING COUNT(*)>1)',
          'duplicate_product_keys': 'SELECT COUNT(*) FROM (SELECT IDCuaHang,MaHangHoa FROM san_pham GROUP BY 1,2 HAVING COUNT(*)>1)',
          'lines_without_order': 'SELECT COUNT(*) FROM chi_tiet_don l LEFT JOIN don_hang h ON l.IDCuaHang=h.IDCuaHang AND l.MaHoaDon=h.MaHoaDon WHERE h.MaHoaDon IS NULL',
          'lines_without_product': 'SELECT COUNT(*) FROM chi_tiet_don l LEFT JOIN san_pham p ON l.IDCuaHang=p.IDCuaHang AND l.MaHangHoa=p.MaHangHoa WHERE p.MaHangHoa IS NULL',
          'order_line_total_mismatches': """SELECT COUNT(*) FROM don_hang h LEFT JOIN
               (SELECT IDCuaHang,MaHoaDon,SUM(TriGia) AS line_sum FROM chi_tiet_don GROUP BY IDCuaHang,MaHoaDon) l
               ON h.IDCuaHang=l.IDCuaHang AND h.MaHoaDon=l.MaHoaDon
               WHERE COALESCE(l.line_sum,0)<>COALESCE(h.TongTienHang,0)""",
          'header_merchandise_total': 'SELECT SUM(TongTienHang) FROM don_hang',
          'order_lines_total': 'SELECT SUM(TriGia) FROM chi_tiet_don',
        }
        values={key:db.execute(sql).fetchone()[0] for key,sql in checks.items()}
        values['join_ready']=not any(values[x] for x in
           ('duplicate_order_keys','duplicate_product_keys','lines_without_order','lines_without_product'))
        values['financially_reconciled']=values['join_ready'] and values['order_line_total_mismatches']==0
        values['notes']='Header merchandise totals and line TriGia are source fields; differences require business-semantic review, not automatic correction.'
        return values

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pos',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    result=assess(a.pos)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result['join_ready'] or not result['financially_reconciled']:
        raise SystemExit(2)

if __name__=='__main__':
    main()
