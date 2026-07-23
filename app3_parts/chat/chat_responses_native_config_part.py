# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: Responses-native config, web_search tool spec, and request params.
# Loaded before chat_streaming_part.py, sharing the original global namespace.


class ResponsesNativeConfigContext:
    def __init__(
        self,
        *,
        user_geo: dict | None = None,
        user_time: dict | None = None,
        agent_stream_env_flag=None,
        agent_stream_web_enabled_for_turn=None,
    ):
        self.user_geo = dict(user_geo or {}) if isinstance(user_geo, dict) else {}
        self.user_time = dict(user_time or {}) if isinstance(user_time, dict) else {}
        self.agent_stream_env_flag = agent_stream_env_flag if callable(agent_stream_env_flag) else (lambda name, default='0': False)
        self.agent_stream_web_enabled_for_turn = agent_stream_web_enabled_for_turn if callable(agent_stream_web_enabled_for_turn) else (lambda: True)

    def web_search_enabled(self) -> bool:
        try:
            if not self.agent_stream_env_flag('RESPONSES_NATIVE_WEB_SEARCH_ENABLED', '1'):
                return False
        except Exception:
            raw = str(app_getenv('RESPONSES_NATIVE_WEB_SEARCH_ENABLED', '1') or '1').strip().lower()
            if raw in {'0', 'false', 'no', 'off', 'disabled'}:
                return False
        try:
            if not self.agent_stream_web_enabled_for_turn():
                return False
        except Exception:
            pass
        return True

    def override_snapshot(self) -> dict:
        try:
            getter = globals().get('_current_request_overrides_snapshot')
            snap = getter() if callable(getter) else {}
            return dict(snap or {}) if isinstance(snap, dict) else {}
        except Exception:
            return {}

    def cfg_value(self, *names: str, default=None):
        overrides = self.override_snapshot()
        for name in names:
            key = str(name or '').strip()
            if key and key in overrides and overrides.get(key) not in (None, ''):
                return overrides.get(key)
        for name in names:
            key = str(name or '').strip()
            if not key:
                continue
            try:
                val = app_getenv(key, None)
            except Exception:
                val = None
            if val not in (None, ''):
                return val
        return default

    def cfg_bool(self, *names: str, default: bool = False) -> bool:
        val = self.cfg_value(*names, default=('1' if default else '0'))
        raw = str(val if val is not None else '').strip().lower()
        if raw in {'1', 'true', 'yes', 'on', 'enabled'}:
            return True
        if raw in {'0', 'false', 'no', 'off', 'disabled'}:
            return False
        return bool(default)

    def cfg_int(self, *names: str, default: int = 0, min_value: int = 0, max_value: int = 128) -> int:
        val = self.cfg_value(*names, default=default)
        try:
            num = int(float(str(val).strip()))
        except Exception:
            num = int(default)
        if num < min_value:
            num = min_value
        if num > max_value:
            num = max_value
        return num

    def split_list_value(self, raw) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, (list, tuple, set)):
            parts = list(raw)
        else:
            text = str(raw or '').strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
                if isinstance(parsed, (list, tuple, set)):
                    parts = list(parsed)
                else:
                    parts = re.split(r'[,\n;\s]+', text)
            except Exception:
                parts = re.split(r'[,\n;\s]+', text)
        out: list[str] = []
        seen: set[str] = set()
        for item in parts:
            val = str(item or '').strip()
            if not val:
                continue
            val = re.sub(r'^https?://', '', val, flags=re.I)
            val = val.split('/')[0].split('?')[0].split('#')[0].strip().lower()
            val = val.strip(' .')[:253]
            if not val or val in seen:
                continue
            seen.add(val)
            out.append(val)
        return out[:100]

    def user_location_from_settings(self) -> dict:
        raw_json = self.cfg_value('RESPONSES_NATIVE_WEB_SEARCH_USER_LOCATION_JSON', 'RESPONSES_WEB_SEARCH_USER_LOCATION_JSON', 'WEB_SEARCH_USER_LOCATION_JSON', default='')
        if raw_json:
            try:
                parsed = json.loads(str(raw_json or '{}'))
                if isinstance(parsed, dict):
                    loc = dict(parsed)
                    loc['type'] = str(loc.get('type') or 'approximate').strip() or 'approximate'
                    return {str(k): v for k, v in loc.items() if v not in (None, '')}
            except Exception:
                pass
        country = str(self.cfg_value('RESPONSES_NATIVE_WEB_SEARCH_COUNTRY', 'RESPONSES_WEB_SEARCH_COUNTRY', 'WEB_SEARCH_COUNTRY', default='') or '').strip().upper()
        city = str(self.cfg_value('RESPONSES_NATIVE_WEB_SEARCH_CITY', 'RESPONSES_WEB_SEARCH_CITY', 'WEB_SEARCH_CITY', default='') or '').strip()
        region = str(self.cfg_value('RESPONSES_NATIVE_WEB_SEARCH_REGION', 'RESPONSES_WEB_SEARCH_REGION', 'WEB_SEARCH_REGION', default='') or '').strip()
        timezone_name = str(self.cfg_value('RESPONSES_NATIVE_WEB_SEARCH_TIMEZONE', 'RESPONSES_WEB_SEARCH_TIMEZONE', 'WEB_SEARCH_TIMEZONE', default='') or '').strip()
        if not any([country, city, region, timezone_name]):
            approx = self.user_geo.get('approximate_location') if isinstance(self.user_geo, dict) and isinstance(self.user_geo.get('approximate_location'), dict) else (self.user_geo if isinstance(self.user_geo, dict) else {})
            country = str(approx.get('country') or approx.get('country_code') or '').strip().upper()
            if len(country) > 2:
                country = ''
            city = str(approx.get('city') or '').strip()
            region = str(approx.get('region') or approx.get('region_code') or '').strip()
            timezone_name = str((approx.get('timezone') if isinstance(approx, dict) else '') or (self.user_time.get('timezone') if isinstance(self.user_time, dict) else '') or '').strip()
        loc = {'type': 'approximate'}
        if country and len(country) == 2:
            loc['country'] = country
        if city:
            loc['city'] = city[:120]
        if region:
            loc['region'] = region[:120]
        if timezone_name:
            loc['timezone'] = timezone_name[:120]
        return loc if len(loc) > 1 else {}

    def web_search_tool_spec(self) -> dict:
        raw_type = str(self.cfg_value('RESPONSES_NATIVE_WEB_SEARCH_TOOL_TYPE', default='web_search') or 'web_search').strip().lower()
        tool_type = raw_type if raw_type in {'web_search', 'web_search_preview'} else 'web_search'
        spec = {'type': tool_type}
        context_size = str(self.cfg_value('RESPONSES_NATIVE_WEB_SEARCH_CONTEXT_SIZE', 'RESPONSES_WEB_SEARCH_CONTEXT_SIZE', 'WEB_SEARCH_CONTEXT_SIZE', default='medium') or 'medium').strip().lower()
        if context_size in {'low', 'medium', 'high'}:
            spec['search_context_size'] = context_size
        user_location = self.user_location_from_settings()
        if user_location:
            spec['user_location'] = user_location
        allowed_domains = self.split_list_value(self.cfg_value('RESPONSES_NATIVE_WEB_SEARCH_ALLOWED_DOMAINS', 'RESPONSES_WEB_SEARCH_ALLOWED_DOMAINS', 'WEB_SEARCH_ALLOWED_DOMAINS', default=''))
        blocked_domains = self.split_list_value(self.cfg_value('RESPONSES_NATIVE_WEB_SEARCH_BLOCKED_DOMAINS', 'RESPONSES_WEB_SEARCH_BLOCKED_DOMAINS', 'WEB_SEARCH_BLOCKED_DOMAINS', default=''))
        if tool_type == 'web_search':
            filters = {}
            if allowed_domains:
                filters['allowed_domains'] = allowed_domains
            if blocked_domains:
                filters['blocked_domains'] = blocked_domains
            if filters:
                spec['filters'] = filters
            external_raw = str(self.cfg_value('RESPONSES_NATIVE_WEB_SEARCH_EXTERNAL_ACCESS', default='') or '').strip().lower()
            if external_raw in {'0', 'false', 'no', 'off'}:
                spec['external_web_access'] = False
            elif external_raw in {'1', 'true', 'yes', 'on'}:
                spec['external_web_access'] = True
        elif allowed_domains:
            # Older web_search_preview-compatible providers commonly expose a
            # `domains` field rather than the newer Responses `filters` object.
            spec['domains'] = allowed_domains
        return spec

    def has_web_search_tool(self, tools: list | None = None) -> bool:
        try:
            return any(str((tool or {}).get('type') or '').strip().lower() in {'web_search', 'web_search_preview'} for tool in (tools or []) if isinstance(tool, dict))
        except Exception:
            return False

    def apply_web_request_params(self, body: dict, tools: list | None = None) -> dict:
        if not isinstance(body, dict) or not self.has_web_search_tool(tools):
            return {}
        applied = {}
        include = body.get('include') if isinstance(body.get('include'), list) else []
        include = [str(x or '').strip() for x in include if str(x or '').strip()]
        if self.cfg_bool('RESPONSES_NATIVE_WEB_SEARCH_INCLUDE_SOURCES', 'RESPONSES_WEB_SEARCH_INCLUDE_SOURCES', default=True):
            if 'web_search_call.action.sources' not in include:
                include.append('web_search_call.action.sources')
            applied['include_sources'] = True
        # Official Responses can return the concrete search result rows as
        # `web_search_call.results`.  Keep it configurable because a few relays
        # may lag behind the official include enum, but default it on so native
        # web_search has enough data to bind websites to the exact search call.
        if self.cfg_bool('RESPONSES_NATIVE_WEB_SEARCH_INCLUDE_RESULTS', 'RESPONSES_WEB_SEARCH_INCLUDE_RESULTS', default=True):
            if 'web_search_call.results' not in include:
                include.append('web_search_call.results')
            applied['include_results'] = True
        if include:
            body['include'] = include
        try:
            web_tools = [dict(t) for t in (tools or []) if isinstance(t, dict) and str((t or {}).get('type') or '').strip().lower() in {'web_search', 'web_search_preview'}]
            if web_tools:
                applied['tool_types'] = [str(t.get('type') or '') for t in web_tools]
                applied['tool_keys'] = sorted({str(k) for t in web_tools for k in t.keys()})
        except Exception:
            pass
        return applied
