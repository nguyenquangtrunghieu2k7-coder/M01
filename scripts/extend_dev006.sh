#!/usr/bin/env bash
# Single-command dev006 extended KPI review/release from a prior revenue release.
# No source rebuild and no change to the previous approved SQLite.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ "${1:-}" != "--approve" || -z "${2:-}" ]]; then
  echo 'Usage: bash scripts/extend_dev006.sh --approve "Data owner"' >&2
  exit 2
fi
POS="${POS:-$HOME/Downloads/public_test/data/dev_006/pos.sqlite}"
PRIOR_RELEASE="${PRIOR_RELEASE:-$ROOT/outputs/dev006_rulebook_20261110_161422/release}"
if [[ ! -f "$POS" ]]; then
  echo "ERROR: POS input not found: $POS" >&2
  exit 2
fi
if [[ ! -f "$PRIOR_RELEASE/manifest.json" ]]; then
  echo "ERROR: approved prior release not found: $PRIOR_RELEASE" >&2
  exit 2
fi
OUTPUT="$ROOT/outputs/dev006_extended_$(date +%Y%m%d_%H%M%S)"
echo '=== Extended family KPI synthetic tests ==='
PYTHONPATH=.:src python3 -m unittest discover \
  -s tests -p 'test_dev006_extended_kpis.py' -v
echo '=== Independent source-POS extended QA and scoped release ==='
PYTHONPATH=.:src python3 scripts/release_dev006_extended.py \
  --pos "$POS" \
  --prior-release "$PRIOR_RELEASE" \
  --output "$OUTPUT" \
  --approve --approved-by "$2"
echo '=== EXTENDED DEV006 RELEASE SUCCESS ==='
echo "Release: $OUTPUT"
echo "QA: $OUTPUT/extended_qa_report.json"
echo "Manifest: $OUTPUT/manifest.json"
echo 'Other unimplemented metric/query families remain unapproved.'
