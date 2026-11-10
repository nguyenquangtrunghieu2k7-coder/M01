#!/usr/bin/env python3
"""Fail-closed release gate for dev_011. No write to source, SQLite or other shops."""
import argparse,hashlib,json,pathlib,sqlite3,subprocess,sys
COUNT={'orders':3819,'order_lines':6043,'product_aliases':59,'source_rows':6102,'mapping_issues':0}
STATUS={'completed':3790,'returned':29}
KPIS={
 'completed_order_count':{'source':'orders','grain':'order_id','filter':"status='completed'",'measure':'COUNT(*)','date_column':'order_date'},
 'completed_sales_revenue':{'source':'orders','grain':'order_id','filter':"status='completed'",'measure':'SUM(items_gross-order_discount)','unit':'VND','date_column':'order_date','note':'Trade-in credit is payment settlement, NOT a reduction of merchandise revenue. Returned entire orders excluded.'},
 'returned_order_count':{'source':'orders','grain':'order_id','filter':"status='returned'",'measure':'COUNT(*)','date_column':'order_date'},
 'completed_trade_in_order_count':{'source':'orders','grain':'order_id','filter':"status='completed' AND trade_in_credit>0",'measure':'COUNT(*)','date_column':'order_date','note':'Counts trade-ins as settlement activity; not sale revenue'}
}
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);a=p.parse_args()
 source=pathlib.Path(a.source);source=source/'SoBanHang.xlsx' if source.is_dir() else source;d=pathlib.Path(a.candidate)
 checks={};failed=[]
 def check(name,passed,details=None):
  checks[name]={'pass':bool(passed)}
  if details is not None:checks[name]['details']=details
  if not passed:failed.append(name)
 for f in ('manifest.json','qa_report.json','dev_011.sqlite'):
  if not (d/f).is_file():raise SystemExit('Missing candidate '+str(d/f))
 manifest=load(d/'manifest.json');struct=load(d/'qa_report.json')
 check('candidate_version',manifest.get('version')=='dev011-candidate-v1')
 check('candidate_not_preapproved',manifest.get('approval')=='CANDIDATE_NOT_APPROVED')
 check('source_sha256',digest(source)==manifest.get('source_sha256'))
 check('sqlite_sha256',digest(d/'dev_011.sqlite')==manifest.get('sqlite_sha256'))
 check('structural_issues_empty',struct.get('issues')=={} and struct.get('order_equation_mismatch_count')==0)
 check('structural_counts',struct.get('counts')==COUNT)
 check('structural_sqlite',struct.get('sqlite_integrity')=='ok' and struct.get('foreign_key_violations')==0)
 qa_proc=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('dev011_financial_qa.py')),'--source',str(source),'--candidate',str(d)],capture_output=True,text=True)
 check('independent_qa_executed',qa_proc.returncode==0,qa_proc.stderr[-500:] if qa_proc.returncode else None)
 if qa_proc.returncode:print(qa_proc.stderr,file=sys.stderr)
 qa=load(d/'financial_qa_report.json') if qa_proc.returncode==0 else {}
 check('independent_source_parity',qa.get('source_to_mart_pass') is True and qa.get('mismatch_counts')=={})
 check('independent_source_hash',qa.get('independent_source_sha256')==digest(source))
 check('independent_coverage',qa.get('source_orders')==3819 and qa.get('source_lines')==6043 and qa.get('catalog_rows')==59 and qa.get('equations_checked')==3819)
 check('independent_returns',qa.get('status_orders')==STATUS and qa.get('trade_in_orders')==221)
 db=sqlite3.connect('file:'+str((d/'dev_011.sqlite').resolve())+'?mode=ro',uri=True)
 counts={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in COUNT}
 check('sqlite_counts',counts==COUNT,counts)
 check('sqlite_integrity',db.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
 check('foreign_keys',db.execute('PRAGMA foreign_key_check').fetchall()==[])
 statuses=dict(db.execute('SELECT status,COUNT(*) FROM orders GROUP BY status'))
 check('statuses',statuses==STATUS,statuses)
 check('ledger_equations',db.execute('SELECT COUNT(*) FROM orders WHERE items_gross-order_discount-trade_in_credit!=customer_paid OR items_gross IS NULL OR customer_paid IS NULL').fetchone()[0]==0)
 check('line_equations',db.execute('SELECT COUNT(*) FROM order_lines WHERE quantity*unit_price!=line_total OR quantity IS NULL OR unit_price IS NULL OR line_total IS NULL').fetchone()[0]==0)
 check('line_order_parity',db.execute('SELECT COUNT(*) FROM orders o WHERE items_gross!=(SELECT SUM(line_total) FROM order_lines l WHERE l.order_id=o.order_id)').fetchone()[0]==0)
 check('valid_product_types',db.execute("SELECT COUNT(*) FROM order_lines WHERE product_type NOT IN ('máy mới','máy cũ','phụ kiện') OR product_name IS NULL").fetchone()[0]==0)
 check('date_coverage',db.execute('SELECT COUNT(*) FROM orders WHERE order_date IS NULL').fetchone()[0]==0)
 check('date_end',db.execute('SELECT MAX(order_date) FROM orders').fetchone()[0]=='2026-07-31')
 totals={st:{'orders':n,'items_gross_vnd':gross,'order_discount_vnd':discount,'trade_in_credit_vnd':trade,'customer_paid_vnd':paid,'sales_revenue_before_trade_in_vnd':gross-discount} for st,n,gross,discount,trade,paid in db.execute('SELECT status,COUNT(*),SUM(items_gross),SUM(order_discount),SUM(trade_in_credit),SUM(customer_paid) FROM orders GROUP BY status')}
 completed_trade=db.execute("SELECT COUNT(*) FROM orders WHERE status='completed' AND trade_in_credit>0").fetchone()[0]
 db.close()
 approved=not failed
 report={'shop':'dev_011','version':'dev011-v1','approval':'PRODUCTION_APPROVED' if approved else 'BLOCKED','gate_pass':approved,'failed_checks':failed,'checks':checks,'source_sha256':digest(source),'sqlite_sha256':digest(d/'dev_011.sqlite'),'independent_qa_sha256':digest(d/'financial_qa_report.json') if (d/'financial_qa_report.json').exists() else None,'status_totals':totals,'completed_trade_in_order_count':completed_trade,'kpi_contract':KPIS if approved else {},'unsupported':['gross_profit','trade_in_resale_profit','refund_cashflow','inventory','IMEI_stock_snapshot','historical_receivables'],'notes':['Returned orders excluded in full','Trade-in credit is distinct from merchandise revenue','All original rows and product aliases retained for lineage']}
 target=d/'release_gate_report.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps({'report':str(target),'approval':report['approval'],'gate_pass':approved,'failed_checks':failed,'supported_kpis':list(report['kpi_contract']),'completed_trade_in_order_count':completed_trade,'status_totals':totals},ensure_ascii=False,indent=2))
 if failed:sys.exit(1)
if __name__=='__main__':main()
