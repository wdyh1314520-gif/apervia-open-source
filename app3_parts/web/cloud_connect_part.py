# cloud connect provider call and route.

def cloud_connect(query: str, k: int = 5, timeout: float = 12.0) -> dict:
    """云端联网能力（非本地浏览器式上网冲浪）：
    - 云端持续更新的知识库命中（kb_hits）
    - 需要实时性的内容通过合规实时数据接口（realtime）
    返回：
      {
        "kb_hits": [{"title","source","snippet","updated_at","url"}...],
        "realtime": [{"type","value","source","ts"}...],
        "note": "补充说明..."
      }
    """
    q = (query or "").strip()
    if not q:
        return {"kb_hits": [], "realtime": [], "note": ""}

    # mock：先用公开索引结果模拟“知识库命中”，方便本地直接跑通。
    if CLOUD_CONNECT_PROVIDER == "mock":
        hits = web_search_searxng(q, k=min(max(int(k), 1), 10), timeout=timeout)
        kb_hits = [{
            "title": it.get("title", ""),
            "source": "public_web_index (mocked as kb)",
            "snippet": it.get("snippet", ""),
            "updated_at": None,
            "url": it.get("url", ""),
        } for it in hits]
        return {
            "kb_hits": kb_hits,
            "realtime": [],
            "note": "当前为 mock：用公开索引结果模拟云端知识库命中；切换 CLOUD_CONNECT_PROVIDER 即可接入你的云端服务。",
        }

    # 真实云端服务：由你在云端实现合规检索/实时接口聚合，这里只做转发与适配
    if not CLOUD_CONNECT_ENDPOINT:
        raise RuntimeError("未配置 CLOUD_CONNECT_ENDPOINT")

    headers = {"Content-Type": "application/json"}
    if CLOUD_CONNECT_TOKEN:
        headers["Authorization"] = f"Bearer {CLOUD_CONNECT_TOKEN}"

    payload = {"q": q, "k": int(k)}
    t = httpx.Timeout(timeout, connect=min(4.0, float(timeout)))
    r = HTTPX_SEARCH.post(CLOUD_CONNECT_ENDPOINT, json=payload, headers=headers, timeout=t)
    r.raise_for_status()
    data = r.json()

    # 约定：你的云端返回就按上述结构；否则在这里做字段适配
    if not isinstance(data, dict):
        raise RuntimeError("云端返回不是 JSON object")
    data.setdefault("kb_hits", [])
    data.setdefault("realtime", [])
    data.setdefault("note", "")
    return data


@app.post("/api3/cloud_connect")
def api3_cloud_connect():
    if not CLOUD_CONNECT_ENABLED:
        return jsonify({"error": "Cloud connect disabled (CLOUD_CONNECT_ENABLED=0)"}), 403

    data = request.get_json(force=True, silent=True) or {}
    q = (data.get("q") or "").strip()
    k = int(data.get("k") or 5)
    k = max(1, min(k, 10))

    if not q:
        return jsonify({"kb_hits": [], "realtime": [], "note": ""})

    try:
        out = cloud_connect(q, k=k)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 400
