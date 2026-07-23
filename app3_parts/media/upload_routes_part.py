# Split from app3_parts/media/async_pullback_upload_server_part.py.
# Purpose: upload parsing, file registry registration, chunk upload, and upload routes.
# Loaded by async_pullback_upload_server_part.py via _exec_split_file(...), sharing the original global namespace.

class _UploadFileView:
    def __init__(self, filename: str = '', mimetype: str = ''):
        self.filename = str(filename or '').strip()
        self.mimetype = str(mimetype or '').strip()


def _upload_form_snapshot(src=None) -> dict:
    out = {}
    try:
        keys = list((src or {}).keys())
    except Exception:
        keys = []
    for key in keys:
        try:
            value = (src or {}).get(key)
        except Exception:
            value = ''
        out[str(key)] = str(value or '')
    return out




def _upload_file_registry_owner_key() -> str:
    for name in ('_file_library_owner_key', '_storage_quota_owner_key'):
        fn = globals().get(name)
        if callable(fn):
            try:
                key = str(fn() or '').strip().lower()
                if key:
                    return key
            except Exception:
                pass
    try:
        fn = globals().get('_current_login_email')
        normalizer = globals().get('_normalize_login_email')
        if callable(fn):
            raw = str(fn() or '').strip()
            if raw:
                return str(normalizer(raw) if callable(normalizer) else raw).strip().lower()
    except Exception:
        pass
    return ''


def _upload_limit_mb(name: str, default: int, *, minimum: int = 1, maximum: int = 2048) -> int:
    try:
        value = int(str(app_getenv(name, str(default)) or default).strip() or default)
    except Exception:
        value = int(default)
    return max(int(minimum), min(int(maximum), value))


def _upload_human_bytes(num: int | float) -> str:
    try:
        n = float(num or 0)
    except Exception:
        n = 0.0
    units = ['B', 'KB', 'MB', 'GB']
    idx = 0
    while n >= 1024 and idx < len(units) - 1:
        n /= 1024.0
        idx += 1
    if idx == 0:
        return f'{int(n)}{units[idx]}'
    return f'{n:.1f}{units[idx]}'


def _upload_max_bytes_for_request(ext: str = '', form: dict | None = None) -> tuple[int, str]:
    ext_l = str(ext or '').strip().lower()
    form = form or {}
    if ext_l in UPLOAD_IMAGE_EXTS:
        return _upload_limit_mb('UPLOAD_IMAGE_MAX_MB', 8, minimum=1, maximum=128) * 1024 * 1024, '图片'
    kb_import = str((form or {}).get('kb_import') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    if kb_import:
        return _upload_limit_mb('KB_UPLOAD_FILE_MAX_MB', 80, minimum=1, maximum=1024) * 1024 * 1024, '知识库文件'
    return _upload_limit_mb('UPLOAD_FILE_MAX_MB', 30, minimum=1, maximum=1024) * 1024 * 1024, '文件'


def _upload_size_error_payload(ext: str = '', form: dict | None = None) -> dict:
    max_bytes, label = _upload_max_bytes_for_request(ext, form=form)
    return {
        'max_bytes': int(max_bytes),
        'max_text': _upload_human_bytes(max_bytes),
        'label': label,
        'error': f'{label}过大，最大支持 {_upload_human_bytes(max_bytes)}',
    }


def _upload_register_saved_file(*, upload_scope: str = '', source: str = 'upload', filename: str = '', saved_filename: str = '', ext: str = '', size_bytes: int = 0, url: str = '', view_url: str = '', download_url: str = '', storage_ref: str = '', content_hash: str = '', text: str = '', summary: str = '') -> dict:
    try:
        owner_key = _upload_file_registry_owner_key()
        raw_text = str(text or '')
        if raw_text.strip():
            rec = _file_registry_record_from_text(
                namespace='uploads',
                scope=upload_scope,
                source=source or 'upload',
                filename=str(filename or saved_filename or ''),
                saved_filename=str(saved_filename or filename or ''),
                text=raw_text,
                size_bytes=int(size_bytes or 0),
                url=url,
                view_url=view_url,
                download_url=download_url,
                storage_ref=storage_ref,
                content_hash=content_hash,
            )
        else:
            fn = str(filename or saved_filename or '').strip()
            saved = str(saved_filename or fn).strip()
            ext_l = str(ext or _ext_of(fn) or _ext_of(saved) or '').strip().lower()
            h = str(content_hash or '').strip() or hashlib.sha256(f'{upload_scope}|{saved}|{int(size_bytes or 0)}'.encode('utf-8', errors='ignore')).hexdigest()[:16]
            fid_seed = f'uploads|{_normalize_upload_scope(upload_scope)}|{saved or fn}|{h[:16]}'
            fid = hashlib.sha1(fid_seed.encode('utf-8', errors='ignore')).hexdigest()[:24]
            ts_now = time.time()
            src_label = '用户上传文件'
            rec = {
                'file_id': fid,
                'source': source or 'upload',
                'namespace': 'uploads',
                'scope': _normalize_upload_scope(upload_scope),
                'filename': fn,
                'saved_filename': saved,
                'ext': ext_l,
                'size': int(size_bytes or 0),
                'url': str(url or '').strip(),
                'view_url': str(view_url or '').strip(),
                'download_url': str(download_url or '').strip(),
                'storage_ref': str(storage_ref or '').strip(),
                'summary': str(summary or f'{src_label}《{os.path.basename(fn or saved or "file")}》').strip()[:900],
                'symbols': [],
                'preview': '',
                'chunks': [],
                'is_code_like': False,
                'content_hash': h,
                'created_at': ts_now,
                'updated_at': ts_now,
            }
        if owner_key:
            rec['owner_key'] = owner_key
        return _file_registry_upsert(rec)
    except Exception:
        try:
            app_logger.exception('[file_registry] upload_register_saved_file_failed filename=%s', filename)
        except Exception:
            pass
        return {}


def _upload_cleanup_unparsed_saved_file(*, upload_scope: str = '', saved_filename: str = '', reason: str = '') -> dict:
    saved = str(saved_filename or '').strip()
    if not saved:
        return {'ok': True, 'skipped': True, 'reason': 'empty_saved_filename'}
    scope = _normalize_upload_scope(upload_scope)
    cleanup = {'ok': True, 'scope': scope, 'saved_filename': saved, 'reason': str(reason or '').strip(), 'deleted': [], 'skipped': []}
    try:
        root = _upload_dir_for_scope(scope, ensure=True)
        root_abs = os.path.abspath(root)
        path = os.path.abspath(os.path.join(root_abs, os.path.basename(saved)))
        if path.startswith(root_abs + os.sep) and os.path.isfile(path):
            size = 0
            try:
                size = os.path.getsize(path)
            except Exception:
                size = 0
            os.remove(path)
            cleanup['deleted'].append({'backend': 'local', 'path': path, 'size_bytes': int(size or 0)})
        else:
            cleanup['skipped'].append({'backend': 'local', 'reason': 'file_missing_or_outside_upload_root'})
    except Exception as e:
        cleanup['ok'] = False
        cleanup.setdefault('errors', []).append({'backend': 'local', 'error': f'{type(e).__name__}: {e}'})
        try:
            app_logger.exception('[upload_cleanup] local_delete_failed scope=%s filename=%s', scope, saved)
        except Exception:
            pass
    try:
        deleter = globals().get('_object_storage_delete_file')
        if callable(deleter) and deleter('uploads', scope, saved):
            cleanup['deleted'].append({'backend': 'object_storage', 'filename': saved})
        else:
            cleanup['skipped'].append({'backend': 'object_storage', 'reason': 'unavailable_or_not_deleted'})
    except Exception as e:
        cleanup['ok'] = False
        cleanup.setdefault('errors', []).append({'backend': 'object_storage', 'error': f'{type(e).__name__}: {e}'})
    try:
        app_logger.info('[upload_cleanup] unparsed_file_cleanup scope=%s filename=%s reason=%s deleted=%s skipped=%s', scope, saved, reason, len(cleanup.get('deleted') or []), len(cleanup.get('skipped') or []))
    except Exception:
        pass
    return cleanup


def _process_uploaded_file_payload(raw: bytes, original_filename: str, mimetype: str = '', form: dict | None = None, upload_scope: str | None = None):
    form = form or {}
    f = _UploadFileView(original_filename, mimetype)
    if not f.filename:
        return jsonify({"error": "文件名为空"}), 400
    ext = _ext_of(f.filename)
    filename_lower = (f.filename or "").strip().lower()
    is_special_text_name = filename_lower in SPECIAL_TEXT_FILENAMES
    if not ext and not is_special_text_name:
        special_hint = "；另支持常见无扩展名文件（如 Dockerfile、.env、.gitignore、Makefile）"
        return jsonify({"error": f"不支持的文件类型。支持：{', '.join(sorted(ALLOWED_EXT))}{special_hint}"}), 400

    if not raw:
        return jsonify({"error": "文件为空"}), 400

    size_payload = _upload_size_error_payload(ext, form=form)
    if len(raw) > int(size_payload.get('max_bytes') or 0):
        return jsonify(size_payload), 413

    # persist file to disk on the current access side only (local -> uploads_local, public -> uploads_public)
    h = hashlib.sha256(raw).hexdigest()[:16]
    ts = int(time.time())
    safe_ext = ext.lower()
    save_name = f"{ts}_{h}{safe_ext}"
    upload_scope = _normalize_upload_scope(upload_scope) if upload_scope else _request_upload_scope()
    save_path = os.path.join(_upload_dir_for_scope(upload_scope), save_name)
    persist_info = _persist_scoped_file_bytes(
        'uploads',
        upload_scope,
        save_name,
        raw,
        content_type=getattr(f, 'mimetype', '') or _guess_content_type_for_file(save_name),
        prune_func=_prune_upload_dir,
    )
    if not persist_info.get('ok'):
        if str(persist_info.get('code') or '') == 'storage_quota_exceeded':
            return _storage_quota_error_response(StorageQuotaError(str(persist_info.get('error') or '存储空间不足'), payload=persist_info.get('quota_payload') if isinstance(persist_info.get('quota_payload'), dict) else {}))
        # if saving fails everywhere, still continue for text extraction; downloadable URL is omitted.
        save_name = ""
        save_path = ""
    else:
        save_path = str(persist_info.get('path') or save_path)

    view_url, download_url = _build_uploaded_file_urls(save_name, upload_scope)
    kb_import = str(form.get('kb_import') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    kb_space_id = str(form.get('kb_space_id') or '').strip()

    # images: public upload must return fast.
    # Do not run Pillow compression/conversion in the upload request on public traffic:
    # mobile Safari + cloudflared can otherwise finish the browser-side upload circle
    # but keep waiting for the origin response until Cloudflare returns 524.
    # The model path still normalizes upload:// images later in the background chat worker.
    if ext in UPLOAD_IMAGE_EXTS:
        source_mime = str(getattr(f, 'mimetype', '') or UPLOAD_IMAGE_MIME_BY_EXT.get(ext, '') or '').split(';', 1)[0].strip().lower()
        if not source_mime:
            source_mime = UPLOAD_IMAGE_MIME_BY_EXT.get(ext, '') or 'application/octet-stream'
        is_heif_source = _is_heif_upload(ext, source_mime)
        public_fast_image = (upload_scope == UPLOAD_SCOPE_PUBLIC and _cfg_bool('PUBLIC_IMAGE_UPLOAD_FAST_RETURN', True) and not is_heif_source)
        if public_fast_image:
            model_raw, model_mime = raw, source_mime
        else:
            try:
                model_raw, model_mime = _prepare_uploaded_image_for_model(raw, filename=f.filename, mime_hint=getattr(f, 'mimetype', '') or '')
            except Exception as e:
                app_logger.warning('[upload_image] normalize_failed filename=%s ext=%s mimetype=%s err=%s', f.filename, ext, getattr(f, 'mimetype', ''), e)
                return jsonify({
                    "error": "该图片格式已上传到服务端，但当前环境暂时无法转换成模型可读取的格式。请优先使用 png、jpg、jpeg、webp、gif；苹果 HEIC/HEIF 请重试或在相册中选择兼容格式。"
                }), 400
        inline_data_url = ''
        if _should_inline_uploaded_image_data(upload_scope, has_saved_file=bool(save_name and view_url)):
            inline_data_url = f"data:{model_mime};base64," + base64.b64encode(model_raw).decode("ascii")
        # 图片上传阶段不要同步 OCR，避免公网/手机端在上传 100% 后继续卡在“最后一圈”。
        # 这里优先尽快返回，让图片先进入待发送；需要文字时后续由视觉模型直接看图即可。
        ocr_text = ''
        attachment_id = f"img_{upload_scope}_{h}"
        storage_ref = _build_upload_storage_ref(save_name, upload_scope) if save_name else ''
        model_storage_ref = storage_ref
        if is_heif_source and model_raw and model_mime in MODEL_SUPPORTED_IMAGE_MIMES:
            model_ext = _model_image_ext_for_mime(model_mime)
            model_h = hashlib.sha256(model_raw).hexdigest()[:16]
            model_save_name = f"{ts}_{model_h}_model{model_ext}"
            try:
                model_persist_info = _persist_scoped_file_bytes(
                    'uploads',
                    upload_scope,
                    model_save_name,
                    model_raw,
                    content_type=model_mime,
                    prune_func=_prune_upload_dir,
                )
            except Exception:
                model_persist_info = {'ok': False}
            if model_persist_info.get('ok'):
                model_storage_ref = _build_upload_storage_ref(model_save_name, upload_scope)
            elif str(model_persist_info.get('code') or '') == 'storage_quota_exceeded':
                return _storage_quota_error_response(StorageQuotaError(str(model_persist_info.get('error') or '存储空间不足'), payload=model_persist_info.get('quota_payload') if isinstance(model_persist_info.get('quota_payload'), dict) else {}))
            elif upload_scope == UPLOAD_SCOPE_PUBLIC:
                app_logger.warning('[upload_image] heif_model_persist_failed filename=%s ext=%s mimetype=%s', f.filename, ext, getattr(f, 'mimetype', ''))
                return jsonify({"error": "苹果图片已转换但模型文件保存失败，请重试。"}), 500
        preview_url = view_url or download_url or inline_data_url
        image_file_registry_payload = _upload_register_saved_file(
            upload_scope=upload_scope,
            source='upload',
            filename=str(f.filename or ''),
            saved_filename=save_name or str(f.filename or ''),
            ext=ext,
            size_bytes=len(raw),
            url=download_url,
            view_url=view_url,
            download_url=download_url,
            storage_ref=storage_ref,
            content_hash=h,
            summary=f'用户上传图片《{f.filename}》',
        )
        return jsonify({
            "filename": f.filename,
            "kind": "image",
            "mime": model_mime,
            "source_mime": source_mime or UPLOAD_IMAGE_MIME_BY_EXT.get(ext, getattr(f, 'mimetype', '') or ''),
            "source_type": "upload",
            "source_role": "user",
            "operation": "upload",
            "created_at_ms": int(time.time() * 1000),
            "image_seq": 1,
            "attachment_id": attachment_id,
            "storage_ref": storage_ref,
            "model_storage_ref": model_storage_ref,
            "url": view_url,
            "view_url": view_url,
            "download_url": download_url,
            "preview_url": preview_url,
            "object_url": _object_storage_public_url('uploads', upload_scope, save_name) if save_name else '',
            "storage_backend": 'object+local' if (persist_info.get('mirror_queued') or persist_info.get('object_ok')) else ('local' if persist_info.get('local_ok') else ''),
            "file_registry": image_file_registry_payload,
            "data_url": inline_data_url,
            "text": truncate_text(ocr_text, max_chars=20000) if ocr_text else "",
        })

    # text-like source/code files
    TEXT_LIKE = {
        ".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".log", ".cfg",
        ".py", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp",
        ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".mts", ".cts", ".java", ".go", ".rs", ".php", ".rb", ".swift", ".kt", ".cs",
        ".sql", ".yaml", ".yml", ".xml", ".toml", ".ini", ".sh", ".bat", ".ps1", ".proto", ".properties", ".conf", ".gradle", ".plist", ".ipynb",
        ".html", ".htm", ".css", ".scss", ".less", ".svg", ".vue", ".svelte", ".astro",
    }
    ARCHIVES = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz"}

    try:
        if ext in TEXT_LIKE or is_special_text_name:
            text = read_text_file(raw)
        elif ext == ".pdf":
            text = read_pdf(raw)
        elif ext == ".docx":
            text = read_docx(raw)
        elif ext == ".doc":
            text = read_doc(raw)
        elif ext == ".xlsx":
            text = read_xlsx(raw)
        elif ext == ".xls":
            text = read_xls(raw)
        elif ext == ".pptx":
            text = read_pptx(raw)
        elif ext in ARCHIVES:
            if ext == ".zip":
                text = read_archive_bundle(raw, ext)
            else:
                return jsonify({
                    "filename": f.filename,
                    "kind": "file",
                    "ext": ext,
                    "size": len(raw),
                    "source_type": "upload",
                    "url": download_url,
                    "view_url": view_url,
                    "download_url": download_url,
                    "object_url": _object_storage_public_url('uploads', upload_scope, save_name) if save_name else '',
                    "storage_backend": 'object+local' if (persist_info.get('mirror_queued') or persist_info.get('object_ok')) else ('local' if persist_info.get('local_ok') else ''),
                    "file_registry": _upload_register_saved_file(upload_scope=upload_scope, source='upload', filename=str(f.filename or ''), saved_filename=save_name or str(f.filename or ''), ext=ext, size_bytes=len(raw), url=download_url, view_url=view_url, download_url=download_url, storage_ref=_build_upload_storage_ref(save_name, upload_scope) if save_name else '', content_hash=h),
                    "note": "该压缩格式已保存，可点击下载；当前仅自动解析 .zip。",
                })
        else:
            # allowed but not parsed -> binary
            return jsonify({
                "filename": f.filename,
                "kind": "file",
                "ext": ext,
                "size": len(raw),
                "source_type": "upload",
                "url": download_url,
                "view_url": view_url,
                "download_url": download_url,
                "object_url": _object_storage_public_url('uploads', upload_scope, save_name) if save_name else '',
                "storage_backend": 'object+local' if (persist_info.get('mirror_queued') or persist_info.get('object_ok')) else ('local' if persist_info.get('local_ok') else ''),
                "file_registry": _upload_register_saved_file(upload_scope=upload_scope, source='upload', filename=str(f.filename or ''), saved_filename=save_name or str(f.filename or ''), ext=ext, size_bytes=len(raw), url=download_url, view_url=view_url, download_url=download_url, storage_ref=_build_upload_storage_ref(save_name, upload_scope) if save_name else '', content_hash=h),
                "note": "文件已保存，可点击下载；该类型不解析文本内容。",
            })
    except Exception as e:
        cleanup = _upload_cleanup_unparsed_saved_file(upload_scope=upload_scope, saved_filename=save_name, reason='parse_exception')
        return jsonify({"error": f"解析失败：{type(e).__name__}: {e}", "upload_retained": False, "cleanup": cleanup}), 400

    full_text = str(text or '').strip()
    if not full_text:
        cleanup = _upload_cleanup_unparsed_saved_file(upload_scope=upload_scope, saved_filename=save_name, reason='empty_parse_result')
        return jsonify({"error": "解析结果为空（扫描版 PDF/图片型文档需要 OCR）", "upload_retained": False, "cleanup": cleanup}), 400
    upload_preview_limit = max(5000, min(_cfg_int('UPLOAD_TEXT_MAX_CHARS', 60000), 300000))
    text = truncate_text(full_text, max_chars=upload_preview_limit)
    text_is_preview = bool(len(text) < len(full_text))

    kb_payload = {}
    if kb_import:
        try:
            kb_payload = _kb_import_document(
                space_id=kb_space_id,
                filename=str(f.filename or ''),
                ext=ext,
                size_bytes=len(raw),
                file_path=save_path if save_name else '',
                download_url=download_url,
                view_url=view_url,
                text=full_text,
                source='upload',
            ) or {}
        except StorageQuotaError as e:
            kb_payload = {'imported': False, 'error': str(e), 'code': 'storage_quota_exceeded'}
        except Exception as e:
            app_logger.exception('[kb] upload_import_failed filename=%s', f.filename)
            kb_payload = {'imported': False, 'error': f'{type(e).__name__}: {e}'}

    file_registry_payload = {}
    try:
        storage_ref = _build_upload_storage_ref(save_name, upload_scope) if save_name else ''
        file_registry_payload = _upload_register_saved_file(
            upload_scope=upload_scope,
            source='upload',
            filename=str(f.filename or ''),
            saved_filename=save_name or str(f.filename or ''),
            text=full_text,
            size_bytes=len(raw),
            url=download_url,
            view_url=view_url,
            download_url=download_url,
            storage_ref=storage_ref,
            content_hash=h,
        )
    except Exception:
        app_logger.exception('[file_registry] upload_register_failed filename=%s', f.filename)

    return jsonify({
        "filename": f.filename,
        "kind": "text",
        "text": text,
        "text_is_preview": text_is_preview,
        "full_text_available": bool(file_registry_payload.get('full_text_available')),
        "parsed_chars": len(full_text),
        "parsed_lines": full_text.count('\n') + (1 if full_text else 0),
        "source_type": "upload",
        "url": download_url,
        "view_url": view_url,
        "download_url": download_url,
        "ext": ext,
        "size": len(raw),
        "object_url": _object_storage_public_url('uploads', upload_scope, save_name) if save_name else '',
        "storage_backend": 'object+local' if (persist_info.get('mirror_queued') or persist_info.get('object_ok')) else ('local' if persist_info.get('local_ok') else ''),
        "file_registry": file_registry_payload,
        "code_summary": file_registry_payload.get('summary') if isinstance(file_registry_payload, dict) else '',
        "symbols": file_registry_payload.get('symbols') if isinstance(file_registry_payload, dict) else [],
        "kb_imported": bool(kb_payload.get('imported')),
        "kb_document": kb_payload.get('document') or {},
        "kb_space": kb_payload.get('space') or {},
        "kb_error": str(kb_payload.get('error') or ''),
    })



_UPLOAD_CHUNK_ROOT_LOCK = threading.Lock()


def _upload_chunk_root() -> str:
    root = _app_data_path('upload_chunks')
    os.makedirs(root, exist_ok=True)
    return root


def _upload_chunk_size_bytes() -> int:
    try:
        raw = int(str(app_getenv('PUBLIC_UPLOAD_CHUNK_SIZE', str(512 * 1024))) or (512 * 1024))
    except Exception:
        raw = 512 * 1024
    return max(128 * 1024, min(raw, 2 * 1024 * 1024))


def _upload_chunk_max_age_seconds() -> float:
    try:
        return max(600.0, float(str(app_getenv('PUBLIC_UPLOAD_CHUNK_MAX_AGE', '21600')) or 21600))
    except Exception:
        return 21600.0


def _upload_chunk_session_dir(scope: str, upload_id: str, ensure: bool = False) -> str:
    clean_scope = _normalize_upload_scope(scope)
    clean_id = re.sub(r'[^0-9a-fA-F_-]+', '', str(upload_id or '').strip())[:80]
    path = os.path.join(_upload_chunk_root(), clean_scope, clean_id)
    if ensure:
        os.makedirs(path, exist_ok=True)
    return path


def _upload_chunk_manifest_path(scope: str, upload_id: str) -> str:
    return os.path.join(_upload_chunk_session_dir(scope, upload_id, ensure=False), 'manifest.json')


def _upload_chunk_write_manifest(scope: str, upload_id: str, manifest: dict) -> None:
    path = _upload_chunk_manifest_path(scope, upload_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp-' + uuid.uuid4().hex
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False)
    os.replace(tmp, path)


def _upload_chunk_read_manifest(scope: str, upload_id: str) -> dict:
    path = _upload_chunk_manifest_path(scope, upload_id)
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f) or {}
    return data if isinstance(data, dict) else {}


def _upload_chunk_find(upload_id: str) -> tuple[str, dict] | tuple[str, None]:
    clean_id = re.sub(r'[^0-9a-fA-F_-]+', '', str(upload_id or '').strip())[:80]
    if not clean_id:
        return '', None
    preferred = _request_upload_scope()
    scopes = []
    for scope in (preferred, UPLOAD_SCOPE_PUBLIC, UPLOAD_SCOPE_LOCAL):
        ns = _normalize_upload_scope(scope)
        if ns not in scopes:
            scopes.append(ns)
    for scope in scopes:
        path = _upload_chunk_manifest_path(scope, clean_id)
        if os.path.exists(path):
            try:
                return scope, _upload_chunk_read_manifest(scope, clean_id)
            except Exception:
                return scope, None
    return '', None


def _upload_chunk_cleanup_old() -> None:
    now = time.time()
    ttl = _upload_chunk_max_age_seconds()
    root = _upload_chunk_root()
    try:
        for scope in os.listdir(root):
            scope_dir = os.path.join(root, scope)
            if not os.path.isdir(scope_dir):
                continue
            for name in os.listdir(scope_dir):
                path = os.path.join(scope_dir, name)
                try:
                    st = os.stat(path)
                except Exception:
                    continue
                if now - float(st.st_mtime) > ttl:
                    shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
    try:
        max_bytes = _storage_quota_int('UPLOAD_CHUNKS_MAX_BYTES', 1024 * 1024 * 1024, minimum=64 * 1024 * 1024)
        _storage_quota_prune_child_dirs(root, max_bytes, ttl_seconds=ttl)
    except Exception:
        pass


def _upload_chunk_json_or_form() -> dict:
    if request.is_json:
        return request.get_json(silent=True) or {}
    out = {}
    try:
        for k in request.form.keys():
            out[k] = request.form.get(k)
    except Exception:
        pass
    return out


def _upload_chunk_error(message: str, status: int = 400, **extra):
    payload = {'ok': False, 'error': str(message or '上传失败')}
    payload.update(extra)
    return jsonify(payload), status


def _upload_chunk_cancel_session(upload_id: str) -> dict:
    clean_id = re.sub(r'[^0-9a-fA-F_-]+', '', str(upload_id or '').strip())[:80]
    if not clean_id:
        return {'ok': False, 'error': 'empty_upload_id'}
    scope, manifest = _upload_chunk_find(clean_id)
    scope = _normalize_upload_scope(scope or (manifest or {}).get('scope') or _request_upload_scope())
    root = os.path.abspath(_upload_chunk_session_dir(scope, clean_id, ensure=False))
    root_base = os.path.abspath(_upload_chunk_root())
    if not (root == root_base or root.startswith(root_base + os.sep)):
        return {'ok': False, 'error': 'invalid_upload_path'}
    existed = os.path.isdir(root)
    if existed:
        shutil.rmtree(root, ignore_errors=True)
    return {'ok': True, 'upload_id': clean_id, 'scope': scope, 'deleted': bool(existed)}


@app.post('/api3/upload_chunk/cancel')
def upload_chunk_cancel_gpt():
    payload = _upload_chunk_json_or_form()
    upload_id = str(payload.get('upload_id') or request.args.get('upload_id') or '').strip()
    result = _upload_chunk_cancel_session(upload_id)
    if not result.get('ok'):
        return _upload_chunk_error(str(result.get('error') or 'cancel_failed'), 400)
    return jsonify(result)


@app.post('/api3/upload_chunk/init')
def upload_chunk_init_gpt():
    # 分片上传不能沿用普通上传的次数限流：一张 iPhone 图片会拆成几十到上百片，
    # 逐片计入 upload 限流会把正常上传误杀成 rate_limited。
    _upload_chunk_cleanup_old()
    payload = _upload_chunk_json_or_form()
    original_filename = str(payload.get('filename') or '').strip()
    if not original_filename:
        return _upload_chunk_error('文件名为空')
    ext = _ext_of(original_filename)
    filename_lower = original_filename.lower()
    is_special_text_name = filename_lower in SPECIAL_TEXT_FILENAMES
    if not ext and not is_special_text_name:
        special_hint = '；另支持常见无扩展名文件（如 Dockerfile、.env、.gitignore、Makefile）'
        return _upload_chunk_error(f"不支持的文件类型。支持：{', '.join(sorted(ALLOWED_EXT))}{special_hint}")
    try:
        size = max(0, int(payload.get('size') or 0))
    except Exception:
        size = 0
    size_payload = _upload_size_error_payload(ext, form=payload)
    if size > 0 and size > int(size_payload.get('max_bytes') or 0):
        return _upload_chunk_error(str(size_payload.get('error') or '文件过大'), 413, max_bytes=int(size_payload.get('max_bytes') or 0), max_text=str(size_payload.get('max_text') or ''))
    default_chunk_size = _upload_chunk_size_bytes()
    try:
        requested_chunk_size = int(str(payload.get('chunk_size') or default_chunk_size).strip() or default_chunk_size)
    except Exception:
        requested_chunk_size = default_chunk_size
    # 公网手机端更稳：允许前端请求更小的分片，避免一片在 cloudflared/移动网络里卡太久。
    chunk_size = max(32 * 1024, min(int(requested_chunk_size or default_chunk_size), 2 * 1024 * 1024))
    try:
        total_chunks = max(1, min(20000, math.ceil(size / chunk_size) if size > 0 else int(payload.get('total_chunks') or 1)))
    except Exception:
        total_chunks = max(1, int(payload.get('total_chunks') or 1))
    upload_scope = _request_upload_scope()
    owner_key = _storage_quota_owner_key() if callable(globals().get('_storage_quota_owner_key')) else ''
    try:
        max_chunks_bytes = _storage_quota_int('UPLOAD_CHUNKS_MAX_BYTES', 1024 * 1024 * 1024, minimum=64 * 1024 * 1024)
        _storage_quota_module_limit('upload_chunks', _storage_quota_dir_size(_upload_chunk_root()), max(0, int(size or 0)), max_chunks_bytes, label='临时上传分片')
        checker = globals().get('_storage_quota_require_write')
        if callable(checker):
            checker('upload_chunks', incoming_bytes=max(0, int(size or 0)), target_path=_upload_chunk_root(), owner_key=owner_key)
    except StorageQuotaError as e:
        return _storage_quota_error_response(e)
    upload_id = uuid.uuid4().hex
    manifest = {
        'upload_id': upload_id,
        'scope': upload_scope,
        'owner_key': owner_key,
        'filename': os.path.basename(original_filename),
        'mimetype': str(payload.get('mime') or payload.get('mimetype') or '').strip(),
        'size': size,
        'total_chunks': total_chunks,
        'chunk_size': chunk_size,
        'created_at': time.time(),
        'updated_at': time.time(),
        'form': {
            'kb_import': str(payload.get('kb_import') or ''),
            'kb_space_id': str(payload.get('kb_space_id') or ''),
        },
    }
    _upload_chunk_write_manifest(upload_scope, upload_id, manifest)
    return jsonify({'ok': True, 'upload_id': upload_id, 'chunk_size': manifest['chunk_size'], 'scope': upload_scope})


def _upload_chunk_save_part(upload_id: str, index: int, raw: bytes):
    upload_id = str(upload_id or '').strip()
    scope, manifest = _upload_chunk_find(upload_id)
    if not scope or not manifest:
        return _upload_chunk_error('上传任务不存在或已过期', 404)
    try:
        index = int(index)
    except Exception:
        index = -1
    total_chunks = int(manifest.get('total_chunks') or 1)
    if index < 0 or index >= total_chunks:
        return _upload_chunk_error('分片序号无效')
    raw = raw if raw is not None else b''
    if not raw:
        return _upload_chunk_error('分片为空')
    manifest_chunk_size = int(manifest.get('chunk_size') or _upload_chunk_size_bytes() or (512 * 1024))
    max_part = max(manifest_chunk_size * 3, 8 * 1024 * 1024)
    if len(raw) > max_part:
        return _upload_chunk_error('单个分片过大')
    root = _upload_chunk_session_dir(scope, upload_id, ensure=True)
    try:
        max_chunks_bytes = _storage_quota_int('UPLOAD_CHUNKS_MAX_BYTES', 1024 * 1024 * 1024, minimum=64 * 1024 * 1024)
        _storage_quota_module_limit('upload_chunks', _storage_quota_dir_size(_upload_chunk_root()), len(raw), max_chunks_bytes, label='临时上传分片')
        checker = globals().get('_storage_quota_check_system')
        if callable(checker):
            checker(incoming_bytes=len(raw), path=root, cleanup=False)
    except StorageQuotaError as e:
        return _storage_quota_error_response(e)
    part_path = os.path.join(root, f'part_{index:06d}.bin')
    tmp = part_path + '.tmp-' + uuid.uuid4().hex
    try:
        with open(tmp, 'wb') as f:
            f.write(raw)
        os.replace(tmp, part_path)
        try:
            os.utime(root, None)
        except Exception:
            pass
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
    return jsonify({'ok': True, 'upload_id': upload_id, 'index': index})


@app.post('/api3/upload_chunk/raw_part')
def upload_chunk_raw_part_gpt():
    # 每个 raw_part 是同一次上传任务的一小片，不能按上传次数限流。
    upload_id = str(request.args.get('upload_id') or request.headers.get('X-Upload-Id') or '').strip()
    try:
        index = int(request.args.get('index') or request.headers.get('X-Upload-Index') or 0)
    except Exception:
        index = -1
    raw = request.get_data(cache=False) or b''
    return _upload_chunk_save_part(upload_id, index, raw)


@app.post('/api3/upload_chunk/part')
def upload_chunk_part_gpt():
    # 兼容旧前端 multipart 分片，同样不能逐片计入普通 upload 限流。
    upload_id = str(request.form.get('upload_id') or '').strip()
    try:
        index = int(request.form.get('index') or 0)
    except Exception:
        index = -1
    part = request.files.get('chunk')
    if not part:
        return _upload_chunk_error('没有收到分片字段 chunk')
    raw = part.read()
    return _upload_chunk_save_part(upload_id, index, raw)


@app.post('/api3/upload_chunk/finish')
def upload_chunk_finish_gpt():
    # finish 只做合并校验，不再受普通上传次数限流影响。
    payload = _upload_chunk_json_or_form()
    upload_id = str(payload.get('upload_id') or '').strip()
    scope, manifest = _upload_chunk_find(upload_id)
    if not scope or not manifest:
        return _upload_chunk_error('上传任务不存在或已过期', 404)
    root = _upload_chunk_session_dir(scope, upload_id, ensure=False)
    total_chunks = int(manifest.get('total_chunks') or 1)
    missing = []
    part_paths = []
    for idx in range(total_chunks):
        pp = os.path.join(root, f'part_{idx:06d}.bin')
        if not os.path.exists(pp):
            missing.append(idx)
        else:
            part_paths.append(pp)
    if missing:
        return _upload_chunk_error('分片不完整，请重试', 409, missing=missing[:20])
    tmp_merged = os.path.join(root, 'merged.tmp')
    try:
        with open(tmp_merged, 'wb') as out:
            for pp in part_paths:
                with open(pp, 'rb') as f:
                    shutil.copyfileobj(f, out, length=1024 * 1024)
        with open(tmp_merged, 'rb') as f:
            raw = f.read()
        expected_size = int(manifest.get('size') or 0)
        if expected_size > 0 and len(raw) != expected_size:
            return _upload_chunk_error('分片合并后大小不一致，请重新上传', 409, expected_size=expected_size, actual_size=len(raw))
        return _process_uploaded_file_payload(
            raw,
            str(manifest.get('filename') or 'upload.bin'),
            str(manifest.get('mimetype') or ''),
            form=dict(manifest.get('form') or {}),
            upload_scope=scope,
        )
    finally:
        try:
            shutil.rmtree(root, ignore_errors=True)
        except Exception:
            pass


@app.post("/api3/upload")
def upload_gpt():
    limit_resp = _apply_rate_limit('upload')
    if limit_resp is not None:
        return limit_resp
    if "file" not in request.files:
        return jsonify({"error": "没有收到文件字段 file"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "文件名为空"}), 400
    raw = f.read()
    if not raw:
        return jsonify({"error": "文件为空"}), 400
    return _process_uploaded_file_payload(raw, f.filename, getattr(f, 'mimetype', '') or '', form=_upload_form_snapshot(request.form))
