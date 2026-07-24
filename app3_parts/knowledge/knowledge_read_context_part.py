# KB document chunk listing, read context, read tool, and prompt rendering.

def _kb_list_document_chunks(owner_key: str | None = None, doc_id: str = '', conn=None, limit: int | None = None) -> list[dict]:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    raw_doc_id = str(doc_id or '').strip()
    if not raw_doc_id:
        return []
    _kb_db_ensure()
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        sql = 'SELECT * FROM kb_chunks WHERE owner_key=? AND doc_id=? ORDER BY chunk_order ASC'
        params = [owner, raw_doc_id]
        if int(limit or 0) > 0:
            sql += ' LIMIT ?'
            params.append(int(limit))
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in (rows or [])]
    finally:
        if own_conn:
            conn.close()




def _kb_document_read_max_chars(default: int = 48000) -> int:
    try:
        return max(6000, min(int(str(app_getenv('KB_DOCUMENT_READ_MAX_CHARS', str(default)) or default)), 180000))
    except Exception:
        return int(default)


def _kb_prompt_cache_stable_document_context(active_doc: dict | None = None, owner_key: str | None = None, conn=None) -> dict:
    doc = dict(active_doc or {})
    doc_id = str(doc.get('id') or '').strip()
    if not doc_id:
        return {'prompt': '', 'full_coverage': False, 'chunk_count': 0, 'included_chunks': 0, 'chars': 0}
    try:
        wants_cache = bool((globals().get('_prompt_cache_runtime_wants_cache') or (lambda: False))())
    except Exception:
        wants_cache = False
    if not wants_cache:
        return {'prompt': '', 'full_coverage': False, 'chunk_count': 0, 'included_chunks': 0, 'chars': 0}
    try:
        max_chars = max(8000, min(int(str(app_getenv('KB_PROMPT_CACHE_STABLE_DOCUMENT_MAX_CHARS', '80000') or 80000)), 300000))
    except Exception:
        max_chars = 80000
    chunks = _kb_list_document_chunks(owner_key=owner_key, doc_id=doc_id, conn=conn)
    chunks = [dict(item) for item in (chunks or []) if isinstance(item, dict) and str(item.get('text') or '').strip()]
    if not chunks:
        return {'prompt': '', 'full_coverage': False, 'chunk_count': 0, 'included_chunks': 0, 'chars': 0}
    filename = str(doc.get('filename') or '未命名文件').strip() or '未命名文件'
    content_hash = str(doc.get('content_hash') or '').strip()
    header = (
        f'【稳定知识库文档｜{filename}】\n'
        f'文档ID：{doc_id}'
        + (f'；内容哈希：{content_hash}' if content_hash else '')
        + '\n以下内容按原文片段顺序固定排列，可作为当前绑定文档的稳定事实前缀。'
    )
    blocks: list[str] = []
    used = len(header)
    for item in chunks:
        order = int(item.get('chunk_order') or 0)
        text = str(item.get('text') or '').strip()
        block = (
            f'### 片段{order + 1}\n'
            f'引用标记：[知识库引用: 《{filename}》#片段{order + 1}]\n'
            + text
        )
        extra = len(block) + 2
        if used + extra > max_chars:
            break
        blocks.append(block)
        used += extra
    full_coverage = bool(blocks and len(blocks) == len(chunks))
    if not full_coverage:
        return {
            'prompt': '',
            'full_coverage': False,
            'chunk_count': len(chunks),
            'included_chunks': len(blocks),
            'chars': 0,
        }
    prompt = header + '\n\n' + '\n\n'.join(blocks)
    return {
        'prompt': prompt,
        'full_coverage': True,
        'chunk_count': len(chunks),
        'included_chunks': len(blocks),
        'chars': len(prompt),
    }


def _kb_resolve_document_for_read(owner_key: str | None = None, *, space_id: str = '', doc_id: str = '', filename: str = '', query: str = '', conn=None) -> dict:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    raw_doc_id = str(doc_id or '').strip()
    target_space_id = str(space_id or '').strip()
    raw_filename = os.path.basename(str(filename or '').strip().replace('\\', '/')).strip()
    lowered_filename = raw_filename.lower()
    _kb_db_ensure()
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        if raw_doc_id:
            doc = _kb_get_document(owner_key=owner, doc_id=raw_doc_id, conn=conn)
            if doc and (not target_space_id or str(doc.get('space_id') or '') == target_space_id):
                return doc
        if lowered_filename:
            params = [owner]
            sql = 'SELECT * FROM kb_documents WHERE owner_key=?'
            if target_space_id:
                sql += ' AND space_id=?'
                params.append(target_space_id)
            sql += ' ORDER BY updated_at DESC, created_at DESC LIMIT 300'
            rows = conn.execute(sql, params).fetchall()
            best = {}
            best_score = -1
            for row in rows or []:
                data = dict(row)
                if not _kb_document_ext_allowed(data.get('ext') or ''):
                    continue
                name = os.path.basename(str(data.get('filename') or '').strip()).lower()
                stem = os.path.splitext(name)[0]
                target_stem = os.path.splitext(lowered_filename)[0]
                score = 0
                if name == lowered_filename:
                    score = 100
                elif stem and stem == target_stem:
                    score = 90
                elif lowered_filename and lowered_filename in name:
                    score = 70
                elif target_stem and target_stem in stem:
                    score = 55
                if score > best_score:
                    best_score = score
                    best = data
            if best and best_score >= 55:
                return _kb_document_public(best)
        return _kb_pick_active_document(owner_key=owner, space_id=target_space_id, doc_id='', query=query, conn=conn)
    finally:
        if own_conn:
            conn.close()


def _kb_read_document_context(owner_key: str | None = None, *, doc_id: str = '', filename: str = '', space_id: str = '', query: str = '', mode: str = 'auto', start_chunk: int | None = None, end_chunk: int | None = None, around_chunk: int | None = None, window_chunks: int | None = None, max_chars: int | None = None, prefer_full_document: bool = False, conn=None) -> dict:
    """Read wider or full knowledge-base document context on demand.

    This is the second-stage KB read path used after normal chunk retrieval.  It
    keeps the default KB path lightweight, but lets the model expand around hits,
    read a range, or read the whole current document when the first evidence is
    not enough.
    """
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    q = str(query or '').strip()
    read_mode = str(mode or 'auto').strip().lower()
    if read_mode in {'all', 'full', 'full_document', 'whole', '全文', '整篇'}:
        read_mode = 'full'
    elif read_mode in {'range', 'chunk_range', '片段范围'}:
        read_mode = 'range'
    elif read_mode in {'around', 'near', 'neighbor', 'context', '附近'}:
        read_mode = 'around'
    elif read_mode in {'focused', 'search', 'query', '相关'}:
        read_mode = 'focused'
    else:
        read_mode = 'auto'
    if prefer_full_document:
        read_mode = 'full'
    limit_chars = _kb_document_read_max_chars(48000) if max_chars in (None, '') else max(4000, min(int(max_chars or 48000), 180000))
    radius = max(1, min(int(window_chunks or 3), 16))
    _kb_db_ensure()
    own_conn = conn is None
    conn = conn or _kb_db_connect()
    try:
        doc = _kb_resolve_document_for_read(owner_key=owner, space_id=space_id, doc_id=doc_id, filename=filename, query=q, conn=conn)
        if not doc:
            return {'ok': False, '_kind': 'knowledge_base_document_read', 'error': 'document_not_found', 'query': q, 'results': []}
        raw_doc_id = str(doc.get('id') or '').strip()
        chunks = _kb_list_document_chunks(owner_key=owner, doc_id=raw_doc_id, conn=conn, limit=None)
        chunks = [dict(x) for x in chunks if isinstance(x, dict) and str(x.get('text') or '').strip()]
        if not chunks:
            return {'ok': False, '_kind': 'knowledge_base_document_read', 'error': 'document_has_no_chunks', 'document': _kb_document_public(doc), 'query': q, 'results': []}
        total_chunks = len(chunks)
        by_order = {int(item.get('chunk_order') or 0): dict(item) for item in chunks}
        orders: list[int] = []
        reason = ''
        if read_mode == 'full':
            orders = sorted(by_order.keys())
            reason = 'full_document_requested'
        elif read_mode == 'range':
            try:
                start = max(0, int(start_chunk if start_chunk is not None else 0))
            except Exception:
                start = 0
            try:
                end = int(end_chunk if end_chunk is not None else start + radius * 2)
            except Exception:
                end = start + radius * 2
            if end < start:
                start, end = end, start
            orders = [order for order in sorted(by_order.keys()) if start <= order <= end]
            reason = 'range_requested'
        elif read_mode == 'around' or around_chunk not in (None, ''):
            try:
                center = int(around_chunk if around_chunk not in (None, '') else 0)
            except Exception:
                center = 0
            orders = [order for order in sorted(by_order.keys()) if max(0, center - radius) <= order <= center + radius]
            reason = 'around_chunk_requested'
        else:
            terms = _kb_query_signal_terms(q)
            scored: list[tuple[float, int]] = []
            for item in chunks:
                data = dict(item)
                data['filename'] = str(doc.get('filename') or '')
                data['updated_at'] = doc.get('updated_at')
                score, _reasons = _kb_rank_chunk_for_query(data, q, active_doc=doc, terms=terms)
                order = int(data.get('chunk_order') or 0)
                scored.append((float(score), order))
            scored.sort(key=lambda row: (row[0], -row[1]), reverse=True)
            centers = [order for score, order in scored[:max(1, min(3, total_chunks))] if score > 0.2]
            if not centers:
                centers = [0]
            selected: set[int] = set()
            for center in centers:
                selected.update(order for order in by_order.keys() if max(0, center - radius) <= int(order) <= center + radius)
            if _history_file_query_needs_overview(q) and total_chunks > 2:
                selected.update({0, 1, max(0, total_chunks - 2), max(0, total_chunks - 1)})
            orders = sorted(selected)
            reason = 'focused_expand_by_query'
        if not orders:
            orders = [0]
        blocks: list[dict] = []
        used_chars = 0
        truncated = False
        for order in orders:
            item = dict(by_order.get(int(order)) or {})
            text = str(item.get('text') or '').strip()
            if not text:
                continue
            remaining = max(0, limit_chars - used_chars)
            if remaining <= 0:
                truncated = True
                break
            piece = text if len(text) <= remaining else text[:remaining]
            if len(piece) < len(text):
                truncated = True
            used_chars += len(piece)
            filename2 = str(doc.get('filename') or item.get('filename') or '未命名文件').strip() or '未命名文件'
            blocks.append({
                'doc_id': raw_doc_id,
                'filename': filename2,
                'chunk_order': int(order),
                'citation_label': f'《{filename2}》#片段{int(order) + 1}',
                'text': piece,
            })
            if truncated:
                break
        selected_orders = [int(item.get('chunk_order') or 0) for item in blocks]
        min_order = min(selected_orders) if selected_orders else 0
        max_order = max(selected_orders) if selected_orders else 0
        coverage = {
            'mode': read_mode,
            'reason': reason,
            'selected_chunk_count': len(blocks),
            'total_chunks': total_chunks,
            'selected_orders': selected_orders[:80],
            'start_chunk': min_order,
            'end_chunk': max_order,
            'chars': used_chars,
            'max_chars': limit_chars,
            'truncated': bool(truncated),
            'full_document_loaded': bool(len(blocks) >= total_chunks and not truncated),
        }
        can_expand = bool(truncated or len(blocks) < total_chunks)
        next_reads: list[dict] = []
        if can_expand:
            if max_order + 1 < total_chunks:
                next_reads.append({'mode': 'range', 'doc_id': raw_doc_id, 'start_chunk': max_order + 1, 'end_chunk': min(total_chunks - 1, max_order + max(3, radius * 2)), 'max_chars': min(180000, max(limit_chars, used_chars + 24000))})
            if read_mode != 'full':
                next_reads.append({'mode': 'full', 'doc_id': raw_doc_id, 'prefer_full_document': True, 'max_chars': min(180000, max(limit_chars * 2, 72000))})
        return {
            'ok': True,
            '_kind': 'knowledge_base_document_read',
            'query': q,
            'document': _kb_document_public(doc),
            'mode': read_mode,
            'results': blocks,
            'result_count': len(blocks),
            'coverage': coverage,
            'can_expand': can_expand,
            'recommended_next_reads': next_reads[:3],
            'instruction': '这些是知识库文档的真实原文片段；如果 coverage.can_expand 为 true 且证据仍不足，可以按 recommended_next_reads 继续读取更大范围或全文。回答时使用对应 citation_label。',
            'error': '',
        }
    finally:
        if own_conn:
            conn.close()


def _read_knowledge_base_document_tool(args: dict | None = None) -> dict:
    args = dict(args or {}) if isinstance(args, dict) else {}
    if args.get('_kb_enabled') is False:
        return {'ok': False, '_kind': 'knowledge_base_document_read', 'error': 'knowledge_base_disabled', 'results': []}
    try:
        return _kb_read_document_context(
            space_id=str(args.get('space_id') or args.get('kb_space_id') or '').strip(),
            doc_id=str(args.get('doc_id') or args.get('kb_doc_id') or '').strip(),
            filename=str(args.get('filename') or args.get('target_filename') or '').strip(),
            query=str(args.get('query') or args.get('q') or '').strip(),
            mode=str(args.get('mode') or '').strip() or ('full' if bool(args.get('prefer_full_document')) else 'auto'),
            start_chunk=args.get('start_chunk'),
            end_chunk=args.get('end_chunk'),
            around_chunk=args.get('around_chunk') if args.get('around_chunk') not in (None, '') else args.get('chunk_order'),
            window_chunks=args.get('window_chunks'),
            max_chars=args.get('max_chars'),
            prefer_full_document=bool(args.get('prefer_full_document') or args.get('prefer_full_file')),
        )
    except Exception as e:
        return {'ok': False, '_kind': 'knowledge_base_document_read', 'error': f'{type(e).__name__}: {e}', 'results': []}

def _kb_chunk_block_role(chunk_order: int, total_chunks: int, hit_orders: set[int] | None = None, anchor_orders: set[int] | None = None) -> str:
    hits = set(hit_orders or set())
    anchors = set(anchor_orders or set())
    if chunk_order in hits:
        return '命中片段'
    if chunk_order in anchors:
        return '关联片段'
    if chunk_order <= 1:
        return '开头片段'
    if total_chunks > 0 and chunk_order >= max(0, total_chunks - 2):
        return '结尾片段'
    return '文档片段'


def _kb_select_document_brief_chunks(active_doc: dict | None = None, query: str = '', search_result: dict | None = None, owner_key: str | None = None, conn=None) -> list[dict]:
    doc = dict(active_doc or {})
    raw_doc_id = str(doc.get('id') or '').strip()
    if not raw_doc_id:
        return []
    chunks = _kb_list_document_chunks(owner_key=owner_key, doc_id=raw_doc_id, conn=conn, limit=96)
    if not chunks:
        return []
    filename = str(doc.get('filename') or '').strip()
    result_items = (search_result or {}).get('results') or []
    overview_like = _history_file_query_needs_overview(query) or _kb_existing_file_content_intent(query=query, active_doc=doc, result_items=result_items)
    hit_items = [dict(item) for item in result_items if isinstance(item, dict) and str(item.get('text') or '').strip() and str(item.get('doc_id') or '') == raw_doc_id]
    hit_orders = {int(item.get('chunk_order') or 0) for item in hit_items}
    candidate_orders: set[int] = set()
    for order in hit_orders:
        candidate_orders.update({order, max(0, order - 1), order + 1})
    if overview_like:
        candidate_orders.update({0, 1, max(0, len(chunks) - 2), max(0, len(chunks) - 1)})
    if not candidate_orders:
        candidate_orders.update({0, 1})
    by_order = {int(item.get('chunk_order') or 0): dict(item) for item in chunks}
    scored: list[tuple[float, int, dict]] = []
    for order, item in by_order.items():
        piece = str(item.get('text') or '').strip()
        if not piece:
            continue
        score = _history_file_chunk_score(piece, query, filename=filename)
        if order in hit_orders:
            score += 5.0
        if order in candidate_orders:
            score += 2.0
        if overview_like:
            if order <= 1:
                score += 2.4
            if order >= max(0, len(chunks) - 2):
                score += 1.4
            if re.search(r'(工作总结|工作计划|主要工作|重点工作|存在问题|下一步|后续计划|目标|安排|措施|建议)', piece, flags=re.I):
                score += 1.2
        if not score:
            score = 0.2
        scored.append((float(score), int(order), item))
    scored.sort(key=lambda row: (row[0], -row[1]), reverse=True)
    limit = 7 if overview_like else 5
    selected_orders: list[int] = []
    seen = set()
    for _score, order, _item in scored:
        if order in seen:
            continue
        if order not in candidate_orders and len(selected_orders) >= max(3, limit - 1):
            continue
        seen.add(order)
        selected_orders.append(order)
        if len(selected_orders) >= limit:
            break
    if overview_like:
        for extra in [0, 1, max(0, len(chunks) - 1)]:
            if extra not in seen and extra in by_order and len(selected_orders) < limit:
                seen.add(extra)
                selected_orders.append(extra)
    selected_orders = sorted(set(selected_orders))
    out: list[dict] = []
    for order in selected_orders:
        item = dict(by_order.get(order) or {})
        piece = truncate_text(str(item.get('text') or '').strip(), max_chars=1600)
        if not piece:
            continue
        out.append({
            'doc_id': raw_doc_id,
            'filename': filename,
            'chunk_order': int(order),
            'text': piece,
            'citation_label': f'《{filename or "未命名文件"}》#片段{int(order) + 1}',
            'block_role': _kb_chunk_block_role(int(order), len(chunks), hit_orders=hit_orders, anchor_orders=candidate_orders),
        })
    return out


def _kb_document_brief_prompt(active_doc: dict | None = None, query: str = '', search_result: dict | None = None, owner_key: str | None = None, conn=None) -> str:
    doc = dict(active_doc or {})
    if not doc:
        return ''
    brief_chunks = _kb_select_document_brief_chunks(active_doc=doc, query=query, search_result=search_result, owner_key=owner_key, conn=conn)
    if not brief_chunks:
        return ''
    filename = str(doc.get('filename') or '未命名文件').strip() or '未命名文件'
    active_doc_id = str(doc.get('id') or '').strip()
    recalled_orders = {
        int(item.get('chunk_order') or 0)
        for item in ((search_result or {}).get('results') or [])
        if isinstance(item, dict)
        and str(item.get('doc_id') or '').strip() == active_doc_id
        and str(item.get('text') or '').strip()
    }
    if recalled_orders:
        brief_chunks = [
            item for item in brief_chunks
            if int(item.get('chunk_order') or 0) not in recalled_orders
        ]
    if not brief_chunks:
        return f'当前轮文档焦点：你现在主要在处理《{filename}》。知识库命中片段已经覆盖本轮所需的文档证据。'
    overview_points = _kb_collect_overview_points(brief_chunks, max_points=6)
    lines = [
        f'当前轮文档焦点：你现在主要在处理《{filename}》。',
        '下面是从该文档按原文顺序整理出来的上下文包；优先基于这些材料回答，不要再说看不到文件。',
    ]
    if overview_points:
        lines.append('### 文档概要线索')
        for idx, point in enumerate(overview_points, start=1):
            cite = str(point.get('citation_label') or '').strip()
            piece = str(point.get('text') or '').strip()
            if cite:
                lines.append(f'{idx}. {piece} [知识库引用: {cite}]')
            else:
                lines.append(f'{idx}. {piece}')
    lines.append('### 文档上下文包（按原文顺序）')
    for idx, item in enumerate(brief_chunks, start=1):
        role = str(item.get('block_role') or '文档片段').strip()
        citation = str(item.get('citation_label') or '').strip()
        order_no = int(item.get('chunk_order') or 0) + 1
        block = [
            f'[{role}] 片段{order_no}',
            f'引用标记：[知识库引用: {citation}]' if citation else '',
            str(item.get('text') or '').strip(),
        ]
        lines.append('\n'.join([line for line in block if line]))
    return '\n\n'.join([line for line in lines if line]).strip()


def _kb_prompt_from_search(search_result: dict | None = None, query: str = '') -> str:
    result = dict(search_result or {})
    items = [dict(item) for item in (result.get('results') or []) if isinstance(item, dict) and str(item.get('text') or '').strip()]
    if not items:
        return ''
    active_doc = dict(result.get('active_document') or {}) if isinstance(result.get('active_document'), dict) else {}
    evidence = dict(result.get('evidence') or {}) if isinstance(result.get('evidence'), dict) else {}
    quality = str(evidence.get('quality') or '').strip()
    direct_count = int(evidence.get('direct_count') or 0)
    context_count = int(evidence.get('context_count') or 0)
    top_score = evidence.get('top_score')
    lines = [
        '以下是当前账号知识库检索得到的证据片段。请优先基于这些片段回答，并把它们当作可核对的原文证据。',
        '使用知识库事实时，建议在对应句末附上 [知识库引用: 《文档名》#片段N]；证据不足时可以继续读取当前知识库文档更大范围或全文，仍不足再说明知识库命中不足，不要把片段外内容当成库内事实。',
    ]
    if quality:
        lines.append(f'### 证据概况\n质量：{quality}；命中片段：{direct_count}；关联上下文：{context_count}；最高分：{top_score}')
    if active_doc:
        lines.append(f'当前轮已锁定文档：《{str(active_doc.get("filename") or "未命名文件").strip()}》。先在这份文档内理解用户问题，再组织回答。')
    for idx, item in enumerate(items, start=1):
        citation = str(item.get('citation_label') or '').strip()
        filename = str(item.get('filename') or '未命名文件').strip()
        role = str(item.get('context_role') or '命中片段').strip() or '命中片段'
        score = item.get('score')
        reasons = [str(x or '').strip() for x in (item.get('rank_reasons') or []) if str(x or '').strip()]
        meta = [role]
        try:
            meta.append(f'分数 {float(score):.2f}')
        except Exception:
            pass
        if reasons:
            meta.append('线索 ' + ', '.join(reasons[:4]))
        block = [
            f'### 知识库证据 {idx}',
            f'文件：{filename}',
            f'片段：{int(item.get("chunk_order") or 0) + 1}',
            '；'.join(meta),
            f'引用标记：[知识库引用: {citation}]' if citation else '',
            str(item.get('text') or '').strip(),
        ]
        lines.append('\n'.join([line for line in block if line]))
    return '\n\n'.join([line for line in lines if line]).strip()
