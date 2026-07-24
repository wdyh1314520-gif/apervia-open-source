# file edit apply, diff, audit, and verifier helpers.

def _file_edit_decode_text_bytes(raw: bytes) -> str:
    encodings = ["utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "utf-16", "latin-1"]
    for enc in encodings:
        try:
            txt = raw.decode(enc)
            if txt is not None:
                return txt.replace("", "")
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore").replace("", "")


def _file_edit_read_archive_bundle_full(raw: bytes, *, max_entries: int = 240, max_each_chars: int = 240000, max_total_chars: int = 600000) -> str:
    """Read a zip for edit workflows without the small preview cap used by normal archive parsing."""
    import zipfile
    text_like_ext = {
        ".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".py", ".pyw", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp",
        ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".mts", ".cts", ".java", ".go", ".rs", ".php", ".rb", ".swift", ".kt", ".cs",
        ".sql", ".yaml", ".yml", ".xml", ".toml", ".ini", ".cfg", ".log", ".sh", ".bat", ".ps1",
        ".html", ".htm", ".css", ".scss", ".less", ".svg", ".vue", ".svelte", ".astro",
    }
    out: list[str] = []
    total_chars = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        infos.sort(key=lambda i: i.filename)
        picked = 0
        for info in infos:
            if picked >= max_entries or total_chars >= max_total_chars:
                break
            inner_name = _safe_artifact_relative_path(info.filename)
            if not inner_name:
                continue
            inner_ext = os.path.splitext(inner_name)[1].lower()
            if inner_ext not in text_like_ext:
                continue
            try:
                blob = zf.read(info)
                inner_text = read_text_file(blob)
            except Exception as e:
                inner_text = f"[解析失败：{type(e).__name__}: {e}]"
            if not inner_text:
                continue
            if len(inner_text) > max_each_chars:
                inner_text = inner_text[:max_each_chars].rstrip() + "\n[已截断：单文件内容过长，不能直接保存为完整替换结果]"
            remaining = max_total_chars - total_chars
            block = f"## {inner_name}\n{inner_text}"
            if len(block) > remaining:
                block = block[:max(0, remaining)].rstrip() + "\n[已截断：压缩包内容过长，不能直接保存为完整替换结果]"
            out.append(block)
            total_chars += len(block) + 2
            picked += 1
    return "\n\n".join(out).strip()


def _file_edit_read_full_text(record: dict | None = None) -> tuple[str, str]:
    rec = dict(record or {})
    path = str(rec.get('_path') or '').strip() or _history_file_resolve_path(rec)
    if not path or not os.path.isfile(path):
        ref = str(rec.get('full_text_ref') or '').strip()
        if ref and callable(globals().get('_file_text_store_read_text')):
            try:
                text = _file_text_store_read_text(ref, max_chars=None)
            except Exception:
                text = ''
            if text:
                return text, ''
        return '', 'source_path_not_found'
    try:
        st = os.stat(path)
        max_bytes = _file_edit_max_source_bytes()
        if int(st.st_size) > max_bytes:
            return '', f'source_too_large:{int(st.st_size)}>{max_bytes}'
        with open(path, 'rb') as f:
            raw = f.read()
        ext = os.path.splitext(os.path.basename(path))[1].lower()
        if ext == '.zip':
            text = _file_edit_read_archive_bundle_full(raw)
        elif _file_registry_is_code_like(os.path.basename(path), ext):
            text = _file_edit_decode_text_bytes(raw)
        else:
            text = _history_file_parse_raw(raw, os.path.basename(path))
        if text is None or text == '':
            return '', 'source_not_text_readable'
        return text, ''
    except Exception as e:
        return '', f'read_source_failed:{type(e).__name__}:{e}'


def _file_edit_validate_complete_text(filename: str, text: str) -> tuple[bool, str]:
    ext = os.path.splitext(str(filename or '').strip())[1].lower()
    try:
        if ext == '.py':
            compile(str(text or ''), filename or '<edited_file>', 'exec')
        elif ext in {'.json'}:
            json.loads(str(text or ''))
        elif ext in {'.jsonl'}:
            for ln, line in enumerate(str(text or '').splitlines(), start=1):
                if line.strip():
                    json.loads(line)
        return True, ''
    except Exception as e:
        return False, f'{type(e).__name__}: {e}'


def _file_edit_parse_archive_bundle_blocks(text: str) -> dict[str, str]:
    """Parse read_archive_bundle() text blocks: ## relative/path\ncontent.

    It is intentionally conservative: only safe relative paths with extensions are
    treated as archive members. This keeps ordinary markdown headings inside file
    content from becoming fake files.
    """
    raw = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    if not raw.strip():
        return {}
    marker_re = re.compile(r'(?m)^##\s+([^\n\r]+?)\s*$')
    matches = []
    for m in marker_re.finditer(raw):
        name = _safe_artifact_relative_path(str(m.group(1) or '').strip())
        if not name or name in {'.', '..'}:
            continue
        leaf = os.path.basename(name)
        if not leaf or '.' not in leaf:
            continue
        if os.path.splitext(leaf)[1].lower() not in ALLOWED_EXT:
            continue
        matches.append((m, name))
    if not matches:
        return {}
    out: dict[str, str] = {}
    for idx, (m, name) in enumerate(matches):
        start = m.end()
        end = matches[idx + 1][0].start() if idx + 1 < len(matches) else len(raw)
        body = raw[start:end]
        body = body.lstrip('\n').rstrip()
        out[name] = body
    return out


def _file_edit_zip_record_path(record: dict | None = None) -> str:
    rec = dict(record or {})
    path = str(rec.get('_path') or '').strip() or _history_file_resolve_path(rec)
    if path and os.path.isfile(path) and os.path.splitext(path)[1].lower() == '.zip':
        return path
    return ''


def _file_edit_zip_changed_members(source_text: str, new_text: str) -> tuple[dict[str, str], str]:
    before = _file_edit_parse_archive_bundle_blocks(source_text)
    after = _file_edit_parse_archive_bundle_blocks(new_text)
    if not before:
        return {}, 'zip_source_bundle_not_parseable'
    if not after:
        return {}, 'zip_edited_bundle_not_parseable'
    changed: dict[str, str] = {}
    for name, body in after.items():
        if before.get(name) != body:
            changed[name] = body
    if not changed:
        return {}, 'zip_edit_no_changed_member'
    return changed, ''


def _file_edit_encode_member_text(filename: str, text: str) -> bytes:
    encoder = globals().get('_artifact_encode_text_payload')
    enc = 'utf-8'
    try:
        normalizer = globals().get('_normalize_artifact_text_encoding')
        if callable(normalizer):
            enc = str(normalizer(filename, _guess_content_type_for_file(filename), 'utf-8', text) or 'utf-8')
    except Exception:
        enc = 'utf-8'
    if callable(encoder):
        try:
            raw, _used = encoder(str(text or ''), enc)
            return bytes(raw)
        except Exception:
            pass
    return str(text or '').encode('utf-8', errors='replace')


def _file_edit_save_zip_output_from_bundle(record: dict, source_text: str, new_text: str, output_filename: str, messages: list | None = None) -> tuple[list[dict], str, list[str]]:
    zip_path = _file_edit_zip_record_path(record)
    if not zip_path:
        return [], 'zip_source_path_not_found', []
    changed, changed_err = _file_edit_zip_changed_members(source_text, new_text)
    if changed_err:
        return [], changed_err, []
    final_name = _safe_filename(os.path.basename(str(output_filename or '').strip()) or 'project-v2.zip')
    if not final_name.lower().endswith('.zip'):
        final_name = _safe_filename(f'{os.path.splitext(final_name)[0]}.zip')
    before_blocks = _file_edit_parse_archive_bundle_blocks(source_text)
    try:
        import zipfile
        import io
        import base64
        out = io.BytesIO()
        written: set[str] = set()
        with zipfile.ZipFile(zip_path, 'r') as zin, zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                if info.is_dir():
                    zout.writestr(info, b'')
                    continue
                arc = _safe_artifact_relative_path(info.filename)
                if not arc:
                    continue
                original_raw = zin.read(info.filename)
                if arc in changed:
                    try:
                        actual_original_text = read_text_file(original_raw)
                    except Exception:
                        actual_original_text = ''
                    source_block_text = before_blocks.get(arc, '')
                    if actual_original_text and source_block_text != actual_original_text:
                        return [], f'zip_member_context_not_full:{arc}', list(changed.keys())
                    raw = _file_edit_encode_member_text(arc, changed[arc])
                    zi = zipfile.ZipInfo(filename=arc, date_time=getattr(info, 'date_time', (1980, 1, 1, 0, 0, 0)) or (1980, 1, 1, 0, 0, 0))
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    try:
                        zi.external_attr = info.external_attr
                    except Exception:
                        pass
                    zout.writestr(zi, raw)
                    written.add(arc)
                else:
                    zout.writestr(info, original_raw)
                    written.add(arc)
            for arc, body in changed.items():
                if arc in written:
                    continue
                zout.writestr(arc, _file_edit_encode_member_text(arc, body))
                written.add(arc)
        raw_zip = out.getvalue()
        if not raw_zip:
            return [], 'zip_rebuild_empty', list(changed.keys())
        publisher = globals().get('_sandbox_stage_and_publish_artifacts')
        publish_result = publisher([{
            'filename': final_name,
            'mime': 'application/zip',
            'encoding': 'base64',
            'data': base64.b64encode(raw_zip).decode('ascii'),
        }], messages or [], source='legacy_zip_edit') if callable(publisher) else {'ok': False, 'files': []}
        saved = [dict(x) for x in (publish_result.get('files') or []) if isinstance(x, dict)]
        if not saved:
            return [], 'zip_rebuild_save_failed', list(changed.keys())
        for item in saved:
            if isinstance(item, dict):
                item['packaged_zip'] = True
                item['bundle_members'] = list(written)
                item['bundle_count'] = len(written)
                item['edited_archive_members'] = list(changed.keys())
        return saved, '', list(changed.keys())
    except Exception as e:
        try:
            app_logger.exception('[zip_edit_save] failed target=%s output=%s', str(record.get('filename') or record.get('saved_filename') or ''), output_filename)
        except Exception:
            pass
        return [], f'zip_rebuild_failed:{type(e).__name__}:{e}', list(changed.keys())


def _file_edit_save_single_member_from_zip_edit(source_text: str, new_text: str, output_filename: str, messages: list | None = None) -> tuple[list[dict], str, list[str]]:
    changed, changed_err = _file_edit_zip_changed_members(source_text, new_text)
    if changed_err:
        return [], changed_err, []
    desired = _safe_artifact_relative_path(str(output_filename or '').strip())
    selected = ''
    if desired and desired in changed:
        selected = desired
    elif desired:
        desired_leaf = os.path.basename(desired).lower()
        hits = [name for name in changed if os.path.basename(name).lower() == desired_leaf]
        if len(hits) == 1:
            selected = hits[0]
    if not selected and len(changed) == 1:
        selected = next(iter(changed.keys()))
    if not selected:
        return [], 'zip_single_member_edit_ambiguous', list(changed.keys())
    out_name = desired or selected
    if os.path.splitext(out_name)[1].lower() not in ALLOWED_EXT:
        return [], f'output_extension_not_allowed:{os.path.splitext(out_name)[1].lower()}', list(changed.keys())
    publisher = globals().get('_sandbox_stage_and_publish_artifacts')
    publish_result = publisher([{
        'filename': out_name,
        'mime': _guess_content_type_for_file(out_name),
        'encoding': 'utf-8',
        'data': changed[selected],
    }], messages or [], source='legacy_zip_member_edit') if callable(publisher) else {'ok': False, 'files': []}
    saved = [dict(x) for x in (publish_result.get('files') or []) if isinstance(x, dict)]
    return saved or [], '' if saved else 'save_zip_member_failed', [selected]




def _file_edit_generated_version_filename(base_filename: str) -> str:
    """Return a stable new filename for edited existing files.

    修改现有文件时不要把结果仍命名为原文件名，否则前端/浏览器容易把“原上传文件”、
    “生成文件”和“下载文件”混在一起，表现为点不开、看不到第二个文件或误以为没生成。
    这里只负责给编辑结果起新版本名，不改变编辑内容。
    """
    safe = _safe_filename(base_filename or '')
    if not safe:
        safe = 'edited-file.txt'
    stem, ext = os.path.splitext(safe)
    if not ext:
        ext = '.txt'
    stem = stem or 'edited-file'
    ext_l = ext.lower()
    max_ver = 0
    try:
        root = _generated_dir_for_scope(_request_upload_scope(), ensure=True)
        pattern = re.compile(r'^' + re.escape(stem) + r'-v(\d+)' + re.escape(ext_l) + r'$', re.I)
        for name in os.listdir(root):
            low = str(name or '').lower()
            if low == f'{stem.lower()}{ext_l}':
                max_ver = max(max_ver, 1)
                continue
            m = pattern.match(low)
            if m:
                try:
                    max_ver = max(max_ver, int(m.group(1) or 0))
                except Exception:
                    pass
    except Exception:
        pass
    next_ver = max(2, max_ver + 1)
    return _safe_filename(f'{stem}-v{next_ver}{ext}')


def _file_edit_normalize_output_filename(edit: dict | None, record: dict | None, target_name: str = '') -> str:
    """Pick a user-visible output filename for historical file-edit audit rows.

    - The edited file is always saved as a generated new version.
    - If the model passes the original filename again, convert it to a versioned name.
    - If the model explicitly passes another valid filename, keep it and let save layer dedupe.
    """
    edit = dict(edit or {})
    rec = dict(record or {})
    raw_output = _safe_filename(edit.get('output_filename') or '')
    source_names = {
        _safe_filename(target_name or '').lower(),
        _safe_filename(rec.get('filename') or '').lower(),
        _safe_filename(rec.get('saved_filename') or '').lower(),
    }
    source_names = {x for x in source_names if x}
    fallback_source = _safe_filename(rec.get('filename') or rec.get('saved_filename') or target_name or 'edited-file.txt')
    if not raw_output:
        return _file_edit_generated_version_filename(fallback_source)
    if raw_output.lower() in source_names:
        return _file_edit_generated_version_filename(raw_output)
    return raw_output


def _file_edit_normalize_match_text(s: str) -> str:
    """Normalize text only for locating a unique patch target; never used as output."""
    try:
        s = str(s or '').replace('\r\n', '\n').replace('\r', '\n')
        # Keep token order, but ignore indentation/trailing-space differences.
        s = '\n'.join(line.rstrip() for line in s.split('\n'))
        s = re.sub(r'\s+', ' ', s).strip()
        return s
    except Exception:
        return str(s or '')


def _file_edit_line_offsets_for_spans(text: str) -> list[int]:
    offsets = [0]
    for m in re.finditer(r'\n', str(text or '')):
        offsets.append(m.end())
    return offsets


def _file_edit_extract_primary_symbol_name_for_patch(*parts: str) -> str:
    combined = '\n'.join(str(p or '') for p in parts if str(p or '').strip())
    if not combined:
        return ''
    patterns = [
        r'\basync\s+function\s+([A-Za-z_$][\w$]*)\s*\(',
        r'\bfunction\s+([A-Za-z_$][\w$]*)\s*\(',
        r'\bdef\s+([A-Za-z_]\w*)\s*\(',
        r'\bclass\s+([A-Za-z_]\w*)\b',
        r'\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>',
        r'\b([A-Za-z_$][\w$]*)\s*:\s*(?:async\s*)?function\s*\(',
    ]
    for pat in patterns:
        m = re.search(pat, combined)
        if m:
            return str(m.group(1) or '').strip()
    return ''


def _file_edit_find_fuzzy_line_span(source_text: str, old: str) -> tuple[int, int, float, str]:
    """Find a unique high-confidence line span for old in source_text.

    This is a product-style fuzzy patch fallback similar in spirit to coding
    agents/editors that tolerate harmless whitespace drift, while still refusing
    ambiguous or low-confidence patches.
    """
    src = str(source_text or '').replace('\r\n', '\n').replace('\r', '\n')
    old_s = str(old or '').replace('\r\n', '\n').replace('\r', '\n')
    if not src or not old_s.strip():
        return -1, -1, 0.0, 'empty'
    old_norm = _file_edit_normalize_match_text(old_s)
    if len(old_norm) < 40:
        return -1, -1, 0.0, 'old_too_short_for_fuzzy'
    src_lines_keep = src.splitlines(keepends=True)
    src_lines_plain = [ln.rstrip('\n') for ln in src_lines_keep]
    old_line_count = max(1, len(old_s.splitlines()))
    offsets = _file_edit_line_offsets_for_spans(src)
    import difflib as _difflib
    best = (-1.0, -1, -1, '')
    second = -1.0
    sizes = sorted(set([old_line_count, old_line_count - 3, old_line_count - 2, old_line_count - 1, old_line_count + 1, old_line_count + 2, old_line_count + 3]))
    sizes = [n for n in sizes if n > 0]
    for win in sizes:
        if win > len(src_lines_plain):
            continue
        for i in range(0, len(src_lines_plain) - win + 1):
            chunk = ''.join(src_lines_keep[i:i+win])
            norm = _file_edit_normalize_match_text(chunk)
            if not norm:
                continue
            # Quick token overlap guard before SequenceMatcher.
            ratio = _difflib.SequenceMatcher(None, old_norm, norm, autojunk=False).ratio()
            if ratio > best[0]:
                second = best[0]
                best = (ratio, i, i + win, chunk)
            elif ratio > second:
                second = ratio
    ratio, start_line_idx, end_line_idx, _chunk = best
    old_len = len(old_norm)
    threshold = 0.965 if old_len < 250 else 0.925
    unique = ratio >= 0.985 or (ratio - second) >= 0.025
    if ratio < threshold:
        return -1, -1, float(ratio), 'fuzzy_low_confidence'
    if not unique:
        return -1, -1, float(ratio), 'fuzzy_ambiguous'
    start = offsets[start_line_idx]
    end = offsets[end_line_idx] if end_line_idx < len(offsets) else len(src)
    return start, end, float(ratio), 'fuzzy_line_window'


def _file_edit_find_patch_span(source_text: str, old: str, new: str) -> tuple[int, int, str, dict]:
    """Locate a replacement span when exact_old does not match exactly.

    Order: exact -> complete symbol block -> high-confidence fuzzy line window.
    The fallback is intentionally generic: it is based on code block identity and
    similarity, not on project-specific UI words or functions.
    """
    src = str(source_text or '')
    old_s = str(old or '')
    new_s = str(new or '')
    exact_pos = src.find(old_s) if old_s else -1
    if exact_pos >= 0:
        return exact_pos, exact_pos + len(old_s), 'exact', {'occurrences': src.count(old_s)}

    symbol = _file_edit_extract_primary_symbol_name_for_patch(old_s, new_s)
    if symbol:
        # Try generic code-block extraction without relying on project-specific names.
        fake_rec = {'filename': 'unknown.js'}
        block, _st, _en = _file_read_extract_js_like_block(src, '', symbol)
        if not block:
            block, _st, _en = _file_read_extract_python_block(src, '', symbol)
        if block:
            bpos = src.find(block)
            if bpos >= 0:
                old_norm = _file_edit_normalize_match_text(old_s)
                blk_norm = _file_edit_normalize_match_text(block)
                import difflib as _difflib
                ratio = _difflib.SequenceMatcher(None, old_norm, blk_norm, autojunk=False).ratio() if old_norm and blk_norm else 0.0
                # If the model supplied a complete replacement for the same named block,
                # replacing that original block is usually safer than failing on whitespace drift.
                if len(block) >= 80 and (ratio >= 0.72 or symbol in new_s):
                    return bpos, bpos + len(block), 'symbol_block', {'symbol': symbol, 'similarity': ratio, 'old_chars': len(old_s), 'block_chars': len(block)}

    start, end, ratio, reason = _file_edit_find_fuzzy_line_span(src, old_s)
    if start >= 0 and end > start:
        return start, end, reason, {'similarity': ratio, 'old_chars': len(old_s), 'span_chars': end - start}
    return -1, -1, reason, {'similarity': ratio}

def _file_edit_apply_replacements(source_text: str, replacements: list) -> tuple[str, list[dict], str]:
    text = str(source_text or '')
    original = str(source_text or '')
    changes: list[dict] = []
    if not isinstance(replacements, list) or not replacements:
        return text, changes, 'empty_replacements'
    for idx, rep in enumerate(replacements, start=1):
        if not isinstance(rep, dict):
            return text, changes, f'invalid_replacement_at:{idx}'
        old = str(rep.get('exact_old') if rep.get('exact_old') is not None else rep.get('old') or '')
        new = str(rep.get('replacement') if rep.get('replacement') is not None else rep.get('new') or '')
        if not old:
            return text, changes, f'missing_exact_old_at:{idx}'
        replace_all = bool(rep.get('replace_all'))
        try:
            expected = int(rep.get('expected_occurrences') or (0 if replace_all else 1))
        except Exception:
            expected = 0 if replace_all else 1
        actual = text.count(old)

        if actual > 0:
            if expected > 0 and actual != expected:
                return text, changes, f'occurrence_mismatch_at:{idx}:expected={expected}:actual={actual}'
            if not replace_all and expected <= 0 and actual != 1:
                return text, changes, f'ambiguous_exact_old_at:{idx}:actual={actual}'
            if replace_all:
                text = text.replace(old, new)
                changed = actual
            else:
                text = text.replace(old, new, 1)
                changed = 1
            changes.append({'index': idx, 'occurrences': changed, 'old_chars': len(old), 'new_chars': len(new), 'strategy': 'exact'})
            continue

        # If exact_old is not found, tolerate harmless whitespace/context drift only
        # through a unique high-confidence patch span. This prevents product-grade
        # edits from failing just because the model copied indentation/newlines
        # imperfectly, while still refusing ambiguous patches.
        if replace_all:
            return text, changes, f'exact_old_not_found_at:{idx}'
        span_start, span_end, strategy, meta = _file_edit_find_patch_span(text, old, new)
        if span_start < 0 or span_end <= span_start:
            detail = str(strategy or 'not_found')
            try:
                sim = meta.get('similarity') if isinstance(meta, dict) else None
                if sim is not None:
                    detail += f':similarity={float(sim):.3f}'
            except Exception:
                pass
            return text, changes, f'occurrence_mismatch_at:{idx}:expected={expected}:actual=0:{detail}'
        before_span = text[span_start:span_end]
        text = text[:span_start] + new + text[span_end:]
        change = {'index': idx, 'occurrences': 1, 'old_chars': len(before_span), 'new_chars': len(new), 'strategy': strategy}
        if isinstance(meta, dict):
            for k, v in meta.items():
                if k not in change:
                    change[k] = v
        changes.append(change)
    if text == original:
        return text, changes, 'no_effective_change'
    return text, changes, ''



def _file_edit_unified_diff_for_verify(filename: str, before: str, after: str, *, max_chars: int = 50000) -> str:
    """Build a compact unified diff for post-edit verification."""
    try:
        difflib = __import__('difflib')
        before_lines = str(before or '').splitlines(keepends=True)
        after_lines = str(after or '').splitlines(keepends=True)
        diff = ''.join(difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f'before/{os.path.basename(str(filename or "file"))}',
            tofile=f'after/{os.path.basename(str(filename or "file"))}',
            lineterm='',
        ))
    except Exception:
        diff = ''
    diff = str(diff or '')
    max_chars = max(4000, min(int(max_chars or 50000), 120000))
    if len(diff) > max_chars:
        head = diff[: max_chars // 2]
        tail = diff[-max_chars // 2:]
        diff = head + '\n\n...【diff 中间过长，已省略】...\n\n' + tail
    return diff



def _file_edit_actual_diff_summary(before: str, after: str, *, max_lines: int = 16, max_chars: int = 2200) -> list[str]:
    """Return a compact factual summary extracted only from the real saved diff.

    This prevents the final answer from describing the model's plan instead of
    the bytes that were actually written to disk. It is not an intent rule; it
    only reports concrete added/removed lines from the applied patch.
    """
    try:
        import difflib as _difflib
        diff_lines = list(_difflib.unified_diff(
            str(before or '').splitlines(),
            str(after or '').splitlines(),
            fromfile='before',
            tofile='after',
            lineterm='',
        ))
    except Exception:
        diff_lines = []
    out: list[str] = []
    seen: set[str] = set()
    for line in diff_lines:
        if not line or line.startswith(('+++', '---', '@@')):
            continue
        if not (line.startswith('+') or line.startswith('-')):
            continue
        body = line[1:].strip()
        if not body:
            continue
        if len(body) > 240:
            body = body[:240] + '…'
        item = f"{line[0]} {body}"
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= max(1, int(max_lines or 16)):
            break
    text_len = 0
    clipped: list[str] = []
    for item in out:
        text_len += len(item) + 1
        if text_len > max(200, int(max_chars or 2200)):
            break
        clipped.append(item)
    return clipped


def _file_edit_sha256_text(text: str) -> str:
    try:
        return hashlib.sha256(str(text or '').encode('utf-8', 'surrogatepass')).hexdigest()
    except Exception:
        return ''


def _file_edit_basename_for_id(value: str = '') -> str:
    try:
        return os.path.basename(str(value or '').strip().replace('\\', '/')).strip()
    except Exception:
        return str(value or '').strip()


def _file_edit_make_task_job_id() -> str:
    try:
        return 'fejob_' + uuid.uuid4().hex[:16]
    except Exception:
        try:
            return 'fejob_' + hashlib.sha1(str(time.time()).encode('utf-8')).hexdigest()[:16]
        except Exception:
            return 'fejob_unknown'


def _file_edit_lineage_key_from_record(rec: dict | None = None, *, basis_filename: str = '', target_filename: str = '', output_filename: str = '', audit: dict | None = None) -> str:
    row = dict(rec or {}) if isinstance(rec, dict) else {}
    aud = dict(audit or {}) if isinstance(audit, dict) else {}
    raw_key = ''
    helper = globals().get('_history_file_lineage_group_key')
    if callable(helper) and row:
        try:
            raw_key = str(helper(row) or '').strip()
        except Exception:
            raw_key = ''
    if raw_key and '@' in raw_key:
        return raw_key[:180]

    names: list[str] = []
    def push_name(value) -> None:
        name = _file_edit_basename_for_id(str(value or ''))
        if name and name.lower() not in {x.lower() for x in names}:
            names.append(name)

    if raw_key:
        push_name(raw_key)
    edited_from = row.get('edited_from') if isinstance(row.get('edited_from'), dict) else {}
    for key in ('filename', 'saved_filename', 'basis_filename', 'requested_target_filename'):
        push_name(edited_from.get(key))
    row_audit = row.get('edit_audit') if isinstance(row.get('edit_audit'), dict) else {}
    details = row.get('edit_details') if isinstance(row.get('edit_details'), dict) else {}
    details_audit = details.get('audit') if isinstance(details.get('audit'), dict) else {}
    for item in (aud, row_audit, details_audit):
        if not isinstance(item, dict):
            continue
        for key in ('lineage_source_filename', 'basis_filename', 'source_filename', 'original_filename', 'requested_target_filename', 'target_filename'):
            push_name(item.get(key))
    for value in (basis_filename, target_filename, row.get('filename'), row.get('saved_filename'), output_filename):
        push_name(value)

    name = names[0] if names else (_file_edit_basename_for_id(basis_filename or target_filename or output_filename) or 'file')
    hashes: list[str] = []
    def push_hash(value) -> None:
        h = str(value or '').strip().lower()
        if h and h not in hashes:
            hashes.append(h)
    for item in (aud, row_audit, details_audit):
        if isinstance(item, dict):
            push_hash(item.get('lineage_sha256'))
            push_hash(item.get('basis_sha256'))
            push_hash(item.get('old_sha256'))
    push_hash(row.get('content_hash'))
    suffix = hashes[0][:12] if hashes else hashlib.sha1(name.lower().encode('utf-8', errors='ignore')).hexdigest()[:12]
    safe_name = re.sub(r'[^0-9A-Za-z._-]+', '-', name)[:80] or 'file'
    return f'{safe_name}@{suffix}'


def _file_edit_make_audit_id(*, task_job_id: str = '', lineage_key: str = '', target_filename: str = '', basis_filename: str = '', output_filename: str = '', old_sha256: str = '', new_sha256: str = '', created_at: str = '') -> str:
    seed = '|'.join([
        str(task_job_id or ''),
        str(lineage_key or ''),
        str(target_filename or ''),
        str(basis_filename or ''),
        str(output_filename or ''),
        str(old_sha256 or ''),
        str(new_sha256 or ''),
        str(created_at or ''),
    ])
    try:
        return 'audit_' + hashlib.sha1(seed.encode('utf-8', errors='ignore')).hexdigest()[:20]
    except Exception:
        return 'audit_unknown'


def _file_edit_compact_verification_for_audit(verification: dict | None = None, static_checks: dict | None = None) -> dict:
    ver = dict(verification or {}) if isinstance(verification, dict) else {}
    static = dict(static_checks or {}) if isinstance(static_checks, dict) else {}
    out = {
        'passed': bool(ver.get('passed', True)),
        'source': str(ver.get('source') or '').strip(),
        'confidence': ver.get('confidence'),
        'issues': [str(x or '').strip() for x in (ver.get('issues') or []) if str(x or '').strip()][:12],
        'missing': [str(x or '').strip() for x in (ver.get('missing') or []) if str(x or '').strip()][:12],
        'warnings': [str(x or '').strip() for x in (static.get('warnings') or ver.get('warnings') or []) if str(x or '').strip()][:12],
        'static_errors': [str(x or '').strip() for x in (static.get('errors') or []) if str(x or '').strip()][:12],
    }
    summary = str(ver.get('summary') or '').strip()
    if summary:
        out['summary'] = summary[:1000]
    return out


def _file_edit_build_audit_record(*, target_filename: str, output_filename: str, before: str, after: str, changes: list | None = None, verification: dict | None = None, static_checks: dict | None = None, user_request: str = '', reason: str = '', basis_filename: str = '', requested_target_filename: str = '', merge_sources: list | None = None, audit_id: str = '', task_job_id: str = '', lineage_key: str = '') -> dict:
    """Create a factual audit record from real pre/post file bytes.

    This is not an intent router. It is generated only after an existing-file
    edit has been applied to the real full source text, so later replies can
    explain what changed from evidence instead of recalling the model's plan.
    """
    before_text = str(before or '')
    after_text = str(after or '')
    diff_text = _file_edit_unified_diff_for_verify(
        output_filename or target_filename or 'file',
        before_text,
        after_text,
        max_chars=_cfg_int('FILE_EDIT_AUDIT_DIFF_MAX_CHARS', 60000),
    )
    summary = _file_edit_actual_diff_summary(before_text, after_text, max_lines=24, max_chars=3200)
    old_hash = _file_edit_sha256_text(before_text)
    new_hash = _file_edit_sha256_text(after_text)
    lineage = str(lineage_key or '').strip() or _file_edit_lineage_key_from_record(
        None,
        basis_filename=basis_filename or target_filename,
        target_filename=target_filename,
        output_filename=output_filename,
        audit={'basis_sha256': old_hash, 'old_sha256': old_hash},
    )
    task_id = str(task_job_id or '').strip() or _file_edit_make_task_job_id()
    created_at = _fmt_ts(_utc_ts()) if '_fmt_ts' in globals() else ''
    audit_key = str(audit_id or '').strip() or _file_edit_make_audit_id(
        task_job_id=task_id,
        lineage_key=lineage,
        target_filename=target_filename,
        basis_filename=basis_filename or target_filename,
        output_filename=output_filename,
        old_sha256=old_hash,
        new_sha256=new_hash,
        created_at=created_at,
    )
    return {
        '_kind': 'file_edit_audit',
        'audit_id': audit_key,
        'task_job_id': task_id,
        'lineage_key': lineage,
        'target_filename': str(target_filename or '').strip(),
        'requested_target_filename': str(requested_target_filename or target_filename or '').strip(),
        'basis_filename': str(basis_filename or target_filename or '').strip(),
        'output_filename': str(output_filename or '').strip(),
        'changed': bool(before_text != after_text),
        'old_sha256': old_hash,
        'new_sha256': new_hash,
        'basis_sha256': old_hash,
        'lineage_sha256': old_hash,
        'merge_sources': list(merge_sources or [])[:12],
        'old_chars': len(before_text),
        'new_chars': len(after_text),
        'old_lines': before_text.count('\n') + 1 if before_text else 0,
        'new_lines': after_text.count('\n') + 1 if after_text else 0,
        'changes': list(changes or [])[:40],
        'diff_summary': summary,
        'diff': diff_text,
        'verification': _file_edit_compact_verification_for_audit(verification, static_checks),
        'user_request': str(user_request or '').strip()[:2400],
        'reason': str(reason or '').strip()[:1200],
        'created_at': created_at,
    }


def _file_edit_compact_audit_for_payload(audit: dict | None = None, *, include_diff: bool = True) -> dict:
    row = dict(audit or {}) if isinstance(audit, dict) else {}
    if not row:
        return {}
    out = {
        '_kind': 'file_edit_audit',
        'audit_id': str(row.get('audit_id') or '').strip(),
        'task_job_id': str(row.get('task_job_id') or '').strip(),
        'lineage_key': str(row.get('lineage_key') or '').strip(),
        'target_filename': str(row.get('target_filename') or '').strip(),
        'requested_target_filename': str(row.get('requested_target_filename') or row.get('target_filename') or '').strip(),
        'basis_filename': str(row.get('basis_filename') or row.get('target_filename') or '').strip(),
        'output_filename': str(row.get('output_filename') or '').strip(),
        'changed': bool(row.get('changed')),
        'old_sha256': str(row.get('old_sha256') or '').strip(),
        'new_sha256': str(row.get('new_sha256') or '').strip(),
        'basis_sha256': str(row.get('basis_sha256') or row.get('old_sha256') or '').strip(),
        'lineage_sha256': str(row.get('lineage_sha256') or row.get('basis_sha256') or row.get('old_sha256') or '').strip(),
        'merge_sources': [dict(x) if isinstance(x, dict) else {'filename': str(x or '')} for x in (row.get('merge_sources') or [])][:12],
        'old_chars': int(row.get('old_chars') or 0),
        'new_chars': int(row.get('new_chars') or 0),
        'old_lines': int(row.get('old_lines') or 0),
        'new_lines': int(row.get('new_lines') or 0),
        'diff_summary': [str(x or '').strip() for x in (row.get('diff_summary') or []) if str(x or '').strip()][:24],
        'verification': dict(row.get('verification') or {}) if isinstance(row.get('verification'), dict) else {},
        'user_request': str(row.get('user_request') or '').strip()[:2400],
        'reason': str(row.get('reason') or '').strip()[:1200],
        'created_at': str(row.get('created_at') or '').strip(),
    }
    for key in ('sandbox_path', 'operation', 'format'):
        value = str(row.get(key) or '').strip()
        if value:
            out[key] = value[:500]
    for key in ('append', 'created', 'binary'):
        if key in row:
            out[key] = bool(row.get(key))
    for key in ('old_bytes', 'new_bytes'):
        if key in row:
            try:
                out[key] = int(row.get(key) or 0)
            except Exception:
                out[key] = 0
    if include_diff:
        out['diff'] = str(row.get('diff') or '')[:_cfg_int('FILE_EDIT_AUDIT_PAYLOAD_DIFF_MAX_CHARS', 60000)]
    return out


def _file_edit_build_saved_answer(saved_files: list | None = None, details: list | None = None) -> str:
    """Build the user-facing edit answer from actual saved files/details only.

    Do not reuse the model-supplied `answer` field from historical edit payloads,
    because that field can describe an intended plan that differs from the
    concrete patch applied by the backend. This keeps final chat text aligned
    with the real saved file and avoids cross-turn/version hallucinations.
    """
    files = [f for f in (saved_files or []) if isinstance(f, dict)]
    ds = [d for d in (details or []) if isinstance(d, dict)]
    names = []
    for f in files:
        name = str(f.get('filename') or '').strip()
        if name and name not in names:
            names.append(name)
    if names:
        if len(names) == 1:
            first = f'已保存修改后的完整文件：{names[0]}。'
        else:
            first = '已保存修改后的完整文件：' + '、'.join(names) + '。'
    else:
        first = '已保存修改后的完整文件。'
    lines = [first, '本次说明只根据后端实际保存结果生成，不复述模型计划。']
    diff_items: list[str] = []
    for d in ds:
        for item in (d.get('actual_diff_summary') or []):
            s = str(item or '').strip()
            if s and s not in diff_items:
                diff_items.append(s)
            if len(diff_items) >= 10:
                break
        if len(diff_items) >= 10:
            break
    if diff_items:
        lines.append('实际 diff 摘要：')
        lines.extend(f'- {x}' for x in diff_items[:10])

    review_items: list[str] = []
    for d in ds:
        verification = d.get('verification') if isinstance(d.get('verification'), dict) else {}
        if not bool((verification or {}).get('needs_review')):
            continue
        for item in (verification.get('issues') or []):
            text = str(item or '').strip()
            if text and text not in review_items:
                review_items.append(text)
            if len(review_items) >= 6:
                break
        if len(review_items) < 6:
            for item in (verification.get('missing') or []):
                text = str(item or '').strip()
                if text and text not in review_items:
                    review_items.append(text)
                if len(review_items) >= 6:
                    break
        fix_instruction = str(verification.get('fix_instruction') or '').strip()
        if fix_instruction and fix_instruction not in review_items and len(review_items) < 6:
            review_items.append(fix_instruction)
        if len(review_items) >= 6:
            break
    if review_items:
        lines.append('自检提示：文件已保存；以下属于可继续优化项，不再阻断交付。')
        lines.extend(f'- {x}' for x in review_items[:6])

    visible_diff_limit = _cfg_int('FILE_EDIT_VISIBLE_DIFF_MAX_CHARS', 9000)
    diff_blocks: list[str] = []
    used = 0
    for d in ds:
        audit = d.get('audit') if isinstance(d.get('audit'), dict) else {}
        diff = str((audit or {}).get('diff') or '').strip()
        if not diff:
            continue
        remain = max(0, visible_diff_limit - used)
        if remain <= 0:
            break
        if len(diff) > remain:
            diff = diff[:remain].rstrip() + '\n...（diff 已截断，只展示前半部分）'
        header = str(d.get('basis_filename') or d.get('target_filename') or '').strip()
        output = str(d.get('output_filename') or '').strip()
        title = f'{header} -> {output}'.strip(' ->')
        diff_blocks.append((f'文件：{title}\n' if title else '') + '```diff\n' + diff + '\n```')
        used += len(diff)
    if diff_blocks:
        lines.append('真实 diff 片段：')
        lines.extend(diff_blocks)
    return '\n'.join(lines).strip()

def _file_edit_static_post_checks(filename: str, before: str, after: str, changes: list | None = None, user_request: str = '') -> dict:
    """Deterministic safety checks before semantic verification.

    这些是交付前质量门，不参与前置意图分流；只在模型已经完成现有文件编辑后，
    检查结果是否明显损坏、缩水或不像完整原文件。这里也做少量交付证据检查：
    对于已落到现有 UI 行为的修改，不能只新增静态占位或 CSS，必须能在相关
    渲染函数里看到对应运行时逻辑。
    """
    fn = str(filename or '').strip()
    ext = os.path.splitext(fn)[1].lower()
    old = str(before or '')
    new = str(after or '')
    req = str(user_request or '')
    req_l = req.lower()
    errors: list[str] = []
    warnings: list[str] = []
    if not new.strip():
        errors.append('edited_file_empty')
    if old == new:
        errors.append('no_effective_change')
    if len(old) >= 2000:
        ratio = (len(new) / max(1, len(old)))
        if ratio < 0.55:
            warnings.append(f'edited_file_much_smaller:ratio={ratio:.3f}')
        elif ratio > 2.50:
            warnings.append(f'edited_file_much_larger:ratio={ratio:.3f}')
    if ext in {'.html', '.htm'}:
        old_l = old.lower()
        new_l = new.lower()
        if '<html' in old_l and '<html' not in new_l:
            errors.append('html_tag_missing')
        if '</html>' in old_l and '</html>' not in new_l:
            errors.append('html_closing_tag_missing')
        if '<body' in old_l and '<body' not in new_l:
            errors.append('body_tag_missing')
        if '</body>' in old_l and '</body>' not in new_l:
            errors.append('body_closing_tag_missing')
        if '<script' in old_l and '<script' not in new_l:
            errors.append('script_tag_missing')
    if ext in {'.py', '.pyw', '.js', '.jsx', '.ts', '.tsx', '.html', '.htm', '.css', '.json', '.md', '.txt'}:
        old_lines = old.count('\n') + 1
        new_lines = new.count('\n') + 1
        if old_lines >= 80 and new_lines < max(20, int(old_lines * 0.45)):
            warnings.append(f'line_count_much_smaller:before={old_lines}:after={new_lines}')

    # Generic edit sanity: if the user asked to modify an existing code/text file
    # and the model only changed a static literal while leaving all executable
    # blocks untouched, flag it for review. This is intentionally generic and
    # does not encode project-specific function/variable names.
    if ext in {'.html', '.htm', '.js', '.jsx', '.ts', '.tsx'}:
        try:
            diff_text = _file_edit_make_unified_diff(fn or 'before', before, after, max_chars=30000)
        except Exception:
            diff_text = ''
        changed_script = bool(re.search(r'^[+-].*(function\s+|=>|\.addEventListener\s*\(|\.onclick\s*=|if\s*\(|for\s*\(|while\s*\(|appendChild\s*\(|insertBefore\s*\(|textContent\s*=|innerHTML\s*=)', diff_text, flags=re.I | re.M))
        changed_markup_or_style = bool(re.search(r'^[+-].*(<div|<span|<style|\.[A-Za-z0-9_-]+\s*\{)', diff_text, flags=re.I | re.M))
        wants_runtime_behavior = bool(re.search(r'(当|如果|时|为空|点击|发送|上传|删除|添加|新增|移除|清空|切换|when|if|on click|send|upload|delete|remove|add)', req, flags=re.I))
        if wants_runtime_behavior and changed_markup_or_style and not changed_script:
            errors.append('runtime_behavior_request_changed_only_markup_or_style')

    return {
        'passed': not errors,
        'errors': errors,
        'warnings': warnings,
        'before_chars': len(old),
        'after_chars': len(new),
        'before_lines': old.count('\n') + 1 if old else 0,
        'after_lines': new.count('\n') + 1 if new else 0,
        'changes': changes or [],
    }


def _file_edit_verifier_enabled() -> bool:
    try:
        raw = str(app_getenv('FILE_EDIT_VERIFY_ENABLED', '1') or '1').strip().lower()
        return raw not in {'0', 'false', 'no', 'off', 'disabled'}
    except Exception:
        return True


def _file_edit_verifier_model(default_model: str | None = None) -> str:
    try:
        raw = str(app_getenv('FILE_EDIT_VERIFY_MODEL', '') or '').strip()
    except Exception:
        raw = ''
    if raw:
        return raw
    try:
        planner = str(app_getenv('TOOL_PREFETCH_MODEL', '') or '').strip()
    except Exception:
        planner = ''
    return planner or str(default_model or DEFAULT_MODEL or '').strip()


def _file_edit_verify_with_model(*, filename: str, user_request: str, edit_reason: str, before: str, after: str, changes: list | None = None, static_checks: dict | None = None, client_override=None, model: str | None = None) -> dict:
    """Static-only post-edit verification.

    This intentionally avoids hidden non-stream LLM verifier calls.  The actual edit
    tool already ran through the model; after bytes are written we only keep factual
    static checks and diff audit, so failed/extra verifier requests cannot create
    separate non-stream records or override a successful artifact.
    """
    static = dict(static_checks or {})
    if static and not bool(static.get('passed', True)):
        return {
            'ok': True,
            'passed': False,
            'source': 'static',
            'issues': list(static.get('errors') or []),
            'warnings': list(static.get('warnings') or []),
            'fix_instruction': '先修复静态验收错误，再重新提交完整文件修改。',
            'static_checks': static,
        }
    return {
        'ok': True,
        'passed': True,
        'source': 'static_only_no_llm',
        'issues': [],
        'missing': [],
        'warnings': list(static.get('warnings') or []) if isinstance(static, dict) else [],
        'static_checks': static,
    }
