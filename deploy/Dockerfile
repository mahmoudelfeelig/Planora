FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLANORA_DB_PATH=/app/data/planora.sqlite3

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY api api
COPY benchmarks benchmarks
COPY config config
COPY connectors connectors
COPY core core
COPY product product
COPY services services
COPY web/public/app-icon.png services/assets/planora_elephant.png
COPY scripts scripts
COPY utils utils

RUN addgroup --system planora && adduser --system --ingroup planora planora \
    && mkdir -p /app/data /backups \
    && chown -R planora:planora /app/data /backups

USER planora

EXPOSE 8787
CMD ["python", "-m", "api.server", "--host", "0.0.0.0", "--port", "8787"]
