# Split loader for web search enrichment, visual context, and planner helpers.
# Keep these files in order; they share app3.py globals and later parts depend on earlier helpers.
_exec_split_file('app3_parts/web/web_enrichment_base_part.py')
_exec_split_file('app3_parts/web/web_search_provider_core_part.py')
_exec_split_file('app3_parts/web/web_visual_context_part.py')
_exec_split_file('app3_parts/web/web_image_search_providers_part.py')
_exec_split_file('app3_parts/web/web_visual_reply_planner_part.py')
_exec_split_file('app3_parts/web/web_search_provider_chain_part.py')
_exec_split_file('app3_parts/web/web_search_multi_planner_part.py')
