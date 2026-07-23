# Split from app3_parts/chat/chat_orchestrator_core_part.py.
# Purpose: web planner query cleanup, review, supplement, and enrichment helpers.
# Loaded by chat_orchestrator_core_part.py via _exec_split_file(...), sharing app3.py globals.

def _web_planner_message_file_kind(message: dict | None = None) -> str:
    """Return file/artifact kind carried by a conversation message, if any.

    Search planning must be based on the user's search topic, not on local file
    artifacts that happen to exist in the chat. This helper only inspects
    structured metadata; it does not decide whether to search.
    """
    if not isinstance(message, dict):
        return ''
    kind = str(message.get('_kind') or '').strip().lower()
    if kind:
        return kind
    content = message.get('content')
    if isinstance(content, dict):
        return str(content.get('_kind') or '').strip().lower()
    return ''


def _web_planner_strip_artifact_text(text: str, *, max_len: int = 360) -> str:
    """Remove local file-artifact noise before the web query planner sees history.

    This is context separation, not intent routing: current user text is kept
    intact, while old generated-file/download/file-list traces are removed so
    queries do not become `file app-v13.py index-v17.html ...`.
    """
    raw = str(text or '')
    if not raw.strip():
        return ''
    file_ext_re = re.compile(r'\b[\w.()\-\u4e00-\u9fff]+\.(?:py|html?|md|txt|json|csv|docx?|xlsx?|pdf|zip|7z|rar|tar|gz|yaml|yml|css|js|ts)\b', re.I)
    kept: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        has_file_name = bool(file_ext_re.search(s))
        artifactish = (
            '已生成文件' in s
            or '生成文件' in s
            or '可下载' in s
            or '下载' in s
            or '附件' in s
            or '保存成' in s
            or '输出文件' in s
            or '基准文件' in s
            or '新文件' in s
            or (s.startswith(('-', '•')) and has_file_name)
        )
        if has_file_name and artifactish:
            continue
        kept.append(s)
    cleaned = '\n'.join(kept).strip()
    if not cleaned:
        return ''
    # Drop leftover standalone local artifact names from history. The current
    # user query is not passed through this function, so explicit file requests
    # in the current turn remain intact.
    cleaned = file_ext_re.sub(' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned:
        return ''
    return _normalize_search_planner_context_text(cleaned, max_len=max_len)



def _web_planner_clean_current_query_text(text: str, *, max_len: int = 600) -> str:
    """Clean only the web-search query lane's current user text.

    Chat/file lanes still receive the raw message. This prevents auto-attached
    local file chips such as `[file] app-v13.py` from becoming web search
    queries, while preserving the actual natural-language request that follows.
    """
    raw = str(text or '')
    if not raw.strip():
        return ''

    file_ext_re = re.compile(
        r'\b[\w.()\-\u4e00-\u9fff]+\.(?:py|html?|md|txt|json|csv|docx?|xlsx?|pdf|zip|7z|rar|tar|gz|yaml|yml|css|js|ts)\b',
        re.I,
    )

    cleaned = raw
    cleaned = re.sub(r'\[(?:file|文件)\]\s*' + file_ext_re.pattern, ' ', cleaned, flags=re.I)
    cleaned = re.sub(r'\[(?:file|文件)\]\s*', ' ', cleaned, flags=re.I)
    cleaned = file_ext_re.sub(' ', cleaned)
    cleaned = re.sub(r'引用/上文定位\s*[:：]?\s*', ' ', cleaned, flags=re.I)
    cleaned = re.sub(r'当前文件\s*[:：]?\s*', ' ', cleaned, flags=re.I)
    cleaned = re.sub(r'已生成文件\s*[:：]?\s*', ' ', cleaned, flags=re.I)
    cleaned = re.sub(r'生成文件\s*[:：]?\s*', ' ', cleaned, flags=re.I)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    if not cleaned:
        cleaned = raw.strip()
    return _normalize_search_planner_context_text(cleaned, max_len=max_len)


def _web_planner_clean_query_item_text(text: str, *, fallback: str = '') -> str:
    """Post-clean planner-produced query text for local artifact leakage."""
    cleaned = _web_planner_clean_current_query_text(text, max_len=220)
    if not cleaned or len(cleaned) < 2:
        return _normalize_search_query(str(fallback or '').strip())
    return _normalize_search_query(cleaned)


def _web_planner_clean_history(history: list | None = None, *, limit: int = 10) -> tuple[list[dict], int]:
    """Build a clean conversational history lane for query generation.

    The final answer lane may know file memory/audits. The search-query lane
    should not inherit local file lists, generated artifacts, diffs, or download
    cards unless the latest user question itself asks for a file-related search.
    """
    out: list[dict] = []
    dropped = 0
    blocked_kinds = {
        'file', 'genfiles', 'file_memory', 'file_recall', 'file_edit_audit',
        'kb_memory', 'kb_recall', 'kb_doc_brief', 'tool_runtime',
        'orchestrator_soft_hint', 'page', 'web', 'image_reply',
    }
    for m in (history or [])[-40:]:
        if not isinstance(m, dict):
            continue
        role = str(m.get('role') or '').strip().lower()
        if role not in {'user', 'assistant'}:
            continue
        msg_kind = _web_planner_message_file_kind(m)
        if msg_kind in blocked_kinds:
            dropped += 1
            continue
        try:
            text = _message_to_text_for_budget(m, include_images=False, include_image_text=False)
        except Exception:
            text = ''
        if not text:
            try:
                text = _msg_content_text(m.get('content')).strip()
                if role == 'user':
                    text = _combine_message_text_and_quote(text, _message_quote_text(m))
            except Exception:
                text = ''
        text = _web_planner_strip_artifact_text(text, max_len=360)
        if not text:
            if msg_kind:
                dropped += 1
            continue
        out.append({'role': role, 'content': text})
    return out[-max(1, int(limit or 10)):], dropped


def _web_planner_review_query_items_with_context(user_text: str, query_items: list | None = None, *, planner_context: str = '', history: list | None = None, client_override=None, model: str | None = None) -> list[dict]:
    """Let the query-generation model borrow the concrete subject from context.

    This is a soft review pass for the planner lane, not a keyword gate. The
    first planner can still decide the search shape; this pass only checks
    whether a vague continuation accidentally survived as the literal query even
    though nearby assistant/image context already named the real subject.
    """
    items = [dict(it) for it in (query_items or []) if isinstance(it, dict) and str(it.get('text') or '').strip()]
    if not items:
        return []

    context_blocks: list[str] = []
    try:
        pc = _normalize_search_planner_context_text(planner_context, max_len=2600)
    except Exception:
        pc = str(planner_context or '').strip()[:2600]
    if pc:
        context_blocks.append('planner_context:\n' + pc)

    try:
        hist_lines = _search_planner_context_lines(history or [], limit=8)
    except Exception:
        hist_lines = []
    if hist_lines:
        context_blocks.append('recent_dialogue:\n' + '\n'.join(hist_lines))

    context_text = '\n\n'.join([x for x in context_blocks if str(x or '').strip()]).strip()
    if not context_text:
        return items

    try:
        user_clean = _normalize_search_query(str(user_text or '').strip())
    except Exception:
        user_clean = str(user_text or '').strip()
    try:
        candidate_json = json.dumps(items[:6], ensure_ascii=False)
    except Exception:
        candidate_json = str(items[:6])

    contract_text = ''
    try:
        contract_builder = globals().get('prompt_contract_text')
        if callable(contract_builder):
            contract_text = str(contract_builder('web_query_reviewer', compact=True) or '').strip()
    except Exception:
        contract_text = ''
    sys = (
        ((contract_text + '\n') if contract_text else '')
        + '搜索 query 二次校对补充约束：不决定是否联网，只检查候选 query 是否把当前任务的真实主体带上。'
        '如果最新用户问题是在承接上一轮，只表达想联网核实、查一下、搜一下、看看网页，但没有新主体，'
        '而上下文里上一轮助手回答、图片引用上下文或 OCR 已经明确出现了商品名、品牌、人名、地点、文件对象等具体主体，'
        '你要借用这个具体主体重写 query；不要把承接句原样作为搜索词。'
        '如果候选 query 已经包含了足够具体的主体，就尽量保持不变。'
    )
    usr = (
        f'最新用户问题：{user_clean}\n\n'
        f'候选 query_items：{candidate_json}\n\n'
        f'可借鉴上下文：\n{context_text}'
    )

    try:
        client = client_override or globals().get('client_gpt')
        if client is None:
            return items
        resolver = globals().get('_resolve_aux_model')
        planner_model = resolver(model, 'WEB_SEARCH_PLANNER_MODEL', 'gpt-5.4-nano') if callable(resolver) else (model or 'gpt-5.4-nano')
        req = {
            'model': planner_model,
            'messages': [
                {'role': 'system', 'content': sys},
                {'role': 'user', 'content': usr},
            ],
            'temperature': 0.0,
            'max_tokens': 340,
        }
        contract_format = globals().get('apply_prompt_contract_response_format')
        if callable(contract_format):
            req = contract_format(req, 'web_query_reviewer')
        else:
            req['response_format'] = {'type': 'json_object'}
        apply_thinking = globals().get('_apply_completion_thinking_kwargs')
        if callable(apply_thinking):
            req = apply_thinking(req, role='query_generation', model=planner_model, client_override=client_override)
        resp = client.chat.completions.create(**req)
        raw = str((resp.choices[0].message.content or '')).strip()
        parser = globals().get('_safe_parse_json')
        obj = parser(raw) if callable(parser) else json.loads(raw)
        revised_raw = (obj or {}).get('query_items') or (obj or {}).get('queries') or []
        normalizer = globals().get('_normalize_planner_query_items')
        if callable(normalizer):
            _qs, revised_items = normalizer(revised_raw, limit=6)
        else:
            revised_items = [dict(it) for it in revised_raw if isinstance(it, dict) and str(it.get('text') or '').strip()]
        revised_items = [dict(it) for it in (revised_items or []) if str((it or {}).get('text') or '').strip()]
        return revised_items or items
    except Exception:
        return items

def _web_enrich_messages(messages: list, *, planner_text: str, user_geo: dict | None = None, user_time: dict | None = None, web_enabled: bool | None = None, web_k: int | None = None, web_max_pages: int | None = None, history: list | None = None, extra_context: str = '', client_override=None, allow_weather_tool: bool = True, model: str | None = None) -> tuple[list, dict]:
    """在工具阶段之后再做一轮 AI 关键词规划 + 联网搜索 + 网页抓取补充。"""
    out = list(messages or [])
    meta = {"enabled": False, "reason": "disabled"}
    if not (bool(web_enabled) and str(planner_text or '').strip()):
        return out, meta

    raw_planner_seed = _normalize_search_query(str(planner_text or '').strip())
    planner_seed = _normalize_search_query(_web_planner_clean_current_query_text(raw_planner_seed, max_len=600))
    if not planner_seed:
        planner_seed = raw_planner_seed
    planner_context = _normalize_search_planner_context_text(extra_context, max_len=1800)

    if web_max_pages is not None:
        max_pages = int(web_max_pages)
    else:
        max_pages = _cfg_int("AUTO_WEB_FAST_MAX_PAGES", 2)
    max_pages = max(0, min(max_pages, 8))

    raw_history_for_planner = history or messages
    try:
        visual_ref_builder = globals().get('_build_visual_reference_planning_context')
        visual_ref = visual_ref_builder(
            raw_history_for_planner or [],
            user_text=planner_seed or planner_text,
            max_items=3,
            max_chars=2400,
        ) if callable(visual_ref_builder) else {}
        visual_ref_text = str((visual_ref or {}).get('text') or '').strip()
        if visual_ref_text and visual_ref_text not in planner_context:
            planner_context = '\n\n'.join([x for x in (planner_context, 'visual_reference_context_for_planning:\n' + visual_ref_text) if str(x or '').strip()])
            planner_context = _normalize_search_planner_context_text(planner_context, max_len=3200)
    except Exception:
        pass
    clean_history_for_planner, dropped_file_context = _web_planner_clean_history(raw_history_for_planner, limit=10)
    try:
        app_logger.info(
            "[WEB_PLANNER_CONTEXT] dropped_file_context=%s clean_history=%s raw_history=%s user_text=%r",
            dropped_file_context,
            len(clean_history_for_planner or []),
            len(raw_history_for_planner or []),
            ("raw=" + str(raw_planner_seed or '')[:120] + " | clean=" + str(planner_seed or '')[:120]),
        )
    except Exception:
        pass
    plan = _llm_decide_web_search(planner_seed, user_geo=user_geo, history=clean_history_for_planner, client_override=client_override, allow_weather_tool=allow_weather_tool, current_model=model, planner_context=planner_context, user_time=user_time)
    plan_query_items = [dict(it) for it in (plan.get('query_items') or []) if isinstance(it, dict) and str(it.get('text') or '').strip()]
    if not plan_query_items:
        plan_query_items = [{'text': str(q).strip(), 'purpose': '', 'coverage': '', 'focus': '', 'priority': 0.0} for q in (plan.get("queries") or []) if str(q or '').strip()]
    if not plan_query_items:
        plan_query_items = [{'text': str(q).strip(), 'purpose': 'fallback', 'coverage': 'fast_query', 'focus': '', 'priority': 0.0} for q in (_fast_queries(planner_seed or planner_text, user_geo=user_geo) or []) if str(q or '').strip()]
    if plan_query_items:
        cleaned_items = []
        for item in plan_query_items:
            if not isinstance(item, dict):
                continue
            cleaned_text = _web_planner_clean_query_item_text(item.get('text') or '', fallback=planner_seed)
            if not cleaned_text:
                continue
            new_item = dict(item)
            new_item['text'] = cleaned_text
            cleaned_items.append(new_item)
        plan_query_items = _web_planner_review_query_items_with_context(
            planner_seed or planner_text,
            cleaned_items,
            planner_context=planner_context,
            history=raw_history_for_planner,
            client_override=client_override,
            model=model,
        )
    if not plan_query_items:
        return out, {"enabled": True, "reason": "no_queries"}

    _normalized_queries, normalized_query_items = _normalize_planner_query_items(plan_query_items, limit=6)
    if not normalized_query_items:
        return out, {"enabled": True, "reason": "no_queries"}

    max_query_rounds = max(1, min(_cfg_int('AUTO_WEB_MAX_QUERIES', 2), 3))
    plan_strategy = _normalize_planner_query_strategy(plan.get('query_strategy') or '')
    plan_focus_plan = _normalize_planner_focus_plan(plan.get('focus_plan') or [], limit=6)
    selected_query_items = _select_diverse_query_items(
        normalized_query_items,
        max_items=max_query_rounds,
        query_strategy=plan_strategy,
        focus_plan=plan_focus_plan,
    )
    selected_texts = {str(it.get('text') or '') for it in selected_query_items}
    reserve_query_items = [item for item in normalized_query_items if str(item.get('text') or '') not in selected_texts]
    candidate_queries = [str(item.get('text') or '').strip() for item in selected_query_items if str(item.get('text') or '').strip()]
    if not candidate_queries:
        return out, {"enabled": True, "reason": "no_queries"}

    q0 = candidate_queries[0]
    cache_key = hashlib.sha1(f"orchestrated|{'||'.join(candidate_queries)}|{_coarse_geo_key(user_geo)}|{max_pages}".encode("utf-8")).hexdigest()
    cached = _cache_get(cache_key)
    if cached:
        out.append({"role": "system", "_kind": "web", "content": cached})
        return out, {"enabled": True, "query": q0, "queries_used": list(candidate_queries), "cache_hit": True, "results": None, "pages": None, "search_rounds": 0, "query_strategy": plan_strategy, "planned_focuses": _planner_focus_plan_keys(plan_focus_plan), "search_results": [], "dropped_file_context": dropped_file_context, "planner_context_source": "clean_history_no_file_artifacts"}

    k_results = int(web_k) if web_k is not None else _cfg_int("AUTO_WEB_K_RESULTS", 8)
    k_results = max(3, min(k_results, 12))

    initial_round_queries = candidate_queries[:min(len(candidate_queries), 2)]
    reserve_queries = [str(item.get('text') or '').strip() for item in reserve_query_items if str(item.get('text') or '').strip()]
    queries_used = list(initial_round_queries)
    search_rounds = 1

    res, err = web_search_multi(initial_round_queries, k=k_results)
    pages = _fetch_web_pages_for_results(res, max_pages=max_pages, query_text=q0)

    need_focus_supplement = _planner_focuses_need_supplement(selected_query_items, reserve_query_items)
    uncovered_focuses = _planner_uncovered_focuses(plan_focus_plan, selected_query_items)
    if _web_search_results_need_supplement(res, pages) or need_focus_supplement or bool(uncovered_focuses):
        preferred_extra_items = _select_query_items_for_supplement(
            reserve_query_items,
            selected_items=selected_query_items,
            focus_plan=plan_focus_plan,
        ) if (need_focus_supplement or bool(uncovered_focuses)) else []
        preferred_extra_texts = [str(item.get('text') or '').strip() for item in preferred_extra_items if str(item.get('text') or '').strip() and str(item.get('text') or '').strip() not in queries_used]
        extra_candidates = preferred_extra_texts or [q for q in reserve_queries if q not in queries_used]
        if not extra_candidates:
            extra_candidates = [
                _normalize_search_query(q)
                for q in (_fast_queries(planner_seed or planner_text, user_geo=user_geo) or [])
                if _normalize_search_query(q) and _normalize_search_query(q) not in queries_used
            ]
        if extra_candidates:
            extra_queries = extra_candidates[:1]
            extra_res, extra_err = web_search_multi(extra_queries, k=k_results)
            queries_used.extend(extra_queries)
            search_rounds += 1
            res = _merge_web_search_results(res, extra_res, limit=max(k_results, 12))
            err = err or extra_err
            pages = _fetch_web_pages_for_results(res, max_pages=max_pages, query_text=q0)

    if res:
        block = _build_web_injection_block(q0, res, pages=pages)
        out.append({
            "role": "system",
            "content": "你已获得实时外部信息（联网搜索结果/网页抓取内容）。请优先基于这些材料回答，并在需要时引用其中的标题/链接；不要再说“无法联网/不能实时获取”。"
        })
        out.append({"role": "system", "_kind": "web", "content": block})
        _cache_set(cache_key, block)
    else:
        out.append({
            "role": "system",
            "_kind": "web",
            "content": f"已自动尝试联网搜索，但未返回结果（query={q0}，error={err}）。如需实时信息可建议用户换关键词或稍后重试。"
        })
    return {"messages": out}["messages"], {"enabled": True, "query": q0, "queries_used": queries_used, "cache_hit": False, "results": len(res or []), "pages": len(pages or []), "error": err, "search_rounds": search_rounds, "query_strategy": plan_strategy, "planned_focuses": _planner_focus_plan_keys(plan_focus_plan), "search_results": _search_results_for_reasoning_meta(res, limit=max(k_results, 24)), "dropped_file_context": dropped_file_context, "planner_context_source": "clean_history_no_file_artifacts"}
