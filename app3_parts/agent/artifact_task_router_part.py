# Auto-split helper: centralized artifact task routing and manager-facing policy.
# Purpose: all file generation/update/export tasks use one artifact route instead
# of drifting through sandbox_run probes, legacy generators, and publish prompts.

import os
import re
from dataclasses import dataclass, asdict

ARTIFACT_TASK_ROUTER_VERSION = 'artifact_task_router_v1_0606'
ARTIFACT_SUPPORTED_FORMATS = {'docx', 'xlsx', 'pptx', 'pdf', 'html', 'rtf', 'csv', 'md', 'zip'}
ARTIFACT_OFFICE_FORMATS = {'docx', 'xlsx', 'pptx', 'pdf', 'html', 'rtf', 'csv', 'md'}
ARTIFACT_FORMAT_WORDS = {
    'excel': 'xlsx', 'xlsx': 'xlsx', 'xls': 'xlsx', '表格': 'xlsx', '工作簿': 'xlsx',
    'word': 'docx', 'docx': 'docx', '文档': 'docx',
    'ppt': 'pptx', 'pptx': 'pptx', '幻灯片': 'pptx',
    'pdf': 'pdf', 'csv': 'csv', 'markdown': 'md', 'md': 'md', 'html': 'html', 'zip': 'zip', '压缩包': 'zip',
}
ARTIFACT_ACTION_RE = re.compile(r'(生成|创建|做成|导出|保存|发布|下载|打包|压缩|完善|优化|修改|改成|补全|整理成|转换成|另存为|新版|最终版|成品|交付|发我)', re.I)


def _artifact_short(value, limit=500):
    text = str(value or '').strip()
    return text if len(text) <= limit else text[:limit] + '…'


def _artifact_guess_format(text: str = '', filename: str = '', explicit: str = '') -> str:
    raw = str(explicit or '').strip().lower().lstrip('.')
    if raw == 'markdown':
        raw = 'md'
    if raw in ARTIFACT_SUPPORTED_FORMATS:
        return raw
    ext = os.path.splitext(str(filename or '').strip())[1].lower().lstrip('.')
    if ext == 'markdown':
        ext = 'md'
    if ext in ARTIFACT_SUPPORTED_FORMATS:
        return ext
    lowered = str(text or '').lower()
    for word, fmt in ARTIFACT_FORMAT_WORDS.items():
        if word.lower() in lowered or word in str(text or ''):
            return fmt
    return ''


@dataclass(frozen=True)
class ArtifactPlan:
    version: str
    is_artifact_task: bool
    action: str
    target_format: str
    primary_tool: str
    required_sequence: list[str]
    blocked_tools: list[str]
    auto_publish: bool
    reason: str
    prompt: str

    def to_dict(self) -> dict:
        return asdict(self)


class ArtifactTaskRouter:
    def plan(self, *, text: str = '', target_format: str = '', output_path: str = '', source_files=None, messages=None) -> ArtifactPlan:
        user_text = str(text or '').strip() or _tir_latest_user_text(messages)
        fmt = _artifact_guess_format(user_text, output_path, target_format)
        route_fn = globals().get('task_intent_route')
        task = {}
        if callable(route_fn):
            try:
                task = dict(route_fn(user_text, files=source_files, messages=messages))
            except Exception:
                task = {}
        is_task = bool(task.get('needs_artifact')) or bool(ARTIFACT_ACTION_RE.search(user_text) and (fmt or output_path))
        action = 'none'
        if is_task:
            action = 'update' if re.search(r'(完善|优化|修改|改成|补全|新版|最终版|基于|根据|从这个|原文件)', user_text) else 'create'
        primary = 'sandbox_create_office_file' if fmt in ARTIFACT_OFFICE_FORMATS else 'sandbox_write_files' if fmt == 'zip' else 'sandbox_write_file'
        sequence = ['sandbox_import_files', 'sandbox_read_file', primary, 'sandbox_publish_files'] if action == 'update' else [primary, 'sandbox_publish_files']
        blocked = ['sandbox_run_dependency_probe', 'retired_file_generator', 'host_shell'] if is_task else []
        return ArtifactPlan(
            version=ARTIFACT_TASK_ROUTER_VERSION,
            is_artifact_task=is_task,
            action=action,
            target_format=fmt,
            primary_tool=primary if is_task else '',
            required_sequence=sequence if is_task else [],
            blocked_tools=blocked,
            auto_publish=bool(is_task and fmt in ARTIFACT_OFFICE_FORMATS),
            reason='artifact_route' if is_task else 'not_artifact_task',
            prompt=artifact_task_policy_prompt(),
        )


def artifact_task_plan(text: str = '', target_format: str = '', output_path: str = '', source_files=None, messages=None) -> dict:
    return ArtifactTaskRouter().plan(text=text, target_format=target_format, output_path=output_path, source_files=source_files, messages=messages).to_dict()


def artifact_task_is_artifact_request(text: str = '', target_format: str = '', output_path: str = '', source_files=None, messages=None) -> bool:
    return bool(artifact_task_plan(text=text, target_format=target_format, output_path=output_path, source_files=source_files, messages=messages).get('is_artifact_task'))


def artifact_task_policy_prompt() -> str:
    return (
        '文件产物统一走 ArtifactTaskRouter：需要生成/完善/修改/导出/发布文件时，先读原文件证据，'
        '再用 sandbox_create_office_file（Office/PDF/CSV/MD/HTML）或写文件工具生成普通文件；.py/.js/.ts/.c/.cpp 等源码产物必须用 sandbox_run 在 Docker 内生成并保留 code/stdout/stderr，随后必须 sandbox_publish_files 发布。'
        '不要先用 sandbox_run 探测 openpyxl/pandas/版本；不要让模型回复“你再说链接我再发”。生成成功后应自动发布并在最终回答直接给下载文件。'
    )
