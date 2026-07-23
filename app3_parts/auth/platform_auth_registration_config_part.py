# Split from app3_parts/auth/platform_auth_core_part.py.
# Purpose: terms and registration-domain rules.
# Loaded by platform_auth_core_part.py via _exec_split_file(...), sharing the original global namespace.

def _auth_text_value(value, default: str = '', max_len: int = 4000) -> str:
    raw = str(value if value is not None else '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not raw:
        raw = str(default or '')
    try:
        limit = max(0, int(max_len or 0))
    except Exception:
        limit = 4000
    return raw[:limit] if limit and len(raw) > limit else raw


def _auth_terms_display_mode(value) -> str:
    mode = str(value or AUTH_TERMS_DEFAULT_DISPLAY_MODE).strip().lower()
    return mode if mode in ('checkbox', 'modal') else AUTH_TERMS_DEFAULT_DISPLAY_MODE


def _auth_terms_slug_value(value, fallback: str = 'terms') -> str:
    raw = str(value or '').strip().lower()
    raw = re.sub(r'^https?://[^/]+', '', raw)
    raw = re.sub(r'^/+', '', raw)
    if raw.startswith('legal/'):
        raw = raw[6:]
    raw = raw.strip('/#? ')
    raw = re.sub(r'[^a-z0-9_-]+', '-', raw)
    raw = re.sub(r'-{2,}', '-', raw).strip('-_')
    fallback_raw = re.sub(r'[^a-z0-9_-]+', '-', str(fallback or 'terms').strip().lower()).strip('-_') or 'terms'
    return (raw or fallback_raw)[:80]


def _auth_terms_default_documents() -> list[dict]:
    return [dict(item) for item in AUTH_TERMS_DEFAULT_DOCUMENTS]


def _auth_terms_normalize_documents(value=None) -> list[dict]:
    rows = value if isinstance(value, list) else []
    if not rows:
        rows = _auth_terms_default_documents()
    docs: list[dict] = []
    seen: set[str] = set()
    for idx, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        title = _auth_text_value(item.get('title') or item.get('name'), f'协议文档 {idx + 1}', 80)
        slug = _auth_terms_slug_value(item.get('slug') or item.get('path') or item.get('route'), f'doc-{idx + 1}')
        base_slug = slug
        suffix = 2
        while slug in seen:
            suffix_text = f'-{suffix}'
            slug = (base_slug[: max(1, 80 - len(suffix_text))] + suffix_text).strip('-_') or f'doc-{idx + 1}'
            suffix += 1
        seen.add(slug)
        content = _auth_text_value(item.get('content') or item.get('markdown') or item.get('body'), '', AUTH_TERMS_MAX_CONTENT_CHARS)
        docs.append({'title': title, 'slug': slug, 'content': content})
        if len(docs) >= AUTH_TERMS_MAX_DOCUMENTS:
            break
    return docs or _auth_terms_default_documents()


def _auth_terms_documents_public(docs=None, include_content: bool = False) -> list[dict]:
    source = _auth_terms_normalize_documents(docs)
    out: list[dict] = []
    for item in source:
        row = {
            'title': str(item.get('title') or '').strip(),
            'slug': str(item.get('slug') or '').strip(),
            'url': '/legal/' + str(item.get('slug') or '').strip(),
        }
        if include_content:
            row['content'] = str(item.get('content') or '')
        out.append(row)
    return out


def _auth_terms_markdown_inline(value: str) -> str:
    text = html.escape(str(value or ''))
    def _link_repl(match):
        label = match.group(1)
        url = match.group(2).strip()
        if not (url.startswith('/') or url.startswith('http://') or url.startswith('https://') or url.startswith('mailto:')):
            return match.group(0)
        return '<a href="' + html.escape(url, quote=True) + '" target="_blank" rel="noopener noreferrer">' + label + '</a>'
    text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', _link_repl, text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return text


def _auth_terms_markdown_to_html(markdown_text: str) -> str:
    lines = str(markdown_text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    parts: list[str] = []
    paragraph: list[str] = []
    list_type = ''
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph():
        nonlocal paragraph
        if paragraph:
            parts.append('<p>' + '<br>'.join(_auth_terms_markdown_inline(line) for line in paragraph) + '</p>')
            paragraph = []

    def close_list():
        nonlocal list_type
        if list_type:
            parts.append(f'</{list_type}>')
            list_type = ''

    for raw_line in lines:
        line = raw_line.rstrip('\n')
        if line.strip().startswith('```'):
            if in_code:
                parts.append('<pre><code>' + html.escape('\n'.join(code_lines)) + '</code></pre>')
                code_lines = []
                in_code = False
            else:
                flush_paragraph()
                close_list()
                in_code = True
                code_lines = []
            continue
        if in_code:
            code_lines.append(line)
            continue
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            close_list()
            continue
        heading = re.match(r'^(#{1,4})\s+(.+)$', stripped)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            parts.append(f'<h{level}>' + _auth_terms_markdown_inline(heading.group(2)) + f'</h{level}>')
            continue
        ul = re.match(r'^[-*+]\s+(.+)$', stripped)
        ol = re.match(r'^\d+[.)]\s+(.+)$', stripped)
        if ul or ol:
            flush_paragraph()
            want = 'ul' if ul else 'ol'
            if list_type != want:
                close_list()
                list_type = want
                parts.append(f'<{list_type}>')
            parts.append('<li>' + _auth_terms_markdown_inline((ul or ol).group(1)) + '</li>')
            continue
        close_list()
        paragraph.append(line)
    if in_code:
        parts.append('<pre><code>' + html.escape('\n'.join(code_lines)) + '</code></pre>')
    flush_paragraph()
    close_list()
    return '\n'.join(parts) or '<p class="muted">该文档暂无内容。</p>'


def _auth_terms_current_config(include_content: bool = False) -> dict:
    with _EMAIL_LOGIN_LOCK:
        enabled = bool(_EMAIL_LOGIN_STATE.get('terms_enabled', False))
        mode = _auth_terms_display_mode(_EMAIL_LOGIN_STATE.get('terms_display_mode'))
        updated_date = _auth_text_value(_EMAIL_LOGIN_STATE.get('terms_updated_date'), AUTH_TERMS_DEFAULT_UPDATED_DATE, 40)
        docs = _auth_terms_normalize_documents(_EMAIL_LOGIN_STATE.get('terms_documents'))
    return {
        'enabled': enabled,
        'display_mode': mode,
        'updated_date': updated_date,
        'documents': _auth_terms_documents_public(docs, include_content=include_content),
    }


def _auth_terms_acceptance_required() -> bool:
    with _EMAIL_LOGIN_LOCK:
        return bool(_EMAIL_LOGIN_STATE.get('terms_enabled', False))


def _auth_terms_verify_acceptance(data) -> None:
    if not _auth_terms_acceptance_required():
        return
    row = data if isinstance(data, dict) else {}
    accepted = row.get('terms_accepted') or row.get('termsAccepted') or row.get('accept_terms') or row.get('accepted_terms')
    if not bool(accepted):
        raise ValueError('请先阅读并同意登录条款')


def _normalize_email_domain_rules(value=None) -> list[str]:
    if value is None:
        raw_items = []
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = re.split(r'[\s,，;；]+', str(value or ''))
    rules: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        rule = str(item or '').strip().lower()
        if not rule:
            continue
        if rule.startswith('@'):
            rule = rule[1:]
        while '..' in rule:
            rule = rule.replace('..', '.')
        if rule.startswith('*.'):
            suffix = rule[2:].strip('.')
            if not suffix or not re.fullmatch(r'[a-z0-9*.-]+', suffix):
                continue
            rule = '*.' + suffix
        else:
            rule = rule.strip('.')
            if not rule or '*' in rule or not re.fullmatch(r'[a-z0-9.-]+', rule):
                continue
        if rule and rule not in seen:
            seen.add(rule)
            rules.append(rule[:120])
        if len(rules) >= 80:
            break
    return rules


def _email_domain_allowed(normalized_email: str) -> bool:
    email_addr = _normalize_login_email(normalized_email)
    if '@' not in email_addr:
        return False
    domain = email_addr.rsplit('@', 1)[1].strip().lower()
    with _EMAIL_LOGIN_LOCK:
        rules = _normalize_email_domain_rules(_EMAIL_LOGIN_STATE.get('allowed_email_domains'))
    if not rules:
        return True
    for rule in rules:
        if rule.startswith('*.'):
            suffix = rule[2:]
            if domain == suffix or domain.endswith('.' + suffix):
                return True
        elif domain == rule:
            return True
    return False


def _email_login_registration_open() -> bool:
    with _EMAIL_LOGIN_LOCK:
        return bool(_EMAIL_LOGIN_STATE.get('registration_open', True))


def _email_login_invite_required() -> bool:
    with _EMAIL_LOGIN_LOCK:
        return bool(_EMAIL_LOGIN_STATE.get('invite_required', True))
