# Split from app3_parts/account/user_personalization_runtime_part.py.
# Purpose: auth personalization memory store, history, tool ops, injection, and API routes.
# Loaded by user_personalization_runtime_part.py via _exec_split_file(...), sharing the original global namespace.

AUTH_PERSONALIZATION_MEMORY_FILE = _app_data_path('auth_personalization_memory_store.json')
_AUTH_PERSONALIZATION_MEMORY_LOCK = threading.Lock()
_AUTH_PERSONALIZATION_MEMORY_STATE = {
    'accounts': {},
    'updated_at': 0.0,
}
AUTH_PERSONALIZATION_MEMORY_MAX_ITEMS = 80
try:
    AUTH_PERSONALIZATION_MEMORY_HISTORY_MAX_VERSIONS = max(1, min(int(app_getenv('MEMORY_HISTORY_MAX_VERSIONS', '20') or 20), 200))
except Exception:
    AUTH_PERSONALIZATION_MEMORY_HISTORY_MAX_VERSIONS = 20
AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS = 600
AUTH_PERSONALIZATION_MEMORY_MAX_INSTRUCTION_CHARS = 1800
AUTH_PERSONALIZATION_CUSTOM_INSTRUCTION_MAX_CHARS = 900
AUTH_PERSONALIZATION_MEMORY_SCHEMA_VERSION = 3


def _auth_personalization_now_ms() -> int:
    try:
        return int(time.time() * 1000)
    except Exception:
        return 0


def _auth_personalization_trim_text(value, max_chars: int) -> str:
    text = str(value or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars]
    return text


def _auth_personalization_normalize_rule_type(value) -> str:
    raw = str(value or '').strip().lower().replace('-', '_').replace(' ', '_')
    if raw in {'hard', 'hard_rule', 'hard_rules', 'constraint', 'constraints', 'required', 'must'}:
        return 'soft'
    if raw in {'soft', 'soft_memory', 'soft_preference', 'preference', 'preferences', 'memory', 'profile'}:
        return 'soft'
    return ''


def _auth_personalization_strip_rule_prefix(text: str) -> tuple[str, str]:
    raw = _auth_personalization_trim_text(text or '', AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS)
    if not raw:
        return '', ''
    prefix_patterns = [
        (r'^\[(硬约束|硬规则|硬记忆|必须执行|强制)\]\s*', 'hard'),
        (r'^\[(软记忆|软偏好|偏好|长期记忆)\]\s*', 'soft'),
        (r'^(硬约束|硬规则|硬记忆|必须执行|强制)\s*[:：]\s*', 'hard'),
        (r'^(软记忆|软偏好|偏好|长期记忆)\s*[:：]\s*', 'soft'),
    ]
    for pattern, rule_type in prefix_patterns:
        try:
            matched = re.match(pattern, raw, flags=re.IGNORECASE)
        except Exception:
            matched = None
        if matched:
            stripped = _auth_personalization_trim_text(raw[matched.end():], AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS)
            return stripped, rule_type
    return raw, ''


def _auth_personalization_text_looks_hard_constraint(text: str) -> bool:
    content = str(text or '').strip()
    if not content:
        return False
    lowered = content.lower()
    strong_markers = ('必须', '一律', '始终', '默认都', '每次都', '所有回答都', '禁止', '只能', '务必')
    behavior_targets = (
        '回答', '回复', '输出', '表情', 'emoji', '先给结论', '结论', '解释', '语言', '英文', '中文', '代码', '格式', '称呼', '语气', '步骤'
    )
    if any(marker in content for marker in strong_markers) and any(target in content for target in behavior_targets):
        return True
    if lowered.startswith('default ') and any(token in lowered for token in ('reply', 'answer', 'output', 'emoji', 'code', 'format', 'language')):
        return True
    return False


def _auth_personalization_detect_rule_type(text: str, explicit_type: str = '') -> str:
    # Saved memories are advisory context. Do not auto-promote them into hard constraints.
    return 'soft'


def _auth_personalization_normalize_item(raw, idx: int = 0, now_ms: int | None = None) -> dict | None:
    ts_now = int(now_ms or _auth_personalization_now_ms() or 0)
    text = ''
    item_id = ''
    created_at = ts_now
    updated_at = ts_now
    explicit_type = ''
    if isinstance(raw, str):
        text = _auth_personalization_trim_text(raw, AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS)
    elif isinstance(raw, dict):
        text = _auth_personalization_trim_text(raw.get('text') or '', AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS)
        item_id = str(raw.get('id') or '').strip()
        explicit_type = (
            raw.get('ruleType')
            or raw.get('memoryType')
            or raw.get('type')
            or raw.get('kind')
            or raw.get('category')
            or ''
        )
        try:
            created_at = max(0, int(raw.get('createdAt') or raw.get('created_at') or ts_now))
        except Exception:
            created_at = ts_now
        try:
            updated_at = max(0, int(raw.get('updatedAt') or raw.get('updated_at') or created_at or ts_now))
        except Exception:
            updated_at = created_at or ts_now
    text, prefix_type = _auth_personalization_strip_rule_prefix(text)
    if not text:
        return None
    rule_type = _auth_personalization_detect_rule_type(text, explicit_type or prefix_type)
    if not item_id:
        item_id = f'mem_{ts_now:x}_{idx}_{uuid.uuid4().hex[:8]}'
    if created_at <= 0:
        created_at = ts_now
    if updated_at <= 0:
        updated_at = created_at
    return {
        'id': item_id,
        'text': text,
        'ruleType': rule_type,
        'createdAt': int(created_at),
        'updatedAt': int(updated_at),
    }


def _auth_personalization_split_items(items_payload) -> tuple[list[dict], list[dict]]:
    hard_items: list[dict] = []
    soft_items: list[dict] = []
    for raw in (items_payload or []):
        if not isinstance(raw, dict):
            continue
        target = hard_items if str(raw.get('ruleType') or '').strip().lower() == 'hard' else soft_items
        target.append(dict(raw))
    return hard_items, soft_items



def _auth_personalization_choice(value, allowed: set[str]) -> str:
    raw = str(value or '').strip().lower()
    return raw if raw in allowed else ''


def _auth_personalization_expression_line(state: dict | None = None) -> str:
    row = state if isinstance(state, dict) else {}
    style_map = {
        'professional': '专业可靠',
        'friendly': '亲和友善',
        'direct': '直言不讳',
        'practical': '高效务实',
    }
    structure_map = {'more': '多用标题/列表', 'less': '少用标题/列表'}
    emoji_map = {'more': '可多用表情', 'less': '少用表情'}
    parts = []
    for value in (
        style_map.get(str(row.get('responseStylePreset') or '')),
        structure_map.get(str(row.get('structurePreference') or '')),
        emoji_map.get(str(row.get('emojiPreference') or '')),
    ):
        if value:
            parts.append(value)
    return ('表达偏好：' + '；'.join(parts) + '。仅影响表达，不影响事实/工具。') if parts else ''

def _auth_personalization_normalize_state(state_payload) -> dict:
    src = state_payload if isinstance(state_payload, dict) else {}
    out = {
        'schemaVersion': AUTH_PERSONALIZATION_MEMORY_SCHEMA_VERSION,
        'memoryEnabled': bool(src.get('memoryEnabled')),
        'memoryAutoManageEnabled': bool(src.get('memoryAutoManageEnabled', True)),
        'historyReferenceEnabled': bool(src.get('historyReferenceEnabled', True)),
        'customInstruction': _auth_personalization_trim_text(src.get('customInstruction') or src.get('customResponseStyle') or src.get('responseStyle') or src.get('responseInstruction') or '', AUTH_PERSONALIZATION_CUSTOM_INSTRUCTION_MAX_CHARS),
        'profileNickname': _auth_personalization_trim_text(src.get('profileNickname') or src.get('nickname') or src.get('displayName') or '', 120),
        'profileOccupation': _auth_personalization_trim_text(src.get('profileOccupation') or src.get('occupation') or src.get('jobTitle') or '', 180),
        'profileDetails': _auth_personalization_trim_text(src.get('profileDetails') or src.get('customAboutUser') or src.get('aboutUser') or src.get('userProfileInstruction') or '', 700),
        'customAboutUser': '',
        'customResponseStyle': '',
        'memoryInstruction': _auth_personalization_trim_text(src.get('memoryInstruction') or '', AUTH_PERSONALIZATION_MEMORY_MAX_INSTRUCTION_CHARS),
        'responseStylePreset': _auth_personalization_choice(src.get('responseStylePreset') or src.get('stylePreset') or '', {'professional', 'friendly', 'direct', 'practical'}),
        'structurePreference': _auth_personalization_choice(src.get('structurePreference') or src.get('titleListPreference') or '', {'more', 'less'}),
        'emojiPreference': _auth_personalization_choice(src.get('emojiPreference') or '', {'more', 'less'}),
        'memoryItems': [],
        'hardRules': [],
        'softMemoryItems': [],
    }
    seen = set()
    now_ms = _auth_personalization_now_ms()
    raw_items = src.get('memoryItems') if isinstance(src.get('memoryItems'), list) else []
    for raw in raw_items:
        item = _auth_personalization_normalize_item(raw, idx=len(out['memoryItems']), now_ms=now_ms)
        if not item:
            continue
        dedup_key = str(item.get('text') or '').strip().lower()
        if not dedup_key or dedup_key in seen:
            continue
        seen.add(dedup_key)
        out['memoryItems'].append(item)
        if len(out['memoryItems']) >= AUTH_PERSONALIZATION_MEMORY_MAX_ITEMS:
            break
    hard_items, soft_items = _auth_personalization_split_items(out.get('memoryItems') or [])
    out['hardRules'] = hard_items
    out['softMemoryItems'] = soft_items
    return out




def _auth_personalization_memory_items_snapshot(state_payload) -> list[dict]:
    state = _auth_personalization_normalize_state(state_payload)
    rows: list[dict] = []
    for raw in (state.get('memoryItems') or []):
        if not isinstance(raw, dict):
            continue
        item = _auth_personalization_normalize_item(raw, idx=len(rows), now_ms=_auth_personalization_now_ms())
        if not item:
            continue
        rows.append({
            'id': str(item.get('id') or '').strip(),
            'text': _auth_personalization_trim_text(item.get('text') or '', AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS),
            'ruleType': str(item.get('ruleType') or 'soft').strip() or 'soft',
            'createdAt': int(item.get('createdAt') or 0),
            'updatedAt': int(item.get('updatedAt') or 0),
        })
        if len(rows) >= AUTH_PERSONALIZATION_MEMORY_MAX_ITEMS:
            break
    return rows


def _auth_personalization_memory_items_signature(state_payload) -> str:
    try:
        rows = [
            {
                'id': str(x.get('id') or ''),
                'text': str(x.get('text') or ''),
                'ruleType': str(x.get('ruleType') or 'soft'),
            }
            for x in _auth_personalization_memory_items_snapshot(state_payload)
        ]
        return json.dumps(rows, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(state_payload or '')


def _auth_personalization_memory_history_max_versions() -> int:
    try:
        return max(1, min(int(app_getenv('MEMORY_HISTORY_MAX_VERSIONS', str(AUTH_PERSONALIZATION_MEMORY_HISTORY_MAX_VERSIONS)) or AUTH_PERSONALIZATION_MEMORY_HISTORY_MAX_VERSIONS), 200))
    except Exception:
        return int(AUTH_PERSONALIZATION_MEMORY_HISTORY_MAX_VERSIONS or 20)


def _auth_personalization_memory_history_action(before_state, after_state, explicit: str = '') -> str:
    raw = str(explicit or '').strip().lower()
    if raw in {'add', 'update', 'delete', 'clear', 'restore', 'import', 'set'}:
        return raw
    before = _auth_personalization_memory_items_snapshot(before_state)
    after = _auth_personalization_memory_items_snapshot(after_state)
    if before and not after:
        return 'clear' if len(before) > 1 else 'delete'
    if after and not before:
        return 'add'
    if len(after) > len(before):
        return 'add'
    if len(after) < len(before):
        return 'delete'
    return 'update'


def _auth_personalization_memory_history_entry_public(row: dict | None = None) -> dict:
    item = dict(row or {}) if isinstance(row, dict) else {}
    history_id = str(item.get('id') or item.get('history_id') or '').strip()
    try:
        created_at = float(item.get('created_at') or item.get('createdAt') or 0.0)
    except Exception:
        created_at = 0.0
    try:
        created_ts = int(item.get('created_ts') or item.get('createdTs') or int(created_at * 1000) or 0)
    except Exception:
        created_ts = int(created_at * 1000) if created_at > 0 else 0
    snapshot_state = {'memoryItems': item.get('memoryItems') if isinstance(item.get('memoryItems'), list) else (item.get('snapshot') if isinstance(item.get('snapshot'), list) else [])}
    memory_items = _auth_personalization_memory_items_snapshot(snapshot_state)
    action = str(item.get('action') or '').strip().lower() or 'update'
    after_count = len(memory_items)
    try:
        before_count = max(0, int(item.get('before_count') if item.get('before_count') is not None else after_count))
    except Exception:
        before_count = after_count
    try:
        change_count = max(0, int(item.get('change_count') if item.get('change_count') is not None else abs(after_count - before_count)))
    except Exception:
        change_count = abs(after_count - before_count)
    return {
        'id': history_id,
        'history_id': history_id,
        'created_at': created_at,
        'created_ts': created_ts,
        'created_at_text': _fmt_ts(created_at) if created_at else '',
        'action': action,
        'actor': str(item.get('actor') or '').strip() or 'user',
        'before_count': before_count,
        'after_count': after_count,
        'change_count': change_count,
        'count': after_count,
        'memoryItems': memory_items,
    }


def _auth_personalization_memory_history_normalize(history_payload) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for idx, raw in enumerate(history_payload if isinstance(history_payload, list) else []):
        if not isinstance(raw, dict):
            continue
        item = _auth_personalization_memory_history_entry_public(raw)
        if not item.get('memoryItems') and not str(item.get('id') or '').strip():
            continue
        history_id = str(item.get('id') or '').strip()
        if not history_id:
            seed = json.dumps(item.get('memoryItems') or [], ensure_ascii=False, sort_keys=True) + '|' + str(item.get('created_ts') or idx)
            try:
                history_id = 'mh_' + hashlib.sha1(seed.encode('utf-8', errors='ignore')).hexdigest()[:18]
            except Exception:
                history_id = f'mh_{idx}_{uuid.uuid4().hex[:8]}'
            item['id'] = history_id
            item['history_id'] = history_id
        if history_id in seen:
            continue
        seen.add(history_id)
        rows.append(item)
    rows.sort(key=lambda x: (float(x.get('created_at') or 0.0), int(x.get('created_ts') or 0)), reverse=True)
    return rows[:_auth_personalization_memory_history_max_versions()]


def _auth_personalization_memory_history_append(history_payload, before_state, after_state, *, action: str = '', actor: str = 'user', reason: str = '') -> list[dict]:
    history = _auth_personalization_memory_history_normalize(history_payload)
    if _auth_personalization_memory_items_signature(before_state) == _auth_personalization_memory_items_signature(after_state):
        return history
    now_ts = _utc_ts()
    now_ms = _auth_personalization_now_ms()
    resolved_action = _auth_personalization_memory_history_action(before_state, after_state, action)
    before_snapshot = _auth_personalization_memory_items_snapshot(before_state)
    snapshot = _auth_personalization_memory_items_snapshot(after_state)
    before_count = len(before_snapshot)
    after_count = len(snapshot)
    entry = {
        'id': 'mh_' + uuid.uuid4().hex[:18],
        'created_at': now_ts,
        'created_ts': now_ms,
        'action': resolved_action,
        'actor': str(actor or '').strip() or 'user',
        'reason': _auth_personalization_trim_text(reason or '', 240),
        'before_count': before_count,
        'after_count': after_count,
        'change_count': abs(after_count - before_count),
        'count': after_count,
        'memoryItems': snapshot,
    }
    return _auth_personalization_memory_history_normalize([entry, *history])


def _auth_personalization_memory_history_for_email(email: str) -> list[dict]:
    normalized = _normalize_login_email(email)
    if not normalized:
        return []
    rec = _auth_personalization_memory_get(normalized) or {}
    return _auth_personalization_memory_history_normalize((rec or {}).get('memory_history') or (rec or {}).get('memoryHistory') or [])


def _auth_personalization_memory_history_delete(email: str, history_id: str) -> dict:
    normalized = _normalize_login_email(email)
    target = str(history_id or '').strip()
    if not normalized or not target:
        raise ValueError('history_id 不能为空')
    deleted = False
    with _AUTH_PERSONALIZATION_MEMORY_LOCK:
        accounts = _AUTH_PERSONALIZATION_MEMORY_STATE.setdefault('accounts', {})
        rec = dict(accounts.get(normalized) or {})
        if not rec:
            raise ValueError('memory_not_found')
        history = _auth_personalization_memory_history_normalize(rec.get('memory_history') or [])
        next_history = [x for x in history if str(x.get('id') or '') != target]
        deleted = len(next_history) != len(history)
        if not deleted:
            raise ValueError('history_version_not_found')
        rec['memory_history'] = next_history
        accounts[normalized] = rec
        _AUTH_PERSONALIZATION_MEMORY_STATE['updated_at'] = _utc_ts()
    _auth_personalization_memory_save()
    return {'ok': True, 'deleted': deleted, 'history': _auth_personalization_memory_history_for_email(normalized)}


def _auth_personalization_memory_history_restore(email: str, history_id: str) -> dict:
    normalized = _normalize_login_email(email)
    target = str(history_id or '').strip()
    if not normalized or not target:
        raise ValueError('history_id 不能为空')
    restored = False
    out_rec: dict | None = None
    with _AUTH_PERSONALIZATION_MEMORY_LOCK:
        accounts = _AUTH_PERSONALIZATION_MEMORY_STATE.setdefault('accounts', {})
        rec = dict(accounts.get(normalized) or {})
        if not rec:
            raise ValueError('memory_not_found')
        history = _auth_personalization_memory_history_normalize(rec.get('memory_history') or [])
        target_row = None
        for row in history:
            if str(row.get('id') or '') == target:
                target_row = row
                break
        if not target_row:
            raise ValueError('history_version_not_found')
        before_state = _auth_personalization_normalize_state(rec.get('state') or {})
        next_state = dict(before_state)
        next_state['memoryItems'] = [dict(x) for x in (target_row.get('memoryItems') or []) if isinstance(x, dict)]
        next_state = _auth_personalization_normalize_state(next_state)
        restored = _auth_personalization_memory_items_signature(before_state) != _auth_personalization_memory_items_signature(next_state)
        if restored:
            history = _auth_personalization_memory_history_append(history, before_state, next_state, action='restore', actor='user', reason=target)
            now_ts = _utc_ts()
            rec = {
                'email': normalized,
                'state': next_state,
                'memory_history': history,
                'updated_at': now_ts,
            }
            accounts[normalized] = rec
            _AUTH_PERSONALIZATION_MEMORY_STATE['updated_at'] = now_ts
        out_rec = dict(rec)
    if restored:
        _auth_personalization_memory_save()
    return {
        'ok': True,
        'restored': restored,
        'email': normalized,
        'state': _auth_personalization_normalize_state((out_rec or {}).get('state') or {}),
        'updated_at': _fmt_ts((out_rec or {}).get('updated_at') or 0.0),
        'updated_ts': float((out_rec or {}).get('updated_at') or 0.0),
        'history': _auth_personalization_memory_history_for_email(normalized),
    }

def _auth_personalization_memory_load() -> None:
    state = {'accounts': {}, 'updated_at': _utc_ts()}
    changed = False
    try:
        if os.path.exists(AUTH_PERSONALIZATION_MEMORY_FILE):
            with open(AUTH_PERSONALIZATION_MEMORY_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f) or {}
            if isinstance(loaded, dict):
                accounts = loaded.get('accounts') or {}
                if isinstance(accounts, dict):
                    clean_accounts = {}
                    for email, rec in accounts.items():
                        normalized_email = _normalize_login_email(email or (rec or {}).get('email') or '')
                        if not normalized_email:
                            changed = True
                            continue
                        raw_state = rec.get('state') if isinstance(rec, dict) else {}
                        normalized_state = _auth_personalization_normalize_state(raw_state)
                        try:
                            updated_at = float((rec or {}).get('updated_at') or _utc_ts())
                        except Exception:
                            updated_at = _utc_ts()
                        raw_history = (rec or {}).get('memory_history') or (rec or {}).get('memoryHistory') or []
                        normalized_history = _auth_personalization_memory_history_normalize(raw_history)
                        clean_accounts[normalized_email] = {
                            'email': normalized_email,
                            'state': normalized_state,
                            'memory_history': normalized_history,
                            'updated_at': updated_at,
                        }
                        if not isinstance(rec, dict) or raw_state != normalized_state or raw_history != normalized_history:
                            changed = True
                else:
                    clean_accounts = {}
                    changed = True
                state['accounts'] = clean_accounts
                try:
                    state['updated_at'] = float(loaded.get('updated_at') or _utc_ts())
                except Exception:
                    state['updated_at'] = _utc_ts()
    except Exception:
        app_logger.exception('[auth_personalization] load_failed')
    with _AUTH_PERSONALIZATION_MEMORY_LOCK:
        _AUTH_PERSONALIZATION_MEMORY_STATE.clear()
        _AUTH_PERSONALIZATION_MEMORY_STATE.update(state)
    if changed:
        try:
            _auth_personalization_memory_save()
        except Exception:
            app_logger.exception('[auth_personalization] normalize_save_failed')


def _auth_personalization_memory_save() -> None:
    with _AUTH_PERSONALIZATION_MEMORY_LOCK:
        payload = {
            'accounts': _AUTH_PERSONALIZATION_MEMORY_STATE.get('accounts') or {},
            'updated_at': _utc_ts(),
        }
        _AUTH_PERSONALIZATION_MEMORY_STATE['updated_at'] = payload['updated_at']
    tmp = AUTH_PERSONALIZATION_MEMORY_FILE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, AUTH_PERSONALIZATION_MEMORY_FILE)
    except Exception:
        app_logger.exception('[auth_personalization] save_failed')
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _auth_personalization_memory_get(email: str) -> dict | None:
    normalized = _normalize_login_email(email)
    if not normalized:
        return None
    with _AUTH_PERSONALIZATION_MEMORY_LOCK:
        rec = (_AUTH_PERSONALIZATION_MEMORY_STATE.get('accounts') or {}).get(normalized)
        return dict(rec or {}) if isinstance(rec, dict) else None


def _auth_personalization_memory_delete_account(email: str) -> bool:
    normalized = _normalize_login_email(email)
    if not normalized:
        return False
    removed = False
    now_ts = _utc_ts()
    with _AUTH_PERSONALIZATION_MEMORY_LOCK:
        accounts = _AUTH_PERSONALIZATION_MEMORY_STATE.setdefault('accounts', {})
        if normalized in accounts:
            accounts.pop(normalized, None)
            _AUTH_PERSONALIZATION_MEMORY_STATE['updated_at'] = now_ts
            removed = True
    if removed:
        _auth_personalization_memory_save()
    return removed


def _auth_personalization_memory_set(email: str, state_payload, *, record_history: bool = True, history_action: str = '', history_actor: str = 'user', history_reason: str = '') -> dict:
    normalized = _normalize_login_email(email)
    if not normalized:
        raise ValueError('登录账号无效')
    clean_state = _auth_personalization_normalize_state(state_payload)
    now_ts = _utc_ts()
    with _AUTH_PERSONALIZATION_MEMORY_LOCK:
        accounts = _AUTH_PERSONALIZATION_MEMORY_STATE.setdefault('accounts', {})
        previous = dict(accounts.get(normalized) or {}) if isinstance(accounts.get(normalized), dict) else {}
        previous_state = _auth_personalization_normalize_state(previous.get('state') or {})
        history = _auth_personalization_memory_history_normalize(previous.get('memory_history') or previous.get('memoryHistory') or [])
        if record_history:
            history = _auth_personalization_memory_history_append(
                history,
                previous_state,
                clean_state,
                action=history_action,
                actor=history_actor,
                reason=history_reason,
            )
        accounts[normalized] = {
            'email': normalized,
            'state': clean_state,
            'memory_history': history,
            'updated_at': now_ts,
        }
        _AUTH_PERSONALIZATION_MEMORY_STATE['updated_at'] = now_ts
    _auth_personalization_memory_save()
    return _auth_personalization_memory_get(normalized) or {
        'email': normalized,
        'state': clean_state,
        'memory_history': [],
        'updated_at': now_ts,
    }


def _auth_personalization_record_from_store(email: str, store_payload=None, updated_at: float | None = None) -> dict | None:
    normalized = _normalize_login_email(email)
    if not normalized:
        return None
    store_obj = store_payload if isinstance(store_payload, dict) else None
    if store_obj is None:
        chat_rec = _auth_chat_store_get(normalized) or {}
        store_obj = chat_rec.get('store') if isinstance(chat_rec.get('store'), dict) else None
        if updated_at is None:
            try:
                updated_at = float(chat_rec.get('updated_at') or 0.0)
            except Exception:
                updated_at = 0.0
    if not isinstance(store_obj, dict) or 'personalization' not in store_obj:
        return None
    try:
        ts = float(updated_at or 0.0)
    except Exception:
        ts = 0.0
    return {
        'email': normalized,
        'state': _auth_personalization_normalize_state(store_obj.get('personalization') or {}),
        'updated_at': ts,
    }


def _auth_personalization_state_has_content(state_payload) -> bool:
    state = _auth_personalization_normalize_state(state_payload)
    return bool(
        state.get('memoryEnabled')
        or state.get('memoryInstruction')
        or state.get('memoryItems')
        or state.get('customInstruction')
        or state.get('profileNickname')
        or state.get('profileOccupation')
        or state.get('profileDetails')
        or state.get('customAboutUser')
        or state.get('customResponseStyle')
    )


def _auth_personalization_sync_from_store(email: str, store_payload=None, updated_at: float | None = None) -> dict | None:
    rec = _auth_personalization_record_from_store(email, store_payload=store_payload, updated_at=updated_at)
    if rec is None:
        return None
    normalized = _normalize_login_email(email)
    if not normalized:
        return None
    existing = _auth_personalization_memory_get(normalized) or {}
    try:
        existing_updated_at = float((existing or {}).get('updated_at') or 0.0)
    except Exception:
        existing_updated_at = 0.0
    store_state = _auth_personalization_normalize_state(rec.get('state') or {})
    if existing_updated_at > 0:
        return existing
    if not _auth_personalization_state_has_content(store_state):
        return existing or None
    return _auth_personalization_memory_set(email, store_state, record_history=False)


def _auth_personalization_get_effective_record(email: str) -> dict | None:
    normalized = _normalize_login_email(email)
    if not normalized:
        return None
    memory_rec = _auth_personalization_memory_get(normalized) or {}
    try:
        memory_updated_at = float((memory_rec or {}).get('updated_at') or 0.0)
    except Exception:
        memory_updated_at = 0.0
    if memory_updated_at > 0:
        return memory_rec

    store_rec = _auth_personalization_record_from_store(normalized)
    if store_rec is None:
        return memory_rec or None

    store_state = _auth_personalization_normalize_state((store_rec or {}).get('state') or {})
    if _auth_personalization_state_has_content(store_state):
        try:
            return _auth_personalization_memory_set(normalized, store_state, record_history=False)
        except Exception:
            app_logger.exception('[auth_personalization] sync_from_store_failed email=%s', normalized)
            try:
                store_updated_at = float((store_rec or {}).get('updated_at') or 0.0)
            except Exception:
                store_updated_at = 0.0
            return {
                'email': normalized,
                'state': store_state,
                'updated_at': store_updated_at,
            }
    return memory_rec or store_rec


def _auth_personalization_shadow_to_chat_store(email: str, state_payload) -> bool:
    normalized = _normalize_login_email(email)
    if not normalized:
        return False
    chat_rec = _auth_chat_store_get(normalized) or {}
    store_obj = dict(chat_rec.get('store') or {}) if isinstance(chat_rec.get('store'), dict) else {}
    if not isinstance(store_obj.get('sessions'), dict) or not str(store_obj.get('activeId') or '').strip():
        return False
    next_state = _auth_personalization_normalize_state(state_payload)
    current_state = _auth_personalization_normalize_state(store_obj.get('personalization') or {})
    try:
        current_sig = json.dumps(current_state, ensure_ascii=False, sort_keys=True)
        next_sig = json.dumps(next_state, ensure_ascii=False, sort_keys=True)
    except Exception:
        current_sig = str(current_state)
        next_sig = str(next_state)
    if current_sig == next_sig:
        return False
    store_obj['personalization'] = next_state
    try:
        _auth_chat_store_set(normalized, store_obj)
        return True
    except Exception:
        app_logger.exception('[auth_personalization] shadow_to_chat_store_failed email=%s', normalized)
        return False


def _auth_personalization_memory_state_signature(state_payload) -> str:
    try:
        return json.dumps(_auth_personalization_normalize_state(state_payload), ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(state_payload or '')


def _auth_personalization_memory_recent_lines(state_payload, *, limit: int = 14, text_chars: int = 180) -> str:
    state = _auth_personalization_normalize_state(state_payload)
    rows = []
    for item in (state.get('memoryItems') or [])[:max(1, int(limit or 14))]:
        if not isinstance(item, dict):
            continue
        mid = str(item.get('id') or '').strip()
        text = _auth_personalization_trim_text(item.get('text') or '', max(40, int(text_chars or 180)))
        if mid and text:
            rows.append(f'[{mid}] {text}')
    return '\n'.join(rows)


def _auth_personalization_parse_json_object(raw: str) -> dict:
    text = str(raw or '').strip()
    if not text:
        return {}
    parser = globals().get('_safe_parse_json')
    if callable(parser):
        try:
            obj = parser(text)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    try:
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            obj = json.loads(text[start:end + 1])
            return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    return {}


def _auth_personalization_memory_norm_for_match(value: str = '') -> str:
    try:
        raw = str(value or '').strip().lower()
        raw = re.sub(r'\s+', ' ', raw)
        return raw
    except Exception:
        return str(value or '').strip().lower()


def _auth_personalization_int_arg(value, default: int = 0) -> int:
    try:
        if value is None or value == '':
            return int(default)
        return int(float(str(value).strip()))
    except Exception:
        return int(default)


def _auth_personalization_bool_arg(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    raw = str(value or '').strip().lower()
    return raw in {'1', 'true', 'yes', 'on', 'all', '全部', '所有', '是'}


def _auth_personalization_memory_query_score(text: str = '', query: str = '') -> float:
    body = _auth_personalization_memory_norm_for_match(text)
    q = _auth_personalization_memory_norm_for_match(query)
    if not body or not q:
        return 0.0
    if body == q:
        return 1000.0
    if q in body:
        return 760.0 + min(120.0, len(q) * 2.0)
    if body in q:
        return 620.0 + min(100.0, len(body) * 1.5)

    tokens = [x for x in re.split(r'[^0-9a-zA-Z\u4e00-\u9fff]+', q) if x]
    token_score = 0.0
    token_weight = 0.0
    for token in tokens:
        weight = max(1.0, min(6.0, len(token)))
        token_weight += weight
        if token in body:
            token_score += weight
    token_ratio = (token_score / token_weight) if token_weight > 0 else 0.0

    q_units = [ch for ch in q if ch.isalnum() or ('\u4e00' <= ch <= '\u9fff')]
    b_units = set(ch for ch in body if ch.isalnum() or ('\u4e00' <= ch <= '\u9fff'))
    if not q_units or not b_units:
        return token_ratio * 260.0
    q_unique = []
    seen = set()
    for ch in q_units:
        if ch in seen:
            continue
        seen.add(ch)
        q_unique.append(ch)
    char_hits = sum(1 for ch in q_unique if ch in b_units)
    char_ratio = char_hits / max(1, len(q_unique))
    return max(token_ratio * 420.0, char_ratio * 260.0)


def _auth_personalization_memory_delete_candidates(items: list[dict], raw: dict | None = None) -> list[dict]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    if not items:
        return []
    mid = str(row.get('id') or row.get('memory_id') or row.get('memoryId') or '').strip()
    if mid:
        return [x for x in items if str(x.get('id') or '') == mid]

    target_index = _auth_personalization_int_arg(
        row.get('target_index') or row.get('targetIndex') or row.get('index') or row.get('memory_index') or row.get('memoryIndex'),
        0,
    )
    if target_index > 0:
        pos = target_index - 1
        if 0 <= pos < len(items):
            return [items[pos]]
        return []

    if _auth_personalization_bool_arg(row.get('latest') or row.get('most_recent') or row.get('recent')):
        return [items[0]]

    text = _auth_personalization_trim_text(row.get('text') or row.get('memory') or '', AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS)
    if text:
        tkey = _auth_personalization_memory_norm_for_match(text)
        exact = [x for x in items if _auth_personalization_memory_norm_for_match(x.get('text') or '') == tkey]
        if exact:
            return exact
        contained = [x for x in items if tkey and tkey in _auth_personalization_memory_norm_for_match(x.get('text') or '')]
        if contained:
            return contained[:1]

    query = _auth_personalization_trim_text(row.get('query') or row.get('q') or row.get('keyword') or row.get('description') or '', AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS)
    if not query:
        return []
    ranked = []
    for idx, item in enumerate(items):
        score = _auth_personalization_memory_query_score(item.get('text') or '', query)
        if score > 0:
            ranked.append((score, -int(item.get('updatedAt') or 0), idx, item))
    ranked.sort(key=lambda x: (-x[0], x[1], x[2]))
    if not ranked:
        return []
    best_score = float(ranked[0][0] or 0.0)
    try:
        threshold = max(40.0, min(float(app_getenv('MEMORY_DELETE_QUERY_SCORE_MIN', '120') or 120), 500.0))
    except Exception:
        threshold = 120.0
    if best_score < threshold:
        return []
    delete_all = _auth_personalization_bool_arg(row.get('delete_all') or row.get('deleteAll') or row.get('all'))
    max_delete = _auth_personalization_int_arg(row.get('max_delete') or row.get('maxDelete') or row.get('limit'), 0)
    if delete_all:
        limit = max(1, min(max_delete or len(items), len(items)))
        return [item for score, _updated, _idx, item in ranked if score >= threshold][:limit]
    return [ranked[0][3]]


def _auth_personalization_apply_memory_ops(state_payload, ops_payload) -> tuple[dict, list[dict]]:
    state = _auth_personalization_normalize_state(state_payload)
    items = [dict(x) for x in (state.get('memoryItems') or []) if isinstance(x, dict)]
    by_id = {str(x.get('id') or ''): x for x in items if str(x.get('id') or '')}
    applied: list[dict] = []
    now_ms = _auth_personalization_now_ms()

    raw_ops = ops_payload if isinstance(ops_payload, list) else []
    for raw in raw_ops[:6]:
        if not isinstance(raw, dict):
            continue
        op = str(raw.get('op') or raw.get('action') or '').strip().lower()
        if op in {'noop', 'none', 'skip'}:
            continue
        mid = str(raw.get('id') or raw.get('memory_id') or raw.get('memoryId') or '').strip()
        text = _auth_personalization_trim_text(raw.get('text') or raw.get('memory') or '', AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS)
        rule_type = _auth_personalization_normalize_rule_type(raw.get('ruleType') or raw.get('type') or raw.get('category') or '') or 'soft'
        if op in {'delete', 'remove', 'forget'}:
            candidates = _auth_personalization_memory_delete_candidates(items, raw)
            if not candidates:
                applied.append({'op': 'no_match', 'reason': 'no_matching_memory'})
                continue
            delete_ids = {str(x.get('id') or '').strip() for x in candidates if str(x.get('id') or '').strip()}
            deleted_rows = [dict(x) for x in items if str(x.get('id') or '').strip() in delete_ids]
            if not deleted_rows:
                applied.append({'op': 'no_match', 'reason': 'no_matching_memory'})
                continue
            items = [x for x in items if str(x.get('id') or '').strip() not in delete_ids]
            by_id = {str(x.get('id') or ''): x for x in items if str(x.get('id') or '')}
            for deleted in deleted_rows:
                applied.append({
                    'op': 'delete',
                    'id': str(deleted.get('id') or '').strip(),
                    'text': _auth_personalization_trim_text(deleted.get('text') or '', AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS),
                    'ruleType': str(deleted.get('ruleType') or '').strip() or 'soft',
                })
            continue
        if op not in {'add', 'update', 'upsert', 'set'} or not text:
            continue
        existing = by_id.get(mid) if mid else None
        if existing:
            existing['text'] = text
            existing['ruleType'] = rule_type
            existing['updatedAt'] = now_ms
            applied.append({'op': 'update', 'id': str(existing.get('id') or ''), 'text': text, 'ruleType': rule_type})
            continue
        duplicate = None
        key = text.strip().lower()
        for item in items:
            if str(item.get('text') or '').strip().lower() == key:
                duplicate = item
                break
        if duplicate:
            duplicate['updatedAt'] = now_ms
            applied.append({'op': 'touch', 'id': str(duplicate.get('id') or ''), 'text': str(duplicate.get('text') or ''), 'ruleType': str(duplicate.get('ruleType') or '') or rule_type})
            continue
        item = _auth_personalization_normalize_item({'text': text, 'ruleType': rule_type, 'createdAt': now_ms, 'updatedAt': now_ms}, idx=len(items), now_ms=now_ms)
        if item:
            items.insert(0, item)
            by_id[str(item.get('id') or '')] = item
            applied.append({'op': 'add', 'id': str(item.get('id') or ''), 'text': str(item.get('text') or ''), 'ruleType': str(item.get('ruleType') or '') or rule_type})
    state['memoryItems'] = items
    state = _auth_personalization_normalize_state(state)
    applied = [x for x in applied if str((x or {}).get('op') or '').strip() != 'no_match'] or applied
    return state, applied

def _auth_personalization_memory_tool_enabled(email: str = '') -> bool:
    normalized = _normalize_login_email(email or '')
    if not normalized:
        try:
            account_email_getter = globals().get('_account_context_current_email')
            if callable(account_email_getter):
                normalized = _normalize_login_email(account_email_getter() or '')
        except Exception:
            normalized = ''
    if not normalized:
        try:
            normalized = _normalize_login_email(_current_login_email())
        except Exception:
            normalized = ''
    if not normalized:
        return False
    try:
        rec = _auth_personalization_get_effective_record(normalized) or {}
        state = _auth_personalization_normalize_state((rec or {}).get('state') or {})
        return bool(state.get('memoryEnabled')) and state.get('memoryAutoManageEnabled') is not False
    except Exception:
        return False


def _auth_personalization_public_memory_event(action: str = '', item: dict | None = None) -> dict:
    row = dict(item or {}) if isinstance(item, dict) else {}
    text = _auth_personalization_trim_text(row.get('text') or '', AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS)
    rid = str(row.get('id') or '').strip()
    op = str(action or '').strip().lower()
    if op == 'delete':
        title = '已删除记忆'
    elif op in {'update', 'touch'}:
        title = '已更新记忆'
    else:
        title = '已保存到记忆'
    return {
        '_kind': 'memory_event',
        'action': op or 'add',
        'title': title,
        'text': text,
        'memory_id': rid,
        'id': rid,
    }


def _auth_personalization_apply_memory_tool(args: dict | None = None, *, email: str = '', session_id: str = '') -> dict:
    raw_args = dict(args or {}) if isinstance(args, dict) else {}
    normalized = _normalize_login_email(email or '')
    if not normalized:
        try:
            account_email_getter = globals().get('_account_context_current_email')
            if callable(account_email_getter):
                normalized = _normalize_login_email(account_email_getter() or '')
        except Exception:
            normalized = ''
    if not normalized:
        try:
            normalized = _normalize_login_email(_current_login_email())
        except Exception:
            normalized = ''
    if not normalized:
        return {'ok': False, 'skipped': True, '_kind': 'memory_event', 'reason': 'no_email'}

    rec = _auth_personalization_get_effective_record(normalized) or {}
    state = _auth_personalization_normalize_state((rec or {}).get('state') or {})
    if not bool(state.get('memoryEnabled')):
        return {'ok': True, 'skipped': True, '_kind': 'memory_event', 'reason': 'memory_disabled'}
    if state.get('memoryAutoManageEnabled') is False:
        return {'ok': True, 'skipped': True, '_kind': 'memory_event', 'reason': 'auto_manage_disabled'}

    raw_ops = raw_args.get('ops') if isinstance(raw_args.get('ops'), list) else None
    if raw_ops is None:
        raw_ops = [raw_args]
    cleaned_ops: list[dict] = []
    for op_raw in raw_ops[:3]:
        if not isinstance(op_raw, dict):
            continue
        op = str(op_raw.get('op') or op_raw.get('action') or '').strip().lower() or 'add'
        if op in {'none', 'skip'}:
            op = 'noop'
        text = _auth_personalization_trim_text(op_raw.get('text') or op_raw.get('memory') or '', AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS)
        mid = str(op_raw.get('id') or op_raw.get('memory_id') or op_raw.get('memoryId') or '').strip()
        rule_type = _auth_personalization_normalize_rule_type(op_raw.get('ruleType') or op_raw.get('type') or op_raw.get('category') or '') or 'soft'
        if op in {'noop'}:
            cleaned_ops.append({'op': 'noop'})
        elif op in {'delete', 'remove', 'forget'}:
            cleaned_ops.append({
                'op': 'delete',
                'id': mid,
                'text': text,
                'query': _auth_personalization_trim_text(op_raw.get('query') or op_raw.get('q') or op_raw.get('keyword') or op_raw.get('description') or '', AUTH_PERSONALIZATION_MEMORY_MAX_TEXT_CHARS),
                'target_index': _auth_personalization_int_arg(op_raw.get('target_index') or op_raw.get('targetIndex') or op_raw.get('index') or op_raw.get('memory_index') or op_raw.get('memoryIndex'), 0),
                'latest': _auth_personalization_bool_arg(op_raw.get('latest') or op_raw.get('most_recent') or op_raw.get('recent')),
                'delete_all': _auth_personalization_bool_arg(op_raw.get('delete_all') or op_raw.get('deleteAll') or op_raw.get('all')),
                'max_delete': _auth_personalization_int_arg(op_raw.get('max_delete') or op_raw.get('maxDelete') or op_raw.get('limit'), 0),
                'ruleType': rule_type,
            })
        elif text:
            cleaned_ops.append({'op': 'update' if mid else 'add', 'id': mid, 'text': text, 'ruleType': rule_type})
    if not cleaned_ops:
        return {'ok': True, 'skipped': True, '_kind': 'memory_event', 'reason': 'empty_ops'}

    before_sig = _auth_personalization_memory_state_signature(state)
    next_state, applied = _auth_personalization_apply_memory_ops(state, cleaned_ops)
    after_sig = _auth_personalization_memory_state_signature(next_state)
    applied_effective = [dict(x or {}) for x in (applied or []) if str((x or {}).get('op') or '').strip() not in {'no_match', 'noop'}]
    if not applied_effective or after_sig == before_sig:
        has_delete = any(str((x or {}).get('op') or '').strip().lower() == 'delete' for x in cleaned_ops)
        reason = 'no_matching_memory' if has_delete else 'noop'
        return {'ok': False if has_delete else True, 'skipped': True, '_kind': 'memory_event', 'reason': reason}

    first_action = str((applied_effective[0] or {}).get('op') or '').strip().lower() if applied_effective else ''
    if first_action == 'touch':
        first_action = 'update'
    saved = _auth_personalization_memory_set(normalized, next_state, history_action=first_action or 'update', history_actor='assistant_tool')
    try:
        _auth_personalization_shadow_to_chat_store(normalized, (saved or {}).get('state') or next_state)
    except Exception:
        pass

    saved_state = _auth_personalization_normalize_state((saved or {}).get('state') or next_state)
    items_by_id = {str(x.get('id') or ''): dict(x) for x in (saved_state.get('memoryItems') or []) if isinstance(x, dict)}
    events = []
    public_applied = []
    for row in applied_effective[:6]:
        aid = str((row or {}).get('id') or '').strip()
        action = str((row or {}).get('op') or '').strip().lower()
        item = items_by_id.get(aid) or {}
        if action == 'delete' and not item:
            item = {'id': aid, 'text': str((row or {}).get('text') or '')}
        ev = _auth_personalization_public_memory_event(action, item)
        events.append(ev)
        public_applied.append({'op': action, 'id': aid, 'text': ev.get('text') or ''})
    if len(events) > 1 and all(str((x or {}).get('action') or '').strip().lower() == 'delete' for x in events):
        event = {
            '_kind': 'memory_event',
            'action': 'delete',
            'title': f'已删除 {len(events)} 条记忆',
            'text': '；'.join([str((x or {}).get('text') or '').strip() for x in events if str((x or {}).get('text') or '').strip()][:3]),
            'memory_id': '',
            'id': '',
            'count': len(events),
        }
    else:
        event = events[0] if events else {'_kind': 'memory_event', 'title': '已更新记忆', 'text': ''}
    return {
        'ok': True,
        'skipped': False,
        '_kind': 'memory_event',
        'applied': public_applied,
        'event': event,
        **event,
    }
def _build_auth_personalization_memory_system_prompt(state_payload) -> str:
    state = _auth_personalization_normalize_state(state_payload)
    items = [dict(item) for item in (state.get('memoryItems') or []) if isinstance(item, dict)]
    hard_items, soft_items = _auth_personalization_split_items(items)
    custom_instruction = _auth_personalization_trim_text(state.get('customInstruction') or '', AUTH_PERSONALIZATION_CUSTOM_INSTRUCTION_MAX_CHARS)
    nickname = _auth_personalization_trim_text(state.get('profileNickname') or '', 120)
    occupation = _auth_personalization_trim_text(state.get('profileOccupation') or '', 180)
    details = _auth_personalization_trim_text(state.get('profileDetails') or '', 700)
    extra = _auth_personalization_trim_text(state.get('memoryInstruction') or '', AUTH_PERSONALIZATION_MEMORY_MAX_INSTRUCTION_CHARS)
    expression_line = _auth_personalization_expression_line(state)
    memory_on = bool(state.get('memoryEnabled'))
    has_profile = bool(nickname or occupation or details)
    has_memory = bool(memory_on and (items or extra))
    if not (custom_instruction or expression_line or has_profile or has_memory):
        return ''
    lines = [
        '【个性化】',
        '- 本轮用户明确要求优先；不要主动提到个性化、记忆或自定义指令。',
    ]
    if expression_line:
        lines.append(expression_line)
    if custom_instruction:
        lines.extend(['', '【自定义指令】', custom_instruction])
    if has_profile:
        lines.extend(['', '【关于你】'])
        if nickname:
            lines.append('昵称：' + nickname)
        if occupation:
            lines.append('职业：' + occupation)
        if details:
            lines.append('详情：' + details)
    if has_memory:
        lines.extend(['', '【保存的记忆】'])
        lines.append('需要修改或删除记忆时，可按这里的序号 target_index 或 memory_id 调用 save_memory。')
        if extra:
            lines.append('说明：' + extra)
        for idx, item in enumerate(items, start=1):
            text = str(item.get('text') or '').strip()
            if not text:
                continue
            mid = str(item.get('id') or '').strip()
            id_part = f' id={mid}' if mid else ''
            lines.append(f'{idx}. [记忆{id_part}] {text}')
    return '\n'.join(lines)

def _personalization_message_kind(content) -> str:
    raw = str(_msg_content_text(content) or '').strip()
    if not raw or not any(marker in raw for marker in ('【个性化】', '【个性化记忆】', '【自定义指令】')):
        return ''
    if raw.startswith('【个性化】') or raw.startswith('【个性化记忆】'):
        return 'dedicated'
    if any(marker in raw for marker in ('【自定义指令】', '【硬约束】', '【软记忆】', '【保存的记忆】', '【用户手动记忆】', '【额外说明】')):
        return 'dedicated'
    return 'generic_marker'


def _find_personalization_memory_indexes(messages: list | None = None, *, dedicated_only: bool = False) -> list[int]:
    indexes: list[int] = []
    for idx, item in enumerate(messages or []):
        if not isinstance(item, dict):
            continue
        if str(item.get('role') or '').strip().lower() != 'system':
            continue
        kind = _personalization_message_kind(item.get('content'))
        if not kind:
            continue
        if dedicated_only and kind != 'dedicated':
            continue
        indexes.append(idx)
    return indexes


def _strip_dedicated_personalization_memory(messages: list | None = None) -> tuple[list, int]:
    base = [dict(item) if isinstance(item, dict) else item for item in (messages or []) if item is not None]
    dedicated_indexes = set(_find_personalization_memory_indexes(base, dedicated_only=True))
    if not dedicated_indexes:
        return base, 0
    out = [item for idx, item in enumerate(base) if idx not in dedicated_indexes]
    return out, len(dedicated_indexes)


def _inject_auth_personalization_memory(messages: list | None = None, *, email: str = '') -> tuple[list, dict]:
    base = [dict(item) if isinstance(item, dict) else item for item in (messages or []) if item is not None]
    normalized_email = _normalize_login_email(email or _current_login_email())
    if not normalized_email:
        return base, {'available': False, 'source': 'none'}
    rec = _auth_personalization_get_effective_record(normalized_email) or {}
    state = _auth_personalization_normalize_state((rec or {}).get('state') or {})
    items = state.get('memoryItems') or []
    hard_items, soft_items = _auth_personalization_split_items(items)
    prompt = _build_auth_personalization_memory_system_prompt(state)
    generic_marker_indexes = _find_personalization_memory_indexes(base, dedicated_only=False)
    base, removed_count = _strip_dedicated_personalization_memory(base)
    if not prompt:
        return base, {
            'available': True,
            'enabled': bool(state.get('memoryEnabled')),
            'count': len(items),
            'hard_count': len(hard_items),
            'soft_count': len(soft_items),
            'generic_marker_count': len(generic_marker_indexes),
            'removed_client_memory_count': removed_count,
            'source': 'backend_empty',
        }
    memory_msg = {'role': 'system', '_kind': 'personalization_memory', 'content': prompt}
    base.insert(0, memory_msg)
    source = 'backend_replaced_client' if removed_count else 'backend_injected'
    return base, {
        'available': True,
        'enabled': bool(state.get('memoryEnabled')),
        'count': len(items),
        'hard_count': len(hard_items),
        'soft_count': len(soft_items),
        'generic_marker_count': len(generic_marker_indexes),
        'removed_client_memory_count': removed_count,
        'source': source,
    }

def _auth_personalization_get_hard_items(email: str = '') -> list[dict]:
    normalized_email = _normalize_login_email(email or _current_login_email())
    if not normalized_email:
        return []
    rec = _auth_personalization_get_effective_record(normalized_email) or {}
    state = _auth_personalization_normalize_state((rec or {}).get('state') or {})
    if not bool(state.get('memoryEnabled')):
        return []
    items = [dict(item) for item in (state.get('memoryItems') or []) if isinstance(item, dict)]
    hard_items, _soft_items = _auth_personalization_split_items(items)
    return hard_items


def _auth_personalization_extract_hard_items_from_messages(messages: list | None = None) -> list[dict]:
    out: list[dict] = []
    seen = set()
    for item in (messages or []):
        if not isinstance(item, dict):
            continue
        if str(item.get('role') or '').strip().lower() != 'system':
            continue
        content = _msg_content_text(item.get('content')) if 'content' in item else ''
        raw = str(content or '')
        if '【个性化记忆】' not in raw or '【硬约束】' not in raw:
            continue
        section = raw.split('【硬约束】', 1)[1]
        if '【软记忆】' in section:
            section = section.split('【软记忆】', 1)[0]
        for line in section.splitlines():
            cleaned = re.sub(r'^\s*\d+[.、]\s*', '', str(line or '').strip())
            if not cleaned:
                continue
            if cleaned.startswith('- ') or cleaned.startswith('【'):
                continue
            dedup_key = cleaned.lower()
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            out.append({'text': cleaned, 'ruleType': 'hard'})
    return out



@app.get('/api3/personalization/memory')
def api3_personalization_memory_get_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    rec = _auth_personalization_get_effective_record(email) or {}
    updated_ts = float(rec.get('updated_at') or 0.0)
    return _json_no_store_response({
        'ok': True,
        'email': email,
        'state': _auth_personalization_normalize_state((rec or {}).get('state') or {}),
        'updated_at': _fmt_ts(updated_ts),
        'updated_ts': updated_ts,
    })


@app.post('/api3/personalization/memory')
def api3_personalization_memory_save_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    try:
        rec = _auth_personalization_memory_set(email, data.get('state'))
        _auth_personalization_shadow_to_chat_store(email, (rec or {}).get('state') or {})
    except ValueError as e:
        return _json_no_store_response({'error': str(e)}, status=400)
    updated_ts = float(rec.get('updated_at') or 0.0)
    return _json_no_store_response({
        'ok': True,
        'email': email,
        'state': _auth_personalization_normalize_state((rec or {}).get('state') or {}),
        'updated_at': _fmt_ts(updated_ts),
        'updated_ts': updated_ts,
    })


@app.get('/api3/personalization/memory/history')
def api3_personalization_memory_history_get_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    try:
        _auth_personalization_get_effective_record(email)
    except Exception:
        pass
    history = _auth_personalization_memory_history_for_email(email)
    return _json_no_store_response({
        'ok': True,
        'email': email,
        'max_versions': _auth_personalization_memory_history_max_versions(),
        'history': history,
        'count': len(history),
    })


@app.post('/api3/personalization/memory/history/delete')
def api3_personalization_memory_history_delete_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    history_id = str(data.get('id') or data.get('history_id') or data.get('version_id') or '').strip()
    try:
        result = _auth_personalization_memory_history_delete(email, history_id)
    except ValueError as e:
        return _json_no_store_response({'ok': False, 'error': str(e) or 'history_delete_failed'}, status=404 if 'not_found' in str(e) else 400)
    return _json_no_store_response({
        **result,
        'email': email,
        'max_versions': _auth_personalization_memory_history_max_versions(),
        'count': len(result.get('history') or []),
    })


@app.post('/api3/personalization/memory/history/restore')
def api3_personalization_memory_history_restore_route():
    email, error_resp = _require_logged_in_email()
    if error_resp is not None:
        return error_resp
    _auth_presence_mark_light(email, path=request.path)
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        data = {}
    history_id = str(data.get('id') or data.get('history_id') or data.get('version_id') or '').strip()
    try:
        result = _auth_personalization_memory_history_restore(email, history_id)
        _auth_personalization_shadow_to_chat_store(email, result.get('state') or {})
    except ValueError as e:
        return _json_no_store_response({'ok': False, 'error': str(e) or 'history_restore_failed'}, status=404 if 'not_found' in str(e) else 400)
    return _json_no_store_response({
        **result,
        'max_versions': _auth_personalization_memory_history_max_versions(),
        'count': len(result.get('history') or []),
    })
