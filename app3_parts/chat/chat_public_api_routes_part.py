# Split from app3_parts/chat/chat_weather_routes_part.py.
# Purpose: public API settings, model/fetch routes, and synchronous chat route.
# Loaded by chat_weather_routes_part.py via _exec_split_file(...), sharing app3.py globals.

@app.get("/api3/whoami")
def whoami_gpt():
    return jsonify({
        "app": APP_NAME,
        "port": PORT,
        "base_url": GPT_BASE_URL,
        "tls_verify": tls_verify,
    })


def _chat_mode_prepare_skip_decision(*, disable_tools: bool = False, skip_prepare_messages: bool = False) -> dict:
    try:
        direct_agent_skip_prepare = bool((not disable_tools) and _agent_stream_should_skip_initial_prepare(True))
    except Exception:
        direct_agent_skip_prepare = False
    return {
        'direct_agent_skip_prepare': bool(direct_agent_skip_prepare),
        'effective_skip_prepare_messages': bool(skip_prepare_messages or direct_agent_skip_prepare),
        'endpoint_mode': 'chat',
    }


def _responses_mode_prepare_skip_decision(*, skip_prepare_messages: bool = False) -> dict:
    return {
        'direct_agent_skip_prepare': True,
        'effective_skip_prepare_messages': True,
        'endpoint_mode': 'responses',
        'explicit_skip_prepare_messages': bool(skip_prepare_messages),
    }


def _prepare_skip_decision_for_endpoint(api_endpoint_mode: str = '', *, disable_tools: bool = False, skip_prepare_messages: bool = False) -> dict:
    mode = str(api_endpoint_mode or '').strip().lower()
    if mode == 'responses':
        return _responses_mode_prepare_skip_decision(skip_prepare_messages=skip_prepare_messages)
    return _chat_mode_prepare_skip_decision(disable_tools=disable_tools, skip_prepare_messages=skip_prepare_messages)



def _remote_browser_data_safe_path(path: str = '') -> str:
    raw = str(path or '').strip()
    if not raw:
        return ''
    try:
        expanded = os.path.abspath(os.path.expanduser(raw))
    except Exception:
        return ''
    try:
        base = os.path.abspath(BASE_DIR)
    except Exception:
        base = ''
    try:
        tmp = os.path.abspath(tempfile.gettempdir())
    except Exception:
        tmp = ''
    lowered = expanded.lower().replace('\\', '/')
    if expanded in {'/', base, tmp, os.path.expanduser('~')}:
        return ''
    marker_ok = any(x in lowered for x in ('webai', 'app3', 'remote_browser', 'browser_data', 'playwright', 'pw_user_data'))
    under_base = bool(base and (expanded == base or expanded.startswith(base + os.sep)))
    under_tmp = bool(tmp and expanded.startswith(tmp + os.sep))
    if not marker_ok or not (under_base or under_tmp):
        return ''
    return expanded


def _remote_browser_clear_dir_contents(path: str = '') -> dict:
    safe = _remote_browser_data_safe_path(path)
    if not safe or not os.path.isdir(safe):
        return {'path': str(path or ''), 'ok': False, 'skipped': True, 'deleted_entries': 0}
    deleted = 0
    errors: list[str] = []
    try:
        for name in os.listdir(safe):
            fp = os.path.join(safe, name)
            try:
                if os.path.isdir(fp) and not os.path.islink(fp):
                    shutil.rmtree(fp, ignore_errors=False)
                else:
                    os.remove(fp)
                deleted += 1
            except Exception as e:
                errors.append(f'{name}: {type(e).__name__}')
        return {'path': safe, 'ok': not errors, 'skipped': False, 'deleted_entries': deleted, 'errors': errors[:8]}
    except Exception as e:
        return {'path': safe, 'ok': False, 'skipped': False, 'deleted_entries': deleted, 'errors': [f'{type(e).__name__}: {e}']}


def _remote_browser_data_candidate_dirs() -> list[str]:
    rows: list[str] = []
    for key in (
        'REMOTE_BROWSER_DATA_DIR',
        'WEBAI_REMOTE_BROWSER_DATA_DIR',
        'WEB_FETCH_PLAYWRIGHT_USER_DATA_DIR',
        'PLAYWRIGHT_USER_DATA_DIR',
        'BROWSER_DATA_DIR',
        'BROWSER_CACHE_DIR',
    ):
        try:
            value = str(app_getenv(key, '') or '').strip()
        except Exception:
            value = ''
        if value:
            rows.append(value)
    for name in (
        'remote_browser_data',
        'webai_remote_browser_data',
        'browser_data',
        'playwright_user_data',
        'playwright_profiles',
        'pw_user_data',
    ):
        try:
            rows.append(_app_data_path(name))
        except Exception:
            pass
    out: list[str] = []
    seen: set[str] = set()
    for item in rows:
        safe = _remote_browser_data_safe_path(item)
        key = safe.lower() if safe else str(item or '').strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(safe or item)
    return out


def _clear_remote_browser_runtime_state() -> dict:
    result = {
        'memory_caches': [],
        'directories': [],
        'host_fetch': {},
    }
    try:
        cache = globals().get('_WEB_CACHE')
        if isinstance(cache, dict):
            n = len(cache)
            cache.clear()
            result['memory_caches'].append({'name': '_WEB_CACHE', 'cleared': n})
    except Exception:
        pass
    try:
        fetcher = globals().get('_fetch_pages_concurrent')
        url_cache = getattr(fetcher, '_url_cache', None) if fetcher is not None else None
        if isinstance(url_cache, dict):
            n = len(url_cache)
            url_cache.clear()
            result['memory_caches'].append({'name': '_fetch_pages_concurrent._url_cache', 'cleared': n})
    except Exception:
        pass
    try:
        cache = globals().get('_REMOTE_IMAGE_FAIL_CACHE')
        lock = globals().get('_REMOTE_IMAGE_FAIL_LOCK')
        if isinstance(cache, dict):
            if lock is not None:
                with lock:
                    n = len(cache)
                    cache.clear()
            else:
                n = len(cache)
                cache.clear()
            result['memory_caches'].append({'name': '_REMOTE_IMAGE_FAIL_CACHE', 'cleared': n})
    except Exception:
        pass
    try:
        state = globals().get('_HOST_FETCH_STATE')
        lock = globals().get('_HOST_FETCH_GUARD')
        if isinstance(state, dict):
            if lock is not None:
                with lock:
                    n = len(state)
                    state.clear()
            else:
                n = len(state)
                state.clear()
            result['memory_caches'].append({'name': '_HOST_FETCH_STATE', 'cleared': n})
    except Exception:
        pass
    try:
        db_path_fn = globals().get('_host_fetch_db_file_path')
        db_path = str(db_path_fn() if callable(db_path_fn) else globals().get('_HOST_FETCH_DB_FILE_DEFAULT') or '').strip()
        if db_path and os.path.exists(db_path):
            sql = __import__('sqlite3')
            conn = sql.connect(db_path, timeout=30.0)
            try:
                deleted_rows = 0
                for table in ('host_state', 'fetch_stats'):
                    try:
                        cur = conn.execute(f'DELETE FROM {table}')
                        deleted_rows += max(0, int(cur.rowcount or 0))
                    except Exception:
                        pass
                conn.commit()
                result['host_fetch']['db_rows_deleted'] = deleted_rows
            finally:
                conn.close()
    except Exception as e:
        result['host_fetch']['db_error'] = f'{type(e).__name__}: {e}'
    try:
        legacy_path_fn = globals().get('_host_fetch_legacy_state_file_path')
        legacy_path = str(legacy_path_fn() if callable(legacy_path_fn) else globals().get('_HOST_FETCH_STATE_FILE_DEFAULT') or '').strip()
        safe_file = _remote_browser_data_safe_path(legacy_path)
        if safe_file and os.path.isfile(safe_file):
            with open(safe_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False)
            result['host_fetch']['legacy_state_cleared'] = True
    except Exception as e:
        result['host_fetch']['legacy_state_error'] = f'{type(e).__name__}: {e}'
    for path in _remote_browser_data_candidate_dirs():
        row = _remote_browser_clear_dir_contents(path)
        if not row.get('skipped') or os.path.exists(str(path or '')):
            result['directories'].append(row)
    return result


@app.post('/api3/remote-browser-data/clear')
def remote_browser_data_clear_route():
    try:
        email = ''
        require_login = globals().get('_require_logged_in_email')
        if callable(require_login):
            email, error_resp = require_login()
            if error_resp is not None:
                try:
                    if _is_local_admin_request():
                        error_resp = None
                    else:
                        return error_resp
                except Exception:
                    return error_resp
        try:
            if email:
                _auth_presence_mark(email, path=request.path)
        except Exception:
            pass
        cleared = _clear_remote_browser_runtime_state()
        payload = {'ok': True, 'cleared': cleared}
        no_store = globals().get('_json_no_store')
        if callable(no_store):
            return no_store(payload)
        return jsonify(payload)
    except Exception as e:
        try:
            app_logger.exception('[remote_browser_data] clear_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'remote_browser_data_clear_failed', 'message': str(e)}), 500


@app.post("/api3/web_settings/validate")
def api3_validate_web_settings():
    payload = request.get_json(force=True, silent=True) or {}
    src = _request_web_settings_source(payload)
    allowed_targets = {'searxng', 'whoogle', 'uapipro', 'external'}

    def _normalize_validate_targets(raw_targets) -> list[str]:
        out = []
        if not isinstance(raw_targets, list):
            return out
        for item in raw_targets:
            name = str(item or '').strip().lower()
            if not name or name == 'none' or name not in allowed_targets:
                continue
            if name not in out:
                out.append(name)
        return out

    def _text_search_targets_from_settings(settings: dict | None = None) -> list[str]:
        row = settings if isinstance(settings, dict) else {}
        out = []
        for key in ('SEARCH_PROVIDER', 'search_provider', 'SEARCH_FALLBACK_PROVIDER', 'search_fallback_provider'):
            name = str(row.get(key) or '').strip().lower()
            if not name or name == 'none' or name not in allowed_targets:
                continue
            if name not in out:
                out.append(name)
        return out

    targets = _normalize_validate_targets(payload.get('validate_targets') or payload.get('providers'))
    if not targets:
        targets = _text_search_targets_from_settings(src)
    if not targets:
        return jsonify({'ok': True, 'results': [], 'message': ''})

    # Validation is for the text web-search source selected in the web-search panel.
    # Do not let image-search providers or stale cached provider values trigger probes here.
    validation_src = dict(src or {}) if isinstance(src, dict) else {}
    validation_src['IMAGE_SEARCH_PROVIDER'] = 'none'
    validation_src['IMAGE_SEARCH_FALLBACK_PROVIDER'] = 'none'
    validation_src['image_search_provider'] = 'none'
    validation_src['image_search_fallback_provider'] = 'none'
    validation_payload = dict(payload or {})
    validation_payload['web_settings'] = validation_src
    validation_payload['validate_targets'] = targets

    request_overrides = _extract_request_overrides(validation_payload)
    try:
        request_overrides = _enforce_request_override_policy(validation_payload, request_overrides)
    except Exception as e:
        msg = str(e)
        return jsonify({
            'ok': False,
            'results': [
                {'provider': name, 'enabled': True, 'ok': False, 'message': msg}
                for name in targets
            ],
            'message': msg,
        })

    _set_request_overrides(request_overrides)
    try:
        results = [_validate_search_provider_connection(name) for name in targets]
        ok = all(bool(item.get('ok')) for item in results if item.get('enabled', True))
        message = '；'.join(str(item.get('message') or '').strip() for item in results if not item.get('ok'))[:500]
        return jsonify({'ok': ok, 'results': results, 'message': message, 'validated_targets': targets})
    finally:
        _set_request_overrides({})


def _normalize_api_endpoint_mode(value: str | None = None) -> str:
    canonical = globals().get('_normalize_payload_api_endpoint_mode') or globals().get('_normalize_chat_api_endpoint_mode')
    if callable(canonical):
        try:
            return canonical(value)
        except Exception:
            pass
    raw = str(value or '').strip().lower()
    if raw in {'responses', 'response', '/responses'}:
        return 'responses'
    return 'chat_completions'


def _api_endpoint_mode_from_payload(payload: dict | None = None) -> str:
    payload = payload or {}
    api_settings = payload.get('api_settings') if isinstance(payload.get('api_settings'), dict) else {}
    return _normalize_api_endpoint_mode(
        payload.get('api_endpoint_mode')
        or payload.get('endpoint_mode')
        or api_settings.get('api_endpoint_mode')
        or api_settings.get('endpoint_mode')
        or api_settings.get('api_mode')
    )


def _chat_request_messages_from_payload(payload: dict | None = None, *, user_text: str = '', history=None) -> list:
    """Build one canonical OpenAI-style message list from a chat payload."""
    payload = payload or {}
    msgs_in = payload.get("messages")
    if isinstance(msgs_in, list) and msgs_in:
        return list(msgs_in)
    hist = history if isinstance(history, list) else (payload.get("history") if isinstance(payload.get("history"), list) else [])
    messages: list[dict] = []
    for h in hist or []:
        if isinstance(h, dict) and h.get("role") in ("system", "user", "assistant", "tool"):
            messages.append({"role": h.get("role"), "content": h.get("content", "")})
    text = str(user_text or '').strip()
    if text:
        messages.append({"role": "user", "content": text})
    return messages


def _chat_request_context_from_payload(payload: dict | None = None, *, source: str = '') -> dict:
    """Normalize request fields shared by /chat, /chat_stream and chat_async."""
    payload = payload or {}
    user_text = _latest_user_text_from_payload(payload)
    history = payload.get("history") if isinstance(payload.get("history"), list) else []
    messages = _chat_request_messages_from_payload(payload, user_text=user_text, history=history)
    return {
        'payload': payload,
        'messages': messages,
        'history': history,
        'user_text': user_text,
        'model': str(payload.get("model") or app_getenv("GPT_MODEL", "gpt-5.4-nano") or '').strip(),
        'label': str(payload.get("label") or ''),
        'show_steps': bool(payload.get("show_steps", True)),
        'api_endpoint_mode': _api_endpoint_mode_from_payload(payload),
        'temporary_chat': bool(payload.get("temporary_chat") or payload.get("temporaryChat")),
        'source': str(source or ''),
    }


def _extract_api_settings_from_payload(payload: dict | None = None) -> dict:
    payload = payload or {}
    api_settings = payload.get('api_settings') if isinstance(payload.get('api_settings'), dict) else {}
    api_key = str(payload.get('api_key') or api_settings.get('api_key') or '').strip()
    api_base = str(payload.get('api_base') or api_settings.get('api_base') or '').strip()
    profile_name = str(payload.get('profile_name') or api_settings.get('profile_name') or '').strip()
    api_endpoint_mode = _api_endpoint_mode_from_payload(payload)
    return {
        'api_key': api_key,
        'api_base': api_base,
        'profile_name': profile_name,
        'api_endpoint_mode': api_endpoint_mode,
    }


def _detect_api_vendor(api_key: str = '', api_base: str = '') -> dict:
    key = str(api_key or '').strip()
    base = str(api_base or '').strip()
    host = ''
    try:
        host = (urlparse(base).hostname or '').strip().lower()
    except Exception:
        host = ''

    host_rules = [
        ('openrouter', 'OpenRouter', lambda h: h == 'openrouter.ai' or h.endswith('.openrouter.ai')),
        ('openai', 'OpenAI', lambda h: h == 'openai.com' or h.endswith('.openai.com')),
        ('anthropic', 'Anthropic', lambda h: h == 'anthropic.com' or h.endswith('.anthropic.com')),
        ('google', 'Google', lambda h: h.endswith('googleapis.com') or h.endswith('google.com') or h.endswith('google.ai') or 'gemini' in h),
        ('xai', 'xAI', lambda h: h == 'x.ai' or h.endswith('.x.ai') or h == 'xai.com' or h.endswith('.xai.com')),
        ('deepseek', 'DeepSeek', lambda h: h.endswith('deepseek.com')),
        ('moonshot', 'Moonshot', lambda h: h.endswith('moonshot.cn') or h.endswith('kimi.moonshot.cn')),
        ('dashscope', 'DashScope', lambda h: 'dashscope' in h or h.endswith('aliyuncs.com')),
        ('siliconflow', 'SiliconFlow', lambda h: h.endswith('siliconflow.cn')),
        ('zhipu', '智谱', lambda h: h == 'z.ai' or h.endswith('.z.ai') or h.endswith('bigmodel.cn') or 'zhipu' in h),
        ('doubao', '豆包 / 火山方舟', lambda h: h.endswith('volces.com') or h.endswith('volcengine.com') or 'ark' in h),
        ('groq', 'Groq', lambda h: h == 'groq.com' or h.endswith('.groq.com')),
        ('vveai', 'VVEAI', lambda h: h.endswith('vveai.com')),
    ]
    for vendor, label, checker in host_rules:
        try:
            if checker(host):
                return {'vendor': vendor, 'label': label, 'source': 'api_base', 'host': host}
        except Exception:
            continue

    key_rules = [
        ('openrouter', 'OpenRouter', lambda k: k.lower().startswith('sk-or-v1-')),
        ('anthropic', 'Anthropic', lambda k: k.lower().startswith('sk-ant')),
        ('google', 'Google', lambda k: k.startswith('AIza')),
        ('groq', 'Groq', lambda k: k.lower().startswith('gsk_')),
        ('openai_compatible', f'OpenAI 兼容 · {host}' if host else 'OpenAI 兼容', lambda k: k.lower().startswith('sk-')),
    ]
    for vendor, label, checker in key_rules:
        try:
            if checker(key):
                return {'vendor': vendor, 'label': label, 'source': 'api_key', 'host': host}
        except Exception:
            continue

    return {'vendor': 'unknown', 'label': f'未识别 · {host}' if host else '未识别厂商', 'source': 'unknown', 'host': host}


def _normalize_models_endpoint(api_base: str = '') -> str:
    raw = str(api_base or '').strip() or str(GPT_BASE_URL or '').strip()
    if not raw:
        return ''
    parsed = urlparse(raw)
    scheme = str(parsed.scheme or 'https').strip().lower() or 'https'
    netloc = str(parsed.netloc or '').strip()
    path = str(parsed.path or '').strip()
    if not netloc:
        return ''
    trimmed = path.rstrip('/')
    for suffix in ('/chat/completions', '/responses', '/completions', '/embeddings'):
        if trimmed.endswith(suffix):
            trimmed = trimmed[:-len(suffix)]
            break
    if trimmed.endswith('/models'):
        model_path = trimmed
    elif trimmed:
        model_path = trimmed + '/models'
    else:
        model_path = '/models'
    return urlunparse((scheme, netloc, model_path, '', '', ''))


def _model_metadata_positive_int(value) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        return 0
    return max(0, parsed)


def _model_metadata_plain_item(item) -> dict:
    if isinstance(item, dict):
        return dict(item)
    for method_name in ('model_dump', 'dict'):
        method = getattr(item, method_name, None)
        if callable(method):
            try:
                value = method()
                if isinstance(value, dict):
                    return dict(value)
            except Exception:
                pass
    row = {}
    for key in (
        'id', 'name', 'owned_by', 'created', 'context_length', 'context_window',
        'max_context_length', 'max_context_tokens', 'input_token_limit', 'max_input_tokens',
        'max_completion_tokens', 'max_output_tokens', 'output_token_limit',
        'architecture', 'top_provider', 'limits', 'capabilities', 'metadata',
    ):
        try:
            value = getattr(item, key, None)
        except Exception:
            value = None
        if value is not None:
            row[key] = value
    return row


def _normalize_model_catalog(raw_models) -> list[dict]:
    items = []
    if raw_models is None:
        return []
    if isinstance(raw_models, dict):
        items = raw_models.get('data') if isinstance(raw_models.get('data'), list) else []
    elif hasattr(raw_models, 'data'):
        try:
            items = list(getattr(raw_models, 'data') or [])
        except Exception:
            items = []
    elif isinstance(raw_models, list):
        items = raw_models
    out: list[dict] = []
    seen = set()
    for item in items:
        row = _model_metadata_plain_item(item)
        model_id = str(row.get('id') or row.get('name') or '').strip()
        if not model_id:
            continue
        key = model_id.lower()
        if key in seen:
            continue
        seen.add(key)
        architecture = row.get('architecture') if isinstance(row.get('architecture'), dict) else {}
        top_provider = row.get('top_provider') if isinstance(row.get('top_provider'), dict) else {}
        limits = row.get('limits') if isinstance(row.get('limits'), dict) else {}
        capabilities = row.get('capabilities') if isinstance(row.get('capabilities'), dict) else {}
        metadata = row.get('metadata') if isinstance(row.get('metadata'), dict) else {}
        context_window = 0
        for candidate in (
            row.get('context_length'), row.get('context_window'), row.get('max_context_length'),
            row.get('max_context_tokens'), row.get('input_token_limit'), row.get('max_input_tokens'),
            architecture.get('context_length'), architecture.get('context_window'),
            top_provider.get('context_length'), top_provider.get('context_window'),
            limits.get('context_length'), limits.get('context_window'), limits.get('max_context_tokens'),
            capabilities.get('context_length'), capabilities.get('context_window'), capabilities.get('max_context_tokens'),
            metadata.get('context_length'), metadata.get('context_window'), metadata.get('max_context_tokens'),
        ):
            context_window = _model_metadata_positive_int(candidate)
            if context_window:
                break
        max_output = 0
        for candidate in (
            row.get('max_completion_tokens'), row.get('max_output_tokens'), row.get('output_token_limit'),
            top_provider.get('max_completion_tokens'), top_provider.get('max_output_tokens'),
            limits.get('max_completion_tokens'), limits.get('max_output_tokens'),
            capabilities.get('max_completion_tokens'), capabilities.get('max_output_tokens'),
            metadata.get('max_completion_tokens'), metadata.get('max_output_tokens'),
        ):
            max_output = _model_metadata_positive_int(candidate)
            if max_output:
                break
        detail = {'id': model_id}
        if context_window:
            detail['context_window_tokens'] = context_window
        if max_output:
            detail['max_output_tokens'] = max_output
        owned_by = str(row.get('owned_by') or '').strip()
        if owned_by:
            detail['owned_by'] = owned_by[:120]
        created = _model_metadata_positive_int(row.get('created'))
        if created:
            detail['created'] = created
        out.append(detail)
    out.sort(key=lambda x: str(x.get('id') or '').lower())
    return out


def _normalize_model_id_list(raw_models) -> list[str]:
    return [str(item.get('id') or '') for item in _normalize_model_catalog(raw_models) if str(item.get('id') or '').strip()]


def _fetch_models_via_openai_client(payload: dict) -> list[dict]:
    client = _client_for_payload(payload)
    response = client.models.list()
    catalog = _normalize_model_catalog(response)
    if catalog:
        return catalog
    raise RuntimeError('empty_model_list')


def _fetch_models_via_http(api_key: str, api_base: str) -> list[dict]:
    endpoint = _normalize_models_endpoint(api_base)
    if not endpoint:
        raise RuntimeError('missing_api_base')
    headers = {
        'Accept': 'application/json',
        "Authorization": f"Bearer {str(api_key or '').strip()}",
    }
    with httpx.Client(verify=tls_verify, timeout=12.0, follow_redirects=True) as client:
        resp = client.get(endpoint, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    catalog = _normalize_model_catalog(payload)
    if catalog:
        return catalog
    raise RuntimeError('empty_model_list')


@app.post('/api3/models/search')
def api3_models_search():
    payload = request.get_json(force=True, silent=True) or {}
    api_settings = _extract_api_settings_from_payload(payload)
    api_key = str(api_settings.get('api_key') or '').strip()
    api_base = str(api_settings.get('api_base') or '').strip()
    if not api_key:
        return jsonify({'error': 'missing_api_key'}), 400

    query = str(payload.get('q') or payload.get('query') or '').strip().lower()
    try:
        limit = max(1, min(int(payload.get('limit') or 300), 1000))
    except Exception:
        limit = 300

    vendor = _detect_api_vendor(api_key, api_base)
    errors: list[str] = []
    catalog: list[dict] = []
    for fetcher in (
        lambda: _fetch_models_via_http(api_key, api_base),
        lambda: _fetch_models_via_openai_client({'api_key': api_key, 'api_base': api_base, 'api_settings': api_settings}),
    ):
        try:
            catalog = fetcher()
            if catalog:
                break
        except Exception as e:
            errors.append(str(e))
            continue

    if not catalog:
        last_error = errors[-1] if errors else 'empty_model_list'
        return jsonify({
            'ok': False,
            'error': last_error,
            'message': last_error,
            'vendor': vendor,
            'models': [],
            'count': 0,
            'api_base': api_base,
            'can_manual_model_id': True,
            'manual_model_id_supported': True,
        })

    if query:
        catalog = [item for item in catalog if query in str((item or {}).get('id') or '').lower()]
    catalog = catalog[:limit]
    models = [str(item.get('id') or '') for item in catalog if str(item.get('id') or '').strip()]
    return jsonify({
        'ok': True,
        'vendor': vendor,
        'models': models,
        'model_details': catalog,
        'count': len(models),
        'api_base': api_base,
    })


@app.post('/api3/thinking_capability_probe')
def api3_thinking_capability_probe():
    payload = request.get_json(force=True, silent=True) or {}
    api_settings = _extract_api_settings_from_payload(payload)
    api_key = str(api_settings.get('api_key') or '').strip()
    api_base = str(api_settings.get('api_base') or '').strip()
    model = str(payload.get('model') or '').strip()
    if not model:
        return jsonify({'ok': False, 'supported': False, 'message': 'missing_model'}), 400
    if not api_key:
        return jsonify({'ok': False, 'supported': False, 'message': 'missing_api_key'}), 400
    result = _probe_model_thinking_type_support(model, api_key=api_key, api_base=api_base)
    return jsonify({
        **result,
        'model': model,
        'api_base': api_base,
        'vendor': _detect_api_vendor(api_key, api_base),
    })


@app.post("/api3/web_search")
def api3_web_search():
    """联网搜索接口（本地方式）：使用 SearxNG JSON API。
    返回旧格式：{"results":[{"title","url","snippet"}...]}，保证前端兼容。
    """
    if not WEB_SEARCH_ENABLED:
        return jsonify({"error": "Web search disabled (WEB_SEARCH_ENABLED=0)"}), 403

    data = request.get_json(force=True, silent=True) or {}
    q = (data.get("q") or "").strip()
    k = int(data.get("k") or 5)
    k = max(1, min(k, 10))

    if not q:
        return jsonify({"results": []})

    try:
        q2 = _normalize_search_query(q)
        results, err = web_search(q2, k=k)
        return jsonify({"results": results, "error": err})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 400



@app.post("/api3/fetch_url")
def api3_fetch_url():
    data = request.get_json(force=True) or {}
    url = (data.get("url") or "").strip()
    max_chars = int(data.get("max_chars") or 12000)
    try:
        out = fetch_url_content_smart(url, query=str(data.get("query") or ""), max_chars=max(1000, min(max_chars, 40000)))
        # 再做一次上限保护
        out["title"] = (out.get("title") or "")[:300]
        out["text"] = truncate_text(out.get("text") or "", max_chars=min(max_chars, 40000))
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 400


@app.post("/api3/fetch_urls")
def api3_fetch_urls():
    data = request.get_json(force=True) or {}
    urls = data.get("urls") or []
    max_chars = int(data.get("max_chars") or 12000)
    if not isinstance(urls, list) or not urls:
        return jsonify({"error": "urls 必须是非空数组"}), 400
    urls = [str(u).strip() for u in urls if str(u).strip()]
    urls = urls[:5]  # 防止滥用
    outs = []
    for u in urls:
        try:
            outs.append(fetch_url_content_smart(u, query=str(data.get("query") or ""), max_chars=max(1000, min(max_chars, 40000))))
        except Exception as e:
            outs.append({"url": u, "error": f"{type(e).__name__}: {e}"})
    return jsonify({"results": outs})
@app.post("/api3/chat")
def chat_gpt():
    data = request.get_json(force=True)
    try:
        enricher = globals().get('_enrich_location_payload_from_request')
        if callable(enricher):
            data = enricher(data)
    except Exception:
        pass
    payload = data
    req_ctx = _chat_request_context_from_payload(payload, source='chat')
    messages = list(req_ctx.get('messages') or [])
    history = list(req_ctx.get('history') or [])
    user_text = str(req_ctx.get('user_text') or '')
    model = str(req_ctx.get('model') or "gpt-5.4-nano")

    # 天气类问题：能确定就直接返回；不确定且抽到地名则给一句澄清
    user_geo = data.get("user_geo")
    user_time = _normalize_runtime_time_payload(data.get("user_time"))

    # 位置类问题：如果拿到浏览器定位，则直接逆地理编码返回“你大概在哪”
    last_user_text = _latest_user_text_from_messages(messages or [])
    try:
        stats = {}
        t0 = time.perf_counter()
        messages = list(req_ctx.get('messages') or [])
        last_user_text = _latest_user_text_from_messages(messages or []) or user_text

        kb_direct_reply = _kb_try_direct_existing_file_reply(
            query=last_user_text or user_text,
            kb_enabled=payload.get("kb_enabled", True),
            kb_space_id=str(payload.get("kb_space_id") or ''),
            kb_doc_id=str(payload.get("kb_doc_id") or ''),
        )
        if kb_direct_reply:
            return jsonify({"reply": str(kb_direct_reply.get("reply") or ''), "meta": {"model": model, "mode": str(kb_direct_reply.get("mode") or 'kb_direct_existing_file'), "kb_result_count": int(kb_direct_reply.get("result_count") or 0)}})

        temporary_chat = bool(payload.get("temporary_chat") or payload.get("temporaryChat"))
        messages = _merge_payload_file_attachments_into_messages(messages, payload, source='chat_async_start')
        messages = _inject_runtime_time_context(messages, user_time=user_time)
        messages = _prepare_messages(
            messages,
            user_geo=user_geo,
            web_enabled=payload.get("web_enabled"),
            web_k=payload.get("web_k"),
            web_max_pages=payload.get("web_max_pages"),
            kb_enabled=payload.get("kb_enabled", True),
            kb_space_id=str(payload.get("kb_space_id") or ''),
            kb_doc_id=str(payload.get("kb_doc_id") or ''),
        )
        if temporary_chat:
            backend_personalization_meta = {'available': False, 'source': 'temporary_chat_disabled'}
        else:
            messages, backend_personalization_meta = _inject_auth_personalization_memory(messages)
        prep_ms = int((time.perf_counter() - t0) * 1000)

        t1 = time.perf_counter()
        client_override = _client_for_payload(payload)
        request_overrides = _extract_request_overrides(payload)
        access_ctx = _chat_async_owner_snapshot()
        request_overrides = _enforce_request_override_policy(payload, request_overrides, access_ctx=access_ctx)
        _set_request_overrides(request_overrides)
        app_logger.warning(
            "[DEBUG_REQUEST_OVERRIDES_SET] route=/api3/chat fallback=%r serper_key_len=%s keys=%s",
            app_getenv("SEARCH_FALLBACK_PROVIDER", "serper"),
            len(app_getenv("SERPER_API_KEY", "").strip()),
            sorted(request_overrides.keys()),
        )
        visual_ctx = _prefetch_visual_context(model, messages or [], last_user_text or user_text, client_override=client_override)
        if visual_ctx and visual_ctx.get("intent") == "clarify":
            return jsonify({"reply": str(visual_ctx.get("text") or "请再具体说明你想看的对象。"), "meta": {"model": model, "mode": "clarify"}})
        model_messages = _inject_visual_context_messages(messages, visual_ctx)
        content, meta = do_chat_with_meta(model, model_messages, user_geo=user_geo, user_time=user_time, client_override=client_override, visual_ctx=visual_ctx, web_enabled=payload.get("web_enabled"), web_k=payload.get("web_k"), web_max_pages=payload.get("web_max_pages"), runtime_model=str(payload.get("runtime_model") or '').strip())
        chat_ms = int((time.perf_counter() - t1) * 1000)

        meta = meta or {}
        meta['backend_personalization'] = backend_personalization_meta or {}
        meta.setdefault("timing", {})
        meta["timing"].update({"prepare_took_ms": prep_ms, "chat_took_ms": chat_ms, "total_took_ms": prep_ms + chat_ms})
        if stats:
            meta["fetch"] = stats
        return jsonify({"reply": content, "meta": meta})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 400
    finally:
        _set_request_overrides({})
