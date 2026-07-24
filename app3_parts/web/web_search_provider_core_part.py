# keyword extraction, search intent, result rerank, upstream errors, and SearxNG provider.

_KW_STOP = {
    # EN
    "the","and","for","with","from","this","that","today","now","what","which","when","where","why","how",
    "a","an","to","of","in","on","at","by","or","is","are","was","were","be","as","it","we","you",
    # ZH (very small set)
    "请问","麻烦","帮我","可以","一下","如何","为什么","怎么","怎么样","是什么","哪些","给我","告诉",
}

def _extract_keywords_simple(text: str, max_n: int = 8) -> list[str]:
    """非常轻量的关键词提取（不依赖模型/第三方库）。
    目标：
    - 更像搜索词：去掉礼貌语/停用词
    - 保留：数字、币种、品牌/产品名、专有名词
    """
    s = (text or "").strip()
    if not s:
        return []
    # remove urls
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    # 1) English words / numbers / CJK chunks
    raw = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{1,40}|\d+(?:\.\d+)?|[\u4e00-\u9fff]{2,8}", s)
    toks = []
    for w in raw:
        wl = w.lower()
        if wl in _KW_STOP:
            continue
        if len(w) == 1 and not w.isdigit():
            continue
        toks.append(w)

    # 2) Split long CJK token into 3-grams (helps for long strings)
    zh = []
    for w in toks:
        if re.search(r"[\u4e00-\u9fff]", w) and len(w) >= 7:
            for i in range(0, min(len(w)-2, 12), 3):
                zh.append(w[i:i+3])
        else:
            zh.append(w)

    # 3) Prefer tokens with digits/currency or longer length
    def _score(w: str) -> tuple[int,int]:
        has_num = 1 if re.search(r"\d", w) else 0
        has_money = 1 if re.search(r"(?:￥|¥|usd|twd|nt\$|rmb|cny)", w, re.I) else 0
        return (has_money*3 + has_num*2, len(w))

    # stable dedupe
    seen = set()
    uniq = []
    for w in zh:
        k = w.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(w)
    uniq.sort(key=_score, reverse=True)

    top = set([w.lower() for w in uniq[:max(6, max_n*2)]])
    out = []
    out_seen = set()
    for w in zh:
        wl = w.lower()
        if wl in top and wl not in out_seen:
            out.append(w)
            out_seen.add(wl)
        if len(out) >= max_n:
            break
    return out[:max_n]
def _fast_queries(user_text: str, user_geo: dict | None = None) -> list[str]:
    """不调用模型的快速 query 生成：够用、便宜、快。"""
    t = _norm_text(user_text, 180)
    if not t:
        return []
    # 更“关键词化”的 query：减少无关词，提升命中率
    kw = _extract_keywords_simple(t, max_n=8)
    if kw:
        t2 = " ".join(kw)
        if len(t2) >= 6:
            t = t2

    # 如果带城市/地点词，直接用原句；否则可附加粗定位（坐标）提示
    geo = _coarse_geo_key(user_geo)
    if geo and ("天气" in t or "weather" in t.lower()):
        return [f"{t} {geo}"]
    return [t]


def _search_planner_context_lines(history: list[dict] | None = None, limit: int = 8) -> list[str]:
    lines: list[str] = []
    for m in (history or [])[-max(1, int(limit)):]:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        # 搜索词规划只参考真实对话内容，尽量避开系统提示对 query 的污染。
        if role not in ("user", "assistant"):
            continue
        if role == "assistant" and m.get("_kind") == "web":
            continue
        try:
            content = _message_to_text_for_budget(m, include_images=False, include_image_text=False)
        except Exception:
            content = ''
        if not content:
            content = _msg_content_text(m.get("content")).strip()
            if role == 'user':
                content = _combine_message_text_and_quote(content, _message_quote_text(m))
        visual_hint = _build_visual_low_priority_hint_for_message(m, max_images=1, max_chars=120)
        if visual_hint:
            content = (content + '\n' if content else '') + f'[visual_low_priority] {visual_hint}'
        if not content:
            continue
        content = _normalize_search_planner_context_text(content, max_len=320)
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return lines

def _should_use_llm_search_planner(user_text: str, history: list[dict] | None = None) -> bool:
    t = str(user_text or '').strip()
    if not t:
        return False
    tl = t.lower()
    if len(t) <= 2:
        return True
    pronoun_patterns = [
        r"(?:介绍|说说|讲讲|聊聊|查查|查下|搜下|搜搜|看下|看看).{0,8}(她|他|它|这个人|这个女生|这个男生|这个博主|这个作者|这位|那位)",
        r"^(她|他|它|这位|那位|这个人|这个女生|这个男生|这个博主|这个作者)",
        r"(她|他|它|这位|那位|这个人|这个女生|这个男生|这个博主|这个作者).{0,8}(是谁|资料|简介|信息|情况)",
    ]
    if any(re.search(p, t, flags=re.I) for p in pronoun_patterns):
        return True
    info_kw = ["基本信息", "简介", "介绍", "资料", "信息", "是谁", "什么来头", "背景", "职业", "身份"]
    if any(k in t for k in info_kw) and not _extract_urls(t):
        return True
    if len(_search_planner_context_lines(history, limit=6)) >= 2 and any(k in tl for k in ["她", "他", "this person", "who is she", "who is he"]):
        return True
    return False


# ====== Web Search (SearxNG JSON) ======

def _classify_search_intent(user_text: str) -> str:
    t = str(user_text or '').lower()
    official_kw = [
        '参数', '规格', '配置', '价格', '官网', '官方', '发布日期', '支持', '兼容', '政策', '文档', '下载',
        'spec', 'specs', 'price', 'pricing', 'support', 'download', 'docs', 'documentation', 'official'
    ]
    review_kw = [
        '评测', '体验', '好不好', '值得买吗', '优缺点', '怎么样', 'review', 'hands-on', 'vs', 'comparison', 'compare'
    ]
    visual_kw = [
        '图片', '照片', '截图', '界面', '长什么样', '长啥样', '外观', '样子', '样貌', 'show me', 'image', 'photo', 'screenshot'
    ]
    if any(k in t for k in official_kw):
        return 'official'
    if any(k in t for k in review_kw):
        return 'review'
    if any(k in t for k in visual_kw):
        return 'visual'
    return 'general'


def _search_has_any_keyword(text: str, keywords: list[str]) -> bool:
    t = str(text or '').lower()
    return any(k in t for k in (keywords or []))


def _is_person_visual_query(query_text: str) -> bool:
    person_visual_kw = [
        '人', '人物', '是谁', '照片', '图片', '长相', '长什么样', '长啥样', '样子', '样貌', '外观',
        '博主', 'up主', 'up', '主播', '账号', '主页', '作者', 'cos', 'coser', '网红', '明星',
        '头像', '壁纸', '截图', '视频', '短视频', '抖音', 'b站', 'bilibili', 'douyin',
        'photo', 'image', 'picture', 'screenshot', 'profile', 'account', 'creator', 'streamer'
    ]
    return _search_has_any_keyword(query_text, person_visual_kw)


def _is_tech_query(query_text: str) -> bool:
    tech_kw = [
        '报错', '错误', '异常', '代码', '编程', '开发', '接口', '部署', '安装', '配置', '环境', '教程',
        'python', 'java', 'javascript', 'typescript', 'node', 'nodejs', 'docker', 'k8s', 'kubernetes',
        'sql', 'mysql', 'postgres', 'redis', 'nginx', 'flask', 'fastapi', 'react', 'vue', 'api', 'bug', 'debug'
    ]
    return _search_has_any_keyword(query_text, tech_kw)


def _wants_douyin_results(query_text: str) -> bool:
    q = str(query_text or '').lower()
    return _search_has_any_keyword(q, [
        '抖音', 'douyin', 'dy', '账号', '主页', '个人页', '博主', '主播', '网红', '达人'
    ])


def _wants_bilibili_results(query_text: str) -> bool:
    q = str(query_text or '').lower()
    return _search_has_any_keyword(q, [
        'b站', 'bilibili', 'up主', 'up', '视频', '主页', '账号', '频道'
    ])


def _has_cjk_query_text(query_text: str) -> bool:
    return bool(re.search(r'[\u4e00-\u9fff]', str(query_text or '')))


def _wants_weibo_results(query_text: str) -> bool:
    q = str(query_text or '').lower()
    return _search_has_any_keyword(q, [
        '微博', 'weibo', '超话', '饭拍', '路透', '生图', '返图'
    ])


def _should_prefer_weibo_for_query(query_text: str) -> bool:
    q = str(query_text or '')
    if not q:
        return False
    if _wants_weibo_results(q):
        return True
    return _has_cjk_query_text(q) and _is_person_visual_query(q) and not (_wants_douyin_results(q) or _wants_bilibili_results(q))


def _allow_platform_host_for_query(host: str, query_text: str) -> bool:
    h = str(host or '').lower().strip('.')
    q = str(query_text or '')
    if not h:
        return False
    if ('douyin.com' in h or h.endswith('.douyin.com')) and (_wants_douyin_results(q) or _is_person_visual_query(q)):
        return True
    if ('bilibili.com' in h or h.endswith('.bilibili.com')) and (_wants_bilibili_results(q) or _is_person_visual_query(q)):
        return True
    if (
        'weibo.com' in h or h.endswith('.weibo.com') or
        'weibo.cn' in h or h.endswith('.weibo.cn')
    ) and _should_prefer_weibo_for_query(q):
        return True
    if ('csdn.net' in h or h.endswith('.csdn.net')) and _is_tech_query(q):
        return True
    return False


def _preferred_social_site_for_query(query_text: str) -> str:
    q = str(query_text or '').lower()
    if not q:
        return ''
    if 'site:' in q:
        return ''
    if _search_has_any_keyword(q, ['抖音', 'douyin']):
        return 'douyin.com'
    if _search_has_any_keyword(q, ['b站', 'bilibili']):
        return 'bilibili.com'
    if _wants_weibo_results(q) or _should_prefer_weibo_for_query(q):
        return 'weibo.cn'
    return ''


def _site_bias_terms(query_text: str, site_host: str = '') -> str:
    q = str(query_text or '').strip()
    if not q:
        return q
    s = q
    drop_kw = [
        '帮我', '查一下', '查一查', '查找', '搜一下', '搜一搜', '找一下', '找一找', '看一下', '看一看',
        '抖音号', '抖音账号', '抖音主页', '抖音个人页', '抖音', 'douyin',
        'b站号', 'b站账号', 'b站主页', 'b站个人页', 'b站', 'bilibili',
        '微博号', '微博账号', '微博主页', '微博个人页', '微博', 'weibo', '超话',
        '账号', '帐号', '主页', '个人页', '首页', '链接', '地址', '资料', '个人简介', '简介',
    ]
    for kw in drop_kw:
        s = re.sub(re.escape(kw), ' ', s, flags=re.I)
    s = re.sub(r'[？?。!！,:：;；()（）\[\]【】]',' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    if not s:
        return q
    tokens = [t for t in s.split(' ') if t]
    if len(tokens) > 6:
        tokens = tokens[:6]
    return ' '.join(tokens) or q


def _social_site_bias_queries(query_text: str) -> list[str]:
    q = str(query_text or '').strip()
    site_host = _preferred_social_site_for_query(q)
    if not q or not site_host:
        return []
    terms = _site_bias_terms(q, site_host)
    cands = [
        f'site:{site_host} {terms}'.strip(),
        f'{terms} site:{site_host}'.strip(),
    ]
    out = []
    seen = {q}
    for cand in cands:
        cand = re.sub(r'\s+', ' ', cand).strip()
        if not cand or cand in seen:
            continue
        seen.add(cand)
        out.append(cand)
    return out


def _host_matches_preference(url: str, query_text: str) -> bool:
    host = _host_of(url)
    pref = _preferred_social_site_for_query(query_text)
    if not pref or not host:
        return False
    if pref == 'weibo.cn':
        return host in {'weibo.com', 'weibo.cn', 'm.weibo.cn'} or host.endswith('.weibo.com') or host.endswith('.weibo.cn')
    return host == pref or host.endswith('.' + pref)


def _official_domains_from_text(text: str) -> list[str]:
    t = str(text or '').lower()
    mapping = [
        (['iphone', 'ipad', 'macbook', 'mac mini', 'imac', 'apple watch', 'airpods', 'ios', 'macos', 'apple'], ['apple.com']),
        (['surface', 'windows', 'microsoft', 'xbox'], ['microsoft.com', 'xbox.com']),
        (['pixel', 'android', 'google', 'nest', 'chromecast'], ['google.com', 'store.google.com', 'support.google.com']),
        (['galaxy', 'samsung'], ['samsung.com']),
        (['tesla', 'model 3', 'model y', 'model s', 'model x'], ['tesla.com']),
        (['openai', 'chatgpt', 'gpt-4', 'gpt-5'], ['openai.com']),
        (['playstation', 'ps5', 'ps4', 'sony'], ['playstation.com', 'sony.com']),
        (['nintendo', 'switch', 'switch 2'], ['nintendo.com']),
        (['xiaomi', 'redmi', 'mi band'], ['xiaomi.com', 'mi.com']),
        (['huawei', 'matebook', 'pura', 'mate 60'], ['huawei.com']),
        (['oneplus'], ['oneplus.com']),
        (['oppo'], ['oppo.com']),
        (['vivo'], ['vivo.com']),
        (['lenovo', 'thinkpad'], ['lenovo.com']),
        (['dell', 'xps', 'alienware'], ['dell.com']),
        (['hp', 'spectre', 'omen'], ['hp.com']),
        (['asus', 'rog', 'zenbook'], ['asus.com']),
        (['canon'], ['canon.com']),
        (['nikon'], ['nikon.com']),
    ]
    out = []
    for keys, domains in mapping:
        if any(k in t for k in keys):
            out.extend(domains)
    seen = set()
    uniq = []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq

def _domain_score(url: str, intent: str, query_text: str = '') -> int:
    u = (url or '').lower()
    score = 0
    dynamic_official = _official_domains_from_text(query_text)
    generic_official = [
        'support.apple.com', 'developer.apple.com', 'apple.com',
        'support.google.com', 'developers.google.com', 'store.google.com', 'google.com',
        'microsoft.com', 'support.microsoft.com', 'learn.microsoft.com',
        'openai.com', 'platform.openai.com',
        'docs.python.org', 'python.org', 'developer.mozilla.org', 'mozilla.org', 'react.dev',
        'flask.palletsprojects.com', 'nodejs.org', 'typescriptlang.org', 'postgresql.org', 'mysql.com',
        'ubuntu.com', 'debian.org', 'kernel.org'
    ]
    wiki_domains = ['wikipedia.org', 'wikimedia.org']
    media_domains = [
        'theverge.com', 'techcrunch.com', 'cnet.com', 'arstechnica.com', 'engadget.com',
        'tomsguide.com', '9to5mac.com', 'androidauthority.com', 'gsmarena.com', 'wired.com'
    ]

    hard_low_quality_domains = [
        'tieba.baidu.com', 'baidu.com', 'sohu.com', 'qq.com'
    ]
    medium_low_quality_domains = [
        'zhihu.com'
    ]

    is_weibo_host = any(d in u for d in ['weibo.com', 'weibo.cn'])
    is_weibo_cdn = 'sinaimg.cn' in u

    if is_weibo_host:
        if _wants_weibo_results(query_text):
            score += 24
        elif intent == 'visual' and _should_prefer_weibo_for_query(query_text):
            score += 20
        else:
            score -= 90
    elif any(d in u for d in hard_low_quality_domains):
        score -= 90
    elif any(d in u for d in medium_low_quality_domains):
        score -= 30

    if is_weibo_cdn and intent == 'visual' and _should_prefer_weibo_for_query(query_text):
        score += 18

    if 'csdn.net' in u:
        score += 18 if _is_tech_query(query_text) else -8

    if 'bilibili.com' in u or 'douyin.com' in u:
        score += 22 if _is_person_visual_query(query_text) else -12

    if any(d in u for d in dynamic_official):
        score += 140 if intent in ('official', 'visual', 'general') else 90
    if any(d in u for d in generic_official):
        score += 110 if intent in ('official', 'general') else 80
    if any(d in u for d in wiki_domains):
        score += 70 if intent == 'general' else 45
    if any(d in u for d in media_domains):
        score += 110 if intent == 'review' else 55
    if re.search(r'/docs?/|/support/|/manual|/help', u):
        score += 20 if intent == 'official' else 8
    return score

def _rerank_results(results: list[dict], user_text: str) -> list[dict]:
    intent = _classify_search_intent(user_text)
    def score_item(r: dict) -> tuple[int, int, int]:
        url = r.get('url') or ''
        title = str(r.get('title') or '')
        snippet = str(r.get('snippet') or '')
        text = f"{title} {snippet}".lower()
        score = _domain_score(url, intent, user_text)
        if intent == 'official' and any(k in text for k in ['official', 'spec', 'specs', 'specification', 'support', 'manual', 'price', 'pricing']):
            score += 24
        if intent == 'review' and any(k in text for k in ['review', 'hands-on', 'vs', 'comparison', 'compare', 'benchmark']):
            score += 24
        if intent == 'general' and any(k in text for k in ['overview', 'introduction', 'guide', 'what is']):
            score += 10
        return score, len(snippet), len(title)
    return sorted(results or [], key=score_item, reverse=True)

def _score_image_candidate(row: dict, subject: str, user_text: str = '') -> float:
    subject = _normalize_image_subject(subject).lower()
    title = str((row or {}).get('title') or '').lower()
    page_url = str((row or {}).get('source') or '').lower()
    img_url = str((row or {}).get('url') or '').lower()
    blob = f"{title} {page_url} {img_url}"
    score = 0.0

    if subject:
        if subject in title:
            score += 5.5
        if subject in page_url:
            score += 3.0
        if subject in img_url:
            score += 2.0
        tokens = [t for t in re.split(r'[\s/|,_-]+', subject) if t]
        if len(tokens) >= 2:
            hits = sum(1 for t in tokens if t in blob)
            score += min(hits, len(tokens)) * 1.1

    good_words = ['照片', '相片', '人像', '人物', 'photo', 'portrait', 'headshot', 'profile']
    for kw in good_words:
        if kw in title:
            score += 0.9

    bad_words = ['illustration', 'vector', 'cartoon', 'wallpaper', 'logo', 'icon', 'ai generated', 'render']
    for kw in bad_words:
        if kw in blob:
            score -= 3.2

    bad_domains = ['pinterest', 'shutterstock', 'istock', 'freepik', 'depositphotos', 'alamy','zhihu']
    if any(d in page_url or d in img_url for d in bad_domains):
        score -= 4.0

    if re.search(r'\bavatar\b|\bdefault\b|\bplaceholder\b', blob):
        score -= 2.5

    intent = _classify_search_intent(user_text or subject)
    score += _domain_score(page_url or img_url, 'visual' if intent == 'visual' else intent, user_text or subject) / 120.0
    score += _remote_image_host_score_adjust(img_url or page_url)
    return round(score, 4)


def _rerank_image_results(rows: list[dict], user_text: str, subject: str = '', limit: int | None = None) -> list[dict]:
    subject = _normalize_image_subject(subject or _clean_image_subject(user_text) or _image_search_query_from_user_text(user_text))
    scored = []
    for r in (rows or []):
        item = dict(r or {})
        item['_score'] = _score_image_candidate(item, subject, user_text)
        scored.append(item)
    scored.sort(key=lambda r: (float(r.get('_score') or 0.0), len(str(r.get('title') or ''))), reverse=True)

    if not scored:
        return []

    top = float(scored[0].get('_score') or 0.0)
    threshold = 2.8 if subject else 1.4
    kept = [r for r in scored if float(r.get('_score') or 0.0) >= threshold]
    if not kept:
        kept = scored[:min(len(scored), max(1, int(limit or 3)))]

    compact = []
    for r in kept:
        if compact and float(r.get('_score') or 0.0) < top - 3.0:
            continue
        compact.append(r)
        if limit and len(compact) >= int(limit):
            break
    return compact if compact else kept[:max(1, int(limit or 3))]


def _format_search_upstream_error(provider_label: str, endpoint: str, exc: Exception, *, mention_api_path: bool = False) -> str:
    label = str(provider_label or '搜索服务').strip() or '搜索服务'
    target = str(endpoint or '').strip() or '-'
    status = 0
    try:
        status = int(getattr(getattr(exc, 'response', None), 'status_code', 0) or 0)
    except Exception:
        status = 0
    if isinstance(exc, httpx.TimeoutException):
        tail = '、搜索接口路径' if mention_api_path else ''
        return f'{label} 连接超时，请检查地址、端口{tail}是否正确，并确认服务已启动（当前：{target}）'
    if isinstance(exc, httpx.ConnectError):
        return f'{label} 连接失败，请检查地址和端口是否正确，并确认服务已启动（当前：{target}）'
    if isinstance(exc, httpx.HTTPStatusError):
        tail = '，请检查地址、端口或搜索接口路径' if mention_api_path else '，请检查地址和端口'
        return f'{label} 返回 HTTP {status}{tail}（当前：{target}）'
    if isinstance(exc, httpx.NetworkError):
        tail = '或搜索接口路径' if mention_api_path else ''
        return f'{label} 网络请求失败，请检查地址、端口{tail}是否可达（当前：{target}）'
    return f'{label} 请求失败：{type(exc).__name__}: {exc}'


def _searxng_request_json(endpoint: str, params: dict, timeout: float) -> dict:
    t = httpx.Timeout(timeout, connect=min(4.0, float(timeout)))
    try:
        r = HTTPX_SEARCH.get(endpoint, params=params, timeout=t)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(_format_search_upstream_error('SearxNG', endpoint, e, mention_api_path=True)) from e
    try:
        data = r.json()
    except Exception as e:
        raise RuntimeError(f'SearxNG 响应不是有效 JSON，请检查地址或搜索接口路径（当前：{endpoint}）') from e
    if not isinstance(data, dict):
        raise RuntimeError(f'SearxNG 响应格式不正确，请检查地址或搜索接口路径（当前：{endpoint}）')
    return data


def _probe_whoogle_connection(base_url: str, timeout: float = 4.0) -> str:
    root = str(base_url or '').strip().rstrip('/')
    if not root:
        raise RuntimeError('已启用 Whoogle，但还没有填写地址')
    headers = {'Accept': 'text/html,application/xhtml+xml'}
    params = {'q': 'test'}
    last_exc = None
    tried: list[str] = []
    for path in ('/search', '/'):
        endpoint = root + path
        tried.append(endpoint)
        try:
            t = httpx.Timeout(timeout, connect=min(4.0, float(timeout)))
            r = HTTPX_SEARCH.get(endpoint, params=params, headers=headers, timeout=t)
            r.raise_for_status()
            return endpoint
        except Exception as e:
            last_exc = e
            continue
    if last_exc is not None:
        raise RuntimeError(_format_search_upstream_error('Whoogle', root, last_exc)) from last_exc
    raise RuntimeError(f'Whoogle 无法访问（当前：{", ".join(tried) or root}）')


def _validate_search_provider_connection(provider: str, timeout: float = 4.0) -> dict:
    name = str(provider or '').strip().lower()
    if name == 'searxng':
        base_url = app_getenv('SEARXNG_URL', '').strip().rstrip('/')
        api_path = app_getenv('SEARXNG_API_PATH', '/search').strip() or '/search'
        endpoint = (base_url + api_path) if base_url else api_path
        if not base_url:
            return {'provider': 'searxng', 'enabled': True, 'ok': False, 'message': '已启用 SearxNG，但还没有填写地址'}
        try:
            _searxng_request_json(endpoint, {'q': 'test', 'format': 'json', 'language': 'all', 'safesearch': 0}, timeout)
            return {'provider': 'searxng', 'enabled': True, 'ok': True, 'message': 'SearxNG 连接正常'}
        except Exception as e:
            return {'provider': 'searxng', 'enabled': True, 'ok': False, 'message': str(e)}
    if name == 'whoogle':
        base_url = app_getenv('WHOOGLE_URL', '').strip().rstrip('/')
        if not base_url:
            return {'provider': 'whoogle', 'enabled': True, 'ok': False, 'message': '已启用 Whoogle，但还没有填写地址'}
        try:
            _probe_whoogle_connection(base_url, timeout=timeout)
            return {'provider': 'whoogle', 'enabled': True, 'ok': True, 'message': 'Whoogle 连接正常'}
        except Exception as e:
            return {'provider': 'whoogle', 'enabled': True, 'ok': False, 'message': str(e)}
    if name == 'external':
        endpoint = str(app_getenv('EXTERNAL_SEARCH_URL', '') or '').strip()
        api_key = str(app_getenv('EXTERNAL_SEARCH_API_KEY', '') or '').strip()
        if not endpoint:
            return {'provider': 'external', 'enabled': True, 'ok': False, 'message': '已启用 external，但还没有填写搜索接口地址'}
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        payload = {'query': 'test', 'max_results': 3, 'allow_fallback': False}
        try:
            data = _external_search_request_json(endpoint, headers, payload, timeout)
            rows = _external_search_extract_items(data)
            if not isinstance(rows, list):
                raise RuntimeError('external 响应格式不正确：搜索结果不是数组')
            return {'provider': 'external', 'enabled': True, 'ok': True, 'message': 'external 连接正常'}
        except Exception as e:
            return {'provider': 'external', 'enabled': True, 'ok': False, 'message': str(e)}
    if name == 'uapipro':
        base_url = app_getenv('UAPIPRO_BASE_URL', 'https://uapis.cn/api/v1').strip().rstrip('/')
        api_key = app_getenv('UAPIPRO_API_KEY', '').strip()
        if not base_url:
            return {'provider': 'uapipro', 'enabled': True, 'ok': False, 'code': 'uapipro_base_url_missing', 'message': '已启用 UApiPro，但还没有填写 Base URL'}
        if not api_key:
            return {'provider': 'uapipro', 'enabled': True, 'ok': False, 'code': 'uapipro_api_key_missing', 'message': '已启用 UApiPro，但还没有填写 API Key'}
        try:
            headers = {'Authorization': f'Bearer {api_key}'}
            t = httpx.Timeout(timeout, connect=min(4.0, float(timeout)))
            r = HTTPX_SEARCH.get(base_url + '/search/engines', headers=headers, timeout=t)
            r.raise_for_status()
            return {'provider': 'uapipro', 'enabled': True, 'ok': True, 'message': 'UApiPro 连接正常'}
        except Exception as e:
            return {'provider': 'uapipro', 'enabled': True, 'ok': False, 'message': str(e)}
    return {'provider': name or 'unknown', 'enabled': False, 'ok': True, 'message': ''}



def web_search_searxng(query: str, k: int = 5, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
    """本地/自建 SearxNG 的 JSON 搜索接口（推荐）：
    返回：[{title,url,snippet,engines}]，并按问题类型做轻量重排序。
    - 若首轮因 engines/categories/language 约束过严导致 0 结果，会自动放宽后再试一次。
    - 若仍 0 结果且 SearxNG 明确报告大量 unresponsive_engines，则抛错交给上层 fallback provider。
    """
    q = (query or "").strip()
    if not q:
        return []
    searxng_url = app_getenv("SEARXNG_URL", "").strip().rstrip("/")
    searxng_api_path = app_getenv("SEARXNG_API_PATH", "/search").strip() or "/search"
    if not searxng_url:
        raise RuntimeError("未配置 SEARXNG_URL（默认留空；如需启用可填写例如 http://127.0.0.1:8080）")

    endpoint = searxng_url + searxng_api_path

    engines = app_getenv("SEARXNG_ENGINES", "").strip()
    categories = app_getenv("SEARXNG_CATEGORIES", "general").strip() or "general"
    language = app_getenv("SEARXNG_LANGUAGE", "zh").strip() or "zh"
    safesearch = int(app_getenv("SEARXNG_SAFESEARCH", "0") or 0)

    params = {
        "q": q,
        "format": "json",
        "language": language,
        "safesearch": safesearch,
        "categories": categories,
    }
    if engines:
        params["engines"] = engines

    app_logger.info("[WEB_SEARCH] searxng start q=%r k=%s", q, k)
    data = _searxng_request_json(endpoint, params, timeout)
    initial_results = data.get("results") or []
    unresponsive = data.get("unresponsive_engines") or []

    if not initial_results:
        relaxed_params = dict(params)
        relaxed_params.pop("engines", None)
        relaxed_params.pop("categories", None)
        relaxed_params["language"] = "all"
        if relaxed_params != params:
            app_logger.warning(
                "[WEB_SEARCH] searxng empty; retry relaxed q=%r unresponsive=%s",
                q,
                unresponsive,
            )
            relaxed_data = _searxng_request_json(endpoint, relaxed_params, timeout)
            relaxed_results = relaxed_data.get("results") or []
            if relaxed_results:
                data = relaxed_data
                initial_results = relaxed_results
                unresponsive = relaxed_data.get("unresponsive_engines") or unresponsive
                app_logger.info("[WEB_SEARCH] searxng relaxed retry ok q=%r hits=%s", q, len(initial_results))
            else:
                relaxed_unresponsive = relaxed_data.get("unresponsive_engines") or []
                if relaxed_unresponsive:
                    unresponsive = relaxed_unresponsive
        if not initial_results and unresponsive:
            raise RuntimeError(
                "SearxNG 无结果，且搜索引擎不可用：" + ", ".join(str(x) for x in unresponsive[:8])
            )

    raw_limit = max(min(int(k or 5) * 4, 24), int(k or 5))
    results = []
    for it in initial_results[:raw_limit]:
        eng = it.get("engines") or it.get("engine") or []
        if isinstance(eng, str):
            eng = [eng]
        results.append({
            "title": (it.get("title") or "")[:200],
            "url": (it.get("url") or "")[:500],
            "snippet": (_strip_html_tags(it.get("content") or it.get("snippet") or ""))[:400],
            "engines": eng,
        })
    results = _filter_search_results(results, user_text or q)
    results = _rerank_results(results, user_text or q)
    return results[:max(1, min(int(k), 10))]
