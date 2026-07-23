# Split from app3_parts/tools/file_registry_edit_tools_part.py.
# Purpose: sandbox file listing helpers and the sandbox_list_files compatibility tool.
# Loaded by app3.py before file_registry_edit_tools_part.py, sharing the original global namespace.


def _sandbox_list_mount_path(rel_path: str = '') -> str:
    rel = str(rel_path or '').strip().replace('\\', '/').strip('/')
    return '/mnt/data' if not rel else '/mnt/data/' + rel


def _sandbox_list_files_type_filter(args: dict | None = None) -> str:
    args = dict(args or {}) if isinstance(args, dict) else {}
    raw = str(args.get('type') or args.get('filter') or args.get('kind') or args.get('mode') or '').strip().lower()
    if raw in {'file', 'files', 'f', 'only_files', '只列文件', '文件'}:
        return 'file'
    if raw in {'dir', 'dirs', 'directory', 'directories', 'd', 'only_dirs', '目录'}:
        return 'dir'
    if args.get('only_files') is True or args.get('files_only') is True:
        return 'file'
    if args.get('only_dirs') is True or args.get('dirs_only') is True or args.get('directories_only') is True:
        return 'dir'
    return 'all'


def _sandbox_list_files_shell_script(path: str = '', *, max_depth: int = 2, max_files: int = 200, type_filter: str = 'all') -> str:
    rel = str(path or '').strip().replace('\\', '/').strip('/')
    target = _sandbox_list_mount_path(rel)
    depth = max(0, min(int(max_depth or 2), 12))
    limit = max(1, min(int(max_files or 200), 1000))
    type_arg = ''
    if type_filter == 'file':
        type_arg = ' -type f'
    elif type_filter == 'dir':
        type_arg = ' -type d'
    return f"find {shlex.quote(target)} -maxdepth {depth}{type_arg} -printf '%y\t%p\t%s bytes\n' | sort | head -{limit}"


def _sandbox_list_files_shell_command(path: str = '', *, max_depth: int = 2, max_files: int = 200, type_filter: str = 'all') -> str:
    script = _sandbox_list_files_shell_script(path, max_depth=max_depth, max_files=max_files, type_filter=type_filter)
    return 'bash -lc ' + shlex.quote(script)


def _sandbox_list_files_tool(args: dict | None = None, messages: list | None = None) -> dict:
    """Legacy-compatible alias for listing files through the unified runner.

    This tool used to scan the host-side sandbox directory with os.walk and then
    synthesize tree/basename/list_output fields.  That duplicated sandbox_run and
    could rewrite `/mnt/data/file` into `file`.  Keep the function only as a
    compatibility alias: build the same find command and execute it via
    sandbox_run, so stdout/stderr/exit_code/command all come from one runner.
    """
    if not _sandbox_tools_enabled():
        return {'ok': False, 'error': 'sandbox_tools_disabled'}
    args = dict(args or {}) if isinstance(args, dict) else {}
    raw_path = args.get('path') or args.get('directory') or ''
    try:
        _base, rel_base = _sandbox_resolve_path(raw_path, messages or [], must_exist=True, for_dir=True)
    except FileNotFoundError:
        return {'ok': False, 'error': 'directory_not_found'}
    except Exception as e:
        return {'ok': False, 'error': str(e or 'invalid_path')}
    try:
        max_files = max(1, min(int(args.get('max_files') or 200), 1000))
    except Exception:
        max_files = 200
    try:
        max_depth = max(0, min(int(args.get('max_depth') if args.get('max_depth') is not None else 2), 12))
    except Exception:
        max_depth = 2
    type_filter = _sandbox_list_files_type_filter(args)
    script = _sandbox_list_files_shell_script(rel_base, max_depth=max_depth, max_files=max_files, type_filter=type_filter)
    result = _sandbox_run_tool({
        'command': script,
        'language': 'shell',
        'cwd': '',
        'timeout_s': args.get('timeout_s') or args.get('timeout') or 30,
    }, messages=messages or [])
    out = dict(result or {}) if isinstance(result, dict) else {'ok': False, 'error': 'sandbox_run_failed'}
    out['tool_alias'] = 'sandbox_list_files'
    out['path'] = rel_base
    out['type_filter'] = type_filter
    out['max_depth'] = int(max_depth)
    out['max_files'] = int(max_files)
    out['list_command'] = str(out.get('display_command') or out.get('command') or _sandbox_list_files_shell_command(rel_base, max_depth=max_depth, max_files=max_files, type_filter=type_filter))
    out['list_output'] = str(out.get('stdout') or '')
    out['command_language'] = 'shell'
    return out
