# M01 mapping correction (review patch)

## What changed

- All nonblank records are staged **before** any semantic skip, with index-prefixed header labels to retain duplicate/blank columns.
- Validation issues increment `staging_rows.issue_count` only when a new issue is inserted.
- Repeated headers are recorded as an explicit issue and are not emitted as a business transaction.
- `dev_006` order lines resolve product labels via `san_pham(IDCuaHang,MaHangHoa)` and transaction date/status via `don_hang(IDCuaHang,MaHoaDon)`. Duplicate lookup keys fail closed. Lineage for derived fields points to the raw join key, with transformation labeled as lookup.
- `dev_014` monthly sheet mappings include T7/T8/T9 2026.
- Refuses to silently overwrite an existing SQLite output. Use a fresh output directory. `--overwrite` is explicit and **destroys imported reference tables** in old DB, so backup first.

## Source evidence

Actual raw dev_006 POS SQLite source examined: `chi_tiet_don` has 72,411 lines; all 72,411 match `san_pham` on (`IDCuaHang`, `MaHangHoa`), with no missing names. All order lines match `don_hang` on (`IDCuaHang`, `MaHoaDon`). 80 products have unique shop-scoped product keys. 37,833 orders have unique order identifiers. This explains the earlier 72,411 `MISSING_ITEM` errors without inventing data.

## Tests / limitations

- `python -m unittest discover -s tests -v`: 2 regression tests PASS, using small synthetic CSV and SQLite fixtures.
- A complete `dev_006` rebuild on original source was attempted, but did not finish within the execution timeout. It is **not** claimed that the full rebuilt database was QA-approved.
- This is a narrow fix; other shops' unresolved keys, financial reconciliation, and M03 production approval remain open. Do not deploy as production-approved.
- GitHub App branch creation returned 403 `Resource not accessible by integration`, so these changes could not be pushed as a PR automatically in this session.
