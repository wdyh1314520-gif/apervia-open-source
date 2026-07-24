# KB deleted-document artifact cleanup, state, and delete document.

def _kb_deleted_doc_reference_values(row_obj: dict | None = None) -> dict:
    row = dict(row_obj or {}) if isinstance(row_obj, dict) else {}
    urls: list[str] = []
    paths: list[str] = []
    names: list[str] = []

    def push_unique(bucket: list[str], value: str = '') -> None:
        raw = str(value or '').strip()
        if raw and raw not in bucket:
            bucket.append(raw)

    for key in ('download_url', 'view_url'):
        push_unique(urls, row.get(key) or '')
    push_unique(paths, row.get('file_path') or '')
    for path in list(paths):
        push_unique(names, os.path.basename(str(path or '').strip()))
    extractor = globals().get('_extract_saved_filename_from_url')
    for url in list(urls):
        name = ''
        try:
            name = str(extractor(url) if callable(extractor) else os.path.basename(urlparse(url).path or '') or '').strip()
        except Exception:
            name = ''
        push_unique(names, name)
    return {
        'doc_id': str(row.get('id') or '').strip(),
        'owner_key': str(row.get('owner_key') or '').strip().lower(),
        'filename': str(row.get('filename') or '').strip(),
        'content_hash': str(row.get('content_hash') or '').strip(),
        'urls': urls,
        'paths': paths,
        'names': names,
    }


def _kb_safe_local_artifact_path(path: str = '') -> str:
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
    if not os.path.isfile(candidate):
        return ''
    for root in roots:
        try:
            if candidate == root or candidate.startswith(root + os.sep):
                return candidate
        except Exception:
            continue
    return ''


def _kb_local_paths_for_deleted_doc(row_obj: dict | None = None) -> list[str]:
    refs = _kb_deleted_doc_reference_values(row_obj)
    out: list[str] = []

    def push_path(path: str = '') -> None:
        safe = _kb_safe_local_artifact_path(path)
        if safe and safe not in out:
            out.append(safe)

    for path in refs.get('paths') or []:
        push_path(path)

    scope_from_url = globals().get('_extract_upload_scope_from_url')
    resolve_upload = globals().get('_resolve_uploaded_file_dir')
    resolve_generated = globals().get('_resolve_generated_file_dir')
    extractor = globals().get('_extract_saved_filename_from_url')
    for url in refs.get('urls') or []:
        try:
            filename = str(extractor(url) if callable(extractor) else os.path.basename(urlparse(url).path or '') or '').strip()
        except Exception:
            filename = ''
        if not filename:
            continue
        try:
            scope = str(scope_from_url(url) if callable(scope_from_url) else '').strip() or None
        except Exception:
            scope = None
        lowered = str(url or '').lower()
        base = None
        try:
            if ('/api3/generated-files/' in lowered or '/api3/generated-download/' in lowered) and callable(resolve_generated):
                base = resolve_generated(filename, scope=scope)
            elif callable(resolve_upload):
                base = resolve_upload(filename, scope=scope)
        except Exception:
            base = None
        if base:
            push_path(os.path.join(str(base), filename))
    return out


def _kb_deleted_doc_has_other_kb_refs(row_obj: dict | None = None, conn=None) -> bool:
    refs = _kb_deleted_doc_reference_values(row_obj)
    doc_id = str(refs.get('doc_id') or '').strip()
    if not doc_id:
        return True
    checks: list[tuple[str, str]] = []
    for path in refs.get('paths') or []:
        checks.append(('file_path', path))
    for url in refs.get('urls') or []:
        checks.append(('download_url', url))
        checks.append(('view_url', url))
    checks = [(k, str(v or '').strip()) for k, v in checks if str(v or '').strip()]
    if not checks:
        return False
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        for key, value in checks:
            try:
                row = conn.execute(f'SELECT id FROM kb_documents WHERE id<>? AND {key}=? LIMIT 1', (doc_id, value)).fetchone()
                if row is not None:
                    return True
            except Exception:
                continue
        return False
    finally:
        if own_conn:
            conn.close()


def _kb_deleted_doc_has_chat_refs(row_obj: dict | None = None) -> bool:
    refs = _kb_deleted_doc_reference_values(row_obj)
    owner = str(refs.get('owner_key') or '').strip().lower()
    values: list[str] = []
    for value in (refs.get('urls') or []):
        raw = str(value or '').strip()
        if raw and raw not in values:
            values.append(raw)
    for name in (refs.get('names') or []):
        raw = str(name or '').strip()
        if len(raw) >= 8 and raw not in values:
            values.append(raw)
    for path in (refs.get('paths') or []):
        raw = str(path or '').strip()
        base = os.path.basename(raw)
        if len(base) >= 8 and base not in values:
            values.append(base)
    if not values:
        return False
    texts: list[str] = []
    try:
        state = globals().get('_AUTH_CHAT_STATE') or {}
        lock = globals().get('_AUTH_CHAT_LOCK')
        accounts = {}
        if isinstance(state, dict):
            if lock is not None:
                with lock:
                    accounts = dict((state.get('accounts') or {}) if isinstance(state.get('accounts'), dict) else {})
            else:
                accounts = dict((state.get('accounts') or {}) if isinstance(state.get('accounts'), dict) else {})
        if accounts:
            texts.append(json.dumps(accounts, ensure_ascii=False, separators=(',', ':')))
    except Exception:
        pass
    if not texts and owner:
        getter = globals().get('_auth_chat_store_get')
        rec = None
        if callable(getter):
            try:
                rec = getter(owner)
            except Exception:
                rec = None
        if isinstance(rec, dict):
            try:
                texts.append(json.dumps(rec, ensure_ascii=False, separators=(',', ':')))
            except Exception:
                texts.append(str(rec))
    if not texts:
        return False
    return any(value and any(value in text for text in texts) for value in values)


def _kb_file_registry_records_for_deleted_doc(row_obj: dict | None = None) -> dict[str, dict]:
    refs = _kb_deleted_doc_reference_values(row_obj)
    names = {str(x or '').strip() for x in (refs.get('names') or []) if str(x or '').strip()}
    urls = {str(x or '').strip() for x in (refs.get('urls') or []) if str(x or '').strip()}
    if not names and not urls:
        return {}
    loader = globals().get('_file_registry_load')
    lock = globals().get('_FILE_REGISTRY_LOCK')
    state = globals().get('_FILE_REGISTRY_STATE')
    if callable(loader):
        try:
            loader()
        except Exception:
            pass
    if lock is None or not isinstance(state, dict):
        return {}
    matched_records: dict[str, dict] = {}
    with lock:
        files = dict((state.get('files') or {}) if isinstance(state.get('files'), dict) else {})
        for fid, rec in files.items():
            item = dict(rec or {}) if isinstance(rec, dict) else {}
            rec_names = {
                str(item.get('saved_filename') or '').strip(),
                str(item.get('filename') or '').strip(),
                os.path.basename(str(item.get('storage_ref') or '').strip()),
            }
            rec_urls = {
                str(item.get('url') or '').strip(),
                str(item.get('view_url') or '').strip(),
                str(item.get('download_url') or '').strip(),
            }
            rec_names = {x for x in rec_names if x}
            rec_urls = {x for x in rec_urls if x}
            if (urls and rec_urls and urls.intersection(rec_urls)) or (names and rec_names and names.intersection(rec_names)):
                matched_records[str(fid)] = item
    return matched_records


def _kb_remove_file_registry_for_deleted_doc(row_obj: dict | None = None, records: dict | None = None) -> dict:
    removed_records = dict(records or _kb_file_registry_records_for_deleted_doc(row_obj))
    if not removed_records:
        return {'removed': 0, 'full_text_removed': 0, 'records': {}}
    remover = globals().get('_file_registry_remove_records')
    if not callable(remover):
        return {'removed': 0, 'full_text_removed': 0, 'records': {}, 'error': 'file_registry_unavailable'}
    try:
        result = remover(list(removed_records))
    except Exception as e:
        return {'removed': 0, 'full_text_removed': 0, 'records': {}, 'error': f'{type(e).__name__}: {e}'}
    removed = dict(result.get('records') or {}) if isinstance(result, dict) else {}
    return {'removed': len(removed), 'full_text_removed': 0, 'records': removed}


def _kb_cleanup_deleted_document_artifacts(row_obj: dict | None = None, conn=None, *, use_recycle: bool = True) -> dict:
    row = dict(row_obj or {}) if isinstance(row_obj, dict) else {}
    if not row:
        return {'ok': True, 'skipped': True, 'reason': 'empty_row'}
    cleanup = {
        'ok': True,
        'local_files_deleted': [],
        'local_files_skipped': [],
        'registry': {},
    }
    try:
        if _kb_deleted_doc_has_other_kb_refs(row, conn=conn):
            cleanup['local_files_skipped'].append({'reason': 'referenced_by_other_kb_document'})
            cleanup['registry'] = {'removed': 0, 'skipped': True, 'reason': 'referenced_by_other_kb_document'}
            return cleanup
        if _kb_deleted_doc_has_chat_refs(row):
            cleanup['local_files_skipped'].append({'reason': 'referenced_by_chat_history'})
            cleanup['registry'] = {'removed': 0, 'skipped': True, 'reason': 'referenced_by_chat_history'}
            return cleanup
        registry_records = _kb_file_registry_records_for_deleted_doc(row)
        paths = [path for path in _kb_local_paths_for_deleted_doc(row) if os.path.isfile(path)]
        selected_ids = {str(fid or '').strip() for fid in registry_records}
        all_records_getter = globals().get('_file_registry_files_snapshot')
        all_records = all_records_getter() if callable(all_records_getter) else {}
        for item in registry_records.values():
            ref = str((item or {}).get('full_text_ref') or '').strip()
            if not ref or not callable(globals().get('_file_text_store_path')):
                continue
            shared = any(
                str(fid or '').strip() not in selected_ids
                and isinstance(other, dict)
                and str(other.get('full_text_ref') or '').strip() == ref
                for fid, other in (all_records or {}).items()
            )
            if shared:
                continue
            full_text_path = str(_file_text_store_path(ref) or '').strip()
            if full_text_path and os.path.isfile(full_text_path) and full_text_path not in paths:
                paths.append(full_text_path)
        recycle_result = {}
        if paths and use_recycle:
            recycler = globals().get('_platform_admin_recycle_paths')
            if not callable(recycler):
                raise ValueError('回收站服务不可用，已保留本地文件')
            recycle_result = recycler(
                paths,
                reason='用户删除知识库文档',
                source_kind='knowledge_document',
                display_name=str(row.get('filename') or '知识库文档'),
                restore_context={'file_registry_records': registry_records, 'owner_key': str(row.get('owner_key') or '')},
            )
            cleanup['recycle'] = recycle_result.get('file') or {}
            for artifact in ((recycle_result.get('record') or {}).get('artifacts') or []):
                if isinstance(artifact, dict):
                    cleanup['local_files_deleted'].append({
                        'path': str(artifact.get('original_path') or ''),
                        'size_bytes': int(artifact.get('size_bytes') or 0),
                        'recycled': True,
                    })
        elif paths:
            for path in paths:
                try:
                    size = int(os.path.getsize(path) or 0)
                    os.remove(path)
                    cleanup['local_files_deleted'].append({
                        'path': path,
                        'size_bytes': size,
                        'recycled': False,
                    })
                except Exception as e:
                    cleanup['local_files_skipped'].append({
                        'path': path,
                        'reason': f'{type(e).__name__}: {e}',
                    })
        cleanup['registry'] = _kb_remove_file_registry_for_deleted_doc(row, records=registry_records)
        if cleanup['registry'].get('error'):
            recycle_id = str(((recycle_result.get('file') or {}).get('id') if isinstance(recycle_result, dict) else '') or '').strip()
            cancel_recycle = globals().get('_platform_admin_recycle_cancel')
            if callable(cancel_recycle) and recycle_id:
                cancel_recycle(recycle_id)
            cleanup['ok'] = False
    except Exception as e:
        cleanup['ok'] = False
        cleanup['error'] = f'{type(e).__name__}: {e}'
        try:
            app_logger.exception('[kb_delete_cleanup] failed doc=%s', row.get('id'))
        except Exception:
            pass
    return cleanup


def _kb_state(owner_key: str | None = None, space_id: str = '') -> dict:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    _kb_db_ensure()
    conn = _kb_db_connect()
    try:
        spaces = _kb_list_spaces(owner_key=owner, conn=conn)
        target_space = _kb_resolve_space(owner_key=owner, space_id=space_id, conn=conn) if str(space_id or '').strip() else _kb_ensure_default_space(owner_key=owner, conn=conn)
        space_summary = _kb_space_summary(space=target_space, owner_key=owner, conn=conn)
        docs = _kb_list_documents(owner_key=owner, space_id=str(target_space.get('id') or ''), limit=160, conn=conn)
        return {
            'ok': True,
            'owner_key': owner,
            'spaces': [_kb_space_summary(space=space, owner_key=owner, conn=conn) for space in spaces],
            'active_space': space_summary,
            'documents': docs,
        }
    finally:
        conn.close()


def _kb_delete_document(owner_key: str | None = None, doc_id: str = '') -> dict:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    raw_doc_id = str(doc_id or '').strip()
    if not raw_doc_id:
        raise ValueError('缺少文档 id')
    _kb_db_ensure()
    conn = _kb_db_connect()
    try:
        row = conn.execute('SELECT * FROM kb_documents WHERE owner_key=? AND id=? LIMIT 1', (owner, raw_doc_id)).fetchone()
        if row is None:
            raise ValueError('文档不存在或无权删除')
        row_obj = dict(row) if row is not None else {}
        space_id = str((row_obj or {}).get('space_id') or '')
        conn.execute('DELETE FROM kb_chunks WHERE doc_id=?', (raw_doc_id,))
        conn.execute('DELETE FROM kb_documents WHERE id=?', (raw_doc_id,))
        conn.execute('UPDATE kb_spaces SET updated_at=? WHERE id=?', (_utc_ts(), space_id))
        conn.commit()
        cleanup = _kb_cleanup_deleted_document_artifacts(row_obj, conn=conn)
        return {'ok': True, 'doc_id': raw_doc_id, 'space_id': space_id, 'cleanup': cleanup}
    finally:
        conn.close()
