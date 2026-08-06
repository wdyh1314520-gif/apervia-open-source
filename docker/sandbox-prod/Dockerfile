FROM python:3.14.0-bookworm

ARG APT_MIRROR=
ARG PIP_INDEX_URL=
ARG APP_BUILD_VERSION=
ARG APP_BUILD_SHA=unknown

LABEL org.opencontainers.image.title="Apervia Sandbox" \
      org.opencontainers.image.version="${APP_BUILD_VERSION}" \
      org.opencontainers.image.revision="${APP_BUILD_SHA}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    MPLCONFIGDIR=/mnt/data/.cache/matplotlib \
    XDG_CACHE_HOME=/mnt/data/.cache \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

WORKDIR /mnt/data

RUN set -eux; \
    if [ -n "$APT_MIRROR" ]; then \
      sed -i "s|http://deb.debian.org/debian|$APT_MIRROR|g; s|http://security.debian.org/debian-security|$APT_MIRROR-security|g" /etc/apt/sources.list.d/debian.sources || true; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      bash \
      build-essential \
      ca-certificates \
      curl \
      file \
      fontconfig \
      fonts-dejavu \
      fonts-liberation \
      fonts-noto-cjk \
      fonts-noto-color-emoji \
      ghostscript \
      git \
      jq \
      less \
      libbz2-dev \
      libcairo2 \
      libffi-dev \
      libgdk-pixbuf-2.0-0 \
      libglib2.0-0 \
      libgl1 \
      libgomp1 \
      libjpeg62-turbo \
      libmagic1 \
      libnss3 \
      libpango-1.0-0 \
      libpangocairo-1.0-0 \
      libsqlite3-dev \
      libssl-dev \
      libtiff6 \
      libxml2 \
      libxslt1.1 \
      libreoffice \
      nodejs \
      npm \
      pandoc \
      poppler-utils \
      p7zip-full \
      qpdf \
      ripgrep \
      shared-mime-info \
      tesseract-ocr \
      tesseract-ocr-chi-sim \
      tesseract-ocr-eng \
      unzip \
      wget \
      wkhtmltopdf \
      xz-utils \
      zip \
      zlib1g-dev; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /opt/app3-sandbox/requirements.txt
COPY probe.py /opt/app3-sandbox/probe.py

RUN set -eux; \
    python -m pip install --upgrade pip setuptools wheel; \
    if [ -n "$PIP_INDEX_URL" ]; then \
      python -m pip install -i "$PIP_INDEX_URL" -r /opt/app3-sandbox/requirements.txt; \
    else \
      python -m pip install -r /opt/app3-sandbox/requirements.txt; \
    fi; \
    python -m playwright install --with-deps chromium; \
    python /opt/app3-sandbox/probe.py --quick

CMD ["python", "-V"]
