# Split from app3_parts/media/async_pullback_upload_server_part.py.
# Purpose: read-aloud speech settings and proxy route.
# Loaded by async_pullback_upload_server_part.py via _exec_split_file(...), sharing the original global namespace.

# ==============================
# READ ALOUD OUTPUT (message text -> OpenAI-compatible TTS audio)
# ==============================
def _read_aloud_bool(value, default=False) -> bool:
    if value is None:
        return bool(default)
    raw = str(value).strip().lower()
    if raw in {'1', 'true', 'yes', 'on', '开启'}:
        return True
    if raw in {'0', 'false', 'no', 'off', '关闭'}:
        return False
    return bool(default)


def _read_aloud_response_format(value: str = '') -> str:
    raw = str(value or '').strip().lower()
    return raw if raw in {'mp3', 'opus', 'wav', 'pcm'} else 'mp3'


def _read_aloud_base_url(api_base: str = '') -> str:
    raw = str(api_base or '').strip()
    if not raw:
        return ''
    try:
        parsed = urlparse(raw)
        if not parsed.scheme or not parsed.netloc:
            return ''
        scheme = str(parsed.scheme or 'https').strip().lower() or 'https'
        if scheme not in {'http', 'https'}:
            return ''
        netloc = str(parsed.netloc or '').strip()
        path = str(parsed.path or '').strip().rstrip('/')
        for suffix in ('/audio/speech', '/audio/transcriptions', '/chat/completions', '/responses', '/completions', '/embeddings', '/models'):
            if path.endswith(suffix):
                path = path[:-len(suffix)].rstrip('/')
                break
        return urlunparse((scheme, netloc, path, '', '', '')).rstrip('/')
    except Exception:
        return ''


def _read_aloud_endpoint(base_url: str = '', endpoint: str = '') -> str:
    raw_endpoint = str(endpoint or '').strip()
    if raw_endpoint:
        try:
            parsed = urlparse(raw_endpoint)
            if str(parsed.scheme or '').lower() not in {'http', 'https'} or not parsed.netloc:
                return ''
            return raw_endpoint.rstrip('/')
        except Exception:
            return ''
    base = _read_aloud_base_url(base_url)
    if not base:
        return ''
    return base.rstrip('/') + '/audio/speech'


def _read_aloud_private_endpoint_allowed() -> bool:
    try:
        return str(app_getenv('READ_ALOUD_ALLOW_PRIVATE_ENDPOINT', '1') or '1').strip().lower() in {'1', 'true', 'yes', 'on'}
    except Exception:
        return True


@app.post('/api3/read-aloud/speech')
def api3_read_aloud_speech():
    payload = request.get_json(force=True, silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    text = str(payload.get('text') or payload.get('input') or '').strip()
    if not text:
        return jsonify({'ok': False, 'error': 'missing_text'}), 400
    max_chars = 12000
    try:
        max_chars = max(500, min(30000, int(app_getenv('READ_ALOUD_MAX_CHARS', '12000') or '12000')))
    except Exception:
        max_chars = 12000
    if len(text) > max_chars:
        text = text[:max_chars]

    settings = payload.get('read_aloud_settings') or payload.get('settings') or {}
    if not isinstance(settings, dict):
        settings = {}
    api_settings = payload.get('api_settings') or {}
    if not isinstance(api_settings, dict):
        api_settings = {}

    follow_chat_api = _read_aloud_bool(settings.get('follow_chat_api'), default=True)
    api_key = str(settings.get('api_key') or '').strip()
    base_url = str(settings.get('base_url') or settings.get('api_base') or '').strip()
    if follow_chat_api:
        api_key = api_key or str(api_settings.get('api_key') or '').strip()
        base_url = base_url or str(api_settings.get('api_base') or api_settings.get('base_url') or '').strip()
    api_key = api_key or str(app_getenv('READ_ALOUD_API_KEY', '') or '').strip()
    base_url = base_url or str(app_getenv('READ_ALOUD_BASE_URL', '') or '').strip() or str(GPT_BASE_URL or '').strip()

    model = str(settings.get('model') or app_getenv('READ_ALOUD_MODEL', 'gpt-4o-mini-tts') or 'gpt-4o-mini-tts').strip() or 'gpt-4o-mini-tts'
    voice = str(settings.get('voice') or app_getenv('READ_ALOUD_VOICE', 'sage') or 'sage').strip() or 'sage'
    instructions = str(settings.get('instructions') or app_getenv('READ_ALOUD_INSTRUCTIONS', '') or '').strip()[:1200]
    response_format = _read_aloud_response_format(settings.get('response_format') or settings.get('format') or 'mp3')
    endpoint = _read_aloud_endpoint(base_url, settings.get('speech_url') or settings.get('endpoint') or '')

    if not api_key:
        return jsonify({'ok': False, 'error': 'missing_api_key'}), 400
    if not endpoint:
        return jsonify({'ok': False, 'error': 'missing_or_invalid_tts_base_url'}), 400
    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname or ''
        if (not _read_aloud_private_endpoint_allowed()) and callable(globals().get('_is_private_host')) and globals()['_is_private_host'](host):
            return jsonify({'ok': False, 'error': 'private_tts_endpoint_blocked'}), 400
    except Exception:
        pass

    body = {
        'model': model,
        'voice': voice,
        'input': text,
        'response_format': response_format,
    }
    if instructions:
        body['instructions'] = instructions
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'Accept': 'audio/*, application/octet-stream, application/json',
    }
    try:
        resp = HTTPX_GPT.post(endpoint, headers=headers, json=body, timeout=float(app_getenv('READ_ALOUD_TIMEOUT_SECONDS', '90') or '90'))
        content_type = str(resp.headers.get('content-type') or '').split(';', 1)[0].strip().lower()
        raw = resp.content or b''
        if resp.status_code >= 400:
            err = ''
            try:
                err = str(resp.json().get('error') or resp.json().get('message') or '')
            except Exception:
                try:
                    err = resp.text[:2000]
                except Exception:
                    err = ''
            try:
                app_logger.warning('[read_aloud_speech] provider_error status=%s endpoint=%s model=%s voice=%s format=%s chars=%s error=%s', resp.status_code, endpoint, model, voice, response_format, len(text), (err or str(resp.text or '')[:1000]))
            except Exception:
                pass
            return jsonify({'ok': False, 'error': err or f'HTTP {resp.status_code}', 'provider_status': int(resp.status_code or 0)}), 502
        if not raw:
            return jsonify({'ok': False, 'error': 'empty_audio'}), 502
        if 'json' in content_type:
            try:
                data = resp.json()
            except Exception:
                data = {}
            return jsonify({'ok': False, 'error': str((data or {}).get('error') or (data or {}).get('message') or 'provider_returned_json')}), 502
        mimetype = content_type or ({'mp3':'audio/mpeg','opus':'audio/opus','wav':'audio/wav','pcm':'audio/L16'}.get(response_format) or 'audio/mpeg')
        return Response(raw, mimetype=mimetype, headers={
            'Cache-Control': 'no-store',
            'X-WebAI-TTS-Model': model,
            'X-WebAI-TTS-Voice': voice,
        })
    except Exception as e:
        try:
            app_logger.exception('[read_aloud_speech] failed endpoint=%s model=%s voice=%s chars=%s', endpoint, model, voice, len(text))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 502
