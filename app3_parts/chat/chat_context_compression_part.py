# Split from app3_parts/chat/chat_responses_adapter_part.py.
# Purpose: chat and Responses context compression helpers.
# Loaded by chat_responses_adapter_part.py via _exec_split_file(...), sharing app3.py globals.

def _chat_context_cfg(name: str = '', default: str = '') -> str:
    try:
        getter = globals().get('app_getenv')
        if callable(getter):
            return str(getter(str(name or ''), str(default or '')) or '')
    except Exception:
        pass
    try:
        return str(os.getenv(str(name or ''), str(default or '')) or '')
    except Exception:
        return str(default or '')


def _chat_context_cfg_bool(name: str = '', default: str = '1') -> bool:
    raw = _chat_context_cfg(name, default).strip().lower()
    return raw not in {'0', 'false', 'no', 'off', 'disabled'}


def _chat_context_cfg_int(name: str = '', default: int = 0, *, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        value = int(float(_chat_context_cfg(name, str(default))))
    except Exception:
        value = int(default or 0)
    if min_value is not None:
        value = max(int(min_value), value)
    if max_value is not None:
        value = min(int(max_value), value)
    return value


def _chat_context_payload_chars(value) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return len(str(value or ''))


def _chat_context_clip_text(text: str = '', limit: int = 0, *, preserve_tail: bool = True) -> str:
    text = str(text or '')
    limit = int(limit or 0)
    if limit <= 0 or len(text) <= limit:
        return text
    if limit < 120:
        return text[:limit]
    marker = '\n...【context compacted】...\n'
    if not preserve_tail or limit <= len(marker) + 80:
        return text[:max(1, limit - len(marker))].rstrip() + marker.strip()
    head = max(40, int((limit - len(marker)) * 0.55))
    tail = max(40, limit - len(marker) - head)
    return text[:head].rstrip() + marker + text[-tail:].lstrip()


def _chat_context_message_text(message: dict | None = None, *, include_image_text: bool = True) -> str:
    if not isinstance(message, dict):
        return ''
    content = message.get('content')
    if isinstance(content, str):
        return content.strip()
    try:
        helper = globals().get('_message_to_text_for_budget')
        if callable(helper):
            text = helper(message, include_images=False, include_image_text=include_image_text)
            text = str(text or '').strip()
            if text:
                return text
    except Exception:
        pass
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                typ = str(item.get('type') or '').strip().lower()
                if typ in {'text', 'input_text', 'output_text'}:
                    txt = str(item.get('text') or item.get('content') or item.get('output_text') or '').strip()
                    if txt:
                        parts.append(txt)
                elif typ in {'image_url', 'input_image'} and include_image_text:
                    parts.append('[image omitted from compacted context]')
            elif str(item or '').strip():
                parts.append(str(item or '').strip())
        return '\n'.join(parts).strip()
    if isinstance(content, dict):
        return str(content.get('text') or content.get('content') or content.get('answer') or '').strip()
    return str(content or '').strip()


def _chat_context_part_is_image(part) -> bool:
    if not isinstance(part, dict):
        return False
    typ = str(part.get('type') or '').strip().lower()
    if typ in {'image_url', 'input_image'}:
        return True
    if part.get('image') or part.get('file_id'):
        return True
    try:
        image_url = part.get('image_url')
        if isinstance(image_url, dict) and str(image_url.get('url') or '').strip():
            return True
        if isinstance(image_url, str) and image_url.strip():
            return True
    except Exception:
        pass
    return False


def _chat_context_message_has_image(message: dict | None = None) -> bool:
    if not isinstance(message, dict):
        return False
    content = message.get('content')
    if isinstance(content, list):
        return any(_chat_context_part_is_image(part) for part in content)
    if isinstance(content, dict):
        return _chat_context_part_is_image(content)
    return False


def _chat_context_compact_content_parts(content, *, role: str = 'user', text_limit: int = 2000, preserve_images: bool = False):
    role = str(role or 'user').strip().lower()
    text_type = 'text'
    if isinstance(content, str):
        return _chat_context_clip_text(content, text_limit)
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        text = str(content or '').strip()
        return _chat_context_clip_text(text, text_limit) if text else ''
    out: list = []
    text_parts: list[str] = []
    image_omitted = 0
    remaining = max(0, int(text_limit or 0))
    for part in content:
        if isinstance(part, dict) and _chat_context_part_is_image(part):
            if preserve_images:
                out.append(dict(part))
            else:
                image_omitted += 1
            continue
        txt = ''
        if isinstance(part, dict):
            txt = str(part.get('text') or part.get('content') or part.get('output_text') or '').strip()
        else:
            txt = str(part or '').strip()
        if not txt:
            continue
        if remaining > 0:
            clipped = _chat_context_clip_text(txt, remaining)
            text_parts.append(clipped)
            remaining -= len(clipped)
    if text_parts:
        joined = '\n'.join(text_parts).strip()
        out.insert(0, {'type': text_type, 'text': joined})
    if image_omitted and not preserve_images:
        notice = f'[{image_omitted} older image payload(s) omitted from compacted context]'
        out.append({'type': 'text', 'text': notice})
    return out if out else ''


def _chat_context_clone_message(message: dict | None = None, *, endpoint_mode: str = 'chat_completions', raw: bool = False, text_limit: int = 2000, preserve_images: bool = False, preserve_tool_protocol: bool = False) -> dict | None:
    if not isinstance(message, dict):
        return None
    role = str(message.get('role') or '').strip().lower()
    if not role:
        return None
    out = {'role': role}
    if raw:
        out.update(dict(message))
        return out
    if role in {'system', 'developer'}:
        content = _responses_instruction_text_from_content(message.get('content')) if endpoint_mode == 'responses' else _chat_context_message_text(message, include_image_text=False)
        out['content'] = _chat_context_clip_text(content, text_limit, preserve_tail=False)
        if isinstance(message.get('name'), str) and message.get('name'):
            out['name'] = message.get('name')
        if message.get('_kind'):
            out['_kind'] = message.get('_kind')
        return out if str(out.get('content') or '').strip() else None
    if role == 'tool':
        text = _chat_context_message_text(message, include_image_text=False)
        out['content'] = _chat_context_clip_text(text, text_limit, preserve_tail=True)
        if preserve_tool_protocol and isinstance(message.get('tool_call_id'), str) and message.get('tool_call_id'):
            out['tool_call_id'] = message.get('tool_call_id')
        if preserve_tool_protocol and isinstance(message.get('name'), str) and message.get('name'):
            out['name'] = message.get('name')
        if not preserve_tool_protocol:
            out['role'] = 'user'
            out['content'] = 'Tool result summary:\n' + str(out.get('content') or '')
        return out if str(out.get('content') or '').strip() else None
    content = message.get('content')
    out['content'] = _chat_context_compact_content_parts(content, role=role, text_limit=text_limit, preserve_images=preserve_images)
    if isinstance(message.get('name'), str) and message.get('name'):
        out['name'] = message.get('name')
    if preserve_tool_protocol:
        if isinstance(message.get('tool_calls'), list) and message.get('tool_calls'):
            out['tool_calls'] = message.get('tool_calls')
        if isinstance(message.get('function_call'), dict) and message.get('function_call'):
            out['function_call'] = message.get('function_call')
        if isinstance(message.get('tool_call_id'), str) and message.get('tool_call_id'):
            out['tool_call_id'] = message.get('tool_call_id')
    return out if out.get('content') or out.get('tool_calls') or out.get('function_call') else None


_CHAT_CONTEXT_TOKEN_ENCODER_CACHE: dict[str, object] = {}


def _chat_context_active_payload() -> dict:
    getter = globals().get('_webai_get_active_api_payload')
    if callable(getter):
        try:
            value = getter()
            if isinstance(value, dict):
                return value
        except Exception:
            pass
    return {}


def _chat_context_active_positive_int(*names: str) -> int:
    payload = _chat_context_active_payload()
    api_settings = payload.get('api_settings') if isinstance(payload.get('api_settings'), dict) else {}
    for source in (payload, api_settings):
        for name in names:
            try:
                value = int(float(source.get(name)))
            except Exception:
                value = 0
            if value > 0:
                return value
    return 0


def _chat_context_active_model_name() -> str:
    payload = _chat_context_active_payload()
    return str(payload.get('model') or payload.get('runtime_model') or '').strip()


def _chat_context_token_encoder(model: str = ''):
    model_name = str(model or '').strip()
    cache_key = model_name.lower() or 'o200k_base'
    if cache_key in _CHAT_CONTEXT_TOKEN_ENCODER_CACHE:
        return _CHAT_CONTEXT_TOKEN_ENCODER_CACHE.get(cache_key)
    encoder = None
    try:
        tiktoken = __import__('tiktoken')
        if model_name:
            try:
                encoder = tiktoken.encoding_for_model(model_name)
            except Exception:
                encoder = None
        if encoder is None:
            encoder = tiktoken.get_encoding('o200k_base')
    except Exception:
        encoder = None
    _CHAT_CONTEXT_TOKEN_ENCODER_CACHE[cache_key] = encoder
    return encoder


def _chat_context_estimate_tokens(value, *, model: str = '') -> int:
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str, separators=(',', ':'))
    except Exception:
        text = str(value or '')
    text = str(text or '')
    encoder = _chat_context_token_encoder(model)
    if encoder is not None:
        try:
            return max(1, len(encoder.encode(text, disallowed_special=())))
        except Exception:
            pass
    ascii_chars = 0
    cjk_chars = 0
    other_chars = 0
    for ch in text:
        code = ord(ch)
        if code <= 0x7f:
            ascii_chars += 1
        elif 0x3400 <= code <= 0x9fff or 0xf900 <= code <= 0xfaff:
            cjk_chars += 1
        else:
            other_chars += 1
    return max(1, int(math.ceil(ascii_chars / 4.0 + cjk_chars * 0.85 + other_chars / 2.0)))


def _compress_messages_for_llm_endpoint(messages: list | None = None, *, endpoint_mode: str = 'chat_completions', phase: str = '') -> list:
    if not isinstance(messages, list):
        return []
    endpoint_mode = _normalize_chat_api_endpoint_mode(endpoint_mode)
    base_messages = list(messages or [])
    try:
        deduper = globals().get('_orch_dedupe_model_messages')
        if callable(deduper):
            base_messages = deduper(base_messages)
    except Exception:
        pass
    if not _chat_context_cfg_bool('CHAT_CONTEXT_COMPRESSION_ENABLED', '1'):
        return base_messages

    context_window = _chat_context_active_positive_int(
        'generation_context_window_tokens', 'context_window_tokens',
        'context_window', 'max_context_tokens',
    )
    if context_window <= 0:
        return base_messages

    output_reserve = _chat_context_active_positive_int(
        'generation_max_tokens', 'generation_upstream_max_output_tokens', 'max_output_tokens',
        'max_completion_tokens', 'max_tokens',
    )
    if output_reserve <= 0:
        output_reserve = min(4096, max(1024, context_window // 16))
    safety_reserve = min(32768, max(1024, int(context_window * 0.08)))
    input_budget = max(2048, context_window - output_reserve - safety_reserve)
    model_name = _chat_context_active_model_name()
    original_tokens = _chat_context_estimate_tokens(messages or [], model=model_name)
    deduped_tokens = _chat_context_estimate_tokens(base_messages or [], model=model_name)
    original_chars = _chat_context_payload_chars(messages or [])
    if deduped_tokens <= input_budget:
        return base_messages

    try:
        cache_wanted = bool(_prompt_cache_runtime_wants_cache())
    except Exception:
        cache_wanted = False
    recent_key = 'RESPONSES_CONTEXT_RECENT_MESSAGES' if endpoint_mode == 'responses' else 'CHAT_CONTEXT_RECENT_MESSAGES'
    recent_limit = _chat_context_cfg_int(recent_key, 48 if cache_wanted else 16, min_value=2, max_value=160)
    old_key = 'RESPONSES_CONTEXT_OLD_MESSAGE_MAX_CHARS' if endpoint_mode == 'responses' else 'CHAT_CONTEXT_OLD_MESSAGE_MAX_CHARS'
    old_msg_limit = _chat_context_cfg_int(old_key, 80000 if cache_wanted else 4000, min_value=200, max_value=300000)
    recent_msg_limit = _chat_context_cfg_int('CHAT_CONTEXT_RECENT_MESSAGE_MAX_CHARS', 80000 if cache_wanted else 24000, min_value=1000, max_value=300000)
    latest_user_limit = _chat_context_cfg_int('CHAT_CONTEXT_LATEST_USER_MAX_CHARS', 160000 if cache_wanted else 90000, min_value=4000, max_value=500000)
    tool_limit = _chat_context_cfg_int('CHAT_CONTEXT_TOOL_MESSAGE_MAX_CHARS', 120000 if cache_wanted else 24000, min_value=1000, max_value=300000)
    system_limit = _chat_context_cfg_int(
        'RESPONSES_CONTEXT_SYSTEM_MESSAGE_MAX_CHARS' if endpoint_mode == 'responses' else 'CHAT_CONTEXT_SYSTEM_MESSAGE_MAX_CHARS',
        120000 if cache_wanted else 24000,
        min_value=1000,
        max_value=300000,
    )

    indexed = [(i, m) for i, m in enumerate(base_messages) if isinstance(m, dict)]
    latest_user_idx = None
    for i, message in reversed(indexed):
        if str(message.get('role') or '').strip().lower() == 'user':
            latest_user_idx = i
            break

    selected: dict[int, dict] = {}
    budget = input_budget
    for i, message in indexed:
        role = str(message.get('role') or '').strip().lower()
        if role not in {'system', 'developer'}:
            continue
        compacted_message = _chat_context_clone_message(
            message,
            endpoint_mode=endpoint_mode,
            raw=False,
            text_limit=system_limit,
            preserve_images=False,
        )
        if not compacted_message:
            continue
        cost = _chat_context_estimate_tokens(compacted_message, model=model_name)
        if cost <= budget:
            selected[i] = compacted_message
            budget -= cost

    recent_seen = 0
    dropped = 0
    compacted = 0
    for i, message in reversed(indexed):
        if i in selected:
            continue
        role = str(message.get('role') or '').strip().lower()
        if role in {'system', 'developer'}:
            continue
        is_latest_user = bool(latest_user_idx is not None and i == latest_user_idx)
        recent_seen += 1
        recent = recent_seen <= recent_limit
        if is_latest_user:
            text_limit = latest_user_limit
        elif role == 'tool':
            text_limit = tool_limit if recent else old_msg_limit
        elif recent:
            text_limit = recent_msg_limit
        else:
            text_limit = old_msg_limit
        compacted_message = _chat_context_clone_message(
            message,
            endpoint_mode=endpoint_mode,
            raw=False,
            text_limit=text_limit,
            preserve_images=is_latest_user,
            preserve_tool_protocol=bool(recent and endpoint_mode != 'responses'),
        )
        if not compacted_message:
            dropped += 1
            continue
        cost = _chat_context_estimate_tokens(compacted_message, model=model_name)
        if cost <= budget:
            selected[i] = compacted_message
            budget -= cost
            if not recent or _chat_context_payload_chars(compacted_message) < _chat_context_payload_chars(message):
                compacted += 1
            continue
        remaining_char_hint = max(240, min(text_limit, max(0, budget - 64) * 3))
        if remaining_char_hint > 240:
            tiny = _chat_context_clone_message(
                message,
                endpoint_mode=endpoint_mode,
                raw=False,
                text_limit=remaining_char_hint,
                preserve_images=False,
                preserve_tool_protocol=False,
            )
            tiny_cost = _chat_context_estimate_tokens(tiny, model=model_name) if tiny else 0
            if tiny and tiny_cost <= budget:
                selected[i] = tiny
                budget -= tiny_cost
                compacted += 1
                continue
        dropped += 1

    out = [selected[i] for i in sorted(selected.keys()) if selected.get(i)]
    if not out:
        return base_messages
    try:
        app_logger.info(
            '[CONTEXT_TOKEN_BUDGET] endpoint=%s phase=%s model=%s window_tokens=%s output_reserve=%s safety_reserve=%s input_budget=%s messages=%s->%s tokens=%s->%s chars=%s->%s compacted=%s dropped=%s',
            endpoint_mode,
            str(phase or ''),
            model_name,
            context_window,
            output_reserve,
            safety_reserve,
            input_budget,
            len(messages or []),
            len(out),
            original_tokens,
            _chat_context_estimate_tokens(out, model=model_name),
            original_chars,
            _chat_context_payload_chars(out),
            compacted,
            dropped,
        )
    except Exception:
        pass
    return out


def _compress_messages_for_chat_endpoint(messages: list | None = None, *, phase: str = '') -> list:
    return _compress_messages_for_llm_endpoint(messages or [], endpoint_mode='chat_completions', phase=phase)


def _compress_messages_for_responses_endpoint(messages: list | None = None, *, phase: str = '') -> list:
    return _compress_messages_for_llm_endpoint(messages or [], endpoint_mode='responses', phase=phase)


def _responses_input_item_chars(item) -> int:
    return _chat_context_payload_chars(item)


def _responses_input_item_has_image(item: dict | None = None) -> bool:
    if not isinstance(item, dict):
        return False
    content = item.get('content')
    if isinstance(content, list):
        return any(isinstance(part, dict) and str(part.get('type') or '').strip().lower() == 'input_image' for part in content)
    if isinstance(content, dict):
        return str(content.get('type') or '').strip().lower() == 'input_image'
    return False


def _compact_responses_input_item(item: dict | None = None, *, text_limit: int = 1600, preserve_images: bool = False, function_output_limit: int = 18000) -> dict | None:
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
        output = _chat_context_clip_text(str(output or ''), function_output_limit)
        return {'type': 'function_call_output', 'call_id': call_id, 'output': output} if call_id else None
    if typ == 'function_call':
        out = {
            'type': 'function_call',
            'name': str(item.get('name') or '').strip(),
            'arguments': _chat_context_clip_text(str(item.get('arguments') or '').strip(), max(800, min(text_limit, 6000)), preserve_tail=False),
            'call_id': str(item.get('call_id') or item.get('id') or '').strip(),
        }
        if item.get('id'):
            out['id'] = str(item.get('id') or '').strip()
        return out if out.get('name') and out.get('call_id') else None
    role = str(item.get('role') or 'user').strip().lower()
    if role not in {'user', 'assistant', 'system', 'developer'}:
        role = 'user'
    content = item.get('content')
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        text = _chat_context_clip_text(str(content or item.get('text') or '').strip(), text_limit)
        if not text:
            return None
        return {'role': role, 'content': [{'type': 'output_text' if role == 'assistant' else 'input_text', 'text': text}]}
    parts: list[dict] = []
    text_chunks: list[str] = []
    image_omitted = 0
    remain = max(0, int(text_limit or 0))
    for part in content:
        if not isinstance(part, dict):
            txt = str(part or '').strip()
            if txt and remain > 0:
                clipped = _chat_context_clip_text(txt, remain)
                text_chunks.append(clipped)
                remain -= len(clipped)
            continue
        ptyp = str(part.get('type') or '').strip().lower()
        if ptyp == 'input_image':
            if preserve_images:
                clean = {'type': 'input_image', 'detail': str(part.get('detail') or 'auto').strip() or 'auto'}
                if str(part.get('image_url') or '').strip():
                    clean['image_url'] = str(part.get('image_url') or '').strip()
                if str(part.get('file_id') or '').strip():
                    clean['file_id'] = str(part.get('file_id') or '').strip()
                parts.append(clean)
            else:
                image_omitted += 1
            continue
        txt = str(part.get('text') or part.get('content') or part.get('output_text') or '').strip()
        if txt and remain > 0:
            clipped = _chat_context_clip_text(txt, remain)
            text_chunks.append(clipped)
            remain -= len(clipped)
    if text_chunks:
        parts.insert(0, {'type': 'output_text' if role == 'assistant' else 'input_text', 'text': '\n'.join(text_chunks).strip()})
    if image_omitted:
        parts.append({'type': 'input_text', 'text': f'[{image_omitted} older image payload(s) omitted from compacted context]'})
    return {'role': role, 'content': parts} if parts else None


def _compress_responses_input_items_for_endpoint(input_items: list | None = None, *, phase: str = '') -> list:
    if not isinstance(input_items, list):
        return []
    if not _chat_context_cfg_bool('CHAT_CONTEXT_COMPRESSION_ENABLED', '1'):
        return list(input_items or [])
    try:
        cache_wanted = bool(_prompt_cache_runtime_wants_cache())
    except Exception:
        cache_wanted = False
    max_chars = _chat_context_cfg_int('RESPONSES_INPUT_MAX_CHARS', 800000 if cache_wanted else 90000, min_value=12000, max_value=1200000)
    if cache_wanted:
        cache_max_chars = _chat_context_cfg_int(
            'RESPONSES_PROMPT_CACHE_INPUT_MAX_CHARS',
            800000,
            min_value=24000,
            max_value=1200000,
        )
        max_chars = max(max_chars, cache_max_chars)
    original_chars = _chat_context_payload_chars(input_items or [])
    recent_limit = _chat_context_cfg_int('RESPONSES_INPUT_RECENT_ITEMS', 64 if cache_wanted else 14, min_value=2, max_value=200)
    old_msg_limit = _chat_context_cfg_int('RESPONSES_INPUT_OLD_ITEM_MAX_CHARS', 80000 if cache_wanted else 1200, min_value=200, max_value=300000)
    recent_msg_limit = _chat_context_cfg_int('RESPONSES_INPUT_RECENT_ITEM_MAX_CHARS', 120000 if cache_wanted else 14000, min_value=1000, max_value=300000)
    function_output_limit = _chat_context_cfg_int('RESPONSES_FUNCTION_OUTPUT_MAX_CHARS', 120000 if cache_wanted else 18000, min_value=1000, max_value=300000)
    if cache_wanted or original_chars > max_chars:
        try:
            app_logger.info(
                '[RESPONSES_INPUT_BUDGET] phase=%s cache_wanted=%s items=%s chars=%s max_chars=%s recent_limit=%s old_item_limit=%s recent_item_limit=%s function_output_limit=%s',
                str(phase or ''),
                bool(cache_wanted),
                len(input_items or []),
                original_chars,
                max_chars,
                recent_limit,
                old_msg_limit,
                recent_msg_limit,
                function_output_limit,
            )
        except Exception:
            pass
    if original_chars <= max_chars:
        return list(input_items or [])
    selected: dict[int, dict] = {}
    budget = max_chars
    dropped = 0
    compacted = 0
    recent_seen = 0
    for i, item in reversed(list(enumerate(input_items or []))):
        if not isinstance(item, dict):
            continue
        typ = str(item.get('type') or '').strip().lower()
        has_image = _responses_input_item_has_image(item)
        recent_seen += 1
        raw_recent = bool(recent_seen <= recent_limit)
        if typ in {'function_call', 'function_call_output'}:
            limit = function_output_limit
            preserve_images = False
        elif has_image:
            limit = recent_msg_limit
            preserve_images = True
        elif raw_recent:
            limit = recent_msg_limit
            preserve_images = False
        else:
            limit = old_msg_limit
            preserve_images = False
        mm = _compact_responses_input_item(item, text_limit=limit, preserve_images=preserve_images, function_output_limit=function_output_limit)
        if not mm:
            dropped += 1
            continue
        cost = _responses_input_item_chars(mm)
        if cost <= budget or has_image:
            selected[i] = mm
            budget -= cost
            if cost < _responses_input_item_chars(item):
                compacted += 1
            continue
        tiny_limit = max(240, min(old_msg_limit, budget - 200))
        if tiny_limit > 240 and typ not in {'function_call'}:
            tiny = _compact_responses_input_item(item, text_limit=tiny_limit, preserve_images=False, function_output_limit=max(800, tiny_limit))
            if tiny and _responses_input_item_chars(tiny) <= budget:
                selected[i] = tiny
                budget -= _responses_input_item_chars(tiny)
                compacted += 1
                continue
        dropped += 1
    out = [selected[i] for i in sorted(selected.keys()) if selected.get(i)]
    if not out:
        return list(input_items or [])
    try:
        app_logger.info('[RESPONSES_INPUT_COMPRESSION] phase=%s items=%s->%s chars=%s->%s compacted=%s dropped=%s', str(phase or ''), len(input_items or []), len(out), original_chars, _chat_context_payload_chars(out), compacted, dropped)
    except Exception:
        pass
    return out
