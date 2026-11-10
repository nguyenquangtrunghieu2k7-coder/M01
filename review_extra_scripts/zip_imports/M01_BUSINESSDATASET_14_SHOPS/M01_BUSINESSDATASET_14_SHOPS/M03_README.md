# M01 BusinessDataset — M03 sandbox handoff

Contains 14 read-only SQLite BusinessDatasets with mart, staging, validation, catalog and lineage as available per shop.

## Access
Use `sqlite3.connect("file:/absolute/path/to/databases/dev_XXX.sqlite?mode=ro", uri=True)` and inspect `manifest.json` and `schema_contract.json` before queries. `shop_id` is the isolation boundary. Do not sum `orders.amount` with `order_lines.amount`; grain and semantic approval are not guaranteed.

## Safety
All shops are provisional, `production_eligible=false`. Do not publish KPIs until mapping and reconciliation are approved. `unlinked_validation=0` proves issue-to-staging traceability only; it does not resolve validation issues. Some candidate marts use heuristic mapping and may contain unlinked lines, missing IDs or repeated totals. Source reference records are not transaction facts.

## Privacy
Staging and mart tables can contain sensitive customer data. Do not publish or commit SQLite to a public repository.
