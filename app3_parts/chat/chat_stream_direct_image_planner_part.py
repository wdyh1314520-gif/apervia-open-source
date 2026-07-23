# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: build direct-image handoff task plans without owning tool execution.
# Loaded before chat_streaming_part.py, sharing the original global namespace.


class ChatStreamDirectImagePlanner:
    def __init__(
        self,
        *,
        messages: list | None = None,
        client_override=None,
        image_generation_settings: dict | None = None,
        image_handoff_task_type=None,
        external_image_asset_candidate_rows=None,
        enrich_candidate_rows=None,
        direct_resolve_image_rows=None,
        arg_string_values=None,
        model_resolve_refs_once=None,
    ):
        self.messages = list(messages or []) if isinstance(messages, list) else []
        self.client_override = client_override
        self.image_generation_settings = dict(image_generation_settings or {}) if isinstance(image_generation_settings, dict) else {}
        self.image_handoff_task_type = image_handoff_task_type if callable(image_handoff_task_type) else (lambda args=None: '')
        self.external_image_asset_candidate_rows = external_image_asset_candidate_rows if callable(external_image_asset_candidate_rows) else (lambda limit=12: [])
        self.enrich_candidate_rows = enrich_candidate_rows if callable(enrich_candidate_rows) else (lambda rows=None: [])
        self.direct_resolve_image_rows = direct_resolve_image_rows if callable(direct_resolve_image_rows) else (lambda values=None, rows=None, limit=4: [])
        self.arg_string_values = arg_string_values if callable(arg_string_values) else (lambda args=None, *keys: [])
        self.model_resolve_refs_once = model_resolve_refs_once if callable(model_resolve_refs_once) else (lambda args=None, candidate_rows=None, task_type='', prompt_text='': {})

    def build_plan(self, args: dict | None = None) -> dict:
        """Convert the streaming model's own image handoff into a tool-stage plan.

        This is not an intent keyword gate. The direct Agent has already made a
        semantic tool call; this bridge preserves that model decision so the
        legacy image lane does not ask a second planner to override it.
        """
        messages = self.messages
        client_override = self.client_override
        image_generation_settings = self.image_generation_settings
        args = dict(args or {}) if isinstance(args, dict) else {}
        handoff_task_type = self.image_handoff_task_type(args)
        if not handoff_task_type:
            return {}
        task_type = 'text_to_image' if handoff_task_type == 'image_generation' else handoff_task_type
        last_user = _latest_user_text_from_messages(messages or [])
        reason = str(args.get('reason') or '').strip()
        prompt_text = str(args.get('prompt') or args.get('instruction') or '').strip()
        if not prompt_text:
            prompt_text = str(last_user or reason or '').strip()
        try:
            prompt_text = _planner_safe_text(prompt_text, max_len=1200).strip()
        except Exception:
            prompt_text = prompt_text[:1200]
        candidate_rows: list[dict] = []
        endpoint_mode = _orch_current_endpoint_mode(client_override)
        try:
            candidate_builder = globals().get('_image_mode_candidate_rows')
            if callable(candidate_builder):
                candidate_rows = [dict(r) for r in (candidate_builder(_agent_stream_messages_for_image_index(messages or []), user_text=last_user, limit=12) or []) if isinstance(r, dict)]
            external_rows_for_plan = self.external_image_asset_candidate_rows(limit=12)
            if external_rows_for_plan:
                candidate_rows = [*candidate_rows, *external_rows_for_plan]
        except Exception:
            candidate_rows = []
            candidate_rows = _orch_filter_image_rows_by_endpoint(candidate_rows, endpoint_mode=endpoint_mode, allow_legacy=False)
        candidate_rows = self.enrich_candidate_rows(candidate_rows)
        if not candidate_rows:
            candidate_rows = self.external_image_asset_candidate_rows(limit=12)
        try:
            normalized_handoff_image_settings = _normalize_image_generation_settings(image_generation_settings)
            edit_enabled = bool((normalized_handoff_image_settings or {}).get('edit', {}).get('enabled'))
        except Exception:
            normalized_handoff_image_settings = image_generation_settings or {}
            edit_enabled = False
        responses_native_image_inputs_enabled = False
        try:
            native_checker = globals().get('_image_generation_should_use_responses_native')
            responses_native_image_inputs_enabled = bool(native_checker(normalized_handoff_image_settings or {}, client_override=client_override)) if callable(native_checker) else False
        except Exception:
            responses_native_image_inputs_enabled = False

        def resolve(values: list[str], limit: int = 4) -> list[dict]:
            if not values:
                return []
            return self.direct_resolve_image_rows(values, candidate_rows, limit=limit)

        image_ref_values = self.arg_string_values(
            args,
            'image_ref', 'image_id', 'target', 'target_image_id', 'target_image_ids',
            'source_image_id', 'source_image_ids', 'image_refs', 'image_ids',
        )
        explicit_edit_values = self.arg_string_values(args, 'edit_target_image_ids', 'edit_target_ids', 'target_image_ids')
        explicit_reference_values = self.arg_string_values(args, 'reference_image_ids', 'reference_ids', 'ref_image_ids')
        explicit_selected_values = self.arg_string_values(args, 'selected_image_ids', 'selected_ids')
        explicit_all_values = explicit_edit_values + explicit_reference_values + explicit_selected_values + image_ref_values
        has_explicit_image_refs = bool(explicit_all_values)

        edit_target_rows = resolve(explicit_edit_values + image_ref_values, limit=8) if explicit_edit_values or image_ref_values else []
        reference_rows = resolve(explicit_reference_values, limit=8) if explicit_reference_values else []
        selected_rows = resolve(explicit_selected_values + image_ref_values, limit=8) if explicit_selected_values or image_ref_values else []
        pure_text_to_image = task_type == 'text_to_image' and not has_explicit_image_refs

        plan_row_helpers = ChatStreamDirectImagePlanRows(resolve=resolve)
        row_key = plan_row_helpers.row_key
        row_public_id = plan_row_helpers.row_public_id
        add_unique = plan_row_helpers.add_unique
        row_lineage_ids = plan_row_helpers.row_lineage_ids
        lineage_rows_for = plan_row_helpers.lineage_rows_for
        row_group_name = plan_row_helpers.row_group_name
        grouped_source_rows = plan_row_helpers.grouped_source_rows

        direct_image_source_groups = {'current_user_rows': [], 'assistant_rows': [], 'historical_rows': [], 'overflow_rows': [], 'overflow_index': [], 'ordered_rows': []}
        direct_all_source_rows: list[dict] = []
        priority_rows: list[dict] = []
        add_unique(priority_rows, edit_target_rows, max_items=8)
        add_unique(priority_rows, reference_rows, max_items=8)
        add_unique(priority_rows, selected_rows, max_items=8)

        if candidate_rows and has_explicit_image_refs and task_type in {'text_to_image', 'image_edit', 'reference_generate', 'reference_edit', 'variation', 'existing_image_analysis'}:
            # Image handoff requires explicit stable image ids. Keep lineage for
            # those ids, but do not attach an unselected candidate pack.
            direct_image_source_groups, direct_all_source_rows = grouped_source_rows(
                candidate_rows,
                max_items=8,
                priority_rows=priority_rows,
            )
            lineage_rows = lineage_rows_for(priority_rows, limit=8)
            if task_type == 'text_to_image' and (priority_rows or lineage_rows):
                task_type = 'reference_generate'
                reason = ((reason + '; ') if reason else '') + 'explicit_image_refs'
            if task_type == 'reference_generate':
                add_unique(reference_rows, priority_rows, max_items=8)
                add_unique(reference_rows, lineage_rows, max_items=8)
            elif task_type in {'image_edit', 'reference_edit', 'variation'}:
                if not edit_target_rows:
                    add_unique(edit_target_rows, priority_rows, max_items=8)
                add_unique(reference_rows, lineage_rows, max_items=8)
            elif task_type == 'existing_image_analysis':
                add_unique(selected_rows, priority_rows, max_items=8)
                add_unique(selected_rows, lineage_rows, max_items=8)
        if task_type in {'image_edit', 'reference_edit', 'variation'} and not edit_target_rows:
            edit_target_rows = add_unique([], selected_rows, max_items=4)
        if task_type == 'existing_image_analysis' and not edit_target_rows:
            edit_target_rows = add_unique([], selected_rows, max_items=4)
        if task_type in {'reference_generate', 'reference_edit'} and not reference_rows:
            reference_rows = add_unique([], selected_rows, max_items=4)

        source_needed_now = task_type in {'image_edit', 'reference_edit', 'reference_generate', 'variation', 'existing_image_analysis'}
        if not (edit_target_rows or reference_rows or selected_rows) and source_needed_now and candidate_rows:
            # The streaming model owns image selection. If it omitted concrete ids
            # in the first handoff, ask the model to bind ids from the stable image
            # index. The backend only maps returned ids to rows; it does not choose
            # images or run the legacy image planner here.
            binding_args = self.model_resolve_refs_once(
                args,
                candidate_rows,
                task_type=task_type,
                prompt_text=prompt_text or last_user,
            )
            if isinstance(binding_args, dict) and binding_args:
                if str(binding_args.get('prompt') or '').strip() and not str(args.get('prompt') or args.get('instruction') or '').strip():
                    prompt_text = str(binding_args.get('prompt') or '').strip()[:1200]
                edit_target_rows = resolve(binding_args.get('edit_target_image_ids') or [], limit=4)
                reference_rows = resolve(binding_args.get('reference_image_ids') or [], limit=4)
                selected_rows = resolve(binding_args.get('selected_image_ids') or [], limit=6)
                if task_type in {'image_edit', 'reference_edit', 'variation'} and not edit_target_rows:
                    edit_target_rows = add_unique([], selected_rows, max_items=4)
                if task_type == 'existing_image_analysis' and not edit_target_rows:
                    edit_target_rows = add_unique([], selected_rows, max_items=4)
                if task_type in {'reference_generate', 'reference_edit'} and not reference_rows:
                    reference_rows = add_unique([], selected_rows, max_items=4)
                if edit_target_rows or reference_rows or selected_rows:
                    reason = ((reason + '; ') if reason else '') + 'binding_resolved_by_direct_model'

        selected_rows = []
        add_unique(selected_rows, edit_target_rows, max_items=8)
        add_unique(selected_rows, reference_rows, max_items=8)

        needs_source = task_type in {'image_edit', 'reference_edit', 'reference_generate', 'variation', 'existing_image_analysis'}
        need_clarify = bool(needs_source and not selected_rows)
        clarify_question = ''
        if need_clarify:
            clarify_question = '请明确要使用哪一张图片。'
        if task_type in {'image_edit', 'reference_edit', 'reference_generate', 'variation'} and not edit_enabled and not responses_native_image_inputs_enabled:
            need_clarify = True
            clarify_question = clarify_question or '当前图片编辑未启用，无法使用上传图片作为编辑或参考输入。'

        return {
            'ok': True,
            'task_type': task_type,
            'direct_image_handoff_task_type': handoff_task_type,
            'prompt': prompt_text,
            'need_clarify': bool(need_clarify),
            'clarify_question': clarify_question,
            'reason': (reason or 'agent_stream_direct_handoff')[:160],
            'candidate_rows': candidate_rows,
            'edit_target_rows': edit_target_rows,
            'reference_rows': reference_rows,
            'ignore_rows': [],
            'selected_rows': selected_rows,
            'direct_image_source_groups': direct_image_source_groups,
            'edit_enabled': edit_enabled,
            'source': 'agent_stream_direct_model',
        }


class ChatStreamDirectImageHandoffContext:
    def __init__(
        self,
        *,
        messages: list | None = None,
        user_geo: dict | None = None,
        user_time: str = '',
        web_enabled: bool = False,
        web_k: int = 0,
        web_max_pages: int = 0,
        latest_user_text=None,
        strip_lane_system_messages=None,
        sanitize_messages_for_model=None,
        build_orchestrator_soft_hint=None,
        inject_runtime_tool_context=None,
        inject_orchestrator_soft_hint=None,
        build_direct_image_task_plan=None,
        logger=None,
        model: str = '',
    ):
        self.messages = list(messages or []) if isinstance(messages, list) else []
        self.user_geo = user_geo
        self.user_time = user_time
        self.web_enabled = web_enabled
        self.web_k = web_k
        self.web_max_pages = web_max_pages
        self.latest_user_text = latest_user_text if callable(latest_user_text) else (lambda messages=None: '')
        self.strip_lane_system_messages = strip_lane_system_messages if callable(strip_lane_system_messages) else (lambda messages, kinds=(): list(messages or []))
        self.sanitize_messages_for_model = sanitize_messages_for_model if callable(sanitize_messages_for_model) else (lambda messages: list(messages or []))
        self.build_orchestrator_soft_hint = build_orchestrator_soft_hint if callable(build_orchestrator_soft_hint) else (lambda route_signals=None, file_hint_active=False, enable_visual=True: '')
        self.inject_runtime_tool_context = inject_runtime_tool_context if callable(inject_runtime_tool_context) else (lambda messages, **kwargs: list(messages or []))
        self.inject_orchestrator_soft_hint = inject_orchestrator_soft_hint if callable(inject_orchestrator_soft_hint) else (lambda messages, hint='': list(messages or []))
        self.build_direct_image_task_plan = build_direct_image_task_plan if callable(build_direct_image_task_plan) else (lambda args=None: {})
        self.logger = logger or globals().get('app_logger')
        self.model = str(model or '')

    def image_handoff_task_type(self, args: dict | None = None) -> str:
        raw = str(((args or {}).get('task_type') or (args or {}).get('type') or '')).strip().lower()
        raw = raw.replace('\\', '/').replace('-', '_').replace(' ', '_')
        aliases = {
            'analysis': 'existing_image_analysis', 'analyze': 'existing_image_analysis', 'image_analysis': 'existing_image_analysis',
            'existing_image': 'existing_image_analysis', 'existing_image_analysis': 'existing_image_analysis',
            'generate': 'image_generation', 'generation': 'image_generation', 'image_generation': 'image_generation',
            'text_to_image': 'text_to_image', 'txt2img': 'text_to_image', 'txt_to_img': 'text_to_image',
            'edit': 'image_edit', 'image_edit': 'image_edit', 'image_editing': 'image_edit',
            'reference_generate': 'reference_generate', 'reference_edit': 'reference_edit', 'variation': 'variation',
        }
        if raw in aliases:
            return aliases.get(raw, '')
        tail = raw.rsplit('/', 1)[-1].strip() if '/' in raw else ''
        if tail in aliases:
            return aliases.get(tail, '')
        if 'text_to_image' in raw or 'txt2img' in raw or 'txt_to_img' in raw:
            return 'text_to_image'
        if 'reference_edit' in raw:
            return 'reference_edit'
        if 'reference_generate' in raw:
            return 'reference_generate'
        if 'image_edit' in raw or raw.endswith('/edit'):
            return 'image_edit'
        if 'image_generation' in raw or raw.endswith('/generate'):
            return 'image_generation'
        if 'existing_image_analysis' in raw or 'image_analysis' in raw:
            return 'existing_image_analysis'
        return ''

    def direct_image_prefetch(self, args: dict | None = None) -> dict:
        args = dict(args or {}) if isinstance(args, dict) else {}
        task_type = self.image_handoff_task_type(args)
        reason = str(args.get('reason') or args.get('prompt') or args.get('instruction') or self.latest_user_text(self.messages or []) or '').strip()
        primary = 'image_edit' if task_type in {'image_edit', 'reference_edit', 'variation'} else 'image'
        return {
            'route_mode': 'visual',
            'answer_strategy': 'tool_first',
            'primary_delivery': primary,
            'visual_decision': {
                'intent': task_type or 'image_mode',
                'subject': reason[:240],
                'reason': 'direct_agent_image_handoff',
            },
            'direct_image_handoff': True,
            'direct_image_handoff_task_type': task_type,
            'route_reason': reason[:240],
        }

    def direct_image_context(self, args: dict | None = None) -> dict:
        args = dict(args or {}) if isinstance(args, dict) else {}
        task_type = self.image_handoff_task_type(args)
        reason = str(args.get('reason') or args.get('prompt') or args.get('instruction') or self.latest_user_text(self.messages or []) or '').strip()
        prefetch_for_image = self.direct_image_prefetch(args)
        base_messages = list(self.messages or [])
        answer_messages = self.strip_lane_system_messages(list(base_messages), ('tool_runtime', 'orchestrator_soft_hint'))
        query_messages = self.sanitize_messages_for_model(list(answer_messages))
        soft_hint_text = self.build_orchestrator_soft_hint(prefetch_for_image, file_hint_active=False, enable_visual=True)
        prepared_messages = self.inject_runtime_tool_context(list(base_messages), user_geo=self.user_geo, allow_weather_tool=True, route_signals=prefetch_for_image)
        prepared_messages = self.inject_orchestrator_soft_hint(prepared_messages, soft_hint_text)
        prepared_messages = self.sanitize_messages_for_model(prepared_messages)
        ctx = {
            'base_messages': base_messages,
            'prepared_messages': prepared_messages,
            'tool_messages': prepared_messages,
            'answer_messages': answer_messages,
            'query_messages': query_messages,
            'last_user_text': self.latest_user_text(base_messages),
            'visual_ctx': None,
            'prefetch_decision': prefetch_for_image,
            'route_mode': 'visual',
            'primary_delivery': prefetch_for_image.get('primary_delivery') or 'image',
            'answer_strategy': 'tool_first',
            'file_gate': {'should_enter_sandbox_files': False, 'reason': 'direct_image_handoff'},
            'should_short_circuit_to_file_generation': False,
            'file_hint_active': False,
            'allow_location_tool': True,
            'allow_weather_tool': True,
            'should_use_web_research': False,
            'soft_web_research_hit': False,
            'web_enabled': self.web_enabled,
            'web_k': self.web_k,
            'web_max_pages': self.web_max_pages,
            'user_time': self.user_time,
            'soft_hint_text': soft_hint_text,
            'direct_image_handoff_task_type': task_type,
            'direct_image_handoff_reason': reason,
        }
        preplanned = args.get('preplanned_image_task_plan') if isinstance(args.get('preplanned_image_task_plan'), dict) else None
        if isinstance(preplanned, dict) and str(preplanned.get('task_type') or '').strip():
            ctx['preplanned_image_task_plan'] = dict(preplanned)
        else:
            bridged_plan = self.build_direct_image_task_plan(args)
            if isinstance(bridged_plan, dict) and str(bridged_plan.get('task_type') or '').strip():
                ctx['preplanned_image_task_plan'] = bridged_plan
                try:
                    self.logger.info(
                        '[AGENT_STREAM_DIRECT_IMAGE_PREPLAN] model=%s task_type=%s need_clarify=%s prompt=%s candidates=%s selected=%s source=%s reason=%s',
                        self.model,
                        str(bridged_plan.get('task_type') or ''),
                        bool(bridged_plan.get('need_clarify')),
                        str(bridged_plan.get('prompt') or '')[:160],
                        len(bridged_plan.get('candidate_rows') or []),
                        len(bridged_plan.get('selected_rows') or []),
                        str(bridged_plan.get('source') or ''),
                        str(bridged_plan.get('reason') or '')[:160],
                    )
                except Exception:
                    pass
        return ctx
