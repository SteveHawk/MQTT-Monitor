import asyncio
import contextlib
from typing import AsyncGenerator

import fasthtml.common as ft
from fasthtml.common import (
    H1,
    Article,
    Button,
    Code,
    Div,
    Footer,
    Link,
    Main,
    P,
    Script,
    Small,
    Title,
)
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
            'return msgs.length === 0 ? 0 : msgs[0].id.split("_")[1]; }'
            'function manualRefresh() { htmx.trigger("#messages", "manual_refresh", {}) }'
            'function jumpToLastMsg() { document.querySelector("#message_" + getMsgId()).scrollIntoView(); }'
        ),
        Link(rel="stylesheet", href="style.css", type="text/css"),
    ),
)


def gen_message_ui(messages: list[Message]) -> list[ft.FT]:
    """Generate message list UI."""
    ui = list[ft.FT]()
    for message in messages:
        user = NodeDB[message.message["from"]]
        msg_ui = Div(
            Div(Small(user["short_name"]), cls="msg-avatar"),
            Article(str(message), id=f"message_{message.id}", cls="msg-bubble"),
            cls="msg-div",
        )
        ui.append(msg_ui)
    return ui[::-1]


@app.get("/")
def home() -> tuple[ft.FT, ...]:
    """Main page."""
    return (
        Title(title := "Meshtastic MQTT Monitor"),
        Main(
            Div(
                H1(title),
                Small(
                    "Server:",
                    Code(mqtt_monitor.settings.address),
                    " Topic:",
                    Code(mqtt_monitor.settings.root_topic),
                    " Channel:",
                    Code(mqtt_monitor.settings.channel),
                ),
                cls="title",
            ),
            Div(
                Div(
                    *gen_message_ui(mqtt_monitor.ring_buffer.fetch_all()),
                    id="messages",
                    cls="messages",
                    hx_get="/fetch-messages",  # fetch new message
                    hx_trigger="sse:new_message, manual_refresh",  # trigger fetch new message
                    hx_vals="js:{current_id: getMsgId()}",  # calculate current_id to avoid missing messages
                    hx_target="this",
                    hx_swap="afterbegin show:bottom",
                ),
                Footer(
                    Button("Refresh", hx_on_click="manualRefresh()"),
                    Button("Scroll To Bottom", hx_on_click="jumpToLastMsg()"),
                ),
                cls="messages-outer",
                hx_ext="sse",
                sse_connect="/sse-new-msg",  # SSE endpoint
                hx_target="footer",
                hx_swap="beforeend",
                sse_swap="sse_close_msg",  # server shutdown display
                sse_close="sse_close",  # shutdown SSE connection
            ),
            cls="container",  # pico css centered viewport
        ),
    )


@app.get("/sse-new-msg")
async def new_message() -> EventSourceResponse:
    """SSE endpoint for incoming new message notification."""
    shutdown_event = asyncio.Event()
    shutdown_elm = Div(
        P("Server shutdown, refresh page to reconnect"), cls="shutdown-sign"
    )

    async def notify() -> AsyncGenerator[ServerSentEvent, None]:
        while not shutdown_event.is_set():
            if await asyncio.to_thread(mqtt_monitor.ring_buffer.wait, 5):
                yield ServerSentEvent("new msg", event="new_message")

        yield ServerSentEvent(shutdown_elm, event="sse_close_msg")
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
