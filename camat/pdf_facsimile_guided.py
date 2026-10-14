"""Support for the guided PDF notebook; the general API is ``camat.pdf_facsimile``."""
from __future__ import annotations

import json
import re
import tempfile
import traceback
import urllib.request
import warnings
from functools import wraps
from pathlib import Path
from typing import Callable

from PIL import Image as PILImage, ImageDraw, ImageFont

from camat import display_path, launch_interactive_facsimile_viewer, resolve_repo_path
from camat.pdf_facsimile import (
    _BoxEditError,
    _DetectorResponseError,
    _IntegrationGateError,
    _LayoutError,
    _PageReviewError,
    _SystemCountError,
    _mei_movement as _read_movement,
    _new_box as _validate_new_box,
    _ranges,
    POPPLER_INSTALL_HINTS,
    apply_page_layout,
    approve_alignment_review,
    build_measure_alignment,
    check_page_layout,
    check_poppler,
    detect_measure_boxes,
    draw_alignment_overlays,
    edit_measure_boxes,
    group_measure_boxes_into_systems,
    integrate_pdf_facsimile,
    number_single_mdiv,
    parse_page_layout,
    render_pdf_pages,
    write_page_breaks,
)

EXAMPLE_PDF = "converted_mei/pdf_guided/bsb00023199_0170-0173.pdf"
BSB_FORM_URL = (
    "https://download.digitale-sammlungen.de/BOOKS/download.pl"
    "?id=00023199&ersteseite=170&letzteseite=173&xdfz=2&vers=d&nr=&abschicken=ja"
    "&captcha_zeit=00023199"
)
BSB_HOST = "https://download.digitale-sammlungen.de"
COORDS = ("ulx", "uly", "lrx", "lry")


__all__ = [
    "make_page_images", "describe_pages", "find_bars", "check_bars",
    "merge_with_mei", "open_result", "NotDone", "download_example_pdf",
]


class _ExampleDownloadError(ValueError):
    """A BSB response could not supply the example PDF."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def download_example_pdf(
    pdf: str | Path, *, on_download: Callable[[str], None] | None = None,
) -> Path:
    """Download the BSB Buxtehude example, raising ordinary errors on failure.

    Call only after accepting BSB's CC BY-NC-SA 4.0 terms. An existing PDF
    is reused. ``on_download`` receives the resolved download URL.
    """
    pdf = Path(pdf)
    if pdf.is_file():
        return pdf
    with urllib.request.urlopen(BSB_FORM_URL, timeout=120) as response:
        html = response.read().decode("utf-8", errors="replace")
    links = re.findall(r'href=[\'"](/pdf/\d+bsb00023199\.pdf)[\'"]', html)
    if len(links) != 1:
        raise _ExampleDownloadError(
            f"expected one /pdf/<digits>bsb00023199.pdf link, found {len(links)}", "links")
    url = BSB_HOST + links[0]
    if on_download is not None:
        on_download(url)
    with urllib.request.urlopen(url, timeout=300) as response:
        data = response.read()
    if not data.startswith(b"%PDF-"):
        raise _ExampleDownloadError(f"{url} did not return a PDF; download it by hand instead (see above).", "pdf")
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(data)
    return pdf


def _description_problem(problem: _LayoutError) -> NotDone:
    if problem.code != "bars":
        return NotDone(str(problem))
    missing, extra, bars = (problem.details[key] for key in ("missing", "extra", "bars"))
    lines = ["Your description and the MEI do not have the same bars."]
    if missing:
        lines.append(f"  In the MEI but not in your description: {_ranges(missing)}")
    if extra:
        lines.append(f"  In your description but not in the MEI: {_ranges(extra)}")
    lines.append(f"The MEI has {len(bars)} bars: {_ranges(bars)}. Correct the description and run this cell again.")
    return NotDone("\n".join(lines))


def _box_problem(page: dict, problem: _BoxEditError) -> NotDone:
    details, number = problem.details, page["pdf_page_number"]
    if problem.code == "malformed":
        message = (f"ADD_BOXES, page {number}: {details['entry']!r} is not a box. "
                   "Write four numbers in round brackets: (left, top, right, bottom).")
    elif problem.code == "edges":
        message = (f"ADD_BOXES, page {number}: in {details['entry']!r}, left must be smaller than right "
                   "and top smaller than bottom. The order is (left, top, right, bottom).")
    elif problem.code == "bounds":
        message = (f"ADD_BOXES, page {number}: {details['entry']!r} reaches outside the page "
                   f"(the picture is {page['width']} × {page['height']} pixels).")
    elif problem.code == "index":
        message = (f"REMOVE_BOXES, page {number}: {details['index']!r} is not a box number "
                   f"(this page has boxes 0 to {details['count'] - 1}).")
    elif problem.code == "overlap":
        message = (f"ADD_BOXES, page {number}: {tuple(details['box'].values())} covers "
                   f"most of box {details['index']}. Is that bar really missing?")
    else:
        raise problem
    return NotDone(message)


class NotDone(Exception):
    """A step stops here; the message says what to do."""


def _step(function: Callable) -> Callable:
    """Print a short NOT DONE message instead of a long error report."""
    @wraps(function)
    def run(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except NotDone as problem:
            print(f"\n⚠ NOT DONE. {problem}")
        except Exception as problem:
            print(f"\n⚠ NOT DONE. Something unexpected happened: {type(problem).__name__}: {problem}")
            print("Show this message and the details below to your teacher.")
            traceback.print_exc()
        return None
    return run


def _folders(output_folder: str | Path) -> dict:
    out = resolve_repo_path(output_folder)
    pages = out / "pages"
    return {"out": out, "pages": pages, "pages_json": pages / "pages.json", "boxes": pages / "boxes",
            "alignment": pages / "alignment.json", "overlays": out / "overlays",
            "previews": out / "previews", "mei": out / "mei"}


def _switch(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise NotDone(f"{name} must be True or False, written without quotes. "
                      "Correct it in the settings cell and run that cell again.")
    return value


def _in_jupyter() -> bool:
    try:
        from IPython import get_ipython
    except ImportError:
        return False
    shell = get_ipython()
    return shell is not None and getattr(shell, "kernel", None) is not None


def _show_file(path: Path, width: int | None = None) -> None:
    if _in_jupyter():
        from IPython.display import Image, display
        display(Image(filename=str(path), width=width))
    else:
        print(f"(picture: {display_path(path)})")


def _show(image: PILImage.Image, path: Path, width: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    _show_file(path, width)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def _sheet(tiles: list[tuple[PILImage.Image, str]], columns: int, tile_width: int) -> PILImage.Image:
    """Put (picture, caption) pairs side by side."""
    thumbs = []
    for image, caption in tiles:
        height = round(image.height * tile_width / image.width)
        thumbs.append((image.convert("RGB").resize((tile_width, height)), caption))
    cell_height = max(thumb.height for thumb, _ in thumbs) + 40
    rows = (len(thumbs) + columns - 1) // columns
    sheet = PILImage.new("RGB", (min(columns, len(thumbs)) * (tile_width + 20) + 20, rows * cell_height + 20), "white")
    draw, font = ImageDraw.Draw(sheet), _font(18)
    for index, (thumb, caption) in enumerate(thumbs):
        x = 20 + (index % columns) * (tile_width + 20)
        y = 20 + (index // columns) * cell_height
        draw.text((x, y), caption, fill="black", font=font)
        sheet.paste(thumb, (x, y + 28))
        draw.rectangle([x - 1, y + 27, x + thumb.width, y + 28 + thumb.height], outline=(150, 150, 150))
    return sheet


def _read_pages(folders: dict) -> dict:
    if not folders["pages_json"].is_file():
        raise NotDone("There are no page images yet. Run step 1 first.")
    return json.loads(folders["pages_json"].read_text(encoding="utf-8"))


def _music_pages(folders: dict) -> list[dict]:
    music = [page for page in _read_pages(folders)["pages"] if page.get("role") == "music"]
    if not music:
        raise NotDone("No page is described as music yet. Run step 2 first.")
    return music


def _page_name(page: dict) -> str:
    printed = page.get("printed_page")
    return f"PDF page {page['pdf_page_number']}" + (f" (printed page {printed})" if printed else "")


def _download_example(pdf: Path) -> None:
    print("Downloading the example PDF from the Bayerische Staatsbibliothek ...")
    try:
        download_example_pdf(pdf)
    except _ExampleDownloadError as problem:
        if problem.code == "links":
            raise NotDone("The library's download page looked different than expected. "
                          "Download the PDF by hand (see the instructions above).") from problem
        raise NotDone("The library did not send a PDF. Download it by hand (see the instructions above).") from problem
    print(f"Saved {display_path(pdf)} ({pdf.stat().st_size // 1024} KB). "
          "Licence: CC BY-NC-SA 4.0, Bayerische Staatsbibliothek. Keep this file.")


def _require_poppler() -> None:
    try:
        check_poppler()
    except RuntimeError as problem:
        raise NotDone(
            "This step needs the free program Poppler, which is not installed.\n"
            + POPPLER_INSTALL_HINTS
            + "Then restart the kernel (Kernel → Restart Kernel) and run the notebook again from the top.") from problem


@_step
def make_page_images(pdf_file: str | Path, output_folder: str | Path, *, download_example: bool = False) -> None:
    """Step 1: turn every PDF page into a PNG picture and show small previews."""
    download_example = _switch(download_example, "DOWNLOAD_EXAMPLE_PDF")
    folders, pdf = _folders(output_folder), resolve_repo_path(pdf_file)
    if not pdf.is_file():
        if download_example and pdf == resolve_repo_path(EXAMPLE_PDF):
            _download_example(pdf)
        elif download_example:
            raise NotDone(f"DOWNLOAD_EXAMPLE_PDF only fetches the Buxtehude example. "
                          f"Your PDF_FILE points to {display_path(pdf)}, which does not exist. "
                          "Put your PDF there, or correct PDF_FILE in the settings cell.")
        else:
            raise NotDone(f"The PDF is missing: {display_path(pdf)}\n"
                          "For the example, set DOWNLOAD_EXAMPLE_PDF = True in the settings cell (and run it), "
                          "or download the PDF by hand as described above.")
    _require_poppler()
    source_id = re.sub(r"[^A-Za-z0-9_.-]", "_", pdf.stem)
    if not re.match(r"[A-Za-z_]", source_id):
        source_id = "pdf_" + source_id
    print("Turning the PDF pages into pictures (300 dpi). This takes a moment ...")
    try:
        manifest = render_pdf_pages(pdf, folders["pages"], dpi=300, source_id=source_id)
    except (ValueError, FileExistsError) as problem:
        raise NotDone(f"The folder {display_path(folders['pages'])} already holds pictures of another PDF, "
                      "or of an earlier download of this one (every download counts as a new file). "
                      "Set a new OUTPUT_FOLDER in the settings cell, run that cell, and start again with step 1.\n"
                      f"(Details: {problem})")
    tiles = []
    for page in manifest["pages"]:
        with PILImage.open(folders["pages"] / page["image"]) as image:
            tiles.append((image.copy(), f"PDF page {page['pdf_page_number']}"))
    print(f"✓ {manifest['page_count']} pages, saved in {display_path(folders['pages'])}")
    _show(_sheet(tiles, columns=5, tile_width=220), folders["previews"] / "pages.png")
    print("Which PDF pages show music? You need that for step 2.")


def _mei_movement(mei: Path) -> tuple[str | None, list[str]]:
    try:
        return _read_movement(mei)
    except FileNotFoundError as problem:
        raise NotDone(f"The MEI file is missing: {display_path(mei)}. Check MEI_FILE in the settings cell.") from problem
    except _LayoutError as problem:
        details = problem.details
        if problem.code == "xml":
            message = f"{display_path(mei)} is not a readable XML file: {details['problem']}"
        elif problem.code == "no_mdiv":
            message = f"{display_path(mei)} has no <mdiv> (movement). Is it an MEI file?"
        elif problem.code == "multiple_mdivs":
            message = (f"{display_path(mei)} has {details['count']} movements (<mdiv> elements). This guided notebook "
                       "links one movement. For several, use mei_pdf_facsimile_integration.ipynb.")
        elif problem.code == "measure_n":
            message = (f"The MEI has a <measure> without a bar number (@n), xml:id {details['xml_id']}. "
                       "Every bar needs a number.")
        elif problem.code == "no_measures":
            message = f"{display_path(mei)} has no <measure> elements."
        else:
            raise
        raise NotDone(message) from problem


def _forget_description(folders: dict, manifest: dict) -> None:
    """After a failed step 2, later steps must not use an older description."""
    if any(page.get("role") == "music" for page in manifest["pages"]):
        apply_page_layout(folders["pages_json"], {})


@_step
def describe_pages(description: str, mei_file: str | Path, output_folder: str | Path) -> None:
    """Step 2: check the page description against the MEI and save it in pages.json."""
    folders = _folders(output_folder)
    manifest = _read_pages(folders)
    try:
        # Read the MEI first, as in the notebook, so its errors take priority.
        mei = resolve_repo_path(mei_file)
        _mei_movement(mei)
        try:
            pages = parse_page_layout(description, page_count=manifest["page_count"])
            checked = check_page_layout(pages, mei)
        except _LayoutError as problem:
            raise _description_problem(problem)
        except ValueError as problem:
            raise NotDone(str(problem)) from problem
    except NotDone:
        _forget_description(folders, manifest)
        raise
    mdiv_n, bar_count, split = checked["mdiv"], len(checked["bars"]), checked["split_bars"]
    manifest = apply_page_layout(folders["pages_json"], pages, mdiv=mdiv_n or "1")

    print("PDF page | printed page | content")
    for page in manifest["pages"]:
        if page["role"] == "music":
            labels = [label for system in page["systems"] for label in system]
            content = f"music: {len(page['systems'])} systems, bars {_ranges(list(dict.fromkeys(labels)))}"
        elif page["role"] == "unreviewed":
            content = "not described, so no music"
        else:
            content = f"{page['role']}, no music"
        print(f"{page['pdf_page_number']:>8} | {page['printed_page'] or '-':>12} | {content}")
    print(f"\n✓ Your description matches the MEI: all {bar_count} bars, in the same order.")
    if split:
        print(f"  Bars that continue on the next system: {', '.join(split)}")
    if mdiv_n is None:
        print("  (The movement in the MEI has no number; step 4 numbers it 1 in the new file.)")


def _box_files(folders: dict, page: dict) -> tuple[Path, Path]:
    path = folders["boxes"] / f"{page['page_id']}.json"
    return path, path.with_name(f"{page['page_id']}.original.json")


def _boxes(folders: dict, page: dict) -> tuple[dict, dict]:
    """Return (the detector's boxes, the boxes in use now)."""
    path, original = _box_files(folders, page)
    current = json.loads(path.read_text(encoding="utf-8"))
    first = json.loads(original.read_text(encoding="utf-8")) if original.is_file() else current
    return first, current


def _labelled_page(folders: dict, page: dict, boxes: list[dict], labels: list[str]) -> PILImage.Image:
    with PILImage.open(folders["pages"] / page["image"]) as source:
        image = source.convert("RGB")
    draw, font = ImageDraw.Draw(image, "RGBA"), _font(max(24, image.width // 32))
    for box, label in zip(boxes, labels):
        color = (30, 90, 220) if label == "new" else (210, 30, 30)
        draw.rectangle([box[k] for k in COORDS], outline=(*color, 255), width=max(3, image.width // 400))
        x, y = box["ulx"] + 8, box["uly"] + 8
        draw.rectangle(draw.textbbox((x, y), label, font=font), fill=(255, 255, 255, 220))
        draw.text((x, y), label, font=font, fill=(*color, 255))
    return image


def _labels_for(original: dict, boxes: list[dict]) -> list[str]:
    return [str(original["measures"].index(box)) if box in original["measures"] else "new" for box in boxes]


@_step
def find_bars(output_folder: str | Path, *, send_to_detector: bool = False) -> None:
    """Step 3a: get one box per bar from the measure detector (or reuse saved boxes)."""
    send_to_detector = _switch(send_to_detector, "SEND_PAGES_TO_DETECTOR")
    folders = _folders(output_folder)
    music = _music_pages(folders)
    missing = [page for page in music if not _box_files(folders, page)[0].is_file()]
    if missing and not send_to_detector:
        raise NotDone("The detector has not seen these pages yet: "
                      + ", ".join(_page_name(page) for page in missing) + ".\n"
                      "Set SEND_PAGES_TO_DETECTOR = True in the settings cell, run that cell, "
                      "then run this cell again.")
    if missing:
        print(f"Sending {len(missing)} page(s) to the measure detector. This can take a minute per page ...")
    try:
        records = detect_measure_boxes(folders["pages_json"], allow_upload=send_to_detector)
    except (RuntimeError, OSError) as problem:
        raise NotDone(f"The detector could not be reached or did not answer: {problem}\n"
                      "Check the internet connection and run this cell again later.")
    except _DetectorResponseError as problem:
        raise NotDone(f"The detector sent an answer CAMAT cannot read ({problem}). Try again later.")
    except ValueError as problem:
        details = f"{problem} (step 3)" if isinstance(problem, _PageReviewError) else str(problem)
        raise NotDone(f"The saved boxes do not fit the page pictures ({details}). "
                      "Set a new OUTPUT_FOLDER in the settings cell and start again with step 1.")
    sources = {record["page_id"]: record["source"] for record in records}
    tiles = []
    for page in music:
        original, current = _boxes(folders, page)
        boxes = original["measures"]
        note = " (in use: your corrections from step 3b)" if current != original else ""
        print(f"{_page_name(page)}: the detector found {len(boxes)} boxes{note}")
        image = _labelled_page(folders, page, boxes, [str(i) for i in range(len(boxes))])
        tiles.append((image, f"PDF page {page['pdf_page_number']}: {len(boxes)} boxes"))
        if sources[page["page_id"]] == "manual":
            print("  (boxes from a file you supplied, not from the detector)")
    _show(_sheet(tiles, columns=2, tile_width=520), folders["previews"] / "detector-boxes.png")
    print("Every box has a number. Step 3b checks the boxes against your description from step 2.")


def _corrections(name: str, value: object, music: list[dict], check: Callable) -> dict:
    if not isinstance(value, dict):
        raise NotDone(f"{name} must look like {{2: [...]}}: curly brackets around it.")
    by_number = {page["pdf_page_number"]: page for page in music}
    result = {}
    for number, entries in value.items():
        if number not in by_number:
            raise NotDone(f"{name}: {number!r} is not the number of a music page "
                          f"(music pages: {', '.join(str(n) for n in by_number)}).")
        if not isinstance(entries, (list, tuple)):
            raise NotDone(f"{name}, page {number}: put the entries in square brackets, e.g. {number}: [...].")
        if name == "ADD_BOXES" and len(entries) == 4 and all(isinstance(v, (int, float)) for v in entries):
            entries = [entries]  # a single box without the outer brackets
        result[number] = [check(by_number[number], entry) for entry in entries]
    return result


def _new_box(page: dict, entry: object) -> dict:
    try:
        return _validate_new_box(page, entry)
    except _BoxEditError as problem:
        if "problem" in problem.details:
            # The notebook reported round()'s non-finite-number errors through
            # _step's unexpected-error path. Keep that presentation unchanged.
            raise problem.details["problem"] from None
        raise _box_problem(page, problem) from problem


def _apply_corrections(folders: dict, page: dict, add: list[dict], remove: list) -> None:
    try:
        edit_measure_boxes(folders["pages_json"], page["page_id"],
                           add=[tuple(box.values()) for box in add], remove=remove)
    except _BoxEditError as problem:
        raise _box_problem(page, problem) from problem


def _ruler_picture(folders: dict, page: dict, boxes: list[dict], labels: list[str], band: tuple, path: Path) -> None:
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import MultipleLocator

    x0, y0, x1, y1 = band
    with PILImage.open(folders["pages"] / page["image"]) as source:
        crop = source.convert("L").crop(band)
    figure = Figure(figsize=(13, 13 * (y1 - y0) / (x1 - x0) + 1.2), dpi=100)
    axes = figure.add_subplot()
    axes.imshow(crop, cmap="gray", extent=(x0, x1, y1, y0))
    for box, label in zip(boxes, labels):
        color = "tab:blue" if label == "new" else "red"
        axes.add_patch(Rectangle((box["ulx"], box["uly"]), box["lrx"] - box["ulx"], box["lry"] - box["uly"],
                                 fill=False, edgecolor=color, linewidth=1.5))
        axes.text(box["ulx"] + 12, box["uly"] + 12, label, color=color, fontsize=11, va="top",
                  bbox={"facecolor": "white", "edgecolor": "none", "pad": 1})
    axes.set_xlim(x0, x1)
    axes.set_ylim(y1, y0)
    axes.xaxis.set_major_locator(MultipleLocator(100))
    axes.xaxis.set_minor_locator(MultipleLocator(50))
    axes.yaxis.set_major_locator(MultipleLocator(100))
    axes.tick_params(axis="x", labelrotation=90, labelsize=8)
    axes.tick_params(axis="y", labelsize=8)
    axes.xaxis.set_ticks_position("both")
    axes.tick_params(axis="x", labeltop=True)
    axes.grid(True, which="both", color="tab:blue", alpha=0.25, linewidth=0.6)
    axes.set_xlabel("pixels from the left edge  →  left, right")
    axes.set_ylabel("pixels from the top  →  top, bottom")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path)
    _show_file(path)


def _diagnose(folders: dict, music: list[dict]) -> None:
    print("⚠ NOT DONE. The boxes do not match your description yet:\n")
    for page in music:
        original, current = _boxes(folders, page)
        rows = group_measure_boxes_into_systems(current, page)
        found = [len(row) for row in rows]
        described = [len(system) for system in page["systems"]]
        if found == described:
            continue
        labels = _labels_for(original, current["measures"])
        if len(found) != len(described):
            print(f"{_page_name(page)}: the boxes form {len(found)} rows, but you described "
                  f"{len(described)} systems. Maybe a whole system has no boxes, or the description "
                  "in step 2 has a system too many or too few.")
            _ruler_picture(folders, page, current["measures"], labels,
                           (0, 0, page["width"], page["height"]),
                           folders["previews"] / f"{page['page_id']}-check.png")
            continue
        for number, (row, system) in enumerate(zip(rows, page["systems"]), 1):
            if len(row) == len(system):
                continue
            difference = len(system) - len(row)
            problem = (f"{difference} box{'es are' if difference > 1 else ' is'} missing" if difference > 0
                       else f"{-difference} box{'es' if difference < -1 else ''} too many")
            print(f"{_page_name(page)}, system {number} (bars {_ranges(list(dict.fromkeys(system)))}): "
                  f"you described {len(system)} bars, the detector drew {len(row)} boxes, so {problem}.")
            boxes = [current["measures"][item["box_index"]] for item in row]
            top = max(0, min(box["uly"] for box in boxes) - 150)
            bottom = min(page["height"], max(box["lry"] for box in boxes) + 150)
            _ruler_picture(folders, page, boxes, [labels[item["box_index"]] for item in row],
                           (0, top, page["width"], bottom),
                           folders["previews"] / f"{page['page_id']}-system{number}-check.png")
            print("Boxes on this system, as (left, top, right, bottom):")
            for item in row:
                box = current["measures"][item["box_index"]]
                print(f"  box {labels[item['box_index']]:>3}: ({', '.join(str(round(box[k])) for k in COORDS)})")
            print()
    print("How to fix it:")
    print("  • A box is missing: add it to ADD_BOXES (see the instructions above this cell).")
    print("  • A box is too many: put its number into REMOVE_BOXES.")
    print("  • Or the description in step 2 is wrong: correct it there and run step 2 again.")
    print("Then run this cell again.")


@_step
def check_bars(output_folder: str | Path, add_boxes: dict | None = None, remove_boxes: dict | None = None) -> None:
    """Step 3b: apply your corrections, compare the boxes with step 2, and number them."""
    folders = _folders(output_folder)
    music = _music_pages(folders)
    if any(not _box_files(folders, page)[0].is_file() for page in music):
        raise NotDone("Some music pages have no boxes yet. Run step 3a first.")
    add = _corrections("ADD_BOXES", add_boxes or {}, music, _new_box)
    remove = _corrections("REMOVE_BOXES", remove_boxes or {}, music, lambda page, index: index)
    for page in music:
        _apply_corrections(folders, page, add.get(page["pdf_page_number"], []),
                           remove.get(page["pdf_page_number"], []))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            build_measure_alignment(folders["pages_json"], output=folders["alignment"])
    except _SystemCountError:
        folders["alignment"].unlink(missing_ok=True)
        _diagnose(folders, music)
        return
    regions = json.loads(folders["alignment"].read_text(encoding="utf-8"))["regions"]
    changes = sum(len(v) for v in add.values()) + sum(len(v) for v in remove.values())
    if changes:
        print(f"Your corrections: {sum(len(v) for v in add.values())} box(es) added, "
              f"{sum(len(v) for v in remove.values())} removed.")
    print(f"✓ Every bar has a box: {len(regions)} boxes on {len(music)} pages.")
    print("Look at every picture: does each bar number (movement/bar) sit on the right bar?\n")
    for path in draw_alignment_overlays(folders["alignment"], folders["overlays"]):
        with PILImage.open(path) as overlay:
            preview = overlay.resize((1100, round(overlay.height * 1100 / overlay.width)))
        _show(preview, folders["previews"] / f"check-{path.name}")
    print("If a number sits on the wrong bar, the description in step 2 does not match the print. "
          "Correct it there and run steps 2, 3a and 3b again.")


def _result_path(mei_file: str | Path, output_folder: str | Path) -> Path:
    return _folders(output_folder)["mei"] / f"{resolve_repo_path(mei_file).stem}_with_facsimile.mei"


@_step
def merge_with_mei(mei_file: str | Path, output_folder: str | Path, *, checked_by: str = "", match_line_breaks: bool = True) -> None:
    """Step 4: write a new MEI file with a <facsimile> and measure/@facs links."""
    match_line_breaks = _switch(match_line_breaks, "MATCH_LINE_BREAKS_TO_PDF")
    if not isinstance(checked_by, str):
        raise NotDone('YOUR_NAME must be text in quotes, for example "Clara Schumann".')
    folders = _folders(output_folder)
    output = _result_path(mei_file, output_folder)
    output.unlink(missing_ok=True)  # step 5 must not show an older result if this run fails
    _music_pages(folders)
    try:  # check the boxes as they are now, not an older result
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            build_measure_alignment(folders["pages_json"], output=folders["alignment"])
    except (ValueError, FileNotFoundError):
        raise NotDone("Step 3 is not finished: the boxes do not match your description yet. Go back to step 3b.")
    if checked_by.strip():
        approve_alignment_review(folders["alignment"], checked_by)

    mei = resolve_repo_path(mei_file)
    mdiv_n, _ = _mei_movement(mei)
    text = mei.read_bytes().decode("utf-8")
    if mdiv_n is None:
        text = number_single_mdiv(text)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="camat-guided-") as temp:
        staged = Path(temp) / mei.name
        staged.write_bytes(text.encode("utf-8"))
        try:
            report = integrate_pdf_facsimile(staged, folders["pages_json"], folders["alignment"], output)
        except _IntegrationGateError as problem:
            raise NotDone(f"The MEI and your description from step 2 do not agree: {problem}")
    breaks = write_page_breaks(output, folders["pages_json"], output) if match_line_breaks else None

    print(f"✓ Done. {report['measures_linked']} bars of the MEI now point to "
          f"{report['zones']} boxes on {report['surfaces']} pages.")
    print(f"  New file:      {display_path(output)}")
    print(f"  Page pictures: {display_path(folders['pages'])} (the new file refers to them; keep the folders together)")
    if breaks:
        print(f"  Line breaks:   {breaks['pb']} page breaks and {breaks['sb']} system breaks now follow the PDF.")
    elif report["pb_not_at_page_start"]:
        print(f"  Line breaks:   {len(report['pb_not_at_page_start'])} page break(s) of the MEI do not match the PDF; "
              "set MATCH_LINE_BREAKS_TO_PDF = True to replace them.")
    if report["unreviewed_pages"]:
        print("  ⚠ YOUR_NAME is empty, so the file records that nobody has checked the boxes. "
              "Write your name in the settings cell once you have checked the pictures of step 3b, "
              "run that cell and this one again.")
    else:
        review = json.loads(folders["alignment"].read_text(encoding="utf-8"))["review"].values()
        names = sorted({f"{entry['reviewer']} ({entry['date']})" for entry in review})
        print(f"  Checked by:    {', '.join(names)}")
    if report["other_facsimiles"]:
        print(f"  The MEI already had {report['other_facsimiles']} other <facsimile>; it was kept.")

    result = output.read_text(encoding="utf-8")
    excerpt = [re.search(r"<surface\b[^>]*>", result), re.search(r"<graphic\b[^>]*>", result),
               *list(re.finditer(r"<zone\b[^>]*>", result))[:2]]
    measure = re.search(r"<measure\b[^>]*\bfacs=[^>]*>", result)
    print("\nWhat was added (first lines):")
    for index, match in enumerate(excerpt):
        print(("   " if index else "") + match[0])
    print("   ...")
    print(measure[0])


@_step
def open_result(mei_file: str | Path, output_folder: str | Path):
    """Step 5: show the new file in CAMAT's facsimile viewer."""
    path = _result_path(mei_file, output_folder)
    if not path.is_file():
        raise NotDone("There is no result yet. Run step 4 first.")
    if not _in_jupyter():
        print(f"Result: {display_path(path)} (open this notebook in Jupyter to see the viewer)")
        return None
    return launch_interactive_facsimile_viewer(str(path), verovio_breaks="encoded")
