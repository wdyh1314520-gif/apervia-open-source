# Purpose: commodity API template enumeration and lightweight Playwright probes.
# Loaded through _exec_split_file(...), sharing the parent runtime namespace.

# ====== 全站通用：基于已发现的 commodity API 模板，强制枚举 categoryId（可选）======
def _extract_cookie_dict_from_pw(cookies_list):
    """Playwright cookies() -> requests cookie dict"""
    out = {}
    if not isinstance(cookies_list, list):
        return out
    for c in cookies_list:
        if isinstance(c, dict) and c.get("name") is not None:
            out[str(c.get("name"))] = str(c.get("value") or "")
    return out

def _commodity_api_template_from_url(u: str) -> tuple[str | None, str]:
    """
    如果 u 像 .../commodity?categoryId=2 返回 (template_url, param_name)
    template_url 中会保留其他 query，只把 category 参数值替换为 {cid}
    """
    try:
        if not u:
            return None, ""
        pu = urllib.parse.urlparse(u)
        q = urllib.parse.parse_qs(pu.query, keep_blank_values=True)
        for key in ("categoryId", "category_id", "catId", "cid"):
            if key in q:
                q2 = {k: v[:] for k, v in q.items()}
                q2[key] = ["{cid}"]
                new_query = urllib.parse.urlencode(q2, doseq=True)
                tpl = urllib.parse.urlunparse((pu.scheme, pu.netloc, pu.path, pu.params, new_query, pu.fragment))
                return tpl, key
        return None, ""
    except Exception:
        return None, ""

def _force_enum_categories_via_http(template_url: str, cookie_dict: dict, max_cid: int, timeout: float, debug: bool, referer: str = "") -> list[dict]:
    """
    通用：对 template_url 做 categoryId=1..max_cid 枚举，请求 JSON，返回 obj 列表（每个元素格式同 hits 中的 {url,obj}）
    """
    if not template_url or "{cid}" not in template_url:
        return []
    results: list[dict] = []
    headers = {}
    if referer:
        headers["Referer"] = referer
        try:
            headers["Origin"] = urllib.parse.urlparse(referer).scheme + "://" + urllib.parse.urlparse(referer).netloc
        except Exception:
            pass
    # UA/语言尽量跟你现有一致
    ua = app_getenv("WEB_FETCH_UA", "").strip()
    al = app_getenv("WEB_FETCH_ACCEPT_LANGUAGE", "").strip()
    if ua:
        headers["User-Agent"] = ua
    if al:
        headers["Accept-Language"] = al

    s = requests.Session()
    if cookie_dict:
        s.cookies.update(cookie_dict)

    empty_streak = 0
    max_empty_streak = int(app_getenv('COMMODITY_ENUM_MAX_EMPTY_STREAK','6') or 6)
    for cid in range(1, max_cid + 1):
        url = template_url.replace("{cid}", str(cid))
        try:
            r = s.get(url, headers=headers, timeout=timeout)
            ct = (r.headers.get("content-type") or "").lower()
            if debug:
                try:
                    # best-effort count
                    j = r.json()
                    data = j.get("data") if isinstance(j, dict) else None
                    n = len(data) if isinstance(data, list) else (len(data.get("list")) if isinstance(data, dict) and isinstance(data.get("list"), list) else None)
                except Exception:
                    n = None
                app_logger.debug(f"[API] GET {url} -> {r.status_code} (items={n})")
            if r.status_code != 200:
                continue
            txt = (r.text or "").strip()
            if not txt or not (txt.startswith("{") or txt.startswith("[")):
                continue
            try:
                obj = r.json()
            except Exception:
                continue
            # --- early stop on consecutive empty categories ---
            item_count = None
            try:
                data = obj.get('data') if isinstance(obj, dict) else None
                if isinstance(data, list):
                    item_count = len(data)
                elif isinstance(data, dict):
                    for k in ('list','items','rows','data'):
                        v = data.get(k)
                        if isinstance(v, list):
                            item_count = len(v)
                            break
            except Exception:
                item_count = None
            if item_count == 0:
                empty_streak += 1
            elif item_count is not None:
                empty_streak = 0
            if empty_streak >= max_empty_streak and cid >= 4:
                if debug:
                    app_logger.debug(f"[API] stop enum early at cid={cid} empty_streak={empty_streak}")
                break
            results.append({"url": url, "content_type": ct, "obj": obj})
        except Exception:
            continue
    return results
# ====== Optional Playwright rendering for JS-heavy pages (universal) ======
PLAYWRIGHT_TIMEOUT = float(app_getenv("PLAYWRIGHT_TIMEOUT", "18").strip() or "18")  # seconds

def _render_html_playwright(url: str, timeout: float | None = None) -> tuple[str, str | None]:
    """Render a page with Playwright to get JS-generated DOM.

    Prefer launching system Edge/Chrome channel to avoid missing bundled browsers.
    """
    if not _cfg_bool("PLAYWRIGHT_ENABLE", True):
        return "", "playwright_disabled"
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        return "", f"playwright_not_installed: {e}"

    to = float(timeout or app_getenv("PLAYWRIGHT_TIMEOUT", "18") or 18)
    channel = app_getenv("WEB_FETCH_PW_CHANNEL", "msedge").strip() or "msedge"
    wait_until = app_getenv("WEB_FETCH_PW_WAIT_UNTIL", "networkidle").strip() or "networkidle"
    ua = app_getenv("WEB_FETCH_UA", "").strip() or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    al = app_getenv("WEB_FETCH_ACCEPT_LANGUAGE", "zh-TW,zh;q=0.9,en;q=0.6").strip()

    try:
        with sync_playwright() as p:
            # 先尝试使用系统浏览器 channel（更不容易缺浏览器）
            browser = p.chromium.launch(headless=True, channel=channel)
            page = browser.new_page(user_agent=ua, extra_http_headers={"Accept-Language": al})
            page.set_default_timeout(int(to * 1000))
            page.goto(url, wait_until=wait_until, timeout=int(to * 1000))
            html = page.content() or ""
            final_url = page.url or url
            browser.close()
        return html, None
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"
