# Image task planner and visual prompt helpers. Loaded before tool result compression and chat orchestration.

def _planner_safe_text(text: str, max_len: int = 1200) -> str:
    s = str(text or '')
    s = re.sub(r'data:image/[^\s)\]]+', '[image]', s, flags=re.I)
    s = re.sub(r'https?://[^\s)\]]+', lambda m: m.group(0)[:180], s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:max_len]


def _planner_safe_raw_output_text(text: str, max_len: int = 24000) -> str:
    """Safe text for command stdout/stderr while preserving raw terminal layout.

    The generic planner sanitizer intentionally collapses whitespace for prompts,
    OCR and snippets.  Do not use that for sandbox_run stdout/stderr: command
    output is evidence, so tabs/newlines/leading spaces and paths such as
    /mnt/data/file must stay byte-for-text faithful except for hard truncation
    and large data-url/URL shortening.
    """
    s = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    s = re.sub(r'data:image/[^\s)\]]+', '[image]', s, flags=re.I)
    s = re.sub(r'https?://[^\s)\]]+', lambda m: m.group(0)[:180], s)
    limit = max(2000, int(max_len or 0))
    if len(s) <= limit:
        return s
    keep_head = max(800, limit // 2)
    keep_tail = max(400, limit - keep_head - 100)
    omitted = max(0, len(s) - keep_head - keep_tail)
    return s[:keep_head] + f'\n\n...[已截断 {omitted} 个字符]...\n\n' + s[-keep_tail:]


def _image_prompt_label(item: dict | None = None, idx: int = 0) -> str:
    label = str((item or {}).get('filename') or '').strip()
    if label:
        return label
    return f'图片{idx}' if idx > 0 else '图片'


def _image_prompt_ocr_text(item: dict | None = None) -> str:
    return str((item or {}).get('_ocr_text') or (item or {}).get('ocr_text') or (item or {}).get('text') or '').strip()


def _looks_like_chat_ui_ocr_text(text: str) -> bool:
    s = str(text or '').strip()
    if not s:
        return False
    compact = re.sub(r'\s+', '', s)
    if not compact:
        return False
    lower = s.lower()
    marker_hits = 0
    markers = [
        'chatgpt', 'assistant', 'user', '/api3/', 'chat_async', 'chat_stream',
        '本次耗时', '发送', '重试', '继续', '复制', '对话', '回复', '模型', 'gpt-',
    ]
    for marker in markers:
        if marker in lower or marker in s:
            marker_hits += 1
    rows = [ln.strip() for ln in re.split(r'\r?\n+', s) if ln.strip()]
    if 'chatgpt' in lower:
        return True
    if marker_hits >= 2:
        return True
    if marker_hits >= 1 and len(compact) >= 140 and len(rows) >= 3:
        return True
    return False


def _inspect_image_data_url_for_prompt(data_url: str) -> dict:
    meta = {'width': 0, 'height': 0, 'pixels': 0}
    raw_url = str(data_url or '').strip()
    if not raw_url.lower().startswith('data:image/'):
        return meta
    try:
        _head, b64 = raw_url.split('base64,', 1)
        raw = base64.b64decode((b64 or '').strip(), validate=False)
        from PIL import Image  # type: ignore
        with Image.open(io.BytesIO(raw)) as img:
            w, h = img.size
        meta['width'] = int(w or 0)
        meta['height'] = int(h or 0)
        meta['pixels'] = int(max(0, int(w or 0)) * max(0, int(h or 0)))
    except Exception:
        return meta
    return meta


def _is_probable_chat_screenshot_item(item: dict | None = None, *, data_url: str = '') -> bool:
    ocr_text = _image_prompt_ocr_text(item)
    ui_text_like = _looks_like_chat_ui_ocr_text(ocr_text)
    if not data_url:
        return ui_text_like
    meta = _inspect_image_data_url_for_prompt(data_url)
    w = int(meta.get('width') or 0)
    h = int(meta.get('height') or 0)
    pixels = int(meta.get('pixels') or 0)
    portrait_screenish = bool(w > 0 and h >= max(int(w * 1.35), 1100))
    wide_screenish = bool(h > 0 and w >= max(int(h * 1.15), 1200))
    if ui_text_like and pixels >= 450000 and (portrait_screenish or wide_screenish):
        return True
    return ui_text_like and (portrait_screenish or wide_screenish)


def _build_image_text_hint_for_model(item: dict | None = None, *, idx: int = 0, allow_images: bool = False, data_url: str = '') -> tuple[str, bool]:
    label = _image_prompt_label(item, idx=idx)
    ocr_text = _image_prompt_ocr_text(item)
    screenshot_like = _is_probable_chat_screenshot_item(item, data_url=data_url)
    if not ocr_text:
        return '', screenshot_like
    if screenshot_like:
        if allow_images:
            return '', True
        return f'{label}（聊天/页面截图，OCR 低可信，仅供参考）：\n{truncate_text(ocr_text, max_chars=260)}', True
    return f'{label} 识别文字：\n{truncate_text(ocr_text, max_chars=1200)}', False


def _chat_screenshot_guard_prompt() -> str:
    return (
        '以下附图中可能包含聊天/页面截图。理解用户问题时，请优先关注截图内真正的原始题图、文档、照片或表格区域；'
        '不要把界面里的旧回答、按钮、状态文字、模型名称或聊天记录当成题目原文或事实。'
    )


def _extract_image_text_hints_from_content(content, allow_images: bool = False) -> list[str]:
    hints: list[str] = []
    if not isinstance(content, list):
        return hints
    for idx, it in enumerate(content, 1):
        if not isinstance(it, dict) or it.get('type') != 'image_url':
            continue
        hint, _ = _build_image_text_hint_for_model(it, idx=idx, allow_images=allow_images, data_url='')
        if hint:
            hints.append(hint)
    return hints



def _build_visual_low_priority_hint_for_message(message: dict | None = None, *, max_images: int = 2, max_chars: int = 160) -> str:
    m = message if isinstance(message, dict) else {}
    content = m.get('content')
    if isinstance(content, dict) and str(content.get('_kind') or '').strip() == 'image_reply':
        content = _image_reply_content_to_image_url_parts(content)
    if not isinstance(content, list):
        return ''
    lines: list[str] = []
    screenshot_hits = 0
    for idx, it in enumerate(content, 1):
        if not isinstance(it, dict) or it.get('type') != 'image_url':
            continue
        label = _image_prompt_label(it, idx=idx)
        ocr_text = _planner_safe_text(_image_prompt_ocr_text(it), max_len=max_chars)
        screenshot_like = _is_probable_chat_screenshot_item(it, data_url='')
        if screenshot_like:
            screenshot_hits += 1
            if ocr_text:
                lines.append(f'{label}: 聊天/页面截图，OCR低可信；摘要 {ocr_text[:max(60, min(max_chars, 120))]}')
            else:
                lines.append(f'{label}: 聊天/页面截图，OCR低可信')
        elif ocr_text:
            lines.append(f'{label}: {ocr_text}')
        else:
            lines.append(f'{label}: 用户附图')
        if len(lines) >= max(1, int(max_images or 2)):
            break
    if not lines:
        return ''
    header = f'含{len(lines)}张图片'
    if screenshot_hits and screenshot_hits == len(lines):
        header += '（偏截图）'
    text = header + '；' + '；'.join(lines)
    return _planner_safe_text(text, max_len=max(120, min(int(max_chars or 160) * max(1, len(lines)) + 80, 420)))


def _build_recent_visual_low_priority_hint(messages: list | None = None, *, max_messages: int = 2, max_images_per_message: int = 2, max_chars: int = 160) -> str:
    rows: list[str] = []
    for m in reversed(messages or []):
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '').strip()
        if role not in ('user', 'assistant'):
            continue
        hint = _build_visual_low_priority_hint_for_message(m, max_images=max_images_per_message, max_chars=max_chars)
        if not hint:
            continue
        rows.append(f'{role}: {hint}')
        if len(rows) >= max(1, int(max_messages or 2)):
            break
    if not rows:
        return ''
    rows.reverse()
    return '\n'.join(rows)



def _build_recent_visual_dialogue_anchor_for_planning(messages: list | None = None, user_text: str = '', *, max_turns: int = 4, max_chars: int = 1200) -> str:
    """Compact nearby dialogue text for image-bound follow-up search planning.

    This is deliberately only context serialization: it does not decide whether to
    search or which image to use. It gives planner lanes the same continuity that
    the final answer lane often has, so a later message like “能上网查一下吗” can
    still inherit the previous image task subject instead of searching that short
    sentence literally.
    """
    rows: list[str] = []
    current_norm = re.sub(r'\s+', ' ', str(user_text or '').strip())
    for m in reversed(messages or []):
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '').strip().lower()
        if role not in {'user', 'assistant'}:
            continue
        try:
            text = _message_to_text_for_budget(m, include_images=False, include_image_text=True)
        except Exception:
            try:
                text = _msg_content_text(m.get('content')).strip()
            except Exception:
                text = ''
        text = re.sub(r'\s+', ' ', str(text or '').strip())
        if not text:
            continue
        if role == 'user' and current_norm and text == current_norm:
            continue
        try:
            visual_hint = _build_visual_low_priority_hint_for_message(m, max_images=2, max_chars=180)
        except Exception:
            visual_hint = ''
        if visual_hint and visual_hint not in text:
            text = (text + '；' if text else '') + f'图片线索：{visual_hint}'
        text = _normalize_search_planner_context_text(text, max_len=420)
        if not text:
            continue
        rows.append(f'{role}: {text}')
        if len(rows) >= max(1, int(max_turns or 4)):
            break
    rows.reverse()
    out = '\n'.join(rows).strip()
    try:
        max_chars_i = max(300, int(max_chars or 1200))
    except Exception:
        max_chars_i = 1200
    if len(out) > max_chars_i:
        out = out[-max_chars_i:]
    return out


def _build_visual_reference_planning_context(messages: list | None = None, user_text: str = '', *, max_items: int = 3, max_chars: int = 2200) -> dict:
    """Return a compact, exact image-reference context for planning lanes.

    The image index already knows message order and explicit references such as
    “第一张图/第二张图/上一张”. This helper only serializes that existing evidence so
    tool prefetch and web-query planning use the same target image as the final
    visual-answer lane, instead of silently falling back to the latest image.
    """
    rows: list[dict] = []
    try:
        rows = _recent_image_anchor_items(messages or [], user_text=user_text, limit=max(1, int(max_items or 3))) or []
    except Exception:
        rows = []
    if not rows:
        return {'text': '', 'rows': [], 'urls': [], 'binding_mode': '', 'binding_desc': ''}

    all_rows: list[dict] = []
    try:
        all_rows = _collect_context_image_items(messages or [], roles=('user', 'assistant', 'tool')) or []
    except Exception:
        all_rows = []
    ordinal_by_key: dict[str, int] = {}
    for pos, row in enumerate(all_rows, 1):
        key = str(row.get('attachment_key') or row.get('url') or '').strip()
        if key and key not in ordinal_by_key:
            ordinal_by_key[key] = pos

    lines: list[str] = [
        '【图片引用上下文】',
        '来源：后端会话图片索引；用于工具预判和搜索词补全，不是硬规则。',
        '如果用户说第一张/第二张/上一张/刚才那张，应优先按这里的绑定对象理解，而不是默认最近图片。',
    ]
    binding_mode = str((rows[0] or {}).get('binding_mode') or '').strip()
    binding_desc = str((rows[0] or {}).get('binding_desc') or '').strip()

    for local_pos, row in enumerate(rows[:max(1, int(max_items or 3))], 1):
        item = dict(row.get('item') or {})
        url = str(row.get('url') or '').strip()
        key = str(row.get('attachment_key') or _image_item_attachment_key(item) or url).strip()
        global_pos = ordinal_by_key.get(key)
        global_label = f'图{global_pos}' if global_pos else f'选中图{local_pos}'
        role = str(row.get('role') or '').strip() or 'unknown'
        msg_idx = row.get('message_index')
        img_idx = row.get('idx')
        row_binding = str(row.get('binding_mode') or binding_mode or 'recent').strip() or 'recent'
        row_desc = str(row.get('binding_desc') or binding_desc or '').strip()
        label = _image_prompt_label(item, idx=local_pos)
        try:
            ocr_text = _planner_safe_text(_image_prompt_ocr_text(item), max_len=560)
        except Exception:
            ocr_text = ''
        line = f'{global_label}: role={role}; message_index={msg_idx}; image_index_in_message={img_idx}; binding={row_binding}'
        if row_desc:
            line += f'; binding_desc={row_desc}'
        if label and label != global_label:
            line += f'; label={label}'
        lines.append(line)
        if ocr_text:
            lines.append(f'{global_label} 可见文字/OCR：{ocr_text}')
        else:
            lines.append(f'{global_label} 暂无可靠文字线索；若用户要求查询图中对象，应结合图片本身识别主体。')

    try:
        dialogue_anchor = _build_recent_visual_dialogue_anchor_for_planning(messages or [], user_text=user_text, max_turns=4, max_chars=1100)
    except Exception:
        dialogue_anchor = ''
    if dialogue_anchor:
        lines.append('最近图片/视觉相关对话锚点：')
        lines.append(dialogue_anchor)

    text = '\n'.join([str(x).strip() for x in lines if str(x).strip()]).strip()
    try:
        max_chars_i = max(500, int(max_chars or 2200))
    except Exception:
        max_chars_i = 2200
    if len(text) > max_chars_i:
        text = text[:max_chars_i] + '\n...【图片引用上下文过长，已截断】'
    return {
        'text': text,
        'rows': rows[:max(1, int(max_items or 3))],
        'urls': [],
        'binding_mode': binding_mode,
        'binding_desc': binding_desc,
    }




def _image_mode_role_prefix(role: str = '') -> str:
    raw = str(role or '').strip().lower()
    if raw == 'user':
        return 'user'
    if raw == 'assistant':
        return 'assistant'
    if raw == 'tool':
        return 'tool'
    return raw or 'image'


def _image_mode_role_label_zh(role: str = '') -> str:
    raw = str(role or '').strip().lower()
    if raw == 'user':
        return '用户图'
    if raw == 'assistant':
        return '助手图'
    if raw == 'tool':
        return '工具图'
    return '图片'


def _image_mode_enrich_rows_with_order(rows: list[dict] | None = None, messages: list | None = None) -> list[dict]:
    base_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
    if not base_rows:
        return []
    base_rows.sort(key=_image_row_order_key)
    role_counts: dict[str, int] = {}
    enriched: list[dict] = []
    for global_pos, row in enumerate(base_rows, 1):
        role = str(row.get('role') or row.get('source_role') or '').strip().lower() or 'unknown'
        role_counts[role] = int(role_counts.get(role, 0)) + 1
        role_pos = role_counts[role]
        prefix = _image_mode_role_prefix(role)
        label_zh = f'{_image_mode_role_label_zh(role)}{role_pos}'
        item = dict(row.get('item') or {})
        key = str(row.get('attachment_key') or _image_item_attachment_key(item) or row.get('url') or '').strip()
        out = dict(row)
        out['global_image_index'] = global_pos
        out['role_image_index'] = role_pos
        out['role_image_id'] = f'{prefix}_img_{role_pos}'
        out['role_label'] = label_zh
        out['global_label'] = f'图{global_pos}'
        out['attachment_key'] = key
        out['created_at_ms'] = int(float(out.get('created_at_ms') or out.get('order_ts_ms') or 0)) if str(out.get('created_at_ms') or out.get('order_ts_ms') or '').strip() else 0
        out['order_ts_ms'] = int(float(out.get('order_ts_ms') or out.get('created_at_ms') or 0)) if str(out.get('order_ts_ms') or out.get('created_at_ms') or '').strip() else 0
        out['order_seq'] = int(float(out.get('order_seq') or out.get('image_seq') or 0)) if str(out.get('order_seq') or out.get('image_seq') or '').strip() else 0
        enriched.append(out)
    return enriched


def _image_mode_row_lookup_meta(all_rows: list[dict] | None = None) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for row in all_rows or []:
        if not isinstance(row, dict):
            continue
        item = dict(row.get('item') or {})
        keys = [
            row.get('attachment_key'),
            _image_item_attachment_key(item),
            row.get('url'),
        ]
        for raw_key in keys:
            key = str(raw_key or '').strip()
            if key and key not in lookup:
                lookup[key] = dict(row)
    return lookup



def _image_mode_candidate_rows(messages: list | None = None, *, user_text: str = '', limit: int = 6) -> list[dict]:
    """Collect a compact image candidate set for the secondary image-task planner.

    This keeps the first tool router coarse (just entering the image lane) and lets
    the image-mode planner decide which image is the real edit target, which one is
    only a reference, and which ones should be ignored.
    """
    try:
        limit_i = max(1, min(int(limit or 6), 8))
    except Exception:
        limit_i = 6
    seeded: list[dict] = []
    try:
        seeded = _recent_image_anchor_items(messages or [], user_text=user_text, limit=limit_i) or []
    except Exception:
        seeded = []
    try:
        all_rows_raw = _collect_context_image_items(messages or [], roles=('user', 'assistant', 'tool')) or []
    except Exception:
        all_rows_raw = []
    all_rows = _image_mode_enrich_rows_with_order(all_rows_raw, messages or [])
    order_meta = _image_mode_row_lookup_meta(all_rows)
    try:
        latest_user_message_index = max(i for i, m in enumerate(messages or []) if isinstance(m, dict) and str(m.get('role') or '').strip().lower() == 'user')
    except Exception:
        latest_user_message_index = None

    merged: list[dict] = []
    seen: set[str] = set()
    for row in [*(seeded or []), *list(reversed(all_rows or []))]:
        if not isinstance(row, dict):
            continue
        # Keep current-turn user images in the image candidate index.
        # They are still imported through the sandbox file plane before use, but
        # image edit/reference generation needs a selectable stable id so the
        # same model can choose the uploaded image instead of falling into a
        # sandbox-analysis-only answer.
        item = dict(row.get('item') or {})
        key = str(row.get('attachment_key') or _image_item_attachment_key(item) or row.get('url') or '').strip()
        if not key or key in seen:
            continue
        merged_row = dict(row)
        meta = order_meta.get(key) or order_meta.get(str(row.get('url') or '').strip()) or {}
        if meta:
            for meta_key in ('global_image_index', 'role_image_index', 'role_image_id', 'role_label', 'global_label', 'message_index', 'created_at_ms', 'order_ts_ms', 'image_seq', 'order_seq', 'operation', 'source_role', 'parent_image_id', 'source_image_ids', 'derived_from'):
                if meta.get(meta_key) is not None and merged_row.get(meta_key) in (None, ''):
                    merged_row[meta_key] = meta.get(meta_key)
            if not merged_row.get('attachment_key'):
                merged_row['attachment_key'] = key
        seen.add(key)
        merged.append(merged_row)
        if len(merged) >= limit_i:
            break

    out: list[dict] = []
    current_user_image_count = 0
    for pos, row in enumerate(merged[:limit_i], 1):
        item = dict(row.get('item') or {})
        attachment_key = str(row.get('attachment_key') or _image_item_attachment_key(item) or row.get('url') or '').strip()
        raw_url = str(row.get('url') or '').strip()
        role = str(row.get('role') or '').strip() or 'unknown'
        try:
            is_current_user_row = bool(role == 'user' and latest_user_message_index is not None and int(row.get('message_index')) == int(latest_user_message_index))
        except Exception:
            is_current_user_row = False
        if is_current_user_row:
            current_user_image_count += 1
            current_user_image_no = current_user_image_count
        else:
            current_user_image_no = 0
        current_user_image_id = f'current_user_image_{current_user_image_no}' if is_current_user_row else ''
        role_image_id = str(row.get('role_image_id') or f'{_image_mode_role_prefix(role)}_img_{int(row.get("role_image_index") or pos)}').strip()
        stable_image_id = str(current_user_image_id or row.get('stable_image_id') or role_image_id or f'img_{pos}').strip()
        role_label = str(row.get('role_label') or (f'当前用户图{current_user_image_no}' if is_current_user_row else f'{_image_mode_role_label_zh(role)}{int(row.get("role_image_index") or pos)}')).strip()
        global_index = row.get('global_image_index')
        global_label = str(row.get('global_label') or (f'图{global_index}' if global_index else f'图{pos}')).strip()
        label = _image_prompt_label(item, idx=pos) or role_label or global_label or f'图{pos}'
        try:
            ocr_text = _planner_safe_text(_image_prompt_ocr_text(item), max_len=220)
        except Exception:
            ocr_text = ''
        raw_source_image_ids = row.get('source_image_ids') or row.get('derived_from') or []
        if isinstance(raw_source_image_ids, str):
            source_image_ids = [raw_source_image_ids]
        elif isinstance(raw_source_image_ids, list):
            source_image_ids = [str(x or '').strip() for x in raw_source_image_ids if str(x or '').strip()]
        else:
            source_image_ids = []
        parent_image_id = str(row.get('parent_image_id') or '').strip()
        if parent_image_id and parent_image_id not in source_image_ids:
            source_image_ids.insert(0, parent_image_id)
        alias_ids = []
        alias_seed = [f'img_{pos}', stable_image_id, role_image_id, role_label, global_label, attachment_key, raw_url]
        if current_user_image_id:
            alias_seed.extend([current_user_image_id, f'本轮图片{current_user_image_no}', f'当前图片{current_user_image_no}', f'上传图{current_user_image_no}'])
        for val in alias_seed:
            val = str(val or '').strip()
            if val and val not in alias_ids:
                alias_ids.append(val)
        summary_bits = [
            f'label={label}',
            f'candidate_id=img_{pos}',
            f'stable_image_id={stable_image_id}',
            f'role_image_id={role_image_id}',
            f'role_label={role_label}',
            f'global_order={global_index if global_index is not None else pos}',
            f'recency_rank={pos}',
            f'role={role}',
            f'created_at_ms={row.get("order_ts_ms") or row.get("created_at_ms") or ""}',
            f'order_seq={row.get("order_seq") or row.get("image_seq") or ""}',
            f'operation={row.get("operation") or ""}',
            f'parent_image_id={parent_image_id}',
        ]
        if source_image_ids:
            summary_bits.append('derived_from=' + ','.join(source_image_ids[:6]))
        message_text = ''
        try:
            msg_idx = row.get('message_index')
            if msg_idx is not None and 0 <= int(msg_idx) < len(messages or []):
                msg_obj = (messages or [])[int(msg_idx)]
                message_text = _planner_safe_text(_image_anchor_message_text(msg_obj), max_len=260)
        except Exception:
            message_text = ''
        if row.get('message_index') is not None:
            summary_bits.append(f'message_index={row.get("message_index")}')
        if row.get('idx') is not None:
            summary_bits.append(f'image_index_in_message={row.get("idx")}')
        if message_text:
            summary_bits.append(f'message_text={message_text}')
        binding_mode = str(row.get('binding_mode') or ('current_user_message' if is_current_user_row else '')).strip()
        binding_desc = str(row.get('binding_desc') or (f'current_user_message_image:{row.get("idx") or pos}' if is_current_user_row else '')).strip()
        if binding_mode:
            summary_bits.append(f'binding={binding_mode}')
        if binding_desc:
            summary_bits.append(f'binding_desc={binding_desc}')
        if ocr_text:
            summary_bits.append(f'ocr={ocr_text}')
        out.append({
            'image_id': f'img_{pos}',
            'stable_image_id': stable_image_id,
            'current_user_image_id': current_user_image_id,
            'role_image_id': role_image_id,
            'role_label': role_label,
            'alias_ids': alias_ids,
            'global_image_index': global_index,
            'global_label': global_label,
            'attachment_key': attachment_key,
            'url': raw_url,
            'role': role,
            'source_role': str(row.get('source_role') or role).strip() or role,
            'operation': str(row.get('operation') or '').strip(),
            'parent_image_id': parent_image_id,
            'source_image_ids': source_image_ids,
            'derived_from': source_image_ids,
            'created_at_ms': row.get('order_ts_ms') or row.get('created_at_ms'),
            'order_ts_ms': row.get('order_ts_ms') or row.get('created_at_ms'),
            'image_seq': row.get('order_seq') or row.get('image_seq'),
            'order_seq': row.get('order_seq') or row.get('image_seq'),
            'message_index': row.get('message_index'),
            'idx': row.get('idx'),
            'recency_rank': pos,
            'message_text': message_text,
            'binding_mode': binding_mode,
            'binding_desc': binding_desc,
            'summary': '; '.join([str(x).strip() for x in summary_bits if str(x).strip()]),
            'item': item,
        })
    return out


def _resolve_image_mode_selected_rows(raw_values, candidate_rows: list[dict] | None = None, *, limit: int = 4) -> list[dict]:
    rows = [dict(r) for r in (candidate_rows or []) if isinstance(r, dict)]
    by_image_id = {str(r.get('image_id') or '').strip(): r for r in rows if str(r.get('image_id') or '').strip()}
    by_stable_image_id = {str(r.get('stable_image_id') or '').strip(): r for r in rows if str(r.get('stable_image_id') or '').strip()}
    by_role_image_id = {str(r.get('role_image_id') or '').strip(): r for r in rows if str(r.get('role_image_id') or '').strip()}
    by_role_label = {str(r.get('role_label') or '').strip(): r for r in rows if str(r.get('role_label') or '').strip()}
    by_global_label = {str(r.get('global_label') or '').strip(): r for r in rows if str(r.get('global_label') or '').strip()}
    by_attachment_key = {str(r.get('attachment_key') or '').strip(): r for r in rows if str(r.get('attachment_key') or '').strip()}
    by_url = {str(r.get('url') or '').strip(): r for r in rows if str(r.get('url') or '').strip()}
    by_alias: dict[str, dict] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        aliases = r.get('alias_ids') if isinstance(r.get('alias_ids'), list) else []
        for alias in aliases:
            key = str(alias or '').strip()
            if key and key not in by_alias:
                by_alias[key] = r

    values = raw_values if isinstance(raw_values, list) else ([raw_values] if raw_values else [])
    out: list[dict] = []
    seen: set[str] = set()
    for raw in values:
        token = str(raw or '').strip()
        if not token:
            continue
        row = by_image_id.get(token) or by_stable_image_id.get(token) or by_role_image_id.get(token) or by_role_label.get(token) or by_global_label.get(token) or by_attachment_key.get(token) or by_url.get(token) or by_alias.get(token)
        if not row:
            continue
        key = str(row.get('attachment_key') or row.get('url') or row.get('image_id') or '').strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
        if len(out) >= max(1, int(limit or 4)):
            break
    return out



def _apply_exact_bound_image_selection(plan: dict | None = None, messages: list | None = None, *, user_text: str = '', limit: int = 4) -> dict:
    """If the current user text already resolves to an exact image binding, keep the
    planner from drifting to another candidate.

    This reuses the existing image-index resolution result instead of introducing a
    new parallel rule system. It only corrects cases where the model selected a
    different image even though the current request explicitly bound a target such
    as "第2张"、"最后一张" or a deictic follow-up of such a request.
    """
    result = dict(plan or {})
    candidate_rows = [dict(r) for r in (result.get('candidate_rows') or []) if isinstance(r, dict)]
    if not candidate_rows:
        return result
    try:
        exact_rows = _recent_image_anchor_items(messages or [], user_text=user_text, limit=limit) or []
    except Exception:
        exact_rows = []
    if not exact_rows:
        return result
    binding_mode = str((exact_rows[0] or {}).get('binding_mode') or '').strip().lower()
    if binding_mode not in {'exact', 'exact_followup'}:
        return result

    candidate_by_key: dict[str, dict] = {}
    for row in candidate_rows:
        key = str(row.get('attachment_key') or row.get('url') or '').strip()
        if key and key not in candidate_by_key:
            candidate_by_key[key] = dict(row)

    anchored_rows: list[dict] = []
    seen: set[str] = set()
    for row in exact_rows:
        key = str(row.get('attachment_key') or row.get('url') or '').strip()
        if not key or key in seen:
            continue
        seen.add(key)
        anchored = candidate_by_key.get(key) or dict(row)
        anchored['binding_mode'] = binding_mode
        anchored['binding_desc'] = str((row or {}).get('binding_desc') or anchored.get('binding_desc') or '').strip()
        anchored_rows.append(anchored)
        if len(anchored_rows) >= max(1, int(limit or 4)):
            break
    if not anchored_rows:
        return result

    def _rows_overlap(a_rows: list[dict] | None, b_rows: list[dict] | None) -> bool:
        a = {str((r or {}).get('attachment_key') or (r or {}).get('url') or '').strip() for r in (a_rows or []) if str((r or {}).get('attachment_key') or (r or {}).get('url') or '').strip()}
        b = {str((r or {}).get('attachment_key') or (r or {}).get('url') or '').strip() for r in (b_rows or []) if str((r or {}).get('attachment_key') or (r or {}).get('url') or '').strip()}
        return bool(a and b and (a & b))

    task_type = str(result.get('task_type') or '').strip().lower()
    changed = False

    if task_type == 'existing_image_analysis':
        if not _rows_overlap(result.get('edit_target_rows'), anchored_rows):
            result['edit_target_rows'] = [dict(r) for r in anchored_rows]
            changed = True
    elif task_type == 'image_edit':
        if not _rows_overlap(result.get('edit_target_rows'), anchored_rows):
            result['edit_target_rows'] = [dict(r) for r in anchored_rows[:1]]
            changed = True
    elif task_type in {'reference_generate', 'variation'}:
        if not _rows_overlap(result.get('reference_rows'), anchored_rows):
            result['reference_rows'] = [dict(r) for r in anchored_rows]
            changed = True
    elif task_type == 'reference_edit':
        target_rows = [dict(r) for r in (result.get('edit_target_rows') or []) if isinstance(r, dict)]
        if target_rows:
            if not _rows_overlap(result.get('reference_rows'), anchored_rows):
                result['reference_rows'] = [dict(r) for r in anchored_rows]
                changed = True
        else:
            if not _rows_overlap(result.get('edit_target_rows'), anchored_rows):
                result['edit_target_rows'] = [dict(r) for r in anchored_rows[:1]]
                changed = True

    if changed:
        selected_rows: list[dict] = []
        seen2: set[str] = set()
        for group in (result.get('edit_target_rows') or [], result.get('reference_rows') or []):
            for row in group:
                key = str((row or {}).get('attachment_key') or (row or {}).get('url') or (row or {}).get('image_id') or '').strip()
                if not key or key in seen2:
                    continue
                seen2.add(key)
                selected_rows.append(dict(row))
        result['selected_rows'] = selected_rows
        raw_reason = str(result.get('reason') or '').strip()
        suffix = 'exact_image_binding_kept'
        result['reason'] = (raw_reason + '; ' + suffix) if raw_reason else suffix
    return result



def _build_image_mode_recent_task_dialogue(messages: list | None = None, user_text: str = '', *, max_turns: int = 8, max_chars: int = 1800) -> str:
    """Serialize recent image-task dialogue for the image-mode planner.

    This is context only. It does not decide task type or bind images. The second
    planner uses it to continue a pending image task when the user replies with a
    short constraint such as “全身的人物”.
    """
    rows: list[str] = []
    current_norm = re.sub(r'\s+', ' ', str(user_text or '').strip())
    for m in reversed(messages or []):
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '').strip().lower()
        if role not in {'user', 'assistant'}:
            continue
        try:
            text = _message_to_text_for_budget(m, include_images=False, include_image_text=True)
        except Exception:
            try:
                text = _msg_content_text(m.get('content')).strip()
            except Exception:
                text = ''
        text = re.sub(r'\s+', ' ', str(text or '').strip())
        if role == 'user' and current_norm and text == current_norm:
            continue
        if not text:
            continue
        try:
            visual_hint = _build_visual_low_priority_hint_for_message(m, max_images=2, max_chars=220)
        except Exception:
            visual_hint = ''
        if visual_hint:
            text = (text + '；' if text else '') + f'图片线索：{visual_hint}'
        rows.append(f'{role}: {_planner_safe_text(text, max_len=520)}')
        if len(rows) >= max(1, int(max_turns or 8)):
            break
    rows.reverse()
    out = '\n'.join(rows).strip()
    try:
        max_chars_i = max(600, int(max_chars or 1800))
    except Exception:
        max_chars_i = 1800
    if len(out) > max_chars_i:
        out = out[-max_chars_i:]
    return out

def _build_image_mode_planner_user_content(messages: list | None = None, user_text: str = '', *, candidate_rows: list[dict] | None = None, image_generation_settings: dict | None = None, max_images: int = 4) -> list:
    rows = [dict(r) for r in (candidate_rows or []) if isinstance(r, dict)]
    edit_enabled = False
    responses_native_image_inputs_enabled = False
    try:
        normalized_image_settings = _normalize_image_generation_settings(image_generation_settings) or {}
        edit_enabled = bool((normalized_image_settings or {}).get('edit', {}).get('enabled'))
        native_checker = globals().get('_image_generation_should_use_responses_native')
        responses_native_image_inputs_enabled = bool(native_checker(normalized_image_settings or {}, client_override=None)) if callable(native_checker) else False
    except Exception:
        edit_enabled = False
        responses_native_image_inputs_enabled = False
    source_image_input_enabled = bool(edit_enabled or responses_native_image_inputs_enabled)
    try:
        dialogue_anchor = _build_recent_visual_dialogue_anchor_for_planning(messages or [], user_text=user_text, max_turns=6, max_chars=1400)
    except Exception:
        dialogue_anchor = ''
    try:
        recent_task_dialogue = _build_image_mode_recent_task_dialogue(messages or [], user_text=user_text, max_turns=8, max_chars=2000)
    except Exception:
        recent_task_dialogue = ''

    grouped_candidates: dict[str, list[str]] = {'current_user': [], 'previous_user': [], 'assistant': [], 'tool': [], 'other': []}
    for row in rows:
        candidate_id = str(row.get('image_id') or '').strip()
        stable_id = str(row.get('stable_image_id') or '').strip()
        role_id = str(row.get('role_image_id') or '').strip()
        role_label = str(row.get('role_label') or '').strip()
        global_label = str(row.get('global_label') or '').strip()
        role = str(row.get('role') or row.get('source_role') or '').strip().lower()
        binding_mode = str(row.get('binding_mode') or '').strip().lower()
        if role == 'user' and binding_mode == 'current_user_message':
            group_key = 'current_user'
        elif role == 'user':
            group_key = 'previous_user'
        elif role == 'assistant':
            group_key = 'assistant'
        elif role == 'tool':
            group_key = 'tool'
        else:
            group_key = 'other'
        aliases = ' / '.join([x for x in (stable_id, candidate_id, role_id, role_label, global_label) if x])
        derived = row.get('source_image_ids') or row.get('derived_from') or []
        if isinstance(derived, list) and derived:
            relation_text = '；derived_from=' + ','.join([str(x or '').strip() for x in derived if str(x or '').strip()][:6])
        else:
            relation_text = ''
        grouped_candidates.setdefault(group_key, []).append(f"- {aliases}: {str(row.get('summary') or '').strip()}{relation_text}")
    candidate_sections = []
    section_titles = [
        ('current_user', '当前用户本轮图片'),
        ('previous_user', '历史用户上传图片'),
        ('assistant', '助手生成/编辑图片'),
        ('tool', '工具/联网图片'),
        ('other', '其他图片'),
    ]
    for group_key, title in section_titles:
        vals = grouped_candidates.get(group_key) or []
        if vals:
            candidate_sections.append(title + ':\n' + '\n'.join(vals))
    candidate_text = '\n\n'.join(candidate_sections) if candidate_sections else 'none'
    contract_text = ''
    try:
        contract_builder = globals().get('prompt_contract_text')
        if callable(contract_builder):
            contract_text = str(contract_builder('image_task_planner', compact=True) or '').strip()
    except Exception:
        contract_text = ''

    planner_contract_text = contract_text or 'Prompt contract: image_task_planner.\n输出：只输出 JSON object。'
    text = f'''{planner_contract_text}

任务类型：
- text_to_image：纯文生图，不需要候选图。
- image_edit：编辑目标图。
- reference_generate：参考图生成新图。
- reference_edit：编辑目标图并参考其他图。
- variation：基于已有图重绘/变体。
- existing_image_analysis：只分析已有图，不生成。
- unclear：只有信息真的不足才用。

简洁约束：
- 纯文本画面需求可以直接 text_to_image，不需要候选图或参考图。
- 候选图片已经按“当前用户本轮图片 / 历史用户上传图片 / 助手生成或编辑图片 / 工具图片”分区；不同分区代表不同来源，需要按分区和关系字段区分。
- 优先使用 stable_image_id / role_image_id 这类稳定 ID 选图，候选顺序 img_1 只作为兜底候选号。
- selected_image_ids 表示本次任务实际用到的图片并集；edit_target_image_ids / reference_image_ids 只是按用途细分。
- 用户目标是改变已有图片时，绑定 edit_target_image_ids；缺少目标图才追问。
- 用户目标是参考某张图或沿用某张图人物/脸/风格来生成新图时，优先用 reference_generate，并把图片只放到 reference_image_ids。
- reference_edit 只在“明确有编辑目标图”且“另有参考图”时使用；不要把同一张图同时放到 edit_target_image_ids 和 reference_image_ids。
- 如果任务类型已经确定，就让列表与 task_type 保持一致：reference_generate 不要给 edit_target_image_ids；image_edit 至少要有 edit_target_image_ids；text_to_image 不依赖任何图片列表。
- 如果当前用户请求很短、像是在承接上一轮图片任务，请结合最近图片任务继承完整画面要求；不要把短承接语本身当作最终 prompt。
- 如果用户让你“根据/按/用/参考”某张候选图继续生成，但没有明确要求直接修改原图，应由你判断是否选择 reference_generate，并只把该图放到 reference_image_ids。
- 用户说重新生成/再来一张/继续，但本轮主体不足时，尽量继承最近图片任务；找不到可继承主题才追问。
- 候选图无关就忽略；历史图片不能覆盖当前目标。
- prompt 必须能直接交给图片模型执行；理由一句话。
- 图片输入能力：{'yes' if source_image_input_enabled else 'no'}；独立编辑 API：{'yes' if edit_enabled else 'no'}。只有图片输入能力不可用时，才因编辑/参考/变体提示开启或改文生图。

当前用户请求：
{str(user_text or '').strip()}

最近图片相关对话：
{dialogue_anchor or 'none'}

最近图片任务：
{recent_task_dialogue or 'none'}

候选图片：
{candidate_text}
'''

    parts = [{'type': 'text', 'text': text[:5500]}]
    for row in rows[:max(1, int(max_images or 4))]:
        image_id = str(row.get('image_id') or '').strip() or 'img'
        summary = str(row.get('summary') or '').strip()
        alias = ' / '.join([x for x in (str(row.get('stable_image_id') or '').strip(), image_id, str(row.get('role_image_id') or '').strip(), str(row.get('role_label') or '').strip(), str(row.get('global_label') or '').strip()) if x])
        parts.append({'type': 'text', 'text': f'候选图片 {alias}（仅作为图片模式二次编排的索引依据；真实图片内容必须后续按 ID 进入 sandbox 链路）：{summary}'[:800]})
    return parts


def _normalize_image_task_plan_structure(result: dict | None = None) -> dict:
    """Normalize planner output structurally without reinterpreting user semantics.

    This function does not decide task type from keywords. It only keeps the
    planner's chosen task_type and makes the selected image lists internally
    consistent with that task type.
    """
    res = dict(result or {})
    task_type = str(res.get('task_type') or '').strip().lower()

    def _dedupe_rows(rows: list[dict] | None) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        for row in (rows or []):
            if not isinstance(row, dict):
                continue
            item = dict(row)
            key = str(item.get('attachment_key') or item.get('url') or item.get('image_id') or '').strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _row_key(row: dict | None) -> str:
        return str((row or {}).get('attachment_key') or (row or {}).get('url') or (row or {}).get('image_id') or '').strip()

    edit_rows = _dedupe_rows(res.get('edit_target_rows'))
    reference_rows = _dedupe_rows(res.get('reference_rows'))
    ignore_rows = _dedupe_rows(res.get('ignore_rows'))
    selected_rows = _dedupe_rows(res.get('selected_rows'))

    if task_type == 'text_to_image':
        edit_rows = []
        reference_rows = []
        selected_rows = []
    elif task_type == 'reference_generate':
        if not reference_rows and edit_rows:
            reference_rows = [dict(r) for r in edit_rows]
        edit_rows = []
    elif task_type in {'image_edit', 'reference_edit'}:
        edit_keys = {_row_key(r) for r in edit_rows if _row_key(r)}
        if edit_keys:
            reference_rows = [dict(r) for r in reference_rows if _row_key(r) not in edit_keys]
    elif task_type == 'existing_image_analysis':
        if not edit_rows and reference_rows:
            edit_rows = [dict(reference_rows[0])]
        reference_rows = []

    if task_type != 'text_to_image':
        selected_rows = []
        seen_selected: set[str] = set()
        for group in (edit_rows, reference_rows):
            for row in group:
                key = _row_key(row)
                if not key or key in seen_selected:
                    continue
                seen_selected.add(key)
                selected_rows.append(dict(row))

    changed_reason = False
    if task_type == 'reference_generate' and res.get('edit_target_rows'):
        changed_reason = True
    elif task_type in {'image_edit', 'reference_edit'}:
        raw_edit_keys = {_row_key(r) for r in (res.get('edit_target_rows') or []) if _row_key(r)}
        raw_ref_keys = {_row_key(r) for r in (res.get('reference_rows') or []) if _row_key(r)}
        if raw_edit_keys & raw_ref_keys:
            changed_reason = True
    elif task_type == 'text_to_image' and ((res.get('edit_target_rows') or []) or (res.get('reference_rows') or [])):
        changed_reason = True

    res['edit_target_rows'] = edit_rows
    res['reference_rows'] = reference_rows
    res['ignore_rows'] = ignore_rows
    res['selected_rows'] = selected_rows
    if changed_reason:
        raw_reason = str(res.get('reason') or '').strip()
        suffix = 'task_structure_normalized'
        res['reason'] = ((raw_reason + '; ' + suffix) if raw_reason else suffix)[:160]
    return res

def _repair_unclear_image_generation_plan(result: dict | None = None, user_text: str = '', *, raw_plan: dict | None = None, candidate_rows: list[dict] | None = None) -> dict:
    """Repair an over-cautious image planner result.

    The image lane has already been selected. If the secondary planner returns
    `unclear` even though the latest user text is a standalone image prompt, do
    not require a reference image. Pure text-to-image is valid with zero
    candidates.
    """
    res = dict(result or {})
    task_type = str(res.get('task_type') or '').strip().lower()
    if task_type != 'unclear' and not bool(res.get('need_clarify')):
        return res

    candidate_rows_list = [dict(r) for r in (candidate_rows or []) if isinstance(r, dict)]
    if candidate_rows_list:
        return res

    raw_user = re.sub(r'\s+', ' ', str(user_text or '').strip())
    clean_user = str(_clean_image_subject(raw_user) or raw_user).strip()
    compact = re.sub(r'\s+', '', clean_user)
    if not compact:
        return res

    # Very short follow-ups like “重新生成一张 / 继续 / 再来一张” still need context.
    too_short_for_standalone = len(compact) < 8
    if too_short_for_standalone:
        return res

    prompt = str(res.get('prompt') or (raw_plan or {}).get('prompt') or '').strip()
    if (not prompt) or any(x in prompt for x in ('请补充', '缺少', '无法直接', '不能直接')):
        prompt = clean_user
    prompt = _planner_safe_text(prompt, max_len=1200).strip()
    if not prompt:
        return res

    res['task_type'] = 'text_to_image'
    res['prompt'] = prompt
    res['need_clarify'] = False
    res['clarify_question'] = ''
    res['edit_target_rows'] = []
    res['reference_rows'] = []
    res['selected_rows'] = []
    raw_reason = str(res.get('reason') or '').strip()
    suffix = 'unclear_repaired_to_text_to_image'
    res['reason'] = (raw_reason + '; ' + suffix)[:160] if raw_reason else suffix
    return res


def _plan_image_task_once(model: str, messages: list | None = None, user_text: str = '', *, image_generation_settings: dict | None = None, client_override=None) -> dict:
    """Secondary planner inside image mode.

    The first router only decides that the request belongs to the image lane. This
    function performs the second-stage planning: task type, target/reference image
    selection, clarification need, and the final prompt passed to the image model.
    """
    candidate_rows = _image_mode_candidate_rows(messages or [], user_text=user_text, limit=6)
    allowed_task_types = {'existing_image_analysis', 'text_to_image', 'image_edit', 'reference_generate', 'reference_edit', 'variation', 'unclear'}
    responses_native_image_inputs_enabled = False
    try:
        normalized_image_settings = _normalize_image_generation_settings(image_generation_settings) or {}
        edit_enabled = bool((normalized_image_settings or {}).get('edit', {}).get('enabled'))
        native_checker = globals().get('_image_generation_should_use_responses_native')
        responses_native_image_inputs_enabled = bool(native_checker(normalized_image_settings or {}, client_override=client_override)) if callable(native_checker) else False
    except Exception:
        edit_enabled = False
        responses_native_image_inputs_enabled = False
    source_image_input_enabled = bool(edit_enabled or responses_native_image_inputs_enabled)
    judge_model = _resolve_aux_model(model, 'TOOL_PREFETCH_MODEL', 'gpt-5-nano-2025-08-07')
    try:
        convo = []
        for m in (messages or [])[-6:]:
            if not isinstance(m, dict):
                continue
            role = str(m.get('role') or '').strip()
            if role not in ('system', 'user', 'assistant'):
                continue
            content = _msg_content_text(m.get('content'))
            if content:
                convo.append({'role': role, 'content': content[:1000]})
        contract_text = ''
        try:
            contract_builder = globals().get('prompt_contract_text')
            if callable(contract_builder):
                contract_text = str(contract_builder('image_task_planner', compact=True) or '').strip()
        except Exception:
            contract_text = ''
        planner_messages = [
            {'role': 'system', 'content': (contract_text + '\n图片模式二次编排补充约束：历史对话和候选图片只用于消解代词、省略和明确承接关系，不能默认把上一轮图片任务拼进新的 prompt。').strip() if contract_text else 'Prompt contract: image_task_planner.\n输出：只输出 JSON object。\n约束：最新用户请求优先；历史对话和候选图片只用于消解代词、省略和明确承接关系，不能默认把上一轮图片任务拼进新的 prompt。'},
            *convo,
            {'role': 'user', 'content': _build_image_mode_planner_user_content(messages or [], user_text=user_text, candidate_rows=candidate_rows, image_generation_settings=image_generation_settings, max_images=4)},
        ]
        try:
            planner_messages = _sanitize_messages_for_model(planner_messages, allow_images=False)
        except Exception:
            pass
        req = {
            'model': judge_model,
            'messages': planner_messages,
            'temperature': 0,
            'max_tokens': 420,
        }
        contract_format = globals().get('apply_prompt_contract_response_format')
        if callable(contract_format):
            req = contract_format(req, 'image_task_planner')
        else:
            req['response_format'] = {'type': 'json_object'}
        req = _apply_completion_thinking_kwargs(req, role='tool_prefetch', model=judge_model, client_override=client_override)
        stream_json = globals().get('_file_delivery_stream_chat_json_content')
        if not callable(stream_json):
            raise RuntimeError('stream_json_helper_unavailable')
        try:
            raw = stream_json(req, client_override=client_override, purpose='image_mode_planner')
        except Exception:
            req['messages'] = _sanitize_messages_for_model(planner_messages, allow_images=False)
            raw = stream_json(req, client_override=client_override, purpose='image_mode_planner_text_only')
        obj = _safe_json_loads(raw) or {}
        tracer = globals().get('skill_trace_span')
        if callable(tracer):
            tracer('prompt_contract_completed', skill='image_generate', endpoint_mode='chat_completions', status='ok', metadata={'contract': 'image_task_planner', 'candidate_count': len(candidate_rows or [])})
    except Exception as e:
        return {
            'ok': False,
            'task_type': 'unclear',
            'prompt': '',
            'need_clarify': True,
            'clarify_question': '图片任务规划失败，请明确要生成、编辑、参考哪张图片，或只分析图片内容。',
            'reason': f'image_mode_planner_failed:{type(e).__name__}',
            'candidate_rows': candidate_rows,
            'edit_target_rows': [],
            'reference_rows': [],
            'ignore_rows': [],
            'selected_rows': [],
            'edit_enabled': edit_enabled,
            'source': 'planner_error',
            'error': f'{type(e).__name__}: {e}',
        }

    task_type = str(obj.get('task_type') or '').strip().lower()
    task_type = {
        'image_generation': 'text_to_image',
        'generate': 'text_to_image',
        'text2image': 'text_to_image',
        'txt2img': 'text_to_image',
        'edit': 'image_edit',
        'analysis': 'existing_image_analysis',
        'analyze': 'existing_image_analysis',
        'image_analysis': 'existing_image_analysis',
    }.get(task_type, task_type)
    if task_type not in allowed_task_types:
        task_type = 'unclear'
    prompt_text = str(obj.get('prompt') or '').strip()
    if task_type == 'text_to_image' and not prompt_text:
        prompt_text = _clean_image_subject(user_text) or str(user_text or '').strip()[:240]
    need_clarify = bool(obj.get('need_clarify')) or task_type == 'unclear'
    clarify_question = str(obj.get('clarify_question') or '').strip()
    edit_target_rows = _resolve_image_mode_selected_rows(obj.get('edit_target_image_ids'), candidate_rows, limit=4)
    reference_rows = _resolve_image_mode_selected_rows(obj.get('reference_image_ids'), candidate_rows, limit=4)
    selected_seed_rows = _resolve_image_mode_selected_rows(obj.get('selected_image_ids'), candidate_rows, limit=6)
    ignore_rows = _resolve_image_mode_selected_rows(obj.get('ignore_image_ids'), candidate_rows, limit=6)

    if task_type == 'text_to_image' and (reference_rows or selected_seed_rows):
        task_type = 'reference_generate'
    if task_type in {'reference_generate', 'variation'} and not reference_rows and selected_seed_rows:
        reference_rows = [dict(r) for r in selected_seed_rows[:4]]
    if task_type == 'image_edit' and not edit_target_rows and selected_seed_rows:
        edit_target_rows = [dict(r) for r in selected_seed_rows[:1]]
    if task_type == 'reference_edit' and not (edit_target_rows or reference_rows) and selected_seed_rows:
        reference_rows = [dict(r) for r in selected_seed_rows[:4]]

    if task_type == 'existing_image_analysis' and not (edit_target_rows or reference_rows):
        # For plain image follow-up, use the most relevant recent candidate as the image to analyze.
        if candidate_rows:
            edit_target_rows = candidate_rows[:1]
        else:
            need_clarify = True
            if not clarify_question:
                clarify_question = '请明确要分析哪一张图。'
    if task_type in {'image_edit', 'reference_edit'} and not edit_target_rows:
        need_clarify = True
        if not clarify_question:
            clarify_question = '请明确要编辑哪一张图。'
    if task_type in {'reference_generate', 'reference_edit', 'variation'} and not reference_rows and task_type != 'variation':
        if not edit_target_rows:
            need_clarify = True
            if not clarify_question:
                clarify_question = '请明确要参考哪一张图。'
    if task_type in {'image_edit', 'reference_edit', 'reference_generate', 'variation'} and not source_image_input_enabled:
        need_clarify = True
        if not clarify_question:
            clarify_question = '当前这类图片任务需要先启用图片编辑，或改为纯文生图。'
    if task_type == 'variation' and not (edit_target_rows or reference_rows):
        need_clarify = True
        if not clarify_question:
            clarify_question = '请明确要基于哪张图做变体。'

    selected_rows: list[dict] = []
    seen: set[str] = set()
    for group in (edit_target_rows, reference_rows):
        for row in group:
            key = str(row.get('attachment_key') or row.get('url') or row.get('image_id') or '').strip()
            if not key or key in seen:
                continue
            seen.add(key)
            selected_rows.append(dict(row))

    if selected_seed_rows:
        for row in selected_seed_rows:
            key = str(row.get('attachment_key') or row.get('url') or row.get('image_id') or '').strip()
            if not key or key in seen:
                continue
            seen.add(key)
            selected_rows.append(dict(row))

    result = {
        'ok': True,
        'task_type': task_type,
        'prompt': prompt_text,
        'need_clarify': bool(need_clarify),
        'clarify_question': clarify_question[:160],
        'reason': str(obj.get('reason') or '')[:160],
        'candidate_rows': candidate_rows,
        'edit_target_rows': edit_target_rows,
        'reference_rows': reference_rows,
        'ignore_rows': ignore_rows,
        'selected_rows': selected_rows,
        'edit_enabled': edit_enabled,
        'source': 'model',
    }
    result = _repair_unclear_image_generation_plan(result, user_text, raw_plan=obj, candidate_rows=candidate_rows)
    result = _apply_exact_bound_image_selection(result, messages or [], user_text=user_text, limit=4)
    return _normalize_image_task_plan_structure(result)

def _build_tool_prefetch_visual_user_content(messages: list | None = None, user_text: str = '', *, latest_user_has_images: bool = False, has_recent_context_images: bool = False, visual_hint: str = '', max_images: int = 2) -> list:
    """Build a text-only image index block for the prefetch/router model.

    This does not attach pixels. It only exposes stable ids and low-priority text
    hints so the router can choose the image lane; real image inspection must
    later go through image_id -> /mnt/data/chat_images -> sandbox analysis.
    """
    safe_hint = str(visual_hint or '').strip()
    try:
        visual_ref = _build_visual_reference_planning_context(
            messages or [],
            user_text=user_text,
            max_items=max(1, int(max_images or 2)),
            max_chars=1500,
        )
    except Exception:
        visual_ref = {'text': '', 'urls': []}
    visual_ref_text = str((visual_ref or {}).get('text') or '').strip()
    visual_context_bits = []
    if visual_ref_text:
        visual_context_bits.append(visual_ref_text)
    if safe_hint:
        visual_context_bits.append('【最近图片低优先级摘要】\n' + safe_hint)
    visual_context_text = '\n\n'.join([x for x in visual_context_bits if x]).strip() or 'none'

    parts = [{
        'type': 'text',
        'text': (
            f"用户最新问题：{str(user_text or '').strip()}\n"
            f"本轮用户消息是否自带图片：{'yes' if latest_user_has_images else 'no'}\n"
            f"最近对话里是否已有图片可供分析：{'yes' if has_recent_context_images else 'no'}\n"
            "图片/视觉上下文说明：这些内容只作为路由、工具选择和搜索主体补全的软证据；"
            "不要因为有图片就机械调用工具，也不要让低可信 OCR 覆盖用户真实文字请求。"
            "但当用户要联网查询、核实、了解“图里这个/它/这瓶/这个产品/这张图中的对象”时，"
            "应结合图片可见对象、标签文字或辅助识别文字判断是否需要联网，并把明确主体交给后续搜索规划。"
            "如果用户明确说第一张、第二张、上一张等，优先参考图片引用上下文里的绑定对象，而不是默认最近图片。"
            "如果用户要基于、参考或沿用对话已有图片继续生成/修改图片，即使本轮没有重新上传图片，也应把最近图片索引当作可用资产来判断 image_mode。\n"
            f"辅助视觉上下文：\n{visual_context_text}\n"
        )[:3200]
    }]

    return parts

def _message_to_text_for_budget(m: dict, include_images: bool = False, include_image_text: bool = True) -> str:
    if not isinstance(m, dict):
        return ''
    c = m.get('content')
    body = ''
    if isinstance(c, str):
        body = c
    elif isinstance(c, list):
        parts = []
        screenshot_like_count = 0
        for idx, it in enumerate(c, 1):
            if not isinstance(it, dict):
                continue
            if it.get('type') == 'text':
                txt = it.get('text')
                if isinstance(txt, str) and txt.strip():
                    parts.append(txt)
            elif it.get('type') == 'image_url':
                if include_images:
                    parts.append('[image]')
                if include_image_text:
                    hint, screenshot_like = _build_image_text_hint_for_model(it, idx=idx, allow_images=include_images, data_url='')
                    if screenshot_like:
                        screenshot_like_count += 1
                    if hint:
                        parts.append(hint)
        if screenshot_like_count and include_image_text:
            parts.insert(0, _chat_screenshot_guard_prompt())
        body = '\n'.join(parts)
    else:
        body = _structured_content_to_model_text(c)
    if str(m.get('role') or '') == 'user':
        body = _combine_message_text_and_quote(body, _message_quote_text(m))
    return _planner_safe_text(body, max_len=4000)

def _build_planner_messages(messages: list, user_geo: dict | None = None) -> list:
    user_text = _latest_user_text_from_messages(messages or [])
    recent = []
    for m in reversed(messages or []):
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '')
        if role not in ('user', 'assistant'):
            continue
        txt = _message_to_text_for_budget(m, include_images=False, include_image_text=False)
        visual_hint = _build_visual_low_priority_hint_for_message(m, max_images=1, max_chars=140)
        if visual_hint:
            txt = (txt + '\n' if txt else '') + f'[visual_low_priority] {visual_hint}'
        if not txt:
            continue
        recent.append(f'{role}: {txt[:560]}')
        if len(recent) >= 2:
            break
    recent.reverse()
    context = '\n'.join(recent[:-1]).strip() if recent else ''
    visual_hint = _build_recent_visual_low_priority_hint(messages or [], max_messages=2, max_images_per_message=2, max_chars=140)
    sys = (
        'You are a lightweight planner. Decide whether tools are needed before answering. '
        'Prefer the minimum necessary tools. Never include long quotations. '
        'Available tools include get_location, web_search, fetch_url, fetch_urls, get_weather, image_search. '
        'Visual hints are low-priority only: use them to avoid missing an attached image or follow-up, but do not let OCR noise override the user\'s actual request. '
        'Reply by using tool calls when needed, otherwise answer directly.'
    )
    if user_geo and isinstance(user_geo, dict) and user_geo.get('city'):
        sys += f" User city hint: {user_geo.get('city')}."
    user_block = user_text[:800]
    blocks = []
    if context:
        blocks.append(f'Recent context:\n{context}')
    if visual_hint:
        blocks.append(f'Visual hint (low priority):\n{visual_hint}')
    blocks.append(f'Current user request:\n{user_block}')
    user_block = '\n\n'.join([b for b in blocks if str(b or '').strip()])
    return [
        {'role': 'system', 'content': sys},
        {'role': 'user', 'content': user_block},
    ]
