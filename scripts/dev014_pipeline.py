#!/usr/bin/env python3
"""dev014 phone shop; isolated source-bound SQLite candidate."""
import argparse,collections,json,pathlib,re,sqlite3
from dev014_common import Book,clean,normalize,money,integer,date,sha,dump
SOURCES=('SoBanHang.xlsx','SoNo.xlsx','ThuMayCu.xlsx')
RETURN_TERMS=('trả lại hàng','khách mang trả','khách trả lại')
def build(src,out):
 if out.exists():raise RuntimeError('Refusing to overwrite candidate '+str(out))
 for f in SOURCES:
  if not (src/f).is_file():raise RuntimeError('Missing source '+f)
 out.mkdir(parents=True)
 books={f:Book(src/f) for f in SOURCES}
 db=sqlite3.connect(out/'dev_014.sqlite');db.execute('PRAGMA foreign_keys=ON')
 db.executescript('''
 CREATE TABLE source_rows(file TEXT,sheet TEXT,row INTEGER,raw_json TEXT,PRIMARY KEY(file,sheet,row));
 CREATE TABLE aliases(source_row INTEGER PRIMARY KEY,alias TEXT,product_name TEXT,product_type TEXT);
 CREATE TABLE orders(order_id INTEGER PRIMARY KEY,order_date TEXT,customer_raw TEXT,status TEXT,note TEXT,items_gross INTEGER,order_discount INTEGER,trade_in_credit INTEGER,customer_paid_ledger INTEGER,rounding_delta INTEGER,has_installment INTEGER,has_credit INTEGER,source_sheet TEXT,source_row INTEGER);
 CREATE TABLE order_lines(sheet TEXT,row INTEGER,order_id INTEGER REFERENCES orders(order_id),raw_product TEXT,product_name TEXT,product_type TEXT,imei_raw TEXT,quantity INTEGER,unit_price INTEGER,line_total INTEGER,rounding_delta INTEGER,PRIMARY KEY(sheet,row));
 CREATE TABLE sale_imeis(imei TEXT PRIMARY KEY,order_id INTEGER REFERENCES orders(order_id),source_sheet TEXT,source_row INTEGER);
 CREATE TABLE trade_ins(row INTEGER PRIMARY KEY,order_id INTEGER REFERENCES orders(order_id),trade_date TEXT,customer_raw TEXT,phone TEXT,model TEXT,condition_raw TEXT,imei TEXT UNIQUE,trade_value INTEGER,raw_json TEXT);
 CREATE TABLE credit_accounts(order_id INTEGER PRIMARY KEY REFERENCES orders(order_id),initial_debt INTEGER,purchase_date TEXT,customer TEXT,phone TEXT,source_row INTEGER);
 CREATE TABLE credit_payments(row INTEGER PRIMARY KEY,order_id INTEGER REFERENCES credit_accounts(order_id),payment_date TEXT,amount INTEGER,raw_json TEXT);
 CREATE TABLE installment_contracts(order_id INTEGER PRIMARY KEY REFERENCES orders(order_id),contract_date TEXT,customer TEXT,phone TEXT,model TEXT,contract_price INTEGER,upfront INTEGER,term_count INTEGER,monthly_amount INTEGER,due_day INTEGER,schedule_rounding_delta INTEGER,source_row INTEGER);
 CREATE TABLE installment_payments(row INTEGER PRIMARY KEY,order_id INTEGER REFERENCES installment_contracts(order_id),payment_date TEXT,amount INTEGER,raw_json TEXT);
 CREATE TABLE warranty_visits(row INTEGER PRIMARY KEY,visit_date TEXT,customer TEXT,phone TEXT,model TEXT,imei TEXT REFERENCES sale_imeis(imei),purchase_date TEXT,problem TEXT,resolution TEXT,raw_json TEXT);
 CREATE TABLE exact_duplicate_lines(sheet TEXT,row INTEGER,retained_sheet TEXT,retained_row INTEGER,order_id INTEGER,amount INTEGER,PRIMARY KEY(sheet,row));
 CREATE TABLE excluded_rows(file TEXT,sheet TEXT,row INTEGER,reason TEXT,raw_json TEXT,PRIMARY KEY(file,sheet,row));
 CREATE TABLE source_adjustments(sheet TEXT,row INTEGER,code TEXT,delta_vnd INTEGER,details TEXT);
 CREATE TABLE mapping_issues(file TEXT,sheet TEXT,row INTEGER,code TEXT,detail TEXT);
 CREATE INDEX lines_by_order ON order_lines(order_id);
 ''')
 counts=collections.Counter();ex=collections.Counter();diagnostics=collections.Counter();problems=collections.Counter();orders={};order_lines=collections.defaultdict(list);seen={}
 def issue(f,s,r,k,d):
  problems[k]+=1;db.execute('INSERT INTO mapping_issues VALUES(?,?,?,?,?)',(f,s,r,k,clean(d)[:300]))
 def diagnostic(s,r,k,delta,details):
  diagnostics[k]+=1;db.execute('INSERT INTO source_adjustments VALUES(?,?,?,?,?)',(s,r,k,delta,clean(details)[:300]))
 def stage(f,s,n,r):
  db.execute('INSERT INTO source_rows VALUES(?,?,?,?)',(f,s,n,json.dumps(r,ensure_ascii=False,default=str)))
 cat={};b=books[SOURCES[0]]
 for n,r in b.table('Ghi tắt'):
  stage(SOURCES[0],'Ghi tắt',n,r)
  name=clean(r['Tên hàng']);typ=clean(r['Loại'])
  for v in (r['Ghi tắt'],r['Tên hàng']):
   key=normalize(v)
   if key in cat and cat[key]!=(name,typ):issue(SOURCES[0],'Ghi tắt',n,'AMBIGUOUS_ALIAS',v)
   cat[key]=(name,typ)
  db.execute('INSERT INTO aliases VALUES(?,?,?,?)',(n,clean(r['Ghi tắt']),name,typ));counts['aliases']+=1
 for sheet in list(b.sheets)[1:]:
  period=re.fullmatch(r'T(\d+)-(\d{4})',sheet)
  for n,r in b.table(sheet,2):
   stage(SOURCES[0],sheet,n,r)
   oid=integer(r.get('STT'))
   if oid is None:
    x=clean(r.get('Ngày'))
    reason='monthly_subtotal' if x=='Tổng cộng' else 'sheet_note' if x.startswith('Ghi chú:') else 'unrecognized_non_order'
    ex[reason]+=1
    db.execute('INSERT INTO excluded_rows VALUES(?,?,?,?,?)',(SOURCES[0],sheet,n,reason,json.dumps(r,ensure_ascii=False)))
    if reason=='unrecognized_non_order':issue(SOURCES[0],sheet,n,'UNRECOGNIZED_ROW',r)
    continue
   if oid not in orders:
    dt=date(r.get('Ngày'));note=clean(r.get('Ghi chú')).lower();status='returned' if any(w in note for w in RETURN_TERMS) else 'completed'
    if dt is None:issue(SOURCES[0],sheet,n,'INVALID_DATE',r.get('Ngày'))
    if period and dt and dt[:7]!=f'{period[2]}-{int(period[1]):02d}':issue(SOURCES[0],sheet,n,'WRONG_MONTH',dt)
    orders[oid]={'day':dt,'customer':clean(r.get('Khách')),'status':status,'note':note,'discount':money(r.get('Bớt')) or 0,'paid':money(r.get('Khách trả')),'sheet':sheet,'row':n}
    counts['orders']+=1
    db.execute('INSERT INTO orders(order_id,order_date,customer_raw,status,note,order_discount,customer_paid_ledger,source_sheet,source_row) VALUES(?,?,?,?,?,?,?,?,?)',(oid,dt,clean(r.get('Khách')),status,note,money(r.get('Bớt')) or 0,money(r.get('Khách trả')),sheet,n))
   else:
    h=orders[oid]
    for k,rawval in [('day',date(r.get('Ngày'))),('discount',money(r.get('Bớt')) or 0),('paid',money(r.get('Khách trả')))]:
     if h[k]!=rawval:issue(SOURCES[0],sheet,n,'ORDER_HEADER_CONFLICT',str((oid,k,h[k],rawval)))
    if normalize(h['customer'])!=normalize(r.get('Khách')):issue(SOURCES[0],sheet,n,'CUSTOMER_CONFLICT',oid)
    if h['note']!=clean(r.get('Ghi chú')).lower():issue(SOURCES[0],sheet,n,'NOTE_CONFLICT',oid)
   sig=tuple(sorted((key,clean(val)) for key,val in r.items()))
   if sig in seen:
    orig_sheet,orig_row=seen[sig]
    ex['exact_duplicate_line']+=1
    db.execute('INSERT INTO exact_duplicate_lines VALUES(?,?,?,?,?,?)',(sheet,n,orig_sheet,orig_row,oid,money(r.get('Thành tiền'))))
    continue
   seen[sig]=(sheet,n)
   product=clean(r.get('Hàng'));mapping=cat.get(normalize(product))
   if mapping is None:issue(SOURCES[0],sheet,n,'UNKNOWN_PRODUCT',product);mapping=(None,None)
   q=integer(r.get('SL'));price=money(r.get('Giá'));total=money(r.get('Thành tiền'))
   if None in (q,price,total):issue(SOURCES[0],sheet,n,'BAD_LINE_MONEY',oid)
   gap=total-q*price if None not in (q,price,total) else None
   if gap is not None and abs(gap)>1:issue(SOURCES[0],sheet,n,'LINE_MONEY_MISMATCH',str((oid,gap)))
   elif gap:diagnostic(sheet,n,'LINE_ROUNDING_1VND',gap,oid)
   db.execute('INSERT INTO order_lines VALUES(?,?,?,?,?,?,?,?,?,?,?)',(sheet,n,oid,product,*mapping,clean(r.get('IMEI')),q,price,total,gap));counts['order_lines']+=1
   order_lines[oid].append((sheet,n,total,q,clean(r.get('IMEI')),mapping[1]))
   if mapping[1] in ('máy mới','máy cũ'):
    imeis=re.findall(r'(?<!\d)\d{15}(?!\d)',clean(r.get('IMEI')))
    if q is not None and len(imeis)!=q:issue(SOURCES[0],sheet,n,'PHONE_IMEI_COUNT_MISMATCH',str((oid,q,imeis)))
    for imei in imeis:
     try:db.execute('INSERT INTO sale_imeis VALUES(?,?,?,?)',(imei,oid,sheet,n));counts['sale_imeis']+=1
     except sqlite3.IntegrityError:issue(SOURCES[0],sheet,n,'DUPLICATE_IMEI',imei)
   elif mapping[1]=='phụ kiện' and clean(r.get('IMEI')):issue(SOURCES[0],sheet,n,'ACCESSORY_WITH_IMEI',oid)
 trade=collections.defaultdict(int)
 for n,r in books[SOURCES[2]].table('Sheet1'):
  stage(SOURCES[2],'Sheet1',n,r)
  oid=integer(r['Trừ vào (STT sổ bán)']);amt=money(r['Giá thu']);imei=clean(r['IMEI'])
  if oid not in orders:issue(SOURCES[2],'Sheet1',n,'ORPHAN_TRADE_IN',oid)
  if amt is None or amt<0:issue(SOURCES[2],'Sheet1',n,'BAD_TRADE_VALUE',r['Giá thu'])
  trade[oid]+=amt or 0
  try:
   db.execute('INSERT INTO trade_ins VALUES(?,?,?,?,?,?,?,?,?,?)',(n,oid,date(r['Ngày']),clean(r['Khách']),clean(r['SĐT']),clean(r['Máy thu']),clean(r['Tình trạng']),imei,amt,json.dumps(r,ensure_ascii=False)))
   counts['trade_ins']+=1
  except sqlite3.IntegrityError:issue(SOURCES[2],'Sheet1',n,'DUPLICATE_TRADE_IMEI',imei)
 paybook=books[SOURCES[1]];inst=set()
 for n,r in paybook.table('Trả góp'):
  stage(SOURCES[1],'Trả góp',n,r)
  oid=integer(r.get('STT'))
  if oid not in orders:issue(SOURCES[1],'Trả góp',n,'ORPHAN_INSTALLMENT',oid);continue
  if clean(r.get('Ngày')):
   if oid in inst:issue(SOURCES[1],'Trả góp',n,'DUPLICATE_CONTRACT',oid)
   inst.add(oid)
   price=money(r['Giá']);upfront=money(r['Trả trước']);terms=integer(r['Số kỳ']);monthly=money(r['Góp/tháng']);due=integer(r['Hạn góp (ngày)'])
   gap=price-upfront-terms*monthly if None not in (price,upfront,terms,monthly) else None
   if gap is None or abs(gap)>6:issue(SOURCES[1],'Trả góp',n,'INSTALLMENT_EQUATION',str((oid,gap)))
   if gap:diagnostic('Trả góp',n,'INSTALLMENT_SCHEDULE_ROUNDING',gap,oid)
   db.execute('INSERT INTO installment_contracts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(oid,date(r['Ngày']),clean(r['Khách']),clean(r['SĐT']),clean(r['Máy']),price,upfront,terms,monthly,due,gap,n));counts['installment_contracts']+=1
  if clean(r.get('Đã góp')):
   val=money(r['Đã góp']);dt=date(r['Ngày góp'])
   if val is None or dt is None:issue(SOURCES[1],'Trả góp',n,'INVALID_INSTALLMENT_PAYMENT',oid)
   db.execute('INSERT INTO installment_payments VALUES(?,?,?,?,?)',(n,oid,dt,val,json.dumps(r,ensure_ascii=False)));counts['installment_payments']+=1
 credit=set()
 for n,r in paybook.table('Sổ nợ'):
  stage(SOURCES[1],'Sổ nợ',n,r)
  match=re.search(r'STT\s*(\d+)',clean(r.get('Ghi chú')),re.I)
  oid=int(match[1]) if match else None
  if oid not in orders:issue(SOURCES[1],'Sổ nợ',n,'ORPHAN_CREDIT',r.get('Ghi chú'));continue
  if clean(r.get('Ngày')):
   if oid in credit:issue(SOURCES[1],'Sổ nợ',n,'DUPLICATE_CREDIT_ACCOUNT',oid)
   credit.add(oid);amt=money(r['Nợ'])
   if amt is None:issue(SOURCES[1],'Sổ nợ',n,'INVALID_INITIAL_DEBT',oid)
   db.execute('INSERT INTO credit_accounts VALUES(?,?,?,?,?,?)',(oid,amt,date(r['Ngày']),clean(r['Khách']),clean(r['SĐT']),n));counts['credit_accounts']+=1
  if clean(r.get('Đã trả')):
   val=money(r['Đã trả']);dt=date(r['Ngày trả'])
   if val is None or dt is None:issue(SOURCES[1],'Sổ nợ',n,'INVALID_CREDIT_PAYMENT',oid)
   db.execute('INSERT INTO credit_payments VALUES(?,?,?,?,?)',(n,oid,dt,val,json.dumps(r,ensure_ascii=False)));counts['credit_payments']+=1
 for n,r in paybook.table('Bảo hành'):
  stage(SOURCES[1],'Bảo hành',n,r)
  imei=clean(r['IMEI'])
  if not db.execute('SELECT 1 FROM sale_imeis WHERE imei=?',(imei,)).fetchone():issue(SOURCES[1],'Bảo hành',n,'WARRANTY_IMEI_NOT_SOLD',imei)
  db.execute('INSERT INTO warranty_visits VALUES(?,?,?,?,?,?,?,?,?,?)',(n,date(r['Ngày nhận']),clean(r['Khách']),clean(r['SĐT']),clean(r['Máy']),imei,date(r['Ngày mua']),clean(r['Lỗi']),clean(r['Xử lý']),json.dumps(r,ensure_ascii=False)));counts['warranty_visits']+=1
 for oid,h in orders.items():
  gross=sum(r[2] or 0 for r in order_lines[oid]);delta=gross-h['discount']-trade[oid]-h['paid'] if h['paid'] is not None else None
  if delta is None or abs(delta)>1:issue(SOURCES[0],h['sheet'],h['row'],'ORDER_ARITHMETIC',str((oid,delta)))
  elif delta:diagnostic(h['sheet'],h['row'],'ORDER_ROUNDING_1VND',delta,oid)
  db.execute('UPDATE orders SET items_gross=?,trade_in_credit=?,rounding_delta=?,has_installment=?,has_credit=? WHERE order_id=?',(gross,trade[oid],delta,int(oid in inst),int(oid in credit),oid))
  counts['completed_orders' if h['status']=='completed' else 'returned_orders']+=1
 db.commit()
 report={'approval':'CANDIDATE_NOT_APPROVED','accepted':dict(counts),'excluded':dict(ex),'diagnostics':dict(diagnostics),'issues':dict(problems),'statuses':dict(db.execute('SELECT status,COUNT(*) FROM orders GROUP BY status')),'foreign_key_violations':len(db.execute('PRAGMA foreign_key_check').fetchall()),'sqlite_integrity':db.execute('PRAGMA integrity_check').fetchone()[0]}
 db.close()
 dump(out/'candidate_report.json',report);dump(out/'manifest.json',{'approval':'CANDIDATE_NOT_APPROVED','version':'dev014-candidate-v1','source_sha256':{f:sha(src/f) for f in SOURCES},'sqlite_sha256':sha(out/'dev_014.sqlite')})
 print(json.dumps({'output':str(out),'candidate':report},ensure_ascii=False,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args();build(pathlib.Path(a.source),pathlib.Path(a.output))
