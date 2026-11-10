# D5 – Implementation Plan

## Baseline and evidence status
- D1 inventory: 177 inventory rows including non-data objects; headers are preliminary candidates, not validated physical mappings.
- D2: 14 shops classified with 14 fine-grained subfamily labels.
- D3: 20 shared business concepts and 14-shop concept coverage matrix; conceptual, not confirmed physical schema.
- D4: runnable generic profiler source, CLI and tests supplied; executed `profile_report.json`, `profile_summary.csv`, `profile_errors.json` and raw `archive.zip` now provided.
- D5: architecture and configuration templates only. No claim that source-to-canonical mappings are production-ready.

## Implementation phases and exit gates
1. **Evidence acquisition**: run D4 against 14 raw shops; archive report, errors, input hashes and D4 version. Exit: all source objects accounted for; errors triaged.
2. **Source-grain verification**: confirm headers, date semantics, keys, line/document/payment grain and monthly drift. Exit: reviewed evidence per source object.
3. **Mapping review**: populate each shop config using exact physical headers from profiles and inspected samples; capture evidence/reviewer/time; approve only verified mappings. Exit: no required unverified mapping.
4. **Core framework**: implement config schema validator, registry, readers, canonical emitter, quarantine and provenance; keep family logic separate from shop config.
5. **Six family plugins**: F01 POS, F02 monthly, F03 multi-ledger, F04 relational, F05 summary, F06 service. Support optional specialized behaviors in config; no forced flattening.
6. **Testing**: golden fixtures from real samples (redacted), schema drift, header ambiguity, duplicate keys, join fanout, payment split, adjustments, returns, service vs sales, summary-only.
7. **Release**: verify all 14 shop routes, reconciliation reports, lineage and contract compatibility. Ship only approved mappings; unapproved shops remain blocked.

## Acceptance criteria
- 14/14 shop IDs routed to one of six families, with D2 original subtype preserved.
- No invented physical column, join key, source ID, amount semantics or fabricated line items.
- Every active mapping points to a profiled physical column with explicit evidence and approval.
- Each emitted record has provenance, version, validation result and source locator.
- Reconciliation is grain-aware; no many-to-many fanout.
- All validation failures are observable; no silent mapping fallback.

## Open decisions
- Final field requiredness by event type; supported currencies and time zones.
- Canonical ID hashing and stable locator policy for mutable Excel rows.
- Thresholds for reconciliation and null rates; privacy handling of customer/IMEI data.
- Raw source and executed D4 report are available; independent semantic/grain/parse/join verification and reviewer approval are still required.

## 2026-11-10 checkpoint
D4 ingestion evidence acquired: 163 profiled objects across 14 shops, no D4 errors. `d4_profile_object_catalog.csv` and `d4_physical_column_evidence.csv` record actual observed labels but NOT source-to-canonical mappings. Next exit gate: review representative raw rows per distinct schema and approve per-shop mappings and parsing.
