#!/usr/bin/env python3
"""Read-only dev_006 source-to-mart parity, using stable SOURCE ROW provenance.

Do not deduplicate by (order, position, SKU): source can contain repeated
business values representing different physical order lines. Rebuilding the
mart is not needed to run this audit.
"""
import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

ELIGIBLE = {'completed', 'shipping'}

def audit(pos_path, mart_path):
    with sqlite3.connect(f'file:{Path(pos_path).resolve()}?mode=ro', uri=True) as source, \
         sqlite3.connect(f'file:{Path(mart_path).resolve()}?mode=ro', uri=True) as mart:
        sample_failures=[]
        failures=Counter()
        def error(code, detail):
            failures[code]+=1
            if len(sample_failures)<30:
                sample_failures.append(f'{code}: {detail}')
        raw_count=source.execute('SELECT COUNT(*) FROM chi_tiet_don').fetchone()[0]
        mart_count=mart.execute("SELECT COUNT(*) FROM order_lines WHERE shop_id='dev_006'").fetchone()[0]
        if raw_count!=mart_count:
            error('line_count_mismatch',f'raw={raw_count}, mart={mart_count}')
        source_header_count=source.execute('SELECT COUNT(*) FROM don_hang').fetchone()[0]
        header_by_doc={}
        for doc,bid,status in mart.execute(
            "SELECT document_uid,source_business_id,status_raw FROM orders WHERE shop_id='dev_006'"):
            if not doc or doc in header_by_doc:
                error('duplicate_or_missing_header_uid',repr(doc))
            header_by_doc[doc]=(str(bid),status)
        if len(header_by_doc)!=source_header_count:
            error('header_count_mismatch',f'raw={source_header_count},mart={len(header_by_doc)}')

        sources=mart.execute("""
            SELECT source_id FROM raw_sources
            WHERE shop_id='dev_006' AND source_object='chi_tiet_don'
        """).fetchall()
        if len(sources)!=1:
            error('raw_source_registration',f'expected one chi_tiet_don source, found {len(sources)}')
        line_source_id=sources[0][0] if len(sources)==1 else None

        raw_agg=defaultdict(lambda:[0,0])
        mart_agg=defaultdict(lambda:[0,0])
        raw_status=Counter();mart_status=Counter()
        # The M01 SQLite importer numbers header as row 1 and records 2..N+1.
        # Its SELECT * iteration follows SQLite's rowid scan of this POS table.
        # Use that identical physical ordering and include EVERY source line.
        expected={}
        raw_sql="""SELECT l.IDCuaHang,l.MaHoaDon,l.SoThuTu,l.MaHangHoa,
                          l.TriGia,d.TinhTrang,substr(d.ThoiGianLap,1,10)
                   FROM chi_tiet_don l LEFT JOIN don_hang d
                   ON d.IDCuaHang=l.IDCuaHang AND d.MaHoaDon=l.MaHoaDon
                   ORDER BY l.rowid"""
        for rownum, (sid,oid,seq,sku,amount,status,event_date) in enumerate(
                source.execute(raw_sql),start=2):
            expected[rownum]=(str(sid),str(oid),str(seq),str(sku),str(amount),status,event_date)
            raw_status[status]+=1
            if status in ELIGIBLE:
                month=event_date[:7] if event_date else 'MISSING_DATE'
                raw_agg[month][0]+=1
                try:raw_agg[month][1]+=int(Decimal(str(amount)))
                except (InvalidOperation,TypeError,ValueError):
                    error('raw_amount_invalid',f'source_row={rownum}')
            elif status is None:
                error('missing_order_join',f'source_row={rownum}')

        observed=set()
        mart_sql="""SELECT source_id,source_row,document_uid,source_business_id,
                           event_date,amount,status_raw,attributes_json
                    FROM order_lines WHERE shop_id='dev_006'"""
        for source_id,source_row,doc,bid,date,amount,status,attrs in mart.execute(mart_sql):
            if line_source_id is not None and source_id!=line_source_id:
                error('unexpected_line_source_id',f'source_row={source_row}')
            if source_row in observed:
                error('duplicate_source_row',f'source_row={source_row}')
                continue
            observed.add(source_row)
            record=expected.get(source_row)
            if record is None:
                error('unmatched_source_row',f'source_row={source_row}')
                continue
            sid,oid,seq,sku,raw_amount,raw_status_value,raw_date=record
            try:
                src=(json.loads(attrs).get('source_values') or {})
            except (TypeError,ValueError):
                error('invalid_attributes_json',f'source_row={source_row}')
                continue
            if (str(src.get('IDCuaHang')),str(bid),str(src.get('SoThuTu')),
                    str(src.get('MaHangHoa'))) != (sid,oid,seq,sku):
                error('source_fields_mismatch',f'source_row={source_row}')
            try:
                amount_matches=Decimal(str(amount))==Decimal(raw_amount)
            except (InvalidOperation,TypeError,ValueError):
                amount_matches=False
            if not amount_matches or status!=raw_status_value or date!=raw_date:
                error('value_status_date_mismatch',f'source_row={source_row}')
            if header_by_doc.get(doc)!=(oid,status):
                error('header_join_mismatch',f'source_row={source_row}')
            mart_status[status]+=1
            if status in ELIGIBLE:
                month=date[:7] if date else 'MISSING_DATE'
                mart_agg[month][0]+=1
                try:mart_agg[month][1]+=int(Decimal(str(amount)))
                except (InvalidOperation,TypeError,ValueError):
                    error('mart_amount_invalid',f'source_row={source_row}')
        if len(observed)!=len(expected):
            error('source_row_coverage_mismatch',f'raw={len(expected)}, mart={len(observed)}')
        if raw_status!=mart_status:
            error('status_distribution_mismatch',f'raw={dict(raw_status)}, mart={dict(mart_status)}')
        if dict(raw_agg)!=dict(mart_agg):
            for month in sorted(set(raw_agg)|set(mart_agg)):
                if raw_agg[month]!=mart_agg[month]:
                    error('monthly_revenue_mismatch',f'{month}: raw={raw_agg[month]},mart={mart_agg[month]}')
        if 'MISSING_DATE' in raw_agg or 'MISSING_DATE' in mart_agg:
            error('eligible_line_missing_date','eligible line without valid date')
        return {
            'shop_id':'dev_006','source_order_lines':raw_count,'mart_order_lines':mart_count,
            'source_order_headers':source_header_count,'mart_order_headers':len(header_by_doc),
            'source_eligible_revenue_vnd':sum(v[1] for v in raw_agg.values()),
            'mart_eligible_revenue_vnd':sum(v[1] for v in mart_agg.values()),
            'revenue_by_month':{k:{'source_line_count':raw_agg[k][0],
                        'mart_line_count':mart_agg[k][0],
                        'source_revenue_vnd':raw_agg[k][1],
                        'mart_revenue_vnd':mart_agg[k][1]}
                        for k in sorted(set(raw_agg)|set(mart_agg))},
            'parity_method':'source_id + source_row, preserving repeated order-line values',
            'source_vs_mart_parity_pass':not failures,
            'failure_count':sum(failures.values()),'failure_breakdown':dict(failures),
            'sample_failures':sample_failures,'production_approved':False,
            'note':'Source-to-mart parity is not full M03 question/as_of_date acceptance.'
        }

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pos',required=True,type=Path)
    p.add_argument('--db',required=True,type=Path)
    p.add_argument('--report',required=True,type=Path)
    args=p.parse_args()
    result=audit(args.pos,args.db)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='revenue_by_month'},ensure_ascii=False,indent=2))
    if not result['source_vs_mart_parity_pass']:
        raise SystemExit(2)

if __name__=='__main__':main()
