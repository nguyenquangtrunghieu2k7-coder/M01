#!/usr/bin/env python3
"""Dev010 candidate adapter. Never edits original CSV or approved shops."""
import argparse,csv,hashlib,json,pathlib,re,sqlite3,collections,datetime
from decimal import Decimal,InvalidOperation
FILES={'orders':'don_hang.csv','order_lines':'chi_tiet_don.csv','payments':'thanh_toan.csv','customers':'khach_hang.csv','products':'san_pham.csv'}
KEY={'orders':'Số CT','order_lines':'Mã bill','payments':'Mã TT','customers':'Mã khách','products':'Mã vạch'}
ID=re.compile(r'^ORD\d{6}$');PAY=re.compile(r'^PAY\d{6}$')
def norm(v):return str(v or '').strip()
def money(v):
 s=norm(v).lower().replace(' ','').replace('đ','').replace('₫','')
 if not s:return None
 if re.fullmatch(r'-?\d[\d.,]*',s):
  return int(s.replace('.','').replace(',',''))
 m=re.fullmatch(r'(-?)(\d+)(?:([,.])(\d+))?tr',s)
 if m:
  return int(Decimal(m[2]+('.'+(m[4] or '')))*1000000)*(-1 if m[1] else 1)
 m=re.fullmatch(r'(-?)(\d+)tr(\d{1,3})',s)
 if m:return (-1 if m[1] else 1)*(int(m[2])*1000000+int(m[3].ljust(3,'0'))*1000)
 return None
def read(path):
 with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
 src=pathlib.Path(a.source);out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=True)
 rows={t:read(src/f) for t,f in FILES.items()}
 hashes={f:hashlib.sha256((src/f).read_bytes()).hexdigest() for f in FILES.values()}
 db=out/'dev_010.sqlite'
 if db.exists():raise SystemExit('Refusing to overwrite existing SQLite: '+str(db))
 con=sqlite3.connect(db);con.execute('PRAGMA foreign_keys=ON')
 con.executescript("""CREATE TABLE source_rows(source_table TEXT,source_row INTEGER,record_type TEXT,raw_json TEXT,PRIMARY KEY(source_table,source_row));
 CREATE TABLE orders(order_id TEXT PRIMARY KEY,order_date TEXT,status TEXT,channel TEXT,customer_id TEXT,gross_amount INTEGER,discount_amount INTEGER,shipping_amount INTEGER,customer_paid INTEGER,outstanding_amount INTEGER,source_row INTEGER UNIQUE);
 CREATE TABLE order_lines(source_row INTEGER PRIMARY KEY,order_id TEXT REFERENCES orders(order_id),line_no TEXT,product_id TEXT,quantity_raw TEXT,quantity_converted_raw TEXT,unit_price INTEGER,line_amount INTEGER,line_discount INTEGER,unit TEXT);
 CREATE TABLE payments(payment_id TEXT PRIMARY KEY,order_id TEXT REFERENCES orders(order_id),paid_at TEXT,method TEXT,amount INTEGER,source_row INTEGER UNIQUE);
 CREATE TABLE customers(customer_id TEXT PRIMARY KEY,customer_name TEXT,raw_json TEXT,source_row INTEGER UNIQUE);
 CREATE TABLE products(product_id TEXT PRIMARY KEY,product_name TEXT,list_price INTEGER,raw_json TEXT,source_row INTEGER UNIQUE);
 CREATE TABLE excluded_records(source_table TEXT,source_row INTEGER,reason TEXT,raw_json TEXT,PRIMARY KEY(source_table,source_row));
 CREATE TABLE mapping_issues(source_table TEXT,source_row INTEGER,issue TEXT,details TEXT);
 CREATE INDEX idx_lines_order ON order_lines(order_id);CREATE INDEX idx_payments_order ON payments(order_id);""")
 issues=collections.Counter();excluded=collections.Counter();accepted=collections.Counter()
 def issue(t,i,code,detail=''):
  issues[code]+=1;con.execute('INSERT INTO mapping_issues VALUES(?,?,?,?)',(t,i,code,str(detail)[:500]))
 def exclude(t,i,r,reason):
  excluded[(t,reason)]+=1;con.execute('INSERT INTO excluded_records VALUES(?,?,?,?)',(t,i,reason,json.dumps(r,ensure_ascii=False)))
 for t,rs in rows.items():
  for i,r in enumerate(rs,2):
   k=norm(r.get(KEY[t]));typ='header' if k==KEY[t] else 'transaction' if (bool(ID.fullmatch(k)) if t in ('orders','order_lines') else bool(PAY.fullmatch(k)) if t=='payments' else True) else 'summary_or_other'
   con.execute('INSERT INTO source_rows VALUES(?,?,?,?)',(t,i,typ,json.dumps(r,ensure_ascii=False)))
 for t,key,name in [('customers','Mã khách','Khách lẻ/sỉ'),('products','Mã vạch','ten_hang')]:
  for i,r in enumerate(rows[t],2):
   k=norm(r[key])
   if not k:exclude(t,i,r,'missing_key');continue
   try:
    if t=='customers':con.execute('INSERT INTO customers VALUES(?,?,?,?)',(k,r.get(name),json.dumps(r,ensure_ascii=False),i))
    else:con.execute('INSERT INTO products VALUES(?,?,?,?,?)',(k,r.get(name),money(r.get('Giá bán')),json.dumps(r,ensure_ascii=False),i))
    accepted[t]+=1
   except sqlite3.IntegrityError:exclude(t,i,r,'duplicate_key');issue(t,i,'DUPLICATE_KEY',k)
 for i,r in enumerate(rows['orders'],2):
  k=norm(r['Số CT'])
  if not ID.fullmatch(k):exclude('orders',i,r,'summary_or_other');continue
  vals=[money(r[x]) for x in ('Thành tiền','Tiền giảm','Phí vận chuyển','Khách trả','Con no')]
  for field,v in zip(('Thành tiền','Tiền giảm','Phí vận chuyển','Khách trả','Con no'),vals):
   if v is None:issue('orders',i,'UNPARSEABLE_MONEY',field+': '+r[field])
  date=norm(r['Date']);status=norm(r['Xử lý'])
  if date:
   try:datetime.date.fromisoformat(date)
   except ValueError:issue('orders',i,'INVALID_DATE',date)
  if not status:issue('orders',i,'MISSING_STATUS',k)
  try:
   con.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)',(k,date,status,norm(r['Kênh đặt']),norm(r['Mã thẻ']) or None,*vals,i));accepted['orders']+=1
  except sqlite3.IntegrityError:exclude('orders',i,r,'duplicate_order_id');issue('orders',i,'DUPLICATE_ORDER_ID',k)
 valid={x[0] for x in con.execute('SELECT order_id FROM orders')}
 products={x[0] for x in con.execute('SELECT product_id FROM products')}
 for i,r in enumerate(rows['order_lines'],2):
  k=norm(r['Mã bill'])
  if k=='Mã bill':exclude('order_lines',i,r,'repeated_header');continue
  if not ID.fullmatch(k):exclude('order_lines',i,r,'non_transaction_key');continue
  if k not in valid:exclude('order_lines',i,r,'orphan_order');issue('order_lines',i,'ORPHAN_ORDER',k);continue
  product=norm(r['Mã H.hóa'])
  if product not in products:issue('order_lines',i,'UNKNOWN_PRODUCT',product)
  amounts=[money(r[x]) for x in ('Đơn giá (đ)','Cộng','CK')]
  if any(v is None for v in amounts):issue('order_lines',i,'UNPARSEABLE_LINE_AMOUNT',k)
  con.execute('INSERT INTO order_lines VALUES(?,?,?,?,?,?,?,?,?,?)',(i,k,norm(r['No.']),product,norm(r['SoLuong']),norm(r['SL quy đổi']),amounts[0],amounts[1],amounts[2],norm(r['dvt'])));accepted['order_lines']+=1
 for i,r in enumerate(rows['payments'],2):
  pid=norm(r['Mã TT']);oid=norm(r['Mã đơn'])
  if not PAY.fullmatch(pid):exclude('payments',i,r,'non_payment_id');continue
  if oid not in valid:exclude('payments',i,r,'orphan_order');issue('payments',i,'ORPHAN_PAYMENT',oid);continue
  amount=money(r['So tien'])
  if amount is None:issue('payments',i,'UNPARSEABLE_PAYMENT',pid)
  try:con.execute('INSERT INTO payments VALUES(?,?,?,?,?,?)',(pid,oid,norm(r['Ngay thu']),norm(r['Loại TT']),amount,i));accepted['payments']+=1
  except sqlite3.IntegrityError:exclude('payments',i,r,'duplicate_payment_id');issue('payments',i,'DUPLICATE_PAYMENT_ID',pid)
 con.commit()
 # Independent reference checks use raw CSV row values, not adapter transformations.
 raw_order={norm(r['Số CT']) for r in rows['orders'] if ID.fullmatch(norm(r['Số CT']))}
 raw_lines={norm(r['Mã bill']) for r in rows['order_lines'] if ID.fullmatch(norm(r['Mã bill']))}
 raw_pay={norm(r['Mã đơn']) for r in rows['payments'] if PAY.fullmatch(norm(r['Mã TT']))}
 checks={}
 def check(k,e,v):checks[k]={'expected':e,'actual':v,'pass':e==v}
 for t in FILES:check(t+'_source_rows',len(rows[t]),con.execute('SELECT COUNT(*) FROM source_rows WHERE source_table=?',(t,)).fetchone()[0])
 check('distinct_orders',len(raw_order),con.execute('SELECT COUNT(*) FROM orders').fetchone()[0])
 check('valid_lines',sum(bool(ID.fullmatch(norm(r['Mã bill']))) and norm(r['Mã bill']) in raw_order for r in rows['order_lines']),con.execute('SELECT COUNT(*) FROM order_lines').fetchone()[0])
 check('valid_payments',sum(bool(PAY.fullmatch(norm(r['Mã TT']))) and norm(r['Mã đơn']) in raw_order for r in rows['payments']),con.execute('SELECT COUNT(*) FROM payments').fetchone()[0])
 check('orders_without_lines',len(raw_order-raw_lines),con.execute('SELECT COUNT(*) FROM orders o WHERE NOT EXISTS(SELECT 1 FROM order_lines l WHERE l.order_id=o.order_id)').fetchone()[0])
 check('orders_without_payments',len(raw_order-raw_pay),con.execute('SELECT COUNT(*) FROM orders o WHERE NOT EXISTS(SELECT 1 FROM payments p WHERE p.order_id=o.order_id)').fetchone()[0])
 check('line_fk',0,con.execute('SELECT COUNT(*) FROM order_lines l LEFT JOIN orders o ON l.order_id=o.order_id WHERE o.order_id IS NULL').fetchone()[0])
 check('payment_fk',0,con.execute('SELECT COUNT(*) FROM payments p LEFT JOIN orders o ON p.order_id=o.order_id WHERE o.order_id IS NULL').fetchone()[0])
 check('integrity','ok',con.execute('PRAGMA integrity_check').fetchone()[0])
 check('source_accountability',sum(map(len,rows.values())),sum(accepted.values())+sum(excluded.values()))
 qa={'approval':'CANDIDATE_NOT_APPROVED','checks':checks,'all_structural_checks_pass':all(x['pass'] for x in checks.values()),'issues':dict(issues),'accepted':dict(accepted),'excluded':{t+':'+reason:n for (t,reason),n in excluded.items()},'financial_qa':'NOT_RUN','warnings':['Money parser requires independently validated reference totals and status semantics before production.']}
 (out/'qa_report.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2))
 tables=['orders','order_lines','payments','customers','products','source_rows','excluded_records','mapping_issues']
 contract={'version':'dev010-candidate-v2','approval':'CANDIDATE_NOT_APPROVED','tables':{t:[x[1] for x in con.execute('PRAGMA table_info('+t+')')] for t in tables},'kpis_supported':[]}
 (out/'schema_contract.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2))
 con.close()
 manifest={'version':contract['version'],'approval':'CANDIDATE_NOT_APPROVED','source_sha256':hashes,'sqlite_sha256':hashlib.sha256(db.read_bytes()).hexdigest(),'kpis_supported':[],'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 print(json.dumps({'output':str(out),'qa_structural_pass':qa['all_structural_checks_pass'],'accepted':dict(accepted),'issues':dict(issues),'excluded':qa['excluded'],'failed_checks':[k for k,v in checks.items() if not v['pass']]},ensure_ascii=False,indent=2))
