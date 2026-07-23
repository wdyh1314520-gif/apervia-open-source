# Split from app3_parts/tools/file_registry_edit_tools_part.py.
# Purpose: sandbox core status, quotas, owner/session paths.
# Loaded by file_registry_edit_tools_part.py via _exec_split_file(...), sharing app3.py globals.

def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


SANDBOX_ROOT_DIR = _app_data_path('sandboxes')
SANDBOX_DENY_DIR_NAMES = {
    '.git', '.hg', '.svn', '__pycache__', '.pytest_cache', '.mypy_cache',
    'node_modules', '.venv', 'venv', 'env', '.idea', '.vscode',
}


def _sandbox_tools_enabled() -> bool:
    raw = str(app_getenv('SANDBOX_TOOLS_ENABLED', '1') or '1').strip().lower()
    return raw not in {'0', 'false', 'off', 'no'}


def _sandbox_configured_image() -> str:
    return str(app_getenv('SANDBOX_DOCKER_IMAGE', '') or '').strip()


def _sandbox_image() -> str:
    image = _sandbox_configured_image()
    if not image:
        raise RuntimeError('SANDBOX_DOCKER_IMAGE_not_configured')
    image_lower = image.lower()
    if re.search(r'(^|/)python:[0-9][0-9.]*-slim(?:$|[@:])', image_lower):
        raise RuntimeError('SANDBOX_DOCKER_IMAGE_disallowed_slim')
    return image


def _sandbox_image_for_result() -> str:
    try:
        return _sandbox_image()
    except Exception:
        return _sandbox_configured_image()


def _sandbox_backend_status() -> tuple[bool, str]:
    if not _sandbox_tools_enabled():
        return False, 'sandbox_tools_disabled'
    try:
        _sandbox_image()
    except RuntimeError as e:
        err = str(e or '').strip()
        if err == 'SANDBOX_DOCKER_IMAGE_disallowed_slim':
            return False, 'sandbox_image_disallowed_slim'
        return False, 'sandbox_image_not_configured'
    health = _sandbox_runner_health()
    if not health or not bool(health.get('ok')) or str(health.get('service') or '') != 'apervia-sandbox-runner':
        return False, 'sandbox_backend_unavailable'
    if not bool(health.get('docker_ok')):
        return False, 'sandbox_backend_unavailable'
    if not bool(health.get('image_available')):
        return False, 'sandbox_image_not_available'
    return True, ''


def _sandbox_unavailable_result(error: str = 'sandbox_backend_unavailable', messages: list | None = None) -> dict:
    return {
        'ok': False,
        'error': str(error or 'sandbox_backend_unavailable'),
        'sandbox_id': _sandbox_session_slug(messages or []),
        'mount': '/mnt/data',
        'backend': 'sandbox_runner',
        'image': _sandbox_image_for_result(),
    }


def _sandbox_disk_max_bytes() -> int:
    try:
        return max(1 * 1024 * 1024, int(app_getenv('SANDBOX_DISK_MAX_BYTES', str(512 * 1024 * 1024)) or (512 * 1024 * 1024)))
    except Exception:
        return 512 * 1024 * 1024


def _sandbox_tmpfs_size(env_name: str = '', default_size: str = '64m') -> str:
    raw = str(app_getenv(env_name, default_size) or default_size).strip().lower()
    if re.match(r'^[1-9][0-9]*[kmg]$', raw):
        return raw
    return default_size


def _sandbox_dir_size(path: str = '') -> int:
    root = os.path.abspath(str(path or ''))
    if not root or not os.path.isdir(root):
        return 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SANDBOX_DENY_DIR_NAMES]
        for name in filenames:
            fp = os.path.join(dirpath, name)
            try:
                if os.path.isfile(fp) and not os.path.islink(fp):
                    total += int(os.path.getsize(fp))
            except Exception:
                pass
    return total


def _sandbox_quota_ok(messages: list | None = None, incoming_bytes: int = 0, current_path: str = '', append: bool = False) -> tuple[bool, dict]:
    root = _sandbox_root(messages or [])
    limit = _sandbox_disk_max_bytes()
    usage = _sandbox_dir_size(root)
    existing = 0
    try:
        if current_path and os.path.isfile(current_path):
            existing = int(os.path.getsize(current_path))
    except Exception:
        existing = 0
    projected = usage + max(0, int(incoming_bytes or 0))
    if current_path and not append:
        projected = max(0, usage - existing) + max(0, int(incoming_bytes or 0))
    if projected > limit:
        return False, {**_sandbox_result_base(messages or []), 'ok': False, 'error': 'sandbox_disk_quota_exceeded', 'disk_usage_bytes': usage, 'disk_max_bytes': limit, 'incoming_bytes': max(0, int(incoming_bytes or 0))}
    return True, {'disk_usage_bytes': usage, 'disk_max_bytes': limit, 'projected_disk_usage_bytes': projected}


def _sandbox_storage_owner_key() -> str:
    try:
        fn = globals().get('_file_read_registry_owner_key')
        owner = str(fn() if callable(fn) else '').strip().lower()
        if owner:
            return owner
    except Exception:
        pass
    return ''


def _sandbox_storage_quota_ok(messages: list | None = None, incoming_bytes: int = 0, current_path: str = '', append: bool = False) -> tuple[bool, dict]:
    checker = globals().get('_storage_quota_require_write')
    if not callable(checker):
        return True, {}
    incoming = max(0, int(incoming_bytes or 0))
    existing = 0
    try:
        if current_path and os.path.isfile(current_path):
            existing = int(os.path.getsize(current_path) or 0)
    except Exception:
        existing = 0
    delta = incoming if append else max(0, incoming - existing)
    if delta <= 0:
        return True, {}
    try:
        checker(kind='sandbox', incoming_bytes=delta, target_path=current_path or _sandbox_root(messages or []), owner_key=_sandbox_storage_owner_key() or None)
        return True, {'storage_incoming_bytes': delta}
    except Exception as e:
        payload = getattr(e, 'payload', {}) if hasattr(e, 'payload') else {}
        return False, {**_sandbox_result_base(messages or []), 'ok': False, 'error': 'storage_quota_exceeded', 'detail': str(e), **(payload if isinstance(payload, dict) else {})}


def _sandbox_safe_slug(value: str = '', fallback: str = 'default') -> str:
    raw = str(value or '').strip()
    if not raw:
        raw = fallback
    slug = re.sub(r'[^0-9A-Za-z_.-]+', '-', raw).strip('.-_')
    return (slug or fallback)[:80]


def _sandbox_owner_slug() -> str:
    owner = ''
    try:
        fn = globals().get('_file_read_registry_owner_key')
        owner = str(fn() if callable(fn) else '').strip().lower()
    except Exception:
        owner = ''
    if not owner:
        owner = 'anonymous'
    digest = hashlib.sha256(owner.encode('utf-8', errors='ignore')).hexdigest()[:16]
    label = _sandbox_safe_slug(owner.split('@', 1)[0], 'owner')[:32]
    return f'{label}-{digest}'


def _sandbox_session_slug(messages: list | None = None) -> str:
    try:
        getter = globals().get('_chat_async_current_job_id')
        job_id = str(getter() if callable(getter) else '').strip()
        if job_id:
            jobs = globals().get('_CHAT_ASYNC_JOBS')
            lock = globals().get('_CHAT_ASYNC_JOB_LOCK')
            rec = {}
            if lock is not None and isinstance(jobs, dict):
                with lock:
                    rec = dict(jobs.get(job_id) or {})
            elif isinstance(jobs, dict):
                rec = dict(jobs.get(job_id) or {})
            payload = rec.get('payload') if isinstance(rec.get('payload'), dict) else {}
            sid = str((payload or {}).get('client_session_id') or (payload or {}).get('session_id') or '').strip()
            if sid:
                return _sandbox_safe_slug(sid, 'session')
            if job_id:
                return _sandbox_safe_slug(job_id[:24], 'job')
    except Exception:
        pass
    try:
        text = _latest_user_text_from_messages(messages or []) if callable(globals().get('_latest_user_text_from_messages')) else ''
        if text:
            return 'chat-' + hashlib.sha256(str(text).encode('utf-8', errors='ignore')).hexdigest()[:16]
    except Exception:
        pass
    return 'default'


def _sandbox_root(messages: list | None = None) -> str:
    root = os.path.abspath(os.path.join(SANDBOX_ROOT_DIR, _sandbox_owner_slug(), _sandbox_session_slug(messages or [])))
    os.makedirs(root, exist_ok=True)
    return root
