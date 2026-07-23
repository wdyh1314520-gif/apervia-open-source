# Auto-split helper: centralized file evidence routing policy.
# Purpose: keep text-vs-visual-vs-execution decisions in one place so file Q&A
# does not drift into scattered prompt patches.
# Loaded by app3.py before file_registry_edit_tools_part.py and chat_streaming_part.py.

import os
import re

FILE_EVIDENCE_POLICY_VERSION = 'file_evidence_policy_v1_0606'

FILE_EVIDENCE_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff'}
FILE_EVIDENCE_SPREADSHEET_EXTS = {'.xlsx', '.xls', '.csv', '.tsv'}
FILE_EVIDENCE_OFFICE_DOC_EXTS = {'.pdf', '.doc', '.docx', '.ppt', '.pptx'}
FILE_EVIDENCE_TEXT_EXTS = {
    '.txt', '.md', '.markdown', '.json', '.jsonl', '.csv', '.tsv', '.xml', '.html', '.htm', '.css', '.js', '.ts', '.tsx',
    '.py', '.java', '.go', '.rs', '.c', '.cpp', '.h', '.hpp', '.sh', '.ps1', '.bat', '.yml', '.yaml', '.toml', '.ini',
    '.conf', '.log', '.sql'
}
FILE_EVIDENCE_ARCHIVE_EXTS = {'.zip', '.tar', '.tgz', '.gz', '.7z', '.rar'}

# Visual means evidence that must be seen as pixels/page rendering, not just text cells.
FILE_EVIDENCE_VISUAL_RE = re.compile(
    r'(图表|chart|可视化|截图|图片|照片|扫描|版式|布局|打印|分页|页面|渲染|视觉|看起来|外观|颜色|背景|边框|字体|字号|列宽|行高|合并单元格|merged|format|style|layout|visual|image|screenshot|scan|render)',
    re.I,
)
FILE_EVIDENCE_TARGET_RE = re.compile(
    r'((图|表)\s*[0-9一二三四五六七八九十]+|(?:Figure|Fig\.?|Table)\s*[0-9]+|第\s*[0-9一二三四五六七八九十]+\s*(页|张图|幅图|个图|个表)|page\s*[0-9]+)',
    re.I,
)
FILE_EVIDENCE_BROAD_REVIEW_RE = re.compile(
    r'(怎么样|写得|评价|评估|审阅|检查|看看|整体|论文|报告|初稿|质量|问题|不足|建议|打分|能不能交|专业|规范|格式|逻辑)',
    re.I,
)
FILE_EVIDENCE_RUN_RE = re.compile(
    r'(运行|执行|跑一下|测试|单元测试|pytest|npm|node|python|bash|脚本|命令|grep|find|搜索文件|统计|计算|校验|验证|生成|导出|转换|修改|替换|安装依赖|build|compile|lint|test|execute|run|compute)',
    re.I,
)


def _file_evidence_short(value, limit=260):
    text = str(value or '').strip()
    if len(text) <= limit:
        return text
    return text[:limit] + '…'


def file_evidence_ext(filename: str = '', ext: str = '') -> str:
    value = str(ext or '').strip().lower()
    if value and not value.startswith('.'):
        value = '.' + value
    if value:
        return value
    return os.path.splitext(str(filename or '').strip())[1].lower()


def file_evidence_kind(filename: str = '', ext: str = '') -> str:
    ext_l = file_evidence_ext(filename, ext)
    if ext_l in FILE_EVIDENCE_IMAGE_EXTS:
        return 'image'
    if ext_l in FILE_EVIDENCE_SPREADSHEET_EXTS:
        return 'spreadsheet'
    if ext_l in FILE_EVIDENCE_OFFICE_DOC_EXTS:
        return 'office_document'
    if ext_l in FILE_EVIDENCE_ARCHIVE_EXTS:
        return 'archive'
    if ext_l in FILE_EVIDENCE_TEXT_EXTS:
        return 'text_or_code'
    return 'other'


def file_evidence_intent(query: str = '', target: str = '') -> dict:
    text = ' '.join([str(target or ''), str(query or '')]).strip()
    explicit_visual = bool(FILE_EVIDENCE_VISUAL_RE.search(text)) if text else False
    explicit_target = bool(FILE_EVIDENCE_TARGET_RE.search(text)) if text else False
    broad_review = bool(FILE_EVIDENCE_BROAD_REVIEW_RE.search(text)) if text else False
    execution = bool(FILE_EVIDENCE_RUN_RE.search(text)) if text else False
    return {
        'text': _file_evidence_short(text),
        'explicit_visual': explicit_visual,
        'explicit_target': explicit_target,
        'broad_review': broad_review,
        'execution': execution,
    }


def file_evidence_policy_prompt() -> str:
    return (
        '文件证据按统一策略选择，不按单个案例硬补：先判断文件类型与用户意图，再选证据通道。'
        '纯图片文件直接用视觉；XLSX/CSV/TSV 的单元格/数据/清单/表格内容问题先用 sandbox_read_file 读取结构化文本，'
        '不要把普通“看看/这个怎么样”当作渲染页面图片的理由；只有明确问图表、截图、版式、颜色、列宽行高、合并单元格、打印分页或指定图/表/页时才补 sandbox_analyze_file_images。'
        'PDF/DOCX/PPTX 先读文本层；当文本层不足、扫描页、公式/图表/截图/版式相关或整体文档审阅确实依赖页面观感时，再补视觉证据。'
        'sandbox_run 只用于真实执行/测试/grep/find/复杂统计校验/生成产物，不作为 Office/表格首读工具。'
        '最终回答必须说明依据来自文本、视觉还是运行结果；不要用一个通道冒充另一个通道。'
    )


def file_evidence_plan(filename: str = '', ext: str = '', query: str = '', target: str = '', diagnostics: dict | None = None) -> dict:
    ext_l = file_evidence_ext(filename, ext)
    kind = file_evidence_kind(filename, ext_l)
    intent = file_evidence_intent(query, target)
    explicit_visual = bool(intent.get('explicit_visual') or intent.get('explicit_target'))
    broad_review = bool(intent.get('broad_review'))
    execution = bool(intent.get('execution'))
    diag = diagnostics if isinstance(diagnostics, dict) else {}
    requires_visual = bool(diag.get('requires_visual_review') or diag.get('media_count') or diag.get('drawing_count') or diag.get('office_math_count'))

    primary_tool = 'sandbox_read_file'
    secondary_tools: list[str] = []
    blocked_first_tools: list[str] = []
    allow_visual = False
    allow_run_first = False
    reason = 'text_first'

    if kind == 'image':
        primary_tool = 'sandbox_analyze_file_images'
        allow_visual = True
        allow_run_first = False
        reason = 'direct_image_visual_first'
    elif kind == 'spreadsheet':
        primary_tool = 'sandbox_read_file'
        allow_visual = bool(explicit_visual)
        allow_run_first = bool(execution and not broad_review)
        if allow_visual:
            secondary_tools.append('sandbox_analyze_file_images')
            reason = 'spreadsheet_visual_explicit'
        else:
            blocked_first_tools.append('sandbox_analyze_file_images')
            reason = 'spreadsheet_structured_text_first'
        if allow_run_first:
            secondary_tools.append('sandbox_run')
        else:
            blocked_first_tools.append('sandbox_run')
    elif kind == 'office_document':
        primary_tool = 'sandbox_read_file'
        allow_visual = bool(explicit_visual or requires_visual or broad_review)
        allow_run_first = bool(execution)
        if allow_visual:
            secondary_tools.append('sandbox_analyze_file_images')
            reason = 'office_text_first_visual_when_needed'
        else:
            reason = 'office_text_first'
        if allow_run_first:
            secondary_tools.append('sandbox_run')
        else:
            blocked_first_tools.append('sandbox_run')
    elif kind == 'archive':
        primary_tool = 'sandbox_run'
        allow_visual = False
        allow_run_first = bool(execution)
        secondary_tools.append('sandbox_run')
        reason = 'archive_inspect_or_extract_first'
    elif kind == 'text_or_code':
        primary_tool = 'sandbox_read_file'
        allow_visual = False
        allow_run_first = bool(execution)
        if allow_run_first:
            secondary_tools.append('sandbox_run')
            reason = 'code_or_text_execution_requested'
        else:
            blocked_first_tools.append('sandbox_run')
            reason = 'text_read_first'
    else:
        primary_tool = 'sandbox_read_file'
        allow_visual = bool(explicit_visual)
        allow_run_first = bool(execution)
        if allow_visual:
            secondary_tools.append('sandbox_analyze_file_images')
        if allow_run_first:
            secondary_tools.append('sandbox_run')
        reason = 'unknown_file_text_first'

    # Keep ordering stable and deduplicated.
    seen = set()
    secondary_tools = [x for x in secondary_tools if not (x in seen or seen.add(x))]
    blocked_first_tools = [x for x in blocked_first_tools if x != primary_tool]

    return {
        'version': FILE_EVIDENCE_POLICY_VERSION,
        'filename': _file_evidence_short(filename, 220),
        'ext': ext_l,
        'kind': kind,
        'intent': intent,
        'primary_tool': primary_tool,
        'secondary_tools': secondary_tools,
        'blocked_first_tools': blocked_first_tools,
        'allow_visual': bool(allow_visual),
        'allow_run_first': bool(allow_run_first),
        'requires_visual_from_diagnostics': bool(requires_visual),
        'reason': reason,
        'prompt': file_evidence_policy_prompt(),
    }


def file_evidence_should_allow_visual(filename: str = '', ext: str = '', query: str = '', target: str = '', diagnostics: dict | None = None) -> bool:
    return bool(file_evidence_plan(filename=filename, ext=ext, query=query, target=target, diagnostics=diagnostics).get('allow_visual'))


def file_evidence_should_allow_run_first(filename: str = '', ext: str = '', query: str = '', target: str = '', diagnostics: dict | None = None) -> bool:
    return bool(file_evidence_plan(filename=filename, ext=ext, query=query, target=target, diagnostics=diagnostics).get('allow_run_first'))
