# Split from app3_parts/account/user_personalization_runtime_part.py.
# Purpose: request admission throttling, health snapshots, and health/ops routes.
# Loaded by user_personalization_runtime_part.py via _exec_split_file(...), sharing the original global namespace.

# ==============================
# Big-platform stability layer v4: request lane admission guard
# ==============================
# Reserve public request capacity for cheap control-plane APIs.  Heavy synchronous
# endpoints fail fast when the server is already busy, instead of occupying all
# Waitress threads until auth/status/poll requests start timing out.
try:
    APP_DEFAULTS.setdefault('WEBAI_HEAVY_REQUEST_MAX_CONCURRENT', '5')
    APP_DEFAULTS.setdefault('WEBAI_HEAVY_REQUEST_RETRY_AFTER_MS', '1600')
except Exception:
    pass

_WEBAI_REQUEST_ADMISSION_LOCK = threading.Lock()
_WEBAI_REQUEST_ADMISSION_ACTIVE = {'heavy': 0, 'light': 0, 'rejected': 0}


def _webai_admission_cfg_int(name: str, default: int, *, min_value: int = 0, max_value: int = 10000) -> int:
    try:
        value = int(str(app_getenv(name, str(default)) or default).strip())
    except Exception:
        value = int(default)
    return max(int(min_value), min(int(max_value), value))


_WEBAI_HEAVY_REQUEST_SEMAPHORE = threading.BoundedSemaphore(
    _webai_admission_cfg_int('WEBAI_HEAVY_REQUEST_MAX_CONCURRENT', 5, min_value=1, max_value=32)
)


_WEBBAI_LIGHT_PATH_EXACT = {
    '/',
    '/api3/auth/me',
    '/api3/auth/status',
    '/api3/chat-sync/manifest',
    '/api3/chat-sync/session',
    '/api3/chat-sync/push',
    '/api3/chat-sync/events',
    '/api3/chat_async/poll',
    '/api3/chat_async/stream',
    '/api3/chat_async/stop',
    '/api3/remote-image/status',
    '/api3/image-generation/mirror-status',
    '/api3/whoami',
}
_WEBBAI_LIGHT_PREFIXES = (
    '/static/',
    '/api3/uploads/',
    '/api3/download/',
    '/api3/generated-files/',
    '/api3/generated-download/',
)
_WEBBAI_HEAVY_PATH_EXACT = {
    '/api3/chat',
    '/api3/chat_stream',
    '/api3/web_search',
    '/api3/fetch_url',
    '/api3/fetch_urls',
    '/api3/code/run',
    '/api3/upload',
    '/api3/upload_chunk/finish',
    '/api3/cloud_connect',
    '/api3/thinking_capability_probe',
    '/api3/models/search',
    '/api3/kb/search',
}
_WEBBAI_HEAVY_PREFIXES = (
    '/api3/upload_chunk/',
)


def _webai_request_lane_for_current_request() -> str:
    try:
        path = str(request.path or '').strip()
        method = str(request.method or '').strip().upper()
    except Exception:
        return 'unknown'
    if path in _WEBBAI_LIGHT_PATH_EXACT or any(path.startswith(prefix) for prefix in _WEBBAI_LIGHT_PREFIXES):
        return 'light'
    if path in {'/api3/remote-image', '/api3/image_proxy'}:
        try:
            force_sync = str(request.args.get('wait') or request.args.get('sync') or request.args.get('force') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
        except Exception:
            force_sync = False
        return 'heavy' if force_sync else 'light'
    if path == '/api3/chat_async/start':
        # The route only creates a background job.  The worker itself is capped in
        # async_pullback_upload_server_part.py, so keeping this route light avoids
        # start_timeout while still protecting the real model work.
        return 'light'
    if method == 'POST' and (path in _WEBBAI_HEAVY_PATH_EXACT or any(path.startswith(prefix) for prefix in _WEBBAI_HEAVY_PREFIXES)):
        return 'heavy'
    return 'normal'


def _webai_request_admission_before_request():
    lane = _webai_request_lane_for_current_request()
    try:
        g.webai_request_lane = lane
        g.webai_heavy_request_slot = False
    except Exception:
        pass
    if lane == 'light':
        try:
            with _WEBAI_REQUEST_ADMISSION_LOCK:
                _WEBAI_REQUEST_ADMISSION_ACTIVE['light'] = int(_WEBAI_REQUEST_ADMISSION_ACTIVE.get('light') or 0) + 1
        except Exception:
            pass
        return None
    if lane != 'heavy':
        return None
    acquired = False
    try:
        acquired = _WEBAI_HEAVY_REQUEST_SEMAPHORE.acquire(blocking=False)
    except Exception:
        acquired = True
    if acquired:
        try:
            g.webai_heavy_request_slot = True
            with _WEBAI_REQUEST_ADMISSION_LOCK:
                _WEBAI_REQUEST_ADMISSION_ACTIVE['heavy'] = int(_WEBAI_REQUEST_ADMISSION_ACTIVE.get('heavy') or 0) + 1
        except Exception:
            pass
        return None
    retry_after_ms = _webai_admission_cfg_int('WEBAI_HEAVY_REQUEST_RETRY_AFTER_MS', 1600, min_value=300, max_value=60000)
    try:
        with _WEBAI_REQUEST_ADMISSION_LOCK:
            _WEBAI_REQUEST_ADMISSION_ACTIVE['rejected'] = int(_WEBAI_REQUEST_ADMISSION_ACTIVE.get('rejected') or 0) + 1
    except Exception:
        pass
    resp = _json_no_store_response({
        'ok': False,
        'error': '服务器正在处理较多任务，请稍后重试。',
        'code': 'server_busy_retryable',
        'lane': 'heavy',
        'retry_after_ms': retry_after_ms,
    }, 429)
    try:
        resp.headers['Retry-After'] = str(max(1, int(math.ceil(retry_after_ms / 1000.0))))
        resp.headers['X-WebAI-Request-Lane'] = 'heavy-rejected'
    except Exception:
        pass
    return resp


def _webai_request_admission_after_request(resp):
    try:
        lane = str(getattr(g, 'webai_request_lane', '') or '')
    except Exception:
        lane = ''
    try:
        if lane:
            resp.headers['X-WebAI-Request-Lane'] = lane
        if lane == 'light':
            resp.headers['X-WebAI-Light-Priority'] = '1'
    except Exception:
        pass
    try:
        if bool(getattr(g, 'webai_heavy_request_slot', False)):
            _WEBAI_HEAVY_REQUEST_SEMAPHORE.release()
            g.webai_heavy_request_slot = False
            with _WEBAI_REQUEST_ADMISSION_LOCK:
                _WEBAI_REQUEST_ADMISSION_ACTIVE['heavy'] = max(0, int(_WEBAI_REQUEST_ADMISSION_ACTIVE.get('heavy') or 0) - 1)
    except Exception:
        pass
    try:
        if lane == 'light':
            with _WEBAI_REQUEST_ADMISSION_LOCK:
                _WEBAI_REQUEST_ADMISSION_ACTIVE['light'] = max(0, int(_WEBAI_REQUEST_ADMISSION_ACTIVE.get('light') or 0) - 1)
    except Exception:
        pass
    return resp


try:
    funcs = list((app.before_request_funcs or {}).get(None) or [])
    if _webai_request_admission_before_request not in funcs:
        # Run after trace/auth setup but before route handlers.  Keeping it near the
        # front makes overload decisions cheap.
        funcs.append(_webai_request_admission_before_request)
    app.before_request_funcs[None] = funcs
except Exception:
    pass
try:
    after_funcs = list((app.after_request_funcs or {}).get(None) or [])
    if _webai_request_admission_after_request not in after_funcs:
        after_funcs.insert(0, _webai_request_admission_after_request)
    app.after_request_funcs[None] = after_funcs
except Exception:
    pass



# ==============================
# Big-platform stability layer v7: health checks and runtime status
# ==============================
# Public cloud deployments need very cheap probes that never touch model/search/image
# providers.  These routes are intentionally control-plane only so systemd,
# cloudflared, uptime checks and the browser can distinguish "app process alive"
# from "heavy AI task is slow".
try:
    APP_DEFAULTS.setdefault('WEBAI_HEALTH_DEGRADED_HEAVY_WAITING', '16')
    APP_DEFAULTS.setdefault('WEBAI_HEALTH_DEGRADED_CHAT_JOBS', '120')
except Exception:
    pass

_WEBAI_HEALTH_STARTED_AT = time.time()


def _webai_health_cfg_int(name: str, default: int, *, min_value: int = 0, max_value: int = 100000) -> int:
    try:
        value = int(str(app_getenv(name, str(default)) or default).strip())
    except Exception:
        value = int(default)
    return max(int(min_value), min(int(max_value), value))


def _webai_health_dir_status(path: str = '') -> dict:
    raw = str(path or '').strip()
    out = {'path': raw, 'exists': False, 'is_dir': False, 'readable': False, 'writable': False}
    if not raw:
        return out
    try:
        out['exists'] = os.path.exists(raw)
        out['is_dir'] = os.path.isdir(raw)
        out['readable'] = os.access(raw, os.R_OK)
        out['writable'] = os.access(raw, os.W_OK)
    except Exception:
        pass
    return out


def _webai_health_chat_async_snapshot() -> dict:
    worker = {}
    try:
        snap = globals().get('_chat_async_worker_slot_snapshot')
        if callable(snap):
            worker = dict(snap() or {})
    except Exception:
        worker = {}
    jobs_total = running = done = queued = errored = 0
    try:
        lock = globals().get('_CHAT_ASYNC_JOB_LOCK')
        jobs = globals().get('_CHAT_ASYNC_JOBS')
        if lock is not None and isinstance(jobs, dict):
            with lock:
                rows = [dict(v or {}) for v in jobs.values() if isinstance(v, dict)]
        elif isinstance(jobs, dict):
            rows = [dict(v or {}) for v in jobs.values() if isinstance(v, dict)]
        else:
            rows = []
        jobs_total = len(rows)
        for rec in rows:
            st = str(rec.get('status') or '').strip().lower()
            if bool(rec.get('done')):
                done += 1
            if st == 'running':
                running += 1
            elif st == 'queued':
                queued += 1
            elif st == 'error':
                errored += 1
    except Exception:
        pass
    return {
        'worker': worker,
        'jobs_total': jobs_total,
        'jobs_running': running,
        'jobs_queued': queued,
        'jobs_done': done,
        'jobs_error': errored,
    }


def _webai_health_remote_image_snapshot() -> dict:
    out = {'jobs_total': 0, 'active': 0, 'queued': 0, 'fetching': 0, 'ready': 0, 'failed_retryable': 0, 'failed_final': 0, 'limit': 0}
    try:
        limiter = globals().get('_remote_image_proxy_background_limit')
        if callable(limiter):
            out['limit'] = int(limiter())
    except Exception:
        pass
    try:
        lock = globals().get('_REMOTE_IMAGE_PROXY_JOB_LOCK')
        jobs = globals().get('_REMOTE_IMAGE_PROXY_JOBS')
        active = globals().get('_REMOTE_IMAGE_PROXY_ACTIVE')
        if lock is not None and isinstance(jobs, dict):
            with lock:
                rows = [dict(v or {}) for v in jobs.values() if isinstance(v, dict)]
                out['active'] = int(active or 0)
        elif isinstance(jobs, dict):
            rows = [dict(v or {}) for v in jobs.values() if isinstance(v, dict)]
            out['active'] = int(active or 0)
        else:
            rows = []
        out['jobs_total'] = len(rows)
        for rec in rows:
            st = str(rec.get('state') or rec.get('status') or '').strip().lower()
            if st in out:
                out[st] = int(out.get(st) or 0) + 1
    except Exception:
        pass
    return out


def _webai_health_admission_snapshot() -> dict:
    try:
        with _WEBAI_REQUEST_ADMISSION_LOCK:
            active = dict(_WEBAI_REQUEST_ADMISSION_ACTIVE or {})
    except Exception:
        active = {}
    try:
        heavy_limit = _webai_admission_cfg_int('WEBAI_HEAVY_REQUEST_MAX_CONCURRENT', 5, min_value=1, max_value=32)
    except Exception:
        heavy_limit = 5
    return {
        'active_heavy': int(active.get('heavy') or 0),
        'active_light': int(active.get('light') or 0),
        'rejected_total': int(active.get('rejected') or 0),
        'heavy_limit': int(heavy_limit),
    }


def _webai_health_snapshot(*, readiness: bool = False) -> dict:
    now_ts = time.time()
    dirs = {
        'base': _webai_health_dir_status(globals().get('BASE_DIR', '')),
        'uploads_local': _webai_health_dir_status(globals().get('UPLOAD_DIR_LOCAL', '')),
        'uploads_public': _webai_health_dir_status(globals().get('UPLOAD_DIR_PUBLIC', '')),
        'generated_local': _webai_health_dir_status(globals().get('GENERATED_DIR_LOCAL', '')),
        'generated_public': _webai_health_dir_status(globals().get('GENERATED_DIR_PUBLIC', '')),
    }
    admission = _webai_health_admission_snapshot()
    chat_async = _webai_health_chat_async_snapshot()
    remote_image = _webai_health_remote_image_snapshot()
    issues = []
    if not dirs['base'].get('exists') or not dirs['base'].get('is_dir'):
        issues.append('base_dir_missing')
    if readiness:
        for key in ('uploads_local', 'uploads_public', 'generated_local', 'generated_public'):
            row = dirs.get(key) or {}
            # Missing dirs can be created lazily by the app, but non-writable existing dirs
            # are real deployment problems.
            if row.get('exists') and not row.get('writable'):
                issues.append(f'{key}_not_writable')
    try:
        heavy_waiting_limit = _webai_health_cfg_int('WEBAI_HEALTH_DEGRADED_HEAVY_WAITING', 16, min_value=1, max_value=10000)
        waiting = int((chat_async.get('worker') or {}).get('waiting') or 0)
        if waiting >= heavy_waiting_limit:
            issues.append('chat_async_queue_high')
    except Exception:
        pass
    try:
        job_limit = _webai_health_cfg_int('WEBAI_HEALTH_DEGRADED_CHAT_JOBS', 120, min_value=10, max_value=100000)
        if int(chat_async.get('jobs_total') or 0) >= job_limit:
            issues.append('chat_async_jobs_high')
    except Exception:
        pass
    status = 'ok' if not issues else 'degraded'
    payload = {
        'ok': True,
        'status': status,
        'ready': bool(not issues or (issues == ['chat_async_queue_high'])),
        'issues': issues,
        'app': globals().get('APP_NAME', 'Apervia'),
        'build': _app_build_info(),
        'port': globals().get('PORT', None),
        'time': _fmt_ts(now_ts),
        'uptime_s': int(max(0, now_ts - float(_WEBAI_HEALTH_STARTED_AT or now_ts))),
        'request_id': str(getattr(g, 'request_id', '') or ''),
        'admission': admission,
        'chat_async': chat_async,
        'remote_image': remote_image,
        'dirs': dirs if readiness else {},
        'config': {
            'waitress_threads': _webai_health_cfg_int('WAITRESS_THREADS', 32, min_value=16, max_value=128),
            'heavy_request_max_concurrent': admission.get('heavy_limit'),
            'chat_async_worker_max_concurrent': int((chat_async.get('worker') or {}).get('limit') or _webai_health_cfg_int('CHAT_ASYNC_WORKER_MAX_CONCURRENT', 4, min_value=1, max_value=24)),
            'remote_image_background_workers': remote_image.get('limit'),
        },
    }
    return payload


def _webai_health_response(payload: dict, status: int = 200):
    resp = _json_no_store_response(payload, status=status)
    try:
        resp.headers['X-WebAI-Health'] = str(payload.get('status') or 'ok')
        resp.headers['X-WebAI-Uptime-S'] = str(payload.get('uptime_s') or 0)
    except Exception:
        pass
    return resp


@app.get('/api3/health/live')
@app.get('/api3/healthz')
def webai_health_live_route():
    return _webai_health_response({
        'ok': True,
        'status': 'ok',
        'app': globals().get('APP_NAME', 'Apervia'),
        'build': _app_build_info(),
        'port': globals().get('PORT', None),
        'time': _fmt_ts(time.time()),
        'uptime_s': int(max(0, time.time() - float(_WEBAI_HEALTH_STARTED_AT or time.time()))),
        'request_id': str(getattr(g, 'request_id', '') or ''),
    })


@app.get('/api3/health/ready')
@app.get('/api3/readyz')
def webai_health_ready_route():
    payload = _webai_health_snapshot(readiness=True)
    status_code = 200 if bool(payload.get('ready')) else 503
    return _webai_health_response(payload, status=status_code)


@app.get('/api3/ops/status')
def webai_ops_status_route():
    # Redacted runtime status for the admin/operator UI or curl.  No secrets,
    # no prompt content and no user message text are returned here.
    return _webai_health_response(_webai_health_snapshot(readiness=False))
