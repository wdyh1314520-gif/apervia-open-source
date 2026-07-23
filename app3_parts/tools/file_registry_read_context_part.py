# Split from app3_parts/tools/file_registry_edit_tools_part.py.
# Purpose: file read context and symbol-window helpers.
# Loaded by app3.py via _exec_split_file(...), sharing the original global namespace.

def _file_read_context_max_chars(value=None) -> int:
    try:
        default_chars = int(str(app_getenv('FILE_READ_CONTEXT_DEFAULT_MAX_CHARS', '120000') or 120000))
    except Exception:
        default_chars = 120000
    try:
        min_chars = int(str(app_getenv('FILE_READ_CONTEXT_MIN_CHARS', '30000') or 30000))
    except Exception:
        min_chars = 30000
    try:
        hard_max = int(str(app_getenv('FILE_READ_CONTEXT_HARD_MAX_CHARS', '600000') or 600000))
    except Exception:
        hard_max = 600000
    try:
        requested = int(value) if value not in (None, '') else int(default_chars)
    except Exception:
        requested = int(default_chars)
    min_chars = max(2000, min(int(min_chars), int(hard_max)))
    hard_max = max(min_chars, int(hard_max))
    return max(min_chars, min(int(requested), hard_max))


def _file_read_tool_result_model_max_chars(value=None) -> int:
    try:
        default_chars = int(str(app_getenv('FILE_READ_TOOL_RESULT_MODEL_MAX_CHARS', '120000') or 120000))
    except Exception:
        default_chars = 120000
    try:
        hard_max = int(str(app_getenv('FILE_READ_TOOL_RESULT_HARD_MAX_CHARS', '600000') or 600000))
    except Exception:
        hard_max = 600000
    try:
        requested = int(value) if value not in (None, '') else int(default_chars)
    except Exception:
        requested = int(default_chars)
    return max(12000, min(int(requested), max(12000, int(hard_max))))


def _file_read_context_next_read_hints(
    *,
    filename: str = '',
    function_name: str = '',
    query: str = '',
    mode: str = '',
    chars: int = 0,
    source_chars: int = 0,
    max_chars: int = 0,
    prefer_full_file: bool = False,
) -> dict:
    try:
        src_len = max(0, int(source_chars or 0))
    except Exception:
        src_len = 0
    try:
        got_len = max(0, int(chars or 0))
    except Exception:
        got_len = 0
    try:
        cur_max = max(0, int(max_chars or 0))
    except Exception:
        cur_max = 0
    coverage = round((got_len / src_len), 4) if src_len > 0 else 0.0
    truncated = bool(src_len > 0 and got_len < src_len and str(mode or '') not in {'symbol_window', 'callable_context', 'query_snippets'})
    can_expand = bool(src_len > got_len or src_len > cur_max)
    next_max = 0
    if can_expand:
        next_max = min(_file_read_context_max_chars(src_len), max(src_len, cur_max * 2 if cur_max else 0, 120000))
    recommended = []
    base = {
        'target_filename': str(filename or '').strip(),
        'query': str(query or '').strip(),
        'function_name': str(function_name or '').strip(),
    }
    if can_expand and next_max > cur_max:
        row = {k: v for k, v in base.items() if v}
        row['max_chars'] = int(next_max)
        recommended.append(row)
    if src_len > got_len and not prefer_full_file:
        row = {k: v for k, v in base.items() if v}
        row['prefer_full_file'] = True
        row['max_chars'] = int(next_max or cur_max or 120000)
        recommended.append(row)
    return {
        'coverage': coverage,
        'truncated': truncated,
        'can_expand': can_expand,
        'next_max_chars': int(next_max or 0),
        'recommended_next_reads': recommended[:2],
    }

def _file_read_query_needs_runtime_code_context(query: str) -> bool:
    """Whether a user request needs enough executable source context to edit/reason.

    This is a generic quality guard for source reading. It does not route by a
    project-specific keyword; it only prevents tiny HTML ids/classes/selectors or
    one-line fragments from being treated as sufficient source context for a
    behavior/edit request.
    """
    q = str(query or '')
    if not q.strip():
        return False
    return bool(re.search(
        r'(修改|改成|新增|添加|删除|移除|修复|实现|显示|隐藏|渲染|提示|状态|为空|为空时|返回完整|完整文件|交付|\bedit\b|\bmodify\b|\bfix\b|\badd\b|\bdelete\b|\bremove\b|\bshow\b|\bdisplay\b|\brender\b|\bempty\b|\bstate\b|\bfull file\b)',
        q,
        flags=re.I,
    ))


def _file_read_source_context_too_small(snippet: str, source_text: str, query: str) -> bool:
    """Reject suspiciously tiny context for behavior/edit requests.

    A 10-100 character HTML id/class/selector can be a valid search hit, but it
    is not enough evidence to modify an existing source file. In that case we
    fall back to callable scoring or broader snippets.
    """
    s = str(snippet or '').strip()
    if not s:
        return False
    if not _file_read_query_needs_runtime_code_context(query):
        return False
    if len(str(source_text or '')) <= max(1200, len(s) + 400):
        return False
    if len(s) < 240:
        return True
    if len(s) < 600 and not re.search(r'(function\s+|=>\s*\{|\bif\s*\(|\bfor\s*\(|\bwhile\s*\(|appendChild\s*\(|textContent\s*=|innerHTML\s*=|addEventListener\s*\(|onclick\s*=|class\s+|def\s+)', s):
        return True
    return False


def _file_line_span_from_offsets(raw: str, start_pos: int, end_pos: int) -> tuple[int, int]:
    text = str(raw or '')
    a = max(0, min(len(text), int(start_pos or 0)))
    b = max(a, min(len(text), int(end_pos or a)))
    start_line = text.count('\n', 0, a) + 1
    end_line = text.count('\n', 0, b) + 1
    return start_line, end_line


def _file_read_match_brace_block(raw: str, open_brace_pos: int) -> int:
    text = str(raw or '')
    n = len(text)
    i = max(0, int(open_brace_pos or 0))
    if i >= n or text[i] != '{':
        return -1
    depth = 0
    quote = ''
    escape = False
    line_comment = False
    block_comment = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ''
        if line_comment:
            if ch == '\n':
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == '*' and nxt == '/':
                block_comment = False
                i += 2
            else:
                i += 1
            continue
        if quote:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == quote:
                quote = ''
            i += 1
            continue
        if ch == '/' and nxt == '/':
            line_comment = True
            i += 2
            continue
        if ch == '/' and nxt == '*':
            block_comment = True
            i += 2
            continue
        if ch in {'"', "'", '`'}:
            quote = ch
            i += 1
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth <= 0:
                return i + 1
        i += 1
    return -1


def _file_read_extract_js_like_block(text: str, filename: str, symbol_name: str) -> tuple[str, int, int]:
    raw = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    name = str(symbol_name or '').strip()
    if not raw or not name:
        return '', 0, 0
    leaf = re.escape(name.split('.')[-1])
    patterns = [
        rf'(?m)(?:async\s+)?function\s+{leaf}\s*\([^)]*\)\s*\{{',
        rf'(?m)(?:const|let|var)\s+{leaf}\s*=\s*(?:async\s*)?(?:function\s*)?\([^)]*\)\s*=>?\s*\{{',
        rf'(?m)(?:const|let|var)\s+{leaf}\s*=\s*(?:async\s+)?function\s*\([^)]*\)\s*\{{',
        rf'(?m){leaf}\s*[:=]\s*(?:async\s*)?function\s*\([^)]*\)\s*\{{',
        rf'(?m){leaf}\s*[:=]\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{{',
        rf'(?m)(?:async\s+)?{leaf}\s*\([^)]*\)\s*\{{',
    ]
    best = None
    for pat in patterns:
        try:
            m = re.search(pat, raw)
        except Exception:
            m = None
        if not m:
            continue
        brace_pos = raw.find('{', m.start(), m.end() + 1)
        if brace_pos < 0:
            continue
        end_pos = _file_read_match_brace_block(raw, brace_pos)
        if end_pos < 0:
            continue
        if best is None or m.start() < best[0]:
            best = (m.start(), end_pos)
    if best is None:
        # Single-line arrow / assignment fallback, useful for tiny helpers.
        try:
            m = re.search(rf'(?m)^\s*(?:const|let|var)\s+{leaf}\s*=.*$', raw)
        except Exception:
            m = None
        if m:
            start_line, end_line = _file_line_span_from_offsets(raw, m.start(), m.end())
            return raw[m.start():m.end()], start_line, end_line
        return '', 0, 0
    start_pos, end_pos = best
    start_line, end_line = _file_line_span_from_offsets(raw, start_pos, end_pos)
    return raw[start_pos:end_pos], start_line, end_line


def _file_read_extract_python_block(text: str, filename: str, symbol_name: str) -> tuple[str, int, int]:
    raw = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    name = str(symbol_name or '').strip()
    if not raw or not name:
        return '', 0, 0
    try:
        ast_mod = __import__('ast')
        tree = ast_mod.parse(raw)
        lines = raw.splitlines()
        target_leaf = name.split('.')[-1]
        best = None

        class Visitor(ast_mod.NodeVisitor):
            def __init__(self):
                self.class_stack = []
            def visit_ClassDef(self, node):
                qn = '.'.join([*self.class_stack, getattr(node, 'name', '')]) if self.class_stack else str(getattr(node, 'name', '') or '')
                nonlocal best
                if qn == name or getattr(node, 'name', '') == target_leaf:
                    best = node
                self.class_stack.append(str(getattr(node, 'name', '') or ''))
                self.generic_visit(node)
                self.class_stack.pop()
            def visit_FunctionDef(self, node):
                qn = '.'.join([*self.class_stack, getattr(node, 'name', '')]) if self.class_stack else str(getattr(node, 'name', '') or '')
                nonlocal best
                if qn == name or getattr(node, 'name', '') == target_leaf:
                    best = node
                self.generic_visit(node)
            def visit_AsyncFunctionDef(self, node):
                self.visit_FunctionDef(node)

        Visitor().visit(tree)
        if best is not None:
            start = max(1, int(getattr(best, 'lineno', 1) or 1))
            end = max(start, int(getattr(best, 'end_lineno', start) or start))
            return '\n'.join(lines[start - 1:end]), start, end
    except Exception:
        pass
    return '', 0, 0


def _file_read_extract_symbol_window(text: str, record: dict | None, symbol_name: str, max_chars: int) -> tuple[str, int, int]:
    raw = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    name = str(symbol_name or '').strip()
    if not raw or not name:
        return '', 0, 0
    filename = str((record or {}).get('filename') or (record or {}).get('saved_filename') or '')
    ext = _history_file_ext(filename)
    if ext in {'.py', '.pyw'}:
        block, start, end = _file_read_extract_python_block(raw, filename, name)
        if block:
            return block[:max_chars], start, end
    if ext in {'.js', '.jsx', '.ts', '.tsx', '.html', '.htm', '.vue', '.svelte'}:
        block, start, end = _file_read_extract_js_like_block(raw, filename, name)
        if block:
            return block[:max_chars], start, end
    lines = raw.splitlines()
    symbols = [dict(s) for s in ((record or {}).get('symbols') or []) if isinstance(s, dict)]
    if not symbols:
        try:
            symbols = _file_registry_extract_symbols(raw, filename)
        except Exception:
            symbols = []
    candidates = []
    leaf = name.split('.')[-1]
    for s in symbols:
        sname = str(s.get('name') or '').strip()
        if not sname:
            continue
        if sname == name or sname.split('.')[-1] == leaf:
            try:
                line = int(s.get('line') or 0)
            except Exception:
                line = 0
            if line > 0:
                candidates.append((line, sname))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        start = candidates[0][0]
        following = []
        for s in symbols:
            try:
                line = int(s.get('line') or 0)
            except Exception:
                line = 0
            if line > start:
                following.append(line)
        end = min(following) - 1 if following else min(len(lines), start + 240)
        start_idx = max(0, start - 1)
        end_idx = max(start_idx + 1, min(len(lines), end))
        chunk = '\n'.join(lines[start_idx:end_idx])
        if len(chunk) > max_chars:
            chunk = chunk[:max_chars]
        return chunk, start, start + chunk.count('\n')

    pos = raw.find(name)
    if pos >= 0:
        half = max(1000, max_chars // 2)
        a = max(0, pos - half)
        b = min(len(raw), pos + half)
        start_line = raw.count('\n', 0, a) + 1
        end_line = raw.count('\n', 0, b) + 1
        return raw[a:b], start_line, end_line
    return '', 0, 0


def _file_read_infer_target_record(messages: list | None = None, *, function_name: str = '', query: str = '') -> tuple[dict | None, str]:
    """Safely infer a target file for reading existing context.

    This is not an intent router. It only helps the model read original context when
    the target file can be uniquely inferred from existing structural metadata.
    Saving edits still requires a concrete target filename returned from this read.
    """
    try:
        records, _heavy = _collect_history_file_records(messages or [])
    except Exception as e:
        return None, f'collect_records_failed:{type(e).__name__}:{e}'
    available: list[dict] = []
    seen: set[str] = set()
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        row = dict(rec)
        row['_path'] = _history_file_resolve_path(row)
        if not str(row.get('_path') or '').strip():
            continue
        key = _file_edit_record_key(row)
        if key in seen:
            continue
        seen.add(key)
        available.append(row)
    if not available:
        return None, 'target_file_not_found'

    name = str(function_name or '').strip()
    if name:
        leaf = name.split('.')[-1]
        symbol_matches: list[dict] = []
        for rec in available:
            symbols = rec.get('symbols') if isinstance(rec.get('symbols'), list) else []
            names = {str((s or {}).get('name') or '').strip() for s in symbols if isinstance(s, dict)}
            leafs = {n.split('.')[-1] for n in names if n}
            if name in names or leaf in leafs:
                symbol_matches.append(rec)
        if len(symbol_matches) == 1:
            return symbol_matches[0], ''
        if len(symbol_matches) > 1:
            labels = [str(r.get('filename') or r.get('saved_filename') or '') for r in symbol_matches[:8]]
            return None, 'ambiguous_target_file_by_symbol:' + ','.join(labels)

    # If the model did not pass target_filename, infer it from an explicitly
    # mentioned existing filename in the query/current user text. This is only a
    # structural disambiguation step for reading source text, not an intent rule.
    q = str(query or '').strip().lower()
    if q:
        file_matches: list[dict] = []
        for rec in available:
            try:
                names = [str(x or '').strip().lower() for x in (_file_edit_candidate_names(rec) or []) if str(x or '').strip()]
            except Exception:
                names = []
            hit = False
            for candidate in names:
                if candidate and candidate in q:
                    hit = True
                    break
            if hit:
                file_matches.append(rec)
        if len(file_matches) == 1:
            return file_matches[0], ''
        if len(file_matches) > 1:
            labels = [str(r.get('filename') or r.get('saved_filename') or '') for r in file_matches[:8]]
            return None, 'ambiguous_target_file_by_query:' + ','.join(labels)

    if len(available) == 1:
        return available[0], ''

    return None, 'missing_target_filename'



def _file_read_symbol_kind(record: dict | None = None, symbol_name: str = '') -> str:
    name = str(symbol_name or '').strip()
    if not name:
        return ''
    for s in ((record or {}).get('symbols') or []):
        if not isinstance(s, dict):
            continue
        nm = str(s.get('name') or '').strip()
        if nm == name or nm.split('.')[-1] == name:
            return str(s.get('kind') or '').strip().lower()
    return ''


def _file_read_is_callable_symbol(record: dict | None = None, symbol_name: str = '') -> bool:
    return _file_read_symbol_kind(record, symbol_name) in {'function', 'method', 'class', 'component'}


def _file_read_split_symbol_name(name: str) -> list[str]:
    raw = str(name or '').strip()
    if not raw:
        return []
    leaf = raw.split('.')[-1]
    spaced = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', leaf)
    parts = re.split(r'[^0-9A-Za-z]+', spaced)
    out = []
    for part in parts:
        part = str(part or '').strip().lower()
        if len(part) >= 2 and part not in out:
            out.append(part)
    joined = ''.join(out)
    if joined and joined not in out:
        out.append(joined)
    return out



def _file_read_collect_ranked_callable_context(record: dict | None = None, source_text: str = '', query: str = '', max_chars: int = 30000) -> tuple[str, int, int]:
    """Return one or more real callable/code blocks ranked for a behavior query.

    Generic coding-agent retrieval fallback: for a file edit, a tiny DOM id/class
    or selector is not enough context. Rank real callable blocks by name/body
    evidence from the user's request and return a compact bundle.
    """
    src = str(source_text or '')
    q = str(query or '')
    if not src.strip() or not q.strip():
        return '', 0, 0
    try:
        max_chars = max(2000, min(int(max_chars or 30000), 120000))
    except Exception:
        max_chars = 30000
    terms = _file_context_expanded_query_terms_for_code(q) or _history_file_query_terms(q)
    symbols = [dict(x) for x in ((record or {}).get('symbols') or []) if isinstance(x, dict)]
    if not symbols:
        try:
            symbols = _file_registry_extract_symbols(src, str((record or {}).get('filename') or (record or {}).get('saved_filename') or ''))
        except Exception:
            symbols = []
    scored = []
    behavior_query = bool(re.search(r'(修改|改成|新增|添加|删除|移除|修复|实现|显示|隐藏|渲染|提示|状态|为空|队列|列表|上传|文件|edit|modify|fix|add|delete|remove|show|display|render|empty|queue|list|upload|file)', q, flags=re.I))
    for sym in symbols:
        kind = str(sym.get('kind') or '').strip().lower()
        name = str(sym.get('name') or '').strip()
        if not name or kind not in {'function', 'method', 'class', 'component'}:
            continue
        try:
            block, start, end = _file_read_extract_symbol_window(src, record, name, min(max_chars, 24000))
        except Exception:
            block, start, end = '', 0, 0
        block = str(block or '').strip('\n')
        if len(block.strip()) < 80:
            continue
        name_l = name.lower()
        block_l = block.lower()
        name_tokens = set(_file_read_split_symbol_name(name))
        score = 0.0
        for term in terms:
            t = str(term or '').strip().lower()
            if not t or len(t) < 2:
                continue
            if t == name_l or t in name_tokens:
                score += 9.0
            elif t in name_l:
                score += 5.0
            hits = block_l.count(t)
            if hits:
                score += min(8, hits) * (1.2 + min(len(t), 12) * 0.08)
        if behavior_query and re.search(r'(appendChild|insertBefore|remove\s*\(|textContent\s*=|innerHTML\s*=|addEventListener|onclick\s*=|className\s*=|return\s+|\.length\b|if\s*\()', block):
            score += 4.0
        if score > 0:
            try:
                line = int(sym.get('line') or start or 0)
            except Exception:
                line = int(start or 0)
            scored.append((score, -line, name, block, int(start or line or 1), int(end or start or line or 1)))
    if not scored:
        return '', 0, 0
    scored.sort(reverse=True)
    chosen = []
    total = 0
    top = scored[0][0]
    for score, neg_line, name, block, start, end in scored[:6]:
        if chosen and score < max(2.0, top * 0.35):
            continue
        header = f"// ===== callable: {name} lines {start}-{end} score {score:.1f} =====\n"
        part = header + block.strip() + "\n"
        if chosen and total + len(part) > max_chars:
            continue
        chosen.append((part, start, end))
        total += len(part)
        if total >= max_chars:
            break
    if not chosen:
        return '', 0, 0
    text = '\n'.join(x[0] for x in chosen).strip()
    return text[:max_chars], chosen[0][1], chosen[-1][2]

def _file_read_infer_related_callable_symbol(record: dict | None = None, source_text: str = '', query: str = '') -> str:
    """Pick a likely callable context for a behavior-level query.

    This is a generic scorer inspired by coding-agent workflows: search the real
    code, prefer callable blocks with name/body evidence, and let the model use
    the returned exact text. It deliberately avoids project-specific mappings
    from one user phrase to one function or variable.
    """
    q = str(query or '').strip()
    src = str(source_text or '')
    if not q or not src:
        return ''
    terms = _file_context_expanded_query_terms_for_code(q)
    if not terms:
        return ''
    candidates = []
    for s in ((record or {}).get('symbols') or []):
        if not isinstance(s, dict):
            continue
        name = str(s.get('name') or '').strip()
        kind = str(s.get('kind') or '').strip().lower()
        if not name or kind not in {'function', 'method', 'class', 'component'}:
            continue
        try:
            block, _sl, _el = _file_read_extract_symbol_window(src, record, name, 12000)
        except Exception:
            block = ''
        if not block or len(str(block).strip()) < 120:
            continue
        name_l = name.lower()
        block_l = str(block or '').lower()
        score = 0.0
        name_tokens = _file_read_split_symbol_name(name)
        for term in terms:
            t = str(term or '').lower()
            if not t or len(t) < 2:
                continue
            if t == name_l or t in name_tokens:
                score += 7.0
            elif t in name_l:
                score += 4.0
            hits = block_l.count(t)
            if hits:
                score += min(5, hits) * (1.0 + min(len(t), 10) * 0.06)
        # Prefer blocks that actually mutate/render UI or data when the request
        # is behavior-oriented, but keep this generic across projects.
        if re.search(r'(显示|隐藏|点击|发送|上传|删除|添加|新增|移除|清空|切换|状态|提示|show|hide|send|upload|delete|remove|add|render|state)', q, flags=re.I):
            if re.search(r'(appendChild|insertBefore|remove\s*\(|textContent\s*=|innerHTML\s*=|addEventListener|onclick\s*=|return\s+)', block):
                score += 3.0
        if score > 0:
            candidates.append((score, -int(s.get('line') or 0), name))
    if not candidates:
        return ''
    candidates.sort(reverse=True)
    top_score, _neg_line, top_name = candidates[0]
    second = candidates[1][0] if len(candidates) > 1 else 0.0
    if top_score >= 7.0 and (top_score >= second + 1.5 or top_score >= 13.0):
        return top_name
    return ''

def _file_read_infer_symbol_name(record: dict | None = None, query: str = '') -> str:
    """从已选文件的符号元数据里，把模糊读取请求升级为明确符号读取。

    这里不判断用户意图、不保存文件，只在查询文本里明确出现且唯一匹配某个符号时，
    帮 sandbox_read_file/sandbox_run 定位真实函数体，而不是回退到普通片段。
    """
    q = str(query or '').strip()
    if not q:
        return ''
    symbols = [dict(s) for s in ((record or {}).get('symbols') or []) if isinstance(s, dict) and str((s or {}).get('name') or '').strip()]
    if not symbols:
        return ''
    found: list[str] = []
    q_lower = q.lower()
    for s in symbols:
        name = str(s.get('name') or '').strip()
        if not name:
            continue
        leaf = name.split('.')[-1]
        candidates = []
        for item in (name, leaf):
            item = str(item or '').strip()
            if item and item not in candidates:
                candidates.append(item)
        hit = False
        for cand in candidates:
            c_lower = cand.lower()
            if not c_lower:
                continue
            if re.search(r'(?<![0-9A-Za-z_])' + re.escape(c_lower) + r'(?![0-9A-Za-z_])', q_lower):
                hit = True
                break
        if hit and name not in found:
            found.append(name)
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        found_sorted = sorted(found, key=lambda x: len(x), reverse=True)
        top = found_sorted[0]
        if all((other == top) or top.endswith('.' + other) or other in top for other in found_sorted[1:]):
            return top
    return ''



def _file_read_query_is_narrow_selector_or_filename(text: str) -> bool:
    """Return true for query strings that are only structural anchors.

    Examples: "#fileQueue", ".item", "index.html". Such anchors are useful,
    but they are not enough to retrieve editable runtime code for an existing
    file edit. They should be combined with the current user request.
    """
    q = str(text or '').strip()
    if not q:
        return False
    q_one = re.sub(r'\s+', ' ', q).strip()
    if len(q_one) <= 80 and re.fullmatch(r'[#.][A-Za-z0-9_-]+', q_one):
        return True
    if len(q_one) <= 120 and re.fullmatch(r'[A-Za-z0-9_.\- /\\]+\.(?:html?|css|js|ts|tsx|jsx|py|json|md|txt|yml|yaml|xml)', q_one, flags=re.I):
        return True
    if len(q_one) <= 80 and not _file_read_query_needs_runtime_code_context(q_one):
        return True
    return False
