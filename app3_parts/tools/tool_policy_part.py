# Unified tool policy across task, evidence, web, execution and artifact routes.
# Purpose: avoid exposing every tool as equally valid at every step while keeping GPT-like dynamic tool use.

from __future__ import annotations

from dataclasses import dataclass, asdict

TOOL_POLICY_VERSION = 'tool_policy_v2_0717'

TOOL_POLICY_RUNTIME_PROMPT = (
    '统一工具策略：普通聊天直接答；只有需要证据、执行或文件交付才调用工具。'
    '文件先导入 sandbox /mnt/data；读文本/表格/Office 内容用 sandbox_read_file，图表/扫描/版式/截图才补 sandbox_analyze_file_images；'
    'diff 先 sandbox_resolve_file_context 再 sandbox_diff_files；执行/测试/grep/find/复杂统计才用 sandbox_run。'
    '普通 Office/PDF/表格产物用 sandbox_create_office_file，普通文本用 write/replace；生成 .py/.js/.ts/.c/.cpp 等源码文件时必须用 sandbox_run 在 Docker 内运行代码写入 /mnt/data，保留真实 code/stdout/stderr 记录，再用 sandbox_publish_files 发布。'
    '联网用于最新/官方/外部事实；search 只是候选，fetch 后才可引用。'
    '证据按网页、文件文本、视觉、运行结果、产物发布分类型使用，不能互相冒充。'
)


def tool_policy_runtime_prompt() -> str:
    """Compact runtime policy shared by Chat and Responses tool loops."""
    return TOOL_POLICY_RUNTIME_PROMPT


def _tp_task_intent(text: str = '', files=None, messages=None) -> dict:
    fn = globals().get('task_intent_route')
    if callable(fn):
        try:
            return dict(fn(text=text, files=files, messages=messages))
        except Exception as exc:
            return {'kind': 'general_chat', 'error': f'{type(exc).__name__}: {exc}'}
    return {'kind': 'general_chat'}


def _tp_agent_plan(text: str = '', files=None, messages=None, task_intent=None) -> dict:
    fn = globals().get('agent_loop_plan')
    if callable(fn):
        try:
            return dict(fn(text=text, files=files, messages=messages, task_intent=task_intent))
        except Exception as exc:
            return {'version': 'agent_loop_error', 'allowed_tools': [], 'blocked_first_tools': [], 'error': f'{type(exc).__name__}: {exc}'}
    return {'version': 'agent_loop_missing', 'allowed_tools': [], 'blocked_first_tools': []}


@dataclass(frozen=True)
class ToolPolicyPlan:
    version: str
    task_kind: str
    allowed_tools: list[str]
    blocked_first_tools: list[str]
    dynamic_research: bool
    schema_mode: str
    evidence_required: bool
    reason: str
    instruction: str

    def to_dict(self) -> dict:
        return asdict(self)


class ToolPolicy:
    def plan(self, *, text: str = '', files=None, messages=None) -> ToolPolicyPlan:
        intent = _tp_task_intent(text=text, files=files, messages=messages)
        loop = _tp_agent_plan(text=text, files=files, messages=messages, task_intent=intent)
        allowed = [str(x) for x in (loop.get('allowed_tools') or []) if str(x).strip()]
        blocked = [str(x) for x in (loop.get('blocked_first_tools') or []) if str(x).strip()]
        kind = str(intent.get('kind') or loop.get('task_kind') or 'general_chat')
        instruction = (
            'Expose tools by task boundary, not by scattered if rules. Tool calls should use structured arguments; '
            'tool outputs must be fed back to the model, which may then request more tools or finalize. '
            'Do not use sandbox_run as a generic probe when file/artifact routes have a dedicated tool.'
        )
        return ToolPolicyPlan(
            version=TOOL_POLICY_VERSION,
            task_kind=kind,
            allowed_tools=allowed,
            blocked_first_tools=blocked,
            dynamic_research=bool(loop.get('dynamic_research')),
            schema_mode='strict_like_required_fields',
            evidence_required=kind in {'file_read', 'file_diff', 'visual_review', 'web_search', 'artifact_create', 'artifact_update', 'code_run'},
            reason=str(loop.get('reason') or intent.get('reason') or ''),
            instruction=instruction,
        )


def tool_policy_plan(text: str = '', files=None, messages=None) -> dict:
    return ToolPolicy().plan(text=text, files=files, messages=messages).to_dict()


def tool_policy_prompt() -> str:
    return TOOL_POLICY_RUNTIME_PROMPT
