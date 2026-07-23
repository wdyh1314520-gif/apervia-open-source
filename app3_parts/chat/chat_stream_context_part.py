# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: turn-level context objects for the streaming chat generator.
# Loaded before chat_streaming_part.py, sharing the original global namespace.


class ChatStreamRuntimeModelState:
    def __init__(self, initial_model: str = ''):
        self.input_runtime_model = _normalize_runtime_model_name(initial_model)
        self.model = ''

    def remember(self, value) -> str:
        model_name = _normalize_runtime_model_name(value)
        if model_name:
            self.model = model_name
        return str(self.model or '')

    def current(self) -> str:
        return _normalize_runtime_model_name(self.model)

    def context_model(self) -> str:
        # Only expose a model identity that came from runtime/upstream metadata.
        # Do not fall back to the requested model name here.
        return self.current() or self.input_runtime_model

    def meta(self) -> dict:
        return _runtime_model_meta(self.current())


class ChatStreamTurnContext:
    def __init__(self, *, messages: list | None = None, client_session_id: str = '', client_session_title: str = '', started_at: float = 0.0):
        self.messages = [m for m in (messages or []) if isinstance(m, dict)]
        self.client_session_id = str(client_session_id or '').strip()[:160]
        self.client_session_title = str(client_session_title or '').strip()[:240]
        self.started_at = float(started_at or time.time())
        self.activity_turn_id = f"{self.client_session_id or 'sessionless'}:{int(self.started_at * 1000)}:{id(messages)}"[:240]
        self.external_image_asset_messages: list[dict] = []

    def build_external_image_asset_messages(self, image_assets: list | None = None, *, client_override=None) -> list:
        out: list = []
        seen: set[str] = set()
        assets = image_assets if isinstance(image_assets, list) else []
        try:
            current_endpoint_mode = _orch_current_endpoint_mode(client_override)
        except Exception:
            current_endpoint_mode = ''
        try:
            if current_endpoint_mode:
                current_endpoint_mode = _normalize_chat_api_endpoint_mode(current_endpoint_mode)
        except Exception:
            pass
        for _idx, asset in enumerate(assets or [], 1):
            if not isinstance(asset, dict):
                continue
            content = dict(asset)
            if str(content.get('_kind') or '').strip() != 'image_reply':
                content['_kind'] = 'image_reply'
            if not str(content.get('source_role') or '').strip():
                content['source_role'] = 'assistant'
            if not str(content.get('source_type') or '').strip():
                content['source_type'] = 'assistant_generated'
            asset_endpoint_mode = str(content.get('endpoint_mode') or content.get('api_endpoint_mode') or current_endpoint_mode or '').strip()
            try:
                if asset_endpoint_mode:
                    asset_endpoint_mode = _normalize_chat_api_endpoint_mode(asset_endpoint_mode)
            except Exception:
                pass
            if current_endpoint_mode and asset_endpoint_mode and current_endpoint_mode != asset_endpoint_mode:
                continue
            if asset_endpoint_mode:
                # image_reply 外层属于会话链路；图片提供商内部的模式标记
                # 不能反向覆盖会话模式，否则 Responses 续轮会过滤自己的生成图。
                content['endpoint_mode'] = asset_endpoint_mode
                content['api_endpoint_mode'] = asset_endpoint_mode
            imgs = content.get('images') if isinstance(content.get('images'), list) else []
            normalized_imgs: list[dict] = []
            for img in imgs:
                if not isinstance(img, dict):
                    continue
                ii = dict(img)
                if not str(ii.get('source_role') or '').strip():
                    ii['source_role'] = 'assistant'
                if not str(ii.get('source_type') or ii.get('sourceType') or '').strip():
                    ii['source_type'] = str(content.get('source_type') or 'assistant_generated')
                if asset_endpoint_mode:
                    ii['endpoint_mode'] = asset_endpoint_mode
                    ii['api_endpoint_mode'] = asset_endpoint_mode
                normalized_imgs.append(ii)
            content['images'] = normalized_imgs
            imgs = normalized_imgs
            if not imgs:
                continue
            sig_parts: list[str] = []
            for img in imgs[:4]:
                if not isinstance(img, dict):
                    continue
                sig_parts.append(str(img.get('model_storage_ref') or img.get('storage_ref') or img.get('raw_url') or img.get('rawUrl') or img.get('view_url') or img.get('viewUrl') or img.get('download_url') or img.get('downloadUrl') or img.get('preview_url') or img.get('previewUrl') or img.get('url') or img.get('src') or img.get('image_id') or img.get('id') or '').strip())
            sig = '|'.join([x for x in sig_parts if x])
            if not sig or sig in seen:
                continue
            seen.add(sig)
            created = content.get('created_at_ms') or content.get('createdAtMs') or content.get('created_at') or content.get('createdAt') or None
            out.append({
                'role': 'assistant',
                '_image_asset_context_only': True,
                'created_at_ms': created,
                'createdAtMs': created,
                'content': content,
            })
        self.external_image_asset_messages = out
        return out

    def log_external_image_assets(self) -> None:
        try:
            out = self.external_image_asset_messages
            if out:
                debug_rows: list[dict] = []
                for _midx, _msg in enumerate(out[:8], 1):
                    _content = _msg.get('content') if isinstance(_msg, dict) and isinstance(_msg.get('content'), dict) else {}
                    for _iidx, _img in enumerate((_content.get('images') if isinstance(_content.get('images'), list) else [])[:4], 1):
                        if not isinstance(_img, dict):
                            continue
                        debug_rows.append({
                            'reply_index': _midx,
                            'image_index': _iidx,
                            'image_id': str(_img.get('image_id') or _img.get('attachment_id') or '')[:80],
                            'source_role': str(_img.get('source_role') or _content.get('source_role') or '')[:40],
                            'source_type': str(_img.get('source_type') or _content.get('source_type') or '')[:60],
                            'operation': str(_img.get('operation') or _img.get('task_mode') or _content.get('operation') or '')[:60],
                            'model_storage_ref': bool(str(_img.get('model_storage_ref') or '').strip()),
                            'storage_ref': bool(str(_img.get('storage_ref') or '').strip()),
                            'file_library_id': bool(str(_img.get('file_library_id') or _img.get('library_file_id') or '').strip()),
                            'url_kind': ('data_url' if str(_img.get('url') or '').startswith('data:image/') else ('storage_ref' if str(_img.get('url') or '').startswith('upload://') else ('http' if str(_img.get('url') or '').startswith(('http://', 'https://')) else ('other' if str(_img.get('url') or '').strip() else '')))),
                            'raw_kind': ('data_url' if str(_img.get('raw_url') or _img.get('rawUrl') or '').startswith('data:image/') else ('storage_ref' if str(_img.get('raw_url') or _img.get('rawUrl') or '').startswith('upload://') else ('http' if str(_img.get('raw_url') or _img.get('rawUrl') or '').startswith(('http://', 'https://')) else ('other' if str(_img.get('raw_url') or _img.get('rawUrl') or '').strip() else '')))),
                        })
                app_logger.info('[AGENT_STREAM_EXTERNAL_IMAGE_ASSETS_LOADED] count=%s images=%s detail=%s', len(out), sum(len(((m.get('content') or {}).get('images') or [])) for m in out if isinstance(m, dict)), json.dumps(debug_rows[:16], ensure_ascii=False))
        except Exception:
            pass

    def messages_for_image_index(self, base_messages: list | None = None) -> list:
        base = [m for m in (base_messages if isinstance(base_messages, list) else (self.messages or [])) if isinstance(m, dict)]
        if not self.external_image_asset_messages:
            return base
        return [*base, *[dict(m) for m in self.external_image_asset_messages]]
