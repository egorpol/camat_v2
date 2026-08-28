"""Render linked MEI notation and facsimile measure zones side by side.

Pure helpers parse MEI, render Verovio SVG pages, and return HTML. The
:class:`InteractiveFacsimileViewer` and
:func:`launch_interactive_facsimile_viewer` entry points add Jupyter controls
and optional MEI file watching. The viewer accepts a local MEI path or an HTTP(S)
link: files with facsimile surfaces, measure zones, and matching measure
``@facs`` links get a linked two-pane view, while files without those records
get a score-only view.
"""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass, field
from html import escape
import hashlib
import json
import math
import mimetypes
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable
from urllib.parse import urlparse
import uuid
import xml.etree.ElementTree as ET

import verovio

from .quiet_utils import suppress_native_output

MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NS = {"m": MEI_NS}

DEFAULT_PORTRAIT_SIZE = (2100, 2970)
DEFAULT_LANDSCAPE_SIZE = (2970, 2100)

__all__ = [
    "DEFAULT_LANDSCAPE_SIZE",
    "DEFAULT_PORTRAIT_SIZE",
    "FacsimileViewerCache",
    "FacsimileUnavailableError",
    "InteractiveFacsimileViewer",
    "build_facsimile_viewer",
    "build_verovio_options",
    "display_path",
    "find_camat_root",
    "format_facsimile_summary",
    "launch_interactive_facsimile_viewer",
    "make_diagnostic_table",
    "make_viewer_html",
    "mei_file_fingerprint",
    "probe_note_pname",
    "read_facsimile_model",
    "render_verovio_pages",
    "resolve_graphic_src",
    "resolve_mei_source",
    "resolve_repo_path",
    "score_content_hash",
    "verovio_options_hash",
]


class FacsimileUnavailableError(RuntimeError):
    """Raised when an MEI has no usable facsimile surface to inspect."""


def find_camat_root(start: Path | None = None) -> Path:
    """Return the CAMAT checkout when Jupyter or tests start in a subdirectory."""
    start = (start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "camat").is_dir():
            return candidate
    return start


def resolve_repo_path(path: str | Path, *, repo_root: Path | None = None) -> Path:
    """Resolve a repo-relative, absolute, or home-relative path."""
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = (repo_root or find_camat_root()).resolve() / resolved
    return resolved.resolve()


def display_path(path: Path, *, repo_root: Path | None = None) -> str:
    """Return a compact path relative to repo_root when possible."""
    root = (repo_root or find_camat_root()).resolve()
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _default_mei_cache_dir(repo_root: Path | None = None) -> Path:
    root = (repo_root or find_camat_root()).resolve()
    if (root / "pyproject.toml").is_file() and (root / "camat").is_dir():
        return root / "converted_mei" / "facsimile_viewer_sources"
    from .music_utils import get_download_cache_dir

    return Path(get_download_cache_dir())


def resolve_mei_source(
    source: str | Path,
    *,
    repo_root: Path | None = None,
    cache_dir: str | Path | None = None,
    timeout_seconds: int = 60,
) -> Path:
    """Return a local MEI path from a local file or an HTTP(S) link.

    GitHub ``blob`` pages are converted to raw-file URLs. Remote files are
    cached under ``converted_mei/facsimile_viewer_sources/`` when this is a
    CAMAT checkout, otherwise under the shared CAMAT download cache.
    """
    root = (repo_root or find_camat_root()).resolve()
    source_text = str(source)
    if source_text.startswith(("http://", "https://")):
        from .music_utils import get_file_path

        resolved_cache = Path(cache_dir) if cache_dir is not None else _default_mei_cache_dir(root)
        return Path(
            get_file_path(
                source_text,
                timeout_seconds=timeout_seconds,
                use_cache=True,
                cache_dir=str(resolved_cache),
            )
        ).resolve()

    local_path = resolve_repo_path(source, repo_root=root)
    if not local_path.is_file():
        raise FileNotFoundError(f"No MEI file at {local_path}")
    return local_path


def parse_int_attr(element: ET.Element, attr: str, *, context: str) -> int:
    value = element.get(attr)
    if value is None:
        raise ValueError(f"Missing @{attr} on {context}")
    try:
        return int(round(float(value)))
    except ValueError as exc:
        raise ValueError(f"Invalid @{attr}={value!r} on {context}") from exc


def resolve_graphic_src(target: str, mei_path: Path) -> str:
    """Return a browser-usable image source for a graphic target."""
    parsed = urlparse(target)
    if parsed.scheme in {"http", "https", "data"}:
        return target

    image_path = Path(target).expanduser()
    if not image_path.is_absolute():
        image_path = mei_path.parent / image_path
    image_path = image_path.resolve()
    if not image_path.is_file():
        return target

    mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    payload = b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def read_facsimile_model(
    mei_path: str | Path,
    *,
    repo_root: Path | None = None,
    allow_missing_facsimile: bool = False,
) -> dict:
    """Parse facsimile graphics, zones, and score measure links from an MEI file.

    ``mei_path`` may be a local path or an HTTP(S) link, including a GitHub
    ``blob`` page. Set ``allow_missing_facsimile=True`` to return a score-only
    model when the MEI has no facsimile or usable surfaces. Invalid
    facsimile records, such as unresolved measure links, remain errors.
    """
    mei_path = resolve_mei_source(mei_path, repo_root=repo_root)
    tree = ET.parse(mei_path)
    root = tree.getroot()

    def score_only_model(reason: str) -> dict:
        measures = []
        for measure in root.findall(".//m:measure", NS):
            facs = measure.get("facs") or ""
            measures.append(
                {
                    "measure_id": measure.get(XML_ID) or "",
                    "measure_n": measure.get("n") or "",
                    "facs": facs,
                    "zone_id": facs[1:] if facs.startswith("#") else facs,
                    "zone": None,
                    "surface_id": None,
                    "surface_index": None,
                    "status": "facsimile unavailable",
                }
            )
        if not measures:
            raise RuntimeError(
                f"No score <measure> elements found in "
                f"{display_path(mei_path, repo_root=repo_root)}"
            )
        return {
            "mei_path": mei_path,
            "viewer_mode": "score-only",
            "has_facsimile": False,
            "facsimile_status": reason,
            "graphic_target": None,
            "graphic_src": None,
            "image_width": None,
            "image_height": None,
            "surfaces": [],
            "zones": {},
            "measures": measures,
            "linked": [],
            "missing_facs": measures,
            "other_surface_links": [],
        }

    def unavailable(message: str) -> dict:
        if allow_missing_facsimile:
            return score_only_model(message)
        raise FacsimileUnavailableError(message)

    facsimile = root.find(".//m:facsimile", NS)
    if facsimile is None:
        return unavailable(
            f"No <facsimile> found in {display_path(mei_path, repo_root=repo_root)}"
        )

    surface_elements = facsimile.findall("m:surface", NS)
    if not surface_elements:
        return unavailable(
            f"No <surface> found in <facsimile> for {display_path(mei_path, repo_root=repo_root)}"
        )

    surfaces = []
    zones = {}
    for source_index, surface in enumerate(surface_elements):
        measure_zones = [
            zone
            for zone in surface.findall("m:zone", NS)
            if zone.get("type") == "measure"
        ]
        if not measure_zones:
            continue

        surface_id = surface.get(XML_ID) or f"surface-{source_index + 1}"
        graphic = surface.find("m:graphic", NS)
        if graphic is None:
            raise RuntimeError(
                f"Facsimile surface {surface_id!r} has measure zones but no <graphic>"
            )
        graphic_target = graphic.get("target")
        if not graphic_target:
            raise RuntimeError(
                f"The <graphic> on facsimile surface {surface_id!r} has no @target"
            )

        surface_index = len(surfaces)
        surface_zones = {}
        for zone in measure_zones:
            zone_id = zone.get(XML_ID)
            if not zone_id:
                raise RuntimeError("A measure <zone> is missing xml:id")
            if zone_id in zones:
                raise RuntimeError(f"Duplicate measure zone xml:id: {zone_id}")
            zone_model = {
                "id": zone_id,
                "ulx": parse_int_attr(zone, "ulx", context=f"zone {zone_id}"),
                "uly": parse_int_attr(zone, "uly", context=f"zone {zone_id}"),
                "lrx": parse_int_attr(zone, "lrx", context=f"zone {zone_id}"),
                "lry": parse_int_attr(zone, "lry", context=f"zone {zone_id}"),
                "surface_id": surface_id,
                "surface_index": surface_index,
            }
            surface_zones[zone_id] = zone_model
            zones[zone_id] = zone_model

        surfaces.append(
            {
                "id": surface_id,
                "n": surface.get("n") or str(source_index + 1),
                "index": surface_index,
                "graphic_target": graphic_target,
                "graphic_src": resolve_graphic_src(graphic_target, mei_path),
                "image_width": parse_int_attr(
                    graphic, "width", context=f"graphic on surface {surface_id}"
                ),
                "image_height": parse_int_attr(
                    graphic, "height", context=f"graphic on surface {surface_id}"
                ),
                "zones": surface_zones,
            }
        )

    if not surfaces:
        return unavailable(
            f"No facsimile surface with measure zones found in "
            f"{display_path(mei_path, repo_root=repo_root)}"
        )

    measures = []
    unresolved = []
    missing_facs = []
    for measure in root.findall(".//m:measure", NS):
        measure_id = measure.get(XML_ID)
        measure_n = measure.get("n") or ""
        facs = measure.get("facs") or ""
        zone_id = facs[1:] if facs.startswith("#") else facs
        zone = zones.get(zone_id) if zone_id else None
        status = "linked" if zone else "missing facs" if not zone_id else "unresolved facs"
        row = {
            "measure_id": measure_id or "",
            "measure_n": measure_n,
            "facs": facs,
            "zone_id": zone_id,
            "zone": zone,
            "surface_id": zone["surface_id"] if zone else None,
            "surface_index": zone["surface_index"] if zone else None,
            "status": status,
        }
        measures.append(row)
        if status == "missing facs":
            missing_facs.append(row)
        elif status == "unresolved facs":
            unresolved.append(row)

    if not measures:
        raise RuntimeError(f"No score <measure> elements found in {display_path(mei_path, repo_root=repo_root)}")
    if unresolved:
        examples = ", ".join(row["facs"] for row in unresolved[:5])
        raise RuntimeError(f"Found {len(unresolved)} unresolved measure @facs link(s): {examples}")

    linked = [row for row in measures if row["status"] == "linked"]
    first_surface = surfaces[0]
    return {
        "mei_path": mei_path,
        "viewer_mode": "facsimile",
        "has_facsimile": True,
        "facsimile_status": None,
        # Keep the first-surface fields for callers written against the
        # original single-surface model.
        "graphic_target": first_surface["graphic_target"],
        "graphic_src": first_surface["graphic_src"],
        "image_width": first_surface["image_width"],
        "image_height": first_surface["image_height"],
        "surfaces": surfaces,
        "zones": zones,
        "measures": measures,
        "linked": linked,
        "missing_facs": missing_facs,
        "other_surface_links": [
            row for row in linked if (row["surface_index"] or 0) > 0
        ],
    }


def _remove_elements(root: ET.Element, tag_name: str) -> None:
    for element in list(root.iter()):
        if element.tag.rsplit("}", 1)[-1] != tag_name:
            continue
        for parent in root.iter():
            if element in list(parent):
                parent.remove(element)
                break


def score_content_hash(mei_path: Path) -> str:
    """Hash score content while ignoring facsimile zones and measure @facs links."""
    tree = ET.parse(mei_path)
    root = tree.getroot()
    _remove_elements(root, "facsimile")
    for measure in root.findall(".//m:measure", NS):
        measure.attrib.pop("facs", None)
    payload = ET.tostring(root, encoding="unicode")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verovio_options_hash(options: dict) -> str:
    return hashlib.sha256(json.dumps(options, sort_keys=True).encode("utf-8")).hexdigest()


def format_facsimile_summary(model: dict, *, repo_root: Path | None = None) -> str:
    mei_path = model["mei_path"]
    if not model.get("has_facsimile", True):
        return (
            f"MEI:             {display_path(mei_path, repo_root=repo_root)}\n"
            f"Viewer mode:     score only\n"
            f"Measures:        {len(model['measures'])}\n"
            f"Facsimile:       unavailable ({model['facsimile_status']})"
        )
    return (
        f"MEI:             {display_path(mei_path, repo_root=repo_root)}\n"
        f"Viewer mode:     score + facsimile\n"
        f"Surfaces:        {len(model.get('surfaces', []))}\n"
        f"Measures:        {len(model['measures'])}\n"
        f"Linked zones:    {len(model['linked'])}\n"
        f"Missing @facs:   {len(model['missing_facs'])}"
    )


@dataclass
class FacsimileViewerCache:
    score_hash: str | None = None
    options_hash: str | None = None
    score_render: dict | None = field(default=None)


def build_facsimile_viewer(
    mei_path: str | Path,
    *,
    verovio_options: dict,
    initial_page: int = 1,
    render_score: bool | str = "auto",
    cache: FacsimileViewerCache | None = None,
    repo_root: Path | None = None,
    viewer_id: str | None = None,
    viewer_max_height: int = 820,
    facsimile_max_width: int = 600,
    zone_opacity: float = 0.18,
    initial_score_zoom_percent: int | float = 100,
    initial_facsimile_zoom_percent: int | float = 100,
    zoom_step_percent: int | float = 25,
    min_zoom_percent: int | float = 50,
    max_zoom_percent: int | float = 300,
    show_diagnostic_table: bool = True,
    show_verovio_warnings: bool = False,
    allow_missing_facsimile: bool = True,
) -> dict:
    """Render linked facsimiles or fall back to a score-only MEI viewer."""
    resolved_path = resolve_mei_source(mei_path, repo_root=repo_root)
    model = read_facsimile_model(
        resolved_path,
        repo_root=repo_root,
        allow_missing_facsimile=allow_missing_facsimile,
    )
    current_score_hash = score_content_hash(resolved_path)
    current_options_hash = verovio_options_hash(verovio_options)
    viewer_cache = cache if cache is not None else FacsimileViewerCache()

    if render_score == "auto":
        render_score = (
            viewer_cache.score_render is None
            or viewer_cache.score_hash != current_score_hash
            or viewer_cache.options_hash != current_options_hash
        )
    elif not render_score:
        render_score = False
    else:
        render_score = True

    if render_score or viewer_cache.score_render is None:
        score_render = render_verovio_pages(
            resolved_path,
            initial_page=initial_page,
            options=verovio_options,
            repo_root=repo_root,
            show_verovio_warnings=show_verovio_warnings,
        )
        viewer_cache.score_hash = current_score_hash
        viewer_cache.options_hash = current_options_hash
        viewer_cache.score_render = score_render
    else:
        score_render = viewer_cache.score_render

    html = make_viewer_html(
        model,
        score_render["pages"],
        total_score_pages=score_render["page_count"],
        initial_page_index=score_render["initial_page_index"],
        viewer_id=viewer_id,
        viewer_max_height=viewer_max_height,
        facsimile_max_width=facsimile_max_width,
        zone_opacity=zone_opacity,
        initial_score_zoom_percent=initial_score_zoom_percent,
        initial_facsimile_zoom_percent=initial_facsimile_zoom_percent,
        zoom_step_percent=zoom_step_percent,
        min_zoom_percent=min_zoom_percent,
        max_zoom_percent=max_zoom_percent,
        show_diagnostic_table=show_diagnostic_table,
    )
    return {
        "html": html,
        "model": model,
        "score_render": score_render,
        "rendered_score": render_score,
        "summary": format_facsimile_summary(model, repo_root=repo_root),
        "cache": viewer_cache,
    }


def build_verovio_options(
    base_options: dict,
    *,
    orientation: str,
    breaks: str,
    adjust_page_height: bool,
    portrait_size: tuple[int, int] = DEFAULT_PORTRAIT_SIZE,
    landscape_size: tuple[int, int] = DEFAULT_LANDSCAPE_SIZE,
) -> dict:
    orientation = orientation.lower()
    if orientation == "portrait":
        page_width, page_height = portrait_size
    elif orientation == "landscape":
        page_width, page_height = landscape_size
    else:
        raise ValueError('orientation must be "portrait" or "landscape"')

    if breaks not in {"auto", "encoded", "none"}:
        raise ValueError('breaks must be "auto", "encoded", or "none"')

    options = dict(base_options)
    options["adjustPageHeight"] = adjust_page_height
    options["breaks"] = breaks
    options["pageWidth"] = page_width
    options["pageHeight"] = page_height
    return options


def render_verovio_pages(
    mei_path: str | Path,
    *,
    initial_page: int,
    options: dict,
    repo_root: Path | None = None,
    show_verovio_warnings: bool = False,
) -> dict:
    """Render all Verovio pages and return SVG strings plus page metadata.

    Verovio layout messages such as ``Justification is highly compressed`` are
    suppressed unless ``show_verovio_warnings`` is True.
    """
    mei_path = resolve_mei_source(mei_path, repo_root=repo_root)
    mei_text = mei_path.read_text(encoding="utf-8")
    with suppress_native_output(enabled=not show_verovio_warnings):
        toolkit = verovio.toolkit()
        toolkit.setOptions(options)
        if not toolkit.loadData(mei_text):
            raise RuntimeError(
                f"Verovio could not load {display_path(mei_path, repo_root=repo_root)}"
            )

        page_count = toolkit.getPageCount()
        if initial_page < 1 or initial_page > page_count:
            raise ValueError(
                f"initial_page={initial_page} is outside the rendered page range 1..{page_count}"
            )

        pages = []
        for page_number in range(1, page_count + 1):
            svg = toolkit.renderToSVG(page_number)
            if not svg.strip():
                raise RuntimeError(f"Verovio returned an empty SVG for page {page_number}")
            pages.append({"number": page_number, "svg": svg})

    return {
        "page_count": page_count,
        "initial_page": initial_page,
        "initial_page_index": initial_page - 1,
        "pages": pages,
    }


def make_diagnostic_table(model: dict, *, show: bool = True) -> str:
    if not show:
        return ""

    rows = []
    for row in model["measures"]:
        zone = row["zone"] or {}
        rows.append(
            "<tr>"
            f"<td>{escape(row['measure_n'])}</td>"
            f"<td>{escape(row['measure_id'])}</td>"
            f"<td>{escape(row['facs'])}</td>"
            f"<td>{escape(row['zone_id'])}</td>"
            f"<td>{escape(row.get('surface_id') or '')}</td>"
            f"<td>{zone.get('ulx', '')}</td>"
            f"<td>{zone.get('uly', '')}</td>"
            f"<td>{zone.get('lrx', '')}</td>"
            f"<td>{zone.get('lry', '')}</td>"
            f"<td>{escape(row['status'])}</td>"
            "</tr>"
        )

    summary = (
        f"Measure-zone diagnostic table ({len(model['measures'])} measures)"
        if model.get("has_facsimile", True)
        else f"Measure/facsimile status ({len(model['measures'])} measures)"
    )
    return f"""
    <details class="mei-viewer-details">
      <summary>{summary}</summary>
      <table class="mei-viewer-table">
        <thead>
          <tr>
            <th>n</th><th>measure id</th><th>@facs</th><th>zone id</th>
            <th>surface</th><th>ulx</th><th>uly</th><th>lrx</th><th>lry</th><th>status</th>
          </tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </details>
    """


def make_viewer_html(
    model: dict,
    score_pages: list[dict],
    *,
    total_score_pages: int,
    initial_page_index: int = 0,
    viewer_id: str | None = None,
    viewer_max_height: int = 820,
    facsimile_max_width: int = 600,
    zone_opacity: float = 0.18,
    initial_score_zoom_percent: int | float = 100,
    initial_facsimile_zoom_percent: int | float = 100,
    zoom_step_percent: int | float = 25,
    min_zoom_percent: int | float = 50,
    max_zoom_percent: int | float = 300,
    show_diagnostic_table: bool = True,
) -> str:
    zoom_values = {
        "initial_score_zoom_percent": initial_score_zoom_percent,
        "initial_facsimile_zoom_percent": initial_facsimile_zoom_percent,
        "zoom_step_percent": zoom_step_percent,
        "min_zoom_percent": min_zoom_percent,
        "max_zoom_percent": max_zoom_percent,
    }
    for name, value in zoom_values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a number")
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if min_zoom_percent <= 0:
        raise ValueError("min_zoom_percent must be greater than zero")
    if max_zoom_percent < min_zoom_percent:
        raise ValueError(
            "max_zoom_percent must be greater than or equal to min_zoom_percent"
        )
    if zoom_step_percent <= 0:
        raise ValueError("zoom_step_percent must be greater than zero")
    for name, value in (
        ("initial_score_zoom_percent", initial_score_zoom_percent),
        ("initial_facsimile_zoom_percent", initial_facsimile_zoom_percent),
    ):
        if not min_zoom_percent <= value <= max_zoom_percent:
            raise ValueError(
                f"{name} must be between min_zoom_percent and max_zoom_percent"
            )

    viewer_id = viewer_id or f"mei-viewer-{uuid.uuid4().hex}"
    has_facsimile = model.get("has_facsimile", True)
    surfaces = model.get("surfaces", [])
    surface_overlays = {surface["index"]: [] for surface in surfaces}
    pairs = []
    measure_page = {}
    score_page_html = []
    initial_page_index = max(0, min(initial_page_index, len(score_pages) - 1))

    for index, page in enumerate(score_pages):
        page_number = page["number"]
        page_class = "score-page is-active" if index == initial_page_index else "score-page"
        score_page_html.append(
            f'<div class="{page_class}" data-score-page-index="{index}" data-score-page-number="{page_number}">'
            f'{page["svg"]}'
            "</div>"
        )
        for row in model["linked"]:
            measure_id = row["measure_id"]
            if measure_id and f'id="{measure_id}"' in page["svg"]:
                measure_page[measure_id] = index

    for row in model["linked"]:
        zone = row["zone"]
        measure_id = row["measure_id"]
        if not measure_id:
            continue
        width = zone["lrx"] - zone["ulx"]
        height = zone["lry"] - zone["uly"]
        page_index = measure_page.get(measure_id)
        surface_index = row["surface_index"]
        surface_overlays[surface_index].append(
            f'<rect class="zone" data-measure-id="{escape(measure_id)}" '
            f'data-zone-id="{escape(zone["id"])}" data-measure-n="{escape(row["measure_n"])}" '
            f'x="{zone["ulx"]}" y="{zone["uly"]}" width="{width}" height="{height}" />'
        )
        pairs.append(
            {
                "measureId": measure_id,
                "measureN": row["measure_n"],
                "zoneId": zone["id"],
                "surfaceIndex": surface_index,
                "pageIndex": page_index,
                "scorePage": score_pages[page_index]["number"] if page_index is not None else None,
            }
        )

    score_page_surface_indices = []
    for page_index in range(len(score_pages)):
        counts = {}
        for item in pairs:
            if item["pageIndex"] != page_index:
                continue
            surface_index = item["surfaceIndex"]
            counts[surface_index] = counts.get(surface_index, 0) + 1
        score_page_surface_indices.append(
            max(counts, key=counts.get) if counts else None
        )

    initial_surface_index = (
        score_page_surface_indices[initial_page_index]
        if score_page_surface_indices[initial_page_index] is not None
        else 0
    )
    pairs_json = json.dumps(pairs)
    score_pages_json = json.dumps([page["number"] for page in score_pages])
    score_page_surfaces_json = json.dumps(score_page_surface_indices)
    table_html = make_diagnostic_table(model, show=show_diagnostic_table)
    disabled_prev = "disabled" if len(score_pages) <= 1 else ""
    disabled_next = "disabled" if len(score_pages) <= 1 else ""
    if has_facsimile:
        facsimile_pages = []
        for surface in surfaces:
            surface_index = surface["index"]
            surface_class = (
                "facsimile-page is-active"
                if surface_index == initial_surface_index
                else "facsimile-page"
            )
            graphic_src = escape(surface["graphic_src"], quote=True)
            graphic_target = escape(surface["graphic_target"], quote=True)
            source_attribute = (
                f'src="{graphic_src}"'
                if surface_index == initial_surface_index
                else f'data-src="{graphic_src}"'
            )
            facsimile_pages.append(
                f'<div class="{surface_class}" data-surface-index="{surface_index}" '
                f'data-surface-n="{escape(surface["n"], quote=True)}">'
                '<div class="facsimile-wrap">'
                f'<img {source_attribute} alt="Facsimile image from MEI graphic target" '
                f'title="{graphic_target}" width="{surface["image_width"]}" '
                f'height="{surface["image_height"]}">'
                f'<svg class="zone-layer" viewBox="0 0 {surface["image_width"]} '
                f'{surface["image_height"]}" preserveAspectRatio="none" '
                'aria-label="Measure zone overlay">'
                f'{"".join(surface_overlays[surface_index])}'
                "</svg></div></div>"
            )
        facsimile_panel = f"""
    <div class="viewer-pane facsimile-pane" aria-label="Facsimile with measure zones">
      {''.join(facsimile_pages)}
    </div>"""
        viewer_status = "Hover or click a rendered measure or facsimile zone."
        grid_class = "viewer-grid"
        facsimile_zoom_controls = f"""
    <div class="zoom-controls" aria-label="Facsimile zoom controls">
      <span class="zoom-label">Facsimile zoom</span>
      <button type="button" class="facsimile-zoom-out" title="Zoom facsimile out">−</button>
      <button type="button" class="facsimile-zoom-reset" title="Reset facsimile zoom">{initial_facsimile_zoom_percent:g}%</button>
      <button type="button" class="facsimile-zoom-in" title="Zoom facsimile in">+</button>
    </div>"""
    else:
        facsimile_panel = ""
        facsimile_zoom_controls = ""
        viewer_status = (
            "Score-only mode — this MEI has no usable facsimile records. "
            "Add them and use Check facsimile to enable the linked view."
        )
        grid_class = "viewer-grid is-score-only"

    return f"""
<style>
  #{viewer_id} {{
    --active: #f59e0b;
    --linked: #2563eb;
    --panel-border: #d7dce2;
    --score-zoom: {initial_score_zoom_percent:g}%;
    --facsimile-zoom: {initial_facsimile_zoom_percent:g}%;
    color: #1f2933;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}
  #{viewer_id} .viewer-status {{
    margin: 0 0 10px;
    padding: 8px 10px;
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    background: #f8fafc;
    font-size: 13px;
  }}
  #{viewer_id} .score-toolbar {{
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    margin: 0 0 10px;
  }}
  #{viewer_id} .score-toolbar button {{
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    background: #ffffff;
    color: #1f2933;
    cursor: pointer;
    font-size: 13px;
    padding: 5px 9px;
  }}
  #{viewer_id} .score-toolbar button:disabled {{
    cursor: not-allowed;
    opacity: 0.45;
  }}
  #{viewer_id} .score-page-label {{
    font-size: 13px;
    color: #4b5563;
  }}
  #{viewer_id} .toolbar-spacer {{
    flex: 1 1 24px;
  }}
  #{viewer_id} .zoom-controls {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }}
  #{viewer_id} .zoom-label {{
    margin-right: 2px;
    color: #4b5563;
    font-size: 12px;
  }}
  #{viewer_id} .zoom-controls button {{
    min-width: 31px;
    padding-inline: 7px;
  }}
  #{viewer_id} .zoom-controls button[class$="-reset"] {{
    min-width: 52px;
  }}
  #{viewer_id} .viewer-grid {{
    display: grid;
    grid-template-columns: minmax(360px, 1fr) minmax(320px, {facsimile_max_width}px);
    gap: 14px;
    align-items: start;
  }}
  #{viewer_id} .viewer-grid.is-score-only {{
    grid-template-columns: minmax(0, 1fr);
  }}
  #{viewer_id} .viewer-pane {{
    min-width: 0;
    max-height: {viewer_max_height}px;
    overflow: auto;
    scrollbar-gutter: stable;
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    background: white;
  }}
  #{viewer_id} .score-pane {{
    padding: 8px;
  }}
  #{viewer_id} .score-page {{
    display: none;
  }}
  #{viewer_id} .score-page.is-active {{
    display: block;
  }}
  #{viewer_id} .score-pane svg {{
    width: var(--score-zoom);
    max-width: none;
    height: auto;
  }}
  #{viewer_id} .facsimile-wrap {{
    position: relative;
    width: var(--facsimile-zoom);
    line-height: 0;
  }}
  #{viewer_id} .facsimile-page {{
    display: none;
  }}
  #{viewer_id} .facsimile-page.is-active {{
    display: block;
  }}
  #{viewer_id} .facsimile-page-label {{
    color: #4b5563;
    font-size: 13px;
  }}
  #{viewer_id} .facsimile-wrap img {{
    display: block;
    width: 100%;
    height: auto;
  }}
  #{viewer_id} .zone-layer {{
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }}
  #{viewer_id} .zone {{
    fill: rgba(37, 99, 235, {zone_opacity});
    stroke: rgba(37, 99, 235, 0.8);
    stroke-width: 2;
    vector-effect: non-scaling-stroke;
    cursor: pointer;
  }}
  #{viewer_id} .zone.is-active {{
    fill: rgba(245, 158, 11, 0.32);
    stroke: var(--active);
    stroke-width: 4;
  }}
  #{viewer_id} .score-pane .measure {{
    cursor: pointer;
  }}
  #{viewer_id} .score-pane .measure.is-active,
  #{viewer_id} .score-pane .measure.is-active * {{
    fill: var(--active) !important;
    stroke: var(--active) !important;
  }}
  #{viewer_id} .mei-viewer-details {{
    margin-top: 14px;
    font-size: 13px;
  }}
  #{viewer_id} .mei-viewer-table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 8px;
  }}
  #{viewer_id} .mei-viewer-table th,
  #{viewer_id} .mei-viewer-table td {{
    border: 1px solid var(--panel-border);
    padding: 4px 6px;
    text-align: left;
    vertical-align: top;
  }}
  #{viewer_id} .mei-viewer-table th {{
    background: #eef2f7;
  }}
  @media (max-width: 900px) {{
    #{viewer_id} .viewer-grid {{
      grid-template-columns: 1fr;
    }}
  }}
</style>
<div id="{viewer_id}" class="mei-viewer">
  <div class="viewer-status" aria-live="polite">{viewer_status}</div>
  <div class="score-toolbar" aria-label="Rendered score page controls">
    <button type="button" class="score-prev" {disabled_prev}>Previous score page</button>
    <button type="button" class="score-next" {disabled_next}>Next score page</button>
    <span class="score-page-label"></span>
    <span class="facsimile-page-label" aria-live="polite"></span>
    <span class="toolbar-spacer"></span>
    <div class="zoom-controls" aria-label="Score zoom controls">
      <span class="zoom-label">Score zoom</span>
      <button type="button" class="score-zoom-out" title="Zoom score out">−</button>
      <button type="button" class="score-zoom-reset" title="Reset score zoom">{initial_score_zoom_percent:g}%</button>
      <button type="button" class="score-zoom-in" title="Zoom score in">+</button>
    </div>
    {facsimile_zoom_controls}
  </div>
  <div class="{grid_class}">
    <div class="viewer-pane score-pane" aria-label="Rendered MEI score">
      {''.join(score_page_html)}
    </div>
    {facsimile_panel}
  </div>
  {table_html}
</div>
<script>
(() => {{
  const viewerId = {json.dumps(viewer_id)};
  let initializationAttempts = 0;

  function initializeViewer() {{
    const root = document.getElementById(viewerId);
    if (!root) {{
      initializationAttempts += 1;
      if (initializationAttempts < 50) window.setTimeout(initializeViewer, 20);
      return;
    }}
    if (root.dataset.camatViewerInitialized === 'true') return;
    root.dataset.camatViewerInitialized = 'true';

  const pairs = {pairs_json};
  const scorePages = {score_pages_json};
  const scorePageSurfaces = {score_page_surfaces_json};
  const totalScorePages = {total_score_pages};
  const totalSurfaces = {len(surfaces)};
  const initialScoreZoom = {initial_score_zoom_percent};
  const initialFacsimileZoom = {initial_facsimile_zoom_percent};
  const zoomStep = {zoom_step_percent};
  const minZoom = {min_zoom_percent};
  const maxZoom = {max_zoom_percent};
  const status = root.querySelector('.viewer-status');
  const pageLabel = root.querySelector('.score-page-label');
  const surfaceLabel = root.querySelector('.facsimile-page-label');
  const prevButton = root.querySelector('.score-prev');
  const nextButton = root.querySelector('.score-next');
  const scoreZoomOut = root.querySelector('.score-zoom-out');
  const scoreZoomReset = root.querySelector('.score-zoom-reset');
  const scoreZoomIn = root.querySelector('.score-zoom-in');
  const facsimileZoomOut = root.querySelector('.facsimile-zoom-out');
  const facsimileZoomReset = root.querySelector('.facsimile-zoom-reset');
  const facsimileZoomIn = root.querySelector('.facsimile-zoom-in');
  const byMeasure = new Map(pairs.map((item) => [item.measureId, item]));
  const byZone = new Map(pairs.map((item) => [item.zoneId, item]));
  const initialPageIndex = {initial_page_index};
  let activePageIndex = initialPageIndex;
  let activeSurfaceIndex = {initial_surface_index};
  let scoreZoom = initialScoreZoom;
  let facsimileZoom = initialFacsimileZoom;

  function clampZoom(value) {{
    return Math.min(maxZoom, Math.max(minZoom, value));
  }}

  function applyScoreZoom(value) {{
    scoreZoom = clampZoom(value);
    root.style.setProperty('--score-zoom', `${{scoreZoom}}%`);
    scoreZoomReset.textContent = `${{Math.round(scoreZoom)}}%`;
    scoreZoomOut.disabled = scoreZoom <= minZoom;
    scoreZoomIn.disabled = scoreZoom >= maxZoom;
  }}

  function applyFacsimileZoom(value) {{
    if (!facsimileZoomReset) return;
    facsimileZoom = clampZoom(value);
    root.style.setProperty('--facsimile-zoom', `${{facsimileZoom}}%`);
    facsimileZoomReset.textContent = `${{Math.round(facsimileZoom)}}%`;
    facsimileZoomOut.disabled = facsimileZoom <= minZoom;
    facsimileZoomIn.disabled = facsimileZoom >= maxZoom;
  }}

  function showFacsimileSurface(index) {{
    if (index === null || index === undefined || index < 0 || index >= totalSurfaces) return;
    const nextSurface = root.querySelector(`.facsimile-page[data-surface-index="${{index}}"]`);
    if (!nextSurface) return;
    if (!nextSurface.classList.contains('is-active')) {{
      root.querySelectorAll('.facsimile-page').forEach((surface) => {{
        surface.classList.toggle('is-active', surface === nextSurface);
      }});
    }}
    activeSurfaceIndex = index;
    const image = nextSurface.querySelector('img[data-src]');
    if (image && !image.getAttribute('src')) image.setAttribute('src', image.dataset.src);
    if (surfaceLabel) {{
      const surfaceN = nextSurface.dataset.surfaceN || String(activeSurfaceIndex + 1);
      surfaceLabel.textContent = `Facsimile surface ${{surfaceN}} (${{activeSurfaceIndex + 1}} of ${{totalSurfaces}})`;
    }}
  }}

  function showScorePage(index) {{
    if (index < 0 || index >= scorePages.length) return;
    const pageChanged = index !== activePageIndex || !root.querySelector('.score-page.is-active');
    activePageIndex = index;
    if (pageChanged) {{
      root.querySelectorAll('.score-page').forEach((page, pageIndex) => {{
        page.classList.toggle('is-active', pageIndex === activePageIndex);
      }});
    }}
    prevButton.disabled = activePageIndex === 0;
    nextButton.disabled = activePageIndex === scorePages.length - 1;
    pageLabel.textContent = `Rendered score page ${{scorePages[activePageIndex]}} of ${{totalScorePages}}`;
    showFacsimileSurface(scorePageSurfaces[activePageIndex]);
  }}

  function clearActive() {{
    root.querySelectorAll('.is-active.measure, .zone.is-active').forEach((node) => node.classList.remove('is-active'));
  }}

  function activate(item, scrollScore = false) {{
    if (!item) return;
    if (item.pageIndex !== null && item.pageIndex !== undefined) showScorePage(item.pageIndex);
    showFacsimileSurface(item.surfaceIndex);
    clearActive();
    const activePage = root.querySelector('.score-page.is-active');
    const measure = activePage ? activePage.querySelector(`#${{CSS.escape(item.measureId)}}`) : null;
    const zone = root.querySelector(`.zone[data-zone-id="${{CSS.escape(item.zoneId)}}"]`);
    if (measure) {{
      measure.classList.add('is-active');
      if (scrollScore) measure.scrollIntoView({{block: 'center', inline: 'center', behavior: 'smooth'}});
    }}
    if (zone) zone.classList.add('is-active');
    const scorePageText = item.scorePage ? ` | score page ${{item.scorePage}}` : ' | not in rendered score output';
    status.textContent = `Measure ${{item.measureN || '(unnumbered)'}} | ${{item.measureId}} | ${{item.zoneId}}${{scorePageText}}`;
  }}

  prevButton.addEventListener('click', () => showScorePage(activePageIndex - 1));
  nextButton.addEventListener('click', () => showScorePage(activePageIndex + 1));
  scoreZoomOut.addEventListener('click', () => applyScoreZoom(scoreZoom - zoomStep));
  scoreZoomReset.addEventListener('click', () => applyScoreZoom(initialScoreZoom));
  scoreZoomIn.addEventListener('click', () => applyScoreZoom(scoreZoom + zoomStep));
  if (facsimileZoomReset) {{
    facsimileZoomOut.addEventListener('click', () => applyFacsimileZoom(facsimileZoom - zoomStep));
    facsimileZoomReset.addEventListener('click', () => applyFacsimileZoom(initialFacsimileZoom));
    facsimileZoomIn.addEventListener('click', () => applyFacsimileZoom(facsimileZoom + zoomStep));
  }}

  root.querySelectorAll('.score-pane .measure[id]').forEach((measure) => {{
    const item = byMeasure.get(measure.id);
    if (!item) return;
    measure.addEventListener('mouseenter', () => activate(item));
    measure.addEventListener('click', () => activate(item));
  }});

  root.querySelectorAll('.zone').forEach((zone) => {{
    const item = byZone.get(zone.dataset.zoneId);
    if (!item) return;
    zone.addEventListener('mouseenter', () => activate(item));
    zone.addEventListener('click', () => activate(item, true));
  }});

  applyScoreZoom(initialScoreZoom);
  applyFacsimileZoom(initialFacsimileZoom);
  showScorePage(initialPageIndex);
  const initialItem = pairs.find((item) => item.pageIndex === initialPageIndex) || pairs[0];
  if (initialItem) activate(initialItem);
  }}

  // Notebook frontends can evaluate an HTML output's script before its root
  // element has been attached to the live DOM. Defer and retry initialization
  // so page controls also work on the first render, not only after reload.
  window.setTimeout(initializeViewer, 0);
}})();
</script>
"""


def mei_file_fingerprint(path: Path | None) -> tuple[int, int] | None:
    """Return a cheap (mtime_ns, size) fingerprint for change detection."""
    if path is None:
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def probe_note_pname(path: Path, note_xml_id: str) -> str:
    """Read @pname for a note xml:id from disk (debug aid for watch status)."""
    pattern = re.compile(
        rf'xml:id="{re.escape(note_xml_id)}"[^>]*\bpname="([^"]+)"'
    )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"read-error:{exc}"
    match = pattern.search(text)
    return match.group(1) if match else "(note not found)"


class InteractiveFacsimileViewer:
    """Jupyter MEI viewer with facsimile linking and a score-only fallback."""

    def __init__(
        self,
        mei_path: str | Path,
        *,
        repo_root: Path | None = None,
        viewer_id: str | None = None,
        verovio_initial_page: int = 1,
        verovio_orientation: str = "portrait",
        verovio_portrait_size: tuple[int, int] = DEFAULT_PORTRAIT_SIZE,
        verovio_landscape_size: tuple[int, int] = DEFAULT_LANDSCAPE_SIZE,
        verovio_breaks: str = "encoded",
        verovio_adjust_page_height: bool = True,
        verovio_options: dict | None = None,
        viewer_max_height: int = 820,
        facsimile_max_width: int = 600,
        zone_opacity: float = 0.18,
        initial_score_zoom_percent: int | float = 100,
        initial_facsimile_zoom_percent: int | float = 100,
        zoom_step_percent: int | float = 25,
        min_zoom_percent: int | float = 50,
        max_zoom_percent: int | float = 300,
        show_diagnostic_table: bool = True,
        show_verovio_warnings: bool = False,
        allow_missing_facsimile: bool = True,
        auto_watch_mei: bool = True,
        auto_watch_mode: str = "events",
        watch_interval_sec: float = 2.0,
        watch_settle_sec: float = 0.35,
        watch_debounce_sec: float = 0.4,
        note_probe_id: str | None = None,
    ) -> None:
        self.repo_root = (repo_root or find_camat_root()).resolve()
        self.mei_path = resolve_mei_source(mei_path, repo_root=self.repo_root)
        self.viewer_id = viewer_id or f"mei-viewer-live-{uuid.uuid4().hex}"
        self.verovio_initial_page = verovio_initial_page
        self.verovio_orientation = verovio_orientation
        self.verovio_portrait_size = verovio_portrait_size
        self.verovio_landscape_size = verovio_landscape_size
        self.verovio_breaks = verovio_breaks
        self.verovio_adjust_page_height = verovio_adjust_page_height
        self.verovio_options = dict(verovio_options or {})
        self.viewer_max_height = viewer_max_height
        self.facsimile_max_width = facsimile_max_width
        self.zone_opacity = zone_opacity
        self.initial_score_zoom_percent = initial_score_zoom_percent
        self.initial_facsimile_zoom_percent = initial_facsimile_zoom_percent
        self.zoom_step_percent = zoom_step_percent
        self.min_zoom_percent = min_zoom_percent
        self.max_zoom_percent = max_zoom_percent
        self.show_diagnostic_table = show_diagnostic_table
        self.show_verovio_warnings = show_verovio_warnings
        self.allow_missing_facsimile = allow_missing_facsimile
        self.auto_watch_mei = auto_watch_mei
        self.auto_watch_mode = auto_watch_mode
        self.watch_interval_sec = watch_interval_sec
        self.watch_settle_sec = watch_settle_sec
        self.watch_debounce_sec = watch_debounce_sec
        self.note_probe_id = note_probe_id

        self.cache = FacsimileViewerCache()
        self._widgets: Any = None
        self._get_ipython: Callable | None = None
        self._HTML: Any = None
        self._clear_output: Any = None
        self._display: Any = None

        self.status_output = None
        self.viewer_output = None
        self.watch_status = None
        self.reload_zones_btn = None
        self.reload_score_btn = None
        self.watch_toggle = None

        self._watch_state: dict[str, Any] = {
            "path": None,
            "callback": None,
            "observer": None,
            "reloading": False,
            "pending": False,
            "debounce_timer": None,
            "ignore_until": 0.0,
            "file_fp": None,
            "last_checked": None,
            "last_reloaded": None,
        }

    def _require_jupyter(self) -> None:
        if self._widgets is not None:
            return
        try:
            import ipywidgets as widgets
            from IPython import get_ipython
            from IPython.display import HTML, clear_output, display
        except ImportError as exc:
            raise ImportError(
                "InteractiveFacsimileViewer requires ipywidgets and IPython"
            ) from exc
        self._widgets = widgets
        self._get_ipython = get_ipython
        self._HTML = HTML
        self._clear_output = clear_output
        self._display = display

    def _verovio_options(self) -> dict:
        return build_verovio_options(
            self.verovio_options,
            orientation=self.verovio_orientation,
            breaks=self.verovio_breaks,
            adjust_page_height=self.verovio_adjust_page_height,
            portrait_size=self.verovio_portrait_size,
            landscape_size=self.verovio_landscape_size,
        )

    def _probe_note_pname(self, path: Path | None) -> str:
        if path is None or not self.note_probe_id:
            return "—"
        return probe_note_pname(path, self.note_probe_id)

    def _build_viewer(self, *, render_score: bool | str = "auto") -> dict:
        result = build_facsimile_viewer(
            self.mei_path,
            verovio_options=self._verovio_options(),
            initial_page=self.verovio_initial_page,
            render_score=render_score,
            cache=self.cache,
            repo_root=self.repo_root,
            viewer_id=self.viewer_id,
            viewer_max_height=self.viewer_max_height,
            facsimile_max_width=self.facsimile_max_width,
            zone_opacity=self.zone_opacity,
            initial_score_zoom_percent=self.initial_score_zoom_percent,
            initial_facsimile_zoom_percent=self.initial_facsimile_zoom_percent,
            zoom_step_percent=self.zoom_step_percent,
            min_zoom_percent=self.min_zoom_percent,
            max_zoom_percent=self.max_zoom_percent,
            show_diagnostic_table=self.show_diagnostic_table,
            show_verovio_warnings=self.show_verovio_warnings,
            allow_missing_facsimile=self.allow_missing_facsimile,
        )
        self.cache = result["cache"]
        return result

    def _show_viewer_result(self, result: dict) -> None:
        score_render = result["score_render"]
        if self.reload_zones_btn is not None:
            self.reload_zones_btn.description = (
                "Reload zones" if result["model"]["has_facsimile"] else "Check facsimile"
            )
        render_note = "re-rendered score" if result["rendered_score"] else "reused cached score"
        with self.status_output:
            self._clear_output(wait=True)
            print(result["summary"])
            print(
                f"Viewer:          {score_render['page_count']} Verovio score page(s), {render_note}"
            )
        with self.viewer_output:
            self._clear_output(wait=True)
            self._display(self._HTML(result["html"]))

    def refresh_viewer(self, *, render_score: bool | str = "auto") -> dict:
        result = self._build_viewer(render_score=render_score)
        self._show_viewer_result(result)
        return result

    def _set_watch_status(self, text: str) -> None:
        self.watch_status.value = text

    def _format_always_status(self, *, reloading: bool = False) -> str:
        path = self._watch_state["path"]
        checked = self._watch_state["last_checked"] or "—"
        reloaded = self._watch_state["last_reloaded"] or "—"
        state = "reloading…" if reloading else f"checked {checked}"
        return (
            f"Always · every {self.watch_interval_sec:g}s · {state} · "
            f"last reload {reloaded} · "
            f"<code>{path.name if path else '?'}</code>"
        )

    def _schedule_on_kernel(self, fn: Callable) -> None:
        ip = self._get_ipython() if self._get_ipython is not None else None
        if ip is not None and hasattr(ip, "kernel"):
            ip.kernel.io_loop.add_callback(fn)
        else:
            fn()

    def _reload_from_watch(self, reason: str, *, quiet: bool = False) -> None:
        if not self.watch_toggle.value:
            return
        if self._watch_state["reloading"]:
            self._watch_state["pending"] = True
            return

        path = self._watch_state["path"]
        self._watch_state["reloading"] = True
        self._watch_state["pending"] = False
        if quiet:
            self._set_watch_status(self._format_always_status(reloading=True))
        else:
            pname = self._probe_note_pname(path)
            probe = (
                f" · on-disk <code>{self.note_probe_id}</code> pname=<code>{pname}</code>"
                if self.note_probe_id
                else ""
            )
            self._set_watch_status(f"<b>Reloading</b> ({reason}){probe}…")
        try:
            time.sleep(self.watch_settle_sec)
            result = self.refresh_viewer(render_score=True)
            self._watch_state["ignore_until"] = time.monotonic() + 1.0
            when = time.strftime("%H:%M:%S")
            self._watch_state["file_fp"] = mei_file_fingerprint(path)
            self._watch_state["last_checked"] = when
            self._watch_state["last_reloaded"] = when
            if quiet:
                self._set_watch_status(self._format_always_status())
            else:
                pname = self._probe_note_pname(path)
                render_note = (
                    "re-rendered score" if result["rendered_score"] else "reused cached score"
                )
                probe = (
                    f" · on-disk <code>{self.note_probe_id}</code> pname=<code>{pname}</code>"
                    if self.note_probe_id
                    else ""
                )
                self._set_watch_status(
                    f"<b style='color:#047857'>Reloaded</b> at {when} ({render_note}) · "
                    f"trigger=<code>{reason}</code>{probe} · "
                    f"mode=<code>{self.auto_watch_mode}</code>"
                )
        except Exception as exc:
            self._set_watch_status(f"<b style='color:#b91c1c'>Reload failed:</b> {exc}")
        finally:
            self._watch_state["reloading"] = False
            if self._watch_state["pending"] and self.watch_toggle.value:
                self._watch_state["pending"] = False
                self._schedule_on_kernel(lambda: self._reload_from_watch("queued-change"))

    def _request_reload(self, reason: str) -> None:
        if not self.watch_toggle.value:
            return
        if time.monotonic() < self._watch_state["ignore_until"]:
            return

        timer = self._watch_state.get("debounce_timer")
        if timer is not None:
            timer.cancel()

        def _fire(r=reason):
            self._schedule_on_kernel(lambda rr=r: self._reload_from_watch(rr))

        timer = threading.Timer(self.watch_debounce_sec, _fire)
        timer.daemon = True
        self._watch_state["debounce_timer"] = timer
        timer.start()

    def _poll_always(self) -> None:
        if not self.watch_toggle.value:
            return
        if self._watch_state["reloading"]:
            return

        path = self._watch_state["path"]
        fp = mei_file_fingerprint(path)
        self._watch_state["last_checked"] = time.strftime("%H:%M:%S")

        if fp is None:
            self._set_watch_status(f"<b style='color:#b91c1c'>Missing file:</b> {path}")
            return

        if self._watch_state["file_fp"] is None:
            self._watch_state["file_fp"] = fp

        if fp != self._watch_state["file_fp"]:
            self._reload_from_watch("periodic", quiet=True)
            return

        self._set_watch_status(self._format_always_status())

    def _start_watch_always(self) -> None:
        from tornado.ioloop import PeriodicCallback

        path = self._watch_state["path"]
        self._watch_state["file_fp"] = mei_file_fingerprint(path)
        self._watch_state["last_checked"] = time.strftime("%H:%M:%S")
        if self._watch_state["last_reloaded"] is None:
            self._watch_state["last_reloaded"] = self._watch_state["last_checked"]

        callback = PeriodicCallback(self._poll_always, int(self.watch_interval_sec * 1000))
        self._watch_state["callback"] = callback
        callback.start()
        self._set_watch_status(self._format_always_status())

    @staticmethod
    def _paths_match_target(candidate: str | None, target: Path) -> bool:
        if not candidate:
            return False
        try:
            return Path(candidate).resolve() == target
        except OSError:
            return Path(candidate).name == target.name

    def _start_watch_events(self) -> bool:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            self._set_watch_status(
                "<b style='color:#b45309'>watchdog not installed in this kernel</b> — "
                "run <code>pip install watchdog</code>, then re-run this cell. "
                "Falling back to always mode."
            )
            return False

        path = self._watch_state["path"]
        target_name = path.name
        viewer = self

        class Handler(FileSystemEventHandler):
            def on_moved(self, event):
                if event.is_directory:
                    return
                if viewer._paths_match_target(getattr(event, "dest_path", None), path):
                    viewer._request_reload("moved")

            def on_created(self, event):
                if event.is_directory:
                    return
                if viewer._paths_match_target(event.src_path, path):
                    viewer._request_reload("created")

            def on_modified(self, event):
                if event.is_directory:
                    return
                if viewer._paths_match_target(event.src_path, path):
                    viewer._request_reload("modified")

            def on_closed(self, event):
                if getattr(event, "is_directory", False):
                    return
                if viewer._paths_match_target(getattr(event, "src_path", None), path):
                    viewer._request_reload("closed")

        observer = Observer()
        observer.schedule(Handler(), str(path.parent), recursive=False)
        observer.daemon = True
        observer.start()
        self._watch_state["observer"] = observer
        self._watch_state["ignore_until"] = time.monotonic() + 1.0
        if self.note_probe_id:
            pname = self._probe_note_pname(path)
            probe = (
                f" · on-disk <code>{self.note_probe_id}</code> pname=<code>{pname}</code> · "
            )
        else:
            probe = " · "
        self._set_watch_status(
            f"Events mode (inotify) on <code>{target_name}</code>{probe}"
            f"save the MEI to reload"
        )
        return True

    def start_watch(self) -> None:
        self.stop_watch(update_label=False)
        path = resolve_repo_path(self.mei_path, repo_root=self.repo_root)
        self._watch_state["path"] = path
        self._watch_state["reloading"] = False
        self._watch_state["pending"] = False
        self._watch_state["file_fp"] = None
        self._watch_state["last_checked"] = None
        self._watch_state["last_reloaded"] = None

        if not path.is_file():
            self._set_watch_status(f"<b style='color:#b91c1c'>Missing file:</b> {path}")
            self.watch_toggle.value = False
            return

        mode = str(self.auto_watch_mode).lower().strip()
        if mode == "events":
            if not self._start_watch_events():
                self._start_watch_always()
        elif mode == "always":
            self._start_watch_always()
        else:
            self._set_watch_status(
                f"<b style='color:#b91c1c'>Unknown auto_watch_mode={self.auto_watch_mode!r}</b> "
                "(use 'events' or 'always')"
            )
            self.watch_toggle.value = False

    def stop_watch(self, *, update_label: bool = True) -> None:
        callback = self._watch_state.get("callback")
        if callback is not None:
            callback.stop()
            self._watch_state["callback"] = None
        timer = self._watch_state.get("debounce_timer")
        if timer is not None:
            timer.cancel()
            self._watch_state["debounce_timer"] = None
        observer = self._watch_state.get("observer")
        if observer is not None:
            observer.stop()
            observer.join(timeout=2)
            self._watch_state["observer"] = None
        self._watch_state["reloading"] = False
        self._watch_state["pending"] = False
        if update_label:
            self._set_watch_status("<i>Auto-watch off</i>")

    def display(self) -> InteractiveFacsimileViewer:
        """Create controls, render once, and optionally start auto-watch."""
        self._require_jupyter()
        widgets = self._widgets

        self.status_output = widgets.Output()
        self.viewer_output = widgets.Output()
        self.watch_status = widgets.HTML(value="<i>Auto-watch off</i>")
        self.reload_zones_btn = widgets.Button(description="Reload zones", icon="refresh")
        self.reload_score_btn = widgets.Button(description="Reload score", icon="sync")
        self.watch_toggle = widgets.ToggleButton(
            description="Auto-watch MEI", value=self.auto_watch_mei
        )

        controls = widgets.HBox(
            [self.reload_zones_btn, self.reload_score_btn, self.watch_toggle]
        )
        self._display(controls, self.watch_status, self.status_output, self.viewer_output)

        self.reload_zones_btn.on_click(lambda _: self.refresh_viewer(render_score=False))
        self.reload_score_btn.on_click(lambda _: self.refresh_viewer(render_score=True))

        def _on_watch_toggle(change) -> None:
            if change["new"]:
                self.start_watch()
            else:
                self.stop_watch()

        self.watch_toggle.observe(_on_watch_toggle, names="value")

        self.refresh_viewer(render_score=True)
        if self.watch_toggle.value:
            self.start_watch()
        else:
            self.stop_watch()
        return self


def launch_interactive_facsimile_viewer(
    mei_path: str | Path,
    **kwargs: Any,
) -> InteractiveFacsimileViewer:
    """Construct and display a Jupyter viewer for a local MEI path or HTTP(S) link."""
    return InteractiveFacsimileViewer(mei_path, **kwargs).display()
