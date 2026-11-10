#!/usr/bin/env python3
"""dev002: monthly Excel retail/cafe source -> isolated SQLite candidate."""
import argparse,collections,datetime,hashlib,json,pathlib,re,sqlite3
from decimal import Decimal,InvalidOperation
from dev011_source_audit import sheet_rows
MONTHLY=tuple('BanHang_T%d_%d.xlsx'%(m,y) for y in (2025,2026) for m in range(1,13) if (y==2025 or m<=5))
FILES=(*MONTHLY,'DanhSachQuyDoi.xlsx')
STATUS={'Đã hoàn thành':'completed','Đã hủy':'cancelled','Đã hoàn hàng':'returned','Đang giao dịch':'in_progress'}
def norm(v):return str(v if v is not None else '').strip()
def money(v):
 s=norm(v).lower().replace('₫','').replace('đ','').replace(' ','')
 if not s:return None
 sign=-1 if s.startswith('-') else 1
 if sign<0:s=s[1:]
 mul=1
 if s.endswith('tr'):mul=1000000;s=s[:-2]
 elif s.endswith('k'):mul=1000;s=s[:-1]
 if re.fullmatch(r'\d{1,3}(?:[,.]\d{3})+',s):s=re.sub('[,.]','',s)
 else:s=s.replace(',','.')
 try:
  v=Decimal(s)*mul
  return sign*int(v) if v==int(v) else None
 except (InvalidOperation,ValueError):return None
def integer(v):
 m=re.fullmatch(r'(\d+)(?:\s+[a-zA-ZÀ-ỹ]+)?',norm(v))
 return int(m[1]) if m else None
def date(v):
 s=norm(v)
 if re.fullmatch(r'\d{5}(?:\.\d+)?',s):return (datetime.datetime(1899,12,30)+datetime.timedelta(days=float(s))).date().isoformat()
 try:return datetime.datetime.strptime(s,'%d/%m/%Y').date().isoformat()
 except ValueError:return None
def monthly_rows(p):
 for n,v in sheet_rows(p,1):
  if n>=5 and any(norm(x) for x in v.values()):yield n,{k:v.get(i) for i,k in enumerate(('order_id','date','status','customer','name','quantity','price','total','unit'))}
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,data):p.write_text(json.dumps(data,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def build(source,out):
 if out.exists():raise RuntimeError('Refuse overwrite: '+str(out))
 for f in FILES:
  if not (source/f).is_file():raise RuntimeError('Missing '+f)
 out.mkdir(parents=True)
 db=sqlite3.connect(out/'dev_002.sqlite');db.execute('PRAGMA foreign_keys=ON')
 db.executescript("""
 CREATE TABLE source_rows(file TEXT,row INTEGER,raw_json TEXT,PRIMARY KEY(file,row));
 CREATE TABLE unit_conversions(source_row INTEGER PRIMARY KEY,product_name TEXT,large_unit TEXT,factor INTEGER,base_unit TEXT);
 CREATE TABLE orders(order_id TEXT PRIMARY KEY,order_date TEXT,source_status TEXT,status TEXT,customer_first TEXT,item_total INTEGER DEFAULT 0,line_count INTEGER DEFAULT 0);
 CREATE TABLE order_lines(file TEXT,row INTEGER,order_id TEXT REFERENCES orders(order_id),full_product TEXT,base_product TEXT,unit TEXT,quantity INTEGER,base_quantity INTEGER,unit_price INTEGER,base_amount INTEGER,topping_amount INTEGER,line_discount INTEGER,line_total INTEGER,has_embedded_topping INTEGER,PRIMARY KEY(file,row));
 CREATE TABLE topping_components(file TEXT,row INTEGER,position INTEGER,part_name TEXT,part_quantity INTEGER,part_total INTEGER,PRIMARY KEY(file,row,position),FOREIGN KEY(file,row) REFERENCES order_lines(file,row));
 CREATE TABLE excluded_rows(file TEXT,row INTEGER,reason TEXT,raw_json TEXT,PRIMARY KEY(file,row));
 CREATE TABLE mapping_issues(file TEXT,row INTEGER,code TEXT,detail TEXT);
 CREATE INDEX ix_lines_order ON order_lines(order_id);
 """)
 issues=collections.Counter();counts=collections.Counter();excluded=collections.Counter();seen_orders={}
 def problem(f,n,code,detail):
  issues[code]+=1;db.execute('INSERT INTO mapping_issues VALUES(?,?,?,?)',(f,n,code,str(detail)[:300]))
 conv={}
 for n,v in sheet_rows(source/'DanhSachQuyDoi.xlsx',1):
  if n==1:continue
  if not any(norm(x) for x in v.values()):continue
  prod,large,factor,base=(norm(v.get(i)) for i in range(4))
  if not re.fullmatch(r'\d+',factor) or int(factor)<=0:problem('DanhSachQuyDoi.xlsx',n,'INVALID_FACTOR',factor);continue
  if (prod,large) in conv:problem('DanhSachQuyDoi.xlsx',n,'DUPLICATE_CONVERSION',prod)
  conv[(prod,large)]=int(factor)
  db.execute('INSERT INTO unit_conversions VALUES(?,?,?,?,?)',(n,prod,large,int(factor),base));counts['unit_conversions']+=1
 for f in MONTHLY:
  match=re.fullmatch(r'BanHang_T(\d+)_(\d+)\.xlsx',f);month,year=int(match[1]),int(match[2])
  for rn,r in monthly_rows(source/f):
   raw=json.dumps(r,ensure_ascii=False,default=str)
   db.execute('INSERT INTO source_rows VALUES(?,?,?)',(f,rn,raw))
   oid=norm(r['order_id'])
   if not re.fullmatch(r'ORD\d+',oid):
    reason='repeated_header' if oid=='Mã đơn hàng' else 'daily_summary' if 'TỔNG NGÀY' in norm(r['name']) else 'non_transaction'
    excluded[reason]+=1
    db.execute('INSERT INTO excluded_rows VALUES(?,?,?,?)',(f,rn,reason,raw))
    continue
   dt=date(r['date']);status=STATUS.get(norm(r['status']))
   if dt is None:problem(f,rn,'BAD_DATE',r['date'])
   elif dt[:7]!=f'{year}-{month:02d}':problem(f,rn,'WRONG_MONTH',oid)
   if status is None:problem(f,rn,'UNKNOWN_STATUS',r['status'])
   if oid not in seen_orders:
    seen_orders[oid]=(dt,status)
    db.execute('INSERT INTO orders(order_id,order_date,source_status,status,customer_first) VALUES(?,?,?,?,?)',(oid,dt,norm(r['status']),status,norm(r['customer'])))
    counts['orders']+=1
   elif seen_orders[oid]!=(dt,status):problem(f,rn,'CONFLICTING_ORDER_DATE_STATUS',oid)
   quantity=integer(r['quantity']);price=money(r['price']);total=money(r['total']);name=norm(r['name']);unit=norm(r['unit'])
   components=[]
   if ' + ' in name:
    parts=name.split(' + ');base_name=parts[0].strip()
    for pos,part in enumerate(parts[1:],1):
     m=re.fullmatch(r'(?:(\d+)\s+)?(.+?)\s*\(([\d.,]+)\s*đ\)',part.strip())
     if not m:problem(f,rn,'TOPPING_PARSE',part);continue
     topping_q=int(m[1] or 1);topping_amt=money(m[3])
     if topping_amt is None or topping_q<=0:problem(f,rn,'TOPPING_VALUE',part)
     components.append((pos,m[2].strip(),topping_q,topping_amt))
   else:base_name=name
   top_amount=sum(c[3] for c in components if c[3] is not None)
   base_amount=quantity*price if quantity is not None and price is not None else None
   discount=base_amount+top_amount-total if base_amount is not None and total is not None else None
   if None in (quantity,price,total,discount) or quantity<=0:problem(f,rn,'INVALID_LINE_MONEY',oid)
   elif discount<0:problem(f,rn,'UNSUPPORTED_UPCHARGE',oid)
   if not name or not unit:problem(f,rn,'MISSING_PRODUCT_OR_UNIT',oid)
   factor=conv.get((base_name,unit),1)
   baseqty=quantity*factor if quantity is not None else None
   db.execute('INSERT INTO order_lines VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(f,rn,oid,name,base_name,unit,quantity,baseqty,price,base_amount,top_amount,discount,total,int(bool(components))))
   for pos,part_name,part_q,part_amt in components:db.execute('INSERT INTO topping_components VALUES(?,?,?,?,?,?)',(f,rn,pos,part_name,part_q,part_amt))
   counts['order_lines']+=1;counts['topping_components']+=len(components)
 db.executescript("""
 UPDATE orders SET item_total=COALESCE((SELECT SUM(line_total) FROM order_lines WHERE order_id=orders.order_id),0),
 line_count=COALESCE((SELECT COUNT(*) FROM order_lines WHERE order_id=orders.order_id),0);
 """)
 db.commit()
 report={'approval':'CANDIDATE_NOT_APPROVED','accepted':dict(counts),'excluded':dict(excluded),'issues':dict(issues),'status_counts':dict(db.execute('SELECT status,COUNT(*) FROM orders GROUP BY status')),'sqlite_integrity':db.execute('PRAGMA integrity_check').fetchone()[0],'foreign_key_violations':len(db.execute('PRAGMA foreign_key_check').fetchall()),'source_rows':db.execute('SELECT COUNT(*) FROM source_rows').fetchone()[0],'line_discount_count':db.execute('SELECT COUNT(*) FROM order_lines WHERE line_discount>0').fetchone()[0]}
 db.close()
 write(out/'candidate_report.json',report)
 write(out/'manifest.json',{'approval':'CANDIDATE_NOT_APPROVED','version':'dev002-candidate-v1','source_sha256':{f:digest(source/f) for f in FILES},'sqlite_sha256':digest(out/'dev_002.sqlite')})
 print(json.dumps({'output':str(out),'candidate':report},ensure_ascii=False,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);args=p.parse_args()
 build(pathlib.Path(args.source),pathlib.Path(args.output))
