#!/usr/bin/env python3
"""Fail-closed dev_006 pharmacy KPI parity: raw POS vs rebuilt M01 SQLite.

Checks each transaction line, its order join, status, date, and rulebook revenue
at total and monthly grain. No data or approval status is changed.
"""
import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

ELIGIBLE = ('completed', 'shipping')

def raw_rows(db):
    return db.execute("""
        SELECT l.IDCuaHang,l.MaHoaDon,l.SoThuTu,l.MaHangHoa,l.TriGia,
               h.TinhTrang,substr(h.ThoiGianLap,1,10)
        FROM chi_tiet_don l JOIN don_hang h
        ON h.IDCuaHang=l.IDCuaHang AND h.MaHoaDon=l.MaHoaDon
    """)

def verify(pos_path, mart_path):
    with sqlite3.connect(f'file:{Path(pos_path).resolve()}?mode=ro', uri=True) as source, \
         sqlite3.connect(f'file:{Path(mart_path).resolve()}?mode=ro', uri=True) as mart:
        problems=[]
        raw_count=source.execute('SELECT COUNT(*) FROM chi_tiet_don').fetchone()[0]
        mart_count=mart.execute("SELECT COUNT(*) FROM order_lines WHERE shop_id='dev_006'").fetchone()[0]
        if raw_count!=mart_count: problems.append(f'line count differs: {raw_count} vs {mart_count}')
        headers=mart.execute("SELECT document_uid,source_business_id,status_raw FROM orders WHERE shop_id='dev_006'").fetchall()
        header_by_doc={}
        for doc,bid,status in headers:
            if not doc or doc in header_by_doc:problems.append('missing or duplicate order document_uid');break
            header_by_doc[doc]=(bid,status)
        raw_agg=defaultdict(lambda:[0,0]); mart_agg=defaultdict(lambda:[0,0])
        raw_status=Counter(); mart_status=Counter()
        expected={}
        for sid,oid,seq,sku,amount,status,event_date in raw_rows(source):
            key=(str(sid),str(oid),str(seq),str(sku))
            if key in expected:problems.append('duplicate raw line identity: '+repr(key));continue
            expected[key]=(str(amount),status,event_date)
            raw_status[status]+=1
            if status in ELIGIBLE:
                k=event_date[:7] if event_date else 'MISSING_DATE'
                raw_agg[k][0]+=1;raw_agg[k][1]+=int(amount)
        observed=set()
        for doc,bid,date,amount,status,attrs in mart.execute("""
            SELECT document_uid,source_business_id,event_date,amount,status_raw,attributes_json
            FROM order_lines WHERE shop_id='dev_006'"""):
            attributes=json.loads(attrs)
            src=attributes.get('source_values') or {}
            key=(str(src.get('IDCuaHang')),str(bid),str(src.get('SoThuTu')),str(src.get('MaHangHoa')))
            if key in observed:problems.append('duplicate normalized line identity: '+repr(key));continue
            observed.add(key)
            record=expected.get(key)
            if record is None:
                problems.append('normalized line not found in source: '+repr(key));continue
            raw_amount,raw_st,raw_date=record
            if str(amount)!=raw_amount or status!=raw_st or date!=raw_date:
                problems.append('amount/status/date mismatch: '+repr(key))
            header=header_by_doc.get(doc)
            if header!=(bid,status):
                problems.append('order header JOIN mismatch: '+repr(key))
            mart_status[status]+=1
            if status in ELIGIBLE:
                month=date[:7] if date else 'MISSING_DATE'
                mart_agg[month][0]+=1
                try:mart_agg[month][1]+=int(Decimal(str(amount)))
                except (InvalidOperation,ValueError,TypeError):problems.append('invalid mart amount: '+repr(key))
        if len(observed)!=len(expected):problems.append(f'line identity coverage mismatch: source={len(expected)},mart={len(observed)}')
        if raw_status!=mart_status:problems.append('line status distribution differs')
        if dict(raw_agg)!=dict(mart_agg):problems.append('monthly eligible revenue differs')
        if 'MISSING_DATE' in raw_agg or 'MISSING_DATE' in mart_agg:problems.append('eligible lines missing date')
        report={
            'shop_id':'dev_006','source_order_lines':raw_count,'mart_order_lines':mart_count,
            'source_order_headers':source.execute('SELECT COUNT(*) FROM don_hang').fetchone()[0],
            'mart_order_headers':len(headers),
            'eligible_revenue_vnd':sum(v[1] for v in mart_agg.values()),
            'revenue_by_month':{k:{'line_count':v[0],'revenue_vnd':v[1]} for k,v in sorted(mart_agg.items())},
            'revenue_basis':'chi_tiet_don.TriGia, completed and shipping only; as_of_date cutoff to be applied by M03',
            'source_vs_mart_parity_pass':not problems,
            'failure_count':len(problems),'sample_failures':problems[:30],
            'production_approved':False
        }
        return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pos',type=Path,required=True)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args()
    report=verify(args.pos,args.db)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='revenue_by_month'},ensure_ascii=False,indent=2))
    if not report['source_vs_mart_parity_pass']:raise SystemExit(2)

if __name__=='__main__': main()
