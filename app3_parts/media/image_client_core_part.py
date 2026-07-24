# compatible API clients, image workflows, artifact delivery, and sandbox adapters.

# ====== OpenAI 兼容 ======
# API 配置不再受 .env.app3 控制；默认值只作为前端未传入时的兜底。
GPT_BASE_URL = "https://api.openai.com/v1"
GPT_API_KEY = ""
tls_verify = app_getenv("GPT_TLS_VERIFY", "1").strip() != "0"

# ====== HTTPX 网络参数（供 _httpx_get_json / 搜索 / 高德接口复用） ======
WEB_SEARCH_TLS_VERIFY = app_getenv("WEB_SEARCH_TLS_VERIFY", "1").strip() != "0"
WEB_SEARCH_TRUST_ENV = app_getenv("WEB_SEARCH_TRUST_ENV", "0").strip() != "0"

# ====== HTTPX 全局连接池（并发/性能关键）======
# 说明：
# - 避免在每次请求里反复 with httpx.Client(...) 造成 TCP/TLS 反复握手
# - 统一复用 keep-alive 连接，提高吞吐量
# - 每次请求可覆盖 timeout / headers
def _app_cfg_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        value = int(str(app_getenv(name, str(default)) or default).strip())
    except Exception:
        value = int(default)
    if min_value is not None:
        value = max(int(min_value), value)
    if max_value is not None:
        value = min(int(max_value), value)
    return value


def _app_cfg_float(name: str, default: float, *, min_value: float | None = None, max_value: float | None = None) -> float:
    try:
        value = float(str(app_getenv(name, str(default)) or default).strip())
    except Exception:
        value = float(default)
    if min_value is not None:
        value = max(float(min_value), value)
    if max_value is not None:
        value = min(float(max_value), value)
    return value


def _openai_max_retries(default: int = 2) -> int:
    return _app_cfg_int('GPT_API_MAX_RETRIES', default, min_value=0, max_value=5)


_HTTPX_LIMITS = httpx.Limits(
    max_keepalive_connections=int(app_getenv("HTTPX_MAX_KEEPALIVE", "30") or 30),
    max_connections=int(app_getenv("HTTPX_MAX_CONNECTIONS", "80") or 80),
    keepalive_expiry=float(app_getenv("HTTPX_KEEPALIVE_EXPIRY", "30") or 30),
)

HTTPX_GPT = httpx.Client(
    verify=tls_verify,
    timeout=httpx.Timeout(
        connect=_app_cfg_float('GPT_API_CONNECT_TIMEOUT', 45.0, min_value=5.0, max_value=120.0),
        read=_app_cfg_float('GPT_API_READ_TIMEOUT', 900.0, min_value=60.0, max_value=1800.0),
        write=_app_cfg_float('GPT_API_WRITE_TIMEOUT', 300.0, min_value=30.0, max_value=900.0),
        pool=_app_cfg_float('GPT_API_POOL_TIMEOUT', 60.0, min_value=5.0, max_value=300.0),
    ),
    limits=_HTTPX_LIMITS,
    follow_redirects=True,
)
HTTPX_GPT_FILE = httpx.Client(
    verify=tls_verify,
    timeout=httpx.Timeout(
        connect=_app_cfg_float('GPT_API_CONNECT_TIMEOUT', 45.0, min_value=5.0, max_value=120.0),
        read=_app_cfg_float('GPT_FILE_STREAM_READ_TIMEOUT', 1200.0, min_value=120.0, max_value=2400.0),
        write=_app_cfg_float('GPT_FILE_STREAM_WRITE_TIMEOUT', 360.0, min_value=30.0, max_value=900.0),
        pool=_app_cfg_float('GPT_API_POOL_TIMEOUT', 60.0, min_value=5.0, max_value=300.0),
    ),
    limits=_HTTPX_LIMITS,
    follow_redirects=True,
    trust_env=False,
)
HTTPX_SEARCH = httpx.Client(verify=tls_verify, timeout=12.0, limits=_HTTPX_LIMITS, follow_redirects=True)
HTTPX_WEB = httpx.Client(
    verify=WEB_SEARCH_TLS_VERIFY,
    timeout=10.0,
    limits=_HTTPX_LIMITS,
    follow_redirects=True,
    trust_env=WEB_SEARCH_TRUST_ENV,
)

# OpenAI SDK 2.x 会在构造客户端时拒绝空密钥。默认客户端只是兼容旧调用链的
# 兜底对象；真正请求仍由用户/后台配置产生的 client_override 承载。这里使用
# 明确的非密钥占位值，让全新 Docker 实例可以先启动并完成管理员初始化。
_OPENAI_CLIENT_BOOTSTRAP_KEY = GPT_API_KEY or 'not-configured'

client_gpt = OpenAI(
    api_key=_OPENAI_CLIENT_BOOTSTRAP_KEY,
    base_url=GPT_BASE_URL,
    http_client=HTTPX_GPT,
    max_retries=_openai_max_retries(),
)
client_gpt_file = OpenAI(
    api_key=_OPENAI_CLIENT_BOOTSTRAP_KEY,
    base_url=GPT_BASE_URL,
    http_client=HTTPX_GPT_FILE,
    max_retries=_openai_max_retries(),
)


def _resolve_openai_client_identity(client_override=None, *, default_api_key: str | None = None, default_base_url: str | None = None) -> tuple[str, str]:
    api_key = str(default_api_key if default_api_key is not None else GPT_API_KEY or '').strip()
    base_url = str(default_base_url if default_base_url is not None else GPT_BASE_URL or '').strip()
    if client_override is None:
        return api_key, base_url
    try:
        override_key = str(getattr(client_override, 'api_key', '') or '').strip()
    except Exception:
        override_key = ''
    try:
        override_base = str(getattr(client_override, 'base_url', '') or '').strip()
    except Exception:
        override_base = ''
    if override_key:
        api_key = override_key
    if override_base:
        base_url = override_base
    return api_key, (base_url or GPT_BASE_URL)


def _close_httpx_client_quietly(http_client) -> None:
    if http_client is None:
        return
    try:
        close_fn = getattr(http_client, 'close', None)
        if callable(close_fn):
            close_fn()
            return
    except Exception:
        pass
    try:
        close_fn = getattr(http_client, 'aclose', None)
        if callable(close_fn):
            close_fn()
    except Exception:
        pass


def _build_isolated_stream_openai_client(client_override=None, *, read_timeout: float | None = None, write_timeout: float | None = None):
    api_key, base_url = _resolve_openai_client_identity(client_override)
    resolved_connect_timeout = _app_cfg_float('GPT_STREAM_CONNECT_TIMEOUT', 45.0, min_value=5.0, max_value=120.0)
    resolved_pool_timeout = _app_cfg_float('GPT_STREAM_POOL_TIMEOUT', 60.0, min_value=5.0, max_value=300.0)
    resolved_read_timeout = float(read_timeout if read_timeout is not None else (app_getenv('GPT_STREAM_READ_TIMEOUT', '900') or 900))
    resolved_write_timeout = float(write_timeout if write_timeout is not None else (app_getenv('GPT_STREAM_WRITE_TIMEOUT', '300') or 300))
    http_client = httpx.Client(
        verify=tls_verify,
        timeout=httpx.Timeout(
            connect=resolved_connect_timeout,
            read=max(60.0, resolved_read_timeout),
            write=max(30.0, resolved_write_timeout),
            pool=resolved_pool_timeout,
        ),
        limits=httpx.Limits(max_keepalive_connections=0, max_connections=1, keepalive_expiry=0.0),
        follow_redirects=True,
    )
    client = OpenAI(
        api_key=api_key,
        base_url=base_url or GPT_BASE_URL,
        http_client=http_client,
        max_retries=0,
    )
    # Preserve the user's selected endpoint lane for file delivery.  The isolated
    # HTTP client is only a transport swap; it must not silently turn a Responses
    # request into Chat Completions.
    try:
        setattr(client, '_webai_api_endpoint_mode', getattr(client_override, '_webai_api_endpoint_mode', 'chat_completions'))
        setattr(client, '_webai_api_settings', dict(getattr(client_override, '_webai_api_settings', {}) or {}))
        setattr(client, '_webai_file_api_source', getattr(client_override, '_webai_file_api_source', 'current_endpoint_only'))
    except Exception:
        pass
    return client, http_client
