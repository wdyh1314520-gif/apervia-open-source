# Split from app3_parts/media/model_image_file_delivery_part.py.
# Purpose: stream collection, partial JSON preview, visible message, and URL helpers.
# Loaded by model_image_file_delivery_part.py via _exec_split_file(...), sharing the original global namespace.

def _collect_streamed_chat_message(stream_resp) -> dict:
    content_parts: list[str] = []
    tool_calls_by_index: dict[int, dict] = {}
    saw_chunk = False

    def _append_piece(base: str, piece) -> str:
        part = str(piece or '')
        if not part:
            return base
        if base.endswith(part):
            return base
        return base + part

    def _merge_tool_calls_from_node(node) -> None:
        tc_list = getattr(node, 'tool_calls', None) or []
        for tc in tc_list:
            try:
                idx = int(getattr(tc, 'index', 0) or 0)
            except Exception:
                idx = 0
            entry = tool_calls_by_index.setdefault(idx, {
                'id': '',
                'type': 'function',
                'function': {'name': '', 'arguments': ''},
            })
            tc_id = getattr(tc, 'id', None)
            if tc_id:
                entry['id'] = _append_piece(str(entry.get('id') or ''), tc_id)
            tc_type = getattr(tc, 'type', None)
            if tc_type:
                entry['type'] = str(tc_type)
            fn = getattr(tc, 'function', None)
            if fn is None:
                continue
            fn_name = getattr(fn, 'name', None)
            if fn_name:
                entry['function']['name'] = _append_piece(str((entry.get('function') or {}).get('name') or ''), fn_name)
            fn_args = getattr(fn, 'arguments', None)
            if fn_args:
                entry['function']['arguments'] = str((entry.get('function') or {}).get('arguments') or '') + str(fn_args)

    for chunk in stream_resp:
        saw_chunk = True
        choices = getattr(chunk, 'choices', None) or []
        if not choices:
            continue
        choice0 = choices[0]
        delta = getattr(choice0, 'delta', None)
        message = getattr(choice0, 'message', None)
        content = getattr(delta, 'content', None) if delta is not None else None
        if content:
            content_parts.append(str(content))
        elif message is not None:
            msg_content = getattr(message, 'content', None)
            if msg_content:
                content_parts.append(str(msg_content))
        if delta is not None:
            _merge_tool_calls_from_node(delta)
        if message is not None:
            _merge_tool_calls_from_node(message)

    tool_calls = []
    for idx in sorted(tool_calls_by_index.keys()):
        item = tool_calls_by_index.get(idx) or {}
        func = item.get('function') or {}
        if item.get('id') or func.get('name') or func.get('arguments'):
            tool_calls.append(item)

    return {
        'content': ''.join(content_parts),
        'tool_calls': tool_calls,
        'saw_chunk': saw_chunk,
    }


def _file_delivery_stream_chat_json_content(req: dict, *, client_override=None, purpose: str = '') -> str:
    """Run small JSON helper LLM calls through streaming instead of non-stream requests."""
    call_kwargs = dict(req or {})
    call_kwargs.pop('stream', None)
    model_name = str(call_kwargs.get('model') or '')
    try:
        app_logger.info('[LLM_CALL] purpose=%s stream=1 model=%s messages=%s tools=%s', str(purpose or 'file_aux_json'), model_name, len(call_kwargs.get('messages') or []), len(call_kwargs.get('tools') or []))
    except Exception:
        pass
    client_obj = client_override or client_gpt
    stream_resp = None
    try:
        creator = globals().get('_file_delivery_chat_completion_create_current_endpoint')
        if callable(creator):
            stream_resp = creator(client_obj, call_kwargs, stream=True)
        else:
            stream_resp = client_obj.chat.completions.create(stream=True, **call_kwargs)
        payload = _collect_streamed_chat_message(stream_resp)
        return str((payload or {}).get('content') or '').strip()
    finally:
        try:
            close_fn = getattr(stream_resp, 'close', None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass



def _decide_file_generation_gate(model: str, messages: list, *, prefetch_decision: dict | None = None, client_override=None) -> dict:
    """让模型先判断是否真的应该进入 sandbox artifact runtime。"""
    convo = []
    for m in (messages or [])[-8:]:
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '').strip()
        if role not in ('user', 'assistant', 'system'):
            continue
        content = _msg_content_text(m.get('content'))
        if not content:
            continue
        convo.append({'role': role, 'content': content[:1800]})

    prefetch_decision = dict(prefetch_decision or {})
    prefetch_file_action = str(prefetch_decision.get('file_action') or '').strip().lower()
    file_reason = str(prefetch_decision.get('file_reason') or '').strip()
    heuristic_hint = _file_delivery_soft_context(messages or []) or {}
    file_prompt = _build_file_delivery_soft_prompt(messages or [])
    hinted_mode = _normalize_file_delivery_mode(
        prefetch_decision.get('file_delivery_mode') or prefetch_decision.get('delivery_mode') or heuristic_hint.get('delivery_mode_hint'),
        user_text=str(heuristic_hint.get('user_text') or ''),
        info=heuristic_hint,
        default='single_file',
    )
    fallback_should = bool(heuristic_hint.get('wants_file')) or prefetch_file_action == 'sandbox_files'

    if not file_prompt and prefetch_file_action != 'sandbox_files':
        return {
            'should_enter_sandbox_files': False,
            'delivery_mode': 'none',
            'reason': 'no_signal',
            'source': 'skip',
        }

    contract_text = ''
    try:
        contract_builder = globals().get('prompt_contract_text')
        if callable(contract_builder):
            contract_text = str(contract_builder('file_delivery_gate', compact=True) or '').strip()
    except Exception:
        contract_text = ''
    judge_prompt = [
        {
            'role': 'system',
            'content': (
                ((contract_text + '\n') if contract_text else '')
                + '先判断用户最终是否想拿到真实可保存、可运行、可下载、可提交的文件/代码/页面交付物。'
                '不要把“生成图片/根据提示词生成图片”理解成“在文件里实现生图功能”，除非用户明确要求修改页面、代码或功能。'
                'delivery_mode：single_file 表示普通文件交付；zip_bundle 表示压缩包/项目包。'
                '这里只做入口判断，不要生成正文，不要输出代码，不要调用工具。'
            ),
        },
        *convo,
        {
            'role': 'user',
            'content': (
                f"文件交付线索：{file_prompt or '无明显文件线索'}\n"
                f"预判参考（仅作参考，不要机械服从）：action={prefetch_file_action or 'none'}；reason={file_reason[:160] or '无'}；delivery_mode={hinted_mode}\n"
                '请独立判断：这轮是否应该进入 sandbox artifact runtime 生成真实文件？如果要进入，再判断交付模式是 single_file 还是 zip_bundle。'
            ),
        },
    ]
    try:
        req = {
            'model': model,
            'messages': judge_prompt,
            'temperature': 0,
            'max_tokens': 160,
        }
        contract_format = globals().get('apply_prompt_contract_response_format')
        if callable(contract_format):
            req = contract_format(req, 'file_delivery_gate')
        else:
            req['response_format'] = {"type": "json_object"}
        msg = _file_delivery_stream_chat_json_content(req, client_override=client_override, purpose='sandbox_file_gate')
        obj = _safe_json_loads(msg) or {}
        should_enter_sandbox_files = bool(obj.get('should_enter_sandbox_files'))
        reason = str(obj.get('reason') or '').strip()
        delivery_mode = _normalize_file_delivery_mode(
            obj.get('delivery_mode'),
            user_text=str(heuristic_hint.get('user_text') or ''),
            info=heuristic_hint,
            default=hinted_mode if hinted_mode != 'none' else 'single_file',
        )
        if not should_enter_sandbox_files:
            delivery_mode = 'none'
        return {
            'should_enter_sandbox_files': should_enter_sandbox_files,
            'delivery_mode': delivery_mode,
            'reason': reason[:160],
            'source': 'model',
        }
    except Exception as e:
        app_logger.debug(f"[file_gate] fallback_to_hint: {type(e).__name__}: {e}")
        return {
            'should_enter_sandbox_files': fallback_should,
            'delivery_mode': hinted_mode if fallback_should else 'none',
            'reason': (file_reason[:160] or 'fallback_from_hint'),
            'source': 'fallback_hint',
        }


def _normalize_tool_calls_payload(tool_calls, round_index: int = 1) -> list[dict]:
    """Normalize tool call payloads into plain serializable dicts."""
    out: list[dict] = []
    for idx, tc in enumerate(tool_calls or []):
        if isinstance(tc, dict):
            call_id = str(tc.get('id') or '').strip()
            call_type = str(tc.get('type') or 'function').strip() or 'function'
            fn = dict(tc.get('function') or {})
            fn_name = str(fn.get('name') or '').strip()
            fn_args = fn.get('arguments')
        else:
            call_id = str(getattr(tc, 'id', None) or '').strip()
            call_type = str(getattr(tc, 'type', None) or 'function').strip() or 'function'
            fn_obj = getattr(tc, 'function', None)
            fn_name = str(getattr(fn_obj, 'name', None) or '').strip() if fn_obj is not None else ''
            fn_args = getattr(fn_obj, 'arguments', None) if fn_obj is not None else None

        if fn_args is None:
            args_text = '{}'
        elif isinstance(fn_args, str):
            args_text = fn_args
        else:
            try:
                args_text = json.dumps(fn_args, ensure_ascii=False)
            except Exception:
                args_text = str(fn_args)

        if not call_id:
            call_id = f'file_tool_call_{max(1, int(round_index or 1))}_{idx + 1}'

        if not fn_name:
            continue

        out.append({
            'id': call_id,
            'type': call_type,
            'function': {
                'name': fn_name,
                'arguments': args_text,
            },
        })
    return out




def _jsonish_unescape_preview_text(raw: str) -> str:
    text = str(raw or '')
    if not text:
        return ''
    text = text.replace('\\n', '\n').replace('\\r', '\r').replace('\\t', '\t').replace('\\/', '/').replace('\\\"', '"').replace("\\'", "'")
    try:
        text = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), text)
    except Exception:
        pass
    try:
        text = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), text)
    except Exception:
        pass
    return text


def _extract_partial_json_string_values(raw: str, key: str, *, max_count: int = 8, max_chars: int = 400) -> list[str]:
    text = str(raw or '')
    if not text or not key:
        return []
    token = f'"{str(key)}"'
    out: list[str] = []
    pos = 0
    while len(out) < max(1, int(max_count or 1)):
        idx = text.find(token, pos)
        if idx < 0:
            break
        colon = text.find(':', idx + len(token))
        if colon < 0:
            break
        quote = text.find('"', colon + 1)
        if quote < 0:
            break
        i = quote + 1
        buf: list[str] = []
        escaped = False
        while i < len(text) and len(buf) < max(16, int(max_chars or 16)):
            ch = text[i]
            if escaped:
                buf.append('\\' + ch)
                escaped = False
                i += 1
                continue
            if ch == '\\':
                escaped = True
                i += 1
                continue
            if ch == '"':
                break
            buf.append(ch)
            i += 1
        value = _jsonish_unescape_preview_text(''.join(buf)).strip()
        if value:
            out.append(value)
        pos = max(i + 1, idx + len(token))
    return out


def _looks_like_base64ish_preview(text: str) -> bool:
    raw = str(text or '').strip()
    if len(raw) < 96:
        return False
    compact = re.sub(r'\s+', '', raw)
    if len(compact) < 96:
        return False
    if re.fullmatch(r'[A-Za-z0-9+/=]+', compact or '') is None:
        return False
    unique_chars = len(set(compact))
    return unique_chars <= 40


def _build_file_generation_live_preview(snapshot: dict | None, *, preferred_mode: str = '') -> dict:
    snapshot = snapshot or {}
    preferred_mode = str(preferred_mode or '').strip()
    tool_calls = list(snapshot.get('tool_calls') or [])
    write_args_parts: list[str] = []
    replace_args_parts: list[str] = []
    read_args_parts: list[str] = []
    for tc in tool_calls:
        fn = dict((tc or {}).get('function') or {})
        name = str(fn.get('name') or '').strip()
        arguments = str(fn.get('arguments') or '')
        if not arguments.strip():
            continue
        if name in {'sandbox_write_file', 'sandbox_write_file', 'sandbox_write_files', 'sandbox_create_office_file'}:
            write_args_parts.append(arguments)
        elif name in {'sandbox_replace_text', 'sandbox_replace_text'}:
            replace_args_parts.append(arguments)
        elif name == 'sandbox_read_file':
            read_args_parts.append(arguments)
        elif preferred_mode == 'edit_existing':
            replace_args_parts.append(arguments)
        elif preferred_mode == 'generate_new':
            write_args_parts.append(arguments)

    edit_args_blob = '\n'.join(part for part in replace_args_parts if str(part or '').strip())
    if edit_args_blob:
        target_names: list[str] = []
        seen_targets: set[str] = set()
        for key in ('target_filename', 'output_filename'):
            for name in _extract_partial_json_string_values(edit_args_blob, key, max_count=12, max_chars=180):
                clean_name = str(name or '').strip()
                lowered = clean_name.lower()
                if not lowered or lowered in seen_targets:
                    continue
                seen_targets.add(lowered)
                target_names.append(clean_name)

        answer_values = _extract_partial_json_string_values(edit_args_blob, 'answer', max_count=1, max_chars=500)
        reason_values = _extract_partial_json_string_values(edit_args_blob, 'reason', max_count=8, max_chars=600)
        exact_old_values = _extract_partial_json_string_values(edit_args_blob, 'exact_old', max_count=10, max_chars=28000)
        replacement_values = _extract_partial_json_string_values(edit_args_blob, 'replacement', max_count=10, max_chars=42000)

        lead = '正在生成原始文件修改代码（可展开查看）'
        if target_names:
            lead += '：' + '、'.join(target_names[:6])
            if len(target_names) > 6:
                lead += f' 等 {len(target_names)} 个文件'

        text_parts: list[str] = [lead]
        answer_text = str(answer_values[0] if answer_values else '').strip()
        if answer_text:
            text_parts.append('说明：' + answer_text[:600])
        for idx, reason in enumerate(reason_values[:6], 1):
            reason_text = str(reason or '').strip()
            if reason_text:
                text_parts.append(f'修改原因 {idx}：{reason_text[:800]}')

        preview_count = 0
        max_items = max(len(replacement_values), len(exact_old_values), 1)
        for idx in range(min(max_items, 10)):
            replacement = str(replacement_values[idx] if idx < len(replacement_values) else '').replace('\r\n', '\n').replace('\r', '\n').strip()
            exact_old = str(exact_old_values[idx] if idx < len(exact_old_values) else '').replace('\r\n', '\n').replace('\r', '\n').strip()
            if not replacement and not exact_old:
                continue
            preview_count += 1
            block_parts = [f'===== 修改 {preview_count} / replacement（模型正在生成的新代码） =====']
            if replacement:
                block_parts.append(replacement[:42000].rstrip() + ('\n…' if len(replacement) > 42000 else ''))
            else:
                block_parts.append('（replacement 正在生成中…）')
            if exact_old:
                block_parts.append(f'----- exact_old（将被替换的原始代码片段） -----\n{exact_old[:28000].rstrip()}' + ('\n…' if len(exact_old) > 28000 else ''))
            text_parts.append('\n'.join(block_parts).strip())

        if preview_count <= 0:
            raw_tail = edit_args_blob[-24000:].strip()
            if raw_tail:
                text_parts.append('===== sandbox_replace_text 原始工具参数（生成中） =====\n' + raw_tail)
                preview_count = 1

        preview_text = '\n\n'.join(part for part in text_parts if str(part or '').strip()).strip()
        if len(preview_text) > 180000:
            preview_text = preview_text[:180000].rstrip() + '\n…'
        return {
            'text': preview_text,
            'filenames': target_names[:12],
            'status': '正在生成原始修改代码…',
            'artifact_count': len(target_names),
            'preview_count': preview_count,
            'mode': 'sandbox_replace_text',
        }

    read_args_blob = '\n'.join(part for part in read_args_parts if str(part or '').strip())
    if read_args_blob:
        target_values = _extract_partial_json_string_values(read_args_blob, 'target_filename', max_count=4, max_chars=180)
        query_values = _extract_partial_json_string_values(read_args_blob, 'symbol_or_query', max_count=2, max_chars=260)
        target_text = '、'.join([str(x or '').strip() for x in target_values if str(x or '').strip()])
        query_text = str(query_values[0] if query_values else '').strip()
        lines = ['正在读取原文件上下文…']
        if target_text:
            lines.append('目标文件：' + target_text)
        if query_text:
            lines.append('读取范围：' + query_text[:300])
        return {
            'text': '\n'.join(lines).strip(),
            'filenames': target_values[:8],
            'status': '正在读取原文件…',
            'artifact_count': 0,
            'preview_count': 0,
            'mode': 'sandbox_read_file',
        }

    args_blob = '\n'.join(part for part in write_args_parts if str(part or '').strip())
    if not args_blob:
        return {}

    filenames: list[str] = []
    seen_names: set[str] = set()
    for name in _extract_partial_json_string_values(args_blob, 'path', max_count=12, max_chars=180):
        clean_name = str(name or '').strip()
        lowered = clean_name.lower()
        if not lowered or lowered in seen_names:
            continue
        seen_names.add(lowered)
        filenames.append(clean_name)

    answer_values = _extract_partial_json_string_values(args_blob, 'answer', max_count=1, max_chars=320)
    answer_text = str(answer_values[0] if answer_values else '').strip()

    encoding_values = _extract_partial_json_string_values(args_blob, 'encoding', max_count=max(1, min(12, len(filenames) or 1)), max_chars=80)
    data_values = _extract_partial_json_string_values(args_blob, 'content', max_count=max(1, min(12, len(filenames) or 12)), max_chars=70000)

    def _preview_encoding_for(index: int) -> str:
        if index < len(encoding_values):
            return str(encoding_values[index] or '').strip().lower()
        if len(encoding_values) == 1:
            return str(encoding_values[0] or '').strip().lower()
        return ''

    def _clean_preview_data(value: str, *, encoding_text: str = '') -> str:
        data_text = str(value or '').strip()
        encoding_text = str(encoding_text or '').strip().lower()
        if encoding_text == 'base64' or _looks_like_base64ish_preview(data_text):
            return ''
        if not data_text:
            return ''
        data_text = data_text.replace('\r\n', '\n').replace('\r', '\n').strip()
        if len(data_text) > 70000:
            data_text = data_text[:70000].rstrip() + '\n…'
        return data_text

    artifact_previews: list[dict] = []
    max_rows = max(len(filenames), len(data_values))
    for idx in range(min(max_rows, 12)):
        filename = filenames[idx] if idx < len(filenames) else f'文件 {idx + 1}'
        encoding_text = _preview_encoding_for(idx)
        raw_data = data_values[idx] if idx < len(data_values) else ''
        data_text = _clean_preview_data(raw_data, encoding_text=encoding_text)
        if filename or data_text:
            artifact_previews.append({
                'filename': filename,
                'data': data_text,
                'encoding': encoding_text,
            })

    if answer_text:
        answer_text = answer_text[:260].strip()

    lead = ''
    if filenames:
        show_names = filenames[:8]
        more = len(filenames) - len(show_names)
        lead = '正在写入：' + '、'.join(show_names)
        if more > 0:
            lead += f' 等 {len(filenames)} 个文件'
    elif answer_text:
        lead = '正在整理文件说明…'
    elif any(str(item.get('data') or '').strip() for item in artifact_previews):
        lead = '正在写入文件内容…'
    else:
        lead = '正在生成文件…'

    text_parts = [lead]
    if answer_text and answer_text not in text_parts:
        text_parts.append(answer_text)

    available_data_count = 0
    for item in artifact_previews:
        data_text = str(item.get('data') or '').strip()
        filename = str(item.get('filename') or '').strip()
        if not data_text:
            continue
        available_data_count += 1
        title = f'===== {filename or ("文件 " + str(available_data_count))} ====='
        text_parts.append(f'{title}\n{data_text}')

    preview_text = '\n\n'.join(part for part in text_parts if str(part or '').strip()).strip()
    if not preview_text:
        return {}

    if len(preview_text) > 180000:
        preview_text = preview_text[:180000].rstrip() + '\n…'

    if any(str(item.get('data') or '').strip() for item in artifact_previews):
        status_text = '正在写入文件内容…'
    elif filenames:
        status_text = '正在准备文件内容…'
    else:
        status_text = '正在生成文件…'

    return {
        'text': preview_text,
        'filenames': filenames[:12],
        'status': status_text,
        'artifact_count': len(filenames),
        'preview_count': available_data_count,
        'mode': 'sandbox_write_file',
    }


def _file_delivery_office_generation_requested(gate: dict | None = None, info: dict | None = None) -> bool:
    """Office 文件统一交给 sandbox_create_office_file，不再启用旧直写分支。"""
    return False



def _file_delivery_model_visible_messages(messages: list | None = None) -> list:
    """Return only API-safe messages for the file-tool LLM call.

    Sandbox artifact routing also needs the raw uploaded/generated file records so
    server-side tools can read and edit the user's real files. Those records are
    kept in a side channel and must not be sent to the model as malformed chat
    messages.
    """
    safe: list[dict] = []
    for m in (messages or []):
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '').strip().lower()
        content = m.get('content')
        if role == 'system' and str(m.get('_kind') or '').strip() == '__meta__':
            continue
        if role == 'user' and isinstance(content, dict) and str(content.get('_kind') or '').strip() == 'file':
            continue
        if role == 'assistant' and isinstance(content, dict) and str(content.get('_kind') or '').strip() == 'genfiles':
            continue
        safe.append(dict(m))
    return _sanitize_messages_for_model(safe)


def _file_delivery_code_fence_to_ext(lang: str = '') -> str:
    raw = str(lang or '').strip().lower()
    aliases = {
        'html': 'html', 'htm': 'html', 'xml': 'xml', 'svg': 'svg',
        'css': 'css', 'scss': 'scss', 'less': 'less',
        'javascript': 'js', 'js': 'js', 'jsx': 'jsx', 'typescript': 'ts', 'ts': 'ts', 'tsx': 'tsx',
        'python': 'py', 'py': 'py', 'java': 'java', 'go': 'go', 'rust': 'rs', 'rs': 'rs',
        'php': 'php', 'ruby': 'rb', 'rb': 'rb', 'swift': 'swift', 'kotlin': 'kt', 'kt': 'kt',
        'c': 'c', 'cpp': 'cpp', 'c++': 'cpp', 'cs': 'cs', 'csharp': 'cs',
        'json': 'json', 'yaml': 'yml', 'yml': 'yml', 'toml': 'toml',
        'markdown': 'md', 'md': 'md', 'csv': 'csv', 'txt': 'txt', 'text': 'txt',
        'shell': 'sh', 'bash': 'sh', 'sh': 'sh', 'powershell': 'ps1', 'ps1': 'ps1',
    }
    return aliases.get(raw, '')


def _cut_url_at_cjk(u: str) -> str:
    '''Cut URL at first CJK char (handles cases like https://.../repo这是干什么).'''
    if not u:
        return ''
    for i, ch in enumerate(u):
        if '\u4e00' <= ch <= '\u9fff':
            return u[:i]
    return u


def _extract_urls(text: str) -> list[str]:
    """从文本中提取 URL（尽量宽松）。"""
    if not text:
        return []
    urls = re.findall(r"https?://[^\s<>'\"]+", text)
    cleaned: list[str] = []
    seen: set[str] = set()
    for u in urls:
        u = u.rstrip(').,;:!?"\'」』）】>')  # 去掉尾部常见标点
        u = u.strip()
        u = _cut_url_at_cjk(u).strip()
        if not u:
            continue
        try:
            pu = urlparse(u)
            if pu.scheme not in ("http", "https") or not pu.netloc:
                continue
        except Exception:
            continue
        if u not in seen:
            seen.add(u)
            cleaned.append(u)
    return cleaned

def _first_url_and_tail(text: str):
    """Return (url, tail_text). Split "URL + extra instruction" in one message."""
    if not text:
        return None, ""
    s = str(text)

    m = re.search(r'(https?://[^\s<>"\']+)', s)
    if not m:
        return None, s.strip()

    raw = m.group(1).strip().rstrip(').】》>，。,;；!！?？"\'』」）')
    raw = _cut_url_at_cjk(raw).strip()

    # If user appended Chinese right after URL path, split it out
    cjk = re.search(r'[\u4e00-\u9fff]', raw)
    if cjk:
        idx = cjk.start()
        url = raw[:idx]
        tail = raw[idx:] + " " + s[m.end():]
    else:
        url = raw
        tail = (s[:m.start()] + " " + s[m.end():]).strip()

    return url.strip(), (tail or "").strip()
