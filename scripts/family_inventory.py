#!/usr/bin/env python3
"""Inventory all 13 non-dev006 families at physical source-object granularity.

Source list comes from actual CSV/XLSX/SQLite files, never guessed. Classify
by shop AND file/sheet, not a global mapping. Output is CANDIDATE, not M03
production approval. No PII or source rows are written to contracts.
"""
import argparse,csv,json,sqlite3,zipfile,xml.etree.ElementTree as ET
from pathlib import Path

FAMILIES={
'dev_001':'retail_single_export','dev_002':'retail_monthly_exports',
'dev_003':'cafe_multi_source','dev_004':'building_materials_delivery',
'dev_005':'pharmacy_excel_lots','dev_007':'restaurant_csv_pos',
'dev_008':'restaurant_excel_pos','dev_009':'invoice_summary_only',
'dev_010':'linked_csv_pos','dev_011':'mobile_sales_ledger',
'dev_012':'motorcycle_service_ledger','dev_013':'mother_baby_ledger',
'dev_014':'mobile_multi_ledger'}
SIMPLE={
'dev_001':{'So_chi_tiet_ban_hang':'order_lines','Danh sách hàng hóa':'products'},
'dev_003':{'BanHang':'order_lines','BanHang_HangHoa':'products','BanHang_KhachHang':'customers',
 'BanHang_DonViQuyDoi':'unit_conversions','BanHang_LichSuGia':'price_history',
 'BanHang_PhieuThu':'payments','SoTay_NhapHang':'purchase_lines','SoTay_ChiPhi':'expenses',
 'ton_kho':'inventory_snapshots','BaoCaoCa':'cash_shift'},
'dev_004':{'SoBanHang':'order_lines','SoNhapHang':'purchase_lines',
 'SoGiaoHang':'deliveries','TonKho':'inventory_snapshots','DanhMuc':'unit_conversions',
 'BangGia':'price_history','SoHanNo':'receivable_schedule'},
'dev_005':{'DonHang_ChiTiet':'order_lines','DanhSachSanPham':'products',
 'DanhSachQuyDoi':'unit_conversions','DonNhapHang_ChiTiet':'purchase_lines',
 'DonNhapHang':'purchase_receipts','DonHang_Lo':'lot_allocations','DanhSachThuoc':'medicine_catalog'},
'dev_007':{'chi_tiet_hoa_don':'order_lines','chi_tiet_nhap_hang':'purchase_lines','danh_muc_hang':'products'},
'dev_008':{'ChiTietHoaDon_1':'order_lines','ChiTietHoaDon_2':'order_lines',
 'ChiTietNhapHang':'purchase_lines','DanhMucHang':'products'},
'dev_009':{'danh_sach_hoa_don':'orders'},
'dev_010':{'don_hang':'orders','chi_tiet_don':'order_lines','thanh_toan':'payments',
 'khach_hang':'customers','san_pham':'products'},
'dev_011':{'Sổ bán hàng':'order_lines','Ghi tắt':'entity_aliases'},
'dev_012':{'SoSuaXe':'service_visits','DanhSachTho':'staff_reference'},
'dev_013':{'DanhMuc':'products','KhachHang':'customers','NhapHang':'purchase_lines',
 'KhuyenMai':'promotions'},
'dev_014':{'Ghi tắt':'entity_aliases','Sổ nợ':'receivables',
 'Trả góp':'installment_schedules','Bảo hành':'warranty_visits','ThuMayCu':'trade_ins'}
}

def role(shop,path,obj):
    stem=path.stem
    if shop=='dev_003' and obj=='BanHang':return 'order_lines'
    if shop=='dev_002':
        return 'unit_conversions' if stem=='DanhSachQuyDoi' else ('order_lines' if stem.startswith('BanHang_T') and obj=='DonHang_ChiTiet' else 'unclassified')
    if shop=='dev_005' and stem.startswith('BanHang_Thang'):
        return 'order_lines' if obj=='DonHang_ChiTiet' else 'unclassified'
    if shop=='dev_013' and stem.startswith('BanHang_'):
        return 'order_lines_with_adjustments'
    if shop=='dev_014' and stem=='SoBanHang' and obj!='Ghi tắt':
        return 'order_lines'
    if shop=='dev_012' and stem=='SoSuaXe':return 'service_visits'
    if shop=='dev_001' and stem.startswith('Danh'):return 'products'
    if shop=='dev_001' and stem.startswith('So_chi'):return 'order_lines'
    if shop=='dev_004':return SIMPLE[shop].get(stem,'unclassified')
    if shop=='dev_008':return SIMPLE[shop].get(stem,'unclassified')
    if shop=='dev_003' and stem=='BaoCaoCa':return 'cash_shift'
    if shop=='dev_003' and stem=='SoTay_ChiPhi':return 'expenses'
    if shop=='dev_003' and stem=='SoTay_NhapHang':return 'purchase_lines'
    if shop=='dev_003' and stem=='BanHang_PhieuThu':return 'payments'
    if shop=='dev_005' and stem in SIMPLE[shop]:return SIMPLE[shop][stem]
    if shop=='dev_014' and stem=='ThuMayCu':return 'trade_ins'
    return SIMPLE.get(shop,{}).get(obj,SIMPLE.get(shop,{}).get(stem,'unclassified'))

def inventory(folder):
    out=[]
    for path in sorted(folder.iterdir()):
        ext=path.suffix.lower()
        if ext=='.xlsx':
            with zipfile.ZipFile(path) as z:
                root=ET.fromstring(z.read('xl/workbook.xml'))
                ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                for item in root.findall('x:sheets/x:sheet',ns):
                    out.append((path,item.attrib['name'],'xlsx'))
        elif ext=='.csv':out.append((path,path.stem,'csv'))
        elif ext=='.sqlite':
            with sqlite3.connect(f'file:{path.resolve()}?mode=ro',uri=True) as c:
                for (obj,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                    out.append((path,obj,'sqlite'))
    return out

def contract(shop,folder):
    if not (folder/'README.md').is_file():
        raise FileNotFoundError('README missing: '+shop)
    entries=[{'path':f'public_test/data/{shop}/{p.name}','format':fmt,
              'object':obj,'candidate_role':role(shop,p,obj),
              'mapping_approval':'review_required',
              'semantic_evidence':f'public_test/data/{shop}/README.md'}
             for p,obj,fmt in inventory(folder)]
    return {'shop_id':shop,'family':FAMILIES[shop],
            'contract_version':'0.1.0-candidate','approval_status':'CANDIDATE_NOT_APPROVED',
            'official_kpis_approved':[],'source_manifest':entries,
            'raw_preservation_required':True,'lineage_required':True,
            'fail_closed':True,
            'do_not_infer':['invoice_lines_from_summary'] if shop=='dev_009' else [],
            'rulebook':'public_test/rulebook.md'}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--write-contracts',action='store_true')
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    configdir=a.output/'family_contracts';configdir.mkdir(exist_ok=True)
    report=[]
    for shop in FAMILIES:
        folder=a.data_root/'public_test'/'data'/shop
        found=contract(shop,folder)
        destination=configdir/(shop+'.json')
        if a.write_contracts:
            if destination.exists():raise FileExistsError(destination)
            destination.write_text(json.dumps(found,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        else:
            found=json.loads(destination.read_text(encoding='utf-8'))
        physical={(p.name,obj,fmt) for p,obj,fmt in inventory(folder)}
        declared={(Path(s['path']).name,s['object'],s['format']) for s in found['source_manifest']}
        unclassified=[(Path(s['path']).name,s['object']) for s in found['source_manifest']
                      if s['candidate_role']=='unclassified']
        good=(found['shop_id']==shop and found['family']==FAMILIES[shop]
              and found['approval_status']=='CANDIDATE_NOT_APPROVED'
              and not found['official_kpis_approved'] and physical==declared
              and len(declared)==len(found['source_manifest']) and not unclassified)
        report.append({'shop_id':shop,'family':found['family'],'source_objects':len(physical),
                       'configured_source_objects':len(declared),
                       'uncovered':sorted(map(list,physical-declared)),
                       'unclassified':unclassified,'inventory_pass':good,
                       'production_approved':False})
    summary={'shops':len(report),'source_objects':sum(x['source_objects'] for x in report),
             'inventory_pass_count':sum(x['inventory_pass'] for x in report),
             'production_approved':False,'shops_detail':report}
    (a.output/'family_inventory_audit.json').write_text(
        json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='shops_detail'},ensure_ascii=False))
    if summary['inventory_pass_count']!=len(FAMILIES):raise SystemExit(2)

if __name__=='__main__':main()
