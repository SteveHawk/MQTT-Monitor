import asyncio
import contextlib
from typing import AsyncGenerator

import fasthtml.common as ft
from fasthtml.common import Article, Div, Script, Titled
from starlette.applications import Starlette
from starlette.responses import StreamingResponse

from mqtt_monitor import Message, MQTTMonitor, NodeDB

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


def gen_message_ui(messages: list[Message]) -> list[ft.FT]:
    ui = list[ft.FT]()
    for message in messages:
        user = NodeDB[message.message["from"]]
        msg_ui = Div(
            Div(user["short_name"], cls="avatar"),
            Article(str(message), id=f"message_{message.id}"),
        )
        ui.append(msg_ui)
    return ui


@app.get("/")
def home() -> ft.FT:
    return Titled(
        "Meshtastic MQTT Monitor",
        Div(
            Div(
                *gen_message_ui(mqtt_monitor.ring_buffer.fetch_all()),
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
        while True:
            if await asyncio.to_thread(mqtt_monitor.ring_buffer.wait, 5):
                yield ft.sse_message("new msg", event="new_message")

    return StreamingResponse(notify(), media_type="text/event-stream")


@app.get("/fetch-messages")
def fetch_messages(current_id: int) -> list[ft.FT]:
    return gen_message_ui(mqtt_monitor.ring_buffer.fetch_new(current_id))


if __name__ == "__main__":
    ft.serve(reload=False)
