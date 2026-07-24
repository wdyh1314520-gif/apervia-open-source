# platform-admin system, CPU, memory, disk, network, process, and service status payloads.

try:
    import psutil as _platform_admin_psutil
except Exception:
    _platform_admin_psutil = None

def _platform_admin_read_text_file(path: str = '', limit: int = 1024 * 1024) -> str:
    try:
        with open(str(path or ''), 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(max(1, int(limit or 0)))
    except Exception:
        return ''


def _platform_admin_percent(part: float | int, total: float | int) -> float:
    try:
        t = float(total or 0)
        if t <= 0:
            return 0.0
        return round(max(0.0, min(100.0, (float(part or 0) / t) * 100.0)), 2)
    except Exception:
        return 0.0


def _platform_admin_format_seconds(seconds: float | int) -> str:
    try:
        s = max(0, int(float(seconds or 0)))
    except Exception:
        s = 0
    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f'{days}d {hours}h'
    if hours > 0:
        return f'{hours}h {minutes}m'
    return f'{minutes}m'


def _platform_admin_cpu_times() -> tuple[int, int] | None:
    raw = _platform_admin_read_text_file('/proc/stat', 4096)
    if not raw:
        return None
    first = raw.splitlines()[0].strip().split()
    if not first or first[0] != 'cpu':
        return None
    values: list[int] = []
    for item in first[1:]:
        try:
            values.append(int(item))
        except Exception:
            values.append(0)
    if not values:
        return None
    idle = (values[3] if len(values) > 3 else 0) + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return total, idle


def _platform_admin_cpu_payload() -> dict:
    try:
        cpu_count = max(1, int(os.cpu_count() or 1))
    except Exception:
        cpu_count = 1
    try:
        load = [round(float(x), 2) for x in os.getloadavg()]
    except Exception:
        load = []
    now = time.time()
    current = _platform_admin_cpu_times()
    percent = 0.0
    with _PLATFORM_ADMIN_SYSTEM_STATUS_LOCK:
        prev = _PLATFORM_ADMIN_SYSTEM_STATUS_CACHE.get('cpu')
        _PLATFORM_ADMIN_SYSTEM_STATUS_CACHE['cpu'] = {'at': now, 'times': current}
    if current and isinstance(prev, dict) and isinstance(prev.get('times'), tuple):
        try:
            prev_total, prev_idle = prev.get('times')
            total_delta = max(0, int(current[0]) - int(prev_total))
            idle_delta = max(0, int(current[1]) - int(prev_idle))
            if total_delta > 0:
                percent = round(max(0.0, min(100.0, (1.0 - (idle_delta / float(total_delta))) * 100.0)), 2)
        except Exception:
            percent = 0.0
    elif load:
        try:
            percent = round(max(0.0, min(100.0, (float(load[0]) / float(cpu_count or 1)) * 100.0)), 2)
        except Exception:
            percent = 0.0
    if current is None and _platform_admin_psutil is not None:
        try:
            percent = round(float(_platform_admin_psutil.cpu_percent(interval=0.05)), 2)
            cpu_count = max(1, int(_platform_admin_psutil.cpu_count(logical=True) or cpu_count))
        except Exception:
            pass
    return {'count': cpu_count, 'percent': percent, 'load': load, 'load_text': ' | '.join(str(x) for x in load) if load else '-'}


def _platform_admin_meminfo_payload() -> dict:
    raw = _platform_admin_read_text_file('/proc/meminfo', 64 * 1024)
    data: dict[str, int] = {}
    for line in raw.splitlines():
        if ':' not in line:
            continue
        key, rest = line.split(':', 1)
        value = str(rest or '').strip().split()[0:1]
        try:
            data[key] = int(value[0]) * 1024 if value else 0
        except Exception:
            data[key] = 0
    total = int(data.get('MemTotal') or 0)
    available = int(data.get('MemAvailable') or data.get('MemFree') or 0)
    used = max(0, total - available)
    swap_total = int(data.get('SwapTotal') or 0)
    swap_free = int(data.get('SwapFree') or 0)
    swap_used = max(0, swap_total - swap_free)
    if total <= 0 and _platform_admin_psutil is not None:
        try:
            virtual = _platform_admin_psutil.virtual_memory()
            swap = _platform_admin_psutil.swap_memory()
            total = int(virtual.total or 0)
            available = int(virtual.available or 0)
            used = int(virtual.used or max(0, total - available))
            swap_total = int(swap.total or 0)
            swap_used = int(swap.used or 0)
        except Exception:
            pass
    return {
        'total_bytes': total,
        'available_bytes': available,
        'used_bytes': used,
        'used_text': _storage_quota_human(used),
        'total_text': _storage_quota_human(total),
        'percent': _platform_admin_percent(used, total),
        'swap_total_bytes': swap_total,
        'swap_used_bytes': swap_used,
        'swap_used_text': _storage_quota_human(swap_used),
        'swap_total_text': _storage_quota_human(swap_total),
        'swap_percent': _platform_admin_percent(swap_used, swap_total),
    }


def _platform_admin_disk_payload() -> dict:
    try:
        usage = shutil.disk_usage(APP_DATA_DIR)
        total = int(usage.total)
        used = int(usage.used)
        free = int(usage.free)
    except Exception:
        total = used = free = 0
    return {
        'total_bytes': total,
        'used_bytes': used,
        'free_bytes': free,
        'used_text': _storage_quota_human(used),
        'total_text': _storage_quota_human(total),
        'free_text': _storage_quota_human(free),
        'percent': _platform_admin_percent(used, total),
    }


def _platform_admin_process_payload() -> dict:
    raw = _platform_admin_read_text_file('/proc/self/status', 64 * 1024)
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            values[k.strip()] = v.strip()
    def kb_value(key: str) -> int:
        try:
            return int(str(values.get(key) or '0').split()[0]) * 1024
        except Exception:
            return 0
    try:
        threads = int(str(values.get('Threads') or '0').split()[0])
    except Exception:
        threads = 0
    uptime_s = max(0, time.time() - float(globals().get('_PLATFORM_ADMIN_PROCESS_START_TS') or time.time()))
    rss_bytes = kb_value('VmRSS')
    vm_size_bytes = kb_value('VmSize')
    if (not values or rss_bytes <= 0) and _platform_admin_psutil is not None:
        try:
            process = _platform_admin_psutil.Process(os.getpid())
            memory = process.memory_info()
            rss_bytes = int(memory.rss or 0)
            vm_size_bytes = int(memory.vms or 0)
            threads = int(process.num_threads() or 0)
            uptime_s = max(0, time.time() - float(process.create_time() or time.time()))
        except Exception:
            pass
    return {
        'pid': os.getpid() if callable(getattr(os, 'getpid', None)) else 0,
        'rss_bytes': rss_bytes,
        'rss_text': _storage_quota_human(rss_bytes),
        'vm_size_bytes': vm_size_bytes,
        'vm_size_text': _storage_quota_human(vm_size_bytes),
        'threads': threads,
        'uptime_seconds': int(uptime_s),
        'uptime_text': _platform_admin_format_seconds(uptime_s),
    }


def _platform_admin_uptime_payload() -> dict:
    raw = _platform_admin_read_text_file('/proc/uptime', 4096).strip().split()
    try:
        seconds = float(raw[0]) if raw else 0.0
    except Exception:
        seconds = 0.0
    if seconds <= 0 and _platform_admin_psutil is not None:
        try:
            seconds = max(0.0, time.time() - float(_platform_admin_psutil.boot_time() or time.time()))
        except Exception:
            pass
    return {'seconds': int(max(0, seconds)), 'text': _platform_admin_format_seconds(seconds)}


def _platform_admin_network_counters() -> tuple[int, int]:
    raw = _platform_admin_read_text_file('/proc/net/dev', 64 * 1024)
    rx = 0
    tx = 0
    for line in raw.splitlines():
        if ':' not in line:
            continue
        name, rest = line.split(':', 1)
        iface = str(name or '').strip()
        if not iface or iface == 'lo':
            continue
        parts = str(rest or '').split()
        if len(parts) < 16:
            continue
        try:
            rx += int(parts[0])
            tx += int(parts[8])
        except Exception:
            continue
    if rx == 0 and tx == 0 and _platform_admin_psutil is not None:
        try:
            counters = _platform_admin_psutil.net_io_counters(pernic=True) or {}
            for name, item in counters.items():
                lowered = str(name or '').strip().lower()
                if lowered in {'lo', 'loopback', 'loopback pseudo-interface 1'} or 'loopback' in lowered:
                    continue
                rx += int(item.bytes_recv or 0)
                tx += int(item.bytes_sent or 0)
        except Exception:
            pass
    return rx, tx


def _platform_admin_network_payload() -> dict:
    now = time.time()
    rx, tx = _platform_admin_network_counters()
    down_bps = 0.0
    up_bps = 0.0
    with _PLATFORM_ADMIN_SYSTEM_STATUS_LOCK:
        prev = _PLATFORM_ADMIN_SYSTEM_STATUS_CACHE.get('network')
        _PLATFORM_ADMIN_SYSTEM_STATUS_CACHE['network'] = {'at': now, 'rx': rx, 'tx': tx}
    if isinstance(prev, dict):
        try:
            delta = max(0.001, now - float(prev.get('at') or now))
            down_bps = max(0.0, (rx - int(prev.get('rx') or 0)) / delta)
            up_bps = max(0.0, (tx - int(prev.get('tx') or 0)) / delta)
        except Exception:
            down_bps = 0.0
            up_bps = 0.0
    return {
        'rx_bytes': rx,
        'tx_bytes': tx,
        'rx_text': _storage_quota_human(rx),
        'tx_text': _storage_quota_human(tx),
        'download_bps': int(down_bps),
        'upload_bps': int(up_bps),
        'download_text': _storage_quota_human(down_bps) + '/s',
        'upload_text': _storage_quota_human(up_bps) + '/s',
    }


def _platform_admin_connection_count(path: str) -> int:
    raw = _platform_admin_read_text_file(path, 1024 * 1024)
    return len([x for x in raw.splitlines()[1:] if x.strip()])


def _platform_admin_connections_payload() -> dict:
    tcp = _platform_admin_connection_count('/proc/net/tcp') + _platform_admin_connection_count('/proc/net/tcp6')
    udp = _platform_admin_connection_count('/proc/net/udp') + _platform_admin_connection_count('/proc/net/udp6')
    if tcp == 0 and udp == 0 and _platform_admin_psutil is not None:
        try:
            import socket
            for connection in _platform_admin_psutil.net_connections(kind='inet'):
                if connection.type == socket.SOCK_STREAM:
                    tcp += 1
                elif connection.type == socket.SOCK_DGRAM:
                    udp += 1
        except Exception:
            pass
    return {'tcp': tcp, 'udp': udp}


def _platform_admin_service_status(name: str = '') -> dict:
    service = str(name or '').strip()
    if not service:
        return {'name': '', 'active': False, 'status': 'unknown', 'status_text': '未知'}
    try:
        result = subprocess.run(['systemctl', 'is-active', service], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=0.8)
        status = str(result.stdout or '').strip() or ('inactive' if result.returncode else 'active')
    except Exception:
        status = 'unknown'
    if status == 'unknown' and _platform_admin_psutil is not None:
        if service == 'app3.service':
            return {'name': service, 'active': True, 'status': 'process', 'status_text': '运行中（当前进程）'}
    return {'name': service, 'active': status == 'active', 'status': status, 'status_text': '运行中' if status == 'active' else ('未运行' if status in {'inactive', 'failed'} else status)}


def _platform_admin_system_status_payload() -> dict:
    cpu = _platform_admin_cpu_payload()
    memory = _platform_admin_meminfo_payload()
    swap = {
        'used_bytes': int(memory.get('swap_used_bytes') or 0),
        'total_bytes': int(memory.get('swap_total_bytes') or 0),
        'used_text': str(memory.get('swap_used_text') or '0B'),
        'total_text': str(memory.get('swap_total_text') or '0B'),
        'percent': float(memory.get('swap_percent') or 0.0),
    }
    return {
        'ok': True,
        'updated_at': time.time(),
        'cpu': cpu,
        'memory': memory,
        'swap': swap,
        'disk': _platform_admin_disk_payload(),
        'uptime': _platform_admin_uptime_payload(),
        'process': _platform_admin_process_payload(),
        'network': _platform_admin_network_payload(),
        'connections': _platform_admin_connections_payload(),
        'services': {'app3': _platform_admin_service_status('app3.service')},
    }
