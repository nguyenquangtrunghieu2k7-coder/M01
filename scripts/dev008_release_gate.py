#!/usr/bin/env python3
"""dev_008 status-aware release gate; independently re-audits raw source.

Approved scope excludes debt snapshot and payment cashflow because debt is
recorded as end-of-period free-text notes, not a payment ledger.
"""
import argparse,hashlib,json,pathlib,sqlite3,subprocess,sys,collections,re
EXPECTED={'orders':40154,'order_lines':151392,'product_catalog':61,'inbound_lines':1836,'dedup_lineage':1347}
STATUSES={'completed':39220,'cancelled':834,'returned':82,'shipping':9,'in_progress':9}
SOURCES={'ChiTietHoaDon_1.xlsx','ChiTietHoaDon_2.xlsx','DanhMucHang.xlsx','ChiTietNhapHang.xlsx'}
KPIS={
 'completed_order_count':{'grain':'order_id','date':'order_date','filter':"normalized_status='completed'",'measure':'COUNT(*)'},
 'completed_item_revenue':{'grain':'order_id','date':'order_date','filter':"normalized_status='completed'",'measure':'SUM(order_items_total)','unit':'VND','definition':'Sum of product and service line totals after line discounts, before order discount and shipping'},
 'completed_order_revenue_excluding_shipping':{'grain':'order_id','date':'order_date','filter':"normalized_status='completed'",'measure':'SUM(order_items_total-order_discount)','unit':'VND','definition':'Completed items minus invoice-level discount; shipping excluded'},
 'cancelled_order_count':{'grain':'order_id','date':'order_date','filter':"normalized_status='cancelled'",'measure':'COUNT(*)'},
 'returned_order_count':{'grain':'order_id','date':'order_date','filter':"normalized_status='returned'",'measure':'COUNT(*)'},
}
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);a=p.parse_args()
 src=pathlib.Path(a.source);d=pathlib.Path(a.candidate)
 errors=[];checks={}
 def check(k,passed,details=None):
  checks[k]={'pass':bool(passed)}
  if details is not None:checks[k]['details']=details
  if not passed:errors.append(k)
 for name in ('dev_008.sqlite','manifest.json','candidate_report.json'):
  if not (d/name).is_file():raise SystemExit('Missing '+str(d/name))
 manifest=read(d/'manifest.json');candidate=read(d/'candidate_report.json')
 check('correct_candidate_version',manifest.get('version')=='dev008-candidate-v2')
 check('unapproved_candidate',manifest.get('approval')=='CANDIDATE_NOT_APPROVED')
 check('sqlite_hash_matches_manifest',sha(d/'dev_008.sqlite')==manifest.get('sqlite_sha256'))
 check('source_file_set',set(manifest.get('source_sha256',{}))==SOURCES)
 for filename,expected in manifest.get('source_sha256',{}).items():
  check('source_hash:'+filename,sha(src/filename)==expected)
 check('adapter_no_mapping_issues',candidate.get('issues')=={})
 check('candidate_counts',candidate.get('accepted')=={k:v for k,v in EXPECTED.items() if k!='dedup_lineage'})
 check('candidate_exclusions',candidate.get('excluded')=={'exact_duplicate_line':1347,'non_transaction_or_summary':587})
 check('candidate_item_parity',candidate.get('orders_matching_item_sum')==40154)
 check('candidate_invoice_equation',candidate.get('orders_matching_payable_equation')==40154)
 check('candidate_dedup_lineage',candidate.get('dedup_lineage_count')==1347 and candidate.get('dedup_lineage_amount')==191714500)
 # Always rerun independent QA from source to prevent release from stale QA.
 result=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('dev008_financial_qa.py')),'--source',str(src),'--candidate',str(d)],text=True,capture_output=True)
 check('independent_qa_executed',result.returncode==0,result.stderr[-500:] if result.returncode else None)
 if result.returncode:print(result.stderr,file=sys.stderr)
 if result.returncode==0:
  qa=read(d/'financial_qa_report.json')
  check('source_to_mart_parity',qa.get('source_to_mart_pass') is True)
  check('financial_equations',qa.get('financial_equation_pass') is True)
  check('no_independent_mismatches',qa.get('mismatch_counts')=={} and qa.get('unparseable_money')=={})
  counts=qa.get('counts',{})
  check('independent_counts',counts.get('source_orders')==40154 and counts.get('db_orders')==40154 and counts.get('source_lines')==151392 and counts.get('db_lines')==151392)
  check('independent_duplicate_evidence',counts.get('source_exact_duplicate_copies')==1347 and counts.get('db_duplicate_copies')==1347 and counts.get('source_duplicate_amount')==191714500)
 con=sqlite3.connect('file:'+str((d/'dev_008.sqlite').resolve())+'?mode=ro',uri=True)
 check('sqlite_integrity',con.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
 check('foreign_keys',con.execute('PRAGMA foreign_key_check').fetchall()==[])
 counts={k:con.execute('SELECT COUNT(*) FROM '+k).fetchone()[0] for k in EXPECTED}
 check('sqlite_counts',counts==EXPECTED,counts)
 status=dict(con.execute('SELECT normalized_status,COUNT(*) FROM orders GROUP BY normalized_status'))
 check('status_distribution',status==STATUSES,status)
 check('no_null_sale_amount',con.execute('SELECT COUNT(*) FROM orders WHERE order_items_total IS NULL OR order_discount IS NULL OR shipping_fee IS NULL OR order_payable IS NULL').fetchone()[0]==0)
 check('no_null_line_amount',con.execute('SELECT COUNT(*) FROM order_lines WHERE line_total IS NULL OR line_discount IS NULL OR unit_price IS NULL').fetchone()[0]==0)
 check('all_order_dates',con.execute("SELECT COUNT(*) FROM orders WHERE order_date IS NULL OR order_date NOT GLOB '????-??-??'").fetchone()[0]==0)
 check('all_invoice_equations',con.execute('SELECT COUNT(*) FROM orders WHERE order_payable != order_items_total-order_discount+shipping_fee').fetchone()[0]==0)
 check('all_line_equations',con.execute('SELECT COUNT(*) FROM orders o WHERE o.order_items_total != (SELECT SUM(line_total) FROM order_lines l WHERE l.order_id=o.order_id)').fetchone()[0]==0)
 check('no_line_duplicates_by_order_position',con.execute('SELECT COUNT(*) FROM (SELECT order_id,line_number FROM order_lines GROUP BY order_id,line_number HAVING COUNT(*)>1)').fetchone()[0]==0)
 debt=con.execute("SELECT order_id,debt_note,order_payable FROM orders WHERE payment_method='debt' ORDER BY order_id").fetchall()
 check('debt_notes_present',len(debt)==245 and all(note for _,note,_ in debt),{'debt_orders':len(debt)})
 settled=sum(any(s in note.lower() for s in ('đã trả đủ','khách ck đủ rồi','khách trả hết rồi')) for _,note,_ in debt)
 unresolved=[{'order_id':oid,'note':note,'payable_vnd':payable} for oid,note,payable in debt if not any(s in note.lower() for s in ('đã trả đủ','khách ck đủ rồi','khách trả hết rồi'))]
 check('debt_note_classification',settled==230 and len(unresolved)==15,{'settled':settled,'unsettled_or_ambiguous':len(unresolved)})
 # Do NOT equate payment_method debt with current receivables; source only
 # provides free-text notes as of end date and lacks repayment timestamps.
 metrics={st:{'orders':count,'items_vnd':items,'payable_vnd':payable,'invoice_discount_vnd':discount,'shipping_vnd':shipping} for st,count,items,payable,discount,shipping in con.execute('SELECT normalized_status,COUNT(*),SUM(order_items_total),SUM(order_payable),SUM(order_discount),SUM(shipping_fee) FROM orders GROUP BY normalized_status')}
 con.close()
 approved=not errors
 release={'shop':'dev_008','approval':'PRODUCTION_APPROVED' if approved else 'BLOCKED','gate_pass':approved,'failed_checks':errors,'checks':checks,'version':'dev008-v1','source_sha256':manifest['source_sha256'],'sqlite_sha256':sha(d/'dev_008.sqlite'),'independent_qa_sha256':sha(d/'financial_qa_report.json') if (d/'financial_qa_report.json').is_file() else None,'status_totals':metrics,'debt_note_audit':{'settled_order_count':settled,'unsettled_or_ambiguous_count':len(unresolved),'unsettled_or_ambiguous_orders':unresolved},'kpi_contract':KPIS if approved else {},'excluded_from_completed_revenue':['cancelled','returned','shipping','in_progress'],'unsupported':['current_debt_snapshot','historical_debt','cashflow','net_profit','cost_of_goods_sold','inventory_history','shipping_inclusive_revenue_as_item_sales'],'notes':['Debt free-text snapshot is preserved but not published as a numeric KPI','Invoice discount and shipping must be applied only once per order','Returned and cancelled invoices must not contribute to completed revenue']}
 output=d/'release_gate_report.json';output.write_text(json.dumps(release,ensure_ascii=False,indent=2))
 print(json.dumps({'report':str(output),'approval':release['approval'],'gate_pass':approved,'failed_checks':errors,'supported_kpis':list(release['kpi_contract']),'debt_note_audit':{'settled_orders':settled,'unsettled_or_ambiguous_orders':len(unresolved)},'status_totals':metrics},ensure_ascii=False,indent=2))
 if errors:sys.exit(1)
if __name__=='__main__':main()
