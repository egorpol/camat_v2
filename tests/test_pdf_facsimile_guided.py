"""Student messages and presentation adapters for the guided PDF notebook."""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

import camat.pdf_facsimile as pf
import camat.pdf_facsimile_guided as guided
from test_pdf_facsimile import fixture, mei, read_json


def guided_fixture(tmp_path: Path, scopes: list[dict], *, boxes: bool = True) -> tuple[Path, Path]:
    pages = fixture(tmp_path, scopes, boxes=boxes)
    out = tmp_path / "out"
    out.mkdir()
    pages.parent.rename(out / "pages")
    return out, out / "pages/pages.json"


@pytest.mark.parametrize("state", ["rendered", "reviewed", "reset"])
def test_failed_description_reset_matches_original_cell_in_reachable_states(tmp_path, monkeypatch, state):
    out, pages = guided_fixture(tmp_path, [{"role": "unreviewed"}, {"role": "unreviewed"}], boxes=False)
    if state != "rendered":
        pf.apply_page_layout(pages, pf.parse_page_layout("1 | cover\n2 | 160 | 1"))
    if state == "reset":
        pf.apply_page_layout(pages, {})
    original = read_json(pages)
    expected = json.loads(pages.read_bytes())
    had_music = any(page.get("role") == "music" for page in expected["pages"])
    if had_music:
        for page in expected["pages"]:
            page.pop("mdiv", None)
            page.pop("systems", None)
            page.update(role="unreviewed", printed_page=None)
    before, mtime = pages.read_bytes(), pages.stat().st_mtime_ns
    with monkeypatch.context() as patch:
        if not had_music:
            patch.setattr(pf, "_write_json", lambda *_: pytest.fail("no previous description should be rewritten"))
        guided._forget_description(guided._folders(out), original)
    assert pages.read_bytes() == (json.dumps(expected, indent=2, ensure_ascii=False) + "\n").encode()
    if not had_music:
        assert pages.read_bytes() == before and pages.stat().st_mtime_ns == mtime


def test_description_failure_resets_and_preserves_mei_error_priority(tmp_path, capsys):
    out, pages = guided_fixture(tmp_path, [{"mdiv": 1, "systems": [[1, 2]]}])
    source = mei(tmp_path, [("1", [1, 2])])
    guided.describe_pages("1 | 160 | 1", source, out)
    assert capsys.readouterr().out == (
        "\n⚠ NOT DONE. Your description and the MEI do not have the same bars.\n"
        "  In the MEI but not in your description: 2\n"
        "The MEI has 2 bars: 1–2. Correct the description and run this cell again.\n"
    )
    assert read_json(pages)["pages"][0]["role"] == "unreviewed"
    guided.find_bars(out)
    assert capsys.readouterr().out == "\n⚠ NOT DONE. No page is described as music yet. Run step 2 first.\n"
    missing = tmp_path / "absent.mei"
    guided.describe_pages("invalid description", missing, out)
    assert capsys.readouterr().out == (
        f"\n⚠ NOT DONE. The MEI file is missing: {guided.display_path(missing)}. Check MEI_FILE in the settings cell.\n"
    )


def test_description_success_table_and_split_message(tmp_path, capsys):
    out, _ = guided_fixture(tmp_path, [{"role": "unreviewed"}, {"role": "unreviewed"}], boxes=False)
    source = mei(tmp_path, [("1", [1, 2])])
    source.write_bytes(source.read_bytes().replace(b'<mdiv n="1">', b'<mdiv>'))
    guided.describe_pages("1 | cover\n2 | 160 | 1, 1-2", source, out)
    assert capsys.readouterr().out == (
        "PDF page | printed page | content\n"
        "       1 |            - | cover, no music\n"
        "       2 |          160 | music: 2 systems, bars 1–2\n"
        "\n✓ Your description matches the MEI: all 2 bars, in the same order.\n"
        "  Bars that continue on the next system: 1\n"
        "  (The movement in the MEI has no number; step 4 numbers it 1 in the new file.)\n"
    )


@pytest.mark.parametrize("switch,call", [
    ("DOWNLOAD_EXAMPLE_PDF", lambda out: guided.make_page_images("missing.pdf", out, download_example="True")),
    ("SEND_PAGES_TO_DETECTOR", lambda out: guided.find_bars(out, send_to_detector=1)),
    ("MATCH_LINE_BREAKS_TO_PDF", lambda out: guided.merge_with_mei("missing.mei", out, match_line_breaks=None)),
])
def test_switch_messages(tmp_path, capsys, switch, call):
    call(tmp_path)
    assert capsys.readouterr().out == (
        f"\n⚠ NOT DONE. {switch} must be True or False, written without quotes. "
        "Correct it in the settings cell and run that cell again.\n"
    )


@pytest.mark.parametrize("add,remove,message", [
    (["box"], {}, "ADD_BOXES must look like {2: [...]}: curly brackets around it."),
    ({2: [(1, 1, 2, 2)]}, {}, "ADD_BOXES: 2 is not the number of a music page (music pages: 1)."),
    ({1: "box"}, {}, "ADD_BOXES, page 1: put the entries in square brackets, e.g. 1: [...]."),
    ({1: [(True, 1, 2, 3)]}, {}, "ADD_BOXES, page 1: (True, 1, 2, 3) is not a box. Write four numbers in round brackets: (left, top, right, bottom)."),
    ({1: [(2, 1, 1, 3)]}, {}, "ADD_BOXES, page 1: in (2, 1, 1, 3), left must be smaller than right and top smaller than bottom. The order is (left, top, right, bottom)."),
    ({1: [(1, 1, 2, 900)]}, {}, "ADD_BOXES, page 1: (1, 1, 2, 900) reaches outside the page (the picture is 320 × 480 pixels)."),
    ({1: [(10, 20, 55, 80)]}, {}, "ADD_BOXES, page 1: (10, 20, 55, 80) covers most of box 0. Is that bar really missing?"),
    ({}, {1: [99]}, "REMOVE_BOXES, page 1: 99 is not a box number (this page has boxes 0 to 0)."),
    ({}, {1: 7}, "REMOVE_BOXES, page 1: put the entries in square brackets, e.g. 1: [...]."),
])
def test_correction_student_messages(tmp_path, capsys, add, remove, message):
    out, _ = guided_fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}])
    guided.check_bars(out, add, remove)
    assert capsys.readouterr().out == f"\n⚠ NOT DONE. {message}\n"


def test_single_tuple_correction_and_typed_count_failure(tmp_path, monkeypatch, capsys):
    out, pages = guided_fixture(tmp_path, [{"mdiv": 1, "systems": [[1, 2]]}])
    def count_failure(*args, **kwargs):
        raise pf._SystemCountError("wording deliberately changed")
    monkeypatch.setattr(guided, "build_measure_alignment", count_failure)
    monkeypatch.setattr(guided, "_diagnose", lambda *_: print("count diagnosis"))
    guided.check_bars(out, {1: (180, 250, 230, 350)}, {1: [0]})
    assert capsys.readouterr().out == "count diagnosis\n"
    assert len(read_json(pages.parent / "boxes/print-p0001.json")["measures"]) == 2


def test_student_box_message_uses_details_not_library_wording(tmp_path, monkeypatch):
    page = {"page_id": "print-p0001", "pdf_page_number": 1}
    def fail(*_):
        raise pf._BoxEditError("unrelated wording", "malformed", entry="bad")
    monkeypatch.setattr(guided, "_validate_new_box", fail)
    with pytest.raises(guided.NotDone) as caught:
        guided._new_box(page, "bad")
    assert str(caught.value) == "ADD_BOXES, page 1: 'bad' is not a box. Write four numbers in round brackets: (left, top, right, bottom)."


def test_student_movement_message_uses_details_not_library_wording(monkeypatch):
    def fail(*_):
        raise pf._LayoutError("unrelated wording", "multiple_mdivs", count=2)
    monkeypatch.setattr(guided, "_read_movement", fail)
    path = Path("score.mei")
    with pytest.raises(guided.NotDone) as caught:
        guided._mei_movement(path)
    assert str(caught.value) == (
        f"{guided.display_path(path)} has 2 movements (<mdiv> elements). This guided notebook "
        "links one movement. For several, use mei_pdf_facsimile_integration.ipynb."
    )


@pytest.mark.parametrize("error,message", [
    (pf._DetectorResponseError("new wording"), "The detector sent an answer CAMAT cannot read (new wording). Try again later."),
    (ValueError("saved issue"), "The saved boxes do not fit the page pictures (saved issue). Set a new OUTPUT_FOLDER in the settings cell and start again with step 1."),
    (pf._PageReviewError("page review"), "The saved boxes do not fit the page pictures (page review (step 3)). Set a new OUTPUT_FOLDER in the settings cell and start again with step 1."),
    (RuntimeError("offline"), "The detector could not be reached or did not answer: offline\nCheck the internet connection and run this cell again later."),
])
def test_detector_failure_routing_uses_exception_types(tmp_path, monkeypatch, capsys, error, message):
    out, _ = guided_fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}])
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(guided, "detect_measure_boxes", fail)
    guided.find_bars(out)
    assert capsys.readouterr().out == f"\n⚠ NOT DONE. {message}\n"


def test_download_shared_function_reuses_bytes_and_reports_url(tmp_path, monkeypatch):
    path = tmp_path / "source/example.pdf"
    data = b"%PDF-1.4\nexample"
    calls, urls = [], []
    def response(url, timeout):
        calls.append((url, timeout))
        return BytesIO(b'<a href="/pdf/123bsb00023199.pdf">PDF</a>' if url == guided.BSB_FORM_URL else data)
    monkeypatch.setattr(guided.urllib.request, "urlopen", response)
    assert guided.download_example_pdf(path, on_download=urls.append) == path
    assert path.read_bytes() == data
    assert urls == [guided.BSB_HOST + "/pdf/123bsb00023199.pdf"]
    assert calls == [(guided.BSB_FORM_URL, 120), (urls[0], 300)]
    mtime = path.stat().st_mtime_ns
    assert guided.download_example_pdf(path) == path
    assert len(calls) == 2 and path.stat().st_mtime_ns == mtime


@pytest.mark.parametrize("html,data,code,student", [
    (b"no link", b"", "links", "The library's download page looked different than expected. Download the PDF by hand (see the instructions above)."),
    (b'<a href="/pdf/1bsb00023199.pdf">a</a><a href="/pdf/2bsb00023199.pdf">b</a>', b"", "links", "The library's download page looked different than expected. Download the PDF by hand (see the instructions above)."),
    (b'<a href="/pdf/1bsb00023199.pdf">a</a>', b"not a PDF", "pdf", "The library did not send a PDF. Download it by hand (see the instructions above)."),
])
def test_download_ordinary_errors_and_guided_messages(tmp_path, monkeypatch, capsys, html, data, code, student):
    path = tmp_path / "source/example.pdf"
    monkeypatch.setattr(guided.urllib.request, "urlopen", lambda url, timeout: BytesIO(html if url == guided.BSB_FORM_URL else data))
    with pytest.raises(ValueError) as caught:
        guided.download_example_pdf(path)
    assert not isinstance(caught.value, guided.NotDone)
    assert caught.value.code == code and not path.exists()
    with pytest.raises(guided.NotDone) as caught:
        guided._download_example(path)
    assert str(caught.value) == student
    assert capsys.readouterr().out == "Downloading the example PDF from the Bayerische Staatsbibliothek ...\n"


def test_picture_display_headless_and_contact_sheet(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(guided, "_in_jupyter", lambda: False)
    path = tmp_path / "previews/pages.png"
    sheet = guided._sheet([(Image.new("L", (100, 200)), "PDF page 1"),
                           (Image.new("RGB", (100, 100)), "PDF page 2")], columns=2, tile_width=50)
    assert sheet.mode == "RGB" and sheet.size == (160, 160)
    guided._show(sheet, path)
    assert path.is_file()
    assert capsys.readouterr().out == f"(picture: {guided.display_path(path)})\n"


def test_no_result_and_bad_reviewer_messages(tmp_path, capsys):
    guided.open_result("source.mei", tmp_path)
    assert capsys.readouterr().out == "\n⚠ NOT DONE. There is no result yet. Run step 4 first.\n"
    guided.merge_with_mei("source.mei", tmp_path, checked_by=None)
    assert capsys.readouterr().out == '\n⚠ NOT DONE. YOUR_NAME must be text in quotes, for example "Clara Schumann".\n'


def test_guided_poppler_message_ignores_library_wording(monkeypatch):
    def missing():
        raise RuntimeError("unrelated library wording")
    monkeypatch.setattr(guided, "check_poppler", missing)
    with pytest.raises(guided.NotDone) as caught:
        guided._require_poppler()
    assert str(caught.value) == (
        "This step needs the free program Poppler, which is not installed.\n"
        + pf.POPPLER_INSTALL_HINTS
        + "Then restart the kernel (Kernel → Restart Kernel) and run the notebook again from the top."
    )


def test_tutorial_missing_poppler_prints_hints_without_traceback(monkeypatch, capsys):
    notebook = Path(__file__).resolve().parents[1] / "notebooks/mei_pdf_facsimile_integration.ipynb"
    cell = "".join(json.loads(notebook.read_text())["cells"][7]["source"])
    monkeypatch.setattr(pf.shutil, "which", lambda *_: None)
    exec(cell, {"check_poppler": pf.check_poppler, "shutil": pf.shutil})
    assert capsys.readouterr().out == (
        "Poppler's pdftoppm is missing; install it and put it on PATH:\n"
        + pf.POPPLER_INSTALL_HINTS
        + "Then re-run this cell.\n"
    )


def test_detector_response_error_has_structured_type(tmp_path, monkeypatch):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}], boxes=False)
    def invalid_response(*args, **kwargs):
        raise ValueError("unrelated detector wording")
    monkeypatch.setattr(pf, "upload_image", invalid_response)
    with pytest.raises(pf._DetectorResponseError, match="unrelated detector wording"):
        pf.detect_measure_boxes(pages, allow_upload=True)


@pytest.mark.parametrize("value,error,message", [
    (float("nan"), ValueError, "cannot convert float NaN to integer"),
    (float("inf"), OverflowError, "cannot convert float infinity to integer"),
])
def test_nonfinite_guided_box_preserves_original_round_error(value, error, message):
    page = {"page_id": "print-p0001", "pdf_page_number": 1, "width": 320, "height": 480}
    with pytest.raises(error) as caught:
        guided._new_box(page, (1, 2, value, 4))
    assert str(caught.value) == message
