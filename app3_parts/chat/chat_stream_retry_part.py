# centralize stream retry configuration and retryable-error rules.


class ChatStreamRetryPolicy:
    def cfg_int(self, name: str, default: int, *, min_value: int = 0, max_value: int = 100) -> int:
        try:
            value = int(str(app_getenv(name, str(default)) or default).strip())
        except Exception:
            value = int(default)
        return max(int(min_value), min(int(max_value), value))

    def cfg_float(self, name: str, default: float, *, min_value: float = 0.0, max_value: float = 60.0) -> float:
        try:
            value = float(str(app_getenv(name, str(default)) or default).strip())
        except Exception:
            value = float(default)
        return max(float(min_value), min(float(max_value), value))

    def max_retries(self) -> int:
        return self.cfg_int('GPT_STREAM_MAX_RETRIES', 2, min_value=0, max_value=5)

    def max_attempts(self) -> int:
        return 1 + self.max_retries()

    def is_retryable(self, err: Exception) -> bool:
        if isinstance(err, (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError, httpx.NetworkError)):
            return True
        try:
            status = getattr(err, 'status_code', None)
            if status is None:
                response = getattr(err, 'response', None)
                status = getattr(response, 'status_code', None)
            if int(status or 0) in {500, 502, 503, 504, 520, 522, 523, 524}:
                return True
        except Exception:
            pass
        name = type(err).__name__.lower()
        txt = str(err or '').lower()
        non_retryable_markers = (
            '429', 'too many requests', 'usage_limit', 'usage limit', 'rate limit',
            'model_cooldown', 'cooling down', 'all credentials',
        )
        if any(token in txt for token in non_retryable_markers):
            return False
        markers = (
            'apiconnectionerror', 'api connection error', 'connection reset', 'connection aborted',
            'server disconnected', 'remote protocol', 'readtimeout', 'connecttimeout', 'pooltimeout',
            'temporarily unavailable', 'bad gateway', 'gateway timeout', 'upstream', 'eof',
            'internalservererror', 'internal server error', '500 internal server error', 'http/1.1 500',
            '<h1>500', '502 bad gateway', '503 service unavailable', '504 gateway timeout',
            'responses api error 500', 'responses api error 502', 'responses api error 503', 'responses api error 504',
            '520', '522', '523', '524', 'nginx',
        )
        if any(token in name for token in ('timeout', 'connection', 'protocol', 'network', 'internalservererror')):
            return True
        return any(token in txt for token in markers)

    def delay(self, attempt: int) -> float:
        base = self.cfg_float('GPT_STREAM_RETRY_BACKOFF', 0.75, min_value=0.05, max_value=10.0)
        cap = self.cfg_float('GPT_STREAM_RETRY_MAX_BACKOFF', 3.0, min_value=0.1, max_value=30.0)
        jitter = 0.15 * random.random()
        return min(cap, base * (2 ** max(0, int(attempt) - 1)) + jitter)
