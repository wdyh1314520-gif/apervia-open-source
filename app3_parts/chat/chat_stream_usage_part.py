# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: pure usage parsing helpers shared by Chat Completions and Responses streaming.
# Loaded before chat_streaming_part.py, sharing the original global namespace.


def _usage_obj_value(obj, name: str, default=None):
    try:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)
    except Exception:
        return default


def _usage_optional_int(value):
    try:
        if value is None or value == '':
            return None
        n = int(float(value))
        if n < 0:
            return None
        return n
    except Exception:
        return None


def _usage_to_plain_dict(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    for attr in ('model_dump', 'dict'):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                data = fn()
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    out = {}
    for key in (
        'prompt_tokens', 'completion_tokens', 'total_tokens',
        'input_tokens', 'output_tokens', 'reasoning_tokens', 'cached_tokens', 'cache_write_tokens',
        'prompt_tokens_details', 'completion_tokens_details',
        'input_tokens_details', 'output_tokens_details',
    ):
        try:
            v = getattr(value, key, None)
        except Exception:
            v = None
        if v is not None:
            out[key] = v
    return out


def _usage_cached_token_candidates(usage_dict: dict | None = None) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []

    def add(source: str, value) -> None:
        n = _usage_optional_int(value)
        if n is not None:
            rows.append((source, int(n)))

    if not isinstance(usage_dict, dict):
        return rows
    add('usage.cached_tokens', usage_dict.get('cached_tokens'))
    for details_key in ('input_tokens_details', 'prompt_tokens_details'):
        details = _usage_to_plain_dict(usage_dict.get(details_key))
        if not details:
            continue
        add(f'{details_key}.cached_tokens', details.get('cached_tokens'))
        add(f'{details_key}.cached_input_tokens', details.get('cached_input_tokens'))
    return rows


def _usage_cache_write_token_candidates(usage_dict: dict | None = None) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []

    def add(source: str, value) -> None:
        n = _usage_optional_int(value)
        if n is not None:
            rows.append((source, int(n)))

    if not isinstance(usage_dict, dict):
        return rows
    add('usage.cache_write_tokens', usage_dict.get('cache_write_tokens'))
    add('usage.cache_creation_input_tokens', usage_dict.get('cache_creation_input_tokens'))
    for details_key in ('input_tokens_details', 'prompt_tokens_details'):
        details = _usage_to_plain_dict(usage_dict.get(details_key))
        if not details:
            continue
        add(f'{details_key}.cache_write_tokens', details.get('cache_write_tokens'))
        add(f'{details_key}.cache_creation_input_tokens', details.get('cache_creation_input_tokens'))
    return rows


def _extract_usage_from_stream_chunk(chunk) -> dict:
    usage = _usage_obj_value(chunk, 'usage', None)
    if usage is None:
        response = _usage_obj_value(chunk, 'response', None)
        usage = _usage_obj_value(response, 'usage', None)
    if usage is None:
        return {}
    usage_dict = _usage_to_plain_dict(usage)
    if not usage_dict:
        return {}
    prompt = _usage_optional_int(usage_dict.get('prompt_tokens'))
    completion = _usage_optional_int(usage_dict.get('completion_tokens'))
    total = _usage_optional_int(usage_dict.get('total_tokens'))
    input_tokens = _usage_optional_int(usage_dict.get('input_tokens'))
    output_tokens = _usage_optional_int(usage_dict.get('output_tokens'))
    if prompt is None:
        prompt = input_tokens
    if completion is None:
        completion = output_tokens
    if total is None and prompt is not None and completion is not None:
        total = int(prompt) + int(completion)
    if prompt is None and completion is None and total is None:
        return {}
    input_details = _usage_to_plain_dict(usage_dict.get('input_tokens_details'))
    prompt_tokens_details = _usage_to_plain_dict(usage_dict.get('prompt_tokens_details'))
    prompt_details = input_details or prompt_tokens_details
    completion_details = _usage_to_plain_dict(usage_dict.get('completion_tokens_details') or usage_dict.get('output_tokens_details'))
    reasoning = _usage_optional_int(usage_dict.get('reasoning_tokens'))
    if reasoning is None:
        reasoning = _usage_optional_int(completion_details.get('reasoning_tokens'))
    cached_candidates = _usage_cached_token_candidates(usage_dict)
    cached_source = ''
    cached = None
    if cached_candidates:
        cached_source, cached = max(cached_candidates, key=lambda row: int(row[1]))
    cache_write_candidates = _usage_cache_write_token_candidates(usage_dict)
    cache_write_source = ''
    cache_write = None
    if cache_write_candidates:
        cache_write_source, cache_write = max(cache_write_candidates, key=lambda row: int(row[1]))
    return {
        'input_tokens': int(prompt or 0),
        'output_tokens': int(completion or 0),
        'total_tokens': int(total or ((prompt or 0) + (completion or 0))),
        'reasoning_tokens': int(reasoning or 0),
        'cached_tokens': int(cached or 0),
        'cached_tokens_source': cached_source,
        'cached_tokens_candidates': cached_candidates[:8],
        'cache_write_tokens': int(cache_write or 0),
        'cache_write_tokens_source': cache_write_source,
        'cache_write_tokens_candidates': cache_write_candidates[:8],
        'raw': usage_dict,
    }


class StreamUsageTracker:
    """Track one turn's LLM usage snapshots without double-counting stream chunks."""

    def __init__(self, *, endpoint: str = ''):
        self.endpoint = str(endpoint or '')
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.reasoning_tokens = 0
        self.cached_tokens = 0
        self.cache_write_tokens = 0
        self.calls: list[dict] = []
        self.call_snapshots: dict[str, dict] = {}
        self.call_order: list[str] = []
        self.emitted_sig = ''

    def _recalculate_totals(self) -> None:
        input_total = output_total = total_total = reasoning_total = cached_total = cache_write_total = 0
        calls = []
        for key in self.call_order:
            item = self.call_snapshots.get(key)
            if not isinstance(item, dict):
                continue
            calls.append(item)
            input_total += max(0, int(item.get('input_tokens') or 0))
            output_total += max(0, int(item.get('output_tokens') or 0))
            total_total += max(0, int(item.get('total_tokens') or 0))
            reasoning_total += max(0, int(item.get('reasoning_tokens') or 0))
            cached_total += max(0, int(item.get('cached_tokens') or 0))
            cache_write_total += max(0, int(item.get('cache_write_tokens') or 0))
        self.calls = calls
        self.input_tokens = input_total
        self.output_tokens = output_total
        self.total_tokens = total_total or (input_total + output_total)
        self.reasoning_tokens = reasoning_total
        self.cached_tokens = cached_total
        self.cache_write_tokens = cache_write_total

    def record(self, usage_payload: dict | None, *, phase: str = '', model_name: str = '', endpoint: str = '', call_key: str = '') -> dict:
        if not isinstance(usage_payload, dict) or not usage_payload:
            return {}
        input_tokens = max(0, int(usage_payload.get('input_tokens') or 0))
        output_tokens = max(0, int(usage_payload.get('output_tokens') or 0))
        total_tokens = max(0, int(usage_payload.get('total_tokens') or (input_tokens + output_tokens) or 0))
        reasoning_tokens = max(0, int(usage_payload.get('reasoning_tokens') or 0))
        cached_tokens = max(0, int(usage_payload.get('cached_tokens') or 0))
        cached_tokens_source = str(usage_payload.get('cached_tokens_source') or '').strip()
        cached_tokens_candidates = usage_payload.get('cached_tokens_candidates') if isinstance(usage_payload.get('cached_tokens_candidates'), list) else []
        cache_write_tokens = max(0, int(usage_payload.get('cache_write_tokens') or 0))
        cache_write_tokens_source = str(usage_payload.get('cache_write_tokens_source') or '').strip()
        cache_write_tokens_candidates = usage_payload.get('cache_write_tokens_candidates') if isinstance(usage_payload.get('cache_write_tokens_candidates'), list) else []
        if total_tokens <= 0 and input_tokens <= 0 and output_tokens <= 0:
            return {}
        usage_call_key = str(call_key or '').strip()
        if not usage_call_key:
            usage_call_key = '|'.join([str(phase or ''), str(model_name or ''), str(endpoint or self.endpoint or ''), 'default'])

        prev = self.call_snapshots.get(usage_call_key)
        update_count = 1
        if isinstance(prev, dict):
            update_count = max(0, int(prev.get('snapshot_updates') or 0)) + 1
            prev_sig = (
                int(prev.get('input_tokens') or 0),
                int(prev.get('output_tokens') or 0),
                int(prev.get('total_tokens') or 0),
                int(prev.get('reasoning_tokens') or 0),
                int(prev.get('cached_tokens') or 0),
                int(prev.get('cache_write_tokens') or 0),
            )
            new_sig = (input_tokens, output_tokens, total_tokens, reasoning_tokens, cached_tokens, cache_write_tokens)
            if prev_sig == new_sig:
                return prev
        elif usage_call_key not in self.call_order:
            self.call_order.append(usage_call_key)

        call_payload = {
            'phase': str(phase or ''),
            'model': str(model_name or ''),
            'endpoint': str(endpoint or self.endpoint or ''),
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': total_tokens,
            'reasoning_tokens': reasoning_tokens,
            'cached_tokens': cached_tokens,
            'cached_tokens_source': cached_tokens_source,
            'cached_tokens_candidates': cached_tokens_candidates[:8],
            'cache_write_tokens': cache_write_tokens,
            'cache_write_tokens_source': cache_write_tokens_source,
            'cache_write_tokens_candidates': cache_write_tokens_candidates[:8],
            'snapshot_updates': update_count,
        }
        self.call_snapshots[usage_call_key] = call_payload
        self._recalculate_totals()
        return call_payload

    def payload(self) -> dict:
        total = max(0, int(self.total_tokens or 0))
        input_tokens = max(0, int(self.input_tokens or 0))
        output_tokens = max(0, int(self.output_tokens or 0))
        if total <= 0 and input_tokens <= 0 and output_tokens <= 0:
            return {}
        calls = [dict(x) for x in (self.calls or []) if isinstance(x, dict)]
        return {
            'input_tokens': input_tokens,
            'prompt_tokens': input_tokens,
            'output_tokens': output_tokens,
            'completion_tokens': output_tokens,
            'total_tokens': total or (input_tokens + output_tokens),
            'reasoning_tokens': max(0, int(self.reasoning_tokens or 0)),
            'cached_tokens': max(0, int(self.cached_tokens or 0)),
            'cache_write_tokens': max(0, int(self.cache_write_tokens or 0)),
            'calls': calls[-12:],
            'call_count': len(calls),
            'endpoint': self.endpoint,
        }

    def payload_signature(self, payload: dict | None = None) -> str:
        data = payload if isinstance(payload, dict) else self.payload()
        return json.dumps(
            {k: data.get(k) for k in ('input_tokens', 'output_tokens', 'total_tokens', 'reasoning_tokens', 'cached_tokens', 'cache_write_tokens', 'call_count')},
            sort_keys=True,
            ensure_ascii=False,
        )

    def mark_emitted_if_new(self, payload: dict | None = None) -> bool:
        sig = self.payload_signature(payload)
        if sig == str(self.emitted_sig or ''):
            return False
        self.emitted_sig = sig
        return True
