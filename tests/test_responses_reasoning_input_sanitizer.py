import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "app3_parts" / "chat" / "chat_stream_image_input_part.py"


def _load_context_class():
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"), filename=str(SOURCE_PATH))
    nodes = [
        item for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == "ChatStreamImageInputContext"
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "json": json,
        "app_logger": None,
    }
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace["ChatStreamImageInputContext"]


class ResponsesReasoningInputSanitizerTests(unittest.TestCase):
    def test_keeps_only_public_encrypted_reasoning_fields(self):
        context = _load_context_class()(model="gpt-test")
        clean = context._agent_stream_public_responses_input_item({
            "type": "reasoning",
            "id": "rs_1",
            "status": "completed",
            "encrypted_content": "encrypted-state",
            "summary": [{"type": "summary_text", "text": "plan", "private": True}],
            "content": [{"type": "reasoning_text", "text": "details"}],
            "_trace": "must-not-leak",
        })

        self.assertEqual({
            "type": "reasoning",
            "encrypted_content": "encrypted-state",
            "id": "rs_1",
            "status": "completed",
            "summary": [{"type": "summary_text", "text": "plan"}],
            "content": [{"type": "reasoning_text", "text": "details"}],
        }, clean)

    def test_keeps_public_message_output_fields_for_manual_history(self):
        context = _load_context_class()(model="gpt-test")
        clean = context._agent_stream_public_responses_input_item({
            "type": "message",
            "id": "msg_1",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "answer", "annotations": [{"private": True}]}],
            "_trace": "must-not-leak",
        })

        self.assertEqual({
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "answer"}],
            "id": "msg_1",
            "status": "completed",
        }, clean)

    def test_keeps_required_empty_summary_on_reasoning_input(self):
        context = _load_context_class()(model="gpt-test")

        for source in (
            {"type": "reasoning", "encrypted_content": "state-empty", "summary": []},
            {"type": "reasoning", "encrypted_content": "state-missing"},
        ):
            with self.subTest(source=source):
                clean = context._agent_stream_public_responses_input_item(source)
                self.assertEqual([], clean["summary"])


if __name__ == "__main__":
    unittest.main()
