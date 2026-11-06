"""Attach facsimile zone columns to a CAMAT note or event table.

The link is bar-level only: a row's ``xml_id`` leads to the element with that
id, then to the enclosing ``<measure>``, then through ``measure/@facs`` to the
zone, surface, and graphic. The columns never claim where inside the bar a
note sits.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd

from .facsimile_viewer import NS, XML_ID, ResolvedMeiSource, read_facsimile_model

__all__ = ["add_facsimile_columns"]

ZONE_FIELDS = (
    "zone_id",
    "surface_id",
    "page",
    "image",
    "zone_ulx",
    "zone_uly",
    "zone_lrx",
    "zone_lry",
)
COLUMNS = ZONE_FIELDS + ("zone_status",)

_STATUS_NO_ID = "no xml_id"
_STATUS_NOT_IN_FILE = "id not in file"
_STATUS_OUTSIDE = "outside measure"
_STATUS_MISSING_FACS = "missing facs"
_STATUS_UNAVAILABLE = "facsimile unavailable"
_STATUS_LINKED = "linked"


def _missing_xml_id(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value) == ""


def _element_measure_index(root: ET.Element) -> tuple[dict[str, int], set[str]]:
    """Map every xml:id under a measure to that measure's document-order index.

    Indexing by position, not by the measure's own id, is required: a bar need
    not carry ``xml:id``, and ``model["measures"]`` is built in the same
    ``.//m:measure`` order.
    """
    known = {element.get(XML_ID) for element in root.iter() if element.get(XML_ID)}
    by_id: dict[str, int] = {}
    for index, measure in enumerate(root.findall(".//m:measure", NS)):
        for element in measure.iter():
            element_id = element.get(XML_ID)
            if element_id:
                by_id[element_id] = index
    return by_id, known


def _zone_tokens(zone: dict[str, Any], surfaces: list[dict[str, Any]]) -> tuple[str, ...]:
    surface = surfaces[zone["surface_index"]]
    return (
        zone["id"],
        zone["surface_id"],
        str(surface["n"]),
        surface["graphic_target"],
        str(zone["ulx"]),
        str(zone["uly"]),
        str(zone["lrx"]),
        str(zone["lry"]),
    )


def _join_zones(zones: list[dict[str, Any]], surfaces: list[dict[str, Any]]) -> tuple[str, ...]:
    pieces = [_zone_tokens(zone, surfaces) for zone in zones]
    if len(pieces) > 1:
        # These cells are read position by position, so one value holding a
        # space (MEI's @target is a URI list) would shift the rest of its column.
        for zone, tokens in zip(zones, pieces):
            for token in tokens:
                if len(token.split()) != 1:
                    raise ValueError(
                        f"Zone {zone['id']!r} shares its bar with other zones, but "
                        f"{token!r} contains a space, so the space-separated cells "
                        "could not be read position by position"
                    )
    return tuple(" ".join(column) for column in zip(*pieces))


def add_facsimile_columns(
    table: pd.DataFrame,
    mei: str | Path | ResolvedMeiSource,
    *,
    repo_root: Path | None = None,
    allow_missing_facsimile: bool = False,
) -> pd.DataFrame:
    """Return a copy of ``table`` with facsimile zone columns for each row.

    The link is bar-level: row ``xml_id`` -> the element with that ``xml:id`` ->
    the ``<measure>`` holding it (or the measure itself) -> ``measure/@facs`` ->
    zone -> surface -> graphic. Nothing here claims where inside the bar a note
    sits.

    New columns, appended after the existing ones, in this order: ``zone_id``,
    ``surface_id``, ``page``, ``image``, ``zone_ulx``, ``zone_uly``,
    ``zone_lrx``, ``zone_lry``, ``zone_status``.

    ``zone_status`` is one of ``linked``, ``no xml_id``, ``id not in file``,
    ``outside measure``, ``missing facs``, or ``facsimile unavailable``. For
    every status but ``linked``, the eight zone cells are missing values.

    A bar with several zones keeps one space-separated token per zone in each
    of the eight cells, in ``@facs`` order. The k-th token of every column
    belongs to the k-th zone. Corner columns are nullable ``Int64`` when no row
    has a split bar; otherwise those four columns are strings throughout.

    Raises ``FacsimileUnavailableError`` when the MEI has no usable facsimile
    unless ``allow_missing_facsimile`` is true, in which case every row is marked
    ``facsimile unavailable``. Invalid facsimile records raise ``RuntimeError``
    from ``read_facsimile_model`` in both modes. ``ValueError`` is raised for a
    table without an ``xml_id`` column, for a table that already has one of the
    new column names (rather than overwrite it, so a table that has been through
    this function once is refused), and for a bar with several zones where a
    value contains a space, as a multi-URI ``@target`` does.
    """
    if "xml_id" not in table.columns:
        raise ValueError(
            "table has no 'xml_id' column; CAMAT's parsers add it unless "
            "include_xml_ids=False"
        )
    clashes = [name for name in COLUMNS if name in table.columns]
    if clashes:
        raise ValueError(
            f"table already has column(s) {', '.join(clashes)}; rename or drop "
            "them first"
        )

    model = read_facsimile_model(
        mei,
        repo_root=repo_root,
        allow_missing_facsimile=allow_missing_facsimile,
    )
    out = table.copy(deep=True)
    n_rows = len(out)

    if not model.get("has_facsimile", True):
        for name in ("zone_id", "surface_id", "page", "image"):
            out[name] = pd.Series([pd.NA] * n_rows, index=out.index, dtype=object)
        for name in ("zone_ulx", "zone_uly", "zone_lrx", "zone_lry"):
            out[name] = pd.Series([pd.NA] * n_rows, index=out.index, dtype="Int64")
        out["zone_status"] = _STATUS_UNAVAILABLE
        return out

    root = ET.parse(model["mei_path"]).getroot()
    by_id, known = _element_measure_index(root)
    measures: list[dict[str, Any]] = model["measures"]
    surfaces: list[dict[str, Any]] = model["surfaces"]

    # Resolve positionally so repeated xml_id values and repeated index labels
    # both keep a one-to-one row mapping; a left-keyed merge would not.
    statuses: list[str] = []
    linked_tokens: list[tuple[str, ...] | None] = []
    has_split = False
    for value in out["xml_id"]:
        if _missing_xml_id(value):
            statuses.append(_STATUS_NO_ID)
            linked_tokens.append(None)
            continue
        xml_id = str(value)
        if xml_id not in known:
            statuses.append(_STATUS_NOT_IN_FILE)
            linked_tokens.append(None)
            continue
        measure_index = by_id.get(xml_id)
        if measure_index is None:
            statuses.append(_STATUS_OUTSIDE)
            linked_tokens.append(None)
            continue
        measure = measures[measure_index]
        zones = measure.get("zones") or []
        if not zones:
            statuses.append(_STATUS_MISSING_FACS)
            linked_tokens.append(None)
            continue
        if len(zones) > 1:
            has_split = True
        statuses.append(_STATUS_LINKED)
        linked_tokens.append(_join_zones(zones, surfaces))

    zone_columns: dict[str, list[Any]] = {name: [] for name in ZONE_FIELDS}
    for tokens in linked_tokens:
        if tokens is None:
            for name in ZONE_FIELDS:
                zone_columns[name].append(pd.NA)
            continue
        for name, token in zip(ZONE_FIELDS, tokens):
            zone_columns[name].append(token)

    for name in ("zone_id", "surface_id", "page", "image"):
        out[name] = pd.Series(zone_columns[name], index=out.index, dtype=object)

    for name in ("zone_ulx", "zone_uly", "zone_lrx", "zone_lry"):
        values = zone_columns[name]
        if has_split:
            out[name] = pd.Series(values, index=out.index, dtype=object)
        else:
            ints: list[Any] = [
                pd.NA if (value is None or pd.isna(value)) else int(value)
                for value in values
            ]
            out[name] = pd.Series(ints, index=out.index, dtype="Int64")

    out["zone_status"] = pd.Series(statuses, index=out.index, dtype=object)
    return out
