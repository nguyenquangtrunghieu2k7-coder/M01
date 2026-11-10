#!/usr/bin/env python3
"""dev013 source-bound candidate builder. Immutable Excel inputs; no other shops changed."""
import argparse,collections,datetime,hashlib,json,pathlib,re,sqlite3
from decimal import Decimal
from dev011_source_audit import sheet_rows
SALES=('BanHang_2025.xlsx','BanHang_2026.xlsx')
HEADERS=['ĐG','TT','SL','ĐVT','Tên hàng','HĐ','Ngày','Khách','Kênh','Ghi chú']
def norm(v):return str(v if v is not None else '').strip()
def money(v):
 s=norm(v).lower().replace(' ','').replace('₫','').replace('đ','')
 if not s:return None
 sign=-1 if s.startswith('-') else 1
 if sign<0:s=s[1:]
 m=re.fullmatch(r'(\d+(?:[,.]\d+)?)tr(\d{0,3})',s)
 if m:return sign*int(Decimal(m[1].replace(',','.'))*1000000+(int(m[2])*10**(6-len(m[2])) if m[2] else 0))
 m=re.fullmatch(r'(\d+(?:[,.]\d+)?)k',s)
 if m:return sign*int(Decimal(m[1].replace(',','.'))*1000)
 if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',s):return sign*int(re.sub('[.,]','',s))
 if s.isdigit():return sign*int(s)
 return None
def date(v,month=None,year=None):
 if v is None or norm(v)=='':return None
 if isinstance(v,(int,float)) or (isinstance(v,str) and re.fullmatch(r'\d{5}',v.strip())):
  return (datetime.date(1899,12,30)+datetime.timedelta(days=int(float(v)))).isoformat()
 s=norm(v).lower().replace('tháng','thg')
 m=re.fullmatch(r'(\d{1,2})\s*thg\s*(\d{1,2})\s*(\d{4})',s)
 if m:return datetime.date(int(m[3]),int(m[2]),int(m[1])).isoformat()
 m=re.fullmatch(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?',s)
 if m:return datetime.date(int(m[3]) if m[3] else year,int(m[2]),int(m[1])).isoformat()
 try:return datetime.date.fromisoformat(s[:10]).isoformat()
 except ValueError:return None
def all_rows(path,idx,header_rows=1):
 it=sheet_rows(path,idx)
 for _ in range(header_rows):next(it)
 for n,cells in it:
  if any(norm(v) for v in cells.values()):yield n,cells
def manager(path,sheet_idx):
 it=sheet_rows(path,sheet_idx);_,header=next(it)
 columns={k:norm(v) for k,v in header.items()}
 for rownum,cells in it:
  if any(norm(v) for v in cells.values()):yield rownum,{label:cells.get(k) for k,label in columns.items()}
def classify(name,quantity):
 if name=='Voucher':return 'voucher'
 if name=='Phí ship':return 'shipping_fee'
 if re.fullmatch(r'Dùng \d+ điểm',name):return 'points_redemption'
 if quantity is not None:return 'item'
 return 'unknown'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def process(source,out):
 if out.exists():raise RuntimeError('Output exists: '+str(out))
 out.mkdir(parents=True);dbpath=out/'dev_013.sqlite'
 con=sqlite3.connect(dbpath);con.execute('PRAGMA foreign_keys=ON')
 con.executescript("""
 CREATE TABLE source_rows(source_file TEXT,sheet TEXT,source_row INTEGER,raw_json TEXT,PRIMARY KEY(source_file,sheet,source_row));
 CREATE TABLE orders(order_id TEXT PRIMARY KEY,order_date TEXT,customer_name TEXT,channel TEXT,note TEXT,status TEXT,item_amount INTEGER DEFAULT 0,voucher_amount INTEGER DEFAULT 0,points_amount INTEGER DEFAULT 0,shipping_amount INTEGER DEFAULT 0,order_payable INTEGER DEFAULT 0);
 CREATE TABLE order_lines(source_file TEXT,sheet TEXT,source_row INTEGER,order_id TEXT REFERENCES orders(order_id),line_type TEXT,product_name TEXT,quantity INTEGER,unit TEXT,unit_price INTEGER,line_discount INTEGER,line_amount INTEGER,redeemed_points INTEGER,PRIMARY KEY(source_file,sheet,source_row));
 CREATE TABLE catalog(source_row INTEGER PRIMARY KEY,product_name TEXT UNIQUE,category TEXT,brand TEXT,unit TEXT,conversion_raw TEXT,raw_json TEXT);
 CREATE TABLE customers(source_row INTEGER PRIMARY KEY,customer_name TEXT,registration_date TEXT,points_snapshot INTEGER,raw_json TEXT);
 CREATE TABLE purchases(source_row INTEGER PRIMARY KEY,receipt_id TEXT,product_name TEXT,quantity INTEGER,unit TEXT,unit_cost INTEGER,total_cost INTEGER,purchase_date TEXT,raw_json TEXT);
 CREATE TABLE promotions(source_row INTEGER PRIMARY KEY,promotion_name TEXT,applicable_product TEXT,start_date TEXT,end_date TEXT,raw_json TEXT);
 CREATE TABLE excluded_records(source_file TEXT,sheet TEXT,source_row INTEGER,reason TEXT,raw_json TEXT,PRIMARY KEY(source_file,sheet,source_row));
 CREATE TABLE mapping_issues(source_file TEXT,sheet TEXT,source_row INTEGER,issue TEXT,details TEXT);
 CREATE INDEX lines_order_idx ON order_lines(order_id);
 """)
 issues=collections.Counter();excluded=collections.Counter();counts=collections.Counter();known=set();customers=set();orders={}
 def issue(f,s,r,kind,details=''):
  issues[kind]+=1;con.execute('INSERT INTO mapping_issues VALUES(?,?,?,?,?)',(f,s,r,kind,str(details)[:300]))
 for si,title in enumerate(('DanhMuc','KhachHang','NhapHang','KhuyenMai'),1):
  for ri,r in manager(source/'QuanLy.xlsx',si):
   raw=json.dumps(r,ensure_ascii=False,default=str)
   con.execute('INSERT INTO source_rows VALUES(?,?,?,?)',('QuanLy.xlsx',title,ri,raw))
   if title=='DanhMuc':
    name=norm(r['Tên hàng']);known.add(name)
    con.execute('INSERT INTO catalog VALUES(?,?,?,?,?,?,?)',(ri,name,norm(r['Nhóm']),norm(r['Hãng']),norm(r['ĐVT']),norm(r['Quy đổi']),raw));counts['catalog']+=1
   elif title=='KhachHang':
    name=norm(r['Tên KH']);customers.add(name)
    con.execute('INSERT INTO customers VALUES(?,?,?,?,?)',(ri,name,date(r['Ngày đăng ký']),int(r['Điểm hiện có']),raw));counts['customers']+=1
   elif title=='NhapHang':
    product=norm(r['Hàng']);qty=int(r['SL']);cost=money(r['Đơn giá']);total=money(r['Thành tiền'])
    if cost is None or total is None or cost*qty!=total:issue('QuanLy.xlsx',title,ri,'BAD_PURCHASE_EQUATION',product)
    if product not in known:issue('QuanLy.xlsx',title,ri,'UNKNOWN_PURCHASE_PRODUCT',product)
    con.execute('INSERT INTO purchases VALUES(?,?,?,?,?,?,?,?,?)',(ri,norm(r['Số phiếu']),product,qty,norm(r['ĐVT']),cost,total,date(r['Ngày']),raw));counts['purchases']+=1
   else:
    con.execute('INSERT INTO promotions VALUES(?,?,?,?,?,?)',(ri,norm(r['Chương trình']),norm(r['Hàng áp dụng']),date(r['Từ ngày']),date(r['Đến ngày']),raw));counts['promotions']+=1
 for f in SALES:
  for sn in (range(1,9) if f.endswith('2025.xlsx') else range(1,7)):
   year=2025 if f.endswith('2025.xlsx') else 2026;month=sn+4 if year==2025 else sn
   sheet=f'T{month:02d}-{year}'
   for ri,values in all_rows(source/f,sn,header_rows=2):
    row={k:values.get(i) for i,k in enumerate(HEADERS)}
    raw=json.dumps(row,ensure_ascii=False,default=str)
    con.execute('INSERT INTO source_rows VALUES(?,?,?,?)',(f,sheet,ri,raw))
    oid=norm(row['HĐ'])
    if not re.fullmatch(r'ORD\d+',oid):
     excluded['non_invoice_or_subtotal']+=1
     con.execute('INSERT INTO excluded_records VALUES(?,?,?,?,?)',(f,sheet,ri,'non_invoice_or_subtotal',raw));continue
    name=norm(row['Tên hàng']);kind=classify(name,row['SL']);v=money(row['TT'])
    if v is None:issue(f,sheet,ri,'INVALID_MONEY',row['TT']);v=0
    if kind=='unknown':issue(f,sheet,ri,'UNKNOWN_LINE_TYPE',name)
    if kind=='item':
     if name not in known:issue(f,sheet,ri,'UNKNOWN_PRODUCT',name)
     q=int(row['SL']);unit=norm(row['ĐVT']);price=money(row['ĐG'])
     if price is None or price*q<v:issue(f,sheet,ri,'INVALID_ITEM_PRICE',oid)
     discount=(price*q-v) if price is not None else None;points=None
    else:
     q=None;unit=None;price=None;discount=None
     points=int(re.search(r'\d+',name).group()) if kind=='points_redemption' else None
     if kind in ('voucher','points_redemption') and v>=0:issue(f,sheet,ri,'NONNEGATIVE_DISCOUNT',name)
     if kind=='shipping_fee' and v<0:issue(f,sheet,ri,'NEGATIVE_SHIPPING',oid)
     if points is not None and v!=-100*points:issue(f,sheet,ri,'POINTS_CONVERSION_MISMATCH',name)
    if oid not in orders:
     orders[oid]={'date':None,'customer':None,'channel':None,'note':None}
     con.execute('INSERT INTO orders(order_id) VALUES(?)',(oid,));counts['orders']+=1
    meta=orders[oid]
    for fld,target in (('Ngày','date'),('Khách','customer'),('Kênh','channel'),('Ghi chú','note')):
     value=date(row[fld],month,year) if target=='date' else norm(row[fld])
     if value:
      if target=='date' and value[:7]!=f'{year}-{month:02d}':issue(f,sheet,ri,'DATE_OUTSIDE_SHEET',value)
      if meta[target] is not None and meta[target]!=value:issue(f,sheet,ri,'CONFLICTING_ORDER_FIELD',oid+':'+target)
      else:meta[target]=value
    con.execute('INSERT INTO order_lines VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(f,sheet,ri,oid,kind,name,q,unit,price,discount,v,points))
    counts['order_lines']+=1
 for oid,meta in orders.items():
  note=(meta['note'] or '').lower()
  status='cancelled' if any(s in note for s in ('huỷ','hủy','cancel')) else 'shipping' if any(s in note for s in ('đang giao','chưa giao')) else 'completed' if not note else None
  if not status:issue('orders','orders',0,'UNKNOWN_STATUS',oid+':'+note)
  if not meta['date']:issue('orders','orders',0,'MISSING_ORDER_DATE',oid)
  if not meta['customer']:issue('orders','orders',0,'MISSING_CUSTOMER',oid)
  elif meta['customer']!='Khách lẻ' and meta['customer'] not in customers:issue('orders','orders',0,'CUSTOMER_NOT_IN_CATALOG',meta['customer'])
  con.execute('UPDATE orders SET order_date=?,customer_name=?,channel=?,note=?,status=? WHERE order_id=?',(meta['date'],meta['customer'],meta['channel'],meta['note'],status,oid))
 con.executescript("""
 UPDATE orders SET
 item_amount=COALESCE((SELECT SUM(line_amount) FROM order_lines WHERE order_id=orders.order_id AND line_type='item'),0),
 voucher_amount=COALESCE((SELECT SUM(line_amount) FROM order_lines WHERE order_id=orders.order_id AND line_type='voucher'),0),
 points_amount=COALESCE((SELECT SUM(line_amount) FROM order_lines WHERE order_id=orders.order_id AND line_type='points_redemption'),0),
 shipping_amount=COALESCE((SELECT SUM(line_amount) FROM order_lines WHERE order_id=orders.order_id AND line_type='shipping_fee'),0);
 UPDATE orders SET order_payable=item_amount+voucher_amount+points_amount+shipping_amount;
 """)
 con.commit()
 status_counts=dict(con.execute('SELECT status,COUNT(*) FROM orders GROUP BY status'))
 line_types=dict(con.execute('SELECT line_type,COUNT(*) FROM order_lines GROUP BY line_type'))
 report={'source_counts':dict(counts),'excluded':dict(excluded),'issues':dict(issues),'status_counts':status_counts,'line_types':line_types,
 'foreign_key_errors':len(con.execute('PRAGMA foreign_key_check').fetchall()),'integrity':con.execute('PRAGMA integrity_check').fetchone()[0]}
 con.close()
 dump(out/'candidate_report.json',report)
 dump(out/'manifest.json',{'approval':'CANDIDATE_NOT_APPROVED','version':'dev013-candidate-v1','source_sha256':{f:sha(source/f) for f in (*SALES,'QuanLy.xlsx')},'sqlite_sha256':sha(dbpath),'kpis_supported':[]})
 print(json.dumps({'phase':'candidate','output':str(out),'report':report},ensure_ascii=False,indent=2))
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
 process(pathlib.Path(a.source),pathlib.Path(a.output))
