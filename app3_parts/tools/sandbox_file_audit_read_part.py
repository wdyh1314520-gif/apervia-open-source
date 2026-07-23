# Split from app3_parts/tools/file_registry_edit_tools_part.py.
# Purpose: sandbox file audit snapshots and read-file tool entry point.
# Loaded by file_registry_edit_tools_part.py via _exec_split_file(...), sharing app3.py globals.

def _sandbox_rel_key(value: str = '') -> str:
    return str(value or '').strip().replace('\\', '/').lstrip('/').lower()


def _sandbox_read_text_for_audit(path: str = '') -> str:
    if not path or not os.path.isfile(path):
        return ''
    try:
        max_bytes = max(4096, min(int(app_getenv('SANDBOX_AUDIT_TEXT_MAX_BYTES', str(20 * 1024 * 1024)) or (20 * 1024 * 1024)), 80 * 1024 * 1024))
    except Exception:
        max_bytes = 20 * 1024 * 1024
    try:
        with open(path, 'rb') as f:
            raw = f.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
        try:
            return raw.decode('utf-8', errors='replace')
        except Exception:
            return read_text_file(raw) if callable(globals().get('read_text_file')) else raw.decode('utf-8', errors='replace')
    except Exception:
        return ''


def _sandbox_build_text_audit(rel_path: str = '', before: str = '', after: str = '', *, operation: str = '', append: bool = False, before_exists: bool | None = None) -> dict:
    rel = str(rel_path or '').strip().replace('\\', '/')
    audit = _file_edit_build_audit_record(
        target_filename=os.path.basename(rel) or rel or 'file',
        output_filename=rel,
        before=str(before or ''),
        after=str(after or ''),
        changes=[{'operation': str(operation or 'sandbox_write'), 'path': rel, 'append': bool(append)}],
        reason=str(operation or 'sandbox_write'),
        basis_filename=os.path.basename(rel) or rel or 'file',
        requested_target_filename=os.path.basename(rel) or rel or 'file',
    )
    audit['operation'] = str(operation or 'sandbox_write')
    audit['sandbox_path'] = rel
    audit['append'] = bool(append)
    audit['created'] = not bool(before_exists) if before_exists is not None else not bool(before)
    return _file_edit_compact_audit_for_payload(audit, include_diff=True)


def _sandbox_sha256_bytes(raw: bytes = b'') -> str:
    try:
        return hashlib.sha256(bytes(raw or b'')).hexdigest()
    except Exception:
        return ''


def _sandbox_file_binary_snapshot(path: str = '') -> dict:
    if not path or not os.path.isfile(path):
        return {'exists': False, 'size': 0, 'sha256': ''}
    try:
        with open(path, 'rb') as f:
            raw = f.read()
        return {'exists': True, 'size': len(raw), 'sha256': _sandbox_sha256_bytes(raw)}
    except Exception:
        try:
            return {'exists': True, 'size': int(os.path.getsize(path)), 'sha256': ''}
        except Exception:
            return {'exists': True, 'size': 0, 'sha256': ''}


def _sandbox_build_binary_audit(rel_path: str = '', before: dict | None = None, after: dict | None = None, *, operation: str = '', fmt: str = '', lineage: dict | None = None) -> dict:
    rel = str(rel_path or '').strip().replace('\\', '/')
    before = dict(before or {})
    after = dict(after or {})
    old_hash = str(before.get('sha256') or '').strip()
    new_hash = str(after.get('sha256') or '').strip()
    created_at = _fmt_ts(_utc_ts()) if '_fmt_ts' in globals() else ''
    lineage_meta = dict(lineage or {}) if isinstance(lineage, dict) else {}
    basis_filename = str(lineage_meta.get('basis_filename') or '').strip() or os.path.basename(rel) or rel or 'file'
    target_filename = os.path.basename(rel) or rel or 'file'
    lineage_key = str(lineage_meta.get('lineage_key') or '').strip()
    if not lineage_key:
        lineage_key = _file_edit_lineage_key_from_record(
            None,
            basis_filename=basis_filename,
            target_filename=target_filename,
            output_filename=rel,
            audit={'basis_sha256': old_hash, 'old_sha256': old_hash},
        )
    task_id = _file_edit_make_task_job_id()
    audit = {
        '_kind': 'file_edit_audit',
        'audit_id': _file_edit_make_audit_id(
            task_job_id=task_id,
            lineage_key=lineage_key,
            target_filename=target_filename,
            basis_filename=basis_filename,
            output_filename=rel,
            old_sha256=old_hash,
            new_sha256=new_hash,
            created_at=created_at,
        ),
        'task_job_id': task_id,
        'lineage_key': lineage_key,
        'target_filename': target_filename,
        'requested_target_filename': target_filename,
        'basis_filename': basis_filename,
        'output_filename': rel,
        'sandbox_path': rel,
        'operation': str(operation or 'sandbox_create_file'),
        'format': str(fmt or '').strip().lower(),
        'binary': True,
        'created': not bool(before.get('exists')),
        'changed': bool((old_hash or before.get('size')) != (new_hash or after.get('size'))),
        'old_sha256': old_hash,
        'new_sha256': new_hash,
        'basis_sha256': old_hash,
        'lineage_sha256': old_hash,
        'old_bytes': int(before.get('size') or 0),
        'new_bytes': int(after.get('size') or 0),
        'parent_file_ids': [str(x or '').strip() for x in (lineage_meta.get('parent_file_ids') or []) if str(x or '').strip()][:20],
        'source_file_ids': [str(x or '').strip() for x in (lineage_meta.get('source_file_ids') or []) if str(x or '').strip()][:20],
        'compared_file_ids': [str(x or '').strip() for x in (lineage_meta.get('compared_file_ids') or []) if str(x or '').strip()][:20],
        'source_paths': [str(x or '').strip() for x in ((lineage_meta.get('source_paths') or []) if isinstance(lineage_meta.get('source_paths'), list) else []) if str(x or '').strip()][:20] or ([str(lineage_meta.get('parent_path') or '').strip()] if str(lineage_meta.get('parent_path') or '').strip() else []),
        'compared_paths': [str(x or '').strip() for x in ((lineage_meta.get('compared_paths') or []) if isinstance(lineage_meta.get('compared_paths'), list) else []) if str(x or '').strip()][:20],
        'compared_filenames': [str(x or '').strip() for x in ((lineage_meta.get('compared_filenames') or []) if isinstance(lineage_meta.get('compared_filenames'), list) else []) if str(x or '').strip()][:20],
        'file_role': str(lineage_meta.get('role') or '').strip(),
        'lineage_strength': str(lineage_meta.get('lineage_strength') or '').strip(),
        'diff_summary': [
            f"{str(operation or 'sandbox_create_file')}: {rel}",
            f"bytes {int(before.get('size') or 0)} -> {int(after.get('size') or 0)}",
        ],
        'diff': '',
        'verification': {'passed': True, 'source': 'sandbox_binary_audit'},
        'created_at': created_at,
    }
    return _file_edit_compact_audit_for_payload(audit, include_diff=False)


def _sandbox_collect_file_edit_audits_from_obj(obj, out: list[dict], *, depth: int = 0) -> None:
    if depth > 4:
        return
    if isinstance(obj, dict):
        if str(obj.get('_kind') or '').strip() == 'file_edit_audit' or obj.get('old_sha256') or obj.get('new_sha256') or obj.get('diff_summary'):
            compact = _file_edit_compact_audit_for_payload(obj, include_diff=True)
            if compact:
                out.append(compact)
        for key in ('file_edit_audit', 'edit_audit'):
            if isinstance(obj.get(key), dict):
                _sandbox_collect_file_edit_audits_from_obj(obj.get(key), out, depth=depth + 1)
        for key in ('file_edit_audits', 'edit_audits', 'files', 'delivery_files', 'source_files'):
            if isinstance(obj.get(key), list):
                _sandbox_collect_file_edit_audits_from_obj(obj.get(key), out, depth=depth + 1)
    elif isinstance(obj, list):
        for item in obj[:200]:
            _sandbox_collect_file_edit_audits_from_obj(item, out, depth=depth + 1)


def _sandbox_file_edit_audit_map(args: dict | None = None, messages: list | None = None) -> dict[str, dict]:
    audits: list[dict] = []
    _sandbox_collect_file_edit_audits_from_obj((args or {}).get('file_edit_audits'), audits)
    _sandbox_collect_file_edit_audits_from_obj((args or {}).get('edit_audits'), audits)
    for m in (messages or [])[-80:]:
        if not isinstance(m, dict):
            continue
        _sandbox_collect_file_edit_audits_from_obj(m.get('file_edit_audit'), audits)
        content = m.get('content')
        if isinstance(content, str) and ('file_edit_audit' in content or 'diff_summary' in content or 'old_sha256' in content):
            try:
                _sandbox_collect_file_edit_audits_from_obj(json.loads(content), audits)
            except Exception:
                pass
    out: dict[str, dict] = {}
    seen: set[str] = set()
    for audit in audits:
        if not isinstance(audit, dict):
            continue
        aid = str(audit.get('audit_id') or '').strip()
        identity = aid or '|'.join([str(audit.get('output_filename') or ''), str(audit.get('new_sha256') or '')])
        if identity in seen:
            continue
        seen.add(identity)
        for key in ('sandbox_path', 'output_filename', 'target_filename', 'requested_target_filename'):
            rel = _sandbox_rel_key(audit.get(key))
            if rel and rel not in out:
                out[rel] = dict(audit)
    return out


def _sandbox_file_text_from_bytes(raw: bytes, filename: str = '', *, max_chars: int = 60000) -> tuple[str, str, bool, str]:
    """Read sandbox file bytes through the single /mnt/data plane."""
    ext = os.path.splitext(str(filename or ''))[1].lower()
    try:
        max_chars = max(1000, min(int(max_chars or 60000), 500000))
    except Exception:
        max_chars = 60000
    try:
        if ext == '.pdf':
            return str(read_pdf(raw) or '')[:max_chars], 'pdf_text', True, ''
        if ext == '.docx':
            return str(read_docx(raw) or '')[:max_chars], 'docx_text', True, ''
        if ext == '.doc':
            return str(read_doc(raw) or '')[:max_chars], 'doc_text', True, ''
        if ext == '.xlsx':
            return str(read_xlsx(raw) or '')[:max_chars], 'xlsx_text', True, ''
        if ext == '.pptx':
            return str(read_pptx(raw) or '')[:max_chars], 'pptx_text', True, ''
        if ext == '.zip':
            return str(read_archive_bundle(raw, ext, max_total_chars=max_chars) or '')[:max_chars], 'zip_text_bundle', True, ''
        return str(read_text_file(raw) or '')[:max_chars], 'text', False, ''
    except Exception as e:
        if ext in {'.pdf', '.docx', '.doc', '.xlsx', '.pptx', '.zip'}:
            return '', f'{ext.lstrip(".")}_text', True, f'{type(e).__name__}: {e}'
        try:
            return str(read_text_file(raw) or '')[:max_chars], 'text_fallback', False, ''
        except Exception as e2:
            return '', 'text', False, f'{type(e2).__name__}: {e2}'


def _sandbox_read_visual_hint(ext: str, text: str, diagnostics: dict | None = None) -> str:
    diag = diagnostics if isinstance(diagnostics, dict) else {}
    ext_l = str(ext or '').lower()
    policy = _sandbox_file_evidence_policy(ext_l, diagnostics=diag)
    if bool(diag.get('requires_visual_review')) and policy.get('kind') != 'spreadsheet':
        signals = ', '.join([str(x or '') for x in (diag.get('quality_signals') or [])[:4] if str(x or '').strip()])
        suffix = f' Detected signals: {signals}.' if signals else ''
        return 'This non-spreadsheet document has text-layer/OOXML signals that formulas, symbols, tables, or embedded vector images may be missing from plain text. Add sandbox_analyze_file_images when the user question depends on rendered page/visual evidence.' + suffix
    if str(text or '').strip():
        return ''
    if policy.get('kind') == 'spreadsheet':
        return 'sandbox_read_file attempted structured spreadsheet text. Use sandbox_analyze_file_images only for explicit chart/layout/format/page-rendering questions.'
    if ext_l in {'.pdf', '.docx', '.pptx'}:
        return 'sandbox_read_file only reads text layers/structured text. For screenshots, charts, diagrams, UI, scanned pages, or page layout inside this file, call sandbox_analyze_file_images when visually relevant.'
    if ext_l in {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff'}:
        return 'This is an image file. Import it into /mnt/data, then call sandbox_analyze_file_images for visual/OCR evidence.'
    return ''


def _sandbox_read_file_tool(args: dict | None = None, messages: list | None = None) -> dict:
    if not _sandbox_tools_enabled():
        return {'ok': False, 'error': 'sandbox_tools_disabled'}
    args = dict(args or {})
    try:
        target, rel = _sandbox_resolve_path(args.get('path') or args.get('filename') or '', messages or [], must_exist=True)
    except FileNotFoundError:
        return {'ok': False, 'error': 'file_not_found'}
    except Exception as e:
        return {'ok': False, 'error': str(e or 'invalid_path')}
    if not os.path.isfile(target):
        return {'ok': False, 'error': 'not_a_file', 'path': rel}
    try:
        max_chars = max(1000, min(int(args.get('max_chars') or 60000), 500000))
    except Exception:
        max_chars = 60000
    try:
        ext = os.path.splitext(rel)[1].lower()
        binary_extract_exts = {'.pdf', '.docx', '.doc', '.xlsx', '.pptx', '.zip'}
        max_bytes = max(max_chars * 4, 4096)
        if ext in binary_extract_exts:
            try:
                max_bytes = max(max_bytes, min(max(4096, os.path.getsize(target)), 40 * 1024 * 1024))
            except Exception:
                pass
        with open(target, 'rb') as f:
            raw = f.read(max_bytes + 1)
        truncated_bytes = len(raw) > max_bytes
        if truncated_bytes:
            raw = raw[:max_bytes]
        text, reader_mode, binary_source, extract_error = _sandbox_file_text_from_bytes(raw, rel, max_chars=max_chars)
        if extract_error:
            return {**_sandbox_result_base(messages or []), 'ok': False, 'error': 'sandbox_file_extract_failed', 'path': rel, 'reader_mode': reader_mode, 'detail': extract_error}
        truncated_chars = len(text) > max_chars
        if truncated_chars:
            text = text[:max_chars]
        try:
            size = int(os.path.getsize(target))
        except Exception:
            size = len(raw)
        document_diagnostics = _sandbox_document_text_diagnostics(raw, rel, text) if ext in {'.docx'} else {}
        document_diagnostic_summary = _sandbox_document_diagnostic_summary(document_diagnostics)
        payload = {
            **_sandbox_result_base(messages or []),
            'ok': True,
            'path': rel,
            'size': size,
            'content': text,
            'chars': len(text),
            'truncated': bool(truncated_bytes or truncated_chars),
            'reader_mode': reader_mode,
            'binary_source': bool(binary_source),
            'visual_hint': _sandbox_read_visual_hint(ext, text, document_diagnostics),
            'document_diagnostics': document_diagnostics,
            'document_diagnostic_summary': document_diagnostic_summary,
        }
        return _attach_evidence_ledger_event('sandbox_read_file', payload, args)
    except Exception as e:
        return {'ok': False, 'path': rel, 'error': f'{type(e).__name__}: {e}'}
