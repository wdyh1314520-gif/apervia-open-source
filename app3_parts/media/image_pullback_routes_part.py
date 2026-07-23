# Split from app3_parts/media/async_pullback_upload_server_part.py.
# Purpose: image pullback job state, monitor, owner filtering, local deletion, and routes.
# Loaded by async_pullback_upload_server_part.py via _exec_split_file(...), sharing the original global namespace.

# ==============================
# IMAGE PULLBACK JOBS
# ==============================
IMAGE_PULLBACK_STORE_FILE = _app_data_path('image_pullback_jobs.json')
_IMAGE_PULLBACK_LOCK = threading.RLock()
_IMAGE_PULLBACK_JOBS: dict[str, dict] = {}
_IMAGE_PULLBACK_MONITORS: dict[str, threading.Thread] = {}
_IMAGE_PULLBACK_MAX_RECORDS = max(60, min(int(str(app_getenv('IMAGE_PULLBACK_MAX_RECORDS', '240') or '240')), 800))
_IMAGE_PULLBACK_SOFT_TIMEOUT_MS = max(30000, min(int(str(app_getenv('IMAGE_PULLBACK_SOFT_TIMEOUT_MS', '180000') or '180000')), 15 * 60 * 1000))


def _image_pullback_owner_from_chat_record(rec: dict | None = None) -> dict:
    rec = rec or {}
    return {
        'email': _normalize_login_email(rec.get('owner_email') or ''),
        'device_id': str(rec.get('owner_device_id') or '').strip(),
        'is_local_admin_request': bool(rec.get('owner_is_local_admin_request')),
        'is_public_request': bool(rec.get('owner_is_public_request')),
        'allow_private_search_targets': bool(rec.get('owner_allow_private_search_targets')),
    }


def _image_pullback_record_owner_fields(owner: dict | None = None) -> dict:
    owner = owner or {}
    return {
        'owner_email': _normalize_login_email(owner.get('email') or owner.get('owner_email') or ''),
        'owner_device_id': str(owner.get('device_id') or owner.get('owner_device_id') or '').strip(),
        'owner_is_local_admin_request': bool(owner.get('is_local_admin_request') or owner.get('owner_is_local_admin_request')),
        'owner_is_public_request': bool(owner.get('is_public_request') or owner.get('owner_is_public_request')),
        'owner_allow_private_search_targets': bool(owner.get('allow_private_search_targets') or owner.get('owner_allow_private_search_targets')),
    }


def _image_pullback_json_clone(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, list):
            return list(value)
        return value


def _image_pullback_status_label(status: str = '') -> str:
    status = str(status or '').strip().lower()
    return {
        'queued': '排队中',
        'running': '拉回中',
        'done': '已完成',
        'error': '失败',
        'expired': '已过期',
        'deleted': '已删除',
    }.get(status, status or '拉回中')


def _image_pullback_public_row(rec: dict | None = None) -> dict:
    rec = rec or {}
    return {
        'id': str(rec.get('id') or '').strip(),
        'source_job_id': str(rec.get('source_job_id') or '').strip(),
        'session_id': str(rec.get('session_id') or '').strip(),
        'session_title': str(rec.get('session_title') or '').strip(),
        'prompt': str(rec.get('prompt') or '').strip(),
        'task_mode': str(rec.get('task_mode') or '').strip(),
        'reason': str(rec.get('reason') or '').strip(),
        'status': str(rec.get('status') or 'running').strip().lower() or 'running',
        'status_label': _image_pullback_status_label(str(rec.get('status') or 'running')),
        'status_text': str(rec.get('status_text') or '').strip(),
        'created_at': _fmt_ts(rec.get('created_at')),
        'created_ts': float(rec.get('created_at') or 0.0),
        'updated_at': _fmt_ts(rec.get('updated_at')),
        'updated_ts': float(rec.get('updated_at') or 0.0),
        'completed_at': _fmt_ts(rec.get('completed_at')) if rec.get('completed_at') else '',
        'completed_ts': float(rec.get('completed_at') or 0.0),
        'error': str(rec.get('error') or '').strip(),
        'full_text': str(rec.get('full_text') or '').strip(),
        'images': [dict(x) for x in (rec.get('images') or []) if isinstance(x, dict)],
        'artifacts': [dict(x) for x in (rec.get('artifacts') or []) if isinstance(x, dict)],
        'done': bool(rec.get('done')),
    }


def _image_pullback_save_locked() -> None:
    rows = [
        _image_pullback_json_clone(v)
        for v in (_IMAGE_PULLBACK_JOBS or {}).values()
        if isinstance(v, dict) and str(v.get('status') or '').strip().lower() != 'deleted'
    ]
    rows.sort(key=lambda x: float(x.get('updated_at') or x.get('created_at') or 0.0), reverse=True)
    rows = rows[:_IMAGE_PULLBACK_MAX_RECORDS]
    payload = {'updated_at': time.time(), 'jobs': rows}
    tmp_path = IMAGE_PULLBACK_STORE_FILE + '.tmp-' + uuid.uuid4().hex
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp_path, IMAGE_PULLBACK_STORE_FILE)
    except Exception:
        try:
            app_logger.exception('[IMAGE_PULLBACK_SAVE] failed')
        except Exception:
            pass
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _image_pullback_load() -> None:
    rows: list[dict] = []
    try:
        if os.path.exists(IMAGE_PULLBACK_STORE_FILE):
            with open(IMAGE_PULLBACK_STORE_FILE, 'r', encoding='utf-8') as f:
                payload = json.load(f) or {}
            raw_jobs = payload.get('jobs') or payload.get('items') or []
            if isinstance(raw_jobs, dict):
                raw_jobs = list(raw_jobs.values())
            if isinstance(raw_jobs, list):
                rows = [dict(x) for x in raw_jobs if isinstance(x, dict)]
    except Exception:
        try:
            app_logger.exception('[IMAGE_PULLBACK_LOAD] failed')
        except Exception:
            pass
        rows = []
    now_ts = time.time()
    with _IMAGE_PULLBACK_LOCK:
        _IMAGE_PULLBACK_JOBS.clear()
        for item in rows:
            rid = str(item.get('id') or '').strip()
            if not rid:
                continue
            status = str(item.get('status') or '').strip().lower()
            if status in {'queued', 'running'}:
                item['status'] = 'expired'
                item['done'] = True
                item['error'] = str(item.get('error') or '服务已重启，原后台任务不再保活。')
                item['status_text'] = '服务已重启，原后台任务已失效。'
                item['completed_at'] = float(item.get('completed_at') or now_ts)
            item.update(_image_pullback_record_owner_fields(item))
            item['created_at'] = float(item.get('created_at') or item.get('updated_at') or now_ts)
            item['updated_at'] = float(item.get('updated_at') or item.get('created_at') or now_ts)
            _IMAGE_PULLBACK_JOBS[rid] = item


def _image_pullback_is_image_filename(filename: str = '') -> bool:
    ext = _history_file_ext(str(filename or '').strip())
    return ext in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg', '.heic', '.heif'}


def _image_pullback_normalize_image_item(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    preview_url = str(item.get('preview_url') or item.get('previewUrl') or item.get('preview') or item.get('thumbnail_url') or item.get('url') or item.get('src') or '').strip()
    view_url = str(item.get('view_url') or item.get('viewUrl') or item.get('url') or preview_url).strip()
    download_url = str(item.get('download_url') or item.get('downloadUrl') or item.get('download') or view_url or preview_url).strip()
    raw_url = str(item.get('raw_url') or item.get('rawUrl') or item.get('file_url') or item.get('url') or preview_url or '').strip()
    filename = str(item.get('filename') or item.get('name') or _extract_saved_filename_from_url(download_url or view_url or preview_url or raw_url) or '').strip()
    if not (preview_url or view_url or download_url or raw_url):
        return None
    return {
        'preview_url': preview_url or view_url or download_url or raw_url,
        'view_url': view_url or preview_url or download_url or raw_url,
        'download_url': download_url or view_url or preview_url or raw_url,
        'raw_url': raw_url or view_url or preview_url or download_url,
        'filename': filename,
        'caption': str(item.get('caption') or item.get('prompt') or item.get('alt') or '').strip(),
        'width': int(item.get('width') or 0) if str(item.get('width') or '').strip().isdigit() else 0,
        'height': int(item.get('height') or 0) if str(item.get('height') or '').strip().isdigit() else 0,
    }


def _image_pullback_image_signature(item: dict | None = None) -> str:
    if not isinstance(item, dict):
        return ''
    return '||'.join([
        str(item.get('download_url') or '').strip(),
        str(item.get('view_url') or '').strip(),
        str(item.get('preview_url') or '').strip(),
        str(item.get('filename') or '').strip(),
    ]).strip('|')


def _image_pullback_images_from_image_reply_payloads(payloads: list | None = None) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for payload in (payloads or []):
        if not isinstance(payload, dict):
            continue
        for raw in (payload.get('images') or []):
            item = _image_pullback_normalize_image_item(raw)
            sig = _image_pullback_image_signature(item)
            if not item or not sig or sig in seen:
                continue
            seen.add(sig)
            out.append(item)
    return out


def _image_pullback_images_from_artifacts(artifacts: list | None = None) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for art in (artifacts or []):
        if not isinstance(art, dict):
            continue
        url = str(art.get('download_url') or art.get('view_url') or art.get('file_url') or art.get('url') or '').strip()
        filename = str(art.get('filename') or _extract_saved_filename_from_url(url) or '').strip()
        if not (url or filename):
            continue
        if not _image_pullback_is_image_filename(filename or url):
            continue
        item = _image_pullback_normalize_image_item({
            'preview_url': str(art.get('view_url') or art.get('download_url') or url).strip(),
            'view_url': str(art.get('view_url') or art.get('download_url') or url).strip(),
            'download_url': str(art.get('download_url') or art.get('view_url') or url).strip(),
            'raw_url': str(art.get('file_url') or art.get('download_url') or art.get('view_url') or url).strip(),
            'filename': filename,
            'caption': str(art.get('label') or art.get('caption') or '').strip(),
        })
        sig = _image_pullback_image_signature(item)
        if not item or not sig or sig in seen:
            continue
        seen.add(sig)
        out.append(item)
    return out


def _image_pullback_collect_chat_job_snapshot(job_id: str) -> dict:
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(str(job_id or '').strip())
        if not isinstance(rec, dict):
            return {'found': False}
        snapshot = {
            'found': True,
            'job_id': str(rec.get('job_id') or job_id or '').strip(),
            'done': bool(rec.get('done')),
            'status': str(rec.get('status') or 'queued').strip().lower() or 'queued',
            'status_text': str(rec.get('status_text') or '').strip(),
            'error': str(rec.get('error') or '').strip(),
            'full_text': str(rec.get('full_text') or '').strip(),
            'artifacts': [dict(x) for x in (rec.get('artifacts') or []) if isinstance(x, dict)],
            'meta': dict(rec.get('meta') or {}) if isinstance(rec.get('meta'), dict) else {},
            'events': [dict(x) for x in (rec.get('events') or []) if isinstance(x, dict)],
        }
    payloads = []
    for event in (snapshot.get('events') or []):
        if str(event.get('event') or '').strip() != 'image_reply':
            continue
        payload = event.get('payload') or {}
        if isinstance(payload, dict):
            payloads.append(dict(payload))
    artifacts = list(snapshot.get('artifacts') or [])
    meta = snapshot.get('meta') or {}
    if isinstance(meta, dict) and isinstance(meta.get('artifacts'), list):
        artifacts.extend([dict(x) for x in meta.get('artifacts') if isinstance(x, dict)])
    images = _image_pullback_images_from_image_reply_payloads(payloads)
    if not images:
        images = _image_pullback_images_from_artifacts(artifacts)
    snapshot['images'] = images
    snapshot['image_reply_payloads'] = payloads
    snapshot['artifacts'] = artifacts
    return snapshot


def _image_pullback_status_from_snapshot(snapshot: dict | None = None) -> str:
    snapshot = snapshot or {}
    if not snapshot.get('found'):
        return 'expired'
    if not snapshot.get('done'):
        status = str(snapshot.get('status') or 'running').strip().lower()
        return 'running' if status in {'queued', 'running'} else (status or 'running')
    error_text = str(snapshot.get('error') or '').strip()
    has_output = bool((snapshot.get('images') or []) or (snapshot.get('artifacts') or []) or str(snapshot.get('full_text') or '').strip())
    if error_text and not has_output:
        return 'error'
    return 'done'


def _image_pullback_track_record(source_job_id: str, *, owner: dict | None = None, prompt: str = '', task_mode: str = '', session_id: str = '', session_title: str = '', reason: str = '') -> dict:
    source_job_id = str(source_job_id or '').strip()
    if not source_job_id:
        return {}
    owner_fields = _image_pullback_record_owner_fields(owner)
    now_ts = time.time()
    with _IMAGE_PULLBACK_LOCK:
        for existing in _IMAGE_PULLBACK_JOBS.values():
            if not isinstance(existing, dict):
                continue
            if str(existing.get('source_job_id') or '').strip() != source_job_id:
                continue
            existing['updated_at'] = now_ts
            if prompt and not str(existing.get('prompt') or '').strip():
                existing['prompt'] = str(prompt or '').strip()[:1000]
            if task_mode and not str(existing.get('task_mode') or '').strip():
                existing['task_mode'] = str(task_mode or '').strip()[:80]
            if session_title and not str(existing.get('session_title') or '').strip():
                existing['session_title'] = str(session_title or '').strip()[:220]
            if session_id and not str(existing.get('session_id') or '').strip():
                existing['session_id'] = str(session_id or '').strip()[:160]
            if reason and not str(existing.get('reason') or '').strip():
                existing['reason'] = str(reason or '').strip()[:80]
            existing.update(owner_fields)
            _image_pullback_save_locked()
            return dict(existing)
        rid = uuid.uuid4().hex
        rec = {
            'id': rid,
            'source_job_id': source_job_id,
            'prompt': str(prompt or '').strip()[:1000],
            'task_mode': str(task_mode or '').strip()[:80],
            'reason': str(reason or '').strip()[:80],
            'session_id': str(session_id or '').strip()[:160],
            'session_title': str(session_title or '').strip()[:220],
            'status': 'running',
            'status_text': '拉回中',
            'created_at': now_ts,
            'updated_at': now_ts,
            'completed_at': 0.0,
            'error': '',
            'full_text': '',
            'images': [],
            'artifacts': [],
            'done': False,
        }
        rec.update(owner_fields)
        _IMAGE_PULLBACK_JOBS[rid] = rec
        _image_pullback_save_locked()
        return dict(rec)


def _image_pullback_sync_from_chat_job(pullback_id: str) -> tuple[dict | None, bool]:
    pullback_id = str(pullback_id or '').strip()
    with _IMAGE_PULLBACK_LOCK:
        current = _IMAGE_PULLBACK_JOBS.get(pullback_id)
        if not isinstance(current, dict):
            return None, True
        source_job_id = str(current.get('source_job_id') or '').strip()
    snapshot = _image_pullback_collect_chat_job_snapshot(source_job_id)
    changed = False
    now_ts = time.time()
    with _IMAGE_PULLBACK_LOCK:
        rec = _IMAGE_PULLBACK_JOBS.get(pullback_id)
        if not isinstance(rec, dict):
            return None, True
        next_status = _image_pullback_status_from_snapshot(snapshot)
        if snapshot.get('found'):
            next_status_text = str(snapshot.get('status_text') or '').strip()
            next_error = str(snapshot.get('error') or '').strip()
            next_full_text = str(snapshot.get('full_text') or '').strip()
            next_images = [dict(x) for x in (snapshot.get('images') or []) if isinstance(x, dict)]
            next_artifacts = [dict(x) for x in (snapshot.get('artifacts') or []) if isinstance(x, dict)]
        else:
            next_status_text = '原后台任务已过期或不可用。'
            next_error = str(rec.get('error') or '原后台任务已过期或不可用。')
            next_full_text = str(rec.get('full_text') or '').strip()
            next_images = [dict(x) for x in (rec.get('images') or []) if isinstance(x, dict)]
            next_artifacts = [dict(x) for x in (rec.get('artifacts') or []) if isinstance(x, dict)]
        new_done = next_status in {'done', 'error', 'expired'}
        updates = {
            'status': next_status,
            'status_text': next_status_text,
            'error': next_error,
            'full_text': next_full_text,
            'images': next_images,
            'artifacts': next_artifacts,
            'done': bool(new_done),
        }
        for key, value in updates.items():
            if rec.get(key) != value:
                rec[key] = value
                changed = True
        if new_done and not rec.get('completed_at'):
            rec['completed_at'] = now_ts
            changed = True
        if changed or not rec.get('updated_at'):
            rec['updated_at'] = now_ts
            changed = True
        if changed:
            _image_pullback_save_locked()
        return dict(rec), bool(rec.get('done'))


def _image_pullback_monitor_loop(pullback_id: str) -> None:
    pullback_id = str(pullback_id or '').strip()
    try:
        idle_rounds = 0
        while True:
            rec, done = _image_pullback_sync_from_chat_job(pullback_id)
            if rec is None or done:
                break
            idle_rounds += 1
            time.sleep(2.0 if idle_rounds < 120 else 5.0)
    except Exception:
        try:
            app_logger.exception('[IMAGE_PULLBACK_MONITOR] id=%s failed', pullback_id)
        except Exception:
            pass
    finally:
        with _IMAGE_PULLBACK_LOCK:
            _IMAGE_PULLBACK_MONITORS.pop(pullback_id, None)


def _image_pullback_ensure_monitor(pullback_id: str) -> None:
    pullback_id = str(pullback_id or '').strip()
    if not pullback_id:
        return
    with _IMAGE_PULLBACK_LOCK:
        worker = _IMAGE_PULLBACK_MONITORS.get(pullback_id)
        if worker and worker.is_alive():
            return
        worker = threading.Thread(target=_image_pullback_monitor_loop, args=(pullback_id,), daemon=True)
        _IMAGE_PULLBACK_MONITORS[pullback_id] = worker
    worker.start()


def _image_pullback_hint_current_async_job(prompt_text: str = '', *, task_mode: str = '', settings: dict | None = None, image_sources: list | None = None) -> dict:
    job_id = _chat_async_current_job_id()
    if not job_id:
        return {}
    _chat_async_append_event(job_id, 'image_pullback_hint', {
        'soft_timeout_ms': _IMAGE_PULLBACK_SOFT_TIMEOUT_MS,
        'prompt': str(prompt_text or '').strip()[:1000],
        'task_mode': str(task_mode or '').strip(),
        'status_text': '图片任务超时保护已开启。',
    })
    return {'ok': True, 'job_id': job_id, 'soft_timeout_ms': _IMAGE_PULLBACK_SOFT_TIMEOUT_MS}


def _image_pullback_track_current_async_job(prompt_text: str = '', *, task_mode: str = '', settings: dict | None = None, image_sources: list | None = None) -> dict:
    job_id = _chat_async_current_job_id()
    if not job_id:
        return {}
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(job_id)
        if not isinstance(rec, dict):
            return {}
        owner = _image_pullback_owner_from_chat_record(rec)
        payload = dict(rec.get('payload') or {}) if isinstance(rec.get('payload'), dict) else {}
    rec_pb = _image_pullback_track_record(
        job_id,
        owner=owner,
        prompt=str(prompt_text or '').strip(),
        task_mode=str(task_mode or '').strip(),
        session_id=str(payload.get('client_session_id') or payload.get('session_id') or '').strip(),
        session_title=str(payload.get('client_session_title') or payload.get('session_title') or '').strip(),
        reason='backend_track',
    )
    pullback_id = str(rec_pb.get('id') or '').strip()
    if pullback_id:
        _image_pullback_ensure_monitor(pullback_id)
        _chat_async_append_event(job_id, 'image_pullback_hint', {
            'pullback_id': pullback_id,
            'soft_timeout_ms': _IMAGE_PULLBACK_SOFT_TIMEOUT_MS,
            'prompt': str(prompt_text or '').strip()[:1000],
            'task_mode': str(task_mode or '').strip(),
            'status_text': '图片任务已进入后台拉回保护。',
        })
    return rec_pb


def _image_pullback_list_for_owner(owner: dict | None = None) -> list[dict]:
    owner = owner or {}
    rows: list[dict] = []
    with _IMAGE_PULLBACK_LOCK:
        for rec in _IMAGE_PULLBACK_JOBS.values():
            if not isinstance(rec, dict):
                continue
            if not _chat_async_can_access(rec, owner):
                continue
            reason = str(rec.get('reason') or '').strip().lower()
            if reason not in {'frontend_soft_timeout', 'frontend_timeout', 'soft_timeout'}:
                continue
            rows.append(dict(rec))
    rows.sort(key=lambda x: float(x.get('updated_at') or x.get('created_at') or 0.0), reverse=True)
    for row in rows:
        if str(row.get('status') or '').strip().lower() in {'queued', 'running'}:
            _image_pullback_ensure_monitor(str(row.get('id') or '').strip())
    return [_image_pullback_public_row(x) for x in rows]


def _image_pullback_url_to_local_path(url: str = '') -> str | None:
    filename = _extract_saved_filename_from_url(url)
    if not filename:
        return None
    base_dir = _resolve_generated_file_dir(filename)
    if base_dir:
        return os.path.join(base_dir, filename)
    base_dir = _resolve_uploaded_file_dir(filename)
    if base_dir:
        return os.path.join(base_dir, filename)
    return None


def _image_pullback_delete_local_files(rec: dict | None = None) -> None:
    urls: list[str] = []
    for item in (rec or {}).get('images') or []:
        if not isinstance(item, dict):
            continue
        for key in ('download_url', 'view_url', 'preview_url', 'raw_url'):
            val = str(item.get(key) or '').strip()
            if val:
                urls.append(val)
    for item in (rec or {}).get('artifacts') or []:
        if not isinstance(item, dict):
            continue
        for key in ('download_url', 'view_url', 'file_url', 'url'):
            val = str(item.get(key) or '').strip()
            if val:
                urls.append(val)
    seen_paths: set[str] = set()
    for url in urls:
        path = _image_pullback_url_to_local_path(url)
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        try:
            if os.path.exists(path):
                os.remove(path)
                try:
                    post_delete = globals().get('_storage_quota_after_local_file_deleted')
                    if callable(post_delete):
                        post_delete(path, reason='image_pullback_delete')
                except Exception:
                    pass
        except Exception:
            try:
                app_logger.exception('[IMAGE_PULLBACK_DELETE_FILE] path=%s failed', path)
            except Exception:
                pass


@app.get('/api3/image-pullback/list')
def image_pullback_list_route():
    owner = _chat_async_owner_snapshot()
    jobs = _image_pullback_list_for_owner(owner)
    return _json_no_store_response({'ok': True, 'jobs': jobs, 'count': len(jobs), 'soft_timeout_ms': _IMAGE_PULLBACK_SOFT_TIMEOUT_MS})


@app.post('/api3/image-pullback/track')
def image_pullback_track_route():
    payload = request.get_json(force=True, silent=True) or {}
    source_job_id = str(payload.get('source_job_id') or payload.get('sourceJobId') or '').strip()
    if not source_job_id:
        return jsonify({'error': '缺少 source_job_id'}), 400
    owner = _chat_async_owner_snapshot()
    with _CHAT_ASYNC_JOB_LOCK:
        rec = _CHAT_ASYNC_JOBS.get(source_job_id)
        if not isinstance(rec, dict):
            return jsonify({'error': '后台任务不存在或已过期'}), 404
        if not _chat_async_can_access(rec, owner):
            return jsonify({'error': '无权操作该任务'}), 403
        job_owner = _image_pullback_owner_from_chat_record(rec)
        job_payload = dict(rec.get('payload') or {}) if isinstance(rec.get('payload'), dict) else {}
    reason = str(payload.get('reason') or 'frontend_soft_timeout').strip().lower() or 'frontend_soft_timeout'
    if reason not in {'frontend_soft_timeout', 'frontend_timeout', 'soft_timeout'}:
        reason = 'frontend_soft_timeout'
    rec_pb = _image_pullback_track_record(
        source_job_id,
        owner=job_owner,
        prompt=str(payload.get('prompt') or '').strip(),
        task_mode=str(payload.get('task_mode') or payload.get('taskMode') or '').strip(),
        session_id=str(payload.get('session_id') or payload.get('sessionId') or job_payload.get('client_session_id') or job_payload.get('session_id') or '').strip(),
        session_title=str(payload.get('session_title') or payload.get('sessionTitle') or job_payload.get('client_session_title') or job_payload.get('session_title') or '').strip(),
        reason=reason,
    )
    pullback_id = str(rec_pb.get('id') or '').strip()
    if pullback_id:
        _image_pullback_ensure_monitor(pullback_id)
    return _json_no_store_response({'ok': True, 'job': _image_pullback_public_row(rec_pb)})


@app.post('/api3/image-pullback/clear')
def image_pullback_clear_route():
    owner = _chat_async_owner_snapshot()
    removed: list[dict] = []
    with _IMAGE_PULLBACK_LOCK:
        for pullback_id, rec in list(_IMAGE_PULLBACK_JOBS.items()):
            if not isinstance(rec, dict):
                continue
            if not _chat_async_can_access(rec, owner):
                continue
            reason = str(rec.get('reason') or '').strip().lower()
            if reason not in {'frontend_soft_timeout', 'frontend_timeout', 'soft_timeout'}:
                continue
            removed.append(dict(rec))
            _IMAGE_PULLBACK_JOBS.pop(pullback_id, None)
        if removed:
            _image_pullback_save_locked()
    for rec in removed:
        try:
            _image_pullback_delete_local_files(rec)
        except Exception:
            try:
                app_logger.exception('[IMAGE_PULLBACK_CLEAR] delete files failed')
            except Exception:
                pass
    return _json_no_store_response({'ok': True, 'count': len(removed)})


@app.post('/api3/image-pullback/delete')
def image_pullback_delete_route():
    payload = request.get_json(force=True, silent=True) or {}
    pullback_id = str(payload.get('id') or '').strip()
    if not pullback_id:
        return jsonify({'error': '缺少 id'}), 400
    owner = _chat_async_owner_snapshot()
    removed = None
    with _IMAGE_PULLBACK_LOCK:
        rec = _IMAGE_PULLBACK_JOBS.get(pullback_id)
        if rec is None:
            return jsonify({'error': '拉回记录不存在'}), 404
        if not _chat_async_can_access(rec, owner):
            return jsonify({'error': '无权操作该记录'}), 403
        removed = dict(rec)
        _IMAGE_PULLBACK_JOBS.pop(pullback_id, None)
        _image_pullback_save_locked()
    try:
        _image_pullback_delete_local_files(removed)
    except Exception:
        try:
            app_logger.exception('[IMAGE_PULLBACK_DELETE] id=%s delete files failed', pullback_id)
        except Exception:
            pass
    return _json_no_store_response({'ok': True, 'id': pullback_id})
