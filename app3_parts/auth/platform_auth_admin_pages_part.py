"""Unified administrator page and API access guard."""

def _admin_html_response(html_text: str) -> Response:
    response = Response(html_text, mimetype='text/html; charset=utf-8')
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


def _admin_page_guard(target_path: str):
    user = _auth_identity_current_user()
    if not user:
        safe_target = str(target_path or '/admin').strip() or '/admin'
        return redirect('/login?' + urllib.parse.urlencode({'next': safe_target}), code=302)
    if str(user.get('role') or '') != 'admin':
        return Response('Administrator access required', status=403, mimetype='text/plain; charset=utf-8')
    return None


def _admin_restricted_path(path: str = '') -> bool:
    normalized = str(path or '').split('?', 1)[0].strip() or '/'
    if normalized in {'/admin', '/storage-admin', '/platform-admin'}:
        return True
    return any(normalized.startswith(prefix) for prefix in (
        '/api3/storage-admin/',
        '/api3/platform-admin/',
        '/api3/admin/',
    ))


@app.before_request
def _admin_access_before_request():
    if request.method == 'OPTIONS':
        return None
    path = str(request.path or '')
    if not _admin_restricted_path(path):
        return None
    guard = _auth_identity_admin_guard()
    if guard is None or path.startswith('/api3/'):
        return guard
    return _admin_page_guard(path)
