# pure stream chunk text/reasoning extraction helpers.


def _partial_tag_suffix_len(text: str, tags: tuple[str, ...]) -> int:
    raw = str(text or '')
    low = raw.lower()
    best = 0
    for tag in tags:
        tag_low = str(tag or '').lower()
        max_len = min(len(low), len(tag_low) - 1)
        for size in range(max_len, 0, -1):
            if low.endswith(tag_low[:size]):
                best = max(best, size)
                break
    return best


class ThinkTagSplitter:
    """Stateful splitter for streamed <think> tags scoped to one chat turn."""

    def __init__(self):
        self.mode = 'answer'
        self.carry = ''

    def split(self, text: str, flush: bool = False) -> tuple[str, str, str]:
        raw = str(text or '')
        if not raw and not (flush and self.carry):
            return '', '', ''
        merged = str(self.carry or '') + raw
        self.carry = ''
        reasoning_parts = []
        answer_parts = []
        mode = str(self.mode or 'answer')
        pos = 0
        while pos < len(merged):
            low = merged.lower()
            if mode == 'answer':
                idx = low.find('<think>', pos)
                if idx < 0:
                    tail_keep = 0 if flush else _partial_tag_suffix_len(merged[pos:], ('<think>',))
                    end = len(merged) - tail_keep
                    if end > pos:
                        answer_parts.append(merged[pos:end])
                    if tail_keep > 0:
                        self.carry = merged[-tail_keep:]
                    pos = len(merged)
                    break
                if idx > pos:
                    answer_parts.append(merged[pos:idx])
                pos = idx + len('<think>')
                mode = 'reasoning'
                continue
            idx = low.find('</think>', pos)
            if idx < 0:
                tail_keep = 0 if flush else _partial_tag_suffix_len(merged[pos:], ('</think>',))
                end = len(merged) - tail_keep
                if end > pos:
                    reasoning_parts.append(merged[pos:end])
                if tail_keep > 0:
                    self.carry = merged[-tail_keep:]
                pos = len(merged)
                break
            if idx > pos:
                reasoning_parts.append(merged[pos:idx])
            pos = idx + len('</think>')
            mode = 'answer'
        self.mode = mode
        source = 'think_tag' if reasoning_parts else ''
        return ''.join(reasoning_parts), ''.join(answer_parts), source


def _coerce_stream_piece(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return ''.join(_coerce_stream_piece(v) for v in value)
    if isinstance(value, dict):
        for key in ('text', 'content', 'value', 'reasoning_content', 'reasoning', 'reasoning_text', 'thinking', 'think'):
            part = _coerce_stream_piece(value.get(key))
            if part:
                return part
        return ""
    for key in ('text', 'content', 'value', 'reasoning_content', 'reasoning', 'reasoning_text', 'thinking', 'think'):
        try:
            part = _coerce_stream_piece(getattr(value, key, None))
        except Exception:
            part = ""
        if part:
            return part
    return ""


def _stream_holder_value(holder, name: str):
    if holder is None:
        return None
    if isinstance(holder, dict):
        return holder.get(name)
    return getattr(holder, name, None)


def _extract_text_from_content_blocks(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, (list, tuple)):
        return ""
    parts = []
    for block in value:
        if isinstance(block, str):
            parts.append(block)
            continue
        if isinstance(block, dict):
            block_type = str(block.get('type') or block.get('kind') or '').strip().lower()
            if 'reason' in block_type or 'think' in block_type:
                continue
            text = _coerce_stream_piece(block.get('text') or block.get('content'))
        else:
            block_type = str(getattr(block, 'type', None) or getattr(block, 'kind', None) or '').strip().lower()
            if 'reason' in block_type or 'think' in block_type:
                continue
            text = _coerce_stream_piece(getattr(block, 'text', None) or getattr(block, 'content', None))
        if text:
            parts.append(text)
    return ''.join(parts)


def _extract_reasoning_from_content_blocks(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return ""
    if not isinstance(value, (list, tuple)):
        return ""
    parts = []
    for block in value:
        if isinstance(block, dict):
            block_type = str(block.get('type') or block.get('kind') or '').strip().lower()
            if 'reason' in block_type or 'think' in block_type:
                text = _coerce_stream_piece(block.get('text') or block.get('content') or block.get('reasoning_content') or block.get('reasoning'))
                if text:
                    parts.append(text)
        else:
            block_type = str(getattr(block, 'type', None) or getattr(block, 'kind', None) or '').strip().lower()
            if 'reason' in block_type or 'think' in block_type:
                text = _coerce_stream_piece(
                    getattr(block, 'text', None)
                    or getattr(block, 'content', None)
                    or getattr(block, 'reasoning_content', None)
                    or getattr(block, 'reasoning', None)
                )
                if text:
                    parts.append(text)
    return ''.join(parts)


def _extract_stream_text(chunk):
    try:
        choices = getattr(chunk, "choices", None)
        if not choices:
            return ""
        c0 = choices[0]
        for holder in (getattr(c0, 'delta', None), getattr(c0, 'message', None), c0):
            if holder is None:
                continue
            content_value = _stream_holder_value(holder, 'content')
            if isinstance(content_value, str):
                txt = _coerce_stream_piece(content_value)
                if txt:
                    return txt
            txt = _extract_text_from_content_blocks(content_value)
            if txt:
                return txt
            txt = _coerce_stream_piece(_stream_holder_value(holder, 'text'))
            if txt:
                return txt
    except Exception:
        return ""
    return ""


def _extract_stream_reasoning(chunk):
    try:
        choices = getattr(chunk, "choices", None)
        if not choices:
            return ""
        c0 = choices[0]
        for holder in (getattr(c0, 'delta', None), getattr(c0, 'message', None), c0):
            if holder is None:
                continue
            for key in ('reasoning_content', 'reasoningContent', 'reasoning', 'reasoning_text', 'reasoningText', 'thinking', 'think'):
                txt = _coerce_stream_piece(_stream_holder_value(holder, key))
                if txt:
                    return txt
            txt = _extract_reasoning_from_content_blocks(_stream_holder_value(holder, 'content'))
            if txt:
                return txt
    except Exception:
        return ""
    return ""
