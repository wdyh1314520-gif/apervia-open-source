# Responses-to-chat compatibility chunk helpers.

class _CompatChoiceObj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _compat_chat_text_chunk(text: str = '', *, finish_reason: str = 'stop', reasoning_text: str = '', reasoning_source: str = '', model: str = ''):
    delta_kwargs = {'content': str(text or '')}
    message_kwargs = {'content': str(text or '')}
    reasoning_piece = str(reasoning_text or '')
    if reasoning_piece:
        delta_kwargs['reasoning_content'] = reasoning_piece
        delta_kwargs['reasoning'] = reasoning_piece
        delta_kwargs['reasoning_text'] = reasoning_piece
        delta_kwargs['thinking'] = reasoning_piece
        if reasoning_source:
            delta_kwargs['reasoning_source'] = str(reasoning_source or '')
        message_kwargs.update({
            'reasoning_content': reasoning_piece,
            'reasoning': reasoning_piece,
            'reasoning_text': reasoning_piece,
            'thinking': reasoning_piece,
        })
    delta = _CompatChoiceObj(**delta_kwargs)
    choice = _CompatChoiceObj(delta=delta, message=_CompatChoiceObj(**message_kwargs), finish_reason=finish_reason)
    obj = _CompatChoiceObj(choices=[choice])
    runtime_model = _normalize_runtime_model_name(model)
    if runtime_model:
        obj.model = runtime_model
    return obj


def _compat_chat_reasoning_chunk(text: str = '', *, source: str = 'responses_reasoning', model: str = ''):
    return _compat_chat_text_chunk('', finish_reason='', reasoning_text=str(text or ''), reasoning_source=source, model=model)


def _compat_chat_usage_chunk(usage=None, *, model: str = ''):
    """Return an OpenAI-chat-compatible empty chunk carrying Responses usage.

    The main chat streaming layer already knows how to read chunk.usage; keeping
    this as an empty text chunk lets /v1/responses reuse the same usage display
    path without changing text/reasoning rendering.
    """
    obj = _compat_chat_text_chunk('', finish_reason='', model=model)
    try:
        if isinstance(usage, dict) and usage:
            obj.usage = dict(usage)
    except Exception:
        pass
    return obj


def _responses_usage_from_payload(payload):
    if not isinstance(payload, dict):
        return None
    usage = payload.get('usage') if isinstance(payload.get('usage'), dict) else None
    if usage:
        return usage
    response = payload.get('response') if isinstance(payload.get('response'), dict) else None
    if isinstance(response, dict) and isinstance(response.get('usage'), dict):
        return response.get('usage')
    return None


def _responses_endpoint_from_base_url(base_url: str = '') -> str:
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
            # Preserve exactly the user's base path. Some providers expose endpoints
            # directly under host:port without /v1.
            if not path.strip('/'):
                raw = urlunparse((parsed.scheme, parsed.netloc, '', '', '', ''))
    except Exception:
        pass
    return raw.rstrip('/') + '/responses' if raw else ''
