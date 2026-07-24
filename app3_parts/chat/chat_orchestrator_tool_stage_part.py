# orchestrator prepare/tool-stage execution, stage normalization, and final-message assembly.

def _tool_orchestrator_prepare(model: str, messages: list, *, user_geo: dict | None = None, user_time: dict | None = None, client_override=None, enable_visual: bool = True, web_enabled: bool | None = None, web_k: int | None = None, web_max_pages: int | None = None):
    """统一编排准备阶段：这里只产出软提示，不提前绑定任何工具入口。"""
    _t_prepare0 = time.time()
    base_messages = list(messages or [])
    last_user_text = _latest_user_text_from_messages(base_messages)
    prefetch_decision = _orch_apply_primary_delivery_lock(_decide_tool_prefetch_once(model, base_messages, last_user_text, client_override=client_override))
    primary_delivery = _orch_normalize_primary_delivery(prefetch_decision)
    route_hint = _normalize_prefetch_route_mode(prefetch_decision)
    answer_strategy_hint = _normalize_prefetch_answer_strategy(prefetch_decision, route_mode=route_hint)
    file_gate = _decide_orchestrator_file_gate(
        model,
        base_messages,
        prefetch_decision=prefetch_decision,
        client_override=client_override,
    )
    file_hint_active = bool((file_gate or {}).get('file_hint_active'))
    soft_hint_text = _build_orchestrator_soft_hint(prefetch_decision, file_hint_active=file_hint_active, enable_visual=enable_visual)

    # Keep answer_messages as an internal message list, not an API-sanitized list.
    # The final answer builder still sanitizes before calling the model, but it needs
    # the internal _kind metadata here so already-compacted file/kb recall blocks are
    # not passed through the generic 4000-char message budget a second time.
    answer_messages = _orch_strip_lane_system_messages(list(base_messages), ('tool_runtime', 'orchestrator_soft_hint'))
    query_messages = _sanitize_messages_for_model(list(answer_messages))
    prepared_messages = _inject_runtime_tool_context(list(base_messages), user_geo=user_geo, allow_weather_tool=True, route_signals=prefetch_decision)
    prepared_messages = _inject_orchestrator_soft_hint(prepared_messages, soft_hint_text)
    prepared_messages = _sanitize_messages_for_model(prepared_messages)

    soft_web_research_hit = _prefetch_soft_web_research_hit(
        prefetch_decision,
        route_mode=route_hint,
        answer_strategy=answer_strategy_hint,
    )

    ctx = {
        'base_messages': base_messages,
        'prepared_messages': prepared_messages,
        'tool_messages': prepared_messages,
        'answer_messages': answer_messages,
        'query_messages': query_messages,
        'last_user_text': last_user_text,
        'visual_ctx': None,
        'prefetch_decision': prefetch_decision,
        'route_mode': route_hint,
        'primary_delivery': primary_delivery,
        'answer_strategy': answer_strategy_hint,
        'file_gate': file_gate,
        'should_short_circuit_to_file_generation': False,
        'file_hint_active': file_hint_active,
        'allow_location_tool': True,
        'allow_weather_tool': True,
        'should_use_web_research': False,
        'soft_web_research_hit': bool(soft_web_research_hit),
        'web_enabled': web_enabled,
        'web_k': web_k,
        'web_max_pages': web_max_pages,
        'user_time': user_time,
        'soft_hint_text': soft_hint_text,
    }
    try:
        app_logger.info(
            '[ORCH_PREPARE_DONE] model=%s ms=%s primary_delivery=%s route_hint=%s answer_strategy_hint=%s soft_web_research_hit=%s route_confidence=%.2f current_world_risk=%s need_external_evidence=%s location_action_hint=%s weather_action_hint=%s file_action_hint=%s file_hint_active=%s visual_hint=%s allow_location_tool=%s allow_weather_tool=%s prepared_messages=%s user_text_len=%s',
            model,
            int((time.time() - _t_prepare0) * 1000),
            str(primary_delivery or 'unknown'),
            str(route_hint or 'direct_answer'),
            str(answer_strategy_hint or 'fast_direct'),
            bool(soft_web_research_hit),
            float((prefetch_decision or {}).get('route_confidence') or 0.0),
            str((prefetch_decision or {}).get('current_world_risk') or 'low'),
            bool((prefetch_decision or {}).get('need_external_evidence')),
            str((prefetch_decision or {}).get('location_action') or 'none'),
            str((prefetch_decision or {}).get('weather_action') or 'none'),
            str((prefetch_decision or {}).get('file_action') or 'none'),
            bool(file_hint_active),
            str((((prefetch_decision or {}).get('visual_decision') or {}) if isinstance((prefetch_decision or {}).get('visual_decision'), dict) else {}).get('intent') or 'none'),
            True,
            True,
            len(prepared_messages or []),
            len(str(last_user_text or '')),
        )
    except Exception:
        pass
    return ctx

def _run_orchestrated_tool_stage(model: str, ctx: dict, *, client_override=None, show_steps: bool = False, label: str = '', emit=None) -> dict:
    """统一工具阶段：直接消费第一次统一预判，再执行需要的工具。"""
    _ = show_steps, label
    messages = list((ctx or {}).get('base_messages') or [])
    prepared_messages = list((ctx or {}).get('prepared_messages') or [])
    tool_messages = list((ctx or {}).get('tool_messages') or prepared_messages or [])
    answer_messages_seed = list((ctx or {}).get('answer_messages') or _orch_strip_lane_system_messages(tool_messages))
    query_messages = list((ctx or {}).get('query_messages') or answer_messages_seed)
    last_user_text = str((ctx or {}).get('last_user_text') or '')
    prefetch_decision = _orch_apply_primary_delivery_lock((ctx or {}).get('prefetch_decision') or {})
    file_hint_active = bool((ctx or {}).get('file_hint_active'))

    tool_plan = _decide_orchestrated_tool_plan_once(
        model,
        messages,
        last_user_text,
        prefetch_decision=prefetch_decision,
        file_hint_active=file_hint_active,
        enable_visual=True,
        image_generation_enabled=bool((ctx or {}).get('image_generation_enabled')),
        image_generation_settings=(ctx or {}).get('image_generation_settings'),
        client_override=client_override,
        user_geo=ctx.get('user_geo'),
        user_time=ctx.get('user_time'),
    )

    tool_records = []
    tool_counts = {'web_search': 0, 'fetch_url': 0, 'fetch_urls': 0, 'get_location': 0, 'get_weather': 0}
    latest_location_payload = None
    latest_weather_payload = None
    weather_present = None
    planner_direct_answer = ''
    visual_ctx = (ctx or {}).get('visual_ctx') if isinstance((ctx or {}).get('visual_ctx'), dict) else None
    image_generation_result = {}
    image_task_plan = {}

    visual_decision = (prefetch_decision or {}).get('visual_decision') if isinstance((prefetch_decision or {}).get('visual_decision'), dict) else {}
    visual_intent_hint = str((visual_decision or {}).get('intent') or '').strip().lower()
    image_generation_subject_for_record = ''
    if visual_ctx is None and bool(tool_plan.get('use_visual')) and visual_intent_hint in {'image_search'}:
        try:
            visual_ctx = _materialize_visual_context_from_decision(
                model,
                messages,
                last_user_text,
                visual_decision,
                client_override=client_override,
            )
        except Exception:
            visual_ctx = None

    if bool(tool_plan.get('use_location')):
        nm = 'get_location'
        if emit:
            emit(nm, None)
        result = _exec_tool(nm, {'query': last_user_text}, user_geo=ctx.get('user_geo'), messages=messages, client_override=client_override)
        tool_counts[nm] += 1
        compact = _compress_tool_result_for_model(nm, result, user_text=last_user_text)
        tool_records.append({'name': nm, 'content': json.dumps(compact, ensure_ascii=False) if not isinstance(compact, str) else compact})
        if isinstance(result, dict) and result.get('_kind') == 'location':
            latest_location_payload = result

    if bool(tool_plan.get('use_weather')):
        nm = 'get_weather'
        if emit:
            emit(nm, None)
        result = _exec_tool(nm, {'query': last_user_text}, user_geo=ctx.get('user_geo'), messages=messages, client_override=client_override)
        tool_counts[nm] += 1
        compact = _compress_tool_result_for_model(nm, result, user_text=last_user_text)
        tool_records.append({'name': nm, 'content': json.dumps(compact, ensure_ascii=False) if not isinstance(compact, str) else compact})
        if isinstance(result, dict) and result.get('_kind') == 'weather':
            latest_weather_payload = result
            if result.get('ok'):
                try:
                    weather_present = _decide_weather_present_mode_once(model, messages or [], last_user_text, client_override=client_override or client_gpt)
                except Exception:
                    weather_present = {'mode': 'card', 'reason': 'fallback_error', 'source': 'fallback'}

    image_tool_requested = bool(tool_plan.get('use_image_mode'))
    if image_tool_requested:
        preplanned_image_task_plan = (ctx or {}).get('preplanned_image_task_plan') if isinstance(ctx, dict) else None
        if isinstance(preplanned_image_task_plan, dict) and str(preplanned_image_task_plan.get('task_type') or '').strip():
            image_task_plan = dict(preplanned_image_task_plan)
            image_task_plan.setdefault('source', 'preplanned')
        else:
            try:
                image_task_plan = _plan_image_task_once(
                    model,
                    messages or [],
                    last_user_text,
                    image_generation_settings=(ctx or {}).get('image_generation_settings'),
                    client_override=client_override,
                )
            except Exception as e:
                image_task_plan = {
                'ok': False,
                'task_type': 'unclear',
                'prompt': '',
                'need_clarify': True,
                'clarify_question': '请再明确一下你是要生成新图、改图，还是参考某张图来出图。',
                'reason': f'image_task_plan_error:{type(e).__name__}',
                'candidate_rows': [],
                'edit_target_rows': [],
                'reference_rows': [],
                'ignore_rows': [],
                'selected_rows': [],
                'edit_enabled': False,
                'source': 'exception',
            }

        forced_image_task_type = str((ctx or {}).get('direct_image_handoff_task_type') or '').strip().lower()
        if forced_image_task_type:
            forced_aliases = {
                'analysis': 'existing_image_analysis', 'analyze': 'existing_image_analysis', 'image_analysis': 'existing_image_analysis',
                'existing_image': 'existing_image_analysis', 'existing_image_analysis': 'existing_image_analysis',
                'generate': 'image_generation', 'generation': 'image_generation', 'text_to_image': 'text_to_image',
                'image_generation': 'image_generation', 'txt2img': 'text_to_image',
                'edit': 'image_edit', 'image_edit': 'image_edit', 'image_editing': 'image_edit',
                'reference_generate': 'reference_generate', 'reference_edit': 'reference_edit', 'variation': 'variation',
            }
            forced_image_task_type = forced_aliases.get(forced_image_task_type, forced_image_task_type)
            if forced_image_task_type in {'existing_image_analysis', 'image_generation', 'text_to_image', 'image_edit', 'reference_generate', 'reference_edit', 'variation'}:
                image_task_plan = dict(image_task_plan or {})
                image_task_plan['direct_image_handoff_task_type'] = forced_image_task_type
                image_task_plan['source'] = (str(image_task_plan.get('source') or 'image_planner') + '+direct_image_handoff_hint')[:96]
                if not str(image_task_plan.get('prompt') or '').strip():
                    image_task_plan['prompt'] = str((ctx or {}).get('direct_image_handoff_reason') or last_user_text or '').strip()[:1000]

        planned_task_type = str((image_task_plan or {}).get('task_type') or '').strip().lower()
        prompt_subject = str((image_task_plan or {}).get('prompt') or '').strip() or str(tool_plan.get('image_generation_subject') or '').strip() or str((visual_decision or {}).get('subject') or '').strip()
        image_generation_subject_for_record = prompt_subject
        clarify_question = str((image_task_plan or {}).get('clarify_question') or '').strip()
        edit_enabled_now = bool((image_task_plan or {}).get('edit_enabled'))
        selected_rows = [dict(r) for r in ((image_task_plan or {}).get('selected_rows') or []) if isinstance(r, dict)]
        edit_target_rows = [dict(r) for r in ((image_task_plan or {}).get('edit_target_rows') or []) if isinstance(r, dict)]
        reference_rows = [dict(r) for r in ((image_task_plan or {}).get('reference_rows') or []) if isinstance(r, dict)]
        ignore_rows = [dict(r) for r in ((image_task_plan or {}).get('ignore_rows') or []) if isinstance(r, dict)]
        responses_native_image_inputs_enabled = False
        try:
            native_checker = globals().get('_image_generation_should_use_responses_native')
            settings_normalizer = globals().get('_normalize_image_generation_settings')
            normalized_image_settings = settings_normalizer((ctx or {}).get('image_generation_settings')) if callable(settings_normalizer) else ((ctx or {}).get('image_generation_settings') or {})
            responses_native_image_inputs_enabled = bool(native_checker(normalized_image_settings or {}, client_override=client_override)) if callable(native_checker) else False
        except Exception:
            responses_native_image_inputs_enabled = False

        def _image_mode_row_keys(rows):
            out = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                key = str(row.get('image_id') or row.get('attachment_key') or row.get('url') or '').strip()
                if key:
                    out.append(key[:120])
            return out

        def _image_mode_candidate_log_rows(rows):
            out = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                out.append({
                    'id': str(row.get('image_id') or ''),
                    'role_image_id': str(row.get('role_image_id') or ''),
                    'role_label': str(row.get('role_label') or ''),
                    'global_label': str(row.get('global_label') or ''),
                    'recency_rank': row.get('recency_rank'),
                    'role': str(row.get('role') or '')[:20],
                    'message_index': row.get('message_index'),
                    'binding_mode': str(row.get('binding_mode') or '')[:30],
                })
            return out

        try:
            app_logger.info(
                '[IMAGE_MODE_PLAN] model=%s planner_source=%s visual_hint=%s task_type=%s need_clarify=%s edit_enabled=%s prompt=%s candidates=%s candidate_order=%s selected=%s edit_targets=%s references=%s ignored=%s reason=%s clarify=%s',
                model,
                str((image_task_plan or {}).get('source') or ''),
                visual_intent_hint,
                planned_task_type or 'none',
                bool((image_task_plan or {}).get('need_clarify')),
                edit_enabled_now,
                prompt_subject[:160],
                len((image_task_plan or {}).get('candidate_rows') or []),
                json.dumps(_image_mode_candidate_log_rows((image_task_plan or {}).get('candidate_rows') or []), ensure_ascii=False),
                json.dumps(_image_mode_row_keys(selected_rows), ensure_ascii=False),
                json.dumps(_image_mode_row_keys(edit_target_rows), ensure_ascii=False),
                json.dumps(_image_mode_row_keys(reference_rows), ensure_ascii=False),
                json.dumps(_image_mode_row_keys(ignore_rows), ensure_ascii=False),
                str((image_task_plan or {}).get('reason') or '')[:160],
                clarify_question[:160],
            )
        except Exception:
            pass

        needs_source_images = planned_task_type in {'image_edit', 'reference_edit', 'reference_generate', 'variation'}
        if planned_task_type == 'existing_image_analysis':
            task_mode = 'analyze'
        elif planned_task_type in {'image_edit', 'reference_edit', 'variation'}:
            task_mode = 'edit'
        elif planned_task_type == 'reference_generate':
            # Reference-image generation with Responses native image_generation can
            # use input_image directly without requiring the old separate edit API.
            task_mode = 'reference_generate' if responses_native_image_inputs_enabled else ('edit' if edit_enabled_now else 'generate')
        else:
            task_mode = 'generate'

        if planned_task_type == 'existing_image_analysis' and not bool((image_task_plan or {}).get('need_clarify')):
            analysis_rows = selected_rows or edit_target_rows or reference_rows
            analysis_binding_mode = ''
            analysis_binding_desc = ''
            for row in analysis_rows:
                if not isinstance(row, dict):
                    continue
                mode = str(row.get('binding_mode') or '').strip()
                desc = str(row.get('binding_desc') or '').strip()
                if not analysis_binding_mode and mode:
                    analysis_binding_mode = mode
                if not analysis_binding_desc and desc:
                    analysis_binding_desc = desc
            if analysis_rows:
                image_generation_subject_for_record = ''
                analysis_rows_meta = _image_mode_row_log_meta(analysis_rows, limit=4)
                try:
                    app_logger.info(
                        '[IMAGE_MODE_ANALYZE_BIND] model=%s rows=%s binding_mode=%s binding_desc=%s source_rows=%s reason=%s',
                        model,
                        len(analysis_rows[:4]),
                        analysis_binding_mode or 'explicit_selected_rows',
                        analysis_binding_desc[:120],
                        json.dumps(analysis_rows_meta, ensure_ascii=False),
                        str((image_task_plan or {}).get('reason') or 'image_mode_analysis')[:160],
                    )
                except Exception:
                    pass
                visual_ctx = {
                    'intent': 'existing_image_analysis',
                    'decision': {'intent': 'existing_image_analysis', 'reason': str((image_task_plan or {}).get('reason') or 'image_mode_analysis')[:120]},
                    'urls': [],
                    'text_hints': [],
                    'binding_mode': analysis_binding_mode or 'explicit_selected_rows',
                    'binding_desc': analysis_binding_desc or 'image_mode_secondary_planner',
                    'rows': analysis_rows_meta,
                    'requires_sandbox_tool': True,
                }
                image_generation_result = {
                    'ok': False,
                    'artifacts': [],
                    'task_mode': 'analyze',
                    'image_task_type': 'existing_image_analysis',
                    'need_generation': False,
                    'need_sandbox_visual_tool': True,
                    'error': 'existing_image_analysis_requires_analyze_existing_image_sandbox_tool',
                    'analysis_binding': {
                        'binding_mode': analysis_binding_mode or 'explicit_selected_rows',
                        'binding_desc': analysis_binding_desc or 'image_mode_secondary_planner',
                        'rows': analysis_rows_meta,
                    },
                }
                try:
                    app_logger.info(
                        '[IMAGE_MODE_ANALYZE_CONTEXT] model=%s visual_binding_mode=%s visual_binding_desc=%s tool_record_binding=%s user_text=%s',
                        model,
                        str((visual_ctx or {}).get('binding_mode') or ''),
                        str((visual_ctx or {}).get('binding_desc') or '')[:120],
                        json.dumps((image_generation_result or {}).get('analysis_binding') or {}, ensure_ascii=False),
                        str(last_user_text or '')[:160],
                    )
                except Exception:
                    pass
            else:
                image_generation_result = {
                    'ok': False,
                    'need_clarification': True,
                    'error': '当前图片分析需要先明确相关图片',
                    'clarification_question': clarify_question or '请明确要分析哪一张图。',
                    'artifacts': [],
                    'task_mode': 'analyze',
                    'image_task_type': 'existing_image_analysis',
                }
        elif bool((image_task_plan or {}).get('need_clarify')) or not prompt_subject:
            image_generation_result = {
                'ok': False,
                'need_clarification': True,
                'error': '缺少图片任务信息' if planned_task_type == 'unclear' else ('缺少改图要求' if task_mode == 'edit' else '缺少出图主体'),
                'clarification_question': clarify_question or ('请再明确一下你的图片需求。' if planned_task_type == 'unclear' else ('你想怎么修改这张图片？' if task_mode == 'edit' else '你想生成什么主体？')),
                'artifacts': [],
                'task_mode': task_mode,
                'image_task_type': planned_task_type or 'unclear',
            }
        elif needs_source_images and not edit_enabled_now and not responses_native_image_inputs_enabled:
            image_generation_result = {
                'ok': False,
                'need_clarification': True,
                'error': '当前图片编辑未启用，无法使用上传图片作为编辑或参考输入',
                'clarification_question': clarify_question or '请先在设置里启用图片编辑，或改成纯文生图。',
                'artifacts': [],
                'task_mode': 'edit',
                'image_task_type': planned_task_type or 'unclear',
            }
        else:
            image_sources = []
            source_seen = set()
            source_group_rows: list[dict] = []
            try:
                source_groups = (image_task_plan or {}).get('direct_image_source_groups') if isinstance(image_task_plan, dict) else {}
                if isinstance(source_groups, dict):
                    ordered_group_rows = source_groups.get('ordered_rows') if isinstance(source_groups.get('ordered_rows'), list) else []
                    if ordered_group_rows:
                        for row in ordered_group_rows:
                            if isinstance(row, dict):
                                source_group_rows.append(dict(row))
                    else:
                        for group_key in ('current_user_rows', 'assistant_rows', 'historical_rows'):
                            for row in source_groups.get(group_key) or []:
                                if isinstance(row, dict):
                                    source_group_rows.append(dict(row))
            except Exception:
                source_group_rows = []
            max_source_images = 8
            source_execution_rows: list[dict] = []
            if edit_target_rows or reference_rows:
                source_execution_rows = [*edit_target_rows, *reference_rows]
            elif selected_rows:
                source_execution_rows = [*selected_rows]
            else:
                source_execution_rows = [*source_group_rows]
            for row in source_execution_rows:
                url = str((row or {}).get('url') or '').strip()
                if not url or url in source_seen:
                    continue
                source_seen.add(url)
                image_sources.append(url)
                if len(image_sources) >= max_source_images:
                    break
            if needs_source_images and not image_sources:
                image_generation_result = {
                    'ok': False,
                    'need_clarification': True,
                    'error': '当前图片任务需要先明确相关图片',
                    'clarification_question': clarify_question or '请明确要编辑或参考哪一张图。',
                    'artifacts': [],
                    'task_mode': task_mode,
                    'image_task_type': planned_task_type or 'unclear',
                }
            else:
                try:
                    app_logger.info(
                        '[IMAGE_MODE_EXEC] model=%s task_type=%s task_mode=%s prompt=%s source_image_count=%s source_images=%s',
                        model,
                        planned_task_type or 'none',
                        task_mode,
                        prompt_subject[:200],
                        len(image_sources),
                        json.dumps([str(u or '')[:180] for u in image_sources[:4]], ensure_ascii=False),
                    )
                except Exception:
                    pass
                if emit:
                    emit('image_generation', {'subject': prompt_subject, 'task_mode': task_mode, 'image_task_type': planned_task_type})
                image_generation_result = _generate_image_artifacts(
                    prompt_subject,
                    settings=(ctx or {}).get('image_generation_settings'),
                    client_override=client_override,
                    image_sources=image_sources,
                    task_mode=task_mode,
                    response_model=model,
                )
                if isinstance(image_generation_result, dict):
                    image_generation_result.setdefault('task_mode', task_mode)
                    image_generation_result.setdefault('image_task_type', planned_task_type or ('image_edit' if task_mode == 'edit' else 'text_to_image'))
                    try:
                        _time_mod = globals().get('time') or __import__('time')
                        result_created_at_ms = int(_time_mod.time() * 1000)
                    except Exception:
                        result_created_at_ms = 0
                    parent_image_id = ''
                    source_image_ids = []
                    try:
                        lineage_rows = list(source_execution_rows or [])
                        seen_lineage = set()
                        for source_row in lineage_rows:
                            if not isinstance(source_row, dict):
                                continue
                            source_id = str(source_row.get('stable_image_id') or source_row.get('current_user_image_id') or source_row.get('role_image_id') or source_row.get('attachment_key') or source_row.get('global_label') or source_row.get('image_id') or '').strip()
                            if source_id and source_id not in seen_lineage:
                                seen_lineage.add(source_id)
                                source_image_ids.append(source_id)
                        preferred_parent_rows = edit_target_rows if edit_target_rows else reference_rows
                        if preferred_parent_rows:
                            parent_row = dict(preferred_parent_rows[0] or {})
                            parent_image_id = str(parent_row.get('stable_image_id') or parent_row.get('current_user_image_id') or parent_row.get('role_image_id') or parent_row.get('attachment_key') or parent_row.get('global_label') or parent_row.get('image_id') or '').strip()
                        elif source_image_ids:
                            parent_image_id = source_image_ids[0]
                    except Exception:
                        parent_image_id = ''
                        source_image_ids = []
                    artifacts_for_lineage = image_generation_result.get('artifacts') if isinstance(image_generation_result.get('artifacts'), list) else []
                    for artifact_idx, artifact in enumerate(artifacts_for_lineage, 1):
                        if not isinstance(artifact, dict):
                            continue
                        artifact.setdefault('source_role', 'assistant')
                        artifact.setdefault('source_type', 'generated')
                        artifact.setdefault('operation', task_mode or 'generate')
                        if result_created_at_ms:
                            artifact.setdefault('created_at_ms', result_created_at_ms)
                        artifact.setdefault('image_seq', artifact_idx)
                        if parent_image_id:
                            artifact.setdefault('parent_image_id', parent_image_id)
                        if source_image_ids:
                            artifact.setdefault('source_image_ids', list(source_image_ids))
                            artifact.setdefault('derived_from', list(source_image_ids))
                try:
                    app_logger.info(
                        '[IMAGE_MODE_RESULT] model=%s ok=%s task_type=%s task_mode=%s artifacts=%s need_clarification=%s error=%s',
                        model,
                        bool((image_generation_result or {}).get('ok')),
                        str((image_generation_result or {}).get('image_task_type') or planned_task_type or ''),
                        str((image_generation_result or {}).get('task_mode') or task_mode or ''),
                        len((image_generation_result or {}).get('artifacts') or []),
                        bool((image_generation_result or {}).get('need_clarification')),
                        str((image_generation_result or {}).get('error') or '')[:200],
                    )
                except Exception:
                    pass

    if image_tool_requested:
        try:
            app_logger.info(
                '[IMAGE_MODE_FINAL] model=%s planned_task_type=%s final_ok=%s task_mode=%s need_clarification=%s tool_record_kind=%s',
                model,
                str((image_task_plan or {}).get('task_type') or ''),
                bool((image_generation_result or {}).get('ok')),
                str((image_generation_result or {}).get('task_mode') or ''),
                bool((image_generation_result or {}).get('need_clarification')),
                str((image_generation_result or {}).get('_kind') or 'image_generation_result'),
            )
        except Exception:
            pass
        image_generation_record = dict(image_generation_result or {})
        if image_generation_subject_for_record:
            image_generation_record['subject'] = image_generation_subject_for_record
        image_generation_record.setdefault('_kind', 'image_generation_result')
        try:
            app_logger.info(
                '[IMAGE_MODE_TOOL_RECORD] model=%s task_type=%s task_mode=%s has_subject=%s analysis_binding=%s',
                model,
                str(image_generation_record.get('image_task_type') or ''),
                str(image_generation_record.get('task_mode') or ''),
                bool(str(image_generation_record.get('subject') or '').strip()),
                json.dumps((image_generation_record.get('analysis_binding') or {}), ensure_ascii=False)[:500],
            )
        except Exception:
            pass
        tool_records.append({'name': 'image_task', 'content': image_generation_record})

    extra_context_bits = []
    try:
        visual_ref_builder = globals().get('_build_visual_reference_planning_context')
        visual_ref = visual_ref_builder(
            messages or [],
            user_text=last_user_text,
            max_items=3,
            max_chars=2400,
        ) if callable(visual_ref_builder) else {}
        visual_ref_text = str((visual_ref or {}).get('text') or '').strip()
        if visual_ref_text:
            extra_context_bits.append('visual_reference_context_for_planning:\n' + visual_ref_text)
    except Exception:
        visual_ref_text = ''
    visual_hint = _build_recent_visual_low_priority_hint(messages or [], max_messages=2, max_images_per_message=2, max_chars=520)
    if visual_hint:
        extra_context_bits.append('visual_context_for_planning: ' + visual_hint)
    try:
        visual_subject_hint = str((visual_decision or {}).get('subject') or '').strip()
        visual_reason_hint = str((visual_decision or {}).get('reason') or (prefetch_decision or {}).get('route_reason') or '').strip()
        route_hint = str((prefetch_decision or {}).get('route_mode') or '').strip()
        strategy_hint = str((prefetch_decision or {}).get('answer_strategy') or '').strip()
        evidence_hint = bool((prefetch_decision or {}).get('need_external_evidence'))
        if visual_subject_hint or visual_reason_hint:
            extra_context_bits.append(
                'prefetch_visual_soft_hint: '
                + json.dumps({
                    'intent': visual_intent_hint,
                    'subject': visual_subject_hint[:160],
                    'reason': visual_reason_hint[:180],
                    'route_mode': route_hint[:40],
                    'answer_strategy': strategy_hint[:40],
                    'need_external_evidence': evidence_hint,
                }, ensure_ascii=False)
            )
    except Exception:
        pass
    if latest_location_payload:
        extra_context_bits.append(_planner_safe_text(json.dumps(_compress_tool_result_for_model('get_location', latest_location_payload, user_text=last_user_text), ensure_ascii=False), max_len=900))
    if latest_weather_payload:
        extra_context_bits.append(_planner_safe_text(json.dumps(_compress_tool_result_for_model('get_weather', latest_weather_payload, user_text=last_user_text), ensure_ascii=False), max_len=1200))
    if isinstance(visual_ctx, dict) and visual_ctx.get('intent') == 'image_search':
        try:
            payload = _visual_ctx_to_image_reply_payload(visual_ctx) or {}
            imgs = payload.get('images') or []
            subject = str(payload.get('subject') or '')
            extra_context_bits.append(f'已找到相关图片 subject={subject} count={len(imgs)}')
        except Exception:
            pass

    should_use_web_research = bool(tool_plan.get('use_web_research'))
    if should_use_web_research:
        enriched_messages, web_meta = _web_enrich_messages(
            query_messages,
            planner_text=last_user_text,
            user_geo=ctx.get('user_geo'),
            user_time=ctx.get('user_time'),
            web_enabled=ctx.get('web_enabled'),
            web_k=ctx.get('web_k'),
            web_max_pages=ctx.get('web_max_pages'),
            history=messages,
            extra_context='\n'.join(extra_context_bits),
            client_override=client_override,
            allow_weather_tool=True,
            model=model,
        )
    else:
        enriched_messages = answer_messages_seed
        web_meta = {'enabled': False, 'reason': 'prefetch_skip', 'planner_reason': str(tool_plan.get('web_reason') or '')[:120]}

    web_tool_record = _build_web_grounding_tool_record({'web_meta': web_meta})
    if web_tool_record:
        tool_records.append(web_tool_record)
        try:
            search_rounds = int(web_meta.get('search_rounds') or 0)
        except Exception:
            search_rounds = 0
        tool_counts['web_search'] = max(int(tool_counts.get('web_search') or 0), search_rounds or 1)

    actual_route_mode = 'direct_answer'
    primary_delivery_stage = str(tool_plan.get('primary_delivery') or '').strip().lower()
    if primary_delivery_stage in {'image', 'image_edit'}:
        actual_route_mode = 'visual'
    elif bool(tool_plan.get('request_file_generation')):
        actual_route_mode = 'file'
    elif bool(tool_plan.get('use_visual')):
        actual_route_mode = 'visual'
    elif should_use_web_research:
        actual_route_mode = 'web_research'
    elif bool(tool_plan.get('use_weather')):
        actual_route_mode = 'weather'
    elif bool(tool_plan.get('use_location')):
        actual_route_mode = 'location'

    return {
        'messages': messages,
        'prepared_messages': tool_messages,
        'tool_messages': tool_messages,
        'answer_messages': enriched_messages,
        'query_messages': query_messages,
        'last_user_text': last_user_text,
        'visual_ctx': visual_ctx,
        'tool_records': tool_records,
        'tool_counts': tool_counts,
        'latest_location_payload': latest_location_payload,
        'latest_weather_payload': latest_weather_payload,
        'weather_present': weather_present,
        'planner_direct_answer': planner_direct_answer,
        # 图片生成的成败只作为工具结果交给最终聊天模型，不在这里短路成固定话术。
        'tool_direct_content': '',
        'generated_artifacts': list((image_generation_result or {}).get('artifacts') or []),
        'image_generation_result': image_generation_result,
        'image_task_plan': image_task_plan,
        'web_meta': web_meta,
        'tool_plan': tool_plan,
        'request_file_generation': bool(tool_plan.get('request_file_generation')),
        'route_mode': actual_route_mode,
    }

def _run_orchestrator_once(model: str, messages: list, *, user_geo: dict | None = None, user_time: dict | None = None, client_override=None, visual_ctx: dict | None = None, enable_visual: bool = True, web_enabled: bool | None = None, web_k: int | None = None, web_max_pages: int | None = None, image_generation_enabled: bool = False, image_generation_settings: dict | None = None, show_steps: bool = False, label: str = '', emit=None, prepared_ctx: dict | None = None) -> tuple[dict, dict]:
    """统一执行一次 orchestrator：prepare → tool stage。"""
    _t_orch0 = time.time()
    ctx = dict(prepared_ctx or {}) if isinstance(prepared_ctx, dict) else _tool_orchestrator_prepare(
        model,
        messages or [],
        user_geo=user_geo,
        user_time=user_time,
        client_override=client_override,
        enable_visual=enable_visual,
        web_enabled=web_enabled,
        web_k=web_k,
        web_max_pages=web_max_pages,
    )
    if visual_ctx is not None:
        ctx["visual_ctx"] = visual_ctx
    stage = _run_orchestrated_tool_stage(
        model,
        {**ctx, "user_geo": user_geo, "user_time": user_time if user_time is not None else ctx.get("user_time"), "image_generation_enabled": bool(image_generation_enabled), "image_generation_settings": dict(image_generation_settings or {})},
        client_override=client_override,
        show_steps=show_steps,
        label=label,
        emit=emit,
    )
    try:
        web_meta = stage.get('web_meta') or {}
        tool_counts = stage.get('tool_counts') or {}
        app_logger.info(
            "[ORCH_STAGE_DONE] model=%s ms=%s tool_counts=%s web_enabled=%s web_reason=%s location_ok=%s weather_ok=%s visual_intent=%s tool_records=%s",
            model,
            int((time.time() - _t_orch0) * 1000),
            json.dumps(tool_counts, ensure_ascii=False, sort_keys=True),
            bool(web_meta.get('enabled')),
            str(web_meta.get('reason') or ''),
            bool(((stage.get('latest_location_payload') or {}).get('ok'))),
            bool(((stage.get('latest_weather_payload') or {}).get('ok'))),
            str(((ctx.get('visual_ctx') or {}).get('intent') if isinstance(ctx.get('visual_ctx'), dict) else '') or 'none'),
            len(stage.get('tool_records') or []),
        )
    except Exception:
        pass
    return ctx, stage



def _stage_has_image_mode_request(stage: dict | None = None) -> bool:
    """Whether this turn entered the image-mode lane.

    This is only a lane-state helper. It does not decide user intent and it does
    not trigger any tool by itself.
    """
    st = stage if isinstance(stage, dict) else {}
    tool_plan = st.get('tool_plan') if isinstance(st.get('tool_plan'), dict) else {}
    image_result = st.get('image_generation_result') if isinstance(st.get('image_generation_result'), dict) else {}
    image_task_plan = st.get('image_task_plan') if isinstance(st.get('image_task_plan'), dict) else {}
    return bool(
        tool_plan.get('use_image_mode')
        or tool_plan.get('use_image_generation')
        or tool_plan.get('use_image_edit')
        or image_result
        or image_task_plan
        or list(st.get('generated_artifacts') or [])
    )


def _stage_image_generation_success_has_artifacts(stage: dict | None = None) -> bool:
    """True only when the image tool actually produced displayable artifacts."""
    st = stage if isinstance(stage, dict) else {}
    image_result = st.get('image_generation_result') if isinstance(st.get('image_generation_result'), dict) else {}
    artifacts = list(st.get('generated_artifacts') or [])
    if not artifacts:
        return False
    if image_result and not bool(image_result.get('ok')):
        return False
    task_type = str(image_result.get('image_task_type') or '').strip().lower()
    if task_type == 'existing_image_analysis' or image_result.get('need_generation') is False:
        return False
    return True


def _stage_should_direct_return_image_reply(stage: dict | None = None) -> bool:
    """Image generation/edit success should end at the image card, with no text."""
    return bool(_stage_has_image_mode_request(stage) and _stage_image_generation_success_has_artifacts(stage))


def _build_orchestrated_final_messages(stage: dict | None, fallback_messages: list | None = None, *, user_geo: dict | None = None, visual_ctx: dict | None = None) -> list:
    """统一组装最终喂给模型的消息，避免同步/流式路径重复拼装。"""
    stage = stage or {}
    message_base = stage.get("answer_messages") or stage.get("prepared_messages") or fallback_messages or []
    chosen_visual_ctx = visual_ctx if visual_ctx is not None else stage.get("visual_ctx")
    if not isinstance(chosen_visual_ctx, dict):
        chosen_visual_ctx = _orch_build_existing_image_visual_ctx(message_base, user_text=stage.get("last_user_text") or '', endpoint_mode=str(stage.get('api_endpoint_mode') or stage.get('endpoint_mode') or ''))
    try:
        app_logger.info(
            '[ORCH_FINAL_VISUAL_CTX] intent=%s binding_mode=%s binding_desc=%s urls=%s tool_records=%s',
            str((chosen_visual_ctx or {}).get('intent') or ''),
            str((chosen_visual_ctx or {}).get('binding_mode') or ''),
            str((chosen_visual_ctx or {}).get('binding_desc') or '')[:120],
            len((chosen_visual_ctx or {}).get('urls') or []),
            len(stage.get('tool_records') or []),
        )
    except Exception:
        pass
    final_messages = _build_answer_messages(
        message_base,
        list(stage.get("tool_records") or []),
        user_geo=user_geo,
        include_visual=False,
        weather_payload=stage.get("latest_weather_payload"),
        user_text=stage.get("last_user_text") or '',
        include_file_edit_audit_context=True,
    )
    return _sanitize_messages_for_model(
        _inject_visual_context_messages(final_messages, chosen_visual_ctx)
    )
