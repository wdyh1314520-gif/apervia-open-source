# KB SQLite setup, owner resolution, spaces, and public row shaping.

def _kb_sqlite_module():
    return __import__('sqlite3')


def _kb_db_path() -> str:
    raw = str(app_getenv('KB_DB_FILE', _KB_DB_FILE_DEFAULT) or '').strip()
    return raw or _KB_DB_FILE_DEFAULT


def _kb_db_connect():
    sql = _kb_sqlite_module()
    conn = sql.connect(_kb_db_path(), timeout=30.0, check_same_thread=False)
    try:
        conn.row_factory = sql.Row
    except Exception:
        pass
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except Exception:
        pass
    try:
        conn.execute('PRAGMA synchronous=NORMAL')
    except Exception:
        pass
    return conn


def _kb_db_ensure() -> None:
    if getattr(_kb_db_ensure, '_ready', False):
        return
    with _KB_DB_GUARD:
        if getattr(_kb_db_ensure, '_ready', False):
            return
        conn = _kb_db_connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kb_spaces (
                    id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_spaces_owner_updated ON kb_spaces(owner_key, updated_at DESC)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kb_documents (
                    id TEXT PRIMARY KEY,
                    space_id TEXT NOT NULL,
                    owner_key TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    ext TEXT DEFAULT '',
                    size_bytes INTEGER DEFAULT 0,
                    char_count INTEGER DEFAULT 0,
                    chunk_count INTEGER DEFAULT 0,
                    content_hash TEXT DEFAULT '',
                    file_path TEXT DEFAULT '',
                    download_url TEXT DEFAULT '',
                    view_url TEXT DEFAULT '',
                    note TEXT DEFAULT '',
                    source TEXT DEFAULT 'upload',
                    parse_status TEXT DEFAULT 'indexed',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    indexed_at REAL DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_docs_owner_space_updated ON kb_documents(owner_key, space_id, updated_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_docs_owner_hash ON kb_documents(owner_key, space_id, content_hash)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kb_chunks (
                    id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    space_id TEXT NOT NULL,
                    owner_key TEXT NOT NULL,
                    chunk_order INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    text_lower TEXT NOT NULL,
                    char_count INTEGER DEFAULT 0,
                    created_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc_order ON kb_chunks(doc_id, chunk_order)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_chunks_owner_space_order ON kb_chunks(owner_key, space_id, chunk_order)")
            conn.commit()
        finally:
            conn.close()
        _kb_db_ensure._ready = True


def _kb_normalize_owner_key(value: str = '') -> str:
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


def _kb_current_async_owner_key() -> str:
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
            email = _kb_normalize_owner_key(rec.get('owner_email') or '')
            if email:
                return email
    except Exception:
        pass
    return ''


def _kb_owner_key() -> str:
    try:
        getter = globals().get('_current_login_account')
        if callable(getter):
            acc = getter() or {}
            email = _kb_normalize_owner_key((acc or {}).get('email') or '')
            if email:
                return email
    except Exception:
        pass
    async_owner = _kb_current_async_owner_key()
    if async_owner:
        return async_owner
    return 'anonymous'


def _kb_normalize_space_name(name: str) -> str:
    base = str(name or '').strip().replace('\r', ' ').replace('\n', ' ')
    base = re.sub(r'\s+', ' ', base)
    return (base[:48] or '默认知识库').strip() or '默认知识库'


def _kb_space_public(row) -> dict:
    if row is None:
        return {}
    if not isinstance(row, dict):
        try:
            row = dict(row)
        except Exception:
            row = {}
    return {
        'id': str((row or {}).get('id') or ''),
        'name': str((row or {}).get('name') or ''),
        'is_default': bool((row or {}).get('is_default')),
        'created_at': _fmt_ts((row or {}).get('created_at')),
        'updated_at': _fmt_ts((row or {}).get('updated_at')),
    }


def _kb_document_public(row) -> dict:
    if row is None:
        return {}
    if not isinstance(row, dict):
        try:
            row = dict(row)
        except Exception:
            row = {}
    filename = str((row or {}).get('filename') or '').strip()
    ext = str((row or {}).get('ext') or '').strip().lower()
    return {
        'id': str((row or {}).get('id') or ''),
        'space_id': str((row or {}).get('space_id') or ''),
        'filename': filename,
        'ext': ext,
        'size_bytes': int((row or {}).get('size_bytes') or 0),
        'char_count': int((row or {}).get('char_count') or 0),
        'chunk_count': int((row or {}).get('chunk_count') or 0),
        'download_url': str((row or {}).get('download_url') or ''),
        'view_url': str((row or {}).get('view_url') or ''),
        'note': str((row or {}).get('note') or ''),
        'source': str((row or {}).get('source') or ''),
        'parse_status': str((row or {}).get('parse_status') or ''),
        'created_at': _fmt_ts((row or {}).get('created_at')),
        'updated_at': _fmt_ts((row or {}).get('updated_at')),
        'indexed_at': _fmt_ts((row or {}).get('indexed_at')),
    }


def _kb_ensure_default_space(owner_key: str | None = None, conn=None) -> dict:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    _kb_db_ensure()
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        row = conn.execute(
            'SELECT * FROM kb_spaces WHERE owner_key=? AND is_default=1 ORDER BY updated_at DESC LIMIT 1',
            (owner,),
        ).fetchone()
        if row is None:
            now = _utc_ts()
            row = {
                'id': 'space_' + uuid.uuid4().hex,
                'owner_key': owner,
                'name': '默认知识库',
                'is_default': 1,
                'created_at': now,
                'updated_at': now,
            }
            conn.execute(
                'INSERT INTO kb_spaces (id, owner_key, name, is_default, created_at, updated_at) VALUES (?,?,?,?,?,?)',
                (row['id'], owner, row['name'], 1, now, now),
            )
            conn.commit()
        return dict(row)
    finally:
        if own_conn:
            conn.close()


def _kb_resolve_space(owner_key: str | None = None, space_id: str = '', conn=None) -> dict:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    _kb_db_ensure()
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        raw_space_id = str(space_id or '').strip()
        if raw_space_id:
            row = conn.execute(
                'SELECT * FROM kb_spaces WHERE owner_key=? AND id=? LIMIT 1',
                (owner, raw_space_id),
            ).fetchone()
            if row is not None:
                return dict(row)
        return _kb_ensure_default_space(owner_key=owner, conn=conn)
    finally:
        if own_conn:
            conn.close()


def _kb_list_spaces(owner_key: str | None = None, conn=None) -> list[dict]:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    _kb_db_ensure()
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        _kb_ensure_default_space(owner_key=owner, conn=conn)
        rows = conn.execute(
            'SELECT * FROM kb_spaces WHERE owner_key=? ORDER BY is_default DESC, updated_at DESC, created_at DESC',
            (owner,),
        ).fetchall()
        return [dict(row) for row in (rows or [])]
    finally:
        if own_conn:
            conn.close()


def _kb_create_space(name: str, owner_key: str | None = None) -> dict:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    title = _kb_normalize_space_name(name)
    _kb_db_ensure()
    conn = _kb_db_connect()
    try:
        now = _utc_ts()
        row = {
            'id': 'space_' + uuid.uuid4().hex,
            'owner_key': owner,
            'name': title,
            'is_default': 0,
            'created_at': now,
            'updated_at': now,
        }
        conn.execute(
            'INSERT INTO kb_spaces (id, owner_key, name, is_default, created_at, updated_at) VALUES (?,?,?,?,?,?)',
            (row['id'], owner, title, 0, now, now),
        )
        conn.commit()
        return _kb_space_public(row)
    finally:
        conn.close()



def _kb_delete_space(owner_key: str | None = None, space_id: str = '') -> dict:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    raw_space_id = str(space_id or '').strip()
    if not raw_space_id:
        raise ValueError('缺少知识库 id')
    _kb_db_ensure()
    conn = _kb_db_connect()
    try:
        row = conn.execute('SELECT * FROM kb_spaces WHERE owner_key=? AND id=? LIMIT 1', (owner, raw_space_id)).fetchone()
        if row is None:
            next_space = _kb_ensure_default_space(owner_key=owner, conn=conn)
            next_space_id = str((next_space or {}).get('id') or '')
            conn.commit()
            return {
                'ok': True,
                'space_id': raw_space_id,
                'deleted_documents': 0,
                'next_space_id': next_space_id,
                'already_deleted': True,
                'cleanup': [],
            }
        space_obj = dict(row)
        if bool((space_obj or {}).get('is_default')):
            raise ValueError('默认知识库不能删除')
        doc_rows = [dict(r) for r in (conn.execute('SELECT * FROM kb_documents WHERE owner_key=? AND space_id=?', (owner, raw_space_id)).fetchall() or [])]
        doc_ids = [str((doc or {}).get('id') or '').strip() for doc in doc_rows if str((doc or {}).get('id') or '').strip()]
        if doc_ids:
            placeholders = ','.join(['?'] * len(doc_ids))
            conn.execute(f'DELETE FROM kb_chunks WHERE doc_id IN ({placeholders})', doc_ids)
        conn.execute('DELETE FROM kb_documents WHERE owner_key=? AND space_id=?', (owner, raw_space_id))
        conn.execute('DELETE FROM kb_spaces WHERE owner_key=? AND id=?', (owner, raw_space_id))
        next_space = _kb_ensure_default_space(owner_key=owner, conn=conn)
        next_space_id = str((next_space or {}).get('id') or '')
        conn.commit()
        cleanups = []
        for doc in doc_rows:
            cleanups.append(_kb_cleanup_deleted_document_artifacts(doc, conn=conn))
        return {
            'ok': True,
            'space_id': raw_space_id,
            'deleted_documents': len(doc_rows),
            'next_space_id': next_space_id,
            'cleanup': cleanups[:20],
        }
    finally:
        conn.close()
