#!/usr/bin/env python3
"""dev_007 fail-closed independent QA gate, then immutable SQLite/JSON release."""
import argparse,datetime,hashlib,json,os,pathlib,shutil,sqlite3,subprocess,sys,tempfile
EXPECTED={'orders':32022,'order_lines':119070,'catalog':61,'purchases':1731,'dedup_lineage':1381}
STATUSES={'completed':31310,'cancelled':630,'returned':68,'in_progress':14}
FILES={'chi_tiet_hoa_don.csv','danh_muc_hang.csv','chi_tiet_nhap_hang.csv'}
KPIS={
 'completed_order_count':{'grain':'order_id','source':'orders','filter':"status='completed'",'measure':'COUNT(*)','date_column':'order_date'},
 'completed_item_revenue':{'grain':'order_id','source':'orders','filter':"status='completed'",'measure':'SUM(items_total)','unit':'VND','date_column':'order_date','note':'Includes menu item and service-fee lines; excludes delivery fee'},
 'completed_order_revenue_excluding_delivery':{'grain':'order_id','source':'orders','filter':"status='completed'",'measure':'SUM(items_total-invoice_discount)','unit':'VND','date_column':'order_date','note':'Subtract invoice-level discount once, excluding delivery fee'},
 'cancelled_order_count':{'grain':'order_id','source':'orders','filter':"status='cancelled'",'measure':'COUNT(*)','date_column':'order_date'},
 'returned_order_count':{'grain':'order_id','source':'orders','filter':"status='returned'",'measure':'COUNT(*)','date_column':'order_date'},
}
def hashfile(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,v):path.write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);p.add_argument('--release',required=True);a=p.parse_args()
 src=pathlib.Path(a.source);d=pathlib.Path(a.candidate);release=pathlib.Path(a.release)
 for path in (d/'dev_007.sqlite',d/'manifest.json',d/'candidate_report.json'):
  if not path.is_file():raise SystemExit('Missing candidate: '+str(path))
 manifest=load(d/'manifest.json');candidate=load(d/'candidate_report.json')
 checks={};bad=[]
 def check(name,ok,details=None):
  checks[name]={'pass':bool(ok)}
  if details is not None:checks[name]['details']=details
  if not ok:bad.append(name)
 check('candidate_version',manifest.get('version')=='dev007-candidate-v1' and manifest.get('approval')=='CANDIDATE_NOT_APPROVED')
 check('source_file_set',set(manifest.get('source_sha256',{}))==FILES)
 for file in FILES:check('source_hash:'+file,(src/file).is_file() and hashfile(src/file)==manifest.get('source_sha256',{}).get(file))
 check('sqlite_hash',hashfile(d/'dev_007.sqlite')==manifest.get('sqlite_sha256'))
 check('no_mapping_issues',candidate.get('issues')=={})
 check('candidate_excluded',candidate.get('excluded')=={'daily_subtotal':616,'exact_duplicate_line':1381})
 check('candidate_integrity',candidate.get('sqlite_integrity')=='ok' and candidate.get('foreign_key_violations')==0)
 check('candidate_receipt_parity',candidate.get('purchase_receipt_mismatches')==0)
 check('candidate_counts',candidate.get('accepted')=={'catalog':61,'purchases':1731,'orders':32022,'order_lines':119070},candidate.get('accepted'))
 check('candidate_status',candidate.get('status_counts')==STATUSES)
 # Source-based QA always recomputed now. Candidate reports cannot self-approve.
 qa_proc=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('dev007_financial_qa.py')),'--source',str(src),'--candidate',str(d)],capture_output=True,text=True)
 check('qa_execution',qa_proc.returncode==0,qa_proc.stderr[-500:] if qa_proc.returncode else None)
 if qa_proc.returncode!=0:print(qa_proc.stderr[-1500:],file=sys.stderr)
 fin=load(d/'financial_qa_report.json') if qa_proc.returncode==0 else {}
 check('independent_qa_pass',fin.get('source_to_mart_pass') is True and fin.get('mismatches')=={})
 check('independent_counts',fin.get('orders')==32022 and fin.get('unique_lines')==119070 and fin.get('duplicates')==1381 and fin.get('duplicates_amount_vnd')==195342000)
 check('independent_status',fin.get('status_counts')==STATUSES)
 check('independent_source_hash',fin.get('source_hashes')==manifest.get('source_sha256'))
 db=sqlite3.connect('file:'+str((d/'dev_007.sqlite').resolve())+'?mode=ro',uri=True)
 counts={t:db.execute('SELECT COUNT(*) FROM '+('purchase_lines' if t=='purchases' else t)).fetchone()[0] for t in EXPECTED}
 check('db_counts',counts==EXPECTED,counts)
 check('sqlite_integrity',db.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
 check('foreign_keys',db.execute('PRAGMA foreign_key_check').fetchall()==[])
 check('db_status',dict(db.execute('SELECT status,COUNT(*) FROM orders GROUP BY status'))==STATUSES)
 check('no_null_money',db.execute('SELECT COUNT(*) FROM orders WHERE items_total IS NULL OR invoice_discount IS NULL OR customer_paid IS NULL OR outstanding_snapshot IS NULL OR delivery_fee_inferred IS NULL').fetchone()[0]==0)
 check('all_dates',db.execute("SELECT COUNT(*) FROM orders WHERE order_date IS NULL OR order_date NOT GLOB '????-??-??'").fetchone()[0]==0)
 check('item_invoice_total',db.execute('SELECT COUNT(*) FROM orders o WHERE items_total!=(SELECT SUM(line_total) FROM order_lines l WHERE l.order_id=o.order_id)').fetchone()[0]==0)
 check('line_price',db.execute('SELECT COUNT(*) FROM order_lines WHERE quantity*unit_price-line_discount!=line_total').fetchone()[0]==0)
 check('no_unexpected_delivery_fee',db.execute("SELECT COUNT(*) FROM orders WHERE delivery_fee_inferred!=(CASE WHEN status IN ('completed','in_progress') AND channel IN ('phone','zalo_oa') THEN 15000 ELSE 0 END)").fetchone()[0]==0)
 check('active_financial_equation',db.execute("SELECT COUNT(*) FROM orders WHERE status!='cancelled' AND customer_paid+outstanding_snapshot!=items_total-invoice_discount+delivery_fee_inferred").fetchone()[0]==0)
 check('cancelled_financial_equation',db.execute("SELECT COUNT(*) FROM orders WHERE status='cancelled' AND (customer_paid!=0 OR outstanding_snapshot!=0)").fetchone()[0]==0)
 check('service_fees_in_lines',db.execute("SELECT COUNT(*) FROM order_lines WHERE is_service_fee=1 AND (sku!='SP0061' OR product_name!='Phí phục vụ')").fetchone()[0]==0)
 check('source_accountability',sum(candidate.get('source_rows',{}).values())==121067+1731+61)
 check('duplicate_lineage_amount',db.execute('SELECT COALESCE(SUM(duplicate_amount),0) FROM dedup_lineage').fetchone()[0]==195342000)
 sums={status:{'orders':n,'item_revenue_vnd':gross,'invoice_discount_vnd':discount,'revenue_excluding_delivery_vnd':gross-discount,'inferred_delivery_fee_vnd':fee,'customer_paid_vnd':paid,'debt_snapshot_vnd':debt} for status,n,gross,discount,fee,paid,debt in db.execute('SELECT status,COUNT(*),SUM(items_total),SUM(invoice_discount),SUM(delivery_fee_inferred),SUM(customer_paid),SUM(outstanding_snapshot) FROM orders GROUP BY status')}
 schemas={name:[r[1] for r in db.execute('PRAGMA table_info("'+name+'")')] for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
 db.close()
 approved=not bad
 gate={'shop':'dev_007','version':'dev007-v1','approval':'PRODUCTION_APPROVED' if approved else 'BLOCKED','gate_pass':approved,'failed_checks':bad,'checks':checks,'status_totals':sums,'source_sha256':manifest['source_sha256'],'sqlite_sha256':manifest['sqlite_sha256'],'kpi_contract':KPIS if approved else {},'unsupported':['historical_debt_series','historical_inventory','net_profit','delivery_fee_as_menu_revenue','refund_cashflow'],'notes':['Service fee is already a sales line: never add separately.','Delivery fees are inferred from source payment arithmetic and excluded from item revenue.','Returned orders keep original paid record but are excluded entirely from completed revenue.']}
 write(d/'release_gate_report.json',gate)
 if not approved:
  print(json.dumps({'approval':'BLOCKED','gate_pass':False,'failed_checks':bad,'candidate':str(d)},ensure_ascii=False,indent=2))
  sys.exit(1)
 if release.exists():raise SystemExit('Release already exists. Refusing to overwrite: '+str(release))
 release.parent.mkdir(parents=True,exist_ok=True)
 staging=pathlib.Path(tempfile.mkdtemp(prefix='.dev007_release_',dir=release.parent))
 try:
  for src_name,dst_name in (('dev_007.sqlite','dev_007.sqlite'),('candidate_report.json','qa_report.json'),('financial_qa_report.json','financial_qa_report.json'),('release_gate_report.json','release_gate_report.json')):
   shutil.copy2(d/src_name,staging/dst_name)
  write(staging/'schema_contract.json',{'approval':'PRODUCTION_APPROVED','version':'dev007-v1','shop':'dev_007','tables':schemas,'kpi_contract':KPIS,'unsupported':gate['unsupported']})
  files={f.name:{'sha256':hashfile(f),'bytes':f.stat().st_size} for f in staging.iterdir()}
  write(staging/'manifest.json',{'approval':'PRODUCTION_APPROVED','gate_pass':True,'shop':'dev_007','version':'dev007-v1','source_sha256':manifest['source_sha256'],'files':files,'kpis_supported':list(KPIS),'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
  os.rename(staging,release)
 except BaseException:
  shutil.rmtree(staging,ignore_errors=True);raise
 print(json.dumps({'approval':'PRODUCTION_APPROVED','gate_pass':True,'failed_checks':[],'supported_kpis':list(KPIS),'status_totals':sums,'release_dir':str(release),'release_files':sorted(x.name for x in release.iterdir())},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
