from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

import camat.facsimile_viewer as facsimile_viewer
from camat.facsimile_viewer import (
    FacsimileViewerCache,
    FacsimileUnavailableError,
    InteractiveFacsimileViewer,
    build_facsimile_viewer,
    build_verovio_options,
    make_viewer_html,
    read_facsimile_model,
    render_verovio_pages,
    score_content_hash,
)


def _write_facsimile_mei(
    path: Path,
    *,
    zone_id: str = "zone-1",
    zone_ulx: int = 10,
    note_pname: str = "c",
    include_facsimile: bool = True,
) -> None:
    (path.parent / "scan.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="200"/>',
        encoding="utf-8",
    )
    facsimile = f'''
  <facsimile>
    <surface xml:id="surface-1">
      <graphic target="scan.svg" width="100" height="200"/>
      <zone xml:id="{zone_id}" type="measure" ulx="{zone_ulx}" uly="20" lrx="80" lry="180"/>
    </surface>
  </facsimile>''' if include_facsimile else ""
    facs = f' facs="#{zone_id}"' if include_facsimile else ""
    path.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.0">
  <meiHead><fileDesc><titleStmt><title>Fixture</title></titleStmt>
    <pubStmt><p>Test fixture</p></pubStmt></fileDesc></meiHead>
  {facsimile}
  <music><body><mdiv><score>
    <scoreDef meter.count="4" meter.unit="4"><staffGrp><staffDef n="1" lines="5"/></staffGrp></scoreDef>
    <section><measure xml:id="measure-1" n="1"{facs}>
      <staff n="1"><layer n="1"><note xml:id="note-1" pname="{note_pname}" oct="4" dur="1"/></layer></staff>
    </measure></section>
  </score></mdiv></body></music>
</mei>
''',
        encoding="utf-8",
    )


def test_read_facsimile_model_resolves_local_graphic(tmp_path: Path) -> None:
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)

    model = read_facsimile_model("page.mei", repo_root=tmp_path)

    assert model["graphic_target"] == "scan.svg"
    assert model["graphic_src"].startswith("data:image/svg+xml;base64,")
    assert model["image_width"] == 100
    assert model["image_height"] == 200
    assert model["zones"]["zone-1"]["ulx"] == 10
    assert model["zones"]["zone-1"]["surface_index"] == 0
    assert len(model["surfaces"]) == 1
    assert model["linked"][0]["measure_id"] == "measure-1"
    assert model["missing_facs"] == []


def test_read_facsimile_model_rejects_unresolved_measure_link(tmp_path: Path) -> None:
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    mei_path.write_text(
        mei_path.read_text(encoding="utf-8").replace('facs="#zone-1"', 'facs="#absent"'),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="unresolved measure @facs"):
        read_facsimile_model(mei_path)
    with pytest.raises(RuntimeError, match="unresolved measure @facs"):
        read_facsimile_model(mei_path, allow_missing_facsimile=True)


def test_later_surface_links_are_available_for_display(tmp_path: Path) -> None:
    mei_path = tmp_path / "pages.mei"
    _write_facsimile_mei(mei_path)
    text = mei_path.read_text(encoding="utf-8")
    text = text.replace(
        "</facsimile>",
        '''
    <surface xml:id="surface-2">
      <graphic target="scan.svg" width="100" height="200"/>
      <zone xml:id="zone-2" type="measure" ulx="10" uly="20" lrx="80" lry="180"/>
    </surface>
  </facsimile>''',
    ).replace(
        "</section>",
        '''<measure xml:id="measure-2" n="2" facs="#zone-2">
      <staff n="1"><layer n="1"><note xml:id="note-2" pname="d" oct="4" dur="1"/></layer></staff>
    </measure></section>''',
    )
    mei_path.write_text(text, encoding="utf-8")

    model = read_facsimile_model(mei_path)

    assert [surface["id"] for surface in model["surfaces"]] == [
        "surface-1",
        "surface-2",
    ]
    assert [row["measure_id"] for row in model["linked"]] == [
        "measure-1",
        "measure-2",
    ]
    assert [row["measure_id"] for row in model["other_surface_links"]] == ["measure-2"]
    assert model["other_surface_links"][0]["status"] == "linked"
    assert model["other_surface_links"][0]["surface_index"] == 1


def test_score_pages_switch_to_their_linked_facsimile_surface(tmp_path: Path) -> None:
    mei_path = tmp_path / "pages.mei"
    _write_facsimile_mei(mei_path)
    text = mei_path.read_text(encoding="utf-8")
    text = text.replace(
        "</facsimile>",
        '''
    <surface xml:id="surface-2" n="2">
      <graphic target="scan.svg" width="100" height="200"/>
      <zone xml:id="zone-2" type="measure" ulx="10" uly="20" lrx="80" lry="180"/>
    </surface>
  </facsimile>''',
    ).replace(
        "</section>",
        '''<measure xml:id="measure-2" n="2" facs="#zone-2">
      <staff n="1"><layer n="1"><note xml:id="note-2" pname="d" oct="4" dur="1"/></layer></staff>
    </measure></section>''',
    )
    mei_path.write_text(text, encoding="utf-8")
    model = read_facsimile_model(mei_path)

    html = make_viewer_html(
        model,
        [
            {"number": 1, "svg": '<svg><g class="measure" id="measure-1"/></svg>'},
            {"number": 2, "svg": '<svg><g class="measure" id="measure-2"/></svg>'},
        ],
        total_score_pages=2,
        viewer_id="test-viewer",
        initial_score_zoom_percent=125,
        initial_facsimile_zoom_percent=150,
        zoom_step_percent=25,
        min_zoom_percent=50,
        max_zoom_percent=200,
    )

    assert 'data-surface-index="0"' in html
    assert 'data-surface-index="1"' in html
    assert 'data-surface-n="2"' in html
    assert 'const scorePageSurfaces = [0, 1];' in html
    assert "showFacsimileSurface(scorePageSurfaces[activePageIndex])" in html
    assert '"surfaceIndex": 1' in html
    assert 'width="100" height="200"' in html
    assert "scrollbar-gutter: stable" in html
    assert "if (!nextSurface.classList.contains('is-active'))" in html
    assert '<span class="facsimile-page-label" aria-live="polite"></span>' in html
    assert "--score-zoom: 125%;" in html
    assert "--facsimile-zoom: 150%;" in html
    assert 'class="score-zoom-reset" title="Reset score zoom">125%</button>' in html
    assert (
        'class="facsimile-zoom-reset" title="Reset facsimile zoom">150%</button>'
        in html
    )
    assert "const zoomStep = 25;" in html
    assert "const minZoom = 50;" in html
    assert "const maxZoom = 200;" in html
    assert "applyScoreZoom(scoreZoom + zoomStep)" in html
    assert "applyFacsimileZoom(facsimileZoom + zoomStep)" in html


def test_missing_facsimile_has_strict_error_and_score_only_model(tmp_path: Path) -> None:
    mei_path = tmp_path / "score.mei"
    _write_facsimile_mei(mei_path, include_facsimile=False)

    with pytest.raises(FacsimileUnavailableError, match="No <facsimile>"):
        read_facsimile_model(mei_path)

    model = read_facsimile_model(mei_path, allow_missing_facsimile=True)
    assert model["viewer_mode"] == "score-only"
    assert model["has_facsimile"] is False
    assert model["linked"] == []
    assert model["measures"][0]["status"] == "facsimile unavailable"


def test_score_hash_ignores_facsimile_edits_but_tracks_notation(tmp_path: Path) -> None:
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path, zone_ulx=10)
    initial_hash = score_content_hash(mei_path)

    _write_facsimile_mei(mei_path, zone_ulx=25)
    assert score_content_hash(mei_path) == initial_hash

    _write_facsimile_mei(mei_path, zone_ulx=25, note_pname="d")
    assert score_content_hash(mei_path) != initial_hash


def test_build_viewer_reuses_score_render_for_zone_only_edit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path, zone_ulx=10)
    calls: list[Path] = []

    def fake_render(path: Path, **_: object) -> dict:
        calls.append(path)
        return {
            "page_count": 1,
            "initial_page": 1,
            "initial_page_index": 0,
            "pages": [
                {
                    "number": 1,
                    "svg": '<svg><g class="measure" id="measure-1"></g></svg>',
                }
            ],
        }

    monkeypatch.setattr(facsimile_viewer, "render_verovio_pages", fake_render)
    cache = FacsimileViewerCache()
    first = build_facsimile_viewer(
        mei_path,
        verovio_options={"scale": 30},
        cache=cache,
        viewer_id="test-viewer",
    )

    _write_facsimile_mei(mei_path, zone_ulx=25)
    second = build_facsimile_viewer(
        mei_path,
        verovio_options={"scale": 30},
        cache=cache,
        viewer_id="test-viewer",
    )

    assert first["rendered_score"] is True
    assert second["rendered_score"] is False
    assert len(calls) == 1
    assert 'x="25"' in second["html"]
    assert "Measure-zone diagnostic table (1 measures)" in second["html"]


def test_score_only_viewer_can_transition_to_linked_view_without_rerendering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mei_path = tmp_path / "score.mei"
    _write_facsimile_mei(mei_path, include_facsimile=False)
    calls: list[Path] = []

    def fake_render(path: Path, **_: object) -> dict:
        calls.append(path)
        return {
            "page_count": 1,
            "initial_page": 1,
            "initial_page_index": 0,
            "pages": [
                {
                    "number": 1,
                    "svg": '<svg><g class="measure" id="measure-1"></g></svg>',
                }
            ],
        }

    monkeypatch.setattr(facsimile_viewer, "render_verovio_pages", fake_render)
    cache = FacsimileViewerCache()
    score_only = build_facsimile_viewer(
        mei_path,
        verovio_options={"scale": 30},
        cache=cache,
        viewer_id="test-viewer",
    )

    assert score_only["model"]["viewer_mode"] == "score-only"
    assert score_only["rendered_score"] is True
    assert "Score-only mode" in score_only["html"]
    assert "viewer-grid is-score-only" in score_only["html"]
    assert "facsimile-pane" not in score_only["html"]

    _write_facsimile_mei(mei_path, include_facsimile=True)
    linked = build_facsimile_viewer(
        mei_path,
        verovio_options={"scale": 30},
        cache=cache,
        viewer_id="test-viewer",
    )

    assert linked["model"]["viewer_mode"] == "facsimile"
    assert linked["rendered_score"] is False
    assert "facsimile-pane" in linked["html"]
    assert len(calls) == 1


def test_build_verovio_options_validates_layout() -> None:
    options = build_verovio_options(
        {"scale": 40},
        orientation="landscape",
        breaks="encoded",
        adjust_page_height=True,
        landscape_size=(1200, 800),
    )

    assert options == {
        "scale": 40,
        "adjustPageHeight": True,
        "breaks": "encoded",
        "pageWidth": 1200,
        "pageHeight": 800,
    }
    with pytest.raises(ValueError, match="orientation"):
        build_verovio_options({}, orientation="square", breaks="auto", adjust_page_height=False)
    with pytest.raises(ValueError, match="breaks"):
        build_verovio_options({}, orientation="portrait", breaks="manual", adjust_page_height=False)


def test_render_verovio_pages_returns_every_page() -> None:
    source = Path(__file__).parents[1] / "camat" / "examples" / "duration_semantics.mei"
    result = render_verovio_pages(
        str(source),
        initial_page=1,
        options={"footer": "none", "scale": 20, "svgViewBox": True},
    )

    assert result["page_count"] >= 1
    assert len(result["pages"]) == result["page_count"]
    assert all("<svg" in page["svg"] for page in result["pages"])


def test_render_verovio_pages_can_keep_native_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[bool] = []

    @contextlib.contextmanager
    def fake_suppress(*, enabled: bool = True, **_: object):
        seen.append(enabled)
        yield

    monkeypatch.setattr(facsimile_viewer, "suppress_native_output", fake_suppress)
    source = Path(__file__).parents[1] / "camat" / "examples" / "duration_semantics.mei"
    render_verovio_pages(
        str(source),
        initial_page=1,
        options={"footer": "none", "scale": 20, "svgViewBox": True},
        show_verovio_warnings=True,
    )

    assert seen == [False]


def test_viewer_page_controls_initialize_after_dom_attachment(tmp_path: Path) -> None:
    mei_path = tmp_path / "score.mei"
    _write_facsimile_mei(mei_path, include_facsimile=False)
    model = read_facsimile_model(mei_path, allow_missing_facsimile=True)
    html = make_viewer_html(
        model,
        [
            {"number": 1, "svg": '<svg><g class="measure" id="measure-1"/></svg>'},
            {"number": 2, "svg": '<svg><g class="measure" id="measure-2"/></svg>'},
        ],
        total_score_pages=2,
        viewer_id="test-viewer",
    )

    assert 'class="score-next"' in html
    assert "function initializeViewer()" in html
    assert "window.setTimeout(initializeViewer, 0)" in html
    assert "root.dataset.camatViewerInitialized" in html
    assert 'class="score-zoom-out"' in html
    assert '<button type="button" class="facsimile-zoom-out"' not in html


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"min_zoom_percent": 0}, "min_zoom_percent"),
        (
            {"min_zoom_percent": 200, "max_zoom_percent": 100},
            "max_zoom_percent",
        ),
        ({"zoom_step_percent": 0}, "zoom_step_percent"),
        ({"initial_score_zoom_percent": 25}, "initial_score_zoom_percent"),
        ({"initial_facsimile_zoom_percent": 400}, "initial_facsimile_zoom_percent"),
    ],
)
def test_viewer_rejects_invalid_zoom_configuration(
    tmp_path: Path,
    kwargs: dict,
    message: str,
) -> None:
    mei_path = tmp_path / "score.mei"
    _write_facsimile_mei(mei_path, include_facsimile=False)
    model = read_facsimile_model(mei_path, allow_missing_facsimile=True)

    with pytest.raises(ValueError, match=message):
        make_viewer_html(
            model,
            [{"number": 1, "svg": "<svg/>"}],
            total_score_pages=1,
            **kwargs,
        )


def test_interactive_viewers_get_unique_default_dom_ids(tmp_path: Path) -> None:
    _write_facsimile_mei(tmp_path / "one.mei")
    _write_facsimile_mei(tmp_path / "two.mei")
    first = InteractiveFacsimileViewer(tmp_path / "one.mei")
    second = InteractiveFacsimileViewer(tmp_path / "two.mei")

    assert first.viewer_id.startswith("mei-viewer-live-")
    assert first.viewer_id != second.viewer_id


def test_to_direct_download_url_converts_github_blob_pages() -> None:
    from camat.music_utils import to_direct_download_url

    blob = "https://github.com/owner/repo/blob/main/path/score.mei"
    raw = "https://raw.githubusercontent.com/owner/repo/main/path/score.mei"
    assert to_direct_download_url(blob) == raw
    assert to_direct_download_url(raw) == raw
    assert to_direct_download_url("https://example.org/score.mei") == "https://example.org/score.mei"


def test_resolve_mei_source_accepts_local_and_remote_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from camat.facsimile_viewer import resolve_mei_source

    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)

    assert resolve_mei_source("page.mei", repo_root=tmp_path) == mei_path.resolve()
    assert resolve_mei_source(mei_path) == mei_path.resolve()

    with pytest.raises(FileNotFoundError, match="No MEI file"):
        resolve_mei_source("missing.mei", repo_root=tmp_path)

    downloaded = tmp_path / "downloaded.mei"
    downloaded.write_text("<mei/>", encoding="utf-8")
    blob = "https://github.com/owner/repo/blob/main/score.mei"

    def fake_get_file_path(file_source: str, **_: object) -> str:
        assert file_source == blob
        return str(downloaded)

    monkeypatch.setattr("camat.music_utils.get_file_path", fake_get_file_path)

    assert resolve_mei_source(blob, cache_dir=tmp_path / "cache") == downloaded.resolve()
