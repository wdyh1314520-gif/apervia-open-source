# message dedupe and runtime location context helpers.

def _orch_message_text_for_dedupe(message: dict | None = None) -> str:
    if not isinstance(message, dict):
        return ''
    role = str(message.get('role') or '').strip().lower()
    try:
        text = _responses_instruction_text_from_content(message.get('content')) if role in {'system', 'developer'} else str(message.get('content') or '')
    except Exception:
        text = str(message.get('content') or '')
    try:
        return re.sub(r'\s+', ' ', str(text or '')).strip()
    except Exception:
        return ' '.join(str(text or '').split())


def _orch_message_dedupe_fingerprint(message: dict | None = None, *, include_kind: bool = True) -> str:
    if not isinstance(message, dict):
        return ''
    role = str(message.get('role') or '').strip().lower()
    kind = str(message.get('_kind') or '').strip().lower() if include_kind else ''
    norm = _orch_message_text_for_dedupe(message).lower()
    if not norm:
        return ''
    if len(norm) > 5000:
        norm = norm[:5000]
    try:
        digest = hashlib.sha1(norm.encode('utf-8', errors='ignore')).hexdigest()[:20]
    except Exception:
        digest = str(abs(hash(norm)))[:20]
    return '|'.join([role, kind, digest])


def _orch_dedupe_model_messages(messages: list | None = None) -> list:
    """Drop duplicate model-only context blocks while preserving chat turns.

    Conservative rules:
    - never drop user/assistant turns;
    - exact duplicate system/developer blocks are removed even if their legacy
      `_kind` differs;
    - known singleton runtime blocks keep only the latest version in one request.
    This prevents prompt-token drift from repeated runtime/tool/file hints without
    changing tool routing or visible chat history.
    """
    rows = [m for m in (messages or []) if isinstance(m, dict)]
    singleton_kinds = {
        'runtime_time', 'runtime_location_visibility', 'runtime_model',
        'tool_runtime', 'agent_stream_policy', 'agent_stream_runtime', 'agent_stream_image_payload_notice',
        'file_delivery_soft_prompt', 'code_chinese_safe_prompt',
        'file_memory', 'file_recall', 'file_edit_audit', 'kb_memory',
        'kb_recall', 'kb_doc_brief', 'kb_existing_file_answer',
        'agent_stream_file_loop_hint', 'generated_artifact_context',
        'weather_ctx', 'image_generation_failure_context',
        'agent_final_file_delivery_guard', 'agent_final_grounding_guard',
        'agent_final_memory_guard', 'agent_final_fact_bridge',
    }
    keep_singleton_index: dict[str, int] = {}
    for idx, item in enumerate(rows):
        role = str(item.get('role') or '').strip().lower()
        kind = str(item.get('_kind') or '').strip().lower()
        if role in {'system', 'developer'} and kind in singleton_kinds:
            keep_singleton_index[kind] = idx

    out: list = []
    seen_exact: set[str] = set()
    seen_text: set[str] = set()
    seen_tool_evidence: set[str] = set()
    dropped = 0
    for idx, item in enumerate(rows):
        role = str(item.get('role') or '').strip().lower()
        if role not in {'system', 'developer'}:
            out.append(item)
            continue
        kind = str(item.get('_kind') or '').strip().lower()
        if kind in singleton_kinds and keep_singleton_index.get(kind) != idx:
            dropped += 1
            continue
        fp_exact = _orch_message_dedupe_fingerprint(item, include_kind=True)
        fp_text = _orch_message_dedupe_fingerprint(item, include_kind=False)
        if fp_exact and fp_exact in seen_exact:
            dropped += 1
            continue
        # Same role + same long text should only be sent once even when older
        # callers forgot `_kind` or used a different legacy kind.
        text_norm = _orch_message_text_for_dedupe(item)
        if fp_text and len(text_norm) >= 160 and fp_text in seen_text:
            dropped += 1
            continue
        text = text_norm
        if '[tool_evidence_v1]' in text or '工具结果摘要' in text or '工具证据' in text:
            nm = ''
            m = re.search(r'(?:tool|工具结果摘要|工具证据)[：:\s（(]+([A-Za-z0-9_\-]+)', text)
            if m:
                nm = m.group(1).strip().lower()
            tool_fp = nm + '|' + (fp_text or fp_exact or '')
            if tool_fp in seen_tool_evidence:
                dropped += 1
                continue
            if tool_fp.strip('|'):
                seen_tool_evidence.add(tool_fp)
        if fp_exact:
            seen_exact.add(fp_exact)
        if fp_text:
            seen_text.add(fp_text)
        out.append(item)
    try:
        if dropped:
            app_logger.info('[MODEL_CONTEXT_DEDUPE] messages=%s->%s dropped=%s', len(rows), len(out), dropped)
    except Exception:
        pass
    return out

def _orch_strip_lane_system_messages(messages: list, remove_kinds: tuple[str, ...] = ('tool_runtime', 'orchestrator_soft_hint')) -> list:
    blocked = {str(k or '').strip() for k in (remove_kinds or ()) if str(k or '').strip()}
    out = []
    for m in (messages or []):
        if not isinstance(m, dict):
            continue
        if str(m.get('role') or '').strip().lower() == 'system' and str(m.get('_kind') or '').strip() in blocked:
            continue
        out.append(dict(m))
    return out


def _runtime_location_visibility_safe_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    raw = str(value or '').strip().lower()
    if raw in {'1', 'true', 'yes', 'on', 'enabled', '开启'}:
        return True
    if raw in {'0', 'false', 'no', 'off', 'disabled', '关闭'}:
        return False
    return None


def _inject_runtime_location_visibility_context(messages: list | None = None, *, user_geo: dict | None = None, user_time: dict | None = None, debug_geo_meta: dict | None = None, location_state: dict | None = None) -> list:
    """Expose ChatGPT-like location visibility facts, not keyword triggers."""
    out = [dict(m) if isinstance(m, dict) else m for m in (messages or [])]
    try:
        for m in out:
            if isinstance(m, dict) and str(m.get('role') or '').strip().lower() == 'system' and str(m.get('_kind') or '').strip() == 'runtime_location_visibility':
                return out
    except Exception:
        return out

    meta = dict(debug_geo_meta or {}) if isinstance(debug_geo_meta, dict) else {}
    state = dict(location_state or {}) if isinstance(location_state, dict) else {}
    if not state and isinstance(meta.get('location_state'), dict):
        state = dict(meta.get('location_state') or {})
    if not state and isinstance(user_geo, dict) and isinstance(user_geo.get('_location_state'), dict):
        state = dict(user_geo.get('_location_state') or {})

    precise_state = state.get('precise_location') if isinstance(state.get('precise_location'), dict) else {}
    approx_state = state.get('approximate_location') if isinstance(state.get('approximate_location'), dict) else {}
    browser_geo = meta.get('browser_geo') if isinstance(meta.get('browser_geo'), dict) else {}

    lines = ['位置状态只说明本轮可见的位置能力；不按关键词触发，也不代表用户一定在问位置。']

    has_geo = False
    lat = lon = None
    if isinstance(user_geo, dict):
        try:
            lat = float(user_geo.get('lat'))
            lon = float(user_geo.get('lon'))
            has_geo = bool(-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0)
        except Exception:
            has_geo = False
    if not has_geo and isinstance(precise_state, dict):
        try:
            lat = float(precise_state.get('lat'))
            lon = float(precise_state.get('lon'))
            has_geo = bool(-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and bool(precise_state.get('available')))
        except Exception:
            has_geo = False

    precise_enabled = _runtime_location_visibility_safe_bool(precise_state.get('enabled'))
    if precise_enabled is None:
        precise_enabled = _runtime_location_visibility_safe_bool(meta.get('browser_geo_enabled'))
    if precise_enabled is None:
        precise_enabled = _runtime_location_visibility_safe_bool(browser_geo.get('browser_geo_enabled'))
    permission_state = str(precise_state.get('permission_state') or '').strip()
    can_request = _runtime_location_visibility_safe_bool(precise_state.get('can_request'))

    if has_geo:
        accuracy = precise_state.get('accuracy') if precise_state.get('accuracy') not in (None, '') else ((user_geo or {}).get('accuracy') if isinstance(user_geo, dict) else None)
        source_value = precise_state.get('source') or (((user_geo or {}).get('source')) if isinstance(user_geo, dict) else '') or meta.get('geo_source') or 'user_geo'
        source = str(source_value).strip() or 'user_geo'
        coord = f'lat={float(lat):.6f}, lon={float(lon):.6f}'
        if accuracy not in (None, ''):
            try:
                coord += f', accuracy≈{float(accuracy):.0f}m'
            except Exception:
                pass
        lines.append(f'精确位置=可用（{coord}, source={source}）。')
    else:
        status_bits = []
        if precise_enabled is not None:
            status_bits.append('应用定位开关=' + ('开启' if precise_enabled else '关闭'))
        if permission_state:
            status_bits.append('浏览器权限=' + permission_state)
        if can_request is not None:
            status_bits.append('当前页面可请求定位=' + ('yes' if can_request else 'no'))
        attach_mode = str(precise_state.get('attach_mode') or meta.get('geo_attach_mode') or '').strip()
        if attach_mode:
            status_bits.append('附带状态=' + attach_mode)
        if status_bits:
            lines.append('精确位置=无（' + '，'.join(status_bits) + '）。')
        else:
            lines.append('精确位置=无。')

    if isinstance(approx_state, dict) and bool(approx_state.get('available')):
        desc = str(approx_state.get('name') or approx_state.get('region') or approx_state.get('city') or '').strip()
        source = str(approx_state.get('source') or 'approximate').strip()
        lines.append(f'粗略位置=可用{("，" + desc) if desc else ""}，source={source}；不能当精确地址。')
    else:
        lines.append('粗略位置=无。')

    last_err = precise_state.get('last_error') if isinstance(precise_state.get('last_error'), dict) else None
    if last_err is None:
        last_err = browser_geo.get('last_geo_error') if isinstance(browser_geo.get('last_geo_error'), dict) else None
    if isinstance(last_err, dict):
        reason = str(last_err.get('reason') or last_err.get('name') or '').strip()
        if reason:
            lines.append(f'最近一次浏览器定位状态：{reason}。')

    lines.append('不要用时区推断地址；本地问题地点不足时可调用 get_location(request_precise=true) 或请用户补充。')

    sys_msg = {'role': 'system', '_kind': 'runtime_location_visibility', 'content': '\n'.join(lines)}
    insert_at = 0
    try:
        for i, m in enumerate(out):
            if isinstance(m, dict) and str(m.get('role') or '').strip().lower() == 'system':
                insert_at = i + 1
        out.insert(insert_at, sys_msg)
    except Exception:
        out.append(sys_msg)
    return out
