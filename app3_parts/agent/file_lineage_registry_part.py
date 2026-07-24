# Centralized file lineage registry.
# Purpose: one source of truth for file role, family, parent/source/diff lineage.
# Old edit_audit/edited_from/history helpers are normalized here instead of
# keeping separate weak lineage heuristics in multiple modules.

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, asdict

FILE_LINEAGE_REGISTRY_VERSION = 'file_lineage_registry_v1_strong_0606'

_FILE_LINEAGE_DIFF_RE = re.compile(r'(diff|差异|对比|比较|compare|comparison|变更|修改点)', re.I)
_FILE_LINEAGE_GENERATED_RE = re.compile(r'(完善版|增强版|新版|最终版|整理版|修改版|改进版|优化版|enhanced|improved|updated|final|revised|v\d+|version)', re.I)
_FILE_LINEAGE_TEMP_RE = re.compile(r'(^~\$|\.tmp$|\.temp$|__pycache__|\.cache|_webai_tasks/)', re.I)
_FILE_LINEAGE_SOURCE_RE = re.compile(r'(^|/)(app3\.py|app3_parts/|static/|templates/|docker/|\.git/|node_modules/|venv/|\.venv/)', re.I)


def _flr_text(value, limit=1000) -> str:
    s = '' if value is None else str(value)
    s = s.strip()
    return s if len(s) <= limit else s[:limit] + '…'


def _flr_base(value: str = '') -> str:
    try:
        return os.path.basename(str(value or '').strip().replace('\\', '/')).strip()
    except Exception:
        return str(value or '').strip()


def _flr_path(value: str = '') -> str:
    return str(value or '').strip().replace('\\', '/')


def file_lineage_ext(name: str = '') -> str:
    return os.path.splitext(_flr_base(name))[1].lower()


def file_lineage_stem(name: str = '') -> str:
    return os.path.splitext(_flr_base(name))[0].strip()


def file_lineage_normalized_family_name(name: str = '') -> str:
    base = file_lineage_stem(name).lower()
    base = re.sub(r'\s+', ' ', base).strip()
    patterns = [
        r'[_\-\s]*(?:diff|差异|对比|比较|comparison|compare|变更|修改点)(?:表|清单|结果|报告|patch)?$',
        r'[_\-\s]*(?:完善版|增强版|新版|最终版|整理版|修改版|改进版|优化版)$',
        r'[_\-\s]*(?:enhanced|improved|updated|final|revised)$',
        r'[_\-\s]*(?:v|version)[_\-\s]*\d+$',
        r'[_\-\s]*\(\d+\)$',
        r'[_\-\s]*copy$',
    ]
    changed = True
    while changed:
        changed = False
        for pat in patterns:
            nb = re.sub(pat, '', base, flags=re.I).strip(' _-')
            if nb and nb != base:
                base = nb
                changed = True
    return base or file_lineage_stem(name).lower()


def _flr_unique(values, limit=40) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        if isinstance(value, dict):
            for key in ('file_id', 'registry_file_id', 'id', 'path', 'filename', 'saved_filename'):
                v = str(value.get(key) or '').strip()
                if v:
                    break
            else:
                v = ''
        else:
            v = str(value or '').strip()
        if not v:
            continue
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
        if len(out) >= limit:
            break
    return out


def file_lineage_record_key(row: dict | None = None) -> str:
    r = dict(row or {})
    for key in ('registry_file_id', 'file_id', 'id'):
        v = str(r.get(key) or '').strip()
        if v:
            return f'id:{v.lower()}'
    for key in ('path', 'sandbox_path', 'output_filename', 'saved_filename'):
        v = _flr_path(r.get(key) or '')
        if v:
            return f'path:{v.lower()}'
    url = str(r.get('download_url') or r.get('url') or r.get('view_url') or '').strip()
    name = _flr_base(r.get('filename') or r.get('saved_filename') or '')
    source = str(r.get('source') or r.get('namespace') or '').strip().lower()
    if name or url:
        return f'{source}|{name.lower()}|{url.lower()}'
    return f'anon:{time.time_ns()}'


def _flr_collect_audits(row: dict | None = None) -> list[dict]:
    r = dict(row or {})
    audits: list[dict] = []

    def add(obj):
        if isinstance(obj, dict) and obj:
            audits.append(dict(obj))

    add(r.get('edit_audit'))
    add(r.get('file_edit_audit'))
    details = r.get('edit_details') if isinstance(r.get('edit_details'), dict) else {}
    add(details.get('audit') if isinstance(details, dict) else None)
    for key in ('edit_audits', 'file_edit_audits'):
        if isinstance(r.get(key), list):
            for item in r.get(key) or []:
                add(item)
    return audits


def _flr_first(*values) -> str:
    for value in values:
        if isinstance(value, (list, tuple)):
            for item in value:
                s = str(item or '').strip()
                if s:
                    return s
        else:
            s = str(value or '').strip()
            if s:
                return s
    return ''


def file_lineage_extract(row: dict | None = None, *, path: str = '', filename: str = '') -> dict:
    r = dict(row or {})
    name = _flr_base(filename or r.get('filename') or r.get('saved_filename') or r.get('path') or r.get('sandbox_path') or path)
    rel = _flr_path(path or r.get('path') or r.get('sandbox_path') or r.get('output_filename') or r.get('saved_filename') or name)
    audits = _flr_collect_audits(r)
    edited_from = r.get('edited_from') if isinstance(r.get('edited_from'), dict) else {}
    src_role = str(r.get('source_role') or '').strip().lower()
    source = str(r.get('source') or r.get('namespace') or '').strip().lower()

    parent_ids: list[str] = []
    source_ids: list[str] = []
    compared_ids: list[str] = []
    source_paths: list[str] = []
    compared_paths: list[str] = []
    basis_names: list[str] = []
    compared_names: list[str] = []
    lineage_key = ''
    explicit_role = ''

    for audit in audits:
        lineage_key = lineage_key or str(audit.get('lineage_key') or '').strip()
        explicit_role = explicit_role or str(audit.get('file_role') or audit.get('role') or '').strip().lower()
        parent_ids.extend(audit.get('parent_file_ids') or []) if isinstance(audit.get('parent_file_ids'), list) else None
        source_ids.extend(audit.get('source_file_ids') or []) if isinstance(audit.get('source_file_ids'), list) else None
        compared_ids.extend(audit.get('compared_file_ids') or []) if isinstance(audit.get('compared_file_ids'), list) else None
        source_paths.extend(audit.get('source_paths') or []) if isinstance(audit.get('source_paths'), list) else None
        compared_paths.extend(audit.get('compared_paths') or []) if isinstance(audit.get('compared_paths'), list) else None
        for key in ('basis_filename', 'source_filename', 'original_filename', 'target_filename'):
            if str(audit.get(key) or '').strip():
                basis_names.append(str(audit.get(key) or '').strip())
        if str(audit.get('compared_filenames') or '').strip():
            compared_names.append(str(audit.get('compared_filenames') or '').strip())
        if isinstance(audit.get('compared_filenames'), list):
            compared_names.extend(audit.get('compared_filenames') or [])
        basis_files = audit.get('basis_files') if isinstance(audit.get('basis_files'), list) else []
        for item in basis_files:
            if isinstance(item, dict):
                if str(item.get('file_id') or item.get('registry_file_id') or '').strip():
                    source_ids.append(str(item.get('file_id') or item.get('registry_file_id') or '').strip())
                if str(item.get('path') or item.get('sandbox_path') or '').strip():
                    source_paths.append(str(item.get('path') or item.get('sandbox_path') or '').strip())
                basis_names.append(_flr_first(item.get('basis_filename'), item.get('source_filename'), item.get('filename')))

    for key in ('parent_file_ids', 'source_file_ids', 'compared_file_ids'):
        vals = r.get(key)
        if isinstance(vals, list):
            if key == 'parent_file_ids': parent_ids.extend(vals)
            elif key == 'source_file_ids': source_ids.extend(vals)
            else: compared_ids.extend(vals)
    if edited_from:
        for key in ('file_id', 'registry_file_id', 'id'):
            if str(edited_from.get(key) or '').strip():
                parent_ids.append(str(edited_from.get(key) or '').strip())
        for key in ('path', 'sandbox_path', 'saved_filename'):
            if str(edited_from.get(key) or '').strip():
                source_paths.append(str(edited_from.get(key) or '').strip())
        for key in ('filename', 'saved_filename'):
            if str(edited_from.get(key) or '').strip():
                basis_names.append(str(edited_from.get(key) or '').strip())
        lineage_key = lineage_key or str(edited_from.get('lineage_key') or '').strip()

    if not lineage_key:
        lineage_key = file_lineage_normalized_family_name(_flr_first(basis_names, name))
    family = file_lineage_normalized_family_name(lineage_key or name)
    if family and (not lineage_key or lineage_key == name):
        lineage_key = family

    role = explicit_role
    haystack = f'{name} {rel}'.strip()
    if not role:
        if _FILE_LINEAGE_TEMP_RE.search(haystack):
            role = 'temp'
        elif _FILE_LINEAGE_SOURCE_RE.search(haystack):
            role = 'source_code'
        elif compared_ids or compared_paths or _FILE_LINEAGE_DIFF_RE.search(name):
            role = 'diff'
        elif src_role in {'user_upload', 'upload', 'uploaded', 'original', 'user'} or source in {'upload', 'uploads'}:
            role = 'original'
        elif src_role in {'edited_output', 'assistant_edited', 'edited'} or parent_ids or source_ids or edited_from:
            role = 'enhanced'
        elif src_role in {'assistant_generated', 'latest_generated', 'generated', 'assistant_file', 'assistant'} or source == 'generated':
            role = 'enhanced' if _FILE_LINEAGE_GENERATED_RE.search(name) else 'generated'
        elif _FILE_LINEAGE_GENERATED_RE.search(name):
            role = 'enhanced'
        else:
            role = 'file'

    basis_filename = _flr_base(_flr_first(basis_names))
    if not basis_filename and parent_ids:
        basis_filename = ''
    compared_filenames = [_flr_base(x) for x in _flr_unique(compared_names, limit=20) if _flr_base(x)]

    return {
        'version': FILE_LINEAGE_REGISTRY_VERSION,
        'record_key': file_lineage_record_key(r),
        'role': role,
        'family': family,
        'lineage_key': lineage_key or family,
        'basis_filename': basis_filename,
        'parent_file_ids': _flr_unique(parent_ids, limit=20),
        'source_file_ids': _flr_unique(source_ids or parent_ids, limit=20),
        'compared_file_ids': _flr_unique(compared_ids, limit=20),
        'source_paths': _flr_unique(source_paths, limit=20),
        'compared_paths': _flr_unique(compared_paths, limit=20),
        'compared_filenames': compared_filenames,
        'has_strong_parent': bool(parent_ids or source_ids or source_paths or basis_filename),
        'has_strong_compare': bool(compared_ids or compared_paths or compared_filenames),
    }


@dataclass(frozen=True)
class FileLineageRecord:
    file_id: str
    filename: str
    path: str
    ext: str
    source: str
    role: str
    family: str
    lineage_key: str
    order: float
    size: int = 0
    download_url: str = ''
    registry_file_id: str = ''
    source_role: str = ''
    record_key: str = ''
    parent_file_ids: tuple[str, ...] = ()
    source_file_ids: tuple[str, ...] = ()
    compared_file_ids: tuple[str, ...] = ()
    source_paths: tuple[str, ...] = ()
    compared_paths: tuple[str, ...] = ()
    basis_filename: str = ''
    compared_filenames: tuple[str, ...] = ()
    lineage_strength: str = 'weak'

    def to_dict(self) -> dict:
        row = asdict(self)
        for key in ('parent_file_ids', 'source_file_ids', 'compared_file_ids', 'source_paths', 'compared_paths', 'compared_filenames'):
            row[key] = list(row.get(key) or [])
        return row


def file_lineage_make_record(row: dict | None = None, *, source_hint: str = '', idx: int = 0) -> dict | None:
    r = dict(row or {})
    filename = _flr_base(r.get('filename') or r.get('saved_filename') or r.get('path') or r.get('sandbox_path') or '')
    path = _flr_path(r.get('path') or r.get('sandbox_path') or r.get('output_filename') or r.get('saved_filename') or '')
    if not filename and path:
        filename = _flr_base(path)
    if not filename:
        return None
    lineage = file_lineage_extract(r, path=path, filename=filename)
    try:
        order = float(r.get('order') or r.get('created_at_ts') or idx)
    except Exception:
        order = float(idx)
    try:
        size = int(r.get('size') or 0)
    except Exception:
        size = 0
    file_id = _flr_text(r.get('file_id') or r.get('registry_file_id') or r.get('id') or '', 160)
    registry_file_id = _flr_text(r.get('registry_file_id') or '', 160)
    rec = FileLineageRecord(
        file_id=file_id,
        registry_file_id=registry_file_id,
        filename=filename,
        path=path or filename,
        ext=file_lineage_ext(filename),
        source=_flr_text(r.get('source') or source_hint or 'unknown', 80),
        source_role=_flr_text(r.get('source_role') or '', 80),
        role=str(lineage.get('role') or 'file'),
        family=str(lineage.get('family') or file_lineage_normalized_family_name(filename)),
        lineage_key=str(lineage.get('lineage_key') or lineage.get('family') or file_lineage_normalized_family_name(filename)),
        order=order,
        size=size,
        download_url=_flr_text(r.get('download_url') or r.get('url') or '', 500),
        record_key=str(lineage.get('record_key') or file_lineage_record_key(r)),
        parent_file_ids=tuple(lineage.get('parent_file_ids') or []),
        source_file_ids=tuple(lineage.get('source_file_ids') or []),
        compared_file_ids=tuple(lineage.get('compared_file_ids') or []),
        source_paths=tuple(lineage.get('source_paths') or []),
        compared_paths=tuple(lineage.get('compared_paths') or []),
        basis_filename=str(lineage.get('basis_filename') or ''),
        compared_filenames=tuple(lineage.get('compared_filenames') or []),
        lineage_strength='strong' if (lineage.get('has_strong_parent') or lineage.get('has_strong_compare')) else 'weak',
    )
    return rec.to_dict()


def _flr_identity_aliases(row: dict | None = None) -> set[str]:
    r = dict(row or {})
    aliases: set[str] = set()
    for key in ('record_key', 'file_id', 'registry_file_id'):
        v = str(r.get(key) or '').strip().lower()
        if v:
            aliases.add(v)
            if key in {'file_id', 'registry_file_id'}:
                aliases.add('id:' + v)
    for key in ('path', 'filename', 'basis_filename'):
        v = str(r.get(key) or '').strip().replace('\\', '/').lower()
        if v:
            aliases.add(v)
            aliases.add(_flr_base(v).lower())
            aliases.add('path:' + v)
    return {x for x in aliases if x}


def _flr_find_by_refs(records: list[dict], refs: list[str]) -> list[dict]:
    if not refs:
        return []
    refset = {str(x or '').strip().replace('\\', '/').lower() for x in refs if str(x or '').strip()}
    out = []
    seen = set()
    for row in records:
        aliases = _flr_identity_aliases(row)
        if aliases.intersection(refset) or aliases.intersection({'id:' + x for x in refset}):
            key = str(row.get('record_key') or row.get('path') or row.get('filename') or '').lower()
            if key not in seen:
                seen.add(key)
                out.append(row)
    return out


def file_lineage_score_record(row: dict, query: str = '') -> float:
    q = str(query or '').lower()
    raw = re.split(r'[^0-9a-zA-Z_\u4e00-\u9fff]+', q)
    toks = {x for x in raw if len(x) >= 2}
    text = ' '.join(str(row.get(k) or '') for k in ('filename', 'path', 'family', 'lineage_key', 'role')).lower()
    score = 0.0
    for tok in toks:
        if tok in text:
            score += 3.0 if tok in str(row.get('filename') or '').lower() else 1.2
    role = str(row.get('role') or '')
    if role in {'original', 'enhanced', 'generated', 'diff'}:
        score += 1.0
    if row.get('lineage_strength') == 'strong':
        score += 2.0
    try:
        score += min(float(row.get('order') or 0) / 100000.0, 0.5)
    except Exception:
        pass
    return score


def file_lineage_compare_candidates(records: list[dict], query: str = '', *, comparable_exts: set[str] | None = None, max_candidates: int = 8) -> list[dict]:
    rows = [dict(r) for r in (records or []) if isinstance(r, dict)]
    allowed_exts = set(comparable_exts or [])
    if allowed_exts:
        rows = [r for r in rows if str(r.get('ext') or '').lower() in allowed_exts]
    rows = [r for r in rows if str(r.get('role') or '') not in {'temp', 'source_code'}]
    out: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    def add_candidate(left: dict | None, right: dict | None, *, reason: str, diffs: list[dict] | None = None, base_score: float = 0.0):
        if not left or not right:
            return
        if str(left.get('path') or left.get('filename') or '') == str(right.get('path') or right.get('filename') or ''):
            return
        lkey = str(left.get('record_key') or left.get('path') or left.get('filename') or '').lower()
        rkey = str(right.get('record_key') or right.get('path') or right.get('filename') or '').lower()
        if not lkey or not rkey or (lkey, rkey) in seen_pairs:
            return
        seen_pairs.add((lkey, rkey))
        score = base_score + file_lineage_score_record(left, query) + file_lineage_score_record(right, query)
        if reason.startswith('strong_'):
            score += 8.0
        if _FILE_LINEAGE_DIFF_RE.search(str(query or '')):
            score += 2.0
        out.append({
            'family': str(right.get('lineage_key') or right.get('family') or left.get('lineage_key') or left.get('family') or ''),
            'ext': str(right.get('ext') or left.get('ext') or ''),
            'score': round(score, 3),
            'left': left,
            'right': right,
            'diffs': (diffs or [])[:4],
            'reason': reason,
        })

    # Strong parent links: generated/enhanced/diff result explicitly names source.
    for row in rows:
        role = str(row.get('role') or '')
        if role in {'enhanced', 'generated'}:
            parents = _flr_find_by_refs(rows, list(row.get('parent_file_ids') or []) + list(row.get('source_file_ids') or []) + list(row.get('source_paths') or []) + ([row.get('basis_filename')] if row.get('basis_filename') else []))
            for parent in parents[:3]:
                if str(parent.get('role') or '') != 'diff':
                    add_candidate(parent, row, reason='strong_parent_file_ids', base_score=12.0)
        if role == 'diff':
            compared = _flr_find_by_refs(rows, list(row.get('compared_file_ids') or []) + list(row.get('compared_paths') or []) + list(row.get('compared_filenames') or []))
            if len(compared) >= 2:
                comp_sorted = sorted(compared, key=lambda r: float(r.get('order') or 0))
                add_candidate(comp_sorted[0], comp_sorted[-1], reason='strong_compared_file_ids', diffs=[row], base_score=14.0)

    # Weak family fallback after strong relations. This keeps old filename/audit grouping as fallback only.
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = (str(row.get('lineage_key') or row.get('family') or '').lower(), str(row.get('ext') or '').lower())
        if key[0]:
            groups.setdefault(key, []).append(row)
    for (family, ext), group_rows in groups.items():
        group_rows = sorted(group_rows, key=lambda r: (float(r.get('order') or 0), file_lineage_score_record(r, query)), reverse=True)
        diffs = [r for r in group_rows if str(r.get('role') or '') == 'diff']
        originals = [r for r in group_rows if str(r.get('role') or '') == 'original']
        generated = [r for r in group_rows if str(r.get('role') or '') in {'enhanced', 'generated'}]
        fallback = [r for r in group_rows if r not in originals and r not in generated and r not in diffs]
        left = originals[-1] if len(originals) > 1 else (originals[0] if originals else None)
        right = generated[0] if generated else (fallback[0] if len(fallback) >= 2 else None)
        if not left and len(group_rows) >= 2:
            non_diff = [r for r in group_rows if str(r.get('role') or '') != 'diff']
            if len(non_diff) >= 2:
                left = sorted(non_diff, key=lambda r: float(r.get('order') or 0))[0]
                right = sorted(non_diff, key=lambda r: float(r.get('order') or 0), reverse=True)[0]
        add_candidate(left, right, reason='weak_family_fallback', diffs=diffs, base_score=2.0)

    out.sort(key=lambda c: float(c.get('score') or 0.0), reverse=True)
    return out[:max(1, int(max_candidates or 8))]


def file_lineage_select_parent_for_output(target_filename: str = '', records: list[dict] | None = None, query: str = '') -> dict:
    family = file_lineage_normalized_family_name(target_filename)
    ext = file_lineage_ext(target_filename)
    rows = [dict(r) for r in (records or []) if isinstance(r, dict)]
    matches = []
    for r in rows:
        role = str(r.get('role') or '')
        if role in {'source_code', 'temp', 'diff'}:
            continue
        if ext and str(r.get('ext') or '') and str(r.get('ext') or '') != ext:
            continue
        if str(r.get('lineage_key') or r.get('family') or '').lower() == family.lower() and _flr_base(r.get('filename') or '') != _flr_base(target_filename):
            matches.append(r)
    matches.sort(key=lambda r: (1 if str(r.get('role') or '') == 'original' else 0, 1 if r.get('lineage_strength') == 'strong' else 0, float(r.get('order') or 0)), reverse=True)
    parent = matches[0] if matches else {}
    fid = str(parent.get('file_id') or parent.get('registry_file_id') or parent.get('record_key') or '').strip() if parent else ''
    return {
        'version': FILE_LINEAGE_REGISTRY_VERSION,
        'target_filename': _flr_base(target_filename),
        'target_family': family,
        'basis_filename': str(parent.get('filename') or '') if parent else '',
        'parent_file_ids': [fid] if fid else [],
        'source_file_ids': [fid] if fid else [],
        'parent_path': str(parent.get('path') or '') if parent else '',
        'source_paths': [str(parent.get('path') or '')] if parent and parent.get('path') else [],
        'lineage_key': str(parent.get('lineage_key') or parent.get('family') or family) if parent else family,
        'role': 'diff' if _FILE_LINEAGE_DIFF_RE.search(target_filename) else ('enhanced' if _FILE_LINEAGE_GENERATED_RE.search(target_filename) else 'generated'),
        'lineage_strength': 'strong' if parent else 'weak',
    }


def file_lineage_make_diff_lineage(*, left: dict | None = None, right: dict | None = None, output_path: str = '', output_filename: str = '', family: str = '') -> dict:
    left = dict(left or {})
    right = dict(right or {})
    output_name = _flr_base(output_filename or output_path or 'diff')
    compared_ids = []
    for row in (left, right):
        fid = str(row.get('file_id') or row.get('registry_file_id') or row.get('record_key') or '').strip()
        if fid:
            compared_ids.append(fid)
    compared_paths = [str(x.get('path') or '').strip() for x in (left, right) if str(x.get('path') or '').strip()]
    compared_names = [str(x.get('filename') or '').strip() for x in (left, right) if str(x.get('filename') or '').strip()]
    lineage_key = str(family or right.get('lineage_key') or right.get('family') or left.get('lineage_key') or left.get('family') or file_lineage_normalized_family_name(output_name)).strip()
    return {
        'version': FILE_LINEAGE_REGISTRY_VERSION,
        'target_filename': output_name,
        'target_family': file_lineage_normalized_family_name(output_name),
        'basis_filename': str(left.get('filename') or ''),
        'parent_file_ids': _flr_unique(compared_ids[:1], limit=20),
        'source_file_ids': _flr_unique(compared_ids, limit=20),
        'compared_file_ids': _flr_unique(compared_ids, limit=20),
        'parent_path': str(left.get('path') or ''),
        'source_paths': _flr_unique(compared_paths, limit=20),
        'compared_paths': _flr_unique(compared_paths, limit=20),
        'compared_filenames': _flr_unique(compared_names, limit=20),
        'lineage_key': lineage_key,
        'role': 'diff',
        'lineage_strength': 'strong',
    }


def file_lineage_legacy_groups(records: list[dict] | None = None, *, max_groups: int = 8, max_versions: int = 4) -> list[dict]:
    normalized = []
    for idx, rec in enumerate(records or []):
        row = file_lineage_make_record(rec, source_hint=str((rec or {}).get('source') or 'history'), idx=idx) if isinstance(rec, dict) else None
        if row:
            normalized.append(row)
    groups: dict[str, list[dict]] = {}
    for row in normalized:
        key = str(row.get('lineage_key') or row.get('family') or '').strip()
        if key:
            groups.setdefault(key, []).append(row)
    out = []
    for key, rows in groups.items():
        rows = sorted(rows, key=lambda r: float(r.get('order') or 0.0), reverse=True)
        uploads = [r for r in rows if str(r.get('role') or '') == 'original']
        generated = [r for r in rows if str(r.get('role') or '') in {'enhanced', 'generated', 'diff'}]
        originals = []
        seen = set()
        for r in uploads:
            name = _flr_base(r.get('filename') or '')
            if name and name.lower() not in seen:
                seen.add(name.lower())
                originals.append(name)
        if not originals:
            for r in generated:
                for name in ([r.get('basis_filename')] + list(r.get('source_paths') or [])):
                    base = _flr_base(name)
                    if base and base.lower() not in seen:
                        seen.add(base.lower())
                        originals.append(base)
                        break
                if originals:
                    break
        versions = []
        seen_v = set()
        for r in generated:
            name = _flr_base(r.get('filename') or '')
            if name and name.lower() not in seen_v:
                seen_v.add(name.lower())
                versions.append(name)
            if len(versions) >= max(1, int(max_versions or 4)):
                break
        latest = rows[0] if rows else {}
        out.append({
            'key': key,
            'originals': originals[:3],
            'latest': _flr_base(latest.get('filename') or ''),
            'latest_role': str(latest.get('role') or ''),
            'versions': versions[:max(1, int(max_versions or 4))],
            'records': rows,
            'latest_order': float(latest.get('order') or 0.0),
        })
    out.sort(key=lambda g: float(g.get('latest_order') or 0.0), reverse=True)
    return out[:max(1, int(max_groups or 8))]


def file_lineage_record_names(row: dict | None = None) -> list[str]:
    r = dict(row or {})
    names = []
    lineage = file_lineage_extract(r)
    for value in [r.get('filename'), r.get('saved_filename'), lineage.get('basis_filename')]:
        if value:
            names.append(value)
    names.extend(lineage.get('source_paths') or [])
    names.extend(lineage.get('compared_filenames') or [])
    return [_flr_base(x) for x in _flr_unique(names, limit=12) if _flr_base(x)]
