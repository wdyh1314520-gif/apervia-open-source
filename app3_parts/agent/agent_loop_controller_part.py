# Official-style dynamic agent loop controller.
# Purpose: keep GPT-like multi-step tool use flexible while bounding it with
# stable policy. The router only sets boundaries; the model may still search,
# read files, inspect visuals, run code, and generate artifacts mid-task when
# evidence says it is needed.

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

AGENT_LOOP_CONTROLLER_VERSION = 'agent_loop_controller_v3_0721'

_SOURCE_CODE_ARTIFACT_EXTS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.c', '.h', '.cpp', '.cc', '.cxx',
    '.hpp', '.java', '.go', '.rs', '.rb', '.php', '.sh', '.bash', '.ps1', '.sql',
}

_DYNAMIC_RESEARCH_RE = re.compile(
    r'(最新|现在|当前|官方|官网|资料|查资料|联网|搜索|核验|验证来源|引用|出处|标准|规范|政策|价格|版本|发布日期|recent|current|official|source|citation|verify|research|web)',
    re.I,
)
_ARTIFACT_RESEARCH_RE = re.compile(
    r'(根据.*(最新|官方|资料|官网|网页|链接|标准|政策)|查.*(资料|官网|官方|最新).*?(生成|完善|修改|整理|做成|导出)|research.*?(file|excel|sheet|doc|ppt|pdf))',
    re.I,
)


def _alc_short(value, limit=700):
    text = str(value or '').strip()
    return text if len(text) <= limit else text[:limit] + '…'


def _alc_call_task_intent(text: str = '', files=None, messages=None) -> dict:
    fn = globals().get('task_intent_route')
    if callable(fn):
        try:
            return dict(fn(text=text, files=files, messages=messages))
        except Exception as exc:
            return {'version': 'task_intent_error', 'kind': 'general_chat', 'error': f'{type(exc).__name__}: {exc}', 'user_text': _alc_short(text)}
    return {'version': 'task_intent_missing', 'kind': 'general_chat', 'user_text': _alc_short(text)}


@dataclass(frozen=True)
class AgentLoopPlan:
    version: str
    task_kind: str
    dynamic_research: bool
    allowed_tools: list[str]
    blocked_first_tools: list[str]
    required_state: list[str]
    stop_when: list[str]
    reason: str
    instruction: str

    def to_dict(self) -> dict:
        return asdict(self)


class AgentLoopController:
    """Official-style loop boundary, not a rigid workflow.

    The model can request more tools after seeing outputs, matching the OpenAI
    tool-call flow where the final response can be replaced by more tool calls.
    This controller only decides which families are allowed and what state must
    be accumulated before final delivery.
    """

    def plan(self, *, text: str = '', files=None, messages=None, task_intent: dict | None = None) -> AgentLoopPlan:
        intent = dict(task_intent or _alc_call_task_intent(text=text, files=files, messages=messages))
        kind = str(intent.get('kind') or 'general_chat')
        user_text = str(text or intent.get('user_text') or '')
        target_formats = {str(x or '').strip().lower() for x in (intent.get('target_formats') or [])}
        source_code_artifact = bool(target_formats & _SOURCE_CODE_ARTIFACT_EXTS)
        needs_dynamic_research = bool(intent.get('needs_web')) or bool(_DYNAMIC_RESEARCH_RE.search(user_text))
        if kind in {'artifact_create', 'artifact_update'} and _ARTIFACT_RESEARCH_RE.search(user_text):
            needs_dynamic_research = True

        allowed = []
        blocked = []
        required = []
        stop_when = []
        reason = 'general_chat_minimal_tools'
        if kind in {'artifact_create', 'artifact_update'}:
            allowed = [
                'sandbox_import_files', 'sandbox_read_file', 'sandbox_analyze_file_images',
                'web_search', 'fetch_url', 'fetch_urls',
                'sandbox_create_office_file', 'sandbox_write_file', 'sandbox_write_files', 'sandbox_replace_text',
                'sandbox_run', 'sandbox_publish_files',
            ]
            blocked = [] if source_code_artifact else ['sandbox_run']
            required = ['file_evidence_if_user_supplied_files', 'artifact_generated', 'artifact_published']
            if source_code_artifact:
                required.append('execution_result')
            stop_when = ['final_answer_has_download_url_or_published_files', 'missing_evidence_disclosed']
            reason = 'source_code_artifact_execute_then_publish' if source_code_artifact else 'artifact_task_dynamic_evidence_then_publish'
        elif kind == 'file_diff':
            allowed = ['sandbox_import_files', 'sandbox_resolve_file_context', 'sandbox_diff_files', 'sandbox_read_file', 'sandbox_publish_files']
            blocked = ['sandbox_run']
            required = ['file_context', 'diff_result']
            stop_when = ['diff_answered_or_file_published', 'ambiguous_pair_asks_user_to_choose']
            reason = 'file_diff_context_then_diff_router'
        elif kind == 'file_read':
            allowed = ['sandbox_import_files', 'sandbox_read_file', 'sandbox_analyze_file_images']
            blocked = ['sandbox_run']
            required = ['file_evidence']
            stop_when = ['question_answered_from_evidence']
            reason = 'file_evidence_task'
        elif kind == 'visual_review':
            allowed = ['sandbox_import_files', 'sandbox_read_file', 'sandbox_analyze_file_images']
            blocked = ['sandbox_run']
            required = ['text_evidence_when_available', 'visual_evidence']
            stop_when = ['visual_question_answered']
            reason = 'visual_evidence_task'
        elif kind == 'code_run':
            allowed = ['sandbox_import_files', 'sandbox_read_file', 'sandbox_run', 'sandbox_publish_files', 'sandbox_write_file', 'sandbox_write_files']
            blocked = []
            required = ['execution_result']
            stop_when = ['execution_succeeded_or_failure_explained']
            reason = 'explicit_execution_task'
        elif kind == 'web_search' or needs_dynamic_research:
            allowed = ['web_search', 'fetch_url', 'fetch_urls']
            blocked = []
            required = ['web_evidence']
            stop_when = ['answer_has_sources_or_uncertainty']
            reason = 'web_evidence_task'
        else:
            allowed = []
            blocked = []
            required = []
            stop_when = ['direct_answer_ok']

        instruction = (
            'Use a dynamic agent loop: after every tool result, decide whether evidence is sufficient, '
            'whether another web/file/visual/code tool is needed, or whether to finalize. Do not pre-collect once and lock the flow. '
            'Every evidence-producing tool result should be treated as an append-only ledger item. For artifact tasks, generate/publish only after enough evidence has been collected, but continue searching mid-task when a gap appears.'
        )
        return AgentLoopPlan(
            version=AGENT_LOOP_CONTROLLER_VERSION,
            task_kind=kind,
            dynamic_research=bool(needs_dynamic_research),
            allowed_tools=allowed,
            blocked_first_tools=blocked,
            required_state=required,
            stop_when=stop_when,
            reason=reason,
            instruction=instruction,
        )


def agent_loop_plan(text: str = '', files=None, messages=None, task_intent: dict | None = None) -> dict:
    return AgentLoopController().plan(text=text, files=files, messages=messages, task_intent=task_intent).to_dict()


def agent_tool_round_indices():
    """Yield tool round numbers until the model finalizes or the user stops."""
    round_index = 1
    while True:
        yield round_index
        round_index += 1


def agent_loop_policy_prompt() -> str:
    return (
        'Agent loop 对齐官方工具调用：不是一次性收集证据，而是每轮工具结果后继续判断是否需要更多工具。'
        'Router 只定边界，不锁死流程；模型可在读文件、查网页、看视觉、生成文件之间动态切换。'
        '所有证据进入 EvidenceLedger；搜索结果只是候选，fetch_url/fetch_urls 读取过的网页才作为可引用来源；'
        'artifact 任务必须在生成后由 ArtifactManager 发布真实下载链接，不让用户再回复“链接”；diff 任务先用 FileContextResolver，再用 FileDiffRouter，不用 shell 扫目录猜。'
    )
