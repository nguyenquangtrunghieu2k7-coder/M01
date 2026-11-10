import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.datamate.m01_data_processing.generic_profiler import (
    detect_header, profile_rows, run_profiler
)

class TestGenericProfiler(unittest.TestCase):
    def test_null_duplicate_and_candidate_key(self):
        result = profile_rows(
            [("A", 10), ("B", 20), ("B", 20), ("C", None)],
            ["code", "amount"], {"format": "test"}
        )
        self.assertEqual(result["shape"]["row_count"], 4)
        self.assertEqual(result["duplicate_rows"], 1)
        self.assertEqual(result["columns"][1]["null_count"], 1)
        self.assertEqual(result["candidate_key_columns"], [])

    def test_candidate_key(self):
        result = profile_rows([("x",), ("y",)], ["id"], {"format": "test"})
        self.assertEqual(result["candidate_key_columns"], ["id"])

    def test_header_detection(self):
        rows = [
            ("BÁO CÁO BÁN HÀNG", None, None),
            ("Ngày", "Mã đơn", "Thành tiền"),
            ("01/01/2026", "DH01", 100),
        ]
        self.assertEqual(detect_header(rows), 1)

    def test_csv_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input"
            source.mkdir()
            with (source / "sample.csv").open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["id", "value"])
                w.writerow(["1", "10"])
                w.writerow(["2", ""])
            output = root / "out"
            stats = run_profiler(source, output)
            self.assertEqual(stats["objects_profiled"], 1)
            report = json.loads((output / "profile_report.json").read_text())
            self.assertEqual(report[0]["shape"]["row_count"], 2)

    def test_sqlite_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "sample.db"
            conn = sqlite3.connect(db)
            conn.execute("create table sales(id integer, amount real)")
            conn.executemany("insert into sales values (?, ?)", [(1, 2.5), (2, 3.5)])
            conn.commit()
            conn.close()
            output = root / "out"
            stats = run_profiler(db, output)
            self.assertEqual(stats["objects_profiled"], 1)

if __name__ == "__main__":
    unittest.main()
