# Append-only evidence ledger.
# Purpose: separate model-visible evidence from UI/runtime metadata, and prevent
# search/file/visual/execution/artifact outputs from being mixed by ad-hoc fields.

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, asdict

EVIDENCE_LEDGER_VERSION = 'evidence_ledger_v1_0606'


def _el_short(value, limit=500):
    text = str(value or '').strip()
    return text if len(text) <= limit else text[:limit] + '…'


def _el_hash(*parts) -> str:
    raw = '\n'.join(str(x or '') for x in parts)
    return hashlib.sha1(raw.encode('utf-8', 'ignore')).hexdigest()[:16]


@dataclass(frozen=True)
class EvidenceEvent:
    version: str
    event_id: str
    type: str
    source_tool: str
    title: str
    status: str
    model_visible: bool
    citable: bool
    locator: str
    summary: str
    payload: dict
    created_at: float

    def to_dict(self) -> dict:
        return asdict(self)


class EvidenceLedger:
    def from_tool_result(self, *, tool: str = '', result=None, args=None) -> EvidenceEvent | None:
        if not isinstance(result, dict):
            return None
        tool_name = str(tool or '').strip()
        status = 'success' if bool(result.get('ok', True)) and not result.get('error') else 'error'
        args = dict(args or {}) if isinstance(args, dict) else {}

        if tool_name == 'web_search':
            query = str(result.get('query') or args.get('query') or '').strip()
            rows = [dict(x) for x in (result.get('results') or []) if isinstance(x, dict)][:10]
            return EvidenceEvent(
                version=EVIDENCE_LEDGER_VERSION,
                event_id='ev_' + _el_hash(tool_name, query, len(rows)),
                type='web_search_results',
                source_tool=tool_name,
                title='联网搜索',
                status=status,
                model_visible=True,
                citable=False,
                locator=query,
                summary=f'query={query}; results={len(rows)}',
                payload={'query': query, 'results': rows[:10], 'note': 'Search results are candidates. Fetch pages before citing detailed claims.'},
                created_at=time.time(),
            )
        if tool_name in {'fetch_url', 'fetch_urls'}:
            if tool_name == 'fetch_urls':
                pages = [dict(x) for x in (result.get('results') or result.get('pages') or []) if isinstance(x, dict)][:8]
                locator = ', '.join([str(x.get('url') or '') for x in pages[:3] if x.get('url')])
                summary = f'fetched_pages={len(pages)}'
                payload = {'pages': pages, 'note': 'Fetched pages are citable evidence if text is sufficient.'}
            else:
                locator = str(result.get('url') or args.get('url') or '').strip()
                summary = _el_short(result.get('title') or locator, 220)
                payload = {'url': locator, 'title': result.get('title'), 'text': _el_short(result.get('text') or result.get('snippet') or '', 2500)}
            return EvidenceEvent(
                version=EVIDENCE_LEDGER_VERSION,
                event_id='ev_' + _el_hash(tool_name, locator, summary),
                type='web_page_read',
                source_tool=tool_name,
                title='读取网页',
                status=status,
                model_visible=True,
                citable=True,
                locator=locator,
                summary=summary,
                payload=payload,
                created_at=time.time(),
            )
        if tool_name == 'sandbox_read_file':
            path = str(result.get('path') or args.get('path') or args.get('filename') or '').strip()
            return EvidenceEvent(
                version=EVIDENCE_LEDGER_VERSION,
                event_id='ev_' + _el_hash(tool_name, path, result.get('chars')),
                type='file_text_evidence',
                source_tool=tool_name,
                title='读取文件文本',
                status=status,
                model_visible=True,
                citable=False,
                locator=path,
                summary=f'{path}; chars={int(result.get("chars") or 0)}; reader={result.get("reader_mode") or ""}',
                payload={'path': path, 'reader_mode': result.get('reader_mode'), 'evidence_policy': result.get('evidence_policy'), 'visual_hint': result.get('visual_hint')},
                created_at=time.time(),
            )
        if tool_name == 'sandbox_analyze_file_images':
            path = str(result.get('path') or args.get('path') or args.get('filename') or '').strip()
            return EvidenceEvent(
                version=EVIDENCE_LEDGER_VERSION,
                event_id='ev_' + _el_hash(tool_name, path, result.get('analyzed_count')),
                type='visual_evidence',
                source_tool=tool_name,
                title='读取视觉证据',
                status=status,
                model_visible=True,
                citable=False,
                locator=path,
                summary=f'{path}; analyzed={int(result.get("analyzed_count") or 0)}',
                payload={'path': path, 'image_count': result.get('image_count'), 'analyzed_count': result.get('analyzed_count')},
                created_at=time.time(),
            )
        if tool_name in {'sandbox_create_office_file', 'sandbox_write_file', 'sandbox_write_files', 'sandbox_replace_text', 'sandbox_publish_files'}:
            path = str(result.get('path') or args.get('path') or args.get('filename') or '').strip()
            files = [dict(x) for x in (result.get('files') or []) if isinstance(x, dict)][:20]
            return EvidenceEvent(
                version=EVIDENCE_LEDGER_VERSION,
                event_id='ev_' + _el_hash(tool_name, path, len(files), result.get('size')),
                type='artifact_event' if tool_name != 'sandbox_publish_files' else 'artifact_published',
                source_tool=tool_name,
                title='产物生成/发布',
                status=status,
                model_visible=True,
                citable=False,
                locator=path,
                summary=f'{tool_name}; path={path}; files={len(files)}',
                payload={'path': path, 'files': files, 'published_paths': result.get('published_paths') or []},
                created_at=time.time(),
            )
        if tool_name == 'sandbox_run':
            return EvidenceEvent(
                version=EVIDENCE_LEDGER_VERSION,
                event_id='ev_' + _el_hash(tool_name, result.get('command'), result.get('exit_code')),
                type='execution_result',
                source_tool=tool_name,
                title='代码运行结果',
                status=status,
                model_visible=True,
                citable=False,
                locator=str(result.get('display_command') or result.get('command') or '')[:260],
                summary=f'exit={result.get("exit_code")}; skipped={bool(result.get("skipped_by_policy"))}',
                payload={'exit_code': result.get('exit_code'), 'skipped_by_policy': result.get('skipped_by_policy'), 'output_paths': result.get('output_paths') or []},
                created_at=time.time(),
            )
        return None


def evidence_ledger_event_from_tool(tool: str = '', result=None, args=None) -> dict | None:
    ev = EvidenceLedger().from_tool_result(tool=tool, result=result, args=args)
    return ev.to_dict() if ev else None


def evidence_ledger_attach_tool_result(tool: str = '', result=None, args=None) -> dict:
    if not isinstance(result, dict):
        return result
    out = dict(result)
    ev = evidence_ledger_event_from_tool(tool=tool, result=result, args=args)
    if ev:
        out['evidence_ledger_event'] = ev
        out['activity_event'] = {
            'event_id': ev.get('event_id'),
            'type': ev.get('type'),
            'title': ev.get('title'),
            'status': ev.get('status'),
            'source_tool': ev.get('source_tool'),
            'locator': ev.get('locator'),
        }
    return out


def evidence_ledger_policy_prompt() -> str:
    return (
        'EvidenceLedger 是追加式证据账本：每次 web_search、fetch_url、sandbox_read_file、sandbox_analyze_file_images、sandbox_run、生成/发布产物后都形成一条证据事件。'
        '搜索结果只是候选来源，读取网页后的 fetch_url/fetch_urls 才能支撑具体网页事实；文件文本、视觉证据、运行结果和产物发布要分类型记录，不能互相冒充。'
        '最终回答和生成文件必须基于 ledger 中已有证据；证据不足时继续调用工具或说明不足。'
    )
