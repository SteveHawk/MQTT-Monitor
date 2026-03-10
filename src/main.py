import asyncio
import contextlib
from datetime import datetime
from typing import AsyncGenerator

import fasthtml.common as ft
from fasthtml.common import (
    H1,
    Article,
    Button,
    Code,
    Div,
    Footer,
    Header,
    Link,
    Main,
    Mark,
    P,
    Script,
    Small,
    Title,
)
from sse_starlette import EventSourceResponse, ServerSentEvent
from starlette.applications import Starlette

from mqtt_monitor import MQTTMonitor
from packet_store import NodeDB, Packet

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
        Script(src="src/script.js"),
        Link(rel="stylesheet", href="src/style.css", type="text/css"),
    ),
)


def gen_message_ui(packets: list[Packet], text_only: bool) -> list[ft.FT]:
    """Generate message list UI."""
    ui = list[ft.FT]()
    for pkt in packets:
        dt = datetime.fromtimestamp(pkt.timestamp)
        if (text_only and pkt.msg_new_day) or (not text_only and pkt.pkt_new_day):
            ui.append(Div(Code(dt.strftime("%Y-%m-%d")), cls="date-bubble"))

        if text_only and (not pkt.is_text):
            continue

        user = NodeDB[pkt.packet["from"]]
        timestamp = Small(dt.strftime("%m-%d %H:%M:%S"), cls="bubble-date")

        if text_only:
            msg_ui = Div(
                Div(Small(user["short_name"]), cls="msg-avatar"),
                Div(
                    Small(f"{user['long_name']}"),
                    Article(
                        str(pkt.payload),
                        timestamp,
                        id=f"message_{pkt.msg_id}",
                        cls="msg-bubble",
                    ),
                ),
                cls="msg-div",
            )
        else:
            uer_to = NodeDB[pkt.packet["to"]]
            msg_ui = Div(
                Div(
                    Mark(Small(user["short_name"]), cls="pkt-avatar"),
                    Small(f"{user['long_name']} -> {uer_to['long_name']}"),
                ),
                Code(str(pkt), timestamp, id=f"packet_{pkt.pkt_id}"),
                cls="pkt-div",
            )
        ui.append(msg_ui)

    return ui[::-1]


@app.get("/")
def home() -> tuple[ft.FT, ...]:
    """Main page."""
    return (
        Title(title := "Meshtastic MQTT Monitor"),
        Main(
            Header(
                H1(title),
                Small(
                    "Server:",
                    Code(mqtt_monitor.settings.address),
                    " Topic:",
                    Code(mqtt_monitor.settings.root_topic),
                    " Channel:",
                    Code(mqtt_monitor.settings.channel),
                ),
            ),
            Div(
                Button(
                    "Messages", cls="tab-button", hx_on_click='selectTab("messages")'
                ),
                Button(
                    "Raw Packets",
                    cls="tab-button outline secondary",
                    hx_on_click='selectTab("packets")',
                ),
                role="group",
                cls="tab-switcher",
            ),
            Div(
                Div(
                    # Messages UI
                    *gen_message_ui(mqtt_monitor.packet_store.fetch_all(True), True),
                    id="messages",
                    cls="messages",
                    hx_get="/fetch-messages",  # fetch new message
                    hx_trigger="sse:new_message, manual_refresh",  # trigger fetch new message
                    hx_vals="js:{current_id: getMsgId(), text_only: true}",  # calculate current_id to avoid missing messages
                    hx_target="this",
                    hx_swap="afterbegin show:bottom",
                ),
                Div(
                    # Packets UI
                    *gen_message_ui(mqtt_monitor.packet_store.fetch_all(False), False),
                    id="packets",
                    cls="messages",
                    hx_get="/fetch-messages",  # fetch new message
                    hx_trigger="sse:new_packet, manual_refresh",  # trigger fetch new packets
                    hx_vals="js:{current_id: getMsgId(), text_only: false}",  # calculate current_id to avoid missing messages
                    hx_target="this",
                    hx_swap="afterbegin show:bottom",
                    hidden=True,
                ),
                cls="messages-outer",
                hx_ext="sse",
                sse_connect="/sse-new-msg",  # SSE endpoint
                hx_target="footer",
                hx_swap="beforeend",
                sse_swap="sse_close_msg",  # server shutdown display
                sse_close="sse_close",  # shutdown SSE connection
            ),
            Footer(
                Button("Refresh", hx_on_click="manualRefresh()"),
                Button("Scroll To Bottom", hx_on_click="jumpToLastMsg()"),
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
            if await asyncio.to_thread(mqtt_monitor.packet_store.wait, 5, False):
                if msg := mqtt_monitor.packet_store.fetch_latest(False):
                    if msg.is_text:
                        yield ServerSentEvent("new msg", event="new_message")
                    yield ServerSentEvent("new msg", event="new_packet")

        yield ServerSentEvent(shutdown_elm, event="sse_close_msg")
        yield ServerSentEvent("sse close", event="sse_close")

    return EventSourceResponse(
        notify(),
        shutdown_event=shutdown_event,  # type: ignore
        shutdown_grace_period=10,
    )


@app.get("/fetch-messages")
def fetch_messages(current_id: int, text_only: bool) -> list[ft.FT]:
    """Endpoint for fetching latest messages."""
    return gen_message_ui(
        mqtt_monitor.packet_store.fetch_new(current_id, text_only), text_only
    )


if __name__ == "__main__":
    ft.serve(reload=False)
