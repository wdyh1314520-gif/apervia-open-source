# platform-admin Skill docs, sandbox Python packages, runtime logs, and settings diagnostics.

import collections
import importlib.metadata as importlib_metadata
import json


_PLATFORM_ADMIN_LOG_ROWS = collections.deque(maxlen=1200)
_PLATFORM_ADMIN_LOG_LOCK = threading.Lock()
_PLATFORM_ADMIN_LOG_SEQUENCE = 0
_PLATFORM_ADMIN_PYTHON_INSTALL_LOCK = threading.Lock()
_PLATFORM_ADMIN_DOCKER_STATUS_CACHE = {'checked_at': 0.0, 'payload': {}}
_PLATFORM_ADMIN_PYTHON_PACKAGES_CACHE = {'checked_at': 0.0, 'key': '', 'payload': {}}
_SANDBOX_PYTHON_PACKAGES_CONTAINER_DIR = '/opt/app3-python-packages'


def _platform_admin_redact_log_text(value: str = '') -> str:
    text = str(value or '')
    patterns = (
        (r'(?i)\bsk-[a-z0-9_-]{8,}\b', 'sk-***'),
        (r'(?i)(bearer\s+)[a-z0-9._~+/=-]{8,}', r'\1***'),
        (r'(?i)(https?://)[^/\s:@]+:[^@\s/]+@', r'\1***:***@'),
        (r'(?i)([?&](?:token|api_key|apikey|key|secret|password|local_admin_token)=)[^&\s]+', r'\1***'),
        (r'(?i)(["\'](?:token|api_key|apikey|secret|password|authorization)["\']\s*:\s*["\'])[^"\']+', r'\1***'),
    )
    for pattern, replacement in patterns:
        try:
            text = re.sub(pattern, replacement, text)
        except Exception:
            continue
    return text[:8000]


class _PlatformAdminMemoryLogHandler(logging.Handler):
    _app3_platform_admin_memory_log_handler = True

    def emit(self, record) -> None:
        global _PLATFORM_ADMIN_LOG_SEQUENCE
        try:
            message = _platform_admin_redact_log_text(self.format(record))
            with _PLATFORM_ADMIN_LOG_LOCK:
                _PLATFORM_ADMIN_LOG_SEQUENCE += 1
                _PLATFORM_ADMIN_LOG_ROWS.append({
                    'seq': _PLATFORM_ADMIN_LOG_SEQUENCE,
                    'ts': float(getattr(record, 'created', time.time()) or time.time()),
                    'time': _storage_quota_fmt_ts(float(getattr(record, 'created', time.time()) or time.time())),
                    'level': str(getattr(record, 'levelname', 'INFO') or 'INFO').upper()[:16],
                    'logger': str(getattr(record, 'name', '') or '')[:120],
                    'message': message,
                })
        except Exception:
            return


def _platform_admin_install_memory_log_handler() -> None:
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers or []):
        if bool(getattr(handler, '_app3_platform_admin_memory_log_handler', False)):
            return
    handler = _PlatformAdminMemoryLogHandler(level=logging.INFO)
    handler.setFormatter(logging.Formatter('%(message)s'))
    root_logger.addHandler(handler)


_platform_admin_install_memory_log_handler()


def _platform_admin_app_logs_payload(
    *,
    after_seq: int = 0,
    limit: int = 200,
    level: str = '',
    query: str = '',
) -> dict:
    after_seq = _platform_admin_safe_int(after_seq, 0, minimum=0, maximum=2_000_000_000)
    limit = _platform_admin_safe_int(limit, 200, minimum=10, maximum=500)
    level_key = str(level or '').strip().upper()
    query_key = str(query or '').strip().lower()[:120]
    with _PLATFORM_ADMIN_LOG_LOCK:
        rows = [dict(item) for item in list(_PLATFORM_ADMIN_LOG_ROWS)]
        latest_seq = int(_PLATFORM_ADMIN_LOG_SEQUENCE or 0)
    if after_seq:
        rows = [item for item in rows if int(item.get('seq') or 0) > after_seq]
    if level_key:
        rows = [item for item in rows if str(item.get('level') or '').upper() == level_key]
    if query_key:
        rows = [item for item in rows if query_key in (str(item.get('logger') or '') + ' ' + str(item.get('message') or '')).lower()]
    if len(rows) > limit:
        rows = rows[-limit:]
    return {
        'ok': True,
        'rows': rows,
        'latest_seq': latest_seq,
        'buffer_size': len(_PLATFORM_ADMIN_LOG_ROWS),
        'buffer_limit': int(_PLATFORM_ADMIN_LOG_ROWS.maxlen or 1200),
        'updated_at_text': _storage_quota_fmt_ts(time.time()),
    }


def _sandbox_python_packages_host_dir() -> str:
    configured = str(app_getenv('SANDBOX_PYTHON_PACKAGES_DIR', '') or '').strip()
    return os.path.abspath(configured) if configured else _app_data_path('sandbox_python_packages')


def _platform_admin_docker_status(*, force: bool = False) -> dict:
    now = time.time()
    cached = dict(_PLATFORM_ADMIN_DOCKER_STATUS_CACHE.get('payload') or {})
    if not force and cached and now - float(_PLATFORM_ADMIN_DOCKER_STATUS_CACHE.get('checked_at') or 0.0) < 15.0:
        return cached
    health = _sandbox_runner_health()
    available = bool(health.get('ok')) and bool(health.get('docker_ok')) and bool(health.get('image_available'))
    payload = {
        'available': available,
        'version': str(health.get('docker_version') or '')[:80],
        'message': 'Sandbox Runner 可用' if available else 'Sandbox Runner 未启动、Docker 不可用或镜像缺失',
        'error': _platform_admin_redact_log_text(str(health.get('error') or ''))[:500],
        'runner': True,
        'image_available': bool(health.get('image_available')),
    }
    _PLATFORM_ADMIN_DOCKER_STATUS_CACHE.update({'checked_at': now, 'payload': payload})
    return dict(payload)


def _platform_admin_python_package_rows() -> list[dict]:
    root = _sandbox_python_packages_host_dir()
    if not os.path.isdir(root):
        return []
    rows: list[dict] = []
    try:
        for distribution in importlib_metadata.distributions(path=[root]):
            metadata = distribution.metadata
            name = str(metadata.get('Name') or '').strip()
            if not name:
                continue
            rows.append({
                'name': name,
                'version': str(distribution.version or ''),
                'summary': str(metadata.get('Summary') or '')[:240],
            })
    except Exception:
        return []
    rows.sort(key=lambda item: str(item.get('name') or '').lower())
    return rows[:1000]


def _platform_admin_python_package_key(value: str = '') -> str:
    return re.sub(r'[-_.]+', '-', str(value or '').strip().lower())


def _platform_admin_sandbox_python_inventory(
    *,
    docker_status: dict,
    sandbox_image: str,
    extension_rows: list[dict],
    force: bool = False,
) -> dict:
    extension_by_key = {
        _platform_admin_python_package_key(item.get('name')): dict(item)
        for item in extension_rows
        if _platform_admin_python_package_key(item.get('name'))
    }
    extension_names = set(extension_by_key)
    fallback_rows = [
        {
            **dict(item),
            'source': 'extension',
        }
        for item in extension_rows
    ]
    if not docker_status.get('available'):
        return {
            'available': False,
            'rows': fallback_rows,
            'image_total': 0,
            'extension_total': len(fallback_rows),
            'message': 'Docker 未启动，无法读取沙盒镜像中的 Python 包',
            'error': str(docker_status.get('error') or ''),
        }
    if not sandbox_image:
        return {
            'available': False,
            'rows': fallback_rows,
            'image_total': 0,
            'extension_total': len(fallback_rows),
            'message': '沙盒 Docker 镜像未配置，无法读取 Python 包',
            'error': '',
        }

    root = os.path.realpath(_sandbox_python_packages_host_dir())
    try:
        root_stamp = os.path.getmtime(root) if os.path.isdir(root) else 0.0
    except OSError:
        root_stamp = 0.0
    cache_key = f'{sandbox_image}|{root}|{root_stamp:.6f}'
    now = time.time()
    cached = dict(_PLATFORM_ADMIN_PYTHON_PACKAGES_CACHE.get('payload') or {})
    if (
        not force
        and cached
        and str(_PLATFORM_ADMIN_PYTHON_PACKAGES_CACHE.get('key') or '') == cache_key
        and now - float(_PLATFORM_ADMIN_PYTHON_PACKAGES_CACHE.get('checked_at') or 0.0) < 30.0
    ):
        return cached

    try:
        runner_payload = _sandbox_runner_request_path('/v1/python/inventory', {'image': sandbox_image}, timeout=40.0)
        raw_rows = runner_payload.get('rows') or []
        if not isinstance(raw_rows, list):
            raise ValueError('沙盒 Python 包清单格式无效')
        rows_by_key: dict[str, dict] = {}
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get('name') or '').strip()
            key = _platform_admin_python_package_key(name)
            if not name or not key:
                continue
            is_extension = key in extension_names
            extension_item = extension_by_key.get(key) or {}
            rows_by_key[key] = {
                'name': name,
                'version': str(raw.get('version') or ''),
                'summary': str(extension_item.get('summary') or '')[:240] if is_extension else '',
                'source': 'extension' if is_extension else 'image',
            }
        rows = sorted(rows_by_key.values(), key=lambda item: str(item.get('name') or '').lower())[:2000]
        extension_total = len([item for item in rows if item.get('source') == 'extension'])
        payload = {
            'available': True,
            'rows': rows,
            'image_total': max(0, len(rows) - extension_total),
            'extension_total': extension_total,
            'message': '已读取沙盒 Python 实际可见包',
            'error': '',
        }
    except Exception as exc:
        payload = {
            'available': False,
            'rows': fallback_rows,
            'image_total': 0,
            'extension_total': len(fallback_rows),
            'message': '沙盒 Python 包识别失败',
            'error': _platform_admin_redact_log_text(f'{type(exc).__name__}: {exc}')[:1000],
        }
    _PLATFORM_ADMIN_PYTHON_PACKAGES_CACHE.update({
        'checked_at': now,
        'key': cache_key,
        'payload': payload,
    })
    return dict(payload)


def _platform_admin_sandbox_image_text() -> str:
    try:
        return str(_sandbox_image() or '').strip()
    except Exception:
        return ''


def _platform_admin_python_packages_payload(
    *,
    force_docker_check: bool = False,
    force_inventory_check: bool = False,
) -> dict:
    extension_rows = _platform_admin_python_package_rows()
    docker_status = _platform_admin_docker_status(force=force_docker_check)
    sandbox_image = _platform_admin_sandbox_image_text()
    inventory = _platform_admin_sandbox_python_inventory(
        docker_status=docker_status,
        sandbox_image=sandbox_image,
        extension_rows=extension_rows,
        force=force_inventory_check,
    )
    rows = list(inventory.get('rows') or [])
    return {
        'ok': True,
        'rows': rows,
        'total': len(rows),
        'docker': docker_status,
        'image': sandbox_image,
        'image_total': int(inventory.get('image_total') or 0),
        'extension_total': int(inventory.get('extension_total') or 0),
        'inventory_available': bool(inventory.get('available')),
        'inventory_message': str(inventory.get('message') or ''),
        'inventory_error': str(inventory.get('error') or ''),
        'inventory_scope': 'sandbox_effective',
        'container_dir': _SANDBOX_PYTHON_PACKAGES_CONTAINER_DIR,
        'persistent': True,
        'read_only_in_runtime': True,
        'updated_at_text': _storage_quota_fmt_ts(time.time()),
    }


def _platform_admin_normalize_python_package_spec(value: str = '') -> str:
    spec = str(value or '').strip()
    pattern = r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}(?:\[[A-Za-z0-9_,.-]{1,120}\])?(?:==[A-Za-z0-9][A-Za-z0-9._+!-]{0,80})?$'
    if not spec or not re.fullmatch(pattern, spec):
        raise ValueError('仅支持 PyPI 包名或“包名==版本”，不支持 URL、路径和 pip 参数')
    return spec


def _platform_admin_python_package_install(spec: str = '') -> dict:
    package_spec = _platform_admin_normalize_python_package_spec(spec)
    docker_status = _platform_admin_docker_status(force=True)
    if not docker_status.get('available'):
        raise RuntimeError('Sandbox Runner 不可用，请启动 sandbox profile 并确认镜像已构建')
    root = os.path.realpath(_sandbox_python_packages_host_dir())
    base = os.path.realpath(APP_DATA_DIR)
    configured = str(app_getenv('SANDBOX_PYTHON_PACKAGES_DIR', '') or '').strip()
    if not configured and os.path.commonpath([base, root]) != base:
        raise RuntimeError('Python 包目录不在项目工作区内')
    os.makedirs(root, exist_ok=True)
    index_url = str(app_getenv('SANDBOX_PIP_INDEX_URL', 'https://pypi.tuna.tsinghua.edu.cn/simple') or '').strip()
    parsed_index = urllib.parse.urlparse(index_url)
    if parsed_index.scheme not in {'http', 'https'} or not parsed_index.netloc:
        raise RuntimeError('SANDBOX_PIP_INDEX_URL 配置无效')
    sandbox_image = _platform_admin_sandbox_image_text()
    if not sandbox_image:
        raise RuntimeError('沙盒 Docker 镜像未配置，无法安装 Python 包')
    with _PLATFORM_ADMIN_PYTHON_INSTALL_LOCK:
        result = _sandbox_runner_request_path(
            '/v1/python/install',
            {'image': sandbox_image, 'package': package_spec},
            timeout=260.0,
        )
    output = _platform_admin_redact_log_text((str(result.get('stdout') or '') + '\n' + str(result.get('stderr') or '')).strip())[-8000:]
    _PLATFORM_ADMIN_PYTHON_PACKAGES_CACHE.update({'checked_at': 0.0, 'key': '', 'payload': {}})
    payload = _platform_admin_python_packages_payload(
        force_docker_check=False,
        force_inventory_check=True,
    )
    payload.update({'installed': package_spec, 'output': output})
    _platform_admin_audit_append('sandbox_python_package_install', package_spec, {
        'package': package_spec,
        'package_total': payload.get('total'),
    }, ok=True)
    try:
        app_logger.info('[platform_admin] sandbox_python_package_installed package=%s', package_spec)
    except Exception:
        pass
    return payload


def _platform_admin_settings_payload() -> dict:
    def _flag(name: str, default: str = '0') -> bool:
        return str(app_getenv(name, default) or default).strip().lower() not in {'0', 'false', 'off', 'no', 'disabled'}

    return {
        'ok': True,
        'groups': [
            {
                'name': '应用运行',
                'items': [
                    {'key': 'runtime_log_file', 'label': '文件日志', 'value': _flag('APP3_RUNTIME_LOG_FILE', '0')},
                    {'key': 'debug_mode', 'label': '调试模式', 'value': _flag('DEBUG', '0')},
                ],
            },
            {
                'name': '沙盒安全',
                'items': [
                    {'key': 'docker_image', 'label': '镜像', 'value': _platform_admin_sandbox_image_text() or '未配置'},
                    {'key': 'runner', 'label': '执行后端', 'value': _sandbox_runner_base_url()},
                    {'key': 'network', 'label': '普通任务网络', 'value': 'none（Runner 强制）'},
                    {'key': 'python_packages_read_only', 'label': '扩展包运行时只读', 'value': True},
                ],
            },
        ],
        'updated_at_text': _storage_quota_fmt_ts(time.time()),
    }
