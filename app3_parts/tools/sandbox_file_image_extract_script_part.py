# Split from app3_parts/tools/file_registry_edit_tools_part.py.
# Purpose: embedded /mnt/data visual extraction script used by sandbox_analyze_file_images.
# Loaded after file_registry_edit_tools_part.py, sharing the original global namespace.

def _sandbox_file_image_extract_script() -> str:
    return r'''
import json, os, re, shutil, subprocess, sys, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff'}
DIRECT_COPY_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp'}
OFFICE_RENDER_EXTS = {'.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls'}

def safe_name(value):
    raw = str(value or '').strip().replace('\\', '/')
    raw = raw.rsplit('/', 1)[-1]
    stem, suffix = os.path.splitext(raw)
    if suffix.lower() in IMAGE_EXTS:
        raw = stem
    raw = re.sub(r'[^0-9A-Za-z_.-]+', '-', raw).strip('.-_')
    return raw or 'image'

def short_text(value, limit=900):
    text = str(value or '').replace('\r', ' ').strip()
    text = re.sub(r'\s+', ' ', text)
    return text[:limit]

def run_cmd(cmd, timeout=100):
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return {
            'cmd': [str(x) for x in cmd],
            'exit_code': int(proc.returncode),
            'stdout': short_text(proc.stdout, 1600),
            'stderr': short_text(proc.stderr, 1600),
        }
    except Exception as exc:
        return {
            'cmd': [str(x) for x in cmd],
            'exit_code': None,
            'error': type(exc).__name__ + ': ' + str(exc),
        }

def save_image(img, outdir, source, label, index, max_side=1800):
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(img)
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    w, h = img.size
    longest = max(w, h, 1)
    if longest > max_side:
        scale = float(max_side) / float(longest)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        w, h = img.size
    if img.mode == 'L':
        img = img.convert('RGB')
    filename = f'{index:03d}_{safe_name(label)}.jpg'
    path = outdir / filename
    img.save(path, 'JPEG', quality=92, optimize=True)
    return {
        'index': index,
        'path': str(path.relative_to(Path('/mnt/data'))).replace('\\', '/'),
        'source': source,
        'label': str(label or ''),
        'width': int(w),
        'height': int(h),
        'bytes': int(path.stat().st_size),
    }

def save_raw_image(blob, outdir, source, label, index, ext):
    ext = str(ext or '').lower()
    if ext == '.jpeg':
        ext = '.jpg'
    if ext not in DIRECT_COPY_IMAGE_EXTS:
        ext = '.jpg'
    filename = f'{index:03d}_{safe_name(label)}{ext}'
    path = outdir / filename
    path.write_bytes(blob)
    width = height = 0
    try:
        img = open_image_bytes(blob)
        width, height = getattr(img, 'size', (0, 0)) or (0, 0)
    except Exception:
        pass
    return {
        'index': index,
        'path': str(path.relative_to(Path('/mnt/data'))).replace('\\', '/'),
        'source': source,
        'label': str(label or ''),
        'width': int(width or 0),
        'height': int(height or 0),
        'bytes': int(path.stat().st_size),
        'raw_copy': True,
    }

def docx_visual_inventory(src):
    info = {
        'document_type': src.suffix.lower().lstrip('.'),
        'zip_entries': 0,
        'media_count': 0,
        'media_by_ext': {},
        'drawing_count': 0,
        'object_count': 0,
        'shape_count': 0,
        'ole_count': 0,
        'embedding_count': 0,
        'caption_candidates': [],
    }
    if src.suffix.lower() != '.docx':
        return info
    ns = {
        'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
        'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
        'v': 'urn:schemas-microsoft-com:vml',
        'o': 'urn:schemas-microsoft-com:office:office',
    }
    try:
        with zipfile.ZipFile(src, 'r') as zf:
            names = zf.namelist()
            info['zip_entries'] = len(names)
            media = [n for n in names if n.lower().startswith('word/media/') and not n.endswith('/')]
            info['media_count'] = len(media)
            by_ext = {}
            for name in media:
                ext = Path(name).suffix.lower() or '<none>'
                by_ext[ext] = by_ext.get(ext, 0) + 1
            info['media_by_ext'] = by_ext
            info['embedding_count'] = len([n for n in names if n.lower().startswith('word/embeddings/') and not n.endswith('/')])
            if 'word/document.xml' not in names:
                return info
            root = ET.fromstring(zf.read('word/document.xml'))
            paras = root.findall('.//w:p', ns)
            info['paragraph_count'] = len(paras)
            info['nonempty_paragraph_count'] = len([p for p in paras if ''.join((t.text or '') for t in p.findall('.//w:t', ns)).strip()])
            info['table_count'] = len(root.findall('.//w:tbl', ns))
            info['office_math_count'] = len(root.findall('.//m:oMath', ns)) + len(root.findall('.//m:oMathPara', ns))
            info['drawing_count'] = len(root.findall('.//w:drawing', ns))
            info['object_count'] = len(root.findall('.//w:object', ns))
            info['shape_count'] = len(root.findall('.//v:shape', ns))
            info['ole_count'] = len(root.findall('.//o:OLEObject', ns))
            captions = []
            for p_idx, p in enumerate(root.findall('.//w:p', ns), 1):
                text = ''.join((t.text or '') for t in p.findall('.//w:t', ns))
                compact = re.sub(r'\s+', '', text)
                if re.search(r'(图|表|Figure|Fig\.?)\s*[\d一二三四五六七八九十]+', text, re.I) or re.search(r'(图|表)[\d一二三四五六七八九十]+', compact):
                    captions.append({
                        'paragraph_index': p_idx,
                        'text': short_text(text, 260),
                        'drawing_count': len(p.findall('.//w:drawing', ns)),
                        'object_count': len(p.findall('.//w:object', ns)),
                        'shape_count': len(p.findall('.//v:shape', ns)),
                    })
                if len(captions) >= 20:
                    break
            info['caption_candidates'] = captions
    except Exception as exc:
        info['inspect_error'] = type(exc).__name__ + ': ' + str(exc)
    return info

def open_image_bytes(blob):
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(blob))
    img.load()
    return img

def compact_text(value):
    return re.sub(r'\s+', '', str(value or '')).lower()

def target_terms_from_query(value):
    raw = str(value or '').strip()
    terms = []
    def add(term):
        term = compact_text(term)
        if term and term not in terms:
            terms.append(term)
    for m in re.finditer(r'(图|表)\s*([0-9一二三四五六七八九十]+)', raw, re.I):
        add(m.group(1) + m.group(2))
    for m in re.finditer(r'(?:figure|fig\.?)\s*([0-9]+)', raw, re.I):
        add('figure' + m.group(1))
        add('fig.' + m.group(1))
        add('fig' + m.group(1))
    if re.search(r'第\s*一\s*张\s*图|第一张图', raw):
        add('图1')
    return terms

def find_target_pages(doc, target_query):
    terms = target_terms_from_query(target_query)
    if not terms:
        return [], terms
    hits = []
    for page_index in range(len(doc)):
        try:
            text = compact_text(doc.load_page(page_index).get_text('text') or '')
        except Exception:
            text = ''
        if any(term in text for term in terms):
            hits.append(page_index)
    return hits, terms

def broad_review_query(value):
    raw = str(value or '')
    if not raw.strip():
        return False
    if 'APP3_BROAD_DOCUMENT_REVIEW' in raw:
        return True
    return bool(re.search(r'(怎么样|写得|评价|评估|审阅|检查|看看|整体|论文|报告|初稿|质量|问题|不足|建议|打分|能不能交|专业|规范|格式|逻辑|图表|公式)', raw, re.I))

def page_text_records(doc):
    rows = []
    for page_index in range(len(doc)):
        try:
            text = doc.load_page(page_index).get_text('text') or ''
        except Exception:
            text = ''
        rows.append({
            'page_index': page_index,
            'page': page_index + 1,
            'text': short_text(text, 1200),
            'compact': compact_text(text),
        })
    return rows

def score_page_for_review(record, page_count):
    text = record.get('text') or ''
    compact = record.get('compact') or ''
    page_no = int(record.get('page') or 0)
    score = 0
    reasons = []
    if page_no <= 3:
        score += 8
        reasons.append('front_matter')
    if page_count and page_no >= max(1, page_count - 2):
        score += 3
        reasons.append('ending')
    keyword_weights = [
        ('摘要', 8), ('问题重述', 5), ('问题分析', 5), ('模型假设', 5), ('符号说明', 6),
        ('模型建立', 7), ('模型求解', 7), ('目标函数', 7), ('约束', 5), ('算法', 4),
        ('结果', 6), ('结论', 6), ('灵敏度', 6), ('利润率', 5), ('满意度', 5),
        ('覆盖率', 5), ('图', 2), ('表', 2), ('公式', 4), ('equation', 4),
    ]
    for key, weight in keyword_weights:
        probe = compact_text(key)
        if probe and probe in compact:
            score += weight
            reasons.append(key)
    if re.search(r'(图|表)\s*[0-9一二三四五六七八九十]+', text) or re.search(r'(figure|fig\.?|table)\s*[0-9]+', text, re.I):
        score += 8
        reasons.append('caption')
    if len(text.strip()) < 80:
        score -= 3
        reasons.append('low_text')
    return score, reasons[:8]

def select_review_pages(doc, target_query, max_pages):
    records = page_text_records(doc)
    page_count = len(records)
    max_pages_i = max(1, int(max_pages or 1))
    if not broad_review_query(target_query):
        return list(range(min(page_count, max_pages_i))), {
            'strategy': 'first_pages',
            'selection_reason': 'no_explicit_target_or_review_intent',
            'page_count': page_count,
            'page_scores': [],
        }
    selected = []
    def add(idx):
        if 0 <= idx < page_count and idx not in selected:
            selected.append(idx)
    for idx in range(min(3, page_count)):
        add(idx)
    scored = []
    for record in records:
        score, reasons = score_page_for_review(record, page_count)
        scored.append({'page': record.get('page'), 'score': score, 'reasons': reasons})
    if page_count:
        tail_keep = min(2, page_count)
        for idx in range(max(0, page_count - tail_keep), page_count):
            add(idx)
    for item in sorted(scored, key=lambda x: (int(x.get('score') or 0), -int(x.get('page') or 0)), reverse=True):
        if len(selected) >= max_pages_i:
            break
        add(int(item.get('page') or 1) - 1)
    selected = selected[:max_pages_i]
    selected.sort()
    top_scores = [x for x in sorted(scored, key=lambda x: int(x.get('score') or 0), reverse=True) if int(x.get('score') or 0) > 0][:24]
    return selected, {
        'strategy': 'review_key_pages',
        'selection_reason': 'broad_document_review',
        'page_count': page_count,
        'page_scores': top_scores,
    }

def render_pdf_pages(pdf_path, outdir, rows, max_images, max_pages, target_query=''):
    import fitz
    doc = fitz.open(str(pdf_path))
    target_hits, target_terms = find_target_pages(doc, target_query)
    if target_terms and not target_hits:
        page_count = len(doc)
        doc.close()
        return {
            'page_count': page_count,
            'target_query': short_text(target_query, 260),
            'target_terms': target_terms,
            'target_found': False,
            'selected_pages': [],
            'strategy': 'target_text_search',
        }
    if target_hits:
        page_indexes = target_hits[:max(1, int(max_pages or 1))]
        selection_info = {'strategy': 'target_text_search', 'selection_reason': 'explicit_target_matched'}
    else:
        page_indexes, selection_info = select_review_pages(doc, target_query, max_pages)
    for page_index in page_indexes:
        if len(rows) >= max_images:
            break
        page = doc.load_page(page_index)
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        from PIL import Image
        img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
        rows.append(save_image(img, outdir, 'rendered_page', f'page-{page_index + 1}', len(rows) + 1))
    info = {
        'page_count': len(doc),
        'target_query': short_text(target_query, 260),
        'target_terms': target_terms,
        'target_found': bool(target_hits) if target_terms else None,
        'selected_pages': [int(x + 1) for x in page_indexes],
        'strategy': str(selection_info.get('strategy') or ('target_text_search' if target_terms else 'first_pages')),
        'selection_reason': str(selection_info.get('selection_reason') or ''),
        'page_scores': selection_info.get('page_scores') if isinstance(selection_info.get('page_scores'), list) else [],
    }
    doc.close()
    return info

def convert_office_to_pdf(src, outdir):
    exe = shutil.which('soffice') or shutil.which('libreoffice')
    if not exe:
        return None, {'ok': False, 'error': 'office_binary_not_found'}
    ext = src.suffix.lower()
    filters = {
        '.doc': 'pdf:writer_pdf_Export',
        '.docx': 'pdf:writer_pdf_Export',
        '.xls': 'pdf:calc_pdf_Export',
        '.xlsx': 'pdf:calc_pdf_Export',
        '.ppt': 'pdf:impress_pdf_Export',
        '.pptx': 'pdf:impress_pdf_Export',
    }
    convert_values = [filters.get(ext, 'pdf'), 'pdf']
    profile = Path('/mnt/data') / '.cache' / ('app3-lo-profile-' + str(os.getpid()))
    profile.mkdir(parents=True, exist_ok=True)
    attempts = []
    for convert_to in convert_values:
        cmd = [
            exe, '--headless', '--nologo', '--nofirststartwizard',
            '-env:UserInstallation=file://' + str(profile),
            '--convert-to', convert_to, '--outdir', str(outdir), str(src),
        ]
        attempt = run_cmd(cmd, timeout=100)
        expected = outdir / (src.stem + '.pdf')
        attempt['expected_pdf'] = str(expected)
        attempt['expected_exists'] = bool(expected.exists())
        attempts.append(attempt)
        if attempt.get('exit_code') == 0 and expected.exists():
            return expected, {'ok': True, 'attempts': attempts, 'profile': str(profile)}
        pdfs = sorted(outdir.glob('*.pdf'), key=lambda p: p.stat().st_mtime, reverse=True)
        attempt['pdf_outputs'] = [str(p) for p in pdfs[:5]]
        if attempt.get('exit_code') == 0 and pdfs:
            return pdfs[0], {'ok': True, 'attempts': attempts, 'profile': str(profile)}
    return None, {'ok': False, 'error': 'office_pdf_convert_failed', 'attempts': attempts, 'profile': str(profile), 'outdir_files': [p.name for p in sorted(outdir.glob('*'))[:40]]}

def sandbox_rel(value):
    raw = str(value or '').strip().replace('\\', '/')
    for prefix in ('/mnt/data/', '/sandbox/'):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    if raw in {'/mnt/data', '/sandbox'}:
        raw = ''
    return raw.strip('/')

def main():
    src_arg = sys.argv[1]
    out_arg = sys.argv[2]
    max_images = max(1, min(int(sys.argv[3]), 80))
    max_pages = max(1, min(int(sys.argv[4]), 80))
    target_query = sys.argv[5] if len(sys.argv) > 5 else ''
    mode = 'rendered'
    src = Path('/mnt/data') / sandbox_rel(src_arg)
    outdir = Path('/mnt/data') / sandbox_rel(out_arg)
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    errors = []
    diagnostics = {'requested_mode': mode, 'target_query': short_text(target_query, 260)}
    ext = src.suffix.lower()
    try:
        if ext == '.docx':
            diagnostics['document_visual_inventory'] = docx_visual_inventory(src)
        if ext in IMAGE_EXTS:
            img = open_image_bytes(src.read_bytes())
            rows.append(save_image(img, outdir, 'direct_image', src.name, len(rows) + 1))
        elif ext == '.pdf':
            diagnostics['pdf_render'] = render_pdf_pages(src, outdir, rows, max_images, max_pages, target_query)
            if diagnostics.get('pdf_render', {}).get('target_terms') and not diagnostics.get('pdf_render', {}).get('target_found'):
                errors.append('target_page_not_found')
        elif ext in OFFICE_RENDER_EXTS:
            pdf, convert_diag = convert_office_to_pdf(src, outdir)
            diagnostics['office_pdf_conversion'] = convert_diag
            if pdf is not None:
                diagnostics['pdf_render'] = render_pdf_pages(pdf, outdir, rows, max_images, max_pages, target_query)
                if diagnostics.get('pdf_render', {}).get('target_terms') and not diagnostics.get('pdf_render', {}).get('target_found'):
                    errors.append('target_page_not_found')
            else:
                errors.append('office_pdf_convert_failed')
        else:
            errors.append('unsupported_extension:' + ext)
    except Exception as exc:
        errors.append(type(exc).__name__ + ': ' + str(exc))
    print(json.dumps({'ok': bool(rows), 'images': rows, 'errors': errors, 'diagnostics': diagnostics}, ensure_ascii=False))

if __name__ == '__main__':
    main()
'''
