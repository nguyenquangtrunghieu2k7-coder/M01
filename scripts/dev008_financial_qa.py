#!/usr/bin/env python3
"""Independent financial/source parity for dev_008; no KPI approval by itself.

Treat all repeated (Bill, Số dòng) keys as distinct pending evidence, never
silently delete them. Source accounting determines whether copies are real.
"""
import argparse,collections,datetime,hashlib,json,pathlib,re,sqlite3
from decimal import Decimal
from dev008_source_audit import rows as xlsx_rows
SALES=('ChiTietHoaDon_1.xlsx','ChiTietHoaDon_2.xlsx')
def parse(v):
 s=str(v if v is not None else '').strip().lower().replace(' ','').replace('đ','').replace('₫','')
 if not s:return None
 neg=s.startswith('-')
 if neg:s=s[1:]
 m=re.fullmatch(r'(\d+(?:[,.]\d+)?)tr(\d{0,3})',s)
 if m:
  n=Decimal(m[1].replace(',','.'))*1000000
  if m[2]:n+=Decimal(m[2])*10**(6-len(m[2]))
  return -int(n) if neg else int(n)
 if re.fullmatch(r'\d+',s):return -int(s) if neg else int(s)
 if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',s):
  n=int(re.sub('[.,]','',s));return -n if neg else n
 return None
def records(path):
 it=xlsx_rows(path)
 _,h=next(it);cols={k:str(v).strip() for k,v in h.items()}
 for line,values in it:
  if not values:continue
  yield line,{field:values.get(col) for col,field in cols.items()}
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);a=p.parse_args()
 source=pathlib.Path(a.source);dest=pathlib.Path(a.candidate)
 con=sqlite3.connect('file:'+str((dest/'dev_008.sqlite').resolve())+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
 reference={};line_sums=collections.defaultdict(int);line_counts=collections.Counter();linekeys=collections.Counter()
 mismatch=collections.Counter();samples=collections.defaultdict(list);errors=[]
 def flag(kind,detail):
  mismatch[kind]+=1
  if len(samples[kind])<8:samples[kind].append(detail)
 file_counts={};invalid=collections.Counter();money_unparsed=collections.Counter()
 for file in SALES:
  file_counts[file]=0
  for rowno,r in records(source/file):
   file_counts[file]+=1;oid=str(r.get('Bill') or '').strip()
   if not re.fullmatch(r'ORD\d+',oid):
    invalid[file]+=1
    continue
   raw_header={c:str(r.get(c) if r.get(c) is not None else '').strip() for c in ('Ngày xuất','Giờ bán','TT đơn','Thanh toán bằng','Mã người mua','Kênh bán','Note')}
   values={}
   for field in ('Tổng tiền hàng','Giảm giá HĐ','Phi ship','Tong tien','Đơn giá (đ)','Giảm (đ)','Thành tiền'):
    values[field]=parse(r.get(field))
    if values[field] is None:money_unparsed[field]+=1
   if oid not in reference:reference[oid]=(raw_header,values,file,rowno)
   else:
    first,firstv,_,_=reference[oid]
    for field in first:
     if first[field]!=raw_header[field]:flag('SOURCE_INCONSISTENT_HEADER',{'order_id':oid,'field':field,'file':file,'row':rowno})
    for field in ('Tổng tiền hàng','Giảm giá HĐ','Phi ship','Tong tien'):
     if firstv[field]!=values[field]:flag('SOURCE_INCONSISTENT_ORDER_MONEY',{'order_id':oid,'field':field,'file':file,'row':rowno})
   line_counts[oid]+=1;linekeys[(oid,str(r.get('Số dòng') or '').strip())]+=1
   if values['Thành tiền'] is not None:line_sums[oid]+=values['Thành tiền']
 order_rows={r['order_id']:r for r in con.execute('SELECT * FROM orders')}
 db_lines={r[0]:(r[1],r[2]) for r in con.execute('SELECT order_id,COUNT(*),SUM(line_total) FROM order_lines GROUP BY order_id')}
 check={'source_orders':len(reference),'db_orders':len(order_rows),'source_lines':sum(line_counts.values()),'db_lines':sum(r[0] for r in db_lines.values()),'source_summary_rows':sum(invalid.values()),'source_repeated_line_key_copies':sum(n-1 for n in linekeys.values() if n>1)}
 for oid,(header,v,file,rowno) in reference.items():
  db=order_rows.get(oid)
  if db is None:
   flag('MISSING_DB_ORDER',{'order_id':oid});continue
  for field,key in [('Tổng tiền hàng','order_items_total'),('Giảm giá HĐ','order_discount'),('Phi ship','shipping_fee'),('Tong tien','order_payable')]:
   if v[field]!=db[key]:flag('DB_ORDER_AMOUNT_PARITY',{'order_id':oid,'field':field,'source':v[field],'db':db[key]})
  if header['TT đơn']!=db['raw_status'] or header['Thanh toán bằng']!=db['payment_method']:flag('DB_ORDER_ATTRIBUTE_PARITY',{'order_id':oid})
  if db_lines.get(oid)!=(line_counts[oid],line_sums[oid]):flag('DB_LINE_PARITY',{'order_id':oid,'source_lines':line_counts[oid],'db':db_lines.get(oid),'source_line_sum':line_sums[oid]})
  if None not in (v['Tổng tiền hàng'],v['Giảm giá HĐ'],v['Phi ship'],v['Tong tien']):
   if v['Tong tien']!=v['Tổng tiền hàng']-v['Giảm giá HĐ']+v['Phi ship']:
    flag('SOURCE_ORDER_PAYABLE_EQUATION',{'order_id':oid,'source_total':v['Tong tien'],'calculated':v['Tổng tiền hàng']-v['Giảm giá HĐ']+v['Phi ship']})
   if v['Tổng tiền hàng']!=line_sums[oid]:
    flag('SOURCE_ITEMS_VS_LINES',{'order_id':oid,'items_total':v['Tổng tiền hàng'],'line_sum':line_sums[oid],'delta':v['Tổng tiền hàng']-line_sums[oid]})
 for file,rows in file_counts.items():
  dbcount=con.execute('SELECT COUNT(*) FROM source_rows WHERE source_file=?',(file,)).fetchone()[0]
  if dbcount!=rows:flag('SOURCE_ROW_COVERAGE',{'file':file,'source':rows,'db':dbcount})
 other_files=('DanhMucHang.xlsx','ChiTietNhapHang.xlsx')
 for file in other_files:
  actual=sum(1 for _ in records(source/file))
  dbcount=con.execute('SELECT COUNT(*) FROM source_rows WHERE source_file=?',(file,)).fetchone()[0]
  if actual!=dbcount:flag('OTHER_SOURCE_ROW_COVERAGE',{'file':file,'source':actual,'db':dbcount})
 check['foreign_key_violations']=len(con.execute('PRAGMA foreign_key_check').fetchall())
 check['sqlite_integrity']=con.execute('PRAGMA integrity_check').fetchone()[0]
 if check['source_orders']!=check['db_orders']:flag('ORDER_COUNT_MISMATCH',check)
 if check['source_lines']!=check['db_lines']:flag('LINE_COUNT_MISMATCH',check)
 if check['foreign_key_violations'] or check['sqlite_integrity']!='ok':flag('DB_INTEGRITY_ERROR',check)
 con.close()
 structural_errors={'SOURCE_INCONSISTENT_HEADER','SOURCE_INCONSISTENT_ORDER_MONEY','MISSING_DB_ORDER','DB_ORDER_AMOUNT_PARITY','DB_ORDER_ATTRIBUTE_PARITY','DB_LINE_PARITY','SOURCE_ROW_COVERAGE','OTHER_SOURCE_ROW_COVERAGE','ORDER_COUNT_MISMATCH','LINE_COUNT_MISMATCH','DB_INTEGRITY_ERROR'}
 report={'shop':'dev_008','approval':'CANDIDATE_NOT_APPROVED','source_to_mart_pass':not any(mismatch[k] for k in structural_errors) and not money_unparsed,'financial_equation_pass':not mismatch['SOURCE_ITEMS_VS_LINES'] and not mismatch['SOURCE_ORDER_PAYABLE_EQUATION'],'counts':check,'unparseable_money':dict(money_unparsed),'mismatch_counts':dict(mismatch),'mismatch_samples':dict(samples),'notes':['Order-header values are counted once per Bill','Repeated order-line keys are preserved pending source-level duplicate proof','Debt note parsing and KPI status semantics not yet approved']}
 target=dest/'financial_qa_report.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps({'report':str(target),'source_to_mart_pass':report['source_to_mart_pass'],'financial_equation_pass':report['financial_equation_pass'],'counts':check,'unparseable_money':dict(money_unparsed),'mismatch_counts':dict(mismatch),'samples':{k:v[:3] for k,v in samples.items()}},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
