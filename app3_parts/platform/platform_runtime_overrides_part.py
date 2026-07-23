# Split from app3_parts/platform/platform_auth_part.py.
# Purpose: per-request runtime override helpers and config accessors.
# Loaded by app3.py via _exec_split_file(...), sharing the original global namespace.

# ====== 不再读取 .env.app3 ======

# ====== 不再读取 .env.app3 ======
# 按用户要求：API 与联网控制不再受 .env.app3 支配。
# 当前程序不会读取 .env.app3 或系统环境变量；相关配置改为：前端设置 > 程序内置默认值。

# ====== per-request runtime overrides ======
_REQUEST_OVERRIDES = contextvars.ContextVar("app3_request_overrides", default={})
_REQUEST_OVERRIDES_TLS = threading.local()
_LAST_REQUEST_OVERRIDES: dict[str, object] = {}
_LAST_REQUEST_OVERRIDES_LOCK = threading.Lock()

def _set_request_overrides(data: dict | None):
    data2 = dict(data or {})
    _REQUEST_OVERRIDES.set(data2)
    try:
        _REQUEST_OVERRIDES_TLS.data = data2
    except Exception:
        pass
    try:
        with _LAST_REQUEST_OVERRIDES_LOCK:
            _LAST_REQUEST_OVERRIDES.clear()
            _LAST_REQUEST_OVERRIDES.update(data2)
    except Exception:
        pass

def _get_request_override(name: str, default=None):
    ctx = _REQUEST_OVERRIDES.get({})
    if isinstance(ctx, dict) and name in ctx and ctx.get(name) not in (None, ""):
        return ctx.get(name)
    try:
        tls = getattr(_REQUEST_OVERRIDES_TLS, 'data', None)
        if isinstance(tls, dict) and name in tls and tls.get(name) not in (None, ""):
            return tls.get(name)
    except Exception:
        pass
    try:
        with _LAST_REQUEST_OVERRIDES_LOCK:
            if name in _LAST_REQUEST_OVERRIDES and _LAST_REQUEST_OVERRIDES.get(name) not in (None, ""):
                return _LAST_REQUEST_OVERRIDES.get(name)
    except Exception:
        pass
    return default


def _current_request_overrides_snapshot() -> dict:
    try:
        ctx = _REQUEST_OVERRIDES.get({})
        if isinstance(ctx, dict) and ctx:
            return dict(ctx)
    except Exception:
        pass
    try:
        tls = getattr(_REQUEST_OVERRIDES_TLS, 'data', None)
        if isinstance(tls, dict) and tls:
            return dict(tls)
    except Exception:
        pass
    try:
        with _LAST_REQUEST_OVERRIDES_LOCK:
            if isinstance(_LAST_REQUEST_OVERRIDES, dict) and _LAST_REQUEST_OVERRIDES:
                return dict(_LAST_REQUEST_OVERRIDES)
    except Exception:
        pass
    return {}

def _cfg_int(name: str, default: int) -> int:
    v = _get_request_override(name, None)
    if v in (None, ""):
        return int(default)
    try:
        return int(v)
    except Exception:
        return int(default)

def _cfg_float(name: str, default: float) -> float:
    v = _get_request_override(name, None)
    if v in (None, ""):
        return float(default)
    try:
        return float(v)
    except Exception:
        return float(default)
