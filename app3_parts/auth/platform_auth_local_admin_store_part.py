# 后台守卫兼容层：旧路由名称继续调用这里，但实际授权只认统一身份库中的 admin 角色。

LOCAL_ADMIN_SCOPE = 'admin-system'


def _local_admin_load() -> None:
    return None


def _local_admin_has_grant(scope: str = LOCAL_ADMIN_SCOPE) -> bool:
    user = _auth_identity_current_user()
    return bool(user and str(user.get('role') or '') == 'admin')


def _require_admin_role():
    return _auth_identity_admin_guard()


def _require_local_admin_grant(scope: str = LOCAL_ADMIN_SCOPE):
    return _require_admin_role()
