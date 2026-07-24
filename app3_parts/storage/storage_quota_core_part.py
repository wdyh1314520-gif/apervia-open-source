# storage quota owner resolution, tracking, pruning, cleanup, and write checks.

# Purpose: shared disk quota helpers for uploads, generated files, caches, chunks and knowledge base.

class StorageQuotaError(Exception):
    def __init__(self, message: str = '', *, payload: dict | None = None):
        super().__init__(str(message or '存储空间不足'))
        self.payload = payload or {}


_STORAGE_QUOTA_LOCK = threading.Lock()
_PLATFORM_ADMIN_PROCESS_START_TS = time.time()
_PLATFORM_ADMIN_SYSTEM_STATUS_LOCK = threading.Lock()
_PLATFORM_ADMIN_SYSTEM_STATUS_CACHE = {
    'cpu': None,
    'network': None,
}


def _storage_quota_int(name: str, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        value = int(str(app_getenv(name, str(default)) or default).strip() or default)
    except Exception:
        value = int(default)
    value = max(int(minimum), int(value))
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def _storage_quota_human(num: int | float) -> str:
    try:
        n = float(num or 0)
    except Exception:
        n = 0.0
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    idx = 0
    while n >= 1024 and idx < len(units) - 1:
        n /= 1024.0
        idx += 1
    if idx == 0:
        return f'{int(n)}{units[idx]}'
    return f'{n:.1f}{units[idx]}'


_STORAGE_QUOTA_POLICY_SPECS = (
    {'key': 'APP_STORAGE_MAX_BYTES', 'label': '整站应用数据上限', 'group': '整站与磁盘保护', 'default': 12 * 1024**3, 'minimum': 1024**3, 'maximum': 64 * 1024**4, 'note': '应用目录总占用达到上限时阻止继续增长。'},
    {'key': 'STORAGE_CLEANUP_FREE_BYTES', 'label': '自动清理触发剩余空间', 'group': '整站与磁盘保护', 'default': 8 * 1024**3, 'minimum': 256 * 1024**2, 'maximum': 64 * 1024**4, 'note': '磁盘剩余空间低于此值时优先清理可过期数据。'},
    {'key': 'STORAGE_MIN_FREE_BYTES', 'label': '拒绝大文件写入剩余空间', 'group': '整站与磁盘保护', 'default': 5 * 1024**3, 'minimum': 128 * 1024**2, 'maximum': 64 * 1024**4, 'note': '必须低于自动清理触发值。'},
    {'key': 'ACCOUNT_STORAGE_DEFAULT_MAX_BYTES', 'label': '普通账号默认额度', 'group': '账号额度', 'default': 1024**3, 'minimum': 64 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'ACCOUNT_STORAGE_ANONYMOUS_MAX_BYTES', 'label': '匿名访问额度', 'group': '账号额度', 'default': 128 * 1024**2, 'minimum': 16 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'UPLOAD_DIR_PUBLIC_MAX_BYTES', 'label': '公网上传目录', 'group': '文件与生成目录', 'default': 1024**3, 'minimum': 64 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'UPLOAD_DIR_LOCAL_MAX_BYTES', 'label': '本地上传目录', 'group': '文件与生成目录', 'default': 512 * 1024**2, 'minimum': 64 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'GENERATED_DIR_PUBLIC_MAX_BYTES', 'label': '公网生成文件目录', 'group': '文件与生成目录', 'default': 2 * 1024**3, 'minimum': 64 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'GENERATED_DIR_LOCAL_MAX_BYTES', 'label': '本地生成文件目录', 'group': '文件与生成目录', 'default': 512 * 1024**2, 'minimum': 64 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'SANDBOX_ROOT_MAX_BYTES', 'label': '沙盒目录总额度', 'group': '文件与生成目录', 'default': 4 * 1024**3, 'minimum': 128 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'KB_DB_MAX_BYTES', 'label': '知识库总额度', 'group': '知识库', 'default': 2 * 1024**3, 'minimum': 64 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'KB_OWNER_MAX_BYTES', 'label': '知识库单账号额度', 'group': '知识库', 'default': 512 * 1024**2, 'minimum': 64 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'KB_SINGLE_IMPORT_MAX_BYTES', 'label': '知识库单次导入上限', 'group': '知识库', 'default': 80 * 1024**2, 'minimum': 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'UPLOAD_CHUNKS_MAX_BYTES', 'label': '上传分片临时目录', 'group': '缓存、索引与维护', 'default': 1024**3, 'minimum': 64 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'AUTH_CHAT_BACKUP_MAX_BYTES', 'label': '会话备份目录', 'group': '缓存、索引与维护', 'default': 512 * 1024**2, 'minimum': 16 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'AUTH_CHAT_STORE_MAX_BYTES', 'label': '单账号会话同步数据上限', 'group': '数据库与维护阈值', 'default': 64 * 1024**2, 'minimum': 16 * 1024**2, 'maximum': 64 * 1024**4, 'note': '达到此值时停止同步并提示，不会自动删除会话。'},
    {'key': 'FILE_TEXT_STORE_MAX_BYTES', 'label': '文件全文索引', 'group': '缓存、索引与维护', 'default': 1024**3, 'minimum': 64 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'REMOTE_IMAGE_CACHE_MAX_BYTES', 'label': '远程图片缓存', 'group': '缓存、索引与维护', 'default': 256 * 1024**2, 'minimum': 16 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'FAVICON_CACHE_MAX_BYTES', 'label': '网站图标缓存', 'group': '缓存、索引与维护', 'default': 64 * 1024**2, 'minimum': 4 * 1024**2, 'maximum': 64 * 1024**4},
    {'key': 'FILE_REGISTRY_MAX_BYTES', 'label': '文件索引 JSON', 'group': '缓存、索引与维护', 'default': 32 * 1024**2, 'minimum': 512 * 1024, 'maximum': 64 * 1024**4},
    {'key': 'STORAGE_MAINTENANCE_CHAT_ASYNC_VACUUM_THRESHOLD_BYTES', 'label': '后台任务库压缩阈值', 'group': '数据库与维护阈值', 'default': 200 * 1024**2, 'minimum': 16 * 1024**2, 'maximum': 64 * 1024**4, 'note': '这是触发维护提示的阈值，不是严格写入上限。'},
    {'key': 'AUTH_CHAT_DB_MAX_BYTES', 'label': '账号云端会话库', 'group': '数据库与维护阈值', 'default': 512 * 1024**2, 'minimum': 64 * 1024**2, 'maximum': 64 * 1024**4},
)


def _storage_quota_policy_specs_by_key() -> dict:
    return {str(item.get('key') or ''): dict(item) for item in _STORAGE_QUOTA_POLICY_SPECS}


def _storage_quota_policy_payload() -> dict:
    overrides_fn = globals().get('_storage_quota_policy_overrides')
    overrides = overrides_fn() if callable(overrides_fn) else {}
    groups = []
    grouped = {}
    for spec in _STORAGE_QUOTA_POLICY_SPECS:
        key = str(spec.get('key') or '')
        default_value = int(spec.get('default') or 0)
        custom = key in overrides
        value = int(overrides.get(key) or default_value)
        item = {
            'key': key,
            'label': str(spec.get('label') or key),
            'group': str(spec.get('group') or '其他'),
            'note': str(spec.get('note') or ''),
            'value_bytes': value,
            'value_text': _storage_quota_human(value),
            'value_mb': round(value / float(1024**2), 3),
            'default_bytes': default_value,
            'default_text': _storage_quota_human(default_value),
            'minimum_bytes': int(spec.get('minimum') or 1),
            'maximum_bytes': int(spec.get('maximum') or 64 * 1024**4),
            'custom': custom,
        }
        group_name = item['group']
        if group_name not in grouped:
            grouped[group_name] = {'name': group_name, 'items': []}
            groups.append(grouped[group_name])
        grouped[group_name]['items'].append(item)
    return {
        'ok': True,
        'groups': groups,
        'items': [item for group in groups for item in group['items']],
        'custom_count': len(overrides),
        'policy_file': os.path.basename(_storage_quota_policy_file()),
    }


def _storage_quota_validate_policy_values(values: dict) -> None:
    cleanup_free = int(values.get('STORAGE_CLEANUP_FREE_BYTES') or 0)
    min_free = int(values.get('STORAGE_MIN_FREE_BYTES') or 0)
    if cleanup_free < min_free:
        raise ValueError('自动清理触发剩余空间不能低于拒绝写入剩余空间')
    kb_db = int(values.get('KB_DB_MAX_BYTES') or 0)
    kb_owner = int(values.get('KB_OWNER_MAX_BYTES') or 0)
    kb_import = int(values.get('KB_SINGLE_IMPORT_MAX_BYTES') or 0)
    if kb_import > kb_owner:
        raise ValueError('知识库单次导入上限不能高于知识库单账号额度')
    if kb_owner > kb_db:
        raise ValueError('知识库单账号额度不能高于知识库总额度')


def _storage_quota_refresh_runtime_policy_globals() -> dict:
    specs = _storage_quota_policy_specs_by_key()
    overrides_fn = globals().get('_storage_quota_policy_overrides')
    overrides = dict(overrides_fn() if callable(overrides_fn) else {})
    effective = {key: int(overrides.get(key) or spec.get('default') or 0) for key, spec in specs.items()}
    if 'AUTH_CHAT_DB_MAX_BYTES' in globals():
        globals()['AUTH_CHAT_DB_MAX_BYTES'] = int(effective['AUTH_CHAT_DB_MAX_BYTES'])
    if 'AUTH_CHAT_BACKUP_MAX_BYTES' in globals():
        globals()['AUTH_CHAT_BACKUP_MAX_BYTES'] = int(effective['AUTH_CHAT_BACKUP_MAX_BYTES'])
    if 'AUTH_CHAT_STORE_MAX_BYTES' in globals():
        globals()['AUTH_CHAT_STORE_MAX_BYTES'] = int(effective['AUTH_CHAT_STORE_MAX_BYTES'])
    return effective


def _storage_quota_update_policy(limits=None, *, reset_keys=None, reset_all: bool = False) -> dict:
    specs = _storage_quota_policy_specs_by_key()
    overrides_fn = globals().get('_storage_quota_policy_overrides')
    save_fn = globals().get('_storage_quota_save_policy_overrides')
    if not callable(save_fn):
        raise RuntimeError('存储额度策略持久化不可用')
    overrides = dict(overrides_fn() if callable(overrides_fn) else {})
    if reset_all:
        overrides.clear()
    for raw_key in (reset_keys or []):
        key = str(raw_key or '').strip()
        if key not in specs:
            raise ValueError(f'未知的存储额度项：{key}')
        overrides.pop(key, None)
    if limits is not None and not isinstance(limits, dict):
        raise ValueError('limits 必须是对象')
    for raw_key, raw_value in (limits or {}).items():
        key = str(raw_key or '').strip()
        spec = specs.get(key)
        if not spec:
            raise ValueError(f'未知的存储额度项：{key}')
        try:
            value = int(raw_value)
        except Exception:
            raise ValueError(f'{spec["label"]} 必须是整数字节数')
        minimum = int(spec.get('minimum') or 1)
        maximum = int(spec.get('maximum') or 64 * 1024**4)
        if value < minimum or value > maximum:
            raise ValueError(f'{spec["label"]} 必须在 {_storage_quota_human(minimum)} 到 {_storage_quota_human(maximum)} 之间')
        overrides[key] = value
    effective = {key: int(overrides.get(key) or spec.get('default') or 0) for key, spec in specs.items()}
    _storage_quota_validate_policy_values(effective)
    save_fn(overrides)
    _storage_quota_refresh_runtime_policy_globals()
    audit_fn = globals().get('_platform_admin_audit_append')
    if callable(audit_fn):
        audit_fn('storage_policy_update', 'storage_quota_policy', {
            'updated_keys': sorted(str(key) for key in (limits or {}).keys()),
            'reset_keys': sorted(str(key) for key in (reset_keys or [])),
            'reset_all': bool(reset_all),
            'custom_count': len(overrides),
        }, ok=True)
    return _storage_quota_policy_payload()


def _storage_quota_file_size(path: str) -> int:
    try:
        return int(os.path.getsize(path)) if os.path.isfile(path) else 0
    except Exception:
        return 0


def _storage_quota_json_size(obj) -> int:
    try:
        return len(json.dumps(obj if obj is not None else {}, ensure_ascii=False, separators=(',', ':')).encode('utf-8', 'ignore'))
    except Exception:
        return 0


def _storage_quota_norm_owner(value: str = '') -> str:
    raw = str(value or '').strip().lower()
    if not raw:
        return ''
    try:
        normalizer = globals().get('_normalize_login_email')
        if callable(normalizer):
            normalized = str(normalizer(raw) or '').strip().lower()
            if normalized:
                return normalized
    except Exception:
        pass
    return raw


def _storage_quota_current_async_owner_key() -> str:
    try:
        getter = globals().get('_chat_async_current_job_id')
        job_id = str(getter() if callable(getter) else '').strip()
        if not job_id:
            return ''
        rec = None
        job_getter = globals().get('_chat_async_get_job')
        if callable(job_getter):
            rec = job_getter(job_id)
        if not isinstance(rec, dict):
            lock = globals().get('_CHAT_ASYNC_JOB_LOCK')
            jobs = globals().get('_CHAT_ASYNC_JOBS')
            if lock is not None and isinstance(jobs, dict):
                with lock:
                    rec = dict(jobs.get(job_id) or {})
            elif isinstance(jobs, dict):
                rec = dict(jobs.get(job_id) or {})
        if isinstance(rec, dict):
            email = _storage_quota_norm_owner(rec.get('owner_email') or '')
            if email:
                return email
    except Exception:
        pass
    return ''


def _storage_quota_owner_key(owner_key: str | None = None) -> str:
    explicit = _storage_quota_norm_owner(owner_key or '')
    if explicit:
        return explicit
    try:
        getter = globals().get('_current_login_account')
        if callable(getter):
            acc = getter() or {}
            email = _storage_quota_norm_owner((acc or {}).get('email') or '')
            if email:
                return email
    except Exception:
        pass
    try:
        getter = globals().get('_current_login_email')
        if callable(getter):
            email = _storage_quota_norm_owner(getter() or '')
            if email:
                return email
    except Exception:
        pass
    async_owner = _storage_quota_current_async_owner_key()
    if async_owner:
        return async_owner
    return 'anonymous'


def _storage_quota_account_limits_file() -> str:
    return _app_data_path('storage_account_quota_limits.json')


def _storage_quota_load_account_limits() -> dict:
    path = _storage_quota_account_limits_file()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        if isinstance(data, dict):
            limits = data.get('limits') if isinstance(data.get('limits'), dict) else {}
            clean = {}
            for owner, value in limits.items():
                key = _storage_quota_norm_owner(owner or '')
                if not key:
                    continue
                try:
                    ivalue = int(value or 0)
                except Exception:
                    ivalue = 0
                if ivalue > 0:
                    clean[key] = ivalue
            return {'limits': clean, 'updated_at': float(data.get('updated_at') or 0.0)}
    except Exception:
        pass
    return {'limits': {}, 'updated_at': 0.0}


def _storage_quota_save_account_limits(data: dict) -> None:
    path = _storage_quota_account_limits_file()
    payload = data if isinstance(data, dict) else {'limits': {}}
    limits = payload.get('limits') if isinstance(payload.get('limits'), dict) else {}
    payload['limits'] = {str(k): int(v) for k, v in limits.items() if str(k or '').strip() and int(v or 0) > 0}
    payload['updated_at'] = time.time()
    tmp = path + '.tmp-' + uuid.uuid4().hex
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def _storage_quota_owner_limit_override_bytes(owner_key: str | None = None) -> int:
    owner = _storage_quota_owner_key(owner_key)
    if not owner or owner == 'anonymous':
        return 0
    try:
        data = _storage_quota_load_account_limits()
        return max(0, int((data.get('limits') or {}).get(owner) or 0))
    except Exception:
        return 0


def _storage_quota_set_owner_limit_override(owner_key: str, limit_bytes: int | None = None, *, reset: bool = False) -> dict:
    owner = _storage_quota_owner_key(owner_key)
    if not owner or owner == 'anonymous':
        raise ValueError('账号无效')
    with _STORAGE_QUOTA_LOCK:
        data = _storage_quota_load_account_limits()
        limits = data.setdefault('limits', {})
        if reset:
            limits.pop(owner, None)
        else:
            value = int(limit_bytes or 0)
            if value < 64 * 1024 * 1024:
                raise ValueError('账号额度不能低于 64MB')
            if value > 32 * 1024 * 1024 * 1024:
                raise ValueError('单账号额度不能超过 32GB')
            limits[owner] = value
        _storage_quota_save_account_limits(data)
    return _storage_quota_owner_breakdown(owner)


def _storage_quota_default_owner_limit_bytes(owner_key: str | None = None) -> int:
    owner = _storage_quota_owner_key(owner_key)
    if owner == 'anonymous':
        return _storage_quota_int('ACCOUNT_STORAGE_ANONYMOUS_MAX_BYTES', 128 * 1024 * 1024, minimum=16 * 1024 * 1024)
    return _storage_quota_int('ACCOUNT_STORAGE_DEFAULT_MAX_BYTES', 1024 * 1024 * 1024, minimum=128 * 1024 * 1024)


def _storage_quota_owner_limit_bytes(owner_key: str | None = None) -> int:
    owner = _storage_quota_owner_key(owner_key)
    override = _storage_quota_owner_limit_override_bytes(owner)
    if override > 0:
        return override
    return _storage_quota_default_owner_limit_bytes(owner)


def _storage_quota_owner_index_file() -> str:
    return _app_data_path('storage_account_files.json')


def _storage_quota_load_owner_index() -> dict:
    path = _storage_quota_owner_index_file()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        if isinstance(data, dict):
            files = data.get('files') if isinstance(data.get('files'), dict) else {}
            return {'files': files, 'updated_at': float(data.get('updated_at') or 0.0)}
    except Exception:
        pass
    return {'files': {}, 'updated_at': 0.0}


def _storage_quota_save_owner_index(data: dict) -> None:
    path = _storage_quota_owner_index_file()
    payload = data if isinstance(data, dict) else {'files': {}}
    payload['updated_at'] = time.time()
    tmp = path + '.tmp-' + uuid.uuid4().hex
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def _storage_quota_prune_owner_index_locked(data: dict | None = None) -> tuple[dict, bool]:
    payload = data if isinstance(data, dict) else _storage_quota_load_owner_index()
    files = payload.setdefault('files', {})
    if not isinstance(files, dict):
        payload['files'] = files = {}
    changed = False
    for key in list(files.keys()):
        rec = files.get(key) or {}
        path = str((rec or {}).get('path') or '').strip()
        if not path or not os.path.isfile(path):
            files.pop(key, None)
            changed = True
            continue
        try:
            actual = int(os.path.getsize(path))
        except Exception:
            actual = 0
        if actual <= 0:
            files.pop(key, None)
            changed = True
            continue
        if int((rec or {}).get('size') or 0) != actual:
            rec['size'] = actual
            rec['updated_at'] = time.time()
            files[key] = rec
            changed = True
    return payload, changed



def _storage_quota_prune_tracked_files(owner_key: str | None = None, *, target_free_bytes: int = 0, keep_paths: list[str] | None = None, namespace: str = '', scope: str = '') -> dict:
    """Delete oldest registered upload/generated files to make room.

    This is used only for quota rollover. It does not touch chat JSON directly;
    knowledge-base rows are handled by the KB module so DB metadata stays valid.
    """
    target = max(0, int(target_free_bytes or 0))
    if target <= 0:
        return {'ok': True, 'deleted': [], 'freed_bytes': 0, 'target_free_bytes': target}
    owner = _storage_quota_owner_key(owner_key) if owner_key is not None else ''
    ns_filter = str(namespace or '').strip().lower()
    scope_filter = str(scope or '').strip().lower()
    keep = {os.path.abspath(str(p)) for p in (keep_paths or []) if str(p or '').strip()}
    deleted: list[dict] = []
    freed = 0
    with _STORAGE_QUOTA_LOCK:
        data = _storage_quota_load_owner_index()
        data, _changed = _storage_quota_prune_owner_index_locked(data)
        files = data.setdefault('files', {})
        rows: list[tuple[float, str, dict]] = []
        for key, rec in list(files.items()):
            if not isinstance(rec, dict):
                continue
            path = os.path.abspath(str(rec.get('path') or '').strip())
            if not path or path in keep or not os.path.isfile(path):
                continue
            if owner and _storage_quota_owner_key(rec.get('owner') or '') != owner:
                continue
            if ns_filter and str(rec.get('namespace') or '').strip().lower() != ns_filter:
                continue
            if scope_filter and str(rec.get('scope') or '').strip().lower() != scope_filter:
                continue
            try:
                size = int(os.path.getsize(path) or rec.get('size') or 0)
            except Exception:
                size = int(rec.get('size') or 0)
            if size <= 0:
                continue
            try:
                mt = float(os.path.getmtime(path))
            except Exception:
                mt = float(rec.get('updated_at') or 0.0)
            rows.append((mt, key, {**rec, 'path': path, 'size': size}))
        rows.sort(key=lambda item: (item[0], str((item[2] or {}).get('path') or '')))
        for _mt, key, rec in rows:
            if freed >= target:
                break
            path = str(rec.get('path') or '')
            size = int(rec.get('size') or 0)
            try:
                os.remove(path)
                freed += max(0, size)
                post_delete = {}
                try:
                    post_delete = _storage_quota_after_local_file_deleted(
                        path,
                        namespace=str(rec.get('namespace') or ''),
                        scope=str(rec.get('scope') or ''),
                        filename=str(rec.get('filename') or ''),
                        reason='quota_prune_tracked_files',
                    )
                except Exception:
                    post_delete = {}
                deleted.append({
                    'filename': os.path.basename(path),
                    'path': path,
                    'owner': _storage_quota_owner_key(rec.get('owner') or ''),
                    'namespace': str(rec.get('namespace') or ''),
                    'scope': str(rec.get('scope') or ''),
                    'size_bytes': size,
                    'size_text': _storage_quota_human(size),
                    'post_delete': post_delete,
                })
            except Exception:
                continue
            files.pop(key, None)
        try:
            _storage_quota_save_owner_index(data)
        except Exception:
            pass
    return {'ok': True, 'deleted': deleted, 'deleted_count': len(deleted), 'freed_bytes': freed, 'freed_text': _storage_quota_human(freed), 'target_free_bytes': target, 'target_free_text': _storage_quota_human(target)}

def _storage_quota_owner_tracked_bytes(owner_key: str | None = None, *, prune: bool = True) -> int:
    owner = _storage_quota_owner_key(owner_key)
    with _STORAGE_QUOTA_LOCK:
        data = _storage_quota_load_owner_index()
        if prune:
            data, changed = _storage_quota_prune_owner_index_locked(data)
            if changed:
                try:
                    _storage_quota_save_owner_index(data)
                except Exception:
                    pass
        total = 0
        for rec in (data.get('files') or {}).values():
            if _storage_quota_owner_key((rec or {}).get('owner') or '') == owner:
                total += max(0, int((rec or {}).get('size') or 0))
        return total


def _storage_quota_owner_kb_bytes(owner_key: str | None = None) -> int:
    owner = _storage_quota_owner_key(owner_key)
    try:
        kb_used = globals().get('_kb_owner_used_bytes')
        kb_conn = globals().get('_kb_db_connect')
        if callable(kb_used) and callable(kb_conn):
            with kb_conn() as conn:
                return max(0, int(kb_used(owner, conn=conn) or 0))
        if callable(kb_used):
            return max(0, int(kb_used(owner) or 0))
    except Exception:
        return 0
    return 0


def _storage_quota_owner_chat_bytes(owner_key: str | None = None) -> int:
    owner = _storage_quota_owner_key(owner_key)
    try:
        account_bytes = globals().get('_auth_chat_store_account_bytes')
        if callable(account_bytes):
            return max(0, int(account_bytes(owner) or 0))
    except Exception:
        pass
    try:
        getter = globals().get('_auth_chat_store_get')
        if callable(getter):
            rec = getter(owner) or {}
            return _storage_quota_json_size(rec)
    except Exception:
        pass
    return 0


def _storage_quota_sandbox_root() -> str:
    raw = globals().get('SANDBOX_ROOT_DIR') or _app_data_path('sandboxes')
    return os.path.abspath(str(raw or _app_data_path('sandboxes')))


def _storage_quota_sandbox_safe_slug(value: str = '', fallback: str = 'default') -> str:
    fn = globals().get('_sandbox_safe_slug')
    if callable(fn):
        try:
            return str(fn(value, fallback) or fallback)
        except Exception:
            pass
    raw = str(value or '').strip() or str(fallback or 'default')
    slug = re.sub(r'[^0-9A-Za-z_.-]+', '-', raw).strip('.-_')
    return (slug or str(fallback or 'default'))[:80]


def _storage_quota_sandbox_owner_slug(owner_key: str | None = None) -> str:
    owner = _storage_quota_owner_key(owner_key)
    digest = hashlib.sha256(owner.encode('utf-8', errors='ignore')).hexdigest()[:16]
    label = _storage_quota_sandbox_safe_slug(owner.split('@', 1)[0], 'owner')[:32]
    return f'{label}-{digest}'


def _storage_quota_sandbox_owner_root(owner_key: str | None = None) -> str:
    return os.path.abspath(os.path.join(_storage_quota_sandbox_root(), _storage_quota_sandbox_owner_slug(owner_key)))


def _storage_quota_sandbox_source_abs(source: dict | None = None) -> str:
    src = dict(source or {}) if isinstance(source, dict) else {}
    root_rel = str(src.get('sandbox_root_rel') or '').strip().replace('\\', '/').strip('/')
    rel = str(src.get('path') or '').strip().replace('\\', '/').strip('/')
    if not root_rel or not rel:
        return ''
    if root_rel.startswith('/') or rel.startswith('/') or '..' in root_rel.split('/') or '..' in rel.split('/'):
        return ''
    root = _storage_quota_sandbox_root()
    target = os.path.abspath(os.path.join(root, *[p for p in (root_rel + '/' + rel).split('/') if p]))
    if not (target == root or target.startswith(root + os.sep)):
        return ''
    return target


def _storage_quota_sandbox_referenced_paths(owner_key: str | None = None) -> set[str]:
    owner = _storage_quota_owner_key(owner_key) if owner_key is not None else ''
    out: set[str] = set()
    snapshot = globals().get('_file_registry_files_snapshot')
    files = snapshot() if callable(snapshot) else {}
    for rec in files.values():
        if not isinstance(rec, dict):
            continue
        if owner:
            rec_owner = _storage_quota_owner_key(rec.get('owner_key') or rec.get('owner') or '')
            if rec_owner != owner:
                continue
        for src in (rec.get('sandbox_source_files') or []):
            path = _storage_quota_sandbox_source_abs(src if isinstance(src, dict) else {})
            if path:
                out.add(path)
    return out


def _storage_quota_sandbox_session_rows(owner_key: str | None = None) -> list[dict]:
    owner_root = _storage_quota_sandbox_owner_root(owner_key)
    rows: list[dict] = []
    if not os.path.isdir(owner_root):
        return rows
    try:
        entries = sorted(os.scandir(owner_root), key=lambda e: e.name.lower())
    except Exception:
        return rows
    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
            files = _storage_quota_collect_files(entry.path)
            size = sum(int(item[2] or 0) for item in files)
            mt = max([float(item[0] or 0) for item in files] + [float(entry.stat(follow_symlinks=False).st_mtime or 0)])
            rows.append({
                'session_id': entry.name,
                'path': os.path.abspath(entry.path),
                'bytes': size,
                'text': _storage_quota_human(size),
                'file_count': len(files),
                'updated_at': mt,
                'updated_at_text': _storage_quota_fmt_ts(mt),
            })
        except Exception:
            continue
    rows.sort(key=lambda item: (float(item.get('updated_at') or 0), str(item.get('session_id') or '')))
    return rows


def _storage_quota_owner_sandbox_breakdown(owner_key: str | None = None) -> dict:
    rows = _storage_quota_sandbox_session_rows(owner_key)
    total = sum(max(0, int((row or {}).get('bytes') or 0)) for row in rows)
    file_count = sum(max(0, int((row or {}).get('file_count') or 0)) for row in rows)
    return {
        'sandbox_bytes': total,
        'sandbox_text': _storage_quota_human(total),
        'sandbox_file_count': file_count,
        'sandbox_session_count': len(rows),
        'sandbox_sessions': rows,
    }


def _storage_quota_owner_sandbox_bytes(owner_key: str | None = None) -> int:
    return int(_storage_quota_owner_sandbox_breakdown(owner_key).get('sandbox_bytes') or 0)


def _storage_quota_remove_empty_dirs(root: str = '') -> int:
    base = os.path.abspath(str(root or '').strip())
    if not base or not os.path.isdir(base):
        return 0
    removed = 0
    for dirpath, dirnames, filenames in os.walk(base, topdown=False):
        if os.path.abspath(dirpath) == base:
            continue
        try:
            if not dirnames and not filenames:
                os.rmdir(dirpath)
                removed += 1
        except Exception:
            continue
    return removed


def _storage_quota_prune_sandbox_dirs(owner_key: str | None = None, *, target_free_bytes: int = 0, max_bytes: int | None = None, ttl_seconds: int | None = None) -> dict:
    root = _storage_quota_sandbox_owner_root(owner_key) if owner_key is not None else _storage_quota_sandbox_root()
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return {'ok': True, 'root': root, 'deleted': [], 'deleted_count': 0, 'freed_bytes': 0, 'freed_text': _storage_quota_human(0), 'empty_dirs_removed': 0}
    ttl = _storage_quota_int('SANDBOX_SESSION_TTL_S', 7 * 24 * 3600, minimum=3600) if ttl_seconds is None else max(0, int(ttl_seconds or 0))
    limit = max(0, int(max_bytes if max_bytes is not None else _storage_quota_int('SANDBOX_ROOT_MAX_BYTES', 4 * 1024 * 1024 * 1024, minimum=128 * 1024 * 1024)))
    active_grace = _storage_quota_int('SANDBOX_ACTIVE_GRACE_S', 6 * 3600, minimum=0)
    target = max(0, int(target_free_bytes or 0))
    keep = _storage_quota_sandbox_referenced_paths(owner_key)
    rows = _storage_quota_collect_files(root)
    total = sum(int(size or 0) for _mt, _fp, size in rows)
    rows.sort(key=lambda item: (item[0], item[1]))
    now = time.time()
    deleted: list[dict] = []
    freed = 0
    for mt, fp, size in rows:
        ap = os.path.abspath(fp)
        if ap in keep:
            continue
        if active_grace > 0 and now - float(mt or 0) < float(active_grace):
            continue
        expired = bool(ttl > 0 and now - float(mt or 0) > float(ttl))
        oversized = bool(limit > 0 and total - freed > limit)
        needed = bool(target > 0 and freed < target)
        if not (expired or oversized or needed):
            continue
        try:
            os.remove(ap)
            freed += max(0, int(size or 0))
            deleted.append({'path': ap, 'size_bytes': int(size or 0), 'size_text': _storage_quota_human(size)})
        except Exception:
            continue
    empty_removed = _storage_quota_remove_empty_dirs(root)
    return {
        'ok': True,
        'root': root,
        'total_bytes': total,
        'total_text': _storage_quota_human(total),
        'max_bytes': limit,
        'max_text': _storage_quota_human(limit),
        'ttl_seconds': ttl,
        'active_grace_seconds': active_grace,
        'target_free_bytes': target,
        'target_free_text': _storage_quota_human(target),
        'deleted': deleted,
        'deleted_count': len(deleted),
        'freed_bytes': freed,
        'freed_text': _storage_quota_human(freed),
        'protected_count': len(keep),
        'empty_dirs_removed': empty_removed,
    }


def _storage_quota_owner_used_bytes(owner_key: str | None = None) -> int:
    owner = _storage_quota_owner_key(owner_key)
    return (
        _storage_quota_owner_tracked_bytes(owner)
        + _storage_quota_owner_kb_bytes(owner)
        + _storage_quota_owner_chat_bytes(owner)
        + _storage_quota_owner_sandbox_bytes(owner)
    )


def _storage_quota_owner_public_payload(owner_key: str | None = None, *, used_bytes: int | None = None, limit_bytes: int | None = None) -> dict:
    owner = _storage_quota_owner_key(owner_key)
    used = _storage_quota_owner_used_bytes(owner) if used_bytes is None else max(0, int(used_bytes or 0))
    limit = _storage_quota_owner_limit_bytes(owner) if limit_bytes is None else max(0, int(limit_bytes or 0))
    return {
        'owner': owner,
        'used_bytes': used,
        'limit_bytes': limit,
        'used_text': _storage_quota_human(used),
        'limit_text': _storage_quota_human(limit),
        'available_bytes': max(0, limit - used),
        'available_text': _storage_quota_human(max(0, limit - used)),
    }


def _storage_quota_require_owner_write(owner_key: str | None = None, *, incoming_bytes: int = 0, kind: str = 'file', current_bytes: int | None = None) -> None:
    owner = _storage_quota_owner_key(owner_key)
    limit = _storage_quota_owner_limit_bytes(owner)
    if limit <= 0:
        return
    incoming = max(0, int(incoming_bytes or 0))
    used = _storage_quota_owner_used_bytes(owner) if current_bytes is None else max(0, int(current_bytes or 0))
    if used + incoming <= limit:
        return
    need_free = max(0, used + incoming - limit)
    prune_detail = {
        'tracked_files': _storage_quota_prune_tracked_files(owner, target_free_bytes=need_free),
        'sandboxes': {},
    }
    if current_bytes is None:
        used = _storage_quota_owner_used_bytes(owner)
    else:
        used = max(0, int(current_bytes or 0) - int(((prune_detail.get('tracked_files') or {}).get('freed_bytes')) or 0))
    if used + incoming <= limit:
        return
    prune_detail['sandboxes'] = _storage_quota_prune_sandbox_dirs(owner, target_free_bytes=max(0, used + incoming - limit))
    if current_bytes is None:
        used = _storage_quota_owner_used_bytes(owner)
    else:
        used = max(0, int(used or 0) - int(((prune_detail.get('sandboxes') or {}).get('freed_bytes')) or 0))
    if used + incoming <= limit:
        return
    payload = _storage_quota_owner_public_payload(owner, used_bytes=used, limit_bytes=limit)
    payload.update({'incoming_bytes': incoming, 'incoming_text': _storage_quota_human(incoming), 'kind': str(kind or 'file'), 'auto_prune': prune_detail})
    raise StorageQuotaError(
        f'当前账号空间暂时不足：已用 {_storage_quota_human(used)} / {_storage_quota_human(limit)}，本次需要 {_storage_quota_human(incoming)}。系统已自动回收最旧的可过期文件，但当前请求仍超过可自动腾出的空间。',
        payload={'account_quota': payload},
    )


def _storage_quota_register_file(owner_key: str | None = None, *, namespace: str = '', scope: str = '', path: str = '', size_bytes: int = 0, filename: str = '') -> dict:
    fp = os.path.abspath(str(path or '').strip())
    if not fp or not os.path.isfile(fp):
        return {}
    owner = _storage_quota_owner_key(owner_key)
    try:
        size = int(size_bytes or os.path.getsize(fp) or 0)
    except Exception:
        size = int(size_bytes or 0)
    if size <= 0:
        return {}
    with _STORAGE_QUOTA_LOCK:
        data = _storage_quota_load_owner_index()
        data, _changed = _storage_quota_prune_owner_index_locked(data)
        files = data.setdefault('files', {})
        key = hashlib.sha256(fp.encode('utf-8', 'ignore')).hexdigest()[:32]
        files[key] = {
            'owner': owner,
            'namespace': str(namespace or '').strip() or 'file',
            'scope': str(scope or '').strip(),
            'path': fp,
            'filename': os.path.basename(str(filename or fp)),
            'size': size,
            'updated_at': time.time(),
        }
        _storage_quota_save_owner_index(data)
    return _storage_quota_owner_public_payload(owner)


def _storage_quota_file_location_from_path(path: str = '', *, namespace: str = '', scope: str = '', filename: str = '') -> dict:
    fp = os.path.abspath(str(path or '').strip()) if str(path or '').strip() else ''
    ns = str(namespace or '').strip().lower()
    sc = str(scope or '').strip().lower()
    name = os.path.basename(str(filename or '').strip()) if str(filename or '').strip() else (os.path.basename(fp) if fp else '')
    roots = [
        ('uploads', 'local', globals().get('UPLOAD_DIR_LOCAL')),
        ('uploads', 'public', globals().get('UPLOAD_DIR_PUBLIC')),
        ('generated', 'local', globals().get('GENERATED_DIR_LOCAL')),
        ('generated', 'public', globals().get('GENERATED_DIR_PUBLIC')),
    ]
    if fp:
        for cand_ns, cand_scope, root in roots:
            try:
                root_abs = os.path.abspath(str(root or '').strip())
            except Exception:
                root_abs = ''
            if root_abs and fp.startswith(root_abs + os.sep):
                ns = ns or cand_ns
                sc = sc or cand_scope
                name = name or os.path.basename(fp)
                break
    if ns not in {'uploads', 'generated'}:
        ns = 'uploads'
    if sc not in {'local', 'public'}:
        try:
            normalizer = globals().get('_normalize_upload_scope')
            sc = str(normalizer(sc) if callable(normalizer) else sc).strip().lower()
        except Exception:
            sc = 'local'
    if sc not in {'local', 'public'}:
        sc = 'local'
    return {'namespace': ns, 'scope': sc, 'filename': name, 'path': fp}


def _storage_quota_registry_ids_for_file(namespace: str = '', scope: str = '', filename: str = '', path: str = '') -> list[str]:
    ns = str(namespace or '').strip().lower()
    sc = str(scope or '').strip().lower()
    name = os.path.basename(str(filename or '').strip())
    target_path = os.path.normcase(os.path.abspath(str(path or '').strip())) if str(path or '').strip() else ''
    snapshot = globals().get('_file_registry_files_snapshot')
    files = snapshot() if callable(snapshot) else {}
    out: list[str] = []
    path_candidates_fn = globals().get('_file_library_path_candidates')
    for fid, rec in files.items():
        if not isinstance(rec, dict):
            continue
        rec_id = str(rec.get('file_id') or fid or '').strip()
        if not rec_id or rec_id in out:
            continue
        matched = False
        if name:
            rec_name = os.path.basename(str(rec.get('saved_filename') or rec.get('filename') or '').strip())
            rec_ns = str(rec.get('namespace') or '').strip().lower()
            rec_scope = str(rec.get('scope') or '').strip().lower()
            if rec_name == name and (not ns or rec_ns == ns) and (not sc or rec_scope in {sc, ''}):
                matched = True
        if not matched and target_path and callable(path_candidates_fn):
            try:
                for cand in path_candidates_fn(rec):
                    if os.path.normcase(os.path.abspath(str(cand or ''))) == target_path:
                        matched = True
                        break
            except Exception:
                pass
        if matched:
            out.append(rec_id)
    return out


def _storage_quota_after_local_file_deleted(path: str = '', *, namespace: str = '', scope: str = '', filename: str = '', reason: str = '') -> dict:
    loc = _storage_quota_file_location_from_path(path, namespace=namespace, scope=scope, filename=filename)
    ns = str(loc.get('namespace') or '').strip()
    sc = str(loc.get('scope') or '').strip()
    name = str(loc.get('filename') or '').strip()
    out = {'ok': True, 'namespace': ns, 'scope': sc, 'filename': name, 'reason': str(reason or '').strip(), 'object_storage_deleted': False, 'registry_removed': []}
    if name:
        try:
            deleter = globals().get('_object_storage_delete_file')
            if callable(deleter):
                out['object_storage_deleted'] = bool(deleter(ns, sc, name))
        except Exception as e:
            out['ok'] = False
            out['object_storage_error'] = f'{type(e).__name__}: {e}'
    ids = _storage_quota_registry_ids_for_file(ns, sc, name, path)
    remover = globals().get('_file_library_remove_registry_record')
    for fid in ids:
        try:
            removed = remover(fid) if callable(remover) else {}
            out['registry_removed'].append({'file_id': fid, **(removed if isinstance(removed, dict) else {})})
        except Exception as e:
            out.setdefault('registry_errors', []).append({'file_id': fid, 'error': f'{type(e).__name__}: {e}'})
            out['ok'] = False
    locked_here = False
    try:
        locked_here = bool(_STORAGE_QUOTA_LOCK.acquire(blocking=False))
        if locked_here:
            data = _storage_quota_load_owner_index()
            data, _changed = _storage_quota_prune_owner_index_locked(data)
            _storage_quota_save_owner_index(data)
    except Exception:
        pass
    finally:
        if locked_here:
            try:
                _STORAGE_QUOTA_LOCK.release()
            except Exception:
                pass
    return out


def _storage_quota_sqlite_group_size(path: str) -> int:
    raw = str(path or '').strip()
    if not raw:
        return 0
    total = 0
    for suffix in ('', '-wal', '-shm'):
        total += _storage_quota_file_size(raw + suffix)
    return total


def _storage_quota_dir_size(root: str) -> int:
    base = str(root or '').strip()
    if not base or not os.path.exists(base):
        return 0
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                fp = os.path.join(dirpath, name)
                try:
                    total += int(os.path.getsize(fp))
                except Exception:
                    continue
    except Exception:
        return total
    return total


def _storage_quota_collect_files(root: str) -> list[tuple[float, str, int]]:
    base = str(root or '').strip()
    rows: list[tuple[float, str, int]] = []
    if not base or not os.path.exists(base):
        return rows
    try:
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                fp = os.path.join(dirpath, name)
                try:
                    st = os.stat(fp)
                    if os.path.isfile(fp):
                        rows.append((float(st.st_mtime), fp, int(st.st_size)))
                except Exception:
                    continue
    except Exception:
        pass
    return rows


def _storage_quota_prune_dir(root: str, max_bytes: int, *, ttl_seconds: float | None = None, keep_paths: list[str] | None = None) -> dict:
    base = os.path.abspath(str(root or '').strip())
    if not base or not os.path.exists(base):
        return {'ok': True, 'total_bytes': 0, 'max_bytes': int(max_bytes or 0), 'deleted': []}
    limit = int(max_bytes or 0)
    keep = {os.path.abspath(str(p)) for p in (keep_paths or []) if str(p or '').strip()}
    now = time.time()
    deleted: list[str] = []
    rows = _storage_quota_collect_files(base)
    total = sum(size for _mt, _fp, size in rows)
    rows.sort(key=lambda item: (item[0], item[1]))
    for mt, fp, size in rows:
        if os.path.abspath(fp) in keep:
            continue
        expired = ttl_seconds is not None and ttl_seconds > 0 and now - float(mt) > float(ttl_seconds)
        oversized = limit > 0 and total > limit
        if not expired and not oversized:
            continue
        try:
            os.remove(fp)
            total = max(0, total - int(size))
            deleted.append(os.path.relpath(fp, base))
        except Exception:
            continue
    try:
        for dirpath, dirnames, _filenames in os.walk(base, topdown=False):
            for dirname in dirnames:
                dp = os.path.join(dirpath, dirname)
                try:
                    if not os.listdir(dp):
                        os.rmdir(dp)
                except Exception:
                    pass
    except Exception:
        pass
    return {'ok': True, 'total_bytes': total, 'max_bytes': limit, 'deleted': deleted}


def _storage_quota_child_dir_size(path: str) -> int:
    return _storage_quota_dir_size(path)


def _storage_quota_prune_child_dirs(root: str, max_bytes: int, *, ttl_seconds: float | None = None) -> dict:
    base = os.path.abspath(str(root or '').strip())
    if not base or not os.path.isdir(base):
        return {'ok': True, 'total_bytes': 0, 'max_bytes': int(max_bytes or 0), 'deleted': []}
    limit = int(max_bytes or 0)
    now = time.time()
    rows: list[tuple[float, str, int]] = []
    try:
        for scope in os.listdir(base):
            scope_dir = os.path.join(base, scope)
            if not os.path.isdir(scope_dir):
                continue
            for name in os.listdir(scope_dir):
                path = os.path.join(scope_dir, name)
                if not os.path.isdir(path):
                    continue
                try:
                    st = os.stat(path)
                    rows.append((float(st.st_mtime), path, _storage_quota_child_dir_size(path)))
                except Exception:
                    continue
    except Exception:
        return {'ok': False, 'total_bytes': 0, 'max_bytes': limit, 'deleted': []}
    total = sum(size for _mt, _path, size in rows)
    rows.sort(key=lambda item: (item[0], item[1]))
    deleted: list[str] = []
    for mt, path, size in rows:
        expired = ttl_seconds is not None and ttl_seconds > 0 and now - float(mt) > float(ttl_seconds)
        oversized = limit > 0 and total > limit
        if not expired and not oversized:
            continue
        try:
            shutil.rmtree(path, ignore_errors=True)
            total = max(0, total - int(size))
            deleted.append(os.path.relpath(path, base))
        except Exception:
            continue
    return {'ok': True, 'total_bytes': total, 'max_bytes': limit, 'deleted': deleted}


def _storage_quota_prune_known_file_dirs(*, target_free_bytes: int = 0, keep_paths: list[str] | None = None) -> dict:
    target = max(0, int(target_free_bytes or 0))
    if target <= 0:
        return {'ok': True, 'deleted': [], 'freed_bytes': 0, 'target_free_bytes': target}
    roots = []
    for root in (UPLOAD_DIR_LOCAL, UPLOAD_DIR_PUBLIC, GENERATED_DIR_LOCAL, GENERATED_DIR_PUBLIC):
        ap = os.path.abspath(str(root or '').strip())
        if ap and ap not in roots:
            roots.append(ap)
    keep = {os.path.abspath(str(p)) for p in (keep_paths or []) if str(p or '').strip()}
    rows: list[tuple[float, str, int, str]] = []
    for root in roots:
        try:
            for mt, fp, size in _storage_quota_collect_files(root):
                ap = os.path.abspath(fp)
                if ap in keep:
                    continue
                rows.append((mt, ap, int(size or 0), root))
        except Exception:
            continue
    rows.sort(key=lambda item: (item[0], item[1]))
    deleted: list[dict] = []
    freed = 0
    for _mt, fp, size, root in rows:
        if freed >= target:
            break
        try:
            os.remove(fp)
            freed += max(0, int(size or 0))
            post_delete = {}
            try:
                post_delete = _storage_quota_after_local_file_deleted(fp, reason='quota_prune_known_file_dirs')
            except Exception:
                post_delete = {}
            deleted.append({'path': fp, 'filename': os.path.basename(fp), 'size_bytes': int(size or 0), 'size_text': _storage_quota_human(size), 'root': root, 'post_delete': post_delete})
        except Exception:
            continue
    try:
        with _STORAGE_QUOTA_LOCK:
            data = _storage_quota_load_owner_index()
            data, _changed = _storage_quota_prune_owner_index_locked(data)
            _storage_quota_save_owner_index(data)
    except Exception:
        pass
    return {'ok': True, 'deleted': deleted, 'deleted_count': len(deleted), 'freed_bytes': freed, 'freed_text': _storage_quota_human(freed), 'target_free_bytes': target, 'target_free_text': _storage_quota_human(target)}

def _storage_quota_disk_free(path: str | None = None) -> int:
    target = str(path or APP_DATA_DIR or '.').strip() or '.'
    try:
        probe = target
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        usage = shutil.disk_usage(probe or APP_DATA_DIR or '.')
        return int(usage.free)
    except Exception:
        return 0


def _storage_quota_app_used_bytes() -> int:
    paths = [
        UPLOAD_DIR_LOCAL,
        UPLOAD_DIR_PUBLIC,
        GENERATED_DIR_LOCAL,
        GENERATED_DIR_PUBLIC,
        app_getenv('REMOTE_IMAGE_CACHE_DIR', REMOTE_IMAGE_CACHE_DIR_DEFAULT),
        _app_data_path('favicon_cache'),
        _app_data_path('file_text_store'),
        _app_data_path('upload_chunks'),
        _app_data_path('auth_chat_store_backups'),
        _storage_quota_sandbox_root(),
    ]
    total = 0
    seen: set[str] = set()
    for path in paths:
        ap = os.path.abspath(str(path or '').strip())
        if not ap or ap in seen:
            continue
        seen.add(ap)
        total += _storage_quota_dir_size(ap)
    total += _storage_quota_sqlite_group_size(app_getenv('KB_DB_FILE', _app_data_path('knowledge_base.db')))
    total += _storage_quota_sqlite_group_size(app_getenv('HOST_FETCH_DB_FILE', _app_data_path('host_fetch_state.db')))
    total += _storage_quota_sqlite_group_size(_app_data_path('chat_async_jobs.db'))
    total += _storage_quota_sqlite_group_size(_storage_quota_auth_chat_db_file())
    total += _storage_quota_file_size(_app_data_path('auth_chat_store.json'))
    total += _storage_quota_file_size(_app_data_path('storage_account_files.json'))
    return total


def _storage_quota_cleanup(reason: str = '') -> dict:
    details: dict[str, dict] = {}
    with _STORAGE_QUOTA_LOCK:
        try:
            fn = globals().get('_prune_remote_image_cache')
            if callable(fn):
                fn()
        except Exception:
            pass
        try:
            fn = globals().get('_prune_favicon_cache')
            if callable(fn):
                fn()
        except Exception:
            pass
        try:
            chunks_root = _app_data_path('upload_chunks')
            ttl = _storage_quota_int('PUBLIC_UPLOAD_CHUNK_MAX_AGE', 21600, minimum=600)
            max_bytes = _storage_quota_int('UPLOAD_CHUNKS_MAX_BYTES', 1024 * 1024 * 1024, minimum=64 * 1024 * 1024)
            details['upload_chunks'] = _storage_quota_prune_child_dirs(chunks_root, max_bytes, ttl_seconds=ttl)
        except Exception:
            pass
        try:
            backup_root = _app_data_path('auth_chat_store_backups')
            max_bytes = _storage_quota_int('AUTH_CHAT_BACKUP_MAX_BYTES', 512 * 1024 * 1024, minimum=16 * 1024 * 1024)
            details['auth_chat_backups'] = _storage_quota_prune_dir(backup_root, max_bytes)
        except Exception:
            pass
        try:
            text_root = _app_data_path('file_text_store')
            max_bytes = _storage_quota_int('FILE_TEXT_STORE_MAX_BYTES', 1024 * 1024 * 1024, minimum=64 * 1024 * 1024)
            details['file_text_store'] = _storage_quota_prune_dir(text_root, max_bytes)
        except Exception:
            pass
        try:
            max_bytes = _storage_quota_int('SANDBOX_ROOT_MAX_BYTES', 4 * 1024 * 1024 * 1024, minimum=128 * 1024 * 1024)
            ttl = _storage_quota_int('SANDBOX_SESSION_TTL_S', 7 * 24 * 3600, minimum=3600)
            details['sandboxes'] = _storage_quota_prune_sandbox_dirs(max_bytes=max_bytes, ttl_seconds=ttl)
        except Exception:
            pass
    return {'ok': True, 'reason': str(reason or ''), 'details': details}


def _storage_quota_check_system(*, incoming_bytes: int = 0, path: str | None = None, cleanup: bool = True) -> None:
    incoming = max(0, int(incoming_bytes or 0))
    min_free = _storage_quota_int('STORAGE_MIN_FREE_BYTES', 5 * 1024 * 1024 * 1024, minimum=512 * 1024 * 1024)
    cleanup_free = _storage_quota_int('STORAGE_CLEANUP_FREE_BYTES', 8 * 1024 * 1024 * 1024, minimum=min_free)
    free_before = _storage_quota_disk_free(path or APP_DATA_DIR)
    if cleanup and free_before and free_before - incoming < cleanup_free:
        _storage_quota_cleanup('low_free_space')
    free_after = _storage_quota_disk_free(path or APP_DATA_DIR)
    if free_after and free_after - incoming < min_free:
        free_text = _storage_quota_human(free_after)
        minimum_text = _storage_quota_human(min_free)
        raise StorageQuotaError(
            'storage_system_min_free',
            payload={
                'code': 'storage_system_min_free',
                'params': {'free': free_text, 'minimum': minimum_text},
                'free_bytes': int(free_after),
                'minimum_free_bytes': int(min_free),
            },
        )


def _storage_quota_check_app_total(*, incoming_bytes: int = 0) -> None:
    limit = _storage_quota_int('APP_STORAGE_MAX_BYTES', 12 * 1024 * 1024 * 1024, minimum=1024 * 1024 * 1024)
    if limit <= 0:
        return
    incoming = max(0, int(incoming_bytes or 0))
    used = _storage_quota_app_used_bytes()
    if used + incoming <= limit:
        return
    _storage_quota_cleanup('app_storage_limit')
    used = _storage_quota_app_used_bytes()
    if used + incoming > limit:
        _storage_quota_prune_tracked_files(None, target_free_bytes=max(0, used + incoming - limit))
        used = _storage_quota_app_used_bytes()
    if used + incoming > limit:
        _storage_quota_prune_known_file_dirs(target_free_bytes=max(0, used + incoming - limit))
        used = _storage_quota_app_used_bytes()
    if used + incoming > limit:
        _storage_quota_prune_sandbox_dirs(target_free_bytes=max(0, used + incoming - limit))
        used = _storage_quota_app_used_bytes()
    if used + incoming > limit:
        raise StorageQuotaError(f'应用存储空间暂时不足，当前已用 {_storage_quota_human(used)} / {_storage_quota_human(limit)}。系统已自动回收最旧的可过期内容，但当前请求仍超过可自动腾出的空间。')


def _storage_quota_require_write(kind: str = 'file', *, incoming_bytes: int = 0, target_path: str | None = None, owner_key: str | None = None) -> None:
    _storage_quota_check_system(incoming_bytes=incoming_bytes, path=target_path or APP_DATA_DIR, cleanup=True)
    _storage_quota_check_app_total(incoming_bytes=incoming_bytes)
    _storage_quota_require_owner_write(owner_key, incoming_bytes=incoming_bytes, kind=kind)


def _storage_quota_module_limit(kind: str, current_bytes: int, incoming_bytes: int, max_bytes: int, *, label: str = '') -> None:
    limit = int(max_bytes or 0)
    if limit <= 0:
        return
    cur = max(0, int(current_bytes or 0))
    incoming = max(0, int(incoming_bytes or 0))
    if incoming > limit:
        raise StorageQuotaError(f'{label or kind}单次内容过大：{_storage_quota_human(incoming)}，超过系统自动维护上限 {_storage_quota_human(limit)}。')
    if cur + incoming <= limit:
        return
    # 兜底：调用方通常已经按模块清过旧文件；这里再尝试按已知文件目录回收一次，避免把“删除旧内容”的压力交给用户。
    try:
        detail = _storage_quota_prune_known_file_dirs(target_free_bytes=max(0, cur + incoming - limit))
        cur = max(0, cur - int((detail or {}).get('freed_bytes') or 0))
    except Exception:
        pass
    if cur + incoming > limit:
        raise StorageQuotaError(f'{label or kind}空间暂时不足：当前 {_storage_quota_human(cur)} / {_storage_quota_human(limit)}，本次需要 {_storage_quota_human(incoming)}。系统已自动回收最旧的可过期内容，但当前请求仍超过可自动腾出的空间。')


def _storage_quota_error_response(err: Exception, status: int = 507):
    payload = {'ok': False, 'error': str(err), 'code': 'storage_quota_exceeded'}
    try:
        extra = getattr(err, 'payload', None)
        if isinstance(extra, dict):
            payload.update(extra)
    except Exception:
        pass
    return jsonify(payload), status
