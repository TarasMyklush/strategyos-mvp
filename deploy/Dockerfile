FROM python:3.12-slim

ARG CA_CERTIFICATES_VERSION=20250419
ARG CURL_VERSION=8.14.1-2+deb13u3
ARG POPPLER_UTILS_VERSION=25.03.0-5+deb13u2
ARG TESSERACT_OCR_VERSION=5.5.0-1+b1
ARG TESSERACT_OCR_ENG_VERSION=1:4.1.0-2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STRATEGYOS_WORKSPACE_ROOT=/app/workspace \
    STRATEGYOS_OUTPUT_ROOT=/app/workspace/outputs \
    STRATEGYOS_OCR_ENGINE=tesseract \
    STRATEGYOS_RUNTIME_DEP_CA_CERTIFICATES_VERSION=${CA_CERTIFICATES_VERSION} \
    STRATEGYOS_RUNTIME_DEP_CURL_VERSION=${CURL_VERSION} \
    STRATEGYOS_RUNTIME_DEP_POPPLER_UTILS_VERSION=${POPPLER_UTILS_VERSION} \
    STRATEGYOS_RUNTIME_DEP_TESSERACT_VERSION=${TESSERACT_OCR_VERSION} \
    STRATEGYOS_RUNTIME_DEP_TESSERACT_ENG_VERSION=${TESSERACT_OCR_ENG_VERSION}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates=${CA_CERTIFICATES_VERSION} \
        curl=${CURL_VERSION} \
        poppler-utils=${POPPLER_UTILS_VERSION} \
        tesseract-ocr=${TESSERACT_OCR_VERSION} \
        tesseract-ocr-eng=${TESSERACT_OCR_ENG_VERSION} \
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
