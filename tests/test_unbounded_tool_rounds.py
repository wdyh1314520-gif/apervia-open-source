import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOOP_CONTROLLER_PATH = ROOT / 'app3_parts' / 'agent' / 'agent_loop_controller_part.py'
STREAMING_PATH = ROOT / 'app3_parts' / 'chat' / 'chat_streaming_part.py'
LEGACY_STREAMING_PATH = ROOT / 'app3_parts' / 'media' / 'legacy_chat_stream_route_part.py'


def load_loop_controller():
    spec = importlib.util.spec_from_file_location('app3_unbounded_agent_loop_test', LOOP_CONTROLLER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class UnboundedToolRoundTests(unittest.TestCase):
    def test_round_iterator_does_not_stop_at_previous_caps(self):
        rounds = load_loop_controller().agent_tool_round_indices()
        observed = [next(rounds) for _ in range(64)]
        self.assertEqual(observed, list(range(1, 65)))

    def test_all_chat_lanes_use_the_unbounded_iterator(self):
        streaming_source = STREAMING_PATH.read_text(encoding='utf-8')
        legacy_source = LEGACY_STREAMING_PATH.read_text(encoding='utf-8')

        self.assertEqual(streaming_source.count('for round_idx in agent_tool_round_indices():'), 2)
        self.assertIn('for _ in agent_tool_round_indices():', legacy_source)
        for source in (streaming_source, legacy_source):
            self.assertNotIn('AGENT_STREAM_TOOLS_MAX_ROUNDS', source)
            self.assertNotIn('工具调用轮数已达上限', source)
            self.assertNotIn('工具调用轮次过多', source)

    def test_legacy_search_tools_have_no_call_count_gate(self):
        source = LEGACY_STREAMING_PATH.read_text(encoding='utf-8')
        self.assertNotIn('MAX_WEB_SEARCH_CALLS', source)
        self.assertNotIn('MAX_FETCH_URL_CALLS', source)
        self.assertNotIn('_limit_reached', source)


if __name__ == '__main__':
    unittest.main()
