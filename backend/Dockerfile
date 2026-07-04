FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

# System deps for scientific stack + psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend/ .
COPY lib /app/lib

EXPOSE 5000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:5000/api/health || exit 1

# Параллельная обработка: несколько воркеров-процессов (WEB_CONCURRENCY, gunicorn
# читает эту переменную), каждый — Uvicorn + пул потоков для sync-эндпоинтов.
# Длинный timeout: цепочка acquire → веса → генерация может занимать минуты.
# WEB_CONCURRENCY переопределяется в .env / docker-compose под ресурсы машины.
ENV WEB_CONCURRENCY=4
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--timeout", "300", "--graceful-timeout", "30", "-k", "uvicorn.workers.UvicornWorker", "wsgi:app"]
