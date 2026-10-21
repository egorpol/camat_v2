"""Render, review and link local PDF facsimiles to movement-scoped MEI measures.

Poppler supplies the page pixels; saved detector responses or manual boxes
supply geometry. Page review in ``pages.json`` supplies the musical labels.
No uploads occur unless explicitly enabled, and integration reports pending
reviews without blocking them. Layout changes are a separate operation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date as local_date, datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
from statistics import median
import struct
import subprocess
import sys
import tempfile
from typing import NamedTuple
import warnings
import xml.etree.ElementTree as ET
from xml.parsers import expat

from .upload_and_integrate_measure_annotations import DETECTOR_URL, upload_image

MEI = "{http://www.music-encoding.org/ns/mei}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_COORDS = ("ulx", "uly", "lrx", "lry")
_TAG = re.compile(rb"""<[^>"']*(?:(?:"[^"]*"|'[^']*')[^>"']*)*>""")
_XMLNS = re.compile(r'\sxmlns(?::([^\s=]+))?="([^"]*)"')
_ID_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*\Z")
_REVIEW_STATUSES = {"unreviewed", "approved", "rejected"}


NON_MUSIC_PAGE_ROLES = ("cover", "title", "preface", "blank", "advertisement", "duplicate")
POPPLER_INSTALL_HINTS = (
    "  Windows / any system with conda:  conda install -c conda-forge poppler\n"
    "  macOS with Homebrew:              brew install poppler\n"
    "  Debian / Ubuntu:                  sudo apt install poppler-utils\n"
    "  Google Colab:                     run  !apt-get install -y poppler-utils  in a new cell\n"
)


class _LayoutError(ValueError):
    """Layout failure with details for clients that supply their own wording."""

    def __init__(self, message: str, code: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class _BoxEditError(ValueError):
    """Box correction failure with details for presentation clients."""

    def __init__(self, message: str, code: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class _SystemCountError(ValueError):
    """The detected system counts differ from the reviewed layout."""


class _PageReviewError(ValueError):
    """Page review fields need correction."""


class _DetectorResponseError(ValueError):
    """The detector returned invalid boxes."""


class _IntegrationGateError(ValueError):
    """The MEI and alignment failed a correspondence or preservation gate."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False) as stream:
            temp = Path(stream.name)
            stream.write(data)
        if path.exists():
            shutil.copymode(path, temp)
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _write_json(path: Path, data: dict) -> None:
    _atomic_write(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def _relative(path: Path, folder: Path) -> str:
    return Path(os.path.relpath(path.resolve(), folder.resolve())).as_posix()


def _source_id(value: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid source_id {value!r}; use source_id= with an XML ID matching "
                         "^[A-Za-z_][A-Za-z0-9_.-]*$")
    return value


def _png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if (len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n"
            or header[8:16] != b"\x00\x00\x00\rIHDR"):
        raise ValueError(f"Invalid PNG header: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if not width or not height:
        raise ValueError(f"Invalid PNG dimensions: {path}")
    return width, height


def _poppler(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Poppler's {command[0]} is missing; install it and put it on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{command[0]} failed: {(exc.stderr or exc.stdout).strip()}") from exc


def render_pdf_pages(
    pdf: str | Path, output_dir: str | Path, dpi: int = 300, *, source_id: str | None = None,
) -> dict:
    """Rasterize every PDF page with Poppler, or verify and reuse its manifest.

    Each image shows the page's crop box, the area a PDF reader shows.
    Existing derivatives are never overwritten when the input, settings or
    image hashes differ. Review fields in an existing manifest are preserved.
    """
    pdf, output_dir = Path(pdf).resolve(), Path(output_dir).resolve()
    source_id = _source_id(pdf.stem if source_id is None else source_id)
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
        raise ValueError("dpi must be a positive integer")
    check_poppler()
    version = _poppler(["pdftoppm", "-v"])
    renderer = (version.stderr or version.stdout).splitlines()[0]
    pdf_hash = _sha256(pdf)
    manifest_path = output_dir / "pages.json"
    if manifest_path.exists():
        existing = _read_json(manifest_path)
        changes = [key for key, value in {"pdf_sha256": pdf_hash, "dpi": dpi,
                   "renderer": renderer, "source_id": source_id}.items() if existing.get(key) != value]
        for page in existing["pages"]:
            image = output_dir / page["image"]
            if not image.is_file() or _sha256(image) != page["sha256"]:
                changes.append(f"image hash ({page['page_id']}: {page['image']})")
        if changes:
            raise ValueError("Cannot reuse pages.json; changed: " + ", ".join(changes)
                             + ". Move derivatives aside before rendering again.")
        return existing
    if any(output_dir.glob("page-*.png")):
        raise FileExistsError(f"{output_dir}: page-*.png exists without pages.json; refusing to overwrite")
    info = _poppler(["pdfinfo", str(pdf)]).stdout
    match = re.search(r"^Pages:\s+(\d+)", info, re.M)
    if not match or int(match[1]) < 1:
        raise RuntimeError(f"Cannot determine PDF page count: {pdf}")
    count = int(match[1])
    info = _poppler(["pdfinfo", "-f", "1", "-l", str(count), "-box", str(pdf)]).stdout
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".render-", dir=output_dir) as temp:
        stage = Path(temp)
        _poppler(["pdftoppm", "-r", str(dpi), "-cropbox", "-png", str(pdf), str(stage / "page")])
        pictures = sorted(stage.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
        if len(pictures) != count:
            raise RuntimeError(f"Expected {count} pages from {pdf}, got {len(pictures)}")
        pages = []
        for number, picture in enumerate(pictures, 1):
            width, height = _png_size(picture)
            pages.append({"page_id": f"{source_id}-p{number:04d}", "pdf_page_number": number,
                          "image": f"page-{number:04d}.png", "width": width, "height": height,
                          "sha256": _sha256(picture), "printed_page": None, "role": "unreviewed"})
        manifest = {"schema_version": 1, "source_id": source_id, "pdf": _relative(pdf, output_dir),
                    "pdf_sha256": pdf_hash, "page_count": count, "dpi": dpi, "renderer": renderer,
                    "coordinate_system": "image pixels; origin top-left; x right, y down", "pages": pages}
        for picture, page in zip(pictures, pages):
            os.replace(picture, output_dir / page["image"])
        _atomic_write(output_dir / "pdfinfo.txt", info.encode("utf-8"))
        _write_json(manifest_path, manifest)
    return manifest


def _ranges(labels: list[str]) -> str:
    """['1', '2', '3', '7'] -> '1–3, 7'"""
    parts, run = [], []
    for label in labels:
        if run and label.isdigit() and run[-1].isdigit() and int(label) == int(run[-1]) + 1:
            run.append(label)
            continue
        if run:
            parts.append(run[0] if len(run) == 1 else f"{run[0]}–{run[-1]}")
        run = [label]
    if run:
        parts.append(run[0] if len(run) == 1 else f"{run[0]}–{run[-1]}")
    return ", ".join(parts)


def _labels(text: str, line_no: int, shown: str) -> list[str]:
    """'1-4 6' -> ['1', '2', '3', '4', '6']"""
    text = re.sub(r"\s*[-–—]\s*", "-", text.strip())
    if not text:
        raise ValueError(f"Line {line_no} ({shown}): one system is empty. Are there two commas in a row?")
    labels = []
    for token in text.split():
        match = re.fullmatch(r"(\d+)-(\d+)", token)
        if match:
            first, last = int(match[1]), int(match[2])
            if first > last:
                raise ValueError(f"Line {line_no} ({shown}): {token} counts backwards. Write the smaller number first.")
            labels.extend(str(n) for n in range(first, last + 1))
        elif "-" in token:
            raise ValueError(f"Line {line_no} ({shown}): I cannot read {token!r}. Write a range like 5-9.")
        else:
            labels.append(token)
    return labels


def parse_page_layout(text: str, *, page_count: int | None = None) -> dict[int, dict]:
    """Parse one movement's page roles, printed pages and system bar labels.

    Use ``PDF page | printed page | 1-4, 5-9`` for music, or
    ``PDF page | cover`` (or another ``NON_MUSIC_PAGE_ROLES`` role).
    Commas separate systems; spaces separate labels and numeric ranges.
    Comments start with ``#``. A repeated boundary label denotes a split bar.
    """
    pages = {}
    for line_no, raw in enumerate(text.splitlines(), 1):
        line, shown = raw.split("#", 1)[0].strip(), raw.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if not parts[0].isdigit():
            raise ValueError(f"Line {line_no} ({shown}) must start with a PDF page number, "
                             "for example: 2 | 160 | 1-4, 5-9, 10-14")
        number = int(parts[0])
        if number < 1 or (page_count is not None and number > page_count):
            if page_count is None:
                raise ValueError(f"Line {line_no} ({shown}): PDF page numbers must start at 1.")
            raise ValueError(f"Line {line_no} ({shown}): the PDF only has pages 1 to {page_count}.")
        if number in pages:
            raise ValueError(f"Line {line_no} ({shown}): PDF page {number} is described twice.")
        if len(parts) == 2:
            kind = parts[1].lower()
            if kind not in NON_MUSIC_PAGE_ROLES:
                raise ValueError(f"Line {line_no} ({shown}): a page with music needs three parts, "
                                 "PDF page | printed page | bars. For a page without music, use one of: "
                                 + ", ".join(NON_MUSIC_PAGE_ROLES) + ".")
            pages[number] = {"role": kind}
        elif len(parts) == 3:
            printed = None if parts[1] in ("", "-", "?") else parts[1]
            systems = [_labels(system, line_no, shown) for system in parts[2].split(",")]
            pages[number] = {"role": "music", "printed_page": printed, "systems": systems}
        else:
            raise ValueError(f"Line {line_no} ({shown}): expected 2 or 3 parts separated by |, found {len(parts)}.")
    if not any(page["role"] == "music" for page in pages.values()):
        raise ValueError("Your description has no page with music. "
                         "Write one line per music page, for example: 2 | 160 | 1-4, 5-9, 10-14")
    return dict(sorted(pages.items()))


def _split_bars(pages: dict[int, dict]) -> list[str]:
    """Bar numbers written at the end of one system and again at the start of the next."""
    previous, split = None, []
    for number in sorted(pages):
        for system in pages[number].get("systems", []):
            if previous is not None and system[0] == previous:
                split.append(system[0])
            previous = system[-1]
    return split


def check_poppler() -> None:
    """Require pdftoppm and pdfinfo on PATH; the error lists ``POPPLER_INSTALL_HINTS``."""
    for program in ("pdftoppm", "pdfinfo"):
        if shutil.which(program) is None:
            raise RuntimeError(f"Poppler's {program} is missing; install it and put it on PATH:\n"
                               + POPPLER_INSTALL_HINTS.rstrip("\n"))


def _mei_movement(mei: Path) -> tuple[str | None, list[str]]:
    if not mei.is_file():
        raise FileNotFoundError(f"The MEI file is missing: {mei}")
    try:
        root = ET.parse(mei).getroot()
    except ET.ParseError as exc:
        raise _LayoutError(f"{mei} is not a readable XML file: {exc}", "xml", problem=exc) from exc
    mdivs = list(root.iter(MEI + "mdiv"))
    if not mdivs:
        raise _LayoutError(f"{mei} has no <mdiv> (movement). Is it an MEI file?", "no_mdiv")
    if len(mdivs) > 1:
        raise _LayoutError(f"{mei} has {len(mdivs)} movements (<mdiv> elements); expected one.",
                           "multiple_mdivs", count=len(mdivs))
    bars = []
    for measure in mdivs[0].iter(MEI + "measure"):
        if measure.get("n") is None:
            raise _LayoutError(
                f"The MEI has a <measure> without a bar number (@n), xml:id {measure.get(XML_ID)}. "
                "Every bar needs a number.", "measure_n", xml_id=measure.get(XML_ID))
        bars.append(measure.get("n"))
    if not bars:
        raise _LayoutError(f"{mei} has no <measure> elements.", "no_measures")
    return mdivs[0].get("n"), bars


def check_page_layout(layout: dict[int, dict], mei: str | Path) -> dict:
    """Check one movement's layout against MEI labels, counting split bars once.

    Return ``mdiv`` (its @n or None), ``bars`` in MEI order and ``split_bars``.
    Missing/extra bars are reported as ranges before the first order mismatch.
    """
    mdiv_n, bars = _mei_movement(Path(mei))
    sequence = []
    for number in sorted(layout):
        for system in layout[number].get("systems", []):
            sequence.extend(system[1:] if sequence and system[0] == sequence[-1] else system)
    missing = [bar for bar in bars if bar not in set(sequence)]
    extra = [label for label in sequence if label not in set(bars)]
    if missing or extra:
        lines = ["Your description and the MEI do not have the same bars."]
        if missing:
            lines.append(f"  In the MEI but not in your description: {_ranges(missing)}")
        if extra:
            lines.append(f"  In your description but not in the MEI: {_ranges(extra)}")
        lines.append(f"The MEI has {len(bars)} bars: {_ranges(bars)}.")
        raise _LayoutError("\n".join(lines), "bars", missing=missing, extra=extra, bars=bars)
    if sequence != bars:
        index = next((i for i, (a, b) in enumerate(zip(sequence, bars)) if a != b), min(len(sequence), len(bars)))
        before = f"after bar {bars[index - 1]}" if index else "at the start"
        raise _LayoutError(
            f"Your bars are not in the same order as in the MEI: {before}, the MEI continues with "
            f"bar {bars[index] if index < len(bars) else '(end)'}, your description with "
            f"bar {sequence[index] if index < len(sequence) else '(end)'}. "
            "Is a bar listed twice or in the wrong place?", "order", index=index, bars=bars, sequence=sequence)
    return {"mdiv": mdiv_n, "bars": bars, "split_bars": _split_bars(layout)}


def _write_json_if_changed(path: Path, data: dict) -> bool:
    encoded = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if path.read_bytes() == encoded:
        return False
    _write_json(path, data)
    return True


def apply_page_layout(pages_json: str | Path, layout: dict[int, dict], *, mdiv: str = "1") -> dict:
    """Save reviewed page roles and one movement's system labels when changed.

    Unlisted pages become unreviewed. An empty layout resets every page.
    """
    pages_json = Path(pages_json)
    manifest = _read_json(pages_json)
    numbers = {page["pdf_page_number"] for page in manifest["pages"]}
    for number in layout:
        if number not in numbers:
            raise ValueError(f"PDF page {number} is not in {pages_json}")
    for page in manifest["pages"]:
        entry = layout.get(page["pdf_page_number"], {"role": "unreviewed"})
        page.pop("mdiv", None)
        page.pop("systems", None)
        page["role"] = entry["role"]
        page["printed_page"] = entry.get("printed_page")
        if entry["role"] == "music":
            page["mdiv"] = mdiv
            page["systems"] = entry["systems"]
    _write_json_if_changed(pages_json, manifest)
    return manifest


def _new_box(page: dict, entry: object) -> dict:
    if (not isinstance(entry, (list, tuple)) or len(entry) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in entry)):
        raise _BoxEditError(f"{page['page_id']}: {entry!r} is not a box. "
                            "Use four numbers: (left, top, right, bottom).", "malformed", entry=entry)
    try:
        left, top, right, bottom = (round(v) for v in entry)
    except (ValueError, OverflowError) as problem:
        raise _BoxEditError(f"{page['page_id']}: {entry!r} is not a box. "
                            "Use four numbers: (left, top, right, bottom).",
                            "malformed", entry=entry, problem=problem) from problem
    if left >= right or top >= bottom:
        raise _BoxEditError(f"{page['page_id']}: in {entry!r}, left must be smaller than right "
                            "and top smaller than bottom. The order is (left, top, right, bottom).",
                            "edges", entry=entry)
    if left < 0 or top < 0 or right > page["width"] or bottom > page["height"]:
        raise _BoxEditError(f"{page['page_id']}: {entry!r} reaches outside the page "
                            f"(the picture is {page['width']} × {page['height']} pixels).", "bounds", entry=entry)
    return dict(zip(_COORDS, (left, top, right, bottom)))


def _overlap(a: dict, b: dict) -> float:
    width = min(a["lrx"], b["lrx"]) - max(a["ulx"], b["ulx"])
    height = min(a["lry"], b["lry"]) - max(a["uly"], b["uly"])
    if width <= 0 or height <= 0:
        return 0.0
    area_a = (a["lrx"] - a["ulx"]) * (a["lry"] - a["uly"])
    area_b = (b["lrx"] - b["ulx"]) * (b["lry"] - b["uly"])
    return width * height / (area_a + area_b - width * height)


def edit_measure_boxes(
    pages_json: str | Path, page_id: str, *, add: tuple | list = (), remove: tuple | list = (),
) -> dict:
    """Rebuild boxes from detector indices and added pixel rectangles.

    Preserve the first response in ``boxes/<page_id>.original.json``.
    Empty corrections restore those bytes and remove the backup. Detector
    run metadata is never changed. Added boxes may not cover a kept box
    with intersection-over-union greater than 0.5.
    """
    pages_json = Path(pages_json)
    manifest = _read_json(pages_json)
    page = next((p for p in manifest["pages"] if p["page_id"] == page_id), None)
    if page is None or page.get("role") != "music":
        raise ValueError(f"{page_id}: expected a music page in {pages_json}")
    path = pages_json.parent / "boxes" / f"{page_id}.json"
    backup = path.with_name(f"{page_id}.original.json")
    if not path.is_file():
        raise ValueError(f"{page_id}: missing boxes file {path}")
    added = [_new_box(page, entry) for entry in add]
    removed = list(remove)
    original = _read_json(backup if backup.is_file() else path)
    boxes = _validate_boxes(original, page_id)
    count = len(boxes)
    for index in removed:
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < count:
            raise _BoxEditError(f"{page_id}: {index!r} is not a box number "
                                f"(this page has boxes 0 to {count - 1}).", "index", index=index, count=count)
    kept = [box for index, box in enumerate(boxes) if index not in removed]
    for box in added:
        for index, other in enumerate(boxes):
            if index not in removed and _overlap(box, other) > 0.5:
                raise _BoxEditError(f"{page_id}: {tuple(box.values())} covers most of box {index}.",
                                    "overlap", box=box, index=index)
    changed = False
    if not added and not removed:
        if backup.is_file():
            data = backup.read_bytes()
            if path.read_bytes() != data:
                _atomic_write(path, data)
                changed = True
            backup.unlink()
        edited = original
    else:
        edited = deepcopy(original)
        edited["measures"] = kept + added
        if not backup.is_file():
            _atomic_write(backup, path.read_bytes())
        changed = _write_json_if_changed(path, edited)
    return {"page_id": page_id, "boxes": str(path), "measures": len(edited["measures"]), "changed": changed}


def approve_alignment_review(
    alignment_json: str | Path, reviewer: str, *, date: str | local_date | None = None,
) -> int:
    """Approve pages for a stripped reviewer name; return the changed count.

    An approval for the same reviewer is preserved, including its date.
    """
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("reviewer must be non-empty text")
    reviewer = reviewer.strip()
    if date is None:
        date = local_date.today().isoformat()
    elif isinstance(date, local_date):
        date = date.isoformat()
    elif not isinstance(date, str):
        raise ValueError("date must be ISO date text or a datetime.date")
    alignment_json = Path(alignment_json)
    data = _read_json(alignment_json)
    changed = 0
    for entry in data.get("review", {}).values():
        if entry.get("status") != "approved" or entry.get("reviewer") != reviewer:
            entry.update(status="approved", reviewer=reviewer, date=date)
            changed += 1
    if changed:
        _write_json(alignment_json, data)
    return changed


def number_single_mdiv(text: str) -> str:
    """Add n="1" to the sole unnumbered mdiv start tag, preserving other text."""
    # Match whole XML tokens, including quoted > characters, and skip content
    # that can mention tags without introducing elements.
    tokens = re.compile(r'''<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<[^>"']*(?:(?:"[^"]*"|'[^']*')[^>"']*)*>''', re.S)
    matches = [m for m in tokens.finditer(text) if re.match(r"<mdiv(?=\s|/?>)", m[0])]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one <mdiv> start tag, found {len(matches)}")
    match = matches[0]
    tag = match[0]
    attributes = re.compile(r'''([^\s=<>/]+)\s*=\s*(?:"([^"]*)"|'([^']*)')''')
    if any(attr[1] == "n" for attr in attributes.finditer(tag)):
        return text
    cut = len(tag) - (2 if tag.endswith("/>") else 1)
    return text[:match.start()] + tag[:cut] + ' n="1"' + tag[cut:] + text[match.end():]


def _label(value: object, page_id: str, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or str(value) == "":
        raise ValueError(f"{page_id}: {field} must be a non-empty string or integer")
    return str(value)


def _load_pages(path: Path) -> dict:
    manifest = _read_json(path)
    if manifest.get("schema_version") != 1:
        raise ValueError(f"{path}: expected pages.json schema_version 1")
    _source_id(manifest.get("source_id"))
    if not isinstance(manifest.get("pages"), list):
        raise _PageReviewError(f"{path}: pages must be a list; review pages.json")
    ids, numbers = set(), set()
    for page in manifest["pages"]:
        page_id = page.get("page_id", "<missing page_id>")
        if not isinstance(page_id, str) or not _ID_PATTERN.fullmatch(page_id) or page_id in ids:
            raise ValueError(f"{page_id}: invalid or duplicate page_id")
        ids.add(page_id)
        number = page.get("pdf_page_number")
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0 or number in numbers:
            raise ValueError(f"{page_id}: invalid or duplicate pdf_page_number")
        numbers.add(number)
        for dimension in ("width", "height"):
            value = page.get(dimension)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{page_id}: {dimension} must be a positive integer")
        if not isinstance(page.get("image"), str) or not isinstance(page.get("sha256"), str):
            raise ValueError(f"{page_id}: image and sha256 are required")
        page["printed_page"] = (None if page.get("printed_page") is None else
                                _label(page["printed_page"], page_id, "printed_page"))
        page.setdefault("role", "unreviewed")
        if not isinstance(page["role"], str):
            raise ValueError(f"{page_id}: role must be text")
        if page["role"] != "music":
            if "systems" in page:
                raise _PageReviewError(f"{page_id}: non-music page has systems; check role and review pages.json")
            continue
        systems = page.get("systems")
        if not isinstance(systems, list) or not systems:
            raise _PageReviewError(f"{page_id}: music page needs non-empty systems; review pages.json")
        if "mdiv" in page:
            page["mdiv"] = _label(page["mdiv"], page_id, "mdiv")
        normalized = []
        for system in systems:
            if isinstance(system, dict):
                mdiv, labels = system.get("mdiv"), system.get("measures")
            else:
                mdiv, labels = page.get("mdiv"), system
            mdiv = _label(mdiv, page_id, "system mdiv")
            if not isinstance(labels, list) or not labels:
                raise ValueError(f"{page_id}: each system needs a non-empty measures list")
            normalized.append({"mdiv": mdiv, "measures": [_label(n, page_id, "measure label") for n in labels]})
        page["systems"] = normalized
    manifest["pages"].sort(key=lambda p: p["pdf_page_number"])
    if not any(p["role"] == "music" for p in manifest["pages"]):
        names = ", ".join(p["page_id"] for p in manifest["pages"])
        raise _PageReviewError(f"No music pages ({names}); review pages.json")
    return manifest


def _music_pages(manifest: dict) -> list[dict]:
    return [p for p in manifest["pages"] if p["role"] == "music"]


def _verify_image(page: dict, folder: Path, *, remedy: str = "review pages.json") -> Path:
    image = folder / page["image"]
    if not image.is_file() or _sha256(image) != page.get("image_sha256", page.get("sha256")):
        raise ValueError(f"{page['page_id']}: image hash changed or image missing; {remedy}")
    return image


def _validate_boxes(payload: dict, page_id: str) -> list[dict]:
    measures = payload.get("measures")
    if not isinstance(measures, list):
        raise ValueError(f"{page_id}: boxes must contain a measures list")
    for index, box in enumerate(measures):
        if not isinstance(box, dict) or any(
            isinstance(box.get(k), bool) or not isinstance(box.get(k), (int, float))
            or not math.isfinite(box[k]) for k in _COORDS
        ):
            raise ValueError(f"{page_id}: invalid box {index}; expected numeric ulx, uly, lrx, lry")
    return measures


def _cached_boxes(page: dict, folder: Path) -> tuple[Path, dict, str] | None:
    path = folder / "boxes" / f"{page['page_id']}.json"
    run_path = path.with_suffix(".run.json")
    run = _read_json(run_path) if run_path.exists() else None
    if run is not None and run.get("image_sha256") != page["sha256"]:
        raise ValueError(f"{page['page_id']}: saved boxes belong to other pixels (image_sha256 differs)")
    if not path.exists():
        return None
    payload = _read_json(path)
    _validate_boxes(payload, page["page_id"])
    source = "manual" if run is None else ("detector" if _sha256(path) == run.get("response_sha256")
                                           else "detector-edited")
    return path, payload, source


def detect_measure_boxes(
    pages_json: str | Path, *, allow_upload: bool = False, detector_url: str = DETECTOR_URL,
    timeout: int = 90, retries: int = 1,
) -> list[dict]:
    """Verify music-page pixels and reuse boxes, uploading only with opt-in.

    Responses are retained without modifying their fields. A response edited
    since its detector run is reported as ``detector-edited``; one without a
    run record is ``manual``.
    """
    pages_json = Path(pages_json)
    pages = _music_pages(_load_pages(pages_json))
    cached = []
    for page in pages:
        _verify_image(page, pages_json.parent)
        boxes = _cached_boxes(page, pages_json.parent)
        if boxes is None and not allow_upload:
            raise FileNotFoundError(f"{page['page_id']}: missing boxes/{page['page_id']}.json; "
                                    "set allow_upload=True to send the image to the detector")
        cached.append(boxes)
    records = []
    for page, boxes in zip(pages, cached):
        uploaded = boxes is None
        if boxes is None:
            image = _verify_image(page, pages_json.parent)
            try:
                payload = upload_image(image, detector_url, timeout, retries=retries, retry_delay=2)
            except ValueError as exc:
                raise _DetectorResponseError(str(exc)) from exc
            _validate_boxes(payload, page["page_id"])
            path = pages_json.parent / "boxes" / f"{page['page_id']}.json"
            _write_json(path, payload)
            _write_json(path.with_suffix(".run.json"), {
                "endpoint": detector_url, "created_at": datetime.now(timezone.utc).isoformat(),
                "image": page["image"], "image_sha256": page["sha256"],
                "response_sha256": _sha256(path), "measures": len(payload["measures"]),
            })
            source = "detector"
        else:
            path, payload, source = boxes
        records.append({"page_id": page["page_id"], "boxes": str(path), "source": source,
                        "measures": len(payload["measures"]), "uploaded": uploaded})
    return records


def _check_bbox(box: list[int], page: dict) -> None:
    if (not isinstance(box, list) or len(box) != 4
            or any(isinstance(value, bool) or not isinstance(value, int) for value in box)):
        raise ValueError(f"{page['page_id']}: bbox must be a list of four integer pixel coordinates")
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= page["width"] and 0 <= y1 < y2 <= page["height"]):
        raise ValueError(f"{page['page_id']}: invalid or out-of-bounds box {box} "
                         f"for {page['width']}x{page['height']} image")


def group_measure_boxes_into_systems(payload: dict, page: dict) -> list[list[dict]]:
    """Group boxes top to bottom, with each system ordered left to right.

    Each item contains ``box_index``, rounded pixel ``bbox`` and ``center_y``.
    """
    rows = []
    for index, box in enumerate(_validate_boxes(payload, page["page_id"])):
        bbox = [round(box[k]) for k in _COORDS]
        _check_bbox(bbox, page)
        rows.append({"box_index": index, "bbox": bbox, "center_y": (bbox[1] + bbox[3]) / 2})
    if not rows:
        return []
    threshold = 0.45 * median(row["bbox"][3] - row["bbox"][1] for row in rows)
    systems: list[list[dict]] = []
    for row in sorted(rows, key=lambda r: r["center_y"]):
        if not systems or abs(row["center_y"] - median(r["center_y"] for r in systems[-1])) > threshold:
            systems.append([])
        systems[-1].append(row)
    for system in systems:
        system.sort(key=lambda r: r["bbox"][0])
    return systems


_ordered_systems = group_measure_boxes_into_systems


def build_measure_alignment(pages_json: str | Path, *, output: str | Path | None = None) -> Path:
    """Gate system box counts, then write deterministic movement/region links.

    Reviews survive a rerun verbatim when both hashes match. Changed hashes
    reset the affected review and emit a warning. All count failures are
    reported together without writing an alignment.
    """
    pages_json = Path(pages_json)
    manifest = _load_pages(pages_json)
    output = Path(output) if output is not None else pages_json.parent / "alignment.json"
    prepared, failures = [], []
    for page in _music_pages(manifest):
        image = _verify_image(page, pages_json.parent)
        saved = _cached_boxes(page, pages_json.parent)
        if saved is None:
            raise FileNotFoundError(f"{page['page_id']}: missing boxes; run detect_measure_boxes or supply manual boxes")
        boxes, payload, _ = saved
        systems = _ordered_systems(payload, page)
        actual = [len(s) for s in systems]
        expected = [len(s["measures"]) for s in page["systems"]]
        if actual != expected:
            failures.append(f"{page['page_id']} (PDF page {page['pdf_page_number']}, "
                            f"printed page {page['printed_page']}): actual {actual}, expected {expected}")
        prepared.append((page, image, boxes, systems, _sha256(boxes)))
    if failures:
        raise _SystemCountError("System count gate failed; review boxes and pages.json:\n" + "\n".join(failures))
    previous = _read_json(output).get("review", {}) if output.exists() else {}
    pages, regions, review = [], [], {}
    occurrences: Counter = Counter()
    for page, image, boxes, systems, boxes_hash in prepared:
        page_id = page["page_id"]
        pages.append({"page_id": page_id, "image": _relative(image, output.parent),
                      "image_sha256": page["sha256"], "boxes": _relative(boxes, output.parent),
                      "boxes_sha256": boxes_hash, "systems": len(systems)})
        for system_number, (system, scope) in enumerate(zip(systems, page["systems"]), 1):
            for box, label in zip(system, scope["measures"]):
                key = scope["mdiv"], label
                occurrences[key] += 1
                regions.append({"mdiv": key[0], "measure_n": key[1], "occurrence": occurrences[key],
                                "page_id": page_id, "system": system_number, "bbox": box["bbox"],
                                "image_sha256": page["sha256"], "boxes_sha256": boxes_hash,
                                "box_index": box["box_index"]})
        old = previous.get(page_id)
        if old is not None and old.get("status") not in _REVIEW_STATUSES:
            raise ValueError(f"{page_id}: invalid review status {old.get('status')!r}")
        if old is not None and old.get("image_sha256") == page["sha256"] and old.get("boxes_sha256") == boxes_hash:
            review[page_id] = old
        else:
            entry = {"status": "unreviewed", "reviewer": None, "date": None, "notes": "",
                     "image_sha256": page["sha256"], "boxes_sha256": boxes_hash}
            if old is not None:
                reason = "image changed" if old.get("image_sha256") != page["sha256"] else "boxes changed"
                entry["reset_reason"] = reason
                warnings.warn(f"{page_id}: review reset ({reason})", UserWarning, stacklevel=2)
            review[page_id] = entry
    _write_json(output, {"schema_version": 1, "source_id": manifest["source_id"],
                         "pages_json": _relative(pages_json, output.parent), "pages": pages,
                         "regions": regions, "review": review})
    return output


def draw_alignment_overlays(
    alignment: str | Path, output_dir: str | Path | None = None,
) -> list[Path]:
    """Draw one full-size labelled PNG per aligned page after verifying pixels."""
    from PIL import Image, ImageDraw, ImageFont

    alignment = Path(alignment)
    data = _read_json(alignment)
    output_dir = Path(output_dir) if output_dir is not None else alignment.parent / "overlays"
    images = [_verify_image(p, alignment.parent, remedy="re-run build_measure_alignment") for p in data["pages"]]
    colors = [(20, 90, 210), (170, 70, 10), (0, 125, 85), (140, 40, 150), (20, 115, 155)]
    outputs = []
    for page, image_path in zip(data["pages"], images):
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        draw = ImageDraw.Draw(image, "RGBA")
        size = max(12, round(image.width / 80))
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", size)
        except OSError:
            font = ImageFont.load_default(size=size)
        for region in data["regions"]:
            if region["page_id"] != page["page_id"]:
                continue
            color = colors[(region["system"] - 1) % len(colors)]
            draw.rectangle(region["bbox"], fill=(*color, 16), outline=(*color, 235), width=max(1, size // 8))
            label = f"{region['mdiv']}/{region['measure_n']}"
            if region["occurrence"] > 1:
                label += f" ({region['occurrence']})"
            x, y = region["bbox"][:2]
            draw.text((x + 4, y + 4), label, font=font, fill=(*color, 255))
        path = output_dir / f"{page['page_id']}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        outputs.append(path)
    return outputs


class _MeiDocument(NamedTuple):
    root: ET.Element
    prolog: bytes
    epilog: bytes
    encoding: str
    crlf: bool
    root_tag: str
    namespaces: list[tuple[str, str, bool]]  # prefix, URI, declared on the root
    islands: dict[ET.Element, str]  # non-MEI subtrees inside MEI, as source text


def _xml_parser() -> ET.XMLParser:
    return ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))


def _read_mei(path: Path) -> _MeiDocument:
    data = path.read_bytes()
    root = ET.fromstring(data, parser=_xml_parser())
    encoding_match = re.match(br'<\?xml\s[^?]*encoding=[\'"]([^\'"]+)', data)
    encoding = encoding_match[1].decode("ascii") if encoding_match else "utf-8"
    # Expat byte offsets locate the root and each foreign subtree (such as the
    # humxml and MADS blocks of Verovio's Humdrum import) without mistaking
    # prolog comments or a DOCTYPE's internal subset for a start tag.
    namespaces, spans, open_elements, count = [], {}, [], 0
    probe = expat.ParserCreate(namespace_separator=" ")

    def declare(prefix: str | None, uri: str) -> None:
        namespaces.append((prefix or "", uri, count == 0))

    def start(name: str, attrs: dict) -> None:
        nonlocal count
        uri = name.rpartition(" ")[0]
        state = None
        if open_elements:
            _, _, parent_uri, parent_state = open_elements[-1]
            if parent_state:
                state = "inside"
            elif parent_uri == MEI[1:-1] and uri != parent_uri:
                state = "island"
        open_elements.append((count, probe.CurrentByteIndex, uri, state))
        count += 1

    def end(name: str) -> None:
        index, begin, _, state = open_elements.pop()
        if state == "island" or not open_elements:
            head = _TAG.match(data, begin)
            stop = head.end() if head[0].endswith(b"/>") else _TAG.match(data, probe.CurrentByteIndex).end()
            spans[index] = begin, stop

    probe.StartNamespaceDeclHandler = declare
    probe.StartElementHandler, probe.EndElementHandler = start, end
    probe.Parse(data, True)
    elements = [e for e in root.iter() if isinstance(e.tag, str)]
    if len(elements) != count:
        raise ValueError(f"{path}: element offsets do not match the parsed tree")
    begin, stop = spans.pop(0)

    def source(a: int, b: int) -> str:
        return data[a:b].decode(encoding).replace("\r\n", "\n")

    return _MeiDocument(root, data[:begin], data[stop:], encoding, b"\r\n" in data,
                        source(begin, _TAG.match(data, begin).end()), namespaces,
                        {elements[i]: source(a, b) for i, (a, b) in spans.items()})


def _tostring(root: ET.Element, namespaces: list[tuple[str, str, bool]]) -> str:
    """Serialize with the file's prefixes and MEI as default namespace, leaving ET's registry as it was."""
    saved = dict(ET._namespace_map)
    try:
        # Root declarations go last, so they win a prefix that is bound twice.
        for prefix, uri, _ in sorted(namespaces, key=lambda n: n[2]):
            if prefix and prefix != "xml" and uri != MEI[1:-1] and not re.fullmatch(r"ns\d+", prefix):
                ET.register_namespace(prefix, uri)
        ET.register_namespace("", MEI[1:-1])
        return ET.tostring(root, encoding="unicode")
    finally:
        ET._namespace_map.clear()
        ET._namespace_map.update(saved)


def _same_tree(a: ET.Element, b: ET.Element) -> bool:
    return (a.tag == b.tag and a.attrib == b.attrib and (a.text or "") == (b.text or "")
            and (a.tail or "") == (b.tail or "") and len(a) == len(b) and all(map(_same_tree, a, b)))


def _serialize(document: _MeiDocument, verbatim: bool) -> bytes | None:
    """Return the file bytes, or None if they would not parse back to the same tree."""
    root, markers = document.root, {}
    if verbatim:
        parents = {child: parent for parent in root.iter() for child in parent}
        for number, (element, source) in enumerate(document.islands.items()):
            parent = parents.get(element)
            if parent is not None:  # not inside a replaced facsimile
                marker = ET.PI(f"camat-verbatim-{number}")
                marker.tail = element.tail
                index = list(parent).index(element)
                parent[index] = marker
                markers[f"<?{marker.text}?>"] = parent, index, element, source
    try:
        text = _tostring(root, document.namespaces)
    finally:
        for parent, index, element, _ in markers.values():
            parent[index] = element
    if verbatim:
        # Keep the source's root start tag, so the islands' prefixes stay bound,
        # and add what ET declared beyond it.
        head = text.index(">") + 1
        declared = {(prefix, uri) for prefix, uri, on_root in document.namespaces if on_root}
        extra = "".join(m[0] for m in _XMLNS.finditer(text[:head]) if (m[1] or "", html.unescape(m[2])) not in declared)
        tag = document.root_tag
        cut = len(tag) - (2 if tag.endswith("/>") else 1)
        text = tag[:cut] + extra + tag[cut:] + text[head:]
        for token, (_, _, _, source) in markers.items():
            if text.count(token) != 1:
                return None
            text = text.replace(token, source)
    if document.crlf:
        text = text.replace("\n", "\r\n")
    data = document.prolog + text.encode(document.encoding, "xmlcharrefreplace") + document.epilog
    try:
        return data if _same_tree(ET.fromstring(data, parser=_xml_parser()), root) else None
    except ET.ParseError:
        return None


def _write_mei(document: _MeiDocument, output: Path) -> None:
    data = _serialize(document, verbatim=True)
    if data is None:
        warnings.warn(f"{output}: XML in other namespaces could not be kept byte for byte; "
                      "it is written with generated prefixes", stacklevel=3)
        data = _serialize(document, verbatim=False)
    if data is None:
        raise ValueError(f"{output}: the MEI namespaces cannot be serialized faithfully; output not written")
    _atomic_write(output, data)


def _body_digest(root: ET.Element) -> str:
    body = root.find(f".//{MEI}body")
    if body is None:
        raise ValueError("MEI needs a <body>")
    body = deepcopy(body)
    for element in body.iter():
        element.attrib.pop("facs", None)
        if element.text is not None and not element.text.strip():
            element.text = None
        if element.tail is not None and not element.tail.strip():
            element.tail = None
    canonical = ET.canonicalize(ET.tostring(body, encoding="unicode"), with_comments=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _scope(root: ET.Element) -> dict[ET.Element, str | None]:
    body = root.find(f".//{MEI}body")
    if body is None:
        raise ValueError("MEI needs a <body>")
    scope = {}

    def walk(element: ET.Element, mdiv: str | None) -> None:
        if element.tag == MEI + "mdiv":
            mdiv = element.get("n")
        scope[element] = mdiv
        for child in element:
            walk(child, mdiv)

    walk(body, None)
    return scope


def _pair_measures(root: ET.Element, regions: list[dict]) -> tuple:
    scope = _scope(root)
    mei_mdivs = list(dict.fromkeys(e.get("n") for e in scope if e.tag == MEI + "mdiv" and e.get("n") is not None))
    region_mdivs = list(dict.fromkeys(r["mdiv"] for r in regions))
    linked = [n for n in mei_mdivs if n in region_mdivs]
    if not linked:
        raise ValueError(f"No linked movements: MEI mdiv/@n {mei_mdivs}; facsimile mdivs {region_mdivs}")
    measures = [e for e, movement in scope.items() if e.tag == MEI + "measure" and movement in linked]
    by_key, by_region = defaultdict(list), defaultdict(list)
    for measure in measures:
        if measure.get("n") is None:
            raise ValueError(f"mdiv {scope[measure]}: measure {measure.get(XML_ID, '<no xml:id>')} lacks @n")
        by_key[scope[measure], measure.get("n")].append(measure)
    for index, region in enumerate(regions):
        if region["mdiv"] in linked:
            by_region[region["mdiv"], region["measure_n"]].append(index)
    misses = []
    for key in by_key.keys() - by_region.keys():
        misses.append(f"MEI measure {key[0]}/{key[1]} has no region")
    for key in by_region.keys() - by_key.keys():
        misses.append(f"region {key[0]}/{key[1]} has no MEI measure")
    if misses:
        raise _IntegrationGateError("Measure/region gate failed: " + "; ".join(sorted(misses)))
    assignments, region_measures = {}, {}
    for key, group in by_key.items():
        indices = sorted(by_region[key], key=lambda i: regions[i]["occurrence"])
        if len(group) == 1:
            assignments[group[0]] = indices
            for index in indices:
                region_measures[index] = group[0]
        elif len(group) == len(indices):
            for measure, index in zip(group, indices):
                assignments[measure] = [index]
                region_measures[index] = measure
        else:
            raise ValueError(f"{key[0]}/{key[1]}: {len(group)} MEI measures vs {len(indices)} regions; "
                             "need one MEI measure or equal counts")
    return linked, measures, assignments, region_measures, scope


def _load_alignment(path: Path, pages_json: Path, manifest: dict) -> dict:
    data = _read_json(path)
    remedy = "re-run build_measure_alignment"
    if data.get("schema_version") != 1 or data.get("source_id") != manifest["source_id"]:
        raise ValueError(f"Alignment source/schema differs from pages.json; {remedy}")
    current = {p["page_id"]: p for p in _music_pages(manifest)}
    aligned = {p["page_id"]: p for p in data["pages"]}
    if current.keys() != aligned.keys():
        raise ValueError(f"Alignment pages differ from pages.json; {remedy}")
    for page_id, page in aligned.items():
        reviewed = current[page_id]
        image = _verify_image(page, path.parent, remedy=remedy)
        if page["image_sha256"] != reviewed["sha256"] or image.resolve() != (pages_json.parent / reviewed["image"]).resolve():
            raise ValueError(f"{page_id}: alignment image differs from pages.json; {remedy}")
        boxes = path.parent / page["boxes"]
        if not boxes.is_file() or _sha256(boxes) != page["boxes_sha256"]:
            raise ValueError(f"{page_id}: alignment boxes hash changed or boxes missing; {remedy}")
    for region in data["regions"]:
        page_id = region["page_id"]
        if page_id not in aligned:
            raise ValueError(f"{page_id}: region has no aligned page; {remedy}")
        for key in ("image_sha256", "boxes_sha256"):
            if region.get(key) != aligned[page_id][key]:
                raise ValueError(f"{page_id}: region {key} is stale; {remedy}")
        _check_bbox(region["bbox"], current[page_id])
    # Labels come from pages.json; an edit there after aligning would make
    # integration and write_page_breaks disagree about which box is which bar.
    fields = ("mdiv", "measure_n", "occurrence", "page_id", "system")
    if [tuple(r[k] for k in fields) for r in data["regions"]] != [
            tuple(r[k] for k in fields) for r in _manifest_regions(manifest)]:
        raise ValueError(f"pages.json systems changed since the alignment was built; {remedy}")
    return data


def _leading_space(parent: ET.Element, index: int) -> str:
    value = parent.text if index == 0 else parent[index - 1].tail
    return value if value and not value.strip() else ""


def _format_facsimile(element: ET.Element, parent: ET.Element, index: int) -> None:
    lead = _leading_space(parent, index)
    if "\n" not in lead:
        return
    indent = lead.rsplit("\n", 1)[1]
    parent_indent = (parent.tail or "").rsplit("\n", 1)[-1]
    step = indent[len(parent_indent):] if indent.startswith(parent_indent) else ""
    step = step or "   "

    def format_children(node: ET.Element, padding: str) -> None:
        if not len(node):
            return
        node.text = "\n" + padding + step
        for child in node:
            format_children(child, padding + step)
            child.tail = "\n" + padding + step
        node[-1].tail = "\n" + padding

    format_children(element, indent)


def _update_facs(element: ET.Element, removed_ids: set[str], additions: list[str]) -> None:
    tokens = [t for t in element.get("facs", "").split() if not (t.startswith("#") and t[1:] in removed_ids)]
    tokens.extend(t for t in additions if t not in tokens)
    if tokens:
        element.set("facs", " ".join(tokens))
    else:
        element.attrib.pop("facs", None)


def _check_ids(root: ET.Element, new: list[ET.Element], excluded: set[ET.Element]) -> None:
    existing = {e.get(XML_ID) for e in root.iter() if e not in excluded and e.get(XML_ID)}
    added = [e.get(XML_ID) for node in new for e in node.iter() if e.get(XML_ID)]
    duplicates = existing.intersection(added) | {ident for ident, count in Counter(added).items() if count > 1}
    if duplicates:
        raise ValueError("New xml:id collision: " + ", ".join(sorted(duplicates)))


def integrate_pdf_facsimile(
    mei: str | Path, pages_json: str | Path, alignment_json: str | Path, output_mei: str | Path,
    *, source_ref: str | None = None,
) -> dict:
    """Add or replace this PDF's facsimile, preserving notation and other links.

    Measures pair by movement, label and occurrence. One encoded measure may
    have several regions. Pending or stale reviews are reported, not blocked.
    Graphic paths are relative to the output MEI, including for in-place writes.
    """
    mei, pages_json, alignment_json, output_mei = map(Path, (mei, pages_json, alignment_json, output_mei))
    manifest = _load_pages(pages_json)
    alignment = _load_alignment(alignment_json, pages_json, manifest)
    document = _read_mei(mei)
    root = document[0]
    before = _body_digest(root)
    regions = alignment["regions"]
    linked, measures, assignments, _, scope = _pair_measures(root, regions)
    music = root.find(MEI + "music")
    if music is None:
        raise ValueError("MEI needs a <music> element")
    facsimile_id = "facsimile-" + manifest["source_id"]
    facsimiles = music.findall(MEI + "facsimile")
    owned = [e for e in facsimiles if e.get(XML_ID) == facsimile_id]
    if len(owned) > 1:
        raise ValueError(f"Duplicate owned facsimile {facsimile_id}")
    old = owned[0] if owned else None
    removed = set(old.iter()) if old is not None else set()
    removed_ids = {e.get(XML_ID) for e in removed if e.get(XML_ID)}
    facsimile = ET.Element(MEI + "facsimile", {XML_ID: facsimile_id})
    if source_ref is not None:
        facsimile.set("decls", "#" + source_ref)
    page_regions: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for index, region in enumerate(regions):
        page_regions[region["page_id"]].append((index, region))
    zone_ids, used_pages = {}, []
    for page in _music_pages(manifest):
        entries = page_regions[page["page_id"]]
        if not any(r["mdiv"] in linked for _, r in entries):
            continue
        page_id = page["page_id"]
        used_pages.append(page_id)
        attrs = {XML_ID: f"surface-{page_id}"}
        if page["printed_page"] is not None:
            attrs["n"] = page["printed_page"]
        attrs.update(ulx="0", uly="0", lrx=str(page["width"] - 1), lry=str(page["height"] - 1))
        surface = ET.SubElement(facsimile, MEI + "surface", attrs)
        ET.SubElement(surface, MEI + "graphic", {
            XML_ID: f"graphic-{page_id}", "target": _relative(pages_json.parent / page["image"], output_mei.parent),
            "width": str(page["width"]), "height": str(page["height"]),
        })
        for number, (index, region) in enumerate(entries, 1):
            if region["mdiv"] not in linked:
                continue
            zone_id = f"zone-{page_id}-{number:03d}"
            zone_ids[index] = zone_id
            ET.SubElement(surface, MEI + "zone", {XML_ID: zone_id, "type": "measure",
                          **dict(zip(_COORDS, map(str, region["bbox"]))),
                          "label": f"{region['mdiv']}/{region['measure_n']}"})
    _check_ids(root, [facsimile], removed)
    additions = {measure: ["#" + zone_ids[i] for i in indices] for measure, indices in assignments.items()}
    pb_linked, pb_not_at_page_start = 0, []
    next_measures = {}
    following = None
    for element, movement in reversed(list(scope.items())):
        if element.tag == MEI + "measure":
            following = element
        elif element.tag == MEI + "pb" and movement in linked:
            next_measures[element] = following
    pb_position = 0
    for element, movement in scope.items():
        if element.tag != MEI + "pb" or movement not in linked:
            continue
        pb_position += 1
        measure = next_measures.get(element)
        first = assignments[measure][0] if measure in assignments else None
        if first is not None:
            region = regions[first]
            is_start = region["system"] == 1 and page_regions[region["page_id"]][0][0] == first
        else:
            is_start = False
        if is_start:
            additions[element] = ["#surface-" + regions[first]["page_id"]]
            pb_linked += 1
        else:
            pb_not_at_page_start.append(element.get(XML_ID) or f"pb at position {pb_position}")
    for element in root.iter():
        if "facs" in element.attrib or element in additions:
            _update_facs(element, removed_ids, additions.get(element, []))
    children = list(music)
    if old is not None:
        index = children.index(old)
        facsimile.tail = old.tail
        _format_facsimile(facsimile, music, index)
        music.remove(old)
    else:
        index = children.index(facsimiles[-1]) + 1 if facsimiles else next(
            (i for i, e in enumerate(children) if e.tag == MEI + "body"), len(children))
        _format_facsimile(facsimile, music, index)
        facsimile.tail = _leading_space(music, index)
    music.insert(index, facsimile)
    if _body_digest(root) != before:
        raise _IntegrationGateError("Body gate failed: facsimile integration changed the score; output not written")
    reviews = alignment.get("review", {})
    aligned_pages = {p["page_id"]: p for p in alignment["pages"]}
    unreviewed = []
    for page_id in used_pages:
        review, page = reviews.get(page_id, {}), aligned_pages[page_id]
        if review.get("status") != "approved" or any(review.get(k) != page[k] for k in ("image_sha256", "boxes_sha256")):
            unreviewed.append(page_id)
    _write_mei(document, output_mei)
    return {"output_mei": str(output_mei), "mdivs": linked, "surfaces": len(used_pages), "zones": len(zone_ids),
            "measures_linked": len(measures), "split_measures": sum(len(v) > 1 for v in assignments.values()),
            "pb_linked": pb_linked, "pb_not_at_page_start": pb_not_at_page_start,
            "other_facsimiles": len(facsimiles) - len(owned), "unreviewed_pages": unreviewed}


def _manifest_regions(manifest: dict) -> list[dict]:
    regions, occurrences = [], Counter()
    for page in _music_pages(manifest):
        for number, system in enumerate(page["systems"], 1):
            for label in system["measures"]:
                key = system["mdiv"], label
                occurrences[key] += 1
                regions.append({"mdiv": key[0], "measure_n": key[1], "occurrence": occurrences[key],
                                "page_id": page["page_id"], "system": number})
    return regions


def write_page_breaks(mei: str | Path, pages_json: str | Path, output_mei: str | Path) -> dict:
    """Replace linked movements' page/system breaks with the reviewed layout.

    The manifest must follow the encoded measure sequence. A continuation of
    one split MEI measure gets no break. Score definitions directly before a
    measure follow its new break, and missing surfaces are reported.
    """
    mei, pages_json, output_mei = map(Path, (mei, pages_json, output_mei))
    manifest = _load_pages(pages_json)
    regions = _manifest_regions(manifest)
    document = _read_mei(mei)
    root = document[0]
    linked, measures, assignments, region_measures, scope = _pair_measures(root, regions)
    sequence, seen = [], set()
    for index in range(len(regions)):
        measure = region_measures.get(index)
        if measure is not None and measure not in seen:
            sequence.append(measure)
            seen.add(measure)
    for index in range(max(len(sequence), len(measures))):
        listed = sequence[index] if index < len(sequence) else None
        encoded = measures[index] if index < len(measures) else None
        if listed is not encoded:
            def describe(e: ET.Element | None) -> str:
                return "<end>" if e is None else f"{scope[e]}/{e.get('n')} ({e.get(XML_ID, 'no xml:id')})"
            raise ValueError(f"Measure sequence diverges at position {index + 1}: "
                             f"pages.json {describe(listed)}, MEI {describe(encoded)}")
    parents = {child: parent for parent in root.iter() for child in parent}
    removed = [e for e, movement in scope.items() if movement in linked and e.tag in {MEI + "pb", MEI + "sb"}]
    surfaces = {e.get(XML_ID) for e in root.iter(MEI + "surface")}
    pages = {p["page_id"]: p for p in _music_pages(manifest)}
    starts, split_starts, missing_surfaces = [], [], []
    system_seen = set()
    for index, region in enumerate(regions):
        key = region["page_id"], region["system"]
        if key in system_seen:
            continue
        system_seen.add(key)
        if index not in region_measures:
            continue
        measure = region_measures[index]
        if assignments[measure][0] != index:
            split_starts.append({k: region[k] for k in ("page_id", "system", "mdiv", "measure_n")})
            continue
        page_id, number = key
        attrs = {XML_ID: f"pb-{page_id}" if number == 1 else f"sb-{page_id}-s{number:02d}"}
        if number == 1:
            if pages[page_id]["printed_page"] is not None:
                attrs["n"] = pages[page_id]["printed_page"]
            surface_id = "surface-" + page_id
            if surface_id in surfaces:
                attrs["facs"] = "#" + surface_id
            else:
                missing_surfaces.append(page_id)
        starts.append((measure, ET.Element(MEI + ("pb" if number == 1 else "sb"), attrs)))
    _check_ids(root, [e for _, e in starts], set(removed))
    for element in removed:
        parent = parents[element]
        index = list(parent).index(element)
        if element.tail and element.tail.strip():
            if index:
                parent[index - 1].tail = (parent[index - 1].tail or "") + element.tail
            else:
                parent.text = (parent.text or "") + element.tail
        elif index == len(parent) - 1 and element.tail is not None:
            # A last child's tail holds the parent's closing-tag indentation.
            if index:
                parent[index - 1].tail = element.tail
            else:
                parent.text = element.tail
        parent.remove(element)
    for measure, element in starts:
        parent = parents[measure]
        children = list(parent)
        index = children.index(measure)
        scan = index - 1
        while scan >= 0:
            sibling = children[scan]
            if sibling.tag == MEI + "scoreDef":
                index = scan
            elif isinstance(sibling.tag, str) and sibling.tag not in {MEI + "pb", MEI + "sb"}:
                break
            scan -= 1
        element.tail = _leading_space(parent, index)
        parent.insert(index, element)
    _write_mei(document, output_mei)
    return {"pb": sum(e.tag == MEI + "pb" for _, e in starts), "sb": sum(e.tag == MEI + "sb" for _, e in starts),
            "removed": len(removed), "split_system_starts": split_starts,
            "pb_without_surface": missing_surfaces, "output_mei": str(output_mei)}


def main(argv: list[str] | None = None) -> int:
    """Run the render, detect, align, integrate or breaks command."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render", help="Rasterize and verify every physical page")
    render.add_argument("pdf")
    render.add_argument("--output-dir", required=True)
    render.add_argument("--dpi", type=int, default=300)
    render.add_argument("--source-id")
    detect = commands.add_parser("detect", help="Reuse saved boxes or explicitly upload music pages")
    detect.add_argument("pages_json")
    detect.add_argument("--allow-upload", action="store_true")
    detect.add_argument("--detector-url", default=DETECTOR_URL)
    detect.add_argument("--timeout", type=int, default=90)
    align = commands.add_parser("align", help="Align boxes and draw review overlays")
    align.add_argument("pages_json")
    align.add_argument("--no-overlays", action="store_true")
    integrate = commands.add_parser("integrate", help="Link a PDF facsimile without changing notation")
    for name in ("mei", "pages_json", "alignment_json", "output_mei"):
        integrate.add_argument(name)
    integrate.add_argument("--source-ref")
    breaks = commands.add_parser("breaks", help="Write reviewed page and system breaks")
    for name in ("mei", "pages_json", "output_mei"):
        breaks.add_argument(name)
    args = parser.parse_args(argv)
    try:
        if args.command == "render":
            result = render_pdf_pages(args.pdf, args.output_dir, args.dpi, source_id=args.source_id)
            print(f"Verified {result['page_count']} pages: {Path(args.output_dir) / 'pages.json'}")
        elif args.command == "detect":
            records = detect_measure_boxes(args.pages_json, allow_upload=args.allow_upload,
                                           detector_url=args.detector_url, timeout=args.timeout)
            print(f"Verified boxes for {len(records)} pages ({sum(r['uploaded'] for r in records)} uploaded)")
        elif args.command == "align":
            path = build_measure_alignment(args.pages_json)
            outputs = [] if args.no_overlays else draw_alignment_overlays(path)
            print(f"Alignment: {path}; {len(outputs)} overlays")
        elif args.command == "integrate":
            result = integrate_pdf_facsimile(args.mei, args.pages_json, args.alignment_json, args.output_mei,
                                             source_ref=args.source_ref)
            print(f"Linked {result['measures_linked']} measures, {result['zones']} zones, "
                  f"{len(result['unreviewed_pages'])} unreviewed pages: {result['output_mei']}")
        else:
            result = write_page_breaks(args.mei, args.pages_json, args.output_mei)
            print(f"Wrote {result['pb']} page breaks and {result['sb']} system breaks: {result['output_mei']}")
    except Exception as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
