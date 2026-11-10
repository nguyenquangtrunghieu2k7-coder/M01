#!/usr/bin/env bash
# Run read-only semantic audit for all 13 shops, with optional *scoped*
# releases for dev009 invoice-summary and dev012 repair-ledger after QA.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DATA_ROOT="${DATA_ROOT:-$HOME/Downloads}"
CANDIDATE_DIR="${CANDIDATE_DIR:-$ROOT/outputs/families13_20261110_174922}"
if [[ ! -f "$CANDIDATE_DIR/dev_009.sqlite" || ! -f "$CANDIDATE_DIR/dev_012.sqlite" ]]; then
  echo "Missing 13-shop candidate build: $CANDIDATE_DIR" >&2
  exit 2
fi
APPROVE=0
APPROVER=""
if [[ "${1:-}" == "--approve" ]]; then
  APPROVE=1
  APPROVER="${2:-}"
  if [[ -z "$APPROVER" ]]; then echo "Missing human approver" >&2; exit 2; fi
elif [[ "$#" -ne 0 ]]; then
  echo 'Usage: bash scripts/semantic_phase_13.sh [--approve "Data owner"]' >&2
  exit 2
fi
OUTPUT="$ROOT/outputs/semantic13_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT"
echo "=== SEMANTIC INVENTORY ALL 13 CANDIDATE FAMILIES ==="
python3 scripts/triage_13_semantics.py \
  --candidates "$CANDIDATE_DIR" \
  --output "$OUTPUT/triage_13.json"
echo "=== DEV009 RAW INVOICE -> MART AUDIT ==="
qa009=0
python3 scripts/dev009_semantic_release.py \
  --source "$DATA_ROOT/public_test/data/dev_009/danh_sach_hoa_don.csv" \
  --candidate "$CANDIDATE_DIR/dev_009.sqlite" \
  --output "$OUTPUT/dev_009_release" \
  --report "$OUTPUT/dev009_acceptance.json" || qa009=$?
echo "=== DEV012 RAW SERVICE -> MART AUDIT ==="
qa012=0
python3 scripts/dev012_semantic_release.py \
  --source "$DATA_ROOT/public_test/data/dev_012/SoSuaXe.xlsx" \
  --candidate "$CANDIDATE_DIR/dev_012.sqlite" \
  --output "$OUTPUT/dev_012_release" \
  --report "$OUTPUT/dev012_acceptance.json" || qa012=$?
echo "=== FAMILY PHASE SUMMARY ==="
python3 - "$OUTPUT" <<'PY'
import json,sys
from pathlib import Path
folder=Path(sys.argv[1])
for shop in ('009','012'):
 p=folder/f'dev{shop}_acceptance.json'
 if p.is_file():
  r=json.loads(p.read_text())
  print('dev_'+shop,'accepted=',r.get('accepted'),
        'errors=',r.get('error_count'),'source_counts=',
        {k:v for k,v in r.items() if k in (
          'unique_invoice_count','daily_subtotals_not_orders',
          'identical_export_duplicate_copies','repair_visits','sheet_notes_excluded')})
  print('  KPI candidates:',r.get('kpis'))
 else:print('dev_'+shop,'NO REPORT: audit exception')
print('Triage:',folder/'triage_13.json')
PY
if [[ "$qa009" -ne 0 || "$qa012" -ne 0 ]]; then
 echo "SEMANTIC QA FAILED. No production releases issued." >&2
 echo "Inspect reports under $OUTPUT" >&2
 exit 2
fi
if [[ "$APPROVE" -eq 1 ]]; then
 echo "=== HUMAN-AUTHORIZED DEV009 SCOPED RELEASE ==="
 python3 scripts/dev009_semantic_release.py \
   --source "$DATA_ROOT/public_test/data/dev_009/danh_sach_hoa_don.csv" \
   --candidate "$CANDIDATE_DIR/dev_009.sqlite" \
   --output "$OUTPUT/dev_009_release" \
   --approve --approved-by "$APPROVER"
 echo "=== HUMAN-AUTHORIZED DEV012 SCOPED RELEASE ==="
 python3 scripts/dev012_semantic_release.py \
   --source "$DATA_ROOT/public_test/data/dev_012/SoSuaXe.xlsx" \
   --candidate "$CANDIDATE_DIR/dev_012.sqlite" \
   --output "$OUTPUT/dev_012_release" \
   --approve --approved-by "$APPROVER"
 echo '=== TWO SCOPED FAMILY RELEASES COMPLETED ==='
else
 echo "=== SEMANTIC QA PASS (NO RELEASES: explicit --approve required) ==="
fi
echo "Reports: $OUTPUT"
echo "Other 11 shop families are still candidate-only."
