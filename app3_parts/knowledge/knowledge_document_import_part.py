# KB document quota, import, list, get, and active document selection.

_KB_IMAGE_EXTENSIONS = frozenset({
    '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg', '.tif', '.tiff',
    '.ico', '.jfif', '.heic', '.heif',
})


def _kb_normalize_document_ext(ext: str = '') -> str:
    raw = str(ext or '').strip().lower()
    if raw and not raw.startswith('.'):
        raw = '.' + raw
    return raw


def _kb_document_ext_allowed(ext: str = '') -> bool:
    return _kb_normalize_document_ext(ext) not in _KB_IMAGE_EXTENSIONS


def _kb_sql_non_image_clause(column: str = 'ext') -> tuple[str, list[str]]:
    safe_column = str(column or 'ext').strip()
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', safe_column):
        raise ValueError('invalid knowledge-base SQL column')
    values = sorted(_KB_IMAGE_EXTENSIONS)
    placeholders = ','.join('?' for _ in values)
    return f"LOWER(COALESCE({safe_column}, '')) NOT IN ({placeholders})", values

def _kb_should_search(query: str) -> bool:
    s = str(query or '').strip()
    if len(s) < 2:
        return False
    sl = s.lower()
    if re.fullmatch(r'[?？!！。,.，\s]+', s):
        return False
    smalltalk = [
        'hi', 'hello', '你好', '您好', '在吗', '在嗎', '谢谢', '謝謝', '收到', '好的', 'ok', 'okay', '嗯', '哦', '哈',
    ]
    if len(s) <= 12 and any(sl == item or s == item for item in smalltalk):
        return False
    return True


def _kb_space_summary(space: dict | None = None, owner_key: str | None = None, space_id: str = '', conn=None) -> dict:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    _kb_db_ensure()
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        target = dict(space or _kb_resolve_space(owner_key=owner, space_id=space_id, conn=conn))
        allowed_clause, allowed_params = _kb_sql_non_image_clause('ext')
        row = conn.execute(
            f'SELECT COUNT(1) AS doc_count, COALESCE(SUM(chunk_count), 0) AS chunk_count, COALESCE(SUM(char_count), 0) AS char_count FROM kb_documents WHERE owner_key=? AND space_id=? AND {allowed_clause}',
            [owner, str(target.get('id') or ''), *allowed_params],
        ).fetchone()
        row_obj = dict(row) if row is not None else {}
        base = _kb_space_public(target)
        base['doc_count'] = int((row_obj or {}).get('doc_count') or 0)
        base['chunk_count'] = int((row_obj or {}).get('chunk_count') or 0)
        base['char_count'] = int((row_obj or {}).get('char_count') or 0)
        return base
    finally:
        if own_conn:
            conn.close()


def _kb_owner_used_bytes(owner_key: str, conn=None) -> int:
    owner = str(owner_key or '').strip().lower() or 'anonymous'
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        row = conn.execute(
            'SELECT COALESCE(SUM(size_bytes), 0) AS file_bytes, COALESCE(SUM(char_count), 0) AS chars FROM kb_documents WHERE owner_key=?',
            (owner,),
        ).fetchone()
        obj = dict(row) if row is not None else {}
        file_bytes = int((obj or {}).get('file_bytes') or 0)
        char_bytes = int((obj or {}).get('chars') or 0)
        return max(file_bytes, char_bytes)
    finally:
        if own_conn:
            conn.close()



def _kb_total_used_bytes(conn=None) -> int:
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        rows = conn.execute('SELECT size_bytes, char_count FROM kb_documents').fetchall()
        total = 0
        for row in rows or []:
            obj = dict(row) if row is not None else {}
            total += max(int((obj or {}).get('size_bytes') or 0), int((obj or {}).get('char_count') or 0))
        return max(0, int(total or 0))
    finally:
        if own_conn:
            conn.close()


def _kb_prune_document_row_for_quota(conn, row) -> dict:
    obj = dict(row) if row is not None else {}
    doc_id = str((obj or {}).get('id') or '').strip()
    if not doc_id:
        return {}
    space_id = str((obj or {}).get('space_id') or '')
    size = max(int((obj or {}).get('size_bytes') or 0), int((obj or {}).get('char_count') or 0))
    conn.execute('DELETE FROM kb_chunks WHERE doc_id=?', (doc_id,))
    conn.execute('DELETE FROM kb_documents WHERE id=?', (doc_id,))
    if space_id:
        conn.execute('UPDATE kb_spaces SET updated_at=? WHERE id=?', (_utc_ts(), space_id))
    return {
        'doc_id': doc_id,
        'filename': str((obj or {}).get('filename') or ''),
        'owner_key': str((obj or {}).get('owner_key') or ''),
        'space_id': space_id,
        'size_bytes': size,
        '_cleanup_row': obj,
    }


def _kb_prune_old_documents_for_quota(owner_key: str, incoming_bytes: int, *, owner_max: int = 0, db_max: int = 0, replacing_doc_id: str = '', conn=None) -> dict:
    owner = str(owner_key or '').strip().lower() or 'anonymous'
    incoming = max(0, int(incoming_bytes or 0))
    exclude_id = str(replacing_doc_id or '').strip()
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    deleted: list[dict] = []
    try:
        if owner_max > 0:
            guard = 0
            while _kb_owner_used_bytes(owner, conn=conn) + incoming > int(owner_max or 0):
                guard += 1
                if guard > 1000:
                    break
                if exclude_id:
                    row = conn.execute('SELECT * FROM kb_documents WHERE owner_key=? AND id<>? ORDER BY updated_at ASC, created_at ASC LIMIT 1', (owner, exclude_id)).fetchone()
                else:
                    row = conn.execute('SELECT * FROM kb_documents WHERE owner_key=? ORDER BY updated_at ASC, created_at ASC LIMIT 1', (owner,)).fetchone()
                if row is None:
                    break
                item = _kb_prune_document_row_for_quota(conn, row)
                if item:
                    deleted.append(item)
                else:
                    break
        if db_max > 0:
            guard = 0
            while _kb_total_used_bytes(conn=conn) + incoming > int(db_max or 0):
                guard += 1
                if guard > 1000:
                    break
                if exclude_id:
                    row = conn.execute('SELECT * FROM kb_documents WHERE id<>? ORDER BY updated_at ASC, created_at ASC LIMIT 1', (exclude_id,)).fetchone()
                else:
                    row = conn.execute('SELECT * FROM kb_documents ORDER BY updated_at ASC, created_at ASC LIMIT 1').fetchone()
                if row is None:
                    break
                item = _kb_prune_document_row_for_quota(conn, row)
                if item:
                    deleted.append(item)
                else:
                    break
        if deleted:
            conn.commit()
            for item in deleted:
                cleanup_row = dict((item or {}).pop('_cleanup_row', {}) or {})
                try:
                    item['cleanup'] = _kb_cleanup_deleted_document_artifacts(cleanup_row, conn=conn, use_recycle=False) if cleanup_row else {}
                except Exception as e:
                    item['cleanup'] = {'ok': False, 'error': f'{type(e).__name__}: {e}'}
            try:
                conn.execute('VACUUM')
            except Exception:
                pass
        return {'ok': True, 'deleted': deleted, 'deleted_count': len(deleted), 'freed_bytes': sum(max(0, int((item or {}).get('size_bytes') or 0)) for item in deleted)}
    finally:
        if own_conn:
            conn.close()

def _kb_check_import_quota(owner_key: str, incoming_bytes: int, *, replacing_doc_id: str = '', conn=None) -> None:
    incoming = max(0, int(incoming_bytes or 0))
    single_max = _storage_quota_int('KB_SINGLE_IMPORT_MAX_BYTES', 80 * 1024 * 1024, minimum=1024 * 1024) if callable(globals().get('_storage_quota_int')) else 80 * 1024 * 1024
    owner_max = _storage_quota_int('KB_OWNER_MAX_BYTES', 512 * 1024 * 1024, minimum=16 * 1024 * 1024) if callable(globals().get('_storage_quota_int')) else 512 * 1024 * 1024
    db_max = _storage_quota_int('KB_DB_MAX_BYTES', 2 * 1024 * 1024 * 1024, minimum=64 * 1024 * 1024) if callable(globals().get('_storage_quota_int')) else 2 * 1024 * 1024 * 1024
    if incoming > single_max:
        raise StorageQuotaError(f'单篇知识库内容过大：{_storage_quota_human(incoming)}，上限 {_storage_quota_human(single_max)}。')
    replaced = 0
    if replacing_doc_id and conn is not None:
        try:
            row = conn.execute('SELECT size_bytes, char_count FROM kb_documents WHERE owner_key=? AND id=? LIMIT 1', (owner_key, replacing_doc_id)).fetchone()
            obj = dict(row) if row is not None else {}
            replaced = max(int((obj or {}).get('size_bytes') or 0), int((obj or {}).get('char_count') or 0))
        except Exception:
            replaced = 0
    prune_detail = {}
    owner_used = max(0, _kb_owner_used_bytes(owner_key, conn=conn) - replaced)
    db_used = _kb_total_used_bytes(conn=conn)
    if owner_used + incoming > owner_max or db_used + incoming > db_max:
        prune_detail = _kb_prune_old_documents_for_quota(owner_key, incoming, owner_max=owner_max, db_max=db_max, replacing_doc_id=replacing_doc_id, conn=conn)
        owner_used = max(0, _kb_owner_used_bytes(owner_key, conn=conn) - replaced)
        db_used = _kb_total_used_bytes(conn=conn)
    if owner_used + incoming > owner_max:
        raise StorageQuotaError(f'当前账号知识库空间暂时不足：已用 {_storage_quota_human(owner_used)} / {_storage_quota_human(owner_max)}，本次需要 {_storage_quota_human(incoming)}。系统已自动回收最旧知识库文档，但当前请求仍超过可自动腾出的空间。')
    if db_used + incoming > db_max:
        raise StorageQuotaError(f'知识库总空间暂时不足：已用 {_storage_quota_human(db_used)} / {_storage_quota_human(db_max)}。系统已自动回收最旧知识库文档，但当前请求仍超过可自动腾出的空间。')
    system_checker = globals().get('_storage_quota_check_system')
    if callable(system_checker):
        system_checker(incoming_bytes=incoming, path=_kb_db_path(), cleanup=True)
    app_checker = globals().get('_storage_quota_check_app_total')
    if callable(app_checker):
        app_checker(incoming_bytes=incoming)
    owner_checker = globals().get('_storage_quota_require_owner_write')
    if callable(owner_checker):
        tracked = _storage_quota_owner_tracked_bytes(owner_key) if callable(globals().get('_storage_quota_owner_tracked_bytes')) else 0
        chat_bytes = _storage_quota_owner_chat_bytes(owner_key) if callable(globals().get('_storage_quota_owner_chat_bytes')) else 0
        owner_checker(owner_key, incoming_bytes=incoming, kind='knowledge_base', current_bytes=max(0, int(tracked or 0) + int(chat_bytes or 0) + int(owner_used or 0)))


def _kb_import_document(*, owner_key: str | None = None, space_id: str = '', filename: str = '', ext: str = '', size_bytes: int = 0, file_path: str = '', download_url: str = '', view_url: str = '', text: str = '', note: str = '', source: str = 'upload') -> dict:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    clean_name = str(filename or '').strip() or '未命名文件'
    clean_ext = _kb_normalize_document_ext(ext or _ext_of(clean_name) or '')
    if not _kb_document_ext_allowed(clean_ext):
        raise ValueError('图片文件只保留在资料库，不能加入知识库')
    content_text = truncate_text(str(text or '').replace('\r\n', '\n').replace('\r', '\n').strip(), max_chars=220000)
    clean_note = truncate_text(str(note or '').strip(), max_chars=400)
    _kb_db_ensure()
    conn = _kb_db_connect()
    try:
        space = _kb_resolve_space(owner_key=owner, space_id=space_id, conn=conn)
        now = _utc_ts()
        content_hash = hashlib.sha1((content_text or f'{clean_name}|{clean_note}|{clean_ext}').encode('utf-8', 'ignore')).hexdigest()
        existed = conn.execute(
            'SELECT id FROM kb_documents WHERE owner_key=? AND space_id=? AND content_hash=? ORDER BY updated_at DESC LIMIT 1',
            (owner, str(space.get('id') or ''), content_hash),
        ).fetchone()
        existed_obj = dict(existed) if existed is not None else {}
        doc_id = str((existed_obj or {}).get('id') or '') or ('doc_' + uuid.uuid4().hex)
        incoming_bytes = max(int(size_bytes or 0), len(content_text.encode('utf-8', 'ignore')))
        _kb_check_import_quota(owner, incoming_bytes, replacing_doc_id=doc_id if existed is not None else '', conn=conn)
        chunks = _history_file_split_chunks(content_text, target_chars=1100, overlap=140) if content_text else []
        if not chunks and content_text:
            chunks = [truncate_text(content_text, max_chars=1600)]
        parse_status = 'indexed' if chunks else ('empty' if content_text else 'no_text')
        if existed is None:
            conn.execute(
                'INSERT INTO kb_documents (id, space_id, owner_key, filename, ext, size_bytes, char_count, chunk_count, content_hash, file_path, download_url, view_url, note, source, parse_status, created_at, updated_at, indexed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (
                    doc_id, str(space.get('id') or ''), owner, clean_name, clean_ext, int(size_bytes or 0),
                    len(content_text), len(chunks), content_hash, str(file_path or ''), str(download_url or ''), str(view_url or ''),
                    clean_note, str(source or 'upload'), parse_status, now, now, now,
                ),
            )
        else:
            conn.execute(
                'UPDATE kb_documents SET filename=?, ext=?, size_bytes=?, char_count=?, chunk_count=?, content_hash=?, file_path=?, download_url=?, view_url=?, note=?, source=?, parse_status=?, updated_at=?, indexed_at=? WHERE id=?',
                (
                    clean_name, clean_ext, int(size_bytes or 0), len(content_text), len(chunks), content_hash,
                    str(file_path or ''), str(download_url or ''), str(view_url or ''), clean_note, str(source or 'upload'),
                    parse_status, now, now, doc_id,
                ),
            )
            conn.execute('DELETE FROM kb_chunks WHERE doc_id=?', (doc_id,))
        for idx, chunk in enumerate(chunks):
            piece = str(chunk or '').strip()
            if not piece:
                continue
            conn.execute(
                'INSERT INTO kb_chunks (id, doc_id, space_id, owner_key, chunk_order, text, text_lower, char_count, created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                (
                    'chunk_' + uuid.uuid4().hex,
                    doc_id,
                    str(space.get('id') or ''),
                    owner,
                    idx,
                    piece,
                    piece.lower(),
                    len(piece),
                    now,
                ),
            )
        conn.execute('UPDATE kb_spaces SET updated_at=? WHERE id=?', (now, str(space.get('id') or '')))
        conn.commit()
        row = conn.execute('SELECT * FROM kb_documents WHERE id=? LIMIT 1', (doc_id,)).fetchone()
        return {
            'ok': True,
            'space': _kb_space_summary(space=space, owner_key=owner, conn=conn),
            'document': _kb_document_public(row),
            'imported': True,
            'deduped': existed is not None,
        }
    finally:
        conn.close()


def _kb_list_documents(owner_key: str | None = None, space_id: str = '', limit: int = 120, conn=None) -> list[dict]:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    _kb_db_ensure()
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        allowed_clause, allowed_params = _kb_sql_non_image_clause('ext')
        params = [owner, *allowed_params]
        sql = f'SELECT * FROM kb_documents WHERE owner_key=? AND {allowed_clause}'
        if str(space_id or '').strip():
            sql += ' AND space_id=?'
            params.append(str(space_id or '').strip())
        sql += ' ORDER BY updated_at DESC, created_at DESC LIMIT ?'
        params.append(max(1, min(int(limit or 120), 500)))
        rows = conn.execute(sql, params).fetchall()
        return [_kb_document_public(row) for row in (rows or [])]
    finally:
        if own_conn:
            conn.close()

def _kb_get_document(owner_key: str | None = None, doc_id: str = '', conn=None) -> dict:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    raw_doc_id = str(doc_id or '').strip()
    if not raw_doc_id:
        return {}
    _kb_db_ensure()
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        allowed_clause, allowed_params = _kb_sql_non_image_clause('ext')
        row = conn.execute(
            f'SELECT * FROM kb_documents WHERE owner_key=? AND id=? AND {allowed_clause} LIMIT 1',
            [owner, raw_doc_id, *allowed_params],
        ).fetchone()
        return _kb_document_public(row)
    finally:
        if own_conn:
            conn.close()


def _kb_pick_active_document(owner_key: str | None = None, *, space_id: str = '', doc_id: str = '', query: str = '', conn=None) -> dict:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    _kb_db_ensure()
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        target_space_id = str(space_id or '').strip()
        direct = _kb_get_document(owner_key=owner, doc_id=doc_id, conn=conn) if str(doc_id or '').strip() else {}
        if direct and (not target_space_id or str(direct.get('space_id') or '') == target_space_id):
            return direct
        docs = _kb_list_documents(owner_key=owner, space_id=target_space_id, limit=24, conn=conn)
        if not docs:
            return {}
        if len(docs) == 1:
            return dict(docs[0])
        lowered_query = str(query or '').strip().lower()
        if not lowered_query:
            return {}
        ranked = []
        for doc in docs:
            filename = str((doc or {}).get('filename') or '').strip()
            if not filename:
                continue
            score = 0.0
            filename_lower = filename.lower()
            if filename_lower and filename_lower in lowered_query:
                score += 18.0
            stem_hits = 0
            for stem in _history_file_stems(filename):
                if stem and stem in lowered_query:
                    stem_hits += 1
                    score += 5.0
            if stem_hits:
                score += min(4.0, stem_hits * 1.2)
            if _history_file_query_looks_referential(lowered_query, [{'filename': filename}]):
                score += 1.0
            if score <= 0:
                continue
            ranked.append((score, doc))
        ranked.sort(key=lambda item: (item[0], str((item[1] or {}).get('updated_at') or '')), reverse=True)
        return dict(ranked[0][1]) if ranked else {}
    finally:
        if own_conn:
            conn.close()
