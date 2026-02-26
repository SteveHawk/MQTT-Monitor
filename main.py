import contextlib
from typing import AsyncGenerator

from fasthtml.common import FT, A, Body, Div, FastHTML, Head, Html, Img, Title, serve
from starlette.applications import Starlette

from mqtt_monitor import MQTTMonitor


@contextlib.asynccontextmanager
async def mqttc_lifespan(app: Starlette) -> AsyncGenerator[None, None]:
    print("Run at startup!")
    with MQTTMonitor():
        yield
    print("Run on shutdown!")


app = FastHTML(lifespan=mqttc_lifespan)


@app.get("/")  # type: ignore
def home() -> FT:
    page = Html(
        Head(Title("Some page")),
        Body(
            Div(
                "Some text, ",
                A("A link", href="https://example.com"),
                Img(src="https://placehold.co/200"),
                cls="myclass",
            )
        ),
    )
    return page


if __name__ == "__main__":
    serve()
