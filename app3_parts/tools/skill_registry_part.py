# ====== skill / capability registry ======
# 目标：把工具所属能力、endpoint 可用性和短描述集中到一处。
# 说明：这里不执行工具，也不改变 Chat / Responses 协议；只提供产品级元数据。

import re
import time
import uuid
from dataclasses import dataclass, asdict


SKILL_REGISTRY_VERSION = 'skill_registry_v4_0710'


@dataclass(frozen=True)
class SkillToolSpec:
    name: str
    group: str
    modes: tuple[str, ...]
    description: str
    tool_kind: str = 'function'
    execution_plane: str = 'app3'
    handoff_target: str = ''

    def to_dict(self) -> dict:
        row = asdict(self)
        row['modes'] = list(self.modes)
        return row


@dataclass(frozen=True)
class SkillSpec:
    name: str
    title: str
    modes: tuple[str, ...]
    description: str
    tools: tuple[str, ...]
    requires: tuple[str, ...] = ()
    lifecycle: str = 'stable'
    activation: tuple[str, ...] = ()
    trace_events: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        row = asdict(self)
        row['modes'] = list(self.modes)
        row['tools'] = list(self.tools)
        row['requires'] = list(self.requires)
        row['activation'] = list(self.activation)
        row['trace_events'] = list(self.trace_events)
        return row


@dataclass(frozen=True)
class PublicSkillSpec:
    key: str
    title: str
    description: str
    modes: tuple[str, ...]
    groups: tuple[str, ...]
    hint: str = ''

    def to_dict(self) -> dict:
        row = asdict(self)
        row['modes'] = list(self.modes)
        row['groups'] = list(self.groups)
        return row


@dataclass(frozen=True)
class SkillRuntimePlan:
    mode: str
    requested_groups: tuple[str, ...]
    active_groups: tuple[str, ...]
    tools: tuple[str, ...]
    handoffs: tuple[str, ...]
    native_tools: tuple[str, ...]
    trace_events: tuple[str, ...]

    def to_dict(self) -> dict:
        row = asdict(self)
        for key in ('requested_groups', 'active_groups', 'tools', 'handoffs', 'native_tools', 'trace_events'):
            row[key] = list(row.get(key) or [])
        return row


@dataclass(frozen=True)
class PromptContractSpec:
    name: str
    purpose: str
    output: str
    schema: str = ''
    invariants: tuple[str, ...] = ()
    json_schema: dict | None = None
    strict: bool = True

    def to_dict(self) -> dict:
        row = asdict(self)
        row['invariants'] = list(self.invariants)
        row['strict'] = bool(self.strict)
        return row


def _json_schema_object(properties: dict, *, required: tuple[str, ...] | list[str] | None = None, additional_properties: bool = False) -> dict:
    return {
        'type': 'object',
        'properties': dict(properties or {}),
        'required': list(required or tuple((properties or {}).keys())),
        'additionalProperties': bool(additional_properties),
    }


def _json_schema_array(item_schema: dict | None = None) -> dict:
    return {'type': 'array', 'items': dict(item_schema or {})}


def _json_schema_string_enum(values: tuple[str, ...] | list[str]) -> dict:
    return {'type': 'string', 'enum': [str(x) for x in values]}


_JSON_STRING = {'type': 'string'}
_JSON_BOOL = {'type': 'boolean'}
_JSON_NUMBER = {'type': 'number'}
_JSON_OBJECT = {'type': 'object', 'additionalProperties': True}


_SKILL_TOOL_SPECS: dict[str, SkillToolSpec] = {
    'save_memory': SkillToolSpec('save_memory', 'memory', ('chat_completions', 'responses'), 'Save, update, or delete durable user memory; do not expose memory JSON to the user.'),
    'web_search': SkillToolSpec('web_search', 'web', ('chat_completions', 'responses'), 'Search current or external facts when the answer depends on fresh, niche, cited, or verifiable information.'),
    'fetch_url': SkillToolSpec('fetch_url', 'web', ('chat_completions', 'responses'), 'Read one specific URL when page content is needed for evidence.'),
    'fetch_urls': SkillToolSpec('fetch_urls', 'web', ('chat_completions', 'responses'), 'Read multiple specific URLs for comparison or multi-source grounding.'),
    'get_weather': SkillToolSpec('get_weather', 'weather', ('chat_completions', 'responses'), 'Get weather or forecast only when real weather data is needed.'),
    'get_location': SkillToolSpec('get_location', 'location', ('chat_completions', 'responses'), 'Return location evidence; request browser precise location only when coarse evidence is insufficient.'),
    'image_search': SkillToolSpec('image_search', 'image', ('chat_completions', 'responses'), 'Find real public images or reference photos; do not use as the normal image-generation pre-step.'),
    'analyze_existing_image': SkillToolSpec('analyze_existing_image', 'image', ('chat_completions', 'responses'), 'Analyze existing chat images for visual Q&A, OCR, comparison, or focused inspection; not as a generation pre-step.'),
    'handoff_to_image_delivery': SkillToolSpec('handoff_to_image_delivery', 'image_generate', ('chat_completions',), 'Chat-lane image delivery handoff for generation/edit/reference tasks; Responses uses native image_generation.', tool_kind='handoff', execution_plane='chat_completions', handoff_target='image_delivery'),
    'image_generation': SkillToolSpec('image_generation', 'image_generate', ('responses',), 'Responses native image generation/editing tool; never exposed through Chat/completions handoff.', tool_kind='native_tool', execution_plane='responses'),
    'search_knowledge_base': SkillToolSpec('search_knowledge_base', 'knowledge', ('chat_completions', 'responses'), 'Search local uploaded knowledge-base documents for grounded snippets.'),
    'read_knowledge_base_document': SkillToolSpec('read_knowledge_base_document', 'knowledge', ('chat_completions', 'responses'), 'Read wider or full context from one knowledge-base document when snippets are insufficient.'),
    'search_account_context': SkillToolSpec('search_account_context', 'history', ('chat_completions', 'responses'), 'Search same-account past chats with timeline labels when prior decisions or files matter.'),
    'read_account_context': SkillToolSpec('read_account_context', 'history', ('chat_completions', 'responses'), 'Read selected past-chat context with time header after search_account_context identifies the session.'),
    'sandbox_import_files': SkillToolSpec('sandbox_import_files', 'sandbox', ('chat_completions', 'responses'), 'Import uploaded or generated files into /mnt/data before reading, running, editing, or publishing.'),
    'sandbox_read_file': SkillToolSpec('sandbox_read_file', 'sandbox', ('chat_completions', 'responses'), 'Read text layers or structured spreadsheet/document text from /mnt/data; first path for ordinary file Q&A.'),
    'sandbox_analyze_file_images': SkillToolSpec('sandbox_analyze_file_images', 'sandbox', ('chat_completions', 'responses'), 'Extract rendered visual evidence from files for charts, layout, scans, pages, screenshots, OCR, or explicit visual targets.'),
    'sandbox_resolve_file_context': SkillToolSpec('sandbox_resolve_file_context', 'sandbox', ('chat_completions', 'responses'), 'Resolve files, roles, lineage, and compare candidates before diff, version, or ambiguous file tasks.'),
    'sandbox_diff_files': SkillToolSpec('sandbox_diff_files', 'sandbox', ('chat_completions', 'responses'), 'Run structured file diff through the controlled diff router instead of ad-hoc shell or spreadsheet scripts.'),
    'sandbox_write_file': SkillToolSpec('sandbox_write_file', 'sandbox', ('chat_completions', 'responses'), 'Write one non-code text file into /mnt/data. Generated source-code deliverables must use sandbox_run.'),
    'sandbox_write_files': SkillToolSpec('sandbox_write_files', 'sandbox', ('chat_completions', 'responses'), 'Write multiple non-code text files into /mnt/data. Generated source-code deliverables must use sandbox_run.'),
    'sandbox_replace_text': SkillToolSpec('sandbox_replace_text', 'sandbox', ('chat_completions', 'responses'), 'Replace exact text in a real /mnt/data file after reading the observed content.'),
    'sandbox_create_office_file': SkillToolSpec('sandbox_create_office_file', 'sandbox', ('chat_completions', 'responses'), 'Create a real Office/PDF/CSV/HTML/MD artifact in /mnt/data without shell wrappers.'),
    'sandbox_run': SkillToolSpec('sandbox_run', 'sandbox', ('chat_completions', 'responses'), 'Run code in Docker for execution, tests, validation, conversion, and generated source-code artifacts; write source outputs under /mnt/data, retain code/stdout/stderr, then publish.'),
    'sandbox_publish_files': SkillToolSpec('sandbox_publish_files', 'sandbox', ('chat_completions', 'responses'), 'Publish existing /mnt/data files as downloadable artifacts after generation, edit, or validation.'),
}

_SKILL_SPECS: dict[str, SkillSpec] = {
    'memory': SkillSpec(
        'memory',
        'Memory',
        ('chat_completions', 'responses'),
        '保存、更新或删除长期用户偏好。',
        ('save_memory',),
        activation=('remember preference', 'forget memory', '用户偏好', '记住'),
        trace_events=('memory_saved', 'memory_deleted'),
    ),
    'web': SkillSpec(
        'web',
        'Web Evidence',
        ('chat_completions', 'responses'),
        '搜索并读取最新或外部网页证据。',
        ('web_search', 'fetch_url', 'fetch_urls'),
        activation=('current facts', 'web evidence', 'latest', '今天', '联网', '引用来源'),
        trace_events=('web_search', 'web_fetch', 'evidence_bound'),
    ),
    'weather': SkillSpec(
        'weather',
        'Weather',
        ('chat_completions', 'responses'),
        '查询真实天气和预报。',
        ('get_weather',),
        requires=('location',),
        activation=('weather', 'forecast', '天气', '预报'),
        trace_events=('weather_lookup',),
    ),
    'location': SkillSpec(
        'location',
        'Location',
        ('chat_completions', 'responses'),
        '获取粗略位置或授权精确位置。',
        ('get_location',),
        activation=('location', 'near me', '定位', '附近'),
        trace_events=('location_resolved',),
    ),
    'image': SkillSpec(
        'image',
        'Image Understanding',
        ('chat_completions', 'responses'),
        '搜索图片，或进行看图、OCR、比较和局部分析。',
        ('image_search', 'analyze_existing_image'),
        activation=('image search', 'OCR', '看图', '识图', '图片分析'),
        trace_events=('image_search', 'image_analysis'),
    ),
    'image_generate': SkillSpec(
        'image_generate',
        'Image Generation',
        ('chat_completions', 'responses'),
        '生成、编辑、扩展或参考图片。',
        ('handoff_to_image_delivery', 'image_generation'),
        requires=('image',),
        activation=('generate image', 'edit image', '生图', '改图', '参考图'),
        trace_events=('image_task_selected', 'image_generation_call', 'image_artifact_saved'),
    ),
    'knowledge': SkillSpec(
        'knowledge',
        'Knowledge Base',
        ('chat_completions', 'responses'),
        '搜索并读取本地知识库文档。',
        ('search_knowledge_base', 'read_knowledge_base_document'),
        activation=('knowledge base', 'uploaded docs', '知识库', '文档库'),
        trace_events=('knowledge_search', 'knowledge_read'),
    ),
    'history': SkillSpec(
        'history',
        'Account History',
        ('chat_completions', 'responses'),
        '搜索并读取同账号历史对话。',
        ('search_account_context', 'read_account_context'),
        activation=('past chat', 'history', '之前', '历史对话'),
        trace_events=('history_search', 'history_read'),
    ),
    'sandbox': SkillSpec(
        'sandbox',
        'Sandbox Files',
        ('chat_completions', 'responses'),
        '在沙盒读取、分析、运行、修改和交付文件。',
        (
            'sandbox_import_files',
            'sandbox_read_file',
            'sandbox_analyze_file_images',
            'sandbox_resolve_file_context',
            'sandbox_diff_files',
            'sandbox_write_file',
            'sandbox_write_files',
            'sandbox_replace_text',
            'sandbox_create_office_file',
            'sandbox_run',
            'sandbox_publish_files',
        ),
        activation=('file', 'artifact', 'sandbox', 'xlsx', 'docx', 'pdf', '文件', '沙盒', '生成文件', '修改文件'),
        trace_events=('sandbox_import', 'sandbox_read', 'sandbox_run', 'sandbox_publish'),
    ),
}


# 公开能力目录用于产品展示和分组解析；运行时直接暴露真实工具 schema。
_PUBLIC_SKILL_SPECS: tuple[PublicSkillSpec, ...] = (
    PublicSkillSpec('vision', '图片理解', '看图、截图、OCR、图表理解', ('chat_completions', 'responses'), ('image',), hint='看图/OCR'),
    PublicSkillSpec('image_crop', '图片裁剪', '运行真实代码裁剪并分析局部', ('chat_completions', 'responses'), ('image',), hint='代码裁图'),
    PublicSkillSpec('image_generation', '图片生成', '根据文字生成图片', ('chat_completions', 'responses'), ('image_generate',), hint='文生图'),
    PublicSkillSpec('image_edit', '图片编辑', '修图、换背景、增删元素、扩图', ('chat_completions', 'responses'), ('image_generate',), hint='修图/扩图'),
    PublicSkillSpec('image_search', '图片搜索', '搜索真实网络图片', ('chat_completions', 'responses'), ('image',), hint='搜图'),
    PublicSkillSpec('web_search', '联网搜索', '联网查证最新或外部信息', ('chat_completions', 'responses'), ('web',), hint='联网'),
    PublicSkillSpec('file_search', '文件搜索', '搜索文件库和历史文件', ('chat_completions', 'responses'), ('knowledge', 'history'), hint='文件/历史'),
    PublicSkillSpec('code_execution', '代码执行', '在沙盒运行代码、命令和测试', ('chat_completions', 'responses'), ('sandbox',), hint='沙盒代码'),
    PublicSkillSpec('document_process', 'Word 文档', '读取、创建和修改 Word 文档', ('chat_completions', 'responses'), ('sandbox',), hint='Word'),
    PublicSkillSpec('pdf_process', 'PDF 处理', '读取、渲染、创建和修改 PDF', ('chat_completions', 'responses'), ('sandbox',), hint='PDF'),
    PublicSkillSpec('spreadsheet_process', '表格处理', '读取、创建和分析 Excel/CSV', ('chat_completions', 'responses'), ('sandbox',), hint='Excel/CSV'),
    PublicSkillSpec('slides_process', 'PPT 处理', '读取、创建和修改演示文稿', ('chat_completions', 'responses'), ('sandbox',), hint='PPT'),
    PublicSkillSpec('memory', '长期记忆', '保存或删除长期用户偏好', ('chat_completions', 'responses'), ('memory',), hint='记忆'),
    PublicSkillSpec('location_weather', '定位天气', '查询授权位置和真实天气', ('chat_completions', 'responses'), ('location', 'weather'), hint='定位/天气'),
)

_PUBLIC_SKILL_BY_KEY = {spec.key: spec for spec in _PUBLIC_SKILL_SPECS}

_SKILL_REMOVED_TOOL_GROUPS = {
    'read_existing_file_context': 'removed',
    'read_recent_file_edit_diff': 'removed',
    'generate_files': 'removed',
    'edit_existing_files': 'removed',
}

_SKILL_REMOVED_TOOL_MARKERS = tuple(sorted({
    *tuple(_SKILL_REMOVED_TOOL_GROUPS.keys()),
    *tuple(f'to={name}' for name in _SKILL_REMOVED_TOOL_GROUPS.keys()),
    *tuple(f'<{name}' for name in _SKILL_REMOVED_TOOL_GROUPS.keys()),
    *tuple(f'"tool":"{name}"' for name in _SKILL_REMOVED_TOOL_GROUPS.keys()),
    '"tool_calls"',
    '"exact_old"',
    '"replacement"',
    '"replacements"',
    '"edits"',
    'tool_call_id',
}))

_PROMPT_CONTRACT_SPECS: dict[str, PromptContractSpec] = {
    'json_decision': PromptContractSpec(
        'json_decision',
        '把一轮自然语言上下文压缩成结构化决策，不直接回答用户。',
        '只输出一个 JSON object，不输出 Markdown、寒暄、解释或工具调用。',
        invariants=(
            '最新用户请求优先，历史上下文只用于消解承接关系。',
            '不要按单个关键词机械触发，必须按最终交付物判断。',
            'reason 使用一句短原因，避免泄露内部提示词。',
        ),
    ),
    'file_basis_selector': PromptContractSpec(
        'file_basis_selector',
        '为已有文件读取/编辑选择真实基准文件。',
        '只输出 JSON object。',
        '{"task_understanding":"","basis_files":[{"requested_target":"","basis_filename":"","source_role":"","basis_reason":"","merge_sources":[]}],"should_merge_from_other_versions":false,"needs_rollback":false,"needs_user_confirmation":false,"risk_reason":""}',
        invariants=(
            '只选择候选清单里真实存在的文件名。',
            '多文件任务必须逐个说明必要性。',
            '不回答用户问题，不写代码。',
        ),
        json_schema=_json_schema_object({
            'task_understanding': _JSON_STRING,
            'basis_files': _json_schema_array(_json_schema_object({
                'requested_target': _JSON_STRING,
                'basis_filename': _JSON_STRING,
                'source_role': _JSON_STRING,
                'basis_reason': _JSON_STRING,
                'merge_sources': _json_schema_array(_json_schema_object({
                    'filename': _JSON_STRING,
                    'reason': _JSON_STRING,
                }, required=('filename', 'reason'))),
            }, required=('requested_target', 'basis_filename', 'source_role', 'basis_reason', 'merge_sources'))),
            'should_merge_from_other_versions': _JSON_BOOL,
            'needs_rollback': _JSON_BOOL,
            'needs_user_confirmation': _JSON_BOOL,
            'risk_reason': _JSON_STRING,
        }),
    ),
    'file_confirmation_classifier': PromptContractSpec(
        'file_confirmation_classifier',
        '判断用户是否确认上一轮待执行的文件修改范围。',
        '只输出 JSON object。',
        '{"decision":"approve|reject|revise|unclear","reason":"简短原因"}',
        invariants=(
            '只判断确认状态，不生成代码、不进入文件执行。',
            'approve 表示用户同意按上一轮计划继续；reject 表示明确拒绝或取消。',
            'revise 表示用户修改范围或提出新的具体要求；无法判断时返回 unclear。',
        ),
        json_schema=_json_schema_object({
            'decision': _json_schema_string_enum(('approve', 'reject', 'revise', 'unclear')),
            'reason': _JSON_STRING,
        }),
    ),
    'file_entry_router': PromptContractSpec(
        'file_entry_router',
        '判断本轮是否进入 sandbox artifact runtime。',
        '只输出 JSON object。',
        '{"should_enter":true,"mode":"edit_existing|read_existing|generate_new|none","target_filename":"","symbol_or_query":"","edit_scope":"single_file|multi_file_confirmed|multi_file_needs_confirmation|unknown","required_files":[{"filename":"","reason":""}],"needs_user_confirmation":false,"reason":""}',
        invariants=(
            '真实文件、代码、新版页面或明确修改已有文件才进入。',
            '图片成品/图片编辑优先走图片 lane，除非用户明确要写入代码或文件。',
            '普通聊天、方案讨论、原因分析且不要求交付文件时返回 none。',
        ),
        json_schema=_json_schema_object({
            'should_enter': _JSON_BOOL,
            'mode': _json_schema_string_enum(('edit_existing', 'read_existing', 'generate_new', 'none')),
            'target_filename': _JSON_STRING,
            'symbol_or_query': _JSON_STRING,
            'edit_scope': _json_schema_string_enum(('single_file', 'multi_file_confirmed', 'multi_file_needs_confirmation', 'unknown')),
            'required_files': _json_schema_array(_json_schema_object({
                'filename': _JSON_STRING,
                'reason': _JSON_STRING,
            }, required=('filename', 'reason'))),
            'needs_user_confirmation': _JSON_BOOL,
            'reason': _JSON_STRING,
        }),
    ),
    'file_delivery_gate': PromptContractSpec(
        'file_delivery_gate',
        '判断本轮是否需要生成或发布真实可下载文件。',
        '只输出 JSON object。',
        '{"should_enter_sandbox_files":false,"delivery_mode":"single_file|zip_bundle|none","reason":""}',
        invariants=(
            '真实可保存、可运行、可下载、可提交的文件/代码/页面交付物才进入。',
            '图片成品、图片编辑、普通回答、原因分析或方案讨论不默认进入文件交付。',
            '历史文件和上游预判只作参考，不要机械服从。',
        ),
        json_schema=_json_schema_object({
            'should_enter_sandbox_files': _JSON_BOOL,
            'delivery_mode': _json_schema_string_enum(('single_file', 'zip_bundle', 'none')),
            'reason': _JSON_STRING,
        }),
    ),
    'tool_route_soft_hint': PromptContractSpec(
        'tool_route_soft_hint',
        '为本轮选择最可能的能力路径，只产出软提示。',
        '只输出 JSON object。',
        '{"primary_delivery":"answer|web|location|weather|image|image_edit|file|file_edit|composite","route_candidates":{},"route_mode":"direct_answer|location|weather|visual|file|web_research","route_reason":"","route_confidence":0.0,"answer_strategy":"fast_direct|direct_with_caveat|quick_then_verify|research_first|tool_first","strategy_reason":"","need_external_evidence":false,"current_world_risk":"low|medium|high","upgrade_worth":"low|medium|high","location_action":"resolve_location|none","weather_action":"call_weather|none","file_action":"sandbox_files|none","file_delivery_mode":"zip_bundle|single_file|none","visual_intent":"image_mode|image_search|none","subject":"","count":5,"need_clarify":false,"clarify_question":"","reason":""}',
        invariants=(
            '这是软提示，不直接执行工具。',
            '先判断最终交付物，再选择能力路径。',
            '历史图片和历史文件只是上下文，不能覆盖当前目标。',
        ),
        json_schema=_json_schema_object({
            'primary_delivery': _json_schema_string_enum(('answer', 'web', 'location', 'weather', 'image', 'image_edit', 'file', 'file_edit', 'composite')),
            'route_candidates': _JSON_OBJECT,
            'route_mode': _json_schema_string_enum(('direct_answer', 'location', 'weather', 'visual', 'file', 'web_research')),
            'route_reason': _JSON_STRING,
            'route_confidence': _JSON_NUMBER,
            'answer_strategy': _json_schema_string_enum(('fast_direct', 'direct_with_caveat', 'quick_then_verify', 'research_first', 'tool_first')),
            'strategy_reason': _JSON_STRING,
            'need_external_evidence': _JSON_BOOL,
            'current_world_risk': _json_schema_string_enum(('low', 'medium', 'high')),
            'upgrade_worth': _json_schema_string_enum(('low', 'medium', 'high')),
            'location_action': _json_schema_string_enum(('resolve_location', 'none')),
            'weather_action': _json_schema_string_enum(('call_weather', 'none')),
            'file_action': _json_schema_string_enum(('sandbox_files', 'none')),
            'file_delivery_mode': _json_schema_string_enum(('zip_bundle', 'single_file', 'none')),
            'visual_intent': _json_schema_string_enum(('image_mode', 'image_search', 'none')),
            'subject': _JSON_STRING,
            'count': {'type': 'integer'},
            'need_clarify': _JSON_BOOL,
            'clarify_question': _JSON_STRING,
            'reason': _JSON_STRING,
        }),
    ),
    'image_task_planner': PromptContractSpec(
        'image_task_planner',
        '在图片 lane 内选择任务类型、目标图、参考图和最终图片提示词。',
        '只输出 JSON object。',
        '{"task_type":"existing_image_analysis|text_to_image|image_edit|reference_generate|reference_edit|variation|unclear","prompt":"","need_clarify":false,"clarify_question":"","selected_image_ids":[],"edit_target_image_ids":[],"reference_image_ids":[],"ignore_image_ids":[],"reason":""}',
        invariants=(
            '最新用户请求优先，历史图片只用于承接表达。',
            '纯文本画面需求不需要候选图。',
            '不要把同一张图同时作为编辑目标和参考图。',
        ),
        json_schema=_json_schema_object({
            'task_type': _json_schema_string_enum(('existing_image_analysis', 'text_to_image', 'image_edit', 'reference_generate', 'reference_edit', 'variation', 'unclear')),
            'prompt': _JSON_STRING,
            'need_clarify': _JSON_BOOL,
            'clarify_question': _JSON_STRING,
            'selected_image_ids': _json_schema_array(_JSON_STRING),
            'edit_target_image_ids': _json_schema_array(_JSON_STRING),
            'reference_image_ids': _json_schema_array(_JSON_STRING),
            'ignore_image_ids': _json_schema_array(_JSON_STRING),
            'reason': _JSON_STRING,
        }),
    ),
    'image_id_binder': PromptContractSpec(
        'image_id_binder',
        '把图片任务中的自然语言图片引用绑定到候选图片 ID。',
        '只输出 JSON object。',
        '{"edit_target_image_ids":[],"reference_image_ids":[],"selected_image_ids":[],"prompt":"","reason":""}',
        invariants=(
            '只从候选图片 ID 或 aliases 中选择，无法确定就返回空数组。',
            '不要重新判断任务类型，不要把引用绑定改造成新任务。',
            '优先返回 stable id 或 role id。',
        ),
        json_schema=_json_schema_object({
            'edit_target_image_ids': _json_schema_array(_JSON_STRING),
            'reference_image_ids': _json_schema_array(_JSON_STRING),
            'selected_image_ids': _json_schema_array(_JSON_STRING),
            'prompt': _JSON_STRING,
            'reason': _JSON_STRING,
        }),
    ),
    'document_image_analyzer': PromptContractSpec(
        'document_image_analyzer',
        '观察文档内图片像素，提取可用于回答或文件处理的视觉证据。',
        '输出简体中文结构化文本，不输出 JSON。',
        invariants=(
            '只描述看得见的内容，不编造不可见细节。',
            '保留关键原文、表格、图表、UI、流程图或截图中的证据。',
            '按 summary、visible_text、visual_elements、tables_or_charts、answer_relevant_evidence、confidence 组织。',
        ),
    ),
    'web_query_planner': PromptContractSpec(
        'web_query_planner',
        '联网已由外层决定；这里只规划干净、互补、可执行的搜索词。',
        '只输出 JSON object。',
        '{"subject":"","intent":"basic_info|bio|official_info|realtime|general|unknown","query_strategy":"single_focus|split_by_entity|holistic_compare|broad_scan","focus_plan":[],"queries":[],"query_items":[],"reason":""}',
        invariants=(
            'query 不能包含 user:/assistant:/context:/工具结果 等元文字。',
            '代词和省略表达要结合最近上下文补全主体。',
            'query 之间要互补，不要机械同义改写。',
        ),
        json_schema=_json_schema_object({
            'subject': _JSON_STRING,
            'intent': _json_schema_string_enum(('basic_info', 'bio', 'official_info', 'realtime', 'general', 'unknown')),
            'query_strategy': _json_schema_string_enum(('single_focus', 'split_by_entity', 'holistic_compare', 'broad_scan')),
            'focus_plan': _json_schema_array(_JSON_OBJECT),
            'queries': _json_schema_array(_JSON_STRING),
            'query_items': _json_schema_array(_JSON_OBJECT),
            'reason': _JSON_STRING,
        }),
    ),
    'web_query_reviewer': PromptContractSpec(
        'web_query_reviewer',
        '二次检查候选搜索词是否带上当前任务真实主体。',
        '只输出 JSON object。',
        '{"query_items":[{"text":"","purpose":"","focus":"","priority":0.0,"coverage":""}],"reason":""}',
        invariants=(
            '不决定是否联网，只修正候选 query。',
            '候选 query 已经足够具体时尽量保持不变。',
            '不要添加上下文里没有的精确参数。',
        ),
        json_schema=_json_schema_object({
            'query_items': _json_schema_array(_json_schema_object({
                'text': _JSON_STRING,
                'purpose': _JSON_STRING,
                'focus': _JSON_STRING,
                'priority': _JSON_NUMBER,
                'coverage': _JSON_STRING,
            }, required=('text', 'purpose', 'focus', 'priority', 'coverage'))),
            'reason': _JSON_STRING,
        }),
    ),
    'image_search_decider': PromptContractSpec(
        'image_search_decider',
        '判断回答是否应该自动补充真实网络图片。',
        '只输出 JSON object。',
        '{"need_images":false,"query":"","reason":""}',
        invariants=(
            '只有图片能显著帮助理解对象外观、界面、地点、人物、动物、商品或结构时才返回 true。',
            '代码、报错、纯概念、纯写作、纯改文档任务通常返回 false。',
            'query 必须是用于搜图的短查询。',
        ),
        json_schema=_json_schema_object({
            'need_images': _JSON_BOOL,
            'query': _JSON_STRING,
            'reason': _JSON_STRING,
        }),
    ),
    'image_search_planner': PromptContractSpec(
        'image_search_planner',
        '把用户真实想看的内容规划成适合搜图的 query。',
        '只输出 JSON object。',
        '{"search_query":"","search_queries":[],"display_subject":"","count":5}',
        invariants=(
            '贴近用户原话和当前语境，不主动堆摄影、情绪、画质、风格修饰。',
            'search_queries 是同一主体的少量自然变体，不制造无意义差异。',
            'count 取 1 到 10。',
        ),
        json_schema=_json_schema_object({
            'search_query': _JSON_STRING,
            'search_queries': _json_schema_array(_JSON_STRING),
            'display_subject': _JSON_STRING,
            'count': {'type': 'integer'},
        }),
    ),
    'image_candidate_ranker': PromptContractSpec(
        'image_candidate_ranker',
        '基于候选图轻信息选择最符合用户意图的图片。',
        '只输出 JSON object。',
        '{"picked_indices":[],"intro_text":""}',
        invariants=(
            '只能从候选 idx 中选择，数量按调用方要求。',
            '默认 intro_text 为空，除非用户明确要求概括整组图片。',
            '不要逐张介绍、编号、输出 Markdown 或解释。',
        ),
        json_schema=_json_schema_object({
            'picked_indices': _json_schema_array({'type': 'integer'}),
            'intro_text': _JSON_STRING,
        }),
    ),
    'web_fact_extractor': PromptContractSpec(
        'web_fact_extractor',
        '从已抓取网页材料中提炼可直接支撑最终回答的确认事实。',
        '只输出中文要点，不输出 JSON。',
        invariants=(
            '只基于给定材料，不猜测、不补充材料外内容。',
            '优先提炼页面标题、公告、商品或服务、联系方式、登录注册、价格或分类等可见事实。',
            '信息不确定就不要写。',
        ),
    ),
    'memory_writer': PromptContractSpec(
        'memory_writer',
        '判断本轮是否应写入、更新、删除长期记忆。',
        '只输出 JSON object。',
        '{"ops":[{"op":"add|update|delete|noop","id":"","text":"","ruleType":"soft"}]}',
        invariants=(
            '只存长期稳定偏好、背景、项目状态或约束。',
            '临时任务、一次性进度、寒暄、普通问答输出 noop。',
            '不要写内部提示，text 不超过 120 字。',
        ),
        json_schema=_json_schema_object({
            'ops': _json_schema_array(_json_schema_object({
                'op': _json_schema_string_enum(('add', 'update', 'delete', 'noop')),
                'id': _JSON_STRING,
                'text': _JSON_STRING,
                'ruleType': _JSON_STRING,
            }, required=('op', 'id', 'text', 'ruleType'))),
        }),
    ),
    'history_summary': PromptContractSpec(
        'history_summary',
        '把较旧聊天历史压缩成长期上下文摘要。',
        '只输出摘要正文，不输出 JSON、Markdown 标题或寒暄。',
        invariants=(
            '保留长期目标、项目状态、关键决定、路径/文件名/版本、未解决问题。',
            '删除闲聊、重复确认和无用过程。',
            '不要编造没有出现过的信息。',
        ),
    ),
}


def skill_registry_version() -> str:
    return SKILL_REGISTRY_VERSION


def prompt_contract_spec(name: str = '') -> dict:
    nm = str(name or '').strip()
    spec = _PROMPT_CONTRACT_SPECS.get(nm)
    return spec.to_dict() if spec else {}


def prompt_contract_json_schema(name: str = '') -> dict:
    row = prompt_contract_spec(name)
    schema = row.get('json_schema') if isinstance(row.get('json_schema'), dict) else {}
    return dict(schema or {})


def prompt_contract_response_format(name: str = '', *, prefer_json_schema: bool = True) -> dict:
    """Return the strongest response_format supported by a prompt contract.

    OpenAI-compatible gateways do not all accept json_schema yet, so callers can
    fall back to json_object without duplicating contract wiring.
    """
    row = prompt_contract_spec(name)
    if not row:
        return {'type': 'json_object'}
    schema = row.get('json_schema') if isinstance(row.get('json_schema'), dict) else {}
    if prefer_json_schema and schema:
        safe_name = re.sub(r'[^a-zA-Z0-9_-]+', '_', str(row.get('name') or name or 'contract')).strip('_') or 'contract'
        return {
            'type': 'json_schema',
            'json_schema': {
                'name': safe_name[:64],
                'strict': bool(row.get('strict', True)),
                'schema': schema,
            },
        }
    return {'type': 'json_object'}


def prompt_contract_responses_text_format(name: str = '', *, prefer_json_schema: bool = True) -> dict:
    """Responses API text.format equivalent for prompt contracts."""
    fmt = prompt_contract_response_format(name, prefer_json_schema=prefer_json_schema)
    if fmt.get('type') == 'json_schema':
        return {
            'format': {
                'type': 'json_schema',
                'name': str(((fmt.get('json_schema') or {}).get('name') or name or 'contract'))[:64],
                'strict': bool((fmt.get('json_schema') or {}).get('strict', True)),
                'schema': dict((fmt.get('json_schema') or {}).get('schema') or {}),
            }
        }
    return {'format': {'type': 'json_object'}}


def apply_prompt_contract_response_format(req: dict | None = None, name: str = '', *, prefer_json_schema: bool = True) -> dict:
    out = dict(req or {})
    out['response_format'] = prompt_contract_response_format(name, prefer_json_schema=prefer_json_schema)
    return out


def apply_prompt_contract_responses_text_format(body: dict | None = None, name: str = '', *, prefer_json_schema: bool = True) -> dict:
    out = dict(body or {})
    text = out.get('text') if isinstance(out.get('text'), dict) else {}
    text.update(prompt_contract_responses_text_format(name, prefer_json_schema=prefer_json_schema))
    out['text'] = text
    return out


def prompt_contract_text(name: str = '', *, compact: bool = True) -> str:
    row = prompt_contract_spec(name)
    if not row:
        return ''
    lines = [
        f'Prompt contract: {row.get("name")}.',
        f'用途：{row.get("purpose")}',
        f'输出：{row.get("output")}',
    ]
    schema = str(row.get('schema') or '').strip()
    if schema:
        lines.append('JSON schema：' + schema)
    invariants = [str(x or '').strip() for x in (row.get('invariants') or []) if str(x or '').strip()]
    if invariants:
        if compact:
            lines.append('约束：' + '；'.join(invariants) + '。')
        else:
            lines.extend(['约束：', *[f'- {item}' for item in invariants]])
    return '\n'.join(lines).strip()


def skill_activation_plan(
    endpoint_mode: str = 'chat_completions',
    signals: dict | None = None,
    requested_groups: list | tuple | None = None,
) -> dict:
    """Resolve active skill groups from structured runtime signals.

    This keeps activation as a platform decision instead of repeating long
    natural-language instructions in every prompt.
    """
    mode = _skill_normalize_mode(endpoint_mode)
    sig = signals if isinstance(signals, dict) else {}
    groups: list[str] = []
    reasons: dict[str, str] = {}

    def _add(group: str, reason: str) -> None:
        if not group or group in groups or not skill_group_allowed_for_mode(group, mode):
            return
        groups.append(group)
        reasons[group] = reason

    requested = [str(x or '').strip() for x in (requested_groups or []) if str(x or '').strip()]
    requested_all = 'all' in {x.lower() for x in requested}
    if requested_all:
        for group in skill_groups_for_mode(mode):
            _add(group, 'requested_all')
    else:
        resolved_requested = skill_resolve_public_keys(requested, mode)
        for group in resolved_requested:
            _add(group, 'requested')

    route_mode = str(sig.get('route_mode') or '').strip().lower()
    primary_delivery = str(sig.get('primary_delivery') or '').strip().lower()
    file_action = str(sig.get('file_action') or '').strip().lower()
    visual_intent = str(sig.get('visual_intent') or '').strip().lower()
    location_action = str(sig.get('location_action') or '').strip().lower()
    weather_action = str(sig.get('weather_action') or '').strip().lower()

    if bool(sig.get('need_external_evidence')) or route_mode == 'web_research' or primary_delivery == 'web':
        _add('web', 'external_evidence')
    if weather_action == 'call_weather' or route_mode == 'weather' or primary_delivery == 'weather':
        _add('weather', 'weather_route')
        _add('location', 'weather_may_need_location')
    if location_action == 'resolve_location' or route_mode == 'location' or primary_delivery == 'location':
        _add('location', 'location_route')
    if file_action == 'sandbox_files' or route_mode == 'file' or primary_delivery in {'file', 'file_edit'}:
        _add('sandbox', 'sandbox_file_delivery')
    if visual_intent == 'image_search':
        _add('image', 'image_search')
    if visual_intent == 'image_mode' or route_mode == 'visual' or primary_delivery in {'image', 'image_edit'}:
        _add('image', 'visual_route')
        _add('image_generate', 'image_generation_or_edit')

    if bool(sig.get('knowledge_enabled')) or bool(sig.get('knowledge_context')):
        _add('knowledge', 'knowledge_context')
    if bool(sig.get('history_enabled')) or bool(sig.get('history_context')):
        _add('history', 'history_context')
    if bool(sig.get('memory_enabled')) or bool(sig.get('memory_context')):
        _add('memory', 'memory_context')

    # Runtime plans expose all registered groups by default. Semantic planning is
    # intentionally stricter: no task signals means no selected business group.
    if groups:
        plan = skill_runtime_plan(mode, groups)
    else:
        plan = SkillRuntimePlan(
            mode=mode,
            requested_groups=tuple(requested),
            active_groups=(),
            tools=(),
            handoffs=(),
            native_tools=(),
            trace_events=(),
        ).to_dict()
    plan['activation_reasons'] = reasons
    plan['activation_signals'] = {
        key: sig.get(key)
        for key in (
            'primary_delivery', 'route_mode', 'file_action', 'visual_intent',
            'location_action', 'weather_action', 'need_external_evidence',
        )
        if key in sig
    }
    return plan


_SKILL_TRACE_BUFFER: list[dict] = []
_SKILL_TRACE_BUFFER_MAX = 500


def skill_trace_span(
    event: str = '',
    *,
    skill: str = '',
    tool: str = '',
    endpoint_mode: str = 'chat_completions',
    status: str = 'ok',
    metadata: dict | None = None,
) -> dict:
    ev = str(event or '').strip()
    mode = _skill_normalize_mode(endpoint_mode)
    skill_name = str(skill or '').strip()
    tool_name = str(tool or '').strip()
    if not skill_name and tool_name:
        skill_name = skill_tool_group(tool_name)
    span = {
        'trace_id': 'skill_' + uuid.uuid4().hex[:16],
        'event': ev,
        'skill': skill_name,
        'tool': tool_name,
        'endpoint_mode': mode,
        'status': str(status or 'ok').strip()[:40] or 'ok',
        'ts_ms': int(time.time() * 1000),
        'metadata': dict(metadata or {}),
    }
    _SKILL_TRACE_BUFFER.append(span)
    if len(_SKILL_TRACE_BUFFER) > _SKILL_TRACE_BUFFER_MAX:
        del _SKILL_TRACE_BUFFER[:len(_SKILL_TRACE_BUFFER) - _SKILL_TRACE_BUFFER_MAX]
    return dict(span)


def skill_trace_recent(limit: int = 50) -> list[dict]:
    try:
        n = max(1, min(int(limit or 50), _SKILL_TRACE_BUFFER_MAX))
    except Exception:
        n = 50
    return [dict(x) for x in _SKILL_TRACE_BUFFER[-n:]]


def skill_tool_spec(name: str = '') -> dict:
    nm = str(name or '').strip()
    spec = _SKILL_TOOL_SPECS.get(nm)
    return spec.to_dict() if spec else {}


def skill_spec(name: str = '') -> dict:
    nm = str(name or '').strip()
    spec = _SKILL_SPECS.get(nm)
    return spec.to_dict() if spec else {}


def skill_group_allowed_for_mode(name: str = '', endpoint_mode: str = 'chat_completions') -> bool:
    row = skill_spec(name)
    if not row:
        return True
    mode = 'responses' if str(endpoint_mode or '').strip().lower() in {'responses', 'response', '/responses'} else 'chat_completions'
    modes = {str(x or '').strip() for x in (row.get('modes') or [])}
    return mode in modes


def skill_group_tools(name: str = '', endpoint_mode: str = 'chat_completions') -> list[str]:
    row = skill_spec(name)
    if not row or not skill_group_allowed_for_mode(name, endpoint_mode):
        return []
    return [str(x or '').strip() for x in (row.get('tools') or []) if str(x or '').strip() and skill_tool_allowed_for_mode(str(x or '').strip(), endpoint_mode)]


def skill_groups_for_mode(endpoint_mode: str = 'chat_completions') -> list[str]:
    return [name for name in sorted(_SKILL_SPECS.keys()) if skill_group_allowed_for_mode(name, endpoint_mode)]


def skill_removed_tool_names() -> list[str]:
    return sorted(_SKILL_REMOVED_TOOL_GROUPS.keys())


def skill_removed_tool_markers() -> list[str]:
    return list(_SKILL_REMOVED_TOOL_MARKERS)


def skill_tool_group(name: str = '', spec: dict | None = None) -> str:
    nm = str(name or '').strip()
    if nm in _SKILL_REMOVED_TOOL_GROUPS:
        return _SKILL_REMOVED_TOOL_GROUPS[nm]
    row = skill_tool_spec(nm)
    if row.get('group'):
        return str(row.get('group') or '')
    tool_type = str((spec or {}).get('type') or '').strip().lower()
    if tool_type in {'web_search', 'web_search_preview'}:
        return 'web'
    if tool_type == 'code_interpreter':
        return 'code_interpreter'
    if tool_type == 'image_generation':
        return 'image_generate'
    return 'other'


def skill_tool_description(name: str = '', fallback: str = '', *, max_chars: int = 0) -> str:
    row = skill_tool_spec(name)
    desc = str(row.get('description') or fallback or '').strip()
    if max_chars and len(desc) > int(max_chars):
        return desc[:max(1, int(max_chars))]
    return desc


def skill_tool_allowed_for_mode(name: str = '', endpoint_mode: str = 'chat_completions') -> bool:
    row = skill_tool_spec(name)
    if not row:
        return True
    mode = 'responses' if str(endpoint_mode or '').strip().lower() in {'responses', 'response', '/responses'} else 'chat_completions'
    modes = {str(x or '').strip() for x in (row.get('modes') or [])}
    return mode in modes


def _skill_normalize_mode(endpoint_mode: str = 'chat_completions') -> str:
    return 'responses' if str(endpoint_mode or '').strip().lower() in {'responses', 'response', '/responses'} else 'chat_completions'


def _skill_public_key(value: str = '') -> str:
    return str(value or '').strip().lower().replace('-', '_')[:80]


def skill_public_catalog(
    endpoint_mode: str = 'chat_completions',
    *,
    allowed_groups: list | tuple | set | None = None,
) -> list[dict]:
    """返回产品能力目录；不包含工具参数或 SKILL.md 正文。"""
    mode = _skill_normalize_mode(endpoint_mode)
    restrict_groups = allowed_groups is not None
    allowed = {str(x or '').strip() for x in (allowed_groups or []) if str(x or '').strip()}
    out = []
    for spec in _PUBLIC_SKILL_SPECS:
        if mode not in set(spec.modes):
            continue
        groups = [group for group in spec.groups if not restrict_groups or group in allowed]
        if not groups:
            continue
        row = spec.to_dict()
        row['groups'] = groups
        if spec.key == 'file_search':
            if groups == ['knowledge']:
                row['description'] = '搜索文件库'
                row['hint'] = '文件'
            elif groups == ['history']:
                row['description'] = '搜索历史对话和历史文件'
                row['hint'] = '历史'
        elif spec.key == 'location_weather':
            if groups == ['location']:
                row['description'] = '获取授权位置'
                row['hint'] = '定位'
            elif groups == ['weather']:
                row['description'] = '查询真实天气'
                row['hint'] = '天气'
        out.append(row)
    return out


def skill_resolve_public_keys(
    values: list | tuple | set | str | None,
    endpoint_mode: str = 'chat_completions',
    *,
    allowed_groups: list | tuple | set | None = None,
) -> list[str]:
    """把公开 skill_key 统一映射到内部工具组，同时兼容旧组名。"""
    mode = _skill_normalize_mode(endpoint_mode)
    restrict_groups = allowed_groups is not None
    allowed = {str(x or '').strip() for x in (allowed_groups or []) if str(x or '').strip()}
    if isinstance(values, str):
        source = [x for x in re.split(r'[,;，；\s]+', values) if x]
    else:
        source = list(values or [])
    internal_groups = set(skill_groups_for_mode(mode))
    out: list[str] = []

    def _push(group: str) -> None:
        value = str(group or '').strip()
        if not value or (restrict_groups and value not in allowed) or value not in internal_groups or value in out:
            return
        out.append(value)

    legacy_code_aliases = {'python', 'code', 'analysis', 'code_interpreter', 'code_interpreter_tool'}
    for raw in source:
        key = _skill_public_key(raw)
        if key == 'all':
            return ['all']
        if key in legacy_code_aliases and 'code_interpreter' in internal_groups and (not restrict_groups or 'code_interpreter' in allowed):
            _push('code_interpreter')
            continue
        public = _PUBLIC_SKILL_BY_KEY.get(key)
        if public and mode in set(public.modes):
            for group in public.groups:
                _push(group)
            continue
        # 兼容已保存的内部组名；新模型只看到公开 skill_key。
        if key in internal_groups:
            _push(key)
    return out


def skill_runtime_plan(endpoint_mode: str = 'chat_completions', requested_groups: list | tuple | None = None) -> dict:
    mode = _skill_normalize_mode(endpoint_mode)
    requested_labels = [str(x or '').strip() for x in (requested_groups or []) if str(x or '').strip()]
    raw_groups = skill_resolve_public_keys(requested_labels, mode) if requested_labels else []
    if not requested_labels or 'all' in {x.lower() for x in requested_labels} or 'all' in raw_groups:
        raw_groups = skill_groups_for_mode(mode)
    active_groups = []
    tools = []
    handoffs = []
    native_tools = []
    trace_events = []
    for group in raw_groups:
        if not skill_group_allowed_for_mode(group, mode):
            continue
        row = skill_spec(group)
        if not row:
            continue
        active_groups.append(group)
        for event in row.get('trace_events') or []:
            value = str(event or '').strip()
            if value and value not in trace_events:
                trace_events.append(value)
        for tool_name in skill_group_tools(group, mode):
            if tool_name not in tools:
                tools.append(tool_name)
            spec = skill_tool_spec(tool_name)
            kind = str(spec.get('tool_kind') or '').strip()
            if kind == 'handoff' and tool_name not in handoffs:
                handoffs.append(tool_name)
            if kind == 'native_tool' and tool_name not in native_tools:
                native_tools.append(tool_name)
    return SkillRuntimePlan(
        mode=mode,
        requested_groups=tuple(requested_labels or raw_groups),
        active_groups=tuple(active_groups),
        tools=tuple(tools),
        handoffs=tuple(handoffs),
        native_tools=tuple(native_tools),
        trace_events=tuple(trace_events),
    ).to_dict()


def skill_runtime_prompt(endpoint_mode: str = 'chat_completions', requested_groups: list | tuple | None = None, *, compact: bool = True) -> str:
    plan = skill_runtime_plan(endpoint_mode, requested_groups)
    mode = str(plan.get('mode') or _skill_normalize_mode(endpoint_mode))
    active = [str(x or '').strip() for x in (plan.get('active_groups') or []) if str(x or '').strip()]
    tools = [str(x or '').strip() for x in (plan.get('tools') or []) if str(x or '').strip()]
    handoffs = [str(x or '').strip() for x in (plan.get('handoffs') or []) if str(x or '').strip()]
    native_tools = [str(x or '').strip() for x in (plan.get('native_tools') or []) if str(x or '').strip()]
    traces = [str(x or '').strip() for x in (plan.get('trace_events') or []) if str(x or '').strip()]
    if compact:
        lines = [f'Active tool groups: {", ".join(active) or "none"}.']
    else:
        lines = [
            f'Skill runtime mode={mode}; active_groups={", ".join(active) or "none"}.',
            f'Available tools={", ".join(tools) or "none"}.',
        ]
    if handoffs and not compact:
        lines.append('Handoffs=' + ', '.join(handoffs) + '.')
    if native_tools and not compact:
        lines.append('Native tools=' + ', '.join(native_tools) + '.')
    if traces and not compact:
        lines.append('Trace events=' + ', '.join(traces) + '.')
    if 'sandbox' in active:
        lines.append('Sandbox: import files before use; publish generated outputs.')
    if 'image_generate' in active:
        if mode == 'responses':
            lines.append('Image create/edit: use native image_generation.')
        else:
            lines.append('Image create/edit: use handoff_to_image_delivery.')
    return '\n'.join(lines).strip()


def _skill_registry_summary(*, include_internal: bool = False) -> dict:
    groups: dict[str, list[str]] = {}
    for name, spec in sorted(_SKILL_TOOL_SPECS.items()):
        groups.setdefault(spec.group, []).append(name)
    skills = {name: spec.to_dict() for name, spec in sorted(_SKILL_SPECS.items())}
    prompt_contracts = {name: spec.to_dict() for name, spec in sorted(_PROMPT_CONTRACT_SPECS.items())}
    summary = {
        'version': SKILL_REGISTRY_VERSION,
        'groups': groups,
        'skills': skills,
        'public_skills': skill_public_catalog('chat_completions'),
        'public_skills_by_mode': {
            'chat_completions': skill_public_catalog('chat_completions'),
            'responses': skill_public_catalog('responses'),
        },
        'prompt_contracts': prompt_contracts,
        'runtime_plans': {
            'chat_completions': skill_runtime_plan('chat_completions'),
            'responses': skill_runtime_plan('responses'),
        },
        'skill_count': len(_SKILL_SPECS),
        'public_skill_count': len(_PUBLIC_SKILL_SPECS),
        'tool_count': len(_SKILL_TOOL_SPECS),
    }
    if include_internal:
        summary['trace_recent'] = skill_trace_recent(20)
    return summary


def skill_registry_public_summary() -> dict:
    """Customer-safe registry summary: no trace spans or internal route logs."""
    return _skill_registry_summary(include_internal=False)


def skill_registry_internal_summary() -> dict:
    """Developer/admin diagnostic summary. Do not expose to customer UI."""
    return _skill_registry_summary(include_internal=True)


def skill_registry_with_manifest_summary(manifests: list | None = None) -> dict:
    summary = skill_registry_public_summary()
    rows = []
    for raw in manifests or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get('name') or '').strip()
        if not name:
            continue
        rows.append({
            'name': name,
            'public_key': _skill_public_key(raw.get('public_key') or ''),
            'title': str(raw.get('title') or name).strip(),
            'version': str(raw.get('version') or '').strip(),
            'description': str(raw.get('description') or '').strip(),
            'modes': [str(x or '').strip() for x in (raw.get('modes') or []) if str(x or '').strip()],
            'groups': [str(x or '').strip() for x in (raw.get('groups') or []) if str(x or '').strip()],
            'tools': [str(x or '').strip() for x in (raw.get('tools') or []) if str(x or '').strip()],
            'entrypoint': str(raw.get('entrypoint') or '').strip(),
            'scripts': [str(x or '').strip() for x in (raw.get('scripts') or []) if str(x or '').strip()],
            'input_contract': str(raw.get('input_contract') or '').strip(),
            'output_contract': str(raw.get('output_contract') or '').strip(),
            'activation': [str(x or '').strip() for x in (raw.get('activation') or []) if str(x or '').strip()],
            'trace_events': [str(x or '').strip() for x in (raw.get('trace_events') or []) if str(x or '').strip()],
        })
    summary['skill_manifests'] = rows
    summary['skill_manifest_count'] = len(rows)
    return summary
