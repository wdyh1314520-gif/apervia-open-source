# Split from app3_parts/chat/chat_weather_routes_part.py.
# Purpose: streaming chat route and public async bridge.
# Loaded by chat_weather_routes_part.py via _exec_split_file(...), sharing app3.py globals.

@app.post("/api3/chat_stream")
def chat_stream_gpt():
    if _is_public_request_scope():
        payload = request.get_json(force=True, silent=True) or {}
        payload.pop('mcp_servers', None)
        try:
            enricher = globals().get('_enrich_location_payload_from_request')
            if callable(enricher):
                payload = enricher(payload)
        except Exception:
            pass
        limit_resp = _apply_rate_limit('chat_stream')
        if limit_resp is not None:
            return limit_resp
        owner = _chat_async_owner_snapshot()
        busy_resp = _chat_async_busy_response(owner)
        if busy_resp is not None:
            return busy_resp
        rec = _chat_async_create_job(payload, owner=owner)
        job_id = str(rec.get('job_id') or '')
        worker = threading.Thread(target=_chat_async_worker, args=(job_id,), daemon=True)
        with _CHAT_ASYNC_JOB_LOCK:
            runtime = _CHAT_ASYNC_JOB_RUNTIME.setdefault(job_id, {})
            runtime['thread'] = worker
        worker.start()

        @stream_with_context
        def public_async_sse_bridge():
            cursor = 0
            last_ping = 0.0
            yielded_done = False
            yield ": public async bridge\n\n"
            yield sse("status", {"text": "公网稳定通道已连接，正在处理…"})
            while True:
                now = time.time()
                events = []
                done = False
                with _CHAT_ASYNC_JOB_LOCK:
                    rec2 = _CHAT_ASYNC_JOBS.get(job_id)
                    if rec2 is None:
                        events = [{'seq': cursor + 1, 'event': 'error', 'payload': {'error': '任务不存在或已过期'}}]
                        done = True
                    else:
                        events = [dict(item) for item in list(rec2.get('events') or []) if int((item or {}).get('seq') or 0) > cursor][:160]
                        done = bool(rec2.get('done'))

                if events:
                    for item in events:
                        try:
                            seq = int(item.get('seq') or 0)
                        except Exception:
                            seq = cursor + 1
                        cursor = max(cursor, seq)
                        event_name = str(item.get('event') or 'message')
                        payload_obj = dict(item.get('payload') or {})
                        if event_name == 'done':
                            yielded_done = True
                        yield sse(event_name, payload_obj)

                if done:
                    if not yielded_done:
                        yield sse('done', {})
                    break

                if now - last_ping >= 2.5:
                    last_ping = now
                    yield ": ping\n\n"

                cond = _chat_async_job_cond(job_id)
                try:
                    with cond:
                        cond.wait(timeout=1.5)
                except Exception:
                    time.sleep(0.5)

        return Response(
            public_async_sse_bridge(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "X-WebAI-Transport": "chat-async-sse-bridge",
            },
        )

    payload = request.get_json(force=True, silent=True) or {}
    payload.pop('mcp_servers', None)
    try:
        enricher = globals().get('_enrich_location_payload_from_request')
        if callable(enricher):
            payload = enricher(payload)
    except Exception:
        pass
    limit_resp = _apply_rate_limit('chat_stream')
    if limit_resp is not None:
        return limit_resp
    req_ctx = _chat_request_context_from_payload(payload, source='chat_stream')
    user_text = str(req_ctx.get('user_text') or '')
    model = str(req_ctx.get('model') or app_getenv("GPT_MODEL", "gpt-5.4-nano") or '').strip()
    show_steps = bool(req_ctx.get('show_steps', True))
    history = list(req_ctx.get('history') or [])
    label = str(req_ctx.get('label') or '')
    user_geo = payload.get("user_geo") or None
    user_time = _normalize_runtime_time_payload(payload.get("user_time"))
    debug_geo_meta = payload.get("debug_geo_meta") if isinstance(payload.get("debug_geo_meta"), dict) else {}
    try:
        if debug_geo_meta and (bool(debug_geo_meta.get('is_weather_query')) or bool(debug_geo_meta.get('is_location_query')) or not isinstance(user_geo, dict)):
            browser_geo = debug_geo_meta.get('browser_geo') if isinstance(debug_geo_meta.get('browser_geo'), dict) else None
            brief_meta = {
                'is_weather_query': bool(debug_geo_meta.get('is_weather_query')),
                'is_location_query': bool(debug_geo_meta.get('is_location_query')),
                'is_weather_followup': bool(debug_geo_meta.get('is_weather_followup')),
                'need_fresh_geo': bool(debug_geo_meta.get('need_fresh_geo')),
                'geo_source': str(debug_geo_meta.get('geo_source') or '')[:40],
                'browser_geo': browser_geo,
            }
            app_logger.warning('[DEBUG_CHAT_STREAM_GEO] user_geo=%s meta=%s', _geo_debug_brief(user_geo), brief_meta)
    except Exception:
        pass
    disable_tools = bool(payload.get("disable_tools", False))
    skip_prepare_messages = bool(payload.get("skip_prepare_messages", False))
    disable_visual_prefetch = bool(payload.get("disable_visual_prefetch", False))

    # Early SSE: connect first, then do the heavy work inside the generator
    @stream_with_context
    def gen():
        yield ": ping\n\n"
        if show_steps:
            yield sse("status", {"text": f"{label} 已连接，准备中…"})
        try:
            kb_direct_reply = _kb_try_direct_existing_file_reply(
                query=user_text,
                kb_enabled=payload.get("kb_enabled", True),
                kb_space_id=str(payload.get("kb_space_id") or ''),
                kb_doc_id=str(payload.get("kb_doc_id") or ''),
            )
            if kb_direct_reply:
                if show_steps:
                    yield sse("status", {"text": f"{label} 已锁定知识库文档，正在直接回答…"})
                yield sse("delta", {"text": str(kb_direct_reply.get("reply") or '')})
                yield sse("meta", {"model": model, "mode": str(kb_direct_reply.get("mode") or 'kb_direct_existing_file'), "kb_result_count": int(kb_direct_reply.get("result_count") or 0)})
                yield sse("done", {})
                return

            # 不再在进入模型前走“天气卡片快路径”或地点澄清兜底。
            # 是否需要查天气/联网，统一交给模型在单轮工具判断里决定。

            # Prepare messages (may trigger web_search). Give the UI feedback.
            if show_steps:
                yield sse("status", {"text": f"{label} 正在整理对话与联网信息…"})
            messages = list(req_ctx.get('messages') or [])
            messages = _merge_payload_file_attachments_into_messages(messages, payload, source='chat_stream')
            messages = _inject_runtime_time_context(messages, user_time=user_time)
            api_endpoint_mode = str(req_ctx.get('api_endpoint_mode') or _api_endpoint_mode_from_payload(payload))
            temporary_chat = bool(req_ctx.get('temporary_chat'))
            prepare_skip = _prepare_skip_decision_for_endpoint(api_endpoint_mode, disable_tools=disable_tools, skip_prepare_messages=skip_prepare_messages)
            direct_agent_skip_prepare = bool(prepare_skip.get('direct_agent_skip_prepare'))
            effective_skip_prepare_messages = bool(prepare_skip.get('effective_skip_prepare_messages'))
            if not effective_skip_prepare_messages:
                messages = _prepare_messages(
                    messages,
                    user_geo=user_geo,
                    web_enabled=payload.get("web_enabled"),
                    web_k=payload.get("web_k"),
                    web_max_pages=payload.get("web_max_pages"),
                    kb_enabled=payload.get("kb_enabled", True),
                    kb_space_id=str(payload.get("kb_space_id") or ''),
                    kb_doc_id=str(payload.get("kb_doc_id") or ''),
                )
            if temporary_chat:
                backend_personalization_meta = {'available': False, 'source': 'temporary_chat_disabled'}
            else:
                messages, backend_personalization_meta = _inject_auth_personalization_memory(messages)
            if show_steps and backend_personalization_meta.get('source') == 'backend_injected':
                yield sse("status", {"text": f"{label} 已载入账号记忆…"})
            if show_steps:
                yield sse("status", {"text": f"{label} 准备完成，开始生成…"})
            # Now stream the final answer (tool self-decision for every turn)
            client_override = _client_for_payload(payload)
            api_endpoint_mode = _api_endpoint_mode_from_payload(payload)
            request_overrides = _extract_request_overrides(payload)
            request_overrides = _enforce_request_override_policy(payload, request_overrides)
            _set_request_overrides(request_overrides)
            app_logger.warning(
                "[DEBUG_REQUEST_OVERRIDES_SET] route=/api3/chat_stream fallback=%r serper_key_len=%s keys=%s",
                app_getenv("SEARCH_FALLBACK_PROVIDER", "serper"),
                len(app_getenv("SERPER_API_KEY", "").strip()),
                sorted(request_overrides.keys()),
            )
            yield from _chat_stream_gen(
                model,
                messages,
                show_steps,
                label,
                user_geo=user_geo,
                user_time=user_time,
                client_override=client_override,
                api_endpoint_mode=api_endpoint_mode,
                enable_tools=not disable_tools,
                enable_visual=not disable_visual_prefetch,
                web_enabled=payload.get("web_enabled"),
                web_k=payload.get("web_k"),
                web_max_pages=payload.get("web_max_pages"),
                image_generation_enabled=bool(payload.get("image_generation_enabled")),
                image_generation_settings=_normalize_image_generation_settings(payload.get("image_generation_settings")),
                initial_prepare_skipped=bool(direct_agent_skip_prepare),
                kb_enabled=payload.get("kb_enabled", True),
                kb_space_id=str(payload.get("kb_space_id") or ''),
                kb_doc_id=str(payload.get("kb_doc_id") or ''),
                runtime_model=str(payload.get("runtime_model") or '').strip(),
                temporary_chat=temporary_chat,
                client_session_id=str(payload.get("client_session_id") or payload.get("session_id") or payload.get("active_session_id") or '').strip(),
                client_session_title=str(payload.get("client_session_title") or payload.get("session_title") or '').strip(),
                mcp_owner_email=str(_current_login_email() or '').strip().lower(),
            )
        except Exception as e:
            app_logger.exception("chat_stream_gpt error")
            yield sse("error", {"error": f"AI服务异常：{type(e).__name__}: {e}"})
            yield sse("done", {})
            return
        finally:
            _set_request_overrides({})

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
