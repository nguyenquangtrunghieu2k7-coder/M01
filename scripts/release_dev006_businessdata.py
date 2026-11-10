#!/usr/bin/env python3
"""Publish dev006 BusinessData only after evidence gates and human approval.

Input DB is never mutated. This release explicitly approves verified
source/mart revenue semantics, not untested KPIs of other shops.
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from verify_dev006_coverage import verify as coverage
from verify_dev006_rulebook_financial import assess as financial
from verify_dev006_m03_parity import verify as parity

def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
    return h.hexdigest()

def publish(pos,db,out,approver):
    if out.exists():raise ValueError('Refusing to overwrite existing release directory')
    if not pos.is_file() or not db.is_file():raise FileNotFoundError('Missing POS or candidate SQLite')
    checks={'coverage':coverage(pos,db),'financial':financial(pos),'parity':parity(pos,db)}
    failures=[]
    if not checks['coverage']['coverage_pass']:failures.append('source coverage')
    if not checks['financial']['financial_rulebook_checks_pass']:failures.append('source financial formulas')
    if not checks['parity']['acceptance_pass']:failures.append('source-mart and as-of parity')
    with sqlite3.connect(f'file:{db.resolve()}?mode=ro',uri=True) as c:
        catalog_rows=c.execute('SELECT catalog_json FROM business_catalog').fetchall()
        if len(catalog_rows)!=1:raise ValueError('Expected one catalog')
        catalog=json.loads(catalog_rows[0][0])
        if catalog['shop_id']!='dev_006':failures.append('wrong shop')
        if catalog.get('approval_status')!='CANDIDATE_NOT_APPROVED':failures.append('input must be candidate')
        if catalog.get('validation_status')!='PROVISIONAL_NOT_FOR_PRODUCTION':failures.append('input must be provisional')
        if catalog.get('unmapped_objects'):failures.append('unmapped source objects')
        if catalog.get('source_objects_processed')!=17:failures.append('source coverage count !=17')
        if sum(catalog.get('reference_counts',{}).values())!=89:failures.append('reference rows !=89')
        if catalog.get('duplicate_row_counts',{}).get('order_lines',0)!=checks['parity']['exact_duplicate_copies']:
            failures.append('missing exact duplicate evidence')
        if c.execute('SELECT COUNT(*) FROM validation_issues').fetchone()[0]:failures.append('validation issues present')
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':failures.append('SQLite integrity')
        for table,count in catalog.get('row_counts',{}).items():
            actual=c.execute(f'SELECT COUNT(*) FROM "{table}" WHERE shop_id=?',('dev_006',)).fetchone()[0]
            if actual!=count:failures.append(f'{table}: catalog row count mismatch')
    if failures:
        raise ValueError('RELEASE BLOCKED: '+', '.join(failures))
    out.mkdir(parents=True)
    (out/'qa_report.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    derived=out/'dev_006.sqlite'
    shutil.copy2(db,derived)
    now=datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(derived) as c:
        cat=json.loads(c.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
        cat.update({'validation_status':'APPROVED','approval_status':'PRODUCTION_APPROVED',
                    'approved_by':approver,'approved_at_utc':now,
                    'approved_metrics':['revenue_by_order_date'],
                    'approval_evidence':'qa_report.json',
                    'notes':'Verified dev006 revenue metric only; other M03 KPI families require separate acceptance.'})
        c.execute('UPDATE business_catalog SET catalog_json=?',(json.dumps(cat,ensure_ascii=False),))
        c.execute('UPDATE dataset_versions SET status=? WHERE shop_id=? AND version_id=?',
                  ('APPROVED','dev_006',cat['version_id']))
        c.commit()
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Released SQLite integrity failed')
    # Test actual production-mode M03 opening and counts.
    from m03_consumer import open_business_dataset, query_entity_count, query_shop_revenue
    con,cat=open_business_dataset(derived)
    try:
        if query_entity_count(con,cat,'order_lines')!=checks['parity']['mart_lines']:
            raise ValueError('M03 row count mismatch')
        revenue=con.execute("""SELECT COALESCE(SUM(CAST(amount AS INTEGER)),0)
           FROM order_lines WHERE shop_id=? AND status_raw IN ('completed','shipping')""",
           ('dev_006',)).fetchone()[0]
        if revenue!=checks['parity']['mart_revenue_after_dedup_vnd']:
            raise ValueError('M03 revenue smoke mismatch')
        bounds=con.execute("SELECT MIN(event_date),MAX(event_date) FROM orders WHERE shop_id='dev_006'").fetchone()
        from_reader=query_shop_revenue(con,cat,start_date=bounds[0],
                                      end_date=bounds[1],as_of_date=bounds[1])
        if from_reader!=revenue:
            raise ValueError('M03 public KPI interface does not agree with accepted revenue')
    finally:con.close()
    with sqlite3.connect(derived) as c:
        schema={table:[col[1] for col in c.execute('PRAGMA table_info("'+table+'")')]
              for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    (out/'schema_contract.json').write_text(json.dumps({
        'shop_id':'dev_006','family':'pharmacy_pos',
        'approved_metrics':['revenue_by_order_date'],
        'rulebook':'public_test/rulebook.md',
        'source_readme':'public_test/data/dev_006/README.md',
        'tables':schema},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    manifest={'shop_id':'dev_006','family':'pharmacy_pos',
       'approval_status':'PRODUCTION_APPROVED','approved_by':approver,
       'approved_at_utc':now,'version_id':cat['version_id'],
       'approved_metrics':['revenue_by_order_date'],
       'source_sha256':sha256(pos),'database_sha256':sha256(derived),
       'revenue_after_rulebook_dedup_vnd':revenue,
       'duplicate_rows_removed_from_mart':checks['parity']['exact_duplicate_copies'],
       'source_rows_still_staged':checks['parity']['staged_line_count'],
       'm03_reader_smoke_pass':True,
       'files':['dev_006.sqlite','qa_report.json','schema_contract.json','manifest.json']}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pos',type=Path,required=True)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--approve',action='store_true',help='Explicitly authorize production release if all QA gates pass')
    p.add_argument('--approved-by',required=True,help='Human reviewer/owner')
    a=p.parse_args()
    if not a.approve or not a.approved_by.strip():
        p.error('Release requires --approve and nonempty --approved-by')
    try:
        print(json.dumps(publish(a.pos,a.db,a.output,a.approved_by.strip()),ensure_ascii=False,indent=2))
    except Exception as ex:
        print('RELEASE FAILED:',ex,file=sys.stderr)
        raise SystemExit(2)

if __name__=='__main__':main()
