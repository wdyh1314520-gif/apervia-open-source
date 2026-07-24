# generated file extension policy, path helpers, and artifact persistence.

ALLOWED_EXT = {
    # text & docs
    ".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".log", ".cfg",
    ".pdf",
    ".docx", ".doc",
    ".xlsx", ".xls",
    ".pptx",

    # code / web / config
    ".py", ".c", ".cc", ".cpp", ".cxx",
    ".h", ".hpp",
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".mts", ".cts", ".java", ".go", ".rs",
    ".php", ".rb", ".swift", ".kt", ".cs",
    ".sql", ".yaml", ".yml", ".xml", ".toml", ".ini", ".sh", ".bat", ".ps1",
    ".html", ".htm", ".css", ".scss", ".less", ".svg", ".vue", ".svelte", ".astro",

    # archives / binaries
    ".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz",

    # images
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".tif", ".tiff", ".ico", ".jfif", ".jpe", ".dib",
    ".heic", ".heif",
}

SPECIAL_TEXT_FILENAMES = {
    ".env", ".env.local", ".env.development", ".env.production",
    ".gitignore", ".gitattributes", ".dockerignore",
    "dockerfile", "makefile", "jenkinsfile", "procfile",
    "requirements.txt", "pipfile", "pipfile.lock",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "readme", "license", ".npmrc", ".yarnrc", ".editorconfig", ".prettierrc", ".eslintrc", ".gitmodules",
}


MODEL_SUPPORTED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
HEIF_IMAGE_MIMES = {"image/heic", "image/heif", "image/heic-sequence", "image/heif-sequence"}
HEIF_IMAGE_EXTS = {".heic", ".heif"}
UPLOAD_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".ico", ".jfif", ".jpe", ".dib", ".heic", ".heif"}
UPLOAD_IMAGE_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jpe": "image/jpeg",
    ".jfif": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".dib": "image/bmp",
    ".svg": "image/svg+xml",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".ico": "image/x-icon",
    ".heic": "image/heic",
    ".heif": "image/heif",
}


def _is_heif_upload(ext: str = '', mime: str = '') -> bool:
    ext_l = str(ext or '').strip().lower()
    mime_l = str(mime or '').split(';', 1)[0].strip().lower()
    return ext_l in HEIF_IMAGE_EXTS or mime_l in HEIF_IMAGE_MIMES


def _model_image_ext_for_mime(mime: str = '') -> str:
    mime_l = str(mime or '').split(';', 1)[0].strip().lower()
    if mime_l == 'image/png':
        return '.png'
    if mime_l == 'image/webp':
        return '.webp'
    if mime_l == 'image/gif':
        return '.gif'
    return '.jpg'


def _prepare_uploaded_image_for_model(raw: bytes, filename: str = '', mime_hint: str = '') -> tuple[bytes, str]:
    if not raw:
        raise ValueError('empty_image')
    ext = os.path.splitext(str(filename or '').strip())[1].lower()
    mime = str(mime_hint or '').split(';', 1)[0].strip().lower()
    if not mime:
        mime = UPLOAD_IMAGE_MIME_BY_EXT.get(ext, '')
    if not mime:
        mime = 'application/octet-stream'

    coerced_raw, coerced_mime = _coerce_image_bytes_for_model(raw, mime)
    final_raw = coerced_raw if coerced_raw else raw
    final_mime = str(coerced_mime or mime or '').split(';', 1)[0].strip().lower()

    if final_raw and final_mime in MODEL_SUPPORTED_IMAGE_MIMES:
        return final_raw, final_mime
    if raw and mime in MODEL_SUPPORTED_IMAGE_MIMES:
        return raw, mime
    raise ValueError(f'unsupported_uploaded_image_format:{final_mime or mime or "unknown"}')

def _safe_filename(name: str) -> str:
    name = (name or "").strip()
    # keep simple chars, dots, dashes, spaces, underscores, and CJK
    name = re.sub(r"[^\w\-. ()\u4e00-\u9fff]", "_", name)
    if not name:
        name = f"file-{uuid.uuid4().hex[:8]}.txt"
    # prevent path tricks
    name = name.replace("..", "_")
    return name[:120]


def _safe_artifact_relative_path(name: str) -> str:
    raw = str(name or '').strip().replace('\\', '/')
    if not raw:
        return ''
    raw = raw.replace('\x00', '')
    raw = re.sub(r'^[A-Za-z]:/+', '', raw).lstrip('/')
    parts: list[str] = []
    for part in raw.split('/'):
        part = str(part or '').strip()
        if not part or part in {'.', '..'}:
            continue
        safe = re.sub(r"[^\w\-. ()\[\]@+\u4e00-\u9fff]", "_", part).replace('..', '_')[:120].strip().strip('.')
        if safe and safe not in {'.', '..'}:
            parts.append(safe)
    if not parts:
        return ''
    rel = '/'.join(parts)
    while '../' in rel or '/..' in rel:
        rel = rel.replace('../', '_/').replace('/..', '/_')
    return rel[:420]


def _flat_filename_from_relative_path(rel_path: str, fallback: str = '') -> str:
    rel = _safe_artifact_relative_path(rel_path or fallback)
    if not rel:
        return _safe_filename(fallback or '')
    return _safe_filename(rel.replace('/', '_'))


def _zip_arcname_from_saved_item(item: dict | None = None) -> str:
    row = item if isinstance(item, dict) else {}
    for key in ('relative_path', 'logical_path', 'original_filename', 'path'):
        rel = _safe_artifact_relative_path(str(row.get(key) or '').strip())
        if rel:
            return rel
    filename = str(row.get('filename') or row.get('saved_filename') or '').strip()
    return _safe_artifact_relative_path(filename) or _safe_filename(filename)


def _dedupe_zip_arcname(arcname: str, seen: set[str]) -> str:
    name = _safe_artifact_relative_path(arcname) or _safe_filename(arcname or '')
    if not name:
        name = f'file-{uuid.uuid4().hex[:8]}.txt'
    key = name.lower()
    if key not in seen:
        seen.add(key)
        return name
    if '/' in name:
        parent, leaf = name.rsplit('/', 1)
    else:
        parent, leaf = '', name
    stem, ext = os.path.splitext(leaf)
    stem = stem or 'file'
    for i in range(2, 1000):
        cand_leaf = f'{stem}-v{i}{ext}'
        cand = f'{parent}/{cand_leaf}' if parent else cand_leaf
        key = cand.lower()
        if key not in seen:
            seen.add(key)
            return cand
    cand = f'{parent}/{stem}-{uuid.uuid4().hex[:8]}{ext}' if parent else f'{stem}-{uuid.uuid4().hex[:8]}{ext}'
    seen.add(cand.lower())
    return cand


def _should_bundle_generated_files(saved_files: list[dict] | None = None, artifacts: list[dict] | None = None, delivery_mode: str = '') -> bool:
    files = [x for x in (saved_files or []) if isinstance(x, dict)]
    if not files and artifacts:
        for a in artifacts or []:
            if not isinstance(a, dict):
                continue
            original_filename = str(a.get('filename') or '').strip()
            rel = _safe_artifact_relative_path(original_filename)
            flat = _flat_filename_from_relative_path(rel, original_filename)
            if flat:
                files.append({'filename': flat, 'relative_path': rel or flat})
    if len(files) <= 1:
        return False
    if str(delivery_mode or '').strip().lower() == 'zip_bundle':
        return True
    try:
        threshold = int(str(app_getenv('GENERATED_FILES_AUTO_ZIP_THRESHOLD', '4') or '4').strip())
    except Exception:
        threshold = 4
    threshold = max(2, min(threshold, 20))
    image_exts = set(UPLOAD_IMAGE_EXTS or set())
    non_image_files = [x for x in files if os.path.splitext(str(x.get('filename') or ''))[1].lower() not in image_exts]
    if not non_image_files:
        return False
    if len(files) > threshold:
        return True
    for item in files:
        rel = str(item.get('relative_path') or item.get('logical_path') or '').strip().replace('\\', '/')
        if '/' in rel:
            return True
    return False


def _generated_files_bundle_filename(messages: list | None = None, *, saved_files: list[dict] | None = None, info: dict | None = None) -> str:
    info = dict(info or {})
    explicit_name = str(info.get('filename') or '').strip()
    if explicit_name:
        base = os.path.basename(explicit_name)
        if base:
            return _safe_filename(base if base.lower().endswith('.zip') else f'{os.path.splitext(base)[0]}.zip')
    files = [x for x in (saved_files or []) if isinstance(x, dict)]
    has_tree = any('/' in str((x.get('relative_path') or '')).replace('\\', '/') for x in files)
    if has_tree or len(files) > 1:
        return 'project.zip'
    resolver = globals().get('_resolve_zip_bundle_filename')
    if callable(resolver):
        try:
            name = str(resolver(messages or [], saved_files=saved_files or [], info=info or {}) or '').strip()
            if name:
                base = os.path.basename(name)
                if base and os.path.splitext(base)[0].lower() not in {'readme', 'package', 'tsconfig', 'next.config', 'postcss.config', 'tailwind.config'}:
                    return _safe_filename(base if base.lower().endswith('.zip') else f'{os.path.splitext(base)[0]}.zip')
        except Exception:
            pass
    return 'generated-files.zip'


def _dedupe_filename(path_dir: str, filename: str) -> str:
    """If filename exists in path_dir, append -v2/-v3... to avoid overwriting."""
    try:
        base, ext = os.path.splitext(filename)
        full = os.path.join(path_dir, filename)
        if not os.path.exists(full):
            return filename
        for i in range(2, 1000):
            cand = f"{base}-v{i}{ext}"
            if not os.path.exists(os.path.join(path_dir, cand)):
                return cand
        # fallback
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{base}-{ts}{ext}"
    except Exception:
        return filename


def _try_parse_artifact_json(text: str):
    """Return (answer:str, artifacts:list[dict]) or None."""
    if not text:
        return None

    def _normalize_obj(obj):
        if not isinstance(obj, dict):
            return None
        arts = obj.get("artifacts")
        if isinstance(arts, list) and arts:
            return (obj.get("answer") or "", arts)
        if obj.get("filename") and ("data" in obj):
            return (obj.get("answer") or "", [obj])
        return None

    s = str(text).strip()
    if not s:
        return None

    # sometimes model may wrap in code fences
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()

    try:
        parsed = _normalize_obj(json.loads(s))
        if parsed:
            return parsed
    except Exception:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", s):
        start_idx = match.start()
        try:
            obj, _end = decoder.raw_decode(s[start_idx:])
        except Exception:
            continue
        parsed = _normalize_obj(obj)
        if parsed:
            return parsed
    return None


def _user_wants_excel(messages: list) -> bool:
    """Heuristic: whether the user explicitly wants an Excel file (.xlsx/.xls)."""
    try:
        last = ""
        for m in reversed(messages or []):
            if isinstance(m, dict) and m.get("role") == "user":
                last = str(m.get("content") or "")
                break
        t = last.lower()
        keys = ["xlsx", ".xlsx", "xls", ".xls", "excel", "表格", "做成表", "做个表", "导出表", "导出excel", "生成excel", "生成表格"]
        return any(k in last or k in t for k in keys)
    except Exception:
        return False


def _message_quote_text(m: dict) -> str:
    if not isinstance(m, dict):
        return ""
    q = m.get("_quote")
    if isinstance(q, str):
        return q.strip()
    return ""


def _combine_message_text_and_quote(text: str, quote_text: str) -> str:
    body = str(text or "").strip()
    quote = str(quote_text or "").strip()
    if quote and body:
        return f"引用内容：\n{quote}\n\n当前用户消息：\n{body}"
    if quote:
        return f"引用内容：\n{quote}"
    return body


def _latest_user_message_text(messages: list) -> str:
    try:
        for m in reversed(messages or []):
            if isinstance(m, dict) and m.get("role") == "user":
                return _combine_message_text_and_quote(_msg_content_text(m.get("content")), _message_quote_text(m))
    except Exception:
        pass
    return ""


def _extract_requested_filename_from_text(user_text: str) -> str:
    raw = str(user_text or "")
    if not raw:
        return ""
    allowed_exts = "txt|md|markdown|json|jsonl|csv|tsv|xlsx|xls|docx|pdf|zip|pptx|py|c|cc|cpp|cxx|h|hpp|js|ts|tsx|jsx|html|htm|css|scss|less|java|go|rs|php|rb|swift|kt|cs|sql|xml|yaml|yml|toml|ini|sh|bat|ps1"
    pattern = re.compile(rf"(?<![\/\w.-])([A-Za-z0-9][A-Za-z0-9_\- ]{{0,80}}\.(?:{allowed_exts}))(?![\w.-])", re.I)
    for match in pattern.finditer(raw):
        candidate = str(match.group(1) or "").strip().strip('`"“”\'')
        if not candidate:
            continue
        if any(sep in candidate for sep in ('/', '\\')):
            continue
        return _safe_filename(candidate)
    return ""


def _detect_requested_extension_from_text(user_text: str) -> str:
    raw = str(user_text or "")
    if not raw:
        return ""
    patterns = [
        r"\.([A-Za-z0-9]{1,10})\s*文件",
        r"保存成\s*\.([A-Za-z0-9]{1,10})",
        r"保存为\s*\.([A-Za-z0-9]{1,10})",
        r"导出成\s*\.([A-Za-z0-9]{1,10})",
        r"导出为\s*\.([A-Za-z0-9]{1,10})",
        r"生成\s*\.([A-Za-z0-9]{1,10})\s*文件",
        r"写一个\s*\.([A-Za-z0-9]{1,10})\s*文件",
    ]
    for pat in patterns:
        m = re.search(pat, raw, flags=re.I)
        if m:
            ext = str(m.group(1) or "").strip().lower()
            if ext:
                return ext
    return ""


def _detect_requested_format_label(user_text: str) -> str:
    raw = str(user_text or "")
    t = raw.lower()
    mapping = [
        (("excel", ".xlsx", ".xls", "表格", "工作簿"), "Excel 表格"),
        (("word", ".docx", ".doc", "文档"), "Word 文档"),
        (("pdf", ".pdf"), "PDF 文件"),
        (("markdown", ".md", "md文件"), "Markdown 文件"),
        (("json", ".json", "接口数据"), "JSON 文件"),
        (("csv", ".csv"), "CSV 文件"),
        (("ppt", "pptx", ".pptx", "幻灯片", "演示文稿"), "PPTX 演示文稿"),
        (("zip", ".zip", "压缩包"), "ZIP 压缩包"),
        (("python", ".py"), "Python 源文件"),
        (("c语言", ".c", " c 文件", "c文件"), "C 源文件"),
        (("cpp", ".cpp", "c++", "cxx", ".cc"), "C++ 源文件"),
        (("html", ".html", ".htm", "网页文件"), "HTML 文件"),
    ]
    for keys, label in mapping:
        if any(k in raw or k in t for k in keys):
            return label
    return ""


def _suggest_filename_for_extension(user_text: str, ext: str) -> str:
    normalized_ext = str(ext or "").strip().lower().lstrip('.')
    if not normalized_ext:
        return ""
    t = str(user_text or "").lower()
    stem = "output"
    topic_map = [
        (("最大公约数", "gcd"), "gcd_example"),
        (("天气", "weather"), "weather_report"),
        (("简历", "resume", "cv"), "resume"),
        (("表格", "excel", "csv"), "table_export"),
        (("报告", "report"), "report"),
        (("代码", "程序", "script"), "code_output"),
        (("游戏", "rpg", "game"), "game_project"),
        (("网站", "网页", "web", "html"), "web_project"),
    ]
    for keys, candidate in topic_map:
        if any(k in t for k in keys):
            stem = candidate
            break
    return _safe_filename(f"{stem}.{normalized_ext}")


def _infer_file_delivery_mode_from_text(user_text: str, *, info: dict | None = None) -> str:
    info = dict(info or {})
    raw = str(user_text or info.get('user_text') or '').strip()
    if not raw:
        return 'none'
    filename = str(info.get('filename') or '').strip() or _extract_requested_filename_from_text(raw)
    ext = str(info.get('ext') or '').strip().lower()
    if not ext and filename and '.' in filename:
        ext = filename.rsplit('.', 1)[-1].lower()
    if not ext:
        ext = _detect_requested_extension_from_text(raw)
    format_label = str(info.get('format_label') or '').strip() or _detect_requested_format_label(raw)
    explicit_zip = bool(
        (filename and filename.lower().endswith('.zip'))
        or ext == 'zip'
        or format_label == 'ZIP 压缩包'
        or re.search(r'(?:\.zip\b|\bzip\b|压缩包|打包成?zip|源码包|项目包|bundle)', raw, flags=re.I)
    )
    project_like = bool(re.search(
        r'(可运行.{0,12}(项目|游戏|程序)|完整项目|完整源码|多文件|目录结构|源码包|项目源码|工程文件|前后端|网站项目|游戏项目|实战游戏)',
        raw,
        flags=re.I,
    ))
    if explicit_zip or project_like:
        return 'zip_bundle'
    wants_file = bool(info.get('wants_file')) if info else _has_explicit_file_delivery_intent(raw)
    return 'single_file' if wants_file else 'none'


def _normalize_file_delivery_mode(mode: str | None, *, user_text: str = '', info: dict | None = None, default: str = 'single_file') -> str:
    raw = str(mode or '').strip().lower()
    aliases = {
        'zip': 'zip_bundle',
        'zip_bundle': 'zip_bundle',
        'bundle': 'zip_bundle',
        'archive': 'zip_bundle',
        'archive_bundle': 'zip_bundle',
        'project_bundle': 'zip_bundle',
        'single': 'single_file',
        'single_file': 'single_file',
        'file': 'single_file',
        'none': 'none',
    }
    normalized = aliases.get(raw, raw)
    if normalized in {'zip_bundle', 'single_file', 'none'}:
        return normalized
    inferred = _infer_file_delivery_mode_from_text(user_text, info=info)
    if inferred != 'none':
        return inferred
    return default


def _resolve_zip_bundle_filename(messages: list | None = None, *, saved_files: list[dict] | None = None, info: dict | None = None) -> str:
    info = dict(info or _file_delivery_soft_context(messages or []))
    filename = str(info.get('filename') or '').strip()
    if filename:
        if filename.lower().endswith('.zip'):
            return _safe_filename(filename)
        stem = os.path.splitext(filename)[0].strip()
        if stem:
            return _safe_filename(f'{stem}.zip')
    for item in saved_files or []:
        if not isinstance(item, dict):
            continue
        saved_name = str(item.get('filename') or '').strip()
        if not saved_name:
            continue
        stem = os.path.splitext(saved_name)[0].strip()
        if stem:
            return _safe_filename(f'{stem}.zip')
    suggested = str(info.get('suggested_filename') or '').strip()
    if suggested:
        stem = os.path.splitext(suggested)[0].strip()
        if stem:
            return _safe_filename(f'{stem}.zip')
    user_text = str(info.get('user_text') or '')
    auto_name = _suggest_filename_for_extension(user_text, 'zip')
    return _safe_filename(auto_name or 'bundle.zip')


def _file_delivery_soft_context(messages: list) -> dict:
    user_text = _latest_user_message_text(messages)
    filename = _extract_requested_filename_from_text(user_text)
    ext = ""
    if filename and '.' in filename:
        ext = filename.rsplit('.', 1)[-1].lower()
    if not ext:
        ext = _detect_requested_extension_from_text(user_text)
    format_label = _detect_requested_format_label(user_text)
    t = str(user_text or "").lower()
    cue_checks = [
        ("提到“生成/写一个文件”", ["生成文件", "写一个文件", "写个文件", "做成文件", "给我个文件", "发我文件"]),
        ("提到“保存/导出/下载/附件”", ["保存为", "保存成", "导出", "下载", "附件", "打包"]),
        ("明确给了文件名", [filename] if filename else []),
        ("明确给了扩展名", [f'.{ext}'] if ext else []),
        ("提到了文件格式", [format_label] if format_label else []),
    ]
    cues: list[str] = []
    wants_file = False
    for label, keys in cue_checks:
        keys = [str(k or "").strip() for k in (keys or []) if str(k or "").strip()]
        if not keys:
            continue
        hit = False
        for k in keys:
            lk = k.lower()
            if k in user_text or lk in t:
                hit = True
                break
        if hit:
            cues.append(label)
            wants_file = True
    suggested_filename = ""
    if ext:
        suggested_filename = _suggest_filename_for_extension(user_text, ext)
        if not wants_file:
            wants_file = True
    if filename:
        wants_file = True
    info = {
        "user_text": user_text,
        "wants_file": wants_file,
        "filename": filename,
        "ext": ext,
        "format_label": format_label,
        "suggested_filename": suggested_filename,
        "cues": cues,
    }
    info["delivery_mode_hint"] = _infer_file_delivery_mode_from_text(user_text, info=info)
    return info


def _build_file_delivery_soft_prompt(messages: list) -> str:
    info = _file_delivery_soft_context(messages)
    if not info.get("wants_file"):
        return ""
    runtime_plan_prompt = ''
    try:
        prompt_builder = globals().get('skill_runtime_prompt')
        if callable(prompt_builder):
            runtime_plan_prompt = str(prompt_builder('chat_completions', ['sandbox'], compact=True) or '').strip()
    except Exception:
        runtime_plan_prompt = ''
    cues = info.get("cues") or []
    cue_text = "、".join(cues[:5]) if cues else "用户表达里带有明显的文件交付倾向"
    filename = str(info.get("filename") or "").strip()
    ext = str(info.get("ext") or "").strip()
    format_label = str(info.get("format_label") or "").strip()
    suggested_filename = str(info.get("suggested_filename") or "").strip()
    delivery_mode_hint = str(info.get('delivery_mode_hint') or 'single_file').strip()
    pieces = [
        "补充软提示（不是硬规则，只供你判断用户意图）：本轮用户很可能想拿到真实可下载文件，而不只是正文里的示例内容。",
        f"检测到的交付信号：{cue_text}。",
        runtime_plan_prompt or "如果你判断交付文件更符合用户意图，应通过 sandbox 工具链写入、验证并发布真实下载文件，而不是只在正文里贴完整代码/文稿/表格。",
    ]
    if filename:
        pieces.append(f"用户已经给了具体文件名：{filename}。写入 /mnt/data 和发布时必须严格使用这个名字。")
    elif ext:
        pieces.append(f"用户已经明确要求文件扩展名 .{ext}。写入 /mnt/data 和发布时必须保留这个扩展名。")
    if format_label:
        pieces.append(f"用户偏好的文件类型：{format_label}。")
    if delivery_mode_hint == 'zip_bundle':
        pieces.append("如果用户要的是 ZIP/压缩包/源码包/项目包，不要直接生成 zip 二进制或伪 base64；优先把压缩包内的真实源码/说明/资源文件分别生成出来，后端会再统一打包成 zip。")
    if (not filename) and suggested_filename:
        pieces.append(f"如果用户只给了扩展名但没起文件名，可以自行补一个自然文件名，例如：{suggested_filename}。")
    pieces.append("只有当你判断用户其实只是想口头解释、文件交付会偏离意图时，才保持普通聊天回答。")
    return "\n".join(pieces)


def _generated_file_registry_id(item: dict | None = None) -> str:
    row = item if isinstance(item, dict) else {}
    reg = row.get('file_registry') if isinstance(row.get('file_registry'), dict) else {}
    for key in ('registry_file_id', 'file_registry_id', 'library_file_id'):
        fid = str(row.get(key) or '').strip()
        if fid:
            return fid[:220]
    fid = str(reg.get('file_id') or '').strip()
    if fid:
        return fid[:220]
    # Only use the loose top-level file_id after the artifact has been marked as
    # a generated app artifact. This avoids confusing upstream provider IDs with
    # WebAI's own registry IDs.
    fid = str(row.get('file_id') or '').strip()
    source_type = str(row.get('source_type') or row.get('sourceType') or row.get('source') or '').strip().lower()
    if fid and (row.get('generated_by_assistant') is True or source_type == 'generated') and not fid.lower().startswith(('file-', 'container_', 'ctnr_')):
        return fid[:220]
    return ''


def _generated_file_id_download_url(file_id: str = '') -> str:
    fid = str(file_id or '').strip()
    if not fid:
        return ''
    try:
        return '/api3/generated-download-id/' + urllib.parse.quote(fid, safe='')
    except Exception:
        return '/api3/generated-download-id/' + fid


def _generated_file_id_view_url(file_id: str = '') -> str:
    fid = str(file_id or '').strip()
    if not fid:
        return ''
    try:
        return '/api3/generated-files-id/' + urllib.parse.quote(fid, safe='')
    except Exception:
        return '/api3/generated-files-id/' + fid


def _generated_file_sandbox_url(item: dict | None = None) -> str:
    row = item if isinstance(item, dict) else {}
    rel = str(row.get('relative_path') or row.get('display_filename') or row.get('filename') or '').strip().replace('\\', '/')
    rel = rel.lstrip('/')
    if not rel or '..' in rel.split('/'):
        return ''
    return 'sandbox:/mnt/data/' + rel


def _generated_file_path_annotation(item: dict | None = None) -> dict:
    row = item if isinstance(item, dict) else {}
    fid = _generated_file_registry_id(row)
    sandbox_url = str(row.get('sandbox_url') or row.get('sandbox_path') or _generated_file_sandbox_url(row)).strip()
    if not fid or not sandbox_url:
        return {}
    filename = str(row.get('filename') or row.get('display_filename') or '').strip()
    return {
        'type': 'file_path',
        'text': sandbox_url,
        'file_path': {
            'file_id': fid,
            'filename': filename,
            'download_url': _generated_file_id_download_url(fid),
        },
    }


def _generated_file_attach_official_path_metadata(item: dict | None = None) -> dict:
    row = item if isinstance(item, dict) else {}
    if not row:
        return {}
    fid = _generated_file_registry_id(row)
    sandbox_url = str(row.get('sandbox_url') or row.get('sandbox_path') or _generated_file_sandbox_url(row)).strip()
    if fid:
        by_id = _generated_file_id_download_url(fid)
        view_by_id = _generated_file_id_view_url(fid)
        if by_id:
            legacy = str(row.get('download_url') or row.get('url') or '').strip()
            if legacy and legacy != by_id:
                row.setdefault('legacy_download_url', legacy)
            row['download_url'] = by_id
            row['url'] = by_id
            row['download_url_by_id'] = by_id
        if view_by_id:
            legacy_view = str(row.get('view_url') or '').strip()
            if legacy_view and legacy_view != view_by_id:
                row.setdefault('legacy_view_url', legacy_view)
            row['view_url_by_id'] = view_by_id
        row['file_id'] = fid
        row['registry_file_id'] = fid
        row.setdefault('id', fid)
    if sandbox_url:
        row['sandbox_url'] = sandbox_url
        row['sandbox_path'] = sandbox_url
    ann = _generated_file_path_annotation(row)
    if ann:
        row['file_path_annotation'] = ann
        anns = row.get('annotations') if isinstance(row.get('annotations'), list) else []
        ann_key = str(ann.get('text') or '') + '|' + str((ann.get('file_path') or {}).get('file_id') or '')
        existing = {str(x.get('text') or '') + '|' + str((x.get('file_path') or {}).get('file_id') or '') for x in anns if isinstance(x, dict)}
        if ann_key not in existing:
            row['annotations'] = [*anns, ann]
    return row


def _generated_files_download_url(item: dict | None = None) -> str:
    row = item if isinstance(item, dict) else {}
    fid = _generated_file_registry_id(row)
    if fid:
        by_id = _generated_file_id_download_url(fid)
        if by_id:
            return by_id
    url = str(row.get('download_url') or row.get('url') or row.get('view_url') or '').strip()
    if not url:
        filename = str(row.get('filename') or '').strip()
        if filename:
            scope = str(row.get('scope') or '').strip() or None
            try:
                scope_candidates = []
                for raw_scope in (scope, _request_upload_scope() if callable(globals().get('_request_upload_scope')) else '', 'local', 'public'):
                    normalized_scope = _normalize_upload_scope(raw_scope) if callable(globals().get('_normalize_upload_scope')) else str(raw_scope or '').strip().lower()
                    if normalized_scope and normalized_scope not in scope_candidates:
                        scope_candidates.append(normalized_scope)
                for candidate_scope in scope_candidates:
                    base_dir = _generated_dir_for_scope(candidate_scope, ensure=False)
                    if os.path.exists(os.path.join(base_dir, os.path.basename(filename))):
                        _view_url, url = _build_generated_file_urls(filename, candidate_scope)
                        break
            except Exception:
                url = ''
    if url.startswith('/api3/generated-files/'):
        return '/api3/generated-download/' + url[len('/api3/generated-files/'):].lstrip('/')
    if url.startswith('/api3/uploads/'):
        return '/api3/download/' + url[len('/api3/uploads/'):].lstrip('/')
    return url


def _generated_files_markdown_links(files: list[dict] | None = None, *, limit: int = 8) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    max_rows = max(1, min(int(limit or 8), 12))
    for item in (files or []):
        if not isinstance(item, dict):
            continue
        filename = str(item.get('filename') or '').strip()
        href = _generated_files_download_url(item)
        if not filename or not href:
            continue
        key = (filename + '|' + href).lower()
        if key in seen:
            continue
        seen.add(key)
        safe_name = filename.replace('[', '［').replace(']', '］')
        safe_href = href.replace(')', '%29')
        lines.append(f'- [{safe_name}]({safe_href})')
        if len(lines) >= max_rows:
            break
    return '\n'.join(lines).strip()


def _file_delivery_attach_generated_file_links(answer: str = '', files: list[dict] | None = None, *, default_text: str = '已生成文件。') -> str:
    # 保持助手最终正文由主模型自然生成；这里不再替助手补固定文件话术或链接。
    return str(answer or '').strip()


def _generated_files_reference_prompt(files: list[dict]) -> str:
    items = [item for item in (files or []) if isinstance(item, dict)]
    if not items:
        return ''
    links_text = _generated_files_markdown_links(items)
    if links_text:
        return '文件：\n' + links_text
    names = [str(item.get('filename') or '').strip() for item in items if str(item.get('filename') or '').strip()]
    names_text = '、'.join(names[:8]) if names else '已生成'
    return '文件：' + names_text


def _file_delivery_minimal_file_refs(files: list[dict] | None = None, *, limit: int = 8) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for item in (files or []):
        if not isinstance(item, dict):
            continue
        filename = str(item.get('filename') or '').strip()
        href = _generated_files_download_url(item)
        if not filename or not href:
            continue
        key = (filename + '|' + href).lower()
        if key in seen:
            continue
        seen.add(key)
        source_role = str(item.get('source_role') or item.get('sourceRole') or '').strip().lower()
        if source_role in {'assistant', 'generated', 'latest_generated'}:
            source_role = 'assistant_generated'
        if not source_role:
            source_role = 'edited_output' if (isinstance(item.get('edit_audit'), dict) or isinstance(item.get('edit_details'), dict) or isinstance(item.get('edited_from'), dict)) else 'assistant_generated'
        file_id = _generated_file_registry_id(item) if callable(globals().get('_generated_file_registry_id')) else str(item.get('registry_file_id') or item.get('file_id') or '').strip()
        sandbox_url = _generated_file_sandbox_url(item) if callable(globals().get('_generated_file_sandbox_url')) else ''
        row = {
            'artifact_id': str(item.get('artifact_id') or item.get('id') or '').strip(),
            'file_id': file_id,
            'registry_file_id': file_id,
            'filename': filename,
            'download_url': href,
            'view_url': str(item.get('view_url_by_id') or item.get('view_url') or '').strip(),
            'sandbox_url': sandbox_url,
            'sandbox_path': sandbox_url,
            'source_type': str(item.get('source_type') or 'generated').strip() or 'generated',
            'source_role': source_role,
            'scope': str(item.get('scope') or '').strip(),
            'relative_path': str(item.get('relative_path') or '').strip(),
            'display_filename': str(item.get('display_filename') or '').strip(),
        }
        ann = _generated_file_path_annotation(item) if callable(globals().get('_generated_file_path_annotation')) else {}
        if ann:
            row['annotations'] = [ann]
            row['file_path_annotation'] = ann
        if item.get('bundle_members'):
            row['bundle_members'] = [str(x or '')[:260] for x in (item.get('bundle_members') or []) if str(x or '').strip()][:30]
            row['bundle_count'] = int(item.get('bundle_count') or len(item.get('bundle_members') or []))
        edited_from = item.get('edited_from') if isinstance(item.get('edited_from'), dict) else {}
        if edited_from:
            row['basis_filename'] = str(edited_from.get('basis_filename') or edited_from.get('filename') or '').strip()
            row['lineage_key'] = str(edited_from.get('lineage_key') or '').strip()
            row['task_job_id'] = str(edited_from.get('task_job_id') or '').strip()
        audit = item.get('edit_audit') if isinstance(item.get('edit_audit'), dict) else {}
        if audit:
            row['audit_id'] = str(audit.get('audit_id') or '').strip()
            row['basis_filename'] = row.get('basis_filename') or str(audit.get('basis_filename') or audit.get('target_filename') or '').strip()
            row['lineage_key'] = row.get('lineage_key') or str(audit.get('lineage_key') or '').strip()
            row['task_job_id'] = row.get('task_job_id') or str(audit.get('task_job_id') or '').strip()
        rows.append({k: v for k, v in row.items() if v not in ('', [], None)})
        if len(rows) >= max(1, min(int(limit or 8), 12)):
            break
    return rows


def _file_delivery_minimal_audit_refs(audits: list[dict] | None = None, *, limit: int = 4) -> list[dict]:
    rows: list[dict] = []
    for audit in (audits or []):
        if not isinstance(audit, dict):
            continue
        row = {
            'target_filename': str(audit.get('target_filename') or '').strip(),
            'output_filename': str(audit.get('output_filename') or '').strip(),
            'changed': bool(audit.get('changed')),
        }
        summary = [str(x or '').strip() for x in (audit.get('diff_summary') or []) if str(x or '').strip()]
        if summary:
            row['diff_summary'] = summary[:6]
        rows.append({k: v for k, v in row.items() if v not in ('', [], None)})
        if len(rows) >= max(1, min(int(limit or 4), 8)):
            break
    return rows


def _file_delivery_compact_tool_result_for_model(name: str, result: dict | None = None) -> dict:
    row = dict(result or {}) if isinstance(result, dict) else {}
    tool_name = str(name or '').strip()
    ok = bool(row.get('ok'))
    out: dict = {'ok': ok}
    files = _file_delivery_minimal_file_refs(row.get('files') if isinstance(row.get('files'), list) else [])
    if files:
        out['files'] = files
        out['filenames'] = [x.get('filename') for x in files if x.get('filename')]
        out['count'] = len(files)
    needs_review = bool(row.get('needs_review'))
    if needs_review:
        out['needs_review'] = True
    error = str(row.get('error') or '').strip()
    if error:
        out['error'] = error[:240]
    if bool(row.get('reused_existing')):
        out['reused_existing'] = True
        action = str(row.get('action') or '').strip()
        if action:
            out['action'] = action[:120]
    if (not ok) or needs_review or bool(row.get('reused_existing')):
        message = str(row.get('message') or row.get('note') or row.get('reference_hint') or '').strip()
        if message:
            out['message'] = message[:420]
        fix_instruction = str(row.get('fix_instruction') or '').strip()
        if fix_instruction:
            out['fix_instruction'] = fix_instruction[:600]
    return out


def _file_delivery_final_artifact_context(files: list[dict] | None = None, audits: list[dict] | None = None) -> str:
    refs = _file_delivery_minimal_file_refs(files or [])
    if not refs:
        return ''
    payload = {'generated_files': refs}
    return (
        '【本轮真实文件 artifact】\n'
        + json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        + '\n回答涉及文件或下载时，只使用这里的真实 download_url 或 sandbox_url；不要根据文件名自行拼 /api3/generated-download，也不要手动 URL 编码中文文件名。'
    )


_ARTIFACT_WINDOWS_TEXT_UTF8_SIG_EXTS = {
    ".txt", ".md",
}

_ARTIFACT_WINDOWS_GB18030_EXTS = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".hxx",
    ".bat", ".cmd", ".rc",
    ".log", ".ini", ".cfg", ".conf",
}

_ARTIFACT_PROGRAM_SOURCE_UTF8_EXTS = {
    ".py", ".pyw",
    ".java", ".kt", ".kts", ".scala", ".groovy",
    ".cs", ".vb",
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".go", ".rs", ".php", ".rb", ".swift",
    ".ps1", ".sh",
    ".html", ".htm", ".css", ".scss", ".less", ".vue", ".svelte",
    ".json", ".xml", ".yaml", ".yml", ".toml", ".properties",
}


def _artifact_contains_cjk_text(text: str) -> bool:
    try:
        return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", str(text or "")))
    except Exception:
        return False


def _normalize_artifact_text_encoding(filename: str, mime: str, requested_encoding: str, data) -> str:
    ext = os.path.splitext(str(filename or "").strip())[1].lower()
    mime_l = str(mime or "").strip().lower()
    enc = str(requested_encoding or "").strip().lower()
    alias = {
        "": "",
        "auto": "",
        "utf8": "utf-8",
        "utf_8": "utf-8",
        "utf-8": "utf-8",
        "utf8-sig": "utf-8-sig",
        "utf_8_sig": "utf-8-sig",
        "utf-8-sig": "utf-8-sig",
        "utf-8-bom": "utf-8-sig",
        "utf8bom": "utf-8-sig",
        "gb18030": "gb18030",
        "gbk": "gbk",
        "base64": "base64",
    }
    enc = alias.get(enc, enc)
    if enc == "base64":
        return enc

    txt = "" if data is None else str(data)
    if ext == ".csv" or mime_l in ("text/csv", "application/csv"):
        if enc in ("", "utf-8", "utf-8-sig"):
            return "utf-8-sig"
        return enc or "utf-8-sig"

    if _artifact_contains_cjk_text(txt):
        if ext in _ARTIFACT_WINDOWS_TEXT_UTF8_SIG_EXTS and enc in ("", "utf-8", "utf-8-sig"):
            return "utf-8-sig"
        if ext in _ARTIFACT_WINDOWS_GB18030_EXTS and enc in ("", "utf-8", "utf-8-sig"):
            return "gb18030"

    if ext in _ARTIFACT_PROGRAM_SOURCE_UTF8_EXTS:
        return enc or "utf-8"

    return enc or "utf-8"



def _artifact_text_has_meaningful_content(data) -> bool:
    try:
        txt = "" if data is None else str(data)
    except Exception:
        return False
    return bool(txt.replace("\ufeff", "").strip())


def _artifact_try_decode_base64_bytes(data) -> bytes | None:
    if not isinstance(data, str):
        return None
    raw_text = str(data or '').strip()
    if not raw_text:
        return None
    try:
        raw = base64.b64decode(raw_text, validate=False)
    except Exception:
        return None
    return raw if isinstance(raw, (bytes, bytearray)) and len(raw) > 0 else None


def _artifact_zip_has_meaningful_entries(raw: bytes) -> bool:
    if not raw:
        return False
    try:
        import zipfile
        with zipfile.ZipFile(io.BytesIO(raw), 'r') as zf:
            infos = list(zf.infolist() or [])
            if not infos:
                return False
            return any((not info.is_dir()) and int(getattr(info, 'file_size', 0) or 0) > 0 for info in infos)
    except Exception:
        return False




def _artifact_encode_text_payload(payload_text: str, preferred_encoding: str) -> tuple[bytes, str]:
    enc_try = str(preferred_encoding or "utf-8").strip().lower() or "utf-8"
    fallbacks = [enc_try]
    if enc_try.startswith("gb"):
        fallbacks.extend(["utf-8-sig", "utf-8"])
    elif enc_try == "utf-8-sig":
        fallbacks.append("utf-8")
    else:
        fallbacks.append("utf-8-sig")
    tried = set()
    last_err = None
    for enc_name in fallbacks:
        enc_name = str(enc_name or "").strip().lower()
        if not enc_name or enc_name in tried:
            continue
        tried.add(enc_name)
        try:
            return payload_text.encode(enc_name), enc_name
        except UnicodeEncodeError as e:
            last_err = e
            continue
    if last_err is not None:
        raise last_err
    return payload_text.encode("utf-8", errors="replace"), "utf-8"


def _save_artifacts_as_zip_bundle(artifacts: list, zip_filename: str | None = None) -> list[dict]:
    upload_scope = _image_generation_current_output_scope()
    upload_dir = _generated_dir_for_scope(upload_scope)
    pseudo_files: list[dict] = []
    members: list[tuple[str, bytes]] = []
    seen_arcnames: set[str] = set()

    for a in artifacts or []:
        if not isinstance(a, dict):
            continue
        original_filename = str(a.get("filename") or "").strip()
        relative_path = _safe_artifact_relative_path(original_filename)
        final_fn = _flat_filename_from_relative_path(relative_path, original_filename)
        ext = os.path.splitext(final_fn)[1].lower()
        if not final_fn or ext not in ALLOWED_EXT:
            continue

        mime = (a.get("mime") or "").strip()
        data = a.get("data")
        encoding = _normalize_artifact_text_encoding(final_fn, mime, a.get("encoding"), data)

        try:
            if encoding == "base64":
                raw = _artifact_try_decode_base64_bytes(data)
                if raw is None:
                    app_logger.warning('[artifact_zip_bundle] skip_empty_or_invalid_binary filename=%s', final_fn)
                    continue
                if ext == '.zip' and not _artifact_zip_has_meaningful_entries(raw):
                    app_logger.warning('[artifact_zip_bundle] skip_empty_zip filename=%s', final_fn)
                    continue
                if final_fn.lower().endswith(".csv") or (mime or "").lower() in ("text/csv", "application/csv"):
                    raw = _maybe_add_csv_bom(final_fn, mime, raw)
            else:
                if not _artifact_text_has_meaningful_content(data):
                    app_logger.warning('[artifact_zip_bundle] skip_empty_text filename=%s', final_fn)
                    continue
                if ext == '.zip':
                    app_logger.warning('[artifact_zip_bundle] skip_nonbinary_zip filename=%s', final_fn)
                    continue
                txt = "" if data is None else str(data)
                if final_fn.lower().endswith(".csv") or (mime or "").lower() in ("text/csv", "application/csv"):
                    txt = _maybe_add_csv_bom(final_fn, mime, txt)
                raw, _used_encoding = _artifact_encode_text_payload(txt, encoding or "utf-8")
        except Exception:
            app_logger.exception('[artifact_zip_bundle] encode_failed filename=%s', final_fn)
            continue

        arcname = _dedupe_zip_arcname(relative_path or final_fn, seen_arcnames)
        members.append((arcname, bytes(raw)))
        pseudo_files.append({
            "filename": final_fn,
            "original_filename": original_filename,
            "relative_path": relative_path or final_fn,
            "logical_path": relative_path or final_fn,
        })

    if len(members) <= 1:
        return []

    final_zip_name = _safe_filename(str(zip_filename or '').strip() or _generated_files_bundle_filename(None, saved_files=pseudo_files))
    if not final_zip_name.lower().endswith('.zip'):
        final_zip_name = _safe_filename(f'{os.path.splitext(final_zip_name)[0]}.zip')
    final_zip_name = _dedupe_filename(upload_dir, final_zip_name)
    out_path = os.path.join(upload_dir, final_zip_name)
    tmp_path = out_path + f'.tmp-{uuid.uuid4().hex}'

    try:
        import zipfile
        with zipfile.ZipFile(tmp_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for arcname, raw in members:
                zf.writestr(arcname, raw)
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) <= 0:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return []
        os.replace(tmp_path, out_path)
    except Exception:
        app_logger.exception('[artifact_zip_bundle] failed')
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return []

    _prune_generated_dir(scope=upload_scope, keep_paths=[out_path])
    mirror_queued = _object_storage_mirror_file_async('generated', upload_scope, final_zip_name, out_path, content_type='application/zip')
    view_url, download_url = _build_generated_file_urls(final_zip_name, upload_scope)
    item = {
        'artifact_id': 'artifact_' + uuid.uuid4().hex,
        'filename': final_zip_name,
        'original_filename': final_zip_name,
        'relative_path': final_zip_name,
        'display_filename': final_zip_name,
        'mime': 'application/zip',
        'size': os.path.getsize(out_path),
        'download_url': download_url,
        'view_url': view_url,
        'object_url': _object_storage_public_url('generated', upload_scope, final_zip_name),
        'storage_backend': 'object+local' if mirror_queued else 'local',
        'scope': upload_scope,
        'source_type': 'generated',
        'source_role': 'assistant_generated',
        'generated_by_assistant': True,
        'packaged_zip': True,
        'bundle_members': [arcname for arcname, _raw in members],
        'bundle_count': len(members),
    }
    sandbox_sources = _generated_artifact_sandbox_sources_from_rows(artifacts or [])
    if sandbox_sources:
        item['sandbox_source_files'] = sandbox_sources
        item['sandbox_cleanup_policy'] = 'delete_with_file_library'
        item['sandbox_published'] = True
    _generated_artifact_register_saved_file(item, out_path, source='generated')
    return [item]

def _package_saved_files_as_zip(saved_files: list[dict], zip_filename: str) -> dict | None:
    members = []
    seen_files = set()
    seen_arcnames: set[str] = set()
    upload_scope = _image_generation_current_output_scope()
    upload_dir = _generated_dir_for_scope(upload_scope)
    for item in saved_files or []:
        if not isinstance(item, dict):
            continue
        filename = _safe_filename(str(item.get('filename') or '').strip())
        if not filename or filename.lower().endswith('.zip'):
            continue
        file_key = filename.lower()
        if file_key in seen_files:
            continue
        seen_files.add(file_key)
        base_dir = _resolve_generated_file_dir(filename, scope=upload_scope)
        if not base_dir:
            continue
        fp = os.path.join(base_dir, filename)
        if not os.path.isfile(fp):
            continue
        try:
            if os.path.getsize(fp) <= 0:
                continue
        except Exception:
            continue
        arcname = _dedupe_zip_arcname(_zip_arcname_from_saved_item(item) or filename, seen_arcnames)
        members.append((fp, arcname))

    if not members:
        return None

    final_zip_name = _safe_filename(str(zip_filename or '').strip() or 'bundle.zip')
    if not final_zip_name.lower().endswith('.zip'):
        final_zip_name = _safe_filename(f'{os.path.splitext(final_zip_name)[0]}.zip')
    final_zip_name = _dedupe_filename(upload_dir, final_zip_name)
    out_path = os.path.join(upload_dir, final_zip_name)
    tmp_path = out_path + f'.tmp-{uuid.uuid4().hex}'

    try:
        import zipfile
        with zipfile.ZipFile(tmp_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for fp, arcname in members:
                zf.write(fp, arcname=arcname)
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) <= 0:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return None
        os.replace(tmp_path, out_path)
    except Exception:
        app_logger.exception('[artifact_zip_package] failed')
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return None

    _prune_generated_dir(scope=upload_scope, keep_paths=[out_path])
    mirror_queued = _object_storage_mirror_file_async('generated', upload_scope, final_zip_name, out_path, content_type='application/zip')
    view_url, download_url = _build_generated_file_urls(final_zip_name, upload_scope)
    item = {
        'filename': final_zip_name,
        'mime': 'application/zip',
        'size': os.path.getsize(out_path),
        'download_url': download_url,
        'view_url': view_url,
        'object_url': _object_storage_public_url('generated', upload_scope, final_zip_name),
        'storage_backend': 'object+local' if mirror_queued else 'local',
        'scope': upload_scope,
        'source_type': 'generated',
        'generated_by_assistant': True,
        'bundle_members': [name for _fp, name in members],
        'bundle_count': len(members),
    }
    edit_audits: list[dict] = []
    seen_audits: set[str] = set()
    for row in saved_files or []:
        if not isinstance(row, dict):
            continue
        candidates = []
        if isinstance(row.get('edit_audit'), dict):
            candidates.append(row.get('edit_audit'))
        if isinstance(row.get('file_edit_audit'), dict):
            candidates.append(row.get('file_edit_audit'))
        if isinstance(row.get('file_edit_audits'), list):
            candidates.extend([x for x in row.get('file_edit_audits') if isinstance(x, dict)])
        for audit in candidates:
            aid = str((audit or {}).get('audit_id') or '').strip() or (str((audit or {}).get('output_filename') or '') + '|' + str((audit or {}).get('new_sha256') or ''))
            if aid and aid not in seen_audits:
                edit_audits.append(dict(audit or {}))
                seen_audits.add(aid)
    if edit_audits:
        item['file_edit_audits'] = edit_audits[:200]
        item['source_role'] = 'edited_output'
        if len(edit_audits) == 1:
            item['edit_audit'] = dict(edit_audits[0])
    sandbox_sources = _generated_artifact_sandbox_sources_from_rows(saved_files or [])
    if sandbox_sources:
        item['sandbox_source_files'] = sandbox_sources
        item['sandbox_cleanup_policy'] = 'delete_with_file_library'
        item['sandbox_published'] = True
    sandbox_sources = _generated_artifact_sandbox_sources_from_rows(saved_files or [])
    if sandbox_sources:
        item['sandbox_source_files'] = sandbox_sources
        item['sandbox_published'] = True
    _generated_artifact_register_saved_file(item, out_path, source='generated')
    return item


def _save_artifacts_to_uploads(artifacts: list) -> list[dict]:
    """Save model-produced artifacts to the current side's generated directory and return metadata for UI.

    - Avoid overwriting by auto -v2/-v3... via _dedupe_filename
    - Add UTF-8 BOM for CSV so Windows Excel opens Chinese correctly
    - Prefer gb18030 for some Windows-prone Chinese code/text artifacts to reduce mojibake
    """
    if _should_bundle_generated_files(None, artifacts, ''):
        zip_name = _generated_files_bundle_filename(None, saved_files=[
            {
                'filename': _flat_filename_from_relative_path(_safe_artifact_relative_path(str(a.get('filename') or '').strip()), str(a.get('filename') or '').strip()),
                'relative_path': _safe_artifact_relative_path(str(a.get('filename') or '').strip()),
            }
            for a in (artifacts or []) if isinstance(a, dict)
        ])
        bundled = _save_artifacts_as_zip_bundle(artifacts, zip_name)
        if bundled:
            return bundled

    saved: list[dict] = []

    def _maybe_add_csv_bom(filename: str, mime: str, payload):
        try:
            fn = (filename or "").lower()
            mm = (mime or "").lower()
            is_csv = fn.endswith(".csv") or mm in ("text/csv", "application/csv")
            if not is_csv:
                return payload
            if isinstance(payload, str):
                return payload if payload.startswith("\ufeff") else ("\ufeff" + payload)
            if isinstance(payload, (bytes, bytearray)):
                b = bytes(payload)
                return b if b.startswith(b"\xef\xbb\xbf") else (b"\xef\xbb\xbf" + b)
            return payload
        except Exception:
            return payload

    for a in artifacts or []:
        if not isinstance(a, dict):
            continue

        upload_scope = _image_generation_current_output_scope()
        upload_dir = _generated_dir_for_scope(upload_scope)
        original_filename = str(a.get("filename") or "").strip()
        relative_path = _safe_artifact_relative_path(original_filename)
        final_fn = _flat_filename_from_relative_path(relative_path, original_filename)
        final_fn = _dedupe_filename(upload_dir, final_fn)
        ext = os.path.splitext(final_fn)[1].lower()
        if ext not in ALLOWED_EXT:
            continue

        mime = (a.get("mime") or "").strip()
        data = a.get("data")
        encoding = _normalize_artifact_text_encoding(final_fn, mime, a.get("encoding"), data)
        used_text_encoding = None if encoding == "base64" else encoding

        if encoding == "base64":
            raw_preview = _artifact_try_decode_base64_bytes(data)
            if raw_preview is None:
                app_logger.warning('[artifact_save] skip_empty_or_invalid_binary filename=%s', final_fn)
                continue
            if ext == '.zip' and not _artifact_zip_has_meaningful_entries(raw_preview):
                app_logger.warning('[artifact_save] skip_empty_zip filename=%s', final_fn)
                continue
        else:
            if not _artifact_text_has_meaningful_content(data):
                app_logger.warning('[artifact_save] skip_empty_text filename=%s', final_fn)
                continue
            if ext == '.zip':
                app_logger.warning('[artifact_save] skip_nonbinary_zip filename=%s', final_fn)
                continue

        out_path = os.path.join(upload_dir, final_fn)

        def _write_text_payload(payload_text: str, preferred_encoding: str) -> str:
            enc_try = str(preferred_encoding or "utf-8").strip().lower() or "utf-8"
            fallbacks = [enc_try]
            if enc_try.startswith("gb"):
                fallbacks.extend(["utf-8-sig", "utf-8"])
            elif enc_try == "utf-8-sig":
                fallbacks.append("utf-8")
            else:
                fallbacks.append("utf-8-sig")
            tried = set()
            last_err = None
            for enc_name in fallbacks:
                enc_name = str(enc_name or "").strip().lower()
                if not enc_name or enc_name in tried:
                    continue
                tried.add(enc_name)
                try:
                    with open(out_path, "w", encoding=enc_name, newline="") as f:
                        f.write(payload_text)
                    return enc_name
                except UnicodeEncodeError as e:
                    last_err = e
                    continue
            if last_err is not None:
                raise last_err
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                f.write(payload_text)
            return "utf-8"

        try:
            if encoding == "base64":
                raw = _artifact_try_decode_base64_bytes(data)
                if raw is None:
                    continue
                # BOM for csv in bytes form
                if final_fn.lower().endswith(".csv") or (mime or "").lower() in ("text/csv", "application/csv"):
                    raw = _maybe_add_csv_bom(final_fn, mime, raw)
                with open(out_path, "wb") as f:
                    f.write(raw)
                size = len(raw)

            else:
                txt = "" if data is None else str(data)
                # BOM for csv in text form
                if final_fn.lower().endswith(".csv") or (mime or "").lower() in ("text/csv", "application/csv"):
                    txt = _maybe_add_csv_bom(final_fn, mime, txt)

                if ext == ".pdf":
                    try:
                        from reportlab.lib.pagesizes import A4
                        from reportlab.pdfgen import canvas
                        from reportlab.lib.units import mm

                        c = canvas.Canvas(out_path, pagesize=A4)
                        width, height = A4
                        x = 15 * mm
                        y = height - 15 * mm
                        line_h = 5 * mm

                        for line in (txt.splitlines() or [""]):
                            while len(line) > 120:
                                c.drawString(x, y, line[:120])
                                line = line[120:]
                                y -= line_h
                                if y < 15 * mm:
                                    c.showPage()
                                    y = height - 15 * mm
                            c.drawString(x, y, line)
                            y -= line_h
                            if y < 15 * mm:
                                c.showPage()
                                y = height - 15 * mm

                        c.save()
                        size = os.path.getsize(out_path)
                    except Exception:
                        used_text_encoding = _write_text_payload(txt, used_text_encoding or "utf-8")
                        size = len(txt.encode(used_text_encoding, errors="replace"))
                else:
                    used_text_encoding = _write_text_payload(txt, used_text_encoding or "utf-8")
                    size = len(txt.encode(used_text_encoding, errors="replace"))

        except Exception:
            app_logger.exception('Exception occurred')
            continue

        preview_info = _maybe_build_generated_image_preview(out_path, final_fn, upload_scope, mime=mime or _guess_content_type_for_file(final_fn), size_bytes=size)
        keep_paths = [out_path]
        if str(preview_info.get('path') or '').strip():
            keep_paths.append(str(preview_info.get('path') or '').strip())
        _prune_generated_dir(scope=upload_scope, keep_paths=keep_paths)
        mirror_queued = _object_storage_mirror_file_async('generated', upload_scope, final_fn, out_path, content_type=mime or _guess_content_type_for_file(final_fn))

        view_url, download_url = _build_generated_file_urls(final_fn, upload_scope)
        item = {
            "artifact_id": 'artifact_' + uuid.uuid4().hex,
            "filename": final_fn,
            "original_filename": original_filename,
            "relative_path": relative_path or final_fn,
            "display_filename": os.path.basename(relative_path or final_fn),
            "mime": mime,
            "size": size,
            "download_url": download_url,
            "view_url": view_url,
            "object_url": _object_storage_public_url('generated', upload_scope, final_fn),
            "storage_backend": 'object+local' if mirror_queued else 'local',
            "scope": upload_scope,
            "source_type": "generated",
            "source_role": str(a.get('source_role') or a.get('sourceRole') or ('assistant' if ext in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.svg'} else 'assistant_generated')).strip(),
            "generated_by_assistant": True,
        }
        _generated_artifact_copy_lineage_metadata(item, a)
        if preview_info:
            item['preview_url'] = str(preview_info.get('view_url') or '').strip()
            item['preview_download_url'] = str(preview_info.get('download_url') or '').strip()
            item['preview_filename'] = str(preview_info.get('filename') or '').strip()
            item['preview_size'] = int(preview_info.get('size') or 0)
            item['preview_mime'] = str(preview_info.get('mime') or '').strip()
        if used_text_encoding:
            item["text_encoding"] = used_text_encoding
        _generated_artifact_register_saved_file(item, out_path, source='generated')
        saved.append(item)

    return saved
