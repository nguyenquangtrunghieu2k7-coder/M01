#!/usr/bin/env python3
"""Independent source-POS vs normalized-mart acceptance for dev006 KPI candidates.

Read-only. No approval is issued by this audit. Release qualification requires
all family-specific KPI checks to pass, not just an approved revenue KPI.
"""
import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from dev006_extended_kpis import METRICS,calculate
from verify_dev006_m03_parity import verify as verify_revenue

ELIGIBLE={'completed','shipping'}
CHECKPOINTS=('2025-04-30','2025-12-31','2026-08-08')
PERIODS=(('2025-04-01','2025-04-30'),('2026-01-01','2026-01-31'),
         ('2025-04-01','2026-08-08'))

def money(value):
    """Independently parse POS units; tr is decimal millions, k thousands."""
    import re
    if isinstance(value,int):return value
    if value is None:raise ValueError('Missing source receipt')
    s=str(value).strip().lower().replace(' ','').replace('₫','').replace('đ','')
    embedded=re.fullmatch(r'([+-]?\\d+)tr(\\d{1,3})',s)
    if embedded:
        amount=Decimal(embedded.group(1)+'.'+embedded.group(2))*1000000
        if amount!=amount.to_integral_value():
            raise ValueError('Fractional VND: '+repr(value))
        return int(amount)
    unit=1
    if s.endswith('tr'):
        s=s[:-2];unit=1000000
    elif s.endswith('k'):
        s=s[:-1];unit=1000
    if unit!=1:
        if re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?',s) is None:
            raise ValueError('Invalid scaled POS money: '+repr(value))
        amount=Decimal(s.replace(',','.'))*unit
    else:
        if re.fullmatch(r'[+-]?(?:\d+|\d{1,3}(?:\.\d{3})+)',s) is None:
            raise ValueError('Invalid POS money: '+repr(value))
        amount=Decimal(s.replace('.',''))
    if amount!=amount.to_integral_value():raise ValueError('Fractional VND: '+repr(value))
    return int(amount)

def round2(num,den):
    return float((Decimal(100)*Decimal(num)/Decimal(den)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if den else 0.0

def source_facts(db):
    db.row_factory=sqlite3.Row
    orders={str(r['MaHoaDon']):dict(r) for r in db.execute('SELECT * FROM don_hang')}
    lines=[];seen=set()
    for r in db.execute('SELECT * FROM chi_tiet_don ORDER BY rowid'):
        key=tuple(r)
        if key in seen:continue
        seen.add(key)
        lines.append(dict(r))
    drug={str(r['MaHangHoa']):dict(r) for r in db.execute('SELECT * FROM thong_tin_thuoc')}
    products={str(r['MaHangHoa']):dict(r) for r in db.execute('SELECT * FROM san_pham')}
    receipts=[dict(r) for r in db.execute('SELECT * FROM phieu_nhap')]
    payments=[dict(r) for r in db.execute('SELECT * FROM thanh_toan')]
    inventory=[dict(r) for r in db.execute('SELECT * FROM the_kho ORDER BY rowid')]
    prices=[dict(r) for r in db.execute('SELECT * FROM lich_su_gia')]
    lots=[dict(r) for r in db.execute('SELECT * FROM lo_hang')]
    allocations=[dict(r) for r in db.execute('SELECT * FROM chi_tiet_don_lo')]
    returns=[dict(r) for r in db.execute('SELECT * FROM tra_hang')]
    return locals()

def source_expected(facts,metric,*,asof,start=None,end=None,product_id=None,ingredient=None,payment_method=None):
    cut=str(asof)
    first=start or '';last=min(end,cut) if end is not None else ''
    within=lambda day:bool(day and first<=str(day)[:10]<=last)
    orders=facts['orders']
    if metric in ('order_count','cancel_rate'):
        selected=[o for o in orders.values() if within(o['ThoiGianLap'])]
        if metric=='order_count':return sum(o['TinhTrang'] in ELIGIBLE for o in selected)
        return round2(sum(o['TinhTrang']=='cancelled' for o in selected),len(selected))
    if metric in ('gross_profit_by_order_date','units_sold_base','prescription_revenue','ingredient_revenue'):
        total=0
        for r in facts['lines']:
            o=orders[str(r['MaHoaDon'])]
            if o['TinhTrang'] not in ELIGIBLE or not within(o['ThoiGianLap']):continue
            sku=str(r['MaHangHoa'])
            if product_id is not None and str(product_id)!=sku:continue
            if metric=='gross_profit_by_order_date':
                total+=r['TriGia']-r['SL']*r['GiaVonLucBan']
            elif metric=='units_sold_base':total+=r['SLQuyDoi']
            elif metric=='prescription_revenue':
                if int(facts['drug'][sku]['BanTheoDon'])==1:total+=r['TriGia']
            elif metric=='ingredient_revenue':
                if facts['drug'][sku]['ThanhPhanChinh']==ingredient:total+=r['TriGia']
        return float(total) if metric=='units_sold_base' else total
    if metric=='purchases_by_receipt_date':
        return sum(r['TongGiaTriNhap'] for r in facts['receipts']
                if within(r['NgayNhapKho']) and r['TinhTrang'] not in ('cancelled','canceled'))
    if metric=='supplier_purchase_value':
        return sum(r['TongGiaTriNhap'] for r in facts['receipts']
                if within(r['NgayNhapKho']) and r['MaNhaCungCap']==product_id
                and r['TinhTrang'] not in ('cancelled','canceled'))
    if metric=='cash_collected':
        method=payment_method or 'cash'
        return sum(money(r['SoTienThu']) for r in facts['payments']
                   if within(r['NgayGioThu']) and r['PhuongThuc']==method)
    if metric=='returns_count':
        return sum(o['TinhTrang']=='returned' for o in orders.values()
                   if within(o['ThoiGianLap']))
    if metric=='receivables_as_of':
        settled=defaultdict(int)
        for r in facts['payments']:
            if r['NgayGioThu'][:10]<=cut:
                settled[str(r['MaHoaDon'])]+=money(r['SoTienThu'])
        return sum(max(0,o['TongThanhToan']-settled[k]) for k,o in orders.items()
            if o['ThoiGianLap'][:10]<=cut and o['TinhTrang']!='cancelled'
            and o['PhuongThucTT']!='cod'
            and o.get('KenhBanHang') not in ('marketplace','ecommerce','sàn TMĐT'))
    if metric in ('stock_units_as_of','inventory_value_as_of','stockout_product_count'):
        latest={}
        for r in facts['inventory']:
            if r['NgayGioPhatSinh'][:10]>cut:continue
            sku=str(r['MaHangHoa'])
            key=(r['NgayGioPhatSinh'],r['MaGiaoDichKho'])
            if sku not in latest or key>latest[sku][0]:
                latest[sku]=(key,r['TonCuoi'])
        if metric=='stock_units_as_of':
            return latest[str(product_id)][1]
        if metric=='stockout_product_count':
            return sum(q==0 for _,q in latest.values())
        return sum(q*facts['products'][sku]['GiaVonHang'] for sku,(_,q) in latest.items() if q>0)
    if metric=='selling_price_as_of':
        selected=[r for r in facts['prices'] if str(r['MaHangHoa'])==str(product_id) and r['NgayApDung']<=cut]
        if not selected:raise ValueError('No price on checkpoint')
        return max(enumerate(selected),key=lambda x:(x[1]['NgayApDung'],x[0]))[1]['GiaBanLe']
    if metric in ('expiry_lot_count','expiry_lot_cost_vnd'):
        horizon=(date.fromisoformat(cut)+timedelta(days=product_id)).isoformat()
        receipts={r['MaPhieuNhap']:r for r in facts['receipts']}
        returned={}
        for r in facts['returns']:
            oid=r['MaHoaDon']
            if oid not in returned or r['NgayGioTra'][:10]<returned[oid]:
                returned[oid]=r['NgayGioTra'][:10]
        used=defaultdict(int)
        for r in facts['allocations']:
            oid=r['MaHoaDon'];lot=r['MaLo']
            if orders[oid]['ThoiGianLap'][:10]<=cut:
                used[lot]+=r['SLQuyDoi']
            if oid in returned and returned[oid]<=cut:
                used[lot]-=r['SLTraQuyDoi']
        qualified=[]
        for r in facts['lots']:
            if receipts[r['MaPhieuNhap']]['NgayNhapKho']<=cut and cut<=r['HanSuDung']<=horizon:
                left=r['SLNhapQuyDoi']-used[r['MaLo']]
                if left>0:qualified.append((left,r['DonGiaNhap']))
        if metric=='expiry_lot_count':return len(qualified)
        return sum(left*unit_cost for left,unit_cost in qualified)
    raise ValueError('Unimplemented '+metric)

def audit(pos,db):
    parity=verify_revenue(pos,db)
    report={'shop_id':'dev_006','revenue_source_to_mart_pass':parity['acceptance_pass'],
            'checks':[],'pass':False,'failures':[],'eligible_for_approval':False}
    if not parity['acceptance_pass']:
        report['failures'].append('Revenue acceptance failed')
    with sqlite3.connect(f'file:{Path(pos).resolve()}?mode=ro',uri=True) as source, \
         sqlite3.connect(f'file:{Path(db).resolve()}?mode=ro',uri=True) as mart:
        facts=source_facts(source)
        cat=json.loads(mart.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
        cat['approved_metrics']=list(METRICS)  # in-memory sandbox ONLY, not writing catalog
        checks=[]
        for asof in CHECKPOINTS:
            for start,end in PERIODS:
                if start>asof:continue
                for metric in ('order_count','cancel_rate','gross_profit_by_order_date',
                    'units_sold_base','purchases_by_receipt_date','cash_collected',
                    'returns_count','prescription_revenue'):
                    checks.append((metric,asof,start,end,{}))
                for ingredient in sorted({r['ThanhPhanChinh'] for r in facts['drug'].values()
                                           if r['ThanhPhanChinh']}):
                    checks.append(('ingredient_revenue',asof,start,end,{'ingredient':ingredient}))
                for method in ('cash','transfer'):
                    checks.append(('cash_collected',asof,start,end,{'payment_method':method}))
                checks.append(('supplier_purchase_value',asof,start,end,{'product_id':'NCC001'}))
            for metric in ('receivables_as_of','inventory_value_as_of','stockout_product_count',
                           'expiry_lot_count','expiry_lot_cost_vnd'):
                args={'product_id':30} if metric.startswith('expiry_lot') else {}
                checks.append((metric,asof,None,None,args))
            for sku in ('SP0001','SP0002'):
                checks.append(('stock_units_as_of',asof,None,None,{'product_id':sku}))
                checks.append(('selling_price_as_of',asof,None,None,{'product_id':sku}))
        for metric,asof,start,end,kwargs in checks:
            params=dict(as_of_date=asof,start_date=start,end_date=end,**kwargs)
            try:
                expected=source_expected(facts,metric,asof=asof,start=start,end=end,**kwargs)
                observed=calculate(mart,cat,metric,**params)
                passed=expected==observed
                if not passed:
                    report['failures'].append(f'{metric} {asof} {start}..{end} {kwargs}: source={expected} mart={observed}')
            except Exception as exc:
                passed=False
                report['failures'].append(f'{metric} {asof} {start}..{end} {kwargs}: {type(exc).__name__}: {exc}')
            report['checks'].append({'metric':metric,'as_of_date':asof,'period':[start,end],
                                    'params':kwargs,'pass':passed})
    report['test_count']=len(report['checks'])
    report['passed_count']=sum(r['pass'] for r in report['checks'])
    report['failure_count']=len(report['failures'])
    report['pass']=not report['failures'] and report['test_count']>0
    report['eligible_for_approval']=report['pass']
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--pos',required=True,type=Path)
    p.add_argument('--db',required=True,type=Path)
    p.add_argument('--report',required=True,type=Path)
    a=p.parse_args()
    result=audit(a.pos,a.db)
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='checks'},
                     ensure_ascii=False,indent=2)[:20000])
    if not result['pass']:raise SystemExit(2)

if __name__=='__main__':main()
