# D5 – Adapter Design (evidence-first)

**Status:** architecture designed; D4 profiling evidence attached for 14/14 shops; exact physical headers observed; semantic mappings NOT APPROVED; implementation NOT STARTED.

## Purpose
Convert heterogeneous shop data into a versioned, multi-entity canonical contract for downstream modules without asserting source columns, business keys or relationships that have not been verified against actual D4 profiling and raw source samples.

## Current progress (D1 → D5)
| Stage | Delivered in provided archives | Limit |
|---|---|---|
| D1 | Inventory CSV + README (177 records) | Header candidates are preliminary |
| D2 | Classification of all 14 shops | Families are conceptual |
| D3 | 20 business concepts + coverage matrix | No physical mapping proof |
| D4 | Generic profiler code, CLI, tests | Executed profiler report and raw archive now supplied; inspect evidence catalog |
| D5 | This design package, 6 families, 14 routes, contract, interface, validations and config templates | Activation blocked pending profile + approval |

## Architecture
```text
14 shop source sets (CSV / XLSX / SQLite)
     ↓ source discovery + D4 profile_report.json
shop registry → family router → config gate (FAIL CLOSED)
     ↓
6 family adapters: POS / monthly / multi-ledger / relational / summary / service
     ↓ semantic mapping + grain-aware links + raw provenance
canonical collections: events / documents / lines / payments / inventory / receivables / services / adjustments
     ↓ validation + reconciliation + quarantine
versioned outputs for downstream modules
```

## Six families
See `adapter_family_matrix.csv` and `shop_adapter_registry.csv`. D2's A1–A5/B1–B5/C1–C2/D1 labels are preserved as subtype metadata; grouping into six families is a D5 architecture decision, not a newly observed source fact.

## Evidence and mapping policy
- `DESIGN_PROPOSED`: canonical concept, family and interface design only.
- `CANDIDATE`: preliminary D1/D2/D3 inference; never executable.
- `UNMAPPED`: physical column intentionally null.
- `VERIFIED`: exact D4 profiled source column + source object + sample/meaning verification + reviewer approval.
- `BLOCKED`: absent profile, ambiguous header, schema drift, unsupported relationship or unapproved mapping.

All 14 JSON configs now reference actual D4-profiled source objects; `mappings=[]` remains unchanged and status is `BLOCKED_PENDING_MAPPING_APPROVAL`. This is intentional. A `README` in a shop or D1 `header_candidate` is **not** sufficient evidence to approve mapping.

## Files
- `README.md`: architecture and evidence boundaries.
- `adapter_family_matrix.csv`: six family design decisions.
- `shop_adapter_registry.csv`: 14 shop routes and readiness.
- `canonical_data_contract.md`: logical entities and grain.
- `adapter_interface.md`: proposed API and fail-closed execution.
- `validation_rules.csv`: 20 checks, design-only.
- `implementation_plan.md`: gated rollout plan.
- `configs/*.adapter.json`: 14 blocked shop configs; `configs/family_*.template.json`: six family-level skeletons.

## Next action
D4 report and archive are now present. Inspect rows and validate grain/meaning, parsing policies, joins and mapping proposals; obtain human approval before executing transforms. Do not mark D5 mapping complete before this step.

## Evidence update (2026-11-10)

D4 evidence now includes `profile_report.json` and raw `archive.zip` with 163 profiled objects across 14 shops; `profile_errors.json` contains zero errors. 163 profiled objects have matching source file paths in archive (Unicode-normalized comparison); **matching file paths does not verify a semantic mapping**. See `d4_evidence_manifest.json`, `d4_profile_object_catalog.csv`, `d4_physical_column_evidence.csv`, and `d4_profile_risk_register.csv`. Header labels are directly observed from D4; field semantics, grain, joins, parser decisions, and mappings remain unapproved.

**Privacy:** D4 report may include personal examples; new evidence indexes deliberately omit sample values and archive does not get bundled in this D5 zip.
