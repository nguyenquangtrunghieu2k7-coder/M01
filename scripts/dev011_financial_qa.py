#!/usr/bin/env python3
"""Independent source-to-mart reconciliation for dev_011; source read-only."""
import argparse,collections,datetime,hashlib,json,pathlib,sqlite3
from decimal import Decimal
from dev011_source_audit import table
RETURN_TERMS=('trả lại','trả hàng','mang trả','hoàn')
def text(v):return str(v if v is not None else '').strip()
def number(v):
 if not text(v):return None
 try:
  x=Decimal(text(v));return int(x) if x==int(x) else None
 except (ValueError,ArithmeticError):return None
def day(v):
 try:return (datetime.date(1899,12,30)+datetime.timedelta(days=int(text(v)))).isoformat()
 except (ValueError,TypeError,OverflowError):return None
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);a=p.parse_args()
 source=pathlib.Path(a.source);source=source/'SoBanHang.xlsx' if source.is_dir() else source
 out=pathlib.Path(a.candidate);catalog=list(table(source,1));rows=list(table(source,2))
 abbr={text(r['Ghi tắt']):(text(r['Tên hàng']),text(r['Loại'])) for _,r in catalog}
 names={x[0]:x for x in abbr.values()}
 orders={};lines={};sums=collections.Counter();errors=collections.Counter();samples=collections.defaultdict(list);current=None
 def fail(code,detail):
  errors[code]+=1
  if len(samples[code])<6:samples[code].append(detail)
 for row,r in rows:
  stt=number(r['STT'])
  if stt is not None:
   current=stt
   if stt in orders:fail('DUPLICATE_SOURCE_ORDER',{'order_id':stt,'row':row})
   note=text(r['Ghi chú'])
   orders[stt]={'order_date':day(r['Ngày']),'customer_raw':text(r['Khách']),'status':'returned' if any(x in note.lower() for x in RETURN_TERMS) else 'completed','note':note,'order_discount':number(r['Bớt']) if text(r['Bớt']) else 0,'trade_in_credit':number(r['Thu máy cũ']) if text(r['Thu máy cũ']) else 0,'customer_paid':number(r['Khách trả']),'source_row':row}
  if current is None:fail('ORPHAN_LINE',{'row':row});continue
  name=text(r['Hàng']);product=abbr.get(name) or names.get(name)
  if product is None:fail('UNMAPPED_ITEM',{'row':row,'name':name});continue
  qty=number(r['SL']);price=number(r['Giá']);total=number(r['Thành tiền'])
  if None in (qty,price,total):fail('UNPARSEABLE_LINE',{'row':row});continue
  if qty*price!=total:fail('LINE_EQUATION',{'row':row})
  sums[current]+=total
  lines[row]={'order_id':current,'raw_item':name,'product_name':product[0],'product_type':product[1],'imei_raw':text(r['IMEI']),'quantity':qty,'unit_price':price,'line_total':total}
 for oid,r in orders.items():
  r['items_gross']=sums[oid]
  if r['items_gross']-r['order_discount']-r['trade_in_credit']!=r['customer_paid']:fail('ORDER_EQUATION',{'order_id':oid})
 db=sqlite3.connect('file:'+str((out/'dev_011.sqlite').resolve())+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 db_orders={r['order_id']:dict(r) for r in db.execute('SELECT * FROM orders')}
 db_lines={r['source_row']:dict(r) for r in db.execute('SELECT * FROM order_lines')}
 for oid,src in orders.items():
  dest=db_orders.get(oid)
  if dest is None:fail('MISSING_DB_ORDER',{'order_id':oid});continue
  for field,value in src.items():
   if dest[field]!=value:fail('ORDER_FIELD_PARITY',{'order_id':oid,'field':field,'expected':value,'actual':dest[field]})
 for row,src in lines.items():
  dest=db_lines.get(row)
  if dest is None:fail('MISSING_DB_LINE',{'source_row':row});continue
  for field,value in src.items():
   if dest[field]!=value:fail('LINE_FIELD_PARITY',{'row':row,'field':field,'expected':value,'actual':dest[field]})
 if len(db_orders)!=len(orders):fail('DB_ORDER_COUNT',{'source':len(orders),'db':len(db_orders)})
 if len(db_lines)!=len(lines):fail('DB_LINE_COUNT',{'source':len(lines),'db':len(db_lines)})
 if db.execute('SELECT COUNT(*) FROM source_rows').fetchone()[0]!=len(catalog)+len(rows):fail('SOURCE_LINEAGE',{})
 if db.execute('SELECT COUNT(*) FROM product_aliases').fetchone()[0]!=len(catalog):fail('CATALOG_COUNT',{})
 if db.execute('SELECT COUNT(*) FROM mapping_issues').fetchone()[0]:fail('DB_MAPPING_ISSUES',{})
 if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':fail('DB_INTEGRITY',{})
 if db.execute('PRAGMA foreign_key_check').fetchall():fail('DB_FOREIGN_KEYS',{})
 db.close()
 statuses=dict(collections.Counter(x['status'] for x in orders.values()))
 trade=sum(bool(x['trade_in_credit']) for x in orders.values())
 report={'approval':'CANDIDATE_NOT_APPROVED','source_to_mart_pass':not errors,'independent_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_orders':len(orders),'source_lines':len(lines),'catalog_rows':len(catalog),'status_orders':statuses,'trade_in_orders':trade,'equations_checked':len(orders),'mismatch_counts':dict(errors),'samples':dict(samples),'kpis_supported':[]}
 target=out/'financial_qa_report.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps({'report':str(target),'source_to_mart_pass':report['source_to_mart_pass'],'orders':len(orders),'lines':len(lines),'status_orders':statuses,'trade_in_orders':trade,'equations_checked':len(orders),'mismatch_counts':dict(errors),'samples':{k:v[:3] for k,v in samples.items()}},ensure_ascii=False,indent=2))
 if errors:raise SystemExit(1)
if __name__=='__main__':main()
