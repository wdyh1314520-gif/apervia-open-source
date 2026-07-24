# image-result normalization, SearxNG image search, Whoogle parsing, and Serper image search.

def _normalize_image_url_value(u: str) -> str:
    u = str(u or '').strip()
    if not u:
        return ''
    if u.startswith('//'):
        return 'https:' + u
    return u


def _norm_image_result_url_for_dedup(u: str) -> str:
    if not u:
        return ''
    u = _normalize_image_url_value(u)
    try:
        pu = urllib.parse.urlsplit(u)
        scheme = (pu.scheme or 'http').lower()
        netloc = (pu.netloc or '').lower()
        path = pu.path or '/'
        q = urllib.parse.parse_qsl(pu.query, keep_blank_values=False)
        drop_keys = {
            'w', 'h', 'width', 'height', 'size', 'quality', 'q', 'x-oss-process', 'imageview2',
            'crop', 'format', 'fmt', 'token', 'sign', 'signature', 'expires', 'timestamp',
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'spm', 'from', 'ref', 'source'
        }
        q2 = [(k, v) for (k, v) in q if (k or '').lower() not in drop_keys]
        query = urllib.parse.urlencode(q2, doseq=True)
        return urllib.parse.urlunsplit((scheme, netloc, path.rstrip('/') or '/', query, ''))
    except Exception:
        return u


def web_search_searxng_images_multi(queries: list[str], k: int = 12, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
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

    per_query_k = max(6, min(int(k or 12), 24))
    merged = []
    seen_u = set()
    for q in qs:
        rows = web_search_searxng_images(q, k=per_query_k, timeout=timeout, user_text=user_text or q)
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            raw_url = _pick_best_image_candidate_url(row)
            key = _norm_image_result_url_for_dedup(raw_url)
            if not key or key in seen_u:
                continue
            seen_u.add(key)
            row2 = dict(row)
            row2.setdefault('_query', q)
            merged.append(row2)

    limit = max(1, min(int(k or 12), 48))
    subject = qs[0]
    merged = _rerank_image_results(merged, user_text or subject, subject=subject, limit=limit)
    return merged[:limit]


def web_search_searxng_images(query: str, k: int = 3, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
    """使用 SearxNG 图片分类返回图片结果。返回 [{url,title,thumbnail,source}]，并优先官方/权威来源。"""
    q = (query or "").strip()
    if not q:
        return []
    searxng_url = app_getenv("SEARXNG_URL", "").strip().rstrip("/")
    searxng_api_path = app_getenv("SEARXNG_API_PATH", "/search").strip() or "/search"
    if not searxng_url:
        return []
    endpoint = searxng_url + searxng_api_path
    params = {
        "q": q,
        "format": "json",
        "language": app_getenv("SEARXNG_LANGUAGE", "zh").strip() or "zh",
        "safesearch": int(app_getenv("SEARXNG_SAFESEARCH", "0") or 0),
        "categories": "images",
    }
    engines = app_getenv("SEARXNG_IMAGE_ENGINES", "").strip()
    if engines:
        params["engines"] = engines
    t = httpx.Timeout(timeout, connect=min(4.0, float(timeout)))
    try:
        r = HTTPX_SEARCH.get(endpoint, params=params, timeout=t)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    raw_limit = max(min(int(k or 3) * 8, 60), max(int(k or 3), 12))
    outs = []
    seen = set()
    for it in (data.get("results") or [])[:raw_limit]:
        cand = (
            it.get("img_src")
            or it.get("thumbnail_src")
            or it.get("thumbnail")
            or it.get("image")
            or it.get("url")
            or it.get("src")
            or ""
        )
        cand = _normalize_image_url_value(cand)
        thumb = _normalize_image_url_value(it.get("thumbnail_src") or it.get("thumbnail") or cand)
        source_url = _normalize_image_url_value(it.get("url") or it.get("link") or "")
        cand_key = _norm_image_result_url_for_dedup(cand)
        if not cand or not cand_key or cand_key in seen:
            continue
        if not re.match(r"^https?://", cand, flags=re.I):
            continue
        seen.add(cand_key)
        outs.append({
            "url": cand,
            "title": (it.get("title") or "")[:200],
            "thumbnail": thumb[:500],
            "source": source_url[:500],
            "provider": "searxng",
            "engine": str(it.get("engine") or ",".join(it.get("engines") or []) or "")[:120],
        })
    outs = _rerank_image_results(outs, user_text or q, subject=q, limit=max(1, int(k or 3)))
    return outs[:max(1, int(k or 3))]


def _effective_web_result_count(rows: list[dict]) -> int:
    count = 0
    seen = set()
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        url = str(row.get('url') or '').strip()
        if not url:
            continue
        nu = _norm_url_for_dedup(url)
        if not nu or nu in seen:
            continue
        seen.add(nu)
        title = str(row.get('title') or '').strip()
        snippet = str(row.get('snippet') or '').strip()
        if len(title) >= 4 or len(snippet) >= 20:
            count += 1
    return count


def _effective_image_result_count(rows: list[dict]) -> int:
    count = 0
    seen = set()
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        raw_url = _pick_best_image_candidate_url(row)
        key = _norm_image_result_url_for_dedup(raw_url)
        if not key or key in seen:
            continue
        seen.add(key)
        thumb = str(row.get('thumbnail') or '').strip()
        source = str(row.get('source') or '').strip()
        if raw_url and (thumb or source):
            count += 1
    return count


def _merge_unique_web_rows(base_rows: list[dict], extra_rows: list[dict]) -> list[dict]:
    merged = []
    seen = set()
    for bucket in (base_rows or [], extra_rows or []):
        for row in bucket or []:
            if not isinstance(row, dict):
                continue
            u = str(row.get('url') or '').strip()
            if not u:
                continue
            nu = _norm_url_for_dedup(u)
            if not nu or nu in seen:
                continue
            seen.add(nu)
            merged.append(dict(row))
    return merged


def _merge_unique_image_rows(base_rows: list[dict], extra_rows: list[dict]) -> list[dict]:
    merged = []
    seen = set()
    for bucket in (base_rows or [], extra_rows or []):
        for row in bucket or []:
            if not isinstance(row, dict):
                continue
            raw_url = _pick_best_image_candidate_url(row)
            key = _norm_image_result_url_for_dedup(raw_url)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(dict(row))
    return merged


def _whoogle_extract_result_url(href: str, base_url: str) -> str:
    raw = str(href or '').strip()
    if not raw:
        return ''
    try:
        joined = urllib.parse.urljoin(base_url.rstrip('/') + '/', raw)
        pu = urllib.parse.urlsplit(joined)
        q = urllib.parse.parse_qs(pu.query or '')
        for key in ('q', 'url', 'uddg'):
            cand = str((q.get(key) or [''])[0] or '').strip()
            if re.match(r'^https?://', cand, flags=re.I):
                return cand
        if re.match(r'^https?://', joined, flags=re.I):
            base_host = (urllib.parse.urlsplit(base_url).hostname or '').lower()
            joined_host = (pu.hostname or '').lower()
            if joined_host and joined_host != base_host:
                return joined
            if pu.path in ('/url', '/redirect', '/r'):
                return ''
        return ''
    except Exception:
        return ''


class _WhoogleResultHTMLParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.results = []
        self.current = None
        self.depth = 0
        self.capture_title = False
        self.capture_snippet = False
        self.title_buf = []
        self.snippet_buf = []
        self._snippet_started = False

    def handle_starttag(self, tag, attrs):
        attrs_d = {k: v for k, v in attrs}
        classes = set(str(attrs_d.get('class') or '').split())
        if self.current is None and tag in ('div', 'article', 'section', 'li') and 'result' in classes:
            self.current = {'title': '', 'url': '', 'snippet': ''}
            self.depth = 1
            self.capture_title = False
            self.capture_snippet = False
            self.title_buf = []
            self.snippet_buf = []
            self._snippet_started = False
            return
        if self.current is None:
            return
        self.depth += 1
        if tag == 'a':
            href = _whoogle_extract_result_url(attrs_d.get('href') or '', self.base_url)
            if href:
                if not self.current.get('url'):
                    self.current['url'] = href
                self.capture_title = True
                self.title_buf = []
        wants_snippet = (
            any(c in classes for c in ('result__content', 'result__snippet', 'result__body'))
            or (tag == 'p' and not self._snippet_started)
        )
        if wants_snippet:
            self.capture_snippet = True
            self.snippet_buf = []
            self._snippet_started = True

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if tag == 'a' and self.capture_title:
            title = ' '.join(' '.join(self.title_buf).split()).strip()
            if title and (not self.current.get('title') or len(title) > len(self.current.get('title') or '')):
                self.current['title'] = title[:200]
            self.capture_title = False
            self.title_buf = []
        if tag in ('p', 'div', 'section', 'span') and self.capture_snippet:
            snippet = ' '.join(' '.join(self.snippet_buf).split()).strip()
            if snippet and (not self.current.get('snippet') or len(snippet) > len(self.current.get('snippet') or '')):
                self.current['snippet'] = snippet[:400]
            self.capture_snippet = False
            self.snippet_buf = []
        self.depth -= 1
        if self.depth <= 0:
            title = str(self.current.get('title') or '').strip()
            url = str(self.current.get('url') or '').strip()
            snippet = str(self.current.get('snippet') or '').strip()
            if url and (title or snippet):
                self.results.append({'title': title[:200], 'url': url[:500], 'snippet': snippet[:400]})
            self.current = None
            self.depth = 0
            self.capture_title = False
            self.capture_snippet = False
            self.title_buf = []
            self.snippet_buf = []
            self._snippet_started = False

    def handle_data(self, data):
        if self.current is None:
            return
        txt = str(data or '')
        if not txt.strip():
            return
        if self.capture_title:
            self.title_buf.append(txt)
        if self.capture_snippet:
            self.snippet_buf.append(txt)


def web_search_whoogle(query: str, k: int = 5, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
    q = (query or '').strip()
    if not q:
        return []
    base_url = app_getenv('WHOOGLE_URL', '').strip().rstrip('/')
    if not base_url:
        raise RuntimeError('未配置 WHOOGLE_URL（默认留空；如需启用可填写例如 http://127.0.0.1:5000）')

    tried = []
    last_exc = None
    headers = {'Accept': 'text/html,application/xhtml+xml'}
    params = {'q': q}
    for path in ('/search', '/'):
        endpoint = base_url + path
        tried.append(endpoint)
        try:
            t = httpx.Timeout(timeout, connect=min(4.0, float(timeout)))
            r = HTTPX_SEARCH.get(endpoint, params=params, headers=headers, timeout=t)
            r.raise_for_status()
            html_text = str(r.text or '')
            parser = _WhoogleResultHTMLParser(base_url)
            parser.feed(html_text)
            rows = parser.results
            if not rows and html_text:
                fallback_rows = []
                for href, title in re.findall(r"<a[^>]+href=[\"\']([^\"\']+)[\"\'][^>]*>(.*?)</a>", html_text, flags=re.I | re.S):
                    url = _whoogle_extract_result_url(href, base_url)
                    clean_title = _strip_html_tags(title or '').strip()
                    if url and clean_title:
                        fallback_rows.append({'title': clean_title[:200], 'url': url[:500], 'snippet': ''})
                rows = fallback_rows
            if not rows:
                continue
            rows = _filter_search_results(rows, user_text or q)
            rows = _rerank_results(rows, user_text or q)
            out = []
            seen = set()
            for row in rows:
                nu = _norm_url_for_dedup(str((row or {}).get('url') or '').strip())
                if not nu or nu in seen:
                    continue
                seen.add(nu)
                item = dict(row)
                item.setdefault('engines', ['whoogle'])
                item.setdefault('provider', 'whoogle')
                item.setdefault('source', 'whoogle')
                out.append(item)
                if len(out) >= max(1, min(int(k), 10)):
                    break
            if out:
                return out
        except Exception as e:
            last_exc = e
            continue
    if last_exc is not None:
        raise RuntimeError(_format_search_upstream_error('Whoogle', base_url, last_exc)) from last_exc
    raise RuntimeError(f'Whoogle 无结果: {", ".join(tried)}')


def web_search_serper_images(query: str, k: int = 8, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
    q = (query or '').strip()
    if not q:
        return []
    api_key = app_getenv('SERPER_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('未配置 SERPER_API_KEY')
    endpoint = app_getenv('SERPER_IMAGE_API_URL', 'https://google.serper.dev/images').strip() or 'https://google.serper.dev/images'
    payload = {'q': q, 'num': max(1, min(int(k or 8), 20))}
    headers = {
        'X-API-KEY': api_key,
        'Content-Type': 'application/json',
    }
    t = httpx.Timeout(timeout, connect=min(4.0, float(timeout)))
    r = HTTPX_SEARCH.post(endpoint, headers=headers, json=payload, timeout=t)
    r.raise_for_status()
    data = r.json()
    raw_limit = max(min(int(k or 8) * 4, 40), int(k or 8))
    out = []
    seen = set()
    for it in (data.get('images') or [])[:raw_limit]:
        image_url = _normalize_image_url_value(it.get('imageUrl') or it.get('image_url') or it.get('link') or '')
        thumb = _normalize_image_url_value(it.get('thumbnailUrl') or it.get('thumbnail_url') or image_url)
        source = _normalize_image_url_value(it.get('sourceUrl') or it.get('source_url') or it.get('link') or '')
        key = _norm_image_result_url_for_dedup(image_url or thumb)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            'url': (image_url or thumb)[:500],
            'title': str(it.get('title') or '')[:200],
            'thumbnail': thumb[:500],
            'source': source[:500],
            'provider': 'serper',
        })
    out = _rerank_image_results(out, user_text or q, subject=q, limit=max(1, int(k or 8)))
    return out[:max(1, int(k or 8))]


def web_search_serper_images_multi(queries: list[str], k: int = 12, timeout: float = 12.0, *, user_text: str | None = None) -> list[dict]:
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
    per_query_k = max(6, min(int(k or 12), 24))
    merged = []
    for q in qs:
        rows = web_search_serper_images(q, k=per_query_k, timeout=timeout, user_text=user_text or q)
        merged = _merge_unique_image_rows(merged, rows)
    limit = max(1, min(int(k or 12), 48))
    subject = qs[0]
    merged = _rerank_image_results(merged, user_text or subject, subject=subject, limit=limit)
    return merged[:limit]
