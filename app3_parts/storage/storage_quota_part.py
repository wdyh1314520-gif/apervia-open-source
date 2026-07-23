# Split loader for storage quota, platform-admin, and storage-admin backend.
# Keep these files in order; they share app3.py globals and later parts depend on earlier helpers.
_exec_split_file('app3_parts/storage/storage_quota_core_part.py')
_exec_split_file('app3_parts/storage/storage_quota_reporting_part.py')
_exec_split_file('app3_parts/storage/platform_admin_system_part.py')
_exec_split_file('app3_parts/storage/platform_admin_inventory_part.py')
_exec_split_file('app3_parts/storage/platform_admin_audit_recycle_part.py')
_exec_split_file('app3_parts/storage/platform_admin_account_purge_part.py')
_exec_split_file('app3_parts/storage/platform_admin_chat_backup_part.py')
_exec_split_file('app3_parts/storage/platform_admin_devtools_part.py')
_exec_split_file('app3_parts/storage/platform_admin_ui_part.py')
_exec_split_file('app3_parts/storage/platform_admin_routes_part.py')
_exec_split_file('app3_parts/storage/storage_admin_routes_part.py')
