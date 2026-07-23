# Split from app3_parts/web/web_fetch_cloud_code_part.py.
# Purpose: price/product extraction, internal-link scoring, JSON capture, deep price fetch, and pagination helpers.
# Loaded by web_fetch_cloud_code_part.py via _exec_split_file(...), sharing the original global namespace.

# ====== Web Fetch Enhancements: price detection + deep crawl + playwright JSON capture ======
_PRICE_PATTERNS = [
    r"[¥￥]\s*\d",
    r"\bUSD\b\s*\d",
    r"\bUS\$\s*\d",
    r"\bNT\$\s*\d",
    r"\bCNY\b\s*\d",
    r"\bRMB\b\s*\d",
    r"\$\s*\d",
    r"\d+\s*(元|块|人民币|台币|新台币)",
]
_PRICE_REGEX = re.compile("|".join(_PRICE_PATTERNS), flags=re.I)

def _has_price_like(text: str) -> bool:
    t = (text or "")
    if not t:
        return False
    return _PRICE_REGEX.search(t) is not None

def _extract_internal_links(html_text: str, base_url: str, limit: int = 50) -> list[str]:
    """从 HTML 中提取同站点链接（去重、规范化），并过滤静态资源链接（ico/js/css/img/font 等）。"""
    base = base_url
    pu = urlparse(base)
    base_netloc = (pu.netloc or "").lower()
    if not base_netloc:
        return []

    # 常见静态资源后缀（避免误把 favicon/图片/CSS/JS 当成“价格页”）
    asset_ext = {
        ".ico", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
        ".css", ".js", ".mjs", ".map",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".mp3", ".mp4", ".avi", ".mov", ".m4a",
        ".zip", ".rar", ".7z", ".gz", ".tar",
        ".pdf",
    }

    def is_asset_url(u: str) -> bool:
        try:
            p = urlparse(u)
            path = (p.path or "").lower()
            # 过滤常见静态目录
            if any(seg in path for seg in ("/assets/", "/static/", "/dist/", "/build/", "/images/", "/img/", "/css/", "/js/")):
                return True
            # 过滤后缀
            for ext in asset_ext:
                if path.endswith(ext):
                    return True
            # 特殊：favicon
            if "favicon" in path:
                return True
        except Exception:
            return True
        return False

    links: list[str] = []
    seen: set[str] = set()

    # 简单 regex 抓取 href（避免引入额外依赖）
    for m in re.finditer(r'href\s*=\s*["\']([^"\'#\s>]+)', html_text or "", flags=re.I):
        href = (m.group(1) or "").strip()
        if not href:
            continue
        if href.startswith(("javascript:", "mailto:", "tel:")):
            continue

        u = urllib.parse.urljoin(base, href)
        # 去掉 fragment
        u = u.split("#", 1)[0]

        try:
            pu2 = urlparse(u)
        except Exception:
            continue
        if (pu2.scheme or "").lower() not in ("http", "https"):
            continue
        if (pu2.netloc or "").lower() != base_netloc:
            continue
        if is_asset_url(u):
            continue

        if u in seen:
            continue
        seen.add(u)
        links.append(u)
        if len(links) >= limit:
            break
    return links

def _score_link(u: str) -> int:
    path = (urlparse(u).path or "").lower()
    q = (urlparse(u).query or "").lower()
    s = path + "?" + q
    score = 0
    # 价格/商品相关关键词优先
    for kw, w in [
        ("price", 10), ("pricing", 10), ("plan", 8), ("套餐", 8), ("价格", 10),
        ("product", 9), ("goods", 9), ("item", 8), ("sku", 8), ("shop", 7), ("store", 7),
        ("category", 6), ("catalog", 6), ("list", 5), ("cart", 4), ("checkout", 4),
    ]:
        if kw in s:
            score += w
    # 太泛的首页/登录降低权重
    for kw, w in [("login", -3), ("signin", -3), ("register", -2), ("/#", -2)]:
        if kw in s:
            score += w
    return score

def _top_candidate_links(html_text: str, base_url: str, max_links: int = 12) -> list[str]:
    links = _extract_internal_links(html_text, base_url, limit=80)
    links = sorted(links, key=_score_link, reverse=True)
    return links[:max_links]

def _summarize_prices_from_json(obj) -> list[str]:
    """从 JSON 对象中提取疑似价格字段，返回若干行摘要。"""
    out: list[str] = []
    price_key_re = re.compile(r"(price|amount|money|cost|sale|pay|total|fee|yuan|rmb|cny|ntd|twd|usd)", re.I)

    def walk(x, path=""):
        if len(out) >= 60:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                p2 = f"{path}.{k}" if path else str(k)
                # key 命中 + value 看起来像数字/币值
                if price_key_re.search(str(k) or ""):
                    if isinstance(v, (int, float)) and v != 0:
                        out.append(f"{p2} = {v}")
                    elif isinstance(v, str) and _PRICE_REGEX.search(v):
                        out.append(f"{p2} = {v[:120]}")
                walk(v, p2)
        elif isinstance(x, list):
            for i, v in enumerate(x[:80]):
                walk(v, f"{path}[{i}]")
        else:
            return

    walk(obj)
    return out


def _extract_products_from_json(obj) -> list[dict]:
    """尝试把接口 JSON 里的商品/套餐抽成结构化行：name/title + price/user_price 等。

    返回形如：
      [{"name": "...", "cat": "...", "id": "...", "price": 18, "user_price": 17.8, "raw_index": "data[0]"}]
    """
    rows: list[dict] = []
    if obj is None:
        return rows

    # 常见字段名
    name_keys = ("name", "title", "goods_name", "product_name", "sku_name", "card_name", "plan_name")
    cat_keys = ("category", "category_name", "cat_name", "type_name")
    id_keys = ("id", "goods_id", "product_id", "sku_id", "item_id")

    def pick(d: dict, keys: tuple[str, ...]):
        for k in keys:
            if k in d and isinstance(d.get(k), (str, int)):
                return d.get(k)
        return None

    def is_price_dict(d: dict) -> bool:
        # 至少有 price/user_price 其一，且为数字
        for k in ("price", "user_price", "sale_price", "amount", "money", "cost", "userPrice", "salePrice", "memberPrice", "vipPrice", "payPrice", "discountPrice"):
            v = d.get(k)
            if isinstance(v, (int, float)) and v != 0:
                return True
            if isinstance(v, str):
                s = v.strip()
                m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
                if m:
                    try:
                        if float(m.group(0)) != 0:
                            return True
                    except Exception:
                        pass
        return False

    # 在 JSON 里找“像商品列表”的数组
    list_candidates: list[tuple[str, list]] = []

    def walk(x, path=""):
        if isinstance(x, dict):
            for k, v in x.items():
                p2 = f"{path}.{k}" if path else str(k)
                if isinstance(v, list) and v and all(isinstance(it, dict) for it in v[:5]):
                    # 这个 list 里如果很多元素有价格字段，视作候选
                    score = 0
                    for it in v[:20]:
                        if isinstance(it, dict) and is_price_dict(it):
                            score += 1
                    if score >= (1 if len(v) < 8 else 3):
                        list_candidates.append((p2, v))
                walk(v, p2)
        elif isinstance(x, list):
            for i, v in enumerate(x[:80]):
                walk(v, f"{path}[{i}]")

    walk(obj)

    # 取评分最高的若干个 list
    def cand_score(t):
        p, lst = t
        score = 0
        for it in lst[:30]:
            if isinstance(it, dict) and is_price_dict(it):
                score += 1
        # data/list/items 更常见
        p_low = p.lower()
        for kw, w in (("data", 2), ("list", 2), ("items", 2), ("goods", 2), ("product", 2), ("sku", 1)):
            if kw in p_low:
                score += w
        return score

    list_candidates = sorted(list_candidates, key=cand_score, reverse=True)[:4]

    for base_path, lst in list_candidates:
        for i, it in enumerate(lst[:200]):
            if not isinstance(it, dict):
                continue
            if not is_price_dict(it):
                continue
            name = pick(it, name_keys)
            cat = pick(it, cat_keys)
            _id = pick(it, id_keys)
            # 价格字段优先 price/user_price
            def num(v):
                if isinstance(v, (int, float)):
                    return v
                if isinstance(v, str):
                    s = v.strip()
                    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
                    if not m:
                        return None
                    try:
                        return float(m.group(0))
                    except Exception:
                        return None
                return None

            price = None
            for _k in ("price", "sale_price", "salePrice", "payPrice", "discountPrice", "amount", "money", "cost"):
                _v = num(it.get(_k))
                if _v is not None:
                    price = _v
                    break

            user_price = None
            for _k in ("user_price", "userPrice", "member_price", "memberPrice", "vip_price", "vipPrice"):
                _v = num(it.get(_k))
                if _v is not None:
                    user_price = _v
                    break
            row = {
                "name": str(name) if name is not None else "",
                "cat": str(cat) if cat is not None else "",
                "id": str(_id) if _id is not None else "",
                "price": price,
                "user_price": user_price,
                "raw_index": f"{base_path}[{i}]",
            }
            rows.append(row)

    # 去重（按 id+name+price）
    seen = set()
    uniq: list[dict] = []
    for r in rows:
        key = (r.get("id",""), r.get("name",""), r.get("price"), r.get("user_price"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq



# categoryId -> 人类可读分类名（通用：不做站点针对性映射）
_CATEGORY_ID_NAME: dict[str, str] = {}

def _category_label_from_url(url: str) -> str:
    """从接口 URL 里提取分类标签（通用：不做站点特定映射）。"""
    if not url:
        return ""
    m = re.search(r"[?&]categoryId=(\d+)", url)
    if not m:
        return ""
    cid = m.group(1)
    # 不做“ChatGPT/Gemini”等写死映射
    return f"分类 {cid}"

def _format_product_rows_by_category(rows: list[dict], max_lines: int = 80) -> list[str]:
    """按分类输出：分类标题 + 商品条目。"""
    cleaned = [r for r in rows if isinstance(r, dict)]

    # 给每行补一个分类名（如果接口没给）
    for r in cleaned:
        if not (r.get("cat") or "").strip():
            lbl = (r.get("cat_label") or "").strip()
            if not lbl and r.get("category_id"):
                lbl = _CATEGORY_ID_NAME.get(str(r.get("category_id")), f"categoryId={r.get('category_id')}")
            if lbl:
                r["cat"] = lbl

    def price_val(r):
        v = r.get("user_price") if r.get("user_price") is not None else r.get("price")
        try:
            return float(v)
        except Exception:
            return 0.0

    groups: dict[str, list[dict]] = {}
    for r in cleaned:
        cat = (r.get("cat") or "").strip() or "未分类"
        groups.setdefault(cat, []).append(r)

    order = {name: i for i, name in enumerate(_CATEGORY_ID_NAME.values())}
    cats = sorted(groups.keys(), key=lambda c: (order.get(c, 999), c))

    def fmt(x):
        if x is None:
            return ""
        try:
            fx = float(x)
            return str(int(fx)) if fx.is_integer() else str(fx)
        except Exception:
            return str(x)

    lines: list[str] = []
    count = 0
    for cat in cats:
        items = sorted(groups[cat], key=price_val)
        lines.append(f"## {cat}")
        for r in items:
            if count >= max_lines:
                return lines
            name = (r.get("name") or "").strip() or "(未命名商品)"
            _id = (r.get("id") or "").strip()
            price = r.get("price")
            user_price = r.get("user_price")
            up = fmt(user_price) if user_price is not None else fmt(price)
            op = fmt(price)
            id_part = f" (id={_id})" if _id else ""
            if op and up and up != op:
                lines.append(f"- {name}{id_part}：{up}（原价 {op}）")
            else:
                lines.append(f"- {name}{id_part}：{up or op}")
            count += 1
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return lines

def _format_product_rows(rows: list[dict], max_lines: int = 60) -> list[str]:
    """把商品行格式化为文本列表。"""
    lines: list[str] = []
    for r in rows[:max_lines]:
        name = (r.get("name") or "").strip()
        cat = (r.get("cat") or "").strip()
        rid = (r.get("id") or "").strip()
        price = r.get("price")
        user_price = r.get("user_price")
        idx = r.get("raw_index")
        left = ""
        if cat:
            left += f"[{cat}] "
        left += name if name else (idx or "item")
        if rid:
            left += f" (id={rid})"
        if price is not None and user_price is not None:
            lines.append(f"- {left}: price {price}, user_price {user_price}")
        elif price is not None:
            lines.append(f"- {left}: price {price}")
        elif user_price is not None:
            lines.append(f"- {left}: user_price {user_price}")
        else:
            lines.append(f"- {left}")
    return lines

def _looks_like_price_text(s: str) -> bool:
    if not s:
        return False
    t = s.lower()
    has_digit = any(ch.isdigit() for ch in t)
    if not has_digit:
        return False
    money_kws = ["price", "pricing", "plan", "plans", "amount", "cost", "fee", "yuan", "usd", "cny", "rmb", "¥", "￥", "元", "月", "年", "订阅", "套餐", "开通", "购买", "会员", "充值"]
    return any(k in t for k in money_kws)


def _playwright_capture_json(url: str, timeout: float = 12.0) -> tuple[str, str, list[dict], str | None]:
    """通用 Playwright 渲染 + 捕获 JSON/XHR 响应（不做站点针对性）。

    说明：
    - 仅在 WEB_FETCH_CAPTURE_JSON_APIS=1 时启用
    - 会抓取“像接口”的 JSON 响应，并尽量解析为 obj，便于后续抽取商品/价格
    - 会附带一次 cookies 快照（url="__pw_cookies__"），用于后续枚举/复用
    """
    if app_getenv("WEB_FETCH_CAPTURE_JSON_APIS", "0").strip() != "1":
        return "", url, [], "json api capture disabled"
    if not _cfg_bool("PLAYWRIGHT_ENABLE", True):
        return "", url, [], "playwright_disabled"
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        return "", url, [], f"playwright import failed: {e}"

    hits: list[dict] = []
    max_items = int(app_getenv("WEB_FETCH_CAPTURE_MAX_ITEMS", "30") or "30")
    max_bytes = int(app_getenv("WEB_FETCH_CAPTURE_MAX_BYTES", "1500000") or "1500000")
    cap_timeout = float(app_getenv("WEB_FETCH_PW_CAPTURE_TIMEOUT", str(timeout)) or timeout)
    wait_until = (app_getenv("WEB_FETCH_PW_WAIT_UNTIL", "domcontentloaded") or "domcontentloaded").strip()
    channel = (app_getenv("WEB_FETCH_PW_CHANNEL", "msedge") or "msedge").strip()
    ua = app_getenv("WEB_FETCH_UA", "").strip() or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    al = app_getenv("WEB_FETCH_ACCEPT_LANGUAGE", "zh-TW,zh;q=0.9,en;q=0.6").strip()

    budget_seconds = float(app_getenv("WEB_FETCH_FULL_MAX_SECONDS", "15") or "15")
    max_steps = int(app_getenv("WEB_FETCH_FULL_MAX_STEPS", "18") or "18")
    stall_rounds = int(app_getenv("WEB_FETCH_FULL_STALL_ROUNDS", "2") or "2")

    start_ts = time.time()
    used_bytes = 0

    def _try_parse_json(txt: str):
        if not txt:
            return None
        t = txt.strip()
        # 兼容 JSONP / 前缀噪声
        if t.startswith((")]}'", "while(1);", "for(;;);")):
            t = t.split("", 1)[-1].strip()
        # JSONP: foo(...)
        if "(" in t[:60] and t.endswith(")"):
            inner = t[t.find("(") + 1 : -1].strip()
            if inner.startswith(("{", "[")):
                t = inner
        if not (t.startswith("{") or t.startswith("[")):
            return None
        try:
            return json.loads(t)
        except Exception:
            return None

    def on_response(resp):
        nonlocal used_bytes
        if len(hits) >= max_items or used_bytes >= max_bytes:
            return
        try:
            h = resp.headers or {}
            ct = (h.get("content-type") or "").lower()
            u = (resp.url or "")
            u_low = u.lower()
            if resp.status != 200:
                return

            # 只尝试解析“像接口”的响应；保持通用，不写死路径
            is_jsonish = (
                ("application/json" in ct)
                or ("text/json" in ct)
                or u_low.endswith(".json")
                or ("graphql" in u_low)
                or ("/api" in u_low)
            )
            if not is_jsonish:
                return

            try:
                body = resp.body()
            except Exception:
                body = None
            if not isinstance(body, (bytes, bytearray)) or not body:
                return

            # 控制体积预算
            remain = max_bytes - used_bytes
            if remain <= 0:
                return
            if len(body) > remain:
                body = body[:remain]

            # 只保留“看起来像价格/套餐”的响应（避免 token 爆）
            try:
                txt = body.decode("utf-8", errors="ignore")
            except Exception:
                txt = ""
            if not _looks_like_price_text(txt):
                return

            used_bytes += len(body)
            obj = _try_parse_json(txt)
            hits.append({
                "url": u,
                "content_type": ct,
                "status": resp.status,
                "text": txt[:200000],  # 二次截断
                "obj": obj,
            })
        except Exception:
            return

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel=channel)
            page = browser.new_page(user_agent=ua, extra_http_headers={"Accept-Language": al})
            page.set_default_timeout(int(cap_timeout * 1000))
            page.on("response", on_response)

            # 导航 + 基础等待
            page.goto(url, wait_until=wait_until, timeout=int(cap_timeout * 1000))

            # 触发更多数据：轻量滚动 + 尝试点击“加载更多/下一页”
            steps = 0
            last_hit_cnt = len(hits)
            stall = 0
            while True:
                if (time.time() - start_ts) > budget_seconds:
                    break
                if steps >= max_steps:
                    break

                try:
                    page.mouse.wheel(0, 1200)
                except Exception:
                    pass
                try:
                    page.wait_for_timeout(600)
                except Exception:
                    pass

                # 尝试点一下“加载更多/下一页”
                if steps in (3, 7, 11):
                    try:
                        page.locator("text=/加载更多|更多|下一页|展开/i").first.click(timeout=800)
                    except Exception:
                        pass

                steps += 1

                # stall 判断：连续若干轮没有新增 hits 就停
                if len(hits) == last_hit_cnt:
                    stall += 1
                else:
                    stall = 0
                    last_hit_cnt = len(hits)
                if stall >= stall_rounds:
                    break

            try:
                html2 = page.content() or ""
            except Exception:
                html2 = ""
            try:
                final_url = page.url or url
            except Exception:
                final_url = url

            # 附带 cookies 快照（用于后续复用/枚举）
            try:
                cookies = page.context.cookies()
                hits.append({"url": "__pw_cookies__", "obj": {"cookies": cookies}})
            except Exception:
                pass

            browser.close()
            return html2, final_url, hits, None
    except Exception as e:
        return "", url, hits, f"{type(e).__name__}: {e}"

def _deep_fetch_prices_from_links(base_url: str, html_text: str, timeout: float, headers: dict) -> tuple[str, str]:
    """当首页没有价格时，尝试抓取同站点若干个候选链接，返回 (hit_url, hit_text) 或 ("","")。

    注意：会过滤明显的静态资源链接与非文本内容，避免误命中 favicon/图片等。
    """
    cand = _top_candidate_links(html_text, base_url, max_links=int(app_getenv("WEB_FETCH_DEEP_LINKS", "10") or "10"))
    for u in cand:
        try:
            raw2, final2, ctype2, warn2 = _fetch_raw_with_fallback(u, timeout=timeout, headers=headers, tls_verify=tls_verify)
            if not raw2:
                continue

            ctype2 = (ctype2 or "").lower()
            # 过滤非文本内容（图片/字体/二进制等）
            if ctype2.startswith("image/") or ctype2.startswith("audio/") or ctype2.startswith("video/"):
                continue
            if ctype2 in ("application/octet-stream", "application/x-binary"):
                continue

            # 解码（宽容）
            s2 = raw2.decode("utf-8", errors="replace")

            # 仅在 HTML/JSON/文本里找价格；否则跳过（避免把二进制当文本）
            is_html = ("html" in ctype2) or ("<html" in s2.lower())
            is_json = ("application/json" in ctype2) or s2.lstrip().startswith(("{", "["))
            is_text = ctype2.startswith("text/") or is_html or is_json
            if not is_text:
                continue

            if is_html:
                ext2 = _extract_text_from_html(s2, max_chars=12000)
                t2 = ext2.get("text", "")
            else:
                t2 = " ".join(s2.split())

            if _has_price_like(t2):
                return (final2 or u), t2
        except Exception:
            continue
    return "", ""

# ====== Web Fetch Enhancements: dynamic pages + pagination (non-breaking) ======
_PAGINATION_TEXT_HINTS = [
    "下一页", "下一頁", "下页", "下頁",
    "next", "older", "more", "→", "›", "»",
]
_PAGINATION_REL_RE = re.compile(r'(?is)<link[^>]+rel=["\']?next["\']?[^>]*>')
_PAGINATION_HREF_RE = re.compile(r'(?is)href=["\']([^"\']+)["\']')

def _looks_like_js_shell(html: str, extracted_text: str) -> bool:
    """判断是否像 SPA/动态页的“空壳”HTML：正文很短但包含典型打包/挂载特征。"""
    h = (html or "").lower()
    t = (extracted_text or "").strip()
    if len(t) >= 600:
        return False
    dynamic_markers = [
    "__NEXT_DATA__",
    "__next_data__",
    "id='__next'",
    "data-reactroot",
    "react",
    "webpack",
    "nuxt",
    "id='__nuxt'",
    "vite",
    "window.__",
    "app-root",
    "id='root'",
    "id='app'",
]
    if any(m.lower() in h for m in dynamic_markers):
        return True
    if "enable javascript" in h or "please enable javascript" in h:
        return True
    if "checking your browser" in h or "verify you are human" in h or "captcha" in h:
        return True
    return False

def _increment_page_param(u: str) -> str | None:
    """如果 URL query 里存在常见分页参数，尝试 +1。"""
    try:
        pu = urlparse(u)
        q = parse_qs(pu.query, keep_blank_values=True)
        keys = ["page", "p", "pn", "pageNo", "pageNum", "page_index", "pageIndex", "currentPage", "cur"]
        hit = None
        for k in keys:
            if k in q and q[k]:
                hit = k
                break
        if not hit:
            return None
        v0 = q[hit][0]
        try:
            n = int(str(v0).strip())
        except Exception:
            return None
        q[hit] = [str(n + 1)]
        new_query = urlencode([(k, vv) for k, vs in q.items() for vv in vs], doseq=True)
        return urlunparse((pu.scheme, pu.netloc, pu.path, pu.params, new_query, pu.fragment))
    except Exception:
        return None

def _find_next_page_url(base_url: str, html: str) -> str | None:
    """从 HTML 里尽量找“下一页”链接；找不到则尝试用 query 参数自增。"""
    h = html or ""
    m = _PAGINATION_REL_RE.search(h)
    if m:
        m2 = _PAGINATION_HREF_RE.search(m.group(0))
        if m2:
            return urljoin(base_url, m2.group(1).strip())
    for am in re.finditer(r'(?is)<a\b[^>]*>.*?</a>', h):
        blk = am.group(0)
        txt = re.sub(r'(?is)<[^>]+>', ' ', blk)
        txt = re.sub(r'\s+', ' ', txt).strip().lower()
        if 'rel="next"' in blk.lower() or any(hint in txt for hint in [x.lower() for x in _PAGINATION_TEXT_HINTS]):
            hm = _PAGINATION_HREF_RE.search(blk)
            if hm:
                href = hm.group(1).strip()
                if href and not href.lower().startswith("javascript:"):
                    return urljoin(base_url, href)
    return _increment_page_param(base_url)
