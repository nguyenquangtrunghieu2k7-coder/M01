#!/usr/bin/env python3
"""Independent dev003 source-to-SQLite audit; parses XLSX without importing adapter."""
import argparse,collections,csv,datetime,hashlib,json,pathlib,re,sqlite3
from decimal import Decimal
from dev011_source_audit import sheet_rows
SOURCES=('BanHang_TongHop_2025.xlsx','BanHang_TongHop_2026.xlsx','BanHang_PhieuThu.xlsx','SoTay_NhapHang.xlsx','SoTay_ChiPhi.xlsx','BaoCaoCa.xlsx','ton_kho.csv')
STAT={'Xong':'completed','Đã hủy đơn':'cancelled','Khách trả':'returned','Đang vận chuyển':'shipping'}
def t(x):return str(x if x is not None else '').strip()
def value(x):
 s=t(x).lower().replace('đ','').replace('₫','').replace(' ','')
 if not s:return None
 sign=-1 if s.startswith('-') else 1
 if sign<0:s=s[1:]
 try:
  if s.endswith('k'):return sign*int(Decimal(s[:-1].replace(',','.'))*1000)
  if s.endswith('tr'):return sign*int(Decimal(s[:-2].replace(',','.'))*1000000)
  if re.fullmatch(r'\d{1,3}(?:[,.]\d{3})+',s):return sign*int(re.sub('[,.]','',s))
  if s.isdigit():return sign*int(s)
 except Exception:return None
 return None
def day(x):
 s=t(x)
 if re.fullmatch(r'\d{5}(?:\.\d+)?',s):return (datetime.datetime(1899,12,30)+datetime.timedelta(days=float(s))).date().isoformat()
 m=re.fullmatch(r'(\d{1,2}) thg (\d{1,2}) (\d{4})',s)
 if m:return datetime.date(int(m[3]),int(m[2]),int(m[1])).isoformat()
 try:return datetime.datetime.strptime(s,'%d/%m/%Y').date().isoformat()
 except ValueError:return None
def read(path,index=1,heading=1):
 it=sheet_rows(path,index)
 for _ in range(heading-1):next(it)
 _,h=next(it)
 for n,v in it:
  if any(t(x) for x in v.values()):yield n,{name:v.get(c) for c,name in h.items()}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def audit(src,folder):
 con=sqlite3.connect('file:'+str((folder/'dev_003.sqlite').resolve())+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
 errors=collections.Counter();examples=collections.defaultdict(list)
 def fail(k,x):
  errors[k]+=1
  if len(examples[k])<5:examples[k].append(x)
 source_orders={};source_lines={};duplicates={};seen={};sums=collections.Counter();payments=collections.Counter();statuses=collections.Counter()
 for f in SOURCES[:2]:
  for n,r in read(src/f):
   oid=t(r['Đơn số'])
   if not re.fullmatch(r'ORD\d+',oid):fail('BAD_ORDER_ID',(f,n,oid));continue
   status=STAT.get(t(r['Trạng thái giao']))
   head=(day(r['Ngày HĐ']),status,t(r['Nguồn']),t(r['Mã khách']),t(r['Mã NV bán']),t(r['Hình thức thanh toán']),value(r['Tiền hàng trước giảm']),value(r['Tiền giảm']),value(r['Phí ship']),value(r['Tổng thanh toán']),value(r['Da tra']),value(r['Công nợ']))
   if oid in source_orders and source_orders[oid]!=head:fail('ORDER_HEADER',(oid,n))
   if oid not in source_orders:source_orders[oid]=head;statuses[status]+=1
   signature=tuple(sorted((k,t(v)) for k,v in r.items()))
   if signature in seen:
    old=seen[signature];duplicates[(f,n)]=(old[0],old[1],oid,value(r['Thành tiền (đ)']))
    continue
   seen[signature]=(f,n)
   qfield=t(r['S.L']);match=re.match(r'^([0-9]+)(?:\s*[a-zA-ZÀ-ỹ]+)?$',qfield)
   q=int(match[1]) if match else None
   row=(oid,value(r['Dòng']),t(r['Barcode']),t(r['Hàng hóa']),t(r['ĐV']),q,value(r['SL (ĐV cơ bản)']),value(r['Giá 1 đv']),value(r['Giảm (đ)']),value(r['Thành tiền (đ)']),value(r['Giá vốn lúc bán']))
   source_lines[(f,n)]=row
   if None in (q,row[7],row[8],row[9]) or q*row[7]-row[8]!=row[9]:fail('SOURCE_LINE_PRICE',(f,n))
   sums[oid]+=row[9] or 0
 db_orders={r['order_id']:r for r in con.execute('SELECT * FROM orders')}
 db_lines={(r['file'],r['row']):r for r in con.execute('SELECT * FROM order_lines')}
 db_dups={(r['file'],r['row']):(r['retained_file'],r['retained_row'],r['order_id'],r['amount']) for r in con.execute('SELECT * FROM exact_duplicate_lines')}
 if db_dups!=duplicates:fail('DUPLICATE_LINEAGE',{'source':len(duplicates),'db':len(db_dups)})
 if len(db_orders)!=len(source_orders):fail('ORDER_COUNT',{'source':len(source_orders),'db':len(db_orders)})
 if len(db_lines)!=len(source_lines):fail('LINE_COUNT',{'source':len(source_lines),'db':len(db_lines)})
 for (f,n),vals in source_lines.items():
  r=db_lines.get((f,n))
  if r is None:fail('MISSING_LINE',(f,n));continue
  for col,v in zip(('order_id','line_no','sku','product','sale_unit','quantity','base_quantity','unit_price','line_discount','line_total','unit_cost'),vals):
   if r[col]!=v:fail('LINE_FIELD',(f,n,col,v,r[col]))
 for oid,h in source_orders.items():
  db=db_orders.get(oid)
  if db is None:fail('MISSING_ORDER',oid);continue
  for col,v in zip(('order_date','status','channel','customer_id','staff_id','payment_method','item_total','discount','shipping','payable','paid_snapshot','debt_snapshot'),h):
   if db[col]!=v:fail('ORDER_FIELD',(oid,col,v,db[col]))
  if sums[oid]!=h[6]:fail('SOURCE_ORDER_ITEM_SUM',(oid,sums[oid],h[6]))
  if h[6]-h[7]+h[8]!=h[9]:fail('SOURCE_ORDER_PAYABLE',oid)
  if h[1]=='cancelled':
   if h[10]!=0 or h[11]!=0:fail('CANCELLED_CASH',oid)
  elif h[10]+h[11]!=h[9]:fail('SOURCE_ORDER_SETTLEMENT',oid)
 receipt_rows=0;db_receipts={r['payment_id']:r for r in con.execute('SELECT * FROM receipts')}
 for n,r in read(src/'BanHang_PhieuThu.xlsx'):
  receipt_rows+=1;pid=t(r['Mã thanh toán']);oid=t(r['Ma don']);amount=value(r['Tiền thu'])
  payments[oid]+=amount or 0
  row=db_receipts.get(pid)
  if row is None:fail('MISSING_RECEIPT',pid);continue
  for col,v in (('order_id',oid),('amount',amount),('payment_date',day(r['Ngày TT'])),('method',t(r['PTTT']))):
   if row[col]!=v:fail('RECEIPT_FIELD',(pid,col))
 if len(db_receipts)!=receipt_rows:fail('RECEIPT_COUNT',(receipt_rows,len(db_receipts)))
 for oid,h in source_orders.items():
  if payments[oid]!=h[10]:fail('SOURCE_PAYMENT_SUM',(oid,payments[oid],h[10]))
 shift_rows=0;shift_money=collections.Counter()
 for n,r in read(src/'BaoCaoCa.xlsx'):
  shift_rows+=1;received=value(r['Tiền mặt thu']);refund=value(r['Tiền mặt hoàn khách']);net=value(r['Tiền mặt ròng của ca'])
  if None in (received,refund,net) or received-refund!=net:fail('SHIFT_SOURCE_EQUATION',n)
  shift_money['cash_received']+=received or 0;shift_money['cash_refunded']+=refund or 0;shift_money['cash_net']+=net or 0
 if con.execute('SELECT COUNT(*) FROM shift_cash').fetchone()[0]!=shift_rows:fail('SHIFT_COUNT',shift_rows)
 for row in con.execute('SELECT source_row,cash_received,cash_refunded,net_cash FROM shift_cash'):
  if row['cash_received']-row['cash_refunded']!=row['net_cash']:fail('SHIFT_DB_EQUATION',row['source_row'])
 for f,table in [('SoTay_NhapHang.xlsx','purchases'),('SoTay_ChiPhi.xlsx','expenses')]:
  header=3;count=0
  for n,r in read(src/f,heading=header):
   count+=1
   if table=='purchases':
    q=value(r['SL nhập']);unit=value(r['Giá nhập']);total=value(r['Thành tiền'])
    if None in (q,unit,total) or q*unit!=total:fail('PURCHASE_SOURCE_EQUATION',n)
   else:
    if value(r['Tiền chi']) is None:fail('EXPENSE_SOURCE_VALUE',n)
  if con.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]!=count:fail('OTHER_SOURCE_COVERAGE',(table,count))
 if con.execute('SELECT COUNT(*) FROM mapping_issues').fetchone()[0]:fail('DB_MAPPING_ISSUES',{})
 if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':fail('SQLITE_INTEGRITY',{})
 if con.execute('PRAGMA foreign_key_check').fetchall():fail('FOREIGN_KEYS',{})
 source_hashes={f:sha(src/f) for f in SOURCES}
 result={'source_to_mart_pass':not errors,'mismatches':dict(errors),'samples':dict(examples),'source_sha256':source_hashes,'orders':len(source_orders),'lines':len(source_lines),'duplicate_rows':len(duplicates),'receipts':receipt_rows,'shifts':shift_rows,'statuses':dict(statuses),'shift_cash_totals':dict(shift_money),'scope':'Source-origin order, line, receipt, refund shift, expense and purchase checks; shift cash is NOT booked sales revenue'}
 con.close()
 (folder/'financial_qa_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'source_to_mart_pass':result['source_to_mart_pass'],'orders':result['orders'],'lines':result['lines'],'duplicate_rows':result['duplicate_rows'],'receipts':receipt_rows,'shifts':shift_rows,'statuses':result['statuses'],'mismatches':result['mismatches'],'samples':{k:v[:2] for k,v in examples.items()}},ensure_ascii=False,indent=2))
 if errors:raise SystemExit(1)
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--source',required=True);a.add_argument('--candidate',required=True);x=a.parse_args();audit(pathlib.Path(x.source),pathlib.Path(x.candidate))
