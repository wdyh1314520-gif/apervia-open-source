# Split from app3_parts/media/async_pullback_upload_server_part.py.
# Purpose: voice transcription settings, local Whisper fallback, and transcription route.
# Loaded by async_pullback_upload_server_part.py via _exec_split_file(...), sharing the original global namespace.

# ==============================
# VOICE INPUT TRANSCRIPTION (browser recorder -> OpenAI-compatible audio API)
# ==============================
def _voice_transcribe_parse_api_settings(raw: str = '') -> dict:
    try:
        data = json.loads(str(raw or '').strip() or '{}')
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _voice_transcribe_form_value(*names: str, default: str = '') -> str:
    for name in names:
        try:
            value = str(request.form.get(name) or '').strip()
        except Exception:
            value = ''
        if value:
            return value
    return str(default or '').strip()


def _voice_transcribe_base_url(api_base: str = '') -> str:
    raw = str(api_base or '').strip() or str(GPT_BASE_URL or '').strip()
    if not raw:
        return ''
    try:
        parsed = urlparse(raw)
        if not parsed.scheme or not parsed.netloc:
            return ''
        scheme = str(parsed.scheme or 'https').strip().lower() or 'https'
        netloc = str(parsed.netloc or '').strip()
        path = str(parsed.path or '').strip().rstrip('/')
        for suffix in ('/audio/transcriptions', '/chat/completions', '/responses', '/completions', '/embeddings', '/models'):
            if path.endswith(suffix):
                path = path[:-len(suffix)].rstrip('/')
                break
        return urlunparse((scheme, netloc, path, '', '', '')).rstrip('/')
    except Exception:
        return ''


def _voice_transcribe_endpoint(api_base: str = '') -> str:
    base = _voice_transcribe_base_url(api_base)
    if not base:
        return ''
    return base.rstrip('/') + '/audio/transcriptions'


def _voice_transcribe_normalize_endpoint(endpoint: str = '', api_base: str = '') -> str:
    raw = str(endpoint or '').strip()
    if raw:
        try:
            parsed = urlparse(raw)
            if str(parsed.scheme or '').lower() not in {'http', 'https'} or not parsed.netloc:
                return ''
            try:
                allow_private = str(app_getenv('VOICE_TRANSCRIBE_ALLOW_PRIVATE_ENDPOINT', '0') or '0').strip().lower() in {'1', 'true', 'yes', 'on'}
            except Exception:
                allow_private = False
            try:
                host = parsed.hostname or ''
                if (not allow_private) and callable(globals().get('_is_private_host')) and globals()['_is_private_host'](host):
                    return ''
            except Exception:
                pass
            return raw
        except Exception:
            return ''
    return _voice_transcribe_endpoint(api_base)


def _voice_transcribe_response_format(value: str = '') -> str:
    raw = str(value or '').strip().lower()
    if raw in {'json', 'text', 'verbose_json', 'srt', 'vtt'}:
        return raw
    return 'json'


def _voice_transcribe_max_bytes() -> int:
    try:
        return max(512 * 1024, min(int(str(app_getenv('VOICE_TRANSCRIBE_MAX_BYTES', str(25 * 1024 * 1024)) or (25 * 1024 * 1024))), 80 * 1024 * 1024))
    except Exception:
        return 25 * 1024 * 1024


def _voice_transcribe_normalize_language(value: str = '') -> str:
    raw = str(value or '').strip().lower().replace('_', '-')
    if not raw:
        return ''
    head = raw.split('-', 1)[0].strip()
    if re.fullmatch(r'[a-z]{2,3}', head or ''):
        return head
    return ''


def _voice_transcribe_engine(value: str = '') -> str:
    raw = str(value or '').strip().lower()
    if raw in {'local', 'whisper', 'faster_whisper', 'faster-whisper', 'local_whisper'}:
        return 'local_whisper'
    if raw in {'web', 'webapi', 'web_api', 'browser'}:
        return 'web_api'
    return 'openai_compatible'


def _voice_transcribe_bool(value, default: bool = False) -> bool:
    if value is None or value == '':
        return bool(default)
    if isinstance(value, bool):
        return value
    raw = str(value or '').strip().lower()
    if raw in {'1', 'true', 'yes', 'on', 'enable', 'enabled'}:
        return True
    if raw in {'0', 'false', 'no', 'off', 'disable', 'disabled'}:
        return False
    return bool(default)


def _voice_transcribe_mime_patterns(value: str = '') -> list[str]:
    raw = str(value or '').strip()
    if not raw:
        return []
    out = []
    for item in re.split(r'[，,\n]+', raw):
        it = str(item or '').strip().lower()
        if not it or '/' not in it:
            continue
        if not re.fullmatch(r'[a-z0-9.+-]+/(?:[a-z0-9.+*-]+)', it):
            continue
        if it not in out:
            out.append(it)
        if len(out) >= 24:
            break
    return out


def _voice_transcribe_mime_allowed(mimetype: str = '', patterns: list[str] | None = None) -> bool:
    pats = [str(x or '').strip().lower() for x in (patterns or []) if str(x or '').strip()]
    if not pats:
        return True
    mime = str(mimetype or '').split(';', 1)[0].strip().lower()
    if not mime:
        return False
    for pat in pats:
        if pat.endswith('/*'):
            prefix = pat.split('/', 1)[0] + '/'
            if mime.startswith(prefix):
                return True
        elif mime == pat:
            return True
    return False


try:
    _VOICE_LOCAL_WHISPER_LOCK
except Exception:
    _VOICE_LOCAL_WHISPER_LOCK = threading.Lock()
try:
    _VOICE_LOCAL_WHISPER_CACHE
except Exception:
    _VOICE_LOCAL_WHISPER_CACHE = {}


def _voice_transcribe_local_whisper_model(model_id: str, device: str = 'auto', compute_type: str = 'auto'):
    model_name = str(model_id or 'base').strip() or 'base'
    device_name = str(device or 'auto').strip().lower() or 'auto'
    compute = str(compute_type or 'auto').strip().lower() or 'auto'
    if device_name not in {'auto', 'cpu', 'cuda'}:
        device_name = 'auto'
    if compute not in {'auto', 'int8', 'float16', 'float32'}:
        compute = 'auto'
    key = (model_name, device_name, compute)
    with _VOICE_LOCAL_WHISPER_LOCK:
        cached = _VOICE_LOCAL_WHISPER_CACHE.get(key)
        if cached is not None:
            return cached
        try:
            fw = __import__('faster_whisper', fromlist=['WhisperModel'])
            WhisperModel = getattr(fw, 'WhisperModel')
        except Exception as e:
            raise RuntimeError('本地 Whisper 未安装：请先在服务器安装 faster-whisper，或切回 OpenAI 兼容引擎') from e
        kwargs = {}
        if device_name:
            kwargs['device'] = device_name
        if compute:
            kwargs['compute_type'] = compute
        try:
            model = WhisperModel(model_name, **kwargs)
        except TypeError:
            kwargs.pop('compute_type', None)
            model = WhisperModel(model_name, **kwargs)
        if len(_VOICE_LOCAL_WHISPER_CACHE) >= 3:
            try:
                _VOICE_LOCAL_WHISPER_CACHE.pop(next(iter(_VOICE_LOCAL_WHISPER_CACHE.keys())), None)
            except Exception:
                _VOICE_LOCAL_WHISPER_CACHE.clear()
        _VOICE_LOCAL_WHISPER_CACHE[key] = model
        return model


def _voice_transcribe_local_whisper(raw: bytes, *, filename: str = '', mimetype: str = '', model_id: str = 'base', language: str = '', prompt: str = '', device: str = 'auto', compute_type: str = 'auto', vad_filter: bool = True) -> dict:
    suffix = os.path.splitext(str(filename or 'voice-input.webm'))[1].strip().lower()
    if not suffix or len(suffix) > 12 or not re.fullmatch(r'\.[0-9a-z]+', suffix):
        mt = str(mimetype or '').lower()
        if 'wav' in mt:
            suffix = '.wav'
        elif 'mpeg' in mt or 'mp3' in mt:
            suffix = '.mp3'
        elif 'mp4' in mt:
            suffix = '.m4a'
        else:
            suffix = '.webm'
    tmp_path = ''
    try:
        tf = tempfile.NamedTemporaryFile(prefix='webai_voice_', suffix=suffix, delete=False)
        tmp_path = tf.name
        with tf:
            tf.write(raw or b'')
        model = _voice_transcribe_local_whisper_model(model_id, device=device, compute_type=compute_type)
        kwargs = {
            'vad_filter': bool(vad_filter),
        }
        if language:
            kwargs['language'] = language
        if prompt:
            kwargs['initial_prompt'] = prompt
        segments, info = model.transcribe(tmp_path, **kwargs)
        parts = []
        for seg in segments:
            text = str(getattr(seg, 'text', '') or '').strip()
            if text:
                parts.append(text)
        text = ' '.join(parts).strip()
        if not text:
            raise RuntimeError('empty_transcription')
        return {
            'ok': True,
            'text': text,
            'model': str(model_id or 'base'),
            'engine': 'local_whisper',
            'language': str(getattr(info, 'language', '') or language or ''),
        }
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@app.post('/api3/voice/transcribe')
def api3_voice_transcribe():
    # OpenWebUI-style STT endpoint:
    # - openai_compatible: forward recorded audio to /audio/transcriptions
    # - local_whisper: optional server-side faster-whisper when installed
    # - web_api: handled by browser and should not call this endpoint
    f = request.files.get('audio') or request.files.get('file')
    if not f:
        return jsonify({'ok': False, 'error': '没有收到语音文件字段 audio'}), 400
    raw = f.read() or b''
    if not raw:
        return jsonify({'ok': False, 'error': '语音文件为空'}), 400
    max_bytes = _voice_transcribe_max_bytes()
    if len(raw) > max_bytes:
        return jsonify({'ok': False, 'error': f'语音文件过大，最大 {max_bytes // (1024 * 1024)}MB'}), 413

    form_api_settings = _voice_transcribe_parse_api_settings(request.form.get('api_settings') or '')
    voice_settings = _voice_transcribe_parse_api_settings(request.form.get('voice_settings') or '')
    engine = _voice_transcribe_engine(
        request.form.get('engine')
        or voice_settings.get('engine')
        or voice_settings.get('stt_engine')
        or app_getenv('VOICE_TRANSCRIBE_ENGINE', 'openai_compatible')
    )
    if engine == 'web_api':
        return jsonify({'ok': False, 'error': 'web_api_browser_only'}), 400

    filename = str(getattr(f, 'filename', '') or 'voice-input.webm').strip() or 'voice-input.webm'
    mimetype = str(getattr(f, 'mimetype', '') or 'application/octet-stream').strip() or 'application/octet-stream'
    mime_patterns = _voice_transcribe_mime_patterns(
        request.form.get('mime_types')
        or voice_settings.get('mime_types')
        or voice_settings.get('supported_mime_types')
        or app_getenv('VOICE_TRANSCRIBE_MIME_TYPES', '')
        or ''
    )
    if not _voice_transcribe_mime_allowed(mimetype, mime_patterns):
        return jsonify({'ok': False, 'error': f'unsupported_mime_type:{mimetype}'}), 415

    language = _voice_transcribe_normalize_language(request.form.get('language') or voice_settings.get('language') or '')
    response_format = _voice_transcribe_response_format(request.form.get('response_format') or voice_settings.get('response_format') or 'json')
    prompt = str(request.form.get('prompt') or voice_settings.get('prompt') or '').strip()[:1000]

    if engine == 'local_whisper':
        local_model = str(
            request.form.get('local_model')
            or voice_settings.get('local_model')
            or voice_settings.get('whisper_model')
            or request.form.get('model')
            or app_getenv('VOICE_LOCAL_WHISPER_MODEL', 'base')
            or 'base'
        ).strip() or 'base'
        local_device = str(request.form.get('local_device') or voice_settings.get('local_device') or app_getenv('VOICE_LOCAL_WHISPER_DEVICE', 'auto') or 'auto').strip().lower()
        local_compute = str(request.form.get('local_compute_type') or voice_settings.get('local_compute_type') or app_getenv('VOICE_LOCAL_WHISPER_COMPUTE_TYPE', 'auto') or 'auto').strip().lower()
        vad_filter = _voice_transcribe_bool(request.form.get('local_vad_filter') or voice_settings.get('local_vad_filter'), default=True)
        try:
            result = _voice_transcribe_local_whisper(
                raw,
                filename=filename,
                mimetype=mimetype,
                model_id=local_model,
                language=language,
                prompt=prompt,
                device=local_device,
                compute_type=local_compute,
                vad_filter=vad_filter,
            )
            result['response_format'] = response_format
            return jsonify(result)
        except Exception as e:
            try:
                app_logger.exception('[voice_transcribe_local] failed model=%s filename=%s bytes=%s', local_model, filename, len(raw))
            except Exception:
                pass
            return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}', 'engine': 'local_whisper'}), 502

    api_key = str(
        request.form.get('api_key')
        or voice_settings.get('api_key')
        or form_api_settings.get('api_key')
        or ''
    ).strip()
    api_base = str(
        request.form.get('api_base')
        or voice_settings.get('api_base')
        or form_api_settings.get('api_base')
        or GPT_BASE_URL
        or ''
    ).strip()
    endpoint_raw = str(
        request.form.get('transcribe_url')
        or request.form.get('endpoint')
        or request.form.get('voice_transcribe_url')
        or voice_settings.get('transcribe_url')
        or voice_settings.get('endpoint')
        or app_getenv('VOICE_TRANSCRIBE_ENDPOINT', '')
        or ''
    ).strip()
    model = str(request.form.get('model') or voice_settings.get('model') or app_getenv('VOICE_TRANSCRIBE_MODEL', 'whisper-1') or 'whisper-1').strip() or 'whisper-1'
    if not api_key:
        return jsonify({'ok': False, 'error': 'missing_api_key'}), 400
    endpoint = _voice_transcribe_normalize_endpoint(endpoint_raw, api_base)
    if not endpoint:
        return jsonify({'ok': False, 'error': 'missing_or_invalid_transcribe_url'}), 400

    multipart = {
        'file': (filename, raw, mimetype),
        'model': (None, model),
        'response_format': (None, response_format),
    }
    if language:
        multipart['language'] = (None, language)
    if prompt:
        multipart['prompt'] = (None, prompt)
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Accept': 'application/json',
    }
    try:
        resp = HTTPX_GPT_FILE.post(endpoint, headers=headers, files=multipart)
        raw_text = str(resp.text or '').strip()
        if resp.status_code >= 400:
            return jsonify({
                'ok': False,
                'error': raw_text[:2000] or f'HTTP {resp.status_code}',
                'provider_status': int(resp.status_code or 0),
                'engine': 'openai_compatible',
            }), 502
        try:
            data = resp.json()
        except Exception:
            data = {}
        text = ''
        if isinstance(data, dict):
            text = str(data.get('text') or data.get('transcript') or '').strip()
            if not text and isinstance(data.get('segments'), list):
                text = ' '.join(str((seg or {}).get('text') or '').strip() for seg in data.get('segments') or [] if isinstance(seg, dict)).strip()
        if not text and raw_text:
            text = raw_text.strip()
        if not text:
            return jsonify({'ok': False, 'error': 'empty_transcription', 'engine': 'openai_compatible'}), 502
        return jsonify({'ok': True, 'text': text, 'model': model, 'response_format': response_format, 'engine': 'openai_compatible'})
    except Exception as e:
        try:
            app_logger.exception('[voice_transcribe] failed endpoint=%s model=%s filename=%s bytes=%s', endpoint, model, filename, len(raw))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}', 'engine': 'openai_compatible'}), 502
