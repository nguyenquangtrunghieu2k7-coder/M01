#!/usr/bin/env python3
"""Install audited dev014 plain Python sources from the matching source bundle.

The zip contains exactly 4 readable .py scripts. Each must match its
independently tested SHA256. Refuses overwrite unless explicitly approved.
Does not touch prior shop releases or input data.
"""
import argparse,hashlib,pathlib,zipfile,sys
EXPECTED={
 "dev014_common.py":"a1e498a00a77d455775671e48d41084a3f1d5ebddee0d03e5fe36ac31aba8192",
 "dev014_pipeline.py":"db0e07f53b73000d446ae849da384f812be415fbfec715e7902f12b6764f5a74",
 "dev014_financial_qa.py":"42c81bf7a3c952789c0cbc2ed8770660cd686193abd3697d82cfaf9cf939767f",
 "dev014_release.py":"2fafc429ac5d1240e23083b0a992c4094ff48ee1b7607595c0192b2afac701ce",
}
ZIP_SHA="55ecfe69242300961045ba936484b76047a1630b231c0104367cf1e86b75b334"
def main():
 p=argparse.ArgumentParser()
 p.add_argument('--zip',required=True,help='Downloaded dev014_scripts.zip')
 p.add_argument('--dest',default='scripts',help='Local scripts directory')
 a=p.parse_args();src=pathlib.Path(a.zip);dest=pathlib.Path(a.dest)
 if hashlib.sha256(src.read_bytes()).hexdigest()!=ZIP_SHA:raise SystemExit('FAILED: source ZIP SHA256 mismatch')
 with zipfile.ZipFile(src) as z:
  expected={'scripts/'+name for name in EXPECTED}
  if set(z.namelist())!=expected:raise SystemExit('FAILED: unexpected file set in zip')
  contents={}
  for name,digest in EXPECTED.items():
   payload=z.read('scripts/'+name)
   if hashlib.sha256(payload).hexdigest()!=digest:raise SystemExit('FAILED source integrity: '+name)
   contents[name]=payload
 dest.mkdir(parents=True,exist_ok=True)
 for name,payload in contents.items():
  target=dest/name
  if target.exists() and target.read_bytes()!=payload:
   raise SystemExit('Refusing to overwrite different existing script: '+str(target))
 for name,payload in contents.items():
  target=dest/name
  if not target.exists():target.write_bytes(payload)
 print('DEV014_SOURCES_VERIFIED 4/4; installed to '+str(dest.resolve()))
if __name__=='__main__':main()
