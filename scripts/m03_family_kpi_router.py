"""One fail-closed M03 KPI entrance for approved family-specific datasets.

Each shop declares an explicit approved_metrics capability set. No fallback
guessing: unsupported or candidate metrics are NotApprovedForKPI, never zero.
"""
from scripts.m03_consumer import NotApprovedForKPI,open_business_dataset,query_shop_revenue
from scripts.dev006_extended_kpis import METRICS as PHARMACY_METRICS
from scripts.dev006_extended_kpis import calculate as pharmacy_calculate
from scripts.dev001_semantic_release import METRICS as RETAIL_METRICS
from scripts.dev001_semantic_release import query_kpi as retail_query
from scripts.dev009_semantic_release import APPROVED as INVOICE_METRICS
from scripts.dev009_semantic_release import query_kpi as invoice_query
from scripts.dev012_semantic_release import APPROVED as SERVICE_METRICS
from scripts.dev012_semantic_release import query_kpi as service_query

FAMILIES={
 'dev_001':('retail_single_export',set(RETAIL_METRICS),retail_query),
 'dev_009':('invoice_summary_only',set(INVOICE_METRICS),invoice_query),
 'dev_012':('motorcycle_service_ledger',set(SERVICE_METRICS),service_query)
}

def query_approved_kpi(sqlite_path,metric,*,as_of_date,start_date=None,
                       end_date=None,product_id=None,ingredient=None,
                       payment_method=None):
    """Read a single typed KPI from an APPROVED business dataset.

    Date periods are inclusive; a source-only or unanswerable metric must
    raise instead of silently returning zero. The caller owns date parsing.
    """
    db,cat=open_business_dataset(sqlite_path)
    try:
        shop=cat['shop_id']
        if metric not in cat.get('approved_metrics',[]):
            raise NotApprovedForKPI(shop+': '+metric+' not approved')
        if shop=='dev_006':
            if metric=='revenue_by_order_date':
                if start_date is None or end_date is None:
                    raise ValueError('Period required for revenue')
                return query_shop_revenue(db,cat,start_date=start_date,
                    end_date=end_date,as_of_date=as_of_date)
            if metric not in PHARMACY_METRICS:
                raise NotApprovedForKPI('Unknown dev006 metric '+metric)
            return pharmacy_calculate(db,cat,metric,as_of_date=as_of_date,
                start_date=start_date,end_date=end_date,product_id=product_id,
                ingredient=ingredient,payment_method=payment_method)
        family=FAMILIES.get(shop)
        if family is None:raise NotApprovedForKPI(shop+': no approved family adapter')
        family_name,metrics,func=family
        if cat.get('family')!=family_name:
            raise NotApprovedForKPI(shop+': family mismatch')
        if metric not in metrics:
            raise NotApprovedForKPI(shop+': unsupported KPI '+metric)
        if any(x is not None for x in (product_id,ingredient,payment_method)):
            raise ValueError('Unsupported parameter for '+shop+' KPI: '+metric)
        return func(db,metric,as_of_date=as_of_date,
                    start_date=start_date,end_date=end_date)
    finally:
        db.close()
