from pathlib import Path

from fastapi.responses import HTMLResponse

_HTML_PATH = Path(__file__).parent / "static" / "index.html"


def get_index_html() -> str:
    return _HTML_PATH.read_text(encoding="utf-8")


def index_response() -> HTMLResponse:
    return HTMLResponse(content=get_index_html())
