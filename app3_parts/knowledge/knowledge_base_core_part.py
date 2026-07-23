# Split loader for knowledge base core storage, search, context, and cleanup helpers.
# Keep these files in order; later context/read helpers depend on storage and search helpers.
_exec_split_file('app3_parts/knowledge/knowledge_context_runtime_part.py')
_exec_split_file('app3_parts/knowledge/knowledge_db_spaces_part.py')
_exec_split_file('app3_parts/knowledge/knowledge_document_import_part.py')
_exec_split_file('app3_parts/knowledge/knowledge_search_part.py')
_exec_split_file('app3_parts/knowledge/knowledge_read_context_part.py')
_exec_split_file('app3_parts/knowledge/knowledge_context_prepare_part.py')
_exec_split_file('app3_parts/knowledge/knowledge_cleanup_part.py')
_exec_split_file('app3_parts/knowledge/knowledge_web_import_part.py')
