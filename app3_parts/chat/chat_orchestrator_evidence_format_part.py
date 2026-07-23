# Split from app3_parts/chat/chat_orchestrator_core_part.py.
# Purpose: tool budget and tool-result evidence formatting helpers.
# Loaded by chat_orchestrator_core_part.py via _exec_split_file(...), sharing app3.py globals.

def _orch_compact_text(value, limit: int = 1000) -> str:
    try:
        raw = str(value or '').replace('\r\n', '\n').replace('\r', '\n')
    except Exception:
        raw = ''
    raw = re.sub(r'[ \t\f\v]+', ' ', raw).strip()
    raw = re.sub(r'\n{3,}', '\n\n', raw)
    if limit and len(raw) > int(limit):
        raw = raw[:max(1, int(limit))].rstrip() + '…'
    return raw


def _orch_raw_output_text(value, limit: int = 24000) -> str:
    """Preserve sandbox terminal output exactly for model evidence.

    _orch_compact_text is correct for snippets and planner prose, but it
    collapses tabs/spaces and can make `find -printf` output look different
    from the real terminal result.  Sandbox stdout/stderr and list_files output
    are command evidence; keep newlines, tabs, leading spaces and /mnt/data
    paths unchanged except CRLF normalization, URL/data-url shortening and hard
    truncation.
    """
    try:
        raw = str(value or '').replace('\r\n', '\n').replace('\r', '\n')
    except Exception:
        raw = ''
    raw = re.sub(r'data:image/[^\s)\]]+', '[image]', raw, flags=re.I)
    raw = re.sub(r'https?://[^\s)\]]+', lambda m: m.group(0)[:180], raw)
    lim = max(2000, int(limit or 0))
    if len(raw) <= lim:
        return raw.rstrip('\n')
    keep_head = max(800, lim // 2)
    keep_tail = max(400, lim - keep_head - 100)
    omitted = max(0, len(raw) - keep_head - keep_tail)
    return (raw[:keep_head] + f'\n\n...[已截断 {omitted} 个字符]...\n\n' + raw[-keep_tail:]).rstrip('\n')


def _orch_json_compact(value, limit: int = 4000) -> str:
    try:
        raw = json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(',', ':'))
    except Exception:
        raw = str(value or '')
    return _orch_compact_text(raw, limit)


def _orch_tool_budget(name: str = '', phase: str = 'generic') -> int:
    """Model-facing budgets for already-executed tool evidence.

    Keeps Chat/Responses tool loops fully autonomous while avoiding repeated,
    oversized tool JSON in the next model round. File source/diff tools remain
    intentionally large enough for real code-editing work.
    """
    nm = str(name or '').strip().lower()
    try:
        sandbox_visual_budget = max(16000, min(int(str(app_getenv('RESPONSES_SANDBOX_VISUAL_OUTPUT_MAX_CHARS', '80000') or '80000')), 240000))
    except Exception:
        sandbox_visual_budget = 80000
    budgets = {
        'save_memory': 1400,
        'get_location': 900,
        'location': 900,
        'get_weather': 2800,
        'weather': 2800,
        'web_search': 5000,
        'web_research': 5200,
        'fetch_url': 5200,
        'fetch_urls': 5200,
        'image_search': 4000,
        'analyze_existing_image': 5200,
        'image_generation': 3600,
        'image_task': 3200,
        'search_knowledge_base': 5200,
        'read_knowledge_base_document': 12000,
        'search_account_context': 3600,
        'read_account_context': 5200,
        'sandbox_write_file': 3200,
        'sandbox_replace_text': 3600,
        'sandbox_publish_files': 2200,
        'sandbox_analyze_file_images': sandbox_visual_budget,
    }
    return int(budgets.get(nm, 7000))


def _orch_url_dedupe_key(url: str = '') -> str:
    raw = str(url or '').strip()
    if not raw:
        return ''
    try:
        pu = urlparse(raw)
        scheme = (pu.scheme or 'https').lower()
        host = (pu.netloc or '').lower()
        path = (pu.path or '/').rstrip('/') or '/'
        return urlunparse((scheme, host, path, '', '', ''))
    except Exception:
        return raw.lower()


def _orch_tool_result_evidence_text(name: str = 'tool', result=None, *, args: dict | None = None, last_user_text: str = '', phase: str = 'generic') -> str:
    """Return a compact, stable evidence block for tool results.

    This is not a tool-routing rule. It only normalizes already-executed tool
    results so both Chat and Responses lanes feed the model a consistent digest
    instead of large, noisy JSON with repeated fields.
    """
    tool_name = str(name or 'tool').strip() or 'tool'
    nm = tool_name.lower()
    args = dict(args or {}) if isinstance(args, dict) else {}
    payload = result
    if isinstance(payload, str):
        text = payload.strip()
        if text and text[:1] in '{[':
            try:
                payload = json.loads(text)
            except Exception:
                payload = text
    lines: list[str] = ['[tool_evidence_v1]', f'tool: {tool_name}']
    user_q = _orch_compact_text(last_user_text, 240)
    if user_q:
        lines.append('user_query: ' + user_q)

    if isinstance(payload, dict):
        ok_raw = payload.get('ok')
        if ok_raw is not None:
            lines.append('ok: ' + str(bool(ok_raw)))
        err = _orch_compact_text(payload.get('error') or payload.get('message') or '', 800)
        if err:
            lines.append('error: ' + err)

        if nm == 'save_memory':
            if bool(payload.get('skipped')):
                lines.append('memory_status: skipped')
                reason = _orch_compact_text(payload.get('reason') or '', 160)
                if reason:
                    lines.append('reason: ' + reason)
            else:
                ev = payload.get('event') if isinstance(payload.get('event'), dict) else payload
                action = _orch_compact_text((ev or {}).get('action') or '', 40).lower()
                lines.append('memory_status: ' + ('deleted' if action == 'delete' else ('updated' if action in {'update', 'touch'} else 'saved')))
                title = _orch_compact_text((ev or {}).get('title') or '已更新记忆', 80)
                text = _orch_compact_text((ev or {}).get('text') or '', 260)
                if title:
                    lines.append('title: ' + title)
                if text:
                    lines.append('memory: ' + text)
            return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

        if nm == 'web_search':
            query = _orch_compact_text(payload.get('query') or args.get('query') or '', 260)
            if query:
                lines.append('query: ' + query)
            rows = [dict(x) for x in (payload.get('results') or []) if isinstance(x, dict)]
            lines.append('item_count: ' + str(len(rows)))
            seen_urls: set[str] = set()
            for idx, item in enumerate(rows[:6], 1):
                title = _orch_compact_text(item.get('title') or item.get('name') or '', 180)
                url = _orch_compact_text(item.get('url') or item.get('href') or '', 500)
                host = _orch_compact_text(item.get('host') or item.get('domain') or '', 120)
                snippet = _orch_compact_text(item.get('snippet') or item.get('summary') or item.get('text') or item.get('content') or '', 520)
                key = _orch_url_dedupe_key(url)
                if key and key in seen_urls:
                    continue
                if key:
                    seen_urls.add(key)
                lines.append(f'item {idx}:')
                lines.append('  title: ' + (title or host or url or 'untitled'))
                if host:
                    lines.append('  host: ' + host)
                if url:
                    lines.append('  url: ' + url)
                if snippet:
                    lines.append('  evidence: ' + snippet)
            return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

        if nm == 'fetch_url':
            title = _orch_compact_text(payload.get('title') or '', 220)
            url = _orch_compact_text(payload.get('url') or args.get('url') or '', 500)
            text = _orch_compact_text(payload.get('text') or payload.get('content') or payload.get('snippet') or '', 3600)
            if title:
                lines.append('title: ' + title)
            if url:
                lines.append('url: ' + url)
            if text:
                lines.append('evidence:')
                lines.append(text)
            return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

        if nm == 'fetch_urls':
            pages = payload.get('pages') or payload.get('results') or []
            pages = [dict(x) for x in pages if isinstance(x, dict)]
            lines.append('page_count: ' + str(len(pages)))
            seen_urls: set[str] = set()
            for idx, page in enumerate(pages[:4], 1):
                title = _orch_compact_text(page.get('title') or '', 180)
                url = _orch_compact_text(page.get('url') or '', 500)
                key = _orch_url_dedupe_key(url)
                if key and key in seen_urls:
                    continue
                if key:
                    seen_urls.add(key)
                text = _orch_compact_text(page.get('text') or page.get('content') or page.get('snippet') or '', 1800)
                perr = _orch_compact_text(page.get('error') or '', 300)
                lines.append(f'page {idx}: ' + (title or url or 'untitled'))
                if url:
                    lines.append('  url: ' + url)
                if text:
                    lines.append('  evidence: ' + text)
                if perr:
                    lines.append('  error: ' + perr)
            return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

        if nm == 'image_search':
            query = _orch_compact_text(payload.get('query') or args.get('query') or '', 260)
            if query:
                lines.append('query: ' + query)
            image_payload = payload.get('image_reply_payload') if isinstance(payload.get('image_reply_payload'), dict) else {}
            image_items = image_payload.get('images') if isinstance(image_payload.get('images'), list) else []
            rows = [dict(x) for x in (payload.get('results') or image_items or []) if isinstance(x, dict)]
            lines.append('item_count: ' + str(len(rows)))
            lines.append('ui_delivery: structured_image_reply')
            lines.append('output_policy: do not output Markdown images, raw image URLs, or source link lists; the UI already renders the images.')

            def _image_source_host(item: dict) -> str:
                raw = str(item.get('source_url') or item.get('page_url') or item.get('source') or item.get('domain') or '').strip()
                if not raw:
                    return ''
                try:
                    if '://' in raw:
                        return (urlparse(raw).hostname or '').lower().strip('.')[:120]
                except Exception:
                    pass
                return re.sub(r'[^A-Za-z0-9._-]+', '', raw).lower()[:120]

            for idx, item in enumerate(rows[:6], 1):
                title = _orch_compact_text(item.get('title') or item.get('alt') or item.get('caption') or '', 160)
                host = _orch_compact_text(_image_source_host(item), 120)
                lines.append(f'item {idx}:')
                if title:
                    lines.append('  title: ' + title)
                if host:
                    lines.append('  source_host: ' + host)
            return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

        if nm in {'get_weather', 'get_location'}:
            lines.append('payload: ' + _orch_json_compact(payload, 6500))
            return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

        if nm == 'analyze_existing_image':
            try:
                lines.append('image_count: ' + str(int(payload.get('image_count') or 0)))
            except Exception:
                lines.append('image_count: 0')
            ids = payload.get('selected_image_ids') if isinstance(payload.get('selected_image_ids'), list) else []
            if ids:
                lines.append('selected_image_ids: ' + ', '.join(str(x) for x in ids[:8]))
            if bool(payload.get('analysis_deferred_to_responses')):
                lines.append('status: selected chat/history images were imported into sandbox /mnt/data, then attached as input_image items for the next Responses round; inspect attached pixels directly.')
                try:
                    lines.append('imported_count: ' + str(int(payload.get('imported_count') or 0)))
                except Exception:
                    pass
                try:
                    lines.append('visual_input_count: ' + str(int(payload.get('visual_input_count') or 0)))
                except Exception:
                    pass
                stage = _orch_compact_text(payload.get('visual_processing_stage') or '', 160)
                if stage:
                    lines.append('visual_processing_stage: ' + stage)
            else:
                try:
                    lines.append('imported_count: ' + str(int(payload.get('imported_count') or 0)))
                except Exception:
                    pass
                try:
                    lines.append('analyzed_count: ' + str(int(payload.get('analyzed_count') or 0)))
                except Exception:
                    pass
                stage = _orch_compact_text(payload.get('visual_processing_stage') or '', 160)
                if stage:
                    lines.append('visual_processing_stage: ' + stage)
                analysis = _orch_compact_text(payload.get('analysis') or payload.get('message') or '', 3600)
                if analysis:
                    lines.append('analysis:')
                    lines.append(analysis)
            return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

        if nm == 'search_knowledge_base':
            state_obj = payload.get('state') if isinstance(payload.get('state'), dict) else {}
            if state_obj:
                lines.append('kb_state: docs=%s chunks=%s space=%s' % (str(state_obj.get('doc_count') or 0), str(state_obj.get('chunk_count') or 0), _orch_compact_text(state_obj.get('name') or '', 80)))
            rows = [dict(x) for x in (payload.get('results') or []) if isinstance(x, dict)]
            lines.append('hit_count: ' + str(len(rows)))
            for idx, item in enumerate(rows[:6], 1):
                filename = _orch_compact_text(item.get('filename') or '', 160)
                citation = _orch_compact_text(item.get('citation_label') or '', 160)
                text = _orch_compact_text(item.get('text') or '', 1000)
                lines.append(f'hit {idx}: ' + (filename or 'untitled') + (f' citation={citation}' if citation else ''))
                if text:
                    lines.append('  evidence: ' + text)
            return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

        if nm == 'read_knowledge_base_document':
            doc = payload.get('document') if isinstance(payload.get('document'), dict) else {}
            if doc:
                lines.append('document: %s doc_id=%s chunks=%s' % (_orch_compact_text(doc.get('filename') or '', 180), _orch_compact_text(doc.get('id') or '', 100), str(doc.get('chunk_count') or 0)))
            coverage = payload.get('coverage') if isinstance(payload.get('coverage'), dict) else {}
            if coverage:
                lines.append('coverage: mode=%s chunks=%s/%s start=%s end=%s truncated=%s full_loaded=%s' % (_orch_compact_text(coverage.get('mode') or payload.get('mode') or '', 60), str(coverage.get('selected_chunk_count') or 0), str(coverage.get('total_chunks') or 0), str(coverage.get('start_chunk') or 0), str(coverage.get('end_chunk') or 0), str(bool(coverage.get('truncated'))), str(bool(coverage.get('full_document_loaded')))))
            rows = [dict(x) for x in (payload.get('results') or []) if isinstance(x, dict)]
            lines.append('chunk_count: ' + str(len(rows)))
            for idx, item in enumerate(rows[:10], 1):
                citation = _orch_compact_text(item.get('citation_label') or '', 160)
                text = _orch_compact_text(item.get('text') or '', 1600)
                lines.append(f'chunk {idx}' + (f' citation={citation}' if citation else '') + ':')
                if text:
                    lines.append(text)
            if bool(payload.get('can_expand')):
                lines.append('can_expand: true')
                recs = [dict(x) for x in (payload.get('recommended_next_reads') or []) if isinstance(x, dict)][:2]
                if recs:
                    lines.append('recommended_next_reads: ' + _orch_json_compact(recs, 900))
            return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

        if nm == 'sandbox_list_files':
            command = _orch_compact_text(payload.get('list_command') or payload.get('command') or args.get('command') or '', 1200)
            if command:
                lines.append('command: ' + command)
            if payload.get('count') is not None:
                lines.append('count: ' + str(payload.get('count')))
            if payload.get('file_count') is not None:
                lines.append('file_count: ' + str(payload.get('file_count')))
            if payload.get('dir_count') is not None:
                lines.append('dir_count: ' + str(payload.get('dir_count')))
            list_output = _orch_raw_output_text(payload.get('list_output') or payload.get('stdout') or '', 24000)
            if list_output:
                lines.append('stdout:')
                lines.append(list_output)
            else:
                rows = [dict(x) for x in (payload.get('files') or []) if isinstance(x, dict)]
                if rows:
                    lines.append('files:')
                    for idx, item in enumerate(rows[:80], 1):
                        typ = str(item.get('type') or '').strip()[:20]
                        path = str(item.get('mount_path') or item.get('path') or '').strip()[:500]
                        size = str(item.get('size') or 0)
                        lines.append(f'{idx}. type={typ} path={path} size={size}')
            return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

        if nm == 'sandbox_run':
            command = _orch_compact_text(payload.get('command') or args.get('command') or '', 500)
            if command:
                lines.append('command: ' + command)
            if payload.get('exit_code') is not None:
                lines.append('exit_code: ' + str(payload.get('exit_code')))
            if bool(payload.get('stdin_used')):
                lines.append('stdin_used: true')
            if bool(payload.get('stdin_normalized')):
                lines.append('stdin_normalized: true')
            stdout = _orch_raw_output_text(payload.get('stdout') or '', 24000)
            stderr = _orch_raw_output_text(payload.get('stderr') or '', 12000)
            if stdout:
                lines.append('stdout:')
                lines.append(stdout)
            if stderr:
                lines.append('stderr:')
                lines.append(stderr)
            output_paths = [str(x or '').strip() for x in (payload.get('output_paths') or []) if str(x or '').strip()]
            created_paths = [str(x or '').strip() for x in (payload.get('created_paths') or []) if str(x or '').strip()]
            changed_paths = [str(x or '').strip() for x in (payload.get('changed_paths') or []) if str(x or '').strip()]
            if output_paths:
                lines.append('output_paths: ' + ', '.join(output_paths[:12]))
            elif created_paths:
                lines.append('created_paths: ' + ', '.join(created_paths[:12]))
            elif changed_paths:
                lines.append('changed_paths: ' + ', '.join(changed_paths[:12]))
            if output_paths or created_paths or changed_paths:
                lines.append('link_policy: these are sandbox /mnt/data paths, not download links. Do not print /api3/generated-download or Markdown download links from filenames. Call sandbox_publish_files first, then use only its download_url for user-facing links.')
                lines.append('next: call sandbox_publish_files with output_paths when the user needs a downloadable file.')
            failure_instruction = _orch_compact_text(payload.get('failure_instruction') or '', 260)
            if failure_instruction:
                lines.append('failure_instruction: ' + failure_instruction)
            return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

        if nm == 'sandbox_publish_files':
            rows = [dict(x) for x in (payload.get('files') or []) if isinstance(x, dict)]
            source_rows = [dict(x) for x in (payload.get('source_files') or []) if isinstance(x, dict)]
            lines.append('file_count: ' + str(len(rows)))
            lines.append('link_policy: use only download_url below for user-facing download links; do not use object_url/storage backend URLs. If a zip and source files are both listed, choose the link matching the user request.')
            for idx, item in enumerate(rows[:12], 1):
                filename = _orch_compact_text(item.get('filename') or item.get('display_filename') or '', 220)
                download_url = _orch_compact_text(item.get('download_url') or '', 500)
                view_url = _orch_compact_text(item.get('view_url') or '', 500)
                size = item.get('size')
                lines.append(f'file {idx}: ' + (filename or 'untitled'))
                if download_url:
                    lines.append('  download_url: ' + download_url)
                if view_url:
                    lines.append('  view_url: ' + view_url)
                if size not in (None, ''):
                    lines.append('  size: ' + str(size))
            if source_rows:
                lines.append('source_file_count: ' + str(len(source_rows)))
                shown = {str((item.get('download_url') or item.get('filename') or '')).strip().lower() for item in rows}
                for idx, item in enumerate(source_rows[:12], 1):
                    marker = str((item.get('download_url') or item.get('filename') or '')).strip().lower()
                    if marker and marker in shown:
                        continue
                    filename = _orch_compact_text(item.get('filename') or item.get('display_filename') or '', 220)
                    download_url = _orch_compact_text(item.get('download_url') or '', 500)
                    view_url = _orch_compact_text(item.get('view_url') or '', 500)
                    if not (filename or download_url or view_url):
                        continue
                    lines.append(f'source_file {idx}: ' + (filename or 'untitled'))
                    if download_url:
                        lines.append('  download_url: ' + download_url)
                    if view_url:
                        lines.append('  view_url: ' + view_url)
            return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

        lines.append('payload: ' + _orch_json_compact(payload, _orch_tool_budget(nm, phase) - 200))
        return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]

    if isinstance(payload, list):
        lines.append('payload: ' + _orch_json_compact(payload, _orch_tool_budget(nm, phase) - 200))
    else:
        text = _orch_compact_text(payload, _orch_tool_budget(nm, phase) - 200)
        if text:
            lines.append('text: ' + text)
    return '\n'.join(lines).strip()[:_orch_tool_budget(nm, phase)]
