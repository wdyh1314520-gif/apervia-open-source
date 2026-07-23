# Split loader for web fetch, cloud connect, code runner, and text decoding helpers.
# Keep these files in order; they share app3.py globals and later parts depend on earlier helpers.
_exec_split_file('app3_parts/web/web_fetch_basic_part.py')
_exec_split_file('app3_parts/web/web_fetch_price_deep_part.py')
_exec_split_file('app3_parts/web/web_fetch_github_content_part.py')
_exec_split_file('app3_parts/web/web_render_fallback_part.py')
_exec_split_file('app3_parts/web/cloud_connect_part.py')
_exec_split_file('app3_parts/web/code_run_part.py')
_exec_split_file('app3_parts/web/file_text_reader_part.py')
