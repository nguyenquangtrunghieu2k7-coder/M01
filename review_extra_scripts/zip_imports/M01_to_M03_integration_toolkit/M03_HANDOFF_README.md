# M01 → M03 handoff toolkit (14-shop scope)

This toolkit is a **verified interface scaffold**, not a claim that all 14 shops have approved mappings. Original M01 files are retained, and no customer raw data is included.

## Run on the original local repository

Copy `scripts/export_m03_bundle.py` and `scripts/m03_consumer.py` to the repository's `scripts/` directory. Run from the repository root:

```bash
python scripts/export_m03_bundle.py \
  --db-dir /tmp/datamate_d5_qa \
  --config-dir configs/m01 \
  --output /tmp/datamate_m03_handoff
```

Output: `manifest.json`, `schema_contract.json`, `shop_coverage.csv`, `M03_ACCEPTANCE.md`, and one catalog and metadata JSON per shop. Database files are **not** copied unless `--include-databases` is explicitly passed; only do so with data-owner permission. Review metadata before sharing: source paths, table names and headers can be sensitive.

The exporter checks catalog/version alignment, real table row counts, source coverage, and issue breakdown. It does **not** establish semantic correctness, document reconciliation, or human approval.

## M03 consumer example

```python
from scripts.m03_consumer import open_business_dataset, query_entity_count

# Official KPI access fails closed for provisional data.
connection, catalog = open_business_dataset('/tmp/datamate_d5_qa/dev_009.sqlite')
try:
    print(query_entity_count(connection, catalog, 'orders'))
finally:
    connection.close()
```

For sandbox-only testing, set `allow_provisional_sandbox=True` and label all outputs as provisional. This is not a production bypass.

## Exact metadata and approvals still missing

1. **9 shops with no active sources:** dev_003, dev_004, dev_005, dev_006, dev_007, dev_008, dev_011, dev_013, dev_014. Their D5 design configs are not runnable source mappings. Each needs an activated, reviewed config with source paths, selectors, headers, grain, field mapping, source-defined dedup, and merge keys.
2. **All 14 shops:** business-owner approval of mapping semantics, field-level data dictionary, grain and join verification, reconciliation and dedup rules, unit conversion rules where relevant, and source-coverage acceptance.
3. **Current catalog contract:** real date ranges, per-entity schema semantics, effective snapshot dates, supported metric conditions, reliable document relationships, and explicit unsupported-vs-zero distinction need further development.
4. **Reader capabilities:** pipeline currently handles CSV/XLSX; SQLite source adapter, multirow/merged header support, source-specific forward-fill, multihop unit conversions, and other source patterns must be implemented and tested where needed.
5. **End-to-end acceptance:** source-specific QA with row-level evidence, consumer tests for each supported capability, review of issue severity and KPI eligibility.

## Handover states

- `EXECUTION_PASS`: pipeline ran, but does not imply data is semantically correct.
- `PROVISIONAL_NOT_FOR_PRODUCTION`: sandbox integration only.
- `BLOCKED_NO_MAPPING`: no active source mapping; empty output is not a legitimate zero.
- `APPROVED`: only after evidence-based semantic sign-off and acceptance gates.

Do not commit raw data or local derived databases without explicit authorization.
