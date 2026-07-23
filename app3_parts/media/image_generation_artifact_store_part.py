# Split from app3_parts/media/model_image_file_delivery_part.py.
# Purpose: generated image local/object storage registration helpers.
# Loaded by model_image_file_delivery_part.py via _exec_split_file(...), sharing the original global namespace.

def _image_generation_log(stage: str, **fields) -> None:
    try:
        parts = []
        for key, value in (fields or {}).items():
            if value is None:
                continue
            if isinstance(value, (dict, list, tuple)):
                try:
                    rendered = json.dumps(value, ensure_ascii=False)
                except Exception:
                    rendered = str(value)
            else:
                rendered = str(value)
            limit = 900 if key in {'body_preview', 'payload_preview'} else 260
            rendered = _image_generation_preview_text(rendered, limit=limit)
            if rendered == '':
                continue
            parts.append(f'{key}={rendered}')
        msg = ' '.join(parts)
        if msg:
            app_logger.info('[IMAGE_FETCH_TRACE] stage=%s %s', stage, msg)
        else:
            app_logger.info('[IMAGE_FETCH_TRACE] stage=%s', stage)
    except Exception:
        pass


def _image_generation_item_types(items: list[dict] | None = None) -> list[str]:
    out = []
    for item in list(items or [])[:8]:
        if not isinstance(item, dict):
            continue
        has_b64 = bool(str(item.get('b64') or '').strip())
        has_url = bool(str(item.get('url') or '').strip())
        if has_b64 and has_url:
            out.append('b64+url')
        elif has_b64:
            out.append('b64')
        elif has_url:
            out.append('url')
    return out


def _image_generation_url_looks_signed(url: str) -> bool:
    u = str(url or '').strip().lower()
    if not u:
        return False
    markers = (
        'x-tos-algorithm=', 'x-tos-signature=', 'x-amz-algorithm=', 'x-amz-signature=',
        'x-goog-algorithm=', 'x-goog-signature=', 'x-oss-signature=', 'signature=',
        'sig=', 'token=', 'expires=', 'x-tos-credential=', 'x-amz-credential=', 'x-goog-credential=',
    )
    return any(m in u for m in markers)


def _image_generation_download_headers_for_url(url: str, headers: dict | None = None) -> dict | None:
    out: dict[str, str] = {
        'Accept': 'image/*,*/*;q=0.8',
        'User-Agent': f'{APP_NAME}/image-fetch',
    }
    if isinstance(headers, dict) and not _image_generation_url_looks_signed(url):
        for key, value in headers.items():
            key_s = str(key or '').strip()
            value_s = str(value or '').strip()
            if not key_s or not value_s:
                continue
            if key_s.lower() == 'authorization':
                out[key_s] = value_s
    return out or None


def _download_image_generation_url(url: str, *, timeout: float = 45.0, headers: dict | None = None) -> dict:
    u = str(url or '').strip()
    result = {'ok': False, 'url': u, 'final_url': u, 'status_code': 0, 'content_type': '', 'bytes': b'', 'error': ''}
    if not u:
        result['error'] = 'empty_url'
        return result
    try:
        attempts = int(str(app_getenv('IMAGE_GENERATION_DOWNLOAD_RETRIES', '2') or '2'))
    except Exception:
        attempts = 2
    attempts = max(1, min(attempts, 4))
    timeout_v = max(3.0, min(float(timeout or 45.0), 120.0))
    req_headers = _image_generation_download_headers_for_url(u, headers)
    for attempt in range(1, attempts + 1):
        started = time.time()
        try:
            resp = requests.get(u, timeout=timeout_v, headers=req_headers, allow_redirects=True, stream=False)
            result['status_code'] = int(resp.status_code or 0)
            result['final_url'] = str(getattr(resp, 'url', u) or u)
            result['content_type'] = str(resp.headers.get('content-type') or '').split(';', 1)[0].strip().lower()
            body = resp.content or b''
            elapsed_ms = int((time.time() - started) * 1000)
            _image_generation_log('download_response', attempt=attempt, status=result['status_code'], elapsed_ms=elapsed_ms, content_type=result['content_type'], body_bytes=len(body), url=u, final_url=result['final_url'])
            if resp.ok and body:
                result['ok'] = True
                result['bytes'] = body
                result['error'] = ''
                return result
            result['error'] = f'http_{result["status_code"] or 0}'
        except Exception as e:
            result['error'] = f'{type(e).__name__}: {e}'
            _image_generation_log('download_exception', attempt=attempt, url=u, error=result['error'])
        if attempt < attempts:
            time.sleep(min(1.5 * attempt, 3.0))
    return result


def _image_generation_download_timeout_for_mirror() -> float:
    try:
        raw = app_getenv('IMAGE_GENERATION_MIRROR_DOWNLOAD_TIMEOUT_SECONDS', '25')
        return max(3.0, min(float(str(raw or '25').strip()), 90.0))
    except Exception:
        return 25.0


def _image_generation_current_output_scope() -> str:
    """Resolve where generated-image artifacts should be served from.

    Async chat jobs run outside the original Flask request context, so relying only
    on request.host can incorrectly fall back to the local scope for public/mobile
    traffic. Prefer the async-job public flag when present, then fall back to the
    current request scope.
    """
    try:
        current_job_id = globals().get('_chat_async_current_job_id')
        job_id = current_job_id() if callable(current_job_id) else ''
        if job_id:
            with _CHAT_ASYNC_JOB_LOCK:
                rec = _CHAT_ASYNC_JOBS.get(str(job_id or '').strip()) or {}
            if bool(rec.get('owner_is_public_request')):
                return UPLOAD_SCOPE_PUBLIC
    except Exception:
        pass
    try:
        return _request_upload_scope()
    except Exception:
        return UPLOAD_SCOPE_LOCAL


def _image_generation_should_sync_provider_mirror(scope: str | None = None) -> bool:
    normalized = _normalize_upload_scope(scope) if scope is not None else _image_generation_current_output_scope()
    if normalized != UPLOAD_SCOPE_PUBLIC:
        return False
    try:
        # 公网/手机端不要把最终图片响应卡在上游大图下载上。
        # 先返回临时图片消息，后台落地；前端通过 mirror-status 自动切到本地预览。
        return _cfg_bool('PUBLIC_IMAGE_GENERATION_SYNC_MIRROR', False)
    except Exception:
        return False


def _image_generation_provider_preview_proxy_url(provider_url: str) -> str:
    u = str(provider_url or '').strip()
    if not u or not u.startswith(('http://', 'https://')):
        return ''
    try:
        return '/api3/remote-image?preview=1&url=' + urllib.parse.quote(u, safe='')
    except Exception:
        return ''


def _image_generation_filename_from_url(url: str, *, index: int = 1, ext: str = 'png') -> str:
    fallback = _image_generation_filename(index, ext=ext)
    try:
        parsed = urllib.parse.urlparse(str(url or '').strip())
        name = os.path.basename(urllib.parse.unquote(parsed.path or ''))
    except Exception:
        name = ''
    safe = _safe_filename(name or '') if name else ''
    low = safe.lower()
    if not safe or not any(low.endswith(s) for s in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg')):
        return fallback
    return safe


def _save_generated_image_bytes_to_scope(raw: bytes, *, filename: str, mime: str, scope: str | None = None) -> dict:
    data = raw or b''
    if not data:
        return {}
    normalized_scope = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    upload_dir = _generated_dir_for_scope(normalized_scope, ensure=True)
    final_fn = _safe_filename(filename or '') or _image_generation_filename(1, ext='png')
    final_fn = _dedupe_filename(upload_dir, final_fn)
    ext = os.path.splitext(final_fn)[1].lower()
    if ext not in ALLOWED_EXT:
        return {}
    effective_mime = str(mime or _guess_content_type_for_file(final_fn) or '').strip() or 'application/octet-stream'
    persisted = _persist_scoped_file_bytes('generated', normalized_scope, final_fn, data, content_type=effective_mime, prune_func=_prune_generated_dir)
    if not bool(persisted.get('ok')):
        return {}
    out_path = str(persisted.get('path') or '').strip()
    size = 0
    try:
        size = os.path.getsize(out_path) if out_path and os.path.isfile(out_path) else len(data)
    except Exception:
        size = len(data)
    preview_info = _maybe_build_generated_image_preview(out_path, final_fn, normalized_scope, mime=effective_mime, size_bytes=size) if out_path else {}
    view_url, download_url = _build_generated_file_urls(final_fn, normalized_scope)
    item = {
        'filename': final_fn,
        'mime': effective_mime,
        'size': size,
        'download_url': download_url,
        'view_url': view_url,
        'object_url': _object_storage_public_url('generated', normalized_scope, final_fn),
        'storage_backend': 'object+local' if bool(persisted.get('mirror_queued')) else ('object' if bool(persisted.get('object_ok')) else 'local'),
        'scope': normalized_scope,
        'source_type': 'generated',
        'generated_by_assistant': True,
    }
    if preview_info:
        item['preview_url'] = str(preview_info.get('view_url') or '').strip()
        item['preview_download_url'] = str(preview_info.get('download_url') or '').strip()
        item['preview_filename'] = str(preview_info.get('filename') or '').strip()
        item['preview_size'] = int(preview_info.get('size') or 0)
        item['preview_mime'] = str(preview_info.get('mime') or '').strip()
    _generated_artifact_register_saved_file(item, out_path, source='generated')
    return item


def _generated_artifact_registry_owner_key() -> str:
    fn = globals().get('_storage_quota_owner_key')
    if callable(fn):
        try:
            return str(fn() or '').strip().lower()
        except Exception:
            pass
    return ''


def _generated_artifact_file_hash(path: str = '', *, fallback: str = '') -> str:
    fp = str(path or '').strip()
    try:
        if fp and os.path.isfile(fp):
            h = hashlib.sha256()
            with open(fp, 'rb') as rf:
                while True:
                    chunk = rf.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
    except Exception:
        pass
    try:
        return hashlib.sha256(str(fallback or fp or time.time()).encode('utf-8', errors='ignore')).hexdigest()
    except Exception:
        return ''


def _generated_artifact_sandbox_sources_from_rows(rows) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for src in (row.get('sandbox_source_files') or []):
            if not isinstance(src, dict):
                continue
            rel = str(src.get('path') or '').strip().replace('\\', '/')
            if not rel or rel.startswith('/') or '..' in rel.split('/'):
                continue
            sandbox_id = str(src.get('sandbox_id') or '').strip()
            root_rel = str(src.get('sandbox_root_rel') or '').strip().replace('\\', '/')
            mount = str(src.get('mount') or '/mnt/data').strip() or '/mnt/data'
            if root_rel and (root_rel.startswith('/') or '..' in root_rel.split('/')):
                continue
            key = f'{sandbox_id}|{mount}|{root_rel}|{rel}'.lower()
            if key in seen:
                continue
            seen.add(key)
            item = {
                'path': rel,
                'sandbox_id': sandbox_id,
                'mount': mount,
            }
            if root_rel:
                item['sandbox_root_rel'] = root_rel
            try:
                item['size'] = int(src.get('size') or 0)
            except Exception:
                item['size'] = 0
            out.append(item)
    return out


def _generated_artifact_copy_lineage_metadata(target: dict, row: dict | None = None) -> None:
    if not isinstance(target, dict) or not isinstance(row, dict):
        return
    audit = row.get('edit_audit') if isinstance(row.get('edit_audit'), dict) else row.get('file_edit_audit') if isinstance(row.get('file_edit_audit'), dict) else None
    if isinstance(audit, dict) and audit:
        target['edit_audit'] = dict(audit)
        target['file_edit_audit'] = dict(audit)
        target['source_role'] = 'edited_output'
        details = row.get('edit_details') if isinstance(row.get('edit_details'), dict) else {}
        target['edit_details'] = dict(details) if details else {'mode': 'sandbox', 'audit': dict(audit)}
        target['edited_from'] = {
            'basis_filename': str(audit.get('basis_filename') or '').strip(),
            'target_filename': str(audit.get('target_filename') or '').strip(),
            'output_filename': str(audit.get('output_filename') or '').strip(),
            'lineage_key': str(audit.get('lineage_key') or '').strip(),
            'audit_id': str(audit.get('audit_id') or '').strip(),
        }
    if isinstance(row.get('file_edit_audits'), list):
        audits = [dict(x) for x in (row.get('file_edit_audits') or []) if isinstance(x, dict)]
        if audits:
            target['file_edit_audits'] = audits[:200]
            target['source_role'] = 'edited_output'
            if not isinstance(target.get('edit_audit'), dict) and len(audits) == 1:
                target['edit_audit'] = dict(audits[0])
                target['file_edit_audit'] = dict(audits[0])
    sources = _generated_artifact_sandbox_sources_from_rows([row])
    if sources:
        target['sandbox_source_files'] = sources
        target['sandbox_cleanup_policy'] = str(row.get('sandbox_cleanup_policy') or 'delete_with_file_library').strip()
        target['sandbox_published'] = True


def _generated_artifact_register_saved_file(item: dict | None = None, path: str = '', *, source: str = 'generated') -> dict:
    row = dict(item or {}) if isinstance(item, dict) else {}
    final_path = str(path or '').strip()
    filename = os.path.basename(str(row.get('filename') or row.get('saved_filename') or final_path or '').strip())
    if not filename:
        return {}
    try:
        if final_path and not os.path.isfile(final_path):
            final_path = ''
        if not final_path:
            scope_hint = str(row.get('scope') or '').strip()
            resolver = globals().get('_resolve_generated_file_dir')
            base_dir = resolver(filename, scope=scope_hint) if callable(resolver) else ''
            if base_dir:
                candidate = os.path.join(str(base_dir), filename)
                if os.path.isfile(candidate):
                    final_path = candidate
    except Exception:
        final_path = ''

    scope = _normalize_upload_scope(row.get('scope') or (_request_upload_scope() if callable(globals().get('_request_upload_scope')) else UPLOAD_SCOPE_LOCAL))
    ext = str(row.get('ext') or _ext_of(filename) or '').strip().lower()
    try:
        size = int(row.get('size') or (os.path.getsize(final_path) if final_path and os.path.isfile(final_path) else 0) or 0)
    except Exception:
        size = int(row.get('size') or 0)
    if size <= 0:
        return {}

    owner_key = _generated_artifact_registry_owner_key()
    try:
        registrar = globals().get('_storage_quota_register_file')
        if callable(registrar) and final_path:
            registrar(owner_key=owner_key or None, namespace='generated', scope=scope, path=final_path, size_bytes=size, filename=filename)
    except Exception:
        pass

    view_url = str(row.get('view_url') or row.get('url') or '').strip()
    download_url = str(row.get('download_url') or row.get('url') or view_url).strip()
    content_hash = str(row.get('content_hash') or '').strip() or _generated_artifact_file_hash(final_path, fallback=f'generated|{scope}|{filename}|{size}')
    ts_now = time.time()
    rec = {}

    try:
        if callable(globals().get('_file_registry_is_code_like')) and _file_registry_is_code_like(filename, ext):
            registry_text = ''
            try:
                if final_path and os.path.isfile(final_path):
                    with open(final_path, 'rb') as rf:
                        registry_text = read_text_file(rf.read())
            except Exception:
                registry_text = ''
            if registry_text:
                rec = _file_registry_record_from_text(
                    namespace='generated',
                    scope=scope,
                    source=source or 'generated',
                    filename=filename,
                    saved_filename=filename,
                    text=registry_text,
                    size_bytes=size,
                    url=download_url or view_url,
                    view_url=view_url,
                    download_url=download_url or view_url,
                    content_hash=content_hash,
                )
    except Exception:
        rec = {}

    if not rec:
        h = content_hash or hashlib.sha256(f'generated|{scope}|{filename}|{size}'.encode('utf-8', errors='ignore')).hexdigest()
        fid_seed = f'generated|{scope}|{filename}|{h[:16]}'
        fid = hashlib.sha1(fid_seed.encode('utf-8', errors='ignore')).hexdigest()[:24]
        is_image = ext in (UPLOAD_IMAGE_EXTS or set()) or ext == '.svg'
        label = '生成图片' if is_image else '生成文件'
        rec = {
            'file_id': fid,
            'source': source or 'generated',
            'namespace': 'generated',
            'scope': scope,
            'filename': filename,
            'saved_filename': filename,
            'ext': ext,
            'size': size,
            'url': download_url or view_url,
            'view_url': view_url,
            'download_url': download_url or view_url,
            'storage_ref': '',
            'summary': str(row.get('summary') or f'{label}《{filename}》已保存，可在上传文件库管理。').strip()[:900],
            'symbols': [],
            'preview': '',
            'chunks': [],
            'is_code_like': False,
            'content_hash': h,
            'generated_by_assistant': True,
            'source_role': str(row.get('source_role') or 'assistant').strip(),
            'created_at': ts_now,
            'updated_at': ts_now,
        }
    _generated_artifact_copy_lineage_metadata(rec, row)
    preview_meta = {}
    for key in ('preview_filename', 'preview_url', 'preview_download_url', 'preview_size', 'preview_mime'):
        value = row.get(key)
        if value not in (None, ''):
            preview_meta[key] = value
    if preview_meta:
        rec.update(preview_meta)
        rec['has_generated_preview'] = True
    if owner_key:
        rec['owner_key'] = owner_key
    try:
        public = _file_registry_upsert(rec) if callable(globals().get('_file_registry_upsert')) else {}
        if public:
            row['file_registry'] = public
            if isinstance(item, dict):
                item['file_registry'] = public
                fid = str(public.get('file_id') or '').strip()
                if fid:
                    item['file_id'] = fid
                    item['registry_file_id'] = fid
                    item.setdefault('id', fid)
                    by_id = _generated_file_id_download_url(fid) if callable(globals().get('_generated_file_id_download_url')) else ''
                    view_by_id = _generated_file_id_view_url(fid) if callable(globals().get('_generated_file_id_view_url')) else ''
                    if by_id:
                        legacy = str(item.get('download_url') or item.get('url') or '').strip()
                        if legacy and legacy != by_id:
                            item.setdefault('legacy_download_url', legacy)
                        item['download_url'] = by_id
                        item['url'] = by_id
                        item['download_url_by_id'] = by_id
                    if view_by_id:
                        legacy_view = str(item.get('view_url') or '').strip()
                        if legacy_view and legacy_view != view_by_id:
                            item.setdefault('legacy_view_url', legacy_view)
                        item['view_url_by_id'] = view_by_id
                attach_meta = globals().get('_generated_file_attach_official_path_metadata')
                if callable(attach_meta):
                    try:
                        attach_meta(item)
                    except Exception:
                        pass
                if public.get('summary') and not item.get('code_summary'):
                    item['code_summary'] = public.get('summary') or ''
                if public.get('symbols') and not item.get('symbols'):
                    item['symbols'] = public.get('symbols') or []
            _image_generation_log('file_library_registered', filename=filename, scope=scope, owner=owner_key or '', file_id=str(public.get('file_id') or ''))
            return public
    except Exception:
        try:
            app_logger.exception('[file_registry] generated_register_failed filename=%s', filename)
        except Exception:
            pass
    return {}
