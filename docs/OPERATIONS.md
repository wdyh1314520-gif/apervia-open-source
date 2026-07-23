# Apervia Operations Guide

## Routine status checks

```bash
docker compose ps
docker compose logs --tail 200 app
docker compose --profile sandbox logs --tail 200 sandbox-runner
curl --fail http://127.0.0.1:8002/api3/health/ready
docker compose images
```

The health endpoint returns the application build version and commit SHA. After an upgrade, confirm that both match the target image.

## Data location

Default Compose named volume:

```text
apervia_app3_data
```

Inspect the actual name and mount point:

```bash
docker volume inspect apervia_app3_data
docker compose exec app sh -lc 'id && ls -la /data | head'
```

Do not modify SQLite files in the volume directly. Stop the App before a backup to avoid copying an inconsistent state.

## Backup

```bash
mkdir -p backups
docker compose stop app sandbox-runner
docker run --rm \
  -v apervia_app3_data:/source:ro \
  -v "$PWD/backups:/backup" \
  alpine:3.21 \
  sh -c 'cd /source && tar czf /backup/apervia-data-$(date +%Y%m%d-%H%M%S).tar.gz .'
docker compose --profile sandbox start app sandbox-runner
```

If the sandbox is not enabled, replace the final command with `docker compose start app`.

Inspect the archive:

```bash
ls -lh backups/
tar tzf backups/apervia-data-YYYYMMDD-HHMMSS.tar.gz | head
```

The backup must contain the MCP database and its matching key. Copy backups to another controlled device and perform recovery exercises regularly.

## Restore

Restoration overwrites current data. Back up the current volume again before running:

```bash
docker compose down
docker run --rm \
  -v apervia_app3_data:/target \
  -v "$PWD/backups:/backup:ro" \
  alpine:3.21 \
  sh -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && cd /target && tar xzf /backup/apervia-data-YYYYMMDD-HHMMSS.tar.gz'
docker compose --profile sandbox up -d app sandbox-runner
```

This is a destructive operation. Confirm the volume name and archive name, and verify that the current data has a recoverable backup. Never run cleanup commands against an uncertain directory or volume.

## Upgrade

1. Read the target release notes.
2. Back up the data volume.
3. Pin both App and Sandbox images in `.env` to the same release version:

```dotenv
APP_IMAGE=ghcr.io/wdyh1314520-gif/apervia-open-source:1.0.0
SANDBOX_DOCKER_IMAGE=ghcr.io/wdyh1314520-gif/apervia-open-source-sandbox:1.0.0
```

4. Pull and recreate the containers:

```bash
docker compose --profile sandbox pull app sandbox-runner
docker compose --profile sandbox up -d --force-recreate app sandbox-runner
docker compose ps
curl --fail http://127.0.0.1:8002/api3/health/ready
```

5. Sign in and verify conversations, files, knowledge bases, MCP, and sandbox features.

Production deployments should pin a complete version tag instead of following `latest` indefinitely.

## Rollback

Change both image references in `.env` back to the previous complete version tag, and then recreate the containers. Keep the App and Sandbox versions aligned.

```bash
docker compose --profile sandbox pull app sandbox-runner
docker compose --profile sandbox up -d --force-recreate app sandbox-runner
```

If the release includes a database migration, rolling back only the images may be insufficient. Restore the pre-upgrade data-volume backup according to the release notes.

## Troubleshooting

### The App does not start

```bash
docker compose config
docker compose logs --tail 300 app
docker inspect apervia-app-1 --format '{{json .State}}'
```

Check `.env`, image permissions, data-volume write permissions, port conflicts, and available memory.

### The Sandbox Runner is unhealthy

```bash
docker compose --profile sandbox logs --tail 300 sandbox-runner
docker compose exec sandbox-runner python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8767/healthz').read().decode())"
```

Confirm that `SANDBOX_RUNNER_SECRET` is identical in the App and Runner, that `DOCKER_SOCKET_GID` is correct, and that the Runner can access the Docker socket.

### A container cannot access a host service

Do not use `localhost`. Use `host.docker.internal`, and check the target service bind address and firewall. See the [Integration Guide](INTEGRATIONS.md).

### MCP OAuth reports a private-network block

Check whether a proxy resolved DNS to the `198.18.0.0/15` Fake-IP range. Correct the proxy exclusion rule instead of disabling SSRF protection.

### Disk usage is growing

```bash
docker system df
docker volume inspect apervia_app3_data
```

First review file, trash, backup, and sandbox-package usage in the administration console. Do not delete data-volume content directly or clean Docker resources indiscriminately.

## Taking the service offline

Keep the data volume:

```bash
docker compose down
```

`docker compose down -v` deletes runtime data and is not part of normal shutdown.
