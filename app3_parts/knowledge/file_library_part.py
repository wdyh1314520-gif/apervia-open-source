# file-library state, legacy sync, preview/delete/import helpers, and KB/file-library routes.

# ==============================
# UPLOAD FILE LIBRARY (raw uploaded/generated file management)
# ==============================
_FILE_LIBRARY_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg', '.tif', '.tiff', '.ico', '.jfif', '.heic', '.heif'}


def _file_library_owner_key(owner_key: str | None = None) -> str:
    explicit = str(owner_key or '').strip().lower()
    if explicit:
        return explicit
    getter = globals().get('_storage_quota_owner_key')
    if callable(getter):
        try:
            key = str(getter() or '').strip().lower()
            if key:
                return key
        except Exception:
            pass
    try:
        normalizer = globals().get('_normalize_login_email')
        current_email = globals().get('_current_login_email')
        if callable(current_email):
            raw = str(current_email() or '').strip()
            if raw:
                return str(normalizer(raw) if callable(normalizer) else raw).strip().lower()
    except Exception:
        pass
    return 'anonymous'


def _file_library_ext(filename: str = '', ext: str = '') -> str:
    raw_ext = str(ext or '').strip().lower()
    if raw_ext and not raw_ext.startswith('.'):
        raw_ext = '.' + raw_ext
    if raw_ext:
        return raw_ext
    try:
        return os.path.splitext(str(filename or '').strip())[1].lower()
    except Exception:
        return ''


def _file_library_category(filename: str = '', ext: str = '') -> str:
    return 'image' if _file_library_ext(filename, ext) in _FILE_LIBRARY_IMAGE_EXTS else 'file'


def _file_library_kb_importable(rec: dict | None = None) -> bool:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    filename = str(row.get('filename') or row.get('saved_filename') or '').strip()
    return _file_library_category(filename, str(row.get('ext') or '')) != 'image'


def _file_library_is_generated_preview_name(filename: str = '') -> bool:
    name = os.path.basename(str(filename or '').strip())
    if not name:
        return False
    stem, ext = os.path.splitext(name.lower())
    return bool(stem.endswith('__preview') and ext in {'.jpg', '.jpeg', '.webp', '.png'})


def _file_library_preview_name_for_original(filename: str = '') -> str:
    name = os.path.basename(str(filename or '').strip())
    if not name or _file_library_is_generated_preview_name(name):
        return ''
    stem = os.path.splitext(name)[0].strip() or 'image'
    return _safe_filename(f'{stem}__preview.jpg')


def _file_library_is_generated_preview_record(rec: dict | None = None) -> bool:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    namespace = str(row.get('namespace') or '').strip().lower()
    source = str(row.get('source') or '').strip().lower()
    if namespace != 'generated' and source != 'generated':
        return False
    return _file_library_is_generated_preview_name(str(row.get('saved_filename') or row.get('filename') or ''))


def _file_library_record_allowed_for_owner(rec: dict | None = None, owner_key: str = '') -> bool:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    owner = str(owner_key or _file_library_owner_key()).strip().lower()
    rec_owner = str(row.get('owner_key') or row.get('owner') or '').strip().lower()
    if rec_owner:
        return rec_owner == owner
    # 旧记录没有 owner_key，不能把它授权给任意登录账号。
    return False



_FILE_LIBRARY_LEGACY_SYNC_LOCK = threading.Lock()
_FILE_LIBRARY_LEGACY_SYNC_STATE = {'last_at': 0.0, 'last_result': {}}


def _file_library_legacy_sync_enabled() -> bool:
    try:
        return str(app_getenv('FILE_LIBRARY_LEGACY_SYNC_ENABLED', '1') or '1').strip().lower() not in {'0', 'false', 'no', 'off'}
    except Exception:
        return True


def _file_library_legacy_sync_interval_s() -> float:
    try:
        return max(30.0, min(float(str(app_getenv('FILE_LIBRARY_LEGACY_SYNC_INTERVAL_S', str(30 * 60)) or (30 * 60))), 24 * 3600.0))
    except Exception:
        return float(30 * 60)


def _file_library_legacy_sync_max_files() -> int:
    try:
        return max(100, min(int(str(app_getenv('FILE_LIBRARY_LEGACY_SYNC_MAX_FILES', '10000') or '10000')), 100000))
    except Exception:
        return 10000


def _file_library_legacy_scan_roots() -> list[dict]:
    rows: list[dict] = []
    candidates = [
        ('uploads', 'upload', 'local', 'UPLOAD_DIR_LOCAL'),
        ('uploads', 'upload', 'public', 'UPLOAD_DIR_PUBLIC'),
        ('generated', 'generated', 'local', 'GENERATED_DIR_LOCAL'),
        ('generated', 'generated', 'public', 'GENERATED_DIR_PUBLIC'),
    ]
    for namespace, source, scope, global_name in candidates:
        root = str(globals().get(global_name) or '').strip()
        if not root:
            continue
        try:
            root_abs = os.path.abspath(root)
        except Exception:
            continue
        if not os.path.isdir(root_abs):
            continue
        rows.append({'namespace': namespace, 'source': source, 'scope': _normalize_upload_scope(scope), 'root': root_abs})
    return rows


def _file_library_legacy_path_key(path: str = '') -> str:
    try:
        return os.path.abspath(str(path or '').strip()).replace('\\', '/').lower()
    except Exception:
        return str(path or '').strip().replace('\\', '/').lower()


def _file_library_legacy_file_key(namespace: str = '', scope: str = '', filename: str = '') -> tuple[str, str, str]:
    return (
        str(namespace or '').strip().lower(),
        _normalize_upload_scope(scope) if str(scope or '').strip() else '',
        os.path.basename(str(filename or '').strip()).lower(),
    )


def _file_library_legacy_add_owner(mapping: dict, key, owner: str = '') -> None:
    if not key:
        return
    normalized = str(owner or '').strip().lower()
    if not normalized:
        return
    prev = mapping.get(key)
    if prev is None:
        mapping[key] = normalized
    elif prev and prev != normalized:
        mapping[key] = ''


def _file_library_legacy_owner_maps_from_quota() -> tuple[dict, dict]:
    by_path: dict[str, str] = {}
    by_file: dict[tuple[str, str, str], str] = {}
    loader = globals().get('_storage_quota_load_owner_index')
    if not callable(loader):
        return by_path, by_file
    try:
        data = loader() or {}
    except Exception:
        return by_path, by_file
    files = data.get('files') if isinstance(data.get('files'), dict) else {}
    for rec in files.values():
        if not isinstance(rec, dict):
            continue
        owner = _file_library_owner_key(str(rec.get('owner') or '').strip())
        if not owner or owner == 'anonymous':
            continue
        path = str(rec.get('path') or '').strip()
        if path:
            _file_library_legacy_add_owner(by_path, _file_library_legacy_path_key(path), owner)
        filename = str(rec.get('filename') or os.path.basename(path) or '').strip()
        namespace = str(rec.get('namespace') or '').strip().lower()
        if namespace not in {'uploads', 'generated'}:
            namespace = 'generated' if 'generated' in _file_library_legacy_path_key(path) else 'uploads'
        scope = str(rec.get('scope') or '').strip().lower()
        _file_library_legacy_add_owner(by_file, _file_library_legacy_file_key(namespace, scope, filename), owner)
        _file_library_legacy_add_owner(by_file, _file_library_legacy_file_key(namespace, '', filename), owner)
    return by_path, by_file


def _file_library_legacy_url_parts(value: str = '') -> tuple[str, str, str]:
    raw = str(value or '').strip()
    if not raw:
        return '', '', ''
    try:
        parsed = urlparse(raw)
        path = urllib.parse.unquote(str(parsed.path or raw).split('?', 1)[0].split('#', 1)[0])
    except Exception:
        path = urllib.parse.unquote(raw.split('?', 1)[0].split('#', 1)[0])
    namespace = ''
    if '/api3/generated-download/' in path or '/api3/generated-files/' in path:
        namespace = 'generated'
    elif '/api3/download/' in path or '/api3/uploads/' in path:
        namespace = 'uploads'
    if not namespace:
        return '', '', ''
    extractor = globals().get('_extract_saved_filename_from_url')
    try:
        filename = str(extractor(raw) if callable(extractor) else os.path.basename(path) or '').strip()
    except Exception:
        filename = os.path.basename(path).strip()
    scope_fn = globals().get('_extract_upload_scope_from_url')
    try:
        scope = str(scope_fn(raw) if callable(scope_fn) else '').strip()
    except Exception:
        scope = ''
    return namespace, _normalize_upload_scope(scope) if scope else '', os.path.basename(filename)


def _file_library_legacy_owner_maps_from_chat_store() -> tuple[dict, dict]:
    by_path: dict[str, str] = {}
    by_file: dict[tuple[str, str, str], str] = {}
    state = globals().get('_AUTH_CHAT_STATE')
    lock = globals().get('_AUTH_CHAT_LOCK')
    normalizer = globals().get('_normalize_login_email')
    if not isinstance(state, dict):
        return by_path, by_file
    try:
        if lock is not None:
            with lock:
                accounts = dict(state.get('accounts') or {})
        else:
            accounts = dict(state.get('accounts') or {})
    except Exception:
        accounts = {}

    def norm_owner(raw: str = '') -> str:
        value = str(raw or '').strip().lower()
        if not value:
            return ''
        try:
            if callable(normalizer):
                value = str(normalizer(value) or value).strip().lower()
        except Exception:
            pass
        return value

    def add_from_url(raw_url: str = '', owner: str = '') -> None:
        namespace, scope, filename = _file_library_legacy_url_parts(raw_url)
        if not namespace or not filename:
            return
        _file_library_legacy_add_owner(by_file, _file_library_legacy_file_key(namespace, scope, filename), owner)
        _file_library_legacy_add_owner(by_file, _file_library_legacy_file_key(namespace, '', filename), owner)
        if scope:
            try:
                if namespace == 'generated':
                    root_fn = globals().get('_generated_dir_for_scope')
                else:
                    root_fn = globals().get('_upload_dir_for_scope')
                if callable(root_fn):
                    root = str(root_fn(scope, ensure=False) or '').strip()
                    if root:
                        _file_library_legacy_add_owner(by_path, _file_library_legacy_path_key(os.path.join(root, filename)), owner)
            except Exception:
                pass

    def walk(obj, owner: str, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(obj, str):
            if '/api3/' in obj:
                add_from_url(obj, owner)
            return
        if isinstance(obj, list):
            for item in obj[:2000]:
                walk(item, owner, depth + 1)
            return
        if not isinstance(obj, dict):
            return
        for key in ('url', 'download_url', 'view_url', 'preview_url', 'object_url'):
            raw_url = str(obj.get(key) or '').strip()
            if raw_url:
                add_from_url(raw_url, owner)
        registry = obj.get('file_registry') if isinstance(obj.get('file_registry'), dict) else obj
        if isinstance(registry, dict):
            filename = str(registry.get('saved_filename') or registry.get('filename') or '').strip()
            if filename:
                namespace = str(registry.get('namespace') or '').strip().lower()
                source = str(registry.get('source') or '').strip().lower()
                if namespace not in {'uploads', 'generated'}:
                    namespace = 'generated' if source == 'generated' else 'uploads'
                scope = str(registry.get('scope') or '').strip().lower()
                _file_library_legacy_add_owner(by_file, _file_library_legacy_file_key(namespace, scope, filename), owner)
                _file_library_legacy_add_owner(by_file, _file_library_legacy_file_key(namespace, '', filename), owner)
        for value in obj.values():
            if isinstance(value, (dict, list, str)):
                walk(value, owner, depth + 1)

    for email, rec in accounts.items():
        owner = norm_owner(email or (rec or {}).get('email') if isinstance(rec, dict) else email)
        if not owner:
            continue
        try:
            walk((rec or {}).get('store') if isinstance(rec, dict) else rec, owner)
        except Exception:
            continue
    return by_path, by_file


def _file_library_legacy_owner_maps_from_registry() -> tuple[dict, dict]:
    by_path: dict[str, str] = {}
    by_file: dict[tuple[str, str, str], str] = {}
    snapshot = globals().get('_file_registry_files_snapshot')
    files = snapshot() if callable(snapshot) else {}
    for rec in files.values():
        if not isinstance(rec, dict):
            continue
        owner = str(rec.get('owner_key') or rec.get('owner') or '').strip().lower()
        if not owner:
            continue
        for path in _file_library_path_candidates(rec):
            _file_library_legacy_add_owner(by_path, _file_library_legacy_path_key(path), owner)
        filename = str(rec.get('saved_filename') or rec.get('filename') or '').strip()
        if filename:
            namespace = str(rec.get('namespace') or '').strip().lower()
            source = str(rec.get('source') or '').strip().lower()
            if namespace not in {'uploads', 'generated'}:
                namespace = 'generated' if source == 'generated' else 'uploads'
            scope = str(rec.get('scope') or '').strip().lower()
            _file_library_legacy_add_owner(by_file, _file_library_legacy_file_key(namespace, scope, filename), owner)
            _file_library_legacy_add_owner(by_file, _file_library_legacy_file_key(namespace, '', filename), owner)
    return by_path, by_file


def _file_library_legacy_owner_maps() -> tuple[dict, dict]:
    by_path: dict[str, str] = {}
    by_file: dict[tuple[str, str, str], str] = {}
    for path_map, file_map in (
        _file_library_legacy_owner_maps_from_quota(),
        _file_library_legacy_owner_maps_from_registry(),
        _file_library_legacy_owner_maps_from_chat_store(),
    ):
        for k, v in (path_map or {}).items():
            _file_library_legacy_add_owner(by_path, k, v)
        for k, v in (file_map or {}).items():
            _file_library_legacy_add_owner(by_file, k, v)
    return by_path, by_file


def _file_library_legacy_resolve_owner(namespace: str, scope: str, path: str, filename: str, *, by_path: dict, by_file: dict) -> str:
    path_owner = by_path.get(_file_library_legacy_path_key(path))
    if path_owner:
        return path_owner
    for key in (
        _file_library_legacy_file_key(namespace, scope, filename),
        _file_library_legacy_file_key(namespace, '', filename),
        _file_library_legacy_file_key('', scope, filename),
        _file_library_legacy_file_key('', '', filename),
    ):
        owner = by_file.get(key)
        if owner:
            return owner
    return ''


def _file_library_legacy_existing_indexes() -> tuple[dict, dict, dict]:
    snapshot = globals().get('_file_registry_files_snapshot')
    files = snapshot() if callable(snapshot) else {}
    by_path: dict[str, str] = {}
    by_file: dict[tuple[str, str, str], str] = {}
    by_id: dict[str, dict] = {}
    for fid, rec in files.items():
        if not isinstance(rec, dict):
            continue
        rec_id = str(rec.get('file_id') or fid or '').strip()
        if not rec_id:
            continue
        by_id[rec_id] = dict(rec)
        namespace = str(rec.get('namespace') or '').strip().lower()
        source = str(rec.get('source') or '').strip().lower()
        if namespace not in {'uploads', 'generated'}:
            namespace = 'generated' if source == 'generated' else 'uploads'
        scope = str(rec.get('scope') or '').strip().lower()
        filename = str(rec.get('saved_filename') or rec.get('filename') or '').strip()
        if filename:
            by_file[_file_library_legacy_file_key(namespace, scope, filename)] = rec_id
        for path in _file_library_path_candidates(rec):
            by_path[_file_library_legacy_path_key(path)] = rec_id
    return by_path, by_file, by_id


def _file_library_legacy_should_skip_name(filename: str = '') -> bool:
    name = os.path.basename(str(filename or '').strip())
    low = name.lower()
    if not name or name in {'.', '..'}:
        return True
    if low.endswith(('.tmp', '.part', '.crdownload', '.download', '.uploading')):
        return True
    if low.startswith('.~') or low.startswith('~$'):
        return True
    return False


def _file_library_legacy_record_for_file(*, namespace: str, source: str, scope: str, path: str, filename: str, size: int, mtime: float, owner_key: str = '') -> dict:
    ext = _file_library_ext(filename)
    try:
        if namespace == 'generated':
            view_url, download_url = _build_generated_file_urls(filename, scope)
            storage_ref = ''
        else:
            view_url, download_url = _build_uploaded_file_urls(filename, scope)
            builder = globals().get('_build_upload_storage_ref')
            storage_ref = str(builder(filename, scope) if callable(builder) else '').strip()
    except Exception:
        view_url = download_url = storage_ref = ''
    content_hash = hashlib.sha256(f'legacy|{namespace}|{scope}|{filename}|{int(size or 0)}|{float(mtime or 0.0):.6f}'.encode('utf-8', errors='ignore')).hexdigest()[:16]
    fid_seed = f'{namespace}|{_normalize_upload_scope(scope)}|{filename}|{content_hash[:16]}'
    fid = hashlib.sha1(fid_seed.encode('utf-8', errors='ignore')).hexdigest()[:24]
    label = '历史生成文件' if namespace == 'generated' else '历史上传文件'
    rec = {
        'file_id': fid,
        'source': source or ('generated' if namespace == 'generated' else 'upload'),
        'namespace': namespace,
        'scope': _normalize_upload_scope(scope),
        'filename': filename,
        'saved_filename': filename,
        'ext': ext,
        'size': int(size or 0),
        'url': download_url or view_url,
        'view_url': view_url,
        'download_url': download_url or view_url,
        'storage_ref': storage_ref,
        'summary': f'{label}《{os.path.basename(filename or "file")}》已补登记，可在上传文件库管理。'[:900],
        'symbols': [],
        'preview': '',
        'chunks': [],
        'is_code_like': bool(globals().get('_file_registry_is_code_like') and _file_registry_is_code_like(filename, ext)),
        'content_hash': content_hash,
        'legacy_imported': True,
        'legacy_imported_at': time.time(),
        'created_at': float(mtime or time.time()),
        'updated_at': float(mtime or time.time()),
    }
    owner = str(owner_key or '').strip().lower()
    if owner:
        rec['owner_key'] = owner
    return rec


def _file_library_sync_legacy_files(force: bool = False) -> dict:
    if not _file_library_legacy_sync_enabled():
        return {'ok': True, 'skipped': True, 'reason': 'disabled'}
    now = time.time()
    interval = _file_library_legacy_sync_interval_s()
    with _FILE_LIBRARY_LEGACY_SYNC_LOCK:
        last_at = float(_FILE_LIBRARY_LEGACY_SYNC_STATE.get('last_at') or 0.0)
        if not force and last_at > 0 and now - last_at < interval:
            last = dict(_FILE_LIBRARY_LEGACY_SYNC_STATE.get('last_result') or {})
            last.update({'ok': True, 'skipped': True, 'reason': 'interval', 'last_at': last_at})
            return last
        _FILE_LIBRARY_LEGACY_SYNC_STATE['last_at'] = now

    roots = _file_library_legacy_scan_roots()
    if not roots:
        result = {'ok': True, 'scanned': 0, 'added': 0, 'updated_owner': 0, 'roots': 0}
        with _FILE_LIBRARY_LEGACY_SYNC_LOCK:
            _FILE_LIBRARY_LEGACY_SYNC_STATE['last_result'] = result
        return result

    by_owner_path, by_owner_file = _file_library_legacy_owner_maps()
    existing_by_path, existing_by_file, existing_by_id = _file_library_legacy_existing_indexes()
    max_files = _file_library_legacy_sync_max_files()
    scanned = 0
    added = 0
    updated_owner = 0
    quota_registered = 0
    errors: list[str] = []
    new_records: dict[str, dict] = {}
    owner_updates: dict[str, str] = {}

    for root_info in roots:
        if scanned >= max_files:
            break
        namespace = str(root_info.get('namespace') or '').strip().lower()
        source = str(root_info.get('source') or '').strip().lower()
        scope = str(root_info.get('scope') or '').strip().lower()
        root = str(root_info.get('root') or '').strip()
        try:
            names = sorted(os.listdir(root))
        except Exception as e:
            errors.append(f'{os.path.basename(root) or root}: {type(e).__name__}')
            continue
        for name in names:
            if scanned >= max_files:
                break
            filename = os.path.basename(str(name or '').strip())
            if _file_library_legacy_should_skip_name(filename):
                continue
            if namespace == 'generated' and _file_library_is_generated_preview_name(filename):
                continue
            path = os.path.abspath(os.path.join(root, filename))
            try:
                if not os.path.isfile(path):
                    continue
                st = os.stat(path)
                size = int(st.st_size or 0)
                if size <= 0:
                    continue
                mtime = float(st.st_mtime or now)
            except Exception as e:
                errors.append(f'{filename}: {type(e).__name__}')
                continue
            scanned += 1
            owner = _file_library_legacy_resolve_owner(namespace, scope, path, filename, by_path=by_owner_path, by_file=by_owner_file)
            existing_id = existing_by_path.get(_file_library_legacy_path_key(path)) or existing_by_file.get(_file_library_legacy_file_key(namespace, scope, filename)) or existing_by_file.get(_file_library_legacy_file_key(namespace, '', filename))
            if existing_id:
                rec = existing_by_id.get(existing_id) or {}
                if owner and not str(rec.get('owner_key') or rec.get('owner') or '').strip():
                    owner_updates[existing_id] = owner
                    updated_owner += 1
                continue
            rec = _file_library_legacy_record_for_file(namespace=namespace, source=source, scope=scope, path=path, filename=filename, size=size, mtime=mtime, owner_key=owner)
            fid = str(rec.get('file_id') or '').strip()
            if not fid:
                continue
            new_records[fid] = rec
            existing_by_id[fid] = rec
            existing_by_path[_file_library_legacy_path_key(path)] = fid
            existing_by_file[_file_library_legacy_file_key(namespace, scope, filename)] = fid
            added += 1
            if owner:
                try:
                    registrar = globals().get('_storage_quota_register_file')
                    if callable(registrar):
                        registrar(owner_key=owner, namespace=namespace, scope=scope, path=path, size_bytes=size, filename=filename)
                        quota_registered += 1
                except Exception:
                    pass

    if new_records or owner_updates:
        loader = globals().get('_file_registry_load')
        saver = globals().get('_file_registry_save')
        state = globals().get('_FILE_REGISTRY_STATE')
        lock = globals().get('_FILE_REGISTRY_LOCK')
        if callable(loader):
            try:
                loader()
            except Exception:
                pass
        if lock is not None and isinstance(state, dict):
            try:
                with lock:
                    files = dict(state.get('files') or {}) if isinstance(state.get('files'), dict) else {}
                    for fid, owner in owner_updates.items():
                        row = dict(files.get(fid) or {})
                        if row and not str(row.get('owner_key') or row.get('owner') or '').strip():
                            row['owner_key'] = owner
                            row['legacy_owner_recovered'] = True
                            row['updated_at'] = float(row.get('updated_at') or row.get('created_at') or now)
                            files[fid] = row
                    files.update(new_records)
                    state['files'] = files
                    state['updated_at'] = time.time()
                if callable(saver):
                    saver()
            except Exception as e:
                errors.append(f'registry_save:{type(e).__name__}')

    result = {
        'ok': True,
        'roots': len(roots),
        'scanned': scanned,
        'added': added,
        'updated_owner': updated_owner,
        'quota_registered': quota_registered,
        'max_files': max_files,
        'truncated': scanned >= max_files,
        'errors': errors[:12],
        'ran_at': now,
    }
    try:
        app_logger.info('[file_library_legacy_sync] scanned=%s added=%s updated_owner=%s quota_registered=%s truncated=%s', scanned, added, updated_owner, quota_registered, bool(result.get('truncated')))
    except Exception:
        pass
    with _FILE_LIBRARY_LEGACY_SYNC_LOCK:
        _FILE_LIBRARY_LEGACY_SYNC_STATE['last_result'] = result
    return result

def _file_library_registry_snapshot(owner_key: str | None = None) -> list[dict]:
    owner = _file_library_owner_key(owner_key)
    rows: list[dict] = []
    snapshot = globals().get('_file_registry_files_snapshot')
    files = snapshot() if callable(snapshot) else {}
    for rec in files.values():
        if not isinstance(rec, dict):
            continue
        if not _file_library_record_allowed_for_owner(rec, owner):
            continue
        namespace = str(rec.get('namespace') or '').strip().lower()
        source = str(rec.get('source') or '').strip().lower()
        if namespace not in {'uploads', 'generated'} and source not in {'upload', 'generated', 'pullback'}:
            continue
        if _file_library_is_generated_preview_record(rec):
            continue
        rows.append(dict(rec))
    return rows


def _file_library_safe_local_path_candidate(path: str = '', *, require_exists: bool = True) -> str:
    raw = str(path or '').strip()
    if not raw:
        return ''
    try:
        candidate = os.path.abspath(os.path.expanduser(raw))
    except Exception:
        return ''
    roots: list[str] = []
    for name in ('UPLOAD_DIR_LOCAL', 'UPLOAD_DIR_PUBLIC', 'GENERATED_DIR_LOCAL', 'GENERATED_DIR_PUBLIC'):
        root = str(globals().get(name) or '').strip()
        if not root:
            continue
        try:
            roots.append(os.path.abspath(root))
        except Exception:
            pass
    if not roots:
        return ''
    if os.path.exists(candidate) and not os.path.isfile(candidate):
        return ''
    if require_exists and not os.path.isfile(candidate):
        return ''
    for root in roots:
        try:
            if candidate != root and candidate.startswith(root + os.sep):
                return candidate
        except Exception:
            continue
    return ''


def _file_library_path_candidates(rec: dict | None = None) -> list[str]:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    out: list[str] = []

    def push(path: str = '', *, require_exists: bool = False) -> None:
        safe = _file_library_safe_local_path_candidate(path, require_exists=require_exists)
        if safe and safe not in out:
            out.append(safe)

    storage_ref = str(row.get('storage_ref') or '').strip()
    if storage_ref.startswith('upload://'):
        scope = ''
        filename = ''
        parser = globals().get('_parse_upload_storage_ref')
        if callable(parser):
            try:
                scope, filename = parser(storage_ref)
            except Exception:
                scope, filename = '', ''
        if filename:
            try:
                base = globals().get('_upload_dir_for_scope')
                if callable(base):
                    upload_base = base(scope or None, ensure=True)
                    push(os.path.join(upload_base, filename), require_exists=False)
            except Exception:
                pass
        resolver = globals().get('_upload_storage_ref_to_local_path')
        if callable(resolver):
            try:
                push(str(resolver(storage_ref) or '').strip(), require_exists=True)
            except Exception:
                pass

    resolver = globals().get('_history_file_resolve_path')
    if callable(resolver):
        try:
            push(str(resolver(row) or '').strip(), require_exists=True)
        except Exception:
            pass

    namespace = str(row.get('namespace') or '').strip().lower()
    source = str(row.get('source') or '').strip().lower()
    saved_values: list[tuple[str, str]] = []

    def push_saved(name: str = '', scope: str = '') -> None:
        value = str(name or '').strip()
        if not value:
            return
        pair = (value, str(scope or '').strip())
        if pair not in saved_values:
            saved_values.append(pair)

    push_saved(row.get('saved_filename') or row.get('filename') or '', row.get('scope') or '')
    extractor = globals().get('_extract_saved_filename_from_url')
    scope_from_url = globals().get('_extract_upload_scope_from_url')
    for key in ('download_url', 'view_url', 'url', 'preview_url'):
        raw_url = str(row.get(key) or '').strip()
        if not raw_url:
            continue
        try:
            filename = str(extractor(raw_url) if callable(extractor) else os.path.basename(urlparse(raw_url).path or '') or '').strip()
        except Exception:
            filename = ''
        try:
            scope = str(scope_from_url(raw_url) if callable(scope_from_url) else '').strip()
        except Exception:
            scope = ''
        push_saved(filename, scope or str(row.get('scope') or '').strip())

    upload_dir_for_scope = globals().get('_upload_dir_for_scope')
    generated_dir_for_scope = globals().get('_generated_dir_for_scope')
    for saved, scope in saved_values:
        try:
            if namespace == 'generated' or source == 'generated':
                if callable(generated_dir_for_scope):
                    push(os.path.join(generated_dir_for_scope(scope or None, ensure=True), saved), require_exists=False)
            else:
                if callable(upload_dir_for_scope):
                    push(os.path.join(upload_dir_for_scope(scope or None, ensure=True), saved), require_exists=False)
        except Exception:
            pass
        # Scope can be missing or stale in old records; try both upload scopes as safe fallbacks.
        for fallback_scope in ('local', 'public'):
            try:
                if namespace == 'generated' or source == 'generated':
                    if callable(generated_dir_for_scope):
                        push(os.path.join(generated_dir_for_scope(fallback_scope, ensure=True), saved), require_exists=False)
                else:
                    if callable(upload_dir_for_scope):
                        push(os.path.join(upload_dir_for_scope(fallback_scope, ensure=True), saved), require_exists=False)
            except Exception:
                pass
    return out


def _file_library_preview_path_candidates_for_record(rec: dict | None = None) -> list[str]:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    namespace = str(row.get('namespace') or '').strip().lower()
    source = str(row.get('source') or '').strip().lower()
    if namespace != 'generated' and source != 'generated':
        return []
    if _file_library_is_generated_preview_record(row):
        return []
    filename = str(row.get('saved_filename') or row.get('filename') or '').strip()
    ext = _file_library_ext(filename, row.get('ext') or '')
    if _file_library_category(filename, ext) != 'image':
        return []

    preview_names: list[str] = []

    def push_name(value: str = '') -> None:
        name = os.path.basename(str(value or '').strip())
        if name and _file_library_is_generated_preview_name(name) and name not in preview_names:
            preview_names.append(name)

    push_name(row.get('preview_filename') or '')
    push_name(_file_library_preview_name_for_original(filename))

    extractor = globals().get('_extract_saved_filename_from_url')
    for key in ('preview_url', 'preview_download_url'):
        raw_url = str(row.get(key) or '').strip()
        if not raw_url:
            continue
        try:
            push_name(str(extractor(raw_url) if callable(extractor) else os.path.basename(urlparse(raw_url).path or '') or ''))
        except Exception:
            pass

    out: list[str] = []

    def push_path(path: str = '') -> None:
        safe = _file_library_safe_local_path_candidate(path, require_exists=True)
        if safe and safe not in out:
            out.append(safe)

    for name in preview_names:
        fake = dict(row)
        fake['filename'] = name
        fake['saved_filename'] = name
        fake['ext'] = _file_library_ext(name)
        fake['view_url'] = ''
        fake['download_url'] = ''
        fake['url'] = ''
        fake['preview_url'] = ''
        for path in _file_library_path_candidates(fake):
            push_path(path)

    for key in ('preview_url', 'preview_download_url'):
        raw_url = str(row.get(key) or '').strip()
        if not raw_url:
            continue
        fake = dict(row)
        fake['filename'] = ''
        fake['saved_filename'] = ''
        fake['view_url'] = raw_url
        fake['download_url'] = raw_url
        fake['url'] = raw_url
        fake['preview_url'] = raw_url
        for path in _file_library_path_candidates(fake):
            push_path(path)

    return out


def _file_library_preview_registry_ids_for_record(rec: dict | None = None, owner_key: str | None = None) -> list[str]:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    namespace = str(row.get('namespace') or '').strip().lower()
    source = str(row.get('source') or '').strip().lower()
    if namespace != 'generated' and source != 'generated':
        return []
    if _file_library_is_generated_preview_record(row):
        return []
    owner = _file_library_owner_key(owner_key)
    preview_names: set[str] = set()

    def add_name(value: str = '') -> None:
        name = os.path.basename(str(value or '').strip())
        if name and _file_library_is_generated_preview_name(name):
            preview_names.add(name.lower())

    add_name(row.get('preview_filename') or '')
    add_name(_file_library_preview_name_for_original(str(row.get('saved_filename') or row.get('filename') or '')))
    extractor = globals().get('_extract_saved_filename_from_url')
    for key in ('preview_url', 'preview_download_url'):
        raw_url = str(row.get(key) or '').strip()
        if not raw_url:
            continue
        try:
            add_name(str(extractor(raw_url) if callable(extractor) else os.path.basename(urlparse(raw_url).path or '') or ''))
        except Exception:
            pass

    preview_paths = {_file_library_legacy_path_key(p) for p in _file_library_preview_path_candidates_for_record(row)}
    if not preview_names and not preview_paths:
        return []

    snapshot = globals().get('_file_registry_files_snapshot')
    files = snapshot() if callable(snapshot) else {}

    ids: list[str] = []
    for fid, item in files.items():
        if not isinstance(item, dict):
            continue
        if not _file_library_record_allowed_for_owner(item, owner):
            continue
        if not _file_library_is_generated_preview_record(item):
            continue
        names = {
            os.path.basename(str(item.get('saved_filename') or '').strip()).lower(),
            os.path.basename(str(item.get('filename') or '').strip()).lower(),
        }
        matched = bool(preview_names.intersection({x for x in names if x}))
        if not matched and preview_paths:
            try:
                for path in _file_library_path_candidates(item):
                    if _file_library_legacy_path_key(path) in preview_paths:
                        matched = True
                        break
            except Exception:
                matched = False
        if matched:
            rec_id = str(item.get('file_id') or fid or '').strip()
            if rec_id and rec_id not in ids:
                ids.append(rec_id)
    return ids


def _file_library_prune_storage_quota_index_quietly() -> None:
    try:
        loader = globals().get('_storage_quota_load_owner_index')
        pruner = globals().get('_storage_quota_prune_owner_index_locked')
        saver = globals().get('_storage_quota_save_owner_index')
        lock = globals().get('_STORAGE_QUOTA_LOCK')
        if not (callable(loader) and callable(pruner) and callable(saver)):
            return
        if lock is not None:
            with lock:
                data = loader() or {}
                data, changed = pruner(data)
                if changed:
                    saver(data)
        else:
            data = loader() or {}
            data, changed = pruner(data)
            if changed:
                saver(data)
    except Exception:
        pass


def _file_library_resolve_local_path(rec: dict | None = None) -> str:
    for path in _file_library_path_candidates(rec):
        safe = _file_library_safe_local_path_candidate(path, require_exists=True)
        if safe:
            return safe
    return ''


def _file_library_kb_ref_count(rec: dict | None = None, owner_key: str | None = None) -> int:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    owner = _file_library_owner_key(owner_key)
    values: list[tuple[str, str]] = []
    local_path = _file_library_resolve_local_path(row)
    if local_path:
        values.append(('file_path', local_path))
    for key in ('download_url', 'view_url', 'url'):
        v = str(row.get(key) or '').strip()
        if v:
            values.append(('download_url', v))
            values.append(('view_url', v))
    # de-dupe
    seen = set()
    clean = []
    for k, v in values:
        pair = (k, v)
        if pair not in seen:
            seen.add(pair)
            clean.append(pair)
    if not clean:
        return 0
    try:
        _kb_db_ensure()
        conn = _kb_db_connect()
        try:
            total = 0
            for key, value in clean:
                try:
                    row_count = conn.execute(f'SELECT COUNT(1) AS c FROM kb_documents WHERE owner_key=? AND {key}=?', (owner, value)).fetchone()
                    if row_count is not None:
                        total += int((dict(row_count) if not isinstance(row_count, dict) else row_count).get('c') or row_count[0] or 0)
                except Exception:
                    continue
            return int(total)
        finally:
            conn.close()
    except Exception:
        return 0


def _file_library_public_record(rec: dict | None = None, owner_key: str | None = None) -> dict:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    filename = str(row.get('filename') or row.get('saved_filename') or '').strip()
    saved = str(row.get('saved_filename') or filename).strip()
    ext = _file_library_ext(filename or saved, row.get('ext') or '')
    category = _file_library_category(filename or saved, ext)
    view_url = str(row.get('view_url') or row.get('url') or row.get('download_url') or '').strip()
    download_url = str(row.get('download_url') or row.get('url') or view_url).strip()
    preview_url = str(row.get('preview_url') or row.get('preview_download_url') or '').strip()
    if not preview_url and category == 'image':
        preview_url = view_url
    preview_download_url = str(row.get('preview_download_url') or preview_url or '').strip()
    storage_ref = str(row.get('storage_ref') or '').strip()
    model_storage_ref = storage_ref if storage_ref.startswith('upload://') else ''
    if not model_storage_ref and category == 'image':
        model_storage_ref = view_url or download_url or preview_url
    try:
        updated_ts = float(row.get('updated_at') or row.get('created_at') or 0.0)
    except Exception:
        updated_ts = 0.0
    kb_count = _file_library_kb_ref_count(row, owner_key=owner_key)
    kb_importable = _file_library_kb_importable(row)
    return {
        'file_id': str(row.get('file_id') or '').strip(),
        'filename': filename or saved or '未命名文件',
        'saved_filename': saved,
        'ext': ext,
        'category': category,
        'size': int(row.get('size') or 0),
        'source': str(row.get('source') or '').strip(),
        'namespace': str(row.get('namespace') or '').strip(),
        'scope': str(row.get('scope') or '').strip(),
        'view_url': view_url,
        'download_url': download_url,
        'url': str(row.get('url') or download_url or view_url).strip(),
        'storage_ref': storage_ref,
        'model_storage_ref': model_storage_ref,
        'preview_url': preview_url if category == 'image' else '',
        'preview_download_url': preview_download_url if category == 'image' else '',
        'preview_filename': str(row.get('preview_filename') or '').strip(),
        'preview_size': int(row.get('preview_size') or 0),
        'preview_mime': str(row.get('preview_mime') or '').strip(),
        'summary': truncate_text(str(row.get('summary') or ''), max_chars=280),
        'is_code_like': bool(row.get('is_code_like')),
        'full_text_available': bool(row.get('full_text_available') or row.get('full_text_ref')),
        'updated_ts': updated_ts,
        'kb_doc_count': kb_count,
        'joined_kb': bool(kb_count > 0 and kb_importable),
        'kb_importable': kb_importable,
        'kb_import_block_reason': '' if kb_importable else '图片只保留在资料库，不加入知识库',
    }


def _file_library_state(
    owner_key: str | None = None,
    *,
    category: str = '',
    filter_text: str = '',
    sort: str = 'updated_desc',
    offset: int = 0,
    limit: int = 1000,
) -> dict:
    owner = _file_library_owner_key(owner_key)
    legacy_sync = {}
    try:
        legacy_sync = _file_library_sync_legacy_files(force=False)
    except Exception as e:
        legacy_sync = {'ok': False, 'error': f'{type(e).__name__}: {e}'}
    records = _file_library_registry_snapshot(owner)
    files = [_file_library_public_record(rec, owner_key=owner) for rec in records]
    seen_ids = set()
    deduped = []
    for item in sorted(files, key=lambda x: float((x or {}).get('updated_ts') or 0.0), reverse=True):
        fid = str((item or {}).get('file_id') or '').strip()
        if fid and fid in seen_ids:
            continue
        if fid:
            seen_ids.add(fid)
        deduped.append(item)

    total_size = sum(int((item or {}).get('size') or 0) for item in deduped)
    images = sum(1 for item in deduped if str((item or {}).get('category') or '') == 'image')

    category_filter = str(category or '').strip().lower()
    if category_filter not in {'image', 'file'}:
        category_filter = 'all'
    query = re.sub(r'\s+', ' ', str(filter_text or '').strip()).lower()
    sort_key = str(sort or 'updated_desc').strip().lower() or 'updated_desc'

    filtered = deduped
    if category_filter in {'image', 'file'}:
        filtered = [item for item in filtered if str((item or {}).get('category') or '').strip().lower() == category_filter]
    if query:
        def _match(item: dict) -> bool:
            haystack = ' '.join([
                str(item.get('filename') or ''),
                str(item.get('saved_filename') or ''),
                str(item.get('ext') or ''),
                str(item.get('source') or ''),
                str(item.get('namespace') or ''),
                str(item.get('summary') or ''),
            ]).lower()
            return query in haystack
        filtered = [item for item in filtered if isinstance(item, dict) and _match(item)]

    if sort_key == 'name_asc':
        filtered.sort(key=lambda item: (str((item or {}).get('filename') or (item or {}).get('saved_filename') or '').lower(), -float((item or {}).get('updated_ts') or 0.0)))
    elif sort_key == 'size_desc':
        filtered.sort(key=lambda item: (-int((item or {}).get('size') or 0), -float((item or {}).get('updated_ts') or 0.0)))
    else:
        sort_key = 'updated_desc'
        filtered.sort(key=lambda item: -float((item or {}).get('updated_ts') or 0.0))

    try:
        offset_i = max(0, int(offset or 0))
    except Exception:
        offset_i = 0
    try:
        limit_i = max(1, min(int(limit or 1000), 1000))
    except Exception:
        limit_i = 1000
    filtered_total = len(filtered)
    page_files = filtered[offset_i:offset_i + limit_i]
    next_offset = offset_i + len(page_files)

    return {
        'ok': True,
        'owner_key': owner,
        'legacy_sync': legacy_sync if isinstance(legacy_sync, dict) else {},
        'files': page_files,
        'page': {
            'offset': offset_i,
            'limit': limit_i,
            'returned': len(page_files),
            'filtered_total': filtered_total,
            'has_more': next_offset < filtered_total,
            'next_offset': next_offset,
            'type': category_filter,
            'sort': sort_key,
            'filter': query,
        },
        'stats': {
            'total': len(deduped),
            'filtered_total': filtered_total,
            'images': images,
            'files': max(0, len(deduped) - images),
            'total_size': total_size,
            'joined_kb': sum(1 for item in deduped if bool((item or {}).get('joined_kb'))),
        },
    }


def _file_library_get_record(file_id: str = '', owner_key: str | None = None) -> dict:
    fid = str(file_id or '').strip()
    if not fid:
        return {}
    owner = _file_library_owner_key(owner_key)
    snapshot = globals().get('_file_registry_files_snapshot')
    files = snapshot() if callable(snapshot) else {}
    rec = dict((files or {}).get(fid) or {})
    if not rec or not _file_library_record_allowed_for_owner(rec, owner):
        return {}
    return rec


def _file_library_remove_registry_record(file_id: str = '') -> dict:
    fid = str(file_id or '').strip()
    loader = globals().get('_file_registry_load')
    saver = globals().get('_file_registry_save')
    state = globals().get('_FILE_REGISTRY_STATE')
    lock = globals().get('_FILE_REGISTRY_LOCK')
    if not fid or lock is None or not isinstance(state, dict):
        return {'removed': 0}
    if callable(loader):
        try:
            loader()
        except Exception:
            pass
    removed = {}
    try:
        with lock:
            files = dict(state.get('files') or {}) if isinstance(state.get('files'), dict) else {}
            removed = dict(files.pop(fid, {}) or {})
            if removed:
                state['files'] = files
                state['updated_at'] = time.time()
    except Exception as e:
        return {'removed': 0, 'error': f'{type(e).__name__}: {e}'}
    if removed and callable(saver):
        try:
            saver()
        except Exception:
            pass
    ref = str(removed.get('full_text_ref') or '').strip() if isinstance(removed, dict) else ''
    full_text_removed = False
    if ref:
        # Only remove full text if no other registry record still references it.
        still_used = False
        try:
            with lock:
                for item in ((state.get('files') or {}) if isinstance(state.get('files'), dict) else {}).values():
                    if isinstance(item, dict) and str(item.get('full_text_ref') or '').strip() == ref:
                        still_used = True
                        break
        except Exception:
            still_used = True
        if not still_used and callable(globals().get('_file_text_store_path')):
            try:
                fp = str(_file_text_store_path(ref) or '').strip()
                if fp and os.path.isfile(fp):
                    os.remove(fp)
                    full_text_removed = True
            except Exception:
                pass
    return {'removed': 1 if removed else 0, 'full_text_removed': full_text_removed}


def _file_library_sandbox_root() -> str:
    raw = globals().get('SANDBOX_ROOT_DIR') or _app_data_path('sandboxes')
    return os.path.abspath(str(raw or _app_data_path('sandboxes')))


def _file_library_sandbox_source_abs(source: dict | None = None) -> str:
    src = dict(source or {}) if isinstance(source, dict) else {}
    root_rel = str(src.get('sandbox_root_rel') or '').strip().replace('\\', '/').strip('/')
    rel = str(src.get('path') or '').strip().replace('\\', '/').strip('/')
    if not root_rel or not rel:
        return ''
    if root_rel.startswith('/') or rel.startswith('/') or '..' in root_rel.split('/') or '..' in rel.split('/'):
        return ''
    root = _file_library_sandbox_root()
    target = os.path.abspath(os.path.join(root, *[p for p in (root_rel + '/' + rel).split('/') if p]))
    if not (target == root or target.startswith(root + os.sep)):
        return ''
    return target


def _file_library_sandbox_source_records(rec: dict | None = None) -> list[dict]:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    if str(row.get('sandbox_cleanup_policy') or '').strip() != 'delete_with_file_library':
        return []
    rows: list[dict] = []
    seen: set[str] = set()
    for src in (row.get('sandbox_source_files') or []):
        if not isinstance(src, dict):
            continue
        path = _file_library_sandbox_source_abs(src)
        if not path:
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        rows.append({**src, 'abs_path': path})
    return rows


def _file_library_sandbox_source_still_referenced(source: dict | None = None, *, skip_file_ids: set[str] | None = None, owner_key: str | None = None) -> bool:
    target = os.path.normcase(os.path.abspath(str((source or {}).get('abs_path') or _file_library_sandbox_source_abs(source) or '')))
    if not target:
        return False
    skip = {str(x or '').strip() for x in (skip_file_ids or set()) if str(x or '').strip()}
    snapshot = globals().get('_file_registry_files_snapshot')
    files = snapshot() if callable(snapshot) else {}
    for fid, item in files.items():
        if not isinstance(item, dict):
            continue
        rec_id = str(item.get('file_id') or fid or '').strip()
        if rec_id and rec_id in skip:
            continue
        for src in _file_library_sandbox_source_records(item):
            other = os.path.normcase(os.path.abspath(str(src.get('abs_path') or '')))
            if other and other == target:
                return True
    return False


def _file_library_sandbox_remove_empty_parents(path: str = '') -> int:
    root = _file_library_sandbox_root()
    cur = os.path.abspath(os.path.dirname(str(path or '')))
    removed = 0
    while cur and cur != root and cur.startswith(root + os.sep):
        try:
            if os.path.isdir(cur) and not os.listdir(cur):
                os.rmdir(cur)
                removed += 1
                cur = os.path.dirname(cur)
                continue
        except Exception:
            break
        break
    return removed


def _file_library_delete_sandbox_sources(rec: dict | None = None, *, skip_file_ids: set[str] | None = None, owner_key: str | None = None) -> dict:
    policy = str((rec or {}).get('sandbox_cleanup_policy') or '').strip()
    sources = _file_library_sandbox_source_records(rec)
    out = {
        'policy': policy,
        'deleted': [],
        'skipped': [],
        'deleted_count': 0,
        'freed_bytes': 0,
        'freed_text': '0B',
        'empty_dirs_removed': 0,
    }
    if policy != 'delete_with_file_library':
        out['skipped'].append({'reason': 'cleanup_policy_not_enabled'})
        return out
    if not sources:
        out['skipped'].append({'reason': 'no_sandbox_source_files'})
        return out
    for src in sources:
        path = str(src.get('abs_path') or '').strip()
        if not path:
            out['skipped'].append({'source': src, 'reason': 'invalid_sandbox_source'})
            continue
        if _file_library_sandbox_source_still_referenced(src, skip_file_ids=skip_file_ids, owner_key=owner_key):
            out['skipped'].append({'path': path, 'reason': 'referenced_by_other_file_library_record'})
            continue
        if not os.path.exists(path):
            out['skipped'].append({'path': path, 'reason': 'source_not_found'})
            continue
        if not os.path.isfile(path) or os.path.islink(path):
            out['skipped'].append({'path': path, 'reason': 'source_not_regular_file'})
            continue
        try:
            size = int(os.path.getsize(path) or 0)
            os.remove(path)
            out['deleted'].append({'path': path, 'size_bytes': size, 'size_text': _storage_quota_human(size) if callable(globals().get('_storage_quota_human')) else str(size)})
            out['freed_bytes'] += max(0, size)
            out['empty_dirs_removed'] += _file_library_sandbox_remove_empty_parents(path)
        except Exception as e:
            out['skipped'].append({'path': path, 'reason': 'delete_failed', 'error': f'{type(e).__name__}: {e}'})
    out['deleted_count'] = len(out['deleted'])
    out['freed_text'] = _storage_quota_human(out['freed_bytes']) if callable(globals().get('_storage_quota_human')) else str(out['freed_bytes'])
    return out


def _file_library_object_storage_delete_candidates(rec: dict | None = None) -> list[dict]:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    namespace = str(row.get('namespace') or '').strip().lower()
    source = str(row.get('source') or '').strip().lower()
    if namespace not in {'uploads', 'generated'}:
        namespace = 'generated' if source == 'generated' else 'uploads'
    scope = str(row.get('scope') or '').strip().lower()
    try:
        normalizer = globals().get('_normalize_upload_scope')
        scope = str(normalizer(scope) if callable(normalizer) else scope).strip().lower()
    except Exception:
        pass
    candidates: list[tuple[str, str]] = []

    def push_name(value: str = '', cand_scope: str = '') -> None:
        name = os.path.basename(str(value or '').strip())
        sc = str(cand_scope or scope or '').strip().lower() or 'local'
        pair = (name, sc)
        if name and pair not in candidates:
            candidates.append(pair)

    push_name(row.get('saved_filename') or row.get('filename') or '')
    storage_ref = str(row.get('storage_ref') or '').strip()
    if storage_ref.startswith('upload://'):
        parser = globals().get('_parse_upload_storage_ref')
        try:
            ref_scope, ref_filename = parser(storage_ref) if callable(parser) else ('', '')
        except Exception:
            ref_scope, ref_filename = '', ''
        push_name(ref_filename, ref_scope)
    scope_from_url = globals().get('_extract_upload_scope_from_url')
    for key in ('download_url', 'view_url', 'url', 'preview_url', 'preview_download_url'):
        raw_url = str(row.get(key) or '').strip()
        if not raw_url:
            continue
        try:
            extractor = globals().get('_extract_saved_filename_from_url')
            name = str(extractor(raw_url) if callable(extractor) else os.path.basename(urlparse(raw_url).path or '') or '')
            url_scope = str(scope_from_url(raw_url) if callable(scope_from_url) else '').strip().lower()
            push_name(name, url_scope)
        except Exception:
            pass
    if namespace == 'generated' or source == 'generated':
        push_name(row.get('preview_filename') or '')
        push_name(_file_library_preview_name_for_original(str(row.get('saved_filename') or row.get('filename') or '')))
    return [{'namespace': namespace, 'scope': cand_scope or 'local', 'filename': name} for name, cand_scope in candidates]


def _file_library_delete_object_storage(rec: dict | None = None) -> dict:
    deleter = globals().get('_object_storage_delete_file')
    candidates = _file_library_object_storage_delete_candidates(rec)
    out = {'deleted': [], 'skipped': [], 'deleted_count': 0}
    if not callable(deleter):
        out['skipped'].append({'reason': 'object_storage_deleter_unavailable', 'count': len(candidates)})
        return out
    for item in candidates:
        namespace = str(item.get('namespace') or '').strip()
        scope = str(item.get('scope') or '').strip()
        filename = str(item.get('filename') or '').strip()
        if not filename:
            continue
        try:
            if deleter(namespace, scope, filename):
                out['deleted'].append({'namespace': namespace, 'scope': scope, 'filename': filename})
            else:
                out['skipped'].append({'namespace': namespace, 'scope': scope, 'filename': filename, 'reason': 'not_enabled_or_not_deleted'})
        except Exception as e:
            out['skipped'].append({'namespace': namespace, 'scope': scope, 'filename': filename, 'reason': 'delete_failed', 'error': f'{type(e).__name__}: {e}'})
    out['deleted_count'] = len(out['deleted'])
    return out


def _file_library_delete_file(file_id: str = '', owner_key: str | None = None) -> dict:
    owner = _file_library_owner_key(owner_key)
    rec = _file_library_get_record(file_id, owner)
    if not rec:
        raise ValueError('文件不存在或无权删除')
    kb_refs = _file_library_kb_ref_count(rec, owner_key=owner)
    if kb_refs > 0:
        raise ValueError('这个文件已加入知识库，请先在知识库里删除对应文档')
    candidates = _file_library_path_candidates(rec)
    for preview_path in _file_library_preview_path_candidates_for_record(rec):
        if preview_path not in candidates:
            candidates.append(preview_path)
    preview_registry_ids = _file_library_preview_registry_ids_for_record(rec, owner_key=owner)
    registry_records = {str(rec.get('file_id') or file_id): dict(rec)}
    for preview_id in preview_registry_ids:
        preview_rec = _file_library_get_record(preview_id, owner)
        if preview_rec:
            registry_records[str(preview_id)] = dict(preview_rec)
    selected_registry_ids = {str(value or '').strip() for value in registry_records if str(value or '').strip()}
    registry_snapshot = globals().get('_file_registry_files_snapshot')
    all_registry_records = registry_snapshot() if callable(registry_snapshot) else {}
    for selected_rec in registry_records.values():
        ref = str((selected_rec or {}).get('full_text_ref') or '').strip()
        if not ref or not callable(globals().get('_file_text_store_path')):
            continue
        shared = any(
            str(fid or '').strip() not in selected_registry_ids
            and isinstance(item, dict)
            and str(item.get('full_text_ref') or '').strip() == ref
            for fid, item in (all_registry_records or {}).items()
        )
        if shared:
            continue
        try:
            full_text_path = str(_file_text_store_path(ref) or '').strip()
            if full_text_path and full_text_path not in candidates:
                candidates.append(full_text_path)
        except Exception:
            pass
    sandbox_paths_for_recycle: list[str] = []
    if str(rec.get('sandbox_cleanup_policy') or '').strip() == 'delete_with_file_library':
        for source in _file_library_sandbox_source_records(rec):
            path = str(source.get('abs_path') or '').strip()
            if not path or not os.path.isfile(path) or os.path.islink(path):
                continue
            if _file_library_sandbox_source_still_referenced(source, skip_file_ids=selected_registry_ids, owner_key=owner):
                continue
            sandbox_paths_for_recycle.append(path)
            if path not in candidates:
                candidates.append(path)
    existing_paths = []
    seen_existing_paths = set()
    for p in candidates:
        if os.path.isfile(p):
            key = _file_library_legacy_path_key(p)
            if key not in seen_existing_paths:
                seen_existing_paths.add(key)
                existing_paths.append(p)
    deleted = []
    skipped = []
    recycle_result = {}
    if existing_paths:
        recycler = globals().get('_platform_admin_recycle_paths')
        if not callable(recycler):
            raise ValueError('回收站服务不可用，已取消删除')
        try:
            recycle_result = recycler(
                existing_paths,
                reason='用户从文件库删除',
                source_kind='file_library',
                display_name=str(rec.get('filename') or rec.get('saved_filename') or '文件'),
                restore_context={
                    'file_registry_records': registry_records,
                    'owner_key': owner,
                },
            )
            artifacts = list(((recycle_result.get('record') or {}).get('artifacts') or []))
            deleted = [
                {'path': str(item.get('original_path') or ''), 'size_bytes': int(item.get('size_bytes') or 0), 'recycled': True}
                for item in artifacts
                if isinstance(item, dict)
            ]
        except Exception as e:
            raise ValueError(f'移入回收站失败：{type(e).__name__}: {e}')
    else:
        # 旧记录/异常记录可能只剩 file_registry_store.json 索引，真实文件已经被旧清理、手动删除或过期清理移除。
        # 这种情况不应卡死用户删除；允许清理残留索引，但返回 skipped 说明没有物理文件可删。
        if candidates:
            skipped.extend({'path': p, 'reason': 'file_not_found'} for p in candidates[:8])
        else:
            skipped.append({'path': '', 'reason': 'no_local_path_candidate'})

    sandbox_cleanup = {
        'policy': str(rec.get('sandbox_cleanup_policy') or '').strip(),
        'deleted': [],
        'skipped': [],
        'deleted_count': 0,
        'freed_bytes': 0,
        'freed_text': '0B',
        'empty_dirs_removed': 0,
        'recycled_paths': sandbox_paths_for_recycle,
    }
    registry_ids = [str(rec.get('file_id') or file_id), *preview_registry_ids]
    remove_registry_records = globals().get('_file_registry_remove_records')
    if not callable(remove_registry_records):
        raise ValueError('文件索引批量删除服务不可用，已取消删除')
    try:
        registry = remove_registry_records(registry_ids)
    except Exception as e:
        cancel_recycle = globals().get('_platform_admin_recycle_cancel')
        recycle_id = str(((recycle_result.get('file') or {}).get('id') if isinstance(recycle_result, dict) else '') or '').strip()
        if callable(cancel_recycle) and recycle_id:
            cancel_recycle(recycle_id)
        raise ValueError(f'文件索引清理失败：{type(e).__name__}: {e}')
    removed_records = dict(registry.get('records') or {}) if isinstance(registry, dict) else {}
    primary_id = str(rec.get('file_id') or file_id)
    registry = {
        'removed': 1 if primary_id in removed_records else 0,
        'record': removed_records.get(primary_id) or {},
    }
    preview_registry = [
        {'file_id': preview_id, 'removed': 1, 'record': removed_records.get(preview_id) or {}}
        for preview_id in preview_registry_ids
        if preview_id != primary_id and preview_id in removed_records
    ]
    object_storage = _file_library_delete_object_storage(rec)
    _file_library_prune_storage_quota_index_quietly()
    return {'ok': True, 'file_id': str(file_id or ''), 'deleted': deleted, 'skipped': skipped, 'recycle': recycle_result.get('file') if isinstance(recycle_result, dict) else {}, 'object_storage': object_storage, 'sandbox_cleanup': sandbox_cleanup, 'registry': registry, 'preview_registry': preview_registry, 'state': _file_library_state(owner)}


def _file_library_import_to_kb(file_id: str = '', space_id: str = '', owner_key: str | None = None, *, include_state: bool = True) -> dict:
    owner = _file_library_owner_key(owner_key)
    rec = _file_library_get_record(file_id, owner)
    if not rec:
        raise ValueError('文件不存在或无权使用')
    if not _file_library_kb_importable(rec):
        raise ValueError('图片文件只保留在资料库，不能加入知识库')
    text = ''
    reader = globals().get('_history_file_read_text')
    try:
        if callable(reader):
            text = str(reader({**rec, 'registry_file_id': str(rec.get('file_id') or file_id)}) or '').strip()
    except Exception:
        text = ''
    if not text:
        fid = str(rec.get('file_id') or file_id)
        try:
            text = _file_registry_record_text_by_id(fid)
        except Exception:
            text = ''
    text = str(text or '').strip()
    if not text:
        raise ValueError('这个文件没有可入库的文本内容')
    path = _file_library_resolve_local_path(rec)
    payload = _kb_import_document(
        owner_key=owner,
        space_id=space_id,
        filename=str(rec.get('filename') or rec.get('saved_filename') or '上传文件'),
        ext=_file_library_ext(str(rec.get('filename') or rec.get('saved_filename') or ''), str(rec.get('ext') or '')),
        size_bytes=int(rec.get('size') or 0),
        file_path=path,
        download_url=str(rec.get('download_url') or rec.get('url') or '').strip(),
        view_url=str(rec.get('view_url') or rec.get('url') or '').strip(),
        text=text,
        note='从上传文件库加入知识库',
        source='file_library',
    )
    result = {**payload, 'file': _file_library_public_record(rec, owner_key=owner)}
    if include_state:
        result['file_library'] = _file_library_state(owner)
    return result



def _file_library_preview_text(file_id: str = '', owner_key: str | None = None, *, max_chars: int | None = None) -> dict:
    owner = _file_library_owner_key(owner_key)
    fid = str(file_id or '').strip()
    rec = _file_library_get_record(fid, owner)
    if not rec:
        raise ValueError('文件不存在或无权预览')
    filename = str(rec.get('filename') or rec.get('saved_filename') or '未命名文件').strip()
    ext = _file_library_ext(filename, str(rec.get('ext') or ''))
    category = _file_library_category(filename, ext)
    if category == 'image':
        raise ValueError('图片请直接打开预览')
    try:
        limit = int(max_chars if max_chars is not None else str(app_getenv('FILE_LIBRARY_PREVIEW_MAX_CHARS', '60000') or '60000'))
    except Exception:
        limit = 60000
    limit = max(1000, min(limit, 200000))
    text = ''
    try:
        text = str(_history_file_read_text({**rec, 'registry_file_id': fid}) or '').strip()
    except Exception:
        text = ''
    if not text:
        try:
            text = str(_file_registry_record_text_by_id(fid) or '').strip()
        except Exception:
            text = ''
    if not text:
        raise ValueError('这个文件没有可预览的文本内容')
    clipped = text[:limit]
    return {
        'ok': True,
        'file': _file_library_public_record(rec, owner_key=owner),
        'filename': filename,
        'ext': ext,
        'text': clipped,
        'text_chars': len(text),
        'truncated': bool(len(text) > len(clipped)),
    }


@app.get('/api3/file-library/state')
def api3_file_library_state_route():
    # Read-only library refresh must not consume the upload rate-limit bucket.
    def _arg_int(name: str, default: int, *, minimum: int = 0, maximum: int = 1000) -> int:
        try:
            value = int(str(request.args.get(name, default) or default).strip())
        except Exception:
            value = int(default)
        return max(int(minimum), min(int(maximum), value))

    return jsonify(_file_library_state(
        category=str(request.args.get('type') or request.args.get('category') or 'all'),
        filter_text=str(request.args.get('filter') or request.args.get('q') or ''),
        sort=str(request.args.get('sort') or 'updated_desc'),
        offset=_arg_int('offset', 0, minimum=0, maximum=1000000),
        limit=_arg_int('limit', 1000, minimum=1, maximum=1000),
    ))



@app.get('/api3/file-library/preview')
def api3_file_library_preview_route():
    # Text preview is read-only; do not count it as an upload attempt.
    file_id = str(request.args.get('file_id') or request.args.get('id') or '').strip()
    max_chars_raw = request.args.get('max_chars')
    try:
        max_chars = int(max_chars_raw) if max_chars_raw not in (None, '') else None
    except Exception:
        max_chars = None
    try:
        return jsonify(_file_library_preview_text(file_id=file_id, max_chars=max_chars))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[file_library_preview] failed file_id=%s', file_id)
        except Exception:
            pass
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 400


@app.post('/api3/file-library/delete')
def api3_file_library_delete_route():
    data = request.get_json(force=True, silent=True) or {}
    file_id = str(data.get('file_id') or data.get('id') or '').strip()
    try:
        return jsonify(_file_library_delete_file(file_id=file_id))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[file_library_delete] failed file_id=%s', file_id)
        except Exception:
            pass
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 400




def _file_library_normalize_ids(file_ids=None, *, empty_error: str = '请选择文件') -> list[str]:
    raw_ids = file_ids if isinstance(file_ids, (list, tuple, set)) else []
    ids = []
    seen = set()
    for item in raw_ids:
        fid = str(item or '').strip()
        if not fid or fid in seen:
            continue
        seen.add(fid)
        ids.append(fid)
    if not ids:
        raise ValueError(str(empty_error or '请选择文件'))
    return ids


def _file_library_batch_delete_files(file_ids=None, owner_key: str | None = None) -> dict:
    owner = _file_library_owner_key(owner_key)
    ids = _file_library_normalize_ids(file_ids, empty_error='请选择要删除的文件')

    results = []
    deleted = 0
    failed = 0
    for fid in ids:
        try:
            payload = _file_library_delete_file(file_id=fid, owner_key=owner)
            deleted += 1
            results.append({
                'file_id': fid,
                'ok': True,
                'deleted': payload.get('deleted') if isinstance(payload, dict) else [],
                'skipped': payload.get('skipped') if isinstance(payload, dict) else [],
                'object_storage': payload.get('object_storage') if isinstance(payload, dict) else {},
                'sandbox_cleanup': payload.get('sandbox_cleanup') if isinstance(payload, dict) else {},
                'registry': payload.get('registry') if isinstance(payload, dict) else {},
            })
        except Exception as e:
            failed += 1
            results.append({'file_id': fid, 'ok': False, 'error': str(e)})

    return {
        'ok': failed == 0,
        'requested': len(ids),
        'deleted': deleted,
        'failed': failed,
        'results': results,
        'state': _file_library_state(owner),
    }


@app.post('/api3/file-library/batch-delete')
def api3_file_library_batch_delete_route():
    data = request.get_json(force=True, silent=True) or {}
    file_ids = data.get('file_ids') or data.get('ids') or []
    try:
        return jsonify(_file_library_batch_delete_files(file_ids=file_ids))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[file_library_batch_delete] failed')
        except Exception:
            pass
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 400

@app.post('/api3/file-library/import-to-kb')
def api3_file_library_import_to_kb_route():
    data = request.get_json(force=True, silent=True) or {}
    file_id = str(data.get('file_id') or data.get('id') or '').strip()
    space_id = str(data.get('space_id') or '').strip()
    try:
        return jsonify(_file_library_import_to_kb(file_id=file_id, space_id=space_id))
    except StorageQuotaError as e:
        return _storage_quota_error_response(e)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[file_library_import_to_kb] failed file_id=%s', file_id)
        except Exception:
            pass
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 400


def _file_library_batch_import_to_kb(file_ids=None, space_id: str = '', owner_key: str | None = None) -> dict:
    owner = _file_library_owner_key(owner_key)
    ids = _file_library_normalize_ids(file_ids, empty_error='请选择要加入知识库的文件')
    results = []
    imported = 0
    failed = 0
    for fid in ids:
        try:
            payload = _file_library_import_to_kb(file_id=fid, space_id=space_id, owner_key=owner, include_state=False)
            imported += 1
            results.append({
                'file_id': fid,
                'ok': True,
                'document': payload.get('document') if isinstance(payload, dict) else {},
            })
        except Exception as e:
            failed += 1
            results.append({'file_id': fid, 'ok': False, 'error': str(e)})
    return {
        'ok': failed == 0,
        'requested': len(ids),
        'imported': imported,
        'failed': failed,
        'results': results,
        'state': _file_library_state(owner),
        'knowledge_state': _kb_state(owner_key=owner, space_id=space_id),
    }


@app.post('/api3/file-library/batch-import-to-kb')
def api3_file_library_batch_import_to_kb_route():
    data = request.get_json(force=True, silent=True) or {}
    file_ids = data.get('file_ids') or data.get('ids') or []
    space_id = str(data.get('space_id') or '').strip()
    try:
        return jsonify(_file_library_batch_import_to_kb(file_ids=file_ids, space_id=space_id))
    except StorageQuotaError as e:
        return _storage_quota_error_response(e)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[file_library_batch_import_to_kb] failed')
        except Exception:
            pass
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 400


@app.get('/api3/kb/state')
def api3_kb_state_route():
    # Read-only knowledge-base refresh must not trigger upload throttling.
    space_id = str(request.args.get('space_id') or '').strip()
    return jsonify(_kb_state(space_id=space_id))


@app.post('/api3/kb/space-create')
def api3_kb_space_create_route():
    data = request.get_json(force=True, silent=True) or {}
    name = str(data.get('name') or '').strip()
    if not name:
        return jsonify({'error': '知识库名称不能为空'}), 400
    try:
        created = _kb_create_space(name)
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 400
    return jsonify({'ok': True, 'space': created, 'state': _kb_state(space_id=str(created.get('id') or ''))})




@app.post('/api3/kb/space-delete')
def api3_kb_space_delete_route():
    data = request.get_json(force=True, silent=True) or {}
    space_id = str(data.get('space_id') or data.get('id') or '').strip()
    try:
        payload = _kb_delete_space(space_id=space_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[kb_space_delete] failed space_id=%s', space_id)
        except Exception:
            pass
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 400
    return jsonify({**payload, 'state': _kb_state(space_id=str(payload.get('next_space_id') or ''))})


@app.post('/api3/kb/import-text')
def api3_kb_import_text_route():
    limit_resp = _apply_rate_limit('upload')
    if limit_resp is not None:
        return limit_resp
    data = request.get_json(force=True, silent=True) or {}
    title = str(data.get('title') or data.get('filename') or '').strip()
    text = str(data.get('text') or data.get('content') or '').strip()
    space_id = str(data.get('space_id') or '').strip()
    note = str(data.get('note') or '').strip()
    if not text:
        return jsonify({'error': '文本内容不能为空'}), 400
    filename = _kb_safe_import_filename(title, fallback='文本内容')
    try:
        payload = _kb_import_document(
            space_id=space_id,
            filename=filename,
            ext='.txt',
            size_bytes=len(text.encode('utf-8', errors='replace')),
            text=text,
            note=note or '手动添加文本内容',
            source='text',
        )
        return jsonify({**payload, 'state': _kb_state(space_id=str((payload.get('space') or {}).get('id') or space_id or ''))})
    except StorageQuotaError as e:
        return _storage_quota_error_response(e)
    except Exception as e:
        app_logger.exception('[kb_import_text] failed')
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 400


@app.post('/api3/kb/import-url')
def api3_kb_import_url_route():
    limit_resp = _apply_rate_limit('upload')
    if limit_resp is not None:
        return limit_resp
    data = request.get_json(force=True, silent=True) or {}
    title = str(data.get('title') or '').strip()
    url = str(data.get('url') or data.get('href') or '').strip()
    space_id = str(data.get('space_id') or '').strip()
    if not url:
        return _kb_import_error_response(KnowledgeImportError('kb_url_required'))
    try:
        request_overrides = {}
        extractor = globals().get('_extract_request_overrides')
        if callable(extractor):
            try:
                request_overrides = extractor(data) or {}
            except Exception:
                request_overrides = {}
        enforcer = globals().get('_enforce_request_override_policy')
        if callable(enforcer):
            request_overrides = enforcer(data, request_overrides)
        setter = globals().get('_set_request_overrides')
        if callable(setter):
            setter(request_overrides)
        page = _kb_fetch_webpage_text(url, title_hint=title)
        final_url = str(page.get('final_url') or page.get('url') or url).strip()
        page_title = str(page.get('title') or '').strip()
        filename_title = title or page_title or _kb_title_from_url(final_url or url)
        filename = _kb_safe_import_filename(filename_title, fallback='网页内容')
        text = str(page.get('text') or '').strip()
        if not text:
            return jsonify({'error': '未读取到可入库正文'}), 400
        note = str(data.get('note') or '').strip() or f'来源网页：{final_url or url}'
        payload = _kb_import_document(
            space_id=space_id,
            filename=filename,
            ext='.txt',
            size_bytes=len(text.encode('utf-8', errors='replace')),
            text=text,
            note=note,
            source='url',
            view_url=final_url or url,
        )
        return jsonify({
            **payload,
            'source_url': final_url or url,
            'page_title': page_title,
            'state': _kb_state(space_id=str((payload.get('space') or {}).get('id') or space_id or '')),
        })
    except KnowledgeImportError as e:
        return _kb_import_error_response(e)
    except StorageQuotaError as e:
        return _storage_quota_error_response(e)
    except Exception as e:
        app_logger.exception('[kb_import_url] failed url=%s', url[:240])
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 400
    finally:
        setter = globals().get('_set_request_overrides')
        if callable(setter):
            try:
                setter({})
            except Exception:
                pass



@app.post('/api3/kb/search')
def api3_kb_search_route():
    data = request.get_json(force=True, silent=True) or {}
    query = str(data.get('query') or data.get('q') or '').strip()
    space_id = str(data.get('space_id') or '').strip()
    doc_id = str(data.get('doc_id') or '').strip()
    if not query:
        return jsonify({'ok': True, 'results': [], 'query': query, 'space': _kb_state(space_id=space_id).get('active_space'), 'active_document': _kb_get_document(doc_id=doc_id) if doc_id else {}})
    return jsonify(_kb_search(query=query, space_id=space_id, doc_id=doc_id, limit_docs=int(data.get('limit_docs') or 3), limit_chunks=int(data.get('limit_chunks') or 6)))



@app.post('/api3/kb/document-read')
def api3_kb_document_read_route():
    data = request.get_json(force=True, silent=True) or {}
    data['_kb_enabled'] = True
    return jsonify(_read_knowledge_base_document_tool(data))


@app.post('/api3/kb/document-delete')
def api3_kb_document_delete_route():
    data = request.get_json(force=True, silent=True) or {}
    doc_id = str(data.get('doc_id') or '').strip()
    space_id = str(data.get('space_id') or '').strip()
    try:
        payload = _kb_delete_document(doc_id=doc_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({**payload, 'state': _kb_state(space_id=space_id or str(payload.get('space_id') or ''))})
