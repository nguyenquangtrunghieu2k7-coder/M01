import csv
import json
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
rows = []
processed = 0

for shop in ["dev009", "dev002", "dev010", "dev012"]:
    db = root / f"{shop}_demo.sqlite"

    if not db.is_file():
        print(f"SKIP {shop}: database not found")
        continue

    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='business_catalog'"
            ).fetchone()

            if not exists:
                print(f"SKIP {shop}: business_catalog missing")
                continue

            record = conn.execute(
                "SELECT catalog_json FROM business_catalog LIMIT 1"
            ).fetchone()

            if record is None:
                print(f"SKIP {shop}: catalog empty")
                continue

            cat = json.loads(record[0])
            shop_rows = []

            for entity, num in cat.get("row_counts", {}).items():
                if num:
                    shop_rows.append({
                        "shop": cat["shop_id"],
                        "kind": "mart",
                        "name": entity,
                        "count": num,
                        "status": cat["validation_status"],
                    })

            for name, num in cat.get("issue_counts", {}).items():
                shop_rows.append({
                    "shop": cat["shop_id"],
                    "kind": "issue",
                    "name": name,
                    "count": num,
                    "status": cat["validation_status"],
                })

            for table in [
                "raw_sources",
                "staging_rows",
                "source_lineage",
                "validation_issues",
            ]:
                count = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]

                shop_rows.append({
                    "shop": cat["shop_id"],
                    "kind": "audit",
                    "name": table,
                    "count": count,
                    "status": cat["validation_status"],
                })

        rows.extend(shop_rows)
        processed += 1

        with (root / f"{shop}_catalog.json").open(
            "w", encoding="utf-8"
        ) as f:
            json.dump(cat, f, ensure_ascii=False, indent=2)

        print(f"PASS {shop}: {cat['validation_status']}")

    except (sqlite3.Error, ValueError, KeyError) as exc:
        print(f"FAIL {shop}: {exc}")
        raise

output = root / "QA_SUMMARY.csv"

with output.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f, fieldnames=["shop", "kind", "name", "count", "status"]
    )
    writer.writeheader()
    writer.writerows(rows)

print(f"\nQA SUMMARY: {processed}/4 databases processed")
print(f"Output: {output}")

if processed == 0:
    raise SystemExit("No valid pipeline database available")
