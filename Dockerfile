FROM python:3.14-slim-trixie AS build

# Copy the project into the image
COPY . /app

# Disable development dependencies
ENV UV_NO_DEV=1

# Sync the project into a new environment, asserting the lockfile is up to date
WORKDIR /app/
RUN --mount=from=ghcr.io/astral-sh/uv:0.10,source=/uv,target=/bin/uv \
    uv sync --locked


FROM python:3.14-slim-trixie

ENV PATH="/app/.venv/bin:$PATH"
COPY --from=build /app/ /app/

ENTRYPOINT [ "python", "main.py" ]
