# 13-shop semantic acceptance: family KPI baseline

This is the **next phase after 13/13 structural staging PASS**. Do not
mistake a successful 146/146 source inventory for business KPI validity.

## Current production scopes

- **dev_006**: existing approved revenue + 17 pharmacy KPI metrics, immutable.
- **dev_001**: source-specific retail workbook adapter; 7 KPI capabilities
  (revenue, order count, cancellation count/rate, returns count, base-unit
  quantity and order AOV), gated by full source-vs-mart QA.
- **dev_009**: source-specific invoice-summary adapter; 4 KPI capabilities
  (`invoice_revenue`, `eligible_order_count`, `cancel_rate`,
  `current_debt_snapshot`), gated by full-source QA and explicit owner release.
- **dev_012**: motorcycle-repair adapter; 5 KPI capabilities
  (`visit_count`, `service_revenue`, `warranty_visit_count`,
  `warranty_rate`, `average_paid_ticket`), gated likewise.
- **Other 10 shops**: candidate mapping and source staging only; no newly
  approved business metrics until family-specific parity tests are supplied.

## Why not treat every family as retail sales?

The source rulebook defines different transaction grains.

| Shop | Family | Initial semantic acceptance requirement |
|---|---|---|
| dev_001 | Retail one-file line exports | Derive orders by invoice ID, exclude returned entire invoice, base-unit conversion and source-line dedup |
| dev_002 | Monthly retail + cafe topping | 17 monthly sources; split topping and parent-line revenue correctly, product name mapping, conversion rates |
| dev_003 | Cafe POS + owner notebook | Header/line join, cash shifts vs revenue, cash receipts/debt, gross and net profit |
| dev_004 | Construction materials | Delivery leg != sale; units conversion, outstanding deliveries, debt, returns |
| dev_005 | Pharmacy Excel | 17 monthly sales sheets, composition/expiry by lot, nested unit conversion, returns |
| dev_007 | Restaurant CSV POS | Status and order grouping, service fees, product item counts and shifts |
| dev_008 | Restaurant Excel POS | Two invoice-detail exports; store-level discounts/shipping excluded, notes/payment debt semantics |
| dev_009 | Invoice summary only | Use per-invoice `Giá trị hàng`, never invoice total; 540 daily subtotal lines and 308 identical duplicate copies identified on actual public test |
| dev_010 | Linked CSV POS | Explicit order/line/customer/product/receipts foreign keys and price/date semantics |
| dev_011 | Phone sale ledger | Abbreviation sheet, customer trade-in deduction separate from sales, returned entire order |
| dev_012 | Repair ledger | Per-visit transaction, zero-price warranty counted as visit; commission and vehicle dedup are future KPI work |
| dev_013 | Mother/baby ledger | Distinguish item lines from voucher, loyalty-point and shipping adjustments; catalog filters and loyalty |
| dev_014 | Phone multi-ledger | Sold IMEI vs traded-in IMEI; installments, warranty events, receivables and customer payables |

## Run semantic audit for all 13, no approvals

```bash
cd "$HOME/Desktop/M01_PUBLIC_COMPLETE"
git pull --ff-only origin fix/m03-businessdata-contract-20261110
bash scripts/semantic_phase_13.sh
```

The script reads existing candidates in
`outputs/families13_20261110_174922`, checks the structural mart's
semantic risks for **all 13**, then independently verifies the source
against candidates for dev_001, dev_009 and dev_012. It writes
`triage_13.json`, `dev009_acceptance.json` and
`dev012_acceptance.json`.

If and **only if** all three audits pass, explicitly authorize three scoped
derived releases:

```bash
bash scripts/semantic_phase_13.sh --approve "Data owner"
```

It creates versioned `outputs/semantic13_*/dev_009_release` and
`dev_012_release`, each with SHA256 manifest, SQLite and QA report. It
never touches approved dev_006 releases, other candidate SQLite, or
the public test source files.

**Fail-closed policy:** unreconciled or ambiguous source rows, invalid
source hashes, incorrect catalog status, missing physical provenance,
unsupported date/currency encoding, or unsupported business fields
must block approval. Even a successful release for dev009/dev012 is
not blanket approval for all 111+ question forms or for 11 other shops.

### Source-specific acceptance invariants

**dev_001:** Actual public source has 90,297 real sale lines and 554 daily
subtotal lines, across 35,564 unique invoice IDs. Order statuses must
be normalized from seven observed Vietnamese labels; a returned invoice
excludes its *entire* multi-line value. `Thành tiền` provides the
line-grain revenue and `Số lượng quy đổi` gives base-unit sales. An
unknown status, a conflicting invoice status or date, or unexplained
invoice duplications must block approval. No invoice headers are invented
in the original staging candidate; the production derivative has a
separately audited invoice fact view.


**dev_009:** Source CSV has 23,338 rows after the header: 22,490
unique invoices; 308 exact physical export duplicate invoice copies
(which remain staged); 540 daily-subtotal rows without invoice IDs
(which are not orders). KPI revenue comes from per-invoice
`Giá trị hàng` on completed/shipping invoices, not `TongTien`.
Last-day `Nợ` is a **single snapshot**, never a historical debt
transaction series. `order_lines` must always remain empty.

**dev_012:** Source repair workbook has 6,060 real service visits,
164 warranty visits (no cash collected) and 18 non-visit end-of-sheet
notes. Count all visits including warranty; divide warranty count by
**paid** visits. Each visit is a ledger row; never synthesize sales
order lines or allocate the total visit price to each task.

These counts describe the inspected public test snapshot only. They
are independent evidence checkpoints in acceptance and are not used
as hardcoded business data or to bypass comparisons.
