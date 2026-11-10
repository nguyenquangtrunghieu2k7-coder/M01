"""dev014 XLSX reading and lexical normalization; standard library only."""
import datetime,hashlib,json,re,unicodedata,zipfile,xml.etree.ElementTree as ET
from decimal import Decimal,InvalidOperation
from pathlib import Path
N='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
def clean(x):return str(x if x is not None else '').strip()
def normalize(x):
 t=''.join(ch for ch in unicodedata.normalize('NFD',clean(x).casefold()) if unicodedata.category(ch)!='Mn').replace('đ','d')
 return re.sub('[^a-z0-9]','',t)
def money(x):
 s=clean(x).lower().replace('₫','').replace('đ','').replace(' ','')
 if not s:return None
 neg=-1 if s.startswith('-') else 1
 if neg==-1:s=s[1:]
 m=re.fullmatch(r'(\d+(?:[.,]\d+)?)tr(\d{0,3})',s)
 if m:
  base=Decimal(m[1].replace(',','.'))*1000000
  rest=int(m[2])*10**(6-len(m[2])) if m[2] else 0
  amount=base+rest
 else:
  scale=1000 if s.endswith('k') else 1
  if scale>1:s=s[:-1]
  if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',s):s=s.replace(',','').replace('.','')
  else:s=s.replace(',','.')
  try:amount=Decimal(s)*scale
  except InvalidOperation:return None
 return int(neg*amount) if amount==int(amount) else None
def integer(x):
 s=clean(x)
 return int(s) if re.fullmatch(r'\d+',s) else None
def date(x):
 s=clean(x)
 if not s:return None
 if re.fullmatch(r'\d{5}(?:\.\d+)?',s):return (datetime.datetime(1899,12,30)+datetime.timedelta(days=float(s))).date().isoformat()
 for fmt in ('%d/%m/%Y','%Y-%m-%d'):
  try:return datetime.datetime.strptime(s,fmt).date().isoformat()
  except ValueError:pass
 return None
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
 return h.hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
class Book:
 def __init__(self,path):
  self.z=zipfile.ZipFile(path)
  self.ss=[]
  if 'xl/sharedStrings.xml' in self.z.namelist():
   self.ss=[''.join(x.itertext()) for x in ET.fromstring(self.z.read('xl/sharedStrings.xml'))]
  rel={x.get('Id'):x.get('Target') for x in ET.fromstring(self.z.read('xl/_rels/workbook.xml.rels'))}
  self.sheets={}
  for sh in ET.fromstring(self.z.read('xl/workbook.xml')).find(N+'sheets'):
   loc=rel[sh.get(R+'id')].lstrip('/')
   self.sheets[sh.get('name')]=loc if loc.startswith('xl/') else 'xl/'+loc
 @staticmethod
 def index(label):
  n=0
  for char in label:n=n*26+ord(char)-64
  return n-1
 def rows(self,sheet):
  with self.z.open(self.sheets[sheet]) as file:
   for event,row in ET.iterparse(file,events=('end',)):
    if row.tag!=N+'row':continue
    cols={}
    for c in row.findall(N+'c'):
     m=re.match(r'([A-Z]+)',c.get('r',''))
     if not m:continue
     v=c.find(N+'v');inline=c.find(N+'is')
     value=v.text if v is not None else ''.join(inline.itertext()) if inline is not None else None
     if c.get('t')=='s' and value is not None:value=self.ss[int(value)]
     if value is not None:cols[self.index(m[1])]=value
    yield int(row.get('r')),cols
    row.clear()
 def table(self,sheet,head=1):
  it=self.rows(sheet)
  for n,v in it:
   if n==head:break
  headings={i:clean(x) for i,x in v.items()}
  for n,v in it:
   if v:yield n,{title:v.get(i) for i,title in headings.items()}
