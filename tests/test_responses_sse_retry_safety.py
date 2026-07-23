import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = ROOT / 'app3_parts' / 'chat' / 'chat_responses_sse_stream_part.py'
STREAMING_PATH = ROOT / 'app3_parts' / 'chat' / 'chat_streaming_part.py'


def load_parser_module():
    spec = importlib.util.spec_from_file_location('chat_responses_sse_stream_part_test', PARSER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ResponsesSSERetrySafetyTests(unittest.TestCase):
    def setUp(self):
        self.module = load_parser_module()

    def test_valid_json_event_is_parsed(self):
        buffer = self.module.ResponsesSSEEventBuffer()
        buffer.set_event('response.output_text.delta')
        buffer.add_data('{"type":"response.output_text.delta","delta":"ok"}')

        event_name, payload = buffer.pop_json()

        self.assertEqual(event_name, 'response.output_text.delta')
        self.assertEqual(payload['delta'], 'ok')

    def test_retry_reset_discards_incomplete_previous_connection(self):
        buffer = self.module.ResponsesSSEEventBuffer()
        buffer.set_event('response.web_search_call.searching')
        buffer.add_data('{"type":"response.web_search_call.searching"')

        buffer.reset()
        buffer.set_event('response.output_text.delta')
        buffer.add_data('{"type":"response.output_text.delta","delta":"clean"}')
        event_name, payload = buffer.pop_json()

        self.assertEqual(event_name, 'response.output_text.delta')
        self.assertEqual(payload['delta'], 'clean')

    def test_malformed_protocol_data_is_dropped_not_returned_as_text(self):
        buffer = self.module.ResponsesSSEEventBuffer()
        buffer.set_event('response.output_text.delta')
        buffer.add_data('{"type":"response.output_text.delta"')

        event_name, payload = buffer.pop_json()

        self.assertEqual(event_name, 'response.output_text.delta')
        self.assertIsNone(payload)

    def test_responses_retry_loop_resets_its_event_buffer(self):
        source = STREAMING_PATH.read_text(encoding='utf-8')
        self.assertGreaterEqual(source.count("round_sse_buffer.reset()"), 2)
        self.assertIn("round_sse_buffer.reset()\n                    if responses_websocket_transport is not None:", source)
        self.assertNotIn("sse('delta', {'text': raw_data})", source)


if __name__ == '__main__':
    unittest.main()
