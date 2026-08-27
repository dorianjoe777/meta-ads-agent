FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY app-requirements.txt /app/app-requirements.txt
RUN python -m pip install --no-cache-dir --requirement /app/app-requirements.txt
COPY hosted_service.py hosted_worker.py telegram_ingress.py runtime_broker.py tenant_turn.py tenantctl.py /app/

USER 1001:1001
ENTRYPOINT ["python", "/app/hosted_service.py"]
