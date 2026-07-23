import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SANDBOX_SCHEMA_SOURCE = ROOT / "app3_parts" / "tools" / "sandbox_tool_schema_part.py"
TOP_LEVEL_SCHEMA_SOURCE = ROOT / "app3_parts" / "tools" / "tool_schema_part.py"
CHAT_SCHEMA_SOURCE = ROOT / "app3_parts" / "chat" / "chat_stream_tool_specs_part.py"
RESPONSES_SCHEMA_SOURCE = ROOT / "app3_parts" / "chat" / "chat_responses_native_tool_specs_part.py"


def _load_sandbox_schema(enabled: bool):
    tree = ast.parse(SANDBOX_SCHEMA_SOURCE.read_text(encoding="utf-8"), filename=str(SANDBOX_SCHEMA_SOURCE))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_sandbox_tool_schemas"
    )
    namespace = {
        "_sandbox_tools_enabled": lambda: enabled,
        "_normalize_tool_schemas_for_endpoint": lambda tools, **_kwargs: tools,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SANDBOX_SCHEMA_SOURCE), "exec"), namespace)
    return namespace["_sandbox_tool_schemas"]


class SandboxToolAvailabilityTests(unittest.TestCase):
    def test_disabled_sandbox_exposes_no_tool_schema(self):
        self.assertEqual(_load_sandbox_schema(False)(compact=False), [])
        self.assertEqual(_load_sandbox_schema(False)(compact=True), [])

    def test_enabled_sandbox_keeps_canonical_tool_schema(self):
        specs = _load_sandbox_schema(True)(compact=False)
        names = {
            str(((spec.get("function") or {}).get("name") or ""))
            for spec in specs
            if isinstance(spec, dict)
        }
        self.assertIn("sandbox_run", names)
        self.assertIn("sandbox_publish_files", names)
        self.assertIn("sandbox_read_file", names)
        self.assertTrue(all(name.startswith("sandbox_") for name in names))

    def test_all_chat_and_responses_schema_paths_use_the_gated_source(self):
        top_level = TOP_LEVEL_SCHEMA_SOURCE.read_text(encoding="utf-8")
        chat = CHAT_SCHEMA_SOURCE.read_text(encoding="utf-8")
        responses = RESPONSES_SCHEMA_SOURCE.read_text(encoding="utf-8")

        self.assertIn("tools.extend(_sandbox_tool_schemas(compact=False))", top_level)
        self.assertIn("globals().get('_sandbox_tool_schemas')", chat)
        self.assertIn("self.chat_tool_specs(compact=compact)", responses)


if __name__ == "__main__":
    unittest.main()
