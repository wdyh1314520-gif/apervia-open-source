"""Current-account helpers shared by authenticated routes."""

def _current_login_email() -> str:
    identity_user = _auth_identity_current_user()
    return _normalize_login_email((identity_user or {}).get('email') or '')


def _current_login_account() -> dict:
    return _auth_identity_current_account()


def _require_logged_in_email():
    state = _current_login_account()
    if state.get('session_invalidated'):
        return '', (jsonify(state), 403)
    email = _normalize_login_email(state.get('email') or '')
    if not state.get('logged_in') or not email:
        return '', (jsonify({
            'error': 'login_required',
            'message': AUTH_LOGIN_DISABLED_MESSAGE,
            'login_required': True,
            'login_url': '/login',
        }), 401)
    return email, None
