# Split from app3_parts/chat/chat_responses_adapter_part.py.
# Purpose: Responses SSE reasoning and reasoning request helpers.
# Loaded by chat_responses_adapter_part.py via _exec_split_file(...), sharing app3.py globals.

def _responses_event_name(value: str = '', payload=None) -> str:
    if value:
        return str(value or '').strip()
    if isinstance(payload, dict):
        return str(payload.get('type') or payload.get('event') or '').strip()
    return ''


def _responses_text_from_reasoning_value(value) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            text = _responses_text_from_reasoning_value(item)
            if text:
                parts.append(text)
        return ''.join(parts)
    if isinstance(value, dict):
        # Responses reasoning can be shaped as:
        # {delta: "..."}, {part: {text: "..."}},
        # {summary: [{text: "..."}]}, or relay-specific reasoning/thinking fields.
        for key in ('delta', 'text', 'value', 'output_text', 'reasoning_content', 'reasoningContent', 'reasoning_text', 'reasoningText', 'thinking_text', 'thinkingText', 'summary_text', 'summaryText'):
            text = _responses_text_from_reasoning_value(value.get(key))
            if text:
                return text
        content_value = value.get('content')
        if isinstance(content_value, str):
            return content_value
        if isinstance(content_value, list):
            parts = []
            for block in content_value:
                if isinstance(block, dict):
                    block_type = str(block.get('type') or block.get('kind') or '').strip().lower()
                    if block_type and not any(mark in block_type for mark in ('reasoning', 'thinking', 'think', 'summary')):
                        continue
                text = _responses_text_from_reasoning_value(block)
                if text:
                    parts.append(text)
            if parts:
                return ''.join(parts)
        for key in ('part', 'item', 'summary', 'reasoning', 'thinking', 'think'):
            text = _responses_text_from_reasoning_value(value.get(key))
            if text:
                return text
        return ''
    for key in ('delta', 'text', 'content', 'value', 'reasoning_content', 'reasoning', 'reasoning_text', 'thinking', 'think'):
        try:
            text = _responses_text_from_reasoning_value(getattr(value, key, None))
        except Exception:
            text = ''
        if text:
            return text
    return ''


def _responses_sse_event_is_reasoning(payload, event_name: str = '') -> bool:
    event_type = _responses_event_name(event_name, payload).lower()
    if any(mark in event_type for mark in ('reasoning', 'thinking', 'think')):
        return True
    if isinstance(payload, dict):
        payload_type = str(payload.get('type') or payload.get('kind') or '').strip().lower()
        if any(mark in payload_type for mark in ('reasoning', 'thinking', 'think')):
            return True
        item = payload.get('item') if isinstance(payload.get('item'), dict) else None
        if item is not None:
            item_type = str(item.get('type') or item.get('kind') or '').strip().lower()
            if any(mark in item_type for mark in ('reasoning', 'thinking', 'think')):
                return True
    return False


def _responses_reasoning_event_key_from_sse_payload(payload, event_name: str = '') -> str:
    """Return a stable provider/native reasoning item key for UI grouping.

    Responses streams expose reasoning text as many small deltas.  UI rows must
    not be grouped by sentence or by arrival timing when the provider gives a
    real item identity.  This helper keeps all deltas that belong to the same
    Responses reasoning item/summary part under one stable key.  If a relay does
    not expose any stable item/index field, return an empty string so the
    frontend can fall back to its old continuous-stream heuristics.
    """
    if payload is None:
        return ''
    if not isinstance(payload, dict):
        try:
            payload = payload.model_dump()
        except Exception:
            try:
                payload = dict(payload)
            except Exception:
                return ''
    event_type = _responses_event_name(event_name, payload).strip().lower()
    if not _responses_sse_event_is_reasoning(payload, event_type):
        return ''

    def _clean(v, limit=120):
        try:
            text = str(v or '').strip()
        except Exception:
            text = ''
        if not text:
            return ''
        return re.sub(r'[^a-zA-Z0-9_.:\-]+', '_', text)[:limit]

    def _first(*vals):
        for v in vals:
            text = _clean(v)
            if text:
                return text
        return ''

    item = payload.get('item') if isinstance(payload.get('item'), dict) else None
    output_item = payload.get('output_item') if isinstance(payload.get('output_item'), dict) else None
    part = payload.get('part') if isinstance(payload.get('part'), dict) else None

    # Completed response snapshots can hide the reasoning item inside response.output.
    if item is None:
        try:
            response_obj = payload.get('response') if isinstance(payload.get('response'), dict) else None
            outputs = response_obj.get('output') if isinstance(response_obj, dict) else payload.get('output')
            if isinstance(outputs, list):
                for candidate in outputs:
                    if isinstance(candidate, dict) and _responses_item_is_reasoning(candidate):
                        item = candidate
                        break
        except Exception:
            item = None

    item_id = _first(
        payload.get('item_id'), payload.get('itemId'),
        payload.get('output_item_id'), payload.get('outputItemId'),
        item.get('id') if isinstance(item, dict) else '',
        output_item.get('id') if isinstance(output_item, dict) else '',
    )
    part_id = _first(
        payload.get('part_id'), payload.get('partId'),
        part.get('id') if isinstance(part, dict) else '',
    )

    # Do not include delta_index; every text delta of the same item should merge.
    output_index = _first(payload.get('output_index'), payload.get('outputIndex'))
    content_index = _first(payload.get('content_index'), payload.get('contentIndex'))
    summary_index = _first(payload.get('summary_index'), payload.get('summaryIndex'))
    part_index = _first(payload.get('part_index'), payload.get('partIndex'))

    family = 'reasoning'
    if 'reasoning_summary_text' in event_type or 'summary_text' in event_type:
        family = 'reasoning_summary_text'
    elif 'reasoning_text' in event_type:
        family = 'reasoning_text'
    elif 'thinking_text' in event_type or 'thinking' in event_type or 'think' in event_type:
        family = 'thinking_text'
    elif isinstance(item, dict):
        item_type = str(item.get('type') or item.get('kind') or '').strip().lower()
        if 'summary' in item_type:
            family = 'reasoning_summary_text'
        elif 'thinking' in item_type or 'think' in item_type:
            family = 'thinking_text'

    parts = [f'responses_reasoning:{family}']
    if item_id:
        parts.append(f'item:{item_id}')
    if output_index:
        parts.append(f'out:{output_index}')
    if summary_index:
        parts.append(f'summary:{summary_index}')
    if content_index:
        parts.append(f'content:{content_index}')
    if part_id:
        parts.append(f'part:{part_id}')
    elif part_index:
        parts.append(f'part:{part_index}')

    # At least one provider identity/index is required.  Event type alone would
    # wrongly glue separate reasoning rounds together.
    if len(parts) <= 1:
        return ''
    return '|'.join(parts)[:700]


def _responses_extract_reasoning_delta_from_sse_payload(payload, event_name: str = '') -> str:
    if payload is None:
        return ''
    if not isinstance(payload, dict):
        try:
            payload = payload.model_dump()
        except Exception:
            try:
                payload = dict(payload)
            except Exception:
                return ''
    event_type = _responses_event_name(event_name, payload).strip()
    event_low = event_type.lower()

    # Structural item/part events describe the shape of a Responses output item.
    # They are not text deltas.  Real reasoning text should arrive through
    # response.reasoning_summary_text.delta / response.reasoning_text.delta, or
    # as a snapshot handled separately below.
    if event_low in {
        'response.output_item.added',
        'response.output_item.done',
        'response.reasoning_summary_part.added',
        'response.reasoning_summary_part.done',
        'response.content_part.added',
        'response.content_part.done',
    }:
        return ''

    # `*.done` / `response.completed` events often contain a full accumulated
    # reasoning summary. Treat them as terminators, not deltas, otherwise the UI
    # can show duplicated reasoning after already streaming the delta pieces.
    if event_low in {'response.completed', 'response.done'} or (('reasoning' in event_low or 'thinking' in event_low or 'think' in event_low) and (event_low.endswith('.done') or event_low.endswith('_done') or event_low.endswith('.completed'))):
        return ''

    reasoning_event = _responses_sse_event_is_reasoning(payload, event_type)
    if reasoning_event:
        # OpenAI Responses reasoning summary events commonly carry the text in
        # delta, part.text, or summary blocks. Compatible relays may use
        # reasoning_content / thinking fields instead.
        for key in ('delta', 'text', 'content', 'value', 'reasoning_content', 'reasoningContent', 'reasoning_text', 'reasoningText', 'thinking', 'think', 'thinking_text', 'thinkingText', 'summary_text', 'summaryText'):
            text = _responses_text_from_reasoning_value(payload.get(key))
            if text:
                return text
        for key in ('part', 'summary', 'item'):
            text = _responses_text_from_reasoning_value(payload.get(key))
            if text:
                return text

    for key in ('reasoning_content', 'reasoningContent', 'reasoning_text', 'reasoningText', 'thinking', 'think', 'thinking_text', 'thinkingText'):
        text = _responses_text_from_reasoning_value(payload.get(key))
        if text:
            return text

    try:
        choices = payload.get('choices') or []
        if choices:
            first = choices[0] or {}
            delta_obj = first.get('delta') or {}
            if isinstance(delta_obj, dict):
                for key in ('reasoning_content', 'reasoningContent', 'reasoning', 'reasoning_text', 'reasoningText', 'thinking', 'think'):
                    text = _responses_text_from_reasoning_value(delta_obj.get(key))
                    if text:
                        return text
    except Exception:
        pass

    # Some providers put reasoning blocks into content arrays.
    for container_key in ('content', 'output', 'item'):
        container = payload.get(container_key)
        if isinstance(container, dict):
            container = [container]
        if not isinstance(container, list):
            continue
        parts = []
        for block in container:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get('type') or block.get('kind') or '').strip().lower()
            if any(mark in block_type for mark in ('reasoning', 'thinking', 'think')):
                text = _responses_text_from_reasoning_value(block)
                if text:
                    parts.append(text)
        if parts:
            return ''.join(parts)

    return ''



def _responses_reasoning_dedupe_key(text: str = '') -> str:
    raw = str(text or '').strip()
    if not raw:
        return ''
    try:
        raw = re.sub(r'\s+', ' ', raw)
    except Exception:
        raw = ' '.join(raw.split())
    return raw[:20000]


def _responses_reasoning_control_label(text: str = '') -> bool:
    """Return True for Responses reasoning metadata labels, not summary text.

    Some OpenAI-compatible relays place the requested summary mode (for example
    `detailed`) inside reasoning item snapshots.  That value is request/output
    structure metadata; it is not a reasoning-summary text delta.  Keep real
    `response.reasoning_summary_text.delta` content raw, but do not fabricate a
    reasoning panel from these control labels when no actual text was exposed.
    """
    raw = str(text or '').strip().lower()
    if not raw:
        return False
    try:
        raw = re.sub(r'\s+', ' ', raw)
    except Exception:
        raw = ' '.join(raw.split())
    return raw in {'auto', 'concise', 'detailed', 'summary_text', 'reasoning', 'thinking', 'think'}


def _responses_reasoning_suffix_delta(snapshot: str = '', already: str = '', *, snapshot_mode: bool = False) -> str:
    full = str(snapshot or '')
    prev = str(already or '')
    if not full:
        return ''
    if not prev:
        return full
    if full == prev:
        return ''
    if full.startswith(prev):
        return full[len(prev):]
    full_key = _responses_reasoning_dedupe_key(full)
    prev_key = _responses_reasoning_dedupe_key(prev)
    if full_key and prev_key and full_key == prev_key:
        return ''
    # Snapshot/done events can repeat text that was already streamed as deltas.
    # Only apply the reverse containment guard to snapshot-style events, not raw
    # delta chunks, so repeated words inside genuine streaming text are preserved.
    if snapshot_mode and full_key and prev_key and full_key in prev_key:
        return ''
    # If the provider sends a completed summary after streaming the same summary
    # in deltas, do not append the full snapshot again.  We prefer avoiding visible
    # duplication over trying to splice normalized text heuristically.
    if full_key and prev_key and prev_key in full_key:
        return ''
    return full


def _responses_item_is_reasoning(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    typ = str(obj.get('type') or obj.get('kind') or obj.get('role') or '').strip().lower()
    if any(mark in typ for mark in ('reasoning', 'thinking', 'think')):
        return True
    for key in ('summary', 'reasoning', 'reasoning_content', 'reasoningContent', 'reasoning_text', 'reasoningText', 'thinking', 'think', 'thinking_text', 'thinkingText', 'summary_text', 'summaryText'):
        if key in obj and _responses_text_from_reasoning_value(obj.get(key)):
            return True
    return False


def _responses_collect_reasoning_snapshots_from_obj(obj, out: list[str] | None = None) -> list[str]:
    out = out if isinstance(out, list) else []
    if obj is None:
        return out
    if not isinstance(obj, dict):
        try:
            obj = obj.model_dump()
        except Exception:
            return out
    if _responses_item_is_reasoning(obj):
        for key in ('summary', 'reasoning', 'reasoning_content', 'reasoningContent', 'reasoning_text', 'reasoningText', 'thinking', 'think', 'thinking_text', 'thinkingText', 'summary_text', 'summaryText', 'content', 'text'):
            text = _responses_text_from_reasoning_value(obj.get(key))
            if text and not _responses_reasoning_control_label(text):
                out.append(text)
                break
    for key in ('item', 'output_item', 'part'):
        child = obj.get(key)
        if isinstance(child, dict):
            _responses_collect_reasoning_snapshots_from_obj(child, out)
    for key in ('output', 'outputs', 'content'):
        value = obj.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _responses_collect_reasoning_snapshots_from_obj(item, out)
    response_obj = obj.get('response') if isinstance(obj.get('response'), dict) else None
    if response_obj is not None:
        _responses_collect_reasoning_snapshots_from_obj(response_obj, out)
    return out


def _responses_extract_reasoning_snapshot_from_sse_payload(payload, event_name: str = '') -> str:
    """Extract completed reasoning summaries from snapshot-style Responses events.

    Some relays do not stream `response.reasoning_summary_text.delta`; instead
    they only place the completed reasoning item in `response.output_item.done`
    or in `response.completed.response.output`.  This helper is intentionally
    separate from the delta extractor so callers can dedupe against already
    streamed reasoning and keep tool-progress panels untouched.
    """
    if payload is None:
        return ''
    if not isinstance(payload, dict):
        try:
            payload = payload.model_dump()
        except Exception:
            try:
                payload = dict(payload)
            except Exception:
                return ''
    event_type = _responses_event_name(event_name, payload).strip().lower()
    snapshot_like = bool(
        event_type in {
            'response.output_item.done',
            'response.completed',
            'response.done',
            'response.reasoning_summary_text.done',
            'response.reasoning_text.done',
            'response.thinking_text.done',
        }
        or event_type.endswith('.reasoning_summary_text.done')
        or event_type.endswith('.reasoning_text.done')
        or event_type.endswith('.thinking_text.done')
        or event_type.endswith('.completed')
    )
    if not snapshot_like and not _responses_sse_event_is_reasoning(payload, event_type):
        return ''
    parts = []
    seen = set()
    for text in _responses_collect_reasoning_snapshots_from_obj(payload, []):
        key = _responses_reasoning_dedupe_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        parts.append(str(text or ''))
    return ''.join(parts)

def _responses_extract_delta_from_sse_payload(payload, event_name: str = '') -> str:
    if payload is None:
        return ''
    if not isinstance(payload, dict):
        try:
            payload = payload.model_dump()
        except Exception:
            try:
                payload = dict(payload)
            except Exception:
                return ''
    event_type = str(event_name or payload.get('type') or payload.get('event') or '').strip()
    if _responses_sse_event_is_reasoning(payload, event_type):
        return ''
    if event_type in {
        'response.output_text.delta',
        'response.refusal.delta',
        'output_text.delta',
        'text.delta',
    }:
        delta = payload.get('delta')
        if delta is None:
            delta = payload.get('text') or payload.get('content') or payload.get('value')
        return str(delta or '')
    for key in ('delta', 'text_delta', 'content_delta'):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    try:
        choices = payload.get('choices') or []
        if choices:
            first = choices[0] or {}
            delta_obj = first.get('delta') or {}
            if isinstance(delta_obj, dict):
                content = delta_obj.get('content') or delta_obj.get('text') or ''
                if isinstance(content, list):
                    parts = []
                    for item in content:
                        if isinstance(item, dict):
                            txt = item.get('text') or item.get('content') or ''
                            if txt:
                                parts.append(str(txt))
                        elif item:
                            parts.append(str(item))
                    return ''.join(parts)
                if content:
                    return str(content)
            text = first.get('text') or ''
            if text:
                return str(text)
    except Exception:
        pass
    return ''


def _responses_sse_payload_is_error(payload, event_name: str = '') -> tuple[bool, str]:
    event_type = str(event_name or '').strip().lower()
    if event_type in {'error', 'response.error'}:
        if isinstance(payload, dict):
            err = payload.get('error') or payload.get('message') or payload
            return True, str(err or '')
        return True, str(payload or '')
    if isinstance(payload, dict) and payload.get('error'):
        return True, str(payload.get('error') or '')
    return False, ''


def _responses_normalize_thinking_type_for_request(value: str = '') -> str:
    raw = str(value or '').strip().lower()
    aliases = {
        'x-high': 'xhigh',
        'extra_high': 'xhigh',
        'extra-high': 'xhigh',
        'very_high': 'xhigh',
        'very-high': 'xhigh',
        'on': 'enabled',
        'true': 'enabled',
        'yes': 'enabled',
        'enable': 'enabled',
        'enabled': 'enabled',
        'off': 'disabled',
        'false': 'disabled',
        'no': 'disabled',
        'disable': 'disabled',
        'disabled': 'disabled',
        'none': 'disabled',
    }
    return aliases.get(raw, raw or 'auto')


def _responses_thinking_type_for_main_chat() -> str:
    """Legacy helper kept for older call sites.

    Responses mode must not use CHAT_THINKING_TYPE for reasoning effort anymore;
    use _responses_reasoning_effort_for_request() instead.  Keeping this helper
    avoids touching unrelated Chat Completions / planner logic.
    """
    try:
        getter = globals().get('_thinking_type_for_role')
        if callable(getter):
            value = str(getter('main_chat') or getter('chat') or '').strip()
            if value:
                return _responses_normalize_thinking_type_for_request(value)
    except Exception:
        pass
    try:
        getter = globals().get('_get_request_override')
        if callable(getter):
            value = str(getter('CHAT_THINKING_TYPE', '') or '').strip()
            if value:
                normalizer = globals().get('_normalize_thinking_type')
                if callable(normalizer):
                    try:
                        value = str(normalizer(value) or value).strip()
                    except Exception:
                        pass
                return _responses_normalize_thinking_type_for_request(value)
    except Exception:
        pass
    return 'auto'


def _responses_normalize_reasoning_effort(value: str = '') -> str:
    raw = str(value or '').strip().lower().replace('-', '_')
    aliases = {
        '': 'auto',
        'default': 'auto',
        'automatic': 'auto',
        '自动': 'auto',
        'off': 'none',
        'false': 'none',
        'no': 'none',
        'disable': 'none',
        'disabled': 'none',
        '关闭': 'none',
        'none': 'none',
        'minimal': 'minimal',
        'mini': 'minimal',
        '最低': 'minimal',
        'low': 'low',
        '低': 'low',
        'medium': 'medium',
        'mid': 'medium',
        'normal': 'medium',
        '中': 'medium',
        'high': 'high',
        'hight': 'high',
        '高': 'high',
        'enabled': 'high',
        'enable': 'high',
        'on': 'high',
        'true': 'high',
        'yes': 'high',
        'xhigh': 'xhigh',
        'x_high': 'xhigh',
        'extra_high': 'xhigh',
        'very_high': 'xhigh',
        'max': 'max',
        '极高': 'xhigh',
    }
    return aliases.get(raw, 'auto')


def _responses_reasoning_effort_for_request() -> str:
    """Read the Responses-only effort override.

    This intentionally does not read CHAT_THINKING_TYPE, TOOL_PREFETCH_THINKING_TYPE
    or QUERY_GENERATION_THINKING_TYPE, so changing Responses effort cannot affect
    Chat Completions, tool prefetch, query planning, title generation, or legacy
    orchestrator behavior.
    """
    try:
        getter = globals().get('_get_request_override')
        if callable(getter):
            value = str(getter('RESPONSES_REASONING_EFFORT', '') or '').strip()
            if value:
                return _responses_normalize_reasoning_effort(value)
    except Exception:
        pass
    return 'auto'


def _responses_normalize_reasoning_summary(value: str = '') -> str:
    raw = str(value or '').strip().lower().replace('-', '_')
    if raw in {'0', 'false', 'no', 'off', 'disable', 'disabled', 'none', 'null', '关闭'}:
        return 'off'
    if raw in {'concise', 'detailed'}:
        return raw
    return 'auto'


def _responses_reasoning_summary_for_request() -> str:
    try:
        getter = globals().get('_get_request_override')
        if callable(getter):
            value = str(getter('RESPONSES_REASONING_SUMMARY', '') or '').strip()
            if value:
                return _responses_normalize_reasoning_summary(value)
    except Exception:
        pass
    try:
        return _responses_normalize_reasoning_summary(app_getenv('RESPONSES_REASONING_SUMMARY', 'detailed'))
    except Exception:
        return 'detailed'


def _responses_normalize_reasoning_context(value: str = '') -> str:
    raw = str(value or '').strip().lower().replace('-', '_')
    if raw in {'current', 'current_turn', 'turn', '本轮'}:
        return 'current_turn'
    if raw in {'all', 'all_turns', 'persistent', '全部轮次'}:
        return 'all_turns'
    return 'auto'


def _responses_reasoning_context_for_request() -> str:
    try:
        getter = globals().get('_get_request_override')
        if callable(getter):
            value = str(getter('RESPONSES_REASONING_CONTEXT', '') or '').strip()
            if value:
                return _responses_normalize_reasoning_context(value)
    except Exception:
        pass
    return 'auto'


def _responses_model_supports_reasoning_context(model: str = '') -> bool:
    raw = str(model or '').strip().lower()
    if not raw:
        return False
    model_id = raw.rsplit('/', 1)[-1]
    if model_id in {'sol', 'terra', 'luna'}:
        return True
    return bool(re.match(r'^gpt[-_.]?5[._-]?6(?:$|[-_.])', model_id))


def _responses_extra_body_with_reasoning_summary(extra_body: dict | None = None, *, model: str = '') -> dict:
    """Build a Codex/OpenAI-compatible Responses reasoning payload.

    Responses reasoning effort is now controlled only by the Responses-specific
    RESPONSES_REASONING_EFFORT request override.  It does not consume the global
    CHAT_THINKING_TYPE switch, so changing this setting cannot affect Chat
    Completions or the tool/query planner roles.

    Behavior:
    - keep any caller-provided extra_body except chat-only fields;
    - remove relay-only `thinking.type` from Responses requests;
    - add `reasoning.effort` only for explicit none/minimal/low/medium/high/xhigh/max;
    - never downgrade max or suppress none; upstream errors remain visible;
    - set `reasoning.summary` to auto/concise/detailed, or omit it for off;
    - set `reasoning.context` only for GPT-5.6 Sol/Terra/Luna models.
    """
    out = dict(extra_body or {}) if isinstance(extra_body, dict) else {}

    # Chat-completions compatibility fields should not leak into Responses.
    out.pop('thinking', None)
    out.pop('reasoning_effort', None)

    effort = _responses_reasoning_effort_for_request()
    effort_map = {
        'none': 'none',
        'minimal': 'minimal',
        'low': 'low',
        'medium': 'medium',
        'high': 'high',
        'xhigh': 'xhigh',
        'max': 'max',
    }
    normalized_effort = effort_map.get(str(effort or '').strip().lower(), '')

    reasoning = out.get('reasoning') if isinstance(out.get('reasoning'), dict) else {}
    reasoning = dict(reasoning or {})
    if normalized_effort:
        reasoning['effort'] = normalized_effort

    summary_value = _responses_reasoning_summary_for_request()
    if summary_value == 'off':
        reasoning.pop('summary', None)
    else:
        reasoning['summary'] = summary_value

    if _responses_model_supports_reasoning_context(model):
        reasoning['context'] = _responses_reasoning_context_for_request()
    else:
        reasoning.pop('context', None)

    if reasoning:
        out['reasoning'] = reasoning
    else:
        out.pop('reasoning', None)
    return out
