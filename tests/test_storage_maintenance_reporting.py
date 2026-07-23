import ast
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTING = ROOT / "app3_parts" / "storage" / "storage_quota_reporting_part.py"


def _human_bytes(value):
    size = float(value or 0)
    units = ["B", "KB", "MB", "GB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024.0
        index += 1
    return f"{int(size)}{units[index]}" if index == 0 else f"{size:.1f}{units[index]}"


def _sqlite_group_size(path):
    return sum(
        os.path.getsize(path + suffix) if os.path.exists(path + suffix) else 0
        for suffix in ("", "-wal", "-shm")
    )


def _load_maintenance_function():
    source = REPORTING.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(REPORTING))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_storage_quota_sqlite_maintenance"
    )
    namespace = {
        "os": os,
        "_storage_quota_human": _human_bytes,
        "_storage_quota_sqlite_group_size": _sqlite_group_size,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(REPORTING), "exec"), namespace)
    return namespace["_storage_quota_sqlite_maintenance"]


class StorageMaintenanceReportingTests(unittest.TestCase):
    def test_deep_maintenance_measures_after_wal_connection_closes(self):
        maintain = _load_maintenance_function()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "maintenance.db")
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            payload = "x" * 2048
            conn.executemany(
                "INSERT INTO records(payload) VALUES (?)",
                [(payload,) for _ in range(1200)],
            )
            conn.commit()
            conn.execute("DELETE FROM records WHERE id > 30")
            conn.commit()
            conn.close()

            before = _sqlite_group_size(db_path)
            result = maintain(db_path, deep=True)
            after = _sqlite_group_size(db_path)

            self.assertTrue(result["ok"], result)
            self.assertTrue(result.get("vacuum"), result)
            self.assertIn("checkpoint_after", result)
            self.assertLess(after, before)
            self.assertEqual(result["before_bytes"], before)
            self.assertEqual(result["after_bytes"], after)
            self.assertEqual(result["freed_bytes"], before - after)
            self.assertGreater(result["freed_bytes"], 0)

    def test_missing_database_remains_a_successful_noop(self):
        maintain = _load_maintenance_function()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = maintain(str(Path(temp_dir) / "missing.db"), deep=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["freed_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
