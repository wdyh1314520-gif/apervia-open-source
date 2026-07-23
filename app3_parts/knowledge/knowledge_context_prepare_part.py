# Split from app3_parts/knowledge/knowledge_base_core_part.py.
# Purpose: KB chat context preparation and direct existing-file replies.
# Loaded by knowledge_base_core_part.py via _exec_split_file(...), sharing app3.py globals.

def _prepare_knowledge_base_context(current_user_text: str = '', kb_enabled: bool = True, kb_space_id: str = '', kb_doc_id: str = '') -> dict:
    q = str(current_user_text or '').strip()
    if not kb_enabled:
        return {'enabled': False, 'memory_prompt': '', 'recall_prompt': '', 'doc_brief_prompt': '', 'state': {}, 'search': {}, 'active_document': {}}
    owner = _kb_owner_key()
    _kb_db_ensure()
    conn = _kb_db_connect()
    try:
        space = _kb_resolve_space(owner_key=owner, space_id=kb_space_id, conn=conn) if str(kb_space_id or '').strip() else _kb_ensure_default_space(owner_key=owner, conn=conn)
        summary = _kb_space_summary(space=space, owner_key=owner, conn=conn)
        if int(summary.get('doc_count') or 0) <= 0:
            return {'enabled': True, 'memory_prompt': '', 'recall_prompt': '', 'doc_brief_prompt': '', 'state': summary, 'search': {}, 'active_document': {}}
        active_doc = _kb_pick_active_document(owner_key=owner, space_id=str(space.get('id') or ''), doc_id=kb_doc_id, query=q, conn=conn)
        memory_prompt = (
            f"当前账号已启用知识库《{str(summary.get('name') or '默认知识库')}》，共 {int(summary.get('doc_count') or 0)} 个文档、"
            f"{int(summary.get('chunk_count') or 0)} 个切片。若当前问题涉及库内资料，请优先使用知识库命中片段，并在句末附上 [知识库引用: 《文档名》#片段N]。如果命中片段不足以回答，可按需读取当前知识库文档的更大范围或全文后再回答。"
        )
        stable_document = _kb_prompt_cache_stable_document_context(active_doc=active_doc, owner_key=owner, conn=conn) if active_doc else {}
        stable_document_prompt = str((stable_document or {}).get('prompt') or '').strip()
        stable_document_full = bool((stable_document or {}).get('full_coverage') and stable_document_prompt)
        if stable_document_prompt:
            memory_prompt += '\n\n' + stable_document_prompt
        search = _kb_search(owner_key=owner, query=q, space_id=str(space.get('id') or ''), doc_id=str(active_doc.get('id') or ''), limit_docs=3, limit_chunks=6) if _kb_should_search(q) else {'ok': True, 'results': [], 'space': summary, 'query': q, 'active_document': active_doc}
        recall_prompt = '' if stable_document_full else _kb_prompt_from_search(search, query=q)
        doc_brief_prompt = '' if stable_document_full else _kb_document_brief_prompt(active_doc=active_doc, query=q, search_result=search, owner_key=owner, conn=conn)
        if active_doc and (stable_document_full or not doc_brief_prompt):
            doc_brief_prompt = f"当前轮文档焦点：你现在主要在处理《{str(active_doc.get('filename') or '未命名文件').strip()}》。先围绕这份文档理解用户问题。"
        return {
            'enabled': True,
            'memory_prompt': memory_prompt,
            'recall_prompt': recall_prompt,
            'doc_brief_prompt': doc_brief_prompt,
            'stable_document': stable_document,
            'state': summary,
            'search': search,
            'active_document': active_doc,
        }
    finally:
        conn.close()


def _kb_existing_file_content_intent(query: str = '', active_doc: dict | None = None, result_items: list[dict] | None = None) -> bool:
    doc = dict(active_doc or {})
    if not doc:
        return False
    user_text = str(query or '').strip()
    if not user_text:
        return False
    active_filename = str(doc.get('filename') or '').strip()
    active_terms = [term for term in [active_filename.lower(), *_history_file_stems(active_filename)] if str(term or '').strip()]
    lowered_user_text = user_text.lower()
    asks_file_content = bool(
        _history_file_query_needs_overview(user_text)
        or re.search(r'(主要|具体|大概|大致).{0,8}(内容|写了什么|讲了什么|说了什么)', user_text, flags=re.I)
        or re.search(r'(总结|概括|摘要|梗概|主题|重点|要点|介绍)', user_text, flags=re.I)
    )
    if not asks_file_content:
        return False
    mentions_active_file = bool(active_terms and any(term and term in lowered_user_text for term in active_terms))
    referential_to_file = _history_file_query_looks_referential(user_text, [{'filename': active_filename}])
    return bool(mentions_active_file or referential_to_file or [dict(item) for item in (result_items or []) if isinstance(item, dict) and str(item.get('text') or '').strip()])


def _kb_overview_candidate_lines(text: str = '') -> list[str]:
    raw = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    if not raw.strip():
        return []
    out: list[str] = []
    seen = set()

    def push(piece: str) -> None:
        s = re.sub(r'\s+', ' ', str(piece or '')).strip(' \t-•·：:;；，,')
        if len(s) < 6 or len(s) > 88:
            return
        if re.fullmatch(r'[0-9一二三四五六七八九十百千万①②③④⑤⑥⑦⑧⑨⑩、.．（）()【】\[\]\-\s]+', s):
            return
        key = re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', s.lower())
        if len(key) < 5 or key in seen:
            return
        seen.add(key)
        out.append(s)

    lines = [ln.strip() for ln in raw.split('\n') if str(ln or '').strip()]
    heading_re = re.compile(r'^(?:[一二三四五六七八九十百千万]+[、.．]|\d+[、.．]|[（(][一二三四五六七八九十百千万\d]+[）)])\s*.+$', re.I)
    for line in lines:
        if heading_re.match(line) or re.search(r'(工作总结|工作计划|主要工作|重点工作|存在问题|下一步|后续计划|目标|安排|措施|建议)', line, flags=re.I):
            push(line)
            if len(out) >= 8:
                return out

    sentence_parts = re.split(r'[。！？!?；;\n]+', raw)
    for part in sentence_parts:
        push(part)
        if len(out) >= 8:
            break
    return out


def _kb_collect_overview_points(result_items: list[dict] | None = None, max_points: int = 5) -> list[dict]:
    items = [dict(item) for item in (result_items or []) if isinstance(item, dict) and str(item.get('text') or '').strip()]
    if not items:
        return []
    items.sort(key=lambda item: (int(item.get('chunk_order') or 0), -float(item.get('score') or 0.0)))
    out: list[dict] = []
    seen = set()
    for item in items:
        for line in _kb_overview_candidate_lines(str(item.get('text') or '')):
            key = re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', line.lower())
            if len(key) < 5 or key in seen:
                continue
            seen.add(key)
            out.append({
                'text': line,
                'citation_label': str(item.get('citation_label') or '').strip(),
                'chunk_order': int(item.get('chunk_order') or 0),
            })
            if len(out) >= max(1, int(max_points or 5)):
                return out
    if out:
        return out
    for item in items[:max(1, int(max_points or 5))]:
        piece = truncate_text(re.sub(r'\s+', ' ', str(item.get('text') or '').strip()), max_chars=72)
        if not piece:
            continue
        out.append({
            'text': piece,
            'citation_label': str(item.get('citation_label') or '').strip(),
            'chunk_order': int(item.get('chunk_order') or 0),
        })
    return out


def _kb_render_direct_existing_file_answer(query: str = '', active_doc: dict | None = None, result_items: list[dict] | None = None) -> str:
    doc = dict(active_doc or {})
    items = [dict(item) for item in (result_items or []) if isinstance(item, dict) and str(item.get('text') or '').strip()]
    filename = str(doc.get('filename') or '未命名文件').strip() or '未命名文件'
    if not items:
        return f'我已经识别到你问的是知识库里的《{filename}》，不是让你重新上传文件；但当前知识库命中不足，暂时还不能稳定概括它的主要内容。你可以换成更具体的问法，例如“这份文档的工作总结写了什么”或“这份文档的下一步计划有哪些”。'
    points = _kb_collect_overview_points(items, max_points=5)
    lead = f'根据知识库命中的《{filename}》片段，这份文档主要写的是：'
    if not points:
        snippet = truncate_text(re.sub(r'\s+', ' ', str(items[0].get('text') or '').strip()), max_chars=180)
        cite = str(items[0].get('citation_label') or '').strip()
        if cite:
            return f'{lead}\n1. {snippet} [知识库引用: {cite}]'
        return f'{lead}\n1. {snippet}'
    lines = [lead]
    for idx, point in enumerate(points, start=1):
        piece = str(point.get('text') or '').strip()
        cite = str(point.get('citation_label') or '').strip()
        if cite:
            lines.append(f'{idx}. {piece} [知识库引用: {cite}]')
        else:
            lines.append(f'{idx}. {piece}')
    if re.search(r'(总结|工作总结|计划|工作计划)', query or '', flags=re.I):
        lines.append('如果你要，我可以继续把它拆成“工作总结 / 存在问题 / 下一步计划”三部分继续展开。')
    return '\n'.join(lines).strip()


def _kb_try_direct_existing_file_reply(query: str = '', kb_enabled: bool = True, kb_space_id: str = '', kb_doc_id: str = '') -> dict:
    # 兼容旧调用链；真正的稳定性改为上游补充文档级上下文，不再在这里硬直答。
    return {}
