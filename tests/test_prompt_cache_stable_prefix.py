from __future__ import annotations

import ast
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESPONSES_SOURCE_PATH = ROOT / "app3_parts" / "chat" / "chat_responses_input_conversion_part.py"
PROMPT_CACHE_SOURCE_PATH = ROOT / "app3_parts" / "chat" / "chat_prompt_cache_part.py"
STREAMING_SOURCE_PATH = ROOT / "app3_parts" / "chat" / "chat_streaming_part.py"
RESPONSES_TOOL_SPECS_SOURCE_PATH = ROOT / "app3_parts" / "chat" / "chat_responses_native_tool_specs_part.py"


def _exec_selected(path: Path, *, names: set[str], assignments: set[str], namespace: dict | None = None) -> dict:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
            nodes.append(node)
            continue
        if isinstance(node, ast.Assign):
            targets = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if targets & assignments:
                nodes.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in assignments:
            nodes.append(node)
    out = {"__builtins__": __builtins__}
    out.update(namespace or {})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), out)
    return out


def _responses_namespace() -> dict:
    return _exec_selected(
        RESPONSES_SOURCE_PATH,
        names={
            "_responses_input_content_from_chat_content",
            "_responses_instruction_text_from_content",
            "_responses_stable_context_input_enabled",
            "_responses_text_has_stable_file_context_marker",
            "_responses_untyped_context_looks_dynamic",
            "_responses_is_dynamic_context_message",
            "_responses_is_stable_input_context_message",
            "_responses_instructions_from_chat_messages",
            "_responses_input_from_chat_messages",
        },
        assignments={
            "_RESPONSES_STABLE_INSTRUCTION_PREFIX",
            "_PROMPT_CACHE_RUNTIME_TAIL_CONTEXT_KINDS",
            "_RESPONSES_DYNAMIC_CONTEXT_KINDS",
            "_RESPONSES_STABLE_INPUT_CONTEXT_KINDS",
        },
        namespace={
            "_orch_dedupe_model_messages": lambda rows: list(rows or []),
            "_prompt_cache_message_evidence_text": lambda _message: "",
            "_prompt_cache_runtime_wants_cache": lambda: True,
        },
    )


class PromptCacheStablePrefixTests(unittest.TestCase):
    def test_responses_turn_content_and_tool_action_do_not_change_auto_cache_key_material(self):
        ns = _exec_selected(
            PROMPT_CACHE_SOURCE_PATH,
            names={"_prompt_cache_stable_json", "_prompt_cache_digest", "_prompt_cache_key_material_hash"},
            assignments=set(),
            namespace={"json": json, "hashlib": hashlib},
        )
        digest = ns["_prompt_cache_key_material_hash"]
        stable_tools = [
                {"type": "function", "name": "web_search", "parameters": {"type": "object"}},
                {"type": "function", "name": "fetch_url", "parameters": {"type": "object"}},
            ]
        ordinary = {
            "instructions": "Stable platform policy.",
            "tools": stable_tools,
            "tool_choice": "auto",
            "input": [{"role": "user", "content": "hello"}],
        }
        online = {
            "instructions": "Stable platform policy.",
            "tools": stable_tools,
            "tool_choice": {"type": "function", "name": "web_search"},
            "input": [{"role": "user", "content": "latest news"}],
        }
        self.assertEqual(
            digest(ordinary, endpoint_mode="responses"),
            digest(online, endpoint_mode="responses"),
        )
        self.assertNotEqual(
            digest(online, endpoint_mode="responses"),
            digest(online, endpoint_mode="chat_completions"),
        )
        self.assertIn("'pc6'", PROMPT_CACHE_SOURCE_PATH.read_text(encoding="utf-8"))

    def test_responses_stable_prefix_family_changes_when_platform_schema_changes(self):
        ns = _exec_selected(
            PROMPT_CACHE_SOURCE_PATH,
            names={"_prompt_cache_stable_json", "_prompt_cache_digest", "_prompt_cache_key_material_hash"},
            assignments=set(),
            namespace={"json": json, "hashlib": hashlib},
        )
        digest = ns["_prompt_cache_key_material_hash"]
        base = {
            "instructions": "Stable platform policy.",
            "tools": [{"type": "function", "name": "web_search", "parameters": {"type": "object"}}],
            "reasoning": {"effort": "high"},
        }
        changed_tool_schema = {
            **base,
            "tools": [{"type": "function", "name": "web_search", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}],
        }
        changed_policy = {**base, "instructions": "Updated stable platform policy."}
        changed_reasoning = {**base, "reasoning": {"effort": "medium"}}

        self.assertNotEqual(digest(base, endpoint_mode="responses"), digest(changed_tool_schema, endpoint_mode="responses"))
        self.assertNotEqual(digest(base, endpoint_mode="responses"), digest(changed_policy, endpoint_mode="responses"))
        self.assertNotEqual(digest(base, endpoint_mode="responses"), digest(changed_reasoning, endpoint_mode="responses"))

    def test_web_and_other_runtime_context_stay_out_of_responses_instructions(self):
        ns = _responses_namespace()
        build_instructions = ns["_responses_instructions_from_chat_messages"]
        build_input = ns["_responses_input_from_chat_messages"]
        base = [
            {"role": "system", "_kind": "platform_policy", "content": "固定平台规则"},
            {"role": "user", "content": "你好"},
        ]
        expected = build_instructions(base)
        for kind in (
            "web",
            "weather_ctx",
            "agent_stream_image_index",
            "agent_stream_image_payload_notice",
            "agent_stream_file_loop_hint",
            "image_generation_failure_context",
        ):
            messages = [base[0], {"role": "system", "_kind": kind, "content": f"动态内容 {kind}"}, base[1]]
            self.assertEqual(expected, build_instructions(messages), kind)
            response_input = build_input(messages)
            self.assertTrue(response_input[-1]["content"][0]["text"].startswith("Runtime context:\n"), kind)

    def test_chat_web_context_moves_to_tail_without_changing_stable_head(self):
        ns = _responses_namespace()
        prompt_ns = _exec_selected(
            PROMPT_CACHE_SOURCE_PATH,
            names={"_prompt_cache_is_chat_tail_context_message", "_prompt_cache_chat_messages_for_request"},
            assignments={"_PROMPT_CACHE_CHAT_TAIL_CONTEXT_KINDS", "_PROMPT_CACHE_CHAT_REQUIRED_TAIL_CONTEXT_KINDS"},
            namespace={
                **ns,
                "_prompt_cache_chat_dynamic_context_mode": lambda: "tail",
            },
        )
        reorder = prompt_ns["_prompt_cache_chat_messages_for_request"]
        rows = reorder([
            {"role": "system", "_kind": "platform_policy", "content": "固定平台规则"},
            {"role": "system", "_kind": "web", "content": "本轮联网结果"},
            {"role": "user", "content": "查询最新信息"},
        ])
        self.assertEqual("固定平台规则", rows[0]["content"])
        self.assertEqual("查询最新信息", rows[1]["content"])
        self.assertEqual("Runtime context:\n本轮联网结果", rows[2]["content"])

    def test_mcp_specs_are_stabilized_after_append_in_both_lanes(self):
        source = STREAMING_SOURCE_PATH.read_text(encoding="utf-8")
        chat_start = source.index("mcp_chat_specs =")
        chat_stable = source.index("tool_specs = _agent_stream_stabilize_tool_specs(tool_specs)", chat_start)
        chat_use = source.index("if compact_tool_schema:", chat_start)
        self.assertLess(chat_start, chat_stable)
        self.assertLess(chat_stable, chat_use)

        responses_start = source.index("mcp_response_specs =")
        responses_return = source.index("return _agent_stream_stabilize_tool_specs(specs)", responses_start)
        self.assertLess(responses_start, responses_return)

    def test_responses_web_search_keeps_identical_tool_prefix_across_gate_changes(self):
        ns = _exec_selected(
            RESPONSES_TOOL_SPECS_SOURCE_PATH,
            names={"ResponsesNativeToolSpecsContext"},
            assignments=set(),
            namespace={
                "skill_tool_group": lambda name, _spec=None: {
                    "save_memory": "memory",
                    "search_knowledge_base": "knowledge",
                }.get(name, "other"),
            },
        )
        context = ns["ResponsesNativeToolSpecsContext"](
            web_search_enabled=lambda: True,
            web_search_tool_spec=lambda: {"type": "web_search"},
            web_enabled_for_turn=lambda: True,
            prompt_cache_wants_stable_tools=lambda: True,
            filter_tool_specs_for_settings=lambda specs: list(specs or []),
            chat_tool_specs=lambda compact=False: [
                {
                    "type": "function",
                    "function": {
                        "name": "save_memory",
                        "description": "Save memory.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "search_knowledge_base",
                        "description": "Search knowledge.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
            ],
            stabilize_tool_specs=lambda specs: sorted(
                [dict(item) for item in (specs or [])],
                key=lambda item: (str(item.get("type") or ""), str(item.get("name") or "")),
            ),
        )

        ordinary_turn_tools = context.tool_specs(allowed_tool_groups=["memory"])
        web_turn_tools = context.tool_specs(allowed_tool_groups=["web"])
        tool_output_round_tools = context.tool_specs(allowed_tool_groups=["knowledge"])

        self.assertEqual(ordinary_turn_tools, web_turn_tools)
        self.assertEqual(web_turn_tools, tool_output_round_tools)
        self.assertTrue(any(item.get("type") == "web_search" for item in web_turn_tools))


if __name__ == "__main__":
    unittest.main()
