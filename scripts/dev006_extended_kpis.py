"""Family-scoped M03 KPI queries for dev_006 pharmacy POS.

Read only approved metrics. Sqlite mart source_values are recorded from the
actual POS columns; no synthetic transaction joins or inferred receipts.
All returned money values are integer VND.
"""
import json
import re
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from scripts.m03_consumer import NotApprovedForKPI, UnanswerableKPI

METRICS = (
    'order_count','cancel_rate','gross_profit_by_order_date',
    'units_sold_base','purchases_by_receipt_date','cash_collected',
    'receivables_as_of','stock_units_as_of','inventory_value_as_of',
    'prescription_revenue','ingredient_revenue'
)
ELIGIBLE = ('completed','shipping')

def _check(db,cat,metric,as_of,start=None,end=None):
    if cat.get('shop_id')!='dev_006':
        raise NotApprovedForKPI('Only pharmacy_pos dev_006 is supported')
    if metric not in METRICS or metric not in cat.get('approved_metrics',[]):
        raise NotApprovedForKPI(f'{metric} not explicitly approved in this release')
    cut=date.fromisoformat(as_of)
    if start is not None:
        first=date.fromisoformat(start);last=date.fromisoformat(end)
        if first>last:raise ValueError('start after end')
    else:first=last=None
    bounds=db.execute("SELECT MIN(event_date),MAX(event_date) FROM orders WHERE shop_id='dev_006'").fetchone()
    if not bounds or not bounds[0] or not bounds[1]:
        raise UnanswerableKPI('No published shop coverage')
    lo=date.fromisoformat(bounds[0]);hi=date.fromisoformat(bounds[1])
    if cut<lo:raise UnanswerableKPI('As-of precedes source coverage')
    if first is not None:
        if first>cut or last<lo or first>hi:
            raise UnanswerableKPI('Interval outside published data')
        last=min(last,cut,hi)
        first=max(first,lo)
    return cut,first,last

def _rows(db,table,where='',args=()):
    allowed={'orders','order_lines','payments','purchase_receipts',
             'inventory_events','products','source_reference_records'}
    if table not in allowed:raise ValueError('Unsupported table')
    if table=='source_reference_records':
        query="SELECT raw_json,event_date FROM (SELECT raw_json,NULL AS event_date FROM source_reference_records WHERE shop_id='dev_006')"
    else:
        query=f"SELECT attributes_json,event_date FROM {table} WHERE shop_id='dev_006'"
    if where:query+=' AND '+where if table!='source_reference_records' else ' WHERE '+where
    for raw,day in db.execute(query,args):
        obj=json.loads(raw)
        if table=='source_reference_records':
            yield ({key.split(':',1)[-1]:value for key,value in obj.items()},day)
        else:
            yield (obj['source_values'],day)

def _num(value):
    if value is None:raise ValueError('Required numeric source field missing')
    if isinstance(value,bool):raise ValueError('Boolean not numeric')
    try:
        result=Decimal(str(value))
        if not result.is_finite():raise ValueError('Invalid decimal')
        return result
    except Exception as e:raise ValueError(f'Invalid source number: {value!r}') from e

def _vnd(value):
    val=_num(value)
    if val!=val.to_integral_value():raise ValueError('Money is not integer VND')
    return int(val)

def _receipt(value):
    if isinstance(value,(int,float)):return _vnd(value)
    if not isinstance(value,str):raise ValueError('Missing receipt amount')
    cleaned=value.strip().replace('đ','').replace('₫','').replace(' ','')
    if not re.fullmatch(r'[-+]?\d{1,3}(?:[.]\d{3})*|[-+]?\d+',cleaned):
        raise ValueError('Ambiguous POS receipt money format: '+repr(value))
    return int(cleaned.replace('.',''))

def _within(day,first,last):
    return bool(day and first.isoformat()<=str(day)[:10]<=last.isoformat())

def _money(val):
    if val!=val.to_integral_value():
        return int(val.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    return int(val)

def calculate(db,cat,metric,*,as_of_date,start_date=None,end_date=None,
              product_id=None,ingredient=None,payment_method=None):
    """Return one scoped KPI. Period metrics require start/end ISO dates.

    Only metrics explicitly listed in the release's approved_metrics work.
    All outcomes are computed against the *deduplicated* M01 mart.
    """
    cut,first,last=_check(db,cat,metric,as_of_date,start_date,end_date)
    period_metric=metric not in {'receivables_as_of','stock_units_as_of','inventory_value_as_of'}
    if period_metric and (first is None or last is None):
        raise ValueError('Period KPI requires start_date and end_date')
    if not period_metric and (start_date is not None or end_date is not None):
        raise ValueError('As-of snapshot KPI must not receive period bounds')
    if metric in {'order_count','cancel_rate'}:
        statuses=[raw['TinhTrang'] for raw,day in _rows(db,'orders') if _within(day,first,last)]
        if metric=='order_count':return sum(x in ELIGIBLE for x in statuses)
        return float((Decimal(100)*sum(x=='cancelled' for x in statuses)/len(statuses)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if statuses else 0.0
    if metric in {'gross_profit_by_order_date','units_sold_base','prescription_revenue','ingredient_revenue'}:
        drug=None
        if metric in {'prescription_revenue','ingredient_revenue'}:
            drug={}
            for raw,_ in _rows(db,'source_reference_records'):
                if 'MaHangHoa' in raw and 'BanTheoDon' in raw:
                    drug[str(raw['MaHangHoa'])]=raw
            if not drug:raise UnanswerableKPI('Pharmacy drug classification not present')
            if metric=='ingredient_revenue' and ingredient is None:
                raise ValueError('ingredient is required, exact catalog compound label')
        total=Decimal(0)
        for raw,day in _rows(db,'order_lines'):
            if not _within(day,first,last):continue
            # status is inherited from the verified header, not line source_values.
            # Read header's decision through joined document/status field below.
        qry="""SELECT l.attributes_json,l.event_date,l.status_raw
            FROM order_lines l WHERE l.shop_id='dev_006' AND l.event_date>=? AND l.event_date<=?
            AND l.status_raw IN ('completed','shipping')"""
        for attrs,day,status in db.execute(qry,(first.isoformat(),last.isoformat())):
            raw=json.loads(attrs)['source_values']
            sku=str(raw['MaHangHoa'])
            if product_id is not None and sku!=str(product_id):continue
            if metric=='gross_profit_by_order_date':
                total+=_num(raw['TriGia'])-_num(raw['SL'])*_num(raw['GiaVonLucBan'])
            elif metric=='units_sold_base':total+=_num(raw['SLQuyDoi'])
            elif metric=='prescription_revenue':
                if str(drug.get(sku,{}).get('BanTheoDon')) in ('1','True','true'):
                    total+=_num(raw['TriGia'])
            elif metric=='ingredient_revenue':
                if drug.get(sku,{}).get('ThanhPhanChinh')==ingredient:
                    total+=_num(raw['TriGia'])
        return _money(total) if metric!='units_sold_base' else float(total)
    if metric=='purchases_by_receipt_date':
        total=0
        for raw,day in _rows(db,'purchase_receipts'):
            if _within(day,first,last) and raw.get('TinhTrang') not in ('cancelled','canceled'):
                total+=_vnd(raw['TongGiaTriNhap'])
        return total
    if metric=='cash_collected':
        total=0
        for raw,day in _rows(db,'payments'):
            payment_day=str(raw['NgayGioThu'])[:10]
            if _within(payment_day,first,last):
                if payment_method is None or raw['PhuongThuc']==payment_method:
                    total+=_receipt(raw['SoTienThu'])
        return total
    if metric=='receivables_as_of':
        settled={}
        for raw,day in _rows(db,'payments'):
            if str(raw['NgayGioThu'])[:10]<=cut.isoformat():
                key=(str(raw['IDCuaHang']),str(raw['MaHoaDon']))
                settled[key]=settled.get(key,0)+_receipt(raw['SoTienThu'])
        debt=0
        for raw,day in _rows(db,'orders'):
            if day is None or day>cut.isoformat() or raw['TinhTrang']=='cancelled':continue
            # COD not customer debt, regardless of payment delays.
            if raw.get('PhuongThucTT')=='cod':continue
            if raw.get('KenhBanHang') in ('marketplace','ecommerce','sàn TMĐT'):
                continue
            key=(str(raw['IDCuaHang']),str(raw['MaHoaDon']))
            left=_vnd(raw['TongThanhToan'])-settled.get(key,0)
            if left>0:debt+=left
        return debt
    if metric in {'stock_units_as_of','inventory_value_as_of'}:
        last_by_sku={}
        for raw,day in _rows(db,'inventory_events'):
            timestamp=str(raw.get('NgayGioPhatSinh') or '')
            if timestamp[:10]>cut.isoformat():continue
            sku=str(raw['MaHangHoa'])
            # One inventory event per source row; latest timestamp + event ID.
            key=(timestamp,str(raw['MaGiaoDichKho']))
            if sku not in last_by_sku or key>last_by_sku[sku][0]:
                last_by_sku[sku]=(key,_vnd(raw['TonCuoi']))
        if not last_by_sku:raise UnanswerableKPI('No stock snapshots by as_of_date')
        if metric=='stock_units_as_of':
            if product_id is None:raise ValueError('stock_units_as_of requires product_id')
            if str(product_id) not in last_by_sku:
                raise UnanswerableKPI('Product has no inventory snapshot')
            return last_by_sku[str(product_id)][1]
        costs={str(raw['MaHangHoa']):_vnd(raw['GiaVonHang'])
               for raw,day in _rows(db,'products')}
        if any(sku not in costs for sku in last_by_sku):
            raise UnanswerableKPI('Inventory missing product base cost')
        return sum(qty*costs[sku] for sku,(_,qty) in last_by_sku.items() if qty>0)
    raise UnanswerableKPI('Metric implementation is not available')
