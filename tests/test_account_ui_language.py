import ast
import json
import re
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PART = ROOT / 'app3_parts/auth/platform_auth_chat_store_part.py'


def _load_profile_language_namespace():
    source = PROFILE_PART.read_text(encoding='utf-8')
    tree = ast.parse(source)
    names = {
        '_auth_ui_language_normalize',
        '_auth_account_profile_normalize',
        '_auth_account_profile_public',
        '_auth_account_profiles_payload_size',
        '_auth_account_profile_get',
        '_auth_account_profile_set',
        '_auth_account_ui_language_set',
    }
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {
        '__builtins__': __builtins__,
        'AUTH_UI_LANGUAGE_DEFAULT': 'en',
        'AUTH_UI_LANGUAGES': frozenset({'en', 'zh-CN'}),
        'AUTH_ACCOUNT_PROFILE_MAX_BYTES': 8 * 1024 * 1024,
        '_AUTH_ACCOUNT_PROFILE_LOCK': threading.Lock(),
        '_AUTH_ACCOUNT_PROFILE_STATE': {'profiles': {}, 'updated_at': 0.0},
        '_auth_account_profile_trim': lambda value, limit: str(value or '').strip()[:limit],
        '_auth_account_profile_avatar_data_url': lambda value: str(value or '').strip(),
        '_normalize_login_email': lambda value: str(value or '').strip().lower(),
        '_mask_login_email': lambda value: str(value or '').strip().lower(),
        '_fmt_ts': lambda value: str(value or ''),
        '_utc_ts': time.time,
        '_auth_account_profiles_save': lambda: None,
        'json': json,
        're': re,
    }
    exec(compile(module, str(PROFILE_PART), 'exec'), namespace)
    return namespace


class AccountUiLanguageTests(unittest.TestCase):
    def setUp(self):
        self.namespace = _load_profile_language_namespace()

    def test_supported_languages_and_aliases_are_normalized(self):
        normalize = self.namespace['_auth_ui_language_normalize']
        self.assertEqual('en', normalize('en-US'))
        self.assertEqual('zh-CN', normalize('zh_Hans'))
        self.assertEqual('en', normalize('unsupported'))
        self.assertEqual('', normalize('unsupported', default=None))

    def test_language_only_profile_is_persisted_and_public(self):
        set_language = self.namespace['_auth_account_ui_language_set']
        public = self.namespace['_auth_account_profile_public']
        profile = set_language('user@example.com', 'zh-CN')
        self.assertEqual('zh-CN', profile['ui_language'])
        self.assertEqual('zh-CN', public('user@example.com', profile)['ui_language'])
        self.assertIn('user@example.com', self.namespace['_AUTH_ACCOUNT_PROFILE_STATE']['profiles'])

    def test_profile_save_preserves_existing_language(self):
        set_language = self.namespace['_auth_account_ui_language_set']
        save_profile = self.namespace['_auth_account_profile_set']
        set_language('user@example.com', 'en')
        profile = save_profile('user@example.com', {'display_name': 'Apervia User'})
        self.assertEqual('en', profile['ui_language'])
        self.assertEqual('Apervia User', profile['display_name'])

    def test_invalid_language_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '界面语言无效'):
            self.namespace['_auth_account_ui_language_set']('user@example.com', 'fr')


if __name__ == '__main__':
    unittest.main()
