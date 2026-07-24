# build model-facing Responses function_call_output evidence text.


class ResponsesNativeToolOutputContext:
    def output_text(self, name: str, result, compact, args: dict | None = None, last_user_text: str = '') -> str:
        """Build a plain-text tool evidence block for Responses function_call_output.

        The UI meta event only renders the search/process panel.  The model must
        also receive the same evidence through function_call_output, otherwise it
        can continue as if no realtime result was available.  Keep this text
        explicit and source-oriented so Responses native tool loops ground the
        next streaming round on the actual tool result.
        """
        tool_name = str(name or 'tool').strip() or 'tool'
        args = dict(args or {}) if isinstance(args, dict) else {}

        def _txt(value, limit: int = 1000) -> str:
            try:
                raw = str(value or '').replace('\r\n', '\n').replace('\r', '\n')
            except Exception:
                raw = ''
            raw = re.sub(r'[ \t\f\v]+', ' ', raw).strip()
            raw = re.sub(r'\n{3,}', '\n\n', raw)
            if limit and len(raw) > limit:
                raw = raw[:max(1, int(limit))].rstrip() + '…'
            return raw

        def _json_fallback(obj, limit: int = 12000) -> str:
            try:
                raw = json.dumps(obj, ensure_ascii=False, indent=2)
            except Exception:
                raw = str(obj or '')
            raw = _txt(raw, limit)
            return raw

        lines: list[str] = [
            '【后端工具执行结果 / function_call_output】',
            f'tool: {tool_name}',
            '说明：下面内容是后端刚刚实际执行工具得到的结果，不是模型猜测。继续回答时请基于这些结果；如果这里有搜索结果或网页内容，不要声称“没有拿到实时网页检索结果”。',
        ]
        user_q = _txt(last_user_text, 300)
        if user_q:
            lines.append(f'user_query: {user_q}')

        try:
            evidence_text = _orch_tool_result_evidence_text(
                tool_name,
                result,
                args=args,
                last_user_text=last_user_text,
                phase='responses_function_call_output',
            )
            if evidence_text:
                return evidence_text
        except Exception:
            pass

        try:
            if tool_name == 'save_memory' and isinstance(result, dict):
                lines.append(f'ok: {bool(result.get("ok", True))}')
                if bool(result.get('skipped')):
                    lines.append('memory_status: skipped')
                    reason = _txt(result.get('reason') or '', 200)
                    if reason:
                        lines.append('reason: ' + reason)
                else:
                    ev = result.get('event') if isinstance(result.get('event'), dict) else result
                    title = _txt((ev or {}).get('title') or '已更新记忆', 80)
                    text = _txt((ev or {}).get('text') or '', 260)
                    action = _txt((ev or {}).get('action') or '', 40).lower()
                    if action == 'delete':
                        lines.append('memory_status: deleted')
                    elif action in {'update', 'touch'}:
                        lines.append('memory_status: updated')
                    else:
                        lines.append('memory_status: saved')
                    lines.append('title: ' + title)
                    if text:
                        lines.append('memory: ' + text)
                lines.append('请继续自然回答用户；不要把工具 JSON 或内部记忆字段暴露给用户。')
                return '\n'.join(lines).strip()[:12000]

            if tool_name == 'web_search' and isinstance(result, dict):
                query = _txt(result.get('query') or args.get('query') or '', 300)
                if query:
                    lines.append(f'search_query: {query}')
                results = [dict(x) for x in (result.get('results') or []) if isinstance(x, dict)]
                ok_value = result.get('ok')
                lines.append(f'ok: {bool(ok_value) if ok_value is not None else True}')
                lines.append(f'result_count: {len(results)}')
                if results:
                    lines.append('搜索结果：')
                    for idx, item in enumerate(results[:8], 1):
                        title = _txt(item.get('title') or item.get('name') or '', 220)
                        url = _txt(item.get('url') or item.get('href') or '', 700)
                        snippet = _txt(item.get('snippet') or item.get('summary') or item.get('text') or item.get('content') or '', 900)
                        host = _txt(item.get('host') or item.get('domain') or '', 160)
                        lines.append(f'{idx}. {title or host or url or "未命名结果"}')
                        if host:
                            lines.append(f'   host: {host}')
                        if url:
                            lines.append(f'   url: {url}')
                        if snippet:
                            lines.append(f'   snippet: {snippet}')
                else:
                    err = _txt(result.get('error') or result.get('message') or '', 800)
                    lines.append('搜索结果为空。' + (f' error: {err}' if err else ''))
                return '\n'.join(lines).strip()[:12000]

            if tool_name == 'fetch_url' and isinstance(result, dict):
                lines.append(f'ok: {bool(result.get("ok", True))}')
                url = _txt(result.get('url') or args.get('url') or '', 700)
                title = _txt(result.get('title') or '', 240)
                text = _txt(result.get('text') or result.get('content') or result.get('snippet') or '', 5000)
                err = _txt(result.get('error') or '', 800)
                if title:
                    lines.append(f'title: {title}')
                if url:
                    lines.append(f'url: {url}')
                if text:
                    lines.append('网页正文/摘要：')
                    lines.append(text)
                if err:
                    lines.append(f'error: {err}')
                return '\n'.join(lines).strip()[:12000]

            if tool_name == 'fetch_urls' and isinstance(result, dict):
                pages = result.get('pages') or result.get('results') or []
                pages = [dict(x) for x in pages if isinstance(x, dict)]
                lines.append(f'ok: {bool(result.get("ok", True))}')
                lines.append(f'page_count: {len(pages)}')
                for idx, page in enumerate(pages[:5], 1):
                    title = _txt(page.get('title') or '', 220)
                    url = _txt(page.get('url') or '', 700)
                    text = _txt(page.get('text') or page.get('content') or page.get('snippet') or '', 2500)
                    err = _txt(page.get('error') or '', 500)
                    lines.append(f'{idx}. {title or url or "未命名网页"}')
                    if url:
                        lines.append(f'   url: {url}')
                    if text:
                        lines.append(f'   content: {text}')
                    if err:
                        lines.append(f'   error: {err}')
                return '\n'.join(lines).strip()[:12000]

            if tool_name == 'get_weather' and isinstance(result, dict):
                lines.append(_json_fallback(result, 10000))
                return '\n'.join(lines).strip()[:12000]

            if tool_name == 'image_search' and isinstance(result, dict):
                safe_compact = compact if compact else _compress_tool_result_for_model(tool_name, result, user_text=last_user_text)
                lines.append(_json_fallback(safe_compact, 5000))
                lines.append('output_policy: images are delivered through structured image_reply data; do not output Markdown images, raw image URLs, or source link lists.')
                return '\n'.join(lines).strip()[:12000]

            if tool_name == 'analyze_existing_image' and isinstance(result, dict):
                lines.append(f'ok: {bool(result.get("ok", True))}')
                try:
                    lines.append(f'image_count: {int(result.get("image_count") or 0)}')
                except Exception:
                    lines.append('image_count: 0')
                ids = result.get('selected_image_ids') if isinstance(result.get('selected_image_ids'), list) else []
                if ids:
                    lines.append('selected_image_ids: ' + json.dumps([str(x) for x in ids[:8]], ensure_ascii=False))
                ref = _txt(result.get('image_ref') or '', 300)
                if ref:
                    lines.append(f'image_ref: {ref}')
                if bool(result.get('analysis_deferred_to_responses')):
                    lines.append('status: selected chat/history images were imported into sandbox /mnt/data, then attached as input_image items for the next /responses round.')
                    try:
                        lines.append(f'imported_count: {int(result.get("imported_count") or 0)}')
                    except Exception:
                        pass
                    try:
                        lines.append(f'visual_input_count: {int(result.get("visual_input_count") or 0)}')
                    except Exception:
                        pass
                    stage = _txt(result.get('visual_processing_stage') or '', 160)
                    if stage:
                        lines.append('visual_processing_stage: ' + stage)
                    lines.append('continue_instruction: inspect the attached input_image content directly and answer the user question; do not rely only on the lightweight index.')
                else:
                    try:
                        lines.append(f'imported_count: {int(result.get("imported_count") or 0)}')
                    except Exception:
                        pass
                    try:
                        lines.append(f'analyzed_count: {int(result.get("analyzed_count") or 0)}')
                    except Exception:
                        pass
                    stage = _txt(result.get('visual_processing_stage') or '', 160)
                    if stage:
                        lines.append('visual_processing_stage: ' + stage)
                    analysis = _txt(result.get('analysis') or result.get('message') or result.get('error') or '', 5000)
                    if analysis:
                        lines.append('analysis:')
                        lines.append(analysis)
                return '\n'.join(lines).strip()[:12000]

            if tool_name == 'sandbox_analyze_file_images' and isinstance(result, dict):
                sandbox_visual_rows_limit = _agent_stream_cfg_int('RESPONSES_SANDBOX_VISUAL_ROWS_LIMIT', 24, min_value=4, max_value=80)
                sandbox_visual_evidence_limit = _agent_stream_cfg_int('RESPONSES_SANDBOX_VISUAL_EVIDENCE_MAX_CHARS', 60000, min_value=12000, max_value=200000)
                sandbox_visual_output_limit = _agent_stream_cfg_int('RESPONSES_SANDBOX_VISUAL_OUTPUT_MAX_CHARS', 80000, min_value=16000, max_value=240000)
                lines.append(f'ok: {bool(result.get("ok", True))}')
                lines.append('path: ' + _txt(result.get('path') or args.get('path') or '', 300))
                lines.append('mode: ' + _txt(result.get('mode') or args.get('mode') or '', 80))
                lines.append('endpoint_mode: ' + _txt(result.get('endpoint_mode') or '', 80))
                try:
                    lines.append(f'image_count: {int(result.get("image_count") or 0)}')
                except Exception:
                    lines.append('image_count: 0')
                if bool(result.get('analysis_deferred_to_responses')):
                    try:
                        lines.append(f'visual_input_count: {int(result.get("visual_input_count") or 0)}')
                    except Exception:
                        lines.append('visual_input_count: 0')
                    deferred_to = _txt(result.get('visual_input_deferred_to') or 'responses', 80)
                    if deferred_to:
                        lines.append('visual_input_deferred_to: ' + deferred_to)
                    stage = _txt(result.get('visual_processing_stage') or '', 160)
                    if stage:
                        lines.append('visual_processing_stage: ' + stage)
                    lines.append('sandbox_visual_role: render/select/store images; no pixel interpretation is done inside the sandbox in this lane.')
                    lines.append('model_visual_role: inspect the attached input_image content directly in this same /responses round.')
                    lines.append('status: extracted/rendered pages have been attached as input_image items for the current Responses visual pass.')
                    lines.append('continue_instruction: answer by inspecting the attached input_image content and combining it with text-layer evidence; document figure evidence comes from rendered pages and visible captions. If target_found is false, say the requested figure/page was not located instead of answering from another page. For whole-document review, do not give a shallow summary or generic paper-review template. You must name the rendered page labels/selected_pages you inspected, cite visible text or layout evidence from multiple pages, combine OOXML/text diagnostics such as office_math/media/MERGEFORMAT/formula gaps when present, and give specific fixes tied to those page-level findings.')
                else:
                    try:
                        lines.append(f'analyzed_count: {int(result.get("analyzed_count") or 0)}')
                    except Exception:
                        lines.append('analyzed_count: 0')
                err = _txt(result.get('error') or '', 800)
                if err:
                    lines.append('error: ' + err)
                extract_errors = [str(x or '') for x in (result.get('extract_errors') or []) if str(x or '').strip()]
                if extract_errors:
                    lines.append('extract_errors: ' + json.dumps(extract_errors[:6], ensure_ascii=False))
                diagnostics = result.get('diagnostics') if isinstance(result.get('diagnostics'), dict) else {}
                diagnostic_summary = result.get('diagnostic_summary') if isinstance(result.get('diagnostic_summary'), dict) else {}
                if diagnostic_summary:
                    lines.append('diagnostic_summary:')
                    lines.append(_json_fallback(diagnostic_summary, 12000))
                    if diagnostic_summary.get('render_selected_pages'):
                        lines.append('selected_pages: ' + _json_fallback(diagnostic_summary.get('render_selected_pages'), 500))
                    if diagnostic_summary.get('render_target_found') is not None:
                        lines.append('target_found: ' + str(diagnostic_summary.get('render_target_found')))
                if diagnostics:
                    try:
                        lines.append('diagnostics:')
                        lines.append(_json_fallback(diagnostics, 20000))
                    except Exception:
                        pass
                rows = [dict(x) for x in (result.get('images') or []) if isinstance(x, dict)]
                if rows:
                    lines.append('image_records:')
                    for row in rows[:sandbox_visual_rows_limit]:
                        lines.append('%s. source=%s label=%s path=%s size=%sx%s ok=%s error=%s' % (
                            str(row.get('index') or '?'),
                            _txt(row.get('source') or '', 80),
                            _txt(row.get('label') or '', 180),
                            _txt(row.get('path') or '', 260),
                            str(row.get('width') or 0),
                            str(row.get('height') or 0),
                            str(bool(row.get('ok'))),
                            _txt(row.get('error') or '', 220),
                        ))
                evidence = _txt(result.get('evidence') or '', sandbox_visual_evidence_limit)
                if evidence:
                    lines.append('visual_analysis:')
                    lines.append(evidence)
                return '\n'.join(lines).strip()[:sandbox_visual_output_limit]

            if tool_name == 'search_knowledge_base' and isinstance(result, dict):
                lines.append(f'ok: {bool(result.get("ok", True))}')
                state_obj = result.get('state') if isinstance(result.get('state'), dict) else {}
                if state_obj:
                    lines.append('知识库概况：docs=%s chunks=%s space=%s' % (
                        str(state_obj.get('doc_count') or 0),
                        str(state_obj.get('chunk_count') or 0),
                        _txt(state_obj.get('name') or '', 120),
                    ))
                active_doc = result.get('active_document') if isinstance(result.get('active_document'), dict) else {}
                if active_doc:
                    lines.append('当前绑定文档：' + _txt(active_doc.get('filename') or '', 220))
                rows = [dict(x) for x in (result.get('results') or []) if isinstance(x, dict)]
                lines.append(f'命中片段数: {len(rows)}')
                for idx, item in enumerate(rows[:8], 1):
                    filename = _txt(item.get('filename') or '', 220)
                    citation = _txt(item.get('citation_label') or '', 220)
                    text = _txt(item.get('text') or '', 1600)
                    lines.append(f'{idx}. {filename or "未命名文档"}' + (f' citation={citation}' if citation else ''))
                    if text:
                        lines.append(text)
                err = _txt(result.get('error') or '', 800)
                if err:
                    lines.append(f'error: {err}')
                return '\n'.join(lines).strip()[:12000]

            if tool_name == 'read_knowledge_base_document' and isinstance(result, dict):
                lines.append(f'ok: {bool(result.get("ok", True))}')
                doc = result.get('document') if isinstance(result.get('document'), dict) else {}
                if doc:
                    lines.append('文档：%s doc_id=%s chunks=%s' % (
                        _txt(doc.get('filename') or '', 220),
                        _txt(doc.get('id') or '', 120),
                        str(doc.get('chunk_count') or 0),
                    ))
                coverage = result.get('coverage') if isinstance(result.get('coverage'), dict) else {}
                if coverage:
                    lines.append('读取范围：mode=%s chunks=%s/%s start=%s end=%s truncated=%s full_loaded=%s' % (
                        _txt(coverage.get('mode') or result.get('mode') or '', 80),
                        str(coverage.get('selected_chunk_count') or 0),
                        str(coverage.get('total_chunks') or 0),
                        str(coverage.get('start_chunk') or 0),
                        str(coverage.get('end_chunk') or 0),
                        str(bool(coverage.get('truncated'))),
                        str(bool(coverage.get('full_document_loaded'))),
                    ))
                rows = [dict(x) for x in (result.get('results') or []) if isinstance(x, dict)]
                lines.append(f'读取片段数: {len(rows)}')
                for idx, item in enumerate(rows[:12], 1):
                    citation = _txt(item.get('citation_label') or '', 220)
                    text = _txt(item.get('text') or '', 2200)
                    lines.append(f'{idx}. citation={citation}' if citation else f'{idx}.')
                    if text:
                        lines.append(text)
                if bool(result.get('can_expand')):
                    lines.append('can_expand: true')
                    recs = [dict(x) for x in (result.get('recommended_next_reads') or []) if isinstance(x, dict)][:2]
                    if recs:
                        lines.append('recommended_next_reads: ' + json.dumps(recs, ensure_ascii=False))
                err = _txt(result.get('error') or '', 800)
                if err:
                    lines.append(f'error: {err}')
                return '\n'.join(lines).strip()[:24000]

            # Generic fallback keeps the compact model-safe result but wraps it as
            # explicit evidence instead of an anonymous JSON blob.
            lines.append(_json_fallback(compact if compact is not None else result, 10000))
            return '\n'.join(lines).strip()[:12000]
        except Exception:
            lines.append(_json_fallback(compact if compact is not None else result, 10000))
            return '\n'.join(lines).strip()[:12000]
