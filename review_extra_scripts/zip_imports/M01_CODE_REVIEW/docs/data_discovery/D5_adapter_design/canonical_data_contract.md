# D5 – Canonical Data Contract (design v0.1)

**Status:** DESIGN_PROPOSED. Logical names below are NEW canonical field names, **not assertions about physical source columns**. D1 headers are preliminary; D4 profile and raw archive have now been supplied; physical headers are observed, but business meanings and canonical mappings still require approval. No physical mapping is approved.

## Grain and entities

Emit separate typed collections; do not flatten everything into `sales`:

| Entity | One record represents | Core logical fields (proposed) |
|---|---|---|
| `business_event` | one business event at source-supported grain | `event_uid`, `shop_id`, `event_type`, `event_date`, `source_event_id`, `source_provenance` |
| `document` | one source document/invoice/ticket where observed | `document_uid`, `event_uid`, `source_document_id`, `document_total`, `currency` |
| `line_item` | one observed product/service/adjustment line | `line_uid`, `document_uid`, `event_uid`, `item_ref`, `quantity`, `unit_raw`, `unit_price`, `line_amount`, `line_kind` |
| `payment` | one independently observed payment | `payment_uid`, `event_uid`, `document_uid`, `payment_amount`, `payment_date`, `payment_method` |
| `inventory_movement` | one stock movement | `movement_uid`, `event_uid`, `item_ref`, `quantity`, `unit_raw`, `batch_id`, `expiry_date` |
| `receivable_event` | one debt/collection/installment entry | `receivable_uid`, `event_uid`, `document_uid`, `amount`, `event_date` |
| `service_event` | one service/repair/warranty visit or lifecycle event | `service_uid`, `event_uid`, `serial_number`, `staff_ref`, `service_status` |
| `adjustment` | one separately identifiable adjustment | `adjustment_uid`, `event_uid`, `document_uid`, `adjustment_type`, `adjustment_amount` |

`source_provenance` (mandatory on every emitted record): `shop_id`, `source_file`, `source_object` (sheet/table), `source_row` (nullable for non-row-based aggregates), `source_record_locator`, `adapter_family`, `adapter_version`, `config_version`, `profile_fingerprint`. Generated `*_uid` is an **internal deterministic technical identifier**, never a fabricated source business ID; its generation algorithm must be versioned and scoped to the source locator. Preserve raw source values in a traceable sidecar or raw-value references.

## Types and semantics

- Identifiers: UTF-8 strings; source IDs remain nullable and are never filled with fabricated business IDs.
- Date/time: ISO 8601 date or offset-aware timestamp only after an explicit, tested parsing rule. Preserve raw date and distinguish transaction, invoice, payment and service dates.
- Monetary values: decimal (base-10) with declared currency and source scale; never floating-point for accounting. `document_total`, `line_amount`, `payment_amount`, `adjustment_amount` are **different concepts**.
- Quantities: decimal and explicit `unit_raw`; conversions require approved unit rules. Negative values do not automatically mean returns.
- Missing, unknown and not-applicable are distinct in diagnostics. No synthetic line items for summary-only invoices.
- `event_type` is an extensible controlled vocabulary (`sale`, `return`, `payment`, `purchase`, `inventory`, `service`, `warranty`, `receivable`, `expense`, `unknown`); use `unknown` until classified.
- Foreign references are nullable when the source has no reliable linkage. Never join on name similarity without an approved rule.

## Integrity and reconciliation

A document-to-line relation is 1:N when evidenced; payment-to-document may be N:M or unknown. Aggregate each independently before reconciliation to avoid multiplication from many-to-many joins. Report source totals, line sums, payment sums and adjustments separately, with a tolerance explicitly configured and never silently assume equality.

## Evolution

Contract version `0.1.0`; additive nullable fields can be minor versions, changed meaning/grain requires major version. Downstream consumers check `contract_version`, `validation_status` and `mapping_approval_status`; blocked/unverified output is not production data.

## D3 concept trace

- `event_date` → candidate `event_date` (D3 conceptual only; source mapping unverified).
- `business_event_id` → candidate `source_event_id` (D3 conceptual only; source mapping unverified).
- `event_type` → candidate `event_type` (D3 conceptual only; source mapping unverified).
- `counterparty/customer` → candidate `customer_ref` (D3 conceptual only; source mapping unverified).
- `item_or_service` → candidate `item_ref` (D3 conceptual only; source mapping unverified).
- `quantity` → candidate `quantity` (D3 conceptual only; source mapping unverified).
- `unit` → candidate `unit_raw / unit_normalized` (D3 conceptual only; source mapping unverified).
- `unit_price` → candidate `unit_price` (D3 conceptual only; source mapping unverified).
- `line_amount` → candidate `line_amount` (D3 conceptual only; source mapping unverified).
- `document_total` → candidate `document_total` (D3 conceptual only; source mapping unverified).
- `payment_event` → candidate `payment_amount` (D3 conceptual only; source mapping unverified).
- `discount_adjustment` → candidate `adjustment_type + adjustment_amount` (D3 conceptual only; source mapping unverified).
- `return_or_refund` → candidate `return_event / signed_quantity` (D3 conceptual only; source mapping unverified).
- `inventory_movement` → candidate `inventory_event` (D3 conceptual only; source mapping unverified).
- `product_batch_expiry` → candidate `batch_id, expiry_date` (D3 conceptual only; source mapping unverified).
- `serial_imei` → candidate `serial_number` (D3 conceptual only; source mapping unverified).
- `debt_installment` → candidate `receivable_event` (D3 conceptual only; source mapping unverified).
- `warranty_service` → candidate `service_event` (D3 conceptual only; source mapping unverified).
- `employee_mechanic` → candidate `staff_ref + raw_staff_name` (D3 conceptual only; source mapping unverified).
- `source_provenance` → candidate `source_file, source_object, source_row, adapter_version` (D3 conceptual only; source mapping unverified).
