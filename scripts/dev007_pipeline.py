#!/usr/bin/env python3
"""dev_007 isolated restaurant CSV -> SQLite candidate. Does not touch approved shops."""
import argparse,csv,collections,datetime,hashlib,json,pathlib,re,sqlite3
from decimal import Decimal
FILES={'sales':'chi_tiet_hoa_don.csv','products':'danh_muc_hang.csv','purchases':'chi_tiet_nhap_hang.csv'}
STATUS={'Xong':'completed','Đã hủy đơn':'cancelled','Đã trả hàng':'returned','Đang xử lý':'in_progress'}
def clean(x):return str(x or '').strip()
def val(x):
 s=clean(x).lower().replace(' ','').replace('₫','').replace('đ','')
 if not s:return None
 sign=-1 if s.startswith('-') else 1
 if sign<0:s=s[1:]
 m=re.fullmatch(r'(\d+(?:[,.]\d+)?)k',s)
 if m:return sign*int(Decimal(m[1].replace(',','.'))*1000)
 m=re.fullmatch(r'(\d+(?:[,.]\d+)?)tr(\d{0,3})',s)
 if m:return sign*int(Decimal(m[1].replace(',','.'))*1000000+(int(m[2])*10**(6-len(m[2])) if m[2] else 0))
 if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',s):return sign*int(re.sub(r'[.,]','',s))
 if s.isdigit():return sign*int(s)
 return None
def day(x):
 s=clean(x)
 if re.fullmatch(r'\d{5}',s):return (datetime.date(1899,12,30)+datetime.timedelta(days=int(s))).isoformat()
 try:return datetime.datetime.strptime(s,'%d/%m/%Y').date().isoformat()
 except ValueError:return None
def reader(p):
 with p.open(encoding='utf-8-sig',newline='') as f:
  yield from enumerate(csv.DictReader(f),2)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 src=pathlib.Path(a.source);out=pathlib.Path(a.output)
 if out.exists():raise SystemExit('Refusing to overwrite candidate: '+str(out))
 for name in FILES.values():
  if not (src/name).is_file():raise SystemExit('Missing '+str(src/name))
 out.mkdir(parents=True)
 db=sqlite3.connect(out/'dev_007.sqlite');db.execute('PRAGMA foreign_keys=ON')
 db.executescript("""
 CREATE TABLE source_rows(source_file TEXT,source_row INTEGER,raw_json TEXT,PRIMARY KEY(source_file,source_row));
 CREATE TABLE orders(order_id TEXT PRIMARY KEY,order_date TEXT,ordered_at TEXT,raw_status TEXT,status TEXT,channel TEXT,table_name TEXT,area TEXT,customer_count INTEGER,customer_name TEXT,items_total INTEGER,invoice_discount INTEGER,customer_paid INTEGER,outstanding_snapshot INTEGER,delivery_fee_inferred INTEGER,source_row INTEGER);
 CREATE TABLE order_lines(source_row INTEGER PRIMARY KEY,order_id TEXT REFERENCES orders(order_id),line_no INTEGER,sku TEXT,product_name TEXT,quantity INTEGER,base_quantity INTEGER,unit_price INTEGER,line_discount INTEGER,line_total INTEGER,is_service_fee INTEGER);
 CREATE TABLE catalog(sku TEXT PRIMARY KEY,product_name TEXT,group_name TEXT,base_unit TEXT,unit_cost_snapshot INTEGER,inventory_snapshot INTEGER,raw_json TEXT,source_row INTEGER);
 CREATE TABLE purchase_lines(source_row INTEGER PRIMARY KEY,receipt_id TEXT,sku TEXT,quantity INTEGER,unit TEXT,unit_cost INTEGER,line_total INTEGER,receipt_total INTEGER,purchase_date TEXT,raw_json TEXT);
 CREATE TABLE excluded_records(source_file TEXT,source_row INTEGER,reason TEXT,raw_json TEXT,PRIMARY KEY(source_file,source_row));
 CREATE TABLE dedup_lineage(duplicate_source_row INTEGER PRIMARY KEY,retained_source_row INTEGER,order_id TEXT,duplicate_amount INTEGER);
 CREATE TABLE mapping_issues(source_file TEXT,source_row INTEGER,issue TEXT,detail TEXT);
 CREATE INDEX idx_line_order ON order_lines(order_id);
 """)
 counts=collections.Counter();excluded=collections.Counter();issues=collections.Counter()
 def issue(f,r,k,d):
  issues[k]+=1;db.execute('INSERT INTO mapping_issues VALUES(?,?,?,?)',(f,r,k,str(d)[:300]))
 def raw(f,i,r):
  s=json.dumps(r,ensure_ascii=False)
  db.execute('INSERT INTO source_rows VALUES(?,?,?)',(f,i,s));return s
 for i,r in reader(src/FILES['products']):
  s=raw(FILES['products'],i,r);sku=clean(r['Mã SKU'])
  try:
   db.execute('INSERT INTO catalog VALUES(?,?,?,?,?,?,?,?)',(sku,clean(r['Hàng bán']),clean(r['Nhóm']),clean(r['ĐVT']),val(r['Giá vốn']),val(r['Tồn cuối']),s,i));counts['catalog']+=1
  except sqlite3.IntegrityError:issue(FILES['products'],i,'DUPLICATE_PRODUCT',sku)
 skus={x[0] for x in db.execute('SELECT sku FROM catalog')}
 for i,r in reader(src/FILES['purchases']):
  s=raw(FILES['purchases'],i,r);sku=clean(r['Mã hàng bán'])
  quantity=val(r['SL nhập']);cost=val(r['Giá nhập']);total=val(r['Thành tiền']);receipt=val(r['Tổng tiền phiếu'])
  if sku not in skus:issue(FILES['purchases'],i,'UNKNOWN_PURCHASE_SKU',sku)
  if None in (quantity,cost,total,receipt) or quantity*cost!=total:issue(FILES['purchases'],i,'PURCHASE_LINE_MONEY',sku)
  db.execute('INSERT INTO purchase_lines VALUES(?,?,?,?,?,?,?,?,?,?)',(i,clean(r['Mã phiếu nhập']),sku,quantity,clean(r['ĐVT nhập']),cost,total,receipt,day(r['Ngày nhập']),s));counts['purchases']+=1
 seen={};order_headers={};sale_rows=0
 header_keys=('Giờ bán','Tiến độ','Nguồn','Bàn','Khu vực','Số khách','Họ tên khách','Tổng tiền hàng','Giảm giá HĐ','Khách trả','Còn nợ')
 for i,r in reader(src/FILES['sales']):
  s=raw(FILES['sales'],i,r);sale_rows+=1;oid=clean(r['Mã bill'])
  if not re.fullmatch(r'ORD\d+',oid):
   excluded['daily_subtotal']+=1
   db.execute('INSERT INTO excluded_records VALUES(?,?,?,?)',(FILES['sales'],i,'daily_subtotal',s))
   continue
  header=tuple(clean(r[k]) for k in header_keys)
  if oid in order_headers:
   if header!=order_headers[oid]:issue(FILES['sales'],i,'CONFLICTING_ORDER_HEADER',oid)
  else:
   order_headers[oid]=header
   st=clean(r['Tiến độ']);mapped=STATUS.get(st)
   if mapped is None:issue(FILES['sales'],i,'UNKNOWN_STATUS',st)
   dt=day(r['Ngày giao dịch'])
   try:timestamp=datetime.datetime.fromisoformat(clean(r['Giờ bán']))
   except ValueError:timestamp=None
   if dt is None or timestamp is None or (timestamp and timestamp.date().isoformat()!=dt):issue(FILES['sales'],i,'INVALID_ORDER_DATE',oid)
   money=[val(r[k]) for k in ('Tổng tiền hàng','Giảm giá HĐ','Khách trả','Còn nợ')]
   if any(x is None for x in money):issue(FILES['sales'],i,'INVALID_HEADER_MONEY',oid)
   fee=(money[2]+money[3]-(money[0]-money[1])) if all(x is not None for x in money) else None
   # Cancellation preserves pre-cancel amount, but charges neither paid nor debt.
   if mapped=='cancelled':
    if money[2]!=0 or money[3]!=0:issue(FILES['sales'],i,'CANCELLED_WITH_PAYMENT',oid)
    fee=0
   elif mapped=='returned':
    # Returned invoices retain their original paid/debt values as historical
    # ledger fields; exclude their entire invoices from booked revenue.
    # Do NOT zero the source cash fields or double-count refunds.
    if money[2]+money[3]!=money[0]-money[1]:
     issue(FILES['sales'],i,'RETURNED_LEDGER_EQUATION',oid)
    fee=0
   else:
    expected=15000 if clean(r['Nguồn']) in ('phone','zalo_oa') else 0
    if fee!=expected:issue(FILES['sales'],i,'UNEXPECTED_DELIVERY_FEE',oid+':'+str(fee))
   db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(oid,dt,clean(r['Giờ bán']),st,mapped,clean(r['Nguồn']),clean(r['Bàn']),clean(r['Khu vực']),val(r['Số khách']),clean(r['Họ tên khách']),*money,fee,i))
   counts['orders']+=1
  signature=tuple((k,clean(v)) for k,v in sorted(r.items()))
  if signature in seen:
   old=seen[signature];excluded['exact_duplicate_line']+=1
   db.execute('INSERT INTO excluded_records VALUES(?,?,?,?)',(FILES['sales'],i,'exact_duplicate_line',s))
   db.execute('INSERT INTO dedup_lineage VALUES(?,?,?,?)',(i,old,oid,val(r['Thành tiền'])))
   continue
  seen[signature]=i
  sku=clean(r['Mã vạch']);q=val(r['Sluong']);bq=val(r['Số lượng lẻ']);price=val(r['Đơn giá (đ)']);disc=val(r['Tiền giảm']);total=val(r['Thành tiền'])
  if sku not in skus:issue(FILES['sales'],i,'UNKNOWN_PRODUCT',sku)
  if None in (q,bq,price,disc,total) or q*price-disc!=total:issue(FILES['sales'],i,'LINE_EQUATION',oid)
  service=int(clean(r['Mặt hàng'])=='Phí phục vụ')
  if service and sku!='SP0061':issue(FILES['sales'],i,'SERVICE_SKU_MISMATCH',sku)
  db.execute('INSERT INTO order_lines VALUES(?,?,?,?,?,?,?,?,?,?,?)',(i,oid,val(r['No.']),sku,clean(r['Mặt hàng']),q,bq,price,disc,total,service))
  counts['order_lines']+=1
 db.commit()
 totals={oid:(amt,disc) for oid,amt,disc in db.execute('SELECT order_id,items_total,invoice_discount FROM orders')}
 for oid,amount,discount in db.execute('SELECT order_id,COALESCE(SUM(line_total),0),COALESCE(SUM(line_discount),0) FROM order_lines GROUP BY order_id'):
  if totals[oid][0]!=amount:issue(FILES['sales'],0,'ITEM_TOTAL_MISMATCH',oid+':'+str((amount,totals[oid][0])))
 purch_mismatch=db.execute('SELECT COUNT(*) FROM (SELECT receipt_id,MIN(receipt_total) a,MAX(receipt_total) b,SUM(line_total) c FROM purchase_lines GROUP BY receipt_id HAVING a!=b OR a!=c)').fetchone()[0]
 if purch_mismatch:issue(FILES['purchases'],0,'RECEIPT_TOTAL_MISMATCH',purch_mismatch)
 db.commit()
 status=dict(db.execute('SELECT status,COUNT(*) FROM orders GROUP BY status'))
 report={'approval':'CANDIDATE_NOT_APPROVED','source_rows':{name:db.execute('SELECT COUNT(*) FROM source_rows WHERE source_file=?',(name,)).fetchone()[0] for name in FILES.values()},'accepted':dict(counts),'excluded':dict(excluded),'status_counts':status,'issues':dict(issues),'purchase_receipt_mismatches':purch_mismatch,'foreign_key_violations':len(db.execute('PRAGMA foreign_key_check').fetchall()),'sqlite_integrity':db.execute('PRAGMA integrity_check').fetchone()[0],'kpis_supported':[]}
 db.close()
 dump(out/'candidate_report.json',report)
 dump(out/'manifest.json',{'version':'dev007-candidate-v1','approval':'CANDIDATE_NOT_APPROVED','source_sha256':{name:sha(src/name) for name in FILES.values()},'sqlite_sha256':sha(out/'dev_007.sqlite'),'kpis_supported':[]})
 print(json.dumps({'output':str(out),'report':report},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
