# chat message to Responses input conversion helpers.

def _responses_input_content_from_chat_content(content, *, role: str = 'user'):
    role = str(role or 'user').strip().lower()

    def text_part(text: str) -> dict | None:
        text = str(text or '').strip()
        if not text:
            return None
        if role == 'assistant':
            return {'type': 'output_text', 'text': text}
        return {'type': 'input_text', 'text': text}

    if isinstance(content, str):
        if role == 'assistant':
            part = text_part(content)
            return [part] if part else ''
        return content
    if isinstance(content, list):
        out = []
        for item in content:
            if isinstance(item, str):
                part = text_part(item)
                if part:
                    out.append(part)
                continue
            if not isinstance(item, dict):
                part = text_part(str(item or '').strip())
                if part:
                    out.append(part)
                continue
            typ = str(item.get('type') or '').strip().lower()
            if typ in {'text', 'input_text', 'output_text'}:
                part = text_part(str(item.get('text') or item.get('output_text') or '').strip())
                if part:
                    out.append(part)
                continue
            if typ == 'refusal':
                text = str(item.get('refusal') or item.get('text') or '').strip()
                if text:
                    if role == 'assistant':
                        out.append({'type': 'refusal', 'refusal': text})
                    else:
                        part = text_part(text)
                        if part:
                            out.append(part)
                continue
            if typ == 'image_url':
                if role == 'assistant':
                    continue
                url = ''
                try:
                    img = item.get('image_url') or {}
                    url = str((img or {}).get('url') or '').strip()
                except Exception:
                    url = ''
                if url:
                    out.append({'type': 'input_image', 'image_url': url, 'detail': 'auto'})
                continue
            if typ == 'input_image':
                if role == 'assistant':
                    continue
                image_url = str(item.get('image_url') or item.get('url') or '').strip()
                file_id = str(item.get('file_id') or '').strip()
                detail = str(item.get('detail') or 'auto').strip() or 'auto'
                if image_url or file_id:
                    img = {'type': 'input_image', 'detail': detail}
                    if image_url:
                        img['image_url'] = image_url
                    if file_id:
                        img['file_id'] = file_id
                    out.append(img)
                continue
            part = text_part(str(item.get('text') or item.get('content') or '').strip())
            if part:
                out.append(part)
        return out or ''
    if isinstance(content, dict):
        text = str(content.get('text') or content.get('content') or content.get('answer') or '').strip()
        if role == 'assistant':
            part = text_part(text)
            return [part] if part else ''
        return text
    return str(content or '')


def _responses_failed_assistant_history_message(message: dict | None = None) -> bool:
    row = message if isinstance(message, dict) else {}
    if str(row.get('role') or '').strip().lower() != 'assistant':
        return False
    text = _responses_instruction_text_from_content(row.get('content'))
    compact = str(text or '').strip().lower()
    return compact.startswith('ai生成失败') or (
        'responses api error' in compact
        and ('responses_native_agent' in compact or 'runtimeerror' in compact)
    )


def _responses_instruction_text_from_content(content) -> str:
    if isinstance(content, str):
        return content.strip()
    try:
        helper = globals().get('_message_to_text_for_budget')
        if callable(helper):
            text = helper({'role': 'system', 'content': content}, include_images=False, include_image_text=False)
            text = str(text or '').strip()
            if text:
                return text
    except Exception:
        pass
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get('type') == 'text' and item.get('text'):
                parts.append(str(item.get('text') or '').strip())
            elif item.get('text'):
                parts.append(str(item.get('text') or '').strip())
        return '\n'.join(x for x in parts if x).strip()
    if isinstance(content, dict):
        return str(content.get('text') or content.get('content') or content.get('answer') or '').strip()
    return str(content or '').strip()


_RESPONSES_STABLE_INSTRUCTION_PREFIX = (
    "System instructions:\n"
    "Follow the user's language and instructions. Use provided tool_evidence_v1 blocks as factual evidence. "
    "When tools are available, choose and call them only when useful; otherwise answer directly and naturally."
)

_PROMPT_CACHE_RUNTIME_TAIL_CONTEXT_KINDS = {
    'agent_stream_runtime',
    'runtime_time',
    'runtime_location_visibility',
    'runtime_model',
    'agent_stream_image_index',
    'agent_stream_image_payload_notice',
    'sandbox_skill_runtime',
    'weather_ctx',
    'kb_recall',
    'kb_doc_brief',
    'kb_existing_file_answer',
    'agent_stream_file_loop_hint',
    'image_generation_failure_context',
    'orchestrator_soft_hint',
    'tool_runtime',
    'web',
    'tool_evidence',
    'agent_final_fact_bridge',
    'agent_final_memory_guard',
    'agent_final_file_delivery_guard',
    'agent_final_grounding_guard',
}

_RESPONSES_DYNAMIC_CONTEXT_KINDS = set(_PROMPT_CACHE_RUNTIME_TAIL_CONTEXT_KINDS)

_RESPONSES_STABLE_INPUT_CONTEXT_KINDS = {
    'file_recall',
    'file_memory',
    'file_edit_audit',
    'file_delivery_soft_prompt',
    'kb_memory',
    'generated_artifact_context',
    'prompt_cache_chat_history_prefix',
}


def _responses_stable_context_input_enabled() -> bool:
    getter = globals().get('_prompt_cache_app_getenv')
    raw = ''
    if callable(getter):
        try:
            raw = str(getter('APP3_RESPONSES_STABLE_CONTEXT_PLACEMENT', '') or '').strip().lower()
        except Exception:
            raw = ''
    if raw in {'instructions', 'instruction', 'top', 'legacy', '0', 'false', 'off', 'no'}:
        return False
    if raw in {'input', 'messages', 'message', '1', 'true', 'on', 'yes'}:
        return True
    try:
        wants_cache = globals().get('_prompt_cache_runtime_wants_cache')
        return bool(wants_cache()) if callable(wants_cache) else False
    except Exception:
        return False


def _responses_text_has_stable_file_context_marker(text: str = '') -> bool:
    text = str(text or '')
    if not text:
        return False
    file_context_markers = (
        '文本附件正文',
        'sandbox_import_files',
        'sandbox_read_file',
        'file_recall',
        'file_memory',
    )
    return any(marker in text for marker in file_context_markers)


def _responses_untyped_context_looks_dynamic(text: str = '') -> bool:
    text = str(text or '').strip()
    if not text:
        return False
    if _responses_text_has_stable_file_context_marker(text):
        return False
    lowered = text.lower()
    if 'utc=' in text and len(text) <= 300:
        return True
    dynamic_markers = (
        'runtime context:',
        'current runtime',
        'current time',
        'current date',
        'current model',
        'local time',
        'timezone',
        '当前时间',
        '当前日期',
        '当前模型',
        '运行时上下文',
    )
    return any(marker in lowered or marker in text for marker in dynamic_markers)


def _responses_is_dynamic_context_message(message: dict | None = None) -> bool:
    if not isinstance(message, dict):
        return False
    role = str(message.get('role') or '').strip().lower()
    if role not in {'system', 'developer'}:
        return False
    kind = str(message.get('_kind') or '').strip().lower()
    if kind in _RESPONSES_DYNAMIC_CONTEXT_KINDS:
        return True
    try:
        text = _responses_instruction_text_from_content(message.get('content'))
    except Exception:
        text = ''
    # Older preparation paths can lose `_kind`; only move clearly per-request
    # runtime snippets, not all untyped system/developer instructions.
    if not kind and _responses_untyped_context_looks_dynamic(text):
        return True
    return False


def _responses_is_stable_input_context_message(message: dict | None = None) -> bool:
    if not _responses_stable_context_input_enabled():
        return False
    if not isinstance(message, dict):
        return False
    role = str(message.get('role') or '').strip().lower()
    if role not in {'system', 'developer'}:
        return False
    kind = str(message.get('_kind') or '').strip().lower()
    if kind in _RESPONSES_STABLE_INPUT_CONTEXT_KINDS:
        return True
    try:
        text = _responses_instruction_text_from_content(message.get('content'))
    except Exception:
        text = ''
    return _responses_text_has_stable_file_context_marker(text)


def _responses_instructions_from_chat_messages(messages: list | None = None, *, max_chars: int = 24000) -> str:
    # Static prefix first for prompt-cache friendliness; per-turn runtime context
    # is moved to input by _responses_input_from_chat_messages().
    # This does not restrict tool_choice=auto, reasoning, or the streaming tool loop.
    lines: list[str] = [_RESPONSES_STABLE_INSTRUCTION_PREFIX]
    for m in _orch_dedupe_model_messages(messages or []):
        if not isinstance(m, dict):
            continue
        if _responses_is_dynamic_context_message(m):
            continue
        if _responses_is_stable_input_context_message(m):
            continue
        role = str(m.get('role') or '').strip().lower()
        if role not in {'system', 'developer'}:
            continue
        text = _responses_instruction_text_from_content(m.get('content'))
        if not text:
            continue
        stable_body = _RESPONSES_STABLE_INSTRUCTION_PREFIX.split('\n', 1)[-1].strip()
        if text.strip() == stable_body:
            continue
        prefix = 'Developer instructions' if role == 'developer' else 'System instructions'
        lines.append(f'{prefix}:\n{text}')
    instructions = '\n\n'.join(lines).strip()
    max_chars = max(1000, int(max_chars or 24000))
    if len(instructions) > max_chars:
        instructions = instructions[:max_chars].rstrip() + '\n...【instructions truncated】'
    return instructions


def _responses_input_from_chat_messages(messages: list | None = None) -> list[dict]:
    out = []
    stable_context = []
    dynamic_context = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        if _responses_failed_assistant_history_message(m):
            continue
        role = str(m.get('role') or 'user').strip().lower()
        # Keep ordinary system/developer content in top-level instructions, but
        # put large stable file context in input so Responses relays that cache
        # message/input prefixes can reuse the real attachment body too.
        if role in {'system', 'developer'}:
            text = _responses_instruction_text_from_content(m.get('content'))
            if _responses_is_stable_input_context_message(m):
                if text:
                    stable_context.append({
                        'role': role,
                        'content': [{'type': 'input_text', 'text': text}],
                    })
            elif _responses_is_dynamic_context_message(m):
                if text:
                    dynamic_context.append({
                        'role': 'user',
                        'content': [{'type': 'input_text', 'text': 'Runtime context:\n' + text}],
                    })
            continue
        if role == 'tool':
            role = 'user'
        if role not in {'user', 'assistant'}:
            role = 'user'
        content = _responses_input_content_from_chat_content(m.get('content'), role=role)
        if role == 'assistant':
            evidence_text = _prompt_cache_message_evidence_text(m)
            if evidence_text:
                evidence_part = {'type': 'output_text', 'text': evidence_text}
                if isinstance(content, list):
                    content.append(evidence_part)
                elif isinstance(content, str) and content.strip():
                    content = [
                        {'type': 'output_text', 'text': content.strip()},
                        evidence_part,
                    ]
                else:
                    content = [evidence_part]
        if isinstance(content, str) and not content.strip():
            continue
        if isinstance(content, list) and not content:
            continue
        out.append({'role': role, 'content': content})
    if stable_context:
        out = stable_context + out
    if dynamic_context:
        out.extend(dynamic_context)
    return out
