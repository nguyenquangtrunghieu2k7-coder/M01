#!/usr/bin/env python3
"""Package approved M01 candidates into immutable, self-contained deliveries.

Only dev_008, dev_010 and dev_011. Does not modify source, approved older
shops, or candidate files. Requires passing signed-off release_gate_report.json.
"""
import argparse,datetime,hashlib,json,pathlib,shutil,sqlite3,sys,tempfile,os
SHOPS={
 '008':{'candidate':'outputs/dev008_candidate_v2_fix','sqlite':'dev_008.sqlite','qa':'candidate_report.json'},
 '010':{'candidate':'outputs/dev010_candidate_v3','sqlite':'dev_010.sqlite','qa':'qa_report.json'},
 '011':{'candidate':'outputs/dev011_candidate_v1','sqlite':'dev_011.sqlite','qa':'qa_report.json'}
}
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def jsonfile(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')
def package(root,destination,shop):
 cfg=SHOPS[shop];src=root/cfg['candidate'];target=destination/('dev_'+shop+'_release')
 if target.exists():raise RuntimeError('Refusing to overwrite already published release: '+str(target))
 source_db=src/cfg['sqlite']
 paths=[source_db,src/'manifest.json',src/'release_gate_report.json',src/cfg['qa'],src/'financial_qa_report.json']
 if shop=='010':paths.append(src/'schema_contract.json')
 for path in paths:
  if not path.is_file():raise RuntimeError('Missing evidence: '+str(path))
 candidate=jsonfile(src/'manifest.json');gate=jsonfile(src/'release_gate_report.json')
 financial=jsonfile(src/'financial_qa_report.json')
 if gate.get('approval')!='PRODUCTION_APPROVED' or gate.get('gate_pass') is not True or gate.get('failed_checks')!=[]:
  raise RuntimeError('Release gate is NOT approved for dev_'+shop)
 if not gate.get('kpi_contract'):raise RuntimeError('Approved KPI contract missing for dev_'+shop)
 if candidate.get('approval')!='CANDIDATE_NOT_APPROVED':raise RuntimeError('Unexpected candidate state')
 if sha(source_db)!=candidate.get('sqlite_sha256') or sha(source_db)!=gate.get('sqlite_sha256'):
  raise RuntimeError('SQLite SHA mismatch for dev_'+shop)
 if shop=='010':
  if financial.get('exact_source_to_mart_pass') is not True or financial.get('financial_semantics_approved') is not True:raise RuntimeError('Financial QA failed')
 else:
  if financial.get('source_to_mart_pass') is not True:raise RuntimeError('Source parity failed')
  if shop=='008' and financial.get('financial_equation_pass') is not True:raise RuntimeError('Financial equations failed')
 for k,info in gate.get('checks',{}).items():
  if not isinstance(info,dict) or info.get('pass') is not True:raise RuntimeError('Gate evidence failed: '+k)
 # Validate source references are complete and tied to the approved gate.
 candidate_source_hashes=candidate.get('source_sha256')
 gate_source_hashes=gate.get('source_sha256')
 # dev_011 records its single XLSX source SHA as a string in both the
 # candidate and approved gate; dev_008/dev_010 use file-to-SHA mappings.
 if gate_source_hashes!=candidate_source_hashes:
  raise RuntimeError('Source SHA mismatch gate vs candidate for dev_'+shop)
 source_hashes=({'SoBanHang.xlsx':candidate_source_hashes}
                if shop=='011' else candidate_source_hashes)
 if not isinstance(source_hashes,dict) or not source_hashes:
  raise RuntimeError('Invalid source manifest for dev_'+shop)
 con=sqlite3.connect('file:'+str(source_db.resolve())+'?mode=ro',uri=True)
 try:
  if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('SQLite corrupt')
  if con.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Broken foreign keys')
  tables={row[0]:[{'name':col[1],'type':col[2],'not_null':bool(col[3]),'primary_key':bool(col[5])} for col in con.execute('PRAGMA table_info("'+row[0]+'")')] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
 finally:con.close()
 destination.mkdir(parents=True,exist_ok=True)
 tmp=pathlib.Path(tempfile.mkdtemp(prefix='.dev_'+shop+'_release_',dir=destination))
 try:
  shutil.copy2(source_db,tmp/cfg['sqlite'])
  shutil.copy2(src/cfg['qa'],tmp/'qa_report.json')
  shutil.copy2(src/'financial_qa_report.json',tmp/'financial_qa_report.json')
  shutil.copy2(src/'release_gate_report.json',tmp/'release_gate_report.json')
  contract={'shop':'dev_'+shop,'version':gate.get('version'),'approval':'PRODUCTION_APPROVED','sqlite_file':cfg['sqlite'],'tables':tables,'kpi_contract':gate['kpi_contract'],'unsupported':gate.get('unsupported',[]),'status_semantics':gate.get('excluded_from_completed_revenue',gate.get('excluded_from_revenue',[])),'candidate_origin':cfg['candidate']}
  write(tmp/'schema_contract.json',contract)
  files={p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(tmp.iterdir()) if p.is_file()}
  manifest={'shop':'dev_'+shop,'version':gate.get('version'),'approval':'PRODUCTION_APPROVED','gate_pass':True,'source_sha256':source_hashes,'source_candidate_manifest_sha256':sha(src/'manifest.json'),'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':files,'kpis_supported':list(gate['kpi_contract']),'production_sqlite':cfg['sqlite'],'immutable':True}
  write(tmp/'manifest.json',manifest)
  # Verify every artifact included and its hash prior to publishing directory.
  for name,expected in files.items():
   if sha(tmp/name)!=expected['sha256']:raise RuntimeError('Output hash mismatch: '+name)
  os.rename(tmp,target)
 except BaseException:
  shutil.rmtree(tmp,ignore_errors=True);raise
 return {'shop':'dev_'+shop,'release_dir':str(target),'approval':'PRODUCTION_APPROVED','kpis':list(gate['kpi_contract']),'files':list(files)+['manifest.json']}
def main():
 p=argparse.ArgumentParser()
 p.add_argument('--repo',default='.')
 p.add_argument('--output',default='outputs/production_releases_20261110')
 p.add_argument('--shops',nargs='+',choices=sorted(SHOPS),default=['008','010','011'])
 a=p.parse_args();root=pathlib.Path(a.repo).resolve();dest=pathlib.Path(a.output).resolve()
 results=[]
 for shop in a.shops:results.append(package(root,dest,shop))
 print(json.dumps({'packaging':'PASS','releases':results},ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except Exception as exc:
  print(json.dumps({'packaging':'FAILED','error':str(exc)},ensure_ascii=False,indent=2),file=sys.stderr)
  sys.exit(1)
