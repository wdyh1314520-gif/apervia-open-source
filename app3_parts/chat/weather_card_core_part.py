# Split from app3_parts/chat/chat_weather_routes_part.py.
# Purpose: weather intent compatibility, geocoding, caching, and card construction.
# Loaded by chat_weather_routes_part.py via _exec_split_file(...), sharing app3.py globals.

# ====== Weather card fast path ======
WEATHER_WMO_CODES = {
    0: ("晴", "☀️"), 1: ("晴间多云", "🌤️"), 2: ("多云", "⛅"), 3: ("阴", "☁️"),
    45: ("雾", "🌫️"), 48: ("雾凇", "🌫️"),
    51: ("毛毛雨", "🌦️"), 53: ("小雨", "🌦️"), 55: ("中雨", "🌧️"),
    56: ("冻毛毛雨", "🌧️"), 57: ("冻雨", "🌧️"),
    61: ("小雨", "🌧️"), 63: ("中雨", "🌧️"), 65: ("大雨", "🌧️"),
    66: ("冻雨", "🌧️"), 67: ("强冻雨", "🌧️"),
    71: ("小雪", "🌨️"), 73: ("中雪", "🌨️"), 75: ("大雪", "❄️"),
    77: ("雪粒", "🌨️"),
    80: ("阵雨", "🌦️"), 81: ("阵雨", "🌧️"), 82: ("强阵雨", "⛈️"),
    85: ("阵雪", "🌨️"), 86: ("强阵雪", "❄️"),
    95: ("雷阵雨", "⛈️"), 96: ("雷雨夹冰雹", "⛈️"), 99: ("强雷雨夹冰雹", "⛈️"),
}



# 天气 / 定位是否调用工具由 orchestrator/tool planner 统一判断。
# 这里保留同名函数只是为了兼容旧调用点；它们不再参与天气或定位意图触发。
def _classify_weather_route(text: str) -> str:
    return "none"


def _weather_intent_kind(text: str) -> str:
    return "none"


def _is_weather_query_text(text: str) -> bool:
    return False


def _is_weather_followup_text(text: str) -> bool:
    return False


def _weather_query_needs_context(text: str) -> bool:
    return False


def _looks_like_weather_place_reply(text: str) -> bool:
    return False


def _detect_pending_weather_turn(messages: list, current_user_text: str = "") -> dict | None:
    return None


def _weather_desc(code: int | None) -> tuple[str, str]:
    try:
        return WEATHER_WMO_CODES.get(int(code), ("未知", "🌈"))
    except Exception:
        return ("未知", "🌈")


def _decide_weather_present_mode_once(model: str, messages: list, user_text: str, client_override=None) -> dict:
    """Return weather presentation mode without a secondary model call.

    Weather presentation is a rendering decision.  In the Responses native lane it
    must not open a hidden /chat/completions request; the main Responses agent has
    already decided to use the weather tool, and the UI should keep the structured
    weather card attached to the same assistant turn.
    """
    s = str(user_text or '').strip()
    return {
        "mode": "card",
        "reason": "structured_weather_payload",
        "source": "same_lane_no_secondary_model",
        "user_text_present": bool(s),
    }


def _extract_weather_memory_from_messages(messages: list, current_user_text: str = "") -> dict | None:
    """Recover only the latest structured weather location already produced by the tool.

    This no longer infers weather topics from natural language. Whether the
    current turn should reuse this memory is decided by the model location
    resolver after get_weather has actually been called.
    """
    msgs = [m for m in list(messages or []) if isinstance(m, dict)]
    if not msgs:
        return None

    def _weather_obj_from_message(m: dict) -> dict | None:
        role = str(m.get("role") or "")
        if role not in ("assistant", "tool"):
            return None
        content = m.get("content")
        if isinstance(content, dict) and content.get("_kind") == "weather":
            return content
        txt = _msg_content_text(content).strip()
        if not txt:
            return None
        try:
            obj = json.loads(txt)
        except Exception:
            obj = None
        if isinstance(obj, dict) and obj.get("_kind") == "weather":
            return obj
        return None

    work = list(msgs)
    latest_text = str(current_user_text or "").strip()
    if latest_text:
        for i in range(len(work) - 1, -1, -1):
            m = work[i]
            if m.get("role") != "user":
                continue
            txt = _msg_content_text(m.get("content")).strip()
            if txt and txt == latest_text:
                work = work[:i]
                break

    for m in reversed(work):
        obj = _weather_obj_from_message(m)
        if not (isinstance(obj, dict) and obj.get("ok")):
            continue
        loc = obj.get("location") or {}
        lat = loc.get("lat")
        lon = loc.get("lon")
        name = str(loc.get("name") or "").strip()
        if lat is None or lon is None:
            continue
        try:
            role = str(m.get("role") or "")
            source = "recent_weather_assistant" if role == "assistant" else "recent_weather_tool"
            return {"lat": float(lat), "lon": float(lon), "name": name or "当前位置", "source": source}
        except Exception:
            continue
    return None


def _extract_structured_weather_memory_from_messages(messages: list, current_user_text: str = "") -> dict | None:
    """只返回最近连续天气话题里的结构化天气位置，不从自然语言里猜地点。"""
    memory = _extract_weather_memory_from_messages(messages or [], current_user_text=current_user_text)
    if not isinstance(memory, dict):
        return None
    source = str(memory.get("source") or "").strip()
    if source not in {"recent_weather_assistant", "recent_weather_tool"}:
        return None
    try:
        lat = float(memory.get("lat"))
        lon = float(memory.get("lon"))
    except Exception:
        return None
    return {
        "lat": lat,
        "lon": lon,
        "name": str(memory.get("name") or "当前位置").strip() or "当前位置",
        "source": source,
    }



def _weather_location_state_from_user_geo(user_geo: dict | None = None) -> dict:
    if not isinstance(user_geo, dict):
        return {}
    state = user_geo.get('_location_state') if isinstance(user_geo.get('_location_state'), dict) else {}
    if not state and isinstance(user_geo.get('location_state'), dict):
        state = user_geo.get('location_state') or {}
    return dict(state or {}) if isinstance(state, dict) else {}


def _weather_approx_location_from_user_geo(user_geo: dict | None = None) -> dict:
    state = _weather_location_state_from_user_geo(user_geo)
    approx = state.get('approximate_location') if isinstance(state.get('approximate_location'), dict) else {}
    if not isinstance(approx, dict) or not bool(approx.get('available')):
        return {}
    return dict(approx)


def _weather_approx_location_name(approx: dict | None = None) -> str:
    row = dict(approx or {}) if isinstance(approx, dict) else {}
    direct = str(row.get('name') or '').strip()
    if direct:
        return direct
    bits = []
    for key in ('city', 'region'):
        val = str(row.get(key) or '').strip()
        if val:
            bits.append(val)
    country = str(row.get('country_name') or row.get('country') or '').strip()
    if country:
        bits.append(country)
    return '，'.join(bits).strip()


def _weather_effective_user_geo(user_geo: dict | None = None) -> dict | None:
    """Use structured precise coords first, then structured coarse network coords.

    This does not infer intent. It only bridges already available location evidence
    into the weather executor, so a model-chosen get_weather call can use network
    coarse coordinates when no browser position is available.
    """
    if isinstance(user_geo, dict) and user_geo.get('lat') is not None and user_geo.get('lon') is not None:
        return user_geo
    approx = _weather_approx_location_from_user_geo(user_geo)
    if not approx:
        return user_geo
    try:
        lat = float(approx.get('lat'))
        lon = float(approx.get('lon'))
    except Exception:
        return user_geo
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return user_geo
    out = dict(user_geo or {}) if isinstance(user_geo, dict) else {}
    out['lat'] = lat
    out['lon'] = lon
    out['name'] = _weather_approx_location_name(approx) or str(approx.get('city') or approx.get('region') or approx.get('country') or '').strip() or '网络粗略位置'
    out['source'] = str(approx.get('source') or 'approximate_location').strip() or 'approximate_location'
    out['accuracy'] = str(approx.get('accuracy') or 'coarse').strip() or 'coarse'
    out['location_type'] = 'approximate'
    out['scope'] = str(approx.get('scope') or 'network_exit_location').strip() or 'network_exit_location'
    state = _weather_location_state_from_user_geo(user_geo)
    if state:
        out['_location_state'] = state
    return out


def _weather_approx_structured_place(user_geo: dict | None = None) -> str:
    approx = _weather_approx_location_from_user_geo(user_geo)
    if not approx:
        return ''
    granularity = str(approx.get('granularity') or '').strip().lower()
    if granularity not in {'city', 'region'}:
        return ''
    return _weather_approx_location_name(approx)

def _weather_location_safe_fallback_decision(user_text: str, messages: list | None = None, user_geo: dict | None = None) -> dict:
    """Safety fallback for weather location execution.

    It does not classify user intent or extract places with keyword rules. It
    only uses structured coordinates/place evidence already available to the
    request.
    """
    text = str(user_text or '').strip()
    effective_geo = _weather_effective_user_geo(user_geo)
    has_user_geo = isinstance(effective_geo, dict) and effective_geo.get('lat') is not None and effective_geo.get('lon') is not None
    structured_memory = _extract_structured_weather_memory_from_messages(messages or [], current_user_text=text)
    approx_place = _weather_approx_structured_place(user_geo)
    if has_user_geo:
        return {
            'action': 'user_geo',
            'explicit_place_text': '',
            'switched_place': False,
            'reason': 'fallback_user_geo',
            'source': 'safe_fallback',
        }
    if structured_memory:
        return {
            'action': 'recent_weather',
            'explicit_place_text': '',
            'switched_place': False,
            'reason': 'fallback_recent_structured_weather',
            'source': 'safe_fallback',
        }
    if approx_place:
        return {
            'action': 'explicit_place',
            'explicit_place_text': approx_place[:120],
            'switched_place': False,
            'reason': 'fallback_approx_structured_place',
            'source': 'safe_fallback',
        }
    return {
        'action': 'need_location',
        'explicit_place_text': '',
        'switched_place': False,
        'reason': 'fallback_need_location',
        'source': 'safe_fallback',
    }



def _weather_location_model_decision_enabled() -> bool:
    """Kept for compatibility with older call sites.

    Weather/location selection is now lane-owned: the active Chat stream agent or
    the active Responses stream agent decides whether to call get_weather /
    get_location and what structured place to pass.  The weather executor must
    not open a hidden secondary model call from inside a tool.
    """
    return False


def _decide_weather_location_strategy_once(user_text: str, messages: list | None = None, user_geo: dict | None = None, client_override=None) -> dict:
    """Resolve weather location without crossing lanes.

    This function intentionally does not call chat.completions or responses.
    It only consumes structured coordinates already available to this request.
    If the main streaming agent has an explicit place, it should pass it through
    structured_place so _build_weather_card can geocode it directly.
    """
    return _weather_location_safe_fallback_decision(user_text, messages=messages or [], user_geo=user_geo)


def _weather_geo_distance_km(a: dict | None, b: dict | None) -> float | None:
    try:
        if not isinstance(a, dict) or not isinstance(b, dict):
            return None
        lat1 = float(a.get("lat"))
        lon1 = float(a.get("lon"))
        lat2 = float(b.get("lat"))
        lon2 = float(b.get("lon"))
    except Exception:
        return None
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(max(0.0, h))))


def _weather_user_geo_with_memory(user_geo: dict | None, messages: list | None, user_text: str = "") -> tuple[dict | None, dict | None]:
    """Return available structured location context without rule-based switching."""
    effective_geo = _weather_effective_user_geo(user_geo)
    has_user_geo = isinstance(effective_geo, dict) and effective_geo.get("lat") is not None and effective_geo.get("lon") is not None
    if has_user_geo:
        return effective_geo, None
    memory = _extract_structured_weather_memory_from_messages(messages or [], current_user_text=user_text)
    if memory:
        return {"lat": memory.get("lat"), "lon": memory.get("lon"), "name": memory.get("name"), "source": memory.get("source")}, memory
    return user_geo, None


def _extract_weather_place_candidates(text: str) -> list[str]:
    # 地点抽取交给天气位置模型决策；这里不再用正则从自然语言里猜地点。
    return []


def _extract_weather_place(text: str) -> str:
    return ""


def _http_get_json(url: str, params: dict | None = None, timeout: float = 12.0, headers: dict | None = None, retries: int = 1, retry_delay: float = 0.6):
    hdrs = {"User-Agent": app_getenv("WEB_FETCH_UA", "Mozilla/5.0")}
    if headers:
        hdrs.update(headers)

    last_err = None
    attempts = max(1, int(retries) + 1)
    for i in range(attempts):
        try:
            r = requests.get(url, params=params or {}, timeout=timeout, headers=hdrs)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.SSLError as e:
            last_err = e
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_err = e
        except requests.exceptions.RequestException:
            raise
        if i < attempts - 1:
            time.sleep(max(0.0, float(retry_delay)))
    if last_err:
        raise last_err
    raise RuntimeError("http_get_json_failed")


_WEATHER_CACHE_LOCK = threading.Lock()
_WEATHER_GEOCODE_CACHE: dict[str, dict] = {}
_WEATHER_REVERSE_GEOCODE_CACHE: dict[str, dict] = {}
_WEATHER_FORECAST_CACHE: dict[str, dict] = {}


def _weather_cache_clone(value):
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:
        return value


def _weather_cache_trim_locked(store: dict, max_items: int = 256) -> None:
    try:
        overflow = max(0, len(store) - max_items)
        if overflow <= 0:
            return
        oldest = sorted(
            store.items(),
            key=lambda item: float((item[1] or {}).get('ts') or 0.0),
        )[:overflow]
        for key, _meta in oldest:
            store.pop(key, None)
    except Exception:
        return


def _weather_cache_get(store: dict, key: str, ttl_s: float):
    if not key or ttl_s <= 0:
        return None
    now = time.time()
    with _WEATHER_CACHE_LOCK:
        rec = store.get(key)
        if not isinstance(rec, dict):
            return None
        ts = float(rec.get('ts') or 0.0)
        if ts <= 0 or now - ts > ttl_s:
            store.pop(key, None)
            return None
        rec['ts'] = now
        store[key] = rec
        return _weather_cache_clone(rec.get('value'))


def _weather_cache_set(store: dict, key: str, value, max_items: int = 256):
    if not key:
        return value
    with _WEATHER_CACHE_LOCK:
        store[key] = {
            'ts': time.time(),
            'value': _weather_cache_clone(value),
        }
        _weather_cache_trim_locked(store, max_items=max_items)
    return value


def _weather_geocode_cache_key(query: str) -> str:
    q = re.sub(r'\s+', ' ', str(query or '').strip()).lower()
    return q[:120]


def _weather_reverse_geocode_cache_key(lat: float, lon: float) -> str:
    try:
        return f"{float(lat):.4f},{float(lon):.4f}"
    except Exception:
        return ''


def _weather_forecast_cache_key(lat: float, lon: float) -> str:
    try:
        precision = max(1, min(int(app_getenv('WEATHER_FORECAST_CACHE_ROUND', '3') or 3), 5))
    except Exception:
        precision = 3
    try:
        lat_v = round(float(lat), precision)
        lon_v = round(float(lon), precision)
    except Exception:
        return ''
    return f"{lat_v:.{precision}f},{lon_v:.{precision}f}"


def _reverse_geocode_name(lat: float, lon: float) -> str:
    cache_key = _weather_reverse_geocode_cache_key(lat, lon)
    cache_ttl = max(0, int(app_getenv('WEATHER_REVERSE_GEOCODE_CACHE_TTL', str(12 * 3600)) or (12 * 3600)))
    cached = _weather_cache_get(_WEATHER_REVERSE_GEOCODE_CACHE, cache_key, cache_ttl)
    if isinstance(cached, str) and cached.strip():
        app_logger.info('[weather_cache] reverse_geocode hit key=%s', cache_key)
        return cached.strip()
    try:
        data = _http_get_json(
            "https://nominatim.openstreetmap.org/reverse",
            params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 10, "addressdetails": 1},
            headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6"},
            timeout=10.0,
        )
        addr = data.get("address") or {}
        parts = [
            addr.get("city") or addr.get("town") or addr.get("county") or addr.get("state_district"),
            addr.get("state"),
            addr.get("country"),
        ]
        parts = [str(x).strip() for x in parts if str(x or "").strip()]
        result = parts[0] if len(parts) == 1 else " · ".join(parts[:2]) if parts else str(data.get("display_name") or "").split(",")[0].strip()
        if result:
            _weather_cache_set(_WEATHER_REVERSE_GEOCODE_CACHE, cache_key, result)
        return result
    except Exception:
        return ""




def _weather_place_geocode_confident(place_text: str, geocode_row: dict | None = None) -> bool:
    """Validate a geocoding hit by evidence, not by weather-word blacklists.

    Large weather/maps products do not treat an arbitrary sentence fragment as a
    location just because geocoding returned *something*.  They use the user's
    selected/explicit place, device location, biasing and confidence checks.  This
    guard keeps our old text extractor as a weak hypothesis only: a geocode hit is
    accepted only when the returned place still visibly matches the requested
    place string.  If it does not, the caller should fall back to browser geo,
    recent weather memory, or ask for clarification.
    """
    raw = str(place_text or '').strip()
    row = geocode_row if isinstance(geocode_row, dict) else {}
    if not raw or not row:
        return False

    def norm(v: str) -> str:
        t = str(v or '').lower()
        t = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fff]+', '', t)
        return t.strip()

    cand = norm(raw)
    if not cand:
        return False
    name = norm(str(row.get('name') or ''))
    # Some providers return "name · admin".  Keep the whole display string so
    # province/city pairs such as "北京朝阳" can still validate against
    # "朝阳区 · 北京市".
    result_text = norm(' '.join([
        str(row.get('name') or ''),
        str(row.get('admin1') or ''),
        str(row.get('admin2') or ''),
        str(row.get('country') or ''),
    ]))
    if not result_text:
        result_text = name
    if not result_text:
        return False

    suffix_re = r'(省|市|区|县|镇|乡|村|州|盟|旗|新区|特区|自治州|自治县)$'
    cand_core = re.sub(suffix_re, '', cand)
    result_core = re.sub(suffix_re, '', result_text)
    candidates = [x for x in {cand, cand_core} if x]
    targets = [x for x in {result_text, result_core, name} if x]

    for c in candidates:
        for t in targets:
            if c and (c in t or t in c):
                return True

    # When the streaming agent passes a full tool query such as "湖南娄底 天气"
    # instead of a separate place field, accept the geocode only if the returned
    # primary/admin place token is visibly present in the original query.  This
    # is evidence validation for the geocoder result, not weather-intent parsing.
    result_tokens = []
    for raw_token in (row.get('name'), row.get('admin2'), row.get('admin1')):
        token = norm(str(raw_token or ''))
        token_core = re.sub(suffix_re, '', token)
        for item in (token, token_core):
            if item and len(item) >= 2 and item not in result_tokens:
                result_tokens.append(item)
    for c in candidates:
        if any(tok in c for tok in result_tokens):
            return True

    # For very short CJK names, overlap alone is too weak: "今天" vs "天涯区"
    # would share one character, but it is not the same place.  Longer place
    # phrases can use high character coverage as a confidence signal.
    if len(cand_core or cand) <= 2:
        return False
    chars = [ch for ch in (cand_core or cand) if re.match(r'[0-9a-zA-Z\u4e00-\u9fff]', ch)]
    if not chars:
        return False
    unique = set(chars)
    hit = sum(1 for ch in unique if ch in result_text)
    coverage = hit / max(1, len(unique))
    return coverage >= 0.75
def _geocode_place_name(query: str) -> dict | None:
    q = str(query or "").strip()
    if not q:
        return None

    cache_key = _weather_geocode_cache_key(q)
    cache_ttl = max(0, int(app_getenv('WEATHER_GEOCODE_CACHE_TTL', str(12 * 3600)) or (12 * 3600)))
    cached = _weather_cache_get(_WEATHER_GEOCODE_CACHE, cache_key, cache_ttl)
    if isinstance(cached, dict) and cached.get('lat') is not None and cached.get('lon') is not None:
        app_logger.info('[weather_cache] geocode hit query=%s', q[:60])
        return cached

    def _pack_result(r0: dict, default_name: str):
        try:
            name = str(r0.get("name") or default_name).strip()
            admin1 = str(r0.get("admin1") or r0.get("state") or "").strip()
            admin2 = str(r0.get("admin2") or r0.get("county") or "").strip()
            country = str(r0.get("country") or "").strip()
            pretty = name
            for extra in (admin2, admin1, country):
                if extra and extra not in pretty:
                    pretty += f" · {extra}"
                    break
            return {
                "name": pretty,
                "lat": float(r0.get("latitude") if r0.get("latitude") is not None else r0.get("lat")),
                "lon": float(r0.get("longitude") if r0.get("longitude") is not None else r0.get("lon")),
            }
        except Exception:
            return None

    def _score_result(r0: dict, raw_q: str) -> tuple:
        name = str(r0.get("name") or "")
        admin1 = str(r0.get("admin1") or r0.get("state") or "")
        admin2 = str(r0.get("admin2") or r0.get("county") or "")
        country = str(r0.get("country") or "")
        cc = str(r0.get("country_code") or "").lower()
        text = f"{name} {admin2} {admin1} {country}".lower()
        ql = raw_q.lower()
        q2 = re.sub(r"(省|市|区|县|镇|乡|州|盟|旗|新区|特区|自治州|自治县)$", "", raw_q)
        exact = 1 if ql == name.lower() else 0
        contains = 1 if ql in text or q2.lower() in text else 0
        china = 1 if (cc == "cn" or "china" in text or "中国" in text) else 0
        return (exact, contains, china)

    # 1) Open-Meteo geocoding
    try:
        data = _http_get_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": q, "count": 5, "language": "zh", "format": "json"},
            timeout=10.0,
        )
        results = data.get("results") or []
        if results:
            results = sorted(results, key=lambda r: _score_result(r, q), reverse=True)
            packed = _pack_result(results[0], q)
            if packed:
                _weather_cache_set(_WEATHER_GEOCODE_CACHE, cache_key, packed)
                return packed
    except Exception:
        pass

    # 2) Nominatim search fallback
    try:
        data = _http_get_json(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "jsonv2", "limit": 5, "addressdetails": 1},
            headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6"},
            timeout=10.0,
        )
        if isinstance(data, list) and data:
            def _nm_to_open(r: dict):
                addr = r.get("address") or {}
                return {
                    "name": addr.get("city") or addr.get("town") or addr.get("county") or addr.get("state") or r.get("name") or q,
                    "admin1": addr.get("state") or "",
                    "admin2": addr.get("county") or addr.get("state_district") or "",
                    "country": addr.get("country") or "",
                    "country_code": addr.get("country_code") or "",
                    "lat": r.get("lat"),
                    "lon": r.get("lon"),
                }
            rows = [_nm_to_open(r) for r in data]
            rows = sorted(rows, key=lambda r: _score_result(r, q), reverse=True)
            packed = _pack_result(rows[0], q)
            if packed:
                _weather_cache_set(_WEATHER_GEOCODE_CACHE, cache_key, packed)
                return packed
    except Exception:
        pass
    return None


def _weather_number(v, digits: int = 0):
    try:
        x = float(v)
    except Exception:
        return v
    if digits <= 0:
        return int(round(x))
    return round(x, digits)


def _weather_card_display_number(v):
    return _weather_number(v, digits=0)


def _weather_summary_text(payload: dict, user_text: str = "") -> str:
    try:
        cur = payload.get("current") or {}
        daily = (payload.get("daily") or [])[:1]
        place = ((payload.get("location") or {}).get("name") or "当前位置").split(" · ")[0]
        temp = cur.get("temperature")
        feels = cur.get("feels_like")
        weather = str(cur.get("weather") or "").strip()
        precip = None
        if daily and isinstance(daily[0], dict):
            precip = daily[0].get("precip")
        intent = _weather_intent_kind(user_text)

        def _fmt_temp(v):
            try:
                return f"{round(float(v))}°C"
            except Exception:
                return ""

        parts = []
        if weather:
            parts.append(f"{place}现在{weather}")
        else:
            parts.append(f"{place}现在天气已查到")
        if temp is not None:
            parts.append(f"气温大约{_fmt_temp(temp)}")
        if feels is not None:
            parts.append(f"体感{_fmt_temp(feels)}")

        tip = ""
        try:
            t = float(temp) if temp is not None else None
        except Exception:
            t = None
        try:
            p = float(precip) if precip is not None else None
        except Exception:
            p = None
        if intent == "advice":
            if p is not None and p >= 40:
                tip = "出门带伞会更稳妥。"
            elif t is not None and t <= 12:
                tip = "外出建议加件外套。"
            elif t is not None and t >= 30:
                tip = "体感会偏热，注意补水。"
            else:
                tip = "整体看出门问题不大。"
        else:
            if p is not None and p >= 50:
                tip = "今天有一定降水概率。"
            elif t is not None and t <= 10:
                tip = "整体偏凉。"
            elif t is not None and t >= 30:
                tip = "整体偏热。"

        text = "，".join([x for x in parts if x])
        if tip:
            text = f"{text}，{tip}"
        return text.strip("， ")
    except Exception:
        return ""


def _weather_context_text(payload: dict, user_text: str = "") -> str:
    """Build a compact weather context block for the model from the same data used by the UI card."""
    try:
        if not isinstance(payload, dict):
            return ""
        if not payload.get("ok", True):
            bits = ["【天气数据】"]
            msg = str(payload.get("message") or "").strip()
            if msg:
                bits.append(f"状态：{msg}")
            tips = payload.get("tips") or []
            if isinstance(tips, list) and tips:
                bits.append("可提示用户补充地点：" + "；".join(str(x) for x in tips[:3] if str(x).strip()))
            return "\n".join(bits).strip()

        loc = payload.get("location") or {}
        cur = payload.get("current") or {}
        hourly = payload.get("hourly") or []
        daily = payload.get("daily") or []
        unit = str(cur.get("temperature_unit") or "°C")
        wind_unit = str(cur.get("wind_speed_unit") or "km/h")

        lines = ["【天气数据】"]
        if user_text:
            lines.append(f"用户问题：{str(user_text).strip()}")
        lines.append(f"地点：{str(loc.get('name') or '当前位置').strip()}")

        cur_bits = []
        if cur.get('weather'):
            cur_bits.append(f"天气：{cur.get('weather')}")
        if cur.get('temperature') is not None:
            cur_bits.append(f"温度：{cur.get('temperature')}{unit}")
        if cur.get('feels_like') is not None:
            cur_bits.append(f"体感：{cur.get('feels_like')}{unit}")
        if cur.get('humidity') is not None:
            cur_bits.append(f"湿度：{cur.get('humidity')}%")
        if cur.get('wind_speed') is not None:
            cur_bits.append(f"风速：{cur.get('wind_speed')} {wind_unit}")
        if cur.get('pressure') is not None:
            cur_bits.append(f"气压：{cur.get('pressure')} hPa")
        if cur.get('precipitation') is not None:
            cur_bits.append(f"当前降水：{cur.get('precipitation')} mm")
        if cur_bits:
            lines.append("当前：" + "；".join(str(x) for x in cur_bits if str(x).strip()))

        if hourly:
            hs = []
            for h in hourly[:6]:
                if not isinstance(h, dict):
                    continue
                piece = []
                tm = str(h.get('time') or '').strip()
                if tm:
                    piece.append(tm)
                if h.get('weather'):
                    piece.append(str(h.get('weather')))
                if h.get('temp') is not None:
                    piece.append(f"{h.get('temp')}{unit}")
                if h.get('precip') is not None:
                    piece.append(f"降水{h.get('precip')}%")
                if piece:
                    hs.append(" ".join(piece))
            if hs:
                lines.append("未来数小时：" + " | ".join(hs))

        if daily:
            ds = []
            for d in daily[:3]:
                if not isinstance(d, dict):
                    continue
                piece = []
                label = str(d.get('label') or d.get('date') or '').strip()
                if label:
                    piece.append(label)
                if d.get('weather'):
                    piece.append(str(d.get('weather')))
                if d.get('temp_max') is not None or d.get('temp_min') is not None:
                    piece.append(f"{d.get('temp_max','--')}{unit}/{d.get('temp_min','--')}{unit}")
                if d.get('precip') is not None:
                    piece.append(f"降水{d.get('precip')}%")
                if piece:
                    ds.append(" ".join(piece))
            if ds:
                lines.append("未来几天：" + " | ".join(ds))

        summary = str(payload.get('summary') or '').strip()
        if summary:
            lines.append("摘要：" + summary)

        lines.append("请基于以上天气数据自然回答用户，不要机械复述全部字段；优先总结最有用的信息，并可顺带给出简短建议。不要说你无法看到天气卡片或无法获取实时天气。")
        return "\n".join(lines).strip()
    except Exception:
        return ""


def _inject_weather_context_messages(messages: list, weather_payload: dict, user_text: str = "") -> list:
    out = list(messages or [])
    block = _weather_context_text(weather_payload, user_text=user_text)
    if not block:
        return out
    # avoid duplicate injection
    for m in out:
        if isinstance(m, dict) and m.get('role') == 'system' and m.get('_kind') == 'weather_ctx':
            return out
    insert_at = 0
    while insert_at < len(out) and isinstance(out[insert_at], dict) and out[insert_at].get('role') == 'system':
        insert_at += 1
    out.insert(insert_at, {'role': 'system', '_kind': 'weather_ctx', 'content': block})
    return out


def _geo_debug_brief(geo: dict | None) -> dict:
    try:
        if not isinstance(geo, dict):
            return {}
        out = {}
        if geo.get('name'):
            out['name'] = str(geo.get('name'))[:80]
        if geo.get('lat') is not None:
            out['lat'] = round(float(geo.get('lat')), 6)
        if geo.get('lon') is not None:
            out['lon'] = round(float(geo.get('lon')), 6)
        if geo.get('source'):
            out['source'] = str(geo.get('source'))[:40]
        if geo.get('accuracy') is not None:
            out['accuracy'] = geo.get('accuracy')
        return out
    except Exception:
        return {'raw': str(geo)[:160]}


def _build_weather_card(user_text: str, user_geo: dict | None = None, messages: list | None = None, client_override=None, structured_place: str = '') -> dict:
    text = str(user_text or "").strip()
    place = ""
    lat = lon = None
    location_name = ""
    user_geo = _weather_effective_user_geo(user_geo)

    structured_place = str(structured_place or '').strip()
    if structured_place:
        decision = {
            'action': 'explicit_place',
            'explicit_place_text': structured_place[:80],
            'switched_place': False,
            'reason': 'main_agent_structured_place',
            'source': 'main_agent',
        }
    else:
        decision = _decide_weather_location_strategy_once(text, messages=messages or [], user_geo=user_geo, client_override=client_override)
    app_logger.warning('[DEBUG_WEATHER_LOC_DECISION] text=%r decision=%s user_geo=%s', text, decision, _geo_debug_brief(user_geo))

    decision_action = str((decision or {}).get('action') or '').strip()
    decision_source = str((decision or {}).get('source') or '').strip().lower()
    decision_place = str((decision or {}).get('explicit_place_text') or '').strip()
    has_live_user_geo = isinstance(user_geo, dict) and user_geo.get('lat') is not None and user_geo.get('lon') is not None
    memory = None

    if decision_action == 'explicit_place' and decision_place:
        if re.fullmatch(r"[-+]?\d{1,2}(?:\.\d+)?\s*,\s*[-+]?\d{1,3}(?:\.\d+)?", decision_place):
            lat_s, lon_s = [x.strip() for x in decision_place.split(',', 1)]
            lat, lon = float(lat_s), float(lon_s)
            location_name = _reverse_geocode_name(lat, lon) or f"{lat:.2f},{lon:.2f}"
            place = decision_place
        else:
            g = _geocode_place_name(decision_place)
            if g and _weather_place_geocode_confident(decision_place, g):
                place = decision_place
                lat, lon = g['lat'], g['lon']
                location_name = g['name']
            else:
                try:
                    app_logger.info(
                        '[weather_location_resolver] rejected_weak_place place=%s geocode=%s user_geo=%s',
                        str(decision_place or '')[:80],
                        _geo_debug_brief(g if isinstance(g, dict) else {}),
                        _geo_debug_brief(user_geo),
                    )
                except Exception:
                    pass
                # Do not let a weak geocode hit override live browser location.
                # If no better location source exists below, the normal need-location
                # response will be returned.

    if (lat is None or lon is None) and not structured_place and text:
        # Same-lane fallback for old/new model calls that put the named place in
        # query instead of the optional place field.  Try the query as geocoder
        # evidence before falling back to the browser position, so explicit user
        # places like "湖南娄底 天气" do not get overwritten by current geo.
        query_geo = None
        if re.fullmatch(r"[-+]?\d{1,2}(?:\.\d+)?\s*,\s*[-+]?\d{1,3}(?:\.\d+)?", text):
            try:
                lat_s, lon_s = [x.strip() for x in text.split(',', 1)]
                lat, lon = float(lat_s), float(lon_s)
                location_name = _reverse_geocode_name(lat, lon) or f"{lat:.2f},{lon:.2f}"
                place = text
                query_geo = {'lat': lat, 'lon': lon, 'name': location_name}
            except Exception:
                query_geo = None
        else:
            query_geo = _geocode_place_name(text)
            if query_geo and _weather_place_geocode_confident(text, query_geo):
                place = text
                lat, lon = query_geo['lat'], query_geo['lon']
                location_name = query_geo['name']
            elif query_geo:
                try:
                    app_logger.info(
                        '[weather_location_resolver] rejected_query_geocode query=%s geocode=%s user_geo=%s',
                        str(text or '')[:80],
                        _geo_debug_brief(query_geo if isinstance(query_geo, dict) else {}),
                        _geo_debug_brief(user_geo),
                    )
                except Exception:
                    pass

    if (lat is None or lon is None) and decision_action == 'recent_weather':
        memory = _extract_structured_weather_memory_from_messages(messages or [], current_user_text=text)
        if isinstance(memory, dict) and memory.get('lat') is not None and memory.get('lon') is not None:
            lat = float(memory.get('lat'))
            lon = float(memory.get('lon'))
            location_name = str(memory.get('name') or '').strip() or _reverse_geocode_name(lat, lon) or '当前位置'

    if lat is None or lon is None:
        if decision_action != 'need_location' and isinstance(user_geo, dict) and user_geo.get('lat') is not None and user_geo.get('lon') is not None:
            lat = float(user_geo.get('lat'))
            lon = float(user_geo.get('lon'))
            location_name = _reverse_geocode_name(lat, lon) or '当前位置'
        elif decision_action != 'need_location':
            memory = _extract_structured_weather_memory_from_messages(messages or [], current_user_text=text)
            if isinstance(memory, dict) and memory.get('lat') is not None and memory.get('lon') is not None:
                lat = float(memory.get('lat'))
                lon = float(memory.get('lon'))
                location_name = str(memory.get('name') or '').strip() or _reverse_geocode_name(lat, lon) or '当前位置'
        if lat is None or lon is None:
            return {
                '_kind': 'weather',
                'ok': False,
                'need_location': True,
                'message': '要直接显示天气卡片，需要城市名，或者允许浏览器定位。',
                'tips': ['例如：北京天气', '也可以开启定位后直接问：今天天气'],
            }

    forecast_cache_key = _weather_forecast_cache_key(lat, lon)
    forecast_cache_ttl = max(0, int(app_getenv('WEATHER_FORECAST_CACHE_TTL', '180') or 180))
    forecast = _weather_cache_get(_WEATHER_FORECAST_CACHE, forecast_cache_key, forecast_cache_ttl)
    if isinstance(forecast, dict):
        app_logger.info('[weather_cache] forecast hit location=%s key=%s', location_name or place or '当前位置', forecast_cache_key)
    else:
        try:
            forecast = _http_get_json(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "timezone": "auto",
                    "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,pressure_msl,wind_speed_10m,weather_code,is_day",
                    "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
                    "forecast_days": 7,
                },
                timeout=12.0,
                retries=1,
                retry_delay=0.8,
            )
            if isinstance(forecast, dict):
                _weather_cache_set(_WEATHER_FORECAST_CACHE, forecast_cache_key, forecast)
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
            return {
            "_kind": "weather",
            "ok": False,
            "need_location": False,
            "location": location_name or "当前位置",
            "message": "天气服务暂时连接失败，我先不展示天气卡片了。",
            "tips": ["可以稍后再试一次", "也可以改成让我直接联网搜这座城市的天气情况"],
            "error": f"{type(e).__name__}: {e}",
        }

    cur = forecast.get("current") or {}
    cur_units = forecast.get("current_units") or {}
    h = forecast.get("hourly") or {}
    d = forecast.get("daily") or {}

    desc, emoji = _weather_desc(cur.get("weather_code"))

    hourly = []
    times = h.get("time") or []
    temps = h.get("temperature_2m") or []
    pps = h.get("precipitation_probability") or []
    wcodes = h.get("weather_code") or []
    winds = h.get("wind_speed_10m") or []
    for i in range(min(12, len(times), len(temps))):
        hdesc, hemoji = _weather_desc(wcodes[i] if i < len(wcodes) else None)
        t = str(times[i] or "")
        hourly.append({
            "time": t[11:16] if len(t) >= 16 else t,
            "temp": _weather_card_display_number(temps[i]),
            "precip": pps[i] if i < len(pps) else None,
            "weather": hdesc,
            "emoji": hemoji,
            "wind": winds[i] if i < len(winds) else None,
        })

    daily = []
    dates = d.get("time") or []
    tmax = d.get("temperature_2m_max") or []
    tmin = d.get("temperature_2m_min") or []
    dpps = d.get("precipitation_probability_max") or []
    dwcodes = d.get("weather_code") or []
    sunrise = d.get("sunrise") or []
    sunset = d.get("sunset") or []
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for i in range(min(7, len(dates), len(tmax), len(tmin))):
        ds = str(dates[i] or "")
        try:
            dt = datetime.datetime.strptime(ds, "%Y-%m-%d")
            label = "今天" if i == 0 else weekdays[dt.weekday()]
        except Exception:
            label = "今天" if i == 0 else ds
        ddesc, demoji = _weather_desc(dwcodes[i] if i < len(dwcodes) else None)
        daily.append({
            "date": ds,
            "label": label,
            "temp_max": tmax[i],
            "temp_min": tmin[i],
            "precip": dpps[i] if i < len(dpps) else None,
            "weather": ddesc,
            "emoji": demoji,
            "sunrise": str(sunrise[i] or "")[-5:] if i < len(sunrise) and sunrise[i] else "",
            "sunset": str(sunset[i] or "")[-5:] if i < len(sunset) and sunset[i] else "",
        })

    payload = {
        "_kind": "weather",
        "ok": True,
        "source": "open-meteo",
        "intent": _weather_intent_kind(user_text),
        "location": {
            "name": location_name or "当前位置",
            "lat": lat,
            "lon": lon,
        },
        "current": {
            "time": cur.get("time"),
            "temperature": _weather_card_display_number(cur.get("temperature_2m")),
            "temperature_unit": cur_units.get("temperature_2m") or "°C",
            "feels_like": _weather_card_display_number(cur.get("apparent_temperature")),
            "humidity": _weather_number(cur.get("relative_humidity_2m"), 0),
            "precipitation": _weather_number(cur.get("precipitation"), 1),
            "pressure": _weather_number(cur.get("pressure_msl"), 0),
            "wind_speed": _weather_number(cur.get("wind_speed_10m"), 1),
            "wind_speed_unit": cur_units.get("wind_speed_10m") or "km/h",
            "weather": desc,
            "emoji": emoji,
            "is_day": cur.get("is_day"),
        },
        "hourly": hourly,
        "daily": daily,
    }
    payload["summary"] = _weather_summary_text(payload, user_text=user_text)
    return payload
