# persistent Responses WebSocket v2 transport with HTTP fallback handled by the caller.


def _responses_websocket_enabled() -> bool:
    raw = str(app_getenv('RESPONSES_WEBSOCKET_ENABLED', '1') or '1').strip().lower()
    return raw not in {'0', 'false', 'no', 'off'}


def _responses_websocket_url(endpoint: str = '') -> str:
    raw = str(endpoint or '').strip()
    if raw.startswith('https://'):
        return 'wss://' + raw[len('https://'):]
    if raw.startswith('http://'):
        return 'ws://' + raw[len('http://'):]
    return raw


def _responses_websocket_request_event(body: dict | None = None) -> dict:
    event = dict(body or {})
    event.pop('stream', None)
    event.pop('background', None)
    event['type'] = 'response.create'
    event.setdefault('store', False)
    return event


def _responses_websocket_handshake_headers(headers: dict | None = None) -> dict:
    """构造 Responses WebSocket v2 握手头，避免混入 HTTP/SSE 专用头。"""
    blocked = {
        'accept',
        'connection',
        'content-length',
        'content-type',
        'host',
        'origin',
        'upgrade',
    }
    result = {}
    for key, value in dict(headers or {}).items():
        name = str(key or '').strip()
        lowered = name.lower()
        if not name or not str(value or '').strip():
            continue
        if lowered in blocked or lowered.startswith('sec-websocket-'):
            continue
        if lowered == 'openai-beta':
            continue
        result[name] = value
    result['OpenAI-Beta'] = 'responses_websockets=2026-02-06'
    return result


def _responses_websocket_error_is_unsupported(error) -> bool:
    """只把明确的协议/升级拒绝记为不支持，网络抖动仍允许后续重试。"""
    text = str(error or '').strip().lower()
    if not text:
        return False
    return any(marker in text for marker in (
        'handshake status 200',
        'handshake status 400',
        'handshake status 404',
        'handshake status 405',
        'unexpected http response',
        'upgrade required',
        'websocket upgrade',
        'does not support websocket',
        'websocket is not supported',
    ))


class ResponsesTransportCapabilityRegistry:
    """按端点记忆已验证的 Responses 传输能力，避免每轮重复走失败协议。"""

    def __init__(self, ttl_seconds: float = 1800.0):
        import threading
        self.ttl_seconds = max(60.0, float(ttl_seconds or 1800.0))
        self._states: dict[str, dict] = {}
        self._lock = threading.RLock()

    def endpoint_key(self, endpoint: str = '') -> str:
        from urllib.parse import urlsplit
        raw = str(endpoint or '').strip()
        try:
            parsed = urlsplit(raw)
            if parsed.netloc:
                return '%s://%s%s' % (
                    str(parsed.scheme or '').lower(),
                    str(parsed.netloc or '').lower(),
                    str(parsed.path or '').rstrip('/').lower(),
                )
        except Exception:
            pass
        return raw.rstrip('/').lower()

    def get(self, endpoint: str = '', capability: str = '') -> bool | None:
        import time
        key = self.endpoint_key(endpoint)
        name = str(capability or '').strip().lower()
        if not key or not name:
            return None
        now = time.monotonic()
        with self._lock:
            state = self._states.get(key)
            if not isinstance(state, dict) or now - float(state.get('updated_at') or 0.0) > self.ttl_seconds:
                self._states.pop(key, None)
                return None
            value = state.get(name)
            return value if isinstance(value, bool) else None

    def set(self, endpoint: str = '', capability: str = '', supported: bool | None = None) -> None:
        import time
        key = self.endpoint_key(endpoint)
        name = str(capability or '').strip().lower()
        if not key or not name or not isinstance(supported, bool):
            return
        with self._lock:
            state = self._states.setdefault(key, {})
            state[name] = supported
            state['updated_at'] = time.monotonic()


_RESPONSES_TRANSPORT_CAPABILITIES = ResponsesTransportCapabilityRegistry()


class ResponsesWebSocketTransport:
    """一条工具链复用一条 Responses WebSocket 连接。"""

    def __init__(self, *, endpoint: str, headers: dict | None = None, logger=None, timeout: float = 900.0):
        self.endpoint = str(endpoint or '').strip()
        self.url = _responses_websocket_url(self.endpoint)
        self.headers = dict(headers or {})
        self.logger = logger
        self.timeout = max(10.0, float(timeout or 900.0))
        self._socket = None

    def _connect(self):
        if self._socket is not None:
            return self._socket
        import websocket

        handshake_headers = _responses_websocket_handshake_headers(self.headers)
        header_rows = [f'{key}: {value}' for key, value in handshake_headers.items()]
        self._socket = websocket.create_connection(
            self.url,
            header=header_rows,
            timeout=self.timeout,
            enable_multithread=True,
        )
        return self._socket

    def stream_response(self, body: dict | None = None):
        ws = self._connect()
        event = _responses_websocket_request_event(body)
        ws.send(json.dumps(event, ensure_ascii=False, default=str))
        while True:
            raw = ws.recv()
            if raw is None:
                raise RuntimeError('Responses WebSocket closed before terminal event')
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode('utf-8', errors='replace')
            payload = json.loads(str(raw or '{}'))
            if not isinstance(payload, dict):
                continue
            event_type = str(payload.get('type') or '').strip().lower()
            if event_type == 'error':
                error_obj = payload.get('error') if isinstance(payload.get('error'), dict) else {}
                raise RuntimeError(
                    'Responses WebSocket error: '
                    + str(error_obj.get('message') or payload.get('message') or payload)[:2000]
                )
            yield payload
            if event_type in {
                'response.completed',
                'response.failed',
                'response.incomplete',
                'response.cancelled',
            }:
                return

    def close(self) -> None:
        ws, self._socket = self._socket, None
        if ws is None:
            return
        try:
            ws.close()
        except Exception:
            pass
