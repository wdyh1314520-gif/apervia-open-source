from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "app3_parts" / "chat" / "chat_prompt_cache_part.py"


def _load_selected(names: set[str]) -> dict:
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"), filename=str(SOURCE_PATH))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names
    ]
    namespace = {"__builtins__": __builtins__, "re": re, "urlparse": urlparse}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE_PATH), "exec"), namespace)
    return namespace


class PromptCacheModernProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_selected({
            "_prompt_cache_uses_modern_protocol",
            "_prompt_cache_default_options",
            "_prompt_cache_base_host",
            "_prompt_cache_should_use_modern_protocol",
            "_prompt_cache_preserve_legacy_retention",
            "_prompt_cache_mark_message_breakpoint",
            "_prompt_cache_apply_explicit_breakpoint",
            "_prompt_cache_without_modern_protocol",
            "_prompt_cache_rejects_modern_protocol",
            "PromptCachePlan",
        })

    def test_gpt_56_and_later_use_modern_protocol(self):
        uses_modern = self.ns["_prompt_cache_uses_modern_protocol"]
        for model in ("gpt-5.6", "openai/gpt-5.6-2026-07-01", "gpt-5.7", "gpt-6"):
            self.assertTrue(uses_modern(model), model)
        for model in ("gpt-5.5", "gpt-5", "gpt-4.1", "o3", "custom-gpt-5.6ish"):
            self.assertFalse(uses_modern(model), model)

    def test_modern_protocol_follows_model_family(self):
        should_use_modern = self.ns["_prompt_cache_should_use_modern_protocol"]

        self.assertTrue(should_use_modern("gpt-5.6", "https://api.openai.com/v1"))
        self.assertTrue(should_use_modern("gpt-5.6-luna", "https://apihost.cn/v1"))
        self.assertTrue(should_use_modern(
            "gpt-5.6-luna",
            "https://apihost.cn/v1",
            {"mode": "implicit", "ttl": "30m"},
        ))
        self.assertFalse(should_use_modern("gpt-5.5", "https://api.openai.com/v1"))

    def test_third_party_modern_models_preserve_legacy_retention_hint(self):
        preserve_legacy = self.ns["_prompt_cache_preserve_legacy_retention"]

        self.assertFalse(preserve_legacy("gpt-5.6", "https://api.openai.com/v1"))
        self.assertTrue(preserve_legacy("gpt-5.6-luna", "https://apihost.cn/v1"))
        self.assertFalse(preserve_legacy("gpt-5.5", "https://apihost.cn/v1"))

    def test_modern_protocol_rejection_requires_named_unsupported_field(self):
        rejects = self.ns["_prompt_cache_rejects_modern_protocol"]
        self.assertTrue(rejects("Unknown parameter: prompt_cache_options"))
        self.assertTrue(rejects("prompt_cache_breakpoint is not supported"))
        self.assertFalse(rejects("upstream returned 503"))
        self.assertFalse(rejects("unknown parameter: temperature"))

    def test_responses_breakpoint_marks_stable_context_not_latest_user(self):
        apply_breakpoint = self.ns["_prompt_cache_apply_explicit_breakpoint"]
        body = {
            "input": [
                {"role": "developer", "content": [{"type": "input_text", "text": "stable file context"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "current question"}]},
            ]
        }
        out, count = apply_breakpoint(body, endpoint_mode="responses")
        self.assertEqual(1, count)
        self.assertEqual(
            {"mode": "explicit"},
            out["input"][0]["content"][0]["prompt_cache_breakpoint"],
        )
        self.assertNotIn("prompt_cache_breakpoint", out["input"][1]["content"][0])
        self.assertNotIn("prompt_cache_breakpoint", body["input"][0]["content"][0])

    def test_single_dynamic_responses_message_keeps_implicit_only(self):
        apply_breakpoint = self.ns["_prompt_cache_apply_explicit_breakpoint"]
        body = {"input": [{"role": "user", "content": [{"type": "input_text", "text": "current"}]}]}
        out, count = apply_breakpoint(body, endpoint_mode="responses")
        self.assertEqual(0, count)
        self.assertEqual(body, out)

    def test_responses_replay_breakpoint_matches_previous_request_boundary(self):
        apply_breakpoint = self.ns["_prompt_cache_apply_explicit_breakpoint"]
        body = {
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": "previous question"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "Runtime context:\nprevious"}]},
                {"type": "reasoning", "encrypted_content": "state", "summary": []},
                {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "previous answer"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "current question"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "Runtime context:\ncurrent"}]},
            ]
        }

        out, count = apply_breakpoint(body, endpoint_mode="responses")

        self.assertEqual(1, count)
        self.assertEqual(
            {"mode": "explicit"},
            out["input"][1]["content"][0]["prompt_cache_breakpoint"],
        )
        self.assertNotIn("prompt_cache_breakpoint", out["input"][4]["content"][0])
        self.assertNotIn("prompt_cache_breakpoint", out["input"][5]["content"][0])

    def test_chat_breakpoint_converts_last_leading_instruction_to_content_block(self):
        apply_breakpoint = self.ns["_prompt_cache_apply_explicit_breakpoint"]
        body = {
            "messages": [
                {"role": "system", "content": "stable policy"},
                {"role": "user", "content": "current question"},
            ]
        }
        out, count = apply_breakpoint(body, endpoint_mode="chat_completions")
        self.assertEqual(1, count)
        self.assertEqual("text", out["messages"][0]["content"][0]["type"])
        self.assertEqual({"mode": "explicit"}, out["messages"][0]["content"][0]["prompt_cache_breakpoint"])

    def test_modern_plan_replaces_legacy_retention_and_can_be_stripped(self):
        plan_class = self.ns["PromptCachePlan"]
        plan = plan_class.__new__(plan_class)
        plan.body = {
            "messages": [
                {"role": "system", "content": "stable policy"},
                {"role": "user", "content": "question"},
            ],
            "extra_body": {"prompt_cache_retention": "24h"},
        }
        plan.enabled = True
        plan.placement = "extra_body"
        plan.key = "stable-key"
        plan.modern_protocol = True
        plan.options = {"mode": "implicit", "ttl": "30m"}
        plan.model = "gpt-5.6"
        plan.endpoint = "chat_completions"
        plan.breakpoint_count = 0

        out = plan.apply_to(plan.body)
        self.assertNotIn("prompt_cache_retention", out["extra_body"])
        self.assertEqual({"mode": "implicit", "ttl": "30m"}, out["extra_body"]["prompt_cache_options"])
        self.assertEqual(1, plan.breakpoint_count)

        stripped = self.ns["_prompt_cache_without_modern_protocol"](out, placement="extra_body")
        self.assertNotIn("prompt_cache_options", stripped["extra_body"])
        self.assertNotIn("prompt_cache_breakpoint", stripped["messages"][0]["content"][0])

    def test_legacy_plan_removes_modern_only_fields(self):
        plan_class = self.ns["PromptCachePlan"]
        plan = plan_class.__new__(plan_class)
        plan.body = {
            "messages": [{
                "role": "system",
                "content": [{
                    "type": "text",
                    "text": "stable policy",
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }],
            }],
            "extra_body": {"prompt_cache_options": {"mode": "implicit", "ttl": "30m"}},
        }
        plan.enabled = True
        plan.placement = "extra_body"
        plan.key = "stable-key"
        plan.modern_protocol = False
        plan.options = {}
        plan.retention = "24h"
        plan.model = "gpt-5.5"
        plan.endpoint = "chat_completions"
        plan.breakpoint_count = 0

        out = plan.apply_to(plan.body)
        self.assertEqual("24h", out["extra_body"]["prompt_cache_retention"])
        self.assertNotIn("prompt_cache_options", out["extra_body"])
        self.assertNotIn("prompt_cache_breakpoint", out["messages"][0]["content"][0])

    def test_third_party_modern_plan_keeps_both_protocols_until_capability_retry(self):
        plan_class = self.ns["PromptCachePlan"]
        plan = plan_class.__new__(plan_class)
        plan.body = {
            "input": [
                {"role": "developer", "content": [{"type": "input_text", "text": "stable"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "current"}]},
            ],
        }
        plan.enabled = True
        plan.placement = "body"
        plan.key = "stable-key"
        plan.modern_protocol = True
        plan.compat_legacy_retention = True
        plan.options = {"mode": "implicit", "ttl": "30m"}
        plan.retention = "24h"
        plan.model = "gpt-5.6-luna"
        plan.endpoint = "responses"
        plan.breakpoint_count = 0

        out = plan.apply_to(plan.body)

        self.assertEqual("24h", out["prompt_cache_retention"])
        self.assertEqual({"mode": "implicit", "ttl": "30m"}, out["prompt_cache_options"])
        self.assertEqual(
            {"mode": "explicit"},
            out["input"][0]["content"][0]["prompt_cache_breakpoint"],
        )

        stripped = self.ns["_prompt_cache_without_modern_protocol"](out, placement="body")
        self.assertEqual("24h", stripped["prompt_cache_retention"])
        self.assertNotIn("prompt_cache_options", stripped)
        self.assertNotIn("prompt_cache_breakpoint", stripped["input"][0]["content"][0])


if __name__ == "__main__":
    unittest.main()
