# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv
WORKDIR /app

# Dependency layer (cached unless pyproject/uv.lock change).
FROM base AS deps
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

FROM deps AS app
COPY src ./src
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" \
    ARTEMIS_HOME=/data
VOLUME ["/data"]
ENTRYPOINT ["artemis"]
CMD ["version"]
