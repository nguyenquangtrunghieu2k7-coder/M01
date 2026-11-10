#!/usr/bin/env bash
# Fail-closed local build and release of only dev_006 pharmacy POS.
# Does not overwrite raw POS, other shop databases, or previous releases.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DATA_ROOT="${DATA_ROOT:-$HOME/Downloads}"
POS="$DATA_ROOT/public_test/data/dev_006/pos.sqlite"
if [[ ! -f "$POS" ]]; then
  echo "ERROR: POS source not found at $POS" >&2
  exit 2
fi
if [[ "${1:-}" != "--approve" || -z "${2:-}" ]]; then
  echo 'Usage: bash scripts/build_and_release_dev006.sh --approve "Data owner"' >&2
  echo 'Approving only rulebook-verified dev006 revenue_by_order_date KPI.' >&2
  exit 2
fi
APPROVER="$2"
RUN_DIR="$ROOT/outputs/dev006_rulebook_$(date +%Y%m%d_%H%M%S)"
if [[ -e "$RUN_DIR" ]]; then
  echo "ERROR: output directory already exists: $RUN_DIR" >&2
  exit 2
fi
mkdir -p "$RUN_DIR"
echo "QA and release outputs: $RUN_DIR"

echo "=== 1. Python regression tests ==="
PYTHONPATH=.:src python3 -m unittest discover -s tests -p 'test_candidate_builder_integrity.py' -v
PYTHONPATH=.:src python3 -m unittest discover -s tests -p 'test_m03_contract_gate.py' -v

echo "=== 2. Rebuild with exact-export-duplicate suppression ==="
python3 -u build_9_shops.py \
  --data-root "$DATA_ROOT" \
  --output "$RUN_DIR" \
  --shops dev_006 > "$RUN_DIR/rebuild.log" 2>&1 || {
    tail -n 60 "$RUN_DIR/rebuild.log"
    echo "BUILD FAILED. Inspect $RUN_DIR/rebuild.log" >&2
    exit 2
  }
tail -n 10 "$RUN_DIR/rebuild.log"

echo "=== 3. Source coverage ==="
python3 scripts/verify_dev006_coverage.py \
  --pos "$POS" --db "$RUN_DIR/dev_006.sqlite" \
  --report "$RUN_DIR/coverage.json"

echo "=== 4. Rulebook financial source checks ==="
python3 scripts/verify_dev006_rulebook_financial.py \
  --pos "$POS" --output "$RUN_DIR/financial.json"

echo "=== 5. Source to normalized M03 as-of acceptance ==="
python3 scripts/verify_dev006_m03_parity.py \
  --pos "$POS" --db "$RUN_DIR/dev_006.sqlite" \
  --report "$RUN_DIR/m03_acceptance.json"

echo "=== 6. Release gate, authorized by $APPROVER ==="
PYTHONPATH=.:src python3 scripts/release_dev006_businessdata.py \
  --pos "$POS" \
  --db "$RUN_DIR/dev_006.sqlite" \
  --output "$RUN_DIR/release" \
  --approve --approved-by "$APPROVER"

echo "=== SUCCESS: scoped M03-ready dev_006 revenue release ==="
echo "BusinessData: $RUN_DIR/release/dev_006.sqlite"
echo "Manifest:     $RUN_DIR/release/manifest.json"
echo "QA report:    $RUN_DIR/release/qa_report.json"
echo "IMPORTANT: other KPI families and shops remain pending acceptance."
