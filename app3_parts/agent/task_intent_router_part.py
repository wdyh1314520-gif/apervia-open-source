# Auto-split helper: centralized task intent routing.
# Purpose: avoid one-off prompt/tool patches by routing each user turn into a
# stable task class before evidence, execution, artifact and activity policies run.
# Loaded by app3.py before file/tool execution modules.

import os
import re
from dataclasses import dataclass, asdict

TASK_INTENT_ROUTER_VERSION = 'task_intent_router_v2_0717'

SOURCE_CODE_FORMAT_EXTS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.c', '.h', '.cpp', '.cc', '.cxx',
    '.hpp', '.java', '.go', '.rs', '.rb', '.php', '.sh', '.bash', '.ps1', '.sql',
}
ARTIFACT_FORMAT_EXTS = {'.docx', '.xlsx', '.pptx', '.pdf', '.html', '.rtf', '.csv', '.md', '.zip'} | SOURCE_CODE_FORMAT_EXTS
ARTIFACT_FORMAT_RE = re.compile(r'(xlsx|excel|表格|工作簿|docx|word|文档|pptx|ppt|幻灯片|pdf|csv|md|markdown|zip|压缩包|python\s*文件|py\s*文件|javascript\s*文件|typescript\s*文件|c\s*语言文件|源码文件|代码文件|下载链接|下载|导出|保存成|生成文件|做成文件|发我文件|发文件给我)', re.I)
ARTIFACT_ACTION_RE = re.compile(r'(生成|创建|做一个|做成|导出|保存|发布|下载|打包|压缩|完善|优化|修改|改成|改一下|补全|整理成|转换成|另存为|新版|最终版|成品|交付|发我|发文件给我|发给我)', re.I)
CODE_RUN_RE = re.compile(r'(运行|执行|跑一下|测试|pytest|npm|node|python|bash|shell|命令|脚本|编译|构建|lint|grep|find|日志|报错|traceback|unit test|run|execute|test|build|compile)', re.I)
VISUAL_RE = re.compile(r'(图片|图像|截图|照片|视觉|看起来|版式|布局|页面|分页|打印|颜色|字体|字号|边框|背景|图表|chart|diagram|screenshot|image|visual|layout|render)', re.I)
WEB_RE = re.compile(r'(联网|搜索|查资料|最新|现在|官网|官方|链接|网页|url|http://|https://|价格|新闻|发布时间|当前|verify|search)', re.I)
FILE_DIFF_RE = re.compile(r'(diff|差异|对比|比较|变更|修改点|看.*改了什么|compare|comparison)', re.I)
FILE_READ_RE = re.compile(r'(看看|分析|总结|评价|审阅|检查|读取|里面|这个怎么样|文件|表格|文档|内容|清单|数据|第几行|sheet)', re.I)
MEMORY_ACTION_RE = re.compile(
    r'((请|帮我|给我|替我)?(记住|记一下|保存到记忆|加入记忆|写进记忆|以后记得|记得我)|'
    r'(忘记|别记|不要记|删除|清除|移除|更新|修改).{0,12}(记忆|偏好|个人信息)|'
    r'\b(remember|save|store|forget|delete|remove|update)\b.{0,24}\b(memory|preference|profile)\b)',
    re.I,
)
HISTORY_REFERENCE_RE = re.compile(
    r'(上次|之前|以前|历史对话|过去对话|之前聊|以前聊|接着上次|继续上次|找一下之前|查一下之前|'
    r'\b(previous|earlier|last time|past chat|chat history|continue from last)\b)',
    re.I,
)


def _tir_short(value, limit=500):
    text = str(value or '').strip()
    return text if len(text) <= limit else text[:limit] + '…'


def _tir_latest_user_text(messages=None) -> str:
    try:
        for msg in reversed(messages or []):
            if not isinstance(msg, dict):
                continue
            if str(msg.get('role') or '').lower() != 'user':
                continue
            content = msg.get('content')
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get('type') in {'text', 'input_text'}:
                            parts.append(str(item.get('text') or ''))
                        elif isinstance(item.get('text'), str):
                            parts.append(str(item.get('text') or ''))
                text = '\n'.join(x for x in parts if x.strip()).strip()
                if text:
                    return text
    except Exception:
        pass
    return ''


def _tir_file_exts(files=None) -> list[str]:
    exts = []
    try:
        rows = files or []
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            if isinstance(row, dict):
                name = str(row.get('filename') or row.get('name') or row.get('path') or row.get('target_filename') or '')
            else:
                name = str(row or '')
            ext = os.path.splitext(name)[1].lower()
            if ext and ext not in exts:
                exts.append(ext)
    except Exception:
        pass
    return exts


_TIR_CODE_FENCE_EXTS = {
    'python': '.py', 'py': '.py', 'javascript': '.js', 'js': '.js',
    'typescript': '.ts', 'ts': '.ts', 'jsx': '.jsx', 'tsx': '.tsx',
    'c': '.c', 'cpp': '.cpp', 'c++': '.cpp', 'java': '.java', 'go': '.go',
    'rust': '.rs', 'rs': '.rs', 'ruby': '.rb', 'rb': '.rb', 'php': '.php',
    'shell': '.sh', 'bash': '.sh', 'sh': '.sh', 'powershell': '.ps1',
    'sql': '.sql',
}


def _tir_message_text(message) -> str:
    if not isinstance(message, dict):
        return ''
    content = message.get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and str(item.get('type') or '') in {'text', 'input_text', 'output_text'}:
                parts.append(str(item.get('text') or ''))
        return '\n'.join(x for x in parts if x.strip())
    return ''


def _tir_recent_source_code_ext(messages=None) -> str:
    for message in reversed(list(messages or [])[-12:]):
        if not isinstance(message, dict) or str(message.get('role') or '').lower() != 'assistant':
            continue
        text = _tir_message_text(message)
        fences = re.findall(r'```\s*([A-Za-z0-9_+.-]+)', text)
        for language in reversed(fences):
            ext = _TIR_CODE_FENCE_EXTS.get(str(language or '').strip().lower())
            if ext:
                return ext
    return ''


@dataclass(frozen=True)
class TaskIntent:
    version: str
    kind: str
    user_text: str
    target_formats: list[str]
    file_exts: list[str]
    needs_artifact: bool
    needs_execution: bool
    needs_visual: bool
    needs_web: bool
    dynamic_research: bool
    needs_file_evidence: bool
    confidence: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class TaskIntentRouter:
    """Small deterministic router; it does not replace the model, it bounds tools.

    The router is intentionally conservative: artifact/update requests are routed
    before code execution so Office/PDF generation cannot drift into dependency
    probes; explicit code/test/debug requests still route to code_run.
    """

    def route(self, *, text: str = '', files=None, messages=None) -> TaskIntent:
        user_text = str(text or '').strip() or _tir_latest_user_text(messages)
        exts = _tir_file_exts(files)
        lowered = user_text.lower()
        target_formats = []
        for ext in ARTIFACT_FORMAT_EXTS:
            token = ext.lstrip('.')
            if ext in lowered or re.search(rf'(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])', lowered):
                target_formats.append(ext)
        if 'excel' in lowered or '表格' in user_text or '工作簿' in user_text:
            if '.xlsx' not in target_formats:
                target_formats.append('.xlsx')
        if 'word' in lowered or '文档' in user_text:
            if '.docx' not in target_formats:
                target_formats.append('.docx')
        if 'ppt' in lowered or '幻灯片' in user_text:
            if '.pptx' not in target_formats:
                target_formats.append('.pptx')
        if 'pdf' in lowered and '.pdf' not in target_formats:
            target_formats.append('.pdf')
        explicit_code_formats = [
            (r'python\s*(?:文件|代码)|py\s*文件', '.py'),
            (r'javascript\s*(?:文件|代码)|js\s*文件', '.js'),
            (r'typescript\s*(?:文件|代码)|ts\s*文件', '.ts'),
            (r'c\s*语言(?:文件|代码)?', '.c'),
            (r'c\+\+\s*(?:文件|代码)?', '.cpp'),
        ]
        for pattern, ext in explicit_code_formats:
            if re.search(pattern, user_text, re.I) and ext not in target_formats:
                target_formats.append(ext)
        delivery_followup = bool(re.search(r'(发文件给我|发给我|发我文件|做成文件|保存成文件|给.*下载)', user_text, re.I))
        if delivery_followup and not any(ext in SOURCE_CODE_FORMAT_EXTS for ext in target_formats):
            recent_code_ext = _tir_recent_source_code_ext(messages)
            if recent_code_ext and recent_code_ext not in target_formats:
                target_formats.append(recent_code_ext)

        has_files = bool(exts)
        artifact_signal = bool(ARTIFACT_ACTION_RE.search(user_text) and (ARTIFACT_FORMAT_RE.search(user_text) or target_formats or has_files and re.search(r'(新版|完善|修改|改成|补全|整理成|导出|下载|发布|发我)', user_text)))
        execution_signal = bool(CODE_RUN_RE.search(user_text))
        visual_signal = bool(VISUAL_RE.search(user_text))
        web_signal = bool(WEB_RE.search(user_text))
        file_signal = bool(has_files or FILE_READ_RE.search(user_text))
        diff_signal = bool(FILE_DIFF_RE.search(user_text))

        dynamic_research_signal = bool(web_signal or re.search(r'(根据.*(最新|官方|资料|官网|网页|链接|标准|政策)|查.*(资料|官网|官方|最新).*?(生成|完善|修改|整理|做成|导出)|research.*?(file|excel|sheet|doc|ppt|pdf))', user_text, re.I))

        if diff_signal and (has_files or file_signal):
            kind = 'file_diff'
            reason = 'diff_or_compare_file_question'
            confidence = 0.84
        elif artifact_signal:
            kind = 'artifact_update' if has_files and re.search(r'(完善|修改|改成|补全|新版|最终版|基于|根据|从这个|原文件)', user_text) else 'artifact_create'
            reason = 'artifact_action_and_format_or_file'
            confidence = 0.86
        elif execution_signal and not artifact_signal:
            kind = 'code_run'
            reason = 'explicit_execution_or_debug'
            confidence = 0.80
        elif visual_signal and file_signal:
            kind = 'visual_review'
            reason = 'visual_file_question'
            confidence = 0.76
        elif file_signal:
            kind = 'file_read'
            reason = 'file_content_question'
            confidence = 0.72
        elif web_signal:
            kind = 'web_search'
            reason = 'external_current_or_url_question'
            confidence = 0.70
        else:
            kind = 'general_chat'
            reason = 'no_tool_required_by_router'
            confidence = 0.55

        source_code_artifact = kind in {'artifact_create', 'artifact_update'} and any(ext in SOURCE_CODE_FORMAT_EXTS for ext in target_formats)
        return TaskIntent(
            version=TASK_INTENT_ROUTER_VERSION,
            kind=kind,
            user_text=_tir_short(user_text),
            target_formats=target_formats[:8],
            file_exts=exts[:20],
            needs_artifact=kind in {'artifact_create', 'artifact_update'},
            needs_execution=kind == 'code_run' or source_code_artifact or (execution_signal and not artifact_signal),
            needs_visual=visual_signal or kind == 'visual_review',
            needs_web=bool(web_signal or dynamic_research_signal),
            dynamic_research=bool(dynamic_research_signal),
            needs_file_evidence=file_signal or kind in {'artifact_update', 'file_read', 'visual_review', 'file_diff'},
            confidence=confidence,
            reason=reason,
        )


def task_intent_route(text: str = '', files=None, messages=None) -> dict:
    return TaskIntentRouter().route(text=text, files=files, messages=messages).to_dict()


def task_capability_preselect(text: str = '', files=None, messages=None) -> dict:
    """统一生成首轮低风险能力提示；最终是否调用工具仍由主模型决定。"""
    user_text = str(text or '').strip() or _tir_latest_user_text(messages)
    task = task_intent_route(text=user_text, files=files, messages=messages)
    groups: list[str] = []
    reasons: list[str] = []

    if str(task.get('kind') or '') in {'artifact_create', 'artifact_update'}:
        groups.append('sandbox')
        reasons.append('file_create_or_export_intent')
    if MEMORY_ACTION_RE.search(user_text):
        groups.append('memory')
        reasons.append('explicit_memory_write_or_delete')
    if HISTORY_REFERENCE_RE.search(user_text):
        groups.append('history')
        reasons.append('explicit_history_reference')

    return {
        'version': TASK_INTENT_ROUTER_VERSION,
        'groups': list(dict.fromkeys(groups)),
        'reasons': list(dict.fromkeys(reasons)),
        'reason': ','.join(dict.fromkeys(reasons)),
        'task': task,
    }


def task_intent_policy_prompt() -> str:
    return (
        '任务先统一路由再选工具：file_read 只读证据；visual_review 才补视觉；file_diff 先解析文件上下文再对比；'
        'artifact_create/artifact_update 进入文件产物链路，先读取原证据；如果任务要求最新/官方/外部资料，允许中途 web_search/fetch_url 动态补证据；普通文档用 sandbox_create_office_file 或写文件工具，.py/.js/.ts/.c/.cpp 等源码产物必须用 sandbox_run 在 Docker 内生成并保留执行记录，随后发布；'
        'code_run 只处理明确运行/测试/调试/复杂计算，不作为 Office/表格首读或普通产物生成探测。'
    )
