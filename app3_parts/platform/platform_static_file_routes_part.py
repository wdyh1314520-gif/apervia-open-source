# Split from app3_parts/platform/platform_auth_part.py.
# Purpose: index/static aliases, upload/download, and generated-file routes.
# Loaded by app3.py via _exec_split_file(...), sharing the original global namespace.

APP3_STATIC_VERSION_PLACEHOLDER = '__APP3_STATIC_VERSION__'
APP3_STATIC_VERSION_BASE = 'frontend_20260710_v1'


def _index_static_asset_version() -> str:
    configured = str(os.getenv('APP3_STATIC_VERSION') or app_getenv('APP3_STATIC_VERSION', '') or '').strip()
    if configured:
        return re.sub(r'[^A-Za-z0-9_.-]+', '_', configured)[:80] or 'manual'
    roots = [
        os.path.join(STATIC_DIR, 'index3.html'),
        os.path.join(STATIC_DIR, 'index3', 'css'),
        os.path.join(STATIC_DIR, 'index3', 'js'),
    ]
    latest_ns = 0
    for root in roots:
        try:
            if os.path.isfile(root):
                latest_ns = max(latest_ns, int(os.stat(root).st_mtime_ns))
                continue
            if os.path.isdir(root):
                for dirpath, _dirnames, filenames in os.walk(root):
                    for name in filenames:
                        if not (name.endswith('.css') or name.endswith('.js')):
                            continue
                        path = os.path.join(dirpath, name)
                        latest_ns = max(latest_ns, int(os.stat(path).st_mtime_ns))
        except Exception:
            continue
    return APP3_STATIC_VERSION_BASE + '_' + str(latest_ns or int(time.time() * 1000))


def _prepare_index_html_response_text(html_text: str) -> str:
    text = str(html_text or '')
    if APP3_STATIC_VERSION_PLACEHOLDER not in text:
        return text
    return text.replace(APP3_STATIC_VERSION_PLACEHOLDER, _index_static_asset_version())


@app.get("/")
@app.get("/c/<path:session_id>")
@app.get("/temporary-chat")
@app.get("/settings")
@app.get("/settings/<path:settings_path>")
@app.get("/library")
@app.get("/library/<path:library_path>")
@app.get("/image-pullback")
def index_gpt(session_id: str = '', settings_path: str = '', library_path: str = ''):
    # Serve index without browser caching so local frontend edits take effect.
    index_path = os.path.join(STATIC_DIR, "index3.html")
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            html_text = f.read()
        html_text = _prepare_index_html_response_text(html_text)
        resp = Response(html_text, mimetype="text/html; charset=utf-8")
    except Exception:
        resp = send_from_directory(STATIC_DIR, "index3.html", max_age=0)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers['Expires'] = '0'
    return resp


def _webai_static_alias_response(primary: str = '', fallback: str = '', mimetype: str = ''):
    for rel in (primary, fallback):
        safe = str(rel or '').strip().replace('\\', '/')
        if not safe or safe.startswith('/') or '..' in safe.split('/'):
            continue
        path = os.path.join(STATIC_DIR, *[p for p in safe.split('/') if p])
        try:
            if os.path.isfile(path):
                resp = send_from_directory(os.path.dirname(path), os.path.basename(path), mimetype=(mimetype or None), max_age=0)
                resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                resp.headers['Pragma'] = 'no-cache'
                resp.headers['Expires'] = '0'
                return resp
        except Exception:
            continue
    return jsonify({'error': 'static_asset_not_found'}), 404


def _webai_static_alias_handler(primary: str = '', fallback: str = '', mimetype: str = ''):
    def _handler():
        return _webai_static_alias_response(primary, fallback, mimetype)
    _handler.__name__ = 'static_alias_' + re.sub(r'[^A-Za-z0-9_]+', '_', str(primary or fallback or 'asset')).strip('_')
    return _handler


def _webai_add_static_alias_route(route: str = '', endpoint: str = '', primary: str = '', fallback: str = '', mimetype: str = '') -> None:
    app.add_url_rule(
        str(route or ''),
        str(endpoint or ''),
        _webai_static_alias_handler(primary, fallback, mimetype),
        methods=['GET'],
    )


_WEBAI_STATIC_ALIAS_ROUTES = (
    ('/static/index3/css/index3.css', 'static_index3_css_alias', 'index3/css/index3.css', 'index3.css', 'text/css; charset=utf-8'),
    ('/static/index3/css/index3-overrides.css', 'static_index3_overrides_css_alias', 'index3/css/index3-overrides.css', 'index3-overrides.css', 'text/css; charset=utf-8'),
    ('/static/index3/js/index3.js', 'static_index3_js_alias', 'index3/js/index3.js', 'index3.js', 'application/javascript; charset=utf-8'),
)


for _route, _endpoint, _primary, _fallback, _mimetype in _WEBAI_STATIC_ALIAS_ROUTES:
    _webai_add_static_alias_route(_route, _endpoint, _primary, _fallback, _mimetype)


def _file_link_response_json(payload: dict, status: int = 403):
    resp = jsonify(payload)
    resp.status_code = int(status or 403)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


def _file_link_forbidden_response(filename: str = '', *, namespace: str = '', reason: str = 'file_access_denied'):
    safe = os.path.basename(str(filename or '').strip())
    payload = {
        'ok': False,
        'error': 'file_access_denied',
        'code': str(reason or 'file_access_denied'),
        'filename': safe,
        'namespace': str(namespace or '').strip(),
        'login_required': reason in {'login_required', 'file_owner_unknown'},
    }
    try:
        accepts = str(request.headers.get('Accept') or '')
        if 'text/html' in accepts and 'application/json' not in accepts:
            html = '<!doctype html><meta charset="utf-8"><title>文件不可访问</title><body style="font-family:system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;padding:32px;background:#f7f7f8;color:#111"><h2>文件不可访问</h2><p>请使用拥有该文件的账号登录后再打开链接。</p></body>'
            return Response(html, status=403, mimetype='text/html; charset=utf-8')
    except Exception:
        pass
    return _file_link_response_json(payload, 403)


def _file_link_current_owner_key() -> str:
    try:
        if callable(globals().get('_is_local_admin_request')) and _is_local_admin_request():
            return '__local_admin__'
    except Exception:
        pass
    for name in ('_file_library_owner_key', '_storage_quota_owner_key'):
        fn = globals().get(name)
        if callable(fn):
            try:
                key = str(fn() or '').strip().lower()
                if key:
                    return key
            except Exception:
                pass
    try:
        getter = globals().get('_current_login_account')
        if callable(getter):
            acc = getter() or {}
            email = str((acc or {}).get('email') or '').strip()
            normalizer = globals().get('_normalize_login_email')
            if email:
                return str(normalizer(email) if callable(normalizer) else email).strip().lower()
    except Exception:
        pass
    try:
        getter = globals().get('_current_login_email')
        if callable(getter):
            email = str(getter() or '').strip()
            normalizer = globals().get('_normalize_login_email')
            if email:
                return str(normalizer(email) if callable(normalizer) else email).strip().lower()
    except Exception:
        pass
    return 'anonymous'


def _file_link_owner_has_global_access(owner_key: str = '') -> bool:
    owner = str(owner_key or '').strip().lower()
    return owner == '__local_admin__'


def _file_link_record_allowed_for_owner(rec: dict | None = None, owner_key: str = '') -> bool:
    owner = str(owner_key or '').strip().lower()
    if _file_link_owner_has_global_access(owner):
        return True
    checker = globals().get('_file_library_record_allowed_for_owner')
    if callable(checker):
        try:
            return bool(checker(rec, owner))
        except Exception:
            pass
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    rec_owner = str(row.get('owner_key') or row.get('owner') or row.get('owner_email') or '').strip().lower()
    return bool(owner and owner != 'anonymous' and rec_owner and rec_owner == owner)


def _file_link_extract_url_filename(url: str = '') -> str:
    raw = str(url or '').strip()
    if not raw:
        return ''
    extractor = globals().get('_extract_saved_filename_from_url')
    if callable(extractor):
        try:
            found = str(extractor(raw) or '').strip()
            if found:
                return os.path.basename(found)
        except Exception:
            pass
    try:
        parsed = urllib.parse.urlparse(raw)
        return os.path.basename(urllib.parse.unquote(parsed.path or ''))
    except Exception:
        return ''


def _file_link_record_names(rec: dict | None = None) -> set[str]:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    out: set[str] = set()

    def add(value: str = '') -> None:
        name = os.path.basename(str(value or '').strip())
        if name:
            out.add(name.lower())

    for key in ('saved_filename', 'filename'):
        add(row.get(key) or '')
    for key in ('url', 'view_url', 'download_url', 'preview_url', 'preview_download_url', 'object_url'):
        add(_file_link_extract_url_filename(row.get(key) or ''))
    storage_ref = str(row.get('storage_ref') or '').strip()
    if storage_ref:
        add(storage_ref.rsplit('/', 1)[-1])
    return out


def _file_link_registry_records(namespace: str = '', filename: str = '', scope: str = '') -> list[dict]:
    safe_name = os.path.basename(str(filename or '').strip()).lower()
    if not safe_name:
        return []
    ns = str(namespace or '').strip().lower()
    try:
        normalized_scope = _normalize_upload_scope(scope) if scope else ''
    except Exception:
        normalized_scope = str(scope or '').strip().lower()

    snapshot = globals().get('_file_registry_files_snapshot')
    files = snapshot() if callable(snapshot) else {}

    rows: list[dict] = []
    for raw in files.values():
        if not isinstance(raw, dict):
            continue
        rec = dict(raw)
        rec_ns = str(rec.get('namespace') or '').strip().lower()
        rec_source = str(rec.get('source') or '').strip().lower()
        if ns == 'uploads':
            if rec_ns and rec_ns != 'uploads':
                continue
            if not rec_ns and rec_source not in {'upload', 'pullback'}:
                continue
        elif ns == 'generated':
            if rec_ns and rec_ns != 'generated':
                continue
            if not rec_ns and rec_source != 'generated':
                continue
        elif ns:
            if rec_ns != ns:
                continue
        try:
            rec_scope = _normalize_upload_scope(rec.get('scope') or '') if rec.get('scope') else ''
        except Exception:
            rec_scope = str(rec.get('scope') or '').strip().lower()
        if normalized_scope and rec_scope and rec_scope != normalized_scope:
            continue
        if safe_name not in _file_link_record_names(rec):
            continue
        rows.append(rec)
    rows.sort(key=lambda item: float((item or {}).get('updated_at') or (item or {}).get('created_at') or 0.0), reverse=True)
    return rows


def _file_link_registry_record_by_file_id(file_id: str = '', namespace: str = '', scope: str = '') -> dict:
    fid = str(file_id or '').strip()
    try:
        fid = urllib.parse.unquote(fid)
    except Exception:
        pass
    fid = fid.strip()
    if not fid or len(fid) > 240 or '/' in fid or '\\' in fid:
        return {}
    ns = str(namespace or '').strip().lower()
    try:
        normalized_scope = _normalize_upload_scope(scope) if scope else ''
    except Exception:
        normalized_scope = str(scope or '').strip().lower()

    snapshot = globals().get('_file_registry_files_snapshot')
    files = snapshot() if callable(snapshot) else {}

    rows: list[dict] = []
    for raw in files.values():
        if not isinstance(raw, dict):
            continue
        rec = dict(raw)
        rec_id = str(rec.get('file_id') or '').strip()
        if rec_id != fid:
            continue
        rec_ns = str(rec.get('namespace') or '').strip().lower()
        rec_source = str(rec.get('source') or '').strip().lower()
        if ns == 'generated':
            if rec_ns and rec_ns != 'generated':
                continue
            if not rec_ns and rec_source != 'generated':
                continue
        elif ns == 'uploads':
            if rec_ns and rec_ns != 'uploads':
                continue
            if not rec_ns and rec_source not in {'upload', 'pullback'}:
                continue
        elif ns:
            if rec_ns != ns:
                continue
        try:
            rec_scope = _normalize_upload_scope(rec.get('scope') or '') if rec.get('scope') else ''
        except Exception:
            rec_scope = str(rec.get('scope') or '').strip().lower()
        if normalized_scope and rec_scope and rec_scope != normalized_scope:
            continue
        rows.append(rec)
    rows.sort(key=lambda item: float((item or {}).get('updated_at') or (item or {}).get('created_at') or 0.0), reverse=True)
    return rows[0] if rows else {}


def _file_link_access_guard_for_record(rec: dict | None = None, *, namespace: str = 'generated'):
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    filename = os.path.basename(str(row.get('saved_filename') or row.get('filename') or row.get('file_id') or '').strip())
    owner = _file_link_current_owner_key()
    if _file_link_owner_has_global_access(owner):
        return None
    if not row:
        return _file_link_forbidden_response(filename, namespace=namespace, reason='file_owner_unknown')
    if _file_link_record_allowed_for_owner(row, owner):
        return None
    if owner in {'', 'anonymous'}:
        return _file_link_forbidden_response(filename, namespace=namespace, reason='login_required')
    return _file_link_forbidden_response(filename, namespace=namespace, reason='owner_mismatch')


def _file_link_resolver_for_namespace(namespace: str = ''):
    ns = str(namespace or '').strip().lower()
    if ns == 'generated':
        return _resolve_generated_file_dir
    if ns == 'uploads':
        return _resolve_uploaded_file_dir
    return None


def _file_link_send_record(namespace: str = '', rec: dict | None = None, *, as_attachment: bool = True):
    ns = str(namespace or '').strip().lower()
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    filename = os.path.basename(str(row.get('saved_filename') or row.get('filename') or '').strip())
    if not filename:
        return _expired_file_link_response(str(row.get('file_id') or ''), namespace=ns)
    scope = str(row.get('scope') or '').strip() or _request_upload_scope_for_access()
    resolver = _file_link_resolver_for_namespace(ns)
    base_dir = resolver(filename, scope=scope) if callable(resolver) else ''
    if not base_dir:
        obj_resp = _object_storage_file_response(ns, filename, scope, as_attachment=as_attachment)
        if obj_resp is not None:
            try:
                _object_storage_restore_to_local(ns, scope, filename)
            except Exception:
                pass
            return _file_link_harden_response(obj_resp, filename)
        return _expired_file_link_response(filename, namespace=ns)
    return _file_link_harden_response(send_from_directory(base_dir, filename, as_attachment=as_attachment or _file_link_should_force_download(filename)), filename)


def _file_link_record_by_id_response(file_id: str = '', namespace: str = '', *, as_attachment: bool = True):
    ns = str(namespace or '').strip().lower()
    preferred_scope = _request_upload_scope_for_access()
    rec = _file_link_registry_record_by_file_id(file_id, namespace=ns, scope=preferred_scope) or _file_link_registry_record_by_file_id(file_id, namespace=ns, scope='')
    denied = _file_link_access_guard_for_record(rec, namespace=ns)
    if denied is not None:
        return denied
    return _file_link_send_record(ns, rec, as_attachment=as_attachment)


def _file_link_named_file_response(filename: str = '', namespace: str = '', *, as_attachment: bool = True):
    ns = str(namespace or '').strip().lower()
    preferred_scope = _request_upload_scope_for_access()
    denied = _file_link_access_guard(ns, filename, preferred_scope)
    if denied is not None:
        return denied
    resolver = _file_link_resolver_for_namespace(ns)
    base_dir = resolver(filename, scope=preferred_scope) if callable(resolver) else ''
    if not base_dir:
        obj_resp = _object_storage_file_response(ns, filename, preferred_scope, as_attachment=as_attachment)
        if obj_resp is not None:
            try:
                _object_storage_restore_to_local(ns, preferred_scope, filename)
            except Exception:
                pass
            return _file_link_harden_response(obj_resp, filename)
        return _expired_file_link_response(filename, namespace=ns)
    return _file_link_harden_response(send_from_directory(base_dir, filename, as_attachment=as_attachment or _file_link_should_force_download(filename)), filename)


def _file_link_access_guard(namespace: str = '', filename: str = '', scope: str = ''):
    owner = _file_link_current_owner_key()
    if _file_link_owner_has_global_access(owner):
        return None
    records = _file_link_registry_records(namespace, filename, scope)
    if not records:
        return _file_link_forbidden_response(filename, namespace=namespace, reason='file_owner_unknown')
    for rec in records:
        if _file_link_record_allowed_for_owner(rec, owner):
            return None
    if owner in {'', 'anonymous'}:
        return _file_link_forbidden_response(filename, namespace=namespace, reason='login_required')
    return _file_link_forbidden_response(filename, namespace=namespace, reason='owner_mismatch')


@app.get("/api3/uploads/<path:filename>")
def api3_uploads(filename):
    return _file_link_named_file_response(filename, 'uploads', as_attachment=False)


@app.get("/api3/uploads-id/<path:file_id>")
def api3_uploads_by_id(file_id):
    return _file_link_record_by_id_response(file_id, 'uploads', as_attachment=False)


@app.get("/api3/download/<path:filename>")
def api3_download(filename):
    return _file_link_named_file_response(filename, 'uploads', as_attachment=True)


@app.get("/api3/download-id/<path:file_id>")
def api3_download_by_id(file_id):
    return _file_link_record_by_id_response(file_id, 'uploads', as_attachment=True)




def _expired_file_link_response(filename: str = '', *, namespace: str = ''):
    name = os.path.basename(str(filename or '').strip())
    label = '文件链接已过期'
    payload = {
        'ok': False,
        'error': label,
        'code': 'file_link_expired',
        'filename': name,
        'namespace': str(namespace or '').strip(),
    }
    try:
        accepts = str(request.headers.get('Accept') or '')
        if 'text/html' in accepts and 'application/json' not in accepts:
            html = '<!doctype html><meta charset="utf-8"><title>文件链接已过期</title><body style="font-family:system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;padding:32px;background:#f7f7f8;color:#111"><h2>文件链接已过期</h2><p>这个文件已经被系统自动清理，无法继续打开。</p></body>'
            return Response(html, status=410, mimetype='text/html; charset=utf-8')
    except Exception:
        pass
    return jsonify(payload), 410

def _cache_generated_image_response(resp, filename: str = ''):
    try:
        ext = os.path.splitext(os.path.basename(str(filename or '')))[1].strip().lower()
    except Exception:
        ext = ''
    if ext in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}:
        try:
            resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            resp.headers['X-WebAI-Generated-Image-Cache'] = 'immutable'
        except Exception:
            pass
    return resp


ACTIVE_FILE_EXTS_FORCE_DOWNLOAD = {
    '.html', '.htm', '.xhtml', '.svg',
    '.js', '.mjs', '.cjs',
    '.ts', '.tsx', '.jsx', '.mts', '.cts',
    '.vue', '.svelte', '.astro',
    '.xml', '.xsl',
}


def _file_link_should_force_download(filename: str = '') -> bool:
    name = os.path.basename(str(filename or '').strip()).lower()
    ext = os.path.splitext(name)[1].lower()
    if ext in ACTIVE_FILE_EXTS_FORCE_DOWNLOAD:
        return True
    if name in {'.env', '.env.local', '.env.development', '.env.production', '.npmrc', '.yarnrc'}:
        return True
    return False


def _file_link_harden_response(resp, filename: str = ''):
    try:
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['Referrer-Policy'] = 'same-origin'
    except Exception:
        pass
    return _cache_generated_image_response(resp, filename)



@app.get("/api3/generated-files-id/<path:file_id>")
def api3_generated_files_by_id(file_id):
    return _file_link_record_by_id_response(file_id, 'generated', as_attachment=False)


@app.get("/api3/generated-download-id/<path:file_id>")
def api3_generated_download_by_id(file_id):
    return _file_link_record_by_id_response(file_id, 'generated', as_attachment=True)

@app.get("/api3/generated-files/<path:filename>")
def api3_generated_files(filename):
    return _file_link_named_file_response(filename, 'generated', as_attachment=False)


@app.get("/api3/generated-download/<path:filename>")
def api3_generated_download(filename):
    return _file_link_named_file_response(filename, 'generated', as_attachment=True)



@app.get("/<path:filename>")
def api3_direct_generated_file_fallback(filename):
    """Allow old assistant artifact links to keep working.

    Older answers sometimes rendered generated artifacts as plain filenames or
    sandbox paths such as /mnt/data/report.xlsx instead of the canonical
    /api3/generated-download/report.xlsx route.  Normalize only known sandbox
    path prefixes to their basename; arbitrary nested paths still 404.
    """
    raw = str(filename or '').strip().replace('\\', '/')
    raw = raw.lstrip('/')
    safe = os.path.basename(raw)
    allowed_legacy_path = bool(re.match(r'^(?:mnt/data|tmp|sandbox/mnt/data)/[^/]+$', raw, flags=re.I))
    if not safe or safe.startswith('.') or (safe != raw and not allowed_legacy_path):
        return jsonify({"error": "文件不存在"}), 404
    ext = os.path.splitext(safe)[1].lower()
    try:
        allowed = set(ALLOWED_EXT)
    except Exception:
        allowed = {'.txt', '.md', '.html', '.htm', '.py', '.js', '.json', '.csv', '.docx', '.xlsx', '.pdf', '.zip'}
    if ext not in allowed:
        return jsonify({"error": "文件不存在"}), 404

    preferred_scope = _request_upload_scope_for_access()
    base_dir = _resolve_generated_file_dir(safe, scope=preferred_scope)
    if base_dir:
        denied = _file_link_access_guard('generated', safe, preferred_scope)
        if denied is not None:
            return denied
        return _file_link_harden_response(send_from_directory(base_dir, safe, as_attachment=_file_link_should_force_download(safe)), safe)

    base_dir = _resolve_uploaded_file_dir(safe, scope=preferred_scope)
    if base_dir:
        denied = _file_link_access_guard('uploads', safe, preferred_scope)
        if denied is not None:
            return denied
        return _file_link_harden_response(send_from_directory(base_dir, safe, as_attachment=_file_link_should_force_download(safe)), safe)

    return _expired_file_link_response(safe, namespace='file')
