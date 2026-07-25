# platform-admin audit log, recycle bin, orphan recycle, purge, and clear actions.

def _platform_admin_audit_file() -> str:
    return _app_data_path('platform_admin_audit_log.json')


def _platform_admin_recycle_dir() -> str:
    root = _app_data_path('platform_admin_recycle')
    try:
        os.makedirs(os.path.join(root, 'files'), exist_ok=True)
    except Exception:
        pass
    return root


def _platform_admin_recycle_store_file() -> str:
    return os.path.join(_platform_admin_recycle_dir(), 'recycle_store.json')


def _platform_admin_json_atomic_write(path: str, payload: dict | list) -> None:
    tmp = str(path) + '.tmp-' + uuid.uuid4().hex
    parent = os.path.dirname(os.path.abspath(str(path)))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def _platform_admin_request_actor() -> dict:
    try:
        ip = str(_client_ip() or '').strip()
    except Exception:
        ip = ''
    try:
        user = _auth_identity_current_user()
    except Exception:
        user = {}
    return {
        'kind': 'admin_account',
        'user_id': str((user or {}).get('id') or ''),
        'email': _normalize_login_email((user or {}).get('email') or ''),
        'ip': ip,
    }


def _platform_admin_audit_load() -> dict:
    path = _platform_admin_audit_file()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        if isinstance(data, dict):
            rows = data.get('items') if isinstance(data.get('items'), list) else []
            return {'items': [dict(x or {}) for x in rows if isinstance(x, dict)], 'updated_at': float(data.get('updated_at') or 0.0)}
    except Exception:
        pass
    return {'items': [], 'updated_at': 0.0}


def _platform_admin_audit_save(data: dict) -> None:
    payload = data if isinstance(data, dict) else {'items': []}
    rows = payload.get('items') if isinstance(payload.get('items'), list) else []
    max_rows = _platform_admin_safe_int(app_getenv('PLATFORM_ADMIN_AUDIT_MAX_ROWS', '800'), 800, minimum=100, maximum=5000)
    payload['items'] = rows[-max_rows:]
    payload['updated_at'] = time.time()
    _platform_admin_json_atomic_write(_platform_admin_audit_file(), payload)


def _platform_admin_audit_append(action: str, target: str = '', detail: dict | None = None, *, ok: bool = True, error: str = '') -> dict:
    item = {
        'id': 'audit_' + uuid.uuid4().hex[:18],
        'ts': time.time(),
        'time': _storage_quota_fmt_ts(time.time()),
        'action': str(action or '').strip(),
        'target': str(target or '').strip()[:320],
        'ok': bool(ok),
        'error': str(error or '').strip()[:500],
        'actor': _platform_admin_request_actor(),
        'detail': dict(detail or {}) if isinstance(detail, dict) else {},
    }
    try:
        data = _platform_admin_audit_load()
        rows = data.setdefault('items', [])
        rows.append(item)
        _platform_admin_audit_save(data)
    except Exception:
        try:
            app_logger.exception('[platform_admin] audit_append_failed')
        except Exception:
            pass
    return item


def _platform_admin_audit_payload(limit: int = 120, target: str = '', query: str = '', page: int = 1, page_size: int = 40) -> dict:
    page_size = _platform_admin_safe_int(page_size or limit, 40, minimum=10, maximum=200)
    page = _platform_admin_safe_int(page, 1, minimum=1, maximum=100000)
    target_l = str(target or '').strip().lower()
    qtext = str(query or '').strip()
    rows = list((_platform_admin_audit_load().get('items') or []))
    if target_l:
        rows = [row for row in rows if target_l in str(row.get('target') or '').lower() or target_l in json.dumps(row.get('detail') or {}, ensure_ascii=False).lower()]
    if qtext:
        rows = [row for row in rows if _platform_admin_row_matches_query(row, qtext)]
    rows.sort(key=lambda item: float((item or {}).get('ts') or 0.0), reverse=True)
    page_rows, page_info = _platform_admin_paginate_rows(rows, page=page, page_size=page_size)
    return {'ok': True, 'total': len(rows), 'rows': page_rows, 'page': page_info, 'target': target_l, 'query': qtext}


def _platform_admin_recycle_load() -> dict:
    path = _platform_admin_recycle_store_file()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        if isinstance(data, dict):
            items = data.get('items') if isinstance(data.get('items'), dict) else {}
            return {'items': {str(k): dict(v or {}) for k, v in items.items() if isinstance(v, dict)}, 'updated_at': float(data.get('updated_at') or 0.0)}
    except Exception:
        pass
    return {'items': {}, 'updated_at': 0.0}


def _platform_admin_recycle_save(data: dict) -> None:
    payload = data if isinstance(data, dict) else {'items': {}}
    if not isinstance(payload.get('items'), dict):
        payload['items'] = {}
    payload['updated_at'] = time.time()
    _platform_admin_json_atomic_write(_platform_admin_recycle_store_file(), payload)


def _platform_admin_recycle_public_row(rec: dict | None = None) -> dict:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    recycled_at = float(row.get('recycled_at') or 0.0)
    artifacts = _platform_admin_recycle_artifacts(row)
    exists_count = 0
    size = 0
    for artifact in artifacts:
        path = str(artifact.get('recycle_path') or '').strip()
        if not path or not os.path.isfile(path):
            continue
        exists_count += 1
        try:
            size += int(os.path.getsize(path) or 0)
        except Exception:
            size += max(0, int(artifact.get('size_bytes') or 0))
    first = artifacts[0] if artifacts else {}
    original_path = str(first.get('original_path') or row.get('original_path') or '').strip()
    recycle_path = str(first.get('recycle_path') or row.get('recycle_path') or '').strip()
    return {
        'id': str(row.get('id') or ''),
        'filename': str(row.get('filename') or ''),
        'original_path': _platform_admin_rel_path(original_path),
        'recycle_path': _platform_admin_rel_path(recycle_path),
        'root_label': str(row.get('root_label') or ''),
        'namespace': str(row.get('namespace') or ''),
        'scope': str(row.get('scope') or ''),
        'source_kind': str(row.get('source_kind') or 'orphan_file'),
        'artifact_count': len(artifacts),
        'missing_count': max(0, len(artifacts) - exists_count),
        'size_bytes': size,
        'size_text': _storage_quota_human(size),
        'reason': str(row.get('reason') or ''),
        'exists': bool(artifacts and exists_count == len(artifacts)),
        'recycled_at': _storage_quota_fmt_ts(recycled_at),
        'recycled_ts': recycled_at,
    }


def _platform_admin_recycle_payload(limit: int = 120, query: str = '', page: int = 1, page_size: int = 40) -> dict:
    page_size = _platform_admin_safe_int(page_size or limit, 40, minimum=10, maximum=200)
    page = _platform_admin_safe_int(page, 1, minimum=1, maximum=100000)
    data = _platform_admin_recycle_load()
    rows = [_platform_admin_recycle_public_row(rec) for rec in (data.get('items') or {}).values()]
    qtext = str(query or '').strip()
    if qtext:
        rows = [row for row in rows if _platform_admin_row_matches_query(row, qtext)]
    rows.sort(key=lambda item: float(item.get('recycled_ts') or 0.0), reverse=True)
    total_bytes = sum(int(item.get('size_bytes') or 0) for item in rows)
    page_rows, page_info = _platform_admin_paginate_rows(rows, page=page, page_size=page_size)
    return {'ok': True, 'total': len(rows), 'total_bytes': total_bytes, 'total_text': _storage_quota_human(total_bytes), 'rows': page_rows, 'page': page_info, 'query': qtext}


def _platform_admin_resolve_managed_path(rel_path: str = '') -> tuple[str, dict]:
    raw = str(rel_path or '').strip().replace('\\', '/')
    if not raw or raw.startswith('/') or '..' in raw.split('/'):
        raise ValueError('文件路径无效')
    base = os.path.abspath(APP_DATA_DIR)
    path = os.path.abspath(os.path.join(base, *[x for x in raw.split('/') if x]))
    if not (path == base or path.startswith(base + os.sep)):
        raise ValueError('文件路径不在应用目录内')
    for root_info in _platform_admin_file_roots():
        root = os.path.abspath(str(root_info.get('root') or ''))
        if root and (path == root or path.startswith(root + os.sep)):
            return path, root_info
    raise ValueError('只能处理上传/生成目录中的文件')


def _platform_admin_resolve_orphan_file(rel_path: str = '') -> tuple[str, dict, int]:
    path, root_info = _platform_admin_resolve_managed_path(rel_path)
    if not os.path.isfile(path):
        raise ValueError('文件不存在')
    if _platform_admin_should_skip_file_name(os.path.basename(path)):
        raise ValueError('临时文件不在此处处理')
    registered = _platform_admin_known_registered_paths()
    if os.path.abspath(path).replace('\\', '/').lower() in registered:
        raise ValueError('该文件已经登记，不能按孤儿文件删除')
    try:
        size = int(os.path.getsize(path) or 0)
    except Exception:
        size = 0
    if size <= 0:
        raise ValueError('空文件不处理')
    return path, root_info, size


def _platform_admin_recycle_artifacts(rec: dict | None = None) -> list[dict]:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    raw_items = row.get('artifacts') if isinstance(row.get('artifacts'), list) else []
    items = [dict(item or {}) for item in raw_items if isinstance(item, dict)]
    if not items and (row.get('original_path') or row.get('recycle_path')):
        items = [{
            'original_path': str(row.get('original_path') or ''),
            'recycle_path': str(row.get('recycle_path') or ''),
            'size_bytes': int(row.get('size_bytes') or 0),
        }]
    return items


def _platform_admin_recycle_cleanup_artifact_dirs(rec: dict | None = None) -> None:
    files_root = os.path.abspath(os.path.join(_platform_admin_recycle_dir(), 'files'))
    parents: set[str] = set()
    for artifact in _platform_admin_recycle_artifacts(rec):
        recycle_path = os.path.abspath(str(artifact.get('recycle_path') or '').strip())
        parent = os.path.dirname(recycle_path)
        if parent and parent.startswith(files_root + os.sep):
            parents.add(parent)
    for parent in sorted(parents, key=len, reverse=True):
        try:
            if os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
        except Exception:
            pass


def _platform_admin_recycle_validate_source_path(path: str = '') -> str:
    raw = os.path.abspath(str(path or '').strip())
    base = os.path.abspath(APP_DATA_DIR)
    recycle_root = os.path.abspath(_platform_admin_recycle_dir())
    if not raw or not raw.startswith(base + os.sep):
        raise ValueError('只能回收应用目录内的文件')
    if raw == recycle_root or raw.startswith(recycle_root + os.sep):
        raise ValueError('不能重复回收回收站内的文件')
    if not os.path.isfile(raw) or os.path.islink(raw):
        raise ValueError('回收目标不是普通文件')
    return raw


def _platform_admin_recycle_restore_registry_context(rec: dict | None = None) -> list[str]:
    context = dict((rec or {}).get('restore_context') or {}) if isinstance((rec or {}).get('restore_context'), dict) else {}
    records = context.get('file_registry_records') if isinstance(context.get('file_registry_records'), dict) else {}
    if not records:
        return []
    loader = globals().get('_file_registry_load')
    saver = globals().get('_file_registry_save')
    lock = globals().get('_FILE_REGISTRY_LOCK')
    state = globals().get('_FILE_REGISTRY_STATE')
    if lock is None or not isinstance(state, dict) or not callable(saver):
        raise ValueError('文件索引当前不可用，无法恢复')
    if callable(loader):
        loader()
    inserted: list[str] = []
    with lock:
        files = dict(state.get('files') or {}) if isinstance(state.get('files'), dict) else {}
        conflicts = [fid for fid in records if fid in files]
        if conflicts:
            raise ValueError('文件索引中已存在同 ID 记录，无法覆盖恢复')
        for fid, item in records.items():
            key = str(fid or '').strip()
            if not key or not isinstance(item, dict):
                continue
            files[key] = dict(item)
            inserted.append(key)
        state['files'] = files
        state['updated_at'] = time.time()
    saver(raise_on_error=True)
    return inserted


def _platform_admin_recycle_remove_registry_context(file_ids: list[str] | None = None) -> None:
    ids = {str(value or '').strip() for value in (file_ids or []) if str(value or '').strip()}
    if not ids:
        return
    lock = globals().get('_FILE_REGISTRY_LOCK')
    state = globals().get('_FILE_REGISTRY_STATE')
    saver = globals().get('_file_registry_save')
    if lock is None or not isinstance(state, dict):
        return
    with lock:
        files = dict(state.get('files') or {}) if isinstance(state.get('files'), dict) else {}
        for fid in ids:
            files.pop(fid, None)
        state['files'] = files
        state['updated_at'] = time.time()
    if callable(saver):
        saver()


def _platform_admin_recycle_paths(
    paths: list[str] | None = None,
    *,
    reason: str = '',
    source_kind: str = 'managed_file',
    restore_context: dict | None = None,
    display_name: str = '',
    root_info: dict | None = None,
) -> dict:
    unique: list[str] = []
    seen: set[str] = set()
    for value in paths or []:
        path = _platform_admin_recycle_validate_source_path(value)
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    if not unique:
        raise ValueError('没有可回收的文件实体')
    rid = 'recycle_' + uuid.uuid4().hex[:20]
    dest_root = os.path.join(_platform_admin_recycle_dir(), 'files', rid)
    os.makedirs(dest_root, exist_ok=True)
    artifacts: list[dict] = []
    moved: list[tuple[str, str]] = []
    try:
        for index, path in enumerate(unique):
            filename = os.path.basename(path)
            safe_name = re.sub(r'[^0-9A-Za-z._-]+', '-', filename)[:120] or 'file'
            dest = os.path.join(dest_root, f'{index:03d}_{safe_name}')
            size = int(os.path.getsize(path) or 0)
            shutil.move(path, dest)
            moved.append((path, dest))
            artifacts.append({'original_path': path, 'recycle_path': dest, 'size_bytes': size})
        info = dict(root_info or {}) if isinstance(root_info, dict) else {}
        rec = {
            'id': rid,
            'filename': str(display_name or os.path.basename(unique[0]) or 'file').strip(),
            'original_path': unique[0],
            'recycle_path': artifacts[0]['recycle_path'],
            'root_key': str(info.get('key') or ''),
            'root_label': str(info.get('label') or ''),
            'namespace': str(info.get('namespace') or ''),
            'scope': str(info.get('scope') or ''),
            'source_kind': str(source_kind or 'managed_file').strip(),
            'size_bytes': sum(int(item.get('size_bytes') or 0) for item in artifacts),
            'reason': str(reason or '').strip()[:500],
            'recycled_at': time.time(),
            'artifacts': artifacts,
            'restore_context': dict(restore_context or {}) if isinstance(restore_context, dict) else {},
        }
        data = _platform_admin_recycle_load()
        data.setdefault('items', {})[rid] = rec
        _platform_admin_recycle_save(data)
    except Exception:
        for original, dest in reversed(moved):
            try:
                if os.path.isfile(dest) and not os.path.exists(original):
                    os.makedirs(os.path.dirname(original), exist_ok=True)
                    shutil.move(dest, original)
            except Exception:
                pass
        try:
            if os.path.isdir(dest_root) and not os.listdir(dest_root):
                os.rmdir(dest_root)
        except Exception:
            pass
        raise
    _platform_admin_audit_append('file_recycle', _platform_admin_rel_path(unique[0]), {
        'id': rid,
        'source_kind': rec['source_kind'],
        'artifact_count': len(artifacts),
        'size_bytes': rec['size_bytes'],
        'reason': reason,
    }, ok=True)
    return {'ok': True, 'file': _platform_admin_recycle_public_row(rec), 'record': rec}


def _platform_admin_recycle_cancel(recycle_id: str = '') -> None:
    rid = str(recycle_id or '').strip()
    if not rid:
        return
    data = _platform_admin_recycle_load()
    items = data.setdefault('items', {})
    rec = dict(items.get(rid) or {})
    if not rec:
        return
    moved: list[tuple[str, str]] = []
    try:
        for artifact in _platform_admin_recycle_artifacts(rec):
            recycle_path = str(artifact.get('recycle_path') or '').strip()
            original_path = os.path.abspath(str(artifact.get('original_path') or '').strip())
            if not recycle_path or not os.path.isfile(recycle_path):
                continue
            if os.path.exists(original_path):
                raise ValueError('取消回收时原位置已被占用')
            os.makedirs(os.path.dirname(original_path), exist_ok=True)
            shutil.move(recycle_path, original_path)
            moved.append((original_path, recycle_path))
        items.pop(rid, None)
        _platform_admin_recycle_save(data)
        _platform_admin_recycle_cleanup_artifact_dirs(rec)
    except Exception:
        for original_path, recycle_path in reversed(moved):
            try:
                if os.path.isfile(original_path) and not os.path.exists(recycle_path):
                    os.makedirs(os.path.dirname(recycle_path), exist_ok=True)
                    shutil.move(original_path, recycle_path)
            except Exception:
                pass
        raise


def _platform_admin_recycle_orphan_file(rel_path: str = '', reason: str = '') -> dict:
    path, root_info, size = _platform_admin_resolve_orphan_file(rel_path)
    result = _platform_admin_recycle_paths(
        [path],
        reason=reason,
        source_kind='orphan_file',
        display_name=os.path.basename(path),
        root_info=root_info,
    )
    result.update({'files': _platform_admin_files_payload(limit=120), 'recycle': _platform_admin_recycle_payload(limit=120)})
    return result


def _platform_admin_recycle_orphan_files(rel_paths: list[str] | None = None, reason: str = '', *, limit: int = 80) -> dict:
    paths = [str(x or '').strip() for x in (rel_paths or []) if str(x or '').strip()]
    max_items = _platform_admin_safe_int(limit, 80, minimum=1, maximum=200)
    rows: list[dict] = []
    errors: list[dict] = []
    for rel_path in paths[:max_items]:
        try:
            one = _platform_admin_recycle_orphan_file(rel_path, reason)
            if isinstance(one.get('file'), dict):
                rows.append(one.get('file') or {})
        except Exception as e:
            err = f'{type(e).__name__}: {e}'
            errors.append({'path': rel_path, 'error': err})
            _platform_admin_audit_append('orphan_file_recycle_batch_item', rel_path, {'reason': reason}, ok=False, error=err)
    _platform_admin_audit_append('orphan_file_recycle_batch', 'orphan_files', {
        'requested': len(paths),
        'processed': min(len(paths), max_items),
        'recycled': len(rows),
        'errors': len(errors),
        'reason': reason,
    }, ok=not errors, error=('部分文件处理失败' if errors else ''))
    return {
        'ok': bool(rows) and not errors,
        'partial_ok': bool(rows),
        'recycled': len(rows),
        'errors': errors[:40],
        'rows': rows,
        'files': _platform_admin_files_payload(limit=120),
        'recycle': _platform_admin_recycle_payload(limit=120),
    }


def _platform_admin_recycle_action(recycle_id: str = '', action: str = '') -> dict:
    rid = str(recycle_id or '').strip()
    action_key = str(action or '').strip().lower()
    if not rid:
        raise ValueError('回收站文件 ID 不能为空')
    data = _platform_admin_recycle_load()
    items = data.setdefault('items', {})
    rec = dict(items.get(rid) or {})
    if not rec:
        raise ValueError('回收站文件不存在')
    artifacts = _platform_admin_recycle_artifacts(rec)
    original_path = str(rec.get('original_path') or '').strip()
    if action_key == 'restore':
        base = os.path.abspath(APP_DATA_DIR)
        if not artifacts:
            raise ValueError('回收站文件实体记录缺失')
        for artifact in artifacts:
            recycle_path = str(artifact.get('recycle_path') or '').strip()
            original_abs = os.path.abspath(str(artifact.get('original_path') or '').strip())
            if not recycle_path or not os.path.isfile(recycle_path):
                raise ValueError('回收站文件实体不存在')
            if not original_abs.startswith(base + os.sep):
                raise ValueError('原始路径不在应用目录内')
            if os.path.exists(original_abs):
                raise ValueError('原位置已有同名文件，暂不能自动覆盖')
        moved: list[tuple[str, str]] = []
        inserted_ids: list[str] = []
        try:
            for artifact in artifacts:
                recycle_path = str(artifact.get('recycle_path') or '').strip()
                original_abs = os.path.abspath(str(artifact.get('original_path') or '').strip())
                os.makedirs(os.path.dirname(original_abs), exist_ok=True)
                shutil.move(recycle_path, original_abs)
                moved.append((original_abs, recycle_path))
            inserted_ids = _platform_admin_recycle_restore_registry_context(rec)
            items.pop(rid, None)
            _platform_admin_recycle_save(data)
        except Exception:
            _platform_admin_recycle_remove_registry_context(inserted_ids)
            for original_abs, recycle_path in reversed(moved):
                try:
                    if os.path.isfile(original_abs) and not os.path.exists(recycle_path):
                        os.makedirs(os.path.dirname(recycle_path), exist_ok=True)
                        shutil.move(original_abs, recycle_path)
                except Exception:
                    pass
            raise
        _platform_admin_recycle_cleanup_artifact_dirs(rec)
        _platform_admin_audit_append('recycle_restore', _platform_admin_rel_path(original_path), {'id': rid, 'artifact_count': len(artifacts)}, ok=True)
    elif action_key in {'purge', 'delete'}:
        for artifact in artifacts:
            recycle_path = str(artifact.get('recycle_path') or '').strip()
            if recycle_path and os.path.isfile(recycle_path):
                os.remove(recycle_path)
        items.pop(rid, None)
        _platform_admin_recycle_save(data)
        _platform_admin_recycle_cleanup_artifact_dirs(rec)
        _platform_admin_audit_append('recycle_purge', _platform_admin_rel_path(original_path), {'id': rid, 'artifact_count': len(artifacts)}, ok=True)
    else:
        raise ValueError('不支持的回收站操作')
    return {'ok': True, 'recycle': _platform_admin_recycle_payload(limit=120), 'files': _platform_admin_files_payload(limit=120)}


def _platform_admin_recycle_purge_all(query: str = '') -> dict:
    data = _platform_admin_recycle_load()
    items = data.setdefault('items', {})
    qtext = str(query or '').strip()
    rows = []
    for rid, rec in list(items.items()):
        public = _platform_admin_recycle_public_row(rec)
        if qtext and not _platform_admin_row_matches_query(public, qtext):
            continue
        rows.append((rid, dict(rec or {}), public))
    purged = 0
    freed = 0
    errors: list[dict] = []
    for rid, rec, public in rows:
        try:
            removed_size = 0
            for artifact in _platform_admin_recycle_artifacts(rec):
                recycle_path = str(artifact.get('recycle_path') or '').strip()
                if recycle_path and os.path.isfile(recycle_path):
                    removed_size += int(os.path.getsize(recycle_path) or 0)
                    os.remove(recycle_path)
            items.pop(rid, None)
            _platform_admin_recycle_cleanup_artifact_dirs(rec)
            purged += 1
            freed += removed_size
        except Exception as e:
            freed += removed_size
            errors.append({'id': rid, 'file': str(public.get('filename') or ''), 'error': f'{type(e).__name__}: {e}'})
    _platform_admin_recycle_save(data)
    ok = not errors
    _platform_admin_audit_append('recycle_purge_all', 'platform_admin_recycle', {'purged': purged, 'freed_bytes': freed, 'query': qtext, 'errors': errors[:10]}, ok=ok, error='' if ok else f'{len(errors)} 个回收站文件删除失败')
    return {
        'ok': ok or purged > 0,
        'partial_ok': bool(errors and purged > 0),
        'purged': purged,
        'freed_bytes': freed,
        'freed_text': _storage_quota_human(freed),
        'errors': errors[:20],
        'recycle': _platform_admin_recycle_payload(limit=120),
        'files': _platform_admin_files_payload(limit=120),
    }


def _platform_admin_audit_clear(query: str = '', target: str = '') -> dict:
    data = _platform_admin_audit_load()
    rows = list(data.get('items') or [])
    qtext = str(query or '').strip()
    target_l = str(target or '').strip().lower()
    kept: list[dict] = []
    removed: list[dict] = []
    for row in rows:
        match = True
        if target_l:
            hay = (str(row.get('target') or '').lower() + ' ' + json.dumps(row.get('detail') or {}, ensure_ascii=False).lower())
            match = target_l in hay
        if match and qtext:
            match = _platform_admin_row_matches_query(row, qtext)
        if match:
            removed.append(row)
        else:
            kept.append(row)
    data['items'] = kept
    _platform_admin_audit_save(data)
    note = {'cleared': len(removed), 'kept': len(kept), 'query': qtext, 'target': target_l}
    _platform_admin_audit_append('audit_clear', 'platform_admin_audit', note, ok=True)
    return {'ok': True, 'cleared': len(removed), 'audit': _platform_admin_audit_payload(page=1, page_size=60)}
