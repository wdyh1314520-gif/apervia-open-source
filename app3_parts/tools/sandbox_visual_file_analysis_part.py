# sandbox visual file diagnostics and image analysis tool.

def _sandbox_data_url_for_image(path: str = '', *, max_bytes: int = 5 * 1024 * 1024) -> tuple[str, str, int]:
    if not path or not os.path.isfile(path):
        return '', '', 0
    try:
        size = int(os.path.getsize(path))
    except Exception:
        size = 0
    if size > max_bytes:
        return '', 'image_too_large', size
    try:
        with open(path, 'rb') as f:
            raw = f.read(max_bytes + 1)
        if len(raw) > max_bytes:
            return '', 'image_too_large', len(raw)
    except Exception as e:
        return '', f'{type(e).__name__}: {e}', size
    ext = os.path.splitext(str(path or ''))[1].lower()
    ext_mime = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.webp': 'image/webp',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp',
        '.tif': 'image/tiff',
        '.tiff': 'image/tiff',
    }.get(ext, '')
    mime = ext_mime or (_guess_content_type_for_file(path) if callable(globals().get('_guess_content_type_for_file')) else 'image/jpeg')
    if not str(mime or '').startswith('image/'):
        mime = 'image/jpeg'
    return f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii'), '', len(raw)


def _sandbox_visual_model_name(model: str | None = None, args: dict | None = None) -> str:
    def clean(value) -> str:
        s = str(value or '').strip()
        if s.lower() in {'', 'auto', 'default', 'current', 'none', 'null'}:
            return ''
        return s

    raw = ''
    if isinstance(args, dict):
        raw = clean(args.get('vision_model') or args.get('model'))
    return (
        raw
        or clean(app_getenv('FILE_IMAGE_VISION_MODEL', ''))
        or clean(app_getenv('VISION_MODEL', ''))
        or clean(model)
        or clean(app_getenv('GPT_MODEL', ''))
    )


def _sandbox_cfg_int(name: str, default: int, *, min_value: int = 0, max_value: int = 1000000) -> int:
    try:
        value = int(str(app_getenv(name, str(default)) or str(default)).strip())
    except Exception:
        value = int(default)
    return max(int(min_value), min(int(value), int(max_value)))


def _sandbox_client_endpoint_mode(client_override=None) -> str:
    try:
        normalizer = globals().get('_normalize_payload_api_endpoint_mode') or globals().get('_normalize_chat_api_endpoint_mode')
        raw = str(getattr(client_override, '_webai_api_endpoint_mode', '') or 'chat_completions').strip()
        if callable(normalizer):
            return str(normalizer(raw) or 'chat_completions').strip()
        return 'responses' if raw.lower() == 'responses' else 'chat_completions'
    except Exception:
        return 'chat_completions'


def _sandbox_file_image_diagnostic_summary(diagnostics: dict | None = None) -> dict:
    diag = diagnostics if isinstance(diagnostics, dict) else {}
    office = diag.get('office_pdf_conversion') if isinstance(diag.get('office_pdf_conversion'), dict) else {}
    render = diag.get('pdf_render') if isinstance(diag.get('pdf_render'), dict) else {}
    document_visual_inventory = diag.get('document_visual_inventory') if isinstance(diag.get('document_visual_inventory'), dict) else {}
    attempts = [dict(x) for x in (office.get('attempts') or []) if isinstance(x, dict)]
    first = attempts[0] if attempts else {}
    return {
        'document_visual_inventory': {
            'document_type': str(document_visual_inventory.get('document_type') or '')[:40],
            'media_count': int(document_visual_inventory.get('media_count') or 0),
            'media_by_ext': document_visual_inventory.get('media_by_ext') if isinstance(document_visual_inventory.get('media_by_ext'), dict) else {},
            'paragraph_count': int(document_visual_inventory.get('paragraph_count') or 0),
            'nonempty_paragraph_count': int(document_visual_inventory.get('nonempty_paragraph_count') or 0),
            'table_count': int(document_visual_inventory.get('table_count') or 0),
            'office_math_count': int(document_visual_inventory.get('office_math_count') or 0),
            'drawing_count': int(document_visual_inventory.get('drawing_count') or 0),
            'object_count': int(document_visual_inventory.get('object_count') or 0),
            'shape_count': int(document_visual_inventory.get('shape_count') or 0),
            'ole_count': int(document_visual_inventory.get('ole_count') or 0),
            'embedding_count': int(document_visual_inventory.get('embedding_count') or 0),
            'caption_candidates': [dict(x) for x in (document_visual_inventory.get('caption_candidates') or [])[:8] if isinstance(x, dict)],
            'inspect_error': str(document_visual_inventory.get('inspect_error') or '')[:260],
        } if document_visual_inventory else {},
        'office_error': str(office.get('error') or '')[:240],
        'office_profile': str(office.get('profile') or '')[:260],
        'office_exit_code': first.get('exit_code'),
        'office_stdout': str(first.get('stdout') or '')[:1200],
        'office_stderr': str(first.get('stderr') or first.get('error') or '')[:1200],
        'office_cmd': [str(x or '')[:160] for x in (first.get('cmd') or [])[:20]] if isinstance(first.get('cmd'), list) else [],
        'render_strategy': str(render.get('strategy') or '')[:80],
        'render_target_found': render.get('target_found'),
        'render_selected_pages': render.get('selected_pages') if isinstance(render.get('selected_pages'), list) else [],
        'render_target_terms': render.get('target_terms') if isinstance(render.get('target_terms'), list) else [],
        'render_selection_reason': str(render.get('selection_reason') or '')[:160],
        'render_page_scores': render.get('page_scores')[:8] if isinstance(render.get('page_scores'), list) else [],
    }


def _sandbox_latest_user_text(messages: list | None = None) -> str:
    try:
        fn = globals().get('_latest_user_text_from_messages')
        if callable(fn):
            return str(fn(messages or []) or '').strip()
    except Exception:
        pass
    try:
        for msg in reversed(messages or []):
            if not isinstance(msg, dict) or str(msg.get('role') or '').strip().lower() != 'user':
                continue
            content = msg.get('content')
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and str(item.get('type') or '').strip().lower() in {'text', 'input_text'}:
                        parts.append(str(item.get('text') or ''))
                return '\n'.join(parts).strip()
    except Exception:
        pass
    return ''


def _sandbox_visual_target_from_text(text: str = '') -> str:
    raw = str(text or '').strip()
    if not raw:
        return ''
    patterns = [
        r'(图\s*[0-9一二三四五六七八九十]+)',
        r'(表\s*[0-9一二三四五六七八九十]+)',
        r'((?:Figure|Fig\.?)\s*[0-9]+)',
        r'((?:Table)\s*[0-9]+)',
        r'(第\s*[0-9一二三四五六七八九十]+\s*页)',
        r'(第\s*[0-9一二三四五六七八九十]+\s*张\s*图)',
    ]
    for pat in patterns:
        m = re.search(pat, raw, re.I)
        if m:
            return re.sub(r'\s+', '', m.group(1))
    return ''


def _sandbox_broad_document_review_query(text: str = '') -> bool:
    raw = str(text or '')
    if not raw.strip():
        return False
    if 'APP3_BROAD_DOCUMENT_REVIEW' in raw:
        return True
    return bool(re.search(r'(怎么样|写得|评价|评估|审阅|检查|看看|整体|论文|报告|初稿|质量|问题|不足|建议|打分|能不能交|专业|规范|格式|逻辑|图表|公式)', raw, re.I))


def _sandbox_has_explicit_visual_target(text: str = '') -> bool:
    raw = str(text or '').strip()
    if not raw:
        return False
    return bool(re.search(r'((图|表)\s*[0-9一二三四五六七八九十]+|(?:Figure|Fig\.?|Table)\s*[0-9]+|第\s*[0-9一二三四五六七八九十]+\s*(页|张图|幅图|个图))', raw, re.I))


def _sandbox_file_evidence_policy_prompt() -> str:
    fn = globals().get('file_evidence_policy_prompt')
    if callable(fn):
        try:
            return str(fn() or '').strip()
        except Exception:
            pass
    return '文件证据策略：文本/结构化数据先读文本层，视觉问题再补渲染页，运行代码只用于真实执行。'


def _sandbox_file_evidence_policy(ext: str = '', query: str = '', target: str = '', *, filename: str = '', diagnostics: dict | None = None) -> dict:
    fn = globals().get('file_evidence_plan')
    if callable(fn):
        try:
            return dict(fn(filename=filename, ext=ext, query=query, target=target, diagnostics=diagnostics))
        except Exception as exc:
            return {'version': 'fallback', 'ext': str(ext or '').lower(), 'kind': 'unknown', 'primary_tool': 'sandbox_read_file', 'allow_visual': False, 'allow_run_first': False, 'reason': f'policy_error:{type(exc).__name__}', 'prompt': _sandbox_file_evidence_policy_prompt()}
    return {'version': 'fallback', 'ext': str(ext or '').lower(), 'kind': 'unknown', 'primary_tool': 'sandbox_read_file', 'allow_visual': False, 'allow_run_first': False, 'reason': 'policy_missing', 'prompt': _sandbox_file_evidence_policy_prompt()}


def spreadsheet_visual_query(value):
    return bool(_sandbox_file_evidence_policy('.xlsx', query=value).get('allow_visual'))


def _sandbox_task_intent_policy_prompt() -> str:
    parts = []
    for fn_name in ('task_intent_policy_prompt', 'agent_loop_policy_prompt', 'tool_policy_prompt', 'evidence_ledger_policy_prompt', 'web_evidence_policy_prompt', 'file_evidence_policy_prompt', 'file_context_policy_prompt', 'file_diff_policy_prompt', 'artifact_task_policy_prompt', 'sandbox_execution_policy_prompt', 'artifact_manager_policy_prompt'):
        fn = globals().get(fn_name)
        if callable(fn):
            try:
                text = str(fn() or '').strip()
                if text:
                    parts.append(text)
            except Exception:
                pass
    return '\n'.join(parts) or _sandbox_file_evidence_policy_prompt()


def _sandbox_artifact_task_plan_for_messages(args: dict | None = None, messages: list | None = None) -> dict:
    fn = globals().get('artifact_task_plan')
    if callable(fn):
        try:
            latest = _sandbox_latest_user_text(messages or [])
            return dict(fn(text=latest, target_format=str((args or {}).get('format') or ''), output_path=str((args or {}).get('path') or (args or {}).get('filename') or ''), messages=messages or []))
        except Exception as exc:
            return {'version': 'artifact_policy_fallback', 'is_artifact_task': False, 'error': f'{type(exc).__name__}: {exc}'}
    return {'version': 'artifact_policy_missing', 'is_artifact_task': False}


def _sandbox_execution_decision_for_args(args: dict | None = None, messages: list | None = None) -> dict:
    fn = globals().get('sandbox_execution_decision')
    if callable(fn):
        try:
            return dict(fn(args=args or {}, messages=messages or [], user_text=_sandbox_latest_user_text(messages or [])))
        except Exception as exc:
            return {
                'version': 'execution_policy_fallback',
                'allow': False,
                'skip_as_success': True,
                'reason': f'policy_error:{type(exc).__name__}: {exc}',
                'instruction': 'Sandbox execution was blocked because the centralized execution policy failed. Do not retry the same command until the policy is available.',
            }
    return {
        'version': 'execution_policy_missing',
        'allow': False,
        'skip_as_success': True,
        'reason': 'policy_missing',
        'instruction': 'Sandbox execution was blocked because the centralized execution policy is unavailable.',
    }


def _sandbox_policy_skip_result(messages: list | None = None, *, tool: str = '', args: dict | None = None, decision: dict | None = None) -> dict:
    dec = dict(decision or {}) if isinstance(decision, dict) else {}
    replacement = str(dec.get('replacement_tool') or '').strip()
    return {
        **_sandbox_result_base(messages or []),
        'ok': True,
        'skipped_by_policy': True,
        'tool': str(tool or '').strip(),
        'error': '',
        'policy_reason': str(dec.get('reason') or 'not_needed')[:220],
        'replacement_tool': replacement,
        'execution_policy': dec,
        'message': str(dec.get('instruction') or 'This tool call was skipped by centralized policy because another tool is the correct route.')[:600],
        'instruction': str(dec.get('instruction') or '')[:1200],
        'next_step': ('Call ' + replacement + ' instead.') if replacement else '',
    }


def _attach_evidence_ledger_event(tool: str = '', result: dict | None = None, args: dict | None = None) -> dict:
    if not isinstance(result, dict):
        return result
    fn = globals().get('evidence_ledger_attach_tool_result')
    if callable(fn):
        try:
            return dict(fn(tool=tool, result=result, args=args or {}) or result)
        except Exception as exc:
            out = dict(result)
            out['evidence_ledger_error'] = f'{type(exc).__name__}: {exc}'[:260]
            return out
    return result


def _compact_evidence_ledger_event(result: dict | None = None) -> dict | None:
    if not isinstance(result, dict):
        return None
    ev = result.get('evidence_ledger_event') if isinstance(result.get('evidence_ledger_event'), dict) else None
    if not ev:
        return None
    return {
        'event_id': str(ev.get('event_id') or '')[:80],
        'type': str(ev.get('type') or '')[:80],
        'source_tool': str(ev.get('source_tool') or '')[:80],
        'status': str(ev.get('status') or '')[:40],
        'citable': bool(ev.get('citable')),
        'locator': str(ev.get('locator') or '')[:260],
        'summary': str(ev.get('summary') or '')[:500],
    }


def _sandbox_analyze_one_image_with_model(data_url: str = '', *, prompt: str = '', source_label: str = '', model: str = '', client_override=None) -> dict:
    if not data_url:
        return {'ok': False, 'error': 'missing_image_data'}
    model_name = str(model or '').strip()
    if not model_name:
        return {'ok': False, 'error': 'vision_model_not_configured'}
    contract_text = ''
    try:
        contract_builder = globals().get('prompt_contract_text')
        if callable(contract_builder):
            contract_text = str(contract_builder('document_image_analyzer', compact=True) or '').strip()
    except Exception:
        contract_text = ''
    sys_prompt = (
        ((contract_text + '\n') if contract_text else '')
        + '请直接观察图片像素，提取图中可见文字、表格/图表、UI、流程图、截图和可用于回答问题的证据。'
    )
    user_text = (
        f'来源：{source_label or "document image"}\n'
        f'用户关注点：{prompt or "识别这张文档内图片的主要内容、文字、图表、表格、截图和可用于回答问题的证据。"}\n'
        '请按以下字段输出：summary、visible_text、visual_elements、tables_or_charts、answer_relevant_evidence、confidence。'
    )
    messages = [
        {'role': 'system', 'content': sys_prompt},
        {'role': 'user', 'content': [
            {'type': 'text', 'text': user_text},
            {'type': 'image_url', 'image_url': {'url': data_url, 'detail': 'high'}},
        ]},
    ]
    endpoint_mode = _sandbox_client_endpoint_mode(client_override)
    if endpoint_mode == 'responses':
        responses_create = globals().get('_responses_create_non_stream_text')
        if callable(responses_create):
            try:
                raw = str(responses_create(client_override=client_override or client_gpt, model=model_name, messages=messages, timeout=240) or '').strip()
                return {'ok': bool(raw), 'text': raw[:_sandbox_cfg_int('SANDBOX_FILE_IMAGE_ANALYSIS_MAX_CHARS', 16000, min_value=2000, max_value=60000)], 'model': model_name, 'api': 'responses'}
            except Exception as e:
                return {'ok': False, 'error': f'Responses:{type(e).__name__}: {e}', 'model': model_name, 'api': 'responses'}
        return {'ok': False, 'error': 'Responses:responses_helper_unavailable', 'model': model_name, 'api': 'responses'}
    try:
        req = {'model': model_name, 'messages': messages, 'temperature': 0, 'max_tokens': _sandbox_cfg_int('SANDBOX_FILE_IMAGE_ANALYSIS_MAX_TOKENS', 2400, min_value=600, max_value=8000)}
        applier = globals().get('_apply_completion_thinking_kwargs')
        if callable(applier):
            req = applier(req, role='chat', model=model_name, client_override=client_override)
        resp = (client_override or client_gpt).chat.completions.create(**req)
        raw = (((resp.choices or [None])[0] or None).message.content or '').strip()
        return {'ok': bool(raw), 'text': raw[:_sandbox_cfg_int('SANDBOX_FILE_IMAGE_ANALYSIS_MAX_CHARS', 16000, min_value=2000, max_value=60000)], 'model': model_name, 'api': 'chat_completions'}
    except Exception as e:
        return {'ok': False, 'error': f'ChatCompletions:{type(e).__name__}: {e}', 'model': model_name, 'api': 'chat_completions'}


def _sandbox_analyze_file_images_tool(args: dict | None = None, messages: list | None = None, client_override=None, model: str | None = None) -> dict:
    args = dict(args or {})
    mode = 'rendered'
    visual_exec_id = 'vis_' + uuid.uuid4().hex[:12]
    latest_user_text = _sandbox_latest_user_text(messages or [])
    if not str(args.get('query') or args.get('prompt') or '').strip() and latest_user_text:
        args['query'] = latest_user_text
    if not str(args.get('target') or '').strip():
        auto_target = _sandbox_visual_target_from_text(str(args.get('query') or args.get('prompt') or latest_user_text or ''))
        if auto_target:
            args['target'] = auto_target
    if not _sandbox_tools_enabled():
        return {'ok': False, 'error': 'sandbox_tools_disabled'}
    try:
        target, rel = _sandbox_resolve_path(args.get('path') or args.get('filename') or '', messages or [], must_exist=True)
    except FileNotFoundError:
        return {'ok': False, 'error': 'file_not_found'}
    except Exception as e:
        return {'ok': False, 'error': str(e or 'invalid_path')}
    if not os.path.isfile(target):
        return {'ok': False, 'error': 'not_a_file', 'path': rel}
    if str(rel or '').replace('\\', '/').lstrip('/').startswith('.app3_vision/'):
        return {**_sandbox_result_base(messages or []), 'ok': False, 'path': rel, 'mode': mode, 'image_count': 0, 'analyzed_count': 0, 'error': 'internal_vision_artifact_not_user_file', 'message': 'sandbox_analyze_file_images only accepts user/imported source files, not .app3_vision intermediate outputs.'}

    ext = os.path.splitext(rel)[1].lower()
    intent_text_for_policy = ' '.join([
        str(args.get('query') or args.get('prompt') or ''),
        str(args.get('target') or ''),
        str(latest_user_text or ''),
    ]).strip()
    evidence_policy = _sandbox_file_evidence_policy(ext, query=intent_text_for_policy, target=str(args.get('target') or ''), filename=rel)
    if evidence_policy.get('kind') == 'spreadsheet' and not bool(evidence_policy.get('allow_visual')):
        return {
            **_sandbox_result_base(messages or []),
            'ok': False,
            'path': rel,
            'mode': mode,
            'image_count': 0,
            'analyzed_count': 0,
            'error': 'visual_not_needed',
            'evidence_policy': evidence_policy,
            'instruction': 'This spreadsheet question should use sandbox_read_file structured cell text first. Use sandbox_analyze_file_images only for explicit chart/layout/format/page/merged-cell visual questions.',
        }
    if ext in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff'}:
        image_rel = rel
        images = [{
            'index': 1,
            'path': image_rel,
            'source': 'direct_image',
            'label': os.path.basename(rel),
            'width': 0,
            'height': 0,
            'bytes': int(os.path.getsize(target) if os.path.exists(target) else 0),
        }]
        focus_crop_execution = _sandbox_generate_focus_crops(image_rel, messages or [], visual_exec_id) if _sandbox_focus_crop_requested(args, intent_text_for_policy) else {}
        focus_crop_images = [dict(row) for row in (focus_crop_execution.get('images') or []) if isinstance(row, dict)]
        if focus_crop_images:
            images.extend(focus_crop_images)
        diagnostics = {
            'requested_mode': mode,
            'direct_image': True,
            'focus_crop_count': len(focus_crop_images),
            'focus_crop_used_for_model': bool(focus_crop_images),
        }
        extract_errors = []
    else:
        document_exts = {'.pdf', '.doc', '.docx', '.ppt', '.pptx'}
        is_document_visual_review = ext in document_exts
        broad_review = False
        explicit_visual_target = False
        try:
            intent_text = ' '.join([str(args.get('query') or args.get('prompt') or ''), str(latest_user_text or '')]).strip()
            explicit_visual_target = bool(str(args.get('target') or '').strip() or _sandbox_has_explicit_visual_target(intent_text))
            broad_review = _sandbox_broad_document_review_query(intent_text)
            if is_document_visual_review and not explicit_visual_target:
                broad_review = True
            default_images = _sandbox_cfg_int('SANDBOX_FILE_IMAGE_REVIEW_MAX_IMAGES', 24, min_value=1, max_value=80) if broad_review else _sandbox_cfg_int('SANDBOX_FILE_IMAGE_MAX_IMAGES', 12, min_value=1, max_value=80)
            requested_images = int(args.get('max_images') or default_images or 12)
            if broad_review:
                requested_images = max(requested_images, int(default_images or 24))
            max_images = max(1, min(requested_images, _sandbox_cfg_int('SANDBOX_FILE_IMAGE_HARD_MAX_IMAGES', 48, min_value=1, max_value=80)))
        except Exception:
            max_images = _sandbox_cfg_int('SANDBOX_FILE_IMAGE_REVIEW_MAX_IMAGES', 24, min_value=1, max_value=80) if is_document_visual_review else _sandbox_cfg_int('SANDBOX_FILE_IMAGE_MAX_IMAGES', 12, min_value=1, max_value=80)
        try:
            intent_text = ' '.join([str(args.get('query') or args.get('prompt') or ''), str(latest_user_text or '')]).strip()
            explicit_visual_target = bool(str(args.get('target') or '').strip() or _sandbox_has_explicit_visual_target(intent_text))
            broad_review = bool(broad_review or _sandbox_broad_document_review_query(intent_text))
            if is_document_visual_review and not explicit_visual_target:
                broad_review = True
            default_pages = _sandbox_cfg_int('SANDBOX_FILE_IMAGE_REVIEW_MAX_PAGES', 24, min_value=1, max_value=80) if broad_review else _sandbox_cfg_int('SANDBOX_FILE_IMAGE_MAX_PAGES', 12, min_value=1, max_value=80)
            requested_pages = int(args.get('max_pages') or default_pages or 12)
            if broad_review:
                requested_pages = max(requested_pages, int(default_pages or 24))
            max_pages = max(1, min(requested_pages, _sandbox_cfg_int('SANDBOX_FILE_IMAGE_HARD_MAX_PAGES', 48, min_value=1, max_value=80)))
        except Exception:
            max_pages = _sandbox_cfg_int('SANDBOX_FILE_IMAGE_REVIEW_MAX_PAGES', 24, min_value=1, max_value=80) if is_document_visual_review else _sandbox_cfg_int('SANDBOX_FILE_IMAGE_MAX_PAGES', 12, min_value=1, max_value=80)
        out_dir_rel = '.app3_vision/' + hashlib.sha1((rel + '|' + str(time.time())).encode('utf-8', 'ignore')).hexdigest()[:16]
        script_rel = '.app3_vision_extract_images.py'
        try:
            script_path, _script_display = _sandbox_resolve_path(script_rel, messages or [])
            os.makedirs(os.path.dirname(script_path), exist_ok=True)
            with open(script_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(_sandbox_file_image_extract_script())
        except Exception as e:
            return {**_sandbox_result_base(messages or []), 'ok': False, 'path': rel, 'error': f'script_write_failed:{type(e).__name__}: {e}'}
        target_query = str(args.get('target') or args.get('query') or args.get('prompt') or '').strip()
        if broad_review and not explicit_visual_target and 'APP3_BROAD_DOCUMENT_REVIEW' not in target_query:
            target_query = (target_query + '\nAPP3_BROAD_DOCUMENT_REVIEW').strip()
        extract = _sandbox_run_tool({
            'argv': ['python', script_rel, rel, out_dir_rel, str(max_images), str(max_pages), target_query],
            'timeout_s': max(60, min(float(args.get('timeout_s') or app_getenv('SANDBOX_FILE_IMAGE_EXTRACT_TIMEOUT_S', '180') or 180), 600)),
        }, messages=messages or [])
        if not bool(extract.get('ok')) or int(extract.get('exit_code') or 0) != 0:
            return {**_sandbox_result_base(messages or []), 'ok': False, 'path': rel, 'mode': mode, 'image_count': 0, 'analyzed_count': 0, 'error': 'image_extract_failed', 'extract_result': extract}
        stdout = str(extract.get('stdout') or '').strip()
        try:
            payload = json.loads(stdout[stdout.find('{'):]) if '{' in stdout else {}
        except Exception as e:
            return {**_sandbox_result_base(messages or []), 'ok': False, 'path': rel, 'mode': mode, 'image_count': 0, 'analyzed_count': 0, 'error': f'image_extract_json_failed:{type(e).__name__}: {e}', 'stdout': stdout[:2000]}
        images = [dict(x) for x in (payload.get('images') or []) if isinstance(x, dict)]
        diagnostics = payload.get('diagnostics') if isinstance(payload.get('diagnostics'), dict) else {}
        extract_errors = payload.get('errors') or []

    diagnostic_summary = _sandbox_file_image_diagnostic_summary(diagnostics)
    if not images:
        error_name = 'target_page_not_found' if any(str(x or '') == 'target_page_not_found' for x in (extract_errors or [])) else 'no_images_extracted'
        return {**_sandbox_result_base(messages or []), 'ok': False, 'path': rel, 'mode': mode, 'image_count': 0, 'analyzed_count': 0, 'error': error_name, 'extract_errors': extract_errors, 'diagnostics': diagnostics, 'diagnostic_summary': diagnostic_summary}

    extracted_image_limit = int(max_images) if 'max_images' in locals() else 0
    requested_after_extract = int(args.get('max_images') or extracted_image_limit or len(images) or 1)
    if bool(locals().get('focus_crop_images')):
        requested_after_extract = max(requested_after_extract, 1 + len(focus_crop_images))
    if bool(locals().get('broad_review')) and extracted_image_limit:
        requested_after_extract = max(requested_after_extract, extracted_image_limit, len(images))
    max_images = max(1, min(requested_after_extract, _sandbox_cfg_int('SANDBOX_FILE_IMAGE_HARD_MAX_IMAGES', 48, min_value=1, max_value=80)))
    prompt = str(args.get('query') or args.get('prompt') or '').strip()
    vision_model = _sandbox_visual_model_name(model, args)
    endpoint_mode = _sandbox_client_endpoint_mode(client_override)

    def attach_data_urls(rows: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
        render_diag = diagnostics.get('pdf_render') if isinstance(diagnostics, dict) and isinstance(diagnostics.get('pdf_render'), dict) else {}
        target_note = ''
        if render_diag.get('target_terms'):
            target_note = (
                f"\n目标定位：terms={render_diag.get('target_terms')} found={render_diag.get('target_found')} "
                f"selected_pages={render_diag.get('selected_pages')}"
                "\n如果目标未定位成功，不要把第一页或其他页面当作目标图回答。"
            )
        selected_pages = []
        try:
            if isinstance(render_diag.get('selected_pages'), list):
                selected_pages = [int(x) for x in render_diag.get('selected_pages') if str(x).strip()]
        except Exception:
            selected_pages = []
        review_contract = (
            '下面附带的是 sandbox_analyze_file_images 从导入文件渲染出的真实页面/图片。请逐张观察 input_image 的视觉内容后再回答。\n'
            '硬性要求：如果这是整体文档审阅，最终回答必须基于页面证据展开，至少点名 6 个以上具体页面/图像标签或可见文本；'
            '必须同时融合文本层/OOXML 诊断事实、渲染页可见版式、公式/域代码、图表与正文一致性。'
            '不要只给通用论文评价模板；如果无法确认某页内容，就说明对应页未能确认。\n'
            '输出建议：先说已检查的页数和页码范围，再列主要问题，每条问题尽量给“页码/可见内容/影响/修法”。'
        )
        content = [{'type': 'input_text', 'text': (review_contract + f'\n文件：{rel}\n模式：{mode}\n用户关注点：{prompt or "识别文件里的视觉内容。"}' + target_note)[:6000]}]
        out_rows: list[dict] = []
        errors: list[str] = []
        for item in rows[:max_images]:
            row = dict(item)
            image_rel = str(row.get('path') or '').strip()
            try:
                image_abs, _image_display = _sandbox_resolve_path(image_rel, messages or [], must_exist=True)
                data_url, data_err, data_bytes = _sandbox_data_url_for_image(image_abs)
            except Exception as e:
                data_url, data_err, data_bytes = '', f'image_path_invalid:{type(e).__name__}: {e}', 0
            row['data_bytes'] = data_bytes
            row['ok'] = bool(data_url and not data_err)
            if data_err:
                row['error'] = str(data_err or '')[:500]
                errors.append(str(data_err or '')[:300])
            else:
                page_label = ''
                try:
                    if selected_pages and (len(out_rows) < len(selected_pages)):
                        page_label = f'page {selected_pages[len(out_rows)]}'
                except Exception:
                    page_label = ''
                label_text = str(row.get('label') or image_rel or '').strip()
                if page_label or label_text:
                    content.append({'type': 'input_text', 'text': f'【页面图像 {len(out_rows) + 1}】{page_label or ""} label={label_text}。回答中引用本页时请使用这个页码/标签。'})
                content.append({'type': 'input_image', 'image_url': data_url, 'detail': 'high'})
            out_rows.append(row)
        return out_rows, ([{'role': 'user', 'content': content}] if len(content) > 1 else []), errors

    if endpoint_mode == 'responses':
        response_images, response_input_items, build_errors = attach_data_urls(images)
        visual_input_count = len([x for x in response_images if bool(x.get('ok'))])
        document_visual_items = _sandbox_document_visual_activity_items(rel, response_images, diagnostics, messages or [], visual_exec_id)
        focus_crop_items = _sandbox_focus_crop_activity_items(response_images, messages or [], visual_exec_id)
        return {
            **_sandbox_result_base(messages or []),
            'ok': bool(response_input_items),
            'path': rel,
            'mode': mode,
            'endpoint_mode': 'responses',
            'analysis_deferred_to_responses': bool(response_input_items),
            'visual_input_deferred_to': 'responses' if response_input_items else '',
            'visual_processing_stage': 'sandbox_rendered_pages_attached_to_responses' if response_input_items else 'responses_image_input_build_failed',
            'visual_exec_id': visual_exec_id,
            'sandbox_visual_role': 'render_select_store_images',
            'model_visual_role': 'interpret_attached_input_images',
            'instruction': 'Sandbox rendered/selected the file pages and attached them as input_image items for the next /responses round. The sandbox does not interpret the pixels in this lane; the Responses model must inspect the attached images directly before answering. If target_found is false, say the target page/figure was not located instead of answering from another page.',
            'image_count': len(images),
            'selected_image_count': len(response_images),
            'visual_input_count': visual_input_count,
            'analyzed_count': 0,
            'images': response_images,
            'focus_crop_execution': dict(locals().get('focus_crop_execution') or {}),
            'focus_crop_items': focus_crop_items,
            'focus_crop_count': len(focus_crop_items),
            'document_visual_items': document_visual_items,
            'document_page_count': len([row for row in response_images if isinstance(row, dict) and str(row.get('source') or '').strip().lower() == 'rendered_page']),
            'extract_errors': extract_errors,
            'diagnostics': diagnostics,
            'diagnostic_summary': diagnostic_summary,
            'vision_model': vision_model,
            'error': '' if response_input_items else 'responses_image_input_build_failed',
            'image_input_errors': build_errors[:8],
            '_responses_input_items': response_input_items,
        }

    if not vision_model:
        document_visual_items = _sandbox_document_visual_activity_items(rel, images[:max_images], diagnostics, messages or [], visual_exec_id)
        focus_crop_items = _sandbox_focus_crop_activity_items(images[:max_images], messages or [], visual_exec_id)
        return {**_sandbox_result_base(messages or []), 'ok': False, 'path': rel, 'mode': mode, 'endpoint_mode': endpoint_mode, 'image_count': len(images), 'analyzed_count': 0, 'images': images, 'focus_crop_execution': dict(locals().get('focus_crop_execution') or {}), 'focus_crop_items': focus_crop_items, 'focus_crop_count': len(focus_crop_items), 'document_visual_items': document_visual_items, 'document_page_count': len([row for row in images[:max_images] if isinstance(row, dict) and str(row.get('source') or '').strip().lower() == 'rendered_page']), 'extract_errors': extract_errors, 'diagnostics': diagnostics, 'diagnostic_summary': diagnostic_summary, 'vision_model': '', 'error': 'vision_model_not_configured'}

    analyses = []
    for item in images[:max_images]:
        image_rel = str(item.get('path') or '').strip()
        try:
            image_abs, _image_display = _sandbox_resolve_path(image_rel, messages or [], must_exist=True)
            data_url, data_err, data_bytes = _sandbox_data_url_for_image(image_abs)
        except Exception as e:
            data_url, data_err, data_bytes = '', f'image_path_invalid:{type(e).__name__}: {e}', 0
        row = dict(item)
        row['data_bytes'] = data_bytes
        if data_err:
            row.update({'ok': False, 'error': data_err})
            analyses.append(row)
            continue
        vision = _sandbox_analyze_one_image_with_model(data_url, prompt=prompt, source_label=f"{rel} / {row.get('label') or image_rel}", model=vision_model, client_override=client_override)
        row['ok'] = bool(vision.get('ok'))
        row['analysis'] = str(vision.get('text') or '')[:_sandbox_cfg_int('SANDBOX_FILE_IMAGE_ANALYSIS_MAX_CHARS', 16000, min_value=2000, max_value=60000)]
        row['vision_model'] = str(vision.get('model') or vision_model or '')[:120]
        if vision.get('error'):
            row['error'] = str(vision.get('error') or '')[:500]
        analyses.append(row)
    ok_count = len([x for x in analyses if bool(x.get('ok'))])
    evidence_parts = [f"## image {row.get('index')}: {row.get('label') or row.get('path')}\n{str(row.get('analysis') or '').strip()}" for row in analyses if str(row.get('analysis') or '').strip()]
    document_visual_items = _sandbox_document_visual_activity_items(rel, analyses, diagnostics, messages or [], visual_exec_id)
    focus_crop_items = _sandbox_focus_crop_activity_items(analyses, messages or [], visual_exec_id)
    return {**_sandbox_result_base(messages or []), 'ok': ok_count > 0, 'path': rel, 'mode': mode, 'endpoint_mode': endpoint_mode, 'visual_exec_id': visual_exec_id, 'image_count': len(images), 'analyzed_count': ok_count, 'images': analyses, 'focus_crop_execution': dict(locals().get('focus_crop_execution') or {}), 'focus_crop_items': focus_crop_items, 'focus_crop_count': len(focus_crop_items), 'document_visual_items': document_visual_items, 'document_page_count': len([row for row in analyses if isinstance(row, dict) and str(row.get('source') or '').strip().lower() == 'rendered_page']), 'evidence': '\n\n'.join(evidence_parts)[:_sandbox_cfg_int('SANDBOX_FILE_IMAGE_EVIDENCE_MAX_CHARS', 80000, min_value=12000, max_value=240000)], 'extract_errors': extract_errors, 'diagnostics': diagnostics, 'diagnostic_summary': diagnostic_summary, 'vision_model': vision_model}
