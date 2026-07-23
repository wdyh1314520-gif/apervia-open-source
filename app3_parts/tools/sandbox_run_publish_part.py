# Split from app3_parts/tools/file_registry_edit_tools_part.py.
# Purpose: sandbox run and publish tools.
# Loaded by file_registry_edit_tools_part.py via _exec_split_file(...), sharing app3.py globals.

def _sandbox_run_tool(args: dict | None = None, messages: list | None = None) -> dict:
    args = dict(args or {})
    ok_backend, backend_error = _sandbox_backend_status()
    if not ok_backend:
        return _sandbox_unavailable_result(backend_error, messages or [])
    command_text = str(args.get('command') or '').strip()
    raw_code = args.get('code')
    if raw_code is None:
        raw_code = args.get('python_code')
    if raw_code is None:
        raw_code = args.get('script')
    code_text = str(raw_code or '')
    language = str(args.get('language') or args.get('lang') or '').strip()
    stdin_text = str(args.get('stdin') if args.get('stdin') is not None else args.get('stdin_text') if args.get('stdin_text') is not None else '')
    if code_text and not stdin_text:
        stdin_text = code_text
        if not command_text:
            command_text, code_reason = _sandbox_run_language_command(language, code_text)
            normalized_stdin = True
            normalized_reason = code_reason
        else:
            normalized_stdin = False
            normalized_reason = ''
    else:
        normalized_stdin = False
        normalized_reason = ''
    command_text, stdin_text, normalized_stdin2, normalized_reason2 = _sandbox_run_normalize_stdin_command(command_text, stdin_text, language)
    normalized_stdin = bool(normalized_stdin or normalized_stdin2)
    normalized_reason = normalized_reason or normalized_reason2
    argv = args.get('argv')
    display_command = ''
    operation_key = ''
    no_stdin_python_repl = bool((not stdin_text) and re.match(r"(?i)^\s*(python3|python|py)\s*(?:-)?\s*$", command_text or ''))
    no_stdin_node_repl = bool((not stdin_text) and re.match(r"(?i)^\s*(node|nodejs)\s*(?:-)?\s*$", command_text or ''))
    no_stdin_python_c = bool((not stdin_text) and re.match(r"(?i)^\s*(python3|python|py)\s+-c\s*$", command_text or ''))
    if no_stdin_python_c:
        return {
            **_sandbox_result_base(messages or []),
            'ok': False,
            'error': 'missing_argument_for_python_c_option',
            'command': command_text,
            'real_command': command_text,
            'display_command': command_text,
            'stdin_used': False,
            'failure_instruction': 'python3 -c requires the code as the next command-line argument. For sandbox code execution, use language="python" plus code; the backend wraps it with bash -lc and runs python3 -P - with stdin.',
        }
    if no_stdin_python_repl or no_stdin_node_repl:
        return {
            **_sandbox_result_base(messages or []),
            'ok': False,
            'error': 'missing_code_for_interpreter_stdin',
            'command': command_text,
            'real_command': command_text,
            'display_command': command_text,
            'stdin_used': False,
            'failure_instruction': 'For Python/Node execution, call sandbox_run with language plus code. Do not call an interactive interpreter command without code/stdin; the backend will wrap the run with bash -lc.',
        }
    normalized_argv_for_key = None
    if isinstance(argv, list):
        normalized_argv, argv_changed, argv_reason = _sandbox_run_normalize_argv(argv, stdin_text, language)
        normalized_argv_for_key = normalized_argv if isinstance(normalized_argv, list) else [str(x) for x in argv if str(x or '').strip()]
        hardened_argv, hardened_changed, hardened_reason = _sandbox_run_harden_python_argv(normalized_argv_for_key)
        if isinstance(hardened_argv, list):
            normalized_argv_for_key = hardened_argv
        if hardened_changed and not normalized_reason:
            normalized_reason = hardened_reason
        if _sandbox_run_argv_python_c_missing_arg(normalized_argv_for_key):
            return {
                **_sandbox_result_base(messages or []),
                'ok': False,
                'error': 'missing_argument_for_python_c_option',
                'command': _sandbox_run_cmd_display(normalized_argv_for_key),
                'real_command': _sandbox_run_cmd_display(['bash', '-lc', _sandbox_run_shell_join(normalized_argv_for_key)]),
                'display_command': _sandbox_run_display_command(command_text, stdin_text, language, normalized_argv_for_key),
                'stdin_used': bool(stdin_text),
                'failure_instruction': 'Do not call python3 -c without a code argument. For sandbox code execution, call sandbox_run with language="python" and code; the backend wraps it with bash -lc and runs python3 -P -.',
            }
        if argv_changed and not normalized_reason:
            normalized_reason = argv_reason
        run_argv, run_stdin_text, display_command, runtime_language = _sandbox_run_unified_bash_runner(command_text, stdin_text, language, normalized_argv_for_key)
    elif command_text:
        run_argv, run_stdin_text, display_command, runtime_language = _sandbox_run_unified_bash_runner(command_text, stdin_text, language, None)
    else:
        return {**_sandbox_result_base(messages or []), 'ok': False, 'error': 'empty_command'}
    if not (len(run_argv) >= 3 and str(run_argv[2] or '').strip()):
        return {
            **_sandbox_result_base(messages or []),
            'ok': False,
            'error': 'empty_bash_lc_script',
            'command': display_command or 'bash -lc',
            'real_command': _sandbox_run_cmd_display(run_argv) if run_argv else 'bash -lc',
            'display_command': display_command or 'bash -lc',
            'stdin_used': bool(run_stdin_text),
            'failure_instruction': 'sandbox_run uses one outer bash -lc runner. Provide the shell script after bash -lc, or pass language/code so the backend can wrap it as a heredoc.',
        }
    operation_key = _sandbox_run_operation_key(command_text, stdin_text, normalized_argv_for_key if isinstance(normalized_argv_for_key, list) else None)
    try:
        cwd, rel_cwd = _sandbox_resolve_path(args.get('cwd') or '', messages or [], must_exist=True, for_dir=True)
    except Exception as e:
        return {'ok': False, 'error': str(e or 'invalid_cwd')}
    try:
        timeout_s = max(1.0, min(float(args.get('timeout_s') or args.get('timeout') or app_getenv('SANDBOX_COMMAND_TIMEOUT', '30') or 30), 300.0))
    except Exception:
        timeout_s = 30.0
    data_root = _sandbox_root(messages or [])
    before_files = _sandbox_run_snapshot_files(data_root)
    container_cwd = '/mnt/data' + (('/' + rel_cwd.strip('/')) if rel_cwd else '')
    started = time.time()
    try:
        sandbox_rel = os.path.relpath(data_root, SANDBOX_ROOT_DIR).replace('\\', '/')
        runner_result = _sandbox_runner_request(
            {
                'sandbox_rel': sandbox_rel,
                'image': _sandbox_image(),
                'argv': run_argv,
                'stdin': run_stdin_text,
                'cwd': rel_cwd,
                'timeout_s': timeout_s,
                'disk_max_bytes': _sandbox_disk_max_bytes(),
                'memory': str(app_getenv('SANDBOX_DOCKER_MEMORY', '512m') or '512m').strip(),
                'memory_swap': str(app_getenv('SANDBOX_DOCKER_MEMORY_SWAP', app_getenv('SANDBOX_DOCKER_MEMORY', '512m')) or '512m').strip(),
                'cpus': str(app_getenv('SANDBOX_DOCKER_CPUS', '1.0') or '1.0').strip(),
                'pids_limit': str(app_getenv('SANDBOX_DOCKER_PIDS_LIMIT', '128') or '128').strip(),
                'shm_size': _sandbox_tmpfs_size('SANDBOX_DOCKER_SHM_SIZE', '128m'),
                'tmpfs_size': _sandbox_tmpfs_size('SANDBOX_DOCKER_TMPFS_SIZE', '64m'),
                'var_tmpfs_size': _sandbox_tmpfs_size('SANDBOX_DOCKER_VAR_TMPFS_SIZE', '32m'),
            },
            timeout=timeout_s + 25.0,
        )
        timed_out = bool(runner_result.get('timed_out'))
        stdout = str(runner_result.get('stdout') or '')
        stderr = str(runner_result.get('stderr') or '')
        try:
            max_out = max(2000, min(int(app_getenv('SANDBOX_COMMAND_MAX_OUTPUT_CHARS', '60000') or 60000), 300000))
        except Exception:
            max_out = 60000
        usage = _sandbox_dir_size(data_root)
        if usage > _sandbox_disk_max_bytes():
            return {**_sandbox_result_base(messages or []), 'ok': False, 'error': 'sandbox_disk_quota_exceeded', 'disk_usage_bytes': usage, 'disk_max_bytes': _sandbox_disk_max_bytes()}
        after_files = _sandbox_run_snapshot_files(data_root)
        created_paths, changed_paths, output_paths = _sandbox_run_changed_paths(before_files, after_files)
        exit_code = -1 if timed_out else int(runner_result.get('exit_code') or 0)
        return {
            **_sandbox_result_base(messages or []),
            'ok': True,
            'cwd': rel_cwd,
            'argv': run_argv,
            'command': display_command or _sandbox_run_cmd_display(run_argv),
            'real_command': _sandbox_run_cmd_display(run_argv),
            'display_command': display_command or _sandbox_run_cmd_display(run_argv),
            'operation_key': operation_key,
            'language': runtime_language or (_sandbox_run_effective_language(language, command_text, stdin_text) if stdin_text else str(language or '').strip().lower()),
            'stdin_used': bool(run_stdin_text),
            'stdin_normalized': bool(normalized_stdin),
            'stdin_normalized_reason': normalized_reason,
            'exit_code': exit_code,
            'stdout': _code_run_truncate_output(stdout or '', max_out) if callable(globals().get('_code_run_truncate_output')) else (stdout or '')[:max_out],
            'stderr': _code_run_truncate_output(stderr or '', max_out) if callable(globals().get('_code_run_truncate_output')) else (stderr or '')[:max_out],
            'timed_out': bool(timed_out),
            'elapsed_ms': int(runner_result.get('elapsed_ms') or ((time.time() - started) * 1000)),
            'created_paths': created_paths[:200],
            'changed_paths': changed_paths[:200],
            'output_paths': output_paths[:200],
            'output_file_count': len(output_paths),
            'publish_instruction': 'Call sandbox_publish_files with output_paths to deliver downloadable artifacts. output_paths are sandbox paths, not download links; do not print /api3/generated-download until sandbox_publish_files returns download_url.' if output_paths else '',
            'sandbox_note': 'Command executed through the isolated Sandbox Runner in an ephemeral Docker container; the app process has no Docker socket and no host shell fallback was used.',
        }
    except Exception as e:
        return {**_sandbox_result_base(messages or []), 'ok': False, 'cwd': rel_cwd, 'argv': run_argv, 'error': f'{type(e).__name__}: {e}'}


def _sandbox_publish_files_tool(args: dict | None = None, messages: list | None = None) -> dict:
    if not _sandbox_tools_enabled():
        return {'ok': False, 'error': 'sandbox_tools_disabled'}
    args = dict(args or {})
    raw_paths = args.get('paths') or args.get('files') or args.get('path') or []
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    if not isinstance(raw_paths, list):
        return {'ok': False, 'error': 'invalid_paths'}

    try:
        max_files = max(1, min(int(args.get('max_files') or 200), 1000))
    except Exception:
        max_files = 200
    try:
        max_bytes = max(1024, min(int(args.get('max_total_bytes') or (80 * 1024 * 1024)), 512 * 1024 * 1024))
    except Exception:
        max_bytes = 80 * 1024 * 1024

    selected: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in raw_paths:
        raw = str(item or '').strip()
        if not raw:
            continue
        try:
            abs_path, rel = _sandbox_resolve_path(raw, messages or [], must_exist=True)
        except Exception as e:
            return {'ok': False, 'error': 'path_not_found_or_invalid', 'path': raw, 'detail': str(e)}
        if os.path.isdir(abs_path):
            root_depth = abs_path.rstrip(os.sep).count(os.sep)
            for dirpath, dirnames, filenames in os.walk(abs_path):
                dirnames[:] = [d for d in dirnames if d not in SANDBOX_DENY_DIR_NAMES and not d.startswith('.cache')]
                if dirpath.rstrip(os.sep).count(os.sep) - root_depth > 20:
                    dirnames[:] = []
                for filename in filenames:
                    fp = os.path.join(dirpath, filename)
                    rel_file = _sandbox_display_path(fp, messages or [])
                    key = rel_file.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    selected.append((fp, rel_file))
                    if len(selected) >= max_files:
                        break
                if len(selected) >= max_files:
                    break
        else:
            key = rel.lower()
            if key not in seen:
                seen.add(key)
                selected.append((abs_path, rel))
        if len(selected) >= max_files:
            break

    if not selected:
        return {'ok': False, 'error': 'empty_paths'}

    artifacts: list[dict] = []
    sandbox_sources: list[dict] = []
    audit_by_path = _sandbox_file_edit_audit_map(args, messages or [])
    published_audits: list[dict] = []
    published_audit_ids: set[str] = set()
    total_bytes = 0
    for abs_path, rel in selected:
        if not os.path.isfile(abs_path):
            continue
        try:
            size = os.path.getsize(abs_path)
        except Exception:
            size = 0
        total_bytes += int(size or 0)
        if total_bytes > max_bytes:
            return {'ok': False, 'error': 'sandbox_publish_too_large', 'max_total_bytes': max_bytes, 'total_bytes': total_bytes}
        try:
            with open(abs_path, 'rb') as f:
                raw = f.read()
        except Exception as e:
            return {'ok': False, 'error': 'sandbox_file_read_failed', 'path': rel, 'detail': f'{type(e).__name__}: {e}'}
        mime = _guess_content_type_for_file(rel) if callable(globals().get('_guess_content_type_for_file')) else ''
        source_record = _sandbox_publish_source_record(abs_path, rel, messages or [])
        audit = audit_by_path.get(_sandbox_rel_key(rel)) or audit_by_path.get(_sandbox_rel_key(os.path.basename(rel)))
        if source_record and isinstance(audit, dict) and audit:
            source_record['audit_id'] = str(audit.get('audit_id') or '').strip()
        if isinstance(audit, dict) and audit:
            audit_id = str(audit.get('audit_id') or '').strip() or (str(audit.get('output_filename') or '') + '|' + str(audit.get('new_sha256') or ''))
            if audit_id not in published_audit_ids:
                published_audits.append(dict(audit))
                published_audit_ids.add(audit_id)
        if source_record:
            sandbox_sources.append(source_record)
        artifact = {
            'filename': rel,
            'mime': mime,
            'encoding': 'base64',
            'data': base64.b64encode(raw).decode('ascii'),
            'source_role': 'edited_output' if isinstance(audit, dict) and audit else 'assistant_generated',
        }
        if isinstance(audit, dict) and audit:
            artifact['edit_audit'] = dict(audit)
            artifact['file_edit_audit'] = dict(audit)
            artifact['edit_details'] = {'mode': 'sandbox', 'audit': dict(audit)}
        if source_record:
            artifact['sandbox_source_files'] = [source_record]
            artifact['sandbox_cleanup_policy'] = 'delete_with_file_library'
            artifact['sandbox_published'] = True
        artifacts.append(artifact)

    saver = globals().get('_save_artifacts_to_uploads')
    if not callable(saver):
        return {'ok': False, 'error': 'artifact_saver_unavailable'}
    saved = saver(artifacts)
    if not saved:
        return {'ok': False, 'error': 'sandbox_publish_save_failed', 'count': len(artifacts)}

    bundle_name = str(args.get('bundle_name') or args.get('zip_filename') or '').strip()
    force_zip = bool(args.get('force_zip') or args.get('zip') or bundle_name or len(saved) > 1)
    packaged_zip = None
    if force_zip:
        packager = globals().get('_package_saved_files_as_zip')
        namer = globals().get('_generated_files_bundle_filename')
        if not bundle_name:
            bundle_name = namer(messages or [], saved_files=saved, info={}) if callable(namer) else 'sandbox-files.zip'
        if callable(packager):
            packaged_zip = packager(saved, bundle_name)

    files_for_ui: list[dict] = []
    file_keys: set[str] = set()

    def _add_publish_file(item: dict | None) -> None:
        if not isinstance(item, dict) or not item:
            return
        key_parts = [
            str(item.get('download_url') or item.get('url') or item.get('view_url') or '').strip().lower(),
            str(item.get('filename') or item.get('display_filename') or '').strip().lower(),
            str(item.get('file_id') or item.get('id') or '').strip().lower(),
        ]
        key = '|'.join(key_parts).strip('|')
        if key and key in file_keys:
            return
        if key:
            file_keys.add(key)
        files_for_ui.append(item)

    if isinstance(packaged_zip, dict) and packaged_zip:
        _add_publish_file(packaged_zip)
    for item in saved:
        _add_publish_file(item if isinstance(item, dict) else None)

    answer = str(args.get('answer') or '').strip()
    return {
        **_sandbox_result_base(messages or []),
        'ok': True,
        'answer': answer,
        'count': len(files_for_ui),
        'source_count': len(saved),
        'files': files_for_ui,
        'delivery_files': files_for_ui,
        'source_files': saved if packaged_zip else [],
        'filenames': [str(item.get('filename') or '') for item in files_for_ui if isinstance(item, dict) and str(item.get('filename') or '').strip()],
        'packaged_zip': bool(packaged_zip),
        'published_paths': [rel for _abs, rel in selected],
        'sandbox_source_files': sandbox_sources,
        'file_edit_audits': published_audits,
        'edit_audits': published_audits,
        'generated_by_assistant': True,
        'reference_hint': '这些文件来自沙盒磁盘发布；files 同时包含打包文件和可直接下载的源文件，最终回复优先使用对应文件的 download_url。',
    }
