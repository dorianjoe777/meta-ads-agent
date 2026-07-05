FROM node:22-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=7871 \
    ALLOW_PUBLIC_DASHBOARD=true \
    AGENT_CHAT_PROVIDER=hermes \
    HERMES_CLI=hermes \
    HERMES_ENABLED_TOOLSETS=memory,skills,session_search,vision,file \
    HERMES_DISABLED_TOOLSETS=terminal,code_execution,image_gen \
    HERMES_USE_PYTHON_LIBRARY=true \
    HERMES_REQUIRE_CODEX_AUTH=true \
    CODEX_CREATIVE_ENABLED=true \
    CODEX_CLI=codex \
    CODEX_HOME=/app/runtime/codex

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip ca-certificates curl git openssl ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/local/bin/python3

RUN npm install -g @openai/codex
RUN python3 -m pip install --break-system-packages --no-cache-dir \
    "mcp>=1.0.0" \
    "python-telegram-bot>=21,<22" \
    "git+https://github.com/NousResearch/hermes-agent.git"

COPY . .
RUN chmod +x scripts/*.sh \
    && cp -R brand_guides /app/brand_guides_seed \
    && mkdir -p /app/runtime /app/dashboard/data /app/output /app/logs

EXPOSE 7871

CMD ["bash", "scripts/docker-entrypoint.sh"]
