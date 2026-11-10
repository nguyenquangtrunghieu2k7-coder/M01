"""Business-family semantics for the 13 non-dev006 DataMate shops.

Policies are descriptive constraints for mapping and QA; no policy gives
approval to invent source values, orders, transactions or official KPIs.
"""
POLICIES={
 'dev_001':{
   'grain':'order_line','fact_roles':['order_lines'],
   'identity':'Shop-scoped source order ID; totals repeated on lines count once per order',
   'special':'Explicit product catalog; discounts follow line-level TriGia where supported',
   'forbid':['sum_repeated_order_header_amount','fabricate_order_when_missing']},
 'dev_002':{
   'grain':'monthly_order_line','fact_roles':['order_lines'],
   'identity':'Source invoice identity scoped by shop plus documented month/file if codes reused',
   'special':'17 monthly files; join products by validated names and per-product unit conversion',
   'forbid':['global_name_merge_without_alias_validation','common_conversion_factor']},
 'dev_003':{
   'grain':'cafe_order_line_and_cash_event',
   'fact_roles':['order_lines','payments','cash_shift','purchase_lines','expenses'],
   'identity':'Shop-scoped invoice; cash_shift is a separate payment-time grain',
   'special':'Toppings are separately saleable; shifts use receipt timestamps and cash only',
   'forbid':['count_cash_shift_as_order_revenue','duplicate_order_total_per_line']},
 'dev_004':{
   'grain':'construction_order_line_and_delivery_trip',
   'fact_roles':['order_lines','deliveries','purchase_lines','inventory_snapshots'],
   'identity':'Order lines by month; delivery trip by order and each delivery occurrence',
   'special':'Multiple deliveries per order; debt and inventory snapshots have as-of dates',
   'forbid':['count_delivery_trip_as_sale','merge_distinct_delivery_occurrences']},
 'dev_005':{
   'grain':'pharmacy_excel_line_and_lot',
   'fact_roles':['order_lines','purchase_receipts','purchase_lines','lot_allocations'],
   'identity':'Line-level order and lot allocation must retain invoice and SKU keys',
   'special':'Pharmacy products/compounds and lot expiry are distinct reference grains',
   'forbid':['treat_lot_allocation_as_extra_sale','infer_medicine_expiry_without_lot']},
 'dev_007':{
   'grain':'restaurant_csv_order_line',
   'fact_roles':['order_lines','purchase_lines'],
   'identity':'Invoice ID, one source row per sold product',
   'special':'Purchase detail separate from sale lines; product catalog joins by SKU',
   'forbid':['sum_repeated_order_amount_per_line','invent_order_headers']},
 'dev_008':{
   'grain':'restaurant_excel_order_line',
   'fact_roles':['order_lines','purchase_lines'],
   'identity':'Invoice ID plus source file/row for line identity',
   'special':'Two split sales exports; merge per verified business key, preserving source lineage',
   'forbid':['treat_split_export_as_disjoint_invoice_ids','invent_order_headers']},
 'dev_009':{
   'grain':'invoice_summary_only',
   'fact_roles':['orders'],
   'identity':'One row equals one invoice (no SKU detail)',
   'special':'Only invoice-level financial metrics when fields and semantics explicitly support them',
   'forbid':['fabricate_order_lines','invent_product_ranking','infer_skus_from_invoice_total']},
 'dev_010':{
   'grain':'linked_csv_order_and_line',
   'fact_roles':['orders','order_lines','payments'],
   'identity':'Use explicit source invoice/SKU foreign keys, confirm uniqueness before joining',
   'special':'Five CSV files for orders, lines, payments, products and customers',
   'forbid':['join_by_ambiguous_name','multiply_header_total_by_line_count']},
 'dev_011':{
   'grain':'mobile_order_line_ledger',
   'fact_roles':['order_lines'],
   'identity':'An STT shared within one documented group; blank continuation rows are not a new order',
   'special':'Abbreviation table normalizes display only, must not merge distinct phone models',
   'forbid':['forward_fill_stt_across_unrelated_groups','guess_invoice_id_from_source_row']},
 'dev_012':{
   'grain':'one_repair_visit_per_row',
   'fact_roles':['service_visits'],
   'identity':'Every ledger row is a repair visit; no invented invoice or service line price',
   'special':'Zero-payment warranty visits still count as visits but not paid jobs',
   'forbid':['turn_visit_text_into_priced_order_lines','exclude_warranty_from_visit_count']},
 'dev_013':{
   'grain':'mother_baby_order_line_or_adjustment',
   'fact_roles':['order_lines_with_adjustments','purchase_lines'],
   'identity':'Invoice grouped within each month; voucher, points and shipping are adjustments',
   'special':'Voucher/points/ship are not products and do not join product rankings',
   'forbid':['count_discount_as_product_revenue','infer_customer_by_name_without_review']},
 'dev_014':{
   'grain':'mobile_multi_ledger_and_financing',
   'fact_roles':['order_lines','trade_ins','receivables','installment_schedules','warranty_visits'],
   'identity':'Sale joins to trade-in/financing by verified invoice/IMEI; not by arbitrary STT alone',
   'special':'Trade-in credit reduces amount due not revenue; installments are debt collections',
   'forbid':['subtract_trade_in_from_revenue','count_installment_payment_as_new_sale']}
}

def policy_for(shop):
    if shop not in POLICIES:raise ValueError('Unknown family: '+str(shop))
    return POLICIES[shop]

def validate_contract(contract):
    shop=contract.get('shop_id')
    policy=policy_for(shop)
    actual={source['candidate_role'] for source in contract.get('source_manifest',[])}
    if not set(policy['fact_roles']).issubset(actual):
        raise ValueError(f'{shop}: required family fact role absent: '
                         f"{set(policy['fact_roles'])-actual}")
    if contract.get('approval_status')!='CANDIDATE_NOT_APPROVED':
        raise ValueError('Family contract must not preapprove KPI')
    if contract.get('official_kpis_approved'):
        raise ValueError('Family contract official KPIs must be empty')
    if shop=='dev_009' and ('order_lines' in actual or 'order_lines_with_adjustments' in actual):
        raise ValueError('Summary-only invoices cannot contain guessed SKU detail')
    if shop=='dev_012' and 'order_lines' in actual:
        raise ValueError('Repair visit grain cannot be flattened into order lines')
    return policy
