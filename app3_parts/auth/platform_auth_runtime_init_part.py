# 认证状态初始化与请求生命周期。

_email_login_load()
_local_admin_load()
_auth_invite_codes_load()
_auth_users_load()
_auth_account_delete_log_load()
_auth_start_account_delete_sweeper()
_auth_chat_store_load()
_auth_account_profiles_load()
_auth_identity_init()
_platform_release_announcement_init()
_rate_limit_load()


@app.before_request
def _auth_session_gate_before_request():
    """Docker Web 请求统一使用服务端身份会话。"""
    path = str(request.path or '/')
    if request.method == 'OPTIONS' or _auth_gate_exempt_path(path):
        return None
    user = _auth_identity_current_user()
    if user:
        return None
    if path.startswith('/api3/'):
        return _json_no_store({
            'error': 'login_required',
            'message': '请先登录',
            'login_required': True,
            'login_url': '/login',
        }, 401)
    target = str(request.full_path or request.path or '/')
    if target.endswith('?'):
        target = target[:-1]
    return redirect('/login?' + urllib.parse.urlencode({'next': target}), code=302)
