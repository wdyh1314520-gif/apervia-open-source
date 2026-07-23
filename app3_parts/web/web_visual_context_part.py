# Split from app3_parts/web/web_search_enrichment_part.py.
# Purpose: reply image attachment, visual text hinting, context image collection, and explicit image references.
# Loaded by web_search_enrichment_part.py via _exec_split_file(...), sharing the original global namespace.

# ====== 联网能力（对齐 app.py：搜索 + 天气 + URL 抓取注入）=====



# ====== Reply image attachment (safe, backend-only enhancement) ======
_IMAGE_ATTACH_HINTS = [
    # 这里只保留“明确要图”的表达，避免后端替模型做太多判断
    "图片", "配图", "看图", "看看图", "来张图", "发图", "附图", "照片",
    "截图", "示意图", "效果图", "样例图", "示例图", "产品图",
    "show me", "image", "images", "picture", "pictures", "photo", "photos",
    "screenshot", "screenshots",
]

def _latest_user_text_from_messages(messages: list) -> str:
    try:
        chunks: list[str] = []
        seen_user = False
        for m in reversed(messages or []):
            if not isinstance(m, dict):
                continue
            if m.get("role") != "user":
                if seen_user:
                    break
                continue
            seen_user = True
            piece = _combine_message_text_and_quote(_msg_content_text(m.get("content")), _message_quote_text(m)).strip()
            if piece:
                chunks.append(piece)
        if chunks:
            return "\n".join(reversed(chunks)).strip()
    except Exception:
        pass
    return ""

def _latest_user_message_has_images(messages: list) -> bool:
    try:
        seen_user = False
        for m in reversed(messages or []):
            if not isinstance(m, dict):
                continue
            if m.get("role") != "user":
                if seen_user:
                    break
                continue
            seen_user = True
            if _extract_image_urls_from_content(m.get("content")):
                return True
        return False
    except Exception:
        pass
    return False

def _should_attach_images_to_reply(user_text: str) -> bool:
    t = str(user_text or "").strip().lower()
    if not t:
        return False
    return any(k in t for k in _IMAGE_ATTACH_HINTS)

def _image_search_query_from_user_text(user_text: str) -> str:
    q = str(user_text or "").strip()
    if not q:
        return ""
    q = re.sub(r"https?://\S+", " ", q)
    q = re.sub(r"[“”\"'`]+", " ", q)
    q = re.sub(r"(给我|帮我|请|麻烦|能不能|可以|想|我想|我想看|看看|看一下|看下|展示一下|展示|有吗|有没有|来点|附上|发我|发几张)", " ", q)
    q = re.sub(r"(图片|配图|截图|示意图|效果图|样例图|示例图|产品图|照片|photo|photos|image|images|screenshot|screenshots)", " ", q, flags=re.I)
    q = re.sub(r"\s+", " ", q).strip(" ，,。:：;；")
    if not q:
        q = str(user_text or "").strip()
    return q[:120]

def _extract_requested_image_count(user_text: str, default: int = 5) -> int:
    t = str(user_text or '').strip()
    if not t:
        return max(1, min(int(default or 5), 10))
    try:
        m = re.search(r'(?<!\d)([1-9]|10)\s*(?:张|个|幅|组)?', t)
        if m:
            return max(1, min(int(m.group(1)), 10))
    except Exception:
        pass
    cn_map = {
        '一': 1, '两': 2, '二': 2, '俩': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    }
    for k, v in cn_map.items():
        if re.search(rf'{k}\s*(?:张|个|幅|组)', t):
            return v
    rich_hint_patterns = [
        r'多来点(?:图|图片|照片)', r'多放点(?:图|图片|照片)', r'多给点(?:图|图片|照片)',
        r'尽量多[一点些]?', r'越多越好', r'图多一点', r'图片多一点', r'来一组', r'图集'
    ]
    if any(re.search(p, t) for p in rich_hint_patterns):
        return 8
    if '几张' in t or '几幅' in t or '几组' in t or '一些' in t or '来点' in t:
        return max(1, min(int(default or 5), 10))
    return max(1, min(int(default or 5), 10))


def _clean_image_subject(user_text: str) -> str:
    q = str(user_text or '').strip()
    if not q:
        return ''
    q = re.sub(r'https?://\S+', ' ', q)
    q = re.sub(r"[“”\"'`]+", ' ', q)
    q = re.sub(r'(给我|帮我|请|麻烦|能不能|可以|想|我想|我想看|看看|看一下|看下|展示一下|展示|有吗|有没有|来点|附上|发我|发几张|来几张|来点|找几张|搜几张)', ' ', q)
    q = re.sub(r'(?<!\d)([1-9]|10)\s*(张|个|幅|组)?', ' ', q)
    q = re.sub(r'(一|两|二|俩|三|四|五|六|七|八|九|十)\s*(张|个|幅|组)', ' ', q)
    q = re.sub(r'(几张|几个|几幅|几组|一些|一组)', ' ', q)
    q = re.sub(r'(plain\s*links?|markdown\s*列表|markdown|链接|直链|时间戳|来源时间戳|格式)', ' ', q, flags=re.I)
    q = re.sub(r'(图片|配图|截图|示意图|效果图|样例图|示例图|产品图|照片|相片|photo|photos|image|images|screenshot|screenshots)', ' ', q, flags=re.I)
    q = re.sub(r'(给我发|发我|发|来|找|搜|看看|看一下|看下)$', ' ', q)
    q = re.sub(r'\s+', ' ', q).strip(' ，,。:：;；')
    return q[:120]

def _normalize_image_subject(subject: str) -> str:
    s = str(subject or '').strip()
    if not s:
        return ''
    s = re.sub(r'https?://\S+', ' ', s)
    s = re.sub(r"[“”\"'`]+", ' ', s)
    s = re.sub(r'(给我|帮我|请|麻烦|能不能|可以|想|我想|我想看|看看|看一下|看下|展示一下|展示|有吗|有没有|来点|附上|发我|发几张|来几张|找几张|搜几张)', ' ', s)
    s = re.sub(r'(图片|配图|截图|示意图|效果图|样例图|示例图|产品图|照片|相片|photo|photos|image|images|screenshot|screenshots)', ' ', s, flags=re.I)
    s = re.sub(r'\s+', ' ', s).strip(' ，,。:：;；')
    s = re.sub(r'[的地得]\s*$', '', s)
    return s[:120]



def _image_reply_content_to_image_url_parts(content) -> list[dict]:
    """Convert a structured assistant image_reply into lightweight image_url parts.

    The frontend stores generated image replies as structured objects so normal
    chat-model sanitization can keep them textual, while the visual/image planner
    can still index the generated image on later turns.
    """
    obj = content if isinstance(content, dict) else {}
    if str(obj.get('_kind') or '').strip() != 'image_reply':
        return []
    parent_created = obj.get('created_at_ms') or obj.get('createdAtMs') or obj.get('created_at') or obj.get('createdAt') or obj.get('ts')
    parent_seq = obj.get('image_seq') or obj.get('seq')
    parent_operation = str(obj.get('operation') or obj.get('task_mode') or obj.get('image_task_type') or 'generate').strip() or 'generate'
    parent_endpoint_mode = _visual_endpoint_mode_from_obj(obj)
    parent_message_id = str(obj.get('message_id') or obj.get('messageId') or obj.get('assistant_message_id') or '').strip()
    out: list[dict] = []
    for idx, item in enumerate(obj.get('images') or [], 1):
        if not isinstance(item, dict):
            continue
        candidates = [
            item.get('model_storage_ref'),
            item.get('storage_ref'),
            item.get('raw_url'), item.get('rawUrl'),
            item.get('view_url'), item.get('viewUrl'),
            item.get('download_url'), item.get('downloadUrl'),
            item.get('preview_url'), item.get('previewUrl'),
            item.get('url'), item.get('src'),
        ]
        url = ''
        for candidate in candidates:
            value = str(candidate or '').strip()
            if value:
                url = value
                break
        if not url:
            continue
        filename = str(item.get('filename') or item.get('name') or f'generated_image_{idx}.png').strip()
        alt = str(item.get('alt') or item.get('caption') or obj.get('subject') or filename or '生成图片').strip()
        created_at_ms = item.get('created_at_ms') or item.get('createdAtMs') or item.get('created_at') or item.get('createdAt') or parent_created
        image_seq = item.get('image_seq') or item.get('seq') or parent_seq or idx
        endpoint_mode = _visual_endpoint_mode_from_obj(item) or parent_endpoint_mode
        item_id = str(item.get('image_id') or item.get('imageId') or item.get('attachment_id') or item.get('id') or f'generated_{idx}_{abs(hash(url))}').strip()
        parent_image_id = str(item.get('parent_image_id') or item.get('parentImageId') or obj.get('parent_image_id') or obj.get('parentImageId') or '').strip()
        raw_source_ids = (
            item.get('source_image_ids') or item.get('sourceImageIds') or item.get('derived_from') or item.get('derivedFrom')
            or obj.get('source_image_ids') or obj.get('sourceImageIds') or obj.get('derived_from') or obj.get('derivedFrom')
            or []
        )
        if isinstance(raw_source_ids, str):
            source_image_ids = [raw_source_ids]
        elif isinstance(raw_source_ids, (list, tuple, set)):
            source_image_ids = [str(x or '').strip() for x in raw_source_ids]
        else:
            source_image_ids = []
        source_image_ids = [x for x in source_image_ids if x]
        if parent_image_id and parent_image_id not in source_image_ids:
            source_image_ids.insert(0, parent_image_id)
        source_image_ids = source_image_ids[:8]
        item_registry = item.get('file_registry') if isinstance(item.get('file_registry'), dict) else {}
        out.append({
            'type': 'image_url',
            'image_url': {'url': url},
            'url': url,
            'raw_url': str(item.get('raw_url') or item.get('rawUrl') or url).strip(),
            'view_url': str(item.get('view_url') or item.get('viewUrl') or url).strip(),
            'download_url': str(item.get('download_url') or item.get('downloadUrl') or '').strip(),
            'preview_url': str(item.get('preview_url') or item.get('previewUrl') or '').strip(),
            'storage_ref': str(item.get('storage_ref') or item.get('model_storage_ref') or item_registry.get('storage_ref') or item_registry.get('model_storage_ref') or '').strip(),
            'model_storage_ref': str(item.get('model_storage_ref') or item.get('storage_ref') or item_registry.get('model_storage_ref') or item_registry.get('storage_ref') or '').strip(),
            'file_library_id': str(item.get('file_library_id') or item.get('library_file_id') or item_registry.get('file_id') or '').strip(),
            'library_file_id': str(item.get('library_file_id') or item.get('file_library_id') or item_registry.get('file_id') or '').strip(),
            'file_registry': item_registry or None,
            'persisted_url': str(item.get('persisted_url') or item.get('persistedUrl') or '').strip(),
            'server_url': str(item.get('server_url') or item.get('serverUrl') or '').strip(),
            '_source_url': str(item.get('_source_url') or item.get('source_url') or item.get('sourceUrl') or '').strip(),
            '_preview_url': str(item.get('_preview_url') or item.get('preview_url') or item.get('previewUrl') or '').strip(),
            'filename': filename,
            'alt': alt,
            'caption': str(item.get('caption') or alt).strip(),
            'attachment_id': item_id,
            'image_id': item_id,
            'message_id': str(item.get('message_id') or item.get('messageId') or parent_message_id or '').strip(),
            'endpoint_mode': endpoint_mode,
            'api_endpoint_mode': endpoint_mode,
            'source_type': str(item.get('source_type') or item.get('sourceType') or obj.get('source_type') or 'assistant_generated').strip() or 'assistant_generated',
            'source_role': str(item.get('source_role') or item.get('role') or 'assistant').strip() or 'assistant',
            'operation': str(item.get('operation') or item.get('task_mode') or parent_operation or 'generate').strip() or 'generate',
            'created_at_ms': created_at_ms,
            'image_seq': image_seq,
            'parent_image_id': parent_image_id,
            'source_image_ids': source_image_ids,
            'derived_from': source_image_ids,
        })
    return out

def _extract_image_urls_from_content(content) -> list[str]:
    refs: list[str] = []
    def add(u):
        value = str(u or '').strip()
        if not value:
            return
        if value.startswith(('http://', 'https://', 'data:image/', '/api3/uploads/', '/api3/generated-files/', '/api3/generated-download/', '/api3/remote-image', '/api3/image_proxy', 'upload://')):
            refs.append(value)
    if isinstance(content, dict) and str(content.get('_kind') or '').strip() == 'image_reply':
        for it in _image_reply_content_to_image_url_parts(content):
            for candidate in _image_item_model_candidates(it):
                add(candidate)
    elif isinstance(content, list):
        for it in content:
            if not isinstance(it, dict):
                continue
            if it.get('type') == 'image_url':
                for candidate in _image_item_model_candidates(it):
                    add(candidate)
            elif it.get('type') == 'text':
                txt = str(it.get('text') or '')
                for m in re.finditer(r'!\[[^\]]*\]\((https?://[^)\s]+)\)', txt):
                    add(m.group(1))
    elif isinstance(content, str):
        txt = content
        for m in re.finditer(r'!\[[^\]]*\]\((https?://[^)\s]+)\)', txt):
            add(m.group(1))
        for m in re.finditer(r'https?://\S+', txt):
            u = m.group(0).rstrip(").,;!?\"'")
            if re.search(r'\.(?:png|jpe?g|webp|gif|bmp)(?:[?#].*)?$', u, flags=re.I):
                add(u)
    out=[]; seen=set()
    for u in refs:
        if u not in seen:
            seen.add(u); out.append(u)
    return out



def _visual_endpoint_mode_normalize(value: str = '') -> str:
    raw = str(value or '').strip().lower().replace('-', '_').replace(' ', '_')
    if not raw:
        return ''
    if raw in {'responses', 'response', 'openai_responses', 'responses_api', 'response_api'}:
        return 'responses'
    if raw in {'chat', 'chat_completions', 'chat_completion', 'completions', 'chatcompletions', 'chat_api'}:
        return 'chat_completions'
    if raw in {'legacy', 'legacy_shared', 'shared', 'unknown'}:
        return 'legacy_shared'
    return raw[:64]


def _visual_endpoint_mode_from_obj(obj) -> str:
    if not isinstance(obj, dict):
        return ''
    for key in ('endpoint_mode', 'api_endpoint_mode', 'apiEndpointMode', 'endpointMode', '_endpoint_mode'):
        mode = _visual_endpoint_mode_normalize(obj.get(key))
        if mode:
            return mode
    settings = obj.get('api_settings') if isinstance(obj.get('api_settings'), dict) else obj.get('apiSettings') if isinstance(obj.get('apiSettings'), dict) else None
    if isinstance(settings, dict):
        for key in ('endpoint_mode', 'api_endpoint_mode', 'apiEndpointMode', 'endpointMode'):
            mode = _visual_endpoint_mode_normalize(settings.get(key))
            if mode:
                return mode
    meta = obj.get('meta') if isinstance(obj.get('meta'), dict) else None
    if isinstance(meta, dict):
        mode = _visual_endpoint_mode_from_obj(meta)
        if mode:
            return mode
    return ''


def _visual_current_endpoint_mode(client_override=None) -> str:
    try:
        mode = _visual_endpoint_mode_normalize(getattr(client_override, '_webai_api_endpoint_mode', '') if client_override is not None else '')
        if mode:
            return mode
    except Exception:
        pass
    try:
        settings = getattr(client_override, '_webai_api_settings', {}) if client_override is not None else {}
        if isinstance(settings, dict):
            mode = _visual_endpoint_mode_from_obj(settings)
            if mode:
                return mode
    except Exception:
        pass
    try:
        req = globals().get('request')
        if req is not None:
            data = req.get_json(force=False, silent=True) or {}
            if isinstance(data, dict):
                mode = _visual_endpoint_mode_from_obj(data)
                if mode:
                    return mode
    except Exception:
        pass
    return ''


def _visual_legacy_lane_fallback_enabled() -> bool:
    try:
        raw = str(app_getenv('IMAGE_CONTEXT_LEGACY_LANE_FALLBACK', '1') or '1').strip().lower()
        return raw not in {'0', 'false', 'no', 'off'}
    except Exception:
        return True


def _visual_row_endpoint_mode(row: dict | None = None) -> str:
    r = dict(row or {}) if isinstance(row, dict) else {}
    mode = _visual_endpoint_mode_from_obj(r)
    if mode:
        return mode
    item = r.get('item') if isinstance(r.get('item'), dict) else None
    if isinstance(item, dict):
        mode = _visual_endpoint_mode_from_obj(item)
        if mode:
            return mode
    return ''


def _visual_filter_image_rows_for_endpoint(rows: list[dict] | None = None, *, endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[dict]:
    lane = _visual_endpoint_mode_normalize(endpoint_mode)
    clean: list[dict] = []
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        item = dict(row)
        row_lane = _visual_row_endpoint_mode(item)
        if row_lane:
            item['endpoint_mode'] = row_lane
            item['api_endpoint_mode'] = row_lane
        else:
            item['endpoint_mode'] = 'legacy_shared'
            item['api_endpoint_mode'] = 'legacy_shared'
        clean.append(item)
    if not lane or lane == 'legacy_shared':
        return clean
    same = [r for r in clean if _visual_endpoint_mode_normalize(r.get('endpoint_mode')) == lane]
    if same:
        return same
    legacy_ok = _visual_legacy_lane_fallback_enabled() if allow_legacy is None else bool(allow_legacy)
    if not legacy_ok:
        return []
    return [r for r in clean if _visual_endpoint_mode_normalize(r.get('endpoint_mode')) == 'legacy_shared']


def _find_recent_user_image_urls(messages: list, limit: int = 4, *, endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[str]:
    rows = _collect_context_image_items(messages or [], roles=('user',), endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    urls: list[str] = []
    for row in sorted(rows or [], key=_image_row_order_key, reverse=True):
        u = str((row or {}).get('url') or '').strip()
        if u and u not in urls:
            urls.append(u)
        if len(urls) >= max(1, int(limit or 4)):
            return urls[:max(1, int(limit or 4))]
    return urls[:max(1, int(limit or 4))]


def _find_recent_assistant_image_urls(messages: list, limit: int = 4, *, endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[str]:
    rows = _collect_context_image_items(messages or [], roles=('assistant', 'tool'), endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    urls: list[str] = []
    for row in sorted(rows or [], key=_image_row_order_key, reverse=True):
        u = str((row or {}).get('url') or '').strip()
        if u and u not in urls:
            urls.append(u)
        if len(urls) >= max(1, int(limit or 4)):
            return urls[:max(1, int(limit or 4))]
    return urls[:max(1, int(limit or 4))]


def _find_recent_context_image_urls(messages: list, limit: int = 4, *, endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[str]:
    out: list[str] = []
    for group in (
        _find_recent_user_image_urls(messages or [], limit=limit, endpoint_mode=endpoint_mode, allow_legacy=allow_legacy),
        _find_recent_assistant_image_urls(messages or [], limit=limit, endpoint_mode=endpoint_mode, allow_legacy=allow_legacy),
    ):
        for u in group:
            if u and u not in out:
                out.append(u)
            if len(out) >= max(1, int(limit or 4)):
                return out[:max(1, int(limit or 4))]
    return out[:max(1, int(limit or 4))]


_VISUAL_TEXT_HINT_CACHE_LOCK = threading.Lock()
_VISUAL_TEXT_HINT_CACHE: dict[str, dict] = {}
_VISUAL_TEXT_HINT_CACHE_MAX = 256


def _image_prompt_best_url(item: dict | None = None) -> str:
    for candidate in _image_item_model_candidates(item):
        if candidate:
            return candidate
    return ''



def _image_text_hint_score(text: str) -> float:
    try:
        return float(_ocr_text_score(text))
    except Exception:
        return 0.0



def _should_upgrade_image_text_hint(item: dict | None = None, *, text: str = '', data_url: str = '') -> bool:
    compact = re.sub(r'\s+', '', str(text or ''))
    score = _image_text_hint_score(text)
    screenshot_like = _is_probable_chat_screenshot_item(item, data_url=data_url)
    symbol_dense = _looks_symbol_dense_text(text)
    if not compact:
        return True
    if screenshot_like and score < 320:
        return True
    if symbol_dense and (score < 220 or len(compact) < 64):
        return True
    if len(compact) < 24:
        return True
    return score < 95


def _should_pass_low_trust_seed_to_visual_hint(seed_text: str, *, screenshot_like: bool = False, symbol_dense: bool = False) -> bool:
    raw = str(seed_text or '').strip()
    if not raw or screenshot_like:
        return False
    compact = re.sub(r'\s+', '', raw)
    if len(compact) < 28:
        return False
    score = _image_text_hint_score(raw)
    if symbol_dense and score < 200:
        return False
    return score >= 110


def _data_url_to_pil_image(data_url: str):
    raw = str(data_url or '').strip()
    if not raw.lower().startswith('data:image/') or 'base64,' not in raw:
        return None
    try:
        _head, b64 = raw.split('base64,', 1)
        blob = base64.b64decode((b64 or '').strip(), validate=False)
        from PIL import Image, ImageOps  # type: ignore
        img = Image.open(io.BytesIO(blob))
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode not in ('RGB', 'L'):
            try:
                img = img.convert('RGB')
            except Exception:
                pass
        return img
    except Exception:
        return None


def _pil_image_to_png_data_url(img, *, text_ready: bool = False) -> str:
    if text_ready:
        try:
            img = _ocr_render_text_ready_image(img, strong=True)
        except Exception:
            pass
    try:
        from PIL import Image  # type: ignore
        resample = getattr(Image, 'Resampling', Image).LANCZOS
    except Exception:
        resample = None
    try:
        w, h = img.size
        longest = max(int(w or 0), int(h or 0), 1)
        if longest < 2200 and resample is not None:
            scale = min(2.2, max(1.0, 2200.0 / float(longest)))
            if scale > 1.03:
                img = img.resize((max(1, int(round(w * scale))), max(1, int(round(h * scale)))), resample)
    except Exception:
        pass
    try:
        out = io.BytesIO()
        if getattr(img, 'mode', '') not in ('RGB', 'L'):
            img = img.convert('RGB')
        img.save(out, format='PNG', optimize=True, compress_level=4)
        data = out.getvalue()
        if not data:
            return ''
        return 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')
    except Exception:
        return ''



def _is_image_text_transcription_request(user_text: str = '') -> bool:
    t = str(user_text or '').strip().lower()
    if not t:
        return False
    patterns = [
        r'识别', r'ocr', r'读出来', r'抄一下', r'转写', r'逐字', r'原文', r'题目', r'题干',
        r'图里写了什么', r'图片里写了什么', r'截图里写了什么', r'文字内容', r'内容是什么',
        r'什么题', r'第\s*\d+(?:\.\d+)?\s*题', r'准确率', r'不准', r'看不清'
    ]
    return any(re.search(p, t, flags=re.I) for p in patterns)


def _find_screenshot_embedded_media_crop(img):
    try:
        from PIL import ImageOps, ImageStat  # type: ignore
    except Exception:
        return None
    try:
        base = img if getattr(img, 'mode', '') == 'L' else ImageOps.grayscale(img)
        w, h = base.size
    except Exception:
        return None
    if min(int(w or 0), int(h or 0)) < 320:
        return None

    grid_x = 4
    grid_y = 4 if h <= int(w * 1.2) else 5
    best = None
    for gy in range(grid_y):
        for gx in range(grid_x):
            left = int(round(w * gx / grid_x))
            right = int(round(w * (gx + 1) / grid_x))
            top = int(round(h * gy / grid_y))
            bottom = int(round(h * (gy + 1) / grid_y))
            if right - left < max(180, int(w * 0.16)) or bottom - top < max(140, int(h * 0.14)):
                continue
            try:
                crop = base.crop((left, top, right, bottom))
                hist = crop.histogram() or []
                total = float(sum(hist) or 1.0)
                white_ratio = float(sum(hist[245:])) / total
                dark_ratio = float(sum(hist[:90])) / total
                mid_ratio = float(sum(hist[85:235])) / total
                stddev = float((ImageStat.Stat(crop).stddev or [0.0])[0] or 0.0)
            except Exception:
                continue
            coverage = float((right - left) * (bottom - top)) / float(max(1, w * h))
            if coverage < 0.045 or coverage > 0.46:
                continue
            if white_ratio > 0.90 or mid_ratio < 0.14 or stddev < 18.0:
                continue
            score = stddev * 2.4 + mid_ratio * 120.0 - white_ratio * 35.0 - dark_ratio * 18.0
            if gx >= max(1, grid_x // 2):
                score += 5.0
            if gy <= max(1, grid_y // 2):
                score += 3.0
            cand = {'score': score, 'box': (left, top, right, bottom), 'coverage': coverage}
            if best is None or score > float(best.get('score') or 0.0):
                best = cand
    if not best or float(best.get('score') or 0.0) < 48.0:
        return None
    left, top, right, bottom = best['box']
    pad_x = max(10, int(round((right - left) * 0.06)))
    pad_y = max(10, int(round((bottom - top) * 0.06)))
    left = max(0, left - pad_x)
    top = max(0, top - pad_y)
    right = min(w, right + pad_x)
    bottom = min(h, bottom + pad_y)
    try:
        crop = img.crop((left, top, right, bottom))
    except Exception:
        return None
    return {
        'crop': crop,
        'box': (left, top, right, bottom),
        'coverage': float(best.get('coverage') or 0.0),
        'score': float(best.get('score') or 0.0),
    }

def _build_visual_focus_crop_data_url(data_url: str, *, screenshot_like: bool = False, symbol_dense: bool = False) -> str:
    img = _data_url_to_pil_image(data_url)
    if img is None:
        return ''
    try:
        w, h = img.size
    except Exception:
        return ''
    if min(int(w or 0), int(h or 0)) <= 0:
        return ''

    candidates = []
    seen = set()

    def push(one):
        try:
            key = (tuple(getattr(one, 'size', (0, 0)) or (0, 0)), hash(one.tobytes()[:2048]))
        except Exception:
            key = (tuple(getattr(one, 'size', (0, 0)) or (0, 0)), id(one))
        if key in seen:
            return
        seen.add(key)
        candidates.append(one)

    if screenshot_like:
        nested = _find_screenshot_embedded_media_crop(img)
        if isinstance(nested, dict):
            push(nested.get('crop'))

    push(_ocr_trim_background_edges(img, tolerance=18))
    for crop in _ocr_generate_focus_crops(img):
        push(crop)

    def add_ratio_box(left_ratio, top_ratio, right_ratio, bottom_ratio):
        left = int(round(w * float(left_ratio)))
        top = int(round(h * float(top_ratio)))
        right = int(round(w * float(right_ratio)))
        bottom = int(round(h * float(bottom_ratio)))
        if right - left < max(320, int(w * 0.45)) or bottom - top < max(240, int(h * 0.42)):
            return
        try:
            push(img.crop((left, top, right, bottom)))
        except Exception:
            return

    add_ratio_box(0.08, 0.08, 0.92, 0.92)
    if screenshot_like:
        add_ratio_box(0.14, 0.40, 0.92, 0.98)
        add_ratio_box(0.16, 0.50, 0.90, 0.98)
    elif symbol_dense:
        add_ratio_box(0.05, 0.05, 0.95, 0.94)

    scored = [(_ocr_focus_region_score(one), one) for one in candidates if one is not None]
    scored.sort(key=lambda it: it[0], reverse=True)
    best = (scored[0][1] if scored else None) or img
    return _pil_image_to_png_data_url(best, text_ready=True)


def _build_visual_text_hint_prompt(*, screenshot_like: bool = False, symbol_dense: bool = False) -> str:
    parts = [
        '请稳定提取这张图片里与主体内容直接相关的可见文字。不要回答问题，不要总结，不要翻译，不要脑补。',
        '若只有部分文字能确认，就只写能确认的部分，并尽量保留原文换行。',
    ]
    if screenshot_like:
        parts.append('如果这是聊天/网页/应用截图，请尽量忽略明显无关的状态栏、地址栏、侧边栏、按钮、输入框、模型名或壳层 UI；但如果聊天正文/页面正文就是主体内容，请保留主体区域里的正文文字。')
    else:
        parts.append('如果有正文、题目、表格、图片说明或页码，请优先保留主体区域，不要把边缘噪声当成正文。')
    parts.append('如有编号、括号、项目符号、标点、英文字母、数字或短横线，请按原样保留。')
    if symbol_dense:
        parts.append('这张图里很可能有逻辑/数学/公式符号。请逐字逐符号抄写，不要把少见符号替换成更常见的符号。尤其不要自行把 ↑、↓、∨、∧、→、¬、↔ 等替换成别的箭头或运算符。')
    else:
        parts.append('如果看见公式或特殊符号，也请尽量逐字逐符号保留。')
    parts.append('请严格只按下面格式输出：\n<kind>document|screenshot|scene|mixed</kind>\n<text>\n这里写提取到的主体文字；如果几乎没有可用文字就留空\n</text>')
    return ''.join(parts)


def _extract_visual_text_hint_once(model_name: str, data_url: str, *, prompt_text: str, user_text: str, client_override=None) -> dict:
    out = {'text': '', 'kind': '', 'source': 'none'}
    if not model_name or not data_url:
        return out
    try:
        req = _apply_completion_thinking_kwargs({
            'model': model_name,
            'messages': [
                {'role': 'system', 'content': prompt_text},
                {'role': 'user', 'content': [
                    {'type': 'text', 'text': user_text},
                    {'type': 'image_url', 'image_url': {'url': data_url}},
                ]},
            ],
            'temperature': 0,
            'max_tokens': 900,
        }, role='chat', model=model_name, client_override=client_override)
        resp = (client_override or client_gpt).chat.completions.create(**req)
        raw = (((resp.choices or [None])[0] or None).message.content or '').strip()
        kind, parsed_text = _normalize_visual_text_hint_output(raw)
        if parsed_text:
            out = {'text': truncate_text(parsed_text, max_chars=2200), 'kind': kind, 'source': 'vision_model'}
    except Exception as e:
        app_logger.warning('[image_text_hint] vision_extract_failed model=%s err=%s: %s', model_name, type(e).__name__, e)
    return out


def _pick_better_visual_text_hint(primary: dict | None, candidate: dict | None, *, symbol_dense: bool = False) -> dict:
    a = dict(primary or {})
    b = dict(candidate or {})
    a_text = str(a.get('text') or '').strip()
    b_text = str(b.get('text') or '').strip()
    a_score = _image_text_hint_score(a_text)
    b_score = _image_text_hint_score(b_text)
    if symbol_dense:
        if _looks_symbol_dense_text(a_text):
            a_score += 24.0
        if _looks_symbol_dense_text(b_text):
            b_score += 24.0
    if b_score > a_score * 1.05:
        return b
    return a if a_text else b



def _normalize_visual_text_hint_output(raw: str) -> tuple[str, str]:
    text = str(raw or '').strip()
    if not text:
        return '', ''
    kind = ''
    m_kind = re.search(r'<kind>\s*([^<]{1,40})\s*</kind>', text, flags=re.I | re.S)
    if m_kind:
        kind = str(m_kind.group(1) or '').strip().lower()
    m_text = re.search(r'<text>\s*([\s\S]*?)\s*</text>', text, flags=re.I)
    if m_text:
        text = str(m_text.group(1) or '').strip()
    text = re.sub(r'^```(?:\w+)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = re.sub(r'^提取结果[:：]\s*', '', text)
    text = re.sub(r'^识别结果[:：]\s*', '', text)
    text = text.strip()
    if text in {'【无可提取文字】', '[无可提取文字]', '无可提取文字', '无明显文字', '未识别到文字', '无'}:
        text = ''
    return kind, text



def _visual_text_hint_cache_key(model: str | None, data_url: str = '') -> str:
    return (str(model or '').strip().lower() + '::' + hashlib.sha1(str(data_url or '').encode('utf-8', 'ignore')).hexdigest())



def _visual_text_hint_cache_get(model: str | None, data_url: str = '') -> dict | None:
    key = _visual_text_hint_cache_key(model, data_url=data_url)
    with _VISUAL_TEXT_HINT_CACHE_LOCK:
        row = _VISUAL_TEXT_HINT_CACHE.get(key)
        return dict(row) if isinstance(row, dict) else None



def _visual_text_hint_cache_set(model: str | None, data_url: str = '', payload: dict | None = None) -> dict:
    key = _visual_text_hint_cache_key(model, data_url=data_url)
    item = dict(payload or {})
    item['updated_at'] = time.time()
    with _VISUAL_TEXT_HINT_CACHE_LOCK:
        _VISUAL_TEXT_HINT_CACHE[key] = item
        if len(_VISUAL_TEXT_HINT_CACHE) > _VISUAL_TEXT_HINT_CACHE_MAX:
            rows = sorted(_VISUAL_TEXT_HINT_CACHE.items(), key=lambda kv: float((kv[1] or {}).get('updated_at') or 0.0))
            drop_n = max(1, len(_VISUAL_TEXT_HINT_CACHE) - _VISUAL_TEXT_HINT_CACHE_MAX)
            for stale_key, _stale_val in rows[:drop_n]:
                _VISUAL_TEXT_HINT_CACHE.pop(stale_key, None)
    return item



def _extract_visual_text_hint_with_model(model: str | None, data_url: str, *, existing_text: str = '', item: dict | None = None, client_override=None) -> dict:
    cached = _visual_text_hint_cache_get(model, data_url=data_url)
    if isinstance(cached, dict):
        return cached

    out = {'text': '', 'kind': '', 'source': 'none'}
    data_url = str(data_url or '').strip()
    model_name = str(model or '').strip()
    if not data_url or not model_name:
        return out

    seed_text = str(existing_text or '').strip()
    screenshot_like = bool(_is_probable_chat_screenshot_item(item, data_url=data_url) or _looks_like_chat_ui_ocr_text(seed_text))
    symbol_dense = _looks_symbol_dense_text(seed_text)
    prompt_text = _build_visual_text_hint_prompt(screenshot_like=screenshot_like, symbol_dense=symbol_dense)
    user_text = '请提取这张图片中的主体文字。'
    if _should_pass_low_trust_seed_to_visual_hint(seed_text, screenshot_like=screenshot_like, symbol_dense=symbol_dense):
        user_text += '\\n\\n下面是低可信本地 OCR，可参考但不要盲信或照抄：\\n' + truncate_text(seed_text, max_chars=1200)

    first = _extract_visual_text_hint_once(model_name, data_url, prompt_text=prompt_text, user_text=user_text, client_override=client_override)
    out = first if isinstance(first, dict) else out

    first_text = str((out or {}).get('text') or '').strip()
    need_focus_retry = False
    if screenshot_like and _image_text_hint_score(first_text) < 340:
        need_focus_retry = True
    if symbol_dense and (_image_text_hint_score(first_text) < 240 or not _looks_symbol_dense_text(first_text)):
        need_focus_retry = True
    if need_focus_retry:
        crop_data_url = _build_visual_focus_crop_data_url(data_url, screenshot_like=screenshot_like, symbol_dense=symbol_dense)
        if crop_data_url and crop_data_url != data_url:
            retry_user_text = '请只看这张经过局部放大和文字增强的图片，继续提取主体文字；不要补全看不清的字符。'
            second = _extract_visual_text_hint_once(model_name, crop_data_url, prompt_text=prompt_text, user_text=retry_user_text, client_override=client_override)
            out = _pick_better_visual_text_hint(out, second, symbol_dense=symbol_dense)

    return _visual_text_hint_cache_set(model, data_url=data_url, payload=out)



def _iter_recent_context_image_items(messages: list, limit: int = 4, *, endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[dict]:
    rows = _collect_context_image_items(messages or [], roles=('user', 'assistant', 'tool'), endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    out: list[dict] = []
    seen: set[str] = set()
    for row in sorted(rows or [], key=_image_row_order_key, reverse=True):
        if not isinstance(row, dict):
            continue
        dedupe_key = str(row.get('attachment_key') or row.get('url') or '').strip()
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(dict(row))
        if len(out) >= max(1, int(limit or 4)):
            break
    return out[:max(1, int(limit or 4))]


def _looks_like_multi_image_reference(user_text: str = '') -> bool:
    t = str(user_text or '').strip().lower()
    if not t:
        return False
    patterns = [
        r'这两张', r'这几张', r'这两个图', r'这两幅', r'这两题', r'这几题',
        r'上面两张', r'下面两张', r'前两张', r'前面两张', r'两张图', r'几张图',
        r'比较', r'对比', r'区别', r'差别', r'分别', r'各自', r'哪张', r'哪一张',
        r'第一张和第二张', r'第\s*1\s*张和第\s*2\s*张', r'前后两张', r'最近两张', r'最后两张'
    ]
    return any(re.search(p, t, flags=re.I) for p in patterns)


def _image_anchor_message_text(message: dict | None = None) -> str:
    m = dict(message or {})
    content = m.get('content')
    parts: list[str] = []
    if isinstance(content, list):
        for it in content:
            if isinstance(it, dict) and str(it.get('type') or '').strip() == 'text':
                value = str(it.get('text') or '').strip()
                if value:
                    parts.append(value)
    elif isinstance(content, str):
        value = content.strip()
        if value:
            parts.append(value)
    if parts:
        return '\n'.join(parts).strip()
    helper = globals().get('_message_to_text_for_budget')
    if callable(helper):
        try:
            return str(helper(m, include_images=False, include_image_text=False) or '').strip()
        except Exception:
            return ''
    return ''


def _coerce_image_order_ts_ms(value, default: int = 0) -> int:
    try:
        if value is None:
            return int(default or 0)
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return int(default or 0)
            if re.fullmatch(r'\d+(?:\.\d+)?', raw):
                num = float(raw)
            else:
                try:
                    dt = datetime.datetime.fromisoformat(raw.replace('Z', '+00:00'))
                    num = dt.timestamp() * 1000.0
                except Exception:
                    return int(default or 0)
        else:
            num = float(value)
        if num <= 0:
            return int(default or 0)
        if num < 10000000000:
            num *= 1000.0
        return int(num)
    except Exception:
        return int(default or 0)


def _image_message_created_at_ms(message: dict | None = None, *, fallback_ms: int = 0) -> int:
    m = dict(message or {})
    for key in ('created_at_ms', 'createdAtMs', 'created_at', 'createdAt', 'ts', 'time'):
        ts = _coerce_image_order_ts_ms(m.get(key), 0)
        if ts > 0:
            return ts
    return int(fallback_ms or 0)


def _image_item_created_at_ms(item: dict | None = None, message: dict | None = None, *, message_index: int = 0, idx: int = 0) -> int:
    row = dict(item or {})
    for key in ('created_at_ms', 'createdAtMs', '_created_at_ms', 'server_created_at_ms', 'created_at', 'createdAt', 'created_ts', 'ts'):
        ts = _coerce_image_order_ts_ms(row.get(key), 0)
        if ts > 0:
            return ts
    msg_ts = _image_message_created_at_ms(message, fallback_ms=0)
    if msg_ts > 0:
        return msg_ts
    try:
        return int(message_index or 0) * 1000000 + int(idx or 0)
    except Exception:
        return 0


def _image_item_order_seq(item: dict | None = None, *, message_index: int = 0, idx: int = 0) -> int:
    row = dict(item or {})
    for key in ('image_seq', 'seq', 'order_seq', '_image_seq'):
        try:
            value = row.get(key)
            if value is not None and str(value).strip() != '':
                return int(float(value))
        except Exception:
            pass
    try:
        return int(message_index or 0) * 1000 + int(idx or 0)
    except Exception:
        return int(idx or 0)


def _image_row_order_key(row: dict | None = None) -> tuple[int, int, int, int]:
    r = dict(row or {})
    try:
        ts = int(float(r.get('order_ts_ms') or r.get('created_at_ms') or 0))
    except Exception:
        ts = 0
    try:
        seq = int(float(r.get('order_seq') or r.get('image_seq') or 0))
    except Exception:
        seq = 0
    try:
        msg_idx = int(r.get('message_index') or 0)
    except Exception:
        msg_idx = 0
    try:
        img_idx = int(r.get('idx') or 0)
    except Exception:
        img_idx = 0
    return (ts, seq, msg_idx, img_idx)


def _collect_context_image_items(messages: list, *, roles: tuple[str, ...] = ('user', 'assistant', 'tool'), endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[dict]:
    allowed_roles = {str(r or '').strip() for r in (roles or ()) if str(r or '').strip()}
    out: list[dict] = []
    seen: set[str] = set()
    for message_index, m in enumerate(messages or []):
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '').strip()
        if role not in allowed_roles:
            continue
        content = m.get('content')
        if isinstance(content, dict) and str(content.get('_kind') or '').strip() == 'image_reply':
            image_parts = _image_reply_content_to_image_url_parts(content)
        elif isinstance(content, list):
            image_parts = content
        else:
            image_parts = []
        if not isinstance(image_parts, list):
            continue
        message_ts_ms = _image_message_created_at_ms(m, fallback_ms=0)
        message_id = str(m.get('message_id') or m.get('messageId') or m.get('id') or m.get('_id') or '').strip()
        session_id = str(m.get('session_id') or m.get('sessionId') or m.get('client_session_id') or m.get('conversation_id') or '').strip()
        try:
            turn_index = int(m.get('turn_index') or m.get('turnIndex') or message_index)
        except Exception:
            turn_index = int(message_index or 0)
        message_lane = _visual_endpoint_mode_from_obj(m)
        message_text = _image_anchor_message_text(m)[:320]
        for idx, it in enumerate(image_parts, 1):
            if not isinstance(it, dict) or it.get('type') != 'image_url':
                continue
            best_url = _image_prompt_best_url(it)
            attachment_key = _image_item_attachment_key(it)
            dedupe_key = str(attachment_key or best_url or '').strip()
            if not best_url or not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            image_created_at_ms = _image_item_created_at_ms(it, m, message_index=message_index, idx=idx)
            if image_created_at_ms <= 0 and message_ts_ms > 0:
                image_created_at_ms = message_ts_ms
            available_at_ms = _coerce_image_order_ts_ms(
                it.get('image_available_at_ms') or it.get('available_at_ms') or it.get('landed_at_ms') or it.get('saved_at_ms') or it.get('completed_at_ms') or it.get('created_at_ms') or it.get('createdAtMs'),
                image_created_at_ms,
            )
            # Conversation order must be anchored to the owning message, not to the
            # moment an async generated image is downloaded or saved.  Keep the
            # actual image/file timestamps separately for diagnostics.
            try:
                structural_order_ts_ms = int(message_index or 0) * 1000000 + int(idx or 0)
            except Exception:
                structural_order_ts_ms = int(idx or 0)
            order_ts_ms = message_ts_ms or structural_order_ts_ms
            order_seq = _image_item_order_seq(it, message_index=message_index, idx=idx)
            source_type = str(it.get('source_type') or it.get('sourceType') or '').strip()
            if not source_type:
                operation_hint = str(it.get('operation') or it.get('task_mode') or '').strip().lower()
                if role == 'user':
                    source_type = 'user_upload'
                elif role == 'tool':
                    source_type = 'image_search'
                elif operation_hint in {'edit', 'image_edit', 'assistant_edited', 'variation'}:
                    source_type = 'assistant_edited'
                elif role == 'assistant':
                    source_type = 'assistant_generated'
                else:
                    source_type = 'image'
            operation = str(it.get('operation') or it.get('task_mode') or source_type or ('upload' if role == 'user' else 'generate' if role == 'assistant' else '')).strip()
            row_lane = _visual_endpoint_mode_from_obj(it) or message_lane
            if not row_lane:
                row_lane = 'legacy_shared'
            image_id = str(
                it.get('image_id') or it.get('imageId') or it.get('attachment_id') or it.get('id') or it.get('uuid') or ''
            ).strip()
            if not image_id:
                try:
                    image_id = 'img_' + hashlib.sha1(dedupe_key.encode('utf-8', errors='ignore')).hexdigest()[:16]
                except Exception:
                    image_id = 'img_' + str(abs(hash(dedupe_key)))[:16]
            ocr_text = str(
                it.get('ocr_text_hint') or it.get('ocrTextHint') or it.get('visual_text') or it.get('image_text') or it.get('text_hint') or it.get('caption') or ''
            ).strip()
            raw_source_image_ids = it.get('source_image_ids') or it.get('sourceImageIds') or it.get('derived_from') or it.get('derivedFrom') or []
            if isinstance(raw_source_image_ids, str):
                source_image_ids = [raw_source_image_ids]
            elif isinstance(raw_source_image_ids, list):
                source_image_ids = [str(x or '').strip() for x in raw_source_image_ids if str(x or '').strip()]
            else:
                source_image_ids = []
            parent_image_id_value = str(it.get('parent_image_id') or it.get('parentImageId') or '').strip()
            if parent_image_id_value and parent_image_id_value not in source_image_ids:
                source_image_ids.insert(0, parent_image_id_value)
            row = {
                'image_id': image_id,
                'role': role,
                'source_role': str(it.get('source_role') or it.get('role') or role).strip() or role,
                'source_type': source_type,
                'operation': operation,
                'status': str(it.get('status') or it.get('state') or 'ready').strip() or 'ready',
                'endpoint_mode': row_lane,
                'api_endpoint_mode': row_lane,
                'session_id': session_id or str(it.get('session_id') or it.get('sessionId') or '').strip(),
                'message_id': str(it.get('message_id') or it.get('messageId') or message_id or '').strip(),
                'turn_index': turn_index,
                'parent_image_id': parent_image_id_value,
                'source_image_ids': source_image_ids,
                'derived_from': source_image_ids,
                'request_id': str(it.get('request_id') or it.get('requestId') or it.get('job_id') or it.get('jobId') or '').strip(),
                'created_at_ms': order_ts_ms,
                'order_ts_ms': order_ts_ms,
                'image_created_at_ms': image_created_at_ms,
                'image_available_at_ms': available_at_ms,
                'image_seq': order_seq,
                'order_seq': order_seq,
                'message_created_at_ms': message_ts_ms,
                'message_text': message_text,
                'ocr_text_hint': ocr_text,
                'ocr_source': str(it.get('ocr_source') or it.get('ocrSource') or ('local_hint' if ocr_text else '')).strip(),
                'item': it,
                'url': best_url,
                'idx': idx,
                'message_index': message_index,
                'attachment_key': dedupe_key,
            }
            if str(row.get('status') or '').strip().lower() in {'deleted', 'removed', 'failed', 'error'}:
                continue
            out.append(row)
    out.sort(key=_image_row_order_key)
    if endpoint_mode:
        out = _visual_filter_image_rows_for_endpoint(out, endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    return out


_IMAGE_REF_CN_NUM_MAP = {
    '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
}


def _parse_image_ref_ordinal(value: str) -> int | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    if raw.isdigit():
        try:
            return max(1, int(raw))
        except Exception:
            return None
    if raw in _IMAGE_REF_CN_NUM_MAP:
        return _IMAGE_REF_CN_NUM_MAP.get(raw)
    if len(raw) == 2 and raw[0] == '十' and raw[1] in _IMAGE_REF_CN_NUM_MAP:
        return 10 + int(_IMAGE_REF_CN_NUM_MAP.get(raw[1]) or 0)
    if len(raw) == 2 and raw[1] == '十' and raw[0] in _IMAGE_REF_CN_NUM_MAP:
        return int(_IMAGE_REF_CN_NUM_MAP.get(raw[0]) or 0) * 10
    if len(raw) == 3 and raw[1] == '十' and raw[0] in _IMAGE_REF_CN_NUM_MAP and raw[2] in _IMAGE_REF_CN_NUM_MAP:
        return int(_IMAGE_REF_CN_NUM_MAP.get(raw[0]) or 0) * 10 + int(_IMAGE_REF_CN_NUM_MAP.get(raw[2]) or 0)
    return None


def _looks_like_deictic_image_followup(user_text: str = '') -> bool:
    t = str(user_text or '').strip().lower()
    if not t:
        return False
    deictic_patterns = [
        r'那张图', r'那张图片', r'那张', r'那一张', r'那幅', r'那个图', r'那题', r'那一题',
        r'这张图', r'这张图片', r'这张', r'这一张', r'这幅', r'这题', r'这一题',
        r'上面那张', r'下面那张', r'刚才那张', r'刚刚那张', r'前面那张', r'之前那张',
        r'再看看', r'再看一下', r'再看一眼', r'再看下', r'再看看那张', r'回去看', r'看回那张'
    ]
    if not any(re.search(p, t, flags=re.I) for p in deictic_patterns):
        return False
    explicit_patterns = [
        r'第\s*[0-9一二两三四五六七八九十]+\s*(?:张|幅|个图|题|页)',
        r'第一次(?:发|传|上传)', r'最开始(?:发|传|上传)', r'一开始(?:发|传|上传)',
        r'最新(?:那张|一张|的图)?', r'最后一张', r'上一张', r'前一张', r'倒数第'
    ]
    return not any(re.search(p, t, flags=re.I) for p in explicit_patterns)


def _pick_image_rows_by_indices(rows: list[dict], indices: list[int], *, limit: int = 4, binding_mode: str = '', binding_desc: str = '') -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    total = len(rows or [])
    for idx in indices or []:
        try:
            pos = int(idx)
        except Exception:
            continue
        if pos < 0:
            pos = total + pos + 1
        if pos < 1 or pos > total:
            continue
        row = dict(rows[pos - 1] or {})
        dedupe_key = str(row.get('attachment_key') or row.get('url') or '').strip()
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        if binding_mode:
            row['binding_mode'] = binding_mode
        if binding_desc:
            row['binding_desc'] = binding_desc
        out.append(row)
        if len(out) >= limit:
            break
    return out[:limit]



def _image_row_group_ids(row: dict | None = None) -> list[str]:
    """Stable structural group IDs for chat images.

    These IDs are not semantic intent rules. They only map the image index shown
    to the model back to concrete rows the backend can fetch.
    """
    r = dict(row or {})
    item = dict(r.get('item') or {})
    role = str(r.get('role') or r.get('source_role') or item.get('source_role') or '').strip().lower()
    msg_idx = str(r.get('message_index') if r.get('message_index') is not None else '').strip()
    source_type = str(item.get('source_type') or r.get('source_type') or '').strip().lower()
    operation = str(item.get('operation') or r.get('operation') or '').strip().lower()
    parent_image_id = str(item.get('parent_image_id') or item.get('parentImageId') or r.get('parent_image_id') or '').strip()
    groups: list[str] = []
    if role and msg_idx:
        groups.append(f'{role}_message_{msg_idx}')
        groups.append(f'{role}_image_group_{msg_idx}')
        if role == 'assistant' or source_type == 'generated' or operation in {'generate', 'image_generation', 'text_to_image'}:
            groups.append(f'assistant_image_reply_{msg_idx}')
    if parent_image_id:
        groups.append(parent_image_id)
    out: list[str] = []
    seen: set[str] = set()
    for gid in groups:
        gid = re.sub(r'[^0-9A-Za-z_\-:.]+', '_', str(gid or '').strip())
        if gid and gid not in seen:
            seen.add(gid)
            out.append(gid)
    return out


def _pick_recent_role_image_rows(messages: list, *, role: str = 'assistant', limit: int = 4, binding_mode: str = 'exact', binding_desc: str = '', endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[dict]:
    rows = _collect_context_image_items(messages or [], roles=(str(role or '').strip() or 'assistant',), endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    if not rows:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for row in sorted(rows or [], key=_image_row_order_key, reverse=True):
        if not isinstance(row, dict):
            continue
        dedupe_key = str(row.get('attachment_key') or row.get('url') or '').strip()
        if not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        item = dict(row)
        if binding_mode:
            item['binding_mode'] = binding_mode
        if binding_desc:
            item['binding_desc'] = binding_desc
        out.append(item)
        if len(out) >= max(1, int(limit or 4)):
            break
    return out[:max(1, int(limit or 4))]


def _resolve_image_ref_reference_items(messages: list, *, image_ref: str = '', user_text: str = '', limit: int = 4, endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[dict]:
    """Resolve only structural refs produced from the image index.

    The backend intentionally does not infer meanings like "你生成的图" here.
    The model should choose image_ref from the injected image index; this mapper
    only turns that structural ref into concrete image rows.
    """
    raw = str(image_ref or '').strip()
    if not raw:
        return []
    rows = _collect_context_image_items(messages or [], roles=('user', 'assistant', 'tool'), endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    if not rows:
        return []

    compact = re.sub(r'[^a-z0-9_\-一二两三四五六七八九十图]+', '', raw.lower().strip())
    raw_lower = raw.lower().strip()
    if compact in {'auto', 'default', 'current'}:
        return []

    role_rows: dict[str, list[dict]] = {'user': [], 'assistant': [], 'tool': []}
    for row in rows:
        role = str(row.get('role') or '').strip().lower()
        if role in role_rows:
            role_rows[role].append(row)

    matched_group: list[dict] = []
    for row in rows:
        dedupe_key = str(row.get('attachment_key') or row.get('url') or '').strip()
        url = str(row.get('url') or '').strip()
        if raw and raw == dedupe_key:
            return _pick_image_rows_by_indices([row], [1], limit=limit, binding_mode='exact', binding_desc=f'image_ref:attachment:{raw[:80]}')
        if raw and raw == url:
            return _pick_image_rows_by_indices([row], [1], limit=limit, binding_mode='exact', binding_desc='image_ref:url')
        group_ids = _image_row_group_ids(row)
        if raw in group_ids or raw_lower in {g.lower() for g in group_ids} or compact in {re.sub(r'[^a-z0-9_\-]+', '', g.lower()) for g in group_ids}:
            matched_group.append(row)
    if matched_group:
        return _pick_image_rows_by_indices(matched_group, list(range(1, len(matched_group) + 1)), limit=limit, binding_mode='exact', binding_desc=f'image_ref:group:{raw[:80]}')

    if compact in {'assistant_latest', 'latest_assistant', 'assistant_last', 'assistant_recent', 'latestassistant', 'assistantlatest'}:
        return _pick_recent_role_image_rows(messages or [], role='assistant', limit=limit, binding_mode='exact', binding_desc=f'image_ref:{raw}', endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    if compact in {'user_latest', 'latest_user', 'user_last', 'user_recent', 'latestuser', 'userlatest'}:
        return _pick_recent_role_image_rows(messages or [], role='user', limit=limit, binding_mode='exact', binding_desc=f'image_ref:{raw}', endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    if compact in {'tool_latest', 'latest_tool', 'tool_last', 'tool_recent', 'latesttool', 'toollatest'}:
        return _pick_recent_role_image_rows(messages or [], role='tool', limit=limit, binding_mode='exact', binding_desc=f'image_ref:{raw}', endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    if compact in {'latest', 'recent', 'last', 'latest_image', 'recent_image', 'latestimage', 'recentimage'}:
        return _pick_image_rows_by_indices(rows, [len(rows)], limit=limit, binding_mode='exact', binding_desc=f'image_ref:{raw}')

    global_match = re.fullmatch(r'(?:img|image|图)[_\-]?([0-9一二两三四五六七八九十]+)', compact, flags=re.I)
    if global_match:
        ordinal = _parse_image_ref_ordinal(global_match.group(1))
        if ordinal:
            return _pick_image_rows_by_indices(rows, [ordinal], limit=limit, binding_mode='exact', binding_desc=f'image_ref:{raw}')

    role_match = re.fullmatch(r'(assistant|user|tool)[_\-]?(?:img|image|图)[_\-]?([0-9一二两三四五六七八九十]+)', compact, flags=re.I)
    if role_match:
        role = str(role_match.group(1) or '').strip().lower()
        ordinal = _parse_image_ref_ordinal(role_match.group(2))
        if ordinal:
            return _pick_image_rows_by_indices(role_rows.get(role) or [], [ordinal], limit=limit, binding_mode='exact', binding_desc=f'image_ref:{raw}')

    return []

def _resolve_explicit_image_reference_items(messages: list, *, user_text: str = '', limit: int = 4, endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[dict]:
    t = str(user_text or '').strip().lower()
    if not t:
        return []
    prefer_user_only = bool(re.search(r'我发|我上传|我传|发的图|上传的图|第一次发|最开始发|一开始发', t, flags=re.I))
    rows = _collect_context_image_items(messages or [], roles=('user',) if prefer_user_only else ('user', 'assistant', 'tool'), endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    if not rows and not prefer_user_only:
        rows = _collect_context_image_items(messages or [], roles=('user',), endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    if not rows:
        return []

    if re.search(r'第\s*1\s*张\s*和\s*第\s*2\s*张|第一张和第二张|前两张|前面两张|最开始两张', t, flags=re.I):
        return _pick_image_rows_by_indices(rows, [1, 2], limit=limit, binding_mode='exact', binding_desc='explicit:first_two')
    if re.search(r'最后两张|最近两张|最新两张|后两张', t, flags=re.I):
        return _pick_image_rows_by_indices(rows, [len(rows) - 1, len(rows)], limit=limit, binding_mode='exact', binding_desc='explicit:last_two')
    if re.search(r'上一张|前一张', t, flags=re.I):
        idx = len(rows) - 1 if len(rows) >= 2 else len(rows)
        return _pick_image_rows_by_indices(rows, [idx], limit=limit, binding_mode='exact', binding_desc='explicit:previous')
    if re.search(r'最后一张|最新一张|最近一张|刚发那张|刚上传那张|最新那张', t, flags=re.I):
        return _pick_image_rows_by_indices(rows, [len(rows)], limit=limit, binding_mode='exact', binding_desc='explicit:last')
    if re.search(r'第一次(?:发|传|上传)|最开始(?:发|传|上传)|一开始(?:发|传|上传)|最早那张|刚开始那张|第一张', t, flags=re.I):
        return _pick_image_rows_by_indices(rows, [1], limit=limit, binding_mode='exact', binding_desc='explicit:first')
    if re.search(r'第二张|第二题|第二幅', t, flags=re.I):
        return _pick_image_rows_by_indices(rows, [2], limit=limit, binding_mode='exact', binding_desc='explicit:second')
    if re.search(r'第三张|第三题|第三幅', t, flags=re.I):
        return _pick_image_rows_by_indices(rows, [3], limit=limit, binding_mode='exact', binding_desc='explicit:third')
    if re.search(r'第四张|第四题|第四幅', t, flags=re.I):
        return _pick_image_rows_by_indices(rows, [4], limit=limit, binding_mode='exact', binding_desc='explicit:fourth')

    ordinal_match = re.search(r'第\s*([0-9一二两三四五六七八九十]+)\s*(?:张|幅|个图|题|页)', t, flags=re.I)
    if ordinal_match:
        ordinal = _parse_image_ref_ordinal(ordinal_match.group(1))
        if ordinal:
            return _pick_image_rows_by_indices(rows, [ordinal], limit=limit, binding_mode='exact', binding_desc=f'explicit:nth:{ordinal}')
    return []


def _reuse_previous_exact_image_reference(messages: list, *, user_text: str = '', limit: int = 4, endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[dict]:
    if not _looks_like_deictic_image_followup(user_text):
        return []
    rows_messages = list(messages or [])
    current_norm = re.sub(r'\s+', ' ', str(user_text or '').strip().lower())
    for end in range(len(rows_messages) - 1, -1, -1):
        m = rows_messages[end]
        if not isinstance(m, dict) or str(m.get('role') or '').strip() != 'user':
            continue
        prev_text = _image_anchor_message_text(m)
        prev_norm = re.sub(r'\s+', ' ', str(prev_text or '').strip().lower())
        if not prev_norm or prev_norm == current_norm:
            continue
        resolved = _resolve_explicit_image_reference_items(rows_messages[:end + 1], user_text=prev_text, limit=limit, endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
        if resolved:
            tagged: list[dict] = []
            for row in resolved[:limit]:
                item = dict(row or {})
                item['binding_mode'] = 'exact_followup'
                item['binding_desc'] = f'followup_of:{prev_text[:80]}'
                tagged.append(item)
            return tagged[:limit]
    return []


def _recent_image_anchor_items(messages: list, *, user_text: str = '', limit: int = 4, endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[dict]:
    exact_rows = _resolve_explicit_image_reference_items(messages or [], user_text=user_text, limit=limit, endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    if exact_rows:
        return exact_rows[:limit]
    followup_rows = _reuse_previous_exact_image_reference(messages or [], user_text=user_text, limit=limit, endpoint_mode=endpoint_mode, allow_legacy=allow_legacy)
    if followup_rows:
        return followup_rows[:limit]
    return []


def _build_existing_image_analysis_visual_ctx(messages: list, *, user_text: str = '', image_ref: str = '', model: str | None = None, client_override=None, decision: dict | None = None, limit: int = 4, endpoint_mode: str = '', allow_legacy: bool | None = None) -> dict | None:
    if not str(image_ref or '').strip():
        return None
    resolved_endpoint_mode = _visual_endpoint_mode_normalize(endpoint_mode) or _visual_current_endpoint_mode(client_override)
    rows = _resolve_image_ref_reference_items(messages or [], image_ref=image_ref, user_text=user_text, limit=limit, endpoint_mode=resolved_endpoint_mode, allow_legacy=allow_legacy)
    if not rows:
        return None

    transcription_request = _is_image_text_transcription_request(user_text)
    urls: list[str] = []
    hints: list[str] = []
    binding_mode = str((rows[0] or {}).get('binding_mode') or 'recent').strip() or 'recent'
    binding_desc = str((rows[0] or {}).get('binding_desc') or '').strip()
    attachment_keys: list[str] = []
    source_roles: list[str] = []
    group_ids: list[str] = []
    resolved_image_ref = str(image_ref or '').strip()
    all_rows = _collect_context_image_items(messages or [], roles=('user', 'assistant', 'tool'), endpoint_mode=resolved_endpoint_mode, allow_legacy=allow_legacy)
    ordinal_by_key: dict[str, int] = {}
    for pos, row in enumerate(all_rows, 1):
        key = str(row.get('attachment_key') or row.get('url') or '').strip()
        if key and key not in ordinal_by_key:
            ordinal_by_key[key] = pos

    for pos, row in enumerate(rows, 1):
        item = dict(row.get('item') or {})
        raw_url = str(row.get('url') or '').strip()
        attachment_key = str(row.get('attachment_key') or _image_item_attachment_key(item) or raw_url).strip()
        if attachment_key and attachment_key not in attachment_keys:
            attachment_keys.append(attachment_key)
        if raw_url and raw_url not in urls:
            urls.append(raw_url)
        source_role = str(row.get('role') or row.get('source_role') or '').strip()
        if source_role and source_role not in source_roles:
            source_roles.append(source_role)
        for gid in _image_row_group_ids(row):
            if gid and gid not in group_ids:
                group_ids.append(gid)
        if not resolved_image_ref and attachment_key:
            ordinal = ordinal_by_key.get(attachment_key)
            if ordinal:
                resolved_image_ref = f'img_{ordinal}'
        label = _image_prompt_label(item, idx=pos)
        local_text = _image_prompt_ocr_text(item)
        data_url = ''
        try:
            data_url = _normalize_image_input_to_data_url(raw_url) or ''
        except Exception:
            data_url = ''
        best_text = str(local_text or '').strip()
        source_tag = 'ocr'
        screenshot_like = _is_probable_chat_screenshot_item(item, data_url=data_url) if data_url else _is_probable_chat_screenshot_item(item, data_url='')
        nested_media = None
        if screenshot_like and data_url:
            try:
                nested_media = _find_screenshot_embedded_media_crop(_data_url_to_pil_image(data_url))
            except Exception:
                nested_media = None
        nested_coverage = float((nested_media or {}).get('coverage') or 0.0)
        symbol_dense = _looks_symbol_dense_text(best_text)
        should_upgrade = _should_upgrade_image_text_hint(item, text=best_text, data_url=data_url) or transcription_request
        if data_url and should_upgrade:
            upgraded = _extract_visual_text_hint_with_model(model, data_url, existing_text=best_text, item=item, client_override=client_override)
            upgraded_text = str((upgraded or {}).get('text') or '').strip()
            if transcription_request:
                picked = _pick_better_visual_text_hint(
                    {'text': best_text, 'kind': '', 'source': source_tag},
                    upgraded,
                    symbol_dense=bool(symbol_dense or _looks_symbol_dense_text(upgraded_text)),
                )
                picked_text = str((picked or {}).get('text') or '').strip()
                if picked_text:
                    best_text = picked_text
                    if picked_text == upgraded_text:
                        source_tag = 'vision'
            elif _image_text_hint_score(upgraded_text) >= max(_image_text_hint_score(best_text) * 1.1, 110.0):
                best_text = upgraded_text
                source_tag = 'vision'
        if not best_text and local_text:
            best_text = str(local_text or '').strip()
            source_tag = 'ocr'

        if screenshot_like and transcription_request:
            safe_threshold = 360.0 if nested_coverage < 0.22 else 280.0
            if _image_text_hint_score(best_text) < safe_threshold:
                hints.append(
                    f'{label} 提醒：这是一张聊天/页面截图，里面真正要读的原图区域偏小或不够清晰。'
                    '当前无法稳定逐字转写，请优先直接查看原始图片；不要根据截图里的旧回答或壳层文字臆断题目原文。'
                )
                continue

        if best_text:
            prefix = f'{label} 高可信视觉转写：' if source_tag == 'vision' else f'{label} 识别文字：'
            hints.append(prefix + "\n" + truncate_text(best_text, max_chars=1500))
    if not urls:
        return None
    return {
        'intent': 'existing_image_analysis',
        'decision': dict(decision or {'intent': 'existing_image_analysis', 'reason': 'explicit_or_resolved_image_ref'}),
        'urls': urls[:limit],
        'text_hints': hints[:limit],
        'binding_mode': binding_mode,
        'binding_desc': binding_desc,
        'attachment_keys': attachment_keys[:limit],
        'resolved_image_ref': resolved_image_ref,
        'resolved_attachment_keys': attachment_keys[:limit],
        'resolved_source_roles': source_roles[:limit],
        'resolved_group_ids': group_ids[:limit],
        'endpoint_mode': resolved_endpoint_mode,
        'api_endpoint_mode': resolved_endpoint_mode,
        'rows': [dict(r or {}) for r in rows[:limit]],
    }

def _looks_like_existing_image_analysis(user_text: str, messages: list) -> bool:
    t = str(user_text or '').strip().lower()
    if not t:
        return False
    has_recent_images = bool(_find_recent_context_image_urls(messages or [], limit=1))
    if not has_recent_images:
        return False
    deictic_patterns = [
        r'这张图', r'这张图片', r'这个图片', r'上面这张', r'下面这张', r'刚才那张', r'上一张', r'前面那张',
        r'这图', r'这几张', r'这两张', r'这些图', r'图片里', r'图里', r'照片里', r'截图里',
        r'图中', r'画面里', r'上图', r'下图', r'左边这张', r'右边这张', r'第一张', r'第二张',
        r'分析这张', r'解释这张', r'这是什么意思', r'看图'
    ]
    analysis_patterns = [
        r'怎么拍', r'如何拍', r'拍的', r'构图', r'光线', r'参数', r'后期'
    ]
    text_followup_patterns = [
        r'题目内容', r'题目是什?么', r'第\s*\d+(?:\.\d+)?\s*题', r'原题', r'把题目发我', r'把题发我',
        r'发我一遍', r'抄一下', r'读出来', r'识别一下', r'图里写了什么', r'图片里写了什么',
        r'截图里写了什么', r'文字内容', r'内容是什?么', r'这题', r'这一题', r'那题', r'那一题'
    ]
    return any(re.search(p, t, flags=re.I) for p in (deictic_patterns + analysis_patterns + text_followup_patterns))
