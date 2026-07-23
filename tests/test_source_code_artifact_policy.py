import importlib.util
import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASK_ROUTER_PATH = ROOT / "app3_parts" / "agent" / "task_intent_router_part.py"
LOOP_CONTROLLER_PATH = ROOT / "app3_parts" / "agent" / "agent_loop_controller_part.py"
SANDBOX_WRITE_PATH = ROOT / "app3_parts" / "tools" / "sandbox_file_write_import_part.py"
TOOL_COMPRESSION_PATH = ROOT / "app3_parts" / "tools" / "tool_result_compression_part.py"
SANDBOX_RUN_PATH = ROOT / "app3_parts" / "tools" / "sandbox_run_publish_part.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_functions(path: Path, names: set[str], namespace: dict):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    selected = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class SourceCodeArtifactPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = load_module(TASK_ROUTER_PATH, "app3_task_intent_router_test")
        cls.loop = load_module(LOOP_CONTROLLER_PATH, "app3_agent_loop_controller_test")

    def test_explicit_python_file_requires_sandbox_execution(self):
        intent = self.router.task_intent_route("生成一个 Python 文件")
        self.assertEqual(intent["kind"], "artifact_create")
        self.assertIn(".py", intent["target_formats"])
        self.assertTrue(intent["needs_execution"])

        plan = self.loop.agent_loop_plan(task_intent=intent)
        self.assertIn("sandbox_run", plan["allowed_tools"])
        self.assertNotIn("sandbox_run", plan["blocked_first_tools"])
        self.assertIn("execution_result", plan["required_state"])
        self.assertEqual(plan["reason"], "source_code_artifact_execute_then_publish")

    def test_followup_delivery_infers_recent_code_fence(self):
        messages = [
            {"role": "assistant", "content": "```c\nint main(void) { return 0; }\n```"},
            {"role": "user", "content": "发文件给我"},
        ]
        intent = self.router.task_intent_route("发文件给我", messages=messages)
        self.assertEqual(intent["kind"], "artifact_create")
        self.assertIn(".c", intent["target_formats"])
        self.assertTrue(intent["needs_execution"])

    def test_office_artifact_keeps_sandbox_run_blocked_first(self):
        intent = self.router.task_intent_route("生成一个 Word 文档")
        plan = self.loop.agent_loop_plan(task_intent=intent)
        self.assertIn(".docx", intent["target_formats"])
        self.assertFalse(intent["needs_execution"])
        self.assertIn("sandbox_run", plan["blocked_first_tools"])

    def test_direct_write_redirects_only_new_source_code(self):
        namespace = {
            "os": os,
            "_SANDBOX_SOURCE_CODE_DELIVERY_EXTS": {
                ".py", ".js", ".ts", ".c", ".cpp"
            },
        }
        load_functions(
            SANDBOX_WRITE_PATH,
            {"_sandbox_source_code_write_redirect"},
            namespace,
        )
        redirect = namespace["_sandbox_source_code_write_redirect"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            new_python = redirect(str(root / "demo.py"), "demo.py")
            self.assertEqual(new_python["replacement_tool"], "sandbox_run")
            self.assertEqual(new_python["error"], "source_code_delivery_requires_sandbox_run")
            self.assertEqual(redirect(str(root / "notes.txt"), "notes.txt"), {})

            existing_python = root / "existing.py"
            existing_python.write_text("print('ok')\n", encoding="utf-8")
            self.assertEqual(redirect(str(existing_python), "existing.py"), {})
            self.assertEqual(redirect(str(root / "append.py"), "append.py", append=True), {})

    def test_write_result_compression_preserves_retry_instruction(self):
        source = TOOL_COMPRESSION_PATH.read_text(encoding="utf-8")
        single = source.split("if name == 'sandbox_write_file':", 1)[1].split(
            "if name == 'sandbox_write_files':", 1
        )[0]
        batch = source.split("if name == 'sandbox_write_files':", 1)[1].split(
            "if name == 'sandbox_import_files':", 1
        )[0]
        for section in (single, batch):
            self.assertIn("out['replacement_tool']", section)
            self.assertIn("out['instruction']", section)

    def test_sandbox_run_is_not_skipped_by_execution_policy(self):
        source = SANDBOX_RUN_PATH.read_text(encoding="utf-8")
        run_tool = source.split("def _sandbox_run_tool", 1)[1].split(
            "def _sandbox_publish_files_tool", 1
        )[0]
        self.assertNotIn("_sandbox_execution_decision_for_args", run_tool)
        self.assertNotIn("_sandbox_policy_skip_result", run_tool)
        self.assertNotIn("'skipped_by_policy': True", run_tool)


if __name__ == "__main__":
    unittest.main()
