# ====== sandbox skills registry ======
# 目标：给现有 sandbox_* 执行平面补一层轻量技能说明/脚本注册。
# 原则：不新增重复工具名；不动态 import 用户可写代码；由独立 Runner 把部署目录里的 app3_skills 复制到每次执行的临时卷。

_SANDBOX_SKILL_CONTAINER_DIR = '/opt/app3_skills'


def _sandbox_skills_enabled() -> bool:
    try:
        raw = str(app_getenv('SANDBOX_SKILLS_ENABLED', '1') or '1').strip().lower()
    except Exception:
        raw = '1'
    return raw not in {'0', 'false', 'off', 'no'}


def _sandbox_skills_host_dir() -> str:
    try:
        configured = str(app_getenv('SANDBOX_SKILLS_DIR', '') or '').strip()
    except Exception:
        configured = ''
    if configured:
        return os.path.abspath(configured)
    return os.path.join(BASE_DIR, 'app3_skills')


def _sandbox_skills_container_dir() -> str:
    try:
        configured = str(app_getenv('SANDBOX_SKILLS_CONTAINER_DIR', '') or '').strip()
    except Exception:
        configured = ''
    return configured or _SANDBOX_SKILL_CONTAINER_DIR


def _sandbox_skill_safe_name(name: str = '') -> str:
    return re.sub(r'[^a-z0-9_.-]+', '', str(name or '').strip().lower())[:80]


def _sandbox_skill_safe_relpath(value: str = '') -> str:
    raw = str(value or '').replace('\\', '/').strip()
    raw_parts = raw.split('/')
    if not raw or raw.startswith('/') or raw.startswith('../') or '..' in raw_parts:
        return ''
    parts = [p for p in raw_parts if p and p != '.']
    if not parts:
        return ''
    clean = '/'.join(re.sub(r'[^a-zA-Z0-9_.\-/]+', '', p) for p in parts)
    return clean[:240]


def _sandbox_skill_read_manifest(skill_dir: str = '', safe_name: str = '') -> tuple[dict, list[str]]:
    errors: list[str] = []
    path = os.path.join(skill_dir, 'skill.json')
    manifest: dict = {}
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                parsed = json.loads(f.read(64 * 1024))
            if isinstance(parsed, dict):
                manifest = dict(parsed)
            else:
                errors.append('manifest_not_object')
        except Exception as exc:
            errors.append(f'manifest_read_failed:{type(exc).__name__}')
    else:
        errors.append('manifest_missing')

    name = _sandbox_skill_safe_name(manifest.get('name') or safe_name)
    if not name:
        name = safe_name
    if name != safe_name:
        errors.append('manifest_name_mismatch')
        name = safe_name

    entrypoint = _sandbox_skill_safe_relpath(manifest.get('entrypoint') or 'SKILL.md') or 'SKILL.md'
    scripts = []
    for item in manifest.get('scripts') or []:
        rel = _sandbox_skill_safe_relpath(item)
        if rel:
            scripts.append(rel)
    modes = []
    for item in manifest.get('modes') or ['chat_completions', 'responses']:
        val = str(item or '').strip()
        if val in {'chat_completions', 'responses'} and val not in modes:
            modes.append(val)
    groups = []
    for item in manifest.get('groups') or ['sandbox']:
        val = _sandbox_skill_safe_name(item)
        if val and val not in groups:
            groups.append(val)
    tools = []
    for item in manifest.get('tools') or []:
        val = _sandbox_skill_safe_name(item)
        if val and val not in tools:
            tools.append(val)

    def _safe_string_list(key: str = '', limit: int = 24) -> list[str]:
        rows = []
        for item in manifest.get(key) or []:
            val = str(item or '').strip().lower()
            val = re.sub(r'[^a-z0-9_+./#-]+', '', val)[:48]
            if val and val not in rows:
                rows.append(val)
            if len(rows) >= int(limit or 24):
                break
        return rows

    normalized = {
        'schema_version': str(manifest.get('schema_version') or 'app3.skill.v1')[:40],
        'name': name,
        'public_key': _sandbox_skill_safe_name(manifest.get('public_key') or ''),
        'title': str(manifest.get('title') or name).strip()[:120],
        'version': str(manifest.get('version') or '').strip()[:80],
        'description': str(manifest.get('description') or '').strip()[:600],
        'modes': modes or ['chat_completions', 'responses'],
        'groups': groups or ['sandbox'],
        'tools': tools,
        'file_types': _safe_string_list('file_types', 32),
        'task_types': _safe_string_list('task_types', 32),
        'risk_level': (str(manifest.get('risk_level') or 'low').strip().lower() if str(manifest.get('risk_level') or 'low').strip().lower() in {'low', 'medium', 'high'} else 'low'),
        'entrypoint': entrypoint,
        'scripts': scripts,
        'input_contract': str(manifest.get('input_contract') or '').strip()[:800],
        'output_contract': str(manifest.get('output_contract') or '').strip()[:800],
        'activation': [str(x or '').strip()[:120] for x in (manifest.get('activation') or []) if str(x or '').strip()],
        'trace_events': [str(x or '').strip()[:120] for x in (manifest.get('trace_events') or []) if str(x or '').strip()],
        'runtime_policy': str(manifest.get('runtime_policy') or '').strip()[:1000],
    }

    entry_abs = os.path.join(skill_dir, entrypoint.replace('/', os.sep))
    if not os.path.isfile(entry_abs):
        errors.append('entrypoint_missing')
    for rel in scripts:
        if not os.path.isfile(os.path.join(skill_dir, rel.replace('/', os.sep))):
            errors.append('script_missing:' + rel)
    return normalized, errors


def _sandbox_skill_catalog(max_chars_per_skill: int = 1400) -> list[dict]:
    """Scan deployment skills. Manifest is metadata; SKILL.md is model guidance."""
    if not _sandbox_skills_enabled():
        return []
    base = _sandbox_skills_host_dir()
    try:
        names = sorted(os.listdir(base))
    except Exception:
        return []
    out: list[dict] = []
    for name in names:
        safe = _sandbox_skill_safe_name(name)
        if not safe or safe.startswith('.') or safe == '_shared' or safe != str(name).strip().lower():
            continue
        skill_dir = os.path.join(base, name)
        if not os.path.isdir(skill_dir):
            continue
        manifest, manifest_errors = _sandbox_skill_read_manifest(skill_dir, safe)
        skill_md = os.path.join(skill_dir, str(manifest.get('entrypoint') or 'SKILL.md').replace('/', os.sep))
        text = ''
        try:
            read_limit = int(max_chars_per_skill or 0)
        except Exception:
            read_limit = 1400
        if read_limit > 0 and os.path.isfile(skill_md):
            try:
                with open(skill_md, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read(read_limit + 1)
            except Exception:
                text = ''
        text = str(text or '').strip()
        if read_limit > 0 and len(text) > read_limit:
            text = text[:read_limit].rstrip() + '\n…'
        out.append({
            'name': safe,
            'manifest': manifest,
            'manifest_errors': manifest_errors,
            'host_dir': skill_dir,
            'container_dir': _sandbox_skills_container_dir().rstrip('/') + '/' + safe,
            'skill_md': text,
        })
    return out


_SANDBOX_SKILL_KEYWORDS = {
    'sandbox': {'sandbox', '沙盒', '运行', '代码', 'python', '脚本', '文件', '生成', '修改', 'excel', 'word', 'docx', 'xlsx'},
    'docx': {'docx', 'word', '文档', '合同', '报告', '论文', '简历', 'doc'},
    'pdfs': {'pdf', '页面', '分页', '合并', '拆分', '扫描', '版式'},
    'spreadsheets': {'xlsx', 'xls', 'excel', 'csv', '表格', '公式', '数据表', '工作簿'},
    'slides': {'ppt', 'pptx', 'powerpoint', 'slide', 'slides', '幻灯片', '演示', '汇报'},
    'security_scan': {'安全', '扫描', '恶意', '脚本', 'zip', '压缩包', '病毒', '隔离', '风险', 'html', 'js'},
}

_SANDBOX_SKILL_PRODUCT_PROFILES = {
    'sandbox': {
        'file_types': {'txt', 'md', 'json', 'yaml', 'yml', 'py', 'js', 'ts', 'html', 'css', 'zip'},
        'task_types': {'read', 'edit', 'run', 'test', 'generate', 'publish', 'diff'},
    },
    'docx': {
        'file_types': {'doc', 'docx'},
        'task_types': {'read', 'outline', 'revise', 'generate', 'format', 'publish'},
    },
    'pdfs': {
        'file_types': {'pdf'},
        'task_types': {'read', 'render', 'extract', 'split', 'merge', 'visual_evidence'},
    },
    'spreadsheets': {
        'file_types': {'xlsx', 'xls', 'csv', 'tsv'},
        'task_types': {'read', 'summarize', 'calculate', 'compare', 'transform', 'generate', 'edit'},
    },
    'slides': {
        'file_types': {'ppt', 'pptx'},
        'task_types': {'read', 'outline', 'generate', 'revise', 'publish'},
    },
    'security_scan': {
        'file_types': {'zip', 'rar', '7z', 'tar', 'gz', 'html', 'js', 'mjs', 'vbs', 'ps1', 'bat', 'cmd', 'sh', 'exe', 'dll'},
        'task_types': {'scan', 'risk', 'malware', 'inspect', 'quarantine'},
    },
}

_SANDBOX_SKILL_RISK_WORDS = {
    '安全', '风险', '病毒', '恶意', '木马', '扫描', '可疑', '危险', '隔离', '查毒',
    'security', 'risk', 'malware', 'virus', 'trojan', 'suspicious', 'scan', 'unsafe',
}


def _sandbox_skill_manifest_file_types(manifest: dict | None = None, name: str = '') -> set[str]:
    row = manifest if isinstance(manifest, dict) else {}
    values = {str(x or '').strip().lower().lstrip('.') for x in (row.get('file_types') or []) if str(x or '').strip()}
    if values:
        return values
    return set((_SANDBOX_SKILL_PRODUCT_PROFILES.get(str(name or '').strip()) or {}).get('file_types') or set())


def _sandbox_skill_manifest_task_types(manifest: dict | None = None, name: str = '') -> set[str]:
    row = manifest if isinstance(manifest, dict) else {}
    values = {str(x or '').strip().lower() for x in (row.get('task_types') or []) if str(x or '').strip()}
    if values:
        return values
    return set((_SANDBOX_SKILL_PRODUCT_PROFILES.get(str(name or '').strip()) or {}).get('task_types') or set())


def _sandbox_skill_context_file_rows(messages: list | None = None, max_rows: int = 12) -> list[dict]:
    """Collect lightweight file facts for product-grade skill selection.

    This is not an intent router and never reads file content. It only exposes
    filename/ext/mime/source facts that already exist in the conversation/file
    registry, so skill loading can avoid pure keyword guessing.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    try:
        records_fn = globals().get('_file_delivery_existing_file_records')
        records = records_fn(messages or []) if callable(records_fn) else []
    except Exception:
        records = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        filename = str(rec.get('filename') or rec.get('saved_filename') or '').strip()
        if not filename:
            continue
        ext = str(rec.get('ext') or '').strip().lower().lstrip('.')
        if not ext:
            m = re.search(r'\.([a-zA-Z0-9]{1,12})(?:$|[?#])', filename)
            ext = (m.group(1).lower() if m else '')
        mime = str(rec.get('mime') or rec.get('content_type') or '').strip().lower()[:120]
        source = str(rec.get('source') or rec.get('namespace') or 'file').strip()[:80]
        key = f'{filename}|{ext}|{source}'
        if key in seen:
            continue
        seen.add(key)
        rows.append({'filename': filename[:240], 'ext': ext[:24], 'mime': mime, 'source': source})
        if len(rows) >= int(max_rows or 12):
            break
    return rows


def _sandbox_skill_route_file_likely(route_signals: dict | None = None) -> bool:
    sig = route_signals if isinstance(route_signals, dict) else {}
    return bool(
        str(sig.get('route_mode') or '').strip().lower() == 'file'
        or str(sig.get('file_action') or '').strip().lower() == 'sandbox_files'
        or str(sig.get('primary_delivery') or '').strip().lower() in {'file', 'file_edit'}
        or bool(sig.get('file_hint_active'))
    )


def _sandbox_select_skill_rows_for_context(
    text: str = '',
    *,
    messages: list | None = None,
    route_signals: dict | None = None,
    catalog: list | None = None,
    max_count: int = 3,
) -> list[dict]:
    """Select sandbox skill guides from structured context.

    Product rule: file facts and route signals are primary. Keyword matching is
    only a fallback signal so normal chat does not load document skills just
    because a word appears in the prompt.
    """
    raw = str(text or '').lower()
    files = _sandbox_skill_context_file_rows(messages or [], max_rows=12)
    file_exts = {str((f or {}).get('ext') or '').strip().lower().lstrip('.') for f in files if str((f or {}).get('ext') or '').strip()}
    file_likely = _sandbox_skill_route_file_likely(route_signals) or bool(files)
    risk_requested = any(str(w).lower() in raw for w in _SANDBOX_SKILL_RISK_WORDS)
    rows: list[dict] = []
    catalog_rows = catalog if isinstance(catalog, list) else []

    for item in catalog_rows:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()
        manifest = item.get('manifest') if isinstance(item.get('manifest'), dict) else {}
        if not name:
            continue
        score = 0
        reasons: list[str] = []
        profile_types = _sandbox_skill_manifest_file_types(manifest, name)
        matched_exts = sorted([ext for ext in file_exts if ext and ext in profile_types])
        if name == 'security_scan':
            if risk_requested and (matched_exts or file_likely):
                score += 88
                reasons.append('risk_request')
                if matched_exts:
                    reasons.append('file_type:' + ','.join(matched_exts[:5]))
            elif matched_exts and risk_requested:
                score += 50
                reasons.append('risk_text_hint')
            elif matched_exts:
                # Suspicious extensions alone are not enough to dominate normal
                # coding/file tasks; keep as low-priority hint.
                score += 8
                reasons.append('risky_ext_hint')
        elif matched_exts:
            score += 80
            reasons.append('file_type:' + ','.join(matched_exts[:5]))
        if name == 'sandbox' and file_likely:
            score += 35
            reasons.append('file_route')
        task_types = _sandbox_skill_manifest_task_types(manifest, name)
        for task in task_types:
            if task and task in raw:
                score += 12
                reasons.append('task:' + task)
                break
        for key in (_SANDBOX_SKILL_KEYWORDS.get(name) or set()):
            if key and str(key).lower() in raw:
                score += 8 if file_likely else 3
                reasons.append('text_hint:' + str(key)[:24])
                break
        activation = [str(x or '').strip().lower() for x in (manifest.get('activation') or []) if str(x or '').strip()]
        for key in activation:
            if key and key not in {'??', '???', '????'} and key in raw:
                score += 10 if file_likely else 4
                reasons.append('activation:' + key[:24])
                break
        # Do not load domain skill guides from weak hints. File extension matches
        # and explicit risk/document intents score high; stray words or risky
        # extensions alone should not inject a full SKILL.md.
        if name != 'sandbox' and score < 18:
            score = 0
            reasons = []
        if score > 0:
            confidence = min(0.99, max(0.15, score / 100.0))
            rows.append({'name': name, 'score': score, 'confidence': round(confidence, 2), 'reasons': reasons[:4]})

    rows.sort(key=lambda r: (-int(r.get('score') or 0), str(r.get('name') or '')))
    selected: list[dict] = []
    for row in rows:
        name = str(row.get('name') or '').strip()
        if not name or name in {str(x.get('name') or '') for x in selected}:
            continue
        # Sandbox is the base guide. Keep it when a file route exists or when a
        # domain skill was selected, but do not let it crowd out domain skills.
        selected.append(row)
        if len(selected) >= int(max_count or 3):
            break
    if file_likely and 'sandbox' not in {str(x.get('name') or '') for x in selected}:
        selected.insert(0, {'name': 'sandbox', 'score': 35, 'confidence': 0.35, 'reasons': ['file_route']})
        selected = selected[:int(max_count or 3)]
    return selected


def _sandbox_select_skill_names_for_text(text: str = '', max_count: int = 4) -> list[str]:
    raw = str(text or '').lower()
    scores: list[tuple[int, str]] = []
    for name, keys in _SANDBOX_SKILL_KEYWORDS.items():
        score = 0
        for key in keys:
            if key and key.lower() in raw:
                score += 1
        if score:
            scores.append((score, name))
    scores.sort(key=lambda item: (-item[0], item[1]))
    selected = [name for _score, name in scores[:max_count]]
    return selected


def _sandbox_skills_prompt_for_user(
    user_text: str = '',
    compact: bool = True,
    *,
    messages: list | None = None,
    route_signals: dict | None = None,
    max_skills: int = 3,
) -> str:
    """Build relevant sandbox skill guidance directly into the request context."""
    if not _sandbox_skills_enabled():
        return ''
    catalog = _sandbox_skill_catalog(max_chars_per_skill=900 if compact else 1600)
    if not catalog:
        return ''
    by_name = {str(item.get('name') or ''): item for item in catalog if isinstance(item, dict)}
    selected_rows = _sandbox_select_skill_rows_for_context(
        user_text,
        messages=messages or [],
        route_signals=route_signals if isinstance(route_signals, dict) else {},
        catalog=catalog,
        max_count=max_skills,
    )
    ordered_names = [str(row.get('name') or '').strip() for row in selected_rows if str(row.get('name') or '').strip()]
    selected = [by_name[n] for n in ordered_names if n in by_name]
    if not selected:
        return ''
    selected_meta = {
        str(row.get('name') or '').strip(): row
        for row in selected_rows
        if str(row.get('name') or '').strip()
    }
    lines = [
        'Sandbox skill guidance available for this request. Do not add new tool names; use existing sandbox_run / sandbox_create_office_file / sandbox_publish_files only.',
        f'Skills root in sandbox: {_sandbox_skills_container_dir()}',
    ]
    for item in selected:
        name = str(item.get('name') or '').strip()
        md = str(item.get('skill_md') or '').strip()
        if not name or not md:
            continue
        meta = selected_meta.get(name) or {}
        reason = ', '.join([str(x or '') for x in (meta.get('reasons') or []) if str(x or '')])
        if reason:
            lines.append(f'Selected skill: {name}; reason={reason}; confidence={meta.get("confidence", "")}.')
        lines.append(f'[{name}] {md}')
    return '\n'.join(lines).strip()


def _sandbox_skills_public_summary() -> dict:
    catalog = _sandbox_skill_catalog(max_chars_per_skill=300)
    registry_summary = {}
    try:
        manifest_registry_fn = globals().get('skill_registry_with_manifest_summary')
        if callable(manifest_registry_fn):
            registry_summary = manifest_registry_fn([dict(item.get('manifest') or {}) for item in catalog if isinstance(item, dict)])
        else:
            # Public/customer-safe summary only. Internal trace spans must stay in
            # backend diagnostics and never leak through the generic skills API.
            registry_fn = globals().get('skill_registry_public_summary')
            if callable(registry_fn):
                registry_summary = registry_fn()
    except Exception:
        registry_summary = {}
    return {
        'enabled': _sandbox_skills_enabled(),
        'host_dir_exists': os.path.isdir(_sandbox_skills_host_dir()),
        'container_dir': _sandbox_skills_container_dir(),
        'skills': [str(item.get('name') or '') for item in catalog if isinstance(item, dict)],
        'manifests': [dict(item.get('manifest') or {}) for item in catalog if isinstance(item, dict)],
        'manifest_errors': {
            str(item.get('name') or ''): [str(x or '') for x in (item.get('manifest_errors') or []) if str(x or '')]
            for item in catalog
            if isinstance(item, dict) and (item.get('manifest_errors') or [])
        },
        'registry': registry_summary,
    }
