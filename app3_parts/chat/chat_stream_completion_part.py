# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: stream-completion lifecycle, request shaping, retry activity, and usage recording.
# Loaded before chat_streaming_part.py, sharing the original global namespace.

import time


class ChatStreamCompletionRunner:
    def __init__(
        self,
        *,
        api_endpoint_mode: str = 'chat_completions',
        model: str = '',
        client_override=None,
        client_session_id: str = '',
        should_stop=None,
        raise_if_stopped=None,
        close_stream_if_possible=None,
        human_stream_error=None,
        looks_like_image_request_error=None,
        sanitize_messages_for_model=None,
        apply_user_generation_settings=None,
        stream_cfg_int=None,
        stream_error_retryable=None,
        stream_retry_delay=None,
        open_stream_with_retry=None,
        set_current_stream_handle=None,
        remember_runtime_model=None,
        extract_runtime_model_from_obj=None,
        extract_usage_from_stream_chunk=None,
        record_generation_usage=None,
    ):
        self.api_endpoint_mode = str(api_endpoint_mode or '')
        self.model = str(model or '')
        self.client_override = client_override
        self.client_session_id = str(client_session_id or '')
        self.should_stop = should_stop if callable(should_stop) else (lambda: False)
        self.raise_if_stopped = raise_if_stopped if callable(raise_if_stopped) else (lambda: None)
        self.close_stream_if_possible = close_stream_if_possible if callable(close_stream_if_possible) else (lambda stream_resp: None)
        self.human_stream_error = human_stream_error if callable(human_stream_error) else (lambda err, phase: str(err))
        self.looks_like_image_request_error = looks_like_image_request_error if callable(looks_like_image_request_error) else (lambda err: False)
        self.sanitize_messages_for_model = sanitize_messages_for_model if callable(sanitize_messages_for_model) else (lambda msgs=None, **kwargs: list(msgs or []))
        self.apply_user_generation_settings = apply_user_generation_settings if callable(apply_user_generation_settings) else (lambda kwargs, endpoint_mode='', client_obj=None: dict(kwargs or {}))
        self.stream_cfg_int = stream_cfg_int if callable(stream_cfg_int) else (lambda name, default, min_value=0, max_value=100: default)
        self.stream_error_retryable = stream_error_retryable if callable(stream_error_retryable) else (lambda err: False)
        self.stream_retry_delay = stream_retry_delay if callable(stream_retry_delay) else (lambda attempt: 0.0)
        self.open_stream_with_retry = open_stream_with_retry if callable(open_stream_with_retry) else (lambda stream_client, phase='', call_kwargs=None: stream_client.chat.completions.create(stream=True, **dict(call_kwargs or {})))
        self.set_current_stream_handle = set_current_stream_handle if callable(set_current_stream_handle) else (lambda stream_resp: None)
        self.remember_runtime_model = remember_runtime_model if callable(remember_runtime_model) else (lambda value: '')
        self.extract_runtime_model_from_obj = extract_runtime_model_from_obj if callable(extract_runtime_model_from_obj) else (lambda chunk: '')
        self.extract_usage_from_stream_chunk = extract_usage_from_stream_chunk if callable(extract_usage_from_stream_chunk) else (lambda chunk: {})
        self.record_generation_usage = record_generation_usage if callable(record_generation_usage) else (lambda usage, **kwargs: None)

    def messages_have_input_image_parts(self, msgs: list | None = None) -> bool:
        try:
            for m in (msgs or []):
                if not isinstance(m, dict):
                    continue
                content = m.get('content')
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and str(item.get('type') or '').strip().lower() == 'input_image':
                            return True
                elif isinstance(content, dict) and str(content.get('type') or '').strip().lower() == 'input_image':
                    return True
        except Exception:
            return False
        return False

    def stream_completion(self, *, phase: str, **kwargs):
        stream_resp = None
        stream_http_client = None
        stream_client = self.client_override or client_gpt
        emit_open_retry_activity = bool(kwargs.pop('_emit_open_retry_activity', False))
        self.raise_if_stopped()
        require_sandbox_visual_images = bool(str(phase or '').strip() in {'agent_stream_direct_image_final'} and self.messages_have_input_image_parts(kwargs.get('messages') if isinstance(kwargs.get('messages'), list) else []))
        def _stream_retry_activity_chunk(*, attempt: int, attempts: int, err: Exception | None = None, state: str = 'active', done: bool = False, clear: bool = False):
            phase_text = str(phase or 'stream').strip() or 'stream'
            model_text = str((kwargs or {}).get('model') or self.model or '').strip()
            err_type = type(err).__name__ if err is not None else ''
            title = f"正在重新连接 {attempt}/{attempts}"
            if clear:
                title = f"正在重新连接 {attempt}/{attempts}"
            elif done:
                title = f"已重新连接 {attempt}/{attempts}"
            detail_bits = []
            if model_text:
                detail_bits.append(model_text)
            if err_type:
                detail_bits.append(err_type)
            now_ms = int(time.time() * 1000)
            terminal_retry = bool(done or clear)
            activity_op = 'remove' if clear else 'upsert'
            return {
                '_webai_stream_control': 'activity_event',
                'activity_event': {
                    'activityEvent': True,
                    'activity_event': True,
                    'key': f"stream_retry|{phase_text}|{model_text or 'model'}",
                    'stage': 'answer',
                    'kind': 'stream_open_retry',
                    'rawStage': 'stream_open_retry',
                    'raw_stage': 'stream_open_retry',
                    'tool': 'llm_stream',
                    'state': 'done' if terminal_retry else (str(state or 'active') or 'active'),
                    'status': 'done' if terminal_retry else 'running',
                    'title': title,
                    'text': title,
                    'detail': ' · '.join(detail_bits),
                    'remove': bool(clear),
                    'removed': bool(clear),
                    'activity_op': activity_op,
                    'activityOp': activity_op,
                    'attempt': int(attempt or 0),
                    'attempt_total': int(attempts or 0),
                    'attemptTotal': int(attempts or 0),
                    'error_type': err_type,
                    'errorType': err_type,
                    'ts': now_ms,
                    'updated_at': now_ms,
                    'updatedAt': now_ms,
                },
            }
        try:
            if isinstance(kwargs.get('messages'), list):
                kwargs = dict(kwargs)
                chat_cache_messages = globals().get('_prompt_cache_chat_messages_for_request')
                if callable(chat_cache_messages) and str(self.api_endpoint_mode or '').strip().lower() != 'responses':
                    kwargs['messages'] = chat_cache_messages(kwargs.get('messages') or [])
                kwargs['messages'] = self.sanitize_messages_for_model(kwargs.get('messages') or [])
                compressor = globals().get('_compress_messages_for_llm_endpoint')
                if callable(compressor):
                    kwargs['messages'] = compressor(kwargs.get('messages') or [], endpoint_mode=self.api_endpoint_mode, phase=phase)
            try:
                app_logger.info(
                    '[LLM_CALL] purpose=%s stream=1 model=%s messages=%s tools=%s',
                    str(phase or 'stream'),
                    kwargs.get('model'),
                    len(kwargs.get('messages') or []),
                    len(kwargs.get('tools') or []) if isinstance(kwargs.get('tools'), list) else 0,
                )
            except Exception:
                pass
            helper = globals().get('_build_isolated_stream_openai_client')
            if callable(helper):
                try:
                    stream_client, stream_http_client = helper(stream_client)
                except Exception as isolated_err:
                    stream_client = self.client_override or client_gpt
                    stream_http_client = None
                    try:
                        app_logger.warning('[chat_stream] isolated_stream_client_build_failed phase=%s model=%s err=%s:%s', phase, kwargs.get('model'), type(isolated_err).__name__, isolated_err)
                    except Exception:
                        pass
            active_stream_kwargs = self.apply_user_generation_settings(kwargs, endpoint_mode=self.api_endpoint_mode, client_obj=stream_client)
            cache_base_url = ''
            try:
                cache_helper = globals().get('_apply_prompt_cache_to_request_payload')
                if callable(cache_helper) and str(self.api_endpoint_mode or '').strip().lower() != 'responses':
                    _cache_api_key, cache_base_url = ('', '')
                    resolver = globals().get('_resolve_openai_client_identity')
                    if callable(resolver):
                        try:
                            _cache_api_key, cache_base_url = resolver(stream_client)
                        except Exception:
                            cache_base_url = str(getattr(stream_client, 'base_url', '') or '')
                    else:
                        cache_base_url = str(getattr(stream_client, 'base_url', '') or globals().get('GPT_BASE_URL') or '')
                    active_stream_kwargs = cache_helper(
                        active_stream_kwargs,
                        endpoint_mode=self.api_endpoint_mode,
                        model=str(active_stream_kwargs.get('model') if isinstance(active_stream_kwargs, dict) else kwargs.get('model') or ''),
                        base_url=cache_base_url,
                        phase=phase,
                        placement='extra_body',
                        cache_namespace=self.client_session_id,
                    )
            except Exception:
                pass
            usage_call_key = 'chat|%s|%s|%s' % (str(phase or ''), str(active_stream_kwargs.get('model') if isinstance(active_stream_kwargs, dict) else kwargs.get('model') or ''), time.time_ns())
            try:
                app_logger.info('[GENERATION_PARAMS] endpoint=%s phase=%s keys=%s extra_body_keys=%s', self.api_endpoint_mode, phase, sorted(str(k) for k in active_stream_kwargs.keys() if k in {'max_completion_tokens','temperature','top_p','response_format','stream_options','extra_body','prompt_cache_key','prompt_cache_retention'}), sorted(str(k) for k in ((active_stream_kwargs.get('extra_body') or {}).keys())) if isinstance(active_stream_kwargs.get('extra_body'), dict) else [])
            except Exception:
                pass
            if emit_open_retry_activity and self.api_endpoint_mode != 'responses':
                attempts = 1 + self.stream_cfg_int('GPT_STREAM_MAX_RETRIES', 2, min_value=0, max_value=5)
                last_open_err = None
                last_retry_attempt = 0
                for open_attempt in range(1, attempts + 1):
                    self.raise_if_stopped()
                    try:
                        stream_resp = stream_client.chat.completions.create(stream=True, **active_stream_kwargs)
                        if last_retry_attempt > 0:
                            yield _stream_retry_activity_chunk(attempt=last_retry_attempt, attempts=attempts, err=last_open_err, clear=True)
                        break
                    except Exception as open_err:
                        if self.should_stop():
                            raise RuntimeError('__async_chat_job_stopped__') from open_err
                        extra = active_stream_kwargs.get('extra_body') if isinstance(active_stream_kwargs.get('extra_body'), dict) else {}
                        reject_modern = globals().get('_prompt_cache_rejects_modern_protocol')
                        strip_modern = globals().get('_prompt_cache_without_modern_protocol')
                        if (
                            'prompt_cache_options' in extra
                            and callable(reject_modern)
                            and callable(strip_modern)
                            and reject_modern(str(open_err or ''))
                        ):
                            active_stream_kwargs = strip_modern(active_stream_kwargs, placement='extra_body')
                            try:
                                stream_resp = stream_client.chat.completions.create(stream=True, **active_stream_kwargs)
                                break
                            except Exception as compatibility_err:
                                open_err = compatibility_err
                        last_open_err = open_err
                        if open_attempt >= attempts or not self.stream_error_retryable(open_err):
                            raise
                        last_retry_attempt = open_attempt
                        try:
                            app_logger.warning('[chat_stream] open_retry phase=%s model=%s attempt=%s/%s err=%s:%s', phase, active_stream_kwargs.get('model') if isinstance(active_stream_kwargs, dict) else kwargs.get('model'), open_attempt, attempts, type(open_err).__name__, open_err)
                        except Exception:
                            pass
                        yield _stream_retry_activity_chunk(attempt=open_attempt, attempts=attempts, err=open_err, state='active')
                        time.sleep(self.stream_retry_delay(open_attempt))
                if stream_resp is None:
                    if last_open_err is not None:
                        raise last_open_err
                    raise RuntimeError('stream_open_failed')
            else:
                stream_resp = self.open_stream_with_retry(stream_client, phase=phase, call_kwargs=active_stream_kwargs)
        except Exception as e:
            if self.should_stop():
                raise RuntimeError('__async_chat_job_stopped__') from e
            if isinstance(kwargs.get('messages'), list) and self.looks_like_image_request_error(e):
                try:
                    app_logger.warning('[chat_stream] image_request_failed_no_drop_retry phase=%s model=%s sandbox_visual=%s err=%s:%s', phase, kwargs.get('model'), bool(require_sandbox_visual_images), type(e).__name__, e)
                except Exception:
                    pass
            raise RuntimeError(self.human_stream_error(e, phase)) from e
        try:
            try:
                self.set_current_stream_handle(stream_resp)
            except Exception:
                pass
            self.raise_if_stopped()
            chunks_seen = 0
            read_retry_count = 0
            pending_read_retry_clear = None
            while True:
                try:
                    for chunk in stream_resp:
                        if self.should_stop():
                            self.close_stream_if_possible(stream_resp)
                            raise RuntimeError('__async_chat_job_stopped__')
                        chunks_seen += 1
                        if pending_read_retry_clear:
                            clear_attempt, clear_attempts, clear_err = pending_read_retry_clear
                            pending_read_retry_clear = None
                            yield _stream_retry_activity_chunk(attempt=clear_attempt, attempts=clear_attempts, err=clear_err, clear=True)
                        self.remember_runtime_model(self.extract_runtime_model_from_obj(chunk))
                        try:
                            usage_payload = self.extract_usage_from_stream_chunk(chunk)
                            if usage_payload:
                                self.record_generation_usage(usage_payload, phase=phase, model_name=str(active_stream_kwargs.get('model') if isinstance(active_stream_kwargs, dict) else kwargs.get('model') or ''), endpoint=self.api_endpoint_mode, call_key=usage_call_key)
                        except Exception:
                            pass
                        yield chunk
                    break
                except Exception as read_err:
                    if str(read_err or '') == '__async_chat_job_stopped__' or self.should_stop():
                        raise RuntimeError('__async_chat_job_stopped__')
                    max_read_retries = self.stream_cfg_int('GPT_STREAM_MAX_RETRIES', 2, min_value=0, max_value=5)
                    if chunks_seen <= 0 and read_retry_count < max_read_retries and self.stream_error_retryable(read_err):
                        read_retry_count += 1
                        try:
                            app_logger.warning('[chat_stream] read_retry_before_first_chunk phase=%s model=%s attempt=%s/%s err=%s:%s', phase, active_stream_kwargs.get('model') if isinstance(active_stream_kwargs, dict) else '', read_retry_count, max_read_retries, type(read_err).__name__, read_err)
                        except Exception:
                            pass
                        self.close_stream_if_possible(stream_resp)
                        pending_read_retry_clear = (read_retry_count, max_read_retries, read_err)
                        yield _stream_retry_activity_chunk(attempt=read_retry_count, attempts=max_read_retries, err=read_err, state='active')
                        time.sleep(self.stream_retry_delay(read_retry_count))
                        stream_resp = self.open_stream_with_retry(stream_client, phase=phase, call_kwargs=active_stream_kwargs)
                        try:
                            self.set_current_stream_handle(stream_resp)
                        except Exception:
                            pass
                        continue
                    raise
        except Exception as e:
            if str(e or '') == '__async_chat_job_stopped__' or self.should_stop():
                raise RuntimeError('__async_chat_job_stopped__')
            raise RuntimeError(self.human_stream_error(e, phase)) from e
        finally:
            try:
                self.set_current_stream_handle(None)
            except Exception:
                pass
            self.close_stream_if_possible(stream_resp)
            helper = globals().get('_close_httpx_client_quietly')
            if callable(helper):
                try:
                    helper(stream_http_client)
                except Exception:
                    pass
