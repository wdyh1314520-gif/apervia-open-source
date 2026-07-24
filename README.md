# Apervia

<p align="right">
  <strong>English</strong> | <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img src="docs/images/apervia-icon.png" width="96" height="96" alt="Apervia icon">
</p>

<p align="center"><strong>A Docker-native AI workspace for individuals and teams</strong></p>

<p align="center">
  Bring conversations, knowledge bases, files, models, and MCP tools into one maintainable private workspace, with isolated sandbox execution for code and document tasks.
</p>

<p align="center">
  <a href="https://github.com/wdyh1314520-gif/apervia-open-source/actions/workflows/publish-images.yml"><img src="https://github.com/wdyh1314520-gif/apervia-open-source/actions/workflows/publish-images.yml/badge.svg" alt="Verification and image publishing status"></a>
  <img src="https://img.shields.io/badge/version-1.0.1-6C86BD" alt="Apervia 1.0.1">
  <img src="https://img.shields.io/badge/Docker-amd64%20%7C%20arm64-2496ED?logo=docker&logoColor=white" alt="Docker amd64 and arm64">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12">
</p>

> Apervia is open-source software released under the [MIT License](LICENSE).

![Apervia desktop sign-in page](docs/images/login-desktop.png)

## Core capabilities

- **Unified workspace**: Manage conversations, knowledge bases, uploaded files, generated results, and account data in one place.
- **Separate model protocols**: Chat Completions and Responses maintain independent request, streaming, and tool-calling boundaries so the two protocols do not interfere with each other.
- **MCP integration**: Connect external MCP servers with OAuth + PKCE, tool discovery, risk levels, and per-call authorization. Credentials are encrypted on the server.
- **Isolated sandbox execution**: The App never accesses the Docker socket. A standalone Runner creates a temporary container for each task with networking disabled, a read-only root filesystem, and minimal privileges.
- **Document and media processing**: Built-in support for Playwright, LibreOffice, OCR, PDF, and common Office document workflows.
- **Platform governance**: Administration for account approval, quotas, files, knowledge bases, trash, backups, and audit records.
- **Docker-native delivery**: GitHub Actions builds and publishes both App and Sandbox images for `linux/amd64` and `linux/arm64`.

## Architecture and security boundaries

![Apervia Docker architecture](docs/images/architecture.svg)

The App mounts only the persistent data volume. The Docker socket is exposed only to the internal `sandbox-runner`, which publishes no host port. Regular execution containers have networking disabled and can access only the temporary volume for the current task. Each container and temporary volume is removed when execution finishes.

## Product tour

After sign-in, model selection, conversation input, file access, and conversation history are available in one workspace:

![Apervia signed-in workspace](docs/images/workspace-desktop.png)

Model APIs, Chat Completions, Responses, web access, MCP, image, and account settings are organized by function:

![Apervia settings](docs/images/settings-desktop.png)

For complete usage instructions, see the [User Guide](docs/USER_GUIDE.md). For account approval, permissions, quotas, backups, and auditing, see the [Administrator Guide](docs/ADMIN_GUIDE.md).

## Start in 5 minutes

### 1. Prepare the environment

- Docker Engine 24+ or Docker Desktop
- Docker Compose v2
- At least 8 GB of memory is recommended; 16 GB is recommended when sandbox and document processing are enabled

```bash
git clone https://github.com/wdyh1314520-gif/apervia-open-source.git
cd apervia-open-source
cp .env.example .env
```

If the repository or GHCR package is private, sign in first:

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

### 2. Configure the images

Edit `.env`:

```dotenv
APP_IMAGE=ghcr.io/wdyh1314520-gif/apervia-open-source:latest
SANDBOX_DOCKER_IMAGE=ghcr.io/wdyh1314520-gif/apervia-open-source-sandbox:latest
APP_BIND_IP=127.0.0.1
APP_HOST_PORT=8002
```

Keep `APP_BIND_IP=127.0.0.1` for local-only use. For LAN access, change it to a specific interface address or `0.0.0.0`, and configure a firewall, reverse proxy, and TLS at the same time.

### 3. Start the App

```bash
docker compose pull app
docker compose up -d app
docker compose ps
curl --fail http://127.0.0.1:8002/api3/health/ready
```

Open [http://127.0.0.1:8002](http://127.0.0.1:8002). A new data volume does not include, simulate, or import any account automatically. The first real registered account becomes the administrator; subsequent accounts require administrator approval by default.

### 4. Enable the isolated sandbox (optional)

Generate a Runner shared secret and add it to `.env`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

```dotenv
SANDBOX_TOOLS_ENABLED=1
SANDBOX_RUNNER_SECRET=REPLACE_WITH_THE_GENERATED_VALUE
```

On native Linux, also set `DOCKER_SOCKET_GID` to the group ID of the Docker socket:

```bash
stat -c %g /var/run/docker.sock
docker compose --profile sandbox pull app sandbox-runner sandbox-image
docker compose --profile sandbox up -d app sandbox-runner
docker compose --profile sandbox ps
```

When the sandbox is disabled, keep `SANDBOX_TOOLS_ENABLED=0`. Neither Chat nor Responses will receive sandbox tool definitions that cannot be executed.

## Documentation

The detailed documentation listed below is maintained in English.

| Document | Description |
| --- | --- |
| [Quick Start](docs/QUICKSTART.md) | Installation, the first administrator, local builds, and basic checks |
| [User Guide](docs/USER_GUIDE.md) | Signed-in workspace, models, files, knowledge bases, MCP, and sandbox usage |
| [Administrator Guide](docs/ADMIN_GUIDE.md) | Account approval, permissions, platform data, backups, auditing, and rate limits |
| [Integration Guide](docs/INTEGRATIONS.md) | MCP, SearXNG, Ollama, and host services |
| [Operations Guide](docs/OPERATIONS.md) | Backup, restore, upgrade, rollback, logs, and troubleshooting |
| [Release Guide](docs/RELEASE_GUIDE.md) | Changes, pull requests, release notes, image publishing, upgrades, and rollback |
| [Runbook](RUNBOOK.md) | Code-level runtime boundaries and advanced troubleshooting |
| [Security Policy](SECURITY.md) | Vulnerability reporting and supported versions |
| [Contributing Guide](CONTRIBUTING.md) | Development, verification, and commit conventions |

## Local builds and verification

Prefer reusing published images. To develop the current source code locally:

```bash
docker build -t apervia:local .
docker build -t apervia-sandbox:local docker/sandbox-prod
```

Change the image references in `.env` to the local tags and set `APP_PULL_POLICY=never`. Before submitting changes, run:

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q app3.py app3_parts sandbox_runner mcp_client tests
docker compose --profile sandbox config --quiet
docker compose --profile sandbox-build config --quiet
```

## Data and upgrade principles

- All runtime data is stored in the Compose named volume `apervia_app3_data`.
- Back up the data volume before every upgrade and retain the complete image tag for the previous version.
- Back up the MCP database `/data/mcp_server_store.db` together with its key `/data/mcp_token.key`.
- Do not run `docker compose down -v` unless you explicitly intend to permanently delete all runtime data.
- Rolling back an image does not roll back the database format. If a release includes a data migration, restore the matching backup according to the release notes.

For deployments published from another repository, use a versioned image reference such as:

```dotenv
APP_IMAGE=ghcr.io/<owner>/<repository>:1.0.1
```

A standard backup archive may be named `apervia-data.tar.gz`. Restoring overwrites the current volume data, so back up the current state and verify the target volume name first.

See the [Operations Guide](docs/OPERATIONS.md) for the complete procedure.

## Current limitations

- The current design supports a single App instance and does not support direct horizontal scaling.
- The repository does not include domain, reverse proxy, TLS, or automatic certificate configuration.
- Sandbox features depend on the host Docker Engine and are disabled by default.
- Before exposing the service externally, configure access control, firewall rules, HTTPS, backups, and a tested recovery procedure.

## Contributing

Before submitting an issue or change, read the [Contributing Guide](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md). Report security issues privately according to the [Security Policy](SECURITY.md); do not disclose vulnerability details publicly.
