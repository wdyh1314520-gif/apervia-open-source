class _WerkzeugNoiseFilter(logging.Filter):
    def filter(self, record):
        try:
            msg = str(record.getMessage() or '')
        except Exception:
            return True
        noisy_paths = (
        )
        return not any(path in msg for path in noisy_paths)


try:
    _werkzeug_logger = logging.getLogger('werkzeug')
    _werkzeug_logger.addFilter(_WerkzeugNoiseFilter())
except Exception:
    pass

_REMOTE_IMAGE_FAIL_CACHE: dict[str, float] = {}
_REMOTE_IMAGE_FAIL_LOCK = threading.Lock()
_REMOTE_IMAGE_LOCKS: dict[str, threading.Lock] = {}
_REMOTE_IMAGE_LOCKS_GUARD = threading.Lock()
_REMOTE_IMAGE_HOST_LOCKS: dict[str, threading.Semaphore] = {}
_REMOTE_IMAGE_HOST_LOCKS_GUARD = threading.Lock()
_HOST_FETCH_GUARD = threading.Lock()

_HOST_FETCH_STATE: dict[str, dict[str, float | int]] = {}
_HOST_FETCH_STATE_FILE_DEFAULT = _app_data_path('host_fetch_state.json')
_HOST_FETCH_DB_FILE_DEFAULT = _app_data_path('host_fetch_state.db')
_HOST_FETCH_DB_GUARD = threading.Lock()
_GLOBAL_FETCH_BUDGET_COND = threading.Condition(threading.Lock())
_GLOBAL_FETCH_BUDGET_STATE = {
    'active_total': 0,
    'peak_total': 0,
    'task_active': {},
    'host_active': {},
    'waiters': 0,
}


class HostFetchBudgetTimeout(RuntimeError):
    def __init__(self, host: str, task_type: str, wait_s: float):
        super().__init__(f'fetch_budget_timeout:{task_type}:{host}:{wait_s:.2f}')
        self.host = host
        self.task_type = task_type
        self.wait_s = float(wait_s)


def _host_fetch_sqlite_module():
    return __import__('sqlite3')


def _host_fetch_state_seed(now: float | None = None) -> dict:
    ts = float(now if now is not None else time.time())
    return {
        'next_ok_at': 0.0,
        'last_req_at': 0.0,
        'failures': 0,
        'successes': 0,
        'blocked_count': 0,
        'tls_failures': 0,
        'playwright_failures': 0,
        'empty_count': 0,
        'last_status': 0,
        'last_success_at': 0.0,
        'hard_fail_until': 0.0,
        'last_success_method': '',
        'strategy_hint': '',
        'last_error': '',
        'updated_at': ts,
    }


def _host_fetch_legacy_state_file_path() -> str:
    raw = str(app_getenv('HOST_FETCH_STATE_FILE', '') or '').strip()
    return raw or _HOST_FETCH_STATE_FILE_DEFAULT


def _host_fetch_db_file_path() -> str:
    raw = str(app_getenv('HOST_FETCH_DB_FILE', '') or '').strip()
    return raw or _HOST_FETCH_DB_FILE_DEFAULT


def _host_fetch_state_ttl_seconds() -> float:
    try:
        return max(3600.0, float(app_getenv('HOST_FETCH_STATE_TTL', str(14 * 24 * 3600)) or (14 * 24 * 3600)))
    except Exception:
        return float(14 * 24 * 3600)


def _host_fetch_persist_debounce_seconds() -> float:
    try:
        return max(0.2, float(app_getenv('HOST_FETCH_PERSIST_DEBOUNCE', '2.0') or 2.0))
    except Exception:
        return 2.0


def _host_fetch_normalize_state(state: dict | None = None, now: float | None = None) -> dict:
    base = _host_fetch_state_seed(now)
    if not isinstance(state, dict):
        return base
    int_fields = {'failures', 'successes', 'blocked_count', 'tls_failures', 'playwright_failures', 'empty_count', 'last_status'}
    float_fields = {'next_ok_at', 'last_req_at', 'last_success_at', 'hard_fail_until', 'updated_at'}
    str_fields = {'last_success_method', 'strategy_hint', 'last_error'}
    for key in int_fields:
        try:
            base[key] = int(state.get(key) or 0)
        except Exception:
            base[key] = 0
    for key in float_fields:
        try:
            base[key] = float(state.get(key) or 0.0)
        except Exception:
            base[key] = 0.0
    for key in str_fields:
        try:
            base[key] = str(state.get(key) or '')[:160]
        except Exception:
            base[key] = ''
    return base


def _host_fetch_db_connect():
    sql = _host_fetch_sqlite_module()
    path = _host_fetch_db_file_path()
    conn = sql.connect(path, timeout=30.0, check_same_thread=False)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except Exception:
        pass
    try:
        conn.execute('PRAGMA synchronous=NORMAL')
    except Exception:
        pass
    return conn


def _host_fetch_stats_ttl_seconds() -> float:
    try:
        return max(3600.0, float(app_getenv('HOST_FETCH_STATS_TTL', str(14 * 24 * 3600)) or (14 * 24 * 3600)))
    except Exception:
        return float(14 * 24 * 3600)


def _host_fetch_db_optimize_interval_seconds() -> float:
    try:
        return max(3600.0, float(app_getenv('HOST_FETCH_DB_OPTIMIZE_INTERVAL', str(24 * 3600)) or (24 * 3600)))
    except Exception:
        return float(24 * 3600)


def _host_fetch_db_cleanup_conn(conn, now: float | None = None, force: bool = False) -> None:
    ts = float(now or time.time())
    interval = _host_fetch_db_optimize_interval_seconds()
    last = float(getattr(_host_fetch_db_cleanup_conn, '_last_at', 0.0) or 0.0)
    if not force and last > 0 and (ts - last) < interval:
        return
    try:
        state_ttl = _host_fetch_state_ttl_seconds()
        if state_ttl > 0:
            expire_before = ts - state_ttl
            conn.execute('DELETE FROM host_state WHERE updated_at > 0 AND updated_at < ? AND hard_fail_until <= ?', (expire_before, ts))
        stats_ttl = _host_fetch_stats_ttl_seconds()
        if stats_ttl > 0:
            stats_expire_before = ts - stats_ttl
            conn.execute('DELETE FROM fetch_stats WHERE updated_at > 0 AND updated_at < ?', (stats_expire_before,))
        try:
            conn.execute('PRAGMA optimize')
        except Exception:
            pass
        setattr(_host_fetch_db_cleanup_conn, '_last_at', ts)
    except Exception:
        app_logger.exception('[host_fetch] db_cleanup_failed')


def _host_fetch_load_legacy_json_payload() -> dict:
    path = _host_fetch_legacy_state_file_path()
    payload = {}
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f) or {}
    except Exception:
        app_logger.exception('[host_fetch] load_legacy_json_failed')
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _host_fetch_db_ensure() -> None:
    if getattr(_host_fetch_db_ensure, '_ready', False):
        return
    with _HOST_FETCH_DB_GUARD:
        if getattr(_host_fetch_db_ensure, '_ready', False):
            return
        now = time.time()
        conn = _host_fetch_db_connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS host_state (
                    host TEXT PRIMARY KEY,
                    next_ok_at REAL DEFAULT 0,
                    last_req_at REAL DEFAULT 0,
                    failures INTEGER DEFAULT 0,
                    successes INTEGER DEFAULT 0,
                    blocked_count INTEGER DEFAULT 0,
                    tls_failures INTEGER DEFAULT 0,
                    playwright_failures INTEGER DEFAULT 0,
                    empty_count INTEGER DEFAULT 0,
                    last_status INTEGER DEFAULT 0,
                    last_success_at REAL DEFAULT 0,
                    hard_fail_until REAL DEFAULT 0,
                    last_success_method TEXT DEFAULT '',
                    strategy_hint TEXT DEFAULT '',
                    last_error TEXT DEFAULT '',
                    updated_at REAL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fetch_stats (
                    host TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    total_requests INTEGER DEFAULT 0,
                    total_successes INTEGER DEFAULT 0,
                    total_failures INTEGER DEFAULT 0,
                    total_blocked INTEGER DEFAULT 0,
                    total_tls_failures INTEGER DEFAULT 0,
                    total_playwright_failures INTEGER DEFAULT 0,
                    total_empty INTEGER DEFAULT 0,
                    total_wait_events INTEGER DEFAULT 0,
                    total_wait_seconds REAL DEFAULT 0,
                    total_cooldown_skips INTEGER DEFAULT 0,
                    total_budget_wait_events INTEGER DEFAULT 0,
                    total_budget_wait_seconds REAL DEFAULT 0,
                    total_budget_timeouts INTEGER DEFAULT 0,
                    total_provider_only INTEGER DEFAULT 0,
                    total_playwright_successes INTEGER DEFAULT 0,
                    last_status INTEGER DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    updated_at REAL DEFAULT 0,
                    PRIMARY KEY (host, task_type)
                )
            """)
            conn.execute('CREATE INDEX IF NOT EXISTS idx_fetch_stats_task_updated ON fetch_stats(task_type, updated_at DESC)')
            _host_fetch_db_cleanup_conn(conn, now=now)
            cur = conn.execute('SELECT COUNT(1) FROM host_state')
            row = cur.fetchone() if cur is not None else None
            if int((row or [0])[0] or 0) <= 0:
                payload = _host_fetch_load_legacy_json_payload()
                hosts_raw = payload.get('hosts') if isinstance(payload, dict) else {}
                if isinstance(hosts_raw, dict) and hosts_raw:
                    rows = []
                    ttl = _host_fetch_state_ttl_seconds()
                    for host, raw_state in hosts_raw.items():
                        host_key = str(host or '').strip().lower()
                        if not host_key:
                            continue
                        state = _host_fetch_normalize_state(raw_state if isinstance(raw_state, dict) else {}, now=now)
                        updated_at = float(state.get('updated_at') or 0.0)
                        hard_fail_until = float(state.get('hard_fail_until') or 0.0)
                        if ttl > 0 and updated_at > 0 and (now - updated_at) > ttl and hard_fail_until <= now:
                            continue
                        rows.append((
                            host_key,
                            float(state.get('next_ok_at') or 0.0),
                            float(state.get('last_req_at') or 0.0),
                            int(state.get('failures') or 0),
                            int(state.get('successes') or 0),
                            int(state.get('blocked_count') or 0),
                            int(state.get('tls_failures') or 0),
                            int(state.get('playwright_failures') or 0),
                            int(state.get('empty_count') or 0),
                            int(state.get('last_status') or 0),
                            float(state.get('last_success_at') or 0.0),
                            float(state.get('hard_fail_until') or 0.0),
                            str(state.get('last_success_method') or '')[:80],
                            str(state.get('strategy_hint') or '')[:80],
                            str(state.get('last_error') or '')[:160],
                            float(state.get('updated_at') or now),
                        ))
                    if rows:
                        conn.executemany("""
                            INSERT INTO host_state (
                                host, next_ok_at, last_req_at, failures, successes, blocked_count,
                                tls_failures, playwright_failures, empty_count, last_status,
                                last_success_at, hard_fail_until, last_success_method,
                                strategy_hint, last_error, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(host) DO UPDATE SET
                                next_ok_at=excluded.next_ok_at,
                                last_req_at=excluded.last_req_at,
                                failures=excluded.failures,
                                successes=excluded.successes,
                                blocked_count=excluded.blocked_count,
                                tls_failures=excluded.tls_failures,
                                playwright_failures=excluded.playwright_failures,
                                empty_count=excluded.empty_count,
                                last_status=excluded.last_status,
                                last_success_at=excluded.last_success_at,
                                hard_fail_until=excluded.hard_fail_until,
                                last_success_method=excluded.last_success_method,
                                strategy_hint=excluded.strategy_hint,
                                last_error=excluded.last_error,
                                updated_at=excluded.updated_at
                        """, rows)
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        setattr(_host_fetch_db_ensure, '_ready', True)


def _host_fetch_stats_bump(host: str, task_type: str = 'web_page', **delta) -> None:
    host_key = str(host or '').strip().lower() or '__unknown__'
    task_key = str(task_type or 'web_page').strip().lower() or 'web_page'
    now = float(delta.pop('updated_at', time.time()) or time.time())
    last_status = int(delta.pop('last_status', 0) or 0)
    last_error = str(delta.pop('last_error', '') or '')[:160]
    columns = {
        'total_requests': int(delta.pop('requests', 0) or 0),
        'total_successes': int(delta.pop('successes', 0) or 0),
        'total_failures': int(delta.pop('failures', 0) or 0),
        'total_blocked': int(delta.pop('blocked', 0) or 0),
        'total_tls_failures': int(delta.pop('tls_failures', 0) or 0),
        'total_playwright_failures': int(delta.pop('playwright_failures', 0) or 0),
        'total_empty': int(delta.pop('empty', 0) or 0),
        'total_wait_events': int(delta.pop('wait_events', 0) or 0),
        'total_wait_seconds': float(delta.pop('wait_seconds', 0.0) or 0.0),
        'total_cooldown_skips': int(delta.pop('cooldown_skips', 0) or 0),
        'total_budget_wait_events': int(delta.pop('budget_wait_events', 0) or 0),
        'total_budget_wait_seconds': float(delta.pop('budget_wait_seconds', 0.0) or 0.0),
        'total_budget_timeouts': int(delta.pop('budget_timeouts', 0) or 0),
        'total_provider_only': int(delta.pop('provider_only', 0) or 0),
        'total_playwright_successes': int(delta.pop('playwright_successes', 0) or 0),
    }
    if not any(v for v in columns.values()) and not last_status and not last_error:
        return
    _host_fetch_db_ensure()
    conn = _host_fetch_db_connect()
    try:
        for row_host in (host_key, '__global__'):
            conn.execute("""
                INSERT INTO fetch_stats (
                    host, task_type, total_requests, total_successes, total_failures, total_blocked,
                    total_tls_failures, total_playwright_failures, total_empty, total_wait_events,
                    total_wait_seconds, total_cooldown_skips, total_budget_wait_events,
                    total_budget_wait_seconds, total_budget_timeouts, total_provider_only,
                    total_playwright_successes, last_status, last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(host, task_type) DO UPDATE SET
                    total_requests = fetch_stats.total_requests + excluded.total_requests,
                    total_successes = fetch_stats.total_successes + excluded.total_successes,
                    total_failures = fetch_stats.total_failures + excluded.total_failures,
                    total_blocked = fetch_stats.total_blocked + excluded.total_blocked,
                    total_tls_failures = fetch_stats.total_tls_failures + excluded.total_tls_failures,
                    total_playwright_failures = fetch_stats.total_playwright_failures + excluded.total_playwright_failures,
                    total_empty = fetch_stats.total_empty + excluded.total_empty,
                    total_wait_events = fetch_stats.total_wait_events + excluded.total_wait_events,
                    total_wait_seconds = fetch_stats.total_wait_seconds + excluded.total_wait_seconds,
                    total_cooldown_skips = fetch_stats.total_cooldown_skips + excluded.total_cooldown_skips,
                    total_budget_wait_events = fetch_stats.total_budget_wait_events + excluded.total_budget_wait_events,
                    total_budget_wait_seconds = fetch_stats.total_budget_wait_seconds + excluded.total_budget_wait_seconds,
                    total_budget_timeouts = fetch_stats.total_budget_timeouts + excluded.total_budget_timeouts,
                    total_provider_only = fetch_stats.total_provider_only + excluded.total_provider_only,
                    total_playwright_successes = fetch_stats.total_playwright_successes + excluded.total_playwright_successes,
                    last_status = CASE WHEN excluded.last_status != 0 THEN excluded.last_status ELSE fetch_stats.last_status END,
                    last_error = CASE WHEN excluded.last_error != '' THEN excluded.last_error ELSE fetch_stats.last_error END,
                    updated_at = excluded.updated_at
            """, (
                row_host, task_key,
                columns['total_requests'], columns['total_successes'], columns['total_failures'], columns['total_blocked'],
                columns['total_tls_failures'], columns['total_playwright_failures'], columns['total_empty'], columns['total_wait_events'],
                columns['total_wait_seconds'], columns['total_cooldown_skips'], columns['total_budget_wait_events'],
                columns['total_budget_wait_seconds'], columns['total_budget_timeouts'], columns['total_provider_only'],
                columns['total_playwright_successes'], last_status, last_error, now,
            ))
        _host_fetch_db_cleanup_conn(conn, now=now)
        conn.commit()
    except Exception:
        app_logger.exception('[host_fetch] stats_bump_failed host=%s task=%s', host_key, task_key)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _host_fetch_load_persisted_state(force: bool = False):
    if getattr(_host_fetch_load_persisted_state, '_loaded', False) and not force:
        return
    _host_fetch_db_ensure()
    now = time.time()
    ttl = _host_fetch_state_ttl_seconds()
    normalized = {}
    conn = _host_fetch_db_connect()
    try:
        cur = conn.execute("""
            SELECT host, next_ok_at, last_req_at, failures, successes, blocked_count,
                   tls_failures, playwright_failures, empty_count, last_status,
                   last_success_at, hard_fail_until, last_success_method,
                   strategy_hint, last_error, updated_at
            FROM host_state
        """)
        rows = cur.fetchall() if cur is not None else []
    except Exception:
        app_logger.exception('[host_fetch] load_state_failed')
        rows = []
    finally:
        try:
            conn.close()
        except Exception:
            pass
    for row in rows:
        host_key = str((row[0] if row else '') or '').strip().lower()
        if not host_key:
            continue
        state = _host_fetch_normalize_state({
            'next_ok_at': row[1], 'last_req_at': row[2], 'failures': row[3], 'successes': row[4],
            'blocked_count': row[5], 'tls_failures': row[6], 'playwright_failures': row[7],
            'empty_count': row[8], 'last_status': row[9], 'last_success_at': row[10],
            'hard_fail_until': row[11], 'last_success_method': row[12], 'strategy_hint': row[13],
            'last_error': row[14], 'updated_at': row[15],
        }, now=now)
        updated_at = float(state.get('updated_at') or 0.0)
        hard_fail_until = float(state.get('hard_fail_until') or 0.0)
        if ttl > 0 and updated_at > 0 and (now - updated_at) > ttl and hard_fail_until <= now:
            continue
        normalized[host_key] = state
    with _HOST_FETCH_GUARD:
        if force or not _HOST_FETCH_STATE:
            _HOST_FETCH_STATE.clear()
            _HOST_FETCH_STATE.update(normalized)
        else:
            for host_key, state in normalized.items():
                if host_key not in _HOST_FETCH_STATE:
                    _HOST_FETCH_STATE[host_key] = state
    setattr(_host_fetch_load_persisted_state, '_loaded', True)


def _host_fetch_save_persisted_state(force: bool = False):
    _host_fetch_load_persisted_state()
    now = time.time()
    dirty = bool(getattr(_host_fetch_save_persisted_state, '_dirty', False))
    last_save_at = float(getattr(_host_fetch_save_persisted_state, '_last_save_at', 0.0) or 0.0)
    if not force and not dirty:
        return
    if not force and (now - last_save_at) < _host_fetch_persist_debounce_seconds():
        return
    with _HOST_FETCH_GUARD:
        snapshot = [
            (
                str(host or '').strip().lower(),
                float(state.get('next_ok_at') or 0.0), float(state.get('last_req_at') or 0.0),
                int(state.get('failures') or 0), int(state.get('successes') or 0), int(state.get('blocked_count') or 0),
                int(state.get('tls_failures') or 0), int(state.get('playwright_failures') or 0), int(state.get('empty_count') or 0),
                int(state.get('last_status') or 0), float(state.get('last_success_at') or 0.0), float(state.get('hard_fail_until') or 0.0),
                str(state.get('last_success_method') or '')[:80], str(state.get('strategy_hint') or '')[:80],
                str(state.get('last_error') or '')[:160], float(state.get('updated_at') or now),
            )
            for host, state in (_HOST_FETCH_STATE or {}).items() if str(host or '').strip()
        ]
    _host_fetch_db_ensure()
    conn = _host_fetch_db_connect()
    try:
        conn.executemany("""
            INSERT INTO host_state (
                host, next_ok_at, last_req_at, failures, successes, blocked_count,
                tls_failures, playwright_failures, empty_count, last_status,
                last_success_at, hard_fail_until, last_success_method,
                strategy_hint, last_error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(host) DO UPDATE SET
                next_ok_at=excluded.next_ok_at,
                last_req_at=excluded.last_req_at,
                failures=excluded.failures,
                successes=excluded.successes,
                blocked_count=excluded.blocked_count,
                tls_failures=excluded.tls_failures,
                playwright_failures=excluded.playwright_failures,
                empty_count=excluded.empty_count,
                last_status=excluded.last_status,
                last_success_at=excluded.last_success_at,
                hard_fail_until=excluded.hard_fail_until,
                last_success_method=excluded.last_success_method,
                strategy_hint=excluded.strategy_hint,
                last_error=excluded.last_error,
                updated_at=excluded.updated_at
        """, snapshot)
        if snapshot:
            _host_fetch_db_cleanup_conn(conn, now=now)
        conn.commit()
        setattr(_host_fetch_save_persisted_state, '_dirty', False)
        setattr(_host_fetch_save_persisted_state, '_last_save_at', now)
    except Exception:
        app_logger.exception('[host_fetch] save_state_failed')
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _host_fetch_mark_dirty(force_save: bool = False):
    setattr(_host_fetch_save_persisted_state, '_dirty', True)
    _host_fetch_save_persisted_state(force=force_save)


def _host_fetch_mutable_state(host: str) -> dict:
    _host_fetch_load_persisted_state()
    host_key = str(host or '').strip().lower()
    now = time.time()
    with _HOST_FETCH_GUARD:
        state = _HOST_FETCH_STATE.get(host_key)
        state = _host_fetch_normalize_state(state if isinstance(state, dict) else {}, now=now)
        _HOST_FETCH_STATE[host_key] = state
        return state


def _host_fetch_snapshot(host: str) -> dict:
    _host_fetch_load_persisted_state()
    host_key = str(host or '').strip().lower()
    with _HOST_FETCH_GUARD:
        return _host_fetch_normalize_state((_HOST_FETCH_STATE.get(host_key) or {}), now=time.time())


def _fetch_budget_cfg_int(primary: str, fallback: str, default: int) -> int:
    raw = app_getenv(primary, None)
    if raw in (None, ''):
        raw = app_getenv(fallback, str(default))
    try:
        return max(1, int(str(raw or default).strip()))
    except Exception:
        return int(default)


def _fetch_budget_cfg_float(primary: str, fallback: str, default: float) -> float:
    raw = app_getenv(primary, None)
    if raw in (None, ''):
        raw = app_getenv(fallback, str(default))
    try:
        return max(0.1, float(str(raw or default).strip()))
    except Exception:
        return float(default)


def _global_fetch_budget_limits(task_type: str = 'web_page') -> dict:
    task_key = str(task_type or 'web_page').strip().lower() or 'web_page'
    prefix = 'WEB_FETCH' if task_key == 'web_page' else 'REMOTE_IMAGE' if task_key == 'remote_image' else 'FETCH'
    task_global_limit = _fetch_budget_cfg_int(f'{prefix}_BUDGET_MAX_ACTIVE', 'FETCH_BUDGET_TOTAL_MAX_ACTIVE', 6 if task_key == 'web_page' else 4)
    host_limit = _fetch_budget_cfg_int(f'{prefix}_BUDGET_PER_HOST_MAX_ACTIVE', 'FETCH_BUDGET_PER_HOST_MAX_ACTIVE', 2 if task_key == 'web_page' else 1)
    total_limit = _fetch_budget_cfg_int('FETCH_BUDGET_TOTAL_MAX_ACTIVE', 'FETCH_BUDGET_TOTAL_MAX_ACTIVE', max(task_global_limit, 8))
    acquire_timeout = _fetch_budget_cfg_float(f'{prefix}_BUDGET_ACQUIRE_TIMEOUT', 'FETCH_BUDGET_ACQUIRE_TIMEOUT', 3.0 if task_key == 'web_page' else 2.0)
    return {'task_global_limit': max(1, task_global_limit), 'host_limit': max(1, host_limit), 'total_limit': max(1, total_limit), 'acquire_timeout': max(0.1, acquire_timeout)}


def _global_fetch_budget_acquire(url: str, task_type: str = 'web_page', timeout_s: float | None = None) -> dict:
    host = _fetch_host_key(url) or '__unknown__'
    task_key = str(task_type or 'web_page').strip().lower() or 'web_page'
    cfg = _global_fetch_budget_limits(task_key)
    deadline = time.time() + float(timeout_s if timeout_s is not None else cfg['acquire_timeout'])
    waited = 0.0
    wait_events = 0
    with _GLOBAL_FETCH_BUDGET_COND:
        _GLOBAL_FETCH_BUDGET_STATE['waiters'] = int(_GLOBAL_FETCH_BUDGET_STATE.get('waiters') or 0) + 1
        try:
            while True:
                task_active = int((_GLOBAL_FETCH_BUDGET_STATE.get('task_active') or {}).get(task_key, 0) or 0)
                host_active = int((_GLOBAL_FETCH_BUDGET_STATE.get('host_active') or {}).get((task_key, host), 0) or 0)
                active_total = int(_GLOBAL_FETCH_BUDGET_STATE.get('active_total') or 0)
                if active_total < int(cfg['total_limit']) and task_active < int(cfg['task_global_limit']) and host_active < int(cfg['host_limit']):
                    _GLOBAL_FETCH_BUDGET_STATE['active_total'] = active_total + 1
                    _GLOBAL_FETCH_BUDGET_STATE['peak_total'] = max(int(_GLOBAL_FETCH_BUDGET_STATE.get('peak_total') or 0), active_total + 1)
                    task_map = _GLOBAL_FETCH_BUDGET_STATE.setdefault('task_active', {})
                    task_map[task_key] = task_active + 1
                    host_map = _GLOBAL_FETCH_BUDGET_STATE.setdefault('host_active', {})
                    host_map[(task_key, host)] = host_active + 1
                    break
                remain = deadline - time.time()
                if remain <= 0:
                    _host_fetch_stats_bump(host, task_key, budget_timeouts=1, budget_wait_events=1 if wait_events or waited > 0 else 0, budget_wait_seconds=waited, last_error='fetch_budget_timeout')
                    raise HostFetchBudgetTimeout(host, task_key, waited)
                wait_start = time.time()
                wait_events += 1
                _GLOBAL_FETCH_BUDGET_COND.wait(timeout=min(remain, 0.25))
                waited += max(0.0, time.time() - wait_start)
        finally:
            _GLOBAL_FETCH_BUDGET_STATE['waiters'] = max(0, int(_GLOBAL_FETCH_BUDGET_STATE.get('waiters') or 0) - 1)
    if waited > 0 or wait_events > 0:
        _host_fetch_stats_bump(host, task_key, budget_wait_events=max(1, wait_events), budget_wait_seconds=waited)
    return {'host': host, 'task_type': task_key, 'waited_s': waited}


def _global_fetch_budget_release(ticket: dict | None) -> None:
    if not isinstance(ticket, dict):
        return
    host = str(ticket.get('host') or '').strip().lower() or '__unknown__'
    task_key = str(ticket.get('task_type') or 'web_page').strip().lower() or 'web_page'
    with _GLOBAL_FETCH_BUDGET_COND:
        _GLOBAL_FETCH_BUDGET_STATE['active_total'] = max(0, int(_GLOBAL_FETCH_BUDGET_STATE.get('active_total') or 0) - 1)
        task_map = _GLOBAL_FETCH_BUDGET_STATE.setdefault('task_active', {})
        if task_key in task_map:
            task_map[task_key] = max(0, int(task_map.get(task_key) or 0) - 1)
            if task_map[task_key] <= 0:
                task_map.pop(task_key, None)
        host_map = _GLOBAL_FETCH_BUDGET_STATE.setdefault('host_active', {})
        pair = (task_key, host)
        if pair in host_map:
            host_map[pair] = max(0, int(host_map.get(pair) or 0) - 1)
            if host_map[pair] <= 0:
                host_map.pop(pair, None)
        _GLOBAL_FETCH_BUDGET_COND.notify_all()

def _decide_host_fetch_strategy(url: str, task_type: str = 'web_page', allow_playwright: bool = True) -> dict:
    host = _fetch_host_key(url)
    out = {
        'host': host,
        'mode': 'direct',
        'skip_direct': False,
        'prefer_content_fallback': False,
        'allow_playwright': bool(allow_playwright),
        'prefer_playwright': False,
        'reason': 'direct',
        'wait_s': 0.0,
    }
    if not host:
        return out
    state = _host_fetch_snapshot(host)
    now = time.time()
    hard_fail_until = float(state.get('hard_fail_until') or 0.0)
    next_ok_at = float(state.get('next_ok_at') or 0.0)
    wait_s = max(0.0, max(hard_fail_until, next_ok_at) - now)
    out['wait_s'] = wait_s
    failures = int(state.get('failures') or 0)
    blocked_count = int(state.get('blocked_count') or 0)
    tls_failures = int(state.get('tls_failures') or 0)
    playwright_failures = int(state.get('playwright_failures') or 0)
    last_status = int(state.get('last_status') or 0)
    strategy_hint = str(state.get('strategy_hint') or '').strip().lower()
    last_success_method = str(state.get('last_success_method') or '').strip().lower()
    bare_host = host.split(':', 1)[0].lower().strip('.')

    if hard_fail_until > now:
        out.update({
            'mode': 'cooldown_skip',
            'skip_direct': True,
            'prefer_content_fallback': task_type == 'web_page',
            'allow_playwright': False,
            'reason': str(state.get('last_error') or 'hard_fail')[:160] or 'hard_fail',
        })
        _host_fetch_stats_bump(host, task_type, cooldown_skips=1, provider_only=1 if task_type == 'web_page' else 0, last_error=str(out.get('reason') or 'hard_fail'))
        return out

    if task_type == 'remote_image':
        if _is_gated_remote_image_host(bare_host):
            out.update({'mode': 'skip_direct', 'skip_direct': True, 'allow_playwright': False, 'reason': 'gated_remote_image_host'})
            _host_fetch_stats_bump(host, task_type, cooldown_skips=1, last_error='gated_remote_image_host')
            return out
        if _is_playwright_unfriendly_remote_image_host(bare_host) or playwright_failures >= 2:
            out['allow_playwright'] = False
        if strategy_hint == 'provider_only' or (blocked_count >= 2 and failures >= 3 and last_status in (401, 403, 404, 410, 429, 503)):
            out.update({'mode': 'skip_direct', 'skip_direct': True, 'allow_playwright': False, 'reason': 'blocked_remote_image_host'})
            _host_fetch_stats_bump(host, task_type, cooldown_skips=1, last_error='blocked_remote_image_host')
            return out
        return out

    if strategy_hint in {'provider_only', 'provider_first'}:
        out.update({'mode': 'provider_first', 'prefer_content_fallback': True, 'reason': strategy_hint})
        _host_fetch_stats_bump(host, task_type, provider_only=1, last_error=str(strategy_hint or 'provider_first'))
    elif tls_failures >= 2 or (blocked_count >= 2 and failures >= 3):
        out.update({'mode': 'provider_first', 'prefer_content_fallback': True, 'reason': 'repeated_host_blocks'})
    elif next_ok_at > now and failures >= 2:
        out.update({'mode': 'provider_first', 'prefer_content_fallback': True, 'reason': 'host_cooling'})

    if blocked_count >= 3 and last_status in (401, 403, 429, 503):
        out['allow_playwright'] = False
    if last_success_method == 'playwright' and out['allow_playwright'] and not out['prefer_content_fallback']:
        out['prefer_playwright'] = True
    return out


def _fetch_host_key(url: str) -> str:
    try:
        p = urlparse(str(url or '').strip())
        host = (p.hostname or '').lower().strip()
        if not host:
            return ''
        port = p.port
        return f'{host}:{port}' if port else host
    except Exception:
        return ''

def _retry_after_seconds(headers: dict | None) -> float | None:
    try:
        if not headers:
            return None
        raw = None
        for k, v in headers.items():
            if str(k).lower() == 'retry-after':
                raw = str(v or '').strip()
                break
        if not raw:
            return None
        if raw.isdigit():
            return float(raw)
        dt = email.utils.parsedate_to_datetime(raw)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        return max(0.0, (dt - now).total_seconds())
    except Exception:
        return None

class HostFetchCooldownSkip(RuntimeError):
    def __init__(self, host: str, wait_s: float, reason: str = ''):
        super().__init__(f'host_cooldown_skip:{host}:{wait_s:.2f}:{reason or "throttle"}')
        self.host = host
        self.wait_s = float(wait_s)
        self.reason = reason or 'throttle'


def _remote_image_exception_chain_messages(exc: Exception) -> list[str]:
    msgs = []
    seen = set()
    cur = exc
    while cur is not None:
        msg = f'{type(cur).__name__}: {cur}'
        if msg not in seen:
            seen.add(msg)
            msgs.append(msg)
        cur = getattr(cur, '__cause__', None) or getattr(cur, '__context__', None)
    return msgs


def _is_tls_cert_verification_error(exc: Exception) -> bool:
    blob = ' | '.join(_remote_image_exception_chain_messages(exc)).lower()
    if not blob:
        return False
    markers = [
        'sslcertverificationerror',
        'certificate verify failed',
        'certificateverifyfailed',
        'self-signed certificate',
        'hostname mismatch',
        'tlsv1 alert',
        'unable to get local issuer certificate',
    ]
    return any(m in blob for m in markers)


def _host_fetch_mark_hard_fail(url: str, cooldown_s: float | None = None, reason: str = '', error: str = ''):
    host = _fetch_host_key(url)
    if not host:
        return
    now = time.time()
    cooldown = float(cooldown_s if cooldown_s is not None else (app_getenv('REMOTE_IMAGE_TLS_CERT_FAIL_COOLDOWN', '1800') or 1800))
    cooldown = max(30.0, cooldown)
    cooldown += random.uniform(0.2, min(3.0, cooldown * 0.05))
    state = _host_fetch_mutable_state(host)
    failures = int(state.get('failures', 0) or 0) + 1
    until = now + cooldown
    state['failures'] = failures
    state['blocked_count'] = int(state.get('blocked_count', 0) or 0) + 1
    state['hard_fail_until'] = max(float(state.get('hard_fail_until', 0.0) or 0.0), until)
    state['next_ok_at'] = max(float(state.get('next_ok_at', 0.0) or 0.0), until)
    state['strategy_hint'] = 'provider_only'
    state['last_error'] = str(reason or error or 'hard_fail')[:160]
    state['updated_at'] = now
    _host_fetch_mark_dirty(force_save=True)
    app_logger.warning('[host_fetch] hard-block %.1fs host=%s failures=%s reason=%s error=%s', cooldown, host, failures, reason or 'hard_fail', error or '')


def _remote_image_host_score_adjust(url: str) -> float:
    host = _fetch_host_key(url)
    if not host:
        return 0.0
    bare_host = str(host).split(':', 1)[0].lower().strip('.')
    base_penalty = 0.0
    if _is_gated_remote_image_host(bare_host):
        base_penalty = -3.0
    elif _is_playwright_unfriendly_remote_image_host(bare_host):
        base_penalty = -0.85
    now = time.time()
    state = _host_fetch_snapshot(host)
    hard_fail_until = float(state.get('hard_fail_until', 0.0) or 0.0)
    next_ok_at = float(state.get('next_ok_at', 0.0) or 0.0)
    failures = int(state.get('failures', 0) or 0)
    if hard_fail_until > now:
        dyn = -min(2.8, 1.4 + max(0, failures - 1) * 0.35)
        return min(base_penalty, dyn)
    if next_ok_at > now and failures > 0:
        dyn = -min(1.4, 0.5 + max(0, failures - 1) * 0.2)
        return min(base_penalty, dyn)
    return base_penalty


def _host_fetch_wait(url: str, reason: str = ''):
    host = _fetch_host_key(url)
    if not host:
        return
    min_gap = max(0.0, float(app_getenv('WEB_FETCH_HOST_MIN_INTERVAL', '0.8') or 0.8))
    max_wait = max(0.0, float(app_getenv('WEB_FETCH_HOST_MAX_WAIT', '2.5') or 2.5))
    now = time.time()
    wait_s = 0.0
    state = _host_fetch_mutable_state(host)
    hard_fail_until = float(state.get('hard_fail_until', 0.0) or 0.0)
    if hard_fail_until > now:
        wait_left = max(0.0, hard_fail_until - now)
        _host_fetch_stats_bump(host, 'remote_image' if str(reason or '').startswith('remote_image') else 'web_page', cooldown_skips=1, wait_events=1, wait_seconds=wait_left, last_error=str(state.get('last_error') or reason or 'hard_fail'))
        raise HostFetchCooldownSkip(host, wait_left, str(state.get('last_error') or reason or 'hard_fail'))
    next_ok_at = float(state.get('next_ok_at', 0.0) or 0.0)
    last_req_at = float(state.get('last_req_at', 0.0) or 0.0)
    wait_s = max(0.0, next_ok_at - now, (last_req_at + min_gap) - now)
    if wait_s > max_wait:
        softened_wait = max(0.05, max_wait * 0.5)
        app_logger.warning('[host_fetch] soften %.2fs->%.2fs host=%s reason=%s max_wait=%.2fs', wait_s, softened_wait, host, reason or 'throttle', max_wait)
        wait_s = softened_wait
    reserve_at = max(now + wait_s, last_req_at)
    state['last_req_at'] = reserve_at
    state['updated_at'] = now
    if wait_s > 0:
        _host_fetch_stats_bump(host, 'remote_image' if str(reason or '').startswith('remote_image') else 'web_page', wait_events=1, wait_seconds=wait_s)
    if wait_s > 0.02:
        app_logger.info('[host_fetch] wait %.2fs host=%s reason=%s', wait_s, host, reason or 'throttle')
        time.sleep(wait_s)


def _host_fetch_record(url: str, status_code: int = 0, headers: dict | None = None, error: str | None = None, method: str = '', task_type: str = ''):
    host = _fetch_host_key(url)
    if not host:
        return
    now = time.time()
    base_cd = max(5.0, float(app_getenv('WEB_FETCH_HOST_FAILURE_COOLDOWN', '90') or 90))
    max_cd = max(base_cd, float(app_getenv('WEB_FETCH_HOST_MAX_COOLDOWN', '600') or 600))
    method = str(method or '').strip().lower()
    task_type = str(task_type or '').strip().lower()
    state = _host_fetch_mutable_state(host)
    failures = int(state.get('failures', 0) or 0)
    blocked = int(status_code or 0) in (401, 403, 406, 409, 423, 425, 429, 500, 502, 503, 504)
    transient_error = bool(error)
    state['last_status'] = int(status_code or 0)
    state['updated_at'] = now
    _host_fetch_stats_bump(host, task_type or 'web_page', requests=1, last_status=int(status_code or 0), last_error=str(error or '')[:160])
    if status_code and 200 <= int(status_code) < 400 and not transient_error:
        state['successes'] = int(state.get('successes', 0) or 0) + 1
        state['failures'] = 0
        state['next_ok_at'] = now
        state['last_req_at'] = now
        state['last_success_at'] = now
        state['hard_fail_until'] = 0.0
        state['last_success_method'] = method[:80]
        state['last_error'] = ''
        state['blocked_count'] = max(0, int(state.get('blocked_count', 0) or 0) - 1)
        state['tls_failures'] = max(0, int(state.get('tls_failures', 0) or 0) - 1)
        if method in {'httpx', 'curl', 'requests', 'playwright'}:
            state['strategy_hint'] = ''
        elif method in {'jina', 'tavily'} and int(state.get('blocked_count', 0) or 0) >= 1:
            state['strategy_hint'] = 'provider_first'
        _host_fetch_stats_bump(host, task_type or 'web_page', successes=1, playwright_successes=1 if method == 'playwright' else 0, last_status=int(status_code or 0))
        _host_fetch_mark_dirty(force_save=False)
        return
    if blocked or transient_error:
        failures += 1
        state['failures'] = failures
        if blocked:
            state['blocked_count'] = int(state.get('blocked_count', 0) or 0) + 1
        err_l = str(error or '').lower()
        if any(token in err_l for token in ('tls', 'ssl', 'cert')):
            state['tls_failures'] = int(state.get('tls_failures', 0) or 0) + 1
        if 'playwright' in method or 'playwright' in err_l:
            state['playwright_failures'] = int(state.get('playwright_failures', 0) or 0) + 1
        if 'empty' in err_l or 'no response' in err_l:
            state['empty_count'] = int(state.get('empty_count', 0) or 0) + 1
        retry_after = _retry_after_seconds(headers)
        if retry_after is None:
            retry_after = min(max_cd, base_cd * (2 ** max(0, failures - 1)))
        retry_after = min(max_cd, max(1.0, float(retry_after)))
        retry_after += random.uniform(0.1, min(1.5, retry_after * 0.15))
        state['next_ok_at'] = max(float(state.get('next_ok_at', 0.0) or 0.0), now + retry_after)
        state['last_error'] = str(error or f'status:{status_code}' or 'fetch_error')[:160]
        if task_type == 'remote_image' and int(state.get('blocked_count', 0) or 0) >= 2 and failures >= 3:
            state['strategy_hint'] = 'provider_only'
        elif int(state.get('tls_failures', 0) or 0) >= 2 or (int(state.get('blocked_count', 0) or 0) >= 2 and failures >= 3):
            state['strategy_hint'] = 'provider_first'
        _host_fetch_stats_bump(host, task_type or 'web_page', failures=1, blocked=1 if blocked else 0, tls_failures=1 if any(token in err_l for token in ('tls', 'ssl', 'cert')) else 0, playwright_failures=1 if ('playwright' in method or 'playwright' in err_l) else 0, empty=1 if ('empty' in err_l or 'no response' in err_l) else 0, last_status=int(status_code or 0), last_error=str(error or f'status:{status_code}' or 'fetch_error')[:160])
        _host_fetch_mark_dirty(force_save=blocked and failures >= 2)
        app_logger.warning('[host_fetch] cooldown %.1fs host=%s status=%s failures=%s error=%s', retry_after, host, status_code, failures, error or '')


def _remote_image_cache_dir() -> str:
    d = str(app_getenv('REMOTE_IMAGE_CACHE_DIR', REMOTE_IMAGE_CACHE_DIR_DEFAULT) or '').strip()
    if not d:
        d = os.path.join(os.path.expanduser('~'), 'remote_image_cache')
    os.makedirs(d, exist_ok=True)
    return d

def _remote_image_cache_key(url: str) -> str:
    return hashlib.sha256(str(url or '').strip().encode('utf-8', 'ignore')).hexdigest()

def _remote_image_lock_for(key: str) -> threading.Lock:
    with _REMOTE_IMAGE_LOCKS_GUARD:
        lock = _REMOTE_IMAGE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _REMOTE_IMAGE_LOCKS[key] = lock
        return lock

def _remote_image_host_lock_for(url: str):
    host = _fetch_host_key(url)
    if not host:
        return None
    limit = max(1, min(int(app_getenv('REMOTE_IMAGE_PER_HOST_CONCURRENCY', '1') or 1), 6))
    with _REMOTE_IMAGE_HOST_LOCKS_GUARD:
        lock = _REMOTE_IMAGE_HOST_LOCKS.get(host)
        if lock is None:
            lock = threading.Semaphore(limit)
            _REMOTE_IMAGE_HOST_LOCKS[host] = lock
        return lock

def _remote_image_failed_recently(url: str) -> bool:
    ttl = max(0, int(app_getenv('REMOTE_IMAGE_FAIL_TTL', '60') or 60))
    if ttl <= 0:
        return False
    now = time.time()
    key = _remote_image_cache_key(url)
    with _REMOTE_IMAGE_FAIL_LOCK:
        ts = float(_REMOTE_IMAGE_FAIL_CACHE.get(key, 0.0) or 0.0)
        if not ts:
            return False
        age = now - ts
        if age >= ttl:
            _REMOTE_IMAGE_FAIL_CACHE.pop(key, None)
            return False
        remaining = max(0.0, ttl - age)
        retry_ratio = min(0.75, max(0.15, 1.0 - (remaining / max(1.0, float(ttl)))))
        if random.random() < retry_ratio:
            app_logger.info('[remote_image_cache] soft-retry age=%.1fs ttl=%ss ratio=%.2f url=%s', age, ttl, retry_ratio, url)
            return False
        return True

def _remote_image_mark_failed(url: str):
    key = _remote_image_cache_key(url)
    with _REMOTE_IMAGE_FAIL_LOCK:
        _REMOTE_IMAGE_FAIL_CACHE[key] = time.time()
    return None

def _guess_image_ext_from_url_and_type(url: str, content_type: str) -> str:
    ct = str(content_type or '').split(';', 1)[0].strip().lower()
    if ct == 'image/jpeg':
        return '.jpg'
    if ct == 'image/png':
        return '.png'
    if ct == 'image/webp':
        return '.webp'
    if ct == 'image/gif':
        return '.gif'
    if ct == 'image/bmp':
        return '.bmp'
    if ct == 'image/svg+xml':
        return '.svg'
    if ct in ('image/heic', 'image/heic-sequence'):
        return '.heic'
    if ct in ('image/heif', 'image/heif-sequence'):
        return '.heif'
    path = urlparse(str(url or '')).path.lower()
    for ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.svg', '.heic', '.heif'):
        if path.endswith(ext):
            return '.jpg' if ext == '.jpeg' else ext
    return '.img'

def _remote_image_cache_candidates(url: str) -> list[str]:
    key = _remote_image_cache_key(url)
    root = _remote_image_cache_dir()
    out = []
    try:
        for name in os.listdir(root):
            if name.startswith(key + '.'):
                out.append(os.path.join(root, name))
    except Exception:
        pass
    return out

def _prune_remote_image_cache():
    root = _remote_image_cache_dir()
    ttl = int(app_getenv('REMOTE_IMAGE_CACHE_TTL', str(7 * 24 * 3600)) or (7 * 24 * 3600))
    max_bytes = int(app_getenv('REMOTE_IMAGE_CACHE_MAX_BYTES', str(256 * 1024 * 1024)) or (256 * 1024 * 1024))
    now = time.time()
    files = []
    total = 0
    try:
        for name in os.listdir(root):
            fp = os.path.join(root, name)
            try:
                st = os.stat(fp)
            except Exception:
                continue
            if not os.path.isfile(fp):
                continue
            age = now - st.st_mtime
            if ttl > 0 and age > ttl:
                try:
                    os.remove(fp)
                except Exception:
                    pass
                continue
            total += int(st.st_size)
            files.append((fp, st.st_mtime, int(st.st_size)))
    except Exception:
        return
    if max_bytes <= 0 or total <= max_bytes:
        return
    files.sort(key=lambda x: x[1])
    for fp, _mt, sz in files:
        if total <= max_bytes:
            break
        try:
            os.remove(fp)
            total -= sz
        except Exception:
            pass

def _read_remote_image_cache(url: str) -> tuple[bytes, str] | None:
    cands = _remote_image_cache_candidates(url)
    if not cands:
        return None
    best = None
    best_mt = -1.0
    for fp in cands:
        try:
            st = os.stat(fp)
            if st.st_mtime > best_mt:
                best = fp
                best_mt = st.st_mtime
        except Exception:
            continue
    if not best:
        return None
    ttl = int(app_getenv('REMOTE_IMAGE_CACHE_TTL', str(7 * 24 * 3600)) or (7 * 24 * 3600))
    try:
        st = os.stat(best)
        if ttl > 0 and time.time() - st.st_mtime > ttl:
            try:
                os.remove(best)
            except Exception:
                pass
            return None
        with open(best, 'rb') as f:
            raw = f.read()
        ext = os.path.splitext(best)[1].lower()
        mime = {'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.webp':'image/webp','.gif':'image/gif','.bmp':'image/bmp','.svg':'image/svg+xml','.heic':'image/heic','.heif':'image/heif'}.get(ext, 'application/octet-stream')
        try:
            if mime == 'image/webp' or mime == 'application/octet-stream' or not _raw_bytes_match_declared_image_mime(raw, mime):
                raw, mime = _coerce_image_bytes_for_model(raw, mime)
        except Exception as e:
            app_logger.warning('[remote_image_cache] purge-bad-image %s :: %s: %s', best, type(e).__name__, e)
            try:
                os.remove(best)
            except Exception:
                pass
            return None
        try:
            os.utime(best, None)
        except Exception:
            pass
        return raw, mime
    except Exception:
        return None

def _write_remote_image_cache(url: str, raw: bytes, content_type: str) -> tuple[str, str]:
    key = _remote_image_cache_key(url)
    ext = _guess_image_ext_from_url_and_type(url, content_type)
    mime = str(content_type or '').split(';', 1)[0].strip().lower() or {'.jpg':'image/jpeg','.png':'image/png','.webp':'image/webp','.gif':'image/gif','.bmp':'image/bmp','.svg':'image/svg+xml'}.get(ext, 'application/octet-stream')
    path = os.path.join(_remote_image_cache_dir(), key + ext)
    tmp = path + '.tmp-' + uuid.uuid4().hex
    with open(tmp, 'wb') as f:
        f.write(raw)
    os.replace(tmp, path)
    try:
        _prune_remote_image_cache()
    except Exception:
        pass
    return path, mime

def _is_douyin_image_host(host: str) -> bool:
    h = str(host or '').lower()
    return (
        h.endswith('douyinpic.com')
        or h.endswith('amemv.com')
        or h.endswith('byteimg.com')
        or h.endswith('douyinvod.com')
        or h.endswith('ibyteimg.com')
        or h.endswith('zijieapi.com')
        or 'douyin' in h
        or 'byte' in h
    )


def _is_gated_remote_image_host(host: str) -> bool:
    h = str(host or '').lower().strip('.')
    if not h:
        return False
    blocked = (
        'lookaside.fbsbx.com', 'fbsbx.com', 'fbcdn.net', 'facebook.com', 'messenger.com',
        'instagram.com', 'cdninstagram.com', 'whatsapp.net', 'whatsapp.com'
    )
    return any(h == d or h.endswith('.' + d) for d in blocked)


def _is_playwright_unfriendly_remote_image_host(host: str) -> bool:
    h = str(host or '').lower().strip('.')
    if not h:
        return False
    blocked = (
        'pbs.twimg.com', 'twimg.com', 'p3-pc-sign.douyinpic.com'
    )
    return any(h == d or h.endswith('.' + d) for d in blocked)


def _should_skip_playwright_remote_image_fallback(url: str, exc: Exception | None = None) -> bool:
    host = (_fetch_host_key(url) or '').split(':', 1)[0].lower().strip('.')
    if _is_gated_remote_image_host(host):
        return True
    msg = str(exc or '').lower()
    if 'unsupported_image_content_type:text/html' in msg:
        return True
    if _is_playwright_unfriendly_remote_image_host(host):
        status = 0
        resp = getattr(exc, 'response', None)
        try:
            status = int(getattr(resp, 'status_code', 0) or 0)
        except Exception:
            status = 0
        if status in (401, 403, 404, 410, 429):
            return True
        if 'unsupported_image_content_type' in msg or 'empty_remote_image' in msg:
            return True
    return False


def _should_bypass_remote_image_proxy(url: str) -> bool:
    """远程图片默认都走服务端代理。

    早先抖音/字节系图片会直接让前端直连，但这类图片经常有防盗链，
    浏览器 302 到原图后反而更容易加载失败。这里统一返回 False，
    让调用链尽量优先走 /api3/remote-image，提高稳定性。
    """
    return False


def _same_origin_local_path_from_url(url: str) -> str | None:
    """Map same-origin local upload/proxy URLs back to filesystem paths when possible."""
    try:
        u = str(url or '').strip()
        if not u:
            return None
        parsed = urlparse(u)
        path = parsed.path or ''
        if not path:
            return None
        if not (u.startswith('/') or parsed.scheme in ('http', 'https')):
            return None
        if path.startswith('/api3/uploads/') or path.startswith('/api3/download/'):
            name = os.path.basename(path)
            try:
                name = urllib.parse.unquote(name)
            except Exception:
                pass
            if not name:
                return None
            base_dir = _resolve_uploaded_file_dir(name)
            if not base_dir:
                return None
            fp = os.path.join(base_dir, name)
            return fp if os.path.isfile(fp) else None
        if path.startswith('/api3/generated-files/') or path.startswith('/api3/generated-download/'):
            name = os.path.basename(path)
            try:
                name = urllib.parse.unquote(name)
            except Exception:
                pass
            if not name:
                return None
            scope = ''
            try:
                extractor = globals().get('_extract_upload_scope_from_url')
                if callable(extractor):
                    scope = str(extractor(u) or '').strip()
            except Exception:
                scope = ''
            candidates = []
            for candidate in (scope, UPLOAD_SCOPE_LOCAL, UPLOAD_SCOPE_PUBLIC):
                candidate = str(candidate or '').strip()
                if candidate and candidate not in candidates:
                    candidates.append(candidate)
            for candidate in candidates:
                try:
                    base_dir = _generated_dir_for_scope(candidate, ensure=False)
                    fp = os.path.join(base_dir, name)
                    if os.path.isfile(fp):
                        return fp
                except Exception:
                    continue
            return None
        return None
    except Exception:
        return None


def _local_image_file_to_data_url(path: str) -> str | None:
    try:
        fp = str(path or '').strip()
        if not fp or not os.path.isfile(fp):
            return None
        with open(fp, 'rb') as f:
            raw = f.read()
        if not raw:
            return None
        ext = os.path.splitext(fp)[1].lower()
        mime = {'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.webp':'image/webp','.gif':'image/gif','.bmp':'image/bmp','.svg':'image/svg+xml'}.get(ext, 'application/octet-stream')
        raw, mime = _coerce_image_bytes_for_model(raw, mime)
        return f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
    except Exception:
        return None


def _normalize_image_input_to_data_url(url: str) -> str | None:
    """Accept data URLs, same-origin upload URLs, proxy URLs, and remote URLs; return a model-safe data URL."""
    u = str(url or '').strip()
    if not u:
        return None
    if u.startswith('data:image/'):
        if 'base64,' not in u:
            return None
        try:
            header, b64 = u.split('base64,', 1)
            mime = header.split(';', 1)[0].replace('data:', '').strip() or 'application/octet-stream'
            raw = base64.b64decode((b64 or '').strip(), validate=False)
            if not raw:
                return None
            raw, mime = _coerce_image_bytes_for_model(raw, mime)
            return f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
        except Exception:
            return None
    local_fp = _same_origin_local_path_from_url(u)
    if local_fp:
        return _local_image_file_to_data_url(local_fp)
    try:
        has_scheme = bool(re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', u))
    except Exception:
        has_scheme = False
    if u and not has_scheme and not u.startswith('/'):
        try:
            getter = globals().get('_file_library_get_record')
            resolver = globals().get('_file_library_resolve_local_path')
            category_fn = globals().get('_file_library_category')
            if callable(getter) and callable(resolver):
                rec = getter(u) or {}
                if isinstance(rec, dict) and rec:
                    local_path = str(resolver(rec) or '').strip()
                    ext = str(_ext_of(rec.get('filename') or rec.get('saved_filename') or local_path or '') or '').strip().lower()
                    category = str(category_fn(rec.get('filename') or rec.get('saved_filename') or local_path or '', ext) if callable(category_fn) else '').strip().lower()
                    if local_path and os.path.isfile(local_path) and (category == 'image' or ext in UPLOAD_IMAGE_EXTS):
                        return _local_image_file_to_data_url(local_path)
        except Exception:
            pass
    try:
        parsed = urlparse(u)
        path = parsed.path or ''
        if path in ('/api3/remote-image', '/api3/image_proxy'):
            raw_q = parse_qs(parsed.query or '', keep_blank_values=True)
            src = ''
            vals = raw_q.get('url') or []
            if vals:
                src = str(vals[0] or '').strip()
            if src:
                return _remote_image_to_data_url(src)
    except Exception:
        pass
    if u.startswith('http://') or u.startswith('https://'):
        return _remote_image_to_data_url(u)
    return None



def _heif_image_mimes() -> set[str]:
    return {'image/heic', 'image/heif', 'image/heic-sequence', 'image/heif-sequence'}


def _image_mime_is_heif(mime: str = '') -> bool:
    return str(mime or '').split(';', 1)[0].strip().lower() in _heif_image_mimes()


def _detect_heif_mime_from_bytes(raw: bytes) -> str:
    if not raw or len(raw) < 12:
        return ''
    probe = bytes(raw[:128] or b'')
    if probe[4:8].lower() != b'ftyp':
        return ''
    brands = probe[8:96].lower()
    if any(brand in brands for brand in (b'heic', b'heix', b'hevc', b'hevx', b'heis', b'heim', b'hevm', b'hevs')):
        return 'image/heic'
    if any(brand in brands for brand in (b'mif1', b'msf1')):
        return 'image/heif'
    return ''


def _looks_like_heif_bytes(raw: bytes) -> bool:
    return bool(_detect_heif_mime_from_bytes(raw))


def _register_pillow_heif_opener_if_available() -> bool:
    if getattr(_register_pillow_heif_opener_if_available, '_done', False):
        return bool(getattr(_register_pillow_heif_opener_if_available, '_ok', False))
    ok = False
    try:
        pillow_heif = __import__('pillow_heif')
        register = getattr(pillow_heif, 'register_heif_opener', None)
        if callable(register):
            register()
            ok = True
    except Exception:
        ok = False
    try:
        setattr(_register_pillow_heif_opener_if_available, '_done', True)
        setattr(_register_pillow_heif_opener_if_available, '_ok', ok)
    except Exception:
        pass
    return ok


def _coerce_heif_bytes_with_system_tool(raw: bytes) -> tuple[bytes, str] | None:
    if not raw:
        return None
    try:
        tempfile_mod = globals().get('tempfile') or __import__('tempfile')
        os_mod = globals().get('os') or __import__('os')
        subprocess_mod = globals().get('subprocess') or __import__('subprocess')
        shutil_mod = globals().get('shutil') or __import__('shutil')
    except Exception:
        return None
    tmpdir = None
    try:
        tmpdir = tempfile_mod.mkdtemp(prefix='webai_heif_')
        src = os_mod.path.join(tmpdir, 'input.heic')
        dst = os_mod.path.join(tmpdir, 'output.jpg')
        with open(src, 'wb') as f:
            f.write(raw)
        commands = []
        if shutil_mod.which('magick'):
            commands.append(['magick', src, dst])
        if shutil_mod.which('heif-convert'):
            commands.append(['heif-convert', src, dst])
        if shutil_mod.which('ffmpeg'):
            commands.append(['ffmpeg', '-y', '-loglevel', 'error', '-i', src, '-frames:v', '1', dst])
        if shutil_mod.which('convert'):
            commands.append(['convert', src, dst])
        for cmd in commands:
            try:
                subprocess_mod.run(cmd, stdout=subprocess_mod.DEVNULL, stderr=subprocess_mod.DEVNULL, timeout=20, check=False)
                if os_mod.path.isfile(dst) and os_mod.path.getsize(dst) > 0:
                    with open(dst, 'rb') as f:
                        out = f.read()
                    if out:
                        return out, 'image/jpeg'
            except Exception:
                continue
    finally:
        try:
            if tmpdir:
                shutil_mod.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
    return None

def _looks_like_image_bytes(raw: bytes) -> bool:
    if not raw:
        return False
    probe = bytes(raw[:128] or b'')
    probe_l = probe.lstrip().lower()
    return (
        probe.startswith(b'\xff\xd8\xff')
        or probe.startswith(b'\x89PNG\r\n\x1a\n')
        or (probe.startswith(b'RIFF') and probe[8:12] == b'WEBP')
        or probe.startswith((b'GIF87a', b'GIF89a'))
        or probe.startswith(b'BM')
        or probe.startswith((b'II*\x00', b'MM\x00*'))
        or _looks_like_heif_bytes(raw)
        or probe_l.startswith(b'<svg')
        or (probe_l.startswith(b'<?xml') and b'<svg' in probe_l)
    )



def _detect_image_mime_from_bytes(raw: bytes) -> str:
    if not raw:
        return ''
    probe = bytes(raw[:4096] or b'')
    probe_l = probe.lstrip().lower()
    if probe.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if probe.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if len(probe) >= 12 and probe.startswith(b'RIFF') and probe[8:12] == b'WEBP':
        return 'image/webp'
    if probe.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if probe.startswith(b'BM'):
        return 'image/bmp'
    if probe.startswith((b'II*\x00', b'MM\x00*')):
        return 'image/tiff'
    heif_mime = _detect_heif_mime_from_bytes(raw)
    if heif_mime:
        return heif_mime
    if probe_l.startswith(b'<svg') or (probe_l.startswith(b'<?xml') and b'<svg' in probe_l):
        return 'image/svg+xml'
    try:
        from PIL import Image  # type: ignore
        with Image.open(io.BytesIO(raw)) as opened:
            fmt = str(getattr(opened, 'format', '') or '').strip().upper()
        return {
            'JPEG': 'image/jpeg',
            'PNG': 'image/png',
            'WEBP': 'image/webp',
            'GIF': 'image/gif',
            'BMP': 'image/bmp',
            'TIFF': 'image/tiff',
            'ICO': 'image/x-icon',
            'HEIF': 'image/heif',
            'HEIC': 'image/heic',
        }.get(fmt, '')
    except Exception:
        return ''


def _is_valid_webp_riff_bytes(raw: bytes) -> bool:
    probe = bytes(raw[:64] or b'')
    return len(probe) >= 12 and probe.startswith(b'RIFF') and probe[8:12] == b'WEBP'


def _raw_bytes_match_declared_image_mime(raw: bytes, mime: str) -> bool:
    mime_l = str(mime or '').split(';', 1)[0].strip().lower()
    if not raw or not mime_l:
        return False
    probe = bytes(raw[:4096] or b'')
    probe_l = probe.lstrip().lower()
    if mime_l == 'image/jpeg':
        return probe.startswith(b'\xff\xd8\xff')
    if mime_l == 'image/png':
        return probe.startswith(b'\x89PNG\r\n\x1a\n')
    if mime_l == 'image/webp':
        return _is_valid_webp_riff_bytes(raw)
    if mime_l == 'image/gif':
        return probe.startswith((b'GIF87a', b'GIF89a'))
    if mime_l == 'image/bmp':
        return probe.startswith(b'BM')
    if mime_l == 'image/tiff':
        return probe.startswith((b'II*\x00', b'MM\x00*'))
    if _image_mime_is_heif(mime_l):
        return _looks_like_heif_bytes(raw)
    if mime_l == 'image/svg+xml':
        return probe_l.startswith(b'<svg') or (probe_l.startswith(b'<?xml') and b'<svg' in probe_l)
    return False


def _prefer_png_for_textlike_image(img, *, source_mime: str = '', detected_mime: str = '') -> bool:
    source_mime = str(source_mime or '').split(';', 1)[0].strip().lower()
    detected_mime = str(detected_mime or '').split(';', 1)[0].strip().lower()
    mode = str(getattr(img, 'mode', '') or '').upper()
    if mode == 'L':
        return True
    if source_mime in {'image/gif', 'image/bmp', 'image/tiff', 'image/x-icon'} or detected_mime in {'image/gif', 'image/bmp', 'image/tiff', 'image/x-icon'}:
        return True
    try:
        w, h = img.size
    except Exception:
        return False
    pixel_count = max(1, int(w or 0) * int(h or 0))
    color_count = None
    if pixel_count <= 6_000_000:
        try:
            probe = img.convert('RGB') if mode != 'RGB' else img
            color_count = probe.getcolors(1024)
            if color_count is not None:
                color_count = len(color_count)
        except Exception:
            color_count = None
    if color_count is not None and color_count <= 256:
        return True
    if source_mime == 'image/png' and color_count is not None and color_count <= 768:
        return True
    return False


def _coerce_image_bytes_for_model(raw: bytes, mime: str) -> tuple[bytes, str]:
    """Normalize arbitrary image bytes into a model-safe payload.

    - Keep SVG as-is when it looks valid.
    - Raster images are decoded with Pillow when available, animated images use the
      first frame, alpha is flattened onto white, very large images are scaled down,
      and screenshot / text-like images prefer lossless PNG to avoid text smearing.
    - Corrupted WebP payloads are rejected locally instead of being passed through to
      the model API.
    - If Pillow is unavailable or decoding fails for non-WebP formats, fall back to
      the original bytes so callers can still decide what to do.
    """
    if not raw:
        raise ValueError('empty_image')

    mime = str(mime or '').split(';', 1)[0].strip().lower()
    detected_mime = _detect_image_mime_from_bytes(raw)
    heif_input = _image_mime_is_heif(mime) or _image_mime_is_heif(detected_mime) or _looks_like_heif_bytes(raw)
    if heif_input and not detected_mime:
        detected_mime = _detect_heif_mime_from_bytes(raw) or 'image/heic'
    if detected_mime and detected_mime != mime:
        if mime == 'image/webp' and detected_mime in {'image/jpeg', 'image/png', 'image/gif', 'image/bmp', 'image/tiff', 'image/x-icon', 'image/svg+xml', 'image/heic', 'image/heif'}:
            mime = detected_mime
        elif not mime or mime == 'application/octet-stream':
            mime = detected_mime
    if mime == 'image/svg+xml':
        probe = bytes(raw[:2048] or b'').lstrip().lower()
        if probe.startswith(b'<svg') or (probe.startswith(b'<?xml') and b'<svg' in probe):
            return raw, 'image/svg+xml'
    if mime == 'image/webp' and not _is_valid_webp_riff_bytes(raw):
        raise ValueError('invalid_webp_riff_header')

    try:
        from PIL import Image, ImageOps  # type: ignore
        if heif_input:
            _register_pillow_heif_opener_if_available()
    except Exception:
        if mime == 'image/webp':
            raise ValueError('webp_decode_unavailable')
        if heif_input:
            converted = _coerce_heif_bytes_with_system_tool(raw)
            if converted:
                return converted
            raise ValueError('heif_decode_unavailable')
        return raw, (mime or detected_mime or 'application/octet-stream')

    try:
        with Image.open(io.BytesIO(raw)) as opened:
            try:
                if getattr(opened, 'is_animated', False):
                    opened.seek(0)
            except Exception:
                pass

            img = ImageOps.exif_transpose(opened)
            try:
                img.load()
            except Exception:
                pass

            bands = tuple(img.getbands() or ())
            has_alpha = 'A' in bands
            if has_alpha:
                bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
                bg.alpha_composite(img.convert('RGBA'))
                img = bg.convert('RGB')
            elif img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')

            max_side = 2048
            if max(img.size or (0, 0)) > max_side:
                resample = getattr(Image, 'Resampling', Image).LANCZOS
                img.thumbnail((max_side, max_side), resample)

            prefer_png = _prefer_png_for_textlike_image(img, source_mime=mime, detected_mime=detected_mime)
            fmt = 'PNG' if prefer_png else 'JPEG'
            out = io.BytesIO()
            save_kwargs = {'format': fmt}
            if fmt == 'JPEG':
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                save_kwargs.update({'quality': 90, 'optimize': True})
                out_mime = 'image/jpeg'
            else:
                if img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                save_kwargs.update({'optimize': True, 'compress_level': 6})
                out_mime = 'image/png'
            img.save(out, **save_kwargs)
            data = out.getvalue()
            if not data:
                raise ValueError('empty_coerced_image')
            return data, out_mime
    except Exception as e:
        if mime == 'image/webp':
            raise ValueError(f'invalid_webp_image:{type(e).__name__}') from e
        if heif_input:
            converted = _coerce_heif_bytes_with_system_tool(raw)
            if converted:
                return converted
            raise ValueError(f'invalid_heif_image:{type(e).__name__}') from e
        fallback_mime = detected_mime or mime or 'application/octet-stream'
        return raw, fallback_mime

def _normalize_downloaded_image_payload(url: str, raw: bytes, content_type: str) -> tuple[bytes, str]:
    if not raw:
        raise ValueError('empty_remote_image')
    mime = str(content_type or '').strip()
    mime_l = mime.lower()
    if mime and not mime_l.startswith('image/'):
        if not (mime_l == 'application/octet-stream' or _looks_like_image_bytes(raw)):
            snippet = ''
            try:
                snippet = (raw[:120].decode('utf-8', 'ignore') or '')[:120].replace('\n', ' ')
            except Exception:
                snippet = ''
            raise ValueError(f'unsupported_image_content_type:{content_type}::{snippet}')
        mime = ''
    elif not mime and not _looks_like_image_bytes(raw):
        snippet = ''
        try:
            snippet = (raw[:120].decode('utf-8', 'ignore') or '')[:120].replace('\n', ' ')
        except Exception:
            snippet = ''
        raise ValueError(f'unsupported_image_content_type::{snippet}')
    if not mime:
        _ext = _guess_image_ext_from_url_and_type(url, '')
        mime = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
            '.gif': 'image/gif', '.bmp': 'image/bmp', '.svg': 'image/svg+xml', '.tif': 'image/tiff', '.tiff': 'image/tiff', '.heic': 'image/heic', '.heif': 'image/heif'
        }.get(_ext, 'application/octet-stream')
    return _coerce_image_bytes_for_model(raw, mime)


def _download_remote_image_requests(url: str, timeout: float | None = None) -> tuple[bytes, str]:
    timeout = float(timeout if timeout is not None else (app_getenv('REMOTE_IMAGE_TIMEOUT', '18') or 18))
    verify = str(app_getenv('GPT_TLS_VERIFY', '1')).strip() not in ('0', 'false', 'False')
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else url
    origin = ''
    if _is_douyin_image_host(host):
        referer = 'https://www.douyin.com/'
        origin = 'https://www.douyin.com'
    headers = {
        'User-Agent': app_getenv('WEB_FETCH_UA', 'Mozilla/5.0'),
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Language': app_getenv('WEB_FETCH_ACCEPT_LANGUAGE', 'zh-CN,zh;q=0.9,en;q=0.6'),
        'Referer': referer,
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
    }
    if origin:
        headers.update({
            'Origin': origin,
            'Sec-Fetch-Dest': 'image',
            'Sec-Fetch-Mode': 'no-cors',
            'Sec-Fetch-Site': 'cross-site',
        })
    ticket = _global_fetch_budget_acquire(url, task_type='remote_image')
    try:
        _host_fetch_wait(url, reason='remote_image')
        if not hasattr(_download_remote_image_requests, '_tls'):
            _download_remote_image_requests._tls = threading.local()  # type: ignore[attr-defined]
        tls = getattr(_download_remote_image_requests, '_tls')  # type: ignore[attr-defined]
        sess = getattr(tls, 'session', None)
        if sess is None:
            sess = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
            sess.mount('http://', adapter)
            sess.mount('https://', adapter)
            tls.session = sess
        request_retries = 1
        try:
            request_retries = max(1, min(int(app_getenv('REMOTE_IMAGE_REQUEST_RETRIES', '2') or 2), 4))
        except Exception:
            request_retries = 2
        retry_backoff = 0.45
        try:
            retry_backoff = max(0.05, min(float(app_getenv('REMOTE_IMAGE_RETRY_BACKOFF', '0.45') or 0.45), 5.0))
        except Exception:
            retry_backoff = 0.45
        last_request_err = None
        for attempt in range(1, request_retries + 1):
            try:
                r = sess.get(url, timeout=timeout, headers=headers, stream=True, verify=verify, allow_redirects=True)
                break
            except Exception as e:
                last_request_err = e
                _host_fetch_record(url, error=f'remote_image_requests:{type(e).__name__}', method='requests', task_type='remote_image')
                retryable = isinstance(e, (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError))
                if attempt >= request_retries or not retryable:
                    raise
                try:
                    app_logger.warning('[remote_image] requests-retry %s attempt=%s/%s :: %s: %s', url, attempt, request_retries, type(e).__name__, e)
                except Exception:
                    pass
                time.sleep(min(3.0, retry_backoff * attempt + 0.1 * random.random()))
        else:
            if last_request_err is not None:
                raise last_request_err
            raise RuntimeError('remote_image_requests_failed')
        status = int(getattr(r, 'status_code', 0) or 0)
        if status >= 400:
            _host_fetch_record(url, status_code=status, headers=dict(getattr(r, 'headers', {}) or {}), error='remote_image_http_error', method='requests', task_type='remote_image')
            if status in (401, 403, 404, 410, 429) and _is_playwright_unfriendly_remote_image_host(host):
                _host_fetch_mark_hard_fail(url, cooldown_s=float(app_getenv('REMOTE_IMAGE_FAST_BLOCK_COOLDOWN', '180') or 180), reason=f'blocked_status_{status}', error='remote_image_http_error')
            raise requests.HTTPError(f'{status} for remote image: {url}', response=r)
        content_type = str(r.headers.get('Content-Type') or '').strip()
        raw_probe = b''
        if content_type and not content_type.lower().startswith('image/'):
            try:
                raw_probe = next(r.iter_content(chunk_size=32), b'') or b''
            except Exception:
                raw_probe = b''
            if not ((content_type.lower() == 'application/octet-stream') or _looks_like_image_bytes(raw_probe)):
                snippet = ''
                try:
                    snippet = (raw_probe.decode('utf-8', 'ignore') or '')[:120].replace('\n', ' ')
                except Exception:
                    snippet = ''
                raise ValueError(f'unsupported_image_content_type:{content_type}::{snippet}')
            if content_type.lower() == 'application/octet-stream':
                content_type = ''
        max_bytes = 20 * 1024 * 1024
        buf = io.BytesIO()
        if raw_probe:
            buf.write(raw_probe)
        for chunk in r.iter_content(chunk_size=65536):
            if not chunk:
                continue
            buf.write(chunk)
            if buf.tell() > max_bytes:
                raise ValueError('remote_image_too_large')
        _host_fetch_record(url, status_code=status, headers=dict(getattr(r, 'headers', {}) or {}), method='requests', task_type='remote_image')
        return _normalize_downloaded_image_payload(url, buf.getvalue(), content_type)
    finally:
        _global_fetch_budget_release(ticket)



def _download_remote_image_playwright(url: str, timeout: float | None = None) -> tuple[bytes, str]:
    if not _cfg_bool('PLAYWRIGHT_ENABLE', True):
        raise RuntimeError('playwright_disabled')
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        raise RuntimeError(f'playwright_not_installed: {e}') from e

    timeout = float(timeout if timeout is not None else (app_getenv('REMOTE_IMAGE_PLAYWRIGHT_TIMEOUT', app_getenv('PLAYWRIGHT_TIMEOUT', '12')) or 12))
    timeout_ms = int(max(4.0, timeout) * 1000)
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else url
    if _is_douyin_image_host(host):
        referer = 'https://www.douyin.com/'
    ua = app_getenv('WEB_FETCH_UA', 'Mozilla/5.0')
    al = app_getenv('WEB_FETCH_ACCEPT_LANGUAGE', 'zh-CN,zh;q=0.9,en;q=0.6')
    max_bytes = 20 * 1024 * 1024
    verify_off = str(app_getenv('GPT_TLS_VERIFY', '1')).strip() in ('0', 'false', 'False')

    def _try_fetch_via_request(ctx, candidate_url: str) -> tuple[bytes, str] | None:
        try:
            resp = ctx.request.get(candidate_url, timeout=timeout_ms, fail_on_status_code=False)
            status = int(resp.status or 0)
            if status >= 400:
                return None
            body = resp.body() or b''
            if not body:
                return None
            if len(body) > max_bytes:
                raise ValueError('remote_image_too_large')
            ctype = str(resp.headers.get('content-type') or '').strip()
            return _normalize_downloaded_image_payload(candidate_url, body, ctype)
        except Exception:
            return None

    ticket = _global_fetch_budget_acquire(url, task_type='remote_image')
    try:
        with sync_playwright() as p:
            channel = (app_getenv('WEB_FETCH_PW_CHANNEL', 'msedge') or 'msedge').strip() or 'msedge'
            launch_kwargs = {'headless': True}
            if channel:
                launch_kwargs['channel'] = channel
            browser = p.chromium.launch(**launch_kwargs)
            ctx = browser.new_context(
                user_agent=ua,
                extra_http_headers={'Accept-Language': al, 'Referer': referer},
                ignore_https_errors=verify_off,
            )
            page = ctx.new_page()
            seen: list[str] = []
            seen_set = set()

            def _remember(candidate: str):
                s = str(candidate or '').strip()
                if not s or s in seen_set:
                    return
                seen_set.add(s)
                seen.append(s)

            def _on_response(resp):
                try:
                    ctype = str((resp.headers or {}).get('content-type') or '').lower()
                    if 'image/' in ctype:
                        _remember(resp.url)
                except Exception:
                    pass

            page.on('response', _on_response)
            try:
                direct = _try_fetch_via_request(ctx, url)
                if direct is not None:
                    return direct

                page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
                try:
                    page.wait_for_load_state('networkidle', timeout=min(timeout_ms, 5000))
                except Exception:
                    pass
                _remember(page.url)
                try:
                    dom_urls = page.eval_on_selector_all('img', '''els => els.flatMap(el => {
    const vals = [];
    const push = (v) => { if (v && typeof v === 'string') vals.push(v); };
    push(el.currentSrc);
    push(el.src);
    push(el.getAttribute('data-src'));
    push(el.getAttribute('data-original'));
    const srcset = el.getAttribute('srcset') || el.getAttribute('data-srcset') || '';
    if (srcset) {
        srcset.split(',').forEach(part => {
            const u = String(part || '').trim().split(/\\s+/)[0];
            if (u) vals.push(u);
        });
    }
    return vals;
})''') or []
                except Exception:
                    dom_urls = []
                for item in dom_urls:
                    _remember(item)
                for candidate in seen:
                    got = _try_fetch_via_request(ctx, candidate)
                    if got is not None:
                        return got
                raise ValueError('remote_image_import_failed')
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    finally:
        _global_fetch_budget_release(ticket)


def _download_remote_image(url: str, timeout: float | None = None, playwright_timeout: float | None = None) -> tuple[bytes, str]:
    strategy = _decide_host_fetch_strategy(url, task_type='remote_image', allow_playwright=True)
    if strategy.get('mode') == 'cooldown_skip':
        raise HostFetchCooldownSkip(str(strategy.get('host') or _fetch_host_key(url) or ''), float(strategy.get('wait_s') or 0.0), str(strategy.get('reason') or 'cooldown'))
    if strategy.get('skip_direct'):
        raise RuntimeError(str(strategy.get('reason') or 'remote_image_direct_fetch_disabled'))

    def _should_bail_after_requests(err: Exception) -> bool:
        if _is_tls_cert_verification_error(err):
            _host_fetch_mark_hard_fail(url, reason='tls_cert_verify_failed', error=f'{type(err).__name__}: {err}')
            return True
        return _should_skip_playwright_remote_image_fallback(url, err)

    def _playwright_fallback(primary_err: Exception | None = None) -> tuple[bytes, str]:
        if not bool(strategy.get('allow_playwright', True)):
            if primary_err is not None:
                raise primary_err
            raise RuntimeError('playwright_strategy_disabled')
        try:
            raw, mime = _download_remote_image_playwright(url, timeout=playwright_timeout if playwright_timeout is not None else timeout)
            _host_fetch_record(url, status_code=200, method='playwright', task_type='remote_image')
            app_logger.info('[remote_image] playwright-fallback-ok %s', url)
            return raw, mime
        except Exception as pw_err:
            _host_fetch_record(url, error=f'remote_image_playwright:{type(pw_err).__name__}', method='playwright', task_type='remote_image')
            app_logger.warning('[remote_image] playwright-fail %s :: %s: %s', url, type(pw_err).__name__, pw_err)
            if primary_err is not None:
                raise primary_err
            raise

    primary_err = None
    host_lock = _remote_image_host_lock_for(url)
    if host_lock is None:
        try:
            return _download_remote_image_requests(url, timeout=timeout)
        except HostFetchCooldownSkip:
            raise
        except Exception as e:
            primary_err = e
            app_logger.warning('[remote_image] requests-fail %s :: %s: %s', url, type(e).__name__, e)
            if _should_bail_after_requests(e):
                raise
        return _playwright_fallback(primary_err)

    with host_lock:
        try:
            return _download_remote_image_requests(url, timeout=timeout)
        except HostFetchCooldownSkip:
            raise
        except Exception as e:
            primary_err = e
            app_logger.warning('[remote_image] requests-fail %s :: %s: %s', url, type(e).__name__, e)
            if _should_bail_after_requests(e):
                raise
        return _playwright_fallback(primary_err)


def _remote_image_to_data_url(url: str, request_timeout: float | None = None, fallback_timeout: float | None = None) -> str | None:
    u = str(url or '').strip()
    if not u or not (u.startswith('http://') or u.startswith('https://')):
        return None
    cached = _read_remote_image_cache(u)
    if cached is not None:
        raw, mime = cached
        app_logger.info('[remote_image_cache] hit %s', u)
        return f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
    skipped_recent_fail = False
    if _remote_image_failed_recently(u):
        skipped_recent_fail = True
        app_logger.warning('[remote_image_cache] recent-fail-soft-skip %s', u)
    key = _remote_image_cache_key(u)
    lock = _remote_image_lock_for(key)
    with lock:
        cached = _read_remote_image_cache(u)
        if cached is not None:
            raw, mime = cached
            app_logger.info('[remote_image_cache] hit-after-lock %s', u)
            return f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
        if skipped_recent_fail:
            return None
        strategy = _decide_host_fetch_strategy(u, task_type='remote_image', allow_playwright=True)
        if strategy.get('mode') == 'cooldown_skip' or strategy.get('skip_direct'):
            _remote_image_mark_failed(u)
            return None
        try:
            raw, mime = _download_remote_image(u, timeout=request_timeout, playwright_timeout=fallback_timeout)
            _write_remote_image_cache(u, raw, mime)
            with _REMOTE_IMAGE_FAIL_LOCK:
                _REMOTE_IMAGE_FAIL_CACHE.pop(key, None)
            app_logger.info('[remote_image_cache] miss->stored %s', u)
            return f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
        except HostFetchCooldownSkip as e:
            _remote_image_mark_failed(u)
            app_logger.warning('[remote_image_cache] cooldown-skip %s :: host=%s wait=%.2fs reason=%s', u, e.host, e.wait_s, e.reason)
            stale = _read_remote_image_cache(u)
            if stale is not None:
                raw, mime = stale
                return f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
            return None
        except Exception as e:
            _remote_image_mark_failed(u)
            app_logger.warning('[remote_image_cache] download-fail %s :: %s: %s', u, type(e).__name__, e)
            stale = _read_remote_image_cache(u)
            if stale is not None:
                raw, mime = stale
                return f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
            return None
