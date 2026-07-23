# Split from app3_parts/chat/chat_responses_adapter_part.py.
# Purpose: runtime model normalization helpers.
# Loaded by chat_responses_adapter_part.py via _exec_split_file(...), sharing app3.py globals.

def _normalize_chat_api_endpoint_mode(value: str | None = None) -> str:
    canonical = globals().get('_normalize_payload_api_endpoint_mode')
    if callable(canonical):
        try:
            return canonical(value)
        except Exception:
            pass
    raw = str(value or '').strip().lower()
    if raw in {'responses', 'response', '/responses'}:
        return 'responses'
    return 'chat_completions'


def _normalize_runtime_model_name(value) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    lowered = raw.lower()
    if lowered in {'none', 'null', 'unknown', 'undefined', 'false'}:
        return ''
    return raw[:160]


def _extract_runtime_model_from_obj(obj) -> str:
    if obj is None:
        return ''
    try:
        value = getattr(obj, 'model', None)
        normalized = _normalize_runtime_model_name(value)
        if normalized:
            return normalized
    except Exception:
        pass
    if isinstance(obj, dict):
        for key in ('model', 'model_id', 'modelId'):
            normalized = _normalize_runtime_model_name(obj.get(key))
            if normalized:
                return normalized
        for key in ('response', 'output', 'data'):
            child = obj.get(key)
            if isinstance(child, dict):
                normalized = _extract_runtime_model_from_obj(child)
                if normalized:
                    return normalized
    return ''


def _main_chat_runtime_model_context(runtime_model: str = '') -> dict | None:
    model_name = _normalize_runtime_model_name(runtime_model)
    if not model_name:
        return None
    return {'role': 'system', '_kind': 'runtime_model', 'content': '当前模型：' + model_name}


def _inject_main_chat_runtime_model_context(messages: list | None = None, runtime_model: str = '') -> list:
    base = [dict(m) if isinstance(m, dict) else m for m in (messages or [])]
    ctx = _main_chat_runtime_model_context(runtime_model)
    if not ctx:
        return base
    out = [ctx, *base]
    try:
        deduper = globals().get('_orch_dedupe_model_messages')
        if callable(deduper):
            return deduper(out)
    except Exception:
        pass
    return out


def _runtime_model_meta(runtime_model: str = '') -> dict:
    model_name = _normalize_runtime_model_name(runtime_model)
    return {'runtime_model': model_name} if model_name else {}
