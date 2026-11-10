#!/usr/bin/env python3
"""Read-only source diagnosis: exact duplicate order lines and cancellation accounting."""
import argparse,csv,collections,json,pathlib,re
def load(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def num(v):
 s=str(v or '').strip().lower().replace('đ','').replace('₫','').replace(' ','')
 if 'tr' in s:
  a,b=s.split('tr');from decimal import Decimal
  return int(Decimal(a.replace(',','.'))*1000000)+(int(b.ljust(3,'0'))*1000 if b else 0)
 return int(s.replace('.','').replace(',','')) if s else 0
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);a=p.parse_args();root=pathlib.Path(a.source)
 orders={r['Số CT'].strip():r for r in load(root/'don_hang.csv') if re.fullmatch(r'ORD\d{6}',r['Số CT'].strip())}
 lines=[r for r in load(root/'chi_tiet_don.csv') if r['Mã bill'].strip() in orders]
 groups=collections.defaultdict(list)
 for r in lines:groups[r['Mã bill'].strip()].append(r)
 duplicate_orders=0;duplicate_rows=0;duplicate_amount=0;reconciled=0;unreconciled=[];diffs=collections.Counter();examples=[]
 for oid,rs in groups.items():
  seen=set();unique=[];dups=[]
  for r in rs:
   sig=tuple((k,str(v).strip()) for k,v in sorted(r.items()))
   if sig in seen:dups.append(r)
   else:seen.add(sig);unique.append(r)
  if dups:
   duplicate_orders+=1;duplicate_rows+=len(dups);duplicate_amount+=sum(num(r['Cộng']) for r in dups)
  o=orders[oid];gross=num(o['Thành tiền']);discount=num(o['Tiền giảm']);shipping=num(o['Phí vận chuyển'])
  original=sum(num(r['Cộng']) for r in rs)-discount+shipping
  dedup=sum(num(r['Cộng']) for r in unique)-discount+shipping
  if original!=gross:
   diffs[(o['Xử lý'].strip(),'original_mismatch')]+=1
   if dedup==gross:reconciled+=1
   else:
    diffs[(o['Xử lý'].strip(),'remaining_after_exact_dedup')]+=1
    if len(unreconciled)<15:unreconciled.append({'order_id':oid,'status':o['Xử lý'],'gross':gross,'original':original,'dedup':dedup,'duplicate_lines':len(dups),'line_ck':sum(num(r['CK']) for r in unique)})
  if dups and len(examples)<8:examples.append({'order_id':oid,'duplicate_lines':len(dups),'duplicate_amount':sum(num(r['Cộng']) for r in dups),'gross':gross,'original':original,'dedup':dedup})
 cancellations=[r for r in orders.values() if r['Xử lý'].strip()=='cancelled']
 result={'approval':'DIAGNOSTIC_ONLY','source_order_count':len(orders),'source_line_count':len(lines),'orders_with_exact_duplicate_lines':duplicate_orders,'exact_duplicate_line_copies':duplicate_rows,'duplicate_line_amount_total':duplicate_amount,'gross_equation_mismatches_resolved_by_exact_dedup':reconciled,'mismatch_counts':{':'.join(k):v for k,v in diffs.items()},'unreconciled_examples':unreconciled,'duplicate_examples':examples,'cancelled_orders':len(cancellations),'cancelled_paid_nonzero':sum(num(r['Khách trả'])!=0 for r in cancellations),'cancelled_debt_nonzero':sum(num(r['Con no'])!=0 for r in cancellations),'cancelled_gross_nonzero':sum(num(r['Thành tiền'])!=0 for r in cancellations),'note':'Do not delete duplicate lines until source business key and exact duplication semantics are confirmed.'}
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
