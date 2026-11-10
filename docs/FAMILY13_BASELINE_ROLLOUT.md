# 13-shop family baseline rollout — M01 → M03

This rollout covers all public-test shops **except dev_006**, whose separate
pharmacy POS revenue and 17 extended KPI metrics already have their own
approved, immutable release. No part of the 13-shop rollout changes that
release.

## What is implemented in this phase

1. `scripts/family_inventory.py` discovers physical source objects (XLSX
   sheets, CSV files, SQLite tables) and creates source manifests for all
   13 families. Source inventories are based on actual data-root contents,
   not filenames guessed from a README.
2. `scripts/family_semantics.py` enforces *distinct* business grains, joins,
   and forbidden transformations per shop.
3. `scripts/build_family_staging.py` writes a separate candidate SQLite
   per shop. It keeps each nonblank row at its original file/sheet/row
   grain, with indexed raw cell values, source SHA256, explicit role, and
   per-object staging counts. It cannot overwrite previous files.
4. Each candidate exposes an M03-compatible `business_catalog` and
   `dataset_versions`. Sandbox M03 can inspect source counts, but the
   official KPI consumer still **fails closed** because the candidate is
   `PROVISIONAL_NOT_FOR_PRODUCTION`, with **no approved KPI metrics**.
5. CI runs package/import, per-family grain, and fail-closed M03 tests.
   Actual full-source staging and count QA must be run on the source files.

## Source coverage and distinct family contracts

| Shop | Family | Physical objects | Critical source-grain constraint |
|---|---|---:|---|
| dev_001 | Retail single export | 2 | Do not sum invoice header amount repeated on lines |
| dev_002 | Retail monthly exports | 18 | Preserve 17 source months; join names and units carefully |
| dev_003 | Cafe POS + cash shifts | 11 | Toppings as separate sale lines; cash-shift grain not order revenue |
| dev_004 | Building-material delivery | 24 | One delivery occurrence is not a new invoice |
| dev_005 | Pharmacy Excel + lots | 23 | Keep sales, receipts, lot allocations, drug catalog separate |
| dev_007 | Restaurant CSV POS | 3 | Invoice lines and purchase details are different entities |
| dev_008 | Restaurant Excel POS | 4 | Two sales exports; do not treat same invoice as automatically distinct |
| dev_009 | Invoice summary only | 1 | **Never invent SKU lines or product rankings** |
| dev_010 | Five linked POS CSVs | 5 | Join order/line/payment/customer/product on validated source keys |
| dev_011 | Mobile sales ledger | 2 | Blank STT continuation scoped to verified invoice group only |
| dev_012 | Motorcycle repair ledger | 15 | One row = one service visit, including warranty |
| dev_013 | Mother/baby ledger | 18 | Voucher/points/shipping adjustments are not merchandise |
| dev_014 | Mobile sales + financing | 20 | Trade-ins, instalments, debts, warranties have independent grains |
| **Total** | **13 shops** | **146** | |

These counts were observed on the provided public-test source inventory.
If a new source version has different files/sheets, validation must fail,
rather than silently reuse an old mapping.

## One command to build the baseline

```bash
cd "$HOME/Desktop/M01_PUBLIC_COMPLETE" || exit 1
git pull --ff-only origin fix/m03-businessdata-contract-20261110
python3 -m pip install openpyxl
bash scripts/rollout_family13.sh
```

Results are created in a fresh `outputs/family13_YYYYMMDD_HHMMSS/`
directory:

- `family_contracts/dev_001.json` ... `dev_014.json` excluding dev_006
- `family_inventory_audit.json` with physical source coverage
- `candidates/dev_001.sqlite` ... `dev_014.sqlite` excluding dev_006
- `candidates/family_stage_manifest.json` with per-shop/per-source row
  counts, role counts and SQLite integrity results

Expected pass counts: **13/13 shops** and **146/146 source objects**,
with nonblank staging row counts measured from the real source. No
production approval is issued by this script.

## Next gates: before claiming BusinessDataset KPI readiness

A source inventory and family-aware raw/staging representation are
**necessary but not sufficient** for M03 production. For each family:

1. Explicitly map column headers (including multirow headers, grouped
   continuation rows, aliases, and date/money/quantity units) into
   valid order, line, payment, receipt, adjustment, delivery, visit,
   lot, debt or warranty entities. Preserve source lineage.
2. Independently reconcile source counts, deduplications, joins,
   financial and inventory rules with the actual family README and
   public_test/rulebook.md.
3. Test `as_of_date` and each KPI on its correct business grain.
4. Approve only passing KPI capabilities, version/checksum the result
   and publish a **new** per-shop release. Never stamp a whole family
   APPROVED from source inventory checks alone.

Priority baseline: complete physically verified source coverage across
all 13, then explicitly verified core fact tables and order/service
KPI where source evidence supports them. Question-specific advanced
analytics come only after core M03 acceptance. `dev_009` can answer
invoice-level metrics but not SKU rankings from its summary source.
