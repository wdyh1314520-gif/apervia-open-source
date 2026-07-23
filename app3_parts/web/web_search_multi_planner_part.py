# Split from app3_parts/web/web_search_enrichment_part.py.
# Purpose: multi-query search, query planner, web injection block, and code Chinese-safe prompt.
# Loaded by web_search_enrichment_part.py via _exec_split_file(...), sharing the original global namespace.

from concurrent.futures import ThreadPoolExecutor, as_completed

_SEARCH_POOL = ThreadPoolExecutor(max_workers=int(app_getenv("WEB_SEARCH_WORKERS", "6") or 6))

def web_search_multi(queries: list[str], k: int = 10) -> tuple[list[dict], str | None]:
    """并发执行多个搜索 query，合并去重后返回 top-k。
    - queries: 形如 ["伊朗 最新 新闻", "Iran latest news"] 或 planner 生成的多条 query
    - 只用于 AUTO_WEB_ENRICH 流程（不破坏你原来的 /api3/web_search 接口）
    """
    try:
        qs = [(_normalize_search_query(q) or "").strip() for q in (queries or []) if (q or "").strip()]
        # 去重保序
        seen=set(); qs2=[]
        for q in qs:
            if q and q not in seen:
                seen.add(q); qs2.append(q)
        qs2 = qs2[:max(1, min(int(app_getenv("AUTO_WEB_MAX_QUERIES", "4") or 4), 8))]
        if not qs2:
            return [], "empty queries"

        kk = int(max(4, min(int(k), 24)))
        request_overrides_snapshot = _current_request_overrides_snapshot()

        def _run_one_query(qq: str):
            _set_request_overrides(request_overrides_snapshot)
            try:
                return web_search(qq, kk)[0]
            finally:
                try:
                    _set_request_overrides({})
                except Exception:
                    pass

        futures = { _SEARCH_POOL.submit(_run_one_query, q): q for q in qs2 }
        merged=[]
        errs=[]
        for fut in as_completed(futures):
            q = futures[fut]
            try:
                res = fut.result()
                if res:
                    # 标记来源 query，方便后续排序/排错
                    for it in res:
                        if isinstance(it, dict):
                            it.setdefault("_q", q)
                    merged.extend(res)
            except Exception as e:
                errs.append(f"{q}: {type(e).__name__}: {e}")

        if not merged:
            return [], ("; ".join(errs)[:200] if errs else "no results")

        # 去重 URL（归一化）
        out=[]
        seen_u=set()
        for it in merged:
            u = (it.get("url") or "").strip()
            if not u:
                continue
            nu = _norm_url_for_dedup(u)
            if nu in seen_u:
                continue
            seen_u.add(nu)
            out.append(it)

        # 用首个 query 做主要排序基准（更符合用户意图）
        base_q = qs2[0]
        try:
            out.sort(key=lambda x: _search_result_score(base_q, x), reverse=True)
        except Exception:
            pass

        return out[:kk], (None if not errs else ("; ".join(errs)[:200]))
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"


# ====== Price keyword helper (kept) ======
_PRICE_KEYWORDS = ["价格","多少钱","收费","套餐","订阅","会员","定价","报价","价位","优惠","折扣","usd","cny","usdt","¥","￥","$"]

def _is_price_or_product_query(text: str) -> bool:
    s = (text or "").lower()
    if not s:
        return False
    return any(k.lower() in s for k in _PRICE_KEYWORDS)

def _safe_parse_json(s: str) -> dict | None:
    """尽量从模型输出中解析 JSON（容错：去掉代码块/前后杂质）。"""
    if not s:
        return None
    t = s.strip()
    # 去掉 ```json ``` 包裹
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*```$", "", t)
    # 尝试截取第一个 { ... } 或 [ ... ]
    obj = None
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    try:
        m = re.search(r"\{[\s\S]*\}", t)
        if m:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
    except Exception:
        return None
    return None


def _planner_query_item_text(item) -> str:
    if isinstance(item, str):
        return str(item).strip()
    if isinstance(item, dict):
        return str(item.get('text') or item.get('query') or '').strip()
    return ''


def _planner_query_item_purpose(item) -> str:
    if not isinstance(item, dict):
        return ''
    return str(item.get('purpose') or item.get('type') or item.get('angle') or '').strip().lower()[:40]


def _planner_query_item_coverage(item) -> str:
    if not isinstance(item, dict):
        return ''
    return str(item.get('coverage') or item.get('note') or '').strip()[:80]


def _planner_query_item_focus(item) -> str:
    if not isinstance(item, dict):
        return ''
    return str(item.get('focus') or item.get('entity') or item.get('slot') or '').strip()[:80]


def _planner_query_item_priority(item) -> float:
    if not isinstance(item, dict):
        return 0.0
    raw = item.get('priority')
    if raw in (None, ''):
        raw = item.get('score')
    try:
        value = float(raw)
    except Exception:
        value = 0.0
    if value > 1.0:
        value = value / 5.0 if value <= 5.0 else value / 10.0
    return max(0.0, min(value, 1.0))


def _normalize_planner_query_strategy(value) -> str:
    raw = str(value or '').strip().lower().replace('-', '_').replace(' ', '_')
    if raw in {'single_focus', 'split_by_entity', 'holistic_compare', 'broad_scan'}:
        return raw
    if raw in {'compare', 'comparison', 'compare_first', 'holistic'}:
        return 'holistic_compare'
    if raw in {'entity_split', 'split_entities', 'entity_first', 'per_entity'}:
        return 'split_by_entity'
    if raw in {'single', 'single_subject', 'single_entity'}:
        return 'single_focus'
    return ''


def _planner_focus_key(value) -> str:
    raw = str(value or '').strip().lower()
    if not raw:
        return ''
    raw = re.sub(r'\s+', ' ', raw)
    return raw[:80]


def _normalize_planner_focus_plan(focus_plan, *, limit: int = 6) -> list[dict]:
    out: list[dict] = []
    seen = set()
    raw_items = focus_plan or []
    if isinstance(raw_items, str):
        raw_items = [raw_items]
    for raw in raw_items:
        if isinstance(raw, dict):
            focus = _planner_focus_key(raw.get('focus') or raw.get('name') or raw.get('label') or '')
            coverage = _planner_query_item_coverage(raw)
            priority = _planner_query_item_priority(raw)
        else:
            focus = _planner_focus_key(raw)
            coverage = ''
            priority = 0.0
        if not focus or focus in seen:
            continue
        seen.add(focus)
        out.append({'focus': focus, 'coverage': coverage, 'priority': priority})
        if len(out) >= max(1, int(limit or 6)):
            break
    return out


def _normalize_planner_query_items(query_items, *, limit: int = 4) -> tuple[list[str], list[dict]]:
    normalized_queries: list[str] = []
    normalized_items: list[dict] = []
    seen = set()
    raw_items = query_items or []
    if isinstance(raw_items, str):
        raw_items = [raw_items]
    for raw in raw_items:
        text = _normalize_search_query(_planner_query_item_text(raw))
        if not text or text in seen:
            continue
        seen.add(text)
        item = {
            'text': text,
            'purpose': _planner_query_item_purpose(raw),
            'coverage': _planner_query_item_coverage(raw),
            'focus': _planner_focus_key(_planner_query_item_focus(raw)),
            'priority': _planner_query_item_priority(raw),
        }
        normalized_queries.append(text)
        normalized_items.append(item)
        if len(normalized_queries) >= max(1, int(limit or 4)):
            break
    return normalized_queries, normalized_items


def _query_novelty_terms(text: str) -> set[str]:
    terms = set()
    for kw in (_extract_keywords_simple(text, max_n=10) or []):
        token = str(kw or '').strip().lower()
        if token:
            terms.add(token)
    raw = str(text or '').strip().lower()
    for token in re.findall(r'[a-z0-9][a-z0-9_\-\.]{1,}', raw):
        terms.add(token)
    if not terms and raw:
        for ch in raw:
            ch = ch.strip()
            if ch and '\u4e00' <= ch <= '\u9fff':
                terms.add(ch)
    return terms


def _planner_query_item_selection_score(item: dict | None = None, *, selected_items: list[dict] | None = None) -> float:
    item = dict(item or {})
    selected = [dict(it) for it in (selected_items or []) if isinstance(it, dict)]
    text2 = str(item.get('text') or '')
    purpose = str(item.get('purpose') or '').strip().lower()
    focus = _planner_focus_key(item.get('focus') or '')
    priority = _planner_query_item_priority(item)
    terms = _query_novelty_terms(text2)
    selected_terms: set[str] = set()
    selected_purposes = {str(it.get('purpose') or '').strip().lower() for it in selected if str(it.get('purpose') or '').strip()}
    selected_focuses = {_planner_focus_key(it.get('focus') or '') for it in selected if _planner_focus_key(it.get('focus') or '')}
    for picked in selected:
        selected_terms.update(_query_novelty_terms(str(picked.get('text') or '')))
    if not selected:
        novelty = 1.0 if terms else 0.5
    elif terms:
        overlap = len(terms & selected_terms)
        novelty = (len(terms) - overlap) / max(1, len(terms))
    else:
        novelty = 0.0
    purpose_bonus = 0.22 if purpose and purpose not in selected_purposes else 0.0
    focus_bonus = 0.38 if focus and focus not in selected_focuses else 0.0
    coverage_bonus = 0.08 if str(item.get('coverage') or '').strip() else 0.0
    return (priority * 1.15) + novelty + purpose_bonus + focus_bonus + coverage_bonus


def _select_diverse_query_items(query_items: list[dict] | None = None, *, max_items: int = 2, query_strategy: str = '', focus_plan: list[dict] | None = None) -> list[dict]:
    items = [dict(it) for it in (query_items or []) if isinstance(it, dict) and str(it.get('text') or '').strip()]
    if not items:
        return []
    limit = max(1, int(max_items or 1))
    if len(items) <= limit:
        return items

    strategy = _normalize_planner_query_strategy(query_strategy)
    normalized_focus_plan = _normalize_planner_focus_plan(focus_plan, limit=limit + 4)
    selected: list[dict] = []
    remaining = list(items)

    def _pick_best(candidates: list[dict]) -> dict | None:
        if not candidates:
            return None
        best = None
        best_score = None
        for candidate in candidates:
            score = _planner_query_item_selection_score(candidate, selected_items=selected)
            if best_score is None or score > best_score:
                best_score = score
                best = candidate
        return best

    if strategy == 'split_by_entity' and normalized_focus_plan:
        for focus_item in normalized_focus_plan:
            if len(selected) >= limit:
                break
            focus_key = _planner_focus_key(focus_item.get('focus') or '')
            if not focus_key:
                continue
            focus_candidates = [item for item in remaining if _planner_focus_key(item.get('focus') or '') == focus_key]
            chosen = _pick_best(focus_candidates)
            if chosen is None:
                continue
            selected.append(chosen)
            remaining = [item for item in remaining if str(item.get('text') or '') != str(chosen.get('text') or '')]

    while remaining and len(selected) < limit:
        chosen = _pick_best(remaining)
        if chosen is None:
            break
        selected.append(chosen)
        remaining = [item for item in remaining if str(item.get('text') or '') != str(chosen.get('text') or '')]

    return selected




def _web_search_query_planner_mode(user_text: str = '', history: list[dict] | None = None, planner_context: str = '') -> str:
    """Return fast/deep query-planner mode without deciding whether to search.

    fast: shorter prompt, less history, lower token budget.
    deep: richer focus planning for ambiguous/multi-context searches.
    auto: uses size/available-context signals only, not keyword locks.
    """
    raw = str(app_getenv('WEB_SEARCH_QUERY_PLANNER_MODE', 'auto') or 'auto').strip().lower()
    if raw in {'fast', 'quick', 'lite', 'light'}:
        return 'fast'
    if raw in {'deep', 'full', 'thorough'}:
        return 'deep'
    try:
        text_len = len(str(user_text or '').strip())
        ctx_len = len(str(planner_context or '').strip())
        hist_count = len([m for m in (history or []) if isinstance(m, dict)])
    except Exception:
        text_len = ctx_len = hist_count = 0
    if ctx_len >= 700 or hist_count >= 6 or text_len >= 120:
        return 'deep'
    return 'fast'


def _web_search_query_planner_limits(mode: str = 'fast') -> dict:
    mode = 'deep' if str(mode or '').strip().lower() == 'deep' else 'fast'
    if mode == 'deep':
        return {
            'history_limit': 12,
            'planner_context_max': 2600,
            'max_tokens': 560,
            'query_limit': 6,
            'focus_plan_limit': 8,
        }
    return {
        'history_limit': 5,
        'planner_context_max': 1200,
        'max_tokens': 320,
        'query_limit': 4,
        'focus_plan_limit': 5,
    }


def _web_search_query_planner_system_prompt(mode: str = 'fast') -> str:
    mode = 'deep' if str(mode or '').strip().lower() == 'deep' else 'fast'
    contract_text = ''
    try:
        contract_builder = globals().get('prompt_contract_text')
        if callable(contract_builder):
            contract_text = str(contract_builder('web_query_planner', compact=True) or '').strip()
    except Exception:
        contract_text = ''
    if mode == 'fast':
        return (
            ((contract_text + "\n") if contract_text else "")
            + "联网搜索 query planner 补充约束：外部已经决定要联网；这里只生成干净、可执行、互补的搜索词。"
            "结合最新用户问题、最近上下文、时间/地点提示补全主体；不要把 user:/assistant:/context:/工具结果 这类元文字写进 query。"
            "输出 1 到 3 条 query；多对象或比较任务可拆成整体+对象焦点。"
        )
    return (
        ((contract_text + "\n") if contract_text else "")
        + "联网搜索词规划补充约束：联网是否开启由外部控制，这里不要决定搜不搜，只负责把这次搜索词规划得更准。"
        "要优先理解‘这轮最新用户问题’到底在承接什么上下文；如果用户用了代词（她/他/它/这个人/这位/上面那个等）或省略表达，要先结合最近对话把主体、时间、地点、比较对象补全，再输出可直接搜索的 query。如果最近对话上下文或 context 中提供了图片/视觉线索、图片 OCR、商品标签或预判出的图片主体，而用户是在查‘它/这个/这瓶/图里这个’，要把这些视觉线索当作可用上下文来补全搜索主体，不要把用户的泛化原话直接当成 query。"
        "如果最新用户问题本身只是继续要求联网、核实、查一下、搜一下、上网看一下，但没有新的明确搜索主体，就把它视为对上一轮任务的延续：优先从最近的用户问题、助手回答、图片引用上下文、视觉对话锚点中抽取已经说出的具体主体（例如商品名、品牌、标签文字、人物名、地点名），再围绕这个主体规划 query；不要把‘能上网查一下吗/帮我查一下/搜一下’这类承接句原样作为 query。"
        "查询词必须像真实搜索框输入：干净、自然、可执行，不要把 user:/assistant:/context:/已知工具结果/最近对话上下文 这类元文字带进 query。"
        "不要依赖固定模板，不要把新闻、天气、人物、产品等问题机械改写成统一句式；应根据当前语境自行组织最贴题的搜法。"
        "尽量理解用户真正想查的对象和意图，再给出 1 到 4 条简短、可直接拿去搜索的 query。"
        "对于人物/账号/产品/公司/地点的基本信息、简介、背景、主页、公开资料，要优先保留明确主体，不要写成她是谁、这个人资料这种无主体 query。"
        "优先生成一组彼此互补的 query，而不是同义改写。"
        "如果用户问题里有现在/当前/今天/本周/本月/今年/最近/最新等时效词，必须按本轮时间锚点理解，并把对应的年份、日期窗口或当前时态体现在 query 里；不要凭旧印象写成过去年份。"
        "先决定这次更适合哪种 query_strategy：single_focus（单对象正常搜）、split_by_entity（多对象时按对象拆分规划）、holistic_compare（整体比较为主但可少量补充）、broad_scan。"
        "如果你判断应该用 split_by_entity，就先给出 focus_plan，说明要覆盖哪些焦点；通常会包含整体比较、对象A、对象B，必要时再加最新动态/官方来源。"
        "当你选择 split_by_entity 时，query_items 里至少应有一部分是真正聚焦单个对象/单个焦点的，不要所有 query 都把多个对象永远绑在一起。"
        "不要机械地把同一句话改写四遍；query 之间应尽量减少语义重叠，并按信息价值排序。"
        "规则：subject 要具体；queries 1 到 4 条；query_items 表达每条 query 的证据角度；不要输出 need_search 字段。"
    )

def _llm_decide_web_search(user_text: str, user_geo: dict | None, history: list[dict] | None = None, client_override=None, allow_weather_tool: bool = True, current_model: str | None = None, planner_context: str = '', user_time: dict | None = None) -> dict:
    """让模型只负责规划搜索词。
    联网是否开启由前端/外层控制，这里不再决定 need_search。
    返回 dict: {need_search: bool, subject: str, intent: str, queries: [..], reason: str}
    其中 need_search 仅保持兼容，默认恒为 True（除空输入）。
    """
    user_text = _normalize_search_query(user_text)
    if not user_text:
        return {"need_search": False, "subject": "", "intent": "", "query_strategy": "", "focus_plan": [], "queries": [], "reason": "empty"}

    geo_hint = ""
    weather_route = _classify_weather_route(user_text)
    weather_tech_query = (weather_route == "tech")
    if allow_weather_tool and (not weather_tech_query) and isinstance(user_geo, dict) and user_geo.get("lat") is not None and user_geo.get("lon") is not None:
        try:
            lat = float(user_geo["lat"])
            lon = float(user_geo["lon"])
            geo_hint = f"用户大概坐标：lat={lat}, lon={lon}。如果问题可能与本地有关（例如天气/附近服务），可以把地点加入搜索词。"
        except Exception:
            geo_hint = ""

    planner_mode = _web_search_query_planner_mode(user_text, history=history, planner_context=planner_context)
    planner_limits = _web_search_query_planner_limits(planner_mode)
    ctx_lines = _search_planner_context_lines(history, limit=int(planner_limits.get('history_limit') or 4))
    planner_context = _normalize_search_planner_context_text(planner_context, max_len=int(planner_limits.get('planner_context_max') or 900))
    if planner_context:
        ctx_lines.append(f"context: {planner_context}")
    ctx = "\n".join(ctx_lines)
    runtime_time_hint = _build_runtime_time_hint(user_time)
    sys = _web_search_query_planner_system_prompt(planner_mode)
    usr = f"planner_mode：{planner_mode}\n用户最新问题：{user_text}\n\n{runtime_time_hint}\n\n{geo_hint}\n\n最近对话上下文（可能为空）：\n{ctx}"

    try:
        client = client_override or client_gpt
        planner_model = _resolve_aux_model(current_model, "WEB_SEARCH_PLANNER_MODEL", "gpt-5.4-nano")
        req = {
            "model": planner_model,
            "messages": [
                {"role": "system", "content": sys},
                {"role": "user", "content": usr},
            ],
            "temperature": 0.0,
            "max_tokens": int(planner_limits.get('max_tokens') or 260),
        }
        contract_format = globals().get('apply_prompt_contract_response_format')
        if callable(contract_format):
            req = contract_format(req, 'web_query_planner')
        else:
            req["response_format"] = {"type": "json_object"}
        req = _apply_completion_thinking_kwargs(req, role="query_generation", model=planner_model, client_override=client_override)
        resp = client.chat.completions.create(**req)
        out = (resp.choices[0].message.content or "").strip()
        obj = _safe_parse_json(out) or {}
        subject = str(obj.get("subject") or "").strip()[:120]
        intent = str(obj.get("intent") or "").strip()[:40]
        query_strategy = _normalize_planner_query_strategy(obj.get("query_strategy") or "")
        focus_plan = _normalize_planner_focus_plan(obj.get("focus_plan") or [], limit=int(planner_limits.get('focus_plan_limit') or 4))
        qs = obj.get("queries") or []
        if isinstance(qs, str):
            qs = [qs]
        query_items_raw = obj.get('query_items') or []
        if isinstance(query_items_raw, dict):
            query_items_raw = [query_items_raw]
        normalized_queries, normalized_items = _normalize_planner_query_items(query_items_raw, limit=int(planner_limits.get('query_limit') or 3))
        if not normalized_queries:
            normalized_queries, normalized_items = _normalize_planner_query_items(qs, limit=int(planner_limits.get('query_limit') or 3))

        return {
            "need_search": True,
            "subject": subject,
            "intent": intent,
            "query_strategy": query_strategy,
            "planner_mode": planner_mode,
            "focus_plan": focus_plan,
            "queries": normalized_queries,
            "query_items": normalized_items,
            "reason": str(obj.get("reason") or "llm")[:80],
        }
    except Exception:
        return {"need_search": True, "subject": "", "intent": "", "query_strategy": "", "focus_plan": [], "queries": [], "reason": "llm_error", "planner_mode": locals().get("planner_mode", "fast")}

def _build_web_injection_block(query: str, results: list[dict], pages: list[dict] | None = None) -> str:
    """把搜索结果 + 可选抓取网页正文，整理成可注入 system 的材料包。
    省钱提速：限制注入的搜索条目数与每页正文长度。
    """
    lines = []
    lines.append(f"【联网搜索】query: {query}")
    lines.append("下面是搜索结果与部分网页摘录（若有）。请基于材料回答；不要编造材料里没有的精确数值/细节；需要时引用标题/链接。")
    lines.append("")
    max_inject = int(app_getenv("AUTO_WEB_INJECT_RESULTS", "3") or 3)
    max_inject = max(1, min(max_inject, 6))
    for i, r in enumerate((results or [])[:max_inject], start=1):
        lines.append(f"[{i}] {r.get('title','')}".strip())
        lines.append((r.get("url") or "").strip())
        sn = (r.get("snippet") or "").strip()
        if sn:
            sn = truncate_text(sn, max_chars=int(app_getenv("AUTO_WEB_SNIPPET_CHARS","300") or 300))
            lines.append(f"摘要：{sn}")
        lines.append("")
    if pages:
        lines.append("【网页正文摘录】（自动抓取，可能被截断）")
        for i, p in enumerate(pages, start=1):
            url = p.get("url") or ""
            title = p.get("title") or ""
            txt = p.get("text") or ""
            err = p.get("error")
            lines.append("")
            lines.append("=" * 18 + f" PAGE {i} " + "=" * 18)
            if title:
                lines.append(f"TITLE: {title}")
            lines.append(f"URL: {url}")
            if err:
                lines.append(f"ERROR: {err}")
            if txt:
                lines.append(_snippet_by_query(txt, query, limit=int(app_getenv("AUTO_WEB_PAGE_EXCERPT_CHARS","1200") or 1200)))
    return "".join([x for x in lines if x is not None]).strip()



def _msg_content_text(content) -> str:
    """Extract user-visible text from OpenAI-style message content.
    Supports:
      - str
      - list[ {type:'text', text:'...'}, {type:'image_url', ...}, ... ]
      - dict attachment tags used by this UI
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        # our UI attachment markers
        if content.get("_kind") in ("file", "image"):
            fn = content.get("filename") or ""
            return f"[{content.get('_kind')}] {fn}".strip()
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts = []
        for it in content:
            if isinstance(it, dict) and it.get("type") == "text":
                t = it.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t.strip())
        return "".join(parts)
    # fallback
    return str(content)


CODE_CHINESE_SAFE_PROMPT = """代码/文件中文兼容软提示（不是硬规则，只在当前任务确实涉及代码、脚本、配置或可下载文件时参考）：
- 不要为了躲避乱码把中文提示、注释、菜单、输出文案强行改成英文；除非用户明确要求英文。
- 如果代码里会显示中文、读写中文，或要生成带中文的文件，要主动处理编码，不要只是把中文字符串直接写进去。
- 普通源码/脚本/配置文件优先 UTF-8；CSV 给 Windows/Excel 打开优先 utf-8-sig。
- 如果是 Windows 本地编译/运行且中文较多，尤其 C/C++、头文件、批处理、纯文本源码这类可下载文件，可优先使用 gb18030，降低本地打开、编译、运行时乱码概率。
- 对 Python、Java、JavaScript/TypeScript、C#、Go、Shell/PowerShell 这类编程任务，要优先照顾“源码文件编码 + 运行时输出编码 + 文件读写编码”，不要只顾源码字面量本身。
- 如果是 Windows 控制台程序并且会输出中文，要把该语言对应的终端中文处理直接写进代码：
  * C/C++：优先处理控制台代码页 / locale，必要时用宽字符输出，不要只写中文字面量。
  * Python：源码文件优先 UTF-8；涉及文件读写要显式 encoding='utf-8'；控制台输出中文时按需要处理 stdout 编码或重配置标准输出。
  * Java：源码文件优先 UTF-8；涉及文件读写要显式指定 Charset/UTF-8；如包含编译/运行说明，优先写出带 -encoding UTF-8、UTF-8 输出的安全写法，不要默认依赖系统本地编码。
  * JavaScript/TypeScript（含 Node.js）：源码文件优先 UTF-8；文件读写优先显式 utf8；终端输出和子进程交互时注意编码，不要默认系统代码页一定正确。
  * C#：源码文件优先 UTF-8；文件读写优先显式 Encoding.UTF8；控制台中文输出时按需要处理 Console 输出编码。
  * 其他语言也按各自惯用方式处理源码编码、终端输出编码和文件编码。
- 如果要交付可直接编译/运行的示例，能把中文兼容处理直接写进源码，就不要只在说明里提醒用户自己改编码；必要时把编译、运行、保存文件时的编码注意点一起写进去。
"""


# 已移除图片专用指导提示：不再单独规定何时配图或如何配图。
