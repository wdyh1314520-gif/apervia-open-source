# Split from app3_parts/media/async_pullback_upload_server_part.py.
# Purpose: Waitress startup tail.
# Loaded by async_pullback_upload_server_part.py via _exec_split_file(...), sharing the original global namespace.

# ====== Waitress startup tail restored ======
def _app3_waitress_startup():
    try:
        from waitress import serve
    except Exception as e:
        raise RuntimeError(f"waitress import failed: {type(e).__name__}: {e}")

    try:
        _waitress_threads = int(str(os.environ.get("WAITRESS_THREADS", "32") or "32").strip())
    except Exception:
        _waitress_threads = 32
    _waitress_threads = max(8, min(_waitress_threads, 128))

    try:
        _waitress_host = str(os.environ.get("APP_HOST", "127.0.0.1") or "127.0.0.1").strip()
    except Exception:
        _waitress_host = "127.0.0.1"

    print(f"{APP_NAME} running: http://{_waitress_host}:{PORT}/", flush=True)
    print(f"base_url(default) = {GPT_BASE_URL}", flush=True)
    print(f"tls_verify = {tls_verify}  (set GPT_TLS_VERIFY=0 to disable verify)", flush=True)
    print("config source = front-end settings > built-in defaults (pure front-end config mode)", flush=True)

    serve(app, host=_waitress_host, port=PORT, threads=_waitress_threads)


if __name__ == "__main__" and not bool(globals().get('APP3_DEFER_WAITRESS_STARTUP')):
    _app3_waitress_startup()
