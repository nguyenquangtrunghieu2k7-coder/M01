#!/usr/bin/env python3
"""Fail-closed dev014 source verification and immutable 6-artifact production release."""
import argparse,datetime,json,os,pathlib,shutil,sqlite3,subprocess,sys,tempfile
from dev014_common import sha,dump
EXPECTED={'orders':6334,'order_lines':10107,'aliases':59,'sale_imeis':2191,'trade_ins':300,'installment_contracts':235,'installment_payments':1138,'credit_accounts':168,'credit_payments':333,'warranty_visits':192,'exact_duplicate_lines':175,'excluded_rows':39}
STATUS={'completed':6266,'returned':68}
SOURCES=('SoBanHang.xlsx','SoNo.xlsx','ThuMayCu.xlsx')
KPIS={
 'completed_order_count':{'source':'orders','grain':'order_id','measure':'COUNT(*)','filter':"status='completed'",'date_column':'order_date'},
 'completed_sales_revenue':{'source':'orders','grain':'order_id','measure':'SUM(items_gross-order_discount)','filter':"status='completed'",'unit':'VND','date_column':'order_date','note':'Trade-in is consideration/settlement, NOT reduction of sales revenue; returned orders excluded.'},
 'returned_order_count':{'source':'orders','grain':'order_id','measure':'COUNT(*)','filter':"status='returned'",'date_column':'order_date'},
 'completed_trade_in_order_count':{'source':'orders','grain':'order_id','measure':'COUNT(*)','filter':"status='completed' AND trade_in_credit>0",'date_column':'order_date','note':'Trade-in credit is not separately booked as new sale.'},
 'completed_installment_order_count':{'source':'orders','grain':'order_id','measure':'COUNT(*)','filter':"status='completed' AND has_installment=1",'date_column':'order_date','note':'Installment ledger payments are not additional revenue.'},
}
UNSUPPORTED=['receivable_as_of_arbitrary_date','net_profit','historic_inventory','trade_in_resale_profit','cashflow_from_sale_customer_paid_column','warranty_service_revenue','installment_interest_income']
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def run(src,cand,dest):
 required=('dev_014.sqlite','manifest.json','candidate_report.json')
 for f in required:
  if not (cand/f).is_file():raise RuntimeError('Candidate missing '+f)
 manifest=read(cand/'manifest.json');candidate=read(cand/'candidate_report.json');checks={};failed=[]
 def check(name,passed,detail=None):
  checks[name]={'pass':bool(passed)}
  if detail is not None:checks[name]['detail']=detail
  if not passed:failed.append(name)
 check('candidate_version',manifest.get('version')=='dev014-candidate-v1' and manifest.get('approval')=='CANDIDATE_NOT_APPROVED')
 check('source_file_set',set(manifest.get('source_sha256',{}))==set(SOURCES))
 for f in SOURCES:check('source_sha:'+f,(src/f).is_file() and sha(src/f)==manifest.get('source_sha256',{}).get(f))
 check('sqlite_sha256',sha(cand/'dev_014.sqlite')==manifest.get('sqlite_sha256'))
 check('candidate_mapping_issues',candidate.get('issues')=={})
 check('candidate_integrity',candidate.get('sqlite_integrity')=='ok' and candidate.get('foreign_key_violations')==0)
 check('candidate_status',candidate.get('statuses')==STATUS)
 check('candidate_exclusions',candidate.get('excluded')=={'exact_duplicate_line':175,'monthly_subtotal':15,'sheet_note':24})
 check('candidate_counts',all(candidate.get('accepted',{}).get(k)==n for k,n in EXPECTED.items() if k not in ('exact_duplicate_lines','excluded_rows')),candidate.get('accepted'))
 qa=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('dev014_financial_qa.py')),'--source',str(src),'--candidate',str(cand)],capture_output=True,text=True)
 check('independent_qa_run',qa.returncode==0,qa.stderr[-1000:] if qa.returncode else None)
 if qa.returncode:print(qa.stderr[-1400:],file=sys.stderr)
 independent=read(cand/'financial_qa_report.json') if qa.returncode==0 else {}
 check('independent_full_source_parity',independent.get('source_to_mart_pass') is True and independent.get('mismatches')=={})
 check('independent_source_sha',independent.get('source_sha256')==manifest.get('source_sha256'))
 check('independent_counts',all(independent.get(k)==v for k,v in {'orders':6334,'order_lines':10107,'alias_rows':59,'exact_duplicates':175,'sale_imeis':2191,'trade_ins':300,'credit_accounts':168,'credit_payments':333,'installment_contracts':235,'installment_payments':1138,'warranty_visits':192,'excluded_rows':39}.items()))
 check('independent_statuses',independent.get('status_orders')==STATUS)
 db=sqlite3.connect('file:'+str((cand/'dev_014.sqlite').resolve())+'?mode=ro',uri=True)
 actual={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in EXPECTED}
 check('sqlite_counts',actual==EXPECTED,actual)
 check('sqlite_integrity',db.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
 check('foreign_keys',db.execute('PRAGMA foreign_key_check').fetchall()==[])
 check('order_line_sum',db.execute('SELECT COUNT(*) FROM orders o WHERE items_gross!=(SELECT SUM(line_total) FROM order_lines l WHERE l.order_id=o.order_id)').fetchone()[0]==0)
 check('order_money',db.execute('SELECT COUNT(*) FROM orders WHERE ABS(items_gross-order_discount-trade_in_credit-customer_paid_ledger)>1 OR customer_paid_ledger IS NULL').fetchone()[0]==0)
 check('line_money',db.execute('SELECT COUNT(*) FROM order_lines WHERE ABS(quantity*unit_price-line_total)>1 OR quantity IS NULL OR unit_price IS NULL OR line_total IS NULL').fetchone()[0]==0)
 check('trade_parity',db.execute('SELECT COUNT(*) FROM orders o WHERE trade_in_credit!=COALESCE((SELECT SUM(trade_value) FROM trade_ins t WHERE t.order_id=o.order_id),0)').fetchone()[0]==0)
 check('installments_not_double_booked',db.execute('SELECT COUNT(*) FROM orders o WHERE has_installment!=EXISTS(SELECT 1 FROM installment_contracts i WHERE i.order_id=o.order_id)').fetchone()[0]==0)
 check('credit_flags',db.execute('SELECT COUNT(*) FROM orders o WHERE has_credit!=EXISTS(SELECT 1 FROM credit_accounts c WHERE c.order_id=o.order_id)').fetchone()[0]==0)
 check('warranty_imei_linked',db.execute('SELECT COUNT(*) FROM warranty_visits w LEFT JOIN sale_imeis s ON w.imei=s.imei WHERE s.imei IS NULL').fetchone()[0]==0)
 check('finance_distinct',db.execute('SELECT COUNT(*) FROM installment_contracts i JOIN credit_accounts c ON i.order_id=c.order_id').fetchone()[0]==0)
 check('date_coverage',db.execute('SELECT COUNT(*) FROM orders WHERE order_date IS NULL OR order_date NOT GLOB "????-??-??"').fetchone()[0]==0)
 check('date_end',db.execute('SELECT MAX(order_date) FROM orders').fetchone()[0]=='2026-09-30')
 totals={s:{'orders':n,'items_gross_vnd':g,'discount_vnd':disc,'sales_revenue_vnd':g-disc,'trade_in_credit_vnd':trade,'customer_paid_ledger_vnd':paid,'trade_in_orders':traded,'installment_orders':ins,'credit_orders':credit} for s,n,g,disc,trade,paid,traded,ins,credit in db.execute('SELECT status,COUNT(*),SUM(items_gross),SUM(order_discount),SUM(trade_in_credit),SUM(customer_paid_ledger),SUM(CASE WHEN trade_in_credit>0 THEN 1 ELSE 0 END),SUM(has_installment),SUM(has_credit) FROM orders GROUP BY status')}
 check('completed_revenue',totals.get('completed',{}).get('sales_revenue_vnd')==25244510000)
 check('completed_trade_and_installments',totals.get('completed',{}).get('trade_in_orders')==300 and totals.get('completed',{}).get('installment_orders')==235)
 schema={name:[{'column':r[1],'type':r[2],'not_null':bool(r[3]),'primary_key':bool(r[5])} for r in db.execute('PRAGMA table_info("'+name+'")')] for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
 db.close()
 passed=not failed
 gate={'shop':'dev_014','version':'dev014-v1','approval':'PRODUCTION_APPROVED' if passed else 'BLOCKED','gate_pass':passed,'failed_checks':failed,'checks':checks,'source_sha256':manifest['source_sha256'],'sqlite_sha256':sha(cand/'dev_014.sqlite'),'independent_qa_sha256':sha(cand/'financial_qa_report.json') if (cand/'financial_qa_report.json').exists() else None,'status_totals':totals,'kpi_contract':KPIS if passed else {},'unsupported':UNSUPPORTED,'notes':['Sales gross minus invoice discount is booked sales; trade-ins do not reduce booked revenue','Sale ledger Khách trả is the contractual invoice amount AFTER trade-in, NOT installment upfront cash','Warranty visits do not create revenue','Returned entire orders are excluded','Finance repayments have distinct ledger and must never be booked again as sale','Deterministic canonical aliases and exact-duplicate lineage; source preserved']}
 dump(cand/'release_gate_report.json',gate)
 if not passed:
  print(json.dumps({'approval':'BLOCKED','gate_pass':False,'failed_checks':failed,'candidate':str(cand)},ensure_ascii=False,indent=2));sys.exit(1)
 if dest.exists():raise RuntimeError('Release exists, cannot overwrite '+str(dest))
 dest.parent.mkdir(parents=True,exist_ok=True)
 temp=pathlib.Path(tempfile.mkdtemp(prefix='.dev014_release_',dir=dest.parent))
 try:
  for old,new in [('dev_014.sqlite','dev_014.sqlite'),('candidate_report.json','qa_report.json'),('financial_qa_report.json','financial_qa_report.json'),('release_gate_report.json','release_gate_report.json')]:shutil.copy2(cand/old,temp/new)
  dump(temp/'schema_contract.json',{'shop':'dev_014','version':'dev014-v1','approval':'PRODUCTION_APPROVED','tables':schema,'kpi_contract':KPIS,'unsupported':UNSUPPORTED})
  files={f.name:{'sha256':sha(f),'bytes':f.stat().st_size} for f in temp.iterdir()}
  dump(temp/'manifest.json',{'shop':'dev_014','version':'dev014-v1','approval':'PRODUCTION_APPROVED','gate_pass':True,'source_sha256':manifest['source_sha256'],'files':files,'kpis_supported':list(KPIS),'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
  os.rename(temp,dest)
 except BaseException:
  shutil.rmtree(temp,ignore_errors=True);raise
 print(json.dumps({'approval':'PRODUCTION_APPROVED','gate_pass':True,'failed_checks':[],'supported_kpis':list(KPIS),'status_totals':totals,'release_dir':str(dest),'release_files':sorted(f.name for f in dest.iterdir())},ensure_ascii=False,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);p.add_argument('--release',required=True);a=p.parse_args();run(pathlib.Path(a.source),pathlib.Path(a.candidate),pathlib.Path(a.release))
