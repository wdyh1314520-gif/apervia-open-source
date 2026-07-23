from __future__ import annotations

import json
import os
import secrets
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from mcp_client.bridge import create_app
from mcp_client.remote import RemoteMcpError, validate_server_url
from mcp_client.signing import ReplayNonceStore, sign_request


SECRET = "test-mcp-bridge-secret-0123456789abcdef"


def signed_headers(path: str, body: bytes, nonce: str | None = None) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = nonce or secrets.token_urlsafe(18)
    return {
        "Content-Type": "application/json",
        "X-App3-Mcp-Timestamp": timestamp,
        "X-App3-Mcp-Nonce": nonce,
        "X-App3-Mcp-Signature": sign_request(SECRET, "POST", path, timestamp, nonce, body),
    }


class McpClientBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {"APP3_MCP_BRIDGE_SECRET": SECRET}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = create_app()
        self.transport = httpx.ASGITransport(app=self.app, client=("127.0.0.1", 12345))

    async def test_signed_list_and_call(self):
        tools = [{"name": "search", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}]
        server = {"id": "demo", "url": "https://mcp.example.com/mcp"}
        async with httpx.AsyncClient(transport=self.transport, base_url="http://127.0.0.1:8766") as client:
            body = json.dumps({"server": server}, separators=(",", ":")).encode()
            with patch("mcp_client.bridge.list_tools", new=AsyncMock(return_value=tools)):
                response = await client.post("/internal/list", content=body, headers=signed_headers("/internal/list", body))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["tools"][0]["name"], "search")

            call_body = json.dumps({"server": server, "tool_name": "search", "arguments": {"q": "x"}}, separators=(",", ":")).encode()
            expected = {"ok": True, "_kind": "mcp_tool_result", "tool": "search"}
            with patch("mcp_client.bridge.call_tool", new=AsyncMock(return_value=expected)):
                response = await client.post("/internal/call", content=call_body, headers=signed_headers("/internal/call", call_body))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["result"]["tool"], "search")

    async def test_signed_oauth_discovery_and_exchange(self):
        server = {"id": "demo", "url": "https://mcp.example.com/mcp", "auth_type": "oauth"}
        discovered = {
            "authorization_endpoint": "https://mcp.example.com/oauth/authorize",
            "token_endpoint": "https://mcp.example.com/oauth/token",
            "resource": "https://mcp.example.com",
        }
        async with httpx.AsyncClient(transport=self.transport, base_url="http://127.0.0.1:8766") as client:
            body = json.dumps({"server": server}, separators=(",", ":")).encode()
            with patch("mcp_client.bridge.discover_oauth", new=AsyncMock(return_value=discovered)):
                response = await client.post("/internal/oauth/discover", content=body, headers=signed_headers("/internal/oauth/discover", body))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["oauth"]["token_endpoint"], discovered["token_endpoint"])

            exchange_payload = {
                "server": server,
                "token_endpoint": discovered["token_endpoint"],
                "client_id": "apervia",
                "code": "code",
                "redirect_uri": "https://app.example.com/api3/mcp/oauth/callback",
                "code_verifier": "verifier",
            }
            exchange_body = json.dumps(exchange_payload, separators=(",", ":")).encode()
            tokens = {"access_token": "access", "token_type": "Bearer", "expires_in": 3600}
            with patch("mcp_client.bridge.exchange_oauth_code", new=AsyncMock(return_value=tokens)):
                response = await client.post("/internal/oauth/exchange", content=exchange_body, headers=signed_headers("/internal/oauth/exchange", exchange_body))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["tokens"]["access_token"], "access")

    async def test_taskgroup_errors_are_unwrapped_for_list_and_call(self):
        server = {"id": "demo", "url": "https://mcp.example.com/mcp"}

        def unauthorized_group() -> ExceptionGroup:
            request = httpx.Request("POST", server["url"])
            response = httpx.Response(401, request=request)
            status_error = httpx.HTTPStatusError(
                "Client error '401 Unauthorized'",
                request=request,
                response=response,
            )
            return ExceptionGroup("unhandled errors in a TaskGroup", [ExceptionGroup("nested", [status_error])])

        async with httpx.AsyncClient(transport=self.transport, base_url="http://127.0.0.1:8766") as client:
            list_body = json.dumps({"server": server}, separators=(",", ":")).encode()
            with patch("mcp_client.bridge.list_tools", new=AsyncMock(side_effect=unauthorized_group())):
                response = await client.post("/internal/list", content=list_body, headers=signed_headers("/internal/list", list_body))
            self.assertEqual(response.status_code, 502)
            self.assertIn("HTTP 401", response.json()["message"])
            self.assertIn("认证", response.json()["message"])
            self.assertNotIn("TaskGroup", response.json()["message"])

            call_body = json.dumps(
                {"server": server, "tool_name": "search", "arguments": {}},
                separators=(",", ":"),
            ).encode()
            with patch("mcp_client.bridge.call_tool", new=AsyncMock(side_effect=unauthorized_group())):
                response = await client.post("/internal/call", content=call_body, headers=signed_headers("/internal/call", call_body))
            self.assertEqual(response.status_code, 502)
            self.assertIn("HTTP 401", response.json()["message"])
            self.assertNotIn("TaskGroup", response.json()["message"])

    async def test_unsigned_request_is_rejected(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://127.0.0.1:8766") as client:
            response = await client.post("/internal/list", json={"server": {}})
        self.assertEqual(response.status_code, 403)

    async def test_oversized_request_is_rejected(self):
        async with httpx.AsyncClient(transport=self.transport, base_url="http://127.0.0.1:8766") as client:
            response = await client.post("/internal/list", content=b"x" * 1048577)
        self.assertEqual(response.status_code, 413)

    def test_nonce_replay_store(self):
        store = ReplayNonceStore()
        self.assertTrue(store.consume("nonce-1"))
        self.assertFalse(store.consume("nonce-1"))

    def test_remote_url_policy(self):
        with patch("mcp_client.remote._resolved_addresses", return_value=[__import__("ipaddress").ip_address("8.8.8.8")]):
            self.assertEqual(validate_server_url({"url": "https://mcp.example.com/mcp"}), "https://mcp.example.com/mcp")
        with patch("mcp_client.remote._resolved_addresses", return_value=[__import__("ipaddress").ip_address("127.0.0.1")]):
            with self.assertRaisesRegex(RemoteMcpError, "https_required"):
                validate_server_url({"url": "http://127.0.0.1:9000/mcp", "allow_insecure_local": False})
            self.assertEqual(
                validate_server_url({"url": "http://127.0.0.1:9000/mcp", "allow_insecure_local": True}),
                "http://127.0.0.1:9000/mcp",
            )


if __name__ == "__main__":
    unittest.main()
