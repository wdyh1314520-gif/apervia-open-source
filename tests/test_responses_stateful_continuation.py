import ast
import json
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "app3_parts" / "chat" / "chat_responses_native_state_part.py"
STREAMING_SOURCE_PATH = ROOT / "app3_parts" / "chat" / "chat_streaming_part.py"


def _load_functions(names: list[str], namespace: dict):
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"), filename=str(SOURCE_PATH))
    nodes = [
        item
        for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and item.name in names
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace


class ResponsesStatefulContinuationTests(unittest.TestCase):
    def test_trace_store_receives_nested_runtime_context_explicitly(self):
        tree = ast.parse(
            STREAMING_SOURCE_PATH.read_text(encoding="utf-8"),
            filename=str(STREAMING_SOURCE_PATH),
        )
        store_defs = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_responses_native_store_conversation_trace"
        ]
        self.assertEqual(len(store_defs), 1)
        self.assertEqual(
            [arg.arg for arg in store_defs[0].args.kwonlyargs],
            ["endpoint", "context_signature", "user_text"],
        )

        store_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_responses_native_store_conversation_trace"
        ]
        self.assertGreaterEqual(len(store_calls), 1)
        for call in store_calls:
            keyword_names = {keyword.arg for keyword in call.keywords}
            self.assertIn("endpoint", keyword_names)
            self.assertIn("context_signature", keyword_names)
            self.assertIn("user_text", keyword_names)

    def test_detects_rejected_optional_cache_retention_parameter(self):
        ns = _load_functions(
            ["_responses_native_rejects_optional_parameter"],
            {},
        )
        error_text = '{"error":{"message":"Unsupported parameter: prompt_cache_retention"}}'

        self.assertTrue(ns["_responses_native_rejects_optional_parameter"](
            error_text,
            "prompt_cache_retention",
        ))
        self.assertFalse(ns["_responses_native_rejects_optional_parameter"](
            error_text,
            "previous_response_id",
        ))
        self.assertTrue(ns["_responses_native_rejects_optional_parameter"](
            '{"error":{"message":"Invalid value: reasoning.encrypted_content"}}',
            "reasoning.encrypted_content",
        ))

    def test_uses_only_tool_outputs_when_response_id_is_available(self):
        ns = _load_functions(
            ["_responses_native_stateful_continuation_enabled", "_responses_native_round_input_plan"],
            {"app_getenv": lambda _name, default="": default},
        )
        replay = [{"role": "user", "content": "history"}]
        outputs = [{"type": "function_call_output", "call_id": "call_1", "output": "ok"}]

        plan = ns["_responses_native_round_input_plan"](
            replay,
            outputs,
            previous_response_id="resp_1",
            stateful_supported=None,
        )

        self.assertTrue(plan["use_stateful"])
        self.assertEqual("resp_1", plan["previous_response_id"])
        self.assertEqual(outputs, plan["input"])
        self.assertEqual(replay, plan["replay_input"])

    def test_replays_full_input_after_provider_rejection(self):
        ns = _load_functions(
            ["_responses_native_stateful_continuation_enabled", "_responses_native_round_input_plan"],
            {"app_getenv": lambda _name, default="": default},
        )
        replay = [{"role": "user", "content": "history"}]
        outputs = [{"type": "function_call_output", "call_id": "call_1", "output": "ok"}]

        plan = ns["_responses_native_round_input_plan"](
            replay,
            outputs,
            previous_response_id="resp_1",
            stateful_supported=False,
        )

        self.assertFalse(plan["use_stateful"])
        self.assertEqual(replay, plan["input"])
        self.assertEqual("", plan["previous_response_id"])

    def test_generic_validation_error_uses_plain_assistant_history(self):
        ns = _load_functions(
            [
                "_responses_native_is_generic_validation_error",
                "_responses_native_item_text",
                "_responses_native_compatibility_replay_items",
            ],
            {},
        )
        self.assertTrue(ns["_responses_native_is_generic_validation_error"](
            '{"error":{"message":"当前请求参数校验异常","type":"upstream_error"}}'
        ))
        replay = ns["_responses_native_compatibility_replay_items"]([
            {"role": "user", "content": [{"type": "input_text", "text": "first"}]},
            {"type": "reasoning", "encrypted_content": "state-1", "summary": []},
            {"type": "message", "id": "msg-1", "status": "completed", "role": "assistant", "content": [{"type": "output_text", "text": "answer"}]},
            {"role": "user", "content": [{"type": "input_text", "text": "second"}]},
        ])
        self.assertEqual([
            {"role": "user", "content": [{"type": "input_text", "text": "first"}]},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": [{"type": "input_text", "text": "second"}]},
        ], replay)

    def test_streaming_has_generic_history_compatibility_retry(self):
        source = STREAMING_SOURCE_PATH.read_text(encoding="utf-8")
        self.assertIn("[RESPONSES_HISTORY_COMPATIBILITY_RETRY]", source)
        self.assertIn("set(endpoint, 'history_output_replay', False)", source)

    def test_preserves_and_deduplicates_encrypted_reasoning_for_stateless_replay(self):
        ns = _load_functions(
            ["ResponsesNativeStateContext"],
            {
                "json": json,
                "uuid": uuid,
                "app_logger": None,
            },
        )
        context = ns["ResponsesNativeStateContext"]()
        collected = {}
        first = {
            "type": "reasoning",
            "id": "rs_1",
            "status": "completed",
            "encrypted_content": "encrypted-state",
            "summary": [{"type": "summary_text", "text": "plan"}],
            "_internal": "must-not-leak",
        }
        context.merge_reasoning_item(collected, first)
        context.merge_reasoning_item(collected, dict(first))

        self.assertEqual([{
            "type": "reasoning",
            "encrypted_content": "encrypted-state",
            "id": "rs_1",
            "status": "completed",
            "summary": [{"type": "summary_text", "text": "plan"}],
        }], context.reasoning_input_items(collected))

    def test_drops_reasoning_without_encrypted_state(self):
        ns = _load_functions(
            ["ResponsesNativeStateContext"],
            {
                "json": json,
                "uuid": uuid,
                "app_logger": None,
            },
        )
        context = ns["ResponsesNativeStateContext"]()
        self.assertIsNone(context.reasoning_input_item({
            "type": "reasoning",
            "id": "rs_missing",
            "summary": [{"type": "summary_text", "text": "not replayable"}],
        }))

    def test_preserves_required_empty_summary_for_reasoning_replay(self):
        ns = _load_functions(
            ["ResponsesNativeStateContext"],
            {
                "json": json,
                "uuid": uuid,
                "app_logger": None,
            },
        )
        context = ns["ResponsesNativeStateContext"]()

        for source in (
            {"type": "reasoning", "encrypted_content": "state-empty", "summary": []},
            {"type": "reasoning", "encrypted_content": "state-missing"},
        ):
            with self.subTest(source=source):
                normalized = context.reasoning_input_item(source)
                self.assertEqual([], normalized["summary"])

    def test_conversation_trace_restores_only_the_new_turn_tail(self):
        ns = _load_functions(
            ["ResponsesConversationTraceRegistry"],
            {"json": json},
        )
        registry = ns["ResponsesConversationTraceRegistry"](ttl_seconds=300)
        stored = [
            {"role": "user", "content": "first"},
            {"type": "reasoning", "encrypted_content": "state-1"},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "answer-1"}]},
        ]
        self.assertTrue(registry.store(
            session_id="session-1",
            endpoint="https://relay.example/v1/responses",
            model="gpt-test",
            context_signature="ctx-1",
            replay_items=stored,
            last_user_text="first",
            assistant_text="answer-1",
        ))
        current = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": [{"type": "output_text", "text": "answer-1"}]},
            {"role": "user", "content": "second"},
            {"role": "user", "content": [{"type": "input_text", "text": "Runtime context:\nnow"}]},
        ]

        restored = registry.restore(
            session_id="session-1",
            endpoint="https://relay.example/v1/responses",
            model="gpt-test",
            context_signature="ctx-1",
            current_items=current,
        )

        self.assertEqual([stored[0], stored[2]] + current[2:], restored)

    def test_conversation_trace_replaces_runtime_and_drops_cross_http_ephemeral_items(self):
        ns = _load_functions(["ResponsesConversationTraceRegistry"], {"json": json})
        registry = ns["ResponsesConversationTraceRegistry"](ttl_seconds=300)
        endpoint = "https://relay.example/v1/responses"
        model = "gpt-test"
        session_id = "session-runtime"
        stored = [
            {"role": "user", "content": "first"},
            {"type": "reasoning", "encrypted_content": "state-1", "summary": []},
            {"type": "web_search_call", "id": "search-1", "status": "completed"},
            {"type": "function_call", "call_id": "call-1", "name": "web_search", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "call-1", "output": "result"},
            {"role": "user", "content": [{"type": "input_text", "text": "Runtime context:\nold time"}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "answer-1"}]},
        ]
        self.assertTrue(registry.store(
            session_id=session_id,
            endpoint=endpoint,
            model=model,
            context_signature="ctx-1",
            replay_items=stored,
            last_user_text="first",
            assistant_text="answer-1",
        ))
        current = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "answer-1"},
            {"role": "user", "content": "second"},
            {"role": "user", "content": [{"type": "input_text", "text": "Runtime context:\nnew time"}]},
            {"role": "user", "content": [{"type": "input_text", "text": "Runtime context:\nnew location"}]},
        ]
        restored = registry.restore(
            session_id=session_id,
            endpoint=endpoint,
            model=model,
            context_signature="ctx-1",
            current_items=current,
        )

        runtime_texts = [registry._item_text(item) for item in restored if registry._is_runtime_item(item)]
        self.assertEqual(["Runtime context:\nnew time", "Runtime context:\nnew location"], runtime_texts)
        self.assertFalse(any(item.get("type") == "reasoning" for item in restored))
        self.assertFalse(any(item.get("type") == "web_search_call" for item in restored))
        self.assertTrue(any(item.get("type") == "function_call" for item in restored))
        self.assertTrue(any(item.get("type") == "function_call_output" for item in restored))

    def test_tool_trace_is_inserted_before_current_runtime_tail(self):
        ns = _load_functions(["ResponsesConversationTraceRegistry"], {"json": json})
        registry = ns["ResponsesConversationTraceRegistry"](ttl_seconds=300)
        initial = [
            {"role": "user", "content": "question"},
            {"role": "user", "content": [{"type": "input_text", "text": "Runtime context:\ncurrent time"}]},
            {"role": "user", "content": [{"type": "input_text", "text": "Runtime context:\ncurrent location"}]},
        ]
        rows = registry.append_before_runtime(initial, [
            {"type": "reasoning", "encrypted_content": "state-1", "summary": []},
            {"type": "web_search_call", "id": "search-1", "status": "completed"},
            {"type": "function_call", "call_id": "call-1", "name": "web_search", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "call-1", "output": "result-1"},
        ])
        runtime_indices = [idx for idx, item in enumerate(rows) if registry._is_runtime_item(item)]
        trace_indices = [
            idx for idx, item in enumerate(rows)
            if str(item.get("type") or "") in {"reasoning", "web_search_call", "function_call", "function_call_output"}
        ]
        self.assertEqual(2, len(runtime_indices))
        self.assertTrue(trace_indices)
        self.assertLess(max(trace_indices), min(runtime_indices))

    def test_streaming_normalizes_runtime_tail_after_tool_append_and_compression(self):
        source = STREAMING_SOURCE_PATH.read_text(encoding="utf-8")
        append_idx = source.index("conversation_input_items = _RESPONSES_CONVERSATION_TRACES.append_before_runtime(")
        compress_idx = source.index(
            "conversation_input_items = input_compressor(conversation_input_items, phase='responses_native_round')",
            append_idx,
        )
        normalize_idx = source.index(
            "conversation_input_items = _RESPONSES_CONVERSATION_TRACES.with_runtime_tail(conversation_input_items)",
            compress_idx,
        )
        self.assertLess(append_idx, compress_idx)
        self.assertLess(compress_idx, normalize_idx)

    def test_conversation_trace_rejects_changed_context_or_history(self):
        ns = _load_functions(
            ["ResponsesConversationTraceRegistry"],
            {"json": json},
        )
        registry = ns["ResponsesConversationTraceRegistry"](ttl_seconds=300)
        registry.store(
            session_id="session-1",
            endpoint="https://relay.example/v1/responses",
            model="gpt-test",
            context_signature="ctx-1",
            replay_items=[{"role": "user", "content": "first"}],
            last_user_text="first",
            assistant_text="answer-1",
        )
        current = [
            {"role": "user", "content": "edited"},
            {"role": "assistant", "content": "answer-1"},
            {"role": "user", "content": "second"},
        ]

        self.assertIsNone(registry.restore(
            session_id="session-1",
            endpoint="https://relay.example/v1/responses",
            model="gpt-test",
            context_signature="ctx-1",
            current_items=current,
        ))
        self.assertIsNone(registry.restore(
            session_id="session-1",
            endpoint="https://relay.example/v1/responses",
            model="gpt-test",
            context_signature="ctx-changed",
            current_items=[
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "answer-1"},
                {"role": "user", "content": "second"},
            ],
        ))


if __name__ == "__main__":
    unittest.main()
