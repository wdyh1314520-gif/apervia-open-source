# file-delivery Chat/Responses compatibility adapter.

class _FileDeliveryCompatObj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _file_delivery_endpoint_mode_from_client(client_obj=None) -> str:
    try:
        normalizer = globals().get('_normalize_payload_api_endpoint_mode') or globals().get('_normalize_chat_api_endpoint_mode')
        raw = getattr(client_obj, '_webai_api_endpoint_mode', '') or 'chat_completions'
        if callable(normalizer):
            return str(normalizer(raw) or 'chat_completions')
    except Exception:
        pass
    raw = str(getattr(client_obj, '_webai_api_endpoint_mode', '') or 'chat_completions').strip().lower()
    return 'responses' if raw in {'responses', 'response', '/responses'} else 'chat_completions'


def _file_delivery_responses_endpoint_from_base_url(base_url: str = '') -> str:
    helper = globals().get('_responses_endpoint_from_base_url')
    if callable(helper):
        try:
            endpoint = str(helper(base_url) or '').strip()
            if endpoint:
                return endpoint
        except Exception:
            pass
    raw = str(base_url or '').strip() or str(globals().get('GPT_BASE_URL') or '').strip()
    raw = raw.rstrip('/')
    lowered = raw.lower()
    for suffix in ('/chat/completions', '/responses', '/completions'):
        if lowered.endswith(suffix):
            raw = raw[:-len(suffix)].rstrip('/')
            lowered = raw.lower()
            break
    try:
        parsed = urlparse(raw)
        if parsed.scheme and parsed.netloc:
            path = str(parsed.path or '').rstrip('/')
            if not path.strip('/'):
                raw = urlunparse((parsed.scheme, parsed.netloc, '', '', '', ''))
    except Exception:
        pass
    return raw.rstrip('/') + '/responses' if raw else ''


def _file_delivery_responses_input_content(content):
    helper = globals().get('_responses_input_content_from_chat_content')
    if callable(helper):
        try:
            return helper(content)
        except Exception:
            pass
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    out.append({'type': 'input_text', 'text': item})
                continue
            if not isinstance(item, dict):
                text = str(item or '').strip()
                if text:
                    out.append({'type': 'input_text', 'text': text})
                continue
            typ = str(item.get('type') or '').strip().lower()
            if typ == 'text':
                text = str(item.get('text') or '').strip()
                if text:
                    out.append({'type': 'input_text', 'text': text})
            elif typ == 'image_url':
                url = str(((item.get('image_url') or {}).get('url')) or '').strip()
                if url:
                    out.append({'type': 'input_image', 'image_url': url, 'detail': 'auto'})
            elif typ == 'input_image':
                image_url = str(item.get('image_url') or item.get('url') or '').strip()
                file_id = str(item.get('file_id') or '').strip()
                detail = str(item.get('detail') or 'auto').strip() or 'auto'
                if image_url or file_id:
                    img = {'type': 'input_image', 'detail': detail}
                    if image_url:
                        img['image_url'] = image_url
                    if file_id:
                        img['file_id'] = file_id
                    out.append(img)
            else:
                text = str(item.get('text') or item.get('content') or '').strip()
                if text:
                    out.append({'type': 'input_text', 'text': text})
        return out or ''
    if isinstance(content, dict):
        return str(content.get('text') or content.get('content') or content.get('answer') or '').strip()
    return str(content or '')


def _file_delivery_responses_instructions_from_messages(messages: list | None = None) -> str:
    helper = globals().get('_responses_instructions_from_chat_messages')
    if callable(helper):
        try:
            return str(helper(messages or []) or '').strip()
        except Exception:
            pass
    lines = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '').strip().lower()
        if role not in {'system', 'developer'}:
            continue
        text = str(m.get('content') or '').strip()
        if text:
            lines.append(('Developer instructions' if role == 'developer' else 'System instructions') + ':\n' + text)
    return '\n\n'.join(lines).strip() or 'Follow the user request and use the provided file tools when needed.'


def _file_delivery_responses_input_from_messages(messages: list | None = None) -> list[dict]:
    out: list[dict] = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or 'user').strip().lower()
        if role in {'system', 'developer'}:
            continue
        if role == 'assistant':
            tool_calls = list(m.get('tool_calls') or []) if isinstance(m.get('tool_calls'), list) else []
            if tool_calls:
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get('function') if isinstance(tc.get('function'), dict) else {}
                    name = str((fn or {}).get('name') or '').strip()
                    if not name:
                        continue
                    call_id = str(tc.get('id') or '').strip() or ('call_' + uuid.uuid4().hex[:18])
                    args = str((fn or {}).get('arguments') or '{}').strip() or '{}'
                    out.append({'type': 'function_call', 'call_id': call_id, 'name': name, 'arguments': args})
            content = _file_delivery_responses_input_content(m.get('content'))
            if isinstance(content, str) and content.strip():
                out.append({'role': 'assistant', 'content': content})
            elif isinstance(content, list) and content:
                out.append({'role': 'assistant', 'content': content})
            continue
        if role == 'tool':
            call_id = str(m.get('tool_call_id') or '').strip() or ('call_' + uuid.uuid4().hex[:18])
            out.append({'type': 'function_call_output', 'call_id': call_id, 'output': str(m.get('content') or '')[:200000]})
            continue
        if role not in {'user', 'assistant'}:
            role = 'user'
        content = _file_delivery_responses_input_content(m.get('content'))
        if isinstance(content, str) and not content.strip():
            continue
        if isinstance(content, list) and not content:
            continue
        out.append({'role': role, 'content': content})
    return out


def _file_delivery_responses_tool_specs(chat_tools: list | None = None) -> list[dict]:
    specs: list[dict] = []
    for item in chat_tools or []:
        if not isinstance(item, dict):
            continue
        if str(item.get('type') or '').strip() == 'function' and isinstance(item.get('function'), dict):
            fn = item.get('function') or {}
            name = str(fn.get('name') or '').strip()
            if not name:
                continue
            spec = {
                'type': 'function',
                'name': name,
                'description': str(fn.get('description') or '').strip(),
                'parameters': fn.get('parameters') if isinstance(fn.get('parameters'), dict) else {'type': 'object', 'properties': {}},
            }
            specs.append(spec)
            continue
        if str(item.get('type') or '').strip() == 'function' and str(item.get('name') or '').strip():
            specs.append(dict(item))
    return specs


def _file_delivery_responses_tool_choice(chat_tool_choice=None):
    if chat_tool_choice is None:
        return 'auto'
    if isinstance(chat_tool_choice, str):
        raw = chat_tool_choice.strip().lower()
        return raw if raw in {'auto', 'none', 'required'} else 'auto'
    if isinstance(chat_tool_choice, dict):
        if str(chat_tool_choice.get('type') or '').strip() == 'function':
            fn = chat_tool_choice.get('function') if isinstance(chat_tool_choice.get('function'), dict) else {}
            name = str((fn or {}).get('name') or chat_tool_choice.get('name') or '').strip()
            if name:
                return {'type': 'function', 'name': name}
        raw = str(chat_tool_choice.get('mode') or chat_tool_choice.get('choice') or '').strip().lower()
        if raw in {'auto', 'none', 'required'}:
            return raw
    return 'auto'


def _file_delivery_responses_body_from_chat_kwargs(call_kwargs: dict | None = None, *, stream: bool = False) -> dict:
    call_kwargs = dict(call_kwargs or {})
    messages = list(call_kwargs.get('messages') or [])
    body = {
        'model': str(call_kwargs.get('model') or '').strip(),
        'instructions': _file_delivery_responses_instructions_from_messages(messages),
        'input': _file_delivery_responses_input_from_messages(messages),
        'stream': bool(stream),
    }
    tools = _file_delivery_responses_tool_specs(call_kwargs.get('tools') or [])
    if tools:
        body['tools'] = tools
        body['tool_choice'] = _file_delivery_responses_tool_choice(call_kwargs.get('tool_choice'))
    reasoning_helper = globals().get('_responses_extra_body_with_reasoning_summary')
    if callable(reasoning_helper):
        try:
            extra = reasoning_helper({}) or {}
            if isinstance(extra, dict):
                for k, v in extra.items():
                    key = str(k or '').strip()
                    if key and key not in {'model', 'input', 'messages', 'stream', 'tools', 'tool_choice'}:
                        body[key] = v
        except Exception:
            pass
    return body


def _file_delivery_extract_response_text(payload) -> str:
    helper = globals().get('_extract_responses_text_payload')
    if callable(helper):
        try:
            return str(helper(payload) or '')
        except Exception:
            pass
    if not isinstance(payload, dict):
        return ''
    direct = str(payload.get('output_text') or '').strip()
    if direct:
        return direct
    parts = []
    for item in payload.get('output') or []:
        if isinstance(item, dict):
            for block in item.get('content') or []:
                if isinstance(block, dict):
                    text = block.get('text') or block.get('output_text') or block.get('content')
                    if text:
                        parts.append(str(text))
    return ''.join(parts)


def _file_delivery_response_items(payload) -> list[dict]:
    if not isinstance(payload, dict):
        try:
            payload = payload.model_dump()
        except Exception:
            return []
    root = payload.get('response') if isinstance(payload.get('response'), dict) else payload
    out = []
    for item in (root.get('output') or root.get('items') or []):
        if isinstance(item, dict):
            out.append(item)
    item = root.get('item') if isinstance(root.get('item'), dict) else None
    if item:
        out.append(item)
    if str(root.get('type') or '').strip().lower() in {'function_call', 'tool_call'}:
        out.append(root)
    return out


def _file_delivery_calls_from_response_payload(payload) -> list[dict]:
    calls: list[dict] = []
    for idx, item in enumerate(_file_delivery_response_items(payload)):
        typ = str(item.get('type') or item.get('kind') or '').strip().lower()
        if typ not in {'function_call', 'tool_call'} and 'function_call' not in typ:
            continue
        name = str(item.get('name') or item.get('function_name') or '').strip()
        fn_obj = item.get('function') if isinstance(item.get('function'), dict) else {}
        if not name:
            name = str((fn_obj or {}).get('name') or '').strip()
        args = item.get('arguments')
        if args is None:
            args = (fn_obj or {}).get('arguments')
        if isinstance(args, dict):
            args = json.dumps(args, ensure_ascii=False)
        args = str(args or '').strip() or '{}'
        if not name:
            continue
        call_id = str(item.get('call_id') or item.get('id') or '').strip() or ('call_' + uuid.uuid4().hex[:18])
        calls.append({
            'id': call_id,
            'type': 'function',
            'function': {'name': name, 'arguments': args},
            '_index': idx,
        })
    return calls


def _file_delivery_chat_completion_compat_response(content: str = '', tool_calls: list[dict] | None = None):
    tc_objs = []
    for i, tc in enumerate(tool_calls or []):
        fn = tc.get('function') if isinstance(tc, dict) else {}
        tc_objs.append(_FileDeliveryCompatObj(
            id=str((tc or {}).get('id') or '').strip(),
            type=str((tc or {}).get('type') or 'function') or 'function',
            function=_FileDeliveryCompatObj(
                name=str((fn or {}).get('name') or '').strip(),
                arguments=str((fn or {}).get('arguments') or ''),
            ),
            index=int((tc or {}).get('_index') if (tc or {}).get('_index') is not None else i),
        ))
    msg = _FileDeliveryCompatObj(content=str(content or ''), tool_calls=tc_objs)
    choice = _FileDeliveryCompatObj(message=msg, delta=_FileDeliveryCompatObj(content=''), finish_reason='tool_calls' if tc_objs else 'stop')
    return _FileDeliveryCompatObj(choices=[choice])


def _file_delivery_chat_completion_compat_chunk(*, content: str = '', tool_call: dict | None = None, finish_reason: str = ''):
    delta_kwargs = {'content': str(content or '')}
    if tool_call:
        fn = tool_call.get('function') if isinstance(tool_call.get('function'), dict) else {}
        delta_kwargs['tool_calls'] = [_FileDeliveryCompatObj(
            index=int(tool_call.get('index') or tool_call.get('_index') or 0),
            id=str(tool_call.get('id') or ''),
            type=str(tool_call.get('type') or 'function') or 'function',
            function=_FileDeliveryCompatObj(
                name=str((fn or {}).get('name') or ''),
                arguments=str((fn or {}).get('arguments') or ''),
            ),
        )]
    delta = _FileDeliveryCompatObj(**delta_kwargs)
    choice = _FileDeliveryCompatObj(delta=delta, message=_FileDeliveryCompatObj(content=str(content or '')), finish_reason=finish_reason)
    return _FileDeliveryCompatObj(choices=[choice])


def _file_delivery_responses_nonstream_create_chat_compat(client_obj=None, call_kwargs: dict | None = None):
    api_key, base_url = _resolve_openai_client_identity(client_obj)
    endpoint = _file_delivery_responses_endpoint_from_base_url(base_url)
    if not endpoint:
        raise RuntimeError('Responses API endpoint missing')
    body = _file_delivery_responses_body_from_chat_kwargs(call_kwargs or {}, stream=False)
    body.pop('stream', None)
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    http_client = globals().get('HTTPX_GPT_FILE') or globals().get('HTTPX_GPT')
    own_client = None
    if http_client is None:
        own_client = httpx.Client(verify=globals().get('tls_verify', True), timeout=900.0, follow_redirects=True)
        http_client = own_client
    try:
        try:
            app_logger.info('[FILE_RESPONSES_CALL] stream=0 endpoint=%s model=%s tools=%s body_keys=%s', endpoint, body.get('model'), len(body.get('tools') or []), sorted(str(k) for k in body.keys()))
        except Exception:
            pass
        timeout = (call_kwargs or {}).get('timeout') or None
        resp = http_client.post(endpoint, headers=headers, json=body, timeout=timeout)
        if int(getattr(resp, 'status_code', 0) or 0) >= 400:
            try:
                err_text = resp.text
            except Exception:
                err_text = ''
            raise RuntimeError(f'Reponses API error {resp.status_code}: {err_text[:4000]}')
        payload = resp.json() if getattr(resp, 'content', b'') else {}
        return _file_delivery_chat_completion_compat_response(_file_delivery_extract_response_text(payload), _file_delivery_calls_from_response_payload(payload))
    finally:
        if own_client is not None:
            try:
                own_client.close()
            except Exception:
                pass


def _file_delivery_responses_stream_create_chat_compat(client_obj=None, call_kwargs: dict | None = None):
    api_key, base_url = _resolve_openai_client_identity(client_obj)
    endpoint = _file_delivery_responses_endpoint_from_base_url(base_url)
    if not endpoint:
        raise RuntimeError('Responses API endpoint missing')
    body = _file_delivery_responses_body_from_chat_kwargs(call_kwargs or {}, stream=True)
    headers = {'Accept': 'text/event-stream', 'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    http_client = globals().get('HTTPX_GPT_FILE') or globals().get('HTTPX_GPT')
    own_client = None
    if http_client is None:
        own_client = httpx.Client(verify=globals().get('tls_verify', True), timeout=900.0, follow_redirects=True)
        http_client = own_client

    def _iter():
        calls: dict[str, dict] = {}
        completed_payload = None

        def _call_key(payload: dict, item: dict | None = None) -> str:
            item = item if isinstance(item, dict) else {}
            for key in ('item_id', 'output_item_id', 'call_id', 'id'):
                value = str(payload.get(key) or item.get(key) or '').strip()
                if value:
                    return value
            try:
                return 'idx_' + str(int(payload.get('output_index') or item.get('output_index') or 0))
            except Exception:
                return 'idx_0'

        def _index_for_key(key: str) -> int:
            keys = list(calls.keys())
            if key not in calls:
                keys.append(key)
            return max(0, keys.index(key))

        def _merge_item(payload: dict, item: dict | None = None) -> list:
            item = item if isinstance(item, dict) else payload
            typ = str((item or {}).get('type') or (item or {}).get('kind') or '').strip().lower()
            if typ not in {'function_call', 'tool_call'} and 'function_call' not in typ:
                return []
            key = _call_key(payload, item)
            entry = calls.setdefault(key, {'id': '', 'name': '', 'arguments': '', 'sent_name': False, 'sent_args_len': 0, 'index': _index_for_key(key)})
            entry['id'] = str((item or {}).get('call_id') or (item or {}).get('id') or entry.get('id') or key).strip()
            fn = (item or {}).get('function') if isinstance((item or {}).get('function'), dict) else {}
            name = str((item or {}).get('name') or (fn or {}).get('name') or entry.get('name') or '').strip()
            if name:
                entry['name'] = name
            args = (item or {}).get('arguments')
            if args is None:
                args = (fn or {}).get('arguments')
            if isinstance(args, dict):
                args = json.dumps(args, ensure_ascii=False)
            if args is not None and str(args) and len(str(args)) > len(str(entry.get('arguments') or '')):
                entry['arguments'] = str(args)
            return _delta_chunks_for_entry(entry)

        def _merge_args_delta(payload: dict, event_type: str = '') -> list:
            key = _call_key(payload)
            entry = calls.setdefault(key, {'id': str(payload.get('call_id') or key), 'name': '', 'arguments': '', 'sent_name': False, 'sent_args_len': 0, 'index': _index_for_key(key)})
            delta = payload.get('delta')
            if delta is None:
                delta = payload.get('arguments_delta') or payload.get('arguments') or ''
            if isinstance(delta, dict):
                delta = json.dumps(delta, ensure_ascii=False)
            if delta:
                if 'done' in str(event_type or '').lower() or str(event_type or '').lower().endswith('.completed'):
                    entry['arguments'] = str(delta)
                else:
                    entry['arguments'] = str(entry.get('arguments') or '') + str(delta)
            return _delta_chunks_for_entry(entry)

        def _delta_chunks_for_entry(entry: dict) -> list:
            chunks = []
            index = int(entry.get('index') or 0)
            call_id = str(entry.get('id') or '').strip()
            name = str(entry.get('name') or '').strip()
            if name and not entry.get('sent_name'):
                entry['sent_name'] = True
                chunks.append(_file_delivery_chat_completion_compat_chunk(tool_call={'index': index, 'id': call_id, 'type': 'function', 'function': {'name': name, 'arguments': ''}}))
            args = str(entry.get('arguments') or '')
            sent_len = int(entry.get('sent_args_len') or 0)
            if len(args) > sent_len:
                piece = args[sent_len:]
                entry['sent_args_len'] = len(args)
                chunks.append(_file_delivery_chat_completion_compat_chunk(tool_call={'index': index, 'id': '' if entry.get('sent_name') else call_id, 'type': 'function', 'function': {'name': '', 'arguments': piece}}))
            return chunks

        def _handle_payload(payload, event_name: str = '') -> list:
            nonlocal completed_payload
            frames = []
            if not isinstance(payload, dict):
                return frames
            is_err_helper = globals().get('_responses_sse_payload_is_error')
            if callable(is_err_helper):
                try:
                    is_err, err_text = is_err_helper(payload, event_name)
                    if is_err:
                        raise RuntimeError(f'Responses API stream error: {str(err_text or "")[:4000]}')
                except RuntimeError:
                    raise
                except Exception:
                    pass
            event_type = str(event_name or payload.get('type') or payload.get('event') or '').strip()
            if event_type in {'response.completed', 'response.done'}:
                completed_payload = payload
            item = payload.get('item') if isinstance(payload.get('item'), dict) else (payload.get('output_item') if isinstance(payload.get('output_item'), dict) else None)
            if item:
                frames.extend(_merge_item(payload, item))
            if str(payload.get('type') or '').strip().lower() in {'function_call', 'tool_call'}:
                frames.extend(_merge_item(payload, payload))
            event_low = event_type.lower()
            if 'function_call_arguments' in event_low or 'arguments.delta' in event_low or event_low.endswith('.arguments.done') or event_low.endswith('.arguments_delta'):
                frames.extend(_merge_args_delta(payload, event_type))
            text_delta = ''
            delta_helper = globals().get('_responses_extract_delta_from_sse_payload')
            if callable(delta_helper):
                try:
                    text_delta = str(delta_helper(payload, event_type) or '')
                except Exception:
                    text_delta = ''
            elif event_low in {'response.output_text.delta', 'output_text.delta', 'text.delta'}:
                text_delta = str(payload.get('delta') or payload.get('text') or '')
            if text_delta:
                frames.append(_file_delivery_chat_completion_compat_chunk(content=text_delta))
            return frames

        def _plain_text_frame(raw_data, _event_name=''):
            return [_file_delivery_chat_completion_compat_chunk(content=raw_data)]

        try:
            try:
                app_logger.info('[FILE_RESPONSES_CALL] stream=1 endpoint=%s model=%s tools=%s body_keys=%s', endpoint, body.get('model'), len(body.get('tools') or []), sorted(str(k) for k in body.keys()))
            except Exception:
                pass
            with http_client.stream('POST', endpoint, headers=headers, json=body, timeout=(call_kwargs or {}).get('timeout') or None) as resp:
                if int(getattr(resp, 'status_code', 0) or 0) >= 400:
                    try:
                        err_text = resp.read().decode('utf-8', errors='replace')
                    except Exception:
                        err_text = str(getattr(resp, 'text', '') or '')
                    raise RuntimeError(f'Responses API error {resp.status_code}: {err_text[:4000]}')
                sse_parser = globals().get('_responses_iter_sse_frames')
                if not callable(sse_parser):
                    raise RuntimeError('Responses SSE parser unavailable')
                for chunk in sse_parser(resp.iter_lines(), _handle_payload, _plain_text_frame):
                    yield chunk
            if completed_payload is not None:
                for complete_call in _file_delivery_calls_from_response_payload(completed_payload):
                    key = str(complete_call.get('id') or complete_call.get('_index') or '').strip()
                    entry = None
                    for saved in calls.values():
                        if str(saved.get('id') or '') == key:
                            entry = saved
                            break
                    if entry is None:
                        yield _file_delivery_chat_completion_compat_chunk(tool_call={'index': int(complete_call.get('_index') or 0), 'id': str(complete_call.get('id') or ''), 'type': 'function', 'function': dict(complete_call.get('function') or {})})
            yield _file_delivery_chat_completion_compat_chunk(finish_reason='stop')
        finally:
            if own_client is not None:
                try:
                    own_client.close()
                except Exception:
                    pass

    return _iter()


def _file_delivery_chat_completion_create_current_endpoint(client_obj=None, call_kwargs: dict | None = None, *, stream: bool = False):
    # File-delivery helper calls should not open hidden non-stream LLM requests.
    # Even callers that omit stream are routed through the streaming path.
    if _file_delivery_endpoint_mode_from_client(client_obj) == 'responses':
        return _file_delivery_responses_stream_create_chat_compat(client_obj, call_kwargs or {})
    return client_obj.chat.completions.create(stream=True, **(call_kwargs or {}))

def _openai_stream_error_retryable(err: Exception) -> bool:
    if isinstance(err, (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError, httpx.NetworkError)):
        return True
    name = type(err).__name__.lower()
    txt = str(err or '').lower()
    markers = (
        'apiconnectionerror', 'api connection error', 'connection reset', 'connection aborted',
        'server disconnected', 'remote protocol', 'readtimeout', 'connecttimeout', 'pooltimeout',
        'temporarily unavailable', 'bad gateway', 'gateway timeout', 'upstream', 'eof',
    )
    if any(token in name for token in ('timeout', 'connection', 'protocol', 'network')):
        return True
    return any(token in txt for token in markers)


def _openai_stream_retry_delay(attempt: int) -> float:
    base = _app_cfg_float('GPT_STREAM_RETRY_BACKOFF', 0.75, min_value=0.05, max_value=10.0)
    cap = _app_cfg_float('GPT_STREAM_RETRY_MAX_BACKOFF', 3.0, min_value=0.1, max_value=30.0)
    return min(cap, base * (2 ** max(0, int(attempt) - 1)) + 0.15 * random.random())


def _openai_stream_create_with_retries(stream_client, *, phase: str, call_kwargs: dict):
    if str(phase or '').strip() == 'file_edit':
        # File edits can be expensive. Do not silently reopen several model calls
        # after a failure unless the operator explicitly opts in.
        attempts = 1 + _app_cfg_int('FILE_EDIT_STREAM_OPEN_RETRIES', 0, min_value=0, max_value=3)
    else:
        attempts = 1 + _app_cfg_int('GPT_STREAM_MAX_RETRIES', 2, min_value=0, max_value=5)
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            return _file_delivery_chat_completion_create_current_endpoint(stream_client, call_kwargs, stream=True)
        except Exception as e:
            last_err = e
            if attempt >= attempts or not _openai_stream_error_retryable(e):
                raise
            try:
                app_logger.warning('[openai_stream] open_retry phase=%s endpoint_mode=%s model=%s attempt=%s/%s err=%s:%s', phase, _file_delivery_endpoint_mode_from_client(stream_client), call_kwargs.get('model'), attempt, attempts, type(e).__name__, e)
            except Exception:
                pass
            time.sleep(_openai_stream_retry_delay(attempt))
    if last_err is not None:
        raise last_err
    raise RuntimeError('stream_open_failed')
