# platform-admin API routes. The UI template lives in static/platform-admin.

@app.get('/platform-admin')
def platform_admin_page():
    gate = _admin_page_guard('/admin')
    if gate is not None:
        return gate
    return redirect('/admin', code=302)


@app.get('/api3/platform-admin/state')
def platform_admin_state_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    include_details = str(request.args.get('details') or '').strip().lower() in {'1', 'true', 'yes'}
    return jsonify(_platform_admin_state_payload(include_details=include_details))


@app.get('/api3/platform-admin/settings')
def platform_admin_settings_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    return jsonify(_platform_admin_settings_payload())


@app.get('/api3/platform-admin/python-packages')
def platform_admin_python_packages_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    force = str(request.args.get('force') or '').strip().lower() in {'1', 'true', 'yes'}
    return jsonify(_platform_admin_python_packages_payload(
        force_docker_check=force,
        force_inventory_check=force,
    ))


@app.post('/api3/platform-admin/python-packages/install')
def platform_admin_python_package_install_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    spec = str(data.get('spec') or data.get('package') or '').strip()
    try:
        return jsonify(_platform_admin_python_package_install(spec))
    except ValueError as exc:
        _platform_admin_audit_append('sandbox_python_package_install', spec, {'package': spec}, ok=False, error=str(exc))
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except RuntimeError as exc:
        _platform_admin_audit_append('sandbox_python_package_install', spec, {'package': spec}, ok=False, error=str(exc))
        return jsonify({'ok': False, 'error': str(exc)}), 503
    except Exception as exc:
        try:
            app_logger.exception('[platform_admin] sandbox_python_package_install_failed')
        except Exception:
            pass
        _platform_admin_audit_append('sandbox_python_package_install', spec, {'package': spec}, ok=False, error=f'{type(exc).__name__}: {exc}')
        return jsonify({'ok': False, 'error': f'{type(exc).__name__}: {exc}'}), 500


@app.get('/api3/platform-admin/app-logs')
def platform_admin_app_logs_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    return jsonify(_platform_admin_app_logs_payload(
        after_seq=_platform_admin_safe_int(request.args.get('after') or 0, 0, minimum=0, maximum=2_000_000_000),
        limit=_platform_admin_safe_int(request.args.get('limit') or 200, 200, minimum=10, maximum=500),
        level=str(request.args.get('level') or '').strip(),
        query=str(request.args.get('q') or request.args.get('query') or '').strip(),
    ))


@app.get('/api3/platform-admin/accounts')
def platform_admin_accounts_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    page, page_size = _platform_admin_page_args(default_page_size=40, max_page_size=200)
    return jsonify(_platform_admin_accounts_payload(
        query=str(request.args.get('q') or request.args.get('query') or '').strip(),
        status=str(request.args.get('status') or '').strip(),
        page=page,
        page_size=page_size,
    ))


@app.get('/api3/platform-admin/account-purge-preview')
def platform_admin_account_purge_preview_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    try:
        return jsonify(_platform_admin_guest_purge_preview(str(request.args.get('email') or '').strip()))
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] account_purge_preview_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.get('/api3/platform-admin/files')
def platform_admin_files_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    owner = str(request.args.get('owner') or '').strip()
    page, page_size = _platform_admin_page_args(default_page_size=40, max_page_size=200)
    orphan_page = _platform_admin_safe_int(request.args.get('orphan_page') or 1, 1, minimum=1, maximum=100000)
    orphan_page_size = _platform_admin_safe_int(request.args.get('orphan_page_size') or page_size, page_size, minimum=10, maximum=200)
    return jsonify(_platform_admin_files_payload(
        owner=owner,
        query=str(request.args.get('q') or request.args.get('query') or '').strip(),
        page=page,
        page_size=page_size,
        orphan_page=orphan_page,
        orphan_page_size=orphan_page_size,
    ))


@app.get('/api3/platform-admin/kb')
def platform_admin_kb_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    owner = str(request.args.get('owner') or '').strip()
    page, page_size = _platform_admin_page_args(default_page_size=50, max_page_size=200)
    return jsonify(_platform_admin_kb_docs_payload(
        owner=owner,
        query=str(request.args.get('q') or request.args.get('query') or '').strip(),
        page=page,
        page_size=page_size,
    ))


@app.post('/api3/platform-admin/file-library-sync')
def platform_admin_file_library_sync_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    payload = _platform_admin_file_library_sync_payload(force=bool(data.get('force', True)))
    status = 200 if payload.get('ok') else 400
    sync = payload.get('sync') if isinstance(payload.get('sync'), dict) else {}
    _platform_admin_audit_append('file_library_sync', 'file_library', {
        'ok': bool(payload.get('ok')),
        'scanned': sync.get('scanned'),
        'added': sync.get('added'),
        'updated_owner': sync.get('updated_owner'),
    }, ok=bool(payload.get('ok')), error=str(payload.get('error') or ''))
    return jsonify(payload), status


@app.post('/api3/platform-admin/migrate-legacy-files')
def platform_admin_migrate_legacy_files_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        payload = _platform_admin_migrate_legacy_files_payload(data)
        return jsonify(payload)
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] migrate_legacy_files_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.post('/api3/platform-admin/account-action')
def platform_admin_account_action_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        payload = _platform_admin_account_action(
            str(data.get('email') or '').strip(),
            str(data.get('action') or '').strip(),
            str(data.get('reason') or '').strip(),
            str(data.get('confirm_email') or '').strip(),
        )
        return jsonify(payload)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] account_action_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.get('/api3/platform-admin/account-detail')
def platform_admin_account_detail_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    try:
        owner = str(request.args.get('owner') or '').strip()
        page, page_size = _platform_admin_page_args(default_page_size=12, max_page_size=50)
        return jsonify(_platform_admin_account_detail_payload(
            owner,
            section=str(request.args.get('section') or '').strip(),
            page=page,
            page_size=page_size,
        ))
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] account_detail_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.get('/api3/platform-admin/chat-session')
def platform_admin_chat_session_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    try:
        return jsonify(_platform_admin_chat_session_payload(
            str(request.args.get('owner') or '').strip(),
            str(request.args.get('session_id') or request.args.get('id') or '').strip(),
            str(request.args.get('reason') or '').strip(),
        ))
    except ValueError as e:
        try:
            owner = _storage_quota_norm_owner(str(request.args.get('owner') or '').strip())
            sid = str(request.args.get('session_id') or request.args.get('id') or '').strip()
            if owner and sid:
                _platform_admin_audit_append('chat_session_view', f'{owner}:{sid}', {
                    'title': '',
                    'model': '',
                    'message_count': 0,
                    'deleted': False,
                    'reason': str(request.args.get('reason') or '').strip()[:240],
                }, ok=False, error=str(e))
        except Exception:
            pass
        status = 404 if isinstance(e, _PlatformAdminChatSessionNotFound) else 400
        return jsonify({'ok': False, 'error': str(e)}), status
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] chat_session_failed')
        except Exception:
            pass
        try:
            owner = _storage_quota_norm_owner(str(request.args.get('owner') or '').strip())
            sid = str(request.args.get('session_id') or request.args.get('id') or '').strip()
            if owner and sid:
                _platform_admin_audit_append('chat_session_view', f'{owner}:{sid}', {
                    'title': '',
                    'model': '',
                    'message_count': 0,
                    'deleted': False,
                    'reason': str(request.args.get('reason') or '').strip()[:240],
                }, ok=False, error=f'{type(e).__name__}: {e}')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.get('/api3/platform-admin/audit')
def platform_admin_audit_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    page, page_size = _platform_admin_page_args(default_page_size=50, max_page_size=200)
    target = str(request.args.get('target') or '').strip()
    return jsonify(_platform_admin_audit_payload(
        target=target,
        query=str(request.args.get('q') or request.args.get('query') or '').strip(),
        page=page,
        page_size=page_size,
    ))


@app.get('/api3/platform-admin/recycle')
def platform_admin_recycle_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    page, page_size = _platform_admin_page_args(default_page_size=50, max_page_size=200)
    return jsonify(_platform_admin_recycle_payload(
        query=str(request.args.get('q') or request.args.get('query') or '').strip(),
        page=page,
        page_size=page_size,
    ))


@app.get('/api3/platform-admin/backups')
def platform_admin_backups_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    page, page_size = _platform_admin_page_args(default_page_size=40, max_page_size=200)
    return jsonify(_platform_admin_backups_payload(
        query=str(request.args.get('q') or request.args.get('query') or '').strip(),
        page=page,
        page_size=page_size,
    ))


@app.post('/api3/platform-admin/backup-create')
def platform_admin_backup_create_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        payload = _platform_admin_create_backup(str(data.get('reason') or '').strip())
        payload['backups'] = _platform_admin_backups_payload(page=1, page_size=40)
        return jsonify(payload)
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] backup_create_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.post('/api3/platform-admin/backup-restore')
def platform_admin_backup_restore_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(_platform_admin_restore_backup(str(data.get('id') or data.get('backup_id') or '').strip()))
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] backup_restore_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.post('/api3/platform-admin/backup-delete')
def platform_admin_backup_delete_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(_platform_admin_backup_delete(str(data.get('id') or data.get('backup_id') or '').strip()))
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] backup_delete_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.post('/api3/platform-admin/backups-clear')
def platform_admin_backups_clear_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        payload = _platform_admin_backups_clear(str(data.get('q') or data.get('query') or '').strip())
        status = 200 if payload.get('ok') or payload.get('partial_ok') else 400
        return jsonify(payload), status
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] backups_clear_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.post('/api3/platform-admin/audit-clear')
def platform_admin_audit_clear_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(_platform_admin_audit_clear(
            query=str(data.get('q') or data.get('query') or '').strip(),
            target=str(data.get('target') or '').strip(),
        ))
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] audit_clear_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.post('/api3/platform-admin/recycle-clear')
def platform_admin_recycle_clear_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        payload = _platform_admin_recycle_purge_all(str(data.get('q') or data.get('query') or '').strip())
        status = 200 if payload.get('ok') or payload.get('partial_ok') else 400
        return jsonify(payload), status
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] recycle_clear_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.post('/api3/platform-admin/orphan-delete')
def platform_admin_orphan_delete_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        payload = _platform_admin_recycle_orphan_file(
            str(data.get('path') or '').strip(),
            str(data.get('reason') or '').strip(),
        )
        return jsonify(payload)
    except ValueError as e:
        _platform_admin_audit_append('orphan_file_recycle', str((data or {}).get('path') or ''), {'reason': str((data or {}).get('reason') or '')}, ok=False, error=str(e))
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] orphan_delete_failed')
        except Exception:
            pass
        _platform_admin_audit_append('orphan_file_recycle', str((data or {}).get('path') or ''), {'reason': str((data or {}).get('reason') or '')}, ok=False, error=f'{type(e).__name__}: {e}')
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.post('/api3/platform-admin/orphan-batch-delete')
def platform_admin_orphan_batch_delete_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        raw_paths = data.get('paths') if isinstance(data.get('paths'), list) else []
        payload = _platform_admin_recycle_orphan_files(
            [str(x or '').strip() for x in raw_paths],
            str(data.get('reason') or '').strip(),
            limit=_platform_admin_safe_int(data.get('limit') or 80, 80, minimum=1, maximum=200),
        )
        status = 200 if payload.get('ok') or payload.get('partial_ok') else 400
        return jsonify(payload), status
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] orphan_batch_delete_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500


@app.post('/api3/platform-admin/recycle-action')
def platform_admin_recycle_action_route():
    guard = _platform_admin_guard()
    if guard is not None:
        return guard
    data = request.get_json(force=True, silent=True) or {}
    try:
        payload = _platform_admin_recycle_action(
            str(data.get('id') or data.get('recycle_id') or '').strip(),
            str(data.get('action') or '').strip(),
        )
        return jsonify(payload)
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        try:
            app_logger.exception('[platform_admin] recycle_action_failed')
        except Exception:
            pass
        return jsonify({'ok': False, 'error': f'{type(e).__name__}: {e}'}), 500
