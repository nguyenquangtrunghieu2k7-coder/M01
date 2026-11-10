#!/usr/bin/env python3
"""Assemble 5 pilot + 9 candidate SQLite into a verifiable M03 sandbox dataset.
Never mutates source databases. Fails closed on missing/invalid sources.
"""
import argparse,csv,hashlib,json,sqlite3,zipfile,datetime
from pathlib import Path

PILOT={1,2,9,10,12}
CANDIDATE={3,4,5,6,7,8,11,13,14}
EXPECTED=PILOT|CANDIDATE

def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def quote(s):return '"'+s.replace('"','""')+'"'
def gettables(c):return {x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
def count(c,t):return c.execute('SELECT COUNT(*) FROM '+quote(t)).fetchone()[0]
def main():
 p=argparse.ArgumentParser();p.add_argument('--pilot-dir',required=True);p.add_argument('--candidate-dir',required=True);p.add_argument('--output',required=True);p.add_argument('--zip',action='store_true');a=p.parse_args()
 out=Path(a.output).expanduser().resolve(); dbdir=out/'databases';dbdir.mkdir(parents=True,exist_ok=True)
 manifest={'contract':'M01-to-M03-sandbox-v1','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'production_eligible':False,'shops':[]};coverage=[];schemas={}
 for i in sorted(EXPECTED):
  shop=f'dev_{i:03d}';origin='pilot' if i in PILOT else 'candidate';source=Path(a.pilot_dir if i in PILOT else a.candidate_dir).expanduser()/f'{shop}.sqlite';dst=dbdir/f'{shop}.sqlite'
  if not source.is_file():raise SystemExit(f'MISSING {source}')
  if source.resolve()==dst.resolve():raise SystemExit('Source and destination must differ')
  with sqlite3.connect(f'file:{source.resolve()}?mode=ro',uri=True) as src:
   if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit(f'INVALID SOURCE {shop}')
   with sqlite3.connect(dst) as target:src.backup(target)
  with sqlite3.connect(f'file:{dst.resolve()}?mode=ro',uri=True) as c:
   if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit(f'INVALID COPY {shop}')
   tables=gettables(c)
   mandatory={'raw_sources','staging_rows','validation_issues','source_lineage','business_catalog'}
   missing=sorted(mandatory-tables)
   if missing:raise SystemExit(f'{shop} missing mandatory tables: {missing}')
   counts={t:count(c,t) for t in sorted(tables) if t not in ('sqlite_sequence',)}
   issue_codes={r[0]:r[1] for r in c.execute('SELECT code,COUNT(*) FROM validation_issues GROUP BY code')}
   orphan_issues=c.execute('SELECT COUNT(*) FROM validation_issues v WHERE NOT EXISTS (SELECT 1 FROM staging_rows s WHERE s.source_id=v.source_id AND s.source_row=v.source_row)').fetchone()[0]
   catalogrow=c.execute('SELECT * FROM business_catalog LIMIT 1').fetchone()
   columns=[x[1] for x in c.execute('PRAGMA table_info(business_catalog)')]
   catalog=dict(zip(columns,catalogrow)) if catalogrow else {}
   parsed={}
   for k,v in catalog.items():
    if isinstance(v,str) and v.startswith(('{','[')):
     try:parsed[k]=json.loads(v)
     except (ValueError,TypeError):parsed[k]=v
    else:parsed[k]=v
   schemas[shop]={t:[{'name':r[1],'type':r[2],'pk':bool(r[5])} for r in c.execute('PRAGMA table_info('+quote(t)+')')] for t in sorted(tables)}
   (out/f'{shop}_catalog.json').write_text(json.dumps(parsed,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
   blockers=[]
   if issue_codes:blockers.append('VALIDATION_ISSUES_PRESENT')
   if orphan_issues:blockers.append('ISSUES_WITHOUT_STAGING')
   if origin=='candidate':blockers.append('CANDIDATE_MAPPING_NOT_APPROVED')
   else:blockers.append('PILOT_MAPPING_PROVISIONAL')
   # Candidate staging backfill can create rows but not full column-level lineage; do not assert complete.
   if counts.get('source_lineage',0)==0:blockers.append('NO_COLUMN_LINEAGE')
   if counts.get('orders',0)==0:blockers.append('NO_ORDER_MART_OR_NOT_APPLICABLE')
   entry={'shop_id':shop,'source_group':origin,'database':f'databases/{shop}.sqlite','sha256':digest(dst),'table_counts':counts,'issue_codes':issue_codes,'validation_issues_without_staging':orphan_issues,'catalog':f'{shop}_catalog.json','blockers':blockers,'production_eligible':False}
   manifest['shops'].append(entry)
   coverage.append({'shop_id':shop,'source_group':origin,'sources':counts.get('raw_sources',0),'staging_rows':counts.get('staging_rows',0),'orders':counts.get('orders',0),'order_lines':counts.get('order_lines',0),'payments':counts.get('payments',0),'reference_rows':counts.get('source_reference_records',0),'validation_issues':counts.get('validation_issues',0),'unlinked_validation':orphan_issues,'production_eligible':False,'blockers':';'.join(blockers)})
   print('PASS',shop,origin,'staging',counts.get('staging_rows',0),'issues',counts.get('validation_issues',0),'integrity ok',flush=True)
 manifest['shop_count']=len(manifest['shops']);manifest['totals']={'staging_rows':sum(x['staging_rows'] for x in coverage),'validation_issues':sum(x['validation_issues'] for x in coverage)}
 (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 (out/'schema_contract.json').write_text(json.dumps(schemas,ensure_ascii=False,indent=2),encoding='utf-8')
 with (out/'shop_coverage.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=coverage[0].keys());w.writeheader();w.writerows(coverage)
 (out/'M03_README.md').write_text('''# M01 BusinessDataset — M03 sandbox handoff\n\nContains 14 read-only SQLite BusinessDatasets with mart, staging, validation, catalog and lineage as available per shop.\n\n## Access\nUse `sqlite3.connect("file:/absolute/path/to/databases/dev_XXX.sqlite?mode=ro", uri=True)` and inspect `manifest.json` and `schema_contract.json` before queries. `shop_id` is the isolation boundary. Do not sum `orders.amount` with `order_lines.amount`; grain and semantic approval are not guaranteed.\n\n## Safety\nAll shops are provisional, `production_eligible=false`. Do not publish KPIs until mapping and reconciliation are approved. `unlinked_validation=0` proves issue-to-staging traceability only; it does not resolve validation issues. Some candidate marts use heuristic mapping and may contain unlinked lines, missing IDs or repeated totals. Source reference records are not transaction facts.\n\n## Privacy\nStaging and mart tables can contain sensitive customer data. Do not publish or commit SQLite to a public repository.\n''',encoding='utf-8')
 if a.zip:
  zpath=out.parent/(out.name+'.zip')
  with zipfile.ZipFile(zpath,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as z:
   for f in sorted(out.rglob('*')):
    if f.is_file():z.write(f,f.relative_to(out.parent))
  with zipfile.ZipFile(zpath) as z:
   bad=z.testzip()
   if bad:raise RuntimeError('Corrupt ZIP member: '+bad)
  print('ZIP',zpath,round(zpath.stat().st_size/1048576,1),'MiB')
 print('DONE 14 SHOP BUSINESSDATASET',out)
if __name__=='__main__':main()
