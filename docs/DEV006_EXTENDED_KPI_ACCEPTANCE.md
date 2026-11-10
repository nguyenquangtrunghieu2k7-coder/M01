# dev_006 additional pharmacy KPI acceptance

The original dev006 revenue release is already approved and **must remain
immutable**. This extension creates a NEW versioned release from that exact
approved SQLite only if tests on the *original POS* prove source-to-mart
parity for the proposed extended metrics. A successful GitHub CI alone does
not approve the real-source KPI values.

## Families implemented

The family-specific read API is `scripts/dev006_extended_kpis.py`:
`calculate(connection, catalog, metric, as_of_date, start_date, end_date, ...)`.

| Metric | Source definition | Date semantics |
|---|---|---|
| `order_count` | `don_hang`, only completed/shipping | order creation, period |
| `cancel_rate` | cancelled divided by all orders, 2dp | order creation, period |
| `gross_profit_by_order_date` | dedup `TriGia - SL*GiaVonLucBan`, valid orders | order creation, period |
| `units_sold_base` | dedup `SLQuyDoi`, valid orders | order creation, period |
| `purchases_by_receipt_date` | noncancelled `phieu_nhap.TongGiaTriNhap` | receipt date, period |
| `supplier_purchase_value` | same, filtered by supplier code | receipt date, period |
| `cash_collected` | `thanh_toan.SoTienThu`, by receipt method; default cash | receipt timestamp, period |
| `receivables_as_of` | positive outstanding invoice debt, excluding cancelled, COD and marketplace, including returned | as-of snapshot |
| `stock_units_as_of` | last `the_kho.TonCuoi` by product, not sum of events | as-of snapshot |
| `inventory_value_as_of` | positive current stock * product's `GiaVonHang` per base unit | as-of snapshot |
| `stockout_product_count` | products with last snapshot quantity exactly zero | as-of snapshot |
| `prescription_revenue` | valid line revenue tagged `BanTheoDon=1` | order creation, period |
| `ingredient_revenue` | valid line revenue by exact compound ingredient label | order creation, period |
| `returns_count` | orders with status returned | order creation, period |
| `selling_price_as_of` | latest `lich_su_gia.GiaBanLe` effective by date | as-of snapshot |
| `expiry_lot_count` | lots with remaining positive qty expiring in next N inclusive days | as-of snapshot |
| `expiry_lot_cost_vnd` | same lots: remaining qty * lot's own base-unit purchase price | as-of snapshot |

The `product_id` selector is reused for *supplier code* in
`supplier_purchase_value` and *days ahead (integer)* in expiry metrics;
this is a temporary programmatic interface and **not** a natural-language
M03 question parser. Do not infer undocumented values or permit unsupported
metric calls.

## Full-source independent acceptance (not yet assumed PASS)

This auditor compares the POS source directly against the normalized
approved-revenue SQLite, including all ingredient labels, monthly periods,
multiple as-of snapshots and expiry valuation:

```bash
cd "$HOME/Desktop/M01_PUBLIC_COMPLETE"
git pull --ff-only origin fix/m03-businessdata-contract-20261110
PRIOR="$PWD/outputs/dev006_rulebook_20261110_161422/release"

PYTHONPATH=.:src python3 -m unittest discover \
  -s tests -p 'test_dev006_extended_kpis.py' -v

PYTHONPATH=.:src python3 scripts/verify_dev006_extended_kpis.py \
  --pos "$HOME/Downloads/public_test/data/dev_006/pos.sqlite" \
  --db "$PRIOR/dev_006.sqlite" \
  --report "$PWD/outputs/dev006_extended_kpi_acceptance.json"
```

If acceptance fails, inspect `failures` in the JSON. Do **not** alter or
relabel the original release to avoid failing the test.

## Separate release of approved extended KPIs

Only after reviewing the audit and confirming the family-specific semantics,
explicitly approve with the owner command:

```bash
PYTHONPATH=.:src python3 scripts/release_dev006_extended.py \
  --pos "$HOME/Downloads/public_test/data/dev_006/pos.sqlite" \
  --prior-release "$PRIOR" \
  --output "$PWD/outputs/dev006_extended_release" \
  --approve --approved-by "Data owner"
```

The release script independently repeats all checks, refuses to alter the
prior release, verifies the original manifest SHA256, and writes a new SQLite
with explicit metric capabilities, new schema contract, source-pinned manifest
and complete audit evidence. If checks fail it writes
`dev006_extended_release.failed_qa.json` **without creating a release**.
No values are hardcoded and metrics are never approved merely because tests
were run.

## Still unsupported / requiring own acceptance

This is a *family KPI library*, not a full score for all 111 natural-language
questions in public_test/questions.jsonl. Advanced question composition
(e.g., Lunar New Year via calendar.csv, customer loyalty and ranking,
per-employee/shift/group revenue, age-of-debt buckets, debt inflows,
price-change effect, missing medical advice) must be built and tested separately.
Medical advice absent from the released records is unanswerable per rulebook
§7. A production approval of these 17 scoped metrics must not be interpreted
as permission for all natural-language questions.
