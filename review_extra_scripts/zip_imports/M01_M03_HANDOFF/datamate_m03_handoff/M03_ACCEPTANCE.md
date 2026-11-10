# M01 → M03 Consumer Acceptance

Shops inspected: 14/14
M03 official-KPI eligible: 0/14

## Blockers

- dev_001: mapping not approved
- dev_002: mapping not approved
- dev_003: no active source mapping, mapping not approved
- dev_004: no active source mapping, mapping not approved
- dev_005: no active source mapping, mapping not approved
- dev_006: no active source mapping, mapping not approved
- dev_007: no active source mapping, mapping not approved
- dev_008: no active source mapping, mapping not approved
- dev_009: mapping not approved
- dev_010: mapping not approved
- dev_011: no active source mapping, mapping not approved
- dev_012: mapping not approved
- dev_013: no active source mapping, mapping not approved
- dev_014: no active source mapping, mapping not approved

## Required for M03
- Read manifest.json and schema_contract.json first.
- Treat unsupported tables and capabilities as unknown, not zero.
- Query database files only when present and approved for intended use.
- Preserve shop_id and version_id in every downstream result.
- Never interpret PROVISIONAL_NOT_FOR_PRODUCTION as approved.
- Database and raw data remain local; metadata may still contain sensitive source paths and must be reviewed before sharing.
