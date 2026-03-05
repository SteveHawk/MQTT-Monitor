import asyncio
import contextlib
from typing import AsyncGenerator

import fasthtml.common as ft
from fasthtml.common import Article, Div, Script, Titled
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
    hdrs=(
        Script(src="https://unpkg.com/htmx-ext-sse@2.2.1/sse.js"),
        Script(
            'function getMsgId() { var msgs = [...document.querySelectorAll("#messages [id]")];'
            'return msgs.length === 0 ? 0 : msgs.pop().id.split("_")[1]; }'
        ),
    ),
)


@app.get("/")
def home() -> ft.FT:
    return Titled(
        "Meshtastic MQTT Monitor",
        Div(
            Div(
                *[
                    Article(str(message), id=f"message_{message.id}")
                    for message in mqtt_monitor.ring_buffer.fetch_all()
                ],
                id="messages",
                hx_get="/fetch-messages",
                hx_trigger="sse:new_message",
                hx_vals="js:{current_id: getMsgId()}",
                hx_swap="beforeend show:bottom",
            ),
            hx_ext="sse",
            sse_connect="/sse-new-msg",
        ),
    )


@app.get("/sse-new-msg")
async def new_message() -> StreamingResponse:
    async def notify() -> AsyncGenerator[str, None]:
        shutdown_event = ft.signal_shutdown()

        while not shutdown_event.is_set():  # TODO: handle shutdown event
            await asyncio.to_thread(mqtt_monitor.ring_buffer.wait)
            yield ft.sse_message("new msg", event="new_message")

    return StreamingResponse(notify(), media_type="text/event-stream")


@app.get("/fetch-messages")
def fetch_messages(current_id: int) -> list[ft.FT]:
    return [
        Article(str(message), id=f"message_{message.id}")
        for message in mqtt_monitor.ring_buffer.fetch_new(current_id)
    ]


if __name__ == "__main__":
    ft.serve()
