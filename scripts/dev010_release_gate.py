#!/usr/bin/env python3
"""Fail-closed dev_010 release gate. Changes ONLY files inside --candidate.

Production scope v1: completed-order gross revenue and count; cancelled/returned
order counts. Returned, cancelled and shipping orders are NOT booked revenue.
Gross is the source order header 'Thành tiền', not sum of un-deduplicated rows.
"""
import argparse,collections,datetime,hashlib,json,pathlib,sqlite3,subprocess,sys
EXPECTED={'orders':25191,'order_lines':43935,'payments':26246,'customers':260,'products':60,'dedup_lineage':1090}
EXCLUDED={'orders:summary_or_other':511,'order_lines:exact_duplicate_line':1090,'order_lines:repeated_header':226}
STATUSES={'completed':24008,'returned':400,'cancelled':775,'shipping':8}
KPIS={
 'completed_order_count':{'grain':'distinct order_id','source':'orders','filter':"status='completed'",'measure':'COUNT(*)','date_column':'order_date','as_of_date':'order_date <= as_of_date'},
 'completed_gross_revenue':{'grain':'order_id','source':'orders','filter':"status='completed'",'measure':'SUM(gross_amount)','unit':'VND','date_column':'order_date','as_of_date':'order_date <= as_of_date','notes':'Thành tiền is order final payable including order discount and shipping; never add line discounts twice'},
 'cancelled_order_count':{'grain':'distinct order_id','source':'orders','filter':"status='cancelled'",'measure':'COUNT(*)','date_column':'order_date','as_of_date':'order_date <= as_of_date'},
 'returned_order_count':{'grain':'distinct order_id','source':'orders','filter':"status='returned'",'measure':'COUNT(*)','date_column':'order_date','as_of_date':'order_date <= as_of_date'},
}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);a=p.parse_args()
 source=pathlib.Path(a.source).resolve();candidate=pathlib.Path(a.candidate).resolve()
 errors=[];checks={}
 def check(name,ok,detail=None):
  checks[name]={'pass':bool(ok)}
  if detail is not None:checks[name]['detail']=detail
  if not ok:errors.append(name)
 required=['dev_010.sqlite','manifest.json','qa_report.json','schema_contract.json']
 for name in required:
  if not (candidate/name).is_file():raise SystemExit('Missing candidate artifact '+str(candidate/name))
 manifest=load(candidate/'manifest.json');struct=load(candidate/'qa_report.json')
 check('candidate_origin',manifest.get('version')=='dev010-candidate-v3')
 check('candidate_is_unapproved',manifest.get('approval')=='CANDIDATE_NOT_APPROVED')
 check('sqlite_hash',sha(candidate/'dev_010.sqlite')==manifest.get('sqlite_sha256'))
 source_hashes={}
 for filename,expected_hash in manifest.get('source_sha256',{}).items():
  f=source/filename
  if not f.is_file():raise SystemExit('Missing source '+str(f))
  source_hashes[filename]=sha(f)
  check('source_hash:'+filename,source_hashes[filename]==expected_hash)
 check('source_file_count',set(source_hashes)=={'don_hang.csv','chi_tiet_don.csv','thanh_toan.csv','khach_hang.csv','san_pham.csv'})
 check('structural_qa_pass',struct.get('all_structural_checks_pass') is True and all(x.get('pass') for x in struct.get('checks',{}).values()))
 check('mapping_issues_empty',struct.get('issues')=={})
 check('accepted_counts',struct.get('accepted')=={k:v for k,v in EXPECTED.items() if k!='dedup_lineage'},struct.get('accepted'))
 check('excluded_counts',struct.get('excluded')==EXCLUDED,struct.get('excluded'))
 # Re-run independent QA against the supplied immutable source, preventing stale report reuse.
 subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('dev010_financial_qa.py')),'--source',str(source),'--candidate',str(candidate)],check=True,capture_output=True,text=True)
 financial=load(candidate/'financial_qa_report.json')
 check('independent_source_parity',financial.get('exact_source_to_mart_pass') is True)
 check('independent_financial_parity',financial.get('financial_semantics_approved') is True and financial.get('mismatch_counts')=={})
 check('independent_source_coverage',financial.get('source_order_count')==25191 and financial.get('unparsed_order_money_count')==0 and financial.get('unparsed_line_count')==0 and financial.get('unparsed_payment_count')==0)
 check('dedup_coverage',financial.get('exact_duplicate_line_copies')==1090 and financial.get('duplicate_line_amount')==293381000)
 eq=financial.get('equations_checked',{})
 check('equation_coverage',eq.get('active_gross_equals_paid_plus_debt_checked')==24416 and eq.get('gross_equals_lines_minus_order_discount_plus_shipping_checked')==25191 and eq.get('customer_paid_equals_receipts_checked')==25191 and eq.get('cancelled_paid_debt_zero_checked')==775)
 check('status_counts',financial.get('status_counts')==STATUSES)
 conn=sqlite3.connect('file:'+str((candidate/'dev_010.sqlite'))+'?mode=ro',uri=True)
 check('sqlite_integrity',conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
 check('sqlite_foreign_keys',len(conn.execute('PRAGMA foreign_key_check').fetchall())==0)
 counts={table:conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in EXPECTED}
 check('sqlite_table_counts',counts==EXPECTED,counts)
 statuses=dict(conn.execute('SELECT status,COUNT(*) FROM orders GROUP BY status'))
 check('sqlite_statuses',statuses==STATUSES,statuses)
 duplicate_sum=conn.execute('SELECT SUM(duplicate_line_amount) FROM dedup_lineage').fetchone()[0]
 check('sqlite_duplicate_value',duplicate_sum==293381000,duplicate_sum)
 check('sqlite_no_null_order_money',conn.execute('SELECT COUNT(*) FROM orders WHERE gross_amount IS NULL OR discount_amount IS NULL OR shipping_amount IS NULL OR customer_paid IS NULL OR outstanding_amount IS NULL').fetchone()[0]==0)
 check('sqlite_no_null_line_money',conn.execute('SELECT COUNT(*) FROM order_lines WHERE line_amount IS NULL OR line_discount IS NULL OR unit_price IS NULL').fetchone()[0]==0)
 check('sqlite_no_null_receipts',conn.execute('SELECT COUNT(*) FROM payments WHERE amount IS NULL').fetchone()[0]==0)
 check('sqlite_dates',conn.execute("SELECT COUNT(*) FROM orders WHERE order_date NOT GLOB '????-??-??'").fetchone()[0]==0)
 check('sqlite_no_unknown_status',set(statuses)==set(STATUSES))
 metrics={s:dict(count=n,gross_vnd=g or 0) for s,n,g in conn.execute('SELECT status,COUNT(*),SUM(gross_amount) FROM orders GROUP BY status')}
 conn.close()
 check('release_kpis_positive_scope',set(KPIS)=={'completed_order_count','completed_gross_revenue','cancelled_order_count','returned_order_count'})
 release={'shop':'dev_010','approval':'PRODUCTION_APPROVED' if not errors else 'BLOCKED','version':'dev010-v1','gate_pass':not errors,'failed_checks':errors,'checks':checks,'source_sha256':source_hashes,'sqlite_sha256':sha(candidate/'dev_010.sqlite'),'financial_qa_sha256':sha(candidate/'financial_qa_report.json'),'status_summaries':metrics,'excluded_from_revenue':['cancelled','returned','shipping'],'kpi_contract':KPIS if not errors else {},'unsupported':['net_revenue_after_returns','payment_cashflow_as_of_date','historical_debt_snapshot','profit','stock_inventory'],'evidence':'source README, structural QA, independent source financial QA, exact duplicate lineage'}
 dest=candidate/'release_gate_report.json';dest.write_text(json.dumps(release,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'approval':release['approval'],'gate_pass':release['gate_pass'],'failed_checks':errors,'supported_kpis':list(release['kpi_contract']),'status_summaries':metrics,'report':str(dest)},ensure_ascii=False,indent=2))
 if errors:sys.exit(1)
if __name__=='__main__':main()
