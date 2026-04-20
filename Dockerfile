FROM python:3.14-slim-trixie AS build

COPY ./pyproject.toml ./uv.lock /app/

ENV UV_NO_DEV=1
WORKDIR /app/
RUN --mount=from=ghcr.io/astral-sh/uv:0.10,source=/uv,target=/bin/uv \
    uv sync --locked &&\
    mkdir -p target/data && mv .venv target

COPY ./src/ /app/target/src/


FROM python:3.14-slim-trixie AS default

ENV PATH="/app/.venv/bin:$PATH"
COPY --from=build /app/target/ /app/
WORKDIR /app/

ENTRYPOINT [ "python", "-m", "src.main" ]


FROM default AS cn

ENV MQTT_MONITOR_ADDRESS="mqtt.mess.host" MQTT_MONITOR_ROOT_TOPIC="msh/CN"
