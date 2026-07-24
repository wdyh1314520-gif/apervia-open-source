# reply image selection, image-search planning, tool prefetch decision, and visual context injection.

from concurrent.futures import ThreadPoolExecutor, as_completed

def _looks_like_code_or_file_request(user_text: str) -> bool:
    t = str(user_text or "").strip().lower()
    if not t:
        return False
    hard_no = [
        "报错", "错误", "代码", "源码", "函数", "接口", "api", "sql", "python", "java", "js", "javascript",
        "html", "css", "bug", "修复", "改代码", "重构", "日志", "文件", "pdf", "docx", "xlsx", "压缩包",
        "翻译", "总结", "润色", "写邮件", "表格", "公式", "证明", "推导",
    ]
    return any(k in t for k in hard_no)


def _safe_json_loads(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def _decide_reply_images_with_model(model: str, messages: list, user_text: str, client_override=None) -> dict:
    """让模型先判断这轮回答是否真的需要配图，尽量更像 GPT。"""
    fallback_query = _image_search_query_from_user_text(user_text)
    if not fallback_query:
        return {"need_images": False, "query": "", "source": "empty_query"}

    # 不在模型判断前做代码/文件类硬拦截，只在模型判断失败时兜底为“不自动配图”。
    base = {"need_images": False, "query": fallback_query, "source": "fallback_none"}

    try:
        convo = []
        for m in (messages or [])[-8:]:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            if role not in ("user", "assistant", "system"):
                continue
            content = _msg_content_text(m.get("content"))
            if not content:
                continue
            convo.append({"role": role, "content": content[:1600]})

        contract_text = ''
        try:
            contract_builder = globals().get('prompt_contract_text')
            if callable(contract_builder):
                contract_text = str(contract_builder('image_search_decider', compact=True) or '').strip()
        except Exception:
            contract_text = ''
        judge_prompt = [
            {"role": "system", "content": (
                ((contract_text + "\n") if contract_text else "")
                + "图片使用决策补充约束：请判断这轮回答是否应该自动补充真实网络图片。"
                "只有在图片能显著帮助用户理解对象外观、界面、地点、人物、动物、商品、示意结构时，才返回 need_images=true。"
                "代码、报错、纯概念、纯写作、纯改文档任务通常返回 false。"
            )},
            *convo,
            {"role": "user", "content": (
                f"用户最新问题：{user_text}\n"
                f"候选搜图词：{fallback_query}"
            )},
        ]
        req = {
            "model": model,
            "messages": judge_prompt,
            "temperature": 0,
            "max_tokens": 120,
        }
        contract_format = globals().get('apply_prompt_contract_response_format')
        if callable(contract_format):
            req = contract_format(req, 'image_search_decider')
        else:
            req["response_format"] = {"type": "json_object"}
        resp = (client_override or client_gpt).chat.completions.create(**req)
        msg = (((resp.choices or [None])[0] or None).message.content or "").strip()
        obj = _safe_json_loads(msg) or {}
        need_images = bool(obj.get("need_images"))
        query = str(obj.get("query") or "").strip() or fallback_query
        reason = str(obj.get("reason") or "").strip()
        return {"need_images": need_images, "query": query[:120], "reason": reason[:120], "source": "model"}
    except Exception as e:
        app_logger.debug(f"[image_decision] fallback to heuristic: {type(e).__name__}: {e}")
        return base




def _is_likely_direct_image_url(url: str) -> bool:
    u = str(url or '').strip()
    if not u:
        return False
    if u.startswith('data:image/'):
        return True
    if re.search(r'\.(png|jpe?g|webp|gif|bmp|svg)(?:[?#].*)?$', u, flags=re.I):
        return True
    try:
        host = (urlparse(u).hostname or '').lower()
    except Exception:
        host = ''
    trusted_hosts = {
        'images.unsplash.com', 'images.pexels.com', 'upload.wikimedia.org', 'i.imgur.com',
        'imgur.com', 'live.staticflickr.com',
        'wx1.sinaimg.cn', 'wx2.sinaimg.cn', 'wx3.sinaimg.cn', 'wx4.sinaimg.cn',
        'tva1.sinaimg.cn', 'tva2.sinaimg.cn', 'tva3.sinaimg.cn', 'tva4.sinaimg.cn',
        'tvax1.sinaimg.cn', 'tvax2.sinaimg.cn', 'tvax3.sinaimg.cn', 'tvax4.sinaimg.cn',
        'pbs.twimg.com', 'images.ctfassets.net', 'cdn.pixabay.com'
    }
    return host in trusted_hosts or any(host.endswith('.' + d) for d in trusted_hosts)


def _pick_best_image_candidate_url(row: dict) -> str:
    if not isinstance(row, dict):
        return ''
    candidates = []
    for key in ('url', 'image_url', 'thumbnail', 'image', 'img_src', 'thumbnail_src'):
        v = _normalize_image_url_value(row.get(key) or '')
        if v and v not in candidates:
            candidates.append(v)
    for u in candidates:
        if _is_likely_direct_image_url(u):
            return u
    return ''


def _display_image_url_for_row(row: dict) -> str:
    raw = _pick_best_image_candidate_url(row)
    if not raw:
        return ''
    if raw.startswith('data:image/'):
        return raw
    if raw.startswith('http://') or raw.startswith('https://'):
        data_url = _remote_image_to_data_url(raw)
        return data_url or ''
    return ''


def _visual_markdown_from_urls(urls: list[str], limit: int = 5) -> str:
    safe = [str(u or '').strip() for u in (urls or []) if str(u or '').strip()]
    if not safe:
        return ''
    return "\n\n" + "\n".join(f"![相关图片{i+1}]({u})" for i, u in enumerate(safe[:max(1, limit)]))


def _reply_has_visible_images(text: str) -> bool:
    s = str(text or '').strip()
    if not s:
        return False
    if re.search(r'!\[[^\]]*\]\((https?://[^)]+|data:image/[^)]+)\)', s, flags=re.I):
        return True
    if re.search(r'<img\b[^>]*src=["\'](?:https?://|data:image/)', s, flags=re.I):
        return True
    return False


def _pick_visual_rows_for_reply(reply_text: str, rows: list[dict], requested_count: int = 3) -> list[dict]:
    cleaned = [r for r in (rows or []) if isinstance(r, dict) and str(r.get('url') or '').strip()]
    if not cleaned:
        return []
    picks: list[dict] = []
    seen = set()
    text = str(reply_text or '')

    idxs = []
    for m in re.finditer(r'候选图\s*(\d+)', text, flags=re.I):
        try:
            idxs.append(int(m.group(1)))
        except Exception:
            pass
    if not idxs:
        for m in re.finditer(r'第\s*(\d+)\s*张', text, flags=re.I):
            try:
                idxs.append(int(m.group(1)))
            except Exception:
                pass

    for idx in idxs:
        pos = idx - 1
        if 0 <= pos < len(cleaned):
            row = cleaned[pos]
            u = str(row.get('url') or '').strip()
            if u and u not in seen:
                picks.append(row)
                seen.add(u)

    want = max(1, min(int(requested_count or 3), 10))
    if not picks:
        picks = cleaned[:want]
    elif len(picks) < want:
        for row in cleaned:
            u = str(row.get('url') or '').strip()
            if u and u not in seen:
                picks.append(row)
                seen.add(u)
            if len(picks) >= want:
                break
    return picks[:want]


def _augment_reply_with_visual_images(reply_text: str, visual_ctx: dict | None) -> str:
    """保留兼容入口，但不再由程序后处理强行补图。

    图片候选只作为上下文提供给模型，由模型自行决定是否展示、展示几张、放在正文哪里。
    """
    return str(reply_text or '')


def _plan_image_search_with_model(model: str, messages: list, user_text: str, decision: dict, client_override=None) -> dict:
    """让模型自己理解搜图意图，并产出更适合搜索的 query。

    这里只处理文本，不处理图片本体。
    """
    subject = str((decision or {}).get('subject') or '').strip() or _image_search_query_from_user_text(user_text)
    count = max(1, min(int((decision or {}).get('count') or 5), 10))
    fallback = {"search_query": subject or user_text, "display_subject": subject or user_text, "count": count}
    try:
        convo = []
        for m in (messages or [])[-8:]:
            if not isinstance(m, dict):
                continue
            role = m.get('role')
            if role not in ('system', 'user', 'assistant'):
                continue
            content = _msg_content_text(m.get('content'))
            if content:
                convo.append({"role": role, "content": content[:1200]})
        judge_model = _resolve_aux_model(model, "WEB_SEARCH_PLANNER_MODEL", "gpt-5.4-nano")
        contract_text = ''
        try:
            contract_builder = globals().get('prompt_contract_text')
            if callable(contract_builder):
                contract_text = str(contract_builder('image_search_planner', compact=True) or '').strip()
        except Exception:
            contract_text = ''
        prompt = [
            {"role": "system", "content": ((contract_text + "\n") if contract_text else "") + """图片搜索规划补充约束：
理解用户真实想看的内容，并生成更贴近用户本意、适合搜图的 query。
不要使用死规则，不要机械把用户词替换成固定模板，要根据上下文自行判断。
默认尽量贴近用户原话和当前语境，不要为了“更像搜图词”而主动堆很多风格、摄影、情绪、画质、场景之类修饰。
如果用户没有明确表达电影感、光影、氛围感、背景虚化、特写、高清、壁纸风格等倾向，不要擅自补这些词；但如果用户明确要这种效果，可以自然保留或适度扩写。
search_queries 应该是围绕同一意图的少量自然变体或轻微改写，用于帮助召回，不要通过新增一串华丽修饰词来制造差异。
要求：
- search_query：主搜图词，简短自然，优先保留用户真正关心的主体和必要限定词，可以中英混合，但不要无依据扩写。
- search_queries：可选，给 1 到 3 条不同但仍指向同一主体的搜图词，用来扩大候选图多样性；应是轻微改写、近义表达或顺序调整，避免无意义修饰词堆砌。
- display_subject：面向用户展示的简短主题描述。
"""},
            *convo,
            {"role": "user", "content": f"用户最新问题：{user_text}\n当前视觉决策：{json.dumps(decision or {}, ensure_ascii=False)}"},
        ]
        req = {
            "model": judge_model,
            "messages": prompt,
            "temperature": 0.2,
            "max_tokens": 180,
        }
        contract_format = globals().get('apply_prompt_contract_response_format')
        if callable(contract_format):
            req = contract_format(req, 'image_search_planner')
        else:
            req["response_format"] = {"type": "json_object"}
        req = _apply_completion_thinking_kwargs(req, role="query_generation", model=judge_model, client_override=client_override)
        resp = (client_override or client_gpt).chat.completions.create(**req)
        msg = (((resp.choices or [None])[0] or None).message.content or '').strip()
        obj = _safe_json_loads(msg) or {}
        q = str(obj.get('search_query') or '').strip()
        disp = str(obj.get('display_subject') or '').strip()
        raw_qs = obj.get('search_queries') or []
        if isinstance(raw_qs, str):
            raw_qs = [raw_qs]
        search_queries = []
        seen_q = set()
        for cand in [q, *list(raw_qs or []), subject, user_text]:
            cq = _normalize_search_query(str(cand or '').strip())
            if not cq or cq in seen_q:
                continue
            seen_q.add(cq)
            search_queries.append(cq[:160])
            if len(search_queries) >= max(1, min(int(app_getenv('IMAGE_SEARCH_MAX_QUERIES', '3') or 3), 4)):
                break
        try:
            c = int(obj.get('count') or count)
        except Exception:
            c = count
        c = max(1, min(c, 10))
        return {
            'search_query': (q or fallback['search_query'])[:160],
            'search_queries': search_queries or [(q or fallback['search_query'])[:160]],
            'display_subject': (disp or subject or q or fallback['display_subject'])[:120],
            'count': c,
        }
    except Exception as e:
        app_logger.debug(f"[image_plan] fallback: {type(e).__name__}: {e}")
        return {**fallback, 'search_queries': [fallback['search_query'][:160]]}


def _rank_image_candidates_with_model(model: str, user_text: str, plan: dict, rows: list[dict], client_override=None) -> dict:
    """让模型基于候选图的轻信息自行选图，不读取图片本体。"""
    clean_rows = []
    seen = set()
    for idx, r in enumerate(rows or [], start=1):
        if not isinstance(r, dict):
            continue
        raw_url = _pick_best_image_candidate_url(r)
        if not raw_url or raw_url in seen:
            continue
        seen.add(raw_url)
        title = str(r.get('title') or '').strip()
        source = str(r.get('source') or '').strip()
        thumb = str(r.get('thumbnail') or r.get('thumbnail_src') or '').strip()
        try:
            source_host = (urlparse(source).hostname or '').lower() if source else ''
        except Exception:
            source_host = ''
        try:
            raw_host = (urlparse(raw_url).hostname or '').lower()
        except Exception:
            raw_host = ''
        clean_rows.append({
            'idx': idx,
            'url': raw_url,
            'title': title[:200],
            'source': source[:300],
            'source_host': source_host[:120],
            'raw_host': raw_host[:120],
            'thumbnail': thumb[:300],
        })
    if not clean_rows:
        return {'rows': [], 'intro_text': ''}
    want = int((plan or {}).get('count') or 5)
    if want <= 0:
        want = 5
    fallback_rows = clean_rows[:want]
    display_subject = str((plan or {}).get('display_subject') or '相关').strip() or '相关'
    fallback_intro = ""
    try:
        judge_model = str(model or '').strip() or 'gpt-5-nano-2025-08-07'
        contract_text = ''
        try:
            contract_builder = globals().get('prompt_contract_text')
            if callable(contract_builder):
                contract_text = str(contract_builder('image_candidate_ranker', compact=True) or '').strip()
        except Exception:
            contract_text = ''
        prompt = [
            {"role": "system", "content": ((contract_text + "\n") if contract_text else "") + f"""图片候选选择补充约束：
你会拿到用户问题、搜图规划，以及一组候选图片的轻信息（标题、来源、域名等）。
请自己判断哪些候选最符合用户真正想看的内容。
不要使用机械规则；如果候选本身就不理想，也尽量选出最接近用户意图的一小组。
要求：
- picked_indices 里填候选 idx，数量 1 到 {want}。
- intro_text 可以为空字符串；默认留空，除非用户明确要求你先概括整组图片。
- 如果写 intro_text，只能写 1 到 2 句自然中文，不能用“给你找了几张……”“这组图主要是……”这类固定开场。
- 如果主体是人物、地点、作品、动物、品牌、产品、建筑等，可以顺带做很简短的背景介绍，但不要写成百科。
"""},
            {"role": "user", "content": f"用户问题：{user_text}\n搜图规划：{json.dumps(plan or {}, ensure_ascii=False)}\n候选列表：{json.dumps(clean_rows[:12], ensure_ascii=False)}"},
        ]
        req = {
            "model": judge_model,
            "messages": prompt,
            "temperature": 0.35,
            "max_tokens": 320,
        }
        contract_format = globals().get('apply_prompt_contract_response_format')
        if callable(contract_format):
            req = contract_format(req, 'image_candidate_ranker')
        else:
            req["response_format"] = {"type": "json_object"}
        resp = (client_override or client_gpt).chat.completions.create(**req)
        msg = (((resp.choices or [None])[0] or None).message.content or '').strip()
        obj = _safe_json_loads(msg) or {}
        picked = obj.get('picked_indices') if isinstance(obj.get('picked_indices'), list) else []
        picked_set = []
        seen_idx = set()
        by_idx = {int(r['idx']): r for r in clean_rows}
        for x in picked:
            try:
                xi = int(x)
            except Exception:
                continue
            if xi in by_idx and xi not in seen_idx:
                seen_idx.add(xi)
                picked_set.append(by_idx[xi])
            if len(picked_set) >= want:
                break
        if not picked_set:
            picked_set = fallback_rows
        intro_text = str(obj.get('intro_text') or '').strip() or fallback_intro
        return {'rows': picked_set[:want], 'intro_text': intro_text[:220]}
    except Exception as e:
        app_logger.debug(f"[image_rank] fallback: {type(e).__name__}: {e}")
        return {'rows': fallback_rows, 'intro_text': fallback_intro}


def _has_explicit_image_search_intent(user_text: str) -> bool:
    t = str(user_text or '').strip().lower()
    if not t:
        return False
    strong_patterns = [
        r'(找|搜|发|来|给我|帮我).*?(图|图片|照片|截图|壁纸|海报|外观图|效果图|示意图)',
        r'(图|图片|照片|截图|壁纸|海报|外观图|效果图|示意图).*?(找|搜|发|来|给我|帮我)',
        r'\b(show me|find)\b.*?\b(image|images|photo|photos|picture|pictures|screenshot|screenshots)\b',
        r'\b(image|images|photo|photos|picture|pictures|screenshot|screenshots|wallpaper|poster)\b',
        r'(雷达图|云图|天气图|地图|卫星云图)',
    ]
    return any(re.search(p, t, flags=re.I) for p in strong_patterns)


def _has_explicit_file_delivery_intent(user_text: str) -> bool:
    """Compatibility fallback: only detect very explicit requests for a real downloadable file."""
    t = str(user_text or '').strip().lower()
    if not t:
        return False
    ext_hit = bool(re.search(
        r'\.(py|js|ts|tsx|jsx|html|css|java|c|cc|cpp|cxx|go|rs|php|rb|swift|kt|cs|sql|yaml|yml|xml|json|md|txt|csv|tsv|docx|xlsx|pptx|pdf|sh|bat|ps1|zip)\b',
        t,
        flags=re.I,
    ))
    explicit_delivery = bool(re.search(
        r'(生成|创建|新建|保存|导出|写成|写到|整理成|做成|给我|发我|交付).{0,18}(文件|源码文件|代码文件|脚本|文档|表格|幻灯片|压缩包|附件|下载)',
        t,
        flags=re.I,
    ))
    explicit_file_words = bool(re.search(
        r'(文件名|保存成|另存为|可下载|下载链接|附件)',
        t,
        flags=re.I,
    ))
    english_delivery = bool(re.search(
        r'\b(generate|create|save|export|write|make|give me)\b.{0,24}\b(file|files|script|document|attachment|docx|xlsx|pptx|pdf|zip)\b',
        t,
        flags=re.I,
    ))
    if explicit_delivery or explicit_file_words or english_delivery:
        return True
    if ext_hit and re.search(r'(生成|创建|保存|写|给我|发我|文件|下载|generate|create|save|write|file)', t, flags=re.I):
        return True
    return False


def _prefetch_looks_like_standalone_image_generation(user_text: str = '') -> dict:
    """Compatibility shim: no keyword verdict; model prompt owns routing."""
    return {'hit': False, 'subject': '', 'reason': ''}


def _normalize_primary_delivery(value: str = '') -> str:
    """Normalize the model's turn-level delivery intent.

    This is not a keyword router. It only normalizes the structured answer from
    the soft prefetch model so downstream tools can separate candidate signals
    from executable actions.
    """
    raw = str(value or '').strip().lower()
    aliases = {
        'direct': 'answer', 'direct_answer': 'answer', 'chat': 'answer',
        'web_research': 'web', 'research': 'web',
        'visual': 'image', 'image_generation': 'image', 'text_to_image': 'image',
        'edit_image': 'image_edit', 'image_editing': 'image_edit',
        'generate_file': 'file', 'file_generation': 'file', 'sandbox_files': 'file',
        'edit_file': 'file_edit', 'file_editing': 'file_edit',
        'code': 'file', 'page': 'file', 'document': 'file',
        'multi': 'composite', 'multi_step': 'composite', 'multiple': 'composite',
    }
    raw = aliases.get(raw, raw)
    allowed = {'answer', 'web', 'location', 'weather', 'image', 'image_edit', 'file', 'file_edit', 'composite'}
    return raw if raw in allowed else ''

def _decide_tool_prefetch_once(model: str, messages: list, user_text: str, client_override=None) -> dict:
    """Single soft-routing prefetch for direct answer vs weather / visual / file / web research."""
    user_text = str(user_text or '').strip()
    latest_user_has_images = _latest_user_message_has_images(messages or [])
    subject = _clean_image_subject(user_text) or _image_search_query_from_user_text(user_text)
    count = _extract_requested_image_count(user_text, default=5)
    visual_heuristic = {
        "intent": "none", "subject": subject, "count": count,
        "need_clarify": False, "clarify_question": "", "reason": "", "source": "prefetch_fallback_none"
    }
    out = {
        "route_mode": "direct_answer",
        "route_reason": "默认直答快通道",
        "route_confidence": 0.0,
        "answer_strategy": "fast_direct",
        "strategy_reason": "普通问题优先直接回答",
        "need_external_evidence": False,
        "current_world_risk": "low",
        "upgrade_worth": "low",
        "weather_action": "none",
        "weather_reason": "",
        "location_action": "none",
        "location_reason": "",
        "file_action": "none",
        "file_reason": "",
        "file_delivery_mode": "none",
        "primary_delivery": "answer",
        "route_candidates": {},
        "visual_decision": dict(visual_heuristic),
        "source": "prefetch_fallback_none",
    }

    has_recent_context_images = bool(_find_recent_context_image_urls(messages or [], limit=1))
    existing_image_followup = bool(_looks_like_existing_image_analysis(user_text, messages or []))
    existing_image_analysis_allowed = bool(latest_user_has_images or has_recent_context_images)
    visual_hint = _build_recent_visual_low_priority_hint(messages or [], max_messages=2, max_images_per_message=2, max_chars=520)
    judge_model = _resolve_aux_model(model, 'TOOL_PREFETCH_MODEL', 'gpt-5-nano-2025-08-07')
    try:
        convo = []
        for m in (messages or [])[-8:]:
            if not isinstance(m, dict):
                continue
            role = m.get('role')
            if role not in ('system', 'user', 'assistant'):
                continue
            content = _msg_content_text(m.get('content'))
            if content:
                convo.append({"role": role, "content": content[:1200]})
        try:
            _file_records_fn = globals().get('_file_delivery_existing_file_records')
            _file_records = _file_records_fn(messages or []) if callable(_file_records_fn) else []
            _file_names = [
                str((r or {}).get('filename') or (r or {}).get('saved_filename') or '').strip()
                for r in (_file_records or [])
                if isinstance(r, dict) and str((r or {}).get('filename') or (r or {}).get('saved_filename') or '').strip()
            ]
            if _file_names:
                convo.append({
                    'role': 'system',
                    'content': '当前对话存在可处理文件：' + '、'.join(_file_names[:8]) + '。这些文件只是可用上下文；请根据最新用户请求的最终交付物判断是否需要 sandbox artifact runtime，不要让历史文件覆盖当前目标。'
                })
        except Exception:
            pass
        contract_text = ''
        try:
            contract_builder = globals().get('prompt_contract_text')
            if callable(contract_builder):
                contract_text = str(contract_builder('tool_route_soft_hint', compact=True) or '').strip()
        except Exception:
            contract_text = ''
        judge_prompt = [
            {"role": "system", "content": ((contract_text + "\n") if contract_text else "") + """工具路由软提示补充约束：

目标：判断本轮最该先走哪条能力路径：direct_answer / location / weather / visual / file / web_research。

简洁约束：
- 先判断用户最终想拿到什么：回答、实时资料、位置/天气、图片、现有图片修改、文件/代码交付。
- 最新用户请求优先；历史图片和历史文件只是上下文，不能覆盖当前目标。
- 想拿到图片成品：route_mode=visual，visual_intent=image_mode；纯文本画面需求不需要参考图。
- 想参考或沿用对话已有图生成新图：route_mode=visual，visual_intent=image_mode，primary_delivery=image；本轮没重传图片时可依赖图片索引。
- 想修改已有图片：route_mode=visual，visual_intent=image_mode；需要绑定目标图。
- 想拿到真实文件、代码、新版页面，或明确修改已有文件：route_mode=file，file_action=sandbox_files；后续只进入 sandbox artifact runtime。
- 只想找外部真实图片/照片/图集：visual_intent=image_search。
- 天气/定位只在用户真实询问天气或位置时启用；位置可见性问题用 location/resolve_location，不要把普通实体词当城市。
- 当前事实、最新信息、价格、发布状态、模型/产品版本、名单、推荐、政策、平台格局、需要出处核实时：倾向 web_research，primary_delivery 优先为 web，answer_strategy 优先 research_first。
- 普通解释、写作、翻译、闲聊、稳定知识：direct_answer。
- 不按单个词触发；根据完整语义和交付物选择最小必要工具。
- count 取 1-10。"""},
            *convo,
            {"role": "user", "content": _build_tool_prefetch_visual_user_content(
                messages or [],
                user_text,
                latest_user_has_images=latest_user_has_images,
                has_recent_context_images=has_recent_context_images,
                visual_hint=visual_hint,
                max_images=2,
            )},
        ]
        try:
            judge_messages = _sanitize_messages_for_model(judge_prompt, allow_images=True)
        except Exception:
            judge_messages = judge_prompt
        req = {
            "model": judge_model,
            "messages": judge_messages,
            "temperature": 0,
            "max_tokens": 360,
        }
        contract_format = globals().get('apply_prompt_contract_response_format')
        if callable(contract_format):
            req = contract_format(req, 'tool_route_soft_hint')
        else:
            req["response_format"] = {"type": "json_object"}
        req = _apply_completion_thinking_kwargs(req, role="tool_prefetch", model=judge_model, client_override=client_override)
        client_for_prefetch = client_override or client_gpt
        no_image_judge_messages = None
        try:
            resp = client_for_prefetch.chat.completions.create(**req)
        except Exception as primary_err:
            # Some configured prefetch models may be text-only. Retry without image
            # parts but keep OCR/visual text hints, rather than falling straight to
            # the direct-answer fallback.
            try:
                no_image_judge_messages = _sanitize_messages_for_model(judge_prompt, allow_images=False)
                retry_req = dict(req)
                retry_req["messages"] = no_image_judge_messages
                resp = client_for_prefetch.chat.completions.create(**retry_req)
            except Exception as no_image_err:
                # Some OpenAI-compatible upstreams reject response_format and/or
                # thinking parameters for lightweight planner calls even though the
                # same key/model can answer normal chat. Keep the decision model-led:
                # retry once with a plain chat-completion JSON instruction, no image
                # parts, no response_format, and no thinking extras.
                try:
                    if no_image_judge_messages is None:
                        no_image_judge_messages = _sanitize_messages_for_model(judge_prompt, allow_images=False)
                    compat_req = {
                        "model": judge_model,
                        "messages": no_image_judge_messages,
                        "temperature": 0,
                        "max_tokens": 360,
                    }
                    resp = client_for_prefetch.chat.completions.create(**compat_req)
                    try:
                        app_logger.warning(
                            "[tool_prefetch_decision] compat_plain_retry_ok model=%s primary_err=%s:%s no_image_err=%s:%s",
                            judge_model,
                            type(primary_err).__name__, str(primary_err)[:180],
                            type(no_image_err).__name__, str(no_image_err)[:180],
                        )
                    except Exception:
                        pass
                except Exception as compat_err:
                    try:
                        app_logger.warning(
                            "[tool_prefetch_decision] compat_plain_retry_failed model=%s primary_err=%s:%s no_image_err=%s:%s compat_err=%s:%s",
                            judge_model,
                            type(primary_err).__name__, str(primary_err)[:180],
                            type(no_image_err).__name__, str(no_image_err)[:180],
                            type(compat_err).__name__, str(compat_err)[:180],
                        )
                    except Exception:
                        pass
                    raise compat_err
        msg = (((resp.choices or [None])[0] or None).message.content or '').strip()
        parser = globals().get('_safe_parse_json')
        obj = _safe_json_loads(msg) or (parser(msg) if callable(parser) else None) or {}
        explicit_image = _has_explicit_image_search_intent(user_text)
        standalone_image_hint = {'hit': False, 'subject': '', 'reason': ''}
        primary_delivery = _normalize_primary_delivery(obj.get('primary_delivery') or obj.get('final_deliverable') or obj.get('delivery_intent') or '')
        raw_candidates = obj.get('route_candidates') if isinstance(obj.get('route_candidates'), dict) else {}
        route_candidates = {}
        for _k, _v in (raw_candidates or {}).items():
            _kk = str(_k or '').strip().lower()
            _vv = str(_v or '').strip().lower()
            if _kk and _vv in {'none', 'low', 'medium', 'high'}:
                route_candidates[_kk[:40]] = _vv
        route_mode = str(obj.get('route_mode') or '').strip().lower()
        if route_mode not in ('direct_answer', 'location', 'weather', 'visual', 'file', 'web_research'):
            route_mode = 'direct_answer'
        route_reason = str(obj.get('route_reason') or obj.get('reason') or '')[:120]
        answer_strategy = str(obj.get('answer_strategy') or '').strip().lower()
        if answer_strategy not in ('fast_direct', 'direct_with_caveat', 'quick_then_verify', 'research_first', 'tool_first'):
            answer_strategy = 'fast_direct' if route_mode == 'direct_answer' else ('tool_first' if route_mode in ('location', 'weather', 'visual', 'file') else 'research_first')
        strategy_reason = str(obj.get('strategy_reason') or '')[:120]
        try:
            route_confidence = float(obj.get('route_confidence') or 0.0)
        except Exception:
            route_confidence = 0.0
        route_confidence = max(0.0, min(route_confidence, 1.0))
        visual_intent = str(obj.get('visual_intent') or '').strip().lower()
        # Backward compatible: older prompts/models may still return detailed image intents.
        # Tool prefetch only keeps the coarse image lane; the image-mode planner decides details.
        if visual_intent in ('existing_image_analysis', 'image_generation', 'image_edit', 'reference_generate', 'reference_edit', 'variation'):
            visual_intent = 'image_mode'
        if visual_intent not in ('image_mode', 'image_search', 'none'):
            visual_intent = 'none'
        if visual_intent == 'none' and existing_image_followup and existing_image_analysis_allowed:
            visual_intent = 'image_mode'
            if route_mode == 'direct_answer':
                route_mode = 'visual'
                route_reason = route_reason or '用户在追问最近图片里的具体内容'
            if answer_strategy not in ('tool_first', 'research_first'):
                answer_strategy = 'tool_first'
            if route_confidence <= 0.0:
                route_confidence = 0.72
        if bool((standalone_image_hint or {}).get('hit')) and route_mode in {'direct_answer', 'file', 'visual'}:
            route_mode = 'visual'
            visual_intent = 'image_mode'
            route_reason = '独立画面生成请求，按文生图处理'
            answer_strategy = 'tool_first'
            route_confidence = max(route_confidence, 0.92)
        if visual_intent == 'image_mode' and primary_delivery in {'', 'answer'} and (
            route_mode == 'visual'
            or str((route_candidates or {}).get('image') or '').strip().lower() in {'medium', 'high'}
            or latest_user_has_images
            or has_recent_context_images
        ):
            primary_delivery = 'image'
        location_action = str(obj.get('location_action') or '').strip().lower()
        if location_action not in ('resolve_location', 'none'):
            location_action = 'none'
        weather_action = str(obj.get('weather_action') or '').strip().lower()
        if weather_action not in ('call_weather', 'none'):
            weather_action = 'none'
        file_action = str(obj.get('file_action') or '').strip().lower()
        if file_action not in ('sandbox_files', 'none'):
            file_action = 'none'

        # Turn-level delivery lock. Candidate signals may coexist, but executable
        # actions are authorized only by the primary delivery selected by the model.
        if primary_delivery in {'image', 'image_edit'}:
            route_mode = 'visual'
            visual_intent = 'image_mode'
            file_action = 'none'
            answer_strategy = 'tool_first'
            route_confidence = max(route_confidence, 0.82)
        elif primary_delivery in {'file', 'file_edit'}:
            route_mode = 'file'
            file_action = 'sandbox_files'
            answer_strategy = 'tool_first'
            route_confidence = max(route_confidence, 0.82)
        elif primary_delivery == 'web':
            route_mode = 'web_research'
            file_action = 'none'
            answer_strategy = 'research_first'
        elif primary_delivery == 'weather':
            route_mode = 'weather'
            file_action = 'none'
            weather_action = 'call_weather'
            answer_strategy = 'tool_first'
        elif primary_delivery == 'location':
            route_mode = 'location'
            file_action = 'none'
            location_action = 'resolve_location'
            answer_strategy = 'tool_first'
        elif primary_delivery == 'answer':
            route_mode = 'direct_answer'
            file_action = 'none'
            answer_strategy = 'fast_direct' if answer_strategy not in {'direct_with_caveat', 'quick_then_verify'} else answer_strategy
        elif primary_delivery == 'composite':
            # Composite is the only state that may keep more than one executable
            # intent, and the model must justify it in route_reason.
            pass
        if bool((standalone_image_hint or {}).get('hit')):
            file_action = 'none'
        need_external_evidence = bool(obj.get('need_external_evidence'))
        current_world_risk = str(obj.get('current_world_risk') or '').strip().lower()
        if current_world_risk not in ('low', 'medium', 'high'):
            current_world_risk = 'high' if route_mode == 'web_research' else 'low'
        upgrade_worth = str(obj.get('upgrade_worth') or '').strip().lower()
        if upgrade_worth not in ('low', 'medium', 'high'):
            upgrade_worth = 'high' if route_mode in ('location', 'weather', 'visual', 'file', 'web_research') else 'low'
        file_reason = str(obj.get('file_reason') or '')[:120]
        file_delivery_mode = _normalize_file_delivery_mode(
            obj.get('file_delivery_mode'),
            user_text=user_text,
            info=_file_delivery_soft_context(messages or []),
            default='single_file',
        )
        if file_action == 'none':
            file_delivery_mode = 'none'
        if route_mode == 'visual' and visual_intent == 'none' and explicit_image:
            visual_intent = 'image_search'
        if route_mode == 'direct_answer' and route_confidence < 0.55:
            route_reason = route_reason or '低置信时保守走直答快通道'
        if route_mode == 'direct_answer' and answer_strategy not in ('fast_direct', 'direct_with_caveat', 'quick_then_verify'):
            answer_strategy = 'fast_direct'
        if route_mode in ('location', 'weather', 'visual', 'file') and answer_strategy not in ('tool_first', 'research_first'):
            answer_strategy = 'tool_first'
        if route_mode == 'web_research' and answer_strategy not in ('research_first', 'quick_then_verify'):
            answer_strategy = 'research_first'
        if route_mode == 'web_research':
            need_external_evidence = True
            if current_world_risk == 'low':
                current_world_risk = 'medium'
            if upgrade_worth == 'low':
                upgrade_worth = 'medium'
        try:
            parsed_count = int(obj.get('count') or count)
        except Exception:
            parsed_count = count
        parsed_count = max(1, min(parsed_count, 10))
        visual_subject_raw = str(obj.get('subject') or '').strip()
        if bool((standalone_image_hint or {}).get('hit')) and not visual_subject_raw:
            visual_subject_raw = str((standalone_image_hint or {}).get('subject') or user_text).strip()
        if visual_intent not in ('image_mode',) and not visual_subject_raw:
            visual_subject_raw = subject
        decision_out = {
            'route_mode': route_mode,
            'route_reason': route_reason,
            'route_confidence': route_confidence,
            'answer_strategy': answer_strategy,
            'strategy_reason': strategy_reason,
            'need_external_evidence': need_external_evidence,
            'current_world_risk': current_world_risk,
            'upgrade_worth': upgrade_worth,
            'location_action': location_action,
            'location_reason': str(obj.get('location_reason') or '')[:120],
            'weather_action': weather_action,
            'weather_reason': str(obj.get('weather_reason') or '')[:120],
            'file_action': file_action,
            'file_reason': file_reason,
            'file_delivery_mode': file_delivery_mode,
            'primary_delivery': primary_delivery or ({'visual': 'image', 'file': 'file', 'web_research': 'web', 'weather': 'weather', 'location': 'location'}.get(route_mode, 'answer')),
            'route_candidates': route_candidates,
            'visual_decision': {
                'intent': visual_intent,
                'subject': _clean_image_subject(visual_subject_raw)[:120],
                'count': parsed_count,
                'need_clarify': bool(obj.get('need_clarify')),
                'clarify_question': str(obj.get('clarify_question') or '')[:160],
                'reason': str(obj.get('reason') or '')[:120],
                'source': 'model',
            },
            'source': 'model',
        }
        activation_builder = globals().get('skill_activation_plan')
        if callable(activation_builder):
            try:
                decision_out['skill_activation_plan'] = activation_builder('chat_completions', decision_out)
            except Exception:
                pass
        tracer = globals().get('skill_trace_span')
        if callable(tracer):
            try:
                active_groups = []
                if isinstance(decision_out.get('skill_activation_plan'), dict):
                    active_groups = list(decision_out.get('skill_activation_plan', {}).get('active_groups') or [])
                tracer('skill_activation_selected', endpoint_mode='chat_completions', status='ok', metadata={
                    'contract': 'tool_route_soft_hint',
                    'route_mode': route_mode,
                    'primary_delivery': decision_out.get('primary_delivery'),
                    'active_groups': active_groups,
                })
            except Exception:
                pass
        return decision_out
    except Exception as e:
        app_logger.debug(f"[tool_prefetch_decision] fallback to heuristic: {type(e).__name__}: {e}")
        activation_builder = globals().get('skill_activation_plan')
        if callable(activation_builder):
            try:
                out['skill_activation_plan'] = activation_builder('chat_completions', out)
            except Exception:
                pass
        return out

def _decide_visual_request_once(model: str, messages: list, user_text: str, client_override=None) -> dict:
    """Backward-compatible visual decision wrapper."""
    decision = _decide_tool_prefetch_once(model, messages or [], user_text, client_override=client_override)
    visual = (decision or {}).get('visual_decision') or {}
    if not isinstance(visual, dict):
        visual = {}
    subject = _clean_image_subject(user_text) or _image_search_query_from_user_text(user_text)
    count = _extract_requested_image_count(user_text, default=5)
    try:
        count = max(1, min(int(visual.get('count') or count), 10))
    except Exception:
        count = max(1, min(int(count or 5), 10))
    return {
        "intent": str(visual.get('intent') or 'none'),
        "subject": str(visual.get('subject') or subject)[:120],
        "count": count,
        "need_clarify": bool(visual.get('need_clarify')),
        "clarify_question": str(visual.get('clarify_question') or '')[:160],
        "reason": str(visual.get('reason') or '')[:120],
        "source": str(visual.get('source') or (decision or {}).get('source') or 'prefetch_wrapper'),
    }


def _search_images_multi(queries: list[str], k: int = 12, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
    """Unified image-search entry used by the visual pipeline.

    Default flow: SearxNG first, and when effective image results are too few,
    supplement with Serper instead of replacing the existing good rows.
    """
    clean_queries = [str(q or '').strip() for q in (queries or []) if str(q or '').strip()]
    if not clean_queries:
        return []

    providers = _provider_chain(
        app_getenv('IMAGE_SEARCH_PROVIDER', 'searxng'),
        app_getenv('IMAGE_SEARCH_FALLBACK_PROVIDER', 'serper'),
        kind='image',
    )
    merged = []
    subject = clean_queries[0]
    min_effective = _cfg_int('IMAGE_SEARCH_MIN_EFFECTIVE_RESULTS', 5)
    target_results = min(max(1, int(k or 12)), _cfg_int('IMAGE_SEARCH_TARGET_RESULTS', 8))
    last_provider = providers[-1] if providers else None

    for provider in providers:
        try:
            rows = _search_images_with_provider(provider, clean_queries, k=max(int(k or 12), target_results), timeout=timeout, user_text=user_text or subject)
        except Exception as e:
            app_logger.warning('[IMAGE_SEARCH] provider=%s failed queries=%s err=%s: %s', provider, clean_queries[:2], type(e).__name__, e)
            continue
        if rows:
            merged = _merge_unique_image_rows(merged, rows)
            merged = _rerank_image_results(merged, user_text or subject, subject=subject, limit=max(int(k or 12), target_results))
        effective_hits = _effective_image_result_count(merged)
        enough_for_stop = effective_hits >= min_effective and len(merged) >= target_results
        app_logger.info('[IMAGE_SEARCH] provider=%s hits=%s effective=%s target=%s stop=%s', provider, len(merged), effective_hits, target_results, enough_for_stop or provider == last_provider)
        if enough_for_stop or provider == last_provider:
            break

    return merged[:max(1, int(k or 12))]


def _materialize_visual_context_from_decision(model: str, messages: list, user_text: str, decision: dict | None, client_override=None) -> dict | None:
    decision = dict(decision or {})
    print("\n===== 工具预判日志 =====")
    print("用户问题:", user_text)
    print("预判结果:", decision)
    print("======================\n")

    intent = str(decision.get('intent') or 'none')
    if intent == 'none':
        return None
    if intent == 'existing_image_analysis':
        return _build_existing_image_analysis_visual_ctx(
            messages or [],
            user_text=user_text,
            model=model,
            client_override=client_override,
            decision=decision,
            limit=4,
        )
    if decision.get('need_clarify') and str(decision.get('clarify_question') or '').strip():
        return {"intent": "clarify", "text": str(decision.get('clarify_question')).strip(), "decision": decision}

    plan = _plan_image_search_with_model(model, messages or [], user_text, decision, client_override=client_override)
    q = str((plan or {}).get('search_query') or '').strip() or str(decision.get('subject') or '').strip() or _image_search_query_from_user_text(user_text)
    if not q:
        return None

    want = max(1, min(int((plan or {}).get('count') or decision.get('count') or 5), 10))
    candidate_k = max(want * 8, 24)
    query_list = [str(x or '').strip() for x in ((plan or {}).get('search_queries') or []) if str(x or '').strip()]
    if q and q not in query_list:
        query_list.insert(0, q)
    elif not query_list and q:
        query_list = [q]
    rows = _search_images_multi(query_list[:max(1, _cfg_int('IMAGE_SEARCH_MAX_QUERIES', 4))], k=candidate_k)
    return {
        "intent": "image_search",
        "decision": decision,
        "plan": plan or {"search_query": q, "count": want, "display_subject": str(decision.get('subject') or q).strip()},
        "rows": rows or [],
    }


def _prefetch_visual_context(model: str, messages: list, user_text: str, client_override=None) -> dict | None:
    decision = _decide_visual_request_once(model, messages or [], user_text, client_override=client_override)
    return _materialize_visual_context_from_decision(model, messages or [], user_text, decision, client_override=client_override)


def _verify_single_reply_image(row: dict, subject: str = '', request_timeout: float = 2.6, fallback_timeout: float = 4.5) -> dict | None:
    """Validate one candidate image and normalize it for the image-reply payload.

    This is intentionally small and only fills the gap for the current pipeline:
    keep the original selection flow, verify that the chosen image can actually be
    fetched/proxied, then return the fields expected by the front end.
    """
    if not isinstance(row, dict):
        return None

    raw_url = _pick_best_image_candidate_url(row)
    if not raw_url:
        return None

    normalized = _norm_image_result_url_for_dedup(raw_url)
    if not normalized:
        return None

    source_url = str(row.get('source') or row.get('source_url') or '').strip()
    title = str(row.get('title') or row.get('alt') or row.get('caption') or subject or '').strip()

    verified_ok = False
    if raw_url.startswith('data:image/'):
        verified_ok = True
    elif raw_url.startswith('http://') or raw_url.startswith('https://'):
        try:
            host = (urlparse(raw_url).hostname or '').lower().strip('.')
            if host and _is_gated_remote_image_host(host):
                return None
            probe = _remote_image_to_data_url(raw_url, request_timeout=request_timeout, fallback_timeout=fallback_timeout)
            verified_ok = bool(probe and probe.startswith('data:image/'))
        except Exception:
            verified_ok = False
    else:
        local_fp = _same_origin_local_path_from_url(raw_url)
        verified_ok = bool(local_fp and os.path.isfile(local_fp))

    if not verified_ok:
        return None

    proxy_url = ''
    if raw_url.startswith('http://') or raw_url.startswith('https://'):
        if not _should_bypass_remote_image_proxy(raw_url):
            proxy_url = '/api3/remote-image?url=' + quote(raw_url, safe='')

    out = dict(row)
    out.update({
        'url': raw_url,
        'raw_url': raw_url,
        'rawUrl': raw_url,
        # 搜图结果应优先作为浏览器直连图片展示；proxy 只作为备用地址，
        # 不能被前端误判成生图 mirror/后台拉回队列。
        'proxy_url': proxy_url,
        'source_url': source_url,
        'source_type': 'image_search',
        'sourceType': 'image_search',
        'operation': 'image_search',
        'intent': 'image_search',
        'alt': title,
        'caption': title,
        '_norm_url': normalized,
    })
    return out


def _select_verified_reply_images(rows: list[dict], requested_count: int, subject: str = '') -> list[dict]:
    clean_rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not clean_rows or requested_count <= 0:
        return []

    candidate_limit = max(requested_count * 10, 28)
    max_candidates = max(12, min(int(app_getenv('REPLY_IMAGE_MAX_CANDIDATES', str(candidate_limit)) or candidate_limit), 72))
    max_workers = max(1, min(int(app_getenv('REPLY_IMAGE_VERIFY_WORKERS', '8') or 8), 12))
    max_per_host = max(1, min(int(app_getenv('REPLY_IMAGE_MAX_PER_HOST', '6') or 6), 8))
    request_timeout = max(1.0, float(app_getenv('REPLY_IMAGE_REQUEST_TIMEOUT', '2.6') or 2.6))
    fallback_timeout = max(request_timeout, float(app_getenv('REPLY_IMAGE_FALLBACK_TIMEOUT', '4.5') or 4.5))
    total_budget = max(2.0, float(app_getenv('REPLY_IMAGE_TOTAL_BUDGET', '9') or 9))

    primary_rows = []
    overflow_rows = []
    blocked_rows = []
    seen = set()
    host_counts: dict[str, int] = {}
    for row in clean_rows:
        raw_url = _pick_best_image_candidate_url(row)
        if not raw_url or raw_url in seen:
            continue
        seen.add(raw_url)
        host = _fetch_host_key(raw_url)
        host_penalty = _remote_image_host_score_adjust(raw_url)
        if host:
            cur = int(host_counts.get(host, 0) or 0)
            target = blocked_rows if host_penalty <= -2.0 else (primary_rows if cur < max_per_host else overflow_rows)
            if target is primary_rows:
                host_counts[host] = cur + 1
            target.append(row)
        else:
            primary_rows.append(row)
        if len(primary_rows) >= max_candidates:
            break

    deduped = list(primary_rows)
    if len(deduped) < max_candidates:
        for bucket in (overflow_rows, blocked_rows):
            for row in bucket:
                deduped.append(row)
                if len(deduped) >= max_candidates:
                    break
            if len(deduped) >= max_candidates:
                break
    if not deduped:
        return []

    if len(deduped) > 1:
        preferred = []
        extras = []
        used_hosts = set()
        for row in deduped:
            host = _fetch_host_key(_pick_best_image_candidate_url(row))
            if host and host not in used_hosts:
                used_hosts.add(host)
                preferred.append(row)
            else:
                extras.append(row)
        deduped = preferred + extras

    stage1_target = min(len(deduped), max(requested_count * 2, requested_count + 3, 8))
    stage1_rows = deduped[:stage1_target]
    stage2_rows = deduped[stage1_target:]
    deadline = time.time() + total_budget
    picked: list[dict] = []
    picked_urls = set()

    def _run_stage(stage_rows: list[dict], stage_request_timeout: float, stage_fallback_timeout: float, stage_need: int):
        nonlocal picked, picked_urls
        if not stage_rows or stage_need <= 0:
            return
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        stage_timeout = max(0.1, min(remaining, total_budget))
        ex = ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(stage_rows))))
        future_map = {
            ex.submit(
                _verify_single_reply_image,
                row,
                subject,
                request_timeout=stage_request_timeout,
                fallback_timeout=stage_fallback_timeout,
            ): row
            for row in stage_rows
        }
        try:
            for fut in as_completed(future_map, timeout=stage_timeout):
                if time.time() >= deadline:
                    break
                try:
                    fut_budget = max(0.1, deadline - time.time())
                    item = fut.result(timeout=fut_budget)
                except Exception:
                    item = None
                if not item:
                    continue
                final_url = str(item.get('url') or '').strip()
                if not final_url or final_url in picked_urls:
                    continue
                picked_urls.add(final_url)
                picked.append(item)
                if len(picked) >= stage_need:
                    break
        except Exception:
            pass
        finally:
            for fut in future_map:
                if not fut.done():
                    fut.cancel()
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                ex.shutdown(wait=False)

    _run_stage(
        stage1_rows,
        stage_request_timeout=request_timeout,
        stage_fallback_timeout=max(request_timeout, min(fallback_timeout, request_timeout + 1.2)),
        stage_need=requested_count,
    )
    if len(picked) < requested_count:
        _run_stage(
            stage2_rows,
            stage_request_timeout=max(request_timeout, request_timeout + 0.5),
            stage_fallback_timeout=max(fallback_timeout, request_timeout + 1.8),
            stage_need=requested_count,
        )
    app_logger.info('[reply_image_pick] requested=%s clean=%s primary=%s overflow=%s blocked=%s picked=%s subject=%s', requested_count, len(clean_rows), len(primary_rows), len(overflow_rows), len(blocked_rows), len(picked), (subject or '')[:80])
    return picked[:requested_count]

def _visual_ctx_to_image_reply_payload(visual_ctx: dict | None) -> dict | None:
    """Build a lightweight image reply payload for direct image-search responses.

    This bypasses the final LLM stage for explicit image-search asks, so the UI can
    render images immediately without waiting for another model round.
    """
    if not isinstance(visual_ctx, dict) or visual_ctx.get('intent') != 'image_search':
        return None

    if bool(visual_ctx.get('_image_reply_payload_ready')):
        cached_payload = visual_ctx.get('_image_reply_payload')
        return cached_payload if isinstance(cached_payload, dict) else None

    decision = visual_ctx.get('decision') or {}
    plan = visual_ctx.get('plan') or {}
    rows = [r for r in (visual_ctx.get('rows') or []) if isinstance(r, dict)]
    subject = str(plan.get('display_subject') or decision.get('subject') or '').strip()
    requested_count = max(1, min(int(plan.get('count') or decision.get('count') or 5), 10))

    images = _select_verified_reply_images(rows, requested_count, subject=subject)
    payload = None
    if images:
        text = ""
        clean_images = []
        for item in images:
            if not isinstance(item, dict):
                continue
            obj = dict(item)
            obj['source_type'] = 'image_search'
            obj['sourceType'] = 'image_search'
            obj['operation'] = 'image_search'
            obj['intent'] = 'image_search'
            clean_images.append(obj)
        payload = {
            '_kind': 'image_reply',
            'source': 'image_search',
            'visual_intent': 'image_search',
            'text': text,
            'images': clean_images,
            'subject': subject,
            'count': len(clean_images),
        }

    visual_ctx['_image_reply_payload'] = payload
    visual_ctx['_image_reply_payload_ready'] = True
    return payload


def _inject_visual_context_messages(messages: list, visual_ctx: dict | None) -> list:
    out = list(messages or [])
    if not visual_ctx:
        return out
    if visual_ctx.get('intent') == 'existing_image_analysis':
        out.append({
            "role": "system",
            "_kind": "sandbox_visual_required",
            "content": (
                "已有会话图片分析不能通过旧的 image_url 直挂方式进入最终模型。"
                "必须先按 image_id 调用 analyze_existing_image，把选中的用户/历史/助手图片导入 /mnt/data/chat_images，"
                "再由 sandbox_analyze_file_images 在当前 API 通道内产出沙盒视觉证据；"
                "Chat 通道使用沙盒分析文本，Responses 通道使用沙盒生成的官方 input_image。"
                "如果本轮没有执行该工具，就不要声称已经看到了图片细节。"
            )
        })
        return out

    if visual_ctx.get('intent') != 'image_search':
        return out

    image_reply_payload = _visual_ctx_to_image_reply_payload(visual_ctx)
    image_items = [img for img in ((image_reply_payload or {}).get('images') or []) if isinstance(img, dict)]
    if not image_items:
        return out

    decision = visual_ctx.get('decision') or {}
    subject = str((image_reply_payload or {}).get('subject') or decision.get('subject') or '').strip()
    payload_images = []
    for img in image_items:
        raw_url = str(img.get("raw_url") or img.get("rawUrl") or img.get("url") or '').strip()
        if not raw_url:
            continue
        source_url = str(img.get("source_url") or '').strip()
        payload_images.append({
            "url": raw_url,
            "title": str(img.get("alt") or img.get("caption") or '').strip(),
            "source_host": ((urlparse(source_url).hostname or '').lower() if source_url else ''),
        })
    if not payload_images:
        return out

    actual_count = len(payload_images)
    text_payload_images = []
    for idx, img in enumerate(payload_images, start=1):
        text_payload_images.append({
            "index": idx,
            "title": str(img.get("title") or '').strip(),
            "source_host": str(img.get("source_host") or '').strip(),
        })
    payload = {
        "subject": subject,
        "requested_count": actual_count,
        "candidate_count": actual_count,
        "ui_delivery": "structured_image_reply",
        "output_policy": "do not output markdown images, raw image urls, or source link lists",
        "images": text_payload_images,
    }

    out.append({
        "role": "system",
        "content": (
            "你已经拿到一组经过检索和筛选后、与用户当前问题直接相关的网络图片。"
            "这些图片默认视为本轮问答已经找到的正确图片依据，除非图片内容本身与用户问题明显不符，否则不要再把它们当成待确认的候选线索。"
            "先基于这些图片正常理解并直接回答用户真正的问题，不要先写空泛的找图导语。"
            "除非用户明确要你介绍整组图片，否则不要用‘给你找了几张……’‘这组图主要是……’‘画面里能看到……’这类固定开场。"
            "如果用户问的是图里是谁、有哪些人、属于哪个队、在做什么、有什么区别、长什么样、位置关系等，优先把这些图片当作主要依据直接作答，不要割裂成‘先介绍图片，再回答问题’。"
            "只有当图片能明显帮助表达，或用户明确在要图、选图、比较图时，才从已筛选结果里挑少量最相关的图片自然插入正文。"
            "如果这次更适合纯文字回答，就不要为了凑图而贴图。"
            "前端可能已经先把这批图片展示给用户了；除非用户明确要求你再次贴图，否则正文不要再重复输出 markdown 图片、整组图片或图片导语。"
            "如果要展示图片，只能使用这批已筛选图片，并自然地放在正文里，不要在回答末尾机械追加整组图片。"
            "不要输出这些图片的原始网页链接、博客详情页链接或‘查看图片’之类的占位文字；展示图片时直接用图片本身。"
            "不要输出 JSON，不要解释你在做图片决策。"
        )
    })
    out.append({
        "role": "system",
        "content": f"<image_search_result>{json.dumps(payload, ensure_ascii=False)}</image_search_result>"
    })

    mm = [{
        "type": "text",
        "text": (
            f"下面是针对当前问题已筛选出的相关图片，主题是“{subject or '相关内容'}”。"
            "请直接查看这些图片内容，并把它们作为回答当前问题的主要视觉依据。"
        )
    }]
    for idx, img in enumerate(payload_images, start=1):
        label_parts = [f"图片{idx}"]
        if img.get('title'):
            label_parts.append(f"标题：{str(img['title'])[:120]}")
        if img.get('source_host'):
            label_parts.append(f"来源站点：{str(img['source_host'])[:120]}")
        mm.append({"type": "text", "text": "；".join(label_parts)})
        mm.append({"type": "image_url", "image_url": {"url": img['url']}})
    out.append({"role": "user", "content": mm})
    return out
