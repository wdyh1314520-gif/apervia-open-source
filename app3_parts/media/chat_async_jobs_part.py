# Split from app3_parts/media/async_pullback_upload_server_part.py.
# Purpose: background chat async job state, persistence, event buffering, worker slots, and worker loop.
# Loaded by async_pullback_upload_server_part.py via _exec_split_file(...), sharing the original global namespace.

# Auto-split from app3.py lines 27697-30616.
# Purpose: background chat async jobs, image pullback jobs, upload/chunk routes, waitress startup, legacy fast/streaming patch tail.
# Loaded by app3.py via _exec_split_file(...), sharing the original global namespace.

# ==============================
# BACKGROUND CHAT JOBS (detach from page lifecycle)
# ==============================
_CHAT_ASYNC_JOB_LOCK = threading.RLock()
_CHAT_ASYNC_JOBS: dict[str, dict] = {}
_CHAT_ASYNC_JOB_CONDS: dict[str, threading.Condition] = {}
_CHAT_ASYNC_JOB_RUNTIME: dict[str, dict] = {}
_CHAT_ASYNC_JOB_THREAD_LOCAL = threading.local()
_CHAT_ASYNC_JOB_EVENTS_LIMIT = 2400
_CHAT_ASYNC_JOB_TTL_S = 6 * 3600
_CHAT_ASYNC_COMPLETED_DISCOVERY_TTL_S = 6 * 3600
_CHAT_ASYNC_POLL_WAIT_MAX_MS = 25000
_CHAT_ASYNC_POLL_WAIT_PUBLIC_MS = 3500
_CHAT_ASYNC_POLL_AFTER_EVENT_MS = 10
_CHAT_ASYNC_POLL_AFTER_IDLE_MS = 16
_CHAT_ASYNC_POLL_AFTER_PUBLIC_EVENT_MS = 8
_CHAT_ASYNC_POLL_AFTER_PUBLIC_IDLE_MS = 12
_CHAT_ASYNC_HEARTBEAT_INTERVAL_S = 4.0
_CHAT_ASYNC_HEARTBEAT_IDLE_S = 4.5
_CHAT_ASYNC_DELTA_MIN_CHARS = 4
_CHAT_ASYNC_DELTA_SOFT_CHARS = 16
_CHAT_ASYNC_DELTA_HARD_CHARS = 28
_CHAT_ASYNC_DELTA_PUBLIC_MIN_CHARS = 3
_CHAT_ASYNC_DELTA_PUBLIC_SOFT_CHARS = 5
_CHAT_ASYNC_DELTA_PUBLIC_HARD_CHARS = 8
_CHAT_ASYNC_DELTA_PUBLIC_FORCE_FLUSH_MS = 90
_CHAT_ASYNC_DELTA_SOFT_BREAKS = set("。！？!?；;：:，,、\n\r\t ")
CHAT_ASYNC_STATE_FILE = _app_data_path('chat_async_jobs_state.json')
CHAT_ASYNC_DB_FILE = _app_data_path('chat_async_jobs.db')
_CHAT_ASYNC_PERSIST_LOCK = threading.Lock()
_CHAT_ASYNC_PERSIST_DEBOUNCE_S = 0.8


try:
    APP_DEFAULTS.setdefault('CHAT_ASYNC_WORKER_MAX_CONCURRENT', '4')
    APP_DEFAULTS.setdefault('CHAT_ASYNC_WORKER_QUEUE_STATUS_INTERVAL_S', '8')
except Exception:
    pass


def _chat_async_prompt_cache_message_text_for_audit(message: dict | None = None, *, max_chars: int = 180) -> str:
    if not isinstance(message, dict):
        return ''
    content = message.get('content')
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if str(item.get('type') or '').strip() in {'text', 'input_text'}:
                    parts.append(str(item.get('text') or ''))
                elif item.get('text') is not None:
                    parts.append(str(item.get('text') or ''))
            elif isinstance(item, str):
                parts.append(item)
        text = '\n'.join(parts)
    elif isinstance(content, dict):
        if str(content.get('_kind') or '') == 'file':
            text = '[file] ' + str(content.get('filename') or content.get('saved_filename') or '')
        else:
            try:
                text = json.dumps(content, ensure_ascii=False, sort_keys=True)
            except Exception:
                text = str(content)
    else:
        text = ''
    return re.sub(r'\s+', ' ', str(text or '')).strip()[:max_chars]


def _chat_async_prompt_cache_message_digest_for_audit(message: dict | None = None) -> str:
    try:
        raw = json.dumps(message or {}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    except Exception:
        raw = str(message or '')
    try:
        return hashlib.sha256(raw.encode('utf-8', 'ignore')).hexdigest()[:12]
    except Exception:
        return ''


def _chat_async_log_prompt_cache_request_messages(stage: str = '', messages: list | None = None, payload: dict | None = None) -> None:
    try:
        rows = [m for m in (messages or []) if isinstance(m, dict)]
        payload_messages = payload.get('messages') if isinstance(payload, dict) and isinstance(payload.get('messages'), list) else []
        role_counts: dict[str, int] = {}
        for msg in rows:
            role = str(msg.get('role') or '').strip().lower() or 'unknown'
            role_counts[role] = role_counts.get(role, 0) + 1
        tail = []
        for idx, msg in list(enumerate(rows))[-8:]:
            tail.append({
                'idx': idx,
                'role': str(msg.get('role') or '').strip().lower(),
                'kind': str((msg.get('_kind') if msg.get('_kind') is not None else '') or '').strip(),
                'hash': _chat_async_prompt_cache_message_digest_for_audit(msg),
                'text': _chat_async_prompt_cache_message_text_for_audit(msg),
            })
        app_logger.info(
            '[PROMPT_CACHE_REQUEST_MESSAGES] stage=%s payload_messages=%s messages=%s roles=%s tail=%s',
            str(stage or ''),
            len(payload_messages or []),
            len(rows),
            json.dumps(role_counts, ensure_ascii=False, sort_keys=True),
            json.dumps(tail, ensure_ascii=False, sort_keys=True),
        )
    except Exception:
        pass

_CHAT_ASYNC_WORKER_SLOT_LOCK = threading.Lock()
_CHAT_ASYNC_WORKER_SLOT_ACTIVE = 0
_CHAT_ASYNC_WORKER_SLOT_WAITING = 0


def _chat_async_worker_slot_limit() -> int:
    try:
        return max(1, min(int(str(app_getenv('CHAT_ASYNC_WORKER_MAX_CONCURRENT', '4') or '4')), 24))
    except Exception:
        return 4


_CHAT_ASYNC_WORKER_SEMAPHORE = threading.BoundedSemaphore(_chat_async_worker_slot_limit())


def _chat_async_worker_queue_status_interval_s() -> float:
    try:
        return max(2.0, min(float(str(app_getenv('CHAT_ASYNC_WORKER_QUEUE_STATUS_INTERVAL_S', '8') or '8')), 60.0))
    except Exception:
        return 8.0


def _chat_async_worker_slot_snapshot() -> dict:
    with _CHAT_ASYNC_WORKER_SLOT_LOCK:
        return {
            'active': int(_CHAT_ASYNC_WORKER_SLOT_ACTIVE),
            'waiting': int(_CHAT_ASYNC_WORKER_SLOT_WAITING),
            'limit': _chat_async_worker_slot_limit(),
        }


def _chat_async_worker_slot_acquire(job_key: str = '') -> bool:
    global _CHAT_ASYNC_WORKER_SLOT_ACTIVE, _CHAT_ASYNC_WORKER_SLOT_WAITING
    key = str(job_key or '').strip()
    last_notice = 0.0
    with _CHAT_ASYNC_WORKER_SLOT_LOCK:
        _CHAT_ASYNC_WORKER_SLOT_WAITING += 1
        waiting_now = int(_CHAT_ASYNC_WORKER_SLOT_WAITING)
        active_now = int(_CHAT_ASYNC_WORKER_SLOT_ACTIVE)
    try:
        if key:
            _chat_async_append_event(key, 'status', {
                'text': '服务器正在处理较多任务，已进入后台排队…',
                'queued': True,
                'worker_queue': {'waiting': waiting_now, 'active': active_now, 'limit': _chat_async_worker_slot_limit()},
            })
    except Exception:
        pass
    while True:
        acquired = _CHAT_ASYNC_WORKER_SEMAPHORE.acquire(timeout=1.0)
        if acquired:
            with _CHAT_ASYNC_WORKER_SLOT_LOCK:
                _CHAT_ASYNC_WORKER_SLOT_WAITING = max(0, _CHAT_ASYNC_WORKER_SLOT_WAITING - 1)
                _CHAT_ASYNC_WORKER_SLOT_ACTIVE += 1
            try:
                if key:
                    _chat_async_append_event(key, 'status', {
                        'text': '后台任务已获得执行资源，开始处理…',
                        'queued': False,
                        'worker_queue': _chat_async_worker_slot_snapshot(),
                    })
            except Exception:
                pass
            return True
        try:
            if key:
                with _CHAT_ASYNC_JOB_LOCK:
                    rec = _CHAT_ASYNC_JOBS.get(key) or {}
                    if bool(rec.get('stop_requested')):
                        raise RuntimeError('__async_chat_job_stopped__')
        except RuntimeError:
            with _CHAT_ASYNC_WORKER_SLOT_LOCK:
                _CHAT_ASYNC_WORKER_SLOT_WAITING = max(0, _CHAT_ASYNC_WORKER_SLOT_WAITING - 1)
            raise
        now_ts = time.time()
        if key and (now_ts - last_notice) >= _chat_async_worker_queue_status_interval_s():
            last_notice = now_ts
            try:
                _chat_async_append_event(key, 'status', {
                    'text': '后台仍在排队，连接可关闭，任务会继续保留…',
                    'queued': True,
                    'worker_queue': _chat_async_worker_slot_snapshot(),
                    'heartbeat': True,
                })
            except Exception:
                pass


def _chat_async_worker_slot_release(job_key: str = '') -> None:
    global _CHAT_ASYNC_WORKER_SLOT_ACTIVE
    try:
        _CHAT_ASYNC_WORKER_SEMAPHORE.release()
    except Exception:
        pass
    with _CHAT_ASYNC_WORKER_SLOT_LOCK:
        _CHAT_ASYNC_WORKER_SLOT_ACTIVE = max(0, _CHAT_ASYNC_WORKER_SLOT_ACTIVE - 1)


def _chat_async_sqlite_module():
    return __import__('sqlite3')


def _chat_async_db_connect():
    sql = _chat_async_sqlite_module()
    conn = sql.connect(CHAT_ASYNC_DB_FILE, timeout=30.0, check_same_thread=False)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except Exception:
        pass
    try:
        conn.execute('PRAGMA synchronous=NORMAL')
    except Exception:
        pass
    return conn


def _chat_async_db_ensure() -> None:
    if getattr(_chat_async_db_ensure, '_ready', False):
        return
    with _CHAT_ASYNC_PERSIST_LOCK:
        if getattr(_chat_async_db_ensure, '_ready', False):
            return
        conn = _chat_async_db_connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_async_jobs (
                    job_id TEXT PRIMARY KEY,
                    created_at REAL DEFAULT 0,
                    updated_at REAL DEFAULT 0,
                    done INTEGER DEFAULT 0,
                    status TEXT DEFAULT '',
                    status_text TEXT DEFAULT '',
                    error TEXT DEFAULT '',
                    full_text TEXT DEFAULT '',
                    payload_json TEXT DEFAULT '',
                    events_json TEXT DEFAULT '',
                    artifacts_json TEXT DEFAULT '',
                    meta_json TEXT DEFAULT '',
                    owner_json TEXT DEFAULT '',
                    scope TEXT DEFAULT '',
                    stop_requested INTEGER DEFAULT 0,
                    recovered_from_disk INTEGER DEFAULT 0
                )
            """)
            for column_sql in (
                "ALTER TABLE chat_async_jobs ADD COLUMN payload_json TEXT DEFAULT ''",
                "ALTER TABLE chat_async_jobs ADD COLUMN owner_key TEXT DEFAULT ''",
                "ALTER TABLE chat_async_jobs ADD COLUMN conversation_id TEXT DEFAULT ''",
                "ALTER TABLE chat_async_jobs ADD COLUMN turn_id TEXT DEFAULT ''",
                "ALTER TABLE chat_async_jobs ADD COLUMN conversation_mode TEXT DEFAULT ''",
                "ALTER TABLE chat_async_jobs ADD COLUMN active_key TEXT DEFAULT ''",
            ):
                try:
                    conn.execute(column_sql)
                except Exception:
                    pass
            try:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_chat_async_conversation_runs "
                    "ON chat_async_jobs(owner_key, conversation_id, updated_at DESC)"
                )
            except Exception:
                pass
            try:
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_async_turn "
                    "ON chat_async_jobs(owner_key, conversation_id, turn_id) "
                    "WHERE owner_key <> '' AND conversation_id <> '' AND turn_id <> ''"
                )
            except Exception:
                # 旧数据库如果已有重复任务，启动不能因此失败；运行时协调器仍会收敛到最新任务。
                pass
            conn.commit()
            setattr(_chat_async_db_ensure, '_ready', True)
        finally:
            conn.close()


def _chat_async_owner_public_snapshot(owner: dict | None = None) -> dict:
    row = dict(owner or {})
    return {
        'email': _normalize_login_email(row.get('email') or ''),
        'device_id': str(row.get('device_id') or '').strip()[:160],
        'is_local_admin_request': bool(row.get('is_local_admin_request')),
        'allow_private_search_targets': bool(row.get('allow_private_search_targets')),
    }


def _chat_async_record_for_persist(rec: dict | None = None) -> dict | None:
    if not isinstance(rec, dict):
        return None
    try:
        events_limit = max(40, min(_CHAT_ASYNC_JOB_EVENTS_LIMIT, 400))
    except Exception:
        events_limit = 240
    payload = {
        'job_id': str(rec.get('job_id') or '').strip(),
        'created_at': float(rec.get('created_at') or 0.0),
        'updated_at': float(rec.get('updated_at') or 0.0),
        'done': bool(rec.get('done')),
        'status': str(rec.get('status') or 'queued').strip().lower() or 'queued',
        'status_text': str(rec.get('status_text') or '').strip()[:400],
        'error': str(rec.get('error') or '').strip()[:4000],
        'full_text': str(rec.get('full_text') or ''),
        'events': [dict(x) for x in (rec.get('events') or []) if isinstance(x, dict)][-events_limit:],
        'artifacts': [dict(x) for x in (rec.get('artifacts') or []) if isinstance(x, dict)],
        'meta': dict(rec.get('meta') or {}) if isinstance(rec.get('meta'), dict) else {},
        'owner': _chat_async_owner_public_snapshot(rec.get('owner') if isinstance(rec.get('owner'), dict) else {
            'email': rec.get('owner_email'),
            'device_id': rec.get('owner_device_id'),
            'is_local_admin_request': rec.get('owner_is_local_admin_request'),
            'allow_private_search_targets': rec.get('owner_allow_private_search_targets'),
        }),
        'scope': _normalize_upload_scope(rec.get('scope') or ''),
        'stop_requested': bool(rec.get('stop_requested')),
        'recovered_from_disk': bool(rec.get('recovered_from_disk')),
        'owner_key': str(rec.get('owner_key') or '').strip()[:320],
        'conversation_id': str(rec.get('conversation_id') or '').strip()[:180],
        'turn_id': str(rec.get('turn_id') or '').strip()[:240],
        'conversation_mode': str(rec.get('conversation_mode') or '').strip()[:40],
        'active_key': str(rec.get('active_key') or '').strip()[:520] if not bool(rec.get('done')) else '',
    }
    if not payload['job_id']:
        return None
    return payload


def _chat_async_json_dumps(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return 'null'


def _chat_async_json_loads(raw: str, default):
    try:
        value = json.loads(str(raw or ''))
    except Exception:
        return default
    return value


def _chat_async_apply_persisted_record(rec: dict | None = None) -> dict | None:
    if not isinstance(rec, dict):
        return None
    job_id = str(rec.get('job_id') or '').strip()
    if not job_id:
        return None
    owner = _chat_async_owner_public_snapshot(rec.get('owner') if isinstance(rec.get('owner'), dict) else None)
    status = str(rec.get('status') or 'queued').strip().lower() or 'queued'
    status_text = str(rec.get('status_text') or '').strip()
    error_text = str(rec.get('error') or '').strip()
    events = [dict(x) for x in (rec.get('events') or []) if isinstance(x, dict)]
    artifacts = [dict(x) for x in (rec.get('artifacts') or []) if isinstance(x, dict)]
    meta = dict(rec.get('meta') or {}) if isinstance(rec.get('meta'), dict) else {}
    restored = {
        'job_id': job_id,
        'created_at': float(rec.get('created_at') or time.time()),
        'updated_at': float(rec.get('updated_at') or time.time()),
        'done': bool(rec.get('done')),
        'status': status,
        'status_text': status_text,
        'error': error_text,
        'full_text': str(rec.get('full_text') or ''),
        'events': events[-_CHAT_ASYNC_JOB_EVENTS_LIMIT:],
        'artifacts': artifacts,
        'meta': meta,
        'owner_email': owner.get('email') or '',
        'owner_device_id': owner.get('device_id') or '',
        'owner_is_local_admin_request': bool(owner.get('is_local_admin_request')),
        'owner_allow_private_search_targets': bool(owner.get('allow_private_search_targets')),
        'scope': _normalize_upload_scope(rec.get('scope') or ''),
        'payload': None,
        'stop_requested': bool(rec.get('stop_requested')),
        'recovered_from_disk': True,
        'owner_key': str(rec.get('owner_key') or '').strip(),
        'conversation_id': str(rec.get('conversation_id') or '').strip(),
        'turn_id': str(rec.get('turn_id') or '').strip(),
        'conversation_mode': str(rec.get('conversation_mode') or '').strip(),
        'active_key': '',
    }
    if restored['done']:
        if restored['status'] not in {'done', 'error', 'stopped'}:
            restored['status'] = 'done' if not error_text else 'error'
    elif restored['status'] in {'queued', 'running'}:
        restored['status'] = 'error'
        restored['done'] = True
        restored['status_text'] = restored['status_text'] or '服务重启，任务已中断'
        if not restored['error']:
            restored['error'] = 'service_restarted_during_processing'
        restored['events'].append({
            'seq': max([int((x or {}).get('seq') or 0) for x in restored['events']] + [0]) + 1,
            'event': 'error',
            'payload': {'error': restored['error'], 'recovered': True},
            'ts': time.time(),
        })
    return restored


def _chat_async_row_from_db_row(row) -> dict | None:
    if row is None:
        return None
    try:
        owner = _chat_async_json_loads(row['owner_json'], {})
        events = _chat_async_json_loads(row['events_json'], [])
        artifacts = _chat_async_json_loads(row['artifacts_json'], [])
        meta = _chat_async_json_loads(row['meta_json'], {})
        payload = _chat_async_json_loads(row['payload_json'], None)
    except Exception:
        return None
    rec = {
        'job_id': str(row['job_id'] or '').strip(),
        'created_at': float(row['created_at'] or 0.0),
        'updated_at': float(row['updated_at'] or 0.0),
        'done': bool(int(row['done'] or 0)),
        'status': str(row['status'] or '').strip(),
        'status_text': str(row['status_text'] or '').strip(),
        'error': str(row['error'] or '').strip(),
        'full_text': str(row['full_text'] or ''),
        'events': [dict(x) for x in (events or []) if isinstance(x, dict)],
        'artifacts': [dict(x) for x in (artifacts or []) if isinstance(x, dict)],
        'meta': dict(meta or {}) if isinstance(meta, dict) else {},
        'owner_email': _normalize_login_email((owner or {}).get('email') or ''),
        'owner_device_id': str((owner or {}).get('device_id') or '').strip(),
        'owner_is_local_admin_request': bool((owner or {}).get('is_local_admin_request')),
        'owner_allow_private_search_targets': bool((owner or {}).get('allow_private_search_targets')),
        'scope': _normalize_upload_scope(row['scope'] or ''),
        'payload': payload if isinstance(payload, dict) else None,
        'stop_requested': bool(int(row['stop_requested'] or 0)),
        'recovered_from_disk': bool(int(row['recovered_from_disk'] or 0)),
        'file_progress': {},
        'owner_key': str(row['owner_key'] or '').strip(),
        'conversation_id': str(row['conversation_id'] or '').strip(),
        'turn_id': str(row['turn_id'] or '').strip(),
        'conversation_mode': str(row['conversation_mode'] or '').strip(),
        'active_key': str(row['active_key'] or '').strip(),
    }
    try:
        rec['seq'] = max([int((x or {}).get('seq') or 0) for x in rec['events']] + [0])
    except Exception:
        rec['seq'] = 0
    return _chat_async_apply_persisted_record(_chat_async_record_for_persist(rec) or rec)


def _chat_async_db_upsert_rows(rows: list[dict] | None = None) -> None:
    rows = [dict(x) for x in (rows or []) if isinstance(x, dict) and str((x or {}).get('job_id') or '').strip()]
    if not rows:
        return
    _chat_async_db_ensure()
    conn = _chat_async_db_connect()
    try:
        conn.executemany("""
            INSERT INTO chat_async_jobs (
                job_id, created_at, updated_at, done, status, status_text, error, full_text,
                payload_json, events_json, artifacts_json, meta_json, owner_json, scope,
                stop_requested, recovered_from_disk, owner_key, conversation_id, turn_id,
                conversation_mode, active_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                done=excluded.done,
                status=excluded.status,
                status_text=excluded.status_text,
                error=excluded.error,
                full_text=excluded.full_text,
                payload_json=excluded.payload_json,
                events_json=excluded.events_json,
                artifacts_json=excluded.artifacts_json,
                meta_json=excluded.meta_json,
                owner_json=excluded.owner_json,
                scope=excluded.scope,
                stop_requested=excluded.stop_requested,
                recovered_from_disk=excluded.recovered_from_disk,
                owner_key=excluded.owner_key,
                conversation_id=excluded.conversation_id,
                turn_id=excluded.turn_id,
                conversation_mode=excluded.conversation_mode,
                active_key=excluded.active_key
        """, [
            (
                str(row.get('job_id') or '').strip(),
                float(row.get('created_at') or 0.0),
                float(row.get('updated_at') or 0.0),
                1 if bool(row.get('done')) else 0,
                str(row.get('status') or '').strip(),
                str(row.get('status_text') or '').strip(),
                str(row.get('error') or '').strip(),
                str(row.get('full_text') or ''),
                _chat_async_json_dumps(None),
                _chat_async_json_dumps(row.get('events') or []),
                _chat_async_json_dumps(row.get('artifacts') or []),
                _chat_async_json_dumps(row.get('meta') or {}),
                _chat_async_json_dumps(row.get('owner') or {}),
                _normalize_upload_scope(row.get('scope') or ''),
                1 if bool(row.get('stop_requested')) else 0,
                1 if bool(row.get('recovered_from_disk')) else 0,
                str(row.get('owner_key') or '').strip(),
                str(row.get('conversation_id') or '').strip(),
                str(row.get('turn_id') or '').strip(),
                str(row.get('conversation_mode') or '').strip(),
                str(row.get('active_key') or '').strip() if not bool(row.get('done')) else '',
            )
            for row in rows
        ])
        conn.commit()
    finally:
        conn.close()


def _chat_async_load_persisted_jobs() -> None:
    _chat_async_db_ensure()
    now_ts = time.time()
    expire_before = now_ts - float(_CHAT_ASYNC_JOB_TTL_S or (6 * 3600))
    restored_count = 0
    conn = _chat_async_db_connect()
    try:
        try:
            conn.row_factory = _chat_async_sqlite_module().Row
        except Exception:
            pass
        db_rows = list(conn.execute(
            "SELECT * FROM chat_async_jobs WHERE updated_at >= ? ORDER BY updated_at DESC LIMIT 400",
            (expire_before,)
        ).fetchall())
    finally:
        conn.close()
    with _CHAT_ASYNC_JOB_LOCK:
        for row in db_rows:
            restored = _chat_async_row_from_db_row(row)
            if not restored:
                continue
            job_id = str(restored.get('job_id') or '').strip()
            if not job_id or job_id in _CHAT_ASYNC_JOBS:
                continue
            _CHAT_ASYNC_JOBS[job_id] = restored
            _CHAT_ASYNC_JOB_RUNTIME[job_id] = {'thread': None, 'stream_handle': None}
            restored_count += 1
    if restored_count == 0:
        try:
            if os.path.exists(CHAT_ASYNC_STATE_FILE):
                with open(CHAT_ASYNC_STATE_FILE, 'r', encoding='utf-8') as f:
                    payload = json.load(f) or {}
                rows = payload.get('jobs') or []
                imported = []
                for item in (rows if isinstance(rows, list) else []):
                    persisted = _chat_async_record_for_persist(_chat_async_apply_persisted_record(item) or item)
                    if persisted:
                        imported.append(persisted)
                if imported:
                    _chat_async_db_upsert_rows(imported)
                    try:
                        backup = CHAT_ASYNC_STATE_FILE + '.imported'
                        if os.path.exists(backup):
                            os.remove(backup)
                        os.replace(CHAT_ASYNC_STATE_FILE, backup)
                    except Exception:
                        pass
                    _chat_async_load_persisted_jobs()
                    return
        except Exception:
            app_logger.exception('[chat_async] import_legacy_json_failed')
    if restored_count:
        app_logger.info('[chat_async] restored_jobs_from_disk=%s', restored_count)


def _chat_async_save_persisted_jobs(force: bool = False) -> None:
    now_ts = time.time()
    debounce_s = 0.0 if force else float(_CHAT_ASYNC_PERSIST_DEBOUNCE_S or 0.0)
    with _CHAT_ASYNC_PERSIST_LOCK:
        last_at = float(getattr(_chat_async_save_persisted_jobs, '_last_at', 0.0) or 0.0)
        dirty = bool(getattr(_chat_async_save_persisted_jobs, '_dirty', False))
        if not force and last_at > 0 and (now_ts - last_at) < debounce_s:
            setattr(_chat_async_save_persisted_jobs, '_dirty', True)
            return
        setattr(_chat_async_save_persisted_jobs, '_dirty', False)
    expire_before = now_ts - float(_CHAT_ASYNC_JOB_TTL_S or (6 * 3600))
    rows = []
    with _CHAT_ASYNC_JOB_LOCK:
        for rec in _CHAT_ASYNC_JOBS.values():
            persisted = _chat_async_record_for_persist(rec)
            if not persisted:
                continue
            updated_at = float(persisted.get('updated_at') or 0.0)
            if updated_at and updated_at < expire_before:
                continue
            rows.append(persisted)
    try:
        rows.sort(key=lambda x: float(x.get('updated_at') or 0.0), reverse=True)
        _chat_async_db_upsert_rows(rows[:max(20, min(400, len(rows) or 20))])
        _chat_async_db_ensure()
        conn = _chat_async_db_connect()
        try:
            conn.execute(
                "DELETE FROM chat_async_jobs WHERE updated_at > 0 AND updated_at < ?",
                (expire_before,)
            )
            conn.commit()
        finally:
            conn.close()
        with _CHAT_ASYNC_PERSIST_LOCK:
            setattr(_chat_async_save_persisted_jobs, '_last_at', now_ts)
            dirty_after = bool(getattr(_chat_async_save_persisted_jobs, '_dirty', False))
            setattr(_chat_async_save_persisted_jobs, '_dirty', False)
        if dirty_after and not force:
            _chat_async_save_persisted_jobs(force=True)
    except Exception:
        app_logger.exception('[chat_async] save_persisted_jobs_failed')


def _chat_async_cleanup_expired(now_ts: float | None = None) -> None:
    now_ts = float(now_ts if now_ts is not None else time.time())
    remove_ids: list[str] = []
    with _CHAT_ASYNC_JOB_LOCK:
        for job_id, rec in list(_CHAT_ASYNC_JOBS.items()):
            updated_at = float((rec or {}).get('updated_at') or (rec or {}).get('created_at') or 0.0)
            if updated_at and (now_ts - updated_at) > _CHAT_ASYNC_JOB_TTL_S:
                remove_ids.append(job_id)
        for job_id in remove_ids:
            _CHAT_ASYNC_JOBS.pop(job_id, None)
            _CHAT_ASYNC_JOB_RUNTIME.pop(job_id, None)
            _CHAT_ASYNC_JOB_CONDS.pop(job_id, None)
    if remove_ids:
        _chat_async_save_persisted_jobs(force=True)


def _chat_async_job_cond(job_id: str) -> threading.Condition:
    with _CHAT_ASYNC_JOB_LOCK:
        cond = _CHAT_ASYNC_JOB_CONDS.get(job_id)
        if cond is None:
            cond = threading.Condition()
            _CHAT_ASYNC_JOB_CONDS[job_id] = cond
        return cond


def _chat_async_notify(job_id: str) -> None:
    cond = _chat_async_job_cond(job_id)
    try:
        with cond:
            cond.notify_all()
    except Exception:
        pass


def _chat_async_owner_snapshot() -> dict:
    email = ''
    try:
        email = _normalize_login_email((_current_login_account() or {}).get('email') or '')
    except Exception:
        email = ''
    if not email:
        try:
            email = _normalize_login_email(_current_login_email())
        except Exception:
            email = ''
    device_id = _auth_current_session_key()
    try:
        is_local_admin_request = bool(_is_local_admin_request())
    except Exception:
        is_local_admin_request = False
    try:
        allow_private_search_targets = bool(_current_request_allows_private_search_targets())
    except Exception:
        allow_private_search_targets = False
    return {
        'email': email,
        'device_id': device_id,
        'is_local_admin_request': is_local_admin_request,
        'is_public_request': bool(_is_public_request_scope()),
        'allow_private_search_targets': allow_private_search_targets,
    }


def _chat_async_can_access(rec: dict | None, owner: dict | None) -> bool:
    rec = rec or {}
    owner = owner or {}
    rec_email = _normalize_login_email(rec.get('owner_email') or '')
    owner_email = _normalize_login_email(owner.get('email') or '')
    if rec_email and owner_email and rec_email == owner_email:
        return True
    rec_device = str(rec.get('owner_device_id') or '').strip()
    owner_device = str(owner.get('device_id') or '').strip()
    if rec_device and owner_device and rec_device == owner_device:
        return True
    if not rec_email and not rec_device:
        return True
    return False


def _chat_async_is_public_job(rec: dict | None = None) -> bool:
    try:
        return bool((rec or {}).get('owner_is_public_request'))
    except Exception:
        return False


def _chat_async_delta_chunk_limits(*, is_public: bool = False) -> tuple[int, int, int, set[str]]:
    if is_public:
        min_chars = max(1, int(_CHAT_ASYNC_DELTA_PUBLIC_MIN_CHARS or 2))
        soft_chars = max(min_chars, int(_CHAT_ASYNC_DELTA_PUBLIC_SOFT_CHARS or 6))
        hard_chars = max(soft_chars, int(_CHAT_ASYNC_DELTA_PUBLIC_HARD_CHARS or 10))
    else:
        min_chars = max(1, int(_CHAT_ASYNC_DELTA_MIN_CHARS or 4))
        soft_chars = max(min_chars, int(_CHAT_ASYNC_DELTA_SOFT_CHARS or 16))
        hard_chars = max(soft_chars, int(_CHAT_ASYNC_DELTA_HARD_CHARS or 28))
    break_chars = _CHAT_ASYNC_DELTA_SOFT_BREAKS if isinstance(_CHAT_ASYNC_DELTA_SOFT_BREAKS, set) else set("。！？!?；;：:，,、\n\r\t ")
    return min_chars, soft_chars, hard_chars, break_chars


def _chat_async_merge_files(existing: list | None, incoming: list | None) -> list:
    out: list[dict] = []
    seen = set()

    def _push(item):
        if not isinstance(item, dict):
            return
        key = f"{str(item.get('download_url') or '').strip()}|{str(item.get('filename') or '').strip()}"
        if key in seen:
            return
        seen.add(key)
        out.append(item)

    for item in list(existing or []):
        _push(item)
    for item in list(incoming or []):
        _push(item)
    return out


class ChatAsyncRunCoordinator:
    """账号级生成任务协调器。

    Chat 和 Responses 只在这里共享会话/回合唯一性；模型请求协议仍由各自链路处理。
    """

    ACTIVE_STATUSES = {'claimed', 'queued', 'running', 'stopping'}

    def __init__(self, jobs: dict, lock: threading.RLock):
        self.jobs = jobs
        self.lock = lock

    @staticmethod
    def owner_key(owner: dict | None = None) -> str:
        row = dict(owner or {})
        email = _normalize_login_email(row.get('email') or '')
        if email:
            return 'email:' + email
        device_id = str(row.get('device_id') or '').strip()
        if device_id:
            return 'device:' + device_id
        if bool(row.get('is_local_admin_request')):
            return 'local-admin'
        return ''

    @staticmethod
    def coordination(payload: dict | None = None, owner: dict | None = None) -> dict:
        body = dict(payload or {})
        temporary = bool(body.get('temporary_chat') or body.get('temporaryChat'))
        conversation_id = '' if temporary else str(
            body.get('client_session_id')
            or body.get('conversation_id')
            or body.get('session_id')
            or body.get('active_session_id')
            or ''
        ).strip()[:180]
        turn_id = '' if temporary else str(
            body.get('client_turn_id')
            or body.get('client_turn_key')
            or body.get('turn_id')
            or body.get('idempotency_key')
            or ''
        ).strip()[:240]
        endpoint_mode = str(body.get('api_endpoint_mode') or body.get('endpoint_mode') or '').strip().lower()
        conversation_mode = 'response' if endpoint_mode in {'responses', 'response'} else 'chat'
        owner_key = ChatAsyncRunCoordinator.owner_key(owner)
        return {
            'owner_key': owner_key,
            'conversation_id': conversation_id,
            'turn_id': turn_id,
            'conversation_mode': conversation_mode,
            'active_key': f'{owner_key}|{conversation_id}' if owner_key and conversation_id else '',
        }

    @classmethod
    def is_active(cls, rec: dict | None = None) -> bool:
        row = rec or {}
        if bool(row.get('done')):
            return False
        status = str(row.get('status') or 'queued').strip().lower() or 'queued'
        return status in cls.ACTIVE_STATUSES or not bool(row.get('done'))

    @staticmethod
    def public_run(rec: dict | None = None, *, reused: bool = False) -> dict:
        row = dict(rec or {})
        return {
            'job_id': str(row.get('job_id') or '').strip(),
            'conversation_id': str(row.get('conversation_id') or '').strip(),
            'turn_id': str(row.get('turn_id') or '').strip(),
            'conversation_mode': str(row.get('conversation_mode') or '').strip() or 'chat',
            'status': str(row.get('status') or 'queued').strip() or 'queued',
            'status_text': str(row.get('status_text') or '').strip(),
            'done': bool(row.get('done')),
            'current_seq': max(0, int(row.get('seq') or 0)),
            'created_ts': float(row.get('created_at') or 0.0),
            'updated_ts': float(row.get('updated_at') or 0.0),
            'recovered_from_disk': bool(row.get('recovered_from_disk')),
            'reused': bool(reused),
        }

    def _matching_runs_locked(self, owner_key: str, conversation_id: str) -> list[dict]:
        rows = [
            rec for rec in self.jobs.values()
            if isinstance(rec, dict)
            and str(rec.get('owner_key') or self.owner_key({
                'email': rec.get('owner_email'),
                'device_id': rec.get('owner_device_id'),
                'is_local_admin_request': rec.get('owner_is_local_admin_request'),
            })).strip() == owner_key
            and str(rec.get('conversation_id') or '').strip() == conversation_id
        ]
        rows.sort(key=lambda rec: (float(rec.get('updated_at') or 0.0), float(rec.get('created_at') or 0.0)), reverse=True)
        return rows

    def find(self, owner: dict | None, conversation_id: str, *, turn_id: str = '', active_only: bool = False) -> dict | None:
        owner_key = self.owner_key(owner)
        conversation_key = str(conversation_id or '').strip()[:180]
        turn_key = str(turn_id or '').strip()[:240]
        if not owner_key or not conversation_key:
            return None
        now_ts = time.time()
        with self.lock:
            rows = self._matching_runs_locked(owner_key, conversation_key)
            if turn_key:
                exact = [rec for rec in rows if str(rec.get('turn_id') or '').strip() == turn_key]
                if exact:
                    selected = exact[0]
                    if not active_only or self.is_active(selected):
                        return selected
            active = [rec for rec in rows if self.is_active(rec)]
            if active:
                return active[0]
            if active_only:
                return None
            for rec in rows:
                updated_at = float(rec.get('updated_at') or rec.get('created_at') or 0.0)
                if updated_at > 0 and (now_ts - updated_at) <= _CHAT_ASYNC_COMPLETED_DISCOVERY_TTL_S:
                    return rec
        return None

    def start_or_reuse(self, payload: dict, owner: dict | None = None) -> tuple[dict, str]:
        coord = self.coordination(payload, owner)
        owner_key = str(coord.get('owner_key') or '')
        conversation_id = str(coord.get('conversation_id') or '')
        turn_id = str(coord.get('turn_id') or '')
        if owner_key and conversation_id:
            with self.lock:
                rows = self._matching_runs_locked(owner_key, conversation_id)
                if turn_id:
                    for rec in rows:
                        if str(rec.get('turn_id') or '').strip() == turn_id:
                            return rec, 'reused'
                for rec in rows:
                    if self.is_active(rec):
                        return rec, 'conversation_busy'
                rec = _chat_async_new_job_record(payload, owner=owner, coordination=coord)
                self.jobs[str(rec.get('job_id') or '')] = rec
                _CHAT_ASYNC_JOB_RUNTIME[str(rec.get('job_id') or '')] = {'thread': None, 'stream_handle': None}
                return rec, 'created'
        rec = _chat_async_create_job(payload, owner=owner)
        return rec, 'created'


_CHAT_ASYNC_RUN_COORDINATOR = ChatAsyncRunCoordinator(_CHAT_ASYNC_JOBS, _CHAT_ASYNC_JOB_LOCK)


def _chat_async_new_job_record(payload: dict, owner: dict | None = None, coordination: dict | None = None) -> dict:
    owner = owner or {}
    coord = dict(coordination or _CHAT_ASYNC_RUN_COORDINATOR.coordination(payload, owner))
    job_id = uuid.uuid4().hex
    now_ts = time.time()
    return {
        'job_id': job_id,
        'created_at': now_ts,
        'updated_at': now_ts,
        'status': 'queued',
        'done': False,
        'stop_requested': False,
        'status_text': '等待响应中…',
        'full_text': '',
        'events': [],
        'seq': 0,
        'artifacts': [],
        'meta': {},
        'file_progress': {},
        'error': '',
        'owner_email': _normalize_login_email(owner.get('email') or ''),
        'owner_device_id': str(owner.get('device_id') or '').strip(),
        'owner_is_local_admin_request': bool(owner.get('is_local_admin_request')),
        'owner_is_public_request': bool(owner.get('is_public_request')),
        'owner_allow_private_search_targets': bool(owner.get('allow_private_search_targets')),
        'owner_key': str(coord.get('owner_key') or '').strip(),
        'conversation_id': str(coord.get('conversation_id') or '').strip(),
        'turn_id': str(coord.get('turn_id') or '').strip(),
        'conversation_mode': str(coord.get('conversation_mode') or 'chat').strip() or 'chat',
        'active_key': str(coord.get('active_key') or '').strip(),
        'payload': payload or {},
    }


def _chat_async_create_job(payload: dict, owner: dict | None = None) -> dict:
    _chat_async_cleanup_expired()
    rec = _chat_async_new_job_record(payload, owner=owner)
    job_id = str(rec.get('job_id') or '').strip()
    with _CHAT_ASYNC_JOB_LOCK:
        _CHAT_ASYNC_JOBS[job_id] = rec
        _CHAT_ASYNC_JOB_RUNTIME[job_id] = {'thread': None, 'stream_handle': None}
    _chat_async_save_persisted_jobs(force=True)
    return rec


def _chat_async_get_job(job_id: str) -> dict | None:
    job_key = str(job_id or '').strip()
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(job_key)
        if rec is None:
            _chat_async_load_persisted_jobs()
            rec = _CHAT_ASYNC_JOBS.get(job_key)
            if rec is None:
                return None
        return rec


def _chat_async_bind_thread_job(job_id: str) -> None:
    _CHAT_ASYNC_JOB_THREAD_LOCAL.job_id = str(job_id or '').strip()


def _chat_async_unbind_thread_job() -> None:
    try:
        if hasattr(_CHAT_ASYNC_JOB_THREAD_LOCAL, 'job_id'):
            delattr(_CHAT_ASYNC_JOB_THREAD_LOCAL, 'job_id')
    except Exception:
        pass


def _chat_async_current_job_id() -> str:
    return str(getattr(_CHAT_ASYNC_JOB_THREAD_LOCAL, 'job_id', '') or '').strip()


def _chat_async_should_stop_current_job() -> bool:
    job_id = _chat_async_current_job_id()
    if not job_id:
        return False
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(job_id) or {}
        return bool(rec.get('stop_requested'))


def _chat_async_set_current_stream_handle(stream_handle) -> None:
    job_id = _chat_async_current_job_id()
    if not job_id:
        return
    with _CHAT_ASYNC_JOB_LOCK:
        runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_id, {})
        runtime['stream_handle'] = stream_handle


def _chat_async_split_delta_text_for_poll(text: str, *, force: bool = False, is_public: bool = False) -> list[str]:
    raw = str(text or '')
    if not raw:
        return []

    min_chars, soft_chars, hard_chars, break_chars = _chat_async_delta_chunk_limits(is_public=is_public)

    out: list[str] = []
    pending = raw
    while pending:
        if len(pending) <= soft_chars and (force or len(pending) < hard_chars):
            out.append(pending)
            break

        search_limit = min(len(pending), hard_chars)
        target_limit = min(search_limit, soft_chars)
        cut = -1

        for idx in range(target_limit, min_chars - 1, -1):
            if pending[idx - 1] in break_chars:
                cut = idx
                break
        if cut < 0 and search_limit > target_limit:
            for idx in range(search_limit, target_limit, -1):
                if pending[idx - 1] in break_chars:
                    cut = idx
                    break
        if cut < 0:
            cut = search_limit

        piece = pending[:cut]
        pending = pending[cut:]
        if piece:
            out.append(piece)
        elif pending:
            out.append(pending)
            break
    return [piece for piece in out if piece]


def _chat_async_append_delta_micro_chunks(job_id: str, text: str, *, force: bool = False, is_public: bool = False) -> int:
    seq = 0
    for piece in _chat_async_split_delta_text_for_poll(text, force=force, is_public=is_public):
        if piece:
            seq = _chat_async_append_event(job_id, 'delta', {'text': piece})
    return seq


def _chat_async_append_event(job_id: str, event: str, payload: dict | None = None) -> int:
    payload_dict = dict(payload or {})
    if str(event or '') in {'location_permission_request', 'mcp_approval_request', 'mcp_approval_result', 'mcp_tool_audit'}:
        payload_dict.setdefault('job_id', str(job_id or '').strip())
        payload_dict.setdefault('_job_id', str(job_id or '').strip())
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(str(job_id or '').strip())
        if rec is None:
            return 0
        rec['seq'] = int(rec.get('seq') or 0) + 1
        seq = int(rec['seq'])
        payload_dict['_job_seq'] = seq
        rec['events'].append({
            'seq': seq,
            'event': str(event or 'message'),
            'payload': payload_dict,
            'ts': time.time(),
        })
        if len(rec['events']) > _CHAT_ASYNC_JOB_EVENTS_LIMIT:
            rec['events'] = rec['events'][-_CHAT_ASYNC_JOB_EVENTS_LIMIT:]
        if event == 'status':
            rec['status_text'] = str(payload_dict.get('text') or '').strip()
            if isinstance(payload_dict.get('file_progress'), dict):
                rec['file_progress'] = dict(payload_dict.get('file_progress') or {})
            lowered = rec['status_text']
            if lowered == '已停止':
                rec['status'] = 'stopped'
                rec['done'] = True
        elif event == 'file_progress':
            rec['file_progress'] = dict(payload_dict or {})
            msg = str(payload_dict.get('message') or payload_dict.get('text') or '').strip()
            if msg:
                rec['status_text'] = msg
            rec['status'] = 'running'
        elif event == 'delta':
            rec['full_text'] = str(rec.get('full_text') or '') + str(payload_dict.get('text') or '')
            rec['status'] = 'running'
        elif event == 'files':
            rec['artifacts'] = _chat_async_merge_files(rec.get('artifacts') or [], payload_dict.get('files') or [])
        elif event == 'meta':
            rec['meta'] = dict(payload_dict or {})
            rec['artifacts'] = _chat_async_merge_files(rec.get('artifacts') or [], payload_dict.get('artifacts') or [])
        elif event == 'error':
            rec['error'] = str(payload_dict.get('error') or '').strip()
            if rec['error'] == '__async_chat_job_stopped__':
                rec['status'] = 'stopped'
                rec['done'] = True
            else:
                rec['status'] = 'error'
        elif event == 'done':
            if rec.get('status') not in {'error', 'stopped'}:
                rec['status'] = 'done'
            rec['done'] = True
        rec['updated_at'] = time.time()
    _chat_async_notify(job_id)
    # 终态必须立即落盘：否则最后一个 done 恰好落在 debounce 窗口内时，数据库会长期保留
    # running/active_key，刷新后的设备会误判为仍在生成。
    _chat_async_save_persisted_jobs(force=bool(event == 'done' or rec.get('done')))
    return seq




def _chat_async_start_keepalive(job_id: str, label: str = '') -> tuple[threading.Event, threading.Thread]:
    job_key = str(job_id or '').strip()
    stop_event = threading.Event()
    base_text = (f"{str(label or '').strip()} 正在处理中…").strip() or '正在处理中…'
    heartbeat_interval = max(2.0, float(_CHAT_ASYNC_HEARTBEAT_INTERVAL_S or 4.0))
    idle_s = max(2.5, float(_CHAT_ASYNC_HEARTBEAT_IDLE_S or (heartbeat_interval + 0.5)))

    def _runner() -> None:
        while not stop_event.wait(heartbeat_interval):
            with _CHAT_ASYNC_JOB_LOCK:
                rec = _CHAT_ASYNC_JOBS.get(job_key)
                if rec is None or bool(rec.get('done')):
                    return
                status = str(rec.get('status') or '').strip().lower()
                status_text = str(rec.get('status_text') or '').strip()
                events = list(rec.get('events') or [])
                last_ts = float((events[-1] if events else {}).get('ts') or rec.get('updated_at') or rec.get('created_at') or 0.0)
            if status in {'done', 'error', 'stopped'}:
                return
            if last_ts and (time.time() - last_ts) < idle_s:
                continue
            heartbeat_text = status_text or base_text
            if heartbeat_text in {'完成', '已停止'}:
                continue
            _chat_async_append_event(job_key, 'status', {'text': heartbeat_text, 'heartbeat': True})

    thread = threading.Thread(target=_runner, name=f'chat_async_keepalive_{job_key[:8]}', daemon=True)
    thread.start()
    return stop_event, thread


def _chat_async_payload_wants_json_object(payload: dict | None = None) -> bool:
    payload = payload or {}
    api_settings = payload.get('api_settings') if isinstance(payload.get('api_settings'), dict) else {}
    candidates = [
        payload.get('generation_response_format'),
        payload.get('response_format'),
        api_settings.get('generation_response_format'),
        api_settings.get('response_format'),
    ]
    for value in candidates:
        raw = str(value or '').strip().lower().replace('-', '_')
        if raw in {'json', 'json_object', 'object'}:
            return True
    return False


def _chat_async_extract_json_object_text(raw: str = '') -> str:
    text = str(raw or '').strip()
    if not text:
        return ''

    def _parse_candidate(candidate: str = '') -> str:
        candidate = str(candidate or '').strip()
        if not candidate:
            return ''
        try:
            obj = json.loads(candidate)
        except Exception:
            return ''
        if isinstance(obj, dict):
            return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
        return ''

    parsed = _parse_candidate(text)
    if parsed:
        return parsed

    for match in re.finditer(r"```(?:json|javascript|js)?\s*([\s\S]*?)```", text, flags=re.I):
        parsed = _parse_candidate(match.group(1))
        if parsed:
            return parsed

    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch != '{':
            continue
        try:
            obj, _end = decoder.raw_decode(text[idx:])
        except Exception:
            continue
        if isinstance(obj, dict):
            return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
    return ''


def _chat_async_parse_sse_frames(frame_text: str) -> list[tuple[str, dict]]:
    text = str(frame_text or '')
    if not text:
        return []
    parts = [part for part in text.split('\n\n') if part.strip()]
    out: list[tuple[str, dict]] = []
    for part in parts:
        lines = str(part).split('\n')
        event = 'message'
        data_lines: list[str] = []
        for line in lines:
            if not line:
                continue
            if line.startswith(':'):
                continue
            if line.startswith('event:'):
                event = line[6:].strip() or 'message'
                continue
            if line.startswith('data:'):
                data_lines.append(line[5:])
        if not data_lines:
            continue
        raw_data = '\n'.join(data_lines).strip()
        if not raw_data:
            continue
        if raw_data == '[DONE]':
            out.append(('done', {}))
            continue
        try:
            payload = json.loads(raw_data)
        except Exception:
            payload = {'text': raw_data}
        if not isinstance(payload, dict):
            payload = {'value': payload}
        out.append((event, payload))
    return out


def _chat_async_request_stop(job_id: str) -> bool:
    job_key = str(job_id or '').strip()
    if not job_key:
        return False
    has_stream_handle = False
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(job_key)
        if rec is None:
            return False
        rec['stop_requested'] = True
        rec['updated_at'] = time.time()
        runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_key, {})
        runtime['stop_requested_at'] = rec['updated_at']
        has_stream_handle = runtime.get('stream_handle') is not None
    try:
        app_logger.info('[chat_async] stop_requested job=%s has_stream=%s', job_key[:12], bool(has_stream_handle))
    except Exception:
        pass
    _chat_async_notify(job_key)
    _chat_async_save_persisted_jobs(force=True)
    return True


def _chat_async_worker(job_id: str) -> None:
    job_key = str(job_id or '').strip()
    rec = _chat_async_get_job(job_key) or {}
    payload = dict(rec.get('payload') or {})
    heartbeat_stop = None
    heartbeat_thread = None
    worker_slot_acquired = False
    try:
        worker_slot_acquired = _chat_async_worker_slot_acquire(job_key)
    except RuntimeError as e:
        if str(e or '') == '__async_chat_job_stopped__':
            try:
                _chat_async_append_event(job_key, 'status', {'text': '已停止'})
                _chat_async_append_event(job_key, 'done', {})
            except Exception:
                pass
            return
        raise
    _chat_async_bind_thread_job(job_key)
    with _CHAT_ASYNC_JOB_LOCK:
        if job_key in _CHAT_ASYNC_JOBS:
            _CHAT_ASYNC_JOBS[job_key]['status'] = 'running'
            _CHAT_ASYNC_JOBS[job_key]['updated_at'] = time.time()
            runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_key, {})
            runtime['worker_slot'] = _chat_async_worker_slot_snapshot()
    try:
        ctx_builder = globals().get('_chat_request_context_from_payload')
        req_ctx = ctx_builder(payload, source='chat_async_start') if callable(ctx_builder) else {}
        user_text = str((req_ctx or {}).get('user_text') or _latest_user_text_from_payload(payload))
        model = str((req_ctx or {}).get('model') or payload.get("model") or app_getenv("GPT_MODEL", "gpt-5.4-nano") or '').strip()
        show_steps = bool((req_ctx or {}).get('show_steps', payload.get("show_steps", True)))
        history = list((req_ctx or {}).get('history') or payload.get("history") or [])
        label = str((req_ctx or {}).get('label') or payload.get("label") or "")
        heartbeat_stop, heartbeat_thread = _chat_async_start_keepalive(job_key, label=str(label or '').strip())
        user_geo = payload.get("user_geo") or None
        location_state = payload.get("location_state") if isinstance(payload.get("location_state"), dict) else {}
        if isinstance(location_state, dict) and location_state:
            if isinstance(user_geo, dict):
                try:
                    user_geo = dict(user_geo)
                    user_geo['_location_state'] = dict(location_state)
                except Exception:
                    pass
            else:
                user_geo = {'_location_state': dict(location_state)}
        user_time = _normalize_runtime_time_payload(payload.get("user_time"))
        debug_geo_meta = payload.get("debug_geo_meta") if isinstance(payload.get("debug_geo_meta"), dict) else {}
        if isinstance(debug_geo_meta, dict) and isinstance(location_state, dict) and location_state and 'location_state' not in debug_geo_meta:
            try:
                debug_geo_meta = dict(debug_geo_meta)
                debug_geo_meta['location_state'] = dict(location_state)
            except Exception:
                pass
        disable_tools = bool(payload.get("disable_tools", False))
        skip_prepare_messages = bool(payload.get("skip_prepare_messages", False))
        disable_visual_prefetch = bool(payload.get("disable_visual_prefetch", False))
        api_endpoint_mode = str((req_ctx or {}).get('api_endpoint_mode') or _api_endpoint_mode_from_payload(payload))
        temporary_chat = bool((req_ctx or {}).get('temporary_chat', bool(payload.get("temporary_chat") or payload.get("temporaryChat"))))

        try:
            if debug_geo_meta and (bool(debug_geo_meta.get('is_weather_query')) or bool(debug_geo_meta.get('is_location_query')) or not isinstance(user_geo, dict)):
                browser_geo = debug_geo_meta.get('browser_geo') if isinstance(debug_geo_meta.get('browser_geo'), dict) else None
                brief_meta = {
                    'is_weather_query': bool(debug_geo_meta.get('is_weather_query')),
                    'is_location_query': bool(debug_geo_meta.get('is_location_query')),
                    'is_weather_followup': bool(debug_geo_meta.get('is_weather_followup')),
                    'need_fresh_geo': bool(debug_geo_meta.get('need_fresh_geo')),
                    'geo_source': str(debug_geo_meta.get('geo_source') or '')[:40],
                    'browser_geo': browser_geo,
                }
                app_logger.warning('[DEBUG_CHAT_ASYNC_GEO] user_geo=%s meta=%s', _geo_debug_brief(user_geo), brief_meta)
        except Exception:
            pass

        if show_steps:
            _chat_async_append_event(job_key, 'status', {'text': f'{label} 已连接，准备中…'})

        kb_direct_reply = _kb_try_direct_existing_file_reply(
            query=user_text,
            kb_enabled=payload.get("kb_enabled", True),
            kb_space_id=str(payload.get("kb_space_id") or ''),
            kb_doc_id=str(payload.get("kb_doc_id") or ''),
        )
        if kb_direct_reply:
            if show_steps:
                _chat_async_append_event(job_key, 'status', {'text': f'{label} 已锁定知识库文档，正在直接回答…'})
            _chat_async_append_event(job_key, 'delta', {'text': str(kb_direct_reply.get('reply') or '')})
            _chat_async_append_event(job_key, 'meta', {'model': model, 'mode': str(kb_direct_reply.get('mode') or 'kb_direct_existing_file'), 'kb_result_count': int(kb_direct_reply.get('result_count') or 0)})
            _chat_async_append_event(job_key, 'done', {})
            return

        if show_steps:
            _chat_async_append_event(job_key, 'status', {'text': f'{label} 正在整理对话与联网信息…'})

        messages = list((req_ctx or {}).get('messages') or [])
        if not messages:
            message_builder = globals().get('_chat_request_messages_from_payload')
            if callable(message_builder):
                messages = message_builder(payload, user_text=user_text, history=history)
        _chat_async_log_prompt_cache_request_messages('payload_normalized', messages, payload)
        messages = _merge_payload_file_attachments_into_messages(messages, payload, source='chat_async_start')
        messages = _inject_runtime_time_context(messages, user_time=user_time)
        try:
            loc_ctx_fn = globals().get('_inject_runtime_location_visibility_context')
            if callable(loc_ctx_fn):
                messages = loc_ctx_fn(messages, user_geo=user_geo, user_time=user_time, debug_geo_meta=debug_geo_meta, location_state=location_state)
        except Exception:
            pass
        _chat_async_log_prompt_cache_request_messages('runtime_context_ready', messages, payload)
        prepare_skip_fn = globals().get('_prepare_skip_decision_for_endpoint')
        if callable(prepare_skip_fn):
            prepare_skip = prepare_skip_fn(api_endpoint_mode, disable_tools=disable_tools, skip_prepare_messages=skip_prepare_messages)
            direct_agent_skip_prepare = bool((prepare_skip or {}).get('direct_agent_skip_prepare'))
            effective_skip_prepare_messages = bool((prepare_skip or {}).get('effective_skip_prepare_messages'))
        else:
            if str(api_endpoint_mode or '').strip().lower() == 'responses':
                direct_agent_skip_prepare = True
            else:
                try:
                    direct_agent_skip_prepare = bool((not disable_tools) and _agent_stream_should_skip_initial_prepare(True))
                except Exception:
                    direct_agent_skip_prepare = False
            effective_skip_prepare_messages = bool(skip_prepare_messages or direct_agent_skip_prepare)
        if not effective_skip_prepare_messages:
            messages = _prepare_messages(
                messages,
                user_geo=user_geo,
                web_enabled=payload.get("web_enabled"),
                web_k=payload.get("web_k"),
                web_max_pages=payload.get("web_max_pages"),
                kb_enabled=payload.get("kb_enabled", True),
                kb_space_id=str(payload.get("kb_space_id") or ''),
                kb_doc_id=str(payload.get("kb_doc_id") or ''),
            )
        if temporary_chat:
            backend_personalization_meta = {'available': False, 'source': 'temporary_chat_disabled'}
        else:
            messages, backend_personalization_meta = _inject_auth_personalization_memory(messages, email=str(rec.get('owner_email') or '').strip())
        if show_steps and backend_personalization_meta.get('source') == 'backend_injected':
            _chat_async_append_event(job_key, 'status', {'text': f'{label} 已载入账号记忆…'})
        if show_steps:
            _chat_async_append_event(job_key, 'status', {'text': f'{label} 准备完成，开始生成…'})

        client_override = _client_for_payload(payload)
        request_overrides = _extract_request_overrides(payload)
        access_ctx = {
            'email': str(rec.get('owner_email') or '').strip(),
            'device_id': str(rec.get('owner_device_id') or '').strip(),
            'is_local_admin_request': bool(rec.get('owner_is_local_admin_request')),
            'allow_private_search_targets': bool(rec.get('owner_allow_private_search_targets')),
        }
        request_overrides = _enforce_request_override_policy(payload, request_overrides, access_ctx=access_ctx)
        _set_request_overrides(request_overrides)
        app_logger.warning(
            "[DEBUG_REQUEST_OVERRIDES_SET] route=/api3/chat_async/start fallback=%r serper_key_len=%s keys=%s",
            app_getenv("SEARCH_FALLBACK_PROVIDER", "serper"),
            len(app_getenv("SERPER_API_KEY", "").strip()),
            sorted(request_overrides.keys()),
        )

        is_public_job = _chat_async_is_public_job(rec)
        _delta_min_chars, _delta_soft_chars, _delta_hard_chars, _delta_break_chars = _chat_async_delta_chunk_limits(is_public=is_public_job)
        _delta_public_force_flush_s = max(0.03, float(_CHAT_ASYNC_DELTA_PUBLIC_FORCE_FLUSH_MS or 90) / 1000.0) if is_public_job else 0.0
        pending_delta_text = ''
        pending_delta_started_at = 0.0
        json_response_mode = _chat_async_payload_wants_json_object(payload)
        json_delta_buffer = ''

        def _flush_pending_delta(force: bool = False) -> None:
            nonlocal pending_delta_text, pending_delta_started_at
            if not pending_delta_text:
                return
            _chat_async_append_delta_micro_chunks(job_key, pending_delta_text, force=force, is_public=is_public_job)
            pending_delta_text = ''
            pending_delta_started_at = 0.0

        stream_kwargs = {
            'user_geo': user_geo,
            'user_time': user_time,
            'location_state': location_state,
            'client_override': client_override,
            'api_endpoint_mode': api_endpoint_mode,
            'enable_tools': not disable_tools,
            'enable_visual': not disable_visual_prefetch,
            'web_enabled': payload.get("web_enabled"),
            'web_k': payload.get("web_k"),
            'web_max_pages': payload.get("web_max_pages"),
            'image_generation_enabled': bool(payload.get("image_generation_enabled")),
            'image_generation_settings': _normalize_image_generation_settings(payload.get("image_generation_settings")),
            'image_assets': payload.get("image_assets") if isinstance(payload.get("image_assets"), list) else [],
            'kb_enabled': payload.get("kb_enabled", True),
            'kb_space_id': str(payload.get("kb_space_id") or ''),
            'kb_doc_id': str(payload.get("kb_doc_id") or ''),
            'initial_prepare_skipped': bool(direct_agent_skip_prepare),
            'runtime_model': str(payload.get("runtime_model") or '').strip(),
            'temporary_chat': temporary_chat,
            'debug_geo_meta': debug_geo_meta,
            'client_session_id': str(payload.get('client_session_id') or payload.get('session_id') or rec.get('session_id') or '').strip(),
            'client_session_title': str(payload.get('client_session_title') or payload.get('session_title') or rec.get('session_title') or '').strip(),
            'mcp_owner_email': str(rec.get('owner_email') or '').strip().lower(),
        }

        def _chat_stream_gen_compat_call(*args, **kwargs):
            """Call the currently loaded orchestrator stream function without
            assuming every split-file version supports the newest keyword args.
            """
            call_kwargs = dict(kwargs or {})
            try:
                inspect_mod = __import__('inspect')
                sig = inspect_mod.signature(_chat_stream_gen)
                params = getattr(sig, 'parameters', {}) or {}
                accepts_kwargs = any(
                    getattr(param, 'kind', None) == inspect_mod.Parameter.VAR_KEYWORD
                    for param in params.values()
                )
                if not accepts_kwargs:
                    call_kwargs = {k: v for k, v in call_kwargs.items() if k in params}
            except Exception:
                pass

            while True:
                try:
                    stream_iter = _chat_stream_gen(*args, **call_kwargs)
                    for item in stream_iter:
                        yield item
                    return
                except TypeError as type_error:
                    err_text = str(type_error or '')
                    m = re.search(r"unexpected keyword argument ['\"]([^'\"]+)['\"]", err_text)
                    unsupported_key = str(m.group(1) or '').strip() if m else ''
                    if unsupported_key and unsupported_key in call_kwargs:
                        try:
                            app_logger.warning('[chat_async] stream_kwarg_unsupported key=%s', unsupported_key)
                        except Exception:
                            pass
                        call_kwargs.pop(unsupported_key, None)
                        continue
                    raise

        for frame in _chat_stream_gen_compat_call(
            model,
            messages,
            show_steps,
            label,
            **stream_kwargs,
        ):
            for event, event_payload in _chat_async_parse_sse_frames(frame):
                if str(event or '') == 'delta':
                    piece = str((event_payload or {}).get('text') or '')
                    if json_response_mode:
                        if piece:
                            json_delta_buffer += piece
                        continue
                    if piece:
                        now_delta_ts = time.time()
                        if not pending_delta_text:
                            pending_delta_started_at = now_delta_ts
                        pending_delta_text += piece
                        pending_age_s = max(0.0, now_delta_ts - float(pending_delta_started_at or now_delta_ts))
                        should_flush_now = False
                        if len(pending_delta_text) >= _delta_hard_chars:
                            should_flush_now = True
                        elif pending_delta_text[-1] in _delta_break_chars and len(pending_delta_text) >= _delta_min_chars:
                            should_flush_now = True
                        elif len(pending_delta_text) >= _delta_soft_chars:
                            if is_public_job:
                                should_flush_now = True
                            elif pending_delta_text[-1] in _delta_break_chars:
                                should_flush_now = True
                        elif is_public_job and pending_age_s >= _delta_public_force_flush_s and len(pending_delta_text) >= _delta_min_chars:
                            should_flush_now = True
                        if should_flush_now:
                            _flush_pending_delta(force=False)
                    continue
                if not json_response_mode:
                    _flush_pending_delta(force=True)
                _chat_async_append_event(job_key, event, event_payload)

        if json_response_mode:
            pending_delta_text = _chat_async_extract_json_object_text(json_delta_buffer) or json_delta_buffer
        _flush_pending_delta(force=True)

        with _CHAT_ASYNC_JOB_LOCK:
            rec2 = _CHAT_ASYNC_JOBS.get(job_key) or {}
            already_done = bool(rec2.get('done'))
            final_text_for_memory = str(rec2.get('full_text') or '')
        if not already_done:
            _chat_async_append_event(job_key, 'done', {})
    except Exception as e:
        app_logger.exception("chat_async_worker error job_id=%s", job_key)
        raw_error = f'{type(e).__name__}: {e}'
        if str(e or '') == '__async_chat_job_stopped__':
            _chat_async_append_event(job_key, 'status', {'text': '已停止'})
            _chat_async_append_event(job_key, 'done', {})
        else:
            with _CHAT_ASYNC_JOB_LOCK:
                rec_err = _CHAT_ASYNC_JOBS.get(job_key) or {}
                partial_text = str(rec_err.get('full_text') or '')
            if partial_text.strip():
                _chat_async_append_event(job_key, 'status', {
                    'text': '网络波动，已保留当前已生成内容。',
                    'partial': True,
                    'error': raw_error,
                })
                _chat_async_append_event(job_key, 'meta', {
                    'partial': True,
                    'error': raw_error,
                    'mode': 'partial_preserved_after_transport_error',
                })
                _chat_async_append_event(job_key, 'done', {})
            else:
                _chat_async_append_event(job_key, 'error', {'error': f'AI服务异常：{raw_error}'})
                _chat_async_append_event(job_key, 'done', {})
    finally:
        try:
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            if heartbeat_thread is not None and heartbeat_thread.is_alive():
                heartbeat_thread.join(timeout=0.8)
        except Exception:
            pass
        try:
            _set_request_overrides({})
        except Exception:
            pass
        try:
            _chat_async_set_current_stream_handle(None)
        except Exception:
            pass
        try:
            if worker_slot_acquired:
                _chat_async_worker_slot_release(job_key)
                worker_slot_acquired = False
        except Exception:
            pass
        _chat_async_unbind_thread_job()
        with _CHAT_ASYNC_JOB_LOCK:
            rec3 = _CHAT_ASYNC_JOBS.get(job_key)
            if rec3 is not None:
                rec3.pop('payload', None)
                rec3['updated_at'] = time.time()
        _chat_async_notify(job_key)


def _chat_async_cfg_int(name: str, default: int, *, min_value: int = 0, max_value: int = 10000) -> int:
    try:
        value = int(str(app_getenv(name, str(default)) or default).strip())
    except Exception:
        value = int(default)
    return max(int(min_value), min(int(max_value), value))


def _chat_async_owner_key(owner: dict | None = None) -> str:
    return _CHAT_ASYNC_RUN_COORDINATOR.owner_key(owner)


def _chat_async_active_counts(owner: dict | None = None) -> dict:
    owner_key = _chat_async_owner_key(owner)
    total_active = 0
    public_active = 0
    owner_active = 0
    now_ts = time.time()
    stale_running_s = max(300, _chat_async_cfg_int('CHAT_ASYNC_STALE_RUNNING_TIMEOUT_S', 1800, min_value=300, max_value=24 * 3600))
    with _CHAT_ASYNC_JOB_LOCK:
        for rec in list(_CHAT_ASYNC_JOBS.values()):
            if not isinstance(rec, dict) or bool(rec.get('done')):
                continue
            updated_at = float(rec.get('updated_at') or rec.get('created_at') or 0.0)
            if updated_at and (now_ts - updated_at) > stale_running_s:
                continue
            total_active += 1
            if _chat_async_is_public_job(rec):
                public_active += 1
            if owner_key:
                rec_key = _chat_async_owner_key({
                    'email': rec.get('owner_email'),
                    'device_id': rec.get('owner_device_id'),
                })
                if rec_key and rec_key == owner_key:
                    owner_active += 1
    return {'total_active': total_active, 'public_active': public_active, 'owner_active': owner_active}


def _chat_async_busy_response(owner: dict | None = None):
    owner = dict(owner or {})
    if bool(owner.get('is_local_admin_request')):
        return None
    counts = _chat_async_active_counts(owner)
    max_total = _chat_async_cfg_int('CHAT_ASYNC_MAX_ACTIVE_JOBS', 10, min_value=1, max_value=128)
    max_owner = _chat_async_cfg_int('CHAT_ASYNC_MAX_ACTIVE_PER_OWNER', 3, min_value=1, max_value=32)
    max_public = _chat_async_cfg_int('CHAT_ASYNC_MAX_ACTIVE_PUBLIC_JOBS', 6, min_value=1, max_value=128)
    is_public = bool(owner.get('is_public_request'))
    busy_reason = ''
    if int(counts.get('owner_active') or 0) >= max_owner:
        busy_reason = 'owner_active_limit'
    elif int(counts.get('total_active') or 0) >= max_total:
        busy_reason = 'global_active_limit'
    elif is_public and int(counts.get('public_active') or 0) >= max_public:
        busy_reason = 'public_active_limit'
    if not busy_reason:
        return None
    app_logger.warning('[chat_async] busy reject reason=%s counts=%s', busy_reason, counts)
    return _json_no_store_response({
        'ok': False,
        'error': '服务器正在处理较多请求，请稍后重试。',
        'code': 'chat_async_busy',
        'reason': busy_reason,
        'counts': counts,
        'retry_after_ms': 1200,
    }, 429)
