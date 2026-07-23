import ast
import random
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "app3_parts" / "chat" / "chat_stream_retry_part.py"


def _load_retry_policy():
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"), filename=str(SOURCE_PATH))
    nodes = [
        item for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == "ChatStreamRetryPolicy"
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    fake_httpx = types.SimpleNamespace(
        TimeoutException=TimeoutError,
        RemoteProtocolError=ConnectionError,
        ReadError=ConnectionError,
        ConnectError=ConnectionError,
        NetworkError=ConnectionError,
    )
    namespace = {
        "app_getenv": lambda _name, default="": default,
        "httpx": fake_httpx,
        "random": random,
    }
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace["ChatStreamRetryPolicy"]


class ChatStreamRetryPolicyTests(unittest.TestCase):
    def test_retries_responses_503_but_not_429(self):
        policy = _load_retry_policy()()

        self.assertTrue(policy.is_retryable(RuntimeError("Responses API error 503: channel_abnormal")))
        self.assertFalse(policy.is_retryable(RuntimeError("Responses API error 429: rate limit")))


if __name__ == "__main__":
    unittest.main()
