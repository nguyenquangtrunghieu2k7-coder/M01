# M01 — Data Processing (auditable pilot v0.2.0)

## Implemented and measured

A conservative, executable pipeline and SQLite contract with **raw source manifests (SHA-256), staging rows with original and parsed values, mart entity tables, per-field source lineage, validation issue locations, immutable-ish technical IDs scoped to file/object/row, a dataset version, and a machine-readable BusinessCatalog**. Source files remain unchanged outside the database; the `raw` logical layer contains immutable file references and fingerprints, not all source bytes. To make a distributable standalone archive, retain the upstream source archive separately.

The contract defines 23 *possible* business tables but each shop SQLite file creates **only the mart tables for supported configured grains**. Absence of a table means lack of evidence / lack of implementation, not zero business activity. Read `business_catalog.capabilities` and row counts.

### Evidence-backed adapter pilots

| Shop | Status | Grain / source scope | Important caveats |
|---|---|---|---|
| dev_009 | provisional QA executed | CSV invoice/one row per invoice | Daily subtotal rows quarantined, duplicate invoice identifiers retained+flagged, no fabricated line items, no claimed individual payment events |
| dev_002 | provisional QA executed | Jan 2025 monthly Excel `DonHang_ChiTiet` | Only 1 of 17 months, repeated headers excluded with errors, quantities with units parsed, topping decomposition pending; no fake order totals |
| dev_010 | provisional QA executed | 5 relational CSV files: orders, lines, payments, products, customers | independently observed payments, joined only by same raw order id; reconciliation/semantic approval still pending |
| dev_012 | provisional QA executed | 14 monthly sheets, service visits | `Làm gì` retained as one unsplit text value; no fabricated visit tasks or separate ticket id |
| dev_001 | source mapping candidate only | sales detail Excel | not executed at full scale, mappings remain provisional |
| dev_003–dev_008, dev_011, dev_013–dev_014 | blocked | registry and evidence in D5 | mapping review and semantic implementation outstanding |

The five candidate configurations were derived from actual README column definitions and matched by exact name against D4 physical profile; **no human-approved mappings exist**. Re-run configuration approval explicitly after verification. Production runs **fail closed** without `approval_status=APPROVED`; the `--allow-provisional` flag is intended for isolated QA and NEVER changes the dataset's `PROVISIONAL_NOT_FOR_PRODUCTION` status.

## Run

At repository root (with D4 source extracted and raw files under `public_test/data`):

```bash
PYTHONPATH=src python -m unittest discover -s tests/m01_data_processing -p 'test_pipeline.py' -v
PYTHONPATH=src python -m datamate.m01_data_processing.pipeline \
  --config configs/m01/dev_009.json --data-root . \
  --out-db reports/m01/dev009.sqlite --profile reports/profiling/d4/profile_report.json \
  --allow-provisional
```

Requires Python 3.10+ and stdlib only for the pipeline; XLSX is safely streamed from ZIP+XML, without running workbook macros or expressions. A formula cell without a cached value generates `MISSING_FORMULA_CACHE` and is prevented from entering the mart. Do not use an XLSX workbook that contains encrypted or unsupported OOXML constructs without improving the reader.

## Architecture

```
source file (immutable, checksum) -> raw_sources
  -> exact object/header verification via D4
  -> staging_rows (raw_json + parsed_json)
  -> parse/quality issue ledger (source row/cell)
  -> approved grain-specific adapter (pilot: order, line_item)
  -> mart entities + source_lineage (field + record)
  -> BusinessCatalog and dataset_versions
```

### Restrictions honored in current pilot

- Source identity includes shop/source file/object/hash; no inference based on file name only.
- No whole-sheet forward-fill; null remains null.
- Summary-only source yields orders, never invented order lines.
- Grouped line-item file yields order with null `amount`: line-level money is not repeated as invoice total.
- Duplicate invoice identifiers in summary source are reported and **retained**, not silently removed; duplicates must be resolved via a source-defined rule and QA before production consumption.
- Product/price names retain raw strings; no fuzzy merging.
- All money values are parsed with base-ten `Decimal` into text in SQLite, never binary float.
- Parsed date is ISO, source raw date preserved in staging; unparseable values get an issue.
- No inventory/debt snapshots are manufactured from current totals. For dev_009, `Nợ` is explicitly stored as **as-of-dataset-end** attribute, never a debt event.

### Known gaps / gates to production

1. **Full 14-shop semantic coverage not reached.** Source-specific parsers needed for nested rows, mergers, multi-level headers, SQLite relationships, repairs, installment/warranty, purchase/inventory ledgers and exceptional subtotals. D5 templates exist but are unapproved.
2. Only four provisional datasets (21 source objects) were QA executed; dev_002 is one month out of 17; cross-month schema drift has NOT been regression-tested.
3. For line-item-only sources `orders` is one technical grouping per source order **per file**, with null totals. For dev_010, documents link on raw order ID within shop, and orders are ingested only from the independently documented order table (never generated twice).
4. Detailed source-cell coordinates currently represent **physical column labels** and row indexes, rather than A1 notations for every field. Formula errors preserve A1 coordinates.
5. `BusinessCatalog` is an initial capability/version ledger; full column-level dictionary, cross-shop aliases and validated unit graph are outstanding.
6. No semantic status mapping/return logic, allocation of repeated invoice money, reconciliation beyond duplicate key warning, or approved unit conversion graph yet. No guessed mappings were activated.
7. SQL table definitions for non-supported entities are a stable contract, not populated marts. SQLite staging contains raw text/parsed text, but does not contain full source XLSX/CSV bytes. Keep raw archive available for replay.
8. Current code can detect unsupported source layouts but **should not be treated as a universal Excel parser**. Test against merged cells and irregular sheets before use.

## M01 ↔ M03 boundary

M01 exposes source-grained records with source context, parse results and quality status. M01 intentionally does not decide the revenue/net-sales/refund/stock KPI computation rules. Any M03 query must check dataset and mapping approval first and refuse provisional output.

## Definition of done

- [x] Architecture, basic executable engine, auditability, versioning, pilot contract
- [x] Real-data dry runs on invoice-only, line-item, relational and service examples
- [x] Strict blocked-production gate
- [ ] Manual mapping approval for each source object and shop
- [ ] All 14 shop adapters semantic-complete and tested
- [ ] Cross-source joins, conversion graph, return/payment semantics and KPI capability checks
- [ ] Full data correctness and performance acceptance suite

**Readiness: M01 framework and four provisional pilots; M01 end-to-end for all shops is NOT complete.**
