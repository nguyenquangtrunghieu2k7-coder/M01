#!/usr/bin/env python3
"""dev002 independent financial gate + immutable production SQLite/JSON package."""
import argparse,datetime,hashlib,json,os,pathlib,shutil,sqlite3,subprocess,sys,tempfile
SOURCES=tuple('BanHang_T%d_%d.xlsx'%(m,y) for y in (2025,2026) for m in range(1,13) if y==2025 or m<=5)+('DanhSachQuyDoi.xlsx',)
COUNTS={'orders':53164,'order_lines':84146,'topping_components':1095,'unit_conversions':2,'source_rows':85092,'excluded_rows':946,'mapping_issues':0}
STATUSES={'completed':51851,'cancelled':1069,'returned':206,'in_progress':38}
EXCLUDED={'repeated_header':420,'daily_summary':526}
KPI={
 'completed_order_count':{'source':'orders','grain':'order_id','date_column':'order_date','filter':"status='completed'",'measure':'COUNT(*)'},
 'completed_sales_revenue':{'source':'orders','grain':'order_id','date_column':'order_date','filter':"status='completed'",'measure':'SUM(item_total)','unit':'VND','note':'Source line totals already include embedded toppings and exclude line discounts; never add topping amount again.'},
 'completed_embedded_topping_amount':{'source':'order_lines JOIN orders USING(order_id)','grain':'source sale line','date_column':'orders.order_date','filter':"orders.status='completed'",'measure':'SUM(order_lines.topping_amount)','unit':'VND','note':'Descriptive INCLUDED component of completed sales revenue, not additional revenue.'},
 'cancelled_order_count':{'source':'orders','grain':'order_id','date_column':'order_date','filter':"status='cancelled'",'measure':'COUNT(*)'},
 'returned_order_count':{'source':'orders','grain':'order_id','date_column':'order_date','filter':"status='returned'",'measure':'COUNT(*)'}
}
UNSUPPORTED=['net_profit','inventory_history','payment_cashflow','outstanding_debt','product_id_based_join','standalone_topping_qty_for_embedded_components','historical_returns_cashflow']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);p.add_argument('--release',required=True);a=p.parse_args()
 source=pathlib.Path(a.source);candidate=pathlib.Path(a.candidate);dest=pathlib.Path(a.release)
 for filename in ('manifest.json','candidate_report.json','dev_002.sqlite'):
  if not (candidate/filename).is_file():raise SystemExit('Missing candidate file: '+filename)
 manifest=read(candidate/'manifest.json');report=read(candidate/'candidate_report.json')
 checks={};failed=[]
 def check(name,ok,detail=None):
  checks[name]={'pass':bool(ok)}
  if detail is not None:checks[name]['details']=detail
  if not ok:failed.append(name)
 check('candidate_version',manifest.get('version')=='dev002-candidate-v1' and manifest.get('approval')=='CANDIDATE_NOT_APPROVED')
 check('source_set',set(manifest.get('source_sha256',{}))==set(SOURCES))
 for filename in SOURCES:
  p=source/filename
  check('source_hash:'+filename,p.is_file() and sha(p)==manifest.get('source_sha256',{}).get(filename))
 check('sqlite_hash',sha(candidate/'dev_002.sqlite')==manifest.get('sqlite_sha256'))
 check('candidate_counts',report.get('accepted')=={'orders':53164,'order_lines':84146,'topping_components':1095,'unit_conversions':2},report.get('accepted'))
 check('candidate_issues',report.get('issues')=={})
 check('candidate_excluded',report.get('excluded')==EXCLUDED,report.get('excluded'))
 check('candidate_status',report.get('status_counts')==STATUSES)
 check('candidate_source_rows',report.get('source_rows')==85092)
 check('candidate_discounted_lines',report.get('line_discount_count')==1060)
 check('candidate_sqlite',report.get('sqlite_integrity')=='ok' and report.get('foreign_key_violations')==0)
 process=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('dev002_financial_qa.py')),'--source',str(source),'--candidate',str(candidate)],capture_output=True,text=True)
 check('independent_qa_executed',process.returncode==0,process.stderr[-1000:] if process.returncode else None)
 if process.returncode:print(process.stderr[-2000:],file=sys.stderr)
 qa=read(candidate/'financial_qa_report.json') if process.returncode==0 else {}
 check('independent_source_parity',qa.get('source_to_mart_pass') is True and qa.get('mismatches')=={})
 check('independent_source_hash',qa.get('source_sha256')==manifest.get('source_sha256'))
 check('independent_counts',qa.get('orders')==53164 and qa.get('order_lines')==84146 and qa.get('source_sale_rows')==85092 and qa.get('unit_conversions')==2 and qa.get('topping_component_count')==1095)
 check('independent_exclusions',qa.get('excluded')==EXCLUDED)
 check('independent_status',qa.get('statuses')==STATUSES)
 check('independent_revenue',qa.get('revenue_by_status_vnd')=={'completed':3686408500,'cancelled':74026500,'returned':15224000,'in_progress':2656500})
 check('independent_topping_discount',qa.get('toppings_and_discounts')=={'embedded_topping_amount_vnd':11010500,'discounted_lines':1060,'line_discount_vnd':2462000})
 db=sqlite3.connect('file:'+str((candidate/'dev_002.sqlite').resolve())+'?mode=ro',uri=True)
 tablemap={k:k for k in COUNTS}
 actual={k:db.execute('SELECT COUNT(*) FROM '+v).fetchone()[0] for k,v in tablemap.items()}
 check('sqlite_counts',actual==COUNTS,actual)
 check('sqlite_integrity',db.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
 check('foreign_keys',db.execute('PRAGMA foreign_key_check').fetchall()==[])
 check('status_distribution',dict(db.execute('SELECT status,COUNT(*) FROM orders GROUP BY status'))==STATUSES)
 check('order_line_sum',db.execute('SELECT COUNT(*) FROM orders o WHERE o.item_total!=(SELECT SUM(line_total) FROM order_lines l WHERE l.order_id=o.order_id)').fetchone()[0]==0)
 check('all_lines_reconciled',db.execute('SELECT COUNT(*) FROM order_lines WHERE base_amount+topping_amount-line_discount!=line_total OR line_discount<0 OR quantity<=0').fetchone()[0]==0)
 check('topping_component_sum',db.execute('SELECT COUNT(*) FROM order_lines l WHERE l.topping_amount!=COALESCE((SELECT SUM(part_total) FROM topping_components t WHERE t.file=l.file AND t.row=l.row),0)').fetchone()[0]==0)
 check('line_quantity_conversion',db.execute("""SELECT COUNT(*) FROM order_lines l WHERE l.base_quantity!=l.quantity*COALESCE((SELECT factor FROM unit_conversions u WHERE u.product_name=l.base_product AND u.large_unit=l.unit),1)""").fetchone()[0]==0)
 check('all_dates',db.execute("SELECT COUNT(*) FROM orders WHERE order_date IS NULL OR order_date NOT GLOB '????-??-??'").fetchone()[0]==0)
 check('sales_revenue',db.execute("SELECT SUM(item_total) FROM orders WHERE status='completed'").fetchone()[0]==3686408500)
 check('no_duplicate_source_rows',db.execute('SELECT COUNT(*) FROM (SELECT file,row FROM source_rows GROUP BY file,row HAVING COUNT(*)>1)').fetchone()[0]==0)
 metrics={status:{'orders':n,'sales_revenue_vnd':revenue} for status,n,revenue in db.execute('SELECT status,COUNT(*),SUM(item_total) FROM orders GROUP BY status')}
 toppings=db.execute("SELECT COALESCE(SUM(l.topping_amount),0) FROM order_lines l JOIN orders o ON o.order_id=l.order_id WHERE o.status='completed'").fetchone()[0]
 metrics['completed']['embedded_topping_value_vnd']=toppings
 schema={name:[r[1] for r in db.execute('PRAGMA table_info("'+name+'")')] for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
 db.close()
 approved=not failed
 gate={'approval':'PRODUCTION_APPROVED' if approved else 'BLOCKED','gate_pass':approved,'failed_checks':failed,'checks':checks,'shop':'dev_002','version':'dev002-v1','source_sha256':manifest['source_sha256'],'sqlite_sha256':sha(candidate/'dev_002.sqlite'),'status_totals':metrics,'kpi_contract':KPI if approved else {},'unsupported':UNSUPPORTED,'notes':['Composite topping amounts are already included in line totals.','Unit conversions affect normalized quantity, not monetary line values.','Discount adjustment is derived from source line totals and stays separate from embedded toppings.','No payment or inventory ledger: do not invent profit/debt/cashflow KPIs.']}
 save(candidate/'release_gate_report.json',gate)
 if not approved:
  print(json.dumps({'approval':'BLOCKED','gate_pass':False,'failed_checks':failed,'candidate':str(candidate)},ensure_ascii=False,indent=2));sys.exit(1)
 if dest.exists():raise SystemExit('Release exists: refusing to overwrite '+str(dest))
 dest.parent.mkdir(parents=True,exist_ok=True)
 temp=pathlib.Path(tempfile.mkdtemp(prefix='.dev002_release_',dir=dest.parent))
 try:
  for a,b in (('dev_002.sqlite','dev_002.sqlite'),('candidate_report.json','qa_report.json'),('financial_qa_report.json','financial_qa_report.json'),('release_gate_report.json','release_gate_report.json')):
   shutil.copy2(candidate/a,temp/b)
  save(temp/'schema_contract.json',{'approval':'PRODUCTION_APPROVED','shop':'dev_002','version':'dev002-v1','tables':schema,'kpi_contract':KPI,'unsupported':UNSUPPORTED})
  filehashes={f.name:{'sha256':sha(f),'bytes':f.stat().st_size} for f in temp.iterdir()}
  save(temp/'manifest.json',{'approval':'PRODUCTION_APPROVED','gate_pass':True,'shop':'dev_002','version':'dev002-v1','source_sha256':manifest['source_sha256'],'files':filehashes,'kpis_supported':list(KPI),'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
  os.rename(temp,dest)
 except BaseException:
  shutil.rmtree(temp,ignore_errors=True);raise
 print(json.dumps({'approval':'PRODUCTION_APPROVED','gate_pass':True,'failed_checks':[],'supported_kpis':list(KPI),'status_totals':metrics,'release_dir':str(dest),'release_files':sorted(f.name for f in dest.iterdir())},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
