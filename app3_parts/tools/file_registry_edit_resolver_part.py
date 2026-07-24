# file edit target resolver helpers.

# ==============================
# Safe complete-file editing for existing uploaded/generated files
# ==============================

def _file_edit_max_source_bytes() -> int:
    try:
        return max(64 * 1024, int(app_getenv('FILE_EDIT_MAX_SOURCE_BYTES', str(5 * 1024 * 1024)) or (5 * 1024 * 1024)))
    except Exception:
        return 5 * 1024 * 1024


def _file_edit_last_user_text(messages: list | None = None) -> str:
    for m in reversed(messages or []):
        if isinstance(m, dict) and str(m.get('role') or '').strip() == 'user':
            return _msg_content_text(m.get('content')).strip()
    return ''


def _file_edit_record_key(rec: dict | None = None) -> str:
    row = dict(rec or {})
    return '|'.join([
        str(row.get('source') or '').strip().lower(),
        str(row.get('namespace') or '').strip().lower(),
        str(row.get('filename') or '').strip().lower(),
        str(row.get('saved_filename') or '').strip().lower(),
        str(row.get('download_url') or row.get('url') or row.get('view_url') or '').strip(),
    ])


def _file_edit_candidate_names(rec: dict | None = None) -> set[str]:
    row = dict(rec or {})
    vals = {
        str(row.get('filename') or '').strip(),
        str(row.get('saved_filename') or '').strip(),
        os.path.basename(str(row.get('filename') or '').strip()),
        os.path.basename(str(row.get('saved_filename') or '').strip()),
    }

    # Generated edited files keep lineage aliases back to the source file.
    # This prevents follow-up edits from resolving the original upload after a
    # newer generated version already exists in the same conversation.
    edit_audit = row.get('edit_audit') if isinstance(row.get('edit_audit'), dict) else {}
    edit_details = row.get('edit_details') if isinstance(row.get('edit_details'), dict) else {}
    details_audit = edit_details.get('audit') if isinstance(edit_details.get('audit'), dict) else {}
    for audit in (edit_audit, details_audit):
        vals.add(str(audit.get('target_filename') or '').strip())
        vals.add(os.path.basename(str(audit.get('target_filename') or '').strip()))
        vals.add(str(audit.get('requested_target_filename') or '').strip())
        vals.add(os.path.basename(str(audit.get('requested_target_filename') or '').strip()))
        vals.add(str(audit.get('basis_filename') or '').strip())
        vals.add(os.path.basename(str(audit.get('basis_filename') or '').strip()))
        vals.add(str(audit.get('output_filename') or '').strip())
        vals.add(os.path.basename(str(audit.get('output_filename') or '').strip()))

    edited_from = row.get('edited_from') if isinstance(row.get('edited_from'), dict) else {}
    vals.add(str(edited_from.get('filename') or '').strip())
    vals.add(os.path.basename(str(edited_from.get('filename') or '').strip()))
    vals.add(str(edited_from.get('basis_filename') or '').strip())
    vals.add(os.path.basename(str(edited_from.get('basis_filename') or '').strip()))
    vals.add(str(edited_from.get('requested_target_filename') or '').strip())
    vals.add(os.path.basename(str(edited_from.get('requested_target_filename') or '').strip()))

    expanded = set()
    for v in vals:
        if not v:
            continue
        expanded.add(str(v).lower())
        try:
            expanded.update(_file_delivery_filename_alias_values(str(v)))
        except Exception:
            pass
    return {v.lower() for v in expanded if v}



def _file_read_registry_owner_key() -> str:
    """Current account key for on-demand account file lookup.

    This is only used after current-conversation file resolution fails or when a
    concrete registry_file_id is supplied.  It does not inject account files into
    the normal current-session file context.
    """
    fn = globals().get('_storage_quota_owner_key')
    if callable(fn):
        try:
            return str(fn() or '').strip().lower()
        except Exception:
            pass
    return ''


def _file_read_registry_owner_matches(rec: dict | None = None, owner_key: str = '') -> bool:
    row = dict(rec or {})
    owner = str(owner_key or '').strip().lower()
    rec_owner = str(row.get('owner_key') or row.get('owner') or row.get('owner_email') or '').strip().lower()
    if owner and owner != 'anonymous':
        return bool(rec_owner and rec_owner == owner)
    return rec_owner in {'', 'anonymous'}


def _file_read_registry_record_to_history_record(rec: dict | None = None) -> dict:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    filename = str(row.get('filename') or row.get('saved_filename') or '').strip()
    saved = str(row.get('saved_filename') or filename).strip()
    namespace = str(row.get('namespace') or '').strip() or ('generated' if str(row.get('source') or '').strip().lower() == 'generated' else 'uploads')
    source = str(row.get('source') or '').strip() or ('generated' if namespace == 'generated' else 'upload')
    role = str(row.get('source_role') or row.get('version_role') or '').strip()
    if not role:
        role = 'assistant_generated' if (namespace == 'generated' or source == 'generated') else 'user_upload'
    out = {
        'source': source,
        'source_role': role,
        'file_id': str(row.get('file_id') or '').strip(),
        'registry_file_id': str(row.get('file_id') or '').strip(),
        'filename': filename,
        'saved_filename': saved,
        'ext': str(row.get('ext') or _history_file_ext(filename or saved) or '').strip().lower(),
        'size': int(row.get('size') or row.get('size_bytes') or 0),
        'url': str(row.get('url') or row.get('download_url') or '').strip(),
        'view_url': str(row.get('view_url') or '').strip(),
        'download_url': str(row.get('download_url') or row.get('url') or '').strip(),
        'namespace': namespace,
        'scope': str(row.get('scope') or '').strip(),
        'summary': str(row.get('summary') or '').strip(),
        'symbols': row.get('symbols') if isinstance(row.get('symbols'), list) else [],
        'note': 'account_registry_file',
        'inline_text': '',
        'full_text_ref': str(row.get('full_text_ref') or '').strip(),
        'full_text_available': bool(row.get('full_text_available') or row.get('full_text_ref')),
        'full_text_chars': int(row.get('full_text_chars') or row.get('parsed_chars') or 0),
        'full_text_lines': int(row.get('full_text_lines') or row.get('parsed_lines') or 0),
        'storage_ref': str(row.get('storage_ref') or '').strip(),
        'owner_key': str(row.get('owner_key') or '').strip().lower(),
        'order': float(row.get('updated_at') or row.get('created_at') or 0.0),
        'registry_updated_at': float(row.get('updated_at') or 0.0),
        'registry_created_at': float(row.get('created_at') or 0.0),
        'from_account_registry': True,
    }
    try:
        path = _history_file_resolve_path(out)
    except Exception:
        path = ''
    if path:
        out['_path'] = path
    return out


def _file_read_registry_records_snapshot() -> list[dict]:
    try:
        if callable(globals().get('_file_registry_load')):
            _file_registry_load()
    except Exception:
        pass
    try:
        with _FILE_REGISTRY_LOCK:
            rows = [dict(v or {}) for v in (_FILE_REGISTRY_STATE.get('files') or {}).values() if isinstance(v, dict)]
    except Exception:
        rows = []
    return rows


def _file_read_registry_role_filter(rec: dict | None = None, source_role: str = '') -> bool:
    role = str(source_role or '').strip().lower()
    if role in {'', 'auto', 'default', 'account_recent', 'recent'}:
        return True
    row = dict(rec or {})
    generated = _file_edit_record_is_generated(row)
    if role in {'user_upload', 'upload', 'original', 'original_upload'}:
        return not generated
    if role in {'assistant_generated', 'generated', 'latest_generated', 'edited_output', 'assistant_edited', 'assistant_file', 'assistant'}:
        if not generated:
            return False
        if role in {'edited_output', 'assistant_edited'}:
            return bool(row.get('edit_audit') or row.get('edit_details') or row.get('edited_from'))
        return True
    return True


def _file_read_registry_candidates(*, registry_file_id: str = '', target_filename: str = '', source_role: str = '', query: str = '', limit: int = 8) -> list[dict]:
    owner = _file_read_registry_owner_key()
    rid = str(registry_file_id or '').strip()
    target_raw = str(target_filename or '').strip()
    target = os.path.basename(target_raw).strip().lower()
    q = str(query or '').strip()
    try:
        limit = max(1, min(int(limit or 8), 20))
    except Exception:
        limit = 8
    role = str(source_role or '').strip().lower()
    has_anchor = bool(rid or target or q or role in {'assistant_generated', 'generated', 'latest_generated', 'edited_output', 'assistant_edited', 'assistant_file', 'user_upload', 'upload', 'original', 'original_upload'})
    if not has_anchor:
        return []
    terms = []
    try:
        terms = _history_file_query_terms(' '.join(x for x in (target_raw, q) if x))
    except Exception:
        terms = []
    scored: list[tuple[float, dict]] = []
    for raw in _file_read_registry_records_snapshot():
        if not _file_read_registry_owner_matches(raw, owner):
            continue
        rec = _file_read_registry_record_to_history_record(raw)
        filename = str(rec.get('filename') or rec.get('saved_filename') or '').strip()
        saved = str(rec.get('saved_filename') or '').strip()
        if not filename and not saved:
            continue
        if rid and rid not in {str(rec.get('registry_file_id') or ''), str(rec.get('file_id') or '')}:
            continue
        if not _file_read_registry_role_filter(rec, source_role):
            continue
        readable = bool(str(rec.get('_path') or '').strip() or str(rec.get('full_text_ref') or '').strip())
        if not readable:
            continue
        names = _file_edit_candidate_names(rec)
        filename_l = filename.lower()
        saved_l = saved.lower()
        ext_l = str(rec.get('ext') or '').strip().lower().lstrip('.')
        if target:
            target_l = target.lstrip('.')
            if target not in names and target not in {filename_l, saved_l} and target not in filename_l and target not in saved_l and target_l != ext_l:
                continue
        hay = '\n'.join([
            filename_l,
            saved_l,
            str(rec.get('summary') or '').lower(),
            str(rec.get('source') or '').lower(),
            str(rec.get('source_role') or '').lower(),
        ])
        score = 0.0
        if rid:
            score += 10000.0
        if target:
            if target in {filename_l, saved_l}:
                score += 300.0
            elif target in names:
                score += 220.0
            elif target in filename_l or target in saved_l:
                score += 120.0
            elif target.lstrip('.') == ext_l:
                score += 70.0
        for term in terms:
            t = str(term or '').strip().lower()
            if not t:
                continue
            if t in {filename_l, saved_l}:
                score += 90.0
            elif t in filename_l or t in saved_l:
                score += 45.0
            elif t in hay:
                score += 14.0
        if role in {'latest_generated', 'assistant_generated', 'generated', 'edited_output', 'assistant_edited', 'assistant_file'}:
            score += 30.0
        try:
            score += min(float(rec.get('registry_updated_at') or rec.get('registry_created_at') or 0.0) / 10000000000.0, 1.0)
        except Exception:
            pass
        scored.append((score, rec))
    scored.sort(key=lambda item: (item[0], float((item[1] or {}).get('registry_updated_at') or (item[1] or {}).get('registry_created_at') or 0.0)), reverse=True)
    return [item[1] for item in scored[:limit]]


def _file_read_registry_candidate_public(rec: dict | None = None) -> dict:
    row = dict(rec or {})
    filename = str(row.get('filename') or row.get('saved_filename') or '').strip()
    return {
        'registry_file_id': str(row.get('registry_file_id') or row.get('file_id') or '').strip(),
        'filename': filename,
        'saved_filename': str(row.get('saved_filename') or '').strip(),
        'source': str(row.get('source') or '').strip(),
        'source_role': str(row.get('source_role') or '').strip(),
        'scope': str(row.get('scope') or '').strip(),
        'ext': str(row.get('ext') or _history_file_ext(filename)).strip(),
        'size': int(row.get('size') or 0) if str(row.get('size') or '').strip() else 0,
        'full_text_chars': int(row.get('full_text_chars') or 0),
        'updated_at': float(row.get('registry_updated_at') or row.get('registry_created_at') or 0.0),
        'summary': truncate_text(str(row.get('summary') or ''), max_chars=260),
        'read_hint': '先用 sandbox_import_files 导入 /mnt/data；导入后按 file_evidence_policy 选证据：Office/表格内容先 sandbox_read_file，真实执行/统计/测试才 sandbox_run，图片/截图/图表/版式/扫描页才 sandbox_analyze_file_images。',
    }


def _file_read_resolve_account_registry_record(payload: dict | None = None, *, target_name: str = '', source_role: str = '', query: str = '') -> tuple[dict | None, str, list[dict]]:
    args = dict(payload or {}) if isinstance(payload, dict) else {}
    rid = str(args.get('registry_file_id') or args.get('registry_id') or args.get('file_id') or args.get('account_file_id') or args.get('id') or '').strip()
    limit = args.get('candidate_limit') or 6
    candidates = _file_read_registry_candidates(
        registry_file_id=rid,
        target_filename=target_name,
        source_role=source_role,
        query=query,
        limit=limit,
    )
    if not candidates:
        return None, '', []
    if rid:
        return candidates[0], '', candidates
    target = os.path.basename(str(target_name or '').strip()).lower()
    role = str(source_role or '').strip().lower()
    # If the model explicitly asks for the latest generated/account file, returning
    # the newest matching account record is an identity resolution, not an intent
    # trigger. Current-conversation records were already attempted first.
    if role in {'latest_generated', 'assistant_generated', 'generated'} and not target:
        return candidates[0], '', candidates
    if target:
        exact = []
        for rec in candidates:
            names = _file_edit_candidate_names(rec)
            if target in names or target in {os.path.basename(str(rec.get('filename') or '').strip()).lower(), os.path.basename(str(rec.get('saved_filename') or '').strip()).lower()}:
                exact.append(rec)
        if len(exact) == 1:
            return exact[0], '', candidates
        if len(exact) > 1:
            return None, 'ambiguous_account_registry_file', exact
    if len(candidates) == 1 and (target or role):
        return candidates[0], '', candidates
    return None, 'account_registry_candidates_available', candidates


def _file_read_current_records_match_identity(messages: list | None = None, *, target_filename: str = '', source_role: str = '') -> bool:
    target = os.path.basename(str(target_filename or '').strip()).lower()
    if not target:
        return False
    try:
        records, _heavy = _collect_history_file_records(messages or [])
    except Exception:
        return False
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if target not in _file_edit_candidate_names(rec):
            continue
        if source_role and not _file_read_registry_role_filter(rec, source_role):
            continue
        return True
    return False

def _file_edit_record_is_generated(rec: dict | None = None) -> bool:
    row = dict(rec or {})
    role = str(row.get('source_role') or row.get('version_role') or '').strip().lower()
    return (
        role in {'assistant_generated', 'latest_generated', 'generated', 'edited_output', 'assistant_edited', 'assistant_file', 'assistant'}
        or str(row.get('source') or '').strip().lower() == 'generated'
        or str(row.get('namespace') or '').strip().lower() == 'generated'
    )


def _file_edit_record_has_lineage_to(rec: dict | None = None, target_filename: str = '') -> bool:
    target = os.path.basename(str(target_filename or '').strip()).lower()
    if not target:
        return False
    row = dict(rec or {})
    edited_from = row.get('edited_from') if isinstance(row.get('edited_from'), dict) else {}
    for key in ('filename', 'basis_filename', 'requested_target_filename'):
        if os.path.basename(str(edited_from.get(key) or '').strip()).lower() == target:
            return True
    edit_audit = row.get('edit_audit') if isinstance(row.get('edit_audit'), dict) else {}
    for key in ('target_filename', 'basis_filename', 'requested_target_filename'):
        if os.path.basename(str(edit_audit.get(key) or '').strip()).lower() == target:
            return True
    edit_details = row.get('edit_details') if isinstance(row.get('edit_details'), dict) else {}
    details_audit = edit_details.get('audit') if isinstance(edit_details.get('audit'), dict) else {}
    for key in ('target_filename', 'basis_filename', 'requested_target_filename'):
        if os.path.basename(str(details_audit.get(key) or '').strip()).lower() == target:
            return True
    return False


def _file_edit_resolve_target_record(messages: list | None = None, target_filename: str = '') -> tuple[dict | None, str]:
    target = os.path.basename(str(target_filename or '').strip()).lower()
    if not target:
        return None, 'missing_target_filename'
    try:
        records, _heavy = _collect_history_file_records(messages or [])
    except Exception as e:
        return None, f'collect_records_failed:{type(e).__name__}:{e}'
    candidates: list[dict] = []
    seen: set[str] = set()
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        names = _file_edit_candidate_names(rec)
        if target not in names:
            continue
        key = _file_edit_record_key(rec)
        if key in seen:
            continue
        seen.add(key)
        row = dict(rec)
        row['_path'] = _history_file_resolve_path(row)
        candidates.append(row)
    candidates = [rec for rec in candidates if str(rec.get('_path') or rec.get('storage_ref') or '').strip()]
    if not candidates:
        return None, f'target_file_not_found:{target_filename}'
    if len(candidates) == 1:
        return candidates[0], ''

    # Resolve by visible file recency and edit lineage, not by text keywords.
    # If a generated file records that it was edited from the requested target,
    # and it is newer than the latest upload of that target, follow that lineage.
    # If the user re-uploads the original after that, the fresh upload wins.
    ordered = sorted(candidates, key=lambda rec: float(rec.get('order') or 0.0), reverse=True)
    uploads = [rec for rec in ordered if not _file_edit_record_is_generated(rec)]
    generated = [rec for rec in ordered if _file_edit_record_is_generated(rec)]
    latest_upload_order = float(uploads[0].get('order') or 0.0) if uploads else -1.0
    lineage_generated = [rec for rec in generated if _file_edit_record_has_lineage_to(rec, target)]
    if lineage_generated:
        latest_gen = lineage_generated[0]
        if float(latest_gen.get('order') or 0.0) >= latest_upload_order:
            top_order = float(latest_gen.get('order') or 0.0)
            tied = [rec for rec in lineage_generated if abs(float(rec.get('order') or 0.0) - top_order) < 1e-9]
            if len(tied) == 1:
                return latest_gen, ''
    if uploads:
        top_order = float(uploads[0].get('order') or 0.0)
        tied = [rec for rec in uploads if abs(float(rec.get('order') or 0.0) - top_order) < 1e-9]
        if len(tied) == 1:
            return uploads[0], ''
    if generated:
        top_order = float(generated[0].get('order') or 0.0)
        tied = [rec for rec in generated if abs(float(rec.get('order') or 0.0) - top_order) < 1e-9]
        if len(tied) == 1:
            return generated[0], ''

    labels = []
    for rec in candidates[:8]:
        labels.append(f"{rec.get('source') or 'file'}:{rec.get('filename') or rec.get('saved_filename') or ''}")
    return None, 'ambiguous_target_file:' + ','.join(labels)


def _file_edit_resolve_exact_visible_record(messages: list | None = None, target_filename: str = '') -> tuple[dict | None, str]:
    """Resolve by exact visible filename/saved_filename, not lineage aliases.

    Used after the basis selector has chosen a concrete file version.  If the
    selector says basis_filename=index.html, this must mean the visible current
    index.html file, not a later generated file that merely records index.html
    in its lineage.
    """
    target = os.path.basename(str(target_filename or '').strip()).lower()
    if not target:
        return None, 'missing_target_filename'
    try:
        records, _heavy = _collect_history_file_records(messages or [])
    except Exception as e:
        return None, f'collect_records_failed:{type(e).__name__}:{e}'
    exact: list[dict] = []
    seen: set[str] = set()
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        names = {
            os.path.basename(str(rec.get('filename') or '').strip()).lower(),
            os.path.basename(str(rec.get('saved_filename') or '').strip()).lower(),
        }
        if target not in {x for x in names if x}:
            continue
        row = dict(rec)
        row['_path'] = _history_file_resolve_path(row)
        if not str(row.get('_path') or '').strip():
            continue
        key = _file_edit_record_key(row)
        if key in seen:
            continue
        seen.add(key)
        exact.append(row)
    if not exact:
        return _file_edit_resolve_target_record(messages or [], target_filename)
    ordered = sorted(exact, key=lambda rec: float(rec.get('order') or 0.0), reverse=True)
    return ordered[0], ''



def _file_edit_resolve_record_by_role(messages: list | None = None, target_filename: str = '', source_role: str = '') -> tuple[dict | None, str]:
    role = str(source_role or '').strip().lower()
    if role in {'', 'auto', 'default'}:
        return _file_edit_resolve_target_record(messages or [], target_filename)
    if role in {'exact', 'exact_visible', 'visible'}:
        return _file_edit_resolve_exact_visible_record(messages or [], target_filename)
    target = os.path.basename(str(target_filename or '').strip()).lower()
    try:
        records, _heavy = _collect_history_file_records(messages or [])
    except Exception as e:
        return None, f'collect_records_failed:{type(e).__name__}:{e}'
    rows: list[dict] = []
    seen: set[str] = set()
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        filename = os.path.basename(str(rec.get('filename') or rec.get('saved_filename') or '').strip()).lower()
        saved = os.path.basename(str(rec.get('saved_filename') or '').strip()).lower()
        if target and target not in {filename, saved}:
            # Allow lineage aliases only for generated/latest requests, not user_upload.
            if role not in {'assistant_generated', 'generated', 'latest_generated'} or target not in _file_edit_candidate_names(rec):
                continue
        generated = _file_edit_record_is_generated(rec)
        if role in {'user_upload', 'upload', 'original', 'original_upload'} and generated:
            continue
        if role in {'assistant_generated', 'generated', 'latest_generated', 'edited_output', 'assistant_edited', 'assistant_file'} and not generated:
            continue
        if role in {'edited_output', 'assistant_edited'} and generated:
            has_edit_lineage = bool(isinstance(rec.get('edit_audit'), dict) or isinstance(rec.get('edit_details'), dict) or isinstance(rec.get('edited_from'), dict))
            if not has_edit_lineage:
                continue
        row = dict(rec)
        row['_path'] = _history_file_resolve_path(row)
        if not str(row.get('_path') or '').strip():
            continue
        key = _file_edit_record_key(row)
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    if not rows:
        return None, f'target_file_not_found_for_role:{target_filename}:{source_role}'
    rows.sort(key=lambda rec: float(rec.get('order') or 0.0), reverse=True)
    return rows[0], ''
