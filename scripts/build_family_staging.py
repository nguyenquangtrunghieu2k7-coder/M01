#!/usr/bin/env python3
"""Lossless, family-aware source staging for the 13 non-dev006 shops.

Every physical nonblank source row is retained at its original file/sheet/row
grain. Family/source roles are read from audited per-shop contracts, never
guessed from column names. This does NOT publish official KPI mart values.
"""
import argparse
import csv
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from family_inventory import FAMILIES, inventory

try:
    import openpyxl
except ImportError:
    raise SystemExit('Install openpyxl: python3 -m pip install openpyxl')

def hash_file(path):
    hasher=hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda:file.read(1024*1024),b''):
            hasher.update(block)
    return hasher.hexdigest()

def uid(*parts):
    return hashlib.sha256('|'.join(map(str,parts)).encode('utf-8')).hexdigest()[:32]

def csv_rows(path):
    with path.open('r',encoding='utf-8-sig',newline='') as file:
        sample=file.read(8192);file.seek(0)
        try:
            dialect=csv.Sniffer().sniff(sample,delimiters=',;\t')
        except csv.Error:
            dialect=csv.excel
        for number,row in enumerate(csv.reader(file,dialect),start=1):
            yield number,row

def xlsx_rows(path,sheet):
    wb=openpyxl.load_workbook(path,read_only=True,data_only=True)
    try:
        ws=wb[sheet]
        for number,values in enumerate(ws.values,start=1):
            yield number,list(values)
    finally:
        wb.close()

def sqlite_rows(path,table):
    with sqlite3.connect(f'file:{path.resolve()}?mode=ro',uri=True) as source:
        cols=[r[1] for r in source.execute('PRAGMA table_info("'+table.replace('"','""')+'")')]
        yield 1,cols
        # Builder numbers source row 1 as column headers, preserving each
        # physical row separately. Explicit ORDER BY rowid for rowid tables.
        quoted='"'+table.replace('"','""')+'"'
        try:
            it=source.execute(f'SELECT * FROM {quoted} ORDER BY rowid')
        except sqlite3.OperationalError:
            it=source.execute(f'SELECT * FROM {quoted}')
        for rn,values in enumerate(it,start=2):
            yield rn,list(values)

def source_iter(path,obj,fmt):
    if fmt=='csv':return csv_rows(path)
    if fmt=='xlsx':return xlsx_rows(path,obj)
    if fmt=='sqlite':return sqlite_rows(path,obj)
    raise ValueError('Unsupported format: '+str(fmt))

def create_db(path):
    db=sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=DELETE')
    db.executescript("""
    CREATE TABLE dataset_versions(
        shop_id TEXT NOT NULL,version_id TEXT PRIMARY KEY,
        family TEXT NOT NULL,contract_version TEXT NOT NULL,
        created_at_utc TEXT NOT NULL,status TEXT NOT NULL);
    CREATE TABLE source_objects(
        source_id TEXT PRIMARY KEY,shop_id TEXT NOT NULL,family TEXT NOT NULL,
        source_path TEXT NOT NULL,source_object TEXT NOT NULL,source_format TEXT NOT NULL,
        source_role TEXT NOT NULL,source_sha256 TEXT NOT NULL,
        physical_row_count INTEGER NOT NULL DEFAULT 0,
        staged_nonblank_rows INTEGER NOT NULL DEFAULT 0,
        blank_rows INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE family_staging_rows(
        staging_uid TEXT PRIMARY KEY,shop_id TEXT NOT NULL,source_id TEXT NOT NULL,
        source_row INTEGER NOT NULL,source_role TEXT NOT NULL,
        raw_values_json TEXT NOT NULL,record_sha256 TEXT NOT NULL,
        semantic_state TEXT NOT NULL DEFAULT 'RAW_ONLY',
        UNIQUE(source_id,source_row));
    CREATE INDEX idx_family_staging_source
        ON family_staging_rows(source_id,source_row);
    CREATE TABLE family_catalog(shop_id TEXT PRIMARY KEY,catalog_json TEXT NOT NULL);
    """)
    return db

def build(shop,root,contracts_dir,output_dir):
    if shop not in FAMILIES:raise ValueError('Unrecognized or excluded shop: '+shop)
    folder=root/'public_test'/'data'/shop
    if not folder.is_dir():raise FileNotFoundError(folder)
    cfg=json.loads((contracts_dir/(shop+'.json')).read_text(encoding='utf-8'))
    if cfg.get('shop_id')!=shop or cfg.get('family')!=FAMILIES[shop]:
        raise ValueError('Wrong family contract')
    if cfg.get('approval_status')!='CANDIDATE_NOT_APPROVED' or cfg.get('official_kpis_approved'):
        raise ValueError('No silent approval or KPI authorization allowed')
    sources=cfg['source_manifest']
    physical={(p.name,obj,fmt) for p,obj,fmt in inventory(folder)}
    expected={(Path(s['path']).name,s['object'],s['format']) for s in sources}
    if physical!=expected or len(expected)!=len(sources):
        raise ValueError('Physical source inventory no longer matches family contract')
    if any(s.get('candidate_role') in (None,'unclassified') for s in sources):
        raise ValueError('Unclassified role in '+shop)
    dest=output_dir/(shop+'.sqlite')
    if dest.exists():raise FileExistsError('Refusing to overwrite candidate: '+str(dest))
    dest.parent.mkdir(parents=True,exist_ok=True)
    file_hashes={}
    version=uid(shop,FAMILIES[shop],json.dumps(cfg,sort_keys=True,ensure_ascii=False))
    db=create_db(dest)
    db.execute('INSERT INTO dataset_versions VALUES(?,?,?,?,?,?)',(
        shop,version,FAMILIES[shop],cfg['contract_version'],
        datetime.now(timezone.utc).isoformat(),'PROVISIONAL_NOT_FOR_PRODUCTION'))
    all_rows=0;blank_rows=0;physical_rows=0;by_role=Counter()
    object_counts=[]
    try:
        for entry in sources:
            src_path=root/entry['path']
            if not src_path.is_file():
                raise FileNotFoundError(src_path)
            src_sha=file_hashes.setdefault(src_path,hash_file(src_path))
            src_id=uid(shop,entry['path'],entry['object'],src_sha)
            role=entry['candidate_role']
            count=0;nonblank=0;blanks=0
            db.execute("""INSERT INTO source_objects
                (source_id,shop_id,family,source_path,source_object,source_format,
                 source_role,source_sha256)
                VALUES (?,?,?,?,?,?,?,?)""",(
                src_id,shop,FAMILIES[shop],entry['path'],entry['object'],
                entry['format'],role,src_sha))
            for row_number,values in source_iter(src_path,entry['object'],entry['format']):
                count+=1
                if not any(v is not None and str(v).strip() for v in values):
                    blanks+=1
                    continue
                raw=json.dumps(values,ensure_ascii=False,default=str)
                row_hash=hashlib.sha256(raw.encode('utf-8')).hexdigest()
                db.execute("""INSERT INTO family_staging_rows
                    (staging_uid,shop_id,source_id,source_row,source_role,
                     raw_values_json,record_sha256)
                    VALUES(?,?,?,?,?,?,?)""",(
                    uid(src_id,row_number),shop,src_id,row_number,role,raw,row_hash))
                nonblank+=1
            db.execute("""UPDATE source_objects SET physical_row_count=?,
                staged_nonblank_rows=?,blank_rows=? WHERE source_id=?""",
                (count,nonblank,blanks,src_id))
            db.commit()
            all_rows+=nonblank;blank_rows+=blanks;physical_rows+=count
            by_role[role]+=nonblank
            object_counts.append({'object':entry['object'],
                                  'file':Path(entry['path']).name,'role':role,
                                  'physical_rows':count,'staged_rows':nonblank,
                                  'blank_rows':blanks})
        catalog={'shop_id':shop,'family':FAMILIES[shop],
            'version_id':version,'contract_version':cfg['contract_version'],
            'approval_status':'CANDIDATE_NOT_APPROVED',
            'validation_status':'PROVISIONAL_NOT_FOR_PRODUCTION',
            'official_kpis_approved':[],'source_objects_processed':len(sources),
            'physical_rows':physical_rows,'nonblank_staged_rows':all_rows,
            'blank_rows':blank_rows,'source_role_counts':dict(by_role),
            'business_marts_approved':[],
            'notes':'Physical-source staging only; semantic family mapping and KPI parity remain pending. Not an M03 production release.'}
        db.execute('INSERT INTO family_catalog VALUES(?,?)',(shop,json.dumps(catalog,ensure_ascii=False)))
        db.commit()
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        registered=db.execute('SELECT COUNT(*) FROM source_objects').fetchone()[0]
        staged=db.execute('SELECT COUNT(*) FROM family_staging_rows').fetchone()[0]
        verified=(integrity=='ok' and registered==len(sources) and staged==all_rows
                  and all(x['physical_rows']==x['staged_rows']+x['blank_rows'] for x in object_counts))
        return {'shop_id':shop,'family':FAMILIES[shop],
            'source_objects':len(sources),'physical_rows':physical_rows,
            'staged_nonblank_rows':all_rows,'blank_rows':blank_rows,
            'source_role_counts':dict(by_role),'staging_integrity_pass':verified,
            'sqlite_integrity':integrity,'production_approved':False,
            'candidate_sqlite':str(dest),'object_counts':object_counts}
    finally:
        db.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--contracts-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--shops',nargs='*',default=list(FAMILIES))
    a=p.parse_args()
    if len(a.shops)!=len(set(a.shops)):p.error('Duplicate shop IDs')
    a.output.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for shop in a.shops:
        result=build(shop,a.data_root,a.contracts_dir,a.output)
        manifest.append(result)
        print(f"{shop}: {result['source_objects']} sources; {result['staged_nonblank_rows']} rows; "
              f"source staging {'PASS' if result['staging_integrity_pass'] else 'FAIL'}",flush=True)
    report={'shops':len(manifest),'source_objects':sum(x['source_objects'] for x in manifest),
            'staged_rows':sum(x['staged_nonblank_rows'] for x in manifest),
            'staging_pass_count':sum(x['staging_integrity_pass'] for x in manifest),
            'production_approved':False,'shops_detail':manifest}
    (a.output/'family_stage_manifest.json').write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if report['staging_pass_count']!=len(manifest):raise SystemExit(2)

if __name__=='__main__':main()
