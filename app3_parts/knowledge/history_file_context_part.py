# Split from app3_parts/knowledge/knowledge_base_context_part.py.
# Purpose: chat history file context, file lineage prompts, snippet selection, and _prepare_messages.
# Loaded after KB core and file-library helpers.

_HISTORY_FILE_TEXT_CACHE_LOCK = threading.Lock()
_HISTORY_FILE_TEXT_CACHE: dict[str, dict] = {}
_HISTORY_FILE_MEMORY_MAX_ITEMS = 8
_HISTORY_FILE_RECALL_MAX_FILES = 4
_HISTORY_FILE_RECALL_MAX_CHUNKS_PER_FILE = 5
_HISTORY_FILE_RECALL_MAX_TOTAL_CHARS = 12000
# 文件阅读上下文不再只按“显式点名文件名”触发：最近上传/生成的文件会作为
# 当前活跃文件继续进入后续几轮上下文，由模型自己判断是否使用。
_HISTORY_FILE_ACTIVE_WINDOW_MESSAGES = 18
_HISTORY_FILE_ACTIVE_RECALL_MAX_CHARS = 52000
_HISTORY_FILE_ACTIVE_RECALL_CHUNKS_PER_FILE = 20
_HISTORY_FILE_ACTIVE_SNIPPET_CHARS = 2600


def _extract_saved_filename_from_url(url: str) -> str:
    raw = str(url or '').strip()
    if not raw:
        return ''
    try:
        parsed = urlparse(raw)
        path = str(parsed.path or raw).strip()
    except Exception:
        path = raw
    path = path.split('?', 1)[0].split('#', 1)[0].strip()
    if '/api3/generated-download/' in path:
        return urllib.parse.unquote(path.rsplit('/api3/generated-download/', 1)[1].strip('/'))
    if '/api3/generated-files/' in path:
        return urllib.parse.unquote(path.rsplit('/api3/generated-files/', 1)[1].strip('/'))
    if '/api3/download/' in path:
        return urllib.parse.unquote(path.rsplit('/api3/download/', 1)[1].strip('/'))
    if '/api3/uploads/' in path:
        return urllib.parse.unquote(path.rsplit('/api3/uploads/', 1)[1].strip('/'))
    return urllib.parse.unquote(os.path.basename(path))


def _history_file_ext(filename: str) -> str:
    return os.path.splitext(str(filename or '').strip())[1].lower()


def _history_file_stems(filename: str) -> list[str]:
    raw = str(filename or '').strip()
    if not raw:
        return []
    stem = os.path.splitext(os.path.basename(raw))[0].strip()
    parts = [stem]
    parts.extend(re.split(r'[\s._\-]+', stem))
    out: list[str] = []
    seen = set()
    for part in parts:
        item = str(part or '').strip().lower()
        if len(item) < 2 or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _parse_uploaded_file_system_note(content: str) -> dict | None:
    text = str(content or '').strip()
    if not text:
        return None
    m = re.match(r'^以下是用户上传文件《(.+?)》的(?:可引用片段|内容)[^\n：:]*[：:]?\s*(.*)$', text, flags=re.S)
    if m:
        return {
            'filename': str(m.group(1) or '').strip(),
            'inline_text': str(m.group(2) or '').strip(),
            'note': '',
            'is_heavy': True,
        }
    m = re.match(r'^用户上传了一个文件《(.+?)》（无法直接解析为文本）。(.*)$', text, flags=re.S)
    if m:
        return {
            'filename': str(m.group(1) or '').strip(),
            'inline_text': '',
            'note': str(m.group(2) or '').strip(),
            'is_heavy': False,
        }
    return None


def _parse_uploaded_file_user_placeholder(content: str) -> dict | None:
    text = str(content or '').strip()
    if not text:
        return None
    m = re.match(r'^\[文件附件\]\s*(.+?)\s*$', text, flags=re.S)
    if not m:
        return None
    filename = str(m.group(1) or '').strip()
    if not filename:
        return None
    return {
        'filename': filename,
        'ext': _history_file_ext(filename),
    }


def _collect_history_file_records(messages: list | None = None) -> tuple[list[dict], set[int]]:
    records: list[dict] = []
    upload_by_id: dict[str, dict] = {}
    heavy_system_indexes: set[int] = set()

    def _file_payload_registry(payload: dict | None = None) -> dict:
        row = dict(payload or {})
        reg = row.get('file_registry') if isinstance(row.get('file_registry'), dict) else {}
        return dict(reg or {})

    def _registry_record_for_file_payloads(*payloads: dict | None) -> dict:
        ids: list[str] = []
        hashes: list[str] = []
        storage_refs: list[str] = []
        urls: list[str] = []
        filenames: list[str] = []
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            reg = _file_payload_registry(payload)
            for key in ('registry_file_id', 'file_library_id', 'library_file_id', 'account_file_id', 'file_id', 'id'):
                val = str(payload.get(key) or '').strip()
                if val:
                    ids.append(val)
            val = str(reg.get('file_id') or '').strip()
            if val:
                ids.insert(0, val)
            content_hash = str(payload.get('content_hash') or reg.get('content_hash') or payload.get('hash') or reg.get('hash') or '').strip()
            if content_hash:
                hashes.append(content_hash)
            for src in (payload, reg):
                for key in ('storage_ref', 'model_storage_ref'):
                    val = str(src.get(key) or '').strip()
                    if val:
                        storage_refs.append(val)
                for key in ('url', 'download_url', 'view_url'):
                    val = str(src.get(key) or '').strip()
                    if val:
                        urls.append(val)
                        try:
                            base = os.path.basename(urllib.parse.urlparse(val).path)
                        except Exception:
                            base = os.path.basename(val)
                        if base:
                            filenames.append(base)
                for key in ('filename', 'saved_filename', 'original_filename'):
                    val = str(src.get(key) or '').strip()
                    if val:
                        filenames.append(val)
        ids = [x for i, x in enumerate(ids) if x and x not in ids[:i]]
        storage_refs = [x for i, x in enumerate(storage_refs) if x and x not in storage_refs[:i]]
        urls = [x for i, x in enumerate(urls) if x and x not in urls[:i]]
        filenames = [os.path.basename(x).strip().lower() for i, x in enumerate(filenames) if x and x not in filenames[:i]]
        try:
            loader = globals().get('_file_registry_load')
            if callable(loader):
                loader()
        except Exception:
            pass
        try:
            state = globals().get('_FILE_REGISTRY_STATE')
            files = dict((state or {}).get('files') or {}) if isinstance(state, dict) else {}
        except Exception:
            files = {}
        for fid in ids:
            found = files.get(fid)
            if isinstance(found, dict) and found:
                return dict(found)
        if hashes:
            wanted = {h for h in hashes if h}
            for found in files.values():
                if not isinstance(found, dict):
                    continue
                if str(found.get('content_hash') or found.get('hash') or '').strip() in wanted:
                    return dict(found)
        if storage_refs:
            wanted_storage = {x for x in storage_refs if x}
            for found in files.values():
                if not isinstance(found, dict):
                    continue
                if str(found.get('storage_ref') or found.get('model_storage_ref') or '').strip() in wanted_storage:
                    return dict(found)
        if urls:
            wanted_urls = {x for x in urls if x}
            for found in files.values():
                if not isinstance(found, dict):
                    continue
                for key in ('url', 'download_url', 'view_url'):
                    if str(found.get(key) or '').strip() in wanted_urls:
                        return dict(found)
        if filenames:
            wanted_names = {x for x in filenames if x}
            for found in files.values():
                if not isinstance(found, dict):
                    continue
                found_names = {
                    os.path.basename(str(found.get('filename') or '')).strip().lower(),
                    os.path.basename(str(found.get('saved_filename') or '')).strip().lower(),
                }
                if wanted_names & {x for x in found_names if x}:
                    return dict(found)
        return {}

    def _enrich_history_file_record(rec: dict, *payloads: dict | None) -> dict:
        out = dict(rec or {})
        registry_rec = _registry_record_for_file_payloads(out, *payloads)
        sources: list[dict] = []
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            sources.append(dict(payload))
            reg = _file_payload_registry(payload)
            if reg:
                sources.append(reg)
        if registry_rec:
            sources.append(registry_rec)

        def fill_text(key: str, *aliases: str) -> None:
            if str(out.get(key) or '').strip():
                return
            for src in sources:
                for src_key in (key, *aliases):
                    val = str(src.get(src_key) or '').strip()
                    if val:
                        out[key] = val
                        return

        def fill_int_max(key: str, *aliases: str) -> None:
            try:
                cur = int(out.get(key) or 0)
            except Exception:
                cur = 0
            best = cur
            for src in sources:
                for src_key in (key, *aliases):
                    try:
                        val = int(src.get(src_key) or 0)
                    except Exception:
                        val = 0
                    if val > best:
                        best = val
            if best > cur:
                out[key] = best

        fill_text('registry_file_id', 'file_id')
        if registry_rec and str(registry_rec.get('file_id') or '').strip():
            out['registry_file_id'] = str(registry_rec.get('file_id') or '').strip()
        fill_text('file_library_id', 'library_file_id', 'registry_file_id')
        fill_text('library_file_id', 'file_library_id', 'registry_file_id')
        fill_text('full_text_ref')
        fill_text('content_hash', 'hash')
        fill_text('storage_ref', 'model_storage_ref')
        fill_text('model_storage_ref', 'storage_ref')
        fill_text('preview')
        for key in ('namespace', 'scope', 'saved_filename', 'summary', 'code_summary', 'url', 'view_url', 'download_url'):
            fill_text(key)
        fill_int_max('full_text_chars', 'parsed_chars')
        fill_int_max('full_text_lines', 'parsed_lines')
        fill_int_max('parsed_chars', 'full_text_chars')
        fill_int_max('parsed_lines', 'full_text_lines')
        fill_int_max('stored_text_chars')
        fill_int_max('size_bytes', 'size')
        fill_int_max('size', 'size_bytes')
        for key in ('full_text_available', 'stored_text_truncated', 'registry_text_truncated', 'text_is_preview'):
            if any(bool(src.get(key)) for src in sources):
                out[key] = True
        symbols = out.get('symbols') if isinstance(out.get('symbols'), list) else []
        for src in sources:
            src_symbols = src.get('symbols') if isinstance(src.get('symbols'), list) else []
            if len(src_symbols) > len(symbols):
                symbols = src_symbols
        if symbols:
            out['symbols'] = symbols
        return out

    def _turn_flag_from_payload(obj: dict | None = None) -> bool:
        row = dict(obj or {})
        scope = str(row.get('turn_scope') or row.get('request_scope') or row.get('scope') or '').strip().lower()
        return bool(
            row.get('_current_turn_attachment')
            or row.get('current_turn')
            or row.get('currentTurn')
            or row.get('selected_for_current_turn')
            or row.get('selectedForCurrentTurn')
            or scope in {'current', 'current_turn', 'composer', 'current-user-message', 'current_user_message'}
        )

    def _mark_turn_flag(rec: dict, *payloads: dict | None) -> dict:
        if any(_turn_flag_from_payload(p) for p in payloads if isinstance(p, dict)):
            rec['_current_turn_attachment'] = True
        return rec

    for idx, m in enumerate(messages or []):
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '').strip()
        content = m.get('content')
        if role == 'user' and isinstance(content, dict) and content.get('_kind') == 'file':
            registry = dict(content.get('file_registry') or {}) if isinstance(content.get('file_registry'), dict) else {}
            top_symbols = content.get('symbols') if isinstance(content.get('symbols'), list) else []
            reg_symbols = registry.get('symbols') if isinstance(registry.get('symbols'), list) else []
            symbols = reg_symbols if len(reg_symbols) >= len(top_symbols) else top_symbols
            filename = str(content.get('filename') or registry.get('filename') or registry.get('original_filename') or registry.get('saved_filename') or '').strip()
            ext = str(content.get('ext') or registry.get('ext') or _history_file_ext(filename) or '').strip().lower()
            if ext and not ext.startswith('.'):
                ext = '.' + ext.lstrip('.').lower()
            registry_file_id = str(registry.get('file_id') or content.get('registry_file_id') or content.get('file_id') or '').strip()
            file_id = str(content.get('id') or content.get('file_id') or registry_file_id or '').strip()
            rec = {
                'source': str(content.get('source_type') or content.get('source') or registry.get('source') or 'upload').strip() or 'upload',
                'source_role': str(content.get('source_role') or (('edited_output' if (isinstance(content.get('edit_audit'), dict) or isinstance(content.get('edit_details'), dict) or isinstance(content.get('edited_from'), dict)) else 'assistant_generated') if str(content.get('source_type') or content.get('source') or registry.get('source') or registry.get('namespace') or '').strip().lower() == 'generated' else 'user_upload')).strip() or 'user_upload',
                'file_id': file_id,
                'registry_file_id': registry_file_id,
                'filename': filename,
                'ext': ext,
                'url': str(content.get('download_url') or content.get('url') or registry.get('download_url') or registry.get('url') or '').strip(),
                'view_url': str(content.get('view_url') or registry.get('view_url') or '').strip(),
                'download_url': str(content.get('download_url') or content.get('url') or registry.get('download_url') or registry.get('url') or '').strip(),
                'namespace': str(registry.get('namespace') or ('generated' if str(content.get('source_type') or content.get('source') or '').strip() == 'generated' else 'uploads')).strip(),
                'scope': str(registry.get('scope') or content.get('scope') or '').strip(),
                'saved_filename': str(registry.get('saved_filename') or content.get('saved_filename') or filename).strip(),
                'summary': str(content.get('code_summary') or registry.get('summary') or registry.get('code_summary') or '').strip(),
                'symbols': symbols or [],
                'note': str(content.get('note') or '').strip(),
                'inline_text': '',
                'order': idx,
                'edit_audit': dict(content.get('edit_audit') or {}) if isinstance(content.get('edit_audit'), dict) else {},
                'edit_details': dict(content.get('edit_details') or {}) if isinstance(content.get('edit_details'), dict) else {},
                'edited_from': dict(content.get('edited_from') or {}) if isinstance(content.get('edited_from'), dict) else {},
            }
            rec = _enrich_history_file_record(_mark_turn_flag(rec, content, registry), content, registry)
            upload_by_id[rec['file_id']] = rec
            records.append(rec)
        elif role == 'user' and isinstance(content, str):
            parsed_user_file = _parse_uploaded_file_user_placeholder(content)
            if parsed_user_file:
                records.append({
                    'source': 'upload',
                    'source_role': 'user_upload',
                    'file_id': '',
                    'filename': str(parsed_user_file.get('filename') or '').strip(),
                    'ext': str(parsed_user_file.get('ext') or '').strip().lower(),
                    'url': '',
                    'view_url': '',
                    'note': '',
                    'inline_text': '',
                    'order': idx,
                })
        elif role == 'assistant' and isinstance(content, dict) and content.get('_kind') == 'genfiles':
            for pos, item in enumerate(content.get('files') or []):
                if not isinstance(item, dict):
                    continue
                item_reg = (item.get('file_registry') or {}) if isinstance(item.get('file_registry'), dict) else {}
                rec = {
                    'source': 'generated',
                    'source_role': str(item.get('source_role') or ('edited_output' if (isinstance(item.get('edit_audit'), dict) or isinstance(item.get('edit_details'), dict) or isinstance(item.get('edited_from'), dict)) else 'assistant_generated')).strip() or 'assistant_generated',
                    'file_id': f'gen::{idx}:{pos}',
                    'registry_file_id': str(item_reg.get('file_id') or '').strip(),
                    'filename': str(item.get('filename') or '').strip(),
                    'ext': _history_file_ext(str(item.get('filename') or '')),
                    'url': str(item.get('download_url') or item.get('url') or '').strip(),
                    'view_url': str(item.get('view_url') or '').strip(),
                    'download_url': str(item.get('download_url') or item.get('url') or '').strip(),
                    'namespace': str(item_reg.get('namespace') or 'generated').strip(),
                    'scope': str(item_reg.get('scope') or item.get('scope') or '').strip(),
                    'saved_filename': str(item_reg.get('saved_filename') or item.get('filename') or '').strip(),
                    'summary': str(item.get('code_summary') or item_reg.get('summary') or '').strip(),
                    'symbols': item_reg.get('symbols') or [],
                    'note': '',
                    'inline_text': '',
                    'order': idx + pos / 1000.0,
                    'edit_audit': dict(item.get('edit_audit') or {}) if isinstance(item.get('edit_audit'), dict) else {},
                    'edited_from': dict(item.get('edited_from') or {}) if isinstance(item.get('edited_from'), dict) else {},
                    'edit_details': dict(item.get('edit_details') or {}) if isinstance(item.get('edit_details'), dict) else {},
                }
                records.append(_enrich_history_file_record(_mark_turn_flag(rec, item, item_reg, content), item, item_reg, content))

    # Top-level message file metadata is how the frontend persists current and
    # historical attachments.  Treat those as structural records too, instead
    # of relying on the broad request-level file_attachments payload.
    for idx, m in enumerate(messages or []):
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '').strip()
        top_files: list[dict] = []
        if role == 'user':
            for key in ('file_attachments', 'attachments', '_composer_file_attachments'):
                rows = m.get(key) if isinstance(m.get(key), list) else []
                for row in rows:
                    if isinstance(row, dict):
                        top_files.append(dict(row))
            for pos, item in enumerate(top_files):
                reg = item.get('file_registry') if isinstance(item.get('file_registry'), dict) else {}
                filename = str(item.get('filename') or reg.get('filename') or reg.get('original_filename') or reg.get('saved_filename') or '').strip()
                if not filename:
                    continue
                registry_file_id = str(item.get('registry_file_id') or item.get('file_library_id') or item.get('library_file_id') or reg.get('file_id') or item.get('file_id') or item.get('id') or '').strip()
                rec = {
                    'source': str(item.get('source_type') or item.get('source') or reg.get('source') or 'upload').strip() or 'upload',
                    'source_role': str(item.get('source_role') or 'user_upload').strip() or 'user_upload',
                    'file_id': str(item.get('id') or item.get('file_id') or registry_file_id or '').strip(),
                    'registry_file_id': registry_file_id,
                    'filename': filename,
                    'ext': str(item.get('ext') or reg.get('ext') or _history_file_ext(filename) or '').strip().lower(),
                    'url': str(item.get('download_url') or item.get('url') or reg.get('download_url') or reg.get('url') or '').strip(),
                    'view_url': str(item.get('view_url') or reg.get('view_url') or '').strip(),
                    'download_url': str(item.get('download_url') or item.get('url') or reg.get('download_url') or reg.get('url') or '').strip(),
                    'namespace': str(reg.get('namespace') or item.get('namespace') or ('uploads' if str(item.get('source_type') or '').strip() != 'generated' else 'generated')).strip(),
                    'scope': str(reg.get('scope') or item.get('scope') or '').strip(),
                    'saved_filename': str(reg.get('saved_filename') or item.get('saved_filename') or filename).strip(),
                    'summary': str(item.get('code_summary') or reg.get('summary') or '').strip(),
                    'symbols': item.get('symbols') if isinstance(item.get('symbols'), list) else (reg.get('symbols') if isinstance(reg.get('symbols'), list) else []),
                    'note': str(item.get('note') or '').strip(),
                    'inline_text': '',
                    'order': max(0.0, idx - 0.001 + (pos / 10000.0)),
                }
                rec = _enrich_history_file_record(_mark_turn_flag(rec, item, reg), item, reg)
                if rec.get('file_id'):
                    upload_by_id[str(rec.get('file_id'))] = rec
                records.append(rec)
        if role == 'assistant':
            generated_rows = []
            for key in ('generatedFiles', 'generated_files'):
                rows = m.get(key) if isinstance(m.get(key), list) else []
                generated_rows.extend([dict(x) for x in rows if isinstance(x, dict)])
            for pos, item in enumerate(generated_rows):
                reg = item.get('file_registry') if isinstance(item.get('file_registry'), dict) else {}
                filename = str(item.get('filename') or reg.get('filename') or reg.get('saved_filename') or '').strip()
                if not filename:
                    continue
                source_role = str(item.get('source_role') or ('edited_output' if (isinstance(item.get('edit_audit'), dict) or isinstance(item.get('edit_details'), dict) or isinstance(item.get('edited_from'), dict)) else 'assistant_generated')).strip() or 'assistant_generated'
                rec = {
                    'source': 'generated',
                    'source_role': source_role,
                    'file_id': str(item.get('id') or item.get('file_id') or reg.get('file_id') or f'genmeta::{idx}:{pos}').strip(),
                    'registry_file_id': str(item.get('registry_file_id') or reg.get('file_id') or item.get('file_id') or '').strip(),
                    'filename': filename,
                    'ext': str(item.get('ext') or reg.get('ext') or _history_file_ext(filename) or '').strip().lower(),
                    'url': str(item.get('download_url') or item.get('url') or reg.get('download_url') or reg.get('url') or '').strip(),
                    'view_url': str(item.get('view_url') or reg.get('view_url') or '').strip(),
                    'download_url': str(item.get('download_url') or item.get('url') or reg.get('download_url') or reg.get('url') or '').strip(),
                    'namespace': str(reg.get('namespace') or 'generated').strip(),
                    'scope': str(reg.get('scope') or item.get('scope') or '').strip(),
                    'saved_filename': str(reg.get('saved_filename') or item.get('saved_filename') or filename).strip(),
                    'summary': str(item.get('code_summary') or reg.get('summary') or '').strip(),
                    'symbols': item.get('symbols') if isinstance(item.get('symbols'), list) else (reg.get('symbols') if isinstance(reg.get('symbols'), list) else []),
                    'note': '',
                    'inline_text': '',
                    'order': idx + pos / 1000.0,
                    'edit_audit': dict(item.get('edit_audit') or {}) if isinstance(item.get('edit_audit'), dict) else {},
                    'edited_from': dict(item.get('edited_from') or {}) if isinstance(item.get('edited_from'), dict) else {},
                    'edit_details': dict(item.get('edit_details') or {}) if isinstance(item.get('edit_details'), dict) else {},
                }
                records.append(_enrich_history_file_record(_mark_turn_flag(rec, item, reg), item, reg))

    for idx, m in enumerate(messages or []):
        if not isinstance(m, dict) or str(m.get('role') or '').strip() != 'system':
            continue
        parsed = _parse_uploaded_file_system_note(_msg_content_text(m.get('content')))
        if not parsed:
            continue
        link_id = str(m.get('_link') or '').strip()
        rec = upload_by_id.get(link_id)
        if rec is None:
            filename = str(parsed.get('filename') or '').strip()
            for cand in reversed(records):
                if str(cand.get('source') or '') != 'upload':
                    continue
                if str(cand.get('filename') or '').strip() == filename:
                    rec = cand
                    break
        if rec is None:
            rec = {
                'source': 'upload',
                'source_role': 'user_upload',
                'file_id': link_id or f'sys::{idx}',
                'filename': str(parsed.get('filename') or '').strip(),
                'ext': _history_file_ext(str(parsed.get('filename') or '').strip()),
                'url': '',
                'view_url': '',
                'note': '',
                'inline_text': '',
                'order': max(0.0, idx - 0.01),
            }
            if rec['file_id']:
                upload_by_id[rec['file_id']] = rec
            records.append(rec)
        if parsed.get('inline_text'):
            rec['inline_text'] = str(parsed.get('inline_text') or '').strip()
        if parsed.get('note'):
            rec['note'] = str(parsed.get('note') or '').strip()
        if parsed.get('is_heavy'):
            heavy_system_indexes.add(idx)

    return records, heavy_system_indexes


def _history_file_query_terms(text: str) -> list[str]:
    s = str(text or '').strip().lower()
    if not s:
        return []
    out: list[str] = []
    seen = set()
    for m in re.finditer(r'[a-z0-9_./\-]{2,}', s):
        term = str(m.group(0) or '').strip('.-_ /\\')
        if len(term) >= 2 and term not in seen:
            seen.add(term)
            out.append(term)
    for m in re.finditer(r'[\u4e00-\u9fff]{2,12}', s):
        term = str(m.group(0) or '').strip()
        if len(term) >= 2 and term not in seen:
            seen.add(term)
            out.append(term)
    for m in re.finditer(r'第\s*([0-9一二三四五六七八九十百千万]+)\s*[条章节点页]', s):
        whole = str(m.group(0) or '').strip()
        if whole and whole not in seen:
            seen.add(whole)
            out.append(whole)
    return out[:18]


def _history_file_query_needs_overview(text: str) -> bool:
    """Deprecated semantic keyword gate.

    文件是否需要进入上下文不再靠“总结/这个/里面”等关键词判断；
    当前轮附件按结构进入候选，历史附件只在用户明确点名文件时进入候选。
    片段排序仍由后续相关性打分负责。
    """
    return False


def _history_file_query_looks_referential(text: str, records: list[dict] | None = None) -> bool:
    """Return True only for explicit file identity matches.

    避免用“这个/那个/总结/里面”之类语义关键词硬判。
    刚上传的附件由 _select_current_turn_file_records 按消息结构处理，
    这里仅处理历史文件被明确点名的情况。
    """
    s = str(text or '').strip().lower()
    if not s:
        return False
    return any(stem and stem in s for rec in (records or []) for stem in _history_file_stems(rec.get('filename') or ''))


def _history_file_record_score(rec: dict, user_text: str, referential: bool = False, max_order: float = 0.0) -> float:
    score = 0.0
    lowered = str(user_text or '').strip().lower()
    filename = str(rec.get('filename') or '').strip()
    filename_lower = filename.lower()
    if filename and filename_lower and filename_lower in lowered:
        score += 12.0
    stem_hits = 0
    for stem in _history_file_stems(filename):
        if stem and stem in lowered:
            stem_hits += 1
            score += 4.0
    if stem_hits:
        score += min(3.0, stem_hits)
    order = float(rec.get('order') or 0.0)
    if max_order > 0:
        gap = max(0.0, float(max_order) - order)
        score += max(0.0, 2.4 - min(2.4, gap * 0.8))
    else:
        score += max(0.0, order / 10000.0)
    if referential:
        score += 1.5
    if str(rec.get('source') or '') == 'upload':
        score += 0.4
    if rec.get('inline_text'):
        score += 0.3
    return score


def _select_history_file_records_for_query(records: list[dict] | None = None, user_text: str = '') -> list[dict]:
    items = [dict(rec) for rec in (records or []) if isinstance(rec, dict) and str(rec.get('filename') or '').strip()]
    if not items:
        return []
    referential = _history_file_query_looks_referential(user_text, items)
    if not referential:
        return []
    max_order = 0.0
    try:
        max_order = max(float((rec or {}).get('order') or 0.0) for rec in items)
    except Exception:
        max_order = 0.0
    ranked: list[tuple[float, dict]] = []
    for rec in items:
        score = _history_file_record_score(rec, user_text, referential=referential, max_order=max_order)
        if score <= 0:
            continue
        ranked.append((score, rec))
    ranked.sort(key=lambda item: (item[0], float((item[1] or {}).get('order') or 0.0)), reverse=True)
    chosen: list[dict] = []
    seen = set()
    for score, rec in ranked:
        key = f"{str(rec.get('filename') or '').strip().lower()}|{str(rec.get('url') or rec.get('view_url') or '').strip()}"
        if key in seen:
            continue
        seen.add(key)
        rec['_score'] = round(float(score), 3)
        chosen.append(rec)
        if len(chosen) >= _HISTORY_FILE_RECALL_MAX_FILES:
            break
    return chosen



def _history_file_record_key(rec: dict | None = None) -> str:
    item = dict(rec or {})
    registry_id = str(item.get('registry_file_id') or '').strip()
    if registry_id:
        return f'registry:{registry_id}'
    file_id = str(item.get('file_id') or '').strip()
    if file_id:
        return f'id:{file_id}'
    name = str(item.get('filename') or '').strip().lower()
    url = str(item.get('url') or item.get('download_url') or item.get('view_url') or '').strip()
    source = str(item.get('source') or '').strip().lower()
    return f'{source}|{name}|{url}'





def _history_file_identity_role(rec: dict | None = None) -> str:
    row = dict(rec or {})
    role = str(row.get('source_role') or row.get('version_role') or '').strip().lower()
    if role in {'user_upload', 'upload', 'uploaded', 'user'}:
        return 'user_upload'
    if role in {'edited_output', 'assistant_edited', 'edited'}:
        return 'edited_output'
    if role in {'assistant_generated', 'latest_generated', 'generated', 'assistant_file', 'assistant'}:
        return 'assistant_generated'
    source = str(row.get('source') or row.get('namespace') or '').strip().lower()
    if source == 'upload' or str(row.get('namespace') or '').strip().lower() == 'uploads':
        return 'user_upload'
    if source == 'generated' or str(row.get('namespace') or '').strip().lower() == 'generated':
        if isinstance(row.get('edit_audit'), dict) or isinstance(row.get('edit_details'), dict) or isinstance(row.get('edited_from'), dict):
            return 'edited_output'
        return 'assistant_generated'
    return source or 'file'


def _history_file_is_assistant_file_role(role: str = '') -> bool:
    return str(role or '').strip().lower() in {'assistant_generated', 'edited_output'}


def _history_file_identity_label(rec: dict | None = None) -> str:
    role = _history_file_identity_role(rec)
    if role == 'user_upload':
        return '用户原始上传'
    if role == 'edited_output':
        return '助手修改版本'
    if _history_file_is_assistant_file_role(role):
        return '助手生成文件'
    return '文件'


def _history_file_identity_line(rec: dict | None = None) -> str:
    row = dict(rec or {})
    name = str(row.get('filename') or row.get('saved_filename') or '').strip() or '未命名文件'
    parts = [f'《{name}》：{_history_file_identity_label(row)}']
    lineage = _history_file_lineage_names(row) if _history_file_is_assistant_file_role(_history_file_identity_role(row)) else []
    if lineage:
        parts.append('来源/基准：' + '、'.join([f'《{x}》' for x in lineage[:3] if str(x or '').strip()]))
    if bool(row.get('_current_turn_attachment')):
        parts.append('当前轮附件')
    elif bool(row.get('_active_recent_attachment')):
        parts.append('最近活跃')
    elif bool(row.get('_lineage_source_attachment')):
        parts.append('血缘关联源文件')
    return '；'.join([x for x in parts if x]).strip()


def _history_file_basename(value: str = '') -> str:
    try:
        return os.path.basename(str(value or '').strip().replace('\\', '/')).strip()
    except Exception:
        return str(value or '').strip()


def _history_file_lineage_record_names(rec: dict | None = None) -> list[str]:
    """Compatibility adapter backed by FileLineageRegistry."""
    return _history_file_lineage_names(rec or {})[:12]

def _history_file_lineage_group_key(rec: dict | None = None) -> str:
    """Compatibility adapter backed by FileLineageRegistry."""
    helper = globals().get('file_lineage_make_record')
    if callable(helper):
        try:
            row = helper(rec or {}, source_hint='history', idx=0) or {}
            return str(row.get('lineage_key') or row.get('family') or row.get('record_key') or '').strip()
        except Exception:
            return ''
    return ''

def _history_file_lineage_groups(records: list[dict] | None = None, *, max_groups: int = 8, max_versions: int = 4) -> list[dict]:
    """Compatibility adapter backed by FileLineageRegistry.

    The old filename-merging implementation was intentionally removed from
    this entry point to avoid two competing lineage systems.
    """
    helper = globals().get('file_lineage_legacy_groups')
    if callable(helper):
        try:
            return helper(records or [], max_groups=max_groups, max_versions=max_versions)
        except Exception:
            return []
    return []

def _history_file_lineage_prompt(records: list[dict] | None = None, *, max_groups: int = 8) -> str:
    groups = _history_file_lineage_groups(records or [], max_groups=max_groups)
    if not groups:
        return ''
    labels = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    lines = ['文件血缘链（结构事实）：']
    for idx, group in enumerate(groups, 1):
        label = labels[idx - 1] if idx <= len(labels) else str(idx)
        originals = [x for x in (group.get('originals') or []) if str(x or '').strip()]
        versions = [x for x in (group.get('versions') or []) if str(x or '').strip()]
        latest = str(group.get('latest') or '').strip()
        key = str(group.get('key') or '').strip()
        parts = [f'{label}:']
        if key:
            parts.append('key=' + key)
        if originals:
            parts.append('原始 ' + '、'.join(f'《{x}》' for x in originals[:3]))
        if latest:
            parts.append('最新 ' + f'《{latest}》')
        if versions:
            parts.append('生成版本 ' + '、'.join(f'《{x}》' for x in versions[:4]))
        parts.append('diff 可按 key/文件名读取')
        lines.append(' '.join(parts))
    return '\n'.join(lines).strip()


def _history_file_identity_prompt(records: list[dict] | None = None, *, max_items: int = 10) -> str:
    rows = []
    seen = set()
    lineage = _history_file_lineage_prompt(records or [], max_groups=min(max(1, int(max_items or 10)), 8))
    if lineage:
        rows.append(lineage)
    detail_rows = []
    for rec in (records or []):
        if not isinstance(rec, dict) or not str(rec.get('filename') or rec.get('saved_filename') or '').strip():
            continue
        key = _history_file_record_key(rec)
        if not key or key in seen:
            continue
        seen.add(key)
        line = _history_file_identity_line(rec)
        if line:
            detail_rows.append('- ' + line)
        if len(detail_rows) >= max(1, int(max_items or 10)):
            break
    if detail_rows:
        rows.append('文件身份明细：\n' + '\n'.join(detail_rows))
    if not rows:
        return ''
    return '\n'.join(rows)


def _history_file_lineage_names(rec: dict | None = None) -> list[str]:
    """Compatibility adapter backed by FileLineageRegistry.

    Keep the old public helper name because other modules call it, but do not
    maintain a second lineage parser here.
    """
    helper = globals().get('file_lineage_record_names')
    if callable(helper):
        try:
            return helper(rec or {})
        except Exception:
            return []
    return []

def _select_lineage_source_file_records(records: list[dict] | None = None, seeds: list[dict] | None = None, limit: int | None = None) -> list[dict]:
    """Select original/source records structurally linked to generated edit outputs.

    This avoids losing the user's original upload after several generated versions,
    without adding keyword or intent rules.
    """
    all_records = [dict(rec) for rec in (records or []) if isinstance(rec, dict) and str(rec.get('filename') or '').strip()]
    seed_records = [dict(rec) for rec in (seeds or []) if isinstance(rec, dict)]
    wanted: set[str] = set()
    for rec in seed_records:
        for name in _history_file_lineage_names(rec):
            raw = str(name or '').strip().lower()
            base = os.path.basename(raw.replace('\\', '/')).strip().lower()
            if raw:
                wanted.add(raw)
            if base:
                wanted.add(base)
    if not wanted:
        return []
    max_items = max(1, int(limit or _HISTORY_FILE_RECALL_MAX_FILES))
    out: list[dict] = []
    seen: set[str] = set()
    for rec in all_records:
        filename = str(rec.get('filename') or '').strip()
        saved = str(rec.get('saved_filename') or '').strip()
        candidates = {filename.lower(), os.path.basename(filename).lower(), saved.lower(), os.path.basename(saved).lower()}
        if not any(x and x in wanted for x in candidates):
            continue
        key = _history_file_record_key(rec)
        if not key or key in seen:
            continue
        seen.add(key)
        obj = dict(rec)
        obj['_lineage_source_attachment'] = True
        out.append(obj)
        if len(out) >= max_items:
            break
    return out

def _merge_history_file_records(*groups: list[dict] | None, limit: int | None = None) -> list[dict]:
    out: list[dict] = []
    seen = set()
    max_items = max(1, int(limit or _HISTORY_FILE_RECALL_MAX_FILES))
    for group in groups:
        for rec in (group or []):
            if not isinstance(rec, dict) or not str(rec.get('filename') or '').strip():
                continue
            key = _history_file_record_key(rec)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(dict(rec))
            if len(out) >= max_items:
                return out
    return out


def _last_user_message_index(messages: list | None = None) -> int:
    for idx in range(len(messages or []) - 1, -1, -1):
        m = (messages or [])[idx]
        if isinstance(m, dict) and str(m.get('role') or '').strip() == 'user':
            return idx
    return -1


def _history_file_message_is_file_carrier(message: dict | None = None) -> bool:
    m = dict(message or {})
    content = m.get('content')
    if isinstance(content, dict) and str(content.get('_kind') or '') in {'file', 'genfiles'}:
        return True
    if isinstance(m.get('generatedFiles'), list) or isinstance(m.get('generated_files'), list):
        return True
    return False


def _previous_assistant_index(messages: list | None = None, before_idx: int = -1) -> int:
    end = before_idx if before_idx >= 0 else len(messages or [])
    for idx in range(end - 1, -1, -1):
        m = (messages or [])[idx]
        if not isinstance(m, dict) or str(m.get('role') or '').strip() != 'assistant':
            continue
        # Synthetic assistant genfiles are file carriers, not conversational turns.
        # Skipping them lets current user-selected generated files remain bound to
        # the current request.
        if _history_file_message_is_file_carrier(m):
            continue
        return idx
    return -1


def _select_current_turn_file_records(records: list[dict] | None = None, messages: list | None = None) -> list[dict]:
    """Return files attached in the same user turn as the latest question.

    不再按用户话术写关键词规则；只根据消息结构判断：同一轮上传并随即提问的附件，
    作为当前轮可用文件资料进入候选上下文，后续由模型结合用户意图自然决定如何使用。
    """
    items = [dict(rec) for rec in (records or []) if isinstance(rec, dict) and str(rec.get('filename') or '').strip()]
    if not items:
        return []
    last_user_idx = _last_user_message_index(messages or [])
    if last_user_idx < 0:
        return []
    prev_assistant_idx = _previous_assistant_index(messages or [], before_idx=last_user_idx)
    selected: list[dict] = []
    seen = set()

    def push_current(rec: dict) -> None:
        key = _history_file_record_key(rec)
        if not key or key in seen:
            return
        seen.add(key)
        obj = dict(rec)
        obj['_current_turn_attachment'] = True
        selected.append(obj)

    # Explicit current-turn marker is the strongest signal.  It is used when the
    # user attached a newly uploaded file or selected a historical file into the
    # composer for this turn.  Keep a small structural window so stale saved
    # markers from old messages cannot hijack future turns.
    for rec in sorted(items, key=lambda r: float((r or {}).get('order') or 0.0)):
        try:
            order = float(rec.get('order') or 0.0)
        except Exception:
            order = 0.0
        if not bool(rec.get('_current_turn_attachment')):
            continue
        if not (max(-1.0, float(last_user_idx) - 6.0) <= order <= float(last_user_idx) + 0.01):
            continue
        push_current(rec)
    if selected:
        return selected

    for rec in sorted(items, key=lambda r: float((r or {}).get('order') or 0.0)):
        try:
            order = float(rec.get('order') or 0.0)
        except Exception:
            order = 0.0
        if not (prev_assistant_idx < order < last_user_idx):
            continue
        push_current(rec)
    return selected


def _select_active_recent_file_records(records: list[dict] | None = None, messages: list | None = None, limit: int | None = None) -> list[dict]:
    """Return the most recent file records as active reading context.

    这不是按“这个/那个/完整题目”等话术硬判，而是按对话结构延续最近的附件对象：
    用户上传/生成文件后，后续几轮追问仍应能看到同一份文件的正文片段。
    """
    items = [dict(rec) for rec in (records or []) if isinstance(rec, dict) and str(rec.get('filename') or '').strip()]
    if not items:
        return []
    last_user_idx = _last_user_message_index(messages or [])
    if last_user_idx < 0:
        return []
    max_gap = max(4, int(_HISTORY_FILE_ACTIVE_WINDOW_MESSAGES or 18))
    max_items = max(1, int(limit or _HISTORY_FILE_RECALL_MAX_FILES))
    ranked: list[tuple[float, dict]] = []
    for rec in items:
        try:
            order = float(rec.get('order') or 0.0)
        except Exception:
            order = 0.0
        if not (order < last_user_idx):
            continue
        gap = float(last_user_idx) - order
        if gap > max_gap:
            continue
        ranked.append((order, rec))
    if not ranked:
        return []
    ranked.sort(key=lambda item: item[0], reverse=True)
    out: list[dict] = []
    seen = set()
    for _order, rec in ranked:
        key = _history_file_record_key(rec)
        if not key or key in seen:
            continue
        seen.add(key)
        obj = dict(rec)
        obj['_active_recent_attachment'] = True
        out.append(obj)
        if len(out) >= max_items:
            break
    out.sort(key=lambda r: float((r or {}).get('order') or 0.0))
    return out


def _file_registry_record_text_by_id(file_id: str = '') -> str:
    fid = str(file_id or '').strip()
    if not fid:
        return ''
    try:
        _file_registry_load()
    except Exception:
        pass
    try:
        with _FILE_REGISTRY_LOCK:
            rec = dict(((_FILE_REGISTRY_STATE.get('files') or {}).get(fid) or {}))
    except Exception:
        rec = {}
    if not rec:
        return ''
    full_ref = str(rec.get('full_text_ref') or '').strip()
    if full_ref:
        full_text = _file_text_store_read_text(full_ref, max_chars=_file_context_read_max_chars())
        if full_text:
            return _file_registry_model_text(full_text, str(rec.get('filename') or rec.get('saved_filename') or ''))
    chunks = rec.get('chunks') or []
    parts = []
    if isinstance(chunks, list):
        for item in chunks:
            if isinstance(item, dict):
                piece = str(item.get('text') or '').strip()
                if piece:
                    parts.append(piece)
            elif isinstance(item, str) and item.strip():
                parts.append(item.strip())
    text = '\n\n'.join(parts).strip()
    if text:
        return truncate_text(text, max_chars=_file_context_read_max_chars())
    preview = str(rec.get('preview') or '').strip()
    if preview:
        return preview
    return str(rec.get('summary') or '').strip()


def _history_file_resolve_path(record: dict | None = None) -> str:
    rec = dict(record or {})
    namespace = str(rec.get('namespace') or '').strip().lower()
    source = str(rec.get('source') or '').strip().lower()
    saved_hint = str(rec.get('saved_filename') or '').strip()

    def _is_generated_url(raw_url: str) -> bool:
        try:
            path = urllib.parse.urlparse(str(raw_url or '')).path
        except Exception:
            path = str(raw_url or '')
        return '/api3/generated-download/' in path or '/api3/generated-files/' in path

    for raw_url in (rec.get('url'), rec.get('download_url'), rec.get('view_url')):
        saved_name = _extract_saved_filename_from_url(raw_url or '') or saved_hint
        if not saved_name:
            continue
        preferred_scope = _extract_upload_scope_from_url(raw_url or '') or str(rec.get('scope') or '') or _request_upload_scope()
        if namespace == 'generated' or source == 'generated' or _is_generated_url(raw_url or ''):
            base_dir = _resolve_generated_file_dir(saved_name, scope=preferred_scope)
        else:
            base_dir = _resolve_uploaded_file_dir(saved_name, scope=preferred_scope)
        if base_dir:
            fp = os.path.join(base_dir, saved_name)
            if os.path.isfile(fp):
                return fp

    filename = saved_hint or str(rec.get('filename') or '').strip()
    if filename:
        preferred_scope = str(rec.get('scope') or '') or _request_upload_scope()
        if namespace == 'generated' or source == 'generated':
            base_dir = _resolve_generated_file_dir(filename, scope=preferred_scope)
        else:
            base_dir = _resolve_uploaded_file_dir(filename, scope=preferred_scope)
        if base_dir:
            fp = os.path.join(base_dir, filename)
            if os.path.isfile(fp):
                return fp
    return ''


def _history_file_parse_raw(raw: bytes, filename: str) -> str:
    ext = _history_file_ext(filename)
    text_like = {
        '.txt', '.md', '.json', '.jsonl', '.csv', '.tsv', '.log', '.cfg', '.py', '.c', '.cc', '.cpp', '.cxx', '.h', '.hpp',
        '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.mts', '.cts', '.java', '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.cs',
        '.sql', '.yaml', '.yml', '.xml', '.toml', '.ini', '.sh', '.bat', '.ps1', '.proto', '.properties', '.conf', '.gradle', '.plist', '.ipynb',
        '.html', '.htm', '.css', '.scss', '.less', '.svg', '.vue', '.svelte', '.astro', ''
    }
    archives = {'.zip', '.7z', '.rar', '.tar', '.gz', '.tgz', '.bz2', '.xz'}
    if ext in text_like:
        return read_text_file(raw)
    if ext == '.pdf':
        return read_pdf(raw)
    if ext == '.docx':
        return read_docx(raw)
    if ext == '.doc':
        return read_doc(raw)
    if ext == '.xlsx':
        return read_xlsx(raw)
    if ext == '.xls':
        return read_xls(raw)
    if ext == '.pptx':
        return read_pptx(raw)
    if ext in archives:
        if ext == '.zip':
            return read_archive_bundle(raw, ext)
        return ''
    image_exts = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.ico', '.jfif'}
    if ext in image_exts:
        return _ocr_image_bytes(raw)
    return ''


def _history_file_read_text(record: dict | None = None) -> str:
    rec = dict(record or {})
    registry_ids = []
    for key in ('registry_file_id', 'file_library_id', 'library_file_id', 'account_file_id', 'file_id', 'id'):
        val = str(rec.get(key) or '').strip()
        if val and val not in registry_ids:
            registry_ids.append(val)
    registry = rec.get('file_registry') if isinstance(rec.get('file_registry'), dict) else {}
    val = str((registry or {}).get('file_id') or '').strip()
    if val and val not in registry_ids:
        registry_ids.insert(0, val)
    for file_id in registry_ids:
        registry_text = _file_registry_record_text_by_id(file_id)
        if registry_text:
            return registry_text
    try:
        loader = globals().get('_file_registry_load')
        if callable(loader):
            loader()
    except Exception:
        pass
    try:
        with _FILE_REGISTRY_LOCK:
            files = [dict(v or {}) for v in (_FILE_REGISTRY_STATE.get('files') or {}).values() if isinstance(v, dict)]
    except Exception:
        files = []
    wanted_storage = {
        str(rec.get(k) or '').strip()
        for k in ('storage_ref', 'model_storage_ref')
        if str(rec.get(k) or '').strip()
    }
    wanted_hash = {
        str(rec.get(k) or '').strip()
        for k in ('content_hash', 'hash', 'sha256')
        if str(rec.get(k) or '').strip()
    }
    wanted_names = set()
    for key in ('filename', 'saved_filename'):
        val = str(rec.get(key) or '').strip()
        if val:
            wanted_names.add(os.path.basename(val).strip().lower())
    for key in ('url', 'download_url', 'view_url'):
        val = str(rec.get(key) or '').strip()
        if not val:
            continue
        try:
            base = os.path.basename(urllib.parse.urlparse(val).path)
        except Exception:
            base = os.path.basename(val)
        if base:
            wanted_names.add(base.strip().lower())
    registry_match: dict = {}
    for found in files:
        if wanted_storage and str(found.get('storage_ref') or found.get('model_storage_ref') or '').strip() in wanted_storage:
            registry_match = found
            break
        if wanted_hash and str(found.get('content_hash') or found.get('hash') or found.get('sha256') or '').strip() in wanted_hash:
            registry_match = found
            break
        if wanted_names:
            found_names = {
                os.path.basename(str(found.get('filename') or '')).strip().lower(),
                os.path.basename(str(found.get('saved_filename') or '')).strip().lower(),
            }
            if wanted_names & {x for x in found_names if x}:
                registry_match = found
                break
    if registry_match:
        registry_text = _file_registry_record_text_by_id(str(registry_match.get('file_id') or '').strip())
        if registry_text:
            return registry_text
    path = _history_file_resolve_path(rec)
    if path:
        try:
            st = os.stat(path)
            cache_key = os.path.abspath(path)
            with _HISTORY_FILE_TEXT_CACHE_LOCK:
                cached = _HISTORY_FILE_TEXT_CACHE.get(cache_key)
            if isinstance(cached, dict):
                if float(cached.get('mtime') or 0.0) == float(st.st_mtime) and int(cached.get('size') or 0) == int(st.st_size):
                    return str(cached.get('text') or '')
            with open(path, 'rb') as f:
                raw = f.read()
            basename = os.path.basename(path)
            text = _history_file_parse_raw(raw, basename)
            text = _file_registry_model_text(text or '', basename)
            text = truncate_text(text or '', max_chars=_file_context_read_max_chars())
            with _HISTORY_FILE_TEXT_CACHE_LOCK:
                _HISTORY_FILE_TEXT_CACHE[cache_key] = {
                    'mtime': float(st.st_mtime),
                    'size': int(st.st_size),
                    'text': text,
                }
            if text:
                return text
        except Exception:
            app_logger.exception('[history_file] read_failed path=%s', path)
    inline_text = str(rec.get('inline_text') or '').strip()
    if inline_text:
        return inline_text
    return ''


def _history_file_split_chunks(text: str, target_chars: int = 1200, overlap: int = 140) -> list[str]:
    raw = str(text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not raw:
        return []
    paras = [p.strip() for p in re.split(r'\n{2,}', raw) if str(p or '').strip()]
    if not paras:
        paras = [raw]
    chunks: list[str] = []
    buf = ''
    for para in paras:
        if not buf:
            buf = para
            continue
        if len(buf) + 2 + len(para) <= max(600, int(target_chars or 1200)):
            buf += '\n\n' + para
        else:
            chunks.append(buf.strip())
            if overlap > 0 and len(buf) > overlap:
                prefix = buf[-overlap:].strip()
                buf = (prefix + '\n\n' + para).strip() if prefix else para
            else:
                buf = para
    if buf.strip():
        chunks.append(buf.strip())
    if len(chunks) <= 1 and len(raw) > target_chars:
        chunks = []
        step = max(500, int(target_chars or 1200) - max(0, int(overlap or 0)))
        size = max(700, int(target_chars or 1200))
        for start in range(0, len(raw), step):
            piece = raw[start:start + size].strip()
            if piece:
                chunks.append(piece)
    return chunks[:64]



def _file_context_expanded_query_terms_for_code(text: str) -> list[str]:
    """Generic retrieval expansion for code contexts.

    This intentionally avoids project-specific mappings such as mapping one UI
    requirement to a particular function name. It only normalizes the user's
    words into broad code-search terms; the model/tooling must inspect the
    ranked real code blocks and decide what to edit.
    """
    q = str(text or '').lower()
    raw = str(text or '')
    terms: list[str] = []

    def add(*vals):
        for v in vals:
            v = str(v or '').strip().lower()
            if v and v not in terms:
                terms.append(v)

    for t in _history_file_query_terms(raw):
        add(t)
        spaced = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', str(t or ''))
        for part in re.split(r'[^0-9A-Za-z]+', spaced):
            if len(part) >= 2:
                add(part)

    # Broad bilingual UI/code vocabulary only. These are generic retrieval hints,
    # not routing rules and not tied to any project-specific function/variable.
    vocab = [
        (('显示', '展示', '提示', '渲染', '呈现'), ('render', 'display', 'show', 'text', 'textcontent')),
        (('为空', '空状态', '没有', '暂无', '空列表', '空队列'), ('empty', 'blank', 'length', 'count', 'if', 'return')),
        (('队列', '列表', '待处理'), ('queue', 'list', 'items')),
        (('上传', '附件', '文件'), ('upload', 'file', 'files', 'attachment')),
        (('按钮', '点击', '删除', '关闭'), ('button', 'click', 'delete', 'remove', 'close')),
        (('输入', '发送', '消息'), ('input', 'send', 'message')),
        (('新增', '创建', '插入'), ('create', 'append', 'insert', 'add')),
        (('移除', '清空', '重置'), ('remove', 'clear', 'reset')),
    ]
    for zh_terms, code_terms in vocab:
        if any(x in raw for x in zh_terms):
            add(*code_terms)

    if any(x in q for x in ('empty state', 'empty', 'blank', 'no files', 'no items')):
        add('empty', 'blank', 'length', 'count', 'if', 'return')
    if any(x in q for x in ('render', 'display', 'show', 'hint', 'status', 'state')):
        add('render', 'display', 'show', 'textcontent')
    if any(x in q for x in ('queue', 'list', 'items')):
        add('queue', 'list', 'items')
    if any(x in q for x in ('upload', 'file', 'attachment')):
        add('upload', 'file', 'files', 'attachment')

    return terms[:40]

def _history_file_chunk_score(chunk: str, query: str, filename: str = '') -> float:
    text = str(chunk or '')
    lowered = text.lower()
    score = 0.0
    for term in _history_file_query_terms(query):
        if not term:
            continue
        t = term.lower()
        hits = lowered.count(t)
        if hits > 0:
            score += min(5, hits) * (1.0 + min(len(t), 8) * 0.12)
    # Behavior-level code retrieval: when the user describes UI behavior rather
    # than a function name, boost code terms that implement that behavior.
    # This is only for ranking snippets after a file has already been selected.
    for term in _file_context_expanded_query_terms_for_code(query):
        t = term.lower()
        if not t:
            continue
        hits = lowered.count(t)
        if hits > 0:
            score += min(6, hits) * (1.25 + min(len(t), 14) * 0.08)
    for stem in _history_file_stems(filename):
        if stem and stem in lowered:
            score += 1.4
    clause = re.search(r'第\\s*([0-9一二三四五六七八九十百千万]+)\\s*([条章节点页])', str(query or ''), flags=re.I)
    if clause:
        phrase = str(clause.group(0) or '').strip().lower()
        if phrase and phrase in lowered:
            score += 6.0
    if not score:
        head = text[:220]
        if head:
            score += 0.1
    return score


def _history_file_select_snippets(text: str, query: str, filename: str = '', *, prefer_overview: bool = False, max_snippets: int | None = None, snippet_chars: int = 1600, max_total_chars: int | None = None) -> list[str]:
    target_chars = max(900, int(snippet_chars or 1600))
    chunks = _history_file_split_chunks(text, target_chars=target_chars, overlap=160)
    if not chunks:
        return []
    limit = max(1, int(max_snippets or _HISTORY_FILE_RECALL_MAX_CHUNKS_PER_FILE))
    char_limit = max(1200, int(max_total_chars or _HISTORY_FILE_RECALL_MAX_TOTAL_CHARS))

    if prefer_overview or _history_file_query_needs_overview(query):
        out: list[str] = []
        total_chars = 0
        for chunk in chunks[:limit]:
            piece = truncate_text(chunk, max_chars=target_chars)
            if not piece:
                continue
            if total_chars + len(piece) > char_limit and out:
                break
            if total_chars + len(piece) > char_limit:
                piece = truncate_text(piece, max_chars=max(800, char_limit - total_chars))
            out.append(piece)
            total_chars += len(piece)
            if total_chars >= char_limit:
                break
        if out:
            return out

    ranked = []
    for idx, chunk in enumerate(chunks):
        ranked.append((_history_file_chunk_score(chunk, query, filename=filename), idx, chunk))
    ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    out: list[str] = []
    total_chars = 0
    for score, _idx, chunk in ranked:
        piece = truncate_text(chunk, max_chars=target_chars)
        if not piece:
            continue
        if score <= 0 and out:
            continue
        if total_chars + len(piece) > char_limit and out:
            break
        if total_chars + len(piece) > char_limit:
            piece = truncate_text(piece, max_chars=max(800, char_limit - total_chars))
        out.append(piece)
        total_chars += len(piece)
        if len(out) >= limit:
            break
    if not out:
        return [truncate_text(chunks[0], max_chars=target_chars)]
    return out

def _structured_content_to_model_text(content) -> str:
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        kind = str(content.get('_kind') or '').strip()
        if kind == 'file':
            filename = str(content.get('filename') or '').strip()
            note = str(content.get('note') or '').strip()
            text = f'用户上传了文件《{filename}》。' if filename else '用户上传了一个文件。'
            if note:
                text += f' 备注：{note}'
            return text
        if kind == 'image':
            filename = str(content.get('filename') or '').strip()
            return f'用户上传了图片《{filename}》。' if filename else '用户上传了一张图片。'
        if kind == 'genfiles':
            names = [str((item or {}).get('filename') or '').strip() for item in (content.get('files') or []) if isinstance(item, dict)]
            names = [name for name in names if name]
            if names:
                joined = '、'.join(names[:8])
                if len(names) > 8:
                    joined += ' 等'
                return f'本对话中已生成文件：{joined}。'
            return '本对话中已生成可下载文件。'
        if kind == 'image_reply':
            imgs = content.get('images') if isinstance(content.get('images'), list) else []
            subject = str(content.get('subject') or '').strip()
            prefix = f'本对话中已有图片结果：{subject}。' if subject else '本对话中已有图片结果。'
            if imgs:
                prefix += f' 共{len(imgs)}张，可作为后续看图、评价、参考或继续改图的候选图片。'
            return prefix
        try:
            return json.dumps(content, ensure_ascii=False)
        except Exception:
            return str(content)
    if isinstance(content, list):
        return _msg_content_text(content)
    return str(content)




def _prepare_messages_should_inject_file_guidance(user_text: str = '', messages: list | None = None) -> bool:
    """Return whether the static file/code guidance is useful for this turn.

    The old path injected file-delivery and Chinese-code prompts into every
    request.  That is safe but costs tokens on ordinary chat.  Keep the guidance
    when the current turn mentions code, file creation/editing/reading, explicit
    export/download formats, or carries attachments.
    """
    text = str(user_text or '').strip()
    low = text.lower()
    if not text:
        return False
    try:
        explicit_delivery = globals().get('_has_explicit_file_delivery_intent')
        if callable(explicit_delivery) and explicit_delivery(text):
            return True
    except Exception:
        pass
    code_file_pattern = (
        r'(代码|源码|脚本|函数|接口|api|bug|报错|错误|日志|运行|执行|测试|调试|修复|重构|部署|编译|依赖|'
        r'文件|附件|下载|导出|保存|生成.*文档|生成.*表格|生成.*幻灯片|压缩包|zip|diff|对比|沙盒|sandbox|'
        r'pdf|docx|xlsx|pptx|csv|json|yaml|yml|xml|md|txt|py|js|ts|tsx|jsx|html|css|java|go|rust|rs|php|sql|sh|bash|powershell|ps1)'
    )
    english_pattern = (
        r'\b(code|source|script|function|api|bug|error|log|run|execute|test|debug|fix|refactor|deploy|compile|'
        r'file|files|attachment|download|export|save|document|spreadsheet|slides|zip|diff|pdf|docx|xlsx|pptx|csv|json|yaml|markdown|python|javascript|typescript|html|css|java|golang|rust|sql|shell|bash|powershell)\b'
    )
    try:
        if re.search(code_file_pattern, text, flags=re.I) or re.search(english_pattern, low, flags=re.I):
            return True
    except Exception:
        pass
    for m in reversed(list(messages or [])[-6:]):
        if not isinstance(m, dict):
            continue
        if str(m.get('role') or '').strip().lower() != 'user':
            continue
        for key in ('file_attachments', 'attachments', '_composer_file_attachments'):
            if isinstance(m.get(key), list) and m.get(key):
                return True
        content = m.get('content')
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and (item.get('file') or item.get('filename') or item.get('file_id') or item.get('registry_file_id')):
                    return True
    return False

def _prepare_messages(messages: list, user_geo: dict | None = None, web_enabled: bool | None = None, web_k: int | None = None, web_max_pages: int | None = None, stats: dict | None = None, kb_enabled: bool | None = True, kb_space_id: str = '', kb_doc_id: str = '') -> list:
    """轻量预处理：这里只做显式 URL 抓取与必要的 system 注入。
    自动联网搜索不再在这里提前触发，避免和后续“先工具、再 AI 提关键词补网页”的主流程重复。"""
    msgs = list(messages or [])

    url_text = ""
    url_err = None
    is_github_repo = False

    # ---- 1) 找到最后一条用户消息
    last_user = None
    for mm in reversed(msgs):
        if isinstance(mm, dict) and mm.get("role") == "user":
            last_user = mm
            break
    user_text = _combine_message_text_and_quote(_msg_content_text((last_user or {}).get('content')), _message_quote_text(last_user or {})).strip()
    # 旧文件正文/片段预读链路已停用。已有文件只通过 sandbox manifest
    # 选择导入目标，真实内容必须进入 /mnt/data 后由 sandbox_read_file/sandbox_run 读取。
    file_memory_prompt = ''
    file_recall_prompt = ''
    kb_ctx = _prepare_knowledge_base_context(current_user_text=user_text, kb_enabled=bool(kb_enabled is not False), kb_space_id=str(kb_space_id or '').strip(), kb_doc_id=str(kb_doc_id or '').strip())
    kb_memory_prompt = str((kb_ctx or {}).get('memory_prompt') or '').strip()
    kb_recall_prompt = str((kb_ctx or {}).get('recall_prompt') or '').strip()
    kb_doc_brief_prompt = str((kb_ctx or {}).get('doc_brief_prompt') or '').strip()
    kb_active_doc = dict((kb_ctx or {}).get('active_document') or {}) if isinstance((kb_ctx or {}).get('active_document'), dict) else {}
    kb_search_result = dict((kb_ctx or {}).get('search') or {}) if isinstance((kb_ctx or {}).get('search'), dict) else {}
    kb_result_items = [dict(item) for item in (kb_search_result.get('results') or []) if isinstance(item, dict) and str(item.get('text') or '').strip()]
    kb_existing_file_content_query = False
    if kb_active_doc:
        active_filename = str(kb_active_doc.get('filename') or '').strip()
        active_terms = [term for term in [active_filename.lower(), *_history_file_stems(active_filename)] if str(term or '').strip()]
        lowered_user_text = str(user_text or '').strip().lower()
        asks_file_content = bool(
            _history_file_query_needs_overview(user_text)
            or re.search(r'(主要|具体|大概|大致).{0,8}(内容|写了什么|讲了什么|说了什么)', str(user_text or ''), flags=re.I)
            or re.search(r'(总结|概括|摘要|梗概|主题|重点|要点|介绍)', str(user_text or ''), flags=re.I)
        )
        mentions_active_file = bool(active_terms and any(term and term in lowered_user_text for term in active_terms))
        referential_to_file = _history_file_query_looks_referential(user_text, [{'filename': active_filename}])
        kb_existing_file_content_query = bool(asks_file_content and (mentions_active_file or referential_to_file or kb_result_items))
    # URL + 文字混写的通用处理：把 URL 跟“指令/问题”拆开，避免把中文当成 URL 路径导致 404
    url0, tail_text = _first_url_and_tail(user_text)
    user_text_intent = (tail_text or "").strip() or re.sub(r"https?://\S+", " ", user_text).strip()


    # ---- 2) 先处理用户显式 URL（保留原功能）
    _t0_url = time.perf_counter()
    try:
        urls = ([url0] if url0 else _extract_urls(user_text))
        if urls:
            try:
                u0 = urls[0]
                u0 = _normalize_url_for_fetch(u0)
                # 普通网页正文
                out = fetch_url_content_smart(u0, query=user_text_intent, max_chars=12000)
                url_text = _compress_injected_text(u0, (out.get("text") or "").strip(), max_chars=8000)
                url_err = out.get("error")
                extracted_len = len((out.get("text") or "").strip())
                if not url_text:
                    url_err = url_err or "empty extracted text"
                try:
                    app_logger.info(
                        "[prepare_messages][url_fetch] url=%s final_url=%s title=%r content_type=%s content_source=%s page_type=%s text_len=%s compressed_len=%s warning=%r error=%r",
                        u0,
                        str(out.get("final_url") or "")[:300],
                        str(out.get("title") or "")[:120],
                        str(out.get("content_type") or "")[:120],
                        str(out.get("content_source") or out.get("provider") or "")[:80],
                        str(out.get("page_type") or "")[:40],
                        extracted_len,
                        len(url_text),
                        str(out.get("warning") or "")[:300],
                        str(url_err or "")[:220],
                    )
                except Exception:
                    pass
                try:
                    ct = str(out.get("content_type") or "").lower()
                    if "github-repo" in ct or ("github.com" in (u0.lower())):
                        is_github_repo = True
                except Exception:
                    pass
            except Exception as e:
                url_text, url_err = "", f"{type(e).__name__}: {e}"
                try:
                    app_logger.warning("[prepare_messages][url_fetch] url=%s exception=%s", u0, url_err[:300])
                except Exception:
                    pass
        else:
            # 没有显式 URL：不再做“商品/价格抓取”（已移除该功能）
            pass
    except Exception as e:
        url_text, url_err = "", f"{type(e).__name__}: {e}"
    finally:
        if isinstance(stats, dict):
            stats.setdefault("url_fetch", {})
            stats["url_fetch"].update({
                "took_ms": int((time.perf_counter() - _t0_url) * 1000),
                "has_url": bool(_extract_urls(user_text)),
                "ok": bool(url_text),
            })
            if url_err:
                stats["url_fetch"]["error"] = str(url_err)[:180]


    # ---- 3) 自动联网搜索改为后置编排：这里只保留显式 URL 结果，不在进入主流程前抢先联网。
    web_sys_blocks = []

# ---- 4) 组装最终 messages（保持你原来的“system 注入在前”风格）
    out = []
    if web_sys_blocks:
        out.append({
            "role": "system",
            "content": "你已获得实时外部信息（联网搜索结果/网页抓取内容）。请优先基于这些材料回答，并在需要时引用其中的标题/链接；不要再说“无法联网/不能实时获取”。"
        })
        out.extend(web_sys_blocks)


    if url_text:
        if is_github_repo:
            out.append({
                "role": "system",
                "content": "用户提供的是 GitHub 仓库链接。请只基于仓库信息与 README，按以下结构用中文回答：\n1) 项目是做什么的（1-2句）\n2) 主要功能（3-6点）\n3) 适合谁使用\n4) 快速开始（若 README 提供安装/运行命令，请列出）\n5) 注意事项/局限（若 README 提到）"
            })
        out.append({
            "role": "system",
            "_kind": "page",
            "content": "以下是用户提供链接抓取到的网页正文（已做清洗与截断）。请基于它回答/总结，不要说无法访问：\n" + url_text
        })
    elif url_err is not None and url_err:
        out.append({
            "role": "system",
            "_kind": "page",
            "content": f"已检测到用户提供的链接，但抓取网页失败：{url_err}。如需要，请根据你已有知识回答，并说明抓取失败。"
        })


    # ====== Smart file-delivery / code guidance ======
    if _prepare_messages_should_inject_file_guidance(user_text, msgs):
        runtime_plan_prompt = ''
        try:
            prompt_builder = globals().get('skill_runtime_prompt')
            if callable(prompt_builder):
                runtime_plan_prompt = str(prompt_builder('chat_completions', ['sandbox'], compact=True) or '').strip()
        except Exception:
            runtime_plan_prompt = ''
        out.append({
            "role": "system",
            "_kind": "file_delivery_soft_prompt",
            "content": (
                "文件/代码任务只保留轻量提示：能直接聊天回答就直接答；只有用户明确要导出、下载、附件、源码包、保存文件，"
                "或确实需要读取/修改/运行已有文件时，才进入 sandbox artifact runtime。已有文件名或扩展名通常是上下文对象，"
                "不要误判成生成同扩展名的新文件。"
                + (runtime_plan_prompt + " " if runtime_plan_prompt else "")
                + "不要用正文代码块或 artifacts JSON 替代真实文件。写代码时保持 UTF-8，中文注释按需求保留，必要术语可用英文。"
            ),
        })


    if kb_memory_prompt:
        out.append({
            "role": "system",
            "_kind": "kb_memory",
            "content": kb_memory_prompt,
        })
    if kb_recall_prompt:
        out.append({
            "role": "system",
            "_kind": "kb_recall",
            "content": kb_recall_prompt,
        })
    if kb_doc_brief_prompt:
        out.append({
            "role": "system",
            "_kind": "kb_doc_brief",
            "content": kb_doc_brief_prompt,
        })
    if kb_existing_file_content_query and kb_active_doc:
        active_name = str(kb_active_doc.get('filename') or '未命名文件').strip() or '未命名文件'
        hit_count = len(kb_result_items)
        direct_hint = [
            f"用户当前是在追问现有文档《{active_name}》本身。先把它当成正在阅读的对象，再自然回答。",
            "优先综合文档上下文包与知识库命中片段进行概括；回答语气保持自然，不要写成规则说明。",
        ]
        if hit_count > 0:
            direct_hint.append(f"当前轮已有 {hit_count} 条来自该文档的命中片段，可直接组织成摘要/要点。")
        else:
            direct_hint.append("如果现有证据仍不足，可以明确说明“知识库命中不足”；但不要误解成让你生成文件或重新上传文件。")
        out.append({
            "role": "system",
            "_kind": "kb_existing_file_answer",
            "content": '\n'.join(direct_hint),
        })

    out.extend(msgs)
    try:
        deduper = globals().get('_orch_dedupe_model_messages')
        if callable(deduper):
            out = deduper(out)
    except Exception:
        pass
    return out


def _compress_injected_text(url: str, text: str, max_chars: int = 8000) -> str:
    """把抓取/注入的长文本压缩成更“可喂给模型”的摘要段（避免上下文溢出）。
    目标：尽量保留标题、列表、带价格/流量/关键词的行，以及关键行附近的上下文。
    """
    if not text:
        return ""

    # 先做基础清洗
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln]  # drop empty

    # GitHub/README/“机场推荐”常见关键词
    kw = [
        "机场", "推薦", "推荐", "评测", "測速", "测速", "价格", "價", "¥", "￥",
        "月", "年", "季", "GB", "TB", "流量", "节点", "節點", "解锁", "解鎖",
        "中转", "中轉", "专线", "專線", "IEPL", "IPLC", "BGP",
        "Clash", "Surge", "Quantumult", "v2ray", "V2Ray", "Trojan", "SSR", "Shadowsocks",
        "Telegram", "TG"
    ]

    def is_heading(ln: str) -> bool:
        return ln.startswith("#") or re.match(r"^\s*\*\*.*\*\*\s*$", ln) is not None

    # 1) 优先：捕捉“推荐/机场”相关标题段
    picked = []
    used = set()

    # 标题块抓取：遇到包含关键词的标题，向后抓取一小段直到下一个大标题/达到上限
    i = 0
    while i < len(lines):
        ln = lines[i]
        if is_heading(ln) and any(k in ln for k in ("机场", "推荐", "推薦", "评测", "評測")):
            # 抓取该标题及后续最多 N 行
            for j in range(i, min(i + 120, len(lines))):
                l2 = lines[j]
                if j != i and is_heading(l2) and l2.startswith("#"):  # 新大标题
                    break
                if l2 not in used:
                    picked.append(l2); used.add(l2)
            i = j
            continue
        i += 1

    # 2) 关键词行 + 邻近上下文（±2 行）
    idxs = []
    for i, ln in enumerate(lines):
        if any(k in ln for k in kw):
            idxs.append(i)
    for i in idxs:
        for j in range(max(0, i - 2), min(len(lines), i + 3)):
            l2 = lines[j]
            if l2 not in used:
                picked.append(l2); used.add(l2)

    # 3) 如果还没抓到东西，就退化为前若干行
    if not picked:
        picked = lines[:200]

    out = "\n".join(picked).strip()

    # 4) 最终截断
    if len(out) > max_chars:
        out = out[:max_chars].rstrip() + "…（内容过长已截断）"

    # 加个很短的上下文提示（不占太多 token）
    if url:
        out = f"[来源] {url}\n" + out
    return out
