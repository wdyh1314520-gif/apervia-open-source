# GitHub repo bundle fetch and primary fetch_url_content entrypoint.

# ====== GitHub repo/README fast fetch (API -> raw) ======
GITHUB_TOKEN = app_getenv("GITHUB_TOKEN", "").strip()

def _parse_github_owner_repo(u: str):
    try:
        pu = urlparse((u or "").strip())
        if pu.scheme not in ("http","https"):
            return None, None
        host = (pu.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host != "github.com":
            return None, None
        parts = [p for p in (pu.path or "").split("/") if p]
        if len(parts) < 2:
            return None, None
        owner, repo = parts[0], parts[1]
        repo = repo.replace(".git","")
        return owner, repo
    except Exception:
        return None, None

def _gh_headers():
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": app_getenv("WEB_FETCH_UA", "").strip() or "Mozilla/5.0",
    }
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h

def _try_fetch_github_repo_bundle(url: str, timeout: float = 12.0, max_chars: int = 12000) -> dict | None:
    """If url is a GitHub repo, return extracted text bundle; else None."""
    owner, repo = _parse_github_owner_repo(url)
    if not owner or not repo:
        return None

    # 1) repo metadata
    repo_api = f"https://api.github.com/repos/{owner}/{repo}"
    repo_obj = None
    warn = ""
    try:
        repo_obj = HTTPX_WEB.get(repo_api, headers=_gh_headers(), timeout=timeout).json()
    except Exception as e:
        warn = f"GitHub API repo 失败：{type(e).__name__}: {e}"

    if not isinstance(repo_obj, dict) or not repo_obj.get("full_name"):
        # fallback: still try raw readme with main/master
        repo_obj = {"full_name": f"{owner}/{repo}", "html_url": f"https://github.com/{owner}/{repo}", "default_branch": "main"}

    default_branch = (repo_obj.get("default_branch") or "main").strip() or "main"

    # 2) README via API
    readme_text = ""
    readme_src = ""
    try:
        readme_api = f"https://api.github.com/repos/{owner}/{repo}/readme"
        r = HTTPX_WEB.get(readme_api, headers=_gh_headers(), timeout=timeout)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, dict) and j.get("encoding") == "base64" and j.get("content"):
                raw = base64.b64decode(j["content"])
                readme_text = raw.decode("utf-8", errors="replace")
                readme_src = "api"
    except Exception:
        pass

    # 3) raw fallback
    if not readme_text:
        branches = [default_branch]
        for b in ("main","master"):
            if b not in branches:
                branches.append(b)
        filenames = ("README.md","README.MD","README.rst","README.txt","readme.md","Readme.md")
        for br in branches:
            for fn in filenames:
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{br}/{fn}"
                try:
                    rr = HTTPX_WEB.get(raw_url, headers={"User-Agent": app_getenv("WEB_FETCH_UA","Mozilla/5.0")}, timeout=min(timeout, 10.0))
                    if rr.status_code == 200:
                        t = (rr.text or "").strip()
                        if len(t) > 20:
                            readme_text = rr.text
                            readme_src = "raw"
                            break
                except Exception:
                    continue
            if readme_text:
                break

    # Build injected text (compact, model-friendly)
    meta_lines = []
    meta_lines.append(f"GitHub 仓库：{repo_obj.get('full_name')}")
    if repo_obj.get("description"):
        meta_lines.append(f"描述：{repo_obj.get('description')}")
    if repo_obj.get("stargazers_count") is not None:
        meta_lines.append(f"Stars：{repo_obj.get('stargazers_count')}  Forks：{repo_obj.get('forks_count')}")
    if repo_obj.get("language"):
        meta_lines.append(f"主要语言：{repo_obj.get('language')}")
    if repo_obj.get("updated_at"):
        meta_lines.append(f"更新时间：{repo_obj.get('updated_at')}")
    meta_lines.append(f"默认分支：{default_branch}")
    if readme_src:
        meta_lines.append(f"README 来源：{readme_src}")
    if warn:
        meta_lines.append(f"警告：{warn}")

    body = "\n".join(meta_lines).strip() + "\n\n"
    if readme_text:
        body += "=== README（节选）===\n" + readme_text.strip()
    else:
        body += "（未获取到 README：可能不存在/限流/私有/README 文件名不常见）"

    body = truncate_text(body, max_chars=max_chars)

    return {
        "url": url,
        "final_url": repo_obj.get("html_url") or url,
        "content_type": "text/plain; github-repo",
        "title": repo_obj.get("full_name") or f"{owner}/{repo}",
        "text": body,
        "warning": warn,
    }

def fetch_url_content(
    url: str,
    timeout: float = 15.0,
    max_chars: int = 12000,
    max_bytes: int = 2_000_000,
    max_pages: int | None = None,
    allow_playwright: bool = True,
    include_html: bool = False,
    direct_success_ok: bool = False,
    enable_price_discovery: bool = True,
) -> dict:
    """抓取网页并提取正文。支持 HTML / text / PDF。
    返回：
      {url, final_url, content_type, title, text, warning}
    """
    url = _validate_http_url(url)

    # GitHub repo special-case: use API/raw to reliably get README & metadata
    gh = _try_fetch_github_repo_bundle(url, timeout=timeout, max_chars=max_chars)
    if gh:
        return gh

    headers = {
        "User-Agent": app_getenv("WEB_FETCH_UA", "").strip() or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.6",
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    }
    raw, final_url, ctype, warning = _fetch_raw_with_fallback(url, timeout=timeout, headers=headers, tls_verify=tls_verify, direct_success_ok=direct_success_ok)

    # size guard (best-effort)
    raw = raw or b""
    if not raw:
        raise RuntimeError(warning or "抓取失败（无响应内容）")
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
        warning = (warning + "；" if warning else "") + f"响应过大，已截断到 {max_bytes} bytes（可能影响解析）"

# PDF
    if "application/pdf" in ctype or final_url.lower().endswith(".pdf"):
        # Some sites mislabel HTML as PDF; avoid slow/noisy parsing in that case.
        if not _looks_like_pdf_bytes(raw):
            try:
                txt2 = raw.decode("utf-8", errors="ignore")
            except Exception:
                txt2 = ""
            txt2 = _strip_html_tags(txt2)
            txt2 = truncate_text(txt2 or "", max_chars=max_chars)
            return {
            "url": url,
            "final_url": final_url,
            "content_type": ctype or "application/pdf",
            "title": "",
            "text": txt2,
            "warning": (warning + "；" if warning else "") + "内容不是有效PDF，已按文本解析",
        }

        # Valid PDF -> extract text
        try:
            txt = read_pdf(raw)
        except Exception as e:
            raise RuntimeError(f"PDF 解析失败：{type(e).__name__}: {e}")
        txt = truncate_text(txt or "", max_chars=max_chars)
        return {
            "url": url,
            "final_url": final_url,
            "content_type": ctype or "application/pdf",
            "title": "",
            "text": txt,
            "warning": warning,
        }


    # HTML/text
    # decode (no httpx Response object here, so no r.encoding)
    # 先用 UTF-8 宽容解码，再尝试从 meta charset 纠正
    html = _decode_html_bytes(raw)
    if "html" in ctype or "<html" in html.lower():

        # JS-heavy pages: if visible text is tiny but scripts are many, try Playwright to render DOM once.
        # 性能优化：
        # - allow_playwright=False 时完全跳过（用于“快抓/批量抓取”）
        # - 自动渲染再加一层开关 WEB_FETCH_AUTO_RENDER（默认开）
        if _cfg_bool("PLAYWRIGHT_ENABLE", True) and allow_playwright and _cfg_bool("WEB_FETCH_AUTO_RENDER", True):

            try:

                plain_probe = _strip_html_tags(html)[:2500]

                script_cnt = len(re.findall(r"<script\b", html, flags=re.I))

                is_spa = ("__NEXT_DATA__" in html) or ("nuxt" in html.lower()) or ("data-reactroot" in html.lower())

                if (len(plain_probe.strip()) < 220 and script_cnt >= 8) or is_spa:

                    # 自动渲染用更短超时，避免卡很久
                    pw_to = float(app_getenv("WEB_FETCH_AUTO_RENDER_TIMEOUT", "8") or 8)
                    html2, _perr = _render_html_playwright(final_url, timeout=min(float(timeout), pw_to))

                    if html2 and len(html2) > len(html):

                        html = html2

                        warning = (warning + "；" if warning else "") + "已使用 Playwright 渲染补全动态内容"

            except Exception:

                pass


        # 如果启用了“捕获接口 JSON”，在疑似 SPA/动态页时用 Playwright 同时抓 DOM + XHR JSON（用于抽取价格/套餐）
        pw_hits: list[dict] = []
        if _cfg_bool("PLAYWRIGHT_ENABLE", True) and allow_playwright and _cfg_bool("WEB_FETCH_CAPTURE_JSON_APIS", False):
            try:
                plain_probe2 = _strip_html_tags(html)[:2500]
                script_cnt2 = len(re.findall(r"<script\b", html, flags=re.I))
                is_spa2 = ("__NEXT_DATA__" in html) or ("nuxt" in html.lower()) or ("data-reactroot" in html.lower()) or ("id=\"root\"" in html.lower()) or ("id='root'" in html.lower())
                if (len((plain_probe2 or '').strip()) < 260 and script_cnt2 >= 6) or is_spa2:
                    pw_to = float(app_getenv("WEB_FETCH_PW_CAPTURE_TIMEOUT", "8") or 8)
                    html_pw, final_pw, hits, perr = _playwright_capture_json(final_url, timeout=min(float(timeout), pw_to))
                    if html_pw and len(html_pw) > len(html):
                        html = html_pw
                        final_url = final_pw or final_url
                        warning = (warning + "；" if warning else "") + "已使用 Playwright 渲染并捕获接口数据"
                    if hits:
                        pw_hits = hits
                    if perr and not warning:
                        warning = perr
            except Exception:
                pass

        ext = _extract_text_from_html(html, max_chars=max_chars, url=final_url)

        text_main = ext.get("text", "") or ""

        # 若 Playwright 捕获到了接口 JSON：尝试抽取商品/价格清单，附加到正文末尾（仅少量，防止 token 爆）
        if pw_hits:
            try:
                all_rows: list[dict] = []
                for h in pw_hits:
                    if not isinstance(h, dict):
                        continue
                    obj = h.get("obj")
                    if obj is None:
                        # 尝试从 text 再 parse 一次
                        try:
                            obj = json.loads((h.get("text") or "").strip())
                        except Exception:
                            obj = None
                    if obj is None:
                        continue
                    rows = _extract_products_from_json(obj)
                    if rows:
                        all_rows.extend(rows)

                # 去重 + 排序
                uniq = {}
                for r in all_rows:
                    if not isinstance(r, dict):
                        continue
                    name = (r.get("name") or "").strip()
                    if not name:
                        continue
                    price = r.get("user_price") if r.get("user_price") is not None else r.get("price")
                    key = (name, str(price))
                    uniq[key] = r
                rows_final = list(uniq.values())

                def _rk(r):
                    try:
                        p = r.get("user_price") if r.get("user_price") is not None else r.get("price")
                        p = float(p) if p is not None else 0.0
                    except Exception:
                        p = 0.0
                    return (0 if (r.get("name") or '').strip() else 1, p)

                rows_final.sort(key=_rk)
                rows_final = rows_final[:40]

                if rows_final:
                    lines = []
                    for r in rows_final:
                        nm = (r.get("name") or "").strip()
                        if not nm:
                            continue
                        p = r.get("user_price") if r.get("user_price") is not None else r.get("price")
                        cat = (r.get("cat") or "").strip()
                        if cat:
                            lines.append(f"- [{cat}] {nm} — {p}")
                        else:
                            lines.append(f"- {nm} — {p}")
                    if lines:
                        text_main = (text_main.rstrip() + "\n\n【接口捕获到的商品/价格（自动提取）】" + "".join(lines)).strip()
            except Exception:
                pass
        warn_extra = ""

        # 商品价格深挖只属于商品/价格读取语义。普通新闻、文档页面没有价格时，旧逻辑也会
        # 遍历同站链接，容易把语言镜像误当成候选页并造成一次 fetch_url 隐式抓取几十页。
        if enable_price_discovery and not _has_price_like(text_main):
            hit_url, hit_text = _deep_fetch_prices_from_links(final_url, html, timeout=timeout, headers=headers)
            if hit_url and hit_text:
                warn_extra = (warn_extra + "；" if warn_extra else "") + f"已自动深挖同站链接并在 {hit_url} 找到疑似价格信息"
                # 合并：把命中的价格页摘要追加到正文（不破坏原有字段）
                prefix = "" if text_main else ""
                text_main = (
                    text_main
                    + prefix
                    + f"[深挖命中页面] {hit_url}"
                    + truncate_text(hit_text, max_chars=max_chars)
                )

                # Enhancement B: playwright capture JSON/XHR when still no price
        if enable_price_discovery and not _has_price_like(text_main) and app_getenv("WEB_FETCH_PLAYWRIGHT", "0").strip() != "0":
            html_pw, final_pw, hits, err_pw = _playwright_capture_json(final_url, timeout=max(timeout, 20.0))
            if err_pw:
                warn_extra = (warn_extra + "；" if warn_extra else "") + f"playwright 接口捕获失败：{err_pw}"
            elif hits:
                # A) 尝试把“价格 -> 商品名/套餐名”对应关系抽出来
                all_rows: list[dict] = []
                api_urls: list[str] = []
                # 从 Playwright 捕获结果里拿 cookies（如果有）
                pw_cookie_dict: dict = {}
                for _h in hits:
                    if isinstance(_h, dict) and str(_h.get("url")) == "__pw_cookies__":
                        try:
                            pw_cookie_dict = _extract_cookie_dict_from_pw((_h.get("obj") or {}).get("cookies"))
                        except Exception:
                            pw_cookie_dict = {}
                        break

                for h in hits:
                    if not isinstance(h, dict):
                        continue
                    api_urls.append(str(h.get("url") or ""))
                    obj = h.get("obj")
                    if obj is None:
                        continue
                    rows = _extract_products_from_json(obj)
                    # 从接口 URL 推断分类名，补到行里（如果接口没给 category 字段）
                    cat_label = _category_label_from_url(str(h.get("url") or ""))
                    if rows and cat_label:
                        for rr in rows:
                            if isinstance(rr, dict) and not (rr.get("cat") or "").strip():
                                rr["cat"] = cat_label
                    if rows:
                        all_rows.extend(rows)

                # 全站通用：如果检测到 commodity API 模板，可强制枚举更多 categoryId（不依赖页面 Tab 是否点击）
                if app_getenv("WEB_FETCH_FORCE_ENUM_CATEGORIES", "0").strip() == "1":
                    max_cid = int(app_getenv("WEB_FETCH_FORCE_ENUM_MAX", "20") or "20")
                    debug_api = app_getenv("WEB_FETCH_DEBUG_API", "0").strip() == "1"
                    tpl = None
                    for u in api_urls:
                        tpl2, _ = _commodity_api_template_from_url(u)
                        if tpl2:
                            tpl = tpl2
                            break
                    if tpl:
                        extra_hits = _force_enum_categories_via_http(
                            template_url=tpl,
                            cookie_dict=pw_cookie_dict,
                            max_cid=max_cid,
                            timeout=max(timeout, 12.0),
                            debug=debug_api,
                            referer=final_pw or final_url,
                        )
                        if extra_hits:
                            for eh in extra_hits:
                                obj2 = eh.get("obj")
                                rows2 = _extract_products_from_json(obj2) if obj2 is not None else []
                                if rows2:
                                    all_rows.extend(rows2)

                # 排序：优先有 name 的、再按 user_price/price
                def row_key(r):
                    has_name = 1 if (r.get("name") or "").strip() else 0
                    price = r.get("user_price") if r.get("user_price") is not None else r.get("price")
                    try:
                        price = float(price) if price is not None else 0.0
                    except Exception:
                        price = 0.0
                    return (-has_name, price)

                all_rows = sorted(all_rows, key=row_key)

                # B) 输出清单（默认最多 80 行）
                if all_rows:
                    lines = _format_product_rows_by_category(all_rows, max_lines=int(app_getenv("WEB_FETCH_PW_MAX_PRODUCTS", "80") or "80"))
                    warn_extra = (warn_extra + "；" if warn_extra else "") + f"已从页面接口响应中提取到商品价格清单（{len(all_rows)}条，已展示前{min(len(lines), len(all_rows), 80)}条）"
                    prefix = "" if text_main else ""
                    text_main = text_main + prefix + "[接口商品价格清单]" + "".join(lines)
                else:
                    # 兜底：只输出价格字段线索
                    hints: list[str] = []
                    for h in hits:
                        obj = h.get("obj") if isinstance(h, dict) else h
                        if obj is None:
                            continue
                        hints.extend(_summarize_prices_from_json(obj))
                        if len(hints) >= 60:
                            break
                    if hints:
                        warn_extra = (warn_extra + "；" if warn_extra else "") + f"已从页面接口响应中提取到疑似价格字段（{len(hints)}条）"
                        prefix = "" if text_main else ""
                        text_main = text_main + prefix + "[接口价格线索]" + "".join(hints[:60])

                # 追加：接口来源（最多 8 条，方便定位/复现）
                api_urls = [u for u in api_urls if u]
                if api_urls:
                    seen_u: list[str] = []
                    for u in api_urls:
                        if u not in seen_u:
                            seen_u.append(u)
                    show_u = seen_u[:8]
                    prefix = "" if text_main else ""
                    text_main = text_main + prefix + "[接口来源]" + "".join([f"- {u}" for u in show_u])

        warning2 = warning
        if warn_extra:
            warning2 = (warning2 + "；" if warning2 else "") + warn_extra


        # Enhancement B: pagination (best-effort). Only follows "next" or increments common page params.
        try:
            mp = max_pages
            if mp is None:
                mp = int(app_getenv("WEB_FETCH_MAX_PAGES", "1") or 1)
            mp = max(1, min(int(mp), 10))
        except Exception:
            mp = 1

        if mp > 1:
            seen_pages = set([final_url])
            per_chars = max(1500, int(max_chars // mp))
            next_url = _find_next_page_url(final_url, html)
            got = 1
            for pi in range(2, mp + 1):
                if not next_url or next_url in seen_pages:
                    break
                seen_pages.add(next_url)
                try:
                    pg = fetch_url_content(
                        next_url,
                        timeout=timeout,
                        max_chars=per_chars,
                        max_bytes=max_bytes,
                        max_pages=1,
                        enable_price_discovery=enable_price_discovery,
                    )
                    pg_text = (pg.get("text") or "").strip()
                    if len(pg_text) < 120:
                        break
                    got += 1
                    text_main = (
                        (text_main or "").rstrip()
                        + ("\n\n[分页 %s] %s\n" % (pi, (pg.get("final_url") or next_url)))
                        + truncate_text(pg_text, max_chars=per_chars)
                        )
                    if pg.get("warning"):
                        warning2 = (warning2 + "；" if warning2 else "") + ("分页%s:%s" % (pi, pg.get("warning")))
                    # 下一页继续：优先 query param 自增
                    next_url = _increment_page_param(pg.get("final_url") or next_url) or _increment_page_param(next_url)
                except Exception as e:
                    warning2 = (warning2 + "；" if warning2 else "") + f"分页{pi}抓取失败:{type(e).__name__}"
                    break
            if got > 1:
                warning2 = (warning2 + "；" if warning2 else "") + f"已自动抓取分页共{got}页"

        result = {
            "url": url,
            "final_url": final_url,
            "content_type": ctype or "text/html",
            "title": ext.get("title", ""),
            "text": truncate_text(text_main, max_chars=max_chars),
            "warning": ((warning2 + "；" + str(ext.get("warning") or "")).strip("；") if str(ext.get("warning") or "").strip() else warning2),
            "provider": ext.get("provider") or "native",
            "content_source": ext.get("content_source") or ext.get("provider") or "native",
        }
        if include_html:
            result["_raw_html"] = html
            result["_raw_html_final_url"] = final_url
            result["_raw_html_content_type"] = ctype or "text/html"
        return result

    # plain text fallback
    txt = " ".join(html.split())
    if len(txt) > max_chars:
        txt = txt[:max_chars].rstrip() + "…（内容过长已截断）"
    result = {
        "url": url,
        "final_url": final_url,
        "content_type": ctype or "text/plain",
        "title": "",
        "text": txt,
        "warning": warning,
    }
    return result
