#!/usr/bin/env python3
"""Fail-closed audit of 17/17 dev_006 POS source coverage (read-only)."""
import argparse
import json
import sqlite3
from pathlib import Path

REFERENCES = ('chi_nhanh','nha_cung_cap','nhan_vien','thong_tin_thuoc')

def verify(source_path,derived_path):
    with sqlite3.connect(f'file:{Path(source_path).resolve()}?mode=ro',uri=True) as source, \
         sqlite3.connect(f'file:{Path(derived_path).resolve()}?mode=ro',uri=True) as derived:
        cat=json.loads(derived.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
        source_objects={r[0] for r in source.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        observed={r[0] for r in derived.execute('SELECT source_object FROM raw_sources')}
        unmapped=sorted(source_objects-observed)
        extra=sorted(observed-source_objects)
        ref_counts={}
        failures=[]
        for name in REFERENCES:
            original=source.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]
            retained=derived.execute(
                'SELECT COUNT(*) FROM source_reference_records WHERE source_object=?',(name,)).fetchone()[0]
            staged=derived.execute("""
                SELECT COUNT(*) FROM staging_rows s
                JOIN raw_sources r ON r.source_id=s.source_id
                WHERE r.source_object=?""",(name,)).fetchone()[0]
            ref_counts[name]={'original':original,'staged':staged,'retained':retained}
            if (original,original)!=(staged,retained):
                failures.append(f'{name}: source/staging/reference counts differ')
        for name in source_objects:
            if name not in observed:
                failures.append(f'{name}: not imported')
        if extra:failures.append(f'unexpected raw_sources: {extra}')
        for name in REFERENCES:
            if cat.get('reference_counts',{}).get(name)!=ref_counts[name]['retained']:
                failures.append(f'{name}: catalog reference_count mismatch')
        n_issues=derived.execute('SELECT COUNT(*) FROM validation_issues').fetchone()[0]
        if n_issues:failures.append(f'{n_issues} validation issues')
        integrity=derived.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity!='ok':failures.append(f'SQLite integrity: {integrity}')
        return {'source_tables':len(source_objects),'imported_tables':len(observed),
                'unmapped_source_tables':unmapped,'reference_counts':ref_counts,
                'validation_issues':n_issues,'integrity':integrity,
                'coverage_pass':not failures,'failures':failures,
                'production_approved':False,
                'note':'Structural coverage only; financial reconciliation and official approval are separate gates.'}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pos',required=True,type=Path)
    p.add_argument('--db',required=True,type=Path)
    p.add_argument('--report',type=Path)
    args=p.parse_args()
    report=verify(args.pos,args.db)
    encoded=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    print(encoded)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(encoded,encoding='utf-8')
    if not report['coverage_pass']:raise SystemExit(2)

if __name__=='__main__':main()
