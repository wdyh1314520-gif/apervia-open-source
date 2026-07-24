# source/search/fetch activity extraction and metadata helpers.


class ChatStreamSourceActivityContext:
    def __init__(self, *, append_progress_event=None, progress_meta=None, focus_crop_activity=None, cfg_int=None):
        self.append_progress_event = append_progress_event if callable(append_progress_event) else (lambda *args, **kwargs: {})
        self.progress_meta = progress_meta if callable(progress_meta) else (lambda *args, **kwargs: {})
        self.focus_crop_activity = focus_crop_activity if callable(focus_crop_activity) else (lambda *args, **kwargs: {})
        self.cfg_int = cfg_int if callable(cfg_int) else self._fallback_cfg_int

    @staticmethod
    def _fallback_cfg_int(name: str, default: int, *, min_value: int = 0, max_value: int = 10000) -> int:
        try:
            value = int(str(app_getenv(name, str(default)) or default).strip())
        except Exception:
            value = int(default)
        return max(int(min_value), min(int(max_value), value))

    def search_source_item_limit(self) -> int:
        # Preserve all search-result website chips the provider returns in normal use.
        # Keep a high safety cap so a malformed/huge JSON payload cannot bloat SSE frames.
        return self.cfg_int('RESPONSES_SEARCH_ACTIVITY_SOURCE_ITEMS_LIMIT', 200, min_value=24, max_value=500)

    def push_sources(self, state: dict, name: str, result: dict | None = None, *, target: str = '') -> None:
        result = result or {}
        if not isinstance(state, dict):
            return

        def _bucket(kind: str):
            # sources = pages the assistant actually opened/read and can cite.
            # searched_sources = raw search result websites shown only in the process panel.
            key = 'searched_sources' if kind == 'searched' else 'sources'
            seen_key = 'searched_source_seen' if kind == 'searched' else 'source_seen'
            rows = state.setdefault(key, [])
            seen = state.setdefault(seen_key, set())
            if not isinstance(rows, list):
                rows = []
                state[key] = rows
            if not isinstance(seen, set):
                try:
                    seen = set(seen or [])
                except Exception:
                    seen = set()
                state[seen_key] = seen
            return rows, seen

        def _push(url: str, title: str = '', snippet: str = '', favicon: str = '', *, kind: str = 'sources') -> None:
            u = str(url or '').strip()
            if not u:
                return
            try:
                if not _is_public_visible_source_url(u):
                    return
                u = _normalize_visible_source_url(u)
            except Exception:
                pass
            rows, seen = _bucket('searched' if kind == 'searched' else 'sources')
            if not u or u in seen:
                return
            seen.add(u)
            rows.append({
                'title': str(title or _host_of(u) or u)[:200],
                'url': u[:500],
                'host': _host_of(u)[:120],
                'snippet': _planner_safe_text(str(snippet or ''), max_len=260),
                **({'favicon': str(favicon or '')[:500]} if str(favicon or '').strip() else {}),
            })

        try:
            target_kind = str(target or '').strip().lower()
            if not target_kind:
                target_kind = 'searched' if name in {'web_search', 'image_search'} else 'sources'
            if name == 'web_search':
                # Search chips in the activity panel must come from the real
                # search result websites, not from pages later opened/read.
                # Providers can return rows under results/items/organic/data/etc.;
                # reuse the broad extractor instead of looking only at results.
                for item in self.source_items_from_result(result, limit=self.search_source_item_limit()):
                    if isinstance(item, dict):
                        _push(
                            item.get('url') or '',
                            item.get('title') or item.get('host') or '',
                            item.get('snippet') or '',
                            item.get('favicon') or item.get('icon') or item.get('icon_url') or item.get('iconUrl') or '',
                            kind='searched',
                        )
            elif name == 'image_search':
                for item in (result.get('results') or result.get('images') or []):
                    if isinstance(item, dict):
                        _push(
                            item.get('source_url') or item.get('page_url') or item.get('url') or '',
                            item.get('title') or item.get('source') or '',
                            item.get('snippet') or '',
                            item.get('favicon') or item.get('icon') or item.get('icon_url') or item.get('iconUrl') or '',
                            kind=target_kind,
                        )
            elif name == 'fetch_url':
                _push(
                    result.get('url') or '',
                    result.get('title') or '',
                    result.get('text') or result.get('snippet') or '',
                    result.get('favicon') or result.get('icon') or result.get('icon_url') or result.get('iconUrl') or '',
                    kind='sources',
                )
            elif name == 'fetch_urls':
                for item in (result.get('results') or result.get('pages') or []):
                    if isinstance(item, dict):
                        _push(
                            item.get('url') or '',
                            item.get('title') or '',
                            item.get('text') or item.get('snippet') or '',
                            item.get('favicon') or item.get('icon') or item.get('icon_url') or item.get('iconUrl') or '',
                            kind='sources',
                        )
        except Exception:
            pass

    def visible_sources(self, state: dict | None = None, limit: int = 8) -> list[dict]:
        if not isinstance(state, dict):
            return []
        primary = _visible_sources_from_result_rows(state.get('sources') or [], limit=limit)
        if primary:
            return primary
        return _visible_sources_from_result_rows(state.get('searched_sources') or [], limit=limit)

    def web_query_text(self, args: dict | None = None, result: dict | None = None) -> str:
        row = result if isinstance(result, dict) else {}
        arg = args if isinstance(args, dict) else {}
        values = []
        def add(value):
            if value is None:
                return
            if isinstance(value, str):
                text = re.sub(r'\s+', ' ', value.strip())
                if text and text not in values:
                    values.append(text)
            elif isinstance(value, (list, tuple)):
                for child in value[:12]:
                    add(child)
            elif isinstance(value, dict):
                add(value.get('query') or value.get('search_query') or value.get('search_terms') or value.get('text') or value.get('summary') or value.get('label'))
        for source in (arg, row):
            add(source.get('query') or source.get('search_query') or source.get('search_terms') or source.get('text'))
            add(source.get('queries') or source.get('search_queries'))
            add(source.get('summary') or source.get('query_summary') or source.get('querySummary') or source.get('label'))
            nested = source.get('request') or source.get('action') or source.get('arguments') or source.get('input')
            if isinstance(nested, (dict, list, tuple)):
                add(nested)
        return (values[0] if values else '')[:800]

    def source_items_from_result(self, result: dict | list | None = None, limit: int = 200) -> list[dict]:
        """Extract visible website chips from every search/fetch result shape.

        The activity panel must show the real websites returned/read by the
        tools.  Older code only looked at result["results"], but our search
        gateway and fetch tools may return rows under organic/items/data/pages
        or nested result containers.  This function is intentionally broad but
        still refuses non-public/internal URLs through _is_public_visible_source_url.
        """
        rows: list[dict] = []
        seen: set[str] = set()
        max_items = max(1, min(int(limit or 200), 500))

        def _as_list(value):
            if isinstance(value, list):
                return value
            if isinstance(value, tuple):
                return list(value)
            return []

        def _push(url: str, title: str = '', snippet: str = '', favicon: str = '') -> None:
            if len(rows) >= max_items:
                return
            u = str(url or '').strip()
            if not u:
                return
            try:
                if not _is_public_visible_source_url(u):
                    return
                u = _normalize_visible_source_url(u)
            except Exception:
                pass
            if not u:
                return
            key = u.lower()
            if key in seen:
                return
            seen.add(key)
            host = _host_of(u)
            rows.append({
                'title': str(title or host or u)[:200],
                'url': u[:500],
                'host': host[:120],
                'snippet': _planner_safe_text(str(snippet or ''), max_len=260),
                **({'favicon': str(favicon or '')[:500]} if str(favicon or '').strip() else {}),
            })

        def _row_url(src: dict) -> str:
            return str(
                src.get('url') or src.get('uri') or src.get('link') or src.get('href') or
                src.get('source_url') or src.get('sourceUrl') or src.get('page_url') or src.get('pageUrl') or
                src.get('canonical_url') or src.get('canonicalUrl') or src.get('displayLink') or ''
            ).strip()

        def _row_title(src: dict) -> str:
            return str(
                src.get('title') or src.get('name') or src.get('site_name') or src.get('siteName') or
                src.get('source') or src.get('provider') or src.get('host') or src.get('domain') or ''
            ).strip()

        def _row_snippet(src: dict) -> str:
            return str(
                src.get('snippet') or src.get('summary') or src.get('description') or src.get('text') or
                src.get('content') or src.get('body') or src.get('markdown') or ''
            ).strip()

        def _row_favicon(src: dict) -> str:
            return str(src.get('favicon') or src.get('icon') or src.get('icon_url') or src.get('iconUrl') or '').strip()

        def _visit(node, depth: int = 0) -> None:
            if len(rows) >= max_items or depth > 5:
                return
            if isinstance(node, list):
                for child in node:
                    _visit(child, depth + 1)
                    if len(rows) >= max_items:
                        break
                return
            if not isinstance(node, dict):
                return

            citation = node.get('url_citation') if isinstance(node.get('url_citation'), dict) else None
            src = citation or node
            url = _row_url(src)
            if url:
                _push(url, _row_title(src), _row_snippet(src), _row_favicon(src))

            # Common search/fetch provider containers. Keep this list explicit so
            # we do not walk arbitrary huge JSON payloads, but cover the gateway
            # shapes used by external, searxng, Tavily/Serper-like adapters and fetch_urls.
            for key in (
                'results', 'items', 'sources', 'organic', 'organic_results', 'search_results',
                'searched_results', 'web_results', 'webPages', 'pages', 'documents', 'data',
                'links', 'citations', 'references', 'annotations', 'output', 'records',
            ):
                value = node.get(key)
                if isinstance(value, list):
                    _visit(value, depth + 1)
                elif isinstance(value, dict):
                    # Some APIs use data={results:[...]} or webPages={value:[...]}
                    for subkey in ('results', 'items', 'value', 'records', 'organic', 'pages', 'sources'):
                        if isinstance(value.get(subkey), list):
                            _visit(value.get(subkey), depth + 1)
                if len(rows) >= max_items:
                    break

        _visit(result, 0)
        return rows[:max_items]

    def web_query_groups_public(self, state: dict | None = None) -> list[dict]:
        if not isinstance(state, dict):
            return []
        rows = []
        for item in (state.get('web_query_groups') or []):
            if not isinstance(item, dict):
                continue
            queries = [re.sub(r'\s+', ' ', str(q or '').strip()) for q in (item.get('queries') or []) if str(q or '').strip()]
            if not queries:
                continue
            idx = int(item.get('index') or (len(rows) + 1))
            result_count = max(0, int(item.get('result_count') or 0))
            status = str(item.get('status') or '').strip().lower()
            state_text = 'done' if status in {'searched', 'completed', 'done'} else ('error' if status in {'error', 'failed'} else 'active')
            rows.append({
                'index': idx,
                'round': int(item.get('round') or 0),
                'status': status or 'searching',
                'state': state_text,
                'queries': queries,
                'query_count': len(queries),
                'result_count': result_count,
                'source_items': [dict(x) for x in (item.get('source_items') or []) if isinstance(x, dict)][:self.search_source_item_limit()],
                'started_at': float(item.get('started_at') or 0.0),
                'updated_at': float(item.get('updated_at') or 0.0),
                'ts': int(float(item.get('started_at') or item.get('updated_at') or time.time()) * 1000),
            })
        return rows

    def web_query_groups_meta(self, state: dict | None = None) -> dict:
        groups = self.web_query_groups_public(state)
        return {'web_query_groups': groups} if groups else {}

    def note_web_search_group(self, state: dict, round_idx: int, args: dict | None = None, result: dict | None = None, status: str = 'searching') -> dict:
        if not isinstance(state, dict):
            return {}
        groups = state.setdefault('web_query_groups', [])
        if not isinstance(groups, list):
            groups = []
            state['web_query_groups'] = groups
        try:
            round_no = int(round_idx or state.get('tool_rounds') or 0)
        except Exception:
            round_no = 0
        group = None
        for item in groups:
            if isinstance(item, dict) and int(item.get('round') or 0) == round_no:
                group = item
                break
        if group is None:
            group = {
                'index': len(groups) + 1,
                'round': round_no,
                'queries': [],
                'status': 'searching',
                'result_count': 0,
                'started_at': time.time(),
                'updated_at': time.time(),
            }
            groups.append(group)
        q = self.web_query_text(args, result)
        if q:
            queries = group.setdefault('queries', [])
            if q not in queries:
                queries.append(q)
            all_queries = state.setdefault('queries_used', [])
            if q not in all_queries:
                all_queries.append(q)
        try:
            if isinstance(result, dict):
                source_items = self.source_items_from_result(result, limit=self.search_source_item_limit())
                raw_results = result.get('results') if isinstance(result.get('results'), list) else []
                # Prefer the actual number of visible search result websites.
                # Some adapters return result rows under organic/data/items, so
                # len(result['results']) can be 0 even when search really found sites.
                group['result_count'] = max(0, int(group.get('result_count') or 0)) + max(len(raw_results), len(source_items))
                if source_items:
                    bucket = group.setdefault('source_items', [])
                    seen_urls = {str((x or {}).get('url') or '') for x in bucket if isinstance(x, dict)}
                    for src in source_items:
                        u = str(src.get('url') or '')
                        if u and u not in seen_urls:
                            bucket.append(src)
                            seen_urls.add(u)
                    group['source_items'] = bucket[:self.search_source_item_limit()]
        except Exception:
            pass
        group['status'] = str(status or group.get('status') or 'searching').strip().lower() or 'searching'
        group['updated_at'] = time.time()
        try:
            idx = int(group.get('index') or len(groups) or 1)
            state_text = 'done' if group['status'] in {'searched', 'completed', 'done'} else ('error' if group['status'] in {'error', 'failed'} else 'active')
            source_items = [dict(x) for x in (group.get('source_items') or []) if isinstance(x, dict)][:self.search_source_item_limit()]
            result_count = max(0, int(group.get('result_count') or 0))
            queries_public = list(group.get('queries') or [])
            # Emit the search row as soon as the search starts.  Waiting for a
            # query/result makes the activity panel look frozen during web work.
            self.append_progress_event(state, {
                'key': f'web|query_group|{int(group.get("round") or 0)}|{idx}',
                'stage': 'web_query_group',
                'panel_stage': 'search',
                'title': f'第 {idx} 次搜索中' if queries_public else '正在联网搜索',
                'queries': queries_public,
                'summary': queries_public[0] if queries_public else '',
                'querySummary': queries_public[0] if queries_public else '',
                'source_items': source_items,
                'result_count': result_count,
                'state': state_text,
                'percent': 100 if state_text == 'done' else 35,
                'ts': int(float(group.get('started_at') or time.time()) * 1000),
                'updated_at': int(float(group.get('updated_at') or time.time()) * 1000),
                'done_at': int(float(group.get('updated_at') or time.time()) * 1000) if state_text in {'done', 'warn', 'error'} else 0,
                'source': 'web_search',
                'round': int(group.get('round') or 0),
                'index': idx,
            })
        except Exception:
            pass
        return self.web_query_groups_meta(state)

    def note_web_fetch_event(self, state: dict, name: str = '', args: dict | None = None, result: dict | None = None, status: str = 'reading', call_id: str = '', round_idx: int = 0) -> dict:
        if not isinstance(state, dict):
            return {}
        tool_name = str(name or '').strip().lower()
        if tool_name not in {'fetch_url', 'fetch_urls', 'web_fetch'}:
            tool_name = 'fetch_url'
        args = args if isinstance(args, dict) else {}
        result = result if isinstance(result, dict) else {}
        state_text = 'done' if str(status or '').strip().lower() in {'read', 'done', 'completed', 'success', 'succeeded'} else ('error' if str(status or '').strip().lower() in {'error', 'failed', 'failure'} else 'active')
        try:
            source_items = self.source_items_from_result(result, limit=self.search_source_item_limit()) if result else []
        except Exception:
            source_items = []
        if not source_items:
            raw_urls = []
            if tool_name == 'fetch_urls':
                raw_urls = args.get('urls') if isinstance(args.get('urls'), list) else []
            else:
                raw_urls = [args.get('url') or args.get('href') or args.get('link') or '']
            source_items = []
            for u in raw_urls:
                u = str(u or '').strip()
                if not u:
                    continue
                try:
                    if not _is_public_visible_source_url(u):
                        continue
                    u = _normalize_visible_source_url(u)
                except Exception:
                    pass
                host = _host_of(u)
                source_items.append({'title': host or u, 'url': u[:500], 'host': host[:120]})
                if len(source_items) >= self.search_source_item_limit():
                    break
        first = source_items[0] if source_items else {}
        host = str((first or {}).get('host') or '').strip()
        title = str((first or {}).get('title') or '').strip()
        count = len(source_items)
        target = host or title or ('网页' if tool_name == 'fetch_url' else f'{max(1, count)} 个网页')
        prefix = '网页读取失败' if state_text == 'error' else ('已阅读网页' if state_text == 'done' else '正在阅读网页')
        row_title = f'{prefix}：{target}' if target else prefix
        op_key = str(call_id or args.get('_activity_call_id') or args.get('_tool_call_id') or args.get('tool_call_id') or '').strip()
        if not op_key:
            basis = '|'.join([tool_name, *(str((x or {}).get('url') or '') for x in source_items[:6])]).strip('|')
            if not basis:
                if tool_name == 'fetch_urls':
                    basis = '|'.join(str(x or '') for x in (args.get('urls') if isinstance(args.get('urls'), list) else [])[:6])
                else:
                    basis = str(args.get('url') or args.get('href') or args.get('link') or '')
            op_key = basis or f'{tool_name}|round|{round_idx or state.get("tool_rounds") or 0}'
        try:
            page_count = len(result.get('pages') or result.get('results') or []) if tool_name == 'fetch_urls' else (1 if (result or args) else 0)
        except Exception:
            page_count = count or 1
        self.append_progress_event(state, {
            'key': f'web|fetch|{tool_name}|{op_key}'[:700],
            'stage': 'web_fetch',
            'panel_stage': 'search',
            'tool': tool_name,
            'title': row_title,
            'detail': '',
            'source_items': source_items,
            'result_count': max(count, int(page_count or 0)),
            'source_count': max(count, int(page_count or 0)),
            'state': state_text,
            'percent': 100 if state_text == 'done' else (100 if state_text == 'error' else 45),
            'ts': int(time.time() * 1000),
            'updated_at': int(time.time() * 1000),
            'done_at': int(time.time() * 1000) if state_text in {'done', 'warn', 'error'} else 0,
            'source': 'web_fetch',
            'action_type': 'open_page',
            'actionType': 'open_page',
            'activity_op': 'open_page',
            'operation_key': op_key[:160],
            'round': int(round_idx or state.get('tool_rounds') or 0),
        })
        if state_text != 'active':
            self.focus_crop_activity(state, result, op_key=op_key, round_idx=round_idx)
        return self.progress_meta(state)

    def note_image_search_event(self, state: dict, args: dict | None = None, result: dict | None = None, status: str = 'searching', call_id: str = '', round_idx: int = 0) -> dict:
        if not isinstance(state, dict):
            return {}
        args = args if isinstance(args, dict) else {}
        result = result if isinstance(result, dict) else {}
        status_text = str(status or '').strip().lower()
        state_text = 'done' if status_text in {'searched', 'done', 'completed', 'success', 'succeeded'} else ('error' if status_text in {'error', 'failed', 'failure'} else 'active')
        query = self.web_query_text(args, result)
        try:
            source_items = self.source_items_from_result(result, limit=self.search_source_item_limit()) if result else []
        except Exception:
            source_items = []
        try:
            raw_count = len(result.get('results') or result.get('images') or [])
        except Exception:
            raw_count = 0
        result_count = max(raw_count, len(source_items))
        title_base = '图片搜索失败' if state_text == 'error' else ('已搜索图片' if state_text == 'done' else '正在搜索图片')
        row_title = f'{title_base}：{query[:80]}' if query else title_base
        op_key = str(call_id or args.get('_activity_call_id') or args.get('_tool_call_id') or args.get('tool_call_id') or '').strip()
        if not op_key:
            op_key = query or f'image_search|round|{round_idx or state.get("tool_rounds") or 0}'
        now_ms = int(time.time() * 1000)
        self.append_progress_event(state, {
            'key': f'image|search|{op_key}'[:700],
            'stage': 'image_search',
            'panel_stage': 'search',
            'tool': 'image_search',
            'title': row_title,
            'detail': '',
            'query': query,
            'search_query': query,
            'searchQuery': query,
            'queries': [query] if query else [],
            'summary': query[:240] if query else '',
            'querySummary': query[:240] if query else '',
            'query_summary': query[:240] if query else '',
            'source_items': source_items,
            'result_count': result_count,
            'source_count': result_count,
            'state': state_text,
            'percent': 100 if state_text in {'done', 'error'} else 35,
            'ts': now_ms,
            'updated_at': now_ms,
            'done_at': now_ms if state_text in {'done', 'warn', 'error'} else 0,
            'source': 'image_search',
            'action_type': 'image_search',
            'actionType': 'image_search',
            'activity_op': 'image_search',
            'operation_key': op_key[:160],
            'round': int(round_idx or state.get('tool_rounds') or 0),
        })
        return self.progress_meta(state)
