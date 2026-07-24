# Responses SSE frame iteration and streaming adapter.

import json


_RESPONSES_PLAIN_TEXT_DELTA_EVENTS = {'response.output_text.delta', 'output_text.delta', 'text.delta', ''}


class ResponsesSSEEventBuffer:
    """按 SSE 事件边界组装 Responses JSON，并在重连时丢弃残帧。"""

    def __init__(self, *, logger=None, lane: str = 'responses'):
        self.logger = logger
        self.lane = str(lane or 'responses')
        self.reset()

    def reset(self) -> None:
        self.event_name = ''
        self.data_lines: list[str] = []

    def set_event(self, event_name: str = '') -> None:
        self.event_name = str(event_name or '').strip()

    def add_data(self, value: str = '') -> None:
        self.data_lines.append(str(value or ''))

    def pop_json(self) -> tuple[str, dict | None]:
        event_name = self.event_name.strip()
        raw_data = '\n'.join(self.data_lines).strip()
        self.reset()
        if not raw_data or raw_data == '[DONE]':
            return event_name, None
        try:
            payload = json.loads(raw_data)
        except Exception as exc:
            # Responses SSE 的 data 必须是 JSON，残缺协议帧绝不能进入助手正文。
            try:
                if self.logger is not None:
                    self.logger.warning(
                        '[RESPONSES_SSE_MALFORMED_DROPPED] lane=%s event=%s chars=%s err=%s',
                        self.lane,
                        event_name or '-',
                        len(raw_data),
                        type(exc).__name__,
                    )
            except Exception:
                pass
            return event_name, None
        return event_name, payload if isinstance(payload, dict) else None


def _responses_iter_sse_frames(iter_lines, handle_payload, plain_text_factory=None):
    current_event = ''
    data_lines: list[str] = []

    def flush_event():
        nonlocal current_event, data_lines
        if not data_lines:
            current_event = ''
            return []
        raw_data = '\n'.join(data_lines).strip()
        event_name = current_event.strip()
        current_event = ''
        data_lines = []
        if not raw_data or raw_data == '[DONE]':
            return []
        try:
            payload = json.loads(raw_data)
        except Exception:
            if raw_data and event_name in _RESPONSES_PLAIN_TEXT_DELTA_EVENTS and callable(plain_text_factory):
                return list(plain_text_factory(raw_data, event_name) or [])
            return []
        return list(handle_payload(payload, event_name) or []) if callable(handle_payload) else []

    for raw_line in iter_lines:
        line = raw_line.decode('utf-8', errors='replace') if isinstance(raw_line, (bytes, bytearray)) else str(raw_line or '')
        if line == '':
            for frame in flush_event():
                yield frame
            continue
        if line.startswith(':'):
            continue
        if line.startswith('event:'):
            current_event = line[len('event:'):].strip()
            continue
        if line.startswith('data:'):
            data_lines.append(line[len('data:'):].lstrip())
            continue
        stripped = line.strip()
        if stripped:
            data_lines.append(stripped)
            for frame in flush_event():
                yield frame
    for frame in flush_event():
        yield frame


def _responses_sse_event_keys_for_log(payload) -> list[str]:
    if not isinstance(payload, dict):
        return []
    keys = []
    for key in payload.keys():
        name = str(key or '').strip()
        if name:
            keys.append(name[:80])
        if len(keys) >= 20:
            break
    return keys


def _responses_log_sse_event_probe(event_type: str = '', payload=None, *, seen: set | None = None) -> None:
    """Log event types/keys plus model metadata only; never log streamed content."""
    try:
        name = str(event_type or '').strip() or str((payload or {}).get('type') or (payload or {}).get('event') or '').strip() or '(blank)'
        key = name.lower()
        if seen is not None:
            if key in seen:
                return
            if len(seen) >= 80:
                return
            seen.add(key)
        root_model = ''
        response_model = ''
        extracted_model = ''
        if isinstance(payload, dict):
            root_model = _normalize_runtime_model_name(payload.get('model'))
            response_obj = payload.get('response') if isinstance(payload.get('response'), dict) else None
            if isinstance(response_obj, dict):
                response_model = _normalize_runtime_model_name(response_obj.get('model'))
            extracted_model = _extract_runtime_model_from_obj(payload)
        app_logger.info(
            '[RESPONSES_SSE_EVENT] type=%s keys=%s response_model=%s root_model=%s extracted_model=%s reasoning_event=%s',
            name[:160],
            _responses_sse_event_keys_for_log(payload),
            response_model or '-',
            root_model or '-',
            extracted_model or '-',
            bool(_responses_sse_event_is_reasoning(payload, name)),
        )
    except Exception:
        pass


def _responses_stream_text_chunks(client_override=None, *, model: str = '', messages: list | None = None, timeout: float | None = None, extra_body: dict | None = None):
    resolver = globals().get('_resolve_openai_client_identity')
    if callable(resolver):
        api_key, base_url = resolver(client_override)
    else:
        api_key = str(getattr(client_override, 'api_key', '') or globals().get('GPT_API_KEY') or '').strip()
        base_url = str(getattr(client_override, 'base_url', '') or globals().get('GPT_BASE_URL') or '').strip()
    endpoint = _responses_endpoint_from_base_url(base_url)
    if not endpoint:
        raise RuntimeError('Responses API endpoint missing')
    body = {
        'model': str(model or '').strip(),
        'instructions': _responses_instructions_from_chat_messages(messages or []),
        'input': _responses_input_from_chat_messages(messages or []),
        'stream': True,
    }
    merged_extra_body = _responses_extra_body_with_reasoning_summary(
        extra_body if isinstance(extra_body, dict) else {},
        model=model,
    )
    if isinstance(merged_extra_body, dict):
        for k, v in dict(merged_extra_body or {}).items():
            key = str(k or '').strip()
            if not key or key in {'model', 'input', 'messages', 'stream'}:
                continue
            body[key] = v
    try:
        body = _apply_prompt_cache_to_request_payload(
            body,
            endpoint_mode='responses',
            model=str(model or '').strip(),
            base_url=base_url,
            phase='responses_stream',
            placement='body',
        )
    except Exception:
        pass
    client = globals().get('HTTPX_GPT')
    own_client = None
    if client is None:
        own_client = httpx.Client(verify=globals().get('tls_verify', True), timeout=timeout or 900.0, follow_redirects=True)
        client = own_client
    headers = {'Accept': 'text/event-stream', 'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    deltas_seen = False
    completed_payload = None
    reasoning_accum = ''
    _sse_probe_seen_event_types: set[str] = set()
    try:
        app_logger.info(
            '[RESPONSES_REQUEST_BODY] endpoint=%s stream=1 keys=%s reasoning_keys=%s thinking_keys=%s',
            endpoint,
            sorted(str(k) for k in body.keys()),
            sorted(str(k) for k in ((body.get('reasoning') or {}).keys())) if isinstance(body.get('reasoning'), dict) else [],
            sorted(str(k) for k in ((body.get('thinking') or {}).keys())) if isinstance(body.get('thinking'), dict) else [],
        )
    except Exception:
        pass

    def _plain_text_frame(raw_data, _event_name=''):
        nonlocal deltas_seen
        deltas_seen = True
        return [_compat_chat_text_chunk(raw_data, finish_reason='', model=model)]

    def _handle_sse_payload(payload, event_name=''):
        nonlocal deltas_seen, completed_payload, reasoning_accum
        is_err, err_text = _responses_sse_payload_is_error(payload, event_name)
        if is_err:
            raise RuntimeError(f'Responses API stream error: {err_text[:4000]}')
        event_type = str(event_name or (payload.get('type') if isinstance(payload, dict) else '') or '').strip()
        _responses_log_sse_event_probe(event_type, payload, seen=_sse_probe_seen_event_types)
        out_chunks = []
        usage = _responses_usage_from_payload(payload)
        if usage:
            out_chunks.append(_compat_chat_usage_chunk(usage, model=_extract_runtime_model_from_obj(payload) or model))
        if event_type in {'response.completed', 'response.done', 'response.output_text.done'}:
            completed_payload = payload
            reasoning_snapshot = _responses_extract_reasoning_snapshot_from_sse_payload(payload, event_name)
            reasoning_piece = _responses_reasoning_suffix_delta(reasoning_snapshot, reasoning_accum, snapshot_mode=True)
            if reasoning_piece:
                reasoning_accum += reasoning_piece
                out_chunks.append(_compat_chat_reasoning_chunk(reasoning_piece, source='responses_reasoning_snapshot', model=_extract_runtime_model_from_obj(payload)))
            return out_chunks
        reasoning_delta = _responses_extract_reasoning_delta_from_sse_payload(payload, event_name)
        if reasoning_delta:
            reasoning_piece = _responses_reasoning_suffix_delta(reasoning_delta, reasoning_accum)
            if reasoning_piece:
                reasoning_accum += reasoning_piece
                out_chunks.append(_compat_chat_reasoning_chunk(reasoning_piece, source='responses_reasoning', model=_extract_runtime_model_from_obj(payload)))
            return out_chunks
        reasoning_snapshot = _responses_extract_reasoning_snapshot_from_sse_payload(payload, event_name)
        reasoning_piece = _responses_reasoning_suffix_delta(reasoning_snapshot, reasoning_accum, snapshot_mode=True)
        if reasoning_piece:
            reasoning_accum += reasoning_piece
            out_chunks.append(_compat_chat_reasoning_chunk(reasoning_piece, source='responses_reasoning_snapshot', model=_extract_runtime_model_from_obj(payload)))
            return out_chunks
        delta = _responses_extract_delta_from_sse_payload(payload, event_name)
        if delta:
            deltas_seen = True
            out_chunks.append(_compat_chat_text_chunk(delta, finish_reason='', model=_extract_runtime_model_from_obj(payload)))
            return out_chunks
        return out_chunks

    try:
        for request_attempt in range(2):
            with client.stream('POST', endpoint, headers=headers, json=body, timeout=timeout or None) as resp:
                if int(getattr(resp, 'status_code', 0) or 0) >= 400:
                    try:
                        err_text = resp.read().decode('utf-8', errors='replace')
                    except Exception:
                        err_text = str(getattr(resp, 'text', '') or '')
                    if (
                        request_attempt == 0
                        and 'prompt_cache_options' in body
                        and _prompt_cache_rejects_modern_protocol(err_text)
                    ):
                        body = _prompt_cache_without_modern_protocol(body, placement='body')
                        try:
                            app_logger.warning('[RESPONSES_PROMPT_CACHE_PROTOCOL_RETRY] model=%s status=%s', model, resp.status_code)
                        except Exception:
                            pass
                        continue
                    raise RuntimeError(f'Responses API error {resp.status_code}: {err_text[:4000]}')
                for chunk in _responses_iter_sse_frames(resp.iter_lines(), _handle_sse_payload, _plain_text_frame):
                    yield chunk
                break
        if (not deltas_seen) and completed_payload is not None:
            final_text = _extract_responses_text_payload(completed_payload.get('response') if isinstance(completed_payload, dict) and isinstance(completed_payload.get('response'), dict) else completed_payload)
            if final_text:
                yield _compat_chat_text_chunk(final_text, finish_reason='', model=_extract_runtime_model_from_obj(completed_payload))
        yield _compat_chat_text_chunk('', finish_reason='stop', model=_extract_runtime_model_from_obj(completed_payload))
    finally:
        if own_client is not None:
            try:
                own_client.close()
            except Exception:
                pass
