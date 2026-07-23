# App3 production sandbox image

This is the production image for the real App3 Docker sandbox. It is not a lightweight extension of `python:3.12.13-slim`; it is based on `python:3.12.13-bookworm` and includes Office, PDF, OCR, image processing, HTML rendering, Playwright, and commonly used data-processing dependencies.

## Build

For servers in regions where alternative package mirrors are faster, pass mirror URLs explicitly:

```bash
cd /opt/app3
docker build \
  --build-arg APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  -t app3-sandbox:py312-prod \
  -f docker/sandbox-prod/Dockerfile \
  docker/sandbox-prod
```

If the server can access the official package sources reliably, omit the build arguments:

```bash
docker build -t app3-sandbox:py312-prod -f docker/sandbox-prod/Dockerfile docker/sandbox-prod
```

## Probe

```bash
mkdir -p /tmp/app3-sandbox-prod-test
docker run --rm --network none \
  --memory 2g --cpus 2.0 --pids-limit 256 \
  --shm-size 256m \
  --cap-drop ALL --security-opt no-new-privileges \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=512m \
  --tmpfs /var/tmp:rw,noexec,nosuid,size=128m \
  -e HOME=/mnt/data \
  -e PYTHONIOENCODING=utf-8 \
  -e PYTHONUTF8=1 \
  -v /tmp/app3-sandbox-prod-test:/mnt/data:rw \
  app3-sandbox:py312-prod \
  python /opt/app3-sandbox/probe.py
```

## App3 service environment variables

Production deployments should set at least:

```ini
Environment=SANDBOX_TOOLS_ENABLED=1
Environment=SANDBOX_DOCKER_IMAGE=app3-sandbox:py312-prod
Environment=SANDBOX_DOCKER_MEMORY=2g
Environment=SANDBOX_DOCKER_CPUS=2.0
Environment=SANDBOX_DOCKER_PIDS_LIMIT=256
Environment=SANDBOX_DOCKER_SHM_SIZE=256m
Environment=SANDBOX_DOCKER_NETWORK=none
Environment=SANDBOX_DOCKER_TMPFS_SIZE=512m
Environment=SANDBOX_DOCKER_VAR_TMPFS_SIZE=128m
Environment=SANDBOX_COMMAND_TIMEOUT=120
Environment=SANDBOX_DISK_MAX_BYTES=2147483648
```

Apply the changes:

```bash
sudo systemctl daemon-reload
sudo systemctl restart app3.service
sudo systemctl status app3.service --no-pager
```

## Notes

- Keep `SANDBOX_DOCKER_NETWORK=none` as the production default.
- The image extends the tools and dependencies inside the container; it does not change App3's host-isolation model.
- If large machine-learning packages such as `torch`, `jax`, `spacy`, `xgboost`, or `catboost` are needed, create a separate image such as `app3-sandbox:py312-ml` instead of adding them to the default production image.
