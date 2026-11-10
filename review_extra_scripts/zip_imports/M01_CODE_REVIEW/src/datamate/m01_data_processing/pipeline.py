"""M01 auditable raw -> staging -> mart pilot, using only stdlib SQLite and safe XLSX XML.
Mappings must be source-evidenced AND explicitly approved for production.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,decimal,hashlib,json,re,sqlite3,zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

VERSION='0.2.0'; D=decimal.Decimal
TABLES=['orders','order_lines','order_adjustments','products','customers','entity_aliases','unit_conversions','payments','purchase_receipts','purchase_lines','returns','inventory_events','inventory_snapshots','lots','lot_allocations','price_history','expenses','deliveries','service_visits','visit_tasks','trade_ins','installment_schedules','warranty_visits']
XMLNS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
def uid(*x):return hashlib.sha256('|'.join(map(str,x)).encode()).hexdigest()[:28]
def norm(s):return re.sub(r'\s+',' ',str(s or '')).strip()
def date_parse(s):
 if s is None or str(s).strip()=='':return None
 if isinstance(s,(int,float)) or re.fullmatch(r'\d+(?:\.\d+)?',str(s).strip()):
  n=float(s)
  if 30000<n<90000:return (dt.datetime(1899,12,30)+dt.timedelta(days=n)).date().isoformat()
 m=re.fullmatch(r'\s*(\d{1,2})\s+th(?:g|áng)\s+(\d{1,2})\s+(\d{4})\s*',str(s),re.IGNORECASE)
 if m:return dt.date(int(m.group(3)),int(m.group(2)),int(m.group(1))).isoformat()
 for fmt in ('%d/%m/%Y','%Y-%m-%d','%d-%m-%Y','%Y-%m-%d %H:%M:%S','%Y-%m-%dT%H:%M:%S'):
  try:return dt.datetime.strptime(str(s).strip(),fmt).date().isoformat()
  except ValueError:pass
 raise ValueError(f'date format unsupported: {s!r}')
def money_parse(s):
 if s is None or str(s).strip()=='':return None
 v=str(s).strip().replace(' ','').replace('₫','').replace('đ','').replace('Đ','')
 mul=1000 if v.lower().endswith('k') else 1
 if mul!=1:v=v[:-1]
 if not re.fullmatch(r'[+-]?[0-9][0-9.,]*',v):raise ValueError('unsupported money '+str(s))
 if ',' in v and '.' in v:
  # commas are grouped thousands, dot decimal only in this evidenced pattern
  if not re.fullmatch(r'[+-]?\d{1,3}(,\d{3})+(\.\d+)?',v):raise ValueError('ambiguous money '+str(s))
  v=v.replace(',','')
 elif ',' in v:
  if re.fullmatch(r'[+-]?\d{1,3}(,\d{3})+',v):v=v.replace(',','')
  else:raise ValueError('ambiguous comma '+str(s))
 elif '.' in v:
  if re.fullmatch(r'[+-]?\d{1,3}(\.\d{3})+',v):v=v.replace('.','')
  elif not re.fullmatch(r'[+-]?\d+\.\d{1,4}',v):raise ValueError('ambiguous dot '+str(s))
 return format(D(v)*mul,'f')
def quantity_parse(s):
 if s is None or norm(s)=='':return None,None
 if isinstance(s,(int,float)):return format(D(str(s)),'f'),None
 m=re.fullmatch(r'([+-]?\d+(?:[.,]\d+)?)\s*([^\d]*)',norm(s))
 if not m:raise ValueError('unsupported quantity '+str(s))
 return format(D(m.group(1).replace(',','.')),'f'),norm(m.group(2)) or None

def read_csv(path):
 with open(path,'r',encoding='utf-8-sig',newline='') as f:
  sample=f.read(4096);f.seek(0)
  try:dialect=csv.Sniffer().sniff(sample,delimiters=',;\t')
  except csv.Error:dialect=csv.excel
  for i,row in enumerate(csv.reader(f,dialect),1):yield i,row,[]
def xlsx_sheet_mapping(z):
 ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
 root=ET.fromstring(z.read('xl/workbook.xml'));rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
 targets={r.attrib['Id']:r.attrib['Target'] for r in rels};out={}
 for s in root.find('m:sheets',ns):
  target=targets[s.attrib['{'+ns['r']+'}id']].lstrip('/')
  if not target.startswith('xl/'):target='xl/'+target
  out[s.attrib['name']]=target
 return out
def col_index(cell):
 s=re.match('[A-Z]+',cell).group();n=0
 for c in s:n=n*26+ord(c)-64
 return n-1
def read_xlsx(path,sheet):
 with zipfile.ZipFile(path) as z:
  mapping=xlsx_sheet_mapping(z)
  if sheet not in mapping:raise ValueError('sheet not found '+sheet)
  shared=[]
  if 'xl/sharedStrings.xml' in z.namelist():
   root=ET.fromstring(z.read('xl/sharedStrings.xml'))
   for si in root.findall(XMLNS+'si'):shared.append(''.join(t.text or '' for t in si.iter(XMLNS+'t')))
  with z.open(mapping[sheet]) as f:
   for _,el in ET.iterparse(f,events=('end',)):
    if el.tag!=XMLNS+'row':continue
    number=int(el.attrib.get('r','0')); cells={};issues=[]
    for c in el.findall(XMLNS+'c'):
     ref=c.attrib.get('r','A1');idx=col_index(ref); t=c.attrib.get('t'); v=c.find(XMLNS+'v');inline=c.find(XMLNS+'is');formula=c.find(XMLNS+'f')
     if formula is not None and (v is None or v.text is None):issues.append({'code':'MISSING_FORMULA_CACHE','cell':ref})
     val=v.text if v is not None else None
     if t=='s' and val is not None:val=shared[int(val)]
     elif t=='inlineStr' and inline is not None:val=''.join(x.text or '' for x in inline.iter(XMLNS+'t'))
     elif t=='b' and val is not None:val=bool(int(val))
     elif t not in ('s','inlineStr','str','e','b') and val is not None:
      try:val=int(val) if re.fullmatch(r'-?\d+',val) else float(val)
      except ValueError:pass
     cells[idx]=val
    if cells:yield number,[cells.get(i) for i in range(max(cells)+1)],issues
    el.clear()

def connect(path,supported_tables=None):
 c=sqlite3.connect(path);c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA journal_mode=WAL');
 c.executescript('''CREATE TABLE IF NOT EXISTS dataset_versions(version_id TEXT PRIMARY KEY, shop_id TEXT, contract_version TEXT, config_sha256 TEXT, created_at TEXT, status TEXT);
 CREATE TABLE IF NOT EXISTS raw_sources(source_id TEXT PRIMARY KEY,shop_id TEXT,source_path TEXT,source_sha256 TEXT,source_object TEXT,source_format TEXT,header_row INTEGER);
 CREATE TABLE IF NOT EXISTS staging_rows(staging_uid TEXT PRIMARY KEY,source_id TEXT,source_row INTEGER,raw_json TEXT,parsed_json TEXT,issue_count INTEGER,FOREIGN KEY(source_id) REFERENCES raw_sources(source_id));
 CREATE TABLE IF NOT EXISTS validation_issues(issue_uid TEXT PRIMARY KEY,shop_id TEXT,source_id TEXT,source_row INTEGER,source_cell TEXT,code TEXT,severity TEXT,detail TEXT);
 CREATE TABLE IF NOT EXISTS source_lineage(lineage_uid TEXT PRIMARY KEY,entity_table TEXT,entity_uid TEXT,shop_id TEXT,source_id TEXT,source_row INTEGER,source_cell TEXT,transform_id TEXT,raw_value TEXT,version_id TEXT);
 CREATE TABLE IF NOT EXISTS business_catalog(catalog_key TEXT PRIMARY KEY,catalog_json TEXT);''')
 for table in (supported_tables or []):
  c.execute(f'''CREATE TABLE IF NOT EXISTS {table}(uid TEXT PRIMARY KEY,shop_id TEXT,source_id TEXT,source_row INTEGER,source_business_id TEXT,event_date TEXT,amount TEXT,quantity TEXT,unit TEXT,document_uid TEXT,display_name TEXT,status_raw TEXT,attributes_json TEXT,version_id TEXT)''')
 c.execute('CREATE INDEX IF NOT EXISTS idx_lineage_entity ON source_lineage(entity_table,entity_uid)')
 c.execute('CREATE INDEX IF NOT EXISTS idx_staging_source ON staging_rows(source_id,source_row)')
 for table in (supported_tables or []):c.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_shop ON {table}(shop_id,event_date)')
 return c

def build(config_path,data_root,out_db,allow_provisional=False,profile_path=None):
 cfg=json.loads(Path(config_path).read_text());shop=cfg['shop_id']
 if cfg.get('approval_status')!='APPROVED' and not allow_provisional:raise ValueError('FAIL_CLOSED: mapping not approved; use --allow-provisional for non-production QA only')
 grain_tables={'order':'orders','line_item':'order_lines','payment':'payments','product':'products','customer':'customers','service_visit':'service_visits'}
 supported={grain_tables[x['grain']] for x in cfg['sources']}
 if 'line_item' in [x['grain'] for x in cfg['sources']] and 'order' not in [x['grain'] for x in cfg['sources']]:supported.add('orders')
 root=Path(data_root).resolve();c=connect(out_db,supported)
 version=uid('dataset',shop,hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest());
 status='APPROVED' if cfg.get('approval_status')=='APPROVED' else 'PROVISIONAL_NOT_FOR_PRODUCTION'
 c.execute('INSERT OR REPLACE INTO dataset_versions VALUES(?,?,?,?,?,?)',(version,shop,'0.2.0',uid(json.dumps(cfg,sort_keys=True)),dt.datetime.now(dt.timezone.utc).isoformat(),status))
 profiles=json.loads(Path(profile_path).read_text()) if profile_path else []
 issue_counter={};counts={t:0 for t in TABLES};objects=0
 def issue(source_id,row,code,msg,cell=None,severity='ERROR'):
  key=uid(source_id,row,code,cell,msg)
  c.execute('INSERT OR IGNORE INTO validation_issues VALUES(?,?,?,?,?,?,?,?)',(key,shop,source_id,row,cell,code,severity,str(msg)[:400]));issue_counter[code]=issue_counter.get(code,0)+1
 def emit(table,source_id,row,business_id,date,amount,quantity,unit,doc,name,status,attrs,fields):
  entity_id=uid(shop,table,source_id,row)
  c.execute(f'INSERT OR REPLACE INTO {table} VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(entity_id,shop,source_id,row,business_id,date,amount,quantity,unit,doc,name,status,json.dumps(attrs,ensure_ascii=False),version));counts[table]+=1
  for field,(col,raw) in fields.items():
   if col is None:continue
   c.execute('INSERT OR REPLACE INTO source_lineage VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(entity_id,field,col),table,entity_id,shop,source_id,row,col,'m01:'+field,json.dumps(raw,ensure_ascii=False,default=str),version))
  c.execute('INSERT OR REPLACE INTO source_lineage VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(entity_id,'row'),table,entity_id,shop,source_id,row,None,'source_row',None,version))
  return entity_id
 for spec in cfg['sources']:
  rel=spec['path'];path=(root/rel).resolve()
  if not path.is_relative_to(root) or not path.exists():raise ValueError('invalid/missing source '+rel)
  actual_hash=hashlib.sha256(path.read_bytes()).hexdigest();fmt=spec['format'];selector=spec['object'];header_row=spec['header_row'];mapping=spec['fields'];grain=spec['grain']
  source_id=uid(shop,rel,selector,actual_hash)
  evidence=[p for p in profiles if p['source']['path'].replace('\\','/').endswith(rel) and p['source']['object']==selector]
  if profile_path and not evidence:raise ValueError('profile mismatch '+rel+'::'+selector)
  rows=read_csv(path) if fmt=='csv' else read_xlsx(path,selector)
  header=None;seen=set();objects+=1
  c.execute('INSERT OR REPLACE INTO raw_sources VALUES(?,?,?,?,?,?,?)',(source_id,shop,rel,actual_hash,selector,fmt,header_row))
  for row_no,values,xissues in rows:
   if row_no<header_row:continue
   if row_no==header_row:
    header=[str(x).strip() if x is not None else '' for x in values]
    if len([x for x in header if x])!=len(set(x for x in header if x)):raise ValueError('ambiguous duplicate headers')
    for col in mapping.values():
     if col is not None and col not in header:raise ValueError('missing mapped header '+col)
    if evidence and header[:len(evidence[0]['columns'])]!=[x['name'] for x in evidence[0]['columns']]:raise ValueError('D4 header drift '+rel)
    continue
   if not any(v is not None and str(v).strip() for v in values):continue
   raw={h:(values[i] if i<len(values) else None) for i,h in enumerate(header) if h}
   staging_id=uid(source_id,row_no);parsed={};errors=[]
   for e in xissues:errors.append((e['code'],e['cell']))
   for key,col in mapping.items():
    if not col:continue
    v=raw.get(col)
    try:
     if key in ('date',):parsed[key]=date_parse(v)
     elif key in ('amount','quantity_amount','unit_price','paid','debt'):
      parsed[key]=money_parse(v) if key!='quantity_amount' else quantity_parse(v)[0]
     elif key=='quantity':parsed[key],parsed['quantity_unit_in_cell']=quantity_parse(v)
     else:parsed[key]=norm(v) or None
    except ValueError as err:errors.append(('PARSE_'+key.upper(),col));issue(source_id,row_no,'PARSE_'+key.upper(),err,col)
   for code,cell in xissues:issue(source_id,row_no,code,'formula missing cached value',cell)
   if raw.get(mapping.get('business_id')) and str(raw.get(mapping.get('business_id'))).strip()==str(mapping.get('business_id')):issues_code='REPEATED_HEADER';errors.append((issues_code,None));issue(source_id,row_no,issues_code,'repeated header inside data')
   c.execute('INSERT OR REPLACE INTO staging_rows VALUES(?,?,?,?,?,?)',(staging_id,source_id,row_no,json.dumps(raw,ensure_ascii=False,default=str),json.dumps(parsed,ensure_ascii=False),len(errors)))
   if errors:continue
   if grain=='order':
    bid=parsed.get('business_id');
    if not bid:issue(source_id,row_no,'MISSING_ORDER_KEY','order key missing');continue
    scoped=(shop,bid)
    if scoped in seen:issue(source_id,row_no,'DUPLICATE_ORDER_KEY','repeated source business ID retained pending source-specific dedup rule',severity='WARNING')
    seen.add(scoped)
    fields={k:(v,raw.get(v)) for k,v in mapping.items() if v};doc=uid(shop,'document',bid) if spec.get('document_scope')=='shop' else uid(shop,'document',source_id,bid);ent=emit('orders',source_id,row_no,bid,parsed.get('date'),parsed.get('amount'),None,None,doc,parsed.get('customer'),parsed.get('status'),{'paid_reported':parsed.get('paid'),'debt_as_of_dataset_end':parsed.get('debt'),'goods_value':parsed.get('goods_value'),'source_grain':'order','money_unit':'VND','source_values':parsed},fields)
   elif grain=='line_item':
    bid=parsed.get('business_id');name=parsed.get('item')
    if not bid or not name:issue(source_id,row_no,'MISSING_LINE_FIELDS','order key and product name required');continue
    fields={k:(v,raw.get(v)) for k,v in mapping.items() if v};doc=uid(shop,'document',bid) if spec.get('document_scope')=='shop' else uid(shop,'document',source_id,bid)
    # no document-total inference: observed line amounts remain line only
    emit('order_lines',source_id,row_no,bid,parsed.get('date'),parsed.get('amount'),parsed.get('quantity'),parsed.get('unit') or parsed.get('quantity_unit_in_cell'),doc,name,parsed.get('status'),{'unit_price':parsed.get('unit_price'),'source_grain':'line_item','source_values':parsed},fields)
    if bid not in seen and not (spec.get('document_scope')=='shop' and any(o['grain']=='order' and o.get('document_scope')=='shop' for o in cfg['sources'])):
     seen.add(bid);emit('orders',source_id,row_no,bid,parsed.get('date'),None,None,None,doc,parsed.get('customer'),parsed.get('status'),{'source_grain':'grouped_lines','document_total_not_observed':True}, {'business_id':fields.get('business_id',(None,None))})
   elif grain=='payment':
    bid=parsed.get('business_id');amount=parsed.get('amount')
    if not bid or amount is None:issue(source_id,row_no,'MISSING_PAYMENT_FIELDS','payment document key or amount missing');continue
    fields={k:(v,raw.get(v)) for k,v in mapping.items() if v}
    doc=uid(shop,'document',bid) if spec.get('document_scope')=='shop' else uid(shop,'document',source_id,bid)
    emit('payments',source_id,row_no,bid,parsed.get('date'),amount,None,None,doc,None,None,{'payment_method':parsed.get('payment_method'),'payment_ref':parsed.get('payment_ref'),'source_values':parsed},fields)
   elif grain in ('product','customer'):
    bid=parsed.get('business_id');name=parsed.get('item') or parsed.get('customer')
    if not bid and not name:issue(source_id,row_no,'MISSING_ENTITY_KEY','entity code and name both absent');continue
    fields={k:(v,raw.get(v)) for k,v in mapping.items() if v}
    emit('products' if grain=='product' else 'customers',source_id,row_no,bid,None,parsed.get('amount'),None,parsed.get('unit'),None,name,None,{'source_values':parsed},fields)
   elif grain=='service_visit':
    fields={k:(v,raw.get(v)) for k,v in mapping.items() if v}
    if not parsed.get('date') or not parsed.get('vehicle'):
     issue(source_id,row_no,'INCOMPLETE_SERVICE_VISIT','missing date or vehicle');continue
    emit('service_visits',source_id,row_no,None,parsed.get('date'),parsed.get('amount'),None,None,None,parsed.get('vehicle'),None,{'work_text':parsed.get('work_text'),'mechanic_raw':parsed.get('mechanic'),'note_raw':parsed.get('note'),'source_values':parsed,'no_synthetic_ticket_id':True},fields)
   else:raise ValueError('unsupported grain '+grain)
  c.commit()
 coverage={t:counts[t]>0 for t in TABLES}
 catalog={'shop_id':shop,'version_id':version,'validation_status':status,'contract_version':'0.2.0','source_objects_processed':objects,'row_counts':counts,'issue_counts':issue_counter,'capabilities':{'order_count':coverage['orders'],'line_item_analysis':coverage['order_lines'],'product_analysis':coverage['products'] or coverage['order_lines'],'payment_events':coverage['payments'],'inventory_as_of':coverage['inventory_snapshots'],'service_visits':coverage['service_visits']},'scope':{'date_range':'derived from successfully parsed event dates; inspect DB','snapshot_dates':[]},'join_keys':{'orders.order_lines':'scoped source business id; document_uid differs for grouped-line order, pending reconciliation'},'approval_status':cfg.get('approval_status'),'observed_sources':[s['path']+'::'+s['object'] for s in cfg['sources']],'unsupported_are_not_zero':True,'notes':'Provisional outputs cannot serve production indicators; summary-only does not emit fake lines. Raw inputs remain external, pinned by sha256; staged raw_json retains each ingested row.'}
 c.execute('INSERT OR REPLACE INTO business_catalog VALUES(?,?)',(shop,json.dumps(catalog,ensure_ascii=False)));c.commit();c.close();return catalog

def main():
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);p.add_argument('--data-root',required=True);p.add_argument('--out-db',required=True);p.add_argument('--profile');p.add_argument('--allow-provisional',action='store_true');a=p.parse_args();print(json.dumps(build(a.config,a.data_root,a.out_db,a.allow_provisional,a.profile),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
