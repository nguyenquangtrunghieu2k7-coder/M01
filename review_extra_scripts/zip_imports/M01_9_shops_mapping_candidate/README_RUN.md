# M01 mapping candidate — nine shops

This is executable code, not a claim of production acceptance. Verified on dev_011 and dev_013 against the uploaded original datasets. Requires Python and openpyxl (`python -m pip install openpyxl`).

From repository root:

```bash
python -m pip install openpyxl
python build_9_shops.py --data-root "$HOME/Downloads" --output "$HOME/Desktop/M01_9_SHOPS_MARTS"
```

The `--data-root` directory must contain `public_test/data/dev_003` ... `dev_014`. Output: nine SQLite files and `mapping_manifest.json`. Existing 5 shop databases must be retained separately. Do not overwrite them.

Every output has raw_sources, staging_rows, validation_issues, source_lineage, business_catalog and 23 mart table schemas. Only evidence-mapped objects generate mart rows. Empty marts are not zero business activity. No official KPI approval.

**Known limitations:** Some sources have multirow headers, blank order IDs, and business-specific quantity/price conventions. These are not inferred. A blank STT in mobile phone journals is not assigned a guessed document ID. Money with ambiguous units is kept in source_values; date parsing is conservative. `source_values` may include PII: don't publish these SQLite files. For large shops processing may take several minutes and require significant disk space.

For M03, only read tables with `business_catalog.capabilities[table] == true` and require separate semantic approval for official metrics.
