# 10-shop source-to-contract acceptance audit — 2026-11-10

**Status:** REVIEWED FOR SOURCE INVENTORY AND KNOWN MAPPING BLOCKERS; **NOT** production acceptance.

## Evidence and scope

- Base: `main` commit `30a3d8b4d6137071e5b882a6348ab6b72cbb046c`.
- Input: user-provided `archive(2).zip`, containing `public_test/data` and shop README files. Archive integrity verified (`ZipFile.testzip() == None`).
- Compared: `configs/m01/*.json`, `build_9_shops.py`, `M01_README.md`, `ACCEPTANCE_GATES.md`, and `docs/data_discovery/D5_adapter_design/*`.
- ZIP raw data stays **outside** Git. No private record contents, contact information, source bytes, or SQLite marts are committed.
- An object is a CSV source file, SQLite file (table-level count not included below), or Excel worksheet. The counts below are **inventory counts**, not counts of successfully ingested objects or verified semantic mappings.

| Shop | Source files | Inventory source objects | Main-pipeline config | Current disposition |
|---|---:|---:|---|---|
| dev_002 | 18 | 18 | 1 Excel month only | PARTIAL — extend 17-month sales coverage, unit conversions and topping rules |
| dev_003 | 7 | 11 | `sources: []` | BLOCKED — combined sales, receipt, expense, purchase and inventory scopes |
| dev_004 | 7 | 24 | `sources: []` | BLOCKED — month sheets, repeated header and document-level amounts |
| dev_005 | 23 | 23 | `sources: []` | BLOCKED — monthly sales **not selected** by `build_9_shops.py` mapping |
| dev_007 | 3 | 3 | `sources: []` | BLOCKED — CSV bill totals, repeats and purchase linkage |
| dev_008 | 4 | 4 | `sources: []` | BLOCKED — two Excel sales partitions, inventory/purchase rules |
| dev_010 | 5 | 5 | five configured CSV objects | PARTIAL — 4,141 documented issues + order/payment/line reconciliation |
| dev_011 | 1 | 2 | `sources: []` | BLOCKED — blank STT continuation, discounts, trade-ins, return notes |
| dev_013 | 3 | 18 | `sources: []` | BLOCKED — multirow headers and invoice adjustments / reward points |
| dev_014 | 3 | 20 | `sources: []` | BLOCKED — monthly sales, debt, installments, warranties and IMEIs |
| **Total** | **74** | **128** | **2 partial, 8 empty** | **0 newly production-approved** |

All statuses are based on direct source/contract inspection, **not** a new full candidate-mart regression run. Most shop work remains open.

## Confirmed correctness blockers

1. **Empty pipeline source contracts.** Eight of the ten `configs/m01/dev_*.json` files contain `sources: []`. A successful no-op pipeline execution cannot certify coverage or production readiness. The nine-shop `build_9_shops.py` builder is a separate provisional path with its own SQLite contract; its output is not equivalent to main-pipeline support.
2. **dev_005 monthly sales omitted in candidate script.** Its 17 sales workbooks use `DonHang_ChiTiet` sheet, but `EXPLICIT['dev_005']` neither matches the workbook stems `BanHang_ThangXX_YYYY` nor maps `DonHang_ChiTiet`. In `consume`, `selector = stem if stem in EXPLICIT else obj`, then unmapped objects are skipped. Thus sales lines are excluded by this candidate builder even if it succeeds. Do not accept missing rows as zero sales.
3. **dev_013 “Dùng N điểm” is a non-item adjustment.** Shop README specifies vouchers and point redemptions as negative invoice adjustments and shipping as a charge. Candidate script recognizes only exact `voucher`, `phí ship`, `phí vận chuyển`, `giảm giá`; strings beginning with `Dùng` are treated as order lines. The handling of monetary adjustments and the order total must be verified against each invoice; no net-sales KPI approval.
4. **dev_011/dev_014 journal boundaries.** README says an order can have several rows, and blank `STT` continuation rows exist. Candidate script stages unlinked lines rather than inferring a join. This is conservative but means incomplete order-line coverage; approval requires an evidenced order grouping policy, and trade-in/discount must be counted once per order.
5. **dev_010 parsing and reconciliation.** Committed `dev010_qa.json` records 23,311 orders, 45,025 lines, 26,246 payment records, and 4,141 issues (1,856 `PARSE_AMOUNT`, 1,579 `PARSE_PAID`, 226 each for quantity/unit price/repeated header, 19 duplicate order keys, 9 debt parse). This is a *prior* provisional QA result; rerun and reconcile before approving money KPIs.
6. **dev_002 incomplete temporal coverage.** Main config only selects `BanHang_T1_2025.xlsx` while README enumerates 17 monthly files (Jan 2025–May 2026). Topping ` + ` decomposition, unit conversion, and cross-month consistency remain unverified.
7. **Cross-source graph and business KPI ownership.** M01 must emit truthful source-grained facts, typed units and identifiers with uncertainty and provenance. M03 owns formulas and KPI query construction. Do not implement/assume M03 KPI SQL in M01.

## Acceptance gates remaining for each shop

- Verify physical columns, exact object selector, header rows, source file SHA-256/profile fingerprint and source-row lineage for **every** object.
- Establish entity grain and document identity (including multirow journals, monthly sheet boundaries, header/summary/adjustment/return rows).
- Verify date, money and unit parsing; ensure bad values cause explicit issues rather than fabricated zero; source-defined unit conversions only.
- Reconcile source order/line/payment/discount/return totals and cross-object joins without fanout; compare row counts with raw and staged sources.
- Produce independent reproducible tests and audited issue disposition; record an explicit human approver where required.
- Only then consider `APPROVED`; until then preserve fail-closed `PROVISIONAL_NOT_FOR_PRODUCTION` and do not claim KPI eligibility.

## Implications for D5 QA / handover

The D5 document's “14/14 integration execution” means the configured execution path completed, **not** that 14/14 source objects or shop semantics were processed. In the prior report, several stores output zero orders, and `M01_README.md` itself calls out known provisional scope. This audit does **not** supersede previous QA metrics, claim a new unit-test run, or change existing approval status. Reconcile these reports before final handover.

## Next implementation priority

1. Fix `dev_005` source selectors and `dev_013` adjustment classification with regression tests.
2. Integrate the remaining eight `sources: []` shops into the **main** pipeline or explicitly document/verify a contract-compatible alternate adapter.
3. Extend `dev_002` to all months, resolve `dev_010` QA issues; execute source-by-source reconciliation.
4. Publish per-shop acceptance matrix and candidate BusinessCatalog capabilities **only** for demonstrated coverage.
