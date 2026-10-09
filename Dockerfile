# syntax=docker/dockerfile:1
#
# Targets:
#   full  (default) all three strategies: HTTP, Chromium, Camoufox (+ xvfb for virtual display)
#   slim            HTTP strategy only; browser strategies report "unavailable"
#
# Run (stdio MCP server):
#   docker run -i --rm --shm-size=1g -v web-fetch-2000-data:/data web-fetch-2000
ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# some dependencies (indexed-zstd via camoufox) have no aarch64 wheel and compile from source
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libzstd-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:${PYTHON_VERSION}-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    WEBFETCH_DATA_DIR=/data \
    HOME=/home/fetch \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini ca-certificates libzstd1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin fetch \
    && mkdir -p /data /opt/pw-browsers && chown fetch:fetch /data /opt/pw-browsers
COPY --from=builder /app /app
WORKDIR /app
VOLUME ["/data"]

# ---- slim: no browsers -------------------------------------------------------------------
FROM base AS slim
USER fetch
ENTRYPOINT ["tini", "--", "webfetch2000"]

# ---- full: browsers + virtual display -----------------------------------------------------
FROM base AS full
# Chromium and Firefox (Camoufox) system libraries + xvfb (Camoufox virtual-display mode)
RUN playwright install-deps chromium firefox \
    && apt-get update && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*
# Camoufox keeps its fingerprint model inside the fpgen package directory (importing fpgen would
# download it as root), so make that directory owned by the runtime user before fetching.
RUN d="$(python -c 'import importlib.util as u; print(u.find_spec("fpgen").submodule_search_locations[0])')" \
    && mkdir -p "$d/data" && chown -R fetch:fetch "$d"
USER fetch
RUN playwright install chromium && python -m camoufox fetch
# the container is the isolation boundary, so Chromium's own sandbox is disabled here
ENV WEBFETCH_NO_SANDBOX=1
ENTRYPOINT ["tini", "--", "webfetch2000"]
