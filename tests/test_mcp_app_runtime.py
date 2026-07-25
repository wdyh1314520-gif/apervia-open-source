from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import requests
from flask import Flask, Response, jsonify, request


ROOT = Path(__file__).resolve().parents[1]


def build_namespace():
    app = Flask(__name__)
    data_dir = tempfile.mkdtemp(prefix="app3-mcp-test-")
    namespace = {
        "__builtins__": __builtins__,
        "__name__": __name__,
        "app": app,
        "app_logger": logging.getLogger("test.mcp.app"),
        "hashlib": hashlib,
        "json": json,
        "jsonify": jsonify,
        "os": os,
        "re": re,
        "Response": Response,
        "request": request,
        "requests": requests,
        "secrets": secrets,
        "sqlite3": sqlite3,
        "threading": threading,
        "time": time,
        "_app_external_origin": lambda: request.url_root.rstrip("/"),
        "_app_external_url": lambda path: request.url_root.rstrip("/") + "/" + str(path or "").lstrip("/"),
        "_current_login_email": lambda: "user@example.com",
        "_require_logged_in_email": lambda: ("user@example.com", None),
        "_normalize_login_email": lambda value: str(value or "").strip().lower(),
        "_app_data_path": lambda *parts: str(Path(data_dir).joinpath(*parts)),
        "_platform_admin_guard": lambda: ({"error": "forbidden"}, 403),
        "_platform_admin_audit_append": lambda *_args, **_kwargs: None,
    }
    def exec_split_file(filename):
        split_path = ROOT / str(filename)
        exec(compile(split_path.read_text(encoding="utf-8"), str(split_path), "exec"), namespace)
    namespace["_exec_split_file"] = exec_split_file
    path = ROOT / "app3_parts" / "mcp" / "client_runtime_part.py"
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return app, namespace


class McpAppRuntimeTests(unittest.TestCase):
    def test_tool_shapes_are_separate_and_all_enabled_tools_are_exposed(self):
        _app, ns = build_namespace()
        runtime = ns["_mcp_client_build_runtime"]([
            {
                "id": "demo",
                "name": "Demo",
                "url": "https://example.com/mcp",
                "enabled": True,
                "auth_type": "none",
                "tools": [
                    {"name": "read", "description": "read", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
                    {"name": "write", "description": "write", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": False}},
                    {"name": "contradictory", "description": "bad annotations", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True, "destructiveHint": True}},
                ],
            }
        ])
        self.assertEqual(len(runtime["registry"]), 3)
        self.assertIn("function", runtime["chat_specs"][0])
        self.assertNotIn("function", runtime["responses_specs"][0])
        self.assertEqual(runtime["responses_specs"][0]["type"], "function")

        enabled = ns["_mcp_client_build_runtime"]([
            {
                "id": "demo",
                "url": "https://example.com/mcp",
                "enabled": True,
                "auth_type": "none",
                "tools": [
                    {"name": "read", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
                    {"name": "write", "enabled": False, "inputSchema": {"type": "object"}},
                ],
            }
        ])
        self.assertEqual(len(enabled["registry"]), 1)

    def test_permission_modes_and_risk_classification(self):
        _app, ns = build_namespace()
        read = ns["_mcp_client_normalize_tool"]({"name": "read", "annotations": {"readOnlyHint": True}})
        low = ns["_mcp_client_normalize_tool"]({"name": "create_note", "annotations": {"readOnlyHint": False}})
        high = ns["_mcp_client_normalize_tool"]({"name": "delete_file", "annotations": {"readOnlyHint": False}})
        self.assertEqual((read["risk"], low["risk"], high["risk"]), ("read", "low", "high"))
        requires = ns["_mcp_client_requires_approval"]
        self.assertFalse(requires({"permission_mode": "allow_low_risk"}, read))
        self.assertFalse(requires({"permission_mode": "allow_low_risk"}, low))
        self.assertTrue(requires({"permission_mode": "allow_low_risk"}, high))
        self.assertTrue(requires({"permission_mode": "always_ask"}, read))
        self.assertFalse(requires({"permission_mode": "allow_all"}, high))
        for name in ("exec_command", "apply_patch", "write_stdin", "kill_session"):
            self.assertEqual(ns["_mcp_client_normalize_tool"]({"name": name})["risk"], "high")

    def test_browser_cannot_enable_server_local_http(self):
        _app, ns = build_namespace()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APP3_MCP_ALLOW_INSECURE_LOCAL", None)
            server = ns["_mcp_client_normalize_server"]({
                "url": "http://127.0.0.1:9000/mcp",
                "allow_insecure_local": True,
            })
        self.assertFalse(server["allow_insecure_local"])
        with patch.dict(os.environ, {"APP3_MCP_ALLOW_INSECURE_LOCAL": "1"}, clear=False):
            server = ns["_mcp_client_normalize_server"]({
                "url": "http://127.0.0.1:9000/mcp",
                "allow_insecure_local": True,
            })
        self.assertTrue(server["allow_insecure_local"])

    def test_high_risk_tool_requires_interactive_approval(self):
        _app, ns = build_namespace()
        client = type("Client", (), {})()
        runtime = ns["_mcp_client_attach_runtime"](client, [{
            "id": "demo",
            "name": "Demo",
            "url": "https://example.com/mcp",
            "enabled": True,
            "auth_type": "none",
            "permission_mode": "allow_low_risk",
            "tools": [{"name": "delete_file", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": False}}],
        }])
        proxy_name = next(iter(runtime["registry"]))
        calls = []
        ns["_chat_async_wait_mcp_approval"] = lambda **_kwargs: {"ok": True, "decision": "allow_once"}
        ns["_mcp_client_bridge_request"] = lambda path, payload, **_kwargs: calls.append((path, payload)) or {"ok": True, "result": {"ok": True}}
        result = ns["_mcp_client_call_proxy_tool"](proxy_name, {"path": "a.txt"}, client_override=client)
        self.assertTrue(result["ok"])
        self.assertTrue(calls[0][1]["permission_granted"])

        calls.clear()
        ns["_chat_async_wait_mcp_approval"] = lambda **_kwargs: {"ok": False, "decision": "deny"}
        denied = ns["_mcp_client_call_proxy_tool"](proxy_name, {"path": "a.txt"}, client_override=client)
        self.assertEqual(denied["error"], "mcp_tool_denied")
        self.assertEqual(calls, [])

        ns["_chat_async_wait_mcp_approval"] = lambda **_kwargs: {
            "ok": False,
            "decision": "revise",
            "user_request": "不要删除原文件，请改为生成副本",
        }
        revised = ns["_mcp_client_call_proxy_tool"](proxy_name, {"path": "a.txt"}, client_override=client)
        self.assertEqual(revised["error"], "mcp_tool_revision_requested")
        self.assertTrue(revised["retryable"])
        self.assertIn("生成副本", revised["user_request"])
        self.assertEqual(calls, [])

    def test_mcp_call_audit_uses_one_activity_id_for_lifecycle(self):
        _app, ns = build_namespace()
        client = type("Client", (), {})()
        runtime = ns["_mcp_client_attach_runtime"](client, [{
            "id": "demo",
            "name": "Demo",
            "url": "https://example.com/mcp",
            "enabled": True,
            "auth_type": "none",
            "permission_mode": "allow_all",
            "tools": [{"name": "exec_command", "title": "Run command", "inputSchema": {"type": "object"}}],
        }])
        proxy_name = next(iter(runtime["registry"]))
        events = []
        ns["_chat_async_current_job_id"] = lambda: "job-1"
        ns["_chat_async_append_event"] = lambda job_id, event, payload: events.append((job_id, event, payload))
        ns["_mcp_client_bridge_request"] = lambda *_args, **_kwargs: {"ok": True, "result": {"ok": True, "stdout": "done"}}

        result = ns["_mcp_client_call_proxy_tool"](proxy_name, {"command": "echo done"}, client_override=client)
        self.assertTrue(result["ok"])
        audits = [payload for _job, event, payload in events if event == "mcp_tool_audit"]
        self.assertEqual([row["action"] for row in audits], ["call_started", "call_completed"])
        self.assertTrue(audits[0]["activity_id"])
        self.assertEqual(audits[0]["activity_id"], audits[1]["activity_id"])
        self.assertEqual(audits[0]["arguments"]["command"], "echo done")
        self.assertEqual(audits[1]["result_preview"]["stdout"], "done")

    def test_dispatcher_routes_proxy_tool_to_mcp_runtime(self):
        namespace = {
            "__builtins__": __builtins__,
            "_mcp_client_is_proxy_tool": lambda name: name.startswith("mcp_ext_"),
            "_mcp_client_call_proxy_tool": lambda name, args, client_override=None: {"ok": True, "name": name, "args": args},
        }
        path = ROOT / "app3_parts" / "tools" / "tool_dispatch_part.py"
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
        result = namespace["_exec_tool"]("mcp_ext_demo_read_123", {"q": "x"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["args"]["q"], "x")

    def test_scan_route_returns_normalized_tools(self):
        app, ns = build_namespace()
        fake = {
            "ok": True,
            "tools": [{"name": "search", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}],
        }
        ns["_mcp_client_bridge_request"] = lambda *_args, **_kwargs: fake
        client = app.test_client()
        saved = client.post("/api3/mcp/servers", json={"server": {"id": "demo", "url": "https://example.com/mcp", "auth_type": "none"}})
        self.assertEqual(saved.status_code, 200)
        response = client.post("/api3/mcp/scan", json={"server_id": "demo"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["tools"][0]["read_only"])

    def test_server_store_encrypts_bearer_token_and_never_returns_it_to_browser(self):
        app, ns = build_namespace()
        token = "mcp-secret-token-that-must-not-be-plaintext"
        client = app.test_client()
        saved = client.post("/api3/mcp/servers", json={"server": {
            "id": "encrypted-demo",
            "url": "https://example.com/mcp",
            "auth_type": "bearer",
            "bearer_token": token,
        }})
        self.assertEqual(saved.status_code, 200)
        saved_server = saved.get_json()["server"]
        self.assertTrue(saved_server["credential_configured"])
        self.assertNotIn("bearer_token", saved_server)
        self.assertNotIn("access_token", saved_server)

        listed = client.get("/api3/mcp/servers").get_json()["servers"][0]
        self.assertTrue(listed["credential_configured"])
        self.assertNotIn("bearer_token", listed)
        self.assertNotIn("access_token", listed)

        store = ns["_MCP_SERVER_STORE"]
        self.assertNotIn(token.encode("utf-8"), Path(store.db_path).read_bytes())
        runtime_server = store.get("user@example.com", "encrypted-demo", include_secret=True)
        self.assertEqual(runtime_server["bearer_token"], token)

    def test_oauth_start_builds_pkce_authorization_url(self):
        app, ns = build_namespace()
        ns["_current_login_email"] = lambda: ""
        ns["_require_logged_in_email"] = lambda: ("real-user@example.com", None)
        ns["_mcp_client_bridge_request"] = lambda *_args, **_kwargs: {
            "ok": True,
            "oauth": {
                "authorization_endpoint": "https://mcp.example.com/oauth/authorize",
                "token_endpoint": "https://mcp.example.com/oauth/token",
                "resource": "https://mcp.example.com",
                "scopes_supported": [],
            },
        }
        client = app.test_client()
        saved = client.post("/api3/mcp/servers", json={"server": {"id": "demo", "url": "https://mcp.example.com/mcp", "auth_type": "oauth", "oauth_client_id": "apervia"}})
        self.assertEqual(saved.status_code, 200)
        response = client.post("/api3/mcp/oauth/start", json={"server_id": "demo"})
        self.assertEqual(response.status_code, 200)
        url = response.get_json()["authorization_url"]
        self.assertIn("response_type=code", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("client_id=apervia", url)

    def test_public_oauth_uses_public_https_callback_and_owner_binding(self):
        app, ns = build_namespace()
        principal = {"email": "alice@example.com"}
        ns["_require_logged_in_email"] = lambda: (principal["email"], None)
        bridge_calls = []

        def bridge_request(path, _payload, **_kwargs):
            bridge_calls.append(path)
            return {
                "ok": True,
                "oauth": {
                    "authorization_endpoint": "https://mcp.example.com/oauth/authorize",
                    "token_endpoint": "https://mcp.example.com/oauth/token",
                    "resource": "https://mcp.example.com",
                    "scopes_supported": [],
                },
            }

        ns["_mcp_client_bridge_request"] = bridge_request
        client = app.test_client()
        client.post("/api3/mcp/servers", json={"server": {"id": "demo", "url": "https://mcp.example.com/mcp", "auth_type": "oauth"}})
        response = client.post("/api3/mcp/oauth/start", base_url="https://chat.example.com", json={"server_id": "demo"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        query = parse_qs(urlsplit(data["authorization_url"]).query)
        self.assertEqual(query["redirect_uri"][0], "https://chat.example.com/api3/mcp/oauth/callback")

        principal["email"] = "bob@example.com"
        callback = app.test_client().get(
            "/api3/mcp/oauth/callback",
            base_url="https://chat.example.com",
            query_string={"state": data["state"], "code": "code"},
        )
        self.assertEqual(callback.status_code, 200)
        self.assertIn("OAuth 登录用户不匹配", callback.get_data(as_text=True))
        self.assertEqual(bridge_calls, ["/internal/oauth/discover"])

    def test_public_unauthenticated_oauth_is_rejected(self):
        app, ns = build_namespace()
        ns["_current_login_email"] = lambda: ""
        ns["_require_logged_in_email"] = lambda: ("", ({"error": "login_required"}, 401))
        response = app.test_client().post("/api3/mcp/oauth/start", base_url="https://chat.example.com", json={"server_id": "demo"})
        self.assertEqual(response.status_code, 401)

    def test_oauth_result_polling_is_owner_bound_and_one_time(self):
        app, ns = build_namespace()
        principal = {"email": "alice@example.com"}
        ns["_require_logged_in_email"] = lambda: (principal["email"], None)

        def bridge_request(path, _payload, **_kwargs):
            if path == "/internal/oauth/discover":
                return {
                    "ok": True,
                    "oauth": {
                        "authorization_endpoint": "https://mcp.example.com/oauth/authorize",
                        "token_endpoint": "https://mcp.example.com/oauth/token",
                        "resource": "https://mcp.example.com",
                        "scopes_supported": [],
                    },
                }
            if path == "/internal/oauth/exchange":
                return {"ok": True, "tokens": {"access_token": "access", "token_type": "Bearer", "expires_in": 3600}}
            raise AssertionError(path)

        ns["_mcp_client_bridge_request"] = bridge_request
        client = app.test_client()
        client.post("/api3/mcp/servers", json={"server": {"id": "demo", "url": "https://mcp.example.com/mcp", "auth_type": "oauth"}})
        started = client.post("/api3/mcp/oauth/start", base_url="https://chat.example.com", json={"server_id": "demo"}).get_json()
        state = started["state"]

        waiting = client.get("/api3/mcp/oauth/result", query_string={"state": state})
        self.assertEqual(waiting.status_code, 200)
        self.assertTrue(waiting.get_json()["pending"])

        callback = client.get("/api3/mcp/oauth/callback", base_url="https://chat.example.com", query_string={"state": state, "code": "code"})
        self.assertEqual(callback.status_code, 200)
        callback_html = callback.get_data(as_text=True)
        self.assertIn("MCP authorized. Returning to Apervia…", callback_html)
        self.assertIn('data-i18n="settings.mcp.oauth_success_page"', callback_html)

        principal["email"] = "bob@example.com"
        forbidden = client.get("/api3/mcp/oauth/result", query_string={"state": state})
        self.assertEqual(forbidden.status_code, 403)

        principal["email"] = "alice@example.com"
        completed = client.get("/api3/mcp/oauth/result", query_string={"state": state})
        self.assertEqual(completed.status_code, 200)
        result = completed.get_json()["result"]
        self.assertNotIn("access_token", result)
        self.assertTrue(result["server"]["credential_configured"])
        stored = ns["_MCP_SERVER_STORE"].get("alice@example.com", "demo", include_secret=True)
        self.assertEqual(stored["bearer_token"], "access")
        database_bytes = Path(ns["_MCP_SERVER_STORE"].db_path).read_bytes()
        self.assertNotIn(b"access", database_bytes)

        consumed = client.get("/api3/mcp/oauth/result", query_string={"state": state})
        self.assertEqual(consumed.status_code, 404)

        ns["_MCP_CLIENT_OAUTH_COMPLETED"]["expired"] = {
            "owner_principal": "alice@example.com",
            "result": {"ok": True},
            "expires_at": time.time() - 1,
        }
        ns["_mcp_client_oauth_cleanup"]()
        self.assertNotIn("expired", ns["_MCP_CLIENT_OAUTH_COMPLETED"])


if __name__ == "__main__":
    unittest.main()
