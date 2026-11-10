#!/usr/bin/env python3
"""Independent dev010 source-to-SQLite financial reconciliation; read-only, fail-closed."""
import argparse,csv,json,pathlib,sqlite3,collections,re
from decimal import Decimal,InvalidOperation
def parse(s):
 s=str(s or '').strip().lower().replace(' ','').replace('₫','').replace('đ','')
 if not s:return None
 sign=-1 if s.startswith('-') else 1
 if sign<0:s=s[1:]
 if 'tr' in s:
  a,b=s.split('tr')
  if not a or not a.replace(',','.').replace('.','',1).isdigit():return None
  try:
   major=Decimal(a.replace(',','.'))*1000000
   if b:
    if not b.isdigit() or len(b)>3 or '.' in a or ',' in a:return None
    major+=int(b)*10**(6-len(b))
   return sign*int(major)
  except InvalidOperation:return None
 if not re.fullmatch(r'[\d.,]+',s):return None
 # Vietnamese thousands groups, or plain integers. Ambiguous decimals are NOT silently rounded.
 if re.fullmatch(r'\d{1,3}([.,]\d{3})+',s):return sign*int(re.sub('[.,]','',s))
 if s.isdigit():return sign*int(s)
 return None
def read(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);a=p.parse_args()
 src=pathlib.Path(a.source);out=pathlib.Path(a.candidate);db=out/'dev_010.sqlite'
 orders=read(src/'don_hang.csv');lines=read(src/'chi_tiet_don.csv');payments=read(src/'thanh_toan.csv')
 con=sqlite3.connect('file:'+str(db.resolve())+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
 expected={};unparsed=[];status=collections.Counter()
 for rownum,r in enumerate(orders,2):
  k=r['Số CT'].strip()
  if not re.fullmatch(r'ORD\d{6}',k):continue
  vals={}
  for field in ('Thành tiền','Tiền giảm','Phí vận chuyển','Khách trả','Con no'):
   vals[field]=parse(r[field])
   if vals[field] is None:unparsed.append({'file':'don_hang.csv','row':rownum,'field':field,'value':r[field]})
  expected[k]=(r['Xử lý'].strip(),vals);status[r['Xử lý'].strip()]+=1
 sums=collections.defaultdict(lambda:[0,0,0]);bad_lines=[]
 seen_signatures={};expected_duplicates={};duplicate_total=0
 for rownum,r in enumerate(lines,2):
  k=r['Mã bill'].strip()
  if k not in expected:continue
  signature=tuple((field,str(value or '').strip()) for field,value in sorted(r.items()))
  if signature in seen_signatures:
   expected_duplicates[rownum]=(seen_signatures[signature],k,parse(r['Cộng']))
   duplicate_total+=parse(r['Cộng']) or 0
   continue
  seen_signatures[signature]=rownum
  vals=[parse(r[c]) for c in ('Cộng','CK','Đơn giá (đ)')]
  if any(v is None for v in vals):bad_lines.append({'row':rownum,'order_id':k,'values':vals});continue
  sums[k][0]+=vals[0];sums[k][1]+=vals[1];sums[k][2]+=1
 receipts=collections.defaultdict(int);payment_counts=collections.Counter();bad_pay=[]
 for rownum,r in enumerate(payments,2):
  k=r['Mã đơn'].strip()
  if k not in expected:continue
  v=parse(r['So tien'])
  if v is None:bad_pay.append({'row':rownum,'order_id':k,'value':r['So tien']});continue
  receipts[k]+=v;payment_counts[k]+=1
 db_orders={r['order_id']:r for r in con.execute('SELECT * FROM orders')}
 db_duplicates={r['duplicate_source_row']:(r['retained_source_row'],r['order_id'],r['duplicate_line_amount']) for r in con.execute('SELECT * FROM dedup_lineage')}
 db_lines=collections.defaultdict(lambda:[0,0,0])
 for r in con.execute('SELECT order_id,line_amount,line_discount FROM order_lines'):
  a=db_lines[r['order_id']];a[0]+=r['line_amount'] or 0;a[1]+=r['line_discount'] or 0;a[2]+=1
 db_receipts=collections.defaultdict(int);db_payment_counts=collections.Counter()
 for r in con.execute('SELECT order_id,amount FROM payments'):
  db_receipts[r['order_id']]+=r['amount'] or 0;db_payment_counts[r['order_id']]+=1
 mismatches=collections.Counter();samples=collections.defaultdict(list);equations=collections.Counter()
 if db_duplicates!=expected_duplicates:
  mismatches['DEDUP_LINEAGE_MISMATCH']+=1
  samples['DEDUP_LINEAGE_MISMATCH'].append({'expected_count':len(expected_duplicates),'actual_count':len(db_duplicates),'expected_total':duplicate_total,'actual_total':sum(x[2] or 0 for x in db_duplicates.values())})
 def record(code,k,details):
  mismatches[code]+=1
  if len(samples[code])<8:samples[code].append({'order_id':k,**details})
 fields={'Thành tiền':'gross_amount','Tiền giảm':'discount_amount','Phí vận chuyển':'shipping_amount','Khách trả':'customer_paid','Con no':'outstanding_amount'}
 for k,(st,v) in expected.items():
  d=db_orders.get(k)
  if d is None:record('MISSING_DB_ORDER',k,{});continue
  if d['status']!=st:record('STATUS_MISMATCH',k,{'source':st,'db':d['status']})
  for field,col in fields.items():
   if v[field]!=d[col]:record('MONEY_MAPPING_MISMATCH',k,{'field':field,'source':v[field],'db':d[col]})
  if sums[k]!=db_lines[k]:record('LINE_AGGREGATION_MISMATCH',k,{'source':sums[k],'db':db_lines[k]})
  if receipts[k]!=db_receipts[k] or payment_counts[k]!=db_payment_counts[k]:record('PAYMENT_AGGREGATION_MISMATCH',k,{'source_amount':receipts[k],'db_amount':db_receipts[k],'source_count':payment_counts[k],'db_count':db_payment_counts[k]})
  gross,discount,shipping,paid,debt=(v[f] for f in fields)
  if None not in (gross,paid,debt):
   if st=='cancelled':
    equations['cancelled_paid_debt_zero_checked']+=1
    if paid!=0 or debt!=0:record('CANCELLED_WITH_PAID_OR_DEBT',k,{'status':st,'gross':gross,'paid':paid,'debt':debt})
   else:
    equations['active_gross_equals_paid_plus_debt_checked']+=1
    if gross!=paid+debt:record('GROSS_VS_PAID_DEBT',k,{'status':st,'gross':gross,'paid':paid,'debt':debt})
  if None not in (gross,discount,shipping) and sums[k][2]:
   equations['gross_equals_lines_minus_order_discount_plus_shipping_checked']+=1
   if gross!=sums[k][0]-discount+shipping:record('GROSS_VS_LINES_DISCOUNT_SHIPPING',k,{'status':st,'gross':gross,'lines':sums[k][0],'discount':discount,'shipping':shipping,'delta':gross-(sums[k][0]-discount+shipping)})
  if paid is not None:
   equations['customer_paid_equals_receipts_checked']+=1
   if paid!=receipts[k]:record('PAID_VS_RECEIPTS',k,{'status':st,'paid':paid,'receipts':receipts[k],'delta':paid-receipts[k]})
 con.close()
 hard=['MISSING_DB_ORDER','STATUS_MISMATCH','MONEY_MAPPING_MISMATCH','LINE_AGGREGATION_MISMATCH','PAYMENT_AGGREGATION_MISMATCH','DEDUP_LINEAGE_MISMATCH','CANCELLED_WITH_PAID_OR_DEBT','GROSS_VS_PAID_DEBT','GROSS_VS_LINES_DISCOUNT_SHIPPING','PAID_VS_RECEIPTS']
 report={'approval':'CANDIDATE_NOT_APPROVED','independent_reference':'raw CSV parsed separately from adapter','source_order_count':len(expected),'status_counts':dict(status),'exact_duplicate_line_copies':len(expected_duplicates),'duplicate_line_amount':duplicate_total,'unparsed_order_money_count':len(unparsed),'unparsed_order_money_examples':unparsed[:30],'unparsed_line_count':len(bad_lines),'unparsed_line_examples':bad_lines[:10],'unparsed_payment_count':len(bad_pay),'unparsed_payment_examples':bad_pay[:10],'equations_checked':dict(equations),'mismatch_counts':dict(mismatches),'mismatch_samples':dict(samples),'exact_source_to_mart_pass':not any(mismatches[c] for c in hard) and not unparsed and not bad_lines and not bad_pay,'financial_semantics_approved':not any(mismatches.values()) and not unparsed and not bad_lines and not bad_pay,'notes':['Exact source row duplicates are excluded once and fully preserved in source_rows and dedup_lineage.','Cancelled orders retain pre-cancellation gross but paid and outstanding must both be zero.','KPI production release remains separate from financial parity passing.']}
 target=out/'financial_qa_report.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'report':str(target),'source_to_mart_pass':report['exact_source_to_mart_pass'],'financial_semantics_approved':report['financial_semantics_approved'],'duplicate_line_copies':len(expected_duplicates),'duplicate_line_amount':duplicate_total,'status_counts':report['status_counts'],'unparsed_order_money_count':len(unparsed),'unparsed_line_count':len(bad_lines),'unparsed_payment_count':len(bad_pay),'equations_checked':report['equations_checked'],'mismatch_counts':report['mismatch_counts'],'samples':{k:v[:3] for k,v in samples.items()}},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
