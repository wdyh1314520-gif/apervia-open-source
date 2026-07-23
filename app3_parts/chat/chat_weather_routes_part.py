# Split loader for chat public routes, weather card logic, and stream route.
# Keep public routes before weather helpers and stream route so existing endpoint registration order stays stable.
_exec_split_file('app3_parts/chat/chat_public_api_routes_part.py')
_exec_split_file('app3_parts/chat/weather_card_core_part.py')
_exec_split_file('app3_parts/chat/payload_file_attachments_part.py')
_exec_split_file('app3_parts/chat/chat_stream_route_part.py')
