# existing chat/history image analysis activity and sandbox import execution.

import json
import re
import time


class ChatStreamExistingImageAnalysisContext:
    def __init__(
        self,
        *,
        model: str = '',
        messages: list | None = None,
        user_geo: dict | None = None,
        client_override=None,
        latest_user_text=None,
        messages_for_image_index=None,
        recent_assistant_image_rows=None,
        external_image_asset_candidate_rows=None,
        filter_image_rows_by_endpoint=None,
        enrich_candidate_rows=None,
        direct_resolve_image_rows=None,
        current_endpoint_mode=None,
        normalize_endpoint_mode=None,
        build_existing_image_visual_ctx=None,
        image_activity_items=None,
        import_image_row_to_sandbox=None,
        exec_tool=None,
        append_progress_event=None,
        progress_meta=None,
        logger=None,
    ):
        self.model = str(model or '')
        self.messages = messages if isinstance(messages, list) else []
        self.user_geo = user_geo
        self.client_override = client_override
        self.latest_user_text = latest_user_text if callable(latest_user_text) else (lambda messages=None: '')
        self.messages_for_image_index = messages_for_image_index if callable(messages_for_image_index) else (lambda base=None: list(base or []))
        self.recent_assistant_image_rows = recent_assistant_image_rows if callable(recent_assistant_image_rows) else (lambda limit=1: [])
        self.external_image_asset_candidate_rows = external_image_asset_candidate_rows if callable(external_image_asset_candidate_rows) else (lambda limit=16: [])
        self.filter_image_rows_by_endpoint = filter_image_rows_by_endpoint if callable(filter_image_rows_by_endpoint) else (lambda rows, endpoint_mode='', allow_legacy=False: list(rows or []))
        self.enrich_candidate_rows = enrich_candidate_rows if callable(enrich_candidate_rows) else (lambda rows: list(rows or []))
        self.direct_resolve_image_rows = direct_resolve_image_rows if callable(direct_resolve_image_rows) else (lambda refs, rows, limit=8: [])
        self.current_endpoint_mode = current_endpoint_mode if callable(current_endpoint_mode) else (lambda client=None: '')
        self.normalize_endpoint_mode = normalize_endpoint_mode if callable(normalize_endpoint_mode) else (lambda value: str(value or '').strip().lower())
        self.build_existing_image_visual_ctx = build_existing_image_visual_ctx if callable(build_existing_image_visual_ctx) else None
        self.image_activity_items = image_activity_items if callable(image_activity_items) else (lambda rows, limit=8: [])
        self.import_image_row_to_sandbox = import_image_row_to_sandbox if callable(import_image_row_to_sandbox) else (lambda row, fallback_url='', index=1, asset_source='': {'ok': False, 'error': 'image_import_unavailable'})
        self.exec_tool = exec_tool if callable(exec_tool) else (lambda name, args, **kwargs: {'ok': False, 'error': 'exec_tool_unavailable'})
        self.append_progress_event = append_progress_event if callable(append_progress_event) else (lambda state, item: {})
        self.progress_meta = progress_meta if callable(progress_meta) else (lambda state=None: {})
        self.logger = logger or globals().get('app_logger')

    def note_event(
        self,
        state: dict,
        args: dict | None = None,
        result: dict | None = None,
        *,
        status: str = 'analyzing',
        call_id: str = '',
        round_idx: int = 0,
    ) -> dict:
        if not isinstance(state, dict):
            return {}
        args = args if isinstance(args, dict) else {}
        result = result if isinstance(result, dict) else {}
        status_text = str(status or '').strip().lower()
        state_text = 'done' if status_text in {'analyzed', 'done', 'completed', 'success', 'succeeded'} else ('error' if status_text in {'error', 'failed', 'failure'} else 'active')
        if result and not bool(result.get('ok')):
            state_text = 'error'
        raw_ids = (
            result.get('selected_image_ids')
            or args.get('selected_image_ids')
            or args.get('image_ids')
            or args.get('image_id')
            or args.get('image_ref')
            or []
        )
        if not isinstance(raw_ids, list):
            raw_ids = [raw_ids] if str(raw_ids or '').strip() else []
        selected_ids = [str(x or '').strip() for x in raw_ids if str(x or '').strip()][:8]
        image_items = self.image_activity_items(result.get('activity_image_items') or result.get('image_items') or [], limit=8)
        if not image_items and selected_ids:
            image_items = self.image_activity_items([{'image_id': image_id} for image_id in selected_ids], limit=8)
        try:
            image_count = max(
                len(image_items),
                len(selected_ids),
                int(result.get('image_count') or result.get('analyzed_count') or result.get('visual_input_count') or 0),
            )
        except Exception:
            image_count = max(len(image_items), len(selected_ids))
        current_input_ids = {str(x or '').strip() for x in (state.get('_current_user_image_activity_ids') or []) if str(x or '').strip()}
        selected_id_set = {str(x or '').strip() for x in selected_ids if str(x or '').strip()}
        current_input_op_key = str(state.get('_current_user_image_activity_op_key') or '').strip()
        if current_input_op_key and selected_id_set and selected_id_set.issubset(current_input_ids):
            op_key = current_input_op_key
        else:
            op_key = str(call_id or args.get('_activity_call_id') or args.get('_tool_call_id') or args.get('tool_call_id') or '').strip()
        if not op_key:
            op_key = '|'.join(selected_ids) or str(result.get('image_ref') or args.get('image_ref') or '').strip()
        if not op_key:
            op_key = f'image_analysis|round|{round_idx or state.get("tool_rounds") or 0}'
        title = '图片分析失败' if state_text == 'error' else ('图片分析完成' if state_text == 'done' else '正在分析图片')
        now_ms = int(time.time() * 1000)
        self.append_progress_event(state, {
            'key': f'image|analysis|{op_key}'[:700],
            'stage': 'image_analysis_done' if state_text != 'active' else 'image_analysis_start',
            'panel_stage': 'image',
            'tool': 'analyze_existing_image',
            'title': title,
            'detail': '',
            'state': state_text,
            'percent': 100 if state_text in {'done', 'error'} else 20,
            'ts': now_ms,
            'updated_at': now_ms,
            'done_at': now_ms if state_text in {'done', 'warn', 'error'} else 0,
            'source': 'existing_image_analysis',
            'action_type': 'image_analysis',
            'actionType': 'image_analysis',
            'activity_op': 'image_analysis',
            'operation_key': op_key[:160],
            'selected_image_ids': selected_ids,
            'image_items': image_items,
            'image_count': image_count,
            'round': int(round_idx or state.get('tool_rounds') or 0),
        })
        return self.progress_meta(state)

    def run_tool(self, args: dict | None = None) -> dict:
        args = dict(args or {}) if isinstance(args, dict) else {}
        query = str(args.get('query') or args.get('question') or args.get('reason') or self.latest_user_text(self.messages or []) or '').strip()
        raw_image_ids = args.get('image_ids')
        if raw_image_ids in (None, '', []):
            raw_image_ids = args.get('selected_image_ids')
        if raw_image_ids in (None, '', []):
            raw_image_ids = args.get('image_id')
        if raw_image_ids in (None, '', []):
            raw_image_ids = args.get('image_ref')
        if raw_image_ids in (None, '', []):
            try:
                recent_rows = self.recent_assistant_image_rows(limit=1)
            except Exception:
                recent_rows = []
            if recent_rows:
                fallback_id = str(
                    (recent_rows[0] or {}).get('stable_image_id')
                    or (recent_rows[0] or {}).get('role_image_id')
                    or (recent_rows[0] or {}).get('image_id')
                    or ''
                ).strip()
                if fallback_id:
                    raw_image_ids = [fallback_id]
                    args['image_ids'] = [fallback_id]
                    args.setdefault('reason', 'analyze_existing_image_recent_assistant_fallback_no_selected_ids')
                    try:
                        self.logger.info('[AGENT_STREAM_ANALYZE_IMAGE_RECENT_ASSISTANT_FALLBACK] model=%s selected=%s reason=no_selected_ids', self.model, fallback_id)
                    except Exception:
                        pass
        if isinstance(raw_image_ids, str) and (',' in raw_image_ids or '，' in raw_image_ids):
            raw_image_ids = [x.strip() for x in re.split(r'[,，]', raw_image_ids) if x.strip()]
        image_ref = ''
        if isinstance(raw_image_ids, list):
            image_ref = ','.join(str(x or '').strip() for x in raw_image_ids if str(x or '').strip())
        else:
            image_ref = str(raw_image_ids or args.get('target') or '').strip()
        endpoint_mode = self.current_endpoint_mode(self.client_override)
        visual_ctx = None
        selected_rows: list[dict] = []
        if raw_image_ids not in (None, '', []):
            try:
                candidate_rows: list[dict] = []
                candidate_builder = globals().get('_image_mode_candidate_rows')
                if callable(candidate_builder):
                    candidate_rows = [
                        dict(row)
                        for row in (
                            candidate_builder(
                                self.messages_for_image_index(self.messages or []),
                                user_text=query or self.latest_user_text(self.messages or []),
                                limit=16,
                            )
                            or []
                        )
                        if isinstance(row, dict)
                    ]
                extra_asset_rows = self.external_image_asset_candidate_rows(limit=16)
                base_rows = self.filter_image_rows_by_endpoint(candidate_rows, endpoint_mode=endpoint_mode, allow_legacy=False)
                candidate_rows = [*base_rows, *extra_asset_rows] if extra_asset_rows else list(base_rows or [])
                enriched = self.enrich_candidate_rows(candidate_rows)
                selected_rows = self.direct_resolve_image_rows(raw_image_ids, enriched, limit=8)
            except Exception:
                selected_rows = []
        if selected_rows:
            urls = []
            attachment_keys = []
            source_roles = []
            for row in selected_rows:
                url = str(row.get('url') or '').strip()
                key = str(row.get('attachment_key') or url or '').strip()
                if url and url not in urls:
                    urls.append(url)
                if key and key not in attachment_keys:
                    attachment_keys.append(key)
                role = str(row.get('role') or row.get('source_role') or '').strip()
                if role and role not in source_roles:
                    source_roles.append(role)
            visual_ctx = {
                'intent': 'existing_image_analysis',
                'decision': {'intent': 'existing_image_analysis', 'reason': 'agent_stream_model_selected_image_ids'},
                'urls': urls[:8],
                'text_hints': [],
                'binding_mode': 'model_selected_ids',
                'binding_desc': 'selected_image_ids:' + image_ref[:160],
                'resolved_image_ref': image_ref,
                'resolved_attachment_keys': attachment_keys[:8],
                'resolved_source_roles': source_roles[:8],
                'endpoint_mode': endpoint_mode,
                'rows': [dict(row or {}) for row in selected_rows[:8]],
            }
        elif image_ref and callable(self.build_existing_image_visual_ctx):
            try:
                visual_ctx = self.build_existing_image_visual_ctx(
                    self.messages or [],
                    user_text=query or image_ref or self.latest_user_text(self.messages or []),
                    image_ref=image_ref,
                    client_override=self.client_override,
                    endpoint_mode=endpoint_mode,
                )
            except Exception:
                visual_ctx = None
        urls = [str(url or '').strip() for url in ((visual_ctx or {}).get('urls') or []) if str(url or '').strip()]
        if not urls:
            return {
                'ok': False,
                'error': 'no_existing_image_context',
                'message': '没有找到可分析的已有图片上下文',
                'query': query,
                'image_ref': image_ref,
                'endpoint_mode': endpoint_mode,
            }
        is_responses_lane = self.normalize_endpoint_mode(endpoint_mode) == 'responses'
        selected_ids = raw_image_ids if isinstance(raw_image_ids, list) else ([str(raw_image_ids)] if str(raw_image_ids or '').strip() else [])
        attached_image_count = 0
        build_failures: list[str] = []
        imported_files: list[dict] = []
        sandbox_results: list[dict] = []
        response_input_items: list[dict] = []
        focus_crop_executions: list[dict] = []
        focus_crop_activity_rows: list[dict] = []
        selected_for_sources = selected_rows if selected_rows else [{'url': url} for url in urls[:8]]
        activity_image_items = self.image_activity_items(selected_for_sources, limit=8)
        for idx, row in enumerate(selected_for_sources[:8], 1):
            row_obj = dict(row or {}) if isinstance(row, dict) else {}
            fallback_url = urls[idx - 1] if idx - 1 < len(urls) else str(row_obj.get('url') or '')
            imported = self.import_image_row_to_sandbox(row_obj, fallback_url=fallback_url, index=idx, asset_source='chat_existing_image')
            imported_row = dict(imported.get('file') or {}) if bool(imported.get('ok')) and isinstance(imported.get('file'), dict) else None
            if imported_row:
                imported_files.append(imported_row)
                analyze_result = self.exec_tool('sandbox_analyze_file_images', {
                    'path': str(imported_row.get('path') or ''),
                    'query': query or '请分析这张图片',
                    'max_images': 1,
                    **({'focus_crop': bool(args.get('focus_crop'))} if 'focus_crop' in args else {}),
                }, user_geo=self.user_geo, messages=self.messages or [], client_override=self.client_override, model=self.model)
                sandbox_results.append(dict(analyze_result or {}))
                crop_execution = analyze_result.get('focus_crop_execution') if isinstance(analyze_result, dict) and isinstance(analyze_result.get('focus_crop_execution'), dict) else {}
                if crop_execution and (crop_execution.get('code') or crop_execution.get('images')):
                    focus_crop_executions.append(dict(crop_execution))
                for crop_item in (analyze_result.get('focus_crop_items') or []) if isinstance(analyze_result, dict) else []:
                    if isinstance(crop_item, dict):
                        focus_crop_activity_rows.append(dict(crop_item))
                for item in (analyze_result.get('_responses_input_items') or []) if isinstance(analyze_result, dict) else []:
                    if isinstance(item, dict):
                        response_input_items.append(item)
                attached_image_count += 1
            else:
                image_label = str(row_obj.get('stable_image_id') or row_obj.get('image_id') or row_obj.get('role_image_id') or fallback_url or f'image_{idx}')[:120]
                build_failures.append((image_label + ':' + str(imported.get('error') or 'source_not_resolved')[:160])[:220])
        if build_failures:
            try:
                self.logger.warning('[RESPONSES_NATIVE_IMAGE_SANDBOX_IMPORT_FAILED] model=%s failed=%s imported=%s endpoint=%s', self.model, json.dumps(build_failures[:8], ensure_ascii=False), attached_image_count, endpoint_mode)
            except Exception:
                pass
        try:
            self.logger.info('[AGENT_STREAM_ANALYZE_EXISTING_IMAGE_SANDBOX_ATTACHED] model=%s imported=%s image_ref=%s endpoint=%s', self.model, len(imported_files), image_ref[:80], endpoint_mode)
        except Exception:
            pass
        if not is_responses_lane:
            evidence_parts: list[str] = []
            ok_count = 0
            analyzed_count = 0
            for item in sandbox_results:
                if not isinstance(item, dict):
                    continue
                if bool(item.get('ok')):
                    ok_count += 1
                try:
                    analyzed_count += int(item.get('analyzed_count') or 0)
                except Exception:
                    pass
                evidence = str(item.get('evidence') or '').strip()
                if evidence:
                    evidence_parts.append(evidence)
                else:
                    for img in (item.get('images') or [])[:4]:
                        if isinstance(img, dict) and str(img.get('analysis') or '').strip():
                            evidence_parts.append(str(img.get('analysis') or '').strip())
            analysis_text = '\n\n'.join(evidence_parts).strip()
            return {
                'ok': bool(ok_count and analysis_text),
                'analysis': analysis_text or 'sandbox_analyze_file_images 没有返回可用图片分析',
                'message': 'selected_images_imported_to_sandbox_and_analyzed' if analysis_text else 'sandbox_image_analysis_failed',
                'visual_processing_stage': 'chat_images_imported_to_sandbox_then_analyzed_in_chat_lane' if analysis_text else 'sandbox_image_analysis_failed',
                'sandbox_visual_role': 'store_select_analyze_chat_images',
                'model_visual_role': 'interpret_sandbox_image_analysis_result',
                'image_count': len(urls[:8]),
                'imported_count': len(imported_files),
                'analyzed_count': analyzed_count,
                'image_ref': image_ref,
                'selected_image_ids': raw_image_ids if isinstance(raw_image_ids, list) else ([str(raw_image_ids)] if str(raw_image_ids or '').strip() else []),
                'activity_image_items': activity_image_items,
                'focus_crop_executions': focus_crop_executions,
                'focus_crop_items': self.image_activity_items(focus_crop_activity_rows, limit=8),
                'query': query,
                'binding_mode': str((visual_ctx or {}).get('binding_mode') or ''),
                'binding_desc': str((visual_ctx or {}).get('binding_desc') or ''),
                'endpoint_mode': endpoint_mode,
                'files': imported_files,
                'sandbox_results': sandbox_results,
                'error': '' if analysis_text else 'sandbox_image_analysis_failed',
                'image_input_errors': build_failures[:8],
            }
        return {
            'ok': bool(response_input_items),
            'analysis_deferred_to_responses': True,
            'message': 'selected_images_imported_to_sandbox_and_attached_to_next_responses_input' if response_input_items else 'sandbox_image_import_failed',
            'instruction': 'Selected chat/history images were first imported into /mnt/data, then sandbox_analyze_file_images attached them as input_image items for the next /responses round. Inspect those images directly before answering.',
            'visual_input_deferred_to': 'responses' if response_input_items else '',
            'visual_processing_stage': 'chat_images_imported_to_sandbox_then_attached_to_responses' if response_input_items else 'sandbox_image_import_failed',
            'sandbox_visual_role': 'store_select_attach_chat_images',
            'model_visual_role': 'interpret_attached_input_images',
            'image_count': len(urls[:8]),
            'imported_count': len(imported_files),
            'visual_input_count': len(response_input_items),
            'image_ref': image_ref,
            'selected_image_ids': selected_ids,
            'activity_image_items': activity_image_items,
            'focus_crop_executions': focus_crop_executions,
            'focus_crop_items': self.image_activity_items(focus_crop_activity_rows, limit=8),
            'query': query,
            'binding_mode': str((visual_ctx or {}).get('binding_mode') or ''),
            'binding_desc': str((visual_ctx or {}).get('binding_desc') or ''),
            'endpoint_mode': endpoint_mode,
            'files': imported_files,
            'sandbox_results': sandbox_results,
            'error': '' if response_input_items else 'sandbox_image_import_failed',
            'image_input_errors': build_failures[:8],
            '_responses_input_items': response_input_items,
        }
