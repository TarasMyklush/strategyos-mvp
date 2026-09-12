FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

# Exact package versions need an immutable repository as well as a pinned base.
# Advance this snapshot and the package versions together for security updates.
ARG DEBIAN_SNAPSHOT=20260912T080000Z

ARG CA_CERTIFICATES_VERSION=20250419
ARG CURL_VERSION=8.14.1-2+deb13u4
ARG POPPLER_UTILS_VERSION=25.03.0-5+deb13u4
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

RUN sed -i \
        -e "s|http://deb.debian.org/debian$|https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}/|" \
        -e "s|http://deb.debian.org/debian-security$|https://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}/|" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Check-Valid-Until=false -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Check-Valid-Until=false -o Acquire::Retries=3 install -y --no-install-recommends \
        ca-certificates=${CA_CERTIFICATES_VERSION} \
        curl=${CURL_VERSION} \
        poppler-utils=${POPPLER_UTILS_VERSION} \
        tesseract-ocr=${TESSERACT_OCR_VERSION} \
        tesseract-ocr-eng=${TESSERACT_OCR_ENG_VERSION} \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md langgraph.json ./
COPY deploy/postgres/schema.sql ./deploy/postgres/schema.sql
COPY deploy/postgres/migrations ./deploy/postgres/migrations
COPY strategyos_mvp ./strategyos_mvp
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[search]"

RUN useradd --create-home --shell /bin/bash strategyos
RUN mkdir -p /app/workspace/outputs /app/workspace/source_dataset \
    && chown -R strategyos:strategyos /app

# Release identity changes on every commit. Keep it after dependency and
# application layers so embedding the exact revision does not invalidate the
# expensive OS/package cache.
ARG STRATEGYOS_RELEASE_SHA=unrecorded
ENV STRATEGYOS_RELEASE_SHA=${STRATEGYOS_RELEASE_SHA}
LABEL org.opencontainers.image.revision=${STRATEGYOS_RELEASE_SHA}

USER strategyos

EXPOSE 8000
CMD ["uvicorn", "strategyos_mvp.api:app", "--host", "0.0.0.0", "--port", "8000"]
