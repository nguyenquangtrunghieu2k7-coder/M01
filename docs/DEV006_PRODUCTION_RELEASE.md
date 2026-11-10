# dev_006 — evidence-gated BusinessData release

This process is **specific to the pharmacy POS family** and **does not apply its mappings to the other 13 shops**. The raw POS data and final SQLite may contain personal data; keep them private.

## Required business rules

Source of truth: `public_test/rulebook.md` §§1, 2, 6 (pharmacy), 8 and `public_test/data/dev_006/README.md`.

- Revenue: sum `chi_tiet_don.TriGia` from orders in `completed` or `shipping` state. Exclude `cancelled` and `returned`, even if the return happened after the question's `as_of_date`.
- Use **order creation date**, not payment date, for revenue periods. A question-specific `as_of_date` is inclusive.
- Do not include invoice-level discount, VAT, or shipping in revenue. Cash receipts are not revenue.
- If two rows of the **same order** are exactly identical across **all physical fields**, rulebook §8 says they are an export duplicate: preserve both in staging, emit only one into the KPI order-line mart. Never deduplicate on order code / line position / SKU alone.
- A query interval fully outside the shop's published coverage is **unanswerable**, not zero.

## Rebuild only dev_006

Run from this repository root, using a POS directory at `~/Downloads/public_test/data/dev_006/pos.sqlite`:

```bash
set -e
python3 -m pip install openpyxl
PYTHONPATH=.:src python3 -m unittest discover -s tests -p 'test_candidate_builder_integrity.py' -v
PYTHONPATH=.:src python3 -m unittest discover -s tests -p 'test_m03_contract_gate.py' -v
RUN_DIR="$PWD/outputs/dev006_rulebook_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RUN_DIR"
python3 -u build_9_shops.py --data-root "$HOME/Downloads" --output "$RUN_DIR" --shops dev_006 > "$RUN_DIR/rebuild.log" 2>&1
python3 scripts/verify_dev006_coverage.py --pos "$HOME/Downloads/public_test/data/dev_006/pos.sqlite" --db "$RUN_DIR/dev_006.sqlite" --report "$RUN_DIR/coverage.json"
python3 scripts/verify_dev006_rulebook_financial.py --pos "$HOME/Downloads/public_test/data/dev_006/pos.sqlite" --output "$RUN_DIR/source_financial.json"
python3 scripts/verify_dev006_m03_parity.py --pos "$HOME/Downloads/public_test/data/dev_006/pos.sqlite" --db "$RUN_DIR/dev_006.sqlite" --report "$RUN_DIR/m03_acceptance.json"
echo "Candidate: $RUN_DIR/dev_006.sqlite"
```

Expected for the provided public POS snapshot (must verify, not hardcode):

| Metric | Expected |
|---|---:|
| Raw order lines | 72,411 |
| Exact duplicate *copies* | 1,350 |
| Order-line mart after §8 | 71,061 |
| Revenue from valid orders, after dedup | 4,174,528,900 VND |
| Imported source tables | 17 / 17 |
| Reference rows retained | 89 / 89 |
| Source/mart acceptance errors | 0 |

The older `verify_dev006_pos.py` asserts header-vs-line equality across **different metrics** and is not a release gate.

## Publish a release

The release step is intentionally **not automatic**: the responsible person must confirm the QA output and explicitly authorize approval.

```bash
PYTHONPATH=.:src python3 scripts/release_dev006_businessdata.py \
  --pos "$HOME/Downloads/public_test/data/dev_006/pos.sqlite" \
  --db "$RUN_DIR/dev_006.sqlite" \
  --output "$RUN_DIR/release" \
  --approve --approved-by "Data owner"
```

This script re-runs coverage, financial consistency and M03 source/mart acceptance, refusing to publish on failures. On success, it generates `release/dev_006.sqlite`, `qa_report.json`, `schema_contract.json`, `manifest.json`; the database is copied before the production status is changed. The original candidate stays provisional.

The release marks **only `revenue_by_order_date` as an accepted KPI metric**. Other metric families, including stock, debt, pharmacy-specific active ingredients/expiration, and profit, require their own acceptance tests before M03 is permitted to claim them as approved.

## Known boundary

The synthetic CI suite does **not** use private/local full POS files; full acceptance and human release approval must happen on the source holder's machine. CI success alone does not constitute production authorization.
