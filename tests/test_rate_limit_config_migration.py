import json
import os
import pathlib
import tempfile
import threading
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Logger:
    def exception(self, *_args, **_kwargs):
        pass


class RateLimitConfigMigrationTests(unittest.TestCase):
    def test_startup_rewrites_legacy_manual_blocks_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            namespace = {
                'json': json,
                'os': os,
                'threading': threading,
                'time': time,
                'Response': object,
                'app_logger': _Logger(),
                '_utc_ts': time.time,
                '_app_data_path': lambda name: os.path.join(temp_dir, name),
            }
            source = (ROOT / 'app3_parts/auth/platform_auth_rate_limit_part.py').read_text(encoding='utf-8')
            exec(compile(source, 'platform_auth_rate_limit_part.py', 'exec'), namespace)

            config_path = pathlib.Path(namespace['RATE_LIMIT_CONFIG_FILE'])
            config_path.write_text(json.dumps({
                'global_enabled': True,
                'events_keep': 80,
                'manual_blocks': [{'scope': 'ip', 'value': '127.0.0.1'}],
                'unknown_root': 'remove-me',
                'endpoints': {
                    'chat_stream': {'ip_limit': 9, 'unknown_endpoint_field': 'remove-me'},
                    'removed_endpoint': {'ip_limit': 1},
                },
            }), encoding='utf-8')

            namespace['_rate_limit_load']()

            runtime_config = namespace['_RATE_LIMIT_CONFIG']
            persisted = json.loads(config_path.read_text(encoding='utf-8'))
            for config in (runtime_config, persisted):
                self.assertNotIn('manual_blocks', config)
                self.assertNotIn('unknown_root', config)
                self.assertNotIn('removed_endpoint', config['endpoints'])
                self.assertNotIn('unknown_endpoint_field', config['endpoints']['chat_stream'])
                self.assertEqual(9, config['endpoints']['chat_stream']['ip_limit'])


if __name__ == '__main__':
    unittest.main()
