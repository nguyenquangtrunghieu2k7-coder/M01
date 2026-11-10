import json,sqlite3,tempfile,unittest
from pathlib import Path
from datamate.m01_data_processing.pipeline import date_parse,money_parse,quantity_parse,build,connect,TABLES
class CoreTests(unittest.TestCase):
 def test_money(self):
  self.assertEqual(money_parse('24,000.0000'),'24000.0000');self.assertEqual(money_parse('29k'),'29000');self.assertEqual(money_parse('43.000đ'),'43000')
  with self.assertRaises(ValueError):money_parse('12,34,5')
 def test_date(self):
  self.assertEqual(date_parse('01/02/2025'),'2025-02-01');self.assertEqual(date_parse('2025-02-01 00:00:00'),'2025-02-01')
 def test_quantity(self):self.assertEqual(quantity_parse('3 lon'),('3','lon'))
 def test_contract_tables(self):
  with tempfile.TemporaryDirectory() as td:
   c=connect(Path(td)/'x.sqlite',TABLES);tables={r[0] for r in c.execute("select name from sqlite_master where type='table'")}
   self.assertTrue(set(TABLES).issubset(tables));self.assertIn('source_lineage',tables)
 def test_fail_closed(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'config.json';p.write_text(json.dumps({'shop_id':'dev_009','approval_status':'EVIDENCE_VALIDATED_NOT_APPROVED','sources':[]}))
   with self.assertRaisesRegex(ValueError,'FAIL_CLOSED'):build(p,td,Path(td)/'demo.sqlite')
 def test_summary_only_no_fake_lines(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'sale.csv').write_text('id,date,total\nA,01/01/2025,1000\nA,01/01/2025,1000\nB,02/01/2025,2000\n')
   cfg={'shop_id':'dev_test','approval_status':'EVIDENCE_VALIDATED_NOT_APPROVED','sources':[{'path':'sale.csv','format':'csv','object':'sale.csv','header_row':1,'grain':'order','fields':{'business_id':'id','date':'date','amount':'total'}}]}
   p=root/'config.json';p.write_text(json.dumps(cfg));result=build(p,root,root/'demo.sqlite',True)
   self.assertEqual(result['row_counts']['orders'],3);self.assertEqual(result['row_counts']['order_lines'],0)
   self.assertEqual(result['issue_counts']['DUPLICATE_ORDER_KEY'],1)
   c=sqlite3.connect(root/'demo.sqlite');self.assertEqual(c.execute('select count(*) from staging_rows').fetchone()[0],3)
if __name__=='__main__':unittest.main()
