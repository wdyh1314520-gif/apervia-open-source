# Split loader for auth core state, stores, account runtime, and login-code helpers.
# Keep these files in order; they share app3.py globals and later parts depend on earlier helpers.
_exec_split_file('app3_parts/auth/platform_auth_core_state_part.py')
_exec_split_file('app3_parts/auth/platform_auth_chat_compaction_part.py')
_exec_split_file('app3_parts/auth/platform_auth_registration_config_part.py')
_exec_split_file('app3_parts/auth/platform_auth_email_store_part.py')
_exec_split_file('app3_parts/auth/platform_auth_chat_store_part.py')
_exec_split_file('app3_parts/auth/platform_auth_user_accounts_part.py')
_exec_split_file('app3_parts/auth/platform_auth_email_runtime_part.py')
