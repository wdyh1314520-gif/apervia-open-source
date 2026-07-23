# Split loader for image generation and file-delivery backend.
# Keep these files in order; they share app3.py globals and later parts depend on earlier helpers.
_exec_split_file('app3_parts/media/image_client_core_part.py')
_exec_split_file('app3_parts/media/image_generation_settings_part.py')
_exec_split_file('app3_parts/media/image_generation_http_part.py')
_exec_split_file('app3_parts/media/image_generation_artifact_store_part.py')
_exec_split_file('app3_parts/media/image_provider_mirror_part.py')
_exec_split_file('app3_parts/media/image_responses_native_part.py')
_exec_split_file('app3_parts/media/image_provider_dispatch_part.py')
_exec_split_file('app3_parts/media/file_delivery_responses_adapter_part.py')
_exec_split_file('app3_parts/media/file_delivery_artifact_core_part.py')
_exec_split_file('app3_parts/media/file_delivery_gate_part.py')
_exec_split_file('app3_parts/media/file_delivery_stream_preview_part.py')
