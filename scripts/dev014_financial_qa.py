#!/usr/bin/env python3
"""Independent dev014 source-to-mart QA: re-read XLSX and verify each ledger."""
import argparse,collections,datetime,json,pathlib,re,sqlite3
from decimal import Decimal
from dev014_common import Book,clean,normalize,date,sha,dump
SOURCES=('SoBanHang.xlsx','SoNo.xlsx','ThuMayCu.xlsx')
RETURNS=('trả lại hàng','khách mang trả','khách trả lại')
def value(x):
 s=clean(x).lower().replace('đ','').replace('₫','').replace(' ','')
 if not s:return None
 negative=s.startswith('-');s=s.lstrip('-')
 m=re.fullmatch(r'(\d+(?:[.,]\d+)?)tr(\d{0,3})',s)
 if m:
  amount=Decimal(m[1].replace(',','.'))*Decimal(10)**6
  if m[2]:amount+=Decimal(m[2])*Decimal(10)**(6-len(m[2]))
 else:
  factor=1000 if s.endswith('k') else 1
  if factor!=1:s=s[:-1]
  if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',s):s=re.sub('[,.]','',s)
  else:s=s.replace(',','.')
  try:amount=Decimal(s)*factor
  except Exception:return None
 if amount!=amount.to_integral_value():return None
 return -int(amount) if negative else int(amount)
def number(x):
 x=clean(x)
 return int(x) if x.isdigit() else None
def validate(src,candidate):
 con=sqlite3.connect('file:'+str((candidate/'dev_014.sqlite').resolve())+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
 books={f:Book(src/f) for f in SOURCES};errors=collections.Counter();samples=collections.defaultdict(list)
 def fail(kind,x):
  errors[kind]+=1
  if len(samples[kind])<6:samples[kind].append(x)
 def check_row(table,where,vals,loc):
  columns=list(vals);sql='SELECT '+','.join('"'+x+'"' for x in columns)+' FROM '+table+' WHERE '+where[0]
  row=con.execute(sql,where[1]).fetchone()
  if row is None:fail('MISSING_'+table,loc);return
  for col,expect in vals.items():
   if row[col]!=expect:fail('PARITY_'+table,(loc,col,expect,row[col]))
 alias={};source=books[SOURCES[0]];line_ref={};orders={};duplicates={};seen={};gross=collections.Counter();counts=collections.Counter();statuses=collections.Counter();imei_source={};trade=collections.Counter()
 for n,r in source.table('Ghi tắt'):
  name=clean(r['Tên hàng']);typ=clean(r['Loại']);counts['aliases']+=1
  for x in (r['Ghi tắt'],r['Tên hàng']):
   k=normalize(x)
   if k in alias and alias[k]!=(name,typ):fail('AMBIGUOUS_ALIAS',(n,x))
   alias[k]=(name,typ)
  check_row('aliases',('source_row=?',(n,)),{'alias':clean(r['Ghi tắt']),'product_name':name,'product_type':typ},n)
 for sheet in list(source.sheets)[1:]:
  for n,r in source.table(sheet,2):
   counts['all_sale_sheet_rows']+=1
   oid=number(r.get('STT'))
   if oid is None:
    reason='monthly_subtotal' if clean(r.get('Ngày'))=='Tổng cộng' else 'sheet_note' if clean(r.get('Ngày')).startswith('Ghi chú:') else 'unrecognized_non_order'
    counts['excluded_'+reason]+=1
    check_row('excluded_rows',('file=? AND sheet=? AND row=?',(SOURCES[0],sheet,n)),{'reason':reason},(sheet,n))
    continue
   dt=date(r['Ngày']);note=clean(r.get('Ghi chú')).lower();status='returned' if any(t in note for t in RETURNS) else 'completed'
   hdr=(dt,normalize(r['Khách']),status,note,value(r['Bớt']) or 0,value(r['Khách trả']))
   if oid not in orders:orders[oid]=(hdr,sheet,n);statuses[status]+=1
   elif orders[oid][0]!=hdr:fail('SOURCE_HEADER_MISMATCH',(oid,sheet,n))
   signature=tuple(sorted((k,clean(v)) for k,v in r.items()))
   if signature in seen:
    old=seen[signature];duplicates[(sheet,n)]=(*old,oid,value(r['Thành tiền']))
    check_row('exact_duplicate_lines',('sheet=? AND row=?',(sheet,n)),{'retained_sheet':old[0],'retained_row':old[1],'order_id':oid,'amount':value(r['Thành tiền'])},(sheet,n))
    continue
   seen[signature]=(sheet,n)
   name=clean(r['Hàng']);mapped=alias.get(normalize(name));quantity=number(r['SL']);price=value(r['Giá']);total=value(r['Thành tiền'])
   if mapped is None:fail('UNMAPPED_PRODUCT',(sheet,n,name));continue
   if None in (quantity,price,total) or abs(total-quantity*price)>1:fail('SOURCE_LINE_EQUATION',(sheet,n,quantity,price,total))
   check_row('order_lines',('sheet=? AND row=?',(sheet,n)),{'order_id':oid,'raw_product':name,'product_name':mapped[0],'product_type':mapped[1],'imei_raw':clean(r['IMEI']),'quantity':quantity,'unit_price':price,'line_total':total,'rounding_delta':total-quantity*price},(sheet,n))
   line_ref[(sheet,n)]=(oid,total);gross[oid]+=total or 0
   if mapped[1] in ('máy mới','máy cũ'):
    imeis=re.findall(r'(?<!\d)\d{15}(?!\d)',clean(r['IMEI']))
    if len(imeis)!=quantity:fail('IMEI_QUANTITY',(sheet,n,quantity,len(imeis)))
    for imei in imeis:
     if imei in imei_source:fail('REUSED_SALE_IMEI',imei)
     imei_source[imei]=(oid,sheet,n)
     check_row('sale_imeis',('imei=?',(imei,)),{'order_id':oid,'source_sheet':sheet,'source_row':n},imei)
   elif clean(r['IMEI']):fail('ACCESSORY_WITH_IMEI',(sheet,n))
 trade_ref=[]
 for n,r in books[SOURCES[2]].table('Sheet1'):
  oid=number(r['Trừ vào (STT sổ bán)']);amt=value(r['Giá thu']);trade[oid]+=amt or 0;trade_ref.append((n,oid,amt))
  check_row('trade_ins',('row=?',(n,)),{'order_id':oid,'trade_date':date(r['Ngày']),'customer_raw':clean(r['Khách']),'phone':clean(r['SĐT']),'model':clean(r['Máy thu']),'condition_raw':clean(r['Tình trạng']),'imei':clean(r['IMEI']),'trade_value':amt},n)
 if con.execute('SELECT COUNT(*) FROM trade_ins').fetchone()[0]!=len(trade_ref):fail('TRADE_COUNT',len(trade_ref))
 credit_heads={};credit_payment=collections.Counter();credits=collections.Counter()
 for n,r in books[SOURCES[1]].table('Sổ nợ'):
  m=re.search(r'STT\s*(\d+)',clean(r['Ghi chú']),re.I);oid=int(m[1]) if m else None
  if oid not in orders:fail('ORPHAN_CREDIT',n)
  if clean(r['Ngày']):
   if oid in credit_heads:fail('MULTIPLE_CREDIT_HEADER',oid)
   credit_heads[oid]=value(r['Nợ'])
   check_row('credit_accounts',('order_id=?',(oid,)),{'initial_debt':value(r['Nợ']),'purchase_date':date(r['Ngày']),'customer':clean(r['Khách']),'phone':clean(r['SĐT']),'source_row':n},n)
  if clean(r['Đã trả']):
   amt=value(r['Đã trả']);credit_payment[oid]+=amt or 0;credits['payments']+=1
   check_row('credit_payments',('row=?',(n,)),{'order_id':oid,'payment_date':date(r['Ngày trả']),'amount':amt},n)
 for oid,original in credit_heads.items():
  if credit_payment[oid]>original:fail('CREDIT_OVERPAY',(oid,original,credit_payment[oid]))
 install_heads={};ins_pay=collections.Counter();install=collections.Counter()
 for n,r in books[SOURCES[1]].table('Trả góp'):
  oid=number(r['STT'])
  if oid not in orders:fail('ORPHAN_INSTALLMENT',n)
  if clean(r['Ngày']):
   if oid in install_heads:fail('DUPLICATE_INSTALLMENT_HEADER',oid)
   price=value(r['Giá']);upfront=value(r['Trả trước']);term=number(r['Số kỳ']);monthly=value(r['Góp/tháng']);due=number(r['Hạn góp (ngày)']);rounding=price-upfront-monthly*term
   if abs(rounding)>6:fail('INSTALLMENT_SCHEDULE',(oid,rounding))
   install_heads[oid]=(price,upfront,term,monthly,rounding)
   check_row('installment_contracts',('order_id=?',(oid,)),{'contract_date':date(r['Ngày']),'customer':clean(r['Khách']),'phone':clean(r['SĐT']),'model':clean(r['Máy']),'contract_price':price,'upfront':upfront,'term_count':term,'monthly_amount':monthly,'due_day':due,'schedule_rounding_delta':rounding,'source_row':n},n)
  if clean(r.get('Đã góp')):
   amt=value(r['Đã góp']);ins_pay[oid]+=amt or 0;install['payments']+=1
   check_row('installment_payments',('row=?',(n,)),{'order_id':oid,'payment_date':date(r['Ngày góp']),'amount':amt},n)
 if set(credit_heads)&set(install_heads):fail('OVERLAPPING_FINANCE_LEDGER',len(set(credit_heads)&set(install_heads)))
 warrantyrows=0
 for n,r in books[SOURCES[1]].table('Bảo hành'):
  warrantyrows+=1;imei=clean(r['IMEI'])
  if imei not in imei_source:fail('WARRANTY_IMEI_UNMATCHED',imei)
  check_row('warranty_visits',('row=?',(n,)),{'visit_date':date(r['Ngày nhận']),'customer':clean(r['Khách']),'phone':clean(r['SĐT']),'model':clean(r['Máy']),'imei':imei,'purchase_date':date(r['Ngày mua']),'problem':clean(r['Lỗi']),'resolution':clean(r['Xử lý'])},n)
 for oid,(header,sheet,row) in orders.items():
  day,customer,status,note,discount,paid=header
  delta=gross[oid]-discount-trade[oid]-paid
  if abs(delta)>1:fail('ORDER_EQUATION',(oid,delta))
  check_row('orders',('order_id=?',(oid,)),{'order_date':day,'status':status,'note':note,'items_gross':gross[oid],'order_discount':discount,'trade_in_credit':trade[oid],'customer_paid_ledger':paid,'rounding_delta':delta,'has_installment':int(oid in install_heads),'has_credit':int(oid in credit_heads),'source_sheet':sheet,'source_row':row},oid)
 if con.execute('SELECT COUNT(*) FROM orders').fetchone()[0]!=len(orders):fail('ORDERS_COUNT',len(orders))
 countscheck={'order_lines':len(line_ref),'aliases':counts['aliases'],'sale_imeis':len(imei_source),'trade_ins':len(trade_ref),'credit_accounts':len(credit_heads),'credit_payments':credits['payments'],'installment_contracts':len(install_heads),'installment_payments':install['payments'],'warranty_visits':warrantyrows,'exact_duplicate_lines':len(duplicates),'excluded_rows':counts['excluded_monthly_subtotal']+counts['excluded_sheet_note']}
 for table,n in countscheck.items():
  count=con.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
  if count!=n:fail('COUNT_'+table,(n,count))
 if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':fail('SQLITE_INTEGRITY',None)
 if con.execute('PRAGMA foreign_key_check').fetchall():fail('FOREIGN_KEYS',None)
 if con.execute('SELECT COUNT(*) FROM mapping_issues').fetchone()[0]:fail('MAPPING_ISSUES',None)
 source_counts={}
 for f,book in books.items():
  source_counts[f]=0
  for sh in book.sheets:
   hdr=2 if f=='SoBanHang.xlsx' and sh!='Ghi tắt' else 1
   count=sum(1 for _ in book.table(sh,hdr))
   staged=con.execute('SELECT COUNT(*) FROM source_rows WHERE file=? AND sheet=?',(f,sh)).fetchone()[0]
   if count!=staged:fail('SOURCE_ROW_COVERAGE',(f,sh,count,staged))
   source_counts[f]+=count
 source_hash={f:sha(src/f) for f in SOURCES};con.close()
 result={'source_to_mart_pass':not errors,'mismatches':dict(errors),'samples':dict(samples),'source_sha256':source_hash,'orders':len(orders),'order_lines':len(line_ref),'status_orders':dict(statuses),'alias_rows':counts['aliases'],'exact_duplicates':len(duplicates),'excluded_rows':countscheck['excluded_rows'],'sale_imeis':len(imei_source),'trade_ins':len(trade_ref),'credit_accounts':len(credit_heads),'credit_payments':credits['payments'],'installment_contracts':len(install_heads),'installment_payments':install['payments'],'warranty_visits':warrantyrows,'source_rows_per_file':source_counts}
 dump(candidate/'financial_qa_report.json',result)
 print(json.dumps({'source_to_mart_pass':result['source_to_mart_pass'],'counts':{k:result[k] for k in ('orders','order_lines','exact_duplicates','sale_imeis','trade_ins','credit_accounts','credit_payments','installment_contracts','installment_payments','warranty_visits')},'mismatches':dict(errors),'examples':{k:v[:3] for k,v in samples.items()}},ensure_ascii=False,indent=2))
 if errors:raise SystemExit(1)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);a=p.parse_args();validate(pathlib.Path(a.source),pathlib.Path(a.candidate))
