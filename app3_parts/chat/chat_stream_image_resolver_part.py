# image id/alias enrichment and direct resolver helpers for chat image tools.


class ChatStreamImageResolver:
    def __init__(self, *, label: str = ''):
        self.label = str(label or '')

    def arg_string_values(self, args: dict | None = None, *keys: str) -> list[str]:
        data = dict(args or {}) if isinstance(args, dict) else {}
        out: list[str] = []

        def push(value) -> None:
            if value is None:
                return
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    push(item)
                return
            if isinstance(value, dict):
                for key in ('image_id', 'id', 'label', 'role_image_id', 'global_label', 'attachment_key', 'url'):
                    if value.get(key) is not None:
                        push(value.get(key))
                return
            text = str(value or '').strip()
            if text and text not in out:
                out.append(text)

        for key in keys:
            push(data.get(key))
        return out


    def image_row_key(self, row: dict | None = None) -> str:
        row = dict(row or {})
        item = dict(row.get('item') or {})
        key = str(row.get('attachment_key') or '').strip()
        if not key:
            try:
                helper = globals().get('_image_item_attachment_key')
                if callable(helper):
                    key = str(helper(item) or '').strip()
            except Exception:
                key = ''
        return key or str(row.get('url') or '').strip() or str(row.get('image_id') or '').strip()

    def image_id_norm(self, value: str = '') -> str:
        return re.sub(r'\s+', '', str(value or '').strip()).lower()

    def image_id_variants(self, value: str = '') -> list[str]:
        raw = str(value or '').strip()
        if not raw:
            return []
        out: list[str] = []
        for item in (raw, raw.lower(), self.image_id_norm(raw)):
            item = str(item or '').strip()
            if item and item not in out:
                out.append(item)
        try:
            compact = self.direct_image_ref_norm(raw)
            if compact and compact not in out:
                out.append(compact)
        except Exception:
            pass
        return out

    def image_alias_numeric_token(self, value: str = '') -> str:
        raw = str(value or '').strip()
        if not raw:
            return ''
        low = raw.lower()
        for pat in (
            r'^assistant_img_(\d+)$',
            r'^assistant_generated_image_(\d+)$',
            r'^assistant_generated_img_(\d+)$',
            r'^generated_image_(\d+)$',
            r'^generated_img_(\d+)$',
            r'^current_user_image_(\d+)$',
            r'^current_user_img_(\d+)$',
            r'^previous_user_image_(\d+)$',
            r'^previous_user_img_(\d+)$',
            r'^historical_image_(\d+)$',
        ):
            m = re.fullmatch(pat, low)
            if m:
                return str(int(m.group(1)))
        m = re.search(r'第\s*(\d+)\s*张?', raw)
        if m:
            return str(int(m.group(1)))
        m = re.search(r'(?:图|img|image)\s*_?\s*(\d+)\s*$', low)
        if m:
            return str(int(m.group(1)))
        return ''

    def alias_matches_primary_number(self, alias: str = '', primary_id: str = '') -> bool:
        alias = str(alias or '').strip()
        primary_id = str(primary_id or '').strip()
        if not alias or not primary_id:
            return True
        primary_low = primary_id.lower()
        m = re.fullmatch(r'assistant_img_(\d+)', primary_low)
        if m:
            primary_no = str(int(m.group(1)))
            alias_no = self.image_alias_numeric_token(alias)
            low = alias.lower()
            generated_context = (
                bool(re.search(r'^(assistant|generated)_', low))
                or any(x in alias for x in ('助手', '生成', '成品', '你生成', '我生成'))
            )
            if re.fullmatch(r'assistant_img_\d+', low):
                return alias_no == primary_no
            if generated_context and alias_no and alias_no != primary_no:
                return False
            return True
        m = re.fullmatch(r'current_user_image_(\d+)', primary_low)
        if m:
            primary_no = str(int(m.group(1)))
            alias_no = self.image_alias_numeric_token(alias)
            low = alias.lower()
            current_context = (
                low.startswith(('current_user_', 'user_current_', 'current_', 'turn_', 'user_'))
                or any(x in alias for x in ('本轮', '当前', '用户'))
            )
            if current_context and alias_no and alias_no != primary_no:
                return False
            return True
        return True

    def sanitize_image_aliases(self, row: dict | None = None, aliases: list | None = None, *, stable_id: str = '') -> list[str]:
        row = dict(row or {}) if isinstance(row, dict) else {}
        primary = str(stable_id or row.get('current_user_image_id') or row.get('stable_image_id') or '').strip()
        if not primary:
            primary = str(row.get('role_image_id') or row.get('image_id') or '').strip()
        out: list[str] = []
        for val in aliases or []:
            val = str(val or '').strip()
            if not val:
                continue
            if primary and not self.alias_matches_primary_number(val, primary):
                continue
            if val not in out:
                out.append(val)
        if primary and primary not in out:
            out.insert(0, primary)
        return out

    def exact_selected_image_rows(self, raw_values, candidate_rows: list[dict] | None = None, *, limit: int = 8) -> list[dict]:
        rows = [dict(r) for r in (candidate_rows or []) if isinstance(r, dict)]
        values = raw_values if isinstance(raw_values, list) else ([raw_values] if raw_values else [])
        selected_keys: list[str] = []
        for raw in values:
            for key in self.image_id_variants(str(raw or '').strip()):
                if key and key not in selected_keys:
                    selected_keys.append(key)
        if not rows or not selected_keys:
            return []
        selected_set = set(selected_keys)
        out: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            primary_ids = []
            for key_name in ('current_user_image_id', 'stable_image_id'):
                val = str(row.get(key_name) or '').strip()
                if val and val not in primary_ids:
                    primary_ids.append(val)
            role_id = str(row.get('role_image_id') or '').strip()
            stable_id = str(row.get('stable_image_id') or row.get('current_user_image_id') or '').strip()
            # role_image_id is allowed as an exact id only when it is not fighting
            # the row's stable id. This avoids assistant_img_2 matching a row whose
            # stable id is assistant_img_3 because stale metadata leaked through.
            if role_id and (not stable_id or role_id == stable_id or not (role_id.startswith('assistant_img_') and stable_id.startswith('assistant_img_'))):
                primary_ids.append(role_id)
            hit = False
            for pid in primary_ids:
                if any(k in selected_set for k in self.image_id_variants(pid)):
                    hit = True
                    break
            if not hit:
                continue
            key = self.image_row_key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(dict(row))
            if len(out) >= max(1, int(limit or 8)):
                break
        return out

    def enrich_direct_image_candidate_rows(self, candidate_rows: list[dict] | None = None) -> list[dict]:
        current_rows = [dict(r) for r in (candidate_rows or []) if isinstance(r, dict) and _agent_stream_is_current_user_image_row(r)]
        rows = [dict(r) for r in (candidate_rows or []) if isinstance(r, dict) and not _agent_stream_is_current_user_image_row(r)]
        current_by_key = {self.image_row_key(r): dict(r) for r in current_rows if self.image_row_key(r)}
        seen: set[str] = set()
        out: list[dict] = []
        historical_counts = {'user': 0, 'assistant': 0, 'other': 0}

        def enrich_historical(row: dict) -> dict:
            enriched = dict(row or {})
            key = self.image_row_key(enriched)
            role = str(enriched.get('role') or enriched.get('source_role') or '').strip().lower()
            if role == 'user':
                bucket = 'user'
                prefix = 'previous_user_image'
                label = '历史用户图'
            elif role == 'assistant':
                bucket = 'assistant'
                prefix = 'assistant_img'
                label = '历史助手图'
            else:
                bucket = 'other'
                prefix = 'historical_image'
                label = '历史图片'
            historical_counts[bucket] = int(historical_counts.get(bucket) or 0) + 1
            pos = historical_counts[bucket]
            role_image_id = str(enriched.get('role_image_id') or '').strip()
            role_label = str(enriched.get('role_label') or '').strip()
            role_pos = str(enriched.get('role_image_index') or '').strip()
            stable_id = str(enriched.get('stable_image_id') or '').strip()
            if not stable_id or stable_id.startswith('current_user_image_') or re.fullmatch(r'(?:assistant|previous_user|historical)_image_\d+', stable_id or ''):
                stable_id = role_image_id or (f'{prefix}_{role_pos}' if role_pos else f'{prefix}_{pos}')
            if role == 'assistant':
                _stable_m = re.fullmatch(r'assistant_img_(\d+)', str(stable_id or '').strip())
                if _stable_m:
                    _assistant_no = str(int(_stable_m.group(1)))
                    role_image_id = stable_id
                    role_label = f'助手生成图{_assistant_no}'
                    role_pos = _assistant_no
                    enriched['role_image_id'] = stable_id
                    enriched['role_label'] = role_label
                    enriched['role_image_index'] = int(_assistant_no)
            aliases: list[str] = []
            for val in [
                *(enriched.get('alias_ids') if isinstance(enriched.get('alias_ids'), list) else []),
                stable_id,
                role_image_id,
                role_label,
                f'{prefix}_{role_pos}' if role_pos else '',
                f'{prefix.replace("_image", "_img")}_{role_pos}' if role_pos else '',
                f'{prefix}_{pos}',
                f'{prefix.replace("_image", "_img")}_{pos}',
                f'{role}_image_{role_pos}' if role_pos else '',
                f'{role}_img_{role_pos}' if role_pos else '',
                f'historical_{role or "image"}_image_{role_pos or pos}',
                f'{label}{role_pos or pos}',
                role_label or f'{label}{pos}',
                f'历史{role_label}' if role_label else f'历史{label}{pos}',
                enriched.get('global_label'),
                enriched.get('image_id'),
                key,
                enriched.get('url'),
            ]:
                val = str(val or '').strip()
                if val and val not in aliases:
                    aliases.append(val)
            if role == 'assistant':
                assistant_pos_values = []
                for _v in (role_pos, pos):
                    _s = str(_v or '').strip()
                    if _s and _s not in assistant_pos_values:
                        assistant_pos_values.append(_s)
                for _pos_token in assistant_pos_values:
                    for val in [
                        f'assistant_img_{_pos_token}',
                        f'assistant_generated_image_{_pos_token}',
                        f'generated_image_{_pos_token}',
                        f'generated_img_{_pos_token}',
                        f'助手生成图{_pos_token}',
                        f'助手第{_pos_token}张图',
                        f'助手生成的第{_pos_token}张图',
                        f'你生成的第{_pos_token}张图',
                        f'你生成的第{_pos_token}张',
                        f'我生成的第{_pos_token}张图',
                        f'我生成的第{_pos_token}张',
                        f'生成的第{_pos_token}张图',
                        f'第{_pos_token}张生成图',
                        f'第{_pos_token}张成品图',
                        f'成品图{_pos_token}',
                    ]:
                        val = str(val or '').strip()
                        if val and val not in aliases:
                            aliases.append(val)
            aliases = self.sanitize_image_aliases(enriched, aliases, stable_id=stable_id)
            enriched['stable_image_id'] = stable_id
            enriched['historical_image_id'] = stable_id
            enriched['display_label'] = str(role_label or enriched.get('display_label') or enriched.get('global_label') or f'{label}{pos}').strip()
            enriched['alias_ids'] = aliases
            enriched['binding_mode'] = str(enriched.get('binding_mode') or 'historical_chat_image').strip()
            enriched['binding_desc'] = str(enriched.get('binding_desc') or f'historical_chat_image:{role or "unknown"}:{pos}').strip()
            summary = str(enriched.get('summary') or '').strip()
            stable_summary = f'stable_id={stable_id}; display_label={enriched.get("display_label")}; role={role or "unknown"}; message_index={enriched.get("message_index")}; image_index_in_message={enriched.get("idx")}; aliases={", ".join(aliases[:8])}'
            enriched['summary'] = (stable_summary + ('; ' + summary if summary else ''))[:1200]
            return enriched

        for row in rows:
            key = self.image_row_key(row)
            if key in current_by_key:
                enriched = dict(row)
                cur = current_by_key.get(key) or {}
                aliases = self.sanitize_image_aliases(
                    enriched,
                    [*(enriched.get('alias_ids') if isinstance(enriched.get('alias_ids'), list) else []), *(cur.get('alias_ids') if isinstance(cur.get('alias_ids'), list) else [])],
                    stable_id=str(cur.get('stable_image_id') or cur.get('current_user_image_id') or ''),
                )
                enriched.update({k: v for k, v in cur.items() if k in {'current_user_image_id', 'stable_image_id', 'display_label', 'current_turn_index', 'binding_mode', 'binding_desc'}})
                enriched['alias_ids'] = aliases
                if cur.get('summary'):
                    enriched['summary'] = str(cur.get('summary') or '')[:1200]
                row = enriched
            else:
                row = enrich_historical(row)
            if key:
                seen.add(key)
            out.append(row)
        for cur in current_rows:
            key = self.image_row_key(cur)
            if key and key not in seen:
                out.insert(0, dict(cur))
                seen.add(key)
        return out

    def direct_image_ref_norm(self, value: str = '') -> str:
        raw = str(value or '').strip().lower()
        if not raw:
            return ''
        return re.sub(r'[^0-9a-zA-Z_\-一二两三四五六七八九十图张幅个当前用户本轮第]+', '', raw)

    def direct_resolve_image_rows(self, raw_values, candidate_rows: list[dict] | None = None, *, limit: int = 4) -> list[dict]:
        rows = [dict(r) for r in (candidate_rows or []) if isinstance(r, dict)]
        values = raw_values if isinstance(raw_values, list) else ([raw_values] if raw_values else [])
        if not rows or not values:
            return []
        exact_rows = self.exact_selected_image_rows(values, rows, limit=limit)
        if exact_rows:
            return exact_rows

        alias_rows: dict[str, list[dict]] = {}
        # Alias lookup is intentionally a pure id->row mapper. It does not infer
        # user intent; it only lands the ids chosen by the model onto actual files.
        # Ambiguous aliases are ignored instead of attaching the wrong image.
        for row in rows:
            stable_id = str(row.get('current_user_image_id') or row.get('stable_image_id') or '').strip()
            keys: list[str] = []
            for key_name in ('display_label', 'image_id', 'role_label', 'global_label', 'attachment_key', 'url'):
                keys.append(str(row.get(key_name) or '').strip())
            role_id = str(row.get('role_image_id') or '').strip()
            if role_id and (not stable_id or role_id == stable_id or not (role_id.startswith('assistant_img_') and stable_id.startswith('assistant_img_'))):
                keys.append(role_id)
            aliases = row.get('alias_ids') if isinstance(row.get('alias_ids'), list) else []
            keys.extend(self.sanitize_image_aliases(row, aliases, stable_id=stable_id))
            for key in keys:
                if not key:
                    continue
                if stable_id and not self.alias_matches_primary_number(key, stable_id):
                    continue
                for k in self.image_id_variants(key):
                    if not k:
                        continue
                    bucket = alias_rows.setdefault(k, [])
                    row_key = self.image_row_key(row)
                    if row_key and not any(self.image_row_key(x) == row_key for x in bucket):
                        bucket.append(dict(row))
        out: list[dict] = []
        seen: set[str] = set()
        for raw in values:
            token = str(raw or '').strip()
            if not token:
                continue
            row = None
            for k in self.image_id_variants(token):
                bucket = alias_rows.get(k) or []
                if len(bucket) == 1:
                    row = dict(bucket[0])
                    break
            if not row:
                continue
            key = self.image_row_key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(dict(row))
            if len(out) >= max(1, int(limit or 4)):
                break
        if out:
            return out
        return []
