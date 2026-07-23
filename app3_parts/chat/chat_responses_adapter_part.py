# Split loader for Responses API compatibility adapter helpers.
# Keep these files in order; they share app3.py globals and later helpers depend on earlier ones.
_exec_split_file('app3_parts/chat/chat_responses_runtime_model_part.py')
_exec_split_file('app3_parts/chat/chat_context_compression_part.py')
_exec_split_file('app3_parts/chat/chat_responses_compat_chunks_part.py')
_exec_split_file('app3_parts/chat/chat_responses_input_conversion_part.py')
_exec_split_file('app3_parts/chat/chat_prompt_cache_part.py')
_exec_split_file('app3_parts/chat/chat_responses_non_stream_part.py')
_exec_split_file('app3_parts/chat/chat_responses_sse_reasoning_part.py')
_exec_split_file('app3_parts/chat/chat_responses_sse_stream_part.py')
