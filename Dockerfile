FROM node:22-bookworm-slim

ARG CODEX_CLI_VERSION=0.147.0
ARG HERMES_AGENT_VERSION=0.18.0
ARG MCP_SDK_VERSION=2.0.0
ARG PILLOW_VERSION=12.2.0

ENV PYTHONUNBUFFERED=1 \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=7871 \
    ALLOW_PUBLIC_DASHBOARD=true \
    AGENT_CHAT_PROVIDER=hermes \
    HERMES_CLI=hermes \
    HERMES_ENABLED_TOOLSETS=memory,session_search,vision,file \
    HERMES_DISABLED_TOOLSETS=terminal,code_execution,image_gen,skills \
    HERMES_USE_PYTHON_LIBRARY=true \
    HERMES_REQUIRE_CODEX_AUTH=true \
    CODEX_CREATIVE_ENABLED=true \
    CODEX_CLI=codex \
    CODEX_HOME=/app/runtime/hermes/codex-auth

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip ca-certificates curl git openssl ffmpeg xz-utils \
        libnss3 libdbus-1-3 libatk1.0-0 libgbm-dev libasound2 libxrandr2 \
        libxkbcommon-dev libxfixes3 libxcomposite1 libxdamage1 \
        libatk-bridge2.0-0 libpango-1.0-0 libcairo2 libcups2 \
        fonts-noto-core fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/local/bin/python3

RUN npm install -g "@openai/codex@${CODEX_CLI_VERSION}"
RUN python3 -m pip install --break-system-packages --no-cache-dir \
    "mcp==${MCP_SDK_VERSION}" \
    "python-telegram-bot>=21,<22" \
    "openpyxl>=3.1,<4" \
    "pypdf>=5,<7" \
    "xlrd>=2,<3" \
    "Pillow==${PILLOW_VERSION}" \
    "hermes-agent==${HERMES_AGENT_VERSION}" \
    && hermes --version

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts \
    && npx remotion browser ensure

# Release-specific metadata belongs after the expensive, version-independent
# dependency layers.  A new rXX/SHA must rebuild the source/provenance layers,
# but must not reinstall the OS, Hermes, Codex, Python and browser toolchains.
ARG ADMIRA_BUILD_VERSION=unknown
ARG ADMIRA_BUILD_SHA=unknown
ARG ADMIRA_SOURCE_MANIFEST=unknown

LABEL org.opencontainers.image.title="Admira IA" \
      org.opencontainers.image.version="${ADMIRA_BUILD_VERSION}" \
      org.opencontainers.image.revision="${ADMIRA_BUILD_SHA}" \
      org.opencontainers.image.source-manifest="${ADMIRA_SOURCE_MANIFEST}" \
      org.opencontainers.image.description="Admira IA agent runtime"

COPY . .
RUN chmod +x scripts/*.sh \
    && printf '%s\n' "${ADMIRA_SOURCE_MANIFEST}" > /app/source-manifest.sha256 \
    && printf '%s\n' "${ADMIRA_BUILD_SHA}" > /app/build-commit.sha \
    && mkdir -p brand_guides \
    && cp -R brand_guides /app/brand_guides_seed \
    && mkdir -p /app/runtime /app/dashboard/data /app/output /app/logs

EXPOSE 7871

CMD ["bash", "scripts/docker-entrypoint.sh"]
