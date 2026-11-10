#!/usr/bin/env python3
"""Audit M01's 14 existing production releases and optionally consolidate them.

Read-only by default; --publish copies only verified releases into a *new*
folder. Never rewrites the SQLite files, original manifests, QA evidence,
existing release dirs or the 13+1 shop adapters. Legacy release contracts
remain legacy; no fabricated financial QA / schema_contract documents.

Usage:
  python3 scripts/audit_m01_delivery.py
  python3 scripts/audit_m01_delivery.py --publish
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

SHOP_IDS=tuple(f"{n:03d}" for n in range(1,15))
NEW={"002","003","004","005","007","008","010","011","013","014"}
PATHS={
 **{s:Path(f"outputs/production_releases_20261110/dev_{s}_release") for s in NEW},
 "001":Path("outputs/semantic13_20261110_191132/dev_001_release"),
 "009":Path("outputs/semantic13_20261110_191132/dev_009_release"),
 "012":Path("outputs/semantic13_20261110_191132/dev_012_release"),
 "006":Path("outputs/dev006_rulebook_20261110_161422/release"),
}
NEW_FILES={"manifest.json","qa_report.json","financial_qa_report.json",
           "release_gate_report.json","schema_contract.json"}
LEGACY_REQUIRED={"manifest.json","qa_report.json"}
LEGACY_KEYS=("approval_status","approval")
APPROVAL_VALUES={"PRODUCTION_APPROVED"}
DEST=Path("outputs/m01_delivery_14shops_20261110")
def sha(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
 return h.hexdigest()
def read_json(path):
 with path.open(encoding="utf-8") as f:return json.load(f)
def audit(shop,folder):
 errors=[];warnings=[];details={"shop":"dev_"+shop,"source":str(folder)}
 def bad(message):errors.append(message)
 if not folder.is_dir():
  bad("RELEASE_DIRECTORY_MISSING")
  return dict(details,passed=False,errors=errors,warnings=warnings)
 sqlite_file=folder/("dev_"+shop+".sqlite")
 if not sqlite_file.is_file():bad("SQLITE_MISSING")
 manifest_path=folder/"manifest.json"
 if not manifest_path.is_file():bad("MANIFEST_MISSING")
 manifest={}
 if manifest_path.is_file():
  try:manifest=read_json(manifest_path)
  except (OSError,ValueError) as e:bad("INVALID_MANIFEST:"+str(e))
 if manifest:
  mid=manifest.get("shop") or manifest.get("shop_id")
  if mid is not None and mid!="dev_"+shop:bad("MANIFEST_SHOP_MISMATCH:"+str(mid))
  approval=manifest.get("approval") or manifest.get("approval_status")
  if approval not in APPROVAL_VALUES:bad("MANIFEST_NOT_APPROVED:"+repr(approval))
  if manifest.get("gate_pass") is False:bad("MANIFEST_GATE_FALSE")
  supported=manifest.get("kpis_supported",manifest.get("approved_metrics"))
  if not isinstance(supported,list) or not supported:
   warnings.append("NO_KPI_LIST_IN_MANIFEST")
  details["kpis"]=supported
 if sqlite_file.is_file():
  try:
   con=sqlite3.connect("file:"+str(sqlite_file.resolve())+"?mode=ro",uri=True)
   integrity=con.execute("PRAGMA integrity_check").fetchone()[0]
   fk=con.execute("PRAGMA foreign_key_check").fetchall()
   tables=[x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
   if integrity!="ok":bad("SQLITE_INTEGRITY:"+str(integrity))
   if fk:bad("SQLITE_FOREIGN_KEYS:"+str(len(fk)))
   if not tables:bad("SQLITE_EMPTY_SCHEMA")
   details.update(sqlite_integrity=integrity,foreign_key_violations=len(fk),table_count=len(tables))
   con.close()
  except (sqlite3.Error,OSError) as e:bad("SQLITE_ERROR:"+str(e))
  details["sqlite_sha256"]=sha(sqlite_file)
 expected=NEW_FILES | {sqlite_file.name} if shop in NEW else LEGACY_REQUIRED | {sqlite_file.name}
 actual={p.name for p in folder.iterdir() if p.is_file()}
 missing=expected-actual
 if missing:bad("REQUIRED_FILES_MISSING:"+",".join(sorted(missing)))
 details["files"]=sorted(actual)
 if shop in NEW:
  gatepath=folder/"release_gate_report.json"
  if gatepath.is_file():
   try:
    gate=read_json(gatepath)
    if gate.get("approval")!="PRODUCTION_APPROVED" or gate.get("gate_pass") is not True or gate.get("failed_checks")!=[]:bad("RELEASE_GATE_NOT_PASS")
    if gate.get("sqlite_sha256") and sqlite_file.is_file() and gate["sqlite_sha256"]!=sha(sqlite_file):bad("RELEASE_GATE_SQLITE_HASH_MISMATCH")
   except (ValueError,OSError) as e:bad("INVALID_GATE_REPORT:"+str(e))
  for fname in ["qa_report.json","financial_qa_report.json","schema_contract.json"]:
   p=folder/fname
   if p.is_file():
    try:read_json(p)
    except (ValueError,OSError) as e:bad("INVALID_JSON:"+fname+":"+str(e))
  if manifest:
   declared=manifest.get("files")
   if not isinstance(declared,dict):bad("NEW_MANIFEST_MISSING_HASHES")
   else:
    for fname,info in declared.items():
     fp=folder/fname
     if not fp.is_file():bad("MANIFEST_FILE_MISSING:"+fname);continue
     if not isinstance(info,dict) or not isinstance(info.get("sha256"),str):bad("MANIFEST_HASH_MISSING:"+fname);continue
     if sha(fp)!=info["sha256"]:bad("MANIFEST_HASH_MISMATCH:"+fname)
     if isinstance(info.get("bytes"),int) and fp.stat().st_size!=info["bytes"]:bad("MANIFEST_SIZE_MISMATCH:"+fname)
    if set(declared)!=(expected-{"manifest.json"}):
     bad("MANIFEST_FILE_SET_MISMATCH:"+repr(sorted(set(declared))))
 else:
  qa=folder/"qa_report.json"
  if qa.is_file():
   try:
    q=read_json(qa)
    if isinstance(q,dict) and (q.get("error_count",0)!=0 or q.get("errors")):
     bad("LEGACY_QA_HAS_ERRORS")
    if isinstance(q,dict) and (q.get("passed") is False or q.get("qa_pass") is False):
     bad("LEGACY_QA_FAILED")
   except (ValueError,OSError) as e:bad("INVALID_LEGACY_QA:"+str(e))
  if shop=="006":
   warnings.append("DEV006_LEGACY_RELEASE: confirm semantic approval explicitly in manifest; do not substitute other candidate DB")
  if manifest and isinstance(manifest.get("files"),list):
   for fname in manifest["files"]:
    if not (folder/fname).is_file():bad("LEGACY_MANIFEST_REFERENCES_MISSING:"+str(fname))
  # A legacy manifest may not embed a hash for each artifact. Preserve it unchanged.
  warnings.append("LEGACY_FORMAT: no new schema or QA artifacts fabricated")
 return dict(details,format="new_6_artifacts" if shop in NEW else "legacy_release",
             passed=not errors,errors=errors,warnings=warnings)
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--publish",action="store_true",help="Copy a fully verified set into a single new destination")
 p.add_argument("--destination",default=str(DEST))
 a=p.parse_args()
 audited=[audit(s,PATHS[s]) for s in SHOP_IDS]
 good=sum(x["passed"] for x in audited)
 result={"audit":"M01_14_SHOP_DELIVERY","checked":len(audited),
         "passed":good,"failed":len(audited)-good,"shops":audited,
         "delivery":"NOT_PUBLISHED"}
 summary=Path("outputs/m01_delivery_audit_report.json")
 summary.parent.mkdir(parents=True,exist_ok=True)
 summary.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"passed":good,"total":len(audited),
                   "missing_or_invalid":{x["shop"]:x["errors"] for x in audited if not x["passed"]},
                   "audit_report":str(summary)},ensure_ascii=False,indent=2))
 if not a.publish:return 0 if good==14 else 1
 if good!=14:
  print("BLOCKED: refuse publishing incomplete or invalid 14-shop bundle",file=sys.stderr)
  return 1
 dest=Path(a.destination)
 if dest.exists():raise SystemExit("Refusing to overwrite existing destination: "+str(dest))
 dest.parent.mkdir(parents=True,exist_ok=True)
 temp=Path(tempfile.mkdtemp(prefix=".m01_delivery_",dir=dest.parent))
 try:
  artifact_hashes={}
  for shop in SHOP_IDS:
   old=PATHS[shop];new=temp/("dev_"+shop+"_release")
   shutil.copytree(old,new)
   artifact_hashes[shop]={f.name:sha(f) for f in new.iterdir() if f.is_file()}
  manifest={"delivery":"M01_14_SHOP_CONSOLIDATION",
            "approved_shop_count":14,"shop_ids":["dev_"+s for s in SHOP_IDS],
            "created_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
            "shop_release_sources":{s:str(PATHS[s]) for s in SHOP_IDS},
            "artifact_sha256":artifact_hashes,
            "note":"Existing production files copied byte-for-byte. Legacy release formats retained; no new approvals asserted."}
  (temp/"delivery_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
  (temp/"delivery_audit.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
  os.rename(temp,dest)
 except BaseException:
  shutil.rmtree(temp,ignore_errors=True)
  raise
 print(json.dumps({"delivery":"PUBLISHED","path":str(dest),
                   "shops":14,"files":sum(len(x) for x in artifact_hashes.values()),
                   "root_manifest":"delivery_manifest.json"},ensure_ascii=False,indent=2))
 return 0
if __name__=="__main__":sys.exit(main())
