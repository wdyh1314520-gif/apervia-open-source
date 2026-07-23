# Request tracing and shared JSON response helpers.
# Purpose: request tracing and shared no-store JSON responses.
# Loaded first by user_personalization_runtime_part.py so later routes share these helpers.


def _request_trace_before_request():
    try:
        incoming = str(request.headers.get('X-Request-ID') or request.headers.get('X-Correlation-ID') or '').strip()
    except Exception:
        incoming = ''
    request_id = incoming or uuid.uuid4().hex
    try:
        g.request_id = request_id
        g.request_started_at = time.time()
    except Exception:
        pass
    try:
        request.environ['HTTP_X_REQUEST_ID'] = request_id
    except Exception:
        pass
    return None


def _request_trace_after_request(resp):
    try:
        request_id = str(getattr(g, 'request_id', '') or '').strip()
    except Exception:
        request_id = ''
    if request_id:
        try:
            resp.headers['X-Request-ID'] = request_id
        except Exception:
            pass
    try:
        started_at = float(getattr(g, 'request_started_at', 0.0) or 0.0)
        if started_at > 0:
            duration_ms = int(max(0.0, (time.time() - started_at) * 1000.0))
            resp.headers['X-Response-Time-Ms'] = str(duration_ms)
    except Exception:
        pass
    return resp


try:
    before_funcs = list((app.before_request_funcs or {}).get(None) or [])
    if _request_trace_before_request not in before_funcs:
        before_funcs.insert(0, _request_trace_before_request)
    app.before_request_funcs[None] = before_funcs
except Exception:
    pass

try:
    after_funcs = list((app.after_request_funcs or {}).get(None) or [])
    if _request_trace_after_request not in after_funcs:
        after_funcs.insert(0, _request_trace_after_request)
    app.after_request_funcs[None] = after_funcs
except Exception:
    pass


def _json_no_store_response(payload, status: int = 200):
    resp = jsonify(payload)
    try:
        resp.status_code = int(status)
    except Exception:
        pass
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    try:
        request_id = str(getattr(g, 'request_id', '') or '').strip()
        if request_id:
            resp.headers['X-Request-ID'] = request_id
    except Exception:
        pass
    return resp
