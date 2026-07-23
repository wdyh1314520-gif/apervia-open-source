# Split from app3_parts/chat/chat_streaming_part.py.
# Purpose: Responses-native web_search event tracking, source aggregation, and meta/progress frames.
# Loaded before chat_streaming_part.py, sharing the original global namespace.

import json
import re
import time
from urllib.parse import urlparse


class ResponsesNativeWebContext:
    def __init__(
        self,
        *,
        model: str = '',
        state: dict | None = None,
        native_web_state: dict | None = None,
        get_round_idx=None,
        sse=None,
        search_source_item_limit=None,
        push_sources=None,
        append_progress_event=None,
        progress_meta=None,
        is_public_visible_source_url=None,
        normalize_visible_source_url=None,
        host_of=None,
        planner_safe_text=None,
        sse_event_keys_for_log=None,
        logger=None,
    ):
        self.model = str(model or '')
        self.state = state if isinstance(state, dict) else {}
        self.native_web_state = native_web_state if isinstance(native_web_state, dict) else {}
        self.get_round_idx = get_round_idx if callable(get_round_idx) else (lambda: 0)
        self.sse = sse if callable(sse) else (lambda event, payload=None: '')
        self.search_source_item_limit = search_source_item_limit if callable(search_source_item_limit) else (lambda: 8)
        self.push_sources = push_sources if callable(push_sources) else (lambda state, name, result=None, target='': None)
        self.append_progress_event = append_progress_event if callable(append_progress_event) else (lambda state, item: None)
        self.progress_meta = progress_meta if callable(progress_meta) else (lambda state=None: {})
        self.is_public_visible_source_url = is_public_visible_source_url if callable(is_public_visible_source_url) else (lambda url: True)
        self.normalize_visible_source_url = normalize_visible_source_url if callable(normalize_visible_source_url) else (lambda url: url)
        self.host_of = host_of if callable(host_of) else (lambda url: (urlparse(str(url or '')).hostname or ''))
        self.planner_safe_text = planner_safe_text if callable(planner_safe_text) else (lambda text, max_len=260: str(text or '')[:max_len])
        self.sse_event_keys_for_log = sse_event_keys_for_log if callable(sse_event_keys_for_log) else (lambda payload: [])
        self.logger = logger or globals().get('app_logger')

    def _round_idx(self) -> int:
        try:
            return int(self.get_round_idx() or 0)
        except Exception:
            return 0

    def _limit(self) -> int:
        try:
            return max(1, int(self.search_source_item_limit() or 8))
        except Exception:
            return 8

    def _responses_native_web_add_query(self, query: str = '') -> int:
        q = re.sub(r'\s+', ' ', str(query or '').strip())[:400]
        if not q:
            return 0
        existing = [str(x or '').strip() for x in (self.state.setdefault('queries_used', []) or []) if str(x or '').strip()]
        if q in existing:
            return 0
        self.state.setdefault('queries_used', []).append(q)
        return 1

    def _responses_native_web_add_source(self, url: str = '', title: str = '', snippet: str = '', *, target: str = 'searched') -> int:
        target_kind = 'sources' if str(target or '').strip().lower() in {'source', 'sources', 'citation', 'citations', 'read', 'clicked'} else 'searched'
        bucket_key = 'sources' if target_kind == 'sources' else 'searched_sources'
        before = len(self.state.get(bucket_key) or [])
        self.push_sources(self.state, 'web_search', {
            'results': [{
                'url': str(url or '').strip(),
                'title': str(title or '').strip(),
                'snippet': str(snippet or '').strip(),
            }]
        }, target=target_kind)
        after = len(self.state.get(bucket_key) or [])
        if after > before:
            try:
                self.state['web_results'] = max(int(self.state.get('web_results') or 0), len(self.state.get('searched_sources') or []), after)
            except Exception:
                self.state['web_results'] = max(len(self.state.get('searched_sources') or []), after)
            return after - before
        return 0

    def _responses_native_web_compact_text(self, value, limit: int = 220) -> str:
        raw = re.sub(r'\s+', ' ', str(value or '').strip())
        return raw[:max(1, int(limit or 220))]

    def _responses_native_web_call_status(self, event_type: str = '', payload: dict | None = None) -> str:
        event_low = str(event_type or '').strip().lower()
        raw_status = ''
        if isinstance(payload, dict):
            raw_status = str(payload.get('status') or payload.get('state') or '').strip().lower()
        if raw_status in {'completed', 'complete', 'done', 'success', 'succeeded'} or event_low.endswith('.completed'):
            return 'completed'
        if raw_status in {'failed', 'error', 'cancelled', 'canceled'} or event_low.endswith('.failed') or event_low.endswith('.error'):
            return 'error'
        if raw_status in {'searching', 'running'} or event_low.endswith('.searching'):
            return 'searching'
        if raw_status in {'in_progress', 'in-progress', 'queued', 'pending'} or event_low.endswith('.in_progress'):
            return 'in_progress'
        if 'web_search_call' in event_low:
            return 'in_progress'
        return raw_status or ''

    def _responses_native_web_public_status(self, status: str = '') -> str:
        key = str(status or '').strip().lower()
        return {
            'completed': 'done',
            'complete': 'done',
            'done': 'done',
            'success': 'done',
            'succeeded': 'done',
            'error': 'error',
            'failed': 'error',
            'cancelled': 'warn',
            'canceled': 'warn',
            'searching': 'active',
            'running': 'active',
            'in_progress': 'active',
            'pending': 'active',
            'queued': 'active',
        }.get(key, 'active' if key else '')

    def _responses_native_web_extract_queries(self, node, out: list[str] | None = None, depth: int = 0) -> list[str]:
        out = out if isinstance(out, list) else []
        if depth > 6 or node is None or len(out) >= 20:
            return out

        def push(value) -> None:
            q = self._responses_native_web_compact_text(value, 300)
            if q and q not in out:
                out.append(q)

        if isinstance(node, str):
            push(node)
        elif isinstance(node, dict):
            for key in ('query', 'search_query', 'search_terms', 'text'):
                if key in node:
                    push(node.get(key))
            for key in ('queries', 'search_queries'):
                rows = node.get(key)
                if isinstance(rows, (list, tuple)):
                    for row in rows[:12]:
                        if isinstance(row, dict):
                            push(row.get('query') or row.get('search_query') or row.get('text') or '')
                        else:
                            push(row)
                elif isinstance(rows, str):
                    push(rows)
            for key in ('action', 'request', 'arguments', 'input'):
                if isinstance(node.get(key), (dict, list, tuple)):
                    self._responses_native_web_extract_queries(node.get(key), out, depth + 1)
        elif isinstance(node, (list, tuple)):
            for row in node[:24]:
                self._responses_native_web_extract_queries(row, out, depth + 1)
        return out

    def _responses_native_web_action_type(self, node, depth: int = 0) -> str:
        if depth > 5 or node is None:
            return ''
        aliases = {
            'search': 'search',
            'web_search': 'search',
            'web_search_call': 'search',
            'open_page': 'open_page',
            'open-page': 'open_page',
            'open page': 'open_page',
            'page_open': 'open_page',
            'read_page': 'open_page',
            'read page': 'open_page',
            'find_in_page': 'find_in_page',
            'find-in-page': 'find_in_page',
            'find in page': 'find_in_page',
            'page_find': 'find_in_page',
        }

        def norm(value) -> str:
            raw = str(value or '').strip().lower().replace('-', '_').replace(' ', '_')
            if raw in aliases:
                return aliases[raw]
            if raw.endswith('.search') or raw.endswith('_search'):
                return 'search'
            if 'open_page' in raw or 'read_page' in raw:
                return 'open_page'
            if 'find_in_page' in raw:
                return 'find_in_page'
            return ''

        if isinstance(node, dict):
            for key in ('action_type', 'actionType', 'type', 'name', 'kind'):
                value = norm(node.get(key))
                if value:
                    return value
            action = node.get('action')
            if isinstance(action, (dict, list, tuple)):
                value = self._responses_native_web_action_type(action, depth + 1)
                if value:
                    return value
            for key in ('request', 'arguments', 'input'):
                value = node.get(key)
                if isinstance(value, (dict, list, tuple)):
                    found = self._responses_native_web_action_type(value, depth + 1)
                    if found:
                        return found
        elif isinstance(node, (list, tuple)):
            for row in node[:24]:
                found = self._responses_native_web_action_type(row, depth + 1)
                if found:
                    return found
        return ''

    def _responses_native_web_source_like_count(self, node, depth: int = 0) -> int:
        if depth > 5 or node is None:
            return 0
        count = 0
        if isinstance(node, dict):
            for key in ('result_count', 'results_count', 'source_count', 'sources_count', 'item_count', 'items_count'):
                try:
                    value = int(node.get(key) or 0)
                except Exception:
                    value = 0
                if value > count:
                    count = value
            for key in ('sources', 'results', 'items', 'search_results'):
                rows = node.get(key)
                if isinstance(rows, (list, tuple)):
                    count = max(count, len([x for x in rows if isinstance(x, (dict, str))]))
            for key in ('action', 'response', 'result', 'output'):
                if isinstance(node.get(key), (dict, list, tuple)):
                    count = max(count, self._responses_native_web_source_like_count(node.get(key), depth + 1))
        elif isinstance(node, (list, tuple)):
            count = max(count, len([x for x in node if isinstance(x, (dict, str))]))
            for row in node[:24]:
                if isinstance(row, (dict, list, tuple)):
                    count = max(count, self._responses_native_web_source_like_count(row, depth + 1))
        return int(count or 0)

    def _responses_native_web_call_public_rows(self) -> list[dict]:
        rows: list[dict] = []
        calls = self.native_web_state.get('calls') if isinstance(self.native_web_state.get('calls'), dict) else {}
        order = [str(x or '').strip() for x in (self.native_web_state.get('call_order') or []) if str(x or '').strip()]
        for public_idx, call_id in enumerate(order, 1):
            call = calls.get(call_id) if isinstance(calls, dict) else None
            if not isinstance(call, dict):
                continue
            queries = [str(q or '').strip() for q in (call.get('queries') or []) if str(q or '').strip()][:12]
            status = str(call.get('status') or '').strip().lower()
            source_count = max(0, int(call.get('source_count') or 0))
            result_count = max(0, int(call.get('result_count') or 0))
            rows.append({
                'id': str(call.get('id') or call_id),
                'short_id': str(call.get('short_id') or call_id)[-10:],
                'index': int(public_idx),
                'status': status,
                'state': self._responses_native_web_public_status(status),
                'event': str(call.get('event') or '').strip()[:120],
                'action_type': str(call.get('action_type') or '').strip().lower()[:40],
                'round': int(call.get('round') or 0),
                'output_index': int(call.get('output_index') or 0),
                'queries': queries,
                'query_count': len(queries),
                'source_count': source_count,
                'result_count': result_count,
                'source_items': [dict(x) for x in (call.get('source_items') or []) if isinstance(x, dict)][:self._limit()],
                'started_at': float(call.get('started_at') or 0.0),
                'updated_at': float(call.get('updated_at') or 0.0),
                'done_at': float(call.get('done_at') or 0.0),
            })
        return rows[:12]

    def _responses_native_web_sync_progress_events(self, native_web_calls: list[dict] | None = None) -> None:
        rows = native_web_calls if isinstance(native_web_calls, list) else self._responses_native_web_call_public_rows()
        for idx, call in enumerate(rows[:12], 1):
            if not isinstance(call, dict):
                continue
            state_text = str(call.get('state') or '').strip().lower()
            if state_text not in {'active', 'done', 'warn', 'error'}:
                state_text = 'done' if str(call.get('status') or '').strip().lower() in {'completed', 'done'} else 'active'
            try:
                ts = int(float(call.get('started_at') or call.get('updated_at') or time.time()) * 1000)
            except Exception:
                ts = int(time.time() * 1000)
            try:
                updated_ts = int(float(call.get('updated_at') or call.get('done_at') or time.time()) * 1000)
            except Exception:
                updated_ts = int(time.time() * 1000)
            queries_public = [str(q or '').strip() for q in (call.get('queries') or []) if str(q or '').strip()]
            source_items = [dict(x) for x in (call.get('source_items') or []) if isinstance(x, dict)][:self._limit()]
            result_count = max(0, int(call.get('result_count') or 0))
            action_type = str(call.get('action_type') or '').strip().lower()

            def first_host(items: list[dict]) -> str:
                for src in items or []:
                    if not isinstance(src, dict):
                        continue
                    host = str(src.get('host') or src.get('domain') or '').strip()
                    if host:
                        return host[:120]
                    url = str(src.get('url') or src.get('link') or src.get('href') or '').strip()
                    if url:
                        try:
                            return (urlparse(url).hostname or url)[:120]
                        except Exception:
                            return url[:120]
                return ''

            host = first_host(source_items)
            if queries_public:
                title = f'第 {idx} 次搜索中'
            elif action_type == 'find_in_page':
                prefix = '已页内查找' if state_text == 'done' else '正在页内查找'
                title = f'{prefix}：{host}' if host else prefix
            elif source_items or result_count or action_type == 'open_page':
                prefix = '已读取' if state_text == 'done' else '正在读取'
                title = f'{prefix}：{host}' if host else f'{prefix}网页'
            else:
                title = '正在联网搜索'
            self.append_progress_event(self.state, {
                'key': f'web|native_query_group|{str(call.get("id") or call.get("short_id") or idx)}',
                'stage': 'web_query_group',
                'panel_stage': 'search',
                'title': title,
                'queries': queries_public,
                'summary': queries_public[0] if queries_public else '',
                'querySummary': queries_public[0] if queries_public else '',
                'source_items': source_items,
                'result_count': result_count,
                'state': state_text,
                'percent': 100 if state_text == 'done' else 35,
                'ts': ts,
                'updated_at': updated_ts,
                'done_at': updated_ts if state_text in {'done', 'warn', 'error'} else 0,
                'source': 'native_web_call',
                'action_type': action_type,
                'round': int(call.get('round') or 0),
                'index': idx,
            })

    def _source_items_from_node(self, node, limit: int = 200) -> list[dict]:
        rows: list[dict] = []
        seen_urls: set[str] = set()

        def push(src: dict | None) -> None:
            if not isinstance(src, dict):
                return
            citation = src.get('url_citation') if isinstance(src.get('url_citation'), dict) else None
            row = citation or src
            url = str(row.get('url') or row.get('uri') or row.get('link') or row.get('href') or '').strip()
            if not url:
                return
            try:
                if not self.is_public_visible_source_url(url):
                    return
                url = self.normalize_visible_source_url(url)
            except Exception:
                pass
            if not url or url in seen_urls:
                return
            seen_urls.add(url)
            rows.append({
                'title': str(row.get('title') or row.get('name') or row.get('site_name') or row.get('source') or self.host_of(url) or url)[:200],
                'url': url[:500],
                'host': self.host_of(url)[:120],
                'snippet': self.planner_safe_text(str(row.get('snippet') or row.get('summary') or row.get('text') or row.get('content') or ''), max_len=260),
            })

        def walk(node2, depth: int = 0) -> None:
            if len(rows) >= limit or depth > 6 or node2 is None:
                return
            if isinstance(node2, dict):
                if node2.get('url') or node2.get('uri') or node2.get('link') or node2.get('href') or isinstance(node2.get('url_citation'), dict):
                    push(node2)
                for key in ('sources', 'results', 'items', 'annotations'):
                    val = node2.get(key)
                    if isinstance(val, (list, tuple, dict)):
                        walk(val, depth + 1)
            elif isinstance(node2, (list, tuple)):
                for row in node2[:max(1, min(int(limit or 200), 500))]:
                    walk(row, depth + 1)
                    if len(rows) >= limit:
                        break

        walk(node)
        return rows[:limit]

    def _responses_native_web_record_call_event(self, payload, event_type: str = '', info: dict | None = None) -> int:
        if not isinstance(payload, dict):
            return 0
        outer_event_low = str(event_type or '').strip().lower()
        payload_event_low = str(payload.get('type') or payload.get('event') or '').strip().lower()
        item = payload.get('item') if isinstance(payload.get('item'), dict) else (payload.get('output_item') if isinstance(payload.get('output_item'), dict) else None)
        item_type = str((item or {}).get('type') or '').strip().lower() if isinstance(item, dict) else ''
        is_web_call = (
            'web_search_call' in outer_event_low
            or 'web_search_call' in payload_event_low
            or 'web_search_call' in item_type
        )
        if not is_web_call:
            return 0
        event_low = outer_event_low if 'web_search_call' in outer_event_low else (payload_event_low or item_type or outer_event_low)
        raw_call_id = str(payload.get('item_id') or payload.get('call_id') or payload.get('id') or '').strip()
        if not raw_call_id and isinstance(item, dict):
            raw_call_id = str(item.get('id') or item.get('call_id') or '').strip()
        if not raw_call_id:
            try:
                fallback_output_index = int(payload.get('output_index') or ((item or {}).get('output_index') if isinstance(item, dict) else 0) or 0)
            except Exception:
                fallback_output_index = 0
            if fallback_output_index:
                raw_call_id = 'native_web_call_output_' + str(fallback_output_index)
            else:
                round_key = str(self._round_idx())
                fallback_ids = self.native_web_state.setdefault('_fallback_call_ids', {})
                if not isinstance(fallback_ids, dict):
                    fallback_ids = {}
                    self.native_web_state['_fallback_call_ids'] = fallback_ids
                raw_call_id = fallback_ids.get(round_key) or ('native_web_call_round_' + round_key)
                fallback_ids[round_key] = raw_call_id
        calls = self.native_web_state.setdefault('calls', {})
        if not isinstance(calls, dict):
            calls = {}
            self.native_web_state['calls'] = calls
        order = self.native_web_state.setdefault('call_order', [])
        if not isinstance(order, list):
            order = []
            self.native_web_state['call_order'] = order
        if raw_call_id not in calls:
            calls[raw_call_id] = {
                'id': raw_call_id,
                'short_id': raw_call_id[-10:],
                'queries': [],
                'status': '',
                'event': '',
                'round': self._round_idx(),
                'output_index': 0,
                'source_count': 0,
                'result_count': 0,
                'source_items': [],
                'started_at': time.time(),
                'updated_at': time.time(),
                'done_at': 0.0,
                '_signature': '',
            }
            order.append(raw_call_id)
        call = calls[raw_call_id]
        status = self._responses_native_web_call_status(event_low, payload)
        action = payload.get('action') or ((item or {}).get('action') if isinstance(item, dict) else None)
        action_type = self._responses_native_web_action_type(action if isinstance(action, (dict, list, tuple)) else payload)
        queries = self._responses_native_web_extract_queries(payload, [])[:12]
        if isinstance(action, (dict, list, tuple)):
            queries = self._responses_native_web_extract_queries(action, queries)[:12]
        if action_type in {'open_page', 'find_in_page'}:
            queries = []
        native_source_items = self._source_items_from_node(action if isinstance(action, (dict, list, tuple)) else payload, limit=self._limit())
        if native_source_items:
            bucket = call.setdefault('source_items', [])
            seen_urls = {str((x or {}).get('url') or '') for x in bucket if isinstance(x, dict)}
            for src in native_source_items:
                url = str(src.get('url') or '')
                if url and url not in seen_urls:
                    bucket.append(src)
                    seen_urls.add(url)
            call['source_items'] = bucket[:self._limit()]
        for query in queries:
            query = self._responses_native_web_compact_text(query, 300)
            if query and query not in call.setdefault('queries', []):
                call.setdefault('queries', []).append(query)
                self._responses_native_web_add_query(query)
        source_like_count = self._responses_native_web_source_like_count(payload)
        try:
            output_index = int(payload.get('output_index') or ((item or {}).get('output_index') if isinstance(item, dict) else 0) or 0)
        except Exception:
            output_index = 0
        if output_index:
            call['output_index'] = output_index
        visible_source_count = len([x for x in (call.get('source_items') or []) if isinstance(x, dict) and str(x.get('url') or '').strip()])
        if visible_source_count:
            call['source_count'] = max(int(call.get('source_count') or 0), int(visible_source_count))
            call['result_count'] = max(int(call.get('result_count') or 0), int(visible_source_count))
        elif source_like_count:
            call['raw_source_like_count'] = max(int(call.get('raw_source_like_count') or 0), int(source_like_count))
        if status:
            call['status'] = status
        if action_type:
            call['action_type'] = action_type
        call['event'] = event_low[:120]
        call['round'] = int(self._round_idx() or call.get('round') or 0)
        call['updated_at'] = time.time()
        if status in {'completed', 'error'}:
            call['done_at'] = call['updated_at']
        signature = json.dumps({
            'event': call.get('event'),
            'status': call.get('status'),
            'action_type': call.get('action_type') or '',
            'queries': call.get('queries') or [],
            'source_count': int(call.get('source_count') or 0),
            'result_count': int(call.get('result_count') or 0),
            'source_items': [str((x or {}).get('url') or '') for x in (call.get('source_items') or []) if isinstance(x, dict)][:self._limit()],
        }, ensure_ascii=False, sort_keys=True)
        if signature == str(call.get('_signature') or ''):
            return 0
        call['_signature'] = signature
        if isinstance(info, dict):
            info['added_web_calls'] = int(info.get('added_web_calls') or 0) + 1
        self._responses_native_web_mark_confirmed(info)
        try:
            self.logger.info(
                '[RESPONSES_NATIVE_WEB_CALL_TRACE] model=%s round=%s call_id=%s status=%s event=%s query_count=%s queries=%s result_count=%s source_count=%s keys=%s',
                self.model,
                self._round_idx(),
                raw_call_id[-16:],
                str(call.get('status') or ''),
                event_low[:120],
                len(call.get('queries') or []),
                (call.get('queries') or [])[:6],
                int(call.get('result_count') or 0),
                int(call.get('source_count') or 0),
                self.sse_event_keys_for_log(payload),
            )
        except Exception:
            pass
        return 1

    def _responses_native_web_note_seen(self, info: dict | None = None) -> None:
        self.native_web_state['observed'] = True
        if isinstance(info, dict):
            info['seen'] = True

    def _responses_native_web_mark_confirmed(self, info: dict | None = None) -> None:
        self.native_web_state['seen'] = True
        self.native_web_state['confirmed'] = True
        self.state['native_web_used'] = True
        if isinstance(info, dict):
            info['seen'] = True
            info['confirmed'] = True
        if not bool(self.native_web_state.get('counted')):
            self.native_web_state['counted'] = True
            counts = self.state.setdefault('tool_counts', {})
            counts['web_search_native'] = int(counts.get('web_search_native') or 0) + 1

    def _responses_native_collect_web_payload(self, payload, event_type: str = '') -> dict:
        info = {'seen': False, 'added_queries': 0, 'added_sources': 0, 'added_web_calls': 0}
        if not isinstance(payload, dict):
            return info
        event_low = str(event_type or '').strip().lower()
        if 'web_search' in event_low:
            self._responses_native_web_note_seen(info)
            self._responses_native_web_record_call_event(payload, event_type, info)

        def add_query(value) -> None:
            before = int(info.get('added_queries') or 0)
            if isinstance(value, str):
                info['added_queries'] += self._responses_native_web_add_query(value)
            elif isinstance(value, (list, tuple)):
                for row in value[:12]:
                    add_query(row)
            elif isinstance(value, dict):
                add_query(value.get('query') or value.get('search_query') or value.get('text') or '')
            if int(info.get('added_queries') or 0) > before:
                self._responses_native_web_mark_confirmed(info)

        def add_source_obj(node, *, target: str = 'searched') -> None:
            if not isinstance(node, dict):
                return
            citation = node.get('url_citation') if isinstance(node.get('url_citation'), dict) else None
            if citation:
                target = 'sources'
            src = citation or node
            url = str(src.get('url') or src.get('uri') or src.get('link') or src.get('href') or '').strip()
            if not url:
                return
            title = str(src.get('title') or src.get('name') or src.get('site_name') or src.get('source') or '').strip()
            snippet = str(src.get('snippet') or src.get('summary') or src.get('text') or src.get('content') or '').strip()
            added = self._responses_native_web_add_source(url, title, snippet, target=target)
            info['added_sources'] += added
            if added:
                self._responses_native_web_mark_confirmed(info)

        def scan_annotations(value) -> None:
            if isinstance(value, dict):
                typ = str(value.get('type') or '').strip().lower()
                if typ == 'url_citation' or isinstance(value.get('url_citation'), dict) or value.get('url'):
                    self._responses_native_web_note_seen(info)
                    add_source_obj(value, target='sources')
                for child in value.values():
                    if isinstance(child, (dict, list, tuple)):
                        scan_annotations(child)
            elif isinstance(value, (list, tuple)):
                for child in value[:80]:
                    scan_annotations(child)

        def scan_action(action) -> None:
            if isinstance(action, dict):
                self._responses_native_web_note_seen(info)
                add_query(action.get('query') or action.get('search_query') or action.get('search_terms') or '')
                add_query(action.get('queries') or action.get('search_queries') or [])
                for key in ('sources', 'results', 'items'):
                    rows = action.get(key)
                    if isinstance(rows, (list, tuple)):
                        for row in rows[:self._limit()]:
                            add_source_obj(row, target='searched')
            elif isinstance(action, (list, tuple)):
                for row in action[:self._limit()]:
                    scan_action(row)

        def walk(node, depth: int = 0) -> None:
            if depth > 8 or node is None:
                return
            if isinstance(node, dict):
                typ = str(node.get('type') or node.get('event') or '').strip().lower()
                if 'web_search_call' in typ or typ in {'web_search', 'web_search_preview'}:
                    self._responses_native_web_note_seen(info)
                    if 'web_search_call' in typ:
                        self._responses_native_web_record_call_event(node, typ or event_type, info)
                    scan_action(node.get('action'))
                if 'web_search_call' in typ:
                    scan_action(node.get('action'))
                if 'annotations' in node:
                    scan_annotations(node.get('annotations'))
                if 'sources' in node and ('web_search' in typ or 'response' in event_low or 'completed' in event_low):
                    rows = node.get('sources')
                    if isinstance(rows, (list, tuple)):
                        self._responses_native_web_note_seen(info)
                        root_target = 'sources' if ('response' in event_low or 'completed' in event_low) and 'web_search' not in typ else 'searched'
                        for row in rows[:self._limit()]:
                            add_source_obj(row, target=root_target)
                if typ == 'url_citation' or isinstance(node.get('url_citation'), dict):
                    self._responses_native_web_note_seen(info)
                    add_source_obj(node, target='sources')
                for key in ('query', 'queries', 'search_query', 'search_queries'):
                    if key in node and ('web_search' in typ or 'web_search' in event_low):
                        add_query(node.get(key))
                for value in node.values():
                    if isinstance(value, (dict, list, tuple)):
                        walk(value, depth + 1)
            elif isinstance(node, (list, tuple)):
                for row in node[:120]:
                    walk(row, depth + 1)

        walk(payload, 0)
        if info.get('added_sources'):
            try:
                self.state['web_results'] = max(int(self.state.get('web_results') or 0), len(self.state.get('searched_sources') or []), len(self.state.get('sources') or []))
            except Exception:
                self.state['web_results'] = max(len(self.state.get('searched_sources') or []), len(self.state.get('sources') or []))
        return info

    def _responses_native_web_meta_frame(self, stage: str = 'native_web_search') -> str | None:
        queries = [str(q or '').strip() for q in (self.state.get('queries_used') or []) if str(q or '').strip()]
        sources = [dict(x) for x in (self.state.get('sources') or []) if isinstance(x, dict)]
        search_results = [dict(x) for x in (self.state.get('searched_sources') or []) if isinstance(x, dict)]
        native_web_calls = self._responses_native_web_call_public_rows()
        if not (bool(self.native_web_state.get('confirmed')) or bool(self.state.get('native_web_used')) or queries or sources or search_results or native_web_calls):
            return None
        sig = json.dumps({
            'stage': str(stage or ''),
            'queries': queries[-8:],
            'sources': [str(x.get('url') or '') for x in sources[-8:]],
            'search_results': [str(x.get('url') or '') for x in search_results[-8:]],
            'native_web_calls': [
                {
                    'id': str(x.get('id') or ''),
                    'status': str(x.get('status') or ''),
                    'action_type': str(x.get('action_type') or ''),
                    'queries': x.get('queries') or [],
                    'result_count': int(x.get('result_count') or 0),
                    'source_count': int(x.get('source_count') or 0),
                    'source_items': [str((src or {}).get('url') or '') for src in (x.get('source_items') or []) if isinstance(src, dict)][:8],
                }
                for x in native_web_calls[-8:]
            ],
        }, ensure_ascii=False, sort_keys=True)
        if sig == str(self.native_web_state.get('meta_signature') or ''):
            return None
        self.native_web_state['meta_signature'] = sig
        native_web_result_count = max(
            int(self.state.get('web_results') or len(search_results) or 0),
            len(search_results),
            max([int((x or {}).get('result_count') or (x or {}).get('source_count') or 0) for x in native_web_calls] or [0]),
        )
        try:
            self._responses_native_web_sync_progress_events(native_web_calls)
        except Exception:
            pass
        return self.sse('meta', {
            'model': self.model,
            'mode': 'responses_native_tools',
            'route_mode': 'responses_native_agent',
            'use_web_research': True,
            'native_web_search': True,
            'web_hit': True,
            'search_stage': str(stage or 'native_web_search'),
            'result_count': native_web_result_count,
            'page_count': int(self.state.get('pages') or 0),
            'queries_used': queries,
            'source_count': len(sources),
            'native_web_call_count': len(native_web_calls),
            'native_web_calls': native_web_calls,
            'sources': sources,
            'search_results': search_results,
            'searched_results': search_results,
            **self.progress_meta(self.state),
        })
