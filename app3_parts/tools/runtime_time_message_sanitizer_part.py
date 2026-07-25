# runtime time hints and model message sanitization.

def _normalize_runtime_time_payload(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    out = {}
    try:
        epoch_ms = int(float(value.get('epoch_ms') or value.get('epochMs') or 0))
    except Exception:
        epoch_ms = 0
    if epoch_ms > 0:
        out['epoch_ms'] = epoch_ms
    tz_name = str(value.get('timezone') or value.get('time_zone') or '').strip()[:80]
    if tz_name:
        out['timezone'] = tz_name
    try:
        offset_minutes = int(float(value.get('offset_minutes') or value.get('offsetMinutes') or 0))
        out['offset_minutes'] = offset_minutes
    except Exception:
        pass
    locale = str(value.get('locale') or '').strip()[:32]
    if locale:
        out['locale'] = locale
    source = str(value.get('source') or '').strip()[:32]
    if source:
        out['source'] = source
    if not out.get('epoch_ms'):
        return None
    return out


def _runtime_time_offset_label(offset_minutes: int | None = None) -> str:
    try:
        total = int(offset_minutes or 0)
    except Exception:
        total = 0
    sign = '+' if total >= 0 else '-'
    total = abs(total)
    hours, minutes = divmod(total, 60)
    return f'UTC{sign}{hours:02d}:{minutes:02d}'


def _build_runtime_time_hint(user_time: dict | None = None) -> str:
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    normalized = _normalize_runtime_time_payload(user_time)
    if normalized and normalized.get('epoch_ms'):
        try:
            utc_dt = datetime.datetime.fromtimestamp(float(normalized['epoch_ms']) / 1000.0, tz=datetime.timezone.utc)
        except Exception:
            utc_dt = now_utc
        tz_name = str(normalized.get('timezone') or '').strip()
        offset_minutes = normalized.get('offset_minutes')
        local_dt = utc_dt
        offset_text = ''
        if isinstance(offset_minutes, int):
            try:
                local_tz = datetime.timezone(datetime.timedelta(minutes=int(offset_minutes)))
                local_dt = utc_dt.astimezone(local_tz)
                offset_text = _runtime_time_offset_label(int(offset_minutes))
            except Exception:
                offset_text = ''
        parts = [f'用户本地={local_dt.strftime("%Y-%m-%d %H:%M:%S")}']
        if offset_text:
            parts.append(offset_text)
        if tz_name:
            parts.append(f'timezone={tz_name}')
        parts.append(f'UTC={now_utc.strftime("%Y-%m-%d %H:%M:%S")}')
        return '时间锚点：' + '，'.join(parts) + '；相对时间按此理解，不代表外部实时事实。'
    return f'时间锚点：UTC={now_utc.strftime("%Y-%m-%d %H:%M:%S")}；未收到前端本地时间。'


def _inject_runtime_time_context(messages: list, user_time: dict | None = None) -> list:
    out = list(messages or [])
    sys_msg = {'role': 'system', '_kind': 'runtime_time', 'content': _build_runtime_time_hint(user_time)}
    insert_at = 0
    for i, m in enumerate(out):
        if isinstance(m, dict) and m.get('role') == 'system':
            insert_at = i + 1
            if m.get('_kind') == 'runtime_time':
                out[i] = sys_msg
                return out
    out.insert(insert_at, sys_msg)
    return out


def _sanitize_messages_for_model(
    messages: list,
    allow_images: bool = True,
    *,
    preserve_internal_kind: bool = False,
) -> list:
    """Ensure messages content matches API requirements.
    - attachment marker dicts are stringified earlier by frontend
    - multimodal content list: keep only text + valid image_url
    - all image inputs are normalized into stable data URLs before sending to the model
    - when allow_images=False, strip image parts but keep the surrounding text context
    """
    try:
        deduper = globals().get('_orch_dedupe_model_messages')
        if callable(deduper):
            messages = deduper(messages or [])
    except Exception:
        pass
    out = []
    normalized_image_cache: dict[str, str | None] = {}

    def _normalize_once(candidate: str) -> str | None:
        u = str(candidate or '').strip()
        if not u or u.startswith('local://'):
            return None
        if u in normalized_image_cache:
            return normalized_image_cache[u]
        data_url = None
        if u.startswith('upload://'):
            try:
                raw, mime = _read_upload_storage_ref_bytes(u)
                if raw:
                    raw, mime = _coerce_image_bytes_for_model(raw, mime or UPLOAD_IMAGE_MIME_BY_EXT.get(_ext_of(_parse_upload_storage_ref(u)[1]), '') or 'application/octet-stream')
                    data_url = f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
            except Exception:
                data_url = None
        else:
            try:
                data_url = _normalize_image_input_to_data_url(u)
            except Exception:
                data_url = None
        if data_url:
            low = str(data_url).lower()
            if not low.startswith('data:image/'):
                data_url = None
            elif low.startswith('data:image/webp'):
                try:
                    header, b64 = data_url.split('base64,', 1)
                    mime = header.split(';', 1)[0].replace('data:', '').strip() or 'application/octet-stream'
                    raw = base64.b64decode((b64 or '').strip(), validate=False)
                    raw, mime = _coerce_image_bytes_for_model(raw, mime)
                    data_url = f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii')
                except Exception:
                    data_url = None
        normalized_image_cache[u] = data_url
        return data_url

    for m in (messages or []):
        if not isinstance(m, dict):
            continue
        if m.get("role") == "system" and m.get("_kind") == "__meta__":
            continue
        role = str(m.get("role") or '').strip()
        if not role:
            continue
        quote_text = _message_quote_text(m) if role == "user" else ""
        mm = {"role": role}
        # Responses 会在生成 API payload 前依据 `_kind` 分流稳定指令与动态上下文。
        # 仅该内部预处理显式保留，默认仍避免把内部字段发给 Chat Completions。
        if preserve_internal_kind:
            internal_kind = str(m.get("_kind") or "").strip()
            if internal_kind:
                mm["_kind"] = internal_kind
        if isinstance(m.get("content"), (str, list)):
            mm["content"] = m.get("content")
        elif "content" in m:
            mm["content"] = _structured_content_to_model_text(m.get("content"))
        if isinstance(mm.get("content"), str) and quote_text:
            mm["content"] = _combine_message_text_and_quote(mm.get("content"), quote_text)
        if isinstance(m.get("name"), str) and m.get("name"):
            mm["name"] = m.get("name")
        if isinstance(m.get("tool_call_id"), str) and m.get("tool_call_id"):
            mm["tool_call_id"] = m.get("tool_call_id")
        if isinstance(m.get("tool_calls"), list) and m.get("tool_calls"):
            mm["tool_calls"] = m.get("tool_calls")
        if isinstance(m.get("function_call"), dict) and m.get("function_call"):
            mm["function_call"] = m.get("function_call")
        c = mm.get("content")
        if isinstance(c, list):
            cleaned = []
            dropped_image_count = 0
            kept_image_count = 0
            image_text_hints: list[str] = []
            screenshot_like_count = 0
            for idx, it in enumerate(c, 1):
                if not isinstance(it, dict):
                    continue
                t = it.get("type")
                if t == "text":
                    txt = it.get("text")
                    if isinstance(txt, str) and txt.strip():
                        cleaned.append({"type": "text", "text": txt})
                elif t == "image_url":
                    data_url = None
                    if allow_images:
                        for candidate in _image_item_model_candidates(it):
                            if not isinstance(candidate, str) or not candidate.strip():
                                continue
                            data_url = _normalize_once(candidate)
                            if data_url:
                                break
                        if data_url:
                            cleaned.append({"type": "image_url", "image_url": {"url": data_url}})
                            kept_image_count += 1
                        else:
                            dropped_image_count += 1
                    else:
                        dropped_image_count += 1
                    hint, screenshot_like = _build_image_text_hint_for_model(it, idx=idx, allow_images=bool(data_url) and allow_images, data_url=data_url or '')
                    if screenshot_like:
                        screenshot_like_count += 1
                    if hint:
                        image_text_hints.append(hint)
                elif t == "input_image":
                    image_url = str(it.get("image_url") or it.get("url") or '').strip()
                    file_id = str(it.get("file_id") or '').strip()
                    data_url = None
                    if allow_images and image_url:
                        data_url = _normalize_once(image_url)
                        if data_url:
                            cleaned.append({"type": "image_url", "image_url": {"url": data_url}})
                            kept_image_count += 1
                        else:
                            dropped_image_count += 1
                    elif allow_images and file_id:
                        detail = str(it.get("detail") or "auto").strip() or "auto"
                        cleaned.append({"type": "input_image", "file_id": file_id, "detail": detail})
                        kept_image_count += 1
                    else:
                        dropped_image_count += 1
            prefix_blocks = []
            if role == "user" and quote_text:
                has_text_part = bool(cleaned or image_text_hints)
                prefix_text = (
                    "引用内容：\n" + quote_text + "\n\n当前用户消息：\n"
                    if has_text_part else
                    "引用内容：\n" + quote_text + "\n\n请结合这段引用理解用户随后给出的图片或请求。"
                )
                prefix_blocks.append({
                    "type": "text",
                    "text": prefix_text
                })
            if role == "user" and screenshot_like_count:
                prefix_blocks.append({
                    "type": "text",
                    "text": _chat_screenshot_guard_prompt()
                })
            if image_text_hints and (not allow_images or kept_image_count <= 0):
                prefix_blocks.append({
                    "type": "text",
                    "text": "以下是用户本轮图片里已解析到的文字，可与图片内容一起理解：\n\n" + "\n\n".join(image_text_hints[:4])
                })
            if prefix_blocks:
                cleaned = prefix_blocks + cleaned
            if dropped_image_count:
                note = (
                    "本轮图片输入已临时跳过，请仅基于可见文字继续回答。"
                    if not allow_images else
                    ("部分图片暂时无法读取，已自动跳过，不要把这当成用户错误。" if kept_image_count > 0 else "本轮图片暂时无法读取，请先基于现有文字继续回答；如果问题必须依赖看图，再简短提示用户重发图片。")
                )
                cleaned.append({
                    "type": "text",
                    "text": note
                })
            mm["content"] = cleaned if cleaned else ""
        out.append(mm)
    try:
        deduper = globals().get('_orch_dedupe_model_messages')
        if callable(deduper):
            out = deduper(out)
    except Exception:
        pass
    return out
