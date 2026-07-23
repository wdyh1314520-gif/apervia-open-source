# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: image candidate rows and model-facing image index text for chat image tools.
# Loaded before chat_streaming_part.py, sharing the original global namespace.


class ChatStreamImageCandidateContext:
    def __init__(
        self,
        *,
        model: str = '',
        messages: list | None = None,
        external_image_asset_messages: list | None = None,
        client_override=None,
        image_rows_log_payload=None,
        image_candidate_sources=None,
        messages_for_image_index=None,
        current_endpoint_mode=None,
        is_current_user_image_row=None,
        filter_image_rows_by_endpoint=None,
        enrich_candidate_rows=None,
        sort_image_rows=None,
        image_row_key=None,
    ):
        self.model = str(model or '')
        self.messages = list(messages or []) if isinstance(messages, list) else []
        self.external_image_asset_messages = list(external_image_asset_messages or []) if isinstance(external_image_asset_messages, list) else []
        self.client_override = client_override
        self.image_rows_log_payload_func = image_rows_log_payload if callable(image_rows_log_payload) else None
        self.image_candidate_sources = image_candidate_sources if callable(image_candidate_sources) else (lambda row=None, primary_url='': [])
        self.messages_for_image_index = messages_for_image_index if callable(messages_for_image_index) else self._default_messages_for_image_index
        self.current_endpoint_mode = current_endpoint_mode if callable(current_endpoint_mode) else (lambda: _orch_current_endpoint_mode(self.client_override))
        self.is_current_user_image_row = is_current_user_image_row if callable(is_current_user_image_row) else _agent_stream_is_current_user_image_row
        self.filter_image_rows_by_endpoint = filter_image_rows_by_endpoint if callable(filter_image_rows_by_endpoint) else _orch_filter_image_rows_by_endpoint
        self.enrich_candidate_rows = enrich_candidate_rows if callable(enrich_candidate_rows) else (lambda rows=None: list(rows or []))
        self.sort_image_rows = sort_image_rows if callable(sort_image_rows) else _agent_stream_sort_image_rows
        self.image_row_key_func = image_row_key if callable(image_row_key) else self._default_image_row_key

    def _default_messages_for_image_index(self, base_messages: list | None = None) -> list:
        base = [m for m in (base_messages or []) if isinstance(m, dict)]
        if not self.external_image_asset_messages:
            return base
        return [*base, *[dict(m) for m in self.external_image_asset_messages if isinstance(m, dict)]]

    @staticmethod
    def _default_image_row_key(row: dict | None = None) -> str:
        row = row or {}
        item = row.get('item') if isinstance(row.get('item'), dict) else {}
        values = (
            row.get('current_user_image_id'), row.get('stable_image_id'), row.get('role_image_id'),
            row.get('image_id'), row.get('attachment_key'), row.get('model_storage_ref'),
            row.get('storage_ref'), row.get('file_library_id'), row.get('library_file_id'),
            row.get('url'), row.get('image_url'), row.get('download_url'),
            item.get('image_id'), item.get('attachment_id'), item.get('model_storage_ref'),
            item.get('storage_ref'), item.get('url'),
        )
        return next((str(value or '').strip() for value in values if str(value or '').strip()), '')

    def image_row_log_payload(self, row: dict | None = None) -> dict:
        row = dict(row or {}) if isinstance(row, dict) else {}
        stable_id = str(row.get('current_user_image_id') or row.get('stable_image_id') or row.get('role_image_id') or row.get('image_id') or '').strip()
        aliases = []
        if isinstance(row.get('alias_ids'), list):
            aliases = [str(x or '').strip() for x in (row.get('alias_ids') or []) if str(x or '').strip()]

        def short_src(value: str = '') -> str:
            raw = str(value or '').strip()
            if not raw:
                return ''
            low = raw.lower()
            if low.startswith('data:image/'):
                return 'data:image/*;base64,...len=' + str(len(raw))
            if low.startswith('base64:'):
                return 'base64:...len=' + str(len(raw))
            if len(raw) > 180:
                return raw[:90] + '...' + raw[-40:]
            return raw

        candidates = []
        try:
            primary_url = str(row.get('url') or row.get('image_url') or row.get('download_url') or '').strip()
            for src in self.image_candidate_sources(row, primary_url=primary_url):
                src_s = short_src(src)
                if src_s and src_s not in candidates:
                    candidates.append(src_s)
                if len(candidates) >= 4:
                    break
        except Exception:
            candidates = []
        return {
            'stable_id': stable_id,
            'image_id': str(row.get('image_id') or '').strip(),
            'display_label': str(row.get('display_label') or row.get('role_label') or row.get('global_label') or '').strip(),
            'role': str(row.get('role') or row.get('source_role') or '').strip(),
            'group': 'current_user' if str(row.get('current_user_image_id') or '').strip() else ('assistant_generated_or_edited' if str(row.get('role') or row.get('source_role') or '').strip().lower() == 'assistant' else 'historical'),
            'message_index': row.get('message_index'),
            'idx': row.get('idx'),
            'role_order': row.get('role_image_index'),
            'global_order': row.get('global_image_index'),
            'message_id': str(row.get('message_id') or '').strip(),
            'parent_image_id': str(row.get('parent_image_id') or '').strip(),
            'source_image_ids': row.get('source_image_ids') if isinstance(row.get('source_image_ids'), list) else row.get('derived_from'),
            'aliases': aliases[:10],
            'sources': candidates,
            'summary': str(row.get('summary') or '').strip()[:260],
        }

    def image_rows_log_payload(self, rows: list[dict] | None = None, *, limit: int = 12) -> list[dict]:
        if callable(self.image_rows_log_payload_func):
            try:
                return self.image_rows_log_payload_func(rows, limit=limit)
            except Exception:
                pass
        out = []
        try:
            max_i = max(1, int(limit or 12))
        except Exception:
            max_i = 12
        for row in (rows or [])[:max_i]:
            if isinstance(row, dict):
                out.append(self.image_row_log_payload(row))
        return out

    def eager_image_rows_for_generation(self, base_messages: list | None = None, *, task_type: str = '', limit: int = 8) -> list[dict]:
        raw_task = str(task_type or '').strip().lower()
        try:
            candidate_builder = globals().get('_image_mode_candidate_rows')
            if not callable(candidate_builder):
                return []
            latest_text = _latest_user_text_from_messages(base_messages or [])
            endpoint_mode = self.current_endpoint_mode()
            raw_base_rows = [
                dict(r)
                for r in (
                    candidate_builder(
                        self.messages_for_image_index(base_messages or []),
                        user_text=latest_text,
                        limit=24,
                    ) or []
                )
                if isinstance(r, dict)
            ]
            # Current-turn user images are the active request input and must stay
            # visible even when historical endpoint filtering is strict.
            current_rows = [dict(r) for r in raw_base_rows if self.is_current_user_image_row(r)]
            historical_rows = [dict(r) for r in raw_base_rows if not self.is_current_user_image_row(r)]
            external_rows = self.external_image_asset_candidate_rows(limit=24)
            historical_rows = self.filter_image_rows_by_endpoint(historical_rows, endpoint_mode=endpoint_mode, allow_legacy=False)
            rows = [*current_rows, *historical_rows, *external_rows] if external_rows else [*current_rows, *historical_rows]
            rows = self.enrich_candidate_rows(rows)
            if not rows and external_rows:
                rows = self.enrich_candidate_rows(external_rows)
            if not rows:
                return []
            try:
                max_i = max(1, min(int(limit or 8), 8))
            except Exception:
                max_i = 8
            ordered = self.sort_image_rows(rows)

            out: list[dict] = []
            seen: set[str] = set()
            for row in ordered:
                key = self.image_row_key_func(row)
                if not key or key in seen:
                    continue
                if not self._row_has_usable_source(row):
                    continue
                seen.add(key)
                out.append(dict(row))
                if len(out) >= max_i:
                    break
            try:
                app_logger.info(
                    '[RESPONSES_NATIVE_EAGER_IMAGE_ROWS] model=%s task_type=%s total=%s usable=%s rows=%s',
                    self.model,
                    raw_task or task_type,
                    len(rows or []),
                    len(out or []),
                    json.dumps(self.image_rows_log_payload(out, limit=12), ensure_ascii=False),
                )
            except Exception:
                pass
            return out
        except Exception as e:
            try:
                app_logger.warning('[RESPONSES_NATIVE_EAGER_IMAGE_ROWS_FAILED] model=%s task_type=%s err=%s:%s', self.model, task_type, type(e).__name__, e)
            except Exception:
                pass
            return []

    def _row_has_usable_source(self, row: dict | None = None) -> bool:
        row = row or {}
        item = row.get('item') if isinstance(row.get('item'), dict) else {}
        for value in (
            row.get('url'), row.get('image_url'), row.get('download_url'),
            row.get('attachment_key'), row.get('model_storage_ref'), row.get('storage_ref'),
            row.get('persisted_url'), row.get('server_url'), row.get('_preview_url'), row.get('_source_url'),
            row.get('file_library_id'), row.get('library_file_id'),
            item.get('model_storage_ref') if isinstance(item, dict) else '',
            item.get('storage_ref') if isinstance(item, dict) else '',
            item.get('file_library_id') if isinstance(item, dict) else '',
            item.get('library_file_id') if isinstance(item, dict) else '',
            item.get('persisted_url') if isinstance(item, dict) else '',
            item.get('server_url') if isinstance(item, dict) else '',
            item.get('url') if isinstance(item, dict) else '',
            item.get('_preview_url') if isinstance(item, dict) else '',
            item.get('_source_url') if isinstance(item, dict) else '',
        ):
            if str(value or '').strip():
                return True
        try:
            model_candidates = globals().get('_image_item_model_candidates')
            if callable(model_candidates) and (model_candidates(item) or []):
                return True
        except Exception:
            pass
        return False

    def recent_assistant_image_rows(self, limit: int = 1) -> list[dict]:
        rows: list[dict] = []
        try:
            endpoint_mode = self.current_endpoint_mode()
        except Exception:
            endpoint_mode = ''
        try:
            builder = globals().get('_image_mode_candidate_rows')
            if callable(builder):
                rows = [dict(r) for r in (builder(self.messages_for_image_index(self.messages or []), user_text=_latest_user_text_from_messages(self.messages or []), limit=24) or []) if isinstance(r, dict)]
        except Exception:
            rows = []
        try:
            external_rows = self.external_image_asset_candidate_rows(limit=24)
        except Exception:
            external_rows = []
        try:
            rows = self.filter_image_rows_by_endpoint(rows, endpoint_mode=endpoint_mode, allow_legacy=False)
        except Exception:
            rows = [dict(r) for r in rows if isinstance(r, dict)]
        if external_rows:
            rows = [*rows, *external_rows]
        try:
            rows = self.enrich_candidate_rows(rows)
            rows = self.sort_image_rows(rows)
        except Exception:
            rows = [dict(r) for r in rows if isinstance(r, dict)]
        assistant_rows: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            role = str(row.get('role') or row.get('source_role') or '').strip().lower()
            stable = str(row.get('stable_image_id') or row.get('role_image_id') or '').strip()
            source_type = str(row.get('source_type') or row.get('operation') or '').strip().lower()
            if role != 'assistant' and not stable.startswith('assistant_img_') and 'assistant_generated' not in source_type:
                continue
            key = self.image_row_key_func(row)
            if not key or key in seen:
                continue
            seen.add(key)
            assistant_rows.append(dict(row))
            if len(assistant_rows) >= max(1, min(int(limit or 1), 8)):
                break
        return assistant_rows

    def direct_image_rows_for_model(self, candidate_rows: list[dict] | None = None, *, limit: int = 8) -> str:
        rows = self.sort_image_rows([dict(r) for r in (candidate_rows or []) if isinstance(r, dict)])
        if not rows:
            return ''
        lines: list[str] = []
        for idx, row in enumerate(rows[:max(1, int(limit or 8))], 1):
            stable_id = str(row.get('current_user_image_id') or row.get('stable_image_id') or row.get('image_id') or f'image_candidate_{idx}').strip()
            aliases = [str(x or '').strip() for x in (row.get('alias_ids') or []) if str(x or '').strip()] if isinstance(row.get('alias_ids'), list) else []
            alias_text = ', '.join(aliases[:4])
            role_value = str(row.get('role') or row.get('source_role') or '').strip().lower()
            if str(row.get('current_user_image_id') or '').strip():
                group_name = 'current_user'
            elif role_value == 'user':
                group_name = 'previous_user'
            elif role_value == 'assistant':
                group_name = 'assistant_generated_or_edited'
            elif role_value == 'tool':
                group_name = 'tool_or_web'
            else:
                group_name = 'other'
            bits = [
                f'id={stable_id}',
                f'group={group_name}',
                f'label={row.get("display_label") or row.get("role_label") or row.get("global_label") or ""}',
            ]
            parent_id = str(row.get('parent_image_id') or '').strip()
            source_ids_raw = row.get('source_image_ids') or row.get('derived_from') or []
            if isinstance(source_ids_raw, str):
                source_ids = [source_ids_raw]
            elif isinstance(source_ids_raw, list):
                source_ids = [str(x or '').strip() for x in source_ids_raw if str(x or '').strip()]
            else:
                source_ids = []
            if parent_id and parent_id not in source_ids:
                source_ids.insert(0, parent_id)
            if parent_id:
                bits.append(f'parent_image_id={parent_id}')
            if source_ids:
                bits.append('derived_from=' + ','.join(source_ids[:3]))
            if alias_text:
                bits.append(f'aliases={alias_text}')
            ocr_hint = str(row.get('ocr_text_hint') or '').strip()
            if ocr_hint:
                bits.append(f'ocr_hint={ocr_hint[:80]}')
            message_text = str(row.get('message_text') or '').strip()
            if message_text:
                bits.append(f'message_text={message_text[:80]}')
            lines.append('- ' + '; '.join(str(x) for x in bits if str(x).strip()))
        return '\n'.join(lines).strip()


    def external_image_asset_candidate_rows(self, limit: int = 12) -> list[dict]:
        """Rows from the independent image_assets side channel.

        This is a bridge between the balanced frontend image_assets payload and the
        existing image candidate machinery. It does not add these assets to normal
        chat self.messages; it only makes them selectable/attachable for image tools.
        """
        if not self.external_image_asset_messages:
            return []
        rows: list[dict] = []
        try:
            collector = globals().get('_collect_context_image_items')
            if callable(collector):
                try:
                    rows = [dict(r) for r in (collector(self.messages_for_image_index([]), roles=('assistant', 'user', 'tool'), endpoint_mode=self.current_endpoint_mode(), allow_legacy=False) or []) if isinstance(r, dict)]
                except TypeError:
                    rows = [dict(r) for r in (collector(self.messages_for_image_index([]), roles=('assistant', 'user', 'tool')) or []) if isinstance(r, dict)]
        except Exception:
            rows = []
        if not rows:
            try:
                builder = globals().get('_image_mode_candidate_rows')
                if callable(builder):
                    rows = [dict(r) for r in (builder(self.messages_for_image_index([]), user_text=_latest_user_text_from_messages(self.messages or []), limit=max(1, min(int(limit or 12), 24))) or []) if isinstance(r, dict)]
            except Exception:
                rows = []
        if not rows:
            # Last-resort direct flatten for image_reply content.  This uses the
            # same structured fields as _image_reply_content_to_image_url_parts
            # normally emits, but only for the tool-side asset lane.
            for msg_idx, msg in enumerate(self.external_image_asset_messages or []):
                if not isinstance(msg, dict):
                    continue
                content = msg.get('content') if isinstance(msg.get('content'), dict) else {}
                imgs = content.get('images') if isinstance(content.get('images'), list) else []
                for idx, img in enumerate(imgs, 1):
                    if not isinstance(img, dict):
                        continue
                    url = str(img.get('model_storage_ref') or img.get('storage_ref') or img.get('raw_url') or img.get('rawUrl') or img.get('view_url') or img.get('viewUrl') or img.get('download_url') or img.get('downloadUrl') or img.get('preview_url') or img.get('previewUrl') or img.get('url') or img.get('src') or '').strip()
                    if not url:
                        continue
                    image_id = str(img.get('image_id') or img.get('imageId') or img.get('attachment_id') or img.get('id') or '').strip() or f'external_asset_{msg_idx + 1}_{idx}'
                    rows.append({
                        'image_id': image_id,
                        'stable_image_id': f'assistant_img_{len(rows) + 1}',
                        'role_image_id': f'assistant_img_{len(rows) + 1}',
                        'role_label': f'助手生成图{len(rows) + 1}',
                        'display_label': f'助手生成图{len(rows) + 1}',
                        'global_label': f'图{len(rows) + 1}',
                        'alias_ids': [image_id, f'assistant_img_{len(rows) + 1}', f'generated_image_{len(rows) + 1}', f'你生成的第{len(rows) + 1}张图', f'第{len(rows) + 1}张生成图'],
                        'attachment_key': image_id or url,
                        'url': url,
                        'role': 'assistant',
                        'source_role': 'assistant',
                        'source_type': str(img.get('source_type') or img.get('sourceType') or content.get('source_type') or 'assistant_generated').strip(),
                        'operation': str(img.get('operation') or img.get('task_mode') or content.get('operation') or content.get('task_mode') or 'generate').strip(),
                        'endpoint_mode': str(img.get('endpoint_mode') or img.get('api_endpoint_mode') or content.get('endpoint_mode') or content.get('api_endpoint_mode') or '').strip(),
                        'api_endpoint_mode': str(img.get('api_endpoint_mode') or img.get('endpoint_mode') or content.get('api_endpoint_mode') or content.get('endpoint_mode') or '').strip(),
                        'parent_image_id': str(img.get('parent_image_id') or img.get('parentImageId') or content.get('parent_image_id') or content.get('parentImageId') or '').strip(),
                        'source_image_ids': [str(x or '').strip() for x in ((img.get('source_image_ids') or img.get('derived_from') or content.get('source_image_ids') or content.get('derived_from') or []) if isinstance((img.get('source_image_ids') or img.get('derived_from') or content.get('source_image_ids') or content.get('derived_from') or []), list) else []) if str(x or '').strip()],
                        'derived_from': [str(x or '').strip() for x in ((img.get('derived_from') or img.get('source_image_ids') or content.get('derived_from') or content.get('source_image_ids') or []) if isinstance((img.get('derived_from') or img.get('source_image_ids') or content.get('derived_from') or content.get('source_image_ids') or []), list) else []) if str(x or '').strip()],
                        'message_index': msg.get('message_index'),
                        'idx': idx,
                        'item': {
                            'type': 'image_url',
                            'image_url': {'url': url},
                            **img,
                            'url': url,
                            'source_role': 'assistant',
                        },
                        'summary': f'stable_id=assistant_img_{len(rows) + 1}; display_label=助手生成图{len(rows) + 1}; role=assistant; source=external_image_assets',
                    })
        try:
            rows = self.enrich_candidate_rows(rows)
        except Exception:
            rows = [dict(r) for r in rows if isinstance(r, dict)]
        try:
            rows = self.sort_image_rows(rows)
        except Exception:
            rows = [dict(r) for r in rows if isinstance(r, dict)]
        out: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            key = self.image_row_key_func(row)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(dict(row))
            if len(out) >= max(1, min(int(limit or 12), 24)):
                break
        try:
            if out:
                app_logger.info('[AGENT_STREAM_EXTERNAL_IMAGE_ASSET_ROWS] count=%s rows=%s', len(out), json.dumps(self.image_rows_log_payload(out, limit=8), ensure_ascii=False))
        except Exception:
            pass
        return out
