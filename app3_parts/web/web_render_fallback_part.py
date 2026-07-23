# Split from app3_parts/web/web_fetch_cloud_code_part.py.
# Purpose: generalized rendering, Tavily fetch, fallback policy, and smart fetch.
# Loaded by web_fetch_cloud_code_part.py via _exec_split_file(...), sharing the original global namespace.

def _strip_private_fetch_fields(out: dict | None) -> dict:
    if not isinstance(out, dict):
        return {}
    for key in ("_raw_html", "_raw_html_final_url", "_raw_html_content_type"):
        out.pop(key, None)
    return out


def _normalize_render_mode() -> str:
    mode = str(app_getenv("WEB_FETCH_RENDER_MODE", "") or "").strip().lower()
    if mode in {"off", "smart", "force"}:
        return mode
    if not _cfg_bool("WEB_FETCH_AUTO_RENDER", True):
        return "off"
    return "smart"


def _decode_html_bytes(raw: bytes) -> str:
    html = (raw or b"").decode("utf-8", errors="replace")
    try:
        m_charset = re.search(r'charset=["\"]?\s*([\-\w]+)', html[:4000], flags=re.I)
        if m_charset:
            enc = (m_charset.group(1) or "").strip()
            if enc and enc.lower() not in ("utf-8", "utf8"):
                html = (raw or b"").decode(enc, errors="replace")
    except Exception:
        pass
    return html


def _extract_full_text_from_html(html: str, max_chars: int = 24000) -> dict:
    html = html or ""
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
    html2 = re.sub(r"(?is)<(script|style|noscript|svg|canvas|iframe)[^>]*>.*?</\1>", " ", html)

    class _FullTextParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self._skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in {"script", "style", "noscript", "svg", "canvas", "iframe"}:
                self._skip += 1
            if tag in {"p", "br", "div", "li", "tr", "section", "article", "main", "aside", "header", "footer", "nav", "h1", "h2", "h3", "h4", "h5", "h6", "button", "a"}:
                self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag in {"script", "style", "noscript", "svg", "canvas", "iframe"} and self._skip > 0:
                self._skip -= 1
            if tag in {"p", "div", "li", "tr", "section", "article", "main", "aside", "header", "footer", "nav"}:
                self.parts.append("\n")

        def handle_data(self, data):
            if self._skip:
                return
            data = (data or "").strip()
            if data:
                self.parts.append(data)
                self.parts.append(" ")

    parser = _FullTextParser()
    try:
        parser.feed(html2)
    except Exception:
        pass
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?:\s*\n\s*){2,}", "\n\n", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…（内容过长已截断）"
    return {"title": title, "text": text}


def _clean_visible_text(text: str) -> str:
    t = (text or "").replace("\xa0", " ")
    t = re.sub(r"\r\n?", "\n", t)
    t = re.sub(r"[ \t\f\v]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _analyze_page_signals(html: str, url: str, main_text: str, full_text: str) -> dict:
    html_l = (html or "").lower()
    full_l = (full_text or "").lower()
    return {
        "url": url,
        "html_len": len(html or ""),
        "main_len": len(main_text or ""),
        "full_len": len(full_text or ""),
        "script_count": len(re.findall(r"<script\b", html_l, flags=re.I)),
        "link_count": len(re.findall(r"<a\b", html_l, flags=re.I)),
        "button_count": len(re.findall(r"<button\b", html_l, flags=re.I)),
        "has_article_tag": "<article" in html_l,
        "has_main_tag": "<main" in html_l,
        "has_next": ("__next" in html_l) or ("__next_data__" in html_l),
        "has_nuxt": "__nuxt" in html_l,
        "has_root_app": ('id="root"' in html_l) or ("id='root'" in html_l) or ('id="app"' in html_l) or ("id='app'" in html_l),
        "has_loading_words": any(x in html_l or x in full_l for x in ["loading", "please enable javascript", "just a moment", "正在加载", "加载中", "努力加载中"]),
        "has_price_words": any(x in (full_text or "") for x in ["¥", "￥", "$", "价格", "售价", "库存", "销量", "已售", "订阅", "套餐", "会员", "购买", "充值"]),
        "button_like": sum((full_text or "").count(x) for x in ["购买", "立即购买", "加入购物车", "立即开通", "订阅", "充值", "联系客服"]),
        "paragraph_count": len(re.findall(r"\n\n+", full_text or "")) + 1 if (full_text or "").strip() else 0,
    }


def _score_page_types(signals: dict) -> dict:
    article = store = spa = portal = 0
    if signals.get("has_article_tag"):
        article += 3
    if signals.get("has_main_tag"):
        article += 2
    if signals.get("main_len", 0) > 1200:
        article += 2
    if signals.get("paragraph_count", 0) >= 8:
        article += 1
    if signals.get("link_count", 0) < 80:
        article += 1

    if signals.get("has_price_words"):
        store += 3
    if signals.get("button_like", 0) >= 2:
        store += 2
    if signals.get("button_count", 0) >= 2:
        store += 1
    if signals.get("link_count", 0) > 30:
        store += 1

    if signals.get("has_next") or signals.get("has_nuxt") or signals.get("has_root_app"):
        spa += 3
    if signals.get("has_loading_words"):
        spa += 3
    if signals.get("html_len", 0) > 80000 and signals.get("main_len", 0) < 500:
        spa += 2
    if signals.get("script_count", 0) > 20:
        spa += 1

    if signals.get("link_count", 0) > 80:
        portal += 2
    if 200 < signals.get("main_len", 0) < 1200 and signals.get("full_len", 0) > max(1500, signals.get("main_len", 0) * 2):
        portal += 2
    if not signals.get("has_article_tag") and not signals.get("has_price_words"):
        portal += 1

    return {"article": article, "store": store, "spa": spa, "portal": portal}


def _detect_page_type(signals: dict) -> tuple[str, dict]:
    scores = _score_page_types(signals)
    return max(scores, key=scores.get), scores


def _should_render_generalized(signals: dict, scores: dict, render_mode: str = "smart") -> bool:
    if render_mode == "off":
        return False
    if render_mode == "force":
        return True
    if scores.get("spa", 0) >= 3:
        return True
    if signals.get("has_loading_words"):
        return True
    if signals.get("html_len", 0) > 60000 and signals.get("main_len", 0) < 500:
        return True
    return False


def _smart_trim_segments(text: str, max_chars: int = 6000) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    head = max_chars // 3
    middle = max_chars // 3
    tail = max_chars - head - middle
    mid_start = max(0, len(text) // 2 - middle // 2)
    mid_end = min(len(text), mid_start + middle)
    return (
        text[:head].rstrip()
        + "\n\n...[中间内容省略]...\n\n"
        + text[mid_start:mid_end].strip()
        + "\n\n...[后续内容省略]...\n\n"
        + text[-tail:].lstrip()
    ).strip()


def _structured_summary_from_hits(hits: list[dict], limit: int = 12) -> str:
    rows = []
    for h in hits or []:
        if not isinstance(h, dict):
            continue
        obj = h.get("obj")
        if obj is None:
            try:
                obj = json.loads((h.get("text") or "").strip())
            except Exception:
                obj = None
        if obj is None:
            continue
        try:
            rows.extend(_extract_products_from_json(obj))
        except Exception:
            pass
    uniq = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = (r.get("name") or "").strip()
        if not name:
            continue
        price = r.get("user_price") if r.get("user_price") is not None else r.get("price")
        uniq[(name, str(price))] = r
    rows = list(uniq.values())[:limit]
    if not rows:
        return ""
    lines = ["【自动提取的结构化信息】"]
    for r in rows:
        name = (r.get("name") or "").strip()
        price = r.get("user_price") if r.get("user_price") is not None else r.get("price")
        sold = r.get("order_sold")
        stock = r.get("stock")
        extras = []
        if price not in (None, ""):
            extras.append(f"价格：{price}")
        if sold not in (None, ""):
            extras.append(f"已售：{sold}")
        if stock not in (None, ""):
            extras.append(f"库存：{stock}")
        suffix = f"（{'，'.join(extras)}）" if extras else ""
        lines.append(f"- {name}{suffix}")
    api_urls = [str(h.get("url") or "").strip() for h in hits or [] if isinstance(h, dict) and str(h.get("url") or "").strip() and str(h.get("url") or "") != "__pw_cookies__"]
    if api_urls:
        lines.append("发现的接口：")
        for u in api_urls[:4]:
            lines.append(f"- {u}")
    return "\n".join(lines).strip()


def _merge_generalized_content(page_type: str, main_text: str, full_text: str, structured_text: str = "") -> str:
    main_text = (main_text or "").strip()
    full_text = (full_text or "").strip()
    structured_text = (structured_text or "").strip()
    if page_type == "article":
        primary = main_text if len(main_text) >= 800 else full_text
    elif page_type == "store":
        primary = full_text if len(full_text) >= max(800, len(main_text)) else main_text
    elif page_type == "spa":
        primary = full_text or main_text
    else:
        primary = full_text if len(full_text) > len(main_text) else main_text
    parts = []
    if structured_text:
        parts.append(structured_text)
    if primary:
        parts.append(primary)
    return "\n\n".join([p for p in parts if p]).strip()


def _playwright_render_generalized(url: str, timeout: float = 12.0, capture_json: bool = False) -> dict:
    if not _cfg_bool("PLAYWRIGHT_ENABLE", True):
        return {"html": "", "final_url": url, "visible_text": "", "hits": [], "warning": "playwright_disabled"}
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        return {"html": "", "final_url": url, "visible_text": "", "hits": [], "warning": f"playwright import failed: {e}"}

    hits = []
    max_items = int(app_getenv("WEB_FETCH_CAPTURE_MAX_ITEMS", "24") or "24")
    max_bytes = int(app_getenv("WEB_FETCH_CAPTURE_MAX_BYTES", "1200000") or "1200000")
    wait_ms = int(float(app_getenv("WEB_FETCH_RENDER_WAIT_MS", "1500") or "1500"))
    step_wait_ms = int(float(app_getenv("WEB_FETCH_RENDER_SCROLL_WAIT_MS", "800") or "800"))
    scroll_rounds = int(app_getenv("WEB_FETCH_RENDER_SCROLL_ROUNDS", "2") or "2")
    channel = (app_getenv("WEB_FETCH_PW_CHANNEL", "msedge") or "msedge").strip()
    ua = app_getenv("WEB_FETCH_UA", "").strip() or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    al = app_getenv("WEB_FETCH_ACCEPT_LANGUAGE", "zh-TW,zh;q=0.9,en;q=0.6").strip()
    used_bytes = 0

    def _maybe_capture(resp):
        nonlocal used_bytes
        if (not capture_json) or len(hits) >= max_items or used_bytes >= max_bytes:
            return
        try:
            h = resp.headers or {}
            ct = (h.get("content-type") or "").lower()
            u = (resp.url or "")
            u_low = u.lower()
            if resp.status != 200:
                return
            if not (("application/json" in ct) or ("text/json" in ct) or u_low.endswith(".json") or ("/api" in u_low) or ("graphql" in u_low)):
                return
            body = resp.body()
            if not isinstance(body, (bytes, bytearray)) or not body:
                return
            remain = max_bytes - used_bytes
            if remain <= 0:
                return
            if len(body) > remain:
                body = body[:remain]
            txt = body.decode("utf-8", errors="ignore")
            if not _looks_like_price_text(txt) and len(txt.strip()) < 80:
                return
            used_bytes += len(body)
            obj = None
            try:
                obj = json.loads(txt)
            except Exception:
                obj = None
            hits.append({"url": u, "content_type": ct, "status": resp.status, "text": txt[:200000], "obj": obj})
        except Exception:
            return

    browser = None
    page = None
    route_handler = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel=channel)
            page = browser.new_page(user_agent=ua, extra_http_headers={"Accept-Language": al})
            page.set_default_timeout(int(timeout * 1000))
            try:
                def route_handler(route):
                    try:
                        if route.request.resource_type in {"image", "font", "media"}:
                            route.abort()
                        else:
                            route.continue_()
                    except BaseException:
                        # Playwright may cancel in-flight route callbacks when a
                        # navigation timeout closes the page/context.  The fetch
                        # result is already handled by the main goto exception;
                        # suppress route-cleanup noise such as CancelledError /
                        # TargetClosedError here.
                        return
                page.route("**/*", route_handler)
            except Exception:
                pass
            if capture_json:
                page.on("response", _maybe_capture)
            page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            try:
                page.wait_for_timeout(wait_ms)
            except Exception:
                pass
            for _ in range(max(0, scroll_rounds)):
                try:
                    page.evaluate("window.scrollTo(0, document.body ? document.body.scrollHeight : 0)")
                except Exception:
                    pass
                try:
                    page.wait_for_timeout(step_wait_ms)
                except Exception:
                    pass
            try:
                visible_text = page.evaluate("document.body ? document.body.innerText : ''") or ""
            except Exception:
                visible_text = ""
            try:
                html = page.content() or ""
            except Exception:
                html = ""
            try:
                final_url = page.url or url
            except Exception:
                final_url = url
            try:
                cookies = page.context.cookies()
                hits.append({"url": "__pw_cookies__", "obj": {"cookies": cookies}})
            except Exception:
                pass
            try:
                if route_handler is not None:
                    page.unroute("**/*", route_handler)
            except BaseException:
                pass
            try:
                page.close()
            except BaseException:
                pass
            page = None
            try:
                browser.close()
            except BaseException:
                pass
            browser = None
        return {"html": html, "final_url": final_url, "visible_text": _clean_visible_text(visible_text), "hits": hits, "warning": ""}
    except Exception as e:
        return {"html": "", "final_url": url, "visible_text": "", "hits": hits, "warning": f"{type(e).__name__}: {e}"}
    finally:
        if page is not None:
            try:
                if route_handler is not None:
                    page.unroute("**/*", route_handler)
            except BaseException:
                pass
            try:
                page.close()
            except BaseException:
                pass
        if browser is not None:
            try:
                browser.close()
            except BaseException:
                pass


# ====== Cloud Connect (云端更新 + 实时数据调用) ======
CLOUD_CONNECT_ENABLED = app_getenv("CLOUD_CONNECT_ENABLED", "0").strip() != "0"
CLOUD_CONNECT_PROVIDER = app_getenv("CLOUD_CONNECT_PROVIDER", "mock").strip().lower()
CLOUD_CONNECT_ENDPOINT = app_getenv("CLOUD_CONNECT_ENDPOINT", "").strip()
CLOUD_CONNECT_TOKEN = app_getenv("CLOUD_CONNECT_TOKEN", "").strip()

def fetch_url_content_tavily(url: str, query: str = "", timeout: float = 12.0, max_chars: int = 12000) -> dict:
    api_key = app_getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 TAVILY_API_KEY")
    endpoint = app_getenv("TAVILY_EXTRACT_URL", "https://api.tavily.com/extract").strip() or "https://api.tavily.com/extract"
    payload = {
        "api_key": api_key,
        "urls": [url],
        "extract_depth": app_getenv("TAVILY_EXTRACT_DEPTH", "advanced").strip() or "advanced",
        "format": "markdown",
        "include_images": False,
    }
    t = httpx.Timeout(timeout, connect=min(4.0, float(timeout)))
    r = HTTPX_SEARCH.post(endpoint, json=payload, timeout=t)
    r.raise_for_status()
    data = r.json()
    results = data.get("results") if isinstance(data, dict) else None
    item = (results or [{}])[0] if isinstance(results, list) and results else {}
    raw_text = item.get("raw_content") or item.get("content") or item.get("text") or ""
    text = _clean_visible_text(str(raw_text or ""))
    return {
        "url": url,
        "final_url": str(item.get("url") or url),
        "content_type": "text/markdown",
        "title": str(item.get("title") or "")[:300],
        "text": truncate_text(text, max_chars=max_chars),
        "provider": "tavily",
        "source": "tavily",
    }


def _should_try_content_fallback(out: dict | None, query: str = "") -> bool:
    out = out or {}
    text = str(out.get("text") or "").strip()
    warning = str(out.get("warning") or "").strip().lower()
    page_type = str(out.get("page_type") or "").strip().lower()
    if len(text) >= max(600, min(1800, int(app_getenv("AUTO_WEB_PAGE_SNIPPET_CHARS", "1800") or 1800))):
        return False
    if any(token in warning for token in ["failed", "timeout", "empty", "forbidden", "blocked", "captcha", "render"]):
        return True
    if page_type in {"spa", "portal"} and len(text) < 1000:
        return True
    if query and _is_price_or_product_query(query) and len(text) < 900:
        return True
    return len(text) < 240


def _apply_content_fallback(url: str, out: dict, query: str = "", timeout: float = 12.0, max_chars: int = 12000) -> dict:
    providers = _provider_chain(
        app_getenv("CONTENT_PROVIDER", "native"),
        app_getenv("CONTENT_FALLBACK_PROVIDER", "tavily"),
        kind="content",
    )
    if "tavily" not in providers:
        return out
    if not _should_try_content_fallback(out, query=query):
        return out
    try:
        alt = fetch_url_content_tavily(url, query=query, timeout=timeout, max_chars=max_chars)
    except Exception as e:
        base = dict(out or {})
        warn = str(base.get("warning") or "").strip()
        extra = f"tavily fallback failed: {type(e).__name__}: {e}"
        base["warning"] = (warn + "；" + extra).strip("；") if warn else extra
        return base
    base = dict(out or {})
    alt_text = str(alt.get("text") or "").strip()
    base_text = str(base.get("text") or "").strip()
    if len(alt_text) >= len(base_text):
        base["text"] = truncate_text(alt_text, max_chars=max_chars)
    if not base.get("title") and alt.get("title"):
        base["title"] = alt.get("title")
    base["provider"] = alt.get("provider") or base.get("provider") or "native"
    base["content_source"] = alt.get("source") or alt.get("provider") or "tavily"
    warn = str(base.get("warning") or "").strip()
    note = "content fallback: tavily"
    base["warning"] = (warn + "；" + note).strip("；") if warn else note
    return base


def fetch_url_content_smart(url: str, query: str = "", timeout: float = 12.0, max_chars: int = 12000) -> dict:
    """按页面类型泛化的智能抓取：
    - 先快速静态抓取
    - 分析页面信号（文章 / 商城 / SPA / 门户）
    - 只在需要时用 Playwright 渲染
    - 主内容 / 整页可见文本 / 结构化 JSON 自动融合
    """
    q = (query or "").strip()
    try:
        # fetch_url/fetch_urls 的语义是读取调用方明确给出的页面，不是从该页继续
        # 自动翻页或遍历语言镜像。模型仍可自主继续调用抓页工具；这里仅禁止单个
        # URL 在工具内部隐式扩张成多页爬取，避免缓存、延迟和证据边界失控。
        out = fetch_url_content(
            url,
            timeout=timeout,
            max_chars=max_chars,
            max_pages=1,
            allow_playwright=False,
            include_html=True,
            direct_success_ok=True,
            enable_price_discovery=_is_price_or_product_query((q + " " + url).strip()),
        )
    except Exception as e:
        out = {"url": url, "final_url": url, "content_type": "", "title": "", "text": "", "warning": f"fast fetch failed: {type(e).__name__}: {e}"}

    cached_html = str(out.pop("_raw_html", "") or "")
    cached_html_final_url = str(out.pop("_raw_html_final_url", "") or "")
    cached_html_content_type = str(out.pop("_raw_html_content_type", "") or "")

    final_url = out.get("final_url") or url
    warning = (out.get("warning") or "").strip()
    content_type = (out.get("content_type") or "").lower()
    title = out.get("title") or ""
    fast_text = (out.get("text") or "").strip()

    # 首次直连已经明确失败时，直接交给现有内容提供商回退。旧逻辑会在同一
    # URL 上再执行一次 _fetch_raw_with_fallback，403/blocked/timeout 页面因此
    # 被重复请求并触发 host cooldown；这既没有增加证据，也会把一次抓页拖成
    # 数十秒。模型后续是否继续搜索或抓其他页面仍完全自主。
    explicit_fast_failure = any(
        token in warning.lower()
        for token in ("failed", "timeout", "forbidden", "blocked", "captcha", "status=403", " 403")
    )
    if explicit_fast_failure and not cached_html and len(fast_text) < 240:
        out["text"] = truncate_text(fast_text, max_chars=max_chars)
        if warning:
            out["warning"] = warning
        return _strip_private_fetch_fields(
            _apply_content_fallback(url, out, query=q, timeout=timeout, max_chars=max_chars)
        )

    if content_type and ("html" not in content_type) and (not content_type.startswith("text/")):
        out["text"] = truncate_text(fast_text, max_chars=max_chars)
        return _strip_private_fetch_fields(out)

    html = cached_html
    if cached_html_final_url:
        final_url = cached_html_final_url
    if cached_html_content_type:
        content_type = cached_html_content_type.lower()

    headers = {
        "User-Agent": app_getenv("WEB_FETCH_UA", "Mozilla/5.0"),
        "Accept-Language": app_getenv("WEB_FETCH_ACCEPT_LANGUAGE", "zh-TW,zh;q=0.9,en;q=0.6"),
    }
    if not html:
        try:
            raw, final2, ctype2, warn2 = _fetch_raw_with_fallback(final_url, timeout=timeout, headers=headers, tls_verify=tls_verify, direct_success_ok=True)
            if raw:
                final_url = final2 or final_url
                content_type = (ctype2 or content_type or "").lower()
                probe = raw[:2048].decode("utf-8", errors="ignore").lower()
                if ("html" in content_type) or ("<html" in probe):
                    html = _decode_html_bytes(raw)
            if warn2:
                warning = (warning + "；" if warning else "") + warn2
        except Exception as e:
            warning = (warning + "；" if warning else "") + f"html probe failed: {type(e).__name__}: {e}"

    if not html:
        out["text"] = truncate_text(fast_text, max_chars=max_chars)
        if warning:
            out["warning"] = warning
        return _strip_private_fetch_fields(_apply_content_fallback(url, out, query=q, timeout=timeout, max_chars=max_chars))

    main_static_ext = _extract_text_from_html(html, max_chars=max(max_chars * 2, 16000), url=final_url)
    main_static = (main_static_ext.get("text") or "").strip()
    full_static_obj = _extract_full_text_from_html(html, max_chars=max(max_chars * 3, 24000))
    full_static = (full_static_obj.get("text") or "").strip()
    if not title:
        title = full_static_obj.get("title") or out.get("title") or ""
    main_static_provider = str(main_static_ext.get("provider") or main_static_ext.get("content_source") or "native") or "native"
    if str(main_static_ext.get("warning") or "").strip():
        warning = (warning + "；" if warning else "") + str(main_static_ext.get("warning"))

    signals = _analyze_page_signals(html, final_url, main_static or fast_text, full_static or fast_text)
    page_type, scores = _detect_page_type(signals)
    render_mode = _normalize_render_mode()
    wants_full = bool(re.search(r"(抓全|全部|翻页|分页|滑动|滚动|加载更多|下一页|全站|所有)", q))
    wants_price = _is_price_or_product_query(q) or bool(re.search(r"(价格|定价|套餐|会员|开通|购买|订阅|充值|pricing|plans?)", q, flags=re.I))
    should_render = _should_render_generalized(signals, scores, render_mode=render_mode)
    if render_mode == "smart" and (wants_full or wants_price) and page_type in {"store", "spa", "portal"}:
        should_render = True

    rendered_main = ""
    rendered_full = ""
    hits = []
    if should_render:
        capture_json = _cfg_bool("WEB_FETCH_CAPTURE_JSON_APIS", False) or page_type in {"store", "spa"} or wants_price
        pw_timeout = min(float(timeout), float(app_getenv("WEB_FETCH_PW_CAPTURE_TIMEOUT", "8") or "8"))
        pw = _playwright_render_generalized(final_url, timeout=max(4.0, pw_timeout), capture_json=capture_json)
        if pw.get("final_url"):
            final_url = pw.get("final_url") or final_url
        if pw.get("warning"):
            warning = (warning + "；" if warning else "") + str(pw.get("warning"))
        hits = pw.get("hits") or []
        rendered_html = pw.get("html") or ""
        rendered_full = _clean_visible_text(pw.get("visible_text") or "")
        if rendered_html:
            rendered_main_ext = _extract_text_from_html(rendered_html, max_chars=max(max_chars * 2, 16000), url=final_url)
            rendered_main = (rendered_main_ext.get("text") or "").strip()
            if not rendered_full:
                rendered_full = (_extract_full_text_from_html(rendered_html, max_chars=max(max_chars * 3, 24000)).get("text") or "").strip()
            signals2 = _analyze_page_signals(rendered_html, final_url, rendered_main or rendered_full, rendered_full or rendered_main)
            page_type2, scores2 = _detect_page_type(signals2)
            if max(scores2.values()) >= max(scores.values()):
                page_type, scores = page_type2, scores2
                signals = signals2

    main_text = rendered_main if len(rendered_main) > len(main_static) else main_static
    full_text = rendered_full if len(rendered_full) > len(full_static) else full_static
    if not main_text:
        main_text = fast_text
    if not full_text:
        full_text = fast_text

    structured_text = _structured_summary_from_hits(hits)
    merged = _merge_generalized_content(page_type, main_text, full_text, structured_text)
    if not merged:
        merged = fast_text or main_text or full_text

    if q and (app_getenv("WEB_FETCH_SNIPPET_BY_QUERY", "1").strip() != "0"):
        try:
            lim = int(app_getenv("WEB_FETCH_QUERY_SNIPPET_CHARS", "2600") or "2600")
            merged = _snippet_by_query(merged, q, limit=max(lim, min(max_chars, 2600)))
        except Exception:
            pass

    merged = _smart_trim_segments(merged, max_chars=max_chars)
    result = {
        "url": url,
        "final_url": final_url,
        "content_type": content_type or out.get("content_type") or "text/html",
        "title": (title or out.get("title") or "")[:300],
        "text": merged,
        "warning": warning,
        "page_type": page_type,
        "signals": signals,
        "scores": scores,
        "provider": main_static_provider or "native",
        "content_source": main_static_provider or "native",
    }
    return _strip_private_fetch_fields(_apply_content_fallback(url, result, query=q, timeout=timeout, max_chars=max_chars))
