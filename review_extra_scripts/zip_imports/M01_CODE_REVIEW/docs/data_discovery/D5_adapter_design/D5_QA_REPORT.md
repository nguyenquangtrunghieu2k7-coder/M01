# D5 Final QA Report

Date: 2026-11-10
Project: ZAIC_DataMate

## Verification

- Unit tests: 11/11 PASS
- JSON syntax validation: 14/14 PASS
- Integration execution: 14/14 PASS
- Production approval: PENDING

## Integration Results

| Shop | Status | Orders | Issues |
|---|---|---:|---:|
| dev_001 | PROVISIONAL_NOT_FOR_PRODUCTION | 35543 | 673 |
| dev_002 | PROVISIONAL_NOT_FOR_PRODUCTION | 3069 | 142 |
| dev_003 | PROVISIONAL_NOT_FOR_PRODUCTION | 0 | 0 |
| dev_004 | PROVISIONAL_NOT_FOR_PRODUCTION | 0 | 0 |
| dev_005 | PROVISIONAL_NOT_FOR_PRODUCTION | 0 | 0 |
| dev_006 | PROVISIONAL_NOT_FOR_PRODUCTION | 0 | 0 |
| dev_007 | PROVISIONAL_NOT_FOR_PRODUCTION | 0 | 0 |
| dev_008 | PROVISIONAL_NOT_FOR_PRODUCTION | 0 | 0 |
| dev_009 | PROVISIONAL_NOT_FOR_PRODUCTION | 22798 | 848 |
| dev_010 | PROVISIONAL_NOT_FOR_PRODUCTION | 23311 | 4141 |
| dev_011 | PROVISIONAL_NOT_FOR_PRODUCTION | 0 | 0 |
| dev_012 | PROVISIONAL_NOT_FOR_PRODUCTION | 0 | 23 |
| dev_013 | PROVISIONAL_NOT_FOR_PRODUCTION | 0 | 0 |
| dev_014 | PROVISIONAL_NOT_FOR_PRODUCTION | 0 | 0 |

Total orders: 84,721

Total validation issues: 5,827

## Interpretation

All 14 configurations completed provisional pipeline execution.

Zero orders does not imply zero source records.

Validation issues require review; they are not automatically
equivalent to failed pipeline executions.

All catalogs are PROVISIONAL_NOT_FOR_PRODUCTION.

Semantic correctness and production readiness are not certified.

## Data Governance

Source datasets remain external to the repository.
Local QA databases are not included in the handover.
