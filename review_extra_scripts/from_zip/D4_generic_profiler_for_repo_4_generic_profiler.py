"""Generic, non-transforming profiler for CSV, XLSX and SQLite sources."""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sqlite3
import statistics
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

SUPPORTED = {".csv", ".xlsx", ".db", ".sqlite", ".sqlite3"}
NULL_STRINGS = {"", "null", "none", "nan", "n/a", "na", "-", "--"}

def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return None if value.casefold() in NULL_STRINGS else value
    return value

def _type_of(v: Any) -> str:
    if v is None:
        return "empty"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (datetime, date)):
        return "date"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return "empty"
        if re.fullmatch(r"[+-]?\d+", s):
            return "integer"
        if re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+)", s):
            return "float"
        # Conservative date recognition; do not parse or rewrite source values.
        if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", s):
            return "date"
        return "text"
    return "text"

def _json_value(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)

def _header_score(row: tuple[Any, ...]) -> float:
    vals = [_clean(v) for v in row]
    nonempty = [v for v in vals if v is not None]
    if not nonempty:
        return -1
    strings = sum(isinstance(v, str) for v in nonempty)
    unique = len({str(v).strip().casefold() for v in nonempty})
    return len(nonempty) + 2 * strings / len(nonempty) + unique / len(nonempty)

def detect_header(rows: list[tuple[Any, ...]], max_scan: int = 10) -> int:
    """Return zero-based candidate header row; heuristic only."""
    if not rows:
        return 0
    return max(range(min(max_scan, len(rows))), key=lambda i: _header_score(rows[i]))

def _safe_name(value: Any, idx: int) -> str:
    value = _clean(value)
    return str(value) if value is not None else f"__unnamed_{idx+1}"

def profile_rows(
    rows: Iterable[tuple[Any, ...]],
    headers: list[str],
    source: dict[str, Any],
    distinct_cap: int = 100_000,
    sample_size: int = 5,
) -> dict[str, Any]:
    ncols = len(headers)
    counts = [0] * ncols
    nulls = [0] * ncols
    distinct = [set() for _ in headers]
    capped = [False] * ncols
    samples: list[list[Any]] = [[] for _ in headers]
    types: list[Counter] = [Counter() for _ in headers]
    numeric: list[list[float]] = [[] for _ in headers]
    row_signatures: set[str] = set()
    duplicate_rows = 0
    row_count = 0

    for raw in rows:
        row = tuple(raw[:ncols]) + (None,) * max(0, ncols - len(raw))
        row = tuple(_clean(v) for v in row)
        if all(v is None for v in row):
            continue
        row_count += 1
        signature = json.dumps([_json_value(v) for v in row], ensure_ascii=False, sort_keys=True)
        if signature in row_signatures:
            duplicate_rows += 1
        else:
            row_signatures.add(signature)
        for i, v in enumerate(row):
            counts[i] += 1
            if v is None:
                nulls[i] += 1
                types[i]["empty"] += 1
                continue
            types[i][_type_of(v)] += 1
            sval = str(v)
            if len(samples[i]) < sample_size and sval not in [str(x) for x in samples[i]]:
                samples[i].append(_json_value(v))
            if len(distinct[i]) < distinct_cap:
                distinct[i].add(sval)
            else:
                capped[i] = True
            if _type_of(v) in {"integer", "float"}:
                try:
                    numeric[i].append(float(v))
                except (TypeError, ValueError):
                    pass

    columns = []
    for i, name in enumerate(headers):
        nonempty_types = [t for t, c in types[i].items() if t != "empty" and c]
        observed = "empty" if not nonempty_types else (
            nonempty_types[0] if len(nonempty_types) == 1 else "mixed"
        )
        col = {
            "name": name,
            "null_count": nulls[i],
            "null_rate": round(nulls[i] / row_count, 6) if row_count else 0.0,
            "distinct_count": len(distinct[i]),
            "distinct_is_capped": capped[i],
            "observed_type": observed,
            "type_counts": dict(types[i]),
            "sample_values": samples[i],
        }
        if numeric[i]:
            vals = numeric[i]
            col["numeric_stats"] = {
                "count": len(vals), "min": min(vals), "max": max(vals),
                "mean": round(statistics.fmean(vals), 6),
            }
        columns.append(col)

    candidate_keys = [
        c["name"] for c in columns
        if row_count > 0 and c["null_count"] == 0
        and c["distinct_count"] == row_count and not c["distinct_is_capped"]
    ]
    return {
        "source": source,
        "shape": {"row_count": row_count, "column_count": ncols},
        "columns": columns,
        "duplicate_rows": duplicate_rows,
        "candidate_key_columns": candidate_keys,
        "warnings": [],
    }

def _rows_csv(path: Path) -> tuple[list[str], Iterator[tuple[Any, ...]], int]:
    f = path.open("r", encoding="utf-8-sig", newline="")
    reader = csv.reader(f)
    try:
        header = next(reader)
    except StopIteration:
        f.close()
        return [], iter(()), 0
    def gen():
        try:
            for row in reader:
                yield tuple(row)
        finally:
            f.close()
    return [_safe_name(v, i) for i, v in enumerate(header)], gen(), 1

def _profile_csv(path: Path) -> list[dict[str, Any]]:
    headers, rows, header_row = _rows_csv(path)
    result = profile_rows(rows, headers, {"path": str(path), "format": "csv", "object": path.name})
    result["source"]["header_row"] = header_row
    return [result]

def _profile_xlsx(path: Path, overrides: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("Thiếu openpyxl. Cài bằng: pip install openpyxl") from exc
    wb = load_workbook(path, read_only=True, data_only=True)
    results = []
    for ws in wb.worksheets:
        cfg = overrides.get(f"{path.name}::{ws.title}", {})
        rows_iter = ws.iter_rows(values_only=True)
        preview = []
        for _ in range(10):
            try:
                preview.append(tuple(next(rows_iter)))
            except StopIteration:
                break
        if not preview:
            results.append(profile_rows([], [], {"path": str(path), "format": "xlsx", "object": ws.title}))
            continue
        header_row = int(cfg.get("header_row", detect_header(preview) + 1))
        if header_row < 1:
            header_row = 1
        # Re-open iterator so configured header row is applied exactly.
        all_rows = ws.iter_rows(values_only=True)
        header = None
        for i, row in enumerate(all_rows, start=1):
            if i == header_row:
                header = tuple(row)
                break
        headers = [_safe_name(v, i) for i, v in enumerate(header or ())]
        def data_rows():
            for row in all_rows:
                yield tuple(row)
        result = profile_rows(data_rows(), headers, {
            "path": str(path), "format": "xlsx", "object": ws.title,
            "header_row": header_row,
        })
        if len(set(headers)) != len(headers):
            result["warnings"].append("Tên cột bị trùng sau khi đọc header.")
        if any(h.startswith("__unnamed_") for h in headers):
            result["warnings"].append("Có ô header trống; tên __unnamed_* chỉ là placeholder.")
        results.append(result)
    wb.close()
    return results

def _profile_sqlite(path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    results = []
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        for (table,) in tables:
            escaped = table.replace('"', '""')
            info = conn.execute(f'PRAGMA table_info("{escaped}")').fetchall()
            headers = [r[1] for r in info]
            cur = conn.execute(f'SELECT * FROM "{escaped}"')
            result = profile_rows((tuple(r) for r in cur), headers, {
                "path": str(path), "format": "sqlite", "object": table,
                "declared_schema": [{"name": r[1], "type": r[2], "notnull": bool(r[3]), "pk": bool(r[5])} for r in info],
            })
            results.append(result)
    finally:
        conn.close()
    return results

def run_profiler(input_path: Path, output_dir: Path, overrides_path: Path | None = None) -> dict[str, Any]:
    overrides = {}
    if overrides_path and overrides_path.exists():
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    files = [input_path] if input_path.is_file() else sorted(p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED)
    profiles, errors = [], []
    for path in files:
        try:
            suffix = path.suffix.lower()
            if suffix == ".csv":
                profiles.extend(_profile_csv(path))
            elif suffix == ".xlsx":
                profiles.extend(_profile_xlsx(path, overrides))
            elif suffix in {".db", ".sqlite", ".sqlite3"}:
                profiles.extend(_profile_sqlite(path))
        except Exception as exc:
            errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "profile_report.json").write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "profile_errors.json").write_text(
        json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "profile_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "path", "format", "object", "row_count", "column_count", "duplicate_rows",
            "candidate_key_columns", "warnings"
        ])
        writer.writeheader()
        for p in profiles:
            s = p["source"]
            writer.writerow({
                "path": s.get("path"), "format": s.get("format"), "object": s.get("object"),
                "row_count": p["shape"]["row_count"], "column_count": p["shape"]["column_count"],
                "duplicate_rows": p["duplicate_rows"],
                "candidate_key_columns": ";".join(p["candidate_key_columns"]),
                "warnings": ";".join(p["warnings"]),
            })
    return {"files_discovered": len(files), "objects_profiled": len(profiles), "errors": len(errors)}

def main():
    parser = argparse.ArgumentParser(description="Generic non-transforming data profiler")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overrides", type=Path)
    args = parser.parse_args()
    summary = run_profiler(args.input, args.output, args.overrides)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
