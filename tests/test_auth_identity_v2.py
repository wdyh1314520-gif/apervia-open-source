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
import uuid
import contextlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IDENTITY_PART = ROOT / 'app3_parts' / 'auth' / 'platform_auth_identity_part.py'


class _Request:
    def __init__(self):
        self.cookies = {}
        self.headers = {'User-Agent': 'identity-test'}


class AuthIdentityV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.request = _Request()
        self.legacy_users = {'users': {}, 'updated_at': 0.0}
        self.namespace = self._namespace()
        source = IDENTITY_PART.read_text(encoding='utf-8')
        exec(compile(source, str(IDENTITY_PART), 'exec'), self.namespace)
        self.namespace['_auth_identity_init']()

    def tearDown(self):
        self.tmp.cleanup()

    def _namespace(self):
        data_dir = self.tmp.name

        def normalize(email):
            return str(email or '').strip().lower()

        def hash_password(password, salt_hex=None):
            salt = bytes.fromhex(str(salt_hex or '').strip()) if salt_hex else os.urandom(16)
            digest = hashlib.pbkdf2_hmac('sha256', str(password or '').encode(), salt, 200000)
            return digest.hex(), salt.hex()

        def validate_password(password, label='密码'):
            raw = str(password or '')
            if len(raw) < 6 or not re.search(r'[A-Z]', raw) or not re.search(r'[a-z]', raw) or not re.search(r'\d', raw):
                raise ValueError(f'{label}强度不足')

        def legacy_get(email):
            return dict(self.legacy_users['users'].get(normalize(email)) or {}) or None

        def legacy_create(email, password):
            password_hash, password_salt = hash_password(password)
            self.legacy_users['users'][normalize(email)] = {
                'email': normalize(email),
                'password_hash': password_hash,
                'password_salt': password_salt,
                'enabled': True,
                'created_at': time.time(),
                'updated_at': time.time(),
            }

        def legacy_enable(email, enabled):
            row = self.legacy_users['users'].get(normalize(email))
            if not row:
                raise ValueError('用户不存在')
            row['enabled'] = bool(enabled)
            return dict(row)

        return {
            '__builtins__': __builtins__,
            'os': os,
            'json': json,
            'time': time,
            're': re,
            'hashlib': hashlib,
            'secrets': secrets,
            'sqlite3': sqlite3,
            'threading': threading,
            'uuid': uuid,
            'contextlib': contextlib,
            'request': self.request,
            'jsonify': lambda payload: payload,
            'APP_DATA_DIR': data_dir,
            '_app_data_path': lambda *parts: os.path.join(data_dir, *parts),
            'app_getenv': lambda name, default='': default,
            '_utc_ts': time.time,
            '_fmt_ts': lambda value: str(value or ''),
            '_normalize_login_email': normalize,
            '_mask_login_email': lambda email: normalize(email),
            '_hash_login_password': hash_password,
            '_auth_validate_password_policy': validate_password,
            '_AUTH_USERS_LOCK': threading.Lock(),
            '_AUTH_USERS_STATE': self.legacy_users,
            '_auth_get_user': legacy_get,
            '_auth_create_user_record_locked': legacy_create,
            '_auth_users_save': lambda: None,
            '_auth_user_set_enabled': legacy_enable,
            'AUTH_ACCOUNT_DISABLED_MESSAGE': '账号已停用，请联系管理员',
            'AUTH_ACCOUNT_DELETED_MESSAGE': '账号已删除，无法继续登录',
            'AUTH_ACCOUNT_DELETE_PENDING_MESSAGE': '账号正在删除期内',
            'AUTH_ACCOUNT_TEMP_BLACKLIST_MESSAGE': '账号已被拉黑',
            '_auth_user_allows_private_search_upstreams': lambda _row: False,
            '_client_ip': lambda: '203.0.113.10',
            '_app_cookie_secure': lambda: True,
        }

    def _set_session(self, token):
        self.request.cookies[self.namespace['AUTH_SESSION_COOKIE']] = token

    def test_first_user_is_active_admin_and_uses_server_session(self):
        user = self.namespace['_auth_identity_register']('Admin@Example.com', 'StrongA1', 'Admin')
        self.assertEqual('admin', user['role'])
        self.assertEqual('active', user['status'])
        token, signed_in = self.namespace['_auth_identity_sign_in']('admin@example.com', 'StrongA1')
        self._set_session(token)
        current = self.namespace['_auth_identity_current_account']()
        self.assertTrue(current['logged_in'])
        self.assertTrue(current['is_admin'])
        self.assertEqual(signed_in['id'], current['user_id'])
        admin_rows = self.namespace['_auth_identity_admin_users']()
        self.assertEqual(1, len(admin_rows))
        self.assertTrue(admin_rows[0]['access_protected'])
        stored = self.namespace['_auth_identity_user_by_id'](user['id'])
        self.assertEqual(600000, int(stored['password_iterations']))

    def test_later_user_waits_for_admin_approval(self):
        self.namespace['_auth_identity_register']('admin@example.com', 'StrongA1', 'Admin')
        pending = self.namespace['_auth_identity_register']('user@example.com', 'StrongB2', 'User')
        self.assertEqual('pending', pending['role'])
        self.assertEqual('pending', pending['status'])
        with self.assertRaises(PermissionError):
            self.namespace['_auth_identity_sign_in']('user@example.com', 'StrongB2')

        token, _ = self.namespace['_auth_identity_sign_in']('admin@example.com', 'StrongA1')
        self._set_session(token)
        updated = self.namespace['_auth_identity_admin_update_user'](pending['id'], role='user', status='active')
        self.assertEqual('user', updated['role'])
        self.assertEqual('active', updated['status'])
        user_token, user = self.namespace['_auth_identity_sign_in']('user@example.com', 'StrongB2')
        self.assertTrue(user_token)
        self.assertEqual('user', user['role'])

    def test_last_active_admin_cannot_be_disabled(self):
        admin = self.namespace['_auth_identity_register']('admin@example.com', 'StrongA1', 'Admin')
        token, _ = self.namespace['_auth_identity_sign_in']('admin@example.com', 'StrongA1')
        self._set_session(token)
        with self.assertRaisesRegex(ValueError, '最后一个管理员'):
            self.namespace['_auth_identity_admin_update_user'](admin['id'], status='disabled')
        with self.assertRaisesRegex(ValueError, '最后一个管理员'):
            self.namespace['_auth_identity_validate_delete']('admin@example.com')

    def test_status_by_email_disables_password_login_and_active_sessions(self):
        self.namespace['_auth_identity_register']('admin@example.com', 'StrongA1', 'Admin')
        pending = self.namespace['_auth_identity_register']('user@example.com', 'StrongB2', 'User')
        admin_token, _ = self.namespace['_auth_identity_sign_in']('admin@example.com', 'StrongA1')
        self._set_session(admin_token)
        self.namespace['_auth_identity_admin_update_user'](pending['id'], role='user', status='active')
        user_token, _ = self.namespace['_auth_identity_sign_in']('user@example.com', 'StrongB2')

        self._set_session(admin_token)
        updated = self.namespace['_auth_identity_admin_set_status_by_email']('user@example.com', 'disabled')
        self.assertEqual('disabled', updated['status'])
        self.assertFalse(self.legacy_users['users']['user@example.com']['enabled'])
        with self.assertRaises(self.namespace['_AuthIdentityAccessError']) as ctx:
            self.namespace['_auth_identity_sign_in']('user@example.com', 'StrongB2')
        self.assertEqual('account_disabled', ctx.exception.code)
        self._set_session(user_token)
        self.assertEqual({}, self.namespace['_auth_identity_current_user']())

    def test_blacklist_blocks_password_login_and_current_session(self):
        self.namespace['_auth_identity_register']('admin@example.com', 'StrongA1', 'Admin')
        pending = self.namespace['_auth_identity_register']('user@example.com', 'StrongB2', 'User')
        admin_token, _ = self.namespace['_auth_identity_sign_in']('admin@example.com', 'StrongA1')
        self._set_session(admin_token)
        self.namespace['_auth_identity_admin_update_user'](pending['id'], role='user', status='active')
        user_token, _ = self.namespace['_auth_identity_sign_in']('user@example.com', 'StrongB2')
        self.legacy_users['users']['user@example.com']['blacklisted'] = True

        with self.assertRaises(self.namespace['_AuthIdentityAccessError']) as ctx:
            self.namespace['_auth_identity_sign_in']('user@example.com', 'StrongB2')
        self.assertEqual('account_blacklisted', ctx.exception.code)
        self._set_session(user_token)
        self.assertEqual({}, self.namespace['_auth_identity_current_user']())

    def test_fresh_database_does_not_import_legacy_accounts(self):
        password_hash, password_salt = self.namespace['_hash_login_password']('LegacyA1')
        self.legacy_users['users']['legacy@example.com'] = {
            'email': 'legacy@example.com',
            'password_hash': password_hash,
            'password_salt': password_salt,
            'enabled': True,
            'created_at': 10.0,
            'updated_at': 20.0,
        }
        self.namespace['_AUTH_IDENTITY_INITIALIZED'] = False
        self.namespace['_auth_identity_init']()
        self.assertEqual(0, self.namespace['_auth_identity_user_count']())
        self.assertIsNone(self.namespace['_auth_identity_user_by_email']('legacy@example.com'))

    def test_identity_source_has_no_automatic_account_creation_path(self):
        source = IDENTITY_PART.read_text(encoding='utf-8')
        self.assertNotIn('_auth_identity_import_legacy_users', source)
        self.assertNotIn('_auth_identity_bootstrap_admin', source)
        self.assertNotIn('AUTH_BOOTSTRAP_ADMIN_', source)


if __name__ == '__main__':
    unittest.main()
