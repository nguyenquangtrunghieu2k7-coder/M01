#!/usr/bin/env python3
"""Independent dev013 financial QA and immutable SQLite/JSON release.

All sources immutable. Never touches other shop outputs. A successful gate
creates an independent versioned release with its own approved manifest.
"""
import argparse,collections,hashlib,json,os,pathlib,re,shutil,sqlite3,tempfile
from decimal import Decimal
from dev011_source_audit import sheet_rows
from dev013_pipeline import all_rows,manager
COUNTS={'orders':11834,'order_lines':32153,'catalog':77,'customers':420,'purchases':1503,'promotions':10}
TYPES={'item':20754,'voucher':8109,'points_redemption':656,'shipping_fee':2634}
STATUS={'completed':11456,'cancelled':358,'shipping':20}
SOURCES=('BanHang_2025.xlsx','BanHang_2026.xlsx','QuanLy.xlsx')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def money(v):
 s=str(v if v is not None else '').strip().lower().replace(' ','').replace('đ','').replace('₫','')
 if not s:return None
 sign=-1 if s.startswith('-') else 1
 if sign<0:s=s[1:]
 m=re.fullmatch(r'(\d+(?:[,.]\d+)?)tr',s)
 if m:return sign*int(Decimal(m[1].replace(',','.'))*1000000)
 m=re.fullmatch(r'(\d+(?:[,.]\d+)?)k',s)
 if m:return sign*int(Decimal(m[1].replace(',','.'))*1000)
 if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',s):return sign*int(re.sub('[.,]','',s))
 if s.isdigit():return sign*int(s)
 return None
def run(source,candidate,release):
 report=read(candidate/'candidate_report.json');manifest=read(candidate/'manifest.json')
 errors=[];checks={}
 def check(name,ok,detail=None):
  checks[name]={'pass':bool(ok)}
  if detail is not None:checks[name]['detail']=detail
  if not ok:errors.append(name)
 check('candidate_version',manifest.get('version')=='dev013-candidate-v1' and manifest.get('approval')=='CANDIDATE_NOT_APPROVED')
 for f in SOURCES:check('source_hash:'+f,sha(source/f)==manifest.get('source_sha256',{}).get(f))
 dbpath=candidate/'dev_013.sqlite'
 check('sqlite_sha',sha(dbpath)==manifest.get('sqlite_sha256'))
 check('candidate_counts',report.get('source_counts')==COUNTS)
 check('candidate_issues',report.get('issues')=={})
 check('candidate_exclusions',report.get('excluded')=={'non_invoice_or_subtotal':21})
 check('candidate_status',report.get('status_counts')==STATUS)
 check('candidate_types',report.get('line_types')==TYPES)
 db=sqlite3.connect('file:'+str(dbpath.resolve())+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 check('sqlite_integrity',db.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
 check('foreign_keys',db.execute('PRAGMA foreign_key_check').fetchall()==[])
 counts={k:db.execute('SELECT COUNT(*) FROM '+k).fetchone()[0] for k in COUNTS}
 check('sqlite_counts',counts==COUNTS,counts)
 check('status_counts',dict(db.execute('SELECT status,COUNT(*) FROM orders GROUP BY status').fetchall())==STATUS)
 check('line_types',dict(db.execute('SELECT line_type,COUNT(*) FROM order_lines GROUP BY line_type').fetchall())==TYPES)
 check('all_dates',db.execute("SELECT COUNT(*) FROM orders WHERE order_date IS NULL OR order_date NOT GLOB '????-??-??'").fetchone()[0]==0)
 check('order_equations',db.execute('SELECT COUNT(*) FROM orders WHERE order_payable!=item_amount+voucher_amount+points_amount+shipping_amount').fetchone()[0]==0)
 check('line_discount_equations',db.execute("SELECT COUNT(*) FROM order_lines WHERE line_type='item' AND (quantity*unit_price-line_discount!=line_amount OR line_discount<0)").fetchone()[0]==0)
 check('point_redemptions',db.execute("SELECT COUNT(*) FROM order_lines WHERE line_type='points_redemption' AND line_amount!=-100*redeemed_points").fetchone()[0]==0)
 check('no_unmapped_items',db.execute("SELECT COUNT(*) FROM order_lines l LEFT JOIN catalog c ON c.product_name=l.product_name WHERE l.line_type='item' AND c.product_name IS NULL").fetchone()[0]==0)
 check('adjustment_signs',db.execute("SELECT COUNT(*) FROM order_lines WHERE (line_type IN ('voucher','points_redemption') AND line_amount>=0) OR (line_type='shipping_fee' AND line_amount<0)").fetchone()[0]==0)
 # Reconcile raw source JSON against mart using an independent money implementation.
 raw_lines={(r['source_file'],r['sheet'],r['source_row']):dict(r) for r in db.execute('SELECT * FROM order_lines')}
 ref=collections.defaultdict(collections.Counter);raw_errors=[];source_sales=0
 for r in db.execute('SELECT * FROM source_rows'):
  if not r['source_file'].startswith('BanHang_'):continue
  x=json.loads(r['raw_json']);oid=str(x.get('HĐ') or '').strip()
  if not re.fullmatch(r'ORD\d+',oid):continue
  source_sales+=1;key=(r['source_file'],r['sheet'],r['source_row']);line=raw_lines.get(key)
  if not line:
   raw_errors.append((key,'missing line'));continue
  value=money(x.get('TT'))
  if value!=line['line_amount']:raw_errors.append((key,'money parity'))
  kind=line['line_type'];ref[oid][kind]+=value or 0
  if kind=='item':
   if money(x.get('ĐG'))!=line['unit_price'] or int(x['SL'])*line['unit_price']-value!=line['line_discount']:
    raw_errors.append((key,'line discount parity'))
  if kind=='points_redemption':
   points=int(re.search(r'\d+',x['Tên hàng']).group())
   if value!=-100*points or points!=line['redeemed_points']:raw_errors.append((key,'point parity'))
 for row in db.execute('SELECT * FROM orders'):
  oid=row['order_id'];totals=ref[oid]
  for kind,column in (('item','item_amount'),('voucher','voucher_amount'),('points_redemption','points_amount'),('shipping_fee','shipping_amount')):
   if totals[kind]!=row[column]:raw_errors.append((oid,kind+' aggregate'))
 check('raw_source_money_reconciliation',not raw_errors,raw_errors[:5])
 check('source_order_coverage',len(ref)==11834)
 check('source_line_coverage',source_sales==32153)
 source_sales_rows=sum(1 for f,indices in [('BanHang_2025.xlsx',range(1,9)),('BanHang_2026.xlsx',range(1,7))] for i in indices for _ in all_rows(source/f,i,header_rows=2))
 manager_rows=sum(1 for sn in range(1,5) for _ in manager(source/'QuanLy.xlsx',sn))
 mart_rows=db.execute('SELECT COUNT(*) FROM source_rows').fetchone()[0]
 check('all_workbook_rows_staged',source_sales_rows+manager_rows==mart_rows,{'source':source_sales_rows+manager_rows,'sqlite':mart_rows})
 summaries={s:{'orders':n,'items_vnd':it,'revenue_excluding_shipping_vnd':it+v+p,'shipping_vnd':ship,'payable_vnd':total} for s,n,it,v,p,ship,total in db.execute('SELECT status,COUNT(*),SUM(item_amount),SUM(voucher_amount),SUM(points_amount),SUM(shipping_amount),SUM(order_payable) FROM orders GROUP BY status')}
 schema={name:[r[1] for r in db.execute('PRAGMA table_info('+name+')')] for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
 db.close()
 qa={'source_to_mart_pass':not errors,'failed_checks':errors,'checks':checks,'source_orders':len(ref),'source_lines':source_sales,'source_sha256':manifest['source_sha256']}
 write(candidate/'financial_qa_report.json',qa)
 kpis={
 'completed_order_count':{'measure':'COUNT(*)','filter':"status='completed'",'date':'order_date'},
 'completed_item_revenue':{'measure':'SUM(item_amount)','filter':"status='completed'",'unit':'VND','date':'order_date'},
 'completed_order_revenue_excluding_shipping':{'measure':'SUM(item_amount+voucher_amount+points_amount)','filter':"status='completed'",'unit':'VND','date':'order_date'},
 'cancelled_order_count':{'measure':'COUNT(*)','filter':"status='cancelled'",'date':'order_date'},
 'shipping_order_count':{'measure':'COUNT(*)','filter':"status='shipping'",'date':'order_date'}}
 gate={'shop':'dev_013','version':'dev013-v1','approval':'PRODUCTION_APPROVED' if not errors else 'BLOCKED','gate_pass':not errors,'failed_checks':errors,'status_totals':summaries,'kpi_contract':kpis if not errors else {},'source_sha256':manifest['source_sha256'],'sqlite_sha256':sha(dbpath),'unsupported':['historical_loyalty_point_balance','net_profit','historical_inventory']}
 write(candidate/'release_gate_report.json',gate)
 if errors:raise RuntimeError('Release BLOCKED: '+', '.join(errors))
 if release.exists():raise RuntimeError('Release exists, refusing overwrite: '+str(release))
 release.parent.mkdir(parents=True,exist_ok=True)
 temp=pathlib.Path(tempfile.mkdtemp(prefix='.dev013_release_',dir=release.parent))
 try:
  for f in ('dev_013.sqlite','financial_qa_report.json','release_gate_report.json'):
   shutil.copy2(candidate/f,temp/f)
  shutil.copy2(candidate/'candidate_report.json',temp/'qa_report.json')
  write(temp/'schema_contract.json',{'approval':'PRODUCTION_APPROVED','shop':'dev_013','version':'dev013-v1','tables':schema,'kpi_contract':kpis,'unsupported':gate['unsupported']})
  files={f.name:{'sha256':sha(f),'bytes':f.stat().st_size} for f in temp.iterdir()}
  write(temp/'manifest.json',{'approval':'PRODUCTION_APPROVED','shop':'dev_013','version':'dev013-v1','source_sha256':manifest['source_sha256'],'files':files,'kpis_supported':list(kpis)})
  os.rename(temp,release)
 except BaseException:
  shutil.rmtree(temp,ignore_errors=True);raise
 print(json.dumps({'gate_pass':True,'approval':'PRODUCTION_APPROVED','failed_checks':[],'supported_kpis':list(kpis),'status_totals':summaries,'release_dir':str(release),'release_files':sorted(f.name for f in release.iterdir())},ensure_ascii=False,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);p.add_argument('--release',required=True);a=p.parse_args()
 run(pathlib.Path(a.source),pathlib.Path(a.candidate),pathlib.Path(a.release))
