# file-context selection, prompt-cache text injection, and sandbox manifest messages.

import os
import re
import time


class ChatStreamFileContext:
    def __init__(self, *, append_file_progress=None, single_sandbox_file_plane_enabled=None):
        self.append_file_progress = append_file_progress if callable(append_file_progress) else (lambda state=None, item=None: None)
        self.single_sandbox_file_plane_enabled = single_sandbox_file_plane_enabled if callable(single_sandbox_file_plane_enabled) else (lambda: False)

    def _agent_stream_public_file_label(self, value) -> str:
        raw = str(value or '').replace('\\', '/').strip()
        if not raw:
            return ''
        raw = raw.split('?', 1)[0].split('#', 1)[0].rstrip('/')
        name = raw.rsplit('/', 1)[-1] if '/' in raw else raw
        name = str(name or '').strip()
        if not name or name in {'.', '..'}:
            return ''
        try:
            from urllib.parse import unquote
            name = unquote(name)
        except Exception:
            pass
        return name[:180]

    def _agent_stream_file_record_display_name(self, rec: dict | None = None) -> str:
        if not isinstance(rec, dict):
            return ''
        for key in ('filename', 'saved_filename', 'target_filename', 'display_name', 'name', 'path'):
            name = self._agent_stream_public_file_label(rec.get(key))
            if name:
                return name
        return ''

    def _agent_stream_file_record_names(self, records: list | None = None, limit: int = 8) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        max_items = max(1, min(int(limit or 8), 80))
        for rec in (records or []):
            name = self._agent_stream_file_record_display_name(rec if isinstance(rec, dict) else {})
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(name)
            if len(out) >= max_items:
                break
        return out

    def _agent_stream_file_context_names_from_prompt(self, prompt: str = '', limit: int = 6) -> list[str]:
        out: list[str] = []
        seen = set()
        text = str(prompt or '')
        for match in re.finditer(r'^###\s*???([^\n?]+)', text, flags=re.M):
            name = str(match.group(1) or '').strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name[:180])
            if len(out) >= max(1, int(limit or 6)):
                break
        return out

    def _agent_stream_file_context_needed_for_groups(self, groups: list | None = None) -> bool:
        """Return True only when the model-selected capability groups need files.

        This keeps ordinary turns from showing file-index reasoning just because
        there are historical uploaded/generated files in the conversation.  The
        decision source is the model/tool gate capability selection, not a
        keyword check over the user's text.
        """
        try:
            selected = {str(x or '').strip().lower() for x in (groups or []) if str(x or '').strip()}
        except Exception:
            selected = set()
        if self.single_sandbox_file_plane_enabled():
            return bool({'sandbox', 'code_interpreter'} & selected)
        return bool({'file'} & selected)

    def _agent_stream_file_context_needed_for_current_turn(self, base_messages: list | None = None) -> tuple[bool, str]:
        """Detect structurally attached file context for the Chat direct-first lane."""
        try:
            collector = globals().get('_collect_history_file_records')
            if not callable(collector):
                return False, ''
            msgs = [dict(m) if isinstance(m, dict) else m for m in (base_messages or [])]
            records, _heavy_indexes = collector(msgs)
            if not records:
                return False, ''
            current_selector = globals().get('_select_current_turn_file_records')
            latest_text = _latest_user_text_from_messages(msgs or [])
            if callable(current_selector) and current_selector(records, msgs):
                return True, 'current_turn_file_attachment'
            query_selector = globals().get('_select_history_file_records_for_query')
            if callable(query_selector) and query_selector(records, latest_text):
                return True, 'explicit_file_reference'
        except Exception as err:
            try:
                app_logger.warning('[AGENT_STREAM_FILE_CONTEXT_TURN_CHECK_FAILED] err=%s:%s', type(err).__name__, err)
            except Exception:
                pass
        return False, ''

    def _agent_stream_prompt_cache_file_context_needed(self, base_messages: list | None = None) -> bool:
        """Keep recently supplied text attachments in prompt cache context."""
        try:
            wants_cache = bool((globals().get('_prompt_cache_runtime_wants_cache') or (lambda: False))())
        except Exception:
            wants_cache = False
        if not wants_cache:
            return False
        try:
            collector = globals().get('_collect_history_file_records')
            if not callable(collector):
                return False
            msgs = [dict(m) if isinstance(m, dict) else m for m in (base_messages or [])]
            records, _heavy_indexes = collector(msgs)
            if not records:
                return False
            current_selector = globals().get('_select_current_turn_file_records')
            if callable(current_selector) and current_selector(records, msgs):
                return True
            recent_selector = globals().get('_select_active_recent_file_records')
            if callable(recent_selector) and recent_selector(records, msgs, limit=4):
                return True
            if self._agent_stream_prompt_cache_text_file_records(records, limit=4):
                return True
        except Exception as err:
            try:
                app_logger.warning('[AGENT_STREAM_PROMPT_CACHE_FILE_CONTEXT_CHECK_FAILED] err=%s:%s', type(err).__name__, err)
            except Exception:
                pass
        return False

    def _agent_stream_prompt_cache_text_file_records(self, records: list | None = None, *, limit: int = 4) -> list[dict]:
        """Select real text files that can form a reusable cache prefix."""
        text_exts = {
            '.txt', '.md', '.markdown', '.csv', '.tsv', '.json', '.jsonl', '.yaml', '.yml',
            '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.scss', '.xml', '.log',
        }
        out: list[dict] = []
        seen = set()
        rows = [r for r in (records or []) if isinstance(r, dict)]
        def _score(row: dict) -> tuple[int, int]:
            active = 2 if bool(row.get('_current_turn_attachment')) else (1 if bool(row.get('_active_recent_attachment')) else 0)
            try:
                order = int(row.get('order') or 0)
            except Exception:
                order = 0
            return active, order
        for rec in sorted(rows, key=_score, reverse=True):
            name = str(rec.get('filename') or rec.get('saved_filename') or '').strip()
            ext = str(rec.get('ext') or '').strip().lower()
            if ext and not ext.startswith('.'):
                ext = '.' + ext.lstrip('.')
            if not ext and '.' in name:
                ext = '.' + name.rsplit('.', 1)[-1].lower()
            if ext and ext not in text_exts:
                continue
            has_text_source = bool(
                str(rec.get('full_text_ref') or rec.get('inline_text') or '').strip()
                or str(rec.get('registry_file_id') or rec.get('file_library_id') or rec.get('library_file_id') or rec.get('account_file_id') or rec.get('file_id') or rec.get('id') or '').strip()
            )
            if not has_text_source:
                for key in ('full_text_chars', 'parsed_chars', 'stored_text_chars'):
                    try:
                        if int(rec.get(key) or 0) > 0:
                            has_text_source = True
                            break
                    except Exception:
                        pass
            if not has_text_source:
                continue
            dedupe_key = str(rec.get('registry_file_id') or rec.get('file_library_id') or rec.get('library_file_id') or rec.get('account_file_id') or rec.get('file_id') or rec.get('id') or rec.get('full_text_ref') or name).strip()
            if not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            out.append(dict(rec))
            if len(out) >= max(1, int(limit or 4)):
                break
        return out

    def _agent_stream_model_driven_file_index_prompt(self, file_ctx: dict | None = None, *, recall_prompt: str = '', current_user_text: str = '') -> str:
        """Build a manifest-only file context for the streaming Agent.

        The goal is GPT-like behavior: the model sees a stable file map, then
        imports the selected file into /mnt/data and reads/runs it from the
        sandbox.  Do not read file bytes here and do not inject symbol/source
        snippets from the backend; the sandbox is the only live read/execute
        plane.
        """
        ctx = file_ctx if isinstance(file_ctx, dict) else {}
        records = [dict(r) for r in (ctx.get('records') or []) if isinstance(r, dict)]
        if not records:
            return ''

        # Prefer current-turn / active records, then recent records.  This is a
        # deterministic file index, not an intent decision.
        def rec_score(rec: dict) -> tuple[int, float]:
            try:
                active = 2 if bool(rec.get('_current_turn_attachment')) else (1 if bool(rec.get('_active_recent_attachment')) else 0)
            except Exception:
                active = 0
            try:
                order = float(rec.get('order') or rec.get('updated_at') or 0.0)
            except Exception:
                order = 0.0
            return (active, order)

        records.sort(key=rec_score, reverse=True)
        max_files = max(1, min(int(os.getenv('AGENT_STREAM_FILE_INDEX_MAX_FILES', '8') or 8), 16))
        lines: list[str] = [
            '?????????????????????????????????????????????????????',
            '????????????????????????????????????????? sandbox_import_files ?? /mnt/data?',
            '?????? sandbox_read_file ? sandbox_run ??????????????????????????????',
        ]
        identity_builder = globals().get('_history_file_identity_line')
        for rec in records[:max_files]:
            name = str(rec.get('filename') or rec.get('saved_filename') or '').strip() or '?????'
            ext = str(rec.get('ext') or '').strip()
            size = rec.get('size_bytes') or rec.get('size') or 0
            identity = ''
            try:
                if callable(identity_builder):
                    identity = str(identity_builder(rec) or '').strip()
            except Exception:
                identity = ''
            if not identity:
                identity = name
            info = f'### ???{name}???????'
            details = []
            details.append('?????' + identity)
            if ext:
                details.append('???' + ext)
            try:
                if int(size or 0) > 0:
                    details.append('???%s bytes' % int(size or 0))
            except Exception:
                pass
            registry_id = str(rec.get('registry_file_id') or rec.get('registry_id') or rec.get('file_id') or rec.get('account_file_id') or rec.get('id') or '').strip()
            if registry_id:
                details.append('sandbox_import_files.registry_file_id: ' + registry_id[:64])
            details.append('sandbox_import_files.target_filename: ' + name[:160])
            content_hash = str(rec.get('content_hash') or rec.get('sha256') or rec.get('hash') or '').strip()
            if content_hash:
                details.append('hash?' + content_hash[:16])
            if bool(rec.get('_current_turn_attachment')):
                details.append('???????/??')
            elif bool(rec.get('_active_recent_attachment')):
                details.append('?????????')
            if details:
                info += '\n' + '?'.join(details)
            lines.append(info)
        return '\n\n'.join([x for x in lines if str(x or '').strip()]).strip()

    def _agent_stream_prompt_cache_inline_file_context(self, records: list | None = None) -> str:
        """Inline real text attachments when prompt cache is expected to reuse them.

        The sandbox manifest remains the source for file operations. This block is
        only evidence/context for long text the user already supplied, so later
        turns can reuse it as a stable prompt-cache prefix.
        """
        try:
            wants_cache = bool((globals().get('_prompt_cache_runtime_wants_cache') or (lambda: False))())
        except Exception:
            wants_cache = False
        if not wants_cache:
            return ''
        try:
            total_limit = max(0, min(int(str(app_getenv('APP3_PROMPT_CACHE_INLINE_FILE_MAX_CHARS', '160000') or 160000)), 500000))
        except Exception:
            total_limit = 160000
        if total_limit <= 0:
            return ''
        try:
            per_file_limit = max(2000, min(int(str(app_getenv('APP3_PROMPT_CACHE_INLINE_FILE_PER_FILE_MAX_CHARS', '120000') or 120000)), total_limit))
        except Exception:
            per_file_limit = min(120000, total_limit)
        text_reader = globals().get('_file_registry_record_text_by_id')
        text_store_reader = globals().get('_file_text_store_read_text')
        model_text_formatter = globals().get('_file_registry_model_text')
        context_read_max = globals().get('_file_context_read_max_chars')
        history_text_reader = globals().get('_history_file_read_text')
        registry_loader = globals().get('_file_registry_load')
        if not callable(text_reader) and not callable(text_store_reader) and not callable(history_text_reader):
            return ''
        rows = [dict(r) for r in (records or []) if isinstance(r, dict)]
        if not rows:
            return ''
        chunks: list[str] = []
        used = 0
        seen = set()
        text_exts = {
            '.txt', '.md', '.markdown', '.csv', '.tsv', '.json', '.jsonl', '.yaml', '.yml',
            '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.scss', '.xml', '.log',
        }
        def _candidate_file_ids(rec: dict) -> list[str]:
            vals = [
                (rec.get('file_registry') or {}).get('file_id') if isinstance(rec.get('file_registry'), dict) else '',
                rec.get('registry_file_id'),
                rec.get('registry_id'),
                rec.get('file_library_id'),
                rec.get('library_file_id'),
                rec.get('account_file_id'),
                rec.get('file_id'),
                rec.get('id'),
            ]
            out: list[str] = []
            for val in vals:
                fid = str(val or '').strip()
                if fid and fid not in out:
                    out.append(fid)
            return out

        def _read_inline_file_text(rec: dict, *, max_chars: int) -> str:
            name = str(rec.get('filename') or rec.get('saved_filename') or '').strip()
            for fid in _candidate_file_ids(rec):
                if not callable(text_reader):
                    break
                try:
                    text = str(text_reader(fid) or '').strip()
                except Exception:
                    text = ''
                if text:
                    return text[:max_chars]
            try:
                if callable(registry_loader):
                    registry_loader()
            except Exception:
                pass
            try:
                state = globals().get('_FILE_REGISTRY_STATE')
                files = dict((state or {}).get('files') or {}) if isinstance(state, dict) else {}
            except Exception:
                files = {}
            registry_rec = {}
            for fid in _candidate_file_ids(rec):
                found = files.get(str(fid or '').strip())
                if isinstance(found, dict) and found:
                    registry_rec = dict(found)
                    break
            if not registry_rec:
                wanted_storage = {str(rec.get(k) or '').strip() for k in ('storage_ref', 'model_storage_ref') if str(rec.get(k) or '').strip()}
                wanted_hash = {str(rec.get(k) or '').strip() for k in ('content_hash', 'hash', 'sha256') if str(rec.get(k) or '').strip()}
                for found in files.values():
                    if not isinstance(found, dict):
                        continue
                    if wanted_storage and str(found.get('storage_ref') or found.get('model_storage_ref') or '').strip() in wanted_storage:
                        registry_rec = dict(found)
                        break
                    if wanted_hash and str(found.get('content_hash') or found.get('hash') or found.get('sha256') or '').strip() in wanted_hash:
                        registry_rec = dict(found)
                        break
            if registry_rec:
                full_ref = str(registry_rec.get('full_text_ref') or '').strip()
                if full_ref and callable(text_store_reader):
                    try:
                        text = str(text_store_reader(full_ref, max_chars=max_chars) or '').strip()
                    except Exception:
                        text = ''
                    if text:
                        try:
                            if callable(model_text_formatter):
                                text = str(model_text_formatter(text, name or str(registry_rec.get('filename') or registry_rec.get('saved_filename') or '')) or text).strip()
                        except Exception:
                            pass
                        return text[:max_chars]
            full_ref = str(rec.get('full_text_ref') or '').strip()
            if full_ref and callable(text_store_reader):
                try:
                    read_limit = max_chars
                    if callable(context_read_max):
                        try:
                            read_limit = max(read_limit, int(context_read_max() or 0))
                        except Exception:
                            pass
                    text = str(text_store_reader(full_ref, max_chars=read_limit) or '').strip()
                except Exception:
                    text = ''
                if text:
                    try:
                        if callable(model_text_formatter):
                            text = str(model_text_formatter(text, name) or text).strip()
                    except Exception:
                        pass
                    return text[:max_chars]
            if callable(history_text_reader):
                try:
                    text = str(history_text_reader(rec) or '').strip()
                except Exception:
                    text = ''
                if text:
                    return text[:max_chars]
            return str(rec.get('inline_text') or '').strip()[:max_chars]

        for rec in rows:
            ids = _candidate_file_ids(rec)
            dedupe_key = ids[0] if ids else (str(rec.get('full_text_ref') or rec.get('filename') or '').strip())
            if not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            ext = str(rec.get('ext') or '').strip().lower()
            if ext and not ext.startswith('.'):
                ext = '.' + ext.lstrip('.')
            if ext and ext not in text_exts:
                continue
            try:
                parsed_chars = int(rec.get('full_text_chars') or rec.get('parsed_chars') or rec.get('stored_text_chars') or 0)
            except Exception:
                parsed_chars = 0
            if parsed_chars <= 0 and not str(rec.get('inline_text') or '').strip() and not str(rec.get('full_text_ref') or '').strip() and not ids:
                continue
            remain = total_limit - used
            if remain <= 0:
                break
            limit = max(0, min(per_file_limit, remain))
            clipped = _read_inline_file_text(rec, max_chars=limit)
            if not clipped:
                continue
            name = str(rec.get('filename') or rec.get('saved_filename') or dedupe_key).strip()[:180]
            chunks.append('### ???????%s\n%s' % (name or dedupe_key, clipped))
            used += len(clipped)
            if used >= total_limit:
                break
        if not chunks:
            return ''
        try:
            app_logger.info('[PROMPT_CACHE_INLINE_FILE_CONTEXT] files=%s chars=%s limit=%s per_file_limit=%s', len(chunks), used, total_limit, per_file_limit)
        except Exception:
            pass
        return (
            '?????????????????????????????????????????'
            '????????????????? sandbox_import_files / sandbox_read_file?\n\n'
            + '\n\n'.join(chunks)
        ).strip()

    def _agent_stream_note_file_context_injection(self, state: dict | None = None, file_ctx: dict | None = None, *, memory_prompt: str = '', recall_prompt: str = '', current_user_text: str = '') -> None:
        if not isinstance(state, dict) or not str(recall_prompt or '').strip():
            return
        ctx = file_ctx if isinstance(file_ctx, dict) else {}
        display_records = ctx.get('display_records') if isinstance(ctx.get('display_records'), list) else None
        records = display_records if display_records is not None else (ctx.get('records') if isinstance(ctx.get('records'), list) else [])
        names = self._agent_stream_file_record_names(records, limit=80)
        if not names:
            names = self._agent_stream_file_context_names_from_prompt(recall_prompt, limit=80)
        try:
            file_count = int(ctx.get('available_file_count') or ctx.get('file_count') or len(records or []) or len(names or []) or 0)
        except Exception:
            file_count = len(records or []) or len(names or [])
        if file_count <= 0 and names:
            file_count = len(names)
        state['file_context_injected'] = True
        detail = '????????????????????'
        if file_count > 0:
            detail = f'??? {file_count} ??????????????????'
            if file_count > len(names) and len(names) >= 8:
                detail += '??????????????'
        self.append_file_progress(state, {
            'stage': 'upload_files_ready',
            'panel_stage': 'file',
            'tool': 'sandbox_import_files',
            'key': 'file|upload_files_ready',
            'message': '???????',
            'percent': 40,
            'detail': detail,
            'fileNames': names[:80],
            'files_preview': names[:8],
            'fileNameTotal': file_count,
            'file_count': file_count,
            'state': 'done',
            'queries': [],
            'ts': int(time.time() * 1000),
        })




    def _agent_stream_messages_with_file_context(self, base_messages: list | None = None, state: dict | None = None) -> list:
        """Inject uploaded/generated file context for the direct streaming-tool lane.

        The direct-first agent intentionally skips the old prepare phase, but the
        frontend now sends uploaded files as structured file_attachments instead of
        inline system previews.  Without this lightweight bridge the model only sees
        the filename after sanitization.  Reuse the existing file-registry context
        builder so reading/reviewing an uploaded file works while generation/editing
        can use the native file-delivery tools without a second legacy prepare pass.
        """
        msgs = [dict(m) if isinstance(m, dict) else m for m in (base_messages or [])]
        try:
            current_user_text = _latest_user_text_from_messages(msgs or [])
            collector = globals().get('_collect_history_file_records')
            if not callable(collector):
                return msgs
            records, heavy_indexes = collector(msgs)
            pruned = [m for idx, m in enumerate(msgs) if idx not in (heavy_indexes or set())]
            current_selector = globals().get('_select_current_turn_file_records')
            query_selector = globals().get('_select_history_file_records_for_query')
            recent_selector = globals().get('_select_active_recent_file_records')
            lineage_selector = globals().get('_select_lineage_source_file_records')
            merge_records = globals().get('_merge_history_file_records')
            current_turn_records = current_selector(records, msgs) if callable(current_selector) else []
            query_selected = query_selector(records, current_user_text) if callable(query_selector) else []
            active_recent_records = [] if current_turn_records else (recent_selector(records, msgs, limit=8) if callable(recent_selector) else [])
            lineage_source_records = lineage_selector(records, [*current_turn_records, *query_selected, *active_recent_records], limit=8) if callable(lineage_selector) else []
            if callable(merge_records):
                selected_records = merge_records(current_turn_records, query_selected, lineage_source_records, active_recent_records, limit=12)
            else:
                selected_records = [dict(x) for x in [*current_turn_records, *query_selected, *lineage_source_records, *active_recent_records] if isinstance(x, dict)]
            if not selected_records:
                try:
                    wants_cache = bool((globals().get('_prompt_cache_runtime_wants_cache') or (lambda: False))())
                except Exception:
                    wants_cache = False
                if wants_cache:
                    selected_records = self._agent_stream_prompt_cache_text_file_records(records, limit=4)
            display_records = current_turn_records if current_turn_records else selected_records
            file_ctx = {
                'messages': pruned,
                'records': selected_records,
                'display_records': display_records,
                'available_file_count': len(display_records or []),
                'selected_file_count': len(selected_records or []),
                'dropped_inline_count': len(heavy_indexes or set()),
                'memory_prompt': '',
                'recall_prompt': 'manifest_only',
            }
            model_file_prompt = self._agent_stream_model_driven_file_index_prompt(file_ctx, recall_prompt='manifest_only', current_user_text=current_user_text)
            inline_file_prompt = self._agent_stream_prompt_cache_inline_file_context(selected_records)
            injected = []
            if inline_file_prompt:
                injected.append({'role': 'system', '_kind': 'file_recall', 'content': inline_file_prompt})
            if model_file_prompt:
                injected.append({'role': 'system', '_kind': 'agent_stream_runtime', 'content': model_file_prompt})
            if injected:
                try:
                    self._agent_stream_note_file_context_injection(state, file_ctx, memory_prompt='', recall_prompt=model_file_prompt or inline_file_prompt, current_user_text=current_user_text)
                except Exception:
                    pass
                try:
                    combined_prompt = (inline_file_prompt + '\n\n' + model_file_prompt).strip() if inline_file_prompt and model_file_prompt else (inline_file_prompt or model_file_prompt or '')
                    app_logger.info(
                        '[AGENT_STREAM_SANDBOX_MANIFEST_INJECTED] messages=%s records=%s dropped_inline=%s manifest_chars=%s inline_file_chars=%s',
                        len(msgs or []),
                        len(selected_records or []),
                        len(heavy_indexes or set()),
                        len(combined_prompt),
                        len(inline_file_prompt or ''),
                    )
                except Exception:
                    pass
                return injected + pruned
            return pruned
        except Exception as file_ctx_err:
            try:
                app_logger.warning('[AGENT_STREAM_FILE_CONTEXT_FAILED] err=%s:%s', type(file_ctx_err).__name__, file_ctx_err)
            except Exception:
                pass
            return msgs
