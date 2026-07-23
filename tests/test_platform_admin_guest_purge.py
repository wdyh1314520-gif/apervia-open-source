import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "app3_parts" / "storage" / "platform_admin_account_purge_part.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
INVENTORY_SOURCE = (ROOT / "app3_parts" / "storage" / "platform_admin_inventory_part.py").read_text(encoding="utf-8")
REPORTING_SOURCE = (ROOT / "app3_parts" / "storage" / "storage_quota_reporting_part.py").read_text(encoding="utf-8")
ADMIN_JS = (ROOT / "static" / "platform-admin" / "platform-admin.js").read_text(encoding="utf-8")
AUTH_SOURCE = (ROOT / "app3_parts" / "auth" / "platform_auth_user_accounts_part.py").read_text(encoding="utf-8")


def load_service(users=None):
    user_map = {str(key).strip().lower(): dict(value) for key, value in (users or {}).items()}
    audit = []
    namespace = {
        "hashlib": hashlib,
        "threading": threading,
        "_storage_quota_norm_owner": lambda value="": str(value or "").strip().lower(),
        "_auth_get_user": lambda email: user_map.get(str(email or "").strip().lower()),
        "_platform_admin_audit_append": lambda action, target, detail, ok=True: audit.append(
            {"action": action, "target": target, "detail": detail, "ok": ok}
        ),
    }
    exec(compile(SOURCE, str(SOURCE_PATH), "exec"), namespace)
    return namespace["PlatformAdminGuestPurgeService"], audit


class PlatformAdminGuestPurgeTests(unittest.TestCase):
    def test_registered_accounts_are_protected(self):
        service_type, _audit = load_service({"member@example.com": {"email": "member@example.com"}})
        with self.assertRaisesRegex(ValueError, "已注册账号不能由后台主动删除"):
            service_type("member@example.com").validate_target()

    def test_anonymous_and_storage_only_owners_are_guest_targets(self):
        service_type, _audit = load_service()
        self.assertEqual("anonymous", service_type("anonymous").validate_target()["owner"])
        self.assertEqual("legacy-owner", service_type("legacy-owner").validate_target()["owner"])

    def test_purge_requires_exact_owner_confirmation_and_never_deletes_auth_user(self):
        service_type, audit = load_service()

        class IsolatedService(service_type):
            def validate_target(self):
                return {"owner": self.email, "registered": False}

        step_names = (
            "_purge_async_jobs",
            "_purge_account_core",
            "_purge_chat_backups",
            "_purge_shares",
            "_purge_knowledge",
            "_purge_file_storage",
            "_scrub_invites",
            "_scrub_delete_logs",
            "_scrub_admin_audit",
        )
        for name in step_names:
            setattr(IsolatedService, name, lambda self, _name=name: {"step": _name})
        service = IsolatedService("anonymous")
        with self.assertRaisesRegex(ValueError, "完整游客归属标识"):
            service.purge("wrong")
        result = service.purge("anonymous")
        self.assertTrue(result["deleted"])
        self.assertNotIn("auth_user", result["steps"])
        self.assertEqual("guest-owner:" + service.fingerprint, audit[-1]["target"])

    def test_guest_chat_backups_are_removed_without_touching_other_owners(self):
        service_type, _audit = load_service()
        method_globals = service_type._purge_chat_backups.__globals__
        method_globals.update({"os": os, "json": json, "_AUTH_CHAT_LOCK": threading.Lock()})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            own_backup = root / "guest.json"
            other_backup = root / "member.json"
            own_backup.write_text(json.dumps({"email": "guest@example.com", "record": {}}), encoding="utf-8")
            other_backup.write_text(json.dumps({"email": "member@example.com", "record": {}}), encoding="utf-8")
            method_globals["AUTH_CHAT_BACKUP_DIR"] = str(root)
            service = service_type("guest@example.com")
            self.assertEqual([str(own_backup)], service._chat_backup_paths())
            result = service._purge_chat_backups()
            self.assertEqual(1, result["removed"])
            self.assertFalse(own_backup.exists())
            self.assertTrue(other_backup.exists())

    def test_inventory_and_ui_only_offer_purge_for_unregistered_rows(self):
        self.assertIn("'can_purge_guest': bool(not auth)", INVENTORY_SOURCE)
        self.assertIn("a.can_purge_guest", ADMIN_JS)
        self.assertIn("admin.platform.purge_summary", ADMIN_JS)
        self.assertNotIn("('auth_user', self._delete_auth_user)", SOURCE)
        self.assertIn("with purge_lock:", AUTH_SOURCE)
        self.assertIn("_auth_create_user_record_locked(normalized, password, max_accounts)", AUTH_SOURCE)
        self.assertIn("keys: set[str] = set()", REPORTING_SOURCE)
        for residual_state in ("_AUTH_ACCOUNT_PROFILE_STATE", "_AUTH_PERSONALIZATION_MEMORY_STATE", "_CHAT_ASYNC_JOBS"):
            self.assertIn(residual_state, REPORTING_SOURCE)


if __name__ == "__main__":
    unittest.main()
