#!/usr/bin/env python3
"""dev_008 candidate builder. Isolated, immutable sources; no production release."""
import argparse,collections,datetime,hashlib,json,pathlib,re,sqlite3
from decimal import Decimal,InvalidOperation
from dev008_source_audit import rows as xlsx_rows

SOURCES=['ChiTietHoaDon_1.xlsx','ChiTietHoaDon_2.xlsx','DanhMucHang.xlsx','ChiTietNhapHang.xlsx']
SALES=SOURCES[:2]
STATUS={'đã xong':'completed','Thành công':'completed','đã lấy':'completed','khách hủy':'cancelled','hủy đơn':'cancelled','Hoàn trả':'returned','trả hàng':'returned','Đã hoàn hàng':'returned','Đang giao':'shipping','Đang giao dịch':'in_progress'}
BILL=re.compile(r'^ORD\d+$')
def val(x):return str(x if x is not None else '').strip()
def amount(x):
 s=val(x).lower().replace(' ','').replace('đ','').replace('₫','')
 if not s:return None
 sign=-1 if s.startswith('-') else 1
 if sign<0:s=s[1:]
 if 'tr' in s:
  m=re.fullmatch(r'(\d+(?:[,.]\d+)?)tr(\d{0,3})',s)
  if not m:return None
  try:return sign*int(Decimal(m[1].replace(',','.'))*1000000+(Decimal(m[2])*10**(6-len(m[2])) if m[2] else 0))
  except InvalidOperation:return None
 if re.fullmatch(r'\d+',s):return sign*int(s)
 if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',s):return sign*int(re.sub(r'[.,]','',s))
 return None
def table(path):
 it=xlsx_rows(path);_,head=next(it)
 columns={i:val(v) for i,v in head.items()}
 for rowno,r in it:
  if r:yield rowno,{k:r.get(i,'') for i,k in columns.items()}
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 src=pathlib.Path(a.source);out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=True)
 db=out/'dev_008.sqlite'
 if db.exists():raise SystemExit('Refusing to overwrite existing SQLite')
 hashes={name:hashlib.sha256((src/name).read_bytes()).hexdigest() for name in SOURCES}
 con=sqlite3.connect(db);con.execute('PRAGMA foreign_keys=ON')
 con.executescript("""CREATE TABLE source_rows(source_file TEXT,source_row INTEGER,record_type TEXT,raw_json TEXT,PRIMARY KEY(source_file,source_row));
 CREATE TABLE orders(order_id TEXT PRIMARY KEY,order_date TEXT,ordered_at TEXT,raw_status TEXT,normalized_status TEXT,payment_method TEXT,customer_id TEXT,channel TEXT,order_items_total INTEGER,order_discount INTEGER,shipping_fee INTEGER,order_payable INTEGER,debt_note TEXT,source_file TEXT,source_row INTEGER);
 CREATE TABLE order_lines(source_file TEXT,source_row INTEGER,order_id TEXT REFERENCES orders(order_id),line_number TEXT,product_id TEXT,product_name TEXT,unit TEXT,quantity_raw TEXT,base_quantity_raw TEXT,unit_price INTEGER,line_discount INTEGER,line_total INTEGER,PRIMARY KEY(source_file,source_row));
 CREATE TABLE product_catalog(source_file TEXT,source_row INTEGER,product_id TEXT,product_name TEXT,raw_json TEXT,PRIMARY KEY(source_file,source_row));
 CREATE TABLE inbound_lines(source_file TEXT,source_row INTEGER,receipt_id TEXT,product_id TEXT,raw_json TEXT,PRIMARY KEY(source_file,source_row));
 CREATE TABLE excluded_records(source_file TEXT,source_row INTEGER,reason TEXT,raw_json TEXT,PRIMARY KEY(source_file,source_row));
 CREATE TABLE mapping_issues(source_file TEXT,source_row INTEGER,issue TEXT,details TEXT);
 CREATE TABLE dedup_lineage(duplicate_source_file TEXT,duplicate_source_row INTEGER,retained_source_file TEXT,retained_source_row INTEGER,order_id TEXT,duplicate_line_amount INTEGER,PRIMARY KEY(duplicate_source_file,duplicate_source_row));
 CREATE INDEX order_lines_order ON order_lines(order_id);""")
 accepted=collections.Counter();excluded=collections.Counter();issues=collections.Counter()
 header_cols=('Ngày xuất','Giờ bán','TT đơn','Thanh toán bằng','Mã người mua','Kênh bán','Tổng tiền hàng','Giảm giá HĐ','Phi ship','Tong tien','Note')
 seen_orders={};seen_lines={}
 def problem(file,row,code,detail):
  issues[code]+=1;con.execute('INSERT INTO mapping_issues VALUES(?,?,?,?)',(file,row,code,str(detail)[:500]))
 def skip(file,row,reason,r):
  excluded[reason]+=1;con.execute('INSERT INTO excluded_records VALUES(?,?,?,?)',(file,row,reason,json.dumps(r,ensure_ascii=False,default=str)))
 for file in SALES:
  for row,r in table(src/file):
   raw=json.dumps(r,ensure_ascii=False,default=str);bill=val(r.get('Bill'))
   if not BILL.fullmatch(bill):
    skip(file,row,'non_transaction_or_summary',r);con.execute('INSERT INTO source_rows VALUES(?,?,?,?)',(file,row,'excluded',raw));continue
   con.execute('INSERT INTO source_rows VALUES(?,?,?,?)',(file,row,'transaction',raw))
   header=tuple(val(r.get(c)) for c in header_cols)
   if bill in seen_orders:
    if header!=seen_orders[bill][0]:problem(file,row,'INCONSISTENT_ORDER_HEADER',bill)
   else:
    seen_orders[bill]=(header,(file,row))
    st=val(r.get('TT đơn'));normalized=STATUS.get(st)
    if normalized is None:problem(file,row,'UNKNOWN_ORDER_STATUS',st)
    amounts=[amount(r.get(c)) for c in ('Tổng tiền hàng','Giảm giá HĐ','Phi ship','Tong tien')]
    for c,v in zip(('Tổng tiền hàng','Giảm giá HĐ','Phi ship','Tong tien'),amounts):
     if v is None:problem(file,row,'UNPARSEABLE_ORDER_MONEY',bill+':'+c+':'+val(r.get(c)))
    day=val(r.get('Ngày xuất'));date=None
    try:date=datetime.datetime.strptime(day,'%d/%m/%Y').date().isoformat()
    except ValueError:problem(file,row,'INVALID_ORDER_DATE',day)
    ordered_at=val(r.get('Giờ bán'))
    con.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(bill,date,ordered_at,st,normalized,val(r.get('Thanh toán bằng')),val(r.get('Mã người mua')),val(r.get('Kênh bán')),*amounts,val(r.get('Note')),file,row))
    accepted['orders']+=1
   # Verify exact entire-row equivalence; NEVER deduplicate by Bill+Số dòng alone.
   signature=tuple((field,val(value)) for field,value in sorted(r.items()))
   if signature in seen_lines:
    old_file,old_row=seen_lines[signature]
    duplicate_amount=amount(r.get('Thành tiền'))
    if duplicate_amount is None:problem(file,row,'UNPARSEABLE_DUPLICATE_MONEY',bill)
    skip(file,row,'exact_duplicate_line',r)
    con.execute('INSERT INTO dedup_lineage VALUES(?,?,?,?,?,?)',(file,row,old_file,old_row,bill,duplicate_amount))
    continue
   seen_lines[signature]=(file,row)
   amounts=[amount(r.get(c)) for c in ('Đơn giá (đ)','Giảm (đ)','Thành tiền')]
   if any(v is None for v in amounts):problem(file,row,'UNPARSEABLE_LINE_MONEY',bill)
   con.execute('INSERT INTO order_lines VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(file,row,bill,val(r.get('Số dòng')),val(r.get('Ma hang')),val(r.get('Tên hàng')),val(r.get('Đơn vị (tính)')),val(r.get('SLg')),val(r.get('SL lẻ')),*amounts))
   accepted['order_lines']+=1
 for file,table_name,key,name in [(SOURCES[2],'product_catalog','Mã sản phẩm bán','Hàng'),(SOURCES[3],'inbound_lines','Mã phiếu nhập','Mã vạch')]:
  for row,r in table(src/file):
   raw=json.dumps(r,ensure_ascii=False,default=str)
   con.execute('INSERT INTO source_rows VALUES(?,?,?,?)',(file,row,'transaction',raw))
   if table_name=='product_catalog':
    con.execute('INSERT INTO product_catalog VALUES(?,?,?,?,?)',(file,row,val(r.get(key)),val(r.get(name)),raw))
   else:
    con.execute('INSERT INTO inbound_lines VALUES(?,?,?,?,?)',(file,row,val(r.get(key)),val(r.get(name)),raw))
   accepted[table_name]+=1
 con.commit()
 independent=[]
 for file in SOURCES:independent.append((file,con.execute('SELECT COUNT(*) FROM source_rows WHERE source_file=?',(file,)).fetchone()[0]))
 by_status=dict(con.execute('SELECT normalized_status,COUNT(*) FROM orders GROUP BY normalized_status'))
 linekey_dups=con.execute("SELECT SUM(n-1) FROM (SELECT COUNT(*) n FROM order_lines GROUP BY order_id,line_number HAVING n>1)").fetchone()[0] or 0
 summaries=con.execute("""SELECT COUNT(*),SUM(CASE WHEN order_items_total=(SELECT SUM(line_total) FROM order_lines l WHERE l.order_id=o.order_id) THEN 1 ELSE 0 END),SUM(CASE WHEN order_payable=order_items_total-order_discount+shipping_fee THEN 1 ELSE 0 END) FROM orders o""").fetchone()
 report={'approval':'CANDIDATE_NOT_APPROVED','source_hashes':hashes,'accepted':dict(accepted),'excluded':dict(excluded),'issues':dict(issues),'status_orders':by_status,'source_rows_by_file':dict(independent),'repeated_order_line_keys':linekey_dups,'dedup_lineage_count':report['dedup_lineage_count'],'dedup_lineage_amount':report['dedup_lineage_amount'],'order_count':summaries[0],'orders_matching_item_sum':summaries[1],'orders_matching_payable_equation':summaries[2],'notes':['Exact duplicated source lines retained in source_rows and dedup_lineage and excluded from order_lines','Source-level inventory and purchase history retained; no inventory or margin KPI approved','Financial and source-independent QA NOT RUN']}
 report['dedup_lineage_count']=con.execute('SELECT COUNT(*) FROM dedup_lineage').fetchone()[0]
 report['dedup_lineage_amount']=con.execute('SELECT SUM(duplicate_line_amount) FROM dedup_lineage').fetchone()[0]
 (out/'candidate_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 (out/'manifest.json').write_text(json.dumps({'approval':'CANDIDATE_NOT_APPROVED','version':'dev008-candidate-v2','source_sha256':hashes,'sqlite_sha256':hashlib.sha256(db.read_bytes()).hexdigest(),'kpis_supported':[]},ensure_ascii=False,indent=2))
 con.close()
 print(json.dumps({'output':str(out),'approval':report['approval'],'accepted':dict(accepted),'excluded':dict(excluded),'issues':dict(issues),'status_orders':by_status,'repeated_order_line_keys':linekey_dups,'order_count':summaries[0],'orders_matching_item_sum':summaries[1],'orders_matching_payable_equation':summaries[2]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
