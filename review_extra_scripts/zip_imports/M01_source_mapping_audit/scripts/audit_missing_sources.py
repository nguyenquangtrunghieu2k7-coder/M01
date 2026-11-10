"""Offline source/adapter coverage audit; never exports row values."""
import argparse,csv,json,hashlib,zipfile
from pathlib import Path
from collections import defaultdict

def main():
 p=argparse.ArgumentParser();p.add_argument('--data-root',required=True,type=Path);p.add_argument('--config-dir',default='configs/m01',type=Path);p.add_argument('--evidence',default='docs/data_discovery/D5_adapter_design/d4_physical_column_evidence.csv',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=True)
 with a.evidence.open(encoding='utf-8-sig',newline='') as f: ev=list(csv.DictReader(f))
 grouped=defaultdict(list)
 for r in ev:grouped[(r['shop_id'],r['source_path'],r['source_object'])].append(r)
 results=[]; columns=[]
 for cp in sorted(a.config_dir.glob('dev_*.json')):
  cfg=json.loads(cp.read_text(encoding='utf-8'));shop=cfg['shop_id'];active={(s['path'],s['object']) for s in cfg.get('sources',[])}
  for (sid,rel,obj),items in sorted(grouped.items()):
   if sid!=shop:continue
   path=(a.data_root/rel).resolve()
   if not path.is_relative_to(a.data_root.resolve()): raise SystemExit('unsafe path: '+rel)
   exists=path.is_file();ext=path.suffix.lower();supported=ext in ('.csv','.xlsx')
   results.append({'shop_id':shop,'source_path':rel,'source_object':obj,'exists_local':exists,'active_mapping':(rel,obj) in active,'format':ext,'pipeline_reader_supported':supported,'column_count':len(items),'source_bytes':path.stat().st_size if exists else '', 'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest() if exists else '', 'action': 'MAPPED' if (rel,obj) in active else 'REVIEW_GRAIN_AND_FIELD_MAPPING'})
   for r in items:columns.append({'shop_id':shop,'source_path':rel,'source_object':obj,'physical_column':r.get('physical_column_observed',''),'observed_type':r.get('observed_type',''),'canonical_entity_evidence':r.get('canonical_entity',''),'canonical_field_evidence':r.get('canonical_field',''),'mapping_approval_status':r.get('mapping_approval_status','')})
 def write(name,rows,fields):
  with (a.output/name).open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 write('SOURCE_COVERAGE.csv',results,['shop_id','source_path','source_object','exists_local','active_mapping','format','pipeline_reader_supported','column_count','source_bytes','source_sha256','action'])
 write('COLUMN_MAPPING_REVIEW.csv',columns,['shop_id','source_path','source_object','physical_column','observed_type','canonical_entity_evidence','canonical_field_evidence','mapping_approval_status'])
 summary={'shops':len(list(a.config_dir.glob('dev_*.json'))),'objects_in_d4':len(results),'unmapped_objects':sum(not r['active_mapping'] for r in results),'missing_local_files':sum(not r['exists_local'] for r in results),'unsupported_format_objects':sum(not r['pipeline_reader_supported'] for r in results),'warning':'This audit exports metadata only; no raw cell values, customer records or approval decisions. Evidence is not semantic approval.'}
 (a.output/'AUDIT_SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False,indent=2));print('OUTPUT:',a.output)
if __name__=='__main__':main()
