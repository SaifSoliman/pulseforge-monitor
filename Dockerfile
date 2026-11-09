FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/pulseforge.db

WORKDIR /srv/pulseforge
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd -r pulseforge && useradd -r -g pulseforge pulseforge \
    && mkdir -p /data && chown pulseforge:pulseforge /data
COPY app ./app
USER pulseforge
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3)" || exit 1
# One process only: avoids duplicate scheduled probes against the same SQLite database.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
