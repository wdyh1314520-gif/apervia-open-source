# App3 Troubleshooting Runbook

> Usage: Select a section by symptom, start with the listed endpoint, and then narrow the investigation through the frontend, backend core functions, and data files. This runbook covers only the current Apervia architecture.

## 1. Chat does not start or respond

Check the endpoints first:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8002/api3/health/live -TimeoutSec 5
Invoke-RestMethod -Uri http://127.0.0.1:8002/api3/health/ready -TimeoutSec 5
```

Investigation order:

1. Confirm in the browser Network panel that the frontend sends `/api3/chat_async/start`.
2. Confirm that a backend job is created in `chat_async_start_route()` in `async_pullback_upload_server_part.py`.
3. Check `/api3/chat_async/stream` or `/api3/chat_async/poll` for SSE or polling events. The core handlers are `chat_async_stream_route()` and `chat_async_poll_route()`.
4. Confirm that model streaming reaches `_chat_stream_gen(...)` in `chat_streaming_part.py`.
5. If execution stops during a tool stage, inspect `chat_orchestrator_tool_stage_part.py` and `_exec_tool(...)` in `file_registry_edit_tools_part.py`.

Key files:

- Frontend: `static/index3/js/index3-async-chat-stream-ui.js`
- Backend: `app3_parts/media/async_pullback_upload_server_part.py`
- Backend core: `app3_parts/chat/chat_streaming_part.py`
- Data: `chat_async_jobs.db`, `auth_chat_store.db`

## 2. Chat responds but the frontend shows nothing

Check the endpoint first:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8002/api3/health/live -TimeoutSec 5
```

Investigation order:

1. Confirm in the Network panel that SSE or polling returns events such as `delta`, `done`, or `error`.
2. Inspect frontend event handling near `processAsyncJobEvent` in `index3-async-chat-stream-ui.js`.
3. After the message reaches the session, inspect `renderChat()` in `index3-chat-render-ui.js`.
4. For missing Markdown, code blocks, or quotations, inspect `index3-render-markdown-ui.js`.
5. For missing images, weather, or file cards, inspect `index3-message-media-render-ui.js`.

Key files:

- Frontend events: `static/index3/js/index3-async-chat-stream-ui.js`
- Frontend rendering: `static/index3/js/index3-chat-render-ui.js`
- Rich text: `static/index3/js/index3-render-markdown-ui.js`
- Media cards: `static/index3/js/index3-message-media-render-ui.js`

## 3. Upload stalls or the file is missing from the library

Check the endpoint first:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8002/api3/storage/quota -TimeoutSec 5
```

Investigation order:

1. Small files use `/api3/upload`; large files and mobile images may use `/api3/upload_chunk/*`.
2. The regular upload entry point is `upload_gpt()`.
3. Chunked upload entry points are `upload_chunk_init_gpt()`, `upload_chunk_raw_part_gpt()`, and `upload_chunk_finish_gpt()`.
4. Actual file processing occurs in `_process_uploaded_file_payload(...)`.
5. For storage rejection, inspect `storage_quota_part.py`.
6. If upload succeeds but the library does not show the file, inspect registry writes in `file_registry_edit_tools_part.py`, followed by `_file_library_state(...)` in `file_library_part.py`.

Key files:

- Frontend: `static/index3/js/index3-upload-dragdrop-ui.js`
- Upload cards: `static/index3/js/index3-composer-attachments-ui.js`
- Backend upload: `app3_parts/media/async_pullback_upload_server_part.py`
- File registry: `app3_parts/tools/file_registry_edit_tools_part.py`
- File library: `app3_parts/knowledge/file_library_part.py`
- Data: `uploads_local/`, `uploads_public/`, `upload_chunks/`, `file_registry_store.json`, `file_text_store/`

## 4. Image generation fails or the generated image is not displayed

Check the endpoint first:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8002/api3/image-generation/mirror-status -TimeoutSec 5
```

Investigation order:

1. Confirm that settings are included in the request through `index3-settings-image-ui.js`.
2. Confirm that the chat tool selects image generation through `image_generation_call` and the image task selector in `chat_streaming_part.py`.
3. The main image-generation entry point is `_generate_image_artifacts(...)` in `model_image_file_delivery_part.py`.
4. Verify dispatch for OpenAI-compatible, Responses native, Automatic1111, Gemini, or ComfyUI backends.
5. If generation succeeds but the result is not shown, inspect `/api3/generated-files/<filename>`.
6. For background retrieval on public or mobile clients, inspect `_image_pullback_*` in `async_pullback_upload_server_part.py`.
7. For an external image that does not render, inspect `platform_remote_image_proxy_part.py`.

Key files:

- Frontend settings: `static/index3/js/index3-settings-image-ui.js`
- Frontend media: `static/index3/js/index3-message-media-render-ui.js`
- Image core: `app3_parts/media/model_image_file_delivery_part.py`
- Chat stream: `app3_parts/chat/chat_streaming_part.py`
- Background retrieval: `app3_parts/media/async_pullback_upload_server_part.py`
- Remote proxy: `app3_parts/platform/platform_remote_image_proxy_part.py`
- Data: `generated_local/`, `generated_public/`, `remote_image_cache/`

## 5. Knowledge-base search fails or chat does not cite the knowledge base

Check the endpoint first:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8002/api3/kb/state -TimeoutSec 5
```

Investigation order:

1. Confirm that the knowledge-base UI can read `/api3/kb/state`.
2. Confirm document import through `knowledge_base.db` and the `/api3/kb/state` response.
3. Test `/api3/kb/search`; the core search function is `_kb_search(...)`.
4. Confirm that the request body in `index3-async-chat-stream-ui.js` includes `kb_enabled`, `kb_space_id`, and `kb_doc_id`.
5. Confirm pre-model injection in `_prepare_messages(...)` and `_prepare_knowledge_base_context(...)`.
6. If a file-library import fails, inspect `_file_library_import_to_kb(...)`.
7. Images should appear only in the library and never in `/api3/kb/state` or search results. If an image still shows an import button, check frontend `kb_importable` and then `_kb_document_ext_allowed(...)`.
8. Library routes must use `/library?tab=all|images|files|knowledge`. If `/c/<id>#library/...` still appears, inspect `libraryTabRoutePath(...)`, `syncModalRoute(...)`, and `applyModalRouteFromLocation(...)` in `index3-session-routing.js`. The chat header and input box must be hidden while the library is open.

Key files:

- Frontend interaction: `static/index3/js/index3-knowledge-base-ui.js`
- Frontend styles: `static/index3/css/index3-knowledge-base.css`
- Request body: `static/index3/js/index3-async-chat-stream-ui.js`
- Backend loader: `app3_parts/knowledge/knowledge_base_context_part.py`
- Knowledge-base core: `app3_parts/knowledge/knowledge_base_core_part.py`
- File library and API routes: `app3_parts/knowledge/file_library_part.py`
- Document import gate: `app3_parts/knowledge/knowledge_document_import_part.py`
- Search filtering: `app3_parts/knowledge/knowledge_search_part.py`
- Historical file context: `app3_parts/knowledge/history_file_context_part.py`
- Tool bridge: `app3_parts/tools/file_registry_edit_tools_part.py`
- Data: `knowledge_base.db`

## 6. Sign-in, account, or session issues

Check the endpoint first:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8002/api3/auth/status -TimeoutSec 5
```

Investigation order:

1. Check sign-in state through `/api3/auth/status` and `/api3/auth/me`.
2. The sign-in route is `email_password_login()` in `platform_auth_routes_part.py`; core validation is `_auth_identity_password_login_http()` in `platform_auth_identity_routes_part.py`.
3. The single sources of truth for accounts, roles, and sessions are `platform_auth_identity_part.py` and `auth_identity.db`. `email_login_store.json` stores only registration policy, announcements, and account-notification SMTP configuration.
4. For request gates and IP or session context, inspect `platform_auth_request_context_part.py` and `platform_auth_runtime_init_part.py`.
5. Be aware of route replacement: `chat_sync_realtime_part.py` replaces `/api3/auth/me` with the lightweight presence handler `email_login_me_light()`.
6. For rate limits or blacklist behavior, inspect `_apply_rate_limit(...)` and routes related to `_auth_blacklist`.

Key files:

- Frontend account lifecycle: `static/index3/js/index3-account-cloud-lifecycle.js`
- Backend routes: `app3_parts/auth/platform_auth_routes_part.py`
- Identity and sessions: `app3_parts/auth/platform_auth_identity_part.py`
- Request context: `app3_parts/auth/platform_auth_request_context_part.py`
- Override layer: `app3_parts/account/user_personalization_runtime_part.py`
- Data: `auth_identity.db`, `email_login_store.json`, `auth_users_store.json`, `rate_limit_store.json`

### Purging unregistered guest data from administration

1. The Accounts page under `/platform-admin` shows **Purge unregistered guest data** only for records with `can_purge_guest=true`. A record qualifies when its ownership identifier does not exist in the registered-account table; the `anonymous` fallback bucket also qualifies.
2. Before deletion, call `GET /api3/platform-admin/account-purge-preview?email=<owner>` to review scope, then enter the complete ownership identifier for a second confirmation.
3. `PlatformAdminGuestPurgeService.validate_target()` queries the registered-account table again. It always rejects a registered account, so frontend button visibility is never the only safety control.
4. The purge covers device remnants, asynchronous jobs, chat and personalization data, per-account chat backups, shares, knowledge bases, file indexes and physical files, sandbox directories, invitations, and deletion-log remnants. Registered-account records are not part of this service's deletion steps.
5. `anonymous` is a shared fallback bucket; purging it affects all current anonymous fallback data. The operation cannot be undone. If a step fails, retry with the same ownership identifier and inspect the hashed fingerprint in the platform audit log.

Key files:

- Administration page: `static/platform-admin/platform-admin.js`
- Routes: `app3_parts/storage/platform_admin_routes_part.py`
- Action entry point: `app3_parts/storage/platform_admin_chat_backup_part.py`
- Central purge service: `app3_parts/storage/platform_admin_account_purge_part.py`
- Account classification: `app3_parts/storage/platform_admin_inventory_part.py`

## 7. Conversation synchronization issues

Check the endpoint first:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8002/api3/chat-sync/manifest -TimeoutSec 5
```

Investigation order:

1. Check the frontend local store in `index3-store-cloud-sync.js`.
2. Confirm that `/api3/chat-sync/manifest` returns the session list.
3. Confirm that a session can be read through `/api3/chat-sync/session?id=<session_id>`.
4. Inspect `/api3/chat-sync/pull` and `/api3/chat-sync/push` for version conflicts.
5. `chat_sync_pull_route()` is defined in both `platform_auth_routes_part.py` and `user_personalization_runtime_part.py`; the later-loaded definition is the relevant implementation.
6. Inspect `_auth_chat_store_get/set(...)` in `platform_auth_core_part.py` for underlying storage.

Key files:

- Frontend synchronization: `static/index3/js/index3-store-cloud-sync.js`
- Frontend lifecycle: `static/index3/js/index3-account-cloud-lifecycle.js`
- Backend routes: `app3_parts/auth/platform_auth_routes_part.py`
- Backend override: `app3_parts/account/user_personalization_runtime_part.py`
- Backend storage: `app3_parts/auth/platform_auth_core_part.py`
- Data: `auth_chat_store.db`, `auth_chat_store.json`, `auth_chat_store_backups/`

## 8. Web search or page fetching fails

Check the endpoint first:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8002/api3/web_search -ContentType 'application/json' -Body '{"query":"OpenAI latest news","k":3}' -TimeoutSec 20
```

Investigation order:

1. Confirm search settings in `index3-settings-web-ui.js` and the request payload.
2. The manual search route is `api3_web_search()` in `chat_weather_routes_part.py`.
3. Provider dispatch uses `_search_with_provider(...)`, `web_search(...)`, and `web_search_multi(...)` in `web_search_enrichment_part.py`.
4. URL fetching begins in `api3_fetch_url()` in `chat_weather_routes_part.py`; the core is `fetch_url_content(...)` in `web_fetch_cloud_code_part.py`.
5. For dynamic or JavaScript-heavy pages, inspect Playwright, curl, and Jina fallbacks.
6. For poor search quality, inspect `_rerank_results(...)`, `_filter_search_results(...)`, and `_domain_quality_adjust(...)`.

### Prompt Cache misses after a Responses web-search continuation

1. Inspect consecutive `PROMPT_CACHE_APPLY` log entries. The first Responses round, `web_search` round, and tool-output continuation for the same model, upstream host, and endpoint must retain the same `key_hash` and `key_basis_hash`.
2. `prompt_cache_key` routes similar requests to the same cache shard. It does not replace exact prefix matching and must not derive a different key for each task-routing group.
3. Tool definitions are part of the upstream exact prefix. With Prompt Cache enabled, regular Responses rounds, `web_search` rounds, and tool-output continuations must send identical, stably ordered `tools`. Task-routing groups may control runtime state but must not trim the upstream schema.
4. Web, weather, image-index, runtime-model, and file-loop prompts are dynamic suffixes. Append them to the Responses `input`; never place them in top-level `instructions`.
5. After built-in and MCP tools are merged, run `_agent_stream_stabilize_tool_specs(...)` again to prevent changes in tool-return order from changing prefix bytes.
6. A cache-routing version upgrade causes one cold start. The current correct version is `pc5`; later web-search continuations should remain warm.

Focused test: `python -m unittest tests.test_prompt_cache_stable_prefix -v`

Key files:

- Frontend settings: `static/index3/js/index3-settings-web-ui.js`
- Search routes: `app3_parts/chat/chat_weather_routes_part.py`
- Search core: `app3_parts/web/web_search_enrichment_part.py`
- Page-fetch core: `app3_parts/web/web_fetch_cloud_code_part.py`
- Cache planning: `app3_parts/chat/chat_prompt_cache_part.py`
- Responses context layers: `app3_parts/chat/chat_responses_input_conversion_part.py`
- Chat and Responses tool loops: `app3_parts/chat/chat_streaming_part.py`
- Data: in-memory `_WEB_CACHE` and provider API configuration

## 9. Personalization memory is ignored or written incorrectly

Check the endpoint first:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8002/api3/personalization/memory -TimeoutSec 5
```

Investigation order:

1. Inspect the frontend memory UI in `index3-personalization-memory-ui.js`.
2. The save endpoint is `api3_personalization_memory_save_route()`.
3. Backend state normalization uses `_auth_personalization_normalize_state(...)`.
4. Model-input injection uses `_inject_auth_personalization_memory(...)`.
5. The main Agent writes through `save_memory` to `_auth_personalization_apply_memory_tool(...)`. There is no second automatic memory-writing model after an answer completes.
6. If hard constraints and soft memories are confused, inspect `_auth_personalization_detect_rule_type(...)`.

Key files:

- Frontend: `static/index3/js/index3-personalization-memory-ui.js`
- Backend: `app3_parts/account/user_personalization_runtime_part.py`
- Data: `auth_personalization_memory_store.json`

## 10. Code-block execution fails

Check the endpoint first:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8002/api3/code/runtimes -TimeoutSec 5
```

Investigation order:

1. Inspect the frontend button and code block in `index3-render-markdown-ui.js`.
2. The runtime list comes from `api3_code_runtimes()`.
3. The execution entry point is `api3_code_run()`.
4. Language recognition and command assembly use `_code_run_normalize_language(...)` and `_code_run_sandbox_command_for_script(...)`.
5. `_code_run_execute(...)` writes only to the current account and session sandbox and calls `_sandbox_run_tool(...)`; there is no host-execution fallback.
6. If a language is unavailable, check `docker compose --profile sandbox ps`, `docker compose --profile sandbox logs sandbox-runner`, and the Runner state returned by `_code_run_runtime_matrix()`. Do not infer availability from the App container or host `PATH`.
7. The `app` service must not mount `/var/run/docker.sock`. Only `sandbox-runner` mounts the socket, and regular tasks must use `network_disabled=True`, a read-only root filesystem, and a temporary Docker volume.
8. If the Runner reports Docker socket `permission denied`, run `stat -c %g /var/run/docker.sock` on the native Linux host and set `DOCKER_SOCKET_GID` in `.env` to the result. The Runner always uses UID/GID `10001:10001` and only adds the socket group; do not switch back to root or grant broad capabilities.

Key files:

- Frontend: `static/index3/js/index3-render-markdown-ui.js`
- Backend: `app3_parts/media/async_pullback_upload_server_part.py`
- Code execution entry point: `app3_parts/web/code_run_part.py`
- Runner client: `app3_parts/tools/sandbox_runner_client_part.py`
- Standalone execution service: `sandbox_runner/service.py`

## 11. MCP tool scanning or invocation fails

In this MCP direction, the Apervia assistant acts as a host and client for an external MCP server. The local bridge only isolates the official MCP SDK and never exposes an MCP service publicly.

Check the bridge health endpoint first:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8766/healthz -TimeoutSec 5
```

Investigation order:

1. Run `bash mcp_client/install.sh --check` to confirm that the isolated environment has every dependency. If dependencies are missing, run `bash mcp_client/install.sh --install`.
2. On a single machine, App3 starts the bridge on first use and generates the shared secret in memory. If `APP3_MCP_BRIDGE_AUTOSTART=0` is set, confirm that App3 and the bridge receive the same `APP3_MCP_BRIDGE_SECRET` with at least 32 characters. Never store the value in the repository.
3. Confirm that the bridge listens only on `127.0.0.1:8766`. Port `8765` is reserved for the existing `coding-tools-mcp` service and must not be reused. Start the bridge manually with `bash mcp_client/install.sh --start`. If the port changes, inject the matching `APP3_MCP_BRIDGE_URL` into App3.
4. In **Settings → MCP**, select OAuth and then **Connect**. Apervia discovers Protected Resource and Authorization Server metadata and opens the MCP server authorization page with Authorization Code + PKCE. Enter passwords only on the server page, never in Apervia.
5. If OAuth cannot begin, inspect `WWW-Authenticate`, `/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server`, and the callback URL. If scanning fails after authorization, check access-token expiry. Manual bearer tokens are a compatibility mode only. Public users may configure only HTTPS MCP servers; local HTTP debugging requires an operator to set `APP3_MCP_ALLOW_INSECURE_LOCAL=1`.
6. If scanned tools are absent from conversations, confirm that the server and individual tools are enabled. Tool risk is classified conservatively from MCP annotations. The permission levels **Always ask**, **Allow reads**, **Allow low-risk actions**, and **Allow all actions** determine when a per-call approval card appears.
7. For non-read-only tools, the bridge runs `tools/list` again and revalidates the current tool, enabled list, and approval credential. Synchronous or non-interactive calls that require approval fail closed and cannot bypass frontend confirmation.
8. Chat and Responses use their own tool schemas and invocation loops. They share only the MCP connection, risk classification, and execution layer. Confirm the current API mode before evaluating request format.
9. Run `python -m unittest discover -s tests -p "test_mcp_*.py" -v` for regression coverage. For a real remote service test, use a trusted test MCP server and never put passwords or production tokens in command history, logs, or the repository.
10. MCP addresses, tool caches, and encrypted credentials are stored only in `/data/mcp_server_store.db`; the default key is `/data/mcp_token.key`. Restore both together. When using `APP3_MCP_TOKEN_KEY`, inject the original key. Administrator endpoints may inspect connection status and enable, disable, disconnect, or delete entries, but can never read plaintext tokens.

Key files:

- App3 MCP schemas, OAuth, scanning, and tool dispatch: `app3_parts/mcp/client_runtime_part.py`
- Server directory and encrypted credentials: `app3_parts/mcp/server_store_part.py`
- Loopback bridge: `mcp_client/bridge.py`
- Official SDK remote connection and security policy: `mcp_client/remote.py`
- Bridge signing: `mcp_client/signing.py`
- Frontend settings: `static/index3/js/index3-settings-mcp-ui.js`
- Administrator status page: `static/platform-admin/platform-admin-mcp.js`
- Installation and operation: `mcp_client/install.sh`, `mcp_client/README.md`

## 12. Updating product icons

`static/index3/assets/apervia-icon-master.png` is the single master asset for product icons. After modifying it, run:

```powershell
python static/index3/assets/generate_product_icons.py
```

The generator produces transparent rounded favicons, web and email icons, the Apple Touch Icon, standard Android icons, Android `maskable` icons, and `site.webmanifest`. Do not overwrite derived assets manually. When the icon version changes, update `ICON_VERSION` in the generator and all page references, and then run `python -m unittest tests.test_product_icon_assets -v`.

## Quick investigation map

- Endpoint returns 4xx or 5xx: inspect the route file, then the core helper.
- Endpoint succeeds but the UI does not move: inspect frontend event handling, then the rendering file.
- Chat: `async_pullback_upload_server_part.py` -> `chat_streaming_part.py` -> `file_registry_edit_tools_part.py`.
- Files: `async_pullback_upload_server_part.py` -> `file_registry_edit_tools_part.py` -> `file_library_part.py` / `history_file_context_part.py`.
- Images: `model_image_file_delivery_part.py` -> `platform_static_file_routes_part.py` -> `index3-message-media-render-ui.js`.
- Synchronization: `index3-store-cloud-sync.js` -> `user_personalization_runtime_part.py` -> `platform_auth_core_part.py`.
