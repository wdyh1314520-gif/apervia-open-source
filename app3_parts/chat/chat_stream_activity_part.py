# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: turn-scoped ActivityEvent timeline, progress metadata, and file progress aggregation.
# Loaded before chat_streaming_part.py, sharing the original global namespace.


class ChatStreamActivityTimeline:
    def __init__(self):
        self.seq = 0

    def sync_from_state(self, state: dict | None = None) -> None:
        if not isinstance(state, dict):
            return
        try:
            self.seq = max(int(self.seq or 0), int(state.get('_activity_event_seq') or 0))
        except Exception:
            pass

    def next(self, state: dict | None = None) -> int:
        self.sync_from_state(state)
        self.seq = int(self.seq or 0) + 1
        return int(self.seq)

    def last(self, state: dict | None = None) -> int:
        self.sync_from_state(state)
        try:
            return int(self.seq or 0)
        except Exception:
            return 0


class ChatStreamActivityContext:
    def __init__(self, *, client_session_id: str = '', client_session_title: str = '', activity_turn_id: str = ''):
        self.client_session_id = str(client_session_id or '')
        self.client_session_title = str(client_session_title or '')
        self.activity_turn_id = str(activity_turn_id or '')
        self.timeline = ChatStreamActivityTimeline()

    def sync_seq_from_state(self, state: dict | None = None) -> None:
        self.timeline.sync_from_state(state)

    def next_seq(self, state: dict | None = None) -> int:
        return self.timeline.next(state)

    def last_seq(self, state: dict | None = None) -> int:
        return self.timeline.last(state)

    def append_progress_event(self, state: dict | None = None, item: dict | None = None) -> dict:
        if not isinstance(state, dict) or not isinstance(item, dict):
            return {}
        upsert = globals().get('_activity_event_upsert_state')
        if not callable(upsert):
            return {}
        try:
            event_item = dict(item or {})
            if self.client_session_id:
                event_item.setdefault('client_session_id', self.client_session_id)
                event_item.setdefault('clientSessionId', self.client_session_id)
                event_item.setdefault('session_id', self.client_session_id)
                event_item.setdefault('sessionId', self.client_session_id)
            if self.client_session_title:
                event_item.setdefault('client_session_title', self.client_session_title)
                event_item.setdefault('clientSessionTitle', self.client_session_title)
            if self.activity_turn_id:
                event_item.setdefault('activity_turn_id', self.activity_turn_id)
                event_item.setdefault('activityTurnId', self.activity_turn_id)
            try:
                if not int(float(event_item.get('seq') or event_item.get('order') or 0)):
                    seq = self.next_seq(state)
                    event_item['seq'] = seq
                    event_item['order'] = seq
            except Exception:
                seq = self.next_seq(state)
                event_item['seq'] = seq
                event_item['order'] = seq
            return upsert(state, event_item) or {}
        except Exception:
            try:
                app_logger.exception('[activity_event] upsert_failed')
            except Exception:
                pass
            return {}

    def progress_meta(self, state: dict | None = None) -> dict:
        meta_fn = globals().get('_activity_events_meta')
        if not callable(meta_fn):
            return {}
        try:
            return meta_fn(state, include_legacy=False) or {}
        except Exception:
            try:
                app_logger.exception('[activity_event] meta_failed')
            except Exception:
                pass
            return {}

    def activity_delta_frame(self, state: dict | None = None) -> str:
        if not isinstance(state, dict):
            return ''
        row = state.get('_last_activity_event') if isinstance(state.get('_last_activity_event'), dict) else None
        if not row:
            return ''
        try:
            sig = json.dumps(row, ensure_ascii=False, sort_keys=True)
        except Exception:
            sig = str(row)
        if sig == str(state.get('_last_activity_event_emitted_sig') or ''):
            return ''
        state['_last_activity_event_emitted_sig'] = sig
        return sse('activity', {'activity_event': dict(row)})
    @staticmethod
    def file_progress_dedupe_key(row: dict | None) -> str:
        if not isinstance(row, dict):
            return ''
        row_stage = str(row.get('stage') or row.get('kind') or '').strip()
        row_tool = str(row.get('tool') or row.get('tool_name') or row.get('name') or '').strip()
        row_msg = str(row.get('message') or row.get('text') or '').strip()
        row_percent = str(row.get('percent') or '').strip()
        row_detail = str(row.get('detail') or row.get('description') or '').strip()
        row_target = str(row.get('target_filename') or row.get('filename') or '').strip()
        row_operation = str(row.get('operation_key') or row.get('operationKey') or '').strip()
        row_command = str(row.get('display_command') or row.get('displayCommand') or row.get('command') or row.get('list_command') or row.get('listCommand') or '').strip()
        row_stdout = str(row.get('stdout') or row.get('list_output') or row.get('listOutput') or '').strip()
        row_stderr = str(row.get('stderr') or '').strip()
        low_tool = row_tool.lower()
        low_stage = row_stage.lower()
        if low_tool in {'sandbox_run', 'sandbox_list_files'} or low_stage in {'sandbox_start', 'sandbox_done', 'sandbox_error'} and low_tool in {'sandbox_run', 'sandbox_list_files'}:
            specific = row_operation or str(row.get('key') or row.get('progressKey') or row.get('progress_key') or '').strip() or row_command
            if not specific and (row_stdout or row_stderr):
                specific = (row_stdout[:220] + '|' + row_stderr[:220]).strip('|')
            if specific:
                return '|'.join([row_stage, row_tool, specific, row_percent])[:1000]
        return '|'.join([
            row_stage,
            row_tool,
            row_msg,
            row_target,
            row_percent,
            row_detail,
        ])[:600]

    def append_file_progress(self, state: dict | None = None, item: dict | None = None) -> dict | None:
        if not isinstance(state, dict) or not isinstance(item, dict):
            return None
        msg = str(item.get('message') or item.get('text') or '').strip()
        if not msg:
            return None
        rows = state.setdefault('file_progress_items', [])
        if not isinstance(rows, list):
            rows = []
            state['file_progress_items'] = rows
        replace_stages = {'sandbox_arguments_streaming'}
        stage = str(item.get('stage') or item.get('kind') or '').strip()
        tool = str(item.get('tool') or item.get('tool_name') or item.get('name') or '').strip()
        if stage in replace_stages:
            rows[:] = [
                x for x in rows
                if not (
                    isinstance(x, dict)
                    and str(x.get('stage') or x.get('kind') or '').strip() == stage
                    and str(x.get('tool') or x.get('tool_name') or x.get('name') or '').strip() == tool
                )
            ]
        key = self.file_progress_dedupe_key(item)
        for old_item in rows:
            if not isinstance(old_item, dict):
                continue
            if self.file_progress_dedupe_key(old_item) == key:
                return None
        obj = dict(item)
        obj.setdefault('ts', int(time.time() * 1000))
        rows.append(obj)
        activity_row = self.append_progress_event(state, {**obj, 'source': 'file_progress'})
        if len(rows) > 80:
            del rows[:-80]
        state['file_tool_used'] = True
        return activity_row

    def file_progress_meta(self, state: dict | None = None) -> dict:
        state = state or {}
        rows = [dict(x) for x in (state.get('file_progress_items') or []) if isinstance(x, dict)] if isinstance(state, dict) else []
        artifacts = [dict(x) for x in (state.get('file_artifacts') or []) if isinstance(x, dict)] if isinstance(state, dict) else []
        audits = [dict(x) for x in (state.get('file_edit_audits') or []) if isinstance(x, dict)] if isinstance(state, dict) else []
        return {
            'file_tool_used': bool((state or {}).get('file_tool_used') or rows or artifacts),
            'file_tool_rounds': int((state or {}).get('file_tool_rounds') or 0),
            'file_progress_items': rows,
            'artifacts': artifacts,
            'artifact_count': len(artifacts),
            'artifact_filenames': [str((item or {}).get('filename') or '') for item in artifacts if isinstance(item, dict)],
            'file_edit_audits': audits,
            **self.progress_meta(state),
        }

    @staticmethod
    def merge_file_artifacts(state: dict | None = None, files: list | None = None) -> list[dict]:
        if not isinstance(state, dict):
            return []
        rows = state.setdefault('file_artifacts', [])
        if not isinstance(rows, list):
            rows = []
            state['file_artifacts'] = rows
        seen = {
            (str((x or {}).get('download_url') or '').strip(), str((x or {}).get('filename') or '').strip())
            for x in rows if isinstance(x, dict)
        }
        added: list[dict] = []
        for item in (files or []):
            if not isinstance(item, dict):
                continue
            row = dict(item)
            key = (str(row.get('download_url') or '').strip(), str(row.get('filename') or '').strip())
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            added.append(row)
        state['file_tool_used'] = bool(rows or state.get('file_tool_used'))
        return added

    def note_sandbox_publish_result(self, state: dict | None = None, result: dict | None = None, args: dict | None = None) -> dict:
        result = result or {}
        args = args or {}
        if not isinstance(state, dict):
            return {}
        state['file_tool_used'] = True
        state['file_tool_rounds'] = int(state.get('file_tool_rounds') or 0) + 1
        if bool(result.get('ok')):
            state['sandbox_published'] = True
        files = [dict(x) for x in (result.get('files') or []) if isinstance(x, dict)] if isinstance(result, dict) else []
        added = self.merge_file_artifacts(state, files)
        meta = self.file_progress_meta(state)
        meta['new_artifacts'] = added
        return meta

    def note_sandbox_write_result(self, state: dict | None = None, name: str = '', result: dict | None = None, args: dict | None = None) -> None:
        if not isinstance(state, dict) or not isinstance(result, dict):
            return
        nm = str(name or '').strip()
        if nm not in {'sandbox_write_file', 'sandbox_write_files', 'sandbox_create_office_file', 'sandbox_replace_text', 'sandbox_run'}:
            return
        if not (bool(result.get('ok')) or bool(result.get('partial_ok'))):
            return
        if isinstance(result.get('files'), list) and result.get('files'):
            try:
                self.merge_file_artifacts(state, [dict(x) for x in (result.get('files') or []) if isinstance(x, dict)])
                state['sandbox_published'] = True
            except Exception:
                pass
        new_audits: list[dict] = []

        def push_audit(value) -> None:
            if isinstance(value, dict) and value:
                new_audits.append(dict(value))

        push_audit(result.get('file_edit_audit'))
        push_audit(result.get('edit_audit'))
        for key in ('file_edit_audits', 'edit_audits'):
            for audit in (result.get(key) or []):
                push_audit(audit)
        for item in (result.get('files') or []):
            if isinstance(item, dict):
                push_audit(item.get('file_edit_audit'))
                push_audit(item.get('edit_audit'))
        if new_audits:
            audit_rows = state.setdefault('file_edit_audits', [])
            if not isinstance(audit_rows, list):
                audit_rows = []
                state['file_edit_audits'] = audit_rows
            seen_audits = {
                str((x or {}).get('audit_id') or '').strip() or (str((x or {}).get('output_filename') or '') + '|' + str((x or {}).get('new_sha256') or ''))
                for x in audit_rows if isinstance(x, dict)
            }
            for audit in new_audits:
                key = str(audit.get('audit_id') or '').strip() or (str(audit.get('output_filename') or '') + '|' + str(audit.get('new_sha256') or ''))
                if key and key not in seen_audits:
                    audit_rows.append(audit)
                    seen_audits.add(key)
        paths: list[str] = []
        if nm == 'sandbox_run':
            for key in ('output_paths', 'created_paths', 'changed_paths'):
                for p in (result.get(key) or []):
                    p = str(p or '').strip()
                    if p:
                        paths.append(p)
        elif nm in {'sandbox_write_file', 'sandbox_create_office_file', 'sandbox_replace_text'}:
            p = str(result.get('path') or (args or {}).get('path') or '').strip()
            if p:
                paths.append(p)
        else:
            for item in (result.get('files') or []):
                if isinstance(item, dict):
                    p = str(item.get('path') or '').strip()
                    if p:
                        paths.append(p)
        if not paths:
            return
        rows = state.setdefault('sandbox_written_paths', [])
        if not isinstance(rows, list):
            rows = []
            state['sandbox_written_paths'] = rows
        seen = {str(x or '').strip().lower() for x in rows if str(x or '').strip()}
        for p in paths:
            key = p.lower()
            if key not in seen:
                rows.append(p)
                seen.add(key)
        if isinstance(result.get('files'), list) and result.get('files'):
            state['sandbox_published'] = True
        else:
            state['sandbox_published'] = False

    @staticmethod
    def attach_sandbox_audits_to_publish_args(state: dict | None = None, name: str = '', args: dict | None = None) -> dict:
        row = dict(args or {})
        if str(name or '').strip() != 'sandbox_publish_files':
            return row
        audits = [dict(x) for x in ((state or {}).get('file_edit_audits') or []) if isinstance(x, dict)]
        if audits and not isinstance(row.get('file_edit_audits'), list):
            row['file_edit_audits'] = audits[-200:]
        return row
