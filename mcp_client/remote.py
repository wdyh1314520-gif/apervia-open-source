"""Official-SDK remote MCP connection, discovery, and invocation helpers."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client


class RemoteMcpError(RuntimeError):
    pass


def normalize_server(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    row = dict(raw or {})
    transport = str(row.get("transport") or "auto").strip().lower()
    if transport not in {"auto", "streamable_http", "sse"}:
        transport = "auto"
    auth_type = str(row.get("auth_type") or "none").strip().lower()
    if auth_type not in {"none", "bearer", "oauth"}:
        auth_type = "none"
    return {
        "id": str(row.get("id") or row.get("server_id") or "server").strip()[:80],
        "name": str(row.get("name") or row.get("id") or "MCP Server").strip()[:120],
        "url": str(row.get("url") or row.get("server_url") or "").strip()[:2000],
        "transport": transport,
        "auth_type": auth_type,
        "bearer_token": str(row.get("access_token") or row.get("bearer_token") or row.get("authorization") or "").strip()[:12000],
        "allow_insecure_local": bool(row.get("allow_insecure_local")),
        "enabled_tool_names": [str(item or "").strip()[:200] for item in (row.get("enabled_tool_names") or []) if str(item or "").strip()][:50],
    }


def _resolved_addresses(hostname: str) -> list[Any]:
    try:
        return list({ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)})
    except Exception as exc:
        raise RemoteMcpError("mcp_server_dns_failed") from exc


def validate_server_url(server: dict[str, Any]) -> str:
    url = str(server.get("url") or "").strip()
    parsed = urlsplit(url)
    host = str(parsed.hostname or "").strip().lower()
    if not host or parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise RemoteMcpError("mcp_server_url_invalid")
    addresses = _resolved_addresses(host)
    is_loopback = bool(addresses) and all(address.is_loopback for address in addresses)
    if parsed.scheme == "http" and not (is_loopback and bool(server.get("allow_insecure_local"))):
        raise RemoteMcpError("mcp_server_https_required")
    if any(address.is_private or address.is_reserved or address.is_link_local or address.is_multicast or address.is_unspecified for address in addresses):
        if not (is_loopback and bool(server.get("allow_insecure_local"))):
            raise RemoteMcpError("mcp_server_private_network_blocked")
    return url


def _headers(server: dict[str, Any]) -> dict[str, str]:
    headers = {"Accept": "application/json, text/event-stream"}
    if server.get("auth_type") in {"bearer", "oauth"}:
        token = str(server.get("bearer_token") or "").strip()
        if not token:
            raise RemoteMcpError("mcp_bearer_token_required")
        headers["Authorization"] = "Bearer " + token
    return headers


def _direct_httpx_client(**kwargs: Any) -> httpx.AsyncClient:
    kwargs["follow_redirects"] = False
    kwargs["trust_env"] = False
    return httpx.AsyncClient(**kwargs)


def _origin(url: str) -> str:
    parsed = urlsplit(str(url or ""))
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _well_known_authorization_url(issuer: str) -> str:
    parsed = urlsplit(str(issuer or ""))
    suffix = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, "/.well-known/oauth-authorization-server" + suffix, "", ""))


async def _safe_json_get(client: httpx.AsyncClient, url: str, server: dict[str, Any], *, optional: bool = False) -> dict[str, Any]:
    validate_server_url({"url": url, "allow_insecure_local": bool(server.get("allow_insecure_local"))})
    response = await client.get(url, headers={"Accept": "application/json"})
    if optional and response.status_code == 404:
        return {}
    if response.status_code >= 400:
        raise RemoteMcpError(f"mcp_oauth_metadata_http_{response.status_code}")
    content = await response.aread()
    if len(content) > 262144:
        raise RemoteMcpError("mcp_oauth_metadata_too_large")
    try:
        data = json.loads(content or b"{}")
    except Exception as exc:
        raise RemoteMcpError("mcp_oauth_metadata_invalid") from exc
    if not isinstance(data, dict):
        raise RemoteMcpError("mcp_oauth_metadata_invalid")
    return data


async def discover_oauth(server_raw: dict[str, Any]) -> dict[str, Any]:
    server = normalize_server(server_raw)
    server_url = await asyncio.to_thread(validate_server_url, server)
    origin = _origin(server_url)
    timeout = httpx.Timeout(20, read=20)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        response = await client.get(server_url, headers={"Accept": "application/json, text/event-stream"})
        www_authenticate = str(response.headers.get("WWW-Authenticate") or "")
        resource_metadata_url = ""
        import re as _re
        match = _re.search(r'resource_metadata\s*=\s*"([^"]+)"', www_authenticate, flags=_re.I)
        if match:
            resource_metadata_url = str(match.group(1) or "").strip()
        if not resource_metadata_url:
            resource_metadata_url = origin + "/.well-known/oauth-protected-resource"
        protected = await _safe_json_get(client, resource_metadata_url, server)
        authorization_servers = protected.get("authorization_servers") if isinstance(protected.get("authorization_servers"), list) else []
        issuer = str((authorization_servers or [origin])[0] or origin).strip().rstrip("/")
        metadata_url = _well_known_authorization_url(issuer)
        metadata = await _safe_json_get(client, metadata_url, server)
        authorization_endpoint = str(metadata.get("authorization_endpoint") or "").strip()
        token_endpoint = str(metadata.get("token_endpoint") or "").strip()
        if not authorization_endpoint or not token_endpoint:
            raise RemoteMcpError("mcp_oauth_endpoints_missing")
        validate_server_url({"url": authorization_endpoint, "allow_insecure_local": bool(server.get("allow_insecure_local"))})
        validate_server_url({"url": token_endpoint, "allow_insecure_local": bool(server.get("allow_insecure_local"))})
        methods = metadata.get("code_challenge_methods_supported") if isinstance(metadata.get("code_challenge_methods_supported"), list) else []
        if methods and "S256" not in methods:
            raise RemoteMcpError("mcp_oauth_pkce_s256_required")
        card = await _safe_json_get(client, origin + "/.well-known/mcp.json", server, optional=True)
    return {
        "issuer": str(metadata.get("issuer") or issuer).strip(),
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "registration_endpoint": str(metadata.get("registration_endpoint") or "").strip(),
        "token_endpoint_auth_methods_supported": [str(item or "").strip() for item in (metadata.get("token_endpoint_auth_methods_supported") or []) if str(item or "").strip()],
        "scopes_supported": [str(item or "").strip() for item in (metadata.get("scopes_supported") or []) if str(item or "").strip()],
        "resource": str(protected.get("resource") or origin).strip(),
        "resource_metadata_url": resource_metadata_url,
        "server_card": card,
    }


async def exchange_oauth_code(payload: dict[str, Any]) -> dict[str, Any]:
    token_endpoint = str(payload.get("token_endpoint") or "").strip()
    server = normalize_server(payload.get("server") if isinstance(payload.get("server"), dict) else {})
    validate_server_url({"url": token_endpoint, "allow_insecure_local": bool(server.get("allow_insecure_local"))})
    client_id = str(payload.get("client_id") or "").strip()[:500]
    client_secret = str(payload.get("client_secret") or "").strip()[:4000]
    form = {
        "grant_type": "authorization_code",
        "code": str(payload.get("code") or "").strip()[:4000],
        "redirect_uri": str(payload.get("redirect_uri") or "").strip()[:2000],
        "code_verifier": str(payload.get("code_verifier") or "").strip()[:256],
        "client_id": client_id,
    }
    resource = str(payload.get("resource") or "").strip()[:2000]
    if resource:
        form["resource"] = resource
    if client_secret:
        form["client_secret"] = client_secret
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=30), follow_redirects=False, trust_env=False) as client:
        response = await client.post(token_endpoint, data=form, headers={"Accept": "application/json"})
        content = await response.aread()
    if len(content) > 262144:
        raise RemoteMcpError("mcp_oauth_token_response_too_large")
    try:
        data = json.loads(content or b"{}")
    except Exception as exc:
        raise RemoteMcpError("mcp_oauth_token_response_invalid") from exc
    if response.status_code >= 400 or not isinstance(data, dict) or not str(data.get("access_token") or "").strip():
        message = str((data or {}).get("error_description") or (data or {}).get("error") or f"HTTP {response.status_code}")
        raise RemoteMcpError("mcp_oauth_token_exchange_failed: " + message[:300])
    return {
        "access_token": str(data.get("access_token") or "").strip()[:12000],
        "refresh_token": str(data.get("refresh_token") or "").strip()[:12000],
        "token_type": str(data.get("token_type") or "Bearer").strip()[:40],
        "expires_in": max(0, min(int(data.get("expires_in") or 0), 31536000)),
        "scope": str(data.get("scope") or "").strip()[:2000],
    }


@asynccontextmanager
async def open_session(server_raw: dict[str, Any], timeout_seconds: int = 30):
    server = normalize_server(server_raw)
    url = await asyncio.to_thread(validate_server_url, server)
    headers = _headers(server)
    timeout = max(5, min(int(timeout_seconds), 90))

    transport = server["transport"]
    if transport in {"auto", "streamable_http"}:
        async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(timeout, read=timeout), follow_redirects=False, trust_env=False) as client:
            async with streamable_http_client(url, http_client=client, terminate_on_close=True) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream, read_timeout_seconds=timedelta(seconds=timeout)) as session:
                    await session.initialize()
                    yield session
        return
    async with sse_client(url, headers=headers, timeout=timeout, sse_read_timeout=timeout, httpx_client_factory=_direct_httpx_client) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream, read_timeout_seconds=timedelta(seconds=timeout)) as session:
            await session.initialize()
            yield session


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="json", by_alias=True, exclude_none=True))
    return dict(value or {}) if isinstance(value, dict) else {}


async def list_tools(server: dict[str, Any]) -> list[dict[str, Any]]:
    async with open_session(server) as session:
        result = await session.list_tools()
    tools: list[dict[str, Any]] = []
    total_size = 0
    for item in (result.tools or []):
        tool = _model_dump(item)
        encoded = json.dumps(tool, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(encoded) > 131072:
            continue
        if total_size + len(encoded) > 1048576:
            break
        tools.append(tool)
        total_size += len(encoded)
        if len(tools) >= 50:
            break
    return tools


def _tool_is_read_only(tool: dict[str, Any]) -> bool:
    annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
    return bool(annotations.get("readOnlyHint")) and not bool(annotations.get("destructiveHint"))


async def call_tool(server: dict[str, Any], tool_name: str, arguments: dict[str, Any], *, permission_granted: bool = False) -> dict[str, Any]:
    async with open_session(server) as session:
        listed = await session.list_tools()
        tools = [_model_dump(tool) for tool in (listed.tools or [])]
        current = next((tool for tool in tools if str(tool.get("name") or "") == tool_name), None)
        if not current:
            raise RemoteMcpError("mcp_tool_not_found")
        enabled_names = {str(item or "").strip() for item in (server.get("enabled_tool_names") or []) if str(item or "").strip()}
        if enabled_names and tool_name not in enabled_names:
            raise RemoteMcpError("mcp_tool_disabled")
        if not _tool_is_read_only(current) and not bool(permission_granted):
            raise RemoteMcpError("mcp_tool_permission_required")
        result = await session.call_tool(tool_name, dict(arguments or {}), read_timeout_seconds=timedelta(seconds=60))
    row = _model_dump(result)
    structured = row.get("structuredContent") or row.get("structured_content")
    output = {
        "ok": not bool(row.get("isError") or row.get("is_error")),
        "_kind": "mcp_tool_result",
        "server": str(server.get("name") or server.get("id") or "MCP"),
        "tool": tool_name,
        "structured_content": structured if isinstance(structured, (dict, list)) else None,
        "content": row.get("content") if isinstance(row.get("content"), list) else [],
    }
    encoded = json.dumps(output, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(encoded) > 64000:
        return {"ok": output["ok"], "_kind": "mcp_tool_result", "tool": tool_name, "truncated": True, "output_preview": encoded[:64000]}
    return output
