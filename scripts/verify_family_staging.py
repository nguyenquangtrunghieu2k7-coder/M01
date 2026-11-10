#!/usr/bin/env python3
"""Independent physical source-to-family staging QA (no official KPI approval).

Reopens each source object and verifies every nonblank source row's location,
exact JSON cell representation, hash and family role against staged SQLite.
"""
import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

try:
    from .build_family_staging import hash_file,source_iter
except ImportError:
    from build_family_staging import hash_file,source_iter

def verify(db_path,root):
    issues=[]
    summary={'db':db_path.name,'source_objects':0,
             'source_nonblank_rows':0,'staged_rows':0,
             'source_blank_rows':0,'problems':issues,
             'source_to_staging_pass':False,'production_approved':False}
    with sqlite3.connect(f'file:{db_path.resolve()}?mode=ro',uri=True) as db:
        shops=db.execute('SELECT shop_id,family,version_id,status FROM dataset_versions').fetchall()
        if len(shops)!=1:
            raise ValueError('Exactly one shop and dataset version required')
        shop,family,version,status=shops[0]
        summary.update({'shop_id':shop,'family':family,'version_id':version})
        if status!='PROVISIONAL_NOT_FOR_PRODUCTION':
            issues.append('Version must remain provisional')
        cat_rows=db.execute('SELECT catalog_json FROM business_catalog').fetchall()
        if len(cat_rows)!=1:
            issues.append('Expected one business catalog')
            catalog={}
        else:
            catalog=json.loads(cat_rows[0][0])
        if catalog.get('approval_status')!='CANDIDATE_NOT_APPROVED':
            issues.append('Catalog must not approve KPI')
        if catalog.get('official_kpis_approved'):
            issues.append('Official KPIs must remain empty')
        try:
            from scripts.m03_consumer import open_business_dataset,NotApprovedForKPI
        except ImportError:
            from m03_consumer import open_business_dataset,NotApprovedForKPI
        try:
            connection,_=open_business_dataset(db_path)
        except NotApprovedForKPI:
            pass
        else:
            connection.close()
            issues.append('Production M03 reader unexpectedly allowed provisional DB')
        sources=db.execute("""SELECT source_id,source_path,source_object,source_format,
            source_role,source_sha256,physical_row_count,staged_nonblank_rows,blank_rows
            FROM source_objects ORDER BY source_path,source_object""").fetchall()
        summary['source_objects']=len(sources)
        for source_id,source_path,obj,fmt,role,sha,physical,staged,blanks in sources:
            path=root/source_path
            if not path.is_file():
                issues.append(f'{source_path} absent');continue
            if hash_file(path)!=sha:
                issues.append(f'{source_path} SHA256 mismatch')
                continue
            count=0;nonblank=0;empty=0
            cursor=db.execute("""SELECT source_row,raw_values_json,record_sha256,source_role
                FROM family_staging_rows WHERE source_id=? ORDER BY source_row""",(source_id,))
            stored=iter(cursor)
            next_record=next(stored,None)
            for rownum,values in source_iter(path,obj,fmt):
                count+=1
                if not any(v is not None and str(v).strip() for v in values):
                    empty+=1;continue
                nonblank+=1
                raw=json.dumps(values,ensure_ascii=False,default=str)
                rowhash=hashlib.sha256(raw.encode('utf-8')).hexdigest()
                if (next_record is None or next_record[0]!=rownum or
                    next_record[1]!=raw or next_record[2]!=rowhash or next_record[3]!=role):
                    if len(issues)<100:
                        issues.append(f'{source_path}::{obj} source row {rownum} failed byte-consistent staging check')
                next_record=next(stored,None)
            if next_record is not None:
                issues.append(f'{source_path}::{obj} has extra staged rows')
            if (physical,staged,blanks)!=(count,nonblank,empty):
                issues.append(f'{source_path}::{obj} declared physical/staged/empty counts do not match')
            summary['source_nonblank_rows']+=nonblank
            summary['source_blank_rows']+=empty
            summary['staged_rows']+=staged
        sql_count=db.execute('SELECT COUNT(*) FROM family_staging_rows').fetchone()[0]
        if sql_count!=summary['staged_rows'] or sql_count!=summary['source_nonblank_rows']:
            issues.append('Cross-source staged total count differs')
        if catalog.get('nonblank_staged_rows')!=sql_count:
            issues.append('Catalog staged count mismatch')
        if catalog.get('source_objects_processed')!=len(sources):
            issues.append('Catalog source-object count mismatch')
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            issues.append('SQLite integrity check failed')
    summary['failure_count']=len(issues)
    summary['source_to_staging_pass']=len(issues)==0 and len(sources)>0
    return summary

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--db-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    reports=[]
    for path in sorted(a.db_dir.glob('dev_*.sqlite')):
        report=verify(path,a.data_root)
        reports.append(report)
        print(f"{report.get('shop_id')}: source-to-staging "
              f"{'PASS' if report['source_to_staging_pass'] else 'FAIL'}; "
              f"rows={report['source_nonblank_rows']}; problems={report['failure_count']}",flush=True)
    result={'shops':len(reports),'accepted_staging_shops':sum(x['source_to_staging_pass'] for x in reports),
            'source_objects':sum(x['source_objects'] for x in reports),
            'staged_rows':sum(x['staged_rows'] for x in reports),
            'source_to_staging_pass':bool(reports) and all(x['source_to_staging_pass'] for x in reports),
            'production_approved':False,'reports':reports}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not result['source_to_staging_pass']:raise SystemExit(2)

if __name__=='__main__':main()
