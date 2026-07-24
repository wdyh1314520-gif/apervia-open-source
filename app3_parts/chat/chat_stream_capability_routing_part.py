# Chat/Responses capability group normalization and first-round soft preselection.

import json
import os
import re
import sys


class ChatStreamCapabilityRoutingContext:
    def __init__(
        self,
        *,
        model: str = '',
        image_generation_enabled: bool = False,
        web_enabled_for_turn=None,
        account_history_enabled=None,
        single_sandbox_file_plane_enabled=None,
        responses_code_interpreter_enabled=None,
        latest_user_text=None,
        recent_image_context=None,
        logger=None,
    ):
        self.model = str(model or '')
        self.image_generation_enabled = bool(image_generation_enabled)
        self.web_enabled_for_turn = web_enabled_for_turn if callable(web_enabled_for_turn) else (lambda: True)
        self.account_history_enabled = account_history_enabled if callable(account_history_enabled) else (lambda: False)
        self.single_sandbox_file_plane_enabled = single_sandbox_file_plane_enabled if callable(single_sandbox_file_plane_enabled) else (lambda: True)
        self.responses_code_interpreter_enabled = responses_code_interpreter_enabled if callable(responses_code_interpreter_enabled) else (lambda: False)
        self.latest_user_text = latest_user_text if callable(latest_user_text) else (lambda messages=None: '')
        self.recent_image_context = recent_image_context if callable(recent_image_context) else (lambda messages=None, max_chars=600: {})
        self.logger = logger or globals().get('app_logger')

    def responses_native_capability_group_names(self) -> list[str]:
        groups = []
        registry_groups = globals().get('skill_groups_for_mode')
        if callable(registry_groups):
            try:
                groups = [str(x or '').strip() for x in (registry_groups('responses') or []) if str(x or '').strip()]
            except Exception:
                groups = []
        if not groups:
            groups = ['web', 'weather', 'location', 'image_generate', 'image', 'sandbox', 'knowledge', 'history']
        preferred_order = ['web', 'weather', 'location', 'image_generate', 'image', 'sandbox', 'knowledge', 'history', 'memory', 'code_interpreter']
        groups = sorted(set(groups), key=lambda g: (preferred_order.index(g) if g in preferred_order else 999, g))
        if not self.single_sandbox_file_plane_enabled() and 'file' not in groups:
            insert_at = groups.index('sandbox') if 'sandbox' in groups else len(groups)
            groups.insert(insert_at, 'file')
        if not str(sys.platform or '').lower().startswith('linux'):
            groups = [g for g in groups if g not in {'sandbox', 'sandbox'}]
        if self.responses_code_interpreter_enabled():
            groups = ['code_interpreter'] + [g for g in groups if g != 'code_interpreter']
        if not self.web_enabled_for_turn():
            groups = [g for g in groups if g != 'web']
        if not self.account_history_enabled():
            groups = [g for g in groups if g != 'history']
        return groups

    def responses_native_capability_groups(self, raw_groups=None) -> list[str]:
        base_groups = self.responses_native_capability_group_names()
        allowed = set(base_groups) | {'all'}
        values = raw_groups
        if isinstance(values, str):
            text = values.strip()
            if text.startswith('['):
                try:
                    parsed = json.loads(text)
                    values = parsed if isinstance(parsed, list) else [text]
                except Exception:
                    values = [text]
            else:
                values = re.split(r'[,;，；\s]+', text)
        elif not isinstance(values, list):
            values = []
        resolver = globals().get('skill_resolve_public_keys')
        if callable(resolver):
            try:
                resolved = [str(x or '').strip() for x in (resolver(values, 'responses', allowed_groups=base_groups) or []) if str(x or '').strip()]
                if 'all' in resolved:
                    return ['all'] if self.web_enabled_for_turn() else list(base_groups)
                return resolved
            except Exception:
                pass
        out: list[str] = []
        for item in values:
            group = str(item or '').strip().lower()
            if group in {'python', 'code', 'analysis', 'code-interpreter'}:
                group = 'code_interpreter'
            if group in allowed and group not in out:
                out.append(group)
        if 'all' in out:
            if self.web_enabled_for_turn():
                return ['all']
            return list(base_groups)
        return out

    def chat_capability_group_names(self) -> list[str]:
        groups = []
        registry_groups = globals().get('skill_groups_for_mode')
        if callable(registry_groups):
            try:
                groups = [str(x or '').strip() for x in (registry_groups('chat_completions') or []) if str(x or '').strip()]
            except Exception:
                groups = []
        if not groups:
            groups = ['web', 'weather', 'location', 'image_generate', 'image', 'sandbox', 'knowledge', 'history', 'memory']
        groups = [g for g in groups if g != 'code_interpreter']
        preferred_order = ['web', 'weather', 'location', 'image_generate', 'image', 'sandbox', 'knowledge', 'history', 'memory']
        groups = sorted(set(groups), key=lambda g: (preferred_order.index(g) if g in preferred_order else 999, g))
        if not str(sys.platform or '').lower().startswith('linux'):
            groups = [g for g in groups if g != 'sandbox']
        if not self.web_enabled_for_turn():
            groups = [g for g in groups if g != 'web']
        if not self.account_history_enabled():
            groups = [g for g in groups if g != 'history']
        return groups

    def chat_capability_groups(self, raw_groups=None) -> list[str]:
        base_groups = self.chat_capability_group_names()
        allowed = set(base_groups) | {'all'}
        values = raw_groups
        if isinstance(values, str):
            text = values.strip()
            if text.startswith('['):
                try:
                    parsed = json.loads(text)
                    values = parsed if isinstance(parsed, list) else [text]
                except Exception:
                    values = [text]
            else:
                values = re.split(r'[,;，；\s]+', text)
        elif not isinstance(values, list):
            values = []
        resolver = globals().get('skill_resolve_public_keys')
        if callable(resolver):
            try:
                resolved = [str(x or '').strip() for x in (resolver(values, 'chat_completions', allowed_groups=base_groups) or []) if str(x or '').strip()]
                if 'all' in resolved:
                    return ['all'] if self.web_enabled_for_turn() else list(base_groups)
                return resolved
            except Exception:
                pass
        out: list[str] = []
        for item in values:
            group = str(item or '').strip().lower()
            if group in allowed and group not in out:
                out.append(group)
        if 'all' in out:
            if self.web_enabled_for_turn():
                return ['all']
            return list(base_groups)
        return out

    def responses_native_file_record_is_image(self, rec: dict | None = None) -> bool:
        row = rec if isinstance(rec, dict) else {}
        name = str(row.get('filename') or row.get('name') or row.get('saved_filename') or '').strip().lower()
        ext = str(row.get('ext') or '').strip().lower()
        if ext and not ext.startswith('.'):
            ext = '.' + ext
        if not ext and name:
            try:
                ext = os.path.splitext(name)[1].lower()
            except Exception:
                ext = ''
        mime = str(row.get('mime') or row.get('mime_type') or row.get('content_type') or '').strip().lower()
        category = str(row.get('category') or row.get('file_category') or row.get('kind') or '').strip().lower()
        image_exts = set(globals().get('_FILE_LIBRARY_IMAGE_EXTS') or {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg', '.tif', '.tiff', '.ico', '.jfif', '.heic', '.heif'})
        return bool(category == 'image' or mime.startswith('image/') or (ext and ext in image_exts))

    def responses_native_current_turn_image_records(self, base_messages: list | None = None) -> list[dict]:
        try:
            msgs = [dict(m) if isinstance(m, dict) else m for m in (base_messages or [])]
            collector = globals().get('_collect_history_file_records')
            current_selector = globals().get('_select_current_turn_file_records')
            if not callable(collector) or not callable(current_selector):
                return []
            records, _heavy_indexes = collector(msgs)
            current_rows = current_selector(records or [], msgs) or []
            return [dict(r) for r in current_rows if isinstance(r, dict) and self.responses_native_file_record_is_image(r)]
        except Exception:
            return []

    def responses_native_file_task_soft_preselect(self, base_messages: list | None = None) -> tuple[bool, str]:
        msgs = [dict(m) if isinstance(m, dict) else m for m in (base_messages or [])]
        if not msgs:
            return False, ''
        try:
            text = str(self.latest_user_text(msgs or []) or '').strip()
        except Exception:
            text = ''
        try:
            preselector = globals().get('task_capability_preselect')
            preselected = dict(preselector(text=text, messages=msgs) or {}) if callable(preselector) else {}
            if 'sandbox' in set(preselected.get('groups') or []):
                return True, str(preselected.get('reason') or 'file_create_or_export_intent')
        except Exception:
            pass
        try:
            collector = globals().get('_collect_history_file_records')
            if not callable(collector):
                return False, ''
            records, _heavy_indexes = collector(msgs)
            if not records:
                return False, ''
            current_selector = globals().get('_select_current_turn_file_records')
            query_selector = globals().get('_select_history_file_records_for_query')
            current_turn_records = current_selector(records, msgs) if callable(current_selector) else []
            if current_turn_records:
                try:
                    image_rows = [r for r in current_turn_records if isinstance(r, dict) and self.responses_native_file_record_is_image(r)]
                    if image_rows and len(image_rows) == len(current_turn_records):
                        return False, 'current_turn_image_attachment'
                except Exception:
                    pass
                return True, 'current_turn_file_attachment'
            query_selected = query_selector(records, text) if callable(query_selector) else []
            if query_selected:
                return True, 'explicit_file_reference'
        except Exception as err:
            try:
                self.logger.warning('[RESPONSES_NATIVE_FILE_SOFT_PRESELECT_FAILED] err=%s:%s', type(err).__name__, err)
            except Exception:
                pass
        return False, ''

    def responses_native_image_generation_preclassify(self, base_messages: list | None = None) -> dict:
        groups = ['all']
        soft_file_sandbox = False
        soft_file_reason = ''
        has_images = False
        image_count = 0
        current_turn_image_count = 0
        try:
            image_ctx = self.recent_image_context(base_messages or [], max_chars=600)
            has_images = bool((image_ctx or {}).get('has_images') or str((image_ctx or {}).get('text') or '').strip())
            image_count = int((image_ctx or {}).get('count') or 0)
        except Exception:
            has_images = False
            image_count = 0
        try:
            current_turn_image_count = len(self.responses_native_current_turn_image_records(base_messages or []))
        except Exception:
            current_turn_image_count = 0
        try:
            soft_file_sandbox, soft_file_reason = self.responses_native_file_task_soft_preselect(base_messages or [])
        except Exception:
            soft_file_sandbox, soft_file_reason = False, ''
        if soft_file_sandbox:
            groups = ['sandbox'] if self.single_sandbox_file_plane_enabled() else ['file']
        out = {
            'use_tools': True,
            'tool_groups': groups,
            'route_mode': 'responses_native_first_round_tool_select',
            'reason': 'responses_native_no_chat_gate_selector_first_round',
            'model': self.model,
            'image_generation_attach_candidates': False,
            'image_generation_eager_first': False,
            'image_task_type': '',
            'image_context_has_images': bool(has_images),
            'image_context_count': int(image_count or 0),
            'current_turn_image_count': int(current_turn_image_count or 0),
            'file_task_soft_sandbox': bool(soft_file_sandbox),
            'file_task_soft_reason': soft_file_reason,
        }
        try:
            self.logger.info(
                '[RESPONSES_NATIVE_FIRST_ROUND_LOCAL_GATE] model=%s groups=%s attach_candidates=%s images=%s file_soft=%s file_reason=%s reason=%s',
                self.model,
                json.dumps(groups, ensure_ascii=False),
                bool(out.get('image_generation_attach_candidates')),
                int(image_count or 0),
                bool(soft_file_sandbox),
                soft_file_reason,
                out.get('reason'),
            )
        except Exception:
            pass
        return out
