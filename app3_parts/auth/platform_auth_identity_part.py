# 统一身份与会话基础层。
# SQLite 是 Docker 版本的账号、角色和会话唯一可信来源；旧 JSON 账号仅作为业务数据兼容镜像。

AUTH_IDENTITY_DB_FILE = _app_data_path('auth_identity.db')
AUTH_SESSION_COOKIE = 'apervia_session'
AUTH_SESSION_MAX_AGE_S = max(3600, int(app_getenv('AUTH_SESSION_MAX_AGE_S', str(30 * 24 * 3600)) or (30 * 24 * 3600)))
AUTH_PASSWORD_ITERATIONS = max(200000, int(app_getenv('AUTH_PASSWORD_ITERATIONS', '600000') or 600000))
AUTH_SIGNUP_ENABLED = str(app_getenv('AUTH_SIGNUP_ENABLED', '1') or '1').strip().lower() not in {'0', 'false', 'off', 'no', 'disabled'}
AUTH_DEFAULT_ROLE = str(app_getenv('AUTH_DEFAULT_ROLE', 'pending') or 'pending').strip().lower()
if AUTH_DEFAULT_ROLE not in {'pending', 'user'}:
    AUTH_DEFAULT_ROLE = 'pending'

AUTH_IDENTITY_ROLES = {'admin', 'user', 'pending'}
AUTH_IDENTITY_STATUSES = {'active', 'pending', 'disabled', 'deleted'}
_AUTH_IDENTITY_INIT_LOCK = threading.Lock()
_AUTH_IDENTITY_INITIALIZED = False


def _auth_identity_connect():
    conn = sqlite3.connect(AUTH_IDENTITY_DB_FILE, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 20000')
    return conn


def _auth_identity_create_schema(conn) -> None:
    conn.executescript(
        '''
        CREATE TABLE IF NOT EXISTS identity_users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL CHECK (role IN ('admin', 'user', 'pending')),
            status TEXT NOT NULL CHECK (status IN ('active', 'pending', 'disabled', 'deleted')),
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            password_iterations INTEGER NOT NULL DEFAULT 600000,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            last_login_at REAL NOT NULL DEFAULT 0,
            last_login_ip TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS identity_users_role_status_idx
            ON identity_users(role, status);

        CREATE TABLE IF NOT EXISTS identity_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES identity_users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            revoked_at REAL NOT NULL DEFAULT 0,
            ip TEXT NOT NULL DEFAULT '',
            user_agent TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS identity_sessions_user_idx
            ON identity_sessions(user_id, expires_at);

        CREATE TABLE IF NOT EXISTS identity_audit (
            id TEXT PRIMARY KEY,
            actor_user_id TEXT,
            action TEXT NOT NULL,
            target_user_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            ip TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS identity_audit_created_idx
            ON identity_audit(created_at DESC);
        '''
    )


def _auth_identity_audit(conn, action: str, *, actor_user_id: str = '', target_user_id: str = '', metadata: dict | None = None) -> None:
    try:
        ip = _client_ip()
    except Exception:
        ip = ''
    conn.execute(
        '''INSERT INTO identity_audit
           (id, actor_user_id, action, target_user_id, metadata_json, ip, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (
            uuid.uuid4().hex,
            str(actor_user_id or '') or None,
            str(action or '')[:80],
            str(target_user_id or '') or None,
            json.dumps(metadata or {}, ensure_ascii=False, separators=(',', ':')),
            str(ip or '')[:96],
            _utc_ts(),
        ),
    )


def _auth_identity_name(email: str, name: str = '') -> str:
    clean = re.sub(r'\s+', ' ', str(name or '').strip())[:80]
    if clean:
        return clean
    normalized = _normalize_login_email(email)
    return (normalized.split('@', 1)[0] if '@' in normalized else normalized)[:80]


def _auth_identity_hash_password(password: str, salt_hex: str = '', iterations: int | None = None) -> tuple[str, str, int]:
    rounds = max(200000, int(iterations or AUTH_PASSWORD_ITERATIONS))
    salt = bytes.fromhex(str(salt_hex or '').strip()) if salt_hex else os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', str(password or '').encode('utf-8', 'ignore'), salt, rounds)
    return digest.hex(), salt.hex(), rounds


def _auth_identity_row_public(row) -> dict:
    obj = dict(row or {})
    role = str(obj.get('role') or 'user').strip().lower()
    status = str(obj.get('status') or 'disabled').strip().lower()
    return {
        'id': str(obj.get('id') or ''),
        'email': _normalize_login_email(obj.get('email') or ''),
        'name': _auth_identity_name(obj.get('email') or '', obj.get('name') or ''),
        'role': role if role in AUTH_IDENTITY_ROLES else 'user',
        'status': status if status in AUTH_IDENTITY_STATUSES else 'disabled',
        'created_at': _fmt_ts(obj.get('created_at')),
        'updated_at': _fmt_ts(obj.get('updated_at')),
        'last_login_at': _fmt_ts(obj.get('last_login_at')),
        'last_login_ip': str(obj.get('last_login_ip') or ''),
    }


def _auth_identity_user_by_email(email: str):
    normalized = _normalize_login_email(email)
    if not normalized:
        return None
    with contextlib.closing(_auth_identity_connect()) as conn:
        return conn.execute('SELECT * FROM identity_users WHERE email = ?', (normalized,)).fetchone()


def _auth_identity_user_by_id(user_id: str):
    raw = str(user_id or '').strip()
    if not raw:
        return None
    with contextlib.closing(_auth_identity_connect()) as conn:
        return conn.execute('SELECT * FROM identity_users WHERE id = ?', (raw,)).fetchone()


def _auth_identity_user_count() -> int:
    with contextlib.closing(_auth_identity_connect()) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM identity_users WHERE status <> 'deleted'").fetchone()
    return int((row or {})['n'] or 0)


def _auth_identity_sync_legacy_user(email: str, password: str = '', *, enabled: bool = True) -> None:
    normalized = _normalize_login_email(email)
    if not normalized:
        return
    existing = _auth_get_user(normalized)
    if not existing and password:
        _auth_create_user_record_locked(normalized, password)
        _auth_users_save()
        existing = _auth_get_user(normalized)
    if existing and bool(existing.get('enabled', True)) != bool(enabled):
        try:
            _auth_user_set_enabled(normalized, bool(enabled))
        except ValueError:
            pass


def _auth_identity_init() -> None:
    global _AUTH_IDENTITY_INITIALIZED
    with _AUTH_IDENTITY_INIT_LOCK:
        if _AUTH_IDENTITY_INITIALIZED:
            return
        os.makedirs(os.path.dirname(AUTH_IDENTITY_DB_FILE) or APP_DATA_DIR, exist_ok=True)
        with contextlib.closing(_auth_identity_connect()) as conn:
            conn.execute('PRAGMA journal_mode = WAL')
            _auth_identity_create_schema(conn)
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM identity_sessions WHERE expires_at <= ? OR revoked_at > 0', (_utc_ts(),))
            conn.commit()
        _AUTH_IDENTITY_INITIALIZED = True


def _auth_identity_register(email: str, password: str, name: str = '') -> dict:
    normalized = _normalize_login_email(email)
    if not normalized or '@' not in normalized:
        raise ValueError('请输入正确的邮箱地址')
    _auth_validate_password_policy(password, label='密码')
    now = _utc_ts()
    password_hash, password_salt, password_iterations = _auth_identity_hash_password(password)
    with contextlib.closing(_auth_identity_connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        count = int(conn.execute("SELECT COUNT(*) FROM identity_users WHERE status <> 'deleted'").fetchone()[0] or 0)
        if count > 0 and not AUTH_SIGNUP_ENABLED:
            raise ValueError('当前实例未开放注册')
        if conn.execute('SELECT 1 FROM identity_users WHERE email = ?', (normalized,)).fetchone():
            raise ValueError('该邮箱已经注册')
        first_user = count == 0
        role = 'admin' if first_user else AUTH_DEFAULT_ROLE
        status = 'active' if role in {'admin', 'user'} else 'pending'
        user_id = uuid.uuid4().hex
        conn.execute(
            '''INSERT INTO identity_users
               (id, email, name, role, status, password_hash, password_salt,
                password_iterations, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (user_id, normalized, _auth_identity_name(normalized, name), role, status, password_hash, password_salt, password_iterations, now, now),
        )
        _auth_identity_audit(conn, 'user_registered', target_user_id=user_id, metadata={'role': role, 'status': status})
        conn.commit()
    _auth_identity_sync_legacy_user(normalized, password, enabled=(status == 'active'))
    return _auth_identity_row_public(_auth_identity_user_by_id(user_id))


def _auth_identity_verify_password(row, password: str) -> bool:
    obj = dict(row or {})
    saved_hash = str(obj.get('password_hash') or '').strip()
    salt = str(obj.get('password_salt') or '').strip()
    if not saved_hash or not salt:
        return False
    calculated, _, _ = _auth_identity_hash_password(str(password or ''), salt, int(obj.get('password_iterations') or 200000))
    try:
        return secrets.compare_digest(calculated, saved_hash)
    except Exception:
        return calculated == saved_hash


def _auth_identity_create_session(user_id: str) -> tuple[str, dict]:
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    now = _utc_ts()
    try:
        user_agent = str(request.headers.get('User-Agent') or '')[:300]
        ip = _client_ip()
    except Exception:
        user_agent = ''
        ip = ''
    session_id = uuid.uuid4().hex
    with contextlib.closing(_auth_identity_connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute(
            '''INSERT INTO identity_sessions
               (id, user_id, token_hash, created_at, last_seen_at, expires_at, revoked_at, ip, user_agent)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)''',
            (session_id, user_id, token_hash, now, now, now + AUTH_SESSION_MAX_AGE_S, str(ip or '')[:96], user_agent),
        )
        conn.execute('UPDATE identity_users SET last_login_at = ?, last_login_ip = ?, updated_at = ? WHERE id = ?', (now, str(ip or '')[:96], now, user_id))
        _auth_identity_audit(conn, 'session_created', actor_user_id=user_id, target_user_id=user_id, metadata={'session_id': session_id[:12]})
        conn.commit()
    return raw_token, _auth_identity_row_public(_auth_identity_user_by_id(user_id))


def _auth_identity_sign_in(email: str, password: str) -> tuple[str, dict]:
    row = _auth_identity_user_by_email(email)
    if not row or not _auth_identity_verify_password(row, password):
        raise ValueError('邮箱或密码错误')
    user = _auth_identity_row_public(row)
    if user['status'] == 'pending' or user['role'] == 'pending':
        raise PermissionError('账号正在等待管理员审核')
    if user['status'] != 'active':
        raise PermissionError('账号已停用，请联系管理员')
    return _auth_identity_create_session(user['id'])


def _auth_identity_token_hash() -> str:
    try:
        token = str(request.cookies.get(AUTH_SESSION_COOKIE) or '').strip()
    except Exception:
        token = ''
    return hashlib.sha256(token.encode('utf-8')).hexdigest() if token else ''


def _auth_identity_current_user() -> dict:
    token_hash = _auth_identity_token_hash()
    if not token_hash:
        return {}
    now = _utc_ts()
    with contextlib.closing(_auth_identity_connect()) as conn:
        row = conn.execute(
            '''SELECT u.*, s.id AS session_id, s.last_seen_at, s.expires_at
               FROM identity_sessions s
               JOIN identity_users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.revoked_at = 0 AND s.expires_at > ?''',
            (token_hash, now),
        ).fetchone()
        if not row:
            return {}
        user = _auth_identity_row_public(row)
        if user['status'] != 'active' or user['role'] == 'pending':
            conn.execute('UPDATE identity_sessions SET revoked_at = ? WHERE token_hash = ?', (now, token_hash))
            conn.commit()
            return {}
        if now - float(row['last_seen_at'] or 0) >= 60:
            conn.execute('UPDATE identity_sessions SET last_seen_at = ? WHERE token_hash = ?', (now, token_hash))
            conn.commit()
        user['session_id'] = str(row['session_id'] or '')
        user['expires_at'] = _fmt_ts(row['expires_at'])
        return user


def _auth_identity_revoke_current_session() -> bool:
    token_hash = _auth_identity_token_hash()
    if not token_hash:
        return False
    now = _utc_ts()
    with contextlib.closing(_auth_identity_connect()) as conn:
        cur = conn.execute('UPDATE identity_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at = 0', (now, token_hash))
        conn.commit()
        return bool(cur.rowcount)


def _auth_identity_revoke_user_sessions(user_id: str) -> int:
    with contextlib.closing(_auth_identity_connect()) as conn:
        cur = conn.execute('UPDATE identity_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at = 0', (_utc_ts(), str(user_id or '')))
        conn.commit()
        return int(cur.rowcount or 0)


def _auth_identity_revoke_email_sessions(email: str) -> int:
    row = _auth_identity_user_by_email(email)
    if not row:
        return 0
    return _auth_identity_revoke_user_sessions(str(row['id'] or ''))


def _auth_identity_mark_deleted(email: str) -> bool:
    normalized = _normalize_login_email(email)
    if not normalized:
        return False
    now = _utc_ts()
    with contextlib.closing(_auth_identity_connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT id, role, status FROM identity_users WHERE email = ?', (normalized,)).fetchone()
        if not row:
            return False
        if str(row['role'] or '') == 'admin' and str(row['status'] or '') == 'active':
            active_admins = int(conn.execute("SELECT COUNT(*) FROM identity_users WHERE role = 'admin' AND status = 'active'").fetchone()[0] or 0)
            if active_admins <= 1:
                raise ValueError('最后一个管理员不能删除自己的账号')
        user_id = str(row['id'] or '')
        conn.execute("UPDATE identity_users SET status = 'deleted', updated_at = ? WHERE id = ?", (now, user_id))
        conn.execute('UPDATE identity_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at = 0', (now, user_id))
        _auth_identity_audit(conn, 'account_delete_requested', actor_user_id=user_id, target_user_id=user_id)
        conn.commit()
    return True


def _auth_identity_validate_delete(email: str) -> None:
    normalized = _normalize_login_email(email)
    with contextlib.closing(_auth_identity_connect()) as conn:
        row = conn.execute('SELECT role, status FROM identity_users WHERE email = ?', (normalized,)).fetchone()
        if not row or str(row['role'] or '') != 'admin' or str(row['status'] or '') != 'active':
            return
        active_admins = int(conn.execute("SELECT COUNT(*) FROM identity_users WHERE role = 'admin' AND status = 'active'").fetchone()[0] or 0)
    if active_admins <= 1:
        raise ValueError('最后一个管理员不能删除自己的账号')


def _auth_identity_set_session_cookie(resp, token: str):
    resp.set_cookie(
        AUTH_SESSION_COOKIE,
        str(token or ''),
        max_age=AUTH_SESSION_MAX_AGE_S,
        httponly=True,
        samesite='Lax',
        secure=_app_cookie_secure(),
        path='/',
    )
    return resp


def _auth_identity_clear_session_cookie(resp):
    resp.set_cookie(AUTH_SESSION_COOKIE, '', expires=0, httponly=True, samesite='Lax', secure=_app_cookie_secure(), path='/')
    return resp


def _auth_identity_current_account() -> dict:
    user = _auth_identity_current_user()
    if not user:
        return {
            'ok': True,
            'trusted': False,
            'logged_in': False,
            'email': '',
            'email_masked': '',
            'name': '',
            'role': '',
            'status': '',
            'login_method': '',
            'login_method_label': '',
        }
    email = _normalize_login_email(user.get('email') or '')
    legacy_user = _auth_get_user(email) or {}
    return {
        'ok': True,
        'trusted': True,
        'logged_in': True,
        'user_id': str(user.get('id') or ''),
        'email': email,
        'email_masked': _mask_login_email(email),
        'name': str(user.get('name') or ''),
        'role': str(user.get('role') or 'user'),
        'status': str(user.get('status') or 'active'),
        'is_admin': str(user.get('role') or '') == 'admin',
        'login_method': 'password',
        'login_method_label': '密码登录',
        'last_login_at': str(user.get('last_login_at') or ''),
        'session_expires_at': str(user.get('expires_at') or ''),
        'allow_private_search_upstreams': _auth_user_allows_private_search_upstreams(legacy_user),
    }


def _auth_identity_admin_guard():
    user = _auth_identity_current_user()
    if not user:
        return jsonify({'error': 'login_required', 'message': '请先登录', 'login_url': '/login'}), 401
    if str(user.get('role') or '') != 'admin':
        return jsonify({'error': 'admin_required', 'message': '需要管理员权限'}), 403
    return None


def _auth_identity_admin_users() -> list[dict]:
    with contextlib.closing(_auth_identity_connect()) as conn:
        rows = conn.execute('SELECT * FROM identity_users ORDER BY created_at ASC').fetchall()
    return [_auth_identity_row_public(row) for row in rows]


def _auth_identity_admin_summary() -> dict:
    with contextlib.closing(_auth_identity_connect()) as conn:
        rows = conn.execute('SELECT role, status, COUNT(*) AS n FROM identity_users GROUP BY role, status').fetchall()
        active_sessions = int(conn.execute('SELECT COUNT(*) FROM identity_sessions WHERE revoked_at = 0 AND expires_at > ?', (_utc_ts(),)).fetchone()[0] or 0)
    counts = {'total': 0, 'admin': 0, 'user': 0, 'pending': 0, 'disabled': 0}
    for row in rows:
        n = int(row['n'] or 0)
        counts['total'] += n
        role = str(row['role'] or '')
        status = str(row['status'] or '')
        if role in counts:
            counts[role] += n
        if status == 'disabled':
            counts['disabled'] += n
    counts['active_sessions'] = active_sessions
    return counts


def _auth_identity_admin_update_user(user_id: str, *, role: str | None = None, status: str | None = None, name: str | None = None) -> dict:
    target_id = str(user_id or '').strip()
    if not target_id:
        raise ValueError('缺少用户 ID')
    clean_role = str(role or '').strip().lower() if role is not None else None
    clean_status = str(status or '').strip().lower() if status is not None else None
    if clean_role is not None and clean_role not in AUTH_IDENTITY_ROLES:
        raise ValueError('无效角色')
    if clean_status is not None and clean_status not in AUTH_IDENTITY_STATUSES:
        raise ValueError('无效账号状态')
    actor = _auth_identity_current_user()
    with contextlib.closing(_auth_identity_connect()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM identity_users WHERE id = ?', (target_id,)).fetchone()
        if not row:
            raise ValueError('用户不存在')
        old = _auth_identity_row_public(row)
        next_role = clean_role if clean_role is not None else old['role']
        next_status = clean_status if clean_status is not None else old['status']
        if old['role'] == 'admin' and old['status'] == 'active' and (next_role != 'admin' or next_status != 'active'):
            admin_count = int(conn.execute("SELECT COUNT(*) FROM identity_users WHERE role = 'admin' AND status = 'active'").fetchone()[0] or 0)
            if admin_count <= 1:
                raise ValueError('不能停用或降级最后一个管理员')
        next_name = _auth_identity_name(old['email'], name if name is not None else old['name'])
        if next_role == 'pending':
            next_status = 'pending'
        elif next_status == 'pending':
            next_status = 'active'
        now = _utc_ts()
        conn.execute('UPDATE identity_users SET name = ?, role = ?, status = ?, updated_at = ? WHERE id = ?', (next_name, next_role, next_status, now, target_id))
        if next_status != 'active':
            conn.execute('UPDATE identity_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at = 0', (now, target_id))
        _auth_identity_audit(
            conn,
            'admin_user_updated',
            actor_user_id=str(actor.get('id') or ''),
            target_user_id=target_id,
            metadata={'from': {'role': old['role'], 'status': old['status']}, 'to': {'role': next_role, 'status': next_status}},
        )
        conn.commit()
    updated = _auth_identity_row_public(_auth_identity_user_by_id(target_id))
    _auth_identity_sync_legacy_user(updated['email'], enabled=(updated['status'] == 'active'))
    return updated
