# load the maintainable platform-admin static HTML shell.

_PLATFORM_ADMIN_HTML_FILE = os.path.join(STATIC_DIR, 'platform-admin', 'index.html')


def _platform_admin_html() -> str:
    with open(_PLATFORM_ADMIN_HTML_FILE, 'r', encoding='utf-8') as handle:
        text = handle.read()
    version_fn = globals().get('_index_static_asset_version')
    version = str(version_fn() if callable(version_fn) else int(time.time()))
    return text.replace('__APP3_STATIC_VERSION__', version)
