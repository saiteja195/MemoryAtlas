# MemoryAtlas API. Build context is the repository root (it needs fixtures/ as well as backend/):
#   docker build -f backend/Dockerfile -t memoryatlas-backend .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# The app finds fixtures/ and eval/ relative to the repository root (app/config.py: parents[2]),
# so keep the same layout under /app.
WORKDIR /app

# Dependencies first, so editing code does not reinstall them. They are read from pyproject.toml
# so there is one list to maintain.
COPY backend/pyproject.toml /tmp/pyproject.toml
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('/tmp/pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
 && pip install -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt /tmp/pyproject.toml

COPY backend/app backend/app
COPY backend/scripts backend/scripts
COPY fixtures fixtures
COPY eval/questions.yaml eval/questions.yaml

# Run as an unprivileged user. /data holds the SQLite file and the model-response cache.
RUN useradd --system --uid 10001 --no-create-home memoryatlas \
 && mkdir -p /data /app/eval/results \
 && chown -R memoryatlas /data /app/eval/results
USER memoryatlas
VOLUME /data

ENV MEMORYATLAS_DB=/data/memoryatlas.db \
    MEMORYATLAS_LLM_MODE=replay
WORKDIR /app/backend
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
