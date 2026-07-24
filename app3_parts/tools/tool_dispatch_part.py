# tool dispatch entry point for chat orchestration.


def _fetch_url_dedupe_key(value: str = '') -> str:
    """Return a stable identity for duplicate page mirrors.

    Keep genuinely different pages separate.  Only normalize transport noise,
    tracking parameters and a leading BCP-47-like locale segment, so search
    results such as /news/x and /zh-CN/news/x do not consume separate fetches.
    """
    raw = str(value or '').strip()
    if not raw:
        return ''
    try:
        parsed = urlparse(raw)
        scheme = str(parsed.scheme or 'https').lower()
        host = str(parsed.netloc or '').lower()
        path = re.sub(r'/+', '/', str(parsed.path or '/') or '/')
        path = re.sub(r'^/[a-z]{2}(?:-[a-z]{2})?(?=/)', '', path, flags=re.I) or '/'
        path = path.rstrip('/') or '/'
        query_items = []
        for key, val in urllib.parse.parse_qsl(str(parsed.query or ''), keep_blank_values=True):
            lowered = str(key or '').strip().lower()
            if lowered.startswith('utm_') or lowered in {'fbclid', 'gclid', 'msclkid'}:
                continue
            query_items.append((str(key or ''), str(val or '')))
        query = urllib.parse.urlencode(sorted(query_items))
        return urllib.parse.urlunparse((scheme, host, path, '', query, ''))
    except Exception:
        return raw.rstrip('/')


def _exec_tool(name: str, args: dict, user_geo: dict | None = None, messages: list | None = None, client_override=None, model: str | None = None) -> dict:
    """执行工具函数并返回可序列化 dict。"""
    args = args or {}
    mcp_detector = globals().get('_mcp_client_is_proxy_tool')
    if callable(mcp_detector) and mcp_detector(name):
        caller = globals().get('_mcp_client_call_proxy_tool')
        if not callable(caller):
            return {'ok': False, 'error': 'mcp_client_runtime_unavailable'}
        return caller(name, args, client_override=client_override)

    if name == "sandbox_list_files":
        return _sandbox_list_files_tool(args, messages=messages or [])

    if name == "sandbox_resolve_file_context":
        tool = globals().get('_file_context_resolver_tool')
        if callable(tool):
            return tool(args, messages=messages or [])
        return {'ok': False, 'error': 'file_context_resolver_unavailable'}

    if name == "sandbox_diff_files":
        tool = globals().get('_file_diff_files_tool')
        if callable(tool):
            return tool(args, messages=messages or [])
        return {'ok': False, 'error': 'file_diff_router_unavailable'}

    if name == "sandbox_read_file":
        return _sandbox_read_file_tool(args, messages=messages or [])

    if name == "sandbox_analyze_file_images":
        return _sandbox_analyze_file_images_tool(args, messages=messages or [], client_override=client_override, model=model)

    if name == "sandbox_write_file":
        return _sandbox_write_file_tool(args, messages=messages or [])

    if name == "sandbox_write_files":
        return _sandbox_write_files_tool(args, messages=messages or [])

    if name == "sandbox_create_office_file":
        return _sandbox_create_office_file_tool(args, messages=messages or [])

    if name == "sandbox_replace_text":
        return _sandbox_replace_text_tool(args, messages=messages or [])

    if name == "sandbox_import_files":
        return _sandbox_import_files_tool(args, messages=messages or [])

    if name == "sandbox_run":
        return _sandbox_run_tool(args, messages=messages or [])

    if name == "sandbox_publish_files":
        return _sandbox_publish_files_tool(args, messages=messages or [])

    if name == "search_knowledge_base":
        return _search_knowledge_base_tool(args)

    if name == "read_knowledge_base_document":
        return _read_knowledge_base_document_exec_tool(args)

    if name == "search_account_context":
        searcher = globals().get('_search_account_context_tool')
        if callable(searcher):
            return searcher(args, messages=messages or [])
        return {"ok": False, "error": "account_context_tool_unavailable"}

    if name == "read_account_context":
        reader = globals().get('_read_account_context_tool')
        if callable(reader):
            return reader(args, messages=messages or [])
        return {"ok": False, "error": "account_context_tool_unavailable"}

    if name == "get_weather":
        query = str(args.get("query") or "").strip()
        structured_place = str(args.get("_structured_weather_place") or args.get("place") or args.get("location") or args.get("location_name") or "").strip()
        return _build_weather_card(
            query,
            user_geo=user_geo,
            messages=messages,
            client_override=client_override,
            structured_place=structured_place,
        )

    if name == "get_location":
        query = str(args.get("query") or "").strip()
        request_precise = bool(args.get("request_precise") or args.get("request_browser_location") or args.get("precise"))
        return _build_location_tool_payload(query, user_geo=user_geo, request_precise=request_precise)

    if name == "web_search":
        q = (args.get("query") or "").strip()
        k = args.get("k")
        try:
            k = int(k) if k is not None else 5
        except Exception:
            k = 5
        k = max(1, min(k, 10))
        q2 = _normalize_search_query(q)
        results, err = web_search(q2, k=k)
        payload = {"ok": True, "query": q2, "results": results, "error": err}
        return _attach_evidence_ledger_event('web_search', payload, args)

    if name == "image_search":
        query = str(args.get("query") or args.get("subject") or "").strip()
        raw_queries = args.get("queries") or []
        if isinstance(raw_queries, str):
            raw_queries = [raw_queries]
        if not isinstance(raw_queries, list):
            raw_queries = []
        queries = [str(q or "").strip() for q in raw_queries if str(q or "").strip()]
        if query and query not in queries:
            queries.insert(0, query)
        if not queries:
            return {"ok": False, "error": "empty_image_query"}
        count = args.get("count", args.get("k", 5))
        try:
            count = int(count) if count is not None else 5
        except Exception:
            count = 5
        count = max(1, min(count, 10))
        subject = str(args.get("subject") or query or queries[0]).strip()
        candidate_k = max(count * 8, 24)
        rows = []
        try:
            app_logger.info('[IMAGE_SEARCH_TOOL_EXEC] query=%s queries=%s count=%s candidate_k=%s', query or queries[0], queries[:5], count, candidate_k)
        except Exception:
            pass
        search_fn = globals().get('_search_images_multi')
        try:
            app_logger.info(
                '[IMAGE_SEARCH_TOOL_PROVIDER] query=%s provider=%s fallback=%s search_fn=%s',
                query or queries[0],
                str(app_getenv('IMAGE_SEARCH_PROVIDER', '') or '').strip(),
                str(app_getenv('IMAGE_SEARCH_FALLBACK_PROVIDER', '') or '').strip(),
                'callable' if callable(search_fn) else type(search_fn).__name__,
            )
        except Exception:
            pass
        if not callable(search_fn):
            try:
                app_logger.warning('[IMAGE_SEARCH_TOOL_ERROR] query=%s error=image_search_provider_missing search_fn_not_callable', query or queries[0])
            except Exception:
                pass
            return {
                "ok": False,
                "error": "image_search_provider_missing",
                "query": query or queries[0],
                "queries": queries[:5],
                "provider": str(app_getenv('IMAGE_SEARCH_PROVIDER', '') or '').strip(),
                "fallback_provider": str(app_getenv('IMAGE_SEARCH_FALLBACK_PROVIDER', '') or '').strip(),
            }
        try:
            try:
                rows = search_fn(queries[:5], k=candidate_k, user_text=subject or query)
            except TypeError:
                rows = search_fn(queries[:5], k=candidate_k)
        except Exception as e:
            try:
                app_logger.warning('[IMAGE_SEARCH_TOOL_ERROR] query=%s error=%s:%s', query or queries[0], type(e).__name__, e)
            except Exception:
                pass
            return {"ok": False, "error": f"image_search_failed:{type(e).__name__}: {e}", "query": query, "queries": queries[:5]}
        rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        try:
            app_logger.info('[IMAGE_SEARCH_TOOL_RESULT] query=%s rows=%s', query or queries[0], len(rows or []))
        except Exception:
            pass
        images = []
        try:
            picker = globals().get('_select_verified_reply_images')
            if callable(picker):
                images = picker(rows, count, subject=subject or query) or []
        except Exception:
            images = []
        if not images:
            for row in rows[:count]:
                image_url = str(row.get('image_url') or row.get('thumbnail') or row.get('url') or '').strip()
                if not image_url:
                    continue
                source_url = str(row.get('source_url') or row.get('page_url') or row.get('source') or '').strip()
                images.append({
                    'url': image_url,
                    'image_url': image_url,
                    'raw_url': image_url,
                    'preview_url': image_url,
                    'source_type': 'image_search',
                    'title': str(row.get('title') or subject or query)[:160],
                    'source_url': source_url,
                    'source': str(row.get('domain') or row.get('source') or '')[:120],
                })
                if len(images) >= count:
                    break
        payload = None
        if images:
            payload = {
                'source': 'image_search',
                'text': '',
                'images': images[:count],
                'subject': subject or query,
                'count': len(images[:count]),
            }
        return {
            "ok": True,
            "query": query or queries[0],
            "queries": queries[:5],
            "subject": subject or query,
            "count": len(images[:count]),
            "results": rows[:max(count, 8)],
            "images": images[:count],
            "image_reply_payload": payload,
        }

    if name == "fetch_url":
        url = (args.get("url") or "").strip()
        max_chars = args.get("max_chars")
        try:
            max_chars = int(max_chars) if max_chars is not None else 12000
        except Exception:
            max_chars = 12000
        out = fetch_url_content_smart(url, query=str(args.get("query") or ""), max_chars=max(1000, min(max_chars, 40000)))
        out["title"] = (out.get("title") or "")[:300]
        out["text"] = truncate_text(out.get("text") or "", max_chars=min(max_chars, 40000))
        out["ok"] = True
        return _attach_evidence_ledger_event('fetch_url', out, args)

    if name == "fetch_urls":
        urls = args.get("urls") or []
        max_chars = args.get("max_chars")
        try:
            max_chars = int(max_chars) if max_chars is not None else 12000
        except Exception:
            max_chars = 12000
        if not isinstance(urls, list):
            urls = [str(urls)]
        requested_urls = [str(u).strip() for u in urls if str(u).strip()]
        urls = []
        seen_url_keys: set[str] = set()
        for candidate in requested_urls:
            dedupe_key = _fetch_url_dedupe_key(candidate)
            if not dedupe_key or dedupe_key in seen_url_keys:
                continue
            seen_url_keys.add(dedupe_key)
            urls.append(candidate)
            if len(urls) >= 5:
                break
        outs = []
        for u in urls:
            try:
                outs.append(fetch_url_content_smart(u, query=str(args.get("query") or ""), max_chars=max(1000, min(max_chars, 40000))))
            except Exception as e:
                outs.append({"url": u, "error": f"{type(e).__name__}: {e}"})
        payload = {
            "ok": True,
            "results": outs,
            "requested_count": len(requested_urls),
            "unique_count": len(urls),
            "duplicate_mirror_count": max(0, len(requested_urls) - len(urls)),
        }
        return _attach_evidence_ledger_event('fetch_urls', payload, args)

    return {"ok": False, "error": f"unknown_tool:{name}"}
