# Sandbox run runtime helpers. Loaded after file_registry_edit_tools_part.py so shared helpers stay available.

def _sandbox_run_snapshot_files(root: str = '') -> dict:
    out: dict[str, tuple[int, int]] = {}
    root_abs = os.path.abspath(str(root or ''))
    if not root_abs or not os.path.isdir(root_abs):
        return out
    skip_dirs = {'.git', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'node_modules', '.venv', 'venv'}
    max_files = _sandbox_cfg_int('SANDBOX_RUN_SNAPSHOT_MAX_FILES', 6000, min_value=200, max_value=50000)
    try:
        for dirpath, dirnames, filenames in os.walk(root_abs):
            dirnames[:] = [d for d in dirnames if str(d or '') not in skip_dirs]
            for name in filenames:
                if len(out) >= max_files:
                    return out
                fp = os.path.join(dirpath, name)
                try:
                    st = os.stat(fp)
                    rel = os.path.relpath(fp, root_abs).replace('\\', '/')
                    if rel.startswith('../') or rel == '..':
                        continue
                    out[rel] = (int(st.st_mtime_ns), int(st.st_size))
                except Exception:
                    continue
    except Exception:
        return out
    return out


def _sandbox_run_changed_paths(before: dict | None = None, after: dict | None = None) -> tuple[list[str], list[str], list[str]]:
    b = before if isinstance(before, dict) else {}
    a = after if isinstance(after, dict) else {}
    created: list[str] = []
    changed: list[str] = []
    for rel, meta in a.items():
        key = str(rel or '').strip()
        if not key:
            continue
        if key not in b:
            created.append(key)
        elif b.get(key) != meta:
            changed.append(key)
    created.sort()
    changed.sort()
    output = []
    seen: set[str] = set()
    for rel in created + changed:
        low = rel.lower()
        if low in seen:
            continue
        seen.add(low)
        output.append(rel)
    return created, changed, output


def _sandbox_run_strip_code_fence(value: str = '') -> tuple[str, str]:
    raw = str(value or '').strip()
    if not raw.startswith('```'):
        return raw, ''
    m = re.match(r"(?s)^```([A-Za-z0-9_+\-#.]*)\s*\n(.*?)\n?```\s*$", raw)
    if not m:
        return raw, ''
    return str(m.group(2) or '').strip('\n'), str(m.group(1) or '').strip().lower()


def _sandbox_run_unwrap_stdin_heredoc(value: str = '') -> tuple[str, str, bool, str]:
    """If code/stdin accidentally contains a shell heredoc wrapper, return its body.

    ChatGPT-style execution should pass only the Python/Node/Shell program in the
    tool's code/stdin field.  Some models still emit a visible shell wrapper such
    as ``python3 - <<'PY'`` inside that code field.  Feeding that whole wrapper to
    ``python3 -`` makes Python parse shell syntax.  Strip only well-formed,
    interpreter heredocs so normal Python text is not touched.
    """
    text = str(value or '').strip()
    if not text or '\n' not in text:
        return text, '', False, ''
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    first_idx = -1
    first = ''
    for idx, line in enumerate(lines):
        if str(line or '').strip():
            first_idx = idx
            first = str(line or '').strip()
            break
    if first_idx < 0:
        return text, '', False, ''
    m = re.match(r"(?i)^\s*(python3|python|py|node|nodejs|sh|bash)\b.*?(?:-|\-s)?\s*<<\s*([\"']{0,3})([A-Za-z_][A-Za-z0-9_]*)\2\s*$", first)
    if not m:
        return text, '', False, ''
    exe = str(m.group(1) or '').strip().lower()
    marker = str(m.group(3) or '').strip()
    end_idx = -1
    for idx in range(len(lines) - 1, first_idx, -1):
        tail = str(lines[idx] or '').strip().strip('"\'')
        if tail == marker:
            end_idx = idx
            break
    if end_idx <= first_idx:
        return text, '', False, ''
    # Allow only whitespace after the closing marker.  This avoids swallowing
    # compound shell scripts where the heredoc is just one step among many.
    if any(str(line or '').strip() for line in lines[end_idx + 1:]):
        return text, '', False, ''
    body = '\n'.join(lines[first_idx + 1:end_idx]).strip('\n')
    if exe in {'python3', 'python', 'py'}:
        return body, 'python3 -', True, 'stdin_python_heredoc_wrapper_unwrapped'
    if exe in {'node', 'nodejs'}:
        return body, 'node -', True, 'stdin_node_heredoc_wrapper_unwrapped'
    return body, 'sh -s', True, 'stdin_shell_heredoc_wrapper_unwrapped'


def _sandbox_run_language_command(language: str = '', code_text: str = '') -> tuple[str, str]:
    lang = str(language or '').strip().lower()
    if lang in {'py', 'python', 'python3'}:
        return 'python3 -', 'code_language_python'
    if lang in {'js', 'javascript', 'node', 'nodejs'}:
        return 'node -', 'code_language_node'
    if lang in {'sh', 'shell', 'bash'}:
        return 'sh -s', 'code_language_shell'
    code = str(code_text or '').lstrip()
    if code.startswith(('import ', 'from ', 'def ', 'class ')) or re.search(r'\b(openpyxl|pandas|json|os|pathlib|difflib)\b', code[:1200]):
        return 'python3 -', 'code_language_inferred_python'
    return 'sh -s', 'code_language_inferred_shell'


def _sandbox_run_effective_language(language: str = '', command_text: str = '', stdin_text: str = '') -> str:
    """Return the runtime language used for stdin/code based sandbox_run calls."""
    lang = str(language or '').strip().lower()
    cmd = str(command_text or '').strip().lower()
    code = str(stdin_text or '').lstrip()
    if lang in {'py', 'python', 'python3'}:
        return 'python'
    if lang in {'js', 'javascript', 'node', 'nodejs'}:
        return 'node'
    if lang in {'sh', 'shell', 'bash'}:
        return 'shell'
    if re.match(r'^(python3|python|py)(\s+-|\s*$)', cmd):
        return 'python'
    if re.match(r'^(node|nodejs)(\s+-|\s*$)', cmd):
        return 'node'
    if re.match(r'^(sh|bash)\s+-s\b', cmd):
        return 'shell'
    if code.startswith(('import ', 'from ', 'def ', 'class ')) or re.search(r'\b(openpyxl|pandas|json|os|pathlib|difflib)\b', code[:1200]):
        return 'python'
    return 'shell'


def _sandbox_run_shell_quote(value: str = '') -> str:
    try:
        return __import__('shlex').quote(str(value or ''))
    except Exception:
        text = str(value or '')
        return "'" + text.replace("'", "'\"'\"'") + "'"


def _sandbox_run_cmd_display(parts) -> str:
    values = [str(x) for x in (parts or []) if str(x or '').strip()]
    if callable(globals().get('_code_run_cmd_display')):
        try:
            return _code_run_cmd_display(values)
        except Exception:
            pass
    return ' '.join(_sandbox_run_shell_quote(x) for x in values)


def _sandbox_run_shell_join(parts) -> str:
    values = [str(x) for x in (parts or []) if str(x or '').strip()]
    try:
        return __import__('shlex').join(values)
    except Exception:
        return ' '.join(_sandbox_run_shell_quote(x) for x in values)


def _sandbox_run_heredoc_marker(prefix: str = 'PY', body: str = '') -> str:
    base = re.sub(r'[^A-Za-z0-9_]+', '', str(prefix or 'EOF').upper()) or 'EOF'
    lines = {str(line or '').strip() for line in str(body or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')}
    if base not in lines:
        return base
    for idx in range(1, 100):
        marker = f'{base}_{idx}'
        if marker not in lines:
            return marker
    return base + '_' + hashlib.sha1(str(body or '').encode('utf-8', 'ignore')).hexdigest()[:8].upper()


def _sandbox_run_stdin_shell_command(language: str = '', command_text: str = '', stdin_text: str = '') -> tuple[str, str]:
    lang = _sandbox_run_effective_language(language, command_text, stdin_text)
    if lang == 'python':
        return 'python3 -P -', 'python'
    if lang == 'node':
        return 'node -', 'javascript'
    return 'bash -s', 'shell'


def _sandbox_run_is_shell_lc_head(values) -> bool:
    if not isinstance(values, (list, tuple)) or len(values) < 2:
        return False
    exe = str(values[0] or '').strip().rsplit('/', 1)[-1].lower()
    return exe in {'bash', 'sh'} and str(values[1] or '').strip().lower() == '-lc'


def _sandbox_run_unwrap_bash_lc_command(command_text: str = '') -> str:
    """Return the real script inside one or more ``bash -lc`` wrappers.

    The Activity panel and the Docker runner both use bash -lc as the single
    outer execution boundary.  Models may still send an already-wrapped command
    like ``bash -lc 'echo ok'`` or even a nested wrapper.  Canonicalising here
    prevents ``bash -lc 'bash -lc ...'`` from accumulating and makes the command
    identity stable for start/done activity events.
    """
    text = str(command_text or '').strip()
    if not text:
        return ''
    for _ in range(6):
        try:
            parts = __import__('shlex').split(text)
        except Exception:
            parts = []
        if not _sandbox_run_is_shell_lc_head(parts):
            return text
        if len(parts) < 3:
            return ''
        if len(parts) == 3:
            next_text = str(parts[2] or '').strip()
        else:
            # Be forgiving for model drift such as: bash -lc echo ONE
            # The shell would treat ONE as $0, but the user's intent is almost
            # always to run ``echo ONE`` as the command body.
            next_text = _sandbox_run_shell_join(parts[2:]).strip()
        if not next_text or next_text == text:
            return next_text
        text = next_text
    return text


def _sandbox_run_argv_to_shell_command(argv) -> str:
    values = [str(x) for x in (argv or []) if str(x or '').strip()]
    if not values:
        return ''
    if _sandbox_run_is_shell_lc_head(values):
        if len(values) < 3:
            return ''
        if len(values) == 3:
            return _sandbox_run_unwrap_bash_lc_command(values[2])
        return _sandbox_run_unwrap_bash_lc_command(_sandbox_run_shell_join(values[2:]))
    return _sandbox_run_shell_join(values)


def _sandbox_run_canonical_shell_command(command_text: str = '', argv=None) -> str:
    if isinstance(argv, list):
        return _sandbox_run_argv_to_shell_command(argv).strip()
    return _sandbox_run_unwrap_bash_lc_command(str(command_text or '').strip()).strip()


def _sandbox_run_bash_display_command(shell_command: str = '', stdin_text: str = '', language: str = '') -> str:
    cmd = _sandbox_run_canonical_shell_command(shell_command)
    code = str(stdin_text or '')
    if code:
        lang = _sandbox_run_effective_language(language, cmd, code)
        body = _sandbox_run_truncate_activity_code(code)
        if lang == 'python':
            marker = _sandbox_run_heredoc_marker('PY', body)
            script = f"python3 -P - <<'{marker}'\n{body}\n{marker}"
        elif lang == 'node':
            marker = _sandbox_run_heredoc_marker('JS', body)
            script = f"node - <<'{marker}'\n{body}\n{marker}"
        else:
            marker = _sandbox_run_heredoc_marker('SH', body)
            script = f"bash -s <<'{marker}'\n{body}\n{marker}"
        return 'bash -lc ' + _sandbox_run_shell_quote(script)
    return 'bash -lc ' + _sandbox_run_shell_quote(cmd) if cmd else ''


def _sandbox_run_unified_bash_runner(command_text: str = '', stdin_text: str = '', language: str = '', argv=None) -> tuple[list[str], str, str, str]:
    """Return (argv, stdin, display_command, command_language) for the single sandbox runner.

    There is one outer runtime shape only: ``bash -lc <script>``.  Already
    wrapped inputs are unwrapped first, so neither execution nor Activity can
    drift into ``bash -lc 'bash -lc ...'``.  Code/stdin payloads are still sent
    through stdin for reliability while Activity shows an equivalent heredoc.
    """
    stdin_value = str(stdin_text or '')
    if stdin_value:
        shell_command, command_language = _sandbox_run_stdin_shell_command(language, command_text, stdin_value)
        shell_command = _sandbox_run_canonical_shell_command(shell_command)
        return ['bash', '-lc', shell_command], stdin_value, _sandbox_run_bash_display_command(shell_command, stdin_value, command_language), command_language
    shell_command = _sandbox_run_canonical_shell_command(command_text, argv if isinstance(argv, list) else None)
    return ['bash', '-lc', shell_command], '', _sandbox_run_bash_display_command(shell_command), 'shell'


def _sandbox_run_operation_key(command_text: str = '', stdin_text: str = '', argv=None) -> str:
    canonical_cmd = _sandbox_run_canonical_shell_command(command_text, argv if isinstance(argv, list) else None)
    basis = 'cmd:' + canonical_cmd
    if stdin_text:
        try:
            stdin_hash = hashlib.sha1(str(stdin_text or '').encode('utf-8', 'ignore')).hexdigest()[:16]
        except Exception:
            stdin_hash = str(abs(hash(str(stdin_text or ''))))[:16]
        basis += '|stdin:' + stdin_hash
    try:
        return hashlib.sha1(basis.encode('utf-8', 'ignore')).hexdigest()[:16]
    except Exception:
        return str(abs(hash(basis)))[:16]


def _sandbox_run_activity_code_limit() -> int:
    try:
        return max(2000, min(int(app_getenv('SANDBOX_ACTIVITY_CODE_MAX_CHARS', '20000') or 20000), 80000))
    except Exception:
        return 20000


def _sandbox_run_truncate_activity_code(code_text: str = '') -> str:
    text = str(code_text or '').rstrip('\n')
    limit = _sandbox_run_activity_code_limit()
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[:limit].rstrip('\n') + f"\n# ... truncated {omitted} chars in activity view; full code was sent to the sandbox."


def _sandbox_run_display_command(command_text: str = '', stdin_text: str = '', language: str = '', argv=None) -> str:
    """Build the user-facing command shown in Activity.

    Match the unified execution contract: every sandbox command is displayed as
    a bash -lc invocation; Python/Node/Shell code is represented as a heredoc
    inside that shell command, even though the full code is streamed to Docker
    stdin internally.
    """
    code = str(stdin_text or '')
    if code:
        shell_command, command_language = _sandbox_run_stdin_shell_command(language, command_text, code)
        return _sandbox_run_bash_display_command(shell_command, code, command_language)
    if isinstance(argv, list) and argv:
        return _sandbox_run_bash_display_command(_sandbox_run_shell_join(argv))
    return _sandbox_run_bash_display_command(str(command_text or '').strip())


def _sandbox_run_display_command_from_args(args: dict | None = None, result: dict | None = None) -> str:
    args = dict(args or {}) if isinstance(args, dict) else {}
    result = dict(result or {}) if isinstance(result, dict) else {}
    if result.get('display_command'):
        return str(result.get('display_command') or '').strip()
    raw_code = args.get('code')
    if raw_code is None:
        raw_code = args.get('python_code')
    if raw_code is None:
        raw_code = args.get('script')
    stdin_text = str(args.get('stdin') if args.get('stdin') is not None else args.get('stdin_text') if args.get('stdin_text') is not None else raw_code if raw_code is not None else '')
    command_text = str(args.get('command') or result.get('real_command') or result.get('command') or '').strip()
    language = str(args.get('language') or args.get('lang') or result.get('language') or '').strip()
    argv = args.get('argv') if isinstance(args.get('argv'), list) else result.get('argv') if isinstance(result.get('argv'), list) else None
    if stdin_text:
        command_text, stdin_text, _, _ = _sandbox_run_normalize_stdin_command(command_text, stdin_text, language)
    if isinstance(argv, list):
        normalized_argv, _, _ = _sandbox_run_normalize_argv(argv, stdin_text, language)
        argv = normalized_argv if isinstance(normalized_argv, list) else argv
    return _sandbox_run_display_command(command_text, stdin_text, language, argv)


def _sandbox_run_progress_language(args: dict | None = None, result: dict | None = None, command_text: str = '') -> str:
    args = dict(args or {}) if isinstance(args, dict) else {}
    result = dict(result or {}) if isinstance(result, dict) else {}
    lang = str(args.get('language') or args.get('lang') or result.get('language') or '').strip().lower()
    if lang in {'python', 'py'}:
        return 'python'
    if lang in {'javascript', 'js', 'node', 'nodejs'}:
        return 'javascript'
    if lang in {'shell', 'sh', 'bash'}:
        return 'shell'
    if args.get('code') is not None or args.get('python_code') is not None:
        return 'python'
    text = str(command_text or result.get('display_command') or result.get('real_command') or result.get('command') or args.get('command') or '').strip()
    inner = _sandbox_run_unwrap_bash_lc_command(text)
    probe = (inner or text).strip().lower()
    # Activity commands are displayed and executed through bash -lc.  Keep the
    # panel title based on the payload language, not merely the outer shell.
    if re.match(r"^(?:python3?|py)(?:\s|$)", probe) or re.search(r"\bpython3?\s+(?:-p\s+)?-\b", probe):
        return 'python'
    if re.match(r"^(?:node|nodejs)(?:\s|$)", probe) or re.search(r"\b(?:node|nodejs)\s+-\b", probe):
        return 'javascript'
    if re.match(r"^(?:bash|sh)(?:\s|$)", probe):
        return 'shell'
    return 'shell' if probe else ''



def _sandbox_run_progress_operation_key_from_args_result(args: dict | None = None, result: dict | None = None) -> str:
    """Return the same logical sandbox_run operation key for start and done frames."""
    args = dict(args or {}) if isinstance(args, dict) else {}
    result = dict(result or {}) if isinstance(result, dict) else {}
    call_identity = str(
        args.get('_activity_call_id') or args.get('_tool_call_id') or args.get('tool_call_id') or
        result.get('_activity_call_id') or result.get('_tool_call_id') or result.get('tool_call_id') or ''
    ).strip()
    if call_identity:
        try:
            return ('call:' + hashlib.sha1(call_identity.encode('utf-8', 'ignore')).hexdigest()[:16])[:80]
        except Exception:
            return ('call:' + call_identity)[:80]
    existing = str(result.get('operation_key') or result.get('operationKey') or '').strip()
    if existing:
        return existing
    raw_code = args.get('code')
    if raw_code is None:
        raw_code = args.get('python_code')
    if raw_code is None:
        raw_code = args.get('script')
    language = str(args.get('language') or args.get('lang') or result.get('language') or '').strip()
    stdin_text = str(
        args.get('stdin') if args.get('stdin') is not None else
        args.get('stdin_text') if args.get('stdin_text') is not None else
        raw_code if raw_code is not None else ''
    )
    command_text = str(args.get('command') or result.get('real_command') or result.get('command') or '').strip()
    try:
        command_text, stdin_text, _, _ = _sandbox_run_normalize_stdin_command(command_text, stdin_text, language)
    except Exception:
        pass
    argv_for_key = args.get('argv') if isinstance(args.get('argv'), list) else result.get('argv') if isinstance(result.get('argv'), list) else None
    if isinstance(argv_for_key, list):
        try:
            normalized_argv_for_key, _, _ = _sandbox_run_normalize_argv(argv_for_key, stdin_text, language)
            argv_for_key = normalized_argv_for_key if isinstance(normalized_argv_for_key, list) else argv_for_key
            hardened_argv_for_key, _, _ = _sandbox_run_harden_python_argv(argv_for_key)
            argv_for_key = hardened_argv_for_key if isinstance(hardened_argv_for_key, list) else argv_for_key
        except Exception:
            pass
        return _sandbox_run_operation_key(command_text, stdin_text, argv_for_key)
    return _sandbox_run_operation_key(command_text, stdin_text, None)


def _sandbox_run_progress_captured_output(result: dict | None = None) -> str:
    """Build an official-style single output block for sandbox Python failures."""
    result = dict(result or {}) if isinstance(result, dict) else {}
    cmd = str(result.get('real_command') or result.get('command') or result.get('display_command') or '').strip()
    exit_code = result.get('exit_code')
    stdout = str(result.get('stdout') or '').replace('\r\n', '\n').replace('\r', '\n').strip('\n')
    stderr = str(result.get('stderr') or '').replace('\r\n', '\n').replace('\r', '\n').strip('\n')
    lines = []
    if cmd:
        lines.append('command: ' + cmd)
    if exit_code is not None:
        lines.append('exit_code: ' + str(exit_code))
    lines.append('--- stdout ---')
    if stdout:
        lines.append(stdout)
    lines.append('--- stderr ---')
    if stderr:
        lines.append(stderr)
    return '\n'.join(lines).rstrip()

def _sandbox_run_progress_labels(args: dict | None = None, result: dict | None = None, command_text: str = '') -> tuple[str, str, str, str]:
    """Return user-facing activity labels without changing sandbox execution."""
    args = dict(args or {}) if isinstance(args, dict) else {}
    result = dict(result or {}) if isinstance(result, dict) else {}
    if result.get('skipped_by_policy'):
        return ('正在选择更合适的文件工具', '已跳过不必要的代码运行', 'sandbox_run_skipped', '')

    output_count = 0
    try:
        output_count = max(
            len(result.get('output_paths') or []),
            len(result.get('created_paths') or []),
            len(result.get('changed_paths') or []),
            int(result.get('output_file_count') or 0),
        )
    except Exception:
        output_count = 0
    if output_count > 0:
        return ('正在生成沙盒文件', '已生成沙盒文件', 'sandbox_run_outputs', f'文件变更 {output_count} 项')

    cmd = str(command_text or result.get('display_command') or result.get('real_command') or result.get('command') or args.get('command') or '').strip()
    raw = re.sub(r'\s+', ' ', cmd).strip().lower()
    lang = _sandbox_run_progress_language(args, result, cmd)
    argv = args.get('argv') if isinstance(args.get('argv'), list) else result.get('argv') if isinstance(result.get('argv'), list) else []
    argv_text = ' '.join(str(x or '') for x in argv).strip().lower() if isinstance(argv, list) else ''
    basis = raw or argv_text
    inner_basis = _sandbox_run_unwrap_bash_lc_command(basis)
    if inner_basis:
        basis = re.sub(r'\s+', ' ', inner_basis).strip().lower()
    first = ''
    if basis:
        m = re.match(r"^(?:/usr/bin/env\s+)?([./\w-]+)", basis)
        first = (m.group(1).rsplit('/', 1)[-1] if m else '').strip()

    if first in {'ls', 'dir'}:
        return ('正在列出沙盒文件', '已列出沙盒文件', 'sandbox_run_list_files', '')
    if first == 'find':
        return ('正在查找文件路径', '已查找文件路径', 'sandbox_run_find_files', '')
    if first in {'rg', 'grep', 'ag'}:
        return ('正在搜索文件内容', '已搜索文件内容', 'sandbox_run_search_files', '')
    if first == 'diff' or basis.startswith('git diff'):
        return ('正在检查文件差异', '已检查文件差异', 'sandbox_run_diff', '')
    if 'pytest' in basis or re.search(r'\b(?:npm|pnpm|yarn)\s+(?:run\s+)?test\b', basis):
        return ('正在运行测试', '已运行测试', 'sandbox_run_tests', '')
    if lang == 'python':
        try:
            code = int(result.get('exit_code')) if result.get('exit_code') is not None else 0
        except Exception:
            code = 0
        if code != 0 or bool(result.get('timed_out')):
            return ('执行 Python 命令并捕获输出', '执行错误的 Python 命令并捕获输出', 'sandbox_run_python_capture', '')
        return ('执行 Python 命令并捕获输出', '执行 Python 命令并捕获输出', 'sandbox_run_python_capture', '')
    if lang == 'javascript':
        return ('正在运行脚本', '已运行脚本', 'sandbox_run_script', '')
    return ('正在运行沙盒检查', '已运行沙盒检查', 'sandbox_run_check', '')


def _sandbox_run_normalize_stdin_command(command_text: str = '', stdin_text: str = '', language: str = '') -> tuple[str, str, bool, str]:
    text = str(command_text or '').strip()
    current_stdin, fenced_lang = _sandbox_run_strip_code_fence(str(stdin_text or ''))
    lang = str(language or fenced_lang or '').strip().lower()
    if current_stdin:
        unwrapped_stdin, unwrapped_cmd, did_unwrap, unwrap_reason = _sandbox_run_unwrap_stdin_heredoc(current_stdin)
        if did_unwrap:
            current_stdin = unwrapped_stdin
            if not text or re.match(r"(?i)^\s*(python3|python|py|node|nodejs|sh|bash)\b(?:\s+[-\w]+)*\s*$", text):
                return unwrapped_cmd, current_stdin, True, unwrap_reason

        if not text:
            cmd, reason = _sandbox_run_language_command(lang, current_stdin)
            return cmd, current_stdin, True, reason + '_from_stdin'
        if re.match(r"(?i)^\s*(python3|python|py)\s*$", text):
            exe = re.match(r"(?i)^\s*(python3|python|py)\s*$", text).group(1)
            return f'{exe} -', current_stdin, True, 'python_stdin_dash_added'
        m_py_c = re.match(r"(?i)^\s*(python3|python|py)\s+-c\s*$", text)
        if m_py_c:
            return f'{m_py_c.group(1)} -', current_stdin, True, 'python_c_missing_arg_to_stdin'
        if re.match(r"(?i)^\s*(node|nodejs)\s*$", text):
            return 'node -', current_stdin, True, 'node_stdin_dash_added'
        if re.match(r"(?i)^\s*(bash|sh)\s*$", text):
            return text + ' -s', current_stdin, True, 'shell_stdin_s_added'
        return text, current_stdin, False, ''
    text, fenced_lang = _sandbox_run_strip_code_fence(text)
    if fenced_lang and not lang:
        lang = fenced_lang
        if text:
            cmd, reason = _sandbox_run_language_command(lang, text)
            return cmd, text, True, reason + '_from_command_fence'
    if not text:
        return text, current_stdin, False, ''
    m_py_c_no_stdin = re.match(r"(?i)^\s*(python3|python|py)\s+-c\s*$", text)
    if m_py_c_no_stdin:
        return text, current_stdin, False, 'python_c_missing_arg'
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    if re.match(r"^\s*-c(?:\s+|$)", text):
        return 'python3 ' + text, current_stdin, True, 'python_c_missing_executable'
    if re.match(r"^\s*-\s*$", text):
        return 'python3 -', current_stdin, True, 'python_stdin_missing_executable'
    if len(lines) >= 2:
        first_nonempty = ''
        for line in lines:
            first_nonempty = str(line or '').strip()
            if first_nonempty:
                break
        if first_nonempty.startswith(('import ', 'from ')):
            return 'python3 -', text, True, 'python_program_text_to_stdin'
    if len(lines) < 3:
        return text, current_stdin, False, ''
    head = str(lines[0] or '').strip()
    m_cat = re.search(r"(?i)^cat\s*>\s*(\S+?\.py)\s*<<\s*([\"']{0,3})([A-Za-z_][A-Za-z0-9_]*)\2", head)
    if m_cat:
        marker = str(m_cat.group(3) or '').strip()
        end_idx = -1
        for idx in range(1, len(lines)):
            tail = str(lines[idx] or '').strip().strip('"\'')
            if tail == marker:
                end_idx = idx
                break
        if end_idx > 1:
            body = '\n'.join(lines[1:end_idx])
            rest = '\n'.join(lines[end_idx + 1:]).strip()
            if (not rest) or re.search(r"(?i)\b(python3|python|py)\b\s+\S+?\.py\b", rest):
                return 'python3 -', body, True, 'cat_python_heredoc_to_stdin'
    m = re.search(r"(?i)\b(python3|python|py)\b.*-\s*<<\s*([\"']{0,3})([A-Za-z_][A-Za-z0-9_]*)\2", head)
    if not m:
        return text, current_stdin, False, ''
    exe = str(m.group(1) or 'python3').strip() or 'python3'
    marker = str(m.group(3) or '').strip()
    end_idx = -1
    for idx in range(len(lines) - 1, 0, -1):
        tail = str(lines[idx] or '').strip().strip('"\'')
        if tail == marker:
            end_idx = idx
            break
    if end_idx <= 1:
        return text, current_stdin, False, ''
    body = '\n'.join(lines[1:end_idx])
    return f'{exe} -', body, True, 'python_heredoc_to_stdin'



def _sandbox_run_harden_python_argv(argv) -> tuple[list[str] | None, bool, str]:
    """Add official-style safe-path flags to Python argv when safe to do so.

    ChatGPT Code Interpreter sends code to an interpreter sandbox; it should not
    depend on the current working directory being inserted before stdlib/site
    packages.  Python's -P flag (and PYTHONSAFEPATH env below) prevents local
    files such as inspect.py/json.py/copy.py from shadowing stdlib imports.
    """
    if not isinstance(argv, list) or not argv:
        return argv, False, ''
    out = [str(x) for x in argv if str(x or '').strip()]
    if not out:
        return out, False, ''
    exe = str(out[0] or '').strip().lower()
    if exe not in {'python3', 'python', 'py'}:
        return out, False, ''
    # Do not duplicate the flag.  Place it after executable and before -/-c/script.
    if any(str(x or '').strip() == '-P' for x in out[1:]):
        return out, False, ''
    return [out[0], '-P', *out[1:]], True, 'python_safe_path_flag_added'

def _sandbox_run_normalize_argv(argv, stdin_text: str = '', language: str = '') -> tuple[list[str] | None, bool, str]:
    if not isinstance(argv, list):
        return None, False, ''
    out = [str(x) for x in argv if str(x or '').strip()]
    if not out:
        return [], False, ''
    stdin_present = bool(str(stdin_text or ''))
    first = str(out[0] or '').strip()
    first_l = first.lower()

    def _is_python_exe(value: str) -> bool:
        return str(value or '').strip().lower() in {'python3', 'python', 'py'}

    def _python_c_missing_arg(values: list[str]) -> bool:
        if not values:
            return False
        if _is_python_exe(values[0]):
            return len(values) >= 2 and str(values[1] or '').strip() == '-c' and len(values) == 2
        return str(values[0] or '').strip() == '-c' and len(values) == 1

    # Official-style code execution sends the program as stdin/code.  In that
    # mode ``python3 -c`` is invalid because Python expects the code as the next
    # argv item, not on stdin.  Normalize it to ``python3 -`` so stdin is read.
    if stdin_present:
        if _python_c_missing_arg(out):
            exe = out[0] if _is_python_exe(out[0]) else 'python3'
            return [exe, '-'], True, 'argv_python_c_missing_arg_to_stdin'
        if len(out) == 1 and _is_python_exe(out[0]):
            return [out[0], '-'], True, 'argv_python_stdin_dash_added'
        if first_l in {'-c', '-'} or first_l.startswith('-c '):
            return ['python3', '-'], True, 'argv_python_stdin_missing_executable'

    if first_l in {'-c', '-'} or first_l.startswith('-c '):
        return ['python3', *out], True, 'argv_python_missing_executable'
    return out, False, ''


def _sandbox_run_argv_python_c_missing_arg(argv) -> bool:
    if not isinstance(argv, list):
        return False
    values = [str(x) for x in argv if str(x or '').strip()]
    if not values:
        return False
    first = values[0].strip().lower()
    if first in {'python3', 'python', 'py'}:
        return len(values) == 2 and values[1].strip() == '-c'
    return len(values) == 1 and values[0].strip() == '-c'
