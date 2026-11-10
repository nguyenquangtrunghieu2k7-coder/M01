#!/usr/bin/env python3
"""Read-only inventory and order-grain audit for dev_008 Excel source (stdlib only)."""
import argparse,collections,hashlib,json,pathlib,re,zipfile,xml.etree.ElementTree as ET
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
SALES=['ChiTietHoaDon_1.xlsx','ChiTietHoaDon_2.xlsx']
FILES=SALES+['DanhMucHang.xlsx','ChiTietNhapHang.xlsx']
def rows(path):
 with zipfile.ZipFile(path) as z:
  shared=[]
  if 'xl/sharedStrings.xml' in z.namelist():
   root=ET.fromstring(z.read('xl/sharedStrings.xml'))
   shared=[''.join(x.itertext()) for x in root]
  sheet=next(n for n in z.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',n))
  with z.open(sheet) as f:
   for event,elem in ET.iterparse(f,events=('end',)):
    if elem.tag!='{'+NS['m']+'}row':continue
    record={}
    for c in elem.findall('m:c',NS):
     pos=c.get('r');match=re.match(r'[A-Z]+',pos or '')
     if not match:continue
     key=0
     for ch in match.group():key=key*26+ord(ch)-64
     v=c.find('m:v',NS);inline=c.find('m:is',NS)
     value=v.text if v is not None else ''.join(inline.itertext()) if inline is not None else ''
     if c.get('t')=='s' and value:value=shared[int(value)]
     record[key-1]=value
    yield int(elem.get('r','0')),record
    elem.clear()
def audit(root):
 result={'shop':'dev_008','approval':'SOURCE_AUDIT_ONLY','files':{},'sales':{},'warnings':[]}
 bills=collections.defaultdict(list);line_keys=collections.Counter();status=collections.Counter();methods=collections.Counter();dates=collections.Counter();notes=collections.Counter();missing=collections.Counter();inconsistencies=collections.Counter()
 for file in FILES:
  path=root/file
  if not path.is_file():raise FileNotFoundError(path)
  it=rows(path)
  _,header=next(it);columns={i:str(x).strip() for i,x in header.items()}
  result['files'][file]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'columns':[columns[i] for i in sorted(columns)],'rows':0}
  if file not in SALES:
   result['files'][file]['rows']=sum(1 for _,r in it if r)
   continue
  required=['Bill','Số dòng','Ma hang','TT đơn','Ngày xuất','Thanh toán bằng','Tong tien','Tổng tiền hàng','Giảm giá HĐ','Phi ship','Thành tiền','Giảm (đ)','Note']
  index={v:i for i,v in columns.items()}
  absent=[name for name in required if name not in index]
  if absent:raise ValueError(file+' missing columns '+str(absent))
  for rowno,raw in it:
   if not raw:continue
   result['files'][file]['rows']+=1
   v={name:str(raw.get(col,'')).strip() for name,col in index.items()}
   bill=v['Bill']
   if not re.fullmatch(r'ORD\d+',bill):
    missing['invalid_bill']+=1;continue
   bills[bill].append((file,rowno,v))
   line_keys[(bill,v['Số dòng'])]+=1
   status[v['TT đơn']]+=1;methods[v['Thanh toán bằng']]+=1
   dates[v['Ngày xuất']]+=1
   if v['Note']:notes[v['Thanh toán bằng']]+=1
   for field in ('Ma hang','Số dòng','Thành tiền','Tong tien'):
    if not v[field]:missing[field]+=1
 result['sales']={'valid_orders':len(bills),'valid_sale_line_rows':sum(map(len,bills.values())),'repeated_order_line_keys':sum(n-1 for n in line_keys.values() if n>1),'bills_with_repeated_line_keys':sum(any(line_keys[(bill,line['Số dòng'])]>1 for _,_,line in rows_) for bill,rows_ in bills.items()),'status_line_counts':dict(status),'payment_method_line_counts':dict(methods),'notes_by_payment_method':dict(notes),'missing_fields':dict(missing),'date_sample':dates.most_common(5)}
 cross_file=set()
 for bill,entries in bills.items():
  if len({e[0] for e in entries})>1:cross_file.add(bill)
  for field in ('Tong tien','Tổng tiền hàng','Giảm giá HĐ','Phi ship','TT đơn','Thanh toán bằng','Ngày xuất'):
   variants={e[2][field] for e in entries}
   if len(variants)>1:inconsistencies[field]+=1
 result['sales']['orders_present_in_both_exports']=len(cross_file)
 result['sales']['header_field_inconsistent_orders']=dict(inconsistencies)
 result['warnings']=['Status/method totals count lines, not distinct orders.','No KPI is approved by this audit; source header values must be deduplicated by Bill.','Debt notes require explicit parse and validation; cancelled orders excluded from completed revenue.']
 return result
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',default='outputs/dev008_source_audit.json');a=p.parse_args()
 r=audit(pathlib.Path(a.source));dest=pathlib.Path(a.output);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'report':str(dest),'files':{k:v['rows'] for k,v in r['files'].items()},'sales':r['sales']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
