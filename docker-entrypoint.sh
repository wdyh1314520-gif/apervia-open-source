#!/bin/sh
set -eu

data_dir="${APP_DATA_DIR:-/data}"

mkdir -p \
  "$data_dir/uploads_local" \
  "$data_dir/uploads_public" \
  "$data_dir/generated_local" \
  "$data_dir/generated_public" \
  "$data_dir/remote_image_cache" \
  "$data_dir/file_text_store" \
  "$data_dir/favicon_cache" \
  "$data_dir/sandboxes" \
  "$data_dir/sandbox_python_packages" \
  "$data_dir/platform_admin_backups" \
  "$data_dir/platform_admin_recycle" \
  "$data_dir/home" \
  "$data_dir/cache"

if [ ! -w "$data_dir" ]; then
  echo "APP_DATA_DIR is not writable: $data_dir" >&2
  exit 1
fi

if [ "$#" -eq 0 ]; then
  set -- python /app/app3.py
fi

exec "$@"
