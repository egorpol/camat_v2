"""Build a local review page: one card for each reading the editor must confirm.

Each card shows the source at the card's bars (a crop of the facsimile), the
bars as they were at a git ref ("before") and as they are in the working tree
("after"), both rendered by Verovio, and a description. The editor marks each
card ok or problem and may add a note; the marks stay in the browser
(``localStorage``), and "Copy summary" puts them on the clipboard as lines such
as ``Op. II/3, m. 229: ok``. A card with ``"rows": true`` shows one row per bar
instead, each with its own marks and a line listing the events that changed
(matched by ``xml:id``).

Crops come from each bar's ``@facs`` zone. A IIIF graphic is cut by the image
server: the zone, scaled by the width in the server's ``info.json`` (masters
are often larger than the ``<graphic>``), as a pixel region. A local page image
or any other image URL is cut here. Downloads are cached in camat's download
cache.

Everything is checked before anything is written, and OUT must not exist: each
review goes into a new folder. Usage: ``camat-review-page review.json OUT``,
then open ``OUT/index.html`` in a browser.
"""
from __future__ import annotations

import argparse
import html
from importlib.resources import files
import io
import json
import os
from pathlib import Path
import re
import shutil
from string import Template
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from . import __version__
from .web_edition import VEROVIO_OPTIONS as SITE_VEROVIO_OPTIONS

MEI = "{http://www.music-encoding.org/ns/mei}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEMPLATE_FILES = ("index.html", "review.css", "review.js")
STATUSES = {"check": "to check", "partly": "partly confirmed", "confirmed": "confirmed"}
# The web edition's layout, larger, without a title, at a width set per card. Breaks are
# Verovio's own: with encoded ones, a selection across a <pb/> loses the bars after it.
VEROVIO_OPTIONS = {**SITE_VEROVIO_OPTIONS, "breaks": "auto", "header": "none", "scale": 50}
WIDTH_ONE_BAR, WIDTH_BARS, WIDTH_ROW = 1000, 1800, 900
# Graphic pixels around the zones: left, top, right, bottom (figures sit under the bass).
CROP_PADDING = (200, 80, 200, 240)
CROP_SIZE = "!1400,1600"
LABELS = {"source": "Source", "after": "now"}
# Events whose label is their text rather than a pitch or a duration.
_TEXT_EVENTS = {"harm", "fb", "f", "dir", "dynam", "tempo", "syl", "verse", "rend"}
_ACCID = {"s": "♯", "f": "♭", "n": "♮", "ss": "𝄪", "x": "𝄪", "ff": "𝄫"}
_DIFF_LIMIT = 12

_KEYS = {"$schema", "version", "title", "description", "storage_key", "before_ref", "labels", "verovio", "crop", "cards"}
_LABEL_KEYS = {"source", "before", "after"}
_CROP_KEYS = {"padding", "size"}
_CARD_KEYS = {"id", "label", "mei", "measures", "description", "status", "images", "rows", "width"}
_IMAGE_KEYS = {"src", "caption"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_STORAGE_KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
# IIIF Image API sizes this builder can also apply to a local crop.
_SIZE = re.compile(r"(?:max|full|!?[1-9][0-9]*,[1-9][0-9]*|[1-9][0-9]*,|,[1-9][0-9]*)\Z")
_IIIF_REQUEST = re.compile(r"/full/[^/]+/[^/]+/(?P<quality>[^/.]+)\.(?P<format>[A-Za-z0-9]+)\Z")


class ReviewSpecError(ValueError):
    """The review spec or its inputs have problems; nothing was written."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        count = len(self.problems)
        super().__init__(f"{count} problem{'s' if count != 1 else ''} in the review spec:\n"
                         + "\n".join(f"  - {p}" for p in self.problems))


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _unknown(config: dict, allowed: set[str], where: str, problems: list[str]) -> None:
    for key in sorted(set(config) - allowed):
        problems.append(f"{where}{key}: unknown key (expected one of {', '.join(sorted(allowed))})")


def _text(config: dict, key: str, problems: list[str], *, where: str = "", default: str = "") -> str:
    value = config.get(key, default)
    if not isinstance(value, str):
        problems.append(f"{where}{key}: expected text, got {type(value).__name__}")
        return default
    return value


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


class _Version:
    """One state of an MEI file: its text, its bars and, once needed, a Verovio toolkit."""

    def __init__(self, text: str):
        self.text = text
        self.root = ET.fromstring(text.encode("utf-8"))
        self.measures = list(self.root.iter(MEI + "measure"))
        self._toolkit = None

    def select(self, first: str, last: str) -> list[ET.Element] | str:
        """The bars from ``first`` to ``last`` (``@n`` or ``#xml:id``), or why there are none."""
        indexes = []
        for token in (first, last):
            if token.startswith("#"):
                found = [i for i, m in enumerate(self.measures) if m.get(XML_ID) == token[1:]]
            else:
                found = [i for i, m in enumerate(self.measures) if m.get("n") == token]
            if not found:
                return f"no bar {token}"
            if len(found) > 1:
                ids = ", ".join("#" + (self.measures[i].get(XML_ID) or "?") for i in found[:4])
                return f"{len(found)} bars have n={token!r} ({ids}); give xml:ids instead, as [\"#first\", \"#last\"]"
            indexes.append(found[0])
        if indexes[1] < indexes[0]:
            return f"bar {last} comes before bar {first}"
        return self.measures[indexes[0]:indexes[1] + 1]

    def render(self, first: ET.Element, last: ET.Element, width: int, options: dict) -> list[str]:
        if self._toolkit is None:
            import verovio

            self._toolkit = verovio.toolkit()
            self._toolkit.setOptions(options)
            if not self._toolkit.loadData(self.text):
                raise ValueError("Verovio could not load it")
        tk = self._toolkit
        tk.setOptions({"pageWidth": width})
        tk.select({"start": first.get(XML_ID), "end": last.get(XML_ID)})
        tk.redoLayout()
        return [tk.renderToSVG(page) for page in range(1, tk.getPageCount() + 1)]


def _read_config(spec: str | Path | dict, base_dir: str | Path | None) -> tuple[dict, Path]:
    if isinstance(spec, dict):
        return spec, Path(base_dir or Path.cwd()).resolve()
    path = Path(spec).resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewSpecError([f"{path}: cannot read the review spec ({exc})"]) from exc
    if not isinstance(data, dict):
        raise ReviewSpecError([f"{path}: expected a JSON object"])
    return data, Path(base_dir).resolve() if base_dir else path.parent


def _git_show(path: Path, ref: str) -> str:
    result = subprocess.run(["git", "-C", str(path.parent), "show", f"{ref}:./{path.name}"],
                            capture_output=True, check=False)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ValueError(message[0] if message else f"git show failed ({result.returncode})")
    return result.stdout.decode("utf-8")


def _measures(value: object) -> tuple[str, str] | None:
    """``"12"``, ``"12-14"`` or ``[first, last]`` with ``@n`` values or ``#xml:id``s."""
    if isinstance(value, str) and value.strip():
        first, _, last = value.strip().partition("-")
        return (first, last or first) if first else None
    if (isinstance(value, list) and 1 <= len(value) <= 2 and all(isinstance(v, str) and v for v in value)):
        return value[0], value[-1]
    return None


def _surfaces(root: ET.Element) -> tuple[dict, dict]:
    """Surfaces with their graphic, and each zone's surface and box."""
    surfaces, zones = {}, {}
    for surface in root.iter(MEI + "surface"):
        graphic = surface.find(MEI + "graphic")
        if graphic is None:
            continue
        surfaces[surface.get(XML_ID)] = {
            "id": surface.get(XML_ID), "target": graphic.get("target") or "",
            "width": graphic.get("width"), "height": graphic.get("height"),
        }
        for zone in surface.iter(MEI + "zone"):
            try:
                box = tuple(int(float(zone.get(a))) for a in ("ulx", "uly", "lrx", "lry"))
            except (TypeError, ValueError):
                continue
            zones[zone.get(XML_ID)] = (surface.get(XML_ID), box)
    return surfaces, zones


def _crop_jobs(bars: list[ET.Element], surfaces: dict, zones: dict, padding: tuple) -> tuple[list[dict], list[str]]:
    """One crop per surface: the union of the bars' zones on it, padded. Also the bars without a zone."""
    boxes: dict[str, list[int]] = {}
    missing = []
    for bar in bars:
        refs = [ref.removeprefix("#") for ref in (bar.get("facs") or "").split()]
        found = [zones[ref] for ref in refs if ref in zones]
        if not found:
            missing.append(bar.get("n") or bar.get(XML_ID) or "?")
        for surface_id, (ulx, uly, lrx, lry) in found:
            box = boxes.setdefault(surface_id, [ulx, uly, lrx, lry])
            box[:] = [min(box[0], ulx), min(box[1], uly), max(box[2], lrx), max(box[3], lry)]
    jobs = []
    for surface_id, (ulx, uly, lrx, lry) in boxes.items():
        surface = surfaces[surface_id]
        left, top, right, bottom = padding
        box = [max(0, ulx - left), max(0, uly - top), lrx + right, lry + bottom]
        if (surface["width"] or "").isdigit() and (surface["height"] or "").isdigit():
            box[2], box[3] = min(box[2], int(surface["width"])), min(box[3], int(surface["height"]))
        jobs.append({"surface": surface, "box": box})
    return jobs, missing


def _download(url: str) -> Path:
    from .music_utils import get_file_path

    return Path(get_file_path(url, timeout_seconds=60, use_cache=True))


def _fit(image, size: str):
    """Apply a IIIF size (``max``, ``w,``, ``,h``, ``w,h``, ``!w,h``) to a Pillow image."""
    if size in ("max", "full"):
        return image
    keep_ratio = size.startswith("!")
    width, height = (int(v) if v else None for v in size.lstrip("!").split(","))
    if keep_ratio:
        image = image.copy()
        image.thumbnail((width, height))
        return image
    if width is None:
        width = round(image.width * height / image.height)
    if height is None:
        height = round(image.height * width / image.width)
    return image.resize((width, height))


def _crop(job: dict, mei_path: Path, size: str) -> bytes:
    """The JPEG bytes of one crop."""
    from PIL import Image

    surface, (x0, y0, x1, y1) = job["surface"], job["box"]
    target = surface["target"]
    parts = urlsplit(target)
    request = _IIIF_REQUEST.search(parts.path) if parts.scheme in ("http", "https") else None
    if request and (surface["width"] or "").isdigit():
        base = f"{parts.scheme}://{parts.netloc}{parts.path[:request.start()]}"
        info = json.loads(_download(f"{base}/info.json").read_text(encoding="utf-8"))
        scale = int(info["width"]) / int(surface["width"])
        region = ",".join(str(round(v * scale)) for v in (x0, y0, x1 - x0, y1 - y0))
        data = _download(f"{base}/{region}/{size}/0/{request['quality']}.{request['format']}").read_bytes()
        if request["format"].lower() in ("jpg", "jpeg"):
            return data
        image = Image.open(io.BytesIO(data))
    else:
        if parts.scheme in ("http", "https"):
            path = _download(target)
        else:
            path = Path(target).expanduser()
            path = path if path.is_absolute() else (mei_path.parent / path)
        page = Image.open(path)
        scale = page.width / int(surface["width"]) if (surface["width"] or "").isdigit() else 1.0
        image = _fit(page.crop(tuple(round(v * scale) for v in (x0, y0, x1, y1))), size)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def _context(element: ET.Element, parents: dict) -> dict[str, str]:
    """Staff and layer of an event: its own ``@staff`` or those of its ancestors."""
    found = {}
    node = element
    while node is not None:
        name = _local(node.tag)
        if name in ("staff", "layer") and name not in found and node.get("n"):
            found[name] = node.get("n")
        node = parents.get(node)
    if element.get("staff"):
        found["staff"] = element.get("staff")
    return found


def _events(measure: ET.Element | None) -> dict[str, tuple[str, dict, str]]:
    """Each element with an ``xml:id`` in a bar: tag, attributes (with those of id-less children) and text."""
    if measure is None:
        return {}
    parents = {child: parent for parent in measure.iter() for child in parent}
    events = {}
    for element in measure.iter():
        event_id = element.get(XML_ID)
        if event_id is None or element is measure:
            continue
        attrs = {key: value for key, value in element.attrib.items() if key != XML_ID}
        attrs.update({key: value for key, value in _context(element, parents).items() if key not in attrs})
        stack = list(element)
        while stack:
            child = stack.pop()
            if child.get(XML_ID) is None:
                attrs.update({f"{_local(child.tag)}@{key}": value for key, value in child.attrib.items()})
                stack.extend(child)
        text = ""
        if _local(element.tag) in _TEXT_EVENTS:
            figures = [" ".join("".join(f.itertext()).split()) for f in element.iter(MEI + "f") if f is not element]
            text = "/".join(figures) if figures else " ".join("".join(element.itertext()).split())
        events[event_id] = (_local(element.tag), attrs, text)
    return events


def _pitch(attrs: dict) -> str:
    accid = attrs.get("accid") or attrs.get("accid@accid") or ""
    return f"{attrs.get('pname', '?').upper()}{_ACCID.get(accid, '')}{attrs.get('oct', '')}" if attrs.get("pname") else ""


def _label(event: tuple[str, dict, str]) -> str:
    tag, attrs, text = event
    if text:
        return f"{tag} {text}"
    pitch = _pitch(attrs)
    if pitch:
        return f"{tag} {pitch}"
    return f"{tag} {attrs['dur']}" if attrs.get("dur") else tag


def diff_events(before: ET.Element | None, after: ET.Element | None) -> list[str]:
    """What changed between two states of a bar, one entry per event (matched by ``xml:id``)."""
    old, new = _events(before), _events(after)
    entries = []
    for event_id, event in new.items():
        if event_id not in old:
            entries.append(f"+ {_label(event)}")
            continue
        (old_tag, old_attrs, old_text), (tag, attrs, text) = old[event_id], event
        # A pitch change names the event ("note C4→D4"); other changes follow it.
        name = _label(event) if old_tag == tag else f"{old_tag}→{tag}"
        if _pitch(old_attrs) != _pitch(attrs):
            name = f"{tag} {_pitch(old_attrs) or '-'}→{_pitch(attrs) or '-'}"
        changes = [f"{key} {old_attrs.get(key, '-')}→{attrs.get(key, '-')}"
                   for key in sorted((set(old_attrs) | set(attrs)) - {"pname", "oct", "accid", "accid@accid"})
                   if old_attrs.get(key) != attrs.get(key)]
        if old_text != text:
            changes.append(f"“{old_text}”→“{text}”")
        if changes:
            entries.append(f"{name}: {', '.join(changes)}")
        elif name != _label(event):
            entries.append(name)
    entries += [f"− {_label(event)}" for event_id, event in old.items() if event_id not in new]
    return entries


def _match(bar: ET.Element, old: list[ET.Element] | str | None) -> ET.Element | None:
    """The bar's earlier state: the bar with its xml:id, else with its @n."""
    if not isinstance(old, list):
        return None
    for key, value in ((XML_ID, bar.get(XML_ID)), ("n", bar.get("n"))):
        found = [b for b in old if value is not None and b.get(key) == value]
        if found:
            return found[0]
    return None


def _diff_line(entries: list[str]) -> str:
    if not entries:
        return "no event changed"
    shown = entries[:_DIFF_LIMIT]
    more = f" · and {len(entries) - len(shown)} more" if len(entries) > len(shown) else ""
    return " · ".join(shown) + more


def _check_cards(spec: dict, base: Path, ref: str | None, problems: list[str]) -> list[dict]:
    cards = spec.get("cards")
    if not isinstance(cards, list) or not cards:
        problems.append("cards: expected a non-empty list")
        return []
    versions: dict[Path, tuple] = {}
    checked, ids = [], set()
    for index, card in enumerate(cards):
        where = f"cards[{index}]"
        if not isinstance(card, dict):
            problems.append(f"{where}: expected an object")
            continue
        _unknown(card, _CARD_KEYS, f"{where}.", problems)
        card_id = card.get("id")
        if not isinstance(card_id, str) or not _ID.match(card_id):
            problems.append(f"{where}.id: expected letters, digits, '_', '.' or '-', got {card_id!r}")
        elif card_id in ids:
            problems.append(f"{where}.id: {card_id!r} is used twice")
        ids.add(card_id)
        label = _text(card, "label", problems, where=f"{where}.") or str(card_id)
        description = _text(card, "description", problems, where=f"{where}.")
        status = card.get("status", "check")
        if status not in STATUSES:
            problems.append(f"{where}.status: expected one of {', '.join(STATUSES)}, got {status!r}")
        rows = card.get("rows", False)
        if not isinstance(rows, bool):
            problems.append(f"{where}.rows: expected true or false")
        width = card.get("width")
        if width is not None and (isinstance(width, bool) or not isinstance(width, int) or width < 100):
            problems.append(f"{where}.width: expected a page width in Verovio units (at least 100), got {width!r}")
        images = []
        for number, image in enumerate(card.get("images", []) if isinstance(card.get("images", []), list) else [None]):
            if not isinstance(image, dict) or not isinstance(image.get("src"), str) or not image["src"]:
                problems.append(f'{where}.images[{number}]: expected {{"src": ..., "caption": ...}}')
                continue
            _unknown(image, _IMAGE_KEYS, f"{where}.images[{number}].", problems)
            caption = _text(image, "caption", problems, where=f"{where}.images[{number}].")
            if urlsplit(image["src"]).scheme in ("http", "https"):
                images.append({"src": image["src"], "caption": caption})
            elif (base / image["src"]).is_file():
                images.append({"path": (base / image["src"]).resolve(), "caption": caption})
            else:
                problems.append(f"{where}.images[{number}].src: {(base / image['src']).resolve()} does not exist")
        selection = _measures(card.get("measures"))
        if selection is None:
            problems.append(f'{where}.measures: expected "12", "12-14" or ["first", "last"] (@n or #xml:id), '
                            f"got {card.get('measures')!r}")
        mei = card.get("mei")
        if not isinstance(mei, str) or not mei:
            problems.append(f"{where}.mei: expected the path of an MEI file")
            continue
        path = (base / mei).resolve()
        if path not in versions:
            versions[path] = _load_versions(path, ref, f"{where}.mei", problems)
        after, before = versions[path]
        if after is None or selection is None:
            continue
        bars = after.select(*selection)
        if isinstance(bars, str):
            problems.append(f"{where}.measures: {bars} in {path.name}")
            continue
        unnamed = [b.get("n") or "?" for b in bars if b.get(XML_ID) is None]
        if unnamed:
            problems.append(f"{where}.measures: bars {', '.join(unnamed)} of {path.name} have no xml:id, "
                            "which Verovio needs to show them")
            continue
        old = before.select(*selection) if before is not None else None
        checked.append({"id": card_id, "label": label, "description": description, "status": status,
                        "rows": rows, "width": width, "images": images, "path": path, "after": after,
                        "before": before, "bars": bars, "old": old})
    return checked


def _load_versions(path: Path, ref: str | None, where: str, problems: list[str]) -> tuple:
    try:
        after = _Version(path.read_text(encoding="utf-8"))
    except OSError as exc:
        problems.append(f"{where}: cannot read {path} ({exc})")
        return None, None
    except ET.ParseError as exc:
        problems.append(f"{where}: {path} is not well-formed XML ({exc})")
        return None, None
    if after.root.tag != MEI + "mei":
        problems.append(f"{where}: {path} is not an MEI file")
        return None, None
    if ref is None:
        return after, None
    try:
        return after, _Version(_git_show(path, ref))
    except (ValueError, ET.ParseError) as exc:
        problems.append(f"{where}: cannot read {path.name} at {ref} ({exc})")
        return after, None


def _figure(label: str, sources: list[str], cls: str, empty: str = "") -> str:
    body = "".join(f'<img loading="lazy" src="{_escape(src)}" alt="">' for src in sources) \
        or f'<p class="empty">{_escape(empty)}</p>'
    return f'<figure class="{cls}"><figcaption>{_escape(label)}</figcaption>{body}</figure>'


def _marks(key: str) -> str:
    name = _escape(key)
    return (f'<span class="marks" data-key="{name}">'
            f'<label><input type="radio" name="{name}" value="ok"> ok</label>'
            f'<label><input type="radio" name="{name}" value="problem"> problem</label>'
            f'<label><input type="radio" name="{name}" value=""> clear</label></span>')


class _Writer:
    """Collects the page's files under unique names."""

    def __init__(self, spec: dict, labels: dict, ref: str | None):
        self.files: dict[str, bytes | Path] = {}
        self.options = {**VEROVIO_OPTIONS, **spec.get("verovio", {})}
        self.crop = spec.get("crop", {})
        self.labels, self.ref = labels, ref
        self.counts = {"renders": 0, "crops": 0, "rows": 0}
        self.warnings: list[str] = []

    def renders(self, version: _Version, bars, width: int, name: str) -> list[str]:
        names = []
        for page, svg in enumerate(version.render(bars[0], bars[-1], width, self.options), start=1):
            names.append(f"renders/{name}-{page}.svg")
            self.files[names[-1]] = svg.encode("utf-8")
        self.counts["renders"] += len(names)
        return names

    def crops(self, card: dict, bars, name: str) -> list[str]:
        surfaces, zones = _surfaces(card["after"].root)
        padding = tuple(self.crop.get("padding", CROP_PADDING))
        jobs, missing = _crop_jobs(bars, surfaces, zones, padding)
        if missing:
            self.warnings.append(f"{card['id']}: no facsimile zone for bar{'s' if len(missing) > 1 else ''} {', '.join(missing)}")
        names = []
        for number, job in enumerate(jobs, start=1):
            names.append(f"crops/{name}-{number}.jpg")
            self.files[names[-1]] = _crop(job, card["path"], self.crop.get("size", CROP_SIZE))
        self.counts["crops"] += len(names)
        return names

    def columns(self, card: dict, bars, old, width: int, name: str) -> str:
        source = _figure(self.labels["source"], self.crops(card, bars, name), "source", "no facsimile zone")
        after = _figure(self.labels["after"], self.renders(card["after"], bars, width, f"{name}-after"), "after")
        if self.ref is None:
            return f'<div class="cols">{source}{after}</div>'
        if isinstance(old, list) and any(b.get(XML_ID) is None for b in old):
            before = _figure(self.labels["before"], [], "before", f"bars without xml:id at {self.ref}")
        elif isinstance(old, list):
            before = _figure(self.labels["before"], self.renders(card["before"], old, width, f"{name}-before"), "before")
        else:
            before = _figure(self.labels["before"], [], "before", f"not at {self.ref}: {old or 'unreadable'}")
        return f'<div class="cols">{source}{before}{after}</div>'

    def card(self, card: dict) -> tuple[str, dict]:
        key, bars, old = card["id"], card["bars"], card["old"]
        status = card["status"]
        head = (f'<header><h2>{_escape(card["label"])}</h2><span class="badge">{STATUSES[status]}</span>'
                f'{"" if card["rows"] else _marks(key)}</header>')
        text = f'<div class="description">{card["description"]}</div>' if card["description"] else ""
        extras = "".join(self.image(card, number, image) for number, image in enumerate(card["images"], start=1))
        note = (f'<label class="note">Note <textarea data-key="{_escape(key)}" rows="2" '
                f'placeholder="What is wrong, or what to check again"></textarea></label>')
        data = {"key": key, "label": card["label"], "rows": None}
        if not card["rows"]:
            width = card["width"] or (WIDTH_ONE_BAR if len(bars) == 1 else WIDTH_BARS)
            body = self.columns(card, bars, old, width, key)
            changes = []
            if isinstance(old, list):
                for bar in bars:
                    prefix = f"m. {bar.get('n') or '?'}: " if len(bars) > 1 else ""
                    changes += [prefix + entry for entry in diff_events(_match(bar, old), bar)]
            if changes:
                body += f'<details class="changes"><summary>{len(changes)} changed events</summary><p>{_escape(_diff_line(changes))}</p></details>'
        else:
            rows, data["rows"] = [], []
            used: set[str] = set()
            for number, bar in enumerate(bars, start=1):
                n = bar.get("n") or str(number)
                row_key = f"{key}-{n}" if f"{key}-{n}" not in used else f"{key}-{n}.{number}"
                used.add(row_key)
                before = _match(bar, old)
                line = _diff_line(diff_events(before, bar)) if self.ref is not None else ""
                row_old = [before] if before is not None else "this bar is missing"
                rows.append(f'<section class="row" id="{_escape(row_key)}"><header><h3>m. {_escape(n)}</h3>'
                            f'<span class="moves">{_escape(line)}</span>{_marks(row_key)}</header>'
                            f'{self.columns(card, [bar], row_old, card["width"] or WIDTH_ROW, row_key)}</section>')
                data["rows"].append({"key": row_key, "label": f"m. {n}"})
            self.counts["rows"] += len(rows)
            body = "".join(rows)
        html_card = (f'<section class="card {status}" id="{_escape(key)}">{head}{text}{body}{extras}{note}</section>')
        return html_card, data

    def image(self, card: dict, number: int, image: dict) -> str:
        if "src" in image:
            src = image["src"]
        else:
            src = f"images/{card['id']}-{number}{image['path'].suffix.lower()}"
            self.files[src] = image["path"]
        return _figure(image["caption"], [src], "wide")


def _template(name: str) -> str:
    return (files("camat") / "review_page_template" / name).read_text(encoding="utf-8")


def _check_spec(spec: dict, base: Path, problems: list[str]) -> tuple[str | None, dict, list[dict]]:
    _unknown(spec, _KEYS, "", problems)
    version = spec.get("version", 1)
    if isinstance(version, bool) or version != 1:
        problems.append(f"version: expected 1, the only review spec version camat {__version__} reads, got {version!r}")
    if not isinstance(spec.get("$schema", ""), str):
        problems.append("$schema: expected the URL or path of a JSON Schema")
    if not isinstance(spec.get("title"), str) or not spec["title"].strip():
        problems.append("title: expected text")
    _text(spec, "description", problems)
    key = spec.get("storage_key")
    if not isinstance(key, str) or not _STORAGE_KEY.match(key):
        problems.append(f"storage_key: expected lower-case letters, digits and '-' (it keeps this review's marks "
                        f"apart from other reviews in the same browser), got {key!r}")
    ref = spec.get("before_ref", "HEAD")
    if ref is not None and (not isinstance(ref, str) or not ref.strip() or ref.startswith("-")):
        problems.append(f"before_ref: expected a git ref such as HEAD or v1.0.0, or null for no before column, got {ref!r}")
        ref = None
    labels = {**LABELS, "before": ref or ""}
    if not isinstance(spec.get("labels", {}), dict):
        problems.append("labels: expected an object")
    else:
        _unknown(spec.get("labels", {}), _LABEL_KEYS, "labels.", problems)
        for name in _LABEL_KEYS & set(spec.get("labels", {})):
            labels[name] = _text(spec["labels"], name, problems, where="labels.", default=labels[name])
    if not isinstance(spec.get("verovio", {}), dict):
        problems.append("verovio: expected an object of Verovio options")
    else:
        for name, value in spec.get("verovio", {}).items():
            if not isinstance(value, (str, int, float, bool)):
                problems.append(f"verovio.{name}: expected text, a number or true/false")
    crop = spec.get("crop", {})
    if not isinstance(crop, dict):
        problems.append("crop: expected an object with padding and size")
    else:
        _unknown(crop, _CROP_KEYS, "crop.", problems)
        padding = crop.get("padding", list(CROP_PADDING))
        if (not isinstance(padding, list) or len(padding) != 4
                or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in padding)):
            problems.append(f"crop.padding: expected [left, top, right, bottom] in graphic pixels, got {padding!r}")
        size = crop.get("size", CROP_SIZE)
        if not isinstance(size, str) or not _SIZE.match(size):
            problems.append(f"crop.size: expected a IIIF size such as !1400,1600, 1200, or max, got {size!r}")
    cards = _check_cards(spec, base, ref, problems)
    return ref, labels, cards


def build_review_page(spec: str | Path | dict, out: str | Path, *, base_dir: str | Path | None = None) -> dict:
    """Check a review spec and build the review page into the new folder ``out``.

    ``spec`` is the path of a JSON file or the same object as a dict; its paths
    are relative to the file's folder, or to ``base_dir`` (default: the current
    folder) for a dict. Every check runs before anything is written; otherwise
    :class:`ReviewSpecError` lists all problems found. ``out`` must not exist.
    Returns a report with the counts of cards, rows, renders and crops, the
    files written and warnings (such as bars without a facsimile zone).
    """
    data, base = _read_config(spec, base_dir)
    out = Path(out).resolve()
    problems: list[str] = []
    if out.exists():
        problems.append(f"OUT {out} exists; each review goes into a new folder")
    ref, labels, cards = _check_spec(data, base, problems)
    if problems:
        raise ReviewSpecError(problems)

    writer = _Writer(data, labels, ref)
    sections, entries = [], []
    for card in cards:
        try:
            section, entry = writer.card(card)
        except (OSError, ValueError, KeyError) as exc:
            problems.append(f"card {card['id']}: {exc}")
            continue
        sections.append(section)
        entries.append(entry)
    if problems:
        raise ReviewSpecError(problems)

    nav = "".join(f'<a href="#{_escape(c["id"])}" class="{c["status"]}" data-nav="{_escape(c["id"])}">'
                  f'{_escape(c["label"])}</a>' for c in cards)
    runtime = {"storage_key": data["storage_key"], "title": data["title"], "cards": entries}
    intro = data.get("description", "")
    writer.files["index.html"] = Template(_template("index.html")).substitute(
        title=_escape(data["title"]),
        camat_version=_escape(__version__),
        body_class="" if ref is not None else "no-before",
        nav=nav,
        before_toggle=(f'<label><input type="checkbox" id="show-before" checked> {_escape(labels["before"])} column</label>'
                       if ref is not None else ""),
        intro=f'<div class="intro">{intro}</div>' if intro else "",
        cards="\n".join(sections),
        data=json.dumps(runtime, ensure_ascii=False).replace("<", "\\u003c"),
    ).encode("utf-8")
    for name in TEMPLATE_FILES[1:]:
        writer.files[name] = _template(name).encode("utf-8")

    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{out.name}.", dir=out.parent))
    try:
        stage.chmod(0o755)
        size = 0
        for target, source in writer.files.items():
            destination = stage / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(source, Path):
                shutil.copyfile(source, destination)
            else:
                destination.write_bytes(source)
            size += destination.stat().st_size
        if out.exists():
            raise ReviewSpecError([f"OUT {out} appeared while the page was being built"])
        os.rename(stage, out)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {"out": str(out), "cards": len(entries), **writer.counts, "warnings": writer.warnings,
            "files": sorted(writer.files), "bytes": size}


def main(argv: list[str] | None = None) -> int:
    """Build the review page, or list every problem and write nothing."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("spec", help="review spec (JSON); its paths are relative to its folder")
    parser.add_argument("out", help="output folder, which must not exist")
    args = parser.parse_args(argv)
    import verovio

    # Only errors: a long card of rows prints a layout warning for nearly every bar.
    verovio.enableLog(verovio.LOG_ERROR)
    try:
        report = build_review_page(args.spec, args.out)
    except (ReviewSpecError, OSError) as exc:
        print(f"camat-review-page: {exc}", file=sys.stderr)
        return 1
    print(f"Built {report['out']}: {report['cards']} card{'s' if report['cards'] != 1 else ''}, "
          f"{report['rows']} rows, {report['renders']} renders, {report['crops']} crops, "
          f"{report['bytes'] / 1024:.0f} KB")
    for warning in report["warnings"]:
        print(f"  {warning}")
    print(f"Open {Path(report['out']) / 'index.html'} in a browser.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
