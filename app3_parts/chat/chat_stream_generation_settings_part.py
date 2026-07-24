# normalize user generation settings and map them to Chat/Responses request kwargs.


_GENERATION_AUTO_SENTINELS = {'auto', 'default', 'none', 'null', '自动', '默认', '�Զ�', 'Ĭ��'}


def _generation_setting_value(settings: dict, *keys):
    if not isinstance(settings, dict):
        return None
    for key in keys:
        if key in settings and settings.get(key) not in (None, ''):
            return settings.get(key)
    return None


def _generation_optional_int(value, *, max_value: int = 200000):
    raw = str(value or '').strip()
    if not raw or raw.lower() in _GENERATION_AUTO_SENTINELS:
        return None
    try:
        n = int(float(raw))
    except Exception:
        return None
    if n <= 0:
        return None
    return max(1, min(int(max_value or 200000), n))


def _generation_optional_float(value, *, min_value: float = 0.0, max_value: float = 1.0):
    raw = str(value or '').strip()
    if not raw or raw.lower() in _GENERATION_AUTO_SENTINELS:
        return None
    try:
        n = float(raw)
    except Exception:
        return None
    if n != n:
        return None
    return max(float(min_value), min(float(max_value), n))


def _generation_response_format(value) -> str:
    raw = str(value or '').strip().lower().replace('-', '_')
    if raw in {'json', 'json_object', 'object'}:
        return 'json_object'
    return 'auto'


def _generation_prompt_cache_key(value) -> str:
    raw = str(value or '').strip()
    if not raw or raw.lower() in _GENERATION_AUTO_SENTINELS:
        return ''
    return raw[:512]


def _generation_prompt_cache_retention(value) -> str:
    raw = str(value or '').strip().lower()
    if not raw or raw in _GENERATION_AUTO_SENTINELS:
        return ''
    if raw in {'24h', '1h'}:
        return raw
    return ''


def _generation_tri_state(value) -> str:
    raw = str(value or '').strip().lower()
    if raw in {'1', 'true', 'yes', 'on', 'enable', 'enabled', '开启', '打开', '寮€鍚?', '鎵撳紑'}:
        return 'enabled'
    if raw in {'0', 'false', 'no', 'off', 'disable', 'disabled', '关闭', '鍏抽棴'}:
        return 'disabled'
    return 'auto'


def _generation_settings_from_client(client_obj=None) -> dict:
    try:
        settings = getattr(client_obj, '_webai_api_settings', {}) if client_obj is not None else {}
        return dict(settings or {}) if isinstance(settings, dict) else {}
    except Exception:
        return {}


def _apply_user_generation_settings(call_kwargs: dict | None, *, endpoint_mode: str, client_obj=None) -> dict:
    out = dict(call_kwargs or {})
    settings = _generation_settings_from_client(client_obj)
    if not settings:
        return out

    max_tokens = _generation_optional_int(
        _generation_setting_value(settings, 'generation_max_tokens', 'max_output_tokens', 'max_completion_tokens', 'max_tokens'),
        max_value=200000,
    )
    temperature = _generation_optional_float(_generation_setting_value(settings, 'generation_temperature', 'temperature'), min_value=0.0, max_value=2.0)
    top_p = _generation_optional_float(_generation_setting_value(settings, 'generation_top_p', 'top_p'), min_value=0.0, max_value=1.0)
    response_format = _generation_response_format(_generation_setting_value(settings, 'generation_response_format', 'response_format'))
    include_usage = _generation_tri_state(_generation_setting_value(settings, 'generation_include_usage', 'stream_include_usage', 'include_usage'))
    prompt_cache_key = _generation_prompt_cache_key(_generation_setting_value(settings, 'generation_prompt_cache_key', 'prompt_cache_key'))
    prompt_cache_retention = _generation_prompt_cache_retention(_generation_setting_value(settings, 'generation_prompt_cache_retention', 'prompt_cache_retention'))

    is_responses = str(endpoint_mode or '').strip().lower() == 'responses'
    if is_responses:
        extra_body = dict(out.get('extra_body') or {}) if isinstance(out.get('extra_body'), dict) else {}
        if max_tokens is not None:
            extra_body['max_output_tokens'] = max_tokens
        if temperature is not None:
            extra_body['temperature'] = temperature
        if top_p is not None:
            extra_body['top_p'] = top_p
        if response_format == 'json_object':
            text_obj = dict(extra_body.get('text') or {}) if isinstance(extra_body.get('text'), dict) else {}
            text_obj['format'] = {'type': 'json_object'}
            extra_body['text'] = text_obj
        if prompt_cache_key:
            extra_body['prompt_cache_key'] = prompt_cache_key
        if prompt_cache_retention:
            extra_body['prompt_cache_retention'] = prompt_cache_retention
        if extra_body:
            out['extra_body'] = extra_body
        return out

    if max_tokens is not None:
        out['max_completion_tokens'] = max_tokens
    if temperature is not None:
        out['temperature'] = temperature
    if top_p is not None:
        out['top_p'] = top_p
    if response_format == 'json_object':
        out['response_format'] = {'type': 'json_object'}
    if prompt_cache_key or prompt_cache_retention:
        extra_body = dict(out.get('extra_body') or {}) if isinstance(out.get('extra_body'), dict) else {}
        if prompt_cache_key:
            extra_body['prompt_cache_key'] = prompt_cache_key
        if prompt_cache_retention:
            extra_body['prompt_cache_retention'] = prompt_cache_retention
        out['extra_body'] = extra_body
    if include_usage == 'enabled':
        stream_options = dict(out.get('stream_options') or {}) if isinstance(out.get('stream_options'), dict) else {}
        stream_options['include_usage'] = True
        out['stream_options'] = stream_options
    return out
