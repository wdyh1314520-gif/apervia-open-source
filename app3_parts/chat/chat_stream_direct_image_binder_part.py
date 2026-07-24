# bind direct image handoff arguments to stable image ids chosen by the model.


class ChatStreamDirectImageBinder:
    def __init__(self, *, model: str = '', messages: list | None = None, client_override=None, direct_image_rows_for_model=None):
        self.model = str(model or '')
        self.messages = list(messages or []) if isinstance(messages, list) else []
        self.client_override = client_override
        self.direct_image_rows_for_model = direct_image_rows_for_model if callable(direct_image_rows_for_model) else (lambda rows=None, limit=8: '')

    def resolve_once(self, args: dict | None, candidate_rows: list[dict] | None, *, task_type: str = '', prompt_text: str = '') -> dict:
        """Ask the model to bind image ids when its direct handoff omitted ids.

        This replaces the previous secondary image planner fallback. The model is
        only asked to choose ids from the already-injected image index; the backend
        still does not infer which image should be used.
        """
        model = self.model
        messages = self.messages
        client_override = self.client_override
        _agent_stream_direct_image_rows_for_model = self.direct_image_rows_for_model
        rows_text = _agent_stream_direct_image_rows_for_model(candidate_rows or [], limit=8)
        if not rows_text:
            return {}
        latest_text = _latest_user_text_from_messages(messages or [])
        safe_args = {}
        try:
            for k in ('task_type', 'reason', 'prompt', 'instruction', 'image_ref', 'edit_target_image_ids', 'reference_image_ids', 'selected_image_ids'):
                if isinstance(args, dict) and args.get(k) not in (None, '', []):
                    safe_args[k] = args.get(k)
        except Exception:
            safe_args = {}
        contract_text = ''
        try:
            contract_builder = globals().get('prompt_contract_text')
            if callable(contract_builder):
                contract_text = str(contract_builder('image_id_binder', compact=True) or '').strip()
        except Exception:
            contract_text = ''
        sys_msg = (
            ((contract_text + '\n') if contract_text else '')
            + '?? ID ???????'
            '?????? current_user / previous_user / assistant_generated_or_edited / tool_or_web ????????????'
            '?????????????????????'
        )
        user_msg = '\n\n'.join([
            '???????\n' + str(latest_text or '').strip(),
            '????????? handoff ???\n' + json.dumps(safe_args, ensure_ascii=False),
            '???????? ID?\n' + rows_text,
            '??????????' + str(task_type or ''),
            '????????/???\n' + str(prompt_text or '').strip(),
        ])
        try:
            client = client_override or globals().get('client_gpt')
            if client is None:
                return {}
            req = {
                'model': model,
                'messages': [
                    {'role': 'system', 'content': sys_msg},
                    {'role': 'user', 'content': user_msg},
                ],
                'temperature': 0.0,
                'max_tokens': 420,
            }
            contract_format = globals().get('apply_prompt_contract_response_format')
            if callable(contract_format):
                req = contract_format(req, 'image_id_binder')
            else:
                req['response_format'] = {'type': 'json_object'}
            apply_thinking = globals().get('_apply_completion_thinking_kwargs')
            if callable(apply_thinking):
                req = apply_thinking(req, role='tool_prefetch', model=model, client_override=client_override)
            resp = client.chat.completions.create(**req)
            raw = ''
            if getattr(resp, 'choices', None):
                raw = str(getattr(resp.choices[0].message, 'content', '') or '').strip()
            parser = globals().get('_safe_parse_json')
            obj = parser(raw) if callable(parser) else json.loads(raw)
            if not isinstance(obj, dict):
                return {}
            out = {}
            for k in ('edit_target_image_ids', 'reference_image_ids', 'selected_image_ids'):
                vals = obj.get(k)
                if isinstance(vals, str):
                    vals = [vals]
                if isinstance(vals, list):
                    out[k] = [str(x or '').strip() for x in vals if str(x or '').strip()][:6]
            for k in ('prompt', 'instruction', 'reason'):
                if str(obj.get(k) or '').strip():
                    out[k] = str(obj.get(k) or '').strip()[:1200 if k != 'reason' else 240]
            try:
                app_logger.info(
                    '[AGENT_STREAM_DIRECT_IMAGE_MODEL_BIND] model=%s task_type=%s edit=%s refs=%s selected=%s reason=%s',
                    model,
                    task_type,
                    json.dumps(out.get('edit_target_image_ids') or [], ensure_ascii=False),
                    json.dumps(out.get('reference_image_ids') or [], ensure_ascii=False),
                    json.dumps(out.get('selected_image_ids') or [], ensure_ascii=False),
                    str(out.get('reason') or '')[:120],
                )
            except Exception:
                pass
            return out
        except Exception as e:
            try:
                app_logger.warning('[AGENT_STREAM_DIRECT_IMAGE_MODEL_BIND_FAILED] model=%s task_type=%s err=%s:%s', model, task_type, type(e).__name__, e)
            except Exception:
                pass
            return {}
