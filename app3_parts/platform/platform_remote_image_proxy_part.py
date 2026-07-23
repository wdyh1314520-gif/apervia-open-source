# Split from app3_parts/platform/platform_auth_part.py.
# Purpose: remote image import/proxy helpers, warm queue, and proxy routes.
# Loaded by app3.py via _exec_split_file(...), sharing the original global namespace.

def _remote_image_url_variants(url: str) -> list[str]:
    """Generate lightweight fallback variants for CDN-style transformed image URLs."""
    u = str(url or '').strip()
    if not u:
        return []
    variants: list[str] = [u]
    try:
        parsed = urlparse(u)
        host = (parsed.hostname or '').lower()
        # 抖音/字节系图片链接经常带签名；优先只试原链接，避免改坏参数。
        if not _is_douyin_image_host(host):
            base, sep, suffix = u.partition('@')
            if sep and base:
                variants.append(base)
                low_suffix = suffix.lower()
                if low_suffix.endswith('.webp'):
                    for ext in ('.jpg', '.jpeg', '.png'):
                        variants.append(base + ext)
            path = parsed.path or ''
            low_path = path.lower()
            if low_path.endswith('.webp'):
                for ext in ('.jpg', '.jpeg', '.png'):
                    alt_path = path[:-5] + ext
                    variants.append(urlunparse(parsed._replace(path=alt_path)))
    except Exception:
        pass
    out: list[str] = []
    seen = set()
    for item in variants:
        s = str(item or '').strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _import_remote_image_to_upload(url: str) -> dict:
    u = str(url or '').strip()
    if not u:
        raise ValueError('missing_url')
    parsed = urlparse(u)
    scheme = (parsed.scheme or '').lower()
    if scheme not in ('http', 'https'):
        raise ValueError('unsupported_url_scheme')
    host = (parsed.hostname or '').lower()
    if _is_gated_remote_image_host(host):
        raise ValueError('gated_remote_image_host')

    last_err = None
    for variant in _remote_image_url_variants(u):
        try:
            raw, mime = _download_remote_image(variant)
            ext = _guess_image_ext_from_url_and_type(variant, mime)
            if ext == '.img':
                ext = '.jpg' if str(mime).startswith('image/jpeg') else '.png'
            h = hashlib.sha256(raw).hexdigest()[:16]
            ts = int(time.time())
            save_name = f"{ts}_{h}{ext.lower()}"
            upload_scope = _request_upload_scope()
            save_path = os.path.join(_upload_dir_for_scope(upload_scope), save_name)
            persist_info = _persist_scoped_file_bytes(
                'uploads',
                upload_scope,
                save_name,
                raw,
                content_type=mime or _guess_content_type_for_file(save_name),
                prune_func=_prune_upload_dir,
            )
            if not persist_info.get('ok'):
                raise ValueError('remote_image_import_failed')
            save_path = str(persist_info.get('path') or save_path)
            view_url, download_url = _build_uploaded_file_urls(save_name, upload_scope)
            inline_data_url = ''
            if _should_inline_uploaded_image_data(upload_scope, has_saved_file=bool(save_name and view_url)):
                inline_data_url = f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
            ocr_text = _ocr_image_bytes(raw)
            preview_url = view_url or download_url or inline_data_url
            return {
                'filename': os.path.basename(urlparse(variant).path) or save_name,
                'kind': 'image',
                'mime': mime,
                'url': view_url,
                'view_url': view_url,
                'download_url': download_url,
                'preview_url': preview_url,
                'storage_ref': _build_upload_storage_ref(save_name, upload_scope),
                'model_storage_ref': _build_upload_storage_ref(save_name, upload_scope),
                'object_url': _object_storage_public_url('uploads', upload_scope, save_name),
                'storage_backend': 'object+local' if (persist_info.get('mirror_queued') or persist_info.get('object_ok')) else ('local' if persist_info.get('local_ok') else ''),
                'data_url': inline_data_url,
                'text': truncate_text(ocr_text, max_chars=20000) if ocr_text else '',
                'source_url': variant,
            }
        except Exception as e:
            last_err = e
            continue
    if last_err is not None:
        raise last_err
    raise ValueError('remote_image_import_failed')


def _remote_image_proxy_preview_response_bytes(raw: bytes, mime: str = '') -> tuple[bytes, str]:
    data = raw or b''
    low_mime = str(mime or '').split(';', 1)[0].strip().lower()
    if not data or not low_mime.startswith('image/'):
        return data, mime or 'application/octet-stream'
    if low_mime in {'image/svg+xml', 'image/gif'}:
        return data, low_mime
    try:
        max_side = max(480, min(int(str(app_getenv('REMOTE_IMAGE_PROXY_PREVIEW_MAX_SIDE', '1536') or '1536')), 4096))
    except Exception:
        max_side = 1536
    try:
        trigger_bytes = max(128 * 1024, int(str(app_getenv('REMOTE_IMAGE_PROXY_PREVIEW_TRIGGER_BYTES', '900000') or '900000')))
    except Exception:
        trigger_bytes = 900000
    try:
        quality = max(45, min(int(str(app_getenv('REMOTE_IMAGE_PROXY_PREVIEW_QUALITY', '82') or '82')), 94))
    except Exception:
        quality = 82
    try:
        from PIL import Image, ImageOps  # type: ignore
        with Image.open(io.BytesIO(data)) as opened:
            try:
                if getattr(opened, 'is_animated', False):
                    opened.seek(0)
            except Exception:
                pass
            img = ImageOps.exif_transpose(opened)
            try:
                img.load()
            except Exception:
                pass
            width, height = img.size
            if len(data) <= trigger_bytes and max(width, height) <= max_side:
                return data, low_mime
            preview = img.copy()
            preview.thumbnail((max_side, max_side), Image.LANCZOS)
            if preview.mode not in ('RGB', 'L'):
                bg = Image.new('RGB', preview.size, (255, 255, 255))
                alpha = preview.getchannel('A') if 'A' in preview.getbands() else None
                bg.paste(preview.convert('RGBA'), mask=alpha)
                preview = bg
            elif preview.mode != 'RGB':
                preview = preview.convert('RGB')
            buf = io.BytesIO()
            preview.save(buf, format='JPEG', quality=quality, optimize=True)
            out = buf.getvalue()
            return (out or data), 'image/jpeg' if out else low_mime
    except Exception as e:
        try:
            app_logger.warning('[remote_image_proxy_preview] failed mime=%s bytes=%s err=%s', low_mime, len(data), e)
        except Exception:
            pass
        return data, low_mime


# ==============================
# Public remote image warm queue (non-blocking proxy)
# ==============================
_REMOTE_IMAGE_PROXY_JOB_LOCK = threading.Lock()
_REMOTE_IMAGE_PROXY_JOBS: dict[str, dict] = {}
_REMOTE_IMAGE_PROXY_ACTIVE = 0
_REMOTE_IMAGE_PROXY_TERMINAL_STATES = {'ready', 'failed_final'}
_REMOTE_IMAGE_PROXY_WORKING_STATES = {'queued', 'fetching'}


def _remote_image_proxy_now_ms() -> int:
    try:
        return int(time.time() * 1000)
    except Exception:
        return 0


def _remote_image_proxy_max_attempts() -> int:
    try:
        return max(1, min(int(str(app_getenv('REMOTE_IMAGE_PROXY_MAX_ATTEMPTS', '5') or '5')), 12))
    except Exception:
        return 5


def _remote_image_proxy_retry_delay_ms(attempts: int = 1) -> int:
    try:
        base = max(2000, int(str(app_getenv('REMOTE_IMAGE_PROXY_RETRY_BASE_MS', '6000') or '6000')))
    except Exception:
        base = 6000
    try:
        cap = max(base, int(str(app_getenv('REMOTE_IMAGE_PROXY_RETRY_MAX_MS', '180000') or '180000')))
    except Exception:
        cap = 180000
    try:
        n = max(1, int(attempts or 1))
    except Exception:
        n = 1
    return int(min(cap, base * (2 ** max(0, n - 1))))


def _remote_image_proxy_normalize_state(value: str = '', *, ready: bool = False, attempts: int = 0) -> str:
    raw = str(value or '').strip().lower()
    if ready:
        return 'ready'
    aliases = {
        'running': 'fetching',
        'downloading': 'fetching',
        'checking_cache': 'fetching',
        'done': 'ready',
        'completed': 'ready',
        'failed': 'failed_retryable',
        'error': 'failed_retryable',
    }
    raw = aliases.get(raw, raw)
    if raw not in {'queued', 'fetching', 'ready', 'failed_retryable', 'failed_final'}:
        raw = 'queued'
    if raw == 'failed_retryable' and attempts >= _remote_image_proxy_max_attempts():
        return 'failed_final'
    return raw


def _remote_image_proxy_public_status(rec: dict | None = None) -> dict:
    obj = dict(rec or {})
    try:
        attempts = int(obj.get('attempts') or obj.get('attempt') or 0)
    except Exception:
        attempts = 0
    state = _remote_image_proxy_normalize_state(obj.get('status') or obj.get('state') or '', ready=bool(obj.get('ready')), attempts=attempts)
    now_ms = _remote_image_proxy_now_ms()
    retry_after_ms = 0
    try:
        retry_at = int(float(obj.get('retry_after_ms') or 0))
        if retry_at > now_ms:
            retry_after_ms = max(0, retry_at - now_ms)
    except Exception:
        retry_after_ms = 0
    if state in {'queued', 'fetching'} and retry_after_ms <= 0:
        retry_after_ms = 2500 if state == 'queued' else 1800
    out = dict(obj)
    out['status'] = state
    out['state'] = state
    out['ready'] = bool(state == 'ready' or obj.get('ready'))
    out['retryable'] = bool(state in {'queued', 'fetching', 'failed_retryable'})
    out['terminal'] = bool(state in _REMOTE_IMAGE_PROXY_TERMINAL_STATES)
    out['attempts'] = attempts
    out['max_attempts'] = _remote_image_proxy_max_attempts()
    out['retry_after_ms'] = retry_after_ms
    out['retry_after_s'] = max(1, int(math.ceil(retry_after_ms / 1000.0))) if retry_after_ms > 0 else 0
    return out


def _remote_image_proxy_job_key(url: str = '') -> str:
    return hashlib.sha1(str(url or '').strip().encode('utf-8', 'ignore')).hexdigest()


def _remote_image_proxy_public_url(url: str = '', *, preview: bool = True, cache_bust: str = '') -> str:
    u = str(url or '').strip()
    if not u:
        return ''
    qs = 'url=' + urllib.parse.quote(u, safe='')
    if preview:
        qs = 'preview=1&' + qs
    if cache_bust:
        qs += '&v=' + urllib.parse.quote(str(cache_bust), safe='')
    return '/api3/remote-image?' + qs


def _remote_image_proxy_cached_variant(url: str = '') -> tuple[bytes, str, str] | None:
    for variant in _remote_image_url_variants(url):
        try:
            cached = _read_remote_image_cache(variant)
        except Exception:
            cached = None
        if cached:
            raw, mime = cached
            return raw, mime, variant
    return None


def _remote_image_proxy_job_snapshot(url: str = '') -> dict:
    u = str(url or '').strip()
    key = _remote_image_proxy_job_key(u)
    with _REMOTE_IMAGE_PROXY_JOB_LOCK:
        return dict(_REMOTE_IMAGE_PROXY_JOBS.get(key) or {})


def _remote_image_proxy_job_update(url: str = '', **fields) -> dict:
    u = str(url or '').strip()
    if not u:
        return {}
    key = _remote_image_proxy_job_key(u)
    now_ms = _remote_image_proxy_now_ms()
    with _REMOTE_IMAGE_PROXY_JOB_LOCK:
        if len(_REMOTE_IMAGE_PROXY_JOBS) > 1024:
            rows = sorted(
                _REMOTE_IMAGE_PROXY_JOBS.items(),
                key=lambda kv: float((kv[1] or {}).get('updated_at_ms') or 0.0),
            )
            for old_key, _old in rows[:256]:
                _REMOTE_IMAGE_PROXY_JOBS.pop(old_key, None)
        rec = dict(_REMOTE_IMAGE_PROXY_JOBS.get(key) or {})
        rec.setdefault('url', u)
        rec.setdefault('job_id', key[:16])
        rec.setdefault('created_at_ms', now_ms)
        try:
            rec.setdefault('url_host', str(urlparse(u).hostname or '').strip().lower())
        except Exception:
            rec.setdefault('url_host', '')
        rec['updated_at_ms'] = now_ms
        for k, v in (fields or {}).items():
            if v is None:
                continue
            rec[str(k)] = v
        try:
            attempts = int(rec.get('attempts') or rec.get('attempt') or 0)
        except Exception:
            attempts = 0
        rec['attempts'] = attempts
        rec['status'] = _remote_image_proxy_normalize_state(rec.get('status') or rec.get('state') or '', ready=bool(rec.get('ready')), attempts=attempts)
        rec['state'] = rec['status']
        _REMOTE_IMAGE_PROXY_JOBS[key] = rec
        return _remote_image_proxy_public_status(rec)


def _remote_image_proxy_artifact_for_url(url: str = '', *, variant: str = '', mime: str = '', size: int = 0) -> dict:
    u = str(url or '').strip()
    if not u:
        return {}
    cache_bust = str(int(time.time() * 1000))
    return {
        'url': _remote_image_proxy_public_url(u, preview=True, cache_bust=cache_bust),
        'preview_url': _remote_image_proxy_public_url(u, preview=True, cache_bust=cache_bust),
        'view_url': _remote_image_proxy_public_url(u, preview=False, cache_bust=cache_bust),
        'download_url': _remote_image_proxy_public_url(u, preview=False, cache_bust=cache_bust),
        'raw_url': _remote_image_proxy_public_url(u, preview=False, cache_bust=cache_bust),
        'source_url': u,
        'mirrored_source_url': str(variant or u),
        'mime': str(mime or '').strip(),
        'size': int(size or 0),
        'source_type': 'remote_image',
        'mirror_status': 'ready',
        'delivery_mode': 'remote_image_proxy_cache',
        'is_temporary_remote': False,
    }


def _remote_image_proxy_placeholder_response(status_text: str = 'queued'):
    label = str(status_text or 'queued').strip()[:80]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="8" fill="transparent"/>'
        '</svg>'
    ).encode('utf-8')
    resp = Response(svg, status=200, content_type='image/svg+xml; charset=utf-8')
    resp.headers['Cache-Control'] = 'no-store, max-age=0'
    resp.headers['X-WebAI-Remote-Image-Queued'] = '1'
    resp.headers['X-WebAI-Remote-Image-Status'] = label
    resp.headers['Retry-After'] = '3'
    return resp


def _remote_image_proxy_background_limit() -> int:
    try:
        return max(1, min(int(str(app_getenv('REMOTE_IMAGE_PROXY_BACKGROUND_WORKERS', '4') or '4')), 12))
    except Exception:
        return 4


def _remote_image_proxy_schedule_warm(url: str = '', *, reason: str = '', force_retry: bool = False) -> dict:
    u = str(url or '').strip()
    if not u or not u.startswith(('http://', 'https://')):
        return {}
    cached = _remote_image_proxy_cached_variant(u)
    if cached:
        raw, mime, variant = cached
        return _remote_image_proxy_job_update(
            u,
            status='ready',
            state='ready',
            phase='cache_hit',
            ready=True,
            cached=True,
            size=len(raw or b''),
            mime=mime,
            variant=variant,
            artifact=_remote_image_proxy_artifact_for_url(u, variant=variant, mime=mime, size=len(raw or b'')),
        )

    key = _remote_image_proxy_job_key(u)
    now_ms = _remote_image_proxy_now_ms()
    max_attempts = _remote_image_proxy_max_attempts()
    with _REMOTE_IMAGE_PROXY_JOB_LOCK:
        rec = dict(_REMOTE_IMAGE_PROXY_JOBS.get(key) or {})
        try:
            attempts = int(rec.get('attempts') or rec.get('attempt') or 0)
        except Exception:
            attempts = 0
        state = _remote_image_proxy_normalize_state(rec.get('status') or rec.get('state') or '', ready=bool(rec.get('ready')), attempts=attempts)

        if state in {'queued', 'fetching'} and not force_retry:
            return _remote_image_proxy_public_status(rec)

        retry_at = 0
        try:
            retry_at = int(float(rec.get('retry_after_ms') or 0))
        except Exception:
            retry_at = 0
        if state == 'failed_final' and not force_retry:
            return _remote_image_proxy_public_status(rec)
        if state == 'failed_retryable' and retry_at > now_ms and not force_retry:
            return _remote_image_proxy_public_status(rec)
        if force_retry and state in {'failed_retryable', 'failed_final'}:
            attempts = 0
            rec['attempts'] = 0
            rec['retry_after_ms'] = 0
            rec['error'] = ''

        global _REMOTE_IMAGE_PROXY_ACTIVE
        if _REMOTE_IMAGE_PROXY_ACTIVE >= _remote_image_proxy_background_limit():
            rec.update({
                'url': u,
                'job_id': key[:16],
                'status': 'queued',
                'state': 'queued',
                'phase': 'waiting_for_worker',
                'ready': False,
                'queued_reason': 'worker_limit',
                'reason': reason or 'status_probe',
                'retry_after_ms': now_ms + 3000,
                'updated_at_ms': now_ms,
            })
            _REMOTE_IMAGE_PROXY_JOBS[key] = rec
            return _remote_image_proxy_public_status(rec)

        _REMOTE_IMAGE_PROXY_ACTIVE += 1
        attempts += 1
        rec.update({
            'url': u,
            'job_id': key[:16],
            'status': 'queued',
            'state': 'queued',
            'phase': 'queued',
            'ready': False,
            'reason': reason or 'status_probe',
            'attempts': attempts,
            'max_attempts': max_attempts,
            'queued_at_ms': now_ms,
            'updated_at_ms': now_ms,
            'retry_after_ms': now_ms + 1500,
        })
        _REMOTE_IMAGE_PROXY_JOBS[key] = rec

    def _runner():
        global _REMOTE_IMAGE_PROXY_ACTIVE
        last_error = ''
        started_ms = _remote_image_proxy_now_ms()
        attempts_done = 1
        try:
            snap = _remote_image_proxy_job_update(u, status='fetching', state='fetching', phase='starting', ready=False, started_at_ms=started_ms)
            try:
                attempts_done = int((snap or {}).get('attempts') or 1)
            except Exception:
                attempts_done = 1
            for variant in _remote_image_url_variants(u):
                try:
                    _remote_image_proxy_job_update(u, status='fetching', state='fetching', phase='downloading', ready=False, variant=variant)
                    data_url = _remote_image_to_data_url(variant)
                    cached2 = _remote_image_proxy_cached_variant(u)
                    if cached2:
                        raw, mime, cached_variant = cached2
                        artifact = _remote_image_proxy_artifact_for_url(u, variant=cached_variant, mime=mime, size=len(raw or b''))
                        return _remote_image_proxy_job_update(
                            u,
                            status='ready',
                            state='ready',
                            phase='ready',
                            ready=True,
                            cached=True,
                            variant=cached_variant,
                            mime=mime,
                            size=len(raw or b''),
                            artifact=artifact,
                            retry_after_ms=0,
                            elapsed_ms=max(0, _remote_image_proxy_now_ms() - started_ms),
                        )
                    if data_url:
                        _remote_image_proxy_job_update(u, status='fetching', state='fetching', phase='checking_cache', ready=False, variant=variant)
                except Exception as e:
                    last_error = f'{type(e).__name__}: {e}'
                    try:
                        app_logger.warning('[remote_image_proxy_queue] warm_failed url=%s variant=%s attempt=%s/%s err=%s', u, variant, attempts_done, max_attempts, last_error)
                    except Exception:
                        pass
                    continue
            now2 = _remote_image_proxy_now_ms()
            final = attempts_done >= max_attempts
            retry_delay = 0 if final else _remote_image_proxy_retry_delay_ms(attempts_done)
            return _remote_image_proxy_job_update(
                u,
                status='failed_final' if final else 'failed_retryable',
                state='failed_final' if final else 'failed_retryable',
                phase='failed',
                ready=False,
                retryable=(not final),
                error=last_error or 'remote_image_warm_failed',
                failed_at=now2,
                retry_after_ms=0 if final else now2 + retry_delay,
                elapsed_ms=max(0, now2 - started_ms),
            )
        finally:
            with _REMOTE_IMAGE_PROXY_JOB_LOCK:
                _REMOTE_IMAGE_PROXY_ACTIVE = max(0, _REMOTE_IMAGE_PROXY_ACTIVE - 1)

    try:
        threading.Thread(target=_runner, name='remote-image-warm', daemon=True).start()
    except Exception as e:
        with _REMOTE_IMAGE_PROXY_JOB_LOCK:
            _REMOTE_IMAGE_PROXY_ACTIVE = max(0, _REMOTE_IMAGE_PROXY_ACTIVE - 1)
        now3 = _remote_image_proxy_now_ms()
        return _remote_image_proxy_job_update(u, status='failed_retryable', state='failed_retryable', phase='thread_start_failed', ready=False, error=f'thread_start_failed:{type(e).__name__}', retry_after_ms=now3 + 15000)
    return _remote_image_proxy_job_snapshot(u)


@app.get('/api3/remote-image/status')
def api3_remote_image_proxy_status():
    url = str(request.args.get('url') or '').strip()
    if not url:
        return jsonify({'ok': False, 'ready': False, 'error': 'missing_url'}), 400
    if not url.startswith(('http://', 'https://')):
        return jsonify({'ok': False, 'ready': False, 'error': 'unsupported_url_scheme'}), 400
    cached = _remote_image_proxy_cached_variant(url)
    if cached:
        raw, mime, variant = cached
        artifact = _remote_image_proxy_artifact_for_url(url, variant=variant, mime=mime, size=len(raw or b''))
        status = _remote_image_proxy_job_update(url, status='ready', state='ready', phase='cache_hit', ready=True, cached=True, variant=variant, mime=mime, size=len(raw or b''), artifact=artifact, retry_after_ms=0)
        return jsonify({'ok': True, 'ready': True, 'state': 'ready', 'status': status, 'artifact': artifact, 'retryable': False, 'terminal': True})
    force_retry = str(request.args.get('retry') or request.args.get('force') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    status = _remote_image_proxy_schedule_warm(url, reason='status', force_retry=force_retry) or _remote_image_proxy_job_snapshot(url)
    status = _remote_image_proxy_public_status(status or {'url': url, 'status': 'queued', 'ready': False})
    return jsonify({
        'ok': True,
        'ready': bool(status.get('ready')),
        'state': str(status.get('state') or status.get('status') or 'queued'),
        'status': status,
        'artifact': status.get('artifact') or {},
        'retryable': bool(status.get('retryable')),
        'terminal': bool(status.get('terminal')),
        'retry_after_ms': int(status.get('retry_after_ms') or 0),
        'retry_after_s': int(status.get('retry_after_s') or 0),
    })


@app.post('/api3/remote-image/retry')
def api3_remote_image_proxy_retry():
    payload = request.get_json(force=True, silent=True) or {}
    url = str(payload.get('url') or request.args.get('url') or '').strip()
    if not url:
        return jsonify({'ok': False, 'ready': False, 'error': 'missing_url'}), 400
    if not url.startswith(('http://', 'https://')):
        return jsonify({'ok': False, 'ready': False, 'error': 'unsupported_url_scheme'}), 400
    status = _remote_image_proxy_schedule_warm(url, reason='manual_retry', force_retry=True) or _remote_image_proxy_job_snapshot(url)
    status = _remote_image_proxy_public_status(status or {'url': url, 'status': 'queued', 'ready': False})
    return jsonify({'ok': True, 'ready': bool(status.get('ready')), 'state': str(status.get('state') or status.get('status') or 'queued'), 'status': status, 'artifact': status.get('artifact') or {}, 'retryable': bool(status.get('retryable'))})


@app.get("/api3/remote-image")
@app.get("/api3/image_proxy")
def api3_image_proxy():
    url = str(request.args.get("url") or "").strip()
    if not url:
        return Response("missing url", status=400, content_type="text/plain; charset=utf-8")

    preview_mode = str(request.args.get('preview') or request.args.get('thumb') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    force_sync = str(request.args.get('wait') or request.args.get('sync') or request.args.get('force') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    public_scope = _is_public_request_scope()
    started = time.time()
    last_error = ''
    try:
        cached = _remote_image_proxy_cached_variant(url)
        if cached:
            raw, mime, variant = cached
            before_preview_bytes = len(raw or b'')
            if preview_mode:
                raw, mime = _remote_image_proxy_preview_response_bytes(raw, mime)
            elapsed_ms = int((time.time() - started) * 1000)
            _remote_image_proxy_job_update(
                url,
                status='ready',
                ready=True,
                cached=True,
                variant=variant,
                mime=mime,
                size=before_preview_bytes,
                artifact=_remote_image_proxy_artifact_for_url(url, variant=variant, mime=mime, size=before_preview_bytes),
            )
            resp = Response(raw, content_type=mime or 'application/octet-stream')
            resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
            resp.headers["X-WebAI-Image-Proxy"] = "preview-cache" if preview_mode else "full-cache"
            resp.headers["X-WebAI-Remote-Image-Elapsed-Ms"] = str(elapsed_ms)
            resp.headers["X-WebAI-Remote-Image-Bytes"] = str(before_preview_bytes)
            resp.headers["X-WebAI-Remote-Image-Output-Bytes"] = str(len(raw or b''))
            return resp

        # Public traffic should not spend the image tag request doing a full remote
        # download. Queue the warm job and return a tiny image response so the UI
        # can keep its placeholder instead of surfacing a browser load-failed state.
        if public_scope and not force_sync:
            status = _remote_image_proxy_schedule_warm(url, reason='proxy_request') or {}
            state = str(status.get('status') or 'queued')
            try:
                app_logger.info('[remote_image_proxy] queued public preview=%s url=%s status=%s', preview_mode, url, state)
            except Exception:
                pass
            return _remote_image_proxy_placeholder_response(state)

        for variant in _remote_image_url_variants(url):
            variant_started = time.time()
            try:
                data_url = _remote_image_to_data_url(variant)
            except Exception as e:
                last_error = f'{type(e).__name__}: {e}'
                try:
                    app_logger.warning('[remote_image_proxy] download_failed preview=%s elapsed_ms=%s url=%s variant=%s err=%s', preview_mode, int((time.time() - variant_started) * 1000), url, variant, last_error)
                except Exception:
                    pass
                continue
            if not data_url or not data_url.startswith("data:") or "," not in data_url:
                last_error = 'empty_data_url'
                continue
            header, b64 = data_url.split(",", 1)
            mime = header.split(";", 1)[0].replace("data:", "").strip() or "application/octet-stream"
            raw = base64.b64decode(b64)
            raw_bytes = len(raw or b'')
            before_preview_bytes = raw_bytes
            if preview_mode:
                raw, mime = _remote_image_proxy_preview_response_bytes(raw, mime)
            elapsed_ms = int((time.time() - started) * 1000)
            _remote_image_proxy_job_update(
                url,
                status='ready',
                ready=True,
                cached=True,
                variant=variant,
                mime=mime,
                size=before_preview_bytes,
                artifact=_remote_image_proxy_artifact_for_url(url, variant=variant, mime=mime, size=before_preview_bytes),
            )
            resp = Response(raw, content_type=mime)
            resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
            resp.headers["X-WebAI-Image-Proxy"] = "preview" if preview_mode else "full"
            resp.headers["X-WebAI-Remote-Image-Elapsed-Ms"] = str(elapsed_ms)
            resp.headers["X-WebAI-Remote-Image-Bytes"] = str(before_preview_bytes)
            resp.headers["X-WebAI-Remote-Image-Output-Bytes"] = str(len(raw or b''))
            try:
                app_logger.info('[remote_image_proxy] ok preview=%s elapsed_ms=%s bytes=%s out_bytes=%s mime=%s url=%s variant=%s', preview_mode, elapsed_ms, before_preview_bytes, len(raw or b''), mime, url, variant)
            except Exception:
                pass
            return resp
        try:
            app_logger.warning('[remote_image_proxy] failed preview=%s elapsed_ms=%s url=%s err=%s', preview_mode, int((time.time() - started) * 1000), url, last_error)
        except Exception:
            pass
        _remote_image_proxy_job_update(url, status='failed', ready=False, error=last_error or 'image proxy failed', failed_at=int(time.time() * 1000), retry_after_ms=int(time.time() * 1000) + 90000)
        return Response("image proxy failed", status=502, content_type="text/plain; charset=utf-8")
    except Exception:
        app_logger.exception("image proxy failed: %s", url)
        _remote_image_proxy_job_update(url, status='failed', ready=False, error='image proxy exception', failed_at=int(time.time() * 1000), retry_after_ms=int(time.time() * 1000) + 90000)
        return Response("image proxy failed", status=502, content_type="text/plain; charset=utf-8")
