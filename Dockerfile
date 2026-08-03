FROM node:22-bookworm-slim

ARG CODEX_CLI_VERSION=0.142.5
ARG HERMES_AGENT_VERSION=0.18.0
ARG MCP_SDK_VERSION=2.0.0

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
    CODEX_HOME=/app/runtime/codex

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip ca-certificates curl git openssl ffmpeg xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/local/bin/python3

RUN npm install -g "@openai/codex@${CODEX_CLI_VERSION}"
RUN python3 -m pip install --break-system-packages --no-cache-dir \
    "mcp==${MCP_SDK_VERSION}" \
    "python-telegram-bot>=21,<22" \
    "openpyxl>=3.1,<4" \
    "pypdf>=5,<7" \
    "xlrd>=2,<3" \
    "hermes-agent==${HERMES_AGENT_VERSION}" \
    && hermes --version

COPY . .
RUN chmod +x scripts/*.sh \
    && mkdir -p brand_guides \
    && cp -R brand_guides /app/brand_guides_seed \
    && mkdir -p /app/runtime /app/dashboard/data /app/output /app/logs

EXPOSE 7871

CMD ["bash", "scripts/docker-entrypoint.sh"]
