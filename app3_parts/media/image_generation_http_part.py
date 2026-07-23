# Split from app3_parts/media/model_image_file_delivery_part.py.
# Purpose: image generation timeout, retry, endpoint, filename, and preview helpers.
# Loaded by model_image_file_delivery_part.py via _exec_split_file(...), sharing the original global namespace.

IMAGE_GENERATION_TIMEOUT_MESSAGE = '上游异常超时，已强行截断'


class ImageGenerationTimeoutError(TimeoutError):
    pass


def _image_generation_timeout_seconds() -> float:
    try:
        raw = app_getenv('IMAGE_GENERATION_FORCE_TIMEOUT_SECONDS', app_getenv('IMAGE_GENERATION_TIMEOUT_SECONDS', '900'))
        value = float(str(raw or '180').strip())
    except Exception:
        value = 180.0
    return max(30.0, min(value, 900.0))


def _image_generation_make_deadline(timeout_s: float | None = None) -> float:
    seconds = _image_generation_timeout_seconds() if timeout_s is None else float(timeout_s or _image_generation_timeout_seconds())
    return time.time() + max(1.0, seconds)


def _image_generation_deadline_from_extra(extra_body: dict | None = None) -> float:
    extra = extra_body if isinstance(extra_body, dict) else {}
    try:
        return float(extra.get('_deadline_ts') or 0.0)
    except Exception:
        return 0.0


def _image_generation_remaining_seconds(extra_body: dict | None = None) -> float:
    deadline = _image_generation_deadline_from_extra(extra_body)
    if deadline <= 0:
        return _image_generation_timeout_seconds()
    remaining = deadline - time.time()
    if remaining <= 0:
        raise ImageGenerationTimeoutError(IMAGE_GENERATION_TIMEOUT_MESSAGE)
    return max(0.05, remaining)


def _image_generation_timeout_httpx_timeout(extra_body: dict | None = None):
    remaining = _image_generation_remaining_seconds(extra_body)
    return httpx.Timeout(
        connect=max(1.0, min(45.0, remaining)),
        read=max(1.0, remaining),
        write=max(1.0, remaining),
        pool=max(1.0, min(60.0, remaining)),
    )


def _image_generation_attach_deadline(settings: dict | None = None, *, task_mode: str = 'generate') -> dict:
    normalized = dict(settings or {}) if isinstance(settings, dict) else {}
    timeout_s = _image_generation_timeout_seconds()
    deadline = _image_generation_make_deadline(timeout_s)
    extra = dict(normalized.get('extra_body') or {}) if isinstance(normalized.get('extra_body'), dict) else {}
    extra.setdefault('_deadline_ts', deadline)
    extra.setdefault('_operation_timeout_s', timeout_s)
    normalized['extra_body'] = extra
    edit = dict(normalized.get('edit') or {}) if isinstance(normalized.get('edit'), dict) else {}
    edit_extra = dict(edit.get('extra_body') or {}) if isinstance(edit.get('extra_body'), dict) else {}
    edit_extra.setdefault('_deadline_ts', deadline)
    edit_extra.setdefault('_operation_timeout_s', timeout_s)
    edit['extra_body'] = edit_extra
    normalized['edit'] = edit
    normalized['_deadline_ts'] = deadline
    normalized['_operation_timeout_s'] = timeout_s
    normalized['_task_mode'] = str(task_mode or 'generate')
    return normalized


def _image_generation_external_extra_body(extra_body: dict | None = None) -> dict:
    data = dict(extra_body or {}) if isinstance(extra_body, dict) else {}
    for key in list(data.keys()):
        if str(key or '').startswith('_'):
            data.pop(key, None)
    return data


def _image_generation_timeout_result(*, task_mode: str = 'generate', image_task_type: str = '', settings: dict | None = None) -> dict:
    out = {
        'ok': False,
        'artifacts': [],
        'settings': _image_generation_public_settings(settings or {}),
        'error': IMAGE_GENERATION_TIMEOUT_MESSAGE,
        'timeout_truncated': True,
        'force_truncated': True,
        'task_mode': str(task_mode or 'generate'),
    }
    if image_task_type:
        out['image_task_type'] = str(image_task_type or '')
    return out


def _image_http_client() -> httpx.Client:
    timeout_s = _image_generation_timeout_seconds()
    return httpx.Client(
        verify=tls_verify,
        timeout=httpx.Timeout(
            connect=max(1.0, min(45.0, timeout_s)),
            read=max(1.0, timeout_s),
            write=max(1.0, timeout_s),
            pool=max(1.0, min(60.0, timeout_s)),
        ),
        follow_redirects=True,
    )


def _image_generation_retry_config(extra_body: dict | None = None) -> tuple[int, float]:
    # 图片生成/编辑请求通常是非幂等的：上游可能已经完成并计费，但中转/连接层
    # 断开导致本机没有收到响应。这里必须禁止自动重试，避免同一提示词被重复提交。
    _ = extra_body
    return 0, 1.2


def _image_generation_is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ReadError, httpx.ConnectError, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            status = int(exc.response.status_code)
        except Exception:
            status = 0
        return status in {408, 409, 425, 429, 500, 502, 503, 504}
    name = type(exc).__name__.lower()
    txt = str(exc or '').lower()
    return any(x in name for x in ('timeout', 'connection', 'protocol', 'network')) or any(x in txt for x in ('too many requests', 'service unavailable', 'bad gateway', 'gateway timeout', 'server disconnected'))


def _image_generation_retry_after_seconds(resp) -> float | None:
    try:
        raw = str(resp.headers.get('retry-after') or '').strip()
    except Exception:
        raw = ''
    if not raw:
        return None
    try:
        val = float(raw)
        if val >= 0:
            return min(val, 12.0)
    except Exception:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        if dt:
            return min(max(0.0, dt.timestamp() - time.time()), 12.0)
    except Exception:
        pass
    return None


def _image_generation_http_request_with_retry(http_client, method: str, url: str, *, extra_body: dict | None = None, **kwargs):
    retries, backoff = _image_generation_retry_config(extra_body)
    last_exc = None
    deadline = _image_generation_deadline_from_extra(extra_body)
    for attempt in range(retries + 1):
        try:
            req_kwargs = dict(kwargs or {})
            if deadline > 0 and 'timeout' not in req_kwargs:
                req_kwargs['timeout'] = _image_generation_timeout_httpx_timeout(extra_body)
            resp = http_client.request(method, url, **req_kwargs)
            resp.raise_for_status()
            return resp
        except ImageGenerationTimeoutError:
            raise
        except Exception as exc:
            last_exc = exc
            if deadline > 0 and (deadline - time.time()) <= 0:
                raise ImageGenerationTimeoutError(IMAGE_GENERATION_TIMEOUT_MESSAGE)
            if attempt >= retries or not _image_generation_is_retryable_error(exc):
                if deadline > 0 and isinstance(exc, httpx.TimeoutException):
                    raise ImageGenerationTimeoutError(IMAGE_GENERATION_TIMEOUT_MESSAGE) from exc
                raise
            delay = backoff * (2 ** attempt)
            if isinstance(exc, httpx.HTTPStatusError):
                retry_after = _image_generation_retry_after_seconds(exc.response)
                if retry_after is not None:
                    delay = max(delay, retry_after)
            delay = min(delay + random.random() * 0.25, 12.0)
            if deadline > 0:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise ImageGenerationTimeoutError(IMAGE_GENERATION_TIMEOUT_MESSAGE)
                delay = min(delay, max(0.0, remaining))
            try:
                status = getattr(getattr(exc, 'response', None), 'status_code', '')
                app_logger.warning('[image_generation] retry method=%s url=%s attempt=%s/%s status=%s err=%s:%s', method, url, attempt + 1, retries + 1, status, type(exc).__name__, exc)
            except Exception:
                pass
            if delay <= 0:
                raise ImageGenerationTimeoutError(IMAGE_GENERATION_TIMEOUT_MESSAGE)
            time.sleep(delay)
    if last_exc is not None:
        if deadline > 0 and isinstance(last_exc, httpx.TimeoutException):
            raise ImageGenerationTimeoutError(IMAGE_GENERATION_TIMEOUT_MESSAGE) from last_exc
        raise last_exc
    raise RuntimeError('image_generation_request_failed')


def _append_url_path(base_url: str, path: str) -> str:
    base = str(base_url or '').strip().rstrip('/')
    want = str(path or '').strip()
    if not want.startswith('/'):
        want = '/' + want
    if not base:
        return want
    if base.endswith(want):
        return base
    if want.startswith('/v1/') and re.search(r'/v1$', base, flags=re.I):
        return base + want[3:]
    return base + want


def _openai_image_generation_endpoint(base_url: str) -> str:
    base = str(base_url or '').strip().rstrip('/')
    if not base:
        return '/v1/images/generations'
    if re.search(r'/images/generations$', base, flags=re.I):
        return base
    return _append_url_path(base, '/v1/images/generations')


def _openai_image_edit_endpoint(base_url: str) -> str:
    base = str(base_url or '').strip().rstrip('/')
    if not base:
        return '/v1/images/edits'
    if re.search(r'/images/edits$', base, flags=re.I):
        return base
    return _append_url_path(base, '/v1/images/edits')


def _openai_chat_completions_endpoint(base_url: str) -> str:
    base = str(base_url or '').strip().rstrip('/')
    if not base:
        return '/v1/chat/completions'
    if re.search(r'/chat/completions$', base, flags=re.I):
        return base
    return _append_url_path(base, '/v1/chat/completions')


def _automatic1111_img2img_endpoint(base_url: str) -> str:
    base = str(base_url or '').strip().rstrip('/')
    if not base:
        return '/sdapi/v1/img2img'
    if re.search(r'/sdapi/v1/img2img$', base, flags=re.I):
        return base
    return _append_url_path(base, '/sdapi/v1/img2img')


def _automatic1111_txt2img_endpoint(base_url: str) -> str:
    base = str(base_url or '').strip().rstrip('/')
    if not base:
        return '/sdapi/v1/txt2img'
    if re.search(r'/sdapi/v1/txt2img$', base, flags=re.I):
        return base
    return _append_url_path(base, '/sdapi/v1/txt2img')


def _comfyui_prompt_endpoint(base_url: str) -> str:
    base = str(base_url or '').strip().rstrip('/')
    if not base:
        return '/prompt'
    if re.search(r'/prompt$', base, flags=re.I):
        return base
    return _append_url_path(base, '/prompt')


def _comfyui_history_endpoint(base_url: str, prompt_id: str) -> str:
    base = str(base_url or '').strip().rstrip('/')
    pid = quote(str(prompt_id or '').strip(), safe='')
    if not base:
        return f'/history/{pid}'
    if re.search(r'/history$', base, flags=re.I):
        return base + '/' + pid
    return _append_url_path(base, f'/history/{pid}')


def _parse_image_size(value: str | None, default: tuple[int, int] = (1024, 1024)) -> tuple[int, int]:
    raw = str(value or '').strip().lower().replace('×', 'x').replace(' ', '')
    m = re.match(r'^(\d{2,5})x(\d{2,5})$', raw)
    if not m:
        return default
    try:
        return max(64, int(m.group(1))), max(64, int(m.group(2)))
    except Exception:
        return default


def _strip_data_url_prefix(data: str) -> str:
    raw = str(data or '').strip()
    if raw.startswith('data:') and ',' in raw:
        return raw.split(',', 1)[1].strip()
    return raw


def _image_generation_filename(index: int = 1, *, ext: str = 'png') -> str:
    safe_ext = str(ext or 'png').strip().lower() or 'png'
    if safe_ext == 'jpg':
        safe_ext = 'jpeg'
    if safe_ext not in {'png', 'jpeg', 'webp'}:
        safe_ext = 'png'
    stamp = time.strftime('%Y%m%d_%H%M%S')
    suffix = f'_{index}' if index > 1 else ''
    return f'image_gen_{stamp}{suffix}.{safe_ext}'


def _image_generation_preview_text(value, limit: int = 360) -> str:
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value)
    text = str(text or '').replace("\r", ' ').replace("\n", ' ').strip()
    if len(text) > max(80, int(limit or 360)):
        return text[: max(80, int(limit or 360))] + '...'
    return text
