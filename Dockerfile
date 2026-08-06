FROM python:3.14.0-bookworm

ARG APT_MIRROR=
ARG PIP_INDEX_URL=
ARG APP_BUILD_VERSION=
ARG APP_BUILD_SHA=unknown

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    APP_HOST=0.0.0.0 \
    APP_PORT=8002 \
    APP_DATA_DIR=/data \
    APP_BUILD_VERSION=${APP_BUILD_VERSION} \
    APP_BUILD_SHA=${APP_BUILD_SHA} \
    HOME=/data/home \
    XDG_CACHE_HOME=/data/cache

LABEL org.opencontainers.image.title="Apervia" \
      org.opencontainers.image.version="${APP_BUILD_VERSION}" \
      org.opencontainers.image.revision="${APP_BUILD_SHA}"

WORKDIR /app

RUN set -eux; \
    if [ -n "$APT_MIRROR" ]; then \
      sed -i "s|http://deb.debian.org/debian|$APT_MIRROR|g; s|http://security.debian.org/debian-security|$APT_MIRROR-security|g" /etc/apt/sources.list.d/debian.sources || true; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      fonts-dejavu \
      fonts-liberation \
      fonts-noto-cjk \
      fonts-noto-color-emoji \
      libmagic1 \
      libreoffice-calc \
      libreoffice-draw \
      libreoffice-impress \
      libreoffice-writer \
      pandoc \
      poppler-utils \
      tesseract-ocr \
      tesseract-ocr-chi-sim \
      tesseract-ocr-eng; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN set -eux; \
    python -m pip install --upgrade pip setuptools wheel; \
    if [ -n "$PIP_INDEX_URL" ]; then \
      python -m pip install --index-url "$PIP_INDEX_URL" -r /tmp/requirements.txt; \
    else \
      python -m pip install -r /tmp/requirements.txt; \
    fi; \
    python -m playwright install --with-deps chromium; \
    rm -f /tmp/requirements.txt

COPY app3.py /app/app3.py
COPY VERSION /app/VERSION
COPY app3_parts /app/app3_parts
COPY app3_skills /app/app3_skills
COPY mcp_client /app/mcp_client
COPY sandbox_runner /app/sandbox_runner
COPY static /app/static
COPY release /app/release
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN set -eux; \
    groupadd --gid 10001 app3; \
    useradd --uid 10001 --gid 10001 --create-home --home-dir /home/app3 --shell /usr/sbin/nologin app3; \
    chmod 0755 /usr/local/bin/docker-entrypoint.sh; \
    mkdir -p /data; \
    chown -R app3:app3 /data /home/app3

USER app3

EXPOSE 8002

HEALTHCHECK --interval=20s --timeout=5s --start-period=45s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/api3/health/ready', timeout=4).read()"

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "/app/app3.py"]
