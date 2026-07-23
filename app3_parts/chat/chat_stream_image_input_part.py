# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: convert chat image sources into sandbox-backed Responses input items.
# Loaded before chat_streaming_part.py, sharing the original global namespace.


class ChatStreamImageInputContext:
    def __init__(
        self,
        *,
        model: str = '',
        messages: list | None = None,
        eager_image_rows_for_generation=None,
        exact_selected_image_rows=None,
        direct_resolve_image_rows=None,
        external_image_asset_candidate_rows=None,
        direct_image_rows_for_model=None,
        image_rows_log_payload=None,
        image_row_log_payload=None,
    ):
        self.model = str(model or '')
        self.messages = list(messages or []) if isinstance(messages, list) else []
        self.eager_image_rows_for_generation = eager_image_rows_for_generation if callable(eager_image_rows_for_generation) else (lambda base_messages=None, task_type='', limit=8: [])
        self.exact_selected_image_rows = exact_selected_image_rows if callable(exact_selected_image_rows) else (lambda raw_values=None, candidate_rows=None, limit=8: [])
        self.direct_resolve_image_rows = direct_resolve_image_rows if callable(direct_resolve_image_rows) else (lambda raw_values=None, candidate_rows=None, limit=4: [])
        self.external_image_asset_candidate_rows = external_image_asset_candidate_rows if callable(external_image_asset_candidate_rows) else (lambda limit=12: [])
        self.direct_image_rows_for_model = direct_image_rows_for_model if callable(direct_image_rows_for_model) else (lambda candidate_rows=None, limit=8: '')
        self.image_rows_log_payload = image_rows_log_payload if callable(image_rows_log_payload) else (lambda rows=None, limit=12: [])
        self.image_row_log_payload = image_row_log_payload if callable(image_row_log_payload) else (lambda row=None: {})

    def _agent_stream_image_bytes_to_data_url(self, raw: bytes = b'', mime: str = '', filename: str = '') -> str:
        try:
            data = bytes(raw or b'')
        except Exception:
            data = b''
        if not data:
            return ''
        mime_s = str(mime or '').split(';', 1)[0].strip().lower()
        if not mime_s:
            ext = ''
            try:
                ext = str((globals().get('_ext_of') or (lambda x: os.path.splitext(str(x or ''))[1]))(filename or '') or '').strip().lower()
            except Exception:
                ext = os.path.splitext(str(filename or ''))[1].strip().lower()
            mime_s = {'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.webp':'image/webp','.gif':'image/gif','.bmp':'image/bmp','.svg':'image/svg+xml'}.get(ext, 'image/png')
        try:
            coerce = globals().get('_coerce_image_bytes_for_model')
            if callable(coerce):
                data, mime_s = coerce(data, mime_s)
        except Exception:
            pass
        try:
            return 'data:%s;base64,%s' % (mime_s or 'image/png', base64.b64encode(data).decode('ascii'))
        except Exception:
            return ''

    def _agent_stream_local_image_source_to_data_url(self, source: str = '') -> str:
        raw = str(source or '').strip()
        if not raw:
            return ''
        # Older candidate rows may carry a misleading "base64:" prefix around a
        # project-local reference such as upload://local/xxx.png.  Never forward
        # that shape to /responses: upstreams try to base64-decode the literal
        # upload:// string and fail before image_generation starts.
        low = raw.lower()
        if low.startswith('base64:'):
            body = raw.split(':', 1)[1].strip()
            body_low = body.lower()
            if body_low.startswith(('upload://', 'data:image/', 'http://', 'https://', '/api3/', '/')):
                raw = body
            else:
                try:
                    decoded = base64.b64decode(body.strip(), validate=False)
                    if decoded:
                        return self._agent_stream_image_bytes_to_data_url(decoded, 'image/png', 'image.png')
                except Exception:
                    return ''
        if raw.startswith('upload://'):
            try:
                reader = globals().get('_read_upload_storage_ref_bytes')
                if callable(reader):
                    data, mime = reader(raw)
                    return self._agent_stream_image_bytes_to_data_url(data, mime, raw)
            except Exception:
                return ''
        try:
            has_scheme = bool(re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', raw))
        except Exception:
            has_scheme = False
        if raw and (not has_scheme) and (not raw.startswith('/')):
            try:
                getter = globals().get('_file_library_get_record')
                resolver = globals().get('_file_library_resolve_local_path')
                category_fn = globals().get('_file_library_category')
                if callable(getter) and callable(resolver):
                    rec = getter(raw) or {}
                    if isinstance(rec, dict) and rec:
                        local_path = str(resolver(rec) or '').strip()
                        ext = str((globals().get('_ext_of') or (lambda x: os.path.splitext(str(x or ''))[1]))(rec.get('filename') or rec.get('saved_filename') or local_path or '') or '').strip().lower()
                        category = str(category_fn(rec.get('filename') or rec.get('saved_filename') or local_path or '', ext) if callable(category_fn) else '').strip().lower()
                        if local_path and os.path.isfile(local_path) and (category == 'image' or ext in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.heic', '.heif'}):
                            with open(local_path, 'rb') as f:
                                return self._agent_stream_image_bytes_to_data_url(f.read(), '', local_path)
            except Exception:
                pass
        try:
            parsed = urlparse(raw)
            path = parsed.path or (raw if raw.startswith('/') else '')
            scope = ''
            try:
                scope_helper = globals().get('_extract_upload_scope_from_url')
                if callable(scope_helper):
                    scope = str(scope_helper(raw) or '').strip()
            except Exception:
                scope = ''
            if path.startswith('/api3/generated-files/') or path.startswith('/api3/generated-download/'):
                marker = '/api3/generated-files/' if path.startswith('/api3/generated-files/') else '/api3/generated-download/'
                filename = urllib.parse.unquote(path.split(marker, 1)[1].strip('/'))
                resolver = globals().get('_resolve_generated_file_dir')
                base_dir = resolver(filename, scope=scope or None) if callable(resolver) else ''
                fp = os.path.join(base_dir, filename) if base_dir and filename else ''
                if fp and os.path.isfile(fp):
                    with open(fp, 'rb') as f:
                        return self._agent_stream_image_bytes_to_data_url(f.read(), '', filename)
            if path.startswith('/api3/uploads/') or path.startswith('/api3/download/'):
                marker = '/api3/uploads/' if path.startswith('/api3/uploads/') else '/api3/download/'
                filename = urllib.parse.unquote(path.split(marker, 1)[1].strip('/'))
                resolver = globals().get('_resolve_uploaded_file_dir')
                base_dir = resolver(filename, scope=scope or None) if callable(resolver) else ''
                fp = os.path.join(base_dir, filename) if base_dir and filename else ''
                if fp and os.path.isfile(fp):
                    with open(fp, 'rb') as f:
                        return self._agent_stream_image_bytes_to_data_url(f.read(), '', filename)
        except Exception:
            pass
        try:
            if raw and os.path.isfile(raw):
                with open(raw, 'rb') as f:
                    return self._agent_stream_image_bytes_to_data_url(f.read(), '', raw)
        except Exception:
            pass
        return ''

    def _agent_stream_data_url_to_sandbox_image_item(self, data_url: str = '', *, filename: str = '', label: str = '', source: str = '') -> dict | None:
        messages = self.messages
        raw = str(data_url or '').strip()
        if not raw.startswith('data:image/') or ',' not in raw:
            return None
        try:
            header, payload = raw.split(',', 1)
            mime = header.split(':', 1)[1].split(';', 1)[0].strip() if ':' in header else 'image/png'
            if ';base64' in header.lower():
                data = base64.b64decode(payload)
            else:
                data = urllib.parse.unquote_to_bytes(payload)
        except Exception:
            return None
        if not data:
            return None
        mime_s = str(mime or 'image/png').split(';', 1)[0].strip().lower() or 'image/png'
        try:
            coerce = globals().get('_coerce_image_bytes_for_model')
            if callable(coerce):
                data, mime_s = coerce(data, mime_s)
        except Exception:
            pass
        ext_map = {
            'image/jpeg': '.jpg',
            'image/jpg': '.jpg',
            'image/png': '.png',
            'image/webp': '.webp',
            'image/gif': '.gif',
            'image/bmp': '.bmp',
            'image/tiff': '.tiff',
        }
        ext = ext_map.get(mime_s, '')
        if not ext:
            name_ext = os.path.splitext(str(filename or ''))[1].strip().lower()
            ext = name_ext if name_ext in {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff'} else '.png'
            if ext == '.jpeg':
                ext = '.jpg'
        try:
            slugger = globals().get('_sandbox_safe_slug')
            if callable(slugger):
                safe_name = str(slugger(os.path.splitext(os.path.basename(filename or label or 'image'))[0] or 'image', 'image') or 'image')
            else:
                safe_name = re.sub(r'[^0-9A-Za-z_.-]+', '-', os.path.splitext(os.path.basename(filename or label or 'image'))[0] or 'image') or 'image'
        except Exception:
            safe_name = 'image'
        digest = hashlib.sha256(data).hexdigest()[:16]
        rel = ('chat_images/%s_%s%s' % (safe_name[:48], digest, ext)).replace('\\', '/')
        try:
            abs_path, rel = _sandbox_resolve_path(rel, messages or [], must_exist=False)
            quota_ok, quota_meta = _sandbox_quota_ok(messages or [], incoming_bytes=len(data), current_path=abs_path, append=False)
            if not quota_ok:
                return None
            storage_ok, storage_meta = _sandbox_storage_quota_ok(messages or [], incoming_bytes=len(data), current_path=abs_path, append=False)
            if not storage_ok:
                return None
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, 'wb') as f:
                f.write(data)
            row = {
                'path': rel,
                'mount_path': ('/mnt/data/' + rel.strip('/')).rstrip('/'),
                'filename': os.path.basename(rel),
                'source_filename': filename or os.path.basename(rel),
                'size': int(os.path.getsize(abs_path) if os.path.exists(abs_path) else len(data)),
                'imported_at': int(time.time()),
                'source': 'image_generation_reference',
                'source_ref': str(source or '')[:500],
            }
            try:
                _sandbox_note_imported_files([row], messages or [])
            except Exception:
                pass
            sandbox_data_url, data_err, _data_bytes = _sandbox_data_url_for_image(abs_path)
            if data_err or not str(sandbox_data_url or '').startswith('data:image/'):
                return None
            return {
                'type': 'input_image',
                'image_url': sandbox_data_url,
                'detail': 'high',
                '_sandbox_path': rel,
                '_sandbox_source': 'chat_images',
            }
        except Exception:
            return None

    def _agent_stream_image_ext_from_mime_or_bytes(self, mime: str = '', raw: bytes = b'', filename: str = '') -> str:
        mime_s = str(mime or '').split(';', 1)[0].strip().lower()
        ext = ''
        try:
            ext = str((globals().get('_ext_of') or (lambda x: os.path.splitext(str(x or ''))[1]))(filename or '') or '').strip().lower()
        except Exception:
            ext = os.path.splitext(str(filename or ''))[1].strip().lower()
        if ext in {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tif', '.tiff'}:
            return '.jpg' if ext == '.jpeg' else ext
        by_mime = {
            'image/jpeg': '.jpg',
            'image/jpg': '.jpg',
            'image/png': '.png',
            'image/webp': '.webp',
            'image/gif': '.gif',
            'image/bmp': '.bmp',
            'image/tiff': '.tiff',
        }
        if mime_s in by_mime:
            return by_mime[mime_s]
        data = bytes(raw or b'')[:16]
        if data.startswith(b'\xff\xd8\xff'):
            return '.jpg'
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return '.png'
        if data.startswith(b'RIFF') and b'WEBP' in data[:16]:
            return '.webp'
        if data.startswith((b'GIF87a', b'GIF89a')):
            return '.gif'
        if data.startswith(b'BM'):
            return '.bmp'
        if data.startswith((b'II*\x00', b'MM\x00*')):
            return '.tiff'
        return '.png'

    def _candidate_sources_from_row(self, row: dict | None = None, *, first_url: str = '') -> list[str]:
        srcs: list[str] = []

        def add(value) -> None:
            value = str(value or '').strip()
            if value and value not in srcs:
                srcs.append(value)

        row_obj = dict(row or {}) if isinstance(row, dict) else {}
        item_obj = row_obj.get('item') if isinstance(row_obj.get('item'), dict) else {}
        for value in (
            first_url,
            row_obj.get('url'), row_obj.get('image_url'), row_obj.get('download_url'),
            row_obj.get('attachment_key'), row_obj.get('model_storage_ref'), row_obj.get('storage_ref'),
            row_obj.get('persisted_url'), row_obj.get('server_url'), row_obj.get('_preview_url'), row_obj.get('_source_url'),
            row_obj.get('file_library_id'), row_obj.get('library_file_id'),
        ):
            add(value)
        try:
            model_candidates = globals().get('_image_item_model_candidates')
            if callable(model_candidates):
                for value in (model_candidates(item_obj) or []):
                    add(value)
        except Exception:
            pass
        if isinstance(item_obj, dict):
            img_obj = item_obj.get('image_url') if isinstance(item_obj.get('image_url'), dict) else {}
            for value in (
                item_obj.get('model_storage_ref'), item_obj.get('storage_ref'), item_obj.get('persisted_url'),
                item_obj.get('server_url'), item_obj.get('url'), item_obj.get('_preview_url'), item_obj.get('_source_url'),
                item_obj.get('file_library_id'), item_obj.get('library_file_id'),
                img_obj.get('url') if isinstance(img_obj, dict) else '',
            ):
                add(value)
        return srcs

    def _agent_stream_image_asset_candidate_sources(self, row: dict | None = None, fallback_url: str = '') -> list[str]:
        return self._candidate_sources_from_row(row, first_url=fallback_url)

    def _agent_stream_image_source_to_bytes(self, source: str = '', row: dict | None = None) -> tuple[bytes, str, str, str]:
        raw = str(source or '').strip()
        if not raw:
            return b'', '', '', ''
        if raw.lower().startswith('base64:'):
            body = raw.split(':', 1)[1].strip()
            if body.lower().startswith(('upload://', 'data:image/', 'http://', 'https://', '/api3/', '/')):
                raw = body
            else:
                try:
                    data = base64.b64decode(body, validate=False)
                    return bytes(data or b''), 'image/png', 'inline_image.png', 'base64'
                except Exception:
                    return b'', '', '', ''
        if raw.startswith('data:image/'):
            try:
                header, payload = raw.split(',', 1)
                mime = header.split(':', 1)[1].split(';', 1)[0].strip() if ':' in header else 'image/png'
                if ';base64' in header.lower():
                    return base64.b64decode(payload), mime, 'inline_image' + self._agent_stream_image_ext_from_mime_or_bytes(mime), 'data_url'
                return urllib.parse.unquote_to_bytes(payload), mime, 'inline_image' + self._agent_stream_image_ext_from_mime_or_bytes(mime), 'data_url'
            except Exception:
                return b'', '', '', ''
        if raw.startswith('upload://'):
            try:
                reader = globals().get('_read_upload_storage_ref_bytes')
                if callable(reader):
                    data, mime = reader(raw)
                    return bytes(data or b''), str(mime or ''), raw.rsplit('/', 1)[-1] or 'upload_image', raw
            except Exception:
                return b'', '', '', ''
        try:
            has_scheme = bool(re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', raw))
        except Exception:
            has_scheme = False
        if raw and (not has_scheme) and (not raw.startswith('/')):
            try:
                getter = globals().get('_file_library_get_record')
                resolver = globals().get('_file_library_resolve_local_path')
                category_fn = globals().get('_file_library_category')
                if callable(getter) and callable(resolver):
                    rec = getter(raw) or {}
                    if isinstance(rec, dict) and rec:
                        local_path = str(resolver(rec) or '').strip()
                        filename = str(rec.get('filename') or rec.get('saved_filename') or os.path.basename(local_path) or raw).strip()
                        ext = str((globals().get('_ext_of') or (lambda x: os.path.splitext(str(x or ''))[1]))(filename or local_path or '') or '').strip().lower()
                        category = str(category_fn(filename or local_path or '', ext) if callable(category_fn) else '').strip().lower()
                        if local_path and os.path.isfile(local_path) and (category == 'image' or ext in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.heic', '.heif', '.tif', '.tiff'}):
                            with open(local_path, 'rb') as f:
                                return f.read(), '', filename or os.path.basename(local_path), local_path
            except Exception:
                pass
        try:
            parsed = urlparse(raw)
            path = parsed.path or (raw if raw.startswith('/') else '')
            scope = ''
            try:
                scope_helper = globals().get('_extract_upload_scope_from_url')
                if callable(scope_helper):
                    scope = str(scope_helper(raw) or '').strip()
            except Exception:
                scope = ''
            if path.startswith('/api3/generated-files/') or path.startswith('/api3/generated-download/'):
                marker = '/api3/generated-files/' if path.startswith('/api3/generated-files/') else '/api3/generated-download/'
                filename = urllib.parse.unquote(path.split(marker, 1)[1].strip('/'))
                resolver = globals().get('_resolve_generated_file_dir')
                base_dir = resolver(filename, scope=scope or None) if callable(resolver) else ''
                fp = os.path.join(base_dir, filename) if base_dir and filename else ''
                if fp and os.path.isfile(fp):
                    with open(fp, 'rb') as f:
                        return f.read(), '', filename, fp
            if path.startswith('/api3/uploads/') or path.startswith('/api3/download/'):
                marker = '/api3/uploads/' if path.startswith('/api3/uploads/') else '/api3/download/'
                filename = urllib.parse.unquote(path.split(marker, 1)[1].strip('/'))
                resolver = globals().get('_resolve_uploaded_file_dir')
                base_dir = resolver(filename, scope=scope or None) if callable(resolver) else ''
                fp = os.path.join(base_dir, filename) if base_dir and filename else ''
                if fp and os.path.isfile(fp):
                    with open(fp, 'rb') as f:
                        return f.read(), '', filename, fp
        except Exception:
            pass
        try:
            if raw and os.path.isfile(raw):
                with open(raw, 'rb') as f:
                    return f.read(), '', os.path.basename(raw), raw
        except Exception:
            pass
        if raw.startswith(('http://', 'https://')):
            try:
                req_mod = globals().get('requests')
                if req_mod is None:
                    return b'', '', '', ''
                resp = req_mod.get(raw, timeout=12, stream=True)
                try:
                    status_code = int(getattr(resp, 'status_code', 0) or 0)
                except Exception:
                    status_code = 0
                if status_code < 200 or status_code >= 300:
                    return b'', '', '', ''
                max_bytes = 20 * 1024 * 1024
                chunks = []
                total = 0
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        return b'', '', '', ''
                    chunks.append(chunk)
                mime = str((getattr(resp, 'headers', {}) or {}).get('content-type') or '').split(';', 1)[0].strip()
                filename = os.path.basename(urllib.parse.unquote(urlparse(raw).path or '')) or 'remote_image'
                return b''.join(chunks), mime, filename, raw
            except Exception:
                return b'', '', '', ''
        return b'', '', '', ''

    def _agent_stream_import_image_bytes_to_sandbox(self, raw_bytes: bytes = b'', mime: str = '', filename: str = '', label: str = '', source: str = '', *, asset_source: str = 'chat_image_asset') -> dict:
        model = self.model
        messages = self.messages
        data = bytes(raw_bytes or b'')
        if not data:
            return {'ok': False, 'error': 'empty_image_bytes'}
        mime_s = str(mime or '').split(';', 1)[0].strip().lower()
        try:
            coerce = globals().get('_coerce_image_bytes_for_model')
            if callable(coerce):
                data, mime_s = coerce(data, mime_s or 'application/octet-stream')
        except Exception:
            pass
        ext = self._agent_stream_image_ext_from_mime_or_bytes(mime_s, data, filename)
        try:
            safe_fn = str((globals().get('_sandbox_safe_slug') or (lambda v, fallback='image': re.sub(r'[^0-9A-Za-z_.-]+', '-', str(v or fallback))))(os.path.splitext(os.path.basename(filename or 'image'))[0] or label or 'image', 'image') or 'image')
        except Exception:
            safe_fn = 'image'
        digest = hashlib.sha256(data).hexdigest()[:16]
        rel = ('chat_images/%s_%s%s' % (safe_fn[:48], digest, ext)).replace('\\', '/')
        try:
            abs_path, rel = _sandbox_resolve_path(rel, messages or [], must_exist=False)
            quota_ok, quota_meta = _sandbox_quota_ok(messages or [], incoming_bytes=len(data), current_path=abs_path, append=False)
            if not quota_ok:
                return dict(quota_meta or {'ok': False, 'error': 'sandbox_disk_quota_exceeded'})
            storage_ok, storage_meta = _sandbox_storage_quota_ok(messages or [], incoming_bytes=len(data), current_path=abs_path, append=False)
            if not storage_ok:
                return dict(storage_meta or {'ok': False, 'error': 'storage_quota_exceeded'})
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, 'wb') as f:
                f.write(data)
            row = {
                'path': rel,
                'mount_path': ('/mnt/data/' + rel.strip('/')).rstrip('/'),
                'filename': os.path.basename(rel),
                'source_filename': filename or os.path.basename(rel),
                'size': int(os.path.getsize(abs_path) if os.path.exists(abs_path) else len(data)),
                'sha256': hashlib.sha256(data).hexdigest(),
                'imported_at': int(time.time()),
                'source': asset_source or 'chat_image_asset',
                'source_ref': str(source or '')[:500],
            }
            try:
                _sandbox_note_imported_files([row], messages or [])
            except Exception:
                pass
            try:
                src_kind = 'data_url' if str(source or '').startswith('data:image/') else ('storage_ref' if str(source or '').startswith('upload://') else ('url' if str(source or '').startswith(('http://', 'https://')) else ('file' if os.path.isabs(str(source or '')) else 'ref')))
                app_logger.info(
                    '[AGENT_STREAM_IMAGE_ASSET_IMPORTED] model=%s asset_source=%s path=%s bytes=%s sha256=%s mime=%s source_kind=%s source=%s',
                    model,
                    asset_source or 'chat_image_asset',
                    rel,
                    len(data),
                    hashlib.sha256(data).hexdigest()[:16],
                    mime_s or 'image/png',
                    src_kind,
                    str(source or '')[:240],
                )
            except Exception:
                pass
            return {'ok': True, 'file': row, 'path': rel, 'mime': mime_s or 'image/png'}
        except Exception as e:
            return {'ok': False, 'error': f'sandbox_image_write_failed:{type(e).__name__}: {e}'}

    def _agent_stream_import_image_row_to_sandbox(self, row: dict | None = None, *, fallback_url: str = '', index: int = 1, asset_source: str = 'chat_image_asset') -> dict:
        row_obj = dict(row or {}) if isinstance(row, dict) else {}
        tried_sources = self._agent_stream_image_asset_candidate_sources(row_obj, fallback_url=fallback_url)
        row_failures: list[str] = []
        for src in tried_sources:
            raw_bytes, raw_mime, raw_filename, resolved_source = self._agent_stream_image_source_to_bytes(src, row_obj)
            imported = self._agent_stream_import_image_bytes_to_sandbox(
                raw_bytes,
                raw_mime,
                raw_filename or str(row_obj.get('filename') or row_obj.get('title') or f'image_{index}'),
                str(row_obj.get('stable_image_id') or row_obj.get('image_id') or row_obj.get('role_image_id') or f'image_{index}'),
                resolved_source or src,
                asset_source=asset_source,
            )
            if bool(imported.get('ok')) and isinstance(imported.get('file'), dict):
                imported['source_used'] = str(resolved_source or src)[:500]
                imported['candidate_sources_tried'] = len(tried_sources)
                return imported
            if imported.get('error'):
                row_failures.append(str(imported.get('error') or '')[:160])
        label_text = str(row_obj.get('stable_image_id') or row_obj.get('image_id') or row_obj.get('role_image_id') or fallback_url or f'image_{index}')[:120]
        return {
            'ok': False,
            'error': row_failures[-1] if row_failures else 'source_not_resolved',
            'image_label': label_text,
            'candidate_sources_tried': len(tried_sources),
        }

    def _agent_stream_input_image_item_from_sandbox_file(self, file_row: dict | None = None) -> dict | None:
        messages = self.messages
        rel = str((file_row or {}).get('path') or '').strip()
        if not rel:
            return None
        try:
            abs_path, _rel = _sandbox_resolve_path(rel, messages or [], must_exist=True)
            sandbox_data_url, data_err, _data_bytes = _sandbox_data_url_for_image(abs_path)
            if data_err or not str(sandbox_data_url or '').startswith('data:image/'):
                return None
            return {
                'type': 'input_image',
                'image_url': sandbox_data_url,
                'detail': 'high',
                '_sandbox_path': rel,
                '_sandbox_source': 'chat_images',
            }
        except Exception:
            return None

    def _agent_stream_public_responses_content_part(self, part: dict | None = None, *, role: str = 'user') -> dict | None:
        """Return only fields accepted by the Responses API content schema."""
        if not isinstance(part, dict):
            return None
        role = str(role or 'user').strip().lower()
        typ = str(part.get('type') or '').strip().lower()
        if typ in {'input_text', 'output_text', 'text'}:
            text = str(part.get('text') or part.get('content') or part.get('output_text') or '').strip()
            if not text:
                return None
            if role == 'assistant':
                return {'type': 'output_text', 'text': text}
            return {'type': 'input_text', 'text': text}
        if typ == 'refusal':
            text = str(part.get('refusal') or part.get('text') or part.get('content') or '').strip()
            if not text:
                return None
            if role == 'assistant':
                return {'type': 'refusal', 'refusal': text}
            return {'type': 'input_text', 'text': text}
        if typ in {'input_image', 'image_url'}:
            if role == 'assistant':
                return None
            image_url = ''
            if isinstance(part.get('image_url'), dict):
                image_url = str((part.get('image_url') or {}).get('url') or '').strip()
            else:
                image_url = str(part.get('image_url') or part.get('url') or '').strip()
            file_id = str(part.get('file_id') or '').strip()
            detail = str(part.get('detail') or 'auto').strip() or 'auto'
            if detail not in {'auto', 'low', 'high'}:
                detail = 'auto'
            if not image_url and not file_id:
                return None
            out = {'type': 'input_image', 'detail': detail}
            if image_url:
                out['image_url'] = image_url
            if file_id:
                out['file_id'] = file_id
            return out
        return None

    def _agent_stream_public_responses_input_item(self, item: dict | None = None) -> dict | None:
        """Strip internal tracing keys before sending input items to /responses."""
        if not isinstance(item, dict):
            return None
        typ = str(item.get('type') or '').strip().lower()
        if typ == 'function_call_output':
            call_id = str(item.get('call_id') or '').strip()
            output = item.get('output')
            if not isinstance(output, str):
                try:
                    output = json.dumps(output, ensure_ascii=False, default=str)
                except Exception:
                    output = str(output or '')
            out = {'type': 'function_call_output', 'call_id': call_id, 'output': output}
            return out if call_id else None
        if typ == 'function_call':
            out = {
                'type': 'function_call',
                'name': str(item.get('name') or '').strip(),
                'arguments': str(item.get('arguments') or '').strip(),
                'call_id': str(item.get('call_id') or item.get('id') or '').strip(),
            }
            if item.get('id'):
                out['id'] = str(item.get('id') or '').strip()
            return out if out.get('name') and out.get('call_id') else None
        if typ == 'reasoning':
            encrypted_content = str(item.get('encrypted_content') or '').strip()
            if not encrypted_content:
                return None
            out = {
                'type': 'reasoning',
                'encrypted_content': encrypted_content,
            }
            item_id = str(item.get('id') or '').strip()
            if item_id:
                out['id'] = item_id
            status = str(item.get('status') or '').strip()
            if status:
                out['status'] = status
            for field_name in ('summary', 'content'):
                parts = item.get(field_name)
                if not isinstance(parts, list):
                    continue
                clean_parts = []
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    part_type = str(part.get('type') or '').strip()
                    text = str(part.get('text') or '').strip()
                    if part_type and text:
                        clean_parts.append({'type': part_type, 'text': text})
                if clean_parts:
                    out[field_name] = clean_parts
            out.setdefault('summary', [])
            return out
        if typ == 'message':
            role = str(item.get('role') or 'assistant').strip().lower()
            if role != 'assistant':
                return None
            parts = []
            for part in (item.get('content') or []):
                clean = self._agent_stream_public_responses_content_part(
                    part if isinstance(part, dict) else {'type': 'output_text', 'text': str(part or '')},
                    role='assistant',
                )
                if clean:
                    parts.append(clean)
            if not parts:
                return None
            out = {'type': 'message', 'role': 'assistant', 'content': parts}
            item_id = str(item.get('id') or '').strip()
            if item_id:
                out['id'] = item_id
            status = str(item.get('status') or '').strip()
            if status:
                out['status'] = status
            return out
        role = str(item.get('role') or '').strip().lower()
        if role not in {'system', 'user', 'assistant', 'developer'}:
            role = 'user'
        content = item.get('content')
        parts: list[dict] = []
        if isinstance(content, list):
            for part in content:
                clean = self._agent_stream_public_responses_content_part(part if isinstance(part, dict) else {'type': 'input_text', 'text': str(part or '')}, role=role)
                if clean:
                    parts.append(clean)
        elif isinstance(content, dict):
            clean = self._agent_stream_public_responses_content_part(content, role=role)
            if clean:
                parts.append(clean)
        else:
            text = str(content or item.get('text') or '').strip()
            if text:
                if role == 'assistant':
                    parts.append({'type': 'output_text', 'text': text})
                else:
                    parts.append({'type': 'input_text', 'text': text})
        return {'role': role, 'content': parts} if parts else None

    def _agent_stream_sanitize_responses_input_items_for_api(self, input_items: list | None = None) -> list[dict]:
        model = self.model
        out: list[dict] = []
        stripped = 0
        for item in (input_items or []):
            clean = self._agent_stream_public_responses_input_item(item if isinstance(item, dict) else {'role': 'user', 'content': str(item or '')})
            if clean:
                out.append(clean)
            if isinstance(item, dict):
                try:
                    if json.dumps(item, ensure_ascii=False, default=str) != json.dumps(clean, ensure_ascii=False, default=str):
                        stripped += 1
                except Exception:
                    pass
        if stripped:
            try:
                app_logger.info('[RESPONSES_NATIVE_INPUT_SANITIZED] model=%s items=%s stripped=%s', model, len(out), stripped)
            except Exception:
                pass
        return out

    def _agent_stream_eager_image_candidate_sources(self, row: dict | None = None, primary_url: str = '') -> list[str]:
        return self._candidate_sources_from_row(row, first_url=primary_url)

    def _agent_stream_input_image_item_from_asset_row(self, row: dict | None = None, *, primary_url: str = '', index: int = 1, asset_source: str = 'image_generation_reference') -> dict | None:
        imported = self._agent_stream_import_image_row_to_sandbox(row or {}, fallback_url=primary_url, index=index, asset_source=asset_source)
        if not bool(imported.get('ok')) or not isinstance(imported.get('file'), dict):
            return None
        item = self._agent_stream_input_image_item_from_sandbox_file(imported.get('file') or {})
        if isinstance(item, dict):
            item_meta = {
                'path': str((imported.get('file') or {}).get('path') or ''),
                'source_used': str(imported.get('source_used') or '')[:500],
                'candidate_sources_tried': int(imported.get('candidate_sources_tried') or 0),
            }
            item['_asset_import'] = item_meta
            return item
        return None

    def _agent_stream_append_eager_image_generation_input(self, input_items: list | None = None, *, task_type: str = '', selected_image_ids: list | None = None, reason: str = '') -> tuple[list, int]:
        model = self.model
        messages = self.messages
        items = list(input_items or [])
        rows = self.eager_image_rows_for_generation(messages or [], task_type=task_type, limit=8)
        selected_ids = [str(x or '').strip() for x in (selected_image_ids or []) if str(x or '').strip()] if isinstance(selected_image_ids, list) else []
        selected_count = 0
        if selected_ids:
            selected_rows = self.exact_selected_image_rows(selected_ids, rows, limit=8)
            if not selected_rows:
                selected_rows = self.direct_resolve_image_rows(selected_ids, rows, limit=8)
            if not selected_rows:
                # Extra guard for generated-image assets arriving through the
                # side-channel.  The model may correctly choose assistant_img_N
                # from the injected index while ordinary message-derived rows only
                # contain older user images.  Resolve against external assets once
                # more before treating the selected id as unavailable.
                try:
                    external_selected_rows = self.external_image_asset_candidate_rows(limit=24)
                    if external_selected_rows:
                        selected_rows = self.exact_selected_image_rows(selected_ids, external_selected_rows, limit=8)
                        if not selected_rows:
                            selected_rows = self.direct_resolve_image_rows(selected_ids, external_selected_rows, limit=8)
                except Exception:
                    selected_rows = selected_rows or []
            # When the model has selected concrete image ids, those ids are the
            # binding contract for the image_generation lane.  Do not append the
            # rest of the candidate pool, otherwise "the first generated image"
            # can accidentally send the first and second generated images together.
            if selected_rows:
                selected_count = len(selected_rows)
                rows = selected_rows[:8]
            else:
                # Explicit but unresolved ids should not silently degrade into
                # "attach everything"; the caller will skip image_generation if
                # no real image can be attached.
                rows = []
            try:
                app_logger.info(
                    '[RESPONSES_NATIVE_EAGER_IMAGE_SELECTED_MATCH] model=%s task_type=%s selected_ids=%s matched=%s candidate_after_order=%s',
                    model,
                    task_type,
                    json.dumps(selected_ids, ensure_ascii=False),
                    json.dumps(self.image_rows_log_payload(selected_rows, limit=8), ensure_ascii=False),
                    json.dumps(self.image_rows_log_payload(rows, limit=8), ensure_ascii=False),
                )
            except Exception:
                pass
        else:
            try:
                app_logger.info(
                    '[RESPONSES_NATIVE_EAGER_IMAGE_SELECTED_MATCH] model=%s task_type=%s selected_ids=[] matched=[] candidate_after_order=%s',
                    model,
                    task_type,
                    json.dumps(self.image_rows_log_payload(rows, limit=8), ensure_ascii=False),
                )
            except Exception:
                pass
        if not rows:
            return items, 0
        content: list[dict] = []
        rows_text = self.direct_image_rows_for_model(rows, limit=8)
        task_label = str(task_type or '').strip().lower() or 'image_generation'
        content.append({
            'type': 'input_text',
            'text': (
                '?????????\n'
                '???????????? Responses lane ?????/????/????????????\n'
                '?? native image_generation ??????????????????????????????????????\n'
                '???????' + task_label + '\n'
                + ('?????' + str(reason or '').strip()[:800] + '\n' if str(reason or '').strip() else '') +
                '??????\n' + rows_text
            )[:6000],
        })
        attached = 0
        failed: list[str] = []
        for idx, row in enumerate(rows[:8], 1):
            stable_id = str(row.get('current_user_image_id') or row.get('stable_image_id') or row.get('role_image_id') or row.get('image_id') or f'image_{idx}').strip()
            label_text = str(row.get('display_label') or row.get('role_label') or row.get('global_label') or '').strip()
            role_text = str(row.get('role') or row.get('source_role') or '').strip()
            content.append({'type': 'input_text', 'text': f'????? {idx}?id={stable_id}?label={label_text}?role={role_text}?'})
            primary = str(row.get('url') or row.get('image_url') or row.get('download_url') or '').strip()
            item = self._agent_stream_input_image_item_from_asset_row(row, primary_url=primary, index=idx, asset_source='image_generation_reference')
            if isinstance(item, dict) and (str(item.get('image_url') or '').strip() or str(item.get('file_id') or '').strip()):
                content.append(item)
                attached += 1
                try:
                    src_kind = 'file_id' if str(item.get('file_id') or '').strip() else ('data_url' if str(item.get('image_url') or '').strip().startswith('data:image/') else 'url')
                    import_meta = item.get('_asset_import') if isinstance(item.get('_asset_import'), dict) else {}
                    src_preview = str(import_meta.get('source_used') or item.get('file_id') or item.get('image_url') or '').strip()
                    if src_preview.lower().startswith('data:image/'):
                        src_preview = 'data:image/*;base64,...len=' + str(len(src_preview))
                    elif src_preview.lower().startswith('base64:'):
                        src_preview = 'base64:...len=' + str(len(src_preview))
                    elif len(src_preview) > 180:
                        src_preview = src_preview[:90] + '...' + src_preview[-40:]
                    app_logger.info(
                        '[RESPONSES_NATIVE_EAGER_IMAGE_INPUT_PICKED] model=%s task_type=%s idx=%s stable_id=%s label=%s role=%s source_kind=%s source=%s row=%s',
                        model,
                        task_type,
                        idx,
                        stable_id,
                        label_text,
                        role_text,
                        src_kind,
                        src_preview,
                        json.dumps(self.image_row_log_payload(row), ensure_ascii=False),
                    )
                except Exception:
                    pass
            else:
                failed.append(stable_id or primary or f'image_{idx}')
        if failed:
            try:
                app_logger.warning('[RESPONSES_NATIVE_EAGER_IMAGE_INPUT_BUILD_FAILED] model=%s failed=%s attached=%s task_type=%s', model, json.dumps(failed[:8], ensure_ascii=False), attached, task_type)
            except Exception:
                pass
        if attached <= 0:
            return items, 0
        items.append({'role': 'user', 'content': content})
        try:
            app_logger.info('[RESPONSES_NATIVE_EAGER_IMAGE_INPUT_ATTACHED] model=%s task_type=%s images=%s selected_priority=%s candidates=%s', model, task_type, attached, selected_count, len(rows or []))
        except Exception:
            pass
        return items, attached
