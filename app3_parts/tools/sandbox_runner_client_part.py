# Purpose: authenticated client for the isolated sandbox runner service.

from mcp_client.signing import sign_request as _sandbox_runner_sign_request


def _sandbox_runner_base_url() -> str:
    return str(app_getenv('SANDBOX_RUNNER_URL', 'http://sandbox-runner:8767') or '').strip().rstrip('/')


def _sandbox_runner_secret_file() -> str:
    return _app_data_path('sandbox_runner.secret')


def _sandbox_runner_secret() -> str:
    configured = str(os.getenv('SANDBOX_RUNNER_SECRET', '') or '').strip()
    if configured:
        if len(configured) < 32:
            raise RuntimeError('SANDBOX_RUNNER_SECRET 长度必须至少为 32 个字符')
        return configured
    path = _sandbox_runner_secret_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, 'r', encoding='ascii') as handle:
            secret = handle.read().strip()
    except FileNotFoundError:
        secret = secrets.token_urlsafe(48)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            with open(path, 'r', encoding='ascii') as handle:
                secret = handle.read().strip()
        else:
            with os.fdopen(fd, 'w', encoding='ascii', newline='\n') as handle:
                handle.write(secret + '\n')
                handle.flush()
                os.fsync(handle.fileno())
    if len(secret) < 32:
        raise RuntimeError('sandbox_runner.secret 无效')
    return secret


def _sandbox_runner_health() -> dict:
    base = _sandbox_runner_base_url()
    try:
        response = requests.get(base + '/healthz', timeout=2.0, allow_redirects=False)
        data = response.json() if response.status_code == 200 else {}
        return dict(data or {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _sandbox_runner_request_path(path: str, payload: dict, *, timeout: float = 330.0) -> dict:
    path = '/' + str(path or '').strip().lstrip('/')
    if path not in {'/v1/run', '/v1/python/inventory', '/v1/python/install'}:
        raise RuntimeError('Sandbox Runner 请求路径不允许')
    body = json.dumps(payload or {}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    secret = _sandbox_runner_secret()
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-App3-Sandbox-Timestamp': timestamp,
        'X-App3-Sandbox-Nonce': nonce,
        'X-App3-Sandbox-Signature': _sandbox_runner_sign_request(secret, 'POST', path, timestamp, nonce, body),
    }
    response = requests.post(
        _sandbox_runner_base_url() + path,
        data=body,
        headers=headers,
        timeout=max(10.0, min(float(timeout), 360.0)),
        allow_redirects=False,
    )
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(f'Sandbox Runner 返回了无效 JSON：HTTP {response.status_code}') from exc
    if response.status_code >= 400 or not bool(data.get('ok')):
        raise RuntimeError(str(data.get('message') or data.get('error') or f'Sandbox Runner HTTP {response.status_code}'))
    return dict(data)


def _sandbox_runner_request(payload: dict, *, timeout: float = 330.0) -> dict:
    return _sandbox_runner_request_path('/v1/run', payload, timeout=timeout)
