"""dev_009 summary-only source: no inferred SKU, order lines or cashflows."""
import csv
import datetime as dt
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

STATUSES={'Xong':'completed','Đang giao dịch':'shipping','hủy đơn':'cancelled','trả hàng':'returned'}

def money(value):
    s=str(value).strip().replace(' ','')
    if not re.fullmatch(r'[+-]?(?:\d+|\d{1,3}(?:,\d{3})+|\d{1,3}(?:\.\d{3})+)',s):
        raise ValueError('Invalid VND amount: '+repr(value))
    return int(Decimal(s.replace(',','').replace('.','')))

def day(value):
    s=str(value).strip()
    for fmt in ('%d/%m/%Y','%Y-%m-%d','%Y-%m-%d %H:%M:%S'):
        try:return dt.datetime.strptime(s,fmt).date().isoformat()
        except ValueError:pass
    raise ValueError('Invalid date: '+repr(value))

def source_facts(path):
    """Keep ALL physical rows in staging; count identical invoices once only."""
    invoices=[];subtotals=[];duplicates=[];failures=[];seen={}
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        for rn,row in enumerate(csv.DictReader(stream),start=2):
            code=(row.get('Mã hóa đơn') or '').strip()
            if not code:
                if (row.get('Đối tác') or '').strip().lower().startswith('tổng ngày'):
                    subtotals.append(rn)
                else:failures.append(f'row {rn}: missing ID and not a daily subtotal')
                continue
            try:
                if code in seen:
                    if row!={k:v for k,v in seen[code].items() if k!='_row'}:
                        raise ValueError('duplicate invoice code with conflicting fields')
                    duplicates.append((rn,seen[code]['_row']))
                    continue
                seen[code]=dict(row,_row=rn)
                invoices.append({'source_row':rn,'invoice_code':code,
                   'event_date':day(row['Ngày tháng']),
                   'status':STATUSES[row['Trạng thái đơn']],
                   'revenue_vnd':money(row['Giá trị hàng']),
                   'total_vnd':money(row['TongTien']),
                   'debt_at_source_snapshot_vnd':money(row['Nợ'])})
            except (ValueError,KeyError) as e:failures.append(f'row {rn}: {e}')
    return invoices,subtotals,duplicates,failures

def kpis(rows):
    valid=[r for r in rows if r['status'] in ('completed','shipping')]
    cancelled=sum(r['status']=='cancelled' for r in rows)
    return {'orders_all':len(rows),'orders_eligible':len(valid),
        'orders_cancelled':cancelled,
        'orders_returned':sum(r['status']=='returned' for r in rows),
        'revenue_vnd':sum(r['revenue_vnd'] for r in valid),
        'cancel_rate_percent':float((Decimal(100)*cancelled/len(rows)).quantize(
           Decimal('.01'),rounding=ROUND_HALF_UP)) if rows else 0.0,
        'debt_at_source_snapshot_vnd':sum(max(0,r['debt_at_source_snapshot_vnd'])
           for r in rows if r['status']!='cancelled')}

def query_period(db,metric,start_date,end_date,as_of_date):
    """Only approved invoice metrics; inclusive as-of and source coverage."""
    import json
    approved={'revenue_vnd','orders_eligible','cancel_rate_percent'}
    if metric not in approved:raise ValueError('Unsupported period metric')
    cat=json.loads(db.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
    if cat.get('shop_id')!='dev_009' or metric not in cat.get('approved_metrics',[]):
        raise ValueError('Metric not approved')
    start=dt.date.fromisoformat(start_date);end=dt.date.fromisoformat(end_date)
    cutoff=dt.date.fromisoformat(as_of_date)
    if start>end:raise ValueError('Invalid interval')
    bounds=db.execute('SELECT MIN(event_date),MAX(event_date) FROM family_invoice_facts').fetchone()
    if not bounds[0] or start>cutoff or start.isoformat()>bounds[1] or end.isoformat()<bounds[0]:
        raise ValueError('Unanswerable: outside source coverage')
    observed=db.execute("""SELECT status,revenue_vnd FROM family_invoice_facts
        WHERE event_date BETWEEN ? AND ?""",
        (start.isoformat(),min(end,cutoff).isoformat())).fetchall()
    valid=[r for r in observed if r[0] in ('completed','shipping')]
    if metric=='revenue_vnd':return sum(r[1] for r in valid)
    if metric=='orders_eligible':return len(valid)
    return float((Decimal(100)*sum(r[0]=='cancelled' for r in observed)/len(observed)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if observed else 0.0
