# KB query term extraction, chunk ranking, and search.

def _kb_query_signal_terms(query: str = '') -> list[str]:
    """Build lightweight lexical signals for KB ranking.

    This is not an intent gate. It only gives the existing retriever more usable
    signals for Chinese/English mixed questions where one long phrase would miss
    relevant chunks.
    """
    raw = str(query or '').strip().lower()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def push(value: str) -> None:
        term = str(value or '').strip().lower()
        if not term or len(term) < 2:
            return
        term = term.strip(' .,_-:/\\\t\r\n')
        if len(term) < 2 or term in seen:
            return
        seen.add(term)
        out.append(term)

    for term in (_history_file_query_terms(raw) or []):
        push(term)

    for m in re.finditer(r'[a-z0-9_./\-]{2,}', raw, flags=re.I):
        token = str(m.group(0) or '').strip('.-_ /\\')
        push(token)

    # Add a small amount of CJK n-gram signal so queries like “常见配置” can
    # still match chunks split around “配置项 / 常见 / 服务器”等内容.
    for m in re.finditer(r'[\u4e00-\u9fff]{2,30}', raw):
        seq = str(m.group(0) or '').strip()
        if len(seq) <= 12:
            push(seq)
        for size in (4, 3, 2):
            if len(seq) < size:
                continue
            for i in range(0, len(seq) - size + 1):
                push(seq[i:i + size])
                if len(out) >= 48:
                    return out[:48]
    return out[:48]


def _kb_query_cjk_chars(query: str = '') -> set[str]:
    try:
        return {ch for ch in str(query or '') if '\u4e00' <= ch <= '\u9fff'}
    except Exception:
        return set()


def _kb_rank_chunk_for_query(row: dict | None = None, query: str = '', *, active_doc: dict | None = None, terms: list[str] | None = None) -> tuple[float, list[str]]:
    data = dict(row or {}) if isinstance(row, dict) else {}
    filename = str(data.get('filename') or '').strip()
    piece = str(data.get('text') or '').strip()
    lowered_piece = piece.lower()
    lowered_query = str(query or '').strip().lower()
    signal_terms = [str(t or '').strip().lower() for t in (terms or _kb_query_signal_terms(query)) if str(t or '').strip()]
    reasons: list[str] = []

    score = float(_history_file_chunk_score(piece, query, filename=filename) or 0.0)
    if score > 0.5:
        reasons.append('content_match')

    exact_hits = 0
    soft_hits = 0
    for term in signal_terms[:48]:
        if not term:
            continue
        hits = lowered_piece.count(term)
        if hits > 0:
            exact_hits += hits
            weight = 0.26 + min(len(term), 12) * 0.055
            if len(term) <= 2:
                weight *= 0.55
            score += min(hits, 8) * weight
        elif len(term) >= 4 and all(ch in lowered_piece for ch in term[:4]):
            soft_hits += 1
            score += 0.18
    if exact_hits:
        reasons.append('term_hit')
    if soft_hits:
        reasons.append('soft_overlap')

    q_chars = _kb_query_cjk_chars(lowered_query)
    if q_chars:
        piece_chars = _kb_query_cjk_chars(lowered_piece[:2800])
        if piece_chars:
            overlap = len(q_chars & piece_chars) / max(1, len(q_chars))
            if overlap >= 0.34:
                score += min(2.2, overlap * 1.85)
                reasons.append('char_overlap')

    if lowered_query and len(lowered_query) >= 4 and lowered_query in lowered_piece:
        score += 4.0
        reasons.append('full_query')

    head = lowered_piece[:260]
    if signal_terms and any(term and term in head for term in signal_terms[:24]):
        score += 0.75
        reasons.append('early_hit')

    filename_lower = filename.lower()
    if filename_lower and filename_lower in lowered_query:
        score += 8.0
        reasons.append('filename')
    for stem in _history_file_stems(filename):
        if stem and stem in lowered_query:
            score += 2.2
            reasons.append('filename_stem')
    if signal_terms and any(term and term in filename_lower for term in signal_terms[:24]):
        score += 1.8
        reasons.append('filename_term')

    if active_doc and str(active_doc.get('id') or '') == str(data.get('doc_id') or ''):
        score += 3.5
        reasons.append('active_document')

    try:
        age_days = max(0.0, (_utc_ts() - float(data.get('updated_at') or data.get('created_at') or _utc_ts())) / 86400.0)
    except Exception:
        age_days = 0.0
    score += max(0.0, 0.6 - min(age_days, 365.0) / 365.0)

    if score <= 0.25 and signal_terms:
        reasons.append('weak')
    # Keep reason list compact and stable for UI/model evidence.
    compact: list[str] = []
    for item in reasons:
        if item and item not in compact:
            compact.append(item)
    return round(float(score), 4), compact[:6]


def _kb_neighbor_orders_for_evidence(order: int, *, include_wide: bool = False) -> set[int]:
    try:
        base = int(order)
    except Exception:
        base = 0
    out = {max(0, base - 1), base + 1}
    if include_wide:
        out.update({max(0, base - 2), base + 2})
    return out



def _kb_search(owner_key: str | None = None, query: str = '', space_id: str = '', doc_id: str = '', limit_docs: int = 3, limit_chunks: int = 6) -> dict:
    owner = str(owner_key or _kb_owner_key()).strip().lower() or 'anonymous'
    q = str(query or '').strip()
    raw_doc_id = str(doc_id or '').strip()
    if not _kb_should_search(q):
        active_doc = _kb_get_document(owner_key=owner, doc_id=raw_doc_id) if raw_doc_id else {}
        target_space = _kb_space_summary(owner_key=owner, space_id=space_id) if str(space_id or '').strip() else _kb_space_summary(owner_key=owner)
        return {'ok': True, 'results': [], 'space': target_space, 'query': q, 'active_document': active_doc, 'evidence': {'quality': 'none', 'reason': 'query_not_searchable'}}
    _kb_db_ensure()
    conn = _kb_db_connect()
    try:
        active_doc = _kb_get_document(owner_key=owner, doc_id=raw_doc_id, conn=conn) if raw_doc_id else {}
        active_space_id = str(space_id or '').strip() or str((active_doc or {}).get('space_id') or '').strip()
        space = _kb_resolve_space(owner_key=owner, space_id=active_space_id, conn=conn) if active_space_id else None
        terms = _kb_query_signal_terms(q)
        params = [owner]
        where = ['c.owner_key=?']
        if space is not None:
            where.append('c.space_id=?')
            params.append(str(space.get('id') or ''))
        if active_doc:
            where.append('c.doc_id=?')
            params.append(str(active_doc.get('id') or ''))
        allowed_clause, allowed_params = _kb_sql_non_image_clause('d.ext')
        where.append(allowed_clause)
        params.extend(allowed_params)
        sql = """
            SELECT c.doc_id, c.chunk_order, c.text, c.text_lower, d.filename, d.ext, d.space_id, d.download_url, d.view_url, d.updated_at, d.created_at
            FROM kb_chunks c
            JOIN kb_documents d ON d.id = c.doc_id
            WHERE {where}
        """.format(where=' AND '.join(where))
        rows = []
        direct_query_used = False
        if terms:
            like_clauses = []
            for term in terms[:16]:
                like_clauses.append('c.text_lower LIKE ?')
                params.append(f'%{term}%')
            sql_terms = sql + ' AND (' + ' OR '.join(like_clauses) + ') ORDER BY d.updated_at DESC, c.chunk_order ASC LIMIT 360'
            rows = conn.execute(sql_terms, params).fetchall()
            direct_query_used = bool(rows)
        if not rows:
            params2 = [owner]
            where2 = ['c.owner_key=?']
            if space is not None:
                where2.append('c.space_id=?')
                params2.append(str(space.get('id') or ''))
            if active_doc:
                where2.append('c.doc_id=?')
                params2.append(str(active_doc.get('id') or ''))
            allowed_clause2, allowed_params2 = _kb_sql_non_image_clause('d.ext')
            where2.append(allowed_clause2)
            params2.extend(allowed_params2)
            rows = conn.execute(
                sql.format(where=' AND '.join(where2)) + ' ORDER BY d.updated_at DESC, c.chunk_order ASC LIMIT 260',
                params2,
            ).fetchall()
        scored: list[dict] = []
        for row in (rows or []):
            data = dict(row)
            piece = str(data.get('text') or '').strip()
            if not piece:
                continue
            score, reasons = _kb_rank_chunk_for_query(data, q, active_doc=active_doc, terms=terms)
            if score <= 0.25 and terms and direct_query_used:
                continue
            data['_score'] = float(score)
            data['_rank_reasons'] = reasons
            scored.append(data)
        scored.sort(key=lambda item: (float(item.get('_score') or 0.0), float(item.get('updated_at') or item.get('created_at') or 0.0), -int(item.get('chunk_order') or 0)), reverse=True)

        max_docs = 1 if active_doc else max(1, min(int(limit_docs or 3), 8))
        max_chunks = max(1, min(int(limit_chunks or 6), 12))
        selected_by_key: dict[tuple[str, int], dict] = {}
        per_doc: dict[str, int] = {}
        seen_docs: set[str] = set()

        def push_selected(raw_item: dict, *, context_role: str = '命中片段', score_override: float | None = None, reasons_override: list[str] | None = None) -> bool:
            if len(selected_by_key) >= max_chunks:
                return False
            item = dict(raw_item or {})
            doc_id_current = str(item.get('doc_id') or '')
            if not doc_id_current:
                return False
            try:
                order = int(item.get('chunk_order') or 0)
            except Exception:
                order = 0
            key = (doc_id_current, order)
            if key in selected_by_key:
                existing = selected_by_key[key]
                if context_role and str(existing.get('context_role') or '') != '命中片段':
                    existing['context_role'] = context_role
                return False
            if doc_id_current not in seen_docs and len(seen_docs) >= max_docs:
                return False
            count = int(per_doc.get(doc_id_current, 0) or 0)
            if count >= (4 if active_doc else 3):
                return False
            piece = truncate_text(str(item.get('text') or '').strip(), max_chars=1800)
            if not piece:
                return False
            seen_docs.add(doc_id_current)
            per_doc[doc_id_current] = count + 1
            filename = str(item.get('filename') or '').strip()
            citation_label = f'《{filename or "未命名文件"}》#片段{order + 1}'
            score_value = float(score_override if score_override is not None else (item.get('_score') or item.get('score') or 0.0))
            reasons = reasons_override if reasons_override is not None else (item.get('_rank_reasons') or [])
            selected_by_key[key] = {
                'doc_id': doc_id_current,
                'space_id': str(item.get('space_id') or ''),
                'filename': filename,
                'ext': str(item.get('ext') or '').strip().lower(),
                'chunk_order': order,
                'text': piece,
                'score': round(float(score_value), 4),
                'download_url': str(item.get('download_url') or ''),
                'view_url': str(item.get('view_url') or ''),
                'citation_label': citation_label,
                'context_role': str(context_role or '命中片段').strip() or '命中片段',
                'rank_reasons': [str(x) for x in (reasons or []) if str(x or '').strip()][:6],
            }
            return True

        for item in scored:
            if len(selected_by_key) >= max_chunks:
                break
            push_selected(item, context_role='命中片段')

        # Add neighboring evidence for the top matches when there is room. This
        # gives the answerer paragraph-level context without changing which KB is searched.
        row_map: dict[tuple[str, int], dict] = {}
        for row in (rows or []):
            try:
                data = dict(row)
            except Exception:
                data = row if isinstance(row, dict) else {}
            doc_id_current = str(data.get('doc_id') or '')
            if not doc_id_current:
                continue
            try:
                order = int(data.get('chunk_order') or 0)
            except Exception:
                order = 0
            row_map[(doc_id_current, order)] = data
        top_hits = [dict(item) for item in scored[:max(2, min(5, max_chunks))]]
        for hit in top_hits:
            if len(selected_by_key) >= max_chunks:
                break
            doc_id_current = str(hit.get('doc_id') or '')
            if not doc_id_current:
                continue
            try:
                order = int(hit.get('chunk_order') or 0)
            except Exception:
                order = 0
            include_wide = bool(active_doc and len(selected_by_key) < max_chunks - 1)
            for neighbor_order in sorted(_kb_neighbor_orders_for_evidence(order, include_wide=include_wide)):
                if len(selected_by_key) >= max_chunks:
                    break
                raw = dict(row_map.get((doc_id_current, neighbor_order)) or {})
                if not raw:
                    continue
                score, reasons = _kb_rank_chunk_for_query(raw, q, active_doc=active_doc, terms=terms)
                push_selected(raw, context_role='关联片段', score_override=max(0.0, score * 0.72), reasons_override=(reasons + ['neighbor']))

        selected = [dict(item) for item in selected_by_key.values()]
        selected.sort(key=lambda item: (
            str(item.get('doc_id') or '') != str((active_doc or {}).get('id') or '') if active_doc else 0,
            -float(item.get('score') or 0.0),
            str(item.get('filename') or ''),
            int(item.get('chunk_order') or 0),
        ))
        if active_doc:
            selected.sort(key=lambda item: int(item.get('chunk_order') or 0))
        selected = selected[:max_chunks]
        for idx, item in enumerate(selected, start=1):
            item['rank'] = idx

        scores = [float(item.get('score') or 0.0) for item in selected]
        direct_count = sum(1 for item in selected if str(item.get('context_role') or '') == '命中片段')
        quality = 'none'
        if selected:
            top_score = max(scores or [0.0])
            if direct_count >= 2 or top_score >= 7.0:
                quality = 'strong'
            elif direct_count >= 1 or top_score >= 2.0:
                quality = 'partial'
            else:
                quality = 'weak'
        target_space = _kb_space_summary(space=space, owner_key=owner, conn=conn) if space is not None else {'id': '', 'name': '全部知识库'}
        evidence = {
            'quality': quality,
            'result_count': len(selected),
            'direct_count': direct_count,
            'context_count': max(0, len(selected) - direct_count),
            'top_score': round(max(scores or [0.0]), 4),
            'searched_scope': 'active_document' if active_doc else 'space',
            'top_citations': [str(item.get('citation_label') or '') for item in selected[:4] if str(item.get('citation_label') or '').strip()],
        }
        return {'ok': True, 'results': selected, 'space': target_space, 'query': q, 'terms': terms, 'active_document': active_doc, 'evidence': evidence}
    finally:
        conn.close()
