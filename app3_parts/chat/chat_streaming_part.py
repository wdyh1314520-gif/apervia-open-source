# Split from app3_parts/chat/chat_orchestrator_part.py.
# Purpose: main streaming chat generator and streaming response orchestration.
# Loaded by app3.py via _exec_split_file(...), sharing the original global namespace.
#
# 文件头目录（仅注释，不改变执行逻辑）：
# - 主入口：_chat_stream_gen(...)；/api3/chat_stream 与 chat_async worker 最终都会进入这里附近的流式链路。
# - 入口准备：开头处理 runtime location、temporary_chat、runtime_model、外部 image_assets 注入。
# - 流式基础工具：约 120-640 行，处理 Chat/Responses 模式、文本/推理 delta 抽取、停止信号、重试与 stream 打开。
# - Responses native lane：约 650-1650 行，处理 capability loader、image task selector、图片索引、Responses 工具选择。
# - 工具规格与工具执行：约 1650 行后开始组装本轮可用工具，实际工具分发依赖 file_registry_edit_tools_part.py 的 _exec_tool(...)。
# - 文件/图片交付桥：中段大量处理 selected image ids、image_generation handoff、生成结果映射和 tool result compact。
# - SSE 输出：搜索 `yield sse`；最终前端事件由 index3-async-chat-stream-ui.js 消费并落到 renderChat。
# - Responses 事件循环：搜索 `response.completed`、`function_call`、`image_generation_call`，排查 Responses 兼容中转优先看这里。
# - 天气结构化输出：搜索 `weather_payload`；天气卡片渲染失败时同时看 chat_weather_routes_part.py。
# - 高风险点：这个文件基本都在一个大函数里，新增 helper 时要确认闭包变量、停止信号、SSE 事件名和 Chat/Responses 两条 lane 是否互相污染。

def _chat_stream_gen(model: str, messages: list, show_steps: bool, label: str, user_geo: dict | None = None, user_time: dict | None = None, client_override=None, api_endpoint_mode: str = 'chat_completions', enable_tools: bool = True, enable_visual: bool = True, web_enabled: bool | None = None, web_k: int | None = None, web_max_pages: int | None = None, image_generation_enabled: bool = False, image_generation_settings: dict | None = None, initial_prepare_skipped: bool = False, kb_enabled: bool | None = True, kb_space_id: str = '', kb_doc_id: str = '', runtime_model: str = '', temporary_chat: bool = False, image_assets: list | None = None, debug_geo_meta: dict | None = None, location_state: dict | None = None, client_session_id: str = '', client_session_title: str = '', mcp_owner_email: str = ''):
    """Generator that yields SSE frames for a prepared message list."""
    import time
    import json
    import re

    def _sandbox_file_evidence_policy_text() -> str:
        runtime_policy = globals().get('tool_policy_runtime_prompt')
        if callable(runtime_policy):
            try:
                text = str(runtime_policy() or '').strip()
                if text:
                    return text
            except Exception:
                pass
        expand = False
        try:
            getenv = globals().get('app_getenv')
            raw = str(getenv('APP3_EXPAND_TOOL_POLICY_PROMPTS', '') if callable(getenv) else '').strip().lower()
            expand = raw in {'1', 'true', 'yes', 'on'}
        except Exception:
            expand = False
        if not expand:
            return (
                '文件证据策略：先导入 sandbox /mnt/data；文本/表格/Office 内容先 sandbox_read_file，'
                '图表/扫描/版式/截图再用 sandbox_analyze_file_images；diff 先 resolve 再 diff；'
                '执行/测试/grep/find/复杂统计才用 sandbox_run；生成后 publish。'
            )
        parts = []
        for fn_name in ('task_intent_policy_prompt', 'agent_loop_policy_prompt', 'tool_policy_prompt', 'evidence_ledger_policy_prompt', 'web_evidence_policy_prompt', 'file_evidence_policy_prompt', 'file_context_policy_prompt', 'file_diff_policy_prompt', 'artifact_task_policy_prompt', 'sandbox_execution_policy_prompt', 'artifact_manager_policy_prompt'):
            fn = globals().get(fn_name)
            if callable(fn):
                try:
                    text = str(fn() or '').strip()
                    if text:
                        parts.append(text)
                except Exception:
                    pass
        if parts:
            return '\n'.join(parts)
        return (
            '文件证据策略：纯图片直接视觉；Office/表格/文本先读文本层或结构化文本；'
            '视觉/版式/图表/扫描页再补 sandbox_analyze_file_images；sandbox_run 只用于真实执行、测试、grep/find、复杂统计校验或生成产物。'
        )

    messages = _inject_runtime_location_visibility_context(
        list(messages or []),
        user_geo=user_geo,
        user_time=user_time,
        debug_geo_meta=debug_geo_meta,
        location_state=location_state,
    )
    temporary_chat = bool(temporary_chat)
    runtime_model_state = ChatStreamRuntimeModelState(runtime_model)

    def _remember_runtime_model(value) -> str:
        return runtime_model_state.remember(value)

    def _current_runtime_model() -> str:
        return runtime_model_state.current()

    def _main_chat_runtime_model_for_context() -> str:
        return runtime_model_state.context_model()

    def _current_runtime_model_meta() -> dict:
        return runtime_model_state.meta()

    _t_gen0 = time.time()
    turn_context = ChatStreamTurnContext(
        messages=messages,
        client_session_id=client_session_id,
        client_session_title=client_session_title,
        started_at=_t_gen0,
    )
    client_session_id = turn_context.client_session_id
    client_session_title = turn_context.client_session_title
    activity_turn_id = turn_context.activity_turn_id
    external_image_asset_messages = turn_context.build_external_image_asset_messages(image_assets, client_override=client_override)
    turn_context.log_external_image_assets()

    def _agent_stream_messages_for_image_index(base_messages: list | None = None) -> list:
        return turn_context.messages_for_image_index(base_messages)


    native_reasoning_seen = False
    native_reasoning_source = ''
    native_reasoning_text_accum = ''
    native_reasoning_html_comment_pending = ''
    native_reasoning_html_comment_open = False
    activity_context = ChatStreamActivityContext(
        client_session_id=client_session_id,
        client_session_title=client_session_title,
        activity_turn_id=activity_turn_id,
    )

    def _sync_activity_timeline_seq_from_state(state: dict | None = None) -> None:
        activity_context.sync_seq_from_state(state)

    def _next_activity_timeline_seq(state: dict | None = None) -> int:
        return activity_context.next_seq(state)

    def _last_activity_timeline_seq(state: dict | None = None) -> int:
        return activity_context.last_seq(state)
    api_endpoint_mode = _normalize_chat_api_endpoint_mode(api_endpoint_mode)
    responses_mode = api_endpoint_mode == 'responses'
    mcp_attach = globals().get('_mcp_client_attach_runtime')
    if callable(mcp_attach):
        server_loader = globals().get('_mcp_client_servers_for_owner')
        servers = server_loader(mcp_owner_email, include_secret=True) if callable(server_loader) and str(mcp_owner_email or '').strip() else []
        mcp_attach(client_override, servers)
    # Responses 模式优先走原生 direct-first tool loop：主模型先流式启动，
    # 由同一个 /v1/responses 会话按需发 function_call，后端执行工具后用
    # 无状态 function_call + function_call_output replay 继续流式。
    try:
        app_logger.info('[CHAT_STREAM_CONFIG] api_endpoint_mode=%s tools_enabled=%s responses_mode=%s skip_prepare=%s', api_endpoint_mode, bool(enable_tools), bool(responses_mode), bool(initial_prepare_skipped))
    except Exception:
        pass

    think_tag_splitter = ThinkTagSplitter()
    usage_tracker = StreamUsageTracker(endpoint=api_endpoint_mode)

    def _record_generation_usage(usage_payload: dict | None = None, *, phase: str = '', model_name: str = '', endpoint: str = '', call_key: str = '') -> dict:
        try:
            recorded = usage_tracker.record(
                usage_payload,
                phase=phase,
                model_name=model_name,
                endpoint=endpoint or api_endpoint_mode,
                call_key=call_key,
            )
            if recorded:
                try:
                    app_logger.info(
                        '[USAGE_CHUNK] endpoint=%s phase=%s model=%s input_tokens=%s output_tokens=%s total_tokens=%s reasoning_tokens=%s cached_tokens=%s cached_source=%s cached_candidates=%s',
                        str(endpoint or api_endpoint_mode),
                        str(phase or ''),
                        str(model_name or ''),
                        int(recorded.get('input_tokens') or 0),
                        int(recorded.get('output_tokens') or 0),
                        int(recorded.get('total_tokens') or 0),
                        int(recorded.get('reasoning_tokens') or 0),
                        int(recorded.get('cached_tokens') or 0),
                        str(recorded.get('cached_tokens_source') or ''),
                        json.dumps(recorded.get('cached_tokens_candidates') or [], ensure_ascii=False)[:600],
                    )
                except Exception:
                    pass
            return recorded
        except Exception:
            return {}

    def _usage_sse_frame_if_new() -> str:
        try:
            payload = usage_tracker.payload()
            if not payload:
                return ''
            if not usage_tracker.mark_emitted_if_new(payload):
                return ''
            return sse('usage', payload)
        except Exception:
            return ''

    def _done_frames():
        usage_frame = _usage_sse_frame_if_new()
        if usage_frame:
            yield usage_frame
        yield sse('done', {})

    def _split_think_tag_text(text: str, flush: bool = False) -> tuple[str, str, str]:
        return think_tag_splitter.split(text, flush=flush)

    def _merge_stream_chunk_texts(chunk) -> tuple[str, str, str]:
        field_reasoning = _strip_leaked_think_tags(_extract_stream_reasoning(chunk))
        raw_text = _extract_stream_text(chunk)
        tag_reasoning, answer_text, tag_source = _split_think_tag_text(raw_text)
        tag_reasoning = _strip_leaked_think_tags(tag_reasoning)
        answer_text = _strip_leaked_think_tags(answer_text)
        reasoning_text = ''
        reasoning_source = ''
        if field_reasoning:
            reasoning_text += field_reasoning
            reasoning_source = 'native_field'
        if tag_reasoning:
            reasoning_text += tag_reasoning
            if not reasoning_source:
                reasoning_source = tag_source or 'think_tag'
        reasoning_text = _strip_leaked_think_tags(reasoning_text)
        return reasoning_text, answer_text, reasoning_source

    def _flush_pending_think_text() -> tuple[str, str, str]:
        return _split_think_tag_text('', flush=True)

    def _native_reasoning_meta_payload(*, done: bool | None = None) -> dict:
        payload = {
            'native_reasoning_connected': bool(native_reasoning_seen),
            'native_reasoning_source': native_reasoning_source if native_reasoning_seen else '',
        }
        seq = _last_activity_timeline_seq()
        if seq > 0:
            payload['seq'] = seq
            payload['order'] = seq
        if native_reasoning_text_accum:
            payload['native_reasoning_text'] = str(native_reasoning_text_accum or '')[-60000:]
        if done is not None:
            payload['native_reasoning_done'] = bool(done)
        return payload

    def _strip_stream_reasoning_html_comments(text: str) -> str:
        """Remove HTML comments without leaking markers split across SSE chunks."""
        nonlocal native_reasoning_html_comment_pending, native_reasoning_html_comment_open
        data = str(native_reasoning_html_comment_pending or '') + str(text or '')
        native_reasoning_html_comment_pending = ''
        if not data:
            return ''
        visible = []
        cursor = 0
        while cursor < len(data):
            if native_reasoning_html_comment_open:
                close_at = data.find('-->', cursor)
                if close_at < 0:
                    if data.endswith('--'):
                        native_reasoning_html_comment_pending = '--'
                    elif data.endswith('-'):
                        native_reasoning_html_comment_pending = '-'
                    return ''.join(visible)
                native_reasoning_html_comment_open = False
                cursor = close_at + 3
                continue

            open_at = data.find('<!--', cursor)
            if open_at >= 0:
                visible.append(data[cursor:open_at])
                native_reasoning_html_comment_open = True
                cursor = open_at + 4
                continue

            tail = data[cursor:]
            pending_open = ''
            for marker_prefix in ('<!-', '<!', '<'):
                if tail.endswith(marker_prefix):
                    pending_open = marker_prefix
                    break
            if pending_open:
                visible.append(tail[:-len(pending_open)])
                native_reasoning_html_comment_pending = pending_open
            else:
                visible.append(tail)
            break
        return ''.join(visible)

    def _reasoning_sse_frames(text: str, source: str = '', event_key: str = '') -> list[str]:
        nonlocal native_reasoning_seen, native_reasoning_source, native_reasoning_text_accum
        piece = _strip_stream_reasoning_html_comments(text)
        if not piece:
            return []
        normalized_source = str(source or native_reasoning_source or 'native_field').strip().lower()[:40] or 'native_field'
        native_event_key = str(event_key or '').strip()[:700]
        seq = _next_activity_timeline_seq()
        native_reasoning_text_accum = (str(native_reasoning_text_accum or '') + piece)[-60000:]
        frames = []
        if not native_reasoning_seen:
            native_reasoning_seen = True
            native_reasoning_source = normalized_source
            frames.append(sse('reasoning_meta', {
                'connected': True,
                'source': normalized_source,
                'status': 'streaming',
                'seq': seq,
                'order': seq,
            }))
        elif not native_reasoning_source:
            native_reasoning_source = normalized_source
        reasoning_payload = {
            'text': piece,
            'source': normalized_source,
            'seq': seq,
            'order': seq,
        }
        if native_event_key:
            reasoning_payload['event_key'] = native_event_key
            reasoning_payload['reasoning_event_key'] = native_event_key
            reasoning_payload['segment_key'] = native_event_key
        frames.append(sse('reasoning', reasoning_payload))
        return frames

    def _human_stream_error(e: Exception, phase: str) -> str:
        phase_text = {
            "fast": "生成回复",
            "agent_final": "生成最终回复",
            "agent_plan": "规划工具调用",
        }.get(phase, phase)
        if isinstance(e, httpx.ReadTimeout):
            return f"AI流式响应超时（{phase_text}）"
        if isinstance(e, httpx.ConnectTimeout):
            return f"AI连接超时（{phase_text}）"
        if isinstance(e, httpx.TimeoutException):
            return f"AI请求超时（{phase_text}）"
        if isinstance(e, httpx.RemoteProtocolError):
            return f"AI连接被远端中断（{phase_text}）"
        if isinstance(e, httpx.ReadError):
            return f"AI响应读取失败（{phase_text}）"
        err_text = str(e or '')
        if 'fail to get image from url' in err_text or 'count_token_failed' in err_text:
            return f"AI生成失败（{phase_text}）：图片读取失败。可能是远程链接失效，或图片被错误标记为 webp / 缓存文件头异常。当前已尽量改为发送前复检并优先使用可读图片；若仍出现，请重试或更换图片来源。原始错误：{type(e).__name__}: {e}"
        if isinstance(e, httpx.HTTPError):
            return f"AI网络请求失败（{phase_text}）：{type(e).__name__}: {e}"
        return f"AI生成失败（{phase_text}）：{type(e).__name__}: {e}"

    def _looks_like_image_request_error(err: Exception) -> bool:
        txt = str(err or '').lower()
        if not txt:
            return False
        markers = (
            'fail to get image from url',
            'count_token_failed',
            'fail to decode image config',
            'invalid_image_format',
            'unsupported image',
            'unsupported_image',
        )
        return any(token in txt for token in markers)

    def _should_stop_async_job():
        try:
            return bool(_chat_async_should_stop_current_job())
        except Exception:
            return False

    def _raise_if_async_job_stopped():
        if _should_stop_async_job():
            raise RuntimeError('__async_chat_job_stopped__')

    def _close_stream_if_possible(stream_resp):
        if stream_resp is None:
            return
        try:
            close_fn = getattr(stream_resp, 'close', None)
            if callable(close_fn):
                close_fn()
                return
        except Exception:
            pass
        try:
            close_fn = getattr(stream_resp, 'aclose', None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass

    stream_retry_policy = ChatStreamRetryPolicy()

    def _stream_cfg_int(name: str, default: int, *, min_value: int = 0, max_value: int = 100) -> int:
        return stream_retry_policy.cfg_int(name, default, min_value=min_value, max_value=max_value)

    def _stream_cfg_float(name: str, default: float, *, min_value: float = 0.0, max_value: float = 60.0) -> float:
        return stream_retry_policy.cfg_float(name, default, min_value=min_value, max_value=max_value)

    def _stream_error_retryable(err: Exception) -> bool:
        return stream_retry_policy.is_retryable(err)

    def _stream_retry_delay(attempt: int) -> float:
        return stream_retry_policy.delay(attempt)

    stream_open_helper = ChatStreamOpenHelper(
        endpoint_mode=api_endpoint_mode,
        default_model=model,
        retry_policy=stream_retry_policy,
        should_stop=_should_stop_async_job,
        raise_if_stopped=_raise_if_async_job_stopped,
    )

    def _open_responses_stream_with_retry(stream_client, *, phase: str, call_kwargs: dict):
        return stream_open_helper.open_responses_stream(stream_client, phase=phase, call_kwargs=call_kwargs)

    def _open_stream_with_retry(stream_client, *, phase: str, call_kwargs: dict):
        return stream_open_helper.open_stream(stream_client, phase=phase, call_kwargs=call_kwargs)

    stream_completion_runner = ChatStreamCompletionRunner(
        api_endpoint_mode=api_endpoint_mode,
        model=model,
        client_override=client_override,
        client_session_id=client_session_id,
        should_stop=_should_stop_async_job,
        raise_if_stopped=_raise_if_async_job_stopped,
        close_stream_if_possible=_close_stream_if_possible,
        human_stream_error=_human_stream_error,
        looks_like_image_request_error=_looks_like_image_request_error,
        sanitize_messages_for_model=_sanitize_messages_for_model,
        apply_user_generation_settings=_apply_user_generation_settings,
        stream_cfg_int=_stream_cfg_int,
        stream_error_retryable=_stream_error_retryable,
        stream_retry_delay=_stream_retry_delay,
        open_stream_with_retry=_open_stream_with_retry,
        set_current_stream_handle=_chat_async_set_current_stream_handle,
        remember_runtime_model=_remember_runtime_model,
        extract_runtime_model_from_obj=_extract_runtime_model_from_obj,
        extract_usage_from_stream_chunk=_extract_usage_from_stream_chunk,
        record_generation_usage=_record_generation_usage,
    )

    def _messages_have_input_image_parts(msgs: list | None = None) -> bool:
        return stream_completion_runner.messages_have_input_image_parts(msgs)

    def _stream_completion(*, phase: str, **kwargs):
        yield from stream_completion_runner.stream_completion(phase=phase, **kwargs)

    def _agent_stream_tools_enabled() -> bool:
        raw = str(os.getenv('AGENT_STREAM_TOOLS_ENABLED', '1') or '1').strip().lower()
        return raw not in {'0', 'false', 'no', 'off', 'disabled'}

    def _agent_stream_direct_first_enabled() -> bool:
        raw = str(os.getenv('AGENT_STREAM_DIRECT_FIRST_ENABLED', '1') or '1').strip().lower()
        return raw not in {'0', 'false', 'no', 'off', 'disabled'}

    def _agent_stream_should_try_direct_first() -> bool:
        if not _agent_stream_direct_first_enabled():
            return False
        if not _agent_stream_tools_enabled():
            return False
        if not enable_tools:
            return False
        return True

    def _agent_stream_direct_first_ctx(tool_gate: dict | None = None) -> dict:
        gate = dict(tool_gate or {}) if isinstance(tool_gate, dict) else {}
        return {
            'agent_stream_direct_first': True,
            'prefetch_decision': {},
            'route_mode': str(gate.get('route_mode') or ''),
            'chat_tool_gate': gate,
            'responses_native_tool_gate': gate,
        }



    def _responses_native_light_direct_messages(base_messages: list | None = None) -> list:
        keep_limit = _agent_stream_cfg_int('RESPONSES_NATIVE_LIGHT_DIRECT_HISTORY', 4, min_value=1, max_value=20)
        total_limit = _agent_stream_cfg_int('RESPONSES_NATIVE_LIGHT_DIRECT_MAX_CHARS', 1600, min_value=400, max_value=12000)
        kept: list[dict] = [{
            'role': 'system',
            '_kind': 'responses_light_direct',
            'content': '普通闲聊直答：用用户语言简短自然回答；不调用工具，不输出内部计划。',
        }]
        budget = total_limit
        recent = []
        for m in list(base_messages or [])[-keep_limit:]:
            if not isinstance(m, dict):
                continue
            role = str(m.get('role') or '').strip().lower()
            if role not in {'user', 'assistant'}:
                continue
            try:
                helper = globals().get('_message_to_text_for_budget')
                if callable(helper):
                    content = helper(m, include_images=False, include_image_text=True)
                else:
                    content = m.get('content')
            except Exception:
                content = m.get('content')
            if isinstance(content, list):
                content = ' '.join(str(x) for x in content if str(x).strip())
            content = str(content or '').strip()
            if not content:
                continue
            content = content[:900]
            recent.append({'role': role, 'content': content})
        for m in recent:
            content = str(m.get('content') or '')
            if budget <= 0:
                break
            if len(content) > budget:
                content = content[-budget:]
            kept.append({'role': m.get('role') or 'user', 'content': content})
            budget -= len(content)
        return _sanitize_messages_for_model(kept)

    def _responses_native_code_interpreter_mode() -> str:
        raw = str(app_getenv('RESPONSES_NATIVE_CODE_INTERPRETER', os.getenv('RESPONSES_NATIVE_CODE_INTERPRETER', 'auto')) or 'auto').strip().lower()
        if raw in {'1', 'true', 'yes', 'on', 'force', 'forced'}:
            return 'force'
        if raw in {'0', 'false', 'no', 'off', 'disabled'}:
            return 'off'
        return 'auto'

    def _responses_native_base_host() -> str:
        raw = ''
        try:
            raw = str(getattr(client_override, 'base_url', '') or '').strip()
        except Exception:
            raw = ''
        if not raw:
            raw = str(globals().get('GPT_BASE_URL') or '').strip()
        try:
            return str(urlparse(raw).hostname or '').strip().lower()
        except Exception:
            return ''

    def _responses_native_code_interpreter_enabled() -> bool:
        if str(api_endpoint_mode or '').strip().lower() != 'responses':
            return False
        # 单文件平面开启时，普通文件必须由本地 sandbox_* 工具生成和发布。
        # Responses 原生 code_interpreter 使用供应商远程容器，会形成第二套文件生成后端。
        if _agent_stream_single_sandbox_file_plane_enabled():
            return False
        mode = _responses_native_code_interpreter_mode()
        if mode == 'off':
            return False
        if mode == 'force':
            return True
        host = _responses_native_base_host()
        # NewAPI/Sub2API/OneAPI commonly implement only part of /responses.
        # In auto mode expose official Code Interpreter only for OpenAI hosts.
        return bool(host == 'api.openai.com' or host.endswith('.api.openai.com') or host.endswith('.openai.com'))

    def _responses_native_code_interpreter_tool_spec() -> dict:
        memory_limit = str(app_getenv('RESPONSES_CODE_INTERPRETER_MEMORY_LIMIT', '4g') or '4g').strip() or '4g'
        return {
            'type': 'code_interpreter',
            'container': {
                'type': 'auto',
                'memory_limit': memory_limit,
            },
        }

    def _agent_stream_single_sandbox_file_plane_enabled() -> bool:
        raw = str(app_getenv('SANDBOX_SINGLE_FILE_PLANE', os.getenv('SANDBOX_SINGLE_FILE_PLANE', '1')) or '1').strip().lower()
        return raw not in {'0', 'false', 'no', 'off', 'disabled'}

    def _agent_stream_filter_file_plane_tool_specs(specs: list | None = None) -> list[dict]:
        rows = [spec for spec in (specs or []) if isinstance(spec, dict)]
        if not _agent_stream_single_sandbox_file_plane_enabled():
            return rows
        removed_names = set()
        helper = globals().get('skill_removed_tool_names')
        if callable(helper):
            try:
                removed_names = {str(x or '').strip() for x in (helper() or []) if str(x or '').strip()}
            except Exception:
                removed_names = set()
        if not removed_names:
            return rows
        out = []
        for spec in rows:
            fn = spec.get('function') if isinstance(spec.get('function'), dict) else {}
            name = str((fn or {}).get('name') or spec.get('name') or '').strip()
            if name in removed_names:
                continue
            out.append(spec)
        return out

    def _account_history_reference_enabled_for_turn() -> bool:
        if temporary_chat:
            return False
        checker = globals().get('_account_context_history_enabled')
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return True
        return True

    def _agent_stream_web_enabled_for_turn() -> bool:
        try:
            value = web_enabled
        except Exception:
            return True
        if value is False:
            return False
        raw = str(value if value is not None else '').strip().lower()
        if raw in {'0', 'false', 'no', 'off', 'disabled'}:
            return False
        return True

    def _agent_stream_filter_tool_specs_for_settings(specs: list | None = None) -> list[dict]:
        rows = [spec for spec in (specs or []) if isinstance(spec, dict)]
        blocked: set[str] = set()
        if not _account_history_reference_enabled_for_turn():
            blocked.update({'search_account_context', 'read_account_context'})
        if not _agent_stream_web_enabled_for_turn():
            blocked.update({'web_search', 'fetch_url', 'fetch_urls'})
        if not blocked:
            return rows
        out = []
        for spec in rows:
            fn = spec.get('function') if isinstance(spec.get('function'), dict) else {}
            name = str((fn or {}).get('name') or spec.get('name') or '').strip()
            if name in blocked:
                continue
            out.append(spec)
        return out

    capability_routing_context = ChatStreamCapabilityRoutingContext(
        model=model,
        image_generation_enabled=bool(image_generation_enabled),
        web_enabled_for_turn=_agent_stream_web_enabled_for_turn,
        account_history_enabled=_account_history_reference_enabled_for_turn,
        single_sandbox_file_plane_enabled=_agent_stream_single_sandbox_file_plane_enabled,
        responses_code_interpreter_enabled=_responses_native_code_interpreter_enabled,
        latest_user_text=_latest_user_text_from_messages,
        recent_image_context=lambda base_messages=None, max_chars=600: _agent_stream_recent_image_context(base_messages, max_chars=max_chars),
        logger=app_logger,
    )

    def _responses_native_capability_group_names() -> list[str]:
        return capability_routing_context.responses_native_capability_group_names()

    def _responses_native_capability_groups(raw_groups=None) -> list[str]:
        return capability_routing_context.responses_native_capability_groups(raw_groups)

    def _agent_stream_chat_capability_group_names() -> list[str]:
        return capability_routing_context.chat_capability_group_names()

    def _agent_stream_chat_capability_groups(raw_groups=None) -> list[str]:
        return capability_routing_context.chat_capability_groups(raw_groups)

    def _responses_native_file_record_is_image(rec: dict | None = None) -> bool:
        return capability_routing_context.responses_native_file_record_is_image(rec)

    def _responses_native_current_turn_image_records(base_messages: list | None = None) -> list[dict]:
        return capability_routing_context.responses_native_current_turn_image_records(base_messages)

    def _responses_native_file_task_soft_preselect(base_messages: list | None = None) -> tuple[bool, str]:
        return capability_routing_context.responses_native_file_task_soft_preselect(base_messages)

    def _responses_native_image_generation_preclassify(base_messages: list | None = None) -> dict:
        return capability_routing_context.responses_native_image_generation_preclassify(base_messages)

    def _responses_native_image_task_mode(task_type: str = '') -> str:
        raw = str(task_type or '').strip().lower()
        if raw in {'image_edit', 'reference_edit', 'variation', 'edit'}:
            return 'edit'
        if raw in {'reference_generate'}:
            return 'reference_generate'
        return 'text_to_image'

    def _agent_stream_image_row_log_payload(row: dict | None = None) -> dict:
        return image_candidate_context.image_row_log_payload(row)

    def _agent_stream_image_rows_log_payload(rows: list[dict] | None = None, *, limit: int = 12) -> list[dict]:
        return image_candidate_context.image_rows_log_payload(rows, limit=limit)

    def _agent_stream_eager_image_rows_for_generation(base_messages: list | None = None, *, task_type: str = '', limit: int = 8) -> list[dict]:
        return image_candidate_context.eager_image_rows_for_generation(base_messages, task_type=task_type, limit=limit)

    def _agent_stream_exact_selected_image_rows(raw_values, candidate_rows: list[dict] | None = None, *, limit: int = 8) -> list[dict]:
        return image_resolver.exact_selected_image_rows(raw_values, candidate_rows, limit=limit)

    def _agent_stream_direct_resolve_image_rows(raw_values, candidate_rows: list[dict] | None = None, *, limit: int = 4) -> list[dict]:
        return image_resolver.direct_resolve_image_rows(raw_values, candidate_rows, limit=limit)

    def _agent_stream_enrich_direct_image_candidate_rows(candidate_rows: list[dict] | None = None) -> list[dict]:
        return image_resolver.enrich_direct_image_candidate_rows(candidate_rows)

    def _agent_stream_recent_assistant_image_rows(limit: int = 1) -> list[dict]:
        return image_candidate_context.recent_assistant_image_rows(limit)

    def _agent_stream_direct_image_rows_for_model(candidate_rows: list[dict] | None = None, *, limit: int = 8) -> str:
        return image_candidate_context.direct_image_rows_for_model(candidate_rows, limit=limit)

    def _agent_stream_external_image_asset_candidate_rows(limit: int = 12) -> list[dict]:
        return image_candidate_context.external_image_asset_candidate_rows(limit)

    image_input_context = ChatStreamImageInputContext(
        model=model,
        messages=messages,
        eager_image_rows_for_generation=_agent_stream_eager_image_rows_for_generation,
        exact_selected_image_rows=_agent_stream_exact_selected_image_rows,
        direct_resolve_image_rows=_agent_stream_direct_resolve_image_rows,
        external_image_asset_candidate_rows=_agent_stream_external_image_asset_candidate_rows,
        direct_image_rows_for_model=_agent_stream_direct_image_rows_for_model,
        image_rows_log_payload=_agent_stream_image_rows_log_payload,
        image_row_log_payload=_agent_stream_image_row_log_payload,
    )

    def _agent_stream_image_bytes_to_data_url(raw: bytes = b'', mime: str = '', filename: str = '') -> str:
        return image_input_context._agent_stream_image_bytes_to_data_url(raw, mime, filename)

    def _agent_stream_local_image_source_to_data_url(source: str = '') -> str:
        return image_input_context._agent_stream_local_image_source_to_data_url(source)

    def _agent_stream_data_url_to_sandbox_image_item(data_url: str = '', *, filename: str = '', label: str = '', source: str = '') -> dict | None:
        return image_input_context._agent_stream_data_url_to_sandbox_image_item(data_url, filename=filename, label=label, source=source)

    def _agent_stream_image_ext_from_mime_or_bytes(mime: str = '', raw: bytes = b'', filename: str = '') -> str:
        return image_input_context._agent_stream_image_ext_from_mime_or_bytes(mime, raw, filename)

    def _agent_stream_image_asset_candidate_sources(row: dict | None = None, fallback_url: str = '') -> list[str]:
        return image_input_context._agent_stream_image_asset_candidate_sources(row, fallback_url=fallback_url)

    def _agent_stream_image_source_to_bytes(source: str = '', row: dict | None = None) -> tuple[bytes, str, str, str]:
        return image_input_context._agent_stream_image_source_to_bytes(source, row)

    def _agent_stream_import_image_bytes_to_sandbox(raw_bytes: bytes = b'', mime: str = '', filename: str = '', label: str = '', source: str = '', *, asset_source: str = 'chat_image_asset') -> dict:
        return image_input_context._agent_stream_import_image_bytes_to_sandbox(raw_bytes, mime, filename, label, source, asset_source=asset_source)

    def _agent_stream_import_image_row_to_sandbox(row: dict | None = None, *, fallback_url: str = '', index: int = 1, asset_source: str = 'chat_image_asset') -> dict:
        return image_input_context._agent_stream_import_image_row_to_sandbox(row, fallback_url=fallback_url, index=index, asset_source=asset_source)

    def _agent_stream_input_image_item_from_sandbox_file(file_row: dict | None = None) -> dict | None:
        return image_input_context._agent_stream_input_image_item_from_sandbox_file(file_row)

    def _agent_stream_public_responses_content_part(part: dict | None = None, *, role: str = 'user') -> dict | None:
        return image_input_context._agent_stream_public_responses_content_part(part, role=role)

    def _agent_stream_public_responses_input_item(item: dict | None = None) -> dict | None:
        return image_input_context._agent_stream_public_responses_input_item(item)

    def _agent_stream_sanitize_responses_input_items_for_api(input_items: list | None = None) -> list[dict]:
        return image_input_context._agent_stream_sanitize_responses_input_items_for_api(input_items)

    def _agent_stream_eager_image_candidate_sources(row: dict | None = None, primary_url: str = '') -> list[str]:
        return image_input_context._agent_stream_eager_image_candidate_sources(row, primary_url=primary_url)

    def _agent_stream_input_image_item_from_asset_row(row: dict | None = None, *, primary_url: str = '', index: int = 1, asset_source: str = 'image_generation_reference') -> dict | None:
        return image_input_context._agent_stream_input_image_item_from_asset_row(row, primary_url=primary_url, index=index, asset_source=asset_source)

    def _agent_stream_append_eager_image_generation_input(input_items: list | None = None, *, task_type: str = '', selected_image_ids: list | None = None, reason: str = '') -> tuple[list, int]:
        return image_input_context._agent_stream_append_eager_image_generation_input(input_items, task_type=task_type, selected_image_ids=selected_image_ids, reason=reason)

    tool_spec_context = ChatStreamToolSpecContext(
        temporary_chat=temporary_chat,
        chat_capability_groups=_agent_stream_chat_capability_groups,
        filter_file_plane_tool_specs=_agent_stream_filter_file_plane_tool_specs,
    )

    def _agent_stream_cfg_int(name: str, default: int, *, min_value: int = 0, max_value: int = 10000) -> int:
        return tool_spec_context.cfg_int(name, default, min_value=min_value, max_value=max_value)

    def _responses_native_instruction_max_chars() -> int:
        return tool_spec_context.responses_native_instruction_max_chars()

    def _agent_stream_memory_tool_enabled() -> bool:
        return tool_spec_context.memory_tool_enabled()

    def _agent_stream_save_memory_tool_spec(compact: bool = False) -> dict:
        return tool_spec_context.save_memory_tool_spec(compact=compact)

    def _agent_stream_run_save_memory_tool(args: dict | None = None) -> dict:
        return tool_spec_context.run_save_memory_tool(args)

    def _agent_stream_slim_chat_tool_specs(specs: list | None = None) -> list[dict]:
        return tool_spec_context.slim_chat_tool_specs(specs)

    def _agent_stream_normalize_chat_tool_specs(specs: list | None = None) -> list[dict]:
        return tool_spec_context.normalize_chat_tool_specs(specs)

    def _agent_stream_tool_spec_name(spec: dict | None = None) -> str:
        return tool_spec_context.tool_spec_name(spec)

    def _agent_stream_stabilize_tool_specs(specs: list | None = None) -> list[dict]:
        return tool_spec_context.stabilize_tool_specs(specs)

    def _agent_stream_tool_group(name: str = '', spec: dict | None = None) -> str:
        return tool_spec_context.tool_group(name, spec)

    def _agent_stream_filter_chat_tool_specs_by_groups(specs: list | None = None, allowed_tool_groups: list | None = None) -> list[dict]:
        return tool_spec_context.filter_chat_tool_specs_by_groups(specs, allowed_tool_groups)

    def _agent_stream_chat_filter_or_full_fallback(specs: list | None = None, allowed_tool_groups: list | None = None) -> list[dict]:
        return tool_spec_context.chat_filter_or_full_fallback(specs, allowed_tool_groups)

    def _agent_stream_tool_specs(compact: bool = False, allowed_tool_groups: list | None = None) -> list[dict]:
        return tool_spec_context.tool_specs(compact=compact, allowed_tool_groups=allowed_tool_groups)


    def _agent_streaming_runtime_prompt(ctx_for_prompt: dict | None = None) -> dict:
        ctx_for_prompt = ctx_for_prompt or {}
        responses_prompt_lane = bool(ctx_for_prompt.get('responses_native_tools'))
        skill_runtime_guard_text = ''
        try:
            prompt_builder = globals().get('skill_runtime_prompt')
            if callable(prompt_builder):
                requested_groups = []
                gate = (ctx_for_prompt.get('responses_native_tool_gate') or {}) if isinstance(ctx_for_prompt.get('responses_native_tool_gate'), dict) else {}
                if responses_prompt_lane:
                    requested_groups = gate.get('tool_groups') if isinstance(gate.get('tool_groups'), list) else []
                else:
                    chat_gate = (ctx_for_prompt.get('chat_tool_gate') or {}) if isinstance(ctx_for_prompt.get('chat_tool_gate'), dict) else {}
                    requested_groups = chat_gate.get('tool_groups') if isinstance(chat_gate.get('tool_groups'), list) else []
                mode_hint = 'responses' if responses_prompt_lane else 'chat_completions'
                if requested_groups:
                    skill_runtime_guard_text = str(prompt_builder(mode_hint, requested_groups, compact=True) or '').strip()
                else:
                    skill_runtime_guard_text = 'Active tool groups: all registered groups.'
        except Exception:
            skill_runtime_guard_text = ''
        if str(sys.platform or '').lower().startswith('linux'):
            sandbox_delivery_guard_text = '真实文件读取、修改、运行或交付只走 sandbox artifact runtime：先导入/生成到 /mnt/data，按任务读取/验证，交付前发布 artifact。'
            sandbox_file_qa_guard_text = (
                '附件/沙盒文件是可选资料：只有用户意图确实需要读取、审阅、修改、运行或列出文件时才导入/读取。'
                '普通聊天或与附件无关的问题直接回答，不要因为存在文件清单就默认看文件。'
                '决定使用文件证据后，通过 sandbox_import_files 把目标文件放入 /mnt/data，再按证据策略读取；' + _sandbox_file_evidence_policy_text() + ''
            )
            sandbox_execution_guard_text = (
                '沙盒后端不可用会返回 sandbox_backend_unavailable；不能改用宿主机 shell 冒充沙盒。'
            )
        else:
            sandbox_delivery_guard_text = '真实 sandbox 文件链路只在 Linux Docker runtime 暴露；当前非 Linux 环境不提供 sandbox 本机兼容链路。'
            sandbox_file_qa_guard_text = '当前非 Linux 环境没有真实 sandbox 文件问答链路；不要假装已读取文件或图片。'
            sandbox_execution_guard_text = '真实沙盒只在 Linux Docker runtime 暴露；当前非 Linux 环境不提供 sandbox_* 本机兼容链路。'

        file_task_active = bool(
            ctx_for_prompt.get('agent_has_file_context')
            or ctx_for_prompt.get('agent_file_task_likely')
            or ctx_for_prompt.get('responses_file_task_soft_sandbox')
        )
        if not file_task_active:
            sandbox_delivery_guard_text = '文件/项目的读取、修改、运行或交付才用 sandbox；普通聊天不要读取文件。'
            sandbox_file_qa_guard_text = ''
            sandbox_execution_guard_text = ''

        def _runtime_prompt_content(parts: list | tuple) -> str:
            seen: set[str] = set()
            clean_parts: list[str] = []
            for part in parts or []:
                text = str(part or '').strip()
                if not text:
                    continue
                key = ' '.join(text.split()).casefold()
                if key in seen:
                    continue
                seen.add(key)
                clean_parts.append(text)
            return '\n'.join(clean_parts)

        if bool(ctx_for_prompt.get('agent_stream_direct_first')):
            if bool(ctx_for_prompt.get('responses_image_generation_eager_first')) and bool(image_generation_enabled):
                image_task_hint = str(ctx_for_prompt.get('responses_image_task_type') or '').strip() or 'image_generation'
                image_tool_hint = '本轮已进入 Responses 生图类首轮直通：任务类型=' + image_task_hint + '。文生图、参考生图、编辑图都只使用原生 image_generation；若首轮附带了候选图片，请根据用户语义自行选择参考图/目标图，不要先调用 analyze_existing_image，也不要输出图片分析来代替生图。'
            elif bool(ctx_for_prompt.get('responses_native_tools')) and bool(image_generation_enabled):
                image_tool_hint = 'Responses 生图/改图只使用原生 image_generation；真实找图用 image_search，看图问答/OCR/局部分析用 analyze_existing_image。不要把 Chat-lane handoff 当作 Responses 生图入口。'
            else:
                image_tool_hint = 'Chat 图片任务：看图/OCR 用 image/analyze_existing_image，生图/改图/参考图用 image_generate/handoff_to_image_delivery。不要因为上下文有图就默认用图片工具。'
            return {
                'role': 'system',
                '_kind': 'agent_stream_runtime',
                    'content': _runtime_prompt_content([
                    '普通问题直接答；需要工具才调用。最新/当前/价格/名单/政策等先 web；位置用 get_location/location；不展示函数名、参数或内部 JSON。',
                    skill_runtime_guard_text,
                    image_tool_hint,
                    sandbox_delivery_guard_text,
                    sandbox_file_qa_guard_text,
                    sandbox_execution_guard_text,
                    '已有文件证据才读文件/diff；只要已有产物链接时用已发布元数据，不重生成/发布。',
                    ('知识库先搜片段，不足再读同文档更多内容；账号历史用于接续任务，优先读已保存状态。' if _account_history_reference_enabled_for_turn() else '知识库先搜片段，不足再读同文档更多内容。'),
                    '按当前意图决定是否调用；短确认/寒暄不要仅凭图片上下文升级成生图或编辑。',
                ]),
            }
        bits = [
            '你是主回答模型。普通问题直接答；只有当前语义需要当前可用工具时才调用。最新/当前/价格/名单/政策等先 web 取证；位置用 get_location/location。',
            skill_runtime_guard_text,
            '不要展示工具 JSON、内部计划、函数名或参数；拿到工具结果后自然作答。工具失败时如实说明并基于已有信息继续。',
            '只有需要已有文件证据时才读 diff/片段。只要已有产物链接时用已发布元数据，不重生成/发布。图片生成/编辑优先用 Responses 原生图片能力。',
            sandbox_delivery_guard_text,
            sandbox_file_qa_guard_text,
            sandbox_execution_guard_text,
        ]
        if _agent_stream_web_enabled_for_turn() and bool((ctx_for_prompt or {}).get('soft_web_research_hit')):
            bits.append('本轮上游轻量判断认为可能需要联网核验；如果问题确实涉及最新或外部事实，请优先调用 web_search，再按需要读取页面。')
        route_hint = str((ctx_for_prompt or {}).get('route_mode') or '').strip()
        if route_hint:
            bits.append(f'上游轻量路由提示：{route_hint}。这只是提示，不是强制规则；请以用户当前需求为准。')
        return {'role': 'system', '_kind': 'agent_stream_runtime', 'content': _runtime_prompt_content(bits)}

    def _agent_stream_append_progress_event(state: dict | None = None, item: dict | None = None) -> dict:
        return activity_context.append_progress_event(state, item)

    def _agent_stream_progress_meta(state: dict | None = None) -> dict:
        return activity_context.progress_meta(state)

    def _agent_stream_activity_delta_frame(state: dict | None = None) -> str:
        return activity_context.activity_delta_frame(state)

    def _agent_stream_append_file_progress(state: dict | None = None, item: dict | None = None) -> None:
        return activity_context.append_file_progress(state, item)

    def _agent_stream_file_progress_meta(state: dict | None = None) -> dict:
        return activity_context.file_progress_meta(state)

    def _agent_stream_merge_file_artifacts(state: dict | None = None, files: list | None = None) -> list[dict]:
        return activity_context.merge_file_artifacts(state, files)

    def _agent_stream_note_sandbox_publish_result(state: dict | None = None, result: dict | None = None, args: dict | None = None) -> dict:
        return activity_context.note_sandbox_publish_result(state, result, args)

    def _agent_stream_note_sandbox_write_result(state: dict | None = None, name: str = '', result: dict | None = None, args: dict | None = None) -> None:
        return activity_context.note_sandbox_write_result(state, name, result, args)

    def _agent_stream_attach_sandbox_audits_to_publish_args(state: dict | None = None, name: str = '', args: dict | None = None) -> dict:
        return activity_context.attach_sandbox_audits_to_publish_args(state, name, args)

    def _agent_stream_file_process_preview_frame(state: dict | None = None, calls_acc=None, *, preferred_mode: str = 'generate_new'):
        # Old streamed artifact-argument preview has no place in the sandbox chain.
        # Concrete files are now written and published by sandbox_* tools.
        _ = state, calls_acc, preferred_mode
        return None

    file_context = ChatStreamFileContext(
        append_file_progress=_agent_stream_append_file_progress,
        single_sandbox_file_plane_enabled=_agent_stream_single_sandbox_file_plane_enabled,
    )

    def _agent_stream_public_file_label(value) -> str:
        return file_context._agent_stream_public_file_label(value)

    def _agent_stream_file_record_display_name(rec: dict | None = None) -> str:
        return file_context._agent_stream_file_record_display_name(rec)

    def _agent_stream_file_record_names(records: list | None = None, limit: int = 8) -> list[str]:
        return file_context._agent_stream_file_record_names(records, limit)

    def _agent_stream_file_context_names_from_prompt(prompt: str = '', limit: int = 6) -> list[str]:
        return file_context._agent_stream_file_context_names_from_prompt(prompt, limit)

    def _agent_stream_file_context_needed_for_groups(groups: list | None = None) -> bool:
        return file_context._agent_stream_file_context_needed_for_groups(groups)

    def _agent_stream_file_context_needed_for_current_turn(base_messages: list | None = None) -> tuple[bool, str]:
        return file_context._agent_stream_file_context_needed_for_current_turn(base_messages)

    def _agent_stream_prompt_cache_file_context_needed(base_messages: list | None = None) -> bool:
        return file_context._agent_stream_prompt_cache_file_context_needed(base_messages)

    def _agent_stream_prompt_cache_text_file_records(records: list | None = None, *, limit: int = 4) -> list[dict]:
        return file_context._agent_stream_prompt_cache_text_file_records(records, limit=limit)

    def _agent_stream_model_driven_file_index_prompt(file_ctx: dict | None = None, *, recall_prompt: str = '', current_user_text: str = '') -> str:
        return file_context._agent_stream_model_driven_file_index_prompt(file_ctx, recall_prompt=recall_prompt, current_user_text=current_user_text)

    def _agent_stream_prompt_cache_inline_file_context(records: list | None = None) -> str:
        return file_context._agent_stream_prompt_cache_inline_file_context(records)

    def _agent_stream_note_file_context_injection(state: dict | None = None, file_ctx: dict | None = None, *, memory_prompt: str = '', recall_prompt: str = '', current_user_text: str = '') -> None:
        return file_context._agent_stream_note_file_context_injection(state, file_ctx, memory_prompt=memory_prompt, recall_prompt=recall_prompt, current_user_text=current_user_text)

    def _agent_stream_messages_with_file_context(base_messages: list | None = None, state: dict | None = None) -> list:
        return file_context._agent_stream_messages_with_file_context(base_messages, state)

    knowledge_context = ChatStreamKnowledgeContext(
        kb_enabled=kb_enabled,
        kb_space_id=kb_space_id,
        kb_doc_id=kb_doc_id,
        latest_user_text=_latest_user_text_from_messages,
        logger=app_logger,
    )

    def _agent_stream_messages_with_knowledge_context(base_messages: list | None = None) -> list:
        return knowledge_context.messages_with_context(base_messages)

    visual_context = ChatStreamVisualContext(
        external_image_asset_messages=external_image_asset_messages,
        current_endpoint_mode=lambda: _orch_current_endpoint_mode(client_override),
        find_recent_context_image_urls=_orch_find_recent_context_image_urls,
        is_current_user_image_row=_agent_stream_is_current_user_image_row,
        filter_image_rows_by_endpoint=_orch_filter_image_rows_by_endpoint,
        enrich_direct_image_candidate_rows=_agent_stream_enrich_direct_image_candidate_rows,
        direct_image_rows_for_model=_agent_stream_direct_image_rows_for_model,
        external_image_asset_candidate_rows=_agent_stream_external_image_asset_candidate_rows,
        messages_for_image_index=_agent_stream_messages_for_image_index,
        cfg_int=_agent_stream_cfg_int,
        sanitize_messages_for_model=_sanitize_messages_for_model,
    )

    def _agent_stream_recent_image_context(base_messages: list | None = None, *, max_chars: int = 1400) -> dict:
        return visual_context._agent_stream_recent_image_context(base_messages, max_chars=max_chars)

    def _agent_stream_external_image_assets_index_text(limit: int = 8) -> tuple[str, int]:
        return visual_context._agent_stream_external_image_assets_index_text(limit)

    def _agent_stream_messages_with_visual_context(base_messages: list | None = None) -> list:
        return visual_context._agent_stream_messages_with_visual_context(base_messages)

    def _agent_stream_inline_image_url_from_item(item: dict | None = None) -> str:
        return visual_context._agent_stream_inline_image_url_from_item(item)

    def _agent_stream_strip_inline_image_inputs(base_messages: list | None = None) -> tuple[list, int, int]:
        return visual_context._agent_stream_strip_inline_image_inputs(base_messages)

    def _agent_stream_sanitize_tool_loop_messages(base_messages: list | None = None) -> list:
        return visual_context._agent_stream_sanitize_tool_loop_messages(base_messages)

    def _agent_stream_log_prompt_cache_message_shape(stage: str, rows: list | None = None) -> None:
        return visual_context._agent_stream_log_prompt_cache_message_shape(stage, rows)

    def _agent_stream_should_try(ctx_for_agent: dict | None = None, plan_for_agent: dict | None = None, visual_for_agent: dict | None = None) -> bool:
        if not _agent_stream_tools_enabled():
            return False
        if not enable_tools:
            return False
        plan_for_agent = plan_for_agent or {}
        ctx_for_agent = ctx_for_agent or {}
        if isinstance(visual_for_agent, dict) and visual_for_agent.get('intent'):
            return False
        block_keys = (
            'request_file_generation', 'use_image_mode', 'use_image_generation', 'use_image_edit',
            'image_generation_requested', 'use_visual',
        )
        if any(bool(plan_for_agent.get(k)) for k in block_keys):
            return False
        if str((ctx_for_agent or {}).get('route_mode') or '').strip().lower() in {'file', 'visual', 'image', 'image_generation'}:
            return False
        prefetch = ctx_for_agent.get('prefetch_decision') if isinstance(ctx_for_agent.get('prefetch_decision'), dict) else {}
        file_action = str((prefetch or {}).get('file_action') or '').strip().lower()
        if file_action and file_action not in {'none', 'direct_answer'}:
            return False
        return True

    def _agent_stream_append_focus_crop_activity(state: dict, result: dict | None = None, *, op_key: str = '', round_idx: int = 0) -> dict:
        return _agent_stream_append_focus_crop_activity_impl(state, result, op_key=op_key, round_idx=round_idx)

    tool_runtime_context = ChatStreamToolRuntimeContext(
        label=label,
        sse=sse,
        append_file_progress=_agent_stream_append_file_progress,
        append_focus_crop_activity=_agent_stream_append_focus_crop_activity,
        activity_delta_frame=_agent_stream_activity_delta_frame,
    )

    def _agent_stream_holder_get(obj, name: str):
        return tool_runtime_context._agent_stream_holder_get(obj, name)

    def _agent_stream_extract_tool_deltas(chunk) -> list[dict]:
        return tool_runtime_context._agent_stream_extract_tool_deltas(chunk)

    def _agent_stream_choice_finish_reason(chunk) -> str:
        return tool_runtime_context._agent_stream_choice_finish_reason(chunk)

    def _agent_stream_parse_args(raw: str) -> dict:
        return tool_runtime_context._agent_stream_parse_args(raw)

    def _agent_stream_status_text(tool_name: str) -> str:
        return tool_runtime_context._agent_stream_status_text(tool_name)

    def _agent_stream_is_sandbox_tool(name: str = '') -> bool:
        return tool_runtime_context._agent_stream_is_sandbox_tool(name)

    def _agent_stream_sandbox_status_frame(name: str = '', args: dict | None = None, result: dict | None = None, *, phase: str = 'start', state: dict | None = None, call_id: str = '') -> str:
        return tool_runtime_context._agent_stream_sandbox_status_frame(name, args, result, phase=phase, state=state, call_id=call_id)

    def _agent_stream_sandbox_arguments_status_frame(state: dict | None = None, calls_acc=None, *, force: bool = False) -> str:
        return tool_runtime_context._agent_stream_sandbox_arguments_status_frame(state, calls_acc, force=force)

    def _agent_stream_doc_visual_review_required(result: dict | None = None) -> bool:
        return tool_runtime_context._agent_stream_doc_visual_review_required(result)

    def _agent_stream_doc_visual_review_args(read_result: dict | None = None, read_args: dict | None = None, user_text: str = '') -> dict:
        return tool_runtime_context._agent_stream_doc_visual_review_args(read_result, read_args, user_text)

    def _agent_stream_doc_visual_review_path_key(path: str = '') -> str:
        return tool_runtime_context._agent_stream_doc_visual_review_path_key(path)

    def _agent_stream_doc_visual_review_mark_done(state: dict | None = None, path: str = '') -> bool:
        return tool_runtime_context._agent_stream_doc_visual_review_mark_done(state, path)

    def _agent_stream_doc_visual_review_cache_get(state: dict | None = None, path: str = '') -> dict:
        return tool_runtime_context._agent_stream_doc_visual_review_cache_get(state, path)

    def _agent_stream_doc_visual_review_cache_put(state: dict | None = None, result: dict | None = None, args: dict | None = None) -> str:
        return tool_runtime_context._agent_stream_doc_visual_review_cache_put(state, result, args)

    def _agent_stream_planned_doc_visual_review_paths(calls: list | None = None) -> set[str]:
        return tool_runtime_context._agent_stream_planned_doc_visual_review_paths(calls)

    def _agent_stream_doc_visual_review_already_done(state: dict | None = None, path: str = '') -> bool:
        return tool_runtime_context._agent_stream_doc_visual_review_already_done(state, path)

    def _agent_stream_queue_responses_visual_items(state: dict, runtime_state: dict, result: dict | None = None, *, log_tag: str = 'RESPONSES_NATIVE_SANDBOX_IMAGE_INPUT_QUEUED') -> int:
        if not isinstance(result, dict):
            return 0
        extra_items = result.get('_responses_input_items') if isinstance(result.get('_responses_input_items'), list) else []
        if not extra_items:
            return 0
        pending_items = state.setdefault('pending_responses_extra_input_items', [])
        if isinstance(pending_items, list):
            pending_items.extend([dict(x) if isinstance(x, dict) else x for x in extra_items])
        count = 0
        try:
            count = int(result.get('visual_input_count') or result.get('selected_image_count') or result.get('image_count') or 0)
            runtime_state['responses_image_input_queued'] = True
            runtime_state['responses_image_input_count'] = int(runtime_state.get('responses_image_input_count') or 0) + count
        except Exception:
            count = 0
        try:
            app_logger.info('[%s] model=%s items=%s images=%s visual_inputs=%s path=%s mode=%s', log_tag, model, len(extra_items), int(result.get('image_count') or 0), int(result.get('visual_input_count') or result.get('selected_image_count') or 0), str(result.get('path') or '')[:160], str(result.get('mode') or '')[:40])
        except Exception:
            pass
        return count

    def _agent_stream_auto_doc_visual_review(read_result: dict | None, read_args: dict | None, state: dict, runtime_state: dict, user_text: str = '') -> tuple[dict, dict]:
        if not _agent_stream_doc_visual_review_required(read_result):
            return {}, {}
        visual_args = _agent_stream_doc_visual_review_args(read_result, read_args, user_text)
        if not visual_args:
            return {}, {}
        if _agent_stream_doc_visual_review_already_done(state, str(visual_args.get('path') or '')):
            return {}, {}
        try:
            app_logger.info('[SANDBOX_DOC_VISUAL_REVIEW_AUTO_START] model=%s path=%s', model, str(visual_args.get('path') or '')[:180])
        except Exception:
            pass
        try:
            visual_result = _exec_tool(
                'sandbox_analyze_file_images',
                visual_args,
                user_geo=user_geo,
                messages=messages or [],
                client_override=client_override,
                model=model,
            )
        except Exception as visual_err:
            visual_result = {'ok': False, 'error': f'{type(visual_err).__name__}: {visual_err}', 'path': str(visual_args.get('path') or ''), 'auto_doc_visual_review': True}
        if isinstance(visual_result, dict):
            visual_result['auto_doc_visual_review'] = True
            visual_result.setdefault('path', str(visual_args.get('path') or ''))
        try:
            app_logger.info('[SANDBOX_DOC_VISUAL_REVIEW_AUTO_DONE] model=%s path=%s ok=%s images=%s visual_inputs=%s error=%s', model, str(visual_args.get('path') or '')[:180], bool((visual_result or {}).get('ok')), int((visual_result or {}).get('image_count') or 0), int((visual_result or {}).get('visual_input_count') or (visual_result or {}).get('selected_image_count') or 0), str((visual_result or {}).get('error') or '')[:180])
        except Exception:
            pass
        return visual_args, visual_result if isinstance(visual_result, dict) else {}

    source_activity = ChatStreamSourceActivityContext(
        append_progress_event=_agent_stream_append_progress_event,
        progress_meta=_agent_stream_progress_meta,
        focus_crop_activity=lambda state, result=None, *, op_key='', round_idx=0: _agent_stream_append_focus_crop_activity(state, result, op_key=op_key, round_idx=round_idx),
        cfg_int=_agent_stream_cfg_int,
    )

    def _agent_stream_search_source_item_limit() -> int:
        return source_activity.search_source_item_limit()

    def _agent_stream_push_sources(state: dict, name: str, result: dict | None = None, *, target: str = '') -> None:
        return source_activity.push_sources(state, name, result, target=target)

    def _agent_stream_visible_sources(state: dict | None = None, limit: int = 8) -> list[dict]:
        return source_activity.visible_sources(state, limit=limit)

    def _agent_stream_web_query_text(args: dict | None = None, result: dict | None = None) -> str:
        return source_activity.web_query_text(args, result)

    def _agent_stream_source_items_from_result(result: dict | list | None = None, limit: int = 200) -> list[dict]:
        return source_activity.source_items_from_result(result, limit=limit)

    def _agent_stream_web_query_groups_public(state: dict | None = None) -> list[dict]:
        return source_activity.web_query_groups_public(state)

    def _agent_stream_web_query_groups_meta(state: dict | None = None) -> dict:
        return source_activity.web_query_groups_meta(state)

    def _agent_stream_note_web_search_group(state: dict, round_idx: int, args: dict | None = None, result: dict | None = None, status: str = 'searching') -> dict:
        return source_activity.note_web_search_group(state, round_idx, args, result, status=status)

    def _agent_stream_note_web_fetch_event(state: dict, name: str = '', args: dict | None = None, result: dict | None = None, status: str = 'reading', call_id: str = '', round_idx: int = 0) -> dict:
        return source_activity.note_web_fetch_event(state, name, args, result, status=status, call_id=call_id, round_idx=round_idx)

    def _agent_stream_note_image_search_event(state: dict, args: dict | None = None, result: dict | None = None, status: str = 'searching', call_id: str = '', round_idx: int = 0) -> dict:
        return source_activity.note_image_search_event(state, args, result, status=status, call_id=call_id, round_idx=round_idx)

    def _agent_stream_image_activity_items(rows, limit: int = 8) -> list[dict]:
        """把图片工具数据压缩成 ActivityEvent 可持久化的轻量预览引用。"""
        normalizer = globals().get('_activity_event_image_items')
        if callable(normalizer):
            try:
                return normalizer({'image_items': list(rows or [])}, limit=limit) or []
            except Exception:
                pass
        return []

    def _agent_stream_append_focus_crop_activity_impl(state: dict, result: dict | None = None, *, op_key: str = '', round_idx: int = 0) -> dict:
        """统一记录真实 Python 裁剪代码及其静态图片结果。"""
        if not isinstance(state, dict) or not isinstance(result, dict):
            return {}
        raw_executions = result.get('focus_crop_executions')
        if not isinstance(raw_executions, list):
            one = result.get('focus_crop_execution') if isinstance(result.get('focus_crop_execution'), dict) else {}
            raw_executions = [one] if one else []
        executions = [dict(row) for row in raw_executions if isinstance(row, dict) and (row.get('code') or row.get('images'))]
        crop_items = _agent_stream_image_activity_items(result.get('focus_crop_items') or [], limit=8)
        if not executions:
            return {}
        now_ms = int(time.time() * 1000)
        crop_code = str(executions[0].get('code') or '').strip()
        crop_stdout = '\n'.join(str(row.get('stdout') or '').strip() for row in executions if str(row.get('stdout') or '').strip())
        crop_stderr = '\n'.join(str(row.get('stderr') or row.get('error') or '').strip() for row in executions if str(row.get('stderr') or row.get('error') or '').strip())
        try:
            crop_started_at = min(int(row.get('started_at') or now_ms) for row in executions)
        except Exception:
            crop_started_at = now_ms
        try:
            crop_done_at = max(int(row.get('done_at') or now_ms) for row in executions)
        except Exception:
            crop_done_at = now_ms
        crop_ok = bool(crop_items) and all(bool(row.get('ok')) for row in executions)
        operation_key = str(op_key or result.get('visual_exec_id') or 'focus_crop').strip()
        return _agent_stream_append_progress_event(state, {
            'key': f'sandbox|image_focus_crop|{operation_key}'[:700],
            'stage': 'sandbox_done' if crop_ok else 'sandbox_error',
            'panel_stage': 'sandbox',
            'tool': 'sandbox_run',
            'title': '图片局部裁剪',
            'detail': '',
            'state': 'done' if crop_ok else 'error',
            'percent': 100,
            'ts': crop_started_at,
            'started_at': crop_started_at,
            'updated_at': crop_done_at,
            'done_at': crop_done_at,
            'source': 'analysis_focus_crop',
            'activity_op': 'analysis_focus_crop',
            'operation_key': f'image_focus_crop|{operation_key}'[:160],
            'command': crop_code,
            'command_language': 'python',
            'stdout': crop_stdout,
            'stderr': crop_stderr,
            'exit_code': 0 if crop_ok else next((row.get('exit_code') for row in executions if row.get('exit_code') not in (None, 0)), 1),
            'show_debug': True,
            'debug_available': True,
            'image_items': crop_items,
            'image_count': len(crop_items),
            'round': int(round_idx or state.get('tool_rounds') or 0),
        })

    existing_image_analysis_context = ChatStreamExistingImageAnalysisContext(
        model=model,
        messages=messages,
        user_geo=user_geo,
        client_override=client_override,
        latest_user_text=_latest_user_text_from_messages,
        messages_for_image_index=_agent_stream_messages_for_image_index,
        recent_assistant_image_rows=_agent_stream_recent_assistant_image_rows,
        external_image_asset_candidate_rows=_agent_stream_external_image_asset_candidate_rows,
        filter_image_rows_by_endpoint=_orch_filter_image_rows_by_endpoint,
        enrich_candidate_rows=_agent_stream_enrich_direct_image_candidate_rows,
        direct_resolve_image_rows=_agent_stream_direct_resolve_image_rows,
        current_endpoint_mode=_orch_current_endpoint_mode,
        normalize_endpoint_mode=_normalize_chat_api_endpoint_mode,
        build_existing_image_visual_ctx=_orch_build_existing_image_visual_ctx,
        image_activity_items=_agent_stream_image_activity_items,
        import_image_row_to_sandbox=_agent_stream_import_image_row_to_sandbox,
        exec_tool=_exec_tool,
        append_progress_event=_agent_stream_append_progress_event,
        progress_meta=_agent_stream_progress_meta,
        logger=app_logger,
    )

    def _agent_stream_current_user_image_activity_items(limit: int = 8) -> list[dict]:
        """读取本轮用户消息里已经进入模型输入的普通图片，不包含文件渲染页。"""
        try:
            has_images = globals().get('_latest_user_message_has_images')
            if callable(has_images) and not bool(has_images(messages or [])):
                return []
            candidate_builder = globals().get('_image_mode_candidate_rows')
            if not callable(candidate_builder):
                return []
            candidate_rows = [
                dict(row)
                for row in (
                    candidate_builder(
                        _agent_stream_messages_for_image_index(messages or []),
                        user_text=_latest_user_text_from_messages(messages or []),
                        limit=max(8, min(int(limit or 8) * 2, 24)),
                    )
                    or []
                )
                if isinstance(row, dict) and _agent_stream_is_current_user_image_row(row)
            ]
            if not candidate_rows:
                return []
            enriched = _agent_stream_enrich_direct_image_candidate_rows(candidate_rows)
            return _agent_stream_image_activity_items(enriched or candidate_rows, limit=limit)
        except Exception:
            return []

    def _agent_stream_note_current_user_image_input(state: dict, *, round_idx: int = 0) -> bool:
        image_items = _agent_stream_current_user_image_activity_items(limit=8)
        if not image_items:
            return False
        image_ids = [
            str(item.get('image_id') or item.get('attachment_id') or item.get('file_library_id') or '').strip()
            for item in image_items
            if str(item.get('image_id') or item.get('attachment_id') or item.get('file_library_id') or '').strip()
        ]
        op_key = 'current_user_input|' + ('|'.join(image_ids) or str(len(image_items)))
        state['_current_user_image_activity_op_key'] = op_key
        state['_current_user_image_activity_ids'] = list(image_ids)
        _agent_stream_note_existing_image_analysis_event(
            state,
            {'image_ids': image_ids},
            {'ok': True, 'activity_image_items': image_items, 'image_count': len(image_items)},
            status='analyzing',
            call_id=op_key,
            round_idx=round_idx,
        )
        return True

    def _agent_stream_note_existing_image_analysis_event(
        state: dict,
        args: dict | None = None,
        result: dict | None = None,
        *,
        status: str = 'analyzing',
        call_id: str = '',
        round_idx: int = 0,
    ) -> dict:
        return existing_image_analysis_context.note_event(state, args, result, status=status, call_id=call_id, round_idx=round_idx)

    def _agent_stream_tool_call_message(call_obj: dict) -> dict:
        call_id = str(call_obj.get('id') or '').strip() or ('call_' + uuid.uuid4().hex[:18])
        name = str(((call_obj.get('function') or {}).get('name')) or '').strip()
        if not name:
            return {}
        arguments = str(((call_obj.get('function') or {}).get('arguments')) or '').strip() or '{}'
        return {
            'id': call_id,
            'type': 'function',
            'function': {
                'name': name,
                'arguments': arguments,
            },
        }

    def _agent_stream_kb_results_for_meta(result: dict | None = None, limit: int = 12) -> list[dict]:
        return knowledge_context.results_for_meta(result, limit)

    def _agent_stream_note_kb_result(state: dict, result: dict | None = None, args: dict | None = None) -> dict:
        return knowledge_context.note_result(state, result, args)

    def _agent_stream_run_analyze_existing_image_tool(args: dict | None = None) -> dict:
        return existing_image_analysis_context.run_tool(args)


    direct_image_handoff_context = ChatStreamDirectImageHandoffContext(
        messages=messages,
        user_geo=user_geo,
        user_time=user_time,
        web_enabled=web_enabled,
        web_k=web_k,
        web_max_pages=web_max_pages,
        latest_user_text=_latest_user_text_from_messages,
        strip_lane_system_messages=_orch_strip_lane_system_messages,
        sanitize_messages_for_model=_sanitize_messages_for_model,
        build_orchestrator_soft_hint=_build_orchestrator_soft_hint,
        inject_runtime_tool_context=_inject_runtime_tool_context,
        inject_orchestrator_soft_hint=_inject_orchestrator_soft_hint,
        build_direct_image_task_plan=lambda args=None: _agent_stream_build_direct_image_task_plan(args),
        logger=app_logger,
        model=model,
    )

    def _agent_stream_file_handoff_task_type(args: dict | None = None) -> str:
        raw = str(((args or {}).get('task_type') or (args or {}).get('type') or '')).strip().lower()
        aliases = {
            'file_edit': 'file_edit', 'edit_file': 'file_edit', 'file_editing': 'file_edit', 'edit_existing': 'file_edit',
            'file_generation': 'file_generation', 'generate_file': 'file_generation',
            'file': 'file_generation', 'document': 'file_generation',
        }
        return aliases.get(raw, '')

    def _agent_stream_run_direct_file_handoff(args: dict | None = None):
        """Stop retired direct file handoff before it can bypass sandbox artifact runtime."""
        args = dict(args or {}) if isinstance(args, dict) else {}
        yield sse('status', {'text': f'{label} 文件交付已切换为沙盒链路：先导入/写入 /mnt/data，验证后发布。'})
        yield sse('meta', {
            'model': model,
            'mode': 'agent_stream',
            'route_mode': 'streaming_agent',
            'search_stage': 'file_handoff_removed',
            'status_text': '直接文件 handoff 已停用，请使用 sandbox artifact runtime。',
        })
        return

    def _agent_stream_image_handoff_task_type(args: dict | None = None) -> str:
        return direct_image_handoff_context.image_handoff_task_type(args)

    def _agent_stream_direct_image_prefetch(args: dict | None = None) -> dict:
        return direct_image_handoff_context.direct_image_prefetch(args)

    image_resolver = ChatStreamImageResolver(label=label)

    def _agent_stream_arg_string_values(args: dict | None = None, *keys: str) -> list[str]:
        return image_resolver.arg_string_values(args, *keys)

    def _agent_stream_image_row_key(row: dict | None = None) -> str:
        return image_resolver.image_row_key(row)

    def _agent_stream_image_id_norm(value: str = '') -> str:
        return image_resolver.image_id_norm(value)

    def _agent_stream_image_id_variants(value: str = '') -> list[str]:
        return image_resolver.image_id_variants(value)

    def _agent_stream_image_alias_numeric_token(value: str = '') -> str:
        return image_resolver.image_alias_numeric_token(value)

    def _agent_stream_alias_matches_primary_number(alias: str = '', primary_id: str = '') -> bool:
        return image_resolver.alias_matches_primary_number(alias, primary_id)

    def _agent_stream_sanitize_image_aliases(row: dict | None = None, aliases: list | None = None, *, stable_id: str = '') -> list[str]:
        return image_resolver.sanitize_image_aliases(row, aliases, stable_id=stable_id)

    def _agent_stream_direct_image_ref_norm(value: str = '') -> str:
        return image_resolver.direct_image_ref_norm(value)

    image_candidate_context = ChatStreamImageCandidateContext(
        model=model,
        messages=messages,
        external_image_asset_messages=external_image_asset_messages,
        client_override=client_override,
        image_candidate_sources=_agent_stream_eager_image_candidate_sources,
        messages_for_image_index=_agent_stream_messages_for_image_index,
        current_endpoint_mode=lambda: _orch_current_endpoint_mode(client_override),
        is_current_user_image_row=_agent_stream_is_current_user_image_row,
        filter_image_rows_by_endpoint=_orch_filter_image_rows_by_endpoint,
        enrich_candidate_rows=_agent_stream_enrich_direct_image_candidate_rows,
        sort_image_rows=_agent_stream_sort_image_rows,
        image_row_key=_agent_stream_image_row_key,
    )

    direct_image_binder = ChatStreamDirectImageBinder(
        model=model,
        messages=messages,
        client_override=client_override,
        direct_image_rows_for_model=_agent_stream_direct_image_rows_for_model,
    )

    def _agent_stream_model_resolve_direct_image_refs_once(args: dict | None, candidate_rows: list[dict] | None, *, task_type: str = '', prompt_text: str = '') -> dict:
        return direct_image_binder.resolve_once(args, candidate_rows, task_type=task_type, prompt_text=prompt_text)


    direct_image_planner = ChatStreamDirectImagePlanner(
        messages=messages,
        client_override=client_override,
        image_generation_settings=image_generation_settings,
        image_handoff_task_type=_agent_stream_image_handoff_task_type,
        external_image_asset_candidate_rows=_agent_stream_external_image_asset_candidate_rows,
        enrich_candidate_rows=_agent_stream_enrich_direct_image_candidate_rows,
        direct_resolve_image_rows=_agent_stream_direct_resolve_image_rows,
        arg_string_values=_agent_stream_arg_string_values,
        model_resolve_refs_once=_agent_stream_model_resolve_direct_image_refs_once,
    )

    def _agent_stream_build_direct_image_task_plan(args: dict | None = None) -> dict:
        return direct_image_planner.build_plan(args)

    def _agent_stream_direct_image_context(args: dict | None = None) -> dict:
        return direct_image_handoff_context.direct_image_context(args)

    def _agent_stream_run_direct_image_handoff(args: dict | None = None, *, activity_state: dict | None = None):
        args = dict(args or {}) if isinstance(args, dict) else {}
        task_type = _agent_stream_image_handoff_task_type(args)
        reason = str(args.get('reason') or args.get('prompt') or args.get('instruction') or _latest_user_text_from_messages(messages or []) or '').strip()[:300]
        if not task_type:
            raise RuntimeError('__agent_stream_image_delivery_handoff__')
        try:
            app_logger.info('[AGENT_STREAM_DIRECT_IMAGE_HANDOFF_START] model=%s task_type=%s reason=%s', model, task_type, reason[:160])
        except Exception:
            pass
        if show_steps:
            if task_type == 'existing_image_analysis':
                status_text = f'{label} 已确认需要分析图片，直接进入图片分析链路…'
            elif task_type in {'image_edit', 'reference_edit', 'variation'}:
                status_text = f'{label} 已确认需要编辑图片，直接进入图片交付链路…'
            else:
                status_text = f'{label} 已确认需要生成图片，直接进入图片交付链路…'
            yield sse('status', {'text': status_text})

        direct_ctx = _agent_stream_direct_image_context(args)
        _ctx, stage = _run_orchestrator_once(
            model,
            messages or [],
            user_geo=user_geo,
            user_time=user_time,
            client_override=client_override,
            enable_visual=enable_visual,
            web_enabled=web_enabled,
            web_k=web_k,
            web_max_pages=web_max_pages,
            image_generation_enabled=bool(image_generation_enabled),
            image_generation_settings=dict(image_generation_settings or {}),
            show_steps=show_steps,
            label=label,
            prepared_ctx=direct_ctx,
        )
        image_generated_files = list(stage.get('generated_artifacts') or [])
        image_reply_payload = _image_generation_artifacts_to_image_reply_payload(
            image_generated_files,
            subject=str(((stage.get('image_generation_result') or {}).get('subject') or (stage.get('tool_plan') or {}).get('image_generation_subject') or '')).strip(),
            task_mode=str(((stage.get('image_generation_result') or {}).get('task_mode') or '')).strip(),
        )
        if image_reply_payload:
            yield sse('image_reply', image_reply_payload)

        image_result = stage.get('image_generation_result') if isinstance(stage.get('image_generation_result'), dict) else {}

        existing_image_analysis_result = None
        existing_image_response_items: list = []
        if task_type == 'existing_image_analysis':
            plan_for_analysis = stage.get('image_task_plan') if isinstance(stage.get('image_task_plan'), dict) else {}
            selected_ids_for_analysis = (
                args.get('selected_image_ids')
                or args.get('image_ids')
                or args.get('image_id')
                or args.get('image_ref')
                or plan_for_analysis.get('selected_image_ids')
                or plan_for_analysis.get('edit_target_image_ids')
                or plan_for_analysis.get('reference_image_ids')
                or []
            )
            analysis_query = str(
                args.get('query')
                or args.get('prompt')
                or plan_for_analysis.get('prompt')
                or reason
                or _latest_user_text_from_messages(messages or [])
                or ''
            ).strip()
            analysis_args = {
                'selected_image_ids': selected_ids_for_analysis,
                'query': analysis_query,
                'reason': reason,
            }
            direct_image_activity_state = activity_state if isinstance(activity_state, dict) else {}
            direct_image_activity_call_id = 'direct_image_analysis:' + ('|'.join(str(x or '').strip() for x in selected_ids_for_analysis) if isinstance(selected_ids_for_analysis, list) else str(selected_ids_for_analysis or ''))
            _agent_stream_note_existing_image_analysis_event(
                direct_image_activity_state,
                analysis_args,
                None,
                status='analyzing',
                call_id=direct_image_activity_call_id,
            )
            yield _agent_stream_activity_delta_frame(direct_image_activity_state)
            if show_steps:
                yield sse('status', {'text': f'{label} 正在按图片 ID 导入沙盒并准备视觉证据…'})
            existing_image_analysis_result = _agent_stream_run_analyze_existing_image_tool(analysis_args)
            if isinstance(existing_image_analysis_result, dict):
                _agent_stream_note_existing_image_analysis_event(
                    direct_image_activity_state,
                    analysis_args,
                    existing_image_analysis_result,
                    status='analyzed' if bool(existing_image_analysis_result.get('ok')) else 'error',
                    call_id=direct_image_activity_call_id,
                )
                yield _agent_stream_activity_delta_frame(direct_image_activity_state)
                existing_image_response_items = [dict(x) if isinstance(x, dict) else x for x in (existing_image_analysis_result.get('_responses_input_items') or []) if isinstance(x, dict)]
                stage['visual_ctx'] = None
                stage['image_generation_result'] = {
                    'ok': bool(existing_image_analysis_result.get('ok')),
                    'need_generation': False,
                    'task_mode': 'analyze',
                    'image_task_type': 'existing_image_analysis',
                    'analysis_result': existing_image_analysis_result,
                }
                stage.setdefault('tool_records', []).append({
                    'name': 'analyze_existing_image',
                    'args': analysis_args,
                    'result': existing_image_analysis_result,
                })
                image_result = stage.get('image_generation_result') if isinstance(stage.get('image_generation_result'), dict) else {}
                try:
                    app_logger.info(
                        '[AGENT_STREAM_DIRECT_IMAGE_ANALYZE_TOOL_DONE] model=%s ok=%s selected=%s response_items=%s endpoint=%s',
                        model,
                        bool(existing_image_analysis_result.get('ok')),
                        json.dumps(existing_image_analysis_result.get('selected_image_ids') or selected_ids_for_analysis or [], ensure_ascii=False)[:300],
                        len(existing_image_response_items),
                        _orch_current_endpoint_mode(client_override),
                    )
                except Exception:
                    pass

        direct_image_failure_context = ChatStreamDirectImageFailureContext(task_type=task_type)

        def _agent_stream_direct_image_failure_context(result: dict | None = None) -> str:
            return direct_image_failure_context.build(result)
        image_direct_reply_done = _stage_should_direct_return_image_reply(stage)
        final_text_parts = []
        if not image_direct_reply_done:
            final_messages = _build_orchestrated_final_messages(stage, messages or [], user_geo=user_geo, visual_ctx=stage.get('visual_ctx'))
            if existing_image_response_items:
                final_messages.extend(existing_image_response_items)
            image_failure_context = _agent_stream_direct_image_failure_context(image_result)
            if image_failure_context:
                final_messages.append({'role': 'system', '_kind': 'image_generation_failure_context', 'content': image_failure_context})
                if show_steps:
                    yield sse('status', {'text': f'{label} 图片工具返回失败，正在交给主模型继续处理…'})
            final_messages = _inject_main_chat_runtime_model_context(final_messages, _main_chat_runtime_model_for_context())
            guarded_final_messages = _inject_agent_final_direct_answer_guard(final_messages, stage)
            guarded_final_messages = _inject_agent_final_fact_bridge(model, guarded_final_messages, stage, client_override=client_override)
            if show_steps:
                yield sse('status', {'text': f'{label} 图片工具完成，正在整理回答…'})
            last_ping = time.time()
            for chunk in _stream_completion(phase='agent_stream_direct_image_final', model=model, messages=guarded_final_messages):
                now = time.time()
                if now - last_ping >= 2.0:
                    yield ': ping\n\n'
                    last_ping = now
                reasoning_text, answer_text, reasoning_source = _merge_stream_chunk_texts(chunk)
                if reasoning_text:
                    for frame in _reasoning_sse_frames(reasoning_text, reasoning_source):
                        yield frame
                if answer_text:
                    final_text_parts.append(answer_text)
                    safe_text = _strip_leaked_think_tags(answer_text)
                    if safe_text:
                        yield sse('delta', {'text': safe_text})
            trailing_reasoning, trailing_answer, trailing_source = _flush_pending_think_text()
            if trailing_reasoning:
                for frame in _reasoning_sse_frames(trailing_reasoning, trailing_source):
                    yield frame
            if trailing_answer:
                final_text_parts.append(trailing_answer)
                safe_trailing = _strip_leaked_think_tags(trailing_answer)
                if safe_trailing:
                    yield sse('delta', {'text': safe_trailing})

        yield sse('meta', {
            'model': model,
            'mode': 'agent_stream_direct_image',
            'route_mode': 'visual',
            'answer_strategy': 'direct_image_handoff',
            'image_handoff_direct': True,
            'image_handoff_task_type': task_type,
            'image_generation_ok': bool(image_result.get('ok')),
            'image_task_type': str(image_result.get('image_task_type') or task_type),
            'image_task_mode': str(image_result.get('task_mode') or ''),
            'image_artifact_count': len(image_generated_files),
            'tool_counts': dict(stage.get('tool_counts') or {}),
            'native_reasoning_connected': bool(native_reasoning_seen),
            'native_reasoning_source': native_reasoning_source if native_reasoning_seen else '',
            **_current_runtime_model_meta(),
        })
        if native_reasoning_seen:
            yield sse('reasoning_meta', {'connected': True, 'done': True, 'source': native_reasoning_source or 'native_field', 'status': 'done', 'native_reasoning_text': str(native_reasoning_text_accum or '')[-60000:], 'seq': _last_activity_timeline_seq(), 'order': _last_activity_timeline_seq()})
        yield from _done_frames()
        try:
            app_logger.info(
                '[AGENT_STREAM_DIRECT_IMAGE_HANDOFF_DONE] model=%s task_type=%s artifacts=%s final_chars=%s ok=%s',
                model, task_type, len(image_generated_files), len(''.join(final_text_parts)), bool(image_result.get('ok')),
            )
        except Exception:
            pass


    def _run_streaming_tool_agent(ctx_for_agent: dict | None = None, visual_for_agent: dict | None = None, runtime_state: dict | None = None):
        _native_agent_original_overrides = {}
        _native_agent_overrides_changed = False
        try:
            snapshot_getter = globals().get('_current_request_overrides_snapshot')
            original_snapshot = snapshot_getter() if callable(snapshot_getter) else {}
            _native_agent_original_overrides = dict(original_snapshot or {}) if isinstance(original_snapshot, dict) else {}
            filtered_snapshot = _agent_stream_tool_web_override_snapshot(_native_agent_original_overrides, lane='chat_completions_streaming_agent')
            if filtered_snapshot != _native_agent_original_overrides:
                setter = globals().get('_set_request_overrides')
                if callable(setter):
                    setter(filtered_snapshot)
                    _native_agent_overrides_changed = True
                    try:
                        removed_keys = sorted(set(_native_agent_original_overrides.keys()) - set(filtered_snapshot.keys()))
                        app_logger.info('[AGENT_STREAM_TOOL_WEB_PARAMS_IGNORED] model=%s lane=%s keys=%s', model, 'chat_completions_streaming_agent', removed_keys)
                    except Exception:
                        pass
        except Exception:
            try:
                app_logger.warning('[AGENT_STREAM_TOOL_WEB_PARAMS_FILTER_FAILED] model=%s lane=%s', model, 'chat_completions_streaming_agent')
            except Exception:
                pass
        try:
            runtime_state = runtime_state if isinstance(runtime_state, dict) else {}
            state = {
                'tool_rounds': 0,
                'tool_counts': {},
                'sources': [],
                'source_seen': set(),
                'searched_sources': [],
                'searched_source_seen': set(),
                'web_results': 0,
                'pages': 0,
                'queries_used': [],
                'web_query_groups': [],
                'kb_results': 0,
                'kb_queries_used': [],
                'kb_doc_count': 0,
                'kb_chunk_count': 0,
                'kb_search_results': [],
                'kb_hit': False,
                'file_tool_used': False,
                'file_tool_rounds': 0,
                'file_progress_items': [],
                'file_context_injected': False,
            }
            state['_runtime_state'] = runtime_state
            last_user_text = _latest_user_text_from_messages(messages or [])
            if _agent_stream_note_current_user_image_input(state):
                yield _agent_stream_activity_delta_frame(state)
            direct_first_agent = bool((ctx_for_agent or {}).get('agent_stream_direct_first'))
            gate_groups = _responses_native_capability_groups(((ctx_for_agent or {}).get('responses_native_tool_gate') or {}).get('tool_groups') or runtime_state.get('tool_groups') or [])
            chat_gate = (ctx_for_agent or {}).get('chat_tool_gate') if isinstance((ctx_for_agent or {}).get('chat_tool_gate'), dict) else {}
            chat_gate_groups = _agent_stream_chat_capability_groups((chat_gate or {}).get('tool_groups') or runtime_state.get('chat_tool_groups') or [])
            if direct_first_agent and not chat_gate_groups:
                chat_gate_groups = ['all']
            base_agent_messages = _agent_stream_messages_with_knowledge_context(messages or [])
            turn_file_context_needed, turn_file_context_reason = _agent_stream_file_context_needed_for_current_turn(base_agent_messages)
            cache_file_context_needed = _agent_stream_prompt_cache_file_context_needed(base_agent_messages)
            if _agent_stream_file_context_needed_for_groups(gate_groups) or turn_file_context_needed or cache_file_context_needed:
                if turn_file_context_needed:
                    try:
                        app_logger.info('[AGENT_STREAM_FILE_CONTEXT_TURN_INJECT] model=%s reason=%s groups=%s', model, turn_file_context_reason, json.dumps(gate_groups, ensure_ascii=False))
                    except Exception:
                        pass
                elif cache_file_context_needed:
                    try:
                        app_logger.info('[AGENT_STREAM_PROMPT_CACHE_FILE_CONTEXT_INJECT] model=%s groups=%s', model, json.dumps(gate_groups, ensure_ascii=False))
                    except Exception:
                        pass
                base_agent_messages = _agent_stream_messages_with_file_context(base_agent_messages, state=state)
            agent_messages = _agent_stream_messages_with_visual_context(base_agent_messages)
            file_context_injected = False
            try:
                file_context_injected = any(
                    isinstance(m, dict)
                    and str(m.get('role') or '').strip().lower() == 'system'
                    and str(m.get('_kind') or '').strip() in {'file_memory', 'file_recall', 'file_edit_audit'}
                    for m in (agent_messages or [])
                )
            except Exception:
                file_context_injected = False
            agent_messages = _orch_append_recent_file_edit_audit_context(agent_messages)
            if visual_for_agent is not None or not direct_first_agent:
                agent_messages = _inject_visual_context_messages(agent_messages, visual_for_agent)
            _agent_stream_log_prompt_cache_message_shape('chat_agent_before_runtime', agent_messages)
            prompt_ctx_for_agent = dict(ctx_for_agent or {})
            prompt_ctx_for_agent['chat_tool_gate'] = {
                **(chat_gate if isinstance(chat_gate, dict) else {}),
                'tool_groups': list(chat_gate_groups or []),
                'route_mode': 'tools',
            }
            prompt_ctx_for_agent['agent_has_file_context'] = bool(file_context_injected)
            try:
                file_guidance_gate = globals().get('_prepare_messages_should_inject_file_guidance')
                file_guidance_hit = bool(callable(file_guidance_gate) and file_guidance_gate(last_user_text, messages or []))
            except Exception:
                file_guidance_hit = False
            prompt_ctx_for_agent['agent_file_task_likely'] = bool(turn_file_context_needed or file_guidance_hit)
            agent_messages.append(_agent_streaming_runtime_prompt(prompt_ctx_for_agent))
            if direct_first_agent and file_context_injected:
                agent_messages.append({
                    'role': 'system',
                    '_kind': 'agent_stream_file_loop_hint',
                    'content': '当前只有文件清单/血缘事实，没有正文或视觉证据；只有用户确实需要文件证据或文件操作时才进入 sandbox artifact runtime 导入、读取或运行。普通聊天直接答；已有产物链接用元数据，不重生成/重发布。',
                })
            if state.get('file_progress_items'):
                yield sse('meta', {
                    'model': model,
                    'mode': 'agent_stream',
                    'route_mode': 'streaming_agent',
                    'search_stage': 'file_context',
                    'status_text': '已准备沙盒文件清单',
                    **_agent_stream_file_progress_meta(state),
                })
            try:
                chat_cache_messages = globals().get('_prompt_cache_chat_messages_for_request')
                if callable(chat_cache_messages):
                    agent_messages = chat_cache_messages(agent_messages)
            except Exception:
                pass
            _agent_stream_log_prompt_cache_message_shape('chat_agent_after_cache_order', agent_messages)
            agent_messages = _agent_stream_sanitize_tool_loop_messages(agent_messages)
            _agent_stream_log_prompt_cache_message_shape('chat_agent_after_sanitize', agent_messages)
            agent_messages = _orch_dedupe_model_messages(agent_messages)
            _agent_stream_log_prompt_cache_message_shape('chat_agent_after_dedupe', agent_messages)
            compact_tool_schema = False
            tool_specs = _agent_stream_filter_tool_specs_for_settings(_agent_stream_tool_specs(compact=compact_tool_schema, allowed_tool_groups=chat_gate_groups))
            mcp_chat_specs = globals().get('_mcp_client_chat_tool_specs')
            if callable(mcp_chat_specs):
                tool_specs = list(tool_specs or []) + list(mcp_chat_specs(client_override) or [])
            tool_specs = _agent_stream_stabilize_tool_specs(tool_specs)
            if compact_tool_schema:
                tool_specs = _agent_stream_slim_chat_tool_specs(tool_specs)
            lead_buffer_chars = _agent_stream_cfg_int('AGENT_STREAM_LEAD_BUFFER_CHARS', 360, min_value=0, max_value=4000)
            last_ping = time.time()
            historical_generated_artifacts = _collect_generated_file_artifacts_from_messages(agent_messages or [])

            def _emit_delta(text: str):
                safe = _strip_leaked_think_tags(str(text or ''))
                current_files = state.get('file_artifacts') or []
                safe = _strip_redundant_generated_file_lines(safe, current_files or historical_generated_artifacts)
                if not safe:
                    return None
                runtime_state['visible_delta'] = True
                return sse('delta', {'text': safe})

            for round_idx in agent_tool_round_indices():
                _raise_if_async_job_stopped()
                calls_by_index: dict[int, dict] = {}
                tool_call_seen = False
                lead_buffer = ''
                lead_flushed = False
                streamed_any = False
                call_kwargs = {
                    'model': model,
                    'messages': agent_messages,
                    'tools': tool_specs,
                    'tool_choice': 'auto',
                }
                try:
                    app_logger.info('[AGENT_STREAM_LOOP_START] model=%s round=%s messages=%s tools=%s', model, round_idx, len(agent_messages or []), len(tool_specs or []))
                except Exception:
                    pass
                for chunk in _stream_completion(phase='agent_stream', _emit_open_retry_activity=True, **call_kwargs):
                    now = time.time()
                    if now - last_ping >= 2.0:
                        yield ': ping\n\n'
                        last_ping = now
                    if isinstance(chunk, dict) and str(chunk.get('_webai_stream_control') or '') == 'activity_event':
                        row = chunk.get('activity_event') if isinstance(chunk.get('activity_event'), dict) else {}
                        if row:
                            _agent_stream_append_progress_event(state, row)
                            frame = _agent_stream_activity_delta_frame(state)
                            if frame:
                                yield frame
                        continue
                    reasoning_text, answer_text, reasoning_source = _merge_stream_chunk_texts(chunk)
                    if reasoning_text:
                        for frame in _reasoning_sse_frames(reasoning_text, reasoning_source):
                            yield frame
                    deltas = _agent_stream_extract_tool_deltas(chunk)
                    if deltas:
                        tool_call_seen = True
                        for d in deltas:
                            try:
                                idx_raw = d.get('index')
                                idx = int(idx_raw) if idx_raw is not None else len(calls_by_index)
                            except Exception:
                                idx = len(calls_by_index)
                            acc = calls_by_index.setdefault(idx, {'index': idx, 'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                            if d.get('id'):
                                acc['id'] = str(d.get('id') or '')
                            if d.get('type'):
                                acc['type'] = str(d.get('type') or 'function')
                            if d.get('name'):
                                acc['function']['name'] += str(d.get('name') or '')
                            if d.get('arguments'):
                                acc['function']['arguments'] += str(d.get('arguments') or '')
                        sandbox_args_frame = _agent_stream_sandbox_arguments_status_frame(state, calls_by_index)
                        if sandbox_args_frame:
                            yield sandbox_args_frame
                        preview_frame = _agent_stream_file_process_preview_frame(state, calls_by_index, preferred_mode='generate_new')
                        if preview_frame:
                            yield preview_frame
                    if answer_text and not tool_call_seen:
                        streamed_any = True
                        if not lead_flushed and lead_buffer_chars > 0:
                            lead_buffer += answer_text
                            if len(lead_buffer) < lead_buffer_chars:
                                continue
                            lead_flushed = True
                            frame = _emit_delta(lead_buffer)
                            lead_buffer = ''
                            if frame:
                                yield frame
                            continue
                        if not lead_flushed:
                            lead_flushed = True
                        frame = _emit_delta(answer_text)
                        if frame:
                            yield frame
                    elif answer_text and tool_call_seen:
                        streamed_any = True
                    finish_reason = _agent_stream_choice_finish_reason(chunk)
                    if finish_reason == 'tool_calls':
                        tool_call_seen = True
                    elif finish_reason and not tool_call_seen and lead_buffer:
                        # 上游已经明确结束普通文本生成时，立即释放短回复。
                        # 不再等待 HTTP 流连接彻底关闭，避免部分兼容服务先返回
                        # stop/usage、后延迟关闭连接时，页面长时间看不到任何正文。
                        lead_flushed = True
                        frame = _emit_delta(lead_buffer)
                        lead_buffer = ''
                        if frame:
                            yield frame

                trailing_reasoning, trailing_answer, trailing_source = _flush_pending_think_text()
                if trailing_reasoning:
                    for frame in _reasoning_sse_frames(trailing_reasoning, trailing_source):
                        yield frame
                if trailing_answer and not tool_call_seen:
                    streamed_any = True
                    if not lead_flushed and lead_buffer_chars > 0:
                        lead_buffer += trailing_answer
                    else:
                        frame = _emit_delta(trailing_answer)
                        if frame:
                            yield frame

                calls = []
                for _, raw_call in sorted(calls_by_index.items(), key=lambda kv: kv[0]):
                    call_msg = _agent_stream_tool_call_message(raw_call)
                    if call_msg:
                        calls.append(call_msg)

                if not calls:
                    if lead_buffer:
                        frame = _emit_delta(lead_buffer)
                        if frame:
                            yield frame
                    if native_reasoning_seen:
                        yield sse('reasoning_meta', {'connected': True, 'done': True, 'source': native_reasoning_source or 'native_field', 'status': 'done', 'native_reasoning_text': str(native_reasoning_text_accum or '')[-60000:], 'seq': _last_activity_timeline_seq(), 'order': _last_activity_timeline_seq()})
                    visible_sources = _agent_stream_visible_sources(state, limit=8)
                    yield sse('meta', {
                        'model': model,
                        'mode': 'agent_stream',
                        'route_mode': 'streaming_agent',
                        'agent_stream_tools': True,
                        'tool_rounds': int(state.get('tool_rounds') or 0),
                        'tool_counts': dict(state.get('tool_counts') or {}),
                        'web_hit': bool((state.get('web_results') or 0) or (state.get('pages') or 0) or (state.get('queries_used') or [])),
                        'visual_hit': bool((state.get('image_results') or 0) or (state.get('image_queries_used') or [])),
                        'source_count': len(visible_sources),
                        'sources': visible_sources,
                        'search_results': list(state.get('searched_sources') or []),
                        'searched_results': list(state.get('searched_sources') or []),
                        'result_count': int(state.get('web_results') or 0),
                        'page_count': int(state.get('pages') or 0),
                        'queries_used': [str(q or '').strip() for q in (state.get('queries_used') or []) if str(q or '').strip()],
                        **_agent_stream_web_query_groups_meta(state),
                        'use_knowledge_base': bool(state.get('kb_hit') or (state.get('kb_queries_used') or []) or (state.get('kb_results') or 0)),
                        'knowledge_hit': bool(state.get('kb_hit')),
                        'kb_result_count': int(state.get('kb_results') or 0),
                        'kb_doc_count': int(state.get('kb_doc_count') or 0),
                        'kb_chunk_count': int(state.get('kb_chunk_count') or 0),
                        'kb_queries_used': [str(q or '').strip() for q in (state.get('kb_queries_used') or []) if str(q or '').strip()],
                        'kb_search_results': [dict(x) for x in (state.get('kb_search_results') or []) if isinstance(x, dict)],
                        'use_visual': bool((state.get('image_results') or 0) or (state.get('image_queries_used') or [])),
                        'visual_intent': 'image_search' if bool((state.get('image_results') or 0) or (state.get('image_queries_used') or [])) else '',
                        'image_stage': 'searched' if bool((state.get('image_results') or 0) or (state.get('image_queries_used') or [])) else '',
                        'image_result_count': int(state.get('image_results') or 0),
                        'image_queries_used': [str(q or '').strip() for q in (state.get('image_queries_used') or []) if str(q or '').strip()],
                        **_agent_stream_file_progress_meta(state),
                        **_native_reasoning_meta_payload(),
                        **_current_runtime_model_meta(),
                    })
                    yield from _done_frames()
                    return

                if lead_buffer and runtime_state.get('visible_delta'):
                    # If a model unexpectedly writes a long preface before a tool call,
                    # keep already committed text, but do not flush the uncommitted tail.
                    lead_buffer = ''

                assistant_tool_msg = {'role': 'assistant', 'content': None, 'tool_calls': calls}
                agent_messages.append(assistant_tool_msg)
                state['tool_rounds'] = int(state.get('tool_rounds') or 0) + 1
                state['planned_doc_visual_review_paths'] = _agent_stream_planned_doc_visual_review_paths(calls)
                for call in calls:
                    _raise_if_async_job_stopped()
                    fn = call.get('function') or {}
                    name = str(fn.get('name') or '').strip()
                    if not name:
                        continue
                    raw_args = str(fn.get('arguments') or '{}')
                    args = _agent_stream_parse_args(raw_args)
                    call_id = str(call.get('id') or call.get('call_id') or '').strip()
                    if name == 'sandbox_analyze_file_images':
                        if not str(args.get('query') or args.get('prompt') or '').strip():
                            args['query'] = str(last_user_text or '').strip()
                    if name == 'handoff_to_image_delivery':
                        try:
                            app_logger.info('[AGENT_STREAM_IMAGE_DELIVERY_HANDOFF] model=%s task_type=%s reason=%s', model, str((args or {}).get('task_type') or '')[:80], str((args or {}).get('reason') or '')[:160])
                        except Exception:
                            pass
                        file_handoff_kind = _agent_stream_file_handoff_task_type(args)
                        if direct_first_agent and file_handoff_kind == 'file_edit':
                            for frame in _agent_stream_run_direct_file_handoff(args):
                                yield frame
                            return
                        if direct_first_agent and _agent_stream_image_handoff_task_type(args):
                            for frame in _agent_stream_run_direct_image_handoff(args, activity_state=state):
                                yield frame
                            return
                        raise RuntimeError('__agent_stream_image_delivery_handoff__')
                    if '_invalid_json_arguments' in args:
                        result = {'ok': False, 'error': 'invalid_tool_arguments', 'raw': args.get('_invalid_json_arguments')}
                    elif name in {'web_search', 'fetch_url', 'fetch_urls'} and not _agent_stream_web_enabled_for_turn():
                        result = {'ok': False, 'error': 'web_disabled_by_frontend_switch'}
                    else:
                        if name == 'web_search':
                            raw_k = args.get('k')
                            if raw_k in (None, ''):
                                args.pop('k', None)
                            else:
                                try:
                                    args['k'] = max(1, min(int(raw_k), 10))
                                except Exception:
                                    args.pop('k', None)
                        if name == 'image_search':
                            raw_count = args.get('count') if args.get('count') not in (None, '') else args.get('k')
                            if raw_count not in (None, ''):
                                try:
                                    args['count'] = max(1, min(int(raw_count), 10))
                                except Exception:
                                    args.pop('count', None)
                        if name in {'fetch_url', 'fetch_urls'} and not args.get('max_chars'):
                            args['max_chars'] = 12000
                        if name in {'search_knowledge_base', 'read_knowledge_base_document'}:
                            args.setdefault('space_id', str(kb_space_id or '').strip())
                            args.setdefault('doc_id', str(kb_doc_id or '').strip())
                            args['_kb_enabled'] = bool(kb_enabled is not False)
                        visual_cache_hit = False
                        if name == 'sandbox_analyze_file_images':
                            cached_visual_result = _agent_stream_doc_visual_review_cache_get(state, str(args.get('path') or args.get('filename') or ''))
                            if cached_visual_result:
                                result = cached_visual_result
                                visual_cache_hit = True
                                yield sse('status', {'text': f'{label} 已复用文件视觉页缓存…'})
                        if (not visual_cache_hit) and _agent_stream_is_sandbox_tool(name):
                            yield _agent_stream_sandbox_status_frame(name, args, phase='start', state=state, call_id=call_id)
                        elif not visual_cache_hit:
                            yield sse('status', {'text': _agent_stream_status_text(name)})
                            if name in {'fetch_url', 'fetch_urls'}:
                                _agent_stream_note_web_fetch_event(state, name, args, None, status='reading', call_id=call_id, round_idx=round_idx)
                                yield _agent_stream_activity_delta_frame(state)
                            elif name == 'image_search':
                                _agent_stream_note_image_search_event(state, args, None, status='searching', call_id=call_id, round_idx=round_idx)
                                yield _agent_stream_activity_delta_frame(state)
                            elif name == 'analyze_existing_image':
                                _agent_stream_note_existing_image_analysis_event(state, args, None, status='analyzing', call_id=call_id, round_idx=round_idx)
                                yield _agent_stream_activity_delta_frame(state)
                        if name == 'web_search':
                            web_group_meta = _agent_stream_note_web_search_group(state, round_idx, args, None, status='searching')
                            yield _agent_stream_activity_delta_frame(state)
                            yield sse('meta', {
                                'model': model,
                                'mode': 'agent_stream',
                                'route_mode': 'streaming_agent',
                                'use_web_research': True,
                                'search_stage': 'searching',
                                'result_count': int(state.get('web_results') or 0),
                                'page_count': int(state.get('pages') or 0),
                                'queries_used': [str(q or '').strip() for q in (state.get('queries_used') or []) if str(q or '').strip()],
                                **web_group_meta,
                                **_agent_stream_progress_meta(state),
                            })
                        try:
                            if visual_cache_hit:
                                pass
                            else:
                                if name == 'save_memory':
                                    result = _agent_stream_run_save_memory_tool(args)
                                elif name == 'analyze_existing_image':
                                    raw_ids = args.get('image_ids') or args.get('selected_image_ids') or args.get('image_id') or args.get('image_ref') or []
                                    if raw_ids in (None, '', []):
                                        recent_rows = _agent_stream_recent_assistant_image_rows(limit=1)
                                        if recent_rows:
                                            fallback_id = str((recent_rows[0] or {}).get('stable_image_id') or (recent_rows[0] or {}).get('role_image_id') or (recent_rows[0] or {}).get('image_id') or '').strip()
                                            if fallback_id:
                                                args['image_ids'] = [fallback_id]
                                                args.setdefault('reason', 'chat_analyze_existing_image_recent_assistant_fallback_no_selected_ids')
                                                try:
                                                    app_logger.info('[AGENT_STREAM_ANALYZE_IMAGE_RECENT_ASSISTANT_FALLBACK] model=%s selected=%s reason=no_selected_ids', model, fallback_id)
                                                except Exception:
                                                    pass
                                    result = _agent_stream_run_analyze_existing_image_tool(args)
                                else:
                                    args = _agent_stream_attach_sandbox_audits_to_publish_args(state, name, args)
                                    result = _exec_tool(name, args, user_geo=user_geo, messages=messages or [], client_override=client_override, model=model)
                        except Exception as tool_err:
                            result = {'ok': False, 'error': f'{type(tool_err).__name__}: {tool_err}'}
                    if name == 'get_location' and isinstance(result, dict) and bool(result.get('need_browser_location')):
                        prompt = result.get('location_permission_request') if isinstance(result.get('location_permission_request'), dict) else {}
                        request_id = 'loc_' + uuid.uuid4().hex
                        yield sse('location_permission_request', {
                            'title': str(prompt.get('title') or '需要使用你的位置来回答这个问题'),
                            'message': str(prompt.get('message') or '开启后仅用于本次对话请求。'),
                            'confirm_text': str(prompt.get('confirm_text') or '确定'),
                            'cancel_text': str(prompt.get('cancel_text') or '取消'),
                            'source': 'get_location',
                            'request_id': request_id,
                        })
                        wait_fn = globals().get('_chat_async_wait_location_permission')
                        if callable(wait_fn):
                            wait_result = wait_fn(request_id=request_id)
                            wait_geo = wait_result.get('user_geo') if isinstance(wait_result, dict) else None
                            if isinstance(wait_geo, dict) and bool((wait_result or {}).get('ok')):
                                wait_state = wait_result.get('location_state') if isinstance(wait_result.get('location_state'), dict) else None
                                effective_geo = dict(wait_geo)
                                if wait_state:
                                    effective_geo['_location_state'] = dict(wait_state)
                                try:
                                    args = _agent_stream_attach_sandbox_audits_to_publish_args(state, name, args)
                                    result = _exec_tool(name, args, user_geo=effective_geo, messages=messages or [], client_override=client_override, model=model)
                                except Exception as tool_err:
                                    result = {'ok': False, 'error': f'{type(tool_err).__name__}: {tool_err}'}
                                yield sse('status', {'text': '已获取位置，正在继续回答…'})
                            else:
                                reason = str((wait_result or {}).get('reason') or '').strip() if isinstance(wait_result, dict) else ''
                                wait_state = wait_result.get('location_state') if isinstance(wait_result, dict) and isinstance(wait_result.get('location_state'), dict) else None
                                existing_state = dict(user_geo.get('_location_state') or {}) if isinstance(user_geo, dict) and isinstance(user_geo.get('_location_state'), dict) else {}
                                if wait_state is None and existing_state:
                                    wait_state = dict(existing_state)
                                elif isinstance(wait_state, dict) and existing_state:
                                    old_approx = existing_state.get('approximate_location') if isinstance(existing_state.get('approximate_location'), dict) else {}
                                    cur_approx = wait_state.get('approximate_location') if isinstance(wait_state.get('approximate_location'), dict) else {}
                                    if old_approx.get('available') and not cur_approx.get('available'):
                                        wait_state = dict(wait_state)
                                        wait_state['approximate_location'] = dict(old_approx)
                                result = {
                                    'ok': False,
                                    '_kind': 'location',
                                    'need_location': True,
                                    'need_browser_location': False,
                                    'cancelled': bool((wait_result or {}).get('cancelled')) if isinstance(wait_result, dict) else True,
                                    'timeout': bool((wait_result or {}).get('timeout')) if isinstance(wait_result, dict) else False,
                                    'reason': reason or 'cancelled',
                                    'message': '用户取消或未完成本次精确定位授权。',
                                    'summary': '精确定位授权未完成；已把取消状态和可见位置证据回交给模型继续判断。',
                                }
                                if isinstance(wait_state, dict) and wait_state:
                                    try:
                                        evidence = _build_location_tool_payload(last_user_text, user_geo={'_location_state': wait_state}, request_precise=False)
                                        if isinstance(evidence, dict) and isinstance(evidence.get('location_visibility'), dict):
                                            result['location_visibility'] = evidence.get('location_visibility')
                                        if isinstance(evidence, dict) and isinstance(evidence.get('location'), dict):
                                            result['location'] = evidence.get('location')
                                            result['location_type'] = evidence.get('location_type')
                                    except Exception:
                                        result['location_state'] = dict(wait_state)
                    suppress_cached_visual_progress = bool(name == 'sandbox_analyze_file_images' and isinstance(result, dict) and bool(result.get('_reused_cached_tool_result')))
                    if _agent_stream_is_sandbox_tool(name) and not suppress_cached_visual_progress:
                        yield _agent_stream_sandbox_status_frame(name, args, result, phase='done', state=state, call_id=call_id)
                    if name in {'sandbox_write_file', 'sandbox_write_files', 'sandbox_create_office_file', 'sandbox_replace_text', 'sandbox_import_files', 'sandbox_run'}:
                        _agent_stream_note_sandbox_write_result(state, name, result, args)
                    if name == 'sandbox_analyze_file_images' and isinstance(result, dict):
                        _agent_stream_doc_visual_review_mark_done(state, str(result.get('path') or args.get('path') or args.get('filename') or ''))
                        if not bool(result.get('_reused_cached_tool_result')):
                            _agent_stream_doc_visual_review_cache_put(state, result, args)
                    auto_visual_args = {}
                    auto_visual_result = {}
                    if name == 'sandbox_read_file' and _agent_stream_doc_visual_review_required(result):
                        auto_visual_args = _agent_stream_doc_visual_review_args(result, args, last_user_text)
                        auto_visual_key = _agent_stream_doc_visual_review_path_key(str(auto_visual_args.get('path') or '')) if auto_visual_args else ''
                        planned_visual_paths = state.get('planned_doc_visual_review_paths') if isinstance(state.get('planned_doc_visual_review_paths'), set) else set()
                        if auto_visual_args and auto_visual_key not in planned_visual_paths and not _agent_stream_doc_visual_review_already_done(state, str(auto_visual_args.get('path') or '')):
                            yield _agent_stream_sandbox_status_frame('sandbox_analyze_file_images', auto_visual_args, phase='start', state=state)
                            try:
                                app_logger.info('[AGENT_STREAM_DOC_VISUAL_REVIEW_AUTO_START] model=%s path=%s', model, str(auto_visual_args.get('path') or '')[:180])
                            except Exception:
                                pass
                            try:
                                auto_visual_result = _exec_tool(
                                    'sandbox_analyze_file_images',
                                    auto_visual_args,
                                    user_geo=user_geo,
                                    messages=messages or [],
                                    client_override=client_override,
                                    model=model,
                                )
                            except Exception as visual_err:
                                auto_visual_result = {'ok': False, 'error': f'{type(visual_err).__name__}: {visual_err}', 'path': str(auto_visual_args.get('path') or ''), 'auto_doc_visual_review': True}
                            if isinstance(auto_visual_result, dict):
                                auto_visual_result['auto_doc_visual_review'] = True
                                auto_visual_result.setdefault('path', str(auto_visual_args.get('path') or ''))
                                _agent_stream_doc_visual_review_cache_put(state, auto_visual_result, auto_visual_args)
                            yield _agent_stream_sandbox_status_frame('sandbox_analyze_file_images', auto_visual_args, auto_visual_result, phase='done', state=state)
                            state['tool_counts']['sandbox_analyze_file_images'] = int((state.get('tool_counts') or {}).get('sandbox_analyze_file_images') or 0) + 1
                            try:
                                app_logger.info('[AGENT_STREAM_DOC_VISUAL_REVIEW_AUTO_DONE] model=%s path=%s ok=%s images=%s visual_inputs=%s error=%s', model, str(auto_visual_args.get('path') or '')[:180], bool((auto_visual_result or {}).get('ok')), int((auto_visual_result or {}).get('image_count') or 0), int((auto_visual_result or {}).get('visual_input_count') or (auto_visual_result or {}).get('selected_image_count') or 0), str((auto_visual_result or {}).get('error') or '')[:180])
                            except Exception:
                                pass
                    compact = _compress_tool_result_for_model(name, result, user_text=last_user_text)
                    state['tool_counts'][name] = int((state.get('tool_counts') or {}).get(name) or 0) + 1
                    if auto_visual_args and isinstance(auto_visual_result, dict) and auto_visual_result:
                        auto_visual_compact = _compress_tool_result_for_model('sandbox_analyze_file_images', auto_visual_result, user_text=last_user_text)
                        auto_visual_content = json.dumps(auto_visual_compact, ensure_ascii=False) if not isinstance(auto_visual_compact, str) else str(auto_visual_compact or '')
                        auto_visual_limit = max(12000, int(_orch_tool_budget('sandbox_analyze_file_images', phase='chat_tool_result')))
                        agent_messages.append({
                            'role': 'system',
                            'content': (
                                '后端在 sandbox_read_file 之后自动执行了 sandbox_analyze_file_images，因为该文档的文本层/OOXML 诊断要求渲染页视觉审阅。'
                                '继续回答时必须融合这个渲染页视觉证据、sandbox_read_file 文本证据和 OOXML 诊断；不要只给通用论文评价。\n'
                                + auto_visual_content[:auto_visual_limit]
                            ),
                        })
                    if name == 'web_search' and isinstance(result, dict):
                        try:
                            visible_search_items = _agent_stream_source_items_from_result(result, limit=_agent_stream_search_source_item_limit())
                            state['web_results'] = int(state.get('web_results') or 0) + max(len(result.get('results') or []), len(visible_search_items))
                        except Exception:
                            pass
                        _agent_stream_push_sources(state, name, result, target='searched')
                        web_group_meta = _agent_stream_note_web_search_group(state, round_idx, args, result, status='searched')
                        yield _agent_stream_activity_delta_frame(state)
                        yield sse('meta', {
                            'model': model,
                            'mode': 'agent_stream',
                            'route_mode': 'streaming_agent',
                            'use_web_research': True,
                            'search_stage': 'searched',
                            'result_count': int(state.get('web_results') or 0),
                            'page_count': int(state.get('pages') or 0),
                            'queries_used': [str(q or '').strip() for q in (state.get('queries_used') or []) if str(q or '').strip()],
                            **web_group_meta,
                            **_agent_stream_progress_meta(state),
                            'search_results': [dict(it) for it in (state.get('searched_sources') or []) if isinstance(it, dict)] or [dict(it) for it in (result.get('results') or []) if isinstance(it, dict)],
                        })
                    elif name in {'search_knowledge_base', 'read_knowledge_base_document'} and isinstance(result, dict):
                        kb_meta = _agent_stream_note_kb_result(state, result, args)
                        yield sse('meta', {
                            'model': model,
                            'mode': 'agent_stream',
                            'route_mode': 'streaming_agent',
                            'search_stage': 'kb_document_read' if name == 'read_knowledge_base_document' else 'kb_searched',
                            **kb_meta,
                        })
                    elif name in {'search_account_context', 'read_account_context'} and isinstance(result, dict):
                        yield sse('meta', {
                            'model': model,
                            'mode': 'agent_stream',
                            'route_mode': 'streaming_agent',
                            'search_stage': 'history_searched',
                            'history_result_count': int(result.get('result_count') or len(result.get('results') or [])) if isinstance(result, dict) else 0,
                        })
                    elif name in {'sandbox_publish_files'} and isinstance(result, dict):
                        file_meta = _agent_stream_note_sandbox_publish_result(state, result, args)
                        new_files = [dict(x) for x in (result.get('files') or []) if isinstance(x, dict)]
                        if new_files:
                            yield sse('files', {'files': new_files, 'stage': name})
                        yield sse('meta', {
                            'model': model,
                            'mode': 'agent_stream',
                            'route_mode': 'streaming_agent',
                            'search_stage': 'sandbox_published' if name == 'sandbox_publish_files' else 'sandbox_published',
                            'status_text': '沙盒文件已发布' if new_files else '沙盒文件发布失败',
                            'file_count': len(new_files),
                            'published_paths': [str(x or '') for x in (result.get('published_paths') or [])],
                            **file_meta,
                        })
                    elif name == 'sandbox_create_office_file' and isinstance(result, dict) and isinstance(result.get('files'), list) and result.get('files'):
                        new_files = [dict(x) for x in (result.get('files') or []) if isinstance(x, dict)]
                        file_meta = _agent_stream_file_progress_meta(state)
                        state['sandbox_published'] = True
                        _agent_stream_merge_file_artifacts(state, new_files)
                        if new_files:
                            yield sse('files', {'files': new_files, 'stage': 'sandbox_office_auto_published'})
                        yield sse('meta', {
                            'model': model,
                            'mode': 'agent_stream',
                            'route_mode': 'streaming_agent',
                            'search_stage': 'sandbox_office_auto_published',
                            'status_text': 'Office 文件已生成并发布',
                            'file_count': len(new_files),
                            'published_paths': [str(x or '') for x in (result.get('published_paths') or [])],
                            **file_meta,
                        })
                    elif name == 'image_search' and isinstance(result, dict):
                        try:
                            state['image_results'] = int(state.get('image_results') or 0) + len(result.get('results') or [])
                        except Exception:
                            pass
                        q = str(result.get('query') or args.get('query') or '').strip()
                        if q:
                            state.setdefault('image_queries_used', []).append(q)
                        _agent_stream_push_sources(state, name, result)
                        _agent_stream_note_image_search_event(state, args, result, status='searched' if bool(result.get('ok', True)) else 'error', call_id=call_id, round_idx=round_idx)
                        yield _agent_stream_activity_delta_frame(state)
                        image_payload = result.get('image_reply_payload') if isinstance(result.get('image_reply_payload'), dict) else None
                        if image_payload:
                            yield sse('image_reply', image_payload)
                        yield sse('meta', {
                            'model': model,
                            'mode': 'agent_stream',
                            'route_mode': 'streaming_agent',
                            'use_visual': True,
                            'visual_intent': 'image_search',
                            'image_stage': 'searched',
                            'query': q,
                            'image_query': q,
                            'image_result_count': int(state.get('image_results') or 0),
                            'image_queries_used': [str(q or '').strip() for q in (state.get('image_queries_used') or []) if str(q or '').strip()],
                        })
                    elif name in {'fetch_url', 'fetch_urls'} and isinstance(result, dict):
                        try:
                            if name == 'fetch_urls':
                                state['pages'] = int(state.get('pages') or 0) + len(result.get('results') or result.get('pages') or [])
                            else:
                                state['pages'] = int(state.get('pages') or 0) + 1
                        except Exception:
                            pass
                        _agent_stream_push_sources(state, name, result)
                        _agent_stream_note_web_fetch_event(state, name, args, result, status='read' if bool(result.get('ok', True)) else 'error', call_id=call_id, round_idx=round_idx)
                        yield _agent_stream_activity_delta_frame(state)
                        visible_sources = _agent_stream_visible_sources(state, limit=8)
                        yield sse('meta', {
                            'model': model,
                            'mode': 'agent_stream',
                            'route_mode': 'streaming_agent',
                            'use_web_research': True,
                            'search_stage': 'pages_read',
                            'result_count': int(state.get('web_results') or 0),
                            'page_count': int(state.get('pages') or 0),
                            'source_count': len(visible_sources),
                            'sources': visible_sources,
                            'search_results': list(state.get('searched_sources') or []),
                            'searched_results': list(state.get('searched_sources') or []),
                            **_agent_stream_web_query_groups_meta(state),
                            **_agent_stream_progress_meta(state),
                        })
                    elif name == 'analyze_existing_image' and isinstance(result, dict):
                        _agent_stream_note_existing_image_analysis_event(
                            state,
                            args,
                            result,
                            status='analyzed' if bool(result.get('ok')) else 'error',
                            call_id=call_id,
                            round_idx=round_idx,
                        )
                        yield _agent_stream_activity_delta_frame(state)
                        yield sse('meta', {
                            'model': model,
                            'mode': 'agent_stream',
                            'route_mode': 'streaming_agent',
                            'use_visual': True,
                            'visual_intent': 'existing_image_analysis',
                            'image_stage': 'analyzed',
                            'image_result_count': int(result.get('image_count') or 0),
                        })
                    elif name == 'get_weather' and isinstance(result, dict) and result.get('_kind') == 'weather':
                        weather_present = {'mode': 'card'}
                        try:
                            should_emit_weather = (not bool(result.get('ok'))) or str((weather_present or {}).get('mode') or 'card').lower() == 'card'
                        except Exception:
                            should_emit_weather = True
                        if should_emit_weather:
                            yield sse('weather', result)
                    elif name == 'save_memory' and isinstance(result, dict) and bool(result.get('ok')) and not bool(result.get('skipped')):
                        ev = result.get('event') if isinstance(result.get('event'), dict) else result
                        yield sse('memory_event', ev)

                    content = json.dumps(compact, ensure_ascii=False) if not isinstance(compact, str) else compact
                    content_limit = max(800, int(_orch_tool_budget(name, phase='chat_tool_result')))
                    agent_messages.append({
                        'role': 'tool',
                        'tool_call_id': str(call.get('id') or ''),
                        'name': name,
                        'content': content[:content_limit],
                    })
                if show_steps:
                    yield sse('status', {'text': f'{label} 工具完成，继续生成回复…'})

        finally:
            if _native_agent_overrides_changed:
                try:
                    setter = globals().get('_set_request_overrides')
                    if callable(setter):
                        setter(_native_agent_original_overrides)
                except Exception:
                    pass


    responses_native_config = ResponsesNativeConfigContext(
        user_geo=user_geo,
        user_time=user_time,
        agent_stream_env_flag=_agent_stream_env_flag,
        agent_stream_web_enabled_for_turn=_agent_stream_web_enabled_for_turn,
    )

    def _responses_native_web_search_enabled() -> bool:
        return responses_native_config.web_search_enabled()

    def _responses_native_override_snapshot() -> dict:
        return responses_native_config.override_snapshot()

    def _responses_native_cfg_value(*names: str, default=None):
        return responses_native_config.cfg_value(*names, default=default)

    def _responses_native_cfg_bool(*names: str, default: bool = False) -> bool:
        return responses_native_config.cfg_bool(*names, default=default)

    def _responses_native_cfg_int(*names: str, default: int = 0, min_value: int = 0, max_value: int = 128) -> int:
        return responses_native_config.cfg_int(*names, default=default, min_value=min_value, max_value=max_value)

    def _responses_native_split_list_value(raw) -> list[str]:
        return responses_native_config.split_list_value(raw)

    def _responses_native_user_location_from_settings() -> dict:
        return responses_native_config.user_location_from_settings()

    def _responses_native_web_search_tool_spec() -> dict:
        return responses_native_config.web_search_tool_spec()

    def _responses_native_has_web_search_tool(tools: list | None = None) -> bool:
        return responses_native_config.has_web_search_tool(tools)

    def _responses_native_apply_web_request_params(body: dict, tools: list | None = None) -> dict:
        return responses_native_config.apply_web_request_params(body, tools)


    responses_native_tool_specs_context = ResponsesNativeToolSpecsContext(
        image_generation_enabled=image_generation_enabled,
        image_generation_settings=image_generation_settings,
        memory_tool_enabled=_agent_stream_memory_tool_enabled,
        save_memory_tool_spec=_agent_stream_save_memory_tool_spec,
        stabilize_tool_specs=_agent_stream_stabilize_tool_specs,
        agent_stream_cfg_int=_agent_stream_cfg_int,
        web_search_enabled=_responses_native_web_search_enabled,
        code_interpreter_enabled=_responses_native_code_interpreter_enabled,
        code_interpreter_tool_spec=_responses_native_code_interpreter_tool_spec,
        image_task_mode=_responses_native_image_task_mode,
        filter_tool_specs_for_settings=_agent_stream_filter_tool_specs_for_settings,
        chat_tool_specs=_agent_stream_tool_specs,
        web_search_tool_spec=_responses_native_web_search_tool_spec,
        web_enabled_for_turn=_agent_stream_web_enabled_for_turn,
        prompt_cache_wants_stable_tools=_prompt_cache_runtime_wants_cache,
    )

    def _responses_native_tool_specs(compact: bool = True, allowed_tool_groups: list | None = None, *, image_task_type: str = '', eager_source_images: bool = False) -> list[dict]:
        specs = responses_native_tool_specs_context.tool_specs(compact=compact, allowed_tool_groups=allowed_tool_groups, image_task_type=image_task_type, eager_source_images=eager_source_images)
        mcp_response_specs = globals().get('_mcp_client_responses_tool_specs')
        if callable(mcp_response_specs):
            specs = list(specs or []) + list(mcp_response_specs(client_override) or [])
        return _agent_stream_stabilize_tool_specs(specs)


    responses_native_state = ResponsesNativeStateContext(
        capability_groups=_responses_native_capability_groups,
    )

    def _responses_native_acc_key(payload: dict | None = None, item: dict | None = None) -> str:
        return responses_native_state.acc_key(payload, item)

    def _responses_native_merge_call(calls: dict, payload: dict | None = None, item: dict | None = None) -> None:
        return responses_native_state.merge_call(calls, payload, item)

    def _responses_native_merge_args_delta(calls: dict, payload: dict | None = None, event_type: str = '') -> None:
        return responses_native_state.merge_args_delta(calls, payload, event_type)

    def _responses_native_calls_list(calls_by_key: dict) -> list[dict]:
        return responses_native_state.calls_list(calls_by_key)

    def _responses_native_function_call_input_items(calls: list[dict]) -> list[dict]:
        return responses_native_state.function_call_input_items(calls)

    def _responses_native_merge_reasoning_item(items_by_key: dict, item: dict | None = None) -> None:
        return responses_native_state.merge_reasoning_item(items_by_key, item)

    def _responses_native_reasoning_input_items(items_by_key: dict | None = None) -> list[dict]:
        return responses_native_state.reasoning_input_items(items_by_key)

    def _responses_native_merge_response_output_item(items_by_key: dict, item: dict | None = None) -> None:
        return responses_native_state.merge_response_output_item(items_by_key, item)

    def _responses_native_response_output_input_items(items_by_key: dict | None = None) -> list[dict]:
        return responses_native_state.response_output_input_items(items_by_key)

    def _responses_native_trace_assistant_text(items: list | None = None) -> str:
        for item in reversed(list(items or [])):
            if not isinstance(item, dict) or str(item.get('type') or '').strip().lower() != 'message':
                continue
            return _RESPONSES_CONVERSATION_TRACES._item_text(item)
        return ''

    def _responses_native_store_conversation_trace(
        replay_items: list | None,
        output_items: list | None,
        *,
        endpoint: str,
        context_signature: str,
        user_text: str,
    ) -> bool:
        if temporary_chat or not str(client_session_id or '').strip():
            return False
        final_items = list(output_items or [])
        assistant_text = _responses_native_trace_assistant_text(final_items)
        if not assistant_text:
            return False
        stored = _RESPONSES_CONVERSATION_TRACES.store(
            session_id=client_session_id,
            endpoint=endpoint,
            model=model,
            context_signature=context_signature,
            replay_items=list(replay_items or []) + final_items,
            last_user_text=user_text,
            assistant_text=assistant_text,
        )
        if stored:
            try:
                app_logger.info(
                    '[RESPONSES_CONVERSATION_TRACE_STORED] model=%s session=%s replay_items=%s output_items=%s',
                    model,
                    str(client_session_id or '')[-32:],
                    len(replay_items or []),
                    len(final_items),
                )
            except Exception:
                pass
        return stored

    def _responses_native_image_generation_group_active(state_obj: dict | None = None, groups: list | None = None) -> bool:
        return responses_native_state.image_generation_group_active(state_obj, groups)

    def _responses_native_clear_image_generation_turn_state(state_obj: dict | None = None, runtime_obj: dict | None = None) -> None:
        return responses_native_state.clear_image_generation_turn_state(state_obj, runtime_obj)

    def _responses_native_filter_tools_for_turn(specs: list | None = None, state_obj: dict | None = None) -> list:
        return responses_native_state.filter_tools_for_turn(specs, state_obj)

    def _responses_native_strip_image_generation_input_items(items: list | None = None, state_obj: dict | None = None) -> list:
        return responses_native_state.strip_image_generation_input_items(items, state_obj)


    responses_native_tool_output = ResponsesNativeToolOutputContext()

    def _responses_native_tool_output_text(name: str, result, compact, args: dict | None = None, last_user_text: str = '') -> str:
        return responses_native_tool_output.output_text(name, result, compact, args=args, last_user_text=last_user_text)


    def _responses_native_tool_result_events(
        calls: list[dict],
        state: dict,
        last_user_text: str,
        runtime_state: dict | None = None,
        current_round_idx: int = 0,
    ):
        runtime_state = runtime_state if isinstance(runtime_state, dict) else {}
        try:
            round_idx = int(current_round_idx or state.get('tool_rounds') or 0)
        except Exception:
            round_idx = 0
        outputs: list[dict] = []
        for call in (calls or []):
            _raise_if_async_job_stopped()
            fn = call.get('function') or {}
            name = str(fn.get('name') or '').strip()
            if not name:
                continue
            raw_args = str(fn.get('arguments') or '{}')
            args = _agent_stream_parse_args(raw_args)
            call_id = str(call.get('call_id') or call.get('id') or '').strip() or ('call_' + uuid.uuid4().hex[:18])
            if name == 'handoff_to_image_delivery':
                try:
                    app_logger.info('[RESPONSES_NATIVE_IMAGE_DELIVERY_HANDOFF_BLOCKED] model=%s task_type=%s reason=%s', model, str((args or {}).get('task_type') or '')[:80], str((args or {}).get('reason') or '')[:160])
                except Exception:
                    pass
                file_handoff_kind = _agent_stream_file_handoff_task_type(args)
                if file_handoff_kind == 'file_edit':
                    for frame in _agent_stream_run_direct_file_handoff(args):
                        yield frame
                    return None
                if _agent_stream_image_handoff_task_type(args):
                    result = {
                        'ok': False,
                        'error': 'responses_image_generation_uses_native_tool_only',
                        'message': 'Responses image generation/editing uses the native image_generation tool only. Chat-lane image handoff is not available on the Responses lane.',
                        'task_type': str((args or {}).get('task_type') or ''),
                    }
                else:
                    result = {'ok': False, 'error': 'image_delivery_handoff_not_available_in_responses_native_loop'}
            elif '_invalid_json_arguments' in args:
                result = {'ok': False, 'error': 'invalid_tool_arguments', 'raw': args.get('_invalid_json_arguments')}
            elif name in {'web_search', 'fetch_url', 'fetch_urls'} and not _agent_stream_web_enabled_for_turn():
                result = {'ok': False, 'error': 'web_disabled_by_frontend_switch'}
            else:
                if name == 'web_search':
                    raw_k = args.get('k')
                    if raw_k in (None, ''):
                        args.pop('k', None)
                    else:
                        try:
                            args['k'] = max(1, min(int(raw_k), 10))
                        except Exception:
                            args.pop('k', None)
                if name == 'image_search':
                    raw_count = args.get('count') if args.get('count') not in (None, '') else args.get('k')
                    if raw_count not in (None, ''):
                        try:
                            args['count'] = max(1, min(int(raw_count), 10))
                        except Exception:
                            args.pop('count', None)
                if name in {'fetch_url', 'fetch_urls'} and not args.get('max_chars'):
                    args['max_chars'] = 12000
                if name in {'search_knowledge_base', 'read_knowledge_base_document'}:
                    args.setdefault('space_id', str(kb_space_id or '').strip())
                    args.setdefault('doc_id', str(kb_doc_id or '').strip())
                    args['_kb_enabled'] = bool(kb_enabled is not False)
                if name == 'sandbox_analyze_file_images':
                    if not str(args.get('query') or args.get('prompt') or '').strip():
                        args['query'] = str(last_user_text or '').strip()
                visual_cache_hit = False
                if name == 'sandbox_analyze_file_images':
                    cached_visual_result = _agent_stream_doc_visual_review_cache_get(state, str(args.get('path') or args.get('filename') or ''))
                    if cached_visual_result:
                        result = cached_visual_result
                        visual_cache_hit = True
                        yield sse('status', {'text': '已复用文件视觉页缓存…'})
                if (not visual_cache_hit) and _agent_stream_is_sandbox_tool(name):
                    yield _agent_stream_sandbox_status_frame(name, args, phase='start', state=state, call_id=call_id)
                elif not visual_cache_hit:
                    yield sse('status', {'text': _agent_stream_status_text(name)})
                    if name in {'fetch_url', 'fetch_urls'}:
                        _agent_stream_note_web_fetch_event(state, name, args, None, status='reading', call_id=call_id, round_idx=round_idx)
                        yield _agent_stream_activity_delta_frame(state)
                    elif name == 'image_search':
                        _agent_stream_note_image_search_event(state, args, None, status='searching', call_id=call_id, round_idx=round_idx)
                        yield _agent_stream_activity_delta_frame(state)
                    elif name == 'analyze_existing_image':
                        _agent_stream_note_existing_image_analysis_event(state, args, None, status='analyzing', call_id=call_id, round_idx=round_idx)
                        yield _agent_stream_activity_delta_frame(state)
                if name == 'web_search':
                    web_group_meta = _agent_stream_note_web_search_group(state, round_idx, args, None, status='searching')
                    yield _agent_stream_activity_delta_frame(state)
                    yield sse('meta', {
                        'model': model,
                        'mode': 'responses_native_tools',
                        'route_mode': 'responses_native_agent',
                        'use_web_research': True,
                        'search_stage': 'searching',
                        'result_count': int(state.get('web_results') or 0),
                        'page_count': int(state.get('pages') or 0),
                        'queries_used': [str(q or '').strip() for q in (state.get('queries_used') or []) if str(q or '').strip()],
                        **web_group_meta,
                        **_agent_stream_progress_meta(state),
                    })
                try:
                    if visual_cache_hit:
                        pass
                    elif name == 'save_memory':
                        result = _agent_stream_run_save_memory_tool(args)
                    elif name == 'analyze_existing_image':
                        result = _agent_stream_run_analyze_existing_image_tool(args)
                    else:
                        args = _agent_stream_attach_sandbox_audits_to_publish_args(state, name, args)
                        result = _exec_tool(name, args, user_geo=user_geo, messages=messages or [], client_override=client_override, model=model)
                except Exception as tool_err:
                    result = {'ok': False, 'error': f'{type(tool_err).__name__}: {tool_err}'}
            if name == 'analyze_existing_image' and isinstance(result, dict):
                extra_items = result.get('_responses_input_items') if isinstance(result.get('_responses_input_items'), list) else []
                if extra_items:
                    pending_items = state.setdefault('pending_responses_extra_input_items', [])
                    if isinstance(pending_items, list):
                        pending_items.extend([dict(x) if isinstance(x, dict) else x for x in extra_items])
                    try:
                        runtime_state['responses_image_input_queued'] = True
                        runtime_state['responses_image_input_count'] = int(runtime_state.get('responses_image_input_count') or 0) + int(result.get('image_count') or 0)
                    except Exception:
                        pass
                    try:
                        app_logger.info('[RESPONSES_NATIVE_IMAGE_INPUT_QUEUED] model=%s items=%s images=%s', model, len(extra_items), int(result.get('image_count') or 0))
                    except Exception:
                        pass
            if name == 'sandbox_analyze_file_images' and isinstance(result, dict):
                _agent_stream_doc_visual_review_mark_done(state, str(result.get('path') or args.get('path') or args.get('filename') or ''))
                if not bool(result.get('_reused_cached_tool_result')):
                    _agent_stream_doc_visual_review_cache_put(state, result, args)
                _agent_stream_queue_responses_visual_items(state, runtime_state, result)
            if name == 'sandbox_read_file' and _agent_stream_doc_visual_review_required(result):
                auto_visual_preview_args = _agent_stream_doc_visual_review_args(result, args, last_user_text)
                auto_visual_preview_path = _agent_stream_doc_visual_review_path_key(str((auto_visual_preview_args or {}).get('path') or ''))
                planned_visual_paths = state.get('planned_doc_visual_review_paths') if isinstance(state.get('planned_doc_visual_review_paths'), set) else set()
                auto_visual_seen = False
                try:
                    auto_visual_seen = auto_visual_preview_path in (state.get('doc_visual_review_paths') or set())
                except Exception:
                    auto_visual_seen = False
                cached_auto_visual_result = _agent_stream_doc_visual_review_cache_get(state, str((auto_visual_preview_args or {}).get('path') or '')) if auto_visual_preview_args else {}
                if cached_auto_visual_result:
                    auto_visual_args, auto_visual_result = dict(auto_visual_preview_args), cached_auto_visual_result
                    yield sse('status', {'text': '已复用文件视觉页缓存…'})
                elif auto_visual_preview_args and auto_visual_preview_path not in planned_visual_paths and not auto_visual_seen:
                    yield _agent_stream_sandbox_status_frame('sandbox_analyze_file_images', auto_visual_preview_args, phase='start', state=state)
                    auto_visual_args, auto_visual_result = _agent_stream_auto_doc_visual_review(result, args, state, runtime_state, last_user_text)
                else:
                    auto_visual_args, auto_visual_result = {}, {}
                if auto_visual_args:
                    if not bool((auto_visual_result or {}).get('_reused_cached_tool_result')):
                        yield _agent_stream_sandbox_status_frame('sandbox_analyze_file_images', auto_visual_args, auto_visual_result, phase='done', state=state)
                    state['tool_counts']['sandbox_analyze_file_images'] = int((state.get('tool_counts') or {}).get('sandbox_analyze_file_images') or 0) + 1
                    if not bool((auto_visual_result or {}).get('_reused_cached_tool_result')):
                        _agent_stream_doc_visual_review_cache_put(state, auto_visual_result, auto_visual_args)
                    _agent_stream_queue_responses_visual_items(state, runtime_state, auto_visual_result, log_tag='RESPONSES_NATIVE_AUTO_DOC_VISUAL_INPUT_QUEUED')
                    try:
                        auto_visual_text = _responses_native_tool_output_text(
                            'sandbox_analyze_file_images',
                            auto_visual_result,
                            _compress_tool_result_for_model('sandbox_analyze_file_images', auto_visual_result, user_text=last_user_text),
                            args=auto_visual_args,
                            last_user_text=last_user_text,
                        )
                    except Exception:
                        try:
                            auto_visual_text = json.dumps(_compress_tool_result_for_model('sandbox_analyze_file_images', auto_visual_result, user_text=last_user_text), ensure_ascii=False)
                        except Exception:
                            auto_visual_text = str(auto_visual_result or '')
                    pending_items = state.setdefault('pending_responses_extra_input_items', [])
                    if isinstance(pending_items, list):
                        pending_items.append({
                            'role': 'user',
                            'content': [{
                                'type': 'input_text',
                                'text': (
                                    '后端在 sandbox_read_file 之后自动执行了 sandbox_analyze_file_images，因为该文档的文本层/OOXML 诊断要求渲染页视觉审阅。'
                                    '继续回答时必须像大平台 DOCX 审阅一样，融合文本层、OOXML 诊断、渲染页 input_image 和下面的视觉审阅证据；'
                                    '必须点名页面标签/页码和可见问题，不要只给通用论文评价。\n'
                                    + str(auto_visual_text or '')[:max(12000, int(_orch_tool_budget('sandbox_analyze_file_images', phase='responses_output')))]
                                )
                            }],
                        })
            if name == 'get_location' and isinstance(result, dict) and bool(result.get('need_browser_location')):
                prompt = result.get('location_permission_request') if isinstance(result.get('location_permission_request'), dict) else {}
                request_id = 'loc_' + uuid.uuid4().hex
                yield sse('location_permission_request', {
                    'title': str(prompt.get('title') or '需要使用你的位置来回答这个问题'),
                    'message': str(prompt.get('message') or '开启后仅用于本次对话请求。'),
                    'confirm_text': str(prompt.get('confirm_text') or '确定'),
                    'cancel_text': str(prompt.get('cancel_text') or '取消'),
                    'source': 'get_location',
                    'request_id': request_id,
                })
                wait_fn = globals().get('_chat_async_wait_location_permission')
                if callable(wait_fn):
                    wait_result = wait_fn(request_id=request_id)
                    wait_geo = wait_result.get('user_geo') if isinstance(wait_result, dict) else None
                    if isinstance(wait_geo, dict) and bool((wait_result or {}).get('ok')):
                        wait_state = wait_result.get('location_state') if isinstance(wait_result.get('location_state'), dict) else None
                        effective_geo = dict(wait_geo)
                        if wait_state:
                            effective_geo['_location_state'] = dict(wait_state)
                        try:
                            args = _agent_stream_attach_sandbox_audits_to_publish_args(state, name, args)
                            result = _exec_tool(name, args, user_geo=effective_geo, messages=messages or [], client_override=client_override, model=model)
                        except Exception as tool_err:
                            result = {'ok': False, 'error': f'{type(tool_err).__name__}: {tool_err}'}
                        yield sse('status', {'text': '已获取位置，正在继续回答…'})
                    else:
                        reason = str((wait_result or {}).get('reason') or '').strip() if isinstance(wait_result, dict) else ''
                        wait_state = wait_result.get('location_state') if isinstance(wait_result, dict) and isinstance(wait_result.get('location_state'), dict) else None
                        existing_state = dict(user_geo.get('_location_state') or {}) if isinstance(user_geo, dict) and isinstance(user_geo.get('_location_state'), dict) else {}
                        if wait_state is None and existing_state:
                            wait_state = dict(existing_state)
                        elif isinstance(wait_state, dict) and existing_state:
                            old_approx = existing_state.get('approximate_location') if isinstance(existing_state.get('approximate_location'), dict) else {}
                            cur_approx = wait_state.get('approximate_location') if isinstance(wait_state.get('approximate_location'), dict) else {}
                            if old_approx.get('available') and not cur_approx.get('available'):
                                wait_state = dict(wait_state)
                                wait_state['approximate_location'] = dict(old_approx)
                        result = {
                            'ok': False,
                            '_kind': 'location',
                            'need_location': True,
                            'need_browser_location': False,
                            'cancelled': bool((wait_result or {}).get('cancelled')) if isinstance(wait_result, dict) else True,
                            'timeout': bool((wait_result or {}).get('timeout')) if isinstance(wait_result, dict) else False,
                            'reason': reason or 'cancelled',
                            'message': '用户取消或未完成本次精确定位授权。',
                            'summary': '精确定位授权未完成；已把取消状态和可见位置证据回交给模型继续判断。',
                        }
                        if isinstance(wait_state, dict) and wait_state:
                            try:
                                evidence = _build_location_tool_payload(last_user_text, user_geo={'_location_state': wait_state}, request_precise=False)
                                if isinstance(evidence, dict) and isinstance(evidence.get('location_visibility'), dict):
                                    result['location_visibility'] = evidence.get('location_visibility')
                                if isinstance(evidence, dict) and isinstance(evidence.get('location'), dict):
                                    result['location'] = evidence.get('location')
                                    result['location_type'] = evidence.get('location_type')
                            except Exception:
                                result['location_state'] = dict(wait_state)
            suppress_cached_visual_progress = bool(name == 'sandbox_analyze_file_images' and isinstance(result, dict) and bool(result.get('_reused_cached_tool_result')))
            if _agent_stream_is_sandbox_tool(name) and not suppress_cached_visual_progress:
                yield _agent_stream_sandbox_status_frame(name, args, result, phase='done', state=state, call_id=call_id)
            if name in {'sandbox_write_file', 'sandbox_write_files', 'sandbox_create_office_file', 'sandbox_replace_text', 'sandbox_import_files', 'sandbox_run'}:
                _agent_stream_note_sandbox_write_result(state, name, result, args)
            compact = _compress_tool_result_for_model(name, result, user_text=last_user_text)
            state['tool_counts'][name] = int((state.get('tool_counts') or {}).get(name) or 0) + 1
            if name == 'web_search' and isinstance(result, dict):
                try:
                    visible_search_items = _agent_stream_source_items_from_result(result, limit=_agent_stream_search_source_item_limit())
                    state['web_results'] = int(state.get('web_results') or 0) + max(len(result.get('results') or []), len(visible_search_items))
                except Exception:
                    pass
                _agent_stream_push_sources(state, name, result, target='searched')
                web_group_meta = _agent_stream_note_web_search_group(state, round_idx, args, result, status='searched')
                yield _agent_stream_activity_delta_frame(state)
                yield sse('meta', {
                    'model': model,
                    'mode': 'responses_native_tools',
                    'route_mode': 'responses_native_agent',
                    'use_web_research': True,
                    'search_stage': 'searched',
                    'result_count': int(state.get('web_results') or 0),
                    'page_count': int(state.get('pages') or 0),
                    'queries_used': [str(q or '').strip() for q in (state.get('queries_used') or []) if str(q or '').strip()],
                    **web_group_meta,
                    **_agent_stream_progress_meta(state),
                    'search_results': [dict(it) for it in (state.get('searched_sources') or []) if isinstance(it, dict)] or [dict(it) for it in (result.get('results') or []) if isinstance(it, dict)],
                })
            elif name in {'search_knowledge_base', 'read_knowledge_base_document'} and isinstance(result, dict):
                kb_meta = _agent_stream_note_kb_result(state, result, args)
                yield sse('meta', {
                    'model': model,
                    'mode': 'responses_native_tools',
                    'route_mode': 'responses_native_agent',
                    'search_stage': 'kb_document_read' if name == 'read_knowledge_base_document' else 'kb_searched',
                    **kb_meta,
                })
            elif name in {'search_account_context', 'read_account_context'} and isinstance(result, dict):
                yield sse('meta', {
                    'model': model,
                    'mode': 'responses_native_tools',
                    'route_mode': 'responses_native_agent',
                    'search_stage': 'history_searched',
                    'history_result_count': int(result.get('result_count') or len(result.get('results') or [])) if isinstance(result, dict) else 0,
                })
            elif name in {'sandbox_publish_files'} and isinstance(result, dict):
                file_meta = _agent_stream_note_sandbox_publish_result(state, result, args)
                new_files = [dict(x) for x in (result.get('files') or []) if isinstance(x, dict)]
                if new_files:
                    yield sse('files', {'files': new_files, 'stage': name})
                yield sse('meta', {
                    'model': model,
                    'mode': 'responses_native_tools',
                    'route_mode': 'responses_native_agent',
                    'search_stage': 'sandbox_published' if name == 'sandbox_publish_files' else 'sandbox_published',
                    'status_text': '沙盒文件已发布' if new_files else '沙盒文件发布失败',
                    'file_count': len(new_files),
                    'published_paths': [str(x or '') for x in (result.get('published_paths') or [])],
                    **file_meta,
                })
            elif name == 'sandbox_create_office_file' and isinstance(result, dict) and isinstance(result.get('files'), list) and result.get('files'):
                new_files = [dict(x) for x in (result.get('files') or []) if isinstance(x, dict)]
                file_meta = _agent_stream_file_progress_meta(state)
                state['sandbox_published'] = True
                _agent_stream_merge_file_artifacts(state, new_files)
                if new_files:
                    yield sse('files', {'files': new_files, 'stage': 'sandbox_office_auto_published'})
                yield sse('meta', {
                    'model': model,
                    'mode': 'responses_native_tools',
                    'route_mode': 'responses_native_agent',
                    'search_stage': 'sandbox_office_auto_published',
                    'status_text': 'Office 文件已生成并发布',
                    'file_count': len(new_files),
                    'published_paths': [str(x or '') for x in (result.get('published_paths') or [])],
                    **file_meta,
                })
            elif name == 'image_search' and isinstance(result, dict):
                try:
                    state['image_results'] = int(state.get('image_results') or 0) + len(result.get('results') or [])
                except Exception:
                    pass
                q = str(result.get('query') or args.get('query') or '').strip()
                if q:
                    state.setdefault('image_queries_used', []).append(q)
                _agent_stream_push_sources(state, name, result)
                _agent_stream_note_image_search_event(state, args, result, status='searched' if bool(result.get('ok', True)) else 'error', call_id=call_id, round_idx=round_idx)
                yield _agent_stream_activity_delta_frame(state)
                image_payload = result.get('image_reply_payload') if isinstance(result.get('image_reply_payload'), dict) else None
                if image_payload:
                    yield sse('image_reply', image_payload)
                yield sse('meta', {
                    'model': model,
                    'mode': 'responses_native_tools',
                    'route_mode': 'responses_native_agent',
                    'use_visual': True,
                    'visual_intent': 'image_search',
                    'image_stage': 'searched',
                    'query': q,
                    'image_query': q,
                    'image_result_count': int(state.get('image_results') or 0),
                    'image_queries_used': [str(q or '').strip() for q in (state.get('image_queries_used') or []) if str(q or '').strip()],
                })
            elif name in {'fetch_url', 'fetch_urls'} and isinstance(result, dict):
                try:
                    if name == 'fetch_urls':
                        state['pages'] = int(state.get('pages') or 0) + len(result.get('results') or result.get('pages') or [])
                    else:
                        state['pages'] = int(state.get('pages') or 0) + 1
                except Exception:
                    pass
                _agent_stream_push_sources(state, name, result)
                _agent_stream_note_web_fetch_event(state, name, args, result, status='read' if bool(result.get('ok', True)) else 'error', call_id=call_id, round_idx=round_idx)
                yield _agent_stream_activity_delta_frame(state)
                visible_sources = _agent_stream_visible_sources(state, limit=8)
                yield sse('meta', {
                    'model': model,
                    'mode': 'responses_native_tools',
                    'route_mode': 'responses_native_agent',
                    'use_web_research': True,
                    'search_stage': 'pages_read',
                    'result_count': int(state.get('web_results') or 0),
                    'page_count': int(state.get('pages') or 0),
                    'source_count': len(visible_sources),
                    'sources': visible_sources,
                    'search_results': list(state.get('searched_sources') or []),
                    'searched_results': list(state.get('searched_sources') or []),
                    **_agent_stream_web_query_groups_meta(state),
                    **_agent_stream_progress_meta(state),
                })
            elif name == 'analyze_existing_image' and isinstance(result, dict):
                _agent_stream_note_existing_image_analysis_event(
                    state,
                    args,
                    result,
                    status='analyzed' if bool(result.get('ok')) else 'error',
                    call_id=call_id,
                    round_idx=round_idx,
                )
                yield _agent_stream_activity_delta_frame(state)
                yield sse('meta', {
                    'model': model,
                    'mode': 'responses_native_tools',
                    'route_mode': 'responses_native_agent',
                    'use_visual': True,
                    'visual_intent': 'existing_image_analysis',
                    'image_stage': 'analyzed',
                    'image_result_count': int(result.get('image_count') or 0),
                })
            elif name == 'get_weather' and isinstance(result, dict) and result.get('_kind') == 'weather':
                yield sse('weather', result)
            elif name == 'save_memory' and isinstance(result, dict) and bool(result.get('ok')) and not bool(result.get('skipped')):
                ev = result.get('event') if isinstance(result.get('event'), dict) else result
                yield sse('memory_event', ev)
            content = _responses_native_tool_output_text(name, result, compact, args=args, last_user_text=last_user_text)
            try:
                app_logger.info('[RESPONSES_NATIVE_TOOL_OUTPUT_READY] model=%s tool=%s call_id=%s chars=%s', model, name, call_id, len(str(content or '')))
            except Exception:
                pass
            output_limit = max(800, int(_orch_tool_budget(name, phase='responses_output')))
            outputs.append({
                'type': 'function_call_output',
                'call_id': call_id,
                'output': str(content or '')[:output_limit],
            })
        return outputs

    def _run_responses_native_tool_agent(ctx_for_agent: dict | None = None, runtime_state: dict | None = None):
        """Responses-native direct-first stream with function-call tool loop.

        This is the Responses counterpart of the existing Chat Completions
        direct-first Agent: no gpt-5.4-mini prefetch request, no legacy prepare
        before the first token.  The main model receives tool schemas directly,
        streams text/reasoning, asks for function calls when needed, receives
        function_call_output via Responses stateful continuation when supported,
        then continues streaming. Relays that reject previous_response_id fall
        back to the existing stateless replay in the same round.
        """
        runtime_state = runtime_state if isinstance(runtime_state, dict) else {}
        # Nested Responses-native event helpers can observe lifecycle payloads
        # before the per-round loop assigns round_idx. Keep a stable default so
        # those helpers never fail with NameError on early/terminal events.
        round_idx = 0
        state = {
            'tool_rounds': 0,
            'tool_counts': {},
            'sources': [],
            'source_seen': set(),
            'searched_sources': [],
            'searched_source_seen': set(),
            'web_results': 0,
            'pages': 0,
            'queries_used': [],
            'web_query_groups': [],
            'image_results': 0,
            'image_queries_used': [],
            'kb_results': 0,
            'kb_queries_used': [],
            'kb_doc_count': 0,
            'kb_chunk_count': 0,
            'kb_search_results': [],
            'kb_hit': False,
            'file_tool_used': False,
            'file_tool_rounds': 0,
            'file_progress_items': [],
            'file_context_injected': False,
        }
        state['_runtime_state'] = runtime_state
        last_user_text = _latest_user_text_from_messages(messages or [])
        if _agent_stream_note_current_user_image_input(state):
            yield _agent_stream_activity_delta_frame(state)
        gate_groups = []
        try:
            gate_groups = list(((ctx_for_agent or {}).get('responses_native_tool_gate') or {}).get('tool_groups') or runtime_state.get('tool_groups') or [])
        except Exception:
            gate_groups = []
        gate_groups = _responses_native_capability_groups(gate_groups) or ['all']
        image_generation_eager_first = bool((ctx_for_agent or {}).get('image_generation_eager_first') or runtime_state.get('image_generation_eager_first'))
        image_generation_attach_candidates = bool((ctx_for_agent or {}).get('image_generation_attach_candidates') or runtime_state.get('image_generation_attach_candidates'))
        image_task_type_for_round = str((ctx_for_agent or {}).get('image_task_type') or runtime_state.get('image_task_type') or '').strip().lower()
        native_gate = ((ctx_for_agent or {}).get('responses_native_tool_gate') or {}) if isinstance((ctx_for_agent or {}).get('responses_native_tool_gate'), dict) else {}
        file_task_soft_sandbox = bool((ctx_for_agent or {}).get('file_task_soft_sandbox') or runtime_state.get('file_task_soft_sandbox') or native_gate.get('file_task_soft_sandbox'))
        file_task_soft_reason = str((ctx_for_agent or {}).get('file_task_soft_reason') or runtime_state.get('file_task_soft_reason') or native_gate.get('file_task_soft_reason') or '').strip()
        state['file_task_soft_sandbox'] = bool(file_task_soft_sandbox)
        state['file_task_soft_reason'] = file_task_soft_reason
        state['image_generation_eager_first'] = bool(image_generation_eager_first)
        state['image_generation_attach_candidates'] = bool(image_generation_attach_candidates)
        state['image_task_type'] = image_task_type_for_round
        state['active_tool_groups'] = list(gate_groups or [])
        base_agent_messages = _agent_stream_messages_with_knowledge_context(messages or [])
        cache_file_context_needed = _agent_stream_prompt_cache_file_context_needed(base_agent_messages)
        if _agent_stream_file_context_needed_for_groups(gate_groups) or cache_file_context_needed:
            if cache_file_context_needed and not _agent_stream_file_context_needed_for_groups(gate_groups):
                try:
                    app_logger.info('[RESPONSES_PROMPT_CACHE_FILE_CONTEXT_INJECT] model=%s groups=%s', model, json.dumps(gate_groups, ensure_ascii=False))
                except Exception:
                    pass
            base_agent_messages = _agent_stream_messages_with_file_context(base_agent_messages, state=state)
        agent_messages = _agent_stream_messages_with_visual_context(base_agent_messages)
        agent_messages = _orch_append_recent_file_edit_audit_context(agent_messages)
        if state.get('file_progress_items'):
            yield sse('meta', {
                'model': model,
                'mode': 'responses_native_tools',
                'route_mode': 'responses_native_agent',
                'search_stage': 'file_context',
                'status_text': '已准备沙盒文件清单',
                **_agent_stream_file_progress_meta(state),
            })
        agent_messages = _inject_main_chat_runtime_model_context(agent_messages, _main_chat_runtime_model_for_context())
        agent_messages.append(_agent_streaming_runtime_prompt({
            'agent_stream_direct_first': True,
            'responses_native_tools': True,
            'responses_image_generation_eager_first': bool(image_generation_eager_first),
            'responses_image_generation_attach_candidates': bool(image_generation_attach_candidates),
            'responses_image_task_type': image_task_type_for_round,
            'responses_file_task_soft_sandbox': bool(file_task_soft_sandbox),
            'responses_file_task_soft_reason': file_task_soft_reason,
        }))
        agent_messages = _agent_stream_sanitize_tool_loop_messages(agent_messages)
        agent_messages = _orch_dedupe_model_messages(agent_messages)
        compressor = globals().get('_compress_messages_for_responses_endpoint')
        if callable(compressor):
            agent_messages = compressor(agent_messages, phase='responses_native_initial')
        tool_specs = _responses_native_tool_specs(
            compact=True,
            allowed_tool_groups=gate_groups,
            image_task_type=image_task_type_for_round,
            eager_source_images=bool(image_generation_attach_candidates or (image_generation_eager_first and image_task_type_for_round in {'reference_generate', 'image_edit', 'reference_edit', 'variation'})),
        )
        lead_buffer_chars = _agent_stream_cfg_int('AGENT_STREAM_LEAD_BUFFER_CHARS', 180, min_value=0, max_value=1200)
        resolver = globals().get('_resolve_openai_client_identity')
        if callable(resolver):
            api_key, base_url = resolver(client_override or client_gpt)
        else:
            api_key = str(getattr(client_override, 'api_key', '') or globals().get('GPT_API_KEY') or '').strip()
            base_url = str(getattr(client_override, 'base_url', '') or globals().get('GPT_BASE_URL') or '').strip()
        endpoint = _responses_endpoint_from_base_url(base_url)
        if not endpoint:
            raise RuntimeError('Responses API endpoint missing')
        http_client = globals().get('HTTPX_GPT')
        own_client = None
        if http_client is None:
            own_client = httpx.Client(verify=globals().get('tls_verify', True), timeout=900.0, follow_redirects=True)
            http_client = own_client
        headers = {'Accept': 'text/event-stream', 'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        responses_websocket_transport = None
        websocket_capability = _RESPONSES_TRANSPORT_CAPABILITIES.get(endpoint, 'websocket')
        if _responses_websocket_enabled() and websocket_capability is not False:
            try:
                responses_websocket_transport = ResponsesWebSocketTransport(
                    endpoint=endpoint,
                    headers=headers,
                    logger=app_logger,
                    timeout=900.0,
                )
            except Exception as websocket_init_err:
                try:
                    app_logger.warning(
                        '[RESPONSES_WEBSOCKET_INIT_FAILED] model=%s err=%s:%s',
                        model,
                        type(websocket_init_err).__name__,
                        websocket_init_err,
                    )
                except Exception:
                    pass
        instructions = _responses_instructions_from_chat_messages(agent_messages or [], max_chars=_responses_native_instruction_max_chars())
        conversation_input_items = _responses_input_from_chat_messages(agent_messages or [])
        responses_trace_context_signature = _RESPONSES_CONVERSATION_TRACES.context_signature(instructions, tool_specs)
        if not temporary_chat and str(client_session_id or '').strip():
            restored_trace_items = _RESPONSES_CONVERSATION_TRACES.restore(
                session_id=client_session_id,
                endpoint=endpoint,
                model=model,
                context_signature=responses_trace_context_signature,
                current_items=conversation_input_items,
            )
            if restored_trace_items:
                conversation_input_items = restored_trace_items
                try:
                    app_logger.info(
                        '[RESPONSES_CONVERSATION_TRACE_RESTORED] model=%s session=%s items=%s',
                        model,
                        str(client_session_id or '')[-32:],
                        len(restored_trace_items),
                    )
                except Exception:
                    pass
        input_compressor = globals().get('_compress_responses_input_items_for_endpoint')
        if callable(input_compressor):
            conversation_input_items = input_compressor(conversation_input_items, phase='responses_native_initial')
        try:
            debug_kinds: list[dict] = []
            for _idx, _m in enumerate(agent_messages or []):
                if not isinstance(_m, dict):
                    continue
                _kind = str(_m.get('_kind') or '').strip()
                _txt = _responses_instruction_text_from_content(_m.get('content'))
                _is_target = _kind in {'file_memory', 'file_recall', 'file_edit_audit', 'agent_stream_file_loop_hint', 'agent_stream_runtime', 'runtime_time', 'runtime_location_visibility', 'runtime_model'}
                if _is_target or len(str(_txt or '')) > 4000:
                    debug_kinds.append({
                        'idx': _idx,
                        'role': str(_m.get('role') or ''),
                        'kind': _kind,
                        'chars': len(str(_txt or '')),
                        'starts_runtime': str(_txt or '').startswith('Runtime context:\n'),
                        'has_file_marker': ('文本附件正文' in str(_txt or '') or 'sandbox_import_files' in str(_txt or '')),
                        'dynamic': bool(_responses_is_dynamic_context_message(_m)),
                    })
            if debug_kinds:
                app_logger.info('[RESPONSES_NATIVE_CONTEXT_KIND_AUDIT] model=%s items=%s', model, json.dumps(debug_kinds, ensure_ascii=False))
        except Exception:
            pass
        pending_input = list(conversation_input_items or [])
        pending_continuation_input: list = []
        previous_response_id = ''
        stateful_continuation_supported: bool | None = (
            _RESPONSES_TRANSPORT_CAPABILITIES.get(endpoint, 'http_stateful')
            if responses_websocket_transport is None
            else None
        )
        eager_source_image_count = 0
        if bool(image_generation_attach_candidates or (image_generation_eager_first and image_task_type_for_round in {'reference_generate', 'image_edit', 'reference_edit', 'variation'})):
            candidate_task_type = image_task_type_for_round or 'reference_generate'
            pending_input, eager_source_image_count = _agent_stream_append_eager_image_generation_input(pending_input, task_type=candidate_task_type)
            try:
                runtime_state['responses_image_generation_eager_input_count'] = int(eager_source_image_count or 0)
                runtime_state['responses_image_generation_first_round_candidates_attached'] = bool(eager_source_image_count)
            except Exception:
                pass

        native_image_state = {
            'seen': False,
            'status_emitted': False,
            'image_reply_emitted': False,
            'seen_item_keys': set(),
            'partial_items': [],
            'result_items': [],
            'ext': 'png',
        }
        native_web_state = {
            'seen': False,
            'observed': False,
            'confirmed': False,
            'status_emitted': False,
            'counted': False,
            'meta_signature': '',
            'calls': {},
            'call_order': [],
        }
        native_code_state = {
            'seen': False,
            'status_emitted': False,
            'counted': False,
            'meta_signature': '',
            'calls': {},
            'call_order': [],
            'citations': [],
            'citation_seen': set(),
            'saved_file_seen': set(),
            'saved_files': [],
            'warnings': [],
        }

        native_image_context = ResponsesNativeImageContext(
            model=model,
            endpoint=endpoint,
            api_key=api_key,
            http_client=http_client,
            headers=headers,
            state=state,
            runtime_state=runtime_state,
            native_image_state=native_image_state,
            image_generation_group_active=_responses_native_image_generation_group_active,
            capability_groups=_responses_native_capability_groups,
            sse=sse,
            runtime_model_meta=_current_runtime_model_meta,
            last_user_text=last_user_text,
            image_artifacts_to_reply=_image_generation_artifacts_to_image_reply_payload,
            logger=app_logger,
        )

        def _responses_native_image_ext_from_payload(payload: dict | None = None, fallback: str = '') -> str:
            return native_image_context._responses_native_image_ext_from_payload(payload, fallback)

        def _responses_native_strip_image_b64(value: str = '') -> tuple[str, str]:
            return native_image_context._responses_native_strip_image_b64(value)

        def _responses_native_add_image_item(*, b64: str = '', url: str = '', source: str = 'result', ext: str = '') -> int:
            return native_image_context._responses_native_add_image_item(b64=b64, url=url, source=source, ext=ext)

        def _responses_native_collect_image_payload(payload, event_type: str = '') -> dict:
            return native_image_context._responses_native_collect_image_payload(payload, event_type)

        def _responses_native_image_event_is_response_terminal(event_type: str = '') -> bool:
            return native_image_context._responses_native_image_event_is_response_terminal(event_type)

        def _responses_native_response_retrieve_url(response_id: str = '', *, include_image_result: bool = False) -> str:
            return native_image_context._responses_native_response_retrieve_url(response_id, include_image_result=include_image_result)

        def _responses_native_try_retrieve_final_image(response_id: str = '') -> dict:
            return native_image_context._responses_native_try_retrieve_final_image(response_id)

        native_code_context = ResponsesNativeCodeInterpreterContext(
            model=model,
            endpoint=endpoint,
            api_key=api_key,
            http_client=http_client,
            native_code_state=native_code_state,
            state=state,
            get_round_idx=lambda: round_idx,
            sse=sse,
            append_file_progress=_agent_stream_append_file_progress,
            merge_file_artifacts=_agent_stream_merge_file_artifacts,
            file_progress_meta=_agent_stream_file_progress_meta,
            runtime_model_meta=_current_runtime_model_meta,
            guess_content_type=_guess_content_type_for_file,
            logger=app_logger,
        )

        def _responses_container_file_content_endpoint(container_id: str = '', file_id: str = '') -> str:
            return native_code_context._responses_container_file_content_endpoint(container_id, file_id)

        def _responses_native_note_code_seen(info: dict | None = None) -> None:
            return native_code_context._responses_native_note_code_seen(info)

        def _responses_native_code_status(event_type: str = '', payload: dict | None = None) -> str:
            return native_code_context._responses_native_code_status(event_type, payload)

        def _responses_native_record_code_call(node, event_type: str = '', info: dict | None = None) -> int:
            return native_code_context._responses_native_record_code_call(node, event_type, info)

        def _responses_native_save_container_file(citation: dict | None = None) -> list[dict]:
            return native_code_context._responses_native_save_container_file(citation)

        def _responses_native_collect_code_interpreter_payload(payload, event_type: str = '') -> dict:
            return native_code_context._responses_native_collect_code_interpreter_payload(payload, event_type)

        def _responses_native_code_interpreter_meta_frame(stage: str = 'code_interpreter') -> str | None:
            return native_code_context._responses_native_code_interpreter_meta_frame(stage)

        native_web_context = ResponsesNativeWebContext(
            model=model,
            state=state,
            native_web_state=native_web_state,
            get_round_idx=lambda: round_idx,
            sse=sse,
            search_source_item_limit=_agent_stream_search_source_item_limit,
            push_sources=_agent_stream_push_sources,
            append_progress_event=_agent_stream_append_progress_event,
            progress_meta=_agent_stream_progress_meta,
            is_public_visible_source_url=_is_public_visible_source_url,
            normalize_visible_source_url=_normalize_visible_source_url,
            host_of=_host_of,
            planner_safe_text=_planner_safe_text,
            sse_event_keys_for_log=_responses_sse_event_keys_for_log,
            logger=app_logger,
        )

        def _responses_native_web_add_query(query: str = '') -> int:
            return native_web_context._responses_native_web_add_query(query)

        def _responses_native_web_add_source(url: str = '', title: str = '', snippet: str = '', *, target: str = 'searched') -> int:
            return native_web_context._responses_native_web_add_source(url, title, snippet, target=target)

        def _responses_native_web_compact_text(value, limit: int = 220) -> str:
            return native_web_context._responses_native_web_compact_text(value, limit)

        def _responses_native_web_call_status(event_type: str = '', payload: dict | None = None) -> str:
            return native_web_context._responses_native_web_call_status(event_type, payload)

        def _responses_native_web_public_status(status: str = '') -> str:
            return native_web_context._responses_native_web_public_status(status)

        def _responses_native_web_extract_queries(node, out: list[str] | None = None, depth: int = 0) -> list[str]:
            return native_web_context._responses_native_web_extract_queries(node, out, depth)

        def _responses_native_web_action_type(node, depth: int = 0) -> str:
            return native_web_context._responses_native_web_action_type(node, depth)

        def _responses_native_web_source_like_count(node, depth: int = 0) -> int:
            return native_web_context._responses_native_web_source_like_count(node, depth)

        def _responses_native_web_call_public_rows() -> list[dict]:
            return native_web_context._responses_native_web_call_public_rows()

        def _responses_native_web_sync_progress_events(native_web_calls: list[dict] | None = None) -> None:
            return native_web_context._responses_native_web_sync_progress_events(native_web_calls)

        def _responses_native_web_record_call_event(payload, event_type: str = '', info: dict | None = None) -> int:
            return native_web_context._responses_native_web_record_call_event(payload, event_type, info)

        def _responses_native_web_note_seen(info: dict | None = None) -> None:
            return native_web_context._responses_native_web_note_seen(info)

        def _responses_native_web_mark_confirmed(info: dict | None = None) -> None:
            return native_web_context._responses_native_web_mark_confirmed(info)

        def _responses_native_collect_web_payload(payload, event_type: str = '') -> dict:
            return native_web_context._responses_native_collect_web_payload(payload, event_type)

        def _responses_native_web_meta_frame(stage: str = 'native_web_search') -> str | None:
            return native_web_context._responses_native_web_meta_frame(stage)

        def _responses_native_image_reply_frames(force: bool = False) -> list[str]:
            return native_image_context._responses_native_image_reply_frames(force=force)

        try:
            for round_idx in agent_tool_round_indices():
                _raise_if_async_job_stopped()
                calls_by_key: dict = {}
                reasoning_items_by_key: dict = {}
                response_output_items_by_key: dict = {}
                round_state = {'response_id': '', 'deltas_seen': False, 'tool_call_seen': False}
                round_tool_specs = _responses_native_filter_tools_for_turn(tool_specs, state)
                round_replay_input = _responses_native_strip_image_generation_input_items(pending_input, state)
                continuation_plan = _responses_native_round_input_plan(
                    round_replay_input,
                    pending_continuation_input,
                    previous_response_id=previous_response_id,
                    stateful_supported=stateful_continuation_supported,
                )
                round_pending_input = _responses_native_strip_image_generation_input_items(
                    continuation_plan.get('input') or [],
                    state,
                )
                body = {
                    'model': str(model or '').strip(),
                    'instructions': instructions,
                    'stream': True,
                    'tools': round_tool_specs,
                    'tool_choice': 'auto',
                    'parallel_tool_calls': False,
                    'input': round_pending_input,
                    'include': ['reasoning.encrypted_content'],
                }
                if bool(continuation_plan.get('use_stateful')):
                    body['previous_response_id'] = str(continuation_plan.get('previous_response_id') or '')
                body['input'] = _agent_stream_sanitize_responses_input_items_for_api(body.get('input') if isinstance(body.get('input'), list) else [])
                force_native_image_generation = False
                try:
                    current_groups = _responses_native_capability_groups(state.get('active_tool_groups') or [])
                    has_native_image_tool = any(str((tool or {}).get('type') or '').strip().lower() == 'image_generation' for tool in (round_tool_specs or []) if isinstance(tool, dict))
                    force_native_image_generation = bool(
                        has_native_image_tool
                        and (
                            (bool(state.get('image_generation_eager_first')) and round_idx == 1)
                            or 'image_generate' in {str(x or '').strip().lower() for x in (current_groups or [])}
                        )
                    )
                    if force_native_image_generation:
                        body['tool_choice'] = {'type': 'image_generation'}
                except Exception:
                    force_native_image_generation = False
                    body['tool_choice'] = 'auto'
                try:
                    body.update(_responses_extra_body_with_reasoning_summary({}, model=body.get('model') or model) or {})
                except Exception:
                    pass
                native_web_request_params = {}
                try:
                    native_web_request_params = _responses_native_apply_web_request_params(body, round_tool_specs)
                except Exception:
                    native_web_request_params = {}
                try:
                    cache_helper = globals().get('_apply_prompt_cache_to_request_payload')
                    if callable(cache_helper):
                        body = cache_helper(
                            body,
                            endpoint_mode='responses',
                            model=str(model or ''),
                            base_url=base_url,
                            phase='responses_native_round_%s' % str(round_idx or 0),
                            placement='body',
                            cache_namespace=client_session_id,
                        )
                except Exception:
                    pass
                try:
                    try:
                        native_payload_chars = len(json.dumps(body, ensure_ascii=False, default=str))
                    except Exception:
                        native_payload_chars = 0
                    app_logger.info(
                        '[RESPONSES_NATIVE_TOOL_LOOP_START] model=%s round=%s endpoint=%s prev=%s input_items=%s tools=%s payload_chars=%s instruction_chars=%s body_keys=%s reasoning_keys=%s',
                        model,
                        round_idx,
                        endpoint,
                        bool(body.get('previous_response_id')),
                        len(round_pending_input or []),
                        len(round_tool_specs or []),
                        native_payload_chars,
                        len(str(instructions or '')),
                        sorted(str(k) for k in body.keys()),
                        sorted(str(k) for k in ((body.get('reasoning') or {}).keys())) if isinstance(body.get('reasoning'), dict) else [],
                    )
                    if native_web_request_params:
                        app_logger.info('[RESPONSES_NATIVE_WEB_PARAMS_APPLIED] model=%s round=%s params=%s', model, round_idx, json.dumps(native_web_request_params, ensure_ascii=False, default=str))
                    if force_native_image_generation:
                        app_logger.info('[RESPONSES_NATIVE_IMAGE_GENERATION_FORCED] model=%s round=%s task_type=%s tools=%s', model, round_idx, str(state.get('image_task_type') or ''), len(round_tool_specs or []))
                except Exception:
                    pass
                round_sse_buffer = ResponsesSSEEventBuffer(logger=app_logger, lane='responses_native_round')
                _sse_probe_seen_event_types: set[str] = set()
                round_reasoning_accum = ''
                lead_buffer = ''
                lead_flushed = False
                last_ping = time.time()
                function_args_progress = {'last_status_at': 0.0, 'emitted': False}

                pending_has_input_image = False
                try:
                    for _item in (round_pending_input or []):
                        if not isinstance(_item, dict):
                            continue
                        for _c in (_item.get('content') or []):
                            if isinstance(_c, dict) and str(_c.get('type') or '').strip().lower() == 'input_image':
                                pending_has_input_image = True
                                break
                        if pending_has_input_image:
                            break
                except Exception:
                    pending_has_input_image = False
                if pending_has_input_image and bool(runtime_state.get('responses_image_input_attached')):
                    visual_round_instruction = (
                        '这是沙盒准备并附加的 input_image 视觉轮。'
                        '回答前必须直接观察这些 input_image。'
                        '如果这些图像来自会话图片，请围绕最新用户问题回答，不要声称无法读取当前图片；'
                        '如果这些图像来自文件页面审阅，请明确说明已检查的页面范围或页面标签，'
                        '并用可见文字、图表、版式、公式或页面证据支撑结论。'
                    )
                    round_pending_input = list(round_pending_input or []) + [{
                        'role': 'user',
                        'content': [{
                            'type': 'input_text',
                            'text': visual_round_instruction,
                        }],
                    }]
                    body['input'] = _agent_stream_sanitize_responses_input_items_for_api(round_pending_input)
                    # Some OpenAI-compatible /responses relays fail when a follow-up
                    # request combines selected analyze_existing_image input_image
                    # items with function tools.  Only that deferred selected-image
                    # round is forced to a pure vision answer.  Current-user images
                    # attached at the start stay tool-capable so the main model can
                    # choose image generation/editing instead of being trapped in
                    # analysis-only mode.
                    body.pop('tools', None)
                    body.pop('tool_choice', None)
                    body.pop('include', None)
                    try:
                        app_logger.info('[RESPONSES_NATIVE_IMAGE_INPUT_FINAL_ROUND_NO_TOOLS] model=%s round=%s input_items=%s', model, round_idx, len(pending_input or []))
                    except Exception:
                        pass

                historical_generated_artifacts = _collect_generated_file_artifacts_from_messages(agent_messages or [])

                def _emit_delta(text: str):
                    safe = _strip_leaked_think_tags(str(text or ''))
                    current_files = state.get('file_artifacts') or []
                    safe = _strip_redundant_generated_file_lines(safe, current_files or historical_generated_artifacts)
                    if not safe:
                        return None
                    runtime_state['visible_delta'] = True
                    return sse('delta', {'text': safe})

                def _handle_payload(payload, event_name: str = ''):
                    nonlocal lead_buffer, lead_flushed, round_reasoning_accum
                    frames = []
                    if not isinstance(payload, dict):
                        return frames
                    event_type = str(event_name or payload.get('type') or payload.get('event') or '').strip()
                    _remember_runtime_model(_extract_runtime_model_from_obj(payload))
                    _responses_log_sse_event_probe(event_type, payload, seen=_sse_probe_seen_event_types)
                    if payload.get('id') and str(event_type).startswith('response.'):
                        round_state['response_id'] = str(payload.get('id') or '')
                    response_obj = payload.get('response') if isinstance(payload.get('response'), dict) else None
                    if response_obj and response_obj.get('id'):
                        round_state['response_id'] = str(response_obj.get('id') or '')
                    try:
                        usage_payload = _extract_usage_from_stream_chunk(payload)
                        if usage_payload:
                            usage_key = 'responses_native|%s|%s|%s' % (str(round_idx or 0), str(model or ''), str(round_state.get('usage_key') or ''))
                            if not str(round_state.get('usage_key') or ''):
                                round_state['usage_key'] = str(time.time_ns())
                                usage_key = 'responses_native|%s|%s|%s' % (str(round_idx or 0), str(model or ''), str(round_state.get('usage_key') or ''))
                            _record_generation_usage(usage_payload, phase='responses_native_round_%s' % str(round_idx or 0), model_name=str(model or ''), endpoint='responses', call_key=usage_key)
                            usage_frame = _usage_sse_frame_if_new()
                            if usage_frame:
                                frames.append(usage_frame)
                    except Exception:
                        pass
                    is_err, err_text = _responses_sse_payload_is_error(payload, event_type)
                    if is_err:
                        if bool(native_image_state.get('seen')) or 'image_generation' in str(err_text or '').lower():
                            runtime_state['native_image_seen'] = True
                            runtime_state['native_image_error'] = str(err_text or '')[:4000]
                        raise RuntimeError(f'Responses API stream error: {err_text[:4000]}')
                    image_info = _responses_native_collect_image_payload(payload, event_type)
                    if bool(image_info.get('seen')) and not bool(native_image_state.get('status_emitted')):
                        native_image_state['status_emitted'] = True
                        frames.append(sse('status', {'text': f'{label} 正在生成图片…'}))
                    event_type_low = str(event_type or '').strip().lower()
                    image_response_terminal = _responses_native_image_event_is_response_terminal(event_type_low)
                    if bool(native_image_state.get('seen')) and image_response_terminal and not (native_image_state.get('result_items') or []):
                        _responses_native_try_retrieve_final_image(str(round_state.get('response_id') or ''))
                    if bool(native_image_state.get('seen')) and image_response_terminal:
                        frames.extend(_responses_native_image_reply_frames(force=True))
                    code_info = _responses_native_collect_code_interpreter_payload(payload, event_type)
                    code_has_visible_payload = bool(code_info.get('seen')) or bool(code_info.get('added_calls')) or bool(code_info.get('added_citations')) or bool(code_info.get('saved_files'))
                    if bool(code_info.get('seen')) and not bool(native_code_state.get('status_emitted')):
                        native_code_state['status_emitted'] = True
                        frames.append(sse('status', {'text': f'{label} 正在运行 Python 沙盒…'}))
                    if code_has_visible_payload or (bool(native_code_state.get('seen')) and str(event_type or '').strip().lower() in {'response.completed', 'completed'}):
                        code_meta = _responses_native_code_interpreter_meta_frame('code_interpreter_completed' if str(event_type or '').strip().lower() in {'response.completed', 'completed'} else 'code_interpreter')
                        if code_meta:
                            frames.append(code_meta)
                        saved_files = [dict(x) for x in (code_info.get('saved_files') or []) if isinstance(x, dict)]
                        if saved_files:
                            frames.append(sse('files', {'files': saved_files, 'stage': 'code_interpreter_files'}))
                    web_info = _responses_native_collect_web_payload(payload, event_type)
                    web_has_visible_payload = bool(web_info.get('added_queries')) or bool(web_info.get('added_sources')) or bool(web_info.get('added_web_calls'))
                    if web_has_visible_payload and not bool(native_web_state.get('status_emitted')):
                        native_web_state['status_emitted'] = True
                        frames.append(sse('status', {'text': f'{label} 正在联网搜索…'}))
                    if web_has_visible_payload or (bool(native_web_state.get('confirmed')) and str(event_type or '').strip().lower() in {'response.completed', 'completed'}):
                        web_meta = _responses_native_web_meta_frame('native_web_completed' if str(event_type or '').strip().lower() in {'response.completed', 'completed'} else 'native_web_search')
                        if web_meta:
                            frames.append(web_meta)
                            # The meta frame carries the full normalized snapshot, while
                            # the activity frame carries just the latest changed row.
                            # Emitting both keeps native web query/source updates visible
                            # as soon as they are real, without inventing placeholder
                            # queries or changing the GPT-style expanded structure.
                            activity_frame = _agent_stream_activity_delta_frame(state)
                            if activity_frame:
                                frames.append(activity_frame)
                    reasoning_delta = _responses_extract_reasoning_delta_from_sse_payload(payload, event_type)
                    if reasoning_delta:
                        reasoning_piece = _responses_reasoning_suffix_delta(reasoning_delta, round_reasoning_accum)
                        if reasoning_piece:
                            round_reasoning_accum += reasoning_piece
                            reasoning_event_key = _responses_reasoning_event_key_from_sse_payload(payload, event_type)
                            frames.extend(_reasoning_sse_frames(reasoning_piece, 'responses_reasoning', reasoning_event_key))
                    reasoning_snapshot = _responses_extract_reasoning_snapshot_from_sse_payload(payload, event_type)
                    if reasoning_snapshot:
                        reasoning_piece = _responses_reasoning_suffix_delta(reasoning_snapshot, round_reasoning_accum, snapshot_mode=True)
                        if reasoning_piece:
                            round_reasoning_accum += reasoning_piece
                            reasoning_event_key = _responses_reasoning_event_key_from_sse_payload(payload, event_type)
                            frames.extend(_reasoning_sse_frames(reasoning_piece, 'responses_reasoning_snapshot', reasoning_event_key))
                    # Function-call item events.
                    item = payload.get('item') if isinstance(payload.get('item'), dict) else (payload.get('output_item') if isinstance(payload.get('output_item'), dict) else None)
                    if item:
                        _responses_native_merge_reasoning_item(reasoning_items_by_key, item)
                        _responses_native_merge_response_output_item(response_output_items_by_key, item)
                        before = len(calls_by_key)
                        _responses_native_merge_call(calls_by_key, payload, item)
                        if len(calls_by_key) != before or str((item or {}).get('type') or '').lower() == 'function_call':
                            round_state['tool_call_seen'] = True
                    if response_obj and isinstance(response_obj.get('output'), list):
                        for response_output_item in response_obj.get('output') or []:
                            if isinstance(response_output_item, dict):
                                _responses_native_merge_reasoning_item(reasoning_items_by_key, response_output_item)
                                _responses_native_merge_response_output_item(response_output_items_by_key, response_output_item)
                    if 'function_call_arguments' in event_type or 'arguments.delta' in event_type or event_type.endswith('.arguments.delta'):
                        _responses_native_merge_args_delta(calls_by_key, payload, event_type)
                        round_state['tool_call_seen'] = True
                        try:
                            sandbox_args_frame = _agent_stream_sandbox_arguments_status_frame(state, calls_by_key)
                            if sandbox_args_frame:
                                frames.append(sandbox_args_frame)
                            else:
                                now_status = time.time()
                                should_emit_args_status = (
                                    not bool(function_args_progress.get('emitted'))
                                    or now_status - float(function_args_progress.get('last_status_at') or 0.0) >= 6.0
                                )
                                if should_emit_args_status:
                                    function_args_progress['emitted'] = True
                                    function_args_progress['last_status_at'] = now_status
                                    frames.append(sse('status', {'text': f'{label} 正在生成工具调用参数…'}))
                        except Exception:
                            pass
                        preview_frame = _agent_stream_file_process_preview_frame(state, calls_by_key, preferred_mode='generate_new')
                        if preview_frame:
                            frames.append(preview_frame)
                    # Some relays emit a complete function_call object directly.
                    if str(payload.get('type') or '').strip().lower() in {'function_call', 'tool_call'}:
                        _responses_native_merge_call(calls_by_key, payload, payload)
                        round_state['tool_call_seen'] = True
                    delta = _responses_extract_delta_from_sse_payload(payload, event_type)
                    if delta and bool(native_image_state.get('seen')):
                        compact_delta = re.sub(r'\s+', '', str(delta or '')).strip().lower()
                        if compact_delta in {'完成', '已完成', 'done', 'ok', '好的', '图片已生成', '生成完成'} or len(compact_delta) <= 8:
                            delta = ''
                    if delta and not round_state.get('tool_call_seen'):
                        round_state['deltas_seen'] = True
                        if not lead_flushed and lead_buffer_chars > 0:
                            lead_buffer += delta
                            if len(lead_buffer) < lead_buffer_chars:
                                return frames
                            lead_flushed = True
                            frame = _emit_delta(lead_buffer)
                            lead_buffer = ''
                            if frame:
                                frames.append(frame)
                            return frames
                        if not lead_flushed:
                            lead_flushed = True
                        frame = _emit_delta(delta)
                        if frame:
                            frames.append(frame)
                    return frames

                def _flush_event():
                    event_name, payload = round_sse_buffer.pop_json()
                    if not isinstance(payload, dict):
                        return []
                    return _handle_payload(payload, event_name)

                native_open_attempts = 1 + _stream_cfg_int('GPT_STREAM_MAX_RETRIES', 2, min_value=0, max_value=5)
                native_open_attempt = 0
                while True:
                    native_open_attempt += 1
                    # 上一次连接可能停在半个 data 帧中；重连前必须清空，禁止跨连接拼帧。
                    round_sse_buffer.reset()
                    if responses_websocket_transport is not None:
                        try:
                            app_logger.info(
                                '[RESPONSES_WEBSOCKET_ROUND_START] model=%s round=%s prev=%s input_items=%s',
                                model,
                                round_idx,
                                bool(body.get('previous_response_id')),
                                len(body.get('input') or []),
                            )
                            for websocket_payload in responses_websocket_transport.stream_response(body):
                                _raise_if_async_job_stopped()
                                websocket_event = str((websocket_payload or {}).get('type') or '').strip()
                                for frame in _handle_payload(websocket_payload, websocket_event):
                                    yield frame
                            _RESPONSES_TRANSPORT_CAPABILITIES.set(endpoint, 'websocket', True)
                            if body.get('previous_response_id'):
                                stateful_continuation_supported = True
                            break
                        except Exception as websocket_err:
                            can_fallback_websocket = bool(
                                not bool(runtime_state.get('visible_delta'))
                                and not bool(round_state.get('deltas_seen'))
                                and not bool(calls_by_key)
                            )
                            try:
                                responses_websocket_transport.close()
                            except Exception:
                                pass
                            responses_websocket_transport = None
                            if _responses_websocket_error_is_unsupported(websocket_err):
                                _RESPONSES_TRANSPORT_CAPABILITIES.set(endpoint, 'websocket', False)
                            if not can_fallback_websocket:
                                raise
                            if body.get('previous_response_id'):
                                body.pop('previous_response_id', None)
                                stateful_continuation_supported = False
                                body['input'] = _agent_stream_sanitize_responses_input_items_for_api(
                                    list(continuation_plan.get('replay_input') or round_replay_input or [])
                                )
                                round_pending_input = list(continuation_plan.get('replay_input') or round_replay_input or [])
                            native_open_attempt = max(0, native_open_attempt - 1)
                            try:
                                app_logger.warning(
                                    '[RESPONSES_WEBSOCKET_FALLBACK_HTTP] model=%s round=%s err=%s:%s',
                                    model,
                                    round_idx,
                                    type(websocket_err).__name__,
                                    websocket_err,
                                )
                            except Exception:
                                pass
                            continue
                    try:
                        with http_client.stream('POST', endpoint, headers=headers, json=body, timeout=None) as resp:
                            if int(getattr(resp, 'status_code', 0) or 0) >= 400:
                                try:
                                    err_text = resp.read().decode('utf-8', errors='replace')
                                except Exception:
                                    err_text = str(getattr(resp, 'text', '') or '')
                                if (
                                    'prompt_cache_options' in body
                                    and _prompt_cache_rejects_modern_protocol(err_text)
                                ):
                                    body = _prompt_cache_without_modern_protocol(body, placement='body')
                                    round_sse_buffer.reset()
                                    native_open_attempt = max(0, native_open_attempt - 1)
                                    try:
                                        app_logger.warning(
                                            '[RESPONSES_PROMPT_CACHE_PROTOCOL_RETRY] model=%s round=%s status=%s preserve_previous_response_id=%s',
                                            model,
                                            round_idx,
                                            int(getattr(resp, 'status_code', 0) or 0),
                                            bool(body.get('previous_response_id')),
                                        )
                                    except Exception:
                                        pass
                                    continue
                                if (
                                    body.get('previous_response_id')
                                    and 'prompt_cache_retention' in body
                                    and _responses_native_rejects_optional_parameter(
                                        err_text,
                                        'prompt_cache_retention',
                                    )
                                ):
                                    body.pop('prompt_cache_retention', None)
                                    round_sse_buffer.reset()
                                    native_open_attempt = max(0, native_open_attempt - 1)
                                    try:
                                        app_logger.warning(
                                            '[RESPONSES_OPTIONAL_PARAMETER_RETRY] model=%s round=%s status=%s parameter=prompt_cache_retention preserve_previous_response_id=true',
                                            model,
                                            round_idx,
                                            int(getattr(resp, 'status_code', 0) or 0),
                                        )
                                    except Exception:
                                        pass
                                    continue
                                if (
                                    'reasoning.encrypted_content' in (body.get('include') or [])
                                    and _responses_native_rejects_optional_parameter(
                                        err_text,
                                        'reasoning.encrypted_content',
                                    )
                                ):
                                    body['include'] = [
                                        value for value in (body.get('include') or [])
                                        if str(value or '').strip() != 'reasoning.encrypted_content'
                                    ]
                                    if not body.get('include'):
                                        body.pop('include', None)
                                    round_sse_buffer.reset()
                                    native_open_attempt = max(0, native_open_attempt - 1)
                                    try:
                                        app_logger.warning(
                                            '[RESPONSES_OPTIONAL_PARAMETER_RETRY] model=%s round=%s status=%s parameter=reasoning.encrypted_content preserve_previous_response_id=%s',
                                            model,
                                            round_idx,
                                            int(getattr(resp, 'status_code', 0) or 0),
                                            bool(body.get('previous_response_id')),
                                        )
                                    except Exception:
                                        pass
                                    continue
                                if body.get('previous_response_id'):
                                    rejected_response_id = str(body.pop('previous_response_id', '') or '')
                                    stateful_continuation_supported = False
                                    if 'previous_response_id' in str(err_text or '').lower():
                                        _RESPONSES_TRANSPORT_CAPABILITIES.set(endpoint, 'http_stateful', False)
                                    body['input'] = _agent_stream_sanitize_responses_input_items_for_api(
                                        list(continuation_plan.get('replay_input') or round_replay_input or [])
                                    )
                                    round_pending_input = list(continuation_plan.get('replay_input') or round_replay_input or [])
                                    round_sse_buffer.reset()
                                    native_open_attempt = max(0, native_open_attempt - 1)
                                    try:
                                        app_logger.warning(
                                            '[RESPONSES_STATEFUL_CONTINUATION_FALLBACK] model=%s round=%s status=%s response_id=%s body=%s',
                                            model,
                                            round_idx,
                                            int(getattr(resp, 'status_code', 0) or 0),
                                            rejected_response_id[-32:],
                                            err_text[:500],
                                        )
                                    except Exception:
                                        pass
                                    continue
                                raise RuntimeError(f'Responses API error {resp.status_code}: {err_text[:4000]}')
                            for raw_line in resp.iter_lines():
                                now = time.time()
                                if now - last_ping >= 2.0:
                                    yield ': ping\n\n'
                                    last_ping = now
                                line = raw_line.decode('utf-8', errors='replace') if isinstance(raw_line, (bytes, bytearray)) else str(raw_line or '')
                                if line == '':
                                    for frame in _flush_event():
                                        yield frame
                                    if bool(native_image_state.get('image_reply_finalized')):
                                        break
                                    continue
                                if line.startswith(':'):
                                    continue
                                if line.startswith('event:'):
                                    round_sse_buffer.set_event(line[len('event:'):].strip())
                                    continue
                                if line.startswith('data:'):
                                    round_sse_buffer.add_data(line[len('data:'):].lstrip())
                                    continue
                                stripped = line.strip()
                                if stripped:
                                    round_sse_buffer.add_data(stripped)
                                    for frame in _flush_event():
                                        yield frame
                                    if bool(native_image_state.get('image_reply_finalized')):
                                        break
                            if not bool(native_image_state.get('image_reply_finalized')):
                                for frame in _flush_event():
                                    yield frame
                        if body.get('previous_response_id'):
                            stateful_continuation_supported = True
                            _RESPONSES_TRANSPORT_CAPABILITIES.set(endpoint, 'http_stateful', True)
                        break
                    except Exception as native_open_err:
                        if _should_stop_async_job():
                            raise RuntimeError('__async_chat_job_stopped__') from native_open_err
                        can_retry_native_open = bool(
                            native_open_attempt < native_open_attempts
                            and not bool(runtime_state.get('visible_delta'))
                            and not bool(round_state.get('deltas_seen'))
                            and not bool(calls_by_key)
                            and _stream_error_retryable(native_open_err)
                        )
                        if not can_retry_native_open:
                            raise
                        try:
                            app_logger.warning('[responses_native] open_retry round=%s model=%s attempt=%s/%s err=%s:%s', round_idx, model, native_open_attempt, native_open_attempts, type(native_open_err).__name__, native_open_err)
                        except Exception:
                            pass
                        yield sse('status', {'text': f'{label} 正在重新连接 {native_open_attempt}/{native_open_attempts}'})
                        time.sleep(_stream_retry_delay(native_open_attempt))
                response_id = str(round_state.get('response_id') or '').strip()
                calls = _responses_native_calls_list(calls_by_key)
                if not calls:
                    try:
                        active_groups_now = _responses_native_capability_groups(state.get('active_tool_groups') or [])
                    except Exception:
                        active_groups_now = []
                    image_generate_active = 'image_generate' in {str(x or '').strip().lower() for x in (active_groups_now or [])}
                    if bool(runtime_state.pop('native_image_leak_blocked', False)):
                        lead_buffer = ''
                        try:
                            app_logger.error('[RESPONSES_NATIVE_NON_IMAGE_GROUP_IMAGE_EVENT_BLOCKED] model=%s response_id=%s groups=%s tools=%s', model, response_id[-32:], json.dumps(active_groups_now, ensure_ascii=False), len(round_tool_specs or []))
                        except Exception:
                            pass
                        yield sse('delta', {'text': '内部工具组串线：当前是沙盒工具轮，却收到了 Responses image_generation_call，已阻断该错误事件。请重试当前请求。'})
                    elif bool(native_image_state.get('seen')):
                        if not (native_image_state.get('result_items') or []):
                            _responses_native_try_retrieve_final_image(str(response_id or round_state.get('response_id') or ''))
                        for frame in _responses_native_image_reply_frames(force=True):
                            yield frame
                        lead_buffer = ''
                    elif image_generate_active and bool(image_generation_enabled):
                        lead_buffer = ''
                        try:
                            app_logger.warning('[RESPONSES_NATIVE_IMAGE_TOOL_NOT_CALLED] model=%s response_id=%s task_type=%s tools=%s', model, response_id[-32:], str(state.get('image_task_type') or ''), len(round_tool_specs or []))
                        except Exception:
                            pass
                        yield sse('delta', {'text': '图片生成失败：上游 Responses 没有产生 image_generation_call。已按官方方式暴露并强制 image_generation 工具，但当前上游/中转没有执行该原生工具。'})
                    if lead_buffer:
                        frame = _emit_delta(lead_buffer)
                        if frame:
                            yield frame
                    if native_reasoning_seen:
                        yield sse('reasoning_meta', {'connected': True, 'done': True, 'source': native_reasoning_source or 'native_field', 'status': 'done', 'native_reasoning_text': str(native_reasoning_text_accum or '')[-60000:], 'seq': _last_activity_timeline_seq(), 'order': _last_activity_timeline_seq()})
                    visible_sources = _agent_stream_visible_sources(state, limit=8)
                    _responses_native_store_conversation_trace(
                        round_replay_input,
                        _responses_native_response_output_input_items(response_output_items_by_key),
                        endpoint=endpoint,
                        context_signature=responses_trace_context_signature,
                        user_text=last_user_text,
                    )
                    yield sse('meta', {
                        'model': model,
                        'mode': 'responses_native_tools',
                        'route_mode': 'responses_native_agent',
                        'agent_stream_tools': True,
                        'responses_native_tools': True,
                        'native_web_search': bool(state.get('native_web_used')),
                        'tool_rounds': int(state.get('tool_rounds') or 0),
                        'tool_counts': dict(state.get('tool_counts') or {}),
                        'web_hit': bool((state.get('web_results') or 0) or (state.get('pages') or 0) or (state.get('queries_used') or [])),
                        'visual_hit': bool((state.get('image_results') or 0) or (state.get('image_queries_used') or [])),
                        'source_count': len(visible_sources),
                        'sources': visible_sources,
                        'search_results': list(state.get('searched_sources') or []),
                        'searched_results': list(state.get('searched_sources') or []),
                        'result_count': int(state.get('web_results') or 0),
                        'page_count': int(state.get('pages') or 0),
                        'queries_used': [str(q or '').strip() for q in (state.get('queries_used') or []) if str(q or '').strip()],
                        **_agent_stream_web_query_groups_meta(state),
                        'use_knowledge_base': bool(state.get('kb_hit') or (state.get('kb_queries_used') or []) or (state.get('kb_results') or 0)),
                        'knowledge_hit': bool(state.get('kb_hit')),
                        'kb_result_count': int(state.get('kb_results') or 0),
                        'kb_doc_count': int(state.get('kb_doc_count') or 0),
                        'kb_chunk_count': int(state.get('kb_chunk_count') or 0),
                        'kb_queries_used': [str(q or '').strip() for q in (state.get('kb_queries_used') or []) if str(q or '').strip()],
                        'kb_search_results': [dict(x) for x in (state.get('kb_search_results') or []) if isinstance(x, dict)],
                        'use_visual': bool((state.get('image_results') or 0) or (state.get('image_queries_used') or [])),
                        'visual_intent': 'image_search' if bool((state.get('image_results') or 0) or (state.get('image_queries_used') or [])) else '',
                        'image_stage': 'searched' if bool((state.get('image_results') or 0) or (state.get('image_queries_used') or [])) else '',
                        'image_result_count': int(state.get('image_results') or 0),
                        'image_queries_used': [str(q or '').strip() for q in (state.get('image_queries_used') or []) if str(q or '').strip()],
                        **_agent_stream_file_progress_meta(state),
                        **_native_reasoning_meta_payload(),
                        **_current_runtime_model_meta(),
                    })
                    yield from _done_frames()
                    return
                state['tool_rounds'] = int(state.get('tool_rounds') or 0) + 1
                state['planned_doc_visual_review_paths'] = _agent_stream_planned_doc_visual_review_paths(calls)
                result_gen = _responses_native_tool_result_events(calls, state, last_user_text, runtime_state, round_idx)
                if result_gen is None:
                    return
                outputs = None
                try:
                    while True:
                        try:
                            frame = next(result_gen)
                            yield frame
                        except StopIteration as stop:
                            outputs = stop.value
                            break
                except TypeError:
                    outputs = []
                if outputs is None:
                    return
                if not outputs:
                    outputs = [{'type': 'function_call_output', 'call_id': str((calls[0] or {}).get('call_id') or (calls[0] or {}).get('id') or ''), 'output': json.dumps({'ok': False, 'error': 'tool_result_empty'}, ensure_ascii=False)}]
                try:
                    active_groups = _responses_native_capability_groups(state.get('active_tool_groups') or [])
                    if active_groups:
                        tool_specs = _responses_native_tool_specs(
                            compact=True,
                            allowed_tool_groups=active_groups,
                            image_task_type=str(state.get('image_task_type') or ''),
                            eager_source_images=bool(state.get('image_generation_attach_candidates') or (state.get('image_generation_eager_first') and state.get('image_task_type') in {'reference_generate', 'image_edit', 'reference_edit', 'variation'})),
                        )
                        runtime_state['tool_groups'] = list(active_groups)
                        try:
                            app_logger.info('[RESPONSES_NATIVE_CAPABILITY_ACTIVE] model=%s groups=%s tools=%s', model, json.dumps(active_groups, ensure_ascii=False), len(tool_specs or []))
                        except Exception:
                            pass
                    if bool(state.pop('pending_file_context_activation', False)) and _agent_stream_file_context_needed_for_groups(active_groups) and not bool(state.get('file_context_injected')):
                        file_augmented_messages = _agent_stream_messages_with_file_context(messages or [], state=state)
                        file_system_messages = []
                        for _m in (file_augmented_messages or []):
                            if isinstance(_m, dict) and str(_m.get('role') or '').strip().lower() == 'system' and str(_m.get('_kind') or '').strip() in {'file_memory', 'file_recall', 'file_edit_audit'}:
                                file_system_messages.append(dict(_m))
                        if file_system_messages:
                            agent_messages = list(file_system_messages) + list(agent_messages or [])
                            instructions = _responses_instructions_from_chat_messages(agent_messages or [], max_chars=_responses_native_instruction_max_chars())
                            yield sse('meta', {
                                'model': model,
                                'mode': 'responses_native_tools',
                                'route_mode': 'responses_native_agent',
                                'search_stage': 'file_context',
                                'status_text': '已准备沙盒文件清单',
                                **_agent_stream_file_progress_meta(state),
                            })
                except Exception:
                    pass
                reasoning_input_items = _responses_native_reasoning_input_items(reasoning_items_by_key)
                call_input_items = _responses_native_function_call_input_items(calls)
                extra_input_items = state.pop('pending_responses_extra_input_items', [])
                extra_items_for_image_generation = bool(state.pop('pending_responses_extra_input_items_for_image_generation', False))
                if not isinstance(extra_input_items, list):
                    extra_input_items = []
                if response_id and stateful_continuation_supported is not False:
                    previous_response_id = response_id
                    pending_continuation_input = list(outputs or []) + list(extra_input_items or [])
                else:
                    previous_response_id = ''
                    pending_continuation_input = []
                conversation_input_items = list(conversation_input_items or []) + reasoning_input_items + call_input_items + list(outputs or []) + list(extra_input_items or [])
                input_compressor = globals().get('_compress_responses_input_items_for_endpoint')
                if callable(input_compressor):
                    conversation_input_items = input_compressor(conversation_input_items, phase='responses_native_round')
                pending_input = list(conversation_input_items or [])
                if extra_input_items:
                    try:
                        image_count = 0
                        for _item in extra_input_items:
                            if isinstance(_item, dict):
                                for _c in (_item.get('content') or []):
                                    if isinstance(_c, dict) and str(_c.get('type') or '').strip().lower() == 'input_image':
                                        image_count += 1
                        try:
                            if image_count > 0 and not extra_items_for_image_generation:
                                runtime_state['responses_image_input_attached'] = True
                                runtime_state['responses_image_input_attached_count'] = int(runtime_state.get('responses_image_input_attached_count') or 0) + int(image_count or 0)
                            elif image_count > 0 and extra_items_for_image_generation:
                                runtime_state['responses_image_generation_input_attached'] = True
                                runtime_state['responses_image_generation_input_attached_count'] = int(runtime_state.get('responses_image_generation_input_attached_count') or 0) + int(image_count or 0)
                        except Exception:
                            pass
                        app_logger.info('[RESPONSES_NATIVE_IMAGE_INPUT_ATTACHED] model=%s items=%s images=%s image_generation=%s', model, len(extra_input_items), image_count, bool(extra_items_for_image_generation))
                    except Exception:
                        pass
                if show_steps:
                    try:
                        _next_groups_for_status = _responses_native_capability_groups(state.get('active_tool_groups') or [])
                    except Exception:
                        _next_groups_for_status = []
                    if bool(extra_items_for_image_generation) or 'image_generate' in [str(x or '').strip().lower() for x in (_next_groups_for_status or [])]:
                        yield sse('status', {'text': f'{label} 正在生成图片…'})
                    else:
                        yield sse('status', {'text': f'{label} 工具完成，继续流式回答…'})
        finally:
            try:
                if responses_websocket_transport is not None:
                    responses_websocket_transport.close()
            except Exception:
                pass
            if own_client is not None:
                try:
                    own_client.close()
                except Exception:
                    pass

    try:
        _raise_if_async_job_stopped()
        visual_ctx = None
        ctx = None
        tool_plan = {}
        route_mode = 'direct_answer'
        skip_native_agent_after_prepare = False

        if show_steps:
            if enable_tools:
                yield sse("status", {"text": f"{label} 当前模型：{model}（流式 Agent 优先）"})
            else:
                yield sse("status", {"text": f"{label} 当前模型：{model}（直连模式）"})

        if not enable_tools:
            prepared_for_model = _inject_visual_context_messages(list(messages or []), None)
            prepared_for_model = _inject_agent_final_direct_answer_guard(
                prepared_for_model,
                {"last_user_text": _latest_user_text_from_messages(messages or [])},
            )
            prepared_for_model = _inject_main_chat_runtime_model_context(prepared_for_model, _main_chat_runtime_model_for_context())
            cur_messages = _sanitize_messages_for_model(prepared_for_model)
            compressor = globals().get('_compress_messages_for_llm_endpoint')
            if callable(compressor):
                cur_messages = compressor(cur_messages, endpoint_mode=api_endpoint_mode, phase='fast')
            if show_steps:
                yield sse("status", {"text": f"{label} 生成回复中…"})
            _t_llm0 = time.time()
            app_logger.info(f"[TIMING] llm_start mode=fast model={model} ms={int((_t_llm0-_t_gen0)*1000)}")
            last_ping = time.time()
            fast_streamed_text_parts = []
            for chunk in _stream_completion(phase="fast", model=model, messages=cur_messages):
                now = time.time()
                if now - last_ping >= 2.0:
                    yield ": ping\n\n"
                    last_ping = now
                safe_answer_text = ''
                reasoning_text, answer_text, reasoning_source = _merge_stream_chunk_texts(chunk)
                if reasoning_text:
                    for frame in _reasoning_sse_frames(reasoning_text, reasoning_source):
                        yield frame
                if answer_text:
                    fast_streamed_text_parts.append(answer_text)
                    safe_answer_text = _strip_leaked_think_tags(answer_text)
                if safe_answer_text:
                    yield sse("delta", {"text": safe_answer_text})
            trailing_reasoning, trailing_answer, trailing_source = _flush_pending_think_text()
            if trailing_reasoning:
                for frame in _reasoning_sse_frames(trailing_reasoning, trailing_source):
                    yield frame
            if trailing_answer:
                fast_streamed_text_parts.append(trailing_answer)
                yield sse("delta", {"text": trailing_answer})
            _t_llm1 = time.time()
            app_logger.info(f"[TIMING] llm_done mode=fast model={model} ms={int((_t_llm1-_t_llm0)*1000)}")
            if native_reasoning_seen:
                yield sse('reasoning_meta', {'connected': True, 'done': True, 'source': native_reasoning_source or 'native_field', 'status': 'done', 'native_reasoning_text': str(native_reasoning_text_accum or '')[-60000:], 'seq': _last_activity_timeline_seq(), 'order': _last_activity_timeline_seq()})
            yield sse("meta", {"model": model, "mode": "fast", **_native_reasoning_meta_payload(), **_current_runtime_model_meta()})
            yield from _done_frames()
            return

        if responses_mode and _agent_stream_should_try_direct_first():
            # Responses lane must not call /chat/completions for pre-gating.
            # The same main /responses request gets the real tool set directly.
            responses_native_tool_gate = _responses_native_image_generation_preclassify(messages or [])
            if not responses_native_tool_gate:
                responses_native_tool_gate = {
                    'use_tools': True,
                    'tool_groups': ['all'],
                    'route_mode': 'responses_native_first_round_tool_select',
                    'reason': 'responses_native_no_chat_gate_fallback',
                }
            if not bool((responses_native_tool_gate or {}).get('use_tools', True)):
                light_messages = _responses_native_light_direct_messages(messages or [])
                if show_steps:
                    yield sse("status", {"text": f"{label} 生成回复中…"})
                _t_llm0 = time.time()
                try:
                    app_logger.info(
                        '[RESPONSES_NATIVE_LIGHT_DIRECT_START] model=%s messages=%s gate_reason=%s',
                        model,
                        len(light_messages or []),
                        str((responses_native_tool_gate or {}).get('reason') or '')[:240],
                    )
                except Exception:
                    pass
                last_ping = time.time()
                for chunk in _stream_completion(phase="responses_light_direct", model=model, messages=light_messages):
                    now = time.time()
                    if now - last_ping >= 2.0:
                        yield ": ping\n\n"
                        last_ping = now
                    reasoning_text, answer_text, reasoning_source = _merge_stream_chunk_texts(chunk)
                    if reasoning_text:
                        for frame in _reasoning_sse_frames(reasoning_text, reasoning_source):
                            yield frame
                    safe_answer_text = _strip_leaked_think_tags(answer_text) if answer_text else ''
                    if safe_answer_text:
                        yield sse("delta", {"text": safe_answer_text})
                trailing_reasoning, trailing_answer, trailing_source = _flush_pending_think_text()
                if trailing_reasoning:
                    for frame in _reasoning_sse_frames(trailing_reasoning, trailing_source):
                        yield frame
                if trailing_answer:
                    yield sse("delta", {"text": trailing_answer})
                _t_llm1 = time.time()
                try:
                    app_logger.info('[RESPONSES_NATIVE_LIGHT_DIRECT_DONE] model=%s ms=%s', model, int((_t_llm1 - _t_llm0) * 1000))
                except Exception:
                    pass
                if native_reasoning_seen:
                    yield sse('reasoning_meta', {'connected': True, 'done': True, 'source': native_reasoning_source or 'native_field', 'status': 'done', 'native_reasoning_text': str(native_reasoning_text_accum or '')[-60000:], 'seq': _last_activity_timeline_seq(), 'order': _last_activity_timeline_seq()})
                yield sse("meta", {
                    "model": model,
                    "mode": "responses_light_direct",
                    "route_mode": "direct_answer",
                    "responses_native_light_gate": True,
                    **_native_reasoning_meta_payload(),
                    **_current_runtime_model_meta(),
                })
                yield from _done_frames()
                return

            responses_native_runtime = {
                'visible_delta': False,
                'tool_groups': list((responses_native_tool_gate or {}).get('tool_groups') or []),
                'image_generation_eager_first': bool((responses_native_tool_gate or {}).get('image_generation_eager_first')),
                'image_generation_attach_candidates': bool((responses_native_tool_gate or {}).get('image_generation_attach_candidates')),
                'image_task_type': str((responses_native_tool_gate or {}).get('image_task_type') or ''),
                'file_task_soft_sandbox': bool((responses_native_tool_gate or {}).get('file_task_soft_sandbox')),
                'file_task_soft_reason': str((responses_native_tool_gate or {}).get('file_task_soft_reason') or ''),
            }
            if show_steps:
                yield sse("status", {"text": f"{label} 已进入 Responses 原生流式 Agent，按需调用工具…"})
            try:
                try:
                    app_logger.info(
                        '[RESPONSES_NATIVE_DIRECT_FIRST_START] model=%s messages=%s tool_groups=%s gate_reason=%s',
                        model,
                        len(messages or []),
                        json.dumps((responses_native_tool_gate or {}).get('tool_groups') or [], ensure_ascii=False),
                        str((responses_native_tool_gate or {}).get('reason') or '')[:240],
                    )
                except Exception:
                    pass
                for frame in _agent_stream_tool_web_filtered_frames(
                    _run_responses_native_tool_agent(_agent_stream_direct_first_ctx(responses_native_tool_gate), responses_native_runtime),
                    model=model,
                    lane='responses_native_tools',
                ):
                    yield frame
                return
            except Exception as responses_agent_err:
                if str(responses_agent_err or '') == '__async_chat_job_stopped__' or _should_stop_async_job():
                    raise RuntimeError('__async_chat_job_stopped__')
                skip_native_agent_after_prepare = True
                native_image_seen_before_failure = bool(responses_native_runtime.get('native_image_seen'))
                responses_image_input_seen_before_failure = bool(
                    responses_native_runtime.get('responses_image_input_queued')
                    or responses_native_runtime.get('responses_image_input_attached')
                )
                if bool(responses_native_runtime.get('visible_delta')) or native_image_seen_before_failure or responses_image_input_seen_before_failure:
                    if native_image_seen_before_failure:
                        raw_native_image_error = str(responses_native_runtime.get('native_image_error') or responses_agent_err or '').strip()
                        if not raw_native_image_error:
                            raw_native_image_error = _human_stream_error(responses_agent_err, 'responses_native_agent')
                        try:
                            app_logger.error(
                                '[RESPONSES_NATIVE_DIRECT_FIRST_IMAGE_FAILED_NO_LEGACY_FALLBACK] model=%s err=%s:%s native_image_error=%s',
                                model,
                                type(responses_agent_err).__name__,
                                str(responses_agent_err)[:800],
                                raw_native_image_error[:1200],
                            )
                        except Exception:
                            pass
                        # Responses 内置 image_generation_call 已经开始后，如果上游返回 error，
                        # 只做干净收尾：不再抛 traceback，也不再进入旧 IMAGE_MODE_EXEC 兜底，
                        # 避免同一轮继续触发旧显式图片工具或让前端占位卡住。
                        user_error_text = raw_native_image_error[:2400]
                        yield sse("status", {"text": f"{label} 图片生成失败，已结束本次生成。"})
                        yield sse("delta", {"text": "图片生成失败。上游返回错误：\n" + user_error_text})
                        yield sse("meta", {
                            "model": model,
                            "mode": "responses_native_tools",
                            "route_mode": "responses_native_agent",
                            "image_generation_ok": False,
                            "image_generation_error": user_error_text,
                            **_current_runtime_model_meta(),
                        })
                        yield from _done_frames()
                        return
                    if responses_image_input_seen_before_failure:
                        user_error_text = _human_stream_error(responses_agent_err, 'responses_native_agent')
                        try:
                            app_logger.error(
                                '[RESPONSES_NATIVE_IMAGE_INPUT_FAILED_NO_CROSS_ENDPOINT_FALLBACK] model=%s err=%s:%s queued=%s attached=%s',
                                model,
                                type(responses_agent_err).__name__,
                                str(responses_agent_err)[:1200],
                                bool(responses_native_runtime.get('responses_image_input_queued')),
                                bool(responses_native_runtime.get('responses_image_input_attached')),
                            )
                        except Exception:
                            pass
                        yield sse("error", {"error": user_error_text})
                        yield from _done_frames()
                        return
                    try:
                        app_logger.exception('[RESPONSES_NATIVE_DIRECT_FIRST_FAILED_AFTER_VISIBLE_DELTA] model=%s err=%s:%s', model, type(responses_agent_err).__name__, responses_agent_err)
                    except Exception:
                        pass
                    yield sse("error", {"error": _human_stream_error(responses_agent_err, 'responses_native_agent')})
                    yield from _done_frames()
                    return
                if responses_mode:
                    try:
                        app_logger.error('[RESPONSES_NATIVE_DIRECT_FIRST_FAILED_NO_CROSS_ENDPOINT_FALLBACK] model=%s err=%s:%s', model, type(responses_agent_err).__name__, responses_agent_err)
                    except Exception:
                        pass
                    yield sse("error", {"error": _human_stream_error(responses_agent_err, 'responses_native_agent')})
                    yield from _done_frames()
                    return
                try:
                    app_logger.error('[RESPONSES_NATIVE_DIRECT_FIRST_FAILED_NO_LEGACY_FALLBACK] model=%s err=%s:%s', model, type(responses_agent_err).__name__, responses_agent_err)
                except Exception:
                    pass
                yield sse("error", {"error": _human_stream_error(responses_agent_err, 'responses_native_agent')})
                yield from _done_frames()
                return

        if (not responses_mode) and _agent_stream_should_try_direct_first():
            direct_agent_runtime = {'visible_delta': False}
            if show_steps:
                yield sse("status", {"text": f"{label} 已进入流式 Agent 模式，按需调用工具…"})
            try:
                try:
                    app_logger.info('[AGENT_STREAM_DIRECT_FIRST_START] model=%s messages=%s', model, len(messages or []))
                except Exception:
                    pass
                for frame in _run_streaming_tool_agent(_agent_stream_direct_first_ctx(), None, direct_agent_runtime):
                    yield frame
                return
            except Exception as direct_agent_err:
                if str(direct_agent_err or '') == '__async_chat_job_stopped__' or _should_stop_async_job():
                    raise RuntimeError('__async_chat_job_stopped__')
                skip_native_agent_after_prepare = True
                direct_handoff = str(direct_agent_err or '') == '__agent_stream_image_delivery_handoff__'
                if bool(direct_agent_runtime.get('visible_delta')):
                    app_logger.exception('[AGENT_STREAM_DIRECT_FIRST_FAILED_AFTER_VISIBLE_DELTA] model=%s err=%s:%s', model, type(direct_agent_err).__name__, direct_agent_err)
                    yield sse("error", {"error": _human_stream_error(direct_agent_err, 'agent_stream')})
                    yield from _done_frames()
                    return
                try:
                    log_name = '[AGENT_STREAM_DIRECT_FIRST_HANDOFF]' if direct_handoff else '[AGENT_STREAM_DIRECT_FIRST_FAILED]'
                    app_logger.warning('%s model=%s err=%s:%s', log_name, model, type(direct_agent_err).__name__, direct_agent_err)
                except Exception:
                    pass
                yield sse("error", {"error": _human_stream_error(direct_agent_err, 'agent_stream')})
                yield from _done_frames()
                return

        if enable_tools:
            if initial_prepare_skipped:
                try:
                    app_logger.info('[AGENT_STREAM_LEGACY_PREPARE_START] model=%s messages=%s', model, len(messages or []))
                except Exception:
                    pass
                try:
                    messages = _prepare_messages(
                        list(messages or []),
                        user_geo=user_geo,
                        web_enabled=web_enabled,
                        web_k=web_k,
                        web_max_pages=web_max_pages,
                        kb_enabled=kb_enabled,
                        kb_space_id=str(kb_space_id or ''),
                        kb_doc_id=str(kb_doc_id or ''),
                    )
                    try:
                        app_logger.info('[AGENT_STREAM_LEGACY_PREPARE_DONE] model=%s messages=%s', model, len(messages or []))
                    except Exception:
                        pass
                except Exception as legacy_prepare_err:
                    try:
                        app_logger.warning('[AGENT_STREAM_LEGACY_PREPARE_FAILED] model=%s err=%s:%s', model, type(legacy_prepare_err).__name__, legacy_prepare_err)
                    except Exception:
                        pass
            ctx = _tool_orchestrator_prepare(
                model,
                messages or [],
                user_geo=user_geo,
                user_time=user_time,
                client_override=client_override,
                enable_visual=enable_visual,
                web_enabled=web_enabled,
                web_k=web_k,
                web_max_pages=web_max_pages,
            )
            route_mode = str((ctx or {}).get('route_mode') or 'direct_answer').strip().lower() or 'direct_answer'

        if enable_tools and isinstance(ctx, dict):
            visual_ctx = ctx.get('visual_ctx') if isinstance(ctx.get('visual_ctx'), dict) else None
            prefetch_decision = (ctx.get('prefetch_decision') or {}) if isinstance(ctx.get('prefetch_decision'), dict) else {}
            file_hint_active = bool(ctx.get('file_hint_active'))
            try:
                tool_plan = _decide_orchestrated_tool_plan_once(
                    model,
                    messages or [],
                    _latest_user_text_from_messages(messages or []),
                    prefetch_decision=prefetch_decision,
                    file_hint_active=file_hint_active,
                    enable_visual=enable_visual,
                    image_generation_enabled=bool(image_generation_enabled),
                    client_override=client_override,
                    user_geo=user_geo,
                    user_time=user_time if user_time is not None else ctx.get('user_time'),
                )
            except Exception:
                tool_plan = {}
            visual_decision = prefetch_decision.get('visual_decision') if isinstance(prefetch_decision.get('visual_decision'), dict) else {}
            visual_intent_hint = str((visual_decision or {}).get('intent') or '').strip().lower()
            if visual_ctx is None and bool((tool_plan or {}).get('use_visual')) and visual_intent_hint in {'image_search'}:
                try:
                    visual_ctx = _materialize_visual_context_from_decision(
                        model,
                        messages or [],
                        _latest_user_text_from_messages(messages or []),
                        visual_decision,
                        client_override=client_override,
                    )
                except Exception:
                    visual_ctx = None
            if isinstance(visual_ctx, dict):
                ctx['visual_ctx'] = visual_ctx

        native_agent_runtime = {'visible_delta': False}
        if (not responses_mode) and (not skip_native_agent_after_prepare) and _agent_stream_should_try(ctx, tool_plan, visual_ctx):
            if show_steps:
                yield sse("status", {"text": f"{label} 已进入流式 Agent 模式，按需调用工具…"})
            try:
                for frame in _run_streaming_tool_agent(ctx, visual_ctx, native_agent_runtime):
                    yield frame
                return
            except Exception as native_agent_err:
                if str(native_agent_err or '') == '__async_chat_job_stopped__' or _should_stop_async_job():
                    raise RuntimeError('__async_chat_job_stopped__')
                if bool(native_agent_runtime.get('visible_delta')):
                    app_logger.exception('[AGENT_STREAM_LOOP_FAILED_AFTER_VISIBLE_DELTA] model=%s err=%s:%s', model, type(native_agent_err).__name__, native_agent_err)
                    yield sse("error", {"error": _human_stream_error(native_agent_err, 'agent_stream')})
                    yield from _done_frames()
                    return
                try:
                    app_logger.warning('[AGENT_STREAM_LOOP_FAILED] model=%s err=%s:%s', model, type(native_agent_err).__name__, native_agent_err)
                except Exception:
                    pass
                yield sse("error", {"error": _human_stream_error(native_agent_err, 'agent_stream')})
                yield from _done_frames()
                return

        if visual_ctx and visual_ctx.get("intent") == "clarify":
            yield sse("delta", {"text": str(visual_ctx.get("text") or "请再具体说明你想看的对象。")})
            yield sse("meta", {"model": model, "mode": "clarify"})
            yield from _done_frames()
            return

        fast_image_payload = _visual_ctx_to_image_reply_payload(visual_ctx)
        if fast_image_payload:
            yield sse("image_reply", fast_image_payload)
            if show_steps:
                if route_mode == 'visual':
                    yield sse("status", {"text": f"{label} 已命中视觉增强通道，正在整理回答…"})
                else:
                    yield sse("status", {"text": f"{label} 已找到相关图片，正在继续补充网页信息…"})

        def _image_mode_status_from_plan(plan: dict | None = None) -> str:
            task_type = str((plan or {}).get('task_type') or '').strip().lower()
            if bool((plan or {}).get('need_clarify')) or task_type == 'unclear':
                return f"{label} 正在确认图片任务…"
            if task_type == 'existing_image_analysis':
                return f"{label} 正在分析图片…"
            if task_type == 'text_to_image':
                return f"{label} 正在生成图片…"
            if task_type == 'reference_generate':
                return f"{label} 正在参考图片生成…"
            if task_type in {'image_edit', 'reference_edit', 'variation'}:
                return f"{label} 正在编辑图片…"
            return f"{label} 正在处理图片…"

        preplanned_image_task_plan = {}
        if enable_tools and isinstance(ctx, dict) and bool((tool_plan or {}).get('use_image_mode')):
            try:
                preplanned_image_task_plan = _plan_image_task_once(
                    model,
                    messages or [],
                    _latest_user_text_from_messages(messages or []),
                    image_generation_settings=dict(image_generation_settings or ctx.get('image_generation_settings') or {}),
                    client_override=client_override,
                )
                if isinstance(preplanned_image_task_plan, dict):
                    ctx['preplanned_image_task_plan'] = preplanned_image_task_plan
                    try:
                        app_logger.info(
                            '[IMAGE_MODE_PREFLIGHT] model=%s task_type=%s need_clarify=%s prompt=%s candidates=%s source=%s reason=%s',
                            model,
                            str(preplanned_image_task_plan.get('task_type') or ''),
                            bool(preplanned_image_task_plan.get('need_clarify')),
                            str(preplanned_image_task_plan.get('prompt') or '')[:160],
                            len(preplanned_image_task_plan.get('candidate_rows') or []),
                            str(preplanned_image_task_plan.get('source') or ''),
                            str(preplanned_image_task_plan.get('reason') or '')[:160],
                        )
                    except Exception:
                        pass
            except Exception as e:
                preplanned_image_task_plan = {
                    'task_type': 'unclear',
                    'need_clarify': True,
                    'prompt': '',
                    'reason': f'preflight_error:{type(e).__name__}',
                    'source': 'preflight_exception',
                }
                ctx['preplanned_image_task_plan'] = preplanned_image_task_plan

        soft_web_research_hit = bool((ctx or {}).get('soft_web_research_hit'))
        emitted_route_mode = 'web_research' if soft_web_research_hit else route_mode
        if show_steps and soft_web_research_hit:
            planning_ts = int(time.time() * 1000)
            yield sse("meta", {
                "model": model,
                "mode": "agent",
                "route_mode": emitted_route_mode,
                "answer_strategy": str((ctx or {}).get('answer_strategy') or 'fast_direct'),
                "use_web_research": True,
                "search_stage": "planning",
                "status_text": "已命中联网研究，正在规划搜索与阅读…",
                "result_count": 0,
                "page_count": 0,
                "search_rounds": 0,
                "query_strategy": "",
                "queries_used": [],
                "planned_focuses": [],
                "search_results": [],
                "web_planning_at": planning_ts,
            })
            yield sse("status", {"text": f"{label} 已命中联网研究，正在规划搜索与阅读…"})
        elif show_steps:
            yield sse("status", {"text": f"{label} 正在统一判断工具与联网策略…"})
        pre_emitted_image_generation_status = False
        if show_steps and bool((tool_plan or {}).get('use_image_mode') or (tool_plan or {}).get('use_image_generation') or (tool_plan or {}).get('use_image_edit')):
            status_text = _image_mode_status_from_plan(preplanned_image_task_plan) if bool((tool_plan or {}).get('use_image_mode')) else (f"{label} 正在编辑图片…" if bool((tool_plan or {}).get('use_image_edit')) else f"{label} 正在生成图片…")
            yield sse("status", {"text": status_text})
            pre_emitted_image_generation_status = True

        def _emit_tool_status(nm, tc=None):
            if show_steps:
                if nm == "get_location":
                    yield_obj = sse("status", {"text": f"{label} 正在解析定位…"})
                elif nm == "get_weather":
                    yield_obj = sse("status", {"text": f"{label} 正在查询天气…"})
                elif nm == "image_generation":
                    if pre_emitted_image_generation_status:
                        return
                    image_status = _image_mode_status_from_plan({'task_type': str((tc or {}).get('image_task_type') or '')}) if bool((tool_plan or {}).get('use_image_mode')) else (f"{label} 正在编辑图片…" if bool((tool_plan or {}).get('use_image_edit')) else f"{label} 正在生成图片…")
                    yield_obj = sse("status", {"text": image_status})
                else:
                    yield_obj = sse("status", {"text": f"{label} 正在调用工具：{nm}"})
                nonlocal _queued_status
                _queued_status = yield_obj

        _queued_status = None
        _ctx, stage = _run_orchestrator_once(
            model,
            messages or [],
            user_geo=user_geo,
            user_time=user_time,
            client_override=client_override,
            enable_visual=enable_visual,
            web_enabled=web_enabled,
            web_k=web_k,
            web_max_pages=web_max_pages,
            image_generation_enabled=bool(image_generation_enabled),
            image_generation_settings=dict(image_generation_settings or {}),
            show_steps=show_steps,
            label=label,
            emit=lambda nm, tc=None: _emit_tool_status(nm, tc),
            prepared_ctx=ctx,
        )
        if _queued_status:
            yield _queued_status
            _queued_status = None
        actual_use_web_research = bool((stage.get('tool_plan') or {}).get('use_web_research')) or bool((stage.get('web_meta') or {}).get('enabled'))
        actual_route_mode = str(stage.get('route_mode') or emitted_route_mode or route_mode).strip().lower() or (emitted_route_mode or route_mode or 'direct_answer')
        if actual_use_web_research:
            emitted_route_mode = 'web_research'
        elif actual_route_mode:
            emitted_route_mode = actual_route_mode

        tool_records = list(stage.get("tool_records") or [])
        image_generation_result_for_status = stage.get('image_generation_result') if isinstance(stage.get('image_generation_result'), dict) else {}
        if bool(image_generation_result_for_status.get('timeout_truncated')):
            yield sse("status", {"text": str(image_generation_result_for_status.get('error') or '上游异常超时，已强行截断')})
        weather_payload = stage.get("latest_weather_payload")
        if isinstance(weather_payload, dict) and weather_payload.get("_kind") == "weather":
            # Weather data is a structured artifact, not just answer text.
            # Always emit it to the frontend so the weather card is rendered even
            # when the final model also summarizes the weather in natural language.
            yield sse("weather", weather_payload)

        if (stage.get("web_meta") or {}).get("enabled"):
            web_meta = dict(stage.get("web_meta") or {})
            if show_steps:
                q = str(web_meta.get("query") or '').strip()
                tip = (q[:60] + "…") if len(q) > 60 else q
                yield sse("status", {"text": f"{label} 正在补充网页信息：{tip}".strip() or f"{label} 正在补充网页信息…"})
            yield sse("meta", {
                "model": model,
                "mode": "agent",
                "route_mode": emitted_route_mode,
                "answer_strategy": str((ctx or {}).get('answer_strategy') or 'fast_direct'),
                "use_web_research": bool(actual_use_web_research),
                "search_stage": "searched" if int(web_meta.get('results') or 0) > 0 else "planning",
                "status_text": f"正在补充网页信息：{tip}".strip() or "正在补充网页信息…",
                "result_count": int(web_meta.get('results') or 0) if web_meta.get('results') is not None else 0,
                "page_count": int(web_meta.get('pages') or 0) if web_meta.get('pages') is not None else 0,
                "search_rounds": int(web_meta.get('search_rounds') or 0),
                "query_strategy": str(web_meta.get('query_strategy') or ''),
                "queries_used": [str(q or '').strip() for q in (web_meta.get('queries_used') or []) if str(q or '').strip()],
                "planned_focuses": [str(q or '').strip() for q in (web_meta.get('planned_focuses') or []) if str(q or '').strip()],
                "search_results": [dict(it) for it in (web_meta.get('search_results') or []) if isinstance(it, dict)],
                "web_results_reveal_at": int(time.time() * 1000),
            })

        final_messages = _build_orchestrated_final_messages(stage, messages or [], user_geo=user_geo, visual_ctx=visual_ctx)
        prefetch_decision = dict((ctx or {}).get('prefetch_decision') or {})

        emitted_artifact_keys = set()

        def _emit_files_event(files, stage_name: str):
            fresh = []
            for item in files or []:
                if not isinstance(item, dict):
                    continue
                key = f"{str(item.get('download_url') or '').strip()}|{str(item.get('filename') or '').strip()}"
                if key in emitted_artifact_keys:
                    continue
                emitted_artifact_keys.add(key)
                fresh.append(item)
            if fresh:
                return sse("files", {"files": fresh, "stage": stage_name})
            return None

        file_generation_hit = bool(stage.get('request_file_generation'))
        prefetch_decision['file_action'] = 'none'
        file_hint_active = bool((_ctx or {}).get('file_hint_active')) or file_generation_hit
        if show_steps and file_generation_hit:
            yield sse("status", {"text": f"{label} 已确认需要交付文件，正在生成文件…"})
        elif show_steps and file_hint_active:
            yield sse("status", {"text": f"{label} 正在判断是否需要生成文件…"})
        elif show_steps:
            yield sse("status", {"text": f"{label} 工具完成，生成回复中…"})

        image_generated_files = list(stage.get('generated_artifacts') or [])
        generated_files = []
        all_generated_artifacts_for_context = [*(image_generated_files or []), *(generated_files or [])]
        historical_generated_artifacts = _collect_generated_file_artifacts_from_messages(messages or [])
        current_delivery_artifacts = list(generated_files or []) or list(all_generated_artifacts_for_context or [])
        allowed_generated_link_artifacts = list(current_delivery_artifacts or []) if generated_files else [*(current_delivery_artifacts or []), *(historical_generated_artifacts or [])]
        tool_plan = dict(stage.get('tool_plan') or {})
        is_image_turn = bool(_stage_has_image_mode_request(stage) or image_generated_files)
        image_direct_reply_done = _stage_should_direct_return_image_reply(stage)
        file_messages = list(final_messages)
        file_edit_audits = []
        image_reply_payload = _image_generation_artifacts_to_image_reply_payload(
            image_generated_files,
            subject=str(((stage.get('image_generation_result') or {}).get('subject') or (stage.get('tool_plan') or {}).get('image_generation_subject') or '')).strip(),
            task_mode=str(((stage.get('image_generation_result') or {}).get('task_mode') or '')).strip(),
        )
        if image_reply_payload:
            yield sse('image_reply', image_reply_payload)
        files_event = _emit_files_event(generated_files, 'tool')
        if files_event:
            yield files_event

        final_text = ''
        should_run_final_model = not bool(image_direct_reply_done)
        if should_run_final_model:
            guarded_final_source_messages = list(file_messages or [])
            if generated_files or file_edit_audits:
                guarded_final_source_messages = _strip_file_delivery_internal_messages_for_final(guarded_final_source_messages)
            guarded_final_messages = _inject_agent_final_direct_answer_guard(guarded_final_source_messages, stage)
            guarded_final_messages = _inject_agent_final_fact_bridge(model, guarded_final_messages, stage, client_override=client_override)
            guarded_final_messages = _inject_generated_artifact_context_for_final(guarded_final_messages, current_delivery_artifacts, file_edit_audits)
            guard_process_only = _agent_final_has_grounding(guarded_final_messages, stage)
            try:
                app_logger.info(
                    "[AGENT_FINAL_REQUEST_READY] model=%s elapsed_ms=%s guarded_messages=%s tool_records=%s web_enabled=%s web_reason=%s file_action=%s direct_answer=%s guard_process_only=%s",
                    model,
                    int((time.time() - _t_gen0) * 1000),
                    len(guarded_final_messages or []),
                    len(tool_records or []),
                    bool(((stage.get('web_meta') or {}).get('enabled'))),
                    str(((stage.get('web_meta') or {}).get('reason')) or ''),
                    str((prefetch_decision.get('file_action') or 'none')),
                    bool(str(stage.get('planner_direct_answer') or '').strip()),
                    bool(guard_process_only),
                )
            except Exception:
                pass
            _t_llm0 = time.time()
            app_logger.info(f"[TIMING] llm_start mode=agent_final model={model} ms={int((_t_llm0-_t_gen0)*1000)}")
            last_ping = time.time()
            streamed_text_parts = []
            pending_lead = ''
            buffer_file_visible_text = bool(generated_files or file_edit_audits)
            lead_flushed = bool(buffer_file_visible_text) or (not guard_process_only)
            for chunk in _stream_completion(phase="agent_final", model=model, messages=guarded_final_messages):
                now = time.time()
                if now - last_ping >= 2.0:
                    yield ": ping\n\n"
                    last_ping = now
                reasoning_text, answer_text, reasoning_source = _merge_stream_chunk_texts(chunk)
                if reasoning_text:
                    for frame in _reasoning_sse_frames(reasoning_text, reasoning_source):
                        yield frame
                if not answer_text:
                    continue
                streamed_text_parts.append(answer_text)
                if buffer_file_visible_text:
                    continue
                if not lead_flushed:
                    pending_lead += answer_text
                    pending_len = len(pending_lead)
                    looks_process_only = _looks_like_process_only_reply(pending_lead)
                    has_sentence_end = pending_lead.endswith(("。", "！", "？", "!", "?", ";", "；", ":", "：", "\n"))
                    waiting_structured_preface = bool(guard_process_only and _looks_like_grounded_structured_preface_start(pending_lead) and '}' not in pending_lead and ']' not in pending_lead and pending_len < 2400)
                    if waiting_structured_preface:
                        continue
                    if looks_process_only and pending_len < 48 and not has_sentence_end:
                        continue
                    sanitized_lead = _strip_grounded_process_preface(pending_lead, aggressive=bool(guard_process_only)) if guard_process_only else _strip_leaked_think_tags(pending_lead)
                    lead_flushed = True
                    if sanitized_lead:
                        yield sse("delta", {"text": sanitized_lead})
                    pending_lead = ''
                    continue
                yield sse("delta", {"text": answer_text})
            trailing_reasoning, trailing_answer, trailing_source = _flush_pending_think_text()
            if trailing_reasoning:
                for frame in _reasoning_sse_frames(trailing_reasoning, trailing_source):
                    yield frame
            if trailing_answer:
                trailing_answer = _strip_leaked_think_tags(trailing_answer)
                streamed_text_parts.append(trailing_answer)
                if not lead_flushed:
                    pending_lead += trailing_answer
                else:
                    if trailing_answer and not buffer_file_visible_text:
                        yield sse("delta", {"text": trailing_answer})
            _t_llm1 = time.time()
            app_logger.info(f"[TIMING] llm_done mode=agent_final model={model} ms={int((_t_llm1-_t_llm0)*1000)}")
            final_text = ''.join(streamed_text_parts)
            final_text = _sanitize_file_delivery_visible_text(
                final_text,
                has_artifacts=bool(buffer_file_visible_text),
                allowed_artifacts=allowed_generated_link_artifacts,
                strip_all_generated_links=bool(generated_files),
            ) if buffer_file_visible_text else _strip_grounded_process_preface(final_text, aggressive=bool(guard_process_only))
            if buffer_file_visible_text:
                final_text = _strip_redundant_generated_file_lines(final_text, [])
            if buffer_file_visible_text:
                if final_text:
                    yield sse("delta", {"text": final_text})
            elif not lead_flushed and pending_lead:
                sanitized_pending = _strip_grounded_process_preface(pending_lead, aggressive=bool(guard_process_only))
                if sanitized_pending:
                    yield sse("delta", {"text": sanitized_pending})
            if native_reasoning_seen:
                yield sse('reasoning_meta', {'connected': True, 'done': True, 'source': native_reasoning_source or 'native_field', 'status': 'done', 'native_reasoning_text': str(native_reasoning_text_accum or '')[-60000:], 'seq': _last_activity_timeline_seq(), 'order': _last_activity_timeline_seq()})

        fallback_artifacts = []

        final_text = _strip_redundant_generated_file_lines(final_text, [*(allowed_generated_link_artifacts or []), *(fallback_artifacts or [])] if not generated_files else [])

        merged_artifacts = []
        seen_artifact_keys = set()
        for item in [*(generated_files or []), *(fallback_artifacts or [])]:
            if not isinstance(item, dict):
                continue
            key = f"{str(item.get('download_url') or '').strip()}|{str(item.get('filename') or '').strip()}"
            if key in seen_artifact_keys:
                continue
            seen_artifact_keys.add(key)
            merged_artifacts.append(item)

        web_hit = _stage_has_bound_web_hit(stage)
        visible_sources = _collect_stage_visible_sources(final_messages, stage, limit=8) if web_hit else []

        web_meta = dict(stage.get('web_meta') or {})
        yield sse("meta", {
            "model": model,
            "mode": "agent",
            "route_mode": emitted_route_mode,
            "answer_strategy": str((ctx or {}).get('answer_strategy') or 'fast_direct'),
            "use_web_research": bool(actual_use_web_research),
            "web_hit": web_hit,
            "artifact_count": len(merged_artifacts) + len(image_generated_files or []),
            "artifact_filenames": [str(item.get('filename') or '') for item in [*(merged_artifacts or []), *(image_generated_files or [])] if isinstance(item, dict)],
            "artifacts": merged_artifacts,
            "image_artifacts": image_generated_files,
            "image_generation_ok": bool((stage.get('image_generation_result') or {}).get('ok')),
            "file_tool_used": False,
            "file_tool_rounds": 0,
            "file_edit_audits": file_edit_audits,
            "source_count": len(visible_sources) if web_hit else 0,
            "sources": visible_sources if web_hit else [],
            "result_count": int(web_meta.get('results') or 0) if web_meta.get('results') is not None else 0,
            "page_count": int(web_meta.get('pages') or 0) if web_meta.get('pages') is not None else 0,
            "search_rounds": int(web_meta.get('search_rounds') or 0),
            "query_strategy": str(web_meta.get('query_strategy') or ''),
            "queries_used": [str(q or '').strip() for q in (web_meta.get('queries_used') or []) if str(q or '').strip()],
            "planned_focuses": [str(q or '').strip() for q in (web_meta.get('planned_focuses') or []) if str(q or '').strip()],
            "search_results": [dict(it) for it in (web_meta.get('search_results') or []) if isinstance(it, dict)],
            **_native_reasoning_meta_payload(),
            **_current_runtime_model_meta(),
        })
        yield from _done_frames()
        return

    except Exception as e:
        msg = str(e) or f"{type(e).__name__}: {e}"
        if msg == '__async_chat_job_stopped__':
            yield sse("status", {"text": "已停止"})
            yield from _done_frames()
            return
        app_logger.exception("_chat_stream_gen error")
        yield sse("error", {"error": msg})
        yield from _done_frames()
        return
