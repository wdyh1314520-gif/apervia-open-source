# URL normalization, approximate location, caching, page fetching, and web intent helpers.

# ====== Auto Web Enrichment (fast & low false-trigger) ======
_WEB_CACHE: dict[str, tuple[float, str]] = {}  # key -> (ts, system_block_content)
_WEB_CACHE_TTL = int(app_getenv("AUTO_WEB_CACHE_TTL", "300") or 300)  # seconds


def _normalize_url_for_fetch(u: str) -> str:
    """Ensure URL is fetchable: percent-encode non-ascii path/query safely."""
    try:
        u = (u or "").strip()
        if not u:
            return u
        p = urlparse(u)
        # If it's not an absolute URL, return as-is
        if not p.scheme or not p.netloc:
            return u
        path = p.path or ""
        query = p.query or ""
        # Quote path and query but keep separators
        path_q = quote(path, safe="/:@%+-._~")
        query_q = quote(query, safe="=&?/:@%+-._~")
        rebuilt = urlunparse((p.scheme, p.netloc, path_q, p.params, query_q, p.fragment))
        return rebuilt
    except Exception:
        return (u or "").strip()


def _should_fallback_from_url(fetched_text: str, fetched_error: str | None) -> bool:
    """Decide if we should do a site:domain fallback search when user pasted a URL."""
    err = (fetched_error or "").lower()
    txt = (fetched_text or "").strip()
    if not txt or len(txt) < 200:
        # very short page usually means blocked/empty/error page
        return True
    # common hard failures
    if any(k in err for k in ["404", "not found", "timeout", "timed out", "connection", "refused", "ssl", "blocked", "forbidden", "403", "500"]):
        return True
    # also detect 404 in extracted text
    low = txt.lower()
    if ("404" in low and "not found" in low) or ("page not found" in low):
        return True
    return False


def _fallback_site_queries(user_text: str, url0: str) -> list[str]:
    """Build fallback queries like: site:example.com 价格/套餐 ..."""
    try:
        dom = (urlparse(url0).netloc or "").strip()
        if dom.startswith("www."):
            dom2 = dom[4:]
        else:
            dom2 = dom

        # ✅ Don't do "site:github.com 价格/套餐" fallbacks.
        # GitHub is special-cased elsewhere (repo API/README), and this fallback tends to pull unrelated repos.
        if dom2.lower() in ("github.com", "api.github.com", "raw.githubusercontent.com"):
            return []
        # extract a few keywords from user text (strip URL itself)
        t = re.sub(r"https?://\S+", " ", user_text or "")
        t = re.sub(r"\s+", " ", t).strip()
        # keep it short to improve search precision
        base_terms = []
        for k in ["价格", "套餐", "定价", "收费", "pricing", "price", "plan", "plans", "subscription", "billing", "收费标准", "会员", "vip"]:
            if k.lower() in (t.lower()):
                base_terms.append(k)
        if not base_terms:
            # default intent when user says 看看价格/多少钱
            base_terms = ["价格", "套餐"]
        # build 1-2 queries
        q1 = f"site:{dom2} {' '.join(base_terms)}"
        q2 = f"site:{dom2} {t}" if t else q1
        # de-dupe
        out=[]
        for q in [q1, q2]:
            qn = _normalize_search_query(q)
            if qn and qn not in out:
                out.append(qn)
        return out[:2]
    except Exception:
        return []


def _coarse_geo_key(user_geo: dict | None) -> str:
    try:
        if not isinstance(user_geo, dict):
            return ""
        lat = user_geo.get("lat"); lon = user_geo.get("lon")
        if lat is None or lon is None:
            return ""
        # 约 1km 精度（两位小数约 1.1km）
        return f"{round(float(lat), 2)},{round(float(lon), 2)}"
    except Exception:
        return ""



def _location_header_text(value, limit: int = 120) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    try:
        raw = urllib.parse.unquote(raw)
    except Exception:
        pass
    raw = re.sub(r'[\r\n\t]+', ' ', raw).strip()
    return raw[:max(1, int(limit or 120))]


def _location_float(value):
    try:
        num = float(str(value or '').strip())
    except Exception:
        return None
    if not math.isfinite(num):
        return None
    return num


def _location_public_ip_hint(value: str = '') -> dict:
    raw = str(value or '').split(',', 1)[0].strip()
    if not raw:
        return {}
    try:
        ip_obj = ipaddress.ip_address(raw)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast:
            return {}
        return {'ip_version': ip_obj.version}
    except Exception:
        return {}


def _location_public_ip_for_lookup(value: str = '') -> str:
    raw = str(value or '').split(',', 1)[0].strip()
    if not raw:
        return ''
    try:
        ip_obj = ipaddress.ip_address(raw)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast:
            return ''
        return str(ip_obj)
    except Exception:
        return ''


def _request_public_ip_for_location_lookup(headers=None) -> tuple[str, dict]:
    try:
        headers = headers or request.headers
    except Exception:
        headers = None
    if headers is None:
        return '', {}
    for name in ('CF-Connecting-IP', 'True-Client-IP', 'X-Real-IP', 'X-Forwarded-For'):
        try:
            raw = str(headers.get(name) or '').strip()
        except Exception:
            raw = ''
        ip = _location_public_ip_for_lookup(raw)
        if ip:
            return ip, _location_public_ip_hint(ip)
    return '', {}


_LOCATION_IP_LOOKUP_CACHE: dict[str, tuple[float, dict]] = {}


def _location_ip_lookup_enabled() -> bool:
    raw = str(app_getenv('LOCATION_IP_LOOKUP_ENABLE', '1') or '1').strip().lower()
    return raw not in {'0', 'false', 'no', 'off', 'disabled'}


def _location_ip_lookup_timeout_s() -> float:
    try:
        return max(0.6, min(float(str(app_getenv('LOCATION_IP_LOOKUP_TIMEOUT', '2.2') or '2.2')), 8.0))
    except Exception:
        return 2.2


def _location_ip_lookup_cache_ttl_s() -> float:
    try:
        return max(60.0, min(float(str(app_getenv('LOCATION_IP_LOOKUP_CACHE_TTL', '3600') or '3600')), 24 * 3600.0))
    except Exception:
        return 3600.0


def _location_ip_lookup_urls(ip: str = '') -> list[str]:
    ip = str(ip or '').strip()
    if not ip:
        return []
    custom = str(app_getenv('LOCATION_IP_LOOKUP_URL', '') or '').strip()
    if custom:
        return [custom.replace('{ip}', urllib.parse.quote(ip, safe=''))]
    safe_ip = urllib.parse.quote(ip, safe='')
    return [
        f'https://ipwho.is/{safe_ip}',
        f'https://ipapi.co/{safe_ip}/json/',
    ]


def _parse_ip_lookup_payload(payload) -> dict:
    if not isinstance(payload, dict):
        return {}
    try:
        if payload.get('success') is False:
            return {}
        if str(payload.get('status') or '').lower() == 'fail':
            return {}
        if payload.get('error') and not (payload.get('city') or payload.get('region') or payload.get('country') or payload.get('country_code')):
            return {}
    except Exception:
        pass

    city = _location_header_text(payload.get('city') or '', 120)
    region = _location_header_text(payload.get('region') or payload.get('regionName') or '', 120)
    region_code = _location_header_text(payload.get('region_code') or payload.get('regionCode') or '', 40)
    country_code = _location_header_text(payload.get('country_code') or payload.get('countryCode') or payload.get('country') or '', 40)
    country_name_raw = payload.get('country_name') or payload.get('countryName') or ''
    if not country_name_raw and payload.get('country_code') and payload.get('country'):
        country_name_raw = payload.get('country')
    country_name = _location_header_text(country_name_raw, 120)
    postal_code = _location_header_text(payload.get('postal') or payload.get('zip') or payload.get('postal_code') or '', 40)
    timezone_raw = payload.get('timezone')
    if isinstance(timezone_raw, dict):
        timezone_raw = timezone_raw.get('id') or timezone_raw.get('name') or ''
    timezone = _location_header_text(timezone_raw or payload.get('time_zone') or '', 120)
    lat = _location_float(payload.get('latitude') if payload.get('latitude') is not None else payload.get('lat'))
    lon = _location_float(payload.get('longitude') if payload.get('longitude') is not None else payload.get('lon'))
    if lat is not None and not (-90.0 <= lat <= 90.0):
        lat = None
    if lon is not None and not (-180.0 <= lon <= 180.0):
        lon = None

    has_any = bool(city or region or region_code or country_code or country_name or timezone or postal_code or (lat is not None and lon is not None))
    if not has_any:
        return {}
    granularity = 'city' if city else ('region' if (region or region_code) else ('country' if (country_code or country_name) else ('timezone' if timezone else 'coordinate')))
    name_bits = [x for x in (city, region, country_name or country_code) if x]
    out = {
        'available': True,
        'source': 'ip_lookup',
        'accuracy': 'coarse',
        'granularity': granularity,
        'name': '，'.join(name_bits),
        'scope': 'network_exit_location',
    }
    if city:
        out['city'] = city
    if region:
        out['region'] = region
    if region_code:
        out['region_code'] = region_code
    if country_code:
        out['country'] = country_code
    if country_name:
        out['country_name'] = country_name
    if timezone:
        out['timezone'] = timezone
    if postal_code:
        out['postal_code'] = postal_code
    if lat is not None and lon is not None:
        out['lat'] = lat
        out['lon'] = lon
    return out


def _lookup_approx_location_from_public_ip(ip: str = '') -> dict:
    ip = str(ip or '').strip()
    if not ip or not _location_ip_lookup_enabled():
        return {}
    now = time.time()
    ttl = _location_ip_lookup_cache_ttl_s()
    cached = _LOCATION_IP_LOOKUP_CACHE.get(ip)
    if cached:
        ts, value = cached
        if now - float(ts or 0.0) <= ttl:
            return dict(value or {})
        try:
            _LOCATION_IP_LOOKUP_CACHE.pop(ip, None)
        except Exception:
            pass
    timeout_s = _location_ip_lookup_timeout_s()
    for url in _location_ip_lookup_urls(ip):
        try:
            client = globals().get('HTTPX_WEB')
            if client is not None and hasattr(client, 'get'):
                resp = client.get(url, timeout=timeout_s)
                data = resp.json() if getattr(resp, 'status_code', 0) and int(resp.status_code) < 500 else {}
            else:
                resp = requests.get(url, timeout=timeout_s)
                data = resp.json() if int(getattr(resp, 'status_code', 0) or 0) < 500 else {}
        except Exception:
            data = {}
        parsed = _parse_ip_lookup_payload(data)
        if parsed:
            parsed['source'] = 'ip_lookup'
            try:
                _LOCATION_IP_LOOKUP_CACHE[ip] = (now, dict(parsed))
                if len(_LOCATION_IP_LOOKUP_CACHE) > 256:
                    old = sorted(_LOCATION_IP_LOOKUP_CACHE.items(), key=lambda kv: kv[1][0])[:64]
                    for k, _v in old:
                        _LOCATION_IP_LOOKUP_CACHE.pop(k, None)
            except Exception:
                pass
            return parsed
    return {}


def _location_granularity_rank(value: str = '') -> int:
    order = {'': 0, 'timezone': 1, 'country': 2, 'coordinate': 2, 'region': 3, 'city': 4}
    return order.get(str(value or '').strip().lower(), 0)


def _merge_approx_location_records(header_approx: dict | None = None, lookup_approx: dict | None = None, ip_hint: dict | None = None) -> dict:
    header = dict(header_approx or {}) if isinstance(header_approx, dict) else {}
    lookup = dict(lookup_approx or {}) if isinstance(lookup_approx, dict) else {}
    if not header and not lookup:
        return {}
    out = dict(header or lookup)
    if lookup:
        for key in ('city', 'region', 'region_code', 'country', 'country_name', 'timezone', 'postal_code', 'lat', 'lon', 'scope'):
            if out.get(key) in (None, '') and lookup.get(key) not in (None, ''):
                out[key] = lookup.get(key)
        if _location_granularity_rank(lookup.get('granularity')) > _location_granularity_rank(out.get('granularity')):
            out['granularity'] = lookup.get('granularity')
        name_bits = [str(out.get(k) or '').strip() for k in ('city', 'region')]
        country_label = str(out.get('country_name') or out.get('country') or '').strip()
        if country_label:
            name_bits.append(country_label)
        name = '，'.join([x for x in name_bits if x])
        if name:
            out['name'] = name
        old_source = str(header.get('source') or '').strip()
        lookup_source = str(lookup.get('source') or 'ip_lookup').strip()
        if old_source and old_source != lookup_source:
            out['source'] = old_source + '+' + lookup_source
        else:
            out['source'] = lookup_source or old_source or 'ip_lookup'
    if ip_hint:
        out.update({k: v for k, v in dict(ip_hint or {}).items() if v not in (None, '')})
    out['available'] = True
    out['accuracy'] = str(out.get('accuracy') or 'coarse').strip() or 'coarse'
    out.setdefault('scope', 'network_exit_location')
    return out


def _request_approx_location_from_headers() -> dict:
    """Build coarse network-location evidence from request headers and transient IP lookup.

    This only prepares evidence for the model.  It does not decide whether the
    location is sufficient, and it never exposes or persists the raw client IP.
    """
    try:
        headers = request.headers
    except Exception:
        return {}

    def h(*names):
        for name in names:
            try:
                value = _location_header_text(headers.get(name) or '')
            except Exception:
                value = ''
            if value:
                return value
        return ''

    city = h('CF-IPCity', 'Cf-Ipcity', 'X-Vercel-IP-City', 'X-Appengine-City', 'X-Geo-City')
    region = h('CF-Region', 'Cf-Region', 'X-Vercel-IP-Country-Region', 'X-Appengine-Region', 'X-Geo-Region')
    region_code = h('CF-Region-Code', 'Cf-Region-Code', 'X-Vercel-IP-Country-Region-Code')
    country = h('CF-IPCountry', 'Cf-Ipcountry', 'X-Vercel-IP-Country', 'X-Appengine-Country', 'X-Geo-Country')
    timezone = h('CF-Timezone', 'Cf-Timezone', 'X-Vercel-IP-Timezone', 'X-Appengine-Timezone', 'X-Geo-Timezone')
    postal_code = h('CF-Postal-Code', 'Cf-Postal-Code', 'X-Vercel-IP-Postal-Code')
    lat = _location_float(h('CF-IPLatitude', 'Cf-Iplatitude', 'X-Vercel-IP-Latitude', 'X-Appengine-Citylatlong', 'X-Geo-Latitude'))
    lon = _location_float(h('CF-IPLongitude', 'Cf-Iplongitude', 'X-Vercel-IP-Longitude', 'X-Geo-Longitude'))

    # Some platforms expose "lat,long" in a single header.
    if (lat is None or lon is None):
        pair = h('X-Appengine-Citylatlong', 'X-Geo-Latlong', 'X-Geo-Coordinates')
        if pair and ',' in pair:
            a, b = pair.split(',', 1)
            lat2 = _location_float(a)
            lon2 = _location_float(b)
            if lat2 is not None and lon2 is not None:
                lat, lon = lat2, lon2

    if lat is not None and not (-90.0 <= lat <= 90.0):
        lat = None
    if lon is not None and not (-180.0 <= lon <= 180.0):
        lon = None

    public_ip, ip_hint = _request_public_ip_for_location_lookup(headers)

    has_any = bool(city or region or region_code or country or timezone or postal_code or (lat is not None and lon is not None))
    header_approx = {}
    if has_any:
        granularity = 'city' if city else ('region' if (region or region_code) else ('country' if country else ('timezone' if timezone else 'coordinate')))
        name_bits = [x for x in (city, region, country) if x]
        header_approx = {
            'available': True,
            'source': 'request_network_headers',
            'accuracy': 'coarse',
            'granularity': granularity,
            'name': '，'.join(name_bits),
            'scope': 'network_exit_location',
        }
        if city:
            header_approx['city'] = city
        if region:
            header_approx['region'] = region
        if region_code:
            header_approx['region_code'] = region_code
        if country:
            header_approx['country'] = country
        if timezone:
            header_approx['timezone'] = timezone
        if postal_code:
            header_approx['postal_code'] = postal_code
        if lat is not None and lon is not None:
            header_approx['lat'] = lat
            header_approx['lon'] = lon

    lookup_approx = {}
    if public_ip:
        # When headers only provide country/timezone or no location fields, a
        # transient IP lookup can enrich the same coarse evidence with city/region.
        if not header_approx or _location_granularity_rank(header_approx.get('granularity')) < _location_granularity_rank('city'):
            lookup_approx = _lookup_approx_location_from_public_ip(public_ip)

    return _merge_approx_location_records(header_approx, lookup_approx, ip_hint)


def _merge_request_approx_location_state(location_state: dict | None = None) -> dict:
    state = dict(location_state or {}) if isinstance(location_state, dict) else {}
    approx = state.get('approximate_location') if isinstance(state.get('approximate_location'), dict) else {}
    if approx.get('available'):
        return state
    request_approx = _request_approx_location_from_headers()
    if not request_approx:
        return state
    state['approximate_location'] = request_approx
    if str(state.get('visibility') or '').strip() in {'', 'no_location_context', 'timezone_only', 'no_precise_location'}:
        state['visibility'] = 'approximate_location_available'
    return state


def _enrich_location_payload_from_request(payload: dict | None = None) -> dict:
    data = dict(payload or {}) if isinstance(payload, dict) else {}
    state = data.get('location_state') if isinstance(data.get('location_state'), dict) else {}
    state = _merge_request_approx_location_state(state)
    if state:
        data['location_state'] = state
        user_geo = data.get('user_geo') if isinstance(data.get('user_geo'), dict) else None
        if isinstance(user_geo, dict):
            user_geo = dict(user_geo)
            user_geo['_location_state'] = dict(state)
            data['user_geo'] = user_geo
        elif data.get('user_geo') is None:
            data['user_geo'] = {'_location_state': dict(state)}
        debug_geo_meta = data.get('debug_geo_meta') if isinstance(data.get('debug_geo_meta'), dict) else {}
        debug_geo_meta = dict(debug_geo_meta or {})
        debug_geo_meta['location_state'] = dict(state)
        data['debug_geo_meta'] = debug_geo_meta
    return data

def _norm_text(s: str, max_len: int = 240) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s[:max_len]

def _cache_get(key: str) -> str | None:
    v = _WEB_CACHE.get(key)
    if not v:
        return None
    ts, content = v
    if time.time() - ts > _WEB_CACHE_TTL:
        try:
            del _WEB_CACHE[key]
        except Exception:
            pass
        return None
    return content

def _cache_set(key: str, content: str):
    if not key or not content:
        return
    # 简易裁剪，避免无限增长
    if len(_WEB_CACHE) > 64:
        # 删除最旧的 16 条
        items = sorted(_WEB_CACHE.items(), key=lambda kv: kv[1][0])
        for k, _ in items[:16]:
            _WEB_CACHE.pop(k, None)
    _WEB_CACHE[key] = (time.time(), content)


def _fetch_pages_concurrent(url_items: list[dict], max_chars: int = 7000) -> list[dict]:
    """并发抓取多个网页正文，提高吞吐量。
    url_items: [{"url":..., "title":...}, ...]
    返回与输入同顺序的 page dict 列表。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if not url_items:
        return []
    max_workers = _cfg_int("AUTO_WEB_FETCH_WORKERS", 8)
    max_workers = max(2, min(max_workers, 16))

    # URL 级缓存：避免同一 URL 反复抓
    ttl = int(app_getenv("AUTO_WEB_URL_CACHE_TTL", "1800") or 1800)
    if not hasattr(_fetch_pages_concurrent, "_url_cache"):
        _fetch_pages_concurrent._url_cache = {}  # type: ignore[attr-defined]
    url_cache: dict = getattr(_fetch_pages_concurrent, "_url_cache")  # type: ignore[attr-defined]

    def _get_one(u: str, title: str):
        key = u.strip()
        now = time.time()
        if key in url_cache:
            ts, val = url_cache[key]
            if now - ts < ttl:
                return val
            else:
                url_cache.pop(key, None)
        try:
            # 批量抓取（搜索结果页）以“快”为主：
            # - 缩短 timeout
            # - 禁用 Playwright（否则很容易被动态站拖慢）
            tmo = _cfg_float("AUTO_WEB_PAGE_TIMEOUT", 10.0)
            val = fetch_url_content(key, timeout=tmo, max_chars=max_chars, allow_playwright=False)
        except Exception as e:
            val = {"url": key, "title": title or "", "text": "", "error": f"{type(e).__name__}: {e}"}
        url_cache[key] = (now, val)
        # 简单裁剪
        if len(url_cache) > 128:
            oldest = sorted(url_cache.items(), key=lambda kv: kv[1][0])[:32]
            for k, _v in oldest:
                url_cache.pop(k, None)
        return val

    out = [None] * len(url_items)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_map = {}
        for i, it in enumerate(url_items):
            u = (it.get("url") or "").strip()
            if not u:
                out[i] = {"url": "", "title": it.get("title",""), "text": "", "error": "empty url"}
                continue
            future = ex.submit(_get_one, u, it.get("title",""))
            future_map[future] = i
        for fut in as_completed(future_map):
            i = future_map[fut]
            try:
                out[i] = fut.result()
            except Exception as e:
                it = url_items[i]
                out[i] = {"url": it.get("url",""), "title": it.get("title",""), "text": "", "error": f"{type(e).__name__}: {e}"}
    return [x for x in out if x is not None]

# ====== Async Web Fetch (true concurrency with httpx.AsyncClient) ======
# Motivation: avoid slow serial timeouts when fetching multiple pages for web enrichment.

async def _fetch_pages_async(url_items: list[dict], max_chars: int = 7000) -> list[dict]:
    if not url_items:
        return []
    max_workers = _cfg_int("AUTO_WEB_FETCH_WORKERS", 12)
    max_workers = max(2, min(max_workers, 24))
    timeout = _cfg_float("AUTO_WEB_PAGE_TIMEOUT", 6.0)

    sem = asyncio.Semaphore(max_workers)

    headers = {
        "User-Agent": app_getenv("WEB_FETCH_UA", "").strip() or "Mozilla/5.0",
        "Accept-Language": app_getenv("WEB_FETCH_ACCEPT_LANGUAGE", "").strip() or "zh-TW,zh;q=0.9,en;q=0.6",
    }

    limits = httpx.Limits(max_connections=max_workers, max_keepalive_connections=max_workers)

    async with httpx.AsyncClient(
        follow_redirects=True,
        verify=WEB_SEARCH_TLS_VERIFY,
        timeout=httpx.Timeout(timeout, connect=min(6.0, timeout), read=timeout, write=timeout, pool=timeout),
        headers=headers,
        trust_env=(app_getenv("WEB_FETCH_TRUST_ENV", "0").strip() != "0"),
        limits=limits,
    ) as client:

        async def _one(item: dict) -> dict:
            url = (item.get("url") or "").strip()
            title_hint = (item.get("title") or "").strip()
            if not url:
                return {"url": "", "title": title_hint, "text": "", "error": "empty_url"}

            strategy = _decide_host_fetch_strategy(url, task_type='web_page', allow_playwright=False)
            if strategy.get('mode') == 'cooldown_skip' or strategy.get('prefer_content_fallback'):
                return await asyncio.to_thread(fetch_url_content_smart, url, "", timeout, max_chars)

            async with sem:
                ticket = None
                try:
                    ticket = await asyncio.to_thread(_global_fetch_budget_acquire, url, 'web_page')
                    r = await client.get(url)
                    _host_fetch_record(url, status_code=int(r.status_code or 0), headers=dict(r.headers or {}), method='httpx_async', task_type='web_page')
                    ct = (r.headers.get("content-type") or "").lower()
                    if "pdf" in ct or ct.startswith("application/"):
                        return {"url": url, "title": title_hint, "text": "", "content_type": ct, "warning": "skipped_non_html"}

                    html0 = (r.text or "")
                    try:
                        ex = _extract_text_from_html(html0, max_chars=max_chars)
                        title = (ex.get("title") or title_hint)[:200]
                        txt = truncate_text(ex.get("text") or "", max_chars=max_chars)
                        return {"url": url, "title": title, "text": txt, "content_type": ct}
                    except Exception as e:
                        raw = truncate_text(html0, max_chars=max_chars)
                        return {"url": url, "title": title_hint, "text": raw, "content_type": ct, "warning": f"extract_failed:{type(e).__name__}"}
                except Exception as e:
                    _host_fetch_record(url, error=f'httpx_async:{type(e).__name__}', method='httpx_async', task_type='web_page')
                    return {"url": url, "title": title_hint, "text": "", "error": f"{type(e).__name__}: {e}"}
                finally:
                    if ticket is not None:
                        await asyncio.to_thread(_global_fetch_budget_release, ticket)

        tasks = [asyncio.create_task(_one(it)) for it in url_items]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results


def _fetch_pages_concurrent_async(url_items: list[dict], max_chars: int = 7000) -> list[dict]:
    """Sync wrapper for _fetch_pages_async (Flask is sync)."""
    try:
        return asyncio.run(_fetch_pages_async(url_items, max_chars=max_chars))
    except RuntimeError:
        # If already in an event loop (rare in Flask), run in a new loop.
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_fetch_pages_async(url_items, max_chars=max_chars))
        finally:
            try:
                loop.close()
            except Exception:
                pass
            asyncio.set_event_loop(None)



def _looks_time_sensitive(user_text: str) -> bool:
    t = (user_text or "").lower()
    # 明显需要“最新/实时”的场景：天气、新闻、价格、汇率、比分、航班、开奖、地震等
    kw = [
        "天气","气温","温度","降雨","下雨","台风","预报","雷阵雨","湿度","风速",
        "最新","今天","现在","刚刚","目前","实时","近期","这周","本周","明天","后天",
        "新闻","热搜","行情","价格","多少钱","报价","汇率","股价","币价","比分","赛程","航班","列车","地震","停电","台风路径",
        "weather","forecast","rain","temp","temperature","news","price","exchange rate","stock","score","flight"
    ]
    return any(k in t for k in kw)


def _looks_explicit_web_request(user_text: str) -> bool:
    t = (user_text or "").lower()
    kw = ["联网","上网","搜一下","搜索","查一下","帮我查","查查","来源","引用","link","links","source","browse","search"]
    return any(k in t for k in kw)


def _want_deep_web(user_text: str) -> bool:
    """用户明确要更严谨/更多来源/对比时，才启用深抓（多页网页正文）。"""
    t = (user_text or "").lower()
    kw = [
        "详细", "更详细", "展开", "多抓", "多搜", "多来源", "多个来源", "对比", "比较",
        "引用", "出处", "原文", "链接", "证据", "权威", "官方", "数据来源",
        "cite", "source", "sources", "evidence", "compare", "reference"
    ]
    return any(k in t for k in kw)

def _snippet_by_query(text: str, query: str, limit: int = 1800) -> str:
    """从网页正文中提取更相关的片段，降低 token 成本。"""
    if not text:
        return ""
    t = text.replace("\r\n","\n").replace("\r","\n")
    key = _extract_keywords_simple(query or "", max_n=10)
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if not lines:
        return truncate_text(t, max_chars=limit)
    # 命中行 + 邻近上下文（更偏向“数字/价格/单位”行）
    hit_idx = []
    if key:
        for i, ln in enumerate(lines):
            if any(k in ln for k in key):
                hit_idx.append(i)
    picked=[]
    used=set()
    if hit_idx:
        for i in hit_idx[:60]:
            for j in range(max(0,i-2), min(len(lines), i+3)):
                ln=lines[j]
                if ln not in used:
                    picked.append(ln); used.add(ln)
            if sum(len(x) for x in picked) > limit*2:
                break
    else:
        # 没命中就取开头 + 数字/币种/单位行（更适合价格/参数/套餐）
        num_lines=[ln for ln in lines if re.search(r"(?:\d|￥|¥|USD|TWD|NT\$|GB|TB|MB|%|/month|/year)", ln, re.I)]
        picked = lines[:26] + num_lines[:60]
    out = "\n".join(picked).strip()
    return truncate_text(out, max_chars=limit)
