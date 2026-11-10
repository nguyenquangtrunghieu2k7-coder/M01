#!/usr/bin/env python3
"""Build dev003 coffee POS candidate. Source immutable; never touches other shops."""
import argparse,collections,csv,datetime,hashlib,json,pathlib,re,sqlite3
from decimal import Decimal
from dev011_source_audit import sheet_rows
SALES=('BanHang_TongHop_2025.xlsx','BanHang_TongHop_2026.xlsx')
SOURCES=(*SALES,'BanHang_PhieuThu.xlsx','SoTay_NhapHang.xlsx','SoTay_ChiPhi.xlsx','BaoCaoCa.xlsx','ton_kho.csv')
STATUSES={'Xong':'completed','Đã hủy đơn':'cancelled','Khách trả':'returned','Đang vận chuyển':'shipping'}
def txt(v):return str(v if v is not None else '').strip()
def num(v):
 s=txt(v).lower().replace(' ','').replace('đ','').replace('₫','')
 if not s:return None
 sign=-1 if s.startswith('-') else 1
 if sign<0:s=s[1:]
 try:
  if s.endswith('tr'):return sign*int(Decimal(s[:-2].replace(',','.'))*1000000)
  if s.endswith('k'):return sign*int(Decimal(s[:-1].replace(',','.'))*1000)
  if re.fullmatch(r'\d{1,3}(?:[,.]\d{3})+',s):return sign*int(re.sub('[,.]','',s))
  if re.fullmatch(r'\d+',s):return sign*int(s)
 except Exception:return None
 return None
def qty(v):
 s=txt(v)
 m=re.match(r'^([0-9]+)(?:\s*[a-zA-ZÀ-ỹ]+)?$',s)
 return int(m.group(1)) if m else None
def date(v):
 s=txt(v)
 if not s:return None
 if re.fullmatch(r'\d{5}(?:\.\d+)?',s):
  return (datetime.datetime(1899,12,30)+datetime.timedelta(days=float(s))).date().isoformat()
 m=re.fullmatch(r'(\d{1,2}) thg (\d{1,2}) (\d{4})',s)
 if m:return datetime.date(int(m[3]),int(m[2]),int(m[1])).isoformat()
 try:return datetime.datetime.strptime(s,'%d/%m/%Y').date().isoformat()
 except ValueError:return None
def rows(path,sheet=1,header=1):
 it=sheet_rows(path,sheet)
 for _ in range(header-1):next(it)
 _,h=next(it);head={idx:txt(label) for idx,label in h.items()}
 for rn,cells in it:
  if any(txt(v) for v in cells.values()):yield rn,{label:cells.get(i) for i,label in head.items()}
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def build(source,out):
 if out.exists():raise RuntimeError('Output exists: '+str(out))
 for f in SOURCES:
  if not (source/f).is_file():raise RuntimeError('Source missing: '+f)
 out.mkdir(parents=True)
 db=sqlite3.connect(out/'dev_003.sqlite');db.execute('PRAGMA foreign_keys=ON')
 db.executescript("""
 CREATE TABLE source_rows(file TEXT,sheet TEXT,source_row INTEGER,raw_json TEXT,PRIMARY KEY(file,sheet,source_row));
 CREATE TABLE orders(order_id TEXT PRIMARY KEY,order_date TEXT,source_status TEXT,status TEXT,channel TEXT,customer_id TEXT,customer_name TEXT,staff_id TEXT,payment_method TEXT,item_total INTEGER,discount INTEGER,shipping INTEGER,payable INTEGER,paid_snapshot INTEGER,debt_snapshot INTEGER,source_file TEXT,source_row INTEGER);
 CREATE TABLE order_lines(file TEXT,row INTEGER,order_id TEXT REFERENCES orders(order_id),line_no INTEGER,sku TEXT,product TEXT,sale_unit TEXT,quantity INTEGER,base_quantity INTEGER,unit_price INTEGER,line_discount INTEGER,line_total INTEGER,unit_cost INTEGER,PRIMARY KEY(file,row));
 CREATE TABLE exact_duplicate_lines(file TEXT,row INTEGER,retained_file TEXT,retained_row INTEGER,order_id TEXT,amount INTEGER,PRIMARY KEY(file,row));
 CREATE TABLE receipts(payment_id TEXT PRIMARY KEY,order_id TEXT REFERENCES orders(order_id),payment_date TEXT,method TEXT,amount INTEGER,source_row INTEGER);
 CREATE TABLE products(sku TEXT PRIMARY KEY,product TEXT,category TEXT,unit TEXT,source_row INTEGER);
 CREATE TABLE customers(customer_id TEXT PRIMARY KEY,name TEXT,phone TEXT,source_row INTEGER);
 CREATE TABLE unit_conversions(source_row INTEGER PRIMARY KEY,sku TEXT,unit TEXT,factor INTEGER);
 CREATE TABLE price_history(source_row INTEGER PRIMARY KEY,sku TEXT,start_date TEXT,price INTEGER);
 CREATE TABLE purchases(source_row INTEGER PRIMARY KEY,receipt_id TEXT,product TEXT,quantity INTEGER,unit TEXT,unit_cost INTEGER,total INTEGER,purchase_date TEXT,raw_json TEXT);
 CREATE TABLE expenses(source_row INTEGER PRIMARY KEY,expense_date TEXT,category TEXT,amount INTEGER,raw_json TEXT);
 CREATE TABLE shift_cash(source_row INTEGER PRIMARY KEY,shift_date TEXT,shift TEXT,staff_id TEXT,cash_received INTEGER,cash_refunded INTEGER,net_cash INTEGER,raw_json TEXT);
 CREATE TABLE stock_snapshot(source_row INTEGER PRIMARY KEY,sku TEXT,product TEXT,unit TEXT,quantity INTEGER,raw_json TEXT);
 CREATE TABLE mapping_issues(file TEXT,row INTEGER,code TEXT,detail TEXT);
 CREATE INDEX ix_order_lines_order ON order_lines(order_id);
 CREATE INDEX ix_receipts_order ON receipts(order_id);
 """)
 count=collections.Counter();errors=collections.Counter();excluded=collections.Counter();seen={};orders={};sumlines=collections.Counter();sumreceipts=collections.Counter()
 def issue(f,row,kind,detail):
  errors[kind]+=1;db.execute('INSERT INTO mapping_issues VALUES(?,?,?,?)',(f,row,kind,txt(detail)[:300]))
 def stage(f,s,n,r):
  db.execute('INSERT INTO source_rows VALUES(?,?,?,?)',(f,s,n,json.dumps(r,ensure_ascii=False,default=str)))
 for f in SALES:
  for n,r in rows(source/f):
   stage(f,'BanHang',n,r)
   oid=txt(r['Đơn số'])
   if not re.fullmatch(r'ORD\d+',oid):
    excluded['non_order_row']+=1;continue
   status=STATUSES.get(txt(r['Trạng thái giao']))
   if not status:issue(f,n,'UNKNOWN_STATUS',r['Trạng thái giao'])
   header={ 'order_date':date(r['Ngày HĐ']),'source_status':txt(r['Trạng thái giao']),'status':status,'channel':txt(r['Nguồn']),'customer_id':txt(r['Mã khách']),'customer_name':txt(r['Khách hàng (tên)']),'staff_id':txt(r['Mã NV bán']),'payment_method':txt(r['Hình thức thanh toán']),'item_total':num(r['Tiền hàng trước giảm']),'discount':num(r['Tiền giảm']),'shipping':num(r['Phí ship']),'payable':num(r['Tổng thanh toán']),'paid_snapshot':num(r['Da tra']),'debt_snapshot':num(r['Công nợ'])}
   if oid not in orders:
    orders[oid]=header
    if None in (header['order_date'],header['item_total'],header['discount'],header['shipping'],header['payable'],header['paid_snapshot'],header['debt_snapshot']):issue(f,n,'INVALID_ORDER_FIELDS',oid)
    db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(oid,*header.values(),f,n));count['orders']+=1
   else:
    h=orders[oid]
    for key in ('source_status','channel','customer_id','staff_id','payment_method','item_total','discount','shipping','payable','paid_snapshot','debt_snapshot'):
     if header[key]!=h[key]:issue(f,n,'HEADER_MISMATCH',oid+':'+key)
   signature=tuple(sorted((k,txt(v)) for k,v in r.items()))
   if signature in seen:
    pf,pr=seen[signature];excluded['exact_duplicate_line']+=1
    db.execute('INSERT INTO exact_duplicate_lines VALUES(?,?,?,?,?,?)',(f,n,pf,pr,oid,num(r['Thành tiền (đ)'])));continue
   seen[signature]=(f,n)
   quantity=qty(r['S.L']);base=num(r['SL (ĐV cơ bản)']);price=num(r['Giá 1 đv']);discount=num(r['Giảm (đ)']);amount=num(r['Thành tiền (đ)']);cost=num(r['Giá vốn lúc bán'])
   if None in (quantity,base,price,discount,amount,cost) or quantity*price-discount!=amount:issue(f,n,'LINE_EQUATION',oid)
   else:sumlines[oid]+=amount
   db.execute('INSERT INTO order_lines VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(f,n,oid,num(r['Dòng']),txt(r['Barcode']),txt(r['Hàng hóa']),txt(r['ĐV']),quantity,base,price,discount,amount,cost));count['order_lines']+=1
 for oid,h in orders.items():
  if sumlines[oid]!=h['item_total']:issue('orders',0,'ORDER_ITEMS_SUM',oid)
  if h['item_total']-h['discount']+h['shipping']!=h['payable']:issue('orders',0,'ORDER_PAYABLE',oid)
  if h['status']=='cancelled':
   if h['paid_snapshot']!=0 or h['debt_snapshot']!=0:issue('orders',0,'CANCELLED_CASH',oid)
  elif h['paid_snapshot']+h['debt_snapshot']!=h['payable']:issue('orders',0,'PAID_DEBT_EQUATION',oid)
 f='BanHang_PhieuThu.xlsx'
 for n,r in rows(source/f):
  stage(f,'Sheet1',n,r)
  oid=txt(r['Ma don']);amount=num(r['Tiền thu']);payment_id=txt(r['Mã thanh toán'])
  if oid not in orders:issue(f,n,'ORPHAN_PAYMENT',oid)
  if amount is None:issue(f,n,'UNPARSEABLE_PAYMENT',payment_id)
  try:db.execute('INSERT INTO receipts VALUES(?,?,?,?,?,?)',(payment_id,oid,date(r['Ngày TT']),txt(r['PTTT']),amount,n));count['receipts']+=1
  except sqlite3.IntegrityError:issue(f,n,'DUPLICATE_PAYMENT',payment_id)
  sumreceipts[oid]+=amount or 0
 for oid,h in orders.items():
  if sumreceipts[oid]!=h['paid_snapshot']:issue(f,0,'PAYMENT_PARITY',oid)
 f=SALES[0]
 for sheet,table,cols in [
  (2,'products',('Mã H.hóa','Tên hàng hóa','Nhóm hàng','DVT')),
  (3,'customers',('Mã KH mua','Khách hàng mua','SĐT')),
  (4,'unit_conversions',('Mã vạch','Quy cách','Bằng')),
  (5,'price_history',('Mã H.hóa','Ngày áp dụng','Giá mới'))]:
  for n,r in rows(source/f,sheet):
   stage(f,table,n,r)
   if table=='products':db.execute('INSERT INTO products VALUES(?,?,?,?,?)',(*(txt(r[c]) for c in cols),n))
   if table=='customers':db.execute('INSERT INTO customers VALUES(?,?,?,?)',(*(txt(r[c]) for c in cols),n))
   if table=='unit_conversions':db.execute('INSERT INTO unit_conversions VALUES(?,?,?,?)',(n,txt(r[cols[0]]),txt(r[cols[1]]),num(r[cols[2]])))
   if table=='price_history':db.execute('INSERT INTO price_history VALUES(?,?,?,?)',(n,txt(r[cols[0]]),date(r[cols[1]]),num(r[cols[2]])))
   count[table]+=1
 for f,table,hdr in [('SoTay_NhapHang.xlsx','purchases',3),('SoTay_ChiPhi.xlsx','expenses',3),('BaoCaoCa.xlsx','shift_cash',1)]:
  for n,r in rows(source/f,header=hdr):
   stage(f,'Sheet1',n,r)
   if table=='purchases':
    q=qty(r['SL nhập']);price=num(r['Giá nhập']);amount=num(r['Thành tiền'])
    if None in (q,price,amount) or q*price!=amount:issue(f,n,'PURCHASE_EQUATION',r['Số phiếu'])
    db.execute('INSERT INTO purchases VALUES(?,?,?,?,?,?,?,?,?)',(n,txt(r['Số phiếu']),txt(r['Product']),q,txt(r['ĐVT nhập']),price,amount,date(r['Ngày nhập']),json.dumps(r,ensure_ascii=False)))
   if table=='expenses':
    amt=num(r['Tiền chi'])
    if amt is None:issue(f,n,'EXPENSE_MONEY',r['Tiền chi'])
    db.execute('INSERT INTO expenses VALUES(?,?,?,?,?)',(n,date(r['Ngày mua']),txt(r['Nhóm']),amt,json.dumps(r,ensure_ascii=False)))
   if table=='shift_cash':
    received=num(r['Tiền mặt thu']);refunded=num(r['Tiền mặt hoàn khách']);net=num(r['Tiền mặt ròng của ca'])
    if None in (received,refunded,net) or received-refunded!=net:issue(f,n,'SHIFT_EQUATION',n)
    db.execute('INSERT INTO shift_cash VALUES(?,?,?,?,?,?,?,?)',(n,date(r['Ngày']),txt(r['Ca']),txt(r['Mã NV']),received,refunded,net,json.dumps(r,ensure_ascii=False)))
   count[table]+=1
 f='ton_kho.csv'
 with (source/f).open(encoding='utf-8-sig',newline='') as handle:
  for n,r in enumerate(csv.DictReader(handle),2):
   stage(f,'csv',n,r);q=num(r['Ton kho'])
   if q is None:issue(f,n,'STOCK_MONEY',r['Ton kho'])
   db.execute('INSERT INTO stock_snapshot VALUES(?,?,?,?,?,?)',(n,txt(r['ma_sp']),txt(r['ten_hang']),txt(r['ĐVT']),q,json.dumps(r,ensure_ascii=False)));count['stock_snapshot']+=1
 db.commit()
 status=dict(db.execute('SELECT status,COUNT(*) FROM orders GROUP BY status'))
 rep={'approval':'CANDIDATE_NOT_APPROVED','accepted':dict(count),'excluded':dict(excluded),'issues':dict(errors),'statuses':status,'sqlite_integrity':db.execute('PRAGMA integrity_check').fetchone()[0],'foreign_keys':len(db.execute('PRAGMA foreign_key_check').fetchall())}
 db.close()
 write(out/'candidate_report.json',rep)
 write(out/'manifest.json',{'approval':'CANDIDATE_NOT_APPROVED','version':'dev003-candidate-v1','source_sha256':{f:sha(source/f) for f in SOURCES},'sqlite_sha256':sha(out/'dev_003.sqlite')})
 print(json.dumps({'output':str(out),'candidate':rep},ensure_ascii=False,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 build(pathlib.Path(a.source),pathlib.Path(a.output))
