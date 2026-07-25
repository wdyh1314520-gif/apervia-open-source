# Apervia Quick Start

This guide starts Apervia on a host that already has Docker installed. Read the [Operations Guide](OPERATIONS.md) before a production deployment.

## 1. Check Docker

```bash
docker version
docker compose version
```

At least 8 GB of memory is recommended. Use 16 GB when the isolated sandbox, browser, and Office document processing are enabled.

Before starting, confirm that port `8002` is available or choose another `APP_HOST_PORT`. The repository does not install Docker, change the host firewall, or configure a public reverse proxy for you.

## 2. Get the project and environment template

```bash
git clone https://github.com/wdyh1314520-gif/apervia-open-source.git
cd apervia-open-source
cp .env.example .env
```

On Windows PowerShell, use:

```powershell
Copy-Item .env.example .env
```

If the GHCR package is private, use a GitHub token with `read:packages` permission:

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

Never commit a token in `.env`, a Compose file, or a command script.

## 3. Configure `.env`

Minimal configuration:

```dotenv
APP_IMAGE=ghcr.io/wdyh1314520-gif/apervia-open-source:latest
APP_PULL_POLICY=always
APP_BIND_IP=127.0.0.1
TRUST_PROXY_X_FOR=0
APP_HOST_PORT=8002
AUTH_SIGNUP_ENABLED=1
AUTH_DEFAULT_ROLE=pending
SANDBOX_TOOLS_ENABLED=0
SANDBOX_DOCKER_IMAGE=ghcr.io/wdyh1314520-gif/apervia-open-source-sandbox:latest
```

Bind address behavior:

- `127.0.0.1`: Accessible only from the host; suitable for local use or a fronting reverse proxy.
- A specific LAN IP address: Serves traffic only through the selected network interface.
- `0.0.0.0`: Listens on every interface and requires firewall rules, access control, and TLS.

Keep `TRUST_PROXY_X_FOR=0` unless the App is bound to `127.0.0.1` and exactly one trusted reverse proxy is its only ingress. Set it to `1` only for that topology; never trust forwarded client IPs when exposing the App directly through `0.0.0.0`.

## 4. Start and verify

```bash
docker compose config --quiet
docker compose pull app
docker compose up -d app
docker compose ps
docker compose logs --tail 100 app
curl --fail http://127.0.0.1:8002/api3/health/ready
```

On Windows PowerShell, the readiness request can also be run with:

```powershell
Invoke-WebRequest http://127.0.0.1:8002/api3/health/ready
```

Open `http://127.0.0.1:8002` in a browser. On a new data volume:

1. The first registered account automatically becomes an administrator.
2. Subsequent accounts are pending approval by default.
3. An administrator approves and manages accounts at `/admin`.

Account and session data is stored in `/data/auth_identity.db`. Administrator accounts are never provisioned through environment variables.

## 5. Complete the first signed-in setup

1. Register the first account and sign in.
2. Open **Settings → API**.
3. Choose **Chat Completions** or **Responses** according to the provider's real protocol, then save the key and base URL.
4. Open **Model management**, add or synchronize models, and select one from the workspace header.
5. Send a short text-only request. Confirm that the response completes before enabling external tools.
6. Open `/admin` and verify that the first account is an active administrator.

Keep Chat Completions and Responses configuration separate. A provider offering both protocols should still have independent profiles so compatibility changes in one path cannot affect the other.

## 6. Enable the Sandbox Runner

The sandbox is optional. When enabled, the App calls the Runner through the internal network, and the Runner creates short-lived execution containers.

Generate a shared secret with at least 32 random bytes:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Add the output to `.env`:

```dotenv
SANDBOX_TOOLS_ENABLED=1
SANDBOX_RUNNER_SECRET=REPLACE_WITH_A_RANDOM_VALUE
```

On a native Linux host, also run:

```bash
stat -c %g /var/run/docker.sock
```

Set `DOCKER_SOCKET_GID` to the result, and then start the services:

```bash
docker compose --profile sandbox pull app sandbox-runner sandbox-image
docker compose --profile sandbox up -d app sandbox-runner
docker compose --profile sandbox ps
docker compose --profile sandbox logs --tail 100 sandbox-runner
```

Verify the boundary: the App container must not mount `/var/run/docker.sock`, and the Runner must not publish a host port.

Run one small code task after enabling the Sandbox. If tools do not appear, check all four conditions: `SANDBOX_TOOLS_ENABLED=1`, identical Runner secrets, a healthy `sandbox-runner`, and a locally available execution image.

## 7. Use local images

To verify unpublished source code:

```bash
docker build -t apervia:local .
docker build -t apervia-sandbox:local docker/sandbox-prod
```

```dotenv
APP_IMAGE=apervia:local
APP_PULL_POLICY=never
SANDBOX_DOCKER_IMAGE=apervia-sandbox:local
```

Then run:

```bash
docker compose --profile sandbox up -d --force-recreate app sandbox-runner
```

## 8. Troubleshoot the initial deployment

| Symptom | Check |
| --- | --- |
| `app` keeps restarting | Read `docker compose logs --tail 200 app` and verify `.env` syntax and volume permissions |
| Readiness returns an error | Wait for startup to finish, then inspect the latest application exception |
| A provider cannot connect | Verify DNS, the API base URL, TLS, and whether the address is reachable from the App container |
| A host service cannot connect | Use `host.docker.internal` and ensure the host service listens beyond its own loopback interface when required |
| A later account is blocked | Approve the pending account in `/admin` |
| Sandbox image is missing | Run the profile pull command again and verify `SANDBOX_DOCKER_IMAGE` exactly matches the intended tag |

## 9. Next steps

- Complete signed-in usage: [User Guide](USER_GUIDE.md)
- Account approval and platform administration: [Administrator Guide](ADMIN_GUIDE.md)
- External-service connections: [Integration Guide](INTEGRATIONS.md)
- Backup and upgrades: [Operations Guide](OPERATIONS.md)
- Update and release publishing: [Release Guide](RELEASE_GUIDE.md)
- Advanced troubleshooting: [Runbook](../RUNBOOK.md)
