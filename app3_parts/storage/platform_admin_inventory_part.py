# platform-admin guard, file roots, orphan scan, legacy migration, accounts, KB, and files payloads.

def _platform_admin_guard():
    return _auth_identity_admin_guard()


def _platform_admin_safe_int(value, default: int = 0, *, minimum: int = 0, maximum: int = 100000) -> int:
    try:
        out = int(value)
    except Exception:
        out = int(default)
    return max(int(minimum), min(int(maximum), out))


def _platform_admin_rel_path(path: str = '') -> str:
    raw = str(path or '').strip()
    if not raw:
        return ''
    try:
        base = os.path.abspath(APP_DATA_DIR)
        fp = os.path.abspath(raw)
        if fp == base:
            return '.'
        if fp.startswith(base + os.sep):
            return os.path.relpath(fp, base).replace('\\', '/')
        return os.path.basename(fp)
    except Exception:
        return os.path.basename(raw)


def _platform_admin_file_roots() -> list[dict]:
    rows: list[dict] = []
    for key, label, namespace, scope, global_name in (
        ('uploads_public', '公网上传', 'uploads', UPLOAD_SCOPE_PUBLIC, 'UPLOAD_DIR_PUBLIC'),
        ('uploads_local', '本地上传', 'uploads', UPLOAD_SCOPE_LOCAL, 'UPLOAD_DIR_LOCAL'),
        ('generated_public', '公网生成', 'generated', UPLOAD_SCOPE_PUBLIC, 'GENERATED_DIR_PUBLIC'),
        ('generated_local', '本地生成', 'generated', UPLOAD_SCOPE_LOCAL, 'GENERATED_DIR_LOCAL'),
    ):
        root = str(globals().get(global_name) or '').strip()
        if not root:
            continue
        try:
            root_abs = os.path.abspath(root)
        except Exception:
            continue
        if os.path.isdir(root_abs):
            rows.append({'key': key, 'label': label, 'namespace': namespace, 'scope': scope, 'root': root_abs})
    return rows


def _platform_admin_registry_files_snapshot() -> dict:
    snapshot = globals().get('_file_registry_files_snapshot')
    files = snapshot() if callable(snapshot) else {}
    return {str(k): dict(v or {}) for k, v in files.items() if isinstance(v, dict)}


def _platform_admin_registry_path_candidates(rec: dict | None = None) -> list[str]:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    out: list[str] = []
    path_fn = globals().get('_file_library_path_candidates')
    if callable(path_fn):
        try:
            for p in path_fn(row):
                raw = str(p or '').strip()
                if raw:
                    out.append(os.path.abspath(raw))
        except Exception:
            pass
    for key in ('path', 'file_path', 'local_path'):
        raw = str(row.get(key) or '').strip()
        if raw:
            try:
                out.append(os.path.abspath(raw))
            except Exception:
                pass
    if not out:
        namespace = str(row.get('namespace') or '').strip().lower()
        source = str(row.get('source') or '').strip().lower()
        scope = str(row.get('scope') or '').strip().lower()
        filename = os.path.basename(str(row.get('saved_filename') or row.get('filename') or '').strip())
        if filename:
            root = ''
            try:
                if namespace == 'generated' or source == 'generated':
                    getter = globals().get('_generated_dir_for_scope')
                    root = str(getter(scope, ensure=False) if callable(getter) else '').strip()
                else:
                    getter = globals().get('_upload_dir_for_scope')
                    root = str(getter(scope, ensure=False) if callable(getter) else '').strip()
            except Exception:
                root = ''
            if root:
                try:
                    out.append(os.path.abspath(os.path.join(root, filename)))
                except Exception:
                    pass
    dedup: list[str] = []
    seen: set[str] = set()
    for item in out:
        key = item.replace('\\', '/').lower()
        if key and key not in seen:
            seen.add(key)
            dedup.append(item)
    return dedup


def _platform_admin_registry_file_rows(*, owner: str = '', limit: int = 80) -> list[dict]:
    owner_filter = _storage_quota_norm_owner(owner or '')
    files = _platform_admin_registry_files_snapshot()
    rows: list[dict] = []
    for fid, rec in files.items():
        rec_owner = _storage_quota_norm_owner(rec.get('owner_key') or rec.get('owner') or '')
        if owner_filter and rec_owner != owner_filter:
            continue
        size = 0
        try:
            size = int(rec.get('size') or rec.get('size_bytes') or 0)
        except Exception:
            size = 0
        paths = _platform_admin_registry_path_candidates(rec)
        exists = any(os.path.isfile(path) for path in paths)
        if size <= 0:
            for path in paths:
                try:
                    if os.path.isfile(path):
                        size = int(os.path.getsize(path) or 0)
                        break
                except Exception:
                    pass
        rows.append({
            'file_id': str(rec.get('file_id') or fid or ''),
            'owner': rec_owner,
            'filename': os.path.basename(str(rec.get('filename') or rec.get('saved_filename') or '')),
            'saved_filename': os.path.basename(str(rec.get('saved_filename') or rec.get('filename') or '')),
            'source': str(rec.get('source') or ''),
            'namespace': str(rec.get('namespace') or ''),
            'scope': str(rec.get('scope') or ''),
            'size_bytes': max(0, int(size or 0)),
            'size_text': _storage_quota_human(size),
            'exists': bool(exists),
            'path': _platform_admin_rel_path(paths[0] if paths else ''),
            'url': str(rec.get('download_url') or rec.get('url') or ''),
            'view_url': str(rec.get('view_url') or ''),
            'legacy_imported': bool(rec.get('legacy_imported')),
            'updated_at': _storage_quota_fmt_ts(rec.get('updated_at') or rec.get('created_at')),
            'updated_ts': float(rec.get('updated_at') or rec.get('created_at') or 0.0),
        })
    rows.sort(key=lambda item: (-float(item.get('updated_ts') or 0.0), str(item.get('filename') or '')))
    return rows[:max(1, int(limit or 80))]


def _platform_admin_tracked_file_rows(*, owner: str = '', limit: int = 80) -> list[dict]:
    owner_filter = _storage_quota_norm_owner(owner or '')
    try:
        data = _storage_quota_load_owner_index()
        data, changed = _storage_quota_prune_owner_index_locked(data)
        if changed:
            try:
                _storage_quota_save_owner_index(data)
            except Exception:
                pass
    except Exception:
        data = {'files': {}}
    rows: list[dict] = []
    for key, rec in (data.get('files') or {}).items():
        if not isinstance(rec, dict):
            continue
        rec_owner = _storage_quota_owner_key(rec.get('owner') or '')
        if owner_filter and rec_owner != owner_filter:
            continue
        path = str(rec.get('path') or '').strip()
        try:
            size = int(os.path.getsize(path)) if os.path.isfile(path) else int(rec.get('size') or 0)
        except Exception:
            size = int(rec.get('size') or 0)
        rows.append({
            'key': str(key or ''),
            'owner': rec_owner,
            'filename': os.path.basename(str(rec.get('filename') or path or '')),
            'namespace': str(rec.get('namespace') or ''),
            'scope': str(rec.get('scope') or ''),
            'size_bytes': max(0, size),
            'size_text': _storage_quota_human(size),
            'exists': bool(path and os.path.isfile(path)),
            'path': _platform_admin_rel_path(path),
            'updated_at': _storage_quota_fmt_ts(rec.get('updated_at')),
            'updated_ts': float(rec.get('updated_at') or 0.0),
        })
    rows.sort(key=lambda item: (-float(item.get('updated_ts') or 0.0), str(item.get('filename') or '')))
    return rows[:max(1, int(limit or 80))]


def _platform_admin_known_registered_paths() -> set[str]:
    paths: set[str] = set()
    try:
        data = _storage_quota_load_owner_index()
        for rec in (data.get('files') or {}).values():
            if not isinstance(rec, dict):
                continue
            path = str(rec.get('path') or '').strip()
            if path:
                try:
                    paths.add(os.path.abspath(path).replace('\\', '/').lower())
                except Exception:
                    pass
    except Exception:
        pass
    try:
        for rec in _platform_admin_registry_files_snapshot().values():
            for path in _platform_admin_registry_path_candidates(rec):
                paths.add(os.path.abspath(path).replace('\\', '/').lower())
    except Exception:
        pass
    return paths


def _platform_admin_should_skip_file_name(filename: str = '') -> bool:
    skip_fn = globals().get('_file_library_legacy_should_skip_name')
    if callable(skip_fn):
        try:
            return bool(skip_fn(filename))
        except Exception:
            pass
    low = os.path.basename(str(filename or '')).lower()
    return bool(not low or low.endswith(('.tmp', '.part', '.uploading', '.crdownload', '.download')) or low.startswith('~$') or low.startswith('.~'))


def _platform_admin_orphan_files_scan(*, limit: int = 120, max_scan: int = 30000) -> dict:
    registered = _platform_admin_known_registered_paths()
    rows: list[dict] = []
    total = 0
    total_bytes = 0
    scanned = 0
    truncated = False
    errors: list[str] = []
    for root_info in _platform_admin_file_roots():
        root = str(root_info.get('root') or '').strip()
        if not root:
            continue
        try:
            names = sorted(os.listdir(root))
        except Exception as e:
            errors.append(f'{root_info.get("label") or root}: {type(e).__name__}')
            continue
        for name in names:
            if scanned >= max_scan:
                truncated = True
                break
            filename = os.path.basename(str(name or '').strip())
            if _platform_admin_should_skip_file_name(filename):
                continue
            path = os.path.abspath(os.path.join(root, filename))
            try:
                if not os.path.isfile(path):
                    continue
                scanned += 1
                path_key = path.replace('\\', '/').lower()
                if path_key in registered:
                    continue
                st = os.stat(path)
                size = int(st.st_size or 0)
                if size <= 0:
                    continue
                total += 1
                total_bytes += size
                if len(rows) < limit:
                    rows.append({
                        'root_key': str(root_info.get('key') or ''),
                        'root_label': str(root_info.get('label') or ''),
                        'namespace': str(root_info.get('namespace') or ''),
                        'scope': str(root_info.get('scope') or ''),
                        'filename': filename,
                        'path': _platform_admin_rel_path(path),
                        'size_bytes': size,
                        'size_text': _storage_quota_human(size),
                        'mtime': _storage_quota_fmt_ts(st.st_mtime),
                        'mtime_ts': float(st.st_mtime or 0.0),
                    })
            except Exception as e:
                errors.append(f'{filename}: {type(e).__name__}')
                continue
        if truncated:
            break
    rows.sort(key=lambda item: (-float(item.get('mtime_ts') or 0.0), str(item.get('filename') or '')))
    return {
        'ok': True,
        'scanned': scanned,
        'total': total,
        'count': total,
        'total_bytes': total_bytes,
        'total_text': _storage_quota_human(total_bytes),
        'rows': rows,
        'truncated': bool(truncated),
        'errors': errors[:12],
    }


def _platform_admin_path_inside_base(path: str = '') -> bool:
    try:
        base = os.path.normcase(os.path.abspath(APP_DATA_DIR))
        fp = os.path.normcase(os.path.abspath(str(path or '').strip()))
        return bool(fp and (fp == base or fp.startswith(base + os.sep)))
    except Exception:
        return False


def _platform_admin_current_file_root_paths() -> set[str]:
    out: set[str] = set()
    for info in _platform_admin_file_roots():
        try:
            root = os.path.normcase(os.path.abspath(str(info.get('root') or '').strip()))
            if root:
                out.add(root)
        except Exception:
            continue
    return out


def _platform_admin_legacy_file_migration_roots(extra_roots: list | None = None, *, default_scope: str = '') -> list[dict]:
    scope_default = _normalize_upload_scope(default_scope) if str(default_scope or '').strip() else UPLOAD_SCOPE_LOCAL
    base = os.path.abspath(APP_DATA_DIR)
    candidates: list[dict] = [
        {'key': 'legacy_uploads', 'label': 'legacy uploads', 'namespace': 'uploads', 'scope': scope_default, 'root': os.path.join(base, 'uploads')},
        {'key': 'legacy_upload', 'label': 'legacy upload', 'namespace': 'uploads', 'scope': scope_default, 'root': os.path.join(base, 'upload')},
        {'key': 'legacy_generated', 'label': 'legacy generated', 'namespace': 'generated', 'scope': scope_default, 'root': os.path.join(base, 'generated')},
        {'key': 'legacy_generated_files', 'label': 'legacy generated_files', 'namespace': 'generated', 'scope': scope_default, 'root': os.path.join(base, 'generated_files')},
    ]
    for item in extra_roots or []:
        if isinstance(item, str):
            raw_path = item
            namespace = ''
            scope = ''
            label = ''
        elif isinstance(item, dict):
            raw_path = str(item.get('path') or item.get('root') or '').strip()
            namespace = str(item.get('namespace') or '').strip().lower()
            scope = str(item.get('scope') or '').strip().lower()
            label = str(item.get('label') or item.get('key') or '').strip()
        else:
            continue
        if not raw_path:
            continue
        root = os.path.abspath(raw_path if os.path.isabs(raw_path) else os.path.join(base, raw_path))
        name_l = os.path.basename(root).lower()
        if namespace not in {'uploads', 'generated'}:
            namespace = 'generated' if 'generated' in name_l else 'uploads'
        if scope not in {UPLOAD_SCOPE_LOCAL, UPLOAD_SCOPE_PUBLIC}:
            scope = UPLOAD_SCOPE_PUBLIC if 'public' in name_l else scope_default
        candidates.append({
            'key': 'custom_' + hashlib.sha1(root.encode('utf-8', 'ignore')).hexdigest()[:12],
            'label': label or ('custom ' + os.path.basename(root)),
            'namespace': namespace,
            'scope': _normalize_upload_scope(scope),
            'root': root,
        })

    current_roots = _platform_admin_current_file_root_paths()
    rows: list[dict] = []
    seen: set[str] = set()
    for item in candidates:
        root = os.path.abspath(str(item.get('root') or '').strip())
        root_key = os.path.normcase(root)
        if not root or root_key in seen or root_key in current_roots:
            continue
        seen.add(root_key)
        if not _platform_admin_path_inside_base(root):
            rows.append({**item, 'root': root, 'exists': False, 'skipped': True, 'reason': 'outside_base_dir'})
            continue
        if not os.path.isdir(root):
            rows.append({**item, 'root': root, 'exists': False, 'skipped': True, 'reason': 'not_found'})
            continue
        rows.append({**item, 'root': root, 'exists': True, 'skipped': False, 'reason': ''})
    return rows


def _platform_admin_legacy_file_target_root(namespace: str = '', scope: str = '') -> str:
    ns = str(namespace or '').strip().lower()
    sc = _normalize_upload_scope(scope)
    if ns == 'generated':
        getter = globals().get('_generated_dir_for_scope')
    else:
        getter = globals().get('_upload_dir_for_scope')
    if callable(getter):
        return os.path.abspath(str(getter(sc, ensure=True) or ''))
    if ns == 'generated':
        return os.path.abspath(GENERATED_DIR_LOCAL if sc == UPLOAD_SCOPE_LOCAL else GENERATED_DIR_PUBLIC)
    return os.path.abspath(UPLOAD_DIR_LOCAL if sc == UPLOAD_SCOPE_LOCAL else UPLOAD_DIR_PUBLIC)


def _platform_admin_legacy_migration_same_file(src: str = '', dest: str = '') -> bool:
    try:
        if not os.path.isfile(src) or not os.path.isfile(dest):
            return False
        if int(os.path.getsize(src) or 0) != int(os.path.getsize(dest) or 0):
            return False
        hasher = globals().get('_platform_admin_sha256_file')
        if callable(hasher):
            return bool(hasher(src) and hasher(src) == hasher(dest))
        with open(src, 'rb') as fa, open(dest, 'rb') as fb:
            while True:
                a = fa.read(1024 * 1024)
                b = fb.read(1024 * 1024)
                if a != b:
                    return False
                if not a:
                    return True
    except Exception:
        return False


def _platform_admin_legacy_migration_dest(src_path: str = '', target_root: str = '', filename: str = '') -> tuple[str, str, bool]:
    clean_name = os.path.basename(str(filename or os.path.basename(src_path) or 'file').strip()) or 'file'
    root = os.path.abspath(str(target_root or '').strip())
    first = os.path.abspath(os.path.join(root, clean_name))
    if not os.path.exists(first):
        return first, clean_name, False
    if _platform_admin_legacy_migration_same_file(src_path, first):
        return first, clean_name, True
    stem, ext = os.path.splitext(clean_name)
    try:
        digest = (_platform_admin_sha256_file(src_path) or hashlib.sha1(src_path.encode('utf-8', 'ignore')).hexdigest())[:10]
    except Exception:
        digest = hashlib.sha1((src_path + str(time.time())).encode('utf-8', 'ignore')).hexdigest()[:10]
    for idx in range(1, 1000):
        suffix = f'_legacy_{digest}' if idx == 1 else f'_legacy_{digest}_{idx}'
        name = f'{stem}{suffix}{ext}'
        dest = os.path.abspath(os.path.join(root, name))
        if not os.path.exists(dest):
            return dest, name, False
        if _platform_admin_legacy_migration_same_file(src_path, dest):
            return dest, name, True
    raise ValueError('cannot_resolve_unique_target_filename')


def _platform_admin_legacy_migration_iter_files(root: str = '', *, max_scan: int = 50000) -> tuple[list[dict], bool, list[str]]:
    base = os.path.abspath(str(root or '').strip())
    rows: list[dict] = []
    errors: list[str] = []
    truncated = False
    scanned = 0
    if not os.path.isdir(base):
        return rows, False, errors
    try:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in {'__pycache__', '.git'}]
            for name in sorted(filenames):
                if scanned >= max_scan:
                    truncated = True
                    break
                filename = os.path.basename(str(name or '').strip())
                if _platform_admin_should_skip_file_name(filename):
                    continue
                path = os.path.abspath(os.path.join(dirpath, filename))
                try:
                    if not os.path.isfile(path) or os.path.islink(path):
                        continue
                    st = os.stat(path)
                    size = int(st.st_size or 0)
                    if size <= 0:
                        continue
                    rows.append({'path': path, 'filename': filename, 'size_bytes': size, 'mtime_ts': float(st.st_mtime or 0.0), 'rel': os.path.relpath(path, base).replace('\\', '/')})
                    scanned += 1
                except Exception as e:
                    errors.append(f'{filename}: {type(e).__name__}')
                    continue
            if truncated:
                break
    except Exception as e:
        errors.append(f'{os.path.basename(base) or base}: {type(e).__name__}')
    return rows, truncated, errors[:20]


def _platform_admin_remove_empty_legacy_root(root: str = '') -> dict:
    base = os.path.abspath(str(root or '').strip())
    out = {'root': _platform_admin_rel_path(base), 'removed_dirs': 0, 'root_removed': False, 'remaining_files': 0, 'error': ''}
    if not os.path.isdir(base) or not _platform_admin_path_inside_base(base):
        return out
    try:
        out['removed_dirs'] = _storage_quota_remove_empty_dirs(base)
        remaining = _storage_quota_collect_files(base)
        out['remaining_files'] = len(remaining)
        if not remaining:
            try:
                os.rmdir(base)
                out['root_removed'] = True
            except OSError:
                out['root_removed'] = False
    except Exception as e:
        out['error'] = f'{type(e).__name__}: {e}'
    return out


def _platform_admin_migrate_legacy_files_payload(data: dict | None = None) -> dict:
    req = dict(data or {}) if isinstance(data, dict) else {}
    dry_run = bool(req.get('dry_run', True))
    delete_empty_dirs = bool(req.get('delete_empty_dirs', True))
    remove_duplicates = bool(req.get('remove_duplicates', True))
    default_scope = str(req.get('default_scope') or req.get('scope') or UPLOAD_SCOPE_LOCAL).strip().lower()
    if default_scope not in {UPLOAD_SCOPE_LOCAL, UPLOAD_SCOPE_PUBLIC}:
        default_scope = UPLOAD_SCOPE_LOCAL
    max_files = _platform_admin_safe_int(req.get('max_files') or 1000, 1000, minimum=1, maximum=20000)
    raw_roots = req.get('roots') if isinstance(req.get('roots'), list) else []
    roots = _platform_admin_legacy_file_migration_roots(raw_roots, default_scope=default_scope)
    moved: list[dict] = []
    duplicates: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    root_summaries: list[dict] = []
    empty_dir_cleanup: list[dict] = []
    scanned = 0
    truncated = False
    planned_bytes = 0
    moved_bytes = 0

    for root_info in roots:
        root_public = {k: v for k, v in root_info.items() if k != 'root'}
        root_public['root'] = _platform_admin_rel_path(root_info.get('root') or '')
        if root_info.get('skipped'):
            root_summaries.append({**root_public, 'scanned': 0, 'planned': 0})
            continue
        namespace = str(root_info.get('namespace') or 'uploads').strip().lower()
        scope = _normalize_upload_scope(root_info.get('scope') or default_scope)
        root = os.path.abspath(str(root_info.get('root') or '').strip())
        target_root = _platform_admin_legacy_file_target_root(namespace, scope)
        remaining_budget = max(0, max_files - scanned)
        if remaining_budget <= 0:
            truncated = True
            root_summaries.append({**root_public, 'scanned': 0, 'planned': 0, 'truncated': True})
            break
        files, root_truncated, root_errors = _platform_admin_legacy_migration_iter_files(root, max_scan=remaining_budget)
        truncated = truncated or root_truncated
        planned = 0
        for err in root_errors:
            errors.append({'root': root_public['root'], 'error': err})
        for item in files:
            scanned += 1
            src = str(item.get('path') or '').strip()
            filename = os.path.basename(str(item.get('filename') or '').strip())
            try:
                dest, dest_name, duplicate = _platform_admin_legacy_migration_dest(src, target_root, filename)
                row = {
                    'source': _platform_admin_rel_path(src),
                    'target': _platform_admin_rel_path(dest),
                    'filename': filename,
                    'target_filename': dest_name,
                    'namespace': namespace,
                    'scope': scope,
                    'size_bytes': int(item.get('size_bytes') or 0),
                    'size_text': _storage_quota_human(int(item.get('size_bytes') or 0)),
                    'duplicate': bool(duplicate),
                    'dry_run': dry_run,
                }
                if duplicate:
                    if not dry_run and remove_duplicates:
                        os.remove(src)
                        row['source_removed'] = True
                    duplicates.append(row)
                    continue
                planned += 1
                planned_bytes += int(item.get('size_bytes') or 0)
                if not dry_run:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.move(src, dest)
                    try:
                        mt = float(item.get('mtime_ts') or 0.0)
                        if mt > 0:
                            os.utime(dest, (mt, mt))
                    except Exception:
                        pass
                    if scope == UPLOAD_SCOPE_PUBLIC:
                        try:
                            mirror = globals().get('_object_storage_mirror_file_async')
                            if callable(mirror):
                                row['object_storage_mirror_queued'] = bool(mirror(namespace, scope, dest_name, dest))
                        except Exception as e:
                            row['object_storage_error'] = f'{type(e).__name__}: {e}'
                    moved_bytes += int(item.get('size_bytes') or 0)
                moved.append(row)
            except Exception as e:
                errors.append({'source': _platform_admin_rel_path(src), 'error': f'{type(e).__name__}: {e}'})
        root_summaries.append({**root_public, 'scanned': len(files), 'planned': planned, 'target_root': _platform_admin_rel_path(target_root), 'truncated': bool(root_truncated)})
        if not dry_run and delete_empty_dirs:
            empty_dir_cleanup.append(_platform_admin_remove_empty_legacy_root(root))
        if scanned >= max_files:
            truncated = True
            break

    sync = {}
    if not dry_run:
        sync_fn = globals().get('_file_library_sync_legacy_files')
        if callable(sync_fn):
            try:
                sync = sync_fn(force=True) or {}
            except Exception as e:
                sync = {'ok': False, 'error': f'{type(e).__name__}: {e}'}
        try:
            _platform_admin_audit_append('legacy_file_migration', 'legacy_file_dirs', {
                'dry_run': dry_run,
                'moved': len(moved),
                'duplicates': len(duplicates),
                'moved_bytes': moved_bytes,
                'errors': len(errors),
                'roots': len(root_summaries),
            }, ok=not errors, error='' if not errors else f'{len(errors)} errors')
        except Exception:
            pass

    return {
        'ok': not errors,
        'dry_run': dry_run,
        'default_scope': default_scope,
        'scanned': scanned,
        'moved': len(moved),
        'duplicates': len(duplicates),
        'skipped': skipped,
        'planned_bytes': planned_bytes,
        'planned_text': _storage_quota_human(planned_bytes),
        'moved_bytes': moved_bytes,
        'moved_text': _storage_quota_human(moved_bytes),
        'truncated': bool(truncated),
        'max_files': max_files,
        'roots': root_summaries,
        'files': moved[:200],
        'duplicate_files': duplicates[:200],
        'empty_dir_cleanup': empty_dir_cleanup,
        'sync': sync,
        'errors': errors[:50],
    }


def _platform_admin_auth_users_payload() -> dict:
    state = globals().get('_AUTH_USERS_STATE')
    lock = globals().get('_AUTH_USERS_LOCK')
    public_fn = globals().get('_auth_user_public')
    users: dict = {}
    try:
        if lock is not None and isinstance(state, dict):
            with lock:
                users = {str(k): dict(v or {}) for k, v in (state.get('users') or {}).items() if isinstance(v, dict)}
        elif isinstance(state, dict):
            users = {str(k): dict(v or {}) for k, v in (state.get('users') or {}).items() if isinstance(v, dict)}
    except Exception:
        users = {}
    out: dict[str, dict] = {}
    for email, rec in users.items():
        normalized = _storage_quota_norm_owner(email or rec.get('email') or '')
        if not normalized:
            continue
        try:
            public = public_fn(rec, include_private=True) if callable(public_fn) else dict(rec)
        except Exception:
            public = dict(rec)
        public['email'] = normalized
        out[normalized] = public
    return out


def _platform_admin_identity_users_payload() -> dict:
    users_fn = globals().get('_auth_identity_admin_users')
    if not callable(users_fn):
        return {}
    try:
        rows = users_fn()
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        email = _storage_quota_norm_owner(row.get('email') or '')
        if email:
            out[email] = dict(row)
    return out


def _platform_admin_enriched_accounts_payload(storage_accounts: list[dict] | None = None) -> list[dict]:
    storage_rows = list(storage_accounts or [])
    auth_users = _platform_admin_auth_users_payload()
    identity_users = _platform_admin_identity_users_payload()
    owners = {str(item.get('owner') or '').strip().lower() for item in storage_rows if isinstance(item, dict)} | set(auth_users.keys()) | set(identity_users.keys())
    rows: list[dict] = []
    by_storage = {str(item.get('owner') or '').strip().lower(): dict(item) for item in storage_rows if isinstance(item, dict)}
    for owner in sorted(x for x in owners if x):
        storage = by_storage.get(owner) or _storage_quota_owner_breakdown(owner)
        auth = dict(auth_users.get(owner) or {})
        identity = dict(identity_users.get(owner) or {})
        identity_status = str(identity.get('status') or '').strip().lower()
        identity_role = str(identity.get('role') or '').strip().lower()
        registered = bool(identity)
        enabled = identity_status == 'active' if registered else True
        blacklisted = bool(auth.get('blacklisted'))
        delete_pending = bool(auth.get('delete_pending') or auth.get('account_delete_pending'))
        deleted = bool(auth.get('deleted')) or identity_status == 'deleted'
        pending = identity_status == 'pending' or identity_role == 'pending'
        access_protected = bool(identity.get('access_protected'))
        if not registered:
            status = '匿名共享桶' if owner == 'anonymous' else '未注册游客'
            status_kind = 'warn'
        elif deleted:
            status = '已删除'
            status_kind = 'bad'
        elif delete_pending:
            status = '删除期'
            status_kind = 'warn'
        elif pending:
            status = '待审核'
            status_kind = 'warn'
        elif blacklisted:
            status = str(auth.get('blacklist_status_text') or '已拉黑')
            status_kind = 'bad'
        elif not enabled:
            status = '已停用'
            status_kind = 'warn'
        else:
            status = '正常'
            status_kind = 'ok'
        row = dict(storage)
        row.update({
            'owner': owner,
            'role': ('匿名共享桶' if owner == 'anonymous' else '未注册游客') if not registered else identity_role,
            'auth': auth,
            'identity': identity,
            'account_kind': 'registered' if registered else 'guest',
            'can_purge_guest': bool(not registered),
            'access_protected': access_protected,
            'status': status,
            'status_kind': status_kind,
            'enabled': enabled,
            'blacklisted': blacklisted,
            'delete_pending': delete_pending,
            'deleted': deleted,
            'online_text': str(auth.get('online_text') or ''),
            'last_login_at': str(auth.get('last_login_at') or ''),
            'last_active_at': str(auth.get('last_active_at') or ''),
            'last_login_ip': str(auth.get('last_login_ip') or ''),
            'recent_active_ip': str(auth.get('recent_active_ip') or ''),
        })
        rows.append(row)
    rows.sort(key=lambda item: (-int(item.get('used_bytes') or 0), str(item.get('owner') or '')))
    return rows


def _platform_admin_kb_docs_payload(*, owner: str = '', query: str = '', page: int = 1, page_size: int = 40, limit: int | None = None) -> dict:
    owner_filter = _storage_quota_norm_owner(owner or '')
    qtext = str(query or '').strip()
    if limit is not None:
        page_size = _platform_admin_safe_int(limit, page_size, minimum=20, maximum=500)
    page = _platform_admin_safe_int(page, 1, minimum=1, maximum=100000)
    page_size = _platform_admin_safe_int(page_size, 40, minimum=10, maximum=200)
    offset = max(0, (page - 1) * page_size)
    rows: list[dict] = []
    total = 0
    error = ''
    try:
        ensure = globals().get('_kb_db_ensure')
        connect = globals().get('_kb_db_connect')
        if callable(ensure):
            ensure()
        if callable(connect):
            conn = connect()
            try:
                params: list = []
                where_parts: list[str] = []
                if owner_filter:
                    where_parts.append('d.owner_key=?')
                    params.append(owner_filter)
                if qtext:
                    like = '%' + qtext.lower() + '%'
                    where_parts.append('(LOWER(d.filename) LIKE ? OR LOWER(d.owner_key) LIKE ? OR LOWER(COALESCE(s.name,\'\')) LIKE ? OR LOWER(COALESCE(d.parse_status,\'\')) LIKE ? OR LOWER(COALESCE(d.source,\'\')) LIKE ?)')
                    params.extend([like, like, like, like, like])
                where = ('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''
                total_row = conn.execute(f'''
                    SELECT COUNT(*) AS c
                    FROM kb_documents d
                    LEFT JOIN kb_spaces s ON s.id=d.space_id
                    {where}
                ''', params).fetchone()
                try:
                    total = int((dict(total_row).get('c') if total_row is not None else 0) or 0)
                except Exception:
                    total = 0
                q = f'''
                    SELECT d.*, s.name AS space_name
                    FROM kb_documents d
                    LEFT JOIN kb_spaces s ON s.id=d.space_id
                    {where}
                    ORDER BY d.updated_at DESC, d.created_at DESC
                    LIMIT ? OFFSET ?
                '''
                for item in conn.execute(q, params + [page_size, offset]).fetchall() or []:
                    try:
                        rec = dict(item)
                    except Exception:
                        rec = {}
                    rows.append({
                        'id': str(rec.get('id') or ''),
                        'owner': _storage_quota_norm_owner(rec.get('owner_key') or ''),
                        'space_id': str(rec.get('space_id') or ''),
                        'space_name': str(rec.get('space_name') or ''),
                        'filename': str(rec.get('filename') or ''),
                        'ext': str(rec.get('ext') or ''),
                        'size_bytes': int(rec.get('size_bytes') or 0),
                        'size_text': _storage_quota_human(int(rec.get('size_bytes') or 0)),
                        'char_count': int(rec.get('char_count') or 0),
                        'chunk_count': int(rec.get('chunk_count') or 0),
                        'parse_status': str(rec.get('parse_status') or ''),
                        'source': str(rec.get('source') or ''),
                        'updated_at': _storage_quota_fmt_ts(rec.get('updated_at')),
                        'created_at': _storage_quota_fmt_ts(rec.get('created_at')),
                    })
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
    except Exception as e:
        error = f'{type(e).__name__}: {e}'
    total_pages = max(1, int(math.ceil(total / float(page_size)))) if page_size > 0 else 1
    return {
        'ok': not bool(error),
        'total': total,
        'rows': rows,
        'error': error,
        'query': qtext,
        'owner': owner_filter,
        'page': {
            'page': min(page, total_pages),
            'page_size': page_size,
            'total': total,
            'total_pages': total_pages,
            'has_prev': page > 1,
            'has_next': page < total_pages,
            'start': offset + 1 if total else 0,
            'end': min(offset + len(rows), total),
        },
    }


def _platform_admin_summary_payload(storage_payload: dict, accounts: list[dict]) -> dict:
    users = _platform_admin_auth_users_payload()
    total_users = len(users)
    enabled = sum(1 for item in users.values() if bool(item.get('enabled', True)) and not bool(item.get('deleted')) and not bool(item.get('delete_pending')))
    blacklisted = sum(1 for item in users.values() if bool(item.get('blacklisted')))
    delete_pending = sum(1 for item in users.values() if bool(item.get('delete_pending') or item.get('account_delete_pending')))
    over_limit = sum(1 for item in accounts if int(item.get('used_bytes') or 0) > int(item.get('limit_bytes') or 0) > 0)
    registry_count = len(_platform_admin_registry_files_snapshot())
    kb_docs = 0
    try:
        kb_docs = int((_platform_admin_kb_docs_payload(limit=1).get('total') or 0))
    except Exception:
        kb_docs = 0
    return {
        'users_total': total_users,
        'users_enabled': enabled,
        'users_blacklisted': blacklisted,
        'users_delete_pending': delete_pending,
        'accounts_total': len(accounts),
        'accounts_over_limit': over_limit,
        'registry_files': registry_count,
        'kb_documents': kb_docs,
        'app_used_text': str((storage_payload.get('app') or {}).get('used_text') or ''),
        'disk_free_text': str((storage_payload.get('disk') or {}).get('free_text') or ''),
    }


def _platform_admin_risk_items(storage_payload: dict, accounts: list[dict]) -> list[dict]:
    risks: list[dict] = []
    try:
        app_pct = float((storage_payload.get('app') or {}).get('percent') or 0.0)
        if app_pct >= 90:
            risks.append({'level': 'bad', 'code': 'app_usage_bad', 'percent': app_pct, 'text': f'Apervia 应用数据占用已到 {app_pct}%，建议立即清理缓存或调低用户额度。'})
        elif app_pct >= 75:
            risks.append({'level': 'warn', 'code': 'app_usage_warn', 'percent': app_pct, 'text': f'Apervia 应用数据占用 {app_pct}%，建议关注大文件和生成文件增长。'})
    except Exception:
        pass
    try:
        disk = storage_payload.get('disk') or {}
        free = int(disk.get('free_bytes') or 0)
        min_free = int(disk.get('min_free_bytes') or 0)
        cleanup_free = int(disk.get('cleanup_free_bytes') or 0)
        if min_free and free <= min_free:
            risks.append({'level': 'bad', 'code': 'disk_write_floor', 'text': '服务器剩余空间低于写入保护线，大文件写入会被拒绝。'})
        elif cleanup_free and free <= cleanup_free:
            risks.append({'level': 'warn', 'code': 'disk_cleanup_floor', 'text': '服务器剩余空间低于自动清理线，系统会优先回收缓存和旧文件。'})
    except Exception:
        pass
    over = [item for item in accounts if int(item.get('used_bytes') or 0) > int(item.get('limit_bytes') or 0) > 0]
    if over:
        risks.append({'level': 'warn', 'code': 'accounts_over_limit', 'count': len(over), 'text': f'{len(over)} 个账号超过当前额度，建议调整额度或清理文件。'})
    if not risks:
        risks.append({'level': 'ok', 'text': '当前没有明显存储或账号风险。'})
    return risks[:8]


def _platform_admin_state_payload(*, include_details: bool = False) -> dict:
    storage_payload = _storage_quota_admin_state_payload()
    accounts = _platform_admin_enriched_accounts_payload(storage_payload.get('accounts') or [])
    sync_state = globals().get('_FILE_LIBRARY_LEGACY_SYNC_STATE')
    legacy_sync = dict(sync_state.get('last_result') or {}) if isinstance(sync_state, dict) else {}
    payload = {
        'ok': True,
        'updated_at': time.time(),
        'updated_at_text': _storage_quota_fmt_ts(time.time()),
        'summary': _platform_admin_summary_payload(storage_payload, accounts),
        'system_status': _platform_admin_system_status_payload(),
        'risk_items': _platform_admin_risk_items(storage_payload, accounts),
        'modules': storage_payload.get('modules') or [],
        'maintenance': storage_payload.get('maintenance') or {},
        'recycle': _platform_admin_recycle_payload(limit=40),
        'audit': _platform_admin_audit_payload(limit=60),
        'backups': _platform_admin_backups_payload(page=1, page_size=40),
    }
    if include_details:
        payload.update({
            'storage': storage_payload,
            'accounts': accounts,
            'file_library_legacy_sync': legacy_sync,
        })
    return payload




def _platform_admin_page_args(default_page_size: int = 40, *, max_page_size: int = 200) -> tuple[int, int]:
    page = _platform_admin_safe_int(request.args.get('page') or 1, 1, minimum=1, maximum=100000)
    page_size = _platform_admin_safe_int(request.args.get('page_size') or request.args.get('limit') or default_page_size, default_page_size, minimum=5, maximum=max_page_size)
    return page, page_size


def _platform_admin_paginate_rows(rows: list[dict] | None = None, *, page: int = 1, page_size: int = 40) -> tuple[list[dict], dict]:
    all_rows = list(rows or [])
    page = _platform_admin_safe_int(page, 1, minimum=1, maximum=100000)
    page_size = _platform_admin_safe_int(page_size, 40, minimum=5, maximum=500)
    total = len(all_rows)
    total_pages = max(1, int(math.ceil(total / float(page_size)))) if page_size > 0 else 1
    if page > total_pages:
        page = total_pages
    start = max(0, (page - 1) * page_size)
    end = start + page_size
    return all_rows[start:end], {
        'page': page,
        'page_size': page_size,
        'total': total,
        'total_pages': total_pages,
        'has_prev': page > 1,
        'has_next': page < total_pages,
        'start': start + 1 if total else 0,
        'end': min(end, total),
    }


def _platform_admin_row_matches_query(row: dict | None = None, query: str = '') -> bool:
    q = str(query or '').strip().lower()
    if not q:
        return True
    obj = row if isinstance(row, dict) else {}
    bits: list[str] = []
    def push(value):
        if value is None:
            return
        if isinstance(value, (str, int, float, bool)):
            bits.append(str(value))
        elif isinstance(value, dict):
            for vv in value.values():
                if isinstance(vv, (str, int, float, bool)):
                    bits.append(str(vv))
        elif isinstance(value, list):
            for vv in value[:12]:
                if isinstance(vv, (str, int, float, bool)):
                    bits.append(str(vv))
    for key in ('owner', 'email', 'email_masked', 'status', 'role', 'filename', 'saved_filename', 'path', 'source', 'namespace', 'scope', 'space_name', 'parse_status', 'id', 'file_id', 'action', 'target', 'reason', 'title', 'description', 'error'):
        push(obj.get(key))
    for key in ('auth', 'actor', 'detail'):
        push(obj.get(key))
    return q in ' '.join(bits).lower()


def _platform_admin_accounts_payload(*, query: str = '', status: str = '', page: int = 1, page_size: int = 40) -> dict:
    storage_payload = _storage_quota_admin_state_payload()
    rows = _platform_admin_enriched_accounts_payload(storage_payload.get('accounts') or [])
    st = str(status or '').strip().lower()
    if st == 'blacklisted':
        rows = [item for item in rows if bool(item.get('blacklisted'))]
    elif st:
        rows = [item for item in rows if str(item.get('status_kind') or '').strip().lower() == st]
    q = str(query or '').strip()
    if q:
        rows = [item for item in rows if _platform_admin_row_matches_query(item, q)]
    page_rows, page_info = _platform_admin_paginate_rows(rows, page=page, page_size=page_size)
    return {
        'ok': True,
        'updated_at_text': _storage_quota_fmt_ts(time.time()),
        'rows': page_rows,
        'page': page_info,
        'query': q,
        'status': st,
    }


def _platform_admin_filter_rows(rows: list[dict] | None = None, query: str = '') -> list[dict]:
    q = str(query or '').strip()
    if not q:
        return list(rows or [])
    return [item for item in (rows or []) if _platform_admin_row_matches_query(item, q)]

def _platform_admin_file_row_key(row: dict | None = None) -> str:
    item = dict(row or {}) if isinstance(row, dict) else {}
    path = str(item.get('path') or '').strip().replace('\\', '/').lower()
    if path:
        return 'path:' + path
    file_id = str(item.get('file_id') or item.get('key') or '').strip().lower()
    if file_id:
        return 'id:' + file_id
    parts = [
        str(item.get('owner') or '').strip().lower(),
        str(item.get('scope') or '').strip().lower(),
        str(item.get('namespace') or item.get('source') or '').strip().lower(),
        str(item.get('saved_filename') or item.get('filename') or '').strip().lower(),
        str(item.get('size_bytes') or 0),
    ]
    return 'meta:' + '|'.join(parts)


def _platform_admin_merge_file_rows(registry_rows: list[dict] | None = None, tracked_rows: list[dict] | None = None, *, limit: int = 120) -> tuple[list[dict], int]:
    rows: dict[str, dict] = {}
    duplicate_count = 0

    def push(raw: dict, source_label: str) -> None:
        nonlocal duplicate_count
        if not isinstance(raw, dict):
            return
        item = dict(raw)
        item['record_source'] = source_label
        key = _platform_admin_file_row_key(item)
        existing = rows.get(key)
        if not existing:
            rows[key] = item
            return
        duplicate_count += 1
        sources = set(str(existing.get('record_source') or '').split('+'))
        sources.add(source_label)
        existing['record_source'] = '+'.join(sorted(x for x in sources if x))
        for field in ('file_id', 'key', 'owner', 'filename', 'saved_filename', 'source', 'namespace', 'scope', 'path', 'url', 'view_url', 'updated_at'):
            if not existing.get(field) and item.get(field):
                existing[field] = item.get(field)
        try:
            if int(item.get('size_bytes') or 0) > int(existing.get('size_bytes') or 0):
                existing['size_bytes'] = int(item.get('size_bytes') or 0)
                existing['size_text'] = item.get('size_text') or _storage_quota_human(existing['size_bytes'])
        except Exception:
            pass
        existing['exists'] = bool(existing.get('exists') or item.get('exists'))
        try:
            existing['updated_ts'] = max(float(existing.get('updated_ts') or 0.0), float(item.get('updated_ts') or 0.0))
        except Exception:
            pass

    for row in registry_rows or []:
        push(row, 'registry')
    for row in tracked_rows or []:
        push(row, 'tracked')
    merged = list(rows.values())
    merged.sort(key=lambda item: (-float(item.get('updated_ts') or 0.0), str(item.get('filename') or '')))
    return merged[:max(1, int(limit or 120))], duplicate_count


def _platform_admin_files_payload(owner: str = '', *, query: str = '', page: int = 1, page_size: int = 40, orphan_page: int = 1, orphan_page_size: int = 40, limit: int | None = None) -> dict:
    # Keep the old limit parameter compatible, but the UI now uses real pagination.
    if limit is not None:
        page_size = _platform_admin_safe_int(limit, page_size, minimum=20, maximum=500)
    page = _platform_admin_safe_int(page, 1, minimum=1, maximum=100000)
    page_size = _platform_admin_safe_int(page_size, 40, minimum=10, maximum=200)
    scan_limit = max(500, min(5000, page * page_size + page_size + 500))
    registry_files = _platform_admin_registry_file_rows(owner=owner, limit=scan_limit)
    tracked_files = _platform_admin_tracked_file_rows(owner=owner, limit=scan_limit)
    merged, duplicates_removed = _platform_admin_merge_file_rows(registry_files, tracked_files, limit=scan_limit)
    filtered_files = _platform_admin_filter_rows(merged, query)
    file_rows, file_page = _platform_admin_paginate_rows(filtered_files, page=page, page_size=page_size)

    orphan_scan = _platform_admin_orphan_files_scan(limit=1000)
    orphan_rows = _platform_admin_filter_rows(orphan_scan.get('rows') or [], query)
    orphan_page_rows, orphan_page_info = _platform_admin_paginate_rows(orphan_rows, page=orphan_page, page_size=orphan_page_size)
    orphan_scan['rows'] = orphan_page_rows
    orphan_scan['page'] = orphan_page_info
    orphan_scan['filtered_total'] = len(orphan_rows)
    return {
        'ok': True,
        'updated_at_text': _storage_quota_fmt_ts(time.time()),
        'files': file_rows,
        'page': file_page,
        'registry_files': registry_files[:page_size],
        'tracked_files': tracked_files[:page_size],
        'duplicates_removed': duplicates_removed,
        'orphans': orphan_scan,
        'query': str(query or '').strip(),
    }


def _platform_admin_file_library_sync_payload(force: bool = True) -> dict:
    sync_fn = globals().get('_file_library_sync_legacy_files')
    if not callable(sync_fn):
        return {'ok': False, 'error': 'file_library_sync_unavailable'}
    try:
        result = sync_fn(force=bool(force)) or {}
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}
    payload = _platform_admin_files_payload(limit=120)
    payload['sync'] = dict(result or {})
    return payload
