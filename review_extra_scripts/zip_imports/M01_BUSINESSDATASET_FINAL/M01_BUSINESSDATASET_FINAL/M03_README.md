# M01 BusinessDataset → M03

## Contents
- databases/dev_001.sqlite through dev_014.sqlite
- manifest.json: source hashes, table counts and catalog
- shop_coverage.csv: per-shop data coverage

## Usage
Read manifest.json and select a shop database.
Connect using SQLite in read-only mode.
Inspect business_catalog and validation_issues before querying marts.

## Data status
PROVISIONAL_NOT_FOR_PRODUCTION.

These databases contain the currently materialized business data.
A successful SQLite integrity check does not certify semantic accuracy.
Some shops lack active mappings and may have empty business marts.
Do not use provisional data for official financial KPIs.

## Privacy
Databases may contain personal or commercially sensitive data.
Transfer only through approved secure channels.
