# legacy do_chat_stream route adapter and compatibility helpers.

# ==============================
# FAST MODE (Snippet Only)
# ==============================
# This override disables heavy page crawling and deep fetch logic.
# Search will use only SearxNG snippets (title + snippet).
# This dramatically improves response speed.

DEEP_FETCH = False

print("FAST MODE ENABLED: snippet-only search active")


# ==============================
# TRUE STREAMING PATCH (SSE)
# ==============================
# - Runs tool-calls (web_search / fetch_url / etc.) in background rounds (non-stream).
# - Then performs the FINAL assistant answer with stream=True and forwards deltas to SSE,
#   so the frontend output is smooth (not "fake chunking").
#
# Notes:
# - 文件交付现在通过 sandbox_* /mnt/data 链路统一处理，不再依赖 FILE_MODE。
# - This patch overrides do_chat_stream() only; routes remain unchanged.

def _is_file_mode_messages(msgs: list) -> bool:
    # Legacy noop: file delivery is now decided by sandbox_* tool calls.
    return False

def _delta_text_from_chunk(chunk) -> str:
    """Best-effort extraction of streamed delta text for OpenAI-compatible responses."""
    try:
        choices = getattr(chunk, "choices", None)
        if choices:
            c0 = choices[0]
            delta = getattr(c0, "delta", None)
            if delta is not None:
                txt = getattr(delta, "content", None)
                if txt:
                    return txt
            # some compat servers may put in message.content
            msg = getattr(c0, "message", None)
            if msg is not None:
                txt = getattr(msg, "content", None)
                if txt:
                    return txt
    except Exception:
        pass
    return ""


def _looks_complex_task(messages: list) -> bool:
    try:
        last = ""
        for m in reversed(messages or []):
            if isinstance(m, dict) and m.get("role") == "user":
                last = str(m.get("content") or "")
                break
        t = last.lower()
        keys = [
            "对比","比较","详细分析","多步","一步一步",
            "抓取","爬取","交叉验证","多个来源","深度","完整报告",
            "compare","analyze","step by step","cross verify"
        ]
        if any(k.lower() in t for k in keys):
            return True
        # 单轮工具判断也应该覆盖“明显需要实时/联网”的问题，
        # 例如天气、下雨多久转晴、最新消息、价格、汇率等。
        if _looks_time_sensitive(last) or _looks_explicit_web_request(last):
            return True
        return False
    except Exception:
        return False


def do_chat_stream(model: str, messages: list, show_steps: bool, label: str, user_geo: dict | None = None, extra_meta: dict | None = None):
    """Unified SSE chat stream.

    Fast mode streams directly for simple requests.
    Agent mode performs tool rounds only for clearly complex tasks.
    File generation, artifact saving, and extra_meta are preserved here instead of
    being layered as late patch functions.
    """

    def _merge_meta(base: dict | None = None) -> dict:
        meta = dict(base or {})
        if isinstance(extra_meta, dict):
            meta.update(extra_meta)
        return meta

    def _chunk_text(chunk) -> str:
        txt = _delta_text_from_chunk(chunk)
        if txt:
            return txt
        try:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                return ""
            c0 = choices[0]
            delta = getattr(c0, "delta", None)
            if delta is not None:
                content = getattr(delta, "content", None)
                if isinstance(content, str):
                    return content
            msg = getattr(c0, "message", None)
            if msg is not None:
                content = getattr(msg, "content", None)
                if isinstance(content, str):
                    return content
            content = getattr(c0, "text", None)
            if isinstance(content, str):
                return content
        except Exception:
            pass
        return ""

    def _emit_artifact_meta(full_text: str, base_meta: dict):
        meta = _merge_meta(base_meta)
        try:
            parsed = _try_parse_artifact_json(full_text)
        except Exception:
            parsed = None

        if parsed:
            _, artifacts = parsed
            publisher = globals().get('_sandbox_stage_and_publish_artifacts')
            publish_result = publisher(artifacts, messages or [], source='legacy_chat_stream_artifact_json') if callable(publisher) else {
                'ok': False,
                'error': 'sandbox_artifact_bridge_unavailable',
                'files': [],
            }
            saved = [dict(x) for x in (publish_result.get('files') or []) if isinstance(x, dict)]
            if saved:
                meta["artifacts"] = saved
            return meta

        return meta

    @stream_with_context
    def gen():
        yield ": ping\n\n"
        try:
            prefetch_decision = _decide_tool_prefetch_once(model, messages or [], _latest_user_text_from_messages(messages or []), client_override=client_override)
            allow_weather_tool = str((prefetch_decision or {}).get("weather_action") or "none") == "call_weather"
            cur_messages = _inject_runtime_tool_context(list(messages or []), user_geo=user_geo, allow_weather_tool=allow_weather_tool, route_signals=prefetch_decision)
            file_prompt = _build_file_delivery_soft_prompt(messages or [])
            if file_prompt:
                cur_messages.append({"role": "system", "_kind": "file_delivery_soft_prompt", "content": file_prompt})
            cur_messages = _sanitize_messages_for_model(cur_messages)
            compressor = globals().get('_compress_messages_for_chat_endpoint')
            if callable(compressor):
                cur_messages = compressor(cur_messages, phase='chat_stream_tool_runtime')

            if show_steps:
                yield sse("status", {"text": f"{label} 当前模型：{model}（工具自决模式）"})

            tools = _tools_schema(allow_weather_tool=allow_weather_tool)
            tool_counts = {"web_search": 0, "fetch_url": 0, "fetch_urls": 0}
            rounds = 0
            direct_answer = ""
            activity_state = {"activity_events": []}

            def _pullback_emit_activity(item: dict | None = None) -> str:
                upsert = globals().get('_activity_event_upsert_state')
                if not callable(upsert) or not isinstance(item, dict):
                    return ""
                try:
                    row = upsert(activity_state, item) or {}
                except Exception:
                    row = {}
                return sse("activity", {"activity_event": row}) if row else ""

            def _pullback_source_items_from_fetch(name: str = "", args: dict | None = None, result: dict | None = None) -> list[dict]:
                args = args if isinstance(args, dict) else {}
                result = result if isinstance(result, dict) else {}
                rows = []
                seen = set()

                def _push(url: str = "", title: str = "") -> None:
                    u = str(url or "").strip()
                    if not u or u in seen:
                        return
                    seen.add(u)
                    host = ""
                    try:
                        from urllib.parse import urlparse
                        host = str(urlparse(u).hostname or "").replace("www.", "")
                    except Exception:
                        host = ""
                    rows.append({"url": u[:500], "title": str(title or host or u)[:200], "host": host[:120]})

                candidates = []
                if str(name or "") == "fetch_urls":
                    candidates.extend([x for x in (result.get("pages") or result.get("results") or []) if isinstance(x, dict)])
                    raw_urls = args.get("urls") if isinstance(args.get("urls"), list) else []
                    candidates.extend([{"url": u} for u in raw_urls])
                else:
                    candidates.append(result)
                    candidates.append({"url": args.get("url") or args.get("href") or args.get("link") or ""})
                for row in candidates:
                    if not isinstance(row, dict):
                        continue
                    _push(row.get("url") or row.get("uri") or row.get("link") or row.get("href") or "", row.get("title") or row.get("name") or "")
                    if len(rows) >= 12:
                        break
                return rows

            def _pullback_emit_web_fetch_activity(name: str = "", args: dict | None = None, result: dict | None = None, status: str = "reading", call_id: str = "", round_no: int = 0) -> str:
                tool_name = str(name or "").strip() or "fetch_url"
                args = args if isinstance(args, dict) else {}
                result = result if isinstance(result, dict) else {}
                state_text = "done" if str(status or "").lower() in {"read", "done", "completed", "success"} else ("error" if str(status or "").lower() in {"error", "failed", "failure"} else "active")
                sources = _pullback_source_items_from_fetch(tool_name, args, result)
                first = sources[0] if sources else {}
                target = str(first.get("host") or first.get("title") or ("网页" if tool_name == "fetch_url" else f"{max(1, len(sources))} 个网页")).strip()
                prefix = "网页读取失败" if state_text == "error" else ("已阅读网页" if state_text == "done" else "正在阅读网页")
                op_key = str(call_id or args.get("url") or "|".join(str(x or "") for x in (args.get("urls") if isinstance(args.get("urls"), list) else [])) or f"{tool_name}|{round_no}").strip()
                now_ms = int(time.time() * 1000)
                return _pullback_emit_activity({
                    "key": f"web|fetch|{tool_name}|{op_key}"[:700],
                    "stage": "web_fetch",
                    "panel_stage": "search",
                    "tool": tool_name,
                    "title": f"{prefix}：{target}" if target else prefix,
                    "source_items": sources,
                    "result_count": max(len(sources), 1 if result or args else 0),
                    "source_count": max(len(sources), 1 if result or args else 0),
                    "state": state_text,
                    "percent": 100 if state_text in {"done", "error"} else 45,
                    "ts": now_ms,
                    "updated_at": now_ms,
                    "done_at": now_ms if state_text in {"done", "warn", "error"} else 0,
                    "source": "web_fetch",
                    "action_type": "open_page",
                    "actionType": "open_page",
                    "activity_op": "open_page",
                    "operation_key": op_key[:160],
                    "round": int(round_no or 0),
                })

            for _ in agent_tool_round_indices():
                rounds += 1
                req = _apply_completion_thinking_kwargs({
                    "model": model,
                    "messages": cur_messages,
                    "tools": tools,
                    "tool_choice": "auto",
                }, role="chat", model=model, client_override=client_override)
                resp = (client_override or client_gpt).chat.completions.create(**req)
                if not getattr(resp, "choices", None):
                    raise RuntimeError(f"模型返回空 choices：model={model}")

                msg = resp.choices[0].message
                tool_calls = getattr(msg, "tool_calls", None)
                if not tool_calls:
                    direct_answer = str(getattr(msg, "content", "") or "")
                    if direct_answer:
                        cur_messages.append({"role": "assistant", "content": direct_answer})
                    break

                cur_messages.append({
                    "role": "assistant",
                    "content": getattr(msg, "content", "") or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in tool_calls
                    ],
                })

                for tc in tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except Exception:
                        args = {}

                    if show_steps:
                        if name in globals().get('SANDBOX_TOOL_NAMES', set()):
                            progress_builder = globals().get('_sandbox_tool_progress_payload')
                            progress = progress_builder(name, args, {}, phase='start') if callable(progress_builder) else {'stage': 'sandbox_start', 'message': f'{label} 正在处理沙盒', 'percent': 5, 'ts': int(time.time() * 1000)}
                            yield sse("status", {"text": str(progress.get('message') or f"{label} 正在处理沙盒"), "file_progress": progress})
                        elif name == "web_search":
                            q = str(args.get("query") or args.get("q") or "")
                            tip = (q[:60] + "…") if len(q) > 60 else q
                            yield sse("status", {"text": f"{label} 正在搜索：{tip}".strip() or f"{label} 正在联网搜索…"})
                        elif name in {"fetch_url", "fetch_urls"}:
                            yield sse("status", {"text": f"{label} 正在读取网页…"})
                            yield _pullback_emit_web_fetch_activity(name, args, None, status="reading", call_id=str(getattr(tc, "id", "") or ""), round_no=rounds)
                        else:
                            yield sse("status", {"text": f"{label} 正在调用工具：{name}"})

                    if name == "web_search":
                        tool_counts["web_search"] += 1
                        result = _exec_tool(name, args, user_geo=user_geo, messages=cur_messages, client_override=client_override)
                    elif name == "fetch_url":
                        tool_counts["fetch_url"] += 1
                        result = _exec_tool(name, args, user_geo=user_geo, messages=cur_messages, client_override=client_override)
                        yield _pullback_emit_web_fetch_activity(name, args, result if isinstance(result, dict) else {}, status="read" if isinstance(result, dict) and bool(result.get("ok", True)) else "error", call_id=str(getattr(tc, "id", "") or ""), round_no=rounds)
                    elif name == "fetch_urls":
                        tool_counts["fetch_urls"] += 1
                        result = _exec_tool(name, args, user_geo=user_geo, messages=cur_messages, client_override=client_override)
                        yield _pullback_emit_web_fetch_activity(name, args, result if isinstance(result, dict) else {}, status="read" if isinstance(result, dict) and bool(result.get("ok", True)) else "error", call_id=str(getattr(tc, "id", "") or ""), round_no=rounds)
                    else:
                        if name in tool_counts:
                            tool_counts[name] += 1
                        result = _exec_tool(name, args, user_geo=user_geo, messages=cur_messages, client_override=client_override)

                    if show_steps and name in globals().get('SANDBOX_TOOL_NAMES', set()):
                        progress_builder = globals().get('_sandbox_tool_progress_payload')
                        progress = progress_builder(name, args, result if isinstance(result, dict) else {}, phase='done') if callable(progress_builder) else {'stage': 'sandbox_done', 'message': f'{label} 已处理沙盒', 'percent': 100, 'ts': int(time.time() * 1000)}
                        yield sse("status", {"text": str(progress.get('message') or f"{label} 已处理沙盒"), "file_progress": progress})

                    cur_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    })
            if direct_answer:
                if show_steps:
                    yield sse("status", {"text": f"{label} 生成回复中…"})
                yield sse("delta", {"text": direct_answer})
                meta = _emit_artifact_meta(direct_answer, {
                    "model": model,
                    "mode": "agent_direct",
                    "rounds": rounds,
                    "tool_counts": tool_counts,
                })
                yield sse("meta", meta)
                yield sse("done", {})
                return

            if show_steps:
                yield sse("status", {"text": f"{label} 生成回复中…"})

            req = _apply_completion_thinking_kwargs({
                "model": model,
                "messages": cur_messages,
                "stream": True,
            }, role="chat", model=model, client_override=client_override)
            stream_resp = (client_override or client_gpt).chat.completions.create(**req)
            full = ""
            for chunk in stream_resp:
                txt = _chunk_text(chunk)
                if not txt:
                    continue
                full += txt
                yield sse("delta", {"text": txt})

            meta = _emit_artifact_meta(full, {
                "model": model,
                "mode": "agent",
                "rounds": rounds,
                "tool_counts": tool_counts,
            })
            yield sse("meta", meta)
            yield sse("done", {})

        except Exception as e:
            app_logger.exception("chat_stream error")
            yield sse("error", {"error": f"{type(e).__name__}: {e}"})
            yield sse("done", {})

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
