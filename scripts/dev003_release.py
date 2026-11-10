#!/usr/bin/env python3
"""Fail-closed dev003 release gate. Rerun independent QA before production delivery."""
import argparse,datetime,hashlib,json,os,pathlib,shutil,sqlite3,subprocess,sys,tempfile
EXPECTED={'orders':62839,'order_lines':100210,'exact_duplicate_lines':1994,'receipts':62580,'products':50,'customers':220,'unit_conversions':2,'price_history':79}
STATUS={'completed':61254,'cancelled':1296,'returned':261,'shipping':28}
KPIS={
 'completed_order_count':{'grain':'order_id','source':'orders','date':'order_date','filter':"status='completed'",'measure':'COUNT(*)'},
 'completed_item_revenue':{'grain':'order_id','source':'orders','date':'order_date','filter':"status='completed'",'measure':'SUM(item_total)','unit':'VND'},
 'completed_order_revenue_excluding_shipping':{'grain':'order_id','source':'orders','date':'order_date','filter':"status='completed'",'measure':'SUM(item_total-discount)','unit':'VND'},
 'cancelled_order_count':{'grain':'order_id','source':'orders','date':'order_date','filter':"status='cancelled'",'measure':'COUNT(*)'},
 'returned_order_count':{'grain':'order_id','source':'orders','date':'order_date','filter':"status='returned'",'measure':'COUNT(*)'}
}
UNSUPPORTED=['historical_debt_as_of_date','net_profit_after_expenses','historical_stock','shift_cash_as_sales_revenue','refund_cashflow_without_refund_ledger']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);p.add_argument('--release',required=True);a=p.parse_args()
 src=pathlib.Path(a.source);d=pathlib.Path(a.candidate);dest=pathlib.Path(a.release)
 for f in ('dev_003.sqlite','manifest.json','candidate_report.json'):
  if not (d/f).is_file():raise SystemExit('Missing candidate: '+str(d/f))
 manifest=load(d/'manifest.json');candidate=load(d/'candidate_report.json');checks={};failed=[]
 def check(name,ok,details=None):
  checks[name]={'pass':bool(ok)}
  if details is not None:checks[name]['details']=details
  if not ok:failed.append(name)
 check('candidate_version',manifest.get('version')=='dev003-candidate-v1' and manifest.get('approval')=='CANDIDATE_NOT_APPROVED')
 check('source_hashes',all((src/f).is_file() and sha(src/f)==digest for f,digest in manifest.get('source_sha256',{}).items()) and len(manifest.get('source_sha256',{}))==7)
 check('sqlite_sha',sha(d/'dev_003.sqlite')==manifest.get('sqlite_sha256'))
 check('mapping_issues',candidate.get('issues')=={})
 check('candidate_integrity',candidate.get('sqlite_integrity')=='ok' and candidate.get('foreign_keys')==0)
 check('duplicate_lineage',candidate.get('excluded',{}).get('exact_duplicate_line')==1994)
 check('status_counts',candidate.get('statuses')==STATUS)
 # Exact duplicates are deliberately excluded from the canonical mart.
 # Their count is verified separately in duplicate_lineage, not accepted.
 check('source_counts',all(candidate.get('accepted',{}).get(k)==v for k,v in EXPECTED.items() if k!='exact_duplicate_lines'),candidate.get('accepted'))
 proc=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('dev003_financial_qa.py')),'--source',str(src),'--candidate',str(d)],text=True,capture_output=True)
 check('independent_qa_execution',proc.returncode==0,proc.stderr[-900:] if proc.returncode else None)
 if proc.returncode:print(proc.stderr[-1300:],file=sys.stderr)
 qa=load(d/'financial_qa_report.json') if proc.returncode==0 else {}
 check('independent_source_parity',qa.get('source_to_mart_pass') is True and qa.get('mismatches')=={})
 check('independent_coverage',qa.get('orders')==62839 and qa.get('lines')==100210 and qa.get('duplicate_rows')==1994 and qa.get('receipts')==62580)
 check('independent_source_sha',qa.get('source_sha256')==manifest.get('source_sha256'))
 db=sqlite3.connect('file:'+str((d/'dev_003.sqlite').resolve())+'?mode=ro',uri=True)
 actual={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in EXPECTED}
 check('sqlite_counts',actual==EXPECTED,actual)
 check('sqlite_integrity',db.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
 check('foreign_key_check',db.execute('PRAGMA foreign_key_check').fetchall()==[])
 check('order_line_sum',db.execute('SELECT COUNT(*) FROM orders o WHERE o.item_total!=(SELECT SUM(line_total) FROM order_lines l WHERE l.order_id=o.order_id)').fetchone()[0]==0)
 check('order_invoice_money',db.execute('SELECT COUNT(*) FROM orders WHERE payable!=item_total-discount+shipping').fetchone()[0]==0)
 check('active_order_settlement',db.execute("SELECT COUNT(*) FROM orders WHERE status!='cancelled' AND paid_snapshot+debt_snapshot!=payable").fetchone()[0]==0)
 check('cancelled_not_settled',db.execute("SELECT COUNT(*) FROM orders WHERE status='cancelled' AND (paid_snapshot!=0 OR debt_snapshot!=0)").fetchone()[0]==0)
 check('payment_ledger_parity',db.execute('SELECT COUNT(*) FROM orders o WHERE o.paid_snapshot!=COALESCE((SELECT SUM(amount) FROM receipts r WHERE r.order_id=o.order_id),0)').fetchone()[0]==0)
 check('shift_cash_equations',db.execute('SELECT COUNT(*) FROM shift_cash WHERE cash_received-cash_refunded!=net_cash').fetchone()[0]==0)
 check('purchase_lines',db.execute('SELECT COUNT(*) FROM purchases WHERE quantity*unit_cost!=total').fetchone()[0]==0)
 check('sales_line_price',db.execute('SELECT COUNT(*) FROM order_lines WHERE quantity*unit_price-line_discount!=line_total').fetchone()[0]==0)
 check('dates',db.execute("SELECT COUNT(*) FROM orders WHERE order_date IS NULL OR order_date NOT GLOB '????-??-??'").fetchone()[0]==0)
 check('status_final',dict(db.execute('SELECT status,COUNT(*) FROM orders GROUP BY status'))==STATUS)
 totals={s:{'orders':n,'item_revenue_vnd':g,'discount_vnd':disc,'order_revenue_excluding_shipping_vnd':g-disc,'shipping_vnd':ship,'payable_vnd':pay,'paid_vnd':paid,'debt_snapshot_vnd':debt,'cost_of_items_vnd':cost} for s,n,g,disc,ship,pay,paid,debt,cost in db.execute("""SELECT o.status,COUNT(*),SUM(o.item_total),SUM(o.discount),SUM(o.shipping),SUM(o.payable),SUM(o.paid_snapshot),SUM(o.debt_snapshot),(SELECT SUM(l.quantity*l.unit_cost) FROM order_lines l JOIN orders k ON k.order_id=l.order_id WHERE k.status=o.status) FROM orders o GROUP BY o.status""")}
 schemas={table:[r[1] for r in db.execute('PRAGMA table_info("'+table+'")')] for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
 db.close()
 gate={'shop':'dev_003','version':'dev003-v1','approval':'PRODUCTION_APPROVED' if not failed else 'BLOCKED','gate_pass':not failed,'failed_checks':failed,'checks':checks,'source_sha256':manifest['source_sha256'],'sqlite_sha256':sha(d/'dev_003.sqlite'),'status_totals':totals,'kpi_contract':KPIS if not failed else {},'unsupported':UNSUPPORTED,'notes':['Do not sum duplicated POS lines','Cancelled invoices have historical payable but zero settlement','Shift cash includes repayments and refunds: NOT incremental sales revenue','Debt is last-data-date snapshot, not date-series KPI']}
 dump(d/'release_gate_report.json',gate)
 if failed:
  print(json.dumps({'approval':'BLOCKED','gate_pass':False,'failed_checks':failed,'candidate':str(d)},ensure_ascii=False,indent=2))
  sys.exit(1)
 if dest.exists():raise SystemExit('Refusing to overwrite release: '+str(dest))
 dest.parent.mkdir(parents=True,exist_ok=True)
 tmp=pathlib.Path(tempfile.mkdtemp(prefix='.dev003_release_',dir=dest.parent))
 try:
  for filename,output in (('dev_003.sqlite','dev_003.sqlite'),('candidate_report.json','qa_report.json'),('financial_qa_report.json','financial_qa_report.json'),('release_gate_report.json','release_gate_report.json')):
   shutil.copy2(d/filename,tmp/output)
  dump(tmp/'schema_contract.json',{'shop':'dev_003','version':'dev003-v1','approval':'PRODUCTION_APPROVED','tables':schemas,'kpi_contract':KPIS,'unsupported':UNSUPPORTED})
  files={f.name:{'sha256':sha(f),'bytes':f.stat().st_size} for f in tmp.iterdir()}
  dump(tmp/'manifest.json',{'shop':'dev_003','version':'dev003-v1','approval':'PRODUCTION_APPROVED','gate_pass':True,'source_sha256':manifest['source_sha256'],'files':files,'kpis_supported':list(KPIS),'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
  os.rename(tmp,dest)
 except BaseException:
  shutil.rmtree(tmp,ignore_errors=True);raise
 print(json.dumps({'approval':'PRODUCTION_APPROVED','gate_pass':True,'failed_checks':[],'supported_kpis':list(KPIS),'status_totals':totals,'release_dir':str(dest),'release_files':sorted(f.name for f in dest.iterdir())},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
