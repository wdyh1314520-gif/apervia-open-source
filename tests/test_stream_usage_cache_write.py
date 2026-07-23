from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "app3_parts" / "chat" / "chat_stream_usage_part.py"


def _load_namespace() -> dict:
    namespace = {"__builtins__": __builtins__, "json": json}
    exec(compile(SOURCE_PATH.read_text(encoding="utf-8"), str(SOURCE_PATH), "exec"), namespace)
    return namespace


class StreamUsageCacheWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = _load_namespace()

    def test_extracts_responses_cache_reads_and_writes(self):
        extract = self.ns["_extract_usage_from_stream_chunk"]
        usage = extract({
            "usage": {
                "input_tokens": 50396,
                "output_tokens": 1200,
                "total_tokens": 51596,
                "input_tokens_details": {
                    "cached_tokens": 6784,
                    "cache_write_tokens": 32768,
                },
            }
        })
        self.assertEqual(6784, usage["cached_tokens"])
        self.assertEqual(32768, usage["cache_write_tokens"])
        self.assertEqual("input_tokens_details.cache_write_tokens", usage["cache_write_tokens_source"])

    def test_extracts_chat_cache_write_tokens(self):
        extract = self.ns["_extract_usage_from_stream_chunk"]
        usage = extract({
            "usage": {
                "prompt_tokens": 5717,
                "completion_tokens": 100,
                "total_tokens": 5817,
                "prompt_tokens_details": {
                    "cached_tokens": 5248,
                    "cache_write_tokens": 256,
                },
            }
        })
        self.assertEqual(5248, usage["cached_tokens"])
        self.assertEqual(256, usage["cache_write_tokens"])

    def test_tracker_sums_calls_but_replaces_same_call_snapshot(self):
        tracker = self.ns["StreamUsageTracker"](endpoint="responses")
        first = {
            "input_tokens": 1000,
            "output_tokens": 10,
            "total_tokens": 1010,
            "cached_tokens": 100,
            "cache_write_tokens": 800,
        }
        updated = {**first, "output_tokens": 20, "total_tokens": 1020}
        second = {
            "input_tokens": 1200,
            "output_tokens": 30,
            "total_tokens": 1230,
            "cached_tokens": 900,
            "cache_write_tokens": 128,
        }
        tracker.record(first, call_key="call-1")
        tracker.record(updated, call_key="call-1")
        tracker.record(second, call_key="call-2")

        payload = tracker.payload()
        self.assertEqual(2, payload["call_count"])
        self.assertEqual(1000, payload["cached_tokens"])
        self.assertEqual(928, payload["cache_write_tokens"])
        self.assertEqual(800, payload["calls"][0]["cache_write_tokens"])


if __name__ == "__main__":
    unittest.main()
