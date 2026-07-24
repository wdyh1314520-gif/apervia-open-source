"""Load authentication storage and account helpers in dependency order."""

_exec_split_file('app3_parts/auth/platform_auth_core_state_part.py')
_exec_split_file('app3_parts/auth/platform_auth_chat_compaction_part.py')
_exec_split_file('app3_parts/auth/platform_auth_user_store_part.py')
_exec_split_file('app3_parts/auth/platform_auth_chat_store_part.py')
_exec_split_file('app3_parts/auth/platform_auth_user_accounts_part.py')
_exec_split_file('app3_parts/auth/platform_auth_session_helpers_part.py')
