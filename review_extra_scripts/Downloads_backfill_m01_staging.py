#!/usr/bin/env python3
"""Non-destructive raw staging backfill for nine candidate M01 SQLite datasets.
Preserves mart tables and reference imports. Adds every nonblank source row to staging.
"""
import argparse,csv,hashlib,json,sqlite3
from pathlib import Path
from collections import Counter
import openpyxl

def uid(*v):return hashlib.sha256('|'.join(map(str,v)).encode()).hexdigest()[:28]
def csv_rows(path):
 with path.open('r',encoding='utf-8-sig',newline='') as f:
  sample=f.read(8192);f.seek(0)
  try:d=csv.Sniffer().sniff(sample,delimiters=',;\t')
  except csv.Error:d=csv.excel
  yield from enumerate(csv.reader(f,d),1)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--data-root',required=True);ap.add_argument('--db-dir',required=True);ap.add_argument('--shops',nargs='*',default=[f'dev_{i:03d}' for i in [3,4,5,6,7,8,11,13,14]])
 args=ap.parse_args();root=Path(args.data_root);dbdir=Path(args.db_dir)
 for shop in args.shops:
  path=dbdir/(shop+'.sqlite')
  if not path.exists():raise SystemExit(f'MISSING {path}')
  db=sqlite3.connect(path);db.execute('PRAGMA busy_timeout=30000')
  db.execute('CREATE INDEX IF NOT EXISTS idx_staging_source_row ON staging_rows(source_id,source_row)')
  sources=db.execute('SELECT source_id,source_path,source_object,header_row FROM raw_sources').fetchall()
  issue_count=Counter();counts=Counter();skipped=Counter()
  for src,rel,obj,header in sources:
   file=root/rel
   if not file.exists():raise SystemExit(f'MISSING RAW SOURCE {file}')
   ext=file.suffix.lower()
   if ext=='.xlsx':
    wb=openpyxl.load_workbook(file,read_only=True,data_only=True)
    try:
     ws=wb[obj]; iterator=enumerate(ws.values,1)
     n=stage(db,src,header,iterator,issue_count,skipped)
    finally:wb.close()
   elif ext=='.csv':n=stage(db,src,header,csv_rows(file),issue_count,skipped)
   elif ext in ('.sqlite','.db'):
    with sqlite3.connect(f'file:{file.resolve()}?mode=ro',uri=True) as raw:
     quoted='"'+obj.replace('"','""')+'"'
     cols=[x[1] for x in raw.execute(f'PRAGMA table_info({quoted})')]
     def rows():
      yield 1,cols
      for i,r in enumerate(raw.execute(f'SELECT * FROM {quoted}'),2):yield i,r
     n=stage(db,src,header,rows(),issue_count,skipped)
   else:raise SystemExit(f'UNSUPPORTED {file}')
   counts[obj]+=n;db.commit()
  db.execute('UPDATE staging_rows SET issue_count=(SELECT COUNT(*) FROM validation_issues v WHERE v.source_id=staging_rows.source_id AND v.source_row=staging_rows.source_row) WHERE EXISTS (SELECT 1 FROM validation_issues v WHERE v.source_id=staging_rows.source_id AND v.source_row=staging_rows.source_row)')
  before=db.execute('SELECT COUNT(*) FROM staging_rows').fetchone()[0]
  missing=db.execute('SELECT COUNT(*) FROM validation_issues v WHERE NOT EXISTS(SELECT 1 FROM staging_rows s WHERE s.source_id=v.source_id AND s.source_row=v.source_row)').fetchone()[0]
  if missing:raise RuntimeError(f'{shop}: {missing} validation issues without staging rows')
  status=db.execute('PRAGMA integrity_check').fetchone()[0]
  if status!='ok':raise RuntimeError(f'{shop}: {status}')
  row=db.execute('SELECT catalog_json FROM business_catalog WHERE catalog_key=?',(shop,)).fetchone()
  if row:
   cat=json.loads(row[0]);cat['staging_rows_preserved']=before;cat['staging_backfill_status']='ALL_NONBLANK_MAPPED_SOURCE_ROWS_PRESERVED';cat['validation_issues_without_staging']=missing
   cat['approval_status']='CANDIDATE_NOT_APPROVED';db.execute('UPDATE business_catalog SET catalog_json=? WHERE catalog_key=?',(json.dumps(cat,ensure_ascii=False),shop))
  db.commit();db.close()
  print('PASS',shop,'staging_rows',before,'unlinked_validation',missing,'integrity',status,flush=True)
 print('DONE STAGING BACKFILL')
def stage(db,src,header,iterator,issue_count,skipped):
 hdr=None;buffer=[];n=0
 for rn,values in iterator:
  if rn==header:
   hdr=[str(v).strip() if v is not None else '' for v in values];continue
  if rn<header or hdr is None:continue
  if not any(v is not None and str(v).strip() for v in values):continue
  raw={f'{i}:{h or "col"}':values[i] if i<len(values) else None for i,h in enumerate(hdr)}
  if len(values)>len(hdr):
   for i in range(len(hdr),len(values)):raw[f'{i}:extra']=values[i]
  buffer.append((uid(src,rn),src,rn,json.dumps(raw,ensure_ascii=False,default=str),None,0));n+=1
  if len(buffer)>=1000:
   db.executemany('INSERT OR IGNORE INTO staging_rows VALUES(?,?,?,?,?,?)',buffer);buffer=[]
 if buffer:db.executemany('INSERT OR IGNORE INTO staging_rows VALUES(?,?,?,?,?,?)',buffer)
 return n
if __name__=='__main__':main()
