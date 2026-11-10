#!/usr/bin/env python3
"""Build and audit 13 shop-family *candidates*, never publish KPI approval.

Read each physical source exactly once, classify using shop-specific manifests,
preserve unsupported roles as source-only records, and verify structure,
catalog claims and lineage. Does not mutate dev_006 or earlier releases.
"""
import argparse,json,sqlite3,subprocess,sys
from pathlib import Path

try:
    from family_inventory import FAMILIES
except ImportError:
    from scripts.family_inventory import FAMILIES

REQUIRED=('dataset_versions','business_catalog','raw_sources','staging_rows',
          'source_lineage','validation_issues','source_reference_records','family_native_records')
MARTS=('orders','order_lines','order_adjustments','products','customers',
       'payments','purchase_receipts','purchase_lines','returns','inventory_events',
       'inventory_snapshots','unit_conversions','price_history','expenses','deliveries',
       'service_visits','installment_schedules','trade_ins','warranty_visits')
def inspect(path,contract):
    shop=contract['shop_id']
    failures=[]
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro',uri=True) as c:
        integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity!='ok':failures.append('sqlite integrity: '+str(integrity))
        tables={t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in REQUIRED:
            if t not in tables:failures.append('missing table: '+t)
        if failures:return {'shop_id':shop,'structural_pass':False,'failures':failures}
        data=[json.loads(x[0]) for x in c.execute('SELECT catalog_json FROM business_catalog')]
        if len(data)!=1:return {'shop_id':shop,'structural_pass':False,'failures':['one catalog required']}
        cat=data[0]
        if cat['shop_id']!=shop:failures.append('wrong catalog shop')
        if cat.get('family')!=contract['family']:failures.append('family mismatch')
        if cat.get('validation_status')!='PROVISIONAL_NOT_FOR_PRODUCTION':failures.append('invalid candidate status')
        if cat.get('approval_status')!='CANDIDATE_NOT_APPROVED':failures.append('unexpected production approval')
        if cat.get('official_kpis_approved')!=[]:failures.append('unauthorized KPI approval')
        expected={(Path(s['path']).name,s['object']) for s in contract['source_manifest']}
        physical={(Path(x[0]).name,x[1]) for x in c.execute('SELECT source_path,source_object FROM raw_sources')}
        missing=expected-physical;extra=physical-expected
        if missing:failures.append('missing physical sources: '+str(sorted(missing)))
        if extra:failures.append('unconfigured physical sources: '+str(sorted(extra)))
        if cat.get('unmapped_objects'):failures.append('unmapped source objects')
        if cat.get('source_objects_processed')!=len(expected):failures.append('source object count mismatch')
        src_count=c.execute('SELECT COUNT(*) FROM raw_sources').fetchone()[0]
        staged=c.execute('SELECT COUNT(*) FROM staging_rows').fetchone()[0]
        references=c.execute('SELECT COUNT(*) FROM source_reference_records').fetchone()[0]
        lineage=c.execute('SELECT COUNT(*) FROM source_lineage').fetchone()[0]
        native=c.execute('SELECT COUNT(*) FROM family_native_records').fetchone()[0]
        orphan=c.execute("""SELECT COUNT(*) FROM staging_rows s
            LEFT JOIN raw_sources r ON s.source_id=r.source_id WHERE r.source_id IS NULL""").fetchone()[0]
        if orphan:failures.append('orphan staging rows: '+str(orphan))
        dangling=c.execute("""SELECT COUNT(*) FROM source_reference_records r
            LEFT JOIN staging_rows s ON r.source_id=s.source_id
            AND r.source_row=s.source_row WHERE s.staging_uid IS NULL""").fetchone()[0]
        if dangling:failures.append('reference rows without staging: '+str(dangling))
        orphan_native=c.execute('''SELECT COUNT(*) FROM family_native_records f
          LEFT JOIN staging_rows s ON f.source_id=s.source_id AND f.source_row=s.source_row
          WHERE s.staging_uid IS NULL''').fetchone()[0]
        if orphan_native:failures.append('family native rows without staging: '+str(orphan_native))
        if sum(cat.get('family_native_counts',{}).values())!=native:
            failures.append('family native role count mismatch')
        source_roles={(Path(x['path']).name,x['object']):x['candidate_role']
                      for x in contract['source_manifest']}
        for src_path,obj,role in c.execute('''SELECT s.source_path,f.source_object,f.family_role
           FROM family_native_records f JOIN raw_sources s ON f.source_id=s.source_id
           GROUP BY s.source_path,f.source_object,f.family_role'''):
            if source_roles.get((Path(src_path).name,obj))!=role:
                failures.append('family native role mismatch: '+obj)
        bad_lineage=c.execute("""SELECT COUNT(*) FROM source_lineage l
            LEFT JOIN staging_rows s ON l.source_id=s.source_id
            AND l.source_row=s.source_row WHERE s.staging_uid IS NULL""").fetchone()[0]
        if bad_lineage:failures.append('lineage without staging: '+str(bad_lineage))
        actual={}
        for table in MARTS:
            if table in tables:
                n=c.execute('SELECT COUNT(*) FROM "'+table+'" WHERE shop_id=?',(shop,)).fetchone()[0]
                actual[table]=n
                if n!=cat.get('row_counts',{}).get(table,0):
                    failures.append(table+' catalog count mismatch')
        if shop=='dev_009' and any(actual.get(k,0)>0 for k in ('order_lines','products')):
            failures.append('invented invoice lines/products from summary-only CSV')
        if shop=='dev_012' and any(actual.get(k,0)>0 for k in ('orders','order_lines')):
            failures.append('invented sale from repair-visit ledger')
        validation_count=c.execute('SELECT COUNT(*) FROM validation_issues').fetchone()[0]
        version=c.execute('SELECT status FROM dataset_versions WHERE shop_id=?',(shop,)).fetchone()
        if version is None or version[0]!='PROVISIONAL_NOT_FOR_PRODUCTION':
            failures.append('dataset version approval mismatch')
        return {'shop_id':shop,'family':contract['family'],'source_objects':src_count,
                'expected_source_objects':len(expected),'staging_rows':staged,
                'source_reference_records':references,'family_native_records':native,'family_native_role_counts':cat.get('family_native_counts',{}),'source_lineage':lineage,
                'mart_row_counts':actual,'validation_issues':validation_count,
                'issue_summary':cat.get('issue_counts',{}),'unmapped_objects':cat.get('unmapped_objects',[]),
                'structural_pass':not failures,'failures':failures,
                'semantic_reconciliation_pass':False,'production_approved':False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data-root',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    if a.output.exists():raise SystemExit('Output already exists; refuse overwrite: '+str(a.output))
    a.output.mkdir(parents=True)
    cf=a.output/'family_contracts'
    subprocess.run([sys.executable,str(root/'scripts/family_inventory.py'),
       '--data-root',str(a.data_root),'--output',str(a.output),'--write-contracts'],
        check=True)
    shops=list(FAMILIES)
    results=[]
    for shop in shops:
        log=a.output/(shop+'.build.log')
        args=[sys.executable,str(root/'build_9_shops.py'),
              '--data-root',str(a.data_root),
              '--output',str(a.output),
              '--family-config-dir',str(cf),'--shops',shop]
        with log.open('w',encoding='utf-8') as stream:
            result=subprocess.run(args,stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:
            print(f'BUILD FAILED {shop}: {log}',file=sys.stderr)
            raise SystemExit(2)
        contract=json.loads((cf/(shop+'.json')).read_text(encoding='utf-8'))
        report=inspect(a.output/(shop+'.sqlite'),contract)
        results.append(report)
        print(shop,'sources',report.get('source_objects'),
              'staged',report.get('staging_rows'),
              'reference',report.get('source_reference_records'),
              'QA',report['structural_pass'],flush=True)
    report={'shop_count':len(results),'source_object_count':sum(x['source_objects'] for x in results),
        'structural_pass_count':sum(x['structural_pass'] for x in results),
        'family_candidate_ready':all(x['structural_pass'] for x in results) and len(results)==13,
        'production_approved':False,'shops':results}
    (a.output/'rollout_13_report.json').write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='shops'},ensure_ascii=False))
    if not report['family_candidate_ready']:raise SystemExit(2)

if __name__=='__main__':main()
