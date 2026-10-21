"""Build a static web edition from MEI files and a site config.

The site is the viewer of ``camat/web_edition_template``: each work's MEI
rendered by Verovio in the browser with its encoded page and system breaks,
the editorial notes (``<annot>``), and optionally a facsimile beside it with a
zone for every bar. The facsimile adapter ``pdf`` reads the ``pages.json`` of
:mod:`camat.pdf_facsimile` and the zones that ``integrate_pdf_facsimile``
wrote: visitors open their own copy of the PDF, or see hosted page images,
shown at once or after a confirmation.

Everything is checked before anything is written. The output folder is
replaced as a whole, so it must be empty, missing, or an earlier build; inside
a git repository it must be named ``_site``. Standard library only.

Usage: ``camat-build-site site.json OUT``, then
``python -m http.server -d OUT`` and open http://localhost:8000/.
"""
from __future__ import annotations

import argparse
import hashlib
import html
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shutil
from string import Template
import sys
import tempfile
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from . import __version__

MEI = "{http://www.music-encoding.org/ns/mei}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MARKER = ".camat-site"
TEMPLATE_FILES = ("index.html", "viewer.css", "viewer.js", "facsimile-pdf.js")
FACSIMILE_TYPES = ("pdf",)

LABELS = {
    "work": "Movement",
    "bar": "Bar",
    "bars": "Bars",
    "notes": "Editorial notes",
    "facsimile": "Facsimile",
    "mark_notes": "Mark all notes",
    "bar_boxes": "Bar boxes",
    "hint": "Hover a bar or a symbol to see its bar number and xml:id.",
}
# The layout of camat's facsimile notebook: one rendered page per encoded page.
VEROVIO_OPTIONS = {
    "breaks": "encoded", "adjustPageHeight": True, "footer": "none", "svgViewBox": True, "condense": "none",
    "scale": 35, "spacingLinear": 0.25, "spacingNonLinear": 0.6, "minLastJustification": 0,
}

_KEYS = {"title", "description", "heading", "subtitle", "lang", "storage_prefix", "links", "footer",
         "labels", "works", "verovio", "ref_base", "facsimile"}
_WORK_KEYS = {"id", "label", "title", "mei"}
_PDF_KEYS = {"type", "pages", "pdf", "images"}
_PREFIX = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_WORK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_LANG = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*\Z")


class SiteConfigError(ValueError):
    """The site config or its inputs have problems; nothing was written."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        count = len(self.problems)
        super().__init__(f"{count} problem{'s' if count != 1 else ''} in the site config:\n"
                         + "\n".join(f"  - {p}" for p in self.problems))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _refs(value: str | None) -> list[str]:
    return [token.removeprefix("#") for token in (value or "").split()]


def _text(config: dict, key: str, problems: list[str], *, where: str = "", default: str = "") -> str:
    value = config.get(key, default)
    if not isinstance(value, str):
        problems.append(f"{where}{key}: expected text, got {type(value).__name__}")
        return default
    return value


def _url(value: object, where: str, problems: list[str], *, https: bool = False) -> str | None:
    """An http(s) URL, or a relative link unless ``https`` is set."""
    if isinstance(value, str) and value.strip():
        parts = urlsplit(value)
        if https and parts.scheme == "https" and parts.netloc:
            return value
        if not https and parts.scheme in ("http", "https") and parts.netloc:
            return value
        if not https and not parts.scheme and not parts.netloc:
            return value
    problems.append(f"{where}: expected {'an https URL' if https else 'an http(s) URL or a relative link'}, got {value!r}")
    return None


def _unknown(config: dict, allowed: set[str], where: str, problems: list[str]) -> None:
    for key in sorted(set(config) - allowed):
        problems.append(f"{where}{key}: unknown key (expected one of {', '.join(sorted(allowed))})")


def _read_mei(path: Path, where: str, problems: list[str]) -> dict | None:
    """Count what the viewer uses and collect the facsimile links to check."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        problems.append(f"{where}: {path} is not well-formed XML ({exc})")
        return None
    music = root.find(MEI + "music")
    if root.tag != MEI + "mei" or music is None:
        problems.append(f"{where}: {path} is not an MEI file with <music>")
        return None
    surfaces, zones = {}, {}
    for surface in root.iter(MEI + "surface"):
        graphic = surface.find(MEI + "graphic")
        if graphic is None:
            continue
        surfaces[surface.get(XML_ID)] = {
            "file": (graphic.get("target") or "").rsplit("/", 1)[-1],
            "width": graphic.get("width"), "height": graphic.get("height"),
        }
        for zone in surface.iter(MEI + "zone"):
            zones[zone.get(XML_ID)] = surface.get(XML_ID)
    info = {"measures": 0, "measures_without_id": 0, "linked": 0, "first_bar": None, "notes": 0,
            "surfaces": surfaces, "zones": zones, "dangling": [], "used_surfaces": set()}
    known = set(surfaces) | set(zones)
    for element in music.iter():
        if element.tag == MEI + "measure":
            info["measures"] += 1
            if element.get(XML_ID) is None:
                info["measures_without_id"] += 1
            if info["first_bar"] is None and element.get("n"):
                info["first_bar"] = element.get("n")
            facs = _refs(element.get("facs"))
            info["linked"] += any(ref in zones for ref in facs)
            info["dangling"] += [ref for ref in facs if ref not in known]
        elif element.tag == MEI + "pb":
            facs = _refs(element.get("facs"))[:1]
            info["used_surfaces"].update(ref for ref in facs if ref in surfaces)
            info["dangling"] += [ref for ref in facs if ref not in known]
        elif element.tag == MEI + "annot":
            info["notes"] += 1
    return info


def _read_config(config: str | Path | dict, base_dir: str | Path | None) -> tuple[dict, Path, Path | None]:
    if isinstance(config, dict):
        return config, Path(base_dir or Path.cwd()).resolve(), None
    path = Path(config).resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SiteConfigError([f"{path}: cannot read the site config ({exc})"]) from exc
    if not isinstance(data, dict):
        raise SiteConfigError([f"{path}: expected a JSON object"])
    return data, Path(base_dir).resolve() if base_dir else path.parent, path


def _check_works(config: dict, base: Path, problems: list[str]) -> list[dict]:
    works = config.get("works")
    if not isinstance(works, list) or not works:
        problems.append("works: expected a non-empty list")
        return []
    checked, ids, names = [], set(), set()
    for index, work in enumerate(works):
        where = f"works[{index}]"
        if not isinstance(work, dict):
            problems.append(f"{where}: expected an object")
            continue
        _unknown(work, _WORK_KEYS, f"{where}.", problems)
        work_id = work.get("id")
        if not isinstance(work_id, str) or not _WORK_ID.match(work_id):
            problems.append(f"{where}.id: expected letters, digits, '_', '.' or '-' (used in #<work>/<bar>), got {work_id!r}")
        elif work_id in ids:
            problems.append(f"{where}.id: {work_id!r} is used twice")
        ids.add(work_id)
        label = _text(work, "label", problems, where=f"{where}.", default=work_id if isinstance(work_id, str) else "")
        title = _text(work, "title", problems, where=f"{where}.")
        mei = work.get("mei")
        if not isinstance(mei, str) or not mei:
            problems.append(f"{where}.mei: expected the path of an MEI file")
            continue
        path = (base / mei).resolve()
        if not path.is_file():
            problems.append(f"{where}.mei: {path} does not exist")
            continue
        if path.name in names:
            problems.append(f"{where}.mei: another work's MEI is also named {path.name}")
        names.add(path.name)
        info = _read_mei(path, f"{where}.mei", problems)
        if info is not None:
            checked.append({"id": work_id, "label": label or work_id, "title": title, "path": path, "info": info})
    return checked


def _check_pdf_facsimile(facsimile: dict, base: Path, works: list[dict], problems: list[str]) -> dict | None:
    _unknown(facsimile, _PDF_KEYS, "facsimile.", problems)
    pages_value = facsimile.get("pages")
    if not isinstance(pages_value, str) or not pages_value:
        problems.append("facsimile.pages: expected the path of camat.pdf_facsimile's pages.json")
        return None
    pages_path = (base / pages_value).resolve()
    try:
        manifest = json.loads(pages_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        problems.append(f"facsimile.pages: cannot read {pages_path} ({exc})")
        return None
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("pages"), list):
        problems.append(f"facsimile.pages: {pages_path} is not a pages.json of schema_version 1")
        return None
    pages = {Path(p.get("image", "")).name: p for p in manifest["pages"] if isinstance(p, dict)}

    pdf, source = facsimile.get("pdf", False), None
    if isinstance(pdf, dict):
        _unknown(pdf, {"url", "text"}, "facsimile.pdf.", problems)
        if "url" in pdf:
            source = {"url": _url(pdf["url"], "facsimile.pdf.url", problems),
                      "text": _text(pdf, "text", problems, where="facsimile.pdf.", default=pdf.get("url", ""))}
        pdf = True
    elif not isinstance(pdf, bool):
        problems.append("facsimile.pdf: expected true, false or an object with url and text")
        pdf = False
    images = facsimile.get("images")
    if images is not None:
        if not isinstance(images, dict):
            problems.append("facsimile.images: expected an object with url or copy")
            images = None
        else:
            _unknown(images, {"url", "copy", "confirm", "button"}, "facsimile.images.", problems)
            if ("url" in images) == bool(images.get("copy")):
                problems.append("facsimile.images: give either url (hosted elsewhere) or \"copy\": true")
            elif "url" in images:
                url = _url(images["url"], "facsimile.images.url", problems, https=True)
                images = {**images, "url": url if url is None or url.endswith("/") else url + "/"}
            _text(images, "confirm", problems, where="facsimile.images.")
            _text(images, "button", problems, where="facsimile.images.")
    if not pdf and images is None:
        problems.append("facsimile: give pdf, images or both")

    used = {}
    for work in works:
        info = work["info"]
        if info["dangling"]:
            shown = ", ".join(sorted(set(info["dangling"]))[:5])
            problems.append(f"{work['path'].name}: @facs points at no zone or surface: {shown}")
        for surface_id in sorted(info["used_surfaces"]):
            surface = info["surfaces"][surface_id]
            page = pages.get(surface["file"])
            if page is None:
                problems.append(f"{work['path'].name}: surface {surface_id} shows {surface['file']!r}, which is not in {pages_path.name}")
            elif (surface["width"], surface["height"]) != (str(page.get("width")), str(page.get("height"))):
                problems.append(f"{work['path'].name}: surface {surface_id} is {surface['width']}×{surface['height']}, "
                                f"its page image {page.get('width')}×{page.get('height')}")
            else:
                used[surface["file"]] = page
    if images is not None and images.get("copy"):
        for name, page in sorted(used.items()):
            image = pages_path.parent / page["image"]
            if not image.is_file():
                problems.append(f"facsimile.images: {image} does not exist")
            elif _sha256(image) != page.get("sha256"):
                problems.append(f"facsimile.images: {image} differs from its sha256 in {pages_path.name}")
    keep = ("page_id", "image", "width", "height", "sha256", "pdf_page_number", "printed_page")
    return {
        "pages_path": pages_path, "pdf": pdf, "source": source, "images": images, "used": used,
        "manifest": {"schema_version": 1, "source_id": manifest.get("source_id"), "pdf_sha256": manifest.get("pdf_sha256"),
                     "page_count": manifest.get("page_count", len(manifest["pages"])),
                     "pages": [{key: p.get(key) for key in keep} for p in manifest["pages"] if isinstance(p, dict)]},
    }


def _git_root(path: Path) -> Path | None:
    for folder in (path, *path.parents):
        if (folder / ".git").exists():
            return folder
    return None


def _check_out(out: Path, inputs: list[Path], problems: list[str]) -> None:
    for item in inputs:
        if item == out or item.is_relative_to(out):
            problems.append(f"OUT {out} contains the input {item}; building would delete it")
            return
    repo = _git_root(out)
    if repo is not None and out.name != "_site":
        problems.append(f"OUT {out} is inside the git repository {repo}; there, only a folder named _site may be replaced")
    if out.exists():
        if not out.is_dir():
            problems.append(f"OUT {out} is not a folder")
        elif any(out.iterdir()) and not (out / MARKER).is_file():
            problems.append(f"OUT {out} is not empty and was not built by camat-build-site; choose another folder or empty it yourself")


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def _facsimile_pane(label: str, intro: str) -> str:
    return (f'    <section class="pane facs" id="facs" aria-label="{_escape(label)}">\n'
            f'      <div id="facs-intro" class="intro">\n        <h2>{_escape(label)}</h2>\n{intro}      </div>\n'
            '      <div id="facs-view" hidden>\n'
            '        <div class="paper facs-page">\n'
            '          <canvas id="facs-canvas"></canvas>\n'
            '          <svg id="zones" class="zones" preserveAspectRatio="none" aria-hidden="true"></svg>\n'
            '        </div>\n'
            f'        <p class="facs-meta"><span id="facs-label"></span> <button type="button" id="facs-close" class="link">Hide the {_escape(label.lower())}</button></p>\n'
            '        <p id="facs-warning" class="warning" hidden></p>\n'
            '      </div>\n'
            '      <p id="facs-error" class="error" hidden></p>\n'
            '    </section>\n')


def _pdf_intro(facsimile: dict) -> str:
    lines, images = [], facsimile["images"]
    if images is not None:
        if images.get("confirm"):
            lines.append(f'        <p class="warning">{_escape(images["confirm"])}</p>')
        lines.append(f'        <button type="button" id="scan-show" class="button">{_escape(images.get("button") or "Show the scan")}</button>')
    if facsimile["pdf"]:
        source = facsimile["source"]
        where = f' from <a href="{_escape(source["url"])}">{_escape(source["text"])}</a>' if source and source["url"] else ""
        lines += [f'        <p>{"Or open" if images is not None else "Open"} your own copy of the PDF{where}. '
                  'It is read in your browser and not uploaded anywhere.</p>',
                  '        <label class="button">Open the PDF… <input type="file" id="pdf-input" accept="application/pdf,.pdf"></label>',
                  '        <p class="hint">Or drop the file on this panel.</p>']
    return "".join(line + "\n" for line in lines)


def _template(name: str) -> bytes:
    return (files("camat") / "web_edition_template" / name).read_bytes()


def _render_index(config: dict, works: list[dict], labels: dict, runtime: dict, facsimile: dict | None,
                  problems: list[str]) -> str:
    title = _text(config, "title", problems)
    heading = _text(config, "heading", problems, default=title)
    subtitle = _text(config, "subtitle", problems)
    footer = _text(config, "footer", problems)
    links = config.get("links", [])
    rendered_links = []
    if not isinstance(links, list):
        problems.append("links: expected a list of {text, url}")
        links = []
    for index, link in enumerate(links):
        if not isinstance(link, dict) or set(link) != {"text", "url"} or not isinstance(link["text"], str):
            problems.append(f"links[{index}]: expected {{\"text\": ..., \"url\": ...}}")
            continue
        url = _url(link["url"], f"links[{index}].url", problems)
        if url:
            rendered_links.append(f'<a href="{_escape(url)}">{_escape(link["text"])}</a>')
    first = works[0] if works else None
    example = f"{first['id']}/{first['info']['first_bar'] or 1}" if first else ""
    return Template(_template("index.html").decode("utf-8")).substitute(
        lang=_escape(_text(config, "lang", problems, default="en")),
        title=_escape(title),
        description=_escape(_text(config, "description", problems)),
        camat_version=_escape(__version__),
        config_json=json.dumps(runtime, ensure_ascii=False).replace("<", "\\u003c"),
        heading=_escape(heading),
        subtitle=f"    <p>{_escape(subtitle)}</p>\n" if subtitle else "",
        links=f"    <p>{' · '.join(rendered_links)}</p>\n" if rendered_links else "",
        work_label=_escape(labels["work"]),
        mark_notes_label=_escape(labels["mark_notes"]),
        bar_boxes_label=_escape(labels["bar_boxes"]),
        hint=_escape(labels["hint"]),
        notes_label=_escape(labels["notes"]),
        panes_class="" if facsimile else " single",
        facsimile=_facsimile_pane(labels["facsimile"], _pdf_intro(facsimile)) if facsimile else "",
        footer=f"    <p>{_escape(footer)}</p>\n" if footer else "",
        credits=", PDFs with <a href=\"https://mozilla.github.io/pdf.js/\">pdf.js</a> 6.3.289" if facsimile and facsimile["pdf"] else "",
        link_example=_escape(example),
    )


def _plan(config: dict, base: Path, config_path: Path | None, out: Path) -> tuple[dict[str, bytes | Path], dict]:
    """Check everything and return the files to write, or raise SiteConfigError."""
    problems: list[str] = []
    _unknown(config, _KEYS, "", problems)
    if not isinstance(config.get("title"), str) or not config["title"].strip():
        problems.append("title: expected text")
    prefix = config.get("storage_prefix")
    if not isinstance(prefix, str) or not _PREFIX.match(prefix):
        problems.append(f"storage_prefix: expected lower-case letters, digits and '-' (it keeps this site's "
                        f"settings apart from other sites on the same host), got {prefix!r}")
    lang = config.get("lang", "en")
    if not isinstance(lang, str) or not _LANG.match(lang):
        problems.append(f"lang: expected a language tag such as 'en' or 'de', got {lang!r}")
    labels = dict(LABELS)
    if not isinstance(config.get("labels", {}), dict):
        problems.append("labels: expected an object")
    else:
        _unknown(config.get("labels", {}), set(LABELS), "labels.", problems)
        for key in set(LABELS) & set(config.get("labels", {})):
            labels[key] = _text(config["labels"], key, problems, where="labels.", default=LABELS[key])
    verovio = dict(VEROVIO_OPTIONS)
    if not isinstance(config.get("verovio", {}), dict):
        problems.append("verovio: expected an object of Verovio options")
    else:
        for key, value in config.get("verovio", {}).items():
            if not isinstance(value, (str, int, float, bool)):
                problems.append(f"verovio.{key}: expected text, a number or true/false")
            verovio[key] = value
    ref_base = config.get("ref_base")
    if ref_base is not None:
        ref_base = _url(ref_base, "ref_base", problems)
        if ref_base and not ref_base.endswith("/"):
            problems.append("ref_base: expected a URL ending in '/'")

    works = _check_works(config, base, problems)
    facsimile = None
    raw = config.get("facsimile")
    if raw is not None:
        if not isinstance(raw, dict) or raw.get("type") not in FACSIMILE_TYPES:
            problems.append(f"facsimile.type: expected one of {', '.join(FACSIMILE_TYPES)}")
        else:
            facsimile = _check_pdf_facsimile(raw, base, works, problems)

    runtime = {"prefix": prefix, "labels": labels, "verovio": verovio, "ref_base": ref_base, "facsimile": None}
    plan: dict[str, bytes | Path] = {}
    for work in works:
        plan[f"mei/{work['path'].name}"] = work["path"]
    if facsimile is not None:
        images = facsimile["images"]
        if images is not None and images.get("copy"):
            for name, page in sorted(facsimile["used"].items()):
                plan[f"facsimile/{name}"] = facsimile["pages_path"].parent / page["image"]
        runtime["facsimile"] = {
            "type": "pdf", "pages": "facsimile/pages.json", "pdf": facsimile["pdf"],
            "images": None if images is None else {
                "url": "facsimile/" if images.get("copy") else images.get("url"), "confirm": bool(images.get("confirm"))},
        }
        plan["facsimile/pages.json"] = (json.dumps(facsimile["manifest"], indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    plan["works.json"] = (json.dumps({"works": [
        {"id": w["id"], "label": w["label"], "title": w["title"], "mei": f"mei/{w['path'].name}"} for w in works
    ]}, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    index = _render_index(config, works, labels, runtime, facsimile, problems)
    plan["index.html"] = index.encode("utf-8")
    for name in TEMPLATE_FILES[1:]:
        if name != "facsimile-pdf.js" or facsimile is not None:
            plan[name] = _template(name)
    plan[".nojekyll"] = b""
    plan[MARKER] = b"Built by camat-build-site (camat.web_edition). This folder is replaced on every build.\n"

    inputs = [base, *(w["path"] for w in works)]
    if config_path is not None:
        inputs.append(config_path)
    if facsimile is not None:
        inputs.append(facsimile["pages_path"])
    _check_out(out, inputs, problems)
    if problems:
        raise SiteConfigError(problems)
    report = {"out": str(out), "works": [
        {"id": w["id"], "measures": w["info"]["measures"], "measures_with_zone": w["info"]["linked"],
         "measures_without_id": w["info"]["measures_without_id"], "notes": w["info"]["notes"],
         "facsimile_pages": len(w["info"]["used_surfaces"])} for w in works]}
    return plan, report


def build_site(config: str | Path | dict, out: str | Path, *, base_dir: str | Path | None = None) -> dict:
    """Check a site config and build the web edition into ``out``.

    ``config`` is the path of a JSON file or the same object as a dict; its
    paths are relative to the file's folder, or to ``base_dir`` (default: the
    current folder) for a dict. ``out`` is replaced only after every check has
    passed; otherwise :class:`SiteConfigError` lists all problems found.
    Returns a report with the files written and per-work counts.
    """
    data, base, config_path = _read_config(config, base_dir)
    out = Path(out).resolve()
    plan, report = _plan(data, base, config_path, out)
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{out.name}.", dir=out.parent))
    try:
        stage.chmod(0o755)
        size = 0
        for target, source in plan.items():
            destination = stage / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(source, Path):
                shutil.copyfile(source, destination)
            else:
                destination.write_bytes(source)
            size += destination.stat().st_size
        if out.exists():
            old = stage.with_name(stage.name + ".old")
            os.replace(out, old)
            os.replace(stage, out)
            shutil.rmtree(old)
        else:
            os.replace(stage, out)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    report.update(files=sorted(plan), bytes=size)
    return report


def main(argv: list[str] | None = None) -> int:
    """Build the site, or list every problem and write nothing."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("config", help="site config (JSON); its paths are relative to its folder")
    parser.add_argument("out", help="output folder, replaced as a whole (in a git repository: _site)")
    args = parser.parse_args(argv)
    try:
        report = build_site(args.config, args.out)
    except (SiteConfigError, OSError) as exc:
        print(f"camat-build-site: {exc}", file=sys.stderr)
        return 1
    works = report["works"]
    print(f"Built {report['out']}: {len(works)} work{'s' if len(works) != 1 else ''}, "
          f"{sum(w['measures'] for w in works)} bars ({sum(w['measures_with_zone'] for w in works)} with a zone), "
          f"{len(report['files'])} files, {report['bytes'] / 1024:.0f} KB")
    for work in works:
        if work["measures_without_id"]:
            print(f"  {work['id']}: {work['measures_without_id']} bars have no xml:id and cannot be selected")
    print(f"Preview: python -m http.server -d {report['out']}, then open http://localhost:8000/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
