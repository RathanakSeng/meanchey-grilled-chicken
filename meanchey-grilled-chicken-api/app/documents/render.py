"""Delivery note → PDF with WeasyPrint, on an 80 mm receipt page as tall as its content.

- **Template:** `templates/delivery_note.html.j2` + `templates/receipt.css` (Jinja2, autoescaped).
- **Font:** Kantumruy Pro (Regular / Bold static instances, SIL OFL) bundled in `fonts/`, loaded
  with `@font-face`, so Khmer is shaped by HarfBuzz the same everywhere; nothing is fetched.
- **Height fits the content (two passes):** render once on a very tall page, find the bottom of
  the last element (`#end`), render again with `@page { size: 80mm <that>mm }`. A receipt longer
  than the first page (absurdly long orders) keeps the tall pages.
- **Off the event loop:** WeasyPrint is CPU-bound, so `render_pdf` runs in a worker thread
  (`anyio.to_thread`, at most `MAX_PARALLEL` at once) with a timeout → `503 DOCUMENT_UNAVAILABLE`.
  Also when WeasyPrint's system libraries (Pango) are missing, e.g. on a plain Windows machine.
- WeasyPrint is imported lazily, so the API starts without it.
"""

import logging
from functools import cache
from pathlib import Path
from typing import Any

import anyio
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.errors import AppError, ErrorCode

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = BASE_DIR / "templates"
PAGE_WIDTH_MM = 80
MARGIN_MM = 3
# The first pass's page: taller than any realistic receipt.
PROBE_HEIGHT_MM = 3000
MIN_HEIGHT_MM = 60
TIMEOUT_SECONDS = 20
MAX_PARALLEL = 2
_PX_PER_MM = 96 / 25.4

_limiter = anyio.CapacityLimiter(MAX_PARALLEL)
_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def unavailable_reason() -> str | None:
    """None when WeasyPrint can render here; otherwise why not (missing system libraries)."""
    try:
        _weasyprint()
    except (ImportError, OSError) as e:
        return str(e).splitlines()[0] if str(e) else type(e).__name__
    return None


@cache
def _weasyprint() -> Any:
    import weasyprint

    return weasyprint


def render_html(context: dict[str, Any]) -> str:
    return _env.get_template("delivery_note.html.j2").render(**context)


def _page_css(height_mm: float) -> str:
    return f"@page {{ size: {PAGE_WIDTH_MM}mm {height_mm:.2f}mm; margin: {MARGIN_MM}mm; }}"


def _content_bottom_px(document: Any) -> float | None:
    """y of the bottom of `#end` on the first page (CSS px), or None if it's not there."""
    page = document.pages[0]
    stack = [page._page_box]
    while stack:
        box = stack.pop()
        element = getattr(box, "element", None)
        if element is not None and element.get("id") == "end":
            return box.position_y + box.margin_height()
        stack.extend(getattr(box, "children", ()))
    return None


def _render_sync(html: str) -> bytes:
    wp = _weasyprint()
    from weasyprint.text.fonts import FontConfiguration

    fonts = FontConfiguration()
    source = wp.HTML(string=html, base_url=str(TEMPLATES))
    css = wp.CSS(filename=str(TEMPLATES / "receipt.css"), font_config=fonts)

    def render(height_mm: float) -> Any:
        page = wp.CSS(string=_page_css(height_mm), font_config=fonts)
        return source.render(stylesheets=[css, page], font_config=fonts)

    probe = render(PROBE_HEIGHT_MM)
    bottom = _content_bottom_px(probe) if len(probe.pages) == 1 else None
    if bottom is None:
        return probe.write_pdf()
    height = max(MIN_HEIGHT_MM, bottom / _PX_PER_MM + MARGIN_MM + 2)
    return render(height).write_pdf()


async def render_pdf(context: dict[str, Any]) -> bytes:
    """The PDF for `context` (see delivery_note.build_context). 503 DOCUMENT_UNAVAILABLE when
    WeasyPrint can't run here or takes longer than TIMEOUT_SECONDS."""
    reason = unavailable_reason()
    if reason is not None:
        log.error("Delivery note rendering unavailable: %s", reason)
        raise AppError(503, ErrorCode.DOCUMENT_UNAVAILABLE, "Documents can't be created right now")
    html = render_html(context)
    try:
        with anyio.fail_after(TIMEOUT_SECONDS):
            return await anyio.to_thread.run_sync(
                _render_sync, html, limiter=_limiter, abandon_on_cancel=True
            )
    except TimeoutError as e:
        log.error("Delivery note rendering took longer than %ss", TIMEOUT_SECONDS)
        raise AppError(
            503, ErrorCode.DOCUMENT_UNAVAILABLE, "Documents can't be created right now"
        ) from e
