# Apervia Integration Guide

## Accessing host services from a container

The App runs inside a Docker container. Within that container, `127.0.0.1` and `localhost` refer to the App container itself, not the host.

Use the following address for Ollama, SearXNG, speech services, or other APIs running on the host:

```text
http://host.docker.internal:<port>
```

The repository's `compose.yaml` provides this name through `host-gateway`. The target service must also listen on an address reachable from the container and allow connections from the Docker bridge.

## MCP servers

Apervia acts as an MCP host and client for external MCP servers. The server directory and encrypted credentials remain only in the server-side data volume; browser-stored server lists are never accepted from chat requests.

### OAuth connection

1. Sign in to Apervia.
2. Open **Settings → MCP**.
3. Add a trusted MCP server URL.
4. Select OAuth and then **Connect**.
5. Complete sign-in and authorization on the MCP server page.
6. Return to Apervia, scan for tools, and select permissions based on risk.

OAuth uses Authorization Code + PKCE. Passwords are submitted only to the MCP server; Apervia never reads the remote server password.

### Address requirements

- Public MCP servers must use HTTPS.
- Loopback HTTP is available only for trusted local debugging and requires an operator to set `APP3_MCP_ALLOW_INSECURE_LOCAL=1` explicitly.
- Do not weaken private-address restrictions to work around DNS or proxy errors. Correct the domain resolution instead.

### `mcp_server_private_network_blocked`

This error means that the MCP address resolved to a loopback, private, link-local, or reserved address, so SSRF protection rejected the connection.

Clash/Mihomo Fake-IP mode often returns an address from `198.18.0.0/15`. If a public domain resolves to this range, configure the proxy to return the real public IP for that domain. For example:

```yaml
dns:
  fake-ip-filter:
    - "mcp.wdsaf.ccwu.cc"
```

After the change, check DNS on both the host and inside the App container. Confirm that the result is no longer in `198.18.x.x`, and then start OAuth again. Do not add the entire `198.18.0.0/15` range to an application allowlist.

### Credential backup

Back up these files together:

```text
/data/mcp_server_store.db
/data/mcp_token.key
```

When `APP3_MCP_TOKEN_KEY` is used, back up the same Fernet key securely outside the repository. Saved tokens cannot be recovered if the key is lost.

## SearXNG

If SearXNG is published on host port `18080`, configure Apervia with:

```text
SearXNG URL: http://host.docker.internal:18080
Search path: /search
```

Do not use `http://localhost:18080`. Verify the service from the App container:

```bash
docker compose exec app python -c "import requests; r=requests.get('http://host.docker.internal:18080/search', params={'q':'Apervia','format':'json'}, timeout=10); print(r.status_code, r.headers.get('content-type'))"
```

The expected result is HTTP 200 with a JSON content type.

If SearXNG and Apervia share a user-defined network, use the service name and container port, such as `http://searxng:8080`. Do not confuse the host-published port with the container port.

## Ollama and compatible APIs

A common address for Ollama running on the host is:

```text
http://host.docker.internal:11434
```

Confirm that Ollama listens on an address reachable from Docker and restrict access with the host firewall. Do not expose an unauthenticated API directly to the public internet just to make it reachable from a container.

Other OpenAI-compatible services should also use `host.docker.internal` or a service name on the same Docker network. Chat Completions and Responses must keep their own configuration, request fields, and tool loops even when they use the same backend address.

## Reverse proxy and HTTPS

The repository does not include Caddy, Nginx, a domain, or certificates. Recommended configuration:

1. Set `APP_BIND_IP=127.0.0.1`.
2. Terminate TLS with a reverse proxy on the host.
3. Trust only explicitly identified proxy sources.
4. Configure `TRUST_PROXY_*` for the actual proxy chain; do not enable every option for an unknown network topology.
5. Keep a stable public HTTPS address for MCP OAuth callbacks.
