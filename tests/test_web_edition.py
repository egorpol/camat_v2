"""Checks of the web-edition template and its builder on camat's own small example.

The example runs the PDF facsimile chain of :mod:`camat.pdf_facsimile` on
generated page images (no Poppler) and builds a site from its output.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tomllib

from PIL import Image
import pytest

from camat import pdf_facsimile as pf
from camat import web_edition as we


REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "camat" / "web_edition_template"
SYSTEMS = {1: [[1, 2], [3]], 2: [[4, 5]]}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def score(path: Path, bars: int = 5) -> Path:
    measures = []
    for n in range(1, bars + 1):
        notes = "".join(f'<note xml:id="n{n}-{i}" pname="{p}" oct="4" dur="4" />' for i, p in enumerate("cdef"))
        measures.append(f'          <measure xml:id="m{n}" n="{n}"><staff n="1"><layer n="1">{notes}</layer></staff></measure>')
    annot = ('          <annot xml:id="note-1" type="editorial" plist="#n2-1">'
             '<p>Bar 2: see <ref target="https://example.org/source">the source</ref>.</p></annot>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1">\n'
        '  <meiHead><fileDesc><titleStmt><title>Example</title></titleStmt>'
        '<editionStmt><edition n="0.1">Example edition</edition></editionStmt>'
        '<pubStmt /></fileDesc></meiHead>\n'
        '  <music><body><mdiv n="1"><score>\n'
        '        <scoreDef meter.count="4" meter.unit="4"><staffGrp>'
        '<staffDef n="1" lines="5" clef.shape="G" clef.line="2" /></staffGrp></scoreDef>\n'
        '        <section>\n' + "\n".join(measures) + "\n" + annot + "\n"
        '        </section>\n      </score></mdiv></body></music>\n</mei>\n', encoding="utf-8")
    return path


def chain(root: Path) -> tuple[Path, Path]:
    """Page images, manual boxes and a linked MEI: the output of camat's PDF facsimile chain."""
    folder = root / "facsimiles" / "print"
    folder.mkdir(parents=True)
    pages = []
    for number, systems in SYSTEMS.items():
        image = folder / f"page-{number:04d}.png"
        Image.new("RGB", (320, 480), (250, 250, 250)).save(image)
        pages.append({"page_id": f"print-p{number:04d}", "pdf_page_number": number + 1, "image": image.name,
                      "width": 320, "height": 480, "sha256": sha(image), "printed_page": str(number + 2),
                      "role": "music", "mdiv": 1, "systems": systems})
        boxes = [{"ulx": 10 + i * 100, "uly": 20 + s * 150, "lrx": 105 + i * 100, "lry": 120 + s * 150}
                 for s, bars in enumerate(systems) for i, _ in enumerate(bars)]
        write_json(folder / "boxes" / f"print-p{number:04d}.json", {"measures": boxes})
    manifest = folder / "pages.json"
    write_json(manifest, {"schema_version": 1, "source_id": "print", "pdf": "print.pdf", "pdf_sha256": "f" * 64,
                          "page_count": 3, "dpi": 300, "renderer": "test renderer",
                          "coordinate_system": "image pixels; origin top-left; x right, y down", "pages": pages})
    pf.detect_measure_boxes(str(manifest))
    alignment = pf.build_measure_alignment(str(manifest))
    linked = root / "mei" / "example.mei"
    pf.integrate_pdf_facsimile(str(score(root / "input" / "example.mei")), str(manifest), str(alignment), str(linked))
    pf.write_page_breaks(str(linked), str(manifest), str(linked))
    return linked, manifest


def site_config(root: Path, **changes) -> Path:
    config = {
        "title": "Example <Edition> & Co",
        "description": "camat's small example",
        "subtitle": "After a print",
        "storage_prefix": "example-edition",
        "links": [{"text": "Source files", "url": "https://example.org/repo"}],
        "footer": "Encoding: CC BY 4.0.",
        "labels": {"work": "Piece"},
        "works": [{"id": "I", "label": "I", "title": "Piece I", "mei": "mei/example.mei"}],
        "facsimile": {"type": "pdf", "pages": "facsimiles/print/pages.json",
                      "pdf": {"url": "https://example.org/print.pdf", "text": "example.org"},
                      "images": {"copy": True, "confirm": "Show it only where the print is in the public domain."}},
    }
    config.update(changes)
    path = root / "site.json"
    write_json(path, config)
    return path


@pytest.fixture
def example(tmp_path: Path) -> Path:
    chain(tmp_path)
    return tmp_path


def runtime_config(index: str) -> dict:
    match = re.search(r'<script type="application/json" id="site-config">(.*?)</script>', index, re.S)
    return json.loads(match[1])


def test_site_from_the_pdf_facsimile_chain(example):
    out = example / "public"
    report = we.build_site(site_config(example), out)
    assert report["files"] == [
        ".camat-site", ".nojekyll", "facsimile-pdf.js", "facsimile/page-0001.png", "facsimile/page-0002.png",
        "facsimile/pages.json", "index.html", "mei/example.mei", "viewer.css", "viewer.js", "works.json"]
    assert sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()) == report["files"]
    assert report["works"] == [{"id": "I", "measures": 5, "measures_with_zone": 5, "measures_without_id": 0,
                                "notes": 1, "facsimile_pages": 2}]
    assert (out / "mei/example.mei").read_bytes() == (example / "mei/example.mei").read_bytes()
    assert sha(out / "facsimile/page-0001.png") == sha(example / "facsimiles/print/page-0001.png")
    for name in ("viewer.js", "viewer.css", "facsimile-pdf.js"):
        assert (out / name).read_bytes() == (TEMPLATE / name).read_bytes()

    index = (out / "index.html").read_text(encoding="utf-8")
    assert "<title>Example &lt;Edition&gt; &amp; Co</title>" in index
    assert '<a href="https://example.org/print.pdf">example.org</a>' in index
    assert '<p class="warning">Show it only where the print is in the public domain.</p>' in index
    assert 'id="pdf-input"' in index and 'id="scan-show"' in index and "pdf.js</a> 6.3.289" in index
    assert "<code>#I/1</code>" in index and '<main class="panes">' in index
    assert not re.search(r"\$[a-z_]", index)
    config = runtime_config(index)
    assert config["prefix"] == "example-edition" and config["labels"]["work"] == "Piece"
    assert config["labels"]["bar"] == "Bar" and config["verovio"]["breaks"] == "encoded"
    assert config["facsimile"] == {"type": "pdf", "pages": "facsimile/pages.json", "pdf": True,
                                   "images": {"url": "facsimile/", "confirm": True}}
    assert read_json(out / "works.json") == {"works": [
        {"id": "I", "label": "I", "title": "Piece I", "mei": "mei/example.mei"}]}
    pages = read_json(out / "facsimile/pages.json")
    assert pages["page_count"] == 3 and pages["pdf_sha256"] == "f" * 64
    assert set(pages["pages"][0]) == {"page_id", "image", "width", "height", "sha256", "pdf_page_number", "printed_page"}


def test_the_example_mei_has_what_the_viewer_reads(example):
    text = (example / "mei/example.mei").read_text(encoding="utf-8")
    # One zone per bar, page breaks pointing at surfaces, graphic sizes for the zone viewBox.
    assert text.count('<zone ') == 5 and text.count('<pb ') == 2
    assert re.search(r'<pb [^>]*facs="#surface-print-p0001"', text)
    assert re.search(r'<graphic [^>]*target="[^"]*page-0001.png"[^>]*width="320"[^>]*height="480"', text)
    assert re.search(r'<measure [^>]*n="4"[^>]*facs="#zone-print-p0002-001"', text)


def test_rebuild_replaces_an_earlier_build(example):
    out = example / "public"
    we.build_site(site_config(example), out)
    (out / "stale.txt").write_text("from an earlier build")
    report = we.build_site(site_config(example, facsimile=None), out)
    assert not (out / "stale.txt").exists() and not (out / "facsimile").exists()
    assert "facsimile-pdf.js" not in report["files"]
    assert not [p for p in example.iterdir() if p.name.startswith(".public")]


def _break(config: dict, example: Path) -> None:
    config["storage_prefix"] = "My Edition"


MUTATIONS = {
    "storage_prefix": (_break, "storage_prefix: expected lower-case"),
    "unknown key": (lambda c, e: c.update(titel="x"), "titel: unknown key"),
    "duplicate id": (lambda c, e: c["works"].append(dict(c["works"][0], mei="input/example.mei")), "'I' is used twice"),
    "work id": (lambda c, e: c["works"][0].update(id="I/1"), "works[0].id: expected letters"),
    "missing MEI": (lambda c, e: c["works"][0].update(mei="mei/missing.mei"), "missing.mei does not exist"),
    "script link": (lambda c, e: c["links"][0].update(url="javascript:alert(1)"), "links[0].url: expected an http(s) URL"),
    "label": (lambda c, e: c["labels"].update(bars=3), "labels.bars: expected text"),
    "unknown label": (lambda c, e: c["labels"].update(movement="x"), "labels.movement: unknown key"),
    "ref_base": (lambda c, e: c.update(ref_base="https://example.org/mei"), "ref_base: expected a URL ending"),
    "type": (lambda c, e: c["facsimile"].update(type="iiif"), "facsimile.type: expected one of pdf"),
    "url and copy": (lambda c, e: c["facsimile"]["images"].update(url="https://example.org/"), "give either url"),
    "http images": (lambda c, e: c["facsimile"]["images"].update(copy=False, url="http://example.org/"), "expected an https URL"),
    "no source": (lambda c, e: c["facsimile"].update(pdf=False, images=None), "give pdf, images or both"),
    "image hash": (lambda c, e: Image.new("RGB", (320, 480), "white").save(e / "facsimiles/print/page-0002.png"),
                   "page-0002.png differs from its sha256"),
    "image not in pages.json": (lambda c, e: _rename_page(e), "shows 'page-0001.png', which is not in pages.json"),
    "page size": (lambda c, e: _resize_page(e), "is 320×480, its page image 640×960"),
    "dangling zone": (lambda c, e: _dangling(e), "@facs points at no zone or surface: zone-gone"),
}


def _rename_page(example: Path) -> None:
    path = example / "facsimiles/print/pages.json"
    data = read_json(path)
    data["pages"][0]["image"] = "renamed.png"
    write_json(path, data)


def _resize_page(example: Path) -> None:
    path = example / "facsimiles/print/pages.json"
    data = read_json(path)
    data["pages"][0].update(width=640, height=960)
    write_json(path, data)


def _dangling(example: Path) -> None:
    path = example / "mei/example.mei"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('facs="#zone-print-p0001-001"', 'facs="#zone-gone"', 1), encoding="utf-8")


@pytest.mark.parametrize("name", MUTATIONS)
def test_every_problem_is_reported_and_nothing_is_written(example, name):
    out = example / "public"
    we.build_site(site_config(example), out)
    before = sorted(p.relative_to(out) for p in out.rglob("*"))
    config = read_json(site_config(example))
    mutate, message = MUTATIONS[name]
    mutate(config, example)
    path = example / "site.json"
    write_json(path, config)
    with pytest.raises(we.SiteConfigError) as error:
        we.build_site(path, out)
    assert any(message in problem for problem in error.value.problems), error.value.problems
    assert sorted(p.relative_to(out) for p in out.rglob("*")) == before


def test_all_problems_come_in_one_report(example):
    config = read_json(site_config(example))
    config["storage_prefix"] = "Bad"
    config["works"][0]["mei"] = "nowhere.mei"
    with pytest.raises(we.SiteConfigError) as error:
        we.build_site(config, example / "public", base_dir=example)
    assert len(error.value.problems) == 2 and str(error.value).startswith("2 problems in the site config:")


def test_output_folder_rules(example):
    config = site_config(example)
    repo = example / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(we.SiteConfigError, match="inside the git repository"):
        we.build_site(config, repo / "docs")
    assert we.build_site(config, repo / "_site")["files"]
    with pytest.raises(we.SiteConfigError, match="contains the input"):
        we.build_site(config, example)
    with pytest.raises(we.SiteConfigError, match="contains the input"):
        we.build_site(config, example / "mei")
    foreign = example / "notes"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("not a build")
    with pytest.raises(we.SiteConfigError, match="was not built by camat-build-site"):
        we.build_site(config, foreign)
    assert (foreign / "keep.txt").read_text() == "not a build"
    (example / "file").write_text("x")
    with pytest.raises(we.SiteConfigError, match="is not a folder"):
        we.build_site(config, example / "file")
    empty = example / "empty"
    empty.mkdir()
    assert we.build_site(config, empty)["files"]


def test_hosted_images_pdf_only_and_score_only_sites(example):
    hosted = {"type": "pdf", "pages": "facsimiles/print/pages.json",
              "images": {"url": "https://example.org/print", "button": "Show the page images"}}
    report = we.build_site(site_config(example, facsimile=hosted), example / "hosted")
    assert not [f for f in report["files"] if f.endswith(".png")]
    index = (example / "hosted/index.html").read_text(encoding="utf-8")
    assert runtime_config(index)["facsimile"]["images"] == {"url": "https://example.org/print/", "confirm": False}
    assert "Show the page images" in index and 'class="warning">' not in index and 'id="pdf-input"' not in index
    assert "pdf.js" not in index

    pdf_only = {"type": "pdf", "pages": "facsimiles/print/pages.json", "pdf": True}
    we.build_site(site_config(example, facsimile=pdf_only), example / "pdf-only")
    index = (example / "pdf-only/index.html").read_text(encoding="utf-8")
    assert 'id="scan-show"' not in index and "<p>Open your own copy of the PDF. It is read" in index

    report = we.build_site(site_config(example, facsimile=None, links=[], subtitle=""), example / "score-only")
    index = (example / "score-only/index.html").read_text(encoding="utf-8")
    assert '<main class="panes single">' in index and 'id="facs"' not in index
    assert runtime_config(index)["facsimile"] is None
    assert report["works"][0]["facsimile_pages"] == 2


def test_dict_config_uses_base_dir(example):
    config = read_json(site_config(example))
    with pytest.raises(we.SiteConfigError, match="does not exist"):
        we.build_site(config, example / "public", base_dir=example / "elsewhere")
    assert we.build_site(config, example / "public", base_dir=example)["works"][0]["measures"] == 5


def test_cli(example, capsys):
    assert we.main([str(site_config(example)), str(example / "public")]) == 0
    output = capsys.readouterr().out
    assert "1 work, 5 bars (5 with a zone), 11 files" in output and "python -m http.server -d" in output
    assert we.main([str(site_config(example, storage_prefix="")), str(example / "public")]) == 1
    error = capsys.readouterr().err
    assert error.startswith("camat-build-site: 1 problem in the site config:") and "storage_prefix" in error
    assert we.main([str(example / "missing.json"), str(example / "public")]) == 1
    assert "cannot read the site config" in capsys.readouterr().err


def test_template_files_are_package_data_and_the_cli_is_declared():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    globs = project["tool"]["setuptools"]["package-data"]["camat"]
    shipped = sorted(p.name for p in TEMPLATE.iterdir() if p.is_file())
    assert shipped == sorted(we.TEMPLATE_FILES)
    for name in shipped:
        assert any(Path("web_edition_template", name).match(glob) for glob in globs), name
    assert project["project"]["scripts"]["camat-build-site"] == "camat.web_edition:main"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required")
@pytest.mark.parametrize("name", ["viewer.js", "facsimile-pdf.js"])
def test_viewer_modules_parse(name, tmp_path):
    # node --check reads .mjs as an ES module, as the browser does.
    module = tmp_path / (Path(name).stem + ".mjs")
    shutil.copyfile(TEMPLATE / name, module)
    result = subprocess.run(["node", "--check", str(module)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
