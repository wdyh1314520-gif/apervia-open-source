# tool schema endpoint normalizer.

def _tool_schema_function_name(spec: dict | None = None) -> str:
    if not isinstance(spec, dict):
        return ''
    fn = spec.get('function') if isinstance(spec.get('function'), dict) else {}
    return str((fn or {}).get('name') or spec.get('name') or '').strip()


def _tool_schema_registry_description(name: str = '', fallback: str = '', *, max_chars: int = 0) -> str:
    helper = globals().get('skill_tool_description')
    if callable(helper):
        try:
            desc = str(helper(str(name or '').strip(), fallback, max_chars=max_chars) or '').strip()
            if desc:
                return desc
        except Exception:
            pass
    desc = str(fallback or '').strip()
    if max_chars and len(desc) > int(max_chars):
        return desc[:max(1, int(max_chars))]
    return desc


def _tool_schema_allowed_for_endpoint(name: str = '', endpoint_mode: str = 'chat_completions') -> bool:
    helper = globals().get('skill_tool_allowed_for_mode')
    if callable(helper):
        try:
            return bool(helper(str(name or '').strip(), endpoint_mode))
        except Exception:
            return True
    return True


def _normalize_tool_schemas_for_endpoint(tools: list | None = None, *, endpoint_mode: str = 'chat_completions', desc_max_chars: int = 0) -> list[dict]:
    """Apply SkillRegistry endpoint boundaries without changing tool contracts.

    Chat schemas keep their detailed execution descriptions by default.  Callers
    that need compact capability text can pass desc_max_chars > 0 to opt into the
    registry description.
    """
    out: list[dict] = []
    for raw in (tools or []):
        if not isinstance(raw, dict):
            continue
        spec = dict(raw)
        name = _tool_schema_function_name(spec)
        if name and not _tool_schema_allowed_for_endpoint(name, endpoint_mode):
            continue
        if isinstance(spec.get('function'), dict):
            fn = dict(spec.get('function') or {})
            if name and desc_max_chars:
                fn['description'] = _tool_schema_registry_description(name, str(fn.get('description') or ''), max_chars=desc_max_chars)
            spec['function'] = fn
        elif name and desc_max_chars and 'description' in spec:
            spec['description'] = _tool_schema_registry_description(name, str(spec.get('description') or ''), max_chars=desc_max_chars)
        out.append(spec)
    return out
