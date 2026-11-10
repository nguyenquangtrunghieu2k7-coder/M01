# D5 – Adapter Interface (design specification)

## Pipeline
`source discovery → D4 profile/evidence lookup → registry routing → config verification → source reader → family parser → semantic mapper → canonical emitter → validation/quarantine → downstream`

## Proposed Python protocol (not implemented in D5)

```python
class Adapter(Protocol):
    family_id: str
    def inspect(self, source_manifest: SourceManifest, profile: ProfileReport) -> InspectionResult: ...
    def validate_config(self, config: AdapterConfig, profile: ProfileReport) -> ValidationReport: ...
    def transform(self, source: SourceBatch, config: ApprovedAdapterConfig) -> Iterator[CanonicalBatch]: ...
    def reconcile(self, batch: CanonicalBatch) -> ReconciliationReport: ...
```

`InspectionResult` includes discovered objects, source grain hypothesis, evidence pointers and unresolved questions. `CanonicalBatch` contains separate entity collections, provenance, rejected records, validation issues and contract version.

## Fail-closed preconditions
1. Exact source object identity and profile fingerprint match; no implicit sheet/table fallback.
2. Every physical column reference is present in the selected D4 profile object; uniqueness of header labels and header-row override confirmed.
3. Each required semantic mapping has `status=VERIFIED`, evidence pointer, reviewer and approval timestamp; `UNMAPPED`/`CANDIDATE` mappings never execute.
4. Explicit type parsing, grain, key/linkage cardinality, date and money semantics are approved.
5. On failure: `BLOCKED` with diagnostic; no guess, no positional fallback, no best-effort silent coercion.

## Config schema sketch
`shop_id`, `family_id`, `config_version`, `contract_version`, `status`, `source_objects[]` (`file_selector`, `object_selector`, `profile_fingerprint`, `header_row_override`, `grain`), `mappings[]` (`canonical_entity`, `canonical_field`, `physical_column`, `status`, `evidence`, `reviewed_by`, `approved_at`, `transform_rule`), `join_rules[]`, `validation_policy`, `unresolved_questions[]`.

`physical_column=null` in templates means no mapping, **not** a physical column named `null`. D1 `header_candidate` must not be promoted automatically to `VERIFIED`.

## D4 integration
D4 output is `profile_report.json` with per-object `source`, `shape`, `columns[]` (`name`, `observed_type`, `null_rate`, etc.), `candidate_key_columns`, `warnings`. Candidate keys are not proven business keys. D4 profiler remains unchanged; D5 consumes its reports. D4 report is now present, but source-schema fingerprint and human-reviewed semantic mappings are still mandatory. Profile presence alone does not authorize mapping or execution.
