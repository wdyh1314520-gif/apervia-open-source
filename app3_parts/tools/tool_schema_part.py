# top-level Chat Completions tool schema composition.

def _tools_schema(allow_weather_tool: bool = True):
    """OpenAI tool/function calling schema.

    说明：这里只定义“可以调用什么”，真正执行由 _exec_tool 完成。
    保留单轮工具判断：模型可从天气、联网搜索、网页抓取里选择一个最关键的工具。
    文件交付只走沙盒：写入/替换/运行验证/发布。
    """
    tools = []
    tools.extend(_sandbox_tool_schemas(compact=False))
    tools.append({
        "type": "function",
        "function": {
            "name": "get_location",
            "description": "返回本轮位置证据：已授权坐标、网络/IP 粗略位置、权限状态。只有模型判断确需本轮精确定位时才设置 request_precise=true。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "用户原始位置问题。"},
                    "request_precise": {"type": "boolean", "description": "是否请求浏览器精确定位授权；仅在粗略位置不足且确需精确位置时为 true。"},
                },
            },
        },
    })
    if allow_weather_tool:
        tools.append({
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取天气与近几天天气趋势。地点来源由工具内部结合模型决策、用户明确地点、结构化历史天气位置或已授权定位上下文处理；是否调用由模型根据用户意图判断。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "用户原始天气问题，可包含地点、时间、趋势等，例如：今天天气、天天下雨还要多久变晴天。"},
                    },
                },
            },
        })
    tools.extend([
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "联网搜索当前/外部信息。涉及最新、当前、价格、发布状态、名单、政策、出处核验等不应凭旧知识回答的问题时先用它获取证据。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "k": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "抓取单个网页正文（必要时可用 Playwright 渲染）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_chars": {"type": "integer"},
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_urls",
                "description": "批量抓取多个网页（最多5个）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "urls": {"type": "array", "items": {"type": "string"}},
                        "max_chars": {"type": "integer"},
                    },
                    "required": ["urls"],
                },
            },
        },
    ])
    return _normalize_tool_schemas_for_endpoint(tools, endpoint_mode='chat_completions')
