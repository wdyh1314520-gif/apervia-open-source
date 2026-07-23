# Split from app3_parts/knowledge/knowledge_base_core_part.py.
# Purpose: knowledge context adapter and KB module constants.
# Loaded by knowledge_base_core_part.py via _exec_split_file(...), sharing app3.py globals.

# ==============================
# KNOWLEDGE BASE (platform-level retrieval)
# ==============================
_KB_DB_FILE_DEFAULT = _app_data_path('knowledge_base.db')
_KB_DB_GUARD = threading.Lock()


class ChatStreamKnowledgeContext:
    def __init__(
        self,
        *,
        kb_enabled: bool | None = True,
        kb_space_id: str = '',
        kb_doc_id: str = '',
        latest_user_text=None,
        logger=None,
    ):
        self.kb_enabled = kb_enabled
        self.kb_space_id = str(kb_space_id or '').strip()
        self.kb_doc_id = str(kb_doc_id or '').strip()
        self.latest_user_text = latest_user_text if callable(latest_user_text) else (lambda messages=None: '')
        self.logger = logger

    def messages_with_context(self, base_messages: list | None = None) -> list:
        msgs = [dict(m) if isinstance(m, dict) else m for m in (base_messages or [])]
        try:
            builder = globals().get('_prepare_knowledge_base_context')
            if not callable(builder) or self.kb_enabled is False:
                return msgs
            current_user_text = self.latest_user_text(msgs or [])
            kb_ctx = builder(
                current_user_text=current_user_text,
                kb_enabled=bool(self.kb_enabled is not False),
                kb_space_id=self.kb_space_id,
                kb_doc_id=self.kb_doc_id,
            )
            if not isinstance(kb_ctx, dict) or not kb_ctx.get('enabled'):
                return msgs
            injected: list[dict] = []
            memory_prompt = str(kb_ctx.get('memory_prompt') or '').strip()
            recall_prompt = str(kb_ctx.get('recall_prompt') or '').strip()
            doc_brief_prompt = str(kb_ctx.get('doc_brief_prompt') or '').strip()
            if memory_prompt:
                injected.append({'role': 'system', '_kind': 'kb_memory', 'content': memory_prompt})
            if doc_brief_prompt:
                injected.append({'role': 'system', '_kind': 'kb_doc_brief', 'content': doc_brief_prompt})
            if recall_prompt:
                injected.append({'role': 'system', '_kind': 'kb_recall', 'content': recall_prompt})
            if injected:
                try:
                    state = kb_ctx.get('state') if isinstance(kb_ctx.get('state'), dict) else {}
                    search = kb_ctx.get('search') if isinstance(kb_ctx.get('search'), dict) else {}
                    if self.logger is not None:
                        self.logger.info(
                            '[AGENT_STREAM_KB_CONTEXT_INJECTED] messages=%s injected=%s docs=%s chunks=%s hits=%s memory_chars=%s recall_chars=%s',
                            len(msgs or []),
                            len(injected),
                            int((state or {}).get('doc_count') or 0),
                            int((state or {}).get('chunk_count') or 0),
                            len((search or {}).get('results') or []),
                            len(memory_prompt),
                            len(recall_prompt),
                        )
                except Exception:
                    pass
                return injected + msgs
            return msgs
        except Exception as kb_ctx_err:
            try:
                if self.logger is not None:
                    self.logger.warning('[AGENT_STREAM_KB_CONTEXT_FAILED] err=%s:%s', type(kb_ctx_err).__name__, kb_ctx_err)
            except Exception:
                pass
            return msgs

    def results_for_meta(self, result: dict | None = None, limit: int = 12) -> list[dict]:
        rows = []
        if not isinstance(result, dict):
            return rows
        max_items = max(1, min(int(limit or 12), 20))
        seen = set()
        for item in (result.get('results') or []):
            if not isinstance(item, dict):
                continue
            filename = str(item.get('filename') or item.get('title') or item.get('document_name') or '').strip()
            citation = str(item.get('citation_label') or item.get('citation') or '').strip()
            text = re.sub(r'\s+', ' ', str(item.get('text') or item.get('snippet') or '').strip())[:360]
            doc_id = str(item.get('doc_id') or item.get('document_id') or '').strip()
            try:
                chunk_order = int(item.get('chunk_order') or item.get('chunk') or 0)
            except Exception:
                chunk_order = 0
            key = '|'.join([doc_id, filename, citation, str(chunk_order), text[:120]]).lower()
            if not key.strip('|') or key in seen:
                continue
            seen.add(key)
            rows.append({
                'filename': filename[:220],
                'citation_label': citation[:180],
                'text': text,
                'doc_id': doc_id[:120],
                'chunk_order': chunk_order,
                'score': item.get('score') or item.get('rank_score') or 0,
            })
            if len(rows) >= max_items:
                break
        return rows

    def note_result(self, state: dict, result: dict | None = None, args: dict | None = None) -> dict:
        if not isinstance(state, dict):
            return {}
        result = result or {}
        args = args or {}
        rows = [dict(x) for x in (result.get('results') or []) if isinstance(x, dict)] if isinstance(result, dict) else []
        query = str((result or {}).get('query') or (args or {}).get('query') or '').strip()
        if query:
            existing = [str(q or '').strip() for q in (state.setdefault('kb_queries_used', []) or []) if str(q or '').strip()]
            if query not in existing:
                state.setdefault('kb_queries_used', []).append(query)
        state['kb_results'] = int(state.get('kb_results') or 0) + len(rows)
        state['kb_hit'] = bool(state.get('kb_hit') or rows)
        state_obj = (result or {}).get('state') if isinstance((result or {}).get('state'), dict) else {}
        try:
            state['kb_doc_count'] = max(int(state.get('kb_doc_count') or 0), int((state_obj or {}).get('doc_count') or 0))
        except Exception:
            pass
        try:
            state['kb_chunk_count'] = max(int(state.get('kb_chunk_count') or 0), int((state_obj or {}).get('chunk_count') or 0))
        except Exception:
            pass
        existing_rows = [dict(x) for x in (state.get('kb_search_results') or []) if isinstance(x, dict)]
        merged = existing_rows + self.results_for_meta(result, limit=12)
        out = []
        seen = set()
        for item in merged:
            key = '|'.join([
                str(item.get('doc_id') or ''),
                str(item.get('filename') or ''),
                str(item.get('citation_label') or ''),
                str(item.get('chunk_order') or ''),
            ]).lower()
            if not key.strip('|') or key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) >= 12:
                break
        state['kb_search_results'] = out
        return {
            'use_knowledge_base': True,
            'knowledge_hit': bool(rows),
            'kb_result_count': int(state.get('kb_results') or 0),
            'kb_doc_count': int(state.get('kb_doc_count') or 0),
            'kb_chunk_count': int(state.get('kb_chunk_count') or 0),
            'kb_queries_used': [str(q or '').strip() for q in (state.get('kb_queries_used') or []) if str(q or '').strip()],
            'kb_search_results': [dict(x) for x in (state.get('kb_search_results') or []) if isinstance(x, dict)],
        }
