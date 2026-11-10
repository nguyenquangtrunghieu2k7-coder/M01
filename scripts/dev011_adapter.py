#!/usr/bin/env python3
"""Isolated dev011 phone-ledger candidate; preserves all source and never approves KPIs."""
import argparse,collections,datetime,hashlib,json,pathlib,sqlite3
from dev011_source_audit import table,norm,integer
RETURN_TERMS=('trả lại','trả hàng','mang trả','hoàn')
def date(v):
 if not norm(v):return None
 try:return (datetime.date(1899,12,30)+datetime.timedelta(days=int(float(v)))).isoformat()
 except (ValueError,TypeError,OverflowError):return None
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
 src=pathlib.Path(a.source);src=src/'SoBanHang.xlsx' if src.is_dir() else src;out=pathlib.Path(a.output)
 out.mkdir(parents=True,exist_ok=True);db=out/'dev_011.sqlite'
 if db.exists():raise SystemExit('Refusing to overwrite existing SQLite')
 catalog=list(table(src,1));lines=list(table(src,2))
 abbr={norm(r['Ghi tắt']):(norm(r['Tên hàng']),norm(r['Loại'])) for _,r in catalog}
 full={norm(r['Tên hàng']):(norm(r['Tên hàng']),norm(r['Loại'])) for _,r in catalog}
 con=sqlite3.connect(db);con.execute('PRAGMA foreign_keys=ON')
 con.executescript("""
 CREATE TABLE source_rows(sheet TEXT,source_row INTEGER,raw_json TEXT,PRIMARY KEY(sheet,source_row));
 CREATE TABLE product_aliases(source_row INTEGER PRIMARY KEY,alias TEXT,product_name TEXT,product_type TEXT);
 CREATE TABLE orders(order_id INTEGER PRIMARY KEY,order_date TEXT,customer_raw TEXT,status TEXT,note TEXT,items_gross INTEGER,order_discount INTEGER,trade_in_credit INTEGER,customer_paid INTEGER,source_row INTEGER UNIQUE);
 CREATE TABLE order_lines(source_row INTEGER PRIMARY KEY,order_id INTEGER REFERENCES orders(order_id),raw_item TEXT,product_name TEXT,product_type TEXT,imei_raw TEXT,quantity INTEGER,unit_price INTEGER,line_total INTEGER);
 CREATE TABLE mapping_issues(sheet TEXT,source_row INTEGER,issue TEXT,detail TEXT);
 CREATE INDEX order_lines_order ON order_lines(order_id);
 """)
 issues=collections.Counter();counts=collections.Counter();current=None;gross=0
 def problem(sheet,row,code,detail):
  issues[code]+=1;con.execute('INSERT INTO mapping_issues VALUES(?,?,?,?)',(sheet,row,code,str(detail)[:300]))
 for row,r in catalog:
  con.execute('INSERT INTO source_rows VALUES(?,?,?)',('Ghi tắt',row,json.dumps(r,ensure_ascii=False)))
  con.execute('INSERT INTO product_aliases VALUES(?,?,?,?)',(row,norm(r['Ghi tắt']),norm(r['Tên hàng']),norm(r['Loại'])));counts['product_aliases']+=1
 for row,r in lines:
  con.execute('INSERT INTO source_rows VALUES(?,?,?)',('Sổ bán hàng',row,json.dumps(r,ensure_ascii=False)))
  stt=integer(r['STT'])
  if norm(r['STT']) and stt is None:problem('Sổ bán hàng',row,'INVALID_ORDER_ID',r['STT'])
  if stt is not None:
   if current is not None:con.execute('UPDATE orders SET items_gross=? WHERE order_id=?',(gross,current))
   current=stt;gross=0
   note=norm(r['Ghi chú']);status='returned' if any(x in note.lower() for x in RETURN_TERMS) else 'completed'
   day=date(r['Ngày']);discount=integer(r['Bớt']) or 0;credit=integer(r['Thu máy cũ']) or 0;paid=integer(r['Khách trả'])
   if day is None:problem('Sổ bán hàng',row,'INVALID_DATE',r['Ngày'])
   for field in ('Bớt','Thu máy cũ','Khách trả'):
    if norm(r[field]) and integer(r[field]) is None:problem('Sổ bán hàng',row,'INVALID_ORDER_MONEY',field)
   try:
    con.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)',(stt,day,norm(r['Khách']),status,note,0,discount,credit,paid,row));counts['orders']+=1
   except sqlite3.IntegrityError:problem('Sổ bán hàng',row,'DUPLICATE_ORDER_ID',stt)
  if current is None:problem('Sổ bán hàng',row,'ORPHAN_LINE',row);continue
  name=norm(r['Hàng']);product=abbr.get(name) or full.get(name)
  if not product:problem('Sổ bán hàng',row,'UNMAPPED_PRODUCT',name);product=(None,None)
  qty=integer(r['SL']);price=integer(r['Giá']);line_total=integer(r['Thành tiền'])
  if None in (qty,price,line_total):problem('Sổ bán hàng',row,'INVALID_LINE_MONEY',name)
  elif qty*price!=line_total:problem('Sổ bán hàng',row,'LINE_EQUATION_FAIL',row)
  gross+=line_total or 0
  con.execute('INSERT INTO order_lines VALUES(?,?,?,?,?,?,?,?,?)',(row,current,name,product[0],product[1],norm(r['IMEI']),qty,price,line_total));counts['order_lines']+=1
 if current is not None:con.execute('UPDATE orders SET items_gross=? WHERE order_id=?',(gross,current))
 con.commit()
 db_counts={x:con.execute('SELECT COUNT(*) FROM '+x).fetchone()[0] for x in ('orders','order_lines','product_aliases','source_rows','mapping_issues')}
 mismatches=con.execute('SELECT COUNT(*) FROM orders WHERE items_gross-order_discount-trade_in_credit!=customer_paid').fetchone()[0]
 statuses=dict(con.execute('SELECT status,COUNT(*) FROM orders GROUP BY status'))
 qa={'approval':'CANDIDATE_NOT_APPROVED','counts':db_counts,'statuses':statuses,'issues':dict(issues),'order_equation_mismatch_count':mismatches,'all_order_equations_pass':mismatches==0,'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'sqlite_integrity':con.execute('PRAGMA integrity_check').fetchone()[0],'foreign_key_violations':len(con.execute('PRAGMA foreign_key_check').fetchall()),'kpis_supported':[]}
 con.close()
 (out/'qa_report.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2))
 (out/'manifest.json').write_text(json.dumps({'approval':'CANDIDATE_NOT_APPROVED','version':'dev011-candidate-v1','source_sha256':qa['source_sha256'],'sqlite_sha256':hashlib.sha256(db.read_bytes()).hexdigest(),'kpis_supported':[]},ensure_ascii=False,indent=2))
 print(json.dumps({'output':str(out),'approval':qa['approval'],'counts':db_counts,'statuses':statuses,'mapping_issues':dict(issues),'order_equation_mismatches':mismatches,'sqlite_integrity':qa['sqlite_integrity'],'foreign_key_violations':qa['foreign_key_violations']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
