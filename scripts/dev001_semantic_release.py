#!/usr/bin/env python3
"""dev001 one-file retail semantic acceptance and controlled production release.

Physical daily-total rows are NOT sold lines. Return/cancelled invoice excludes
the WHOLE invoice. Revenue uses each line's Thành tiền, without order-level
adjustments; quantity uses source Số lượng quy đổi (base units).
"""
import argparse,datetime as dt,hashlib,json,sqlite3,shutil,sys
from collections import defaultdict
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from openpyxl import load_workbook

SHOP='dev_001'
SHEET='Sheet1'
STATUS={'Hoàn thành':'completed','đã xong':'completed',
 'Đã hủy đơn':'cancelled','khách hủy':'cancelled',
 'Đã hoàn hàng':'returned','hàng trả về':'returned',
 'Đang giao hàng':'shipping'}
METRICS=('invoice_revenue','eligible_order_count','cancelled_order_count',
 'cancel_rate','returned_order_count','units_sold_base','avg_invoice_revenue')

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for part in iter(lambda:f.read(1048576),b''):h.update(part)
 return h.hexdigest()

def amount(value):
 if value is None:raise ValueError('missing sale amount')
 try:decimal=Decimal(str(value).strip().replace(',',''))
 except Exception as exc:raise ValueError('invalid sale amount '+repr(value)) from exc
 if decimal!=decimal.to_integral_value():raise ValueError('fractional VND')
 return int(decimal)

def order_day(value):
 if isinstance(value,dt.datetime):return value.date().isoformat()
 return dt.datetime.strptime(str(value),'%d/%m/%Y').date().isoformat()

def read_source(path):
 book=load_workbook(path,read_only=True,data_only=True)
 lines=[];summaries=[];errors=[];copies=[];seen=set()
 try:
  sheet=book[SHEET]
  rows=sheet.iter_rows(values_only=True)
  for rn,values in enumerate(rows,1):
   if rn<=4 or not any(x is not None and str(x).strip() for x in values):continue
   row=(list(values)+[None]*10)[:10]
   day,code,name,unit,quantity,price,value,status,base_qty,customer=row
   if not code:
    if str(customer or '').strip().lower().startswith('cộng ngày'):
     summaries.append(rn)
    else:errors.append(f'row {rn}: source without invoice code and no daily total')
    continue
   try:
    key=tuple(row)
    if key in seen:
     copies.append(rn);continue
    seen.add(key)
    st=STATUS[str(status)]
    lines.append({'rn':rn,'code':str(code),'date':order_day(day),
      'status':st,'item':str(name),'amount':amount(value),'base_qty':int(base_qty),
      'unit':str(unit or ''),'customer':str(customer or '')})
   except (KeyError,ValueError,TypeError) as exc:
    errors.append(f'row {rn}: {exc}')
 finally:book.close()
 groups={}
 for line in lines:
  code=line['code']
  if code not in groups:
   groups[code]={'code':code,'date':line['date'],'status':line['status'],
                  'amount':0,'base_qty':0}
  group=groups[code]
  if group['date']!=line['date'] or group['status']!=line['status']:
   errors.append('conflicting date/status inside invoice '+code)
  group['amount']+=line['amount']
  group['base_qty']+=line['base_qty']
 return lines,list(groups.values()),summaries,copies,errors

def totals(groups):
 accepted=[g for g in groups if g['status'] in ('completed','shipping')]
 c=sum(g['status']=='cancelled' for g in groups)
 r=sum(g['status']=='returned' for g in groups)
 count=len(accepted);revenue=sum(g['amount'] for g in accepted)
 return {'invoice_count':len(groups),'eligible_order_count':count,
   'cancelled_order_count':c,'returned_order_count':r,'eligible_revenue_vnd':revenue,
   'base_units_sold':sum(g['base_qty'] for g in accepted),
   'cancel_rate_percent':float((Decimal(c)*100/len(groups)).quantize(
       Decimal('.01'),rounding=ROUND_HALF_UP)) if groups else 0.0,
   'avg_invoice_revenue_vnd':int((Decimal(revenue)/count).quantize(
       Decimal('1'),rounding=ROUND_HALF_UP)) if count else 0}

def acceptance(source,candidate):
 lines,groups,summaries,copies,errors=read_source(source)
 with sqlite3.connect(f'file:{Path(candidate).resolve()}?mode=ro',uri=True) as db:
  if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':errors.append('SQLite integrity')
  cat=json.loads(db.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
  if cat.get('shop_id')!=SHOP or cat.get('approval_status')!='CANDIDATE_NOT_APPROVED':
   errors.append('wrong source shop or already approved')
  sources=db.execute("""SELECT source_id,source_sha256 FROM raw_sources
      WHERE shop_id=? AND source_object=? AND source_path LIKE '%So_chi_tiet_ban_hang.xlsx'""",
      (SHOP,SHEET)).fetchall()
  if len(sources)!=1:errors.append('sales workbook source missing')
  else:
   sid,hashval=sources[0]
   if digest(source)!=hashval:errors.append('source file SHA mismatch')
   physical={r['rn'] for r in lines}|set(summaries)|set(copies)
   staged={rn for rn, in db.execute('SELECT source_row FROM staging_rows WHERE source_id=?',(sid,))}
   if physical!=staged:errors.append('physical sales source rows != staging')
   actual={rn:code for rn,code in db.execute('SELECT source_row,source_business_id FROM order_lines WHERE source_id=?',(sid,))}
   expected={r['rn']:r['code'] for r in lines}
   if copies:
    # Original physical duplicates must be in staging and excluded only on release.
    # This snapshot is expected to have zero exact duplicate lines.
    errors.append('duplicate physical lines require explicit duplicate provenance '+str(len(copies)))
   if expected!=actual:errors.append('candidate sales mart source keys mismatch')
   if any(rn in actual for rn in summaries):errors.append('daily total counted as sale line')
  if db.execute('SELECT COUNT(*) FROM orders WHERE shop_id=?',(SHOP,)).fetchone()[0]:
   errors.append('invented invoice headers in source line-only shop')
  return {'shop_id':SHOP,'family':'retail_single_export',
    'accepted':not errors,'source_line_rows':len(lines),
    'daily_subtotal_rows':len(summaries),'duplicate_source_copies':len(copies),
    'kpis':totals(groups),'errors':errors[:30],'error_count':len(errors),
    'production_approved':False}

def query_kpi(db,metric,*,start_date,end_date,as_of_date):
 cat=json.loads(db.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
 if cat.get('shop_id')!=SHOP or cat.get('approval_status')!='PRODUCTION_APPROVED' or metric not in cat.get('approved_metrics',[]):
  raise ValueError('Unapproved metric for dev001')
 a=dt.date.fromisoformat(start_date);b=dt.date.fromisoformat(end_date)
 cutoff=dt.date.fromisoformat(as_of_date)
 if b<a:raise ValueError('Invalid period')
 bounds=db.execute('SELECT MIN(order_date),MAX(order_date) FROM family_order_facts').fetchone()
 if not bounds[0] or b.isoformat()<bounds[0] or a.isoformat()>bounds[1] or a>cutoff:
  raise ValueError('Unanswerable: period outside published coverage')
 data=db.execute('''SELECT status,revenue_vnd,base_qty FROM family_order_facts
     WHERE order_date BETWEEN ? AND ?''',(a.isoformat(),min(b,cutoff).isoformat())).fetchall()
 valid=[r for r in data if r[0] in ('completed','shipping')]
 cancelled=sum(r[0]=='cancelled' for r in data)
 if metric=='invoice_revenue':return sum(r[1] for r in valid)
 if metric=='eligible_order_count':return len(valid)
 if metric=='cancelled_order_count':return cancelled
 if metric=='returned_order_count':return sum(r[0]=='returned' for r in data)
 if metric=='units_sold_base':return sum(r[2] for r in valid)
 if metric=='cancel_rate':
  return float((Decimal(100)*cancelled/len(data)).quantize(
    Decimal('.01'),rounding=ROUND_HALF_UP)) if data else 0.0
 if metric=='avg_invoice_revenue':
  return int((Decimal(sum(r[1] for r in valid))/len(valid)).quantize(
    Decimal('1'),rounding=ROUND_HALF_UP)) if valid else 0
 raise ValueError('Unsupported metric')

def publish(source,candidate,out,approver):
 source=Path(source);candidate=Path(candidate);out=Path(out)
 if out.exists():raise ValueError('Refusing to overwrite release')
 qa=acceptance(source,candidate)
 if not qa['accepted']:raise ValueError('QA failed: '+repr(qa['errors'][:8]))
 lines,groups,summaries,copies,errors=read_source(source)
 out.mkdir(parents=True,exist_ok=False)
 (out/'qa_report.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2)+'\n')
 target=out/'dev_001.sqlite';shutil.copy2(candidate,target)
 with sqlite3.connect(target) as db:
  cat=json.loads(db.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
  db.execute('''CREATE TABLE family_order_facts(
      invoice_code TEXT PRIMARY KEY,order_date TEXT NOT NULL,status TEXT NOT NULL,
      revenue_vnd INTEGER NOT NULL,base_qty INTEGER NOT NULL)''')
  db.executemany('INSERT INTO family_order_facts VALUES(?,?,?,?,?)',[
      (r['code'],r['date'],r['status'],r['amount'],r['base_qty']) for r in groups])
  db.execute('''CREATE TABLE family_sales_line_facts(
      source_row INTEGER PRIMARY KEY,invoice_code TEXT NOT NULL,
      item_name TEXT NOT NULL,order_date TEXT NOT NULL,status TEXT NOT NULL,
      revenue_vnd INTEGER NOT NULL,base_qty INTEGER NOT NULL)''')
  db.executemany('INSERT INTO family_sales_line_facts VALUES(?,?,?,?,?,?,?)',[
      (r['rn'],r['code'],r['item'],r['date'],r['status'],r['amount'],r['base_qty']) for r in lines])
  sid=db.execute("""SELECT source_id FROM raw_sources WHERE shop_id=?
      AND source_object=? AND source_path LIKE '%So_chi_tiet_ban_hang.xlsx'""",
      (SHOP,SHEET)).fetchone()[0]
  db.executemany('''UPDATE order_lines SET event_date=?,amount=?,quantity=?,status_raw=?
      WHERE shop_id=? AND source_id=? AND source_row=?''',[
      (r['date'],str(r['amount']),str(r['base_qty']),r['status'],SHOP,sid,r['rn'])
       for r in lines])
  for rn in summaries:
   db.execute('UPDATE staging_rows SET parsed_json=? WHERE source_id=? AND source_row=?',
     (json.dumps({'classification':'DAILY_TOTAL_NOT_SALE','count_in_kpi':False}),sid,rn))
   db.execute("""UPDATE validation_issues SET severity='INFO',code='SOURCE_DAILY_TOTAL_NOT_SALE'
      WHERE source_id=? AND source_row=? AND code IN ('UNLINKED_LINE','MISSING_LINE_IDENTIFIERS')""",
      (sid,rn))
  cat['validation_status']='APPROVED';cat['approval_status']='PRODUCTION_APPROVED'
  cat['approved_metrics']=list(METRICS);cat['approved_by']=approver
  cat['approved_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
  cat['approval_evidence']='qa_report.json'
  cat['metric_notes']={'invoice_revenue':'source Thành tiền, excluding entire returned/cancelled invoices',
    'units_sold_base':'source Số lượng quy đổi, all eligible invoice item lines'}
  db.execute('UPDATE business_catalog SET catalog_json=?',(json.dumps(cat,ensure_ascii=False),))
  db.execute("UPDATE dataset_versions SET status='APPROVED' WHERE shop_id=?",(SHOP,))
  db.commit()
  if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
   raise ValueError('Release SQLite integrity failed')
  first,last=db.execute('SELECT MIN(order_date),MAX(order_date) FROM family_order_facts').fetchone()
  comparisons={'invoice_revenue':'eligible_revenue_vnd','eligible_order_count':'eligible_order_count',
    'units_sold_base':'base_units_sold','cancel_rate':'cancel_rate_percent',
    'avg_invoice_revenue':'avg_invoice_revenue_vnd'}
  for metric,field in comparisons.items():
   found=query_kpi(db,metric,start_date=first,end_date=last,as_of_date=last)
   if found!=qa['kpis'][field]:raise ValueError('M03 smoke mismatch: '+metric)
 manifest={'shop_id':SHOP,'family':'retail_single_export','release_id':str(uuid4()),
   'source_dataset_version':cat['version_id'],'approval_status':'PRODUCTION_APPROVED',
   'approved_by':approver,'approved_at_utc':cat['approved_at_utc'],
   'approved_metrics':list(METRICS),'source_sha256':digest(source),
   'candidate_sha256':digest(candidate),'database_sha256':digest(target),
   'source_invoice_count':len(groups),'excluded_daily_totals':len(summaries),
   'eligible_revenue_vnd':qa['kpis']['eligible_revenue_vnd'],
   'files':['dev_001.sqlite','qa_report.json','manifest.json']}
 (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 return manifest

def main():
 p=argparse.ArgumentParser()
 p.add_argument('--source',type=Path,required=True)
 p.add_argument('--candidate',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True)
 p.add_argument('--report',type=Path)
 p.add_argument('--approve',action='store_true')
 p.add_argument('--approved-by',default='')
 a=p.parse_args()
 try:
  if a.approve:
   if not a.approved_by.strip():p.error('Human approver required')
   result=publish(a.source,a.candidate,a.output,a.approved_by)
  else:
   result=acceptance(a.source,a.candidate)
   if a.report:
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
  print(json.dumps(result,ensure_ascii=False,indent=2))
  if not a.approve and not result['accepted']:raise SystemExit(2)
 except (ValueError,sqlite3.Error) as exc:
  print('DEV001 RELEASE BLOCKED:',exc,file=sys.stderr)
  raise SystemExit(2)

if __name__=='__main__':main()
