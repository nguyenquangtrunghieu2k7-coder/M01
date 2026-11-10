#!/usr/bin/env python3
"""Read-only audit of dev_011 phone-shop ledger; stdlib XLSX reader."""
import argparse,collections,hashlib,json,pathlib,re,xml.etree.ElementTree as ET,zipfile
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
def colnum(c):
 n=0
 for x in c:n=n*26+ord(x)-64
 return n-1
def sheet_rows(path,sheet_index):
 with zipfile.ZipFile(path) as z:
  shared=[]
  if 'xl/sharedStrings.xml' in z.namelist():
   root=ET.fromstring(z.read('xl/sharedStrings.xml'))
   shared=[''.join(n.itertext()) for n in root]
  with z.open('xl/worksheets/sheet%d.xml'%sheet_index) as f:
   for _,row in ET.iterparse(f,events=('end',)):
    if row.tag!=NS+'row':continue
    cells={}
    for c in row.findall(NS+'c'):
     label=re.match(r'([A-Z]+)',c.attrib.get('r',''))
     if not label:continue
     v=c.find(NS+'v');inline=c.find(NS+'is')
     value=v.text if v is not None else ''.join(inline.itertext()) if inline is not None else None
     if c.get('t')=='s' and value is not None:value=shared[int(value)]
     cells[colnum(label[1])]=value
    yield int(row.attrib['r']),cells
    row.clear()
def table(path,i):
 it=sheet_rows(path,i);_,head=next(it);columns={k:str(v).strip() for k,v in head.items()}
 for rownum,values in it:
  if any(v is not None and str(v).strip() for v in values.values()):
   yield rownum,{name:values.get(col) for col,name in columns.items()}
def norm(v):return str(v if v is not None else '').strip()
def integer(v):
 if v is None or norm(v)=='':return None
 try:return int(float(v)) if float(v).is_integer() else None
 except (TypeError,ValueError):return None
def audit(path):
 catalog=list(table(path,1));rows=list(table(path,2))
 abbreviations={norm(r['Ghi tắt']):r for _,r in catalog}
 full_names={norm(r['Tên hàng']) for _,r in catalog}
 groups=[];current=None;errors=collections.Counter();samples=collections.defaultdict(list)
 notes=collections.Counter();statuses=collections.Counter();unmapped=collections.Counter();trade=0
 def flag(code,detail):
  errors[code]+=1
  if len(samples[code])<8:samples[code].append(detail)
 for rownum,r in rows:
  stt=integer(r.get('STT'))
  if norm(r.get('STT')) and stt is None:flag('INVALID_STT',{'row':rownum,'value':r.get('STT')})
  if stt is not None:
   current={'stt':stt,'row':rownum,'lines':[],'header':r};groups.append(current)
  elif current is None:flag('ORPHAN_CONTINUATION',{'row':rownum});continue
  current['lines'].append((rownum,r))
  name=norm(r.get('Hàng'))
  if name and name not in abbreviations and name not in full_names:unmapped[name]+=1
  q=integer(r.get('SL'));price=integer(r.get('Giá'));total=integer(r.get('Thành tiền'))
  if None in (q,price,total):flag('UNPARSEABLE_LINE',{'row':rownum})
  elif q*price!=total:flag('LINE_EQUATION_FAIL',{'row':rownum})
 for o in groups:
  h=o['header'];note=norm(h.get('Ghi chú')).lower();notes[note]+=1
  status='returned' if any(t in note for t in ('trả lại','trả hàng','mang trả','hoàn')) else 'completed'
  statuses[status]+=1
  gross=sum(integer(r.get('Thành tiền')) or 0 for _,r in o['lines'])
  discount=integer(h.get('Bớt')) or 0;credit=integer(h.get('Thu máy cũ')) or 0;paid=integer(h.get('Khách trả'))
  trade+=bool(credit)
  if paid is None:flag('MISSING_CUSTOMER_PAID',{'order':o['stt']})
  elif gross-discount-credit!=paid:flag('ORDER_EQUATION_FAIL',{'order':o['stt'],'gross':gross,'discount':discount,'trade':credit,'paid':paid})
 stt_counts=collections.Counter(o['stt'] for o in groups)
 return {'approval':'SOURCE_AUDIT_ONLY','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'catalog_rows':len(catalog),'sale_rows':len(rows),'orders':len(groups),'unique_stt':len(stt_counts),'duplicate_stt':{str(k):v for k,v in stt_counts.items() if v>1},'status_orders':dict(statuses),'trade_in_orders':trade,'unmapped_names':unmapped.most_common(25),'notes':notes.most_common(25),'source_errors':dict(errors),'error_samples':dict(samples)}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',default='outputs/dev011_source_audit.json');args=p.parse_args()
 src=pathlib.Path(args.source);src=src/'SoBanHang.xlsx' if src.is_dir() else src
 report=audit(src);out=pathlib.Path(args.output);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps({'report':str(out),**{k:report[k] for k in ('catalog_rows','sale_rows','orders','unique_stt','duplicate_stt','status_orders','trade_in_orders','unmapped_names','source_errors','error_samples')}},ensure_ascii=False,indent=2))
