# Split from app3_parts/tools/file_registry_edit_tools_part.py.
# Purpose: sandbox visual preview URLs, route, and activity thumbnail helpers.
# Loaded by file_registry_edit_tools_part.py via _exec_split_file(...), sharing app3.py globals.

_SANDBOX_VISUAL_PREVIEW_SECRET = secrets.token_bytes(32)
_SANDBOX_VISUAL_PREVIEW_MAX_AGE_S = 7 * 24 * 60 * 60


def _sandbox_visual_preview_url(rel_path: str = '', messages: list | None = None) -> str:
    """为内部文档渲染页生成短期、当前账号可访问的缩略图地址。"""
    rel = str(rel_path or '').strip().replace('\\', '/').lstrip('/')
    if not rel.startswith('.app3_vision/') or '..' in rel.split('/'):
        return ''
    if os.path.splitext(rel)[1].lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
        return ''
    payload = {
        'owner': _sandbox_owner_slug(),
        'session': _sandbox_session_slug(messages or []),
        'path': rel,
        'expires': int(time.time()) + _SANDBOX_VISUAL_PREVIEW_MAX_AGE_S,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8')
    body = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    signature = hmac.new(_SANDBOX_VISUAL_PREVIEW_SECRET, body.encode('ascii'), hashlib.sha256).hexdigest()
    return f'/api3/sandbox-visual-preview/{body}.{signature}'


def _sandbox_visual_preview_decode(token: str = '') -> dict:
    raw_token = str(token or '').strip()
    if '.' not in raw_token or len(raw_token) > 6000:
        return {}
    body, signature = raw_token.rsplit('.', 1)
    expected = hmac.new(_SANDBOX_VISUAL_PREVIEW_SECRET, body.encode('ascii', errors='ignore'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return {}
    try:
        padded = body + ('=' * ((4 - len(body) % 4) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8'))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    try:
        if int(payload.get('expires') or 0) < int(time.time()):
            return {}
    except Exception:
        return {}
    return payload


@app.get('/api3/sandbox-visual-preview/<path:token>')
def api3_sandbox_visual_preview(token):
    payload = _sandbox_visual_preview_decode(token)
    owner = str(payload.get('owner') or '').strip()
    session_slug = str(payload.get('session') or '').strip()
    rel = str(payload.get('path') or '').strip().replace('\\', '/').lstrip('/')
    if not owner or owner != _sandbox_owner_slug():
        return jsonify({'ok': False, 'error': 'forbidden'}), 403
    if not session_slug or session_slug != _sandbox_safe_slug(session_slug, 'session'):
        return jsonify({'ok': False, 'error': 'invalid_session'}), 400
    if not rel.startswith('.app3_vision/') or '..' in rel.split('/'):
        return jsonify({'ok': False, 'error': 'invalid_path'}), 400
    if os.path.splitext(rel)[1].lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
        return jsonify({'ok': False, 'error': 'invalid_type'}), 400
    root = os.path.abspath(os.path.join(SANDBOX_ROOT_DIR, owner, session_slug))
    target = os.path.abspath(os.path.join(root, *[part for part in rel.split('/') if part]))
    if not target.startswith(root + os.sep) or not os.path.isfile(target):
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    response = send_from_directory(os.path.dirname(target), os.path.basename(target), as_attachment=False)
    response.headers['Cache-Control'] = 'private, max-age=300'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def _sandbox_document_visual_activity_items(
    document_path: str,
    rows: list[dict] | None,
    diagnostics: dict | None,
    messages: list | None,
    visual_exec_id: str = '',
    limit: int = 12,
) -> list[dict]:
    """从真实 rendered_page 结果生成活动面板所需的轻量页缩略图。"""
    render_diag = diagnostics.get('pdf_render') if isinstance(diagnostics, dict) and isinstance(diagnostics.get('pdf_render'), dict) else {}
    selected_pages = []
    try:
        selected_pages = [int(x) for x in (render_diag.get('selected_pages') or []) if int(x) > 0]
    except Exception:
        selected_pages = []
    total_pages = 0
    try:
        total_pages = max(0, int(render_diag.get('page_count') or 0))
    except Exception:
        total_pages = 0
    out = []
    max_items = max(1, min(int(limit or 12), 24))
    for raw in rows or []:
        if not isinstance(raw, dict) or str(raw.get('source') or '').strip().lower() != 'rendered_page':
            continue
        image_path = str(raw.get('path') or '').strip().replace('\\', '/')
        preview_url = _sandbox_visual_preview_url(image_path, messages or [])
        if not preview_url:
            continue
        page_number = 0
        label = str(raw.get('label') or '').strip()
        match = re.search(r'(?:page[-_ ]?|第\s*)(\d+)', label, flags=re.I)
        if match:
            try:
                page_number = int(match.group(1))
            except Exception:
                page_number = 0
        if page_number <= 0 and len(out) < len(selected_pages):
            page_number = selected_pages[len(out)]
        if page_number <= 0:
            try:
                page_number = max(1, int(raw.get('index') or len(out) + 1))
            except Exception:
                page_number = len(out) + 1
        out.append({
            'page_number': page_number,
            'page_label': f'第 {page_number} 页',
            'label': label or f'page-{page_number}',
            'preview_url': preview_url,
            'document_name': os.path.basename(str(document_path or '').replace('\\', '/')),
            'visual_exec_id': str(visual_exec_id or '')[:80],
            'total_pages': total_pages,
        })
        if len(out) >= max_items:
            break
    return out


def _sandbox_focus_crop_script() -> str:
    """返回实际在沙盒中执行的图片局部裁剪代码。"""
    return r'''import json
import os
import sys
from PIL import Image, ImageOps

source = os.path.abspath(sys.argv[1])
output_dir = os.path.abspath(sys.argv[2])
os.makedirs(output_dir, exist_ok=True)
image = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
width, height = image.size

boxes = [
    ("focus-center", (0.06, 0.06, 0.94, 0.94)),
    ("focus-detail", (0.12, 0.24, 0.88, 0.96) if height >= width else (0.18, 0.12, 0.96, 0.88)),
]
rows = []
seen = set()
for index, (label, ratios) in enumerate(boxes, 1):
    left = max(0, min(width - 1, int(round(width * ratios[0]))))
    top = max(0, min(height - 1, int(round(height * ratios[1]))))
    right = max(left + 1, min(width, int(round(width * ratios[2]))))
    bottom = max(top + 1, min(height, int(round(height * ratios[3]))))
    if right - left < 220 or bottom - top < 180:
        continue
    key = (left, top, right, bottom)
    if key in seen:
        continue
    seen.add(key)
    filename = f"focus_{index}.png"
    target = os.path.join(output_dir, filename)
    image.crop(key).save(target, "PNG", optimize=True)
    rows.append({"label": label, "filename": filename, "box": list(key), "width": right - left, "height": bottom - top})

print(json.dumps({"ok": bool(rows), "source_size": [width, height], "crops": rows}, ensure_ascii=False))
'''


def _sandbox_focus_crop_requested(args: dict | None = None, intent_text: str = '') -> bool:
    """统一决定是否需要真实局部裁剪；显式参数优先，其次识别精细视觉任务。"""
    src = args if isinstance(args, dict) else {}
    if 'focus_crop' in src:
        return bool(src.get('focus_crop'))
    text = str(intent_text or src.get('query') or src.get('prompt') or '').strip()
    return bool(re.search(r'(仔细|详细|精细|局部|细节|放大|裁剪|看清|文字|文本|OCR|表格|公式|代码|截图|界面|小字|标注|图表)', text, re.I))


def _sandbox_generate_focus_crops(source_rel: str = '', messages: list | None = None, visual_exec_id: str = '') -> dict:
    """运行真实 Python 裁剪脚本，并返回实际生成且会进入模型视觉输入的图片。"""
    out_dir_rel = f'.app3_vision/{str(visual_exec_id or uuid.uuid4().hex[:12])}/focus_crops'
    script_rel = f'.app3_vision/{str(visual_exec_id or "focus")}_focus_crop.py'
    script_text = _sandbox_focus_crop_script()
    try:
        script_path, _ = _sandbox_resolve_path(script_rel, messages or [])
        os.makedirs(os.path.dirname(script_path), exist_ok=True)
        with open(script_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(script_text)
    except Exception as exc:
        return {'ok': False, 'error': f'focus_crop_script_write_failed:{type(exc).__name__}: {exc}', 'code': script_text, 'images': []}
    started_at = int(time.time() * 1000)
    run_result = _sandbox_run_tool({
        'argv': ['python', script_rel, source_rel, out_dir_rel],
        'timeout_s': 60,
    }, messages=messages or [])
    done_at = int(time.time() * 1000)
    stdout = str(run_result.get('stdout') or '').strip()
    stderr = str(run_result.get('stderr') or '').strip()
    try:
        payload = json.loads(stdout[stdout.find('{'):]) if '{' in stdout else {}
    except Exception:
        payload = {}
    images = []
    for index, raw in enumerate(payload.get('crops') or [], 1):
        if not isinstance(raw, dict):
            continue
        filename = os.path.basename(str(raw.get('filename') or f'focus_{index}.png'))
        crop_rel = f'{out_dir_rel}/{filename}'
        try:
            crop_abs, _ = _sandbox_resolve_path(crop_rel, messages or [], must_exist=True)
        except Exception:
            continue
        images.append({
            'index': index + 1,
            'path': crop_rel,
            'source': 'analysis_focus_crop',
            'label': str(raw.get('label') or f'focus-crop-{index}'),
            'filename': filename,
            'parent_path': source_rel,
            'crop_box': raw.get('box') if isinstance(raw.get('box'), list) else [],
            'width': int(raw.get('width') or 0),
            'height': int(raw.get('height') or 0),
            'bytes': int(os.path.getsize(crop_abs) if os.path.isfile(crop_abs) else 0),
        })
    return {
        'ok': bool(run_result.get('ok')) and bool(images),
        'code': script_text,
        'command': f'python {script_rel} {source_rel} {out_dir_rel}',
        'stdout': stdout,
        'stderr': stderr,
        'exit_code': run_result.get('exit_code'),
        'started_at': started_at,
        'done_at': done_at,
        'images': images,
        'error': '' if images else str(run_result.get('error') or stderr or 'focus_crop_no_output')[:500],
    }


def _sandbox_focus_crop_activity_items(rows: list[dict] | None, messages: list | None = None, visual_exec_id: str = '') -> list[dict]:
    """把真实裁剪文件转换为活动面板的静态图片引用。"""
    out = []
    for index, raw in enumerate(rows or [], 1):
        if not isinstance(raw, dict) or str(raw.get('source') or '').strip().lower() != 'analysis_focus_crop':
            continue
        preview_url = _sandbox_visual_preview_url(str(raw.get('path') or ''), messages or [])
        if not preview_url:
            continue
        out.append({
            'image_id': f'{str(visual_exec_id or "focus")}:crop:{index}',
            'preview_url': preview_url,
            'filename': str(raw.get('label') or raw.get('filename') or f'focus-crop-{index}'),
            'source_role': 'analysis_focus_crop',
        })
    return out[:4]
