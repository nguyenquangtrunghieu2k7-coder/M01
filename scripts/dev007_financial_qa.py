#!/usr/bin/env python3
"""dev007 independent raw-CSV financial reconciliation, with full source lineage."""
import argparse,csv,collections,datetime,hashlib,json,pathlib,re,sqlite3
from decimal import Decimal
FILES=('chi_tiet_hoa_don.csv','danh_muc_hang.csv','chi_tiet_nhap_hang.csv')
STATUS={'Xong':'completed','Đã hủy đơn':'cancelled','Đã trả hàng':'returned','Đang xử lý':'in_progress'}
def text(x):return str(x or '').strip()
def number(x):
 s=text(x).lower().replace(' ','').replace('đ','').replace('₫','')
 if not s:return None
 factor=-1 if s.startswith('-') else 1;s=s.lstrip('-')
 if s.endswith('k'):
  try:return factor*int(Decimal(s[:-1].replace(',','.'))*1000)
  except Exception:return None
 if 'tr' in s:
  m=re.fullmatch(r'(\d+(?:[,.]\d+)?)tr(\d{0,3})',s)
  return factor*int(Decimal(m[1].replace(',','.'))*1000000+(int(m[2])*10**(6-len(m[2])) if m[2] else 0)) if m else None
 if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',s):return factor*int(re.sub('[.,]','',s))
 if s.isdigit():return factor*int(s)
 return None
def date(x):
 s=text(x)
 if re.fullmatch(r'\d{5}',s):return (datetime.date(1899,12,30)+datetime.timedelta(days=int(s))).isoformat()
 try:return datetime.datetime.strptime(s,'%d/%m/%Y').date().isoformat()
 except ValueError:return None
def csv_rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:
  yield from enumerate(csv.DictReader(f),2)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser();a.add_argument('--source',required=True);a.add_argument('--candidate',required=True);args=a.parse_args()
 src=pathlib.Path(args.source);folder=pathlib.Path(args.candidate)
 con=sqlite3.connect('file:'+str((folder/'dev_007.sqlite').resolve())+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
 errs=collections.Counter();samples=collections.defaultdict(list);checks={};order_ref={};line_ref={};dups={};raw_count={}
 def problem(k,d):
  errs[k]+=1
  if len(samples[k])<5:samples[k].append(d)
 for f in FILES:raw_count[f]=sum(1 for _ in csv_rows(src/f))
 source_catalog={text(r['Mã SKU']):r for i,r in csv_rows(src/FILES[1])}
 source_purchases={i:r for i,r in csv_rows(src/FILES[2])}
 for i,r in csv_rows(src/FILES[0]):
  oid=text(r['Mã bill'])
  if not re.fullmatch(r'ORD\d+',oid):continue
  header=(date(r['Ngày giao dịch']),text(r['Giờ bán']),text(r['Tiến độ']),text(r['Nguồn']),text(r['Bàn']),text(r['Khu vực']),number(r['Số khách']),text(r['Họ tên khách']),number(r['Tổng tiền hàng']),number(r['Giảm giá HĐ']),number(r['Khách trả']),number(r['Còn nợ']))
  if oid in order_ref and order_ref[oid][0]!=header:problem('SOURCE_HEADER_CONFLICT',{'order_id':oid,'row':i})
  else:order_ref.setdefault(oid,(header,i))
  sig=tuple((key,text(val)) for key,val in sorted(r.items()))
  if not hasattr(main,'seen'):main.seen={}
  if sig in main.seen:
   dups[i]=(main.seen[sig],oid,number(r['Thành tiền']))
   continue
  main.seen[sig]=i
  line_ref[i]=(oid,number(r['No.']),text(r['Mã vạch']),text(r['Mặt hàng']),number(r['Sluong']),number(r['Số lượng lẻ']),number(r['Đơn giá (đ)']),number(r['Tiền giảm']),number(r['Thành tiền']),int(text(r['Mặt hàng'])=='Phí phục vụ'))
 db_orders={r['order_id']:r for r in con.execute('SELECT * FROM orders')}
 db_lines={r['source_row']:r for r in con.execute('SELECT * FROM order_lines')}
 db_dups={r['duplicate_source_row']:(r['retained_source_row'],r['order_id'],r['duplicate_amount']) for r in con.execute('SELECT * FROM dedup_lineage')}
 if db_dups!=dups:problem('DUPLICATE_LINEAGE',{'expected':len(dups),'actual':len(db_dups),'expected_amount':sum(v[2] or 0 for v in dups.values())})
 if len(db_orders)!=len(order_ref):problem('ORDER_COUNT',{'source':len(order_ref),'db':len(db_orders)})
 if len(db_lines)!=len(line_ref):problem('LINE_COUNT',{'source':len(line_ref),'db':len(db_lines)})
 totals=collections.defaultdict(int);statuses=collections.Counter();fees=collections.Counter()
 for i,(oid,no,sku,name,qty,base,price,disc,amount,service) in line_ref.items():
  totals[oid]+=amount if amount is not None else 0
  db=db_lines.get(i)
  if db is None:problem('MISSING_DB_LINE',i);continue
  fields=('order_id','line_no','sku','product_name','quantity','base_quantity','unit_price','line_discount','line_total','is_service_fee')
  for col,x in zip(fields,(oid,no,sku,name,qty,base,price,disc,amount,service)):
   if db[col]!=x:problem('LINE_FIELD',{'row':i,'column':col,'source':x,'db':db[col]})
  if None in (qty,base,price,disc,amount) or qty*price-disc!=amount:problem('LINE_MONEY_EQUATION',i)
 for oid,(head,source_row) in order_ref.items():
  date_val,at,raw_status,channel,table,area,people,customer,items,discount,paid,debt=head
  status=STATUS.get(raw_status);statuses[status]+=1
  delivery_fee=15000 if status in ('completed','in_progress') and channel in ('phone','zalo_oa') else 0
  fees[delivery_fee]+=1
  fields={'order_date':date_val,'ordered_at':at,'raw_status':raw_status,'status':status,'channel':channel,'table_name':table,'area':area,'customer_count':people,'customer_name':customer,'items_total':items,'invoice_discount':discount,'customer_paid':paid,'outstanding_snapshot':debt,'delivery_fee_inferred':delivery_fee,'source_row':source_row}
  record=db_orders.get(oid)
  if record is None:problem('MISSING_DB_ORDER',oid);continue
  for field,value in fields.items():
   if record[field]!=value:problem('ORDER_FIELD',{'order_id':oid,'field':field,'source':value,'db':record[field]})
  if totals[oid]!=items:problem('ORDER_ITEM_TOTAL',{'order_id':oid,'expected':items,'lines':totals[oid]})
  if status=='cancelled':
   if paid!=0 or debt!=0:problem('CANCELLED_CASH',oid)
  elif None in (items,discount,paid,debt) or paid+debt!=items-discount+delivery_fee:
   problem('PAYMENT_EQUATION',{'order_id':oid,'status':status,'paid':paid,'debt':debt,'items':items,'discount':discount,'fee':delivery_fee})
 for f in FILES:
  n=con.execute('SELECT COUNT(*) FROM source_rows WHERE source_file=?',(f,)).fetchone()[0]
  if n!=raw_count[f]:problem('SOURCE_ROW_COVERAGE',{'file':f,'source':raw_count[f],'db':n})
 db_catalog={r['sku']:r for r in con.execute('SELECT * FROM catalog')}
 if len(source_catalog)!=len(db_catalog):problem('CATALOG_COUNT',{'source':len(source_catalog),'db':len(db_catalog)})
 for sku,rec in source_catalog.items():
  db=db_catalog.get(sku)
  if db is None:problem('MISSING_CATALOG_PRODUCT',sku);continue
  for k,column in [('Hàng bán','product_name'),('Nhóm','group_name'),('ĐVT','base_unit'),('Giá vốn','unit_cost_snapshot'),('Tồn cuối','inventory_snapshot')]:
   expected=number(rec[k]) if k in ('Giá vốn','Tồn cuối') else text(rec[k])
   if db[column]!=expected:problem('CATALOG_FIELD',{'sku':sku,'field':k})
 db_purchases={r['source_row']:r for r in con.execute('SELECT * FROM purchase_lines')}
 if len(source_purchases)!=len(db_purchases):problem('PURCHASE_COUNT',{})
 receipt_total=collections.defaultdict(int);receipt_headers=collections.defaultdict(set)
 for i,r in source_purchases.items():
  db=db_purchases.get(i)
  if db is None:problem('MISSING_PURCHASE',i);continue
  ref={'receipt_id':text(r['Mã phiếu nhập']),'sku':text(r['Mã hàng bán']),'quantity':number(r['SL nhập']),'unit':text(r['ĐVT nhập']),'unit_cost':number(r['Giá nhập']),'line_total':number(r['Thành tiền']),'receipt_total':number(r['Tổng tiền phiếu']),'purchase_date':date(r['Ngày nhập'])}
  for field,value in ref.items():
   if db[field]!=value:problem('PURCHASE_FIELD',{'row':i,'field':field})
  receipt_total[ref['receipt_id']]+=ref['line_total'] or 0
  receipt_headers[ref['receipt_id']].add(ref['receipt_total'])
 for rid,total in receipt_total.items():
  if receipt_headers[rid]!={total}:problem('RECEIPT_SUM',{'receipt_id':rid,'sum':total,'headers':list(receipt_headers[rid])})
 if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':problem('DB_INTEGRITY',{})
 if con.execute('PRAGMA foreign_key_check').fetchall():problem('FOREIGN_KEYS',{})
 if con.execute('SELECT COUNT(*) FROM mapping_issues').fetchone()[0]:problem('DB_MAPPING_ISSUES',{})
 con.close()
 report={'shop':'dev_007','approval':'CANDIDATE_NOT_APPROVED','source_to_mart_pass':not errs,'source_hashes':{f:sha(src/f) for f in FILES},'source_rows':raw_count,'orders':len(order_ref),'unique_lines':len(line_ref),'duplicates':len(dups),'duplicates_amount_vnd':sum(v[2] or 0 for v in dups.values()),'status_counts':dict(statuses),'fees_per_order_vnd':dict(fees),'mismatches':dict(errs),'examples':dict(samples)}
 (folder/'financial_qa_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'report':str(folder/'financial_qa_report.json'),'source_to_mart_pass':report['source_to_mart_pass'],'counts':{k:report[k] for k in ('orders','unique_lines','duplicates','duplicates_amount_vnd')},'statuses':report['status_counts'],'fee_distribution':report['fees_per_order_vnd'],'mismatches':report['mismatches'],'examples':{k:v[:2] for k,v in samples.items()}},ensure_ascii=False,indent=2))
 if errs:raise SystemExit(1)
if __name__=='__main__':main()
