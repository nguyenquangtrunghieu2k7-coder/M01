# M01 — 13-shop family baseline rollout

Scope: dev_001–dev_005, dev_007–dev_014. **dev_006 approved
releases are deliberately excluded and never overwritten.**

Run from repository root:

```bash
git pull --ff-only origin fix/m03-businessdata-contract-20261110
python3 -m pip install openpyxl
bash scripts/build_all_13_families.sh
```

By default the source root is `~/Downloads` containing
`public_test/data/dev_001` … `dev_014`. Set `DATA_ROOT` if elsewhere.

## What is delivered per shop

- A candidate `dev_XXX.sqlite` with shop-scoped business marts **only where
  physical source support exists**; source rows are retained in
  `staging_rows`, with `raw_sources` and `source_lineage`.
- A pinned per-shop `family_contracts/dev_XXX.json` with exact physical
  (file, workbook sheet or SQLite table) source assignments and a native grain.
- `family_native_records` for special family roles that cannot safely
  map to a generic entity, such as cash shifts, debtor ledgers, medicine
  references, promotions and staff. Each row has its exact family role,
  raw values and traceable physical source location. No fabricated KPI.
- One `family_inventory_audit.json` and one `rollout_13_report.json`
  showing physical object count, independent physical-to-staging row-count parity, native row coverage, mart
  row counts, validation issues, orphans and contract mismatches.

Structural acceptance requirements: all 13 source manifests exactly match
the physical files; no unclassified objects; required schema exists; source
rows and lineage references are nonorphaned; every mapped mart count matches
catalog; `dev_009` has no fabricated invoice lines; `dev_012` has no
fabricated product sales; all 13 catalogs and versions remain **candidate**.

## Family list and expected source inventory

| Shop | Native family | Physical objects |
|---|---|---:|
| dev_001 | retail_single_export | 2 |
| dev_002 | retail_monthly_exports | 18 |
| dev_003 | cafe_multi_source | 11 |
| dev_004 | building_materials_delivery | 24 |
| dev_005 | pharmacy_excel_lots | 23 |
| dev_007 | restaurant_csv_pos | 3 |
| dev_008 | restaurant_excel_pos | 4 |
| dev_009 | invoice_summary_only | 1 |
| dev_010 | linked_csv_pos | 5 |
| dev_011 | mobile_sales_ledger | 2 |
| dev_012 | motorcycle_service_ledger | 15 |
| dev_013 | mother_baby_ledger | 18 |
| dev_014 | mobile_multi_ledger | 20 |
| **Total** | 13 families | **146** |

These are verified *source inventories*, not 146 completed semantic mappings.
The builder will refuse unknown/new/removed source objects until the family
contract is reviewed and updated.

## Production boundary and subsequent acceptance

All 13 candidate outputs have
`CANDIDATE_NOT_APPROVED`/`PROVISIONAL_NOT_FOR_PRODUCTION`.
Neither 146/146 inventory nor zero SQLite orphans establishes numeric parity
with the rulebook.

Next pass per family requires: field-level mapping quality review; duplicate
and status semantics; joins & financial parity; date/as-of checks; KPI-specific
acceptance and review; SHA256 manifest and explicit human approval. 
Never apply dev006 pharmacy logic to other shops, never treat unclassified
source-only rows as sales, never create missing invoice details from an order
summary, and never overwrite an approved release.

Because the full public test source is held locally, GitHub Actions executes
*synthetic regressions* but **cannot run the user's full-source 13-shop QA**.
Do not claim production readiness before running
`scripts/build_all_13_families.sh` on the real dataset and reviewing its report.
