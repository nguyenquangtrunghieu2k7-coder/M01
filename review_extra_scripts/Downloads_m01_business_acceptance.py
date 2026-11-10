#!/usr/bin/env python3
"""Read-only, fail-closed business acceptance for the assembled M01 dataset.
Never deletes or rewrites data; a PASS is not equivalent to financial reconciliation.
"""
import argparse,csv,json,sqlite3,collections
from pathlib import Path
from decimal import Decimal,InvalidOperation

MARTS=['orders','order_lines','order_adjustments','payments','products','customers','purchase_lines','returns','inventory_events','inventory_snapshots','lot_allocations','expenses','deliveries','trade_ins']

def ident(x):return '"'+x.replace('"','""')+'"'
def cols(db,t):return {r[1] for r in db.execute('PRAGMA table_info('+ident(t)+')')}
def query(db,sql):return db.execute(sql).fetchone()[0]
def check(db,shop):
 tables={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 failures=[];warnings=[];counts={};metrics={}
 def fail(code,n,detail=''):
  if n:failures.append({'code':code,'count':n,'detail':detail})
 def warn(code,n,detail=''):
  if n:warnings.append({'code':code,'count':n,'detail':detail})
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
 fail('SQLITE_INTEGRITY',int(integrity!='ok'),integrity)
 if 'validation_issues' in tables:
  c=cols(db,'validation_issues');counts['validation_issues']=query(db,'SELECT COUNT(*) FROM validation_issues')
  if 'code' in c:
   by=dict(db.execute('SELECT code,COUNT(*) FROM validation_issues GROUP BY code'))
   for code,n in by.items():fail('UNRESOLVED_'+str(code),n,'Original validation issue still present; not automatically repaired')
  else:warn('UNINTERPRETABLE_VALIDATION',counts['validation_issues'])
 else:fail('MISSING_VALIDATION_TABLE',1)
 if 'staging_rows' in tables and 'raw_sources' in tables:
  cs=cols(db,'staging_rows');cr=cols(db,'raw_sources')
  counts['staging_rows']=query(db,'SELECT COUNT(*) FROM staging_rows')
  if {'source_id','source_row'}<=cs:
   n=query(db,'SELECT COUNT(*) FROM (SELECT source_id,source_row,COUNT(*) n FROM staging_rows GROUP BY source_id,source_row HAVING n>1)')
   fail('DUPLICATE_STAGING_SOURCE_ROW',n)
   if 'source_id' in cr:
    fail('STAGING_WITHOUT_SOURCE',query(db,'SELECT COUNT(*) FROM staging_rows s LEFT JOIN raw_sources r ON s.source_id=r.source_id WHERE r.source_id IS NULL'))
   if 'validation_issues' in tables and {'source_id','source_row'}<=cols(db,'validation_issues'):
    fail('VALIDATION_WITHOUT_STAGING',query(db,'SELECT COUNT(*) FROM validation_issues v WHERE NOT EXISTS(SELECT 1 FROM staging_rows s WHERE s.source_id=v.source_id AND s.source_row=v.source_row)'))
  if 'issue_count' in cs and 'validation_issues' in tables and {'source_id','source_row'}<=cols(db,'validation_issues'):
   n=query(db,'SELECT COUNT(*) FROM staging_rows s WHERE COALESCE(s.issue_count,0)<>(SELECT COUNT(*) FROM validation_issues v WHERE v.source_id=s.source_id AND v.source_row=s.source_row)')
   fail('STAGING_ISSUE_COUNT_MISMATCH',n)
 else:fail('MISSING_STAGING_OR_RAW_SOURCES',1)
 if 'source_reference_records' in tables:
  counts['source_reference_records']=query(db,'SELECT COUNT(*) FROM source_reference_records')
 for t in MARTS:
  if t not in tables:continue
  c=cols(db,t);counts[t]=query(db,'SELECT COUNT(*) FROM '+ident(t))
  if not counts[t]:continue
  if 'uid' in c:fail('NULL_ENTITY_UID_'+t,query(db,'SELECT COUNT(*) FROM '+ident(t)+' WHERE uid IS NULL OR TRIM(uid)=""'))
  if {'source_id','source_row'}<=c and 'staging_rows' in tables and {'source_id','source_row'}<=cols(db,'staging_rows'):
   fail('MART_WITHOUT_STAGING_'+t,query(db,'SELECT COUNT(*) FROM '+ident(t)+' m WHERE NOT EXISTS(SELECT 1 FROM staging_rows s WHERE s.source_id=m.source_id AND s.source_row=m.source_row)'))
  if 'shop_id' in c:fail('WRONG_SHOP_'+t,query(db,'SELECT COUNT(*) FROM '+ident(t)+' WHERE shop_id IS NULL OR shop_id<>\''+shop.replace("'","''")+'\''))
  if 'amount' in c:
   bad=0;examples=[]
   for uid,amount in db.execute('SELECT '+('uid' if 'uid' in c else 'rowid')+',amount FROM '+ident(t)+' WHERE amount IS NOT NULL AND TRIM(amount)<>""'):
    try:
     d=Decimal(str(amount));valid=d.is_finite()
    except (InvalidOperation,ValueError):valid=False
    if not valid:
     bad+=1
     if len(examples)<3:examples.append(str(uid))
   fail('INVALID_DECIMAL_'+t,bad,','.join(examples))
  if 'event_date' in c:
   fail('INVALID_ISO_DATE_'+t,query(db,'SELECT COUNT(*) FROM '+ident(t)+" WHERE event_date IS NOT NULL AND event_date<>'' AND (event_date NOT GLOB '????-??-??' OR date(event_date) IS NULL)"))
  if t in ('order_lines','purchase_lines') and 'source_business_id' in c:
   warn('MISSING_DOCUMENT_KEY_'+t,query(db,'SELECT COUNT(*) FROM '+ident(t)+" WHERE source_business_id IS NULL OR TRIM(source_business_id)=''"))
  if 'source_lineage' in tables and {'entity_table','entity_uid'}<=cols(db,'source_lineage') and 'uid' in c:
   fail('MART_WITHOUT_LINEAGE_'+t,query(db,'SELECT COUNT(*) FROM '+ident(t)+" m WHERE NOT EXISTS(SELECT 1 FROM source_lineage l WHERE l.entity_table='"+t+"' AND l.entity_uid=m.uid)"))
 if 'business_catalog' in tables:
  for (value,) in db.execute('SELECT catalog_json FROM business_catalog'):
   try:
    cat=json.loads(value)
    if cat.get('unmapped_objects'):fail('CATALOG_UNMAPPED_OBJECTS',len(cat['unmapped_objects']))
    if cat.get('approval_status') not in ('APPROVED','PRODUCTION_APPROVED'):warn('CATALOG_NOT_APPROVED',1)
   except (ValueError,TypeError):fail('INVALID_CATALOG_JSON',1)
 else:fail('MISSING_BUSINESS_CATALOG',1)
 return {'shop':shop,'status':'FAIL' if failures else 'STRUCTURAL_PASS_NOT_FINANCIAL_APPROVAL','counts':counts,'failures':failures,'warnings':warnings}

def main():
 p=argparse.ArgumentParser();p.add_argument('--dataset',required=True,help='assembled folder containing databases/');p.add_argument('--output',required=True);args=p.parse_args()
 folder=Path(args.dataset);dbdir=folder/'databases' if (folder/'databases').is_dir() else folder
 out=Path(args.output);out.mkdir(parents=True,exist_ok=True);results=[]
 for i in range(1,15):
  shop=f'dev_{i:03d}';path=dbdir/(shop+'.sqlite')
  if not path.exists():results.append({'shop':shop,'status':'FAIL','failures':[{'code':'MISSING_DATABASE','count':1,'detail':str(path)}],'warnings':[],'counts':{}});continue
  with sqlite3.connect('file:'+str(path.resolve())+'?mode=ro',uri=True) as db:
   results.append(check(db,shop))
  r=results[-1];print(r['status'],shop,'blocking_categories',len(r['failures']),'blocking_rows',sum(x['count'] for x in r['failures']),flush=True)
 (out/'business_acceptance.json').write_text(json.dumps({'approval':'BLOCKED' if any(r['failures'] for r in results) else 'REQUIRES_FINANCIAL_RECONCILIATION','results':results},ensure_ascii=False,indent=2))
 with (out/'business_issues.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(['shop','severity','code','count','detail'])
  for r in results:
   for severity,key in [('BLOCKER','failures'),('WARNING','warnings')]:
    for issue in r[key]:w.writerow([r['shop'],severity,issue['code'],issue['count'],issue.get('detail','')])
 print('REPORT',out/'business_issues.csv')
 print('ACCEPTANCE', 'BLOCKED' if any(r['failures'] for r in results) else 'STRUCTURAL_PASS_RECONCILIATION_PENDING')
if __name__=='__main__':main()
