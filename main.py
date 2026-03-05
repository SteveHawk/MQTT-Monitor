import asyncio
import contextlib
from typing import AsyncGenerator

import fasthtml.common as ft
from fasthtml.common import Article, Div, P, Script, Titled
from sse_starlette import EventSourceResponse, ServerSentEvent
from starlette.applications import Starlette

from mqtt_monitor import Message, MQTTMonitor, NodeDB

mqtt_monitor = MQTTMonitor()


@contextlib.asynccontextmanager
async def mqttc_lifespan(app: Starlette) -> AsyncGenerator[None, None]:
    """Lifespan handler, run mqtt_monitor thread here seperately."""
    with mqtt_monitor:
        yield


app, rt = ft.fast_app(
    lifespan=mqttc_lifespan,
    hdrs=(
        Script(src="https://unpkg.com/htmx-ext-sse@2.2.1/sse.js"),  # SSE extension
        Script(
            # Script for calculating current_id to avoid missing messages
            'function getMsgId() { var msgs = [...document.querySelectorAll("#messages [id]")];'
            'return msgs.length === 0 ? 0 : msgs.pop().id.split("_")[1]; }'
        ),
    ),
)


def gen_message_ui(messages: list[Message]) -> list[ft.FT]:
    """Generate message list UI."""
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
    """Main page."""
    return Titled(
        "Meshtastic MQTT Monitor",
        Div(
            Div(
                *gen_message_ui(mqtt_monitor.ring_buffer.fetch_all()),
                id="messages",
                hx_get="/fetch-messages",  # fetch new message
                hx_trigger="sse:new_message",  # trigger fetch new message
                hx_vals="js:{current_id: getMsgId()}",  # calculate current_id to avoid missing messages
                hx_swap="beforeend show:bottom",
            ),
            hx_ext="sse",
            sse_connect="/sse-new-msg",  # SSE endpoint
            hx_swap="beforeend show:bottom",
            sse_swap="sse_close_msg",  # server shutdown display
            sse_close="sse_close",  # shutdown SSE connection
        ),
    )


@app.get("/sse-new-msg")
async def new_message() -> EventSourceResponse:
    """SSE endpoint for incoming new message notification."""
    shutdown_event = asyncio.Event()

    async def notify() -> AsyncGenerator[ServerSentEvent, None]:
        while not shutdown_event.is_set():
            if await asyncio.to_thread(mqtt_monitor.ring_buffer.wait, 5):
                yield ServerSentEvent("new msg", event="new_message")

        yield ServerSentEvent(P("Server shutdown."), event="sse_close_msg")
        yield ServerSentEvent("sse close", event="sse_close")

    return EventSourceResponse(
        notify(),
        shutdown_event=shutdown_event,  # type: ignore
        shutdown_grace_period=10,
    )


@app.get("/fetch-messages")
def fetch_messages(current_id: int) -> list[ft.FT]:
    """Endpoint for fetching latest messages."""
    return gen_message_ui(mqtt_monitor.ring_buffer.fetch_new(current_id))


if __name__ == "__main__":
    ft.serve(reload=False)
