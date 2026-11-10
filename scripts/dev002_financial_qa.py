#!/usr/bin/env python3
"""Independent full-source QA for dev002; no import from business adapter."""
import argparse,collections,datetime,hashlib,json,pathlib,re,sqlite3
from decimal import Decimal,InvalidOperation
from dev011_source_audit import sheet_rows
MONTHLY=tuple('BanHang_T%d_%d.xlsx'%(m,y) for y in (2025,2026) for m in range(1,13) if y==2025 or m<=5)
SOURCES=(*MONTHLY,'DanhSachQuyDoi.xlsx')
STATES={'Đã hoàn thành':'completed','Đã hủy':'cancelled','Đã hoàn hàng':'returned','Đang giao dịch':'in_progress'}
def s(v):return str(v if v is not None else '').strip()
def amount(v):
 x=s(v).lower().replace('₫','').replace('đ','').replace(' ','')
 if not x:return None
 sign=-1 if x.startswith('-') else 1;x=x.lstrip('-');factor=1
 if x.endswith('tr'):x=x[:-2];factor=1000000
 elif x.endswith('k'):x=x[:-1];factor=1000
 if re.fullmatch(r'\d{1,3}(?:[,.]\d{3})+',x):x=re.sub('[,.]','',x)
 else:x=x.replace(',','.')
 try:
  d=Decimal(x)*factor
  return sign*int(d) if d==int(d) else None
 except (InvalidOperation,ValueError):return None
def parse_date(v):
 x=s(v)
 if re.fullmatch(r'\d{5}(?:\.\d+)?',x):return (datetime.date(1899,12,30)+datetime.timedelta(days=int(float(x)))).isoformat()
 try:return datetime.datetime.strptime(x,'%d/%m/%Y').date().isoformat()
 except ValueError:return None
def hashfile(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--candidate',required=True);a=p.parse_args()
 src=pathlib.Path(a.source);candidate=pathlib.Path(a.candidate)
 db=sqlite3.connect('file:'+str((candidate/'dev_002.sqlite').resolve())+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
 errors=collections.Counter();examples=collections.defaultdict(list)
 def fail(kind,detail):
  errors[kind]+=1
  if len(examples[kind])<5:examples[kind].append(detail)
 conversion={}
 for rn,v in sheet_rows(src/'DanhSachQuyDoi.xlsx',1):
  if rn==1:continue
  if not any(s(x) for x in v.values()):continue
  name,unit,factor,base=(s(v.get(i)) for i in range(4))
  conversion[(name,unit)]=(int(factor),base)
 dbcon={(r['product_name'],r['large_unit']):(r['factor'],r['base_unit']) for r in db.execute('SELECT * FROM unit_conversions')}
 if conversion!=dbcon:fail('UNIT_CONVERSION_PARITY',{'source':conversion,'db':dbcon})
 db_orders={r['order_id']:r for r in db.execute('SELECT * FROM orders')}
 db_lines={(r['file'],r['row']):r for r in db.execute('SELECT * FROM order_lines')}
 db_toppings=collections.defaultdict(list)
 for r in db.execute('SELECT * FROM topping_components ORDER BY file,row,position'):
  db_toppings[(r['file'],r['row'])].append((r['position'],r['part_name'],r['part_quantity'],r['part_total']))
 ref_orders={};totals=collections.Counter();line_counts=collections.Counter();line_types=collections.Counter();status_counts=collections.Counter();revenue=collections.Counter();excluded=collections.Counter();sources=collections.Counter();discounts=collections.Counter()
 for f in MONTHLY:
  mt=re.fullmatch(r'BanHang_T(\d+)_(\d+)\.xlsx',f);month,year=map(int,mt.groups())
  for rn,v in sheet_rows(src/f,1):
   if rn<5:continue
   if not any(s(x) for x in v.values()):continue
   sources[f]+=1
   oid=s(v.get(0));key=(f,rn)
   if not re.fullmatch(r'ORD\d+',oid):
    kind='repeated_header' if oid=='Mã đơn hàng' else 'daily_summary' if 'TỔNG NGÀY' in s(v.get(4)) else 'non_transaction'
    excluded[kind]+=1
    if db.execute('SELECT reason FROM excluded_rows WHERE file=? AND row=?',key).fetchone()[0]!=kind:fail('EXCLUDED_REASON',key)
    continue
   dt=parse_date(v.get(1));raw_status=s(v.get(2));status=STATES.get(raw_status);customer=s(v.get(3))
   if status is None or dt is None or dt[:7]!=f'{year}-{month:02d}':fail('INVALID_SOURCE_DATE_STATUS',key)
   if oid not in ref_orders:ref_orders[oid]=(dt,raw_status,status);status_counts[status]+=1
   elif ref_orders[oid]!=(dt,raw_status,status):fail('SOURCE_ORDER_CONFLICT',oid)
   name=s(v.get(4));qraw=s(v.get(5));qm=re.fullmatch(r'(\d+)(?:\s+[a-zA-ZÀ-ỹ]+)?',qraw)
   qty=int(qm[1]) if qm else None
   unit=s(v.get(8));price=amount(v.get(6));total=amount(v.get(7))
   parts=name.split(' + ');product=parts[0].strip();addons=[]
   for j,part in enumerate(parts[1:],1):
    match=re.fullmatch(r'(?:(\d+)\s+)?(.+?)\s*\(([\d.,]+)\s*đ\)',part.strip())
    if not match:fail('RAW_TOPPING_PARSE',(key,part));continue
    addons.append((j,match[2].strip(),int(match[1] or 1),amount(match[3])))
   topping=sum(x[3] or 0 for x in addons)
   if None in (qty,price,total):fail('RAW_MONEY',key);continue
   base=qty*price;disc=base+topping-total
   if disc<0:fail('NEGATIVE_DISCOUNT',key)
   expected=(oid,name,product,unit,qty,qty*conversion.get((product,unit),(1,unit))[0],price,base,topping,disc,total,int(bool(addons)))
   record=db_lines.get(key)
   if record is None:fail('MISSING_DB_LINE',key);continue
   for col,value in zip(('order_id','full_product','base_product','unit','quantity','base_quantity','unit_price','base_amount','topping_amount','line_discount','line_total','has_embedded_topping'),expected):
    if record[col]!=value:fail('LINE_FIELD_PARITY',(key,col,value,record[col]))
   if db_toppings.get(key,[])!=addons:fail('TOPPING_PARITY',(key,addons,db_toppings.get(key)))
   totals[oid]+=total;line_counts[oid]+=1;revenue[status]+=total
   line_types['lines']+=1
   if addons:line_types['embedded_topping_lines']+=1;line_types['topping_components']+=len(addons);discounts['embedded_topping_amount_vnd']+=topping
   if disc>0:discounts['discounted_lines']+=1;discounts['line_discount_vnd']+=disc
 for oid,info in ref_orders.items():
  record=db_orders.get(oid)
  if record is None:fail('MISSING_DB_ORDER',oid);continue
  dt,raw_status,status=info
  if (record['order_date'],record['source_status'],record['status'],record['item_total'],record['line_count'])!=(dt,raw_status,status,totals[oid],line_counts[oid]):
   fail('ORDER_PARITY',oid)
 if len(db_orders)!=len(ref_orders):fail('ORDER_COUNT',(len(db_orders),len(ref_orders)))
 if len(db_lines)!=line_types['lines']:fail('LINE_COUNT',(len(db_lines),line_types['lines']))
 for f,count in sources.items():
  x=db.execute('SELECT COUNT(*) FROM source_rows WHERE file=?',(f,)).fetchone()[0]
  if x!=count:fail('SOURCE_ROW_LINEAGE',(f,count,x))
 if db.execute('SELECT COUNT(*) FROM source_rows WHERE file=?',('DanhSachQuyDoi.xlsx',)).fetchone()[0]!=0:
  fail('CONVERSION_SOURCE_ROW_POLICY','Conversions represented directly in unit_conversions with sheet source_row')
 if db.execute('SELECT COUNT(*) FROM mapping_issues').fetchone()[0]:fail('MAPPING_ISSUES','non-empty')
 if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':fail('SQLITE_INTEGRITY','failed')
 if db.execute('PRAGMA foreign_key_check').fetchall():fail('FOREIGN_KEYS','failed')
 db.close()
 result={'approval':'CANDIDATE_NOT_APPROVED','source_to_mart_pass':not errors,'mismatches':dict(errors),'samples':dict(examples),'source_sha256':{f:hashfile(src/f) for f in SOURCES},'orders':len(ref_orders),'order_lines':line_types['lines'],'source_sale_rows':sum(sources.values()),'excluded':dict(excluded),'statuses':dict(status_counts),'revenue_by_status_vnd':dict(revenue),'toppings_and_discounts':dict(discounts),'topping_component_count':line_types['topping_components'],'unit_conversions':len(conversion)}
 target=candidate/'financial_qa_report.json';target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'report':str(target),'source_to_mart_pass':result['source_to_mart_pass'],'orders':result['orders'],'order_lines':result['order_lines'],'statuses':result['statuses'],'revenue_by_status_vnd':result['revenue_by_status_vnd'],'toppings_and_discounts':result['toppings_and_discounts'],'mismatches':result['mismatches'],'samples':{k:v[:3] for k,v in examples.items()}},ensure_ascii=False,indent=2))
 if errors:raise SystemExit(1)
if __name__=='__main__':main()
