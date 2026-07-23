# Split from app3_parts/chat/chat_orchestrator_part.py.
# Purpose: blocking chat entrypoints, final-answer cleanup, grounding/source guards, and fact bridge helpers.
# Loaded by app3.py via _exec_split_file(...), sharing the original global namespace.

def do_chat(model: str, messages: list, user_geo: dict | None = None, user_time: dict | None = None, client_override=None, web_enabled: bool | None = None, web_k: int | None = None, web_max_pages: int | None = None, runtime_model: str = ''):
    """兼容旧调用：仅返回文本内容。"""
    content, _meta = do_chat_with_meta(model, messages, user_geo=user_geo, user_time=user_time, client_override=client_override, web_enabled=web_enabled, web_k=web_k, web_max_pages=web_max_pages, runtime_model=runtime_model)
    return content


def _generated_file_link_key(raw_url: str = '') -> str:
    raw = str(raw_url or '').strip().strip('<>')
    if not raw:
        return ''
    try:
        pu = urlparse(raw)
        path = str(pu.path or '').strip()
        query = str(pu.query or '').strip()
    except Exception:
        path = raw.split('?', 1)[0].strip()
        query = raw.split('?', 1)[1].strip() if '?' in raw else ''
    if not (path.startswith('/api3/generated-download/') or path.startswith('/api3/generated-files/')):
        return ''
    try:
        path = re.sub(r'/+', '/', path)
    except Exception:
        pass
    return path + (('?' + query) if query else '')


def _generated_file_link_variants(raw_url: str = '') -> set[str]:
    key = _generated_file_link_key(raw_url)
    if not key:
        return set()
    variants = {key}
    if key.startswith('/api3/generated-files/'):
        variants.add('/api3/generated-download/' + key[len('/api3/generated-files/'):].lstrip('/'))
    elif key.startswith('/api3/generated-download/'):
        variants.add('/api3/generated-files/' + key[len('/api3/generated-download/'):].lstrip('/'))
    return variants


def _verified_generated_file_link_keys(artifacts: list | None = None) -> set[str]:
    allowed: set[str] = set()
    for item in (artifacts or []):
        if not isinstance(item, dict):
            continue
        for field in ('download_url', 'view_url', 'url'):
            allowed.update(_generated_file_link_variants(item.get(field) or ''))
        helper = globals().get('_generated_files_download_url')
        if callable(helper):
            try:
                allowed.update(_generated_file_link_variants(helper(item)))
            except Exception:
                pass
    return {x for x in allowed if x}


def _collect_generated_file_artifacts_from_messages(messages: list | None = None, limit: int = 24) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()

    def _push(item: dict | None = None) -> None:
        if not isinstance(item, dict):
            return
        url = str(item.get('download_url') or item.get('view_url') or item.get('url') or '').strip()
        if not _generated_file_link_key(url):
            return
        filename = str(item.get('filename') or item.get('name') or '').strip()
        key = f'{_generated_file_link_key(url)}|{filename}'
        if key in seen:
            return
        seen.add(key)
        rows.append({
            'filename': filename,
            'download_url': str(item.get('download_url') or url).strip(),
            'view_url': str(item.get('view_url') or item.get('url') or url).strip(),
            'url': str(item.get('url') or item.get('download_url') or url).strip(),
        })

    def _walk(node, depth: int = 0) -> None:
        if len(rows) >= int(limit or 24) or depth > 5:
            return
        if isinstance(node, dict):
            _push(node)
            for key in ('artifacts', 'files', 'generated_files', 'generatedFiles', 'image_artifacts', 'content'):
                value = node.get(key)
                if isinstance(value, (list, tuple, dict)):
                    _walk(value, depth + 1)
        elif isinstance(node, (list, tuple)):
            for item in node:
                _walk(item, depth + 1)
                if len(rows) >= int(limit or 24):
                    break

    try:
        _walk(messages or [], 0)
    except Exception:
        return rows[:limit]
    return rows[:limit]


def _strip_unverified_generated_file_links(text: str = '', artifacts: list | None = None) -> str:
    raw = str(text or '')
    if '/api3/generated-download/' not in raw and '/api3/generated-files/' not in raw:
        return raw
    allowed = _verified_generated_file_link_keys(artifacts or [])

    def _is_allowed(url: str = '') -> bool:
        variants = _generated_file_link_variants(url)
        return bool(variants and any(v in allowed for v in variants))

    markdown_re = re.compile(r'\[([^\]\n]{0,240})\]\(([^)\s]*(?:/api3/generated-(?:download|files)/)[^)]+)\)', re.IGNORECASE)

    def _markdown_repl(match):
        label = str(match.group(1) or '').strip()
        href = str(match.group(2) or '').strip()
        if _is_allowed(href):
            return match.group(0)
        return label

    cleaned = markdown_re.sub(_markdown_repl, raw)
    bare_re = re.compile(r'(?P<url>(?:https?://[^\s\]\)<>"\']+)?/api3/generated-(?:download|files)/[^\s\]\)<>"\']+)', re.IGNORECASE)

    def _bare_repl(match):
        url = str(match.group('url') or '').strip()
        return url if _is_allowed(url) else ''

    cleaned = bare_re.sub(_bare_repl, cleaned)
    out_lines: list[str] = []
    for line in cleaned.splitlines():
        compact = str(line or '').strip()
        if not compact:
            if out_lines and out_lines[-1] != '':
                out_lines.append('')
            continue
        if compact in {'[]', '()', '-', '*'}:
            continue
        out_lines.append(line.rstrip())
    return '\n'.join(out_lines).strip()


def _strip_redundant_generated_file_lines(text: str, artifacts: list | None = None) -> str:
    return _strip_unverified_generated_file_links(str(text or ''), artifacts or [])


def _strip_generated_file_links_for_delivery(
    text: str = '',
    *,
    has_artifacts: bool = False,
    allowed_artifacts: list | None = None,
    strip_all_generated_links: bool = False,
) -> str:
    """File cards are the source of truth for generated downloads."""
    raw = str(text or '')
    if strip_all_generated_links:
        return _strip_unverified_generated_file_links(raw, [])
    if not has_artifacts:
        return _strip_unverified_generated_file_links(raw, [])
    return _strip_unverified_generated_file_links(raw, allowed_artifacts or [])


def _inject_generated_artifact_context_for_final(messages: list | None = None, artifacts: list | None = None, audits: list | None = None) -> list:
    out = [dict(m) if isinstance(m, dict) else m for m in (messages or [])]
    try:
        ctx_builder = globals().get('_file_delivery_final_artifact_context')
        ctx = ctx_builder(artifacts or [], audits or []) if callable(ctx_builder) else ''
        if ctx:
            out.append({'role': 'system', '_kind': 'generated_artifact_context', 'content': ctx})
    except Exception:
        return out
    return out


def _file_delivery_internal_tool_names() -> set[str]:
    helper = globals().get('skill_removed_tool_names')
    if callable(helper):
        try:
            return {str(x or '').strip() for x in (helper() or []) if str(x or '').strip()}
        except Exception:
            pass
    return set()


def _file_delivery_internal_text_markers() -> tuple[str, ...]:
    helper = globals().get('skill_removed_tool_markers')
    if callable(helper):
        try:
            markers = tuple(str(x or '').strip().lower() for x in (helper() or []) if str(x or '').strip())
            if markers:
                return markers
        except Exception:
            pass
    return tuple(sorted({
        '"tool_calls"',
        '"exact_old"',
        '"replacement"',
        '"replacements"',
        '"edits"',
        'tool_call_id',
    }))


def _file_delivery_internal_tool_names_from_message(message: dict | None = None) -> set[str]:
    names: set[str] = set()
    if not isinstance(message, dict):
        return names
    for call in (message.get('tool_calls') or []):
        if not isinstance(call, dict):
            continue
        fn = call.get('function') if isinstance(call.get('function'), dict) else {}
        name = str((fn or {}).get('name') or '').strip()
        if name in _file_delivery_internal_tool_names():
            names.add(name)
    return names


def _looks_like_file_delivery_internal_text(text: str = '') -> bool:
    raw = str(text or '')
    if not raw:
        return False
    low = raw.lower()
    return any(marker in low for marker in _file_delivery_internal_text_markers())


def _strip_file_delivery_internal_messages_for_final(messages: list | None = None) -> list:
    """Remove raw file-tool call/response messages before the final user-visible reply.

    Keep this historical scrubber aware of removed file tool names so older stored
    turns cannot leak raw tool-call JSON into a final answer. The live file chain
    now uses sandbox_* tools only for live file import/read/write/run/publish.
    """
    out: list = []
    drop_tool_ids: set[str] = set()
    for raw in (messages or []):
        if not isinstance(raw, dict):
            continue
        m = dict(raw)
        role = str(m.get('role') or '').strip().lower()
        if role == 'assistant':
            names = _file_delivery_internal_tool_names_from_message(m)
            if names:
                for call in (m.get('tool_calls') or []):
                    if isinstance(call, dict):
                        cid = str(call.get('id') or '').strip()
                        if cid:
                            drop_tool_ids.add(cid)
                content = str(m.get('content') or '').strip()
                if content and not _looks_like_file_delivery_internal_text(content):
                    clean = dict(m)
                    clean.pop('tool_calls', None)
                    out.append(clean)
                continue
        if role == 'tool':
            tool_call_id = str(m.get('tool_call_id') or '').strip()
            content = str(m.get('content') or '')
            if tool_call_id in drop_tool_ids or _looks_like_file_delivery_internal_text(content):
                continue
        if role == 'system':
            content = str(m.get('content') or '')
            if (
                content.startswith('文件处理模式：')
                or '不要用聊天正文冒充附件；文件必须由工具保存。' in content
            ):
                continue
        out.append(m)
    return out


def _sanitize_file_delivery_visible_text(
    text: str = '',
    *,
    has_artifacts: bool = False,
    allowed_artifacts: list | None = None,
    strip_all_generated_links: bool = False,
) -> str:
    cleaned = _strip_leaked_think_tags(str(text or ''))
    if not cleaned:
        return ''
    cleaned = _strip_grounded_process_preface(cleaned, aggressive=bool(has_artifacts))
    cleaned = _strip_generated_file_links_for_delivery(
        cleaned,
        has_artifacts=bool(has_artifacts),
        allowed_artifacts=allowed_artifacts,
        strip_all_generated_links=bool(strip_all_generated_links),
    )
    if not _looks_like_file_delivery_internal_text(cleaned):
        return cleaned
    # If a model echoed raw tool JSON/pseudo-calls, keep only clearly user-facing
    # natural lines. In practice these leaks are usually all-internal, so this often
    # returns an empty string and lets the real file cards carry the delivery.
    kept: list[str] = []
    for line in cleaned.splitlines():
        stripped = str(line or '').strip()
        if not stripped:
            if kept and kept[-1] != '':
                kept.append('')
            continue
        low = stripped.lower()
        if _looks_like_file_delivery_internal_text(stripped):
            continue
        if stripped.startswith(('{', '[', '<')) or stripped.endswith(('}', ']', '/>')):
            continue
        if ('target_filename' in low or 'output_filename' in low or 'expected_occurrences' in low):
            continue
        kept.append(line)
    salvaged = '\n'.join(kept).strip()
    if _looks_like_file_delivery_internal_text(salvaged):
        return ''
    return _strip_unverified_generated_file_links(salvaged, [])


def do_chat_with_meta(model: str, messages: list, user_geo: dict | None = None, user_time: dict | None = None, client_override=None, visual_ctx: dict | None = None, web_enabled: bool | None = None, web_k: int | None = None, web_max_pages: int | None = None, runtime_model: str = ''):
    """统一编排：先决定天气/图片工具，再由 AI 提关键词联网补网页，最后生成回答。"""
    _ctx, stage = _run_orchestrator_once(
        model,
        messages or [],
        user_geo=user_geo,
        user_time=user_time,
        client_override=client_override,
        visual_ctx=visual_ctx,
        enable_visual=visual_ctx is None,
        web_enabled=web_enabled,
        web_k=web_k,
        web_max_pages=web_max_pages,
    )
    tool_records = list(stage.get("tool_records") or [])
    tool_counts = dict(stage.get("tool_counts") or {})
    planner_direct_answer = str(stage.get("planner_direct_answer") or '')

    if planner_direct_answer and not tool_records and not (stage.get("web_meta") or {}).get("enabled") and not bool(stage.get('request_file_generation')):
        meta = {
            'model': model,
            'rounds': 1,
            'tool_counts': tool_counts,
            'web': stage.get('web_meta') or {},
        }
        return planner_direct_answer, meta

    final_messages = _build_orchestrated_final_messages(stage, messages or [], user_geo=user_geo)

    prefetch_decision = dict((_ctx or {}).get('prefetch_decision') or {})
    prefetch_decision['file_action'] = 'none'
    image_artifacts = list(stage.get('generated_artifacts') or [])
    artifacts = [*(image_artifacts or [])]
    file_messages = list(final_messages)
    tool_plan = dict(stage.get('tool_plan') or {})
    is_image_turn = bool(_stage_has_image_mode_request(stage) or image_artifacts)
    image_direct_reply_done = _stage_should_direct_return_image_reply(stage)
    should_run_final_model = not bool(image_direct_reply_done)
    response_runtime_model = ''

    if image_direct_reply_done:
        content = ''
    else:
        file_messages = _inject_main_chat_runtime_model_context(file_messages, runtime_model)
        file_messages = _inject_agent_final_direct_answer_guard(file_messages, stage)
        file_messages = _inject_agent_final_fact_bridge(model, file_messages, stage, client_override=client_override)
        file_messages = _inject_generated_artifact_context_for_final(file_messages, artifacts, [])
        resp2 = (client_override or client_gpt).chat.completions.create(
            model=model,
            messages=file_messages,
        )
        if not getattr(resp2, 'choices', None):
            raise RuntimeError(f"模型返回空 choices：model={model}")
        response_runtime_model = _extract_runtime_model_from_obj(resp2)
        content = getattr(resp2.choices[0].message, 'content', None) or ''


    parsed_saved_artifacts = []
    parsed = _try_parse_artifact_json(content)
    if parsed:
        parsed_answer, parsed_artifacts = parsed
        publisher = globals().get('_sandbox_stage_and_publish_artifacts')
        publish_result = publisher(parsed_artifacts, messages or [], source='chat_nonstream_artifact_json') if callable(publisher) else {
            'ok': False,
            'error': 'sandbox_artifact_bridge_unavailable',
            'files': [],
        }
        saved = [dict(x) for x in (publish_result.get('files') or []) if isinstance(x, dict)]
        if saved:
            artifacts.extend(saved)
            parsed_saved_artifacts = [dict(x) for x in saved if isinstance(x, dict)]
        elif not parsed_answer:
            content = '文件未能通过统一沙盒发布，请重试。'
        content = parsed_answer or content

    current_delivery_artifacts = [*(parsed_saved_artifacts or [])]
    historical_generated_artifacts = _collect_generated_file_artifacts_from_messages(messages or [])
    allowed_generated_link_artifacts = artifacts if current_delivery_artifacts else [*(artifacts or []), *(historical_generated_artifacts or [])]
    content = _strip_grounded_process_preface(content, aggressive=_stage_has_bound_web_hit(stage))
    content = _sanitize_file_delivery_visible_text(
        content,
        has_artifacts=bool(current_delivery_artifacts or allowed_generated_link_artifacts),
        allowed_artifacts=allowed_generated_link_artifacts,
        strip_all_generated_links=bool(current_delivery_artifacts),
    )
    content = _strip_redundant_generated_file_lines(content, [] if current_delivery_artifacts else allowed_generated_link_artifacts)

    # dedupe artifacts
    deduped_artifacts = []
    seen_artifact_keys = set()
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        key = f"{str(item.get('download_url') or '').strip()}|{str(item.get('filename') or '').strip()}"
        if key in seen_artifact_keys:
            continue
        seen_artifact_keys.add(key)
        deduped_artifacts.append(item)

    meta = {
        'model': model,
        'rounds': 2,
        'tool_counts': tool_counts,
        'web': stage.get('web_meta') or {},
        'file_tool_used': False,
        'file_tool_rounds': 0,
        **_runtime_model_meta(response_runtime_model),
    }
    if deduped_artifacts:
        meta['artifacts'] = deduped_artifacts
    return str(content or ''), meta



def _agent_final_has_explicit_url_request(stage: dict | None = None) -> bool:
    stage = stage or {}
    last_user_text = str(stage.get("last_user_text") or "").strip()
    return ("http://" in last_user_text) or ("https://" in last_user_text)



def _collect_agent_final_grounding_material(messages: list | None = None, stage: dict | None = None, max_chars: int = 5200) -> str:
    msgs = list(messages or [])
    stage = stage or {}
    blocks: list[str] = []
    seen = set()

    def _push_block(raw):
        content = str(raw or '').strip()
        if not content:
            return
        norm = re.sub(r'\s+', ' ', content)
        if norm in seen:
            return
        seen.add(norm)
        blocks.append(content)

    prepared_messages = list(stage.get('prepared_messages') or [])
    for item in [*prepared_messages, *msgs]:
        if not isinstance(item, dict):
            continue
        content = str(item.get('content') or '')
        kind = str(item.get('_kind') or '').strip().lower()
        if kind in {'page', 'web'}:
            _push_block(content)
            continue
        if item.get('role') == 'system' and any(marker in content for marker in (
            '以下是用户提供链接抓取到的网页正文',
            '你已获得实时外部信息',
            '【网页正文摘录】',
            '网页标题：',
            '网页正文：',
            '工具结果摘要（',
        )):
            _push_block(content)

    for rec in stage.get('tool_records') or []:
        if not isinstance(rec, dict):
            continue
        rec_text = _coerce_tool_record_content_for_model(rec)
        _push_block(f"工具结果摘要（{rec.get('name','tool')}）：\n{rec_text}")

    joined = '\n\n'.join(blocks).strip()
    if not joined:
        return ''
    return joined[:max_chars]




def _normalize_visible_source_url(url: str) -> str:
    raw = str(url or '').strip()
    if not raw:
        return ''
    try:
        if '_norm_url_for_dedup' in globals() and callable(_norm_url_for_dedup):
            return str(_norm_url_for_dedup(raw) or '').strip() or raw
    except Exception:
        pass
    try:
        pu = urlparse(raw)
        scheme = (pu.scheme or 'https').lower()
        netloc = (pu.netloc or '').lower()
        path = pu.path or '/'
        return urlunparse((scheme, netloc, path.rstrip('/') or '/', '', '', ''))
    except Exception:
        return raw


def _is_public_visible_source_url(url: str) -> bool:
    raw = str(url or '').strip()
    if not re.match(r'^https?://', raw, flags=re.I):
        return False
    try:
        pu = urlparse(raw)
    except Exception:
        return False
    try:
        host = (pu.hostname or '').lower().strip()
    except Exception:
        host = ''
    if not host:
        return False
    if host in {'localhost', '127.0.0.1', '0.0.0.0', '::1'} or host.endswith('.local') or host.endswith('.lan'):
        return False
    try:
        ip_obj = ipaddress.ip_address(host.strip('[]'))
        if bool(ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_unspecified or ip_obj.is_multicast):
            return False
    except Exception:
        pass
    path = str(pu.path or '').strip().lower()
    if path.startswith('/api3/download/') or path.startswith('/api3/uploads/') or path.startswith('/api3/source-favicon'):
        return False
    return True


def _extract_visible_sources_from_text(raw_text: str, limit: int = 8) -> list[dict]:
    text = str(raw_text or '').strip()
    if not text:
        return []

    out: list[dict] = []
    seen = set()

    def _is_private_or_internal_host(host: str) -> bool:
        raw = str(host or '').strip().lower().strip('[]')
        if not raw:
            return True
        if raw in {'localhost', '127.0.0.1', '0.0.0.0', '::1'}:
            return True
        if raw.endswith('.local') or raw.endswith('.lan'):
            return True
        try:
            ip_obj = ipaddress.ip_address(raw)
            return bool(
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
                or ip_obj.is_multicast
            )
        except Exception:
            return False

    def _is_visible_source_url(url: str) -> bool:
        raw = str(url or '').strip()
        if not _is_public_visible_source_url(raw):
            return False
        host = _host_of(raw)
        if _is_private_or_internal_host(host):
            return False
        return True

    def _title_of(url: str, title: str) -> str:
        t = str(title or '').strip().strip('[]【】')
        if t.startswith('TITLE:'):
            t = t[6:].strip()
        if t.startswith('网页标题：'):
            t = t.split('：', 1)[1].strip() if '：' in t else t
        t = re.sub(r'^\[[0-9]+\]\s*', '', t).strip()
        if t:
            return t[:160]
        host = _host_of(url)
        return host[:120] if host else str(url or '').strip()[:160]

    def _push(url: str, title: str = '') -> None:
        u = str(url or '').strip()
        if not _is_visible_source_url(u):
            return
        nu = _normalize_visible_source_url(u)
        if not nu or nu in seen or not _is_visible_source_url(nu):
            return
        seen.add(nu)
        host = _host_of(nu)
        out.append({
            'title': _title_of(nu, title),
            'url': nu[:500],
            'host': host[:120],
        })

    lines = [str(line or '').strip() for line in text.splitlines()]
    pending_title = ''
    pending_candidates: list[str] = []

    for line in lines:
        if not line:
            continue
        if len(out) >= max(1, int(limit or 8)):
            break

        if re.match(r'^\[[0-9]+\]\s+', line):
            pending_title = re.sub(r'^\[[0-9]+\]\s*', '', line).strip()
            continue
        if line.startswith('TITLE:'):
            pending_title = line[6:].strip()
            continue
        if line.startswith('网页标题：'):
            pending_title = line.split('：', 1)[1].strip() if '：' in line else line
            continue
        if line.startswith('[来源]'):
            _push(line.split(']', 1)[1].strip(), pending_title)
            pending_title = ''
            continue
        if line.startswith('URL:'):
            _push(line[4:].strip(), pending_title)
            pending_title = ''
            continue
        if re.match(r'^https?://', line, flags=re.I):
            _push(line, pending_title)
            pending_title = ''
            continue
        pending_candidates.append(line)

    if len(out) < max(1, int(limit or 8)):
        for url in re.findall(r"https?://[^\s\]\)\>\"']+", text, flags=re.I):
            if len(out) >= max(1, int(limit or 8)):
                break
            _push(url, '')

    return out[:max(1, int(limit or 8))]


def _stage_has_bound_web_hit(stage: dict | None = None) -> bool:
    stage = stage or {}
    web_meta = dict(stage.get('web_meta') or {})
    if not bool(web_meta.get('enabled')):
        return False
    if bool(web_meta.get('cache_hit')):
        return True
    try:
        results = int(web_meta.get('results') or 0)
    except Exception:
        results = 0
    try:
        pages = int(web_meta.get('pages') or 0)
    except Exception:
        pages = 0
    search_results = [it for it in (web_meta.get('search_results') or []) if isinstance(it, dict)]
    return bool(results > 0 or pages > 0 or search_results)


def _visible_sources_from_result_rows(items, limit: int = 8) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    max_rows = max(1, min(int(limit or 8), 12))

    for item in (items or []):
        if not isinstance(item, dict):
            continue
        raw_url = str(item.get('url') or item.get('href') or '').strip()
        if not raw_url:
            continue
        try:
            if not _is_public_visible_source_url(raw_url):
                continue
            url = _normalize_visible_source_url(raw_url)
            if not url or not _is_public_visible_source_url(url):
                continue
        except Exception:
            url = raw_url
        key = _normalize_visible_source_url(url)
        if not key or key in seen:
            continue
        seen.add(key)
        host = str(item.get('host') or item.get('domain') or _host_of(url) or '').strip().lower()
        title = str(item.get('title') or item.get('name') or host or url).strip()
        snippet = str(item.get('snippet') or item.get('summary') or item.get('text') or item.get('content') or '').strip()
        favicon = str(item.get('favicon') or item.get('icon') or item.get('icon_url') or item.get('iconUrl') or '').strip()
        rows.append({
            'title': title[:200],
            'url': url[:500],
            'host': host[:120],
            'snippet': _planner_safe_text(snippet, max_len=260),
            **({'favicon': favicon[:500]} if favicon else {}),
        })
        if len(rows) >= max_rows:
            break
    return rows



def _collect_stage_visible_sources(messages: list | None = None, stage: dict | None = None, limit: int = 8) -> list[dict]:
    stage = stage or {}
    if not _stage_has_bound_web_hit(stage):
        return []
    web_meta = dict(stage.get('web_meta') or {}) if isinstance(stage.get('web_meta'), dict) else {}
    try:
        page_count = int(web_meta.get('pages') or 0)
    except Exception:
        page_count = 0
    explicit_fetch_records = []
    for rec in (stage.get('tool_records') or []):
        if not isinstance(rec, dict):
            continue
        if str(rec.get('name') or '').strip() in {'fetch_url', 'fetch_urls'}:
            explicit_fetch_records.append(rec)
    search_results = [dict(it) for it in (web_meta.get('search_results') or []) if isinstance(it, dict)]
    if page_count <= 0 and not explicit_fetch_records:
        return _visible_sources_from_result_rows(search_results, limit=limit)

    blocks: list[str] = []
    if page_count > 0:
        try:
            grounding_text = _collect_agent_final_grounding_material(messages or [], stage or {}, max_chars=24000)
            if grounding_text:
                blocks.append(grounding_text)
        except Exception:
            pass
    for rec in explicit_fetch_records:
        try:
            rec_text = _coerce_tool_record_content_for_model(rec)
        except Exception:
            rec_text = str((rec or {}).get('content') or '')
        if str(rec_text or '').strip():
            blocks.append(str(rec_text or ''))
    visible = _extract_visible_sources_from_text('\n\n'.join(blocks), limit=limit)
    if visible:
        return visible
    return _visible_sources_from_result_rows(search_results, limit=limit)




def _build_web_grounding_tool_record(stage: dict | None = None, *, limit: int = 6) -> dict | None:
    stage = stage or {}
    web_meta = dict(stage.get('web_meta') or {})
    if not bool(web_meta.get('enabled')):
        return None

    try:
        result_count = int(web_meta.get('results') or 0)
    except Exception:
        result_count = 0
    try:
        page_count = int(web_meta.get('pages') or 0)
    except Exception:
        page_count = 0

    query = str(web_meta.get('query') or '').strip()
    queries_used = [str(q or '').strip() for q in (web_meta.get('queries_used') or []) if str(q or '').strip()]
    search_results = [dict(it) for it in (web_meta.get('search_results') or []) if isinstance(it, dict)]
    cache_hit = bool(web_meta.get('cache_hit'))
    if not (query or queries_used or search_results or cache_hit or result_count > 0 or page_count > 0):
        return None

    rows = _visible_sources_from_result_rows(search_results, limit=max(1, min(int(limit or 6), 10)))

    payload = {
        'query': query,
        'queries_used': queries_used[:6],
        'cache_hit': cache_hit,
        'result_count': result_count,
        'page_count': page_count,
        'sources': rows,
    }
    return {
        'name': 'web_research',
        'content': _format_web_grounding_payload_for_model(payload, limit=limit),
    }


def _agent_final_should_build_fact_bridge(model: str | None = None, stage: dict | None = None, client_override=None) -> bool:
    stage = stage or {}
    has_bound_grounding = _agent_final_has_explicit_url_request(stage) or _stage_has_bound_web_hit(stage)
    if not has_bound_grounding:
        return False
    try:
        return bool(_chat_role_prefers_fact_bridge(model, client_override=client_override))
    except Exception:
        return False


def _agent_final_dedupe_model_messages(messages: list | None = None) -> list:
    items = list(messages or [])
    try:
        deduper = globals().get('_orch_dedupe_model_messages')
        if callable(deduper):
            return deduper(items)
    except Exception:
        pass
    return items


def _inject_agent_final_fact_bridge(model: str, messages: list | None = None, stage: dict | None = None, client_override=None) -> list:
    out = list(messages or [])
    stage = stage or {}
    if not _agent_final_has_grounding(out, stage):
        return _agent_final_dedupe_model_messages(out)
    if not _agent_final_should_build_fact_bridge(model, stage, client_override=client_override):
        return out

    cached = str(stage.get('_agent_final_fact_bridge') or '').strip()
    if cached:
        out.append({
            'role': 'system',
            '_kind': 'agent_final_fact_bridge',
            'content': cached,
        })
        return out

    grounding_text = _collect_agent_final_grounding_material(out, stage)
    if len(grounding_text) < 80:
        return out

    user_question = str(stage.get('last_user_text') or '').strip()
    contract_text = ''
    try:
        contract_builder = globals().get('prompt_contract_text')
        if callable(contract_builder):
            contract_text = str(contract_builder('web_fact_extractor', compact=True) or '').strip()
    except Exception:
        contract_text = ''
    extractor_messages = [
        {
            'role': 'system',
            'content': (
                ((contract_text + '\n') if contract_text else '')
                + '请只基于给定材料，提炼出能直接支撑最终回答的已确认事实。'
                '优先提炼：页面标题、顶部入口、公告/提示、商品或服务、联系方式、登录/注册、价格或分类等可见事实。'
                '输出中文要点 4-8 条，每条尽量短，信息不确定就不要写。'
            ),
        },
        {
            'role': 'user',
            'content': f"用户问题：{user_question}\n\n材料：\n{grounding_text}",
        },
    ]
    try:
        resp = (client_override or client_gpt).chat.completions.create(
            model=model,
            messages=extractor_messages,
        )
        fact_text = ''
        if getattr(resp, 'choices', None):
            fact_text = str(getattr(resp.choices[0].message, 'content', None) or '').strip()
        if fact_text:
            bridge = (
                '下面是根据已抓到的网页/工具材料提炼出的事实要点。'
                '请优先围绕这些已确认事实直接回答用户，必要时再参考原始材料补充。'
                '不要把模板化猜测当成事实，也不要再反问用户是否要继续抓取。\n' + fact_text
            )
            stage['_agent_final_fact_bridge'] = bridge
            out.append({
                'role': 'system',
                '_kind': 'agent_final_fact_bridge',
                'content': bridge,
            })
    except Exception:
        app_logger.exception('[agent_final] fact_bridge_build_failed model=%s', model)
    return _agent_final_dedupe_model_messages(out)



def _agent_final_has_grounding(messages: list | None = None, stage: dict | None = None) -> bool:
    msgs = list(messages or [])
    stage = stage or {}
    if stage.get("tool_records") or (stage.get("web_meta") or {}).get("enabled"):
        return True
    if isinstance(stage.get("latest_weather_payload"), dict) and stage.get("latest_weather_payload", {}).get("ok"):
        return True
    markers = (
        "以下是用户提供链接抓取到的网页正文",
        "你已获得实时外部信息",
        "工具结果摘要（",
        "【网页正文摘录】",
        "网页标题：",
        "网页正文：",
        "【本轮文件工具结果】",
    )
    for item in msgs:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "")
        if any(marker in content for marker in markers):
            return True
    return False


def _agent_final_is_internal_prompt_request(stage: dict | None = None) -> bool:
    return False


def _agent_final_is_memory_content_request(stage: dict | None = None) -> bool:
    stage = stage or {}
    text = str(stage.get("last_user_text") or "").strip().lower()
    if not text:
        return False
    markers = (
        '你记得我什么', '你记住了什么', '你还记得什么', '我的记忆', '我的偏好', '保存了什么偏好',
        '保存了什么记忆', '已保存偏好', '已保存记忆', '记忆内容', '记住了哪些', '都记了什么',
        '你保存了我什么', '你知道我的哪些偏好'
    )
    return any(marker in text for marker in markers)



def _inject_agent_final_direct_answer_guard(messages: list | None = None, stage: dict | None = None) -> list:
    out = list(messages or [])
    stage = stage or {}

    if _agent_final_is_memory_content_request(stage):
        out.append({
            "role": "system",
            "_kind": "agent_final_memory_guard",
            "content": "这轮如果回答记忆相关问题，只围绕用户自己的已保存偏好做简短回答。",
        })

    file_prompt = _build_file_delivery_soft_prompt(out)
    if file_prompt:
        out.append({
            "role": "system",
            "_kind": "agent_final_file_delivery_guard",
            "content": (
                "如果这轮用户带有明显文件交付意图，不要说“我没法发附件”“我不能真正生成文件”“你复制到本地保存”之类的话。"
                "真实文件由 sandbox 工具链和已发布 artifact 承载；正文只需正常说明方案、内容或后续步骤。"
            ),
        })

    if not _agent_final_has_grounding(out, stage):
        return _agent_final_dedupe_model_messages(out)

    last_user_text = str(stage.get("last_user_text") or "").strip()
    has_explicit_url = ("http://" in last_user_text) or ("https://" in last_user_text)

    guidance = [
        "你已经拿到了可用的网页/工具材料，现在直接给用户最终答案。",
        "不要输出“我帮你看一下”“我去看看”“请稍等”“正在查询”这类过程性过渡句。",
        "优先概括你已经看到的具体信息，而不是泛泛猜测页面大概是什么。",
    ]
    if has_explicit_url:
        guidance.extend([
            "这轮用户已经给了明确链接，重点是在问这个链接/网页里实际有什么。",
            "请直接总结页面里可见的内容、入口、商品、功能、公告或其他关键信息。",
            "不要把已经抓到的材料说成还需要继续抓取，也不要反问用户是否还要你继续提取或总结。",
            "如果材料仍有缺口，就先说清你已经看到了什么，再简短说明哪些点暂时无法确认。",
        ])
    else:
        guidance.append("若材料足够，就直接回答；只有在确实缺关键事实时，才简短说明不确定点。")

    out.append({
        "role": "system",
        "_kind": "agent_final_grounding_guard",
        "content": ''.join(guidance),
    })
    return _agent_final_dedupe_model_messages(out)


def _looks_like_process_only_reply(text: str) -> bool:
    raw = str(text or '').strip()
    if not raw:
        return False
    compact = re.sub(r'\s+', '', raw)
    compact = compact.strip('，,。.!！？?；;：:、~～…')
    if not compact:
        return False
    if len(compact) > 90:
        return False
    process_markers = (
        '我帮你看一下', '我帮你查一下', '我去帮你看一下', '我去帮你查一下',
        '我先帮你看一下', '我先帮你查一下', '我去看看', '我来看看', '我先看看',
        '我正在查看', '我正在帮你查看', '正在查看', '正在查询',
        '这个网址的内容', '这个链接的内容', '这个网站的内容', '这个网页的内容',
        '请稍等', '请稍候', '稍等', '稍候', '等一下', '请等待',
    )
    info_markers = (
        '首页', '网站', '页面', '商品', '功能', '登录', '注册', '购买', '客服', '公告',
        '提供', '包含', '显示', '售卖', '支持', '价格', '账号', '邮箱', '苹果id', 'ChatGPT',
        'Gemini', 'Claude', 'Grok',
    )
    has_process = any(marker in compact for marker in process_markers)
    has_info = any(marker.lower() in compact.lower() for marker in info_markers)
    if has_process and not has_info:
        return True
    exact_patterns = (
        r'^我(?:去|来|先)?帮你(?:看|查)(?:一下|一看)?这个(?:链接|网址|网站|网页)?(?:的内容)?$',
        r'^我(?:去|来|先)?看看这个(?:链接|网址|网站|网页)?(?:的内容)?$',
        r'^(?:请)?稍等(?:一下|片刻)?$',
        r'^我正在(?:查看|查询).*$'
    )
    return any(re.fullmatch(pattern, compact, flags=re.IGNORECASE) for pattern in exact_patterns)




def _strip_leaked_think_tags(text: str) -> str:
    raw = str(text or '')
    if not raw:
        return raw
    return re.sub(r'(?is)</?\s*think\b[^>]*>?', '', raw)


def _looks_like_grounded_structured_preface_start(text: str) -> bool:
    raw = str(text or '').lstrip()
    if not raw or raw[:1] not in '{[':
        return False
    head = raw[:600]
    markers = ('"query"', '"queries_used"', '"sources"', '"result_count"', '"page_count"')
    return any(marker in head for marker in markers)


def _strip_leading_grounded_json_blob(text: str) -> str:
    raw = str(text or '')
    if not raw:
        return raw
    leading = raw.lstrip()
    prefix_len = len(raw) - len(leading)
    if not _looks_like_grounded_structured_preface_start(leading):
        return raw

    opener = leading[:1]
    closer = '}' if opener == '{' else ']'
    depth = 0
    in_string = False
    escape = False
    end_idx = -1
    for idx, ch in enumerate(leading):
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                end_idx = idx + 1
                break
    if end_idx <= 0:
        return raw
    candidate = leading[:end_idx].strip()
    try:
        obj = json.loads(candidate)
    except Exception:
        return raw
    if isinstance(obj, dict):
        keys = set(obj.keys())
        if not ({'query', 'sources'} & keys or {'queries_used', 'result_count', 'page_count'} & keys):
            return raw
    elif isinstance(obj, list):
        if not obj:
            return raw
    else:
        return raw
    remain = leading[end_idx:].lstrip()
    return raw[:prefix_len] + remain


def _strip_grounded_process_preface(text: str, *, aggressive: bool = False) -> str:
    raw = str(text or '')
    if not raw:
        return raw
    lines = raw.splitlines(keepends=True)
    if not lines:
        return raw

    process_prefixes = (
        '用户询问', '根据已命中的联网材料', '根据已抓到的网页', '我需要调用', '我将调用',
        '我会调用', '我准备调用', '我先调用', '我需要使用', '我将使用', '我会使用', '我先使用',
        '我要搜索', '我将搜索', '我会搜索', '我先搜索', '我来搜索', '我需要查询', '我将查询', '我会查询',
        '我先查询', '我来查询', '我正在查询', 'WEB_SEARCH', 'SEARCH', '搜索词', '查询词', '调用工具',
    )
    fact_markers = (
        '以下是', '要点', '来源', '材料提到', '报道提到', '据', '显示', '表示', '宣布', '称', '指出',
        '1)', '2)', '3)', '4)', '一、', '二、', '三、', '四、', 'http://', 'https://'
    )

    kept = []
    dropped = 0
    max_drop = 8 if aggressive else 4
    dropping = True
    for line in lines:
        stripped = str(line or '').strip()
        if not dropping or not stripped:
            kept.append(line)
            continue
        lower = stripped.lower()
        is_process = _looks_like_process_only_reply(stripped) or any(stripped.startswith(prefix) for prefix in process_prefixes)
        if not is_process and aggressive and ('web_search' in lower or '联网研究' in stripped or '规划搜索' in stripped):
            is_process = not any(marker in stripped for marker in fact_markers)
        if is_process and not any(marker in stripped for marker in fact_markers) and dropped < max_drop:
            dropped += 1
            continue
        dropping = False
        kept.append(line)

    cleaned = ''.join(kept).lstrip()
    cleaned = _strip_leaked_think_tags(cleaned)
    if aggressive:
        cleaned = _strip_leading_grounded_json_blob(cleaned)
        cleaned = _strip_leaked_think_tags(cleaned)
    return cleaned or _strip_leaked_think_tags(raw)
