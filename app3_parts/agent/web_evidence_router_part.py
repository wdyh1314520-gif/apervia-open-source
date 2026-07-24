# Dynamic web evidence router.
# Purpose: web research can happen at any point in the agent loop, including in
# artifact update tasks, but it should distinguish search candidates from read/citable pages.

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

WEB_EVIDENCE_ROUTER_VERSION = 'web_evidence_router_v1_0606'
WEB_EVIDENCE_NEED_RE = re.compile(r'(最新|现在|当前|官方|官网|查资料|资料|搜索|联网|网页|链接|url|http://|https://|核验|验证|来源|出处|引用|标准|政策|价格|发布日期|版本|recent|current|official|verify|source|citation|web|search)', re.I)
OFFICIAL_RE = re.compile(r'(官方|官网|official|docs|documentation|标准|规范|政策)', re.I)


def _wer_short(value, limit=700):
    text = str(value or '').strip()
    return text if len(text) <= limit else text[:limit] + '…'


@dataclass(frozen=True)
class WebEvidencePlan:
    version: str
    needs_web: bool
    mode: str
    first_tool: str
    follow_up_tools: list[str]
    min_sources: int
    prefer_official: bool
    citable_after_fetch: bool
    reason: str
    instruction: str

    def to_dict(self) -> dict:
        return asdict(self)


class WebEvidenceRouter:
    def plan(self, *, text: str = '', task_intent: dict | None = None, evidence_count: int = 0) -> WebEvidencePlan:
        raw = str(text or (task_intent or {}).get('user_text') or '')
        needs = bool((task_intent or {}).get('needs_web')) or bool(WEB_EVIDENCE_NEED_RE.search(raw))
        has_url = bool(re.search(r'https?://\S+', raw))
        prefer_official = bool(OFFICIAL_RE.search(raw))
        first = 'fetch_url' if has_url else 'web_search'
        mode = 'direct_url_read' if has_url else 'research_search_then_fetch'
        min_sources = 2 if prefer_official else 1
        if re.search(r'(全面|深入|多方|竞品|对比|报告|研究|deep|comprehensive)', raw, re.I):
            min_sources = max(min_sources, 3)
        if evidence_count > 0 and not needs:
            mode = 'optional_gap_fill'
        instruction = (
            'Web evidence is dynamic: search when the current evidence has a gap, fetch promising URLs, then decide whether to search/fetch again. '
            'Do not cite search-result snippets as if pages were read. Prefer official/primary sources when requested or when facts may change.'
        )
        return WebEvidencePlan(
            version=WEB_EVIDENCE_ROUTER_VERSION,
            needs_web=needs,
            mode=mode,
            first_tool=first if needs else '',
            follow_up_tools=['fetch_url', 'fetch_urls', 'web_search'] if needs else [],
            min_sources=min_sources if needs else 0,
            prefer_official=prefer_official,
            citable_after_fetch=True,
            reason='web_signal_or_task_need' if needs else 'no_web_signal',
            instruction=instruction,
        )


def web_evidence_plan(text: str = '', task_intent: dict | None = None, evidence_count: int = 0) -> dict:
    return WebEvidenceRouter().plan(text=text, task_intent=task_intent, evidence_count=evidence_count).to_dict()


def web_evidence_policy_prompt() -> str:
    return (
        'WebEvidenceRouter 允许中途随时联网：任务过程中发现缺少最新/官方/外部事实时，可以再次 web_search；'
        '拿到搜索结果后必须按需要 fetch_url/fetch_urls 读取页面正文，搜索结果只作为候选，不作为详细事实引用；'
        '涉及官方、标准、价格、版本、政策、新闻等易变信息优先官方/主来源，并在最终答案或生成文件里保留来源。'
    )
