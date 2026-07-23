# 统一后台页面守卫。
# 旧本地口令解锁页和设备授权页已删除，所有后台入口都依赖统一用户会话与 admin 角色。


def _local_admin_html_response(html_text: str) -> Response:
    resp = Response(html_text, mimetype='text/html; charset=utf-8')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.headers['X-Frame-Options'] = 'DENY'
    return resp


def _device_admin_html_response():
    return redirect('/admin', code=302)


def _local_admin_page_guard(target_path: str, panel_label: str):
    user = _auth_identity_current_user()
    if not user:
        safe_target = str(target_path or '/admin').strip() or '/admin'
        return redirect('/login?' + urllib.parse.urlencode({'next': safe_target}), code=302)
    if str(user.get('role') or '') != 'admin':
        return Response('需要管理员权限', status=403, mimetype='text/plain; charset=utf-8')
    return None


def _local_admin_restricted_path(path: str = '') -> bool:
    p = str(path or '').split('?', 1)[0].strip() or '/'
    if p in {
        '/admin',
        '/storage-admin',
        '/platform-admin',
        '/blacklist-admin',
        '/rate-admin',
    }:
        return True
    if any(p.startswith(prefix) for prefix in (
        '/api3/local-admin/',
        '/api3/storage-admin/',
        '/api3/platform-admin/',
        '/api3/rate-limit/',
        '/api3/admin/',
    )):
        return True
    return p in {
        '/api3/auth/users',
        '/api3/auth/account-delete-logs',
        '/api3/auth/account-delete-logs-clear',
        '/api3/auth/user-restore-delete',
        '/api3/auth/finalize-account-deletions',
        '/api3/auth/invite-codes',
        '/api3/auth/invite-code-create',
        '/api3/auth/invite-code-create-batch',
        '/api3/auth/invite-code-revoke',
        '/api3/auth/invite-code-regenerate',
        '/api3/auth/invite-code-cleanup',
        '/api3/auth/user-toggle',
        '/api3/auth/user-private-search-toggle',
        '/api3/auth/blacklist',
        '/api3/auth/user-blacklist',
        '/api3/auth/config',
        '/api3/auth/disable',
    }


@app.before_request
def _local_admin_local_only_before_request():
    if request.method == 'OPTIONS':
        return None
    path = str(request.path or '')
    if not _local_admin_restricted_path(path):
        return None
    if path.startswith('/api3/local-admin/'):
        return jsonify({
            'error': 'legacy_admin_auth_removed',
            'message': '本地管理口令已移除，请使用管理员账号登录',
            'login_url': '/login',
            'admin_url': '/admin',
        }), 410
    guard = _auth_identity_admin_guard()
    if guard is None:
        return None
    if path.startswith('/api3/'):
        return guard
    return _local_admin_page_guard(path, '管理后台')
