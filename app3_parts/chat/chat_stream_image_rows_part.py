# pure image-row classification and stable ordering helpers.


def _agent_stream_image_row_group_name(row: dict | None = None) -> str:
    row = row or {}
    role = str(row.get('role') or row.get('source_role') or '').strip().lower()
    stable_id = str(row.get('current_user_image_id') or row.get('stable_image_id') or row.get('role_image_id') or '').strip()
    binding_mode = str(row.get('binding_mode') or '').strip().lower()
    if stable_id.startswith('current_user_image_') or binding_mode == 'current_user_message':
        return 'current'
    if role == 'assistant' or stable_id.startswith('assistant_img_'):
        return 'assistant'
    return 'historical'


def _agent_stream_is_current_user_image_row(row: dict | None = None) -> bool:
    row = row or {}
    stable_id = str(row.get('current_user_image_id') or row.get('stable_image_id') or '').strip()
    binding_mode = str(row.get('binding_mode') or '').strip().lower()
    return bool(stable_id.startswith('current_user_image_') or str(row.get('current_user_image_id') or '').strip() or binding_mode == 'current_user_message')


def _agent_stream_image_row_numeric(value, default: int = 10**9) -> int:
    try:
        raw = str(value if value is not None else '').strip()
        if not raw:
            return int(default)
        m = re.search(r'\d+', raw)
        if not m:
            return int(default)
        return int(m.group(0))
    except Exception:
        return int(default)


def _agent_stream_image_row_stable_number(row: dict | None = None) -> int:
    row = row or {}
    for key in ('current_user_image_id', 'stable_image_id', 'role_image_id'):
        raw = str(row.get(key) or '').strip().lower()
        m = re.fullmatch(r'(?:current_user_image|assistant_img|previous_user_image|historical_image)_(\d+)', raw)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return 10**9


def _agent_stream_image_row_order_key(row: dict | None = None) -> tuple:
    row = row or {}
    group = _agent_stream_image_row_group_name(row)
    group_rank = {'current': 0, 'assistant': 1, 'historical': 2}.get(group, 9)
    stable_no = _agent_stream_image_row_stable_number(row)
    role_order = _agent_stream_image_row_numeric(row.get('role_image_index'))
    global_order = _agent_stream_image_row_numeric(row.get('global_image_index'))
    msg_index = _agent_stream_image_row_numeric(row.get('message_index'))
    idx = _agent_stream_image_row_numeric(row.get('idx'), default=0)
    if group == 'current':
        return (group_rank, idx, msg_index, stable_no, global_order)
    if group == 'assistant':
        return (group_rank, min(role_order, stable_no), stable_no, role_order, global_order, msg_index, idx)
    return (group_rank, msg_index, idx, min(global_order, stable_no), stable_no, role_order)


def _agent_stream_sort_image_rows(rows: list[dict] | None = None) -> list[dict]:
    clean = [dict(r) for r in (rows or []) if isinstance(r, dict)]
    return [row for _i, row in sorted(enumerate(clean), key=lambda item: (*_agent_stream_image_row_order_key(item[1]), item[0]))]
