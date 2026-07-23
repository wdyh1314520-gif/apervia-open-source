# Split from app3_parts/web/web_search_enrichment_part.py.
# Purpose: location payloads, result filtering/scoring, provider chain, and text search entrypoint.
# Loaded by web_search_enrichment_part.py via _exec_split_file(...), sharing the original global namespace.

def _strip_html_tags(s: str) -> str:
    """更稳的 HTML 清洗（对齐 app.py）。"""
    if not s:
        return ""
    s = re.sub(r"<script\b[^>]*>.*?</script>", " ", s, flags=re.I | re.S)
    s = re.sub(r"<style\b[^>]*>.*?</style>", " ", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    return " ".join(s.split())
def _normalize_search_planner_context_text(text: str, max_len: int = 900) -> str:
    raw = html.unescape(str(text or '').strip())
    if not raw:
        return ''
    parts = []
    for line in re.split(r'[\r\n]+', raw):
        line = str(line or '').strip()
        if not line:
            continue
        line = re.sub(r'^(?:user|assistant|system)\s*:\s*', '', line, flags=re.I)
        line = re.sub(r'^(?:用户(?:最新)?问题|最近对话上下文|已知工具结果/上下文|已知上下文|工具结果摘要|工具结果|上下文|context)\s*[:：]\s*', '', line, flags=re.I)
        line = re.sub(r'\s+', ' ', line).strip()
        if line:
            parts.append(line)
    if not parts:
        return ''
    out = ' '.join(parts)
    out = re.sub(r'\s+', ' ', out).strip()
    if max_len > 0:
        out = out[:max_len].rstrip()
    return out


def _normalize_search_query(q: str) -> str:
    """只做轻量清洗，不用固定模板硬改用户意图。"""
    q0 = html.unescape(str(q or '').strip())
    if not q0:
        return ''

    s = q0
    s = re.sub(r'[\r\n\t]+', ' ', s)
    s = re.sub(r"[`“”‘’\"']+", ' ', s)
    s = re.sub(r'^(?:用户(?:最新)?问题|问题|搜索(?:词|query)?|query|search query|联网搜索|web search)\s*[:：]\s*', '', s, flags=re.I)
    s = re.sub(r'^(?:请问一下|请问|麻烦你|麻烦|帮我(?:查|搜|看)?(?:一下)?|给我(?:查|搜|看)?(?:一下)?|可以帮我(?:查|搜|看)?(?:一下)?|能不能帮我(?:查|搜|看)?(?:一下)?|想了解一下|想知道)\s*', '', s)
    s = re.sub(r'\s+', ' ', s).strip(' ,，。；;:：!?！？')
    return s[:160]


_LOCATION_INTENT_KEYS = [
    "我在哪", "我在那", "我在哪里", "我在哪儿", "我现在在哪", "我现在在哪里", "当前位置", "我的位置", "定位",
    "我现在在那", "我现在在那儿", "我在哪裡", "我現在在哪", "我現在在哪裡", "目前位置"
]
_LOCATION_INTENT_EXACT_KEYS = tuple(k for k in _LOCATION_INTENT_KEYS if k != "定位")
_LOCATION_INTENT_NEGATIVE_RE = re.compile(
    r"(怎么(开|开启|打开|关闭|允许|授权)?定位|如何(开|开启|打开|关闭|允许|授权)?定位|定位(失败|超时|不了|异常|不准|权限|授权|设置|服务|功能|按钮|开关|接口|api|sdk)|获取(不?到)?位置|拿不到位置|无法获取位置|位置(失败|权限|授权|设置)|浏览器定位|手机定位|系统定位|地图定位|gps)",
    re.I,
)
_LOCATION_INTENT_STRONG_RE = re.compile(
    r"^(请问)?\s*(我(现在)?在(哪|那)(里|裡|儿)?|我当前在(哪|那)(里|裡|儿)?|我现在的位置(在)?(哪|那)(里|裡|儿)?|我的位置(在)?(哪|那)(里|裡|儿)?|当前位置(在)?(哪|那)(里|裡|儿)?|目前位置(在)?(哪|那)(里|裡|儿)?)\s*(啊|呀|呢|嘛)?\s*[?？!！。]*$",
    re.I,
)


def _is_location_query_text(text: str) -> bool:
    raw = str(text or '').strip()
    if not raw:
        return False
    try:
        if _is_weather_query_text(raw):
            return False
    except Exception:
        pass
    if _LOCATION_INTENT_NEGATIVE_RE.search(raw):
        return False
    if _LOCATION_INTENT_STRONG_RE.search(raw):
        return True
    normalized = re.sub(r"\s+", "", raw)
    normalized = re.sub(r"[?？!！。]+$", "", normalized)
    return normalized in _LOCATION_INTENT_EXACT_KEYS


def _resolve_location_payload_from_geo(user_geo: dict | None = None) -> dict | None:
    if not isinstance(user_geo, dict):
        return None
    try:
        lat = float(user_geo.get('lat'))
        lon = float(user_geo.get('lon'))
    except Exception:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    name = str(user_geo.get('name') or '').strip()
    if not name:
        try:
            name = str(_reverse_geocode_name(lat, lon) or '').strip()
        except Exception:
            name = ''
    return {
        'name': name or f'{lat:.5f}, {lon:.5f}',
        'lat': lat,
        'lon': lon,
        'source': str(user_geo.get('source') or 'user_geo').strip() or 'user_geo',
    }


def _build_location_tool_payload(user_text: str, user_geo: dict | None = None, request_precise: bool = False) -> dict:
    text = str(user_text or '').strip()
    location_state = {}
    if isinstance(user_geo, dict) and isinstance(user_geo.get('_location_state'), dict):
        location_state = dict(user_geo.get('_location_state') or {})
    resolved = _resolve_location_payload_from_geo(user_geo)
    request_precise = bool(request_precise)

    if not isinstance(resolved, dict):
        precise_state = location_state.get('precise_location') if isinstance(location_state.get('precise_location'), dict) else {}
        approx_state = location_state.get('approximate_location') if isinstance(location_state.get('approximate_location'), dict) else {}
        time_state = location_state.get('time_environment') if isinstance(location_state.get('time_environment'), dict) else {}
        approx_available = bool(approx_state.get('available'))
        can_request = bool(precise_state.get('can_request')) if 'can_request' in precise_state else False
        details = {
            'precise_location': {
                'enabled': bool(precise_state.get('enabled')) if 'enabled' in precise_state else False,
                'available': False,
                'permission_state': str(precise_state.get('permission_state') or '').strip(),
                'can_request': can_request,
                'attach_mode': str(precise_state.get('attach_mode') or '').strip(),
            },
            'approximate_location': {
                'available': approx_available,
                'source': str(approx_state.get('source') or ('not_available' if not approx_available else 'approximate')).strip(),
                'accuracy': str(approx_state.get('accuracy') or ('coarse' if approx_available else '')).strip(),
                'granularity': str(approx_state.get('granularity') or '').strip(),
            },
            'time_environment': {
                'available': bool(time_state.get('available') or time_state.get('timezone')),
                'timezone': str(time_state.get('timezone') or '').strip(),
                'offset_minutes': time_state.get('offset_minutes'),
                'source': str(time_state.get('source') or 'browser_clock').strip() or 'browser_clock',
            },
            'visibility': str(location_state.get('visibility') or ('approximate_location_available' if approx_available else 'no_precise_location')).strip(),
        }
        if approx_available:
            for key in ('name', 'city', 'region', 'region_code', 'country', 'country_name', 'timezone', 'postal_code', 'lat', 'lon', 'ip_version', 'scope'):
                if approx_state.get(key) not in (None, ''):
                    details['approximate_location'][key] = approx_state.get(key)
        last_error = precise_state.get('last_error') if isinstance(precise_state.get('last_error'), dict) else None
        if isinstance(last_error, dict):
            details['precise_location']['last_error'] = {
                'reason': str(last_error.get('reason') or last_error.get('name') or '').strip(),
                'message': str(last_error.get('message') or '').strip()[:160],
            }

        need_browser_location = bool(request_precise and can_request)
        result = {
            'ok': bool(approx_available),
            '_kind': 'location',
            'query': text,
            'need_location': not bool(approx_available),
            'need_browser_location': need_browser_location,
            'request_precise': request_precise,
            'location_visibility': details,
        }
        if need_browser_location:
            result['location_permission_request'] = {
                'title': '需要使用你的位置来回答这个问题',
                'message': '开启后仅用于本次对话请求。',
                'confirm_text': '确定',
                'cancel_text': '取消',
            }
            result['summary'] = '模型请求本轮精确定位授权；等待用户确认或取消。'
            return result

        if approx_available:
            approx_name = str(details['approximate_location'].get('name') or details['approximate_location'].get('city') or details['approximate_location'].get('region') or details['approximate_location'].get('country') or '').strip()
            loc_obj = dict(details['approximate_location'])
            loc_obj['type'] = 'approximate'
            result.update({
                'ok': True,
                'need_location': False,
                'location_type': 'approximate',
                'location_name': approx_name,
                'location': loc_obj,
                'summary': ('本轮只有网络/IP 粗略位置' + (f'：{approx_name}' if approx_name else '') + '；不能当作精确地址。'),
            })
            return result

        tz = str(details.get('time_environment', {}).get('timezone') or '').strip()
        tips = ['可以直接告诉我城市/地区']
        if can_request:
            tips.append('如需精确位置，可再次调用本工具并设置 request_precise=true')
        summary = '当前没有可用的精确定位坐标或网络粗略位置。'
        if tz:
            summary += f' 本轮只能看到时间/时区环境：{tz}，这不能当作真实城市或地址。'
        result.update({
            'ok': False,
            'message': '当前没有可用位置证据。' + (f' 只能看到时区/时间环境（{tz}），不能据此确定城市或地址。' if tz else ''),
            'tips': tips[:3],
            'summary': summary,
        })
        return result

    name = str(resolved.get('name') or '').strip() or '当前位置'
    lat = float(resolved.get('lat'))
    lon = float(resolved.get('lon'))
    location_obj = {
        'name': name,
        'lat': lat,
        'lon': lon,
        'source': str(resolved.get('source') or 'user_geo').strip() or 'user_geo',
        'type': 'precise',
    }
    try:
        if isinstance(user_geo, dict) and user_geo.get('accuracy') is not None:
            location_obj['accuracy'] = user_geo.get('accuracy')
    except Exception:
        pass
    return {
        'ok': True,
        '_kind': 'location',
        'query': text,
        'need_location': False,
        'need_browser_location': False,
        'location_type': 'precise',
        'location_name': name,
        'summary': f'本轮有已授权定位坐标，可解析为大概位置：{name}。',
        'location': location_obj,
        'location_visibility': {
            'precise_location': {'available': True, 'source': location_obj.get('source')},
            'visibility': 'precise_location_available',
        },
    }

def _dedup_urls(results: list[dict], limit: int = 6) -> list[dict]:
    seen = set()
    out = []
    for r in results or []:
        u = (r.get("url") or "").strip()
        if not u:
            continue
        # 去掉跟踪参数
        try:
            pu = urllib.parse.urlparse(u)
            u2 = pu._replace(query="").geturl()
        except Exception:
            u2 = u
        key = u2
        if key in seen:
            continue
        seen.add(key)
        out.append({**r, "url": u2})
        if len(out) >= limit:
            break
    return out
def _norm_url_for_dedup(u: str) -> str:
    """尽量把同一网页的不同跟踪参数归一化，便于去重。"""
    if not u:
        return ""
    u = u.strip()
    try:
        pu = urllib.parse.urlsplit(u)
        scheme = pu.scheme.lower() if pu.scheme else "http"
        netloc = pu.netloc.lower()
        path = pu.path or "/"
        # 去掉常见跟踪参数
        q = urllib.parse.parse_qsl(pu.query, keep_blank_values=False)
        drop_prefix = ("utm_", "spm", "from", "ref", "source", "campaign", "msclkid", "gclid", "fbclid")
        q2 = [(k, v) for (k, v) in q if not any(k.lower().startswith(p) for p in drop_prefix)]
        query = urllib.parse.urlencode(q2, doseq=True)
        # 去掉默认端口
        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        if netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]
        out = urllib.parse.urlunsplit((scheme, netloc, path.rstrip("/") or "/", query, ""))
        return out
    except Exception:
        return u


def _is_official_intent(q: str) -> bool:
    q = (q or "").lower()
    return any(k in q for k in ["官网", "官方网站", "官方", "official", "site:", "homepage", "home page"])

def _safe_urlsplit(url: str):
    try:
        return urllib.parse.urlsplit(url)
    except Exception:
        return urllib.parse.urlsplit("")

def _host_of(url: str) -> str:
    pu = _safe_urlsplit(url or "")
    return (pu.hostname or "").lower()

def _path_depth(url: str) -> int:
    pu = _safe_urlsplit(url or "")
    p = pu.path or ""
    if p in ("", "/"):
        return 0
    return len([x for x in p.split("/") if x])

def _looks_like_homepage(url: str) -> bool:
    pu = _safe_urlsplit(url or "")
    p = (pu.path or "").strip("/")
    # 根路径或非常短的路径更像官网入口
    if p == "":
        return True
    if p.count("/") == 0 and len(p) <= 12 and p not in {"search", "s", "tag", "tags"}:
        return True
    return False

def _contains_cjk(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", s or ""))

def _engine_blacklist() -> set[str]:
    raw = app_getenv("SEARCH_ENGINE_BLACKLIST", "brave,yandex,startpage").strip()
    return {x.strip().lower() for x in raw.split(",") if x.strip()}

def _domain_blacklist() -> set[str]:
    raw = app_getenv("SEARCH_DOMAIN_BLACKLIST", "").strip()
    return {x.strip().lower() for x in raw.split(",") if x.strip()}

_DEFAULT_JUNK_HOSTS = {
    "360doc.com", "docin.com", "wenku.baidu.com", "mbd.baidu.com", "baijiahao.baidu.com",
    "so.com", "sogou.com", "tieba.baidu.com", "zhidao.baidu.com",
    "juejin.cn", "toutiao.com", "pinterest.com", "facebook.com", "x.com", "twitter.com",
    "zhihu.com", "zhuanlan.zhihu.com", "link.zhihu.com",
}

_DEFAULT_JUNK_TITLE_KWS = [
    "广告", "推广", "赞助", "下载", "破解版", "备用网址", "点击查看", "立即查看",
    "打开app", "扫码", "安装包", "官网入口",
]

_DEFAULT_JUNK_URL_KWS = [
    "utm_", "from=", "spm=", "source=", "campaign=", "clickid=",
    "download", "redirect", "jump", "ad", "推广", "广告",
]

def _is_junk_search_result(row: dict, query: str = "") -> bool:
    try:
        url = str((row or {}).get("url") or "").strip()
        title = str((row or {}).get("title") or "").strip()
        snippet = str((row or {}).get("snippet") or "").strip()
        if not url:
            return True

        host = _host_of(url)
        host_blacklist = set(_DEFAULT_JUNK_HOSTS) | _domain_blacklist()
        if host and any(host == d or host.endswith('.' + d) for d in host_blacklist):
            if not _allow_platform_host_for_query(host, query):
                return True

        blob = f"{title}\n{snippet}".lower()
        if any(k.lower() in blob for k in _DEFAULT_JUNK_TITLE_KWS):
            return True

        ul = url.lower()
        if len(ul) > 140 and any(k in ul for k in _DEFAULT_JUNK_URL_KWS):
            return True

        q = (query or "").strip().lower()
        if _is_official_intent(q) and any(k in blob for k in ["破解版", "下载站", "安装包", "备用网址"]):
            return True

        return False
    except Exception:
        return False

def _filter_search_results(rows: list[dict], query: str = "") -> list[dict]:
    out = []
    dropped = 0
    for row in (rows or []):
        if _is_junk_search_result(row, query=query):
            dropped += 1
            continue
        out.append(row)
    if dropped:
        app_logger.info('[WEB_SEARCH] junk-filter dropped=%s kept=%s q=%r', dropped, len(out), query)
    return out

def _domain_quality_adjust(url: str, title: str, query: str) -> float:
    u = (url or "").lower()
    host = _host_of(u)
    t = (title or "").lower()
    q = (query or "").lower()
    score = 0.0

    # 明显“广告/印刷/设计案例”这类噪声（你截图里就被这些污染了）
    noise_kw = [
        "print-ad", "print ads", "printed-advert", "best-print", "advertising", "designyourway", "vistaprint",
        "bidexpress", "rprint", "theempire", "brand identity", "logo design", "mockup",
    ]
    if any(k in u or k in t for k in noise_kw):
        score -= 6.0

    # 常见“非官网/低价值”站点扣分（按场景区分，不再一刀切误伤）
    bad_hosts = [
        "baike.baidu.com", "zhidao.baidu.com", "tieba.baidu.com",
        "so.com", "sogou.com", "toutiao.com", "juejin.cn",
        "weixin.qq.com", "mp.weixin.qq.com",
        "360doc.com", "docin.com", "wenku.baidu.com",
        "image.baidu.com", "pinterest", "facebook.com", "twitter.com", "x.com",
    ]
    if any(b in host for b in bad_hosts):
        score -= 2.2

    if 'zhihu.com' in host:
        score -= 1.8

    if 'csdn.net' in host:
        score += 1.6 if _is_tech_query(query) else -0.6

    if 'bilibili.com' in host or 'douyin.com' in host:
        score += 1.8 if _is_person_visual_query(query) else -0.8

    # “官网”意图：更偏向根域名/短路径
    if _is_official_intent(q):
        if any(k in t for k in ["官网", "官方", "official"]):
            score += 3.5
        if _looks_like_homepage(u):
            score += 2.5
        # 如果标题里包含“下载/破解版/安装包”，一般不是官网入口
        if any(k in t for k in ["破解版", "crack", "keygen", "破解", "下载站"]):
            score -= 4.0

    # HTTPS 稍微加分
    if u.startswith("https://"):
        score += 0.4

    # 中文查询：稍微偏向 .cn / 中文内容
    if _contains_cjk(query):
        if host.endswith(".cn") or ".cn/" in u or host.endswith(".com.cn"):
            score += 0.8
        if _contains_cjk(title):
            score += 0.5

    # GitHub / 文档站有时更靠谱（尤其是开源项目）
    if any(host.endswith(x) for x in ["github.com", "gitlab.com", "readthedocs.io", "docs.rs"]):
        score += 0.6

    return score

def _search_result_score(query: str, item: dict) -> float:
    """聚合排序打分：越大越靠前。"""
    q = (query or "").strip()
    ql = q.lower()

    title = (item.get("title") or "")
    snip = (item.get("snippet") or "")
    url = (item.get("url") or "")

    tl = title.lower()
    sl = snip.lower()
    ul = url.lower()

    score = 0.0

    # 关键词匹配（标题更重要）
    for tok in re.split(r"\s+", ql):
        tok = tok.strip()
        if not tok or len(tok) < 2:
            continue
        if tok in tl:
            score += 2.0
        elif tok in sl:
            score += 0.8
        elif tok in ul:
            score += 0.4

    # 额外质量项
    score += _domain_quality_adjust(url, title, q)

    # 引擎黑名单（SearxNG 会给 engines 列表；其他源也可以透传）
    engines = item.get("engines") or item.get("_engines") or []
    if isinstance(engines, str):
        engines = [engines]
    bl = _engine_blacklist()
    if any((e or "").lower() in bl for e in engines):
        score -= 8.0

    # 域名黑名单（你想“嫌少不嫌多”，这里可一键加）
    dblk = _domain_blacklist()
    host = _host_of(url)
    if host and any(host == d or host.endswith("." + d) for d in dblk):
        score -= 20.0  # 直接打下去，几乎不会出现在前排

    return score

def _normalize_provider_name(name: str, *, kind: str = "search") -> str:
    n = str(name or "").strip().lower()
    if kind == "search":
        aliases = {
            "": "searxng",
            "default": "searxng",
            "searx": "searxng",
            "whoogle-search": "whoogle",
            "uapi": "uapipro",
            "uapi-pro": "uapipro",
            "uapipro": "uapipro",
            "uapis": "uapipro",
            "serp": "serper",
            "google-serper": "serper",
            "google_serper": "serper",
            "tavily-search": "tavily",
            "tavily_search": "tavily",
            "external-search": "external",
            "external_search": "external",
        }
        return aliases.get(n, n)
    if kind == "image":
        aliases = {
            "": "searxng",
            "default": "searxng",
            "searx": "searxng",
            "serp": "serper",
            "google-serper": "serper",
            "google_serper": "serper",
            "external": "external",
            "external-search": "external",
            "external_search": "external",
            "search-gateway": "external",
            "search_gateway": "external",
        }
        return aliases.get(n, n)
    aliases = {
        "": "native",
        "default": "native",
        "builtin": "native",
        "local": "native",
        "fetch": "native",
        "auto": "auto",
        "trafilatura": "trafilatura",
        "trafilatura_extract": "trafilatura",
        "trafilatura-extract": "trafilatura",
    }
    return aliases.get(n, n)


def _provider_chain(primary: str, fallback: str, *, kind: str = "search") -> list[str]:
    out = []
    for raw in [primary, fallback]:
        name = _normalize_provider_name(raw, kind=kind)
        if not name or name == "none" or name in out:
            continue
        out.append(name)
    if not out:
        if kind in ("search", "image"):
            out.append("searxng")
        else:
            out.append("native")
    return out


def _apply_search_result_defaults(rows: list[dict], provider: str) -> list[dict]:
    out = []
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item.setdefault("provider", provider)
        item.setdefault("source", provider)
        out.append(item)
    return out


def web_search_serper(query: str, k: int = 5, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    api_key = app_getenv("SERPER_API_KEY", "").strip()
    app_logger.warning(
        "[DEBUG_SERPER_ENTER] q=%r key_len=%s endpoint=%r",
        q,
        len(api_key),
        app_getenv("SERPER_API_URL", "https://google.serper.dev/search").strip() or "https://google.serper.dev/search",
    )
    if not api_key:
        raise RuntimeError("未配置 SERPER_API_KEY")
    endpoint = app_getenv("SERPER_API_URL", "https://google.serper.dev/search").strip() or "https://google.serper.dev/search"
    payload = {"q": q, "num": max(1, min(int(k or 5), 10))}
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    t = httpx.Timeout(timeout, connect=min(4.0, float(timeout)))
    r = HTTPX_SEARCH.post(endpoint, headers=headers, json=payload, timeout=t)
    r.raise_for_status()
    data = r.json()
    organic = data.get("organic") or []
    results = []
    raw_limit = max(min(int(k or 5) * 4, 24), int(k or 5))
    for it in organic[:raw_limit]:
        results.append({
            "title": str(it.get("title") or "")[:200],
            "url": str(it.get("link") or it.get("url") or "")[:500],
            "snippet": _strip_html_tags(it.get("snippet") or it.get("description") or "")[:400],
            "engines": ["serper"],
            "provider": "serper",
            "source": "serper",
        })
    results = [r for r in results if r.get("url")]
    results = _filter_search_results(results, user_text or q)
    results = _rerank_results(results, user_text or q)
    return results[:max(1, min(int(k), 10))]


def web_search_tavily(query: str, k: int = 5, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    api_key = app_getenv("TAVILY_API_KEY", "").strip()
    endpoint = app_getenv("TAVILY_SEARCH_URL", "https://api.tavily.com/search").strip() or "https://api.tavily.com/search"
    app_logger.warning(
        "[DEBUG_TAVILY_SEARCH_ENTER] q=%r key_len=%s endpoint=%r",
        q,
        len(api_key),
        endpoint,
    )
    if not api_key:
        raise RuntimeError("未配置 TAVILY_API_KEY")
    payload = {
        "query": q,
        "search_depth": "basic",
        "topic": "general",
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_favicon": True,
        "max_results": max(1, min(int(k or 5) * 2, 20)),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    t = httpx.Timeout(timeout, connect=min(4.0, float(timeout)))
    r = HTTPX_SEARCH.post(endpoint, headers=headers, json=payload, timeout=t)
    r.raise_for_status()
    data = r.json()
    rows = data.get("results") or []
    results = []
    raw_limit = max(min(int(k or 5) * 4, 24), int(k or 5))
    for it in rows[:raw_limit]:
        url = str(it.get("url") or "").strip()
        if not url:
            continue
        results.append({
            "title": str(it.get("title") or "")[:200],
            "url": url[:500],
            "snippet": _strip_html_tags(it.get("content") or it.get("snippet") or "")[:400],
            "engines": ["tavily"],
            "provider": "tavily",
            "source": "tavily",
            "favicon": str(it.get("favicon") or "")[:500],
        })
    results = _filter_search_results(results, user_text or q)
    results = _rerank_results(results, user_text or q)
    return results[:max(1, min(int(k), 10))]


def _external_search_extract_items(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ('results', 'organic', 'organic_results', 'items', 'list'):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    data = payload.get('data')
    if isinstance(data, dict):
        for key in ('results', 'organic', 'organic_results', 'items', 'list'):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _external_search_request_json(endpoint: str, headers: dict, payload: dict, timeout: float):
    t = httpx.Timeout(timeout, connect=min(4.0, float(timeout)))
    response = HTTPX_SEARCH.post(endpoint, headers=headers, json=payload, timeout=t)
    if response.status_code == 405:
        params = {
            'q': str(payload.get('query') or payload.get('q') or '').strip(),
            'limit': int(payload.get('max_results') or payload.get('limit') or 10),
        }
        response = HTTPX_SEARCH.get(endpoint, headers=headers, params=params, timeout=t)
    response.raise_for_status()
    try:
        return response.json()
    except Exception as e:
        raise RuntimeError('external 响应不是有效 JSON') from e


def web_search_external(query: str, k: int = 5, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
    q = (query or '').strip()
    if not q:
        return []
    endpoint = app_getenv('EXTERNAL_SEARCH_URL', '').strip()
    api_key = app_getenv('EXTERNAL_SEARCH_API_KEY', '').strip()
    if not endpoint:
        raise RuntimeError('未配置 EXTERNAL_SEARCH_URL（请填写 external 搜索接口完整地址，例如 http://127.0.0.1:17374/v1/search）')
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    requested_k = max(1, int(k or 5))
    final_limit = max(1, min(requested_k, 10))
    external_request_limit = max(final_limit, min(max(final_limit * 3, 12), 20))

    payload = {
        'query': q,
        'max_results': external_request_limit,
    }
    data = _external_search_request_json(endpoint, headers, payload, timeout)
    rows = _external_search_extract_items(data)
    results = []
    raw_limit = max(min(external_request_limit * 2, 40), external_request_limit)
    for it in rows[:raw_limit]:
        if not isinstance(it, dict):
            continue
        url = str(it.get('url') or it.get('link') or it.get('href') or '').strip()
        if not url:
            continue
        title = str(it.get('title') or it.get('name') or '').strip()
        snippet = _strip_html_tags(it.get('snippet') or it.get('content') or it.get('description') or '')[:400]
        engines = it.get('engines') if isinstance(it.get('engines'), list) else ['external']
        results.append({
            'title': title[:200],
            'url': url[:500],
            'snippet': snippet,
            'engines': [str(x or '').strip() for x in engines if str(x or '').strip()] or ['external'],
            'provider': 'external',
            'source': 'external',
            'favicon': str(it.get('favicon') or '')[:500],
        })
    results = _filter_search_results(results, user_text or q)
    results = _rerank_results(results, user_text or q)
    return results[:final_limit]



def _external_image_search_endpoint() -> str:
    return app_getenv('EXTERNAL_IMAGE_SEARCH_URL', '').strip()


def _external_image_search_extract_items(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ('images', 'image_results', 'organic', 'results', 'items', 'list'):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    data = payload.get('data')
    if isinstance(data, dict):
        for key in ('images', 'image_results', 'organic', 'results', 'items', 'list'):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def web_search_external_images(query: str, k: int = 8, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
    q = (query or '').strip()
    if not q:
        return []
    endpoint = _external_image_search_endpoint()
    api_key = app_getenv('EXTERNAL_IMAGE_SEARCH_API_KEY', '').strip()
    if not endpoint:
        raise RuntimeError('未配置 EXTERNAL_IMAGE_SEARCH_URL（请填写 external 图片搜索接口完整地址，例如 http://127.0.0.1:8008/v1/image_search）')
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    requested_k = max(1, int(k or 8))
    final_limit = max(1, min(requested_k, 24))
    external_request_limit = max(final_limit, min(max(final_limit * 3, 24), 60))
    payload = {
        'query': q,
        'q': q,
        'max_results': external_request_limit,
        'limit': external_request_limit,
    }
    data = _external_search_request_json(endpoint, headers, payload, timeout)
    rows = _external_image_search_extract_items(data)
    out = []
    seen = set()
    raw_limit = max(min(external_request_limit * 2, 120), external_request_limit)
    for it in rows[:raw_limit]:
        if not isinstance(it, dict):
            continue
        image_url = _normalize_image_url_value(
            it.get('image_url') or it.get('imageUrl') or it.get('img_src') or it.get('image') or it.get('url') or it.get('src') or ''
        )
        thumb = _normalize_image_url_value(
            it.get('thumbnail') or it.get('thumbnail_url') or it.get('thumbnailUrl') or it.get('thumb') or image_url
        )
        source_url = _normalize_image_url_value(
            it.get('source_url') or it.get('sourceUrl') or it.get('page_url') or it.get('pageUrl') or it.get('link') or it.get('href') or ''
        )
        if not source_url:
            raw_source = str(it.get('source') or '').strip()
            if raw_source.startswith('http://') or raw_source.startswith('https://') or raw_source.startswith('//'):
                source_url = _normalize_image_url_value(raw_source)
        key = _norm_image_result_url_for_dedup(image_url or thumb)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            'url': (image_url or thumb)[:500],
            'title': str(it.get('title') or it.get('name') or '')[:200],
            'thumbnail': thumb[:500],
            'source': source_url[:500],
            'source_url': source_url[:500],
            'provider': 'external',
            'engine': str(it.get('engine') or it.get('host') or '')[:120],
        })
    out = _rerank_image_results(out, user_text or q, subject=q, limit=final_limit)
    return out[:final_limit]


def web_search_external_images_multi(queries: list[str], k: int = 12, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
    qs = []
    seen_q = set()
    for raw in (queries or []):
        q = _normalize_search_query(str(raw or '').strip())
        if not q or q in seen_q:
            continue
        seen_q.add(q)
        qs.append(q)
        if len(qs) >= max(1, min(int(app_getenv('IMAGE_SEARCH_MAX_QUERIES', '3') or 3), 4)):
            break
    if not qs:
        return []
    per_query_k = max(8, min(int(k or 12), 32))
    merged = []
    for q in qs:
        rows = web_search_external_images(q, k=per_query_k, timeout=timeout, user_text=user_text or q)
        merged = _merge_unique_image_rows(merged, rows)
    limit = max(1, min(int(k or 12), 48))
    subject = qs[0]
    merged = _rerank_image_results(merged, user_text or subject, subject=subject, limit=limit)
    return merged[:limit]


def _uapipro_extract_search_items(payload) -> list[dict]:
    candidates = []
    if isinstance(payload, list):
        candidates.append(payload)
    elif isinstance(payload, dict):
        for key in ("results", "items", "list", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.append(value)
            elif isinstance(value, dict):
                for sub_key in ("results", "items", "list", "data"):
                    sub_value = value.get(sub_key)
                    if isinstance(sub_value, list):
                        candidates.append(sub_value)
    for rows in candidates:
        if isinstance(rows, list) and rows:
            return rows
    return []


def web_search_uapipro(query: str, k: int = 5, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    api_key = app_getenv("UAPIPRO_API_KEY", "").strip()
    base_url = app_getenv("UAPIPRO_BASE_URL", "https://uapis.cn/api/v1").strip().rstrip("/")
    if not api_key:
        raise RuntimeError("未配置 UAPIPRO_API_KEY")
    if not base_url:
        raise RuntimeError("未配置 UAPIPRO_BASE_URL")
    endpoint = base_url + "/search/aggregate"
    payload = {
        "query": q,
        "fetch_full": False,
        "timeout_ms": int(max(float(timeout), 1.0) * 1000),
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    t = httpx.Timeout(timeout, connect=min(4.0, float(timeout)))
    r = HTTPX_SEARCH.post(endpoint, headers=headers, json=payload, timeout=t)
    r.raise_for_status()
    data = r.json()
    rows = _uapipro_extract_search_items(data)
    results = []
    raw_limit = max(min(int(k or 5) * 4, 24), int(k or 5))
    for it in rows[:raw_limit]:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or it.get("link") or it.get("href") or it.get("source_url") or "").strip()
        if not url:
            continue
        title = str(it.get("title") or it.get("name") or it.get("headline") or "").strip()
        snippet = (
            it.get("snippet")
            or it.get("description")
            or it.get("summary")
            or it.get("content")
            or it.get("text")
            or ""
        )
        results.append({
            "title": title[:200],
            "url": url[:500],
            "snippet": _strip_html_tags(str(snippet or ""))[:400],
            "engines": ["uapipro"],
            "provider": "uapipro",
            "source": "uapipro",
        })
    results = _filter_search_results(results, user_text or q)
    results = _rerank_results(results, user_text or q)
    return results[:max(1, min(int(k), 10))]


def _search_with_provider(provider: str, query: str, k: int, *, user_text: str | None = None) -> list[dict]:
    name = _normalize_provider_name(provider, kind="search")
    if name == "serper":
        return _apply_search_result_defaults(web_search_serper(query, k=k, user_text=user_text), "serper")
    if name == "tavily":
        return _apply_search_result_defaults(web_search_tavily(query, k=k, user_text=user_text), "tavily")
    if name == "uapipro":
        return _apply_search_result_defaults(web_search_uapipro(query, k=k, user_text=user_text), "uapipro")
    if name == "external":
        return _apply_search_result_defaults(web_search_external(query, k=k, user_text=user_text), "external")
    if name == "searxng":
        return _apply_search_result_defaults(web_search_searxng(query, k=k, user_text=user_text), "searxng")
    if name == "whoogle":
        return _apply_search_result_defaults(web_search_whoogle(query, k=k, user_text=user_text), "whoogle")
    raise RuntimeError(f"unsupported_search_provider:{provider}")


def _search_images_with_provider(provider: str, queries: list[str], k: int, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
    name = _normalize_provider_name(provider, kind="image")
    if name == 'searxng':
        return web_search_searxng_images_multi(queries, k=k, timeout=timeout, user_text=user_text)
    if name == 'serper':
        return web_search_serper_images_multi(queries, k=k, timeout=timeout, user_text=user_text)
    if name == 'external':
        return web_search_external_images_multi(queries, k=k, timeout=timeout, user_text=user_text)
    raise RuntimeError(f'unsupported_image_provider:{provider}')


def web_search(query: str, k: int = 10) -> tuple[list[dict], str | None]:
    """搜索入口：由前端控制 provider，后端按本次请求执行。

    保持现有 provider 链路，但只在前一个 provider 异常或 0 结果时才继续 fallback。
    对明确提到的平台查询，会在普通 query 结果缺少目标站点时，温和补一轮 site: 定向召回，
    而不是一开始就写死走平台站点。
    """
    q = (query or "").strip()
    if not q:
        return [], "empty query"
    k = int(max(3, min(int(k), 20)))
    providers = _provider_chain(
        app_getenv("SEARCH_PROVIDER", "uapipro"),
        app_getenv("SEARCH_FALLBACK_PROVIDER", "none"),
        kind="search",
    )
    app_logger.warning(
        "[DEBUG_WEB_SEARCH_ENTRY] q=%r providers=%s search_provider=%r fallback=%r serper_key_len=%s",
        q,
        providers,
        app_getenv("SEARCH_PROVIDER", "uapipro"),
        app_getenv("SEARCH_FALLBACK_PROVIDER", "none"),
        len(app_getenv("SERPER_API_KEY", "").strip()),
    )

    def _run_single_query(q_try: str) -> tuple[list[dict], list[str], str | None]:
        merged_local = []
        errors_local = []
        success_provider_local = None
        min_effective = max(1, min(int(k), _cfg_int('WEB_SEARCH_MIN_EFFECTIVE_RESULTS', 3)))
        target_results = max(min_effective, min(int(k), _cfg_int('WEB_SEARCH_TARGET_RESULTS', 6)))
        last_provider = providers[-1] if providers else None
        for provider in providers:
            try:
                rows = _search_with_provider(provider, q_try, max(int(k), target_results), user_text=q)
            except Exception as e:
                errors_local.append(f"{provider}: {type(e).__name__}: {e}")
                continue
            if not rows:
                errors_local.append(f"{provider}: no results")
                continue
            merged_local = _merge_unique_web_rows(merged_local, rows)
            try:
                merged_local = _filter_search_results(merged_local, q)
                merged_local = _rerank_results(merged_local, q)
            except Exception:
                pass
            effective_hits = _effective_web_result_count(merged_local)
            success_provider_local = provider
            enough_for_stop = effective_hits >= min_effective and len(merged_local) >= target_results
            if enough_for_stop or provider == last_provider:
                app_logger.info("[WEB_SEARCH] provider ok=%s q=%r hits=%s effective=%s stop=%s", provider, q_try, len(merged_local), effective_hits, enough_for_stop or provider == last_provider)
                break
            app_logger.info("[WEB_SEARCH] provider=%s q=%r hits=%s effective=%s < target=%s; continue fallback", provider, q_try, len(merged_local), effective_hits, target_results)
        return merged_local, errors_local, success_provider_local

    merged, errors, success_provider = _run_single_query(q)

    need_social_retry = False
    bias_queries = _social_site_bias_queries(q)
    if bias_queries:
        if not merged:
            need_social_retry = True
        else:
            has_pref_host = any(_host_matches_preference((row or {}).get('url') or '', q) for row in merged)
            if not has_pref_host:
                top_n = merged[:max(1, min(len(merged), 5))]
                weak_count = len(merged) <= max(4, min(k, 6))
                weak_relevance = not any(_search_has_any_keyword(
                    f"{(row or {}).get('title') or ''} {(row or {}).get('snippet') or ''}",
                    ['抖音', 'douyin', 'b站', 'bilibili', '微博', 'weibo', '主页', '账号', '个人页', 'up主', '博主', '主播', '超话']
                ) for row in top_n)
                need_social_retry = weak_count or weak_relevance

    if need_social_retry:
        for bias_q in bias_queries[:1]:
            app_logger.info('[WEB_SEARCH] social-site-bias retry base=%r bias=%r', q, bias_q)
            more, more_errors, _ = _run_single_query(bias_q)
            if more_errors:
                errors.extend(more_errors)
            if not more:
                continue
            seen = {_norm_url_for_dedup(str((row or {}).get('url') or '').strip()) for row in (merged or []) if str((row or {}).get('url') or '').strip()}
            merged2 = list(merged or [])
            added = 0
            for row in more:
                u = str((row or {}).get('url') or '').strip()
                if not u:
                    continue
                nu = _norm_url_for_dedup(u)
                if nu in seen:
                    continue
                seen.add(nu)
                merged2.append(row)
                added += 1
            if added:
                try:
                    merged2 = _filter_search_results(merged2, q)
                    merged2 = _rerank_results(merged2, q)
                except Exception:
                    pass
                merged = merged2
            break

    if not merged:
        return [], ("; ".join(errors)[:300] if errors else "no results")

    err_text = None if not errors else ("; ".join(errors)[:300])
    if success_provider and errors:
        return merged[:k], err_text
    return merged[:k], err_text
