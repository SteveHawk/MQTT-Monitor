import asyncio
import contextlib
from typing import AsyncGenerator

import fasthtml.common as ft
from fasthtml.common import Article, Div, Script, Titled
from loguru import logger
from starlette.applications import Starlette
from starlette.responses import StreamingResponse

from mqtt_monitor import MQTTMonitor

mqtt_monitor = MQTTMonitor()


@contextlib.asynccontextmanager
async def mqttc_lifespan(app: Starlette) -> AsyncGenerator[None, None]:
    with mqtt_monitor:
        yield


app, rt = ft.fast_app(
    lifespan=mqttc_lifespan,
    hdrs=(Script(src="https://unpkg.com/htmx-ext-sse@2.2.1/sse.js"),),
)


@app.get("/")
def home() -> ft.FT:
    return Titled(
        "Meshtastic MQTT Monitor",
        Div(
            hx_ext="sse",
            sse_connect="/new-message",
            hx_swap="beforeend show:bottom",
            sse_swap="message",
            *[
                Article(str(message))
                for message in mqtt_monitor.ring_buffer.fetch_all()
            ],
        ),
    )


@app.get("/new-message")
async def new_message() -> StreamingResponse:
    async def get_message() -> AsyncGenerator[str, None]:
        shutdown_event = ft.signal_shutdown()
        current_id = mqtt_monitor.ring_buffer.max_id

        while not shutdown_event.is_set():  # TODO: handle shutdown event
            await asyncio.to_thread(mqtt_monitor.ring_buffer.wait)
            for message in mqtt_monitor.ring_buffer.fetch_new(current_id):
                logger.info(f"New message sent: {message.id=}, {current_id=}")
                yield ft.sse_message(Article(str(message)))
                current_id = message.id

    return StreamingResponse(get_message(), media_type="text/event-stream")


if __name__ == "__main__":
    ft.serve()
