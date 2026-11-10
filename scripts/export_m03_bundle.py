"""Export an auditable, fail-closed M03 integration bundle from M01 SQLite outputs."""
import argparse
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ENTITIES = ['orders','order_lines','order_adjustments','products','customers','entity_aliases','unit_conversions','payments','purchase_receipts','purchase_lines','returns','inventory_events','inventory_snapshots','lots','lot_allocations','price_history','expenses','deliveries','service_visits','visit_tasks','trade_ins','installment_schedules','warranty_visits']

def inspect(db, config):
    with sqlite3.connect(f'file:{db.resolve()}?mode=ro', uri=True) as c:
        c.row_factory = sqlite3.Row
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'business_catalog' not in tables:
            raise ValueError(f'{db}: business_catalog missing')
        catalogs = [json.loads(r[0]) for r in c.execute('SELECT catalog_json FROM business_catalog')]
        if len(catalogs) != 1:
            raise ValueError(f'{db}: expected exactly one catalog, got {len(catalogs)}')
        cat = catalogs[0]
        if cat['shop_id'] != config['shop_id']:
            raise ValueError(f'{db}: shop mismatch')
        missing = [t for t in ['dataset_versions','raw_sources','staging_rows','source_lineage','validation_issues'] if t not in tables]
        if missing: raise ValueError(f'{db}: missing required tables {missing}')
        physical = {t: int(c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in ENTITIES if t in tables}
        differences = {t: {'catalog': cat.get('row_counts',{}).get(t,0), 'actual': n} for t,n in physical.items() if cat.get('row_counts',{}).get(t,0) != n}
        issues = [dict(r) for r in c.execute('SELECT code,severity,COUNT(*) AS count FROM validation_issues GROUP BY code,severity ORDER BY code,severity')]
        dates = {}
        for t in physical:
            a,b = c.execute(f'SELECT MIN(event_date),MAX(event_date) FROM "{t}" WHERE event_date IS NOT NULL').fetchone()
            if a is not None: dates[t] = {'min':a,'max':b}
        sources = [dict(r) for r in c.execute('SELECT source_path,source_object,source_format,source_sha256,header_row FROM raw_sources ORDER BY source_path,source_object')]
        version = c.execute('SELECT version_id,status,contract_version FROM dataset_versions WHERE shop_id=?',(cat['shop_id'],)).fetchall()
        if len(version)!=1 or version[0]['version_id'] != cat['version_id'] or version[0]['status'] != cat['validation_status']:
            raise ValueError(f'{db}: inconsistent version')
        cols = {t:[dict(r) for r in c.execute(f'PRAGMA table_info("{t}")')] for t in sorted(tables) if not t.startswith('sqlite_')}
        audit = {t:int(c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) for t in ['raw_sources','staging_rows','source_lineage','validation_issues']}
    return {'shop_id':cat['shop_id'],'catalog':cat,'source_manifest':sources,'actual_mart_counts':physical,'catalog_count_mismatches':differences,'issue_breakdown':issues,'date_ranges_observed':dates,'audit_counts':audit,'columns':cols,'database_file':db.name,'config_source_count':len(config['sources']),'observed_source_count':len(sources),'status':'BLOCKED_NO_MAPPING' if not config['sources'] else cat['validation_status']}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db-dir',required=True,type=Path)
    p.add_argument('--config-dir',default='configs/m01',type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--include-databases',action='store_true',help='Copy derived SQLite into bundle (only with data-owner permission)')
    a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    configs=sorted(a.config_dir.glob('dev_*.json'))
    if len(configs)!=14: raise SystemExit(f'Expected 14 shop configs, found {len(configs)}')
    results=[]
    for cp in configs:
        config=json.loads(cp.read_text(encoding='utf-8'))
        db=a.db_dir/(cp.stem+'.sqlite')
        if not db.is_file():raise SystemExit(f'Missing {db}')
        item=inspect(db,config)
        item['config_approval_status']=config.get('approval_status')
        item['mapping_source_count']=len(config['sources'])
        item['m03_eligible']=bool(config.get('approval_status')=='APPROVED' and item['catalog'].get('approval_status') in ('APPROVED','PRODUCTION_APPROVED') and item['catalog']['validation_status']=='APPROVED' and not item['issue_breakdown'] and not item['catalog_count_mismatches'] and item['observed_source_count']==item['config_source_count'])
        results.append(item)
        (a.output/f"{cp.stem}_catalog.json").write_text(json.dumps(item['catalog'],ensure_ascii=False,indent=2),encoding='utf-8')
        (a.output/f"{cp.stem}_metadata.json").write_text(json.dumps({k:v for k,v in item.items() if k not in ('catalog','columns')},ensure_ascii=False,indent=2),encoding='utf-8')
        if a.include_databases:
            import shutil
            shutil.copy2(db,a.output/db.name)
    rows=[]
    for r in results:
        rows.append({'shop_id':r['shop_id'],'status':r['status'],'approval':r['config_approval_status'],'sources_configured':r['config_source_count'],'sources_processed':r['observed_source_count'],'mart_rows':sum(r['actual_mart_counts'].values()),'orders':r['actual_mart_counts'].get('orders',0),'issues':r['audit_counts']['validation_issues'],'catalog_count_mismatches':len(r['catalog_count_mismatches']),'m03_eligible':r['m03_eligible']})
    with (a.output/'shop_coverage.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    contract={'contract_version':'0.2.0','interface':'M01 SQLite BusinessDataset + BusinessCatalog','table_columns_by_shop':{r['shop_id']:r['columns'] for r in results},'capabilities_by_shop':{r['shop_id']:r['catalog'].get('capabilities',{}) for r in results},'m03_policy':'Fail closed: only m03_eligible true can feed official KPIs; provisional may be used in explicitly labeled sandbox QA.'}
    (a.output/'schema_contract.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'shop_count':len(results),'approved_shop_count':sum(r['m03_eligible'] for r in results),'database_location':'external; not bundled unless explicitly requested','shops':rows,'source_sha256_by_shop':{r['shop_id']:r['source_manifest'] for r in results}}
    (a.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    summary=['# M01 → M03 Consumer Acceptance','',f"Shops inspected: {len(results)}/14",f"M03 official-KPI eligible: {sum(r['m03_eligible'] for r in results)}/14",'','## Blockers','']
    for r in results:
        blockers=[]
        if not r['mapping_source_count']:blockers.append('no active source mapping')
        if r['config_approval_status']!='APPROVED':blockers.append('mapping not approved')
        if r['catalog_count_mismatches']:blockers.append('catalog/DB count mismatch')
        if r['issue_breakdown']:blockers.append('unresolved validation issues')
        if r['catalog'].get('approval_status') not in ('APPROVED','PRODUCTION_APPROVED'):blockers.append('catalog not approved')
        if r['observed_source_count']!=r['config_source_count']:blockers.append('source coverage mismatch')
        if blockers:summary.append(f"- {r['shop_id']}: {', '.join(blockers)}")
    summary+=['','## Required for M03','- Read manifest.json and schema_contract.json first.','- Treat unsupported tables and capabilities as unknown, not zero.','- Query database files only when present and approved for intended use.','- Preserve shop_id and version_id in every downstream result.','- Never interpret PROVISIONAL_NOT_FOR_PRODUCTION as approved.','- Database and raw data remain local; metadata may still contain sensitive source paths and must be reviewed before sharing.']
    (a.output/'M03_ACCEPTANCE.md').write_text('\n'.join(summary)+'\n',encoding='utf-8')
    print(json.dumps({'shops':len(results),'m03_eligible':sum(r['m03_eligible'] for r in results),'output':str(a.output)},indent=2))

if __name__=='__main__':main()
