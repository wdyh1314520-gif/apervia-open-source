# Split loader for account runtime, health, chat-sync realtime, personalization memory, and API profile helpers.
# Keep these files in order; they share app3.py globals and later parts depend on earlier helpers.
_exec_split_file('app3_parts/account/request_runtime_part.py')
_exec_split_file('app3_parts/account/request_admission_health_part.py')
_exec_split_file('app3_parts/account/chat_sync_realtime_part.py')
_exec_split_file('app3_parts/account/chat_share_part.py')
_exec_split_file('app3_parts/account/personalization_memory_part.py')
_exec_split_file('app3_parts/account/model_thinking_api_profiles_part.py')
