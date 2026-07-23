# Apervia MCP Client

Apervia acts as an MCP host and client. A local bridge built on the official MCP Python SDK connects it to remote MCP servers. By default, the bridge listens only on the internal address `127.0.0.1:8766` of the Linux VPS running Apervia; public users never access this port. Port `8765` remains reserved for the existing `coding-tools-mcp` service.

## Running the bridge

App3 and the bridge must receive the same random secret:

```text
APP3_MCP_BRIDGE_SECRET=<at-least-32-random-characters>
```

Install and start the bridge:

```bash
bash mcp_client/install.sh --install
bash mcp_client/install.sh --start
```

During development and single-machine operation, App3 starts the bridge on port 8766 when MCP is first used and generates the shared secret in memory, so the secret does not need to be stored in `.env`. In production, set `APP3_MCP_BRIDGE_AUTOSTART=0`, start App3 and the bridge separately through the service manager, and inject the same random `APP3_MCP_BRIDGE_SECRET` into both processes.

The public request path on a Linux VPS is: the user's browser accesses only `https://your-domain`; Nginx forwards requests to App3 on port 8002; App3 calls the bridge internally on port 8766. Nginx must forward `Host`, `X-Forwarded-Host`, and `X-Forwarded-Proto` so the OAuth callback is generated as `https://your-domain/api3/mcp/oauth/callback`.

In Apervia, open **Settings → MCP**, add the remote HTTPS MCP URL, select **Connect**, complete authorization on the MCP server's OAuth page, and then scan for tools. The remote server password is never submitted to Apervia.

After scanning and saving, enabled MCP tools are included in requests for the current mode. Chat Completions uses the nested `function` tool structure, while Responses uses the flat function tool structure. The two tool-call loops remain independent and share only the MCP connection and execution layer.

## Security boundaries

- OAuth uses Authorization Code + PKCE. Temporary authorization state remains in the App3 process for ten minutes. Access and refresh tokens are stored per account in the server-side MCP store with Fernet encryption and are never included in chat synchronization.
- Permission levels are **Always ask**, **Allow reads**, **Allow low-risk actions**, and **Allow all actions**. Reads and low-risk actions are allowed by default; high-risk calls show an argument preview and require per-call approval.
- Tool risk is classified from MCP annotations and conservative name-based rules. This does not replace authorization on the remote account; it only determines when Apervia asks again.
- User-configured remote URLs must use HTTPS. Loopback HTTP is available only for server-side development and requires an operator to set `APP3_MCP_ALLOW_INSECURE_LOCAL=1`; browser users cannot enable it.
- Manual bearer tokens are supported only as a compatibility mode and are stored per account in the same encrypted server-side MCP store.
- The server tool list is retrieved again before every call, and the current tool, enabled list, and approval credential for non-read-only calls are revalidated instead of relying only on an earlier scan cache.
- The bridge and App3 use HMAC, a short validity window, and one-time nonces.
- The client does not inherit system HTTP proxies or follow redirects. Tool lists, requests, and tool results are size-limited. Remote tool output remains untrusted, so connect only to trusted servers.

Only remote Streamable HTTP and HTTP-SSE transports are supported. Local stdio commands are never executed.
