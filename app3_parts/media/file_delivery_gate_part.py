# Split from app3_parts/media/model_image_file_delivery_part.py.
# Purpose: existing-file aliases, confirmation, basis selection, and entry gate.
# Loaded by model_image_file_delivery_part.py via _exec_split_file(...), sharing the original global namespace.

def _file_delivery_tool_schemas() -> list[dict]:
    return []



def _file_delivery_filename_alias_key(value: str = '') -> str:
    """Normalize human shorthand like appv11 / app v11 to comparable keys."""
    raw = str(value or '').strip().lower()
    if not raw:
        return ''
    raw = os.path.basename(raw)
    # Users often omit separators or extensions in follow-ups, e.g. appv11.
    raw = re.sub(r'\s+', '', raw)
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', raw)


def _file_delivery_filename_alias_values(value: str = '') -> set[str]:
    raw = os.path.basename(str(value or '').strip())
    if not raw:
        return set()
    low = raw.lower()
    stem, ext = os.path.splitext(low)
    vals = {low, stem}
    compact_stem = _file_delivery_filename_alias_key(stem)
    compact_full = _file_delivery_filename_alias_key(low)
    if compact_stem:
        vals.add(compact_stem)
    if compact_full:
        vals.add(compact_full)
    if ext and compact_stem:
        vals.add(compact_stem + ext.lower())
    return {v for v in vals if v}


def _file_delivery_existing_file_alias_map(messages: list | None = None) -> dict[str, str]:
    """Map filename aliases to the concrete visible filename in this conversation."""
    out: dict[str, str] = {}
    for rec in _file_delivery_existing_file_records(messages or []):
        if not isinstance(rec, dict):
            continue
        display = os.path.basename(str(rec.get('filename') or rec.get('saved_filename') or '').strip())
        if not display:
            continue
        names: set[str] = set()
        try:
            names.update(_file_edit_candidate_names(rec))
        except Exception:
            names.update({display.lower(), os.path.splitext(display.lower())[0]})
        names.update(_file_delivery_filename_alias_values(display))
        for nm in list(names):
            names.update(_file_delivery_filename_alias_values(nm))
        for nm in names:
            key = _file_delivery_filename_alias_key(nm)
            if key and key not in out:
                out[key] = display
            raw = str(nm or '').strip().lower()
            if raw and raw not in out:
                out[raw] = display
    return out


def _file_delivery_recent_dialogue_excerpt(messages: list | None = None, *, max_turns: int = 8, max_chars: int = 3200) -> str:
    """Small recent dialogue excerpt so the model can interpret concise confirmations."""
    rows = []
    for m in (messages or [])[-max(1, max_turns * 2):]:
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '').strip().lower()
        if role not in {'user', 'assistant'}:
            continue
        content = _msg_content_text(m.get('content'))
        content = re.sub(r'<!--WEBAI_FILE_CONFIRM_V1:[A-Za-z0-9_\-]+=*-->', '', str(content or ''))
        content = re.sub(r'\s+', ' ', content).strip()
        if not content:
            continue
        if len(content) > 520:
            content = content[:520] + '…'
        rows.append(f'{role}: {content}')
    text = '\n'.join(rows[-max_turns:]).strip()
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text

def _file_delivery_existing_file_records(messages: list | None = None) -> list[dict]:
    """Collect concrete existing uploaded/generated files for sandbox artifact routing.

    This is structural context, not an intent router: if existing files are present,
    the model is allowed to choose between reading/editing those files and creating
    genuinely new files.
    """
    try:
        records, _heavy = _collect_history_file_records(messages or [])
    except Exception:
        records = []
    out: list[dict] = []
    seen: set[str] = set()
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        filename = str(rec.get('filename') or rec.get('saved_filename') or '').strip()
        if not filename:
            continue
        row = dict(rec)
        try:
            path = _history_file_resolve_path(row)
        except Exception:
            path = ''
        if path:
            row['_path'] = path
        key = _file_edit_record_key(row) if '_file_edit_record_key' in globals() else f"{filename}|{row.get('source') or ''}|{row.get('namespace') or ''}|{row.get('download_url') or row.get('url') or ''}"
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _file_delivery_lineage_prompt_from_records(records: list[dict] | None = None, *, max_groups: int = 8) -> str:
    helper = globals().get('_history_file_lineage_prompt')
    if callable(helper):
        try:
            return str(helper(records or [], max_groups=max_groups) or '').strip()
        except Exception:
            pass
    return ''


def _file_delivery_existing_files_prompt(messages: list | None = None) -> str:
    records = _file_delivery_existing_file_records(messages or [])
    if not records:
        return ''
    lines = [
        '现有文件候选（结构事实，供模型自行选择）：',
        '先读所需真实原文；需要修改或运行时先用 sandbox_import_files 导入 /mnt/data，再用 sandbox_* 处理，最后用 sandbox_publish_files 发布。',
    ]
    lineage_prompt = _file_delivery_lineage_prompt_from_records(records, max_groups=8)
    if lineage_prompt:
        lines.append(lineage_prompt)
    lines.append('文件明细：')
    for idx, rec in enumerate(records[:12], 1):
        filename = str(rec.get('filename') or rec.get('saved_filename') or '').strip()
        saved = str(rec.get('saved_filename') or '').strip()
        identity = _history_file_identity_line(rec) if '_history_file_identity_line' in globals() else ''
        source = str(rec.get('source') or rec.get('namespace') or 'file').strip()
        ext = str(rec.get('ext') or _history_file_ext(filename)).strip()
        path = str(rec.get('_path') or '').strip()
        size_text = ''
        try:
            if path and os.path.isfile(path):
                size_text = f"，大小 {os.path.getsize(path)} bytes"
        except Exception:
            size_text = ''
        symbols = rec.get('symbols') if isinstance(rec.get('symbols'), list) else []
        names = [str((s or {}).get('name') or '').strip() for s in symbols if isinstance(s, dict) and str((s or {}).get('name') or '').strip()]
        sample = ('，结构符号示例：' + '、'.join(names[:8])) if names else ''
        saved_text = f"，保存名 {saved}" if saved and saved != filename else ''
        role_text = identity or f'{filename}{saved_text}'
        href = _generated_files_download_url(rec)
        link_text = f"，download_url={href}" if href else ''
        lines.append(f"{idx}. {role_text}（source={source}，ext={ext or 'unknown'}{size_text}{sample}{link_text}）")
    return '\n'.join(lines)


def _file_delivery_has_existing_context_read(messages: list | None = None) -> bool:
    for m in (messages or []):
        if not isinstance(m, dict):
            continue
        if str(m.get('role') or '').strip().lower() == 'assistant':
            for tc in (m.get('tool_calls') or []):
                if not isinstance(tc, dict):
                    continue
                fn = tc.get('function') if isinstance(tc.get('function'), dict) else {}
                if str((fn or {}).get('name') or '').strip() == 'sandbox_import_files':
                    return True
        if str(m.get('role') or '').strip().lower() == 'tool':
            raw = str(m.get('content') or '')
            if 'exact_text' in raw and 'target_filename' in raw:
                return True
    return False


def _file_delivery_existing_reference_hint(messages: list | None = None, user_text: str = '') -> dict:
    """Resolve whether the current file-delivery turn is anchored to an existing file.

    This is an operation-safety normalizer, not an intent keyword router: it uses
    concrete files/symbols already present in the conversation to prevent an
    existing-file edits from being routed as fresh sandbox files without first
    reading the real source text.
    """
    records = _file_delivery_existing_file_records(messages or [])
    text = str(user_text or '').strip() or _latest_user_message_text(messages or [])
    out = {
        'has_existing_filename_reference': False,
        'has_symbol_reference': False,
        'target_filename': '',
        'symbol_or_query': '',
        'mentioned_existing_filenames': [],
        'mentioned_symbols': [],
    }
    if not records or not text:
        return out

    text_l = text.lower()
    mentioned_files: list[str] = []
    rec_by_file: dict[str, dict] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        display_name = str(rec.get('filename') or rec.get('saved_filename') or '').strip()
        if not display_name:
            continue
        names = set()
        try:
            names.update(_file_edit_candidate_names(rec))
        except Exception:
            names.update({display_name.lower(), os.path.basename(display_name).lower()})
        hit = False
        for nm in names:
            nm = str(nm or '').strip().lower()
            if not nm:
                continue
            try:
                if re.search(r'(?<![0-9A-Za-z_./\\-])' + re.escape(nm) + r'(?![0-9A-Za-z_./\\-])', text_l):
                    hit = True
                    break
            except Exception:
                if nm in text_l:
                    hit = True
                    break
        if hit and display_name not in mentioned_files:
            mentioned_files.append(display_name)
            rec_by_file[display_name] = rec

    out['mentioned_existing_filenames'] = mentioned_files[:8]
    out['mentioned_symbols'] = []
    out['has_existing_filename_reference'] = bool(mentioned_files)
    out['has_symbol_reference'] = False

    if len(mentioned_files) == 1:
        out['target_filename'] = mentioned_files[0]
        out['symbol_or_query'] = text[:240]
    return out


def _file_delivery_should_normalize_existing_edit(mode: str, messages: list | None = None, user_text: str = '') -> tuple[bool, dict]:
    """Protect existing-file edits from being routed as new-file generation."""
    normalized_mode = str(mode or '').strip().lower()
    if normalized_mode != 'generate_new':
        return False, {}
    hint = _file_delivery_existing_reference_hint(messages or [], user_text=user_text)
    target = str(hint.get('target_filename') or '').strip()
    if not target:
        return False, hint
    # A concrete symbol inside an existing file is a strong structural anchor.
    if bool(hint.get('has_symbol_reference')):
        return True, hint
    # If the request names exactly one existing file and no separate new filename
    # is needed to understand the task, returning a complete file should mean a
    # new version of that existing file, not a fresh miniature rewrite.
    mentioned_files = [str(x or '').strip() for x in (hint.get('mentioned_existing_filenames') or []) if str(x or '').strip()]
    if len(mentioned_files) == 1:
        return True, hint
    return False, hint

def _file_delivery_tool_choice(messages: list | None = None, preferred_mode: str = ''):
    _ = messages, preferred_mode
    return None


def _file_delivery_normalize_required_files(value) -> list[dict]:
    """Normalize model-produced file edit plan rows.

    This is a scope/audit helper, not a keyword router. The planner may decide a
    single-file or multi-file edit from the user goal. The backend then uses this
    normalized allow list to prevent accidental extra-file edits while still
    permitting necessary coordinated changes for non-technical users.
    """
    rows = value if isinstance(value, list) else []
    out: list[dict] = []
    seen: set[str] = set()
    for item in rows:
        if isinstance(item, str):
            filename = item
            reason = ''
        elif isinstance(item, dict):
            filename = str(item.get('filename') or item.get('target_filename') or item.get('name') or '').strip()
            reason = str(item.get('reason') or item.get('why') or '').strip()
        else:
            continue
        filename = os.path.basename(str(filename or '').strip())
        if not filename:
            continue
        key = filename.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({'filename': filename[:180], 'reason': reason[:500]})
        if len(out) >= 12:
            break
    return out


def _file_delivery_normalize_edit_scope(scope: str = '', *, mode: str = '', target_filename: str = '', required_files: list | None = None, needs_user_confirmation: bool = False) -> str:
    raw = str(scope or '').strip().lower()
    if raw not in {'single_file', 'multi_file_confirmed', 'multi_file_needs_confirmation', 'unknown'}:
        raw = 'unknown'
    mode = str(mode or '').strip().lower()
    if mode != 'edit_existing':
        return 'unknown'
    if needs_user_confirmation:
        return 'multi_file_needs_confirmation'
    req = _file_delivery_normalize_required_files(required_files or [])
    if raw == 'unknown':
        if len(req) >= 2:
            raw = 'multi_file_confirmed'
        elif str(target_filename or '').strip():
            raw = 'single_file'
    if raw == 'single_file' and not str(target_filename or '').strip() and len(req) >= 2:
        raw = 'multi_file_confirmed'
    return raw or 'unknown'


def _file_delivery_scope_lines_for_prompt(gate: dict | None = None) -> list[str]:
    gate = dict(gate or {})
    scope = str(gate.get('edit_scope') or 'unknown').strip().lower() or 'unknown'
    req = _file_delivery_normalize_required_files(gate.get('required_files') or [])
    lines: list[str] = []
    if scope == 'single_file':
        target = str(gate.get('target_filename') or '').strip()
        if target:
            lines.append(f'本轮编辑作用域：single_file，只能修改目标文件 {target}；不要顺手修改其它文件。')
        else:
            lines.append('本轮编辑作用域：single_file，只能修改一个能明确解析的目标文件；不要顺手修改其它文件。')
    elif scope == 'multi_file_confirmed':
        if req:
            desc = '；'.join([f"{x.get('filename')}：{x.get('reason') or '必要关联修改'}" for x in req])
            lines.append('本轮编辑作用域：multi_file_confirmed。允许且仅允许修改这些计划内文件：' + desc)
        else:
            lines.append('本轮编辑作用域：multi_file_confirmed。只有确实为完成同一用户目标所必需的文件才能修改；每个文件必须在 reason 中说明必要性。')
        lines.append('多文件编辑时，每个文件都必须独立读取原文、独立 exact_old 替换、独立通过 diff/验证/审计；不能把无关文件放进结果。')
    elif scope == 'multi_file_needs_confirmation':
        if req:
            desc = '；'.join([f"{x.get('filename')}：{x.get('reason') or '可能需要'}" for x in req])
            lines.append('本轮模型判断属于高风险或范围不确定的多文件修改，尚需用户确认。候选文件：' + desc)
        else:
            lines.append('本轮模型判断属于高风险或范围不确定的多文件修改，尚需用户确认。')
    return lines


_FILE_DELIVERY_CONFIRM_MARKER = 'WEBAI_FILE_CONFIRM_V1'


def _file_delivery_confirmation_payload(gate: dict | None = None, delivery_mode: str = '') -> dict:
    gate = dict(gate or {})
    payload_gate = {
        'should_enter_sandbox_files': True,
        'delivery_mode': str(delivery_mode or gate.get('delivery_mode') or 'single_file').strip() or 'single_file',
        'reason': str(gate.get('reason') or '').strip()[:500],
        'source': str(gate.get('source') or '').strip()[:120],
        'file_entry_mode': str(gate.get('file_entry_mode') or 'edit_existing').strip().lower() or 'edit_existing',
        'target_filename': os.path.basename(str(gate.get('target_filename') or '').strip())[:180],
        'symbol_or_query': str(gate.get('symbol_or_query') or '').strip()[:240],
        'edit_scope': str(gate.get('edit_scope') or 'multi_file_needs_confirmation').strip().lower()[:80],
        'required_files': _file_delivery_normalize_required_files(gate.get('required_files') or []),
        'needs_user_confirmation': True,
    }
    basis_plan = gate.get('basis_plan') if isinstance(gate.get('basis_plan'), dict) else {}
    if basis_plan:
        payload_gate['basis_plan'] = {
            'source': str(basis_plan.get('source') or '').strip()[:120],
            'task_understanding': str(basis_plan.get('task_understanding') or '').strip()[:1000],
            'basis_files': _file_delivery_normalize_basis_files(basis_plan.get('basis_files') or []),
            'should_merge_from_other_versions': bool(basis_plan.get('should_merge_from_other_versions')),
            'needs_rollback': bool(basis_plan.get('needs_rollback')),
            'risk_reason': str(basis_plan.get('risk_reason') or '').strip()[:800],
        }
    return {
        'kind': _FILE_DELIVERY_CONFIRM_MARKER,
        'created_at': int(time.time()),
        'delivery_mode': payload_gate['delivery_mode'],
        'gate': payload_gate,
    }


def _file_delivery_confirmation_marker(gate: dict | None = None, delivery_mode: str = '') -> str:
    try:
        raw = json.dumps(_file_delivery_confirmation_payload(gate, delivery_mode), ensure_ascii=False, separators=(',', ':'))
        token = base64.urlsafe_b64encode(raw.encode('utf-8')).decode('ascii').rstrip('=')
        return f'<!--{_FILE_DELIVERY_CONFIRM_MARKER}:{token}-->'
    except Exception:
        return ''


def _file_delivery_scope_confirmation_text(gate: dict | None = None, delivery_mode: str = '') -> str:
    gate = dict(gate or {})
    req = _file_delivery_normalize_required_files(gate.get('required_files') or [])
    lines = ['这个改动涉及高风险或范围不确定的多文件修改，我先不擅自保存。']
    if req:
        lines.append('需要你确认的文件范围：')
        for item in req[:8]:
            reason = str(item.get('reason') or '必要关联修改').strip()
            lines.append(f"- {item.get('filename')}：{reason}")
    else:
        lines.append('请确认是否允许我按这个高风险范围继续修改相关文件。')
    lines.append('确认后我会逐个文件读取原文、保存新版本，并保留真实 diff 审计供校验。')
    marker = _file_delivery_confirmation_marker(gate, delivery_mode)
    if marker:
        lines.append(marker)
    return '\n'.join(lines).strip()


def _file_delivery_extract_confirmation_payload(text: str = '') -> dict:
    raw = str(text or '')
    if not raw or _FILE_DELIVERY_CONFIRM_MARKER not in raw:
        return {}
    m = re.search(rf'{re.escape(_FILE_DELIVERY_CONFIRM_MARKER)}:([A-Za-z0-9_\-]+=*)', raw)
    if not m:
        return {}
    token = m.group(1).strip()
    if not token:
        return {}
    try:
        padded = token + ('=' * ((4 - len(token) % 4) % 4))
        obj = json.loads(base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8'))
        if not isinstance(obj, dict) or obj.get('kind') != _FILE_DELIVERY_CONFIRM_MARKER:
            return {}
        gate = obj.get('gate') if isinstance(obj.get('gate'), dict) else {}
        if not gate:
            return {}
        gate['required_files'] = _file_delivery_normalize_required_files(gate.get('required_files') or [])
        if isinstance(gate.get('basis_plan'), dict):
            gate['basis_plan']['basis_files'] = _file_delivery_normalize_basis_files(gate['basis_plan'].get('basis_files') or [])
        return {'gate': gate, 'delivery_mode': str(obj.get('delivery_mode') or gate.get('delivery_mode') or '').strip()}
    except Exception:
        return {}


def _file_delivery_pending_confirmation_from_messages(messages: list | None = None) -> dict:
    """Return the confirmation plan from the immediately previous assistant turn.

    Do not resurrect older confirmation markers after the conversation has already
    moved on; that was the source of plan/file-scope drift across follow-ups.
    """
    seen_latest_user = False
    for m in reversed(messages or []):
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '').strip().lower()
        content = m.get('content')
        if role == 'user' and not seen_latest_user:
            seen_latest_user = True
            continue
        if not seen_latest_user:
            continue
        if role == 'assistant':
            if isinstance(content, str):
                return _file_delivery_extract_confirmation_payload(content)
            return {}
    return {}


def _file_delivery_user_text_primary(user_text: str = '') -> str:
    raw = str(user_text or '').strip()
    if not raw:
        return ''
    raw = re.split(r'\n\s*引用/上文定位\s*[:：]', raw, maxsplit=1)[0].strip()
    return raw


def _file_delivery_confirm_followup_fallback(user_text: str = '') -> str:
    primary = _file_delivery_user_text_primary(user_text)
    compact = re.sub(r'\s+', '', primary)
    if not compact:
        return 'unclear'
    # This fallback is only a state-machine recovery for an explicit prior
    # confirmation request; the model classifier below is preferred.
    if any(ch in compact for ch in ['?', '？']):
        return 'unclear'
    if len(compact) <= 16:
        negative_fragments = ('不', '别', '停', '取消', '算了', '不要', '先别', '等等')
        if any(x in compact for x in negative_fragments):
            return 'reject'
        return 'approve'
    return 'unclear'


def _file_delivery_confirmation_followup_decision_once(model: str, messages: list | None = None, *, pending: dict | None = None, client_override=None, heuristic_hint: dict | None = None) -> dict:
    pending = dict(pending or {})
    gate = dict(pending.get('gate') or {})
    if not gate:
        return {'decision': 'none', 'reason': 'no_pending_confirmation'}
    user_text = str((heuristic_hint or {}).get('user_text') or _latest_user_text_from_messages(messages or []) or '').strip()
    primary = _file_delivery_user_text_primary(user_text)
    required = _file_delivery_normalize_required_files(gate.get('required_files') or [])
    required_text = '\n'.join([f"- {x.get('filename')}: {x.get('reason') or ''}" for x in required[:12]]) or '无'
    contract_text = ''
    try:
        contract_builder = globals().get('prompt_contract_text')
        if callable(contract_builder):
            contract_text = str(contract_builder('file_confirmation_classifier', compact=True) or '').strip()
    except Exception:
        contract_text = ''
    system_text = (
        ((contract_text + '\n') if contract_text else '')
        + '上一轮助手已经明确要求用户确认高风险或范围不确定的文件修改计划。'
    )
    prompt = [
        {'role': 'system', 'content': system_text},
        {'role': 'user', 'content': f'上一轮待确认文件：\n{required_text}\n\n用户最新回复：{primary or user_text}'},
    ]
    try:
        req = {
            'model': model,
            'messages': prompt,
            'temperature': 0,
            'max_tokens': 120,
        }
        contract_format = globals().get('apply_prompt_contract_response_format')
        if callable(contract_format):
            req = contract_format(req, 'file_confirmation_classifier')
        else:
            req['response_format'] = {'type': 'json_object'}
        req = _apply_completion_thinking_kwargs(req, role='tool_prefetch', model=model, client_override=client_override)
        raw = _file_delivery_stream_chat_json_content(req, client_override=client_override, purpose='file_confirmation_classifier')
        obj = _safe_json_loads(raw) or {}
        decision = str(obj.get('decision') or '').strip().lower()
        if decision in {'approve', 'reject', 'revise', 'unclear'}:
            tracer = globals().get('skill_trace_span')
            if callable(tracer):
                tracer('prompt_contract_completed', skill='sandbox', endpoint_mode='chat_completions', status='ok', metadata={'contract': 'file_confirmation_classifier', 'decision': decision})
            return {'decision': decision, 'reason': str(obj.get('reason') or '').strip()[:300], 'source': 'model_confirmation_classifier'}
    except Exception as e:
        try:
            app_logger.warning('[FILE_CONFIRM_FOLLOWUP] classifier_failed err=%s:%s', type(e).__name__, e)
        except Exception:
            pass
    fallback = _file_delivery_confirm_followup_fallback(user_text)
    return {'decision': fallback, 'reason': 'fallback_confirmation_state_machine', 'source': 'fallback'}


def _file_delivery_gate_from_confirmed_pending(pending: dict | None = None, *, fallback_delivery_mode: str = '') -> dict:
    pending = dict(pending or {})
    gate = dict(pending.get('gate') or {})
    req = _file_delivery_normalize_required_files(gate.get('required_files') or [])
    if not req and str(gate.get('target_filename') or '').strip():
        req = [{'filename': os.path.basename(str(gate.get('target_filename') or '').strip()), 'reason': '上一轮确认计划目标'}]
    scope = 'multi_file_confirmed' if len(req) >= 2 else 'single_file'
    target = os.path.basename(str(gate.get('target_filename') or '').strip())
    if not target and req:
        target = str(req[0].get('filename') or '').strip()
    out = {
        'should_enter_sandbox_files': True,
        'delivery_mode': str(pending.get('delivery_mode') or gate.get('delivery_mode') or fallback_delivery_mode or 'single_file').strip() or 'single_file',
        'reason': 'user_confirmed_previous_file_scope',
        'source': 'pending_confirmation_confirmed',
        'file_entry_mode': 'edit_existing',
        'target_filename': target[:180],
        'symbol_or_query': str(gate.get('symbol_or_query') or '').strip()[:240],
        'edit_scope': scope,
        'required_files': req,
        'needs_user_confirmation': False,
    }
    if isinstance(gate.get('basis_plan'), dict):
        out['basis_plan'] = gate.get('basis_plan')
    return out


def _file_delivery_allowed_edit_targets_from_gate(gate: dict | None = None) -> list[str]:
    gate = dict(gate or {})
    scope = str(gate.get('edit_scope') or 'unknown').strip().lower()
    req = _file_delivery_normalize_required_files(gate.get('required_files') or [])
    out: list[str] = []
    seen: set[str] = set()
    for item in req:
        filename = os.path.basename(str(item.get('filename') or '').strip())
        if filename and filename.lower() not in seen:
            seen.add(filename.lower())
            out.append(filename)
    target = os.path.basename(str(gate.get('target_filename') or '').strip())
    if scope == 'single_file' and target and target.lower() not in seen:
        out.insert(0, target)
    return out[:12]



def _file_delivery_basis_candidate_records(messages: list | None = None, limit: int = 24) -> list[dict]:
    """Return user-visible file candidates for the basis selector.

    A file edit must not blindly follow the newest generated file.  The selector
    gets the current conversation's visible uploads/generated files, including
    lineage/audit metadata, and chooses the basis that best matches the latest
    user request.
    """
    try:
        records, _heavy = _collect_history_file_records(messages or [])
    except Exception:
        records = []
    out: list[dict] = []
    seen: set[str] = set()
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        path = _history_file_resolve_path(rec)
        if not path:
            continue
        filename = os.path.basename(str(rec.get('filename') or rec.get('saved_filename') or '').strip())
        saved_filename = os.path.basename(str(rec.get('saved_filename') or '').strip())
        visible_name = filename or saved_filename
        if not visible_name:
            continue
        key = _file_edit_record_key(rec) if '_file_edit_record_key' in globals() else (visible_name.lower() + '|' + path)
        if key in seen:
            continue
        seen.add(key)
        edited_from = rec.get('edited_from') if isinstance(rec.get('edited_from'), dict) else {}
        audit = rec.get('edit_audit') if isinstance(rec.get('edit_audit'), dict) else {}
        details = rec.get('edit_details') if isinstance(rec.get('edit_details'), dict) else {}
        details_audit = details.get('audit') if isinstance(details.get('audit'), dict) else {}
        if not audit and details_audit:
            audit = details_audit
        diff_summary = []
        try:
            diff_summary = [str(x or '').strip() for x in (audit.get('diff_summary') or []) if str(x or '').strip()][:8]
        except Exception:
            diff_summary = []
        lineage_names = _history_file_lineage_names(rec) if '_history_file_lineage_names' in globals() else []
        identity = _history_file_identity_line(rec) if '_history_file_identity_line' in globals() else ''
        chain_key = _history_file_lineage_group_key(rec) if '_history_file_lineage_group_key' in globals() else ''
        out.append({
            'filename': visible_name[:180],
            'saved_filename': saved_filename[:180],
            'role': (_history_file_identity_role(rec) if '_history_file_identity_role' in globals() else str(rec.get('source') or '').strip())[:80],
            'identity': identity[:500],
            'chain_key': str(chain_key or '').strip()[:180],
            'lineage_sources': [str(x or '').strip()[:180] for x in (lineage_names or []) if str(x or '').strip()][:6],
            'source': str(rec.get('source') or '').strip()[:80],
            'namespace': str(rec.get('namespace') or '').strip()[:80],
            'order': float(rec.get('order') or 0.0),
            'ext': str(rec.get('ext') or _history_file_ext(visible_name) or '').strip()[:20],
            'edited_from': {
                'filename': str(edited_from.get('filename') or '').strip()[:180],
                'source_type': str(edited_from.get('source_type') or '').strip()[:80],
            },
            'audit': {
                'audit_id': str(audit.get('audit_id') or '').strip()[:120],
                'task_job_id': str(audit.get('task_job_id') or '').strip()[:120],
                'lineage_key': str(audit.get('lineage_key') or '').strip()[:180],
                'target_filename': str(audit.get('target_filename') or '').strip()[:180],
                'output_filename': str(audit.get('output_filename') or '').strip()[:180],
                'user_request': str(audit.get('user_request') or '').strip()[:500],
                'reason': str(audit.get('reason') or '').strip()[:500],
                'diff_summary': diff_summary,
            },
        })
        if len(out) >= max(1, min(int(limit or 24), 60)):
            break
    return out


def _file_delivery_normalize_basis_files(value) -> list[dict]:
    rows = value if isinstance(value, list) else []
    out: list[dict] = []
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        requested = os.path.basename(str(item.get('requested_target') or item.get('target_filename') or item.get('filename') or '').strip())
        basis = os.path.basename(str(item.get('basis_filename') or item.get('source_filename') or item.get('filename') or requested).strip())
        if not basis:
            continue
        key = (requested or basis).lower() + '|' + basis.lower()
        if key in seen:
            continue
        seen.add(key)
        merge_sources = []
        raw_merge = item.get('merge_sources') or item.get('merged_from') or []
        if isinstance(raw_merge, str):
            raw_merge = [raw_merge]
        if isinstance(raw_merge, list):
            mseen: set[str] = set()
            for m in raw_merge:
                if isinstance(m, dict):
                    name = os.path.basename(str(m.get('filename') or m.get('basis_filename') or '').strip())
                    reason = str(m.get('reason') or '').strip()
                else:
                    name = os.path.basename(str(m or '').strip())
                    reason = ''
                if name and name.lower() not in mseen:
                    mseen.add(name.lower())
                    merge_sources.append({'filename': name[:180], 'reason': reason[:400]})
        source_role = str(item.get('source_role') or item.get('version_role') or '').strip()[:80]
        out.append({
            'requested_target': (requested or basis)[:180],
            'basis_filename': basis[:180],
            'source_role': source_role,
            'basis_reason': str(item.get('basis_reason') or item.get('reason') or '').strip()[:800],
            'merge_sources': merge_sources[:8],
        })
        if len(out) >= 12:
            break
    return out


def _file_delivery_basis_plan_for_tool(gate: dict | None = None) -> list[dict]:
    gate = dict(gate or {})
    plan = gate.get('basis_plan') if isinstance(gate.get('basis_plan'), dict) else {}
    return _file_delivery_normalize_basis_files(plan.get('basis_files') or [])


def _file_delivery_basis_targets_from_gate(gate: dict | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in _file_delivery_basis_plan_for_tool(gate):
        name = os.path.basename(str(item.get('basis_filename') or '').strip())
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    if out:
        return out[:12]
    return _file_delivery_allowed_edit_targets_from_gate(gate)


def _file_delivery_basis_lines_for_prompt(gate: dict | None = None) -> list[str]:
    rows = _file_delivery_basis_plan_for_tool(gate)
    if not rows:
        return []
    lines = ['本轮基准选择（模型已按文件身份/血缘判断）：']
    for item in rows[:10]:
        requested = str(item.get('requested_target') or '').strip()
        basis = str(item.get('basis_filename') or '').strip()
        reason = str(item.get('basis_reason') or '').strip()
        source_role = str(item.get('source_role') or '').strip()
        line = f'- {requested or basis} -> 基准：{basis}'
        if source_role:
            line += f'；身份：{source_role}'
        if reason:
            line += f'；原因：{reason}'
        merges = item.get('merge_sources') if isinstance(item.get('merge_sources'), list) else []
        if merges:
            merge_text = '；'.join([f"{m.get('filename')}（{m.get('reason') or '参考'}）" for m in merges if isinstance(m, dict) and str(m.get('filename') or '').strip()])
            if merge_text:
                line += f'；参考：{merge_text}'
        lines.append(line)
    lines.append('读取和保存时按这个基准计划传 target_filename；需要其它版本证据时再主动读取。')
    return lines


def _file_delivery_default_basis_plan(gate: dict | None = None, messages: list | None = None) -> dict:
    gate = dict(gate or {})
    names = _file_delivery_allowed_edit_targets_from_gate(gate)
    if not names and str(gate.get('target_filename') or '').strip():
        names = [os.path.basename(str(gate.get('target_filename') or '').strip())]
    basis_files = []
    for name in names[:12]:
        if not name:
            continue
        basis_files.append({
            'requested_target': name,
            'basis_filename': name,
            'source_role': '',
            'basis_reason': '默认以用户当前明确目标文件作为基准；是否解析到生成版本由后端候选解析决定。',
            'merge_sources': [],
        })
    return {
        'source': 'fallback',
        'task_understanding': '',
        'basis_files': basis_files,
        'should_merge_from_other_versions': False,
        'needs_rollback': False,
        'needs_user_confirmation': False,
        'risk_reason': '',
    }


def _file_delivery_basis_decision_once(model: str, messages: list | None = None, *, gate: dict | None = None, client_override=None, heuristic_hint: dict | None = None) -> dict:
    """Model-soft basis selector for existing-file edits.

    Latest-generated is only one candidate.  The selector decides whether to use
    a fresh upload, a generated version, an explicitly named version, or a
    rollback/merge basis according to the user's current request.
    """
    gate = dict(gate or {})
    if str(gate.get('file_entry_mode') or '').strip().lower() != 'edit_existing':
        return {}
    candidates = _file_delivery_basis_candidate_records(messages or [])
    if not candidates:
        return _file_delivery_default_basis_plan(gate, messages)
    required = _file_delivery_normalize_required_files(gate.get('required_files') or [])
    user_text = str((heuristic_hint or {}).get('user_text') or _latest_user_text_from_messages(messages or []) or '').strip()
    lineage_context = ''
    try:
        lineage_context = _file_delivery_lineage_prompt_from_records(_file_delivery_existing_file_records(messages or []), max_groups=10)
    except Exception:
        lineage_context = ''
    candidate_lines = []
    valid_names: set[str] = set()
    for idx, rec in enumerate(candidates[:24], 1):
        name = os.path.basename(str(rec.get('filename') or rec.get('saved_filename') or '').strip())
        saved = os.path.basename(str(rec.get('saved_filename') or '').strip())
        if name:
            valid_names.add(name.lower())
        if saved:
            valid_names.add(saved.lower())
        edited_from = rec.get('edited_from') if isinstance(rec.get('edited_from'), dict) else {}
        audit = rec.get('audit') if isinstance(rec.get('audit'), dict) else {}
        chain_key = str(rec.get('chain_key') or '').strip()
        bits = [f'{idx}. filename={name}']
        if chain_key:
            bits.append(f'chain={chain_key}')
        if saved and saved != name:
            bits.append(f'saved={saved}')
        if rec.get('identity'):
            bits.append(f'identity={rec.get("identity")}')
        else:
            bits.append(f'role={rec.get("role") or ""}')
        if rec.get('lineage_sources'):
            bits.append('lineage_sources=' + ','.join([str(x) for x in (rec.get('lineage_sources') or [])[:4]]))
        bits.append(f'source={rec.get("source") or ""}/{rec.get("namespace") or ""}')
        if edited_from.get('filename'):
            bits.append(f'edited_from={edited_from.get("filename")}')
        if audit.get('audit_id'):
            bits.append(f'audit_id={audit.get("audit_id")}')
        if audit.get('lineage_key'):
            bits.append(f'audit_lineage={audit.get("lineage_key")}')
        if audit.get('task_job_id'):
            bits.append(f'audit_job={audit.get("task_job_id")}')
        if audit.get('target_filename') or audit.get('output_filename'):
            bits.append(f'audit_target={audit.get("target_filename") or ""} audit_output={audit.get("output_filename") or ""}')
        if audit.get('user_request'):
            bits.append('audit_request=' + str(audit.get('user_request') or '')[:160])
        ds = audit.get('diff_summary') if isinstance(audit.get('diff_summary'), list) else []
        if ds:
            bits.append('diff=' + ' | '.join([str(x)[:120] for x in ds[:4]]))
        candidate_lines.append('；'.join(bits))
    required_lines = []
    for item in required[:12]:
        required_lines.append(f"- {item.get('filename')}: {item.get('reason') or ''}")
    recent_context = _file_delivery_recent_dialogue_excerpt(messages or [])
    contract_text = ''
    try:
        contract_builder = globals().get('prompt_contract_text')
        if callable(contract_builder):
            contract_text = str(contract_builder('file_basis_selector', compact=True) or '').strip()
    except Exception:
        contract_text = ''
    system_text = (
        ((contract_text + '\n') if contract_text else '')
        + '根据用户最新请求、最近对话、文件身份、血缘链和 diff 审计，选择本轮基准；多文件任务可返回多个 basis_files。diff 审计带 audit_id/lineage_key/job 仅作事实索引。\n'
        'basis_filename 必须来自候选清单 filename/saved；source_role 只在同名或身份易混时填写。'
    )
    prompt = [
        {'role': 'system', 'content': system_text},
        {'role': 'user', 'content': (
            f'用户最新请求：{user_text}\n\n'
            f'最近对话上下文（用于判断继续/回退/基于某版本，不是硬规则）：\n{recent_context if recent_context else "无"}\n\n'
            f'入口计划：mode={gate.get("file_entry_mode")}; scope={gate.get("edit_scope")}; target={gate.get("target_filename")}; symbol={gate.get("symbol_or_query")}\n'
            f'计划内文件：\n{chr(10).join(required_lines) if required_lines else "未明确"}\n\n'
            f'文件血缘链：\n{lineage_context if lineage_context else "无"}\n\n'
            f'当前会话可见候选文件：\n{chr(10).join(candidate_lines) if candidate_lines else "无"}\n\n'
            '请选择本轮实际读取/修改的基准文件；多文件就分别列出。'
        )},
    ]
    try:
        req = {
            'model': model,
            'messages': prompt,
            'temperature': 0,
            'max_tokens': 900,
        }
        contract_format = globals().get('apply_prompt_contract_response_format')
        if callable(contract_format):
            req = contract_format(req, 'file_basis_selector')
        else:
            req['response_format'] = {'type': 'json_object'}
        req = _apply_completion_thinking_kwargs(req, role='tool_prefetch', model=model, client_override=client_override)
        raw = _file_delivery_stream_chat_json_content(req, client_override=client_override, purpose='file_basis_select')
        obj = _safe_json_loads(raw) or {}
    except Exception as e:
        try:
            app_logger.warning('[FILE_BASIS_SELECT] failed err=%s: %s', type(e).__name__, e)
        except Exception:
            pass
        obj = {}
    basis_files = _file_delivery_normalize_basis_files(obj.get('basis_files') if isinstance(obj, dict) else [])
    if valid_names:
        alias_map = _file_delivery_existing_file_alias_map(messages or [])
        filtered = []
        for item in basis_files:
            basis = os.path.basename(str(item.get('basis_filename') or '').strip())
            basis_l = basis.lower()
            resolved = ''
            if basis and basis_l in valid_names:
                resolved = basis
            elif basis:
                resolved = alias_map.get(basis_l) or alias_map.get(_file_delivery_filename_alias_key(basis)) or ''
            if resolved and resolved.lower() in valid_names:
                item = dict(item)
                item['basis_filename'] = resolved
                filtered.append(item)
        basis_files = filtered
    if not basis_files:
        fallback = _file_delivery_default_basis_plan(gate, messages)
        basis_files = _file_delivery_normalize_basis_files(fallback.get('basis_files') or [])
        source = 'fallback'
    else:
        source = 'model_basis_selector'
    plan = {
        'source': source,
        'task_understanding': str((obj or {}).get('task_understanding') or '').strip()[:1000] if isinstance(obj, dict) else '',
        'basis_files': basis_files,
        'should_merge_from_other_versions': bool((obj or {}).get('should_merge_from_other_versions')) if isinstance(obj, dict) else False,
        'needs_rollback': bool((obj or {}).get('needs_rollback')) if isinstance(obj, dict) else False,
        'needs_user_confirmation': bool((obj or {}).get('needs_user_confirmation')) if isinstance(obj, dict) else False,
        'risk_reason': str((obj or {}).get('risk_reason') or '').strip()[:800] if isinstance(obj, dict) else '',
    }
    try:
        app_logger.info('[FILE_BASIS_SELECT] source=%s basis=%s merge=%s rollback=%s', plan.get('source'), [(x.get('requested_target'), x.get('basis_filename')) for x in basis_files[:8]], bool(plan.get('should_merge_from_other_versions')), bool(plan.get('needs_rollback')))
    except Exception:
        pass
    return plan

def _file_delivery_looks_like_standalone_image_generation(user_text: str = '') -> bool:
    """Compatibility shim: file/image boundary is model-decided, not keyword-scored."""
    return False

def _file_delivery_entry_decision_once(model: str, messages: list | None = None, *, client_override=None, prefetch_decision: dict | None = None, heuristic_hint: dict | None = None) -> dict:
    records = _file_delivery_existing_file_records(messages or [])
    user_text = str((heuristic_hint or {}).get('user_text') or _latest_user_text_from_messages(messages or []) or '').strip()
    soft_prompt = _build_file_delivery_soft_prompt(messages or [])
    if not user_text:
        return {'should_enter': False, 'mode': 'none', 'reason': 'empty_user_text', 'source': 'model_gate_skipped'}
    if not records and not soft_prompt:
        return {'should_enter': False, 'mode': 'none', 'reason': 'no_file_context', 'source': 'model_gate_skipped'}

    existing_prompt = _file_delivery_existing_files_prompt(messages or [])
    recent_context = _file_delivery_recent_dialogue_excerpt(messages or [])
    file_lines = []
    for idx, rec in enumerate(records[:12], 1):
        filename = str(rec.get('filename') or rec.get('saved_filename') or '').strip()
        ext = str(rec.get('ext') or _history_file_ext(filename)).strip()
        symbols = rec.get('symbols') if isinstance(rec.get('symbols'), list) else []
        names = [str((s or {}).get('name') or '').strip() for s in symbols if isinstance(s, dict) and str((s or {}).get('name') or '').strip()]
        sample = '、'.join(names[:24])
        file_lines.append(f'{idx}. {filename} ext={ext or "unknown"} symbols={sample}')

    contract_text = ''
    try:
        contract_builder = globals().get('prompt_contract_text')
        if callable(contract_builder):
            contract_text = str(contract_builder('file_entry_router', compact=True) or '').strip()
    except Exception:
        contract_text = ''
    system_text = (
        ((contract_text + '\n') if contract_text else '')
        + '文件处理入口判定补充约束：\n'
        '- 先判断用户最终想拿到的交付物；不要按单个词触发。\n'
        '- 最新用户请求优先；短回复要结合最近对话理解确认/续改。\n'
        '- 历史文件只是上下文，不能覆盖当前目标。\n'
        '- 修改/优化/修复/重构/拆分已有文件或页面：mode=edit_existing。\n'
        '- 查看函数体、片段、原因、结构，且需要原文才能准确回答：mode=read_existing。\n'
        '- 新建/导出/保存真实文件，且不是改现有文件：mode=generate_new。\n'
        '- 用户最终要图片成品或修改图片时，按图片目标理解；如果同时要求写入页面/代码/文件，再交给文件通道。\n'
        '- 不要把“生成图片/根据提示词生成图片”理解成“在文件里实现生图功能”，除非用户明确要求修改页面、代码或功能。\n'
        '- 普通聊天、排查原因、讨论方案但未要求交付文件：mode=none。\n'
        '- edit_existing/read_existing 要尽量给 target_filename；无法唯一定位时用 symbol_or_query。\n'
        '- 只改一个明确文件：single_file；同一目标必须跨文件配合：multi_file_confirmed；高风险或范围不明才 multi_file_needs_confirmation。\n'
        '- 不要顺手改无关文件；理由一句话。'
    )
    prompt = [
        {'role': 'system', 'content': system_text},
        {'role': 'user', 'content': (
            f'用户最新请求：{user_text}\n\n'
            f'最近对话上下文（用于理解短确认/续改，不是硬规则）：\n{recent_context if recent_context else "无"}\n\n'
            f'现有文件清单：\n{chr(10).join(file_lines) if file_lines else "无"}\n\n'
            f'现有文件详细上下文：\n{existing_prompt[:4000] if existing_prompt else "无"}\n\n'
            f'软提示：\n{soft_prompt[:1600] if soft_prompt else "无"}\n\n'
            '按契约返回结构化入口判断。'
        )},
    ]
    try:
        req = {
            'model': model,
            'messages': prompt,
            'temperature': 0,
            'max_tokens': 620,
        }
        contract_format = globals().get('apply_prompt_contract_response_format')
        if callable(contract_format):
            req = contract_format(req, 'file_entry_router')
        else:
            req['response_format'] = {'type': 'json_object'}
        req = _apply_completion_thinking_kwargs(req, role='tool_prefetch', model=model, client_override=client_override)
        raw = _file_delivery_stream_chat_json_content(req, client_override=client_override, purpose='file_entry_decision')
        obj = _safe_json_loads(raw) or {}
        mode = str(obj.get('mode') or '').strip().lower()
        if mode not in {'edit_existing', 'read_existing', 'generate_new', 'none'}:
            mode = 'none'
        should_enter = bool(obj.get('should_enter')) and mode != 'none'
        if mode == 'edit_existing' and not records:
            should_enter = False
            mode = 'none'
        required_files = _file_delivery_normalize_required_files(obj.get('required_files') or [])
        edit_scope = _file_delivery_normalize_edit_scope(
            obj.get('edit_scope') or '',
            mode=mode,
            target_filename=str(obj.get('target_filename') or '').strip(),
            required_files=required_files,
            needs_user_confirmation=bool(obj.get('needs_user_confirmation')),
        )
        return {
            'should_enter': bool(should_enter),
            'mode': mode,
            'target_filename': str(obj.get('target_filename') or '').strip()[:180],
            'symbol_or_query': str(obj.get('symbol_or_query') or '').strip()[:240],
            'edit_scope': edit_scope,
            'required_files': required_files,
            'needs_user_confirmation': bool(obj.get('needs_user_confirmation')),
            'reason': str(obj.get('reason') or '').strip()[:220],
            'source': 'model_gate',
        }
    except Exception as e:
        try:
            app_logger.warning('[file_delivery_entry] model_gate_failed err=%s:%s', type(e).__name__, e)
        except Exception:
            pass
        return {'should_enter': False, 'mode': 'none', 'reason': f'model_gate_failed:{type(e).__name__}', 'source': 'model_gate_failed'}
