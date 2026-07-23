import os
import io
import json
import time
import asyncio
import base64
import urllib.parse
import html
import re
import traceback
import tempfile
import subprocess
import shutil
import logging
import logging.handlers
import shlex
import sys
import math
from html.parser import HTMLParser
from email.message import EmailMessage
from urllib.parse import urlparse, urlunparse, quote, parse_qs, urlencode
import ipaddress
import datetime
import hashlib
import hmac
import uuid
import requests
import contextvars
import threading
import random
import email.utils
import smtplib
import ssl
import secrets
import sqlite3
import contextlib
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    import trafilatura  # type: ignore
except Exception:
    trafilatura = None  # type: ignore

from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context, redirect, g
from werkzeug.exceptions import RequestEntityTooLarge

from openai import OpenAI
import httpx

from pypdf import PdfReader
from docx import Document
import openpyxl


APP_NAME = "Apervia"
_APP_VERSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'VERSION')
try:
    with open(_APP_VERSION_FILE, 'r', encoding='utf-8') as _version_handle:
        APP_VERSION = str(_version_handle.read() or '').strip()[:80]
except OSError:
    APP_VERSION = ''
if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', APP_VERSION):
    raise RuntimeError('VERSION 文件缺失或格式无效')
APP_BUILD_VERSION = APP_VERSION
APP_BUILD_SHA = str(os.getenv('APP_BUILD_SHA', 'unknown') or 'unknown').strip()[:80]


def _app_build_info() -> dict:
    return {
        'version': APP_BUILD_VERSION,
        'sha': APP_BUILD_SHA,
    }


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, '1' if default else '0') or '').strip().lower()
    return raw not in {'', '0', 'false', 'off', 'no', 'disabled'}


def _env_port(name: str, default: int) -> int:
    try:
        return max(1, min(int(str(os.getenv(name, str(default)) or default).strip()), 65535))
    except Exception:
        return default


def _normalize_public_origin(value: str = '') -> str:
    raw = str(value or '').strip().rstrip('/')
    if not raw:
        return ''
    parsed = urlparse(raw)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise RuntimeError('APP_PUBLIC_ORIGIN 必须是完整的 http/https 站点源地址')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError('APP_PUBLIC_ORIGIN 不能包含账号、密码、查询参数或片段')
    if str(parsed.path or '') not in {'', '/'}:
        raise RuntimeError('APP_PUBLIC_ORIGIN 当前只支持部署在域名根路径')
    return f'{parsed.scheme}://{parsed.netloc}'


PORT = _env_port('APP_PORT', 8002)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DATA_DIR = os.path.abspath(str(os.getenv('APP_DATA_DIR', BASE_DIR) or BASE_DIR).strip())
APP_PUBLIC_MODE = _env_flag('APP_PUBLIC_MODE', False)
APP_PUBLIC_ORIGIN = _normalize_public_origin(os.getenv('APP_PUBLIC_ORIGIN', ''))
if APP_PUBLIC_MODE and not APP_PUBLIC_ORIGIN:
    raise RuntimeError('APP_PUBLIC_MODE=1 时必须配置 APP_PUBLIC_ORIGIN')
if APP_PUBLIC_MODE and not APP_PUBLIC_ORIGIN.startswith('https://'):
    raise RuntimeError('APP_PUBLIC_MODE=1 时 APP_PUBLIC_ORIGIN 必须使用 HTTPS')


def _app_data_path(*parts: str) -> str:
    return os.path.join(APP_DATA_DIR, *[str(part) for part in parts])


def _app_external_origin() -> str:
    if APP_PUBLIC_ORIGIN:
        return APP_PUBLIC_ORIGIN
    try:
        return str(request.host_url or '').strip().rstrip('/')
    except Exception:
        return ''


def _app_external_url(path: str = '') -> str:
    origin = _app_external_origin()
    suffix = '/' + str(path or '').lstrip('/')
    return origin + suffix if origin else suffix


def _app_cookie_secure() -> bool:
    if APP_PUBLIC_MODE:
        return True
    try:
        return bool(request.is_secure)
    except Exception:
        return False


os.makedirs(APP_DATA_DIR, exist_ok=True)
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_SCOPE_LOCAL = "local"
UPLOAD_SCOPE_PUBLIC = "public"
UPLOAD_DIR_LOCAL = _app_data_path("uploads_local")
UPLOAD_DIR_PUBLIC = _app_data_path("uploads_public")
GENERATED_DIR_LOCAL = _app_data_path("generated_local")
GENERATED_DIR_PUBLIC = _app_data_path("generated_public")
REMOTE_IMAGE_CACHE_DIR_DEFAULT = _app_data_path("remote_image_cache")

app = Flask(__name__, static_folder=STATIC_DIR)
_proxy_fix_x_for = max(0, min(8, int(os.getenv('TRUST_PROXY_X_FOR', '0') or '0')))
_proxy_fix_x_proto = max(0, min(8, int(os.getenv('TRUST_PROXY_X_PROTO', '0') or '0')))
_proxy_fix_x_host = max(0, min(8, int(os.getenv('TRUST_PROXY_X_HOST', '0') or '0')))
_proxy_fix_x_port = max(0, min(8, int(os.getenv('TRUST_PROXY_X_PORT', '0') or '0')))
_proxy_fix_x_prefix = max(0, min(8, int(os.getenv('TRUST_PROXY_X_PREFIX', '0') or '0')))
if any((_proxy_fix_x_for, _proxy_fix_x_proto, _proxy_fix_x_host, _proxy_fix_x_port, _proxy_fix_x_prefix)):
    app.wsgi_app = ProxyFix(  # type: ignore[assignment]
        app.wsgi_app,
        x_for=_proxy_fix_x_for,
        x_proto=_proxy_fix_x_proto,
        x_host=_proxy_fix_x_host,
        x_port=_proxy_fix_x_port,
        x_prefix=_proxy_fix_x_prefix,
    )


class _RequestContextFilter(logging.Filter):
    def filter(self, record):
        try:
            record.request_id = str(getattr(g, 'request_id', '') or '-')
        except Exception:
            record.request_id = '-'
        try:
            record.request_path = str(getattr(request, 'path', '') or '-')
        except Exception:
            record.request_path = '-'
        return True


_ORIG_LOG_RECORD_FACTORY = logging.getLogRecordFactory()


def _request_context_log_record_factory(*args, **kwargs):
    record = _ORIG_LOG_RECORD_FACTORY(*args, **kwargs)
    try:
        record.request_id = str(getattr(g, 'request_id', '') or '-')
    except Exception:
        record.request_id = '-'
    try:
        record.request_path = str(getattr(request, 'path', '') or '-')
    except Exception:
        record.request_path = '-'
    return record


def _is_local_upload_host(host: str) -> bool:
    raw = str(host or '').strip().lower()
    if not raw:
        return True
    if raw.startswith('['):
        raw = raw.split(']')[0].strip('[]')
    raw = raw.split(':', 1)[0].strip()
    if raw in {'127.0.0.1', 'localhost', '::1'}:
        return True
    try:
        ip_obj = ipaddress.ip_address(raw)
        return bool(ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local)
    except Exception:
        return False


def _request_has_public_proxy_context() -> bool:
    """Detect real public traffic even when cloudflared forwards to 127.0.0.1.

    Some tunnels/proxies preserve the browser Host header, while others expose the
    local upstream as request.host and only keep the public site in forwarded/CF
    headers. Treat those headers as authoritative for storage scope and transport
    selection, otherwise public uploads can be misclassified as local and the
    server may return huge base64 payloads or keep a long request open until
    Cloudflare cuts it with 524.
    """
    if APP_PUBLIC_MODE:
        return True

    try:
        headers = request.headers
    except Exception:
        return False

    for name in ('CF-Connecting-IP', 'CF-Ray', 'Cf-Connecting-Ip', 'Cf-Ray'):
        try:
            if str(headers.get(name) or '').strip():
                return True
        except Exception:
            pass

    for name in ('X-Forwarded-Host', 'X-Original-Host', 'X-Host'):
        try:
            raw = str(headers.get(name) or '').split(',', 1)[0].strip()
        except Exception:
            raw = ''
        if raw and not _is_local_upload_host(raw):
            return True

    try:
        forwarded_proto = str(headers.get('X-Forwarded-Proto') or '').split(',', 1)[0].strip().lower()
        forwarded_for = str(headers.get('X-Forwarded-For') or '').strip()
        if forwarded_proto == 'https' and forwarded_for:
            return True
    except Exception:
        pass

    try:
        forwarded = str(headers.get('Forwarded') or '').strip()
    except Exception:
        forwarded = ''
    if forwarded:
        lowered = forwarded.lower()
        try:
            if 'proto=https' in lowered:
                return True
        except Exception:
            pass
        try:
            for_match = re.search(r'for=(\"?)([^;,\"]+)\1', forwarded, flags=re.I)
            if for_match:
                forwarded_for_host = str(for_match.group(2) or '').strip().strip('[]')
                if forwarded_for_host and not _is_local_upload_host(forwarded_for_host):
                    return True
        except Exception:
            pass

    return False


def _normalize_upload_scope(scope: str | None = None) -> str:
    normalized = str(scope or '').strip().lower()
    if normalized in {UPLOAD_SCOPE_LOCAL, UPLOAD_SCOPE_PUBLIC}:
        return normalized
    return UPLOAD_SCOPE_LOCAL


def _request_upload_scope() -> str:
    try:
        if _request_has_public_proxy_context():
            return UPLOAD_SCOPE_PUBLIC
    except Exception:
        pass
    try:
        host = str(request.host or '').strip()
    except Exception:
        host = ''
    return UPLOAD_SCOPE_LOCAL if _is_local_upload_host(host) else UPLOAD_SCOPE_PUBLIC


def _parse_upload_scope(raw: str | None = None) -> str:
    value = str(raw or '').strip().lower()
    if value in {UPLOAD_SCOPE_LOCAL, UPLOAD_SCOPE_PUBLIC}:
        return value
    return ''


def _request_upload_scope_arg() -> str:
    try:
        return _parse_upload_scope(request.args.get('scope'))
    except Exception:
        return ''


def _request_upload_scope_for_access() -> str:
    return _request_upload_scope_arg() or _request_upload_scope()

def _is_public_request_scope() -> bool:
    try:
        return _request_upload_scope() == UPLOAD_SCOPE_PUBLIC
    except Exception:
        return False


def _public_stream_transport_error_payload() -> dict:
    return {
        "error": "公网稳定模式下已停用直连流式通道，请改用 /api3/chat_async/start + /api3/chat_async/poll。",
        "code": "public_stream_transport_disabled",
        "transport": "chat_async_poll",
    }



def _append_scope_to_file_url(path: str, scope: str | None = None) -> str:
    raw_path = str(path or '').strip()
    normalized = _parse_upload_scope(scope)
    if not raw_path or not normalized:
        return raw_path
    separator = '&' if '?' in raw_path else '?'
    return f'{raw_path}{separator}scope={urllib.parse.quote(normalized)}'


def _build_uploaded_file_urls(filename: str, scope: str | None = None) -> tuple[str, str]:
    save_name = str(filename or '').strip()
    if not save_name:
        return '', ''
    normalized = _parse_upload_scope(scope) or _request_upload_scope()
    view_url = _append_scope_to_file_url(f'/api3/uploads/{urllib.parse.quote(save_name)}', normalized)
    download_url = _append_scope_to_file_url(f'/api3/download/{urllib.parse.quote(save_name)}', normalized)
    return view_url, download_url


def _build_generated_file_urls(filename: str, scope: str | None = None) -> tuple[str, str]:
    save_name = str(filename or '').strip()
    if not save_name:
        return '', ''
    normalized = _parse_upload_scope(scope) or _request_upload_scope()
    view_url = _append_scope_to_file_url(f'/api3/generated-files/{urllib.parse.quote(save_name)}', normalized)
    download_url = _append_scope_to_file_url(f'/api3/generated-download/{urllib.parse.quote(save_name)}', normalized)
    return view_url, download_url


def _extract_upload_scope_from_url(url: str) -> str:
    raw = str(url or '').strip()
    if not raw:
        return ''
    try:
        parsed = urlparse(raw)
        values = parse_qs(str(parsed.query or ''), keep_blank_values=False)
        return _parse_upload_scope(((values.get('scope') or [''])[0]))
    except Exception:
        return ''


def _upload_dir_for_scope(scope: str | None = None, ensure: bool = True) -> str:
    normalized = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    path = UPLOAD_DIR_LOCAL if normalized == UPLOAD_SCOPE_LOCAL else UPLOAD_DIR_PUBLIC
    if ensure:
        os.makedirs(path, exist_ok=True)
    return path


def _current_upload_dir(ensure: bool = True) -> str:
    return _upload_dir_for_scope(None, ensure=ensure)


def _generated_dir_for_scope(scope: str | None = None, ensure: bool = True) -> str:
    normalized = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    path = GENERATED_DIR_LOCAL if normalized == UPLOAD_SCOPE_LOCAL else GENERATED_DIR_PUBLIC
    if ensure:
        os.makedirs(path, exist_ok=True)
    return path


def _current_generated_dir(ensure: bool = True) -> str:
    return _generated_dir_for_scope(None, ensure=ensure)


_UPLOAD_STORAGE_PRUNE_LOCK = threading.Lock()
_GENERATED_STORAGE_PRUNE_LOCK = threading.Lock()


def _upload_dir_size_limit_bytes(scope: str | None = None) -> int:
    normalized = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    if normalized == UPLOAD_SCOPE_LOCAL:
        raw = app_getenv('UPLOAD_DIR_LOCAL_MAX_BYTES', str(1024 * 1024 * 1024))
    else:
        raw = app_getenv('UPLOAD_DIR_PUBLIC_MAX_BYTES', str(1024 * 1024 * 1024))
    try:
        return max(0, int(str(raw or '0').strip()))
    except Exception:
        return 0


def _prune_upload_dir(scope: str | None = None, keep_paths: list[str] | None = None, incoming_bytes: int = 0) -> dict:
    normalized = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    root = _upload_dir_for_scope(normalized, ensure=True)
    max_bytes = _upload_dir_size_limit_bytes(normalized)
    if max_bytes <= 0:
        return {'ok': True, 'scope': normalized, 'max_bytes': max_bytes, 'total_bytes': 0, 'deleted': []}

    keep = {os.path.abspath(str(p)) for p in (keep_paths or []) if str(p or '').strip()}
    deleted: list[str] = []
    with _UPLOAD_STORAGE_PRUNE_LOCK:
        files = []
        total = 0
        try:
            for name in os.listdir(root):
                fp = os.path.join(root, name)
                try:
                    st = os.stat(fp)
                except Exception:
                    continue
                if not os.path.isfile(fp):
                    continue
                size = int(st.st_size)
                total += size
                files.append((fp, float(st.st_mtime), size))
        except Exception:
            return {'ok': False, 'scope': normalized, 'max_bytes': max_bytes, 'total_bytes': 0, 'deleted': []}

        target_total = max(0, max_bytes - max(0, int(incoming_bytes or 0)))
        if total <= target_total:
            return {'ok': True, 'scope': normalized, 'max_bytes': max_bytes, 'total_bytes': total, 'deleted': deleted}

        files.sort(key=lambda x: (x[1], x[0]))
        removable = [item for item in files if os.path.abspath(item[0]) not in keep]
        for fp, _mt, size in removable:
            if total <= target_total:
                break
            try:
                os.remove(fp)
                try:
                    post_delete = globals().get('_storage_quota_after_local_file_deleted')
                    if callable(post_delete):
                        post_delete(fp, namespace='uploads', scope=normalized, filename=os.path.basename(fp), reason='upload_dir_prune')
                except Exception:
                    pass
                total -= size
                deleted.append(os.path.basename(fp))
            except Exception:
                continue

    if deleted:
        app_logger.info('[upload_storage] pruned scope=%s deleted=%s total=%s max=%s', normalized, len(deleted), total, max_bytes)
    elif total > max_bytes:
        app_logger.warning('[upload_storage] over_limit_but_preserved scope=%s total=%s max=%s keep=%s incoming=%s', normalized, total, max_bytes, len(keep), int(incoming_bytes or 0))
    return {'ok': True, 'scope': normalized, 'max_bytes': max_bytes, 'total_bytes': total, 'deleted': deleted}


def _resolve_uploaded_file_dir(filename: str, scope: str | None = None) -> str | None:
    fname = str(filename or '').strip()
    if not fname:
        return None

    preferred_scope = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    candidates: list[str] = []
    for candidate in (preferred_scope, UPLOAD_SCOPE_LOCAL, UPLOAD_SCOPE_PUBLIC):
        normalized = _normalize_upload_scope(candidate)
        if normalized in candidates:
            continue
        candidates.append(normalized)

    for candidate_scope in candidates:
        base_dir = _upload_dir_for_scope(candidate_scope, ensure=True)
        try:
            if os.path.exists(os.path.join(base_dir, fname)):
                return base_dir
        except Exception:
            continue
    try:
        restore_scope = preferred_scope
        restored = _object_storage_restore_to_local('uploads', restore_scope, fname)
        if restored and os.path.exists(restored):
            return os.path.dirname(restored)
    except Exception:
        pass
    return None




def _build_upload_storage_ref(filename: str, scope: str | None = None) -> str:
    save_name = str(filename or '').strip()
    if not save_name:
        return ''
    normalized = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    return f"upload://{normalized}/{urllib.parse.quote(save_name)}"


def _parse_upload_storage_ref(ref: str) -> tuple[str, str]:
    raw = str(ref or '').strip()
    if not raw.lower().startswith('upload://'):
        return '', ''
    body = raw[len('upload://'):].strip()
    if not body:
        return '', ''
    scope, _, filename = body.partition('/')
    scope = _parse_upload_scope(scope)
    filename = urllib.parse.unquote(str(filename or '').strip('/'))
    if not scope or not filename:
        return '', ''
    return scope, filename


def _upload_storage_ref_to_local_path(ref: str) -> str:
    scope, filename = _parse_upload_storage_ref(ref)
    if not scope or not filename:
        return ''
    base_dir = _resolve_uploaded_file_dir(filename, scope=scope)
    if not base_dir:
        return ''
    fp = os.path.join(base_dir, filename)
    return fp if os.path.isfile(fp) else ''


def _read_upload_storage_ref_bytes(ref: str) -> tuple[bytes, str]:
    fp = _upload_storage_ref_to_local_path(ref)
    if fp:
        try:
            with open(fp, 'rb') as f:
                raw = f.read()
            mime = UPLOAD_IMAGE_MIME_BY_EXT.get(_ext_of(fp), '')
            return raw, mime
        except Exception:
            pass
    scope, filename = _parse_upload_storage_ref(ref)
    if scope and filename:
        raw, mime = _object_storage_read_bytes('uploads', scope, filename)
        if raw:
            return raw, mime or UPLOAD_IMAGE_MIME_BY_EXT.get(_ext_of(filename), '')
    return b'', ''


def _image_item_attachment_key(item: dict | None = None) -> str:
    row = dict(item or {})
    keys = [
        row.get('attachment_id'),
        row.get('model_storage_ref'),
        row.get('storage_ref'),
        row.get('persisted_url'),
        row.get('server_url'),
        ((row.get('image_url') or {}).get('url') if isinstance(row.get('image_url'), dict) else ''),
        row.get('_preview_url'),
    ]
    for candidate in keys:
        value = str(candidate or '').strip()
        if value:
            return value
    return ''


def _image_item_model_candidates(item: dict | None = None) -> list[str]:
    row = dict(item or {})
    img_obj = row.get('image_url') or {}
    candidates = [
        row.get('model_storage_ref'),
        row.get('storage_ref'),
        img_obj.get('url') if isinstance(img_obj, dict) else '',
        row.get('persisted_url'),
        row.get('server_url'),
        row.get('url'),
        row.get('_preview_url'),
        row.get('_source_url'),
    ]
    out = []
    seen = set()
    for candidate in candidates:
        value = str(candidate or '').strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
def _generated_dir_size_limit_bytes(scope: str | None = None) -> int:
    normalized = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    if normalized == UPLOAD_SCOPE_LOCAL:
        raw = app_getenv('GENERATED_DIR_LOCAL_MAX_BYTES', str(app_getenv('UPLOAD_DIR_LOCAL_MAX_BYTES', str(1024 * 1024 * 1024))))
    else:
        raw = app_getenv('GENERATED_DIR_PUBLIC_MAX_BYTES', str(app_getenv('UPLOAD_DIR_PUBLIC_MAX_BYTES', str(1024 * 1024 * 1024))))
    try:
        return max(0, int(str(raw or '0').strip()))
    except Exception:
        return 0


def _prune_generated_dir(scope: str | None = None, keep_paths: list[str] | None = None, incoming_bytes: int = 0) -> dict:
    normalized = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    root = _generated_dir_for_scope(normalized, ensure=True)
    max_bytes = _generated_dir_size_limit_bytes(normalized)
    if max_bytes <= 0:
        return {'ok': True, 'scope': normalized, 'max_bytes': max_bytes, 'total_bytes': 0, 'deleted': []}

    keep = {os.path.abspath(str(p)) for p in (keep_paths or []) if str(p or '').strip()}
    deleted: list[str] = []
    with _GENERATED_STORAGE_PRUNE_LOCK:
        files = []
        total = 0
        try:
            for name in os.listdir(root):
                fp = os.path.join(root, name)
                try:
                    st = os.stat(fp)
                except Exception:
                    continue
                if not os.path.isfile(fp):
                    continue
                size = int(st.st_size)
                total += size
                files.append((fp, float(st.st_mtime), size))
        except Exception:
            return {'ok': False, 'scope': normalized, 'max_bytes': max_bytes, 'total_bytes': 0, 'deleted': []}

        target_total = max(0, max_bytes - max(0, int(incoming_bytes or 0)))
        if total <= target_total:
            return {'ok': True, 'scope': normalized, 'max_bytes': max_bytes, 'total_bytes': total, 'deleted': deleted}

        files.sort(key=lambda x: (x[1], x[0]))
        removable = [item for item in files if os.path.abspath(item[0]) not in keep]
        for fp, _mt, size in removable:
            if total <= target_total:
                break
            try:
                os.remove(fp)
                try:
                    post_delete = globals().get('_storage_quota_after_local_file_deleted')
                    if callable(post_delete):
                        post_delete(fp, namespace='generated', scope=normalized, filename=os.path.basename(fp), reason='generated_dir_prune')
                except Exception:
                    pass
                total -= size
                deleted.append(os.path.basename(fp))
            except Exception:
                continue

    if deleted:
        app_logger.info('[generated_storage] pruned scope=%s deleted=%s total=%s max=%s', normalized, len(deleted), total, max_bytes)
    elif total > max_bytes:
        app_logger.warning('[generated_storage] over_limit_but_preserved scope=%s total=%s max=%s keep=%s incoming=%s', normalized, total, max_bytes, len(keep), int(incoming_bytes or 0))
    return {'ok': True, 'scope': normalized, 'max_bytes': max_bytes, 'total_bytes': total, 'deleted': deleted}


def _resolve_generated_file_dir(filename: str, scope: str | None = None) -> str | None:
    fname = str(filename or '').strip()
    if not fname:
        return None

    preferred_scope = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    candidates: list[str] = []
    for candidate in (preferred_scope, UPLOAD_SCOPE_LOCAL, UPLOAD_SCOPE_PUBLIC):
        normalized = _normalize_upload_scope(candidate)
        if normalized in candidates:
            continue
        candidates.append(normalized)

    for candidate_scope in candidates:
        base_dir = _generated_dir_for_scope(candidate_scope, ensure=True)
        try:
            if os.path.exists(os.path.join(base_dir, fname)):
                return base_dir
        except Exception:
            continue
    try:
        restore_scope = preferred_scope
        restored = _object_storage_restore_to_local('generated', restore_scope, fname)
        if restored and os.path.exists(restored):
            return os.path.dirname(restored)
    except Exception:
        pass
    return None

# ====== Pure frontend configuration ======
# The app no longer reads .env.app3 or process environment variables.
# Values come from: request overrides (front-end) -> built-in defaults.
APP_DEFAULTS = {
    "LOG_LEVEL": "INFO",
    "SEARXNG_URL": "",
    "SEARXNG_API_PATH": "/search",
    "SEARCH_PROVIDER": "uapipro",
    "SEARCH_FALLBACK_PROVIDER": "none",
    "WHOOGLE_URL": "",
    "EXTERNAL_SEARCH_URL": "",
    "EXTERNAL_SEARCH_API_KEY": "",
    "EXTERNAL_IMAGE_SEARCH_URL": "",
    "EXTERNAL_IMAGE_SEARCH_API_KEY": "",
    "UAPIPRO_BASE_URL": "https://uapis.cn/api/v1",
    "UAPIPRO_API_KEY": "",
    "IMAGE_SEARCH_PROVIDER": "searxng",
    "IMAGE_SEARCH_FALLBACK_PROVIDER": "serper",
    "WEB_SEARCH_MIN_EFFECTIVE_RESULTS": "3",
    "WEB_SEARCH_TARGET_RESULTS": "6",
    "IMAGE_SEARCH_MIN_EFFECTIVE_RESULTS": "5",
    "IMAGE_SEARCH_TARGET_RESULTS": "8",
    "CONTENT_PROVIDER": "auto",
    "CONTENT_FALLBACK_PROVIDER": "tavily",
    "SERPER_API_KEY": "",
    "TAVILY_API_KEY": "",
    "TAVILY_EXTRACT_DEPTH": "basic",
    "PLAYWRIGHT_ENABLE": "1",
    "PLAYWRIGHT_TIMEOUT": "18",
    "WEB_FETCH_AUTO_RENDER": "1",
    "WEB_FETCH_RENDER_MODE": "smart",
    "WEB_FETCH_CAPTURE_JSON_APIS": "0",
    "WEB_FETCH_PW_CAPTURE_TIMEOUT": "6",
    "WEB_FETCH_PW_CHANNEL": "msedge",
    "WEB_FETCH_PW_WAIT_UNTIL": "networkidle",
    "WEB_FETCH_UA": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "WEB_FETCH_ACCEPT_LANGUAGE": "zh-TW,zh;q=0.9,en;q=0.6",
    "GPT_TLS_VERIFY": "1",
    "WEB_SEARCH_TLS_VERIFY": "1",
    "WEB_SEARCH_TRUST_ENV": "0",
    "HTTPX_MAX_KEEPALIVE": "24",
    "HTTPX_MAX_CONNECTIONS": "64",
    "HTTPX_KEEPALIVE_EXPIRY": "15",
    "WEB_FETCH_MAX_KEEPALIVE": "12",
    "WEB_FETCH_MAX_CONNECTIONS": "32",
    "WEB_FETCH_KEEPALIVE_EXPIRY": "15",
    "WEB_FETCH_HOST_MIN_INTERVAL": "0.45",
    "WEB_FETCH_HOST_MAX_WAIT": "1.5",
    "WEB_FETCH_HOST_FAILURE_COOLDOWN": "10",
    "WEB_FETCH_HOST_MAX_COOLDOWN": "60",
    "HOST_FETCH_DB_FILE": _app_data_path("host_fetch_state.db"),
    "HOST_FETCH_STATE_TTL": str(14 * 24 * 3600),
    "HOST_FETCH_PERSIST_DEBOUNCE": "2.0",
    "FETCH_BUDGET_TOTAL_MAX_ACTIVE": "12",
    "WEB_FETCH_BUDGET_MAX_ACTIVE": "6",
    "REMOTE_IMAGE_BUDGET_MAX_ACTIVE": "3",
    "FETCH_BUDGET_PER_HOST_MAX_ACTIVE": "2",
    "WEB_FETCH_BUDGET_PER_HOST_MAX_ACTIVE": "2",
    "REMOTE_IMAGE_BUDGET_PER_HOST_MAX_ACTIVE": "1",
    "FETCH_BUDGET_ACQUIRE_TIMEOUT": "2.5",
    "WEB_FETCH_BUDGET_ACQUIRE_TIMEOUT": "3.0",
    "REMOTE_IMAGE_BUDGET_ACQUIRE_TIMEOUT": "3.5",
    "REMOTE_IMAGE_CACHE_DIR": REMOTE_IMAGE_CACHE_DIR_DEFAULT,
    "REMOTE_IMAGE_CACHE_TTL": str(7 * 24 * 3600),
    "REMOTE_IMAGE_CACHE_MAX_BYTES": str(256 * 1024 * 1024),
    "UPLOAD_DIR_LOCAL_MAX_BYTES": str(512 * 1024 * 1024),
    "UPLOAD_DIR_PUBLIC_MAX_BYTES": str(1024 * 1024 * 1024),
    "GENERATED_DIR_LOCAL_MAX_BYTES": str(512 * 1024 * 1024),
    "GENERATED_DIR_PUBLIC_MAX_BYTES": str(2 * 1024 * 1024 * 1024),
    "STORAGE_CLEANUP_FREE_BYTES": str(8 * 1024 * 1024 * 1024),
    "STORAGE_MIN_FREE_BYTES": str(5 * 1024 * 1024 * 1024),
    "APP_STORAGE_MAX_BYTES": str(12 * 1024 * 1024 * 1024),
    "ACCOUNT_STORAGE_DEFAULT_MAX_BYTES": str(1024 * 1024 * 1024),
    "ACCOUNT_STORAGE_ANONYMOUS_MAX_BYTES": str(128 * 1024 * 1024),
    "UPLOAD_CHUNKS_MAX_BYTES": str(1024 * 1024 * 1024),
    "AUTH_CHAT_BACKUP_MAX_BYTES": str(512 * 1024 * 1024),
    "KB_DB_MAX_BYTES": str(2 * 1024 * 1024 * 1024),
    "KB_OWNER_MAX_BYTES": str(512 * 1024 * 1024),
    "KB_SINGLE_IMPORT_MAX_BYTES": str(80 * 1024 * 1024),
    "FILE_TEXT_STORE_MAX_BYTES": str(1024 * 1024 * 1024),
    "FILE_REGISTRY_MAX_RECORDS": "1000",
    "FILE_REGISTRY_MAX_BYTES": str(32 * 1024 * 1024),
    "REMOTE_IMAGE_FAIL_TTL": "12",
    "REMOTE_IMAGE_TLS_CERT_FAIL_COOLDOWN": "600",
    "REMOTE_IMAGE_TIMEOUT": "10.5",
    "REMOTE_IMAGE_PER_HOST_CONCURRENCY": "3",
    "FAVICON_CACHE_TTL": str(30 * 24 * 3600),
    "FAVICON_FETCH_TIMEOUT": "4.5",
    "FAVICON_MAX_BYTES": str(256 * 1024),
    "FAVICON_CACHE_MAX_BYTES": str(64 * 1024 * 1024),
    "REPLY_IMAGE_MAX_PER_HOST": "6",
    "AUTO_WEB_K_RESULTS": "6",
    "AUTO_WEB_FAST_MAX_PAGES": "2",
    "AUTO_WEB_MAX_PAGES": "3",
    "AUTO_WEB_MAX_QUERIES": "2",
    "AUTO_WEB_FETCH_WORKERS": "6",
    "AUTO_WEB_PAGE_TIMEOUT": "4",
    "AUTO_WEB_PAGE_MAX_CHARS": "4500",
    "AUTO_WEB_PAGE_SNIPPET_CHARS": "1800",
    "MAX_WEB_SEARCH_CALLS": "1",
    "CHAT_THINKING_TYPE": "auto",
    "TOOL_PREFETCH_THINKING_TYPE": "disabled",
    "WEB_SEARCH_PLANNER_THINKING_TYPE": "disabled",
    "QUERY_GENERATION_THINKING_TYPE": "disabled",
    "WEATHER_GEOCODE_CACHE_TTL": str(12 * 3600),
    "WEATHER_REVERSE_GEOCODE_CACHE_TTL": str(12 * 3600),
    "WEATHER_FORECAST_CACHE_TTL": "180",
    "WEATHER_FORECAST_CACHE_ROUND": "3",
    "IMAGE_SEARCH_MAX_QUERIES": "3",
    "REPLY_IMAGE_MAX_CANDIDATES": "42",
    "REPLY_IMAGE_VERIFY_WORKERS": "8",
    "REPLY_IMAGE_REQUEST_TIMEOUT": "2.6",
    "REPLY_IMAGE_FALLBACK_TIMEOUT": "4.5",
    "REPLY_IMAGE_TOTAL_BUDGET": "9",
    "CODE_RUN_TIMEOUT": "12",
    "CODE_RUN_COMPILE_TIMEOUT": "25",
    "CODE_RUN_MAX_OUTPUT_CHARS": "40000",
    "CODE_RUN_MAX_CODE_CHARS": "200000",
    "UPLOAD_TEXT_MAX_CHARS": "60000",
    "WAITRESS_THREADS": "32",
    "CHAT_ASYNC_MAX_ACTIVE_JOBS": "10",
    "CHAT_ASYNC_MAX_ACTIVE_PUBLIC_JOBS": "6",
    "CHAT_ASYNC_MAX_ACTIVE_PER_OWNER": "3",
    "GPT_API_MAX_RETRIES": "2",
    "GPT_API_CONNECT_TIMEOUT": "45",
    "GPT_API_READ_TIMEOUT": "900",
    "GPT_API_WRITE_TIMEOUT": "300",
    "GPT_API_POOL_TIMEOUT": "60",
    "GPT_STREAM_MAX_RETRIES": "2",
    "GPT_STREAM_RETRY_BACKOFF": "0.75",
    "GPT_STREAM_RETRY_MAX_BACKOFF": "3.0",
    "GPT_STREAM_CONNECT_TIMEOUT": "45",
    "GPT_STREAM_READ_TIMEOUT": "900",
    "GPT_STREAM_WRITE_TIMEOUT": "300",
    "GPT_STREAM_POOL_TIMEOUT": "60",
    "GPT_FILE_STREAM_READ_TIMEOUT": "1200",
    "APP3_PROMPT_CACHE_AUTO": "1",
    "APP3_PROMPT_CACHE_RETENTION": "24h",
    "APP3_PROMPT_CACHE_KEY_SCOPE": "platform",
    "CHAT_CONTEXT_COMPRESSION_ENABLED": "1",
    "CHAT_CONTEXT_MAX_CHARS": "800000",
    "CHAT_CONTEXT_RECENT_MESSAGES": "48",
    "CHAT_CONTEXT_RECENT_MESSAGE_MAX_CHARS": "80000",
    "CHAT_CONTEXT_OLD_MESSAGE_MAX_CHARS": "80000",
    "CHAT_CONTEXT_LATEST_USER_MAX_CHARS": "160000",
    "CHAT_CONTEXT_TOOL_MESSAGE_MAX_CHARS": "120000",
    "CHAT_CONTEXT_SYSTEM_MESSAGE_MAX_CHARS": "120000",
    "RESPONSES_CONTEXT_MAX_CHARS": "800000",
    "RESPONSES_CONTEXT_RECENT_MESSAGES": "48",
    "RESPONSES_CONTEXT_OLD_MESSAGE_MAX_CHARS": "80000",
    "RESPONSES_CONTEXT_SYSTEM_MESSAGE_MAX_CHARS": "120000",
    "RESPONSES_INPUT_MAX_CHARS": "800000",
    "RESPONSES_PROMPT_CACHE_CONTEXT_MAX_CHARS": "800000",
    "RESPONSES_PROMPT_CACHE_INPUT_MAX_CHARS": "800000",
    "RESPONSES_PROMPT_CACHE_SYSTEM_MESSAGE_MAX_CHARS": "120000",
    "CHAT_PROMPT_CACHE_CONTEXT_MAX_CHARS": "800000",
    "APP3_PROMPT_CACHE_OLD_MESSAGE_MAX_CHARS": "80000",
    "APP3_PROMPT_CACHE_AUDIT_HISTORY_ITEMS": "64",
    "APP3_PROMPT_CACHE_AUDIT_SEGMENT_MAX_CHARS": "300000",
    "APP3_RUNTIME_LOG_FILE": "0",
    "APP3_RUNTIME_LOG_MAX_BYTES": "262144",
    "APP3_RUNTIME_LOG_BACKUP_COUNT": "1",
    "RESPONSES_INPUT_RECENT_ITEMS": "64",
    "RESPONSES_INPUT_RECENT_ITEM_MAX_CHARS": "120000",
    "RESPONSES_INPUT_OLD_ITEM_MAX_CHARS": "80000",
    "RESPONSES_FUNCTION_OUTPUT_MAX_CHARS": "120000",
    "GPT_FILE_STREAM_WRITE_TIMEOUT": "360",
    "REMOTE_IMAGE_REQUEST_RETRIES": "2",
    "REMOTE_IMAGE_RETRY_BACKOFF": "0.45",
    "OBJECT_STORAGE_ENABLED": "0",
    "OBJECT_STORAGE_PROVIDER": "s3",
    "OBJECT_STORAGE_ENDPOINT_URL": "",
    "OBJECT_STORAGE_REGION": "auto",
    "OBJECT_STORAGE_BUCKET": "",
    "OBJECT_STORAGE_ACCESS_KEY_ID": "",
    "OBJECT_STORAGE_SECRET_ACCESS_KEY": "",
    "OBJECT_STORAGE_PUBLIC_BASE_URL": "",
    "OBJECT_STORAGE_PREFIX": "webai",
    "OBJECT_STORAGE_SYNC_PUBLIC_ONLY": "1",
    "OBJECT_STORAGE_READ_FALLBACK": "1",
    "OBJECT_STORAGE_MIRROR_ASYNC": "1",
    "OBJECT_STORAGE_MIRROR_MAX_WORKERS": "2",
    "OBJECT_STORAGE_WRITE_RETRIES": "3",
    "OBJECT_STORAGE_READ_RETRIES": "2",
    "OBJECT_STORAGE_TIMEOUT": "20",
}

SERVER_ENV_ONLY_PREFIXES = (
    'OBJECT_STORAGE_',
    'SANDBOX_',
)

STORAGE_QUOTA_POLICY_KEYS = frozenset({
    'APP_STORAGE_MAX_BYTES',
    'STORAGE_CLEANUP_FREE_BYTES',
    'STORAGE_MIN_FREE_BYTES',
    'ACCOUNT_STORAGE_DEFAULT_MAX_BYTES',
    'ACCOUNT_STORAGE_ANONYMOUS_MAX_BYTES',
    'UPLOAD_DIR_PUBLIC_MAX_BYTES',
    'UPLOAD_DIR_LOCAL_MAX_BYTES',
    'GENERATED_DIR_PUBLIC_MAX_BYTES',
    'GENERATED_DIR_LOCAL_MAX_BYTES',
    'SANDBOX_ROOT_MAX_BYTES',
    'KB_DB_MAX_BYTES',
    'KB_OWNER_MAX_BYTES',
    'KB_SINGLE_IMPORT_MAX_BYTES',
    'UPLOAD_CHUNKS_MAX_BYTES',
    'AUTH_CHAT_BACKUP_MAX_BYTES',
    'AUTH_CHAT_STORE_MAX_BYTES',
    'FILE_TEXT_STORE_MAX_BYTES',
    'REMOTE_IMAGE_CACHE_MAX_BYTES',
    'FAVICON_CACHE_MAX_BYTES',
    'STORAGE_MAINTENANCE_CHAT_ASYNC_VACUUM_THRESHOLD_BYTES',
    'FILE_REGISTRY_MAX_BYTES',
    'AUTH_CHAT_DB_MAX_BYTES',
})
_STORAGE_QUOTA_POLICY_LOCK = threading.RLock()
_STORAGE_QUOTA_POLICY_CACHE = {'signature': None, 'limits': {}}


def _storage_quota_policy_file() -> str:
    return _app_data_path('storage_quota_policy.json')


def _storage_quota_policy_signature(path: str):
    try:
        stat = os.stat(path)
        return (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return None


def _storage_quota_policy_overrides() -> dict:
    path = _storage_quota_policy_file()
    signature = _storage_quota_policy_signature(path)
    with _STORAGE_QUOTA_POLICY_LOCK:
        if _STORAGE_QUOTA_POLICY_CACHE.get('signature') == signature:
            return dict(_STORAGE_QUOTA_POLICY_CACHE.get('limits') or {})
        limits = {}
        if signature is not None:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    payload = json.load(f) or {}
                raw_limits = payload.get('limits') if isinstance(payload, dict) else {}
                if isinstance(raw_limits, dict):
                    for key, value in raw_limits.items():
                        name = str(key or '').strip()
                        if name not in STORAGE_QUOTA_POLICY_KEYS:
                            continue
                        parsed = int(value or 0)
                        if parsed > 0:
                            limits[name] = parsed
            except Exception:
                limits = {}
        _STORAGE_QUOTA_POLICY_CACHE['signature'] = signature
        _STORAGE_QUOTA_POLICY_CACHE['limits'] = limits
        return dict(limits)


def _storage_quota_save_policy_overrides(limits: dict) -> None:
    clean = {}
    for key, value in (limits or {}).items():
        name = str(key or '').strip()
        if name not in STORAGE_QUOTA_POLICY_KEYS:
            continue
        parsed = int(value or 0)
        if parsed > 0:
            clean[name] = parsed
    path = _storage_quota_policy_file()
    payload = {'limits': clean, 'updated_at': time.time()}
    tmp = path + '.tmp-' + uuid.uuid4().hex
    with _STORAGE_QUOTA_POLICY_LOCK:
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
        _STORAGE_QUOTA_POLICY_CACHE['signature'] = _storage_quota_policy_signature(path)
        _STORAGE_QUOTA_POLICY_CACHE['limits'] = dict(clean)

def app_getenv(name: str, default=None):
    key = str(name or '')
    if key in STORAGE_QUOTA_POLICY_KEYS:
        policy_value = _storage_quota_policy_overrides().get(key)
        if policy_value not in (None, ''):
            return str(policy_value)
    if key.startswith(SERVER_ENV_ONLY_PREFIXES):
        env_value = os.environ.get(key)
        if env_value not in (None, ""):
            return str(env_value)
        if key in APP_DEFAULTS:
            return str(APP_DEFAULTS[key])
        return default
    try:
        override = _get_request_override(key, None)
    except Exception:
        override = None
    if override not in (None, ""):
        return str(override)
    if key in APP_DEFAULTS:
        return str(APP_DEFAULTS[key])
    return default


def _ensure_runtime_file_logging() -> None:
    raw_path = str(app_getenv('APP3_RUNTIME_LOG_FILE', '0') or '').strip()
    if not raw_path or raw_path.lower() in {'0', 'false', 'off', 'no', 'disabled'}:
        return
    log_path = raw_path if os.path.isabs(raw_path) else _app_data_path(raw_path)
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
    except Exception:
        return
    root = logging.getLogger()
    try:
        target = os.path.abspath(log_path)
        for handler in root.handlers:
            if isinstance(handler, logging.FileHandler):
                if os.path.abspath(getattr(handler, 'baseFilename', '') or '') == target:
                    return
        fmt = '[%(asctime)s] %(levelname)s %(name)s [rid=%(request_id)s path=%(request_path)s]: %(message)s'
        handler = logging.handlers.RotatingFileHandler(
            target,
            maxBytes=max(32 * 1024, int(str(app_getenv('APP3_RUNTIME_LOG_MAX_BYTES', '262144') or '262144'))),
            backupCount=max(0, min(int(str(app_getenv('APP3_RUNTIME_LOG_BACKUP_COUNT', '1') or '1')), 5)),
            encoding='utf-8',
        )
        handler.setLevel(str(app_getenv('LOG_LEVEL', 'INFO')).upper())
        handler.setFormatter(logging.Formatter(fmt))
        root.addHandler(handler)
    except Exception:
        try:
            app_logger.warning('runtime_file_logging_setup_failed path=%s', log_path)
        except Exception:
            pass


app_logger = logging.getLogger('app3')
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=str(app_getenv('LOG_LEVEL', 'INFO')).upper(),
        format='[%(asctime)s] %(levelname)s %(name)s [rid=%(request_id)s path=%(request_path)s]: %(message)s'
    )
app_logger.setLevel(str(app_getenv('LOG_LEVEL', 'INFO')).upper())
logging.setLogRecordFactory(_request_context_log_record_factory)
_ensure_runtime_file_logging()


# ====== Cloud-grade upload/file durability helpers ======
# 本地落盘仍是第一优先级；配置对象存储后，会额外镜像到 S3/R2/OSS 兼容存储。
# 这样公网端即使 ECS 本机文件被清理、进程重启或临时磁盘抖动，仍能通过对象存储回源。
_OBJECT_STORAGE_MIRROR_GUARD = threading.Lock()
_OBJECT_STORAGE_MIRROR_ACTIVE = 0


def _cfg_bool(name: str, default: bool = False) -> bool:
    try:
        raw = str(app_getenv(name, '1' if default else '0') or '').strip().lower()
    except Exception:
        raw = '1' if default else '0'
    return raw in {'1', 'true', 'yes', 'on', 'y'}


def _server_secret_getenv(name: str, default: str = '') -> str:
    """Read server-only environment variables for secrets.

    app_getenv intentionally prefers request/front-end overrides for normal UI
    settings. Storage credentials must never depend on front-end payloads, so this
    helper reads only the process environment.
    """
    try:
        return str(os.environ.get(name, default) or default)
    except Exception:
        return str(default or '')


def _server_secret_bool(name: str, default: bool = False) -> bool:
    try:
        raw = _server_secret_getenv(name, '1' if default else '0').strip().lower()
    except Exception:
        raw = '1' if default else '0'
    return raw in {'1', 'true', 'yes', 'on', 'y'}


def _object_storage_config() -> dict:
    endpoint = _server_secret_getenv('OBJECT_STORAGE_ENDPOINT_URL', '').strip().rstrip('/')
    bucket = _server_secret_getenv('OBJECT_STORAGE_BUCKET', '').strip().strip('/')
    access_key = _server_secret_getenv('OBJECT_STORAGE_ACCESS_KEY_ID', '').strip()
    secret_key = _server_secret_getenv('OBJECT_STORAGE_SECRET_ACCESS_KEY', '').strip()
    prefix = _server_secret_getenv('OBJECT_STORAGE_PREFIX', 'webai').strip().strip('/')
    region = _server_secret_getenv('OBJECT_STORAGE_REGION', 'auto').strip() or 'auto'
    public_base = _server_secret_getenv('OBJECT_STORAGE_PUBLIC_BASE_URL', '').strip().rstrip('/')
    enabled = _server_secret_bool('OBJECT_STORAGE_ENABLED', False) and bool(endpoint and bucket and access_key and secret_key)
    return {
        'enabled': enabled,
        'endpoint': endpoint,
        'bucket': bucket,
        'access_key': access_key,
        'secret_key': secret_key,
        'region': region,
        'prefix': prefix,
        'public_base': public_base,
    }


def _object_storage_should_sync_scope(scope: str | None = None) -> bool:
    normalized = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    if not _cfg_bool('OBJECT_STORAGE_SYNC_PUBLIC_ONLY', True):
        return True
    return normalized == UPLOAD_SCOPE_PUBLIC


def _object_storage_key(namespace: str, scope: str | None, filename: str) -> str:
    ns = re.sub(r'[^0-9A-Za-z_\-./]+', '-', str(namespace or 'uploads').strip().strip('/')) or 'uploads'
    normalized_scope = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    safe_name = os.path.basename(str(filename or '').strip())
    safe_name = urllib.parse.unquote(safe_name).replace('\\', '/').split('/')[-1]
    prefix = str(_object_storage_config().get('prefix') or '').strip().strip('/')
    parts = [x for x in (prefix, ns, normalized_scope, safe_name) if x]
    return '/'.join(parts)


def _object_storage_url_for_key(key: str) -> str:
    cfg = _object_storage_config()
    endpoint = str(cfg.get('endpoint') or '').rstrip('/')
    bucket = str(cfg.get('bucket') or '').strip('/').strip()
    encoded_key = '/'.join(urllib.parse.quote(part, safe='') for part in str(key or '').split('/') if part != '')
    return f'{endpoint}/{urllib.parse.quote(bucket, safe="")}/{encoded_key}'


def _object_storage_public_url(namespace: str, scope: str | None, filename: str) -> str:
    cfg = _object_storage_config()
    base = str(cfg.get('public_base') or '').strip().rstrip('/')
    if not base:
        return ''
    key = _object_storage_key(namespace, scope, filename)
    encoded_key = '/'.join(urllib.parse.quote(part, safe='') for part in key.split('/') if part != '')
    return f'{base}/{encoded_key}'


def _object_storage_sign_headers(method: str, url: str, body: bytes = b'', content_type: str = '') -> dict:
    cfg = _object_storage_config()
    parsed = urlparse(url)
    host = str(parsed.netloc or '').strip()
    now = datetime.datetime.utcnow()
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = now.strftime('%Y%m%d')
    payload_hash = hashlib.sha256(body or b'').hexdigest()
    headers = {
        'host': host,
        'x-amz-content-sha256': payload_hash,
        'x-amz-date': amz_date,
    }
    if content_type:
        headers['content-type'] = str(content_type or '').split(';', 1)[0].strip() or 'application/octet-stream'
    canonical_headers = ''.join(f'{k}:{headers[k]}\n' for k in sorted(headers))
    signed_headers = ';'.join(sorted(headers))
    canonical_uri = parsed.path or '/'
    canonical_querystring = parsed.query or ''
    canonical_request = '\n'.join([
        str(method or 'GET').upper(),
        canonical_uri,
        canonical_querystring,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])
    algorithm = 'AWS4-HMAC-SHA256'
    credential_scope = f"{date_stamp}/{cfg.get('region') or 'auto'}/s3/aws4_request"
    string_to_sign = '\n'.join([
        algorithm,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode('utf-8')).hexdigest(),
    ])

    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()

    k_date = _sign(('AWS4' + str(cfg.get('secret_key') or '')).encode('utf-8'), date_stamp)
    k_region = _sign(k_date, str(cfg.get('region') or 'auto'))
    k_service = _sign(k_region, 's3')
    k_signing = _sign(k_service, 'aws4_request')
    signature = hmac.new(k_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
    headers['Authorization'] = (
        f"{algorithm} Credential={cfg.get('access_key')}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return headers


def _object_storage_request(method: str, namespace: str, scope: str | None, filename: str, *, body: bytes = b'', content_type: str = '') -> requests.Response:
    key = _object_storage_key(namespace, scope, filename)
    url = _object_storage_url_for_key(key)
    timeout = max(3.0, min(float(str(app_getenv('OBJECT_STORAGE_TIMEOUT', '20') or 20)), 120.0))
    headers = _object_storage_sign_headers(method, url, body=body or b'', content_type=content_type)
    return requests.request(str(method or 'GET').upper(), url, data=body if str(method or '').upper() in {'PUT', 'POST'} else None, headers=headers, timeout=timeout)


def _object_storage_put_bytes(namespace: str, scope: str | None, filename: str, raw: bytes, *, content_type: str = '') -> bool:
    cfg = _object_storage_config()
    if not cfg.get('enabled') or not raw or not filename or not _object_storage_should_sync_scope(scope):
        return False
    attempts = max(1, min(int(str(app_getenv('OBJECT_STORAGE_WRITE_RETRIES', '3') or 3)), 6))
    last_err = None
    for attempt in range(attempts):
        try:
            resp = _object_storage_request('PUT', namespace, scope, filename, body=raw, content_type=content_type or 'application/octet-stream')
            if 200 <= int(getattr(resp, 'status_code', 0) or 0) < 300:
                return True
            last_err = RuntimeError(f'HTTP {getattr(resp, "status_code", "?")}: {str(getattr(resp, "text", "") or "")[:240]}')
        except Exception as e:
            last_err = e
        time.sleep(min(2.0, 0.35 * (attempt + 1)))
    try:
        app_logger.warning('[object_storage] put_failed namespace=%s scope=%s filename=%s err=%s', namespace, scope, filename, last_err)
    except Exception:
        pass
    return False


def _object_storage_delete_file(namespace: str, scope: str | None, filename: str) -> bool:
    cfg = _object_storage_config()
    if not cfg.get('enabled') or not filename or not _object_storage_should_sync_scope(scope):
        return False
    try:
        resp = _object_storage_request('DELETE', namespace, scope, filename)
        status = int(getattr(resp, 'status_code', 0) or 0)
        if status in {200, 202, 204, 404}:
            return True
        app_logger.warning(
            '[object_storage] delete_failed namespace=%s scope=%s filename=%s status=%s body=%s',
            namespace,
            scope,
            filename,
            status,
            str(getattr(resp, 'text', '') or '')[:240],
        )
    except Exception as e:
        try:
            app_logger.warning('[object_storage] delete_failed namespace=%s scope=%s filename=%s err=%s', namespace, scope, filename, e)
        except Exception:
            pass
    return False


def _object_storage_read_bytes(namespace: str, scope: str | None, filename: str) -> tuple[bytes, str]:
    cfg = _object_storage_config()
    if not cfg.get('enabled') or not _cfg_bool('OBJECT_STORAGE_READ_FALLBACK', True) or not filename:
        return b'', ''
    attempts = max(1, min(int(str(app_getenv('OBJECT_STORAGE_READ_RETRIES', '2') or 2)), 5))
    last_err = None
    for attempt in range(attempts):
        try:
            resp = _object_storage_request('GET', namespace, scope, filename)
            status = int(getattr(resp, 'status_code', 0) or 0)
            if 200 <= status < 300 and getattr(resp, 'content', b''):
                ctype = str(resp.headers.get('Content-Type') or '').split(';', 1)[0].strip()
                return bytes(resp.content), ctype
            if status == 404:
                return b'', ''
            last_err = RuntimeError(f'HTTP {status}')
        except Exception as e:
            last_err = e
        time.sleep(min(1.5, 0.25 * (attempt + 1)))
    try:
        app_logger.warning('[object_storage] read_failed namespace=%s scope=%s filename=%s err=%s', namespace, scope, filename, last_err)
    except Exception:
        pass
    return b'', ''


def _guess_content_type_for_file(filename: str, fallback: str = '') -> str:
    ext = _ext_of(filename)
    if ext in UPLOAD_IMAGE_MIME_BY_EXT:
        return UPLOAD_IMAGE_MIME_BY_EXT.get(ext) or fallback or 'application/octet-stream'
    mapping = {
        '.txt': 'text/plain; charset=utf-8', '.md': 'text/markdown; charset=utf-8', '.json': 'application/json',
        '.csv': 'text/csv; charset=utf-8', '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8',
        '.css': 'text/css; charset=utf-8', '.js': 'application/javascript', '.pdf': 'application/pdf',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.zip': 'application/zip',
    }
    return mapping.get(ext, fallback or 'application/octet-stream')


def _write_bytes_atomic(path: str, raw: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f'{path}.tmp-{uuid.uuid4().hex}'
    try:
        with open(tmp_path, 'wb') as wf:
            wf.write(raw)
            try:
                wf.flush()
                os.fsync(wf.fileno())
            except Exception:
                pass
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _object_storage_mirror_file_sync(namespace: str, scope: str | None, filename: str, file_path: str, *, content_type: str = '') -> bool:
    try:
        if not os.path.isfile(file_path):
            return False
        with open(file_path, 'rb') as f:
            raw = f.read()
        return _object_storage_put_bytes(namespace, scope, filename, raw, content_type=content_type or _guess_content_type_for_file(filename))
    except Exception as e:
        try:
            app_logger.warning('[object_storage] mirror_file_failed namespace=%s scope=%s filename=%s err=%s', namespace, scope, filename, e)
        except Exception:
            pass
        return False


def _object_storage_mirror_file_async(namespace: str, scope: str | None, filename: str, file_path: str, *, content_type: str = '') -> bool:
    cfg = _object_storage_config()
    if not cfg.get('enabled') or not _object_storage_should_sync_scope(scope) or not filename or not file_path:
        return False
    if not _cfg_bool('OBJECT_STORAGE_MIRROR_ASYNC', True):
        return _object_storage_mirror_file_sync(namespace, scope, filename, file_path, content_type=content_type)
    max_workers = max(1, min(int(str(app_getenv('OBJECT_STORAGE_MIRROR_MAX_WORKERS', '2') or 2)), 8))
    global _OBJECT_STORAGE_MIRROR_ACTIVE
    with _OBJECT_STORAGE_MIRROR_GUARD:
        if _OBJECT_STORAGE_MIRROR_ACTIVE >= max_workers:
            return False
        _OBJECT_STORAGE_MIRROR_ACTIVE += 1

    def _runner() -> None:
        global _OBJECT_STORAGE_MIRROR_ACTIVE
        try:
            _object_storage_mirror_file_sync(namespace, scope, filename, file_path, content_type=content_type)
        finally:
            with _OBJECT_STORAGE_MIRROR_GUARD:
                _OBJECT_STORAGE_MIRROR_ACTIVE = max(0, _OBJECT_STORAGE_MIRROR_ACTIVE - 1)

    try:
        threading.Thread(target=_runner, name=f'object-mirror-{namespace}-{str(filename)[:18]}', daemon=True).start()
        return True
    except Exception:
        with _OBJECT_STORAGE_MIRROR_GUARD:
            _OBJECT_STORAGE_MIRROR_ACTIVE = max(0, _OBJECT_STORAGE_MIRROR_ACTIVE - 1)
        return False


def _persist_scoped_file_bytes(namespace: str, scope: str | None, filename: str, raw: bytes, *, content_type: str = '', prune_func=None) -> dict:
    normalized_scope = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    if namespace == 'generated':
        root = _generated_dir_for_scope(normalized_scope, ensure=True)
    else:
        root = _upload_dir_for_scope(normalized_scope, ensure=True)
    final_path = os.path.join(root, os.path.basename(str(filename or '').strip()))
    local_ok = False
    object_ok = False
    mirror_queued = False
    err = ''
    raw_bytes = raw or b''
    try:
        keep_for_new_file = [final_path]
        if namespace == 'generated':
            try:
                _prune_generated_dir(scope=normalized_scope, keep_paths=keep_for_new_file, incoming_bytes=len(raw_bytes))
            except Exception:
                pass
        else:
            try:
                _prune_upload_dir(scope=normalized_scope, keep_paths=keep_for_new_file, incoming_bytes=len(raw_bytes))
            except Exception:
                pass
        checker = globals().get('_storage_quota_require_write')
        if callable(checker):
            checker(namespace or 'file', incoming_bytes=len(raw_bytes), target_path=root)
        if namespace == 'generated':
            current_total = _storage_quota_dir_size(root) if callable(globals().get('_storage_quota_dir_size')) else 0
            _storage_quota_module_limit('generated', current_total, len(raw_bytes), _generated_dir_size_limit_bytes(normalized_scope), label='生成文件')
        else:
            current_total = _storage_quota_dir_size(root) if callable(globals().get('_storage_quota_dir_size')) else 0
            _storage_quota_module_limit('uploads', current_total, len(raw_bytes), _upload_dir_size_limit_bytes(normalized_scope), label='上传文件')
    except StorageQuotaError as e:
        err = str(e)
        return {
            'ok': False,
            'local_ok': False,
            'object_ok': False,
            'mirror_queued': False,
            'path': '',
            'error': err,
            'code': 'storage_quota_exceeded',
            'quota_payload': getattr(e, 'payload', {}) if hasattr(e, 'payload') else {},
            'public_url': _object_storage_public_url(namespace, normalized_scope, filename),
        }
    except Exception:
        pass
    try:
        _write_bytes_atomic(final_path, raw_bytes)
        local_ok = True
        if callable(prune_func):
            try:
                prune_func(scope=normalized_scope, keep_paths=[final_path])
            except Exception:
                pass
        try:
            registrar = globals().get('_storage_quota_register_file')
            if callable(registrar):
                registrar(namespace=namespace, scope=normalized_scope, path=final_path, size_bytes=len(raw_bytes), filename=filename)
        except Exception:
            pass
    except Exception as e:
        err = f'{type(e).__name__}: {e}'
        try:
            app_logger.warning('[file_persist] local_write_failed namespace=%s scope=%s filename=%s err=%s', namespace, normalized_scope, filename, err)
        except Exception:
            pass
    if local_ok:
        mirror_queued = _object_storage_mirror_file_async(namespace, normalized_scope, filename, final_path, content_type=content_type)
    elif _object_storage_config().get('enabled') and _object_storage_should_sync_scope(normalized_scope):
        object_ok = _object_storage_put_bytes(namespace, normalized_scope, filename, raw_bytes, content_type=content_type or _guess_content_type_for_file(filename))
    return {
        'ok': bool(local_ok or object_ok),
        'local_ok': local_ok,
        'object_ok': object_ok,
        'mirror_queued': mirror_queued,
        'path': final_path if local_ok else '',
        'error': err,
        'public_url': _object_storage_public_url(namespace, normalized_scope, filename),
    }


def _object_storage_restore_to_local(namespace: str, scope: str | None, filename: str) -> str:
    raw, ctype = _object_storage_read_bytes(namespace, scope, filename)
    if not raw:
        return ''
    normalized_scope = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    root = _generated_dir_for_scope(normalized_scope, ensure=True) if namespace == 'generated' else _upload_dir_for_scope(normalized_scope, ensure=True)
    path = os.path.join(root, os.path.basename(str(filename or '').strip()))
    try:
        _write_bytes_atomic(path, raw)
        return path
    except Exception:
        return ''


def _object_storage_file_response(namespace: str, filename: str, scope: str | None = None, *, as_attachment: bool = False):
    raw, ctype = _object_storage_read_bytes(namespace, scope, filename)
    if not raw:
        return None
    ctype = ctype or _guess_content_type_for_file(filename)
    try:
        force_download_fn = globals().get('_file_link_should_force_download')
        if callable(force_download_fn) and force_download_fn(filename):
            as_attachment = True
    except Exception:
        pass
    resp = Response(raw, content_type=ctype)
    disposition_type = 'attachment' if as_attachment else 'inline'
    safe_name = os.path.basename(str(filename or '').strip()) or 'file'
    resp.headers['Content-Disposition'] = f"{disposition_type}; filename*=UTF-8''{urllib.parse.quote(safe_name)}"
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    resp.headers['X-WebAI-Storage'] = 'object-fallback'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Referrer-Policy'] = 'same-origin'
    return resp


def _favicon_warm_max_concurrency() -> int:
    try:
        return max(1, min(int(str(app_getenv('FAVICON_WARM_MAX_CONCURRENCY', '3') or 3)), 8))
    except Exception:
        return 3


_FAVICON_CACHE_LOCK_GUARD = threading.Lock()
_FAVICON_CACHE_LOCKS: dict[str, threading.Lock] = {}
_FAVICON_WARM_GUARD = threading.Lock()
_FAVICON_WARMING: set[str] = set()
_FAVICON_WARM_BUDGET = threading.BoundedSemaphore(_favicon_warm_max_concurrency())
_FAVICON_SYNC_BUDGET = threading.BoundedSemaphore(_favicon_warm_max_concurrency())
_FAVICON_MISS_GUARD = threading.Lock()
_FAVICON_MISS_UNTIL: dict[str, float] = {}


def _favicon_cache_dir() -> str:
    path = _app_data_path('favicon_cache')
    os.makedirs(path, exist_ok=True)
    return path


def _favicon_cache_ttl_seconds() -> int:
    try:
        return max(300, int(str(app_getenv('FAVICON_CACHE_TTL', str(30 * 24 * 3600))) or 0))
    except Exception:
        return 30 * 24 * 3600


def _favicon_fetch_timeout_seconds() -> float:
    try:
        return max(1.5, min(float(str(app_getenv('FAVICON_FETCH_TIMEOUT', '4.5')) or 4.5), 12.0))
    except Exception:
        return 4.5


def _favicon_max_bytes() -> int:
    try:
        return max(4096, int(str(app_getenv('FAVICON_MAX_BYTES', str(256 * 1024))) or 0))
    except Exception:
        return 256 * 1024


def _favicon_cache_max_total_bytes() -> int:
    try:
        return max(32 * 1024, int(str(app_getenv('FAVICON_CACHE_MAX_BYTES', str(64 * 1024 * 1024))) or 0))
    except Exception:
        return 64 * 1024 * 1024


def _favicon_miss_cooldown_seconds() -> float:
    try:
        return max(30.0, min(float(str(app_getenv('FAVICON_MISS_COOLDOWN', '900')) or 900), 3600.0))
    except Exception:
        return 900.0


def _favicon_miss_is_recent(cache_key: str) -> bool:
    key = str(cache_key or '').strip()
    if not key:
        return False
    now = time.time()
    with _FAVICON_MISS_GUARD:
        expired = [k for k, until in _FAVICON_MISS_UNTIL.items() if float(until or 0.0) <= now]
        for k in expired[:64]:
            _FAVICON_MISS_UNTIL.pop(k, None)
        return float(_FAVICON_MISS_UNTIL.get(key) or 0.0) > now


def _favicon_mark_miss(cache_key: str, seconds: float | None = None) -> None:
    key = str(cache_key or '').strip()
    if not key:
        return
    with _FAVICON_MISS_GUARD:
        if len(_FAVICON_MISS_UNTIL) > 1024:
            now = time.time()
            for k, until in list(_FAVICON_MISS_UNTIL.items())[:256]:
                if float(until or 0.0) <= now:
                    _FAVICON_MISS_UNTIL.pop(k, None)
        ttl = _favicon_miss_cooldown_seconds() if seconds is None else max(10.0, float(seconds or 0.0))
        _FAVICON_MISS_UNTIL[key] = time.time() + ttl


def _favicon_clear_miss(cache_key: str) -> None:
    key = str(cache_key or '').strip()
    if not key:
        return
    with _FAVICON_MISS_GUARD:
        _FAVICON_MISS_UNTIL.pop(key, None)


def _favicon_lock_for(cache_key: str) -> threading.Lock:
    key = str(cache_key or '').strip()
    with _FAVICON_CACHE_LOCK_GUARD:
        lock = _FAVICON_CACHE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FAVICON_CACHE_LOCKS[key] = lock
        return lock


def _favicon_is_public_host(host: str) -> bool:
    raw = str(host or '').strip().lower().strip('.')
    if not raw:
        return False
    if raw == 'localhost' or raw.endswith('.localhost') or raw.endswith('.local') or raw.endswith('.lan'):
        return False
    try:
        ip_obj = ipaddress.ip_address(raw)
        if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_unspecified or ip_obj.is_multicast:
            return False
        return True
    except Exception:
        pass
    return True


def _normalize_favicon_target(raw_url: str = '', raw_host: str = '') -> dict | None:
    page_url = str(raw_url or '').strip()
    host = str(raw_host or '').strip().lower().strip('.')
    scheme = 'https'
    if page_url:
        try:
            parsed = urlparse(page_url)
        except Exception:
            return None
        if str(parsed.scheme or '').lower() not in {'http', 'https'}:
            return None
        host = str(parsed.hostname or '').strip().lower().strip('.')
        scheme = str(parsed.scheme or 'https').lower() or 'https'
        if not host or not _favicon_is_public_host(host):
            return None
        homepage = urllib.parse.urlunparse((scheme, parsed.netloc, '/', '', '', ''))
        return {
            'host': host,
            'page_url': page_url,
            'homepage_url': homepage,
            'origin': urllib.parse.urlunparse((scheme, parsed.netloc, '', '', '', '')),
        }
    if not host:
        return None
    if '://' in host:
        try:
            parsed = urlparse(host)
            host = str(parsed.hostname or '').strip().lower().strip('.')
            scheme = str(parsed.scheme or 'https').lower() or 'https'
        except Exception:
            return None
    if not host or not _favicon_is_public_host(host):
        return None
    homepage = f'{scheme}://{host}/'
    return {
        'host': host,
        'page_url': homepage,
        'homepage_url': homepage,
        'origin': f'{scheme}://{host}',
    }


def _favicon_cache_key(host: str) -> str:
    raw = str(host or '').strip().lower()
    return hashlib.sha1(raw.encode('utf-8', 'ignore')).hexdigest()


def _favicon_cache_paths(cache_key: str) -> tuple[str, str]:
    root = _favicon_cache_dir()
    return os.path.join(root, f'{cache_key}.bin'), os.path.join(root, f'{cache_key}.json')


def _prune_favicon_cache() -> None:
    root = _favicon_cache_dir()
    ttl = _favicon_cache_ttl_seconds()
    max_total = _favicon_cache_max_total_bytes()
    now = time.time()
    entries: list[tuple[float, int, str, str]] = []
    total = 0
    try:
        names = list(os.listdir(root))
    except Exception:
        return

    seen_keys: set[str] = set()
    for name in names:
        if not name.endswith('.bin'):
            continue
        cache_key = name[:-4]
        if not cache_key:
            continue
        data_path, meta_path = _favicon_cache_paths(cache_key)
        try:
            data_st = os.stat(data_path)
        except Exception:
            continue

        meta_mtime = 0.0
        if os.path.exists(meta_path):
            try:
                meta_mtime = float(os.stat(meta_path).st_mtime)
            except Exception:
                meta_mtime = 0.0

        last_used = max(float(data_st.st_mtime), meta_mtime, 0.0)
        age = now - last_used if last_used > 0 else 0.0
        if ttl > 0 and last_used > 0 and age > ttl:
            try:
                os.remove(data_path)
            except Exception:
                pass
            try:
                if os.path.exists(meta_path):
                    os.remove(meta_path)
            except Exception:
                pass
            continue

        size = int(data_st.st_size)
        if os.path.exists(meta_path):
            try:
                size += int(os.stat(meta_path).st_size)
            except Exception:
                pass
        total += size
        entries.append((last_used, size, data_path, meta_path))
        seen_keys.add(cache_key)

    for name in names:
        if not name.endswith('.json'):
            continue
        cache_key = name[:-5]
        if not cache_key or cache_key in seen_keys:
            continue
        meta_path = os.path.join(root, name)
        try:
            meta_st = os.stat(meta_path)
        except Exception:
            continue
        meta_age = now - float(meta_st.st_mtime)
        if ttl > 0 and meta_age > ttl:
            try:
                os.remove(meta_path)
            except Exception:
                pass

    if max_total <= 0 or total <= max_total:
        return

    entries.sort(key=lambda item: (item[0], item[2]))
    for _last_used, size, data_path, meta_path in entries:
        if total <= max_total:
            break
        try:
            os.remove(data_path)
            total -= size
        except Exception:
            continue
        try:
            if os.path.exists(meta_path):
                os.remove(meta_path)
        except Exception:
            pass


def _favicon_read_cache(cache_key: str, *, allow_stale: bool = False) -> tuple[bytes, dict] | tuple[None, None]:
    data_path, meta_path = _favicon_cache_paths(cache_key)
    try:
        if not os.path.exists(data_path) or not os.path.exists(meta_path):
            return None, None
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f) or {}
        if not allow_stale:
            fetched_at = float(meta.get('fetched_at') or 0.0)
            if fetched_at <= 0 or (time.time() - fetched_at) > _favicon_cache_ttl_seconds():
                return None, None
        with open(data_path, 'rb') as f:
            data = f.read()
        if not data:
            return None, None
        try:
            os.utime(data_path, None)
        except Exception:
            pass
        try:
            if os.path.exists(meta_path):
                os.utime(meta_path, None)
        except Exception:
            pass
        return data, meta if isinstance(meta, dict) else {}
    except Exception:
        return None, None


def _favicon_write_cache(cache_key: str, data: bytes, mime: str, source_url: str = '') -> None:
    if not data:
        return
    data_path, meta_path = _favicon_cache_paths(cache_key)
    tmp_data = f'{data_path}.tmp-{uuid.uuid4().hex}'
    tmp_meta = f'{meta_path}.tmp-{uuid.uuid4().hex}'
    payload = {
        'mime': str(mime or 'image/x-icon').strip() or 'image/x-icon',
        'size': len(data),
        'source_url': str(source_url or '').strip()[:1000],
        'fetched_at': time.time(),
    }
    try:
        with open(tmp_data, 'wb') as f:
            f.write(data)
        with open(tmp_meta, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_data, data_path)
        os.replace(tmp_meta, meta_path)
        try:
            _prune_favicon_cache()
        except Exception:
            pass
    except Exception:
        try:
            if os.path.exists(tmp_data):
                os.remove(tmp_data)
        except Exception:
            pass
        try:
            if os.path.exists(tmp_meta):
                os.remove(tmp_meta)
        except Exception:
            pass


def _favicon_response(data: bytes, mime: str, *, cache_hit: bool = False, stale: bool = False):
    resp = Response(data, mimetype=str(mime or 'image/x-icon').strip() or 'image/x-icon')
    resp.headers['Cache-Control'] = 'public, max-age=86400, stale-while-revalidate=604800'
    resp.headers['X-Source-Favicon-Cache'] = 'hit' if cache_hit else ('stale' if stale else 'miss')
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp


def _favicon_failure_response(status: int = 404):
    resp = Response(status=int(status))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp


class _FaviconLinkHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.icon_hrefs: list[str] = []
        self.manifest_hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if str(tag or '').lower() != 'link':
            return
        attr_map = {str(k or '').lower(): str(v or '').strip() for k, v in (attrs or []) if k}
        href = html.unescape(str(attr_map.get('href') or '').strip())
        rel = str(attr_map.get('rel') or '').strip().lower()
        if not href or not rel:
            return
        rel_tokens = {token.strip() for token in re.split(r'\s+', rel) if token.strip()}
        if 'manifest' in rel_tokens or rel == 'manifest':
            self.manifest_hrefs.append(href)
            return
        if any('icon' in token for token in rel_tokens) or 'icon' in rel:
            self.icon_hrefs.append(href)


def _favicon_extract_manifest_candidates(manifest_url: str) -> list[str]:
    raw = str(manifest_url or '').strip()
    if not raw:
        return []
    headers = {
        'User-Agent': app_getenv('WEB_FETCH_UA', '').strip() or 'Mozilla/5.0',
        'Accept': 'application/manifest+json,application/json,text/plain;q=0.9,*/*;q=0.8',
        'Accept-Language': app_getenv('WEB_FETCH_ACCEPT_LANGUAGE', '').strip() or 'zh-CN,zh;q=0.9,en;q=0.6',
    }
    timeout = _favicon_fetch_timeout_seconds()
    try:
        resp = requests.get(raw, headers=headers, timeout=timeout, allow_redirects=True, verify=_cfg_bool('WEB_SEARCH_TLS_VERIFY', True))
    except Exception:
        return []
    try:
        if int(resp.status_code or 0) >= 400:
            return []
        try:
            payload = resp.json()
        except Exception:
            return []
        icons = payload.get('icons') if isinstance(payload, dict) else None
        if not isinstance(icons, list):
            return []
        ranked = []
        for item in icons:
            if not isinstance(item, dict):
                continue
            src = str(item.get('src') or '').strip()
            if not src:
                continue
            purpose = str(item.get('purpose') or '').strip().lower()
            sizes = str(item.get('sizes') or '').strip().lower()
            score = 0
            if 'maskable' in purpose:
                score += 2
            if 'any' in sizes:
                score += 1
            size_match = re.findall(r'(\d+)x(\d+)', sizes)
            if size_match:
                try:
                    score += max(min(int(w), int(h)) for w, h in size_match)
                except Exception:
                    pass
            ranked.append((score, src))
        out = []
        seen = set()
        for _score, src in sorted(ranked, key=lambda x: (-x[0], x[1])):
            abs_url = urllib.parse.urljoin(str(resp.url or raw), html.unescape(src))
            try:
                parsed = urlparse(abs_url)
            except Exception:
                continue
            if str(parsed.scheme or '').lower() not in {'http', 'https'}:
                continue
            key = abs_url.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(abs_url)
            if len(out) >= 8:
                break
        return out
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _favicon_extract_link_candidates(page_url: str) -> list[str]:
    page = str(page_url or '').strip()
    if not page:
        return []
    headers = {
        'User-Agent': app_getenv('WEB_FETCH_UA', '').strip() or 'Mozilla/5.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': app_getenv('WEB_FETCH_ACCEPT_LANGUAGE', '').strip() or 'zh-CN,zh;q=0.9,en;q=0.6',
    }
    timeout = _favicon_fetch_timeout_seconds()
    try:
        resp = requests.get(page, headers=headers, timeout=timeout, allow_redirects=True, verify=_cfg_bool('WEB_SEARCH_TLS_VERIFY', True), stream=True)
    except Exception:
        return []
    try:
        if int(resp.status_code or 0) >= 400:
            return []
        content_type = str(resp.headers.get('content-type') or '').lower()
        if 'html' not in content_type:
            return []
        chunks = []
        total = 0
        max_head_bytes = 128 * 1024
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total >= max_head_bytes:
                break
        if not chunks:
            return []
        encoding = str(resp.encoding or '') or 'utf-8'
        try:
            body_text = b''.join(chunks).decode(encoding, errors='ignore')
        except Exception:
            body_text = b''.join(chunks).decode('utf-8', errors='ignore')
        if not body_text:
            return []
        parser = _FaviconLinkHTMLParser()
        try:
            parser.feed(body_text)
        except Exception:
            return []
        out = []
        seen = set()

        def _push(abs_url: str):
            raw_abs = str(abs_url or '').strip()
            if not raw_abs:
                return
            try:
                parsed = urlparse(raw_abs)
            except Exception:
                return
            if str(parsed.scheme or '').lower() not in {'http', 'https'}:
                return
            key = raw_abs.lower()
            if key in seen:
                return
            seen.add(key)
            out.append(raw_abs)

        base_url = str(resp.url or page)
        for href in parser.icon_hrefs[:16]:
            _push(urllib.parse.urljoin(base_url, href))
        for manifest_href in parser.manifest_hrefs[:6]:
            manifest_url = urllib.parse.urljoin(base_url, manifest_href)
            for icon_url in _favicon_extract_manifest_candidates(manifest_url):
                _push(icon_url)
                if len(out) >= 12:
                    break
            if len(out) >= 12:
                break
        return out[:12]
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _favicon_sniff_mime(data: bytes) -> str:
    raw = data if isinstance(data, (bytes, bytearray)) else b''
    if not raw:
        return ''
    head = bytes(raw[:512]).lstrip()
    lowered = head.lower()
    if lowered.startswith(b'<?xml') or lowered.startswith(b'<svg') or b'<svg' in lowered[:256]:
        return 'image/svg+xml'
    if raw[:8] == bytes.fromhex('89504e470d0a1a0a'):
        return 'image/png'
    if raw[:3] == b'GIF':
        return 'image/gif'
    if raw[:2] == b'BM':
        return 'image/bmp'
    if len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return 'image/webp'
    if raw[:2] == bytes.fromhex('ffd8'):
        return 'image/jpeg'
    if len(raw) >= 4 and raw[:4] in (bytes.fromhex('00000100'), bytes.fromhex('00000200')):
        return 'image/x-icon'
    return ''
def _favicon_guess_mime_from_url(url: str) -> str:
    lowered = str(url or '').strip().lower()
    if lowered.endswith('.ico'):
        return 'image/x-icon'
    if lowered.endswith('.svg'):
        return 'image/svg+xml'
    if lowered.endswith('.png'):
        return 'image/png'
    if lowered.endswith('.gif'):
        return 'image/gif'
    if lowered.endswith('.webp'):
        return 'image/webp'
    if lowered.endswith('.jpg') or lowered.endswith('.jpeg'):
        return 'image/jpeg'
    if lowered.endswith('.bmp'):
        return 'image/bmp'
    return ''


def _favicon_download(url: str) -> tuple[bytes, str] | tuple[None, None]:
    raw = str(url or '').strip()
    if not raw:
        return None, None
    headers = {
        'User-Agent': app_getenv('WEB_FETCH_UA', '').strip() or 'Mozilla/5.0',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Language': app_getenv('WEB_FETCH_ACCEPT_LANGUAGE', '').strip() or 'zh-CN,zh;q=0.9,en;q=0.6',
        'Referer': raw,
    }
    timeout = _favicon_fetch_timeout_seconds()
    max_bytes = _favicon_max_bytes()
    try:
        resp = requests.get(raw, headers=headers, timeout=timeout, allow_redirects=True, verify=_cfg_bool('WEB_SEARCH_TLS_VERIFY', True), stream=True)
    except Exception:
        return None, None
    try:
        if int(resp.status_code or 0) >= 400:
            return None, None
        content_type = str(resp.headers.get('content-type') or '').split(';', 1)[0].strip().lower()
        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                return None, None
            chunks.append(chunk)
        data = b''.join(chunks)
        if not data:
            return None, None
        sniffed_mime = _favicon_sniff_mime(data)
        if content_type.startswith('image/'):
            return data, sniffed_mime or content_type
        guessed_mime = _favicon_guess_mime_from_url(raw)
        if sniffed_mime:
            return data, sniffed_mime
        if guessed_mime:
            return data, guessed_mime
        return None, None
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _favicon_fetch_from_public_service(target: dict) -> tuple[bytes, str, str] | tuple[None, None, None]:
    if not isinstance(target, dict):
        return None, None, None
    host = str(target.get('host') or '').strip().lower()
    page_url = str(target.get('page_url') or '').strip()
    homepage_url = str(target.get('homepage_url') or '').strip()
    if not host and not page_url and not homepage_url:
        return None, None, None
    service_candidates = []
    seen = set()

    def _push(u: str):
        raw = str(u or '').strip()
        if not raw:
            return
        key = raw.lower()
        if key in seen:
            return
        seen.add(key)
        service_candidates.append(raw)

    if page_url:
        _push(f'https://www.google.com/s2/favicons?sz=64&domain_url={quote(page_url, safe="")}')
    if homepage_url and homepage_url != page_url:
        _push(f'https://www.google.com/s2/favicons?sz=64&domain_url={quote(homepage_url, safe="")}')
    if host:
        _push(f'https://icons.duckduckgo.com/ip3/{quote(host, safe="")}.ico')
        _push(f'https://www.google.com/s2/favicons?sz=64&domain={quote(host, safe="")}')

    for endpoint in service_candidates:
        data, mime = _favicon_download(endpoint)
        if data and mime:
            return data, mime, endpoint
    return None, None, None


def _favicon_fetch_from_cravatar(target: dict) -> tuple[bytes, str, str] | tuple[None, None, None]:
    if not isinstance(target, dict):
        return None, None, None
    host = str(target.get('host') or '').strip().lower()
    page_url = str(target.get('page_url') or '').strip()
    target_value = host or page_url
    if not target_value:
        return None, None, None
    for endpoint in (
        f'https://cn.cravatar.com/favicon/api/index.php?url={quote(target_value, safe="")}',
        f'https://cravatar.cn/favicon/api/index.php?url={quote(target_value, safe="")}',
    ):
        data, mime = _favicon_download(endpoint)
        if data and mime:
            return data, mime, endpoint
    return None, None, None


def _favicon_fetch_from_target(target: dict, *, include_external_fallback: bool = True, max_candidates: int = 24) -> tuple[bytes, str, str] | tuple[None, None, None]:
    if not isinstance(target, dict):
        return None, None, None
    page_url = str(target.get('page_url') or '').strip()
    homepage_url = str(target.get('homepage_url') or '').strip()
    origin = str(target.get('origin') or '').strip().rstrip('/')
    candidates = []
    seen = set()

    def _push(u: str):
        raw = str(u or '').strip()
        if not raw:
            return
        key = raw.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(raw)

    for src in (page_url, homepage_url):
        for icon_url in _favicon_extract_link_candidates(src):
            _push(icon_url)
    if origin:
        for suffix in (
            '/favicon.ico',
            '/favicon.png',
            '/favicon.svg',
            '/favicon-32x32.png',
            '/favicon-16x16.png',
            '/apple-touch-icon.png',
            '/apple-touch-icon-precomposed.png',
            '/apple-touch-icon-180x180.png',
            '/apple-touch-icon-152x152.png',
            '/android-chrome-192x192.png',
            '/android-chrome-512x512.png',
            '/mstile-150x150.png',
            '/site.webmanifest',
            '/manifest.webmanifest',
            '/manifest.json',
            '/static/favicon.ico',
            '/static/favicon.png',
            '/assets/favicon.ico',
            '/assets/favicon.png',
            '/images/favicon.ico',
            '/images/favicon.png',
            '/img/favicon.ico',
            '/img/favicon.png',
        ):
            _push(f'{origin}{suffix}')
    expanded_candidates = []
    for icon_url in candidates:
        lowered = icon_url.lower()
        if lowered.endswith(('/site.webmanifest', '/manifest.webmanifest', '/manifest.json')):
            for manifest_icon_url in _favicon_extract_manifest_candidates(icon_url):
                _push(manifest_icon_url)
            continue
        expanded_candidates.append(icon_url)
    try:
        candidate_limit = max(1, min(int(max_candidates or 24), 24))
    except Exception:
        candidate_limit = 24
    for icon_url in expanded_candidates[:candidate_limit]:
        data, mime = _favicon_download(icon_url)
        if data and mime:
            return data, mime, icon_url
    if include_external_fallback:
        data, mime, source_url = _favicon_fetch_from_cravatar(target)
        if data and mime:
            return data, mime, source_url
        return _favicon_fetch_from_public_service(target)
    return None, None, None


def _favicon_fetch_from_light_sources(target: dict) -> tuple[bytes, str, str] | tuple[None, None, None]:
    if not isinstance(target, dict):
        return None, None, None
    data, mime, source_url = _favicon_fetch_from_cravatar(target)
    if data and mime:
        return data, mime, source_url
    return _favicon_fetch_from_public_service(target)

def _favicon_public_browser_fallback_urls(target: dict) -> list[str]:
    """Build one-by-one browser fallback URLs for public favicon display.

    The backend still tries to fetch and cache real favicons first. If that fails,
    public traffic should not stay on the local letter placeholder forever: the
    image request can safely follow a single redirect fallback, and later retries
    can step through the next candidates. This mirrors large-product behavior:
    stable placeholder first, crawl/cache when possible, visible lightweight
    fallback when the crawler cannot fetch the icon in time.
    """
    if not isinstance(target, dict):
        return []
    host = str(target.get('host') or '').strip().lower().strip('.')
    page_url = str(target.get('page_url') or '').strip()
    homepage_url = str(target.get('homepage_url') or '').strip()
    origin = str(target.get('origin') or '').strip().rstrip('/')
    if not (host or page_url or homepage_url or origin):
        return []

    out: list[str] = []
    seen: set[str] = set()

    def _push(u: str):
        raw = str(u or '').strip()
        if not raw:
            return
        try:
            parsed = urlparse(raw)
            if str(parsed.scheme or '').lower() not in {'http', 'https'}:
                return
        except Exception:
            return
        key = raw.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(raw)

    # Direct site icons first: when the server-side crawler is blocked or timed
    # out, the user's browser may still be able to load these normal image URLs.
    if origin:
        for suffix in (
            '/favicon.ico',
            '/favicon.png',
            '/apple-touch-icon.png',
            '/apple-touch-icon-precomposed.png',
            '/android-chrome-192x192.png',
        ):
            _push(f'{origin}{suffix}')

    # Then lightweight icon index services. They are only tried one at a time via
    # redirect/retry, not all at once, so public traffic stays bounded.
    if host:
        _push(f'https://icons.duckduckgo.com/ip3/{quote(host, safe="")}.ico')
        _push(f'https://www.google.com/s2/favicons?sz=64&domain={quote(host, safe="")}')
        _push(f'https://cn.cravatar.com/favicon/api/index.php?url={quote(host, safe="")}')
        _push(f'https://cravatar.cn/favicon/api/index.php?url={quote(host, safe="")}')
    if page_url:
        _push(f'https://www.google.com/s2/favicons?sz=64&domain_url={quote(page_url, safe="")}')
    if homepage_url and homepage_url != page_url:
        _push(f'https://www.google.com/s2/favicons?sz=64&domain_url={quote(homepage_url, safe="")}')
    return out[:10]


def _favicon_public_fallback_response(target: dict, cache_key: str, *, retry_count: int = 0, warmed: bool = False, cooled_down: bool = False):
    fallback_urls = _favicon_public_browser_fallback_urls(target)
    if fallback_urls:
        try:
            idx = max(0, min(int(retry_count or 0), len(fallback_urls) - 1))
        except Exception:
            idx = 0
        resp = redirect(fallback_urls[idx], code=302)
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['X-Source-Favicon-Cache'] = 'fallback-cooldown' if cooled_down else ('fallback-warming' if warmed else 'fallback')
        resp.headers['X-Source-Favicon-Fallback-Index'] = str(idx)
        resp.headers['X-Source-Favicon-Host'] = str(target.get('host') or '')[:120]
        resp.headers['X-Accel-Buffering'] = 'no'
        return resp
    return _favicon_public_pending_response(target, cache_key, warmed=warmed, cooled_down=cooled_down)

def _favicon_public_pending_response(target: dict, cache_key: str, *, warmed: bool = False, cooled_down: bool = False):
    resp = Response(status=204)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['X-Source-Favicon-Cache'] = 'cooldown' if cooled_down else ('warming' if warmed else 'pending')
    resp.headers['X-Source-Favicon-Host'] = str(target.get('host') or '')[:120]
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp


def _favicon_schedule_background_refresh(cache_key: str, target: dict, *, allow_deep_fetch: bool = False) -> bool:
    key = str(cache_key or '').strip()
    if not key or not isinstance(target, dict):
        return False
    if _favicon_miss_is_recent(key):
        return False
    with _FAVICON_WARM_GUARD:
        if key in _FAVICON_WARMING:
            return False
        _FAVICON_WARMING.add(key)

    target_copy = dict(target)

    def _worker():
        acquired_budget = False
        try:
            acquired_budget = _FAVICON_WARM_BUDGET.acquire(blocking=False)
            if not acquired_budget:
                _favicon_mark_miss(key, seconds=60.0)
                return
            cached_data, cached_meta = _favicon_read_cache(key, allow_stale=False)
            if cached_data and isinstance(cached_meta, dict):
                return
            lock = _favicon_lock_for(key)
            with lock:
                cached_data2, cached_meta2 = _favicon_read_cache(key, allow_stale=False)
                if cached_data2 and isinstance(cached_meta2, dict):
                    return
                data = mime = source_url = None
                if allow_deep_fetch:
                    data, mime, source_url = _favicon_fetch_from_target(target_copy, include_external_fallback=False, max_candidates=12)
                if not (data and mime):
                    data, mime, source_url = _favicon_fetch_from_light_sources(target_copy)
                if data and mime:
                    _favicon_write_cache(key, data, mime, source_url=source_url or str(target_copy.get('page_url') or ''))
                    _favicon_clear_miss(key)
                else:
                    _favicon_mark_miss(key)
        except Exception:
            _favicon_mark_miss(key)
            app_logger.exception('[favicon] background_refresh_failed host=%s', str(target_copy.get('host') or ''))
        finally:
            if acquired_budget:
                try:
                    _FAVICON_WARM_BUDGET.release()
                except Exception:
                    pass
            with _FAVICON_WARM_GUARD:
                _FAVICON_WARMING.discard(key)

    try:
        thread = threading.Thread(target=_worker, name=f'favicon-warm-{key[:8]}', daemon=True)
        thread.start()
        return True
    except Exception:
        with _FAVICON_WARM_GUARD:
            _FAVICON_WARMING.discard(key)
        return False


def _serve_source_favicon(raw_url: str = '', raw_host: str = ''):
    target = _normalize_favicon_target(raw_url, raw_host)
    if not target:
        return _favicon_failure_response(400)

    cache_key = _favicon_cache_key(target.get('host') or '')
    is_public_scope = False
    try:
        is_public_scope = (_request_upload_scope() == UPLOAD_SCOPE_PUBLIC)
    except Exception:
        is_public_scope = False
    retry_count = 0
    try:
        retry_count = max(0, int(str(request.args.get('_retry') or '0').strip() or 0))
    except Exception:
        retry_count = 0

    cached_data, cached_meta = _favicon_read_cache(cache_key, allow_stale=False)
    if cached_data and isinstance(cached_meta, dict):
        return _favicon_response(cached_data, str(cached_meta.get('mime') or 'image/x-icon'), cache_hit=True)

    lock = _favicon_lock_for(cache_key)
    with lock:
        cached_data, cached_meta = _favicon_read_cache(cache_key, allow_stale=False)
        if cached_data and isinstance(cached_meta, dict):
            return _favicon_response(cached_data, str(cached_meta.get('mime') or 'image/x-icon'), cache_hit=True)
        stale_data, stale_meta = _favicon_read_cache(cache_key, allow_stale=True)

        data = mime = source_url = None
        if is_public_scope:
            if stale_data and isinstance(stale_meta, dict):
                _favicon_schedule_background_refresh(cache_key, target, allow_deep_fetch=True)
                return _favicon_response(stale_data, str(stale_meta.get('mime') or 'image/x-icon'), stale=True)
            acquired_sync_budget = False
            try:
                acquired_sync_budget = _FAVICON_SYNC_BUDGET.acquire(blocking=False)
                if acquired_sync_budget and not _favicon_miss_is_recent(cache_key):
                    data, mime, source_url = _favicon_fetch_from_target(target, include_external_fallback=True, max_candidates=8)
            finally:
                if acquired_sync_budget:
                    try:
                        _FAVICON_SYNC_BUDGET.release()
                    except Exception:
                        pass
        else:
            data, mime, source_url = _favicon_fetch_from_target(target)

        if data and mime:
            _favicon_write_cache(cache_key, data, mime, source_url=source_url or str(target.get('page_url') or ''))
            _favicon_clear_miss(cache_key)
            return _favicon_response(data, mime, cache_hit=False)
        if stale_data and isinstance(stale_meta, dict):
            return _favicon_response(stale_data, str(stale_meta.get('mime') or 'image/x-icon'), stale=True)

    if is_public_scope:
        cooled_down = _favicon_miss_is_recent(cache_key)
        warmed = False if cooled_down else _favicon_schedule_background_refresh(cache_key, target, allow_deep_fetch=True)
        return _favicon_public_fallback_response(target, cache_key, retry_count=retry_count, warmed=warmed, cooled_down=cooled_down)
    return _favicon_failure_response(404)


def _exec_split_file(filename: str):
    part_path = os.path.join(BASE_DIR, filename)
    with open(part_path, 'r', encoding='utf-8-sig') as _split_f:
        _split_code = compile(_split_f.read(), part_path, 'exec')
    exec(_split_code, globals())

# ====== split section: remote image helpers ======
_exec_split_file('app3_parts/media/remote_image_part.py')

# ====== split section: shared storage quota helpers ======
_exec_split_file('app3_parts/storage/storage_quota_part.py')


# Reduce noisy pypdf warnings on malformed PDFs
try:
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    logging.getLogger('pypdf._reader').setLevel(logging.ERROR)
    logging.getLogger('pypdf.filters').setLevel(logging.ERROR)
except Exception:
    pass


app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200M

# --- Uploads (explicitly split: localhost/private access -> uploads_local, public access -> uploads_public) ---
os.makedirs(UPLOAD_DIR_LOCAL, exist_ok=True)
os.makedirs(UPLOAD_DIR_PUBLIC, exist_ok=True)
os.makedirs(GENERATED_DIR_LOCAL, exist_ok=True)
os.makedirs(GENERATED_DIR_PUBLIC, exist_ok=True)


def _should_inline_uploaded_image_data(scope: str | None = None, *, has_saved_file: bool = True) -> bool:
    normalized = _normalize_upload_scope(scope) if scope is not None else _request_upload_scope()
    # 公网优先走已保存的同源文件地址，避免上传后再把整张 base64 图回传一遍。
    # 仅在本机侧，或保存失败没有服务端文件可用时，才内联 data URL 兜底。
    if normalized == UPLOAD_SCOPE_LOCAL:
        return True
    return not bool(has_saved_file)

# ====== split section: platform / auth / upload / proxy ======
_exec_split_file('app3_parts/platform/platform_auth_part.py')


# ====== split section: request trace, chat sync store, personalization memory, thinking/runtime overrides, web settings policy ======
_exec_split_file('app3_parts/account/user_personalization_runtime_part.py')


# ====== split section: account-level cross-session context search ======
_exec_split_file('app3_parts/account/account_context_part.py')


# ====== split section: commodity API template probing and lightweight playwright probe helpers ======
_exec_split_file('app3_parts/web/web_probe_common_part.py')


# ====== split section: OpenAI compatible clients, image generation/edit providers, artifact saving, sandbox artifact routing/adapters ======
_exec_split_file('app3_parts/media/model_image_file_delivery_part.py')


# ====== split section: auto web enrichment, async fetch, search providers, reply-image selection, web injection helpers, code Chinese-safe prompt ======
_exec_split_file('app3_parts/web/web_search_enrichment_part.py')


# ====== split section: knowledge base storage/search/import and message preparation/context recall helpers ======
_exec_split_file('app3_parts/knowledge/knowledge_base_context_part.py')


# ====== split section: web page fetch/extract, dynamic fetch enhancements, GitHub fast fetch, cloud connect, code runner, text file reader ======
_exec_split_file('app3_parts/web/web_fetch_cloud_code_part.py')


# ====== split section: sandbox skills registry (lightweight SKILL.md + read-only scripts; no duplicate tool names) ======
_exec_split_file('app3_parts/tools/sandbox_skills_registry_part.py')
_exec_split_file('app3_parts/tools/skill_registry_part.py')

# ====== split section: centralized task / evidence / artifact / execution policies ======
_exec_split_file('app3_parts/agent/task_intent_router_part.py')
_exec_split_file('app3_parts/agent/file_evidence_policy_part.py')
_exec_split_file('app3_parts/agent/file_lineage_registry_part.py')
_exec_split_file('app3_parts/agent/file_context_resolver_part.py')
_exec_split_file('app3_parts/agent/file_diff_router_part.py')
_exec_split_file('app3_parts/agent/artifact_task_router_part.py')
_exec_split_file('app3_parts/tools/sandbox_execution_policy_part.py')
_exec_split_file('app3_parts/agent/artifact_manager_part.py')
_exec_split_file('app3_parts/agent/agent_loop_controller_part.py')
_exec_split_file('app3_parts/agent/evidence_ledger_part.py')
_exec_split_file('app3_parts/agent/web_evidence_router_part.py')
_exec_split_file('app3_parts/tools/tool_policy_part.py')

# ====== split section: file registry, full-text store, file symbol index, existing file read/edit tools, runtime tool injection/sanitization helpers ======
_exec_split_file('app3_parts/tools/file_registry_store_part.py')
_exec_split_file('app3_parts/tools/sandbox_file_listing_part.py')
_exec_split_file('app3_parts/tools/sandbox_document_readers_part.py')
_exec_split_file('app3_parts/tools/sandbox_office_generation_part.py')
_exec_split_file('app3_parts/tools/tool_schema_normalizer_part.py')
_exec_split_file('app3_parts/tools/sandbox_tool_progress_helpers_part.py')
_exec_split_file('app3_parts/tools/file_registry_edit_resolver_part.py')
_exec_split_file('app3_parts/tools/file_registry_read_context_part.py')
_exec_split_file('app3_parts/tools/file_registry_edit_apply_part.py')
_exec_split_file('app3_parts/tools/file_registry_edit_tools_part.py')
_exec_split_file('app3_parts/tools/sandbox_run_runtime_part.py')
_exec_split_file('app3_parts/tools/sandbox_tool_schema_part.py')
_exec_split_file('app3_parts/tools/tool_schema_part.py')
_exec_split_file('app3_parts/tools/tool_runtime_context_part.py')
_exec_split_file('app3_parts/tools/sandbox_tool_progress_part.py')
_exec_split_file('app3_parts/tools/sandbox_file_image_extract_script_part.py')
_exec_split_file('app3_parts/tools/image_task_planner_part.py')
_exec_split_file('app3_parts/tools/tool_result_compression_part.py')

# ====== split section: canonical activity timeline event helpers ======
_exec_split_file('app3_parts/agent/activity_event_part.py')

# ====== split section: chat orchestration / streaming ======
_exec_split_file('app3_parts/chat/chat_orchestrator_part.py')

# MCP client support is a shared transport/runtime used by both endpoint modes.
# Chat Completions and Responses still receive separately shaped tool schemas.
_exec_split_file('app3_parts/mcp/client_runtime_part.py')





# ====== split section: public API routes after orchestrator, sync chat endpoints, fetch URL APIs, chat route, weather card/location logic, stream route ======
_exec_split_file('app3_parts/chat/chat_weather_routes_part.py')


# ====== split section: background chat async jobs, image pullback jobs, upload/chunk routes, waitress startup, legacy fast/streaming patch tail ======
APP3_DEFER_WAITRESS_STARTUP = True
_exec_split_file('app3_parts/media/async_pullback_upload_server_part.py')


if __name__ == "__main__":
    _app3_waitress_startup()
