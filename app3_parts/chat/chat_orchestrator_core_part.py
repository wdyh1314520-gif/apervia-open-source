# Split loader for chat orchestrator core helpers.
# Keep these files in order; later planner and streaming helpers depend on earlier context formatters.
_exec_split_file('app3_parts/chat/chat_orchestrator_file_edit_context_part.py')
_exec_split_file('app3_parts/chat/chat_orchestrator_evidence_format_part.py')
_exec_split_file('app3_parts/chat/chat_orchestrator_message_context_part.py')
_exec_split_file('app3_parts/chat/chat_orchestrator_visual_payload_part.py')
_exec_split_file('app3_parts/chat/chat_orchestrator_prefetch_routing_part.py')
_exec_split_file('app3_parts/chat/chat_orchestrator_web_planner_part.py')
_exec_split_file('app3_parts/chat/chat_orchestrator_soft_hint_part.py')
_exec_split_file('app3_parts/chat/agent_stream_web_overrides_part.py')
