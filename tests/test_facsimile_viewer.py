from __future__ import annotations

import contextlib
import gc
import json
import os
import re
import weakref
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

import camat.facsimile_viewer as facsimile_viewer
from camat.facsimile_viewer import (
    FacsimileViewerCache,
    FacsimileUnavailableError,
    InteractiveFacsimileViewer,
    apply_facsimile_layout,
    build_facsimile_viewer,
    build_verovio_options,
    json_for_script,
    make_viewer_html,
    embed_viewer_html,
    read_facsimile_model,
    render_verovio_pages,
    resolve_graphic_src,
    display_iiif_url,
    resolve_mei_source_info,
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


def test_resolve_graphic_src_accepts_file_uri(tmp_path: Path) -> None:
    image_path = tmp_path / "scan.svg"
    image_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="20"/>',
        encoding="utf-8",
    )

    result = resolve_graphic_src(image_path.as_uri(), tmp_path / "score.mei")

    assert result.startswith("data:image/svg+xml;base64,")


def test_display_iiif_url_caps_full_width_requests() -> None:
    url = (
        "https://api.digitale-sammlungen.de/iiif/image/v2/"
        "bsb00023199_00013/full/4134,/0/default.jpg"
    )
    assert display_iiif_url(url, 1200).endswith("/full/1200,/0/default.jpg")
    assert display_iiif_url(url, 5000) == url
    assert display_iiif_url(url.replace("4134,", "800,"), 1200).endswith(
        "/full/800,/0/default.jpg"
    )
    assert display_iiif_url("https://example.org/scan.jpg", 1200) == (
        "https://example.org/scan.jpg"
    )
    max_url = url.replace("4134,", "max")
    assert display_iiif_url(max_url, 1200).endswith("/full/1200,/0/default.jpg")


def test_packaged_demo_copies_graphic_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "camat.music_utils.get_download_cache_dir",
        lambda cache_dir=None: str(tmp_path),
    )
    mei_path = facsimile_viewer._packaged_example_path(
        "camat/examples/facsimile_viewer_demo.mei"
    )

    assert mei_path is not None
    assert (mei_path.parent / "facsimile_viewer_demo.svg").is_file()
    assert resolve_graphic_src("facsimile_viewer_demo.svg", mei_path).startswith(
        "data:image/svg+xml;base64,"
    )


def test_viewer_html_embeds_http_iiif_graphic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    mei_path.write_text(
        mei_path.read_text(encoding="utf-8").replace(
            'target="scan.svg"',
            'target="https://api.example.org/iiif/image/v2/page/full/4134,/0/default.jpg"',
        ),
        encoding="utf-8",
    )
    model = read_facsimile_model(mei_path)
    assert model["graphic_src"].startswith("https://")

    jpeg_path = tmp_path / "page.jpg"
    jpeg_path.write_bytes(b"\xff\xd8\xfffakejpeg")
    fetched: list[str] = []

    def fake_get_file_path(url: str, **_kwargs: object) -> str:
        fetched.append(url)
        return str(jpeg_path)

    monkeypatch.setattr("camat.music_utils.get_file_path", fake_get_file_path)

    html = make_viewer_html(
        model,
        [{"number": 1, "svg": '<svg xmlns="http://www.w3.org/2000/svg"></svg>'}],
        total_score_pages=1,
        viewer_id="embed-http-test",
        show_diagnostic_table=False,
        show_annotations=False,
    )

    assert fetched == [
        "https://api.example.org/iiif/image/v2/page/full/100,/0/default.jpg"
    ]
    assert 'src="data:image/jpeg;base64,' in html
    assert 'referrerpolicy="no-referrer"' in html
    assert 'title="https://api.example.org/iiif/image/v2/page/full/4134,/0/default.jpg"' in html


def test_embed_remote_graphic_falls_back_to_url_when_download_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get_file_path(*_args: object, **_kwargs: object) -> str:
        raise ValueError("offline")

    monkeypatch.setattr("camat.music_utils.get_file_path", fake_get_file_path)
    url = "https://api.example.org/iiif/image/v2/page/full/4134,/0/default.jpg"

    assert facsimile_viewer._embed_remote_graphic_src(url, max_width=1200) == (
        "https://api.example.org/iiif/image/v2/page/full/1200,/0/default.jpg"
    )


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
    assert "function initializeViewer(root)" in html
    assert "function initializeAttachedViewers()" in html
    assert 'document.querySelectorAll(\'[id="\' + viewerId + \'"]\')' in html
    assert "window.setTimeout(initializeAttachedViewers, 0)" in html
    assert "MutationObserver" in html
    assert "root.dataset.camatViewerInitialized" in html
    assert 'class="score-zoom-out"' in html
    assert '<button type="button" class="facsimile-zoom-out"' not in html


@pytest.mark.parametrize(
    "value",
    ["a</script>b", "x & y", "<div>", "close </SCRIPT > loosely", "a\u2028b"],
)
def test_json_for_script_round_trips_without_emitting_markup(value: str) -> None:
    encoded = json_for_script(value)

    assert "<" not in encoded
    assert ">" not in encoded
    assert "&" not in encoded
    assert json.loads(encoded) == value


def test_annotation_text_cannot_close_the_viewer_script(tmp_path: Path) -> None:
    """MEI is untrusted input: ``</script>`` in an annotation must stay inert."""
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    hostile = "BREAK</script><script>window.pwned=1;//"
    mei_path.write_text(
        mei_path.read_text(encoding="utf-8").replace(
            "</measure>",
            '<annot xml:id="hostile" plist="#note-1">'
            "BREAK&lt;/script&gt;&lt;script&gt;window.pwned=1;//"
            "</annot></measure>",
        ),
        encoding="utf-8",
    )

    result = build_facsimile_viewer(
        mei_path,
        verovio_options=build_verovio_options(
            {"footer": "none", "scale": 35, "svgViewBox": True},
            orientation="portrait",
            breaks="encoded",
            adjust_page_height=True,
        ),
    )
    html = result["html"]

    assert hostile not in html
    assert html.count("</script>") == 1

    payload = re.search(r"const annotations = (\[.*?\]);\n", html, re.S)
    assert payload is not None
    decoded = json.loads(payload.group(1))
    assert any(item["text"] == hostile for item in decoded)


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
    refresh_flags: list[bool] = []

    def fake_get_file_path(file_source: str, **kwargs: object) -> str:
        assert file_source == blob
        refresh_flags.append(bool(kwargs.get("force_refresh")))
        return str(downloaded)

    monkeypatch.setattr("camat.music_utils.get_file_path", fake_get_file_path)

    assert resolve_mei_source(blob, cache_dir=tmp_path / "cache") == downloaded.resolve()
    assert resolve_mei_source(
        blob,
        cache_dir=tmp_path / "cache",
        refresh_remote=True,
    ) == downloaded.resolve()
    assert refresh_flags == [False, True]


def test_resolve_mei_source_supports_file_uris_and_rejects_foreign_windows_paths(
    tmp_path: Path,
) -> None:
    mei_path = tmp_path / "path with spaces.mei"
    _write_facsimile_mei(mei_path)

    info = resolve_mei_source_info(mei_path.as_uri())

    assert info.kind == "file-uri"
    assert info.local_path == mei_path.resolve()
    if os.name != "nt":
        with pytest.raises(FileNotFoundError, match="Windows path"):
            resolve_mei_source_info(r"C:\\Editions\\score.mei", repo_root=tmp_path)
        with pytest.raises(FileNotFoundError, match="Windows path"):
            resolve_mei_source_info(r"\\server\share\score.mei", repo_root=tmp_path)


def test_remote_mei_resolves_relative_graphic_against_original_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloaded = tmp_path / "downloaded.mei"
    _write_facsimile_mei(downloaded)

    monkeypatch.setattr(
        "camat.music_utils.get_file_path",
        lambda *_args, **_kwargs: str(downloaded),
    )

    model = read_facsimile_model("https://example.org/editions/page.mei")

    assert model["source"].kind == "remote"
    assert model["surfaces"][0]["graphic_src"] == (
        "https://example.org/editions/scan.svg"
    )


def test_bundled_demo_resolves_plist_and_tstamp_annotations() -> None:
    demo = Path(__file__).parents[1] / "camat" / "examples" / "facsimile_viewer_demo.mei"

    result = build_facsimile_viewer(
        demo,
        verovio_options={
            "breaks": "encoded",
            "footer": "none",
            "pageWidth": 2100,
            "pageHeight": 2970,
            "scale": 35,
        },
        viewer_id="annotation-test",
    )
    annotations = {row["id"]: row for row in result["model"]["annotations"]}

    assert annotations["demo-annot-plist"]["target_ids"] == ["demo-note-2"]
    assert annotations["demo-annot-plist"]["status"] == "resolved"
    assert annotations["demo-annot-tstamp"]["target_ids"] == ["demo-note-4"]
    assert annotations["demo-annot-tstamp"]["status"] == "resolved"
    assert "Highlight annotations (2)" in result["html"]
    assert 'data-annotation-id="demo-annot-tstamp"' in result["html"]
    assert "applyAnnotationVisibility" in result["html"]


def test_facsimile_layout_is_inferred_and_applied_without_writing_source(
    tmp_path: Path,
) -> None:
    demo = Path(__file__).parents[1] / "camat" / "examples" / "facsimile_viewer_demo.mei"
    source_text = demo.read_text(encoding="utf-8")
    source_text = source_text.replace(
        '<pb xml:id="demo-pb-1" n="1" facs="#demo-surface-1"/>', ""
    ).replace('<sb xml:id="demo-sb-1"/>', "")
    source_path = tmp_path / "without-breaks.mei"
    source_path.write_text(source_text, encoding="utf-8")
    (tmp_path / "facsimile_viewer_demo.svg").write_text(
        (demo.parent / "facsimile_viewer_demo.svg").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    model = read_facsimile_model(source_path)

    assert [row["measure_id"] for row in model["layout"]["missing_page_breaks"]] == [
        "demo-measure-1"
    ]
    assert model["layout"]["missing_system_breaks"] == ["demo-measure-3"]

    aligned_text, layout = apply_facsimile_layout(source_text, model)

    assert source_path.read_text(encoding="utf-8") == source_text
    assert 'facs="#demo-surface-1"' in aligned_text
    assert "camat-inferred-sb-1" in aligned_text
    assert layout["applied_page_breaks"] == ["demo-measure-1"]
    assert layout["applied_system_breaks"] == ["demo-measure-3"]


def test_interactive_refreshes_use_distinct_render_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    viewer = InteractiveFacsimileViewer(mei_path, viewer_id="stable-viewer")
    render_ids: list[str] = []

    def fake_build(*_args: object, **kwargs: object) -> dict:
        render_ids.append(str(kwargs["viewer_id"]))
        return {"cache": viewer.cache}

    monkeypatch.setattr(facsimile_viewer, "build_facsimile_viewer", fake_build)

    viewer._build_viewer(render_score=True)
    viewer._build_viewer(render_score=False)

    assert render_ids[0].startswith("stable-viewer-render-1-")
    assert render_ids[1].startswith("stable-viewer-render-2-")
    assert render_ids[0] != render_ids[1]


def test_embed_viewer_html_uses_iframe_srcdoc_and_escapes_markup() -> None:
    wrapped = embed_viewer_html('<div id="v">quote="x" & y</div>', min_height=120)

    assert wrapped.startswith('<iframe class="camat-mei-viewer-frame"')
    assert 'sandbox="allow-scripts allow-same-origin"' in wrapped
    assert "min-height:120px" in wrapped
    assert "&lt;div id=&quot;v&quot;&gt;" in wrapped
    assert "&amp; y" in wrapped
    assert "<div id=" not in wrapped
    assert "syncHeight" in wrapped
    assert "no-referrer" in wrapped


def test_display_publishes_a_single_widget_with_iframe_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)

    class FakeWidgets:
        class Layout:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class Button:
            def __init__(self, **kwargs):
                self.description = kwargs.get("description")
                self.clicks = []

            def on_click(self, fn) -> None:
                self.clicks.append(fn)

        class ToggleButton:
            def __init__(self, **kwargs):
                self._value = kwargs.get("value", False)
                self.disabled = kwargs.get("disabled", False)
                self.tooltip = kwargs.get("tooltip", "")
                self._observers: list = []

            @property
            def value(self):
                return self._value

            @value.setter
            def value(self, value) -> None:
                old = self._value
                self._value = value
                if old != value:
                    for fn in self._observers:
                        fn({"name": "value", "old": old, "new": value})

            def observe(self, fn, names=None) -> None:
                self._observers.append(fn)

        class HTML:
            def __init__(self, value="", layout=None):
                self.history: list[str] = []
                self.value = value
                self.layout = layout

            @property
            def value(self):
                return self._value

            @value.setter
            def value(self, text) -> None:
                # Kept so tests can assert on transient messages, not just the last.
                self._value = text
                self.history.append(text)

        class HBox:
            def __init__(self, children):
                self.children = children

        class VBox:
            def __init__(self, children):
                self.children = children

    displayed: list = []

    def fake_display(*args: object, **_: object) -> None:
        displayed.append(args)

    viewer = InteractiveFacsimileViewer(mei_path, auto_watch_mei=False, viewer_max_height=200)
    viewer._widgets = FakeWidgets
    viewer._get_ipython = lambda: None
    viewer._display = fake_display
    monkeypatch.setattr(
        viewer,
        "_build_viewer",
        lambda **_: {
            "html": '<div id="viewer-root"></div>',
            "summary": "ok",
            "score_render": {"page_count": 1},
            "rendered_score": True,
            "model": {"has_facsimile": True},
            "cache": viewer.cache,
        },
    )

    returned = viewer.display()

    assert returned is viewer
    assert len(displayed) == 1
    assert len(displayed[0]) == 1
    assert isinstance(displayed[0][0], FakeWidgets.VBox)
    assert displayed[0][0].children[-1] is viewer.viewer_html
    assert viewer.viewer_html.value.startswith('<iframe class="camat-mei-viewer-frame"')
    assert "srcdoc=" in viewer.viewer_html.value
    assert "ok" in viewer.status_html.value
    assert "1 Verovio score page" in viewer.status_html.value


def _stub_jupyter_widgets():
    class Widgets:
        class Layout:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class Button:
            def __init__(self, **kwargs):
                self.description = kwargs.get("description")
                self.clicks = []

            def on_click(self, fn) -> None:
                self.clicks.append(fn)

        class ToggleButton:
            def __init__(self, **kwargs):
                self._value = kwargs.get("value", False)
                self.disabled = kwargs.get("disabled", False)
                self.tooltip = kwargs.get("tooltip", "")
                self._observers: list = []

            @property
            def value(self):
                return self._value

            @value.setter
            def value(self, value) -> None:
                old = self._value
                self._value = value
                if old != value:
                    for fn in self._observers:
                        fn({"name": "value", "old": old, "new": value})

            def observe(self, fn, names=None) -> None:
                self._observers.append(fn)

        class HTML:
            def __init__(self, value="", layout=None):
                self.history: list[str] = []
                self.value = value
                self.layout = layout

            @property
            def value(self):
                return self._value

            @value.setter
            def value(self, text) -> None:
                # Kept so tests can assert on transient messages, not just the last.
                self._value = text
                self.history.append(text)

        class HBox:
            def __init__(self, children):
                self.children = children

        class VBox:
            def __init__(self, children):
                self.children = children

    return Widgets


def _stub_viewer_build(viewer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        viewer,
        "_build_viewer",
        lambda **_: {
            "html": '<div id="viewer-root"></div>',
            "summary": "ok",
            "score_render": {"page_count": 1},
            "rendered_score": True,
            "model": {"has_facsimile": True},
            "cache": viewer.cache,
        },
    )


def test_remote_source_disables_auto_watch_and_keeps_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloaded = tmp_path / "downloaded.mei"
    _write_facsimile_mei(downloaded)
    monkeypatch.setattr(
        "camat.music_utils.get_file_path",
        lambda *_args, **_kwargs: str(downloaded),
    )
    displayed: list = []
    viewer = InteractiveFacsimileViewer(
        "https://example.org/editions/page.mei",
        auto_watch_mei=True,
        viewer_max_height=200,
    )
    viewer._widgets = _stub_jupyter_widgets()
    viewer._get_ipython = lambda: None
    viewer._display = lambda *args, **_: displayed.append(args)
    _stub_viewer_build(viewer, monkeypatch)

    viewer.display()

    assert viewer.watch_toggle.disabled is True
    assert viewer.watch_toggle.value is False
    assert "Reload source" in viewer.watch_status.value
    assert "Auto-watch off" not in viewer.watch_status.value

    viewer.watch_toggle.disabled = False
    viewer.watch_toggle.value = True

    assert viewer.watch_toggle.value is False
    assert "Reload source" in viewer.watch_status.value
    assert "Auto-watch off" not in viewer.watch_status.value


def test_local_auto_watch_toggle_starts_watch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    viewer = InteractiveFacsimileViewer(
        mei_path, auto_watch_mei=False, viewer_max_height=200
    )
    viewer._widgets = _stub_jupyter_widgets()
    viewer._get_ipython = lambda: None
    viewer._display = lambda *_args, **_kwargs: None
    _stub_viewer_build(viewer, monkeypatch)
    monkeypatch.setattr(
        InteractiveFacsimileViewer,
        "_start_watch_events",
        lambda self: True,
    )

    viewer.display()
    viewer.watch_toggle.value = True

    assert viewer.watch_toggle.value is True
    assert viewer.watch_toggle.disabled is False
    assert viewer._watch_state["path"] == mei_path.resolve()


def _stub_observer_class(created: list) -> type:
    class FakeObserver:
        def __init__(self) -> None:
            self.running = False
            self.daemon = False
            self.handler = None
            self.watched: str | None = None
            created.append(self)

        def schedule(self, handler, path, recursive=False) -> None:
            self.handler = handler
            self.watched = path

        def start(self) -> None:
            self.running = True

        def stop(self) -> None:
            self.running = False

        def join(self, timeout=None) -> None:
            return None

    return FakeObserver


def _fake_refresh() -> dict:
    """A successful render result, with a cache that closes over nothing."""
    return {
        "html": '<div id="viewer-root"></div>',
        "summary": "ok",
        "score_render": {"page_count": 1},
        "rendered_score": True,
        "model": {"has_facsimile": True},
        "cache": FacsimileViewerCache(),
    }


def _stub_widget_plumbing(viewer: InteractiveFacsimileViewer) -> None:
    """Wire fake widgets without capturing ``viewer`` in a strong closure."""
    viewer._widgets = _stub_jupyter_widgets()
    viewer._get_ipython = lambda: None
    viewer._display = lambda *_args, **_kwargs: None
    viewer._build_viewer = lambda **_: _fake_refresh()


def test_toolbar_reload_failure_is_reported_in_the_status_area(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ipywidgets drops handler exceptions, so the viewer must catch them itself."""
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    viewer = InteractiveFacsimileViewer(mei_path, auto_watch_mei=False)
    _stub_widget_plumbing(viewer)
    viewer.display()

    def explode(**_: object) -> dict:
        raise RuntimeError("Found 1 unresolved measure @facs link(s): #no-such-zone")

    monkeypatch.setattr(viewer, "refresh_viewer", explode)
    button = viewer.reload_zones_btn
    for handler in button.clicks:
        handler(button)

    assert "Reload zones failed" in viewer.status_html.value
    assert "RuntimeError" in viewer.status_html.value
    assert "#no-such-zone" in viewer.status_html.value


def test_toolbar_failure_message_is_escaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    viewer = InteractiveFacsimileViewer(mei_path, auto_watch_mei=False)
    _stub_widget_plumbing(viewer)
    viewer.display()

    def explode(**_: object) -> dict:
        raise RuntimeError("<img src=x onerror=alert(1)>")

    monkeypatch.setattr(viewer, "refresh_viewer", explode)
    button = viewer.reload_score_btn
    for handler in button.clicks:
        handler(button)

    assert "<img" not in viewer.status_html.value
    assert "&lt;img" in viewer.status_html.value


def test_relaunching_a_viewer_retires_the_previous_watcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running a launch cell must leave exactly one observer for the file."""
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    created: list = []
    monkeypatch.setattr("watchdog.observers.Observer", _stub_observer_class(created))

    def launch() -> InteractiveFacsimileViewer:
        viewer = InteractiveFacsimileViewer(mei_path, auto_watch_mei=True)
        _stub_widget_plumbing(viewer)
        return viewer.display()

    first = launch()
    second = launch()

    assert len(created) == 2
    assert created[0].running is False
    assert created[1].running is True
    assert first._watch_state["observer"] is None
    assert facsimile_viewer._active_watchers[mei_path.resolve()]() is second

    second.stop_watch()

    assert created[1].running is False
    assert mei_path.resolve() not in facsimile_viewer._active_watchers


def test_watchers_for_different_files_coexist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_path = tmp_path / "one" / "page.mei"
    second_path = tmp_path / "two" / "page.mei"
    for path in (first_path, second_path):
        path.parent.mkdir()
        _write_facsimile_mei(path)
    created: list = []
    monkeypatch.setattr("watchdog.observers.Observer", _stub_observer_class(created))

    viewers = []
    for path in (first_path, second_path):
        viewer = InteractiveFacsimileViewer(path, auto_watch_mei=True)
        _stub_widget_plumbing(viewer)
        viewers.append(viewer.display())

    assert [observer.running for observer in created] == [True, True]
    assert facsimile_viewer._active_watchers.keys() >= {
        first_path.resolve(),
        second_path.resolve(),
    }

    for viewer in viewers:
        viewer.stop_watch()

    assert [observer.running for observer in created] == [False, False]


def test_discarding_a_viewer_stops_its_observer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The observer must not be the reference that keeps a dead viewer alive."""
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    created: list = []
    monkeypatch.setattr("watchdog.observers.Observer", _stub_observer_class(created))

    viewer = InteractiveFacsimileViewer(mei_path, auto_watch_mei=True)
    _stub_widget_plumbing(viewer)
    viewer.display()
    reference = weakref.ref(viewer)

    assert created[0].running is True

    del viewer
    gc.collect()

    assert reference() is None
    assert created[0].running is False


class _RecordingLoop:
    """Stands in for the kernel IO loop, recording instead of running work."""

    def __init__(self) -> None:
        self.queue: list[tuple[float, object]] = []

    def add_callback(self, fn) -> None:
        self.queue.append((0.0, fn))

    def call_later(self, delay, fn) -> None:
        self.queue.append((delay, fn))

    def drain(self) -> list[float]:
        """Run everything queued, returning the delays each item was queued with."""
        delays = []
        while self.queue:
            delay, fn = self.queue.pop(0)
            delays.append(delay)
            fn()
        return delays


def _watching_viewer(
    mei_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs
) -> InteractiveFacsimileViewer:
    monkeypatch.setattr("watchdog.observers.Observer", _stub_observer_class([]))
    viewer = InteractiveFacsimileViewer(mei_path, auto_watch_mei=True, **kwargs)
    _stub_widget_plumbing(viewer)
    viewer.display()
    return viewer


def test_reload_waits_out_the_settle_delay_without_blocking_the_kernel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sleeping here would stall widget comms for every other cell too."""
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    viewer = _watching_viewer(mei_path, monkeypatch, watch_settle_sec=0.4)
    loop = _RecordingLoop()
    viewer._get_ipython = lambda: SimpleNamespace(kernel=SimpleNamespace(io_loop=loop))

    renders: list[dict] = []
    monkeypatch.setattr(
        viewer, "refresh_viewer", lambda **kw: renders.append(kw) or _fake_refresh()
    )
    monkeypatch.setattr(
        "time.sleep", lambda _s: pytest.fail("the reload must not block the loop")
    )

    viewer._reload_from_watch("modified")
    assert renders == [], "rendering must be deferred, not run inline"

    # A thread-safe hop onto the loop, then the settle delay armed from inside it.
    assert loop.drain() == [0.0, 0.4]
    assert renders == [{"render_score": True}]
    assert "Reloaded" in viewer.watch_status.value


def test_reload_retries_a_save_caught_mid_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An editor writing in place is briefly visible as truncated XML."""
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    viewer = _watching_viewer(mei_path, monkeypatch, watch_settle_sec=0)
    monkeypatch.setattr(facsimile_viewer, "WATCH_PARSE_RETRY_SEC", 0)

    attempts = []

    def flaky(**_: object) -> dict:
        attempts.append(1)
        if len(attempts) < 3:
            raise ET.ParseError("no element found: line 41, column 0")
        return _fake_refresh()

    monkeypatch.setattr(viewer, "refresh_viewer", flaky)

    viewer._reload_from_watch("modified")

    assert len(attempts) == 3
    assert "Reloaded" in viewer.watch_status.value
    assert any(
        "Waiting for the save to finish" in text for text in viewer.watch_status.history
    )


def test_reload_reports_mei_that_stays_unparseable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    viewer = _watching_viewer(mei_path, monkeypatch, watch_settle_sec=0)
    monkeypatch.setattr(facsimile_viewer, "WATCH_PARSE_RETRY_SEC", 0)

    def broken(**_: object) -> dict:
        raise ET.ParseError("mismatched tag: line 12, column 4")

    monkeypatch.setattr(viewer, "refresh_viewer", broken)

    viewer._reload_from_watch("modified")

    status = viewer.watch_status.value
    assert "Reload failed" in status
    assert f"after {facsimile_viewer.WATCH_PARSE_RETRIES + 1} attempts" in status
    assert "mismatched tag" in status
    assert viewer._watch_state["reloading"] is False, "a failure must not wedge the watch"


def test_watch_runs_before_display_has_built_a_toggle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``start_watch`` is public: with no toolbar there is no toggle to switch off."""
    mei_path = tmp_path / "page.mei"
    _write_facsimile_mei(mei_path)
    created: list = []
    monkeypatch.setattr("watchdog.observers.Observer", _stub_observer_class(created))
    viewer = InteractiveFacsimileViewer(mei_path, auto_watch_mei=True)
    viewer._get_ipython = lambda: None

    viewer.start_watch()

    assert viewer.watch_toggle is None
    assert viewer._watch_enabled() is True
    assert created[0].running is True

    # start_watch ignores events for a second so its own reads do not retrigger.
    viewer._watch_state["ignore_until"] = 0.0
    viewer._request_reload("modified")
    timer = viewer._watch_state["debounce_timer"]
    assert timer is not None, "a viewer without widgets must still queue reloads"
    timer.cancel()
    viewer.stop_watch()


def test_facsimile_notebook_is_portable_and_has_no_persisted_widget_state() -> None:
    notebook_path = (
        Path(__file__).parents[1] / "notebooks" / "mei_facsimile_viewer.ipynb"
    )
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )

    assert "import setup_camat\nfrom camat import" in code
    assert 'MEI_SOURCE = "camat/examples/facsimile_viewer_demo.mei"' in code
    assert "SHOW_ANNOTATIONS = True" in code
    assert "ALIGN_TO_FACSIMILE = False" in code
    assert all(
        cell.get("execution_count") is None and not cell.get("outputs")
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )
    assert "widgets" not in notebook.get("metadata", {})

def test_resolve_mei_source_fetch_false_uses_cache_or_returns_none(
    tmp_path: Path,
) -> None:
    from camat.facsimile_viewer import resolve_mei_source
    from camat.music_utils import _cached_download_filename, to_direct_download_url

    url = "https://example.org/scores/demo.mei"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    assert resolve_mei_source(url, cache_dir=cache_dir, fetch=False) is None

    cached = cache_dir / _cached_download_filename(to_direct_download_url(url))
    cached.write_text("<mei/>", encoding="utf-8")
    assert resolve_mei_source(url, cache_dir=cache_dir, fetch=False) == cached.resolve()


def test_resolve_mei_source_shared_cache_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from camat.facsimile_viewer import resolve_mei_source
    from camat import music_utils

    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setattr(music_utils, "get_download_cache_dir", lambda cache_dir=None: str(shared))

    downloaded = shared / "file.mei"
    calls: list[str] = []

    def fake_get_file_path(file_source: str, **kwargs: object) -> str:
        calls.append(str(kwargs.get("cache_dir")))
        downloaded.write_text("<mei/>", encoding="utf-8")
        return str(downloaded)

    monkeypatch.setattr(music_utils, "get_file_path", fake_get_file_path)
    path = resolve_mei_source(
        "https://example.org/score.mei",
        shared_cache=True,
        fetch=True,
    )
    assert path == downloaded.resolve()
    assert calls == [str(shared)]

