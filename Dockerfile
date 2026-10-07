# syntax=docker/dockerfile:1
# Claude Code (headless) + Python runtime for archivist.
FROM node:20-slim AS node-stage

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG CLAUDE_CODE_VERSION=2.1.159
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"
# Pi, the second harness (ADR 0008; ARCHIVIST_HARNESS=pi). Pinned like Claude Code.
ARG PI_VERSION=1.0.4
RUN npm install -g --ignore-scripts "@earendil-works/pi-coding-agent@${PI_VERSION}"

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH=/usr/local/bin:$PATH \
    NODE_PATH=/usr/local/lib/node_modules \
    DOCKER_CONTAINER=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        fd-find \
        gh \
        git \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node-stage /usr/local/bin/node /usr/local/bin/node
COPY --from=node-stage /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node-stage /usr/local/bin/claude /usr/local/bin/claude
COPY --from=node-stage /usr/local/bin/pi /usr/local/bin/pi
RUN ln -s ../lib/node_modules/@anthropic-ai/claude-code/vendor /usr/local/bin/vendor

WORKDIR /app

COPY pyproject.toml README.md ./
COPY schemas ./schemas
COPY targets.yaml ./
COPY bundle-template ./bundle-template
COPY examples ./examples
COPY src ./src
COPY agents ./agents
COPY skills ./skills
COPY harness ./harness
COPY tests ./tests
COPY scripts ./scripts
COPY docker ./docker

RUN chmod +x docker/entrypoint.sh docker/claude_token_cache.sh

# The build context has no .git, so the engine's version cannot come from git tags here: it is
# a development version (0.0.0.dev0) unless a release image passes --build-arg
# ARCHIVIST_VERSION=X.Y.Z from a checkout of tag vX.Y.Z. A development image hands pinned
# targets to their pinned release; `--engine current` runs the image's own code.
ARG ARCHIVIST_VERSION=
RUN pip install --upgrade pip \
    && SETUPTOOLS_SCM_PRETEND_VERSION_FOR_ARCHIVIST="${ARCHIVIST_VERSION:-0.0.0.dev0}" pip install -e ".[dev]" \
    && chmod +x tests/run.sh tests/smoke-claude.sh scripts/*.sh

RUN groupadd -r appuser && useradd -r -g appuser -m -d /home/appuser appuser \
    && mkdir -p /workspace \
    && chown -R appuser:appuser /app /home/appuser /workspace

USER appuser
ENV HOME=/home/appuser

EXPOSE 8080

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["archivist", "config-check"]
