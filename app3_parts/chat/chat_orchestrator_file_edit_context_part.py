# Split from app3_parts/chat/chat_orchestrator_core_part.py.
# Purpose: file edit audit lineage and recent edit context helpers.
# Loaded by chat_orchestrator_core_part.py via _exec_split_file(...), sharing app3.py globals.

def _orch_file_edit_basename_for_id(value: str = '') -> str:
    try:
        return os.path.basename(str(value or '').strip().replace('\\', '/')).strip()
    except Exception:
        return str(value or '').strip()


def _orch_file_edit_lineage_key_from_audit(audit: dict | None = None) -> str:
    row = dict(audit or {}) if isinstance(audit, dict) else {}
    existing = str(row.get('lineage_key') or row.get('lineage_id') or row.get('chain_key') or '').strip()
    if existing:
        return existing
    names: list[str] = []
    def push(value) -> None:
        name = _orch_file_edit_basename_for_id(str(value or ''))
        if name and name.lower() not in {x.lower() for x in names}:
            names.append(name)
    for key in ('lineage_source_filename', 'basis_filename', 'source_filename', 'original_filename', 'requested_target_filename', 'target_filename', 'output_filename'):
        push(row.get(key))
    for item in (row.get('merge_sources') or []):
        if isinstance(item, dict):
            push(item.get('filename') or item.get('basis_filename'))
        else:
            push(item)
    name = names[0] if names else 'file'
    hash_seed = str(row.get('lineage_sha256') or row.get('basis_sha256') or row.get('old_sha256') or '').strip().lower()
    if not hash_seed:
        try:
            hash_seed = hashlib.sha1(name.lower().encode('utf-8', errors='ignore')).hexdigest()
        except Exception:
            hash_seed = ''
    safe_name = re.sub(r'[^0-9A-Za-z._-]+', '-', name)[:80] or 'file'
    suffix = (hash_seed or 'unknown')[:12]
    return f'{safe_name}@{suffix}'


def _orch_file_edit_audit_id(audit: dict | None = None) -> str:
    row = dict(audit or {}) if isinstance(audit, dict) else {}
    existing = str(row.get('audit_id') or row.get('diff_id') or '').strip()
    if existing:
        return existing
    seed = '|'.join([
        str(row.get('task_job_id') or ''),
        _orch_file_edit_lineage_key_from_audit(row),
        str(row.get('target_filename') or ''),
        str(row.get('basis_filename') or ''),
        str(row.get('output_filename') or ''),
        str(row.get('old_sha256') or ''),
        str(row.get('new_sha256') or ''),
        str(row.get('created_at') or ''),
    ])
    try:
        return 'audit_' + hashlib.sha1(seed.encode('utf-8', errors='ignore')).hexdigest()[:20]
    except Exception:
        return ''


def _orch_normalize_file_edit_audit(obj) -> dict | None:
    if not isinstance(obj, dict):
        return None
    audit = obj
    if not (str(audit.get('_kind') or '').strip() == 'file_edit_audit' or audit.get('old_sha256') or audit.get('new_sha256') or audit.get('diff') or audit.get('diff_summary')):
        return None
    target = str(audit.get('target_filename') or '').strip()
    output = str(audit.get('output_filename') or '').strip()
    if not (target or output):
        return None
    row = dict(audit)
    if not str(row.get('lineage_key') or '').strip():
        row['lineage_key'] = _orch_file_edit_lineage_key_from_audit(row)
    if not str(row.get('audit_id') or '').strip():
        row['audit_id'] = _orch_file_edit_audit_id(row)
    return row


def _orch_collect_recent_file_edit_audits(messages: list | None = None, limit: int = 3) -> list[dict]:
    """Collect factual edit audits from previous generated-file metadata.

    This does not decide whether a user is asking about edits. It only carries
    already-recorded evidence forward so normal final answers do not invent a
    change summary when the user asks follow-ups after file generation.
    """
    out: list[dict] = []
    seen: set[str] = set()

    def push(audit_obj) -> None:
        audit = _orch_normalize_file_edit_audit(audit_obj)
        if not audit:
            return
        key = str(audit.get('audit_id') or '').strip() or '|'.join([
            str(audit.get('target_filename') or ''),
            str(audit.get('output_filename') or ''),
            str(audit.get('old_sha256') or ''),
            str(audit.get('new_sha256') or ''),
        ])
        if key in seen:
            return
        seen.add(key)
        out.append(audit)

    def scan_obj(obj) -> None:
        if len(out) >= max(1, int(limit or 3)):
            return
        if isinstance(obj, dict):
            push(obj.get('edit_audit'))
            push(obj.get('file_edit_audit'))
            if isinstance(obj.get('edit_details'), dict):
                push((obj.get('edit_details') or {}).get('audit'))
            if str(obj.get('_kind') or '') == 'file_edit_audit':
                push(obj)
            if str(obj.get('_kind') or '') == 'genfiles':
                for f in reversed(obj.get('files') or []):
                    scan_obj(f)
                    if len(out) >= max(1, int(limit or 3)):
                        return
            if str(obj.get('_kind') or '') == 'file':
                push(obj.get('edit_audit'))
        elif isinstance(obj, list):
            for item in reversed(obj):
                scan_obj(item)
                if len(out) >= max(1, int(limit or 3)):
                    return

    for m in reversed(messages or []):
        if not isinstance(m, dict):
            continue
        scan_obj(m.get('content'))
        scan_obj(m.get('file_edit_audit'))
        if len(out) >= max(1, int(limit or 3)):
            break
    return out[:max(1, int(limit or 3))]


def _orch_format_recent_file_edit_audit_context(messages: list | None = None, *, max_chars: int = 1200) -> str:
    audits = _orch_collect_recent_file_edit_audits(messages or [], limit=3)
    if not audits:
        return ''
    lines: list[str] = [
        '【最近文件修改记录索引】',
        '最近有后端保存文件后的真实 diff/hash 摘要；后续文件处理统一先导入 sandbox，再在 /mnt/data 内读取、运行或发布。',
    ]
    for idx, audit in enumerate(audits, 1):
        target = str(audit.get('target_filename') or '').strip()
        output = str(audit.get('output_filename') or '').strip()
        old_hash = str(audit.get('old_sha256') or '').strip()
        new_hash = str(audit.get('new_sha256') or '').strip()
        changed = bool(audit.get('changed'))
        audit_id = str(audit.get('audit_id') or '').strip()
        task_job_id = str(audit.get('task_job_id') or '').strip()
        lineage_key = str(audit.get('lineage_key') or '').strip()
        bits = [f'#{idx}']
        if audit_id:
            bits.append('audit_id=' + audit_id)
        if lineage_key:
            bits.append('lineage_key=' + lineage_key)
        if task_job_id:
            bits.append('job=' + task_job_id)
        if target:
            bits.append('target=' + target)
        if output:
            bits.append('output=' + output)
        basis = str(audit.get('basis_filename') or audit.get('source_filename') or audit.get('requested_target_filename') or '').strip()
        if basis and basis not in {target, output}:
            bits.append('basis=' + basis)
        bits.append('changed=' + str(changed))
        if old_hash or new_hash:
            bits.append('old=' + old_hash[:12])
            bits.append('new=' + new_hash[:12])
        lines.append('；'.join(bits))
    text = '\n'.join(lines).strip()
    max_chars = max(600, int(max_chars or 1200))
    if len(text) > max_chars:
        text = text[:max_chars] + '\n...【文件修改记录索引过长，已截断】'
    return text

def _build_answer_messages(messages: list, tool_records: list, user_geo: dict | None = None, include_visual: bool = True, weather_payload: dict | None = None, user_text: str = '', include_tool_runtime: bool = False, include_file_edit_audit_context: bool = False) -> list:
    base = list(messages or [])
    if include_visual:
        base = _inject_visual_context_messages(base, None)
    if include_tool_runtime:
        base = _inject_runtime_tool_context(base, user_geo=user_geo, allow_weather_tool=bool(weather_payload))
    if isinstance(weather_payload, dict) and weather_payload.get('_kind') == 'weather':
        base = _inject_weather_context_messages(base, weather_payload, user_text=user_text)
    out = []
    for m in base:
        if not isinstance(m, dict):
            continue
        mm = dict(m)
        raw_content = mm.get('content')
        if isinstance(raw_content, list):
            mm['content'] = raw_content
        else:
            preserve_kinds = {'file_recall', 'file_memory', 'kb_recall', 'kb_memory', 'kb_doc_brief'}
            msg_kind = str(mm.get('_kind') or '').strip()
            role = str(mm.get('role') or '').strip().lower()
            if role == 'system' and msg_kind in preserve_kinds and isinstance(raw_content, str):
                # These messages are already compacted upstream. Do not run them through
                # _message_to_text_for_budget(), which intentionally caps generic messages
                # to planner-sized text and can cut off deterministic file indexes.
                mm['content'] = raw_content
            else:
                mm['content'] = _message_to_text_for_budget(mm, include_images=False, include_image_text=False)
        out.append(mm)
    if include_file_edit_audit_context:
        out = _orch_append_recent_file_edit_audit_context(out)
    for rec in tool_records or []:
        rec_name = str((rec or {}).get('name') or 'tool').strip() or 'tool'
        rec_text = _coerce_tool_record_content_for_model(rec)
        rec_limit = _orch_tool_budget(rec_name, phase='final_answer')
        out.append({'role': 'system', '_kind': 'tool_evidence', 'content': f"工具证据（{rec_name}）：\n{str(rec_text or '')[:rec_limit]}"})
    out = _orch_dedupe_model_messages(out)
    return _sanitize_messages_for_model(out)




def _orch_append_recent_file_edit_audit_context(messages: list | None = None, *, max_chars: int = 1200) -> list:
    """Append recent real file-edit audit evidence without loading file indexes.

    This is intentionally separate from _agent_stream_messages_with_file_context():
    it only exposes a tiny index that a saved diff exists. Live file follow-up
    work must import the relevant file into the sandbox instead of calling a
    separate diff/read tool.
    """
    out = [dict(m) if isinstance(m, dict) else m for m in (messages or [])]
    try:
        for m in out:
            if not isinstance(m, dict):
                continue
            if str(m.get('role') or '').strip().lower() == 'system' and str(m.get('_kind') or '').strip() == 'file_edit_audit':
                return out
        ctx = _orch_format_recent_file_edit_audit_context(out, max_chars=max_chars)
        if ctx:
            out.append({'role': 'system', '_kind': 'file_edit_audit', 'content': ctx})
    except Exception:
        return out
    return out
