"""PDF workflow contracts, using redistributable generated pixels and scores."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

import camat.pdf_facsimile as pf

M = "{http://www.music-encoding.org/ns/mei}"
ID = "{http://www.w3.org/XML/1998/namespace}id"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture(tmp_path: Path, scopes: list[dict], *, boxes: bool = True) -> Path:
    folder = tmp_path / "facsimiles" / "print"
    folder.mkdir(parents=True)
    pages = []
    for number, scope in enumerate(scopes, 1):
        image = folder / f"page-{number:04d}.png"
        Image.new("RGB", (320, 480), (250, 250, 250)).save(image)
        page = {"page_id": f"print-p{number:04d}", "pdf_page_number": number,
                "image": image.name, "width": 320, "height": 480, "sha256": sha(image),
                "printed_page": str(number + 2), "role": "music", **scope}
        pages.append(page)
        if boxes and page["role"] == "music":
            measures = []
            for system_number, system in enumerate(page["systems"]):
                labels = system["measures"] if isinstance(system, dict) else system
                for index, _ in enumerate(labels):
                    measures.append({"ulx": 10 + index * 50, "uly": 20 + system_number * 100,
                                     "lrx": 55 + index * 50, "lry": 80 + system_number * 100})
            # Deliberately reverse detector order: region order is geometric.
            write_json(folder / "boxes" / f"{page['page_id']}.json", {"measures": measures[::-1]})
    path = folder / "pages.json"
    write_json(path, {"schema_version": 1, "source_id": "print", "pdf": "print.pdf", "pdf_sha256": "frozen",
                      "page_count": len(pages), "dpi": 300, "renderer": "test renderer",
                      "coordinate_system": "image pixels; origin top-left; x right, y down", "pages": pages})
    return path


def mei(tmp_path: Path, movements: list[tuple[str, list[str | int]]], *, extra: str = "",
        measure_facs: str = "", system_defs: bool = False) -> Path:
    path = tmp_path / "input" / "score.mei"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = []
    for movement, labels in movements:
        lines = [f'      <mdiv n="{movement}">', '        <score><section>',
                 f'          <pb xml:id="old-pb-{movement}" />']
        for index, label in enumerate(labels):
            if system_defs and index == 1:
                lines.extend(['          <sb xml:id="old-sb" />',
                              '          <scoreDef xml:id="change"><staffGrp /></scoreDef>'])
            attrs = f' facs="{measure_facs}"' if measure_facs else ""
            lines.extend([f'          <measure xml:id="m-{movement}-{index}" n="{label}"{attrs}>',
                          '            <!-- keep this score comment -->',
                          '            <?keep notation?>',
                          '            <staff n="1"><layer><note pname="c" oct="4" dur="4" /></layer></staff>',
                          '          </measure>'])
        lines.extend(['        </section></score>', '      </mdiv>'])
        content.extend(lines)
    prolog = ('<?xml version="1.0" encoding="UTF-8"?>\n'
              '<?xml-model href="mei.rng" schematypens="http://relaxng.org/ns/structure/1.0"?>\n'
              '<!DOCTYPE mei [<!ENTITY label "Source">]>\n'
              '<!-- prolog contains <mei> as plain text -->\n')
    path.write_text(prolog + '<mei xmlns="http://www.music-encoding.org/ns/mei" '
                    'xmlns:xlink="http://www.w3.org/1999/xlink">\n'
                    '  <meiHead><ptr xlink:href="source" /></meiHead>\n'
                    f'  <music>\n{extra}'
                    '    <body>\n' + '\n'.join(content) + '\n    </body>\n  </music>\n</mei>\n'
                    '<!-- keep the epilog -->\n', encoding="utf-8")
    return path


def body_without_facs(path: Path) -> str:
    text = path.read_text()
    body = text[text.index('<body>'):text.index('</body>') + len('</body>')]
    return re.sub(r' facs="[^"]*"', '', body)


def test_movement_restart_midpage_and_nonmusic_pages(tmp_path):
    pages = fixture(tmp_path, [
        {"role": "cover"}, {"role": "blank", "printed_page": None},
        {"mdiv": 1, "systems": [[1, 2], {"mdiv": 2, "measures": [0, 1]}]},
        {"role": "advertisement"},
        {"systems": [{"mdiv": 2, "measures": [2]}], "printed_page": "iv"},
    ])
    data = read_json(pages)
    data["pages"].reverse()
    write_json(pages, data)
    records = pf.detect_measure_boxes(str(pages))
    assert [r["page_id"] for r in records] == ["print-p0003", "print-p0005"]
    assert all(r["source"] == "manual" and not r["uploaded"] for r in records)
    alignment = pf.build_measure_alignment(str(pages))
    links = read_json(alignment)["regions"]
    assert [(r["mdiv"], r["measure_n"], r["system"]) for r in links] == [
        ("1", "1", 1), ("1", "2", 1), ("2", "0", 2), ("2", "1", 2), ("2", "2", 1)]
    source = mei(tmp_path, [("1", [1, 2]), ("2", [0, 1, 2])])
    out = tmp_path / "elsewhere" / "out.mei"
    report = pf.integrate_pdf_facsimile(str(source), str(pages), str(alignment), str(out), source_ref="source-record")
    assert report["mdivs"] == ["1", "2"]
    assert report["surfaces"] == 2 and report["zones"] == 5 and report["measures_linked"] == 5
    assert report["pb_linked"] == 1 and report["pb_not_at_page_start"] == ["old-pb-2"]
    assert report["unreviewed_pages"] == ["print-p0003", "print-p0005"]
    root = ET.parse(out).getroot()
    assert root.find(f'.//{M}facsimile').get("decls") == "#source-record"
    for graphic in root.iter(M + "graphic"):
        assert not Path(graphic.get("target")).is_absolute()
        assert (out.parent / graphic.get("target")).resolve() == (pages.parent / Path(graphic.get("target")).name).resolve()
    assert body_without_facs(source) == body_without_facs(out)
    report = pf.write_page_breaks(str(out), str(pages), str(out))
    assert (report["pb"], report["sb"], report["removed"]) == (2, 1, 2)
    root = ET.parse(out).getroot()
    second = root.findall(f'.//{M}mdiv')[1]
    assert next(e for e in second.iter() if e.tag in {M + "pb", M + "sb"}).tag == M + "sb"
    assert root.find(f'.//{M}pb[@n="iv"]') is not None
    assert root.find(f'.//{M}surface').attrib == {
        ID: "surface-print-p0003", "n": "5", "ulx": "0", "uly": "0", "lrx": "319", "lry": "479"}


@pytest.mark.parametrize("encoded", [[1, 2, 3], [1, 2, 2, 3]])
def test_split_measure_pairing_and_idempotence(tmp_path, encoded):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1, 2], [2, 3]], "printed_page": None}])
    alignment = pf.build_measure_alignment(pages)
    assert [r["occurrence"] for r in read_json(alignment)["regions"]] == [1, 1, 2, 1]
    source = mei(tmp_path, [("1", encoded)], system_defs=True)
    out = tmp_path / "out" / "score.mei"
    report = pf.integrate_pdf_facsimile(source, pages, alignment, out)
    assert report["split_measures"] == (1 if len(encoded) == 3 else 0)
    twos = [m for m in ET.parse(out).iter(M + "measure") if m.get("n") == "2"]
    assert [m.get("facs").split() for m in twos] == (
        [["#zone-print-p0001-002", "#zone-print-p0001-003"]] if len(encoded) == 3 else
        [["#zone-print-p0001-002"], ["#zone-print-p0001-003"]])
    report = pf.write_page_breaks(out, pages, out)
    assert report["pb"] == 1
    assert report["sb"] == (0 if len(encoded) == 3 else 1)
    assert len(report["split_system_starts"]) == (1 if len(encoded) == 3 else 0)
    assert not report["pb_without_surface"]
    pb = ET.parse(out).getroot().find(f'.//{M}pb')
    assert pb.get("n") is None
    first = out.read_bytes()
    pf.integrate_pdf_facsimile(out, pages, alignment, out)
    pf.write_page_breaks(out, pages, out)
    assert out.read_bytes() == first
    assert b'<?xml-model href="mei.rng"' in first
    assert b'<!DOCTYPE mei [<!ENTITY label "Source">]>' in first
    assert b'<!-- prolog contains <mei> as plain text -->' in first
    assert b'<!-- keep this score comment -->' in first
    assert b'<?keep notation?>' in first
    assert b'xlink:href="source"' in first and b'xmlns:xlink=' in first
    assert first.endswith(b'<!-- keep the epilog -->\n')


def test_other_facsimile_and_tokens_survive_and_zone_ids_are_global(tmp_path):
    pages = fixture(tmp_path, [{"systems": [{"mdiv": 1, "measures": [1]}, {"mdiv": 2, "measures": [1]}]}])
    alignment = pf.build_measure_alignment(pages)
    extra = ('    <facsimile xml:id="iiif"><surface xml:id="iiif-surface">'
             '<graphic target="https://example.test/iiif" />'
             '<zone xml:id="iiif-zone" type="measure" ulx="0" uly="0" lrx="10" lry="10" />'
             '</surface></facsimile>\n')
    source = mei(tmp_path, [("2", [1])], extra=extra, measure_facs="#iiif-zone", system_defs=False)
    out = tmp_path / "output.mei"
    report = pf.integrate_pdf_facsimile(source, pages, alignment, out)
    assert report["other_facsimiles"] == 1 and report["zones"] == 1
    assert not report["pb_linked"]
    root = ET.parse(out).getroot()
    assert root.find(f'.//{M}measure').get("facs") == "#iiif-zone #zone-print-p0001-002"
    before_iiif = ET.tostring(root.find(f'.//{M}facsimile[@{ID}="iiif"]'))
    # Remove only references belonging to the replaced PDF, throughout the file.
    head = root.find(M + "meiHead")
    ET.SubElement(head, M + "ptr", {"facs": "#graphic-print-p0001 #iiif-zone"})
    root.find(M + "music").find(M + "body").set("facs", "#surface-print-p0001")
    # Keep the prolog by editing the text, rather than using this test tree to write.
    text = out.read_text().replace('</meiHead>', '<ptr facs="#graphic-print-p0001 #iiif-zone" /></meiHead>')
    text = text.replace('<body>', '<body facs="#surface-print-p0001">')
    out.write_text(text)
    pf.integrate_pdf_facsimile(out, pages, alignment, out)
    root = ET.parse(out).getroot()
    assert root.find(f'.//{M}body').get("facs") is None
    assert root.find(M + "meiHead")[-1].get("facs") == "#iiif-zone"
    assert ET.tostring(root.find(f'.//{M}facsimile[@{ID}="iiif"]')) == before_iiif
    report = pf.write_page_breaks(out, pages, out)
    assert (report["pb"], report["sb"]) == (0, 1)
    first = out.read_bytes()
    pf.integrate_pdf_facsimile(out, pages, alignment, out)
    pf.write_page_breaks(out, pages, out)
    assert out.read_bytes() == first


def test_all_system_count_failures_reported_and_no_write(tmp_path):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}, {"mdiv": 1, "systems": [[2, 3]]},
                               {"mdiv": 1, "systems": [[4, 5]]}])
    for number, delta in [(2, 1), (3, -1)]:
        path = pages.parent / "boxes" / f"print-p{number:04d}.json"
        payload = read_json(path)
        if delta > 0:
            payload["measures"].append({"ulx": 115, "uly": 20, "lrx": 155, "lry": 80})
        else:
            payload["measures"].pop()
        write_json(path, payload)
    with pytest.raises(ValueError) as error:
        pf.build_measure_alignment(pages)
    assert all(s in str(error.value) for s in ("print-p0002", "print-p0003", "PDF page 2", "PDF page 3",
                                             "printed page 4", "actual [3], expected [2]", "actual [1], expected [2]"))
    assert not (pages.parent / "alignment.json").exists()
    existing = pages.parent / "alignment.json"
    existing.write_bytes(b'keep existing reviewed alignment')
    with pytest.raises(ValueError):
        pf.build_measure_alignment(pages)
    assert existing.read_bytes() == b'keep existing reviewed alignment'


def test_pb_uses_next_measure_across_movement_boundary(tmp_path):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}, {"mdiv": 2, "systems": [[1]]}])
    alignment = pf.build_measure_alignment(pages)
    source = mei(tmp_path, [("1", [1]), ("2", [1])])
    source.write_text(source.read_text().replace(
        '        </section></score>',
        '          <pb xml:id="transition" />\n        </section></score>', 1))
    report = pf.integrate_pdf_facsimile(source, pages, alignment, source)
    assert report["pb_linked"] == 3 and not report["pb_not_at_page_start"]
    assert ET.parse(source).getroot().find(f'.//{M}pb[@{ID}="transition"]').get("facs") == "#surface-print-p0002"


@pytest.mark.parametrize("encoded", [[1, 2, 3], [1, 2, 2, 3]])
def test_split_at_page_boundary(tmp_path, encoded):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1, 2]]}, {"mdiv": 1, "systems": [[2, 3]]}])
    alignment = pf.build_measure_alignment(pages)
    source = mei(tmp_path, [("1", encoded)])
    pf.integrate_pdf_facsimile(source, pages, alignment, source)
    report = pf.write_page_breaks(source, pages, source)
    assert report["pb"] == (1 if len(encoded) == 3 else 2)
    assert len(report["split_system_starts"]) == (1 if len(encoded) == 3 else 0)
    before = source.read_bytes()
    pf.integrate_pdf_facsimile(source, pages, alignment, source)
    pf.write_page_breaks(source, pages, source)
    assert source.read_bytes() == before


@pytest.mark.parametrize("bad", [
    {"role": "musci", "mdiv": 1, "systems": [[1]]},
    {"role": "music", "systems": [[1]]},
    {"role": "music", "mdiv": 1, "systems": []},
    {"role": "music", "mdiv": 1, "systems": [[]]},
    {"role": "music", "systems": [{"mdiv": 1, "measures": []}]},
    {"role": "music", "mdiv": 1, "systems": [[None]]},
    {"role": "music", "mdiv": True, "systems": [[1]]},
])
def test_page_review_validation_shared_by_all_operations(tmp_path, bad):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}])
    data = read_json(pages)
    page = data["pages"][0]
    page.pop("mdiv")
    page.pop("systems")
    page.update(bad)
    write_json(pages, data)
    for operation in (pf.detect_measure_boxes, pf.build_measure_alignment,
                      lambda p: pf.integrate_pdf_facsimile("missing.mei", p, "missing.json", "out.mei"),
                      lambda p: pf.write_page_breaks("missing.mei", p, "out.mei")):
        with pytest.raises(ValueError, match="print-p0001"):
            operation(pages)


def test_unreviewed_manifest_requires_step_three(tmp_path):
    pages = fixture(tmp_path, [{"role": "blank"}], boxes=False)
    data = read_json(pages)
    del data["pages"][0]["role"]
    write_json(pages, data)
    with pytest.raises(ValueError, match=r"print-p0001.*review pages.json \(step 3\)"):
        pf.detect_measure_boxes(pages)


def test_detector_upload_optin_metadata_cache_and_manual_edits(tmp_path, monkeypatch):
    pages = fixture(tmp_path, [{"role": "cover"}, {"mdiv": 1, "systems": [[1]]}], boxes=False)
    calls = []
    payload = {"measures": [{"ulx": 0.1, "uly": 0, "lrx": 320, "lry": 480}], "extra": "raw response"}

    def upload(path, endpoint, timeout, **kwargs):
        calls.append((path, endpoint, timeout, kwargs))
        return deepcopy(payload)

    monkeypatch.setattr(pf, "upload_image", upload)
    with pytest.raises(FileNotFoundError, match="print-p0002.*allow_upload=True"):
        pf.detect_measure_boxes(pages)
    assert not calls
    records = pf.detect_measure_boxes(pages, allow_upload=True, detector_url="https://test/upload", timeout=7, retries=3)
    assert calls == [(pages.parent / "page-0002.png", "https://test/upload", 7, {"retries": 3, "retry_delay": 2})]
    path = pages.parent / "boxes" / "print-p0002.json"
    assert path.read_text() == json.dumps(payload, indent=2) + "\n"
    run = read_json(path.with_suffix(".run.json"))
    assert set(run) == {"endpoint", "created_at", "image", "image_sha256", "response_sha256", "measures"}
    assert run["image"] == "page-0002.png" and run["response_sha256"] == sha(path) and run["measures"] == 1
    assert run["created_at"].endswith("+00:00")
    assert records == [{"page_id": "print-p0002", "boxes": str(path), "source": "detector", "measures": 1, "uploaded": True}]
    pf.detect_measure_boxes(pages)
    assert len(calls) == 1
    payload["measures"][0]["ulx"] = 2
    write_json(path, payload)
    assert pf.detect_measure_boxes(pages)[0]["source"] == "detector-edited"
    path.with_suffix(".run.json").unlink()
    assert pf.detect_measure_boxes(pages)[0]["source"] == "manual"


@pytest.mark.parametrize("failure", ["network", "shape"])
def test_failed_upload_writes_nothing(tmp_path, monkeypatch, failure):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}], boxes=False)

    def upload(*args, **kwargs):
        if failure == "network":
            raise RuntimeError("offline")
        return {"measures": [{"ulx": "bad"}]}

    monkeypatch.setattr(pf, "upload_image", upload)
    with pytest.raises((RuntimeError, ValueError)):
        pf.detect_measure_boxes(pages, allow_upload=True)
    assert not (pages.parent / "boxes").exists()


@pytest.mark.parametrize("change", ["image", "run", "shape"])
def test_detector_hash_and_shape_gates_precede_any_upload(tmp_path, monkeypatch, change):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}, {"mdiv": 1, "systems": [[2]]}])
    (pages.parent / "boxes" / "print-p0001.json").unlink()
    path = pages.parent / "boxes" / "print-p0002.json"
    if change == "image":
        (pages.parent / "page-0002.png").write_bytes(b"different pixels")
    elif change == "run":
        write_json(path.with_suffix(".run.json"), {"image_sha256": "other pixels"})
    else:
        write_json(path, {"measures": [{"ulx": float("nan"), "uly": 0, "lrx": 100, "lry": 100}]})
    calls = []
    monkeypatch.setattr(pf, "upload_image", lambda *a, **k: calls.append(a))
    with pytest.raises(ValueError, match="print-p0002"):
        pf.detect_measure_boxes(pages, allow_upload=True)
    assert not calls


def test_alignment_reviews_determinism_relative_paths_and_overlays(tmp_path, monkeypatch):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1], [1, 2]]}])
    path = tmp_path / "review" / "alignment.json"
    assert pf.build_measure_alignment(str(pages), output=str(path)) == path
    data = read_json(path)
    assert set(data) == {"schema_version", "source_id", "pages_json", "pages", "regions", "review"}
    assert (path.parent / data["pages_json"]).resolve() == pages.resolve()
    assert set(data["pages"][0]) == {"page_id", "image", "image_sha256", "boxes", "boxes_sha256", "systems"}
    assert set(data["regions"][0]) == {"mdiv", "measure_n", "occurrence", "page_id", "system", "bbox",
                                      "image_sha256", "boxes_sha256", "box_index"}
    reviewed = data["review"]["print-p0001"]
    reviewed.update(status="approved", reviewer="Editor", date="2026-10-12", notes="Checked", custom="retain verbatim")
    write_json(path, data)
    before = path.read_bytes()
    pf.build_measure_alignment(pages, output=path)
    assert path.read_bytes() == before
    source = mei(tmp_path, [("1", [1, 2])])
    report = pf.integrate_pdf_facsimile(source, pages, path, tmp_path / "approved.mei")
    assert not report["unreviewed_pages"]
    captured = []
    from PIL import ImageDraw
    original = ImageDraw.ImageDraw.text

    def capture(self, xy, text, *args, **kwargs):
        captured.append(text)
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    outputs = pf.draw_alignment_overlays(str(path))
    assert outputs == [path.parent / "overlays" / "print-p0001.png"]
    assert "1/1 (2)" in captured
    with Image.open(outputs[0]) as image:
        assert image.size == (320, 480)
    boxes = pages.parent / "boxes" / "print-p0001.json"
    payload = read_json(boxes)
    payload["measures"][0]["ulx"] += 1
    write_json(boxes, payload)
    with pytest.warns(UserWarning, match="print-p0001.*boxes changed"):
        pf.build_measure_alignment(pages, output=path)
    assert read_json(path)["review"]["print-p0001"]["reset_reason"] == "boxes changed"
    before = path.read_bytes()
    pf.build_measure_alignment(pages, output=path)
    assert path.read_bytes() == before
    image = pages.parent / "page-0001.png"
    Image.new("RGB", (320, 480), "white").save(image)
    with pytest.raises(ValueError, match="print-p0001.*image hash"):
        pf.draw_alignment_overlays(path, tmp_path / "bad-overlays")
    assert not (tmp_path / "bad-overlays").exists()
    data = read_json(pages)
    data["pages"][0]["sha256"] = sha(image)
    write_json(pages, data)
    with pytest.warns(UserWarning, match="image changed"):
        pf.build_measure_alignment(pages, output=path)
    assert read_json(path)["review"]["print-p0001"]["reset_reason"] == "image changed"


@pytest.mark.parametrize("bbox,valid", [([0, 0, 320, 480], True), ([-1, 0, 320, 480], False),
                                       ([0, 0, 321, 480], False), ([4, 4, 4, 10], False),
                                       ([0, 10, 20, 0], False)])
def test_box_geometry_viewer_rule(tmp_path, bbox, valid):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}])
    write_json(pages.parent / "boxes" / "print-p0001.json", {"measures": [dict(zip(pf._COORDS, bbox))]})
    if valid:
        alignment = pf.build_measure_alignment(pages)
        assert read_json(alignment)["regions"][0]["bbox"] == bbox
    else:
        with pytest.raises(ValueError, match="print-p0001.*box"):
            pf.build_measure_alignment(pages)


def test_running_median_grouping_and_rounding(tmp_path):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1, 2, 3], [4]]}])
    boxes = [{"ulx": 110.6, "uly": 100.2, "lrx": 150.6, "lry": 200.2},
             {"ulx": 10.2, "uly": 40.2, "lrx": 50.2, "lry": 140.2},
             {"ulx": 60.2, "uly": 80.2, "lrx": 100.2, "lry": 180.2},
             {"ulx": 10, "uly": 300, "lrx": 50, "lry": 400}]
    write_json(pages.parent / "boxes" / "print-p0001.json", {"measures": boxes})
    regions = read_json(pf.build_measure_alignment(pages))["regions"]
    assert [r["box_index"] for r in regions] == [1, 2, 0, 3]
    assert regions[2]["bbox"] == [111, 100, 151, 200]


@pytest.mark.parametrize("change", ["image", "boxes"])
def test_stale_alignment_refused_before_writing(tmp_path, change):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}])
    alignment = pf.build_measure_alignment(pages)
    source = mei(tmp_path, [("1", [1])])
    target = pages.parent / ("page-0001.png" if change == "image" else "boxes/print-p0001.json")
    target.write_bytes(b"changed")
    before = source.read_bytes()
    with pytest.raises(ValueError, match="print-p0001.*re-run build_measure_alignment"):
        pf.integrate_pdf_facsimile(source, pages, alignment, source)
    assert source.read_bytes() == before


@pytest.mark.parametrize("labels,match", [([1, 3], "(?=.*1/2.*no MEI measure)(?=.*1/3.*no region)"),
                                         ([1, 1, 2], "1/1: 2 MEI measures vs 1 regions")])
def test_bidirectional_and_pairing_gates(tmp_path, labels, match):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1, 2]]}])
    alignment = pf.build_measure_alignment(pages)
    source = mei(tmp_path, [("1", labels)])
    before = source.read_bytes()
    for operation in (lambda: pf.integrate_pdf_facsimile(source, pages, alignment, source),
                      lambda: pf.write_page_breaks(source, pages, source)):
        with pytest.raises(ValueError, match=match):
            operation()
        assert source.read_bytes() == before


def test_no_linked_movement_and_missing_measure_number(tmp_path):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}])
    alignment = pf.build_measure_alignment(pages)
    source = mei(tmp_path, [("2", [1])])
    with pytest.raises(ValueError, match=r"MEI mdiv/@n \['2'\].*facsimile mdivs \['1'\]"):
        pf.integrate_pdf_facsimile(source, pages, alignment, source)
    source = mei(tmp_path, [("1", [1])])
    source.write_text(source.read_text().replace(' n="1">\n            <!--', '>\n            <!--'))
    with pytest.raises(ValueError, match=r"mdiv 1.*lacks @n"):
        pf.integrate_pdf_facsimile(source, pages, alignment, source)


def test_nearest_mdiv_and_unlinked_score_unchanged(tmp_path):
    pages = fixture(tmp_path, [{"mdiv": 2, "systems": [[1]]}])
    alignment = pf.build_measure_alignment(pages)
    source = mei(tmp_path, [("1", [1]), ("2", [1]), ("3", [99])])
    text = source.read_text().replace('<mdiv n="2">', '<mdiv n="outer"><mdiv n="2">')
    text = text.replace('      <mdiv n="3">', '      </mdiv><mdiv n="3">')
    source.write_text(text)
    report = pf.integrate_pdf_facsimile(source, pages, alignment, source)
    assert report["mdivs"] == ["2"] and report["measures_linked"] == 1
    root = ET.parse(source).getroot()
    assert [m.get("facs") for m in root.iter(M + "measure")] == [None, "#zone-print-p0001-001", None]
    before_third = ET.tostring(root.find(f'.//{M}mdiv[@n="3"]'))
    pf.write_page_breaks(source, pages, source)
    assert ET.tostring(ET.parse(source).getroot().find(f'.//{M}mdiv[@n="3"]')) == before_third


def test_break_sequence_divergence_leaves_file_untouched(tmp_path):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[2], [1]]}])
    source = mei(tmp_path, [("1", [1, 2])])
    before = source.read_bytes()
    with pytest.raises(ValueError, match="diverges at position 1.*pages.json 1/2.*MEI 1/1"):
        pf.write_page_breaks(source, pages, source)
    assert source.read_bytes() == before


def test_break_placement_missing_surface_and_whitespace(tmp_path):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1], [2]]}])
    source = mei(tmp_path, [("1", [1, 2])], system_defs=True)
    report = pf.write_page_breaks(source, pages, source)
    assert report["pb_without_surface"] == ["print-p0001"]
    root = ET.parse(source).getroot()
    section = root.find(f'.//{M}section')
    assert [e.tag for e in section] == [M + "pb", M + "measure", M + "sb", M + "scoreDef", M + "measure"]
    assert section[0].get("facs") is None
    assert section[2].get(ID) == "sb-print-p0001-s02"
    assert not re.search(r"\n *\n", source.read_text())
    first = source.read_bytes()
    pf.write_page_breaks(source, pages, source)
    assert source.read_bytes() == first


def test_pages_json_relabelled_after_alignment_is_refused(tmp_path):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1, 2]]}])
    alignment = pf.build_measure_alignment(pages)
    manifest = read_json(pages)
    manifest["pages"][0]["systems"] = [[2, 1]]
    write_json(pages, manifest)
    source = mei(tmp_path, [("1", [1, 2])])
    before = source.read_bytes()
    with pytest.raises(ValueError, match="pages.json systems changed.*re-run build_measure_alignment"):
        pf.integrate_pdf_facsimile(source, pages, alignment, source)
    assert source.read_bytes() == before


def test_removing_a_trailing_break_keeps_closing_indentation(tmp_path):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}])
    source = mei(tmp_path, [("1", [1])])
    closing = "          </measure>\n        </section>"
    text = source.read_text()
    assert text.count(closing) == 1
    source.write_text(text.replace(closing, '          </measure>\n          <sb xml:id="trailing" />\n        </section>'))
    pf.write_page_breaks(source, pages, source)
    assert closing in source.read_text()


@pytest.mark.parametrize("operation", ["integrate", "breaks"])
def test_id_collisions_are_atomic(tmp_path, operation):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}])
    alignment = pf.build_measure_alignment(pages)
    source = mei(tmp_path, [("1", [1])])
    ident = "zone-print-p0001-001" if operation == "integrate" else "pb-print-p0001"
    source.write_text(source.read_text().replace('<ptr xlink:', f'<ptr xml:id="{ident}" xlink:'))
    before = source.read_bytes()
    with pytest.raises(ValueError, match="xml:id collision.*" + ident):
        if operation == "integrate":
            pf.integrate_pdf_facsimile(source, pages, alignment, source)
        else:
            pf.write_page_breaks(source, pages, source)
    assert source.read_bytes() == before


HUMXML = ('<extMeta>\n'
          '      <frames xmlns="http://www.humdrum.org/ns/humxml" note=\'a &gt; b\'>\n'
          '        <frame n="1"><token>4c</token><empty/></frame>\n'
          '      </frames>\n'
          '    </extMeta>')


def foreign_mei(tmp_path: Path, head: str, root_declarations: str = "") -> Path:
    source = mei(tmp_path, [("1", [1, 2])])
    text = source.read_text()
    old_head, old_root = '<ptr xlink:href="source" />', 'xmlns:xlink="http://www.w3.org/1999/xlink">'
    assert text.count(old_head) == text.count(old_root) == 1
    source.write_text(text.replace(old_head, head).replace(old_root, old_root[:-1] + root_declarations + ">"))
    return source


def test_foreign_xml_is_kept_byte_for_byte_without_global_side_effects(tmp_path):
    # Verovio's Humdrum import embeds humxml and MADS blocks with their own default namespace.
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1, 2]]}])
    alignment = pf.build_measure_alignment(pages)
    source = foreign_mei(tmp_path, '<ptr xlink:href="source" />' + HUMXML.replace(
        '    </extMeta>', '      <svg:svg width="1"><svg:g/></svg:svg>\n    </extMeta>'),
        '\n     xmlns:svg="http://www.w3.org/2000/svg"')
    registry = [ET.tostring(ET.Element(uri + "x")) for uri in (M, "{http://www.humdrum.org/ns/humxml}")]
    out = tmp_path / "out.mei"
    pf.integrate_pdf_facsimile(source, pages, alignment, out)
    pf.write_page_breaks(out, pages, out)
    heads = [(text := path.read_text())[:text.index("</meiHead>")] for path in (out, source)]
    assert heads[0] == heads[1]
    root = ET.parse(out).getroot()
    assert root.tag == M + "mei" and root.find(f"{M}music/{M}facsimile") is not None
    assert body_without_facs(source) != body_without_facs(out)  # breaks were rewritten
    assert [ET.tostring(ET.Element(uri + "x")) for uri in (M, "{http://www.humdrum.org/ns/humxml}")] == registry


def test_namespace_declared_below_the_root_moves_to_the_root(tmp_path):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1, 2]]}])
    alignment = pf.build_measure_alignment(pages)
    source = foreign_mei(tmp_path, '<ptr xmlns:ex="urn:example" ex:role="x" />' + HUMXML)
    out = tmp_path / "out.mei"
    pf.integrate_pdf_facsimile(source, pages, alignment, out)
    text = out.read_text()
    assert HUMXML in text
    assert 'xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:ex="urn:example">' in text
    assert ET.parse(out).getroot().find(f".//{M}ptr").get("{urn:example}role") == "x"


def test_unsplicable_namespaces_fall_back_to_generated_prefixes(tmp_path):
    # ET names an unregistrable prefix ns2, which the root already binds to the island's namespace.
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1, 2]]}])
    alignment = pf.build_measure_alignment(pages)
    source = foreign_mei(tmp_path, '<ptr xlink:href="source" xmlns:ns7="urn:other" ns7:a="1" />'
                         '<extMeta><ns2:block/></extMeta>', ' xmlns:ns2="urn:island"')
    out = tmp_path / "out.mei"
    with pytest.warns(UserWarning, match="generated prefixes"):
        pf.integrate_pdf_facsimile(source, pages, alignment, out)
    root = ET.parse(out).getroot()
    assert root.find(f".//{M}ptr").get("{urn:other}a") == "1"
    assert root.find(f".//{M}extMeta/{{urn:island}}block") is not None


def test_body_gate_prevents_write(tmp_path, monkeypatch):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}])
    alignment = pf.build_measure_alignment(pages)
    source = mei(tmp_path, [("1", [1])])
    before = source.read_bytes()
    original = pf._update_facs

    def corrupt(element, removed_ids, additions):
        original(element, removed_ids, additions)
        if element.tag == M + "measure":
            element.set("n", "corrupted")

    monkeypatch.setattr(pf, "_update_facs", corrupt)
    with pytest.raises(ValueError, match="Body gate failed"):
        pf.integrate_pdf_facsimile(source, pages, alignment, source)
    assert source.read_bytes() == before


def pdf(path: Path, *, rotate: int = 0, pages: int = 2) -> None:
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               f'<< /Type /Pages /Count {pages} /Kids [{" ".join(f"{i + 3} 0 R" for i in range(pages))}] >>'.encode()]
    objects.extend(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 144] /Rotate {rotate} >>'.encode() for _ in range(pages))
    content = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(content)
    content.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        content.extend(f'{offset:010d} 00000 n \n'.encode())
    content.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path.write_bytes(content)


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="Poppler pdftoppm required")
@pytest.mark.parametrize("rotate", [0, 90])
def test_real_render_rotation_manifest_and_review_reuse(tmp_path, rotate):
    source = tmp_path / "original.pdf"
    pdf(source, rotate=rotate)
    target = tmp_path / "fac" / "pages"
    result = pf.render_pdf_pages(str(source), str(target), 72, source_id="print")
    assert set(result) == {"schema_version", "source_id", "pdf", "pdf_sha256", "page_count", "dpi", "renderer",
                           "coordinate_system", "pages"}
    assert result["page_count"] == 2 and result["pdf"] == "../../original.pdf"
    assert result["pdf_sha256"] == sha(source)
    assert result["renderer"].startswith("pdftoppm version ")
    assert "rot:" in (target / "pdfinfo.txt").read_text()
    size = (144, 72) if rotate else (72, 144)
    for number, page in enumerate(result["pages"], 1):
        assert set(page) == {"page_id", "pdf_page_number", "image", "width", "height", "sha256", "printed_page", "role"}
        assert page["page_id"] == f"print-p{number:04d}" and page["image"] == f"page-{number:04d}.png"
        assert (page["width"], page["height"]) == size
        assert page["sha256"] == sha(target / page["image"])
    path = target / "pages.json"
    result["pages"][0].update(role="music", mdiv="1", systems=[["1"]])
    write_json(path, result)
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    assert pf.render_pdf_pages(source, target, 72, source_id="print") == result
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime
    for kwargs, changed in [({"dpi": 144, "source_id": "print"}, "dpi"),
                            ({"dpi": 72, "source_id": "other"}, "source_id")]:
        with pytest.raises(ValueError, match="changed:.*" + changed):
            pf.render_pdf_pages(source, target, **kwargs)
        assert path.read_bytes() == before
    source.write_bytes(source.read_bytes() + b'\n')
    with pytest.raises(ValueError, match="pdf_sha256"):
        pf.render_pdf_pages(source, target, 72, source_id="print")
    assert path.read_bytes() == before


def test_render_input_ids_and_missing_poppler(tmp_path, monkeypatch):
    source = tmp_path / "123 bad.pdf"
    pdf(source)
    with pytest.raises(ValueError, match="source_id="):
        pf.render_pdf_pages(source, tmp_path / "pages")
    for program in ("pdftoppm", "pdfinfo"):
        original = shutil.which
        with monkeypatch.context() as patch:
            patch.setattr(pf.shutil, "which", lambda name: None if name == program else original(name))
            with pytest.raises(RuntimeError, match=program + " is missing"):
                pf.render_pdf_pages(source, tmp_path / "pages", source_id="good")


@pytest.mark.parametrize("failure", ["page count", "PNG", "process"])
def test_render_staging_failure_writes_no_derivatives(tmp_path, monkeypatch, failure):
    source = tmp_path / "source.pdf"
    pdf(source)
    target = tmp_path / "pages"
    monkeypatch.setattr(pf.shutil, "which", lambda name: name)

    def poppler(command):
        if command[:2] == ["pdftoppm", "-v"]:
            return subprocess.CompletedProcess(command, 0, "", "pdftoppm version test\n")
        if command[0] == "pdfinfo":
            return subprocess.CompletedProcess(command, 0, "Pages: 2\n", "")
        if failure == "process":
            raise RuntimeError("pdftoppm failed")
        stage = Path(command[-1]).parent
        (stage / "page-1.png").write_bytes(b'bad PNG')
        if failure == "PNG":
            (stage / "page-2.png").write_bytes(b'bad PNG')
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(pf, "_poppler", poppler)
    with pytest.raises((RuntimeError, ValueError)):
        pf.render_pdf_pages(source, target)
    assert not list(target.iterdir())


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="Poppler pdftoppm required")
def test_render_damaged_cache_and_orphan_images(tmp_path):
    source = tmp_path / "source.pdf"
    pdf(source)
    target = tmp_path / "pages"
    pf.render_pdf_pages(source, target, 72)
    path = target / "pages.json"
    data = read_json(path)
    before = path.read_bytes()
    data["renderer"] = "different renderer"
    write_json(path, data)
    with pytest.raises(ValueError, match="renderer"):
        pf.render_pdf_pages(source, target, 72)
    path.write_bytes(before)
    (target / "page-0001.png").write_bytes(b'corrupt image')
    with pytest.raises(ValueError, match="image hash.*source-p0001"):
        pf.render_pdf_pages(source, target, 72)
    assert path.read_bytes() == before
    path.unlink()
    with pytest.raises(FileExistsError, match="without pages.json"):
        pf.render_pdf_pages(source, target, 72)


def test_cli_workflow_and_error_summary(tmp_path, capsys):
    pages = fixture(tmp_path, [{"mdiv": 1, "systems": [[1]]}])
    source = mei(tmp_path, [("1", [1])])
    assert pf.main(["detect", str(pages), "--timeout", "1"]) == 0
    assert "Verified boxes for 1 pages" in capsys.readouterr().out
    assert pf.main(["align", str(pages), "--no-overlays"]) == 0
    assert not (pages.parent / "overlays").exists()
    assert pf.main(["align", str(pages)]) == 0
    assert (pages.parent / "overlays" / "print-p0001.png").is_file()
    assert pf.main(["integrate", str(source), str(pages), str(pages.parent / "alignment.json"),
                    str(source), "--source-ref", "src"]) == 0
    assert pf.main(["breaks", str(source), str(pages), str(source)]) == 0
    capsys.readouterr()
    assert pf.main(["detect", str(tmp_path / "missing.json")]) == 1
    assert capsys.readouterr().err.startswith("ERROR: ")
