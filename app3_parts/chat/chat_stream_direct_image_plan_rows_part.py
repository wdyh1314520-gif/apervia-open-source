# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: row-key, lineage, dedupe, and grouping helpers for direct image plans.
# Loaded before chat_streaming_part.py, sharing the original global namespace.


class ChatStreamDirectImagePlanRows:
    def __init__(self, *, resolve=None):
        self.resolve = resolve if callable(resolve) else (lambda values, limit=4: [])

    def row_key(self, row: dict | None = None) -> str:
        row = row or {}
        return str(
            row.get('stable_image_id')
            or row.get('current_user_image_id')
            or row.get('role_image_id')
            or row.get('global_label')
            or row.get('attachment_key')
            or row.get('image_id')
            or row.get('url')
            or ''
        ).strip()

    def row_public_id(self, row: dict | None = None) -> str:
        row = row or {}
        return str(
            row.get('stable_image_id')
            or row.get('current_user_image_id')
            or row.get('role_image_id')
            or row.get('global_label')
            or row.get('image_id')
            or row.get('attachment_key')
            or ''
        ).strip()

    def add_unique(self, dst: list[dict], rows: list[dict], max_items: int = 4) -> list[dict]:
        seen = {self.row_key(r) for r in dst if self.row_key(r)}
        for row in rows or []:
            key = self.row_key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            dst.append(dict(row))
            if len(dst) >= max(1, int(max_items or 4)):
                break
        return dst

    def row_lineage_ids(self, row: dict | None = None) -> list[str]:
        row = row or {}
        ids: list[str] = []
        for raw in (row.get('parent_image_id'), row.get('source_image_ids'), row.get('derived_from')):
            if isinstance(raw, str):
                vals = [raw]
            elif isinstance(raw, list):
                vals = raw
            else:
                vals = []
            for val in vals:
                token = str(val or '').strip()
                if token and token not in ids:
                    ids.append(token)
        return ids

    def lineage_rows_for(self, rows: list[dict] | None = None, *, limit: int = 8) -> list[dict]:
        lineage_ids: list[str] = []
        for row in rows or []:
            for token in self.row_lineage_ids(row):
                if token and token not in lineage_ids:
                    lineage_ids.append(token)
        if not lineage_ids:
            return []
        return self.resolve(lineage_ids, limit=limit)

    def row_group_name(self, row: dict) -> str:
        role = str(row.get('role') or row.get('source_role') or '').strip().lower()
        stable_id = str(row.get('current_user_image_id') or row.get('stable_image_id') or '').strip()
        binding_mode = str(row.get('binding_mode') or '').strip().lower()
        if stable_id.startswith('current_user_image_') or binding_mode == 'current_user_message':
            return 'current_user_rows'
        if role == 'assistant' or stable_id.startswith('assistant_img_'):
            return 'assistant_rows'
        return 'historical_rows'

    def grouped_source_rows(
        self,
        rows: list[dict] | None = None,
        *,
        max_items: int = 8,
        priority_rows: list[dict] | None = None,
    ) -> tuple[dict, list[dict]]:
        grouped = {
            'current_user_rows': [],
            'assistant_rows': [],
            'historical_rows': [],
            'overflow_rows': [],
            'ordered_rows': [],
            'overflow_index': [],
        }
        try:
            max_i = max(1, min(int(max_items or 8), 16))
        except Exception:
            max_i = 8

        all_rows: list[dict] = []
        seen_all: set[str] = set()

        def push_all(src_rows: list[dict] | None = None):
            for row in src_rows or []:
                if not isinstance(row, dict):
                    continue
                key = self.row_key(row)
                if not key or key in seen_all:
                    continue
                seen_all.add(key)
                all_rows.append(dict(row))

        # Explicitly selected / clicked / model-bound rows are not a semantic
        # keyword rule. They are structured state already chosen upstream.
        push_all(priority_rows or [])
        push_all(self.lineage_rows_for(priority_rows or [], limit=8))
        push_all(rows or [])

        group_rank = {'current_user_rows': 0, 'assistant_rows': 1, 'historical_rows': 2}

        def sort_key(item: tuple[int, dict]) -> tuple[int, int]:
            original_index, row = item
            key = self.row_key(row)
            is_priority = 0 if key and any(self.row_key(p) == key for p in (priority_rows or []) if isinstance(p, dict)) else 1
            return (is_priority, group_rank.get(self.row_group_name(row), 9), original_index)

        ordered_all = [row for _, row in sorted(enumerate(all_rows), key=sort_key)]
        ordered: list[dict] = []
        overflow: list[dict] = []
        ordered_seen: set[str] = set()
        for row in ordered_all:
            key = self.row_key(row)
            if not key or key in ordered_seen:
                continue
            ordered_seen.add(key)
            if len(ordered) < max_i:
                ordered.append(dict(row))
                grouped[self.row_group_name(row)].append(dict(row))
            else:
                overflow.append(dict(row))

        grouped['ordered_rows'] = [dict(r) for r in ordered]
        grouped['overflow_rows'] = [dict(r) for r in overflow]
        overflow_index = []
        for row in overflow[:24]:
            if not isinstance(row, dict):
                continue
            overflow_index.append({
                'id': self.row_public_id(row),
                'role': str(row.get('role') or row.get('source_role') or ''),
                'display_label': str(row.get('display_label') or row.get('role_label') or row.get('global_label') or ''),
                'message_index': row.get('message_index'),
                'image_index_in_message': row.get('idx'),
                'parent_image_id': str(row.get('parent_image_id') or ''),
                'source_image_ids': row.get('source_image_ids') if isinstance(row.get('source_image_ids'), list) else [],
                'derived_from': row.get('derived_from') if isinstance(row.get('derived_from'), list) else [],
            })
        grouped['overflow_index'] = overflow_index
        return grouped, ordered
