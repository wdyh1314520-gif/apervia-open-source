# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: centralize Chat/Responses stream opening while keeping event loops in chat_streaming_part.py.
# Loaded before chat_streaming_part.py, sharing the original global namespace.


class ChatStreamOpenHelper:
    def __init__(self, *, endpoint_mode: str, default_model: str = '', retry_policy=None, should_stop=None, raise_if_stopped=None):
        self.endpoint_mode = str(endpoint_mode or '')
        self.default_model = str(default_model or '')
        self.retry_policy = retry_policy or ChatStreamRetryPolicy()
        self.should_stop = should_stop
        self.raise_if_stopped = raise_if_stopped

    def _should_stop_current_job(self) -> bool:
        try:
            return bool(self.should_stop()) if callable(self.should_stop) else False
        except Exception:
            return False

    def _raise_if_stopped(self) -> None:
        if callable(self.raise_if_stopped):
            self.raise_if_stopped()
            return
        if self._should_stop_current_job():
            raise RuntimeError('__async_chat_job_stopped__')

    def responses_kwargs(self, stream_client, *, call_kwargs: dict) -> dict:
        responses_kwargs = dict(call_kwargs or {})
        responses_kwargs.pop('tools', None)
        responses_kwargs.pop('tool_choice', None)
        responses_kwargs.pop('response_format', None)
        responses_kwargs.pop('stream_options', None)
        try:
            apply_thinking = globals().get('_apply_completion_thinking_kwargs')
            if callable(apply_thinking):
                responses_kwargs = apply_thinking(
                    responses_kwargs,
                    role='main_chat',
                    model=responses_kwargs.get('model') or self.default_model,
                    client_override=stream_client,
                )
        except Exception:
            pass
        try:
            responses_extra_body = _responses_extra_body_with_reasoning_summary(
                responses_kwargs.get('extra_body') if isinstance(responses_kwargs.get('extra_body'), dict) else {},
                model=responses_kwargs.get('model') or self.default_model,
            )
            responses_kwargs['extra_body'] = responses_extra_body
        except Exception:
            responses_extra_body = responses_kwargs.get('extra_body') if isinstance(responses_kwargs.get('extra_body'), dict) else {}
        responses_kwargs['_responses_extra_body_for_log'] = responses_extra_body if isinstance(responses_extra_body, dict) else {}
        return responses_kwargs

    def open_responses_stream(self, stream_client, *, phase: str, call_kwargs: dict):
        responses_kwargs = self.responses_kwargs(stream_client, call_kwargs=call_kwargs)
        responses_extra_body = responses_kwargs.pop('_responses_extra_body_for_log', {})
        try:
            app_logger.info(
                '[LLM_CALL] purpose=%s endpoint=responses stream=1 model=%s messages=%s extra_body_keys=%s reasoning_keys=%s thinking_keys=%s',
                phase,
                responses_kwargs.get('model'),
                len(responses_kwargs.get('messages') or []),
                sorted((responses_kwargs.get('extra_body') or {}).keys()) if isinstance(responses_kwargs.get('extra_body'), dict) else [],
                sorted(((responses_extra_body.get('reasoning') or {}).keys())) if isinstance(responses_extra_body, dict) and isinstance(responses_extra_body.get('reasoning'), dict) else [],
                sorted(((responses_extra_body.get('thinking') or {}).keys())) if isinstance(responses_extra_body, dict) and isinstance(responses_extra_body.get('thinking'), dict) else [],
            )
        except Exception:
            pass
        return _responses_stream_text_chunks(
            stream_client,
            model=responses_kwargs.get('model') or self.default_model,
            messages=responses_kwargs.get('messages') or [],
            extra_body=responses_kwargs.get('extra_body') if isinstance(responses_kwargs.get('extra_body'), dict) else None,
        )

    def open_chat_stream_with_retry(self, stream_client, *, phase: str, call_kwargs: dict):
        attempts = self.retry_policy.max_attempts()
        last_err = None
        attempt = 0
        while attempt < attempts:
            attempt += 1
            self._raise_if_stopped()
            try:
                return stream_client.chat.completions.create(stream=True, **call_kwargs)
            except Exception as open_err:
                if self._should_stop_current_job():
                    raise RuntimeError('__async_chat_job_stopped__') from open_err
                last_err = open_err
                extra = call_kwargs.get('extra_body') if isinstance(call_kwargs.get('extra_body'), dict) else {}
                reject_modern = globals().get('_prompt_cache_rejects_modern_protocol')
                strip_modern = globals().get('_prompt_cache_without_modern_protocol')
                if (
                    'prompt_cache_options' in extra
                    and callable(reject_modern)
                    and callable(strip_modern)
                    and reject_modern(str(open_err or ''))
                ):
                    stripped = strip_modern(call_kwargs, placement='extra_body')
                    call_kwargs.clear()
                    call_kwargs.update(stripped)
                    attempt -= 1
                    try:
                        app_logger.warning('[CHAT_PROMPT_CACHE_PROTOCOL_RETRY] phase=%s model=%s', phase, call_kwargs.get('model'))
                    except Exception:
                        pass
                    continue
                if attempt >= attempts or not self.retry_policy.is_retryable(open_err):
                    raise
                try:
                    app_logger.warning('[chat_stream] open_retry phase=%s model=%s attempt=%s/%s err=%s:%s', phase, call_kwargs.get('model'), attempt, attempts, type(open_err).__name__, open_err)
                except Exception:
                    pass
                time.sleep(self.retry_policy.delay(attempt))
        if last_err is not None:
            raise last_err
        raise RuntimeError('stream_open_failed')

    def open_stream(self, stream_client, *, phase: str, call_kwargs: dict):
        if self.endpoint_mode == 'responses':
            return self.open_responses_stream(stream_client, phase=phase, call_kwargs=call_kwargs)
        return self.open_chat_stream_with_retry(stream_client, phase=phase, call_kwargs=call_kwargs)
