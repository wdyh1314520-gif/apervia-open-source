# Docker Web 认证的请求上下文基础层。
# 这里只保留客户端 IP、本机管理请求识别、服务端会话标识和统一登录门禁路径判断。


def _auth_session_short_id(session_key: str) -> str:
    raw = str(session_key or '').strip()
    return raw[:8] if raw else ''


def _auth_current_session_key() -> str:
    try:
        token_hash = str(_auth_identity_token_hash() or '').strip()
    except Exception:
        token_hash = ''
    if not token_hash:
        return ''
    return hashlib.sha256(f'auth-session:{token_hash}'.encode('utf-8')).hexdigest()


def _client_ip() -> str:
    def _clean_ip_header_value(value: str = '') -> str:
        raw = str(value or '').strip().strip('"').strip("'")
        if not raw:
            return ''
        if raw.startswith('[') and ']' in raw:
            raw = raw.split(']', 1)[0].strip('[]')
        elif raw.count(':') == 1 and raw.rsplit(':', 1)[-1].isdigit():
            raw = raw.rsplit(':', 1)[0].strip()
        return raw

    def _ip_publicness(value: str = '') -> tuple[str, bool]:
        ip = _clean_ip_header_value(value)
        if not ip:
            return '', False
        try:
            ip_obj = ipaddress.ip_address(ip)
            is_public = not bool(ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast or ip_obj.is_unspecified)
            return str(ip_obj), is_public
        except Exception:
            return ip[:96], False

    try:
        headers = request.headers
        candidates: list[str] = []
        for name in ('CF-Connecting-IP', 'True-Client-IP', 'X-Real-IP', 'X-Real-Ip'):
            raw = str(headers.get(name) or '').strip()
            if raw:
                candidates.append(raw)
        for name in ('X-Forwarded-For', 'Forwarded'):
            raw = str(headers.get(name) or '').strip()
            if not raw:
                continue
            if name == 'Forwarded':
                for part in raw.split(','):
                    match = re.search(r'(?i)(?:^|;)\s*for=\s*("?\[?[^;,"]+\]?"?)', part)
                    if match:
                        candidates.append(match.group(1))
            else:
                candidates.extend([item.strip() for item in raw.split(',') if item.strip()])
        first_valid = ''
        for item in candidates:
            ip, is_public = _ip_publicness(item)
            if ip and not first_valid:
                first_valid = ip
            if ip and is_public:
                return ip
        if first_valid:
            return first_valid
        ip, _is_public = _ip_publicness(str(request.remote_addr or '').strip())
        return ip
    except Exception:
        try:
            return str(request.remote_addr or '').strip()
        except Exception:
            return ''


def _auth_clean_ip_for_display(value: str = '') -> str:
    raw = str(value or '').strip().strip('"').strip("'")
    if not raw:
        return ''
    if raw.startswith('[') and ']' in raw:
        raw = raw.split(']', 1)[0].strip('[]')
    elif raw.count(':') == 1 and raw.rsplit(':', 1)[-1].isdigit():
        raw = raw.rsplit(':', 1)[0].strip()
    return raw


def _auth_ip_publicness(value: str = '') -> tuple[str, bool, bool]:
    ip = _auth_clean_ip_for_display(value)
    if not ip:
        return '', False, False
    try:
        ip_obj = ipaddress.ip_address(ip)
        is_localish = bool(ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast or ip_obj.is_unspecified)
        return str(ip_obj), not is_localish, is_localish
    except Exception:
        return ip[:96], False, False


def _auth_display_ip_with_active_fallback(primary: str = '', active_ip: str = '') -> str:
    ip, _is_public, is_localish = _auth_ip_publicness(primary)
    active, active_public, _active_localish = _auth_ip_publicness(active_ip)
    if ip and is_localish and active and active_public:
        return active
    return ip


def _request_host_name() -> str:
    try:
        host = str(request.host or '').strip().lower()
        if not host:
            return ''
        if host.startswith('['):
            return host.split(']')[0].strip('[]')
        return host.split(':', 1)[0]
    except Exception:
        return ''


def _local_admin_seen_public_proxy_context() -> bool:
    try:
        checker = globals().get('_request_has_public_proxy_context')
        if callable(checker) and bool(checker()):
            return True
    except Exception:
        pass
    try:
        headers = request.headers
    except Exception:
        return False
    for name in ('CF-Connecting-IP', 'CF-Ray', 'Cf-Connecting-Ip', 'Cf-Ray'):
        try:
            if str(headers.get(name) or '').strip():
                return True
        except Exception:
            pass
    for name in ('X-Forwarded-Host', 'X-Original-Host', 'X-Host'):
        try:
            raw = str(headers.get(name) or '').split(',', 1)[0].strip()
        except Exception:
            raw = ''
        if raw:
            try:
                host = raw.lower()
                if host.startswith('['):
                    host = host.split(']', 1)[0].strip('[]')
                host = host.split(':', 1)[0].strip()
                if host not in {'', '127.0.0.1', 'localhost', '::1'}:
                    return True
            except Exception:
                return True
    try:
        forwarded_proto = str(headers.get('X-Forwarded-Proto') or '').split(',', 1)[0].strip().lower()
        forwarded_for = str(headers.get('X-Forwarded-For') or '').strip()
        if forwarded_proto == 'https' and forwarded_for:
            return True
    except Exception:
        pass
    return False


def _is_local_admin_request() -> bool:
    try:
        if _local_admin_seen_public_proxy_context():
            return False
        host = _request_host_name()
        if host in {'127.0.0.1', 'localhost', '::1'}:
            return True
        remote_ip = str(request.remote_addr or '').strip()
        if remote_ip in {'127.0.0.1', '::1'} and host in {'', '127.0.0.1', 'localhost', '::1'}:
            return True
    except Exception:
        return False
    return False


def _auth_gate_exempt_path(path: str) -> bool:
    normalized = str(path or '').strip() or '/'
    if normalized in {
        '/admin', '/platform-admin', '/storage-admin', '/login',
        '/api3/auth/status', '/api3/auth/me', '/api3/auth/logout',
        '/api3/auth/register', '/api3/auth/password-login',
        '/api3/remote-image', '/api3/image_proxy',
        '/api3/image-generation/mirror-status', '/api3/source-favicon',
        '/api3/health/live', '/api3/health/ready', '/favicon.ico',
    }:
        return True
    if normalized.startswith('/static/') or normalized.startswith('/legal/') or normalized.startswith('/share/'):
        return True
    if normalized.startswith('/api3/admin/'):
        return True
    if normalized.startswith('/api3/storage-admin') or normalized.startswith('/api3/platform-admin') or normalized.startswith('/api3/auth/'):
        return True
    return normalized.startswith((
        '/api3/uploads/', '/api3/download/', '/api3/uploads-id/', '/api3/download-id/',
        '/api3/generated-files/', '/api3/generated-download/',
        '/api3/generated-files-id/', '/api3/generated-download-id/',
    ))
