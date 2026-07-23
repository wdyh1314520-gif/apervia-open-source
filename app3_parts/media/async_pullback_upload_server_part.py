# Split loader for async chat jobs, image pullback, upload, voice, read-aloud, and startup routes.
# Keep these files in order; they share app3.py globals and later parts depend on earlier helpers.
_exec_split_file('app3_parts/media/chat_async_jobs_part.py')
_exec_split_file('app3_parts/media/image_pullback_routes_part.py')
_exec_split_file('app3_parts/media/chat_async_routes_part.py')
_exec_split_file('app3_parts/media/misc_api_routes_part.py')
_exec_split_file('app3_parts/media/upload_routes_part.py')
_exec_split_file('app3_parts/media/voice_transcribe_part.py')
_exec_split_file('app3_parts/media/read_aloud_part.py')
_exec_split_file('app3_parts/media/legacy_chat_stream_route_part.py')
_exec_split_file('app3_parts/media/waitress_startup_part.py')
