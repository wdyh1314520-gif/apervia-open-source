# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: visual context injection, image index messages, and inline image stripping.
# Loaded before chat_streaming_part.py, sharing the original global namespace.

import json


class ChatStreamVisualContext:
    def __init__(
        self,
        *,
        external_image_asset_messages: list | None = None,
        current_endpoint_mode=None,
        find_recent_context_image_urls=None,
        is_current_user_image_row=None,
        filter_image_rows_by_endpoint=None,
        enrich_direct_image_candidate_rows=None,
        direct_image_rows_for_model=None,
        external_image_asset_candidate_rows=None,
        messages_for_image_index=None,
        cfg_int=None,
        sanitize_messages_for_model=None,
    ):
        self.external_image_asset_messages = list(external_image_asset_messages or []) if isinstance(external_image_asset_messages, list) else []
        self.current_endpoint_mode = current_endpoint_mode if callable(current_endpoint_mode) else (lambda: '')
        self.find_recent_context_image_urls = find_recent_context_image_urls if callable(find_recent_context_image_urls) else (lambda msgs=None, limit=6, endpoint_mode='': [])
        self.is_current_user_image_row = is_current_user_image_row if callable(is_current_user_image_row) else (lambda row=None: False)
        self.filter_image_rows_by_endpoint = filter_image_rows_by_endpoint if callable(filter_image_rows_by_endpoint) else (lambda rows=None, endpoint_mode='', allow_legacy=False: rows or [])
        self.enrich_direct_image_candidate_rows = enrich_direct_image_candidate_rows if callable(enrich_direct_image_candidate_rows) else (lambda rows=None: rows or [])
        self.direct_image_rows_for_model = direct_image_rows_for_model if callable(direct_image_rows_for_model) else (lambda rows=None, limit=8: '')
        self.external_image_asset_candidate_rows = external_image_asset_candidate_rows if callable(external_image_asset_candidate_rows) else (lambda limit=8: [])
        self.messages_for_image_index = messages_for_image_index if callable(messages_for_image_index) else (lambda msgs=None: list(msgs or []))
        self.cfg_int = cfg_int if callable(cfg_int) else (lambda name, default, min_value=0, max_value=10000: default)
        self.sanitize_messages_for_model = sanitize_messages_for_model if callable(sanitize_messages_for_model) else (lambda msgs=None, **kwargs: list(msgs or []))

    def _agent_stream_recent_image_context(self, base_messages: list | None = None, *, max_chars: int = 1400) -> dict:
        """Build a compact image index for the direct streaming-tool lane.

        This is context only. It does not decide intent; the model still chooses
        whether to call image_search or hand off to the image lane.
        """
        msgs = list(base_messages or [])
        latest_text = _latest_user_text_from_messages(msgs or [])
        endpoint_mode = self.current_endpoint_mode()
        urls: list[str] = []
        try:
            urls = self.find_recent_context_image_urls(msgs or [], limit=6, endpoint_mode=endpoint_mode)
        except Exception:
            urls = []
        lines: list[str] = []
        try:
            direct_candidates = []
            candidate_builder = globals().get('_image_mode_candidate_rows')
            if callable(candidate_builder):
                direct_candidates = [dict(r) for r in (candidate_builder(msgs or [], user_text=latest_text, limit=12) or []) if isinstance(r, dict)]
            current_direct_candidates = [dict(r) for r in direct_candidates if self.is_current_user_image_row(r)]
            historical_direct_candidates = [dict(r) for r in direct_candidates if not self.is_current_user_image_row(r)]
            historical_direct_candidates = self.filter_image_rows_by_endpoint(historical_direct_candidates, endpoint_mode=endpoint_mode)
            enriched_candidates = self.enrich_direct_image_candidate_rows([*current_direct_candidates, *historical_direct_candidates])
            grouped_images = {'current': [], 'user': [], 'assistant': [], 'tool': [], 'other': []}
            for row in enriched_candidates:
                is_current = bool(str(row.get('current_user_image_id') or '').strip() or str(row.get('binding_mode') or '').strip().lower() == 'current_user_message')
                if is_current:
                    grouped_images['current'].append(dict(row))
                    continue
                role = str((row or {}).get('role') or (row or {}).get('source_role') or '').strip().lower()
                if role == 'user':
                    grouped_images['user'].append(dict(row))
                elif role == 'assistant':
                    grouped_images['assistant'].append(dict(row))
                elif role == 'tool':
                    grouped_images['tool'].append(dict(row))
                else:
                    grouped_images['other'].append(dict(row))
            section_specs = [
                ('current', '????????', '??????????/????? ID?????????????????????????????????'),
                ('user', '????????', '????????? ID???????????????/??/??/?????????????'),
                ('assistant', '????/????', '???????/???? ID???????????????? N ????????????'),
                ('tool', '??/????', '?????????? ID???????????????????'),
                ('other', '??????', '??????? ID????????????'),
            ]
            for group_key, title, note in section_specs:
                group_rows = grouped_images.get(group_key) or []
                if not group_rows:
                    continue
                index_text = self.direct_image_rows_for_model(group_rows, limit=8)
                if index_text:
                    lines.append(f'?{title}?\n' + index_text + '\n' + note)
        except Exception:
            pass
        try:
            builder = globals().get('_build_visual_reference_planning_context')
            if endpoint_mode:
                builder = None
            visual_ref = builder(
                msgs or [],
                user_text=latest_text,
                max_items=4,
                max_chars=max(400, min(int(max_chars or 1400), 2400)),
            ) if callable(builder) else {}
            ref_text = str((visual_ref or {}).get('text') or '').strip()
            if ref_text:
                lines.append('?????????\n' + ref_text + '\n???????????????????????? handoff ???????? ID?')
        except Exception:
            pass
        text_block = '\n'.join([x for x in lines if str(x or '').strip()]).strip()
        if text_block and len(text_block) > max_chars:
            text_block = text_block[:max(200, int(max_chars or 1400))] + '\n...????????????'
        try:
            index_count = max(len(urls or []), len(enriched_candidates or []) if 'enriched_candidates' in locals() else 0)
        except Exception:
            index_count = len(urls or [])
        return {
            'has_images': bool(urls or text_block),
            'urls': urls[:6],
            'text': text_block,
            'count': index_count,
            'endpoint_mode': endpoint_mode,
        }

    def _agent_stream_external_image_assets_index_text(self, limit: int = 8) -> tuple[str, int]:
        """Build a lightweight visible index from the independent image_assets lane.

        This covers the case where the frontend has sent image_assets successfully,
        but the generic visual candidate builder cannot parse image_reply payloads
        yet. It is still only an index; real pixels are attached later when a
        concrete image-analysis or image-generation tool needs them.
        """
        external_image_asset_messages = self.external_image_asset_messages
        if not external_image_asset_messages:
            return '', 0
        rows: list[dict] = []
        try:
            rows = self.external_image_asset_candidate_rows(limit=max(1, min(int(limit or 8), 16)))
        except Exception:
            rows = []
        if not rows:
            return '', 0
        try:
            index_text = self.direct_image_rows_for_model(rows, limit=max(1, min(int(limit or 8), 16)))
        except Exception:
            index_text = ''
        if not str(index_text or '').strip():
            simple_lines: list[str] = []
            for idx, row in enumerate(rows[:max(1, min(int(limit or 8), 16))], 1):
                stable_id = str(row.get('current_user_image_id') or row.get('stable_image_id') or row.get('role_image_id') or row.get('image_id') or f'assistant_img_{idx}').strip()
                label = str(row.get('display_label') or row.get('role_label') or row.get('global_label') or f'?????{idx}').strip()
                role = str(row.get('role') or row.get('source_role') or 'assistant').strip()
                aliases = row.get('alias_ids') if isinstance(row.get('alias_ids'), list) else []
                alias_text = ', '.join([str(x or '').strip() for x in aliases if str(x or '').strip()][:4])
                simple_lines.append(f'- id={stable_id}; label={label}; role={role}; aliases={alias_text}')
            index_text = '\n'.join(simple_lines).strip()
        if not str(index_text or '').strip():
            return '', 0
        try:
            app_logger.info('[AGENT_STREAM_EXTERNAL_IMAGE_ASSET_INDEX_INJECTED] images=%s chars=%s', len(rows), len(index_text))
        except Exception:
            pass
        return (
            '????????????/?????\n'
            + index_text
            + '\n???????? image_assets ?????????????????????? / ????? N ?? / ?????? / ????????????????? assistant_img_N ??? aliases?',
            len(rows),
        )

    def _agent_stream_messages_with_visual_context(self, base_messages: list | None = None) -> list:
        msgs = [dict(m) if isinstance(m, dict) else m for m in (base_messages or [])]
        try:
            image_index_msgs = self.messages_for_image_index(msgs)
            image_ctx = self._agent_stream_recent_image_context(image_index_msgs, max_chars=self.cfg_int('RESPONSES_NATIVE_IMAGE_CONTEXT_MAX_CHARS', 900, min_value=300, max_value=2400))
            image_text = str((image_ctx or {}).get('text') or '').strip()
            external_index_text = ''
            external_index_count = 0
            try:
                external_index_text, external_index_count = self._agent_stream_external_image_assets_index_text(limit=8)
            except Exception:
                external_index_text, external_index_count = '', 0
            if external_index_text and external_index_text not in image_text:
                image_text = (image_text + '\n\n' + external_index_text).strip() if image_text else external_index_text
                try:
                    if isinstance(image_ctx, dict):
                        image_ctx['count'] = max(int(image_ctx.get('count') or 0), int(external_index_count or 0))
                except Exception:
                    pass
            if not image_text:
                return msgs
            content = (
                '????????\n'
                + image_text
                + '\n\n?????????? image_id???????????/OCR/??? analyze_existing_image/non_generation_image???????????????????? task ?? selected_image_ids????? assistant_img_N??????? current_user_image_N??????????????'
            )
            try:
                app_logger.info('[AGENT_STREAM_IMAGE_INDEX_INJECTED] images=%s chars=%s external_assets=%s', int((image_ctx or {}).get('count') or 0), len(image_text), int(external_index_count or 0))
            except Exception:
                pass
            return [{'role': 'system', '_kind': 'agent_stream_image_index', 'content': content}] + msgs
        except Exception as image_ctx_err:
            try:
                app_logger.warning('[AGENT_STREAM_IMAGE_INDEX_FAILED] err=%s:%s', type(image_ctx_err).__name__, image_ctx_err)
            except Exception:
                pass
            return msgs

    def _agent_stream_inline_image_url_from_item(self, item: dict | None = None) -> str:
        it = dict(item or {})
        typ = str(it.get('type') or '').strip().lower()
        if typ == 'image_url':
            img = it.get('image_url')
            if isinstance(img, dict):
                return str(img.get('url') or '').strip()
            return str(img or '').strip()
        if typ == 'input_image':
            return str(it.get('image_url') or it.get('url') or '').strip()
        img = it.get('image_url') or it.get('image')
        if isinstance(img, dict):
            return str(img.get('url') or img.get('image_url') or '').strip()
        return str(img or '').strip()

    def _agent_stream_strip_inline_image_inputs(self, base_messages: list | None = None) -> tuple[list, int, int]:
        """Strip inline image payloads; keep only stable text bindings.

        Inline image payloads are removed from the main text request, but their stable
        ids stay available in the injected image index. Selected images are
        imported into sandbox before either sandbox_analyze_file_images or
        native image_generation uses them.
        """
        out: list = []
        stripped = 0
        kept = 0
        for m in (base_messages or []):
            if not isinstance(m, dict):
                out.append(m)
                continue
            mm = dict(m)
            content = mm.get("content")
            if isinstance(content, list):
                cleaned: list = []
                for item in content:
                    if isinstance(item, dict):
                        typ = str(item.get("type") or "").strip().lower()
                        image_url = self._agent_stream_inline_image_url_from_item(item)
                        is_image_item = bool(typ in {"image_url", "input_image"} or image_url or item.get("image"))
                        if is_image_item:
                            stripped += 1
                            continue
                        if typ == "text":
                            text = str(item.get("text") or "").strip()
                            if text:
                                cleaned.append({"type": "text", "text": text})
                            continue
                        text = str(item.get("text") or item.get("content") or "").strip()
                        if text:
                            cleaned.append({"type": "text", "text": text})
                        continue
                    text = str(item or "").strip()
                    if text:
                        cleaned.append({"type": "text", "text": text})
                mm["content"] = cleaned if cleaned else ""
            elif isinstance(content, dict):
                typ = str(content.get("type") or "").strip().lower()
                image_url = self._agent_stream_inline_image_url_from_item(content)
                if typ in {"image_url", "input_image"} or image_url or content.get("image"):
                    stripped += 1
                    mm["content"] = ""
            out.append(mm)
        if stripped or kept:
            notice = (
                "???????????? image payload???????????"
                "??/OCR/??? image_id ?? analyze_existing_image?"
                "???????????????? image task????????????? image_generation?"
            )
            out.append({
                "role": "system",
                "_kind": "agent_stream_image_payload_notice",
                "content": notice,
            })
        try:
            if stripped or kept:
                app_logger.info("[AGENT_STREAM_IMAGE_PAYLOAD_STRIPPED] kept_current=%s stripped=%s", kept, stripped)
        except Exception:
            pass
        return out, stripped, kept


    def _agent_stream_sanitize_tool_loop_messages(self, base_messages: list | None = None) -> list:
        stripped_messages, _stripped_count, kept_current_count = self._agent_stream_strip_inline_image_inputs(base_messages or [])
        try:
            return self.sanitize_messages_for_model(stripped_messages, allow_images=False)
        except TypeError:
            return self.sanitize_messages_for_model(stripped_messages)

    def _agent_stream_log_prompt_cache_message_shape(self, stage: str, rows: list | None = None) -> None:
        try:
            items = [m for m in (rows or []) if isinstance(m, dict)]
            role_counts: dict[str, int] = {}
            kinds: list[str] = []
            tail: list[dict] = []
            digest = globals().get('_prompt_cache_digest')
            text_reader = globals().get('_responses_instruction_text_from_content')
            for idx, item in enumerate(items):
                role = str(item.get('role') or '').strip().lower() or 'unknown'
                kind = str(item.get('_kind') or '').strip()
                role_counts[role] = int(role_counts.get(role, 0)) + 1
                if kind and kind not in kinds:
                    kinds.append(kind)
                if idx >= max(0, len(items) - 8):
                    try:
                        text = text_reader(item.get('content')) if callable(text_reader) else str(item.get('content') or '')
                    except Exception:
                        text = str(item.get('content') or '')
                    text = str(text or '').replace('\r', ' ').replace('\n', ' ').strip()
                    tail.append({
                        'idx': idx,
                        'role': role,
                        'kind': kind,
                        'chars': len(text),
                        'hash': digest(text, 12) if callable(digest) else '',
                    })
            app_logger.info(
                '[PROMPT_CACHE_CHAT_MESSAGE_SHAPE] stage=%s messages=%s roles=%s kinds=%s tail=%s',
                str(stage or ''),
                len(items),
                json.dumps(role_counts, ensure_ascii=False, sort_keys=True),
                json.dumps(kinds[:20], ensure_ascii=False),
                json.dumps(tail, ensure_ascii=False),
            )
        except Exception:
            pass
