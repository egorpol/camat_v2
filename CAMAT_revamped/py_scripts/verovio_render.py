from __future__ import annotations

import io
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

try:  # pragma: no cover - optional in some environments
    import verovio  # type: ignore
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "The 'verovio' package is required for score rendering. Install it with 'pip install verovio'."
    ) from exc


__all__ = [
    "get_toolkit",
    "vrv_set_options",
    "vrv_guess_input_from",
    "vrv_load_data",
    "vrv_load_from_file",
    "vrv_load_from_url",
    "vrv_render_page",
    "vrv_render_all_pages",
    "vrv_display_svg",
    "vrv_find_elements_at_time",
    "vrv_timemap",
]


_VRV_TOOLKIT = verovio.toolkit()


def get_toolkit():
    return _VRV_TOOLKIT


def _ensure_svg(svg: Any) -> str:
    if svg is None:
        return ""
    if isinstance(svg, bytes):
        return svg.decode("utf-8", errors="ignore")
    return str(svg)


def vrv_set_options(**kwargs: Any) -> None:
    """
    Set Verovio options with sensible defaults for notebook viewing.
    Users may override any defaults with kwargs.
    """
    defaults: Dict[str, Any] = {
        "pageWidth": 8000,
        "pageHeight": 1000,
        "scale": 50,
        "breaks": "none",
        "svgBoundingBoxes": True,
        "adjustPageHeight": True,
    }
    opts = {**defaults, **kwargs}
    _VRV_TOOLKIT.setOptions(opts)


def vrv_guess_input_from(source_hint: Optional[str] = None, content: Optional[str] = None) -> Optional[str]:
    """
    Guess Verovio's inputFrom option (one of 'mei', 'musicxml', 'humdrum').

    Uses file extension from source_hint (URL or path) or lightweight content sniffing.
    Returns None when unknown.
    """
    # 1) Extension-based
    if source_hint:
        path = source_hint.split("?")[0].split("#")[0]
        _, ext = os.path.splitext(path.lower())
        if ext in {".mei"}:
            return "mei"
        if ext in {".xml", ".musicxml", ".mxl"}:
            return "musicxml"
        if ext in {".krn", ".kern", ".hum"}:
            return "humdrum"

    # 2) Content-based
    if content:
        head = content.lstrip()[:4096].lower()
        # Basic XML sniffing
        if head.startswith("<"):
            # MEI
            if "<mei" in head or "xmlns:mei" in head or "http://www.music-encoding.org" in head:
                return "mei"
            # MusicXML roots
            if "<score-partwise" in head or "<score-timewise" in head or "<!doctype score-partwise" in head:
                return "musicxml"
            # Generic XML fallback → prefer musicxml
            return "musicxml"
        # Humdrum heuristics
        if "**kern" in head or re.search(r"\n\*\*kern(\t|\n|\r)", head):
            return "humdrum"
        if head.startswith("!!") or head.startswith("!!humdrum") or "\t" in head:
            # Many humdrum files are tab-separated with global comments (!!)
            return "humdrum"

    return None


def vrv_load_data(data: str, *, input_from: Optional[str] = None) -> int:
    """
    Load a score string into Verovio. Returns page count.
    Set input_from to one of {'mei', 'musicxml', 'humdrum'}; if None, attempts to guess from content.
    """
    inferred = input_from or vrv_guess_input_from(None, data) or "musicxml"
    _VRV_TOOLKIT.setOptions({"inputFrom": inferred})
    _VRV_TOOLKIT.loadData(data)
    return _VRV_TOOLKIT.getPageCount()


def vrv_load_from_file(path: str, *, input_from: Optional[str] = None, encoding: str = "utf-8") -> int:
    with io.open(path, "r", encoding=encoding, errors="ignore") as f:
        data = f.read()
    inferred = input_from or vrv_guess_input_from(path, data)
    return vrv_load_data(data, input_from=inferred)


def vrv_load_from_url(url: str, *, input_from: Optional[str] = None, timeout: int = 30) -> int:
    """
    Load MEI/MusicXML/Humdrum from URL, auto-detecting inputFrom when not provided.
    Returns page count.
    """
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    # Prefer text; fall back to bytes decode
    try:
        data = resp.text
        if not data or data == "" and resp.content:
            data = resp.content.decode("utf-8", errors="ignore")
    except Exception:
        data = resp.content.decode("utf-8", errors="ignore")
    inferred = input_from or vrv_guess_input_from(url, data)
    return vrv_load_data(data, input_from=inferred)


def vrv_render_page(page: int) -> str:
    svg = _VRV_TOOLKIT.renderToSVG(page)
    return _ensure_svg(svg)


def vrv_render_all_pages() -> List[str]:
    pages = _VRV_TOOLKIT.getPageCount()
    return [vrv_render_page(p) for p in range(1, pages + 1)]


def vrv_display_svg(svg: str) -> None:
    try:
        from IPython.display import SVG, display  # type: ignore
        display(SVG(_ensure_svg(svg)))
    except Exception:
        # Silent no-op outside notebooks
        pass


def vrv_find_elements_at_time(ms: float):
    return _VRV_TOOLKIT.getElementsAtTime(ms) if hasattr(_VRV_TOOLKIT, "getElementsAtTime") else None


def vrv_timemap():
    if hasattr(_VRV_TOOLKIT, "renderToTimemap"):
        tm = _VRV_TOOLKIT.renderToTimemap()
        try:
            import json as _json  # type: ignore
            return _json.loads(tm) if isinstance(tm, str) else tm
        except Exception:
            return tm
    return None


