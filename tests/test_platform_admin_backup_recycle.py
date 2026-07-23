import ast
import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BACKUP_SOURCE = ROOT / "app3_parts" / "storage" / "platform_admin_chat_backup_part.py"
RECYCLE_SOURCE = ROOT / "app3_parts" / "storage" / "platform_admin_audit_recycle_part.py"
REGISTRY_SOURCE = ROOT / "app3_parts" / "tools" / "file_registry_store_part.py"
KNOWLEDGE_CLEANUP_SOURCE = ROOT / "app3_parts" / "knowledge" / "knowledge_cleanup_part.py"
KNOWLEDGE_IMPORT_SOURCE = ROOT / "app3_parts" / "knowledge" / "knowledge_document_import_part.py"
KNOWLEDGE_UI_SOURCE = ROOT / "static" / "index3" / "js" / "index3-knowledge-base-ui.js"
ADMIN_UI_SOURCE = ROOT / "static" / "platform-admin" / "platform-admin.js"
ZH_I18N_SOURCE = ROOT / "static" / "i18n" / "zh-CN.js"


def _load_functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    missing = set(names) - {node.name for node in selected}
    if missing:
        raise AssertionError(f"missing functions: {sorted(missing)}")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def _human_bytes(value):
    return f"{int(value or 0)}B"


def _backup_namespace(base_dir):
    names = {
        "_platform_admin_backup_dir",
        "_platform_admin_backup_target_specs",
        "_platform_admin_backup_resolve_target",
        "_platform_admin_backup_snapshot_file",
        "_platform_admin_backup_stage_snapshot",
        "_platform_admin_sha256_file",
        "_platform_admin_create_backup",
        "_platform_admin_restore_stage_archive",
        "_platform_admin_restore_remove_path",
        "_platform_admin_restore_apply",
    }
    namespace = {
        "BASE_DIR": str(base_dir),
        "APP_DATA_DIR": str(base_dir),
        "_app_data_path": lambda *parts: os.path.join(base_dir, *parts),
        "os": os,
        "shutil": shutil,
        "tempfile": tempfile,
        "hashlib": hashlib,
        "datetime": datetime,
        "uuid": uuid,
        "time": time,
        "json": json,
        "re": re,
        "_platform_admin_rel_path": lambda path: os.path.relpath(path, base_dir).replace("\\", "/"),
        "_storage_quota_fmt_ts": lambda value: str(value),
        "_storage_quota_human": _human_bytes,
        "_platform_admin_audit_append": lambda *args, **kwargs: {},
    }
    return _load_functions(BACKUP_SOURCE, names, namespace)


def _recycle_namespace(base_dir):
    names = {
        "_platform_admin_json_atomic_write",
        "_platform_admin_recycle_dir",
        "_platform_admin_recycle_store_file",
        "_platform_admin_recycle_load",
        "_platform_admin_recycle_save",
        "_platform_admin_recycle_public_row",
        "_platform_admin_recycle_payload",
        "_platform_admin_recycle_artifacts",
        "_platform_admin_recycle_cleanup_artifact_dirs",
        "_platform_admin_recycle_validate_source_path",
        "_platform_admin_recycle_restore_registry_context",
        "_platform_admin_recycle_remove_registry_context",
        "_platform_admin_recycle_paths",
        "_platform_admin_recycle_cancel",
        "_platform_admin_recycle_action",
        "_platform_admin_recycle_purge_all",
    }
    state = {"files": {}, "updated_at": 0.0}
    lock = threading.Lock()
    namespace = {
        "BASE_DIR": str(base_dir),
        "APP_DATA_DIR": str(base_dir),
        "_app_data_path": lambda *parts: os.path.join(base_dir, *parts),
        "os": os,
        "shutil": shutil,
        "json": json,
        "uuid": uuid,
        "time": time,
        "re": re,
        "_FILE_REGISTRY_STATE": state,
        "_FILE_REGISTRY_LOCK": lock,
        "_file_registry_load": lambda: None,
        "_file_registry_save": lambda **kwargs: True,
        "_storage_quota_human": _human_bytes,
        "_storage_quota_fmt_ts": lambda value: f"ts:{value}",
        "_platform_admin_rel_path": lambda path: os.path.relpath(path, base_dir).replace("\\", "/") if path else "",
        "_platform_admin_audit_append": lambda *args, **kwargs: {},
        "_platform_admin_files_payload": lambda **kwargs: {"ok": True, "rows": []},
        "_platform_admin_safe_int": lambda value, default, minimum=0, maximum=100000: max(minimum, min(maximum, int(value or default))),
        "_platform_admin_paginate_rows": lambda rows, page=1, page_size=40: (rows, {"page": page, "page_size": page_size, "total": len(rows)}),
        "_platform_admin_row_matches_query": lambda row, query: str(query).lower() in json.dumps(row, ensure_ascii=False).lower(),
    }
    return _load_functions(RECYCLE_SOURCE, names, namespace)


class PlatformAdminBackupTests(unittest.TestCase):
    def test_sqlite_backup_uses_consistent_snapshot_and_includes_state_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            db_path = base / "knowledge_base.db"
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA wal_autocheckpoint=0")
            conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
            conn.executemany("INSERT INTO records(value) VALUES (?)", [(f"row-{i}",) for i in range(80)])
            conn.commit()
            (base / "file_text_store").mkdir()
            (base / "file_text_store" / "doc.txt").write_text("full text", encoding="utf-8")
            recycle_file = base / "platform_admin_recycle" / "files" / "recycle_1" / "item.bin"
            recycle_file.parent.mkdir(parents=True)
            recycle_file.write_bytes(b"recycled")
            ns = _backup_namespace(base)
            stage = base / "stage"
            stage.mkdir()

            entries, targets = ns["_platform_admin_backup_stage_snapshot"](str(stage))
            conn.close()

            paths = {entry["path"] for entry in entries}
            self.assertIn("knowledge_base.db", paths)
            self.assertNotIn("knowledge_base.db-wal", paths)
            self.assertNotIn("knowledge_base.db-shm", paths)
            self.assertIn("file_text_store/doc.txt", paths)
            self.assertIn("platform_admin_recycle/files/recycle_1/item.bin", paths)
            self.assertTrue(any(item["path"] == "file_text_store" and item["present"] for item in targets))
            snapshot = sqlite3.connect(stage / "data" / "knowledge_base.db")
            try:
                count = snapshot.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            finally:
                snapshot.close()
            self.assertEqual(count, 80)

    def test_restore_can_recreate_currently_missing_target(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            target = base / "auth_account_profile_store.json"
            target.write_text('{"profile":"before"}', encoding="utf-8")
            ns = _backup_namespace(base)
            created = ns["_platform_admin_create_backup"]("test")
            backup_path = base / "platform_admin_backups" / created["backup"]["filename"]
            target.unlink()
            stage = base / "restore-stage"
            rollback = base / "restore-rollback"
            stage.mkdir()
            rollback.mkdir()

            _, entries, roots, skipped = ns["_platform_admin_restore_stage_archive"](str(backup_path), str(stage))
            restored = ns["_platform_admin_restore_apply"](str(stage), str(rollback), entries, roots)

            self.assertEqual(skipped, [])
            self.assertIn("auth_account_profile_store.json", restored)
            self.assertEqual(target.read_text(encoding="utf-8"), '{"profile":"before"}')

    def test_hash_mismatch_is_rejected_before_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "file_registry_store.json").write_text('{"files":{}}', encoding="utf-8")
            ns = _backup_namespace(base)
            created = ns["_platform_admin_create_backup"]("test")
            backup_path = base / "platform_admin_backups" / created["backup"]["filename"]
            with zipfile.ZipFile(backup_path, "r") as source:
                archive = {name: source.read(name) for name in source.namelist()}
            archive["data/file_registry_store.json"] = b"tampered"
            with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as output:
                for name, payload in archive.items():
                    output.writestr(name, payload)
            stage = base / "restore-stage"
            stage.mkdir()

            with self.assertRaisesRegex(ValueError, "备份校验失败"):
                ns["_platform_admin_restore_stage_archive"](str(backup_path), str(stage))

    def test_recycle_entity_directory_is_restored_as_exact_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            entity = base / "platform_admin_recycle" / "files" / "recycle_1" / "item.bin"
            entity.parent.mkdir(parents=True)
            entity.write_bytes(b"original")
            ns = _backup_namespace(base)
            created = ns["_platform_admin_create_backup"]("recycle")
            backup_path = base / "platform_admin_backups" / created["backup"]["filename"]
            entity.write_bytes(b"changed")
            stale = entity.parent.parent / "stale.bin"
            stale.write_bytes(b"stale")
            stage = base / "restore-stage"
            rollback = base / "restore-rollback"
            stage.mkdir()
            rollback.mkdir()

            _, entries, roots, _ = ns["_platform_admin_restore_stage_archive"](str(backup_path), str(stage))
            restored = ns["_platform_admin_restore_apply"](str(stage), str(rollback), entries, roots)

            self.assertIn("platform_admin_recycle/files/", restored)
            self.assertEqual(entity.read_bytes(), b"original")
            self.assertFalse(stale.exists())

    def test_apply_failure_restores_all_previous_files(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            ns = _backup_namespace(base)
            first = base / "file_registry_store.json"
            second = base / "storage_account_files.json"
            first.write_text("old-first", encoding="utf-8")
            second.write_text("old-second", encoding="utf-8")
            stage = base / "stage"
            rollback = base / "rollback"
            (stage / "data").mkdir(parents=True)
            rollback.mkdir()
            staged_first = stage / "data" / first.name
            staged_second = stage / "data" / second.name
            staged_first.write_text("new-first", encoding="utf-8")
            staged_second.write_text("new-second", encoding="utf-8")
            entries = [
                {"path": first.name, "target": str(first), "kind": "file", "root": first.name, "staged": str(staged_first)},
                {"path": second.name, "target": str(second), "kind": "file", "root": second.name, "staged": str(staged_second)},
            ]
            real_move = shutil.move

            def fail_second_stage(source, destination, *args, **kwargs):
                if os.path.abspath(str(source)) == os.path.abspath(str(staged_second)):
                    raise OSError("injected apply failure")
                return real_move(source, destination, *args, **kwargs)

            with mock.patch.object(shutil, "move", side_effect=fail_second_stage):
                with self.assertRaisesRegex(OSError, "injected apply failure"):
                    ns["_platform_admin_restore_apply"](str(stage), str(rollback), entries, [])

            self.assertEqual(first.read_text(encoding="utf-8"), "old-first")
            self.assertEqual(second.read_text(encoding="utf-8"), "old-second")


class PlatformAdminRecycleTests(unittest.TestCase):
    def test_multi_file_restore_recovers_files_registry_and_removes_empty_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            first = base / "uploads_local" / "one.txt"
            second = base / "uploads_local" / "one.preview.png"
            first.parent.mkdir()
            first.write_text("one", encoding="utf-8")
            second.write_bytes(b"preview")
            ns = _recycle_namespace(base)

            result = ns["_platform_admin_recycle_paths"](
                [str(first), str(second)],
                source_kind="file_library",
                display_name="one.txt",
                restore_context={"file_registry_records": {"file-1": {"file_id": "file-1", "filename": "one.txt"}}},
            )
            recycle_dir = Path(result["record"]["artifacts"][0]["recycle_path"]).parent
            self.assertFalse(first.exists())
            self.assertEqual(result["file"]["artifact_count"], 2)

            ns["_platform_admin_recycle_action"](result["file"]["id"], "restore")

            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())
            self.assertIn("file-1", ns["_FILE_REGISTRY_STATE"]["files"])
            self.assertFalse(recycle_dir.exists())

    def test_index_save_failure_moves_every_file_back(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            first = base / "uploads_local" / "one.txt"
            second = base / "uploads_local" / "two.txt"
            first.parent.mkdir()
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            ns = _recycle_namespace(base)
            ns["_platform_admin_recycle_save"] = mock.Mock(side_effect=OSError("index write failed"))

            with self.assertRaisesRegex(OSError, "index write failed"):
                ns["_platform_admin_recycle_paths"]([str(first), str(second)])

            self.assertEqual(first.read_text(encoding="utf-8"), "one")
            self.assertEqual(second.read_text(encoding="utf-8"), "two")

    def test_restore_refuses_same_name_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            original = base / "uploads_local" / "same.txt"
            original.parent.mkdir()
            original.write_text("old", encoding="utf-8")
            ns = _recycle_namespace(base)
            result = ns["_platform_admin_recycle_paths"]([str(original)])
            original.write_text("new", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "同名文件"):
                ns["_platform_admin_recycle_action"](result["file"]["id"], "restore")

            self.assertEqual(original.read_text(encoding="utf-8"), "new")
            self.assertTrue(Path(result["record"]["artifacts"][0]["recycle_path"]).is_file())

    def test_payload_sorts_latest_first_and_missing_entity_uses_zero_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            ns = _recycle_namespace(base)
            store = {
                "items": {
                    "old": {"id": "old", "filename": "old", "recycled_at": 1, "artifacts": [{"original_path": str(base / "old"), "recycle_path": str(base / "missing"), "size_bytes": 999}]},
                    "new": {"id": "new", "filename": "new", "recycled_at": 2, "artifacts": [{"original_path": str(base / "new"), "recycle_path": str(base / "missing2"), "size_bytes": 888}]},
                }
            }
            ns["_platform_admin_recycle_save"](store)

            payload = ns["_platform_admin_recycle_payload"]()

            self.assertEqual([row["id"] for row in payload["rows"]], ["new", "old"])
            self.assertEqual(payload["total_bytes"], 0)
            self.assertEqual(payload["rows"][0]["missing_count"], 1)

    def test_clear_counts_only_bytes_that_were_really_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            ns = _recycle_namespace(base)
            existing = base / "platform_admin_recycle" / "files" / "one" / "item.bin"
            existing.parent.mkdir(parents=True)
            existing.write_bytes(b"12345")
            store = {
                "items": {
                    "one": {"id": "one", "filename": "one", "recycled_at": 1, "artifacts": [{"original_path": str(base / "one"), "recycle_path": str(existing), "size_bytes": 999}]},
                    "missing": {"id": "missing", "filename": "missing", "recycled_at": 2, "artifacts": [{"original_path": str(base / "missing"), "recycle_path": str(base / "gone"), "size_bytes": 888}]},
                }
            }
            ns["_platform_admin_recycle_save"](store)

            result = ns["_platform_admin_recycle_purge_all"]()

            self.assertEqual(result["purged"], 2)
            self.assertEqual(result["freed_bytes"], 5)
            self.assertFalse(existing.exists())


class PlatformAdminIntegrationBoundaryTests(unittest.TestCase):
    def test_registry_batch_failure_restores_in_memory_snapshot(self):
        state = {
            "files": {
                "main": {"file_id": "main", "filename": "main.txt"},
                "preview": {"file_id": "preview", "filename": "preview.png"},
            },
            "updated_at": 1.0,
        }
        namespace = {
            "_FILE_REGISTRY_STATE": state,
            "_FILE_REGISTRY_LOCK": threading.Lock(),
            "_file_registry_load": lambda: None,
            "_file_registry_save": mock.Mock(side_effect=OSError("save failed")),
            "time": time,
        }
        _load_functions(REGISTRY_SOURCE, {"_file_registry_remove_records"}, namespace)

        with self.assertRaisesRegex(OSError, "save failed"):
            namespace["_file_registry_remove_records"](["main", "preview"])

        self.assertEqual(set(state["files"]), {"main", "preview"})
        namespace["_file_registry_save"].assert_called_once_with(raise_on_error=True)

    def test_user_deletes_use_recycle_but_quota_eviction_does_not(self):
        cleanup = KNOWLEDGE_CLEANUP_SOURCE.read_text(encoding="utf-8")
        importer = KNOWLEDGE_IMPORT_SOURCE.read_text(encoding="utf-8")
        self.assertIn("use_recycle: bool = True", cleanup)
        self.assertIn("use_recycle=False", importer)

    def test_frontend_describes_real_restore_boundaries(self):
        knowledge = KNOWLEDGE_UI_SOURCE.read_text(encoding="utf-8")
        admin = ADMIN_UI_SOURCE.read_text(encoding="utf-8")
        zh_i18n = ZH_I18N_SOURCE.read_text(encoding="utf-8")
        self.assertIn("library.files.moved_to_trash", knowledge)
        self.assertIn("'library.files.moved_to_trash':'已移入回收站'", zh_i18n)
        self.assertIn("恢复后会回到资料库，需要重新加入知识库", zh_i18n)
        self.assertIn("r.recycled_at", admin)
        self.assertIn("admin.platform.backup_restored_restart", admin)


if __name__ == "__main__":
    unittest.main()
