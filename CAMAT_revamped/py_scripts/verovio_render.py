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
    "vrv_process_annotations",
]


_VRV_TOOLKIT = verovio.toolkit()
_EXTRA_SVG_CSS = ""

# Common namespaces
MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def vrv_namespaces() -> Dict[str, str]:
    """
    Return a namespace prefix map suitable for ElementTree XPath queries.
    Keys: 'mei', 'xml'.
    """
    return {"mei": MEI_NS, "xml": XML_NS}


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

    # If an <annot> with this xml:id already exists, update it in place instead of
    # appending a duplicate. This makes repeated vrv_insert_annot calls idempotent
    # for a given xml_id and prevents multiple identical plist annotations.
    if xml_id:
        existing_annot = None
        for a in root.findall(".//mei:annot", ns):
            if a.get(f"{{{ns_xml}}}id") == xml_id:
                existing_annot = a
                break
        if existing_annot is not None:
            updated = _make_annot()
            existing_annot.attrib.clear()
            existing_annot.attrib.update(updated.attrib)
            existing_annot.text = updated.text
            new_mei = ET.tostring(root, encoding="unicode")
            if reload_score:
                vrv_set_mei(new_mei)
            return new_mei

    def _score_root(tree: "ET.Element") -> "ET.Element":
        """
        Return the <music> subtree when present, otherwise the original tree.
        Some MEI files embed an incipit outside of <music>; we want annotation
        insertions to target the rendered score rather than front matter.
        """
        music_node = tree.find(".//mei:music", ns)
        if music_node is not None:
            return music_node
        body_node = tree.find(".//mei:body", ns)
        if body_node is not None:
            return body_node
        return tree

    def _find_in_score(tree: "ET.Element", xpath: str):
        score = _score_root(tree)
        node = score.find(xpath, ns)
        if node is not None:
            return node
        # Fallback to whole tree so existing absolute XPaths keep working
        return tree.find(xpath, ns)

    def _findall_in_score(tree: "ET.Element", xpath: str) -> List["ET.Element"]:
        score = _score_root(tree)
        matches = score.findall(xpath, ns)
        if matches:
            return matches
        return tree.findall(xpath, ns)

    # Determine candidate parents (try multiple locations robustly)
    candidate_xpaths: List[str] = []
    if parent_xpath:
        candidate_xpaths = [parent_xpath]
    else:
        # If a specific measure index is requested, we will handle it separately below.
        # Otherwise, prefer section for general and time-anchored annot; measure as fallback.
        candidate_xpaths = [
            ".//mei:section",
            ".//mei:measure",
        ]

    last_error: Optional[Exception] = None
    original_mei = ET.tostring(root, encoding="unicode")

    # Try measure by index first if requested
    if measure_index is not None and measure_index >= 1:
        try:
            attempt_root = ET.fromstring(original_mei)
            measures = _findall_in_score(attempt_root, ".//mei:measure")
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
            parent_node = _find_in_score(attempt_root, xpath)
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


def vrv_highlight_ids(
    ids: List[str],
    color: str = "#ff0",
    *,
    shape_only: bool = False,
    include_rects: bool = False,
) -> None:
    """
    Highlight one or more SVG/MEI ids using CSS as a fallback when MEI export
    is not available. Call render again after this to see the effect.
    """
    if not ids:
        return
    # Each id should include the leading '#'
    selectors: List[str] = []
    if shape_only:
        # Target only note glyph shapes, not text/lyrics; include direct-id shapes and descendants.
        shape_tags = ["path", "polygon", "ellipse", "circle", "line", "use"]
        if include_rects:
            shape_tags.append("rect")
        for pid in ids:
            pid = pid if pid.startswith("#") else f"#{pid}"
            core = pid.lstrip("#")
            # Direct id on shape elements
            for tag in shape_tags:
                selectors.append(f"{tag}#{core}")
            # Descendants inside the element/group with this id
            for tag in shape_tags:
                selectors.append(f"{pid} {tag}")
    else:
        # Broad highlight but still avoid bbox rectangles by default.
        shape_tags = ["path", "polygon", "ellipse", "circle", "line", "use"]
        if include_rects:
            shape_tags.append("rect")
        for pid in ids:
            pid = pid if pid.startswith("#") else f"#{pid}"
            core = pid.lstrip("#")
            # Direct id on shape elements
            for tag in shape_tags:
                selectors.append(f"{tag}#{core}")
            # Descendants inside the element/group with this id, including text if present
            for tag in shape_tags + ["text", "tspan"]:
                selectors.append(f"{pid} {tag}")
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


# ---------- Higher-level helpers for plist annotations + highlighting ----------

def _vrv_find_svg_ids(svg_text: str, mei_id: str, *, include_bbox_ids: bool = False, include_derived_ids: bool = False) -> List[str]:
    """
    Resolve one MEI xml:id pointer (e.g., '#d1e64') to SVG id(s) found in the provided SVG text.

    include_bbox_ids: if True, keep bbox-* matches. Otherwise, skip them.
    include_derived_ids: if True, accept ids that contain the core as a substring (e.g., d1e64-1);
                         otherwise require exact equality with the core id.
    """
    core = mei_id.lstrip("#")
    pat = re.compile(r'id="([^"]*%s[^"]*)"' % re.escape(core))
    raw_hits = pat.findall(svg_text)
    hits: List[str] = []
    for h in raw_hits:
        if not include_bbox_ids and h.startswith("bbox-"):
            continue
        if not include_derived_ids and h != core:
            continue
        hits.append(h)
    return hits


def _vrv_resolve_svg_ids(mei_ids: List[str], *, page: int = 1, include_bbox_ids: bool = False, include_derived_ids: bool = False) -> Dict[str, List[str]]:
    """
    Render a page and find corresponding SVG ids for each MEI id pointer (e.g., '#d1e64').
    Returns a dict: {mei_pointer: [svg_ids...]}
    """
    svg = vrv_render_page(page) if page else vrv_render_page(1)
    resolved: Dict[str, List[str]] = {}
    for target in mei_ids:
        resolved[target] = _vrv_find_svg_ids(svg, target, include_bbox_ids=include_bbox_ids, include_derived_ids=include_derived_ids)
    return resolved


def vrv_inject_highlight_css(svg_text: str, ids: List[str], *, color: str = "#ff0", shape_only: bool = True, include_rects: bool = False) -> str:
    """
    Inject an inline <style> block to color-highlight the given ids inside a single SVG string.
    - When shape_only is True, target only shape elements (path/polygon/ellipse/circle/line/use).
      Rectangles are optionally included if include_rects is True.
    - When shape_only is False, target shapes plus text/tspan, still avoiding rects unless include_rects is True.
    """
    shape_tags = ["path", "polygon", "ellipse", "circle", "line", "use"]
    if include_rects:
        shape_tags.append("rect")

    shape_selectors: List[str] = []
    reset_text_selectors: List[str] = []

    for pid in ids:
        bare = pid.lstrip("#")
        if shape_only:
            # Direct id on shapes
            for tag in shape_tags:
                shape_selectors.append(f"{tag}#{bare}")
            # Descendant shapes
            shape_selectors.append(f"#{bare} path")
            shape_selectors.append(f"#{bare} polygon")
            shape_selectors.append(f"#{bare} ellipse")
            shape_selectors.append(f"#{bare} circle")
            shape_selectors.append(f"#{bare} line")
            shape_selectors.append(f"#{bare} use")
            # Be explicit: reset text so it does not inherit color from broad rules
            reset_text_selectors.append(f"#{bare} text")
            reset_text_selectors.append(f"#{bare} tspan")
        else:
            # Broad highlight: shapes and text (avoid rects unless include_rects=True)
            for tag in shape_tags:
                shape_selectors.append(f"{tag}#{bare}")
            shape_selectors.append(f"#{bare} path")
            shape_selectors.append(f"#{bare} polygon")
            shape_selectors.append(f"#{bare} ellipse")
            shape_selectors.append(f"#{bare} circle")
            shape_selectors.append(f"#{bare} line")
            shape_selectors.append(f"#{bare} use")
            shape_selectors.append(f"#{bare} text")
            shape_selectors.append(f"#{bare} tspan")

    if not shape_selectors:
        return svg_text

    style_rules = f"{', '.join(shape_selectors)} {{ fill: {color} !important; stroke: {color} !important; }}"
    style_block = f"<style>{style_rules}</style>"

    if shape_only and reset_text_selectors:
        reset_rules = f"{', '.join(reset_text_selectors)} {{ fill: initial !important; stroke: initial !important; }}"
        style_block += f"<style>{reset_rules}</style>"

    insert_pos = svg_text.find("</defs>")
    if insert_pos != -1:
        insert_pos = insert_pos + len("</defs>")
        return svg_text[:insert_pos] + style_block + svg_text[insert_pos:]
    m = re.search(r"<svg[^>]*>", svg_text)
    if m:
        idx = m.end()
        return svg_text[:idx] + style_block + svg_text[idx:]
    return style_block + svg_text


def vrv_insert_annot_plist(
    *,
    custom_plist: Optional[List[str]] = None,
    plist_annot_config: Optional[List[Dict[str, Any]]] = None,
    plist_annot_text: str = "Plist demo",
    insert_plist_annot: bool = True,
    include_bbox_ids: bool = False,
    include_derived_ids: bool = False,
    shape_only: bool = True,
    highlight_color: str = "#ffcccc",
    include_rects: bool = False,
    pages: Optional[List[int]] = None,
    display: bool = True,
    return_svgs: bool = True,
) -> Optional[List[str]]:
    """
    High-level convenience:
    - Determine target ids (from plist_annot_config or custom_plist or auto).
    - Insert one or multiple clean <annot> plist entries into MEI (idempotent per xml_id).
    - Apply highlight CSS (shape-only or broad) via toolkit (svgAdditionalCSS).
    - Re-render and inject inline CSS for notebook display.

    Returns list of final SVG strings when return_svgs=True; otherwise None.
    """
    # 1) Collect candidate MEI note ids for auto mode
    mei_xml = vrv_get_mei()
    try:
        from xml.etree import ElementTree as _ET  # type: ignore
    except Exception as exc:
        raise RuntimeError("xml.etree.ElementTree is required to analyze MEI XML") from exc

    ns_mei = "http://www.music-encoding.org/ns/mei"
    ns_xml = "http://www.w3.org/XML/1998/namespace"
    ns = {"mei": ns_mei, "xml": ns_xml}

    root = _ET.fromstring(mei_xml)
    notes_with_id = root.findall(".//mei:note[@xml:id]", ns)
    note_ids = [n.attrib.get(f"{{{ns_xml}}}id") for n in notes_with_id]
    auto_plist = [f"#{nid}" for nid in (note_ids or [])[:2] if nid]

    # 2) Determine final set of ids to highlight
    if plist_annot_config:
        all_ids: List[str] = []
        for spec in plist_annot_config:
            plist = spec.get("plist") or []
            all_ids.extend(plist)
        # Deduplicate preserving order
        seen: set[str] = set()
        plist_targets: List[str] = []
        for pid in all_ids:
            if pid not in seen:
                plist_targets.append(pid)
                seen.add(pid)
    else:
        plist_targets = custom_plist or auto_plist

    # 3) Optionally insert annot(s) (idempotent by xml_id)
    if insert_plist_annot:
        if plist_annot_config:
            for spec in plist_annot_config:
                plist = spec.get("plist") or plist_targets
                xml_id = spec.get("xml_id")
                text = spec.get("text")
                vrv_insert_annot(text=text, type="score", plist=plist, xml_id=xml_id)
        else:
            vrv_insert_annot(text=plist_annot_text, type="score", plist=plist_targets, xml_id="plist-demo-1")

    # 4) Map to actual SVG ids (page 1) and build highlight list
    resolved = _vrv_resolve_svg_ids(plist_targets, page=1, include_bbox_ids=include_bbox_ids, include_derived_ids=include_derived_ids)
    highlight_ids: List[str] = []
    for base, hits in resolved.items():
        if hits:
            # Use the exact svg ids we found
            for h in hits:
                highlight_ids.append(h if h.startswith("#") else f"#{h}")
        else:
            # Fall back to base pointer
            highlight_ids.append(base)

    # 5) Apply toolkit CSS (take effect on subsequent renders)
    vrv_highlight_ids(highlight_ids, color=highlight_color, shape_only=shape_only, include_rects=include_rects)

    # 6) Re-render and inject inline CSS for notebook display
    pages_list = pages or list(range(1, get_toolkit().getPageCount() + 1))
    final_svgs: List[str] = []
    for p in pages_list:
        svg = vrv_render_page(p)
        final_svgs.append(vrv_inject_highlight_css(svg, highlight_ids, color=highlight_color, shape_only=shape_only, include_rects=include_rects))

    if display:
        for svg in final_svgs:
            vrv_display_svg(svg)

    return final_svgs if return_svgs else None


def vrv_insert_annots_by_tstamps(
    annots: List[Dict[str, Any]],
    *,
    default_type: Optional[str] = "score",
    default_staff: Optional[str] = None,
    default_layer: Optional[str] = None,
    default_place: Optional[str] = None,
) -> List[Optional[str]]:
    """
    Insert multiple <annot> elements driven by a list of tstamp/tstamp2 specs.

    annots: list of dicts; each can include keys:
        - text, type, staff, layer, tstamp, tstamp2, startid, endid, place, xml_id,
          parent_xpath, measure_index
    Returns a list of xml_id values used (None when not provided).
    """
    xml_ids_used: List[Optional[str]] = []
    for spec in annots:
        text = spec.get("text")
        a_type = spec.get("type", default_type)
        staff = spec.get("staff", default_staff)
        layer = spec.get("layer", default_layer)
        tstamp = spec.get("tstamp")
        tstamp2 = spec.get("tstamp2")
        startid = spec.get("startid")
        endid = spec.get("endid")
        place = spec.get("place", default_place)
        xml_id = spec.get("xml_id")
        parent_xpath = spec.get("parent_xpath")
        measure_index = spec.get("measure_index")
        vrv_insert_annot(
            text=text,
            type=a_type,
            staff=staff,
            layer=layer,
            tstamp=tstamp,
            tstamp2=tstamp2,
            startid=startid,
            endid=endid,
            place=place,
            xml_id=xml_id,
            parent_xpath=parent_xpath,
            measure_index=measure_index,
        )
        xml_ids_used.append(xml_id)
    return xml_ids_used


def vrv_process_annotations(
    annotations: List[Dict[str, Any]],
    *,
    highlight_color: str = "#ffcccc",
    shape_only: bool = True,
    include_rects: bool = False,
    display: bool = True,
    return_svgs: bool = False,
) -> Optional[List[str]]:
    """
    Unified entry point for processing a mix of tstamp and plist annotations.

    annotations: List of annotation dictionaries. Each dict can contain:
        - Standard MEI annot attributes: text, type, staff, layer, tstamp, tstamp2, etc.
        - 'plist': List of XML IDs to link to (for plist annotations).
        - 'xml_id': Optional specific XML ID for the annotation element.
    
    This function will:
    1. Insert all annotations into the MEI.
    2. Collect all 'plist' targets from the annotations.
    3. Highlight the plist targets in the rendered SVG.
    4. Display the result (if display=True).
    """
    # 1. Insert all annotations
    # We track plist targets to highlight them later
    all_plist_targets: List[str] = []

    for annot in annotations:
        # Extract plist if present to track for highlighting
        plist = annot.get("plist")
        if plist:
            if isinstance(plist, list):
                all_plist_targets.extend(plist)
            elif isinstance(plist, str):
                # If it's a string, it might be space-separated or just one id
                all_plist_targets.extend(plist.split())
        
        # Insert the annotation
        vrv_insert_annot(**annot)

    # Deduplicate targets
    unique_targets = list(set(all_plist_targets))

    # 2. & 3. Resolve IDs, Highlight, and Render
    # We can reuse logic similar to vrv_insert_annot_plist but adapted
    
    # Map to actual SVG ids (page 1) - we assume page 1 for resolution for now, 
    # or we could resolve per page if needed, but _vrv_resolve_svg_ids defaults to page 1.
    # For multi-page scores, this might need more robust handling if IDs are on later pages.
    # However, vrv_highlight_ids sets global CSS which applies to all pages.
    
    resolved = _vrv_resolve_svg_ids(unique_targets, page=1, include_bbox_ids=False, include_derived_ids=False)
    highlight_ids: List[str] = []
    for base, hits in resolved.items():
        if hits:
            for h in hits:
                highlight_ids.append(h if h.startswith("#") else f"#{h}")
        else:
            highlight_ids.append(base)

    # Apply toolkit CSS
    vrv_highlight_ids(highlight_ids, color=highlight_color, shape_only=shape_only, include_rects=include_rects)

    # Render all pages and inject CSS
    pages_count = get_toolkit().getPageCount()
    final_svgs: List[str] = []
    for p in range(1, pages_count + 1):
        svg = vrv_render_page(p)
        # Inject CSS for notebook display (since vrv_highlight_ids only affects toolkit state for future renders, 
        # but we just rendered. Actually vrv_highlight_ids sets svgAdditionalCSS which IS used in vrv_render_page.
        # BUT vrv_inject_highlight_css is for INLINE css injection if we want to be sure or if we are manipulating existing SVGs.
        # The existing vrv_insert_annot_plist does BOTH: sets toolkit options AND injects inline. 
        # Let's follow that pattern for consistency.
        svg = vrv_inject_highlight_css(svg, highlight_ids, color=highlight_color, shape_only=shape_only, include_rects=include_rects)
        final_svgs.append(svg)

    if display:
        for svg in final_svgs:
            vrv_display_svg(svg)

    return final_svgs if return_svgs else None
