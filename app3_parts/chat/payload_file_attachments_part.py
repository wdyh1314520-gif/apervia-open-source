# current-turn payload file attachment normalization and merge helpers.

def _latest_user_text_from_payload(payload: dict) -> str:
    text = str(payload.get("text") or payload.get("message") or "").strip()
    if text:
        return text
    msgs = payload.get("messages")
    if not isinstance(msgs, list):
        msgs = payload.get("history") if isinstance(payload.get("history"), list) else []
    for item in reversed(msgs or []):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            chunks = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    t = str(part.get("text") or "").strip()
                    if t:
                        chunks.append(t)
            if chunks:
                return "\n".join(chunks).strip()
    return ""


def _payload_file_attachment_items(payload: dict | None = None) -> list[dict]:
    src = payload if isinstance(payload, dict) else {}
    for key in ('file_attachments', 'files', 'attachments', 'current_files', 'uploaded_files'):
        val = src.get(key)
        if isinstance(val, list) and val:
            return [dict(x) for x in val if isinstance(x, dict)]
    return []


def _payload_file_attachment_is_current_turn(item: dict | None = None) -> bool:
    row = dict(item or {})
    scope = str(row.get('turn_scope') or row.get('request_scope') or row.get('scope') or '').strip().lower()
    return bool(
        row.get('_current_turn_attachment')
        or row.get('current_turn')
        or row.get('currentTurn')
        or row.get('selected_for_current_turn')
        or row.get('selectedForCurrentTurn')
        or scope in {'current', 'current_turn', 'composer', 'current-user-message', 'current_user_message'}
    )

def _payload_file_source_role(raw: dict | None = None, registry: dict | None = None) -> tuple[str, str]:
    row = dict(raw or {})
    reg = dict(registry or {})
    role = str(row.get('source_role') or row.get('sourceRole') or row.get('version_role') or row.get('versionRole') or '').strip().lower()
    source_type = str(row.get('source_type') or row.get('sourceType') or row.get('source') or reg.get('source') or reg.get('namespace') or '').strip().lower()
    has_edit_lineage = bool(
        isinstance(row.get('edited_from'), dict)
        or isinstance(row.get('edit_audit'), dict)
        or isinstance(row.get('file_edit_audit'), dict)
        or isinstance(row.get('edit_details'), dict)
    )
    if role in {'edited_output', 'assistant_edited', 'edited'}:
        return 'generated', 'edited_output'
    if role in {'assistant_generated', 'latest_generated', 'generated', 'assistant_file', 'assistant'}:
        return 'generated', 'assistant_generated'
    if source_type in {'generated', 'assistant_generated', 'edited_output'} or str(reg.get('namespace') or '').strip().lower() == 'generated':
        return 'generated', 'edited_output' if has_edit_lineage else 'assistant_generated'
    return 'upload', 'user_upload'

def _normalize_payload_file_attachment(item: dict | None = None) -> dict | None:
    raw = dict(item or {})
    registry = raw.get('file_registry') if isinstance(raw.get('file_registry'), dict) else {}
    registry = dict(registry or {})
    filename = str(raw.get('filename') or raw.get('name') or registry.get('filename') or registry.get('original_filename') or registry.get('saved_filename') or '').strip()
    if not filename:
        return None
    ext = str(raw.get('ext') or registry.get('ext') or _history_file_ext(filename) or '').strip().lower()
    if ext and not ext.startswith('.'):
        ext = '.' + ext.lstrip('.').lower()
    registry_file_id = str(raw.get('registry_file_id') or registry.get('file_id') or raw.get('file_id') or '').strip()
    if registry_file_id and not registry.get('file_id'):
        registry['file_id'] = registry_file_id
    storage_ref = str(raw.get('storage_ref') or raw.get('model_storage_ref') or registry.get('storage_ref') or registry.get('model_storage_ref') or '').strip()
    model_storage_ref = str(raw.get('model_storage_ref') or raw.get('storage_ref') or registry.get('model_storage_ref') or registry.get('storage_ref') or '').strip()
    if storage_ref and not registry.get('storage_ref'):
        registry['storage_ref'] = storage_ref
    if model_storage_ref and not registry.get('model_storage_ref'):
        registry['model_storage_ref'] = model_storage_ref
    for key in ('namespace', 'scope', 'saved_filename', 'summary', 'full_text_ref'):
        if not registry.get(key) and raw.get(key):
            registry[key] = raw.get(key)
    for key in ('full_text_available', 'text_is_preview'):
        if key not in registry and key in raw:
            registry[key] = raw.get(key)
    for key in ('full_text_chars', 'full_text_lines', 'parsed_chars', 'parsed_lines'):
        if key not in registry and key in raw:
            registry[key] = raw.get(key)
    if not registry.get('symbols') and isinstance(raw.get('symbols'), list):
        registry['symbols'] = raw.get('symbols')
    if not registry.get('summary') and raw.get('code_summary'):
        registry['summary'] = raw.get('code_summary')
    url = str(raw.get('download_url') or raw.get('url') or registry.get('download_url') or '').strip()
    view_url = str(raw.get('view_url') or registry.get('view_url') or raw.get('url') or '').strip()
    file_id = str(raw.get('id') or raw.get('file_id') or registry_file_id or '').strip()
    if not file_id:
        try:
            file_id = 'payload_file_' + hashlib.sha1((filename + '|' + url + '|' + registry_file_id).encode('utf-8', 'ignore')).hexdigest()[:16]
        except Exception:
            file_id = 'payload_file_' + uuid.uuid4().hex[:16]
    source_type, source_role = _payload_file_source_role(raw, registry)
    turn_scope = str(raw.get('turn_scope') or raw.get('request_scope') or raw.get('scope') or '').strip().lower()
    current_turn = bool(
        raw.get('_current_turn_attachment')
        or raw.get('current_turn')
        or raw.get('currentTurn')
        or raw.get('selected_for_current_turn')
        or raw.get('selectedForCurrentTurn')
        or turn_scope in {'current', 'current_turn', 'composer', 'current-user-message', 'current_user_message'}
    )
    normalized = {'_kind': 'file', 'id': file_id, 'file_id': file_id, 'registry_file_id': registry_file_id, 'file_library_id': str(raw.get('file_library_id') or raw.get('library_file_id') or registry_file_id or '').strip(), 'library_file_id': str(raw.get('library_file_id') or raw.get('file_library_id') or registry_file_id or '').strip(), 'filename': filename, 'ext': ext, 'url': url or view_url, 'download_url': url or view_url, 'view_url': view_url, 'storage_ref': storage_ref, 'model_storage_ref': model_storage_ref, 'file_registry': registry, 'code_summary': str(raw.get('code_summary') or registry.get('summary') or '').strip(), 'note': str(raw.get('note') or '').strip(), 'source': source_type, 'source_type': source_type, 'source_role': source_role}
    if current_turn:
        normalized['_current_turn_attachment'] = True
        normalized['current_turn'] = True
        normalized['turn_scope'] = 'current_turn'
        normalized['request_scope'] = 'current_turn'
        if raw.get('selection_source'):
            normalized['selection_source'] = str(raw.get('selection_source') or '').strip()
    artifact_id = str(raw.get('artifact_id') or raw.get('artifactId') or raw.get('id') or '').strip()
    if artifact_id:
        normalized['artifact_id'] = artifact_id
    edit_audit = raw.get('edit_audit') or raw.get('file_edit_audit')
    if not edit_audit and isinstance(raw.get('edit_details'), dict):
        edit_audit = (raw.get('edit_details') or {}).get('audit')
    if isinstance(edit_audit, dict):
        normalized['edit_audit'] = dict(edit_audit)
    if isinstance(raw.get('edit_details'), dict):
        normalized['edit_details'] = dict(raw.get('edit_details') or {})
    edited_from = raw.get('edited_from')
    if isinstance(edited_from, dict):
        normalized['edited_from'] = dict(edited_from)
    return normalized

def _message_file_attachment_key(message: dict | None = None) -> str:
    msg = dict(message or {})
    content = msg.get('content')
    if not (isinstance(content, dict) and content.get('_kind') == 'file'):
        return ''
    registry = content.get('file_registry') if isinstance(content.get('file_registry'), dict) else {}
    rid = str(registry.get('file_id') or content.get('registry_file_id') or '').strip()
    if rid:
        return 'registry:' + rid
    fid = str(content.get('id') or content.get('file_id') or '').strip()
    if fid:
        return 'id:' + fid
    name = str(content.get('filename') or '').strip().lower()
    url = str(content.get('download_url') or content.get('url') or content.get('view_url') or '').strip()
    return ('nameurl:' + name + '|' + url) if (name or url) else ''


def _file_attachment_content_richness(content: dict | None = None) -> int:
    row = content if isinstance(content, dict) else {}
    reg = row.get('file_registry') if isinstance(row.get('file_registry'), dict) else {}
    score = 0
    for key in ('id', 'file_id', 'registry_file_id', 'filename', 'ext', 'url', 'view_url', 'download_url', 'code_summary'):
        if str(row.get(key) or '').strip():
            score += 1
    for key in ('file_id', 'namespace', 'scope', 'saved_filename', 'full_text_ref', 'summary'):
        if str(reg.get(key) or '').strip():
            score += 2
    if bool(row.get('full_text_available') or reg.get('full_text_available') or reg.get('full_text_ref')):
        score += 8
    try:
        score += min(8, int(row.get('parsed_chars') or reg.get('full_text_chars') or reg.get('parsed_chars') or 0) // 12000)
    except Exception:
        pass
    row_symbols = row.get('symbols') if isinstance(row.get('symbols'), list) else []
    reg_symbols = reg.get('symbols') if isinstance(reg.get('symbols'), list) else []
    score += min(10, max(len(row_symbols), len(reg_symbols)) // 20)
    return int(score)


def _merge_file_attachment_content(existing: dict | None = None, incoming: dict | None = None) -> dict:
    """Enrich an already-present file message with the fresher attachment payload.

    前端会同时把会话里的轻量 file 消息和本轮 file_attachments 发上来。
    不能因为 key 重复就直接跳过；否则旧 file 消息可能缺少 file_registry/full_text/symbols，
    后端只能看到片段，完整代码结构索引会扫不出来。
    """
    base = dict(existing or {})
    inc = dict(incoming or {})
    if not inc:
        return base
    if base.get('_kind') != 'file':
        base['_kind'] = 'file'

    def fill_text_key(key: str, *aliases: str) -> None:
        cur = str(base.get(key) or '').strip()
        if cur:
            return
        for src_key in (key, *aliases):
            val = str(inc.get(src_key) or '').strip()
            if val:
                base[key] = val
                return

    fill_text_key('id', 'file_id')
    fill_text_key('file_id', 'id')
    fill_text_key('registry_file_id')
    fill_text_key('file_library_id', 'library_file_id', 'registry_file_id')
    fill_text_key('library_file_id', 'file_library_id', 'registry_file_id')
    fill_text_key('filename', 'name')
    fill_text_key('ext')
    fill_text_key('url', 'download_url', 'view_url')
    fill_text_key('view_url', 'url', 'download_url')
    fill_text_key('download_url', 'url', 'view_url')
    fill_text_key('storage_ref', 'model_storage_ref')
    fill_text_key('model_storage_ref', 'storage_ref')
    fill_text_key('source_type', 'source')
    fill_text_key('source_role', 'sourceRole', 'version_role')
    fill_text_key('note')
    fill_text_key('code_summary')
    if not isinstance(base.get('edit_audit'), dict):
        inc_audit = inc.get('edit_audit') or inc.get('file_edit_audit')
        if not inc_audit and isinstance(inc.get('edit_details'), dict):
            inc_audit = (inc.get('edit_details') or {}).get('audit')
        if isinstance(inc_audit, dict):
            base['edit_audit'] = dict(inc_audit)
    if not isinstance(base.get('edit_details'), dict) and isinstance(inc.get('edit_details'), dict):
        base['edit_details'] = dict(inc.get('edit_details') or {})
    if not isinstance(base.get('edited_from'), dict) and isinstance(inc.get('edited_from'), dict):
        base['edited_from'] = dict(inc.get('edited_from') or {})

    for key in ('size', 'parsed_chars', 'parsed_lines', 'full_text_chars', 'full_text_lines'):
        try:
            base_val = int(base.get(key) or 0)
        except Exception:
            base_val = 0
        try:
            inc_val = int(inc.get(key) or 0)
        except Exception:
            inc_val = 0
        if inc_val > base_val:
            base[key] = inc_val

    if bool(inc.get('full_text_available')):
        base['full_text_available'] = True
    if bool(inc.get('text_is_preview')):
        base['text_is_preview'] = True

    base_symbols = base.get('symbols') if isinstance(base.get('symbols'), list) else []
    inc_symbols = inc.get('symbols') if isinstance(inc.get('symbols'), list) else []
    if len(inc_symbols) > len(base_symbols):
        base['symbols'] = inc_symbols

    base_reg = dict(base.get('file_registry') or {}) if isinstance(base.get('file_registry'), dict) else {}
    inc_reg = dict(inc.get('file_registry') or {}) if isinstance(inc.get('file_registry'), dict) else {}
    if inc.get('registry_file_id') and not inc_reg.get('file_id'):
        inc_reg['file_id'] = inc.get('registry_file_id')
    if inc.get('file_id') and not inc_reg.get('file_id'):
        inc_reg['file_id'] = inc.get('file_id')
    if inc.get('id') and not inc_reg.get('file_id'):
        inc_reg['file_id'] = inc.get('id')

    for key in (
        'file_id', 'source', 'namespace', 'scope', 'saved_filename', 'filename', 'original_filename',
        'ext', 'url', 'view_url', 'download_url', 'storage_ref', 'model_storage_ref', 'full_text_ref', 'summary', 'code_summary'
    ):
        if not str(base_reg.get(key) or '').strip() and str(inc_reg.get(key) or '').strip():
            base_reg[key] = inc_reg.get(key)

    for key in ('full_text_available', 'text_is_preview'):
        if bool(inc_reg.get(key)) and not bool(base_reg.get(key)):
            base_reg[key] = True

    for key in ('full_text_chars', 'full_text_lines', 'parsed_chars', 'parsed_lines', 'size', 'stored_text_chars'):
        try:
            base_val = int(base_reg.get(key) or 0)
        except Exception:
            base_val = 0
        try:
            inc_val = int(inc_reg.get(key) or 0)
        except Exception:
            inc_val = 0
        if inc_val > base_val:
            base_reg[key] = inc_val

    reg_symbols = base_reg.get('symbols') if isinstance(base_reg.get('symbols'), list) else []
    inc_reg_symbols = inc_reg.get('symbols') if isinstance(inc_reg.get('symbols'), list) else []
    top_symbols = base.get('symbols') if isinstance(base.get('symbols'), list) else []
    best_symbols = max([reg_symbols, inc_reg_symbols, top_symbols, inc_symbols], key=lambda arr: len(arr or []))
    if best_symbols:
        base_reg['symbols'] = best_symbols
        if len(best_symbols) > len(top_symbols):
            base['symbols'] = best_symbols

    if base_reg:
        base['file_registry'] = base_reg

    if not str(base.get('ext') or '').strip():
        reg_ext = str(base_reg.get('ext') or '').strip()
        if reg_ext:
            base['ext'] = reg_ext
        else:
            fname = str(base.get('filename') or base_reg.get('filename') or base_reg.get('saved_filename') or '').strip()
            if fname:
                base['ext'] = _history_file_ext(fname)
    if not str(base.get('filename') or '').strip():
        base['filename'] = str(base_reg.get('filename') or base_reg.get('original_filename') or base_reg.get('saved_filename') or '').strip()

    return base

def _payload_file_attachment_to_message(content: dict | None = None) -> dict:
    row = dict(content or {})
    role = str(row.get('source_role') or '').strip().lower()
    source_type = str(row.get('source_type') or row.get('source') or '').strip().lower()
    if role in {'assistant_generated', 'latest_generated', 'edited_output'} or source_type == 'generated':
        item = dict(row)
        item.pop('_kind', None)
        item['source_type'] = 'generated'
        item['source'] = 'generated'
        if not str(item.get('source_role') or '').strip():
            item['source_role'] = 'assistant_generated'
        return {'role': 'assistant', 'content': {'_kind': 'genfiles', 'files': [item]}}
    row['source_role'] = 'user_upload'
    row['source_type'] = 'upload'
    row['source'] = 'upload'
    return {'role': 'user', 'content': row}

def _merge_payload_file_attachments_into_messages(messages: list | None = None, payload: dict | None = None, *, source: str = '') -> list:
    msgs = [dict(m) if isinstance(m, dict) else m for m in (messages or [])]
    raw_items = _payload_file_attachment_items(payload or {})
    # If the frontend marks current-turn selections, never mix them with stale
    # session generated files. This keeps “这个怎么样” bound to the user's
    # selected/uploaded file, while still allowing explicit historical selection
    # through composer/file-library attachments.
    if any(_payload_file_attachment_is_current_turn(x) for x in raw_items):
        raw_items = [x for x in raw_items if _payload_file_attachment_is_current_turn(x)]
    existing_keys = set()
    existing_key_to_indexes: dict[str, list[int]] = {}
    existing_file_msgs = 0
    for i, m in enumerate(msgs):
        key = _message_file_attachment_key(m if isinstance(m, dict) else {})
        if key:
            existing_keys.add(key)
            existing_key_to_indexes.setdefault(key, []).append(i)
            existing_file_msgs += 1
        try:
            c = (m or {}).get('content') if isinstance(m, dict) else None
            if isinstance(c, dict) and str(c.get('_kind') or '') == 'genfiles':
                for gf in (c.get('files') or []):
                    if not isinstance(gf, dict):
                        continue
                    fake_content = {'_kind': 'file', **dict(gf)}
                    gkey = _message_file_attachment_key({'role': 'assistant', 'content': fake_content})
                    if gkey:
                        existing_keys.add(gkey)
                        existing_key_to_indexes.setdefault(gkey, []).append(i)
        except Exception:
            pass
    synthetic = []
    debug_files = []
    enriched_existing = 0
    for item in raw_items:
        content = _normalize_payload_file_attachment(item)
        if not content:
            continue
        key_msg = _payload_file_attachment_to_message(content)
        key = _message_file_attachment_key({'role': 'user', 'content': content})
        if key and key in existing_keys:
            updated = False
            for msg_idx in existing_key_to_indexes.get(key, []):
                old_msg = msgs[msg_idx] if isinstance(msgs[msg_idx], dict) else {}
                old_content = old_msg.get('content') if isinstance(old_msg, dict) else None
                if not (isinstance(old_content, dict) and old_content.get('_kind') == 'file'):
                    continue
                merged = _merge_file_attachment_content(old_content, content)
                if _file_attachment_content_richness(merged) > _file_attachment_content_richness(old_content):
                    new_msg = dict(old_msg)
                    new_msg['content'] = merged
                    msgs[msg_idx] = new_msg
                    updated = True
            if updated:
                enriched_existing += 1
            reg = content.get('file_registry') if isinstance(content.get('file_registry'), dict) else {}
            symbols = reg.get('symbols') if isinstance(reg.get('symbols'), list) else []
            debug_files.append({'filename': content.get('filename'), 'id': content.get('id'), 'source_role': content.get('source_role'), 'source_type': content.get('source_type') or content.get('source'), 'registry_id': reg.get('file_id'), 'ext': content.get('ext'), 'full': bool(reg.get('full_text_available') or reg.get('full_text_ref')), 'parsed_chars': reg.get('parsed_chars') or reg.get('full_text_chars'), 'symbols': len(symbols), 'sample': [str((s or {}).get('name') or '') for s in symbols[:10] if isinstance(s, dict)], 'merged_into_existing': bool(updated)})
            continue
        if key:
            existing_keys.add(key)
            existing_key_to_indexes.setdefault(key, [])
        synthetic.append(key_msg)
        reg = content.get('file_registry') if isinstance(content.get('file_registry'), dict) else {}
        symbols = reg.get('symbols') if isinstance(reg.get('symbols'), list) else []
        debug_files.append({'filename': content.get('filename'), 'id': content.get('id'), 'source_role': content.get('source_role'), 'source_type': content.get('source_type') or content.get('source'), 'registry_id': reg.get('file_id'), 'ext': content.get('ext'), 'full': bool(reg.get('full_text_available') or reg.get('full_text_ref')), 'parsed_chars': reg.get('parsed_chars') or reg.get('full_text_chars'), 'symbols': len(symbols), 'sample': [str((s or {}).get('name') or '') for s in symbols[:10] if isinstance(s, dict)], 'merged_into_existing': False})
    if synthetic:
        last_user_idx = _last_user_message_index(msgs)
        if last_user_idx >= 0:
            msgs = msgs[:last_user_idx] + synthetic + msgs[last_user_idx:]
        else:
            msgs.extend(synthetic)
    try:
        app_logger.warning('[FILE_ATTACHMENTS_MERGE] source=%s raw=%s existing=%s synthetic=%s enriched=%s out_file_msgs=%s files=%s', str(source or '')[:40], len(raw_items), existing_file_msgs, len(synthetic), enriched_existing, existing_file_msgs + len(synthetic), debug_files)
    except Exception:
        pass
    return msgs
