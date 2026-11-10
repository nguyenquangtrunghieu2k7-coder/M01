#!/usr/bin/env python3
"""Read-only semantic completeness inventory across 13 candidates.

Structural QA is not semantic QA. Report date, amount, status coverage, raw
sample distribution, and family-native roles. Never approve metrics.
"""
import argparse,json,sqlite3
from pathlib import Path
SHOPS=[f'dev_{i:03d}' for i in range(1,15) if i!=6]
TRANSACTIONS={'orders','order_lines','payments','purchase_receipts','purchase_lines',
 'returns','inventory_events','deliveries','service_visits','trade_ins',
 'installment_schedules','warranty_visits','expenses'}
NEED_MONEY={'orders','order_lines','payments','purchase_receipts','purchase_lines',
 'service_visits','expenses'}

def inspect_one(path,shop):
 with sqlite3.connect(f'file:{path.resolve()}?mode=ro',uri=True) as db:
  cats=db.execute('SELECT catalog_json FROM business_catalog').fetchall()
  if len(cats)!=1:raise ValueError('Expected one catalog '+shop)
  cat=json.loads(cats[0][0]);issues=[];entities={}
  if cat.get('shop_id')!=shop or cat.get('approval_status')!='CANDIDATE_NOT_APPROVED':
   issues.append('incorrect candidate identity/approval status')
  for table,count in cat.get('row_counts',{}).items():
   if not count or table not in TRANSACTIONS:continue
   n,d,a=db.execute(f"""SELECT COUNT(*),
      SUM(CASE WHEN event_date IS NULL OR event_date='' THEN 1 ELSE 0 END),
      SUM(CASE WHEN amount IS NULL OR amount='' THEN 1 ELSE 0 END)
      FROM "{table}" WHERE shop_id=?""",(shop,)).fetchone()
   statuses=dict(db.execute(f"""SELECT COALESCE(status_raw,'<NULL>'),COUNT(*)
      FROM "{table}" WHERE shop_id=? GROUP BY COALESCE(status_raw,'<NULL>')
      ORDER BY COUNT(*) DESC LIMIT 25""",(shop,)).fetchall())
   entities[table]={'rows':n,'missing_date':d or 0,'missing_amount':a or 0,
     'observed_raw_statuses':statuses}
   if table in ('orders','order_lines','service_visits') and d:
    issues.append(f'{table}: {d}/{n} have no parsed date')
   if table in NEED_MONEY and a:
    issues.append(f'{table}: {a}/{n} have no parsed amount')
   if table in ('orders','order_lines') and any(
       v not in ('completed','cancelled','returned','shipping') for v in statuses):
    issues.append(f'{table}: business status normalization unproven')
  native=db.execute('SELECT family_role,COUNT(*) FROM family_native_records GROUP BY family_role').fetchall()
  return {'shop_id':shop,'family':cat.get('family'),'source_objects':cat.get('source_objects_processed'),
    'staging_rows':db.execute('SELECT COUNT(*) FROM staging_rows').fetchone()[0],
    'family_native_roles':dict(native),'candidate_entities':entities,
    'semantic_risks':issues,'approved_metrics':[],'production_approved':False}

def main():
 p=argparse.ArgumentParser()
 p.add_argument('--candidates',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();results=[]
 for shop in SHOPS:
  db=a.candidates/(shop+'.sqlite')
  if not db.is_file():raise SystemExit('Missing '+str(db))
  results.append(inspect_one(db,shop))
 report={'shop_count':len(results),'total_staging_rows':sum(x['staging_rows'] for x in results),
   'shops_with_semantic_risks':sum(bool(x['semantic_risks']) for x in results),
   'all_shops_production_approved':False,'shops':results}
 a.output.parent.mkdir(parents=True,exist_ok=True)
 a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k!='shops'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
