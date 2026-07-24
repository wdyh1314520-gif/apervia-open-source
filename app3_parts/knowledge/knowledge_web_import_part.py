# KB safe webpage import filename, URL validation, and page text fetching.


class KnowledgeImportError(ValueError):
    def __init__(self, code: str, *, params: dict | None = None):
        self.code = str(code or 'kb_import_failed').strip().lower() or 'kb_import_failed'
        self.params = dict(params or {})
        super().__init__(self.code)


def _kb_import_error_response(err: KnowledgeImportError, status: int = 400):
    return jsonify({
        'ok': False,
        'code': str(getattr(err, 'code', '') or 'kb_import_failed'),
        'params': dict(getattr(err, 'params', {}) or {}),
        'error': str(getattr(err, 'code', '') or 'kb_import_failed'),
    }), int(status or 400)

def _kb_safe_import_filename(name: str = '', fallback: str = '知识库文档') -> str:
    raw = str(name or '').strip().replace('\r', ' ').replace('\n', ' ')
    raw = re.sub(r'\s+', ' ', raw).strip()
    if not raw:
        raw = str(fallback or '知识库文档').strip() or '知识库文档'
    raw = re.sub(r'[\\/:*?"<>|]+', '_', raw).strip(' ._') or '知识库文档'
    if len(raw) > 96:
        raw = raw[:96].rstrip(' ._') or '知识库文档'
    if not os.path.splitext(raw)[1]:
        raw += '.txt'
    return raw


def _kb_title_from_url(url: str = '') -> str:
    try:
        parsed = urlparse(str(url or '').strip())
        host = str(parsed.netloc or '').strip() or '网页'
        path = urllib.parse.unquote(str(parsed.path or '').strip('/'))
        if path:
            tail = path.rsplit('/', 1)[-1].strip() or path.replace('/', '_')
            base = f'{host}_{tail}'
        else:
            base = host
        return base
    except Exception:
        return '网页内容'


def _kb_validate_public_http_url(url: str = '') -> str:
    raw = str(url or '').strip()
    if not raw:
        raise KnowledgeImportError('kb_url_required')
    parsed = urlparse(raw)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise KnowledgeImportError('kb_url_scheme_invalid')
    private_checker = globals().get('_is_private_host')
    if callable(private_checker) and private_checker(parsed.hostname or ''):
        raise KnowledgeImportError('kb_private_url_blocked')
    validator = globals().get('_validate_http_url')
    if callable(validator):
        try:
            return str(validator(raw) or raw).strip()
        except ValueError as exc:
            detail = str(exc or '').strip()
            if 'http/https' in detail.lower():
                raise KnowledgeImportError('kb_url_scheme_invalid') from exc
            if any(token in detail for token in ('本机', '内网', 'private', 'localhost')):
                raise KnowledgeImportError('kb_private_url_blocked') from exc
            raise KnowledgeImportError('kb_url_invalid', params={'detail': detail}) from exc
    return raw


def _kb_fetch_webpage_text(url: str = '', title_hint: str = '') -> dict:
    target_url = _kb_validate_public_http_url(url)
    max_chars = 120000
    fetcher = globals().get('fetch_url_content_smart')
    if callable(fetcher):
        try:
            out = fetcher(target_url, query=str(title_hint or ''), max_chars=max_chars) or {}
            if isinstance(out, dict):
                text = str(out.get('text') or '').strip()
                if text:
                    return {
                        'url': target_url,
                        'final_url': str(out.get('final_url') or out.get('url') or target_url).strip() or target_url,
                        'title': str(out.get('title') or '').strip(),
                        'text': truncate_text(text, max_chars=max_chars),
                        'error': str(out.get('error') or '').strip(),
                    }
                err = str(out.get('error') or out.get('warning') or '').strip()
                if err:
                    raise ValueError(err)
        except Exception as e:
            raise ValueError(f'网页读取失败：{type(e).__name__}: {e}')

    fetcher = globals().get('fetch_url_content')
    if callable(fetcher):
        try:
            out = fetcher(target_url, timeout=20, max_chars=max_chars) or {}
            if isinstance(out, dict):
                text = str(out.get('text') or '').strip()
                if text:
                    return {
                        'url': target_url,
                        'final_url': str(out.get('final_url') or out.get('url') or target_url).strip() or target_url,
                        'title': str(out.get('title') or '').strip(),
                        'text': truncate_text(text, max_chars=max_chars),
                        'error': str(out.get('error') or '').strip(),
                    }
                err = str(out.get('error') or out.get('warning') or '').strip()
                if err:
                    raise ValueError(err)
        except Exception as e:
            raise ValueError(f'网页读取失败：{type(e).__name__}: {e}')

    try:
        resp = requests.get(target_url, timeout=20, headers={'User-Agent': app_getenv('WEB_FETCH_UA', '').strip() or 'Mozilla/5.0'}, allow_redirects=True)
        if int(resp.status_code or 0) >= 400:
            raise ValueError(f'HTTP {resp.status_code}')
        html_text = resp.text or ''
        extractor = globals().get('_extract_text_from_html')
        if callable(extractor):
            extracted = extractor(html_text, max_chars=max_chars, url=str(resp.url or target_url)) or {}
            text = str(extracted.get('text') or '').strip()
            page_title = str(extracted.get('title') or '').strip()
        else:
            page_title = ''
            m = re.search(r'<title[^>]*>(.*?)</title>', html_text, flags=re.I | re.S)
            if m:
                page_title = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(1))).strip()
            cleaned = re.sub(r'(?is)<(script|style|noscript|svg|canvas|iframe)[^>]*>.*?</\1>', ' ', html_text)
            cleaned = re.sub(r'(?s)<[^>]+>', ' ', cleaned)
            text = re.sub(r'\s+', ' ', html.unescape(cleaned)).strip()
        if not text:
            raise ValueError('未读取到可入库正文')
        return {
            'url': target_url,
            'final_url': str(resp.url or target_url),
            'title': page_title,
            'text': truncate_text(text, max_chars=max_chars),
            'error': '',
        }
    except Exception as e:
        raise ValueError(f'网页读取失败：{type(e).__name__}: {e}')
