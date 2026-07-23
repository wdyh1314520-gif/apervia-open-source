# Split from app3_parts/tools/file_registry_edit_tools_part.py.
# Purpose: sandbox tool Activity/file-progress payload construction.
# Loaded after file_registry_edit_tools_part.py, sharing the original global namespace.

def _sandbox_tool_progress_payload(name: str = '', args: dict | None = None, result: dict | None = None, phase: str = 'start') -> dict:
    nm = str(name or '').strip()
    args = dict(args or {}) if isinstance(args, dict) else {}
    result = dict(result or {}) if isinstance(result, dict) else {}
    path = str(args.get('path') or args.get('filename') or args.get('cwd') or result.get('path') or result.get('cwd') or '').strip()
    command = ''
    operation_key = ''
    sandbox_run_activity_op = ''
    sandbox_run_detail_hint = ''
    sandbox_run_language = ''
    if nm in {'sandbox_run', 'sandbox_list_files'}:
        try:
            command = _sandbox_run_display_command_from_args(args, result)
            sandbox_run_language = _sandbox_run_progress_language(args, result, command)
            operation_key = _sandbox_run_progress_operation_key_from_args_result(args, result)
        except Exception:
            command = str(args.get('command') or result.get('display_command') or result.get('command') or result.get('list_command') or '').strip()
            sandbox_run_language = _sandbox_run_progress_language(args, result, command)
    file_names: list[str] = []
    file_name_total = 0
    current_file = ''
    try:
        if nm == 'sandbox_import_files':
            selectors = args.get('files') or args.get('items') or []
            if isinstance(selectors, (str, dict)):
                selectors = [selectors]
            arg_names, arg_total = _sandbox_progress_collect_file_names(selectors, args.get('target_filename'), args.get('filename'), args.get('path'), limit=24)
            result_names, result_total = _sandbox_progress_collect_file_names(result.get('files'), result.get('errors'), limit=24)
            file_names = result_names or arg_names
            try:
                explicit_total = int(result.get('imported_count') or 0) + int(result.get('error_count') or 0)
            except Exception:
                explicit_total = 0
            file_name_total = max(explicit_total, result_total, arg_total, _sandbox_progress_selector_count(selectors), len(file_names))
            current_file = file_names[0] if file_names else ''
        elif nm == 'sandbox_list_files':
            # list_files is a compatibility alias for sandbox_run/find; do not
            # synthesize basename chips from structured file rows.
            file_names = []
            file_name_total = 0
            current_file = ''
        elif nm == 'sandbox_resolve_file_context':
            file_names, collected_total = _sandbox_progress_collect_file_names(result.get('files'), result.get('compare_candidates'), limit=24)
            try:
                file_name_total = max(int(result.get('visible_count') or result.get('count') or 0), collected_total, len(file_names))
            except Exception:
                file_name_total = max(collected_total, len(file_names))
            current_file = file_names[0] if file_names else _sandbox_progress_public_file_label(path)
        elif nm == 'sandbox_diff_files':
            pair = result.get('pair') if isinstance(result.get('pair'), dict) else {}
            file_names, collected_total = _sandbox_progress_collect_file_names(pair.get('left_name'), pair.get('right_name'), result.get('fileNames'), result.get('files'), result.get('delivery_files'), limit=24)
            file_name_total = max(collected_total, len(file_names), int(result.get('fileNameTotal') or 0))
            current_file = file_names[0] if file_names else ''
        elif nm in {'sandbox_read_file', 'sandbox_analyze_file_images', 'sandbox_write_file', 'sandbox_replace_text', 'sandbox_create_office_file', 'sandbox_publish_files'}:
            file_names, collected_total = _sandbox_progress_collect_file_names(path, args.get('path'), args.get('filename'), result.get('path'), result.get('filename'), result.get('files'), result.get('artifacts'), limit=24)
            file_name_total = max(collected_total, len(file_names))
            current_file = file_names[0] if file_names else _sandbox_progress_public_file_label(path)
        elif nm == 'sandbox_write_files':
            file_names, collected_total = _sandbox_progress_collect_file_names(args.get('files'), result.get('files'), limit=24)
            try:
                file_name_total = max(int(result.get('written_count') or 0), collected_total, len(file_names))
            except Exception:
                file_name_total = max(collected_total, len(file_names))
            current_file = file_names[0] if file_names else ''
        elif nm == 'sandbox_run':
            file_names, collected_total = _sandbox_progress_collect_file_names(result.get('output_paths'), result.get('created_paths'), result.get('changed_paths'), limit=24)
            try:
                file_name_total = max(int(result.get('output_file_count') or 0), collected_total, len(file_names))
            except Exception:
                file_name_total = max(collected_total, len(file_names))
            current_file = file_names[0] if file_names else ''
    except Exception:
        file_names = []
        file_name_total = 0
        current_file = ''
    labels = {
        'sandbox_import_files': ('正在导入文件到沙盒', '已导入文件到沙盒'),
        'sandbox_list_files': ('列出沙盒文件', '列出沙盒文件'),
        'sandbox_resolve_file_context': ('正在解析文件上下文', '已解析文件上下文'),
        'sandbox_diff_files': ('正在对比文件差异', '已对比文件差异'),
        'sandbox_read_file': ('正在读取沙盒文件', '已读取沙盒文件'),
        'sandbox_analyze_file_images': ('正在渲染并选择文件视觉页', '已准备文件视觉输入'),
        'sandbox_write_file': ('正在写入沙盒文件', '已写入沙盒文件'),
        'sandbox_write_files': ('正在批量写入沙盒文件', '已批量写入沙盒文件'),
        'sandbox_create_office_file': ('正在生成 Office/PDF 文件', '已生成 Office/PDF 文件'),
        'sandbox_replace_text': ('正在修改沙盒文件', '已修改沙盒文件'),
        'sandbox_run': ('正在运行沙盒命令', '已运行沙盒命令'),
        'sandbox_publish_files': ('正在发布沙盒文件', '已发布沙盒文件'),
    }
    start_label, done_label = labels.get(nm, ('正在处理代码沙盒', '已处理代码沙盒'))
    if nm == 'sandbox_run':
        start_label, done_label, sandbox_run_activity_op, sandbox_run_detail_hint = _sandbox_run_progress_labels(args, result, command)
    error = str(result.get('error') or '').strip()
    ok = bool(result.get('ok', True))
    is_done = str(phase or '').strip().lower() in {'done', 'finish', 'end'}
    is_error = is_done and not ok
    if is_done and nm in {'sandbox_run', 'sandbox_list_files'} and result.get('exit_code') is not None:
        try:
            is_error = is_error or int(result.get('exit_code') or 0) != 0
        except Exception:
            pass
    if is_done and nm in {'sandbox_run', 'sandbox_list_files'} and bool(result.get('timed_out')):
        is_error = True
    if is_done and nm == 'sandbox_run' and bool(result.get('skipped_by_policy')):
        message = '已跳过不必要的代码运行'
        is_error = False
    else:
        if nm == 'sandbox_run' and sandbox_run_activity_op == 'sandbox_run_python_capture':
            message = done_label if is_done else start_label
        else:
            message = (done_label + '失败') if is_error else (done_label if is_done else start_label)
    detail_bits = []
    sandbox_stdout = ''
    sandbox_stderr = ''
    sandbox_exit_code = None
    if path and nm != 'sandbox_run':
        detail_bits.append(path[:180])
    elif current_file and nm != 'sandbox_run':
        detail_bits.append(current_file[:180])
    if command and nm != 'sandbox_run':
        detail_bits.append(command[:220])
    # Do not expose the Docker runtime image as "image=..." in user-facing progress.
    # It is sandbox environment metadata, not a rendered document image.
    if (not is_done) and file_name_total > 1:
        detail_bits.append('files=' + str(file_name_total))
    if is_done and nm in {'sandbox_run', 'sandbox_list_files'}:
        if result.get('skipped_by_policy'):
            detail_bits.append('policy=' + str(result.get('policy_reason') or result.get('replacement_tool') or 'skipped')[:120])
            if result.get('replacement_tool'):
                detail_bits.append('use=' + str(result.get('replacement_tool'))[:80])
        if result.get('exit_code') is not None:
            sandbox_exit_code = result.get('exit_code')
        sandbox_stdout = str(result.get('stdout') or '').replace('\r\n', '\n').replace('\r', '\n').rstrip('\n')
        sandbox_stderr = str(result.get('stderr') or '').replace('\r\n', '\n').replace('\r', '\n').rstrip('\n')
        if nm == 'sandbox_run' and sandbox_run_activity_op == 'sandbox_run_python_capture' and is_error:
            sandbox_stdout = _sandbox_run_progress_captured_output(result)
            sandbox_stderr = ''
        if sandbox_run_detail_hint:
            detail_bits.append(sandbox_run_detail_hint[:180])
        if is_error and sandbox_exit_code is not None:
            detail_bits.append('退出码 ' + str(sandbox_exit_code))
        if is_error and sandbox_stderr:
            detail_bits.append('stderr: ' + sandbox_stderr.split('\n', 1)[0][:180])
    elif is_done and nm == 'sandbox_resolve_file_context':
        try:
            cand_count = len(result.get('compare_candidates') or [])
        except Exception:
            cand_count = 0
        if cand_count:
            detail_bits.append('compare_candidates=' + str(cand_count))
        elif file_name_total:
            detail_bits.append('files=' + str(file_name_total))
    elif is_done and nm == 'sandbox_diff_files':
        summary = str(result.get('summary') or '').strip()
        if summary:
            detail_bits.append(summary[:220])
    elif is_done and nm == 'sandbox_write_files':
        detail_bits.append('written=' + str(result.get('written_count') or len(result.get('files') or [])))
        if result.get('error_count') is not None:
            detail_bits.append('errors=' + str(result.get('error_count') or 0))
    elif is_done and nm == 'sandbox_import_files':
        detail_bits.append('imported=' + str(result.get('imported_count') or len(result.get('files') or [])))
        if result.get('error_count') is not None:
            detail_bits.append('errors=' + str(result.get('error_count') or 0))
        first_error = {}
        try:
            first_error = next((x for x in (result.get('errors') or []) if isinstance(x, dict)), {})
        except Exception:
            first_error = {}
        if first_error:
            err_name = str(first_error.get('error') or '').strip()
            err_file = str(first_error.get('filename') or first_error.get('target_filename') or '').strip()
            if err_name:
                detail_bits.append('error: ' + err_name[:160])
            if err_file:
                detail_bits.append('file: ' + err_file[:120])
    elif is_done and nm == 'sandbox_create_office_file':
        if result.get('format'):
            detail_bits.append('format=' + str(result.get('format')))
        if result.get('size') is not None:
            detail_bits.append(str(result.get('size')) + ' bytes')
    elif is_done and nm == 'sandbox_analyze_file_images':
        if result.get('_reused_cached_tool_result'):
            detail_bits.append('cache=reused')
        if result.get('visual_exec_id'):
            detail_bits.append('exec_id=' + str(result.get('visual_exec_id'))[:80])
        detail_bits.append('images=' + str(result.get('image_count') or 0))
        if result.get('analysis_deferred_to_responses'):
            detail_bits.append('visual_inputs=' + str(result.get('visual_input_count') or len(result.get('_responses_input_items') or []) or 0))
            if result.get('visual_input_deferred_to'):
                detail_bits.append('deferred_to=' + str(result.get('visual_input_deferred_to'))[:80])
        else:
            detail_bits.append('analyzed=' + str(result.get('analyzed_count') or 0))
        if result.get('endpoint_mode'):
            detail_bits.append('lane=' + str(result.get('endpoint_mode'))[:80])
        if result.get('mode'):
            detail_bits.append('mode=' + str(result.get('mode'))[:40])
        extract_errors = result.get('extract_errors') if isinstance(result.get('extract_errors'), list) else []
        if extract_errors:
            detail_bits.append('extract_error: ' + str(extract_errors[0] or '')[:160])
        diag_summary = result.get('diagnostic_summary') if isinstance(result.get('diagnostic_summary'), dict) else {}
        if diag_summary.get('office_stderr'):
            detail_bits.append('office_stderr: ' + str(diag_summary.get('office_stderr') or '')[:180])
        elif diag_summary.get('office_stdout'):
            detail_bits.append('office_stdout: ' + str(diag_summary.get('office_stdout') or '')[:180])
        visual_inventory = diag_summary.get('document_visual_inventory') if isinstance(diag_summary.get('document_visual_inventory'), dict) else {}
        if visual_inventory:
            if visual_inventory.get('office_math_count') is not None:
                detail_bits.append('office_math=' + str(visual_inventory.get('office_math_count') or 0))
            media_by_ext = visual_inventory.get('media_by_ext') if isinstance(visual_inventory.get('media_by_ext'), dict) else {}
            if media_by_ext:
                media_bits = []
                for key, value in sorted(media_by_ext.items(), key=lambda item: str(item[0])):
                    media_bits.append(str(key) + ':' + str(value))
                detail_bits.append('media=' + ','.join(media_bits)[:180])
        if diag_summary.get('render_selected_pages'):
            pages = [str(x) for x in (diag_summary.get('render_selected_pages') or [])]
            page_text = ','.join(pages[:24])
            if len(pages) > 24:
                page_text += ',...+' + str(len(pages) - 24)
            detail_bits.append('pages=' + page_text)
        if diag_summary.get('render_target_found') is not None:
            detail_bits.append('target_found=' + str(diag_summary.get('render_target_found')))
        if diag_summary.get('render_selection_reason'):
            detail_bits.append('select=' + str(diag_summary.get('render_selection_reason') or '')[:80])
        if result.get('error'):
            detail_bits.append('error: ' + str(result.get('error') or '')[:160])
        image_errors = []
        try:
            image_errors = [str(x.get('error') or '').strip() for x in (result.get('images') or []) if isinstance(x, dict) and str(x.get('error') or '').strip()]
        except Exception:
            image_errors = []
        if image_errors:
            detail_bits.append('analysis_error: ' + image_errors[0][:160])
    elif is_done and nm in {'sandbox_write_file', 'sandbox_replace_text', 'sandbox_read_file'}:
        if result.get('size') is not None:
            detail_bits.append(str(result.get('size')) + ' bytes')
        if result.get('replaced') is not None:
            detail_bits.append('replaced=' + str(result.get('replaced')))
    key_basis = operation_key if nm in {'sandbox_run', 'sandbox_list_files'} and operation_key else (command if nm in {'sandbox_run', 'sandbox_list_files'} and command else (path or str(args.get('paths') or args.get('files') or '')[:240]))
    try:
        key_hash = hashlib.sha1(str(key_basis or nm).encode('utf-8', 'ignore')).hexdigest()[:16]
    except Exception:
        key_hash = str(abs(hash(str(key_basis or nm))))[:16]
    payload = {
        'stage': 'sandbox_error' if is_error else ('sandbox_done' if is_done else 'sandbox_start'),
        'tool': nm,
        'key': f'sandbox|{nm}|{key_hash}',
        'message': message,
        'detail': ' | '.join(x for x in detail_bits if str(x or '').strip())[:360],
        'target_filename': path[:180],
        'percent': 100 if is_done else 5,
        'error': error[:220],
        'ts': int(time.time() * 1000),
    }
    if file_names:
        payload['fileNames'] = file_names[:80]
        payload['files_preview'] = file_names[:8]
    if file_name_total > 0:
        payload['fileNameTotal'] = int(file_name_total)
        payload['file_count'] = int(file_name_total)
    if current_file:
        payload['current_file'] = current_file[:180]
        if not payload.get('target_filename'):
            payload['target_filename'] = current_file[:180]
    if nm == 'sandbox_analyze_file_images' and is_done:
        document_visual_items = result.get('document_visual_items') if isinstance(result.get('document_visual_items'), list) else []
        document_visual_items = [dict(row) for row in document_visual_items if isinstance(row, dict)][:12]
        try:
            document_page_count = max(int(result.get('document_page_count') or 0), len(document_visual_items))
        except Exception:
            document_page_count = len(document_visual_items)
        if document_visual_items:
            payload['document_visual_items'] = document_visual_items
            payload['documentVisualItems'] = document_visual_items
        if document_page_count > 0:
            payload['document_page_count'] = document_page_count
            payload['documentPageCount'] = document_page_count
            payload['document_visual_deferred'] = bool(result.get('analysis_deferred_to_responses'))
            payload['documentVisualDeferred'] = bool(result.get('analysis_deferred_to_responses'))
    if nm in {'sandbox_run', 'sandbox_list_files'}:
        payload['activity_op'] = sandbox_run_activity_op or ('sandbox_run_list_files' if nm == 'sandbox_list_files' else '')
        payload['debug_available'] = bool(command or sandbox_stdout or sandbox_stderr or sandbox_exit_code is not None)
        payload['show_debug'] = bool(payload.get('debug_available'))
        if sandbox_run_language:
            payload['command_language'] = sandbox_run_language
            payload['commandLanguage'] = sandbox_run_language
        if operation_key:
            payload['operation_key'] = operation_key
            payload['operationKey'] = operation_key
        if command:
            payload['command'] = command
        if sandbox_exit_code is not None:
            payload['exit_code'] = sandbox_exit_code
        if sandbox_stdout:
            payload['stdout'] = sandbox_stdout
        if sandbox_stderr:
            payload['stderr'] = sandbox_stderr
    return payload
