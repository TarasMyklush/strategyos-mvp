FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STRATEGYOS_WORKSPACE_ROOT=/app/workspace \
    STRATEGYOS_OUTPUT_ROOT=/app/workspace/outputs \
    STRATEGYOS_OCR_ENGINE=tesseract

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md langgraph.json ./
COPY deploy/postgres/schema.sql ./deploy/postgres/schema.sql
COPY strategyos_mvp ./strategyos_mvp
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN useradd --create-home --shell /bin/bash strategyos
RUN mkdir -p /app/workspace/outputs /app/workspace/source_dataset \
    && chown -R strategyos:strategyos /app
USER strategyos

EXPOSE 8000
CMD ["uvicorn", "strategyos_mvp.api:app", "--host", "0.0.0.0", "--port", "8000"]
