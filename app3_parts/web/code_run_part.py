# code runtime aliases, Sandbox Runner probes, and execution result shaping.

def _ext_of(filename: str) -> str:
    name = (filename or "").lower()
    for e in sorted(ALLOWED_EXT, key=len, reverse=True):
        if name.endswith(e):
            return e
    return ""


def truncate_text(s: str, max_chars: int = 20000) -> str:
    s = (s or "").strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "\n\n[已截断：内容过长]"




CODE_RUN_LANGUAGE_ALIASES = {
    'py': 'python',
    'python': 'python',
    'python3': 'python',
    'js': 'javascript',
    'javascript': 'javascript',
    'node': 'javascript',
    'nodejs': 'javascript',
    'mjs': 'javascript',
    'cjs': 'javascript',
    'ts': 'typescript',
    'tsx': 'typescript',
    'typescript': 'typescript',
    'bash': 'bash',
    'shell': 'bash',
    'sh': 'bash',
    'zsh': 'bash',
    'ps1': 'powershell',
    'pwsh': 'powershell',
    'powershell': 'powershell',
    'c': 'c',
    'cc': 'cpp',
    'cpp': 'cpp',
    'cxx': 'cpp',
    'c++': 'cpp',
    'go': 'go',
    'golang': 'go',
    'rs': 'rust',
    'rust': 'rust',
    'java': 'java',
    'php': 'php',
    'rb': 'ruby',
    'ruby': 'ruby',
    'pl': 'perl',
    'perl': 'perl',
    'lua': 'lua',
    'r': 'r',
    'swift': 'swift',
    'dart': 'dart',
}

CODE_RUN_LANGUAGE_LABELS = {
    'python': 'Python',
    'javascript': 'JavaScript',
    'typescript': 'TypeScript',
    'bash': 'Shell',
    'powershell': 'PowerShell',
    'c': 'C',
    'cpp': 'C++',
    'go': 'Go',
    'rust': 'Rust',
    'java': 'Java',
    'php': 'PHP',
    'ruby': 'Ruby',
    'perl': 'Perl',
    'lua': 'Lua',
    'r': 'R',
    'swift': 'Swift',
    'dart': 'Dart',
}

CODE_RUN_SUPPORTED_CANONICAL = tuple(CODE_RUN_LANGUAGE_LABELS.keys())


def _code_run_normalize_language(language: str) -> str:
    raw = str(language or '').strip().lower()
    if raw.startswith('language-'):
        raw = raw.split('-', 1)[1].strip()
    return CODE_RUN_LANGUAGE_ALIASES.get(raw, raw)


def _code_run_truncate_output(text: str, max_chars: int) -> str:
    raw = str(text or '')
    limit = max(2000, int(max_chars or 0))
    if len(raw) <= limit:
        return raw
    keep_head = max(800, limit // 2)
    keep_tail = max(400, limit - keep_head - 80)
    omitted = len(raw) - keep_head - keep_tail
    return raw[:keep_head] + f'\n\n...[已截断 {omitted} 个字符]...\n\n' + raw[-keep_tail:]


def _code_run_detect_java_class_name(code: str) -> str:
    text = str(code or '')
    for pattern in (
        r'public\s+class\s+([A-Za-z_][A-Za-z0-9_]*)',
        r'class\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{',
    ):
        m = re.search(pattern, text)
        if m:
            return str(m.group(1) or '').strip() or 'Main'
    return 'Main'


def _code_run_write_text(path: str, content: str) -> None:
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(str(content or ''))


_CODE_RUN_SANDBOX_RUNTIME_CACHE = {'ts': 0.0, 'matrix': None}


def _code_run_sandbox_backend_status() -> tuple[bool, str]:
    fn = globals().get('_sandbox_backend_status')
    if not callable(fn):
        return False, 'sandbox_backend_unavailable'
    try:
        ok, err = fn()
        return bool(ok), str(err or '')
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


def _code_run_sandbox_call(args: dict | None = None) -> dict:
    fn = globals().get('_sandbox_run_tool')
    if not callable(fn):
        return {'ok': False, 'error': 'sandbox_run_unavailable'}
    try:
        return dict(fn(dict(args or {}), messages=[] ) or {})
    except Exception as e:
        return {'ok': False, 'error': f'{type(e).__name__}: {e}'}


def _code_run_sandbox_workdir() -> tuple[str, str]:
    resolver = globals().get('_sandbox_resolve_path')
    if not callable(resolver):
        raise RuntimeError('sandbox_backend_unavailable')
    run_id = f"run_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
    abs_dir, rel_dir = resolver(f'.code_runs/{run_id}', [], must_exist=False, for_dir=True)
    os.makedirs(abs_dir, exist_ok=True)
    return abs_dir, rel_dir


def _code_run_sandbox_write(path: str, content: str) -> None:
    raw = str(content or '').encode('utf-8', errors='replace')
    quota_fn = globals().get('_sandbox_quota_ok')
    storage_fn = globals().get('_sandbox_storage_quota_ok')
    if callable(quota_fn):
        ok, meta = quota_fn([], incoming_bytes=len(raw), current_path=path, append=False)
        if not ok:
            raise RuntimeError(str((meta or {}).get('error') or 'sandbox_disk_quota_exceeded'))
    if callable(storage_fn):
        ok, meta = storage_fn([], incoming_bytes=len(raw), current_path=path, append=False)
        if not ok:
            raise RuntimeError(str((meta or {}).get('error') or 'storage_quota_exceeded'))
    _code_run_write_text(path, content)


def _code_run_sandbox_runtime_matrix_probe() -> dict:
    ok_backend, backend_error = _code_run_sandbox_backend_status()
    labels = dict(CODE_RUN_LANGUAGE_LABELS)
    if not ok_backend:
        return {
            lang: {'language': lang, 'label': labels.get(lang, lang), 'available': False, 'runtime': '', 'backend': 'sandbox_runner', 'error': backend_error or 'sandbox_backend_unavailable'}
            for lang in CODE_RUN_SUPPORTED_CANONICAL
        }
    probe_script = '''python3 - <<'PYPROBE'
import json, shutil
checks = {
  "python": [["python3"], ["python"]],
  "javascript": [["node"], ["bun"], ["deno"]],
  "typescript": [["tsx"], ["bun"], ["ts-node"], ["deno"]],
  "bash": [["bash"], ["sh"]],
  "powershell": [["pwsh"], ["powershell"]],
  "c": [["gcc"], ["clang"], ["cc"], ["zig"]],
  "cpp": [["g++"], ["clang++"], ["c++"], ["zig"]],
  "go": [["go"]],
  "rust": [["rustc"]],
  "java": [["javac", "java"]],
  "php": [["php"]],
  "ruby": [["ruby"]],
  "perl": [["perl"]],
  "lua": [["lua"]],
  "r": [["Rscript"]],
  "swift": [["swift"]],
  "dart": [["dart"]],
}
out = {}
for lang, groups in checks.items():
    runtime = ""
    available = False
    for group in groups:
        found = [shutil.which(x) for x in group]
        if all(found):
            available = True
            runtime = " + ".join((x or '').split('/')[-1] for x in found if x)
            break
    out[lang] = {"available": available, "runtime": runtime}
print(json.dumps(out, ensure_ascii=False))
PYPROBE'''.strip()
    result = _code_run_sandbox_call({'command': probe_script, 'timeout_s': 12})
    data = {}
    if result.get('ok') and int(result.get('exit_code') or 0) == 0:
        try:
            data = json.loads(str(result.get('stdout') or '').strip().splitlines()[-1])
        except Exception:
            data = {}
    matrix = {}
    for lang in CODE_RUN_SUPPORTED_CANONICAL:
        row = data.get(lang) if isinstance(data, dict) else None
        available = bool(isinstance(row, dict) and row.get('available'))
        runtime = str((row or {}).get('runtime') or '') if isinstance(row, dict) else ''
        matrix[lang] = {
            'language': lang,
            'label': labels.get(lang, lang),
            'available': available,
            'runtime': runtime,
            'backend': 'sandbox_runner',
        }
    return matrix


def _code_run_runtime_matrix() -> dict:
    try:
        ttl = max(1, min(int(app_getenv('CODE_RUN_RUNTIME_CACHE_TTL', '120') or 120), 3600))
    except Exception:
        ttl = 120
    now = time.time()
    cache = globals().get('_CODE_RUN_SANDBOX_RUNTIME_CACHE')
    if isinstance(cache, dict) and isinstance(cache.get('matrix'), dict) and now - float(cache.get('ts') or 0.0) < ttl:
        return dict(cache.get('matrix') or {})
    matrix = _code_run_sandbox_runtime_matrix_probe()
    try:
        _CODE_RUN_SANDBOX_RUNTIME_CACHE['ts'] = now
        _CODE_RUN_SANDBOX_RUNTIME_CACHE['matrix'] = dict(matrix)
    except Exception:
        pass
    return matrix


def _code_run_sandbox_command_for_script(lang: str, filename: str) -> tuple[str, str]:
    if lang == 'python':
        return f'python3 {shlex.quote(filename)}', '.py'
    if lang == 'javascript':
        return f'node {shlex.quote(filename)}', '.js'
    if lang == 'typescript':
        return (
            f'if command -v tsx >/dev/null 2>&1; then tsx {shlex.quote(filename)}; '
            f'elif command -v bun >/dev/null 2>&1; then bun {shlex.quote(filename)}; '
            f'elif command -v ts-node >/dev/null 2>&1; then ts-node {shlex.quote(filename)}; '
            f'elif command -v deno >/dev/null 2>&1; then deno run --quiet {shlex.quote(filename)}; '
            f'else echo "missing_runtime:typescript" >&2; exit 127; fi'
        ), '.ts'
    if lang == 'bash':
        return f'bash {shlex.quote(filename)}', '.sh'
    if lang == 'powershell':
        return f'pwsh -NoProfile -ExecutionPolicy Bypass -File {shlex.quote(filename)}', '.ps1'
    if lang == 'php':
        return f'php {shlex.quote(filename)}', '.php'
    if lang == 'ruby':
        return f'ruby {shlex.quote(filename)}', '.rb'
    if lang == 'perl':
        return f'perl {shlex.quote(filename)}', '.pl'
    if lang == 'lua':
        return f'lua {shlex.quote(filename)}', '.lua'
    if lang == 'r':
        return f'Rscript {shlex.quote(filename)}', '.R'
    if lang == 'swift':
        return f'swift {shlex.quote(filename)}', '.swift'
    if lang == 'dart':
        return f'dart {shlex.quote(filename)}', '.dart'
    return '', ''


def _code_run_sandbox_result(language: str, result: dict, *, compile_result: dict | None = None, compile_failed: bool = False) -> dict:
    max_output_chars = int(app_getenv('CODE_RUN_MAX_OUTPUT_CHARS', '40000') or 40000)
    compile_result = dict(compile_result or {})
    exit_code = int(result.get('exit_code') if result.get('exit_code') is not None else 0)
    timed_out = bool(result.get('timed_out'))
    stderr = str(result.get('stderr') or '')
    if exit_code == 127 and 'missing_runtime:' in stderr:
        missing = stderr.split('missing_runtime:', 1)[1].strip().split()[0] or language
        raise RuntimeError(f'missing_runtime:{missing}')
    return {
        'ok': True,
        'success': (not timed_out) and exit_code == 0 and not compile_failed,
        'language': language,
        'label': CODE_RUN_LANGUAGE_LABELS.get(language, language),
        'backend': 'sandbox_runner',
        'sandbox': True,
        'sandbox_id': result.get('sandbox_id') or '',
        'command': str(result.get('command') or ''),
        'exit_code': exit_code,
        'stdout': _code_run_truncate_output(str(result.get('stdout') or ''), max_output_chars),
        'stderr': _code_run_truncate_output(stderr, max_output_chars),
        'timed_out': timed_out,
        'elapsed_ms': int(result.get('elapsed_ms') or 0),
        'compile_command': str(compile_result.get('command') or ''),
        'compile_stdout': _code_run_truncate_output(str(compile_result.get('stdout') or ''), max_output_chars),
        'compile_stderr': _code_run_truncate_output(str(compile_result.get('stderr') or ''), max_output_chars),
        'compile_elapsed_ms': int(compile_result.get('elapsed_ms') or 0),
        'sandbox_note': str(result.get('sandbox_note') or 'Code executed through Sandbox Runner in an ephemeral Docker volume; no host interpreter was used.'),
    }


def _code_run_execute(language: str, code: str, *, stdin_text: str = '') -> dict:
    lang = _code_run_normalize_language(language)
    if lang not in CODE_RUN_SUPPORTED_CANONICAL:
        raise ValueError('unsupported_language')
    code_text = str(code or '')
    if not code_text.strip():
        raise ValueError('empty_code')

    timeout_s = max(1.0, float(app_getenv('CODE_RUN_TIMEOUT', '12') or 12))
    compile_timeout_s = max(timeout_s, float(app_getenv('CODE_RUN_COMPILE_TIMEOUT', '25') or 25))
    max_code_chars = max(1000, int(app_getenv('CODE_RUN_MAX_CODE_CHARS', '200000') or 200000))
    if len(code_text) > max_code_chars:
        raise ValueError('code_too_large')

    ok_backend, backend_error = _code_run_sandbox_backend_status()
    if not ok_backend:
        return {
            'ok': False,
            'success': False,
            'language': lang,
            'label': CODE_RUN_LANGUAGE_LABELS.get(lang, lang),
            'backend': 'sandbox_runner',
            'sandbox': True,
            'error': backend_error or 'sandbox_backend_unavailable',
            'message': '代码运行沙盒不可用，已阻止回退到宿主机解释器。',
        }

    abs_dir, rel_dir = _code_run_sandbox_workdir()
    try:
        if lang in {'c', 'cpp', 'go', 'rust', 'java'}:
            if lang == 'c':
                src_name = 'main.c'
                compile_command = 'gcc main.c -O2 -o main'
                run_command = './main'
            elif lang == 'cpp':
                src_name = 'main.cpp'
                compile_command = 'g++ main.cpp -O2 -std=c++17 -o main'
                run_command = './main'
            elif lang == 'go':
                src_name = 'main.go'
                compile_command = ''
                run_command = 'go run main.go'
            elif lang == 'rust':
                src_name = 'main.rs'
                compile_command = 'rustc main.rs -O -o main'
                run_command = './main'
            else:
                class_name = _code_run_detect_java_class_name(code_text)
                src_name = class_name + '.java'
                compile_command = f'javac -encoding UTF-8 {shlex.quote(src_name)}'
                run_command = f'java -cp . {shlex.quote(class_name)}'
            _code_run_sandbox_write(os.path.join(abs_dir, src_name), code_text)
            compile_result = None
            if compile_command:
                compile_result = _code_run_sandbox_call({'command': compile_command, 'cwd': rel_dir, 'timeout_s': compile_timeout_s})
                if not compile_result.get('ok'):
                    return {
                        'ok': False,
                        'success': False,
                        'language': lang,
                        'label': CODE_RUN_LANGUAGE_LABELS.get(lang, lang),
                        'backend': 'sandbox_runner',
                        'sandbox': True,
                        'error': str(compile_result.get('error') or 'sandbox_compile_failed'),
                    }
                if bool(compile_result.get('timed_out')):
                    return _code_run_sandbox_result(lang, {
                        'command': run_command,
                        'exit_code': -1,
                        'stdout': '',
                        'stderr': '编译超时',
                        'timed_out': True,
                        'elapsed_ms': int(compile_result.get('elapsed_ms') or 0),
                        'sandbox_id': compile_result.get('sandbox_id') or '',
                    }, compile_result=compile_result, compile_failed=True)
                if int(compile_result.get('exit_code') or 0) != 0:
                    return _code_run_sandbox_result(lang, {
                        'command': run_command,
                        'exit_code': int(compile_result.get('exit_code') or 1),
                        'stdout': '',
                        'stderr': '编译失败',
                        'timed_out': False,
                        'elapsed_ms': int(compile_result.get('elapsed_ms') or 0),
                        'sandbox_id': compile_result.get('sandbox_id') or '',
                    }, compile_result=compile_result, compile_failed=True)
            run_result = _code_run_sandbox_call({'command': run_command, 'cwd': rel_dir, 'timeout_s': timeout_s, 'stdin': stdin_text})
            if not run_result.get('ok'):
                return {
                    'ok': False,
                    'success': False,
                    'language': lang,
                    'label': CODE_RUN_LANGUAGE_LABELS.get(lang, lang),
                    'backend': 'sandbox_runner',
                    'sandbox': True,
                    'error': str(run_result.get('error') or 'sandbox_run_failed'),
                }
            return _code_run_sandbox_result(lang, run_result, compile_result=compile_result)

        command, ext = _code_run_sandbox_command_for_script(lang, 'main')
        if not command or not ext:
            raise RuntimeError(f'unsupported_language:{lang}')
        filename = 'main' + ext
        _code_run_sandbox_write(os.path.join(abs_dir, filename), code_text)
        command, _ = _code_run_sandbox_command_for_script(lang, filename)
        run_result = _code_run_sandbox_call({'command': command, 'cwd': rel_dir, 'timeout_s': timeout_s, 'stdin': stdin_text})
        if not run_result.get('ok'):
            return {
                'ok': False,
                'success': False,
                'language': lang,
                'label': CODE_RUN_LANGUAGE_LABELS.get(lang, lang),
                'backend': 'sandbox_runner',
                'sandbox': True,
                'error': str(run_result.get('error') or 'sandbox_run_failed'),
            }
        return _code_run_sandbox_result(lang, run_result)
    finally:
        try:
            shutil.rmtree(abs_dir, ignore_errors=True)
        except Exception:
            pass
