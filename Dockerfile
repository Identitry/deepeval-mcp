# ---- Builder stage ----
FROM python:3.11-slim AS builder

ARG DEEPEVAL_WRAPPER_REPO=https://github.com/theaiautomators/deepeval-wrapper.git
ARG DEEPEVAL_WRAPPER_VERSION=master

WORKDIR /app
RUN set -eux; \
    apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# NOTE: requirements.txt must include hashes; generate them with `pip-compile --generate-hashes`.
RUN set -eux; \
    git clone --depth 1 --branch "${DEEPEVAL_WRAPPER_VERSION}" "${DEEPEVAL_WRAPPER_REPO}" /app/deepeval_wrapper; \
    pip install --no-cache-dir -r /app/deepeval_wrapper/requirements.txt; \
    pip install --no-cache-dir --upgrade -r requirements.txt; \
    rm -rf /root/.cache/pip /app/deepeval_wrapper/.git

COPY src ./src

RUN set -eux; python -m compileall /usr/local/lib/python3.11/site-packages /app/deepeval_wrapper /app/src


# ---- Runtime stage ----
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.source="https://github.com/Identitry/deepeval-mcp"
LABEL org.opencontainers.image.description="Deepeval MCP Server with integrated wrapper"
LABEL org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/deepeval_wrapper \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    # Set default encoding for all Python operations
    PYTHONUTF8=1

WORKDIR /app

RUN set -eux; \
    apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local /usr/local
COPY --from=builder /app/deepeval_wrapper /app/deepeval_wrapper
COPY --from=builder /app/src /app/src
# .env.example is provided for reference; it is not loaded automatically in runtime.
COPY .env.example .env.example

# Install sitecustomize.py to force UTF-8 globally for all Python code
COPY sitecustomize.py /usr/local/lib/python3.11/site-packages/sitecustomize.py

# Copy test script for debugging
COPY test_encoding.py /app/test_encoding.py

RUN set -eux; find /app -type f -name '*.pyc' -delete

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD curl -fs http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
