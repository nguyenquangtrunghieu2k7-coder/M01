#!/usr/bin/env bash
# Build 13 shop-family candidates from local POS sources. Never touch dev_006.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DATA_ROOT="${DATA_ROOT:-$HOME/Downloads}"
if [[ ! -d "$DATA_ROOT/public_test/data/dev_001" ]]; then
  echo "Missing dataset under $DATA_ROOT/public_test/data" >&2
  exit 2
fi
OUT="$ROOT/outputs/families13_$(date +%Y%m%d_%H%M%S)"
if [[ -e "$OUT" ]]; then
  echo "Output exists. Refusing to overwrite: $OUT" >&2; exit 2
fi
PYTHONPATH=.:src python3 -m unittest discover -s tests -p 'test_13_family_rollout.py' -v
PYTHONPATH=.:src python3 scripts/rollout_13_families.py \
  --data-root "$DATA_ROOT" --output "$OUT"
echo "=== FAMILY CANDIDATE ROLLOUT COMPLETED ==="
echo "Results: $OUT/rollout_13_report.json"
echo "Inventory: $OUT/family_inventory_audit.json"
echo "Candidate SQLite: $OUT/dev_001.sqlite ... $OUT/dev_014.sqlite (excluding dev_006)"
echo "IMPORTANT: structural family ingestion != semantic QA or official KPI approval."
