# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: tool delta parsing, sandbox status frames, and doc visual review bookkeeping.
# Loaded before chat_streaming_part.py, sharing the original global namespace.

import json
import re
import time


class ChatStreamToolRuntimeContext:
    def __init__(self, *, label: str = '', sse=None, append_file_progress=None, append_focus_crop_activity=None, activity_delta_frame=None):
        self.label = str(label or '')
        self.sse = sse if callable(sse) else (lambda event, payload=None: '')
        self.append_file_progress = append_file_progress if callable(append_file_progress) else (lambda state=None, item=None: None)
        self.append_focus_crop_activity = append_focus_crop_activity if callable(append_focus_crop_activity) else (lambda state=None, result=None, **kwargs: {})
        self.activity_delta_frame = activity_delta_frame if callable(activity_delta_frame) else (lambda state=None: '')

    def _agent_stream_holder_get(self, obj, name: str):
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    def _agent_stream_extract_tool_deltas(self, chunk) -> list[dict]:
        out = []
        try:
            choices = getattr(chunk, 'choices', None)
            if not choices:
                return out
            c0 = choices[0]
            for holder in (getattr(c0, 'delta', None), getattr(c0, 'message', None), c0):
                if holder is None:
                    continue
                calls = self._agent_stream_holder_get(holder, 'tool_calls') or self._agent_stream_holder_get(holder, 'toolCalls')
                if not calls:
                    continue
                if isinstance(calls, dict):
                    calls = [calls]
                for tc in calls or []:
                    fn = self._agent_stream_holder_get(tc, 'function') or {}
                    out.append({
                        'index': self._agent_stream_holder_get(tc, 'index'),
                        'id': self._agent_stream_holder_get(tc, 'id'),
                        'type': self._agent_stream_holder_get(tc, 'type') or 'function',
                        'name': self._agent_stream_holder_get(fn, 'name'),
                        'arguments': self._agent_stream_holder_get(fn, 'arguments'),
                    })
                if out:
                    return out
        except Exception:
            return []
        return out

    def _agent_stream_choice_finish_reason(self, chunk) -> str:
        try:
            choices = getattr(chunk, 'choices', None)
            if not choices:
                return ''
            c0 = choices[0]
            return str(self._agent_stream_holder_get(c0, 'finish_reason') or '').strip().lower()
        except Exception:
            return ''

    def _agent_stream_parse_args(self, raw: str) -> dict:
        text = str(raw or '').strip()
        if not text:
            return {}
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else {'value': obj}
        except Exception:
            return {'_invalid_json_arguments': text[:4000]}

    def _agent_stream_status_text(self, tool_name: str) -> str:
        nm = str(tool_name or '').strip()
        if nm == 'save_memory':
            return '???????'
        if nm == 'web_search':
            return f'{self.label} ???????'
        if nm == 'search_knowledge_base':
            return f'{self.label} ????????'
        if nm == 'read_knowledge_base_document':
            return f'{self.label} ??????????'
        if nm in {'search_account_context', 'read_account_context'}:
            return f'{self.label} ?????????'
        if nm == 'image_search':
            return f'{self.label} ???????'
        if nm == 'analyze_existing_image':
            return f'{self.label} ???????'
        if nm in {'fetch_url', 'fetch_urls'}:
            return f'{self.label} ???????'
        if nm == 'sandbox_import_files':
            return f'{self.label} ??????????'
        if nm == 'sandbox_list_files':
            return f'{self.label} ?????????'
        if nm == 'sandbox_resolve_file_context':
            return f'{self.label} ??????????'
        if nm == 'sandbox_diff_files':
            return f'{self.label} ?????????'
        if nm == 'sandbox_read_file':
            return f'{self.label} ?????????'
        if nm == 'sandbox_analyze_file_images':
            return f'{self.label} ???????????'
        if nm in {'sandbox_write_file', 'sandbox_write_files', 'sandbox_replace_text'}:
            return f'{self.label} ?????????'
        if nm == 'sandbox_create_office_file':
            return f'{self.label} ???? Office/PDF ???'
        if nm == 'sandbox_publish_files':
            return f'{self.label} ?????????'
        if nm == 'sandbox_run':
            return f'{self.label} ?????????'
        if nm == 'get_weather':
            return f'{self.label} ???????'
        if nm == 'get_location':
            return f'{self.label} ???????'
        if nm == 'handoff_to_image_delivery':
            return f'{self.label} ???????????'
        return f'{self.label} ???????'

    def _agent_stream_is_sandbox_tool(self, name: str = '') -> bool:
        try:
            names = globals().get('SANDBOX_TOOL_NAMES')
            return str(name or '').strip() in (names if isinstance(names, set) else set())
        except Exception:
            return str(name or '').strip().startswith('sandbox_')

    def _agent_stream_sandbox_status_frame(self, name: str = '', args: dict | None = None, result: dict | None = None, *, phase: str = 'start', state: dict | None = None, call_id: str = '') -> str:
        progress_builder = globals().get('_sandbox_tool_progress_payload')
        progress_args = dict(args or {}) if isinstance(args, dict) else {}
        call_id_text = str(call_id or progress_args.get('_activity_call_id') or progress_args.get('_tool_call_id') or progress_args.get('tool_call_id') or '').strip()
        if call_id_text:
            # Keep ActivityEvent identity tied to the actual tool call.  This lets
            # start/done merge for one call while repeated sandbox_run calls stay
            # as separate timeline rows, even when the shell command text is the same.
            progress_args['_activity_call_id'] = call_id_text
            progress_args['_tool_call_id'] = call_id_text
        payload = progress_builder(name, progress_args, result or {}, phase=phase) if callable(progress_builder) else {
            'stage': 'sandbox_done' if phase == 'done' else 'sandbox_start',
            'message': self._agent_stream_status_text(name),
            'percent': 100 if phase == 'done' else 5,
            'ts': int(time.time() * 1000),
        }
        if isinstance(state, dict) and isinstance(payload, dict):
            self.append_file_progress(state, payload)
            if str(name or '').strip() == 'sandbox_analyze_file_images' and str(phase or '').strip().lower() == 'done' and isinstance(result, dict):
                crop_op_key = call_id_text or str(progress_args.get('path') or progress_args.get('filename') or result.get('visual_exec_id') or '').strip()
                self.append_focus_crop_activity(state, result, op_key=crop_op_key)
        return self.sse('status', {'text': str((payload or {}).get('message') or self._agent_stream_status_text(name)), 'file_progress': payload}) + self.activity_delta_frame(state)

    def _agent_stream_sandbox_arguments_status_frame(self, state: dict | None = None, calls_acc=None, *, force: bool = False) -> str:
        if not isinstance(state, dict):
            return ''
        rows = []
        try:
            source = calls_acc.values() if isinstance(calls_acc, dict) else (calls_acc or [])
            for row in source:
                if isinstance(row, dict):
                    rows.append(row)
        except Exception:
            rows = []
        active_tool = ''
        arg_chars = 0
        for row in rows:
            fn = row.get('function') if isinstance(row.get('function'), dict) else {}
            name = str(fn.get('name') or row.get('name') or '').strip()
            args_text = str(fn.get('arguments') or row.get('arguments') or '')
            if name in {'sandbox_write_file', 'sandbox_write_files', 'sandbox_create_office_file', 'sandbox_replace_text'} or name.startswith('sandbox_write_file'):
                active_tool = name if name in {'sandbox_write_files', 'sandbox_create_office_file', 'sandbox_replace_text'} else 'sandbox_write_file'
                arg_chars += len(args_text)
        if not active_tool:
            return ''
        now_status = time.time()
        if not force and bool(state.get('sandbox_arguments_progress_emitted')) and now_status - float(state.get('sandbox_arguments_progress_last_at') or 0.0) < 6.0:
            return ''
        state['sandbox_arguments_progress_emitted'] = True
        state['sandbox_arguments_progress_last_at'] = now_status
        progress = {
            'stage': 'sandbox_arguments_streaming',
            'tool': active_tool,
            'message': '????????',
            'detail': '',
            'percent': 8,
            'ts': int(now_status * 1000),
        }
        self.append_file_progress(state, progress)
        return self.sse('status', {'text': f'{self.label} ?????????', 'file_progress': progress}) + self.activity_delta_frame(state)

    def _agent_stream_doc_visual_review_required(self, result: dict | None = None) -> bool:
        if not isinstance(result, dict):
            return False
        summary = result.get('document_diagnostic_summary')
        if isinstance(summary, dict) and bool(summary.get('requires_visual_review')):
            return True
        if bool(result.get('requires_visual_review')):
            return True
        if str(result.get('document_continue_instruction') or '').strip():
            return True
        return False

    def _agent_stream_doc_visual_review_args(self, read_result: dict | None = None, read_args: dict | None = None, user_text: str = '') -> dict:
        row = read_result if isinstance(read_result, dict) else {}
        arg = read_args if isinstance(read_args, dict) else {}
        path = str(row.get('path') or arg.get('path') or arg.get('filename') or '').strip()
        if not path:
            return {}
        return {
            'path': path,
            'query': str(user_text or '').strip(),
            'max_images': 24,
            'max_pages': 24,
        }

    def _agent_stream_doc_visual_review_path_key(self, path: str = '') -> str:
        raw = str(path or '').strip().replace('\\', '/')
        if not raw:
            return ''
        raw = re.sub(r'/+', '/', raw)
        low = raw.lower()
        for prefix in ('/mnt/data/', '/sandbox/'):
            if low.startswith(prefix):
                raw = raw[len(prefix):]
                break
        return raw.strip('/').lower()

    def _agent_stream_doc_visual_review_mark_done(self, state: dict | None = None, path: str = '') -> bool:
        if not isinstance(state, dict):
            return False
        key = self._agent_stream_doc_visual_review_path_key(path)
        if not key:
            return False
        seen = state.setdefault('doc_visual_review_paths', set())
        if not isinstance(seen, set):
            try:
                seen = set(self._agent_stream_doc_visual_review_path_key(str(x or '')) for x in (seen or []) if str(x or '').strip())
                seen = {x for x in seen if x}
            except Exception:
                seen = set()
            state['doc_visual_review_paths'] = seen
        already = key in seen
        seen.add(key)
        runtime_state_obj = state.get('_runtime_state')
        if isinstance(runtime_state_obj, dict):
            runtime_seen = runtime_state_obj.setdefault('doc_visual_review_paths', set())
            if not isinstance(runtime_seen, set):
                try:
                    runtime_seen = set(self._agent_stream_doc_visual_review_path_key(str(x or '')) for x in (runtime_seen or []) if str(x or '').strip())
                    runtime_seen = {x for x in runtime_seen if x}
                except Exception:
                    runtime_seen = set()
                runtime_state_obj['doc_visual_review_paths'] = runtime_seen
            runtime_seen.add(key)
        return already

    def _agent_stream_doc_visual_review_cache_get(self, state: dict | None = None, path: str = '') -> dict:
        if not isinstance(state, dict):
            return {}
        key = self._agent_stream_doc_visual_review_path_key(path)
        if not key:
            return {}
        cache = state.get('doc_visual_review_result_cache')
        if not isinstance(cache, dict):
            runtime_state_obj = state.get('_runtime_state')
            cache = runtime_state_obj.get('doc_visual_review_result_cache') if isinstance(runtime_state_obj, dict) else {}
        if not isinstance(cache, dict):
            return {}
        cached = cache.get(key)
        if not isinstance(cached, dict):
            runtime_state_obj = state.get('_runtime_state')
            runtime_cache = runtime_state_obj.get('doc_visual_review_result_cache') if isinstance(runtime_state_obj, dict) else {}
            cached = runtime_cache.get(key) if isinstance(runtime_cache, dict) else {}
        if not isinstance(cached, dict):
            return {}
        out = dict(cached)
        out['_reused_cached_tool_result'] = True
        out['_cache_key'] = key
        return out

    def _agent_stream_doc_visual_review_cache_put(self, state: dict | None = None, result: dict | None = None, args: dict | None = None) -> str:
        if not isinstance(state, dict) or not isinstance(result, dict):
            return ''
        arg = args if isinstance(args, dict) else {}
        key = self._agent_stream_doc_visual_review_path_key(str(result.get('path') or arg.get('path') or arg.get('filename') or ''))
        if not key:
            return ''
        cache = state.setdefault('doc_visual_review_result_cache', {})
        if not isinstance(cache, dict):
            cache = {}
            state['doc_visual_review_result_cache'] = cache
        cached = dict(result)
        if isinstance(result.get('_responses_input_items'), list):
            cached['_responses_input_items'] = [dict(x) if isinstance(x, dict) else x for x in result.get('_responses_input_items') or []]
        cached['_cache_key'] = key
        cache[key] = cached
        runtime_state_obj = state.get('_runtime_state')
        if isinstance(runtime_state_obj, dict):
            runtime_cache = runtime_state_obj.setdefault('doc_visual_review_result_cache', {})
            if isinstance(runtime_cache, dict):
                runtime_cache[key] = dict(cached)
            else:
                runtime_state_obj['doc_visual_review_result_cache'] = {key: dict(cached)}
        self._agent_stream_doc_visual_review_mark_done(state, key)
        return key

    def _agent_stream_planned_doc_visual_review_paths(self, calls: list | None = None) -> set[str]:
        planned: set[str] = set()
        for call in (calls or []):
            if not isinstance(call, dict):
                continue
            fn = call.get('function') if isinstance(call.get('function'), dict) else {}
            name = str(fn.get('name') or call.get('name') or '').strip()
            if name != 'sandbox_analyze_file_images':
                continue
            raw_args = str(fn.get('arguments') or call.get('arguments') or '{}')
            try:
                args = self._agent_stream_parse_args(raw_args)
            except Exception:
                args = {}
            key = self._agent_stream_doc_visual_review_path_key(str((args or {}).get('path') or (args or {}).get('filename') or ''))
            if key:
                planned.add(key)
        return planned

    def _agent_stream_doc_visual_review_already_done(self, state: dict | None = None, path: str = '') -> bool:
        if not isinstance(state, dict):
            return False
        key = self._agent_stream_doc_visual_review_path_key(path)
        if not key:
            return False
        seen = state.setdefault('doc_visual_review_paths', set())
        if not isinstance(seen, set):
            try:
                seen = set(self._agent_stream_doc_visual_review_path_key(str(x or '')) for x in (seen or []) if str(x or '').strip())
                seen = {x for x in seen if x}
            except Exception:
                seen = set()
            state['doc_visual_review_paths'] = seen
        if key in seen:
            return True
        runtime_state_obj = state.get('_runtime_state')
        runtime_seen = runtime_state_obj.get('doc_visual_review_paths') if isinstance(runtime_state_obj, dict) else set()
        if not isinstance(runtime_seen, set):
            try:
                runtime_seen = set(self._agent_stream_doc_visual_review_path_key(str(x or '')) for x in (runtime_seen or []) if str(x or '').strip())
                runtime_seen = {x for x in runtime_seen if x}
                if isinstance(runtime_state_obj, dict):
                    runtime_state_obj['doc_visual_review_paths'] = runtime_seen
            except Exception:
                runtime_seen = set()
        if key in runtime_seen:
            seen.add(key)
            return True
        seen.add(key)
        return False
