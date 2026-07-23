# Split from app3_parts/tools/file_registry_edit_tools_part.py.
# Purpose: inject lightweight runtime tool-selection context into model messages.
# Loaded after tool_schema_part.py, sharing the original global namespace.

def _inject_runtime_tool_context(messages: list, user_geo: dict | None = None, allow_weather_tool: bool = True, route_signals: dict | None = None) -> list:
    """Inject a lightweight system hint so the model knows which tool to choose.

    目标：只提供可用工具和结构化上下文；是否调用工具由模型统一判断。
    """
    out = list(messages or [])
    bits = [
        "工具按需调用；不需要工具就直接回答。",
        "位置/天气/网页/文件工具都只按完整语义触发，不按单个词硬触发。",
    ]
    if allow_weather_tool:
        bits.extend([
            "真实天气用 get_weather；讨论功能、数据来源或接口实现时直接解释或按需联网。",
        ])
    else:
        bits.append("本轮天气工具未开放；涉及说明、来源、接口或实现方式可直接回答或按需 web_search。")
    bits.extend([
        "最新/实时/近期信息用 web_search；用户给 URL 且要读页面时用 fetch_url/fetch_urls。",
    ])

    if _sandbox_tools_enabled():
        bits.extend([
            "Sandbox 只用于文件/项目的导入、读取、审阅、diff、修改、运行、测试或发布；先 import 到 /mnt/data，文本用 read，视觉/OCR 用 analyze_images，代码执行用 run，交付用 publish，不走宿主机 shell。",
        ])

    memory = None
    location_state = {}
    try:
        if isinstance(user_geo, dict) and isinstance(user_geo.get('_location_state'), dict):
            location_state = dict(user_geo.get('_location_state') or {})
    except Exception:
        location_state = {}
    try:
        latest_user_text = _latest_user_text_from_messages(out)
    except Exception:
        latest_user_text = ""
    try:
        skill_prompt_builder = globals().get('_sandbox_skills_prompt_for_user')
        if callable(skill_prompt_builder) and _sandbox_tools_enabled():
            try:
                skill_prompt = str(skill_prompt_builder(latest_user_text, compact=True, messages=out, route_signals=route_signals if isinstance(route_signals, dict) else {}) or '').strip()
            except TypeError:
                skill_prompt = str(skill_prompt_builder(latest_user_text, compact=True) or '').strip()
            if skill_prompt:
                bits.append(skill_prompt)
    except Exception:
        pass
    try:
        memory = _extract_weather_memory_from_messages(out, current_user_text=latest_user_text)
    except Exception:
        memory = None
    if isinstance(user_geo, dict) and user_geo.get("lat") is not None and user_geo.get("lon") is not None:
        try:
            lat = float(user_geo.get("lat"))
            lon = float(user_geo.get("lon"))
            bits.append(f"前端随请求附带了已授权的缓存位置坐标：lat={lat:.6f}, lon={lon:.6f}。这只是可用上下文；只有用户确实需要本地天气或当前位置时才使用。")
        except Exception:
            bits.append("前端随请求附带了已授权的缓存位置；这只是可用上下文，只有用户确实需要本地天气或当前位置时才使用。")
    elif allow_weather_tool and isinstance(memory, dict) and memory.get("lat") is not None and memory.get("lon") is not None:
        try:
            lat = float(memory.get("lat"))
            lon = float(memory.get("lon"))
            name = str(memory.get("name") or "最近天气位置").strip() or "最近天气位置"
            source = str(memory.get("source") or "recent_weather").strip()
            bits.append(f"最近已有结构化天气位置：{name}（lat={lat:.6f}, lon={lon:.6f}, source={source}）。这只是可用上下文；是否复用由模型根据当前问题判断。")
        except Exception:
            bits.append("最近已有结构化天气位置；这只是可用上下文，是否复用由模型根据当前问题判断。")
    elif allow_weather_tool:
        try:
            precise_state = location_state.get('precise_location') if isinstance(location_state.get('precise_location'), dict) else {}
            time_state = location_state.get('time_environment') if isinstance(location_state.get('time_environment'), dict) else {}
            state_bits = []
            if precise_state:
                if 'enabled' in precise_state:
                    state_bits.append('定位开关=' + ('开启' if bool(precise_state.get('enabled')) else '关闭'))
                perm = str(precise_state.get('permission_state') or '').strip()
                if perm:
                    state_bits.append('权限=' + perm)
            tz = str(time_state.get('timezone') or '').strip()
            if tz:
                state_bits.append('时区=' + tz + '（不能当作城市）')
            if state_bits:
                bits.append('当前没有可用精确坐标；' + '，'.join(state_bits) + '。天气或本地问题缺少可执行地点时，可让用户提供城市/地区或开启定位。')
            else:
                bits.append("当前没有可用定位；若天气或本地问题也没有明确地点，可以简短追问城市/地区，或提示开启定位。")
        except Exception:
            bits.append("当前没有可用定位；若天气或本地问题也没有明确地点，可以简短追问城市/地区，或提示开启定位。")

    sys_msg = {"role": "system", "_kind": "tool_runtime", "content": "\n".join(bits)}
    insert_at = 0
    for i, m in enumerate(out):
        if isinstance(m, dict) and m.get("role") == "system":
            insert_at = i + 1
            if m.get("_kind") == "tool_runtime":
                out[i] = sys_msg
                return out
    out.insert(insert_at, sys_msg)
    return out
