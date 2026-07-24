# sandbox display paths, import manifest, path resolution, and base result records.

def _sandbox_display_path(path: str = '', messages: list | None = None) -> str:
    root = _sandbox_root(messages or [])
    try:
        rel = os.path.relpath(os.path.abspath(path), root)
        if rel == '.':
            return ''
        return rel.replace('\\', '/')
    except Exception:
        return ''


def _sandbox_import_manifest_path(messages: list | None = None) -> str:
    return os.path.join(_sandbox_root(messages or []), '.app3_imports.json')


def _sandbox_load_import_manifest(messages: list | None = None) -> list[dict]:
    path = _sandbox_import_manifest_path(messages or [])
    try:
        if not os.path.isfile(path):
            return []
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        rows = data.get('files') if isinstance(data, dict) else data
        return [dict(x) for x in (rows or []) if isinstance(x, dict)]
    except Exception:
        return []


def _sandbox_save_import_manifest(rows: list[dict] | None = None, messages: list | None = None) -> None:
    path = _sandbox_import_manifest_path(messages or [])
    clean = []
    seen = set()
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        rel = str(row.get('path') or '').strip().replace('\\', '/').strip('/')
        if not rel:
            continue
        key = rel.lower()
        if key in seen:
            continue
        seen.add(key)
        clean.append({
            'path': rel,
            'mount_path': ('/mnt/data/' + rel).rstrip('/'),
            'filename': str(row.get('filename') or '').strip(),
            'source_filename': str(row.get('source_filename') or row.get('filename') or '').strip(),
            'size': int(row.get('size') or 0),
            'imported_at': int(row.get('imported_at') or time.time()),
        })
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            json.dump({'files': clean[-500:]}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _sandbox_note_imported_files(rows: list[dict] | None = None, messages: list | None = None) -> None:
    incoming = [dict(x) for x in (rows or []) if isinstance(x, dict)]
    if not incoming:
        return
    existing = _sandbox_load_import_manifest(messages or [])
    merged = []
    by_path = {}
    for row in existing + incoming:
        rel = str(row.get('path') or '').strip().replace('\\', '/').strip('/')
        if not rel:
            continue
        by_path[rel.lower()] = dict(row)
    for _key, row in by_path.items():
        merged.append(row)
    _sandbox_save_import_manifest(merged, messages or [])


def _sandbox_path_alias_candidates(raw: str = '', messages: list | None = None) -> list[str]:
    raw_s = str(raw or '').strip().replace('\\', '/').strip('/')
    if not raw_s:
        return []
    base = os.path.basename(raw_s)
    wanted = {raw_s, base}
    wanted_lower = {x.lower() for x in wanted if x}
    root = _sandbox_root(messages or [])
    out: list[str] = []

    def add(rel: str = '') -> None:
        rel_s = str(rel or '').strip().replace('\\', '/').strip('/')
        if rel_s and rel_s not in out:
            out.append(rel_s)

    for row in _sandbox_load_import_manifest(messages or []):
        rel = str(row.get('path') or '').strip().replace('\\', '/').strip('/')
        names = {
            rel,
            os.path.basename(rel),
            str(row.get('filename') or '').strip(),
            str(row.get('source_filename') or '').strip(),
            os.path.basename(str(row.get('mount_path') or '').strip()),
        }
        if wanted_lower & {x.lower() for x in names if x}:
            add(rel)
    try:
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                if filename.lower() in wanted_lower:
                    add(os.path.relpath(os.path.join(dirpath, filename), root).replace('\\', '/'))
    except Exception:
        pass
    return out


def _sandbox_resolve_path(path: str = '', messages: list | None = None, *, must_exist: bool = False, for_dir: bool = False) -> tuple[str, str]:
    root = _sandbox_root(messages or [])
    raw = str(path or '').strip().replace('\\', '/')
    if raw.startswith('sandbox:'):
        raw = raw.split(':', 1)[1].strip().replace('\\', '/')
    for prefix in ('/mnt/data/', '/sandbox/'):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip('/')
            break
    if raw in {'/mnt/data', '/sandbox'}:
        raw = ''
    if raw in {'', '.', './', '/'}:
        target = root
    else:
        if raw.startswith('/') or re.match(r'^[A-Za-z]:', raw) or '..' in raw.split('/'):
            raise ValueError('path_outside_sandbox')
        target = os.path.abspath(os.path.join(root, *[p for p in raw.split('/') if p]))
    root_abs = os.path.abspath(root)
    target_abs = os.path.abspath(target)
    if not (target_abs == root_abs or target_abs.startswith(root_abs + os.sep)):
        raise ValueError('path_outside_sandbox')
    if must_exist and not os.path.exists(target_abs):
        for alias_rel in _sandbox_path_alias_candidates(raw, messages or []):
            alias_abs = os.path.abspath(os.path.join(root_abs, *[p for p in alias_rel.split('/') if p]))
            if (alias_abs == root_abs or alias_abs.startswith(root_abs + os.sep)) and os.path.exists(alias_abs):
                target_abs = alias_abs
                break
        else:
            raise FileNotFoundError(_sandbox_display_path(target_abs, messages or []))
    if for_dir and os.path.exists(target_abs) and not os.path.isdir(target_abs):
        raise NotADirectoryError(_sandbox_display_path(target_abs, messages or []))
    return target_abs, _sandbox_display_path(target_abs, messages or [])


def _sandbox_result_base(messages: list | None = None) -> dict:
    root = _sandbox_root(messages or [])
    return {
        'sandbox_id': _sandbox_session_slug(messages or []),
        'mount': '/mnt/data',
        'sandbox_root': root,
        'sandbox_relative_root': _sandbox_display_path(root, messages or []),
        'backend': 'docker',
        'image': _sandbox_image_for_result(),
        'disk_usage_bytes': _sandbox_dir_size(root),
        'disk_max_bytes': _sandbox_disk_max_bytes(),
    }


def _sandbox_publish_source_record(abs_path: str = '', rel_path: str = '', messages: list | None = None) -> dict:
    root_abs = os.path.abspath(_sandbox_root(messages or []))
    path_abs = os.path.abspath(str(abs_path or ''))
    if not (path_abs == root_abs or path_abs.startswith(root_abs + os.sep)):
        return {}
    root_rel = os.path.relpath(root_abs, os.path.abspath(SANDBOX_ROOT_DIR)).replace('\\', '/')
    rel = str(rel_path or '').strip().replace('\\', '/')
    if not rel or rel.startswith('/') or '..' in rel.split('/'):
        return {}
    try:
        size = int(os.path.getsize(path_abs)) if os.path.isfile(path_abs) else 0
    except Exception:
        size = 0
    return {
        'path': rel,
        'sandbox_id': _sandbox_session_slug(messages or []),
        'sandbox_root_rel': root_rel,
        'size': size,
    }
