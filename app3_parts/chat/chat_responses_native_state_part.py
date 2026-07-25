# Responses-native function-call accumulators and per-turn image tool state filters.


def _responses_native_stateful_continuation_enabled() -> bool:
    raw = str(app_getenv('RESPONSES_STATEFUL_CONTINUATION_ENABLED', '1') or '1').strip().lower()
    return raw not in {'0', 'false', 'no', 'off'}


def _responses_native_rejects_optional_parameter(error_text: str = '', parameter: str = '') -> bool:
    """识别供应商明确拒绝某个可选 Responses 参数的错误。"""
    text = str(error_text or '').strip().lower()
    name = str(parameter or '').strip().lower()
    if not text or not name or name not in text:
        return False
    return any(marker in text for marker in (
        'unsupported',
        'unknown parameter',
        'unrecognized parameter',
        'invalid',
        'not supported',
        'not allowed',
    ))


def _responses_native_is_generic_validation_error(error_text: str = '') -> bool:
    """识别未返回具体字段名的 Responses 参数校验错误。"""
    text = str(error_text or '').strip().lower()
    if not text:
        return False
    return any(marker in text for marker in (
        '当前请求参数校验异常',
        'request parameter validation',
        'parameter validation failed',
    )) or ('"type":"upstream_error"' in text and '参数' in text)


def _responses_native_item_text(item: dict | None = None) -> str:
    row = item if isinstance(item, dict) else {}
    content = row.get('content')
    if isinstance(content, str):
        return content.strip()
    parts: list[str] = []
    for part in (content or []) if isinstance(content, list) else []:
        if not isinstance(part, dict):
            continue
        text = str(part.get('text') or part.get('refusal') or '').strip()
        if text:
            parts.append(text)
    return '\n'.join(parts).strip()


def _responses_native_compatibility_replay_items(items: list | None = None) -> list[dict]:
    """把历史输出消息降级为中转站普遍支持的 EasyInputMessage。"""
    out: list[dict] = []
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        typ = str(row.get('type') or '').strip().lower()
        role = str(row.get('role') or '').strip().lower()
        if typ == 'reasoning':
            continue
        if typ == 'message' and (role or 'assistant') == 'assistant':
            text = _responses_native_item_text(row)
            if text:
                out.append({'role': 'assistant', 'content': text})
            continue
        if not typ and role == 'assistant':
            text = _responses_native_item_text(row)
            if text:
                out.append({'role': 'assistant', 'content': text})
            continue
        out.append(row)
    return out


def _responses_native_round_input_plan(
    replay_items: list | None,
    continuation_items: list | None,
    previous_response_id: str = '',
    stateful_supported: bool | None = None,
) -> dict:
    """为 Responses 工具续传选择最小输入，同时保留完整重放回退。"""
    replay = list(replay_items or [])
    continuation = list(continuation_items or [])
    response_id = str(previous_response_id or '').strip()
    use_stateful = bool(
        _responses_native_stateful_continuation_enabled()
        and stateful_supported is not False
        and response_id
        and continuation
    )
    return {
        'use_stateful': use_stateful,
        'previous_response_id': response_id if use_stateful else '',
        'input': continuation if use_stateful else replay,
        'replay_input': replay,
    }


class ResponsesNativeStateContext:
    def __init__(self, *, capability_groups=None):
        self.capability_groups = capability_groups if callable(capability_groups) else (lambda groups=None: [])

    def acc_key(self, payload: dict | None = None, item: dict | None = None) -> str:
        row = item if isinstance(item, dict) else {}
        src = payload if isinstance(payload, dict) else {}
        for key in ('item_id', 'id', 'call_id', 'callId'):
            val = str(src.get(key) or row.get(key) or '').strip()
            if val:
                return val
        for key in ('output_index', 'index'):
            val = src.get(key, row.get(key))
            if val is not None:
                return 'idx_' + str(val)
        return 'idx_0'

    def merge_call(self, calls: dict, payload: dict | None = None, item: dict | None = None) -> None:
        src = payload if isinstance(payload, dict) else {}
        row = item if isinstance(item, dict) else src
        typ = str(row.get('type') or src.get('type') or '').strip().lower()
        if typ and typ not in {'function_call', 'tool_call'} and 'function_call' not in typ:
            return
        key = self.acc_key(src, row)
        acc = calls.setdefault(key, {'id': '', 'call_id': '', 'name': '', 'arguments': ''})
        for id_key in ('call_id', 'callId'):
            val = str(row.get(id_key) or src.get(id_key) or '').strip()
            if val:
                acc['call_id'] = val
                break
        val = str(row.get('id') or src.get('id') or '').strip()
        if val:
            acc['id'] = val
        val = str(row.get('name') or src.get('name') or '').strip()
        if val:
            acc['name'] = val
        args_val = row.get('arguments') if 'arguments' in row else src.get('arguments')
        if isinstance(args_val, (dict, list)):
            args_text = json.dumps(args_val, ensure_ascii=False)
        else:
            args_text = str(args_val or '')
        if args_text:
            # output_item.done usually carries the complete arguments.  Delta events
            # append through _responses_native_merge_args_delta below.
            acc['arguments'] = args_text

    def merge_args_delta(self, calls: dict, payload: dict | None = None, event_type: str = '') -> None:
        src = payload if isinstance(payload, dict) else {}
        delta = src.get('delta')
        if delta is None:
            delta = src.get('arguments_delta') or src.get('argumentsDelta') or src.get('text') or src.get('content')
        if delta is None:
            return
        key = self.acc_key(src, {})
        acc = calls.setdefault(key, {'id': '', 'call_id': '', 'name': '', 'arguments': ''})
        for id_key in ('call_id', 'callId'):
            val = str(src.get(id_key) or '').strip()
            if val:
                acc['call_id'] = val
                break
        val = str(src.get('id') or '').strip()
        if val:
            acc['id'] = val
        val = str(src.get('name') or '').strip()
        if val:
            acc['name'] = val
        acc['arguments'] = str(acc.get('arguments') or '') + str(delta or '')

    def calls_list(self, calls_by_key: dict) -> list[dict]:
        out: list[dict] = []
        for _key, raw in (calls_by_key or {}).items():
            if not isinstance(raw, dict):
                continue
            name = str(raw.get('name') or '').strip()
            if not name:
                continue
            call_id = str(raw.get('call_id') or raw.get('id') or '').strip() or ('call_' + uuid.uuid4().hex[:18])
            out.append({
                'id': call_id,
                'call_id': call_id,
                'type': 'function',
                'function': {
                    'name': name,
                    'arguments': str(raw.get('arguments') or '{}').strip() or '{}',
                },
            })
        return out

    def function_call_input_items(self, calls: list[dict]) -> list[dict]:
        """Convert accumulated Responses function calls into stateless input items.

        Some OpenAI-compatible relays reject stateful continuation fields on
        /v1/responses tool-continuation requests.  For those providers we keep
        the Responses tool loop stateless by replaying the function_call item
        immediately followed by its function_call_output item in input.
        """
        items: list[dict] = []
        for call in (calls or []):
            if not isinstance(call, dict):
                continue
            fn = call.get('function') if isinstance(call.get('function'), dict) else {}
            name = str((fn or {}).get('name') or call.get('name') or '').strip()
            if not name:
                continue
            call_id = str(call.get('call_id') or call.get('id') or '').strip() or ('call_' + uuid.uuid4().hex[:18])
            arguments = str((fn or {}).get('arguments') or call.get('arguments') or '{}').strip() or '{}'
            item = {
                'type': 'function_call',
                'call_id': call_id,
                'name': name,
                'arguments': arguments,
            }
            raw_id = str(call.get('id') or '').strip()
            if raw_id and raw_id != call_id:
                item['id'] = raw_id
            items.append(item)
        return items

    def reasoning_input_item(self, item: dict | None = None) -> dict | None:
        """保留无状态 Responses 续轮所需的加密推理项。"""
        row = item if isinstance(item, dict) else {}
        if str(row.get('type') or '').strip().lower() != 'reasoning':
            return None
        encrypted_content = str(row.get('encrypted_content') or '').strip()
        if not encrypted_content:
            return None
        out = {
            'type': 'reasoning',
            'encrypted_content': encrypted_content,
        }
        item_id = str(row.get('id') or '').strip()
        if item_id:
            out['id'] = item_id
        status = str(row.get('status') or '').strip()
        if status:
            out['status'] = status
        for field_name in ('summary', 'content'):
            parts = row.get(field_name)
            if not isinstance(parts, list):
                continue
            clean_parts = []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get('type') or '').strip()
                text = str(part.get('text') or '').strip()
                if part_type and text:
                    clean_parts.append({'type': part_type, 'text': text})
            if clean_parts:
                out[field_name] = clean_parts
        out.setdefault('summary', [])
        return out

    def merge_reasoning_item(self, items_by_key: dict, item: dict | None = None) -> None:
        """按输出顺序收集完整推理项，并对 done/completed 重复事件去重。"""
        clean = self.reasoning_input_item(item)
        if not clean:
            return
        key = str(clean.get('id') or '').strip()
        if not key:
            key = 'encrypted_' + str(clean.get('encrypted_content') or '')[:96]
        items_by_key[key] = clean

    def reasoning_input_items(self, items_by_key: dict | None = None) -> list[dict]:
        return [dict(item) for item in (items_by_key or {}).values() if isinstance(item, dict)]

    def response_output_input_item(self, item: dict | None = None) -> dict | None:
        """把 Responses 输出项规范化为后续 input 可接受的公开字段。"""
        row = item if isinstance(item, dict) else {}
        reasoning = self.reasoning_input_item(row)
        if reasoning:
            return reasoning
        if str(row.get('type') or '').strip().lower() != 'message':
            return None
        role = str(row.get('role') or 'assistant').strip().lower()
        if role != 'assistant':
            return None
        clean_content = []
        for part in (row.get('content') or []):
            if not isinstance(part, dict):
                continue
            part_type = str(part.get('type') or '').strip().lower()
            if part_type == 'output_text':
                text = str(part.get('text') or '').strip()
                if text:
                    clean_content.append({'type': 'output_text', 'text': text})
            elif part_type == 'refusal':
                refusal = str(part.get('refusal') or part.get('text') or '').strip()
                if refusal:
                    clean_content.append({'type': 'refusal', 'refusal': refusal})
        if not clean_content:
            return None
        out = {'type': 'message', 'role': 'assistant', 'content': clean_content}
        item_id = str(row.get('id') or '').strip()
        if item_id:
            out['id'] = item_id
        status = str(row.get('status') or '').strip()
        if status:
            out['status'] = status
        return out

    def merge_response_output_item(self, items_by_key: dict, item: dict | None = None) -> None:
        clean = self.response_output_input_item(item)
        if not clean:
            return
        key = str(clean.get('id') or '').strip()
        if not key:
            key = '%s_%s' % (str(clean.get('type') or 'item'), len(items_by_key or {}))
        items_by_key[key] = clean

    def response_output_input_items(self, items_by_key: dict | None = None) -> list[dict]:
        return [dict(item) for item in (items_by_key or {}).values() if isinstance(item, dict)]

    def image_generation_group_active(self, state_obj: dict | None = None, groups: list | None = None) -> bool:
        try:
            raw_groups = groups if groups is not None else ((state_obj or {}).get('active_tool_groups') or [])
            normalized = {str(x or '').strip().lower() for x in (self.capability_groups(raw_groups) or []) if str(x or '').strip()}
        except Exception:
            normalized = set()
        if 'all' in normalized or 'image_generate' in normalized:
            return True
        return bool((not normalized) and isinstance(state_obj, dict) and state_obj.get('image_generation_eager_first'))

    def clear_image_generation_turn_state(self, state_obj: dict | None = None, runtime_obj: dict | None = None) -> None:
        if isinstance(state_obj, dict):
            state_obj['image_task_type'] = ''
            state_obj['image_generation_attach_candidates'] = False
            state_obj['image_generation_eager_first'] = False
            state_obj.pop('image_generation_instruction', None)
            state_obj.pop('pending_responses_extra_input_items_for_image_generation', None)
        if isinstance(runtime_obj, dict):
            for key in (
                'image_task_type',
                'image_generation_attach_candidates',
                'image_generation_eager_first',
            ):
                runtime_obj.pop(key, None)

    def filter_tools_for_turn(self, specs: list | None = None, state_obj: dict | None = None) -> list:
        rows = [dict(x) if isinstance(x, dict) else x for x in (specs or [])]
        if self.image_generation_group_active(state_obj):
            return rows
        filtered = []
        removed = 0
        for row in rows:
            if isinstance(row, dict) and str(row.get('type') or '').strip().lower() == 'image_generation':
                removed += 1
                continue
            filtered.append(row)
        if removed:
            try:
                app_logger.warning(
                    '[RESPONSES_NATIVE_IMAGE_TOOL_FILTERED_FROM_NON_IMAGE_GROUP] groups=%s removed=%s',
                    json.dumps(self.capability_groups((state_obj or {}).get('active_tool_groups') or []), ensure_ascii=False),
                    removed,
                )
            except Exception:
                pass
        return filtered

    def strip_image_generation_input_items(self, items: list | None = None, state_obj: dict | None = None) -> list:
        if self.image_generation_group_active(state_obj):
            return list(items or [])
        out = []
        removed = 0
        for item in (items or []):
            if not isinstance(item, dict):
                out.append(item)
                continue
            typ = str(item.get('type') or '').strip().lower()
            if 'image_generation_call' in typ:
                removed += 1
                continue
            row = dict(item)
            content = row.get('content')
            if isinstance(content, list):
                clean_content = []
                for part in content:
                    part_typ = str((part or {}).get('type') or '').strip().lower() if isinstance(part, dict) else ''
                    if 'image_generation_call' in part_typ:
                        removed += 1
                        continue
                    clean_content.append(part)
                row['content'] = clean_content
            out.append(row)
        if removed:
            try:
                app_logger.warning(
                    '[RESPONSES_NATIVE_IMAGE_INPUT_STRIPPED_FROM_NON_IMAGE_GROUP] groups=%s removed=%s',
                    json.dumps(self.capability_groups((state_obj or {}).get('active_tool_groups') or []), ensure_ascii=False),
                    removed,
                )
            except Exception:
                pass
        return out


class ResponsesConversationTraceRegistry:
    """保存同一会话跨 HTTP job 的完整 Responses 输入轨迹。"""

    def __init__(self, *, ttl_seconds: float = 1800.0, max_entries: int = 64, max_chars: int = 1000000):
        import threading
        self.ttl_seconds = max(60.0, float(ttl_seconds or 1800.0))
        self.max_entries = max(4, int(max_entries or 64))
        self.max_chars = max(12000, int(max_chars or 1000000))
        self._entries: dict[str, dict] = {}
        self._lock = threading.RLock()

    def _key(self, session_id: str = '', endpoint: str = '', model: str = '') -> str:
        return '|'.join((
            str(session_id or '').strip()[:160],
            str(endpoint or '').strip().rstrip('/').lower(),
            str(model or '').strip().lower(),
        ))

    def context_signature(self, instructions: str = '', tools: list | None = None) -> str:
        import hashlib
        raw = json.dumps({
            'instructions': str(instructions or ''),
            'tools': list(tools or []),
        }, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def _item_role(self, item: dict | None = None) -> str:
        row = item if isinstance(item, dict) else {}
        role = str(row.get('role') or '').strip().lower()
        if str(row.get('type') or '').strip().lower() == 'message' and not role:
            role = 'assistant'
        return role

    def _item_text(self, item: dict | None = None) -> str:
        row = item if isinstance(item, dict) else {}
        content = row.get('content')
        if isinstance(content, str):
            return content.strip()
        parts = []
        for part in (content or []) if isinstance(content, list) else []:
            if not isinstance(part, dict):
                continue
            text = str(part.get('text') or part.get('refusal') or '').strip()
            if text:
                parts.append(text)
        return '\n'.join(parts).strip()

    def _is_runtime_item(self, item: dict | None = None) -> bool:
        return self._item_role(item) == 'user' and self._item_text(item).startswith('Runtime context:\n')

    def _without_runtime_items(self, items: list | None = None) -> list[dict]:
        """移除本轮动态 runtime，但保留同一 HTTP job 的完整原生轨迹。"""
        return [
            dict(item)
            for item in (items or [])
            if isinstance(item, dict) and not self._is_runtime_item(item)
        ]

    def _is_cross_http_ephemeral_item(self, item: dict | None = None) -> bool:
        """识别只服务当前 Responses 请求、不能作为长期会话历史的原生状态。"""
        item_type = str((item or {}).get('type') or '').strip().lower() if isinstance(item, dict) else ''
        return item_type in {'reasoning', 'web_search_call'}

    def _persistent_items(self, items: list | None = None) -> list[dict]:
        """跨 HTTP 只持久化真实会话与可继续使用的函数工具轨迹。"""
        return [
            item
            for item in self._without_runtime_items(items)
            if not self._is_cross_http_ephemeral_item(item)
        ]

    def with_runtime_tail(self, items: list | None = None) -> list[dict]:
        """保持真实历史/工具轨迹在前，本轮动态 runtime 永远位于 input 尾部。"""
        rows = [dict(item) for item in (items or []) if isinstance(item, dict)]
        runtime_rows = [row for row in rows if self._is_runtime_item(row)]
        return self._without_runtime_items(rows) + runtime_rows

    def append_before_runtime(
        self,
        items: list | None = None,
        additions: list | None = None,
    ) -> list[dict]:
        """追加工具/推理轨迹时不让它们落到 runtime 后面破坏可复用前缀。"""
        base_rows = [dict(item) for item in (items or []) if isinstance(item, dict)]
        added_rows = [dict(item) for item in (additions or []) if isinstance(item, dict)]
        runtime_rows = [row for row in base_rows + added_rows if self._is_runtime_item(row)]
        return self._without_runtime_items(base_rows) + self._without_runtime_items(added_rows) + runtime_rows

    def store(
        self,
        *,
        session_id: str,
        endpoint: str,
        model: str,
        context_signature: str,
        replay_items: list | None,
        last_user_text: str,
        assistant_text: str,
    ) -> bool:
        import copy
        import time
        key = self._key(session_id, endpoint, model)
        user_text = str(last_user_text or '').strip()
        answer_text = str(assistant_text or '').strip()
        rows = self._persistent_items(replay_items)
        if not key or not user_text or not answer_text or not rows:
            return False
        try:
            chars = len(json.dumps(rows, ensure_ascii=False, default=str))
        except Exception:
            return False
        if chars > self.max_chars:
            return False
        now = time.monotonic()
        with self._lock:
            expired = [
                entry_key for entry_key, entry in self._entries.items()
                if now - float((entry or {}).get('updated_at') or 0.0) > self.ttl_seconds
            ]
            for entry_key in expired:
                self._entries.pop(entry_key, None)
            self._entries[key] = {
                'context_signature': str(context_signature or ''),
                'replay_items': copy.deepcopy(rows),
                'last_user_text': user_text,
                'assistant_text': answer_text,
                'updated_at': now,
            }
            while len(self._entries) > self.max_entries:
                oldest_key = min(self._entries, key=lambda item_key: float((self._entries.get(item_key) or {}).get('updated_at') or 0.0))
                self._entries.pop(oldest_key, None)
        return True

    def restore(
        self,
        *,
        session_id: str,
        endpoint: str,
        model: str,
        context_signature: str,
        current_items: list | None,
    ) -> list[dict] | None:
        import copy
        import time
        key = self._key(session_id, endpoint, model)
        if not key:
            return None
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if not isinstance(entry, dict) or now - float(entry.get('updated_at') or 0.0) > self.ttl_seconds:
                self._entries.pop(key, None)
                return None
            if str(entry.get('context_signature') or '') != str(context_signature or ''):
                return None
            # 兼容修复前进程内已经累计的 trace；即使旧 entry 含 runtime，
            # 恢复时也立即清掉，避免继续扩散到后续轮次。
            stored_rows = self._persistent_items(copy.deepcopy(entry.get('replay_items') or []))
            previous_user = str(entry.get('last_user_text') or '').strip()
            previous_answer = str(entry.get('assistant_text') or '').strip()
        rows = [dict(item) for item in (current_items or []) if isinstance(item, dict)]
        matched_assistant_idx = -1
        for idx in range(len(rows) - 1, -1, -1):
            if self._item_role(rows[idx]) != 'assistant':
                continue
            current_answer = self._item_text(rows[idx])
            if current_answer == previous_answer or current_answer.startswith(previous_answer + '\n'):
                matched_assistant_idx = idx
                break
        if matched_assistant_idx < 0:
            return None
        matched_user = ''
        for idx in range(matched_assistant_idx - 1, -1, -1):
            if self._item_role(rows[idx]) == 'user' and not self._is_runtime_item(rows[idx]):
                matched_user = self._item_text(rows[idx])
                break
        if matched_user != previous_user:
            return None
        tail = rows[matched_assistant_idx + 1:]
        if not any(self._item_role(item) == 'user' and not self._is_runtime_item(item) for item in tail):
            return None
        return stored_rows + copy.deepcopy(tail)


_RESPONSES_CONVERSATION_TRACES = ResponsesConversationTraceRegistry()
