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
    "vrv_get_mei",
    "vrv_set_mei",
    "vrv_insert_annot",
    "vrv_has_mei_export",
    "vrv_set_additional_css",
    "vrv_highlight_ids",
    "vrv_debug_info",
]


_VRV_TOOLKIT = verovio.toolkit()
_EXTRA_SVG_CSS = ""


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


def vrv_get_mei() -> str:
    """
    Return the current score as MEI XML.
    """
    mei = _VRV_TOOLKIT.getMEI()
    if mei is None:
        raise RuntimeError(
            "Verovio returned no MEI. Make sure a score is loaded first."
        )
    if isinstance(mei, bytes):
        try:
            mei = mei.decode("utf-8", errors="ignore")
        except Exception:
            mei = mei.decode(errors="ignore")  # best-effort
    mei_str = str(mei)
    if not mei_str.strip():
        raise RuntimeError(
            "Verovio returned an empty MEI string. Ensure a document is loaded "
            "and that your Verovio build supports getMEI()."
        )
    return mei_str


def vrv_set_mei(mei_xml: str) -> int:
    """
    Replace the current score with the provided MEI XML. Returns page count.
    """
    _VRV_TOOLKIT.setOptions({"inputFrom": "mei"})
    _VRV_TOOLKIT.loadData(mei_xml)
    pages = _VRV_TOOLKIT.getPageCount()
    if pages <= 0:
        log_msg = ""
        if hasattr(_VRV_TOOLKIT, "getLog"):
            try:
                log_msg = _VRV_TOOLKIT.getLog() or ""
            except Exception:
                log_msg = ""
        raise RuntimeError(
            f"Verovio failed to load the modified MEI (pageCount={pages}). {('Log: ' + log_msg) if log_msg else ''}"
        )
    return pages


def vrv_insert_annot(
    text: Optional[str] = None,
    *,
    type: Optional[str] = None,
    staff: Optional[str] = None,
    layer: Optional[str] = None,
    tstamp: Optional[str] = None,
    tstamp2: Optional[str] = None,
    startid: Optional[str] = None,
    endid: Optional[str] = None,
    plist: Optional[List[str]] = None,
    color: Optional[str] = None,
    place: Optional[str] = None,
    xml_id: Optional[str] = None,
    parent_xpath: Optional[str] = None,
    measure_index: Optional[int] = None,
    reload_score: bool = True,
) -> str:
    """
    Inject an <annot> element into the current MEI and optionally reload it.

    Parameters:
        text: Text content of the annot (optional).
        type, staff, layer, tstamp, tstamp2, startid, endid, color, place: Common MEI @annot attributes.
        plist: List of XML ID pointers (e.g., ['#n1', '#n2']); joined as a space-separated @plist.
        xml_id: Value for xml:id. If omitted, one is auto-generated.
        parent_xpath: XPath (with 'mei' prefix) to choose insertion node (e.g., ".//mei:measure[@n='4']").
        reload_score: If True, reloads the modified MEI into Verovio.

    Returns:
        The modified MEI XML as a string.
    """
    mei_xml = vrv_get_mei()

    try:
        from xml.etree import ElementTree as ET  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("xml.etree.ElementTree is required to manipulate MEI XML") from exc

    ns_mei = "http://www.music-encoding.org/ns/mei"
    ns_xml = "http://www.w3.org/XML/1998/namespace"
    ns = {"mei": ns_mei}

    # Preserve namespace prefixes on serialization (avoid ns0:mei, etc.)
    try:
        ET.register_namespace("", ns_mei)
        ET.register_namespace("xml", ns_xml)
    except Exception:
        pass

    root = ET.fromstring(mei_xml)

    def _make_annot() -> "ET.Element":
        a = ET.Element(f"{{{ns_mei}}}annot")
        if xml_id:
            a.set(f"{{{ns_xml}}}id", xml_id)
        if type:
            a.set("type", type)
        if staff:
            a.set("staff", str(staff))
        if layer:
            a.set("layer", str(layer))
        if tstamp:
            a.set("tstamp", str(tstamp))
        if tstamp2:
            a.set("tstamp2", str(tstamp2))
        if startid:
            a.set("startid", str(startid))
        if endid:
            a.set("endid", str(endid))
        if plist:
            a.set("plist", " ".join(plist) if isinstance(plist, list) else str(plist))
        if color:
            a.set("color", str(color))
        if place:
            a.set("place", str(place))
        if text:
            a.text = text
        return a

    # Determine candidate parents (try multiple locations robustly)
    candidate_xpaths: List[str] = []
    if parent_xpath:
        candidate_xpaths = [parent_xpath]
    else:
        # If a specific measure index is requested, we will handle it separately below.
        # Otherwise, prefer section for general and time-anchored annot; measure as fallback.
        candidate_xpaths = [".//mei:section", ".//mei:measure"]

    last_error: Optional[Exception] = None
    original_mei = ET.tostring(root, encoding="unicode")

    # Try measure by index first if requested
    if measure_index is not None and measure_index >= 1:
        try:
            attempt_root = ET.fromstring(original_mei)
            measures = attempt_root.findall(".//mei:measure", ns)
            if measures and len(measures) >= measure_index:
                parent_node = measures[measure_index - 1]
                parent_node.append(_make_annot())
                new_mei = ET.tostring(attempt_root, encoding="unicode")
                if reload_score:
                    vrv_set_mei(new_mei)
                return new_mei
        except Exception as exc:
            last_error = exc
            # fall through to other candidates
    for xpath in candidate_xpaths:
        try:
            # Work on a fresh tree each attempt to avoid accumulating nodes
            attempt_root = ET.fromstring(original_mei)
            parent_node = attempt_root.find(xpath, ns)
            if parent_node is None:
                continue
            parent_node.append(_make_annot())
            new_mei = ET.tostring(attempt_root, encoding="unicode")
            if reload_score:
                vrv_set_mei(new_mei)
            return new_mei
        except Exception as exc:
            last_error = exc
            continue

    # As absolute last resort, append to root and try
    try:
        attempt_root = ET.fromstring(original_mei)
        attempt_root.append(_make_annot())
        new_mei = ET.tostring(attempt_root, encoding="unicode")
        if reload_score:
            vrv_set_mei(new_mei)
        return new_mei
    except Exception as exc:
        last_error = exc
        raise RuntimeError(
            f"Failed to insert <annot> in any candidate parent. Last error: {last_error}"
        )


def vrv_has_mei_export() -> bool:
    """
    Return True if getMEI() returns a non-empty string for the current document.
    """
    try:
        mei = _VRV_TOOLKIT.getMEI()
        if mei is None:
            return False
        if isinstance(mei, bytes):
            mei = mei.decode("utf-8", errors="ignore")
        return bool(str(mei).strip())
    except Exception:
        return False


def vrv_set_additional_css(css: str, *, append: bool = True) -> None:
    """
    Set or append CSS to be embedded in rendered SVGs via svgAdditionalCSS.
    """
    global _EXTRA_SVG_CSS
    if append and _EXTRA_SVG_CSS:
        _EXTRA_SVG_CSS = f"{_EXTRA_SVG_CSS}\n{css}"
    else:
        _EXTRA_SVG_CSS = css
    _VRV_TOOLKIT.setOptions({"svgAdditionalCSS": _EXTRA_SVG_CSS})


def vrv_highlight_ids(ids: List[str], color: str = "#ff0") -> None:
    """
    Highlight one or more SVG/MEI ids using CSS as a fallback when MEI export
    is not available. Call render again after this to see the effect.
    """
    if not ids:
        return
    # Each id should include the leading '#'
    selectors: List[str] = []
    for pid in ids:
        pid = pid if pid.startswith("#") else f"#{pid}"
        # Target group and its children
        selectors.append(f"g{pid}")
        selectors.append(f"g{pid} *")
    selector = ", ".join(selectors)
    css = f"{selector} {{ fill: {color} !important; stroke: {color} !important; }}"
    vrv_set_additional_css(css, append=True)


def vrv_debug_info() -> Dict[str, Any]:
    """
    Return a dictionary with quick diagnostics about the current Verovio state.
    """
    info: Dict[str, Any] = {}
    tk = _VRV_TOOLKIT
    try:
        import verovio as _verovio  # type: ignore
        info["verovio_package_file"] = getattr(_verovio, "__file__", None)
    except Exception:
        info["verovio_package_file"] = None
    try:
        info["version"] = tk.getVersion()
    except Exception:
        info["version"] = None
    try:
        info["pages"] = tk.getPageCount()
    except Exception:
        info["pages"] = None
    try:
        opts = tk.getOptions() if hasattr(tk, "getOptions") else None
        info["options_raw"] = opts
    except Exception:
        info["options_raw"] = None
    try:
        mei = tk.getMEI() if hasattr(tk, "getMEI") else None
        mei_len = len(mei) if isinstance(mei, (str, bytes)) else None
        info["has_getMEI"] = hasattr(tk, "getMEI")
        info["mei_length"] = mei_len
    except Exception as exc:
        info["has_getMEI"] = hasattr(tk, "getMEI")
        info["mei_length"] = f"error: {exc}"
    try:
        svg = tk.renderToSVG(1)
        svg_txt = _ensure_svg(svg)
        info["svg_len"] = len(svg_txt)
        info["svg_head"] = svg_txt[:200]
    except Exception:
        info["svg_len"] = None
        info["svg_head"] = None
    try:
        info["log"] = tk.getLog() if hasattr(tk, "getLog") else ""
    except Exception:
        info["log"] = ""
    return info

