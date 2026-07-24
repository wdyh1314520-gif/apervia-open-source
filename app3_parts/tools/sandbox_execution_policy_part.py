# Centralized sandbox execution policy.
# Purpose: keep code execution as a deliberate tool, not a fallback/probe path for
# Office reading or artifact creation.

import os
import re

SANDBOX_EXECUTION_POLICY_VERSION = 'sandbox_execution_policy_v1_0606'

RUN_STRONG_RE = re.compile(r'(运行|执行|跑一下|测试|调试|报错|pytest|npm|node|python|bash|shell|命令|脚本|grep|find|统计|计算|校验|验证|build|compile|lint|test|execute|run|compute|debug)', re.I)
OFFICE_PROBE_RE = re.compile(r'(import\s+(openpyxl|pandas|xlsxwriter|docx|pptx)|from\s+(openpyxl|pandas|xlsxwriter|docx|pptx)\s+import|load_workbook|read_excel|ExcelFile|\.xlsx|\.xls\b)', re.I)
VERSION_ONLY_RE = re.compile(r'(__version__|pip\s+show|python\s+-V|python3\s+-V|importlib\.metadata\.version|print\s*\([^\n]{0,80}version)', re.I)
ARTIFACT_WORD_RE = re.compile(r'(生成|创建|做成|导出|保存|发布|下载|完善|修改|改成|补全|整理成|新版|最终版|Excel|xlsx|Word|docx|PPT|pptx|PDF|文件)', re.I)
READ_WORD_RE = re.compile(r'(看看|这个怎么样|分析|审阅|评价|读取|内容|清单|表格|数据)', re.I)


def _sandbox_exec_text_from_args(args: dict | None = None) -> str:
    row = dict(args or {}) if isinstance(args, dict) else {}
    parts = [str(row.get('command') or ''), str(row.get('code') or ''), str(row.get('stdin') or ''), str(row.get('stdin_text') or '')]
    argv = row.get('argv')
    if isinstance(argv, list):
        parts.append(' '.join(str(x) for x in argv))
    return '\n'.join(x for x in parts if x)


class SandboxExecutionPolicy:
    def decide(self, *, args: dict | None = None, messages=None, user_text: str = '') -> dict:
        exec_text = _sandbox_exec_text_from_args(args)
        latest = str(user_text or '').strip() or _tir_latest_user_text(messages)
        task = {}
        fn = globals().get('task_intent_route')
        if callable(fn):
            try:
                task = dict(fn(latest, messages=messages))
            except Exception:
                task = {}
        artifact_plan = {}
        ap = globals().get('artifact_task_plan')
        if callable(ap):
            try:
                artifact_plan = dict(ap(latest, output_path='', messages=messages))
            except Exception:
                artifact_plan = {}

        office_probe = bool(OFFICE_PROBE_RE.search(exec_text))
        version_only = bool(VERSION_ONLY_RE.search(exec_text))
        strong_run = bool(RUN_STRONG_RE.search(latest))
        artifact_task = bool(artifact_plan.get('is_artifact_task') or task.get('needs_artifact') or ARTIFACT_WORD_RE.search(latest))
        ordinary_file_read = bool(READ_WORD_RE.search(latest)) and not strong_run

        if office_probe and version_only and not re.search(r'(版本|version|环境|依赖|库|openpyxl|pandas)', latest, re.I):
            return {
                'version': SANDBOX_EXECUTION_POLICY_VERSION,
                'allow': False,
                'skip_as_success': True,
                'reason': 'dependency_probe_not_needed',
                'replacement_tool': 'sandbox_create_office_file' if artifact_task else 'sandbox_read_file',
                'instruction': '不要为普通 Office/表格任务先探测 openpyxl/pandas 版本。需要生成文件直接用 sandbox_create_office_file；需要读表格直接用 sandbox_read_file。',
            }
        if office_probe and artifact_task and not strong_run:
            return {
                'version': SANDBOX_EXECUTION_POLICY_VERSION,
                'allow': False,
                'skip_as_success': True,
                'reason': 'artifact_task_should_not_start_with_office_code',
                'replacement_tool': 'sandbox_create_office_file',
                'instruction': '这是文件产物任务，首选 sandbox_create_office_file 生成并自动发布；只有明确要求复杂代码生成/验证时才运行 Python。',
            }
        if office_probe and ordinary_file_read:
            return {
                'version': SANDBOX_EXECUTION_POLICY_VERSION,
                'allow': False,
                'skip_as_success': True,
                'reason': 'office_first_read_should_use_reader',
                'replacement_tool': 'sandbox_read_file',
                'instruction': '这是普通 Office/表格读取或审阅，先用 sandbox_read_file；不要用 openpyxl/pandas 作为首读入口。',
            }
        return {
            'version': SANDBOX_EXECUTION_POLICY_VERSION,
            'allow': True,
            'skip_as_success': False,
            'reason': 'explicit_or_allowed_execution',
            'replacement_tool': '',
            'instruction': 'sandbox_run allowed by centralized execution policy.',
        }


def sandbox_execution_decision(args: dict | None = None, messages=None, user_text: str = '') -> dict:
    return SandboxExecutionPolicy().decide(args=args, messages=messages, user_text=user_text)


def sandbox_execution_policy_prompt() -> str:
    return (
        '代码运行统一由 SandboxExecutionPolicy 控制：sandbox_run 只用于明确执行、测试、调试、grep/find、复杂统计/校验或确需代码生成。'
        '生成 .py/.js/.ts/.c/.cpp 等源码产物属于确需代码生成，必须通过 sandbox_run 写入 /mnt/data 并保留执行记录；普通 Office/表格读取用 sandbox_read_file，普通 Office/PDF/Excel 产物生成用 sandbox_create_office_file；不要先跑依赖/版本探测。'
    )
