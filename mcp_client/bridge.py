"""Loopback-only bridge that lets app3 use the official MCP client SDK in isolation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .remote import RemoteMcpError, call_tool, discover_oauth, exchange_oauth_code, list_tools, normalize_server
from .signing import ReplayNonceStore, verify_request_signature


LOGGER = logging.getLogger("apervia.mcp_client")
NONCES = ReplayNonceStore()
LIMITER = asyncio.Semaphore(max(1, min(int(os.getenv("APP3_MCP_MAX_CONCURRENCY", "8") or 8), 32)))


_REMOTE_ERROR_MESSAGES = {
    "mcp_server_dns_failed": "MCP 服务器域名解析失败，请检查服务器地址。",
    "mcp_server_url_invalid": "MCP Server URL 无效。",
    "mcp_server_https_required": "远程 MCP 服务器必须使用 HTTPS。",
    "mcp_server_private_network_blocked": "该 MCP 地址指向受限的内网地址。",
    "mcp_bearer_token_required": "该 MCP 服务器需要访问令牌，请先填写令牌或完成 OAuth 授权。",
}


def _sanitize_exception_message(value: object) -> str:
    """Remove likely credentials before returning a dependency error to the UI."""
    text = str(value or "").strip()
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[已隐藏]", text)
    text = re.sub(
        r"(?i)([?&](?:access_token|token|api_key|key|secret|authorization)=)[^&#\s]+",
        r"\1[已隐藏]",
        text,
    )
    return text[:1000]


def _exception_leaves(exc: BaseException) -> list[BaseException]:
    leaves: list[BaseException] = []
    pending = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        children = getattr(current, "exceptions", None)
        if isinstance(children, (tuple, list)) and children:
            pending[0:0] = [child for child in children if isinstance(child, BaseException)]
            continue
        leaves.append(current)
    return leaves or [exc]


def _describe_exception_leaf(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = int(getattr(getattr(exc, "response", None), "status_code", 0) or 0)
        if status == 401:
            return "MCP 服务器拒绝连接（HTTP 401）：请检查认证方式和访问令牌，或先完成 OAuth 授权。"
        if status == 403:
            return "MCP 服务器拒绝访问（HTTP 403）：当前账号或令牌没有所需权限。"
        if status == 404:
            return "未找到 MCP 接口（HTTP 404）：请检查 Server URL 是否包含正确的 /mcp 路径。"
        if status in {405, 406, 415}:
            return f"MCP 服务器不接受当前连接协议（HTTP {status}），请检查传输类型和接口地址。"
        if status == 429:
            return "MCP 服务器请求过于频繁（HTTP 429），请稍后重试。"
        if status >= 500:
            return f"MCP 服务器暂时不可用（HTTP {status}）。"
        if status:
            return f"MCP 服务器返回 HTTP {status}。"
    if isinstance(exc, httpx.TimeoutException) or isinstance(exc, TimeoutError):
        return "连接 MCP 服务器超时，请检查网络和服务器状态。"
    if isinstance(exc, httpx.ConnectError) or isinstance(exc, ConnectionError):
        return "无法连接 MCP 服务器，请检查地址、网络和服务器状态。"
    raw = _sanitize_exception_message(exc)
    if isinstance(exc, RemoteMcpError) and raw in _REMOTE_ERROR_MESSAGES:
        return _REMOTE_ERROR_MESSAGES[raw]
    if raw and raw not in {"unhandled errors in a TaskGroup (1 sub-exception)", "unhandled errors in a TaskGroup"}:
        return raw
    return type(exc).__name__


def _describe_exception(exc: BaseException) -> str:
    messages: list[str] = []
    for leaf in _exception_leaves(exc):
        if isinstance(leaf, asyncio.CancelledError):
            continue
        message = _describe_exception_leaf(leaf)
        if message and message not in messages:
            messages.append(message)
        if len(messages) >= 3:
            break
    return "；".join(messages)[:1000] or "MCP 连接失败。"


def _secret() -> str:
    return str(os.getenv("APP3_MCP_BRIDGE_SECRET", "") or "").strip()


async def _authorize(request: Request, body: bytes) -> tuple[bool, str]:
    client_host = str(getattr(request.client, "host", "") or "")
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return False, "loopback_required"
    ok, error = verify_request_signature(
        _secret(), request.method, request.url.path,
        request.headers.get("X-App3-Mcp-Timestamp", ""),
        request.headers.get("X-App3-Mcp-Nonce", ""),
        body,
        request.headers.get("X-App3-Mcp-Signature", ""),
    )
    if not ok:
        return False, error
    nonce = request.headers.get("X-App3-Mcp-Nonce", "")
    return (True, "") if NONCES.consume(nonce) else (False, "signature_nonce_replayed")


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "apervia-mcp-client"})


async def list_route(request: Request) -> JSONResponse:
    body = await request.body()
    if len(body) > 1048576:
        return JSONResponse({"ok": False, "error": "request_too_large"}, status_code=413)
    ok, error = await _authorize(request, body)
    if not ok:
        return JSONResponse({"ok": False, "error": error}, status_code=403)
    try:
        payload = json.loads(body or b"{}")
        server = normalize_server(payload.get("server") if isinstance(payload, dict) else {})
        async with LIMITER:
            tools = await list_tools(server)
        return JSONResponse({"ok": True, "tools": tools})
    except (RemoteMcpError, ValueError, TypeError) as exc:
        return JSONResponse({"ok": False, "error": str(exc), "message": str(exc)}, status_code=400)
    except Exception as exc:
        LOGGER.warning("MCP list failed: %s", type(exc).__name__)
        return JSONResponse({"ok": False, "error": "mcp_list_failed", "message": _describe_exception(exc)}, status_code=502)


async def call_route(request: Request) -> JSONResponse:
    body = await request.body()
    if len(body) > 1048576:
        return JSONResponse({"ok": False, "error": "request_too_large"}, status_code=413)
    ok, error = await _authorize(request, body)
    if not ok:
        return JSONResponse({"ok": False, "error": error}, status_code=403)
    try:
        payload = json.loads(body or b"{}")
        server = normalize_server(payload.get("server") if isinstance(payload, dict) else {})
        name = str(payload.get("tool_name") or "").strip()[:200]
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        if not name:
            raise RemoteMcpError("mcp_tool_name_required")
        async with LIMITER:
            result = await call_tool(server, name, arguments, permission_granted=bool(payload.get("permission_granted")))
        return JSONResponse({"ok": True, "result": result})
    except (RemoteMcpError, ValueError, TypeError) as exc:
        return JSONResponse({"ok": False, "error": str(exc), "message": str(exc)}, status_code=400)
    except Exception as exc:
        LOGGER.warning("MCP call failed: %s", type(exc).__name__)
        return JSONResponse({"ok": False, "error": "mcp_call_failed", "message": _describe_exception(exc)}, status_code=502)


async def oauth_discover_route(request: Request) -> JSONResponse:
    body = await request.body()
    if len(body) > 1048576:
        return JSONResponse({"ok": False, "error": "request_too_large"}, status_code=413)
    ok, error = await _authorize(request, body)
    if not ok:
        return JSONResponse({"ok": False, "error": error}, status_code=403)
    try:
        payload = json.loads(body or b"{}")
        async with LIMITER:
            oauth = await discover_oauth(payload.get("server") if isinstance(payload, dict) else {})
        return JSONResponse({"ok": True, "oauth": oauth})
    except (RemoteMcpError, ValueError, TypeError) as exc:
        return JSONResponse({"ok": False, "error": str(exc), "message": str(exc)}, status_code=400)
    except Exception as exc:
        LOGGER.warning("MCP OAuth discovery failed: %s", type(exc).__name__)
        return JSONResponse({"ok": False, "error": "mcp_oauth_discovery_failed", "message": str(exc)[:500]}, status_code=502)


async def oauth_exchange_route(request: Request) -> JSONResponse:
    body = await request.body()
    if len(body) > 1048576:
        return JSONResponse({"ok": False, "error": "request_too_large"}, status_code=413)
    ok, error = await _authorize(request, body)
    if not ok:
        return JSONResponse({"ok": False, "error": error}, status_code=403)
    try:
        payload = json.loads(body or b"{}")
        async with LIMITER:
            tokens = await exchange_oauth_code(payload if isinstance(payload, dict) else {})
        return JSONResponse({"ok": True, "tokens": tokens})
    except (RemoteMcpError, ValueError, TypeError) as exc:
        return JSONResponse({"ok": False, "error": str(exc), "message": str(exc)}, status_code=400)
    except Exception as exc:
        LOGGER.warning("MCP OAuth exchange failed: %s", type(exc).__name__)
        return JSONResponse({"ok": False, "error": "mcp_oauth_exchange_failed", "message": str(exc)[:500]}, status_code=502)


def create_app() -> Starlette:
    return Starlette(routes=[
        Route("/healthz", health, methods=["GET"]),
        Route("/internal/list", list_route, methods=["POST"]),
        Route("/internal/call", call_route, methods=["POST"]),
        Route("/internal/oauth/discover", oauth_discover_route, methods=["POST"]),
        Route("/internal/oauth/exchange", oauth_exchange_route, methods=["POST"]),
    ])


def _start_parent_monitor() -> None:
    """让自动启动的 bridge 在 app3 父进程退出后自行结束，避免遗留孤儿进程。"""
    try:
        parent_pid = int(os.getenv("APP3_MCP_PARENT_PID", "0") or 0)
    except Exception:
        parent_pid = 0
    if parent_pid <= 0:
        return

    def parent_alive() -> bool:
        if os.name == "nt":
            try:
                import ctypes
                process_query_limited_information = 0x1000
                still_active = 259
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(process_query_limited_information, False, parent_pid)
                if not handle:
                    return False
                exit_code = ctypes.c_ulong(0)
                ok = bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)))
                kernel32.CloseHandle(handle)
                return ok and int(exit_code.value) == still_active
            except Exception:
                return False
        try:
            os.kill(parent_pid, 0)
            return True
        except Exception:
            return False

    def monitor() -> None:
        while True:
            time.sleep(2.0)
            if not parent_alive():
                os._exit(0)

    threading.Thread(target=monitor, name="mcp-parent-monitor", daemon=True).start()


def main() -> None:
    if len(_secret()) < 32:
        raise RuntimeError("APP3_MCP_BRIDGE_SECRET must contain at least 32 characters")
    _start_parent_monitor()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(create_app(), host="127.0.0.1", port=max(1, min(int(os.getenv("APP3_MCP_BRIDGE_PORT", "8766") or 8766), 65535)), workers=1, access_log=False)


if __name__ == "__main__":
    main()
