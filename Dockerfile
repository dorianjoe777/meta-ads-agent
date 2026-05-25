FROM node:22-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=7871 \
    ALLOW_PUBLIC_DASHBOARD=true \
    CODEX_CREATIVE_ENABLED=false \
    CODEX_CLI=codex

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip ca-certificates curl git openssl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/local/bin/python3

RUN npm install -g @openai/codex

COPY . .
RUN chmod +x scripts/*.sh \
    && cp -R brand_guides /app/brand_guides_seed \
    && mkdir -p /app/runtime /app/dashboard/data /app/output /app/logs

EXPOSE 7871

CMD ["bash", "scripts/docker-entrypoint.sh"]
