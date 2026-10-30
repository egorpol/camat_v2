"""Checks of the review-page builder on a small MEI in a throwaway git repository.

The page image is generated, the IIIF route is served by a stand-in for the
download function, so nothing here uses the network.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import re
import subprocess
import tomllib
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

from camat import review_page as rp


REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "camat" / "schemas" / "review.schema.json"
BASE_PITCHES = {1: "cdef", 2: "gabc", 3: "cdef", 4: "gfed"}


def mei(pitches: dict[int, str], harm_tstamps: dict[int, str], *, target: str = "page.png", width: int = 800,
        bars: int = 4) -> str:
    """Four bars with zones on one page (bar 4 has none) and a figure in each bar."""
    zones = "".join(f'<zone xml:id="z{n}" type="measure" ulx="{50 + (n - 1) * 180}" uly="100" '
                    f'lrx="{220 + (n - 1) * 180}" lry="250"/>' for n in range(1, 4))
    measures = []
    for n in range(1, bars + 1):
        facs = f' facs="#z{n}"' if n < 4 else ""
        notes = "".join(f'<note xml:id="n{n}-{i}" pname="{p}" oct="4" dur="4"/>' for i, p in enumerate(pitches[n]))
        measures.append(f'<measure xml:id="m{n}" n="{n}"{facs}><staff n="1"><layer n="1">{notes}</layer></staff>'
                        f'<harm xml:id="h{n}" staff="1" tstamp="{harm_tstamps.get(n, "1")}"><fb><f>6</f><f>4</f></fb>'
                        '</harm></measure>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1">'
            '<meiHead><fileDesc><titleStmt><title>T</title></titleStmt><pubStmt/></fileDesc></meiHead><music>'
            f'<facsimile><surface xml:id="s1"><graphic target="{target}" width="{width}" height="600"/>{zones}'
            '</surface></facsimile><body><mdiv><score><scoreDef meter.count="4" meter.unit="4"><staffGrp>'
            '<staffDef n="1" lines="5" clef.shape="G" clef.line="2"/></staffGrp></scoreDef><section><pb facs="#s1"/>'
            + "".join(measures) + "</section></score></mdiv></body></music></mei>\n")


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
                   check=True, capture_output=True)


def spec(**changes) -> dict:
    data = {"title": "Review", "storage_key": "test-review", "description": "<p>Two questions.</p>", "cards": [
        {"id": "m2", "label": "m. 2", "mei": "work.mei", "measures": "2", "description": "Last note <b>D4</b>?"},
        {"id": "fig", "label": "Figures", "mei": "work.mei", "measures": "1-4", "rows": True, "status": "partly"},
        {"id": "m34", "label": "mm. 3–4", "mei": "work.mei", "measures": ["#m3", "#m4"], "status": "confirmed",
         "images": [{"src": "page.png", "caption": "The whole page"}]},
    ]}
    data.update(changes)
    return data


@pytest.fixture
def example(tmp_path: Path) -> Path:
    """A repository whose working tree changes bar 2's last note and moves bar 3's figure."""
    root = tmp_path / "edition"
    root.mkdir()
    Image.new("RGB", (800, 600), "white").save(root / "page.png")
    (root / "work.mei").write_text(mei(BASE_PITCHES, {}), encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-qm", "first")
    (root / "work.mei").write_text(mei({**BASE_PITCHES, 2: "gabd"}, {3: "2"}), encoding="utf-8")
    return root


def write_spec(root: Path, data: dict) -> Path:
    path = root / "review.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def page_data(out: Path) -> dict:
    page = (out / "index.html").read_text(encoding="utf-8")
    return json.loads(re.search(r'<script id="review-data" type="application/json">(.*?)</script>', page).group(1))


def bar_ids(svg: Path) -> list[str]:
    return re.findall(r'<g id="(m\d)" class="measure', svg.read_text(encoding="utf-8"))


def test_builds_cards_rows_crops_and_renders(example, tmp_path):
    out = tmp_path / "review"
    report = rp.build_review_page(write_spec(example, spec()), out)

    assert (report["cards"], report["rows"], report["crops"]) == (3, 4, 5)
    assert report["warnings"] == ["fig: no facsimile zone for bar 4", "m34: no facsimile zone for bar 4"]
    assert {"index.html", "review.css", "review.js", "images/m34-1.png"} <= set(report["files"])
    assert sorted(p.name for p in out.iterdir()) == ["crops", "images", "index.html", "renders", "review.css", "review.js"]
    # Each render shows the card's bars only, before and after.
    assert bar_ids(out / "renders/m2-before-1.svg") == bar_ids(out / "renders/m2-after-1.svg") == ["m2"]
    assert bar_ids(out / "renders/m34-after-1.svg") == ["m3", "m4"]
    # The crop is the zone (170 x 150) plus the default padding, cut from the page.
    assert Image.open(out / "crops/m2-1.jpg").size == (170 + 200 + 200, 150 + 80 + 240)
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "note C4→D4" in page
    assert '<span class="moves">harm 6/4: tstamp 1→2</span>' in page
    assert page.count('<span class="moves">no event changed</span>') == 2
    assert "Last note <b>D4</b>?" in page and "<p>Two questions.</p>" in page
    assert 'id="show-before" checked> HEAD column' in page
    assert page_data(out) == {"storage_key": "test-review", "title": "Review", "cards": [
        {"key": "m2", "label": "m. 2", "rows": None},
        {"key": "fig", "label": "Figures", "rows": [{"key": f"fig-{n}", "label": f"m. {n}"} for n in range(1, 5)]},
        {"key": "m34", "label": "mm. 3–4", "rows": None},
    ]}


def test_without_before_ref_there_is_no_before_column(example, tmp_path):
    out = tmp_path / "review"
    report = rp.build_review_page(write_spec(example, spec(before_ref=None)), out)
    page = (out / "index.html").read_text(encoding="utf-8")
    assert '<body class="no-before">' in page and "show-before" not in page and 'class="before"' not in page
    assert not [name for name in report["files"] if "-before-" in name]
    assert '<span class="moves"></span>' in page


def test_a_bar_missing_at_the_ref_gets_a_placeholder(example, tmp_path):
    (example / "work.mei").write_text(mei({**BASE_PITCHES, 5: "cdef"}, {}, bars=5), encoding="utf-8")
    data = spec(cards=[{"id": "new", "mei": "work.mei", "measures": "5"},
                       {"id": "rows", "mei": "work.mei", "measures": "4-5", "rows": True}])
    out = tmp_path / "review"
    rp.build_review_page(write_spec(example, data), out)
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "not at HEAD: no bar 5" in page
    assert "not at HEAD: this bar is missing" in page
    assert "+ note C4 · + note D4" in page


def test_lists_every_problem_and_writes_nothing(example, tmp_path):
    out = tmp_path / "review"
    data = spec(colour="red", storage_key="Has Spaces", before_ref="no-such-ref", crop={"size": "50%"}, cards=[
        {"id": "a", "mei": "work.mei", "measures": "9"},
        {"id": "a", "mei": "work.mei", "measures": "2", "status": "maybe"},
        {"id": "b", "mei": "missing.mei", "measures": "2"},
        {"id": "c", "mei": "work.mei", "measures": "3-1", "images": [{"src": "nowhere.png"}]},
        {"id": "d", "mei": "work.mei", "measures": 2},
    ])
    with pytest.raises(rp.ReviewSpecError) as error:
        rp.build_review_page(write_spec(example, data), out)
    problems = "\n".join(error.value.problems)
    for expected in ("colour: unknown key", "storage_key: expected lower-case", "crop.size: expected a IIIF size",
                     "cards[0].mei: cannot read work.mei at no-such-ref", "cards[0].measures: no bar 9 in work.mei",
                     "cards[1].id: 'a' is used twice", "cards[1].status: expected one of check, partly, confirmed",
                     "cards[2].mei: cannot read", "cards[3].measures: bar 1 comes before bar 3",
                     "cards[3].images[0].src:", "cards[4].measures: expected"):
        assert expected in problems
    assert not out.exists()
    assert not list(tmp_path.glob(".review.*"))


def test_repeated_bar_numbers_need_xml_ids(example, tmp_path):
    text = mei(BASE_PITCHES, {}).replace('xml:id="m3" n="3"', 'xml:id="m3" n="2"')
    (example / "work.mei").write_text(text, encoding="utf-8")
    with pytest.raises(rp.ReviewSpecError, match=r'2 bars have n=.2. \(#m2, #m3\); give xml:ids'):
        rp.build_review_page(write_spec(example, spec(before_ref=None, cards=[
            {"id": "x", "mei": "work.mei", "measures": "2"}])), tmp_path / "review")
    report = rp.build_review_page(write_spec(example, spec(before_ref=None, cards=[
        {"id": "x", "mei": "work.mei", "measures": ["#m3"]}])), tmp_path / "review")
    assert bar_ids(Path(report["out"]) / "renders/x-after-1.svg") == ["m3"]


def test_bars_across_an_encoded_page_break_render_together(example, tmp_path):
    # With Verovio's encoded breaks, a selection across <pb/> lost the bars after it (an empty second page).
    text = mei(BASE_PITCHES, {}).replace('<measure xml:id="m3"', '<pb/><measure xml:id="m3"')
    (example / "work.mei").write_text(text, encoding="utf-8")
    report = rp.build_review_page(write_spec(example, spec(before_ref=None, cards=[
        {"id": "x", "mei": "work.mei", "measures": "2-3"}])), tmp_path / "review")
    assert report["renders"] == 1
    assert bar_ids(Path(report["out"]) / "renders/x-after-1.svg") == ["m2", "m3"]


def test_out_must_not_exist(example, tmp_path):
    (tmp_path / "review").mkdir()
    with pytest.raises(rp.ReviewSpecError, match="exists; each review goes into a new folder"):
        rp.build_review_page(write_spec(example, spec()), tmp_path / "review")


def test_local_crop_scales_from_graphic_to_image_pixels(example, tmp_path):
    # The image is twice the size the graphic records, so the zone is cut at twice its coordinates.
    Image.new("RGB", (1600, 1200), "white").save(example / "page.png")
    (example / "work.mei").write_text(mei(BASE_PITCHES, {}), encoding="utf-8")
    report = rp.build_review_page(write_spec(example, spec(before_ref=None, crop={"padding": [0, 0, 0, 0], "size": "max"},
                                                           cards=[{"id": "x", "mei": "work.mei", "measures": "2"}])),
                                  tmp_path / "review")
    assert Image.open(Path(report["out"]) / "crops/x-1.jpg").size == (340, 300)


def test_iiif_crops_are_pixel_regions_scaled_by_info_json(example, tmp_path, monkeypatch):
    """BSB masters are larger than the graphic and refuse pct: regions."""
    base = "https://images.example.org/iiif/2/page_0001"
    (example / "work.mei").write_text(mei(BASE_PITCHES, {}, target=f"{base}/full/800,/0/default.jpg"), encoding="utf-8")
    requested = []

    def download(url: str) -> Path:
        requested.append(url)
        path = tmp_path / f"download-{len(requested)}"
        if url.endswith("/info.json"):
            path.write_text(json.dumps({"width": 2000, "height": 1500}), encoding="utf-8")
        else:
            buffer = io.BytesIO()
            Image.new("RGB", (64, 48), "white").save(buffer, "JPEG")
            path.write_bytes(buffer.getvalue())
        return path

    monkeypatch.setattr(rp, "_download", download)
    report = rp.build_review_page(write_spec(example, spec(before_ref=None, cards=[
        {"id": "x", "mei": "work.mei", "measures": "2"}])), tmp_path / "review")
    # Zone 230,100-400,250 padded to 30,20-600,490 in graphic pixels, times 2000 / 800.
    assert requested == [f"{base}/info.json", f"{base}/75,50,1425,1175/!1400,1600/0/default.jpg"]
    assert Image.open(Path(report["out"]) / "crops/x-1.jpg").size == (64, 48)


def test_diff_events_names_pitches_durations_and_figures():
    def bar(content: str) -> ET.Element:
        return ET.fromstring('<measure xmlns="http://www.music-encoding.org/ns/mei" '
                             f'xmlns:xml="http://www.w3.org/XML/1998/namespace" n="1"><staff n="1"><layer n="1">{content}'
                             '</layer></staff></measure>')

    before = bar('<note xml:id="a" pname="c" oct="4" dur="4"/><note xml:id="b" pname="e" oct="4" dur="8">'
                 '<accid accid="f"/></note><rest xml:id="r" dur="4"/>')
    after = bar('<note xml:id="a" pname="d" oct="4" dur="8"/><note xml:id="b" pname="e" oct="4" dur="8"/>'
                '<note xml:id="c" pname="g" oct="3" dur="4" staff="2"/>')
    assert rp.diff_events(before, after) == ["note C4→D4: dur 4→8", "note E♭4→E4", "+ note G3", "− rest 4"]
    assert rp.diff_events(after, after) == []


def test_cli_reports_and_fails_cleanly(example, tmp_path, capsys):
    path = write_spec(example, spec())
    assert rp.main([str(path), str(tmp_path / "review")]) == 0
    printed = capsys.readouterr().out
    assert "3 cards, 4 rows" in printed and "fig: no facsimile zone for bar 4" in printed
    assert rp.main([str(path), str(tmp_path / "review")]) == 1
    assert "exists; each review goes into a new folder" in capsys.readouterr().err


def test_the_package_ships_the_template_and_the_command():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"]["camat-review-page"] == "camat.review_page:main"
    data = project["tool"]["setuptools"]["package-data"]["camat"]
    for name in rp.TEMPLATE_FILES:
        assert f"review_page_template/*{Path(name).suffix}" in data
        assert (REPO / "camat" / "review_page_template" / name).is_file()


def _schema_keys(node: dict) -> set[str]:
    return set(node["properties"])


def test_schema_has_the_builders_keys():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert _schema_keys(schema) == rp._KEYS
    assert set(schema["required"]) == {"title", "storage_key", "cards"}
    assert _schema_keys(schema["properties"]["labels"]) == rp._LABEL_KEYS
    assert _schema_keys(schema["properties"]["crop"]) == rp._CROP_KEYS
    assert schema["properties"]["crop"]["properties"]["padding"]["default"] == list(rp.CROP_PADDING)
    assert schema["properties"]["crop"]["properties"]["size"]["default"] == rp.CROP_SIZE
    assert schema["properties"]["crop"]["properties"]["size"]["pattern"].strip("^$") == rp._SIZE.pattern.removesuffix(r"\Z").replace("(?:", "(")
    assert _schema_keys(schema["definitions"]["card"]) == rp._CARD_KEYS
    assert schema["definitions"]["card"]["properties"]["status"]["enum"] == list(rp.STATUSES)
    assert _schema_keys(schema["definitions"]["image"]) == rp._IMAGE_KEYS
    assert schema["properties"]["storage_key"]["pattern"].strip("^$") == rp._STORAGE_KEY.pattern.removesuffix(r"\Z")
    assert schema["definitions"]["card"]["properties"]["id"]["pattern"].strip("^$") == rp._ID.pattern.removesuffix(r"\Z")


@pytest.mark.parametrize("change", [
    {"colour": "red"}, {"storage_key": "Has Spaces"}, {"version": 2}, {"crop": {"size": "50%"}},
    {"crop": {"padding": [1, 2, 3]}}, {"labels": {"page": "x"}}, {"before_ref": "-x"}, {"cards": []},
    {"cards": [{"id": "a", "mei": "work.mei", "measures": "2", "status": "maybe"}]},
    {"cards": [{"id": "a", "mei": "work.mei", "measures": 2}]},
    {"cards": [{"id": "a", "mei": "work.mei", "measures": "2", "images": [{"caption": "x"}]}]},
])
def test_schema_accepts_the_example_and_refuses_what_the_builder_refuses(example, tmp_path, change):
    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft7Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    jsonschema.Draft7Validator.check_schema(validator.schema)
    assert not list(validator.iter_errors(spec(before_ref=None)))
    assert list(validator.iter_errors(spec(**change)))
    with pytest.raises(rp.ReviewSpecError):
        rp.build_review_page(write_spec(example, spec(**change)), tmp_path / "review")
