# HTTP URL validation, HTML extraction, fetch backends, and fallback fetching.

# ====== Web Page Fetch (真实网页访问 + 正文抽取) ======
def _is_private_host(host: str) -> bool:
    """尽量避免 SSRF：阻止 localhost/内网/保留地址（仅针对明显场景，非 DNS 解析级别）。"""
    if not host:
        return True
    h = host.strip().lower()
    if h in {"localhost", "localhost.localdomain"}:
        return True
    # 常见本地域名
    if h.endswith(".local") or h.endswith(".internal"):
        return True
    # 直接是 IP 的情况
    try:
        ip = ipaddress.ip_address(h)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
    except Exception:
        return False

def _validate_http_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        raise ValueError("url 不能为空")
    p = urlparse(u)
    if p.scheme not in {"http", "https"}:
        raise ValueError("仅支持 http/https")
    if _is_private_host(p.hostname or ""):
        raise ValueError("禁止访问本机/内网地址")
    return u

def _content_provider_name() -> str:
    provider = _normalize_provider_name(app_getenv("CONTENT_PROVIDER", "auto"), kind="content")
    if provider not in {"native", "auto", "trafilatura", "readability", "bs4"}:
        return "native"
    return provider



def _html_title_from_raw(html: str) -> str:
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
    try:
        html_mod = globals().get("html")
        return html_mod.unescape(title) if html_mod is not None and hasattr(html_mod, "unescape") else title
    except Exception:
        return title


def _extract_text_quality_score(text: str, title: str = "") -> float:
    t = _clean_visible_text(text or "")
    if not t:
        return 0.0
    length = len(t)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", t) if p.strip()]
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    unique_lines = len(set(lines)) if lines else 0
    repeated_penalty = max(0, len(lines) - unique_lines) * 8
    short_fragment_lines = sum(1 for ln in lines[:120] if len(ln) <= 6)
    score = 0.0
    score += min(length, 6000) / 6.0
    score += min(len(paragraphs), 18) * 45.0
    if title and title in t[:800]:
        score += 60.0
    if length < 180:
        score -= 260.0
    if len(paragraphs) <= 2 and length > 1500:
        score -= 120.0
    score -= repeated_penalty
    score -= short_fragment_lines * 6.0
    return score


def _truncate_extracted_text(text: str, max_chars: int = 12000) -> str:
    text = _clean_visible_text(text or "")
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…（内容过长已截断）"
    return text


def _extract_text_from_html_native(html: str, max_chars: int = 12000) -> dict:
    """标准库正文抽取：去掉 script/style/noscript 等内容后，提取纯文本。
    说明：不依赖第三方库，稳定可用；不是完美“主内容提取”，但足够支持“去看网页”。"""
    html = html or ""
    # title（粗略）
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I|re.S)
    if m:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()

    # remove noisy blocks
    html2 = re.sub(r"(?is)<(script|style|noscript|svg|canvas|iframe)[^>]*>.*?</\1>", " ", html)
    html2 = re.sub(r"(?is)<(header|footer|nav|aside|form)[^>]*>.*?</\1>", " ", html2)

    class _TextParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.out = []
            self._skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in {"script","style","noscript","svg","canvas","iframe"}:
                self._skip += 1
            if tag in {"p","br","div","li","tr","h1","h2","h3","h4","h5","h6"}:
                self.out.append("")

        def handle_endtag(self, tag):
            if tag in {"script","style","noscript","svg","canvas","iframe"} and self._skip > 0:
                self._skip -= 1
            if tag in {"p","div","li","tr"}:
                self.out.append("")

        def handle_data(self, data):
            if self._skip:
                return
            if data and data.strip():
                self.out.append(data.strip() + " ")

    parser = _TextParser()
    try:
        parser.feed(html2)
    except Exception:
        pass

    text = "".join(parser.out)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…（内容过长已截断）"
    return {"title": title, "text": text}



def _extract_text_from_html_bs4(html: str, max_chars: int = 12000, url: str = "") -> dict:
    title = _html_title_from_raw(html or "")
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception as e:
        return {"title": title, "text": "", "warning": f"bs4 not installed: {type(e).__name__}", "provider": "bs4", "content_source": "bs4"}
    try:
        soup = BeautifulSoup(html or "", "html.parser")
        if getattr(soup, "title", None):
            try:
                title = _clean_visible_text(soup.title.get_text(" ", strip=True)) or title
            except Exception:
                pass
        for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe", "template"]):
            try:
                tag.decompose()
            except Exception:
                pass
        for tag in soup(["nav", "header", "footer", "form"]):
            try:
                tag.decompose()
            except Exception:
                pass

        candidates = []
        selectors = [
            "article",
            "main",
            '[role="main"]',
            "#content",
            "#main",
            ".content",
            ".main",
            ".markdown-body",
            ".docs-content",
            ".doc-content",
            ".article-content",
            ".post-content",
        ]
        seen_ids = set()
        for sel in selectors:
            try:
                nodes = soup.select(sel)
            except Exception:
                nodes = []
            for node in nodes[:8]:
                try:
                    ident = id(node)
                    if ident in seen_ids:
                        continue
                    seen_ids.add(ident)
                    text = _clean_visible_text(node.get_text("\n", strip=True))
                    if text:
                        candidates.append((text, sel))
                except Exception:
                    continue
        try:
            body_node = soup.body or soup
            body_text = _clean_visible_text(body_node.get_text("\n", strip=True))
            if body_text:
                candidates.append((body_text, "body"))
        except Exception:
            pass
        if not candidates:
            return {"title": title, "text": "", "warning": "bs4 extracted empty text", "provider": "bs4", "content_source": "bs4"}
        best_text, best_source = max(candidates, key=lambda item: _extract_text_quality_score(item[0], title))
        return {
            "title": title,
            "text": _truncate_extracted_text(best_text, max_chars=max_chars),
            "warning": "",
            "provider": "bs4",
            "content_source": f"bs4:{best_source}",
        }
    except Exception as e:
        return {"title": title, "text": "", "warning": f"bs4 extract failed: {type(e).__name__}: {e}", "provider": "bs4", "content_source": "bs4"}


def _extract_text_from_html_readability(html: str, max_chars: int = 12000, url: str = "") -> dict:
    title = _html_title_from_raw(html or "")
    try:
        from readability import Document  # type: ignore
    except Exception as e:
        return {"title": title, "text": "", "warning": f"readability not installed: {type(e).__name__}", "provider": "readability", "content_source": "readability"}
    try:
        doc = Document(html or "", url=url or None)
        try:
            title = _clean_visible_text(doc.short_title() or doc.title() or title) or title
        except Exception:
            pass
        summary_html = doc.summary(html_partial=True) or ""
        native = _extract_text_from_html_native(summary_html, max_chars=max_chars)
        text = _truncate_extracted_text(native.get("text") or "", max_chars=max_chars)
        return {"title": title or native.get("title") or "", "text": text, "warning": "", "provider": "readability", "content_source": "readability"}
    except Exception as e:
        return {"title": title, "text": "", "warning": f"readability extract failed: {type(e).__name__}: {e}", "provider": "readability", "content_source": "readability"}


def _extract_text_from_html_trafilatura(html: str, max_chars: int = 12000, url: str = "") -> dict:
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
    if trafilatura is None:
        return {"title": title, "text": "", "warning": "trafilatura not installed", "provider": "trafilatura", "content_source": "trafilatura"}
    text = ""
    warning = ""
    try:
        text = trafilatura.extract(
            html or "",
            include_comments=False,
            include_tables=True,
            favor_precision=True,
            output_format="txt",
            url=(url or None),
        ) or ""
    except Exception as e:
        warning = f"trafilatura extract failed: {type(e).__name__}: {e}"
        text = ""
    text = _clean_visible_text(text)
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…（内容过长已截断）"
    return {"title": title, "text": text, "warning": warning, "provider": "trafilatura", "content_source": "trafilatura"}



def _extract_text_from_html(html: str, max_chars: int = 12000, url: str = "") -> dict:
    provider = _content_provider_name()
    native = _extract_text_from_html_native(html, max_chars=max_chars)
    native["provider"] = "native"
    native["content_source"] = "native"
    native["quality_score"] = _extract_text_quality_score(native.get("text") or "", native.get("title") or "")
    if provider == "native":
        return native

    trf = _extract_text_from_html_trafilatura(html, max_chars=max_chars, url=url)
    trf_text = str(trf.get("text") or "").strip()
    if trf_text:
        trf["quality_score"] = _extract_text_quality_score(trf_text, trf.get("title") or native.get("title") or "")
    else:
        trf["quality_score"] = 0.0

    bs4_ext = _extract_text_from_html_bs4(html, max_chars=max_chars, url=url)
    bs4_text = str(bs4_ext.get("text") or "").strip()
    if bs4_text:
        bs4_ext["quality_score"] = _extract_text_quality_score(bs4_text, bs4_ext.get("title") or native.get("title") or "")
    else:
        bs4_ext["quality_score"] = 0.0

    readability_ext = None
    if provider in {"auto", "readability"}:
        readability_ext = _extract_text_from_html_readability(html, max_chars=max_chars, url=url)
        readability_text = str(readability_ext.get("text") or "").strip()
        if readability_text:
            readability_ext["quality_score"] = _extract_text_quality_score(readability_text, readability_ext.get("title") or native.get("title") or "")
        else:
            readability_ext["quality_score"] = 0.0

    if provider == "trafilatura":
        if trf_text:
            if not trf.get("title") and native.get("title"):
                trf["title"] = native.get("title")
            return trf
        candidates = [bs4_ext, native]
        if readability_ext:
            candidates.insert(0, readability_ext)
        best = max(candidates, key=lambda item: float(item.get("quality_score") or 0.0))
        out = dict(best)
        warn_parts = [str(trf.get("warning") or "trafilatura unavailable").strip()]
        if out.get("warning"):
            warn_parts.append(str(out.get("warning") or ""))
        out["warning"] = "；".join([w for w in warn_parts if w])
        return out

    if provider == "readability":
        if readability_ext and str(readability_ext.get("text") or "").strip():
            if not readability_ext.get("title") and native.get("title"):
                readability_ext["title"] = native.get("title")
            return readability_ext
        best = max([bs4_ext, trf, native], key=lambda item: float(item.get("quality_score") or 0.0))
        out = dict(best)
        warn = str((readability_ext or {}).get("warning") or "readability unavailable").strip()
        if warn:
            out["warning"] = (str(out.get("warning") or "").strip() + "；" + warn).strip("；")
        return out

    if provider == "bs4":
        if bs4_text:
            if not bs4_ext.get("title") and native.get("title"):
                bs4_ext["title"] = native.get("title")
            return bs4_ext
        best = max([trf, native], key=lambda item: float(item.get("quality_score") or 0.0))
        out = dict(best)
        warn = str(bs4_ext.get("warning") or "bs4 unavailable").strip()
        if warn:
            out["warning"] = (str(out.get("warning") or "").strip() + "；" + warn).strip("；")
        return out

    candidates = [native, bs4_ext, trf]
    if readability_ext:
        candidates.append(readability_ext)
    usable = [c for c in candidates if str(c.get("text") or "").strip()]
    if not usable:
        out = dict(native)
        warnings = []
        for c in candidates:
            w = str(c.get("warning") or "").strip()
            if w and w not in warnings:
                warnings.append(w)
        if warnings:
            out["warning"] = "；".join(warnings[:3])
        return out

    best = max(usable, key=lambda item: float(item.get("quality_score") or 0.0))
    if not best.get("title") and native.get("title"):
        best["title"] = native.get("title")

    warnings = []
    for c in candidates:
        w = str(c.get("warning") or "").strip()
        if w and "not installed" not in w.lower() and w not in warnings:
            warnings.append(w)
    out = dict(best)
    if warnings and not str(out.get("warning") or "").strip():
        out["warning"] = "；".join(warnings[:3])
    out["extractors_tried"] = [str(c.get("provider") or c.get("content_source") or "") for c in candidates]
    return out



def _looks_like_block(status_code: int, text: str, headers: dict) -> bool:
    """粗略判断是否命中拦截/人机验证页（Cloudflare/JS challenge 等）。"""
    if status_code in (401, 403, 406, 429, 503):
        return True
    t = (text or "").lower()
    if "cloudflare" in t and ("attention required" in t or "checking your browser" in t):
        return True
    if "ddos" in t and "protection" in t:
        return True
    if "verify you are human" in t or "captcha" in t:
        return True
    # 有些站返回 200 但内容是“请启用 JS/Cookie”
    if "enable javascript" in t and ("browser" in t or "cookies" in t):
        return True
    return False



def _fetch_raw_httpx(url: str, timeout: float, headers: dict, tls_verify: bool) -> tuple[bytes, str, str, int, str | None]:
    """return (raw, final_url, content_type, status_code, err)"""
    try:
        ticket = _global_fetch_budget_acquire(url, task_type='web_page')
    except Exception as e:
        _host_fetch_record(url, error=f'httpx_budget:{type(e).__name__}', method='httpx', task_type='web_page')
        return b"", url, "", 0, f"httpx budget: {type(e).__name__}: {e}"
    try:
        _host_fetch_wait(url, reason='httpx')
        t = httpx.Timeout(timeout, connect=min(6.0, timeout), read=timeout, write=timeout, pool=timeout)
        trust_env_flag = app_getenv("WEB_FETCH_TRUST_ENV", "0").strip() != "0"
        if not hasattr(_fetch_raw_httpx, "_tls"):
            _fetch_raw_httpx._tls = threading.local()  # type: ignore[attr-defined]
        tls = getattr(_fetch_raw_httpx, "_tls")  # type: ignore[attr-defined]
        c = getattr(tls, "client", None)
        meta = getattr(tls, "meta", None)
        need_new = (
            c is None or not isinstance(meta, dict)
            or meta.get("verify") != bool(tls_verify)
            or meta.get("trust_env") != bool(trust_env_flag)
        )
        if need_new:
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass
            limits = httpx.Limits(
                max_connections=int(app_getenv("WEB_FETCH_MAX_CONNECTIONS", "16") or 16),
                max_keepalive_connections=int(app_getenv("WEB_FETCH_MAX_KEEPALIVE", "8") or 8),
                keepalive_expiry=float(app_getenv("WEB_FETCH_KEEPALIVE_EXPIRY", "15") or 15),
            )
            c = httpx.Client(
                timeout=t,
                verify=tls_verify,
                follow_redirects=True,
                trust_env=trust_env_flag,
                limits=limits,
            )
            tls.client = c
            tls.meta = {"verify": bool(tls_verify), "trust_env": bool(trust_env_flag)}
        r = c.get(url, headers=headers, timeout=t)
        raw = r.content or b""
        ctype = (r.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        final_url = str(r.url)
        _host_fetch_record(url, status_code=int(r.status_code), headers=dict(r.headers or {}), method='httpx', task_type='web_page')
        return raw, final_url, ctype, int(r.status_code), None
    except Exception as e:
        _host_fetch_record(url, error=f'httpx:{type(e).__name__}', method='httpx', task_type='web_page')
        return b"", url, "", 0, f"httpx: {type(e).__name__}: {e}"
    finally:
        _global_fetch_budget_release(ticket)


def _curl_fetch_text(url: str, timeout: float = 12.0) -> tuple[str, str | None]:
    """用系统 curl 拉取网页文本（兜底）。返回 (text, err)。
    - 不依赖任何“天气接口”，仅用于网页抓取。
    - 若系统无 curl 或执行失败，返回 err。
    """
    curl_path = shutil.which("curl")
    if not curl_path:
        return "", "curl not found"
    try:
        # --compressed 支持 gzip/br，-L 跟随重定向，-sS 静默但保留错误，--max-time 总超时
        # 用常见 UA，避免部分站点直接 403
        cmd = [
            curl_path,
            "-L",
            "-sS",
            "--compressed",
            "--max-time",
            str(max(1, int(timeout))),
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "-H", "Accept-Language: zh-TW,zh;q=0.9,en;q=0.6",
            url,
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if p.returncode != 0:
            err = (p.stderr or "").strip() or f"curl exit {p.returncode}"
            return "", err
        return (p.stdout or ""), None
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"


def _fetch_raw_curl(url: str, timeout: float) -> tuple[bytes, str, str, int, str | None]:
    """curl 兜底（best-effort）。"""
    ticket = _global_fetch_budget_acquire(url, task_type='web_page')
    try:
        txt, err = _curl_fetch_text(url, timeout=timeout)
        if err:
            return b"", url, "", 0, f"curl: {err}"
        _host_fetch_record(url, status_code=200, method='curl', task_type='web_page')
        return (txt or "").encode("utf-8", errors="ignore"), url, "text/html", 200, None
    finally:
        _global_fetch_budget_release(ticket)


def _fetch_raw_jina(url: str, timeout: float, tls_verify: bool) -> tuple[bytes, str, str, int, str | None]:
    """r.jina.ai 兜底：把网页转成可读文本/HTML（适合正文提取）。"""
    proxy = f"https://r.jina.ai/{url}"
    raw, final_url, ctype, status, err = _fetch_raw_httpx(
        proxy,
        timeout=timeout,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,*/*",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.6",
        },
        tls_verify=tls_verify,
    )
    if err:
        return b"", url, "", 0, f"jina: {err}"
    if raw and status and int(status) < 400:
        _host_fetch_record(url, status_code=int(status), method='jina', task_type='web_page')
    return raw, final_url, ctype or "text/html", status, None



def _fetch_raw_playwright(url: str, timeout: float) -> tuple[bytes, str, str, int, str | None]:
    """可选：真浏览器渲染。不开启不影响原功能。
    开关：WEB_FETCH_PLAYWRIGHT=1

    ⚠️ 浏览器优先用系统 Edge/Chrome，避免 ms-playwright 浏览器缺失导致启动失败：
      - WEB_FETCH_PW_CHANNEL=msedge（默认）/chrome
    """
    if app_getenv("WEB_FETCH_PLAYWRIGHT", "0").strip() == "0":
        return b"", url, "", 0, "playwright disabled"
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        return b"", url, "", 0, f"playwright import failed: {e}"
    ticket = None
    try:
        ticket = _global_fetch_budget_acquire(url, task_type='web_page')
        channel = app_getenv("WEB_FETCH_PW_CHANNEL", "msedge").strip() or "msedge"
        wait_until = app_getenv("WEB_FETCH_PW_WAIT_UNTIL", "networkidle").strip() or "networkidle"
        ua = app_getenv("WEB_FETCH_UA", "").strip() or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        al = app_getenv("WEB_FETCH_ACCEPT_LANGUAGE", "zh-CN,zh;q=0.9,en;q=0.6").strip()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel=channel)
            page = browser.new_page(user_agent=ua, extra_http_headers={"Accept-Language": al})
            page.goto(url, wait_until=wait_until, timeout=int(max(5.0, timeout) * 1000))
            html2 = page.content() or ""
            final_url = page.url or url
            browser.close()
            _host_fetch_record(url, status_code=200, method='playwright', task_type='web_page')
            return html2.encode("utf-8", errors="ignore"), final_url, "text/html", 200, None
    except Exception as e:
        _host_fetch_record(url, error=f'playwright:{type(e).__name__}', method='playwright', task_type='web_page')
        return b"", url, "", 0, f"playwright: {type(e).__name__}: {e}"
    finally:
        if ticket is not None:
            _global_fetch_budget_release(ticket)


def _fetch_raw_with_fallback(url: str, timeout: float, headers: dict, tls_verify: bool, direct_success_ok: bool = False) -> tuple[bytes, str, str, str]:
    """多策略兜底抓取：httpx -> curl -> jina -> (optional) playwright。
    return (raw, final_url, content_type, warning)

    direct_success_ok=True 用于 smart reader 的第一层本地快读：
    只要直连 httpx 已拿到 2xx/3xx 的非空页面，就先交给本地正文提取层判断，
    不在这一层提前升级到 r.jina.ai，避免同一页面直连成功后仍反复远程转正文。
    """
    strategy = _decide_host_fetch_strategy(
        url,
        task_type='web_page',
        allow_playwright=(app_getenv("WEB_FETCH_PLAYWRIGHT", "0").strip() != "0"),
    )
    prefer_provider = bool(strategy.get('prefer_content_fallback')) and not direct_success_ok
    prefer_playwright = bool(strategy.get('prefer_playwright')) and bool(strategy.get('allow_playwright', True))
    allow_playwright = bool(strategy.get('allow_playwright', True)) and (app_getenv("WEB_FETCH_PLAYWRIGHT", "0").strip() != "0")
    profile_note = "" if strategy.get('mode') == 'direct' else f"host profile: {strategy.get('reason') or strategy.get('mode')}"

    if strategy.get('mode') == 'cooldown_skip' and not direct_success_ok:
        raw3, final3, ctype3, status3, err3 = _fetch_raw_jina(url, timeout=timeout, tls_verify=tls_verify)
        if not err3 and raw3:
            note = profile_note or 'host cooldown'
            return raw3, final3, ctype3, note + ' -> jina ok'
        reason = f"host cooldown skip: {strategy.get('reason') or 'cooldown'}（jina={err3}）"
        return b"", url, "", reason

    if prefer_provider:
        raw3, final3, ctype3, status3, err3 = _fetch_raw_jina(url, timeout=timeout, tls_verify=tls_verify)
        if not err3 and raw3:
            note = profile_note or 'provider-first'
            return raw3, final3, ctype3, note + ' -> jina ok'
    else:
        err3 = None

    raw, final_url, ctype, status, err = _fetch_raw_httpx(url, timeout, headers, tls_verify=tls_verify)

    preview = ""
    try:
        preview = raw[:6000].decode("utf-8", errors="ignore")
    except Exception:
        preview = ""

    if not err and status < 400 and raw:
        if direct_success_ok:
            note = profile_note
            if _looks_like_block(status, preview, {}):
                note = (note + "；" if note else "") + f"httpx 直连成功但页面疑似不完整（status={status}），已先交给本地正文提取"
            return raw, final_url, ctype, note
        if not _looks_like_block(status, preview, {}):
            return raw, final_url, ctype, profile_note

    if err:
        warning = f"httpx 抓取失败：{err}，已启用兜底抓取"
    else:
        warning = f"httpx 命中疑似拦截页（status={status}），已启用兜底抓取"
    if profile_note:
        warning = profile_note + "；" + warning

    if prefer_playwright:
        raw_pw, final_pw, ctype_pw, status_pw, err_pw = _fetch_raw_playwright(url, timeout=timeout)
        if not err_pw and raw_pw:
            return raw_pw, final_pw, ctype_pw, warning + " -> playwright ok"
    else:
        err_pw = None

    raw2, final2, ctype2, status2, err2 = _fetch_raw_curl(url, timeout=timeout)
    if not err2 and raw2:
        try:
            preview2 = raw2[:6000].decode("utf-8", errors="ignore")
        except Exception:
            preview2 = ""
        if status2 < 400 and (direct_success_ok or not _looks_like_block(status2, preview2, {})):
            return raw2, final2, ctype2, warning + " -> curl ok"

    raw3, final3, ctype3, status3, err3 = _fetch_raw_jina(url, timeout=timeout, tls_verify=tls_verify)
    if not err3 and raw3:
        return raw3, final3, ctype3, warning + " -> jina ok"

    if allow_playwright and not prefer_playwright:
        raw4, final4, ctype4, status4, err4 = _fetch_raw_playwright(url, timeout=timeout)
        if not err4 and raw4:
            return raw4, final4, ctype4, warning + " -> playwright ok"
    else:
        err4 = err_pw if err_pw is not None else 'playwright skipped by strategy'

    reason = f"（curl={err2}; jina={err3}; playwright={err4}）"
    return raw or b"", final_url or url, ctype or "", warning + reason
