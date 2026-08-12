FROM python:3.12-slim

ARG MEDIA_JANITOR_UID=10001
ARG MEDIA_JANITOR_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --gid "${MEDIA_JANITOR_GID}" mediajanitor \
    && useradd --uid "${MEDIA_JANITOR_UID}" --gid mediajanitor --create-home --no-log-init mediajanitor

COPY pyproject.toml ./
COPY src ./src

RUN python -m pip install --no-cache-dir . \
    && mkdir -p /state \
    && chown mediajanitor:mediajanitor /state

USER mediajanitor:mediajanitor

VOLUME ["/state"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["media-janitor", "--help"]

ENTRYPOINT ["media-janitor"]
CMD ["--help"]
