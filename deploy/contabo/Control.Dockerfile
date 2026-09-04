FROM python:3.12.11-slim-bookworm

ARG ADMIRA_BUILD_SHA=unknown
LABEL org.opencontainers.image.title="Admira control plane" \
      org.opencontainers.image.revision="${ADMIRA_BUILD_SHA}" \
      org.opencontainers.image.variant="hosted-control-plane"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY app-requirements.txt /app/app-requirements.txt
RUN python -m pip install --no-cache-dir --requirement /app/app-requirements.txt
COPY hosted_service.py hosted_worker.py telegram_ingress.py runtime_broker.py tenant_turn.py tenantctl.py \
  recovery_identity.py recovery_service.py recovery_email_worker.py recovery_smtp.py /app/

USER 1001:1001
ENTRYPOINT ["python", "/app/hosted_service.py"]
