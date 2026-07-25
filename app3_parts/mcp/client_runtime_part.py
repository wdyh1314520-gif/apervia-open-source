# Purpose: connect Apervia's existing assistant tool loops to external MCP servers.
# Loaded after the canonical tool dispatcher and account runtime are available.

from urllib.parse import urlencode as _mcp_urlencode, urlsplit as _mcp_urlsplit

from mcp_client.signing import sign_request as _mcp_bridge_sign_request


_MCP_CLIENT_PROXY_PREFIX = 'mcp_ext_'
_MCP_CLIENT_MAX_SERVERS = 6
_MCP_CLIENT_MAX_TOOLS = 80
_MCP_CLIENT_NAME_RE = re.compile(r'[^a-zA-Z0-9_-]+')
_MCP_CLIENT_PERMISSION_MODES = {'always_ask', 'allow_read', 'allow_low_risk', 'allow_all'}
_MCP_CLIENT_OAUTH_PENDING = {}
_MCP_CLIENT_OAUTH_COMPLETED = {}
_MCP_CLIENT_OAUTH_LOCK = threading.RLock()
_MCP_CLIENT_BRIDGE_PROCESS = None
_MCP_CLIENT_BRIDGE_START_LOCK = threading.Lock()
_MCP_CLIENT_BRIDGE_ATEXIT_BOUND = False
_MCP_CLIENT_DANGEROUS_NAME_RE = re.compile(
    r'(?:delete|remove|destroy|drop|truncate|erase|purge|kill|shutdown|reboot|reset|'
    r'exec|shell|command|patch|write|move|rename|upload|payment|purchase|transfer|'
    r'publish|send|invite|permission|credential|secret|token)',
    re.I,
)


def _mcp_client_bridge_base_url() -> str:
    return str(os.getenv('APP3_MCP_BRIDGE_URL', 'http://127.0.0.1:8766') or '').strip().rstrip('/')


def _mcp_client_bridge_secret() -> str:
    return str(os.getenv('APP3_MCP_BRIDGE_SECRET', '') or '').strip()


def _mcp_client_bridge_healthy(base: str) -> bool:
    try:
        response = requests.get(str(base or '').rstrip('/') + '/healthz', timeout=1.0, allow_redirects=False)
        data = response.json() if response.status_code == 200 else {}
        return bool(data.get('ok')) and str(data.get('service') or '') == 'apervia-mcp-client'
    except Exception:
        return False


def _mcp_client_stop_owned_bridge() -> None:
    global _MCP_CLIENT_BRIDGE_PROCESS
    process = _MCP_CLIENT_BRIDGE_PROCESS
    _MCP_CLIENT_BRIDGE_PROCESS = None
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)
    except Exception:
        try:
            if process.poll() is None:
                process.kill()
        except Exception:
            pass


def _mcp_client_ensure_bridge() -> None:
    """按需启动回环 bridge；共享密钥只保留在当前进程及其子进程内。"""
    global _MCP_CLIENT_BRIDGE_PROCESS, _MCP_CLIENT_BRIDGE_ATEXIT_BOUND
    base = _mcp_client_bridge_base_url()
    if not re.match(r'^http://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?$', base, re.I):
        raise RuntimeError('APP3_MCP_BRIDGE_URL 必须使用回环地址')
    secret = _mcp_client_bridge_secret()
    if _mcp_client_bridge_healthy(base):
        if len(secret) < 32:
            raise RuntimeError('MCP bridge 已在运行，但 app3 未配置对应共享密钥')
        return
    autostart = str(os.getenv('APP3_MCP_BRIDGE_AUTOSTART', '1') or '1').strip().lower() not in {'0', 'false', 'off', 'no'}
    if not autostart:
        raise RuntimeError('MCP bridge 未运行，且 APP3_MCP_BRIDGE_AUTOSTART 已关闭')
    with _MCP_CLIENT_BRIDGE_START_LOCK:
        if _mcp_client_bridge_healthy(base):
            if len(_mcp_client_bridge_secret()) < 32:
                raise RuntimeError('MCP bridge 已在运行，但 app3 未配置对应共享密钥')
            return
        if _MCP_CLIENT_BRIDGE_PROCESS is not None and _MCP_CLIENT_BRIDGE_PROCESS.poll() is None:
            raise RuntimeError('MCP bridge 正在启动但健康检查未通过')
        if len(secret) < 32:
            secret = secrets.token_urlsafe(48)
            os.environ['APP3_MCP_BRIDGE_SECRET'] = secret
        import atexit as _mcp_atexit
        import subprocess as _mcp_subprocess
        import sys as _mcp_sys
        root_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(root_dir, '.venv-mcp', 'Scripts', 'python.exe'),
            os.path.join(root_dir, '.venv-mcp', 'bin', 'python'),
        ]
        python_bin = next((path for path in candidates if os.path.isfile(path)), _mcp_sys.executable)
        parsed = _mcp_urlsplit(base)
        port = int(parsed.port or 8766)
        env = os.environ.copy()
        env['APP3_MCP_BRIDGE_SECRET'] = secret
        env['APP3_MCP_BRIDGE_PORT'] = str(port)
        env['APP3_MCP_PARENT_PID'] = str(os.getpid())
        creationflags = int(getattr(_mcp_subprocess, 'CREATE_NO_WINDOW', 0) or 0)
        _MCP_CLIENT_BRIDGE_PROCESS = _mcp_subprocess.Popen(
            [python_bin, '-m', 'mcp_client.bridge'],
            cwd=root_dir,
            env=env,
            stdin=_mcp_subprocess.DEVNULL,
            stdout=_mcp_subprocess.DEVNULL,
            stderr=_mcp_subprocess.DEVNULL,
            creationflags=creationflags,
        )
        if not _MCP_CLIENT_BRIDGE_ATEXIT_BOUND:
            _mcp_atexit.register(_mcp_client_stop_owned_bridge)
            _MCP_CLIENT_BRIDGE_ATEXIT_BOUND = True
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if _MCP_CLIENT_BRIDGE_PROCESS.poll() is not None:
                raise RuntimeError('MCP bridge 启动失败，请运行 mcp_client/install.sh --check')
            if _mcp_client_bridge_healthy(base):
                return
            time.sleep(0.1)
        _mcp_client_stop_owned_bridge()
        raise RuntimeError('MCP bridge 启动超时')


def _mcp_client_clean_id(value: str = '', fallback: str = 'server') -> str:
    clean = _MCP_CLIENT_NAME_RE.sub('_', str(value or '').strip()).strip('_')[:40]
    return clean or fallback


def _mcp_client_proxy_name(server_id: str, tool_name: str) -> str:
    raw = f'{server_id}\0{tool_name}'.encode('utf-8', errors='ignore')
    digest = hashlib.sha256(raw).hexdigest()[:10]
    server = _mcp_client_clean_id(server_id, 'server')[:18]
    tool = _mcp_client_clean_id(tool_name, 'tool')[:26]
    return f'{_MCP_CLIENT_PROXY_PREFIX}{server}_{tool}_{digest}'[:64]


def _mcp_client_tool_risk(name: str, annotations: dict) -> str:
    read_only = bool(annotations.get('readOnlyHint')) and not bool(annotations.get('destructiveHint'))
    if read_only:
        return 'read'
    if bool(annotations.get('destructiveHint')) or bool(annotations.get('openWorldHint')):
        return 'high'
    clean_name = str(name or '').strip()
    if _MCP_CLIENT_DANGEROUS_NAME_RE.search(clean_name):
        return 'high'
    return 'low'


def _mcp_client_normalize_tool(raw: dict | None = None) -> dict:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    name = str(row.get('name') or '').strip()[:200]
    schema = row.get('inputSchema') if isinstance(row.get('inputSchema'), dict) else row.get('input_schema')
    schema = dict(schema or {}) if isinstance(schema, dict) else {'type': 'object', 'properties': {}}
    if str(schema.get('type') or '') != 'object':
        schema = {'type': 'object', 'properties': {}, 'additionalProperties': True}
    annotations = dict(row.get('annotations') or {}) if isinstance(row.get('annotations'), dict) else {}
    read_only = bool(annotations.get('readOnlyHint')) and not bool(annotations.get('destructiveHint'))
    return {
        'name': name,
        'title': str(row.get('title') or name).strip()[:200],
        'description': str(row.get('description') or '').strip()[:4000],
        'inputSchema': schema,
        'annotations': annotations,
        'enabled': row.get('enabled') is not False,
        'read_only': read_only,
        'risk': _mcp_client_tool_risk(name, annotations),
    }


def _mcp_client_normalize_server(raw: dict | None = None, *, include_secret: bool = True) -> dict:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    server_id = _mcp_client_clean_id(row.get('id') or row.get('server_id') or row.get('name'), 'server')
    auth_type = str(row.get('auth_type') or 'oauth').strip().lower()
    if auth_type not in {'none', 'bearer', 'oauth'}:
        auth_type = 'oauth'
    transport = str(row.get('transport') or 'auto').strip().lower()
    if transport not in {'auto', 'streamable_http', 'sse'}:
        transport = 'auto'
    permission_mode = str(row.get('permission_mode') or 'allow_low_risk').strip().lower()
    if permission_mode not in _MCP_CLIENT_PERMISSION_MODES:
        permission_mode = 'allow_low_risk'
    tools = []
    for item in (row.get('tools') or []):
        tool = _mcp_client_normalize_tool(item)
        if tool.get('name'):
            tools.append(tool)
        if len(tools) >= 50:
            break
    enabled_tool_names = [tool['name'] for tool in tools if tool.get('enabled')]
    local_http_enabled = str(os.getenv('APP3_MCP_ALLOW_INSECURE_LOCAL', '') or '').strip().lower() in {'1', 'true', 'on', 'yes'}
    out = {
        'id': server_id,
        'name': str(row.get('name') or server_id).strip()[:120],
        'url': str(row.get('url') or row.get('server_url') or '').strip()[:2000],
        'enabled': bool(row.get('enabled', True)),
        'auth_type': auth_type,
        'transport': transport,
        'allow_insecure_local': local_http_enabled and bool(row.get('allow_insecure_local')),
        'permission_mode': permission_mode,
        'oauth_client_id': str(row.get('oauth_client_id') or 'apervia').strip()[:500] or 'apervia',
        'token_expires_at': max(0, int(row.get('token_expires_at') or 0)),
        'scanned_at': max(0, int(row.get('scanned_at') or 0)),
        'enabled_tool_names': enabled_tool_names,
        'tools': tools,
    }
    if include_secret:
        out['bearer_token'] = str(row.get('access_token') or row.get('bearer_token') or row.get('authorization') or '').strip()[:12000]
    return out


def _mcp_client_normalize_runtime_servers(value) -> list[dict]:
    """规范化后端账号目录加载的运行时快照，不接受浏览器请求配置。"""
    rows = value if isinstance(value, list) else []
    out = []
    seen = set()
    for raw in rows:
        server = _mcp_client_normalize_server(raw)
        if not server.get('enabled') or not server.get('url') or server['id'] in seen:
            continue
        if server.get('auth_type') in {'oauth', 'bearer'} and not server.get('bearer_token'):
            continue
        seen.add(server['id'])
        out.append(server)
        if len(out) >= _MCP_CLIENT_MAX_SERVERS:
            break
    return out


def _mcp_client_signed_headers(method: str, path: str, body: bytes) -> dict:
    secret = _mcp_client_bridge_secret()
    if len(secret) < 32:
        raise RuntimeError('APP3_MCP_BRIDGE_SECRET 未配置或长度不足 32 个字符')
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    return {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'X-App3-Mcp-Timestamp': timestamp,
        'X-App3-Mcp-Nonce': nonce,
        'X-App3-Mcp-Signature': _mcp_bridge_sign_request(secret, method, path, timestamp, nonce, body),
    }


def _mcp_client_bridge_request(path: str, payload: dict, *, timeout: float = 45.0) -> dict:
    base = _mcp_client_bridge_base_url()
    _mcp_client_ensure_bridge()
    body = json.dumps(payload or {}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    headers = _mcp_client_signed_headers('POST', path, body)
    response = requests.post(
        base + path,
        data=body,
        headers=headers,
        timeout=max(5.0, min(float(timeout), 120.0)),
        allow_redirects=False,
    )
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(f'MCP bridge 返回了无效 JSON：HTTP {response.status_code}') from exc
    if response.status_code >= 400 or not bool(data.get('ok')):
        raise RuntimeError(str(data.get('message') or data.get('error') or f'MCP bridge HTTP {response.status_code}'))
    return dict(data)


def _mcp_client_build_runtime(servers) -> dict:
    normalized = _mcp_client_normalize_runtime_servers(servers)
    registry = {}
    chat_specs = []
    responses_specs = []
    for server in normalized:
        for tool in server.get('tools') or []:
            if not tool.get('enabled'):
                continue
            proxy_name = _mcp_client_proxy_name(server['id'], tool['name'])
            if proxy_name in registry:
                continue
            risk_text = {'read': '只读', 'low': '低风险操作', 'high': '高风险操作'}.get(tool.get('risk'), '需确认')
            description = f"[MCP: {server['name']} · {risk_text}] {tool.get('description') or tool['name']}"[:4000]
            parameters = dict(tool.get('inputSchema') or {'type': 'object', 'properties': {}})
            registry[proxy_name] = {'server': server, 'tool': tool}
            chat_specs.append({
                'type': 'function',
                'function': {'name': proxy_name, 'description': description, 'parameters': parameters},
            })
            responses_specs.append({
                'type': 'function',
                'name': proxy_name,
                'description': description,
                'parameters': parameters,
            })
            if len(registry) >= _MCP_CLIENT_MAX_TOOLS:
                break
        if len(registry) >= _MCP_CLIENT_MAX_TOOLS:
            break
    return {'servers': normalized, 'registry': registry, 'chat_specs': chat_specs, 'responses_specs': responses_specs}


def _mcp_client_attach_runtime(client_override=None, servers=None) -> dict:
    runtime = _mcp_client_build_runtime(servers)
    if client_override is not None:
        try:
            setattr(client_override, '_webai_mcp_client_runtime', runtime)
        except Exception:
            pass
    return runtime


def _mcp_client_runtime(client_override=None) -> dict:
    try:
        value = getattr(client_override, '_webai_mcp_client_runtime', None)
    except Exception:
        value = None
    return dict(value or {}) if isinstance(value, dict) else {}


def _mcp_client_chat_tool_specs(client_override=None) -> list[dict]:
    return [dict(item) for item in (_mcp_client_runtime(client_override).get('chat_specs') or []) if isinstance(item, dict)]


def _mcp_client_responses_tool_specs(client_override=None) -> list[dict]:
    return [dict(item) for item in (_mcp_client_runtime(client_override).get('responses_specs') or []) if isinstance(item, dict)]


def _mcp_client_is_proxy_tool(name: str = '') -> bool:
    return str(name or '').startswith(_MCP_CLIENT_PROXY_PREFIX)


def _mcp_client_requires_approval(server: dict, tool: dict) -> bool:
    mode = str(server.get('permission_mode') or 'allow_low_risk')
    risk = str(tool.get('risk') or 'high')
    if mode == 'allow_all':
        return False
    if mode == 'always_ask':
        return True
    if mode == 'allow_read':
        return risk != 'read'
    return risk == 'high'


def _mcp_client_safe_arguments(value, *, depth: int = 0):
    if depth > 4:
        return '[内容过深，已省略]'
    if isinstance(value, dict):
        out = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 30:
                out['…'] = '其余字段已省略'
                break
            key_text = str(key or '')[:100]
            if re.search(r'(?:password|secret|token|authorization|credential|api[_-]?key)', key_text, re.I):
                out[key_text] = '[已隐藏]'
            else:
                out[key_text] = _mcp_client_safe_arguments(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_mcp_client_safe_arguments(item, depth=depth + 1) for item in value[:30]]
    if isinstance(value, str):
        return value[:1000] + ('…' if len(value) > 1000 else '')
    return value if isinstance(value, (int, float, bool)) or value is None else str(value)[:500]


def _mcp_client_audit(event: str, server: dict, tool: dict, **extra) -> None:
    job_id = ''
    try:
        job_id = str(_chat_async_current_job_id() or '')
    except Exception:
        job_id = ''
    if job_id:
        try:
            _chat_async_append_event(job_id, 'mcp_tool_audit', {
                'action': str(event or ''),
                'server_id': str(server.get('id') or ''),
                'server_name': str(server.get('name') or ''),
                'tool_name': str(tool.get('name') or ''),
                'tool_title': str(tool.get('title') or tool.get('name') or ''),
                'tool_description': str(tool.get('description') or '')[:2000],
                'risk': str(tool.get('risk') or 'high'),
                **extra,
            })
        except Exception:
            pass


def _mcp_client_call_proxy_tool(name: str, args: dict | None = None, *, client_override=None) -> dict:
    entry = (_mcp_client_runtime(client_override).get('registry') or {}).get(str(name or ''))
    if not isinstance(entry, dict):
        return {'ok': False, 'error': 'mcp_tool_not_registered'}
    server = dict(entry.get('server') or {})
    tool = dict(entry.get('tool') or {})
    arguments = dict(args or {}) if isinstance(args, dict) else {}
    activity_id = 'mcp_' + secrets.token_urlsafe(18)
    permission_granted = not _mcp_client_requires_approval(server, tool)
    if not permission_granted:
        waiter = globals().get('_chat_async_wait_mcp_approval')
        if not callable(waiter):
            return {'ok': False, 'error': 'mcp_tool_permission_required', 'message': '当前调用不在可交互审批的异步任务中，已拒绝执行。'}
        decision = waiter(
            request_id=activity_id,
            server=server,
            tool=tool,
            arguments=_mcp_client_safe_arguments(arguments),
        )
        decision_name = str((decision or {}).get('decision') or 'deny')
        user_request = str((decision or {}).get('user_request') or '')[:2000]
        permission_granted = isinstance(decision, dict) and decision_name in {'allow_once', 'always_allow'}
        _mcp_client_audit('approval_decision', server, tool, activity_id=activity_id, request_id=activity_id, decision=decision_name, user_request=user_request)
        if decision_name == 'revise':
            return {
                'ok': False,
                'error': 'mcp_tool_revision_requested',
                'message': '用户要求根据附加要求调整本次 MCP 工具调用后重试。',
                'user_request': user_request,
                'retryable': True,
            }
        if not permission_granted:
            return {'ok': False, 'error': 'mcp_tool_denied', 'message': '用户未批准此 MCP 工具调用。'}
    try:
        _mcp_client_audit('call_started', server, tool, activity_id=activity_id, request_id=activity_id, arguments=_mcp_client_safe_arguments(arguments))
        payload = _mcp_client_bridge_request('/internal/call', {
            'server': server,
            'tool_name': str(tool.get('name') or ''),
            'arguments': arguments,
            'permission_granted': bool(permission_granted),
        })
        result = payload.get('result')
        _mcp_client_audit(
            'call_completed',
            server,
            tool,
            activity_id=activity_id,
            request_id=activity_id,
            ok=bool((result or {}).get('ok', True)) if isinstance(result, dict) else True,
            result_preview=_mcp_client_safe_arguments(result),
        )
        return dict(result) if isinstance(result, dict) else {'ok': True, 'result': result}
    except Exception as exc:
        app_logger.warning('[MCP_CLIENT_CALL_FAILED] server=%s tool=%s error=%s', server.get('id'), tool.get('name'), type(exc).__name__)
        _mcp_client_audit('call_failed', server, tool, activity_id=activity_id, request_id=activity_id, error_type=type(exc).__name__, message=str(exc)[:1000])
        return {'ok': False, 'error': 'mcp_tool_call_failed', 'message': str(exc)[:1000]}


def _mcp_client_request_principal() -> str:
    require_email = globals().get('_require_logged_in_email')
    if callable(require_email):
        try:
            email, error = require_email()
            if not error and str(email or '').strip():
                return str(email or '').strip().lower()
        except Exception:
            pass
    try:
        email = str(_current_login_email() or '').strip().lower()
    except Exception:
        email = ''
    return email


def _mcp_client_login_required_response():
    if not _mcp_client_request_principal():
        return jsonify({'ok': False, 'error': 'login_required', 'message': '请先登录 Apervia。'}), 401
    return None


_exec_split_file('app3_parts/mcp/server_store_part.py')


def _mcp_client_oauth_cleanup() -> None:
    cutoff = time.time()
    with _MCP_CLIENT_OAUTH_LOCK:
        expired = [state for state, row in _MCP_CLIENT_OAUTH_PENDING.items() if float((row or {}).get('expires_at') or 0) <= cutoff]
        for state in expired:
            _MCP_CLIENT_OAUTH_PENDING.pop(state, None)
        completed_expired = [state for state, row in _MCP_CLIENT_OAUTH_COMPLETED.items() if float((row or {}).get('expires_at') or 0) <= cutoff]
        for state in completed_expired:
            _MCP_CLIENT_OAUTH_COMPLETED.pop(state, None)


@app.post('/api3/mcp/oauth/start')
def _mcp_client_oauth_start_route():
    login_error = _mcp_client_login_required_response()
    if login_error:
        return login_error
    data = request.get_json(force=False, silent=True) or {}
    server_id = _mcp_client_clean_id((data or {}).get('server_id') if isinstance(data, dict) else '', '')
    owner_principal = _mcp_client_request_principal()
    server = _mcp_client_server_for_owner(owner_principal, server_id, include_secret=True)
    if not server:
        return jsonify({'ok': False, 'error': 'mcp_server_not_found', 'message': '请先保存 MCP 服务器。'}), 404
    if str(server.get('auth_type') or '') != 'oauth':
        return jsonify({'ok': False, 'error': 'mcp_oauth_not_configured', 'message': '该服务器未配置 OAuth。'}), 400
    try:
        discovered = _mcp_client_bridge_request('/internal/oauth/discover', {'server': server}, timeout=35.0)
        oauth = dict(discovered.get('oauth') or {})
        authorization_endpoint = str(oauth.get('authorization_endpoint') or '').strip()
        token_endpoint = str(oauth.get('token_endpoint') or '').strip()
        if not authorization_endpoint or not token_endpoint:
            raise RuntimeError('MCP 服务器未提供完整 OAuth 元数据')
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = __import__('base64').urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
        callback_url = _app_external_url('/api3/mcp/oauth/callback')
        client_id = str(server.get('oauth_client_id') or 'apervia').strip()[:500] or 'apervia'
        client_secret = str(server.get('oauth_client_secret') or '').strip()[:4000]
        pending = {
            'state': state,
            'owner_principal': owner_principal,
            'server': server,
            'client_id': client_id,
            'client_secret': client_secret,
            'code_verifier': verifier,
            'redirect_uri': callback_url,
            'token_endpoint': token_endpoint,
            'resource': str(oauth.get('resource') or '').strip(),
            'oauth': oauth,
            'expires_at': time.time() + 600,
        }
        _mcp_client_oauth_cleanup()
        with _MCP_CLIENT_OAUTH_LOCK:
            _MCP_CLIENT_OAUTH_PENDING[state] = pending
        query = {
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': callback_url,
            'state': state,
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
        }
        scopes = oauth.get('scopes_supported') if isinstance(oauth.get('scopes_supported'), list) else []
        if scopes:
            query['scope'] = ' '.join(str(item) for item in scopes if str(item).strip())
        resource = str(oauth.get('resource') or '').strip()
        if resource:
            query['resource'] = resource
        return jsonify({
            'ok': True,
            'authorization_url': authorization_endpoint + ('&' if '?' in authorization_endpoint else '?') + _mcp_urlencode(query),
            'state': state,
            'oauth': {key: value for key, value in oauth.items() if key not in {'access_token', 'refresh_token'}},
        })
    except Exception as exc:
        app_logger.warning('[MCP_OAUTH_START_FAILED] server=%s error=%s', server.get('id'), type(exc).__name__)
        return jsonify({'ok': False, 'error': 'mcp_oauth_start_failed', 'message': str(exc)[:1000]}), 502


@app.get('/api3/mcp/oauth/callback')
def _mcp_client_oauth_callback_route():
    state = str(request.args.get('state') or '').strip()
    code = str(request.args.get('code') or '').strip()
    remote_error = str(request.args.get('error_description') or request.args.get('error') or '').strip()
    with _MCP_CLIENT_OAUTH_LOCK:
        pending_row = _MCP_CLIENT_OAUTH_PENDING.get(state) if state else None
        if isinstance(pending_row, dict) and not bool(pending_row.get('_callback_processing')):
            pending_row['_callback_processing'] = True
            pending = dict(pending_row)
        else:
            pending = None
    result = {'type': 'apervia:mcp-oauth', 'ok': False, 'state': state}
    status_text = 'MCP authorization failed. You can close this window.'
    status_key = 'settings.mcp.oauth_failed_page'
    try:
        if not isinstance(pending, dict) or float(pending.get('expires_at') or 0) <= time.time():
            raise RuntimeError('OAuth state 无效或已过期')
        current_principal = _mcp_client_request_principal()
        if not current_principal or current_principal != str(pending.get('owner_principal') or ''):
            raise RuntimeError('OAuth 登录用户不匹配')
        if remote_error:
            raise RuntimeError(remote_error)
        if not code:
            raise RuntimeError('OAuth 回调缺少授权码')
        exchanged = _mcp_client_bridge_request('/internal/oauth/exchange', {
            'server': pending.get('server'),
            'token_endpoint': pending.get('token_endpoint'),
            'resource': pending.get('resource'),
            'client_id': pending.get('client_id'),
            'client_secret': pending.get('client_secret'),
            'code': code,
            'redirect_uri': pending.get('redirect_uri'),
            'code_verifier': pending.get('code_verifier'),
        }, timeout=40.0)
        tokens = dict(exchanged.get('tokens') or {})
        if not str(tokens.get('access_token') or '').strip():
            raise RuntimeError('MCP OAuth 令牌响应缺少 access_token')
        expires_in = max(0, int(tokens.get('expires_in') or 0))
        stored_server = dict(pending.get('server') or {})
        stored_server['auth_type'] = 'oauth'
        stored_server['token_expires_at'] = int(time.time()) + expires_in if expires_in else 0
        saved_server = _MCP_SERVER_STORE.upsert(
            str(pending.get('owner_principal') or ''),
            stored_server,
            secret_update={
                'access_token': str(tokens.get('access_token') or ''),
                'refresh_token': str(tokens.get('refresh_token') or ''),
                'oauth_client_secret': str(pending.get('client_secret') or ''),
            },
            preserve_secret=False,
        )
        result.update({
            'ok': True,
            'server_id': str((pending.get('server') or {}).get('id') or ''),
            'server': _mcp_client_public_server(saved_server, credential_configured=bool(tokens.get('access_token'))),
        })
        status_text = 'MCP authorized. Returning to Apervia…'
        status_key = 'settings.mcp.oauth_success_page'
    except Exception as exc:
        result['message'] = str(exc)[:1000]
        app_logger.warning('[MCP_OAUTH_CALLBACK_FAILED] error=%s', type(exc).__name__)
    if state and isinstance(pending, dict):
        with _MCP_CLIENT_OAUTH_LOCK:
            _MCP_CLIENT_OAUTH_PENDING.pop(state, None)
            _MCP_CLIENT_OAUTH_COMPLETED[state] = {
                'owner_principal': str(pending.get('owner_principal') or ''),
                'result': dict(result),
                'expires_at': time.time() + 120,
            }
    payload_json = json.dumps(result, ensure_ascii=False).replace('</', '<\\/')
    origin_json = json.dumps(_app_external_origin(), ensure_ascii=False)
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>MCP authorization · Apervia</title></head>
<body style="font-family:system-ui,sans-serif;padding:48px;text-align:center"><h2 data-i18n="{status_key}">{status_text}</h2>
<script src="/static/shared/i18n.js"></script><script src="/static/i18n/en.js"></script><script src="/static/i18n/zh-CN.js"></script><script src="/static/i18n/en-phrases.js"></script><script>window.AperviaI18n?.start();const payload={payload_json};const target={origin_json};if(window.opener){{window.opener.postMessage(payload,target);setTimeout(()=>window.close(),500);}}</script>
</body></html>'''
    return Response(page, status=200, content_type='text/html; charset=utf-8', headers={'Cache-Control': 'no-store'})


@app.get('/api3/mcp/oauth/result')
def _mcp_client_oauth_result_route():
    login_error = _mcp_client_login_required_response()
    if login_error:
        return login_error
    state = str(request.args.get('state') or '').strip()
    if not state:
        return jsonify({'ok': False, 'error': 'mcp_oauth_state_required'}), 400
    _mcp_client_oauth_cleanup()
    principal = _mcp_client_request_principal()
    with _MCP_CLIENT_OAUTH_LOCK:
        completed = _MCP_CLIENT_OAUTH_COMPLETED.get(state)
        pending = _MCP_CLIENT_OAUTH_PENDING.get(state)
        owner = str(((completed or pending) or {}).get('owner_principal') or '')
        if owner and owner != principal:
            return jsonify({'ok': False, 'error': 'mcp_oauth_owner_mismatch'}), 403
        if isinstance(completed, dict):
            row = _MCP_CLIENT_OAUTH_COMPLETED.pop(state, None) or completed
            return jsonify({'ok': True, 'pending': False, 'result': dict(row.get('result') or {})})
        if isinstance(pending, dict):
            return jsonify({'ok': True, 'pending': True})
    return jsonify({'ok': False, 'error': 'mcp_oauth_state_not_found'}), 404


@app.post('/api3/mcp/scan')
def _mcp_client_scan_route():
    login_error = _mcp_client_login_required_response()
    if login_error:
        return login_error
    data = request.get_json(force=False, silent=True) or {}
    server_id = _mcp_client_clean_id(data.get('server_id') if isinstance(data, dict) else '', '')
    owner = _mcp_client_request_principal()
    server = _mcp_client_server_for_owner(owner, server_id, include_secret=True)
    if not server:
        return jsonify({'ok': False, 'error': 'mcp_server_not_found', 'message': '请先保存 MCP 服务器。'}), 404
    if str(server.get('auth_type') or '') in {'oauth', 'bearer'} and not str(server.get('bearer_token') or ''):
        return jsonify({'ok': False, 'error': 'mcp_credential_required', 'message': '请先配置或完成 MCP 授权。'}), 400
    try:
        payload = _mcp_client_bridge_request('/internal/list', {'server': server}, timeout=35.0)
        tools = [_mcp_client_normalize_tool(item) for item in (payload.get('tools') or []) if isinstance(item, dict)]
        server['tools'] = tools
        server['scanned_at'] = int(time.time() * 1000)
        saved = _MCP_SERVER_STORE.upsert(owner, server, preserve_secret=True)
        public = _mcp_client_public_server(saved, credential_configured=bool(server.get('_credential_configured')))
        return jsonify({'ok': True, 'server': public, 'tools': public.get('tools') or []})
    except Exception as exc:
        app_logger.warning('[MCP_CLIENT_SCAN_FAILED] server=%s error=%s', server.get('id'), type(exc).__name__)
        return jsonify({'ok': False, 'error': 'mcp_scan_failed', 'message': str(exc)[:1000]}), 502
