#!/usr/bin/env python3
"""Independent dev012 motorcycle repair visit KPIs and gated SQLite release.

Rulebook §6: one repair-ledger row = one visit, warranty included in visits,
warranty cash = 0; average ticket divides by paid visits, not all visits.
Do not invent product sales, per-task prices or customer identity from notes.
"""
import argparse,datetime as dt,hashlib,json,re,shutil,sqlite3,sys
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4
from openpyxl import load_workbook
SHOP='dev_012'
APPROVED=['visit_count','service_revenue','warranty_visit_count',
          'warranty_rate','average_paid_ticket']

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()

def parse_day(value):
 if isinstance(value,(dt.datetime,dt.date)):
  return value.date().isoformat() if isinstance(value,dt.datetime) else value.isoformat()
 if isinstance(value,(int,float)) and 30000<value<90000:
  return (dt.datetime(1899,12,30)+dt.timedelta(days=value)).date().isoformat()
 s=str(value or '').strip().lower()
 for fmt in ('%d/%m/%Y','%Y-%m-%d','%Y-%m-%d %H:%M:%S'):
  try:return dt.datetime.strptime(s,fmt).date().isoformat()
  except ValueError:pass
 m=re.fullmatch(r'(\d{1,2})\s+thg\s+(\d{1,2})\s+(\d{4})',s)
 if m:return dt.date(int(m[3]),int(m[2]),int(m[1])).isoformat()
 raise ValueError('Unparseable visit date '+repr(value))

def parse_money(value):
 if isinstance(value,(int,Decimal)):return int(value)
 s=str(value or '').lower().strip().replace(' ','').replace('₫','').replace('đ','')
 m=re.fullmatch(r'(\d+)tr(\d{1,3})',s)
 if m:
  return int((Decimal(m[1]+'.'+m[2])*1000000).to_integral_exact())
 if s.endswith('tr'):
  t=s[:-2]
  if not re.fullmatch(r'\d+(?:[,.]\d+)?',t):raise ValueError('Invalid millions '+repr(value))
  amount=Decimal(t.replace(',','.'))*1000000
 elif s.endswith('k'):
  t=s[:-1]
  if not re.fullmatch(r'\d+(?:[,.]\d+)?',t):raise ValueError('Invalid thousands '+repr(value))
  amount=Decimal(t.replace(',','.'))*1000
 else:
  if not re.fullmatch(r'\d+|\d{1,3}(?:[.,]\d{3})+',s):
   raise ValueError('Invalid money '+repr(value))
  amount=Decimal(s.replace(',','').replace('.',''))
 if amount!=amount.to_integral_value():raise ValueError('Fractional VND')
 return int(amount)

def source_visits(path):
 wb=load_workbook(path,read_only=True,data_only=True)
 visits=[];note_rows=[];errors=[];observed={}
 try:
  for ws in wb:
   if ws.title.startswith('Ghi'):continue
   physical=[]
   for rn,orig in enumerate(ws.values,start=1):
    values=list(orig)
    if rn<=2 or not any(x is not None and str(x).strip() for x in values):continue
    physical.append(rn)
    d,car,task,worker,amount,note=(values+[None]*6)[:6]
    if isinstance(d,str) and d.strip().lower().startswith('ghi chú'):
     note_rows.append((ws.title,rn));continue
    try:
     day=parse_day(d)
     cash=parse_money(amount)
     is_warranty='bảo hành' in str(note or '').lower()
     if is_warranty!=(cash==0):
      raise ValueError('Warranty rule contradiction (zero payment vs note)')
     if not car or not str(car).strip():raise ValueError('Vehicle missing')
     visits.append({'sheet':ws.title,'row':rn,'date':day,'vehicle':str(car),
         'work':str(task or ''),'mechanic':str(worker or ''),
         'money_vnd':cash,'warranty':int(is_warranty)})
    except (ValueError,TypeError,ArithmeticError) as e:
     errors.append(f'{ws.title}:{rn}: {e}')
   observed[ws.title]=physical
 finally:wb.close()
 return visits,note_rows,observed,errors

def totals(visits):
 paid=[v for v in visits if not v['warranty']]
 warranty=len(visits)-len(paid)
 return {'visit_count':len(visits),'paid_visit_count':len(paid),
  'warranty_visit_count':warranty,
  'service_revenue_vnd':sum(v['money_vnd'] for v in paid),
  'warranty_rate_percent':float((Decimal(100)*warranty/len(paid)).quantize(
     Decimal('.01'),rounding=ROUND_HALF_UP)) if paid else 0.0,
  'average_paid_ticket_vnd':int((Decimal(sum(v['money_vnd'] for v in paid))/
      len(paid)).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if paid else 0}

def acceptance(source,candidate):
 source=Path(source);candidate=Path(candidate)
 visits,notes,observed,errors=source_visits(source)
 with sqlite3.connect(f'file:{candidate.resolve()}?mode=ro',uri=True) as db:
  if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':errors.append('SQLite integrity')
  catalog=json.loads(db.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
  if catalog.get('shop_id')!=SHOP or catalog.get('approval_status')!='CANDIDATE_NOT_APPROVED':
   errors.append('wrong candidate or approval state')
  if catalog.get('family')!='motorcycle_service_ledger':
   errors.append('wrong family')
  source_objs=db.execute("""SELECT source_id,source_object,source_sha256
      FROM raw_sources WHERE shop_id=? AND source_path LIKE '%SoSuaXe.xlsx'""",(SHOP,)).fetchall()
  source_ids={sheet:sid for sid,sheet,hashval in source_objs}
  if set(source_ids)!=set(observed):errors.append('repair source sheet coverage mismatch')
  for sid,sheet,hashval in source_objs:
   if hashval!=digest(source):errors.append('repair source SHA mismatch: '+sheet)
   staged={rn for (rn,) in db.execute('SELECT source_row FROM staging_rows WHERE source_id=?',(sid,))}
   if staged!=set(observed.get(sheet,[])):
    errors.append('staging physical row mismatch for '+sheet)
  native={(sheet,rn) for sheet,rn in notes}
  visit_set={(v['sheet'],v['row']) for v in visits}
  if native & visit_set:errors.append('notes overlap visits')
  actual_visits={(sheet,rn) for sid,sheet,hashval in source_objs for (rn,) in
      db.execute('SELECT source_row FROM service_visits WHERE source_id=?',(sid,))}
  if actual_visits!=native|visit_set:
   errors.append('original candidate visit mart differs from physically staged rows')
  if db.execute('SELECT COUNT(*) FROM orders WHERE shop_id=?',(SHOP,)).fetchone()[0] or db.execute(
      'SELECT COUNT(*) FROM order_lines WHERE shop_id=?',(SHOP,)).fetchone()[0]:
   errors.append('fabricated merchandise sales in repair ledger')
 return {'shop_id':SHOP,'family':'motorcycle_service_ledger','accepted':not errors,
   'repair_visits':len(visits),'sheet_notes_excluded':len(notes),'kpis':totals(visits),
   'error_count':len(errors),'errors':errors[:30],'production_approved':False}

def query_kpi(db,metric,*,start_date,end_date,as_of_date):
 cat=json.loads(db.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
 if cat.get('shop_id')!=SHOP or cat.get('approval_status')!='PRODUCTION_APPROVED' or metric not in cat.get('approved_metrics',[]):
  raise ValueError('Unapproved family KPI')
 start=dt.date.fromisoformat(start_date);end=dt.date.fromisoformat(end_date)
 cutoff=dt.date.fromisoformat(as_of_date)
 if end<start:raise ValueError('Invalid date period')
 lo,hi=db.execute('SELECT MIN(visit_date),MAX(visit_date) FROM family_service_facts').fetchone()
 if not lo or end.isoformat()<lo or start.isoformat()>hi or start>cutoff:
  raise ValueError('Unanswerable: period outside source coverage')
 last=min(end,cutoff).isoformat()
 data=db.execute('SELECT warranty,amount_vnd FROM family_service_facts WHERE visit_date BETWEEN ? AND ?',
                 (start.isoformat(),last)).fetchall()
 n=len(data);w=sum(x[0] for x in data)
 paid=n-w;revenue=sum(m for warranty,m in data if not warranty)
 if metric=='visit_count':return n
 if metric=='service_revenue':return revenue
 if metric=='warranty_visit_count':return w
 if metric=='warranty_rate':return float((Decimal(100)*w/paid).quantize(
       Decimal('.01'),rounding=ROUND_HALF_UP)) if paid else 0.0
 if metric=='average_paid_ticket':return int((Decimal(revenue)/paid).quantize(
       Decimal('1'),rounding=ROUND_HALF_UP)) if paid else 0
 raise ValueError('Unsupported metric')

def publish(source,candidate,out,approver):
 source=Path(source);candidate=Path(candidate);out=Path(out)
 if out.exists():raise ValueError('Refusing overwrite')
 qa=acceptance(source,candidate)
 if not qa['accepted']:raise ValueError('QA failed: '+repr(qa['errors'][:8]))
 visits,notes,observed,errors=source_visits(source)
 out.mkdir(parents=True,exist_ok=False)
 (out/'qa_report.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2)+'\n')
 target=out/'dev_012.sqlite';shutil.copy2(candidate,target)
 with sqlite3.connect(target) as db:
  cat=json.loads(db.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
  db.execute('''CREATE TABLE family_service_facts(
      visit_uid TEXT PRIMARY KEY,source_row INTEGER,source_object TEXT,
      visit_date TEXT NOT NULL,vehicle TEXT,work_text TEXT,mechanic TEXT,
      amount_vnd INTEGER NOT NULL,warranty INTEGER NOT NULL)''')
  db.executemany('INSERT INTO family_service_facts VALUES(?,?,?,?,?,?,?,?,?)',
       [(f"{x['sheet']}:{x['row']}",x['row'],x['sheet'],x['date'],x['vehicle'],
         x['work'],x['mechanic'],x['money_vnd'],x['warranty']) for x in visits])
  for sheet,rn in notes:
   sid=db.execute('SELECT source_id FROM raw_sources WHERE source_object=? AND shop_id=?',
                  (sheet,SHOP)).fetchone()[0]
   # Retain note text, provenance and source row in a family-native ledger.
   note_uid='dev012-note:'+sheet+':'+str(rn)
   raw=db.execute('SELECT raw_json FROM staging_rows WHERE source_id=? AND source_row=?',
                  (sid,rn)).fetchone()[0]
   db.execute('INSERT INTO family_native_records VALUES(?,?,?,?,?,?,?,?,?)',
      (note_uid,SHOP,sid,rn,sheet,'motorcycle_service_ledger','ledger_note',
       raw,cat['version_id']))
   db.execute("""UPDATE source_lineage SET entity_table='family_native_records',
       entity_uid=?,transform_id='source_ledger_note'
       WHERE shop_id=? AND source_id=? AND source_row=?
         AND entity_table='service_visits'""",(note_uid,SHOP,sid,rn))
   db.execute('UPDATE staging_rows SET parsed_json=? WHERE source_id=? AND source_row=?',
      (json.dumps({'classification':'LEDGER_NOTE_NOT_SERVICE_VISIT',
                   'count_in_kpi':False}),sid,rn))
   db.execute('DELETE FROM service_visits WHERE source_id=? AND source_row=?',(sid,rn))
  db.executemany("""UPDATE service_visits SET event_date=?,amount=?,status_raw=?
      WHERE shop_id=? AND source_id=(SELECT source_id FROM raw_sources
      WHERE source_object=? AND shop_id=?) AND source_row=?""",
      [(x['date'],str(x['money_vnd']), 'warranty' if x['warranty'] else 'paid',
        SHOP,x['sheet'],SHOP,x['row']) for x in visits])
  cat['row_counts']['service_visits']=len(visits)
  cat['family_native_counts']=dict(cat.get('family_native_counts',{}),ledger_note=len(notes))
  cat['validation_status']='APPROVED'
  cat['approval_status']='PRODUCTION_APPROVED'
  cat['approved_metrics']=APPROVED
  cat['approved_by']=approver
  cat['approved_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
  cat['approval_evidence']='qa_report.json'
  cat['metric_notes']={'service_revenue':'sum paid visits only, warranty excluded',
    'warranty_rate':'warranty visits divided by paid visits per rulebook'}
  db.execute('UPDATE business_catalog SET catalog_json=?',(json.dumps(cat,ensure_ascii=False),))
  db.execute("UPDATE dataset_versions SET status='APPROVED' WHERE shop_id=?",(SHOP,))
  db.commit()
  if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
   raise ValueError('release sqlite integrity failed')
  first,last=db.execute('SELECT MIN(visit_date),MAX(visit_date) FROM family_service_facts').fetchone()
  for key,label in [('visit_count','visit_count'),('service_revenue','service_revenue_vnd'),
                    ('warranty_visit_count','warranty_visit_count'),
                    ('warranty_rate','warranty_rate_percent'),
                    ('average_paid_ticket','average_paid_ticket_vnd')]:
   if query_kpi(db,key,start_date=first,end_date=last,as_of_date=last)!=qa['kpis'][label]:
    raise ValueError('M03 reader smoke KPI mismatch '+key)
 manifest={'shop_id':SHOP,'family':'motorcycle_service_ledger','release_id':str(uuid4()),
   'source_dataset_version':cat['version_id'],'approval_status':'PRODUCTION_APPROVED',
   'approved_by':approver,'approved_at_utc':cat['approved_at_utc'],
   'approved_metrics':APPROVED,'source_sha256':digest(source),
   'candidate_sha256':digest(candidate),'database_sha256':digest(target),
   'visit_count':len(visits),'notes_excluded':len(notes),
   'files':['dev_012.sqlite','qa_report.json','manifest.json']}
 (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 return manifest

def main():
 p=argparse.ArgumentParser()
 p.add_argument('--source',type=Path,required=True)
 p.add_argument('--candidate',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True)
 p.add_argument('--report',type=Path)
 p.add_argument('--approve',action='store_true')
 p.add_argument('--approved-by',default='')
 a=p.parse_args()
 try:
  if a.approve:
   if not a.approved_by.strip():p.error('Require human --approved-by')
   result=publish(a.source,a.candidate,a.output,a.approved_by)
  else:
   result=acceptance(a.source,a.candidate)
   if a.report:
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
  print(json.dumps(result,ensure_ascii=False,indent=2))
  if not a.approve and not result['accepted']:raise SystemExit(2)
 except (ValueError,sqlite3.Error) as exc:
  print('DEV012 RELEASE BLOCKED:',exc,file=sys.stderr)
  raise SystemExit(2)

if __name__=='__main__':main()
