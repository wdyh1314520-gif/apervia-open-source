# orchestrator soft hints and file gate helpers.

def _inject_orchestrator_soft_hint(messages: list, hint_text: str = '') -> list:
    out = list(messages or [])
    hint = str(hint_text or '').strip()
    if not hint:
        return out
    sys_msg = {'role': 'system', '_kind': 'orchestrator_soft_hint', 'content': hint}
    insert_at = 0
    for i, m in enumerate(out):
        if isinstance(m, dict) and m.get('role') == 'system':
            insert_at = i + 1
            if m.get('_kind') == 'orchestrator_soft_hint':
                out[i] = sys_msg
                return out
    out.insert(insert_at, sys_msg)
    return out


def _build_orchestrator_soft_hint(prefetch_decision: dict | None = None, *, file_hint_active: bool = False, enable_visual: bool = True) -> str:
    decision = dict(prefetch_decision or {})
    bits = [
        '下面这些只是上一层软提示，不是硬规则。是否调用定位、天气、图片、联网、sandbox artifact runtime，必须重新根据当前用户问题自行判断。',
        '可以保留多个候选信号，但必须先识别本轮最终交付物；只有最终交付物对应的通道才获得执行权。',
        '历史文件和历史图片只是上下文，不能自动抢当前轮执行权；不要把图片交付误扩展成文件/页面功能。',
    ]
    primary_delivery = _orch_normalize_primary_delivery(decision)
    if primary_delivery:
        bits.append(f'上一层选择的本轮最终交付物：{primary_delivery}。候选信号可以存在，但执行权应跟随最终交付物。')
    route_hint = str(decision.get('route_mode') or '').strip().lower()
    route_reason = str(decision.get('route_reason') or decision.get('reason') or '').strip()
    if route_hint and route_hint != 'direct_answer':
        bits.append(f'上一层软提示倾向：{route_hint}。{route_reason[:120] if route_reason else ""}'.strip())
    location_action = str(decision.get('location_action') or '').strip().lower()
    if location_action == 'resolve_location':
        reason = str(decision.get('location_reason') or '').strip()
        bits.append(f'软提示认为当前问题可能与位置有关，可考虑 get_location。{reason[:120] if reason else ""}'.strip())
    weather_action = str(decision.get('weather_action') or '').strip().lower()
    if weather_action == 'call_weather':
        reason = str(decision.get('weather_reason') or '').strip()
        bits.append(f'软提示认为当前问题可能与天气有关，可考虑 get_weather。{reason[:120] if reason else ""}'.strip())
    visual_decision = decision.get('visual_decision') if isinstance(decision.get('visual_decision'), dict) else {}
    visual_intent = str((visual_decision or {}).get('intent') or '').strip().lower()
    if enable_visual and visual_intent in {'image_search', 'existing_image_analysis'}:
        subject = str((visual_decision or {}).get('subject') or '').strip()
        bits.append(f'软提示认为图片可能有帮助：intent={visual_intent}，subject={subject[:80] or "未写主体"}。是否真的要走视觉能力，仍需你重新判断。')
    need_external_evidence = bool(decision.get('need_external_evidence'))
    current_world_risk = str(decision.get('current_world_risk') or '').strip().lower()
    if need_external_evidence or current_world_risk in {'medium', 'high'}:
        bits.append(f'软提示认为这题可能存在外部证据/当前世界状态风险：need_external_evidence={str(need_external_evidence).lower()}，current_world_risk={current_world_risk or "low"}。是否联网，请独立判断。')
    if file_hint_active:
        file_reason = str(decision.get('file_reason') or '').strip()
        runtime_plan_prompt = ''
        try:
            prompt_builder = globals().get('skill_runtime_prompt')
            if callable(prompt_builder):
                runtime_plan_prompt = str(prompt_builder('chat_completions', ['sandbox'], compact=True) or '').strip()
        except Exception:
            runtime_plan_prompt = ''
        bits.append(f'当前对话里可能存在真实文件交付需求；只有在用户确实要真实文件时才进入 sandbox artifact runtime。{file_reason[:120] if file_reason else ""}'.strip())
        if runtime_plan_prompt:
            bits.append(runtime_plan_prompt)
    return '\n'.join([str(x).strip() for x in bits if str(x).strip()])



def _orch_image_edit_enabled(settings: dict | None = None) -> bool:
    try:
        normalizer = globals().get('_normalize_image_generation_settings')
        normalized = normalizer(settings or {}) if callable(normalizer) else dict(settings or {})
        edit = normalized.get('edit') if isinstance(normalized, dict) and isinstance(normalized.get('edit'), dict) else {}
        if edit:
            return bool(edit.get('enabled'))
        raw = settings if isinstance(settings, dict) else {}
        return bool(raw.get('edit_enabled') or raw.get('image_edit_enabled'))
    except Exception:
        return False


def _decide_orchestrated_tool_plan_once(model: str, messages: list, last_user_text: str, *, prefetch_decision: dict | None = None, file_hint_active: bool = False, enable_visual: bool = True, image_generation_enabled: bool = False, image_generation_settings: dict | None = None, client_override=None, user_geo: dict | None = None, user_time: dict | None = None) -> dict:
    """统一工具规划直接复用第一次预判，不再额外调用一轮模型。"""
    _ = model, messages, last_user_text, client_override, user_geo, user_time
    decision = _orch_apply_primary_delivery_lock(prefetch_decision or {})
    primary_delivery = _orch_normalize_primary_delivery(decision)
    route_hint = _normalize_prefetch_route_mode(decision)
    answer_strategy = _normalize_prefetch_answer_strategy(decision, route_mode=route_hint)
    location_action = str(decision.get('location_action') or '').strip().lower()
    weather_action = str(decision.get('weather_action') or '').strip().lower()
    file_action = str(decision.get('file_action') or '').strip().lower()
    visual_prefetch = decision.get('visual_decision') if isinstance(decision.get('visual_decision'), dict) else {}
    visual_intent = str((visual_prefetch or {}).get('intent') or '').strip().lower()
    # First-stage prefetch only decides the coarse visual lane. Detailed image tasks
    # are handled by _plan_image_task_once inside image mode. Keep old detailed
    # intents compatible in case an older prompt/model returns them.
    visual_available = enable_visual and visual_intent in {'image_search'}
    image_mode_available = bool(image_generation_enabled and visual_intent in {'image_mode', 'existing_image_analysis', 'image_generation', 'image_edit', 'reference_generate', 'reference_edit', 'variation'})
    soft_web_research_hit = _prefetch_soft_web_research_hit(
        decision,
        route_mode=route_hint,
        answer_strategy=answer_strategy,
    )

    use_location = location_action == 'resolve_location'
    use_weather = weather_action == 'call_weather'
    use_visual = bool((visual_available or image_mode_available) and (route_hint == 'visual' or primary_delivery in {'image', 'image_edit', 'composite'}))
    use_image_mode = bool(image_mode_available and (route_hint == 'visual' or primary_delivery in {'image', 'image_edit', 'composite'}))
    request_file_generation = bool(file_action in {'sandbox_files'} and (not primary_delivery or primary_delivery in {'file', 'file_edit', 'composite'}))
    use_web_research = bool(soft_web_research_hit)

    reason_bits = []
    if use_location:
        reason_bits.append('prefetch_location')
    if use_weather:
        reason_bits.append('prefetch_weather')
    if use_image_mode:
        reason_bits.append('prefetch_image_mode')
    elif use_visual:
        reason_bits.append('prefetch_visual')
    if use_web_research:
        reason_bits.append('prefetch_web_research')
    if request_file_generation:
        reason_bits.append('prefetch_file_generation')
    if not reason_bits:
        reason_bits.append('prefetch_direct_answer')

    return {
        'use_location': bool(use_location),
        'location_reason': str(decision.get('location_reason') or '')[:120],
        'use_weather': bool(use_weather),
        'weather_reason': str(decision.get('weather_reason') or '')[:120],
        'use_web_research': bool(use_web_research),
        'web_reason': str(decision.get('route_reason') or decision.get('strategy_reason') or '')[:120],
        'use_visual': bool(use_visual),
        'use_image_mode': bool(use_image_mode),
        'use_image_generation': False,
        'use_image_edit': False,
        'image_task_mode': '',
        'image_mode_hint': visual_intent,
        'primary_delivery': primary_delivery or '',
        'visual_reason': str((visual_prefetch or {}).get('reason') or '')[:120],
        'image_generation_subject': str((visual_prefetch or {}).get('subject') or '')[:240],
        'request_file_generation': bool(request_file_generation),
        'file_reason': str(decision.get('file_reason') or ('soft_hint_only' if file_hint_active else ''))[:120],
        'answer_strategy': answer_strategy or 'fast_direct',
        'reason': ' / '.join(reason_bits)[:120],
        'source': 'prefetch_unified',
    }

def _decide_orchestrator_file_gate(model: str, messages: list, *, prefetch_decision: dict | None = None, client_override=None) -> dict:
    """Sandbox artifact intent only injects a soft hint; prepare never short-circuits."""
    _ = model, client_override
    file_hint_active = bool(_build_file_delivery_soft_prompt(messages or []))
    prefetch_decision = dict(prefetch_decision or {})
    return {
        'should_enter_sandbox_files': False,
        'reason': 'soft_hint_only' if file_hint_active else 'no_file_hint',
        'source': 'no_early_short_circuit',
        'file_hint_active': file_hint_active,
        'prefetch_file_action': str(prefetch_decision.get('file_action') or '').strip().lower() or 'none',
    }

def _agent_stream_env_flag(name: str, default: str = '1') -> bool:
    raw = str(os.getenv(name, default) or default).strip().lower()
    return raw not in {'0', 'false', 'no', 'off', 'disabled'}


def _agent_stream_should_skip_initial_prepare(enable_tools: bool = True) -> bool:
    """Whether the HTTP route should skip the old prepare prompt before direct Agent.

    Direct-first models receive the API tool schema, so the heavy prepare/query/prefetch
    prompts are not needed on the direct streaming Agent path.
    """
    if not enable_tools:
        return False
    if not _agent_stream_env_flag('AGENT_STREAM_TOOLS_ENABLED', '1'):
        return False
    if not _agent_stream_env_flag('AGENT_STREAM_DIRECT_FIRST_ENABLED', '1'):
        return False
    return _agent_stream_env_flag('AGENT_STREAM_SKIP_INITIAL_PREPARE', '1')
