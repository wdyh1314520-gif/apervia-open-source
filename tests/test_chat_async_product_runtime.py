from __future__ import annotations

import ast
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JOBS_PATH = ROOT / "app3_parts" / "media" / "chat_async_jobs_part.py"
ROUTES_PATH = ROOT / "app3_parts" / "media" / "chat_async_routes_part.py"
STREAM_RUNTIME_PATH = ROOT / "static" / "index3" / "js" / "index3-stream-runtime-ui.js"
ASYNC_UI_PATH = ROOT / "static" / "index3" / "js" / "index3-async-chat-stream-ui.js"
CLOUD_SYNC_PATH = ROOT / "static" / "index3" / "js" / "index3-store-cloud-sync.js"


def build_coordinator():
    source = JOBS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(JOBS_PATH))
    class_node = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ChatAsyncRunCoordinator"
    )
    module = ast.Module(body=[class_node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "__builtins__": __builtins__,
        "threading": threading,
        "time": time,
        "_normalize_login_email": lambda value: str(value or "").strip().lower(),
        "_CHAT_ASYNC_COMPLETED_DISCOVERY_TTL_S": 6 * 3600,
        "_CHAT_ASYNC_JOB_RUNTIME": {},
    }
    exec(compile(module, str(JOBS_PATH), "exec"), namespace)
    jobs = {}
    counter = {"value": 0}

    def new_record(payload, owner=None, coordination=None):
        counter["value"] += 1
        coord = dict(coordination or {})
        now_ts = time.time()
        return {
            "job_id": f"job-{counter['value']}",
            "created_at": now_ts,
            "updated_at": now_ts,
            "done": False,
            "status": "queued",
            "status_text": "",
            "seq": 0,
            "owner_email": str((owner or {}).get("email") or "").strip().lower(),
            "owner_device_id": str((owner or {}).get("device_id") or "").strip(),
            **coord,
        }

    namespace["_chat_async_new_job_record"] = new_record
    namespace["_chat_async_create_job"] = lambda payload, owner=None: new_record(payload, owner, {})
    coordinator = namespace["ChatAsyncRunCoordinator"](jobs, threading.RLock())
    return coordinator, jobs


def build_persistence_namespace(db_path: str):
    source = JOBS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(JOBS_PATH))
    names = {
        "_chat_async_sqlite_module",
        "_chat_async_db_connect",
        "_chat_async_db_ensure",
        "_chat_async_json_dumps",
        "_chat_async_db_upsert_rows",
    }
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "__builtins__": __builtins__,
        "CHAT_ASYNC_DB_FILE": db_path,
        "_CHAT_ASYNC_PERSIST_LOCK": threading.Lock(),
        "_normalize_upload_scope": lambda value: str(value or "").strip().lower(),
        "json": json,
    }
    exec(compile(module, str(JOBS_PATH), "exec"), namespace)
    return namespace


class ChatAsyncProductRuntimeTests(unittest.TestCase):
    def test_same_account_and_turn_reuses_one_authoritative_job(self):
        coordinator, jobs = build_coordinator()
        payload = {
            "client_session_id": "conversation-1",
            "client_turn_id": "conversation-1:turn-1",
            "api_endpoint_mode": "responses",
        }
        first, first_action = coordinator.start_or_reuse(
            payload,
            owner={"email": "User@Example.com", "device_id": "device-a"},
        )
        second, second_action = coordinator.start_or_reuse(
            payload,
            owner={"email": "user@example.com", "device_id": "device-b"},
        )

        self.assertEqual(first_action, "created")
        self.assertEqual(second_action, "reused")
        self.assertIs(first, second)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(first["owner_key"], "email:user@example.com")
        self.assertEqual(first["conversation_mode"], "response")

    def test_same_conversation_rejects_a_second_active_turn_across_protocols(self):
        coordinator, _jobs = build_coordinator()
        owner = {"email": "user@example.com", "device_id": "device-a"}
        first, _ = coordinator.start_or_reuse(
            {
                "client_session_id": "conversation-1",
                "client_turn_id": "turn-response",
                "api_endpoint_mode": "responses",
            },
            owner=owner,
        )
        blocked, action = coordinator.start_or_reuse(
            {
                "client_session_id": "conversation-1",
                "client_turn_id": "turn-chat",
                "api_endpoint_mode": "chat_completions",
            },
            owner=owner,
        )

        self.assertEqual(action, "conversation_busy")
        self.assertIs(blocked, first)

    def test_terminal_turn_allows_next_turn_and_remains_discoverable(self):
        coordinator, jobs = build_coordinator()
        owner = {"email": "user@example.com", "device_id": "device-a"}
        first, _ = coordinator.start_or_reuse(
            {"client_session_id": "conversation-1", "client_turn_id": "turn-1"},
            owner=owner,
        )
        first["done"] = True
        first["status"] = "done"
        first["updated_at"] = time.time()

        recovered = coordinator.find(owner, "conversation-1", turn_id="turn-1")
        second, action = coordinator.start_or_reuse(
            {"client_session_id": "conversation-1", "client_turn_id": "turn-2"},
            owner=owner,
        )

        self.assertIs(recovered, first)
        self.assertEqual(action, "created")
        self.assertIsNot(second, first)
        self.assertEqual(len(jobs), 2)

    def test_different_accounts_and_temporary_chats_do_not_share_runs(self):
        coordinator, jobs = build_coordinator()
        payload = {"client_session_id": "same-local-id", "client_turn_id": "turn-1"}
        first, _ = coordinator.start_or_reuse(payload, owner={"email": "one@example.com"})
        second, action = coordinator.start_or_reuse(payload, owner={"email": "two@example.com"})
        temp_a, _ = coordinator.start_or_reuse(
            {**payload, "temporary_chat": True}, owner={"email": "one@example.com"}
        )
        temp_b, _ = coordinator.start_or_reuse(
            {**payload, "temporary_chat": True}, owner={"email": "one@example.com"}
        )

        self.assertEqual(action, "created")
        self.assertIsNot(first, second)
        self.assertIsNot(temp_a, temp_b)
        self.assertEqual(len(jobs), 2)

    def test_server_persists_coordination_keys_and_exposes_active_lookup(self):
        jobs_source = JOBS_PATH.read_text(encoding="utf-8")
        routes_source = ROUTES_PATH.read_text(encoding="utf-8")

        for column in ("owner_key", "conversation_id", "turn_id", "conversation_mode", "active_key"):
            self.assertIn(f"ADD COLUMN {column}", jobs_source)
        self.assertIn("uq_chat_async_turn", jobs_source)
        self.assertIn("force=bool(event == 'done' or rec.get('done'))", jobs_source)
        self.assertIn('@app.get("/api3/chat_async/active")', routes_source)
        self.assertIn("conversation_run_active", routes_source)
        self.assertIn("_CHAT_ASYNC_RUN_COORDINATOR.start_or_reuse", routes_source)
        self.assertIn("'found': False", routes_source)
        self.assertNotIn("'code': 'conversation_run_not_found'", routes_source)

    def test_sqlite_migration_and_turn_uniqueness_are_executable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "jobs.db")
            ns = build_persistence_namespace(db_path)
            ns["_chat_async_db_ensure"]()
            conn = sqlite3.connect(db_path)
            try:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(chat_async_jobs)")}
            finally:
                conn.close()
            self.assertTrue(
                {"owner_key", "conversation_id", "turn_id", "conversation_mode", "active_key"}.issubset(columns)
            )

            base = {
                "job_id": "job-1",
                "created_at": time.time(),
                "updated_at": time.time(),
                "done": False,
                "status": "running",
                "owner": {"email": "user@example.com"},
                "owner_key": "email:user@example.com",
                "conversation_id": "conversation-1",
                "turn_id": "turn-1",
                "conversation_mode": "chat",
                "active_key": "email:user@example.com|conversation-1",
            }
            ns["_chat_async_db_upsert_rows"]([base])
            with self.assertRaises(sqlite3.IntegrityError):
                ns["_chat_async_db_upsert_rows"]([{**base, "job_id": "job-2"}])

            ns["_chat_async_db_upsert_rows"]([{**base, "done": True, "status": "done"}])
            conn = sqlite3.connect(db_path)
            try:
                active_key = conn.execute(
                    "SELECT active_key FROM chat_async_jobs WHERE job_id = ?", ("job-1",)
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(active_key, "")

    def test_frontend_uses_stable_turn_and_device_local_cursor(self):
        stream_source = STREAM_RUNTIME_PATH.read_text(encoding="utf-8")
        async_source = ASYNC_UI_PATH.read_text(encoding="utf-8")
        cloud_source = CLOUD_SYNC_PATH.read_text(encoding="utf-8")

        self.assertIn("function stableAsyncChatTurnIdForSession", stream_source)
        self.assertIn("client_turn_id:", async_source)
        self.assertIn("/api3/chat_async/active?", async_source)
        self.assertIn("if(data?.found === false) return null", async_source)
        self.assertIn("cursor: 0", async_source)
        self.assertIn("rollbackOutgoingTurnForConversationConflict", async_source)
        self.assertIn("conversation_run_conflict_rollback", async_source)
        self.assertIn("function setAsyncSessionStatus", async_source)
        recovery_source = async_source.split("const _sessionRunDiscoveryPromises", 1)[1]
        self.assertNotIn("setStatusForSession(", recovery_source)
        self.assertIn("setAsyncSessionStatus(sid", recovery_source)
        self.assertIn("function cloudSyncHydrateRunRecoveryRuntimeFields", cloud_source)
        self.assertIn("cursor: ''", cloud_source)
        self.assertIn("s.pendingJobCursor = previousJobId === jobId", cloud_source)
        self.assertIn("runRecoveryClearedAt", stream_source)
        self.assertIn("clearedAt >= runUpdatedAt", cloud_source)


if __name__ == "__main__":
    unittest.main()
