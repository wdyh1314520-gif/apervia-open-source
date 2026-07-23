# Split from app3_parts/chat/chat_responses_adapter_part.py.
# Purpose: Responses non-stream text adapter.
# Loaded by chat_responses_adapter_part.py via _exec_split_file(...), sharing app3.py globals.

def _extract_responses_text_payload(payload) -> str:
    if payload is None:
        return ''
    if not isinstance(payload, dict):
        try:
            output_text = getattr(payload, 'output_text', '')
            if output_text:
                return str(output_text or '')
        except Exception:
            pass
        try:
            payload = payload.model_dump()
        except Exception:
            try:
                payload = dict(payload)
            except Exception:
                return str(payload or '')
    direct = str((payload or {}).get('output_text') or '').strip()
    if direct:
        return direct
    parts = []
    for item in (payload or {}).get('output') or []:
        if not isinstance(item, dict):
            continue
        for block in item.get('content') or []:
            if isinstance(block, dict):
                text = block.get('text') or block.get('output_text') or block.get('content')
                if text:
                    parts.append(str(text))
    if parts:
        return ''.join(parts)
    try:
        choices = (payload or {}).get('choices') or []
        if choices:
            msg = choices[0].get('message') or {}
            txt = msg.get('content') or choices[0].get('text') or ''
            if txt:
                return str(txt)
    except Exception:
        pass
    return ''


def _responses_create_non_stream_text(client_override=None, *, model: str = '', messages: list | None = None, timeout: float | None = None) -> str:
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
    }
    client = globals().get('HTTPX_GPT')
    own_client = None
    if client is None:
        own_client = httpx.Client(verify=globals().get('tls_verify', True), timeout=timeout or 900.0, follow_redirects=True)
        client = own_client
    try:
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        resp = client.post(endpoint, headers=headers, json=body, timeout=timeout or None)
        if int(getattr(resp, 'status_code', 0) or 0) >= 400:
            raise RuntimeError(f'Responses API error {resp.status_code}: {str(getattr(resp, "text", "") or "")[:4000]}')
        try:
            payload = resp.json()
        except Exception:
            raise RuntimeError(f'Responses API returned non-JSON: {str(getattr(resp, "text", "") or "")[:1200]}')
        text = _extract_responses_text_payload(payload)
        if not str(text or '').strip():
            raise RuntimeError('Responses API returned empty output')
        return str(text or '')
    finally:
        if own_client is not None:
            try:
                own_client.close()
            except Exception:
                pass
