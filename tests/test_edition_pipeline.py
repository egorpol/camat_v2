from __future__ import annotations

import json
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import requests

from camat import (
    IIIF_IMAGE_URL_TEMPLATE,
    build_annotation_tree,
    detect_and_integrate_mei,
    filter_mei_files,
    parse_graphic_from_output_mei,
    parse_page_ranges,
    read_image_size,
    sha256_bytes,
    sha256_file,
)
from camat.check_bsb_page_coverage import compare_to_manifest
from camat.corpus_cleanup import collect_deletions
from camat.facsimile_downloader import (
    download_facsimile_image,
    parse_bsb_viewer_url,
    resolve_iiif_image_url,
    resolve_width_for_stem,
    stage_mei_copy,
)
from camat.fetch_bsb_metadata import localized_text, split_creation
from camat.generate_volume_pages import build_markdown, extract_meta
from camat.run_pipeline import step1_args, step4_args, step5_args


MEI_NS = "http://www.music-encoding.org/ns/mei"


def _write_source_mei(path: Path) -> None:
    path.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>
<?xml-model href="https://music-encoding.org/schema/5.1/mei-CMN.rng"?>
<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1+CMN">
  <meiHead><fileDesc><titleStmt><title>Pipeline fixture</title></titleStmt>
    <pubStmt><p>Test</p></pubStmt></fileDesc></meiHead>
  <music><body><mdiv><score><section>
    <measure xml:id="measure-1" n="1"><staff n="1"><layer n="1" /></staff></measure>
    <measure xml:id="measure-2" n="2"><staff n="1"><layer n="1" /></staff></measure>
  </section></score></mdiv></body></music>
</mei>
''',
        encoding="utf-8",
    )


def _write_annotation_mei(path: Path) -> None:
    tree = build_annotation_tree(
        {
            "measures": [
                {"ulx": 10, "uly": 20, "lrx": 300, "lry": 200},
                {"ulx": 320, "uly": 20, "lrx": 620, "lry": 200},
            ]
        },
        image_name="bsb00000000_00001.jpg",
        image_width=1000,
        image_height=1400,
    )
    ET.indent(tree, space="  ")
    tree.write(path, encoding="UTF-8", xml_declaration=True)


def test_page_filters_and_coverage_comparison() -> None:
    files = [Path(f"bsb00000000_{page:05d}.mei") for page in range(1, 6)]

    assert parse_page_ranges("2-3,5") == [(2, 3), (5, 5)]
    assert filter_mei_files(files, pages="2-", skip_pages="4") == [
        files[1],
        files[2],
        files[4],
    ]

    comparison = compare_to_manifest(
        ["bsb00000000_00001", "bsb00000000_00002"],
        {"bsb00000000_00002", "bsb00000000_00003"},
    )
    assert comparison["missing_vs_manifest"] == ["bsb00000000_00001"]
    assert comparison["extra_vs_manifest"] == ["bsb00000000_00003"]


def test_reused_measure_annotations_integrate_without_network(tmp_path: Path) -> None:
    source = tmp_path / "bsb00000000_00001.mei"
    annotation = tmp_path / "bsb00000000_00001_measure_annotations.xml"
    _write_source_mei(source)
    _write_annotation_mei(annotation)

    returned_annotation, output = detect_and_integrate_mei(
        source,
        image_dir=tmp_path / "img",
        detector_url="https://example.invalid/detector",
        timeout=1,
        retries=0,
        retry_delay=0,
        minimum_measures=1,
        max_measure_mismatch=0,
        annotation_suffix="_measure_annotations.xml",
        output_suffix="_facs_zones",
        reuse_annotations=True,
        overwrite=False,
        graphic_target_mode="iiif",
        iiif_url_template=IIIF_IMAGE_URL_TEMPLATE,
    )

    assert returned_annotation == annotation
    assert output.is_file()
    expected_target = IIIF_IMAGE_URL_TEMPLATE.format(stem=source.stem, width=1000)
    target, width, height = parse_graphic_from_output_mei(output)
    assert (target, width, height) == (expected_target, 1000, 1400)

    root = ET.parse(output).getroot()
    measures = root.findall(f".//{{{MEI_NS}}}body//{{{MEI_NS}}}measure")
    zones = root.findall(f".//{{{MEI_NS}}}facsimile//{{{MEI_NS}}}zone")
    assert len(zones) == 2
    assert all(measure.get("facs", "").startswith("#zone_") for measure in measures)
    assert "<?xml-model" in output.read_text(encoding="utf-8")

    override = "https://example.test/manual-iiif.jpg"
    _, overridden = detect_and_integrate_mei(
        source,
        image_dir=tmp_path / "img",
        detector_url="https://example.invalid/detector",
        timeout=1,
        retries=0,
        retry_delay=0,
        minimum_measures=1,
        max_measure_mismatch=0,
        annotation_suffix="_measure_annotations.xml",
        output_suffix="_facs_zones",
        reuse_annotations=True,
        overwrite=True,
        graphic_target_mode="iiif",
        iiif_url_template=IIIF_IMAGE_URL_TEMPLATE,
        graphic_target=override,
    )
    target, _, _ = parse_graphic_from_output_mei(overridden)
    assert target == override


def test_image_helpers_and_download_width_resolution(tmp_path: Path) -> None:
    png = tmp_path / "page.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 640, 480))

    assert read_image_size(png) == (640, 480)
    assert sha256_file(png) == sha256_bytes(png.read_bytes())
    session = requests.Session()
    assert resolve_width_for_stem(
        session=session,
        stem="bsb00000000_00001",
        width=1234,
        quality_rank=None,
        target_dpi=None,
        page_width_mm=210,
        timeout=1,
    ) == 1234
    assert resolve_width_for_stem(
        session=session,
        stem="bsb00000000_00001",
        width=None,
        quality_rank=None,
        target_dpi=254,
        page_width_mm=100,
        timeout=1,
    ) == 1000


def test_pipeline_commands_use_installed_modules() -> None:
    args = SimpleNamespace(
        overwrite_images=True,
        minimum_measures=2,
        max_measure_mismatch=3,
        timeout=45,
        force=True,
        pages="10-20",
        skip_pages="12",
    )

    download = step1_args("score", args)
    integration = step4_args("score", args)
    validation = step5_args("score", args)

    assert download[:4] == [sys.executable, "-m", "camat.facsimile_downloader", "score"]
    assert "--overwrite" in download and download[-4:] == ["--pages", "10-20", "--skip-pages", "12"]
    assert integration[:4] == [
        sys.executable,
        "-m",
        "camat.upload_and_integrate_measure_annotations",
        "score",
    ]
    assert integration[integration.index("--graphic-target-mode") + 1] == "iiif"
    assert "--force" in integration
    assert validation[:4] == [sys.executable, "-m", "camat.validate_iiif_vs_local", "score"]
    assert "--check-output-mei" in validation


def test_cleanup_and_metadata_helpers_are_package_safe(tmp_path: Path) -> None:
    score_dir = tmp_path / "01_score"
    score_dir.mkdir()
    source = score_dir / "page.mei"
    output = score_dir / "page_facs_zones.mei"
    image_dir = score_dir / "img"
    source.write_text("source", encoding="utf-8")
    output.write_text("output", encoding="utf-8")
    image_dir.mkdir()

    deletions = collect_deletions(score_dir)
    assert set(deletions) == {source, image_dir}
    assert output not in deletions

    assert localized_text([{"@language": "de", "@value": "Titel"}], preferred="de") == "Titel"
    assert split_creation("Leipzig : Breitkopf, 1901") == {
        "publication_place": "Leipzig",
        "publisher": "Breitkopf",
        "publication_year": "1901",
    }

    manifest = {
        "label": "A volume",
        "metadata": [
            {"label": "Title", "value": "Works: volume one"},
            {"label": "Creator", "value": "Dieterich Buxtehude"},
            {"label": "Creation", "value": "Leipzig, 1901"},
        ],
    }
    metadata = extract_meta(manifest)
    markdown = build_markdown("bsb00000000", metadata)
    assert metadata["title"] == "Works: volume one"
    assert markdown.startswith("# Buxtehude: Works")


def test_bsb_stem_and_iiif_url_overrides(tmp_path: Path, monkeypatch) -> None:
    bsb_id, page, stem = parse_bsb_viewer_url(
        "https://digitale-sammlungen.de/en/view/bsb00023199?page=185"
    )
    assert (bsb_id, page, stem) == ("bsb00023199", 185, "bsb00023199_00185")

    explicit = "https://example.test/page.jpg"
    assert resolve_iiif_image_url(image_url=explicit, stem="ignored", width=1) == explicit
    assert (
        resolve_iiif_image_url(
            stem="bsb00023199_00185",
            width=1000,
            image_url="https://cdn.example/{stem}/{width}.jpg",
        )
        == "https://cdn.example/bsb00023199_00185/1000.jpg"
    )

    source = tmp_path / "orig.mei"
    source.write_text("<mei/>", encoding="utf-8")
    staged = stage_mei_copy(source, tmp_path / "out", "bsb00000000_00001")
    assert staged.name == "bsb00000000_00001.mei"
    assert staged.read_text(encoding="utf-8") == "<mei/>"

    class DummyResponse:
        content = b"jpeg-bytes"

        def raise_for_status(self) -> None:
            return None

    class DummySession:
        def __init__(self) -> None:
            self.url = None

        def get(self, url, timeout):
            self.url = url
            return DummyResponse()

    dummy = DummySession()
    monkeypatch.setattr("camat.facsimile_downloader.requests.Session", lambda: dummy)
    image_path, url = download_facsimile_image(
        tmp_path / "img" / "page.jpg",
        image_url="https://example.test/scan.jpg",
        timeout=1,
    )
    assert url == "https://example.test/scan.jpg"
    assert dummy.url == url
    assert image_path.read_bytes() == b"jpeg-bytes"


def test_copied_pipeline_notebooks_use_package_imports_and_safe_defaults() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    def code_for(name: str) -> str:
        notebook = json.loads((repo_root / name).read_text(encoding="utf-8"))
        return "\n".join(
            "".join(cell["source"])
            for cell in notebook["cells"]
            if cell["cell_type"] == "code"
        )

    single = code_for("single_mei_iiif_integration.ipynb")
    tutorial = code_for("notebooks/mei_single_file_iiif_integration.ipynb")
    batch = code_for("run_pipeline_workflow.ipynb")

    assert "from camat import" in single
    assert "RUN_IIIF_INTEGRATION = False" in single
    assert 'SCRIPTS_DIR' not in single
    assert "import setup_camat" in tutorial
    assert 'test_corpus/Buxtehude-Anhang-S._185_musicxml_verovio.mei' in tutorial
    assert 'page=185' in tutorial
    assert "IIIF_IMAGE_URL" in tutorial
    assert "camat_corpus" not in tutorial
    assert "CORPUS_ROOT" not in tutorial
    assert "def derive_bsb_stem" not in tutorial
    assert "def stage_single_mei" not in tutorial
    assert "RUN_IIIF_INTEGRATION = False" in tutorial
    assert "raise RuntimeError(\"Review the paths" not in tutorial
    example = repo_root / "test_corpus" / "Buxtehude-Anhang-S._185_musicxml_verovio.mei"
    assert example.is_file()
    assert "RUN_PIPELINE = False" in batch
    assert "RUN_COVERAGE_CHECK = False" in batch
    assert "RUN_CUSTOM_INTEGRATION = False" in batch
    assert "RUN_CUSTOM_VALIDATION = False" in batch
    assert "EXPORT_MANUAL_REVIEW = False" in batch
    assert '"-m", "camat.run_pipeline"' in batch
    assert 'scripts/run_pipeline.py' not in batch
