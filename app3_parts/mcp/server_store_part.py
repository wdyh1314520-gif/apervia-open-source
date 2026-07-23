# Purpose: server-side MCP directory and encrypted credential persistence.
# Loaded by client_runtime_part.py after normalization helpers are available.

import contextlib as _mcp_contextlib

from cryptography.fernet import Fernet as _McpFernet, InvalidToken as _McpInvalidToken


class McpServerStore:
    """统一保存用户 MCP 服务器；公开配置与加密凭据始终分离。"""

    def __init__(self, db_path: str, key_path: str):
        self.db_path = os.path.abspath(str(db_path or ''))
        self.key_path = os.path.abspath(str(key_path or ''))
        self._lock = threading.RLock()
        self._fernet = None

    @staticmethod
    def normalize_owner(owner: str = '') -> str:
        normalizer = globals().get('_normalize_login_email')
        if callable(normalizer):
            try:
                return str(normalizer(owner) or '').strip().lower()
            except Exception:
                pass
        return str(owner or '').strip().lower()

    def _connect(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout=15000')
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS mcp_servers (
                owner TEXT NOT NULL,
                server_id TEXT NOT NULL,
                config_json TEXT NOT NULL,
                secret_blob TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (owner, server_id)
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_mcp_servers_updated ON mcp_servers(updated_at DESC)')
        return conn

    @_mcp_contextlib.contextmanager
    def connection(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _key_bytes(self) -> bytes:
        configured = str(os.getenv('APP3_MCP_TOKEN_KEY', '') or '').strip()
        if configured:
            return configured.encode('ascii')
        os.makedirs(os.path.dirname(self.key_path), exist_ok=True)
        try:
            with open(self.key_path, 'rb') as handle:
                key = handle.read().strip()
        except FileNotFoundError:
            key = _McpFernet.generate_key()
            try:
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                with open(self.key_path, 'rb') as handle:
                    key = handle.read().strip()
            else:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(key + b'\n')
                    handle.flush()
                    os.fsync(handle.fileno())
        if os.name != 'nt':
            try:
                os.chmod(self.key_path, 0o600)
            except OSError:
                pass
        return key

    def _cipher(self):
        with self._lock:
            if self._fernet is None:
                try:
                    self._fernet = _McpFernet(self._key_bytes())
                except Exception as exc:
                    raise RuntimeError('APP3_MCP_TOKEN_KEY 不是有效的 Fernet 密钥') from exc
            return self._fernet

    def _encrypt_secret(self, secret: dict | None = None) -> str:
        clean = {
            str(key): str(value or '')
            for key, value in dict(secret or {}).items()
            if str(key or '').strip() and str(value or '')
        }
        if not clean:
            return ''
        raw = json.dumps(clean, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return self._cipher().encrypt(raw).decode('ascii')

    def _decrypt_secret(self, blob: str = '') -> dict:
        token = str(blob or '').strip()
        if not token:
            return {}
        try:
            raw = self._cipher().decrypt(token.encode('ascii'))
            value = json.loads(raw.decode('utf-8'))
            return dict(value or {}) if isinstance(value, dict) else {}
        except _McpInvalidToken as exc:
            raise RuntimeError('MCP 凭据无法解密，请检查 APP3_MCP_TOKEN_KEY 是否与保存时一致') from exc
        except Exception as exc:
            raise RuntimeError('MCP 凭据存储损坏') from exc

    @staticmethod
    def _config_from_row(row) -> dict:
        try:
            value = json.loads(str(row['config_json'] or '{}'))
        except Exception:
            value = {}
        return dict(value or {}) if isinstance(value, dict) else {}

    def list(self, owner: str, *, include_secret: bool = False) -> list[dict]:
        normalized_owner = self.normalize_owner(owner)
        if not normalized_owner:
            return []
        with self.connection() as conn:
            rows = conn.execute(
                'SELECT owner, server_id, config_json, secret_blob, created_at, updated_at '
                'FROM mcp_servers WHERE owner=? ORDER BY created_at ASC, server_id ASC',
                (normalized_owner,),
            ).fetchall()
        out = []
        for row in rows:
            server = _mcp_client_normalize_server(self._config_from_row(row), include_secret=False)
            secret = self._decrypt_secret(str(row['secret_blob'] or '')) if include_secret else {}
            if include_secret:
                server['bearer_token'] = str(secret.get('access_token') or secret.get('bearer_token') or '')
                server['refresh_token'] = str(secret.get('refresh_token') or '')
                server['oauth_client_secret'] = str(secret.get('oauth_client_secret') or '')
            server['_credential_configured'] = bool(str(row['secret_blob'] or '').strip())
            server['_created_at'] = float(row['created_at'] or 0.0)
            server['_updated_at'] = float(row['updated_at'] or 0.0)
            out.append(server)
        return out

    def get(self, owner: str, server_id: str, *, include_secret: bool = False) -> dict:
        target = _mcp_client_clean_id(server_id, '')
        if not target:
            return {}
        return next((row for row in self.list(owner, include_secret=include_secret) if row.get('id') == target), {})

    def count(self, owner: str) -> int:
        normalized_owner = self.normalize_owner(owner)
        if not normalized_owner:
            return 0
        with self.connection() as conn:
            row = conn.execute('SELECT COUNT(1) FROM mcp_servers WHERE owner=?', (normalized_owner,)).fetchone()
        return int(row[0] if row is not None else 0)

    def upsert(
        self,
        owner: str,
        raw_server: dict,
        *,
        secret_update: dict | None = None,
        preserve_secret: bool = True,
    ) -> dict:
        normalized_owner = self.normalize_owner(owner)
        if not normalized_owner:
            raise ValueError('MCP 服务器缺少账号归属')
        server = _mcp_client_normalize_server(raw_server, include_secret=False)
        server_id = str(server.get('id') or '').strip()
        if not server_id or not str(server.get('url') or '').strip():
            raise ValueError('请填写 MCP Server URL。')
        now = time.time()
        config_json = json.dumps(server, ensure_ascii=False, separators=(',', ':'))
        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    'SELECT secret_blob, created_at FROM mcp_servers WHERE owner=? AND server_id=?',
                    (normalized_owner, server_id),
                ).fetchone()
                if existing is None:
                    count_row = conn.execute('SELECT COUNT(1) FROM mcp_servers WHERE owner=?', (normalized_owner,)).fetchone()
                    if int(count_row[0] if count_row is not None else 0) >= _MCP_CLIENT_MAX_SERVERS:
                        raise ValueError(f'每个账号最多保存 {_MCP_CLIENT_MAX_SERVERS} 个 MCP 服务器')
                if secret_update is not None:
                    secret_blob = self._encrypt_secret(secret_update)
                elif preserve_secret and existing is not None:
                    secret_blob = str(existing['secret_blob'] or '')
                else:
                    secret_blob = ''
                created_at = float(existing['created_at'] or now) if existing is not None else now
                conn.execute(
                    '''INSERT INTO mcp_servers(owner, server_id, config_json, secret_blob, created_at, updated_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(owner, server_id) DO UPDATE SET
                         config_json=excluded.config_json,
                         secret_blob=excluded.secret_blob,
                         updated_at=excluded.updated_at''',
                    (normalized_owner, server_id, config_json, secret_blob, created_at, now),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get(normalized_owner, server_id, include_secret=False)

    def delete(self, owner: str, server_id: str) -> bool:
        normalized_owner = self.normalize_owner(owner)
        target = _mcp_client_clean_id(server_id, '')
        if not normalized_owner or not target:
            return False
        with self.connection() as conn:
            cursor = conn.execute('DELETE FROM mcp_servers WHERE owner=? AND server_id=?', (normalized_owner, target))
            conn.commit()
            return int(cursor.rowcount or 0) > 0

    def delete_owner(self, owner: str) -> int:
        normalized_owner = self.normalize_owner(owner)
        if not normalized_owner:
            return 0
        with self.connection() as conn:
            cursor = conn.execute('DELETE FROM mcp_servers WHERE owner=?', (normalized_owner,))
            conn.commit()
            return max(0, int(cursor.rowcount or 0))

    def admin_rows(self, query: str = ''):
        needle = str(query or '').strip().lower()
        with self.connection() as conn:
            rows = conn.execute(
                'SELECT owner, server_id, config_json, secret_blob, created_at, updated_at '
                'FROM mcp_servers ORDER BY updated_at DESC, owner ASC, server_id ASC'
            ).fetchall()
        out = []
        for row in rows:
            server = _mcp_client_normalize_server(self._config_from_row(row), include_secret=False)
            public = _mcp_client_public_server(server, credential_configured=bool(str(row['secret_blob'] or '').strip()))
            item = {
                'owner': str(row['owner'] or ''),
                **public,
                'created_at': float(row['created_at'] or 0.0),
                'updated_at': float(row['updated_at'] or 0.0),
            }
            haystack = ' '.join((item['owner'], str(item.get('id') or ''), str(item.get('name') or ''), str(item.get('url') or ''))).lower()
            if needle and needle not in haystack:
                continue
            out.append(item)
        return out


_MCP_SERVER_STORE = McpServerStore(
    _app_data_path('mcp_server_store.db'),
    _app_data_path('mcp_token.key'),
)


def _mcp_client_public_server(server: dict | None = None, *, credential_configured: bool | None = None) -> dict:
    stored_credential = bool((server or {}).get('_credential_configured')) if isinstance(server, dict) else False
    row = _mcp_client_normalize_server(server, include_secret=False)
    configured = stored_credential if credential_configured is None else bool(credential_configured)
    auth_type = str(row.get('auth_type') or 'oauth')
    expires_at = max(0, int(row.get('token_expires_at') or 0))
    credential_valid = auth_type == 'none' or (configured and (not expires_at or expires_at > int(time.time()) + 30))
    row['credential_configured'] = configured
    row['connected'] = bool(row.get('enabled')) and credential_valid
    row['scanned_at'] = max(0, int((server or {}).get('scanned_at') or 0)) if isinstance(server, dict) else 0
    row['tool_count'] = len(row.get('tools') or [])
    row['enabled_tool_count'] = len([tool for tool in (row.get('tools') or []) if tool.get('enabled')])
    return row


def _mcp_client_servers_for_owner(owner: str, *, include_secret: bool = True) -> list[dict]:
    return _MCP_SERVER_STORE.list(owner, include_secret=include_secret)


def _mcp_client_server_for_owner(owner: str, server_id: str, *, include_secret: bool = True) -> dict:
    return _MCP_SERVER_STORE.get(owner, server_id, include_secret=include_secret)


def _mcp_client_delete_owner(owner: str) -> int:
    return _MCP_SERVER_STORE.delete_owner(owner)


@app.get('/api3/mcp/servers')
def _mcp_client_servers_route():
    login_error = _mcp_client_login_required_response()
    if login_error:
        return login_error
    owner = _mcp_client_request_principal()
    rows = [_mcp_client_public_server(row) for row in _MCP_SERVER_STORE.list(owner, include_secret=False)]
    return jsonify({'ok': True, 'servers': rows, 'max_servers': _MCP_CLIENT_MAX_SERVERS})


@app.post('/api3/mcp/servers')
def _mcp_client_server_save_route():
    login_error = _mcp_client_login_required_response()
    if login_error:
        return login_error
    owner = _mcp_client_request_principal()
    data = request.get_json(force=False, silent=True) or {}
    raw = data.get('server') if isinstance(data.get('server'), dict) else data
    incoming = _mcp_client_normalize_server(raw, include_secret=True)
    existing = _MCP_SERVER_STORE.get(owner, incoming.get('id'), include_secret=False)
    previous_auth = str(existing.get('auth_type') or '')
    next_auth = str(incoming.get('auth_type') or '')
    secret_update = None
    preserve_secret = bool(existing) and previous_auth == next_auth
    if next_auth == 'bearer' and str(incoming.get('bearer_token') or ''):
        secret_update = {'access_token': str(incoming.get('bearer_token') or '')}
    elif next_auth == 'none' or (existing and previous_auth != next_auth):
        secret_update = {}
        preserve_secret = False
    try:
        saved = _MCP_SERVER_STORE.upsert(owner, incoming, secret_update=secret_update, preserve_secret=preserve_secret)
    except ValueError as exc:
        return jsonify({'ok': False, 'error': 'mcp_server_invalid', 'message': str(exc)}), 400
    public = _mcp_client_public_server(saved)
    if existing and preserve_secret and not public.get('credential_configured'):
        public = _mcp_client_public_server(saved, credential_configured=bool(existing.get('_credential_configured')))
    return jsonify({'ok': True, 'server': public})


@app.delete('/api3/mcp/servers/<server_id>')
def _mcp_client_server_delete_route(server_id: str):
    login_error = _mcp_client_login_required_response()
    if login_error:
        return login_error
    deleted = _MCP_SERVER_STORE.delete(_mcp_client_request_principal(), server_id)
    return jsonify({'ok': True, 'deleted': bool(deleted)})


@app.post('/api3/mcp/servers/<server_id>/disconnect')
def _mcp_client_server_disconnect_route(server_id: str):
    login_error = _mcp_client_login_required_response()
    if login_error:
        return login_error
    owner = _mcp_client_request_principal()
    server = _MCP_SERVER_STORE.get(owner, server_id, include_secret=False)
    if not server:
        return jsonify({'ok': False, 'error': 'mcp_server_not_found'}), 404
    saved = _MCP_SERVER_STORE.upsert(owner, server, secret_update={}, preserve_secret=False)
    return jsonify({'ok': True, 'server': _mcp_client_public_server(saved, credential_configured=False)})


@app.get('/api3/platform-admin/mcp')
def _mcp_client_admin_list_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    query = str(request.args.get('q') or request.args.get('query') or '').strip()
    rows = _MCP_SERVER_STORE.admin_rows(query)
    return jsonify({
        'ok': True,
        'rows': rows[:500],
        'total': len(rows),
        'credential_storage': 'encrypted',
        'key_source': 'environment' if str(os.getenv('APP3_MCP_TOKEN_KEY', '') or '').strip() else 'data_file',
    })


@app.post('/api3/platform-admin/mcp/action')
def _mcp_client_admin_action_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=False, silent=True) or {}
    owner = McpServerStore.normalize_owner(data.get('owner') or '')
    server_id = _mcp_client_clean_id(data.get('server_id') or data.get('id'), '')
    action = str(data.get('action') or '').strip().lower()
    server = _MCP_SERVER_STORE.get(owner, server_id, include_secret=False)
    if not owner or not server:
        return jsonify({'ok': False, 'error': 'mcp_server_not_found'}), 404
    if action == 'delete':
        changed = _MCP_SERVER_STORE.delete(owner, server_id)
    elif action == 'disconnect':
        _MCP_SERVER_STORE.upsert(owner, server, secret_update={}, preserve_secret=False)
        changed = True
    elif action in {'enable', 'disable'}:
        server['enabled'] = action == 'enable'
        _MCP_SERVER_STORE.upsert(owner, server, preserve_secret=True)
        changed = True
    else:
        return jsonify({'ok': False, 'error': 'mcp_admin_action_invalid'}), 400
    audit = globals().get('_platform_admin_audit_append')
    if callable(audit):
        audit('mcp_server_' + action, f'{owner}:{server_id}', {'owner': owner, 'server_id': server_id}, ok=bool(changed))
    return jsonify({'ok': True, 'changed': bool(changed), 'rows': _MCP_SERVER_STORE.admin_rows('')[:500]})
