#!/usr/bin/env python3
"""Evidence-conservative M01 mart builder for nine previously unmapped shops.
Requires openpyxl for xlsx. No synthetic KPI totals; unresolved records are staged.
"""
import argparse,csv,datetime as dt,decimal,hashlib,json,re,sqlite3,sys
from pathlib import Path
from collections import Counter
try:import openpyxl
except ImportError:sys.exit('Install openpyxl: python -m pip install openpyxl')
SHOPS=[3,4,5,6,7,8,11,13,14]
TABLES=['orders','order_lines','order_adjustments','products','customers','entity_aliases','unit_conversions','payments','purchase_receipts','purchase_lines','returns','inventory_events','inventory_snapshots','lots','lot_allocations','price_history','expenses','deliveries','service_visits','visit_tasks','trade_ins','installment_schedules','warranty_visits']
GRAINS={
'orders':(['MaHoaDon','Đơn số','Mã hóa đơn','Mã đơn hàng','Mã đơn','Bill','Mã bill','HĐ'],['TongThanhToan','Tổng thanh toán','Tổng tiền hàng','Tổng tiền','Thành tiền']),
'order_lines':(['MaHoaDon','Đơn số','Mã hóa đơn','Mã đơn hàng','Mã bill','Bill','HĐ'],['TriGia','Thành tiền','TT']),
'payments':(['MaPhieuThu','Mã thanh toán','Mã phiếu thu'],['SoTienThu','Tiền thu']),
'products':(['MaHangHoa','Mã SKU','Mã sản phẩm bán','Mã H.hóa','Mã vạch','ma_sp','Mã SKU'],[]),
'customers':(['MaKhachHang','Mã KH mua','Mã KH'],[]),
'purchase_receipts':(['MaPhieuNhap','Mã đơn nhập','Mã phiếu nhập','Số phiếu'],['TongGiaTriNhap','Tổng tiền phiếu']),
'purchase_lines':(['MaPhieuNhap','Mã đơn nhập','Mã phiếu nhập','Số phiếu'],['Thành tiền','TongGiaTriNhap']),
'returns':(['MaPhieuTra'],['TienHoanTra']),
'inventory_events':(['MaGiaoDichKho'],[]),
'inventory_snapshots':(['MaHangHoa','Mã SKU','ma_sp','Mã SKU'],[]),
'price_history':(['MaHangHoa','Mã H.hóa'],['GiaBanLe','Giá mới']),
'expenses':([],['Tiền chi']),
'deliveries':(['Số đơn'],[]),
'installment_schedules':(['STT'],[]),
'warranty_visits':(['IMEI'],[]),
'lots':(['MaLo','Mã lô'],[]),
'lot_allocations':(['MaLo','Mã lô'],[]),
'unit_conversions':(['MaHangHoa','Mã SKU'],[]),
'entity_aliases':([],[]),
'trade_ins':(['IMEI'],['Giá thu']),
}
EXPLICIT={
'dev_003':{'BanHang':'orders','BanHang_HangHoa':'products','BanHang_KhachHang':'customers','BanHang_DonViQuyDoi':'unit_conversions','BanHang_LichSuGia':'price_history','BanHang_PhieuThu':'payments','SoTay_NhapHang':'purchase_lines','SoTay_ChiPhi':'expenses','ton_kho':'inventory_snapshots'},
'dev_004':{'SoBanHang':'order_lines','SoNhapHang':'purchase_lines','SoGiaoHang':'deliveries','TonKho':'inventory_snapshots','DanhMuc':'unit_conversions','BangGia':'price_history','SoHanNo':'installment_schedules'},
'dev_005':{'DonHang_ChiTiet':'order_lines','DanhSachSanPham':'products','DanhSachQuyDoi':'unit_conversions','DonNhapHang_ChiTiet':'purchase_lines','DonNhapHang':'purchase_receipts','DonHang_Lo':'lot_allocations'},
'dev_006':{'don_hang':'orders','chi_tiet_don':'order_lines','thanh_toan':'payments','san_pham':'products','khach_hang':'customers','phieu_nhap':'purchase_receipts','chi_tiet_nhap':'purchase_lines','tra_hang':'returns','the_kho':'inventory_events','lich_su_gia':'price_history','lo_hang':'lots','chi_tiet_don_lo':'lot_allocations','don_vi_sp':'unit_conversions'},
'dev_007':{'chi_tiet_hoa_don':'order_lines','chi_tiet_nhap_hang':'purchase_lines','danh_muc_hang':'products'},
'dev_008':{'ChiTietHoaDon_1':'order_lines','ChiTietHoaDon_2':'order_lines','ChiTietNhapHang':'purchase_lines','DanhMucHang':'products'},
'dev_011':{'Sổ bán hàng':'order_lines','Ghi tắt':'entity_aliases'},
'dev_013':{'BanHang_2025':'order_lines','BanHang_2026':'order_lines','DanhMuc':'products','KhachHang':'customers','NhapHang':'purchase_lines'},
'dev_014':{'T7-2025':'order_lines','T8-2025':'order_lines','T9-2025':'order_lines','T10-2025':'order_lines','T11-2025':'order_lines','T12-2025':'order_lines','T1-2026':'order_lines','T2-2026':'order_lines','T3-2026':'order_lines','T4-2026':'order_lines','T5-2026':'order_lines','T6-2026':'order_lines','T7-2026':'order_lines','T8-2026':'order_lines','T9-2026':'order_lines','Ghi tắt':'entity_aliases','Sổ nợ':'payments','Trả góp':'installment_schedules','Bảo hành':'warranty_visits','ThuMayCu':'trade_ins'}
}
DATE=['NgayLap','Ngày HĐ','Ngày giao dịch','Ngày','Ngày nhập','NgayNhapKho','ThoiGianLap','Ngày TT','NgayGioThu','NgayGioTra','NgayGioPhatSinh','NgayApDung','Ngày áp dụng','Ngày nhận','Giờ bán','Ngày mua','Thời gian giao']
NAME=['TenGoi','Tên sản phẩm','Tên hàng','Hàng','Hàng hóa','Hàng hoá','Mặt hàng','Product','Tên mặt hàng','Tên hàng hóa','Máy','Máy thu','Khách','Khách hàng (tên)']
QTY=['SL','Sluong','SL nhập','Số lượng','SoLuong','SLQuyDoi','Số lượng giao','Số lượng nhập','Tồn cuối','Tồn thực','Ton kho']
UNIT=['DonViTinh','DVT','ĐVT','Đơn vị (tính)','ĐVT nhập','Đơn vị','ĐV gốc']
STATUS=['TinhTrang','Trạng thái đơn hàng','Trạng thái giao','Tiến độ','Trạng thái phiếu']

def uid(*x):return hashlib.sha256('|'.join(map(str,x)).encode()).hexdigest()[:28]
def pick(row,keys):
 for k in keys:
  if k in row and row[k] is not None and str(row[k]).strip()!='':return row[k],k
 return None,None

def money(x):
 if x is None or str(x).strip()=='':return None
 if isinstance(x,(int,float,decimal.Decimal)):return str(x)
 s=str(x).strip().lower().replace('₫','').replace('đ','').replace(' ','')
 mult=1
 if 'tr' in s:
  mult=1000000;s=s.replace('tr','.') if re.search(r'\dtr\d',s) else s.replace('tr','')
 elif s.endswith('k'):mult=1000;s=s[:-1]
 s=s.replace(',','.')
 if not re.fullmatch(r'[+-]?\d+(?:\.\d+)*',s):return None
 chunks=s.lstrip('+-').split('.')
 if len(chunks)>1 and all(len(t)==3 for t in chunks[1:]):s=s.replace('.','')
 elif len(chunks)>2:return None
 try:return str(decimal.Decimal(s)*mult)
 except decimal.InvalidOperation:return None

def date(x,context=''):
 if isinstance(x,dt.datetime):return x.date().isoformat()
 if isinstance(x,dt.date):return x.isoformat()
 if isinstance(x,(int,float)) and 30000<x<90000:return (dt.datetime(1899,12,30)+dt.timedelta(days=x)).date().isoformat()
 if x is None:return None
 s=str(x).strip().lower()
 m=re.fullmatch(r'(\d{1,2})\s+th(?:g|áng)\s+(\d{1,2})\s+(\d{4})',s)
 if m:
  try:return dt.date(int(m[3]),int(m[2]),int(m[1])).isoformat()
  except ValueError:return None
 for fmt in ('%d/%m/%Y','%Y-%m-%d','%Y-%m-%d %H:%M:%S','%d-%m-%Y','%d/%m/%y'):
  try:return dt.datetime.strptime(s,fmt).date().isoformat()
  except ValueError:pass
 m=re.search(r'(?:T|Thang)(\d{1,2})[-_](20\d{2})',context,re.I)
 if m and re.fullmatch(r'\d{1,2}/\d{1,2}',s):
  try:return dt.date(int(m[2]),int(m[1]),int(s.split('/')[0])).isoformat()
  except ValueError:return None
 return None

def read_csv(p):
 with p.open(encoding='utf-8-sig',newline='') as f:
  sample=f.read(8192);f.seek(0)
  try:d=csv.Sniffer().sniff(sample,delimiters=',;\t')
  except csv.Error:d=csv.excel
  for i,row in enumerate(csv.reader(f,d),1):yield i,row

def records_xlsx(p):
 wb=openpyxl.load_workbook(p,read_only=True,data_only=True)
 try:
  for ws in wb:
   yield ws.title,ws.values
 finally:wb.close()

def create_db(path):
 c=sqlite3.connect(path);c.execute('PRAGMA journal_mode=DELETE')
 c.executescript('''CREATE TABLE dataset_versions(version_id TEXT PRIMARY KEY,shop_id TEXT,contract_version TEXT,config_sha256 TEXT,created_at TEXT,status TEXT);
 CREATE TABLE raw_sources(source_id TEXT PRIMARY KEY,shop_id TEXT,source_path TEXT,source_sha256 TEXT,source_object TEXT,source_format TEXT,header_row INTEGER);
 CREATE TABLE staging_rows(staging_uid TEXT PRIMARY KEY,source_id TEXT,source_row INTEGER,raw_json TEXT,parsed_json TEXT,issue_count INTEGER);
 CREATE TABLE validation_issues(issue_uid TEXT PRIMARY KEY,shop_id TEXT,source_id TEXT,source_row INTEGER,source_cell TEXT,code TEXT,severity TEXT,detail TEXT);
 CREATE TABLE source_lineage(lineage_uid TEXT PRIMARY KEY,entity_table TEXT,entity_uid TEXT,shop_id TEXT,source_id TEXT,source_row INTEGER,source_cell TEXT,transform_id TEXT,raw_value TEXT,version_id TEXT);
 CREATE TABLE business_catalog(catalog_key TEXT PRIMARY KEY,catalog_json TEXT);''')
 for t in TABLES:c.execute(f'''CREATE TABLE {t}(uid TEXT PRIMARY KEY,shop_id TEXT,source_id TEXT,source_row INTEGER,source_business_id TEXT,event_date TEXT,amount TEXT,quantity TEXT,unit TEXT,document_uid TEXT,display_name TEXT,status_raw TEXT,attributes_json TEXT,version_id TEXT)''')
 c.execute('CREATE INDEX idx_lineage_entity ON source_lineage(entity_table,entity_uid)');return c

def main():
 a=argparse.ArgumentParser();a.add_argument('--data-root',required=True);a.add_argument('--output',required=True);a.add_argument('--shops',nargs='*',default=[f'dev_{i:03d}' for i in SHOPS]);args=a.parse_args()
 root=Path(args.data_root);out=Path(args.output);out.mkdir(parents=True,exist_ok=True);manifest=[]
 for shop in args.shops:
  folder=root/'public_test'/'data'/shop
  if not folder.exists():raise SystemExit(f'Missing source folder {folder}')
  target=out/f'{shop}.sqlite'
  if target.exists():target.unlink()
  c=create_db(target);version=uid(shop,'mapping_candidate_v1');c.execute('INSERT INTO dataset_versions VALUES(?,?,?,?,?,?)',(version,shop,'0.3.0-candidate','evidence-candidate',dt.datetime.now(dt.timezone.utc).isoformat(),'PROVISIONAL_NOT_FOR_PRODUCTION'))
  stats=Counter();unmapped=[];issues=Counter();source_objects=0;grouped=set();total_files=0
  def problem(src,row,code,detail,severity='WARNING'):
   issues[code]+=1;c.execute('INSERT OR IGNORE INTO validation_issues VALUES(?,?,?,?,?,?,?,?)',(uid(src,row,code),shop,src,row,None,code,severity,str(detail)[:400]))
  def consume(p,obj,iterator,fmt):
   nonlocal source_objects
   stem=p.stem;selector=stem if stem in EXPLICIT.get(shop,{}) else obj
   grain=EXPLICIT.get(shop,{}).get(selector)
   if not grain:
    unmapped.append(p.name+'::'+obj);return
   it=iter(iterator);first=[]
   for _ in range(5):
    try:first.append(next(it))
    except StopIteration:break
   # Detect second-row headers, including merged top rows.
   best=(-1,0)
   for idx,(rn,vals) in enumerate(first):
    nonempty=[str(v).strip() for v in vals if v is not None and str(v).strip()]
    score=len(nonempty)+sum(any(x in nonempty for x in ks) for ks in [DATE,NAME,QTY,UNIT]) * 3
    if score>best[0]:best=(score,idx)
   if not first:return
   header_idx=best[1];header_row,header_vals=first[header_idx]
   headers=[str(v).strip() if v is not None else '' for v in header_vals]
   if not any(headers):unmapped.append(p.name+'::'+obj);return
   sha=hashlib.sha256(p.read_bytes()).hexdigest();src=uid(shop,p.name,obj,sha)
   c.execute('INSERT INTO raw_sources VALUES(?,?,?,?,?,?,?)',(src,shop,'public_test/data/'+shop+'/'+p.name,sha,obj,fmt,header_row));source_objects+=1
   def row_iter():
    yield from first[header_idx+1:];yield from it
   for rn,vals in row_iter():
    if not any(v is not None and str(v).strip() for v in vals):continue
    raw={h:vals[i] if i<len(vals) else None for i,h in enumerate(headers) if h}
    if not raw:continue
    # repeated header rows or section labels should not enter mart
    if sum(str(raw.get(h,''))==h for h in headers if h)>2:continue
    bid,bid_col=pick(raw,GRAINS.get(grain,([],[]))[0]);amount_val,amount_col=pick(raw,GRAINS.get(grain,([],[]))[1]);dt_val,dt_col=pick(raw,DATE);name,name_col=pick(raw,NAME);qty,qty_col=pick(raw,QTY);unit,unit_col=pick(raw,UNIT);status,status_col=pick(raw,STATUS)
    if grain=='order_lines' and shop in ('dev_011','dev_014'):
     # These journals use STT as order/group indicator; blank continuation rows
     # are not assigned a document without validated group boundary.
     bid,bid_col=pick(raw,['STT'])
    if grain=='order_lines' and shop=='dev_013':
     bid,bid_col=pick(raw,['HĐ'])
     if str(name or '').strip().lower() in ('voucher','phí ship','phí vận chuyển','giảm giá'):
      grain_row='order_adjustments'
     else:grain_row=grain
    else:grain_row=grain
    if grain=='order_lines' and shop=='dev_004':bid,bid_col=pick(raw,['Mã đơn','Số đơn','HĐ','STT'])
    if grain=='order_lines' and shop=='dev_005':bid,bid_col=pick(raw,['Mã đơn hàng','Mã hóa đơn','Mã đơn','Mã đơn bán'])
    if grain=='order_lines' and shop=='dev_008':bid,bid_col=pick(raw,['Bill'])
    if grain=='order_lines' and shop=='dev_007':bid,bid_col=pick(raw,['Mã bill'])
    if grain=='purchase_lines' and shop=='dev_005':bid,bid_col=pick(raw,['Mã đơn nhập'])
    if grain=='order_lines' and not (bid or name):
     problem(src,rn,'MISSING_LINE_IDENTIFIERS','no document identifier or item');continue
    if grain_row=='order_adjustments' and not bid:
     problem(src,rn,'UNLINKED_ADJUSTMENT','no document identifier');continue
    if grain in ('orders','payments','purchase_receipts','returns') and not bid:
     problem(src,rn,'MISSING_BUSINESS_ID',grain);continue
    if grain=='order_lines' and not bid:
     problem(src,rn,'UNLINKED_LINE','line has no explicit document id; staged only');continue
    if grain=='order_lines' and not name:
     problem(src,rn,'MISSING_ITEM','line missing item; staged only');continue
    parsed={'business_id':str(bid).strip() if bid is not None else None,'event_date':date(dt_val,p.stem+' '+obj),'amount':money(amount_val),'quantity':str(qty) if qty is not None else None,'unit':str(unit) if unit is not None else None,'display_name':str(name) if name is not None else None}
    c.execute('INSERT OR REPLACE INTO staging_rows VALUES(?,?,?,?,?,?)',(uid(src,rn),src,rn,json.dumps(raw,ensure_ascii=False,default=str),json.dumps(parsed,ensure_ascii=False),0))
    ent=uid(shop,grain_row,src,rn);doc=uid(shop,'document',src,bid) if bid is not None else None
    attrs={'source_grain':grain_row,'source_object':obj,'source_values':raw,'date_unparsed':str(dt_val) if dt_val is not None and not parsed['event_date'] else None,'amount_unparsed':str(amount_val) if amount_val is not None and parsed['amount'] is None else None}
    c.execute(f'INSERT INTO {grain_row} VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(ent,shop,src,rn,parsed['business_id'],parsed['event_date'],parsed['amount'],parsed['quantity'],parsed['unit'],doc,parsed['display_name'],str(status) if status is not None else None,json.dumps(attrs,ensure_ascii=False,default=str),version));stats[grain_row]+=1
    for field,col,val in [('business_id',bid_col,bid),('event_date',dt_col,dt_val),('amount',amount_col,amount_val),('quantity',qty_col,qty),('unit',unit_col,unit),('display_name',name_col,name),('status',status_col,status)]:
     if col is not None:c.execute('INSERT OR IGNORE INTO source_lineage VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(ent,field,col),grain_row,ent,shop,src,rn,col,'m01_candidate:'+field,json.dumps(val,ensure_ascii=False,default=str),version))
    c.execute('INSERT OR IGNORE INTO source_lineage VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(ent,'row'),grain_row,ent,shop,src,rn,None,'source_row',None,version))
   c.commit()
  for p in sorted(folder.iterdir()):
   if p.suffix.lower() not in ('.xlsx','.csv','.sqlite'):continue
   total_files+=1
   if p.suffix=='.csv':consume(p,p.stem,read_csv(p),'csv')
   elif p.suffix=='.xlsx':
    for obj,rows in records_xlsx(p):consume(p,obj,enumerate(rows,1),'xlsx')
   else:
    source=sqlite3.connect(f'file:{p.resolve()}?mode=ro',uri=True)
    for obj, in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
     cols=[x[1] for x in source.execute('PRAGMA table_info("'+obj+'")')]
     def get_rows():
      yield 1,cols
      for rn,row in enumerate(source.execute('SELECT * FROM "'+obj+'"'),2):yield rn,row
     consume(p,obj,get_rows(),'sqlite')
    source.close()
  catalog={'shop_id':shop,'version_id':version,'validation_status':'PROVISIONAL_NOT_FOR_PRODUCTION','contract_version':'0.3.0-candidate','source_files_seen':total_files,'source_objects_processed':source_objects,'row_counts':dict(stats),'issue_counts':dict(issues),'unmapped_objects':unmapped,'capabilities':{t:stats[t]>0 for t in TABLES},'approval_status':'CANDIDATE_NOT_APPROVED','notes':'Candidate mappings, no inferred document totals. Raw data in staging, source provenance in lineage. No official KPI approval.'}
  c.execute('INSERT INTO business_catalog VALUES(?,?)',(shop,json.dumps(catalog,ensure_ascii=False)));c.commit();integrity=c.execute('PRAGMA integrity_check').fetchone()[0];c.close()
  manifest.append({'shop':shop,'integrity':integrity,'sources':source_objects,'rows':dict(stats),'unmapped':len(unmapped),'issues':dict(issues)});print(shop,'sources',source_objects,'rows',sum(stats.values()),'unmapped',len(unmapped),flush=True)
 (out/'mapping_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print('DONE',out)
if __name__=='__main__':main()
