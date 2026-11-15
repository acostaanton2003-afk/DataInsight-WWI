# Backend únicamente. Construir desde la raíz del repositorio.
# Base oficial fijada por digest; actualizar deliberadamente para recibir parches.
FROM python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    BACKEND_DOCS_ENABLED=false \
    ASSISTANT_PROVIDER=local

WORKDIR /app
COPY backend/requirements-docker.lock.txt /app/requirements-docker.lock.txt
# Wheels precompilados: sin compiladores, Rust, ODBC, dependencias de tests o ML.
RUN python -m pip install --only-binary=:all: --no-compile \
        --index-url https://pypi.org/simple -r /app/requirements-docker.lock.txt \
    && python -m pip check

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/artifacts/machine_learning/published
COPY backend/__init__.py /app/backend/__init__.py
COPY backend/app /app/backend/app

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=2); assert r.status==200"]

# Un worker conserva memoria y la cuota IA por proceso. No ETL, modelos ni Ollama.
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "24", "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "10", "--no-access-log", "--no-proxy-headers"]
