# Responses-native image_generation payload collection, retrieval, and image_reply frames.

import json
import urllib.parse


class ResponsesNativeImageContext:
    def __init__(
        self,
        *,
        model: str = '',
        endpoint: str = '',
        api_key: str = '',
        http_client=None,
        headers: dict | None = None,
        state: dict | None = None,
        runtime_state: dict | None = None,
        native_image_state: dict | None = None,
        image_generation_group_active=None,
        capability_groups=None,
        sse=None,
        runtime_model_meta=None,
        last_user_text: str = '',
        image_artifacts_to_reply=None,
        logger=None,
    ):
        self.model = str(model or '')
        self.endpoint = str(endpoint or '')
        self.api_key = str(api_key or '')
        self.http_client = http_client
        self.headers = dict(headers or {})
        self.state = state if isinstance(state, dict) else {}
        self.runtime_state = runtime_state if isinstance(runtime_state, dict) else {}
        self.native_image_state = native_image_state if isinstance(native_image_state, dict) else {}
        self.image_generation_group_active = image_generation_group_active if callable(image_generation_group_active) else (lambda state=None: True)
        self.capability_groups = capability_groups if callable(capability_groups) else (lambda groups=None: [])
        self.sse = sse if callable(sse) else (lambda event, payload=None: '')
        self.runtime_model_meta = runtime_model_meta if callable(runtime_model_meta) else (lambda: {})
        self.last_user_text = str(last_user_text or '')
        self.image_artifacts_to_reply = image_artifacts_to_reply if callable(image_artifacts_to_reply) else (lambda saved, subject='', task_mode='': {})
        self.logger = logger or globals().get('app_logger')

    def _responses_native_image_ext_from_payload(self, payload: dict | None = None, fallback: str = '') -> str:
        raw = ''
        if isinstance(payload, dict):
            raw = str(payload.get('output_format') or payload.get('format') or payload.get('mime') or '').strip().lower()
        raw = raw.replace('image/', '').replace('.', '').strip()
        if raw == 'jpg':
            raw = 'jpeg'
        if raw in {'png', 'jpeg', 'webp', 'gif'}:
            return 'jpg' if raw == 'jpeg' else raw
        fb = str(fallback or self.native_image_state.get('ext') or 'png').strip().lower().replace('.', '')
        return fb if fb in {'png', 'jpg', 'jpeg', 'webp', 'gif'} else 'png'

    def _responses_native_strip_image_b64(self, value: str = '') -> tuple[str, str]:
        raw = str(value or '').strip()
        ext = ''
        if raw.startswith('data:image/') and 'base64,' in raw:
            try:
                header, body = raw.split('base64,', 1)
                ext = header.split('data:image/', 1)[1].split(';', 1)[0].strip().lower().replace('jpeg', 'jpg')
                raw = body.strip()
            except Exception:
                pass
        helper = globals().get('_strip_data_url_prefix')
        if callable(helper):
            try:
                raw = str(helper(raw) or '').strip()
            except Exception:
                pass
        return raw, ext

    def _responses_native_add_image_item(self, *, b64: str = '', url: str = '', source: str = 'result', ext: str = '') -> int:
        raw_url = str(url or '').strip()
        raw_b64, data_ext = self._responses_native_strip_image_b64(b64)
        item_ext = self._responses_native_image_ext_from_payload({'output_format': ext or data_ext}, self.native_image_state.get('ext') or 'png')
        if item_ext:
            self.native_image_state['ext'] = item_ext
        if not raw_url and not raw_b64:
            return 0
        bucket_name = 'partial_items' if str(source or '').strip().lower().startswith('partial') else 'result_items'
        key = (bucket_name, raw_url.lower(), raw_b64[:160])
        seen_keys = self.native_image_state.setdefault('seen_item_keys', set())
        if key in seen_keys:
            return 0
        seen_keys.add(key)
        item = {'url': raw_url, 'b64': raw_b64}
        self.native_image_state.setdefault(bucket_name, []).append(item)
        return 1

    def _image_allowed(self) -> bool:
        try:
            return bool(self.image_generation_group_active(self.state))
        except Exception:
            return True

    def _active_groups_for_log(self) -> list:
        try:
            return self.capability_groups(self.state.get('active_tool_groups') or [])
        except Exception:
            return []

    def _responses_native_image_event_is_response_terminal(self, event_type: str = '') -> bool:
        event_low = str(event_type or '').strip().lower()
        return event_low in {'response.completed', 'completed'}

    def _responses_native_collect_image_payload(self, payload, event_type: str = '') -> dict:
        event_low = str(event_type or '').strip().lower()
        info = {'seen': False, 'added': 0, 'result_added': 0, 'partial_added': 0}
        if not isinstance(payload, dict):
            return info
        image_generation_allowed = self._image_allowed()
        if 'image_generation_call' in event_low and not image_generation_allowed:
            self.runtime_state['native_image_leak_blocked'] = True
            try:
                self.logger.warning(
                    '[RESPONSES_NATIVE_IMAGE_EVENT_BLOCKED_FROM_NON_IMAGE_GROUP] model=%s groups=%s event=%s',
                    self.model,
                    json.dumps(self._active_groups_for_log(), ensure_ascii=False),
                    event_low[:160],
                )
            except Exception:
                pass
            return info
        if 'image_generation_call' in event_low:
            self.native_image_state['seen'] = True
            self.runtime_state['native_image_seen'] = True
            info['seen'] = True
            ext0 = self._responses_native_image_ext_from_payload(payload, self.native_image_state.get('ext') or 'png')
            self.native_image_state['ext'] = ext0

        def walk(node, depth: int = 0, inherited_ext: str = '') -> None:
            if depth > 8 or node is None:
                return
            if isinstance(node, dict):
                typ = str(node.get('type') or node.get('event') or '').strip().lower()
                local_seen = bool('image_generation_call' in typ)
                if local_seen and not image_generation_allowed:
                    self.runtime_state['native_image_leak_blocked'] = True
                    try:
                        self.logger.warning(
                            '[RESPONSES_NATIVE_IMAGE_ITEM_BLOCKED_FROM_NON_IMAGE_GROUP] model=%s groups=%s type=%s',
                            self.model,
                            json.dumps(self._active_groups_for_log(), ensure_ascii=False),
                            typ[:160],
                        )
                    except Exception:
                        pass
                    return
                local_ext = self._responses_native_image_ext_from_payload(node, inherited_ext or self.native_image_state.get('ext') or 'png')
                if local_seen:
                    self.native_image_state['seen'] = True
                    self.runtime_state['native_image_seen'] = True
                    info['seen'] = True
                    self.native_image_state['ext'] = local_ext
                partial_b64 = str(node.get('partial_image_b64') or node.get('partial_image') or '').strip()
                if partial_b64 and image_generation_allowed:
                    self.native_image_state['seen'] = True
                    self.runtime_state['native_image_seen'] = True
                    info['seen'] = True
                    added = self._responses_native_add_image_item(b64=partial_b64, source='partial', ext=local_ext)
                    info['added'] += added
                    info['partial_added'] += added
                if local_seen:
                    direct_image = node.get('image') if isinstance(node.get('image'), str) else ''
                    direct_data = node.get('data') if isinstance(node.get('data'), str) else ''
                    direct_b64 = str(
                        node.get('b64_json')
                        or node.get('base64')
                        or node.get('image_base64')
                        or node.get('image_b64')
                        or direct_image
                        or direct_data
                        or ''
                    ).strip()
                    direct_url = str(
                        node.get('url')
                        or node.get('image_url')
                        or node.get('download_url')
                        or node.get('file_url')
                        or ''
                    ).strip()
                    if direct_b64 or direct_url:
                        added = self._responses_native_add_image_item(
                            b64=direct_b64,
                            url=direct_url,
                            source='result',
                            ext=local_ext,
                        )
                        info['added'] += added
                        info['result_added'] += added
                    result = node.get('result')
                    if isinstance(result, str) and result.strip():
                        added = self._responses_native_add_image_item(b64=result, source='result', ext=local_ext)
                        info['added'] += added
                        info['result_added'] += added
                    elif isinstance(result, dict):
                        added = self._responses_native_add_image_item(
                            b64=str(result.get('b64_json') or result.get('base64') or result.get('image_base64') or result.get('image_b64') or (result.get('image') if isinstance(result.get('image'), str) else '') or (result.get('data') if isinstance(result.get('data'), str) else '') or '').strip(),
                            url=str(result.get('url') or result.get('image_url') or result.get('download_url') or result.get('file_url') or '').strip(),
                            source='result',
                            ext=local_ext,
                        )
                        info['added'] += added
                        info['result_added'] += added
                    elif isinstance(result, list):
                        for row in result[:8]:
                            if isinstance(row, str):
                                added = self._responses_native_add_image_item(b64=row, source='result', ext=local_ext)
                            elif isinstance(row, dict):
                                added = self._responses_native_add_image_item(
                                    b64=str(row.get('b64_json') or row.get('base64') or row.get('image_base64') or row.get('image_b64') or (row.get('image') if isinstance(row.get('image'), str) else '') or (row.get('data') if isinstance(row.get('data'), str) else '') or '').strip(),
                                    url=str(row.get('url') or row.get('image_url') or row.get('download_url') or row.get('file_url') or '').strip(),
                                    source='result',
                                    ext=local_ext,
                                )
                            else:
                                added = 0
                            info['added'] += added
                            info['result_added'] += added
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        walk(value, depth + 1, local_ext)
            elif isinstance(node, list):
                for row in node[:80]:
                    walk(row, depth + 1, inherited_ext)

        walk(payload, 0)
        if (event_low in {'response.completed', 'completed'} or event_low.endswith('.completed')) and bool(self.native_image_state.get('seen')):
            extractor = globals().get('_image_generation_responses_native_extract_items')
            if callable(extractor):
                try:
                    items, _meta = extractor(payload)
                except Exception:
                    items = []
                for row in items or []:
                    if not isinstance(row, dict):
                        continue
                    added = self._responses_native_add_image_item(
                        b64=str(row.get('b64') or row.get('b64_json') or row.get('base64') or '').strip(),
                        url=str(row.get('url') or row.get('image_url') or row.get('download_url') or '').strip(),
                        source='result',
                        ext=self.native_image_state.get('ext') or 'png',
                    )
                    info['added'] += added
                    info['result_added'] += added
        return info

    def _responses_native_response_retrieve_url(self, response_id: str = '', *, include_image_result: bool = False) -> str:
        rid = str(response_id or '').strip()
        if not rid:
            return ''
        try:
            base = str(self.endpoint or '').strip().rstrip('/')
            if not base:
                return ''
            url = f'{base}/{urllib.parse.quote(rid, safe="")}'
            if include_image_result:
                url += '?include[]=output.image_generation_call.result'
            return url
        except Exception:
            return ''

    def _responses_native_try_retrieve_final_image(self, response_id: str = '') -> dict:
        rid = str(response_id or '').strip()
        if not rid or bool(self.native_image_state.get('image_reply_finalized')):
            return {'ok': False, 'added': 0, 'reason': 'not_needed'}
        seen_retrieved = self.native_image_state.setdefault('retrieved_response_ids', set())
        if rid in seen_retrieved:
            return {'ok': False, 'added': 0, 'reason': 'already_tried'}
        seen_retrieved.add(rid)
        before = len(self.native_image_state.get('result_items') or [])
        urls = [
            self._responses_native_response_retrieve_url(rid, include_image_result=True),
            self._responses_native_response_retrieve_url(rid, include_image_result=False),
        ]
        for retrieve_url in [u for u in urls if u]:
            try:
                resp = self.http_client.get(retrieve_url, headers=self.headers, timeout=60.0)
                status_code = int(getattr(resp, 'status_code', 0) or 0)
                if status_code >= 400:
                    try:
                        self.logger.warning('[RESPONSES_NATIVE_IMAGE_RETRIEVE_FAILED] model=%s response_id=%s status=%s url=%s body=%s', self.model, rid, status_code, retrieve_url, str(getattr(resp, 'text', '') or '')[:500])
                    except Exception:
                        pass
                    continue
                try:
                    payload = resp.json() if getattr(resp, 'content', b'') else {}
                except Exception as json_err:
                    try:
                        self.logger.warning('[RESPONSES_NATIVE_IMAGE_RETRIEVE_JSON_FAILED] model=%s response_id=%s err=%s', self.model, rid, json_err)
                    except Exception:
                        pass
                    continue
                info = self._responses_native_collect_image_payload(payload, 'response.completed')
                added = int(info.get('result_added') or info.get('added') or 0)
                if added <= 0:
                    extractor = globals().get('_image_generation_responses_native_extract_items')
                    if callable(extractor):
                        try:
                            items, _meta = extractor(payload)
                        except Exception:
                            items, _meta = [], {}
                        for row in items or []:
                            if not isinstance(row, dict):
                                continue
                            one_added = self._responses_native_add_image_item(
                                b64=str(row.get('b64') or row.get('b64_json') or row.get('base64') or row.get('image_base64') or row.get('image_b64') or (row.get('image') if isinstance(row.get('image'), str) else '') or '').strip(),
                                url=str(row.get('url') or row.get('image_url') or row.get('download_url') or row.get('file_url') or '').strip(),
                                source='result',
                                ext=self.native_image_state.get('ext') or 'png',
                            )
                            added += one_added
                after = len(self.native_image_state.get('result_items') or [])
                try:
                    self.logger.info('[RESPONSES_NATIVE_IMAGE_RETRIEVE_DONE] model=%s response_id=%s added=%s result_items_before=%s result_items_after=%s url_include=%s', self.model, rid, added, before, after, 'include[]=' in retrieve_url)
                except Exception:
                    pass
                if after > before or added > 0:
                    return {'ok': True, 'added': max(added, after - before), 'reason': 'retrieved'}
            except Exception as retrieve_err:
                try:
                    self.logger.warning('[RESPONSES_NATIVE_IMAGE_RETRIEVE_ERROR] model=%s response_id=%s err=%s', self.model, rid, retrieve_err)
                except Exception:
                    pass
        return {'ok': False, 'added': 0, 'reason': 'not_found'}

    def _responses_native_image_reply_frames(self, force: bool = False) -> list[str]:
        if bool(self.native_image_state.get('image_reply_emitted')):
            return []
        if not bool(self.native_image_state.get('seen')):
            return []
        result_items = [dict(x) for x in (self.native_image_state.get('result_items') or []) if isinstance(x, dict)]
        partial_items = [dict(x) for x in (self.native_image_state.get('partial_items') or []) if isinstance(x, dict)]
        candidate_items = result_items or (partial_items if force else [])
        if not candidate_items:
            return []
        save_fn = globals().get('_save_image_b64_items')
        if not callable(save_fn):
            return []
        try:
            saved = save_fn(
                candidate_items,
                ext=self._responses_native_image_ext_from_payload({'output_format': self.native_image_state.get('ext') or 'png'}, 'png'),
                auth_headers={'Authorization': f'Bearer {self.api_key}'} if self.api_key else None,
            )
        except Exception as save_err:
            try:
                self.logger.exception('[RESPONSES_NATIVE_IMAGE_SAVE_FAILED] err=%s', save_err)
            except Exception:
                pass
            return []
        if not saved:
            return []
        payload = self.image_artifacts_to_reply(
            saved,
            subject=self.last_user_text,
            task_mode='generate',
        )
        if not payload:
            return []
        self.native_image_state['image_reply_emitted'] = True
        self.native_image_state['image_reply_finalized'] = bool(result_items)
        try:
            self.logger.info('[RESPONSES_NATIVE_IMAGE_REPLY_READY] saved=%s filenames=%s partial_fallback=%s', len(saved), [str(x.get('filename') or '') for x in saved[:6] if isinstance(x, dict)], bool((not result_items) and partial_items))
            if bool(self.native_image_state.get('image_reply_finalized')):
                self.logger.info('[RESPONSES_NATIVE_IMAGE_REPLY_EARLY_FINISH] saved=%s reason=result_image_saved', len(saved))
        except Exception:
            pass
        frames = [self.sse('image_reply', payload)]
        frames.append(self.sse('meta', {
            'model': self.model,
            'mode': 'responses_native_tools',
            'route_mode': 'responses_native_agent',
            'use_visual': True,
            'visual_intent': 'image_generation',
            'image_stage': 'generated',
            'image_result_count': len(saved),
            **self.runtime_model_meta(),
        }))
        return frames
