# Split from app3_parts/media/model_image_file_delivery_part.py.
# Purpose: image generation/edit settings and skill-mode normalization.
# Loaded by model_image_file_delivery_part.py via _exec_split_file(...), sharing the original global namespace.

IMAGE_GENERATION_DEFAULTS = {
    "engine": "openai_compatible",
    "model": "gpt-image-1",
    "api_base": "",
    "api_key": "",
    # 空值表示自动尺寸：OpenAI 兼容生图/改图请求默认不携带 size，
    # 避免第三方模型因不支持 1024x1024 之类固定尺寸而失败。
    "size": "",
    "extra_body": {},
}

IMAGE_EDIT_DEFAULTS = {
    "enabled": False,
    "engine": "openai_compatible",
    "model": "gpt-image-1",
    "api_base": "",
    "api_key": "",
    "size": "",
    "extra_body": {},
}


def _normalize_image_size_setting(value, *, legacy_default_as_auto: bool = False) -> str:
    raw = str(value if value is not None else '').strip().replace('×', 'x').replace(' ', '').lower()
    if raw in {'', 'auto', 'automatic', 'default', 'none', 'null', '自动', '默认'}:
        return ''
    if legacy_default_as_auto and raw == '1024x1024':
        return ''
    return raw


def _normalize_image_generation_engine(value) -> str:
    raw = str(value or '').strip().lower()
    aliases = {
        'openai': 'openai_compatible',
        'default': 'openai_compatible',
        'relay': 'openai_compatible',
        'openai_compatible': 'openai_compatible',
        'comfyui': 'comfyui',
        'a1111': 'automatic1111',
        'automatic1111': 'automatic1111',
        'automatic-1111': 'automatic1111',
        'gemini': 'gemini',
    }
    return aliases.get(raw, IMAGE_GENERATION_DEFAULTS['engine'])


def _coerce_image_extra_body(*values) -> dict:
    extra_body = {}
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            extra_body.update(dict(value))
        elif isinstance(value, str):
            raw_text = value.strip()
            if raw_text:
                try:
                    parsed = json.loads(raw_text)
                    if isinstance(parsed, dict):
                        extra_body.update(parsed)
                except Exception:
                    pass
    return extra_body


def _truthy_config_value(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    raw = str(value or '').strip().lower()
    return raw in {'1', 'true', 'yes', 'on', 'enable', 'enabled'}


def _normalize_image_edit_settings(raw: dict | None = None, *, generation: dict | None = None) -> dict:
    data = dict(raw or {}) if isinstance(raw, dict) else {}
    nested = data.get('edit') if isinstance(data.get('edit'), dict) else {}
    gen = dict(generation or {}) if isinstance(generation, dict) else {}
    enabled_raw = nested.get('enabled')
    if enabled_raw is None:
        enabled_raw = data.get('edit_enabled', data.get('image_edit_enabled', data.get('enable_image_edit', IMAGE_EDIT_DEFAULTS['enabled'])))
    engine = _normalize_image_generation_engine(nested.get('engine') or data.get('edit_engine') or data.get('image_edit_engine') or IMAGE_EDIT_DEFAULTS['engine'])
    model = str(nested.get('model') or data.get('edit_model') or data.get('image_edit_model') or IMAGE_EDIT_DEFAULTS['model']).strip() or IMAGE_EDIT_DEFAULTS['model']
    api_base = str(nested.get('api_base') or nested.get('base_url') or data.get('edit_api_base') or data.get('edit_base_url') or data.get('image_edit_api_base') or '').strip()
    api_key = str(nested.get('api_key') or nested.get('apiKey') or data.get('edit_api_key') or data.get('image_edit_api_key') or '').strip()
    size = _normalize_image_size_setting(nested.get('size') or data.get('edit_size') or data.get('image_edit_size') or IMAGE_EDIT_DEFAULTS['size'])
    extra_body = _coerce_image_extra_body(
        nested.get('extra_body'),
        nested.get('extra_params'),
        nested.get('extra'),
        data.get('edit_extra_body'),
        data.get('edit_extra_params'),
        data.get('image_edit_extra_body'),
    )
    return {
        'enabled': _truthy_config_value(enabled_raw),
        'engine': engine,
        'model': model,
        'api_base': api_base,
        'api_key': api_key,
        'size': size,
        'extra_body': extra_body,
    }


def _normalize_image_generation_settings(raw: dict | None = None) -> dict:
    data = dict(raw or {}) if isinstance(raw, dict) else {}
    model = str(data.get('model') or IMAGE_GENERATION_DEFAULTS['model']).strip() or IMAGE_GENERATION_DEFAULTS['model']
    api_base = str(data.get('api_base') or data.get('base_url') or data.get('apiBase') or '').strip()
    api_key = str(data.get('api_key') or data.get('apiKey') or '').strip()
    size_explicit = _truthy_config_value(data.get('size_explicit') or data.get('explicit_size') or data.get('force_size'))
    size = _normalize_image_size_setting(data.get('size') or IMAGE_GENERATION_DEFAULTS['size'], legacy_default_as_auto=not size_explicit)
    engine = _normalize_image_generation_engine(data.get('engine') or data.get('provider') or data.get('engine_type'))

    extra_body = _coerce_image_extra_body(data.get('extra_body'), data.get('extra_params'), data.get('extra'))

    legacy_quality = str(data.get('quality') or '').strip()
    legacy_background = str(data.get('background') or '').strip()
    legacy_output_format = str(data.get('output_format') or data.get('format') or '').strip()
    if legacy_quality and 'quality' not in extra_body:
        extra_body['quality'] = legacy_quality
    if legacy_background and 'background' not in extra_body:
        extra_body['background'] = legacy_background
    if legacy_output_format and 'output_format' not in extra_body and 'format' not in extra_body:
        extra_body['output_format'] = legacy_output_format

    out = {
        'engine': engine,
        'model': model,
        'api_base': api_base,
        'api_key': api_key,
        'size': size,
        'extra_body': extra_body,
    }
    out['edit'] = _normalize_image_edit_settings(data, generation=out)
    return out


def _image_skill_normalize_task_type(value: str = '') -> str:
    raw = str(value or '').strip().lower().replace('-', '_')
    aliases = {
        '': 'text_to_image',
        'generate': 'text_to_image',
        'generation': 'text_to_image',
        'image_generation': 'text_to_image',
        'txt2img': 'text_to_image',
        'text2image': 'text_to_image',
        'text_to_image': 'text_to_image',
        'reference': 'reference_generate',
        'reference_generation': 'reference_generate',
        'reference_generate': 'reference_generate',
        'edit': 'image_edit',
        'image_editing': 'image_edit',
        'image_edit': 'image_edit',
        'reference_edit': 'reference_edit',
        'variation': 'variation',
        'variant': 'variation',
    }
    return aliases.get(raw, raw if raw in {'text_to_image', 'reference_generate', 'image_edit', 'reference_edit', 'variation'} else 'text_to_image')


def _image_skill_task_mode(task_type: str = '') -> str:
    typ = _image_skill_normalize_task_type(task_type)
    if typ in {'image_edit', 'reference_edit', 'variation'}:
        return 'edit'
    if typ == 'reference_generate':
        return 'reference_generate'
    return 'generate'


def _image_skill_endpoint_mode(client_override=None, endpoint_mode: str = '') -> str:
    normalizer = globals().get('_normalize_payload_api_endpoint_mode') or globals().get('_normalize_chat_api_endpoint_mode')
    raw = str(endpoint_mode or '').strip()
    if not raw:
        try:
            raw = str(getattr(client_override, '_webai_api_endpoint_mode', '') or '').strip()
        except Exception:
            raw = ''
    if callable(normalizer):
        try:
            return normalizer(raw or 'chat_completions')
        except Exception:
            pass
    return 'responses' if raw.lower() in {'responses', 'response', '/responses'} else 'chat_completions'


def image_skill_intent(
    *,
    prompt: str = '',
    task_type: str = 'text_to_image',
    settings: dict | None = None,
    image_sources: list | None = None,
    endpoint_mode: str = '',
    client_override=None,
    response_model: str = '',
) -> dict:
    """Canonical image skill intent; adapters keep Chat and Responses protocols separate."""
    normalized_settings = _normalize_image_generation_settings(settings)
    mode = _image_skill_endpoint_mode(client_override=client_override, endpoint_mode=endpoint_mode)
    typ = _image_skill_normalize_task_type(task_type)
    sources = [str(x or '').strip() for x in (image_sources or []) if str(x or '').strip()]
    use_responses_native = False
    if mode == 'responses':
        try:
            use_responses_native = bool(_image_generation_should_use_responses_native(normalized_settings, client_override=client_override))
        except Exception:
            use_responses_native = True
    adapter = 'responses_native_image_generation' if mode == 'responses' and use_responses_native else 'chat_image_generation'
    return {
        'kind': 'image_skill_intent',
        'endpoint_mode': mode,
        'adapter': adapter,
        'task_type': typ,
        'task_mode': _image_skill_task_mode(typ),
        'prompt': str(prompt or '').strip(),
        'image_sources': sources,
        'source_image_count': len(sources),
        '_settings': normalized_settings,
        'public_settings': _image_generation_public_settings(normalized_settings),
        'response_model': str(response_model or '').strip(),
    }


def image_skill_generate(intent: dict | None = None, *, client_override=None) -> dict:
    """Dispatch one canonical image intent without merging Chat and Responses request protocols."""
    row = dict(intent or {}) if isinstance(intent, dict) else {}
    prompt = str(row.get('prompt') or '').strip()
    if not prompt:
        return {'ok': False, 'error': '缺少出图主体', 'intent': row}
    task_type = _image_skill_normalize_task_type(row.get('task_type') or row.get('task_mode') or '')
    task_mode = str(row.get('task_mode') or _image_skill_task_mode(task_type)).strip()
    return _generate_image_artifacts(
        prompt,
        settings=row.get('_settings') if isinstance(row.get('_settings'), dict) else (row.get('settings') if isinstance(row.get('settings'), dict) else {}),
        client_override=client_override,
        image_sources=row.get('image_sources') if isinstance(row.get('image_sources'), list) else [],
        task_mode=task_mode,
        response_model=str(row.get('response_model') or ''),
    )

def _image_generation_public_settings(settings: dict | None = None) -> dict:
    data = dict(settings or {}) if isinstance(settings, dict) else {}

    def _scrub(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                key = str(k or '')
                low = key.lower()
                if key.startswith('_'):
                    continue
                if low in {'api_key', 'apikey', 'key', 'token', 'authorization', 'auth', 'secret', 'password'}:
                    continue
                if any(mark in low for mark in ('api_key', 'apikey', 'authorization', 'secret', 'password')):
                    continue
                out[key] = _scrub(v)
            return out
        if isinstance(obj, list):
            return [_scrub(x) for x in obj]
        return obj

    return _scrub(data)


def _preferred_image_generation_ext(settings: dict | None = None) -> str:
    data = dict(settings or {}) if isinstance(settings, dict) else {}
    extra_body = data.get('extra_body') if isinstance(data.get('extra_body'), dict) else {}
    raw_ext = str((extra_body.get('output_format') or extra_body.get('format') or extra_body.get('image_format') or extra_body.get('ext') or '')).strip().lower()
    if raw_ext == 'jpg':
        raw_ext = 'jpeg'
    if raw_ext in {'png', 'jpeg', 'webp'}:
        return raw_ext
    return 'png'


def _maybe_build_generated_image_preview(src_path: str, filename: str, scope: str | None = None, *, mime: str = '', size_bytes: int = 0) -> dict:
    try:
        ext = os.path.splitext(str(filename or '').strip())[1].lower()
        low_mime = str(mime or '').strip().lower()
        if not (low_mime.startswith('image/') or ext in {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'}):
            return {}
        trigger_bytes = max(256 * 1024, int(str(app_getenv('IMAGE_GENERATION_PREVIEW_TRIGGER_BYTES', '1800000') or '1800000')) )
        max_side = max(512, int(str(app_getenv('IMAGE_GENERATION_PREVIEW_MAX_SIDE', '1536') or '1536')) )
        quality = max(50, min(int(str(app_getenv('IMAGE_GENERATION_PREVIEW_QUALITY', '82') or '82')), 95))
        from PIL import Image, ImageOps  # type: ignore
        with Image.open(src_path) as im0:
            im = ImageOps.exif_transpose(im0)
            width, height = im.size
            if size_bytes < trigger_bytes and max(width, height) <= max_side:
                return {}
            preview = im.copy()
            preview.thumbnail((max_side, max_side), Image.LANCZOS)
            if preview.mode not in ('RGB', 'L'):
                bg = Image.new('RGB', preview.size, (255, 255, 255))
                alpha = preview.getchannel('A') if 'A' in preview.getbands() else None
                bg.paste(preview.convert('RGBA'), mask=alpha)
                preview = bg
            elif preview.mode != 'RGB':
                preview = preview.convert('RGB')
            stem = os.path.splitext(os.path.basename(str(filename or '').strip()))[0] or 'image'
            preview_name = _safe_filename(f'{stem}__preview.jpg')
            preview_path = os.path.join(_generated_dir_for_scope(scope), preview_name)
            buf = io.BytesIO()
            preview.save(buf, format='JPEG', quality=quality, optimize=True)
            raw = buf.getvalue()
            _write_bytes_atomic(preview_path, raw)
            try:
                registrar = globals().get('_storage_quota_register_file')
                owner_fn = globals().get('_generated_artifact_registry_owner_key')
                owner_key = str(owner_fn() if callable(owner_fn) else '').strip().lower()
                normalized_scope = _normalize_upload_scope(scope)
                if callable(registrar):
                    registrar(owner_key=owner_key or None, namespace='generated', scope=normalized_scope, path=preview_path, size_bytes=len(raw), filename=preview_name)
                    _image_generation_log('preview_quota_registered', filename=preview_name, scope=normalized_scope, owner=owner_key or '', size=len(raw))
            except Exception:
                pass
            mirror_queued = _object_storage_mirror_file_async('generated', scope, preview_name, preview_path, content_type='image/jpeg')
            view_url, download_url = _build_generated_file_urls(preview_name, scope)
            return {
                'filename': preview_name,
                'path': preview_path,
                'view_url': view_url,
                'download_url': download_url,
                'size': len(raw),
                'mime': 'image/jpeg',
                'storage_backend': 'object+local' if mirror_queued else 'local',
            }
    except Exception as e:
        try:
            app_logger.warning('[image_preview] build_failed filename=%s err=%s', filename, e)
        except Exception:
            pass
        return {}


def _resolve_image_generation_identity(*, settings: dict | None = None, client_override=None) -> tuple[str, str]:
    image_settings = _normalize_image_generation_settings(settings)
    api_key, base_url = _resolve_openai_client_identity(client_override)
    if image_settings.get('api_key'):
        api_key = str(image_settings.get('api_key') or '').strip()
    if image_settings.get('api_base'):
        base_url = str(image_settings.get('api_base') or '').strip()
    return api_key, (base_url or GPT_BASE_URL or '').strip()
