from __future__ import annotations

import concurrent.futures
import io
import json
import os
import re
import secrets
import shutil
import tarfile
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import docker
from docker.types import Ulimit
from flask import Flask, jsonify, request
from mcp_client.signing import ReplayNonceStore, verify_request_signature


SERVICE_NAME = 'apervia-sandbox-runner'
DATA_ROOT = Path(os.getenv('APP_DATA_DIR', '/data')).resolve()
SANDBOX_ROOT = (DATA_ROOT / 'sandboxes').resolve()
EXTENSION_ROOT = (DATA_ROOT / 'sandbox_python_packages').resolve()
SKILLS_ROOT = Path(os.getenv('SANDBOX_RUNNER_SKILLS_DIR', '/app/app3_skills')).resolve()
SECRET_FILE = (DATA_ROOT / 'sandbox_runner.secret').resolve()
ALLOWED_IMAGE = str(os.getenv('SANDBOX_RUNNER_ALLOWED_IMAGE', '') or '').strip()
DATA_UID = max(0, int(os.getenv('SANDBOX_DATA_UID', '10001') or 10001))
DATA_GID = max(0, int(os.getenv('SANDBOX_DATA_GID', '10001') or 10001))
RUNTIME_DIR_NAME = '.app3_runtime'
STDIN_FILE_NAME = '.app3_runner_stdin'
_NONCE_STORE = ReplayNonceStore(ttl_seconds=120, max_entries=8192)
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_PRUNE_LOCK = threading.Lock()
_LAST_PRUNE = 0.0

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024


def _secret() -> str:
    configured = str(os.getenv('SANDBOX_RUNNER_SECRET', '') or '').strip()
    if configured:
        if len(configured) < 32:
            raise RuntimeError('SANDBOX_RUNNER_SECRET 长度不足 32 个字符')
        return configured
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        value = SECRET_FILE.read_text(encoding='ascii').strip()
    except FileNotFoundError:
        value = secrets.token_urlsafe(48)
        try:
            fd = os.open(str(SECRET_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            value = SECRET_FILE.read_text(encoding='ascii').strip()
        else:
            with os.fdopen(fd, 'w', encoding='ascii', newline='\n') as handle:
                handle.write(value + '\n')
                handle.flush()
                os.fsync(handle.fileno())
    if len(value) < 32:
        raise RuntimeError('sandbox_runner.secret 无效')
    try:
        chown = getattr(os, 'chown', None)
        if callable(chown):
            chown(SECRET_FILE, DATA_UID, DATA_GID)
        os.chmod(SECRET_FILE, 0o600)
    except OSError:
        pass
    return value


def _verify_request() -> tuple[bool, str]:
    body = request.get_data(cache=True) or b''
    timestamp = str(request.headers.get('X-App3-Sandbox-Timestamp') or '')
    nonce = str(request.headers.get('X-App3-Sandbox-Nonce') or '')
    signature = str(request.headers.get('X-App3-Sandbox-Signature') or '')
    ok, error = verify_request_signature(
        _secret(), request.method, request.path, timestamp, nonce, body, signature, max_skew_seconds=30
    )
    if not ok:
        return False, error
    if not _NONCE_STORE.consume(nonce):
        return False, 'signature_nonce_replayed'
    return True, ''


def _docker_client():
    client = docker.from_env(timeout=10)
    client.ping()
    return client


def _validate_image(value: str) -> str:
    image = str(value or '').strip()
    if not ALLOWED_IMAGE:
        raise ValueError('SANDBOX_RUNNER_ALLOWED_IMAGE 未配置')
    if image != ALLOWED_IMAGE:
        raise ValueError('sandbox_image_not_allowed')
    return image


def _safe_relative(value: str, *, allow_empty: bool = False, strict_names: bool = True) -> str:
    raw = str(value or '').replace('\\', '/').strip()
    if not raw:
        if allow_empty:
            return ''
        raise ValueError('sandbox_relative_path_required')
    if raw.startswith('/') or re.match(r'^[A-Za-z]:($|/)', raw):
        raise ValueError('sandbox_relative_path_invalid')
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {'', '.', '..'} for part in path.parts):
        raise ValueError('sandbox_relative_path_invalid')
    if any(len(part) > 240 or '\x00' in part for part in path.parts):
        raise ValueError('sandbox_relative_path_invalid')
    if strict_names and any(not re.fullmatch(r'[A-Za-z0-9_.@+-]{1,120}', part) for part in path.parts):
        raise ValueError('sandbox_relative_path_invalid')
    return '/'.join(path.parts)


def _sandbox_path(relative: str) -> Path:
    rel = _safe_relative(relative)
    target = (SANDBOX_ROOT / Path(*PurePosixPath(rel).parts)).resolve()
    if target == SANDBOX_ROOT or SANDBOX_ROOT not in target.parents:
        raise ValueError('sandbox_path_outside_root')
    target.mkdir(parents=True, exist_ok=True)
    return target


def _path_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _size_value(value: str, default: str) -> str:
    text = str(value or default).strip().lower()
    return text if re.fullmatch(r'[1-9][0-9]{0,5}[kmg]', text) else default


def _cpus_to_nano(value: str) -> int:
    try:
        return max(100_000_000, min(int(float(value) * 1_000_000_000), 8_000_000_000))
    except Exception:
        return 1_000_000_000


def _int_value(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _add_tree_to_tar(archive: tarfile.TarFile, root: Path, arc_prefix: str = '', *, max_bytes: int) -> int:
    total = 0
    if not root.is_dir():
        return 0
    for path in sorted(root.rglob('*')):
        try:
            if path.is_symlink():
                continue
            rel = path.relative_to(root).as_posix()
            if not rel or rel.split('/', 1)[0] == RUNTIME_DIR_NAME:
                continue
            arcname = '/'.join(part for part in (arc_prefix.strip('/'), rel) if part)
            if path.is_dir():
                info = archive.gettarinfo(str(path), arcname=arcname)
                archive.addfile(info)
                continue
            if not path.is_file():
                continue
            size = int(path.stat().st_size)
            total += size
            if total > max_bytes:
                raise ValueError('sandbox_input_too_large')
            info = archive.gettarinfo(str(path), arcname=arcname)
            with path.open('rb') as handle:
                archive.addfile(info, handle)
        except FileNotFoundError:
            continue
    return total


def _input_archive(source: Path, stdin_text: str, max_bytes: int, *, include_runtime: bool = True) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        _add_tree_to_tar(archive, source, max_bytes=max_bytes)
        if stdin_text:
            raw = stdin_text.encode('utf-8')
            if len(raw) > 1024 * 1024:
                raise ValueError('sandbox_stdin_too_large')
            info = tarfile.TarInfo(STDIN_FILE_NAME)
            info.size = len(raw)
            info.mode = 0o600
            info.mtime = int(time.time())
            archive.addfile(info, io.BytesIO(raw))
        if include_runtime and SKILLS_ROOT.is_dir():
            _add_tree_to_tar(archive, SKILLS_ROOT, f'{RUNTIME_DIR_NAME}/app3_skills', max_bytes=32 * 1024 * 1024)
        if include_runtime and EXTENSION_ROOT.is_dir():
            _add_tree_to_tar(archive, EXTENSION_ROOT, f'{RUNTIME_DIR_NAME}/python_packages', max_bytes=512 * 1024 * 1024)
    return buffer.getvalue()


def _read_archive(stream, max_bytes: int) -> bytes:
    buffer = io.BytesIO()
    total = 0
    for chunk in stream:
        total += len(chunk)
        if total > max_bytes + 8 * 1024 * 1024:
            raise ValueError('sandbox_output_too_large')
        buffer.write(chunk)
    return buffer.getvalue()


def _extract_archive_to_stage(raw: bytes, stage: Path, max_bytes: int) -> int:
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:*') as archive:
        for member in archive:
            name = str(member.name or '').replace('\\', '/')
            while name.startswith('./'):
                name = name[2:]
            if not name:
                continue
            parts = PurePosixPath(name).parts
            if not parts or any(part in {'', '.', '..'} for part in parts) or parts[0] == RUNTIME_DIR_NAME or parts[0] == STDIN_FILE_NAME:
                continue
            target = (stage / Path(*parts)).resolve()
            if stage != target and stage not in target.parents:
                raise ValueError('sandbox_archive_path_invalid')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            total += max(0, int(member.size or 0))
            if total > max_bytes:
                raise ValueError('sandbox_output_too_large')
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                continue
            with target.open('wb') as handle:
                shutil.copyfileobj(source, handle, 1024 * 1024)
            os.chmod(target, int(member.mode or 0o600) & 0o777 or 0o600)
    return total


def _chown_tree(root: Path) -> None:
    chown = getattr(os, 'chown', None)
    if not callable(chown):
        return
    try:
        chown(root, DATA_UID, DATA_GID)
    except OSError:
        pass
    for path in root.rglob('*'):
        try:
            chown(path, DATA_UID, DATA_GID)
        except OSError:
            pass


def _replace_directory(target: Path, archive_raw: bytes, max_bytes: int) -> int:
    parent = target.parent
    stage = Path(tempfile.mkdtemp(prefix=f'.{target.name}.stage-', dir=str(parent))).resolve()
    backup = parent / f'.{target.name}.backup-{secrets.token_hex(8)}'
    try:
        total = _extract_archive_to_stage(archive_raw, stage, max_bytes)
        _chown_tree(stage)
        if target.exists():
            os.replace(target, backup)
        os.replace(stage, target)
        if backup.exists():
            shutil.rmtree(backup)
        return total
    except Exception:
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        if backup.exists() and target.exists():
            shutil.rmtree(backup, ignore_errors=True)


def _decode_output(value) -> tuple[str, str]:
    if isinstance(value, tuple):
        stdout_raw, stderr_raw = value
    else:
        stdout_raw, stderr_raw = value, b''
    def decode(item) -> str:
        if isinstance(item, bytes):
            return item.decode('utf-8', errors='replace')
        return str(item or '')
    return decode(stdout_raw), decode(stderr_raw)


def _prune_stale(client) -> None:
    global _LAST_PRUNE
    now = time.time()
    if now - _LAST_PRUNE < 60 or not _PRUNE_LOCK.acquire(blocking=False):
        return
    try:
        _LAST_PRUNE = now
        for container in client.containers.list(all=True, filters={'label': 'app3.sandbox.runner=1'})[:100]:
            try:
                started = float((container.labels or {}).get('app3.sandbox.started_at') or 0)
                if started and now - started < 900:
                    continue
                container.remove(force=True)
            except Exception:
                pass
        for volume in client.volumes.list(filters={'label': 'app3.sandbox.runner=1'})[:100]:
            try:
                created = float((volume.attrs.get('Labels') or {}).get('app3.sandbox.started_at') or 0)
                if created and now - created < 900:
                    continue
                volume.remove(force=True)
            except Exception:
                pass
    finally:
        _PRUNE_LOCK.release()


def _execute(payload: dict) -> dict:
    image = _validate_image(payload.get('image'))
    source = _sandbox_path(str(payload.get('sandbox_rel') or ''))
    cwd_rel = _safe_relative(str(payload.get('cwd') or ''), allow_empty=True, strict_names=False)
    argv = payload.get('argv') if isinstance(payload.get('argv'), list) else []
    argv = [str(item or '') for item in argv]
    if len(argv) != 3 or argv[0] != 'bash' or argv[1] != '-lc' or not argv[2].strip():
        raise ValueError('sandbox_argv_must_be_bash_lc')
    stdin_text = str(payload.get('stdin') or '')
    timeout_s = max(1.0, min(float(payload.get('timeout_s') or 30), 300.0))
    disk_max = _int_value(payload.get('disk_max_bytes'), 512 * 1024 * 1024, 1024 * 1024, 2 * 1024 * 1024 * 1024)
    memory = _size_value(payload.get('memory'), '512m')
    memory_swap = _size_value(payload.get('memory_swap'), memory)
    pids_limit = _int_value(payload.get('pids_limit'), 128, 16, 512)
    started = time.time()
    path_lock = _path_lock(source)
    path_lock.acquire()
    token = secrets.token_hex(10)
    labels = {'app3.sandbox.runner': '1', 'app3.sandbox.started_at': str(started)}
    client = None
    volume = None
    container = None
    timed_out = False
    try:
        client = _docker_client()
        _prune_stale(client)
        volume = client.volumes.create(name=f'app3-sandbox-run-{token}', labels=labels)
        archive_raw = _input_archive(source, stdin_text, disk_max)
        script = argv[2]
        if stdin_text:
            script = f'{script} < /mnt/data/{STDIN_FILE_NAME}'
        container = client.containers.create(
            image=image,
            command=['sleep', str(int(timeout_s) + 30)],
            name=f'app3-sandbox-run-{token}',
            labels=labels,
            network_disabled=True,
            read_only=True,
            cap_drop=['ALL'],
            security_opt=['no-new-privileges'],
            mem_limit=memory,
            memswap_limit=memory_swap,
            nano_cpus=_cpus_to_nano(payload.get('cpus')),
            pids_limit=pids_limit,
            ipc_mode='none',
            shm_size=_size_value(payload.get('shm_size'), '128m'),
            tmpfs={
                '/tmp': f'rw,noexec,nosuid,size={_size_value(payload.get("tmpfs_size"), "64m")}',
                '/var/tmp': f'rw,noexec,nosuid,size={_size_value(payload.get("var_tmpfs_size"), "32m")}',
            },
            volumes={volume.name: {'bind': '/mnt/data', 'mode': 'rw'}},
            ulimits=[
                Ulimit(name='nofile', soft=256, hard=256),
                Ulimit(name='nproc', soft=pids_limit, hard=pids_limit),
                Ulimit(name='fsize', soft=128 * 1024 * 1024, hard=128 * 1024 * 1024),
                Ulimit(name='core', soft=0, hard=0),
            ],
        )
        container.start()
        if archive_raw and not container.put_archive('/mnt/data', archive_raw):
            raise RuntimeError('sandbox_input_sync_failed')
        workdir = '/mnt/data' + (f'/{cwd_rel}' if cwd_rel else '')
        environment = {
            'HOME': '/mnt/data',
            'PYTHONIOENCODING': 'utf-8',
            'PYTHONUTF8': '1',
            'PYTHONSAFEPATH': '1',
            'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONNOUSERSITE': '1',
            'APP3_SKILLS_DIR': f'/mnt/data/{RUNTIME_DIR_NAME}/app3_skills',
            'PYTHONPATH': f'/mnt/data/{RUNTIME_DIR_NAME}/python_packages',
        }
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(container.exec_run, ['bash', '-lc', script], workdir=workdir, environment=environment, demux=True)
            try:
                result = future.result(timeout=timeout_s)
            except concurrent.futures.TimeoutError:
                timed_out = True
                container.kill()
                try:
                    result = future.result(timeout=5)
                except Exception:
                    result = type('ExecResult', (), {'exit_code': -1, 'output': (b'', '执行超时'.encode('utf-8'))})()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        try:
            container.exec_run(['rm', '-f', f'/mnt/data/{STDIN_FILE_NAME}'])
        except Exception:
            pass
        stream, _stat = container.get_archive('/mnt/data/.')
        output_archive = _read_archive(stream, disk_max)
        output_size = _replace_directory(source, output_archive, disk_max)
        stdout, stderr = _decode_output(result.output)
        return {
            'ok': True,
            'exit_code': -1 if timed_out else int(result.exit_code or 0),
            'stdout': stdout,
            'stderr': stderr,
            'timed_out': timed_out,
            'elapsed_ms': int((time.time() - started) * 1000),
            'output_bytes': output_size,
        }
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
        try:
            if volume is not None:
                volume.remove(force=True)
        except Exception:
            pass
        try:
            if client is not None:
                client.close()
        except Exception:
            pass
        path_lock.release()


def _run_image_command(image: str, command: list[str], *, timeout_s: float = 30.0) -> tuple[int, str, str]:
    client = _docker_client()
    token = secrets.token_hex(10)
    container = None
    try:
        container = client.containers.create(
            image=_validate_image(image),
            command=command,
            name=f'app3-sandbox-probe-{token}',
            labels={'app3.sandbox.runner': '1', 'app3.sandbox.started_at': str(time.time())},
            network_disabled=True,
            read_only=True,
            cap_drop=['ALL'],
            security_opt=['no-new-privileges'],
            mem_limit='256m',
            memswap_limit='256m',
            nano_cpus=1_000_000_000,
            pids_limit=64,
            tmpfs={'/tmp': 'rw,noexec,nosuid,size=32m'},
        )
        container.start()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(container.wait)
            try:
                status = future.result(timeout=max(5.0, min(timeout_s, 60.0)))
            except concurrent.futures.TimeoutError:
                container.kill()
                return -1, '', '执行超时'
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        logs = container.logs(stdout=True, stderr=False) or b''
        errors = container.logs(stdout=False, stderr=True) or b''
        return int((status or {}).get('StatusCode') or 0), logs.decode('utf-8', 'replace'), errors.decode('utf-8', 'replace')
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
        try:
            client.close()
        except Exception:
            pass


def _python_inventory(payload: dict) -> dict:
    script = '\n'.join((
        'import importlib.metadata as m, json, re',
        'rows = {}',
        'for distribution in m.distributions():',
        '    name = str(distribution.metadata.get("Name") or "").strip()',
        '    if not name: continue',
        '    key = re.sub(r"[-_.]+", "-", name.lower())',
        '    rows[key] = {"name": name, "version": str(distribution.version or "")}',
        'print(json.dumps(list(rows.values()), ensure_ascii=False))',
    ))
    code, stdout, stderr = _run_image_command(str(payload.get('image') or ''), ['python', '-c', script], timeout_s=30)
    if code != 0:
        raise RuntimeError((stderr or stdout or '沙盒 Python 包识别失败')[-1000:])
    rows = json.loads(stdout.strip() or '[]')
    if not isinstance(rows, list):
        raise RuntimeError('沙盒 Python 包清单格式无效')
    return {'ok': True, 'rows': rows[:2000]}


def _python_install(payload: dict) -> dict:
    image = _validate_image(payload.get('image'))
    spec = str(payload.get('package') or '').strip()
    pattern = r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}(?:\[[A-Za-z0-9_,.-]{1,120}\])?(?:==[A-Za-z0-9][A-Za-z0-9._+!-]{0,80})?$'
    if not re.fullmatch(pattern, spec):
        raise ValueError('python_package_spec_invalid')
    index_url = str(os.getenv('SANDBOX_PIP_INDEX_URL', 'https://pypi.tuna.tsinghua.edu.cn/simple') or '').strip()
    parsed = urlparse(index_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('SANDBOX_PIP_INDEX_URL_invalid')
    EXTENSION_ROOT.mkdir(parents=True, exist_ok=True)
    lock = _path_lock(EXTENSION_ROOT)
    lock.acquire()
    client = None
    container = None
    volume = None
    token = secrets.token_hex(10)
    started = time.time()
    try:
        client = _docker_client()
        labels = {'app3.sandbox.runner': '1', 'app3.sandbox.started_at': str(started)}
        volume = client.volumes.create(name=f'app3-sandbox-pip-{token}', labels=labels)
        container = client.containers.create(
            image=image,
            command=['sleep', '300'],
            name=f'app3-sandbox-pip-{token}',
            labels=labels,
            network_mode='bridge',
            read_only=True,
            cap_drop=['ALL'],
            security_opt=['no-new-privileges'],
            mem_limit='768m',
            memswap_limit='768m',
            nano_cpus=1_500_000_000,
            pids_limit=128,
            tmpfs={'/tmp': 'rw,nosuid,size=256m'},
            volumes={volume.name: {'bind': '/opt/extensions', 'mode': 'rw'}},
        )
        container.start()
        existing = _input_archive(EXTENSION_ROOT, '', 1024 * 1024 * 1024, include_runtime=False)
        if existing and not container.put_archive('/opt/extensions', existing):
            raise RuntimeError('python_extensions_sync_failed')
        command = [
            'python', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '--upgrade',
            '--target', '/opt/extensions', '--index-url', index_url, spec,
        ]
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(container.exec_run, command, demux=True)
            try:
                result = future.result(timeout=240)
            except concurrent.futures.TimeoutError:
                container.kill()
                raise RuntimeError('pip install 执行超时')
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        stdout, stderr = _decode_output(result.output)
        if int(result.exit_code or 0) != 0:
            raise RuntimeError((stdout + '\n' + stderr).strip()[-8000:] or f'pip install 退出码 {result.exit_code}')
        stream, _stat = container.get_archive('/opt/extensions/.')
        raw = _read_archive(stream, 1024 * 1024 * 1024)
        _replace_directory(EXTENSION_ROOT, raw, 1024 * 1024 * 1024)
        return {'ok': True, 'installed': spec, 'stdout': stdout[-8000:], 'stderr': stderr[-8000:]}
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
        if volume is not None:
            try:
                volume.remove(force=True)
            except Exception:
                pass
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        lock.release()


@app.get('/healthz')
def healthz():
    docker_ok = False
    image_available = False
    version = ''
    error = ''
    try:
        client = _docker_client()
        version = str(client.version().get('Version') or '')
        docker_ok = True
        if ALLOWED_IMAGE:
            try:
                client.images.get(ALLOWED_IMAGE)
                image_available = True
            except Exception:
                image_available = False
        client.close()
    except Exception as exc:
        error = type(exc).__name__
    return jsonify({
        'ok': docker_ok and image_available,
        'service': SERVICE_NAME,
        'docker_ok': docker_ok,
        'docker_version': version,
        'image': ALLOWED_IMAGE,
        'image_available': image_available,
        'error': error,
    }), 200 if docker_ok and image_available else 503


@app.post('/v1/run')
def run_route():
    ok, error = _verify_request()
    if not ok:
        return jsonify({'ok': False, 'error': error}), 401
    payload = request.get_json(force=False, silent=True) or {}
    try:
        return jsonify(_execute(payload))
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': 'sandbox_runner_failed', 'message': f'{type(exc).__name__}: {exc}'[:1200]}), 500


@app.post('/v1/python/inventory')
def python_inventory_route():
    ok, error = _verify_request()
    if not ok:
        return jsonify({'ok': False, 'error': error}), 401
    try:
        return jsonify(_python_inventory(request.get_json(force=False, silent=True) or {}))
    except Exception as exc:
        return jsonify({'ok': False, 'error': 'sandbox_python_inventory_failed', 'message': f'{type(exc).__name__}: {exc}'[:1200]}), 500


@app.post('/v1/python/install')
def python_install_route():
    ok, error = _verify_request()
    if not ok:
        return jsonify({'ok': False, 'error': error}), 401
    try:
        return jsonify(_python_install(request.get_json(force=False, silent=True) or {}))
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'ok': False, 'error': 'sandbox_python_install_failed', 'message': f'{type(exc).__name__}: {exc}'[:1200]}), 500


def main() -> None:
    from waitress import serve

    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    EXTENSION_ROOT.mkdir(parents=True, exist_ok=True)
    _secret()
    serve(app, host='0.0.0.0', port=int(os.getenv('SANDBOX_RUNNER_PORT', '8767') or 8767), threads=8)


if __name__ == '__main__':
    main()
