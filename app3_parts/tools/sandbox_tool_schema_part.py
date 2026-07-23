# Split from app3_parts/tools/file_registry_edit_tools_part.py.
# Purpose: sandbox tool schemas and canonical sandbox tool name set.
# Loaded after file_registry_edit_tools_part.py, sharing the original global namespace.

def _sandbox_tool_schemas(compact: bool = False) -> list[dict]:
    # ??????????????????????????????????
    # ????????????? schema ??????
    if not _sandbox_tools_enabled():
        return []
    desc_suffix = ' Paths are always relative to the per-chat sandbox.'
    tools = [
        {
            'type': 'function',
            'function': {
                'name': 'sandbox_resolve_file_context',
                'description': ('Resolve current/historical sandbox file context and diff candidates.' if compact else 'Resolve current uploaded files, historical generated artifacts, sandbox files, roles, families, and compare_candidates for diff/compare/version questions. Use this before sandbox_diff_files; it is the controlled replacement for raw ls/find when locating old/new/diff files.' + desc_suffix),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {'type': 'string'},
                        'path': {'type': 'string'},
                        'include_sandbox': {'type': 'boolean'},
                        'max_files': {'type': 'integer'},
                        'max_candidates': {'type': 'integer'},
                    },
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'sandbox_diff_files',
                'description': ('Compare two sandbox files or the best resolved compare candidate.' if compact else 'Compare original/enhanced sandbox files through FileDiffRouter. Provide left_path/right_path when known; otherwise it uses FileContextResolver compare_candidates. Supports xlsx/xlsm spreadsheet diff plus ordinary text/code/config/data file diff. It can publish spreadsheet diff reports and .diff patch files when requested. Use this for diff/对比/差异 requests instead of shell ls/find/openpyxl/ad-hoc scripts.' + desc_suffix),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'query': {'type': 'string'},
                        'left_path': {'type': 'string'},
                        'right_path': {'type': 'string'},
                        'output_path': {'type': 'string'},
                        'create_file': {'type': 'boolean'},
                        'publish': {'type': 'boolean'},
                        'max_changes': {'type': 'integer'},
                    },
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'sandbox_read_file',
                'description': ('Read text from a sandbox file.' if compact else 'Read text layers or structured text from a UTF-8/text, spreadsheet, Office/PDF, or zip file in the persistent coding sandbox. Uploaded/generated files must be imported first with sandbox_import_files. This is the first evidence lane for XLSX/CSV/TSV and ordinary Office Q&A. It does not inspect visual pixels, screenshots, charts, diagrams, UI, formulas embedded only as images, scanned pages, or page layout; use sandbox_analyze_file_images only when the centralized file evidence policy says visual evidence is needed.' + desc_suffix),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'path': {'type': 'string'},
                        'max_chars': {'type': 'integer'},
                    },
                    'required': ['path'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'sandbox_analyze_file_images',
                'description': ('Analyze images/pages inside a sandbox document with a vision model; set focus_crop=true only for detailed local inspection.' if compact else 'Render document pages from an imported sandbox file, then analyze those pages with the active vision-capable model. Use this after sandbox_import_files for real image files, screenshots, charts, diagrams, UI, formulas/symbols that require pixels, scanned pages, page layout, or explicit visual targets inside PDF/DOCX/PPTX/XLSX/image files. For detailed local inspection/OCR/small text, set focus_crop=true so the real Python crop code and its image results are recorded. For XLSX/CSV/TSV, do not use this as the default data-reading path; sandbox_read_file is primary unless the user explicitly asks about chart/layout/format/color/merged cells/page rendering. Office files are rendered through LibreOffice/PDF first. If the user asks for a named figure/table such as 图1/Figure 1, pass that exact target; do not treat the first page as the figure.' + desc_suffix),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'path': {'type': 'string'},
                        'query': {'type': 'string'},
                        'target': {'type': 'string'},
                        'max_images': {'type': 'integer'},
                        'max_pages': {'type': 'integer'},
                        'vision_model': {'type': 'string'},
                        'focus_crop': {'type': 'boolean'},
                    },
                    'required': ['path'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'sandbox_write_file',
                'description': ('Write a non-code text file. Generated source-code deliverables must use sandbox_run.' if compact else 'Create, replace, or append a UTF-8 non-code text file inside the persistent coding sandbox. Do not use this for generated .py/.js/.ts/.c/.cpp or other source-code deliverables; use sandbox_run with language="python" and code that writes the target under /mnt/data so the real execution trace is retained, then publish it.' + desc_suffix),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'path': {'type': 'string'},
                        'content': {'type': 'string'},
                        'append': {'type': 'boolean'},
                    },
                    'required': ['path', 'content'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'sandbox_write_files',
                'description': ('Write multiple non-code text files. Generated source-code deliverables must use sandbox_run.' if compact else 'Create, replace, or append multiple UTF-8 non-code text files inside the persistent coding sandbox in one call. For generated source-code files or projects, use sandbox_run with Python code that writes the targets under /mnt/data, then validate and publish them.' + desc_suffix),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'files': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'path': {'type': 'string'},
                                    'content': {'type': 'string'},
                                    'append': {'type': 'boolean'},
                                },
                                'required': ['path', 'content'],
                                'additionalProperties': False,
                            },
                        },
                        'continue_on_error': {'type': 'boolean'},
                    },
                    'required': ['files'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'sandbox_create_office_file',
                'description': ('Create a real Office/PDF file from structured content; no shell.' if compact else 'Create a real downloadable document file inside the persistent sandbox from structured JSON. Supports docx, xlsx, pptx, pdf, html, rtf, csv, and md. Use this for Word/Excel/PowerPoint/PDF delivery instead of sandbox_run, dependency probes, shell wrappers, or inline code; then call sandbox_publish_files with the generated path.' + desc_suffix),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'path': {'type': 'string'},
                        'format': {'type': 'string', 'enum': ['docx', 'xlsx', 'pptx', 'pdf', 'html', 'rtf', 'csv', 'md']},
                        'title': {'type': 'string'},
                        'content': {'type': 'string'},
                        'sections': {'type': 'array', 'items': {'type': 'object'}},
                        'sheets': {'type': 'array', 'items': {'type': 'object'}},
                        'slides': {'type': 'array', 'items': {'type': 'object'}},
                    },
                    'required': ['path'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'sandbox_run',
                'description': ('Run code/commands in Docker. Use this to generate source-code files under /mnt/data, retain code/stdout/stderr, and publish output_paths.' if compact else 'Run code or commands inside a real Docker sandbox mounted at /mnt/data. Use this for real execution, project tests, grep/find, complex statistics/validation, conversions, or generated artifacts. For generated .py/.js/.ts/.c/.cpp and other source-code deliverables, use language="python" with code that writes the requested file directly under /mnt/data; this preserves a real code/stdout/stderr execution record before sandbox_publish_files. Do not use it as the ordinary first-read path for Office/spreadsheet files. The backend wraps every run with bash -lc and runs Python as python3 -P - with stdin. For shell/node code, set language accordingly. Use command/argv only for simple commands such as ls/find/grep or explicit executable calls. Do not put heredoc syntax like python3 - <<PY in command; pass code/stdin instead. Default network is disabled. If Docker is unavailable this returns sandbox_backend_unavailable and never falls back to host shell. If the command creates or changes files, output_paths is returned and you must call sandbox_publish_files.' + desc_suffix),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'command': {'type': 'string', 'description': 'Shell command for simple commands only, such as ls/find/grep. It is executed through the unified bash -lc runner. Do not use this for Python program bodies, heredoc, or version-only probes unless the user explicitly asks.'},
                        'argv': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Explicit executable argv for simple non-interactive commands.'},
                        'language': {'type': 'string', 'enum': ['python', 'shell', 'bash', 'sh', 'node', 'javascript'], 'description': 'Set to python with code for Python execution; set to shell/bash/sh/node for stdin code in those runtimes.'},
                        'code': {'type': 'string', 'description': 'Program text to run through stdin. For Python, prefer language=python plus code; do not put code into command.'},
                        'cwd': {'type': 'string'},
                        'timeout_s': {'type': 'number'},
                        'stdin': {'type': 'string'},
                        'stdin_text': {'type': 'string'},
                    },
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'sandbox_replace_text',
                'description': ('Replace exact text in a sandbox file.' if compact else 'Replace exact text in a UTF-8 sandbox file. Read the file first and copy exact_old from the observed content.' + desc_suffix),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'path': {'type': 'string'},
                        'exact_old': {'type': 'string'},
                        'new_text': {'type': 'string'},
                        'count': {'type': 'integer'},
                    },
                    'required': ['path', 'exact_old', 'new_text'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'sandbox_publish_files',
                'description': ('Publish sandbox files as downloadable artifacts.' if compact else 'Publish existing files from the persistent coding sandbox as downloadable artifacts. Use this as the only final file-delivery step after sandbox_run / sandbox_write_file / sandbox_write_files / sandbox_create_office_file / sandbox_replace_text and validation.' + desc_suffix),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'paths': {'type': 'array', 'items': {'type': 'string'}},
                        'bundle_name': {'type': 'string'},
                        'answer': {'type': 'string'},
                        'force_zip': {'type': 'boolean'},
                        'max_total_bytes': {'type': 'integer'},
                    },
                    'required': ['paths'],
                    'additionalProperties': False,
                },
            },
        },
        {
            'type': 'function',
            'function': {
                'name': 'sandbox_import_files',
                'description': ('Import uploaded/generated files into /mnt/data.' if compact else 'Copy current uploaded/generated files, account registry files, or zip projects into the sandbox before reading, running, modifying, or publishing. Use extract_archives for zip projects.'),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'files': {'type': 'array', 'items': {'type': 'object'}},
                        'target_filename': {'type': 'string'},
                        'registry_file_id': {'type': 'string'},
                        'registry_id': {'type': 'string'},
                        'file_id': {'type': 'string'},
                        'account_file_id': {'type': 'string'},
                        'id': {'type': 'string'},
                        'destination': {'type': 'string'},
                        'extract_archives': {'type': 'boolean'},
                        'continue_on_error': {'type': 'boolean'},
                    },
                    'additionalProperties': False,
                },
            },
        },
    ]
    return _normalize_tool_schemas_for_endpoint(tools, endpoint_mode='chat_completions')


SANDBOX_TOOL_NAMES = {'sandbox_list_files', 'sandbox_resolve_file_context', 'sandbox_diff_files', 'sandbox_read_file', 'sandbox_analyze_file_images', 'sandbox_write_file', 'sandbox_write_files', 'sandbox_create_office_file', 'sandbox_replace_text', 'sandbox_import_files', 'sandbox_run', 'sandbox_publish_files'}
