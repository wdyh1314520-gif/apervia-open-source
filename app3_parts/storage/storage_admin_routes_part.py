# 存储后台 API。页面统一收口到 /admin，鉴权统一使用 admin 角色。


def _storage_admin_guard():
    return _auth_identity_admin_guard()


@app.get('/storage-admin')
def storage_quota_admin_page():
    gate = _admin_page_guard('/admin')
    if gate is not None:
        return gate
    return redirect('/admin', code=302)


@app.get('/api3/storage-admin/state')
def storage_quota_admin_state_route():
    guard = _storage_admin_guard()
    if guard is not None:
        return guard
    return jsonify(_storage_quota_admin_state_payload())


@app.get('/api3/storage-admin/policy')
def storage_quota_admin_policy_route():
    guard = _storage_admin_guard()
    if guard is not None:
        return guard
    return jsonify(_storage_quota_policy_payload())


@app.post('/api3/storage-admin/policy')
def storage_quota_admin_policy_update_route():
    guard = _storage_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    reset_keys = data.get('reset_keys') or []
    if isinstance(reset_keys, str):
        reset_keys = [reset_keys]
    if not isinstance(reset_keys, list):
        return jsonify({'error': 'reset_keys 必须是数组'}), 400
    try:
        policy = _storage_quota_update_policy(
            data.get('limits'),
            reset_keys=reset_keys,
            reset_all=bool(data.get('reset_all')),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        app_logger.exception('[storage_quota] policy_update_failed')
        return jsonify({'error': f'保存存储配额策略失败：{exc}'}), 500
    return jsonify({'ok': True, 'policy': policy, 'state': _storage_quota_admin_state_payload()})


@app.post('/api3/storage-admin/account-limit')
def storage_quota_admin_account_limit_route():
    guard = _storage_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    owner = str(data.get('owner') or '').strip()
    try:
        item = _storage_quota_set_owner_limit_override(owner, int(data.get('limit_bytes') or 0), reset=bool(data.get('reset')))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'ok': True, 'account': item, 'state': _storage_quota_admin_state_payload()})


@app.post('/api3/storage-admin/cleanup')
def storage_quota_admin_cleanup_route():
    guard = _storage_admin_guard()
    if guard is not None:
        return guard
    detail = _storage_quota_cleanup('admin_manual_cleanup')
    payload = _storage_quota_admin_state_payload()
    payload['cleanup'] = detail
    return jsonify(payload)


@app.post('/api3/storage-admin/maintenance')
def storage_quota_admin_maintenance_route():
    guard = _storage_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    mode = str(data.get('mode') or 'safe').strip().lower()
    target = str(data.get('target') or 'chat_async_jobs').strip()
    if mode == 'deep':
        detail = _storage_quota_run_deep_maintenance(target=target, force=bool(data.get('force')))
        status = 200 if bool(detail.get('ok')) else (409 if detail.get('code') == 'not_idle' else 400)
    else:
        detail = _storage_quota_run_safe_maintenance()
        status = 200
    detail['freed_text'] = _storage_quota_human(int(detail.get('freed_bytes') or 0))
    payload = _storage_quota_admin_state_payload()
    payload['maintenance'] = dict(payload.get('maintenance') or {})
    payload['maintenance']['last_result'] = detail
    payload['maintenance']['freed_bytes'] = int(detail.get('freed_bytes') or 0)
    payload['maintenance']['freed_text'] = str(detail.get('freed_text') or _storage_quota_human(0))
    payload['maintenance_result'] = detail
    if status != 200:
        payload['ok'] = False
        payload['error'] = str(detail.get('error') or '维护失败')
        payload['code'] = str(detail.get('code') or 'maintenance_failed')
    return jsonify(payload), status


@app.post('/api3/storage-admin/migrate-legacy-files')
def storage_quota_admin_migrate_legacy_files_route():
    guard = _storage_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(_platform_admin_migrate_legacy_files_payload(data))
    except Exception as exc:
        app_logger.exception('[storage_admin] migrate_legacy_files_failed')
        return jsonify({'ok': False, 'error': f'{type(exc).__name__}: {exc}'}), 500


@app.get('/api3/storage/quota')
def storage_quota_status_route():
    owner = _storage_quota_owner_key()
    payload = _storage_quota_owner_public_payload(owner)
    try:
        used = max(0, int(payload.get('used_bytes') or 0))
        limit = max(0, int(payload.get('limit_bytes') or 0))
        payload['percent'] = round((used / float(limit)) * 100.0, 1) if limit > 0 else 0.0
        payload['categories'] = _storage_quota_owner_storage_space_categories(owner)
        payload['updated_at'] = time.time()
        payload['updated_at_text'] = _fmt_ts(payload['updated_at'])
    except Exception:
        pass
    try:
        user = _auth_identity_current_user()
        if user and str(user.get('role') or '') == 'admin':
            payload['app_used_bytes'] = _storage_quota_app_used_bytes()
            payload['app_limit_bytes'] = _storage_quota_int('APP_STORAGE_MAX_BYTES', 12 * 1024 * 1024 * 1024, minimum=1024 * 1024 * 1024)
            payload['app_used_text'] = _storage_quota_human(payload['app_used_bytes'])
            payload['app_limit_text'] = _storage_quota_human(payload['app_limit_bytes'])
            payload['disk_free_bytes'] = _storage_quota_disk_free(APP_DATA_DIR)
            payload['disk_free_text'] = _storage_quota_human(payload['disk_free_bytes'])
    except Exception:
        pass
    return jsonify({'ok': True, 'quota': payload})
