"""Render linked MEI notation and facsimile measure zones side by side.

Pure helpers parse MEI, render Verovio SVG pages, and return HTML. The
:class:`InteractiveFacsimileViewer` and
:func:`launch_interactive_facsimile_viewer` entry points add Jupyter controls
and optional MEI file watching. The viewer accepts a local MEI path, ``file://``
URI, or HTTP(S) link: files with facsimile surfaces, measure zones, and matching measure
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
import os
from pathlib import Path, PureWindowsPath
import re
import threading
import time
from typing import Any, Callable
from urllib.parse import unquote, urljoin, urlparse
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
    "ResolvedMeiSource",
    "apply_facsimile_layout",
    "build_facsimile_viewer",
    "build_verovio_options",
    "display_path",
    "find_camat_root",
    "format_facsimile_summary",
    "launch_interactive_facsimile_viewer",
    "make_diagnostic_table",
    "make_viewer_html",
    "embed_viewer_html",
    "mei_file_fingerprint",
    "infer_facsimile_layout",
    "probe_note_pname",
    "read_facsimile_model",
    "render_verovio_pages",
    "resolve_graphic_src",
    "resolve_mei_source",
    "resolve_mei_source_info",
    "resolve_repo_path",
    "score_content_hash",
    "verovio_options_hash",
]


class FacsimileUnavailableError(RuntimeError):
    """Raised when an MEI has no usable facsimile surface to inspect."""


@dataclass(frozen=True)
class ResolvedMeiSource:
    """A local MEI path together with the provenance needed by the viewer."""

    original: str
    kind: str
    local_path: Path
    base_uri: str | None = None


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


def _is_windows_absolute_path(source: str) -> bool:
    """Return whether ``source`` is a Windows drive or UNC absolute path."""
    return PureWindowsPath(source).is_absolute()


def _path_from_file_uri(source: str) -> Path:
    parsed = urlparse(source)
    if parsed.scheme.lower() != "file":
        raise ValueError(f"Not a file URI: {source}")

    path_text = unquote(parsed.path)
    if os.name == "nt":
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            path_text = f"//{parsed.netloc}{path_text}"
        elif re.match(r"^/[A-Za-z]:/", path_text):
            path_text = path_text[1:]
    elif parsed.netloc and parsed.netloc.lower() != "localhost":
        path_text = f"//{parsed.netloc}{path_text}"
    return Path(path_text)


def resolve_mei_source_info(
    source: str | Path | ResolvedMeiSource,
    *,
    repo_root: Path | None = None,
    cache_dir: str | Path | None = None,
    timeout_seconds: int = 60,
    refresh_remote: bool = False,
    fetch: bool = True,
    shared_cache: bool = False,
) -> ResolvedMeiSource | None:
    """Resolve an MEI source while retaining its local or remote provenance.

    Parameters
    ----------
    fetch :
        When False, a remote URL that is not already cached returns ``None``
        instead of downloading. Local paths are unaffected.
    shared_cache :
        When True and ``cache_dir`` is omitted, use CAMAT's shared download
        cache (``~/.cache/camat/downloads``), the same location ``parse_files``
        uses with ``use_remote_cache=True``.
    """
    if isinstance(source, ResolvedMeiSource):
        return source

    root = (repo_root or find_camat_root()).resolve()
    source_text = str(source).strip()
    parsed = urlparse(source_text)
    scheme = parsed.scheme.lower()

    if scheme in {"http", "https"}:
        from .music_utils import (
            _cached_download_filename,
            get_download_cache_dir,
            get_file_path,
            to_direct_download_url,
        )

        if cache_dir is not None:
            resolved_cache = Path(cache_dir)
        elif shared_cache:
            resolved_cache = Path(get_download_cache_dir())
        else:
            resolved_cache = _default_mei_cache_dir(root)
        direct_url = to_direct_download_url(source_text)
        cached_path = (resolved_cache / _cached_download_filename(direct_url)).resolve()
        if (
            not refresh_remote
            and cached_path.is_file()
            and cached_path.stat().st_size > 0
        ):
            local_path = cached_path
        elif not fetch:
            return None
        else:
            local_path = Path(
                get_file_path(
                    source_text,
                    timeout_seconds=timeout_seconds,
                    use_cache=True,
                    cache_dir=str(resolved_cache),
                    force_refresh=refresh_remote,
                )
            ).resolve()
        return ResolvedMeiSource(
            original=source_text,
            kind="remote",
            local_path=local_path,
            base_uri=direct_url,
        )

    if scheme == "file":
        local_path = _path_from_file_uri(source_text).expanduser().resolve()
        kind = "file-uri"
    else:
        if _is_windows_absolute_path(source_text) and os.name != "nt":
            raise FileNotFoundError(
                f"Windows path {source_text!r} cannot be opened on this {os.name} host. "
                "Mount the drive/share locally or use an HTTP(S) URL."
            )
        local_path = resolve_repo_path(source, repo_root=root)
        kind = "local"

    if not local_path.is_file():
        raise FileNotFoundError(f"No MEI file at {local_path}")
    return ResolvedMeiSource(
        original=source_text,
        kind=kind,
        local_path=local_path,
        base_uri=local_path.parent.as_uri() + "/",
    )


def resolve_mei_source(
    source: str | Path | ResolvedMeiSource,
    *,
    repo_root: Path | None = None,
    cache_dir: str | Path | None = None,
    timeout_seconds: int = 60,
    refresh_remote: bool = False,
    fetch: bool = True,
    shared_cache: bool = False,
) -> Path | None:
    """Return a local MEI path from a local file, file URI, or HTTP(S) link.

    GitHub ``blob`` pages are converted to raw-file URLs. Remote files are
    cached under ``converted_mei/facsimile_viewer_sources/`` when this is a
    CAMAT checkout, otherwise under the shared CAMAT download cache. Pass
    ``shared_cache=True`` to force the shared download cache used by
    ``parse_files``. With ``fetch=False``, a remote URL that is not already
    cached returns ``None`` instead of downloading.
    """
    info = resolve_mei_source_info(
        source,
        repo_root=repo_root,
        cache_dir=cache_dir,
        timeout_seconds=timeout_seconds,
        refresh_remote=refresh_remote,
        fetch=fetch,
        shared_cache=shared_cache,
    )
    return None if info is None else info.local_path


def parse_int_attr(element: ET.Element, attr: str, *, context: str) -> int:
    value = element.get(attr)
    if value is None:
        raise ValueError(f"Missing @{attr} on {context}")
    try:
        return int(round(float(value)))
    except ValueError as exc:
        raise ValueError(f"Invalid @{attr}={value!r} on {context}") from exc


def resolve_graphic_src(
    target: str,
    mei_path: Path,
    *,
    base_uri: str | None = None,
) -> str:
    """Return a browser-usable image source for a graphic target."""
    parsed = urlparse(target)
    if parsed.scheme in {"http", "https", "data"}:
        return target

    if base_uri and urlparse(base_uri).scheme in {"http", "https"}:
        return urljoin(base_uri, target)

    image_path = (
        _path_from_file_uri(target).expanduser()
        if parsed.scheme == "file"
        else Path(target).expanduser()
    )
    if not image_path.is_absolute():
        image_path = mei_path.parent / image_path
    image_path = image_path.resolve()
    if not image_path.is_file():
        return target

    mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    payload = b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _ancestor_named(
    element: ET.Element,
    name: str,
    parent_map: dict[ET.Element, ET.Element],
) -> ET.Element | None:
    current = parent_map.get(element)
    while current is not None:
        if _local_name(current) == name:
            return current
        current = parent_map.get(current)
    return None


def _read_annotation_models(root: ET.Element) -> list[dict]:
    """Read score annotations without relying on Verovio's empty SVG groups."""
    parent_map = {child: parent for parent in root.iter() for child in parent}
    annotations = []
    for index, annotation in enumerate(root.findall(".//m:annot", NS), start=1):
        measure = _ancestor_named(annotation, "measure", parent_map)
        plist = [
            token.lstrip("#")
            for token in (annotation.get("plist") or "").split()
            if token.strip("#")
        ]
        tstamp = (annotation.get("tstamp") or "").strip()
        startid = (annotation.get("startid") or "").lstrip("#")
        if plist:
            anchor_mode = "plist"
            targets = plist
        elif tstamp:
            anchor_mode = "tstamp"
            targets = []
        elif startid:
            anchor_mode = "startid"
            targets = [startid]
        else:
            anchor_mode = "unanchored"
            targets = []

        staff = (annotation.get("staff") or "").split()
        layer = (annotation.get("layer") or "").split()
        staff_ancestor = _ancestor_named(annotation, "staff", parent_map)
        layer_ancestor = _ancestor_named(annotation, "layer", parent_map)
        if not staff and staff_ancestor is not None and staff_ancestor.get("n"):
            staff = [staff_ancestor.get("n") or ""]
        if not layer and layer_ancestor is not None and layer_ancestor.get("n"):
            layer = [layer_ancestor.get("n") or ""]

        text = " ".join(" ".join(annotation.itertext()).split())
        annotations.append(
            {
                "id": annotation.get(XML_ID) or f"annotation-{index}",
                "type": annotation.get("type") or "",
                "func": annotation.get("func") or "",
                "text": text,
                "anchor_mode": anchor_mode,
                "target_ids": targets,
                "measure_id": measure.get(XML_ID) if measure is not None else None,
                "tstamp": tstamp or None,
                "staff": staff,
                "layer": layer,
                "status": "pending",
            }
        )
    return annotations


def _encoded_breaks_before(root: ET.Element) -> tuple[list[dict], list[str]]:
    page_breaks: list[dict] = []
    system_breaks: list[str] = []
    pending_page_breaks: list[ET.Element] = []
    pending_system_break = False
    for element in root.iter():
        name = _local_name(element)
        if name == "pb":
            pending_page_breaks.append(element)
        elif name == "sb":
            pending_system_break = True
        elif name == "measure":
            measure_id = element.get(XML_ID) or ""
            for page_break in pending_page_breaks:
                page_breaks.append(
                    {
                        "measure_id": measure_id,
                        "facs": (page_break.get("facs") or "").lstrip("#"),
                    }
                )
            if pending_system_break and measure_id:
                system_breaks.append(measure_id)
            pending_page_breaks = []
            pending_system_break = False
    return page_breaks, system_breaks


def infer_facsimile_layout(model: dict) -> dict:
    """Compare encoded layout markers with page and system hints from zones."""
    if not model.get("has_facsimile"):
        return {
            "inferred_page_breaks": [],
            "inferred_system_breaks": [],
            "encoded_page_breaks": model.get("encoded_page_breaks", []),
            "encoded_system_breaks": model.get("encoded_system_breaks", []),
            "missing_page_breaks": [],
            "missing_system_breaks": [],
            "alignment_applied": False,
        }

    inferred_page_breaks: list[dict] = []
    inferred_system_breaks: list[str] = []
    rows_by_surface: dict[int, list[dict]] = {}
    for row in model.get("linked", []):
        surface_index = row.get("surface_index")
        if surface_index is None or not row.get("measure_id"):
            continue
        rows_by_surface.setdefault(surface_index, []).append(row)

    for surface_index, rows in rows_by_surface.items():
        first = rows[0]
        inferred_page_breaks.append(
            {
                "measure_id": first["measure_id"],
                "surface_id": first["surface_id"],
                "surface_index": surface_index,
            }
        )
        heights = [
            row["zone"]["lry"] - row["zone"]["uly"]
            for row in rows
            if row.get("zone")
        ]
        if not heights:
            continue
        median_height = sorted(heights)[len(heights) // 2]
        threshold = max(50.0, median_height * 0.45)
        band_centers: list[float] = []
        for row in rows:
            zone = row["zone"]
            center = (zone["uly"] + zone["lry"]) / 2.0
            if not band_centers:
                band_centers.append(center)
                continue
            band_center = sum(band_centers) / len(band_centers)
            if abs(center - band_center) > threshold:
                inferred_system_breaks.append(row["measure_id"])
                band_centers = [center]
            else:
                band_centers.append(center)

    encoded_page_breaks = model.get("encoded_page_breaks", [])
    encoded_system_breaks = model.get("encoded_system_breaks", [])
    encoded_page_pairs = {
        (row.get("measure_id"), row.get("facs")) for row in encoded_page_breaks
    }
    encoded_system_ids = set(encoded_system_breaks)
    missing_page_breaks = [
        row
        for row in inferred_page_breaks
        if (row["measure_id"], row["surface_id"]) not in encoded_page_pairs
    ]
    missing_system_breaks = [
        measure_id
        for measure_id in inferred_system_breaks
        if measure_id not in encoded_system_ids
    ]
    return {
        "inferred_page_breaks": inferred_page_breaks,
        "inferred_system_breaks": inferred_system_breaks,
        "encoded_page_breaks": encoded_page_breaks,
        "encoded_system_breaks": encoded_system_breaks,
        "missing_page_breaks": missing_page_breaks,
        "missing_system_breaks": missing_system_breaks,
        "alignment_applied": False,
    }


def apply_facsimile_layout(mei_text: str, model: dict) -> tuple[str, dict]:
    """Inject missing facsimile-derived breaks into a temporary MEI document."""
    layout = dict(model.get("layout") or infer_facsimile_layout(model))
    root = ET.fromstring(mei_text)
    parent_map = {child: parent for parent in root.iter() for child in parent}
    measures = {
        element.get(XML_ID): element
        for element in root.findall(".//m:measure", NS)
        if element.get(XML_ID)
    }
    rows_by_id = {row["measure_id"]: row for row in model.get("linked", [])}

    # Existing encoded markers remain authoritative. Only surfaces without an
    # encoded marker receive inferred temporary markers.
    encoded_page_surfaces = {
        row.get("facs") or rows_by_id.get(row.get("measure_id"), {}).get("surface_id")
        for row in layout["encoded_page_breaks"]
    }
    encoded_page_surfaces.discard(None)
    encoded_system_surfaces = {
        rows_by_id[measure_id].get("surface_id")
        for measure_id in layout["encoded_system_breaks"]
        if measure_id in rows_by_id
    }
    page_targets = [
        row
        for row in layout["missing_page_breaks"]
        if row["surface_id"] not in encoded_page_surfaces
    ]
    system_targets = [
        measure_id
        for measure_id in layout["missing_system_breaks"]
        if rows_by_id.get(measure_id, {}).get("surface_id")
        not in encoded_system_surfaces
    ]

    insertions: dict[str, list[ET.Element]] = {}
    for index, row in enumerate(page_targets, start=1):
        surface = model["surfaces"][row["surface_index"]]
        insertions.setdefault(row["measure_id"], []).append(
            ET.Element(
                f"{{{MEI_NS}}}pb",
                {
                    XML_ID: f"camat-inferred-pb-{index}",
                    "facs": f"#{row['surface_id']}",
                    "n": str(surface.get("n") or index),
                },
            )
        )
    for index, measure_id in enumerate(system_targets, start=1):
        insertions.setdefault(measure_id, []).append(
            ET.Element(
                f"{{{MEI_NS}}}sb",
                {XML_ID: f"camat-inferred-sb-{index}"},
            )
        )

    for measure_id, markers in insertions.items():
        measure = measures.get(measure_id)
        parent = parent_map.get(measure) if measure is not None else None
        if measure is None or parent is None:
            continue
        position = list(parent).index(measure)
        for marker in markers:
            parent.insert(position, marker)
            position += 1

    ET.register_namespace("", MEI_NS)
    layout["alignment_applied"] = bool(insertions)
    layout["applied_page_breaks"] = [row["measure_id"] for row in page_targets]
    layout["applied_system_breaks"] = system_targets
    return ET.tostring(root, encoding="unicode"), layout


def read_facsimile_model(
    mei_path: str | Path | ResolvedMeiSource,
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
    source_info = resolve_mei_source_info(mei_path, repo_root=repo_root)
    mei_path = source_info.local_path
    tree = ET.parse(mei_path)
    root = tree.getroot()
    annotations = _read_annotation_models(root)
    encoded_page_breaks, encoded_system_breaks = _encoded_breaks_before(root)

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
            "source": source_info,
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
            "annotations": annotations,
            "encoded_page_breaks": encoded_page_breaks,
            "encoded_system_breaks": encoded_system_breaks,
            "layout": infer_facsimile_layout(
                {
                    "has_facsimile": False,
                    "encoded_page_breaks": encoded_page_breaks,
                    "encoded_system_breaks": encoded_system_breaks,
                }
            ),
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
                "graphic_src": resolve_graphic_src(
                    graphic_target,
                    mei_path,
                    base_uri=source_info.base_uri,
                ),
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
    model = {
        "mei_path": mei_path,
        "source": source_info,
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
        "annotations": annotations,
        "encoded_page_breaks": encoded_page_breaks,
        "encoded_system_breaks": encoded_system_breaks,
    }
    model["layout"] = infer_facsimile_layout(model)
    return model


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
            f"Facsimile:       unavailable ({model['facsimile_status']})\n"
            f"Annotations:     {len(model.get('annotations', []))}"
        )
    layout = model.get("layout", {})
    alignment_note = (
        "\nLayout:          temporary facsimile alignment applied"
        if layout.get("alignment_applied")
        else (
            f"\nLayout hints:    {len(layout.get('missing_page_breaks', []))} missing <pb>, "
            f"{len(layout.get('missing_system_breaks', []))} missing <sb>"
        )
    )
    return (
        f"MEI:             {display_path(mei_path, repo_root=repo_root)}\n"
        f"Viewer mode:     score + facsimile\n"
        f"Surfaces:        {len(model.get('surfaces', []))}\n"
        f"Measures:        {len(model['measures'])}\n"
        f"Linked zones:    {len(model['linked'])}\n"
        f"Missing @facs:   {len(model['missing_facs'])}\n"
        f"Annotations:     {len(model.get('annotations', []))}"
        f"{alignment_note}"
    )


@dataclass
class FacsimileViewerCache:
    score_hash: str | None = None
    options_hash: str | None = None
    score_render: dict | None = field(default=None)


def build_facsimile_viewer(
    mei_path: str | Path | ResolvedMeiSource,
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
    show_annotations: bool = True,
    annotation_display_limit: int = 300,
    align_to_facsimile: bool = False,
) -> dict:
    """Render linked facsimiles or fall back to a score-only MEI viewer."""
    source_info = resolve_mei_source_info(mei_path, repo_root=repo_root)
    resolved_path = source_info.local_path
    model = read_facsimile_model(
        source_info,
        repo_root=repo_root,
        allow_missing_facsimile=allow_missing_facsimile,
    )
    mei_text = resolved_path.read_text(encoding="utf-8")
    effective_options = dict(verovio_options)
    if align_to_facsimile and model.get("has_facsimile"):
        mei_text, model["layout"] = apply_facsimile_layout(mei_text, model)
        effective_options["breaks"] = "encoded"
    current_score_hash = score_content_hash(resolved_path)
    if align_to_facsimile:
        layout_payload = json.dumps(model.get("layout", {}), sort_keys=True)
        current_score_hash = hashlib.sha256(
            f"{current_score_hash}:{layout_payload}".encode("utf-8")
        ).hexdigest()
    current_options_hash = verovio_options_hash(effective_options)
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
            source_info,
            initial_page=initial_page,
            options=effective_options,
            repo_root=repo_root,
            show_verovio_warnings=show_verovio_warnings,
            mei_text=mei_text,
            annotations=model.get("annotations", []),
        )
        viewer_cache.score_hash = current_score_hash
        viewer_cache.options_hash = current_options_hash
        viewer_cache.score_render = score_render
    else:
        score_render = viewer_cache.score_render

    model["annotations"] = score_render.get("annotations", model.get("annotations", []))

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
        show_annotations=show_annotations,
        annotation_display_limit=annotation_display_limit,
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

    if breaks not in {"auto", "encoded", "line", "smart", "none"}:
        raise ValueError(
            'breaks must be "auto", "encoded", "line", "smart", or "none"'
        )

    options = dict(base_options)
    options["adjustPageHeight"] = adjust_page_height
    options["breaks"] = breaks
    options["pageWidth"] = page_width
    options["pageHeight"] = page_height
    return options


def _element_context(root: ET.Element) -> dict[str, dict[str, str | None]]:
    parent_map = {child: parent for parent in root.iter() for child in parent}
    context = {}
    for element in root.iter():
        element_id = element.get(XML_ID)
        if not element_id:
            continue
        measure = element if _local_name(element) == "measure" else _ancestor_named(
            element, "measure", parent_map
        )
        staff = element if _local_name(element) == "staff" else _ancestor_named(
            element, "staff", parent_map
        )
        layer = element if _local_name(element) == "layer" else _ancestor_named(
            element, "layer", parent_map
        )
        context[element_id] = {
            "measure_id": measure.get(XML_ID) if measure is not None else None,
            "staff": staff.get("n") if staff is not None else None,
            "layer": layer.get("n") if layer is not None else None,
        }
    return context


def _meter_units_by_measure(root: ET.Element) -> dict[str, float]:
    meter_unit = 4.0
    result = {}
    for element in root.iter():
        name = _local_name(element)
        value = None
        if name == "scoreDef":
            value = element.get("meter.unit")
        elif name == "meterSig":
            value = element.get("unit")
        if value:
            try:
                meter_unit = float(value)
            except ValueError:
                pass
        if name == "measure" and element.get(XML_ID):
            result[element.get(XML_ID) or ""] = meter_unit
    return result


def _interpolate_timeline(
    rows: list[dict],
    value: float,
    *,
    input_key: str,
    output_key: str,
) -> float:
    points = sorted(
        (
            (float(row[input_key]), float(row[output_key]))
            for row in rows
            if input_key in row and output_key in row
        ),
        key=lambda item: item[0],
    )
    if not points:
        return value
    if value <= points[0][0]:
        return points[0][1]
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        if value <= right_x:
            if right_x == left_x:
                return right_y
            ratio = (value - left_x) / (right_x - left_x)
            return left_y + ratio * (right_y - left_y)
    if len(points) == 1:
        return points[0][1]
    left_x, left_y = points[-2]
    right_x, right_y = points[-1]
    if right_x == left_x:
        return right_y
    return right_y + (value - right_x) * (right_y - left_y) / (right_x - left_x)


def _resolve_render_annotations(
    annotations: list[dict],
    *,
    root: ET.Element,
    toolkit: Any,
) -> list[dict]:
    if not annotations:
        return []
    context = _element_context(root)
    meter_units = _meter_units_by_measure(root)
    timemap = toolkit.renderToTimemap()
    if isinstance(timemap, str):
        timemap = json.loads(timemap)

    resolved_annotations = []
    for source in annotations:
        annotation = dict(source)
        targets = list(annotation.get("target_ids", []))
        status = "resolved" if targets else "unresolved"
        if annotation.get("anchor_mode") == "tstamp":
            measure_id = annotation.get("measure_id")
            try:
                beat = float(annotation.get("tstamp"))
            except (TypeError, ValueError):
                beat = math.nan
            if measure_id and math.isfinite(beat) and toolkit.getPageWithElement(measure_id):
                measure_start_ms = float(toolkit.getTimeForElement(measure_id))
                measure_start_qstamp = _interpolate_timeline(
                    timemap,
                    measure_start_ms,
                    input_key="tstamp",
                    output_key="qstamp",
                )
                meter_unit = meter_units.get(measure_id, 4.0)
                target_qstamp = measure_start_qstamp + (beat - 1.0) * (4.0 / meter_unit)
                target_ms = _interpolate_timeline(
                    timemap,
                    target_qstamp,
                    input_key="qstamp",
                    output_key="tstamp",
                )
                at_time = toolkit.getElementsAtTime(int(round(target_ms)))
                if isinstance(at_time, str):
                    at_time = json.loads(at_time)
                candidates = [
                    element_id
                    for row in timemap
                    if abs(float(row.get("qstamp", math.inf)) - target_qstamp) < 1e-7
                    for element_id in row.get("on", [])
                ]
                if not candidates:
                    for key in ("notes", "chords", "rests"):
                        candidates.extend(at_time.get(key, []))
                wanted_staff = set(annotation.get("staff", []))
                wanted_layer = set(annotation.get("layer", []))
                targets = [
                    element_id
                    for element_id in candidates
                    if (
                        not wanted_staff
                        or context.get(element_id, {}).get("staff") in wanted_staff
                    )
                    and (
                        not wanted_layer
                        or context.get(element_id, {}).get("layer") in wanted_layer
                    )
                ]
                status = "resolved" if targets else "measure-fallback"
            if not targets and measure_id:
                targets = [measure_id]
        elif not targets and annotation.get("measure_id"):
            targets = [annotation["measure_id"]]
            status = "measure-fallback"

        existing_targets = [
            element_id
            for element_id in targets
            if toolkit.getPageWithElement(element_id) > 0
        ]
        if existing_targets:
            targets = existing_targets
        elif annotation.get("measure_id") and toolkit.getPageWithElement(
            annotation["measure_id"]
        ):
            targets = [annotation["measure_id"]]
            status = "measure-fallback"
        else:
            targets = []
            status = "unresolved"

        pages = sorted(
            {
                int(toolkit.getPageWithElement(element_id))
                for element_id in targets
                if toolkit.getPageWithElement(element_id) > 0
            }
        )
        annotation["target_ids"] = targets
        annotation["score_pages"] = pages
        annotation["status"] = status
        resolved_annotations.append(annotation)
    return resolved_annotations


def render_verovio_pages(
    mei_path: str | Path | ResolvedMeiSource,
    *,
    initial_page: int,
    options: dict,
    repo_root: Path | None = None,
    show_verovio_warnings: bool = False,
    mei_text: str | None = None,
    annotations: list[dict] | None = None,
) -> dict:
    """Render all Verovio pages and return SVG strings plus page metadata.

    Verovio layout messages such as ``Justification is highly compressed`` are
    suppressed unless ``show_verovio_warnings`` is True.
    """
    mei_path = resolve_mei_source(mei_path, repo_root=repo_root)
    mei_text = mei_text if mei_text is not None else mei_path.read_text(encoding="utf-8")
    render_root = ET.fromstring(mei_text)
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
        resolved_annotations = _resolve_render_annotations(
            annotations or [], root=render_root, toolkit=toolkit
        )

    return {
        "page_count": page_count,
        "initial_page": initial_page,
        "initial_page_index": initial_page - 1,
        "pages": pages,
        "annotations": resolved_annotations,
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
    layout = model.get("layout", {})
    missing_page_breaks = layout.get("missing_page_breaks", [])
    missing_system_breaks = layout.get("missing_system_breaks", [])
    if layout.get("alignment_applied"):
        layout_html = (
            '<p class="layout-diagnostic is-applied">Temporary facsimile alignment is active. '
            f'Inserted page breaks before {escape(", ".join(layout.get("applied_page_breaks", [])) or "none")} '
            f'and system breaks before {escape(", ".join(layout.get("applied_system_breaks", [])) or "none")}.</p>'
        )
    elif missing_page_breaks or missing_system_breaks:
        page_labels = ", ".join(row["measure_id"] for row in missing_page_breaks) or "none"
        system_labels = ", ".join(missing_system_breaks) or "none"
        layout_html = (
            '<p class="layout-diagnostic is-warning">Facsimile geometry suggests missing encoded layout: '
            f'&lt;pb&gt; before {escape(page_labels)}; &lt;sb&gt; before {escape(system_labels)}. '
            'Use align_to_facsimile=True for a non-mutating preview.</p>'
        )
    else:
        layout_html = ""
    return f"""
    <details class="mei-viewer-details">
      <summary>{summary}</summary>
      {layout_html}
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
    show_annotations: bool = True,
    annotation_display_limit: int = 300,
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
    if isinstance(annotation_display_limit, bool) or not isinstance(
        annotation_display_limit, int
    ):
        raise TypeError("annotation_display_limit must be an integer")
    if annotation_display_limit < 1:
        raise ValueError("annotation_display_limit must be greater than zero")

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
    page_number_to_index = {
        page["number"]: index for index, page in enumerate(score_pages)
    }
    all_annotations = model.get("annotations", [])
    annotations = []
    for source in all_annotations[:annotation_display_limit]:
        annotation = dict(source)
        target_ids = annotation.get("target_ids", [])
        rendered_pages = list(annotation.get("score_pages", []))
        if not rendered_pages:
            for index, page in enumerate(score_pages):
                if any(f'id="{target_id}"' in page["svg"] for target_id in target_ids):
                    rendered_pages.append(page["number"])
        annotation["page_index"] = (
            page_number_to_index.get(rendered_pages[0]) if rendered_pages else None
        )
        annotations.append(annotation)
    annotations_json = json.dumps(annotations)
    annotation_buttons = []
    for annotation in annotations:
        anchor = annotation.get("anchor_mode", "unanchored")
        if anchor == "tstamp":
            anchor = f'tstamp {annotation.get("tstamp") or "?"}'
        label = annotation.get("text") or annotation.get("id") or "Untitled annotation"
        annotation_buttons.append(
            f'<button type="button" class="annotation-item" '
            f'data-annotation-id="{escape(annotation.get("id", ""), quote=True)}">'
            f'<span class="annotation-kind">{escape(anchor)}</span>'
            f'<span>{escape(label)}</span></button>'
        )
    if annotations:
        checked = "checked" if show_annotations else ""
        annotation_count = (
            str(len(annotations))
            if len(annotations) == len(all_annotations)
            else f"{len(annotations)} of {len(all_annotations)}"
        )
        annotation_controls = (
            '<label class="annotation-toggle-label">'
            f'<input type="checkbox" class="annotation-toggle" {checked}> '
            f'Highlight annotations ({annotation_count})</label>'
        )
        annotation_panel = (
            '<details class="annotation-panel" open>'
            f'<summary>Score annotations ({annotation_count})</summary>'
            f'<div class="annotation-list">{"".join(annotation_buttons)}</div></details>'
        )
    else:
        annotation_controls = ""
        annotation_panel = ""
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
  #{viewer_id} .annotation-toggle-label {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: #4b5563;
    font-size: 12px;
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
    grid-template-columns: minmax(0, 1fr) minmax(0, {facsimile_max_width}px);
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
  #{viewer_id}.annotations-visible .score-pane .is-annotated,
  #{viewer_id}.annotations-visible .score-pane .is-annotated * {{
    color: #7c3aed !important;
    fill: #7c3aed !important;
    stroke: #7c3aed !important;
  }}
  #{viewer_id} .score-pane .is-selected-annotation,
  #{viewer_id} .score-pane .is-selected-annotation * {{
    color: #dc2626 !important;
    fill: #dc2626 !important;
    stroke: #dc2626 !important;
  }}
  #{viewer_id} .annotation-panel {{
    margin-top: 12px;
    border: 1px solid var(--panel-border);
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 13px;
  }}
  #{viewer_id} .annotation-list {{
    display: grid;
    gap: 6px;
    margin-top: 8px;
    max-height: 240px;
    overflow: auto;
  }}
  #{viewer_id} .annotation-item {{
    display: grid;
    grid-template-columns: minmax(72px, auto) 1fr;
    gap: 8px;
    border: 1px solid var(--panel-border);
    border-radius: 5px;
    background: white;
    color: #1f2933;
    padding: 6px 8px;
    text-align: left;
    cursor: pointer;
  }}
  #{viewer_id} .annotation-item.is-active {{
    border-color: #dc2626;
  }}
  #{viewer_id} .annotation-kind {{
    color: #6d28d9;
    font-size: 11px;
    font-weight: 600;
  }}
  #{viewer_id} .layout-diagnostic {{
    margin: 8px 0;
    padding: 7px 9px;
    border-radius: 5px;
  }}
  #{viewer_id} .layout-diagnostic.is-warning {{
    background: #fffbeb;
    color: #92400e;
  }}
  #{viewer_id} .layout-diagnostic.is-applied {{
    background: #ecfdf5;
    color: #065f46;
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
  @media (max-width: 560px) {{
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
    {annotation_controls}
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
  {annotation_panel}
  {table_html}
</div>
<script>
(() => {{
  const viewerId = {json.dumps(viewer_id)};
  let initializationAttempts = 0;

  function initializeViewer(root) {{
    if (!root || root.dataset.camatViewerInitialized === 'true') return;
    root.dataset.camatViewerInitialized = 'true';

  const pairs = {pairs_json};
  const annotations = {annotations_json};
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
  const annotationToggle = root.querySelector('.annotation-toggle');
  const byMeasure = new Map(pairs.map((item) => [item.measureId, item]));
  const byZone = new Map(pairs.map((item) => [item.zoneId, item]));
  const initialPageIndex = {initial_page_index};
  let activePageIndex = initialPageIndex;
  let activeSurfaceIndex = {initial_surface_index};
  let scoreZoom = initialScoreZoom;
  let facsimileZoom = initialFacsimileZoom;

  function annotationTargets(item) {{
    return (item.target_ids || []).map((targetId) =>
      root.querySelector(`#${{CSS.escape(targetId)}}`)
    ).filter(Boolean);
  }}

  function applyAnnotationVisibility(visible) {{
    root.classList.toggle('annotations-visible', visible);
    annotations.forEach((item) => {{
      annotationTargets(item).forEach((node) => node.classList.toggle('is-annotated', visible));
    }});
  }}

  function selectAnnotation(item) {{
    if (!item) return;
    if (item.page_index !== null && item.page_index !== undefined) showScorePage(item.page_index);
    root.querySelectorAll('.is-selected-annotation').forEach((node) => node.classList.remove('is-selected-annotation'));
    root.querySelectorAll('.annotation-item.is-active').forEach((node) => node.classList.remove('is-active'));
    const targets = annotationTargets(item);
    targets.forEach((node) => node.classList.add('is-selected-annotation'));
    const button = root.querySelector(`.annotation-item[data-annotation-id="${{CSS.escape(item.id)}}"]`);
    if (button) button.classList.add('is-active');
    if (targets[0]) targets[0].scrollIntoView({{block: 'center', inline: 'center', behavior: 'smooth'}});
    const anchor = item.anchor_mode === 'tstamp' ? `tstamp ${{item.tstamp}}` : item.anchor_mode;
    status.textContent = `Annotation ${{item.id}} | ${{anchor}} | ${{item.text || '(no text)'}}`;
  }}

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

  root.querySelectorAll('.annotation-item').forEach((button) => {{
    const item = annotations.find((candidate) => candidate.id === button.dataset.annotationId);
    if (!item) return;
    button.addEventListener('click', () => selectAnnotation(item));
  }});
  if (annotationToggle) {{
    annotationToggle.addEventListener('change', () => applyAnnotationVisibility(annotationToggle.checked));
    applyAnnotationVisibility(annotationToggle.checked);
  }}

  applyScoreZoom(initialScoreZoom);
  applyFacsimileZoom(initialFacsimileZoom);
  showScorePage(initialPageIndex);
  const initialItem = pairs.find((item) => item.pageIndex === initialPageIndex) || pairs[0];
  if (initialItem) activate(initialItem);
  }}

  function initializeAttachedViewers() {{
    // Attribute selector: duplicate notebook outputs can share the same id, and
    // getElementById() would bind only the first (often non-interactive) copy.
    const roots = document.querySelectorAll('[id="' + viewerId + '"]');
    if (!roots.length) {{
      initializationAttempts += 1;
      if (initializationAttempts < 250) window.setTimeout(initializeAttachedViewers, 20);
      return;
    }}
    roots.forEach((root) => initializeViewer(root));
  }}

  // Notebook frontends can evaluate an HTML output's script before its root
  // element has been attached, or clone the markup into a widget after the
  // script ran. Retry and observe insertions so hovers work on first paint.
  window.setTimeout(initializeAttachedViewers, 0);
  if (typeof MutationObserver === "function" && document.documentElement) {{
    const observer = new MutationObserver(() => initializeAttachedViewers());
    observer.observe(document.documentElement, {{ childList: true, subtree: true }});
    window.setTimeout(() => observer.disconnect(), 5000);
  }}
}})();
</script>
"""


def embed_viewer_html(html: str, *, min_height: int) -> str:
    """Wrap viewer markup so Jupyter shows it once, inside a widget.

    Notebook frontends treat ``IPython.display.HTML`` inside an ``Output``
    widget as a second cell output. An iframe ``srcdoc`` on ``widgets.HTML``
    stays in the widget, still runs hover scripts, and resizes to its content.
    """
    if isinstance(min_height, bool) or not isinstance(min_height, (int, float)):
        raise TypeError("min_height must be a number")
    if min_height <= 0:
        raise ValueError("min_height must be greater than zero")
    inner = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>html,body{{margin:0;padding:0;background:#fff;}}</style>
</head><body>
{html}
<script>
(() => {{
  function syncHeight() {{
    const frame = window.frameElement;
    if (!frame) return;
    const height = Math.max(
      document.documentElement.scrollHeight,
      document.body ? document.body.scrollHeight : 0
    );
    frame.style.height = Math.ceil(height) + "px";
  }}
  syncHeight();
  window.addEventListener("load", syncHeight);
  if (typeof ResizeObserver === "function") {{
    new ResizeObserver(syncHeight).observe(document.documentElement);
  }}
}})();
</script>
</body></html>
"""
    return (
        '<iframe class="camat-mei-viewer-frame" '
        f'srcdoc="{escape(inner, quote=True)}" '
        'sandbox="allow-scripts allow-same-origin" '
        'title="MEI facsimile viewer" '
        'style="width:100%;border:0;display:block;'
        f'min-height:{int(min_height)}px"></iframe>'
    )


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
        mei_path: str | Path | ResolvedMeiSource,
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
        show_annotations: bool = True,
        annotation_display_limit: int = 300,
        align_to_facsimile: bool = False,
        auto_watch_mei: bool = True,
        auto_watch_mode: str = "events",
        watch_interval_sec: float = 2.0,
        watch_settle_sec: float = 0.35,
        watch_debounce_sec: float = 0.4,
        note_probe_id: str | None = None,
    ) -> None:
        self.repo_root = (repo_root or find_camat_root()).resolve()
        self.mei_source = mei_path.original if isinstance(mei_path, ResolvedMeiSource) else mei_path
        self.source_info = resolve_mei_source_info(mei_path, repo_root=self.repo_root)
        self.mei_path = self.source_info.local_path
        self.viewer_id = viewer_id or f"mei-viewer-live-{uuid.uuid4().hex}"
        self._render_revision = 0
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
        self.show_annotations = show_annotations
        self.annotation_display_limit = annotation_display_limit
        self.align_to_facsimile = align_to_facsimile
        self.auto_watch_mei = auto_watch_mei
        self.auto_watch_mode = auto_watch_mode
        self.watch_interval_sec = watch_interval_sec
        self.watch_settle_sec = watch_settle_sec
        self.watch_debounce_sec = watch_debounce_sec
        self.note_probe_id = note_probe_id

        self.cache = FacsimileViewerCache()
        self._widgets: Any = None
        self._get_ipython: Callable | None = None
        self._display: Any = None

        self.status_html = None
        self.viewer_html = None
        self.watch_status = None
        self.reload_zones_btn = None
        self.reload_score_btn = None
        self.watch_toggle = None
        self.ui = None

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
            from IPython.display import display
        except ImportError as exc:
            raise ImportError(
                "InteractiveFacsimileViewer requires ipywidgets and IPython"
            ) from exc
        self._widgets = widgets
        self._get_ipython = get_ipython
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
        self._render_revision += 1
        render_id = f"{self.viewer_id}-render-{self._render_revision}-{uuid.uuid4().hex[:8]}"
        result = build_facsimile_viewer(
            self.source_info,
            verovio_options=self._verovio_options(),
            initial_page=self.verovio_initial_page,
            render_score=render_score,
            cache=self.cache,
            repo_root=self.repo_root,
            viewer_id=render_id,
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
            show_annotations=self.show_annotations,
            annotation_display_limit=self.annotation_display_limit,
            align_to_facsimile=self.align_to_facsimile,
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
        summary = (
            f"{result['summary']}\n"
            f"Viewer:          {score_render['page_count']} Verovio score page(s), {render_note}"
        )
        if self.status_html is not None:
            self.status_html.value = (
                "<pre style='margin:0;white-space:pre-wrap'>"
                f"{escape(summary)}</pre>"
            )
        if self.viewer_html is not None:
            self.viewer_html.value = embed_viewer_html(
                result["html"],
                min_height=self.viewer_max_height,
            )

    def refresh_viewer(
        self,
        *,
        render_score: bool | str = "auto",
        refresh_source: bool = False,
    ) -> dict:
        if refresh_source and self.source_info.kind == "remote":
            self.source_info = resolve_mei_source_info(
                self.mei_source,
                repo_root=self.repo_root,
                refresh_remote=True,
            )
            self.mei_path = self.source_info.local_path
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
        if self.source_info.kind == "remote":
            self._set_watch_status(
                "<i>Remote source — use Reload source to download it again</i>"
            )
            self.watch_toggle.value = False
            return
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

        self.status_html = widgets.HTML()
        self.viewer_html = widgets.HTML(layout=widgets.Layout(width="100%"))
        self.watch_status = widgets.HTML(value="<i>Auto-watch off</i>")
        self.reload_zones_btn = widgets.Button(description="Reload zones", icon="refresh")
        reload_label = "Reload source" if self.source_info.kind == "remote" else "Reload score"
        self.reload_score_btn = widgets.Button(description=reload_label, icon="sync")
        self.watch_toggle = widgets.ToggleButton(
            description="Auto-watch MEI", value=self.auto_watch_mei
        )

        controls = widgets.HBox(
            [self.reload_zones_btn, self.reload_score_btn, self.watch_toggle]
        )
        self.ui = widgets.VBox(
            [controls, self.watch_status, self.status_html, self.viewer_html]
        )

        self.reload_zones_btn.on_click(lambda _: self.refresh_viewer(render_score=False))
        self.reload_score_btn.on_click(
            lambda _: self.refresh_viewer(render_score=True, refresh_source=True)
        )

        def _on_watch_toggle(change) -> None:
            if change["new"]:
                self.start_watch()
            else:
                self.stop_watch()

        self.watch_toggle.observe(_on_watch_toggle, names="value")

        result = self._build_viewer(render_score=True)
        self._show_viewer_result(result)
        self._display(self.ui)
        if self.watch_toggle.value:
            self.start_watch()
        else:
            self.stop_watch()
        return self


def launch_interactive_facsimile_viewer(
    mei_path: str | Path | ResolvedMeiSource,
    **kwargs: Any,
) -> InteractiveFacsimileViewer:
    """Display a Jupyter viewer for a local path, file URI, or HTTP(S) link."""
    return InteractiveFacsimileViewer(mei_path, **kwargs).display()
