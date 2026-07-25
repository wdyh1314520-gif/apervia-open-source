# prompt cache planning and request payload helpers.

_PROMPT_CACHE_CHAT_TAIL_CONTEXT_KINDS = set(_PROMPT_CACHE_RUNTIME_TAIL_CONTEXT_KINDS)

_PROMPT_CACHE_CHAT_REQUIRED_TAIL_CONTEXT_KINDS = {
    'kb_recall',
    'kb_doc_brief',
    'kb_existing_file_answer',
}


def _prompt_cache_chat_dynamic_context_mode() -> str:
    raw = _prompt_cache_app_getenv('APP3_PROMPT_CACHE_CHAT_DYNAMIC_CONTEXT', '').strip().lower()
    if raw in {'tail', 'append', 'keep'}:
        return 'tail'
    if raw in {'0', 'false', 'off', 'no', 'omit', 'drop', 'disabled', 'disable'}:
        return 'omit'
    return 'tail'



def _prompt_cache_is_chat_tail_context_message(message: dict | None = None) -> bool:
    if not isinstance(message, dict):
        return False
    role = str(message.get('role') or '').strip().lower()
    if role not in {'system', 'developer'}:
        return False
    kind = str(message.get('_kind') or '').strip().lower()
    if kind in _PROMPT_CACHE_CHAT_TAIL_CONTEXT_KINDS:
        return True
    if kind:
        return False
    try:
        text = _responses_instruction_text_from_content(message.get('content'))
    except Exception:
        text = ''
    return _responses_untyped_context_looks_dynamic(text)



def _prompt_cache_message_evidence_text(message: dict | None = None) -> str:
    """Summarize real persisted tool/search/file evidence carried by a message."""
    if not isinstance(message, dict):
        return ''
    rows: list[str] = []

    def add(label: str, value, *, max_chars: int = 12000) -> None:
        if value in (None, '', [], {}):
            return
        try:
            text = value if isinstance(value, str) else _prompt_cache_stable_json(value)
        except Exception:
            text = str(value or '')
        text = _chat_context_clip_text(str(text or '').strip(), max_chars, preserve_tail=False)
        if text:
            rows.append(f'{label}:\n{text}')

    add('工具/检索来源 sources', message.get('sources'), max_chars=18000)
    add('图片检索结果 imageReplies', message.get('imageReplies') or message.get('image_replies'), max_chars=18000)
    add('天气工具结果 weather', message.get('weather'), max_chars=12000)
    add('生成/发布文件 generatedFiles', message.get('generatedFiles') or message.get('generated_files'), max_chars=16000)
    add('文件处理过程 fileProcessText', message.get('fileProcessText') or message.get('file_process_text'), max_chars=24000)
    reasoning_meta = message.get('reasoningMeta') or message.get('reasoning_meta')
    if isinstance(reasoning_meta, dict):
        evidence = {}
        for key in (
            'webHit', 'web_hit', 'resultCount', 'result_count', 'pageCount', 'page_count',
            'sourceCount', 'source_count', 'queriesUsed', 'queries_used',
            'searchResults', 'search_results', 'searchedResults', 'searched_results',
            'sources', 'sourceItems', 'source_items',
        ):
            if key in reasoning_meta:
                evidence[key] = reasoning_meta.get(key)
        add('工具/检索过程 reasoningMeta', evidence, max_chars=20000)
    if not rows:
        return ''
    return '【已持久化的真实工具/检索证据】\n' + '\n\n'.join(rows)



def _prompt_cache_chat_messages_for_request(messages: list | None = None) -> list:
    stable_head: list = []
    stable_runtime: list = []
    rest: list = []
    dynamic_context: list[tuple[dict, bool]] = []
    seen_non_instruction = False
    for m in messages or []:
        if not isinstance(m, dict):
            seen_non_instruction = True
            rest.append(m)
            continue
        role = str(m.get('role') or '').strip().lower()
        kind = str(m.get('_kind') or '').strip().lower()
        if _prompt_cache_is_chat_tail_context_message(m):
            text = _responses_instruction_text_from_content(m.get('content'))
            if text:
                dynamic_context.append((
                    {'role': 'user', 'content': 'Runtime context:\n' + text},
                    kind in _PROMPT_CACHE_CHAT_REQUIRED_TAIL_CONTEXT_KINDS,
                ))
            continue
        # Drop legacy synthetic cache anchors from older in-memory jobs; new
        # requests should cache only real leading instructions and tool schemas.
        if role in {'system', 'developer'} and kind == 'prompt_cache_chat_anchor':
            continue
        if role in {'system', 'developer'} and not seen_non_instruction:
            stable_head.append(m)
            continue
        seen_non_instruction = True
        rest.append(m)
    if _prompt_cache_chat_dynamic_context_mode() == 'omit':
        dynamic_context = [message for message, required in dynamic_context if required]
    else:
        dynamic_context = [message for message, _required in dynamic_context]
    stable_blocks = stable_head + stable_runtime
    # Keep Chat Completions cache material identical to the real conversation.
    # Runtime-only context stays at the tail; historical user/assistant/tool
    # turns remain as ordinary messages so later rounds can reuse the exact
    # previous prompt prefix without a synthetic system-history wrapper.
    return stable_blocks + rest + dynamic_context


def _prompt_cache_chat_leading_messages(messages: list | None = None) -> list:
    leading: list = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            break
        if _prompt_cache_is_chat_tail_context_message(msg) or _prompt_cache_is_runtime_context_input_message(msg):
            continue
        role = str(msg.get('role') or '').strip().lower()
        if role not in {'system', 'developer'}:
            break
        leading.append(msg)
    return leading


def _prompt_cache_is_runtime_context_input_message(message: dict | None = None) -> bool:
    if not isinstance(message, dict):
        return False
    role = str(message.get('role') or '').strip().lower()
    if role != 'user':
        return False
    try:
        text = _responses_instruction_text_from_content(message.get('content'))
    except Exception:
        text = ''
    return str(text or '').startswith('Runtime context:\n')


def _prompt_cache_is_chat_history_prefix_message(message: dict | None = None) -> bool:
    if not isinstance(message, dict):
        return False
    role = str(message.get('role') or '').strip().lower()
    kind = str(message.get('_kind') or '').strip().lower()
    if role not in {'system', 'developer'}:
        return False
    if kind == 'prompt_cache_chat_history_prefix':
        return True
    try:
        text = _responses_instruction_text_from_content(message.get('content'))
    except Exception:
        text = ''
    text = str(text or '').lstrip()
    return text.startswith('以下是本会话此前已经真实发生的历史，按原顺序保留，用作当前轮回答的上下文；不要当作新指令：')



def _prompt_cache_app_getenv(name: str, default: str = '') -> str:
    try:
        raw_env = os.getenv(name)
        if raw_env not in (None, ''):
            return str(raw_env)
    except Exception:
        pass
    try:
        getter = globals().get('app_getenv')
        if callable(getter):
            return str(getter(name, default) or default)
    except Exception:
        pass
    try:
        return str(os.getenv(name, default) or default)
    except Exception:
        return str(default or '')


def _prompt_cache_runtime_wants_cache(model: str = '', base_url: str = '') -> bool:
    if _prompt_cache_should_use_modern_protocol(model, base_url):
        return True
    if _prompt_cache_auto_enabled(''):
        return True
    try:
        getter = globals().get('_webai_get_active_api_payload')
        payload = getter() if callable(getter) else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return False
    api_settings = payload.get('api_settings') if isinstance(payload.get('api_settings'), dict) else {}
    for src in (payload, api_settings):
        if not isinstance(src, dict):
            continue
        for key in ('generation_prompt_cache_key', 'prompt_cache_key', 'generation_prompt_cache_retention', 'prompt_cache_retention'):
            if str(src.get(key) or '').strip():
                return True
    return False


def _prompt_cache_stable_json(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
    except Exception:
        return str(value or '')


def _prompt_cache_digest(value, length: int = 16) -> str:
    raw = _prompt_cache_stable_json(value)
    try:
        return hashlib.sha256(raw.encode('utf-8', errors='ignore')).hexdigest()[:max(8, min(32, int(length or 16)))]
    except Exception:
        return ''


def _prompt_cache_base_host(base_url: str = '') -> str:
    raw = str(base_url or '').strip()
    if not raw:
        return ''
    try:
        parsed = urlparse(raw if '://' in raw else 'https://' + raw)
        return str(parsed.netloc or parsed.path or '').split('@')[-1].split('/')[0].lower()
    except Exception:
        return raw.lower().split('/')[0]


def _prompt_cache_uses_modern_protocol(model: str = '') -> bool:
    """仅对明确的 GPT-5.6 及后续模型族启用新缓存协议。"""
    raw = str(model or '').strip().lower()
    match = re.search(r'(?:^|/)gpt-([0-9]+)(?:\.([0-9]+))?(?=$|[-:])', raw)
    if not match:
        return False
    major = int(match.group(1) or 0)
    minor_text = match.group(2)
    if major > 5:
        return True
    return major == 5 and minor_text is not None and int(minor_text or 0) >= 6


def _prompt_cache_default_options() -> dict:
    return {'mode': 'implicit', 'ttl': '30m'}


def _prompt_cache_should_use_modern_protocol(model: str = '', base_url: str = '', options: dict | None = None) -> bool:
    del base_url, options
    return _prompt_cache_uses_modern_protocol(model)


def _prompt_cache_preserve_legacy_retention(model: str = '', base_url: str = '') -> bool:
    if not _prompt_cache_uses_modern_protocol(model):
        return False
    host = _prompt_cache_base_host(base_url)
    if not host:
        return False
    official = host == 'api.openai.com' or host.endswith('.openai.com')
    return not official


def _prompt_cache_mark_message_breakpoint(message: dict | None = None, *, endpoint_mode: str = '') -> tuple[dict, bool]:
    import copy

    row = copy.deepcopy(message) if isinstance(message, dict) else {}
    endpoint = str(endpoint_mode or '').strip().lower()
    content = row.get('content')
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return row, False
        part_type = 'input_text' if endpoint == 'responses' else 'text'
        row['content'] = [{'type': part_type, 'text': content, 'prompt_cache_breakpoint': {'mode': 'explicit'}}]
        return row, True
    if not isinstance(content, list):
        return row, False
    for index in range(len(content) - 1, -1, -1):
        part = content[index]
        if not isinstance(part, dict):
            continue
        part_type = str(part.get('type') or '').strip().lower()
        text = str(part.get('text') or '').strip()
        allowed = {'text'} if endpoint != 'responses' else {'input_text', 'text'}
        if part_type not in allowed or not text:
            continue
        next_part = dict(part)
        next_part['prompt_cache_breakpoint'] = {'mode': 'explicit'}
        content[index] = next_part
        row['content'] = content
        return row, True
    return row, False


def _prompt_cache_apply_explicit_breakpoint(body: dict | None = None, *, endpoint_mode: str = '') -> tuple[dict, int]:
    import copy

    out = copy.deepcopy(body) if isinstance(body, dict) else {}
    endpoint = str(endpoint_mode or '').strip().lower()
    field_name = 'input' if endpoint == 'responses' else 'messages'
    rows = out.get(field_name)
    if not isinstance(rows, list) or not rows:
        return out, 0

    candidate_indexes: list[int] = []
    if endpoint == 'responses':
        current_tail_start = len(rows)
        index = len(rows) - 1
        while index >= 0:
            row = rows[index] if isinstance(rows[index], dict) else {}
            if str(row.get('role') or '').strip().lower() != 'user':
                break
            current_tail_start = index
            index -= 1

        # Apervia 把本轮动态 Runtime context 放在真实用户问题之后。Responses
        # 的 implicit 断点会落在最后一条动态消息上，因此还需要在真实用户问题
        # 结束处放一个 explicit 断点：原生 web_search 的搜索阶段与最终生成阶段
        # 可以复用同一个真实请求前缀，而运行时位置/时间等内容仍留在断点之后。
        current_user_index = None
        if current_tail_start < len(rows):
            for tail_index in range(len(rows) - 1, current_tail_start - 1, -1):
                row = rows[tail_index] if isinstance(rows[tail_index], dict) else {}
                if str(row.get('role') or '').strip().lower() != 'user':
                    continue
                if _prompt_cache_is_runtime_context_input_item(row):
                    continue
                current_user_index = tail_index
                break
        has_runtime_after_current = bool(
            current_user_index is not None
            and any(
                _prompt_cache_is_runtime_context_input_item(rows[tail_index])
                for tail_index in range(current_user_index + 1, len(rows))
                if isinstance(rows[tail_index], dict)
            )
        )

        # 重建上一轮真实用户消息的读取边界，不锚定历史动态 Runtime context。
        for index in range(current_tail_start - 1, -1, -1):
            row = rows[index] if isinstance(rows[index], dict) else {}
            role = str(row.get('role') or '').strip().lower()
            if role == 'user' and _prompt_cache_is_runtime_context_input_item(row):
                continue
            if role in {'system', 'developer', 'user'}:
                candidate_indexes.append(index)
                break
        if has_runtime_after_current and current_user_index is not None:
            candidate_indexes.append(current_user_index)
    else:
        for index, row in enumerate(rows):
            role = str((row or {}).get('role') or '').strip().lower() if isinstance(row, dict) else ''
            if role not in {'system', 'developer'}:
                break
            candidate_indexes.append(index)
        candidate_indexes.reverse()

    changed_count = 0
    for index in candidate_indexes:
        marked, changed = _prompt_cache_mark_message_breakpoint(rows[index], endpoint_mode=endpoint)
        if changed:
            rows[index] = marked
            changed_count += 1
    if changed_count:
        out[field_name] = rows
    return out, changed_count


def _prompt_cache_without_modern_protocol(body: dict | None = None, *, placement: str = 'body') -> dict:
    import copy

    out = copy.deepcopy(body) if isinstance(body, dict) else {}
    target = out
    if str(placement or 'body').strip().lower() == 'extra_body':
        extra = out.get('extra_body') if isinstance(out.get('extra_body'), dict) else {}
        target = dict(extra)
        out['extra_body'] = target
    target.pop('prompt_cache_options', None)

    def strip_breakpoints(value) -> None:
        if isinstance(value, dict):
            value.pop('prompt_cache_breakpoint', None)
            for child in value.values():
                strip_breakpoints(child)
        elif isinstance(value, list):
            for child in value:
                strip_breakpoints(child)

    strip_breakpoints(out.get('messages'))
    strip_breakpoints(out.get('input'))
    return out


def _prompt_cache_rejects_modern_protocol(error_text: str = '') -> bool:
    text = str(error_text or '').strip().lower()
    if not text or not any(name in text for name in ('prompt_cache_options', 'prompt_cache_breakpoint')):
        return False
    return any(marker in text for marker in (
        'unsupported',
        'unknown parameter',
        'unrecognized parameter',
        'invalid',
        'not supported',
        'not allowed',
        'extra inputs are not permitted',
    ))


def _prompt_cache_auto_enabled(base_url: str = '') -> bool:
    raw = _prompt_cache_app_getenv('APP3_PROMPT_CACHE_AUTO', '0').strip().lower()
    if raw in {'0', 'false', 'off', 'no', 'disabled', 'disable'}:
        return False
    if raw in {'1', 'true', 'on', 'yes', 'enabled', 'enable', 'all'}:
        return True
    return False


def _prompt_cache_retention_default(base_url: str = '') -> str:
    raw = _prompt_cache_app_getenv('APP3_PROMPT_CACHE_RETENTION', '').strip().lower()
    if raw in {'1h', '24h'}:
        return raw
    if _prompt_cache_auto_enabled(base_url):
        return '24h'
    return ''


def _prompt_cache_model_slug(model: str = '') -> str:
    raw = re.sub(r'[^A-Za-z0-9_.:-]+', '-', str(model or '').strip())[:80].strip('-')
    return raw or 'model'


def _prompt_cache_key_scope() -> str:
    raw = _prompt_cache_app_getenv('APP3_PROMPT_CACHE_KEY_SCOPE', 'platform').strip().lower()
    if raw in {'platform', 'global', 'shared'}:
        return 'platform'
    if raw in {'session', 'thread', 'conversation', 'chat'}:
        return 'session'
    return 'platform'


def _prompt_cache_namespace_slug(value: str = '') -> str:
    raw = re.sub(r'[^A-Za-z0-9_.:-]+', '-', str(value or '').strip())[:96].strip('-')
    return raw


def _prompt_cache_key_material_hash(body: dict | None = None, *, endpoint_mode: str = '') -> str:
    body = body if isinstance(body, dict) else {}
    endpoint = str(endpoint_mode or '').strip().lower()
    # prompt_cache_key 用于把同一类精确前缀稳定路由到同一缓存族，不是完整
    # payload 哈希。只纳入位于请求前部且真正稳定的平台材料；input、用户问题、
    # tool_choice 和本轮工具调用动作都不能参与，否则普通轮、联网轮和续轮会换 key。
    # 同时不能只按 endpoint 共用一个 key，否则不同工具 schema / 平台规则会争用
    # 同一缓存路由，在平台流量下反而增加 miss。
    material = {
        'version': 'routing-v3',
        'endpoint': endpoint or 'unknown',
        'instructions': body.get('instructions') or '' if 'instructions' in body else '',
        'tools': body.get('tools') if isinstance(body.get('tools'), list) else [],
        'text': body.get('text') if isinstance(body.get('text'), dict) else {},
        'response_format': body.get('response_format') if 'response_format' in body else {},
        'reasoning': body.get('reasoning') if isinstance(body.get('reasoning'), dict) else {},
        'thinking': body.get('thinking') if isinstance(body.get('thinking'), dict) else {},
    }
    return _prompt_cache_digest(material, 16)


class PromptCachePlan:
    def __init__(
        self,
        body: dict | None = None,
        *,
        endpoint_mode: str = '',
        model: str = '',
        base_url: str = '',
        phase: str = '',
        placement: str = 'body',
        cache_namespace: str = '',
    ):
        self.body = body if isinstance(body, dict) else {}
        self.endpoint = str(endpoint_mode or '').strip().lower() or 'chat_completions'
        self.model = str(model or '').strip()
        self.base_url = str(base_url or '').strip()
        self.phase = str(phase or '')
        self.placement = str(placement or 'body').strip().lower()
        self.cache_namespace = _prompt_cache_namespace_slug(cache_namespace)
        self.key_scope = _prompt_cache_key_scope()
        self.host = _prompt_cache_base_host(self.base_url)
        self.existing_key, self.existing_retention = _prompt_cache_existing(self.body, placement=self.placement)
        self.explicit = bool(self.existing_key or self.existing_retention)
        self.auto_enabled = _prompt_cache_auto_enabled(self.base_url)
        self.modern_protocol = _prompt_cache_should_use_modern_protocol(self.model, self.base_url)
        self.options = _prompt_cache_default_options() if self.modern_protocol else {}
        self.compat_legacy_retention = _prompt_cache_preserve_legacy_retention(self.model, self.base_url)
        self.enabled = bool(self.explicit or self.auto_enabled or self.modern_protocol)
        self.stable_material = _prompt_cache_stable_material(self.body, endpoint_mode=self.endpoint)
        self.stable_hash = _prompt_cache_digest(self.stable_material, 16)
        self.key_material_hash = _prompt_cache_key_material_hash(self.body, endpoint_mode=self.endpoint)
        self.key_basis_hash = self._auto_key_basis_hash()
        self.key = self.existing_key or self._auto_key()
        self.retention = self.existing_retention or _prompt_cache_retention_default(self.base_url)
        self.full_prefix = _prompt_cache_prefix_material(self.body, endpoint_mode=self.endpoint)
        self.platform_prefix = _prompt_cache_platform_prefix_material(self.body, endpoint_mode=self.endpoint)
        self.reusable_context_prefix = _prompt_cache_reusable_context_prefix_material(self.body, endpoint_mode=self.endpoint)
        self.tools_part = _prompt_cache_stable_json(self.body.get('tools')) if isinstance(self.body.get('tools'), list) and self.body.get('tools') else ''
        self.input_part = _prompt_cache_input_diagnostic_material(self.body, endpoint_mode=self.endpoint)
        self.instructions_part = str(self.body.get('instructions') or '') if self.body.get('instructions') is not None else ''
        self.breakpoint_count = 0

    def _auto_key(self) -> str:
        host_hash = _prompt_cache_digest(self.host or 'default', 10)
        # Keep the routing namespace broad and stable. The provider still
        # validates the exact prompt prefix; bind the key to real stable platform
        # material instead of the whole turn so cross-topic platform/tool prefixes
        # can share a bucket without mixing unrelated provider/model hosts.
        stable_hash = self.key_material_hash or _prompt_cache_key_material_hash(self.body, endpoint_mode=self.endpoint)
        parts = ['app3', 'pc6', self.endpoint or 'api', _prompt_cache_model_slug(self.model), host_hash, stable_hash]
        if self.key_scope == 'session' and self.cache_namespace:
            parts.append('s')
            parts.append(_prompt_cache_digest(self.cache_namespace, 12))
        key = ':'.join(parts)
        return key[:512]

    def _auto_key_basis_hash(self) -> str:
        host_hash = _prompt_cache_digest(self.host or 'default', 10)
        material = {
            'version': 'pc6',
            'endpoint': self.endpoint or 'api',
            'model': _prompt_cache_model_slug(self.model),
            'host_hash': host_hash,
            'key_material_hash': self.key_material_hash or _prompt_cache_key_material_hash(self.body, endpoint_mode=self.endpoint),
            'scope': self.key_scope,
            'session': _prompt_cache_digest(self.cache_namespace, 12) if self.key_scope == 'session' and self.cache_namespace else '',
        }
        return _prompt_cache_digest(material, 16)

    def apply_to(self, body: dict | None = None) -> dict:
        import copy

        out = copy.deepcopy(body or self.body or {})
        if not self.enabled:
            return out
        placement = str(getattr(self, 'placement', 'body') or 'body').strip().lower()
        modern_protocol = bool(getattr(self, 'modern_protocol', False))
        retention = str(getattr(self, 'retention', '') or '').strip().lower()
        out = _prompt_cache_without_modern_protocol(out, placement=placement)
        if placement == 'extra_body':
            extra = dict(out.get('extra_body') or {}) if isinstance(out.get('extra_body'), dict) else {}
            if self.key:
                extra['prompt_cache_key'] = self.key
            if modern_protocol:
                extra['prompt_cache_options'] = dict(getattr(self, 'options', None) or _prompt_cache_default_options())
                if bool(getattr(self, 'compat_legacy_retention', False)) and retention:
                    extra['prompt_cache_retention'] = retention
                else:
                    extra.pop('prompt_cache_retention', None)
            elif retention:
                extra['prompt_cache_retention'] = retention
            out['extra_body'] = extra
        else:
            if self.key:
                out['prompt_cache_key'] = self.key
            if modern_protocol:
                out['prompt_cache_options'] = dict(getattr(self, 'options', None) or _prompt_cache_default_options())
                if bool(getattr(self, 'compat_legacy_retention', False)) and retention:
                    out['prompt_cache_retention'] = retention
                else:
                    out.pop('prompt_cache_retention', None)
            elif retention:
                out['prompt_cache_retention'] = retention
        if modern_protocol:
            out, count = _prompt_cache_apply_explicit_breakpoint(out, endpoint_mode=getattr(self, 'endpoint', ''))
            self.breakpoint_count = int(count or 0)
        else:
            self.breakpoint_count = 0
        return out

    def log(self) -> None:
        if not self.enabled:
            return
        try:
            full_chars = len(self.full_prefix)
            platform_chars = len(self.platform_prefix)
            context_chars = len(self.reusable_context_prefix)
            app_logger.info(
                '[PROMPT_CACHE_APPLY] endpoint=%s phase=%s placement=%s auto=%s key_hash=%s retention=%s breakpoints=%s stable_hash=%s key_basis_hash=%s prefix_hash=%s prefix_chars=%s est_prefix_tokens=%s stable_prefix_hash=%s stable_prefix_chars=%s stable_est_prefix_tokens=%s platform_hash=%s platform_chars=%s platform_est_tokens=%s context_hash=%s context_chars=%s context_est_tokens=%s tools=%s host=%s instr_hash=%s instr_chars=%s tools_hash=%s tools_chars=%s input_hash=%s input_chars=%s key_scope=%s namespace_hash=%s',
                self.endpoint,
                self.phase,
                self.placement,
                bool(self.auto_enabled and not self.explicit),
                _prompt_cache_digest(self.key, 12),
                self.retention or '',
                int(getattr(self, 'breakpoint_count', 0) or 0),
                self.stable_hash,
                self.key_basis_hash,
                _prompt_cache_digest(self.full_prefix, 16),
                full_chars,
                int(max(0, full_chars) / 3.6),
                _prompt_cache_digest(self.reusable_context_prefix, 16),
                context_chars,
                int(max(0, context_chars) / 3.6),
                _prompt_cache_digest(self.platform_prefix, 16),
                platform_chars,
                int(max(0, platform_chars) / 3.6),
                _prompt_cache_digest(self.reusable_context_prefix, 16),
                context_chars,
                int(max(0, context_chars) / 3.6),
                len(self.body.get('tools') or []) if isinstance(self.body.get('tools'), list) else 0,
                self.host,
                _prompt_cache_digest(self.instructions_part, 12),
                len(self.instructions_part),
                _prompt_cache_digest(self.tools_part, 12),
                len(self.tools_part),
                _prompt_cache_digest(self.input_part, 12),
                len(self.input_part),
                self.key_scope,
                _prompt_cache_digest(self.cache_namespace, 12) if self.cache_namespace else '',
            )
            if self.endpoint == 'responses':
                shape = _prompt_cache_responses_payload_shape_summary(self.body)
                app_logger.info(
                    '[RESPONSES_PROMPT_CACHE_PAYLOAD_SHAPE] phase=%s key_hash=%s input_items=%s roles=%s total_text_chars=%s file_marker_items=%s file_marker_chars=%s runtime_items=%s large_items=%s duplicate_large_text_hashes=%s',
                    self.phase,
                    _prompt_cache_digest(self.key, 12),
                    shape.get('input_items'),
                    json.dumps(shape.get('roles') or {}, ensure_ascii=False, sort_keys=True),
                    shape.get('total_text_chars'),
                    shape.get('file_marker_items'),
                    shape.get('file_marker_chars'),
                    shape.get('runtime_items'),
                    json.dumps(shape.get('large_items') or [], ensure_ascii=False, sort_keys=True),
                    json.dumps(shape.get('duplicate_large_text_hashes') or [], ensure_ascii=False, sort_keys=True),
                )
            audit_enabled = str(
                _prompt_cache_app_getenv('APP3_PROMPT_CACHE_AUDIT_ENABLED', '0') or '0'
            ).strip().lower() in {'1', 'true', 'yes', 'on'}
            if audit_enabled:
                _prompt_cache_log_audit_segments(
                    self.body,
                    endpoint_mode=self.endpoint,
                    phase=self.phase,
                    key_hash=_prompt_cache_digest(self.key, 12),
                )
        except Exception:
            pass


def _prompt_cache_plan(
    body: dict | None = None,
    *,
    endpoint_mode: str = '',
    model: str = '',
    base_url: str = '',
    phase: str = '',
    placement: str = 'body',
    cache_namespace: str = '',
) -> PromptCachePlan:
    return PromptCachePlan(
        body,
        endpoint_mode=endpoint_mode,
        model=model,
        base_url=base_url,
        phase=phase,
        placement=placement,
        cache_namespace=cache_namespace,
    )


def _prompt_cache_stable_material(body: dict | None = None, *, endpoint_mode: str = '') -> dict:
    body = body if isinstance(body, dict) else {}
    endpoint = str(endpoint_mode or '').strip().lower()
    material: dict = {
        'endpoint': endpoint or 'unknown',
        'tools': body.get('tools') if isinstance(body.get('tools'), list) else [],
        'tool_choice': body.get('tool_choice') if 'tool_choice' in body else '',
        'text': body.get('text') if isinstance(body.get('text'), dict) else {},
        'response_format': body.get('response_format') if 'response_format' in body else {},
        'reasoning': body.get('reasoning') if isinstance(body.get('reasoning'), dict) else {},
        'thinking': body.get('thinking') if isinstance(body.get('thinking'), dict) else {},
    }
    if 'instructions' in body:
        material['instructions'] = body.get('instructions') or ''
    if endpoint != 'responses':
        leading = [
            {'role': str(msg.get('role') or '').strip().lower(), 'content': msg.get('content')}
            for msg in _prompt_cache_chat_leading_messages(body.get('messages') or [])
            if not _prompt_cache_is_chat_history_prefix_message(msg)
        ]
        material['leading_instructions'] = leading
    return material


def _prompt_cache_prefix_material(body: dict | None = None, *, endpoint_mode: str = '', max_chars: int = 1000000) -> str:
    body = body if isinstance(body, dict) else {}
    parts: list[str] = []
    if body.get('instructions') is not None:
        parts.append(str(body.get('instructions') or ''))
    if isinstance(body.get('tools'), list) and body.get('tools'):
        parts.append(_prompt_cache_stable_json(body.get('tools')))
    messages = body.get('messages') if isinstance(body.get('messages'), list) else None
    if messages is not None:
        parts.append(_prompt_cache_stable_json(messages))
    elif body.get('input') is not None:
        parts.append(_prompt_cache_stable_json(body.get('input')))
    text = '\n'.join(x for x in parts if x)
    max_chars = max(1000, int(max_chars or 12000))
    return text[:max_chars]


def _prompt_cache_platform_prefix_material(body: dict | None = None, *, endpoint_mode: str = '', max_chars: int = 1000000) -> str:
    body = body if isinstance(body, dict) else {}
    endpoint = str(endpoint_mode or '').strip().lower()
    parts: list[str] = []
    if body.get('instructions') is not None:
        parts.append(str(body.get('instructions') or ''))
    if isinstance(body.get('tools'), list) and body.get('tools'):
        parts.append(_prompt_cache_stable_json(body.get('tools')))
    if endpoint != 'responses':
        messages = body.get('messages') if isinstance(body.get('messages'), list) else []
        leading_messages = _prompt_cache_chat_leading_messages(messages)
        if leading_messages:
            parts.append(_prompt_cache_stable_json(leading_messages))
    text = '\n'.join(x for x in parts if x)
    max_chars = max(1000, int(max_chars or 12000))
    return text[:max_chars]


def _prompt_cache_stable_prefix_material(body: dict | None = None, *, endpoint_mode: str = '', max_chars: int = 1000000) -> str:
    return _prompt_cache_platform_prefix_material(body, endpoint_mode=endpoint_mode, max_chars=max_chars)


def _prompt_cache_response_input_text(item: dict | None = None) -> str:
    if not isinstance(item, dict):
        return ''
    try:
        return _responses_instruction_text_from_content(item.get('content'))
    except Exception:
        return ''


def _prompt_cache_is_runtime_context_input_item(item: dict | None = None) -> bool:
    return _prompt_cache_response_input_text(item).startswith('Runtime context:\n')


def _prompt_cache_reusable_response_input_items(body: dict | None = None) -> list:
    body = body if isinstance(body, dict) else {}
    input_items = body.get('input') if isinstance(body.get('input'), list) else []
    latest_user_idx = None
    for idx in range(len(input_items) - 1, -1, -1):
        item = input_items[idx]
        if not isinstance(item, dict):
            continue
        if _prompt_cache_is_runtime_context_input_item(item):
            continue
        role = str(item.get('role') or '').strip().lower()
        if role == 'user':
            latest_user_idx = idx
            break
    if latest_user_idx is None:
        return []
    out = []
    for item in input_items[:latest_user_idx]:
        if not isinstance(item, dict):
            continue
        if _prompt_cache_is_runtime_context_input_item(item):
            continue
        out.append(item)
    return out


def _prompt_cache_reusable_chat_messages(messages: list | None = None) -> list:
    rows = [m for m in (messages or []) if isinstance(m, dict)]
    leading_len = len(_prompt_cache_chat_leading_messages(rows))
    latest_user_idx = None
    for idx in range(len(rows) - 1, leading_len - 1, -1):
        msg = rows[idx]
        if _prompt_cache_is_runtime_context_input_message(msg):
            continue
        if str(msg.get('role') or '').strip().lower() == 'user':
            latest_user_idx = idx
            break
    if latest_user_idx is None:
        return []
    reusable = []
    for msg in rows[leading_len:latest_user_idx]:
        if _prompt_cache_is_runtime_context_input_message(msg):
            continue
        reusable.append(msg)
    return reusable


def _prompt_cache_reusable_context_prefix_material(body: dict | None = None, *, endpoint_mode: str = '', max_chars: int = 1000000) -> str:
    body = body if isinstance(body, dict) else {}
    endpoint = str(endpoint_mode or '').strip().lower()
    parts: list[str] = []
    platform = _prompt_cache_platform_prefix_material(body, endpoint_mode=endpoint, max_chars=max_chars)
    if platform:
        parts.append(platform)
    if endpoint == 'responses':
        reusable_items = _prompt_cache_reusable_response_input_items(body)
        if reusable_items:
            parts.append(_prompt_cache_stable_json(reusable_items))
    else:
        reusable_messages = _prompt_cache_reusable_chat_messages(body.get('messages') if isinstance(body.get('messages'), list) else [])
        if reusable_messages:
            parts.append(_prompt_cache_stable_json(reusable_messages))
    text = '\n'.join(x for x in parts if x)
    max_chars = max(1000, int(max_chars or 120000))
    return text[:max_chars]


def _prompt_cache_input_diagnostic_material(body: dict | None = None, *, endpoint_mode: str = '', max_chars: int = 1000000) -> str:
    body = body if isinstance(body, dict) else {}
    endpoint = str(endpoint_mode or '').strip().lower()
    if endpoint == 'responses':
        input_items = body.get('input') if isinstance(body.get('input'), list) else []
        diagnostic_items = []
        for item in input_items:
            if not isinstance(item, dict):
                continue
            content = item.get('content')
            content_text = _responses_instruction_text_from_content(content)
            if content_text.startswith('Runtime context:\n'):
                continue
            diagnostic_items.append(item)
        text = _prompt_cache_stable_json(diagnostic_items) if diagnostic_items else ''
    else:
        messages = body.get('messages') if isinstance(body.get('messages'), list) else []
        leading_len = len(_prompt_cache_chat_leading_messages(messages))
        diagnostic_messages = []
        for msg in messages[leading_len:]:
            if _prompt_cache_is_runtime_context_input_message(msg):
                continue
            diagnostic_messages.append(msg)
        text = _prompt_cache_stable_json(diagnostic_messages) if diagnostic_messages else ''
    max_chars = max(1000, int(max_chars or 12000))
    return text[:max_chars]


def _prompt_cache_responses_payload_shape_summary(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    input_items = body.get('input') if isinstance(body.get('input'), list) else []
    roles: dict[str, int] = {}
    large_items: list[dict] = []
    text_hash_counts: dict[str, int] = {}
    total_text_chars = 0
    file_marker_items = 0
    file_marker_chars = 0
    runtime_items = 0
    for idx, item in enumerate(input_items):
        if not isinstance(item, dict):
            continue
        role = str(item.get('role') or '').strip().lower() or 'unknown'
        roles[role] = roles.get(role, 0) + 1
        try:
            text = _prompt_cache_response_input_text(item)
        except Exception:
            text = ''
        text_chars = len(text or '')
        total_text_chars += text_chars
        has_file_marker = _responses_text_has_stable_file_context_marker(text)
        if has_file_marker:
            file_marker_items += 1
            file_marker_chars += text_chars
        is_runtime = _prompt_cache_is_runtime_context_input_item(item)
        if is_runtime:
            runtime_items += 1
        if text_chars >= 1000:
            text_hash = _prompt_cache_digest(text, 12)
            text_hash_counts[text_hash] = text_hash_counts.get(text_hash, 0) + 1
            large_items.append({
                'idx': idx,
                'role': role,
                'chars': text_chars,
                'hash': text_hash,
                'file_marker': bool(has_file_marker),
                'runtime': bool(is_runtime),
            })
    duplicate_hashes = [
        {'hash': key, 'count': count}
        for key, count in sorted(text_hash_counts.items(), key=lambda row: (-row[1], row[0]))
        if count > 1
    ][:8]
    return {
        'input_items': len(input_items),
        'roles': roles,
        'total_text_chars': total_text_chars,
        'file_marker_items': file_marker_items,
        'file_marker_chars': file_marker_chars,
        'runtime_items': runtime_items,
        'large_items': large_items[:24],
        'duplicate_large_text_hashes': duplicate_hashes,
    }


def _prompt_cache_est_tokens_from_text(text: str = '') -> int:
    counter = globals().get('_chat_context_estimate_tokens')
    if callable(counter):
        try:
            model_getter = globals().get('_chat_context_active_model_name')
            model_name = model_getter() if callable(model_getter) else ''
            return max(0, int(counter(str(text or ''), model=model_name)))
        except Exception:
            pass
    raw = str(text or '')
    ascii_chars = sum(1 for ch in raw if ord(ch) <= 0x7f)
    cjk_chars = sum(1 for ch in raw if 0x3400 <= ord(ch) <= 0x9fff or 0xf900 <= ord(ch) <= 0xfaff)
    other_chars = max(0, len(raw) - ascii_chars - cjk_chars)
    return max(0, int(math.ceil(ascii_chars / 4.0 + cjk_chars * 0.85 + other_chars / 2.0)))


def _prompt_cache_segment_payload(value, max_chars: int | None = None) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        text = value
    else:
        text = _prompt_cache_stable_json(value)
    if max_chars is None:
        max_chars = _chat_context_cfg_int('APP3_PROMPT_CACHE_AUDIT_SEGMENT_MAX_CHARS', 300000, min_value=120000, max_value=1200000)
    max_chars = max(1000, int(max_chars or 300000))
    return str(text or '')[:max_chars]


_PROMPT_CACHE_AUDIT_SEEN_PREFIXES: set[str] = set()


def _prompt_cache_audit_history_item_limit() -> int:
    try:
        raw = _prompt_cache_app_getenv('APP3_PROMPT_CACHE_AUDIT_HISTORY_ITEMS', '64').strip()
        return max(0, min(160, int(raw or '64')))
    except Exception:
        return 64


def _prompt_cache_audit_history_segments(prefix: str, rows: list | None = None) -> list[tuple[str, str]]:
    items = [x for x in (rows or []) if isinstance(x, dict)]
    if not items:
        return []
    limit = _prompt_cache_audit_history_item_limit()
    if limit <= 0 or len(items) <= limit:
        selected = [(idx, item) for idx, item in enumerate(items, 1)]
        omitted: list[dict] = []
    else:
        head = max(1, limit // 2)
        tail = max(1, limit - head)
        selected = [(idx, item) for idx, item in enumerate(items[:head], 1)]
        omitted = items[head:len(items) - tail]
        selected.extend((idx, item) for idx, item in enumerate(items[len(items) - tail:], len(items) - tail + 1))
    out: list[tuple[str, str]] = []
    for idx, item in selected:
        role = str(item.get('role') or 'item').strip().lower() or 'item'
        out.append((f'{prefix}_{idx:03d}_{role}', _prompt_cache_segment_payload(item)))
        if omitted and idx == selected[max(0, len(selected) // 2 - 1)][0]:
            out.append((f'{prefix}_omitted_middle_{len(omitted)}', _prompt_cache_segment_payload(omitted)))
            omitted = []
    return out


def _prompt_cache_latest_non_runtime_user_index(items: list | None = None, *, responses: bool = False, start: int = 0) -> int | None:
    rows = [x for x in (items or []) if isinstance(x, dict)]
    for idx in range(len(rows) - 1, max(-1, int(start or 0) - 1), -1):
        row = rows[idx]
        if responses and _prompt_cache_is_runtime_context_input_item(row):
            continue
        if (not responses) and _prompt_cache_is_runtime_context_input_message(row):
            continue
        if str(row.get('role') or '').strip().lower() == 'user':
            return idx
    return None


def _prompt_cache_audit_segments(body: dict | None = None, *, endpoint_mode: str = '') -> list[tuple[str, str]]:
    body = body if isinstance(body, dict) else {}
    endpoint = str(endpoint_mode or '').strip().lower()
    segments: list[tuple[str, str]] = []
    if endpoint == 'responses':
        if body.get('instructions') is not None:
            segments.append(('instructions', _prompt_cache_segment_payload(body.get('instructions'))))
        if isinstance(body.get('tools'), list) and body.get('tools'):
            segments.append(('tools', _prompt_cache_segment_payload(body.get('tools'))))
        input_items = [x for x in (body.get('input') if isinstance(body.get('input'), list) else []) if isinstance(x, dict)]
        latest_idx = _prompt_cache_latest_non_runtime_user_index(input_items, responses=True)
        if latest_idx is None:
            if input_items:
                segments.append(('input_all_no_latest_user', _prompt_cache_segment_payload(input_items)))
            return segments
        history = [x for x in input_items[:latest_idx] if not _prompt_cache_is_runtime_context_input_item(x)]
        latest = input_items[latest_idx]
        tail = input_items[latest_idx + 1:]
        runtime_tail = [x for x in tail if _prompt_cache_is_runtime_context_input_item(x)]
        other_tail = [x for x in tail if not _prompt_cache_is_runtime_context_input_item(x)]
        if history:
            segments.extend(_prompt_cache_audit_history_segments('history', history))
        segments.append(('latest_user', _prompt_cache_segment_payload(latest)))
        if other_tail:
            segments.append(('after_latest_user', _prompt_cache_segment_payload(other_tail)))
        if runtime_tail:
            segments.append(('runtime_tail', _prompt_cache_segment_payload(runtime_tail)))
        return segments

    messages = [x for x in (body.get('messages') if isinstance(body.get('messages'), list) else []) if isinstance(x, dict)]
    leading_all = _prompt_cache_chat_leading_messages(messages)
    leading_len = len(leading_all)
    leading = [x for x in leading_all if not _prompt_cache_is_chat_history_prefix_message(x)]
    leading_history = [x for x in leading_all if _prompt_cache_is_chat_history_prefix_message(x)]
    if leading:
        segments.append(('leading_instructions', _prompt_cache_segment_payload(leading)))
    if isinstance(body.get('tools'), list) and body.get('tools'):
        segments.append(('tools', _prompt_cache_segment_payload(body.get('tools'))))
    stable_options = {}
    for key in ('response_format', 'text', 'reasoning', 'thinking', 'tool_choice'):
        if key in body:
            stable_options[key] = body.get(key)
    if stable_options:
        segments.append(('stable_options', _prompt_cache_segment_payload(stable_options)))
    if leading_history:
        segments.extend(_prompt_cache_audit_history_segments('history', leading_history))
    latest_idx = _prompt_cache_latest_non_runtime_user_index(messages, responses=False, start=leading_len)
    if latest_idx is None:
        rest = [x for x in messages[leading_len:] if not _prompt_cache_is_runtime_context_input_message(x)]
        if rest:
            segments.append(('messages_after_leading_no_latest_user', _prompt_cache_segment_payload(rest)))
        return segments
    history = [x for x in messages[leading_len:latest_idx] if not _prompt_cache_is_runtime_context_input_message(x)]
    latest = messages[latest_idx]
    tail = messages[latest_idx + 1:]
    runtime_tail = [x for x in tail if _prompt_cache_is_runtime_context_input_message(x)]
    other_tail = [x for x in tail if not _prompt_cache_is_runtime_context_input_message(x)]
    if history:
        segments.extend(_prompt_cache_audit_history_segments('history', history))
    segments.append(('latest_user', _prompt_cache_segment_payload(latest)))
    if other_tail:
        segments.append(('after_latest_user', _prompt_cache_segment_payload(other_tail)))
    if runtime_tail:
        segments.append(('runtime_tail', _prompt_cache_segment_payload(runtime_tail)))
    return segments


def _prompt_cache_log_audit_segments(body: dict | None = None, *, endpoint_mode: str = '', phase: str = '', key_hash: str = '') -> None:
    try:
        segments = _prompt_cache_audit_segments(body, endpoint_mode=endpoint_mode)
        cumulative = 0
        history_cumulative = 0
        latest_start = 0
        latest_end = 0
        cumulative_material_parts: list[str] = []
        latest_prefix_seen_before = False
        history_prefix_seen_before = False
        max_seen_prefix_tokens = 0
        max_seen_prefix_name = ''
        for idx, (name, payload) in enumerate(segments, 1):
            chars = len(payload or '')
            est_tokens = _prompt_cache_est_tokens_from_text(payload or '')
            prev_cumulative = cumulative
            cumulative += est_tokens
            cumulative_material_parts.append(str(payload or ''))
            cumulative_hash = _prompt_cache_digest('\n'.join(cumulative_material_parts), 16)
            prefix_seen_before = cumulative_hash in _PROMPT_CACHE_AUDIT_SEEN_PREFIXES
            if prefix_seen_before and cumulative > max_seen_prefix_tokens:
                max_seen_prefix_tokens = cumulative
                max_seen_prefix_name = name
            if name.startswith('history_'):
                history_cumulative = cumulative
                history_prefix_seen_before = bool(history_prefix_seen_before or prefix_seen_before)
            if name == 'latest_user':
                latest_start = prev_cumulative
                latest_end = cumulative
                latest_prefix_seen_before = bool(latest_prefix_seen_before or prefix_seen_before)
            app_logger.info(
                '[PROMPT_CACHE_SEGMENT] endpoint=%s phase=%s key_hash=%s idx=%s name=%s chars=%s est_tokens=%s cum_est_tokens=%s hash=%s cumulative_hash=%s prefix_seen_before=%s',
                str(endpoint_mode or '').strip().lower() or 'chat_completions',
                str(phase or ''),
                str(key_hash or ''),
                idx,
                name,
                chars,
                est_tokens,
                cumulative,
                _prompt_cache_digest(payload, 12),
                cumulative_hash,
                bool(prefix_seen_before),
            )
            _PROMPT_CACHE_AUDIT_SEEN_PREFIXES.add(cumulative_hash)
        app_logger.info(
            '[PROMPT_CACHE_AUDIT] endpoint=%s phase=%s key_hash=%s segments=%s total_est_tokens=%s history_cum_est_tokens=%s latest_user_start_est_tokens=%s latest_user_end_est_tokens=%s cache_threshold_met_before_history=%s cache_threshold_met_with_history=%s history_prefix_seen_before=%s latest_prefix_seen_before=%s max_seen_prefix_tokens=%s max_seen_prefix_name=%s cache_quantum_tokens=%s',
            str(endpoint_mode or '').strip().lower() or 'chat_completions',
            str(phase or ''),
            str(key_hash or ''),
            len(segments),
            cumulative,
            history_cumulative,
            latest_start,
            latest_end,
            bool(latest_start >= 1024),
            bool(history_cumulative >= 1024),
            bool(history_prefix_seen_before),
            bool(latest_prefix_seen_before),
            max_seen_prefix_tokens,
            str(max_seen_prefix_name or ''),
            128,
        )
    except Exception:
        pass


def _prompt_cache_existing(body: dict | None = None, *, placement: str = 'body') -> tuple[str, str]:
    body = body if isinstance(body, dict) else {}
    placement = str(placement or 'body').strip().lower()
    if placement == 'extra_body':
        extra = body.get('extra_body') if isinstance(body.get('extra_body'), dict) else {}
        return str(extra.get('prompt_cache_key') or '').strip(), str(extra.get('prompt_cache_retention') or '').strip().lower()
    return str(body.get('prompt_cache_key') or '').strip(), str(body.get('prompt_cache_retention') or '').strip().lower()


def _apply_prompt_cache_to_request_payload(
    body: dict | None = None,
    *,
    endpoint_mode: str = '',
    model: str = '',
    base_url: str = '',
    phase: str = '',
    placement: str = 'body',
    cache_namespace: str = '',
) -> dict:
    out = dict(body or {}) if isinstance(body, dict) else {}
    endpoint = str(endpoint_mode or '').strip().lower() or 'chat_completions'
    placement = str(placement or 'body').strip().lower()
    if endpoint != 'responses' and isinstance(out.get('messages'), list):
        try:
            out['messages'] = _prompt_cache_chat_messages_for_request(out.get('messages') or [])
        except Exception:
            pass
    existing_key, existing_retention = _prompt_cache_existing(out, placement=placement)
    explicit = bool(existing_key or existing_retention)
    auto_enabled = _prompt_cache_auto_enabled(base_url)
    modern_protocol = _prompt_cache_should_use_modern_protocol(model, base_url)
    if not explicit and not auto_enabled and not modern_protocol:
        return out

    plan = _prompt_cache_plan(
        out,
        endpoint_mode=endpoint,
        model=model,
        base_url=base_url,
        phase=phase,
        placement=placement,
        cache_namespace=cache_namespace,
    )
    out = plan.apply_to(out)
    plan.log()
    if endpoint == 'responses':
        try:
            shape = _prompt_cache_responses_payload_shape_summary(out)
            app_logger.info(
                '[RESPONSES_PROMPT_CACHE_PAYLOAD_SHAPE_APPLIED] phase=%s key_hash=%s input_items=%s roles=%s total_text_chars=%s file_marker_items=%s file_marker_chars=%s runtime_items=%s large_items=%s duplicate_large_text_hashes=%s',
                str(phase or ''),
                _prompt_cache_digest(plan.key, 12),
                shape.get('input_items'),
                json.dumps(shape.get('roles') or {}, ensure_ascii=False, sort_keys=True),
                shape.get('total_text_chars'),
                shape.get('file_marker_items'),
                shape.get('file_marker_chars'),
                shape.get('runtime_items'),
                json.dumps(shape.get('large_items') or [], ensure_ascii=False, sort_keys=True),
                json.dumps(shape.get('duplicate_large_text_hashes') or [], ensure_ascii=False, sort_keys=True),
            )
        except Exception as exc:
            try:
                app_logger.warning('[RESPONSES_PROMPT_CACHE_PAYLOAD_SHAPE_APPLIED_FAILED] phase=%s err=%s', str(phase or ''), exc)
            except Exception:
                pass
    return out
