# Split from app3_parts/account/user_personalization_runtime_part.py.
# Purpose: aux model resolution, thinking-type probing, API profile clients, request overrides, and search upstream policy.
# Loaded by user_personalization_runtime_part.py via _exec_split_file(...), sharing the original global namespace.

def _resolve_aux_model(current_model: str | None, override_name: str, default_model: str) -> str:
    cur = str(current_model or '').strip()
    override_names = [str(override_name or '').strip()]
    if str(override_name or '').strip() == 'WEB_SEARCH_PLANNER_MODEL':
        override_names.append('QUERY_GENERATION_MODEL')

    override = ''
    for name in override_names:
        if not name:
            continue
        value = str(_get_request_override(name, '') or '').strip()
        if value:
            override = value
            break

    if override.lower() in ('', 'follow_current', 'current', 'same_as_chat', 'same'):
        return cur or default_model
    return override


def _normalize_thinking_type(value, default: str = 'auto') -> str:
    raw = str(value or '').strip().lower()
    if raw in {'auto', 'enabled', 'disabled'}:
        return raw
    return str(default or 'auto').strip().lower() or 'auto'


_THINKING_CAPABILITY_CACHE_LOCK = threading.Lock()
_THINKING_CAPABILITY_CACHE: dict[str, dict] = {}
_THINKING_CAPABILITY_CACHE_TTL_S = 7 * 24 * 3600
_THINKING_PROBE_MAX_ATTEMPTS = 2
_THINKING_PROBE_FAILURE_WINDOW_S = 30 * 60
_THINKING_PROBE_COOLDOWN_S = 30 * 60
_THINKING_PROBE_STATE_LOCK = threading.Lock()
_THINKING_PROBE_STATE: dict[str, dict] = {}


def _thinking_capability_cache_key(model: str | None, api_base: str = '') -> str:
    name = str(model or '').strip().lower()
    base = str(api_base or '').strip().lower().rstrip('/')
    return f'{base}\n{name}'


def _thinking_capability_cache_get(model: str | None, api_base: str = '') -> dict | None:
    key = _thinking_capability_cache_key(model, api_base=api_base)
    if not key.strip():
        return None
    now = time.time()
    with _THINKING_CAPABILITY_CACHE_LOCK:
        item = dict(_THINKING_CAPABILITY_CACHE.get(key) or {})
        expires_at = float(item.get('expires_at') or 0.0)
        if expires_at > 0 and expires_at < now:
            _THINKING_CAPABILITY_CACHE.pop(key, None)
            return None
        return item or None


def _thinking_capability_cache_set(model: str | None, api_base: str = '', supported: bool = False, *, source: str = 'probe') -> dict:
    key = _thinking_capability_cache_key(model, api_base=api_base)
    now = time.time()
    item = {
        'supported': bool(supported),
        'source': str(source or 'probe').strip() or 'probe',
        'checked_at': now,
        'expires_at': now + _THINKING_CAPABILITY_CACHE_TTL_S,
    }
    if key.strip():
        with _THINKING_CAPABILITY_CACHE_LOCK:
            _THINKING_CAPABILITY_CACHE[key] = dict(item)
    return item


def _thinking_probe_state_get(model: str | None, api_base: str = '') -> dict | None:
    key = _thinking_capability_cache_key(model, api_base=api_base)
    if not key.strip():
        return None
    now = time.time()
    with _THINKING_PROBE_STATE_LOCK:
        item = dict(_THINKING_PROBE_STATE.get(key) or {})
        if not item:
            return None
        last_failed_at = float(item.get('last_failed_at') or 0.0)
        cooldown_until = float(item.get('cooldown_until') or 0.0)
        if (cooldown_until > 0 and cooldown_until <= now) or (last_failed_at > 0 and (now - last_failed_at) > _THINKING_PROBE_FAILURE_WINDOW_S):
            _THINKING_PROBE_STATE.pop(key, None)
            return None
        return item


def _thinking_probe_state_clear(model: str | None, api_base: str = '') -> None:
    key = _thinking_capability_cache_key(model, api_base=api_base)
    if not key.strip():
        return
    with _THINKING_PROBE_STATE_LOCK:
        _THINKING_PROBE_STATE.pop(key, None)


def _thinking_probe_state_note_failure(model: str | None, api_base: str = '', message: str = '') -> dict:
    key = _thinking_capability_cache_key(model, api_base=api_base)
    if not key.strip():
        return {'attempts': 1, 'last_failed_at': time.time(), 'cooldown_until': 0.0, 'last_message': str(message or '')[:240]}
    now = time.time()
    with _THINKING_PROBE_STATE_LOCK:
        prev = dict(_THINKING_PROBE_STATE.get(key) or {})
        last_failed_at = float(prev.get('last_failed_at') or 0.0)
        cooldown_until = float(prev.get('cooldown_until') or 0.0)
        if (cooldown_until > 0 and cooldown_until <= now) or (last_failed_at > 0 and (now - last_failed_at) > _THINKING_PROBE_FAILURE_WINDOW_S):
            prev = {}
        attempts = int(prev.get('attempts') or 0) + 1
        item = {
            'attempts': attempts,
            'first_failed_at': float(prev.get('first_failed_at') or now),
            'last_failed_at': now,
            'cooldown_until': 0.0,
            'last_message': str(message or prev.get('last_message') or '').strip()[:240],
        }
        if attempts >= _THINKING_PROBE_MAX_ATTEMPTS:
            item['cooldown_until'] = now + _THINKING_PROBE_COOLDOWN_S
        _THINKING_PROBE_STATE[key] = dict(item)
        return item


def _thinking_probe_build_limited_result(state: dict | None = None, message: str = '') -> dict:
    item = dict(state or {})
    now = time.time()
    cooldown_until = float(item.get('cooldown_until') or 0.0)
    retry_after_s = max(0, int(math.ceil(cooldown_until - now))) if cooldown_until > now else 0
    final_message = str(message or item.get('last_message') or '').strip()
    if not final_message:
        final_message = f'同一商家同一模型探测失败已达 {_THINKING_PROBE_MAX_ATTEMPTS} 次，冷却 {max(1, int(_THINKING_PROBE_COOLDOWN_S // 60))} 分钟后再试'
    return {
        'ok': False,
        'supported': False,
        'message': final_message,
        'cached': True,
        'definitive': False,
        'source': 'probe_limit',
        'checked_at': float(item.get('last_failed_at') or now),
        'probe_attempts': int(item.get('attempts') or 0),
        'probe_limit_reached': True,
        'cooldown_until': cooldown_until,
        'retry_after_s': retry_after_s,
    }


def _thinking_probe_error_looks_unsupported(message: str | None = None) -> bool:
    text = str(message or '').strip().lower()
    if not text:
        return False
    hints = (
        'thinking',
        'unsupported',
        'not support',
        'unknown field',
        'unknown parameter',
        'extra inputs are not permitted',
        'extra_forbidden',
        'invalid field',
        'invalid parameter',
        'unrecognized request argument',
    )
    if 'thinking' in text and any(word in text for word in ('unsupported', 'not support', 'invalid', 'unknown', 'extra')):
        return True
    return any(hint in text for hint in hints) and 'thinking' in text


def _probe_model_thinking_type_support(model: str | None, *, api_key: str = '', api_base: str = '') -> dict:
    model_name = str(model or '').strip()
    base = str(api_base or '').strip()
    key = str(api_key or '').strip()
    if not model_name:
        return {'ok': False, 'supported': False, 'message': 'missing_model', 'cached': False, 'definitive': False}
    if not key:
        return {'ok': False, 'supported': False, 'message': 'missing_api_key', 'cached': False, 'definitive': False}

    cached = _thinking_capability_cache_get(model_name, api_base=base)
    if isinstance(cached, dict) and ('supported' in cached):
        return {
            'ok': True,
            'supported': bool(cached.get('supported')),
            'message': '',
            'cached': True,
            'definitive': True,
            'source': str(cached.get('source') or 'cache'),
            'checked_at': float(cached.get('checked_at') or 0.0),
        }

    probe_state = _thinking_probe_state_get(model_name, api_base=base)
    if isinstance(probe_state, dict):
        attempts = int(probe_state.get('attempts') or 0)
        cooldown_until = float(probe_state.get('cooldown_until') or 0.0)
        if attempts >= _THINKING_PROBE_MAX_ATTEMPTS and cooldown_until > time.time():
            return _thinking_probe_build_limited_result(probe_state)

    try:
        client = _client_for_payload({'api_key': key, 'api_base': base, 'api_settings': {'api_key': key, 'api_base': base}})
        with_options = getattr(client, 'with_options', None)
        if callable(with_options):
            try:
                client = with_options(max_retries=0)
            except Exception:
                pass
        req = {
            'model': model_name,
            'messages': [{'role': 'user', 'content': 'ping'}],
            'max_tokens': 1,
            'temperature': 0,
            'extra_body': {'thinking': {'type': 'enabled'}},
        }
        client.chat.completions.create(**req)
        _thinking_probe_state_clear(model_name, api_base=base)
        item = _thinking_capability_cache_set(model_name, api_base=base, supported=True, source='probe')
        return {
            'ok': True,
            'supported': True,
            'message': '',
            'cached': False,
            'definitive': True,
            'source': str(item.get('source') or 'probe'),
            'checked_at': float(item.get('checked_at') or 0.0),
        }
    except Exception as e:
        msg = str(e or '').strip()
        if _thinking_probe_error_looks_unsupported(msg):
            _thinking_probe_state_clear(model_name, api_base=base)
            item = _thinking_capability_cache_set(model_name, api_base=base, supported=False, source='probe')
            return {
                'ok': True,
                'supported': False,
                'message': msg,
                'cached': False,
                'definitive': True,
                'source': str(item.get('source') or 'probe'),
                'checked_at': float(item.get('checked_at') or 0.0),
            }
        failure_state = _thinking_probe_state_note_failure(model_name, api_base=base, message=msg)
        attempts = int(failure_state.get('attempts') or 0)
        cooldown_until = float(failure_state.get('cooldown_until') or 0.0)
        if attempts >= _THINKING_PROBE_MAX_ATTEMPTS and cooldown_until > time.time():
            return _thinking_probe_build_limited_result(failure_state, message=msg)
        return {
            'ok': False,
            'supported': False,
            'message': msg,
            'cached': False,
            'definitive': False,
            'source': 'probe_error',
            'checked_at': float(failure_state.get('last_failed_at') or time.time()),
            'probe_attempts': attempts,
            'probe_limit_reached': False,
            'cooldown_until': cooldown_until,
            'retry_after_s': 0,
        }


def _completion_client_api_base(client_override=None) -> str:
    try:
        base = str(getattr(client_override, 'base_url', '') or '').strip()
    except Exception:
        base = ''
    if base:
        return base
    try:
        base = str(getattr(client_gpt, 'base_url', '') or '').strip()
    except Exception:
        base = ''
    return base or str(GPT_BASE_URL or '').strip()


def _model_supports_thinking_type(model: str | None, api_base: str = '') -> bool:
    name = str(model or '').strip().lower()
    if not name:
        return False
    cached = _thinking_capability_cache_get(name, api_base=api_base)
    if isinstance(cached, dict) and ('supported' in cached):
        return bool(cached.get('supported'))
    vendor = str((_detect_api_vendor('', api_base) or {}).get('vendor') or '').strip().lower()
    if re.match(r'^glm(?:[-._]|$)', name, flags=re.I):
        return True
    if re.search(r'(^|[\/:_-])glm[-_ ]?(?:4(?:\.[567])?|5)(?:[^a-z0-9]|$)', name, flags=re.I):
        return True
    if vendor == 'zhipu' and 'glm' in name:
        return True
    return False


def _thinking_override_names_for_role(role: str) -> tuple[str, ...]:
    role_key = str(role or 'chat').strip().lower() or 'chat'
    if role_key == 'tool_prefetch':
        return ('TOOL_PREFETCH_THINKING_TYPE',)
    if role_key == 'query_generation':
        return ('WEB_SEARCH_PLANNER_THINKING_TYPE', 'QUERY_GENERATION_THINKING_TYPE')
    return ('CHAT_THINKING_TYPE',)


def _thinking_type_for_role(role: str) -> str:
    for name in _thinking_override_names_for_role(role):
        raw = str(_get_request_override(name, '') or '').strip()
        if raw:
            return _normalize_thinking_type(raw)
    return 'auto'


def _apply_completion_thinking_kwargs(req: dict | None, *, role: str, model: str | None, client_override=None) -> dict:
    out = dict(req or {})
    thinking_type = _thinking_type_for_role(role)
    if thinking_type == 'auto':
        return out
    api_base = _completion_client_api_base(client_override=client_override)
    if not _model_supports_thinking_type(model, api_base=api_base):
        return out
    extra_body = dict(out.get('extra_body') or {}) if isinstance(out.get('extra_body'), dict) else {}
    thinking = dict(extra_body.get('thinking') or {}) if isinstance(extra_body.get('thinking'), dict) else {}
    thinking['type'] = thinking_type
    extra_body['thinking'] = thinking
    out['extra_body'] = extra_body
    return out


def _chat_role_prefers_fact_bridge(model: str | None = None, client_override=None) -> bool:
    thinking_type = _thinking_type_for_role('chat')
    if thinking_type == 'disabled':
        return False
    api_base = _completion_client_api_base(client_override=client_override)
    return _model_supports_thinking_type(model, api_base=api_base)


def _normalize_payload_api_endpoint_mode(value: str | None = None) -> str:
    raw = str(value or '').strip().lower()
    if raw in {'responses', 'response', '/responses'}:
        return 'responses'
    return 'chat_completions'


def _api_profile_payload_for_mode(payload: dict | None = None, mode: str = 'chat_completions') -> dict:
    payload = payload or {}
    target = _normalize_payload_api_endpoint_mode(mode)
    by_mode = payload.get('api_profiles_by_mode') if isinstance(payload.get('api_profiles_by_mode'), dict) else {}
    candidates = []
    if isinstance(by_mode, dict):
        candidates.append(by_mode.get(target))
        if target == 'chat_completions':
            candidates.append(by_mode.get('chat'))
        elif target == 'responses':
            candidates.append(by_mode.get('response'))
    if target == 'chat_completions':
        candidates.append(payload.get('chat_api_settings'))
        candidates.append(payload.get('file_chat_api_settings'))
        candidates.append(payload.get('file_delivery_api_settings'))
        candidates.append(payload.get('file_api_settings'))
    elif target == 'responses':
        candidates.append(payload.get('responses_api_settings'))
    for item in candidates:
        if isinstance(item, dict):
            api_key = str(item.get('api_key') or '').strip()
            api_base = str(item.get('api_base') or item.get('base_url') or '').strip()
            profile_name = str(item.get('profile_name') or item.get('name') or '').strip()
            endpoint_mode = _normalize_payload_api_endpoint_mode(item.get('api_endpoint_mode') or item.get('endpoint_mode') or target)
            if api_key or api_base or profile_name:
                out = {
                    'api_key': api_key,
                    'api_base': api_base,
                    'profile_name': profile_name,
                    'api_endpoint_mode': endpoint_mode,
                }
                profile_param_keys = (
                    'generation_max_tokens', 'generation_temperature', 'generation_top_p',
                    'generation_response_format', 'generation_include_usage',
                    'generation_prompt_cache_key', 'generation_prompt_cache_retention',
                    'max_output_tokens', 'max_completion_tokens', 'temperature', 'top_p',
                    'response_format', 'stream_include_usage', 'include_usage',
                    'prompt_cache_key', 'prompt_cache_retention',
                )
                if target == 'responses':
                    profile_param_keys = (
                        'responses_reasoning_effort',
                        'responses_reasoning_summary',
                        'responses_reasoning_context',
                    ) + profile_param_keys
                for param_key in profile_param_keys:
                    if param_key in item and item.get(param_key) not in (None, ''):
                        out[param_key] = item.get(param_key)
                return out
    return {}



try:
    _WEBAI_ACTIVE_API_PAYLOAD_LOCAL
except NameError:
    _WEBAI_ACTIVE_API_PAYLOAD_LOCAL = threading.local()


def _webai_set_active_api_payload(payload: dict | None = None) -> None:
    try:
        setattr(_WEBAI_ACTIVE_API_PAYLOAD_LOCAL, 'payload', dict(payload or {}) if isinstance(payload, dict) else {})
    except Exception:
        pass


def _webai_get_active_api_payload() -> dict:
    try:
        payload = getattr(_WEBAI_ACTIVE_API_PAYLOAD_LOCAL, 'payload', {})
        return dict(payload or {}) if isinstance(payload, dict) else {}
    except Exception:
        return {}

def _client_for_payload(payload: dict | None):
    payload = payload or {}
    _webai_set_active_api_payload(payload)
    api_settings = payload.get("api_settings") if isinstance(payload.get("api_settings"), dict) else {}
    explicit = ("api_key" in payload) or ("api_base" in payload) or isinstance(payload.get("api_settings"), dict)
    api_key = str(payload.get("api_key") or "").strip()
    api_base = str(payload.get("api_base") or "").strip()
    if isinstance(api_settings, dict):
        if not api_key:
            api_key = str(api_settings.get("api_key") or "").strip()
        if not api_base:
            api_base = str(api_settings.get("api_base") or "").strip()
    endpoint_mode = _normalize_payload_api_endpoint_mode(
        payload.get('api_endpoint_mode')
        or payload.get('endpoint_mode')
        or api_settings.get('api_endpoint_mode')
        or api_settings.get('endpoint_mode')
    )
    if explicit:
        client = OpenAI(
            api_key=api_key,
            base_url=api_base or "https://api.vveai.com/v1",
            http_client=HTTPX_GPT,
            max_retries=_openai_max_retries(),
        )
    else:
        client = client_gpt
    try:
        setattr(client, '_webai_api_endpoint_mode', endpoint_mode)
        setattr(client, '_webai_api_settings', dict(api_settings or {}))
        setattr(client, '_webai_chat_api_settings', _api_profile_payload_for_mode(payload, 'chat_completions'))
        setattr(client, '_webai_responses_api_settings', _api_profile_payload_for_mode(payload, 'responses'))
    except Exception:
        pass
    return client


def _client_for_file_generation(client_override=None):
    """Return a file-delivery client bound to the user's currently selected endpoint.

    No cross-endpoint bridge is performed here:
    - If the current request is Chat Completions, file delivery uses that Chat profile.
    - If the current request is Responses, file delivery uses that same Responses profile.
    Missing current key/base still fails visibly instead of falling back to defaults.
    """
    def _client_base_url_text(client_obj) -> str:
        try:
            return str(getattr(client_obj, 'base_url', '') or '').strip()
        except Exception:
            return ''

    def _client_api_key_text(client_obj) -> str:
        try:
            return str(getattr(client_obj, 'api_key', '') or '').strip()
        except Exception:
            return ''

    endpoint_mode = 'chat_completions'
    try:
        endpoint_mode = _normalize_payload_api_endpoint_mode(getattr(client_override, '_webai_api_endpoint_mode', '') or 'chat_completions')
    except Exception:
        endpoint_mode = 'chat_completions'

    api_key = _client_api_key_text(client_override)
    base_url = _client_base_url_text(client_override)

    try:
        current_profile = getattr(client_override, '_webai_api_settings', None)
        if isinstance(current_profile, dict):
            api_key = str(current_profile.get('api_key') or api_key or '').strip()
            base_url = str(current_profile.get('api_base') or current_profile.get('base_url') or base_url or '').strip()
    except Exception:
        pass

    if not api_key:
        try:
            app_logger.error('[FILE_API_ISOLATION] blocked reason=missing_current_api_key endpoint_mode=%s no_bridge=1 no_default_fallback=1', endpoint_mode)
        except Exception:
            pass
        raise RuntimeError('file_delivery_current_profile_missing:api_key')

    if not base_url:
        try:
            app_logger.error('[FILE_API_ISOLATION] blocked reason=missing_current_api_base endpoint_mode=%s no_bridge=1 no_default_fallback=1', endpoint_mode)
        except Exception:
            pass
        raise RuntimeError('file_delivery_current_profile_missing:api_base')

    try:
        app_logger.info('[FILE_API_ISOLATION] use_current_profile endpoint_mode=%s base=%s key_len=%s no_bridge=1', endpoint_mode, base_url, len(api_key))
    except Exception:
        pass
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=HTTPX_GPT_FILE,
        max_retries=_openai_max_retries(),
    )
    try:
        setattr(client, '_webai_api_endpoint_mode', endpoint_mode)
        setattr(client, '_webai_api_settings', dict(getattr(client_override, '_webai_api_settings', {}) or {}))
        setattr(client, '_webai_file_api_source', 'current_endpoint_only')
    except Exception:
        pass
    return client

def _extract_request_overrides(payload: dict | None) -> dict:
    payload = payload or {}
    src = payload.get("web_settings") if isinstance(payload.get("web_settings"), dict) else payload
    out = {}
    mapping = {
        "SEARXNG_URL": ["searxng_url", "SEARXNG_URL"],
        "SEARXNG_API_PATH": ["searxng_api_path", "SEARXNG_API_PATH"],
        "SEARCH_PROVIDER": ["search_provider", "SEARCH_PROVIDER"],
        "SEARCH_FALLBACK_PROVIDER": ["search_fallback_provider", "SEARCH_FALLBACK_PROVIDER"],
        "WHOOGLE_URL": ["whoogle_url", "WHOOGLE_URL"],
        "EXTERNAL_SEARCH_URL": ["external_search_url", "EXTERNAL_SEARCH_URL"],
        "EXTERNAL_SEARCH_API_KEY": ["external_search_api_key", "EXTERNAL_SEARCH_API_KEY"],
        "EXTERNAL_IMAGE_SEARCH_URL": ["external_image_search_url", "EXTERNAL_IMAGE_SEARCH_URL"],
        "EXTERNAL_IMAGE_SEARCH_API_KEY": ["external_image_search_api_key", "EXTERNAL_IMAGE_SEARCH_API_KEY"],
        "UAPIPRO_BASE_URL": ["uapipro_base_url", "UAPIPRO_BASE_URL"],
        "UAPIPRO_API_KEY": ["uapipro_api_key", "UAPIPRO_API_KEY"],
        "IMAGE_SEARCH_PROVIDER": ["image_search_provider", "IMAGE_SEARCH_PROVIDER"],
        "IMAGE_SEARCH_FALLBACK_PROVIDER": ["image_search_fallback_provider", "IMAGE_SEARCH_FALLBACK_PROVIDER"],
        "IMAGE_SEARCH_MAX_QUERIES": ["image_search_max_queries", "IMAGE_SEARCH_MAX_QUERIES"],
        "WEB_SEARCH_MIN_EFFECTIVE_RESULTS": ["web_search_min_effective_results", "WEB_SEARCH_MIN_EFFECTIVE_RESULTS"],
        "WEB_SEARCH_TARGET_RESULTS": ["web_search_target_results", "WEB_SEARCH_TARGET_RESULTS"],
        "IMAGE_SEARCH_MIN_EFFECTIVE_RESULTS": ["image_search_min_effective_results", "IMAGE_SEARCH_MIN_EFFECTIVE_RESULTS"],
        "IMAGE_SEARCH_TARGET_RESULTS": ["image_search_target_results", "IMAGE_SEARCH_TARGET_RESULTS"],
        "CONTENT_PROVIDER": ["content_provider", "CONTENT_PROVIDER"],
        "CONTENT_FALLBACK_PROVIDER": ["content_fallback_provider", "CONTENT_FALLBACK_PROVIDER"],
        "SERPER_API_KEY": ["serper_api_key", "SERPER_API_KEY"],
        "TAVILY_API_KEY": ["tavily_api_key", "TAVILY_API_KEY"],
        "TAVILY_EXTRACT_DEPTH": ["tavily_extract_depth", "TAVILY_EXTRACT_DEPTH"],
        "AUTO_WEB_K_RESULTS": ["web_k", "AUTO_WEB_K_RESULTS", "auto_web_k_results"],
        "AUTO_WEB_FAST_MAX_PAGES": ["web_fast_max_pages", "AUTO_WEB_FAST_MAX_PAGES", "auto_web_fast_max_pages"],
        "AUTO_WEB_MAX_PAGES": ["web_max_pages", "AUTO_WEB_MAX_PAGES", "auto_web_max_pages"],
        "AUTO_WEB_FETCH_WORKERS": ["fetch_workers", "AUTO_WEB_FETCH_WORKERS", "auto_web_fetch_workers"],
        "AUTO_WEB_PAGE_TIMEOUT": ["page_timeout", "AUTO_WEB_PAGE_TIMEOUT", "auto_web_page_timeout"],
        "AUTO_WEB_PAGE_MAX_CHARS": ["page_max_chars", "AUTO_WEB_PAGE_MAX_CHARS", "auto_web_page_max_chars"],
        "AUTO_WEB_PAGE_SNIPPET_CHARS": ["page_snippet_chars", "AUTO_WEB_PAGE_SNIPPET_CHARS", "auto_web_page_snippet_chars"],
        "PLAYWRIGHT_ENABLE": ["playwright_enable", "PLAYWRIGHT_ENABLE"],
        "PLAYWRIGHT_TIMEOUT": ["playwright_timeout", "PLAYWRIGHT_TIMEOUT"],
        "WEB_FETCH_AUTO_RENDER": ["web_fetch_auto_render", "WEB_FETCH_AUTO_RENDER", "auto_render"],
        "WEB_FETCH_RENDER_MODE": ["web_fetch_render_mode", "WEB_FETCH_RENDER_MODE", "render_mode"],
        "WEB_FETCH_CAPTURE_JSON_APIS": ["web_fetch_capture_json_apis", "WEB_FETCH_CAPTURE_JSON_APIS"],
        "MAX_WEB_SEARCH_CALLS": ["max_web_search_calls", "MAX_WEB_SEARCH_CALLS"],
        "CHAT_THINKING_TYPE": ["chat_thinking_type", "CHAT_THINKING_TYPE"],
        "RESPONSES_REASONING_EFFORT": ["responses_reasoning_effort", "RESPONSES_REASONING_EFFORT"],
        "RESPONSES_REASONING_SUMMARY": ["responses_reasoning_summary", "RESPONSES_REASONING_SUMMARY"],
        "RESPONSES_REASONING_CONTEXT": ["responses_reasoning_context", "RESPONSES_REASONING_CONTEXT"],
    }
    for env_name, keys in mapping.items():
        for k in keys:
            if isinstance(src, dict) and k in src and src.get(k) not in (None, ""):
                out[env_name] = src.get(k)
                break
    try:
        if out:
            app_logger.warning(
                "[DEBUG_OVERRIDES_EXTRACT] keys=%s fallback=%r serper_key_len=%s src=%s",
                sorted(out.keys()),
                str(out.get("SEARCH_FALLBACK_PROVIDER") or ""),
                len(str(out.get("SERPER_API_KEY") or "").strip()),
                "web_settings" if isinstance(payload.get("web_settings"), dict) else "payload",
            )
        else:
            app_logger.warning("[DEBUG_OVERRIDES_EXTRACT] keys=[] src=%s", "web_settings" if isinstance(payload.get("web_settings"), dict) else "payload")
    except Exception:
        pass
    return out


def _request_web_settings_source(payload: dict | None) -> dict:
    payload = payload or {}
    src = payload.get('web_settings') if isinstance(payload.get('web_settings'), dict) else payload
    return src if isinstance(src, dict) else {}


def _is_protected_search_target_url(raw_url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(str(raw_url or '').strip())
    except Exception:
        return False, ''
    scheme = str(parsed.scheme or '').strip().lower()
    if scheme not in {'http', 'https'}:
        return False, ''
    host = str(parsed.hostname or '').strip().lower()
    if not host:
        return False, ''
    reasons: list[str] = []
    if host == 'localhost' or host.endswith('.localhost'):
        reasons.append('localhost')
    if host.endswith('.local') or host.endswith('.lan'):
        reasons.append('lan_hostname')
    try:
        ip_obj = ipaddress.ip_address(host)
        if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_unspecified or ip_obj.is_multicast:
            reasons.append('private_ip')
    except Exception:
        pass
    req_host = _request_host_name()
    if req_host and host == str(req_host).strip().lower():
        reasons.append('same_server_host')
    return (len(reasons) > 0), ','.join(reasons)


def _current_request_allows_private_search_targets(access_ctx: dict | None = None) -> bool:
    ctx = access_ctx if isinstance(access_ctx, dict) else {}
    try:
        if bool(ctx.get('allow_private_search_targets')):
            return True
    except Exception:
        pass
    try:
        if bool(ctx.get('is_local_admin_request')):
            return True
    except Exception:
        pass
    if _is_local_admin_request():
        return True
    try:
        email = _normalize_login_email(str(ctx.get('email') or '').strip())
    except Exception:
        email = ''
    if not email:
        try:
            email = _normalize_login_email((_current_login_account() or {}).get('email') or '')
        except Exception:
            email = ''
    if not email:
        return False
    user = _auth_get_user(email) or {}
    return _auth_user_allows_private_search_upstreams(user)


def _request_uses_search_provider(src: dict, provider_name: str) -> bool:
    target = str(provider_name or '').strip().lower()
    if not target:
        return False
    keys = (
        'SEARCH_PROVIDER', 'search_provider',
        'SEARCH_FALLBACK_PROVIDER', 'search_fallback_provider',
        'IMAGE_SEARCH_PROVIDER', 'image_search_provider',
        'IMAGE_SEARCH_FALLBACK_PROVIDER', 'image_search_fallback_provider',
    )
    for key in keys:
        value = str(src.get(key) or '').strip().lower()
        if value == target:
            return True
    return False


def _enforce_request_override_policy(payload: dict | None, overrides: dict | None, access_ctx: dict | None = None) -> dict:
    overrides = dict(overrides or {})
    if not overrides:
        return overrides
    src = _request_web_settings_source(payload)
    ctx = access_ctx if isinstance(access_ctx, dict) else {}
    policy_checks = (
        ('SEARXNG_URL', 'searxng'),
        ('WHOOGLE_URL', 'whoogle'),
        ('EXTERNAL_SEARCH_URL', 'external'),
        ('EXTERNAL_IMAGE_SEARCH_URL', 'external'),
    )
    for key, provider in policy_checks:
        if not _request_uses_search_provider(src, provider):
            continue
        raw_url = str(overrides.get(key) or '').strip()
        if not raw_url:
            continue
        blocked, reason = _is_protected_search_target_url(raw_url)
        if not blocked:
            continue
        if _current_request_allows_private_search_targets(ctx):
            continue
        try:
            email = _normalize_login_email(str(ctx.get('email') or '').strip())
        except Exception:
            email = ''
        if not email:
            try:
                email = _normalize_login_email((_current_login_account() or {}).get('email') or '')
            except Exception:
                email = ''
        app_logger.warning('[web_settings_policy] blocked key=%s reason=%s email=%s url=%s', key, reason or '-', email or '-', raw_url)
        raise ValueError('当前账号未获准使用主机本地/私网搜索地址（如 127.0.0.1、localhost、同主机其他端口、10.x、192.168.x）。要用主机端口需管理员在统一后台的账号设置中放行；要用你自己电脑的搜索服务，请填写主机可访问的局域网 IP 或公网域名。')
    return overrides
