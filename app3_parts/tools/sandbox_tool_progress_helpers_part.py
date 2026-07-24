# sandbox tool progress file-name helpers.

def _sandbox_progress_public_file_label(value) -> str:
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


def _sandbox_progress_collect_file_names(*values, limit: int = 80) -> tuple[list[str], int]:
    out: list[str] = []
    seen: set[str] = set()
    max_items = max(1, min(int(limit or 80), 200))

    def add(value):
        if value is None:
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                add(item)
            return
        if isinstance(value, dict):
            for key in ('display_name', 'displayName', 'filename', 'target_filename', 'targetFilename', 'source_filename', 'name', 'path', 'mount_path', 'url', 'href'):
                if value.get(key):
                    add(value.get(key))
            for key in ('files_preview', 'fileNames', 'file_names', 'filenames', 'files', 'paths', 'items', 'compare_candidates', 'left', 'right', 'diffs', 'pair', 'delivery_files'):
                if value.get(key):
                    add(value.get(key))
            return
        name = _sandbox_progress_public_file_label(value)
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


def _sandbox_progress_selector_count(value) -> int:
    if value is None or value == '':
        return 0
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if isinstance(value, (str, dict)):
        return 1
    return 0
