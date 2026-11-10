#!/usr/bin/env python3
"""Extend an EXISTING approved dev006 revenue release after independent KPI QA.

Preserves the prior release. Never modifies raw data or candidate databases.
Only issues a new explicitly authorized release when all checks pass.
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4

from dev006_extended_kpis import METRICS,calculate
from m03_consumer import open_business_dataset
from verify_dev006_extended_kpis import audit

def hashfile(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()

def issue(pos,prior,out,approver):
    if out.exists():raise ValueError('Refusing to overwrite release: '+str(out))
    if not pos.is_file():raise FileNotFoundError(pos)
    prior_db=prior/'dev_006.sqlite'
    prior_manifest=prior/'manifest.json'
    if not prior_db.is_file() or not prior_manifest.is_file():
        raise FileNotFoundError('Prior approved release database/manifest required')
    previous=json.loads(prior_manifest.read_text(encoding='utf-8'))
    if previous.get('shop_id')!='dev_006' or previous.get('approval_status')!='PRODUCTION_APPROVED':
        raise ValueError('Prior release not approved')
    if previous.get('source_sha256')!=hashfile(pos) or previous.get('database_sha256')!=hashfile(prior_db):
        raise ValueError('Source/approved database SHA256 do not match prior release')
    con,cat=open_business_dataset(prior_db)
    try:
        if set(cat.get('approved_metrics',[]))!={'revenue_by_order_date'}:
            raise ValueError('Expected original revenue-only approved release')
    finally:con.close()
    result=audit(pos,prior_db)
    if not result['pass']:
        raise ValueError('Extended KPI independent source parity FAILED: '+repr(result['failures'][:10]))
    out.mkdir(parents=True,exist_ok=False)
    report=out/'extended_qa_report.json'
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    new_db=out/'dev_006.sqlite'
    shutil.copy2(prior_db,new_db)
    now=datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(new_db) as db:
        cat=json.loads(db.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
        approved=['revenue_by_order_date',*METRICS]
        cat['approved_metrics']=approved
        cat['approval_status']='PRODUCTION_APPROVED'
        cat['approved_at_utc']=now
        cat['approved_by']=approver
        cat['approval_evidence']='extended_qa_report.json'
        cat['approved_family']='pharmacy_pos'
        cat['approved_metric_semantics']='public_test/rulebook.md and dev_006/README.md'
        db.execute('UPDATE business_catalog SET catalog_json=?',(json.dumps(cat,ensure_ascii=False),))
        db.commit()
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Extended release integrity failed')
    reader,reader_cat=open_business_dataset(new_db)
    try:
        end=reader.execute("SELECT MAX(event_date) FROM orders WHERE shop_id='dev_006'").fetchone()[0]
        start=reader.execute("SELECT MIN(event_date) FROM orders WHERE shop_id='dev_006'").fetchone()[0]
        gross=calculate(reader,reader_cat,'gross_profit_by_order_date',
                        as_of_date=end,start_date=start,end_date=end)
        stock=calculate(reader,reader_cat,'inventory_value_as_of',as_of_date=end)
        debt=calculate(reader,reader_cat,'receivables_as_of',as_of_date=end)
        if any(x<0 for x in (stock,debt)):
            raise ValueError('Invalid negative stock/debt totals in release smoke')
    finally:reader.close()
    source_config=json.loads((prior/'dev_006_config.json').read_text(encoding='utf-8'))
    if source_config.get('shop_id')!='dev_006' or len(source_config.get('sources',[]))!=17:
        raise ValueError('Prior release source mapping config is not 17/17')
    source_config['approved_metrics']=['revenue_by_order_date',*METRICS]
    source_config['approval_utc']=now
    source_config['approved_by']=approver
    source_config['extended_qa_evidence']='extended_qa_report.json'
    (out/'dev_006_config.json').write_text(
        json.dumps(source_config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    previous_schema=json.loads((prior/'schema_contract.json').read_text(encoding='utf-8'))
    previous_schema['approved_metrics']=['revenue_by_order_date',*METRICS]
    previous_schema['metric_qa_evidence']='extended_qa_report.json'
    (out/'schema_contract.json').write_text(json.dumps(previous_schema,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    manifest={
      'shop_id':'dev_006','family':'pharmacy_pos',
      'release_id':str(uuid4()),'source_dataset_version':cat['version_id'],
      'approval_status':'PRODUCTION_APPROVED','approved_by':approver,
      'approved_at_utc':now,'approved_metrics':['revenue_by_order_date',*METRICS],
      'source_sha256':hashfile(pos),'database_sha256':hashfile(new_db),
      'parent_release_database_sha256':previous['database_sha256'],
      'extended_independent_qa_pass':True,'extended_kpi_check_count':result['test_count'],
      'extended_kpi_checks_passed':result['passed_count'],
      'gross_profit_full_period_vnd':gross,
      'inventory_value_at_last_date_vnd':stock,
      'receivables_at_last_date_vnd':debt,
      'files':['dev_006.sqlite','dev_006_config.json',
               'schema_contract.json','extended_qa_report.json','manifest.json']
    }
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pos',required=True,type=Path)
    p.add_argument('--prior-release',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--approve',action='store_true')
    p.add_argument('--approved-by',required=True)
    a=p.parse_args()
    if not a.approve or not a.approved_by.strip():
        p.error('Explicit --approve and --approved-by required')
    try:
        print(json.dumps(issue(a.pos,a.prior_release,a.output,a.approved_by.strip()),ensure_ascii=False,indent=2))
    except Exception as e:
        print('EXTENDED RELEASE BLOCKED:',str(e),file=sys.stderr)
        raise SystemExit(2)

if __name__=='__main__':main()
