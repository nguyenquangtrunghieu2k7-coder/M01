import json,zipfile,os
from pathlib import Path
root=Path(__file__).resolve().parents[1];z=zipfile.ZipFile('/mnt/data/archive.zip');profiles=json.load(open('/mnt/data/profile_report.json'))
config_map={
'dev_009':[('danh_sach_hoa_don.csv','order',{'business_id':'Mã hóa đơn','date':'Ngày tháng','status':'Trạng thái đơn','amount':'TongTien','paid':'Đã thu','debt':'Nợ','customer':'Đối tác','goods_value':'Giá trị hàng'})],
'dev_001':[('So_chi_tiet_ban_hang.xlsx','line_item',{'business_id':'Mã đơn hàng','date':'Ngày','item':'Tên hàng hóa','unit':'Đơn vị tính','quantity':'Số lượng','unit_price':'Đơn giá','amount':'Thành tiền','status':'Trạng thái','customer':'Khách hàng'})],
'dev_002':[('BanHang_T1_2025.xlsx','line_item',{'business_id':'Mã đơn hàng','date':'Ngày đặt hàng','status':'Trạng thái đơn hàng','customer':'Tên khách hàng','item':'Tên sản phẩm','quantity':'Số lượng sản phẩm','unit_price':'Giá sản phẩm','amount':'Tổng tiền','unit':'Đơn vị tính'})]
}
for shop in range(1,15):
 sid=f'dev_{shop:03d}';items=[];candidates=config_map.get(sid,[])
 for name,grain,fields in candidates:
  found=[x for x in z.namelist() if x.startswith('public_test/data/'+sid+'/') and x.endswith('/'+name)]
  if not found:found=[x for x in z.namelist() if x.startswith('public_test/data/'+sid+'/') and x.endswith(name)]
  if not found:raise ValueError(name)
  rel=found[0]
  prof=[x for x in profiles if x['source']['path'].endswith('/'+rel)];
  if not prof:raise ValueError('no profile '+rel)
  p=prof[0]
  for col in fields.values():
   if col not in [c['name'] for c in p['columns']]:raise ValueError('not observed '+col)
  items.append({'path':rel,'format':p['source']['format'],'object':p['source']['object'],'header_row':p['source']['header_row'],'grain':grain,'fields':fields,'evidence':{'business_semantics':'public_test/data/'+sid+'/README.md','physical_columns':'profile_report.json','approval':'review_required'}})
 cfg={'shop_id':sid,'contract_version':'0.2.0','approval_status':'EVIDENCE_VALIDATED_NOT_APPROVED' if items else 'BLOCKED_NO_APPROVED_MAPPING','sources':items,'lineage_policy':'cell and source row','safety_policy':'fail_closed'}
 (root/'configs/m01'/f'{sid}.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
print('Generated 14 configs; 3 provisional candidates from README + profile')
