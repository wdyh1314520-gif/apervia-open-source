# Split section: canonical activity event timeline helpers.
# Purpose: keep the side Activity panel on one backend event source.  Legacy
# progress_events stay as a compatibility alias; new code should write/read
# activity_events.

import hashlib
import re
import time

_ACTIVITY_EVENT_MAX_ROWS = 100
_ACTIVITY_EVENT_SOURCE_ITEMS_LIMIT = 200
_ACTIVITY_EVENT_SOURCE_PREVIEW_LIMIT = 12
_ACTIVITY_EVENT_IMAGE_ITEMS_LIMIT = 8
_ACTIVITY_EVENT_DOCUMENT_VISUAL_ITEMS_LIMIT = 12
_ACTIVITY_EVENT_STATES = {'active', 'done', 'warn', 'error'}


def _activity_event_now_ms() -> int:
    try:
        return int(time.time() * 1000)
    except Exception:
        return 0


def _activity_event_text(value, limit: int = 0) -> str:
    text = str(value if value is not None else '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if limit and len(text) > limit:
        text = text[: max(1, int(limit) - 1)].rstrip() + '…'
    return text


def _activity_event_first_text(src: dict, *keys: str, limit: int = 0) -> str:
    if not isinstance(src, dict):
        return ''
    for key in keys:
        value = src.get(key)
        if value is None:
            continue
        text = _activity_event_text(value, limit)
        if text:
            return text
    return ''


def _activity_event_set_aliases(row: dict, value: str, *keys: str) -> None:
    if not isinstance(row, dict):
        return
    text = str(value or '').strip()
    if not text:
        return
    for key in keys:
        if key:
            row[key] = text


def _activity_event_op(src: dict) -> str:
    return _activity_event_first_text(src if isinstance(src, dict) else {}, 'activity_op', 'activityOp', limit=80).lower()


def _activity_event_is_remove(src: dict) -> bool:
    if not isinstance(src, dict):
        return False
    op = _activity_event_op(src)
    return bool(src.get('remove') or src.get('removed') or src.get('clear') or src.get('cleared') or op in {'remove', 'clear'})


def _activity_event_public_file_label(value) -> str:
    raw = str(value if value is not None else '').replace('\\', '/').strip()
    if not raw:
        return ''
    raw = re.sub(r'[?#].*$', '', raw).rstrip('/')
    name = raw.split('/')[-1] if '/' in raw else raw
    name = str(name or '').strip()
    if not name or name in {'.', '..'}:
        return ''
    try:
        from urllib.parse import unquote
        name = unquote(name)
    except Exception:
        pass
    return name[:160]


def _activity_event_collect_file_names(*values, limit: int = 80):
    out = []
    seen = set()
    max_items = max(1, min(int(limit or 80), 200))

    def add(value):
        if value is None:
            return
        if isinstance(value, (list, tuple, set)):
            for child in value:
                add(child)
            return
        if isinstance(value, dict):
            for key in (
                'display_name', 'displayName', 'filename', 'target_filename', 'targetFilename',
                'source_filename', 'name', 'path', 'mount_path', 'url', 'href', 'current_file', 'currentFile'
            ):
                if value.get(key):
                    add(value.get(key))
            for key in (
                'fileNames', 'file_names', 'filenames', 'files_preview', 'file_preview', 'files', 'paths',
                'items', 'artifacts', 'delivery_files', 'published_paths', 'output_paths', 'created_paths',
                'changed_paths', 'compare_candidates', 'left', 'right', 'diffs', 'pair'
            ):
                if value.get(key):
                    add(value.get(key))
            return
        name = _activity_event_public_file_label(value)
        if not name:
            return
        key = name.lower()
        if key in seen:
            return
        seen.add(key)
        if len(out) < max_items:
            out.append(name)

    for value in values:
        add(value)
    return out, len(seen)


def _activity_event_image_items(item: dict, limit: int = _ACTIVITY_EVENT_IMAGE_ITEMS_LIMIT) -> list[dict]:
    """保留活动面板需要的轻量图片身份和预览引用，不复制图片正文。"""
    src = item if isinstance(item, dict) else {}
    raw_rows = None
    for key in ('image_items', 'imageItems', 'image_preview_items', 'imagePreviewItems'):
        if isinstance(src.get(key), list):
            raw_rows = src.get(key)
            break
    if raw_rows is None:
        raw_rows = []

    rows = []
    seen = set()
    max_items = max(1, min(int(limit or _ACTIVITY_EVENT_IMAGE_ITEMS_LIMIT), 16))
    aliases = {
        'image_id': ('image_id', 'imageId', 'stable_image_id', 'stableImageId', 'role_image_id', 'roleImageId'),
        'attachment_id': ('attachment_id', 'attachmentId'),
        'file_library_id': ('file_library_id', 'fileLibraryId', 'library_file_id', 'libraryFileId'),
        'storage_ref': ('storage_ref', 'storageRef'),
        'model_storage_ref': ('model_storage_ref', 'modelStorageRef'),
        'preview_url': ('preview_url', 'previewUrl', '_preview_url'),
        'view_url': ('view_url', 'viewUrl'),
        'url': ('url', 'image_url', 'imageUrl'),
        'filename': ('filename', 'name', 'title'),
        'source_role': ('source_role', 'sourceRole', 'role'),
    }

    for raw in raw_rows:
        source = {'image_id': raw} if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
        if not source:
            continue
        normalized = {}
        for target, source_keys in aliases.items():
            value = None
            for source_key in source_keys:
                candidate = source.get(source_key)
                if isinstance(candidate, dict):
                    candidate = candidate.get('url')
                if candidate is not None and str(candidate or '').strip():
                    value = candidate
                    break
            text = str(value or '').strip()
            if not text:
                continue
            # data/blob/local 引用既大又无法跨设备复用；活动事件只保存稳定引用。
            if target in {'preview_url', 'view_url', 'url'} and (text.startswith('data:') or text.startswith('blob:') or text.startswith('local://')):
                continue
            normalized[target] = text[:2000] if target.endswith('_url') or target == 'url' else text[:300]
        identity = str(
            normalized.get('image_id')
            or normalized.get('attachment_id')
            or normalized.get('file_library_id')
            or normalized.get('model_storage_ref')
            or normalized.get('storage_ref')
            or normalized.get('view_url')
            or normalized.get('preview_url')
            or normalized.get('url')
            or ''
        ).strip().lower()
        if not identity or identity in seen:
            continue
        seen.add(identity)
        rows.append(normalized)
        if len(rows) >= max_items:
            break
    return rows


def _activity_event_document_visual_items(item: dict, limit: int = _ACTIVITY_EVENT_DOCUMENT_VISUAL_ITEMS_LIMIT) -> list[dict]:
    """保留文档渲染页的轻量标签和受保护预览地址。"""
    src = item if isinstance(item, dict) else {}
    raw_rows = src.get('document_visual_items') if isinstance(src.get('document_visual_items'), list) else src.get('documentVisualItems')
    if not isinstance(raw_rows, list):
        return []
    out = []
    seen = set()
    max_items = max(1, min(int(limit or _ACTIVITY_EVENT_DOCUMENT_VISUAL_ITEMS_LIMIT), 24))
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        preview_url = str(raw.get('preview_url') or raw.get('previewUrl') or '').strip()
        if not preview_url.startswith('/api3/sandbox-visual-preview/'):
            continue
        try:
            page_number = max(0, int(raw.get('page_number') or raw.get('pageNumber') or 0))
        except Exception:
            page_number = 0
        label = _activity_event_text(raw.get('page_label') or raw.get('pageLabel') or raw.get('label') or (f'第 {page_number} 页' if page_number else ''), 100)
        key = f'{page_number}|{preview_url}'.lower()
        if key in seen:
            continue
        seen.add(key)
        row = {
            'preview_url': preview_url[:6000],
            'page_number': page_number,
            'page_label': label,
            'document_name': _activity_event_text(raw.get('document_name') or raw.get('documentName') or '', 180),
        }
        try:
            total_pages = max(0, int(raw.get('total_pages') or raw.get('totalPages') or 0))
        except Exception:
            total_pages = 0
        if total_pages:
            row['total_pages'] = total_pages
        if raw.get('visual_exec_id'):
            row['visual_exec_id'] = _activity_event_text(raw.get('visual_exec_id'), 80)
        out.append(row)
        if len(out) >= max_items:
            break
    return out


def _activity_event_stage(raw_stage: str = '', tool: str = '', panel_stage: str = '') -> str:
    stage = str(panel_stage or '').strip().lower()
    if stage in {'think', 'search', 'web', 'image', 'file', 'sandbox', 'tool', 'answer'}:
        return 'search' if stage == 'web' else stage
    raw = str(raw_stage or '').strip().lower()
    t = str(tool or '').strip().lower()
    if t == 'sandbox_run' or raw == 'sandbox_run' or raw.startswith('sandbox_run'):
        return 'sandbox'
    if raw.startswith('sandbox_') or t.startswith('sandbox_') or t == 'sandbox':
        if t in {'sandbox_read_file', 'sandbox_import_files', 'sandbox_write_file', 'sandbox_write_files', 'sandbox_replace_text', 'sandbox_create_office_file', 'sandbox_publish_files', 'sandbox_diff_files', 'sandbox_resolve_file_context', 'sandbox_list_files', 'sandbox_analyze_file_images'}:
            return 'file'
        return 'sandbox'
    if raw.startswith('file_') or 'read_file' in raw or t.startswith('file_'):
        return 'file'
    if 'web' in raw or 'search' in raw or t in {'web_search', 'fetch_url', 'fetch_urls', 'image_search', 'search_knowledge_base'}:
        return 'search'
    if t == 'analyze_existing_image' or raw.startswith('image_analysis'):
        return 'image'
    if t in {'get_weather', 'get_location', 'save_memory'}:
        return 'tool'
    return 'answer'


def _activity_event_state(item: dict) -> str:
    state = str((item or {}).get('state') or '').strip().lower()
    if state in _ACTIVITY_EVENT_STATES:
        return state
    status = str((item or {}).get('status') or '').strip().lower()
    if status in {'searched', 'completed', 'complete', 'done', 'success', 'succeeded'}:
        return 'done'
    if status in {'error', 'failed', 'failure'}:
        return 'error'
    if status in {'searching', 'running', 'in_progress', 'pending', 'queued', 'started', 'starting'}:
        return 'active'
    percent = None
    try:
        percent = float((item or {}).get('percent'))
    except Exception:
        percent = None
    text = str((item or {}).get('message') or (item or {}).get('title') or (item or {}).get('text') or '').lower()
    raw_stage = str((item or {}).get('raw_stage') or (item or {}).get('rawStage') or (item or {}).get('stage') or '').strip().lower()
    if raw_stage.endswith('_error') or raw_stage == 'error' or 'error' in text or '失败' in text or '错误' in text:
        return 'error'
    if percent is not None and percent >= 100:
        return 'done'
    if '完成' in text or '已' in text or 'done' in text or 'completed' in text:
        return 'done'
    return 'active'


def _activity_event_ts(item: dict) -> int:
    for key in ('ts', 'startedAt', 'started_at', 'createdAt', 'created_at', 'updatedAt', 'updated_at'):
        try:
            n = float((item or {}).get(key) or 0)
        except Exception:
            n = 0
        if n > 0:
            if n < 10000000000:
                n *= 1000
            return int(n)
    return _activity_event_now_ms()


def _activity_event_source_items(item: dict, limit: int = _ACTIVITY_EVENT_SOURCE_ITEMS_LIMIT) -> list[dict]:
    rows = []
    for key in ('source_preview', 'sourcePreview', 'source_items', 'sourceItems', 'search_results', 'searched_results', 'sources', 'results'):
        value = (item or {}).get(key)
        if isinstance(value, list):
            for row in value:
                if not isinstance(row, dict):
                    continue
                url = str(row.get('url') or row.get('link') or row.get('href') or row.get('uri') or '').strip()
                title = str(row.get('title') or row.get('name') or row.get('site_name') or row.get('source') or '').strip()
                snippet = str(row.get('snippet') or row.get('summary') or row.get('text') or '').strip()
                favicon = str(row.get('favicon') or row.get('favicon_url') or row.get('icon') or '').strip()
                host = str(row.get('host') or row.get('domain') or '').strip()
                if not (url or title or host):
                    continue
                rows.append({
                    **({'url': url} if url else {}),
                    **({'title': title[:180]} if title else {}),
                    **({'snippet': snippet[:280]} if snippet else {}),
                    **({'favicon': favicon} if favicon else {}),
                    **({'host': host[:120]} if host else {}),
                })
    out = []
    seen = set()
    for row in rows:
        sig = (str(row.get('url') or '') or str(row.get('host') or '') or str(row.get('title') or '')).lower()
        if sig and sig in seen:
            continue
        if sig:
            seen.add(sig)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _activity_event_source_preview(source_items: list[dict] | None, limit: int = _ACTIVITY_EVENT_SOURCE_PREVIEW_LIMIT) -> list[dict]:
    # Live Activity events must stay light: preview + total count, not every
    # search result on every SSE frame. Search/fetch/evidence can still keep
    # their original full data elsewhere.
    out = []
    seen = set()
    max_items = max(1, min(int(limit or _ACTIVITY_EVENT_SOURCE_PREVIEW_LIMIT), 32))
    for row in (source_items or []):
        if not isinstance(row, dict):
            continue
        url = str(row.get('url') or row.get('link') or row.get('href') or row.get('uri') or '').strip()
        host = str(row.get('host') or row.get('domain') or '').strip()
        title = str(row.get('title') or row.get('name') or row.get('site_name') or row.get('source') or '').strip()
        favicon = str(row.get('favicon') or row.get('favicon_url') or row.get('icon') or '').strip()
        sig = (url or host or title).lower()
        if not sig or sig in seen:
            continue
        seen.add(sig)
        item = {}
        if url:
            item['url'] = url[:500]
        if title:
            item['title'] = title[:120]
        if host:
            item['host'] = host[:100]
        if favicon:
            item['favicon'] = favicon[:500]
        out.append(item)
        if len(out) >= max_items:
            break
    return out


def _activity_event_key(item: dict, stage: str, raw_stage: str, tool: str, title: str, detail: str, command: str) -> str:
    operation_key = str((item or {}).get('operation_key') or (item or {}).get('operationKey') or '').strip()
    if tool == 'sandbox_run':
        if operation_key:
            return ('sandbox_run|' + operation_key)[:700]
        if command:
            try:
                h = hashlib.sha1(command.encode('utf-8', 'ignore')).hexdigest()[:16]
            except Exception:
                h = str(abs(hash(command)))[:16]
            return f'sandbox_run|{h}'[:700]
    raw_key = str((item or {}).get('key') or (item or {}).get('progress_key') or (item or {}).get('progressKey') or '').strip()
    if raw_key:
        # Old sandbox progress keys used a phase suffix, producing duplicate
        # start/done rows. Collapse them here; the row state updates in place.
        m = re.match(r'^(sandbox\|[^|]+\|[^|]+)\|(?:start|done|finish|end)$', raw_key, flags=re.I)
        if m:
            return m.group(1)[:700]
        return raw_key[:700]
    if raw_stage == 'web_query_group':
        round_no = str((item or {}).get('round') or '').strip()
        idx = str((item or {}).get('index') or '').strip()
        return f'web|query_group|{round_no}|{idx}|{"|".join(str(q) for q in ((item or {}).get("queries") or []))}'[:700]
    if tool:
        basis = command or str((item or {}).get('target_filename') or (item or {}).get('filename') or (item or {}).get('path') or detail or title)
        try:
            h = hashlib.sha1(basis.encode('utf-8', 'ignore')).hexdigest()[:16]
        except Exception:
            h = str(abs(hash(basis)))[:16]
        return f'{stage}|{tool}|{h}'[:700]
    return f'{stage}|{raw_stage}|{title}|{detail}'[:700]


def _activity_event_normalize(item: dict) -> dict:
    src = dict(item or {}) if isinstance(item, dict) else {}
    raw_stage = str(src.get('raw_stage') or src.get('rawStage') or src.get('stage') or src.get('kind') or src.get('type') or '').strip().lower()
    tool = str(src.get('tool') or src.get('tool_name') or src.get('name') or '').strip().lower()
    stage = _activity_event_stage(raw_stage, tool, str(src.get('panel_stage') or src.get('panelStage') or src.get('display_stage') or src.get('displayStage') or ''))
    state = _activity_event_state(src)
    title = _activity_event_text(src.get('title') or src.get('message') or src.get('text') or '处理中', 220)
    detail = _activity_event_text(src.get('detail') or src.get('description') or '', 600)
    queries = []
    qv = src.get('queries') if isinstance(src.get('queries'), list) else ([src.get('query') or src.get('search_query')] if (src.get('query') or src.get('search_query')) else [])
    for q in qv:
        text = _activity_event_text(q, 120)
        if text and text not in queries:
            queries.append(text)
    command = _activity_event_text(src.get('display_command') or src.get('displayCommand') or src.get('command') or src.get('list_command') or src.get('listCommand') or '', 0)
    stdout = _activity_event_text(src.get('stdout') or src.get('list_output') or src.get('listOutput') or '', 0)
    stderr = _activity_event_text(src.get('stderr') or '', 0)
    exit_code = src.get('exit_code') if src.get('exit_code') is not None else src.get('exitCode')
    file_names, file_total = _activity_event_collect_file_names(
        src.get('fileNames'), src.get('file_names'), src.get('filenames'), src.get('files_preview'), src.get('file_preview'),
        src.get('filename'), src.get('target_filename'), src.get('targetFilename'), src.get('current_file'), src.get('currentFile'),
        src.get('path'), src.get('paths'), src.get('files'), limit=80,
    )
    for count_key in ('fileNameTotal', 'file_name_total', 'fileNameCount', 'file_name_count', 'fileCount', 'file_count', 'total_count'):
        try:
            file_total = max(file_total, int(float(src.get(count_key) or 0)))
        except Exception:
            pass
    source_items_all = _activity_event_source_items(src, _ACTIVITY_EVENT_SOURCE_ITEMS_LIMIT)
    source_preview = _activity_event_source_preview(source_items_all, _ACTIVITY_EVENT_SOURCE_PREVIEW_LIMIT)
    image_items = _activity_event_image_items(src, _ACTIVITY_EVENT_IMAGE_ITEMS_LIMIT)
    image_count = len(image_items)
    for count_key in ('image_count', 'imageCount', 'analyzed_count', 'analyzedCount', 'visual_input_count', 'visualInputCount'):
        try:
            image_count = max(image_count, int(float(src.get(count_key) or 0)))
        except Exception:
            pass
    document_visual_items = _activity_event_document_visual_items(src, _ACTIVITY_EVENT_DOCUMENT_VISUAL_ITEMS_LIMIT)
    document_page_count = len(document_visual_items)
    for count_key in ('document_page_count', 'documentPageCount'):
        try:
            document_page_count = max(document_page_count, int(float(src.get(count_key) or 0)))
        except Exception:
            pass
    result_count = 0
    for count_key in ('result_count', 'resultCount', 'source_count', 'sourceCount', 'source_total', 'sourceTotal'):
        try:
            result_count = max(result_count, int(float(src.get(count_key) or 0)))
        except Exception:
            pass
    if source_items_all:
        result_count = max(result_count, len(source_items_all))
    key = _activity_event_key(src, stage, raw_stage, tool, title, detail, command)
    try:
        seq = int(float(src.get('seq') or src.get('order') or 0))
    except Exception:
        seq = 0
    debug_available = bool(command or stdout or stderr or exit_code is not None or src.get('debug_available') or src.get('debugAvailable'))
    show_debug = bool(src.get('show_debug') or src.get('showDebug') or (tool == 'sandbox_run' and debug_available) or state == 'error')
    started_ms = _activity_event_ts(src)
    updated_ms = _activity_event_ts({
        'ts': src.get('updatedAt') or src.get('updated_at') or src.get('finishedAt') or src.get('finished_at') or src.get('doneAt') or src.get('done_at') or 0
    }) if (src.get('updatedAt') or src.get('updated_at') or src.get('finishedAt') or src.get('finished_at') or src.get('doneAt') or src.get('done_at')) else _activity_event_now_ms()
    done_ms = 0
    if state in {'done', 'warn', 'error'}:
        done_ms = _activity_event_ts({
            'ts': src.get('doneAt') or src.get('done_at') or src.get('finishedAt') or src.get('finished_at') or src.get('completedAt') or src.get('completed_at') or updated_ms
        })
    summary = _activity_event_text(src.get('summary') or src.get('query_summary') or src.get('querySummary') or src.get('label') or '', 240)
    row = {
        'activity_event': True,
        'event_type': 'activity_event',
        'key': key,
        'title': title,
        'detail': detail,
        'queries': queries[:8],
        'summary': summary,
        'querySummary': summary,
        'stage': stage,
        'kind': stage,
        'state': state,
        'ts': started_ms,
        'started_at': started_ms,
        'startedAt': started_ms,
        'updated_at': updated_ms,
        'updatedAt': updated_ms,
        'text': _activity_event_text(src.get('text') or title, 260),
        'source': str(src.get('source') or '').strip()[:80],
    }
    session_id = _activity_event_first_text(src, 'session_id', 'sessionId', 'client_session_id', 'clientSessionId', limit=160)
    _activity_event_set_aliases(row, session_id, 'session_id', 'sessionId', 'client_session_id', 'clientSessionId')
    turn_id = _activity_event_first_text(src, 'activity_turn_id', 'activityTurnId', 'turn_id', 'turnId', limit=240)
    _activity_event_set_aliases(row, turn_id, 'activity_turn_id', 'activityTurnId')
    session_title = _activity_event_first_text(src, 'client_session_title', 'clientSessionTitle', 'session_title', 'sessionTitle', limit=240)
    _activity_event_set_aliases(row, session_title, 'client_session_title', 'clientSessionTitle')
    if done_ms:
        row['done_at'] = done_ms
        row['doneAt'] = done_ms
    if raw_stage:
        row['raw_stage'] = raw_stage[:120]
    if tool:
        row['tool'] = tool[:120]
    if seq > 0:
        row['seq'] = seq
    else:
        row['seq'] = 0
    try:
        percent = float(src.get('percent') or 0)
        if percent > 0:
            row['percent'] = max(0, min(100, percent))
    except Exception:
        pass
    if result_count:
        row['result_count'] = result_count
        row['resultCount'] = result_count
        row['source_total'] = result_count
        row['sourceTotal'] = result_count
    try:
        attempt = int(float(src.get('attempt') or 0))
    except Exception:
        attempt = 0
    try:
        attempt_total = int(float(src.get('attempt_total') or src.get('attemptTotal') or 0))
    except Exception:
        attempt_total = 0
    if attempt > 0:
        row['attempt'] = attempt
    if attempt_total > 0:
        row['attempt_total'] = attempt_total
        row['attemptTotal'] = attempt_total
    if source_preview:
        row['source_items'] = source_preview
        row['sourceItems'] = source_preview
        row['source_preview'] = source_preview
        row['sourcePreview'] = source_preview
    if image_items:
        row['image_items'] = image_items
        row['imageItems'] = image_items
    if image_count > 0:
        row['image_count'] = image_count
        row['imageCount'] = image_count
    if document_visual_items:
        row['document_visual_items'] = document_visual_items
        row['documentVisualItems'] = document_visual_items
    if document_page_count > 0:
        row['document_page_count'] = document_page_count
        row['documentPageCount'] = document_page_count
        document_visual_deferred = bool(src.get('document_visual_deferred') or src.get('documentVisualDeferred'))
        row['document_visual_deferred'] = document_visual_deferred
        row['documentVisualDeferred'] = document_visual_deferred
    if file_names:
        row['fileNames'] = file_names[:80]
        row['file_names'] = file_names[:80]
    if file_total > 0:
        row['fileNameTotal'] = int(max(file_total, len(file_names)))
        row['file_count'] = int(max(file_total, len(file_names)))
    for scalar_key in ('target_filename', 'filename', 'path', 'current_file', 'currentFile'):
        if src.get(scalar_key) is not None and str(src.get(scalar_key) or '').strip():
            row[scalar_key] = str(src.get(scalar_key) or '').strip()[:240]
    activity_op = _activity_event_op(src)
    _activity_event_set_aliases(row, activity_op, 'activity_op', 'activityOp')
    remove_event = _activity_event_is_remove(src)
    if remove_event:
        row['remove'] = True
        row['removed'] = True
    if src.get('action_type'):
        row['action_type'] = str(src.get('action_type') or '')[:80]
    if src.get('actionType'):
        row['actionType'] = str(src.get('actionType') or '')[:80]
    if src.get('operation_key'):
        row['operation_key'] = str(src.get('operation_key') or '')[:160]
    if src.get('operationKey'):
        row['operationKey'] = str(src.get('operationKey') or '')[:160]
    if src.get('command_language'):
        row['command_language'] = str(src.get('command_language') or '')[:40]
    if src.get('commandLanguage'):
        row['commandLanguage'] = str(src.get('commandLanguage') or '')[:40]
    row['debug_available'] = bool(debug_available)
    row['debugAvailable'] = bool(debug_available)
    row['show_debug'] = bool(show_debug)
    row['showDebug'] = bool(show_debug)
    if tool in {'sandbox_run', 'sandbox_list_files'}:
        if command:
            row['command'] = command
        if stdout:
            row['stdout'] = stdout
        if stderr:
            row['stderr'] = stderr
        if exit_code is not None:
            row['exit_code'] = exit_code
            row['exitCode'] = exit_code
    return row


def _activity_event_row_tool(row: dict | None) -> str:
    if not isinstance(row, dict):
        return ''
    return str(row.get('tool') or row.get('tool_name') or row.get('name') or '').strip().lower()


def _activity_event_row_command(row: dict | None) -> str:
    if not isinstance(row, dict):
        return ''
    return str(row.get('display_command') or row.get('displayCommand') or row.get('command') or '').strip()


def _activity_event_same_sandbox_run(old_row: dict | None, row: dict | None) -> bool:
    old_cmd = _activity_event_row_command(old_row)
    new_cmd = _activity_event_row_command(row)
    if old_cmd and new_cmd and old_cmd != new_cmd:
        return False
    old_op = str((old_row or {}).get('operation_key') or (old_row or {}).get('operationKey') or '').strip()
    new_op = str((row or {}).get('operation_key') or (row or {}).get('operationKey') or '').strip()
    if old_op and new_op:
        return old_op == new_op
    return bool(old_cmd and (not new_cmd or old_cmd == new_cmd))


def _activity_event_merge_rows(old_row: dict, row: dict) -> dict:
    merged = {**old_row, **row}
    tool = _activity_event_row_tool(row) or _activity_event_row_tool(old_row)
    has_debug = any(k in old_row or k in row for k in ('command', 'stdout', 'stderr', 'exit_code', 'exitCode'))
    if tool != 'sandbox_run' and not has_debug:
        return merged
    same_run = _activity_event_same_sandbox_run(old_row, row)
    for key in ('command', 'stdout', 'stderr'):
        if key in row:
            merged[key] = row.get(key) or ''
        elif same_run and key in old_row:
            merged[key] = old_row.get(key) or ''
        else:
            merged.pop(key, None)
    if 'exit_code' in row or 'exitCode' in row:
        if 'exit_code' in row:
            merged['exit_code'] = row.get('exit_code')
        if 'exitCode' in row:
            merged['exitCode'] = row.get('exitCode')
    elif same_run:
        if 'exit_code' in old_row:
            merged['exit_code'] = old_row.get('exit_code')
        if 'exitCode' in old_row:
            merged['exitCode'] = old_row.get('exitCode')
    else:
        merged.pop('exit_code', None)
        merged.pop('exitCode', None)
    return merged


def _activity_event_upsert_state(state: dict | None, item: dict | None) -> dict:
    if not isinstance(state, dict) or not isinstance(item, dict):
        return {}
    row = _activity_event_normalize(item)
    if not row.get('title') and not row.get('command'):
        return {}
    rows = state.setdefault('activity_events', [])
    if not isinstance(rows, list):
        rows = []
        state['activity_events'] = rows
    key = str(row.get('key') or '').strip()
    if not key:
        return {}
    try:
        next_seq = int(state.get('_activity_event_seq') or 0) + 1
    except Exception:
        next_seq = len(rows) + 1
    old_index = None
    old_row = None
    for idx, old in enumerate(rows):
        if isinstance(old, dict) and str(old.get('key') or '').strip() == key:
            old_index = idx
            old_row = old
            break
    if old_row is not None:
        try:
            row['seq'] = int(old_row.get('seq') or row.get('seq') or 0) or next_seq
        except Exception:
            row['seq'] = next_seq
        started_ts = int(float(old_row.get('ts') or old_row.get('startedAt') or old_row.get('started_at') or row.get('ts') or _activity_event_now_ms()))
        row['ts'] = started_ts
        row['started_at'] = started_ts
        row['startedAt'] = started_ts
        try:
            row['updated_at'] = max(int(float(old_row.get('updatedAt') or old_row.get('updated_at') or started_ts)), int(float(row.get('updatedAt') or row.get('updated_at') or _activity_event_now_ms())))
        except Exception:
            row['updated_at'] = _activity_event_now_ms()
        row['updatedAt'] = row['updated_at']
        if str(row.get('state') or '').lower() in {'done', 'warn', 'error'} and not row.get('doneAt') and not row.get('done_at'):
            row['done_at'] = row['updated_at']
            row['doneAt'] = row['updated_at']
        if bool(row.get('remove') or row.get('removed')):
            public_row = dict(row)
            try:
                del rows[old_index]
            except Exception:
                rows[:] = [x for x in rows if not (isinstance(x, dict) and str(x.get('key') or '').strip() == key)]
            state['progress_events'] = rows
            state['_last_activity_event'] = _activity_event_public_row(public_row)
            return state['_last_activity_event']
        rows[old_index] = _activity_event_merge_rows(old_row, row)
        public_row = dict(rows[old_index])
    else:
        if not int(row.get('seq') or 0):
            row['seq'] = next_seq
        if bool(row.get('remove') or row.get('removed')):
            state['progress_events'] = rows
            state['_last_activity_event'] = _activity_event_public_row(row)
            return state['_last_activity_event']
        rows.append(row)
        public_row = dict(row)
    try:
        state['_activity_event_seq'] = max(int(state.get('_activity_event_seq') or 0), int(public_row.get('seq') or 0))
    except Exception:
        state['_activity_event_seq'] = next_seq
    if len(rows) > _ACTIVITY_EVENT_MAX_ROWS:
        del rows[:-_ACTIVITY_EVENT_MAX_ROWS]
    # Legacy compatibility only: same list object, no second writer.
    state['progress_events'] = rows
    state['_last_activity_event'] = _activity_event_public_row(public_row)
    return state['_last_activity_event']


def _activity_event_public_row(row: dict | None) -> dict:
    if not isinstance(row, dict):
        return {}
    out = {}
    for key, value in row.items():
        if str(key).startswith('_'):
            continue
        if key in {'source_items_full', 'sourceItemsFull', 'full_source_items', 'fullSourceItems'}:
            continue
        out[key] = value
    preview = _activity_event_source_preview(
        out.get('source_preview') or out.get('sourcePreview') or out.get('source_items') or out.get('sourceItems') or [],
        _ACTIVITY_EVENT_SOURCE_PREVIEW_LIMIT,
    )
    if preview:
        out['source_items'] = preview
        out['sourceItems'] = preview
        out['source_preview'] = preview
        out['sourcePreview'] = preview
    else:
        for key in ('source_items', 'sourceItems', 'source_preview', 'sourcePreview'):
            out.pop(key, None)
    try:
        total = int(float(out.get('source_total') or out.get('sourceTotal') or out.get('result_count') or out.get('resultCount') or len(preview) or 0))
    except Exception:
        total = len(preview)
    if total > 0:
        total = max(total, len(preview))
        out['source_total'] = total
        out['sourceTotal'] = total
    return out


def _activity_events_public(state: dict | None) -> list[dict]:
    if not isinstance(state, dict):
        return []
    rows = state.get('activity_events') if isinstance(state.get('activity_events'), list) else state.get('progress_events')
    if not isinstance(rows, list):
        return []
    return [_activity_event_public_row(x) for x in rows if isinstance(x, dict)][-_ACTIVITY_EVENT_MAX_ROWS:]


def _activity_events_meta(state: dict | None, *, include_legacy: bool = True) -> dict:
    rows = _activity_events_public(state)
    if not rows:
        return {}
    out = {'activity_events': rows}
    if include_legacy:
        out['progress_events'] = rows
    return out
