# chat/completions memory tool and tool schema assembly helpers.


class ChatStreamToolSpecContext:
    def __init__(
        self,
        *,
        temporary_chat: bool = False,
        chat_capability_groups=None,
        filter_file_plane_tool_specs=None,
    ):
        self.temporary_chat = bool(temporary_chat)
        self.chat_capability_groups = chat_capability_groups if callable(chat_capability_groups) else (lambda groups=None: [])
        self.filter_file_plane_tool_specs = filter_file_plane_tool_specs if callable(filter_file_plane_tool_specs) else (lambda specs=None: [dict(x) for x in (specs or []) if isinstance(x, dict)])

    def cfg_int(self, name: str, default: int, *, min_value: int = 0, max_value: int = 10000) -> int:
        try:
            value = int(os.getenv(name, str(default)) or default)
        except Exception:
            value = default
        return max(min_value, min(max_value, value))

    def responses_native_instruction_max_chars(self) -> int:
        try:
            cache_wanted = bool((globals().get('_prompt_cache_runtime_wants_cache') or (lambda: False))())
        except Exception:
            cache_wanted = False
        if cache_wanted:
            return self.cfg_int(
                'RESPONSES_NATIVE_INSTRUCTIONS_MAX_CHARS',
                120000,
                min_value=24000,
                max_value=300000,
            )
        return self.cfg_int(
            'RESPONSES_NATIVE_INSTRUCTIONS_MAX_CHARS',
            6000,
            min_value=1000,
            max_value=24000,
        )


    def memory_tool_enabled(self) -> bool:
        if self.temporary_chat:
            return False
        try:
            checker = globals().get('_auth_personalization_memory_tool_enabled')
            if callable(checker):
                return bool(checker())
        except Exception:
            return False
        return False

    def save_memory_tool_spec(self, compact: bool = False) -> dict:
        desc = 'Save/update/delete one concise long-term memory when this turn creates durable user preference, background, project state, or a user asks to forget something. Do not call for temporary tasks, ordinary Q&A, or no-op.'
        if compact:
            desc = 'Save/update/delete one concise durable user memory when needed; skip temporary/no-op information.'
        return {
            'type': 'function',
            'function': {
                'name': 'save_memory',
                'description': desc,
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'op': {'type': 'string', 'description': 'add, update, delete, or noop'},
                        'id': {'type': 'string', 'description': 'Existing memory id when updating or deleting.'},
                        'target_index': {'type': 'integer', 'description': '1-based memory number from the visible saved-memory list when deleting by order.'},
                        'query': {'type': 'string', 'description': 'Short semantic target when deleting memories by topic or description.'},
                        'delete_all': {'type': 'boolean', 'description': 'Only true when the user explicitly asks to delete all matching memories.'},
                        'max_delete': {'type': 'integer', 'description': 'Safety cap for delete_all.'},
                        'latest': {'type': 'boolean', 'description': 'True only when the user asks to delete the most recently saved memory.'},
                        'text': {'type': 'string', 'description': 'One concise saved-memory sentence, or exact text to delete.'},
                        'ruleType': {'type': 'string', 'description': 'Use soft for saved memories.'},
                    },
                    'required': ['op'],
                },
            },
        }

    def run_save_memory_tool(self, args: dict | None = None) -> dict:
        saver = globals().get('_auth_personalization_apply_memory_tool')
        if callable(saver):
            try:
                session_getter = globals().get('_account_context_current_session_id')
                session_id = session_getter({}) if callable(session_getter) else ''
            except Exception:
                session_id = ''
            return saver(args or {}, email='', session_id=str(session_id or ''))
        return {'ok': False, 'skipped': True, '_kind': 'memory_event', 'reason': 'memory_tool_unavailable'}

    def slim_chat_tool_specs(self, specs: list | None = None) -> list[dict]:
        """Trim Chat/completions tool-schema prose without changing tool capability.

        Only function/parameter description text is shortened. Tool names,
        parameter names, types, required fields, and execution flow stay intact.
        """
        if not isinstance(specs, list):
            return []
        func_desc_limit = self.cfg_int('AGENT_STREAM_CHAT_TOOL_DESC_MAX_CHARS', 56, min_value=24, max_value=1000)
        param_desc_limit = self.cfg_int('AGENT_STREAM_CHAT_PARAM_DESC_MAX_CHARS', 0, min_value=0, max_value=500)

        def _compact_desc(value, limit: int) -> str:
            raw = str(value or '').replace('\r\n', '\n').replace('\r', '\n')
            raw = re.sub(r'\s+', ' ', raw).strip()
            if not raw or int(limit or 0) <= 0:
                return ''
            limit = max(1, int(limit or 0))
            if len(raw) <= limit:
                return raw
            return raw[:limit].rstrip(' ,;，；。')

        def _slim_schema(obj):
            if isinstance(obj, dict):
                out = {}
                for key, value in obj.items():
                    if key == 'description' and isinstance(value, str):
                        compacted = _compact_desc(value, param_desc_limit)
                        if compacted:
                            out[key] = compacted
                        continue
                    out[key] = _slim_schema(value)
                return out
            if isinstance(obj, list):
                return [_slim_schema(item) for item in obj]
            return obj

        out = []
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            row = dict(spec)
            fn = row.get('function') if isinstance(row.get('function'), dict) else None
            if isinstance(fn, dict):
                fn_out = dict(fn)
                if isinstance(fn_out.get('description'), str):
                    compacted = _compact_desc(fn_out.get('description'), func_desc_limit)
                    if compacted:
                        fn_out['description'] = compacted
                    else:
                        fn_out.pop('description', None)
                if isinstance(fn_out.get('parameters'), dict):
                    fn_out['parameters'] = _slim_schema(fn_out.get('parameters'))
                row['function'] = fn_out
            out.append(row)
        return out

    def normalize_chat_tool_specs(self, specs: list | None = None) -> list[dict]:
        normalizer = globals().get('_normalize_tool_schemas_for_endpoint')
        if callable(normalizer):
            try:
                return normalizer(specs or [], endpoint_mode='chat_completions')
            except Exception:
                pass
        return [dict(x) for x in (specs or []) if isinstance(x, dict)]

    def tool_spec_name(self, spec: dict | None = None) -> str:
        if not isinstance(spec, dict):
            return ''
        fn = spec.get('function') if isinstance(spec.get('function'), dict) else {}
        name = str((fn or {}).get('name') or spec.get('name') or '').strip()
        if name:
            return name
        typ = str(spec.get('type') or '').strip()
        return typ

    def stabilize_tool_specs(self, specs: list | None = None) -> list[dict]:
        """Keep the same tool combination byte-stable across Chat/Responses turns."""
        if not isinstance(specs, list):
            return []
        rows = [dict(x) for x in specs if isinstance(x, dict)]
        group_order = {
            'memory': 1,
            'web': 2,
            'weather': 3,
            'location': 4,
            'image': 5,
            'image_generate': 6,
            'knowledge': 7,
            'history': 8,
            'sandbox': 9,
            'code_interpreter': 10,
            'other': 99,
        }
        tool_order = {
            'save_memory': 2,
            'web_search': 10,
            'fetch_url': 11,
            'fetch_urls': 12,
        }

        def _key(row: dict) -> tuple:
            name = self.tool_spec_name(row)
            typ = str(row.get('type') or '').strip().lower()
            group = self.tool_group(name, row) if name else ('code_interpreter' if typ == 'code_interpreter' else ('image_generate' if typ == 'image_generation' else ('web' if typ in {'web_search', 'web_search_preview'} else 'other')))
            return (
                group_order.get(group, group_order['other']),
                tool_order.get(name, 50),
                group,
                name or typ,
            )

        out: list[dict] = []
        seen: set[str] = set()
        for row in sorted(rows, key=_key):
            name = self.tool_spec_name(row)
            typ = str(row.get('type') or '').strip().lower()
            dedupe_key = (name or typ).lower()
            if dedupe_key and dedupe_key in seen:
                continue
            if dedupe_key:
                seen.add(dedupe_key)
            out.append(row)
        return out

    def tool_group(self, name: str = '', spec: dict | None = None) -> str:
        nm = str(name or '').strip()
        registry_group = globals().get('skill_tool_group')
        if callable(registry_group):
            try:
                group = str(registry_group(nm, spec or {}) or '').strip()
                if group:
                    return group
            except Exception:
                pass
        return 'other'

    def filter_chat_tool_specs_by_groups(self, specs: list | None = None, allowed_tool_groups: list | None = None) -> list[dict]:
        # None 表示内部调用方没有施加分组限制；显式空列表表示尚未选择能力。
        # 只有显式 all 才允许全量工具，避免解析失败后由 [] 意外放权。
        if allowed_tool_groups is None:
            return [dict(x) for x in (specs or []) if isinstance(x, dict)]
        groups = self.chat_capability_groups(allowed_tool_groups)
        if 'all' in groups:
            return [dict(x) for x in (specs or []) if isinstance(x, dict)]
        if not groups:
            return []
        selected = set(groups)
        out: list[dict] = []
        for spec in (specs or []):
            if not isinstance(spec, dict):
                continue
            fn = spec.get('function') if isinstance(spec.get('function'), dict) else {}
            name = str((fn or {}).get('name') or spec.get('name') or '').strip()
            if not name:
                continue
            group = self.tool_group(name, spec)
            if group in selected or (group == 'location' and 'weather' in selected):
                out.append(dict(spec))
        return out

    def chat_filter_or_full_fallback(self, specs: list | None = None, allowed_tool_groups: list | None = None) -> list[dict]:
        filtered = self.filter_chat_tool_specs_by_groups(specs, allowed_tool_groups)
        if allowed_tool_groups is None:
            return filtered
        groups = self.chat_capability_groups(allowed_tool_groups)
        if filtered or 'all' in groups:
            return filtered
        try:
            app_logger.warning('[AGENT_STREAM_CHAT_TOOL_FILTER_EMPTY] groups=%s; fallback=all', json.dumps(groups, ensure_ascii=False))
        except Exception:
            pass
        return self.filter_chat_tool_specs_by_groups(specs, ['all'])

    def tool_specs(self, compact: bool = False, allowed_tool_groups: list | None = None) -> list[dict]:
        allowed_groups = None if allowed_tool_groups is None else self.chat_capability_groups(allowed_tool_groups)
        memory_tool_specs = [self.save_memory_tool_spec(compact=compact)] if self.memory_tool_enabled() else []
        sandbox_builder = globals().get('_sandbox_tool_schemas')
        sandbox_tool_specs = sandbox_builder(compact=compact) if callable(sandbox_builder) else []
        if compact:
            specs = self.normalize_chat_tool_specs(self.filter_file_plane_tool_specs(memory_tool_specs + sandbox_tool_specs + [
                {
                    'type': 'function',
                    'function': {
                        'name': 'web_search',
                        'description': 'Search current/external facts.',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'query': {'type': 'string'},
                                'k': {'type': 'integer'},
                            },
                            'required': ['query'],
                        },
                    },
                },
                {
                    'type': 'function',
                    'function': {
                        'name': 'search_knowledge_base',
                        'description': 'Search local uploaded knowledge-base documents.',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'query': {'type': 'string'},
                                'space_id': {'type': 'string'},
                                'doc_id': {'type': 'string'},
                            },
                            'required': ['query'],
                        },
                    },
                },
                {
                    'type': 'function',
                    'function': {
                        'name': 'read_knowledge_base_document',
                        'description': 'Read wider or full context from one knowledge-base document when search_knowledge_base snippets are not enough.',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'doc_id': {'type': 'string'},
                                'filename': {'type': 'string'},
                                'space_id': {'type': 'string'},
                                'query': {'type': 'string'},
                                'mode': {'type': 'string'},
                                'start_chunk': {'type': 'integer'},
                                'end_chunk': {'type': 'integer'},
                                'around_chunk': {'type': 'integer'},
                                'window_chunks': {'type': 'integer'},
                                'max_chars': {'type': 'integer'},
                                'prefer_full_document': {'type': 'boolean'},
                            },
                        },
                    },
                },
                {
                    'type': 'function',
                    'function': {
                        'name': 'search_account_context',
                        'description': 'Search same-account past chats when history is needed. Results include timeline labels plus relevance_rank and recency_rank, so compare newer resume_state before treating old chats as current.',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'query': {'type': 'string'},
                                'limit': {'type': 'integer'},
                            },
                            'required': ['query'],
                        },
                    },
                },
                {
                    'type': 'function',
                    'function': {
                        'name': 'read_account_context',
                        'description': 'Read selected past-chat context with an explicit session time header and a small amount of recent context only when search_account_context is not enough.',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'session_id': {'type': 'string'},
                                'query': {'type': 'string'},
                                'max_messages': {'type': 'integer'},
                                'max_chars': {'type': 'integer'},
                            },
                        },
                    },
                },
                {
                    'type': 'function',
                    'function': {
                        'name': 'image_search',
                        'description': 'Find real public images/photos/reference pictures.',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'query': {'type': 'string'},
                                'count': {'type': 'integer'},
                                'queries': {'type': 'array', 'items': {'type': 'string'}},
                            },
                            'required': ['query'],
                        },
                    },
                },
                {
                    'type': 'function',
                    'function': {
                        'name': 'analyze_existing_image',
                        'description': 'Analyze selected uploaded/generated chat images only for visual Q&A/OCR/focused inspection. Set focus_crop=true when real local crops are needed for small text or detailed regions; the crop code and result images will be recorded. Do not use as a pre-step for image generation/editing; image generation/editing should hand off to the delivery lane with chosen image ids.',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'query': {'type': 'string'},
                                'image_ref': {'type': 'string'},
                                'image_ids': {'type': 'array', 'items': {'type': 'string'}},
                                'selected_image_ids': {'type': 'array', 'items': {'type': 'string'}},
                                'focus_crop': {'type': 'boolean'},
                            },
                        },
                    },
                },
                {
                    'type': 'function',
                    'function': {
                        'name': 'fetch_url',
                        'description': 'Read one URL.',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'url': {'type': 'string'},
                                'query': {'type': 'string'},
                                'max_chars': {'type': 'integer'},
                            },
                            'required': ['url'],
                        },
                    },
                },
                {
                    'type': 'function',
                    'function': {
                        'name': 'fetch_urls',
                        'description': 'Read multiple URLs.',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'urls': {'type': 'array', 'items': {'type': 'string'}},
                                'query': {'type': 'string'},
                                'max_chars': {'type': 'integer'},
                            },
                            'required': ['urls'],
                        },
                    },
                },
                {
                    'type': 'function',
                    'function': {
                        'name': 'get_weather',
                        'description': 'Weather/forecast tool. Use only when the model judges real weather data is needed. If the user names a place, pass that place separately in place so it overrides runtime current location.',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'query': {'type': 'string'},
                                'place': {'type': 'string', 'description': 'Optional place-only string named by the user, such as 湖南娄底. Leave empty when using current authorized location context.'},
                            },
                            'required': ['query'],
                        },
                    },
                },
                {
                    'type': 'function',
                    'function': {
                        'name': 'get_location',
                        'description': 'Return location evidence: authorized coordinates, coarse network/IP location, and permission state. Set request_precise=true only when this turn needs browser precise location.',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'query': {'type': 'string'},
                                'request_precise': {'type': 'boolean', 'description': 'Ask browser precise-location permission only when coarse evidence is not enough.'},
                            },
                            'required': ['query'],
                        },
                    },
                },
                {
                    'type': 'function',
                    'function': {
                        'name': 'handoff_to_image_delivery',
                        'description': 'Chat-lane image delivery handoff only for image generation/edit/reference tasks. Choose ids from the image index; backend imports selected images before entering the image lane.',
                        'parameters': {
                            'type': 'object',
                            'properties': {
                                'task_type': {'type': 'string', 'description': 'image_generation/text_to_image/image_edit/reference_generate/reference_edit/variation.'},
                                'reason': {'type': 'string'},
                                'prompt': {'type': 'string'},
                                'instruction': {'type': 'string'},
                                'image_ref': {'type': 'string', 'description': 'Optional chosen image id, such as current_user_image_N or assistant_img_N.'},
                                'edit_target_image_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Target/base image ids for edit/outpaint/complete.'},
                                'reference_image_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Reference/source image ids.'},
                                'selected_image_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'All image ids to send to the image lane.'},
                            },
                            'required': ['task_type'],
                        },
                    },
                },
            ]))
            return self.stabilize_tool_specs(self.chat_filter_or_full_fallback(specs, allowed_groups))
        specs = self.normalize_chat_tool_specs(self.filter_file_plane_tool_specs(memory_tool_specs + sandbox_tool_specs + [
            {
                'type': 'function',
                'function': {
                    'name': 'web_search',
                    'description': 'Search the web for current or external information. Use this when the answer may depend on recent facts, prices, news, schedules, public data, or niche information not safely known from memory.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'query': {'type': 'string', 'description': 'A focused search query in the user\'s language when possible.'},
                            'k': {'type': 'integer', 'description': 'Number of search results to return, from 1 to 10.'},
                        },
                        'required': ['query'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'search_knowledge_base',
                    'description': 'Search the local document knowledge base built from uploaded PDF/Word/TXT content. Use this when the user asks about project/reference documents, uploaded materials, saved knowledge-base content, or wants answers grounded in local documents.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'query': {'type': 'string', 'description': 'The document-focused question or keywords to search.'},
                            'space_id': {'type': 'string', 'description': 'Optional knowledge-base space id when known.'},
                            'doc_id': {'type': 'string', 'description': 'Optional document id when the current turn is bound to one document.'},
                        },
                        'required': ['query'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'read_knowledge_base_document',
                    'description': 'Read wider or full original context from one local knowledge-base document after search_knowledge_base. Use it when initial snippets are partial, the user asks to summarize/verify the whole document, or you need neighboring/full-document evidence before answering. Prefer focused/range reads first; set prefer_full_document only when the whole document is needed within max_chars.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'doc_id': {'type': 'string', 'description': 'Knowledge-base document id from search_knowledge_base active_document/results when known.'},
                            'filename': {'type': 'string', 'description': 'Document filename if doc_id is unknown.'},
                            'space_id': {'type': 'string', 'description': 'Optional knowledge-base space id when known.'},
                            'query': {'type': 'string', 'description': 'Question or focus for selecting relevant wider context.'},
                            'mode': {'type': 'string', 'description': 'auto, focused, around, range, or full.'},
                            'start_chunk': {'type': 'integer', 'description': '0-based start chunk for range mode.'},
                            'end_chunk': {'type': 'integer', 'description': '0-based end chunk for range mode.'},
                            'around_chunk': {'type': 'integer', 'description': '0-based center chunk for around mode.'},
                            'window_chunks': {'type': 'integer', 'description': 'How many neighboring chunks to include on each side.'},
                            'max_chars': {'type': 'integer', 'description': 'Maximum characters to return; raise it when expanding.'},
                            'prefer_full_document': {'type': 'boolean', 'description': 'Set true only when complete document context is needed.'},
                        },
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'search_account_context',
                    'description': 'Search relevant past chats from the same logged-in account when your semantic judgment says the answer may depend on previous conversations, earlier project progress, prior decisions, or past generated/uploaded file context. Results include timeline labels, relevance_rank, recency_rank, and saved sessionResumeState/resume_state. When several results fit, compare newer resume_state first; older chats may be background. Do not use it for ordinary questions that can be answered from the current chat.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'query': {'type': 'string', 'description': 'Focused question or keywords for searching past chats.'},
                            'limit': {'type': 'integer', 'description': 'Optional result limit, usually 2 to 3 for low token use.'},
                        },
                        'required': ['query'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'read_account_context',
                    'description': 'Read the saved compact last/resume state from one selected past chat result with an explicit session time header. Use the session_id returned by search_account_context when possible; avoid full rereads unless necessary.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'session_id': {'type': 'string', 'description': 'Past chat session id returned by search_account_context.'},
                            'query': {'type': 'string', 'description': 'Optional focus for what to extract from that past chat.'},
                            'max_messages': {'type': 'integer', 'description': 'Optional number of recent messages to include; keep small, usually 4 to 8.'},
                            'max_chars': {'type': 'integer', 'description': 'Optional max characters to return; keep small, usually 6000 to 12000.'},
                        },
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'image_search',
                    'description': 'Search public images/photos/pictures for real visual references when your semantic judgment says the user wants to find, show, view, compare, or collect existing images. Do not use image search as an image-generation/editing pre-step unless the user asks for external reference images; generation/editing should hand off through handoff_to_image_delivery.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'query': {'type': 'string', 'description': "Focused image search query in the user's language when possible."},
                            'count': {'type': 'integer', 'description': 'How many verified images to show, from 1 to 10.'},
                            'queries': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Optional alternate focused image search queries.'},
                        },
                        'required': ['query'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'analyze_existing_image',
                    'description': 'Analyze existing chat images for visual Q&A/OCR/compare/focused inspection. Choose ids from the image index. Set focus_crop=true when real local crops are needed for small text or detailed regions; the crop code and result images will be recorded. Do not call before image generation/editing.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'query': {'type': 'string', 'description': 'What the user wants to know about the existing image, including text/OCR questions.'},
                            'image_ref': {'type': 'string', 'description': 'Optional stable image label/id from the injected image index if image_ids are unavailable.'},
                            'image_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Image ids chosen from the injected lightweight image index.'},
                            'selected_image_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Alternate field for chosen image ids from the injected image index.'},
                            'focus_crop': {'type': 'boolean', 'description': 'Run and record real Python local-crop code, and analyze the generated crop images.'},
                        },
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'fetch_url',
                    'description': 'Read a specific URL provided by the user or discovered from search when the page content is needed.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'url': {'type': 'string', 'description': 'The URL to read.'},
                            'query': {'type': 'string', 'description': 'Optional focus for extracting the most relevant part of the page.'},
                            'max_chars': {'type': 'integer', 'description': 'Maximum characters to return, normally 12000.'},
                        },
                        'required': ['url'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'fetch_urls',
                    'description': 'Read multiple specific URLs when comparing or grounding an answer from several pages.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'urls': {'type': 'array', 'items': {'type': 'string'}, 'description': 'URLs to read, up to 5.'},
                            'query': {'type': 'string', 'description': 'Optional focus for extraction.'},
                            'max_chars': {'type': 'integer', 'description': 'Maximum characters per request, normally 12000.'},
                        },
                        'required': ['urls'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'get_weather',
                    'description': 'Get current weather or forecast only when the model judges real weather data is needed. If the user explicitly names a city/region, pass it separately in place; that explicit place takes priority over authorized runtime current location. Use runtime location only when no place is named.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'query': {'type': 'string', 'description': 'Weather request including time/detail intent.'},
                            'place': {'type': 'string', 'description': 'Optional place-only string explicitly named by the user, such as 湖南娄底 or 北京朝阳. Leave empty when using current authorized location context.'},
                        },
                        'required': ['query'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'get_location',
                    'description': 'Return location evidence: authorized coordinates, coarse network/IP location, and permission state. Set request_precise=true only when this turn needs browser precise location.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'query': {'type': 'string', 'description': 'The location-related request.'},
                            'request_precise': {'type': 'boolean', 'description': 'Ask browser precise-location permission only when coarse evidence is not enough.'},
                        },
                        'required': ['query'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'handoff_to_image_delivery',
                    'description': 'Chat-lane image delivery handoff only for image generation/edit/reference tasks. Responses uses native image_generation. Existing-image Q&A/OCR uses analyze_existing_image or sandbox_analyze_file_images. Choose ids from the image index; backend imports selected images.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'task_type': {'type': 'string', 'description': 'image_generation/text_to_image/image_edit/reference_generate/reference_edit/variation.'},
                            'reason': {'type': 'string', 'description': 'Brief semantic reason for handoff.'},
                            'prompt': {'type': 'string', 'description': 'Optional final image prompt or delivery instruction.'},
                            'instruction': {'type': 'string', 'description': 'Optional detailed instruction for the delivery lane.'},
                            'image_ref': {'type': 'string', 'description': 'Optional chosen image id/label such as current_user_image_N or assistant_img_N.'},
                            'edit_target_image_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Target/base image ids for edit/outpaint/complete.'},
                            'reference_image_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Reference/source image ids for composition/style/subject transfer.'},
                            'selected_image_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': 'All image ids to send to the image lane.'},
                            'preplanned_image_task_plan': {'type': 'object', 'description': 'Optional advanced image task plan if already resolved.'},
                        },
                        'required': ['task_type'],
                    },
                },
            },
        ]))
        return self.stabilize_tool_specs(self.chat_filter_or_full_fallback(specs, allowed_groups))
