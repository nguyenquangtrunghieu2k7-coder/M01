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
    'prescription_revenue','ingredient_revenue','returns_count',
    'supplier_purchase_value','stockout_product_count','expiry_lot_count',
    'expiry_lot_cost_vnd','selling_price_as_of'
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
    """Parse POS cash strings: 1,086tr == 1_086_000 VND.

    The tr suffix denotes a decimal number of millions, whereas
    dot-grouped plain đ values use thousands groups. Fail on ambiguity.
    """
    if isinstance(value,(int,float,Decimal)):return _vnd(value)
    if not isinstance(value,str):raise ValueError('Missing receipt amount')
    s=value.strip().lower().replace(' ','').replace('₫','').replace('đ','')
    embedded=re.fullmatch(r'([+-]?\\d+)tr(\\d{1,3})',s)
    if embedded:
        # POS convention: 2tr638 = 2.638 million VND.
        amount=Decimal(embedded.group(1)+'.'+embedded.group(2))*1000000
    elif s.endswith('tr'):
        base=s[:-2]
        if not re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?',base):
            raise ValueError('Ambiguous POS million amount: '+repr(value))
        amount=Decimal(base.replace(',','.'))*1000000
    elif s.endswith('k'):
        base=s[:-1]
        if not re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?',base):
            raise ValueError('Ambiguous POS thousand amount: '+repr(value))
        amount=Decimal(base.replace(',','.'))*1000
    else:
        if not re.fullmatch(r'[+-]?(?:\d+|\d{1,3}(?:\.\d{3})+)',s):
            raise ValueError('Ambiguous POS receipt money format: '+repr(value))
        amount=Decimal(s.replace('.',''))
    if amount!=amount.to_integral_value():
        raise ValueError('Non-integer VND amount: '+repr(value))
    return int(amount)

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
    period_metric=metric not in {'receivables_as_of','stock_units_as_of','inventory_value_as_of',
        'stockout_product_count','expiry_lot_count','expiry_lot_cost_vnd','selling_price_as_of'}
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
        if payment_method is None:payment_method='cash'
        total=0
        for raw,day in _rows(db,'payments'):
            payment_day=str(raw['NgayGioThu'])[:10]
            if _within(payment_day,first,last):
                if payment_method is None or raw['PhuongThuc']==payment_method:
                    total+=_receipt(raw['SoTienThu'])
        return total
    if metric=='returns_count':
        count=0
        for raw,day in _rows(db,'orders'):
            if _within(day,first,last) and raw.get('TinhTrang')=='returned':
                count+=1
        return count
    if metric=='supplier_purchase_value':
        if product_id is None:raise ValueError('Pass supplier code as product_id for this metric')
        total=0
        for raw,day in _rows(db,'purchase_receipts'):
            if _within(day,first,last) and raw.get('TinhTrang') not in ('cancelled','canceled'):
                if str(raw.get('MaNhaCungCap'))==str(product_id):
                    total+=_vnd(raw['TongGiaTriNhap'])
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
    if metric=='stockout_product_count':
        last_stock={}
        for raw,day in _rows(db,'inventory_events'):
            t=str(raw.get('NgayGioPhatSinh') or '')
            if t[:10]>cut.isoformat():continue
            sku=str(raw['MaHangHoa'])
            key=(t,str(raw['MaGiaoDichKho']))
            if sku not in last_stock or key>last_stock[sku][0]:
                last_stock[sku]=(key,_vnd(raw['TonCuoi']))
        if not last_stock:raise UnanswerableKPI('No stock snapshots by as_of_date')
        return sum(qty==0 for _,qty in last_stock.values())
    if metric=='selling_price_as_of':
        if product_id is None:raise ValueError('selling_price_as_of requires product_id')
        selected=None
        for attrs,day in db.execute("""SELECT attributes_json,event_date
                FROM price_history WHERE shop_id='dev_006'"""):
            raw=json.loads(attrs)['source_values']
            if str(raw.get('MaHangHoa'))!=str(product_id):continue
            effective=str(raw.get('NgayApDung') or day or '')[:10]
            if effective and effective<=cut.isoformat():
                if selected is None or effective>=selected[0]:
                    selected=(effective,_vnd(raw['GiaBanLe']))
        if selected is None:raise UnanswerableKPI('No documented price at as_of_date')
        return selected[1]
    if metric in {'expiry_lot_count','expiry_lot_cost_vnd'}:
        if not isinstance(product_id,int) or product_id<0:
            raise ValueError('Expiry metrics require nonnegative days_ahead in product_id')
        horizon=cut+timedelta(days=product_id)
        orders={}
        for raw,day in _rows(db,'orders'):
            orders[str(raw['MaHoaDon'])]=str(raw['ThoiGianLap'])[:10]
        returns={}
        for attrs,_ in db.execute("""SELECT attributes_json,event_date
                FROM returns WHERE shop_id='dev_006'"""):
            raw=json.loads(attrs)['source_values']
            oid=str(raw['MaHoaDon']);return_day=str(raw['NgayGioTra'])[:10]
            if oid not in returns or return_day<returns[oid]:
                returns[oid]=return_day
        lot_use={}
        for attrs,_ in db.execute("""SELECT attributes_json,event_date
                FROM lot_allocations WHERE shop_id='dev_006'"""):
            raw=json.loads(attrs)['source_values'];lot=str(raw['MaLo'])
            purchased=orders.get(str(raw['MaHoaDon']))
            if purchased is None:raise UnanswerableKPI('Missing order for lot allocation')
            if purchased<=cut.isoformat():
                lot_use[lot]=lot_use.get(lot,0)+_vnd(raw['SLQuyDoi'])
            returned=returns.get(str(raw['MaHoaDon']))
            if returned is not None and returned<=cut.isoformat():
                lot_use[lot]=lot_use.get(lot,0)-_vnd(raw['SLTraQuyDoi'])
        receipt_dates={}
        for raw,day in _rows(db,'purchase_receipts'):
            receipt_dates[str(raw['MaPhieuNhap'])]=day
        count=0;money=0
        for attrs,_ in db.execute("""SELECT attributes_json,event_date
                FROM lots WHERE shop_id='dev_006'"""):
            raw=json.loads(attrs)['source_values']
            receive=receipt_dates.get(str(raw['MaPhieuNhap']))
            if receive is None:raise UnanswerableKPI('Missing receipt date for lot')
            expiry=date.fromisoformat(str(raw['HanSuDung'])[:10])
            if receive<=cut.isoformat() and cut<=expiry<=horizon:
                qty=_vnd(raw['SLNhapQuyDoi'])-lot_use.get(str(raw['MaLo']),0)
                if qty>0:
                    count+=1;money+=qty*_vnd(raw['DonGiaNhap'])
        return count if metric=='expiry_lot_count' else money
    raise UnanswerableKPI('Metric implementation is not available')
