import json,sqlite3,csv
from pathlib import Path
root=Path(__file__).resolve().parents[1];rows=[]
for shop in ['dev009','dev002','dev010','dev012']:
 c=sqlite3.connect(root/(shop+'_demo.sqlite'))
 cat=json.loads(c.execute('select catalog_json from business_catalog').fetchone()[0]);
 for entity,num in cat['row_counts'].items():
  if num:rows.append({'shop':cat['shop_id'],'kind':'mart','name':entity,'count':num,'status':cat['validation_status']})
 for name,num in cat['issue_counts'].items():rows.append({'shop':cat['shop_id'],'kind':'issue','name':name,'count':num,'status':cat['validation_status']})
 for tab in ['raw_sources','staging_rows','source_lineage','validation_issues']:
  rows.append({'shop':cat['shop_id'],'kind':'audit','name':tab,'count':c.execute(f'select count(*) from {tab}').fetchone()[0],'status':cat['validation_status']})
 print(cat['shop_id'],cat['issue_counts'],cat['row_counts']['orders'],cat['row_counts']['order_lines'])
 with open(root/(shop+'_catalog.json'),'w') as f:json.dump(cat,f,ensure_ascii=False,indent=2)
 c.close()
with open(root/'QA_SUMMARY.csv','w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=['shop','kind','name','count','status']);w.writeheader();w.writerows(rows)
