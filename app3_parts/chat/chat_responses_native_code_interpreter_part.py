# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: Responses-native code_interpreter event tracking and container file saving.
# Loaded before chat_streaming_part.py, sharing the original global namespace.

import base64
import json
import time
import urllib.parse


class ResponsesNativeCodeInterpreterContext:
    def __init__(
        self,
        *,
        model: str = '',
        endpoint: str = '',
        api_key: str = '',
        http_client=None,
        native_code_state: dict | None = None,
        state: dict | None = None,
        get_round_idx=None,
        sse=None,
        append_file_progress=None,
        merge_file_artifacts=None,
        file_progress_meta=None,
        runtime_model_meta=None,
        guess_content_type=None,
        logger=None,
    ):
        self.model = str(model or '')
        self.endpoint = str(endpoint or '')
        self.api_key = str(api_key or '')
        self.http_client = http_client
        self.native_code_state = native_code_state if isinstance(native_code_state, dict) else {}
        self.state = state if isinstance(state, dict) else {}
        self.get_round_idx = get_round_idx if callable(get_round_idx) else (lambda: 0)
        self.sse = sse if callable(sse) else (lambda event, payload=None: '')
        self.append_file_progress = append_file_progress if callable(append_file_progress) else (lambda state, item: None)
        self.merge_file_artifacts = merge_file_artifacts if callable(merge_file_artifacts) else (lambda state, rows: rows or [])
        self.file_progress_meta = file_progress_meta if callable(file_progress_meta) else (lambda state=None: {})
        self.runtime_model_meta = runtime_model_meta if callable(runtime_model_meta) else (lambda: {})
        self.guess_content_type = guess_content_type if callable(guess_content_type) else (lambda filename: 'application/octet-stream')
        self.logger = logger or globals().get('app_logger')

    def _round_idx(self) -> int:
        try:
            return int(self.get_round_idx() or 0)
        except Exception:
            return 0

    def _responses_container_file_content_endpoint(self, container_id: str = '', file_id: str = '') -> str:
        container_id = str(container_id or '').strip()
        file_id = str(file_id or '').strip()
        if not container_id or not file_id:
            return ''
        try:
            base = str(self.endpoint or '').strip().rstrip('/')
            low = base.lower()
            for suffix in ('/responses', '/chat/completions', '/completions'):
                if low.endswith(suffix):
                    base = base[:-len(suffix)].rstrip('/')
                    low = base.lower()
                    break
            cid = urllib.parse.quote(container_id, safe='')
            fid = urllib.parse.quote(file_id, safe='')
            return f'{base}/containers/{cid}/files/{fid}/content' if base else ''
        except Exception:
            return ''

    def _responses_native_note_code_seen(self, info: dict | None = None) -> None:
        self.native_code_state['seen'] = True
        self.state['native_code_interpreter_used'] = True
        self.state['file_tool_used'] = True
        if isinstance(info, dict):
            info['seen'] = True
        if not bool(self.native_code_state.get('counted')):
            self.native_code_state['counted'] = True
            self.state['file_tool_rounds'] = int(self.state.get('file_tool_rounds') or 0) + 1
            counts = self.state.setdefault('tool_counts', {})
            counts['code_interpreter_native'] = int(counts.get('code_interpreter_native') or 0) + 1
            self.append_file_progress(self.state, {
                'stage': 'code_interpreter_start',
                'tool': 'code_interpreter',
                'message': '正在运行官方 Python 沙盒',
                'percent': 55,
                'detail': 'Responses native code_interpreter',
                'ts': int(time.time() * 1000),
            })

    def _responses_native_code_status(self, event_type: str = '', payload: dict | None = None) -> str:
        event_low = str(event_type or '').strip().lower()
        raw_status = ''
        if isinstance(payload, dict):
            raw_status = str(payload.get('status') or payload.get('state') or '').strip().lower()
        if raw_status in {'completed', 'complete', 'done', 'success', 'succeeded'} or event_low.endswith('.completed'):
            return 'completed'
        if raw_status in {'failed', 'error', 'cancelled', 'canceled'} or event_low.endswith('.failed') or event_low.endswith('.error'):
            return 'error'
        if raw_status in {'running', 'in_progress', 'in-progress', 'queued', 'pending'} or event_low.endswith('.in_progress'):
            return 'in_progress'
        if 'code_interpreter' in event_low:
            return 'in_progress'
        return raw_status or ''

    def _responses_native_record_code_call(self, node, event_type: str = '', info: dict | None = None) -> int:
        if not isinstance(node, dict):
            return 0
        event_low = str(event_type or node.get('type') or node.get('event') or '').strip().lower()
        typ = str(node.get('type') or node.get('event') or '').strip().lower()
        if 'code_interpreter' not in event_low and 'code_interpreter' not in typ:
            return 0
        self._responses_native_note_code_seen(info)
        raw_call_id = str(node.get('item_id') or node.get('call_id') or node.get('id') or '').strip()
        if not raw_call_id:
            raw_call_id = 'native_code_call_' + str(len(self.native_code_state.get('call_order') or []) + 1)
        calls = self.native_code_state.setdefault('calls', {})
        if not isinstance(calls, dict):
            calls = {}
            self.native_code_state['calls'] = calls
        order = self.native_code_state.setdefault('call_order', [])
        if not isinstance(order, list):
            order = []
            self.native_code_state['call_order'] = order
        if raw_call_id not in calls:
            calls[raw_call_id] = {
                'id': raw_call_id,
                'short_id': raw_call_id[-10:],
                'status': '',
                'event': '',
                'round': self._round_idx(),
                'started_at': time.time(),
                'updated_at': time.time(),
                'done_at': 0.0,
                '_signature': '',
            }
            order.append(raw_call_id)
        call = calls[raw_call_id]
        status = self._responses_native_code_status(event_low, node)
        if status:
            call['status'] = status
        call['event'] = (event_low or typ)[:120]
        call['round'] = int(self._round_idx() or call.get('round') or 0)
        call['updated_at'] = time.time()
        if status in {'completed', 'error'}:
            call['done_at'] = call['updated_at']
        signature = json.dumps({
            'event': call.get('event'),
            'status': call.get('status'),
        }, ensure_ascii=False, sort_keys=True)
        if signature == str(call.get('_signature') or ''):
            return 0
        call['_signature'] = signature
        if isinstance(info, dict):
            info['added_calls'] = int(info.get('added_calls') or 0) + 1
        return 1

    def _responses_native_save_container_file(self, citation: dict | None = None) -> list[dict]:
        citation = dict(citation or {}) if isinstance(citation, dict) else {}
        container_id = str(citation.get('container_id') or citation.get('container') or '').strip()
        file_id = str(citation.get('file_id') or citation.get('file') or citation.get('id') or '').strip()
        filename = str(citation.get('filename') or citation.get('name') or '').strip()
        if not container_id or not file_id:
            return []
        save_key = f'{container_id}|{file_id}|{filename}'
        seen = self.native_code_state.setdefault('saved_file_seen', set())
        if save_key in seen:
            return []
        seen.add(save_key)
        url = self._responses_container_file_content_endpoint(container_id, file_id)
        if not url:
            return []
        try:
            dl_headers = {'Accept': 'application/octet-stream'}
            if self.api_key:
                dl_headers['Authorization'] = f'Bearer {self.api_key}'
            resp = self.http_client.get(url, headers=dl_headers, timeout=180.0)
            if int(getattr(resp, 'status_code', 0) or 0) >= 400:
                warning = f'container_file_download_failed:{getattr(resp, "status_code", "")}'
                self.native_code_state.setdefault('warnings', []).append(warning)
                try:
                    self.logger.warning('[RESPONSES_NATIVE_CODE_FILE_DOWNLOAD_FAILED] status=%s container_id=%s file_id=%s filename=%s url=%s body=%s', getattr(resp, 'status_code', ''), container_id, file_id, filename, url, str(getattr(resp, 'text', '') or '')[:500])
                except Exception:
                    pass
                return []
            raw = bytes(getattr(resp, 'content', b'') or b'')
            if not raw:
                self.native_code_state.setdefault('warnings', []).append('container_file_empty')
                return []
            mime = str(getattr(resp, 'headers', {}).get('content-type') or '').split(';', 1)[0].strip()
            if not filename:
                filename = (str(file_id or 'container_file') + '.bin')
            saver = globals().get('_save_artifacts_to_uploads')
            if not callable(saver):
                self.native_code_state.setdefault('warnings', []).append('artifact_saver_unavailable')
                return []
            saved = saver([{
                'filename': filename,
                'mime': mime or self.guess_content_type(filename),
                'encoding': 'base64',
                'data': base64.b64encode(raw).decode('ascii'),
                'source_role': 'assistant_generated',
                'container_id': container_id,
                'file_id': file_id,
            }])
            saved_rows = [dict(x) for x in (saved or []) if isinstance(x, dict)]
            if not saved_rows:
                self.native_code_state.setdefault('warnings', []).append('container_file_save_failed')
                return []
            for row in saved_rows:
                row.setdefault('container_id', container_id)
                row.setdefault('file_id', file_id)
                row.setdefault('source_type', 'generated')
                row.setdefault('generated_by_assistant', True)
            added = self.merge_file_artifacts(self.state, saved_rows)
            self.native_code_state.setdefault('saved_files', []).extend(added or saved_rows)
            names = [str((x or {}).get('filename') or filename) for x in (added or saved_rows) if isinstance(x, dict)]
            self.append_file_progress(self.state, {
                'stage': 'code_interpreter_file_saved',
                'tool': 'code_interpreter',
                'message': 'Python 沙盒已生成文件：' + ('、'.join(names[:4]) if names else filename),
                'target_filename': names[0] if names else filename,
                'percent': 100,
                'detail': f'container_id={container_id} file_id={file_id}',
                'ts': int(time.time() * 1000),
            })
            return added or saved_rows
        except Exception as err:
            self.native_code_state.setdefault('warnings', []).append('container_file_download_exception')
            try:
                self.logger.exception('[RESPONSES_NATIVE_CODE_FILE_SAVE_FAILED] container_id=%s file_id=%s filename=%s err=%s', container_id, file_id, filename, err)
            except Exception:
                pass
            return []

    def _responses_native_collect_code_interpreter_payload(self, payload, event_type: str = '') -> dict:
        info = {'seen': False, 'added_calls': 0, 'added_citations': 0, 'saved_files': []}
        if not isinstance(payload, dict):
            return info
        event_low = str(event_type or '').strip().lower()
        if 'code_interpreter' in event_low:
            self._responses_native_note_code_seen(info)
            self._responses_native_record_code_call(payload, event_type, info)

        def add_citation(node: dict) -> None:
            if not isinstance(node, dict):
                return
            typ = str(node.get('type') or '').strip().lower()
            src = node.get('container_file_citation') if isinstance(node.get('container_file_citation'), dict) else node
            if typ != 'container_file_citation' and not isinstance(node.get('container_file_citation'), dict):
                return
            container_id = str(src.get('container_id') or src.get('container') or '').strip()
            file_id = str(src.get('file_id') or src.get('file') or src.get('id') or '').strip()
            filename = str(src.get('filename') or src.get('name') or '').strip()
            if not container_id or not file_id:
                return
            self._responses_native_note_code_seen(info)
            key = f'{container_id}|{file_id}|{filename}'
            seen = self.native_code_state.setdefault('citation_seen', set())
            if key not in seen:
                seen.add(key)
                citation = {'type': 'container_file_citation', 'container_id': container_id, 'file_id': file_id, 'filename': filename}
                self.native_code_state.setdefault('citations', []).append(citation)
                info['added_citations'] = int(info.get('added_citations') or 0) + 1
                saved = self._responses_native_save_container_file(citation)
                if saved:
                    info.setdefault('saved_files', []).extend(saved)

        def walk(node, depth: int = 0) -> None:
            if depth > 9 or node is None:
                return
            if isinstance(node, dict):
                typ = str(node.get('type') or node.get('event') or '').strip().lower()
                if 'code_interpreter' in typ:
                    self._responses_native_note_code_seen(info)
                    self._responses_native_record_code_call(node, event_type, info)
                add_citation(node)
                if 'annotations' in node:
                    walk(node.get('annotations'), depth + 1)
                for value in node.values():
                    if isinstance(value, (dict, list, tuple)):
                        walk(value, depth + 1)
            elif isinstance(node, (list, tuple)):
                for row in node[:160]:
                    walk(row, depth + 1)

        walk(payload, 0)
        return info

    def _responses_native_code_interpreter_meta_frame(self, stage: str = 'code_interpreter') -> str | None:
        calls = self.native_code_state.get('calls') if isinstance(self.native_code_state.get('calls'), dict) else {}
        order = [str(x or '').strip() for x in (self.native_code_state.get('call_order') or []) if str(x or '').strip()]
        call_rows = []
        for call_id in order[-12:]:
            row = calls.get(call_id) if isinstance(calls, dict) else None
            if not isinstance(row, dict):
                continue
            call_rows.append({
                'id': str(row.get('id') or call_id),
                'short_id': str(row.get('short_id') or call_id)[-10:],
                'status': str(row.get('status') or '').strip(),
                'event': str(row.get('event') or '').strip()[:120],
                'round': int(row.get('round') or 0),
            })
        citations = [dict(x) for x in (self.native_code_state.get('citations') or []) if isinstance(x, dict)]
        saved_files = [dict(x) for x in (self.native_code_state.get('saved_files') or []) if isinstance(x, dict)]
        if not (bool(self.native_code_state.get('seen')) or call_rows or citations or saved_files):
            return None
        sig = json.dumps({
            'stage': str(stage or ''),
            'calls': call_rows,
            'citations': citations[-12:],
            'files': [(str(x.get('download_url') or ''), str(x.get('filename') or '')) for x in saved_files[-12:]],
        }, ensure_ascii=False, sort_keys=True)
        if sig == str(self.native_code_state.get('meta_signature') or ''):
            return None
        self.native_code_state['meta_signature'] = sig
        return self.sse('meta', {
            'model': self.model,
            'mode': 'responses_native_tools',
            'route_mode': 'responses_native_agent',
            'native_code_interpreter': True,
            'code_interpreter_stage': str(stage or 'code_interpreter'),
            'code_interpreter_call_count': len(call_rows),
            'code_interpreter_calls': call_rows,
            'code_interpreter_citation_count': len(citations),
            'code_interpreter_citations': citations,
            'code_interpreter_file_count': len(saved_files),
            'code_interpreter_files': saved_files,
            'code_interpreter_warnings': [str(x or '') for x in (self.native_code_state.get('warnings') or []) if str(x or '').strip()][-8:],
            **self.file_progress_meta(self.state),
            **self.runtime_model_meta(),
        })
