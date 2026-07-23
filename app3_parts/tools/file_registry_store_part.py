# Split from app3_parts/tools/file_registry_edit_tools_part.py.
# Purpose: file registry store, full-text store, symbol index, and public registry records.
# Loaded by app3.py before file_registry_edit_tools_part.py, sharing the original global namespace.

# ==============================
# Unified lightweight file registry for uploaded + generated code/text files
# ==============================
FILE_REGISTRY_STORE_FILE = _app_data_path('file_registry_store.json')
FILE_FULL_TEXT_STORE_DIR = _app_data_path('file_text_store')
_FILE_REGISTRY_LOCK = threading.Lock()
_FILE_TEXT_STORE_PRUNE_LOCK = threading.Lock()
_FILE_REGISTRY_STATE = {'files': {}, 'updated_at': 0.0}


def _file_full_text_store_max_chars() -> int:
    try:
        return max(200000, min(int(str(app_getenv('FILE_FULL_TEXT_STORE_MAX_CHARS', str(20 * 1024 * 1024)) or (20 * 1024 * 1024))), 80 * 1024 * 1024))
    except Exception:
        return 20 * 1024 * 1024


def _file_text_store_max_bytes() -> int:
    try:
        return max(0, int(str(app_getenv('FILE_TEXT_STORE_MAX_BYTES', str(1024 * 1024 * 1024)) or (1024 * 1024 * 1024))))
    except Exception:
        return 1024 * 1024 * 1024


def _file_context_read_max_chars() -> int:
    try:
        return max(120000, min(int(str(app_getenv('FILE_CONTEXT_READ_MAX_CHARS', str(2 * 1024 * 1024)) or (2 * 1024 * 1024))), 20 * 1024 * 1024))
    except Exception:
        return 2 * 1024 * 1024


def _file_text_store_root() -> str:
    os.makedirs(FILE_FULL_TEXT_STORE_DIR, exist_ok=True)
    return FILE_FULL_TEXT_STORE_DIR


def _prune_file_text_store(keep_paths: list[str] | None = None) -> dict:
    root = _file_text_store_root()
    max_bytes = _file_text_store_max_bytes()
    if max_bytes <= 0:
        return {'ok': True, 'max_bytes': max_bytes, 'total_bytes': 0, 'deleted': []}

    keep = {os.path.abspath(str(p)) for p in (keep_paths or []) if str(p or '').strip()}
    deleted: list[str] = []
    with _FILE_TEXT_STORE_PRUNE_LOCK:
        files: list[tuple[str, float, int]] = []
        total = 0
        try:
            for dirpath, _dirnames, filenames in os.walk(root):
                for name in filenames:
                    fp = os.path.join(dirpath, name)
                    try:
                        st = os.stat(fp)
                    except Exception:
                        continue
                    if not os.path.isfile(fp):
                        continue
                    size = int(st.st_size)
                    total += size
                    files.append((fp, float(st.st_mtime), size))
        except Exception:
            return {'ok': False, 'max_bytes': max_bytes, 'total_bytes': 0, 'deleted': []}

        if total <= max_bytes:
            return {'ok': True, 'max_bytes': max_bytes, 'total_bytes': total, 'deleted': deleted}

        files.sort(key=lambda item: (item[1], item[0]))
        for fp, _mt, size in files:
            if total <= max_bytes:
                break
            if os.path.abspath(fp) in keep:
                continue
            try:
                os.remove(fp)
                total -= size
                deleted.append(os.path.relpath(fp, root))
            except Exception:
                continue

        try:
            for dirpath, dirnames, _filenames in os.walk(root, topdown=False):
                for dirname in dirnames:
                    dp = os.path.join(dirpath, dirname)
                    try:
                        if not os.listdir(dp):
                            os.rmdir(dp)
                    except Exception:
                        pass
        except Exception:
            pass

    if deleted:
        try:
            app_logger.info('[file_text_store] pruned deleted=%s total=%s max=%s', len(deleted), total, max_bytes)
        except Exception:
            pass
    elif total > max_bytes:
        try:
            app_logger.warning('[file_text_store] over_limit_but_preserved total=%s max=%s keep=%s', total, max_bytes, len(keep))
        except Exception:
            pass
    return {'ok': True, 'max_bytes': max_bytes, 'total_bytes': total, 'deleted': deleted}


def _file_text_store_ref(namespace: str = 'uploads', scope: str = '', content_hash: str = '', filename: str = '') -> str:
    ns = re.sub(r'[^0-9A-Za-z_-]+', '-', str(namespace or 'uploads').strip()) or 'uploads'
    sc = _normalize_upload_scope(scope) if scope else UPLOAD_SCOPE_LOCAL
    seed = str(content_hash or '').strip() or hashlib.sha256(str(filename or '').encode('utf-8', errors='ignore')).hexdigest()[:16]
    safe_seed = re.sub(r'[^0-9A-Za-z_-]+', '-', seed)[:80] or hashlib.sha1(str(filename or '').encode('utf-8', errors='ignore')).hexdigest()[:16]
    ext_hint = re.sub(r'[^0-9A-Za-z_-]+', '-', os.path.splitext(os.path.basename(str(filename or 'file')))[0])[:60]
    name = f'{safe_seed}_{ext_hint}.txt' if ext_hint else f'{safe_seed}.txt'
    return '/'.join([ns, sc, name])


def _file_text_store_path(ref: str = '') -> str:
    raw = str(ref or '').strip().replace('\\', '/')
    if not raw or raw.startswith('/') or '..' in raw.split('/'):
        return ''
    parts = [re.sub(r'[^0-9A-Za-z_.-]+', '-', part) for part in raw.split('/') if part]
    if not parts:
        return ''
    root = os.path.abspath(_file_text_store_root())
    path = os.path.abspath(os.path.join(root, *parts))
    if not (path == root or path.startswith(root + os.sep)):
        return ''
    return path


def _file_text_store_write_text(*, namespace: str = 'uploads', scope: str = '', filename: str = '', text: str = '', content_hash: str = '') -> dict:
    raw = str(text or '')
    if not raw.strip():
        return {}
    original_chars = len(raw)
    max_chars = _file_full_text_store_max_chars()
    stored_text = raw if original_chars <= max_chars else raw[:max_chars]
    ref = _file_text_store_ref(namespace=namespace, scope=scope, content_hash=content_hash, filename=filename)
    path = _file_text_store_path(ref)
    if not path:
        return {}
    try:
        _write_bytes_atomic(path, stored_text.encode('utf-8', errors='replace'))
        try:
            _prune_file_text_store(keep_paths=[path])
        except Exception:
            pass
        return {
            'full_text_ref': ref,
            'full_text_available': True,
            'full_text_chars': original_chars,
            'full_text_lines': raw.count('\n') + (1 if raw else 0),
            'stored_text_chars': len(stored_text),
            'stored_text_truncated': bool(len(stored_text) < original_chars),
        }
    except Exception:
        try:
            app_logger.exception('[file_text_store] write_failed filename=%s', filename)
        except Exception:
            pass
        return {}


def _file_text_store_read_text(ref: str = '', *, max_chars: int | None = None) -> str:
    path = _file_text_store_path(ref)
    if not path or not os.path.isfile(path):
        return ''
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            if max_chars is None or int(max_chars or 0) <= 0:
                return f.read()
            return f.read(max(1, int(max_chars or 0)))
    except Exception:
        try:
            app_logger.exception('[file_text_store] read_failed ref=%s', ref)
        except Exception:
            pass
        return ''


FILE_REGISTRY_CODE_EXTS = {
    '.py', '.pyw', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.mts', '.cts',
    '.html', '.htm', '.css', '.scss', '.less', '.vue', '.svelte', '.astro',
    '.json', '.jsonl', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.properties',
    '.sh', '.bash', '.zsh', '.bat', '.cmd', '.ps1', '.sql', '.xml', '.svg',
    '.java', '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.kts', '.cs',
    '.c', '.cc', '.cpp', '.cxx', '.h', '.hpp', '.gradle', '.proto', '.md', '.txt', '.env', ''
}
FILE_REGISTRY_SPECIAL_NAMES = set(SPECIAL_TEXT_FILENAMES) | {'dockerfile', 'makefile', 'jenkinsfile', 'procfile'}


def _file_registry_is_code_like(filename: str = '', ext: str = '') -> bool:
    name = os.path.basename(str(filename or '')).strip().lower()
    ext_l = str(ext or _ext_of(filename) or '').strip().lower()
    return bool(name in FILE_REGISTRY_SPECIAL_NAMES or ext_l in FILE_REGISTRY_CODE_EXTS)


def _file_registry_model_text(text: str = '', filename: str = '') -> str:
    """Return a model/index friendly view of file text without losing the raw file.

    Large HTML exported by browsers/apps can contain huge inline base64 icons before
    the real <script> code. If we index or chunk the raw text directly, the model only
    sees the icon blob and misses the actual functions. The original file/full text is
    still preserved in file_text_store; this sanitized view is only for registry,
    symbol scanning and context injection.
    """
    raw = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    if not raw:
        return ''
    ext = _ext_of(filename)
    if ext in {'.html', '.htm', '.svg'}:
        try:
            # Remove large data: URLs such as apple-touch-icon base64 blobs while
            # preserving the surrounding tag/line for structure.
            raw = re.sub(
                r'data:[^\s"\']{800,}',
                'data:[large-inline-data-removed]',
                raw,
                flags=re.I,
            )
            # Remove any remaining giant base64-like tokens.
            raw = re.sub(
                r'(?<![A-Za-z0-9+/=])[A-Za-z0-9+/=]{3000,}(?![A-Za-z0-9+/=])',
                '[large-base64-removed]',
                raw,
            )
        except Exception:
            return raw
    return raw


def _file_registry_limits() -> tuple[int, int]:
    try:
        max_records = max(50, min(int(str(app_getenv('FILE_REGISTRY_MAX_RECORDS', '5000') or 5000)), 5000))
    except Exception:
        max_records = 5000
    try:
        max_bytes = max(512 * 1024, min(int(str(app_getenv('FILE_REGISTRY_MAX_BYTES', str(32 * 1024 * 1024)) or (32 * 1024 * 1024))), 256 * 1024 * 1024))
    except Exception:
        max_bytes = 32 * 1024 * 1024
    return max_records, max_bytes


def _file_registry_load() -> None:
    state = {'files': {}, 'updated_at': time.time()}
    try:
        if os.path.exists(FILE_REGISTRY_STORE_FILE):
            with open(FILE_REGISTRY_STORE_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f) or {}
            if isinstance(loaded, dict):
                files = loaded.get('files') or {}
                if isinstance(files, dict):
                    clean = {}
                    for key, rec in files.items():
                        if not isinstance(rec, dict):
                            continue
                        fid = str(rec.get('file_id') or key or '').strip()
                        filename = str(rec.get('filename') or '').strip()
                        if fid and filename:
                            obj = dict(rec)
                            obj['file_id'] = fid[:220]
                            obj['filename'] = filename[:220]
                            try:
                                obj['updated_at'] = float(obj.get('updated_at') or 0.0)
                            except Exception:
                                obj['updated_at'] = 0.0
                            clean[fid] = obj
                    state['files'] = clean
                try:
                    state['updated_at'] = float(loaded.get('updated_at') or time.time())
                except Exception:
                    state['updated_at'] = time.time()
    except Exception:
        try:
            app_logger.exception('[file_registry] load_failed')
        except Exception:
            pass
    with _FILE_REGISTRY_LOCK:
        _FILE_REGISTRY_STATE.clear()
        _FILE_REGISTRY_STATE.update(state)


def _file_registry_save(*, raise_on_error: bool = False) -> bool:
    max_records, max_bytes = _file_registry_limits()
    with _FILE_REGISTRY_LOCK:
        rows = [dict(v or {}) for v in (_FILE_REGISTRY_STATE.get('files') or {}).values() if isinstance(v, dict)]
        rows.sort(key=lambda x: float(x.get('updated_at') or x.get('created_at') or 0.0), reverse=True)
        rows = rows[:max_records]
        payload = {'files': {str(r.get('file_id') or ''): r for r in rows if str(r.get('file_id') or '')}, 'updated_at': time.time()}
        for _ in range(5):
            raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            if len(raw) <= max_bytes:
                break
            for rec in payload.get('files', {}).values():
                if isinstance(rec, dict):
                    rec['chunks'] = []
                    rec['preview'] = truncate_text(str(rec.get('preview') or ''), max_chars=600)
                    rec['summary'] = truncate_text(str(rec.get('summary') or ''), max_chars=600)
                    if isinstance(rec.get('symbols'), list):
                        rec['symbols'] = rec['symbols'][:40]
            keys = sorted(payload.get('files', {}).keys(), key=lambda k: float((payload['files'].get(k) or {}).get('updated_at') or 0.0), reverse=True)
            payload['files'] = {k: payload['files'][k] for k in keys[:max(50, int(len(keys) * 0.75))]}
        _FILE_REGISTRY_STATE.clear()
        _FILE_REGISTRY_STATE.update(payload)
    tmp = FILE_REGISTRY_STORE_FILE + '.tmp-' + uuid.uuid4().hex
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, FILE_REGISTRY_STORE_FILE)
        return True
    except Exception:
        try:
            app_logger.exception('[file_registry] save_failed')
        except Exception:
            pass
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        if raise_on_error:
            raise
        return False


def _file_registry_remove_records(file_ids=None) -> dict:
    """一次提交多个注册表删除；持久化失败时恢复内存快照。"""
    ids = {str(value or '').strip() for value in (file_ids or []) if str(value or '').strip()}
    if not ids:
        return {'removed': 0, 'records': {}}
    _file_registry_load()
    previous_state: dict = {}
    removed: dict[str, dict] = {}
    with _FILE_REGISTRY_LOCK:
        previous_state = {
            'files': dict((_FILE_REGISTRY_STATE.get('files') or {}) if isinstance(_FILE_REGISTRY_STATE.get('files'), dict) else {}),
            'updated_at': float(_FILE_REGISTRY_STATE.get('updated_at') or 0.0),
        }
        files = dict(previous_state['files'])
        for fid in ids:
            rec = files.pop(fid, None)
            if isinstance(rec, dict):
                removed[fid] = dict(rec)
        if not removed:
            return {'removed': 0, 'records': {}}
        _FILE_REGISTRY_STATE['files'] = files
        _FILE_REGISTRY_STATE['updated_at'] = time.time()
    try:
        _file_registry_save(raise_on_error=True)
    except Exception:
        with _FILE_REGISTRY_LOCK:
            _FILE_REGISTRY_STATE.clear()
            _FILE_REGISTRY_STATE.update(previous_state)
        raise
    return {'removed': len(removed), 'records': removed}


def _file_registry_symbol_scan_limit() -> int:
    try:
        return max(120, min(int(str(app_getenv('FILE_REGISTRY_SYMBOL_SCAN_LIMIT', '420') or 420)), 1200))
    except Exception:
        return 420


def _file_registry_add_symbol(symbols: list, seen: set, kind: str, name: str, line: int = 0, *, limit: int | None = None) -> bool:
    kind_s = str(kind or 'symbol').strip().lower() or 'symbol'
    name_s = str(name or '').strip()
    if not name_s:
        return False
    if name_s.lower() in {
        'if', 'for', 'while', 'switch', 'catch', 'try', 'else', 'return', 'function',
        'class', 'const', 'let', 'var', 'async', 'await', 'new', 'do',
    }:
        return False
    if len(name_s) > 180:
        name_s = name_s[:180]
    try:
        line_i = max(0, int(line or 0))
    except Exception:
        line_i = 0
    key = (kind_s, name_s, line_i)
    if key in seen:
        return False
    max_items = max(1, int(limit or _file_registry_symbol_scan_limit()))
    if len(symbols) >= max_items:
        return False
    seen.add(key)
    symbols.append({'kind': kind_s, 'name': name_s, 'line': line_i})
    return True


def _file_registry_extract_html_script_blocks(raw: str) -> list[tuple[str, int]]:
    """Return JS script bodies with 1-based starting line numbers.

    HTML 文件真正有用的“函数清单”通常在 <script> 中；这里专门抽脚本，
    避免只把 id/class 当成符号，导致模型误以为 index.html 没有函数。
    """
    text = str(raw or '')
    blocks: list[tuple[str, int]] = []
    if not text:
        return blocks
    for m in re.finditer(r'<script\b([^>]*)>([\s\S]*?)</script\s*>', text, flags=re.I):
        attrs = str(m.group(1) or '')
        body = str(m.group(2) or '')
        if not body.strip():
            continue
        type_m = re.search(r'\btype\s*=\s*["\']?([^"\'\s>]+)', attrs, flags=re.I)
        script_type = str(type_m.group(1) or '').strip().lower() if type_m else ''
        if script_type and script_type not in {
            'text/javascript', 'application/javascript', 'module',
            'text/ecmascript', 'application/ecmascript',
        }:
            continue
        start_line = text.count('\n', 0, m.start(2)) + 1
        blocks.append((body, start_line))
    return blocks


def _file_registry_extract_python_symbols(raw: str, symbols: list, seen: set, *, limit: int) -> bool:
    """Use AST when possible so Python 函数/类不是从片段里猜。"""
    try:
        ast_mod = __import__('ast')
        tree = ast_mod.parse(str(raw or ''))
    except Exception:
        return False

    class Visitor(ast_mod.NodeVisitor):
        def __init__(self):
            self.class_stack: list[str] = []

        def visit_ClassDef(self, node):
            _file_registry_add_symbol(symbols, seen, 'class', getattr(node, 'name', ''), getattr(node, 'lineno', 0), limit=limit)
            self.class_stack.append(str(getattr(node, 'name', '') or ''))
            self.generic_visit(node)
            if self.class_stack:
                self.class_stack.pop()

        def visit_FunctionDef(self, node):
            kind = 'method' if self.class_stack else 'function'
            name = str(getattr(node, 'name', '') or '')
            if self.class_stack:
                name = f"{self.class_stack[-1]}.{name}"
            _file_registry_add_symbol(symbols, seen, kind, name, getattr(node, 'lineno', 0), limit=limit)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            kind = 'method' if self.class_stack else 'function'
            name = str(getattr(node, 'name', '') or '')
            if self.class_stack:
                name = f"{self.class_stack[-1]}.{name}"
            _file_registry_add_symbol(symbols, seen, kind, name, getattr(node, 'lineno', 0), limit=limit)
            self.generic_visit(node)

    try:
        Visitor().visit(tree)
        return True
    except Exception:
        return False


def _file_registry_extract_js_symbols(js_text: str, symbols: list, seen: set, *, base_line: int = 1, limit: int | None = None) -> None:
    """Lightweight JS/TS/HTML-script symbol scanner.

    覆盖常见前端写法：
    - function foo(...)
    - async function foo(...)
    - const/let/var foo = (...) => ...
    - const/let/var foo = function(...)
    - object/class method: foo(...) { ... }
    """
    raw = str(js_text or '')
    max_items = max(1, int(limit or _file_registry_symbol_scan_limit()))
    patterns: list[tuple[str, str]] = [
        ('class', r'^\s*(?:export\s+default\s+|export\s+)?class\s+([A-Za-z_$][\w$]*)\b'),
        ('function', r'^\s*(?:export\s+default\s+|export\s+)?(?:async\s+)?function\s*\*?\s+([A-Za-z_$][\w$]*)\s*\('),
        ('function', r'^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?function\b'),
        ('function', r'^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>'),
        ('function', r'^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?[A-Za-z_$][\w$]*\s*=>'),
        ('function', r'^\s*([A-Za-z_$][\w$]*)\s*[:=]\s*(?:async\s+)?function\s*\('),
        ('function', r'^\s*([A-Za-z_$][\w$]*)\s*[:=]\s*(?:async\s*)?\([^)]*\)\s*=>'),
        ('method', r'^\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{'),
    ]
    for rel_lineno, line in enumerate(raw.splitlines(), 0):
        if len(symbols) >= max_items:
            break
        stripped = line.strip()
        if not stripped or stripped.startswith('//') or stripped.startswith('*'):
            continue
        for kind, pat in patterns:
            m = re.search(pat, line)
            if not m:
                continue
            name = str(m.group(1) or '').strip()
            if kind == 'method' and name in {'if', 'for', 'while', 'switch', 'catch', 'try', 'else', 'function'}:
                continue
            if _file_registry_add_symbol(symbols, seen, kind, name, int(base_line or 1) + rel_lineno, limit=max_items):
                break


def _file_registry_extract_symbols(text: str, filename: str = '') -> list[dict]:
    raw = str(text or '')
    ext = _ext_of(filename)
    limit = _file_registry_symbol_scan_limit()
    symbols: list[dict] = []
    seen: set = set()
    if not raw.strip():
        return symbols

    if ext in {'.py', '.pyw'}:
        parsed = _file_registry_extract_python_symbols(raw, symbols, seen, limit=limit)
        if not parsed:
            for lineno, line in enumerate(raw.splitlines(), 1):
                if len(symbols) >= limit:
                    break
                for kind, pat in (
                    ('class', r'^\s*class\s+([A-Za-z_][\w]*)'),
                    ('function', r'^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)\s*\('),
                ):
                    m = re.search(pat, line)
                    if m:
                        _file_registry_add_symbol(symbols, seen, kind, m.group(1), lineno, limit=limit)
                        break
        return symbols

    if ext in {'.html', '.htm'}:
        for body, start_line in _file_registry_extract_html_script_blocks(raw):
            _file_registry_extract_js_symbols(body, symbols, seen, base_line=start_line, limit=limit)
            if len(symbols) >= limit:
                break
        dom_limit = min(limit, len(symbols) + 80)
        for lineno, line in enumerate(raw.splitlines(), 1):
            if len(symbols) >= dom_limit:
                break
            for kind, pat in (
                ('id', r'\bid=["\']([^"\']+)["\']'),
                ('class', r'\bclass=["\']([^"\']+)["\']'),
            ):
                for m in re.finditer(pat, line, flags=re.I):
                    names = re.split(r'\s+', str(m.group(1) or '').strip()) if kind == 'class' else [str(m.group(1) or '').strip()]
                    for name in names:
                        _file_registry_add_symbol(symbols, seen, kind, name, lineno, limit=dom_limit)
                        if len(symbols) >= dom_limit:
                            break
                    if len(symbols) >= dom_limit:
                        break
        return symbols

    if ext in {'.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.mts', '.cts', '.vue', '.svelte', '.astro'}:
        _file_registry_extract_js_symbols(raw, symbols, seen, base_line=1, limit=limit)
        return symbols

    if ext in {'.java', '.kt', '.kts', '.cs', '.go', '.rs', '.php', '.rb', '.swift', '.c', '.cc', '.cpp', '.cxx', '.h', '.hpp'}:
        patterns = [
            ('class', r'^\s*(?:public\s+|private\s+|protected\s+|internal\s+|export\s+)?(?:class|struct|enum|interface|trait)\s+([A-Za-z_][\w]*)'),
            ('function', r'^\s*(?:public\s+|private\s+|protected\s+|static\s+|async\s+|func\s+|fn\s+|def\s+|function\s+)*([A-Za-z_][\w]*)\s*\([^;{}]*\)\s*(?:\{|->|:)'),
        ]
    elif ext in {'.css', '.scss', '.less'}:
        patterns = [('selector', r'^\s*([.#][A-Za-z0-9_-]+)\s*[,{\s]')]
    elif ext == '.sql':
        patterns = [('sql', r'^\s*(?:CREATE|ALTER)\s+(?:TABLE|VIEW|INDEX|FUNCTION|PROCEDURE)\s+([\w.]+)')]
    else:
        patterns = [('key', r'^\s*([A-Za-z_][\w.-]{2,})\s*[:=]')]

    for lineno, line in enumerate(raw.splitlines(), 1):
        if len(symbols) >= limit:
            break
        for kind, pat in patterns:
            m = re.search(pat, line, flags=re.I)
            if not m:
                continue
            _file_registry_add_symbol(symbols, seen, kind, str(m.group(1) or '').strip(), lineno, limit=limit)
            break
    return symbols


def _file_registry_make_chunks(text: str, max_chunks: int = 8, chunk_chars: int = 1400) -> list[dict]:
    raw = str(text or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not raw:
        return []
    lines = raw.split('\n')
    chunks, buf, start_line, cur_len = [], [], 1, 0
    for i, line in enumerate(lines, 1):
        if buf and cur_len + len(line) + 1 > chunk_chars:
            chunks.append({'index': len(chunks) + 1, 'start_line': start_line, 'end_line': i - 1, 'text': '\n'.join(buf).strip()})
            if len(chunks) >= max_chunks:
                break
            start_line, buf, cur_len = i, [], 0
        buf.append(line)
        cur_len += len(line) + 1
    if len(chunks) < max_chunks and buf:
        chunks.append({'index': len(chunks) + 1, 'start_line': start_line, 'end_line': start_line + len(buf) - 1, 'text': '\n'.join(buf).strip()})
    return [c for c in chunks if c.get('text')]


def _file_registry_quick_summary(text: str, filename: str, source: str = '') -> str:
    raw = str(text or '').strip()
    line_count = raw.count('\n') + (1 if raw else 0)
    symbols = _file_registry_extract_symbols(raw, filename)
    names = [str(s.get('name') or '').strip() for s in symbols if str(s.get('name') or '').strip()]
    src = 'AI生成文件' if str(source or '') == 'generated' else '用户上传文件'
    parts = [f'{src}《{os.path.basename(str(filename or ""))}》']
    ext = _ext_of(filename)
    if ext:
        parts.append(f'类型 {ext}')
    if line_count:
        parts.append(f'约 {line_count} 行')
    if names:
        parts.append('关键符号：' + '、'.join(names[:18]))
    else:
        head = re.sub(r'\s+', ' ', raw[:500]).strip()
        if head:
            parts.append('开头内容：' + truncate_text(head, max_chars=180))
    return '；'.join(parts)[:900]


def _file_registry_public(record: dict | None = None) -> dict:
    rec = dict(record or {})
    if not rec:
        return {}
    return {
        'file_id': str(rec.get('file_id') or ''),
        'source': str(rec.get('source') or ''),
        'namespace': str(rec.get('namespace') or ''),
        'scope': str(rec.get('scope') or ''),
        'filename': str(rec.get('filename') or ''),
        'saved_filename': str(rec.get('saved_filename') or ''),
        'ext': str(rec.get('ext') or ''),
        'size': int(rec.get('size') or 0),
        'url': str(rec.get('url') or rec.get('download_url') or ''),
        'view_url': str(rec.get('view_url') or ''),
        'download_url': str(rec.get('download_url') or rec.get('url') or ''),
        'summary': truncate_text(str(rec.get('summary') or ''), max_chars=900),
        'symbols': (rec.get('symbols') or [])[:220] if isinstance(rec.get('symbols'), list) else [],
        'preview': truncate_text(str(rec.get('preview') or ''), max_chars=1600),
        'is_code_like': bool(rec.get('is_code_like')),
        'full_text_available': bool(rec.get('full_text_available') or rec.get('full_text_ref')),
        'full_text_chars': int(rec.get('full_text_chars') or rec.get('parsed_chars') or 0),
        'full_text_lines': int(rec.get('full_text_lines') or rec.get('parsed_lines') or 0),
        'stored_text_chars': int(rec.get('stored_text_chars') or 0),
        'stored_text_truncated': bool(rec.get('stored_text_truncated')),
        'registry_text_truncated': bool(rec.get('registry_text_truncated')),
        'updated_at': float(rec.get('updated_at') or 0.0),
    }


def _file_registry_record_from_text(*, namespace: str, scope: str, source: str, filename: str, saved_filename: str = '', text: str = '', size_bytes: int = 0, url: str = '', view_url: str = '', download_url: str = '', storage_ref: str = '', content_hash: str = '') -> dict:
    fn = str(filename or saved_filename or '').strip()
    saved = str(saved_filename or fn).strip()
    ext = _ext_of(fn) or _ext_of(saved)
    full_text_raw = str(text or '')
    raw_hash = str(content_hash or '').strip() or hashlib.sha256(full_text_raw.encode('utf-8', errors='ignore')).hexdigest()[:16]
    text_store = _file_text_store_write_text(
        namespace=str(namespace or 'uploads').strip() or 'uploads',
        scope=_normalize_upload_scope(scope),
        filename=saved or fn or 'file',
        text=full_text_raw,
        content_hash=raw_hash,
    )
    registry_cache_limit = max(2000, min(int(app_getenv('FILE_REGISTRY_TEXT_CACHE_CHARS', '120000') or 120000), 300000))
    model_text_full = _file_registry_model_text(full_text_raw, fn or saved)
    # Registry preview/chunks can be budgeted, but deterministic symbols must be
    # scanned from the full model-friendly text, not only from the head preview.
    raw_text = truncate_text(model_text_full or full_text_raw, max_chars=registry_cache_limit)
    symbol_text = model_text_full or full_text_raw
    fid_seed = f'{namespace}|{_normalize_upload_scope(scope)}|{saved or fn}|{raw_hash[:16]}'
    fid = hashlib.sha1(fid_seed.encode('utf-8', errors='ignore')).hexdigest()[:24]
    ts = time.time()
    return {
        'file_id': fid,
        'source': str(source or '').strip() or ('generated' if str(namespace or '') == 'generated' else 'upload'),
        'namespace': str(namespace or 'uploads').strip() or 'uploads',
        'scope': _normalize_upload_scope(scope),
        'filename': fn,
        'saved_filename': saved,
        'ext': ext,
        'size': int(size_bytes or 0),
        'url': str(url or '').strip(),
        'view_url': str(view_url or '').strip(),
        'download_url': str(download_url or '').strip(),
        'storage_ref': str(storage_ref or '').strip(),
        'summary': _file_registry_quick_summary(symbol_text, fn or saved, source=source),
        'symbols': _file_registry_extract_symbols(symbol_text, fn or saved),
        'preview': truncate_text('\n'.join(raw_text.splitlines()[:120]).strip() or raw_text, max_chars=1600),
        'chunks': _file_registry_make_chunks(raw_text),
        'is_code_like': _file_registry_is_code_like(fn or saved, ext),
        'content_hash': raw_hash,
        'full_text_ref': str(text_store.get('full_text_ref') or ''),
        'full_text_available': bool(text_store.get('full_text_available')),
        'full_text_chars': int(text_store.get('full_text_chars') or len(full_text_raw)),
        'full_text_lines': int(text_store.get('full_text_lines') or (full_text_raw.count('\n') + (1 if full_text_raw else 0))),
        'stored_text_chars': int(text_store.get('stored_text_chars') or 0),
        'stored_text_truncated': bool(text_store.get('stored_text_truncated')),
        'registry_text_truncated': bool(len(raw_text) < len(full_text_raw)),
        'created_at': ts,
        'updated_at': ts,
    }


def _file_registry_upsert(record: dict | None = None) -> dict:
    if not isinstance(record, dict) or not str(record.get('file_id') or '').strip():
        return {}
    rec = dict(record)
    now_ts = time.time()
    rec['updated_at'] = now_ts
    rec.setdefault('created_at', now_ts)
    try:
        with _FILE_REGISTRY_LOCK:
            files = dict(_FILE_REGISTRY_STATE.get('files') or {})
            files[str(rec.get('file_id'))] = rec
            _FILE_REGISTRY_STATE['files'] = files
            _FILE_REGISTRY_STATE['updated_at'] = now_ts
        _file_registry_save()
    except Exception:
        try:
            app_logger.exception('[file_registry] upsert_failed filename=%s', rec.get('filename'))
        except Exception:
            pass
    return _file_registry_public(rec)


try:
    _file_registry_load()
except Exception:
    pass


def _file_registry_files_snapshot() -> dict:
    """Return a copy of registry files after loading under the registry lock."""
    try:
        _file_registry_load()
    except Exception:
        pass
    try:
        with _FILE_REGISTRY_LOCK:
            return dict((_FILE_REGISTRY_STATE.get('files') or {}) if isinstance(_FILE_REGISTRY_STATE, dict) else {})
    except Exception:
        return {}


def _file_registry_records_snapshot() -> list[dict]:
    return [dict(v or {}) for v in _file_registry_files_snapshot().values() if isinstance(v, dict)]
