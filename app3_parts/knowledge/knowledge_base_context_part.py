# Split loader for knowledge, file-library, and history-file context backend.
# Keep these files in order; they share app3.py globals and later parts depend on earlier helpers.
_exec_split_file('app3_parts/knowledge/knowledge_base_core_part.py')
_exec_split_file('app3_parts/knowledge/file_library_part.py')
_exec_split_file('app3_parts/knowledge/history_file_context_part.py')
