FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=true

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Pre-warm the PaddleOCR model cache so the first request isn't a 30s
# download. Re-uses the env var above.
RUN PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=true python -c "from paddleocr import PaddleOCR; PaddleOCR()"

COPY app ./app

EXPOSE 8000

# Runtime config is sourced from the environment (docker compose passes
# the root .env in). Default values match the dev .env.example.
ENV UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000 \
    UVICORN_WORKERS=1 \
    UVICORN_LOG_LEVEL=info

CMD ["sh", "-c", "uvicorn app.main:app --host ${UVICORN_HOST} --port ${UVICORN_PORT} --workers ${UVICORN_WORKERS} --log-level ${UVICORN_LOG_LEVEL}"]
