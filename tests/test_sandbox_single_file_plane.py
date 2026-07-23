import ast
import base64
import hashlib
import os
import tempfile
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STREAMING_SOURCE = ROOT / "app3_parts" / "chat" / "chat_streaming_part.py"
SANDBOX_WRITE_SOURCE = ROOT / "app3_parts" / "tools" / "sandbox_file_write_import_part.py"
CHAT_FINAL_SOURCE = ROOT / "app3_parts" / "chat" / "chat_final_answer_part.py"
LEGACY_STREAM_SOURCE = ROOT / "app3_parts" / "media" / "legacy_chat_stream_route_part.py"
LEGACY_EDIT_SOURCE = ROOT / "app3_parts" / "tools" / "file_registry_edit_apply_part.py"


def _load_functions(path: Path, names: set[str], namespace: dict) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    selected = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    missing = names - {node.name for node in selected}
    if missing:
        raise AssertionError(f"missing functions: {sorted(missing)}")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class SandboxSingleFilePlaneTests(unittest.TestCase):
    def test_responses_native_code_interpreter_is_disabled_by_single_file_plane(self):
        source = STREAMING_SOURCE.read_text(encoding="utf-8")
        start = source.index("def _responses_native_code_interpreter_enabled()")
        end = source.index("def _responses_native_code_interpreter_tool_spec()", start)
        helper = source[start:end]
        self.assertIn("if _agent_stream_single_sandbox_file_plane_enabled():", helper)
        self.assertIn("return False", helper)
        self.assertLess(
            helper.index("if _agent_stream_single_sandbox_file_plane_enabled():"),
            helper.index("mode = _responses_native_code_interpreter_mode()"),
        )

    def test_legacy_artifact_callers_use_sandbox_bridge(self):
        chat_source = CHAT_FINAL_SOURCE.read_text(encoding="utf-8")
        legacy_source = LEGACY_STREAM_SOURCE.read_text(encoding="utf-8")
        edit_source = LEGACY_EDIT_SOURCE.read_text(encoding="utf-8")
        self.assertIn("_sandbox_stage_and_publish_artifacts", chat_source)
        self.assertIn("source='chat_nonstream_artifact_json'", chat_source)
        self.assertNotIn("_save_artifacts_to_uploads(parsed_artifacts)", chat_source)
        self.assertIn("_sandbox_stage_and_publish_artifacts", legacy_source)
        self.assertIn("source='legacy_chat_stream_artifact_json'", legacy_source)
        self.assertNotIn("_save_artifacts_to_uploads(artifacts)", legacy_source)
        self.assertIn("source='legacy_zip_edit'", edit_source)
        self.assertIn("source='legacy_zip_member_edit'", edit_source)
        self.assertNotIn("_save_artifacts_to_uploads([", edit_source)

    def test_legacy_text_artifact_materializes_in_sandbox_before_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = Path(tmp).resolve()
            publish_observations = []

            def resolve_path(raw_path, _messages):
                relative = str(raw_path or "").replace("\\", "/").strip("/")
                target = (sandbox_root / relative).resolve()
                if sandbox_root not in target.parents and target != sandbox_root:
                    raise ValueError("path_outside_sandbox")
                return str(target), relative

            def snapshot(path):
                target = Path(path)
                raw = target.read_bytes() if target.is_file() else b""
                return {
                    "exists": target.is_file(),
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest() if raw else "",
                }

            def publish(args, messages=None):
                paths = list(args.get("paths") or [])
                publish_observations.extend(paths)
                for relative in paths:
                    target = sandbox_root / relative
                    self.assertTrue(target.is_file())
                    self.assertEqual(target.read_text(encoding="utf-8"), "sandbox first")
                return {
                    "ok": True,
                    "files": [{"filename": paths[0], "sandbox_published": True}],
                }

            namespace = {
                "os": os,
                "uuid": uuid,
                "ALLOWED_EXT": {".txt", ".zip"},
                "_SANDBOX_BINARY_ARTIFACT_EXTS": {".zip"},
                "app_getenv": lambda _name, default="": default,
                "_sandbox_tools_enabled": lambda: True,
                "_safe_artifact_relative_path": lambda value: str(value or "").replace("\\", "/").strip("/"),
                "_normalize_artifact_text_encoding": lambda *_args: "utf-8",
                "_artifact_try_decode_base64_bytes": lambda value: base64.b64decode(value) if value else None,
                "_artifact_text_has_meaningful_content": lambda value: bool(str(value or "").strip()),
                "_artifact_encode_text_payload": lambda value, encoding: (str(value).encode(encoding), encoding),
                "_artifact_zip_has_meaningful_entries": lambda _raw: True,
                "_sandbox_resolve_path": resolve_path,
                "_sandbox_quota_ok": lambda *args, **kwargs: (True, {}),
                "_sandbox_storage_quota_ok": lambda *args, **kwargs: (True, {}),
                "_sandbox_file_binary_snapshot": snapshot,
                "_sandbox_build_binary_audit": lambda rel, *_args, **_kwargs: {"output_filename": rel},
                "_sandbox_result_base": lambda _messages: {"sandbox_id": "test-session"},
                "_sandbox_publish_files_tool": publish,
            }
            _load_functions(
                SANDBOX_WRITE_SOURCE,
                {"_sandbox_artifact_payload_bytes", "_sandbox_unique_output_path", "_sandbox_stage_and_publish_artifacts"},
                namespace,
            )
            result = namespace["_sandbox_stage_and_publish_artifacts"](
                [{"filename": "report.txt", "data": "sandbox first", "encoding": "utf-8"}],
                [{"role": "user", "content": "生成文件"}],
                source="test_legacy_bridge",
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["staged_paths"], ["report.txt"])
            self.assertEqual(publish_observations, ["report.txt"])
            self.assertTrue(result["files"][0]["sandbox_published"])

    def test_legacy_artifact_keeps_distinct_sandbox_source_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_root = Path(tmp).resolve()
            (sandbox_root / "report.txt").write_text("old", encoding="utf-8")
            published = []

            def resolve_path(raw_path, _messages):
                relative = str(raw_path or "").replace("\\", "/").strip("/")
                return str((sandbox_root / relative).resolve()), relative

            def snapshot(path):
                target = Path(path)
                raw = target.read_bytes() if target.is_file() else b""
                return {"exists": target.is_file(), "size": len(raw), "sha256": ""}

            def publish(args, messages=None):
                published.extend(args.get("paths") or [])
                return {"ok": True, "files": [{"filename": name} for name in (args.get("paths") or [])]}

            namespace = {
                "os": os,
                "uuid": uuid,
                "ALLOWED_EXT": {".txt"},
                "_SANDBOX_BINARY_ARTIFACT_EXTS": set(),
                "app_getenv": lambda _name, default="": default,
                "_sandbox_tools_enabled": lambda: True,
                "_safe_artifact_relative_path": lambda value: str(value or "").replace("\\", "/").strip("/"),
                "_normalize_artifact_text_encoding": lambda *_args: "utf-8",
                "_artifact_try_decode_base64_bytes": lambda value: base64.b64decode(value) if value else None,
                "_artifact_text_has_meaningful_content": lambda value: bool(str(value or "").strip()),
                "_artifact_encode_text_payload": lambda value, encoding: (str(value).encode(encoding), encoding),
                "_artifact_zip_has_meaningful_entries": lambda _raw: True,
                "_sandbox_resolve_path": resolve_path,
                "_sandbox_quota_ok": lambda *args, **kwargs: (True, {}),
                "_sandbox_storage_quota_ok": lambda *args, **kwargs: (True, {}),
                "_sandbox_file_binary_snapshot": snapshot,
                "_sandbox_build_binary_audit": lambda rel, *_args, **_kwargs: {"output_filename": rel},
                "_sandbox_result_base": lambda _messages: {"sandbox_id": "test-session"},
                "_sandbox_publish_files_tool": publish,
            }
            _load_functions(
                SANDBOX_WRITE_SOURCE,
                {"_sandbox_artifact_payload_bytes", "_sandbox_unique_output_path", "_sandbox_stage_and_publish_artifacts"},
                namespace,
            )
            result = namespace["_sandbox_stage_and_publish_artifacts"]([
                {"filename": "report.txt", "data": "new one"},
                {"filename": "report.txt", "data": "new two"},
            ], [])

            self.assertTrue(result["ok"])
            self.assertEqual(published, ["report-v2.txt", "report-v3.txt"])
            self.assertEqual((sandbox_root / "report.txt").read_text(encoding="utf-8"), "old")
            self.assertEqual((sandbox_root / "report-v2.txt").read_text(encoding="utf-8"), "new one")
            self.assertEqual((sandbox_root / "report-v3.txt").read_text(encoding="utf-8"), "new two")

    def test_binary_legacy_artifact_requires_real_binary_payload(self):
        namespace = {
            "os": os,
            "ALLOWED_EXT": {".pdf"},
            "_SANDBOX_BINARY_ARTIFACT_EXTS": {".pdf"},
            "_safe_artifact_relative_path": lambda value: str(value or ""),
            "_normalize_artifact_text_encoding": lambda *_args: "utf-8",
            "_artifact_try_decode_base64_bytes": lambda value: base64.b64decode(value) if value else None,
            "_artifact_text_has_meaningful_content": lambda value: bool(str(value or "").strip()),
            "_artifact_encode_text_payload": lambda value, encoding: (str(value).encode(encoding), encoding),
            "_artifact_zip_has_meaningful_entries": lambda _raw: True,
        }
        _load_functions(SANDBOX_WRITE_SOURCE, {"_sandbox_artifact_payload_bytes"}, namespace)
        raw, meta = namespace["_sandbox_artifact_payload_bytes"]({
            "filename": "report.pdf",
            "data": "not a real pdf",
            "encoding": "utf-8",
        })
        self.assertIsNone(raw)
        self.assertEqual(meta["error"], "binary_artifact_requires_base64")


if __name__ == "__main__":
    unittest.main()
