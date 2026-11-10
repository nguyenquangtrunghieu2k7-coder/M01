#!/usr/bin/env python3
"""dev_009 invoice-summary semantic acceptance and scoped production release.

Read-only source and candidate; derived SQLite is a separate release.
Rulebook §§1,2,4,8: revenue uses Giá trị hàng; no fabricated invoice lines.
The 540 daily subtotals are not orders; exact duplicate invoice export copies
are retained in staging, and counted only once as real invoices.
"""
import argparse,csv,datetime as dt,hashlib,json,re,shutil,sqlite3,sys
from collections import Counter
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4

SHOP='dev_009'
STATUS={'Xong':'completed','Đang giao dịch':'shipping','hủy đơn':'cancelled','trả hàng':'returned'}
APPROVED=('invoice_revenue','eligible_order_count','cancel_rate','current_debt_snapshot')

def money(value):
    if value is None:raise ValueError('missing VND')
    s=str(value).strip().replace(' ','')
    if not re.fullmatch(r'[+-]?(?:\d+|\d{1,3}(?:[,.]\d{3})+)',s):
        raise ValueError('ambiguous VND '+repr(value))
    return int(s.replace(',','').replace('.',''))

def day(value):
    s=str(value or '').strip()
    for fmt in ('%d/%m/%Y','%Y-%m-%d','%Y-%m-%d %H:%M:%S'):
        try:return dt.datetime.strptime(s,fmt).date().isoformat()
        except ValueError:pass
    raise ValueError('invalid invoice date '+repr(value))

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1048576),b''):h.update(chunk)
    return h.hexdigest()

def source_rows(path):
    """Classify every physical row; reject same ID with conflicting facts."""
    invoices=[];summaries=[];copies=[];errors=[];seen={}
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        fields=list(reader.fieldnames or [])
        mandatory={'Ngày tháng','Trạng thái đơn','TongTien','Mã hóa đơn','Nợ',
                   'Đã thu','Đối tác','Giá trị hàng'}
        if not mandatory.issubset(fields):raise ValueError('Missing invoice columns')
        for rn,raw in enumerate(reader,2):
            code=(raw.get('Mã hóa đơn') or '').strip()
            if not code:
                if (raw.get('Đối tác') or '').strip().lower().startswith('tổng ngày'):
                    summaries.append(rn)
                else:errors.append(f'row {rn}: missing invoice ID not a daily subtotal')
                continue
            try:
                if code in seen:
                    origin,original=seen[code]
                    if raw!=original:raise ValueError('same invoice ID has conflicting contents')
                    copies.append((rn,origin));continue
                status=STATUS[raw['Trạng thái đơn']]
                entry={'source_row':rn,'code':code,'date':day(raw['Ngày tháng']),
                  'status':status,'revenue_vnd':money(raw['Giá trị hàng']),
                  'total_vnd':money(raw['TongTien']),
                  'paid_snapshot_vnd':money(raw['Đã thu']),
                  'debt_snapshot_vnd':money(raw['Nợ']),'raw':raw}
                invoices.append(entry)
                seen[code]=(rn,raw)
            except (ValueError,KeyError) as exc:
                errors.append(f'row {rn}: {exc}')
    return fields,invoices,summaries,copies,errors

def totals(invoices):
    eligible=[r for r in invoices if r['status'] in ('completed','shipping')]
    cancelled=sum(r['status']=='cancelled' for r in invoices)
    percent=(Decimal(100)*cancelled/len(invoices)).quantize(
        Decimal('.01'),rounding=ROUND_HALF_UP) if invoices else Decimal(0)
    return {'invoice_count':len(invoices),'eligible_order_count':len(eligible),
      'cancelled_order_count':cancelled,
      'returned_order_count':sum(r['status']=='returned' for r in invoices),
      'eligible_revenue_vnd':sum(r['revenue_vnd'] for r in eligible),
      'cancel_rate_percent':float(percent),
      'current_debt_snapshot_vnd':sum(max(0,r['debt_snapshot_vnd'])
                                     for r in invoices if r['status']!='cancelled')}

def acceptance(source,candidate):
    fields,invoices,summaries,copies,errors=source_rows(source)
    expected=totals(invoices)
    with sqlite3.connect(f'file:{Path(candidate).resolve()}?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            errors.append('candidate SQLite integrity failure')
        catrows=db.execute('SELECT catalog_json FROM business_catalog').fetchall()
        if len(catrows)!=1:raise ValueError('Expected one business catalog')
        catalog=json.loads(catrows[0][0])
        if catalog.get('shop_id')!=SHOP or catalog.get('approval_status')!='CANDIDATE_NOT_APPROVED':
            errors.append('wrong shop or unauthorized original approval')
        srcrows=db.execute("SELECT source_id,source_sha256 FROM raw_sources WHERE shop_id=? AND source_object=?",
                           (SHOP,'danh_sach_hoa_don')).fetchall()
        if len(srcrows)!=1:errors.append('missing/ambiguous physical CSV source')
        else:
            sid,source_hash=srcrows[0]
            if source_hash!=sha(source):errors.append('source SHA differs from candidate original')
            staged={rn:raw for rn,raw in db.execute(
                'SELECT source_row,raw_json FROM staging_rows WHERE source_id=?',(sid,))}
            all_ids={r['source_row'] for r in invoices}|set(summaries)|{rn for rn,_ in copies}
            if set(staged)!=all_ids:errors.append('physical CSV-to-staging row coverage mismatch')
            # Validate every physical value; staging must not be rewritten by KPI preparation.
            with Path(source).open(encoding='utf-8-sig',newline='') as stream:
                reader=csv.DictReader(stream)
                for rn,raw in enumerate(reader,2):
                    stored=staged.get(rn)
                    if stored is None:continue
                    obj=json.loads(stored)
                    original=list(raw.values())
                    # The canonical raw preservation column tags are 0:Name, 1:Name...
                    if any(str(obj.get(f'{i}:{col}') or '')!=str(value or '')
                           for i,(col,value) in enumerate(zip(fields,original))):
                        errors.append(f'raw row mismatch {rn}')
                        if len(errors)>=20:break
            physical_mart={r[0]:r[1] for r in db.execute(
                "SELECT source_row,source_business_id FROM orders WHERE shop_id=? AND source_id=?",
                (SHOP,sid))}
            expected_mart={r['source_row']:r['code'] for r in invoices}
            for rn,origin in copies:expected_mart[rn]=expected_mart[origin]
            if physical_mart!=expected_mart:
                errors.append('order mart physical rows differ from source invoice/copies')
            if any(rn in physical_mart for rn in summaries):
                errors.append('daily subtotal wrongly entered order mart')
            if db.execute("SELECT COUNT(*) FROM order_lines WHERE shop_id=?",(SHOP,)).fetchone()[0]:
                errors.append('fabricated invoice line exists in summary-only shop')
        return {'shop_id':SHOP,'family':'invoice_summary_only',
          'source_invoice_rows':len(invoices)+len(copies),
          'unique_invoice_count':len(invoices),
          'daily_subtotals_not_orders':len(summaries),
          'identical_export_duplicate_copies':len(copies),
          'original_staging_rows':len(invoices)+len(summaries)+len(copies),
          'kpis':expected,'accepted':not errors,'errors':errors[:30],
          'error_count':len(errors),'production_approved':False}

def query_kpi(db,metric,*,start_date=None,end_date=None,as_of_date):
    catalog=json.loads(db.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
    if (catalog.get('shop_id')!=SHOP or catalog.get('approval_status')!='PRODUCTION_APPROVED'
        or metric not in catalog.get('approved_metrics',[])):
        raise ValueError('Not approved for KPI')
    if metric=='current_debt_snapshot':
        source_last=db.execute('SELECT MAX(order_date) FROM family_invoice_facts').fetchone()[0]
        if as_of_date!=source_last:
            raise ValueError('Unanswerable: only last source debt snapshot is supplied')
        return db.execute("""SELECT COALESCE(SUM(MAX(0,debt_snapshot_vnd)),0)
          FROM family_invoice_facts WHERE status!='cancelled'""").fetchone()[0]
    if metric not in ('invoice_revenue','eligible_order_count','cancel_rate'):
        raise ValueError('Unsupported KPI')
    if start_date is None or end_date is None:raise ValueError('Period is required')
    start=dt.date.fromisoformat(start_date)
    end=dt.date.fromisoformat(end_date)
    cutoff=dt.date.fromisoformat(as_of_date)
    if end<start:raise ValueError('Negative period')
    earliest,latest=db.execute('SELECT MIN(order_date),MAX(order_date) FROM family_invoice_facts').fetchone()
    if end.isoformat()<earliest or start.isoformat()>latest or start>cutoff:
        raise ValueError('Unanswerable: outside source/as-of coverage')
    upper=min(end,cutoff).isoformat()
    rows=db.execute('SELECT status,revenue_vnd FROM family_invoice_facts WHERE order_date BETWEEN ? AND ?',
                    (start.isoformat(),upper)).fetchall()
    if metric=='invoice_revenue':
        return sum(n for status,n in rows if status in ('completed','shipping'))
    if metric=='eligible_order_count':
        return sum(status in ('completed','shipping') for status,n in rows)
    if not rows:return 0.0
    return float((Decimal(100)*sum(status=='cancelled' for status,n in rows)/len(rows)).
                 quantize(Decimal('.01'),rounding=ROUND_HALF_UP))

def publish(source,candidate,out,approver):
    source=Path(source);candidate=Path(candidate);out=Path(out)
    if out.exists():raise ValueError('Refusing to overwrite release directory')
    report=acceptance(source,candidate)
    if not report['accepted']:raise ValueError('QA blocked: '+repr(report['errors'][:8]))
    fields,invoices,summaries,copies,errors=source_rows(source)
    out.mkdir(parents=True,exist_ok=False)
    (out/'qa_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    target=out/'dev_009.sqlite'
    shutil.copy2(candidate,target)
    with sqlite3.connect(target) as db:
        cat=json.loads(db.execute('SELECT catalog_json FROM business_catalog').fetchone()[0])
        db.execute('''CREATE TABLE family_invoice_facts(
            invoice_code TEXT PRIMARY KEY,source_row INTEGER UNIQUE,order_date TEXT NOT NULL,
            status TEXT NOT NULL,revenue_vnd INTEGER NOT NULL,
            total_vnd INTEGER NOT NULL,debt_snapshot_vnd INTEGER NOT NULL,
            paid_snapshot_vnd INTEGER NOT NULL)''')
        db.executemany('INSERT INTO family_invoice_facts VALUES(?,?,?,?,?,?,?,?)',
            [(r['code'],r['source_row'],r['date'],r['status'],r['revenue_vnd'],
              r['total_vnd'],r['debt_snapshot_vnd'],r['paid_snapshot_vnd']) for r in invoices])
        db.executemany("DELETE FROM orders WHERE shop_id=? AND source_row=?",
                       [(SHOP,rn) for rn,origin in copies])
        db.executemany("""UPDATE orders SET event_date=?,amount=?,status_raw=?
            WHERE shop_id=? AND source_row=?""",
            [(r['date'],str(r['revenue_vnd']),r['status'],SHOP,r['source_row']) for r in invoices])
        sid=db.execute("SELECT source_id FROM raw_sources WHERE shop_id=?",(SHOP,)).fetchone()[0]
        db.executemany('INSERT INTO duplicate_source_rows VALUES(?,?,?,?,?,?,?)',
            [('dev009:'+str(rn),SHOP,sid,rn,origin,'orders',cat['version_id'])
             for rn,origin in copies])
        cat['validation_status']='APPROVED'
        cat['approval_status']='PRODUCTION_APPROVED'
        cat['approved_metrics']=list(APPROVED)
        cat['row_counts']['orders']=len(invoices)
        cat['duplicate_row_counts']=dict(cat.get('duplicate_row_counts',{}),orders=len(copies))
        cat['approved_by']=approver
        cat['approved_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
        cat['approval_evidence']='qa_report.json'
        cat['metric_notes']={'current_debt_snapshot':'Only valid at last covered source date',
                             'invoice_revenue':'Giá trị hàng, eligible statuses, order date'}
        db.execute('UPDATE business_catalog SET catalog_json=?',(json.dumps(cat,ensure_ascii=False),))
        db.execute("UPDATE dataset_versions SET status='APPROVED' WHERE shop_id=?",(SHOP,))
        db.commit()
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Release SQLite integrity failed')
        date_first,date_last=db.execute('SELECT MIN(order_date),MAX(order_date) FROM family_invoice_facts').fetchone()
        k=report['kpis']
        assert query_kpi(db,'invoice_revenue',start_date=date_first,end_date=date_last,
                         as_of_date=date_last)==k['eligible_revenue_vnd']
        assert query_kpi(db,'eligible_order_count',start_date=date_first,end_date=date_last,
                         as_of_date=date_last)==k['eligible_order_count']
        assert query_kpi(db,'current_debt_snapshot',as_of_date=date_last)==k['current_debt_snapshot_vnd']
    manifest={'shop_id':SHOP,'family':'invoice_summary_only','release_id':str(uuid4()),
       'source_dataset_version':cat['version_id'],'approval_status':'PRODUCTION_APPROVED',
       'approved_metrics':list(APPROVED),'approved_by':approver,
       'approved_at_utc':cat['approved_at_utc'],'source_sha256':sha(source),
       'candidate_sha256':sha(candidate),'database_sha256':sha(target),
       'unique_invoices':len(invoices),'excluded_daily_subtotals':len(summaries),
       'excluded_duplicate_invoice_copies':len(copies),
       'revenue_vnd':report['kpis']['eligible_revenue_vnd'],
       'excluded_metrics':['item_sales','inventory','gross_profit','historical_debt'],
       'files':['dev_009.sqlite','qa_report.json','manifest.json']}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path)
    p.add_argument('--approve',action='store_true')
    p.add_argument('--approved-by',default='')
    args=p.parse_args()
    try:
        if args.approve:
            if not args.approved_by.strip():p.error('Human approver required')
            result=publish(args.source,args.candidate,args.output,args.approved_by)
        else:
            result=acceptance(args.source,args.candidate)
            if args.report:
                args.report.parent.mkdir(parents=True,exist_ok=True)
                args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if (not args.approve) and not result['accepted']:raise SystemExit(2)
    except (ValueError,sqlite3.Error) as e:
        print('DEV009 RELEASE BLOCKED:',str(e),file=sys.stderr)
        raise SystemExit(2)

if __name__=='__main__':main()
