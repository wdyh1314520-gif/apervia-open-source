# Waitress production server entry point.

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

    print(f"{APP_NAME} {APP_VERSION} started on port {PORT} with {_waitress_threads} threads", flush=True)

    # Keep warnings and failures, but omit Waitress's URL-bearing INFO banner.
    logging.getLogger('waitress').setLevel(logging.WARNING)
    serve(app, host=_waitress_host, port=PORT, threads=_waitress_threads)


if __name__ == "__main__" and not bool(globals().get('APP3_DEFER_WAITRESS_STARTUP')):
    _app3_waitress_startup()
