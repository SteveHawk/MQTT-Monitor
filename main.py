from fasthtml.common import FT, A, Body, Div, FastHTML, Head, Html, Img, Title, serve

app = FastHTML()


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
