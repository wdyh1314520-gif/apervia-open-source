# build Responses-native tool specs and group-filtered schema lists.


class ResponsesNativeToolSpecsContext:
    def __init__(
        self,
        *,
        image_generation_enabled: bool = False,
        image_generation_settings: dict | None = None,
        memory_tool_enabled=None,
        save_memory_tool_spec=None,
        stabilize_tool_specs=None,
        agent_stream_cfg_int=None,
        web_search_enabled=None,
        code_interpreter_enabled=None,
        code_interpreter_tool_spec=None,
        image_task_mode=None,
        filter_tool_specs_for_settings=None,
        chat_tool_specs=None,
        web_search_tool_spec=None,
        web_enabled_for_turn=None,
        prompt_cache_wants_stable_tools=None,
    ):
        self.image_generation_enabled = bool(image_generation_enabled)
        self.image_generation_settings = dict(image_generation_settings or {}) if isinstance(image_generation_settings, dict) else {}
        self.memory_tool_enabled = memory_tool_enabled if callable(memory_tool_enabled) else (lambda: False)
        self.save_memory_tool_spec = save_memory_tool_spec if callable(save_memory_tool_spec) else (lambda compact=False: {})
        self.stabilize_tool_specs = stabilize_tool_specs if callable(stabilize_tool_specs) else (lambda specs=None: [dict(x) for x in (specs or []) if isinstance(x, dict)])
        self.agent_stream_cfg_int = agent_stream_cfg_int if callable(agent_stream_cfg_int) else (lambda name, default, min_value=0, max_value=10000: default)
        self.web_search_enabled = web_search_enabled if callable(web_search_enabled) else (lambda: False)
        self.code_interpreter_enabled = code_interpreter_enabled if callable(code_interpreter_enabled) else (lambda: False)
        self.code_interpreter_tool_spec = code_interpreter_tool_spec if callable(code_interpreter_tool_spec) else (lambda: {})
        self.image_task_mode = image_task_mode if callable(image_task_mode) else (lambda task_type='': str(task_type or ''))
        self.filter_tool_specs_for_settings = filter_tool_specs_for_settings if callable(filter_tool_specs_for_settings) else (lambda specs=None: specs or [])
        self.chat_tool_specs = chat_tool_specs if callable(chat_tool_specs) else (lambda compact=False: [])
        self.web_search_tool_spec = web_search_tool_spec if callable(web_search_tool_spec) else (lambda: {})
        self.web_enabled_for_turn = web_enabled_for_turn if callable(web_enabled_for_turn) else (lambda: True)
        self.prompt_cache_wants_stable_tools = prompt_cache_wants_stable_tools if callable(prompt_cache_wants_stable_tools) else (lambda: False)

    def tool_specs(self, compact: bool = True, allowed_tool_groups: list | None = None, *, image_task_type: str = '', eager_source_images: bool = False) -> list[dict]:
        """Build the Responses-native tool list for the direct-first lane.

        The default Responses path exposes the real tool set directly. Optional
        group filtering remains for task-specific routing, but there is no
        deferred capability-loader control round.
        """
        image_generation_enabled = self.image_generation_enabled
        image_generation_settings = self.image_generation_settings
        out: list[dict] = []
        raw_groups = allowed_tool_groups if isinstance(allowed_tool_groups, list) else []
        # Responses 的工具定义属于上游 Prompt Cache 精确前缀。任务路由组会在
        # 普通回答、联网检索和工具续轮之间变化，但这些变化不能再裁剪 tools；
        # 否则即使 prompt_cache_key 相同，前缀仍会在工具表处失配。
        if self.prompt_cache_wants_stable_tools():
            raw_groups = ['all']
        selected_groups = {str(x or '').strip().lower() for x in raw_groups if str(x or '').strip()}
        use_group_filter = bool(selected_groups) and 'all' not in selected_groups

        def _responses_native_tool_group(name: str = '', spec: dict | None = None) -> str:
            tool_type = str((spec or {}).get('type') or '').strip().lower()
            nm = str(name or '').strip()
            registry_group = globals().get('skill_tool_group')
            if callable(registry_group):
                try:
                    group = str(registry_group(nm, spec) or '').strip()
                    if group:
                        return group
                except Exception:
                    pass
            if tool_type in {'web_search', 'web_search_preview'}:
                return 'web'
            if tool_type == 'code_interpreter':
                return 'code_interpreter'
            if tool_type == 'image_generation':
                return 'image_generate'
            return 'other'

        def _responses_native_tool_allowed(name: str = '', spec: dict | None = None) -> bool:
            group = _responses_native_tool_group(name, spec)
            if group == 'web' and not self.web_enabled_for_turn():
                return False
            if not use_group_filter:
                return True
            if group in selected_groups:
                return True
            if group == 'location' and 'weather' in selected_groups:
                return True
            return False

        def _responses_native_slim_tool_description(name: str, description: str = '') -> str:
            limit = self.agent_stream_cfg_int('RESPONSES_NATIVE_TOOL_DESC_MAX_CHARS', 80, min_value=24, max_value=1000)
            registry_desc = globals().get('skill_tool_description')
            if callable(registry_desc):
                try:
                    desc = str(registry_desc(str(name or '').strip(), description, max_chars=limit) or '').strip()
                    if desc:
                        return desc
                except Exception:
                    pass
            mapping = {
                'save_memory': 'Save/update/delete durable user memory; for deletion use id, target_index, query, latest, or delete_all.',
                'search_knowledge_base': 'Search local uploaded knowledge-base documents.',
                'read_knowledge_base_document': 'Read wider/full context from one knowledge-base document.',
                'search_account_context': 'Search past chats with timeline and rank labels.',
                'read_account_context': 'Read selected past-chat context with time header.',
                'image_search': 'Find real public images or reference photos.',
                'analyze_existing_image': 'Analyze existing chat images only for visual Q&A/OCR/focused inspection; not as generation/edit pre-step.',
                                'sandbox_resolve_file_context': 'Resolve files, roles, lineage and compare candidates before diff/对比 tasks.',
                'sandbox_diff_files': 'Run FileDiffRouter for spreadsheets and ordinary text/code/config/data diff; avoid ad-hoc shell/openpyxl scripts.',
                'sandbox_read_file': 'Read text layers/structured spreadsheet/document text from the real sandbox /mnt/data. For XLSX/CSV/TSV and ordinary Office Q&A this is the first-read tool; pair with rendered visual evidence only for charts/layout/formatting/scans/explicit visual targets.',
                'sandbox_analyze_file_images': 'Extract rendered visual evidence inside PDF/DOCX/PPTX/XLSX/image files in /mnt/data; for spreadsheets use only for charts/layout/formatting/merged cells/screenshots/explicit visual targets, not as the default data-reading path.',
                'sandbox_write_file': 'Write a non-code text file into /mnt/data. For generated source-code deliverables use sandbox_run so code/stdout/stderr are retained.',
                'sandbox_write_files': 'Write multiple non-code text files into /mnt/data. For generated source-code deliverables use sandbox_run.',
                'sandbox_replace_text': 'Replace exact text in a real sandbox /mnt/data file.',
                'sandbox_create_office_file': 'Create a real Office/PDF file directly in /mnt/data.',
                'sandbox_import_files': 'Import uploaded/generated files into /mnt/data before running or editing.',
                'sandbox_publish_files': 'Publish sandbox /mnt/data files as downloadable artifacts.',
                'get_weather': 'Get weather or forecast when needed.',
                'get_location': 'Return location evidence; set request_precise=true only if browser precise location is needed.',
                'web_search': 'Search current/external facts.',
                'fetch_url': 'Read one URL.',
                'fetch_urls': 'Read multiple URLs.',
                'handoff_to_image_delivery': 'Chat-lane delivery handoff only; unavailable on the Responses native tool lane.',
            }
            desc = str(mapping.get(str(name or '').strip(), '') or description or '').strip()
            return desc[:limit]

        native_web_enabled = self.web_search_enabled()
        native_web_function_names = {'web_search', 'fetch_url', 'fetch_urls'}
        native_code_interpreter_tool = self.code_interpreter_tool_spec() if self.code_interpreter_enabled() else None
        native_image_tool = None
        native_image_enabled = False
        native_image_group_requested = bool((not use_group_filter) or ('image_generate' in selected_groups) or ('all' in selected_groups))
        try:
            if bool(image_generation_enabled) and native_image_group_requested:
                normalized_image_settings = _normalize_image_generation_settings(image_generation_settings or {}) if callable(globals().get('_normalize_image_generation_settings')) else (dict(image_generation_settings or {}) if isinstance(image_generation_settings, dict) else {})
                native_tool_builder = globals().get('_image_generation_responses_native_tool_spec')
                native_task_mode = self.image_task_mode(image_task_type or ('reference_generate' if eager_source_images else 'text_to_image'))
                built_native_tool = native_tool_builder(normalized_image_settings, task_mode=native_task_mode, has_source_images=bool(eager_source_images)) if callable(native_tool_builder) else {'type': 'image_generation'}
                if isinstance(built_native_tool, dict) and str(built_native_tool.get('type') or '').strip().lower() == 'image_generation':
                    # Responses image_generation is a native tool.  Keep this lane
                    # independent from Chat/completions and avoid sending optional
                    # tool parameters that some native image backends reject.
                    # input_fidelity is not required for the built-in tool call;
                    # when unsupported, providers fail before generation starts.
                    built_native_tool.pop('input_fidelity', None)
                    native_image_tool = built_native_tool
                    native_image_enabled = True
        except Exception:
            native_image_tool = None
            native_image_enabled = False
        for spec in (self.filter_tool_specs_for_settings(self.chat_tool_specs(compact=compact)) or []):
            if not isinstance(spec, dict):
                continue
            fn = spec.get('function') if isinstance(spec.get('function'), dict) else {}
            name = str((fn or {}).get('name') or spec.get('name') or '').strip()
            if not name:
                continue
            if name == 'handoff_to_image_delivery':
                # Responses and Chat image generation are separate lanes.  The
                # The Chat-lane handoff is an image/file delivery bridge for the
                # Chat streaming tool agent and must not compete with the native
                # Responses image_generation tool.
                continue
            if native_web_enabled and name in native_web_function_names:
                continue
            if not _responses_native_tool_allowed(name, spec):
                continue
            item = {
                'type': 'function',
                'name': name,
                'description': _responses_native_slim_tool_description(name, str((fn or {}).get('description') or spec.get('description') or '')),
                'parameters': (fn or {}).get('parameters') if isinstance((fn or {}).get('parameters'), dict) else (spec.get('parameters') if isinstance(spec.get('parameters'), dict) else {'type': 'object', 'properties': {}}),
            }
            out.append(item)
        try:
            if native_web_enabled:
                native_web_tool = self.web_search_tool_spec()
                native_web_type = str((native_web_tool or {}).get('type') or '').strip().lower()
                has_native_web_tool = any(str((tool or {}).get('type') or '').strip().lower() in {'web_search', 'web_search_preview'} for tool in out if isinstance(tool, dict))
                if native_web_type in {'web_search', 'web_search_preview'} and not has_native_web_tool and _responses_native_tool_allowed('web_search', native_web_tool):
                    out.insert(0, native_web_tool)
        except Exception:
            pass
        try:
            native_code_type = str((native_code_interpreter_tool or {}).get('type') or '').strip().lower() if isinstance(native_code_interpreter_tool, dict) else ''
            has_native_code_tool = any(str((tool or {}).get('type') or '').strip().lower() == 'code_interpreter' for tool in out if isinstance(tool, dict))
            if native_code_type == 'code_interpreter' and not has_native_code_tool and _responses_native_tool_allowed('code_interpreter', native_code_interpreter_tool):
                out.append(dict(native_code_interpreter_tool))
        except Exception:
            pass
        try:
            native_image_type = str((native_image_tool or {}).get('type') or '').strip().lower() if isinstance(native_image_tool, dict) else ''
            has_native_image_tool = any(str((tool or {}).get('type') or '').strip().lower() == 'image_generation' for tool in out if isinstance(tool, dict))
            if native_image_type == 'image_generation' and not has_native_image_tool and _responses_native_tool_allowed('image_generation', native_image_tool):
                # Responses image generation/editing is its own native tool lane.
                # It is intentionally not routed through the Chat-lane handoff.
                out.append(dict(native_image_tool))
        except Exception:
            pass
        try:
            if use_group_filter and not out:
                app_logger.warning('[RESPONSES_NATIVE_TOOL_FILTER_EMPTY] groups=%s; fallback=all', json.dumps(sorted(selected_groups), ensure_ascii=False))
                return self.stabilize_tool_specs(self.tool_specs(compact=compact, allowed_tool_groups=['all']))
        except Exception:
            pass
        return self.stabilize_tool_specs(out)
