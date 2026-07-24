# image generation/edit provider adapters and dispatch.

def _resolve_image_edit_identity(*, settings: dict | None = None, client_override=None) -> tuple[str, str]:
    normalized = _normalize_image_generation_settings(settings)
    edit = normalized.get('edit') if isinstance(normalized.get('edit'), dict) else {}
    api_key, base_url = _resolve_image_generation_identity(settings=normalized, client_override=client_override)
    if edit.get('api_key'):
        api_key = str(edit.get('api_key') or '').strip()
    if edit.get('api_base'):
        base_url = str(edit.get('api_base') or '').strip()
    return api_key, (base_url or GPT_BASE_URL or '').strip()


def _decode_image_data_url_to_bytes(data_url: str) -> tuple[bytes, str]:
    raw = str(data_url or '').strip()
    if not raw.startswith('data:image/') or 'base64,' not in raw:
        return b'', ''
    try:
        header, b64 = raw.split('base64,', 1)
        mime = header.split(';', 1)[0].replace('data:', '').strip() or 'application/octet-stream'
        data = base64.b64decode((b64 or '').strip(), validate=False)
        return data, mime
    except Exception:
        return b'', ''


def _read_image_edit_source_bytes(source: str) -> tuple[bytes, str, str]:
    u = str(source or '').strip()
    if not u:
        return b'', '', ''
    filename = 'image.png'
    if u.startswith('upload://'):
        try:
            scope, fname = _parse_upload_storage_ref(u)
            raw, mime = _read_upload_storage_ref_bytes(u)
            if raw:
                raw, mime = _coerce_image_bytes_for_model(raw, mime or UPLOAD_IMAGE_MIME_BY_EXT.get(_ext_of(fname), '') or 'application/octet-stream')
                return raw, mime, fname or filename
        except Exception:
            return b'', '', ''
    try:
        has_scheme = bool(re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', u))
    except Exception:
        has_scheme = False
    if u and not has_scheme and not u.startswith('/'):
        try:
            getter = globals().get('_file_library_get_record')
            resolver = globals().get('_file_library_resolve_local_path')
            category_fn = globals().get('_file_library_category')
            if callable(getter) and callable(resolver):
                rec = getter(u) or {}
                if isinstance(rec, dict) and rec:
                    local_path = str(resolver(rec) or '').strip()
                    ext = str(_ext_of(rec.get('filename') or rec.get('saved_filename') or local_path or '') or '').strip().lower()
                    category = str(category_fn(rec.get('filename') or rec.get('saved_filename') or local_path or '', ext) if callable(category_fn) else '').strip().lower()
                    if local_path and os.path.isfile(local_path) and (category == 'image' or ext in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.heic', '.heif'}):
                        with open(local_path, 'rb') as f:
                            raw = f.read()
                        mime = UPLOAD_IMAGE_MIME_BY_EXT.get(ext, '') or 'application/octet-stream'
                        raw, mime = _coerce_image_bytes_for_model(raw, mime)
                        return raw, mime, os.path.basename(local_path) or filename
        except Exception:
            pass
    data_url = None
    if u.startswith('data:image/'):
        data_url = u
    else:
        try:
            data_url = _normalize_image_input_to_data_url(u)
        except Exception:
            data_url = None
    if data_url:
        raw, mime = _decode_image_data_url_to_bytes(data_url)
        if raw:
            try:
                raw, mime = _coerce_image_bytes_for_model(raw, mime or 'application/octet-stream')
            except Exception:
                pass
            ext = _model_image_ext_for_mime(mime or 'image/png')
            return raw, mime or 'image/png', 'image' + ext
    return b'', '', ''


def _collect_image_edit_inputs(image_sources: list | None = None, *, max_images: int = 4) -> list[dict]:
    out = []
    seen = set()
    try:
        limit = max(1, min(int(max_images or 4), 16))
    except Exception:
        limit = 4
    for src in image_sources or []:
        raw_src = str(src or '').strip()
        if not raw_src or raw_src in seen:
            continue
        seen.add(raw_src)
        raw, mime, filename = _read_image_edit_source_bytes(raw_src)
        if not raw:
            continue
        out.append({'raw': raw, 'mime': mime or 'image/png', 'filename': filename or 'image.png', 'source': raw_src})
        if len(out) >= limit:
            break
    return out


def _generate_image_edit_artifacts_openai_compatible(prompt_text: str, normalized: dict, image_sources: list | None = None, *, client_override=None) -> dict:
    edit = normalized.get('edit') if isinstance(normalized.get('edit'), dict) else _normalize_image_edit_settings(normalized)
    api_key, base_url = _resolve_image_edit_identity(settings=normalized, client_override=client_override)
    endpoint = _openai_image_edit_endpoint(base_url)
    raw_extra_body = dict(edit.get('extra_body') or {}) if isinstance(edit.get('extra_body'), dict) else {}
    extra_body = _image_generation_external_extra_body(raw_extra_body)
    try:
        max_input_images = int(extra_body.pop('max_input_images', extra_body.pop('max_images', 4)) or 4)
    except Exception:
        max_input_images = 4
    inputs = _collect_image_edit_inputs(image_sources or [], max_images=max_input_images)
    if not inputs:
        return {
            'ok': False,
            'artifacts': [],
            'settings': _image_generation_public_settings(normalized),
            'error': '图片编辑需要先上传或引用一张图片',
            'need_clarification': True,
            'clarification_question': '请先上传要编辑的图片，或说明要编辑哪一张最近的图片。',
        }
    ext = _preferred_image_generation_ext({'extra_body': extra_body})
    req = {
        'model': str(edit.get('model') or normalized.get('model') or IMAGE_EDIT_DEFAULTS['model']).strip(),
        'prompt': prompt_text,
        'n': int(extra_body.pop('n', 1) or 1),
    }
    size = str(edit.get('size') or '').strip()
    if size:
        req['size'] = size
    image_field = str(extra_body.pop('multipart_image_field', extra_body.pop('image_field', 'image')) or 'image').strip() or 'image'
    mask_source = extra_body.pop('mask_source', extra_body.pop('mask_url', extra_body.pop('mask', None)))
    mask_part = None
    if mask_source:
        raw, mime, filename = _read_image_edit_source_bytes(str(mask_source))
        if raw:
            mask_part = ('mask', (filename or 'mask.png', raw, mime or 'image/png'))
    for key, value in list(extra_body.items()):
        if key in {'prompt', 'n', 'model', 'size', 'image', 'images', 'mask'}:
            continue
        req[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    headers = {}
    auth_headers = None
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
        auth_headers = {'Authorization': f'Bearer {api_key}'}
    files = []
    for idx, item in enumerate(inputs, start=1):
        files.append((image_field, (str(item.get('filename') or f'image_{idx}.png'), item.get('raw') or b'', str(item.get('mime') or 'image/png'))))
    if mask_part:
        files.append(mask_part)
    http_client = None
    try:
        http_client = _image_http_client()
        started = time.time()
        _image_generation_log('request_start', task_mode='edit', endpoint=endpoint, model=req.get('model'), timeout_s=normalized.get('_operation_timeout_s'), size=req.get('size') or '', input_image_count=len(inputs), request_keys=sorted(req.keys()), file_parts=len(files))
        resp = _image_generation_http_request_with_retry(http_client, 'POST', endpoint, data={k: str(v) for k, v in req.items() if v is not None}, files=files, headers=headers, extra_body=raw_extra_body)
        elapsed_ms = int((time.time() - started) * 1000)
        parsed = _parse_image_generation_http_response(resp, default_ext=ext)
        meta = parsed.get('meta') or {}
        _image_generation_log('response_received', task_mode='edit', endpoint=endpoint, elapsed_ms=elapsed_ms, status=meta.get('status_code'), content_type=meta.get('content_type'), body_bytes=meta.get('body_bytes'), parse_mode=meta.get('parse_mode'), payload_keys=meta.get('payload_keys'), item_count=meta.get('item_count'), item_types=meta.get('item_types'), json_error=meta.get('json_error'), body_preview=meta.get('body_preview'))
        saved = list(parsed.get('artifacts') or [])
        if not saved:
            items = list(parsed.get('items') or [])
            saved = _save_image_b64_items(items, ext=ext, auth_headers=auth_headers)
        error_text = '' if saved else ('图片编辑接口未返回可保存的图片数据' if not str(meta.get('json_error') or '').strip() else f'图片编辑接口未返回可保存的图片数据（{meta.get("json_error")}）')
        _image_generation_log('request_done', task_mode='edit', ok=bool(saved), saved_count=len(saved), filenames=[str(x.get('filename') or '') for x in saved[:8]], error=error_text)
        return {
            'ok': bool(saved),
            'artifacts': saved,
            'settings': _image_generation_public_settings(normalized),
            'task_mode': 'edit',
            'input_image_count': len(inputs),
            'error': error_text,
        }
    finally:
        _close_httpx_client_quietly(http_client)


def _generate_image_edit_artifacts_automatic1111(prompt_text: str, normalized: dict, image_sources: list | None = None, *, client_override=None) -> dict:
    edit = normalized.get('edit') if isinstance(normalized.get('edit'), dict) else _normalize_image_edit_settings(normalized)
    api_key, base_url = _resolve_image_edit_identity(settings=normalized, client_override=client_override)
    endpoint = _automatic1111_img2img_endpoint(base_url)
    raw_extra_body = dict(edit.get('extra_body') or {}) if isinstance(edit.get('extra_body'), dict) else {}
    extra_body = _image_generation_external_extra_body(raw_extra_body)
    inputs = _collect_image_edit_inputs(image_sources or [], max_images=1)
    if not inputs:
        return {
            'ok': False,
            'artifacts': [],
            'settings': _image_generation_public_settings(normalized),
            'error': '图片编辑需要先上传或引用一张图片',
            'need_clarification': True,
            'clarification_question': '请先上传要编辑的图片，或说明要编辑哪一张最近的图片。',
        }
    width, height = _parse_image_size(str(edit.get('size') or normalized.get('size') or ''), default=_parse_image_size(normalized.get('size')))
    req = {
        'prompt': prompt_text,
        'init_images': [base64.b64encode(inputs[0]['raw']).decode('utf-8')],
        'width': int(extra_body.pop('width', width) or width),
        'height': int(extra_body.pop('height', height) or height),
    }
    for key, value in extra_body.items():
        if key in {'prompt', 'init_images'}:
            continue
        req[key] = value
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    ext = _preferred_image_generation_ext({'extra_body': extra_body})
    http_client = None
    try:
        http_client = _image_http_client()
        resp = _image_generation_http_request_with_retry(http_client, 'POST', endpoint, json=req, headers=headers, extra_body=raw_extra_body)
        payload = resp.json() if resp.content else {}
        images = payload.get('images') if isinstance(payload, dict) else None
        items = []
        if isinstance(images, list):
            for item in images:
                if isinstance(item, str) and item.strip():
                    items.append({'b64': item.strip(), 'url': ''})
        saved = _save_image_b64_items(items, ext=ext)
        return {
            'ok': bool(saved),
            'artifacts': saved,
            'settings': _image_generation_public_settings(normalized),
            'task_mode': 'edit',
            'input_image_count': len(inputs),
            'error': '' if saved else 'Automatic1111 img2img 未返回可保存的图片数据',
        }
    finally:
        _close_httpx_client_quietly(http_client)


def _generate_image_edit_artifacts(prompt_text: str, image_sources: list | None = None, *, settings: dict | None = None, client_override=None) -> dict:
    prompt_text = str(prompt_text or '').strip()
    if not prompt_text:
        return {'ok': False, 'error': '缺少改图要求', 'need_clarification': True, 'clarification_question': '你想怎么修改这张图片？'}
    normalized = _image_generation_attach_deadline(_normalize_image_generation_settings(settings), task_mode='edit')
    edit = normalized.get('edit') if isinstance(normalized.get('edit'), dict) else _normalize_image_edit_settings(normalized)
    if not bool(edit.get('enabled')):
        return {'ok': False, 'error': '图片编辑未启用', 'artifacts': []}
    engine = str(edit.get('engine') or 'openai_compatible').strip().lower()
    if engine == 'comfyui':
        return {
            'ok': False,
            'artifacts': [],
            'settings': _image_generation_public_settings(normalized),
            'error': '当前 ComfyUI 图片编辑需要单独的工作流上传与图片节点映射，本版本先保留配置入口，实际改图请先使用 OpenAI 兼容或 Automatic1111 img2img。',
        }
    if engine == 'gemini':
        return {
            'ok': False,
            'artifacts': [],
            'settings': _image_generation_public_settings(normalized),
            'error': '当前 Gemini 兼容网关仅接通生图，暂不接入改图。请先把图片编辑引擎切到 OpenAI 兼容或 Automatic1111。',
        }
    try:
        if engine == 'automatic1111':
            return _generate_image_edit_artifacts_automatic1111(prompt_text, normalized, image_sources=image_sources, client_override=client_override)
        return _generate_image_edit_artifacts_openai_compatible(prompt_text, normalized, image_sources=image_sources, client_override=client_override)
    except ImageGenerationTimeoutError:
        return _image_generation_timeout_result(task_mode='edit', image_task_type='image_edit', settings=normalized)


def _generate_image_artifacts_openai_compatible(prompt_text: str, normalized: dict, *, client_override=None) -> dict:
    api_key, base_url = _resolve_image_generation_identity(settings=normalized, client_override=client_override)
    endpoint = _openai_image_generation_endpoint(base_url)
    ext = _preferred_image_generation_ext(normalized)
    raw_extra_body = dict(normalized.get('extra_body') or {}) if isinstance(normalized.get('extra_body'), dict) else {}
    extra_body = _image_generation_external_extra_body(raw_extra_body)
    req = {
        'model': normalized['model'],
        'prompt': prompt_text,
        'n': int(extra_body.pop('n', 1) or 1),
    }
    if normalized.get('size'):
        req['size'] = normalized['size']
    for key, value in extra_body.items():
        if key in {'prompt', 'n', 'model', 'size'}:
            continue
        req[key] = value
    headers = {'Content-Type': 'application/json'}
    auth_headers = None
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
        auth_headers = {'Authorization': f'Bearer {api_key}'}
    http_client = None
    try:
        http_client = _image_http_client()
        started = time.time()
        _image_generation_log('request_start', task_mode='generate', endpoint=endpoint, model=req.get('model'), timeout_s=normalized.get('_operation_timeout_s'), size=req.get('size') or '', request_keys=sorted(req.keys()))
        resp = _image_generation_http_request_with_retry(http_client, 'POST', endpoint, json=req, headers=headers, extra_body=raw_extra_body)
        elapsed_ms = int((time.time() - started) * 1000)
        parsed = _parse_image_generation_http_response(resp, default_ext=ext)
        meta = parsed.get('meta') or {}
        _image_generation_log('response_received', task_mode='generate', endpoint=endpoint, elapsed_ms=elapsed_ms, status=meta.get('status_code'), content_type=meta.get('content_type'), body_bytes=meta.get('body_bytes'), parse_mode=meta.get('parse_mode'), payload_keys=meta.get('payload_keys'), item_count=meta.get('item_count'), item_types=meta.get('item_types'), json_error=meta.get('json_error'), body_preview=meta.get('body_preview'))
        saved = list(parsed.get('artifacts') or [])
        if not saved:
            items = list(parsed.get('items') or [])
            saved = _save_image_b64_items(items, ext=ext, auth_headers=auth_headers)
        error_text = ''
        if not saved:
            error_text = '图片接口未返回可保存的图片数据'
            if str(meta.get('json_error') or '').strip():
                error_text += f'（{meta.get("json_error")}）'
            body_preview = str(meta.get('body_preview') or '').strip()
            if body_preview:
                error_text += '\n上游响应原文：' + body_preview
        _image_generation_log('request_done', task_mode='generate', ok=bool(saved), saved_count=len(saved), filenames=[str(x.get('filename') or '') for x in saved[:8]], error=error_text)
        return {
            'ok': bool(saved),
            'artifacts': saved,
            'settings': _image_generation_public_settings(normalized),
            'error': error_text,
        }
    finally:
        _close_httpx_client_quietly(http_client)


def _generate_image_artifacts_automatic1111(prompt_text: str, normalized: dict, *, client_override=None) -> dict:
    api_key, base_url = _resolve_image_generation_identity(settings=normalized, client_override=client_override)
    endpoint = _automatic1111_txt2img_endpoint(base_url)
    raw_extra_body = dict(normalized.get('extra_body') or {}) if isinstance(normalized.get('extra_body'), dict) else {}
    extra_body = _image_generation_external_extra_body(raw_extra_body)
    width, height = _parse_image_size(normalized.get('size'))
    req = {
        'prompt': prompt_text,
        'width': int(extra_body.pop('width', width) or width),
        'height': int(extra_body.pop('height', height) or height),
    }
    for key, value in extra_body.items():
        if key in {'prompt'}:
            continue
        req[key] = value
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    ext = _preferred_image_generation_ext(normalized)
    http_client = None
    try:
        http_client = _image_http_client()
        resp = _image_generation_http_request_with_retry(http_client, 'POST', endpoint, json=req, headers=headers, extra_body=raw_extra_body)
        payload = resp.json() if resp.content else {}
        images = payload.get('images') if isinstance(payload, dict) else None
        items = []
        if isinstance(images, list):
            for item in images:
                if isinstance(item, str) and item.strip():
                    items.append({'b64': item.strip(), 'url': ''})
        saved = _save_image_b64_items(items, ext=ext)
        return {
            'ok': bool(saved),
            'artifacts': saved,
            'settings': _image_generation_public_settings(normalized),
            'error': '' if saved else 'Automatic1111 未返回可保存的图片数据',
        }
    finally:
        _close_httpx_client_quietly(http_client)



def _generate_image_artifacts_gemini(prompt_text: str, normalized: dict, *, client_override=None) -> dict:
    api_key, base_url = _resolve_image_generation_identity(settings=normalized, client_override=client_override)
    endpoint = _openai_chat_completions_endpoint(base_url)
    ext = _preferred_image_generation_ext(normalized)
    raw_extra_body = dict(normalized.get('extra_body') or {}) if isinstance(normalized.get('extra_body'), dict) else {}
    extra_body = _image_generation_external_extra_body(raw_extra_body)

    messages = extra_body.pop('messages', None)
    if not isinstance(messages, list) or not messages:
        messages = [{'role': 'user', 'content': prompt_text}]
    system_prompt = str(extra_body.pop('system_prompt', extra_body.pop('system', '')) or '').strip()
    if system_prompt and not any(str((m or {}).get('role') or '').strip().lower() == 'system' for m in messages if isinstance(m, dict)):
        messages = [{'role': 'system', 'content': system_prompt}, *messages]

    req = {
        'model': normalized['model'],
        'messages': messages,
        'stream': bool(extra_body.pop('stream', False)),
    }
    if normalized.get('size'):
        req['size'] = normalized['size']
    for key, value in extra_body.items():
        if key in {'prompt', 'n', 'model', 'size', 'messages', 'stream', 'input'}:
            continue
        req[key] = value
    headers = {'Content-Type': 'application/json'}
    auth_headers = None
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
        auth_headers = {'Authorization': f'Bearer {api_key}'}
    http_client = None
    try:
        http_client = _image_http_client()
        started = time.time()
        _image_generation_log('request_start', task_mode='generate', engine='gemini', endpoint=endpoint, model=req.get('model'), timeout_s=normalized.get('_operation_timeout_s'), size=req.get('size') or '', request_keys=sorted(req.keys()))
        resp = _image_generation_http_request_with_retry(http_client, 'POST', endpoint, json=req, headers=headers, extra_body=raw_extra_body)
        elapsed_ms = int((time.time() - started) * 1000)
        parsed = _parse_image_generation_http_response(resp, default_ext=ext)
        meta = parsed.get('meta') or {}
        _image_generation_log('response_received', task_mode='generate', engine='gemini', endpoint=endpoint, elapsed_ms=elapsed_ms, status=meta.get('status_code'), content_type=meta.get('content_type'), body_bytes=meta.get('body_bytes'), parse_mode=meta.get('parse_mode'), payload_keys=meta.get('payload_keys'), item_count=meta.get('item_count'), item_types=meta.get('item_types'), json_error=meta.get('json_error'), body_preview=meta.get('body_preview'))
        saved = list(parsed.get('artifacts') or [])
        if not saved:
            items = list(parsed.get('items') or [])
            saved = _save_image_b64_items(items, ext=ext, auth_headers=auth_headers)
        error_text = '' if saved else ('Gemini 兼容聊天接口未返回可保存的图片数据' if not str(meta.get('json_error') or '').strip() else f'Gemini 兼容聊天接口未返回可保存的图片数据（{meta.get("json_error")}）')
        _image_generation_log('request_done', task_mode='generate', engine='gemini', ok=bool(saved), saved_count=len(saved), filenames=[str(x.get('filename') or '') for x in saved[:8]], error=error_text)
        return {
            'ok': bool(saved),
            'artifacts': saved,
            'settings': _image_generation_public_settings(normalized),
            'error': error_text,
        }
    finally:
        _close_httpx_client_quietly(http_client)

def _coerce_json_dict(value):
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        raw = value.strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return None
    return None


def _replace_placeholders_in_workflow(obj, prompt_text: str, negative_prompt: str = ''):
    if isinstance(obj, dict):
        return {k: _replace_placeholders_in_workflow(v, prompt_text, negative_prompt) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_replace_placeholders_in_workflow(v, prompt_text, negative_prompt) for v in obj]
    if isinstance(obj, str):
        return obj.replace('{{prompt}}', prompt_text).replace('{prompt}', prompt_text).replace('$PROMPT', prompt_text).replace('{{negative_prompt}}', negative_prompt).replace('{negative_prompt}', negative_prompt).replace('$NEGATIVE_PROMPT', negative_prompt)
    return obj


def _apply_prompt_to_comfyui_nodes(workflow: dict, prompt_text: str, *, negative_prompt: str = '', text_node_ids=None, negative_node_ids=None) -> dict:
    wf = _replace_placeholders_in_workflow(workflow, prompt_text, negative_prompt)
    target_ids = [str(x).strip() for x in (text_node_ids or []) if str(x).strip()]
    neg_ids = [str(x).strip() for x in (negative_node_ids or []) if str(x).strip()]
    for node_id in target_ids:
        node = wf.get(node_id)
        if isinstance(node, dict) and isinstance(node.get('inputs'), dict):
            if 'text' in node['inputs']:
                node['inputs']['text'] = prompt_text
            elif 'prompt' in node['inputs']:
                node['inputs']['prompt'] = prompt_text
    for node_id in neg_ids:
        node = wf.get(node_id)
        if isinstance(node, dict) and isinstance(node.get('inputs'), dict):
            if 'text' in node['inputs']:
                node['inputs']['text'] = negative_prompt
            elif 'prompt' in node['inputs']:
                node['inputs']['prompt'] = negative_prompt
    return wf


def _comfyui_history_outputs(payload, prompt_id: str) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    entry = None
    if prompt_id and isinstance(payload.get(prompt_id), dict):
        entry = payload.get(prompt_id)
    elif isinstance(payload.get('history'), dict) and isinstance(payload['history'].get(prompt_id), dict):
        entry = payload['history'].get(prompt_id)
    elif isinstance(payload.get('outputs'), dict):
        entry = payload
    if not isinstance(entry, dict):
        return []
    outputs = entry.get('outputs') if isinstance(entry.get('outputs'), dict) else {}
    images = []
    for node in outputs.values():
        if not isinstance(node, dict):
            continue
        for item in (node.get('images') if isinstance(node.get('images'), list) else []):
            if isinstance(item, dict) and item.get('filename'):
                images.append({
                    'filename': str(item.get('filename') or '').strip(),
                    'subfolder': str(item.get('subfolder') or '').strip(),
                    'type': str(item.get('type') or 'output').strip() or 'output',
                })
    return images


def _generate_image_artifacts_comfyui(prompt_text: str, normalized: dict, *, client_override=None) -> dict:
    api_key, base_url = _resolve_image_generation_identity(settings=normalized, client_override=client_override)
    raw_extra_body = dict(normalized.get('extra_body') or {}) if isinstance(normalized.get('extra_body'), dict) else {}
    extra_body = _image_generation_external_extra_body(raw_extra_body)
    workflow = _coerce_json_dict(extra_body.get('workflow')) or _coerce_json_dict(extra_body.get('prompt')) or _coerce_json_dict(extra_body.get('workflow_api')) or _coerce_json_dict(extra_body.get('workflow_json'))
    if not isinstance(workflow, dict) or not workflow:
        return {
            'ok': False,
            'artifacts': [],
            'settings': _image_generation_public_settings(normalized),
            'error': 'ComfyUI 需要在额外参数 JSON 中提供 workflow / prompt 工作流 JSON',
        }
    text_node_ids = extra_body.get('text_node_ids') or extra_body.get('prompt_node_ids') or []
    if isinstance(text_node_ids, (str, int)):
        text_node_ids = [text_node_ids]
    negative_node_ids = extra_body.get('negative_prompt_node_ids') or []
    if isinstance(negative_node_ids, (str, int)):
        negative_node_ids = [negative_node_ids]
    negative_prompt = str(extra_body.get('negative_prompt') or '').strip()
    workflow = _apply_prompt_to_comfyui_nodes(workflow, prompt_text, negative_prompt=negative_prompt, text_node_ids=text_node_ids, negative_node_ids=negative_node_ids)
    client_id = str(extra_body.get('client_id') or uuid.uuid4()).strip()
    payload = {'prompt': workflow, 'client_id': client_id}
    if isinstance(extra_body.get('extra_data'), dict):
        payload['extra_data'] = dict(extra_body.get('extra_data') or {})
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    ext = _preferred_image_generation_ext(normalized)
    http_client = None
    try:
        http_client = _image_http_client()
        submit_resp = _image_generation_http_request_with_retry(http_client, 'POST', _comfyui_prompt_endpoint(base_url), json=payload, headers=headers, extra_body=raw_extra_body)
        submit_payload = submit_resp.json() if submit_resp.content else {}
        prompt_id = str((submit_payload or {}).get('prompt_id') or (submit_payload or {}).get('id') or '').strip()
        if not prompt_id:
            return {
                'ok': False,
                'artifacts': [],
                'settings': _image_generation_public_settings(normalized),
                'error': 'ComfyUI 未返回 prompt_id，无法拉取结果',
            }
        poll_seconds = max(5, min(300, int(extra_body.get('poll_seconds') or 90)))
        deadline = time.time() + poll_seconds
        images = []
        while time.time() < deadline:
            hist_extra_body = dict(raw_extra_body)
            hist_extra_body['retry_attempts'] = 0
            hist_resp = _image_generation_http_request_with_retry(http_client, 'GET', _comfyui_history_endpoint(base_url, prompt_id), headers=headers, extra_body=hist_extra_body)
            if hist_resp.status_code < 400:
                hist_payload = hist_resp.json() if hist_resp.content else {}
                images = _comfyui_history_outputs(hist_payload, prompt_id)
                if images:
                    break
            time.sleep(1.0)
        if not images:
            return {
                'ok': False,
                'artifacts': [],
                'settings': _image_generation_public_settings(normalized),
                'error': 'ComfyUI 在等待时间内未返回可下载图片',
            }
        items = []
        base_root = str(base_url or '').strip().rstrip('/')
        for image in images:
            query = urlencode({
                'filename': image['filename'],
                'subfolder': image['subfolder'],
                'type': image['type'],
            })
            view_url = _append_url_path(base_root, '/view') + '?' + query
            items.append({'url': view_url, 'b64': ''})
        saved = _save_image_b64_items(items, ext=ext, auth_headers={'Authorization': f'Bearer {api_key}'} if api_key else None)
        return {
            'ok': bool(saved),
            'artifacts': saved,
            'settings': _image_generation_public_settings(normalized),
            'error': '' if saved else 'ComfyUI 返回了结果，但图片下载失败',
        }
    finally:
        _close_httpx_client_quietly(http_client)


def _image_generation_candidate_settings(normalized: dict) -> list[dict]:
    base = dict(normalized or {})
    extra = dict(base.get('extra_body') or {}) if isinstance(base.get('extra_body'), dict) else {}
    fallback_raw = extra.get('fallbacks') or extra.get('fallback_providers') or extra.get('fallback_apis') or []
    for key in ('fallbacks', 'fallback_providers', 'fallback_apis'):
        extra.pop(key, None)
    base['extra_body'] = extra
    candidates = [base]
    if isinstance(fallback_raw, dict):
        fallback_raw = [fallback_raw]
    if isinstance(fallback_raw, list):
        for item in fallback_raw[:5]:
            if not isinstance(item, dict):
                continue
            merged = dict(base)
            fb_extra = dict(extra)
            raw_fb_extra = item.get('extra_body') or item.get('extra_params') or item.get('extra')
            if isinstance(raw_fb_extra, dict):
                fb_extra.update(raw_fb_extra)
            merged.update({k: v for k, v in item.items() if k not in {'extra_body', 'extra_params', 'extra'}})
            merged['extra_body'] = fb_extra
            merged = _normalize_image_generation_settings(merged)
            candidates.append(merged)
    return candidates


def _image_generation_dispatch_once(prompt_text: str, normalized: dict, *, client_override=None) -> dict:
    engine = normalized.get('engine') or IMAGE_GENERATION_DEFAULTS['engine']
    if engine == 'automatic1111':
        return _generate_image_artifacts_automatic1111(prompt_text, normalized, client_override=client_override)
    if engine == 'comfyui':
        return _generate_image_artifacts_comfyui(prompt_text, normalized, client_override=client_override)
    if engine == 'gemini':
        return _generate_image_artifacts_gemini(prompt_text, normalized, client_override=client_override)
    return _generate_image_artifacts_openai_compatible(prompt_text, normalized, client_override=client_override)



def _image_generation_exception_public_error(exc: Exception) -> tuple[str, dict]:
    raw = f'{type(exc).__name__}: {exc}'
    lowered = str(exc or '').lower()
    meta = {}
    if isinstance(exc, httpx.HTTPStatusError):
        status = 0
        body_preview = ''
        try:
            status = int(exc.response.status_code or 0)
        except Exception:
            status = 0
        try:
            body_preview = _image_generation_preview_text(exc.response.text or '', limit=1600)
        except Exception:
            body_preview = ''
        meta = {'upstream_status': status}
        if body_preview:
            meta['upstream_response'] = body_preview
            return f'{raw}\n上游状态码：{status}\n上游响应原文：{body_preview}', meta
        return f'{raw}\n上游状态码：{status}', meta
    if isinstance(exc, httpx.RemoteProtocolError) and 'server disconnected without sending a response' in lowered:
        meta = {
            'provider_response_lost': True,
            'provider_maybe_completed': True,
            'retry_suppressed': True,
        }
        return (
            raw + '（上游/中转已接收图片任务，但连接在返回图片数据前断开；本机没有收到图片 URL 或 base64。为避免同一图片任务重复扣费，本轮不会自动重试。）',
            meta,
        )
    if isinstance(exc, (httpx.TimeoutException, httpx.ReadError, httpx.ConnectError, httpx.NetworkError)):
        meta = {
            'provider_response_lost': True,
            'retry_suppressed': True,
        }
        return (
            raw + '（图片接口连接异常，本机没有收到可保存的图片数据；为避免重复扣费，本轮不会自动重试。）',
            meta,
        )
    return raw, meta

def _generate_image_artifacts(prompt_text: str, *, settings: dict | None = None, client_override=None, image_sources: list | None = None, task_mode: str = 'generate', response_model: str = '') -> dict:
    prompt_text = str(prompt_text or '').strip()
    mode = str(task_mode or 'generate').strip().lower()
    try:
        hint_sender = globals().get('_image_pullback_hint_current_async_job')
        if callable(hint_sender):
            hint_sender(prompt_text, task_mode=mode, settings=settings, image_sources=image_sources or [])
    except Exception:
        try:
            app_logger.exception('[IMAGE_PULLBACK_HINT_HOOK] failed')
        except Exception:
            pass
    if not prompt_text:
        return {'ok': False, 'error': '缺少出图主体'}
    normalized = _image_generation_attach_deadline(_normalize_image_generation_settings(settings), task_mode=mode)
    if _image_generation_should_use_responses_native(normalized, client_override=client_override):
        return _generate_image_artifacts_responses_native(
            prompt_text,
            normalized,
            client_override=client_override,
            image_sources=image_sources or [],
            task_mode=mode,
            response_model=response_model,
        )
    if mode in {'edit', 'image_edit'}:
        return _generate_image_edit_artifacts(prompt_text, image_sources=image_sources or [], settings=normalized, client_override=client_override)
    attempts = []
    for idx, candidate in enumerate(_image_generation_candidate_settings(normalized), start=1):
        try:
            result = _image_generation_dispatch_once(prompt_text, candidate, client_override=client_override)
            if bool((result or {}).get('ok')):
                if idx > 1:
                    result['fallback_used'] = True
                    result['fallback_index'] = idx - 1
                return result
            err = str((result or {}).get('error') or '图片接口未返回可保存的图片数据')
            attempts.append({'index': idx, 'engine': candidate.get('engine'), 'api_base': candidate.get('api_base'), 'model': candidate.get('model'), 'error': err})
            try:
                app_logger.warning('[image_generation] candidate_failed index=%s engine=%s base=%s model=%s err=%s', idx, candidate.get('engine'), candidate.get('api_base'), candidate.get('model'), err[:240])
            except Exception:
                pass
        except ImageGenerationTimeoutError:
            return _image_generation_timeout_result(task_mode='generate', image_task_type='text_to_image', settings=normalized)
        except Exception as e:
            err, err_meta = _image_generation_exception_public_error(e)
            attempt_row = {'index': idx, 'engine': candidate.get('engine'), 'api_base': candidate.get('api_base'), 'model': candidate.get('model'), 'error': err}
            if err_meta:
                attempt_row.update(err_meta)
            attempts.append(attempt_row)
            try:
                app_logger.exception('[image_generation] candidate_exception index=%s engine=%s base=%s model=%s response_lost=%s retry_suppressed=%s', idx, candidate.get('engine'), candidate.get('api_base'), candidate.get('model'), bool(err_meta.get('provider_response_lost') if isinstance(err_meta, dict) else False), bool(err_meta.get('retry_suppressed') if isinstance(err_meta, dict) else False))
            except Exception:
                pass
            continue
    last_attempt = attempts[-1] if attempts else {}
    last_error = last_attempt.get('error') or '图片生成失败'
    result = {
        'ok': False,
        'error': last_error,
        'attempts': attempts,
        'settings': _image_generation_public_settings(normalized),
        'artifacts': [],
    }
    if isinstance(last_attempt, dict):
        for key in ('provider_response_lost', 'provider_maybe_completed', 'retry_suppressed'):
            if key in last_attempt:
                result[key] = last_attempt.get(key)
    return result
