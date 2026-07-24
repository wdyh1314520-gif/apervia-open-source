# image URL context and visual/image payload formatting helpers.

def _orch_extract_image_urls_from_content(content) -> list[str]:
    helper = globals().get('_extract_image_urls_from_content')
    if callable(helper):
        try:
            return [str(u or '').strip() for u in (helper(content) or []) if str(u or '').strip()]
        except Exception:
            pass
    urls = []
    def add(u):
        u = str(u or '').strip()
        if u and u not in urls:
            urls.append(u)
    if isinstance(content, list):
        for it in content:
            if not isinstance(it, dict):
                continue
            if it.get('type') == 'image_url':
                add(((it.get('image_url') or {}).get('url')) )
    return urls



def _orch_current_endpoint_mode(client_override=None) -> str:
    helper = globals().get('_visual_current_endpoint_mode')
    if callable(helper):
        try:
            return str(helper(client_override) or '').strip()
        except Exception:
            pass
    try:
        mode = str(getattr(client_override, '_webai_api_endpoint_mode', '') if client_override is not None else '').strip()
        if mode:
            return mode
    except Exception:
        pass
    return ''


def _orch_filter_image_rows_by_endpoint(rows: list | None = None, *, endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[dict]:
    helper = globals().get('_visual_filter_image_rows_for_endpoint')
    if callable(helper):
        try:
            return [dict(r) for r in (helper(rows or [], endpoint_mode=endpoint_mode, allow_legacy=allow_legacy) or []) if isinstance(r, dict)]
        except Exception:
            pass
    return [dict(r) for r in (rows or []) if isinstance(r, dict)]


def _orch_find_recent_context_image_urls(messages: list, limit: int = 4, *, endpoint_mode: str = '', allow_legacy: bool | None = None) -> list[str]:
    helper = globals().get('_find_recent_context_image_urls')
    if callable(helper):
        try:
            rows = [str(u or '').strip() for u in (helper(messages or [], limit=limit, endpoint_mode=endpoint_mode, allow_legacy=allow_legacy) or []) if str(u or '').strip()]
            if rows:
                return rows[:limit]
        except TypeError:
            try:
                rows = [str(u or '').strip() for u in (helper(messages or [], limit=limit) or []) if str(u or '').strip()]
                if rows:
                    return rows[:limit]
            except Exception:
                pass
        except Exception:
            pass
    out = []
    try:
        buckets = []
        for wanted_role in ('user', 'assistant', 'tool'):
            role_urls = []
            for m in reversed(messages or []):
                if not isinstance(m, dict) or m.get('role') != wanted_role:
                    continue
                for u in _orch_extract_image_urls_from_content(m.get('content')):
                    if u not in role_urls:
                        role_urls.append(u)
                    if len(role_urls) >= limit:
                        break
                if len(role_urls) >= limit:
                    break
            buckets.append(role_urls)
        for group in buckets:
            for u in group:
                if u and u not in out:
                    out.append(u)
                if len(out) >= limit:
                    return out[:limit]
    except Exception:
        return out[:limit]
    return out[:limit]


def _orch_build_existing_image_visual_ctx(messages: list, user_text: str = '', *, image_ref: str = '', client_override=None, endpoint_mode: str = '', allow_legacy: bool | None = None) -> dict | None:
    image_ref = str(image_ref or '').strip()
    if not image_ref:
        return None
    resolved_endpoint_mode = str(endpoint_mode or _orch_current_endpoint_mode(client_override) or '').strip()
    builder = globals().get('_build_existing_image_analysis_visual_ctx')
    if callable(builder):
        try:
            built = builder(
                messages or [],
                user_text=user_text,
                image_ref=image_ref,
                model=None,
                client_override=client_override,
                decision={'intent': 'existing_image_analysis', 'reason': 'explicit_image_ref'},
                limit=8,
                endpoint_mode=resolved_endpoint_mode,
                allow_legacy=allow_legacy,
            )
            if isinstance(built, dict) and built.get('urls'):
                return built
        except Exception:
            pass
    return None


def _format_web_grounding_payload_for_model(payload: dict | None = None, *, limit: int = 6) -> str:
    obj = dict(payload or {})
    query = str(obj.get('query') or '').strip()
    queries_used = [str(q or '').strip() for q in (obj.get('queries_used') or []) if str(q or '').strip()]
    cache_hit = bool(obj.get('cache_hit'))
    try:
        result_count = int(obj.get('result_count') or 0)
    except Exception:
        result_count = 0
    try:
        page_count = int(obj.get('page_count') or 0)
    except Exception:
        page_count = 0
    sources = [dict(it) for it in (obj.get('sources') or []) if isinstance(it, dict)]

    lines: list[str] = ['已完成联网检索。']
    if query:
        lines.append(f'主查询：{query}')
    if queries_used:
        lines.append('实际检索：' + '；'.join(queries_used[:4]))
    stats = []
    if result_count > 0:
        stats.append(f'命中结果 {result_count} 条')
    if page_count > 0:
        stats.append(f'读取网页 {page_count} 页')
    if cache_hit:
        stats.append('命中缓存')
    if stats:
        lines.append('检索概况：' + '，'.join(stats))
    if sources:
        lines.append('主要来源：')
        max_rows = max(1, min(int(limit or 6), 10))
        for idx, item in enumerate(sources[:max_rows], 1):
            title = str(item.get('title') or item.get('host') or item.get('url') or '').strip()[:160]
            host = str(item.get('host') or '').strip()[:120]
            url = str(item.get('url') or '').strip()[:500]
            line = f'{idx}. {title}'
            if host and host not in title:
                line += f'（{host}）'
            if url:
                line += f'\n[来源] {url}'
            lines.append(line)
    lines.append('回答时请基于以上来源整理结论，不要原样复述 JSON、字段名或内部结构。')
    return '\n'.join([str(line or '').strip() for line in lines if str(line or '').strip()]).strip()


def _image_generation_artifacts_to_image_reply_payload(artifacts: list | None = None, *, subject: str = '', task_mode: str = '') -> dict:
    images = []
    seen = set()
    _time_mod = globals().get('time') or __import__('time')
    created_at_ms = int(_time_mod.time() * 1000)
    for idx, item in enumerate((artifacts or []), 1):
        if not isinstance(item, dict):
            continue
        filename = str(item.get('filename') or '').strip()
        mime = str(item.get('mime') or '').strip().lower()
        url = str(item.get('view_url') or item.get('url') or item.get('download_url') or '').strip()
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if not url:
            continue
        if not (mime.startswith('image/') or ext in {'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'svg'}):
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        view_url = str(item.get('view_url') or item.get('url') or '').strip()
        download_url = str(item.get('download_url') or '').strip()
        preview_url = str(item.get('preview_url') or '').strip()
        item_created_at_ms = item.get('created_at_ms') or item.get('createdAtMs') or created_at_ms
        raw_source_image_ids = item.get('source_image_ids') or item.get('sourceImageIds') or item.get('derived_from') or item.get('derivedFrom') or []
        if isinstance(raw_source_image_ids, str):
            source_image_ids = [raw_source_image_ids]
        elif isinstance(raw_source_image_ids, list):
            source_image_ids = [str(x or '').strip() for x in raw_source_image_ids if str(x or '').strip()]
        else:
            source_image_ids = []
        parent_image_id = str(item.get('parent_image_id') or item.get('parentImageId') or '').strip()
        if parent_image_id and parent_image_id not in source_image_ids:
            source_image_ids.insert(0, parent_image_id)
        image_obj = {
            'url': preview_url or view_url or download_url or url,
            'raw_url': view_url or download_url or url,
            'view_url': view_url or url,
            'download_url': download_url,
            'preview_url': preview_url,
            'preview_download_url': str(item.get('preview_download_url') or '').strip(),
            'filename': filename,
            'preview_filename': str(item.get('preview_filename') or '').strip(),
            'caption': filename,
            'alt': filename or str(subject or '').strip() or '生成图片',
            'attachment_id': str(item.get('attachment_id') or item.get('id') or '').strip(),
            'source_role': 'assistant',
            'source_type': 'generated',
            'operation': str(item.get('operation') or item.get('task_mode') or task_mode or 'generate').strip() or 'generate',
            'created_at_ms': item_created_at_ms,
            'image_seq': idx,
            'parent_image_id': parent_image_id,
            'source_image_ids': source_image_ids,
            'derived_from': source_image_ids,
        }
        for extra_key in (
            'provider_url', 'proxy_url', 'preview_proxy_url', 'storage_backend',
            'scope', 'mirror_status', 'delivery_mode', 'is_temporary_remote',
            'object_url', 'content_length', 'first_byte_ms', 'download_ms',
            'bytes_per_sec',
        ):
            value = item.get(extra_key)
            if value is not None and str(value).strip() != '':
                image_obj[extra_key] = value
        images.append(image_obj)
    if not images:
        return {}
    return {
        '_kind': 'image_reply',
        'source': 'image_generation',
        'source_role': 'assistant',
        'operation': str(task_mode or 'generate').strip() or 'generate',
        'created_at_ms': created_at_ms,
        'image_seq': 1,
        'subject': str(subject or '').strip(),
        'text': '',
        'images': images,
    }


def _format_image_generation_payload_for_model(payload: dict | None = None, *, limit: int = 4) -> str:
    obj = dict(payload or {})
    subject = str(obj.get('subject') or '').strip()
    ok = bool(obj.get('ok'))
    need_clarification = bool(obj.get('need_clarification'))
    error = str(obj.get('error') or '').strip()
    clarification_question = str(obj.get('clarification_question') or '').strip()
    artifacts = [dict(it) for it in (obj.get('artifacts') or []) if isinstance(it, dict)]

    task_mode = str(obj.get('task_mode') or '').strip().lower()
    tool_title = '图片编辑工具结果：' if task_mode in {'edit', 'image_edit'} else '图片生成工具结果：'
    lines: list[str] = [tool_title]
    if subject:
        lines.append(('用户想修改的内容：' if task_mode in {'edit', 'image_edit'} else '用户想生成的内容：') + subject)
    if ok:
        lines.append('状态：成功。')
        lines.append(f'生成图片数量：{len(artifacts)}')
        if artifacts:
            lines.append('生成图片：')
            for idx, item in enumerate(artifacts[:max(1, min(int(limit or 4), 8))], 1):
                filename = str(item.get('filename') or '').strip()
                view_url = str(item.get('view_url') or item.get('url') or '').strip()
                download_url = str(item.get('download_url') or '').strip()
                desc = f'{idx}. {filename or "未命名图片"}'
                lines.append(desc)
        lines.append('图片已经通过前端图片消息展示；下载入口由图片消息下方的按钮提供。最终回复只需要自然说明已完成，不要在正文输出 /api3/generated-files 或 /api3/generated-download 之类的内部链接。')
    elif need_clarification:
        lines.append('状态：需要用户补充。')
        if clarification_question:
            lines.append('建议追问：' + clarification_question)
        if error:
            lines.append('原因：' + error)
    else:
        lines.append('状态：失败。')
        if error:
            lines.append('错误原文：' + error)
        lines.append('最终回复应继续正常聊天，把失败原因告诉用户；不要编造已经生成成功。')
    return '\n'.join([x for x in lines if str(x or '').strip()]).strip()


def _image_mode_row_log_meta(rows: list | None = None, *, limit: int = 4) -> list[dict]:
    out = []
    for row in list(rows or [])[:max(1, int(limit or 4))]:
        if not isinstance(row, dict):
            continue
        out.append({
            'image_id': str(row.get('image_id') or '')[:80],
            'role_image_id': str(row.get('role_image_id') or '')[:80],
            'role_label': str(row.get('role_label') or '')[:40],
            'global_label': str(row.get('global_label') or '')[:40],
            'recency_rank': row.get('recency_rank'),
            'message_index': row.get('message_index'),
            'binding_mode': str(row.get('binding_mode') or '')[:30],
            'binding_desc': str(row.get('binding_desc') or '')[:80],
        })
    return out


def _summarize_image_task_payload_for_model(payload: dict | None = None) -> str:
    payload = dict(payload or {})
    task_type = str(payload.get('image_task_type') or payload.get('task_type') or '').strip()
    task_mode = str(payload.get('task_mode') or '').strip()
    ok = bool(payload.get('ok'))
    need_clarification = bool(payload.get('need_clarification'))
    error = str(payload.get('error') or '').strip()
    lines = [
        f"图片任务类型：{task_type or 'unknown'}",
        f"任务模式：{task_mode or 'unknown'}",
        f"执行结果：{'ok' if ok else 'not_ok'}",
        f"是否需要澄清：{str(need_clarification).lower()}",
    ]
    if task_type == 'existing_image_analysis':
        analysis_binding = payload.get('analysis_binding') if isinstance(payload.get('analysis_binding'), dict) else {}
        binding_mode = str((analysis_binding or {}).get('binding_mode') or '').strip()
        binding_desc = str((analysis_binding or {}).get('binding_desc') or '').strip()
        bound_rows = _image_mode_row_log_meta((analysis_binding or {}).get('rows') or [], limit=4)
        lines.append('这是已有图片分析，不是新图片生成。')
        if binding_mode:
            lines.append(f'图片绑定模式：{binding_mode}')
        if binding_desc:
            lines.append(f'图片绑定说明：{binding_desc}')
        if bound_rows:
            try:
                lines.append('当前绑定图片：' + json.dumps(bound_rows, ensure_ascii=False))
            except Exception:
                pass
        lines.append('注意：图片内容必须以当前绑定图片本身为准，不要把规划提示词当成图片事实。')
    else:
        subject = str(payload.get('subject') or '').strip()
        if subject:
            lines.append(f'任务主体：{subject[:240]}')
        artifacts = payload.get('artifacts') if isinstance(payload.get('artifacts'), list) else []
        if artifacts:
            brief = []
            for item in artifacts[:6]:
                if not isinstance(item, dict):
                    continue
                brief.append({
                    'filename': str(item.get('filename') or '')[:120],
                    'operation': str(item.get('operation') or '')[:30],
                    'parent_image_id': str(item.get('parent_image_id') or '')[:120],
                    'image_seq': item.get('image_seq'),
                })
            if brief:
                try:
                    lines.append('图片产物：' + json.dumps(brief, ensure_ascii=False))
                except Exception:
                    pass
    if error:
        lines.append('上游错误原文：' + error[:2000])
    attempts = [dict(x) for x in (payload.get('attempts') or []) if isinstance(x, dict)]
    if attempts:
        last_attempt_error = str((attempts[-1] or {}).get('error') or '').strip()
        if last_attempt_error and last_attempt_error != error:
            lines.append('最后一次尝试错误原文：' + last_attempt_error[:1200])
    if not ok:
        evidence = {
            'tool': 'image_generation',
            'ok': False,
            'stage': 'image_generation_failed',
            'upstream_error': error[:2000] if error else '',
        }
        if attempts:
            evidence['attempt_count'] = len(attempts)
            evidence['last_attempt_error'] = str((attempts[-1] or {}).get('error') or '').strip()[:1200]
        try:
            lines.append('结构化失败事实：' + json.dumps(evidence, ensure_ascii=False))
        except Exception:
            lines.append('结构化失败事实：image_generation_failed')
    return '\n'.join([str(x or '').strip() for x in lines if str(x or '').strip()])[:3600]


def _coerce_tool_record_content_for_model(rec: dict | None = None) -> str:
    rec = dict(rec or {})
    name = str(rec.get('name') or 'tool').strip().lower()
    raw_content = rec.get('content')
    if isinstance(raw_content, (dict, list)):
        payload = raw_content
    else:
        content_text = str(raw_content or '').strip()
        payload = content_text
        if content_text and content_text[:1] in '{[':
            try:
                payload = json.loads(content_text)
            except Exception:
                payload = content_text
    if name == 'web_research' and isinstance(payload, dict):
        return _orch_tool_result_evidence_text(name, {'ok': True, 'text': _format_web_grounding_payload_for_model(payload)}, phase='final_answer')
    if name == 'image_generation' and isinstance(payload, dict):
        return _orch_tool_result_evidence_text(name, {'ok': bool(payload.get('ok', True)), 'text': _format_image_generation_payload_for_model(payload), 'error': payload.get('error') or ''}, phase='final_answer')
    if name == 'image_task' and isinstance(payload, dict):
        return _orch_tool_result_evidence_text(name, {'ok': bool(payload.get('ok', True)), 'text': _summarize_image_task_payload_for_model(payload), 'error': payload.get('error') or ''}, phase='final_answer')
    return _orch_tool_result_evidence_text(name, payload, phase='final_answer')
