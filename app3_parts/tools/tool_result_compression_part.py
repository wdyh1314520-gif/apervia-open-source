# compact tool results into model-safe payloads for agent/tool loops.

def _compress_tool_result_for_model(name: str, result, user_text: str = ''):
    try:
        if name == 'web_search' and isinstance(result, dict):
            items = []
            for r in (result.get('results') or [])[:3]:
                if not isinstance(r, dict):
                    continue
                items.append({
                    'title': str(r.get('title') or '')[:120],
                    'url': str(r.get('url') or '')[:240],
                    'snippet': _planner_safe_text(str(r.get('snippet') or ''), max_len=220),
                })
            out = {'ok': bool(result.get('ok', True)), 'results': items}
            ev = _compact_evidence_ledger_event(result)
            if ev:
                out['evidence_ledger_event'] = ev
                out['evidence_instruction'] = 'Search results are candidate evidence; fetch pages before citing detailed claims.'
            return out
        if name == 'search_knowledge_base' and isinstance(result, dict):
            rows = []
            for item in (result.get('results') or [])[:5]:
                if not isinstance(item, dict):
                    continue
                rows.append({
                    'filename': str(item.get('filename') or '')[:160],
                    'citation_label': str(item.get('citation_label') or '')[:180],
                    'chunk_order': item.get('chunk_order'),
                    'score': item.get('score'),
                    'snippet': _planner_safe_text(str(item.get('text') or ''), max_len=700),
                })
            state = result.get('state') if isinstance(result.get('state'), dict) else {}
            return {
                'ok': bool(result.get('ok', True)),
                '_kind': 'knowledge_base',
                'query': str(result.get('query') or '')[:240],
                'doc_count': int((state or {}).get('doc_count') or 0) if state else 0,
                'chunk_count': int((state or {}).get('chunk_count') or 0) if state else 0,
                'result_count': int(result.get('result_count') or len(rows)),
                'results': rows,
                'error': str(result.get('error') or '')[:260],
            }
        if name == 'read_knowledge_base_document' and isinstance(result, dict):
            rows = []
            for item in (result.get('results') or [])[:10]:
                if not isinstance(item, dict):
                    continue
                rows.append({
                    'filename': str(item.get('filename') or '')[:160],
                    'citation_label': str(item.get('citation_label') or '')[:180],
                    'chunk_order': item.get('chunk_order'),
                    'text': _planner_safe_text(str(item.get('text') or ''), max_len=1800),
                })
            doc = result.get('document') if isinstance(result.get('document'), dict) else {}
            coverage = result.get('coverage') if isinstance(result.get('coverage'), dict) else {}
            return {
                'ok': bool(result.get('ok', True)),
                '_kind': 'knowledge_base_document_read',
                'query': str(result.get('query') or '')[:240],
                'document': {
                    'id': str((doc or {}).get('id') or '')[:120],
                    'filename': str((doc or {}).get('filename') or '')[:220],
                    'chunk_count': int((doc or {}).get('chunk_count') or 0) if doc else 0,
                },
                'mode': str(result.get('mode') or '')[:80],
                'coverage': coverage,
                'result_count': int(result.get('result_count') or len(rows)),
                'results': rows,
                'can_expand': bool(result.get('can_expand')),
                'recommended_next_reads': [dict(x) for x in (result.get('recommended_next_reads') or []) if isinstance(x, dict)][:2],
                'instruction': str(result.get('instruction') or '')[:700],
                'error': str(result.get('error') or '')[:260],
            }
        if name == 'search_account_context' and isinstance(result, dict):
            rows = []
            for item in (result.get('results') or [])[:3]:
                if not isinstance(item, dict):
                    continue
                state = item.get('resume_state') if isinstance(item.get('resume_state'), dict) else {}
                rows.append({
                    'session_id': str(item.get('session_id') or '')[:120],
                    'title': str(item.get('title') or '')[:180],
                    'updated_at': str(item.get('updated_at') or '')[:80],
                    'score': item.get('score'),
                    'resume_state': {
                        'text': _planner_safe_text(str((state or {}).get('text') or ''), max_len=1100),
                        'last_user': _planner_safe_text(str((state or {}).get('last_user') or ''), max_len=360),
                        'last_assistant': _planner_safe_text(str((state or {}).get('last_assistant') or ''), max_len=360),
                    },
                    'summary': _planner_safe_text(str(item.get('summary') or ''), max_len=300),
                    'snippet': _planner_safe_text(str(item.get('snippet') or ''), max_len=420),
                    'files': [dict(x) for x in (item.get('files') or []) if isinstance(x, dict)][:4],
                })
            return {
                'ok': bool(result.get('ok', True)),
                '_kind': 'account_context',
                'query': str(result.get('query') or '')[:240],
                'result_count': int(result.get('result_count') or len(rows)),
                'results': rows,
                'error': str(result.get('error') or '')[:260],
                'message': str(result.get('message') or '')[:260],
            }
        if name == 'read_account_context' and isinstance(result, dict):
            text = str(result.get('text') or '')
            limit = max(3000, min(int(result.get('chars') or len(text) or 0) or 8000, 12000))
            truncated_for_model = bool(len(text) > limit)
            if truncated_for_model:
                text = text[:limit].rstrip() + '\n...【历史会话读取结果过长，仅截断给本轮模型】'
            state = result.get('resume_state') if isinstance(result.get('resume_state'), dict) else {}
            return {
                'ok': bool(result.get('ok', True)),
                '_kind': 'account_context_detail',
                'session_id': str(result.get('session_id') or '')[:120],
                'title': str(result.get('title') or '')[:180],
                'query': str(result.get('query') or '')[:240],
                'resume_state': {'text': _planner_safe_text(str((state or {}).get('text') or ''), max_len=1200)},
                'text': text,
                'truncated': bool(result.get('truncated') or truncated_for_model),
                'files': [dict(x) for x in (result.get('files') or []) if isinstance(x, dict)][:6],
                'error': str(result.get('error') or '')[:260],
                'message': str(result.get('message') or '')[:260],
            }
        if name in {'sandbox_list_files', 'sandbox_resolve_file_context', 'sandbox_diff_files', 'sandbox_read_file', 'sandbox_analyze_file_images', 'sandbox_write_file', 'sandbox_write_files', 'sandbox_create_office_file', 'sandbox_replace_text', 'sandbox_import_files', 'sandbox_run', 'sandbox_publish_files'} and isinstance(result, dict):
            if name == 'sandbox_list_files':
                return {
                    'ok': bool(result.get('ok')),
                    '_kind': 'sandbox_run',
                    'tool_alias': 'sandbox_list_files',
                    'sandbox_id': str(result.get('sandbox_id') or '')[:120],
                    'command': str(result.get('display_command') or result.get('command') or result.get('list_command') or '')[:1600],
                    'exit_code': result.get('exit_code'),
                    'stdout': _planner_safe_raw_output_text(str(result.get('stdout') or result.get('list_output') or ''), max_len=24000),
                    'stderr': _planner_safe_raw_output_text(str(result.get('stderr') or ''), max_len=12000),
                    'stdout_is_raw': True,
                    'command_language': str(result.get('command_language') or result.get('language') or 'shell')[:40],
                    'error': str(result.get('error') or '')[:260],
                }
            if name == 'sandbox_resolve_file_context':
                return {
                    'ok': bool(result.get('ok')),
                    '_kind': 'file_context',
                    'version': str(result.get('version') or '')[:80],
                    'query': str(result.get('query') or '')[:240],
                    'visible_count': int(result.get('visible_count') or 0),
                    'files': [dict(x) for x in (result.get('files') or []) if isinstance(x, dict)][:80],
                    'compare_candidates': [dict(x) for x in (result.get('compare_candidates') or []) if isinstance(x, dict)][:8],
                    'instruction': str(result.get('instruction') or '')[:500],
                    'error': str(result.get('error') or '')[:260],
                }
            if name == 'sandbox_diff_files':
                out = {
                    'ok': bool(result.get('ok')),
                    '_kind': 'file_diff',
                    'version': str(result.get('version') or '')[:80],
                    'pair': result.get('pair') if isinstance(result.get('pair'), dict) else {},
                    'summary': str(result.get('summary') or '')[:1200],
                    'error': str(result.get('error') or '')[:260],
                }
                diff_obj = result.get('diff') if isinstance(result.get('diff'), dict) else {}
                if diff_obj:
                    out['diff'] = {
                        'type': str(diff_obj.get('type') or '')[:80],
                        'added_sheets': [str(x or '')[:160] for x in (diff_obj.get('added_sheets') or [])[:20]],
                        'removed_sheets': [str(x or '')[:160] for x in (diff_obj.get('removed_sheets') or [])[:20]],
                        'changed_cell_count': int(diff_obj.get('changed_cell_count') or 0),
                        'sheet_summaries': [dict(x) for x in (diff_obj.get('sheet_summaries') or []) if isinstance(x, dict)][:20],
                        'changes': [dict(x) for x in (diff_obj.get('changes') or []) if isinstance(x, dict)][:80],
                        'diff_preview': [str(x or '')[:500] for x in (diff_obj.get('diff_preview') or [])[:120]],
                        'output_path': str(diff_obj.get('output_path') or '')[:260],
                        'truncated': bool(diff_obj.get('truncated')),
                    }
                files = []
                for item in (result.get('files') or result.get('delivery_files') or [])[:12]:
                    if isinstance(item, dict):
                        files.append({'filename': str(item.get('filename') or '')[:220], 'download_url': str(item.get('download_url') or '')[:500], 'view_url': str(item.get('view_url') or '')[:500], 'size': int(item.get('size') or 0)})
                if files:
                    out['files'] = files
                return out
            if name == 'sandbox_read_file':
                content = str(result.get('content') or '')
                doc_diag_summary = result.get('document_diagnostic_summary') if isinstance(result.get('document_diagnostic_summary'), dict) else {}
                if not doc_diag_summary and isinstance(result.get('document_diagnostics'), dict):
                    doc_diag_summary = _sandbox_document_diagnostic_summary(result.get('document_diagnostics'))
                path_for_policy = str(result.get('path') or '')
                policy_for_read = _sandbox_file_evidence_policy(os.path.splitext(path_for_policy)[1].lower(), filename=path_for_policy, diagnostics=doc_diag_summary)
                doc_continue_instruction = ''
                if bool((doc_diag_summary or {}).get('requires_visual_review')) and policy_for_read.get('kind') != 'spreadsheet':
                    doc_continue_instruction = 'This non-spreadsheet document has text-layer/OOXML diagnostics indicating possible missing formulas, symbols, tables, or embedded vector images. Add sandbox_analyze_file_images rendered evidence before judging document quality when the user question depends on those visual/page facts.'
                continue_instruction = policy_for_read.get('prompt') or _sandbox_file_evidence_policy_prompt()
                return {
                    'ok': bool(result.get('ok')),
                    '_kind': 'sandbox_file',
                    'sandbox_id': str(result.get('sandbox_id') or '')[:120],
                    'image': str(result.get('image') or '')[:160],
                    'path': str(result.get('path') or '')[:260],
                    'size': int(result.get('size') or 0),
                    'content': _planner_safe_text(content, max_len=60000),
                    'chars': int(result.get('chars') or len(content)),
                    'truncated': bool(result.get('truncated')),
                    'visual_hint': str(result.get('visual_hint') or '')[:500],
                    'document_diagnostic_summary': doc_diag_summary,
                    'document_continue_instruction': doc_continue_instruction,
                    'evidence_policy': policy_for_read,
                    'continue_instruction': continue_instruction,
                    'evidence_ledger_event': _compact_evidence_ledger_event(result),
                    'error': str(result.get('error') or '')[:260],
                }
            if name == 'sandbox_analyze_file_images':
                rows = []
                image_row_limit = _sandbox_cfg_int('SANDBOX_FILE_IMAGE_RESULT_ROWS_FOR_MODEL', 24, min_value=4, max_value=80)
                analysis_chars = _sandbox_cfg_int('SANDBOX_FILE_IMAGE_RESULT_ANALYSIS_CHARS', 8000, min_value=1200, max_value=30000)
                for item in (result.get('images') or [])[:image_row_limit]:
                    if not isinstance(item, dict):
                        continue
                    rows.append({
                        'index': item.get('index'),
                        'path': str(item.get('path') or '')[:260],
                        'source': str(item.get('source') or '')[:80],
                        'label': str(item.get('label') or '')[:180],
                        'width': int(item.get('width') or 0),
                        'height': int(item.get('height') or 0),
                        'ok': bool(item.get('ok')),
                        'analysis': _planner_safe_text(str(item.get('analysis') or ''), max_len=analysis_chars),
                        'error': str(item.get('error') or '')[:260],
                    })
                return {
                    'ok': bool(result.get('ok')),
                    '_kind': 'sandbox_file_image_analysis',
                    'sandbox_id': str(result.get('sandbox_id') or '')[:120],
                    'image': str(result.get('image') or '')[:160],
                    'path': str(result.get('path') or '')[:260],
                    'image_count': int(result.get('image_count') or 0),
                    'selected_image_count': int(result.get('selected_image_count') or len(rows) or 0),
                    'visual_input_count': int(result.get('visual_input_count') or 0),
                    'analyzed_count': int(result.get('analyzed_count') or 0),
                    'vision_model': str(result.get('vision_model') or '')[:120],
                    'endpoint_mode': str(result.get('endpoint_mode') or '')[:40],
                    'mode': str(result.get('mode') or '')[:40],
                    'analysis_deferred_to_responses': bool(result.get('analysis_deferred_to_responses')),
                    'visual_input_deferred_to': str(result.get('visual_input_deferred_to') or '')[:40],
                    'visual_processing_stage': str(result.get('visual_processing_stage') or '')[:120],
                    'sandbox_visual_role': str(result.get('sandbox_visual_role') or '')[:80],
                    'model_visual_role': str(result.get('model_visual_role') or '')[:80],
                    'instruction': str(result.get('instruction') or '')[:1200],
                    'fusion_instruction': 'Answer by combining this rendered visual evidence with any sandbox_read_file text evidence already gathered. Do not answer from visual evidence alone when the user asks about document meaning or consistency.',
                    'evidence': _planner_safe_text(str(result.get('evidence') or ''), max_len=_sandbox_cfg_int('SANDBOX_FILE_IMAGE_RESULT_EVIDENCE_CHARS', 60000, min_value=12000, max_value=200000)),
                    'images': rows,
                    'error': str(result.get('error') or '')[:260],
                    'extract_errors': [str(x or '')[:220] for x in (result.get('extract_errors') or [])[:6]],
                    'diagnostics': result.get('diagnostics') if isinstance(result.get('diagnostics'), dict) else {},
                    'diagnostic_summary': result.get('diagnostic_summary') if isinstance(result.get('diagnostic_summary'), dict) else {},
                    'image_input_errors': [str(x or '')[:220] for x in (result.get('image_input_errors') or [])[:6]],
                }
            if name == 'sandbox_write_file':
                out = {
                    'ok': bool(result.get('ok')),
                    '_kind': 'sandbox_write',
                    'sandbox_id': str(result.get('sandbox_id') or '')[:120],
                    'path': str(result.get('path') or '')[:260],
                    'size': int(result.get('size') or 0),
                    'appended': bool(result.get('appended')),
                    'error': str(result.get('error') or '')[:260],
                }
                if result.get('replacement_tool'):
                    out['replacement_tool'] = str(result.get('replacement_tool') or '')[:80]
                if result.get('instruction'):
                    out['instruction'] = str(result.get('instruction') or '')[:800]
                if isinstance(result.get('file_edit_audit'), dict):
                    out['file_edit_audit'] = _file_edit_compact_audit_for_payload(result.get('file_edit_audit'), include_diff=True)
                return out
            if name == 'sandbox_write_files':
                out = {
                    'ok': bool(result.get('ok')),
                    '_kind': 'sandbox_write_batch',
                    'sandbox_id': str(result.get('sandbox_id') or '')[:120],
                    'written_count': int(result.get('written_count') or 0),
                    'error_count': int(result.get('error_count') or 0),
                    'files': [dict(x) for x in (result.get('files') or []) if isinstance(x, dict)][:80],
                    'errors': [dict(x) for x in (result.get('errors') or []) if isinstance(x, dict)][:20],
                    'partial_ok': bool(result.get('partial_ok')),
                    'error': str(result.get('error') or '')[:260],
                }
                if result.get('replacement_tool'):
                    out['replacement_tool'] = str(result.get('replacement_tool') or '')[:80]
                if result.get('instruction'):
                    out['instruction'] = str(result.get('instruction') or '')[:800]
                if isinstance(result.get('file_edit_audits'), list):
                    out['file_edit_audits'] = [_file_edit_compact_audit_for_payload(x, include_diff=True) for x in (result.get('file_edit_audits') or []) if isinstance(x, dict)][:80]
                return out
            if name == 'sandbox_import_files':
                out = {
                    'ok': bool(result.get('ok')),
                    '_kind': 'sandbox_import',
                    'sandbox_id': str(result.get('sandbox_id') or '')[:120],
                    'imported_count': int(result.get('imported_count') or len(result.get('files') or [])),
                    'error_count': int(result.get('error_count') or 0),
                    'files': [dict(x) for x in (result.get('files') or []) if isinstance(x, dict)][:120],
                    'errors': [dict(x) for x in (result.get('errors') or []) if isinstance(x, dict)][:20],
                    'partial_ok': bool(result.get('partial_ok')),
                    'error': str(result.get('error') or '')[:260],
                }
                if not out['ok']:
                    out['failure_instruction'] = 'Import failed or was incomplete; do not claim you inspected or modified the file until a later sandbox_import_files call succeeds and sandbox_read_file or sandbox_run reads it from /mnt/data.'
                return out
            if name == 'sandbox_create_office_file':
                files = []
                for item in (result.get('files') or [])[:12]:
                    if not isinstance(item, dict):
                        continue
                    files.append({
                        'filename': str(item.get('filename') or '')[:220],
                        'download_url': str(item.get('download_url') or '')[:500],
                        'view_url': str(item.get('view_url') or '')[:500],
                        'size': int(item.get('size') or 0),
                    })
                out = {
                    'ok': bool(result.get('ok')),
                    '_kind': 'sandbox_office_file',
                    'sandbox_id': str(result.get('sandbox_id') or '')[:120],
                    'path': str(result.get('path') or '')[:260],
                    'format': str(result.get('format') or '')[:20],
                    'size': int(result.get('size') or 0),
                    'validation': result.get('validation') if isinstance(result.get('validation'), dict) else {},
                    'artifact_plan': result.get('artifact_plan') if isinstance(result.get('artifact_plan'), dict) else {},
                    'auto_published': bool(result.get('auto_published') or result.get('published')),
                    'files': files,
                    'publish_instruction': str(result.get('publish_instruction') or '')[:420],
                    'error': str(result.get('error') or result.get('publish_error') or '')[:260],
                }
                if isinstance(result.get('file_edit_audit'), dict):
                    out['file_edit_audit'] = _file_edit_compact_audit_for_payload(result.get('file_edit_audit'), include_diff=False)
                return out
            if name == 'sandbox_replace_text':
                out = {
                    'ok': bool(result.get('ok')),
                    '_kind': 'sandbox_replace',
                    'sandbox_id': str(result.get('sandbox_id') or '')[:120],
                    'path': str(result.get('path') or '')[:260],
                    'matches': int(result.get('matches') or 0),
                    'replaced': int(result.get('replaced') or 0),
                    'size': int(result.get('size') or 0),
                    'error': str(result.get('error') or '')[:260],
                }
                if isinstance(result.get('file_edit_audit'), dict):
                    out['file_edit_audit'] = _file_edit_compact_audit_for_payload(result.get('file_edit_audit'), include_diff=True)
                return out
            if name == 'sandbox_publish_files':
                files = []
                for item in (result.get('files') or [])[:12]:
                    if not isinstance(item, dict):
                        continue
                    row = {
                        'filename': str(item.get('filename') or '')[:220],
                        'download_url': str(item.get('download_url') or '')[:500],
                        'view_url': str(item.get('view_url') or '')[:500],
                        'size': int(item.get('size') or 0),
                        'bundle_members': [str(x or '')[:260] for x in (item.get('bundle_members') or [])[:80]] if isinstance(item.get('bundle_members'), list) else [],
                    }
                    if isinstance(item.get('edit_audit'), dict):
                        row['edit_audit'] = _file_edit_compact_audit_for_payload(item.get('edit_audit'), include_diff=True)
                    files.append(row)
                out = {
                    'ok': bool(result.get('ok')),
                    '_kind': 'sandbox_publish',
                    'sandbox_id': str(result.get('sandbox_id') or '')[:120],
                    'answer': str(result.get('answer') or '')[:1200],
                    'count': int(result.get('count') or len(files)),
                    'files': files,
                    'published_paths': [str(x or '')[:260] for x in (result.get('published_paths') or [])[:80]],
                    'packaged_zip': bool(result.get('packaged_zip')),
                    'error': str(result.get('error') or '')[:260],
                }
                if isinstance(result.get('file_edit_audits'), list):
                    out['file_edit_audits'] = [_file_edit_compact_audit_for_payload(x, include_diff=True) for x in (result.get('file_edit_audits') or []) if isinstance(x, dict)][:80]
                return out
            command_out = {
                'ok': bool(result.get('ok')),
                '_kind': 'sandbox_command_skipped' if result.get('skipped_by_policy') else 'sandbox_command',
                'sandbox_id': str(result.get('sandbox_id') or '')[:120],
                'image': str(result.get('image') or '')[:160],
                'cwd': str(result.get('cwd') or '')[:260],
                'command': str(result.get('command') or '')[:500],
                'real_command': str(result.get('real_command') or result.get('command') or '')[:500],
                'display_command': str(result.get('display_command') or result.get('command') or '')[:1200],
                'operation_key': str(result.get('operation_key') or '')[:80],
                'exit_code': result.get('exit_code'),
                'stdout': _planner_safe_raw_output_text(str(result.get('stdout') or ''), max_len=24000),
                'stderr': _planner_safe_raw_output_text(str(result.get('stderr') or ''), max_len=12000),
                'stdout_is_raw': True,
                'stderr_is_raw': True,
                'timed_out': bool(result.get('timed_out')),
                'elapsed_ms': result.get('elapsed_ms'),
                'error': str(result.get('error') or '')[:260],
                'stdin_used': bool(result.get('stdin_used')),
                'stdin_normalized': bool(result.get('stdin_normalized')),
                'created_paths': [str(x or '')[:260] for x in (result.get('created_paths') or [])[:80]],
                'changed_paths': [str(x or '')[:260] for x in (result.get('changed_paths') or [])[:80]],
                'output_paths': [str(x or '')[:260] for x in (result.get('output_paths') or [])[:80]],
                'output_file_count': int(result.get('output_file_count') or 0),
                'publish_instruction': str(result.get('publish_instruction') or '')[:260],
                'sandbox_note': str(result.get('sandbox_note') or '')[:180],
                'skipped_by_policy': bool(result.get('skipped_by_policy')),
                'policy_reason': str(result.get('policy_reason') or '')[:220],
                'replacement_tool': str(result.get('replacement_tool') or '')[:80],
                'instruction': str(result.get('instruction') or '')[:800],
                'next_step': str(result.get('next_step') or '')[:260],
            }
            if (not bool(result.get('ok')) or int(result.get('exit_code') or 0) != 0) and '<<' in str(result.get('command') or '') and ('Unknown option: -' in str(result.get('stderr') or '') or 'usage: python' in str(result.get('stderr') or '').lower()):
                command_out['failure_instruction'] = 'Do not retry with shell heredoc in command. Use language="python" plus code; the backend wraps it with bash -lc and runs python3 -P - with stdin.'
            if command_out['output_paths']:
                command_out['next_step'] = 'Call sandbox_publish_files with output_paths before telling the user the generated file is ready. output_paths are sandbox paths, not download links; do not print /api3/generated-download until sandbox_publish_files returns download_url.'
            return command_out
        if name in ('fetch_url', 'fetch_urls'):
            if isinstance(result, dict):
                if isinstance(result.get('pages'), list):
                    pages = []
                    for p2 in result.get('pages')[:2]:
                        if not isinstance(p2, dict):
                            continue
                        pages.append({
                            'url': str(p2.get('url') or '')[:240],
                            'title': str(p2.get('title') or '')[:120],
                            'snippet': _snippet_by_query(str(p2.get('text') or ''), user_text, limit=700),
                            'error': str(p2.get('error') or '')[:180],
                        })
                    out = {'ok': bool(result.get('ok', True)), 'pages': pages}
                    ev = _compact_evidence_ledger_event(result)
                    if ev:
                        out['evidence_ledger_event'] = ev
                        out['evidence_instruction'] = 'Fetched pages are citable evidence if text is sufficient.'
                    return out
                out = {
                    'ok': bool(result.get('ok', True)),
                    'url': str(result.get('url') or '')[:240],
                    'title': str(result.get('title') or '')[:120],
                    'snippet': _snippet_by_query(str(result.get('text') or ''), user_text, limit=900),
                    'error': str(result.get('error') or '')[:180],
                }
                ev = _compact_evidence_ledger_event(result)
                if ev:
                    out['evidence_ledger_event'] = ev
                    out['evidence_instruction'] = 'This fetched page can support cited web facts.'
                return out
        if name == 'get_location' and isinstance(result, dict):
            keep = {}
            for k in ('ok', '_kind', 'query', 'need_location', 'location_name', 'summary', 'message'):
                if k in result:
                    keep[k] = result.get(k)
            loc = result.get('location') or {}
            if isinstance(loc, dict):
                keep['location'] = {
                    'name': str(loc.get('name') or '')[:120],
                    'lat': loc.get('lat'),
                    'lon': loc.get('lon'),
                    'source': str(loc.get('source') or '')[:40],
                }
            if isinstance(result.get('tips'), list):
                keep['tips'] = [str(x or '')[:80] for x in result.get('tips')[:3] if str(x or '').strip()]
            return keep
        if name == 'image_search' and isinstance(result, dict):
            imgs = []
            def _host_from_image_row(row: dict) -> str:
                raw = str(row.get('source_url') or row.get('page_url') or row.get('source') or row.get('domain') or '').strip()
                if not raw:
                    return ''
                try:
                    if '://' in raw:
                        return (urlparse(raw).hostname or '').lower().strip('.')[:120]
                except Exception:
                    pass
                return re.sub(r'[^A-Za-z0-9._-]+', '', raw).lower()[:120]
            for r in (result.get('results') or [])[:5]:
                if not isinstance(r, dict):
                    continue
                imgs.append({
                    'title': str(r.get('title') or '')[:80],
                    'source_host': _host_from_image_row(r),
                })
            image_payload = result.get('image_reply_payload') if isinstance(result.get('image_reply_payload'), dict) else {}
            image_items = image_payload.get('images') if isinstance(image_payload, dict) and isinstance(image_payload.get('images'), list) else []
            try:
                result_count = int(result.get('result_count') or len(result.get('results') or []) or len(image_items) or len(imgs))
            except Exception:
                result_count = max(len(result.get('results') or []), len(image_items), len(imgs))
            out = {
                'ok': bool(result.get('ok', True)),
                'result_count': result_count,
                'displayed_count': len(image_items) or len(imgs),
                'ui_delivery': 'structured_image_reply' if image_items else 'image_search_results',
                'results': imgs,
                'instruction': 'Images are delivered to the UI through structured image_reply data. Do not output Markdown images, raw image URLs, or source link lists.',
            }
            if result.get('subject'):
                out['subject'] = str(result.get('subject'))[:80]
            if result.get('query'):
                out['query'] = str(result.get('query'))[:120]
            return out
        if name == 'get_weather' and isinstance(result, dict):
            keep = {}
            for k in ('ok','_kind','query','need_location','location_name','summary','temperature_c','feels_like_c','humidity','wind_kph'):
                if k in result:
                    keep[k] = result.get(k)
            loc = result.get('location') or {}
            if isinstance(loc, dict):
                keep['location'] = {
                    'name': str(loc.get('name') or '')[:120],
                    'lat': loc.get('lat'),
                    'lon': loc.get('lon'),
                }
            cur = result.get('current') or {}
            if isinstance(cur, dict):
                keep['current'] = {
                    'weather': cur.get('weather'),
                    'temperature': cur.get('temperature'),
                    'temperature_unit': cur.get('temperature_unit'),
                    'feels_like': cur.get('feels_like'),
                    'humidity': cur.get('humidity'),
                    'wind_speed': cur.get('wind_speed'),
                    'wind_speed_unit': cur.get('wind_speed_unit'),
                    'precipitation': cur.get('precipitation'),
                }
            if isinstance(result.get('hourly'), list):
                keep['hourly'] = result.get('hourly')[:6]
            if isinstance(result.get('daily'), list):
                keep['daily'] = result.get('daily')[:3]
            return keep
    except Exception:
        if name == 'image_search':
            return {
                'ok': False,
                'result_count': 0,
                'displayed_count': 0,
                'ui_delivery': 'structured_image_reply',
                'results': [],
                'instruction': 'Images are delivered to the UI through structured image_reply data. Do not output Markdown images, raw image URLs, or source link lists.',
            }
        pass
    raw = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
    return _planner_safe_text(raw, max_len=1800)
