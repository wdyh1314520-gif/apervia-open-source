# Auto-split helper: unified file context resolver.
# Purpose: expose file lists and diff candidates from the centralized
# FileLineageRegistry. This module is now an adapter, not a second lineage
# implementation: role/family/parent/compare decisions live in
# file_lineage_registry_part.py.

from __future__ import annotations

import os
import re

FILE_CONTEXT_RESOLVER_VERSION = 'file_context_resolver_v3_lineage_registry_0606'

# Diff candidates are limited to formats FileDiffRouter can actually compare.
# Other files may still appear in the visible file list, but they will not be
# offered as automatic compare_pairs until a dedicated router supports them.
_FILE_CONTEXT_DIFFABLE_EXTS = {
    '.xlsx', '.xlsm', '.csv', '.tsv',
    '.txt', '.md', '.markdown', '.json', '.jsonl', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.env',
    '.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.html', '.htm', '.css', '.scss', '.less', '.vue', '.svelte',
    '.xml', '.svg', '.sql', '.sh', '.bash', '.zsh', '.fish', '.ps1', '.bat', '.cmd',
    '.java', '.go', '.rs', '.c', '.h', '.cpp', '.cc', '.cxx', '.hpp', '.cs', '.php', '.rb', '.swift', '.kt', '.kts',
    '.dockerfile', '.gitignore', '.gitattributes', '.editorconfig', '.properties', '.gradle', '.lock', '.patch', '.diff', '.log',
}


def _fcr_text(value, limit=1000) -> str:
    s = str(value or '').strip()
    return s if len(s) <= limit else s[:limit] + '…'


def _fcr_basename(value: str = '') -> str:
    try:
        return os.path.basename(str(value or '').strip().replace('\\', '/')).strip()
    except Exception:
        return str(value or '').strip()


def _fcr_ext(name: str = '') -> str:
    return os.path.splitext(_fcr_basename(name))[1].lower()


def file_context_normalized_family_name(name: str = '') -> str:
    """Compatibility wrapper. The canonical implementation is FileLineageRegistry."""
    fn = globals().get('file_lineage_normalized_family_name')
    if callable(fn):
        return str(fn(name) or '').strip()
    return os.path.splitext(_fcr_basename(name))[0].strip().lower()


def _fcr_history_records(messages=None) -> list[dict]:
    fn = globals().get('_collect_history_file_records')
    if callable(fn):
        try:
            rows, _heavy = fn(messages or [])
            return [dict(x) for x in (rows or []) if isinstance(x, dict)]
        except Exception:
            return []
    return []


def _fcr_sandbox_files(path: str = '', messages=None, *, max_files: int = 200, max_depth: int = 4) -> list[dict]:
    resolver = globals().get('_sandbox_resolve_path')
    display = globals().get('_sandbox_display_path')
    if not callable(resolver):
        return []
    try:
        base, _rel_base = resolver(path or '', messages or [], must_exist=True, for_dir=True)
    except Exception:
        return []
    try:
        max_files = max(1, min(int(max_files or 200), 1000))
    except Exception:
        max_files = 200
    try:
        max_depth = max(0, min(int(max_depth if max_depth is not None else 4), 12))
    except Exception:
        max_depth = 4
    deny = globals().get('SANDBOX_DENY_DIR_NAMES')
    deny = deny if isinstance(deny, set) else {'.git', '__pycache__', 'node_modules', 'venv', '.venv'}
    root_depth = str(base).rstrip(os.sep).count(os.sep)
    rows: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(base):
        depth = str(dirpath).rstrip(os.sep).count(os.sep) - root_depth
        dirnames[:] = [d for d in dirnames if d not in deny and not str(d).startswith('.cache')]
        if depth >= max_depth:
            dirnames[:] = []
        for filename in filenames:
            if len(rows) >= max_files:
                break
            abs_path = os.path.join(dirpath, filename)
            try:
                rel = display(abs_path, messages or []) if callable(display) else os.path.relpath(abs_path, base)
            except Exception:
                rel = abs_path
            try:
                size = int(os.path.getsize(abs_path))
            except Exception:
                size = 0
            rows.append({
                'filename': filename,
                'path': rel,
                'sandbox_path': rel,
                'source': 'sandbox',
                'source_role': 'sandbox_file',
                'size': size,
                'order': 100000 + len(rows),
            })
        if len(rows) >= max_files:
            break
    return rows


def _fcr_make_lineage_record(row: dict, *, source_hint: str = '', idx: int = 0) -> dict | None:
    maker = globals().get('file_lineage_make_record')
    if callable(maker):
        try:
            return maker(row or {}, source_hint=source_hint, idx=idx)
        except Exception:
            return None
    # Minimal fallback only for isolated unit loading; runtime should always use
    # FileLineageRegistry because app3.py loads it before this module.
    filename = _fcr_basename((row or {}).get('filename') or (row or {}).get('saved_filename') or (row or {}).get('path') or '')
    if not filename:
        return None
    path = str((row or {}).get('path') or (row or {}).get('sandbox_path') or filename).strip().replace('\\', '/')
    return {
        'file_id': str((row or {}).get('file_id') or (row or {}).get('registry_file_id') or '').strip(),
        'registry_file_id': str((row or {}).get('registry_file_id') or '').strip(),
        'filename': filename,
        'path': path,
        'ext': _fcr_ext(filename),
        'source': str((row or {}).get('source') or source_hint or 'unknown'),
        'source_role': str((row or {}).get('source_role') or ''),
        'role': 'file',
        'family': file_context_normalized_family_name(filename),
        'lineage_key': file_context_normalized_family_name(filename),
        'order': float(idx),
        'size': int((row or {}).get('size') or 0) if str((row or {}).get('size') or '').isdigit() else 0,
        'download_url': str((row or {}).get('download_url') or (row or {}).get('url') or ''),
        'record_key': path.lower(),
        'parent_file_ids': [], 'source_file_ids': [], 'compared_file_ids': [],
        'source_paths': [], 'compared_paths': [], 'basis_filename': '', 'compared_filenames': [],
        'lineage_strength': 'weak',
    }


def _fcr_score_record(row: dict, query: str = '') -> float:
    scorer = globals().get('file_lineage_score_record')
    if callable(scorer):
        try:
            return float(scorer(row, query))
        except Exception:
            return 0.0
    return 0.0


def file_context_resolve(query: str = '', messages=None, *, include_sandbox: bool = True, path: str = '', max_files: int = 200, max_candidates: int = 8) -> dict:
    """Return visible files plus diff candidates from the canonical lineage registry."""
    records: list[dict] = []
    seen: set[str] = set()

    def add(row: dict | None, source_hint: str = '', idx: int = 0):
        rec = _fcr_make_lineage_record(row or {}, source_hint=source_hint, idx=idx)
        if not rec:
            return
        key = str(rec.get('record_key') or rec.get('path') or rec.get('filename') or '').lower()
        if key in seen:
            return
        seen.add(key)
        records.append(rec)

    for idx, row in enumerate(_fcr_history_records(messages or [])):
        add(row, 'history', idx)
    if include_sandbox:
        for idx, row in enumerate(_fcr_sandbox_files(path=path, messages=messages or [], max_files=max_files)):
            add(row, 'sandbox', 100000 + idx)

    records.sort(key=lambda r: (_fcr_score_record(r, query), float(r.get('order') or 0.0)), reverse=True)
    visible = [r for r in records if str(r.get('role') or '') not in {'source_code', 'temp'}]

    compare_fn = globals().get('file_lineage_compare_candidates')
    if callable(compare_fn):
        try:
            candidates = compare_fn(visible, query=query, comparable_exts=_FILE_CONTEXT_DIFFABLE_EXTS, max_candidates=max_candidates)
        except Exception:
            candidates = []
    else:
        candidates = []

    try:
        limit = max(1, min(int(max_files or 80), 200))
    except Exception:
        limit = 80
    file_names = [str(r.get('filename') or '') for r in visible[:80] if str(r.get('filename') or '').strip()]
    return {
        'ok': True,
        '_kind': 'file_context',
        'version': FILE_CONTEXT_RESOLVER_VERSION,
        'query': _fcr_text(query, 300),
        'count': len(records),
        'visible_count': len(visible),
        'files': visible[:limit],
        'compare_candidates': candidates,
        'fileNames': file_names,
        'fileNameTotal': len(visible),
        'diffable_exts': sorted(_FILE_CONTEXT_DIFFABLE_EXTS),
        'instruction': 'Use compare_candidates for diff/compare requests. This resolver is backed by FileLineageRegistry; do not fall back to raw ls/find unless no relevant candidates exist.',
    }


def file_context_select_parent_for_output(target_filename: str = '', messages=None, query: str = '') -> dict:
    """Compatibility wrapper for generated artifact lineage selection."""
    ctx = file_context_resolve(query=query or target_filename, messages=messages or [], include_sandbox=False, max_files=160, max_candidates=8)
    rows = [r for r in (ctx.get('files') or []) if isinstance(r, dict)]
    selector = globals().get('file_lineage_select_parent_for_output')
    if callable(selector):
        try:
            return selector(target_filename, records=rows, query=query or target_filename)
        except Exception:
            pass
    family = file_context_normalized_family_name(target_filename)
    return {
        'version': FILE_CONTEXT_RESOLVER_VERSION,
        'target_filename': _fcr_basename(target_filename),
        'target_family': family,
        'basis_filename': '',
        'parent_file_ids': [],
        'source_file_ids': [],
        'parent_path': '',
        'source_paths': [],
        'lineage_key': family,
        'role': 'generated',
        'lineage_strength': 'weak',
    }


def _file_context_resolver_tool(args: dict | None = None, messages=None) -> dict:
    args = dict(args or {}) if isinstance(args, dict) else {}
    try:
        return file_context_resolve(
            query=str(args.get('query') or args.get('q') or ''),
            messages=messages or [],
            include_sandbox=bool(args.get('include_sandbox', True)),
            path=str(args.get('path') or ''),
            max_files=int(args.get('max_files') or 120),
            max_candidates=int(args.get('max_candidates') or 8),
        )
    except Exception as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}', '_kind': 'file_context'}


def file_context_policy_prompt() -> str:
    return (
        'FileContextResolver 是 FileLineageRegistry 的查询入口，统一管理当前轮上传、历史上传、生成产物和沙盒文件列表。'
        '用户要求 diff/对比/找新版旧版时，先用 sandbox_resolve_file_context 获取 compare_candidates；'
        '普通文本/代码/配置/数据文件也属于可对比文件，不要只把 diff 理解成 Office。不要让模型直接用 ls/find 扫 /mnt/data 作为主链路。文件列表展示应保留文件名、角色、血缘强度，不只显示 items 数量。'
    )
