# Split from app3_parts/tools/file_registry_edit_tools_part.py.
# Purpose: sandbox file write, import, and replace-text tools.
# Loaded by file_registry_edit_tools_part.py via _exec_split_file(...), sharing app3.py globals.

_SANDBOX_SOURCE_CODE_DELIVERY_EXTS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.c', '.h', '.cpp', '.cc', '.cxx',
    '.hpp', '.java', '.go', '.rs', '.rb', '.php', '.sh', '.bash', '.ps1', '.sql',
}


def _sandbox_source_code_write_redirect(target: str = '', rel: str = '', *, append: bool = False) -> dict:
    ext = os.path.splitext(str(rel or target or ''))[1].lower()
    if append or ext not in _SANDBOX_SOURCE_CODE_DELIVERY_EXTS or os.path.isfile(str(target or '')):
        return {}
    return {
        'ok': False,
        'error': 'source_code_delivery_requires_sandbox_run',
        'path': str(rel or ''),
        'replacement_tool': 'sandbox_run',
        'instruction': 'Use sandbox_run with language="python" and code that writes this source file under /mnt/data, then call sandbox_publish_files. This preserves the real code/stdout/stderr execution trace.',
    }


def _sandbox_write_file_tool(args: dict | None = None, messages: list | None = None) -> dict:
    if not _sandbox_tools_enabled():
        return {'ok': False, 'error': 'sandbox_tools_disabled'}
    args = dict(args or {})
    content = str(args.get('content') if args.get('content') is not None else args.get('data') if args.get('data') is not None else '')
    try:
        max_chars = max(1000, min(int(app_getenv('SANDBOX_WRITE_MAX_CHARS', str(2 * 1024 * 1024)) or (2 * 1024 * 1024)), 20 * 1024 * 1024))
    except Exception:
        max_chars = 2 * 1024 * 1024
    if len(content) > max_chars:
        return {'ok': False, 'error': 'content_too_large', 'max_chars': max_chars}
    try:
        target, rel = _sandbox_resolve_path(args.get('path') or args.get('filename') or '', messages or [])
    except Exception as e:
        return {'ok': False, 'error': str(e or 'invalid_path')}
    if not rel:
        return {'ok': False, 'error': 'missing_file_path'}
    redirect = _sandbox_source_code_write_redirect(target, rel, append=bool(args.get('append')))
    if redirect:
        return redirect
    incoming = len(content.encode('utf-8', errors='replace'))
    quota_ok, quota_meta = _sandbox_quota_ok(messages or [], incoming_bytes=incoming, current_path=target, append=bool(args.get('append')))
    if not quota_ok:
        return quota_meta
    storage_ok, storage_meta = _sandbox_storage_quota_ok(messages or [], incoming_bytes=incoming, current_path=target, append=bool(args.get('append')))
    if not storage_ok:
        return storage_meta
    try:
        before_exists = os.path.isfile(target)
        before_text = _sandbox_read_text_for_audit(target) if before_exists else ''
        os.makedirs(os.path.dirname(target), exist_ok=True)
        mode = 'a' if bool(args.get('append')) else 'w'
        with open(target, mode, encoding='utf-8', newline='\n') as f:
            f.write(content)
        after_text = _sandbox_read_text_for_audit(target)
        audit = _sandbox_build_text_audit(rel, before_text, after_text, operation='sandbox_write_file', append=bool(args.get('append')), before_exists=before_exists)
        try:
            size = int(os.path.getsize(target))
        except Exception:
            size = len(content.encode('utf-8', errors='replace'))
        return {**_sandbox_result_base(messages or []), 'ok': True, 'path': rel, 'size': size, 'appended': bool(args.get('append')), 'file_edit_audit': audit, 'edit_audit': audit}
    except Exception as e:
        return {'ok': False, 'path': rel, 'error': f'{type(e).__name__}: {e}'}


def _sandbox_write_files_tool(args: dict | None = None, messages: list | None = None) -> dict:
    if not _sandbox_tools_enabled():
        return {'ok': False, 'error': 'sandbox_tools_disabled'}
    args = dict(args or {})
    rows = args.get('files')
    if rows is None:
        rows = args.get('items')
    if not isinstance(rows, list) or not rows:
        return {'ok': False, 'error': 'missing_files'}
    try:
        max_files = max(1, min(int(app_getenv('SANDBOX_WRITE_FILES_MAX_COUNT', '80') or 80), 200))
    except Exception:
        max_files = 80
    try:
        max_total_chars = max(1000, min(int(app_getenv('SANDBOX_WRITE_FILES_MAX_TOTAL_CHARS', str(4 * 1024 * 1024)) or (4 * 1024 * 1024)), 40 * 1024 * 1024))
    except Exception:
        max_total_chars = 4 * 1024 * 1024
    if len(rows) > max_files:
        return {'ok': False, 'error': 'too_many_files', 'max_files': max_files}

    normalized = []
    total_chars = 0
    for idx, item in enumerate(rows, 1):
        if not isinstance(item, dict):
            return {'ok': False, 'error': 'invalid_file_item', 'index': idx}
        path = str(item.get('path') or item.get('filename') or '').strip()
        if not path:
            return {'ok': False, 'error': 'missing_file_path', 'index': idx}
        content = str(item.get('content') if item.get('content') is not None else item.get('data') if item.get('data') is not None else '')
        total_chars += len(content)
        if total_chars > max_total_chars:
            return {'ok': False, 'error': 'batch_content_too_large', 'max_total_chars': max_total_chars}
        normalized.append({'path': path, 'content': content, 'append': bool(item.get('append'))})

    redirect_paths = []
    for item in normalized:
        try:
            target, rel = _sandbox_resolve_path(item.get('path') or '', messages or [])
        except Exception:
            continue
        if _sandbox_source_code_write_redirect(target, rel, append=bool(item.get('append'))):
            redirect_paths.append(rel)
    if redirect_paths:
        return {
            'ok': False,
            'error': 'source_code_delivery_requires_sandbox_run',
            'paths': redirect_paths,
            'replacement_tool': 'sandbox_run',
            'instruction': 'Use one sandbox_run call with language="python" and code that writes these source files under /mnt/data, then call sandbox_publish_files.',
        }

    written = []
    errors = []
    for idx, item in enumerate(normalized, 1):
        result = _sandbox_write_file_tool(item, messages=messages or [])
        row = {
            'index': idx,
            'ok': bool(result.get('ok')),
            'path': str(result.get('path') or item.get('path') or '')[:500],
            'size': int(result.get('size') or 0),
            'appended': bool(result.get('appended')),
        }
        if isinstance(result.get('file_edit_audit'), dict):
            row['file_edit_audit'] = dict(result.get('file_edit_audit') or {})
            row['edit_audit'] = dict(result.get('file_edit_audit') or {})
        if result.get('ok'):
            written.append(row)
        else:
            row['error'] = str(result.get('error') or 'write_failed')[:500]
            errors.append(row)
            if not bool(args.get('continue_on_error')):
                break

    file_edit_audits = [dict(x.get('file_edit_audit') or {}) for x in written if isinstance(x, dict) and isinstance(x.get('file_edit_audit'), dict)]
    return {
        **_sandbox_result_base(messages or []),
        'ok': bool(written) and not errors,
        'partial_ok': bool(written) and bool(errors),
        'written_count': len(written),
        'error_count': len(errors),
        'files': written,
        'errors': errors,
        'total_chars': total_chars,
        'file_edit_audits': file_edit_audits,
        'edit_audits': file_edit_audits,
    }


_SANDBOX_BINARY_ARTIFACT_EXTS = {
    '.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx',
    '.zip', '.7z', '.rar', '.tar', '.gz', '.tgz', '.bz2', '.xz',
    '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff',
    '.ico', '.jfif', '.jpe', '.dib', '.heic', '.heif',
}


def _sandbox_artifact_payload_bytes(artifact: dict | None = None) -> tuple[bytes | None, dict]:
    """把旧 artifact JSON 载荷规范化为首次落入 sandbox 的字节。"""
    row = dict(artifact or {}) if isinstance(artifact, dict) else {}
    original_filename = str(row.get('filename') or '').strip()
    relative_path = _safe_artifact_relative_path(original_filename)
    ext = os.path.splitext(relative_path or original_filename)[1].lower()
    if not relative_path:
        return None, {'error': 'missing_file_path'}
    if ext not in ALLOWED_EXT:
        return None, {'error': 'unsupported_artifact_extension', 'path': relative_path, 'extension': ext}

    mime = str(row.get('mime') or '').strip()
    data = row.get('data')
    encoding = _normalize_artifact_text_encoding(relative_path, mime, row.get('encoding'), data)
    if encoding == 'base64':
        raw = _artifact_try_decode_base64_bytes(data)
        if raw is None:
            return None, {'error': 'invalid_or_empty_base64_artifact', 'path': relative_path}
    else:
        if not _artifact_text_has_meaningful_content(data):
            return None, {'error': 'empty_text_artifact', 'path': relative_path}
        if ext in _SANDBOX_BINARY_ARTIFACT_EXTS:
            return None, {
                'error': 'binary_artifact_requires_base64',
                'path': relative_path,
                'instruction': 'Use sandbox_create_office_file or sandbox_run for binary output.',
            }
        try:
            raw, encoding = _artifact_encode_text_payload(str(data), encoding)
        except Exception as e:
            return None, {'error': f'artifact_text_encode_failed:{type(e).__name__}: {e}', 'path': relative_path}

    if ext == '.zip' and not _artifact_zip_has_meaningful_entries(raw):
        return None, {'error': 'empty_or_invalid_zip_artifact', 'path': relative_path}
    return bytes(raw), {
        'path': relative_path,
        'mime': mime,
        'encoding': encoding,
        'source_role': str(row.get('source_role') or row.get('sourceRole') or 'assistant_generated').strip() or 'assistant_generated',
    }


def _sandbox_unique_output_path(raw_path: str = '', messages: list | None = None, reserved: set | None = None) -> tuple[str, str]:
    """为兼容生成物保留独立 sandbox 源路径，避免不同版本共享同一来源。"""
    reserved_keys = reserved if isinstance(reserved, set) else set()
    target, rel = _sandbox_resolve_path(raw_path, messages or [])
    key = rel.replace('\\', '/').lower()
    if key not in reserved_keys and not os.path.exists(target):
        return target, rel

    rel_dir = os.path.dirname(rel).replace('\\', '/')
    basename = os.path.basename(rel)
    stem, ext = os.path.splitext(basename)
    stem = stem or 'file'
    for version in range(2, 1000):
        candidate_name = f'{stem}-v{version}{ext}'
        candidate_rel = (rel_dir.rstrip('/') + '/' + candidate_name).strip('/') if rel_dir else candidate_name
        candidate_target, normalized_rel = _sandbox_resolve_path(candidate_rel, messages or [])
        candidate_key = normalized_rel.replace('\\', '/').lower()
        if candidate_key not in reserved_keys and not os.path.exists(candidate_target):
            return candidate_target, normalized_rel
    raise RuntimeError('sandbox_output_version_limit_reached')


def _sandbox_stage_and_publish_artifacts(artifacts: list | None = None, messages: list | None = None, *, source: str = 'legacy_artifact_json') -> dict:
    """兼容旧 artifact JSON，但强制先写 sandbox，再走标准发布出口。"""
    if not _sandbox_tools_enabled():
        return {'ok': False, 'error': 'sandbox_tools_disabled', 'files': []}
    rows = [dict(x) for x in (artifacts or []) if isinstance(x, dict)]
    if not rows:
        return {'ok': False, 'error': 'empty_artifacts', 'files': []}

    try:
        max_files = max(1, min(int(app_getenv('SANDBOX_COMPAT_ARTIFACT_MAX_COUNT', '80') or 80), 200))
    except Exception:
        max_files = 80
    if len(rows) > max_files:
        return {'ok': False, 'error': 'too_many_artifacts', 'max_files': max_files, 'files': []}

    staged_paths: list[str] = []
    staged_path_keys: set[str] = set()
    staged_audits: list[dict] = []
    errors: list[dict] = []
    for index, row in enumerate(rows, 1):
        raw, meta = _sandbox_artifact_payload_bytes(row)
        if raw is None:
            errors.append({'index': index, **dict(meta or {})})
            continue
        rel_hint = str((meta or {}).get('path') or '').strip()
        try:
            target, rel = _sandbox_unique_output_path(rel_hint, messages or [], staged_path_keys)
        except Exception as e:
            errors.append({'index': index, 'path': rel_hint, 'error': f'invalid_path:{e}'})
            continue

        quota_ok, quota_meta = _sandbox_quota_ok(messages or [], incoming_bytes=len(raw), current_path=target, append=False)
        if not quota_ok:
            errors.append({'index': index, 'path': rel, **dict(quota_meta or {})})
            continue
        storage_ok, storage_meta = _sandbox_storage_quota_ok(messages or [], incoming_bytes=len(raw), current_path=target, append=False)
        if not storage_ok:
            errors.append({'index': index, 'path': rel, **dict(storage_meta or {})})
            continue

        tmp_path = target + '.tmp-' + uuid.uuid4().hex
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            before_snapshot = _sandbox_file_binary_snapshot(target)
            with open(tmp_path, 'wb') as f:
                f.write(raw)
            os.replace(tmp_path, target)
            after_snapshot = _sandbox_file_binary_snapshot(target)
            audit = _sandbox_build_binary_audit(
                rel,
                before_snapshot,
                after_snapshot,
                operation='sandbox_stage_legacy_artifact',
                fmt=os.path.splitext(rel)[1].lower().lstrip('.'),
            )
            staged_paths.append(rel)
            staged_path_keys.add(rel.replace('\\', '/').lower())
            if isinstance(audit, dict) and audit:
                staged_audits.append(audit)
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            errors.append({'index': index, 'path': rel, 'error': f'sandbox_stage_failed:{type(e).__name__}: {e}'})

    if not staged_paths:
        return {
            **_sandbox_result_base(messages or []),
            'ok': False,
            'error': 'sandbox_artifact_stage_failed',
            'files': [],
            'errors': errors,
            'source': str(source or 'legacy_artifact_json'),
        }

    publish_result = _sandbox_publish_files_tool({
        'paths': staged_paths,
        'file_edit_audits': staged_audits,
        'edit_audits': staged_audits,
        'force_zip': len(staged_paths) > 1,
    }, messages=messages or [])
    result = dict(publish_result or {}) if isinstance(publish_result, dict) else {}
    result['staged_paths'] = staged_paths
    result['staged_count'] = len(staged_paths)
    result['stage_errors'] = errors
    result['compatibility_bridge'] = True
    result['source'] = str(source or 'legacy_artifact_json')
    return result




def _sandbox_existing_record_path_or_bytes(rec: dict | None = None) -> tuple[str, bytes, str]:
    row = dict(rec or {})
    try:
        path = str(row.get('_path') or '').strip() or _history_file_resolve_path(row)
    except Exception:
        path = ''
    if path and os.path.isfile(path):
        return path, b'', ''
    registry = row.get('file_registry') if isinstance(row.get('file_registry'), dict) else {}
    storage_ref = str(row.get('storage_ref') or row.get('model_storage_ref') or registry.get('storage_ref') or registry.get('model_storage_ref') or '').strip()
    if storage_ref and callable(globals().get('_read_upload_storage_ref_bytes')):
        try:
            raw, _mime = _read_upload_storage_ref_bytes(storage_ref)
            if raw:
                return '', raw, ''
        except Exception as e:
            return '', b'', f'read_storage_ref_failed:{type(e).__name__}:{e}'
    return '', b'', 'source_path_not_found'


def _sandbox_resolve_existing_file_record(args: dict | None = None, messages: list | None = None) -> tuple[dict | None, str, list[dict]]:
    payload = dict(args or {})
    registry_file_id = str(payload.get('registry_file_id') or payload.get('registry_id') or payload.get('file_id') or payload.get('account_file_id') or payload.get('id') or '').strip()
    target_name = str(payload.get('target_filename') or payload.get('filename') or '').strip()
    source_role = str(payload.get('source_role') or payload.get('version_role') or '').strip()
    query = str(payload.get('query') or '').strip()
    if registry_file_id:
        try:
            records, _heavy = _collect_history_file_records(messages or [])
        except Exception:
            records = []
        matches: list[dict] = []
        for rec in records or []:
            if not isinstance(rec, dict):
                continue
            ids = {
                str(rec.get('registry_file_id') or '').strip(),
                str(rec.get('registry_id') or '').strip(),
                str(rec.get('file_id') or '').strip(),
                str(rec.get('account_file_id') or '').strip(),
                str(rec.get('id') or '').strip(),
            }
            if registry_file_id not in {x for x in ids if x}:
                continue
            if source_role and not _file_read_registry_role_filter(rec, source_role):
                continue
            row = dict(rec)
            try:
                row['_path'] = _history_file_resolve_path(row)
            except Exception:
                pass
            matches.append(row)
        if len(matches) == 1:
            return matches[0], '', matches
        if len(matches) > 1:
            ordered = sorted(matches, key=lambda row: float(row.get('order') or row.get('updated_at') or 0.0), reverse=True)
            return ordered[0], '', ordered
        rec, err, candidates = _file_read_resolve_account_registry_record(payload, target_name=target_name, source_role=source_role, query=query)
        return rec, err, candidates
    if target_name:
        if source_role:
            rec, err = _file_edit_resolve_record_by_role(messages or [], target_name, source_role)
        else:
            rec, err = _file_edit_resolve_target_record(messages or [], target_name)
        return rec, err, []
    return None, 'missing_file_selector', []


def _sandbox_import_one_file(rec: dict, *, destination: str = '', extract_archives: bool = False, messages: list | None = None) -> tuple[list[dict], str]:
    filename = os.path.basename(str(rec.get('filename') or rec.get('saved_filename') or 'uploaded-file').strip()) or 'uploaded-file'
    src_path, raw_bytes, read_err = _sandbox_existing_record_path_or_bytes(rec)
    if read_err:
        return [], read_err
    size = int(os.path.getsize(src_path)) if src_path and os.path.isfile(src_path) else len(raw_bytes)
    dest_raw = str(destination or '').strip()
    if dest_raw and (dest_raw.endswith('/') or dest_raw.endswith('\\')):
        dest_raw = dest_raw.rstrip('/\\') + '/' + filename
    if not dest_raw:
        dest_raw = 'uploads/' + filename
    try:
        dest_abs, dest_rel = _sandbox_resolve_path(dest_raw, messages or [])
    except Exception as e:
        return [], str(e or 'invalid_destination')
    quota_ok, quota_meta = _sandbox_quota_ok(messages or [], incoming_bytes=size, current_path=dest_abs, append=False)
    if not quota_ok:
        return [], str(quota_meta.get('error') or 'sandbox_disk_quota_exceeded')
    storage_ok, storage_meta = _sandbox_storage_quota_ok(messages or [], incoming_bytes=size, current_path=dest_abs, append=False)
    if not storage_ok:
        return [], str(storage_meta.get('error') or 'storage_quota_exceeded')
    try:
        os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
        if src_path:
            shutil.copy2(src_path, dest_abs)
        else:
            with open(dest_abs, 'wb') as f:
                f.write(raw_bytes)
    except Exception as e:
        return [], f'import_copy_failed:{type(e).__name__}:{e}'
    imported = [{
        'path': dest_rel,
        'mount_path': ('/mnt/data/' + dest_rel.strip('/')).rstrip('/'),
        'filename': filename,
        'source_filename': filename,
        'size': int(os.path.getsize(dest_abs)) if os.path.exists(dest_abs) else size,
        'imported_at': int(time.time()),
    }]
    if extract_archives and os.path.splitext(dest_rel)[1].lower() == '.zip':
        try:
            import zipfile
            extract_root_abs, extract_root_rel = _sandbox_resolve_path(os.path.splitext(dest_rel)[0].strip('/') or 'archive', messages or [])
            max_entries = max(1, min(int(app_getenv('SANDBOX_IMPORT_ZIP_MAX_ENTRIES', '1200') or 1200), 10000))
            max_total_uncompressed = max(1024 * 1024, min(int(app_getenv('SANDBOX_IMPORT_ZIP_MAX_TOTAL_BYTES', str(256 * 1024 * 1024)) or (256 * 1024 * 1024)), _sandbox_disk_max_bytes()))
            max_member_uncompressed = max(1024 * 1024, min(int(app_getenv('SANDBOX_IMPORT_ZIP_MAX_MEMBER_BYTES', str(80 * 1024 * 1024)) or (80 * 1024 * 1024)), _sandbox_disk_max_bytes()))
            max_compression_ratio = max(5.0, min(float(app_getenv('SANDBOX_IMPORT_ZIP_MAX_RATIO', '120') or 120), 1000.0))
            extracted = 0
            total_uncompressed = 0
            with zipfile.ZipFile(dest_abs) as zf:
                for info in zf.infolist():
                    if info.is_dir() or extracted >= max_entries:
                        continue
                    rel_member = str(info.filename or '').replace('\\', '/').lstrip('/')
                    if not rel_member or rel_member.startswith('/') or '..' in rel_member.split('/') or '\x00' in rel_member:
                        continue
                    mode = (int(getattr(info, 'external_attr', 0) or 0) >> 16) & 0o170000
                    if mode == 0o120000:
                        continue
                    declared_size = max(0, int(getattr(info, 'file_size', 0) or 0))
                    compressed_size = max(1, int(getattr(info, 'compress_size', 0) or 0))
                    if declared_size > max_member_uncompressed:
                        return imported, 'zip_member_too_large'
                    if total_uncompressed + declared_size > max_total_uncompressed:
                        return imported, 'zip_total_uncompressed_too_large'
                    if declared_size > (1024 * 1024) and (declared_size / compressed_size) > max_compression_ratio:
                        return imported, 'zip_compression_ratio_too_high'
                    member_abs, member_rel = _sandbox_resolve_path((extract_root_rel.rstrip('/') + '/' + rel_member).strip('/'), messages or [])
                    quota_ok, quota_meta = _sandbox_quota_ok(messages or [], incoming_bytes=declared_size, current_path=member_abs, append=False)
                    if not quota_ok:
                        return imported, str(quota_meta.get('error') or 'sandbox_disk_quota_exceeded')
                    storage_ok, storage_meta = _sandbox_storage_quota_ok(messages or [], incoming_bytes=declared_size, current_path=member_abs, append=False)
                    if not storage_ok:
                        return imported, str(storage_meta.get('error') or 'storage_quota_exceeded')
                    os.makedirs(os.path.dirname(member_abs), exist_ok=True)
                    written = 0
                    try:
                        with zf.open(info) as rf, open(member_abs, 'wb') as wf:
                            while True:
                                chunk = rf.read(1024 * 1024)
                                if not chunk:
                                    break
                                written += len(chunk)
                                if written > max_member_uncompressed or total_uncompressed + written > max_total_uncompressed:
                                    raise RuntimeError('zip_extract_size_limit_exceeded')
                                wf.write(chunk)
                    except Exception:
                        try:
                            if os.path.exists(member_abs):
                                os.remove(member_abs)
                        except Exception:
                            pass
                        raise
                    total_uncompressed += written
                    imported.append({
                        'path': member_rel,
                        'mount_path': ('/mnt/data/' + member_rel.strip('/')).rstrip('/'),
                        'filename': os.path.basename(member_rel),
                        'source_filename': filename,
                        'size': int(os.path.getsize(member_abs)) if os.path.exists(member_abs) else written,
                        'archive_source': dest_rel,
                        'imported_at': int(time.time()),
                    })
                    extracted += 1
        except Exception as e:
            return imported, f'zip_extract_failed:{type(e).__name__}:{e}'
    return imported, ''


def _sandbox_import_files_tool(args: dict | None = None, messages: list | None = None) -> dict:
    args = dict(args or {})
    if not _sandbox_tools_enabled():
        return {'ok': False, 'error': 'sandbox_tools_disabled'}
    selectors = args.get('files') or args.get('items') or []
    if isinstance(selectors, (str, dict)):
        selectors = [selectors]
    if not selectors and (args.get('target_filename') or args.get('registry_file_id') or args.get('file_id')):
        selectors = [args]
    if not selectors:
        try:
            records, _heavy = _collect_history_file_records(messages or [])
        except Exception:
            records = []
        try:
            current_selector = globals().get('_select_current_turn_file_records')
            current_records = current_selector(records, messages or []) if callable(current_selector) else []
        except Exception:
            current_records = []
        # No explicit selector means “import the active files for this turn”.
        # If current-turn attachments/selections exist, do not import every
        # historical generated file in the conversation.  Explicit filename/id
        # selectors still work for historical files.
        active_records = current_records or records
        selectors = [{'_record': r} for r in (active_records or []) if isinstance(r, dict)]
    imported: list[dict] = []
    errors: list[dict] = []
    extract_archives = bool(args.get('extract_archives') or args.get('extract_zip'))
    dest_base = str(args.get('destination') or args.get('dest') or '').strip()
    for idx, selector in enumerate(selectors if isinstance(selectors, list) else [], 1):
        if isinstance(selector, str):
            selector = {'target_filename': selector}
        if not isinstance(selector, dict):
            errors.append({'index': idx, 'error': 'invalid_file_selector'})
            continue
        rec = selector.get('_record') if isinstance(selector.get('_record'), dict) else None
        if rec is None:
            rec, err, candidates = _sandbox_resolve_existing_file_record(selector, messages or [])
            if not rec:
                errors.append({
                    'index': idx,
                    'error': err or 'source_file_not_found',
                    'registry_file_id': str(selector.get('registry_file_id') or selector.get('registry_id') or selector.get('file_id') or selector.get('account_file_id') or selector.get('id') or '').strip()[:160],
                    'filename': str(selector.get('target_filename') or selector.get('filename') or '').strip()[:240],
                    'candidates': [_file_read_registry_candidate_public(x) for x in (candidates or [])[:8]],
                })
                if not bool(args.get('continue_on_error')):
                    break
                continue
        destination = str(selector.get('destination') or selector.get('dest') or '').strip()
        if not destination and dest_base:
            destination = dest_base.rstrip('/\\') + '/' + os.path.basename(str(rec.get('filename') or rec.get('saved_filename') or 'file').strip())
        rows, err = _sandbox_import_one_file(dict(rec), destination=destination, extract_archives=extract_archives, messages=messages or [])
        imported.extend(rows)
        if err:
            errors.append({'index': idx, 'error': err, 'filename': str((rec or {}).get('filename') or (rec or {}).get('saved_filename') or '')[:240]})
            if not bool(args.get('continue_on_error')):
                break
    _sandbox_note_imported_files(imported, messages or [])
    return {
        **_sandbox_result_base(messages or []),
        'ok': bool(imported) and not errors,
        'partial_ok': bool(imported) and bool(errors),
        'imported_count': len(imported),
        'error_count': len(errors),
        'files': imported,
        'errors': errors,
        'extract_archives': extract_archives,
    }


def _sandbox_replace_text_tool(args: dict | None = None, messages: list | None = None) -> dict:
    if not _sandbox_tools_enabled():
        return {'ok': False, 'error': 'sandbox_tools_disabled'}
    args = dict(args or {})
    exact_old = str(args.get('exact_old') or args.get('old_text') or '')
    new_text = str(args.get('new_text') if args.get('new_text') is not None else args.get('replacement') if args.get('replacement') is not None else '')
    if not exact_old:
        return {'ok': False, 'error': 'empty_exact_old'}
    try:
        target, rel = _sandbox_resolve_path(args.get('path') or args.get('filename') or '', messages or [], must_exist=True)
    except FileNotFoundError:
        return {'ok': False, 'error': 'file_not_found'}
    except Exception as e:
        return {'ok': False, 'error': str(e or 'invalid_path')}
    if not os.path.isfile(target):
        return {'ok': False, 'error': 'not_a_file', 'path': rel}
    try:
        with open(target, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
        hits = source.count(exact_old)
        if hits <= 0:
            return {'ok': False, 'error': 'exact_old_not_found', 'path': rel}
        raw_count = args.get('count')
        try:
            count = int(raw_count) if raw_count is not None else 1
        except Exception:
            count = 1
        if count <= 0:
            count = hits
        changed = source.replace(exact_old, new_text, count)
        if changed == source:
            return {'ok': False, 'error': 'no_change', 'path': rel, 'matches': hits}
        incoming = len(changed.encode('utf-8', errors='replace'))
        quota_ok, quota_meta = _sandbox_quota_ok(messages or [], incoming_bytes=incoming, current_path=target, append=False)
        if not quota_ok:
            return quota_meta
        storage_ok, storage_meta = _sandbox_storage_quota_ok(messages or [], incoming_bytes=incoming, current_path=target, append=False)
        if not storage_ok:
            return storage_meta
        with open(target, 'w', encoding='utf-8', newline='\n') as f:
            f.write(changed)
        audit = _sandbox_build_text_audit(rel, source, changed, operation='sandbox_replace_text', append=False, before_exists=True)
        return {
            **_sandbox_result_base(messages or []),
            'ok': True,
            'path': rel,
            'matches': hits,
            'replaced': min(hits, count),
            'size': int(os.path.getsize(target)) if os.path.exists(target) else len(changed.encode('utf-8', errors='replace')),
            'file_edit_audit': audit,
            'edit_audit': audit,
        }
    except Exception as e:
        return {'ok': False, 'path': rel, 'error': f'{type(e).__name__}: {e}'}
