import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "app3_parts" / "chat" / "chat_responses_websocket_transport_part.py"


def _load_functions(names: list[str], namespace: dict):
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"), filename=str(SOURCE_PATH))
    nodes = [
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.ClassDef)) and item.name in names
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace


class ResponsesWebSocketTransportTests(unittest.TestCase):
    def test_converts_responses_https_endpoint_to_websocket(self):
        ns = _load_functions(["_responses_websocket_url"], {})
        self.assertEqual(
            "wss://api.example.com/v1/responses",
            ns["_responses_websocket_url"]("https://api.example.com/v1/responses"),
        )

    def test_response_create_event_keeps_incremental_input(self):
        ns = _load_functions(["_responses_websocket_request_event"], {})
        item = {"type": "function_call_output", "call_id": "call_1", "output": "ok"}
        event = ns["_responses_websocket_request_event"]({
            "model": "gpt-test",
            "stream": True,
            "previous_response_id": "resp_1",
            "input": [item],
        })

        self.assertEqual("response.create", event["type"])
        self.assertEqual("resp_1", event["previous_response_id"])
        self.assertEqual([item], event["input"])
        self.assertFalse(event["store"])
        self.assertNotIn("stream", event)

    def test_handshake_headers_use_websocket_v2_without_sse_headers(self):
        ns = _load_functions(["_responses_websocket_handshake_headers"], {})
        headers = ns["_responses_websocket_handshake_headers"]({
            "Authorization": "Bearer test-token",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "OpenAI-Beta": "responses=experimental",
            "X-Provider-Route": "stable",
        })

        self.assertEqual("Bearer test-token", headers["Authorization"])
        self.assertEqual("stable", headers["X-Provider-Route"])
        self.assertEqual("responses_websockets=2026-02-06", headers["OpenAI-Beta"])
        self.assertNotIn("Accept", headers)
        self.assertNotIn("Content-Type", headers)

    def test_capability_registry_is_scoped_by_endpoint(self):
        ns = _load_functions(["ResponsesTransportCapabilityRegistry"], {})
        registry = ns["ResponsesTransportCapabilityRegistry"](ttl_seconds=300)
        first = "https://relay-a.example/v1/responses"
        second = "https://relay-b.example/v1/responses"

        self.assertIsNone(registry.get(first, "websocket"))
        registry.set(first, "websocket", False)
        registry.set(first, "http_stateful", False)

        self.assertFalse(registry.get(first, "websocket"))
        self.assertFalse(registry.get(first, "http_stateful"))
        self.assertIsNone(registry.get(second, "websocket"))

    def test_marks_only_explicit_websocket_upgrade_rejection_as_unsupported(self):
        ns = _load_functions(["_responses_websocket_error_is_unsupported"], {})
        detect = ns["_responses_websocket_error_is_unsupported"]

        self.assertTrue(detect("Handshake status 200 OK"))
        self.assertFalse(detect("connection reset by peer"))


if __name__ == "__main__":
    unittest.main()
