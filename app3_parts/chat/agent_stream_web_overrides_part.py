# agent stream web override filtering helpers.

AGENT_STREAM_CHAT_TOOL_WEB_OVERRIDE_BLOCKED_KEYS = {
    'AUTO_WEB_K_RESULTS',
    'AUTO_WEB_FAST_MAX_PAGES',
    'AUTO_WEB_MAX_PAGES',
    'AUTO_WEB_MAX_QUERIES',
    'AUTO_WEB_FETCH_WORKERS',
    'AUTO_WEB_PAGE_TIMEOUT',
    'AUTO_WEB_PAGE_MAX_CHARS',
    'AUTO_WEB_PAGE_SNIPPET_CHARS',
    'WEB_SEARCH_MIN_EFFECTIVE_RESULTS',
    'WEB_SEARCH_TARGET_RESULTS',
    'MAX_WEB_SEARCH_CALLS',
}

# Responses native web_search has its own provider-side knobs. Keep the old
# self-hosted Chat search breadth knobs out of the Responses-native lane.
# `MAX_WEB_SEARCH_CALLS` is ignored in both lanes because tool invocation is
# unbounded; it must not leak into a relay-specific request parameter.
AGENT_STREAM_RESPONSES_NATIVE_WEB_OVERRIDE_BLOCKED_KEYS = {
    'AUTO_WEB_K_RESULTS',
    'AUTO_WEB_FAST_MAX_PAGES',
    'AUTO_WEB_MAX_PAGES',
    'AUTO_WEB_MAX_QUERIES',
    'AUTO_WEB_FETCH_WORKERS',
    'AUTO_WEB_PAGE_TIMEOUT',
    'AUTO_WEB_PAGE_MAX_CHARS',
    'AUTO_WEB_PAGE_SNIPPET_CHARS',
    'WEB_SEARCH_MIN_EFFECTIVE_RESULTS',
    'WEB_SEARCH_TARGET_RESULTS',
    'MAX_WEB_SEARCH_CALLS',
}

# Backward-compatible names for older local hooks/imports.
AGENT_STREAM_TOOL_WEB_OVERRIDE_BLOCKED_KEYS = AGENT_STREAM_CHAT_TOOL_WEB_OVERRIDE_BLOCKED_KEYS
AGENT_STREAM_NATIVE_WEB_OVERRIDE_BLOCKED_KEYS = AGENT_STREAM_RESPONSES_NATIVE_WEB_OVERRIDE_BLOCKED_KEYS


def _agent_stream_tool_web_override_snapshot(overrides: dict | None = None, *, lane: str = 'chat_completions_streaming_agent') -> dict:
    """Return request overrides for a streaming tool-calling search lane.

    Chat-completions tool agents still use the self-hosted function search tools,
    so the old AUTO_WEB breadth knobs are blocked there exactly as before.
    Responses-native agents use the provider `web_search` tool; they keep only
    Responses-specific knobs. Legacy Chat call-count knobs are filtered out so
    they cannot reintroduce a limit or reach relay providers by accident.
    """
    src = dict(overrides or {}) if isinstance(overrides, dict) else {}
    if not src:
        return {}
    lane_key = str(lane or '').strip().lower()
    if lane_key in {'responses_native_tools', 'responses_native_agent', 'responses'}:
        blocked = set(AGENT_STREAM_RESPONSES_NATIVE_WEB_OVERRIDE_BLOCKED_KEYS)
    else:
        blocked = set(AGENT_STREAM_CHAT_TOOL_WEB_OVERRIDE_BLOCKED_KEYS)
    return {str(k): v for k, v in src.items() if str(k) not in blocked}


def _agent_stream_chat_web_override_snapshot(overrides: dict | None = None) -> dict:
    return _agent_stream_tool_web_override_snapshot(overrides, lane='chat_completions_streaming_agent')


def _agent_stream_native_web_override_snapshot(overrides: dict | None = None) -> dict:
    return _agent_stream_tool_web_override_snapshot(overrides, lane='responses_native_tools')


def _agent_stream_tool_web_filtered_frames(frames, *, model: str = '', lane: str = 'streaming_tool'):
    original_overrides = {}
    overrides_changed = False
    try:
        snapshot_getter = globals().get('_current_request_overrides_snapshot')
        original_snapshot = snapshot_getter() if callable(snapshot_getter) else {}
        original_overrides = dict(original_snapshot or {}) if isinstance(original_snapshot, dict) else {}
        filtered_snapshot = _agent_stream_tool_web_override_snapshot(original_overrides, lane=lane)
        if filtered_snapshot != original_overrides:
            setter = globals().get('_set_request_overrides')
            if callable(setter):
                setter(filtered_snapshot)
                overrides_changed = True
                try:
                    removed_keys = sorted(set(original_overrides.keys()) - set(filtered_snapshot.keys()))
                    app_logger.info('[AGENT_STREAM_TOOL_WEB_PARAMS_IGNORED] model=%s lane=%s keys=%s', model, lane, removed_keys)
                except Exception:
                    pass
    except Exception:
        try:
            app_logger.warning('[AGENT_STREAM_TOOL_WEB_PARAMS_FILTER_FAILED] model=%s lane=%s', model, lane)
        except Exception:
            pass
    try:
        for frame in frames:
            yield frame
    finally:
        if overrides_changed:
            try:
                setter = globals().get('_set_request_overrides')
                if callable(setter):
                    setter(original_overrides)
            except Exception:
                pass
