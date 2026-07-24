# Responses native image_generation request and result helpers.

def _extract_openai_like_items(payload) -> list[dict]:
    out = []
    seen = set()
    url_keys = ('url', 'image_url', 'imageUrl', 'download_url', 'downloadUrl', 'signed_url', 'signedUrl', 'result_url', 'resultUrl', 'view_url', 'viewUrl', 'file_url', 'fileUrl', 'href')
    b64_keys = ('b64_json', 'base64', 'image_base64', 'b64', 'image_data', 'imageBase64', 'data')

    def _add(url: str = '', b64: str = ''):
        raw_url = str(url or '').strip()
        raw_b64 = str(b64 or '').strip()
        if raw_b64.startswith('data:image/'):
            raw_b64 = _strip_data_url_prefix(raw_b64)
        if not raw_url and not raw_b64:
            return
        key = (raw_url, raw_b64[:120])
        if key in seen:
            return
        seen.add(key)
        out.append({'url': raw_url, 'b64': raw_b64})

    def _walk(node, depth: int = 0):
        if depth > 8 or node is None:
            return
        if isinstance(node, dict):
            direct_url = ''
            for key in url_keys:
                val = node.get(key)
                if isinstance(val, str) and val.strip().startswith(('http://', 'https://')):
                    direct_url = val
                    break
            direct_b64 = ''
            for key in b64_keys:
                val = node.get(key)
                if isinstance(val, str) and val.strip():
                    if key == 'data' and not val.strip().startswith('data:image/'):
                        continue
                    direct_b64 = val
                    break
            # OpenAI 兼容图片网关可能为同一张图同时返回临时 URL 和 b64_json。
            # 合并为一个候选，让现有保存器优先使用稳定的 Base64 数据，避免前端误收两张图。
            _add(url=direct_url, b64=direct_b64)
            for key in ('data', 'images', 'image', 'result', 'results', 'output', 'outputs', 'items', 'artifacts', 'content', 'response', 'message'):
                if key in node:
                    _walk(node.get(key), depth + 1)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    _walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node[:48]:
                _walk(item, depth + 1)
        elif isinstance(node, str):
            raw = node.strip()
            if raw.startswith(('http://', 'https://')):
                _add(url=raw)
            elif raw.startswith('data:image/'):
                _add(b64=raw)
            else:
                for match in re.findall(r'https?://[^\s<>()"\'`]+', raw):
                    cleaned = str(match or '').strip().rstrip('.,;)]}>')
                    if cleaned:
                        _add(url=cleaned)
                for match in re.findall(r'data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+', raw):
                    cleaned = str(match or '').strip()
                    if cleaned:
                        _add(b64=cleaned)

    _walk(payload, 0)
    return out


def _parse_image_generation_http_response(resp, *, default_ext: str = 'png') -> dict:
    content_type = str(resp.headers.get('content-type') or '').split(';', 1)[0].strip().lower()
    raw = resp.content or b''
    meta = {
        'status_code': int(getattr(resp, 'status_code', 0) or 0),
        'content_type': content_type,
        'body_bytes': len(raw),
        'content_length': str(resp.headers.get('content-length') or '').strip(),
        'parse_mode': 'empty',
        'payload_keys': [],
        'item_count': 0,
        'item_types': [],
        'body_preview': '',
        'json_error': '',
    }
    if raw and content_type.startswith('image/'):
        ext = _model_image_ext_for_mime(content_type).lstrip('.') or str(default_ext or 'png')
        saved = _save_artifacts_to_uploads([{
            'filename': _image_generation_filename(1, ext=ext),
            'mime': content_type or f'image/{ext}',
            'encoding': 'base64',
            'data': base64.b64encode(raw).decode('utf-8'),
        }])
        meta['parse_mode'] = 'binary_image'
        meta['item_count'] = len(saved)
        meta['item_types'] = ['binary_image'] if saved else []
        return {'items': [], 'artifacts': saved, 'meta': meta}

    payload = None
    if raw:
        try:
            payload = resp.json()
            meta['parse_mode'] = 'json'
        except Exception as e:
            meta['json_error'] = f'{type(e).__name__}: {e}'

    text = ''
    if payload is None and raw:
        try:
            text = resp.text or ''
        except Exception:
            text = ''
        stripped = text.strip()
        if stripped:
            meta['body_preview'] = _image_generation_preview_text(stripped, limit=900)
            if stripped[:1] in '{[':
                try:
                    payload = json.loads(stripped)
                    meta['parse_mode'] = 'json_text'
                except Exception as e:
                    meta['json_error'] = f'{type(e).__name__}: {e}'
            if payload is None and stripped.startswith(('http://', 'https://')):
                items = [{'url': stripped, 'b64': ''}]
                meta['parse_mode'] = 'plain_url'
                meta['item_count'] = 1
                meta['item_types'] = ['url']
                return {'items': items, 'artifacts': [], 'meta': meta}
            if payload is None and stripped.startswith('data:image/'):
                items = [{'url': '', 'b64': stripped}]
                meta['parse_mode'] = 'plain_data_url'
                meta['item_count'] = 1
                meta['item_types'] = ['b64']
                return {'items': items, 'artifacts': [], 'meta': meta}

    if payload is not None:
        if isinstance(payload, dict):
            meta['payload_keys'] = list(payload.keys())[:20]
        elif isinstance(payload, list):
            meta['payload_keys'] = ['<list>']
        items = _extract_openai_like_items(payload)
        meta['item_count'] = len(items)
        meta['item_types'] = _image_generation_item_types(items)
        if not meta['body_preview']:
            meta['body_preview'] = _image_generation_preview_text(payload, limit=900)
        return {'items': items, 'artifacts': [], 'meta': meta}

    return {'items': [], 'artifacts': [], 'meta': meta}



def _image_generation_responses_native_enabled(settings: dict | None = None) -> bool:
    """Use the Responses API native image_generation tool on the Responses lane.

    This keeps image generation inside the selected Responses request path instead
    of calling the standalone /images/generations endpoint. It is a transport
    selection only; user intent is still decided by the existing image planner.
    """
    data = dict(settings or {}) if isinstance(settings, dict) else {}
    extra = dict(data.get('extra_body') or {}) if isinstance(data.get('extra_body'), dict) else {}
    raw = None
    for key in ('responses_native_image_generation', 'use_responses_native_image_generation', 'native_responses_image_generation'):
        if key in extra:
            raw = extra.get(key)
            break
        if key in data:
            raw = data.get(key)
            break
    if raw is None:
        raw = app_getenv('IMAGE_GENERATION_RESPONSES_NATIVE_ENABLED', '1')
    return _truthy_config_value(raw)


def _image_generation_should_use_responses_native(normalized: dict | None = None, *, client_override=None) -> bool:
    if not _image_generation_responses_native_enabled(normalized or {}):
        return False
    try:
        endpoint_mode = _file_delivery_endpoint_mode_from_client(client_override)
    except Exception:
        endpoint_mode = str(getattr(client_override, '_webai_api_endpoint_mode', '') or '').strip().lower()
    return endpoint_mode == 'responses'


def _image_generation_responses_native_model(normalized: dict | None = None, *, response_model: str = '') -> str:
    data = dict(normalized or {}) if isinstance(normalized, dict) else {}
    extra = dict(data.get('extra_body') or {}) if isinstance(data.get('extra_body'), dict) else {}
    for key in ('responses_model', 'response_model', 'chat_model', 'main_model'):
        val = str(extra.get(key) or data.get(key) or '').strip()
        if val:
            return val
    env_model = str(app_getenv('IMAGE_GENERATION_RESPONSES_MODEL', '') or '').strip()
    if env_model:
        return env_model
    rm = str(response_model or '').strip()
    if rm:
        return rm
    model = str(data.get('model') or '').strip()
    # Standalone image models are tool backends, not the main Responses model.
    if model.lower().startswith('gpt-image'):
        return ''
    return model


def _image_generation_responses_native_tool_spec(normalized: dict | None = None, *, task_mode: str = 'generate', has_source_images: bool = False) -> dict:
    data = dict(normalized or {}) if isinstance(normalized, dict) else {}
    extra = dict(data.get('extra_body') or {}) if isinstance(data.get('extra_body'), dict) else {}
    tool = {'type': 'image_generation'}
    image_model = str(data.get('model') or '').strip()
    if image_model and image_model.lower().startswith('gpt-image'):
        tool['model'] = image_model
    size = str(data.get('size') or '').strip()
    if size:
        tool['size'] = size
    passthrough_keys = {
        'quality', 'output_format', 'format', 'compression', 'background',
        'moderation', 'partial_images'
    }
    for key in passthrough_keys:
        if key in extra and extra.get(key) not in (None, ''):
            out_key = 'output_format' if key == 'format' else key
            tool[out_key] = extra.get(key)
    # Responses image_generation is an in-Responses native tool.  Do not send
    # input_fidelity by default or from extra_body here; some providers reject the
    # entire tool schema before generation starts.
    if 'action' in extra and str(extra.get('action') or '').strip():
        tool['action'] = str(extra.get('action') or '').strip()
    else:
        mode = str(task_mode or '').strip().lower()
        if mode in {'edit', 'image_edit', 'reference_edit', 'variation'}:
            tool['action'] = 'edit'
        elif mode in {'reference_generate'}:
            tool['action'] = 'generate'
        elif mode in {'generate', 'text_to_image'}:
            tool['action'] = 'auto' if has_source_images else 'generate'
    return tool


def _image_generation_responses_native_image_content_item(source: str) -> dict | None:
    u = str(source or '').strip()
    if not u:
        return None
    # For local uploads/generated files, a public URL may not be reachable by the
    # upstream Responses provider. Prefer a model-safe data URL whenever the
    # project already knows how to normalize the source; fall back to remote URLs.
    data_url = ''
    try:
        normalizer = globals().get('_normalize_image_input_to_data_url')
        if callable(normalizer):
            data_url = str(normalizer(u) or '').strip()
    except Exception:
        data_url = ''
    if data_url.startswith('data:image/'):
        return {'type': 'input_image', 'image_url': data_url, 'detail': 'high'}
    if u.startswith('data:image/'):
        return {'type': 'input_image', 'image_url': u, 'detail': 'high'}
    if u.startswith(('http://', 'https://')):
        return {'type': 'input_image', 'image_url': u, 'detail': 'auto'}
    return None


def _image_generation_responses_native_input(prompt_text: str, image_sources: list | None = None, *, task_mode: str = 'generate') -> list[dict] | str:
    prompt = str(prompt_text or '').strip()
    sources = [str(u or '').strip() for u in (image_sources or []) if str(u or '').strip()]
    if not sources:
        return prompt
    mode = str(task_mode or '').strip().lower()
    action_hint = '请基于下面输入图片完成图片编辑/参考图生成。' if mode in {'edit', 'image_edit', 'reference_edit', 'variation'} else '请把下面输入图片作为参考视觉上下文生成新图，不要把参考图当成普通聊天配图。'
    content = [{'type': 'input_text', 'text': (action_hint + '\n' + prompt).strip()}]
    for u in sources[:4]:
        item = _image_generation_responses_native_image_content_item(u)
        if item:
            content.append(item)
    return [{'role': 'user', 'content': content}]


def _image_generation_responses_native_extract_items(payload) -> tuple[list[dict], dict]:
    if payload is None:
        return [], {'image_call_count': 0, 'item_types': []}
    if not isinstance(payload, dict):
        try:
            payload = payload.model_dump()
        except Exception:
            try:
                payload = dict(payload)
            except Exception:
                payload = {}
    calls = []
    seen = set()
    revised_prompts = []

    def add_item(url: str = '', b64: str = ''):
        raw_url = str(url or '').strip()
        raw_b64 = str(b64 or '').strip()
        if raw_b64.startswith('data:image/'):
            raw_b64 = _strip_data_url_prefix(raw_b64)
        if not raw_url and not raw_b64:
            return
        key = (raw_url, raw_b64[:120])
        if key in seen:
            return
        seen.add(key)
        calls.append({'url': raw_url, 'b64': raw_b64})

    def walk(node, depth: int = 0):
        if depth > 8 or node is None:
            return
        if isinstance(node, dict):
            typ = str(node.get('type') or '').strip().lower()
            # Streaming-compatible gateways may expose only the progressive
            # Responses image event shape.  Keep the latest partial image as a
            # valid fallback so native /responses image generation can still be
            # saved and rendered when the final result field is missing.
            partial_b64 = str(node.get('partial_image_b64') or node.get('partial_image') or '').strip()
            if partial_b64:
                add_item(b64=partial_b64)
            if typ == 'image_generation_call' or 'image_generation_call' in typ:
                rp = str(node.get('revised_prompt') or '').strip()
                if rp:
                    revised_prompts.append(rp)
                result = node.get('result')
                if isinstance(result, str) and result.strip():
                    add_item(b64=result)
                elif isinstance(result, dict):
                    add_item(
                        url=str(result.get('url') or result.get('image_url') or result.get('download_url') or '').strip(),
                        b64=str(result.get('b64_json') or result.get('base64') or result.get('image_base64') or result.get('data') or '').strip(),
                    )
                elif isinstance(result, list):
                    for it in result[:8]:
                        if isinstance(it, str):
                            add_item(b64=it)
                        elif isinstance(it, dict):
                            add_item(
                                url=str(it.get('url') or it.get('image_url') or it.get('download_url') or '').strip(),
                                b64=str(it.get('b64_json') or it.get('base64') or it.get('image_base64') or it.get('data') or '').strip(),
                            )
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node[:80]:
                walk(item, depth + 1)

    walk(payload, 0)
    if not calls:
        # Some compatible gateways wrap images in OpenAI-like data/images fields.
        calls = _extract_openai_like_items(payload)
    item_types = _image_generation_item_types(calls)
    return calls, {
        'image_call_count': len(calls),
        'item_types': item_types,
        'revised_prompt': revised_prompts[0] if revised_prompts else '',
    }


def _generate_image_artifacts_responses_native(prompt_text: str, normalized: dict, *, client_override=None, image_sources: list | None = None, task_mode: str = 'generate', response_model: str = '') -> dict:
    api_key, base_url = _resolve_openai_client_identity(client_override)
    endpoint = _file_delivery_responses_endpoint_from_base_url(base_url)
    model = _image_generation_responses_native_model(normalized, response_model=response_model)
    if not endpoint:
        return {
            'ok': False,
            'artifacts': [],
            'settings': _image_generation_public_settings(normalized),
            'error': 'Responses API endpoint missing，无法使用内置 image_generation 工具',
            'task_mode': str(task_mode or 'generate'),
            'transport': 'responses_native_image_generation',
        }
    if not model:
        return {
            'ok': False,
            'artifacts': [],
            'settings': _image_generation_public_settings(normalized),
            'error': 'Responses 内置生图需要主聊天模型；当前只拿到图片模型名，无法发起 /responses 请求',
            'task_mode': str(task_mode or 'generate'),
            'transport': 'responses_native_image_generation',
        }
    raw_extra_body = dict(normalized.get('extra_body') or {}) if isinstance(normalized.get('extra_body'), dict) else {}
    tool = _image_generation_responses_native_tool_spec(normalized, task_mode=task_mode, has_source_images=bool(image_sources))
    body = {
        'model': model,
        'input': _image_generation_responses_native_input(prompt_text, image_sources or [], task_mode=task_mode),
        'tools': [tool],
        'tool_choice': {'type': 'image_generation'},
    }
    # Allow explicit body-level overrides without leaking internal timeout keys.
    body_extra = raw_extra_body.get('responses_body_extra') if isinstance(raw_extra_body.get('responses_body_extra'), dict) else {}
    for key, value in body_extra.items():
        k = str(key or '').strip()
        if k and k not in {'model', 'input', 'tools', 'tool_choice'} and not k.startswith('_'):
            body[k] = value
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    http_client = globals().get('HTTPX_GPT_FILE') or globals().get('HTTPX_GPT')
    own_client = None
    ext = _preferred_image_generation_ext(normalized)
    try:
        if http_client is None:
            own_client = httpx.Client(verify=globals().get('tls_verify', True), timeout=_image_generation_timeout_httpx_timeout(raw_extra_body), follow_redirects=True)
            http_client = own_client
        started = time.time()
        _image_generation_log('request_start', task_mode=task_mode, transport='responses_native_image_generation', endpoint=endpoint, model=model, image_tool_model=tool.get('model') or '', timeout_s=normalized.get('_operation_timeout_s'), source_image_count=len(image_sources or []), request_keys=sorted(body.keys()), tool_keys=sorted(tool.keys()))
        resp = _image_generation_http_request_with_retry(http_client, 'POST', endpoint, json=body, headers=headers, extra_body=raw_extra_body)
        elapsed_ms = int((time.time() - started) * 1000)
        try:
            payload = resp.json() if getattr(resp, 'content', b'') else {}
        except Exception as e:
            payload = {}
            json_error = f'{type(e).__name__}: {e}'
        else:
            json_error = ''
        items, meta = _image_generation_responses_native_extract_items(payload)
        saved = _save_image_b64_items(items, ext=ext, auth_headers={'Authorization': f'Bearer {api_key}'} if api_key else None)
        body_preview = _image_generation_preview_text(payload, limit=1200)
        error_text = ''
        if not saved:
            error_text = 'Responses 内置 image_generation 没有返回可保存的图片数据'
            if json_error:
                error_text += f'（{json_error}）'
            if body_preview:
                error_text += '\n上游响应原文：' + body_preview
        _image_generation_log('response_received', task_mode=task_mode, transport='responses_native_image_generation', elapsed_ms=elapsed_ms, status=int(getattr(resp, 'status_code', 0) or 0), saved_count=len(saved), item_count=len(items), item_types=meta.get('item_types'), revised_prompt=meta.get('revised_prompt') or '', error=error_text, payload_preview=body_preview if not saved else '')
        out = {
            'ok': bool(saved),
            'artifacts': saved,
            'settings': _image_generation_public_settings(normalized),
            'error': error_text,
            'transport': 'responses_native_image_generation',
            'task_mode': str(task_mode or 'generate'),
        }
        if meta.get('revised_prompt'):
            out['revised_prompt'] = str(meta.get('revised_prompt') or '')
        return out
    except ImageGenerationTimeoutError:
        result = _image_generation_timeout_result(task_mode=task_mode or 'generate', image_task_type='image_edit' if str(task_mode or '').lower() == 'edit' else 'text_to_image', settings=normalized)
        result['transport'] = 'responses_native_image_generation'
        return result
    except Exception as e:
        err, err_meta = _image_generation_exception_public_error(e)
        out = {
            'ok': False,
            'artifacts': [],
            'settings': _image_generation_public_settings(normalized),
            'error': err,
            'transport': 'responses_native_image_generation',
            'task_mode': str(task_mode or 'generate'),
        }
        out.update(err_meta or {})
        return out
    finally:
        _close_httpx_client_quietly(own_client)

def _save_image_b64_items(items: list[dict], *, ext: str, auth_headers: dict | None = None) -> list[dict]:
    local_artifacts = []
    ready_artifacts = []
    current_scope = _image_generation_current_output_scope()
    sync_provider_mirror = _image_generation_should_sync_provider_mirror(current_scope)
    mirror_timeout = _image_generation_download_timeout_for_mirror()
    for idx, item in enumerate(items or [], start=1):
        b64 = _strip_data_url_prefix(item.get('b64') if isinstance(item, dict) else '')
        url = str(item.get('url') if isinstance(item, dict) else '').strip()
        if b64:
            local_artifacts.append({
                'filename': _image_generation_filename(idx, ext=ext),
                'mime': f'image/{ext}',
                'encoding': 'base64',
                'data': b64,
            })
            _image_generation_log('item_ready', index=idx, source='b64', bytes=len(str(b64 or '')), filename=local_artifacts[-1]['filename'])
            continue
        if url:
            passthrough = _image_generation_provider_url_artifact(url, index=idx, ext=ext, scope=current_scope)
            if sync_provider_mirror:
                filename = str(passthrough.get('filename') or '').strip() or _image_generation_filename_from_url(url, index=idx, ext=ext)
                mime_hint = str(passthrough.get('mime') or '').strip()
                saved = _image_generation_stream_provider_url_to_scope(
                    url,
                    filename=filename,
                    mime_hint=mime_hint,
                    scope=current_scope,
                    timeout=mirror_timeout,
                    headers=None,
                )
                if (not bool(saved.get('ok'))) and isinstance(auth_headers, dict) and auth_headers and not _image_generation_url_looks_signed(url):
                    saved = _image_generation_stream_provider_url_to_scope(
                        url,
                        filename=filename,
                        mime_hint=mime_hint,
                        scope=current_scope,
                        timeout=mirror_timeout,
                        headers=auth_headers,
                    )
                if bool(saved.get('ok')):
                    saved.setdefault('created_at_ms', passthrough.get('created_at_ms') or int(time.time() * 1000))
                    saved.setdefault('provider_url', url)
                    saved.setdefault('delivery_mode', 'server_mirrored')
                    saved.setdefault('source_role', 'assistant')
                    saved.setdefault('operation', 'generate')
                    saved.setdefault('image_seq', idx)
                    _image_generation_provider_mirror_remember(url, saved)
                    ready_artifacts.append(saved)
                    _image_generation_log('item_ready', index=idx, source='provider_url_mirrored', url=url, filename=str(saved.get('filename') or ''), preview_url=str(saved.get('preview_url') or ''), scope=current_scope)
                    continue
                passthrough['mirror_status'] = 'download_failed'
                passthrough['mirror_error'] = str(saved.get('error') or 'download_failed')
                passthrough['mirror_http_status'] = int(saved.get('status_code') or 0)
                _image_generation_log('item_ready', index=idx, source='provider_url_fallback_after_mirror_fail', url=url, filename=str(passthrough.get('filename') or ''), error=passthrough['mirror_error'], scope=current_scope)
            ready_artifacts.append(passthrough)
            _image_generation_log('item_ready', index=idx, source='provider_url', url=url, filename=str(passthrough.get('filename') or ''), preview_url=str(passthrough.get('preview_url') or ''), scope=current_scope)
            _mirror_provider_image_artifact_async(passthrough, auth_headers=auth_headers)
    saved_local = _save_artifacts_to_uploads(local_artifacts) if local_artifacts else []
    out = [*(ready_artifacts or []), *(saved_local or [])]
    _image_generation_log('artifacts_saved', candidate_count=len(local_artifacts) + len(ready_artifacts), saved_count=len(out), filenames=[str(x.get('filename') or '') for x in out[:8]])
    return out
