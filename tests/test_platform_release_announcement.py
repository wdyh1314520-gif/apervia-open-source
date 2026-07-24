import contextlib
import datetime
import hashlib
import json
import os
import re
import secrets
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.parse
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IDENTITY_PART = ROOT / 'app3_parts/auth/platform_auth_identity_part.py'
RELEASE_PART = ROOT / 'app3_parts/auth/platform_auth_release_announcement_part.py'


class _Request:
    cookies = {}
    headers = {'User-Agent': 'release-announcement-test'}


class PlatformReleaseAnnouncementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.legacy_users = {'users': {}, 'updated_at': 0.0}
        self.profile_languages = {}
        self.namespace = self._namespace()
        exec(compile(IDENTITY_PART.read_text(encoding='utf-8'), str(IDENTITY_PART), 'exec'), self.namespace)
        self.namespace['_auth_identity_init']()
        exec(compile(RELEASE_PART.read_text(encoding='utf-8'), str(RELEASE_PART), 'exec'), self.namespace)
        self.namespace['_platform_release_announcement_init']()
        self.user = self.namespace['_auth_identity_register']('user@example.com', 'StrongA1', 'User')

    def tearDown(self):
        self.tmp.cleanup()

    def _namespace(self):
        data_dir = self.tmp.name

        def normalize(email):
            return str(email or '').strip().lower()

        def validate_password(password, label='密码'):
            if len(str(password or '')) < 6:
                raise ValueError(f'{label}强度不足')

        def legacy_create(email, password):
            self.legacy_users['users'][normalize(email)] = {'email': normalize(email), 'enabled': True}

        return {
            '__builtins__': __builtins__,
            'contextlib': contextlib,
            'datetime': datetime,
            'hashlib': hashlib,
            'json': json,
            'os': os,
            're': re,
            'secrets': secrets,
            'sqlite3': sqlite3,
            'threading': threading,
            'time': time,
            'urllib': urllib,
            'uuid': uuid,
            'request': _Request(),
            'APP_DATA_DIR': data_dir,
            'BASE_DIR': str(ROOT),
            '_app_data_path': lambda *parts: os.path.join(data_dir, *parts),
            'app_getenv': lambda _name, default='': default,
            '_utc_ts': time.time,
            '_fmt_ts': lambda value: str(value or ''),
            '_normalize_login_email': normalize,
            '_mask_login_email': normalize,
            '_auth_validate_password_policy': validate_password,
            '_AUTH_USERS_LOCK': threading.Lock(),
            '_AUTH_USERS_STATE': self.legacy_users,
            '_auth_get_user': lambda email: self.legacy_users['users'].get(normalize(email)),
            '_auth_create_user_record_locked': legacy_create,
            '_auth_users_save': lambda: None,
            '_auth_user_set_enabled': lambda email, enabled: {'email': normalize(email), 'enabled': bool(enabled)},
            '_auth_user_allows_private_search_upstreams': lambda _row: False,
            '_client_ip': lambda: '203.0.113.20',
            '_app_cookie_secure': lambda: True,
            '_auth_account_profile_get': lambda email: {
                'ui_language': self.profile_languages.get(normalize(email), 'zh-CN'),
            },
        }

    def test_release_1_0_1_is_loaded_from_project_files(self):
        service = self.namespace['_platform_release_announcement_service']
        payload = service.current_for_user(self.user['id'], 'en')
        self.assertTrue(payload['enabled'])
        self.assertEqual('v1.0.1', payload['id'])
        self.assertEqual('Apervia 1.0.1', payload['version'])
        self.assertEqual('Apervia 1.0.1 improves clarity and consistency', payload['title'])
        self.assertEqual('en', payload['language'])
        self.assertFalse(payload['acknowledged'])

        chinese = service.current_for_user(self.user['id'], 'zh-CN')
        self.assertEqual('Apervia 1.0.1 体验与一致性更新', chinese['title'])
        self.assertEqual('我知道了', chinese['button_text'])
        self.assertEqual('zh-CN', chinese['language'])
        self.assertEqual(payload['id'], chinese['id'])

    def test_account_profile_language_selects_the_release_copy(self):
        service = self.namespace['_platform_release_announcement_service']
        self.profile_languages['user@example.com'] = 'en'
        self.assertEqual('en', service.current_for_user(self.user['id'])['language'])
        self.profile_languages['user@example.com'] = 'zh-CN'
        self.assertEqual('zh-CN', service.current_for_user(self.user['id'])['language'])

    def test_receipt_is_account_scoped_and_removed_with_account(self):
        service = self.namespace['_platform_release_announcement_service']
        service.acknowledge(self.user['id'], 'v1.0.1')
        self.assertTrue(service.current_for_user(self.user['id'])['acknowledged'])

        second = self.namespace['_auth_identity_register']('second@example.com', 'StrongA1', 'Second')
        self.assertFalse(service.current_for_user(second['id'])['acknowledged'])
        with contextlib.closing(self.namespace['_auth_identity_connect']()) as conn:
            conn.execute('DELETE FROM identity_users WHERE id = ?', (self.user['id'],))
            conn.commit()
            receipt_count = conn.execute('SELECT COUNT(*) FROM identity_release_receipts').fetchone()[0]
        self.assertEqual(0, receipt_count)

    def test_outdated_release_id_cannot_be_acknowledged(self):
        service = self.namespace['_platform_release_announcement_service']
        with self.assertRaisesRegex(ValueError, '已更新'):
            service.acknowledge(self.user['id'], 'v0.9.0')

    def test_version_and_release_metadata_are_consistent(self):
        version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
        release_text = (ROOT / 'release/announcement.md').read_text(encoding='utf-8')
        chinese_release_text = (ROOT / 'release/announcement.zh-CN.md').read_text(encoding='utf-8')
        changelog = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
        self.assertEqual('1.0.1', version)
        self.assertIn(f'id: v{version}', release_text)
        self.assertIn(f'version: {version}', release_text)
        self.assertIn(f'id: v{version}', chinese_release_text)
        self.assertIn(f'version: {version}', chinese_release_text)
        self.assertIn(f'## [{version}]', changelog)

    def test_remote_version_check_uses_only_the_fixed_release_feed(self):
        calls = []

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'tag_name': 'v1.1.0',
                    'html_url': 'https://github.com/wdyh1314520-gif/apervia-open-source/releases/tag/v1.1.0',
                }

        def http_get(url, **kwargs):
            calls.append((url, kwargs))
            return Response()

        service = self.namespace['PlatformReleaseUpdateService']('1.0.0', http_get=http_get)
        payload = service.check()
        self.assertTrue(payload['update_available'])
        self.assertEqual('1.0.0', payload['current_version'])
        self.assertEqual('1.1.0', payload['latest_version'])
        self.assertEqual(service.API_URL, calls[0][0])
        self.assertEqual(6, calls[0][1]['timeout'])
        self.assertEqual('https://github.com/wdyh1314520-gif/apervia-open-source/releases/tag/v1.1.0', payload['release_url'])

    def test_remote_version_check_rejects_invalid_release_versions(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {'tag_name': 'latest', 'html_url': 'https://example.com/release'}

        service = self.namespace['PlatformReleaseUpdateService']('1.0.0', http_get=lambda *_args, **_kwargs: Response())
        with self.assertRaisesRegex(ValueError, 'invalid_release_version'):
            service.check()

    def test_no_editable_announcement_or_browser_receipt_residue(self):
        backend_sources = '\n'.join(
            (ROOT / path).read_text(encoding='utf-8')
            for path in (
                'app3_parts/auth/platform_auth_core_state_part.py',
                'app3_parts/auth/platform_auth_routes_part.py',
                'app3_parts/auth/platform_auth_release_announcement_part.py',
                'app3_parts/storage/platform_admin_routes_part.py',
            )
        )
        frontend = (ROOT / 'static/index3/js/index3-account-cloud-lifecycle.js').read_text(encoding='utf-8')
        admin_sources = '\n'.join(
            path.read_text(encoding='utf-8')
            for path in (ROOT / 'static/platform-admin').glob('*')
            if path.is_file()
        )
        for old_name in (
            'announcement_enabled',
            'announcement_title',
            'announcement_body',
            'announcement_button_text',
            '_auth_announcement_from_state',
            'platform_announcements',
            'platform_announcement_receipts',
        ):
            self.assertNotIn(old_name, backend_sources)
        self.assertNotIn('webai_app_announcement_seen', frontend)
        self.assertNotIn('app_announcement', frontend)
        self.assertNotIn('网站公告', admin_sources)
        self.assertNotIn('/api3/platform-admin/announcement', backend_sources)
        self.assertFalse(hasattr(self.namespace['PlatformReleaseAnnouncementService'], 'save'))


if __name__ == '__main__':
    unittest.main()
