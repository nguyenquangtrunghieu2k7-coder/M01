#!/usr/bin/env bash
# Semantic triage of all 13 families; source acceptance for 001/009/012.
# Optional explicit human-scoped release; never overwrite candidates or dev006.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DATA_ROOT="${DATA_ROOT:-$HOME/Downloads}"
CANDIDATE_DIR="${CANDIDATE_DIR:-$ROOT/outputs/families13_20261110_174922}"
for shop in 001 009 012; do
  if [[ ! -f "$CANDIDATE_DIR/dev_${shop}.sqlite" ]]; then
    echo "Missing candidate dev_$shop in $CANDIDATE_DIR" >&2; exit 2
  fi
done
APPROVER=""
if [[ "$#" -gt 0 ]]; then
  if [[ "${1:-}" != "--approve" || -z "${2:-}" || "$#" -ne 2 ]]; then
    echo 'Usage: bash scripts/semantic_phase_13.sh [--approve "Data owner"]' >&2
    exit 2
  fi
  APPROVER="$2"
fi
OUTPUT="$ROOT/outputs/semantic13_$(date +%Y%m%d_%H%M%S)"
if [[ -e "$OUTPUT" ]]; then echo "Output exists: $OUTPUT" >&2; exit 2; fi
mkdir -p "$OUTPUT"
echo "=== SEMANTIC TRIAGE 13 FAMILY CANDIDATES ==="
python3 scripts/triage_13_semantics.py \
  --candidates "$CANDIDATE_DIR" --output "$OUTPUT/triage_13.json"

# macOS ships Bash 3.2, which does not support associative arrays.
# Resolve source paths with a case statement instead.
source_for_shop() {
  case "$1" in
    001) printf '%s\\n' "$DATA_ROOT/public_test/data/dev_001/So_chi_tiet_ban_hang.xlsx" ;;
    009) printf '%s\\n' "$DATA_ROOT/public_test/data/dev_009/danh_sach_hoa_don.csv" ;;
    012) printf '%s\\n' "$DATA_ROOT/public_test/data/dev_012/SoSuaXe.xlsx" ;;
    *) echo "Unsupported shop: $1" >&2; return 2 ;;
  esac
}
all_good=1
for shop in 001 009 012; do
  echo "=== DEV_${shop} INDEPENDENT SOURCE -> MART KPI AUDIT ==="
  if ! python3 "scripts/dev${shop}_semantic_release.py" \
       --source "$(source_for_shop "$shop")" \
       --candidate "$CANDIDATE_DIR/dev_${shop}.sqlite" \
       --output "$OUTPUT/dev_${shop}_release" \
       --report "$OUTPUT/dev${shop}_acceptance.json"; then
    all_good=0
  fi
done
echo '=== SEMANTIC QA SUMMARY ==='
python3 - "$OUTPUT" <<'PY'
import json,sys
from pathlib import Path
folder=Path(sys.argv[1])
for shop in ('001','009','012'):
 p=folder/f'dev{shop}_acceptance.json'
 if not p.is_file():
  print('dev_'+shop,'NO QA REPORT — inspect traceback');continue
 report=json.loads(p.read_text())
 print('dev_'+shop,'accepted=',report.get('accepted'),
       'errors=',report.get('error_count'))
 print('  physical counts:',
       {k:v for k,v in report.items() if k in (
        'source_line_rows','daily_subtotal_rows','unique_invoice_count',
        'identical_export_duplicate_copies','daily_subtotals_not_orders',
        'repair_visits','sheet_notes_excluded')})
 print('  source-derived KPI expectations:',report.get('kpis'))
 if report.get('errors'):print('  first errors:',report['errors'][:5])
print('All-family triage:',folder/'triage_13.json')
PY
if [[ "$all_good" -ne 1 ]]; then
  echo "SEMANTIC QA NOT FULLY PASSED. No releases issued." >&2
  echo "Review reports in $OUTPUT" >&2
  exit 2
fi
if [[ -n "$APPROVER" ]]; then
  for shop in 001 009 012; do
    echo "=== HUMAN APPROVED dev_${shop} RELEASE (QA-GATED) ==="
    python3 "scripts/dev${shop}_semantic_release.py" \
      --source "$(source_for_shop "$shop")" \
      --candidate "$CANDIDATE_DIR/dev_${shop}.sqlite" \
      --output "$OUTPUT/dev_${shop}_release" \
      --approve --approved-by "$APPROVER"
  done
  echo '=== THREE SCOPED FAMILY RELEASES COMPLETED ==='
else
  echo '=== ALL THREE SOURCE QA PASS; NO APPROVAL REQUESTED ==='
fi
echo "Audit/results: $OUTPUT"
echo "Other 10 families remain candidate-only pending independent source KPI QA."
