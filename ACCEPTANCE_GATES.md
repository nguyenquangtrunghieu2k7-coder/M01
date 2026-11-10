# M01 Acceptance Gates — honest completion criteria

Each item must be checked for **every supported shop and every source object** before declaring phase complete.

| Gate | Current status | Evidence required |
|---|---|---|
| 14/14 mapping reviewed | NOT MET | reviewer, source-profile fingerprint, field-level semantics and rules |
| 14/14 source patterns supported | NOT MET | runnable adapters, checked source/grain/merge/header semantics |
| Source parsing and isolation | PARTIAL | 4 provisional data sets / 21 source objects |
| Unit conversion graph | NOT MET | shop+product scoped rules, multi-hop consistency tests |
| Transaction/document totals | NOT MET | line/payment/adjustment-level reconciliations, no fanout |
| Source-defined dedup | NOT MET | repeat-record policy, exceptions for ledgers |
| Effective-date snapshots | NOT MET | date evidence, no synthetic history |
| Source tracing | PARTIAL | row+column lineage exists; A1 field positions still needed |
| Catalog | PARTIAL | version, tables, rows, source coverage & capability flags; full field dictionary pending |
| Production approval | NOT MET | all above and explicit human reviewer |

A test-only provisional dataset must never be advertised as a usable production BusinessDataset. All currently provided SQLite files have `PROVISIONAL_NOT_FOR_PRODUCTION` status.
