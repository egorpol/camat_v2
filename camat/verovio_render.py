from __future__ import annotations

import base64
import io
import os
import re
import uuid
import warnings
import json
import hashlib
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from .quiet_utils import suppress_native_output
from .verovio_guard import guarded_load_into_verovio_toolkit

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
    "vrv_convert_to_mei",
    "vrv_render_page",
    "vrv_render_all_pages",
    "vrv_display_svg",
    "vrv_find_elements_at_time",
    "vrv_timemap",
    "vrv_get_mei",
    "vrv_set_mei",
    "vrv_mask_mei_to_ids",
    "vrv_render_selection_excerpt",
    "vrv_render_symbolic_selection",
    "vrv_render_source_context",
    "vrv_insert_annot",
    "vrv_has_mei_export",
    "vrv_set_additional_css",
    "vrv_highlight_ids",
    "vrv_crop_svg_to_ids",
    "vrv_crop_svgs_to_ids",
    "vrv_debug_info",
    "vrv_process_annotations",
    "vrv_quiet",
]


_VRV_TOOLKIT = verovio.toolkit()
_EXTRA_SVG_CSS = ""
_VRV_OPTION_SUPPORT_CACHE: Dict[str, bool] = {}
_VRV_QUIET_NATIVE_OUTPUT = False
_VRV_QUIET_SUPPRESS_STDOUT = True
_VRV_QUIET_SUPPRESS_STDERR = True

# Common namespaces
MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def _get_requests_module():
    """
    Import requests lazily so unrelated workflows do not emit dependency warnings.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import requests  # type: ignore
    return requests


def vrv_namespaces() -> Dict[str, str]:
    """
    Return a namespace prefix map suitable for ElementTree XPath queries.
    Keys: 'mei', 'xml'.
    """
    return {"mei": MEI_NS, "xml": XML_NS}


def get_toolkit():
    return _VRV_TOOLKIT


@contextmanager
def vrv_quiet(
    enabled: bool = True,
    *,
    suppress_stdout: bool = True,
    suppress_stderr: bool = True,
):
    """
    Temporarily suppress native Verovio stdout/stderr output.
    """
    global _VRV_QUIET_NATIVE_OUTPUT, _VRV_QUIET_SUPPRESS_STDOUT, _VRV_QUIET_SUPPRESS_STDERR
    prev = (
        _VRV_QUIET_NATIVE_OUTPUT,
        _VRV_QUIET_SUPPRESS_STDOUT,
        _VRV_QUIET_SUPPRESS_STDERR,
    )
    _VRV_QUIET_NATIVE_OUTPUT = bool(enabled)
    _VRV_QUIET_SUPPRESS_STDOUT = bool(suppress_stdout)
    _VRV_QUIET_SUPPRESS_STDERR = bool(suppress_stderr)
    try:
        yield
    finally:
        (
            _VRV_QUIET_NATIVE_OUTPUT,
            _VRV_QUIET_SUPPRESS_STDOUT,
            _VRV_QUIET_SUPPRESS_STDERR,
        ) = prev


def _vrv_suppress_if_needed():
    return suppress_native_output(
        enabled=_VRV_QUIET_NATIVE_OUTPUT,
        suppress_stdout=_VRV_QUIET_SUPPRESS_STDOUT,
        suppress_stderr=_VRV_QUIET_SUPPRESS_STDERR,
    )


def _ensure_svg(svg: Any) -> str:
    if svg is None:
        return ""
    if isinstance(svg, bytes):
        return svg.decode("utf-8", errors="ignore")
    return str(svg)


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen: set[str] = set()
    deduped: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _xml_local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _vrv_parse_option_payload(payload: Any) -> Optional[Dict[str, Any]]:
    if payload is None:
        return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return None
    if isinstance(payload, dict):
        return payload
    return None


def _vrv_supports_option(option_name: str) -> bool:
    cached = _VRV_OPTION_SUPPORT_CACHE.get(option_name)
    if cached is not None:
        return cached

    payload = None
    if hasattr(_VRV_TOOLKIT, "getAvailableOptions"):
        try:
            payload = _VRV_TOOLKIT.getAvailableOptions()
        except Exception:
            payload = None
    if payload is None and hasattr(_VRV_TOOLKIT, "getOptions"):
        try:
            payload = _VRV_TOOLKIT.getOptions()
        except Exception:
            payload = None

    parsed = _vrv_parse_option_payload(payload)
    supported = bool(parsed and option_name in parsed)
    _VRV_OPTION_SUPPORT_CACHE[option_name] = supported
    return supported


def _vrv_annotation_signature(annot: Dict[str, Any]) -> str:
    """
    Build a stable signature for an annotation spec, ignoring xml_id.
    """
    normalized: Dict[str, Any] = {}
    for key, value in annot.items():
        if key == "xml_id" or value is None:
            continue
        if isinstance(value, list):
            normalized[key] = [str(item) for item in value]
        else:
            normalized[key] = value
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _vrv_assign_stable_annotation_ids(annotations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Return copies of annotation specs with deterministic xml_id values when absent.

    This keeps repeated vrv_process_annotations calls idempotent even when callers
    omit xml_id in convenience notebook code.
    """
    seen_counts: Dict[str, int] = {}
    prepared: List[Dict[str, Any]] = []

    for annot in annotations:
        current = dict(annot)
        if current.get("xml_id"):
            prepared.append(current)
            continue

        signature = _vrv_annotation_signature(current)
        count = seen_counts.get(signature, 0) + 1
        seen_counts[signature] = count
        digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
        current["xml_id"] = f"auto-annot-{digest}-{count}"
        prepared.append(current)

    return prepared


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
    with _vrv_suppress_if_needed():
        _VRV_TOOLKIT.setOptions(opts)


def vrv_guess_input_from(source_hint: Optional[str] = None, content: Optional[str] = None) -> Optional[str]:
    """
    Guess Verovio's inputFrom option.

    Uses file extension from source_hint (URL or path) or lightweight content sniffing.
    Returns a Verovio ``inputFrom`` value when known.
    Returns None when unknown.
    """
    # 1) Extension-based
    if source_hint:
        path = source_hint.split("?")[0].split("#")[0]
        lower_path = path.lower()
        _, ext = os.path.splitext(lower_path)
        if lower_path.endswith(".cmme.xml"):
            return "cmme.xml"
        if ext in {".mei"}:
            return "mei"
        if ext in {".mxl"}:
            return "musicxml-zip"
        if ext in {".musicxml"}:
            return "musicxml"
        if ext in {".krn", ".kern", ".hum"}:
            return "humdrum"
        if ext == ".abc":
            return "abc"
        if ext == ".pae":
            return "pae"
        if ext in {".darms", ".drm"}:
            return "darms"
        if ext == ".esac":
            return "esac"
        if ext in {".volpiano", ".volp"}:
            return "volpiano"
        # .xml is ambiguous: it is used for both MEI and MusicXML. Defer to
        # content sniffing instead of forcing MEI-as-.xml through MusicXML.
        if ext == ".xml" and not content:
            return None

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
        if re.search(r"(?m)^\s*x:\s*\S+", head) and re.search(r"(?m)^\s*k:\s*\S+", head):
            return "abc"

    return None


def _vrv_load_zip_bytes(data: bytes, *, source_hint: Optional[str] = None) -> int:
    """
    Load compressed MusicXML (.mxl) bytes into Verovio and return page count.
    """
    with _vrv_suppress_if_needed():
        if hasattr(_VRV_TOOLKIT, "loadZipDataBase64"):
            load_result = _VRV_TOOLKIT.loadZipDataBase64(base64.b64encode(data).decode("ascii"))
        elif hasattr(_VRV_TOOLKIT, "loadZipDataBuffer"):
            load_result = _VRV_TOOLKIT.loadZipDataBuffer(data, len(data))
        else:
            raise RuntimeError("This Verovio build does not expose a compressed MusicXML loader.")
        pages = _VRV_TOOLKIT.getPageCount()
    if not load_result or pages <= 0:
        log_msg = ""
        if hasattr(_VRV_TOOLKIT, "getLog"):
            try:
                log_msg = _VRV_TOOLKIT.getLog() or ""
            except Exception:
                log_msg = ""
        detail = f" for {source_hint}" if source_hint else ""
        raise RuntimeError(
            f"Verovio failed to load compressed MusicXML{detail} (pageCount={pages}). "
            f"{('Log: ' + log_msg) if log_msg else ''}"
        )
    return pages


def vrv_load_data(
    data: str,
    *,
    input_from: Optional[str] = None,
    source_hint: Optional[str] = None,
) -> int:
    """
    Load a score string into Verovio. Returns page count.
    Set input_from to a Verovio-supported input format; if None, attempts to
    guess from content.
    Use vrv_load_from_file or vrv_load_from_url for compressed MusicXML (.mxl).
    """
    inferred = input_from or vrv_guess_input_from(None, data) or "musicxml"
    with _vrv_suppress_if_needed():
        load_info = guarded_load_into_verovio_toolkit(
            _VRV_TOOLKIT,
            data,
            input_from=inferred,
            source_hint=source_hint,
        )
        if load_info.get("sanitized") and load_info.get("message"):
            warnings.warn(str(load_info["message"]), RuntimeWarning, stacklevel=2)
        return _VRV_TOOLKIT.getPageCount()


def vrv_load_from_file(path: str, *, input_from: Optional[str] = None, encoding: str = "utf-8") -> int:
    inferred = input_from or vrv_guess_input_from(path, None)
    if inferred == "musicxml-zip":
        with io.open(path, "rb") as f:
            return _vrv_load_zip_bytes(f.read(), source_hint=path)
    with io.open(path, "r", encoding=encoding, errors="ignore") as f:
        data = f.read()
    inferred = input_from or vrv_guess_input_from(path, data)
    return vrv_load_data(data, input_from=inferred, source_hint=path)


def vrv_load_from_url(url: str, *, input_from: Optional[str] = None, timeout: int = 30) -> int:
    """
    Load MEI/MusicXML/Humdrum from URL, auto-detecting inputFrom when not provided.
    Returns page count.
    """
    requests = _get_requests_module()
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    inferred = input_from or vrv_guess_input_from(url, None)
    if inferred == "musicxml-zip":
        return _vrv_load_zip_bytes(resp.content, source_hint=url)
    # Prefer text; fall back to bytes decode
    try:
        data = resp.text
        if not data or data == "" and resp.content:
            data = resp.content.decode("utf-8", errors="ignore")
    except Exception:
        data = resp.content.decode("utf-8", errors="ignore")
    inferred = input_from or vrv_guess_input_from(url, data)
    return vrv_load_data(data, input_from=inferred, source_hint=url)


def vrv_convert_to_mei(
    source: str,
    *,
    is_url: bool = False,
    input_from: Optional[str] = None,
    encoding: str = "utf-8",
    timeout: int = 30,
) -> str:
    """
    Convert a Verovio-supported score format to MEI using the global Verovio toolkit.

    This is a thin convenience wrapper around the existing vrv_load_* helpers plus
    vrv_get_mei():

    - When is_url=True, 'source' is treated as a remote URL and loaded via vrv_load_from_url.
    - Otherwise, 'source' is treated as a local file path and loaded via vrv_load_from_file.
    - When ``input_from`` is omitted, the type is auto-detected from the file
      extension or content. This helper only covers formats Verovio can load
      directly; the corpus converter handles other music21-readable formats by
      exporting MusicXML before this Verovio step.

    The converted MEI is returned as a string, and the score remains loaded in the toolkit
    so that subsequent calls to vrv_render_page / vrv_render_all_pages operate on it.
    """
    if is_url:
        vrv_load_from_url(source, input_from=input_from, timeout=timeout)
    else:
        vrv_load_from_file(source, input_from=input_from, encoding=encoding)
    return vrv_get_mei()


def vrv_render_page(page: int) -> str:
    with _vrv_suppress_if_needed():
        svg = _VRV_TOOLKIT.renderToSVG(page)
    return _ensure_svg(svg)


def vrv_render_all_pages() -> List[str]:
    with _vrv_suppress_if_needed():
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
    if not hasattr(_VRV_TOOLKIT, "getElementsAtTime"):
        return None
    with _vrv_suppress_if_needed():
        return _VRV_TOOLKIT.getElementsAtTime(ms)


def vrv_timemap():
    if hasattr(_VRV_TOOLKIT, "renderToTimemap"):
        with _vrv_suppress_if_needed():
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
    with _vrv_suppress_if_needed():
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
    with _vrv_suppress_if_needed():
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


def vrv_mask_mei_to_ids(mei_xml: str, ids: List[str]) -> str:
    """
    Return an MEI score in which only the selected notes remain visible.

    Measures containing no selected ids are removed. Within retained measures,
    unselected notes and rests become invisible ``<space>`` / ``<mSpace>``
    events carrying the original duration attributes and ids. This preserves
    the selected notes' original temporal positions without displaying the
    surrounding music. Partially retained beams are unwrapped so Verovio can
    render the mixture of visible notes and invisible spaces safely.
    """
    try:
        from xml.etree import ElementTree as ET  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("xml.etree.ElementTree is required to mask MEI") from exc

    try:
        ET.register_namespace("", MEI_NS)
        ET.register_namespace("xml", XML_NS)
        root = ET.fromstring(mei_xml)
    except Exception as exc:
        raise ValueError("mei_xml is not well-formed XML") from exc

    selected_ids = {value.lstrip("#") for value in ids if value}
    if not selected_ids:
        raise ValueError("ids must contain at least one MEI xml:id")

    xml_id_key = f"{{{XML_NS}}}id"
    parent_map = {child: parent for parent in root.iter() for child in parent}
    selected_nodes = [
        element
        for element in root.iter()
        if element.get(xml_id_key) in selected_ids
        and _xml_local_name(element.tag) == "note"
    ]
    found_ids = {element.get(xml_id_key) for element in selected_nodes}
    missing_ids = sorted(selected_ids - found_ids)
    if missing_ids:
        preview = ", ".join(missing_ids[:5])
        suffix = " ..." if len(missing_ids) > 5 else ""
        raise ValueError(f"Selected note ids not found in MEI: {preview}{suffix}")

    selected_measures = set()
    selected_staff_numbers: set[str] = set()
    selected_layer_keys: set[Tuple[str, str]] = set()
    for node in selected_nodes:
        current = node
        staff_number = "1"
        layer_number = "1"
        while current is not None:
            local_name = _xml_local_name(current.tag)
            if local_name == "layer":
                layer_number = current.get("n", "1")
            elif local_name == "staff":
                staff_number = current.get("n", "1")
            if _xml_local_name(current.tag) == "measure":
                selected_measures.add(current)
                break
            current = parent_map.get(current)
        selected_staff_numbers.add(staff_number)
        selected_layer_keys.add((staff_number, layer_number))
    if not selected_measures:
        raise ValueError("Selected ids are not contained in MEI measures")

    # Promote the notation context active at the first selected event. Inline
    # clef/key/meter changes can live in an earlier measure that will be removed,
    # so relying only on the work's opening scoreDef can produce the wrong staff.
    selected_score = None
    current = selected_nodes[0]
    while current is not None:
        if _xml_local_name(current.tag) == "score":
            selected_score = current
            break
        current = parent_map.get(current)

    if selected_score is not None:
        score_order = list(selected_score.iter())
        order_index = {element: index for index, element in enumerate(score_order)}
        first_selected_index = min(order_index[node] for node in selected_nodes)
        opening_score_def = next(
            (
                element
                for element in score_order
                if _xml_local_name(element.tag) == "scoreDef"
            ),
            None,
        )

        active_score_context: Dict[str, str] = {}
        active_clefs: Dict[str, Dict[str, str]] = {}

        def ancestor_staff_number(element) -> Optional[str]:
            ancestor = element
            while ancestor is not None and ancestor is not selected_score:
                if _xml_local_name(ancestor.tag) == "staff":
                    return ancestor.get("n", "1")
                ancestor = parent_map.get(ancestor)
            return None

        for element in score_order[: first_selected_index + 1]:
            local_name = _xml_local_name(element.tag)
            if local_name == "scoreDef":
                for name in (
                    "meter.count",
                    "meter.unit",
                    "meter.sym",
                    "keysig",
                    "key.mode",
                ):
                    value = element.get(name)
                    if value is not None:
                        active_score_context[name] = value
            elif local_name == "meterSig":
                for source_name, target_name in (
                    ("count", "meter.count"),
                    ("unit", "meter.unit"),
                    ("sym", "meter.sym"),
                ):
                    value = element.get(source_name)
                    if value is not None:
                        active_score_context[target_name] = value
            elif local_name == "keySig":
                for source_name, target_name in (("sig", "keysig"), ("mode", "key.mode")):
                    value = element.get(source_name)
                    if value is not None:
                        active_score_context[target_name] = value
            elif local_name == "staffDef":
                staff_number = element.get("n", "1")
                clef_context = active_clefs.setdefault(staff_number, {})
                for name in ("shape", "line", "dis", "dis.place"):
                    value = element.get(f"clef.{name}")
                    if value is not None:
                        clef_context[name] = value
            elif local_name == "clef":
                staff_number = element.get("staff") or ancestor_staff_number(element)
                if staff_number:
                    staff_number = str(staff_number).split()[0]
                    clef_context = active_clefs.setdefault(staff_number, {})
                    for name in ("shape", "line", "dis", "dis.place"):
                        value = element.get(name)
                        if value is not None:
                            clef_context[name] = value

        if opening_score_def is not None:
            opening_score_def.attrib.update(active_score_context)
            for staff_def in opening_score_def.iter():
                if _xml_local_name(staff_def.tag) != "staffDef":
                    continue
                staff_number = staff_def.get("n", "1")
                for name, value in active_clefs.get(staff_number, {}).items():
                    staff_def.set(f"clef.{name}", value)

    for measure in list(root.iter()):
        if _xml_local_name(measure.tag) != "measure" or measure in selected_measures:
            continue
        parent = parent_map.get(measure)
        if parent is not None:
            parent.remove(measure)

    # Remove unselected staves and voices entirely. Their timing is irrelevant
    # to the isolated symbolic excerpt and leaving their staffDefs behind can
    # produce empty systems or a dangling brace at the crop boundary.
    for measure in selected_measures:
        for staff in [
            element for element in list(measure) if _xml_local_name(element.tag) == "staff"
        ]:
            staff_number = staff.get("n", "1")
            if staff_number not in selected_staff_numbers:
                measure.remove(staff)
                continue
            for layer in [
                element for element in list(staff) if _xml_local_name(element.tag) == "layer"
            ]:
                if (staff_number, layer.get("n", "1")) not in selected_layer_keys:
                    staff.remove(layer)

    for staff_def in [
        element for element in root.iter() if _xml_local_name(element.tag) == "staffDef"
    ]:
        if staff_def.get("n", "1") in selected_staff_numbers:
            continue
        staff_group = parent_map.get(staff_def)
        if staff_group is not None:
            staff_group.remove(staff_def)
    for staff_group in [
        element for element in root.iter() if _xml_local_name(element.tag) == "staffGrp"
    ]:
        remaining_staff_defs = [
            element
            for element in staff_group.iter()
            if _xml_local_name(element.tag) == "staffDef"
        ]
        if len(remaining_staff_defs) <= 1:
            staff_group.attrib.pop("symbol", None)
            staff_group.attrib.pop("bar.thru", None)

    # Page headers from the full work are not part of an isolated selection.
    parent_map = {child: parent for parent in root.iter() for child in parent}
    for header in list(root.iter()):
        if _xml_local_name(header.tag) not in {"pgHead", "pgFoot"}:
            continue
        parent = parent_map.get(header)
        if parent is not None:
            parent.remove(header)

    duration_attributes = {
        "dur",
        "dots",
        "dur.ges",
        "num",
        "numbase",
        "tstamp",
        "staff",
        "layer",
    }

    def replacement_space(event, *, measure_space: bool = False):
        tag = "mSpace" if measure_space else "space"
        space = ET.Element(f"{{{MEI_NS}}}{tag}")
        event_id = event.get(xml_id_key)
        if event_id:
            space.set(xml_id_key, event_id)
        for name in duration_attributes:
            value = event.get(name)
            if value is not None:
                space.set(name, value)
        if not space.get("dur"):
            for descendant in event.iter():
                value = descendant.get("dur")
                if value:
                    space.set("dur", value)
                    dots = descendant.get("dots")
                    if dots:
                        space.set("dots", dots)
                    break
        return space

    parent_map = {child: parent for parent in root.iter() for child in parent}

    # Chords are simultaneous events: retain selected pitches in a partial chord,
    # or replace the whole unselected chord with one duration-equivalent space.
    chord_notes = set()
    for chord in [element for element in root.iter() if _xml_local_name(element.tag) == "chord"]:
        notes = [child for child in list(chord) if _xml_local_name(child.tag) == "note"]
        chord_notes.update(notes)
        visible_notes = [note for note in notes if note.get(xml_id_key) in selected_ids]
        if visible_notes:
            for note in notes:
                if note not in visible_notes:
                    chord.remove(note)
            continue
        parent = parent_map.get(chord)
        if parent is None:
            continue
        index = list(parent).index(chord)
        parent.remove(chord)
        parent.insert(index, replacement_space(chord))

    parent_map = {child: parent for parent in root.iter() for child in parent}
    for event in list(root.iter()):
        local_name = _xml_local_name(event.tag)
        if local_name == "note" and event not in chord_notes:
            if event.get(xml_id_key) in selected_ids:
                continue
            parent = parent_map.get(event)
            if parent is None:
                continue
            index = list(parent).index(event)
            parent.remove(event)
            # Grace notes occupy no metric time, so no compensating space is needed.
            if event.get("grace") is None:
                parent.insert(index, replacement_space(event))
        elif local_name in {"rest", "mRest"}:
            parent = parent_map.get(event)
            if parent is None:
                continue
            index = list(parent).index(event)
            parent.remove(event)
            parent.insert(index, replacement_space(event, measure_space=local_name == "mRest"))

    # A beam containing spaces is no longer a meaningful visible beam. Promote
    # its children in place; complete beams made entirely of selected notes stay.
    parent_map = {child: parent for parent in root.iter() for child in parent}
    for beam in [element for element in root.iter() if _xml_local_name(element.tag) == "beam"]:
        has_space = any(
            _xml_local_name(descendant.tag) in {"space", "mSpace"}
            for descendant in beam.iter()
        )
        if not has_space:
            continue
        parent = parent_map.get(beam)
        if parent is None:
            continue
        index = list(parent).index(beam)
        children = list(beam)
        parent.remove(beam)
        for offset, child in enumerate(children):
            parent.insert(index + offset, child)

    # A tupletSpan whose endpoints became spaces may no longer engrave its ratio.
    # When its endpoints are now siblings (commonly after partial-beam unwrapping),
    # convert the covered event range into an equivalent temporary <tuplet>.
    parent_map = {child: parent for parent in root.iter() for child in parent}
    by_id = {element.get(xml_id_key): element for element in root.iter() if element.get(xml_id_key)}
    for span in [
        element for element in root.iter() if _xml_local_name(element.tag) == "tupletSpan"
    ]:
        span_parent = parent_map.get(span)
        start = by_id.get((span.get("startid") or "").lstrip("#"))
        end = by_id.get((span.get("endid") or "").lstrip("#"))
        if start is None or end is None or parent_map.get(start) is not parent_map.get(end):
            continue
        event_parent = parent_map.get(start)
        if event_parent is None:
            continue
        siblings = list(event_parent)
        start_index = siblings.index(start)
        end_index = siblings.index(end)
        if end_index < start_index:
            start_index, end_index = end_index, start_index
        covered_events = siblings[start_index : end_index + 1]
        contains_selection = any(
            descendant.get(xml_id_key) in selected_ids
            and _xml_local_name(descendant.tag) == "note"
            for event in covered_events
            for descendant in event.iter()
        )
        if not contains_selection:
            if span_parent is not None:
                span_parent.remove(span)
            continue

        tuplet = ET.Element(f"{{{MEI_NS}}}tuplet")
        for name in (
            "num",
            "numbase",
            "num.format",
            "num.place",
            "num.visible",
            "bracket.place",
            "bracket.visible",
        ):
            value = span.get(name)
            if value is not None:
                tuplet.set(name, value)
        span_id = span.get(xml_id_key)
        if span_id:
            tuplet.set(xml_id_key, span_id)
        for event in covered_events:
            event_parent.remove(event)
            tuplet.append(event)
        event_parent.insert(start_index, tuplet)
        if span_parent is not None:
            span_parent.remove(span)

    # Remove visible editorial/control material that could otherwise float over
    # the blank staff. Tuplets and tupletSpan remain because they affect duration.
    removable_names = {
        "annot",
        "arpeg",
        "dir",
        "dynam",
        "fermata",
        "hairpin",
        "harm",
        "mordent",
        "octave",
        "pedal",
        "phrase",
        "slur",
        "tempo",
        "tie",
        "trill",
        "turn",
        "verse",
    }
    parent_map = {child: parent for parent in root.iter() for child in parent}
    for element in list(root.iter()):
        if _xml_local_name(element.tag) not in removable_names:
            continue
        parent = parent_map.get(element)
        if parent is not None:
            parent.remove(element)

    for note in root.iter(f"{{{MEI_NS}}}note"):
        # Keep source-local notation such as accidentals, dots, stems,
        # articulations, fermatas, and ornaments. Only drop relationship
        # shorthand that can point to notes removed from the excerpt.
        for attribute in ("slur", "tie"):
            note.attrib.pop(attribute, None)

    return ET.tostring(root, encoding="unicode")


def vrv_render_selection_excerpt(
    ids: List[str],
    *,
    mei_xml: Optional[str] = None,
    x_padding: float = 350,
    y_padding: float = 250,
    output_scale: float = 1.25,
    highlight_color: Optional[str] = None,
    highlight_style: str = "solid",
    pulse_color: str = "#0e4bad",
    display: bool = True,
    include_staff_context: bool = True,
) -> List[str]:
    """
    Render selected notes on otherwise blank staves and restore toolkit state.

    The source notes retain their pitch and encoded-duration attributes in a
    temporary masked MEI; surrounding time-bearing events become invisible
    spaces. The rendered pages are then cropped to the selected span, including
    selections that begin or end within a measure. The score previously loaded
    in the shared toolkit is restored before this function returns, even when
    rendering fails.
    """
    original_mei = vrv_get_mei()
    source_mei = mei_xml if mei_xml is not None else original_mei
    masked_mei = vrv_mask_mei_to_ids(source_mei, ids)

    try:
        vrv_set_mei(masked_mei)
        pages = vrv_render_all_pages()
        if highlight_color is not None:
            pages = [
                vrv_inject_highlight_css(
                    svg,
                    ids,
                    color=highlight_color,
                    shape_only=True,
                    highlight_style=highlight_style,
                    pulse_color=pulse_color,
                )
                for svg in pages
            ]
        excerpt_pages = vrv_crop_svgs_to_ids(
            pages,
            ids,
            x_padding=x_padding,
            y_padding=y_padding,
            output_scale=output_scale,
            include_staff_context=include_staff_context,
        )
    finally:
        vrv_set_mei(original_mei)

    if display:
        for svg in excerpt_pages:
            vrv_display_svg(svg)
    return excerpt_pages


def _vrv_ids_from_selection(selection: Any) -> List[str]:
    """Extract normalized MEI pointers from a DataFrame-like object or id list."""
    if isinstance(selection, (list, tuple, set)):
        raw_ids = list(selection)
    elif hasattr(selection, "columns"):
        columns = list(selection.columns)
        normalized = {
            re.sub(r"[^a-z0-9]", "", str(column).lower()): column for column in columns
        }
        xml_id_column = normalized.get("xmlid")
        if xml_id_column is None:
            raise ValueError("selection DataFrame must contain an xml_id column")
        raw_ids = list(selection[xml_id_column])
    else:
        raise TypeError("selection must be a DataFrame-like object or a list of ids")

    ids: List[str] = []
    seen: set[str] = set()
    for value in raw_ids:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text.lower() in {"nan", "<na>", "none"}:
            continue
        pointer = text if text.startswith("#") else f"#{text}"
        if pointer not in seen:
            seen.add(pointer)
            ids.append(pointer)
    if not ids:
        raise ValueError("selection contains no usable MEI xml_id values")
    return ids


def vrv_render_source_context(
    selection: Any,
    *,
    mei_xml: Optional[str] = None,
    highlight_color: str = "#cf268c",
    highlight_colors: Optional[Dict[str, str]] = None,
    selected_pages_only: bool = True,
    display: bool = True,
) -> List[str]:
    """Highlight source IDs on complete score pages, retaining notation context.

    All notes, rests, staves, clefs, signatures and relationships on each page
    remain as encoded. Only the selected note shapes receive highlight CSS.
    By default return complete pages containing a selection; no event masking
    or within-page crop is applied. The previously loaded score is restored.
    ``highlight_colors`` optionally maps selected source IDs to individual
    colors, e.g. search-hit ranks. Unmapped IDs use ``highlight_color``; shared
    beams retain their original color in this mode. Resolve multi-hit note
    membership before supplying one display color per ID.
    Use ``vrv_render_symbolic_selection`` for an isolated, masked selection.
    """
    import xml.etree.ElementTree as ET

    ids = _vrv_ids_from_selection(selection)
    original_mei = vrv_get_mei()
    source_mei = mei_xml if mei_xml is not None else original_mei
    root = ET.fromstring(source_mei)
    source_ids = {element.get(f"{{{XML_NS}}}id") for element in root.iter()}
    missing = [pointer for pointer in ids if pointer.lstrip("#") not in source_ids]
    if missing:
        raise ValueError(f"Selected IDs not found in source MEI: {missing}")
    colors = {pointer.lstrip("#"): color for pointer, color in (highlight_colors or {}).items()}
    if set(colors) - {pointer.lstrip("#") for pointer in ids}:
        raise ValueError("highlight_colors keys must belong to the selected source IDs.")
    pages: List[str] = []
    try:
        vrv_set_mei(source_mei)
        for svg in vrv_render_all_pages():
            resolved = _vrv_resolve_svg_ids_in_svg(
                svg, ids, include_bbox_ids=False, include_derived_ids=False,
            )
            if selected_pages_only and not any(resolved.values()):
                continue
            if highlight_colors is None:
                svg = vrv_inject_highlight_css(
                    svg, ids, color=highlight_color, shape_only=True,
                    extra_shape_selectors=_vrv_collect_beam_shape_selectors(svg, ids),
                )
            else:
                groups: Dict[str, List[str]] = {}
                for pointer in ids:
                    groups.setdefault(colors.get(pointer.lstrip("#"), highlight_color), []).append(pointer)
                # Reuse one scope for every color on this page. Each notebook
                # output still gets a distinct scope to avoid cross-cell CSS.
                scope = f"camat-vrv-{uuid.uuid4().hex}"
                for color, pointers in groups.items():
                    svg = vrv_inject_highlight_css(svg, pointers, color=color, shape_only=True, scope_id=scope)
            pages.append(svg)
    finally:
        vrv_set_mei(original_mei)
    if display:
        for svg in pages:
            vrv_display_svg(svg)
    return pages


def vrv_render_symbolic_selection(
    selection: Any,
    *,
    mei_xml: Optional[str] = None,
    x_padding: float = 200,
    y_padding: float = 300,
    output_scale: float = 1.25,
    highlight_color: Optional[str] = None,
    highlight_style: str = "solid",
    pulse_color: str = "#0e4bad",
    display: bool = True,
    return_mei: bool = False,
):
    """
    Render a DataFrame selection as a source-faithful symbolic MEI excerpt.

    The DataFrame contributes its ``xml_id`` selection; the source MEI supplies
    the notation semantics. Unselected events become duration-preserving spaces,
    while the crop retains the beginning of each selected staff so Verovio's
    clef, key signature, and meter remain visible. Pass the unmodified source
    MEI explicitly when the toolkit's current score has already been annotated.

    Returns SVG pages, or ``(excerpt_mei, svg_pages)`` when ``return_mei=True``.
    """
    ids = _vrv_ids_from_selection(selection)
    source_mei = mei_xml if mei_xml is not None else vrv_get_mei()
    excerpt_mei = vrv_mask_mei_to_ids(source_mei, ids)
    pages = vrv_render_selection_excerpt(
        ids,
        mei_xml=source_mei,
        x_padding=x_padding,
        y_padding=y_padding,
        output_scale=output_scale,
        highlight_color=highlight_color,
        highlight_style=highlight_style,
        pulse_color=pulse_color,
        display=display,
        include_staff_context=True,
    )
    return (excerpt_mei, pages) if return_mei else pages


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
    if not _vrv_supports_option("svgAdditionalCSS"):
        return
    with _vrv_suppress_if_needed():
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
    return _vrv_resolve_svg_ids_in_svg(
        svg,
        mei_ids,
        include_bbox_ids=include_bbox_ids,
        include_derived_ids=include_derived_ids,
    )


def _vrv_resolve_svg_ids_in_svg(svg_text: str, mei_ids: List[str], *, include_bbox_ids: bool = False, include_derived_ids: bool = False) -> Dict[str, List[str]]:
    """
    Resolve one or more MEI ids against a provided SVG string.
    """
    resolved: Dict[str, List[str]] = {}
    for target in mei_ids:
        resolved[target] = _vrv_find_svg_ids(
            svg_text,
            target,
            include_bbox_ids=include_bbox_ids,
            include_derived_ids=include_derived_ids,
        )
    return resolved


def _vrv_collect_beam_shape_selectors(svg_text: str, target_ids: List[str]) -> List[str]:
    """
    Return direct-child shape selectors for beam groups enclosing the given ids.

    This lets us color the beam polygon itself without also coloring every note
    nested inside the same beam group.
    """
    if not svg_text or not target_ids:
        return []

    try:
        from xml.etree import ElementTree as ET  # type: ignore
    except Exception:
        return []

    try:
        root = ET.fromstring(svg_text)
    except Exception:
        return []

    wanted_ids = {target.lstrip("#") for target in target_ids if target}
    if not wanted_ids:
        return []

    parent_map = {child: parent for parent in root.iter() for child in parent}
    beam_shape_tags = {"path", "polygon", "ellipse", "circle", "line", "use"}
    selectors: List[str] = []
    seen: set[str] = set()

    for element in root.iter():
        if element.attrib.get("id") not in wanted_ids:
            continue

        current = parent_map.get(element)
        while current is not None:
            classes = set(current.attrib.get("class", "").split())
            beam_id = current.attrib.get("id")
            if "beam" in classes and beam_id:
                for child in list(current):
                    tag = _xml_local_name(child.tag)
                    if tag not in beam_shape_tags:
                        continue
                    selector = f"#{beam_id} > {tag}"
                    if selector in seen:
                        continue
                    seen.add(selector)
                    selectors.append(selector)
                break
            current = parent_map.get(current)

    return selectors


def vrv_inject_highlight_css(
    svg_text: str,
    ids: List[str],
    *,
    color: str = "#ff0",
    shape_only: bool = True,
    include_rects: bool = False,
    extra_shape_selectors: Optional[List[str]] = None,
    highlight_style: str = "solid",
    pulse_color: str = "#0e4bad",
    scope_id: Optional[str] = None,
) -> str:
    """
    Inject an inline <style> block to color-highlight the given ids inside a single SVG string.
    - When shape_only is True, target only shape elements (path/polygon/ellipse/circle/line/use).
      Rectangles are optionally included if include_rects is True.
    - When shape_only is False, target shapes plus text/tspan, still avoiding rects unless include_rects is True.
    - extra_shape_selectors can be used for page-local selectors such as beam polygons.
    - highlight_style="mei-friend" adds mei-friend's short blue selection pulse.

    Every rule is scoped to a unique attribute on this SVG. This is important in
    notebooks, where several inline Verovio SVGs can contain the same MEI ids;
    unscoped ``#id`` rules otherwise recolor matching notes in other cell outputs.
    """
    if highlight_style not in {"solid", "mei-friend"}:
        raise ValueError("highlight_style must be 'solid' or 'mei-friend'")

    safe_scope_id = re.sub(
        r"[^A-Za-z0-9_-]", "-", scope_id or f"camat-vrv-{uuid.uuid4().hex}"
    )
    scope_attribute = f'data-camat-vrv-scope="{safe_scope_id}"'
    svg_open = re.search(r"<svg\b[^>]*>", svg_text)
    if svg_open and scope_attribute not in svg_open.group(0):
        opening_tag = svg_open.group(0)
        scoped_opening_tag = opening_tag[:-1] + f" {scope_attribute}>"
        svg_text = svg_text[: svg_open.start()] + scoped_opening_tag + svg_text[svg_open.end() :]

    root_selector = f'svg[{scope_attribute}]'
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

    if extra_shape_selectors:
        shape_selectors.extend(extra_shape_selectors)

    if not shape_selectors:
        return svg_text

    shape_selectors = [f"{root_selector} {selector}" for selector in shape_selectors]
    reset_text_selectors = [f"{root_selector} {selector}" for selector in reset_text_selectors]

    animation_rule = ""
    animation_css = ""
    if highlight_style == "mei-friend":
        animation_name = f"camatVrvPulse-{safe_scope_id}"
        animation_rule = f" animation: {animation_name} 0.6s ease;"
        animation_css = (
            f"@keyframes {animation_name} {{"
            "0% { fill: #121212; stroke: #121212; }"
            f"20% {{ fill: {pulse_color}; stroke: {pulse_color}; }}"
            f"100% {{ fill: {color}; stroke: {color}; }}"
            "}"
        )

    important = "" if highlight_style == "mei-friend" else " !important"
    style_rules = (
        f"{', '.join(shape_selectors)} "
        f"{{ fill: {color}{important}; stroke: {color}{important};{animation_rule} }}"
    )
    style_block = f"<style>{animation_css}{style_rules}</style>"

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


def _vrv_svg_translate(transform: Optional[str]) -> Tuple[float, float]:
    """Return the first SVG translate(x[, y]) pair in a transform string."""
    if not transform:
        return 0.0, 0.0
    match = re.search(
        r"translate\(\s*(-?(?:\d+(?:\.\d*)?|\.\d+))"
        r"(?:[\s,]+(-?(?:\d+(?:\.\d*)?|\.\d+)))?\s*\)",
        transform,
    )
    if not match:
        return 0.0, 0.0
    return float(match.group(1)), float(match.group(2) or 0.0)


def _vrv_svg_number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    match = re.match(r"\s*(-?(?:\d+(?:\.\d*)?|\.\d+))", value)
    return float(match.group(1)) if match else None


def _vrv_crop_svg_to_ids_or_none(
    svg_text: str,
    ids: List[str],
    *,
    x_padding: float,
    y_padding: float,
    output_scale: float,
    include_staff_context: bool,
) -> Optional[str]:
    """Crop one Verovio SVG, returning None when none of the ids are present."""
    try:
        from xml.etree import ElementTree as ET  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("xml.etree.ElementTree is required to crop SVG output") from exc

    try:
        ET.register_namespace("", "http://www.w3.org/2000/svg")
        ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
        root = ET.fromstring(_ensure_svg(svg_text))
    except Exception as exc:
        raise ValueError("svg_text is not well-formed SVG XML") from exc

    parent_map = {child: parent for parent in root.iter() for child in parent}
    by_id = {element.get("id"): element for element in root.iter() if element.get("id")}
    targets = [by_id.get(value.lstrip("#")) for value in ids]
    targets = [target for target in targets if target is not None]
    if not targets:
        return None

    definition_svg = None
    current = targets[0]
    while current is not None:
        if _xml_local_name(current.tag) == "svg" and "definition-scale" in set(
            current.get("class", "").split()
        ):
            definition_svg = current
            break
        current = parent_map.get(current)
    if definition_svg is None:
        definition_svg = next(
            (
                element
                for element in root.iter()
                if _xml_local_name(element.tag) == "svg" and element.get("viewBox")
            ),
            None,
        )
    if definition_svg is None:
        raise ValueError("Could not find Verovio's inner SVG viewBox")

    view_box_values = [float(value) for value in definition_svg.get("viewBox", "").split()]
    if len(view_box_values) != 4:
        raise ValueError("Verovio SVG has an invalid viewBox")
    view_x, view_y, view_width, view_height = view_box_values

    def translated_rect(rect) -> Optional[Tuple[float, float, float, float]]:
        x = _vrv_svg_number(rect.get("x"))
        y = _vrv_svg_number(rect.get("y"))
        width = _vrv_svg_number(rect.get("width"))
        height = _vrv_svg_number(rect.get("height"))
        if None in {x, y, width, height}:
            return None
        node = rect
        while node is not None and node is not definition_svg:
            translate_x, translate_y = _vrv_svg_translate(node.get("transform"))
            x += translate_x
            y += translate_y
            node = parent_map.get(node)
        return x, y, x + width, y + height

    target_boxes: List[Tuple[float, float, float, float]] = []
    context_boxes: List[Tuple[float, float, float, float]] = []
    staff_boxes: List[Tuple[float, float, float, float]] = []
    for target in targets:
        bbox = by_id.get(f"bbox-{target.get('id')}")
        bbox_rects = list(bbox.iter()) if bbox is not None else list(target.iter())
        for element in bbox_rects:
            if _xml_local_name(element.tag) != "rect":
                continue
            bounds = translated_rect(element)
            if bounds is not None:
                target_boxes.append(bounds)

        ancestor = target
        while ancestor is not None:
            ancestor_classes = set(ancestor.get("class", "").split())
            if "tuplet" in ancestor_classes:
                for descendant in ancestor.iter():
                    descendant_classes = set(descendant.get("class", "").split())
                    if not descendant_classes.intersection({"tupletNum", "tupletBracket"}):
                        continue
                    for element in descendant.iter():
                        if _xml_local_name(element.tag) != "rect":
                            continue
                        bounds = translated_rect(element)
                        if bounds is not None:
                            context_boxes.append(bounds)
            if "staff" in ancestor_classes:
                staff_bbox = by_id.get(f"bbox-{ancestor.get('id')}")
                if staff_bbox is not None:
                    for element in staff_bbox.iter():
                        if _xml_local_name(element.tag) != "rect":
                            continue
                        bounds = translated_rect(element)
                        if bounds is not None:
                            staff_boxes.append(bounds)
                break
            ancestor = parent_map.get(ancestor)

    if not target_boxes:
        return None

    horizontal_boxes = target_boxes + context_boxes
    if include_staff_context and staff_boxes:
        crop_x0 = min(box[0] for box in staff_boxes) - x_padding
    else:
        crop_x0 = min(box[0] for box in horizontal_boxes) - x_padding
    crop_x1 = max(box[2] for box in horizontal_boxes) + x_padding
    vertical_boxes = target_boxes + context_boxes + staff_boxes
    crop_y0 = min(box[1] for box in vertical_boxes) - y_padding
    crop_y1 = max(box[3] for box in vertical_boxes) + y_padding

    crop_x0 = max(view_x, crop_x0)
    crop_y0 = max(view_y, crop_y0)
    crop_x1 = min(view_x + view_width, crop_x1)
    crop_y1 = min(view_y + view_height, crop_y1)
    crop_width = max(1.0, crop_x1 - crop_x0)
    crop_height = max(1.0, crop_y1 - crop_y0)
    definition_svg.set(
        "viewBox", f"{crop_x0:g} {crop_y0:g} {crop_width:g} {crop_height:g}"
    )
    definition_svg.set("overflow", "hidden")
    root.set("overflow", "hidden")

    outer_width = _vrv_svg_number(root.get("width"))
    outer_height = _vrv_svg_number(root.get("height"))
    if outer_width is not None and view_width > 0:
        root.set("width", f"{crop_width * outer_width / view_width * output_scale:g}px")
    if outer_height is not None and view_height > 0:
        root.set("height", f"{crop_height * outer_height / view_height * output_scale:g}px")

    return ET.tostring(root, encoding="unicode")


def vrv_crop_svg_to_ids(
    svg_text: str,
    ids: List[str],
    *,
    x_padding: float = 250,
    y_padding: float = 250,
    output_scale: float = 1.0,
    include_staff_context: bool = False,
) -> str:
    """
    Crop a rendered Verovio SVG to the visual span of selected MEI/SVG ids.

    The horizontal bounds follow the selected glyphs, so the excerpt may start
    and end within a measure. The vertical bounds retain the selected staves.
    This changes only the SVG viewport; it does not fabricate a partial-measure
    MEI document or alter the score's musical semantics.
    """
    if output_scale <= 0:
        raise ValueError("output_scale must be greater than zero")
    cropped = _vrv_crop_svg_to_ids_or_none(
        svg_text,
        ids,
        x_padding=float(x_padding),
        y_padding=float(y_padding),
        output_scale=float(output_scale),
        include_staff_context=bool(include_staff_context),
    )
    if cropped is None:
        raise ValueError("None of the selected ids occur in this SVG")
    return cropped


def vrv_crop_svgs_to_ids(
    svg_pages: List[str],
    ids: List[str],
    *,
    x_padding: float = 250,
    y_padding: float = 250,
    output_scale: float = 1.0,
    include_staff_context: bool = False,
) -> List[str]:
    """Crop all matching pages and omit pages containing no selected ids."""
    if output_scale <= 0:
        raise ValueError("output_scale must be greater than zero")
    cropped_pages = [
        cropped
        for svg in svg_pages
        if (
            cropped := _vrv_crop_svg_to_ids_or_none(
                svg,
                ids,
                x_padding=float(x_padding),
                y_padding=float(y_padding),
                output_scale=float(output_scale),
                include_staff_context=bool(include_staff_context),
            )
        )
        is not None
    ]
    if not cropped_pages:
        raise ValueError("None of the selected ids occur in the supplied SVG pages")
    return cropped_pages


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
    highlight_style: str = "solid",
    pulse_color: str = "#0e4bad",
    include_rects: bool = False,
    pages: Optional[List[int]] = None,
    display: bool = True,
    return_svgs: bool = True,
) -> Optional[List[str]]:
    """
    High-level convenience:
    - Determine target ids (from plist_annot_config or custom_plist or auto).
    - Insert one or multiple clean <annot> plist entries into MEI (idempotent per xml_id).
    - Inject output-scoped highlight CSS so repeated notebook renders remain independent.

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
    first_svg = vrv_render_page(1)
    resolved = _vrv_resolve_svg_ids_in_svg(
        first_svg,
        plist_targets,
        include_bbox_ids=include_bbox_ids,
        include_derived_ids=include_derived_ids,
    )
    highlight_ids: List[str] = []
    for base, hits in resolved.items():
        if hits:
            # Use the exact svg ids we found
            for h in hits:
                highlight_ids.append(h if h.startswith("#") else f"#{h}")
        else:
            # Fall back to base pointer
            highlight_ids.append(base)
    highlight_ids = _dedupe_preserve_order(highlight_ids)

    # 5) Render and inject output-scoped CSS for notebook display. Do not set
    # svgAdditionalCSS on the shared toolkit: those rules persist into later cells.
    pages_list = pages or list(range(1, get_toolkit().getPageCount() + 1))
    final_svgs: List[str] = []
    for p in pages_list:
        svg = first_svg if p == 1 else vrv_render_page(p)
        beam_selectors = _vrv_collect_beam_shape_selectors(svg, highlight_ids)
        final_svgs.append(
            vrv_inject_highlight_css(
                svg,
                highlight_ids,
                color=highlight_color,
                shape_only=shape_only,
                include_rects=include_rects,
                extra_shape_selectors=beam_selectors,
                highlight_style=highlight_style,
                pulse_color=pulse_color,
            )
        )

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
    highlight_style: str = "solid",
    pulse_color: str = "#0e4bad",
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

    highlight_style: ``"solid"`` for the existing static highlight, or
        ``"mei-friend"`` for mei-friend's blue pulse treatment. Highlight CSS
        is scoped to each returned SVG so duplicate ids in other notebook cells
        are not affected.
    
    This function will:
    1. Insert all annotations into the MEI.
    2. Collect all 'plist' targets from the annotations.
    3. Highlight the plist targets in the rendered SVG.
    4. Display the result (if display=True).
    """
    prepared_annotations = _vrv_assign_stable_annotation_ids(annotations)

    # 1. Insert all annotations
    # We track plist targets to highlight them later
    all_plist_targets: List[str] = []

    for annot in prepared_annotations:
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
    unique_targets = _dedupe_preserve_order(all_plist_targets)

    # 2. & 3. Resolve IDs, highlight, and render
    # We can reuse logic similar to vrv_insert_annot_plist but adapted
    
    # Map to actual SVG ids (page 1) - we assume page 1 for resolution for now, 
    # or we could resolve per page if needed, but _vrv_resolve_svg_ids defaults to page 1.
    # For multi-page scores, this might need more robust handling if IDs are on later pages.
    first_svg = vrv_render_page(1)
    resolved = _vrv_resolve_svg_ids_in_svg(
        first_svg,
        unique_targets,
        include_bbox_ids=False,
        include_derived_ids=False,
    )
    highlight_ids: List[str] = []
    for base, hits in resolved.items():
        if hits:
            for h in hits:
                highlight_ids.append(h if h.startswith("#") else f"#{h}")
        else:
            highlight_ids.append(base)
    highlight_ids = _dedupe_preserve_order(highlight_ids)

    # Render all pages and inject output-scoped CSS. In particular, do not set
    # svgAdditionalCSS on the shared toolkit: it would persist into later cells.
    pages_count = get_toolkit().getPageCount()
    final_svgs: List[str] = []
    for p in range(1, pages_count + 1):
        svg = first_svg if p == 1 else vrv_render_page(p)
        beam_selectors = _vrv_collect_beam_shape_selectors(svg, highlight_ids)
        svg = vrv_inject_highlight_css(
            svg,
            highlight_ids,
            color=highlight_color,
            shape_only=shape_only,
            include_rects=include_rects,
            extra_shape_selectors=beam_selectors,
            highlight_style=highlight_style,
            pulse_color=pulse_color,
        )
        final_svgs.append(svg)

    if display:
        for svg in final_svgs:
            vrv_display_svg(svg)

    return final_svgs if return_svgs else None
