#!/usr/bin/env bash
# Create source-complete CANDIDATE staging datasets for 13 non-dev006 families.
# Preserves existing approved dev006 releases and never issues KPI approval.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DATA_ROOT="${DATA_ROOT:-$HOME/Downloads}"
RUN_DIR="$ROOT/outputs/family13_$(date +%Y%m%d_%H%M%S)"
if [[ -e "$RUN_DIR" ]]; then
    echo "Refusing to overwrite $RUN_DIR" >&2
    exit 2
fi
mkdir -p "$RUN_DIR"
echo "=== Synthetic family regression ==="
PYTHONPATH=.:src python3 -m unittest discover -s tests -p 'test_family_staging.py' -v
echo "=== Physical source inventory (13 shops) ==="
python3 scripts/family_inventory.py \
    --data-root "$DATA_ROOT" --output "$RUN_DIR" --write-contracts
echo "=== Family-role staging, one candidate DB per shop ==="
python3 -u scripts/build_family_staging.py \
    --data-root "$DATA_ROOT" \
    --contracts-dir "$RUN_DIR/family_contracts" \
    --output "$RUN_DIR/candidates"
echo "=== Verify all 13 source/grain coverage ==="
python3 - "$RUN_DIR" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
inv=json.loads((root/'family_inventory_audit.json').read_text())
stage=json.loads((root/'candidates/family_stage_manifest.json').read_text())
assert inv['inventory_pass_count']==13, inv
assert stage['staging_pass_count']==13, stage
assert inv['source_objects']==146, inv['source_objects']
assert stage['source_objects']==146, stage['source_objects']
assert all(not x['production_approved'] for x in stage['shops_detail'])
print(f"PASS: {stage['staging_pass_count']}/13 shops; "
      f"{stage['source_objects']}/146 source objects; "
      f"{stage['staged_rows']} nonblank physical rows staged")
print("Inventory:",root/'family_inventory_audit.json')
print("Manifest:",root/'candidates/family_stage_manifest.json')
print("Candidate SQLite directory:",root/'candidates')
print("Status: CANDIDATE_NOT_APPROVED. Semantic M03 KPI acceptance pending.")
PY
