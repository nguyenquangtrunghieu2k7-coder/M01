#!/usr/bin/env python3
"""Rulebook-grounded, read-only POS-to-mart acceptance for dev_006.

Identical physical rows in one order are export duplicates per rulebook §8.
Keep every source row in staging; only the first instance enters order_lines.
Never deduplicate by SKU/position alone. Verifies total, monthly, as-of-date
and non-overlapping interval KPI parity, with precise row provenance.
"""
import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ELIGIBLE = {'completed', 'shipping'}
CHECKPOINTS = ('2025-04-01','2025-04-30','2025-07-01',
               '2025-12-31','2026-01-01','2026-07-31','2026-08-08')

def verify(pos_path, mart_path):
    src=sqlite3.connect(f'file:{Path(pos_path).resolve()}?mode=ro',uri=True)
    mart=sqlite3.connect(f'file:{Path(mart_path).resolve()}?mode=ro',uri=True)
    errors=Counter()
    samples=[]
    def fail(reason, value):
        errors[reason]+=1
        if len(samples)<30:samples.append(f'{reason}: {value}')
    try:
        source_cols=[r[1] for r in src.execute('PRAGMA table_info(chi_tiet_don)')]
        if not source_cols:raise ValueError('Missing POS order-line columns')
        line_srcs=mart.execute("""SELECT source_id FROM raw_sources
            WHERE shop_id='dev_006' AND source_object='chi_tiet_don'""").fetchall()
        if len(line_srcs)!=1:fail('line_source_registration',str(line_srcs))
        source_id=line_srcs[0][0] if len(line_srcs)==1 else None
        headers={}
        for doc,bid,status,day in mart.execute("""SELECT document_uid,
            source_business_id,status_raw,event_date FROM orders
            WHERE shop_id='dev_006'"""):
            if not doc or doc in headers:fail('header_document_uid',repr(doc))
            headers[doc]=(str(bid),status,day)
        source_headers=src.execute('SELECT COUNT(*) FROM don_hang').fetchone()[0]
        if len(headers)!=source_headers:fail('order_count',(source_headers,len(headers)))

        # Read raw lines in same physical iteration order as SQLite builder.
        raw_values=src.execute('SELECT * FROM chi_tiet_don ORDER BY rowid')
        header_lookup={(str(s),str(o)):(status,str(when)[:10]) for s,o,status,when
                       in src.execute('SELECT IDCuaHang,MaHoaDon,TinhTrang,ThoiGianLap FROM don_hang')}
        expected={}
        duplicates={}
        seen={}
        raw_status=Counter()
        raw_month=defaultdict(lambda:[0,0])
        for rn,values in enumerate(raw_values,start=2):
            fingerprint=json.dumps({f'{i}:{name or "col"}':value for i,(name,value)
                 in enumerate(zip(source_cols,values))},ensure_ascii=False,
                 sort_keys=True,default=str)
            if fingerprint in seen:
                duplicates[rn]=seen[fingerprint]
                continue
            seen[fingerprint]=rn
            row=dict(zip(source_cols,values))
            status_day=header_lookup.get((str(row['IDCuaHang']),str(row['MaHoaDon'])))
            if status_day is None:
                fail('source_missing_order',rn);continue
            status,day=status_day
            expected[rn]=(row,status,day)
            raw_status[status]+=1
            if status in ELIGIBLE:
                if not day:fail('source_missing_date',rn)
                else:
                    amount=int(Decimal(str(row['TriGia'])))
                    month=day[:7]
                    raw_month[month][0]+=1;raw_month[month][1]+=amount

        count_src=src.execute('SELECT COUNT(*) FROM chi_tiet_don').fetchone()[0]
        staging_count=mart.execute("""SELECT COUNT(*) FROM staging_rows
            WHERE source_id=?""",(source_id,)).fetchone()[0] if source_id else None
        if staging_count!=count_src:fail('staging_row_count',(staging_count,count_src))
        mart_count=mart.execute("""SELECT COUNT(*) FROM order_lines
            WHERE shop_id='dev_006'""").fetchone()[0]
        if mart_count!=len(expected):fail('mart_count',(mart_count,len(expected)))
        annotated=mart.execute("""SELECT duplicate_source_row,retained_source_row
            FROM duplicate_source_rows WHERE shop_id='dev_006'
            AND entity_table='order_lines'""").fetchall()
        if len(annotated)!=len(duplicates) or dict(annotated)!=duplicates:
            fail('duplicate_audit_mismatch',(len(annotated),len(duplicates)))
        for rn,retained in duplicates.items():
            rec=mart.execute("""SELECT parsed_json FROM staging_rows
                WHERE source_id=? AND source_row=?""",(source_id,rn)).fetchone()
            if not rec:fail('missing_duplicate_staging',rn);continue
            parsed=json.loads(rec[0])
            if parsed.get('classification')!='EXACT_EXPORT_DUPLICATE' or parsed.get('retained_source_row')!=retained:
                fail('duplicate_staging_flag',rn)

        mart_month=defaultdict(lambda:[0,0])
        mart_status=Counter()
        observed=set()
        for source_id_row,rn,doc,bid,day,amount,status,attrs in mart.execute("""
            SELECT source_id,source_row,document_uid,source_business_id,
                   event_date,amount,status_raw,attributes_json FROM order_lines
            WHERE shop_id='dev_006'"""):
            if source_id_row!=source_id:fail('wrong_source_id',rn)
            if rn in observed:fail('duplicate_mart_source_row',rn);continue
            observed.add(rn)
            wanted=expected.get(rn)
            if wanted is None:fail('unexpected_mart_source_row',rn);continue
            row,exp_status,exp_day=wanted
            try:attributes=json.loads(attrs)
            except (ValueError,TypeError):fail('bad_attributes_json',rn);continue
            actual=attributes.get('source_values') or {}
            for col in source_cols:
                if actual.get(col)!=row[col]:
                    fail('altered_source_field',(rn,col))
            if str(bid)!=str(row['MaHoaDon']) or day!=exp_day or status!=exp_status or Decimal(str(amount))!=Decimal(str(row['TriGia'])):
                fail('incorrect_line_mapping',rn)
            if headers.get(doc)!=(str(bid),status,day):
                fail('order_join',rn)
            mart_status[status]+=1
            if status in ELIGIBLE:
                if not day:fail('mart_missing_date',rn)
                else:
                    mart_month[day[:7]][0]+=1
                    mart_month[day[:7]][1]+=int(Decimal(str(amount)))
        if observed!=set(expected):
            fail('unmatched_source_row_count',(len(observed),len(expected)))
        if mart_status!=raw_status:fail('status_mismatch',(dict(mart_status),dict(raw_status)))
        for month in sorted(set(raw_month)|set(mart_month)):
            if raw_month[month]!=mart_month[month]:
                fail('monthly_revenue',f'{month}: {raw_month[month]} vs {mart_month[month]}')
        # As-of queries are cumulative, but only on the source-observed date
        # range. Dates outside this range are not automatically zero.
        checkpoints={}
        for cutoff in CHECKPOINTS:
            raw_sum=sum(int(row['TriGia']) for row,status,day in expected.values()
                        if status in ELIGIBLE and day<=cutoff)
            mart_sum=mart.execute("""SELECT COALESCE(SUM(CAST(amount AS INTEGER)),0)
                FROM order_lines WHERE shop_id='dev_006'
                AND status_raw IN ('completed','shipping')
                AND event_date<=?""",(cutoff,)).fetchone()[0]
            checkpoints[cutoff]={'raw_vnd':raw_sum,'mart_vnd':mart_sum}
            if raw_sum!=mart_sum:fail('as_of_mismatch',cutoff)
        raw_total=sum(v[1] for v in raw_month.values())
        mart_total=sum(v[1] for v in mart_month.values())
        catalog_row=mart.execute('SELECT catalog_json FROM business_catalog').fetchall()
        if len(catalog_row)!=1:fail('catalog_count',len(catalog_row))
        else:
            catalog=json.loads(catalog_row[0][0])
            if catalog.get('row_counts',{}).get('order_lines')!=mart_count:
                fail('catalog_row_count',mart_count)
            if catalog.get('duplicate_row_counts',{}).get('order_lines',0)!=len(duplicates):
                fail('catalog_duplicate_count',len(duplicates))
        result={
            'shop_id':'dev_006','source_line_count':count_src,
            'staged_line_count':staging_count,'exact_duplicate_copies':len(duplicates),
            'expected_mart_lines':len(expected),'mart_lines':mart_count,
            'source_revenue_after_dedup_vnd':raw_total,
            'mart_revenue_after_dedup_vnd':mart_total,
            'as_of_checkpoints':checkpoints,
            'monthly_revenue_vnd':{month:values[1] for month,values in sorted(mart_month.items())},
            'acceptance_pass':not errors,'failure_count':sum(errors.values()),
            'failure_breakdown':dict(errors),'sample_failures':samples,
            'production_approved':False,
            'note':'This is dev006 M01-to-M03 SQL parity, NOT approval of all M03 question families.'
        }
        return result
    finally:
        src.close();mart.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pos',type=Path,required=True)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args()
    result=verify(a.pos,a.db)
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('monthly_revenue_vnd','as_of_checkpoints')},ensure_ascii=False,indent=2))
    if not result['acceptance_pass']:raise SystemExit(2)

if __name__=='__main__':main()
