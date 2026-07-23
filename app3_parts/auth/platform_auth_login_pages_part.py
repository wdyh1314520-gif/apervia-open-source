# Split loader for auth login and admin HTML renderers.
# Keep these renderers isolated by page so template changes stay local.
_exec_split_file('app3_parts/auth/platform_auth_legal_doc_page_part.py')
_exec_split_file('app3_parts/auth/platform_auth_blacklist_admin_page_part.py')
_exec_split_file('app3_parts/auth/platform_auth_rate_limit_admin_page_part.py')
