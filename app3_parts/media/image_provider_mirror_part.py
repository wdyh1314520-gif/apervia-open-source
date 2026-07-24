# provider URL mirror cache, streaming downloader, and mirror-status route.

_IMAGE_GENERATION_PROVIDER_MIRROR_LOCKS_GUARD = threading.Lock()
_IMAGE_GENERATION_PROVIDER_MIRROR_LOCKS: dict[str, threading.Lock] = {}
_IMAGE_GENERATION_PROVIDER_MIRROR_DONE: dict[str, dict] = {}
_IMAGE_GENERATION_PROVIDER_MIRROR_STATUS: dict[str, dict] = {}
_IMAGE_GENERATION_PROVIDER_MIRROR_STORE_FILE = _app_data_path('image_generation_provider_mirrors.json')


def _image_generation_provider_mirror_key(provider_url: str) -> str:
    return hashlib.sha1(str(provider_url or '').encode('utf-8', 'ignore')).hexdigest()


def _image_generation_provider_url_host(provider_url: str) -> str:
    try:
        return str(urllib.parse.urlparse(str(provider_url or '').strip()).hostname or '').strip().lower()
    except Exception:
        return ''


def _image_generation_provider_mirror_status_update(provider_url: str, **fields) -> dict:
    u = str(provider_url or '').strip()
    if not u:
        return {}
    key = _image_generation_provider_mirror_key(u)
    now_ms = int(time.time() * 1000)
    with _IMAGE_GENERATION_PROVIDER_MIRROR_LOCKS_GUARD:
        if len(_IMAGE_GENERATION_PROVIDER_MIRROR_STATUS) > 768:
            for old_key in list(_IMAGE_GENERATION_PROVIDER_MIRROR_STATUS.keys())[:192]:
                _IMAGE_GENERATION_PROVIDER_MIRROR_STATUS.pop(old_key, None)
        rec = dict(_IMAGE_GENERATION_PROVIDER_MIRROR_STATUS.get(key) or {})
        rec.setdefault('provider_url', u)
        rec.setdefault('url_host', _image_generation_provider_url_host(u))
        rec['updated_at_ms'] = now_ms
        for k, v in (fields or {}).items():
            if v is None:
                continue
            rec[str(k)] = v
        _IMAGE_GENERATION_PROVIDER_MIRROR_STATUS[key] = rec
        return dict(rec)


def _image_generation_provider_mirror_status_snapshot(provider_url: str) -> dict:
    u = str(provider_url or '').strip()
    if not u:
        return {}
    key = _image_generation_provider_mirror_key(u)
    with _IMAGE_GENERATION_PROVIDER_MIRROR_LOCKS_GUARD:
        return dict(_IMAGE_GENERATION_PROVIDER_MIRROR_STATUS.get(key) or {})


def _image_generation_provider_mirror_public_artifact(saved: dict | None = None) -> dict:
    src = dict(saved or {}) if isinstance(saved, dict) else {}
    if not src:
        return {}
    allow = {
        'filename', 'mime', 'size', 'download_url', 'view_url', 'url', 'raw_url',
        'preview_url', 'preview_download_url', 'preview_filename', 'preview_size', 'preview_mime',
        'object_url', 'storage_backend', 'scope', 'source_type', 'generated_by_assistant',
        'provider_url', 'delivery_mode', 'is_temporary_remote', 'created_at_ms',
        'source_role', 'operation', 'image_seq', 'parent_image_id',
        'elapsed_ms', 'header_ms', 'first_byte_ms', 'download_ms', 'bytes_per_sec',
        'content_length', 'status_code', 'final_url', 'url_host', 'final_host',
        'download_mode', 'parallel_download', 'range_parts',
    }
    out = {k: v for k, v in src.items() if k in allow}
    if out:
        out['mirror_status'] = 'ready'
        out['is_temporary_remote'] = False
        out['delivery_mode'] = 'server_mirrored'
    return out


def _image_generation_provider_mirror_lock(provider_url: str) -> threading.Lock:
    key = _image_generation_provider_mirror_key(provider_url)
    with _IMAGE_GENERATION_PROVIDER_MIRROR_LOCKS_GUARD:
        lock = _IMAGE_GENERATION_PROVIDER_MIRROR_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _IMAGE_GENERATION_PROVIDER_MIRROR_LOCKS[key] = lock
        return lock


def _image_generation_provider_mirror_cached(provider_url: str) -> dict:
    key = _image_generation_provider_mirror_key(provider_url)
    with _IMAGE_GENERATION_PROVIDER_MIRROR_LOCKS_GUARD:
        cached = dict(_IMAGE_GENERATION_PROVIDER_MIRROR_DONE.get(key) or {})
    if cached:
        return cached
    try:
        if not os.path.isfile(_IMAGE_GENERATION_PROVIDER_MIRROR_STORE_FILE):
            return {}
        with open(_IMAGE_GENERATION_PROVIDER_MIRROR_STORE_FILE, 'r', encoding='utf-8') as f:
            payload = json.load(f) or {}
        items = payload.get('items') if isinstance(payload, dict) else {}
        rec = dict((items or {}).get(key) or {}) if isinstance(items, dict) else {}
        saved = rec.get('saved') if isinstance(rec.get('saved'), dict) else rec
        if not isinstance(saved, dict) or not saved:
            return {}
        filename = str(saved.get('filename') or '').strip()
        scope = str(saved.get('scope') or '').strip()
        if filename:
            try:
                resolver = globals().get('_resolve_generated_file_dir')
                base_dir = resolver(filename, scope=scope or None) if callable(resolver) else ''
                if base_dir and not os.path.isfile(os.path.join(base_dir, os.path.basename(filename))):
                    return {}
            except Exception:
                pass
        with _IMAGE_GENERATION_PROVIDER_MIRROR_LOCKS_GUARD:
            _IMAGE_GENERATION_PROVIDER_MIRROR_DONE[key] = dict(saved)
        return dict(saved)
    except Exception:
        return {}


def _image_generation_provider_mirror_remember(provider_url: str, saved: dict | None = None) -> None:
    if not isinstance(saved, dict) or not saved:
        return
    key = _image_generation_provider_mirror_key(provider_url)
    saved_copy = dict(saved)
    saved_copy.setdefault('provider_url', str(provider_url or '').strip())
    with _IMAGE_GENERATION_PROVIDER_MIRROR_LOCKS_GUARD:
        if len(_IMAGE_GENERATION_PROVIDER_MIRROR_DONE) > 512:
            for old_key in list(_IMAGE_GENERATION_PROVIDER_MIRROR_DONE.keys())[:128]:
                _IMAGE_GENERATION_PROVIDER_MIRROR_DONE.pop(old_key, None)
        _IMAGE_GENERATION_PROVIDER_MIRROR_DONE[key] = dict(saved_copy)
        try:
            payload = {'items': {}, 'updated_at_ms': int(time.time() * 1000)}
            if os.path.isfile(_IMAGE_GENERATION_PROVIDER_MIRROR_STORE_FILE):
                with open(_IMAGE_GENERATION_PROVIDER_MIRROR_STORE_FILE, 'r', encoding='utf-8') as f:
                    old = json.load(f) or {}
                if isinstance(old, dict) and isinstance(old.get('items'), dict):
                    payload['items'] = dict(old.get('items') or {})
            payload['items'][key] = {
                'provider_url': str(provider_url or '').strip(),
                'saved': dict(saved_copy),
                'updated_at_ms': int(time.time() * 1000),
            }
            if len(payload['items']) > 512:
                rows = sorted(payload['items'].items(), key=lambda kv: int(((kv[1] or {}).get('updated_at_ms') or 0)), reverse=True)[:512]
                payload['items'] = dict(rows)
            tmp = _IMAGE_GENERATION_PROVIDER_MIRROR_STORE_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
            os.replace(tmp, _IMAGE_GENERATION_PROVIDER_MIRROR_STORE_FILE)
        except Exception:
            pass
    _image_generation_provider_mirror_status_update(
        provider_url,
        status='ready',
        ready=True,
        filename=str(saved_copy.get('filename') or ''),
        view_url=str(saved_copy.get('view_url') or ''),
        preview_url=str(saved_copy.get('preview_url') or ''),
        size=int(saved_copy.get('size') or 0),
        elapsed_ms=int(saved_copy.get('elapsed_ms') or saved_copy.get('download_ms') or 0),
        bytes_per_sec=float(saved_copy.get('bytes_per_sec') or 0.0),
    )


def _image_generation_ext_for_content_type(content_type: str = '', fallback_filename: str = '', fallback_ext: str = 'png') -> str:
    mime = str(content_type or '').split(';', 1)[0].strip().lower()
    if mime == 'image/svg+xml':
        return '.svg'
    if mime in {'image/x-icon', 'image/vnd.microsoft.icon'}:
        return '.ico'
    for ext_key, mime_value in (UPLOAD_IMAGE_MIME_BY_EXT or {}).items():
        if str(mime_value or '').lower() == mime:
            return str(ext_key or '').lower()
    if mime.startswith('image/'):
        return _model_image_ext_for_mime(mime)
    current_ext = os.path.splitext(str(fallback_filename or '').strip())[1].lower()
    if current_ext in UPLOAD_IMAGE_EXTS:
        return current_ext
    safe_fallback = str(fallback_ext or 'png').strip().lower().lstrip('.') or 'png'
    if safe_fallback == 'jpg':
        safe_fallback = 'jpeg'
    return '.' + safe_fallback




def _image_generation_parallel_range_download_enabled(scope: str | None = None) -> bool:
    try:
        raw = str(app_getenv('IMAGE_GENERATION_PARALLEL_RANGE_DOWNLOAD', '1') or '1').strip().lower()
        return raw in {'1', 'true', 'yes', 'on', 'y'}
    except Exception:
        return True


def _image_generation_parallel_range_min_bytes() -> int:
    try:
        return max(512 * 1024, int(str(app_getenv('IMAGE_GENERATION_PARALLEL_RANGE_MIN_BYTES', str(1536 * 1024)) or (1536 * 1024))))
    except Exception:
        return 1536 * 1024


def _image_generation_parallel_range_parts(content_length: int = 0) -> int:
    try:
        configured = int(str(app_getenv('IMAGE_GENERATION_PARALLEL_RANGE_PARTS', '4') or '4'))
    except Exception:
        configured = 4
    configured = max(2, min(configured, 8))
    try:
        length = int(content_length or 0)
    except Exception:
        length = 0
    if length > 0:
        # Keep each range large enough to avoid turning small images into noisy extra requests.
        by_size = max(2, min(configured, max(2, length // (512 * 1024))))
        return int(by_size)
    return configured


def _image_generation_range_headers(base_headers: dict | None = None, byte_range: str = '') -> dict:
    out = {}
    if isinstance(base_headers, dict):
        for k, v in base_headers.items():
            key = str(k or '').strip()
            if not key:
                continue
            if key.lower() in {'range', 'accept-encoding'}:
                continue
            out[key] = str(v or '')
    out['Accept-Encoding'] = 'identity'
    if byte_range:
        out['Range'] = byte_range
    return out


def _image_generation_try_parallel_range_download_to_tmp(
    provider_url: str,
    *,
    final_url: str = '',
    headers: dict | None = None,
    target_dir: str,
    content_length: int = 0,
    timeout: float = 25.0,
    started_at: float | None = None,
    status_url: str = '',
    scope: str | None = None,
) -> dict:
    """Download a large provider image with parallel HTTP Range requests when supported.

    If the upstream URL does not support byte ranges, this returns ok=False and the
    caller continues with the existing single-stream path. The merged output is
    byte-for-byte the original image, so preview/original quality is unchanged.
    """
    u = str(provider_url or '').strip()
    download_url = str(final_url or u).strip()
    status_key = str(status_url or u).strip()
    result = {
        'ok': False,
        'skip_reason': '',
        'error': '',
        'tmp_path': '',
        'head': b'',
        'total': 0,
        'first_byte_ms': 0,
        'download_ms': 0,
        'bytes_per_sec': 0.0,
        'range_parts': 0,
        'parallel_download': False,
    }
    if not u or not download_url:
        result['skip_reason'] = 'empty_url'
        return result
    if not _image_generation_parallel_range_download_enabled(scope):
        result['skip_reason'] = 'disabled'
        return result
    try:
        length = int(content_length or 0)
    except Exception:
        length = 0
    if length < _image_generation_parallel_range_min_bytes():
        result['skip_reason'] = 'small_or_unknown_length'
        return result
    started = float(started_at or time.time())
    timeout_v = max(3.0, min(float(timeout or 25.0), 120.0))
    parts = _image_generation_parallel_range_parts(length)
    if parts < 2:
        result['skip_reason'] = 'single_part'
        return result

    chunk_size = int(math.ceil(float(length) / float(parts)))
    ranges: list[tuple[int, int, int]] = []
    pos = 0
    idx = 0
    while pos < length:
        end = min(length - 1, pos + chunk_size - 1)
        ranges.append((idx, pos, end))
        idx += 1
        pos = end + 1
    parts = len(ranges)
    if parts < 2:
        result['skip_reason'] = 'range_split_failed'
        return result

    os.makedirs(target_dir, exist_ok=True)
    tmp_prefix = os.path.join(target_dir, f'.tmp-image-provider-range-{uuid.uuid4().hex}')
    merged_tmp = tmp_prefix + '.merged.part'
    progress_lock = threading.Lock()
    progress = {'bytes': 0, 'first_byte_ms': 0, 'last_update_at': 0.0}
    part_paths: list[str] = []

    def _cleanup() -> None:
        for path in list(part_paths) + [merged_tmp]:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    def _download_part(part_index: int, start_byte: int, end_byte: int) -> dict:
        expected = max(0, int(end_byte - start_byte + 1))
        part_path = f'{tmp_prefix}.{part_index}.part'
        local_total = 0
        range_header = f'bytes={int(start_byte)}-{int(end_byte)}'
        req_headers = _image_generation_range_headers(headers, range_header)
        resp = None
        try:
            resp = requests.get(download_url, timeout=timeout_v, headers=req_headers, allow_redirects=True, stream=True)
            status = int(resp.status_code or 0)
            if status != 206:
                return {'ok': False, 'error': f'range_http_{status}', 'status': status, 'part': part_index}
            with open(part_path, 'wb') as wf:
                for chunk in resp.iter_content(chunk_size=512 * 1024):
                    if not chunk:
                        continue
                    wf.write(chunk)
                    n = len(chunk)
                    local_total += n
                    now_chunk = time.time()
                    with progress_lock:
                        progress['bytes'] = int(progress.get('bytes') or 0) + n
                        if not progress.get('first_byte_ms'):
                            progress['first_byte_ms'] = int((now_chunk - started) * 1000)
                        if now_chunk - float(progress.get('last_update_at') or 0.0) >= 0.8:
                            progress['last_update_at'] = now_chunk
                            elapsed_s = max(0.001, now_chunk - started)
                            speed = float(progress['bytes']) / elapsed_s
                            _image_generation_provider_mirror_status_update(
                                status_key,
                                status='downloading',
                                ready=False,
                                download_mode='parallel_range',
                                parallel_download=True,
                                range_parts=int(parts),
                                bytes_downloaded=int(progress['bytes']),
                                content_length=int(length),
                                download_ms=int((now_chunk - started) * 1000),
                                first_byte_ms=int(progress.get('first_byte_ms') or 0),
                                bytes_per_sec=round(speed, 2),
                            )
                try:
                    wf.flush()
                    os.fsync(wf.fileno())
                except Exception:
                    pass
            if local_total != expected:
                return {'ok': False, 'error': f'range_size_mismatch:{local_total}!={expected}', 'status': status, 'part': part_index}
            return {'ok': True, 'path': part_path, 'part': part_index, 'size': local_total, 'status': status}
        except Exception as e:
            return {'ok': False, 'error': f'{type(e).__name__}: {e}', 'part': part_index}
        finally:
            try:
                if resp is not None:
                    resp.close()
            except Exception:
                pass

    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        _image_generation_provider_mirror_status_update(
            status_key,
            status='downloading',
            ready=False,
            download_mode='parallel_range',
            parallel_download=True,
            range_parts=int(parts),
            content_length=int(length),
            bytes_downloaded=0,
        )
        rows = []
        with ThreadPoolExecutor(max_workers=parts) as ex:
            futures = [ex.submit(_download_part, part_idx, start_byte, end_byte) for part_idx, start_byte, end_byte in ranges]
            for fut in as_completed(futures):
                row = fut.result()
                if not row.get('ok'):
                    result['error'] = str(row.get('error') or 'range_failed')
                    _cleanup()
                    _image_generation_log('mirror_range_failed', error=result['error'], range_parts=parts, content_length=length, url=u, final_url=download_url)
                    return result
                rows.append(row)
                part_paths.append(str(row.get('path') or ''))
        rows.sort(key=lambda x: int(x.get('part') or 0))
        head = b''
        total = 0
        with open(merged_tmp, 'wb') as out_f:
            for row in rows:
                part_path = str(row.get('path') or '')
                with open(part_path, 'rb') as pf:
                    while True:
                        data = pf.read(1024 * 1024)
                        if not data:
                            break
                        if len(head) < 512:
                            head += data[:512 - len(head)]
                        out_f.write(data)
                        total += len(data)
            try:
                out_f.flush()
                os.fsync(out_f.fileno())
            except Exception:
                pass
        for path in part_paths:
            try:
                os.remove(path)
            except Exception:
                pass
        part_paths.clear()
        elapsed_ms = int((time.time() - started) * 1000)
        result.update({
            'ok': True,
            'tmp_path': merged_tmp,
            'head': head,
            'total': total,
            'first_byte_ms': int(progress.get('first_byte_ms') or 0),
            'download_ms': elapsed_ms,
            'bytes_per_sec': round(float(total or 0) / max(0.001, elapsed_ms / 1000.0), 2),
            'range_parts': int(parts),
            'parallel_download': True,
        })
        _image_generation_log('mirror_range_done', elapsed_ms=elapsed_ms, bytes=total, bps=result['bytes_per_sec'], range_parts=parts, content_length=length, url=u, final_url=download_url)
        return result
    except Exception as e:
        result['error'] = f'{type(e).__name__}: {e}'
        _cleanup()
        _image_generation_log('mirror_range_exception', error=result['error'], range_parts=parts, content_length=length, url=u, final_url=download_url)
        return result

def _image_generation_stream_provider_url_to_scope(provider_url: str, *, filename: str = '', mime_hint: str = '', scope: str | None = None, timeout: float = 25.0, headers: dict | None = None) -> dict:
    """Mirror a provider-returned image URL directly to disk.

    This path is intentionally lighter than the normal generated-file saver:
    it streams network -> temp file -> atomic rename, skips preview generation,
    and queues object-storage mirroring asynchronously. The UI can keep showing
    the provider URL immediately while this background landing finishes.
    """
    u = str(provider_url or '').strip()
    result = {
        'ok': False,
        'url': u,
        'final_url': u,
        'status_code': 0,
        'content_type': '',
        'size': 0,
        'error': '',
        'url_host': _image_generation_provider_url_host(u),
        'final_host': '',
        'content_length': 0,
        'header_ms': 0,
        'first_byte_ms': 0,
        'download_ms': 0,
        'bytes_per_sec': 0.0,
    }
    if not u:
        result['error'] = 'empty_url'
        return result
    try:
        attempts = int(str(app_getenv('IMAGE_GENERATION_DOWNLOAD_RETRIES', '2') or '2'))
    except Exception:
        attempts = 2
    attempts = max(1, min(attempts, 4))
    timeout_v = max(3.0, min(float(timeout or 25.0), 120.0))
    req_headers = _image_generation_download_headers_for_url(u, headers)
    normalized_scope = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    target_dir = _generated_dir_for_scope(normalized_scope, ensure=True)
    _image_generation_provider_mirror_status_update(
        u,
        status='running',
        ready=False,
        scope=normalized_scope,
        url_host=result.get('url_host') or _image_generation_provider_url_host(u),
        started_at_ms=int(time.time() * 1000),
    )
    hint_name = _safe_filename(filename or '') or _image_generation_filename_from_url(u, index=1, ext='png')
    if os.path.splitext(hint_name)[1].lower() not in ALLOWED_EXT:
        hint_name = _image_generation_filename(1, ext='png')

    for attempt in range(1, attempts + 1):
        tmp_path = ''
        started = time.time()
        resp = None
        try:
            resp = requests.get(u, timeout=timeout_v, headers=req_headers, allow_redirects=True, stream=True)
            header_at = time.time()
            status = int(resp.status_code or 0)
            final_url = str(getattr(resp, 'url', u) or u)
            header_mime = str(resp.headers.get('content-type') or '').split(';', 1)[0].strip().lower()
            final_host = _image_generation_provider_url_host(final_url)
            try:
                content_length = int(str(resp.headers.get('content-length') or '0').strip() or 0)
            except Exception:
                content_length = 0
            header_ms = int((header_at - started) * 1000)
            result['status_code'] = status
            result['final_url'] = final_url
            result['final_host'] = final_host
            result['content_type'] = header_mime
            result['content_length'] = content_length
            result['header_ms'] = header_ms
            _image_generation_provider_mirror_status_update(
                u,
                status='headers',
                ready=False,
                http_status=status,
                status_code=status,
                final_url=final_url,
                final_host=final_host,
                content_type=header_mime,
                content_length=content_length,
                header_ms=header_ms,
            )
            if not resp.ok:
                result['error'] = f'http_{status or 0}'
                _image_generation_provider_mirror_status_update(u, status='failed', ready=False, error=result['error'], http_status=status, status_code=status)
                _image_generation_log('mirror_stream_http_failed', attempt=attempt, status=status, header_ms=header_ms, content_length=content_length, url=u, final_url=final_url)
                continue

            tmp_path = ''
            head = b''
            total = 0
            parallel_info = _image_generation_try_parallel_range_download_to_tmp(
                u,
                final_url=final_url,
                headers=req_headers,
                target_dir=target_dir,
                content_length=content_length,
                timeout=timeout_v,
                started_at=started,
                status_url=u,
                scope=normalized_scope,
            )
            if parallel_info.get('ok'):
                try:
                    resp.close()
                except Exception:
                    pass
                resp = None
                tmp_path = str(parallel_info.get('tmp_path') or '')
                head = bytes(parallel_info.get('head') or b'')
                total = int(parallel_info.get('total') or 0)
                result['first_byte_ms'] = int(parallel_info.get('first_byte_ms') or 0)
                result['download_ms'] = int(parallel_info.get('download_ms') or 0)
                result['bytes_per_sec'] = float(parallel_info.get('bytes_per_sec') or 0.0)
                result['parallel_download'] = True
                result['download_mode'] = 'parallel_range'
                result['range_parts'] = int(parallel_info.get('range_parts') or 0)
            else:
                if parallel_info.get('error'):
                    _image_generation_log('mirror_range_fallback_stream', attempt=attempt, reason=str(parallel_info.get('error') or ''), content_length=content_length, url=u, final_url=final_url)
                tmp_path = os.path.join(target_dir, f'.tmp-image-provider-{uuid.uuid4().hex}.part')
                first_byte_ms = 0
                last_progress_log = 0.0
                with open(tmp_path, 'wb') as wf:
                    for chunk in resp.iter_content(chunk_size=512 * 1024):
                        if not chunk:
                            continue
                        now_chunk = time.time()
                        if not first_byte_ms:
                            first_byte_ms = int((now_chunk - started) * 1000)
                            result['first_byte_ms'] = first_byte_ms
                            _image_generation_provider_mirror_status_update(u, status='downloading', ready=False, first_byte_ms=first_byte_ms, download_mode='single_stream')
                        if len(head) < 512:
                            head += bytes(chunk[:512 - len(head)])
                        wf.write(chunk)
                        total += len(chunk)
                        if now_chunk - last_progress_log >= 1.0:
                            last_progress_log = now_chunk
                            elapsed_s = max(0.001, now_chunk - started)
                            speed = float(total) / elapsed_s
                            _image_generation_provider_mirror_status_update(
                                u,
                                status='downloading',
                                ready=False,
                                download_mode='single_stream',
                                bytes_downloaded=int(total),
                                content_length=content_length,
                                download_ms=int((now_chunk - started) * 1000),
                                bytes_per_sec=round(speed, 2),
                            )
                    try:
                        wf.flush()
                        os.fsync(wf.fileno())
                    except Exception:
                        pass
            if total <= 0:
                result['error'] = 'empty_body'
                _image_generation_provider_mirror_status_update(u, status='failed', ready=False, error=result['error'], bytes_downloaded=0)
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                _image_generation_log('mirror_stream_empty', attempt=attempt, status=status, header_ms=result.get('header_ms'), url=u, final_url=final_url)
                continue

            sniffed_mime = ''
            try:
                sniffed_mime = _favicon_sniff_mime(head)
            except Exception:
                sniffed_mime = ''
            effective_mime = (sniffed_mime or header_mime or str(mime_hint or '').split(';', 1)[0].strip().lower() or _guess_content_type_for_file(hint_name) or 'application/octet-stream').strip().lower()
            current_ext = os.path.splitext(hint_name)[1].lower()
            image_like = bool(effective_mime.startswith('image/') or current_ext in UPLOAD_IMAGE_EXTS)
            if not image_like:
                result['error'] = f'non_image:{effective_mime or "unknown"}'
                _image_generation_provider_mirror_status_update(u, status='failed', ready=False, error=result['error'], content_type=effective_mime)
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                _image_generation_log('mirror_stream_non_image', attempt=attempt, status=status, content_type=effective_mime, url=u, final_url=final_url)
                continue

            resolved_ext = _image_generation_ext_for_content_type(effective_mime, hint_name, fallback_ext='png')
            target_name = hint_name
            stem, cur_ext = os.path.splitext(target_name)
            cur_ext_l = cur_ext.lower()
            if resolved_ext and (not cur_ext_l or cur_ext_l not in UPLOAD_IMAGE_EXTS or (sniffed_mime and cur_ext_l != resolved_ext)):
                target_name = f'{stem or "image"}{resolved_ext}'
            final_fn = _dedupe_filename(target_dir, _safe_filename(target_name or '') or _image_generation_filename(1, ext=resolved_ext.lstrip('.') or 'png'))
            final_path = os.path.join(target_dir, final_fn)
            os.replace(tmp_path, final_path)
            tmp_path = ''
            try:
                size = os.path.getsize(final_path)
            except Exception:
                size = total
            try:
                _prune_generated_dir(scope=normalized_scope, keep_paths=[final_path])
            except Exception:
                pass
            preview_info = _maybe_build_generated_image_preview(final_path, final_fn, normalized_scope, mime=effective_mime or _guess_content_type_for_file(final_fn), size_bytes=size)
            keep_paths = [final_path]
            if preview_info.get('path'):
                keep_paths.append(str(preview_info.get('path') or ''))
            try:
                _prune_generated_dir(scope=normalized_scope, keep_paths=keep_paths)
            except Exception:
                pass
            mirror_queued = _object_storage_mirror_file_async('generated', normalized_scope, final_fn, final_path, content_type=effective_mime or _guess_content_type_for_file(final_fn))
            view_url, download_url = _build_generated_file_urls(final_fn, normalized_scope)
            saved = {
                'filename': final_fn,
                'mime': effective_mime or _guess_content_type_for_file(final_fn),
                'size': size,
                'download_url': download_url,
                'view_url': view_url,
                'object_url': _object_storage_public_url('generated', normalized_scope, final_fn),
                'storage_backend': 'object+local' if mirror_queued else 'local',
                'scope': normalized_scope,
                'source_type': 'generated',
                'generated_by_assistant': True,
            }
            if preview_info:
                saved['preview_url'] = str(preview_info.get('view_url') or '').strip()
                saved['preview_download_url'] = str(preview_info.get('download_url') or '').strip()
                saved['preview_filename'] = str(preview_info.get('filename') or '').strip()
                saved['preview_size'] = int(preview_info.get('size') or 0)
                saved['preview_mime'] = str(preview_info.get('mime') or '').strip()
            _generated_artifact_register_saved_file(saved, final_path, source='generated')
            saved['provider_url'] = u
            saved['raw_url'] = str(view_url or download_url or u).strip()
            saved['delivery_mode'] = 'server_mirrored'
            saved['is_temporary_remote'] = False
            result.update(saved)
            result['ok'] = True
            result['error'] = ''
            result['elapsed_ms'] = int((time.time() - started) * 1000)
            result['download_ms'] = result['elapsed_ms']
            result['final_url'] = final_url
            result['status_code'] = status
            result['content_type'] = effective_mime
            result['content_length'] = int(result.get('content_length') or content_length or size or 0)
            result['final_host'] = final_host
            result['bytes_per_sec'] = round(float(size or total or 0) / max(0.001, result['elapsed_ms'] / 1000.0), 2)
            _image_generation_provider_mirror_status_update(
                u,
                status='ready',
                ready=True,
                filename=final_fn,
                view_url=view_url,
                preview_url=str((preview_info or {}).get('view_url') or ''),
                size=int(size or 0),
                bytes_downloaded=int(size or total or 0),
                content_length=int(result.get('content_length') or 0),
                download_ms=int(result['download_ms']),
                elapsed_ms=int(result['elapsed_ms']),
                first_byte_ms=int(result.get('first_byte_ms') or 0),
                header_ms=int(result.get('header_ms') or 0),
                bytes_per_sec=float(result.get('bytes_per_sec') or 0.0),
                download_mode=str(result.get('download_mode') or ('parallel_range' if result.get('parallel_download') else 'single_stream')),
                parallel_download=bool(result.get('parallel_download')),
                range_parts=int(result.get('range_parts') or 0),
                final_url=final_url,
                final_host=final_host,
                content_type=effective_mime,
                status_code=status,
            )
            _image_generation_log('mirror_stream_done', attempt=attempt, status=status, header_ms=result.get('header_ms'), first_byte_ms=result.get('first_byte_ms'), elapsed_ms=result['elapsed_ms'], bytes=size, bps=result['bytes_per_sec'], filename=final_fn, view_url=view_url, preview_url=str((preview_info or {}).get('view_url') or ''), scope=normalized_scope, url=u, final_url=final_url)
            return result
        except Exception as e:
            result['error'] = f'{type(e).__name__}: {e}'
            result['download_ms'] = int((time.time() - started) * 1000)
            _image_generation_provider_mirror_status_update(u, status='failed', ready=False, error=result['error'], download_ms=result['download_ms'])
            _image_generation_log('mirror_stream_exception', attempt=attempt, url=u, error=result['error'], elapsed_ms=result['download_ms'])
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
        finally:
            try:
                if resp is not None:
                    resp.close()
            except Exception:
                pass
        if attempt < attempts:
            time.sleep(min(1.5 * attempt, 3.0))
    return result


def _image_generation_provider_url_artifact(url: str, *, index: int = 1, ext: str = 'png', scope: str | None = None, content_type: str = '') -> dict:
    u = str(url or '').strip()
    normalized_scope = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    filename = _image_generation_filename_from_url(u, index=index, ext=ext)
    mime = str(content_type or '').strip().lower()
    if not mime.startswith('image/'):
        mime = _guess_content_type_for_file(filename) or f'image/{ext}'
    try:
        created_at_ms = int(time.time() * 1000)
    except Exception:
        created_at_ms = 0
    preview_proxy_url = _image_generation_provider_preview_proxy_url(u)
    return {
        'filename': filename,
        'mime': mime,
        'size': 0,
        'download_url': u,
        'view_url': u,
        'url': u,
        'file_url': u,
        'raw_url': u,
        'provider_url': u,
        'preview_url': preview_proxy_url,
        'proxy_url': preview_proxy_url,
        'preview_proxy_url': preview_proxy_url,
        'object_url': '',
        'storage_backend': 'provider_url',
        'scope': normalized_scope,
        'source_type': 'generated',
        'generated_by_assistant': True,
        'created_at_ms': created_at_ms,
        'mirror_status': 'pending',
        'delivery_mode': 'provider_url_first',
        'is_temporary_remote': True,
    }


def _image_generation_apply_mirrored_artifact(artifact: dict, saved: dict, provider_url: str) -> None:
    if not isinstance(artifact, dict) or not isinstance(saved, dict) or not saved:
        return
    saved = dict(saved)
    saved.pop('ok', None)
    saved.pop('error', None)
    saved.setdefault('created_at_ms', artifact.get('created_at_ms') or int(time.time() * 1000))
    saved.setdefault('source_role', artifact.get('source_role') or 'assistant')
    saved.setdefault('operation', artifact.get('operation') or 'generate')
    saved.setdefault('image_seq', artifact.get('image_seq') or 1)
    if artifact.get('parent_image_id'):
        saved.setdefault('parent_image_id', artifact.get('parent_image_id'))
    artifact.update(saved)
    artifact['provider_url'] = provider_url
    artifact['mirror_status'] = 'ready'
    artifact['delivery_mode'] = 'provider_url_first'
    artifact['is_temporary_remote'] = False
    artifact['raw_url'] = str(saved.get('view_url') or saved.get('download_url') or provider_url).strip()


def _mirror_provider_image_artifact_async(artifact: dict | None = None, *, auth_headers: dict | None = None) -> bool:
    if not isinstance(artifact, dict):
        return False
    provider_url = str(artifact.get('provider_url') or artifact.get('raw_url') or artifact.get('download_url') or artifact.get('view_url') or artifact.get('url') or '').strip()
    if not provider_url:
        return False
    if bool(artifact.get('_mirror_thread_started')):
        return False
    artifact['_mirror_thread_started'] = True
    artifact['mirror_status'] = 'running'
    try:
        artifact['mirror_started_at_ms'] = int(time.time() * 1000)
    except Exception:
        pass
    scope = str(artifact.get('scope') or '').strip() or _request_upload_scope()
    _image_generation_provider_mirror_status_update(
        provider_url,
        status='queued',
        ready=False,
        scope=scope,
        started_at_ms=int(time.time() * 1000),
    )
    filename = str(artifact.get('filename') or '').strip() or _image_generation_filename_from_url(provider_url, index=1, ext='png')
    mime_hint = str(artifact.get('mime') or '').strip().lower()

    def _runner():
        lock = _image_generation_provider_mirror_lock(provider_url)
        try:
            with lock:
                cached = _image_generation_provider_mirror_cached(provider_url)
                if cached:
                    _image_generation_apply_mirrored_artifact(artifact, cached, provider_url)
                    _image_generation_provider_mirror_status_update(provider_url, status='ready', ready=True, filename=str(cached.get('filename') or ''), view_url=str(cached.get('view_url') or ''), preview_url=str(cached.get('preview_url') or ''), size=int(cached.get('size') or 0))
                    _image_generation_log('mirror_cached', provider_url=provider_url, filename=str(cached.get('filename') or ''), view_url=str(cached.get('view_url') or ''), scope=scope)
                    return

                timeout_v = _image_generation_download_timeout_for_mirror()
                saved = _image_generation_stream_provider_url_to_scope(
                    provider_url,
                    filename=filename,
                    mime_hint=mime_hint,
                    scope=scope,
                    timeout=timeout_v,
                    headers=None,
                )
                if (not bool(saved.get('ok'))) and isinstance(auth_headers, dict) and auth_headers and not _image_generation_url_looks_signed(provider_url):
                    saved = _image_generation_stream_provider_url_to_scope(
                        provider_url,
                        filename=filename,
                        mime_hint=mime_hint,
                        scope=scope,
                        timeout=timeout_v,
                        headers=auth_headers,
                    )
                if bool(saved.get('ok')):
                    _image_generation_provider_mirror_remember(provider_url, saved)
                    _image_generation_apply_mirrored_artifact(artifact, saved, provider_url)
                    _image_generation_log('mirror_done', provider_url=provider_url, filename=str(saved.get('filename') or ''), view_url=str(saved.get('view_url') or ''), scope=scope)
                    return

                artifact['mirror_status'] = 'download_failed'
                artifact['mirror_error'] = str(saved.get('error') or 'download_failed')
                artifact['mirror_http_status'] = int(saved.get('status_code') or 0)
                _image_generation_provider_mirror_status_update(provider_url, status='failed', ready=False, error=artifact['mirror_error'], status_code=artifact['mirror_http_status'], download_ms=int(saved.get('download_ms') or saved.get('elapsed_ms') or 0), bytes_per_sec=float(saved.get('bytes_per_sec') or 0.0))
                _image_generation_log('mirror_failed', provider_url=provider_url, error=artifact['mirror_error'], status=artifact['mirror_http_status'], scope=scope)
        except Exception as e:
            artifact['mirror_status'] = 'error'
            artifact['mirror_error'] = f'{type(e).__name__}: {e}'
            _image_generation_provider_mirror_status_update(provider_url, status='failed', ready=False, error=artifact['mirror_error'])
            _image_generation_log('mirror_failed', provider_url=provider_url, error=artifact['mirror_error'], scope=scope)

    try:
        threading.Thread(target=_runner, name='image-provider-mirror', daemon=True).start()
        return True
    except Exception:
        artifact['mirror_status'] = 'thread_failed'
        return False


@app.get('/api3/image-generation/mirror-status')
def api3_image_generation_mirror_status():
    url = str(request.args.get('url') or request.args.get('provider_url') or '').strip()
    if not url:
        return jsonify({'ok': False, 'ready': False, 'error': 'missing_url'}), 400
    if not url.startswith(('http://', 'https://')):
        return jsonify({'ok': False, 'ready': False, 'error': 'unsupported_url_scheme'}), 400
    cached = _image_generation_provider_mirror_cached(url)
    status = _image_generation_provider_mirror_status_snapshot(url)
    if cached:
        artifact = _image_generation_provider_mirror_public_artifact(cached)
        return jsonify({
            'ok': True,
            'ready': True,
            'status': {**status, 'status': 'ready', 'ready': True},
            'artifact': artifact,
        })
    if isinstance(status, dict) and (bool(status.get('ready')) or str(status.get('status') or '').strip().lower() == 'ready'):
        artifact = _image_generation_provider_mirror_public_artifact(status)
        return jsonify({
            'ok': True,
            'ready': True,
            'status': {**status, 'status': 'ready', 'ready': True},
            'artifact': artifact,
        })
    return jsonify({
        'ok': True,
        'ready': False,
        'status': status or {
            'provider_url': url,
            'url_host': _image_generation_provider_url_host(url),
            'status': 'unknown',
            'ready': False,
        },
        'artifact': {},
    })
