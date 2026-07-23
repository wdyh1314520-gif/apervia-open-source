#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${APP3_MCP_VENV_DIR:-${ROOT_DIR}/.venv-mcp}"
INDEX_URL="${APP3_MCP_PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
ACTION="install"

usage() {
  cat <<'EOF'
Usage: bash mcp_client/install.sh [--install|--check|--test|--start]

Install and operate Apervia's isolated MCP client bridge.

Actions:
  --install  Create .venv-mcp and install locked dependencies (default).
  --check    Verify the isolated environment and installed dependencies.
  --test     Run the MCP client bridge test suite.
  --start    Start the loopback MCP client bridge.
  -h, --help Show this help.

Environment variables:
  APP3_MCP_VENV_DIR       Virtual environment path (default: .venv-mcp).
  APP3_MCP_PIP_INDEX_URL Mirror used by pip.
  APP3_MCP_BRIDGE_PORT   Loopback bridge port (default: 8766).
  PYTHON                  Python executable used to create the environment.

The bridge requires APP3_MCP_BRIDGE_SECRET in both app3 and this process.
This script never creates credentials, reads .env files, starts tunnels, or
exposes an MCP server to the public Internet.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --install) ACTION="install" ;;
    --check) ACTION="check" ;;
    --test) ACTION="test" ;;
    --start) ACTION="start" ;;
    -h|--help) usage; exit 0 ;;
    *)
      printf 'Unknown argument: %s\n\n' "$arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

find_python() {
  if [[ -n "${PYTHON:-}" ]]; then
    printf '%s\n' "$PYTHON"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
    return
  fi
  printf 'Python 3.11+ is required.\n' >&2
  exit 1
}

venv_python() {
  if [[ -x "${VENV_DIR}/Scripts/python.exe" ]]; then
    printf '%s\n' "${VENV_DIR}/Scripts/python.exe"
  else
    printf '%s\n' "${VENV_DIR}/bin/python"
  fi
}

require_venv() {
  local python_bin
  python_bin="$(venv_python)"
  if [[ ! -x "$python_bin" ]]; then
    printf 'MCP environment is missing: %s\n' "$VENV_DIR" >&2
    printf 'Run bash mcp_client/install.sh --install first.\n' >&2
    exit 1
  fi
  printf '%s\n' "$python_bin"
}

install_bridge() {
  local bootstrap_python python_bin
  bootstrap_python="$(find_python)"
  if [[ ! -d "$VENV_DIR" ]]; then
    "$bootstrap_python" -m venv "$VENV_DIR"
  fi
  python_bin="$(require_venv)"
  "$python_bin" -m pip install \
    --disable-pip-version-check \
    --index-url "$INDEX_URL" \
    -r "${ROOT_DIR}/mcp_client/requirements.txt"
  "$python_bin" -m pip check
  printf 'Apervia MCP client dependencies are ready in %s\n' "$VENV_DIR"
}

cd "$ROOT_DIR"

case "$ACTION" in
  install)
    install_bridge
    ;;
  check)
    PYTHON_BIN="$(require_venv)"
    "$PYTHON_BIN" -m pip check
    "$PYTHON_BIN" -c "import mcp, httpx, starlette, uvicorn"
    printf 'Apervia MCP client environment check passed.\n'
    ;;
  test)
    PYTHON_BIN="$(require_venv)"
    "$PYTHON_BIN" -m unittest discover -s tests -p 'test_mcp_client_bridge.py' -v
    ;;
  start)
    PYTHON_BIN="$(require_venv)"
    "$PYTHON_BIN" -m pip check
    exec "$PYTHON_BIN" -m mcp_client.bridge
    ;;
esac
