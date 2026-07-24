# prefetch route confidence and primary delivery helpers.

def _prefetch_route_confidence(prefetch_decision: dict | None = None) -> float:
    decision = dict(prefetch_decision or {})
    try:
        value = float(decision.get('route_confidence') or 0.0)
    except Exception:
        value = 0.0
    return max(0.0, min(value, 1.0))


def _prefetch_dynamic_route_floor(prefetch_decision: dict | None = None, route_mode: str = 'direct_answer', answer_strategy: str = '') -> float:
    decision = dict(prefetch_decision or {})
    route_mode = str(route_mode or 'direct_answer').strip().lower() or 'direct_answer'
    answer_strategy = str(answer_strategy or decision.get('answer_strategy') or '').strip().lower()
    need_external_evidence = bool(decision.get('need_external_evidence'))
    current_world_risk = str(decision.get('current_world_risk') or '').strip().lower()
    upgrade_worth = str(decision.get('upgrade_worth') or '').strip().lower()

    floor = 0.55
    if route_mode == 'web_research':
        if need_external_evidence and current_world_risk == 'high' and answer_strategy == 'research_first':
            floor = 0.40
        elif need_external_evidence and current_world_risk in {'medium', 'high'} and answer_strategy in {'research_first', 'quick_then_verify'}:
            floor = 0.45
        elif need_external_evidence or current_world_risk in {'medium', 'high'} or upgrade_worth == 'high':
            floor = 0.50
    elif route_mode in {'location', 'weather', 'visual', 'file'} and answer_strategy == 'tool_first':
        floor = 0.50
    return max(0.35, min(floor, 0.75))


def _prefetch_should_soft_upgrade_to_web_research(prefetch_decision: dict | None = None, route_mode: str = 'direct_answer', answer_strategy: str = '') -> bool:
    decision = dict(prefetch_decision or {})
    route_mode = str(route_mode or 'direct_answer').strip().lower() or 'direct_answer'
    if route_mode != 'direct_answer':
        return False

    answer_strategy = str(answer_strategy or decision.get('answer_strategy') or '').strip().lower()
    need_external_evidence = bool(decision.get('need_external_evidence'))
    current_world_risk = str(decision.get('current_world_risk') or '').strip().lower()
    upgrade_worth = str(decision.get('upgrade_worth') or '').strip().lower()
    route_confidence = _prefetch_route_confidence(decision)

    if answer_strategy == 'research_first' and need_external_evidence and current_world_risk == 'high' and route_confidence >= 0.40:
        return True
    if answer_strategy == 'quick_then_verify' and need_external_evidence and current_world_risk in {'medium', 'high'} and upgrade_worth in {'medium', 'high'} and route_confidence >= 0.48:
        return True
    if need_external_evidence and current_world_risk == 'high' and upgrade_worth == 'high' and route_confidence >= 0.52:
        return True
    return False


def _prefetch_soft_web_research_hit(prefetch_decision: dict | None = None, route_mode: str = 'direct_answer', answer_strategy: str = '') -> bool:
    decision = dict(prefetch_decision or {})
    route_mode = str(route_mode or decision.get('route_mode') or 'direct_answer').strip().lower() or 'direct_answer'
    answer_strategy = str(answer_strategy or decision.get('answer_strategy') or '').strip().lower()
    need_external_evidence = bool(decision.get('need_external_evidence'))
    current_world_risk = str(decision.get('current_world_risk') or '').strip().lower()

    if route_mode == 'web_research':
        return True
    if answer_strategy == 'research_first' and need_external_evidence:
        return True
    if answer_strategy == 'quick_then_verify' and need_external_evidence and current_world_risk in {'medium', 'high'}:
        return True
    return False


def _web_search_results_need_supplement(results: list | None = None, pages: list | None = None) -> bool:
    unique_urls = []
    seen = set()
    for item in (results or []):
        if not isinstance(item, dict):
            continue
        url = str(item.get('url') or '').strip()
        if not url or url in seen:
            continue
        seen.add(url)
        unique_urls.append(url)
    rich_pages = 0
    for page in (pages or []):
        if not isinstance(page, dict):
            continue
        text = str(page.get('text') or '').strip()
        if len(text) >= 160:
            rich_pages += 1
    min_effective_results = max(2, _cfg_int('WEB_SEARCH_MIN_EFFECTIVE_RESULTS', 3))
    if len(unique_urls) < min_effective_results:
        return True
    if len(unique_urls) <= max(3, min_effective_results) and rich_pages <= 0:
        return True
    return False


def _planner_focuses_need_supplement(selected_items: list[dict] | None = None, reserve_items: list[dict] | None = None) -> bool:
    selected = [dict(it) for it in (selected_items or []) if isinstance(it, dict) and str(it.get('text') or '').strip()]
    reserve = [dict(it) for it in (reserve_items or []) if isinstance(it, dict) and str(it.get('text') or '').strip()]
    if not selected or not reserve:
        return False

    selected_focuses = {_planner_focus_key(it.get('focus') or '') for it in selected if _planner_focus_key(it.get('focus') or '')}
    reserve_focuses = {_planner_focus_key(it.get('focus') or '') for it in reserve if _planner_focus_key(it.get('focus') or '')}
    if not reserve_focuses:
        return False
    if not selected_focuses:
        return True
    return bool(reserve_focuses - selected_focuses)


def _planner_focus_plan_keys(focus_plan: list[dict] | None = None) -> list[str]:
    ordered: list[str] = []
    seen = set()
    for item in (focus_plan or []):
        if not isinstance(item, dict):
            continue
        key = _planner_focus_key((item or {}).get('focus') or '')
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _planner_uncovered_focuses(focus_plan: list[dict] | None = None, selected_items: list[dict] | None = None) -> list[str]:
    planned = _planner_focus_plan_keys(focus_plan)
    if not planned:
        return []
    covered = {_planner_focus_key((item or {}).get('focus') or '') for item in (selected_items or []) if isinstance(item, dict)}
    return [focus for focus in planned if focus and focus not in covered]


def _select_query_items_for_supplement(reserve_items: list[dict] | None = None, *, selected_items: list[dict] | None = None, focus_plan: list[dict] | None = None) -> list[dict]:
    reserve = [dict(it) for it in (reserve_items or []) if isinstance(it, dict) and str(it.get('text') or '').strip()]
    if not reserve:
        return []
    selected = [dict(it) for it in (selected_items or []) if isinstance(it, dict)]
    uncovered = _planner_uncovered_focuses(focus_plan, selected)
    used_texts = {str(it.get('text') or '') for it in selected}

    for focus in uncovered:
        focus_candidates = [item for item in reserve if str(item.get('text') or '') not in used_texts and _planner_focus_key(item.get('focus') or '') == focus]
        if not focus_candidates:
            continue
        best = None
        best_score = None
        for item in focus_candidates:
            score = _planner_query_item_selection_score(item, selected_items=selected)
            if best_score is None or score > best_score:
                best_score = score
                best = item
        if best is not None:
            return [best]

    remaining = [item for item in reserve if str(item.get('text') or '') not in used_texts]
    if not remaining:
        return []
    best = None
    best_score = None
    for item in remaining:
        score = _planner_query_item_selection_score(item, selected_items=selected)
        if best_score is None or score > best_score:
            best_score = score
            best = item
    return [best] if best is not None else []


def _merge_web_search_results(primary: list | None = None, extra: list | None = None, limit: int = 12) -> list:
    out = []
    seen = set()
    for item in [*(primary or []), *(extra or [])]:
        if not isinstance(item, dict):
            continue
        url = str(item.get('url') or '').strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
        if len(out) >= max(3, int(limit or 12)):
            break
    return out


def _search_results_for_reasoning_meta(results: list | None = None, limit: int = 24) -> list[dict]:
    out: list[dict] = []
    seen = set()
    max_items = max(1, min(int(limit or 24), 30))
    for item in (results or []):
        if not isinstance(item, dict):
            continue
        url = str(item.get('url') or '').strip()
        if not url:
            continue
        dedup_key = str(_norm_url_for_dedup(url) or url).strip().lower()
        if not dedup_key or dedup_key in seen:
            continue
        seen.add(dedup_key)
        host = str(_host_of(url) or '').strip().lower()
        title = str(item.get('title') or '').strip()
        if not title:
            title = host or url
        out.append({
            'title': title[:200],
            'url': url[:500],
            'host': host[:120],
            'provider': str(item.get('provider') or item.get('source') or '')[:40],
            'query': str(item.get('_q') or '')[:120],
        })
        if len(out) >= max_items:
            break
    return out


def _fetch_web_pages_for_results(results: list | None = None, *, max_pages: int = 0, query_text: str = '') -> list:
    if not results or max_pages <= 0:
        return []
    items = []
    seen = set()
    for r in (results or []):
        if not isinstance(r, dict):
            continue
        url = str(r.get('url') or '').strip()
        if not url or url in seen:
            continue
        seen.add(url)
        items.append({'url': url, 'title': (r or {}).get('title', '')})
        if len(items) >= max_pages:
            break
    pages = _fetch_pages_concurrent_async(items, max_chars=_cfg_int('AUTO_WEB_PAGE_MAX_CHARS', 4500)) if items else []
    focus_query = str(query_text or '').strip()
    for page in pages:
        if not isinstance(page, dict):
            continue
        if page.get('text'):
            page['text'] = _snippet_by_query(page.get('text') or '', focus_query, limit=_cfg_int('AUTO_WEB_PAGE_SNIPPET_CHARS', 1800))
    return pages



def _normalize_prefetch_route_mode(prefetch_decision: dict | None = None) -> str:
    """Soft route hint only.

    上一层预判只保留“倾向”，不再把它当作硬入口，也不再强制绑定 location/
    weather/file/visual 对应动作。真正是否调用工具，交给后面的统一工具规划阶段。
    """
    decision = dict(prefetch_decision or {})
    route_mode = str(decision.get('route_mode') or '').strip().lower()
    route_confidence = _prefetch_route_confidence(decision)

    if route_mode not in {'direct_answer', 'location', 'weather', 'visual', 'file', 'web_research'}:
        route_mode = 'direct_answer'

    answer_strategy = _normalize_prefetch_answer_strategy(decision, route_mode=route_mode)
    if _prefetch_should_soft_upgrade_to_web_research(decision, route_mode=route_mode, answer_strategy=answer_strategy):
        route_mode = 'web_research'

    if route_mode != 'direct_answer' and route_confidence < 0.35:
        return 'direct_answer'
    return route_mode or 'direct_answer'


def _orch_normalize_primary_delivery(prefetch_decision: dict | None = None) -> str:
    decision = dict(prefetch_decision or {})
    raw = str(decision.get('primary_delivery') or decision.get('final_deliverable') or decision.get('delivery_intent') or '').strip().lower()
    aliases = {
        'direct': 'answer', 'direct_answer': 'answer', 'chat': 'answer',
        'web_research': 'web', 'research': 'web',
        'visual': 'image', 'image_generation': 'image', 'text_to_image': 'image',
        'edit_image': 'image_edit', 'image_editing': 'image_edit',
        'generate_file': 'file', 'file_generation': 'file', 'sandbox_files': 'file',
        'edit_file': 'file_edit', 'file_editing': 'file_edit',
        'multi': 'composite', 'multi_step': 'composite', 'multiple': 'composite',
    }
    raw = aliases.get(raw, raw)
    allowed = {'answer', 'web', 'location', 'weather', 'image', 'image_edit', 'file', 'file_edit', 'composite'}
    return raw if raw in allowed else ''


def _orch_apply_primary_delivery_lock(decision: dict | None = None) -> dict:
    """Make executable tool actions follow the chosen turn-level delivery.

    The prefetch model may keep multiple route candidates for reasoning, but
    downstream execution should not treat every candidate as an action. This keeps
    file and image lanes reasonably parallel at the candidate level while giving
    only the primary delivery lane execution authority.
    """
    out = dict(decision or {})
    pd = _orch_normalize_primary_delivery(out)
    if not pd:
        return out
    out['primary_delivery'] = pd
    if pd in {'image', 'image_edit'}:
        out['route_mode'] = 'visual'
        out['file_action'] = 'none'
        visual = out.get('visual_decision') if isinstance(out.get('visual_decision'), dict) else {}
        visual = dict(visual or {})
        visual['intent'] = 'image_mode'
        out['visual_decision'] = visual
        out['answer_strategy'] = 'tool_first'
    elif pd in {'file', 'file_edit'}:
        out['route_mode'] = 'file'
        out['file_action'] = 'sandbox_files'
        out['answer_strategy'] = 'tool_first'
    elif pd == 'web':
        out['route_mode'] = 'web_research'
        out['file_action'] = 'none'
        out['answer_strategy'] = 'research_first'
    elif pd == 'weather':
        out['route_mode'] = 'weather'
        out['file_action'] = 'none'
        out['weather_action'] = 'call_weather'
        out['answer_strategy'] = 'tool_first'
    elif pd == 'location':
        out['route_mode'] = 'location'
        out['file_action'] = 'none'
        out['location_action'] = 'resolve_location'
        out['answer_strategy'] = 'tool_first'
    elif pd == 'answer':
        out['route_mode'] = 'direct_answer'
        out['file_action'] = 'none'
        out['answer_strategy'] = 'fast_direct'
    elif pd == 'composite':
        # Composite is the only state where multiple executable lanes may remain.
        # Keep model-provided actions and let downstream stages execute in order.
        pass
    return out

def _normalize_prefetch_answer_strategy(prefetch_decision: dict | None = None, route_mode: str = 'direct_answer') -> str:
    decision = dict(prefetch_decision or {})
    strategy = str(decision.get('answer_strategy') or '').strip().lower()
    if strategy not in {'fast_direct', 'direct_with_caveat', 'quick_then_verify', 'research_first', 'tool_first'}:
        strategy = ''
    route_mode = str(route_mode or 'direct_answer').strip().lower() or 'direct_answer'
    if not strategy:
        if route_mode == 'web_research':
            return 'research_first'
        if route_mode in {'location', 'weather', 'visual', 'file'}:
            return 'tool_first'
        return 'fast_direct'
    if route_mode == 'direct_answer' and strategy not in {'fast_direct', 'direct_with_caveat', 'quick_then_verify'}:
        return 'fast_direct'
    if route_mode in {'location', 'weather', 'visual', 'file'} and strategy not in {'tool_first', 'research_first'}:
        return 'tool_first'
    if route_mode == 'web_research' and strategy not in {'research_first', 'quick_then_verify'}:
        return 'research_first'
    return strategy
