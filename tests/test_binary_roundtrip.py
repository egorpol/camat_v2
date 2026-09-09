import numpy as np
import pandas as pd
import pytest

from camat.binary_roundtrip import (
    audit_binary_roundtrip, compare_binary_resolutions, compare_voice_roundtrips,
    describe_binary_span_sources, make_roundtrip_example,
    prepare_binary_timeline, split_binary_voices, find_binary_matches,
    binary_match_sources, plot_binary_comparison, plot_binary_search_trace,
    extract_binary_kernel, rank_binary_matches,
)
from camat.music_utils import (
    binary_matrix_to_df_from_meta, create_binary_matrix, create_binary_matrix_bundle,
    get_binary_cell_provenance, round_trip_sanity_check,
)


def notes(rows):
    return pd.DataFrame(rows, columns=["MIDI", "Global Onset", "Duration"])


def test_grid_ends_at_latest_note_end_and_snaps_decimal_boundaries():
    matrix, meta = create_binary_matrix(
        notes([(60, 0, 2), (62, 3, 0.3)]),
        resolution_method="manual", manual_resolution=0.1,
    )
    assert matrix.shape == (3, 33)
    assert meta["total_duration"] == 3.3
    assert matrix[0].sum() == 20
    assert matrix[2].sum() == 3
    assert np.flatnonzero(matrix[2]).tolist() == [30, 31, 32]


def test_negative_time_is_clipped_and_zero_duration_does_not_add_cells():
    bundle = create_binary_matrix_bundle(
        notes([(60, -1, 2), (61, -2, 1), (62, 0.5, 0), (60, 2, 0.5)]),
        resolution_method="manual", manual_resolution=0.5,
    )
    np.testing.assert_array_equal(bundle.matrix[0], [1, 1, 0, 0, 1])
    assert not bundle.matrix[1:].any()
    assert get_binary_cell_provenance(bundle.meta, 0, 0)["source_count"] == 1


@pytest.mark.parametrize("resolution", [float("nan"), float("inf"), 0, -1])
def test_resolution_must_be_finite_and_positive(resolution):
    with pytest.raises(ValueError, match="finite positive"):
        create_binary_matrix(notes([(60, 0, 1)]), resolution_method="manual", manual_resolution=resolution)


@pytest.mark.parametrize("row", [(60, 0, -1), (60, float("nan"), 1), (60, 0, float("inf"))])
def test_invalid_note_times_are_rejected(row):
    with pytest.raises(ValueError):
        create_binary_matrix(notes([row]))


def test_explicit_measure_offsets_override_display_name_lookup():
    df = notes([(60, 0, 1)])
    results = [{"name": "parsed", "measure_offsets": [0, 4]}]
    bundle = create_binary_matrix_bundle(df, source_name="display", results=results, measure_offsets=[0, 3])
    assert bundle.measure_offsets == [0.0, 3.0]
    assert bundle.slice().measure_offsets == [0.0, 3.0]
    assert create_binary_matrix_bundle(df, source_name="parsed", results=results).measure_offsets == [0, 4]
    assert create_binary_matrix_bundle(df, source_name="parsed", results=results, measure_offsets=[]).measure_offsets == []


def test_slice_bounds_match_actual_array_even_beyond_edges():
    bundle = create_binary_matrix_bundle(notes([(60, 0, 1), (62, 1, 1)]))
    empty = bundle.slice(row_start=99, col_start=99)
    assert (empty.row_start, empty.row_end, empty.col_start, empty.col_end) == (3, 3, 2, 2)
    assert empty.matrix_slice.shape == (0, 0)
    clipped = bundle.slice(row_start=-3, col_start=-4, n_rows=99, n_cols=99)
    np.testing.assert_array_equal(clipped.matrix_slice, bundle.matrix)


@pytest.mark.parametrize("row_order", ["low_to_high", "high_to_low"])
@pytest.mark.parametrize("y_mode", ["minmax", "full"])
def test_roundtrip_distinguishes_cell_equality_from_event_loss(row_order, y_mode):
    bundle = create_binary_matrix_bundle(
        make_roundtrip_example(), resolution_method="manual", manual_resolution=0.25,
        row_order=row_order, y_mode=y_mode,
    )
    audit = audit_binary_roundtrip(bundle)
    assert audit["grid_equal"]
    assert audit["changed_cells"] == 0
    assert not audit["events_equal"]
    assert audit["source_notes"] == 9
    assert audit["reconstructed_spans"] == 6
    assert audit["unchanged_events"] == 4
    assert set(bundle.reconstructed_df.columns) == {"MIDI", "Global Onset", "Duration"}


def test_chroma_has_class_spans_and_octave_provenance_but_no_midi_decode():
    bundle = create_binary_matrix_bundle(make_roundtrip_example(), y_mode="chroma", manual_resolution=0.25,
                                         resolution_method="manual", row_order="high_to_low")
    assert bundle.reconstructed_df is None
    assert "MIDI" not in bundle.decoded_df
    info = get_binary_cell_provenance(bundle.meta, 11, 6, as_dataframe=True)
    assert set(info["source_df"]["MIDI"]) == {60, 72}
    assert audit_binary_roundtrip(bundle)["events_equal"] is None
    with pytest.raises(ValueError, match="Chroma"):
        binary_matrix_to_df_from_meta(bundle.matrix, bundle.meta)


def test_resolution_auto_can_miss_onset_grid_and_merge_rests():
    report, bundles = compare_binary_resolutions(make_roundtrip_example())
    assert report.loc["auto (min duration)", "resolution_QL"] == 0.5
    assert report.loc["auto (min duration)", "max_onset_error_QL"] == 0.25
    assert report.loc["0.25 QL", "max_onset_error_QL"] == 0
    assert report.loc["0.25 QL", "max_end_error_QL"] == 0
    assert report.loc["0.5 QL", "occupied_pitch_QL"] > report.loc["0.25 QL", "occupied_pitch_QL"]
    assert report["grid_equal"].all()
    voices = compare_voice_roundtrips(bundles["0.25 QL"])
    assert voices.loc["echo", "events_equal"]
    assert not voices.loc["upper", "events_equal"]  # repeated pitches still merge within one voice


def test_grid_audit_handles_trailing_silence_and_empty_edited_grid():
    bundle = create_binary_matrix_bundle(notes([(60, 0, 2)]), resolution_method="manual", manual_resolution=0.1)
    bundle.matrix[:, 15:] = 0
    assert audit_binary_roundtrip(bundle)["grid_equal"]
    bundle.matrix[:] = 0
    audit = audit_binary_roundtrip(bundle)
    assert audit["grid_equal"] and audit["reconstructed_spans"] == 0
    assert not audit["events_equal"]


def test_sanity_check_compares_events_without_requiring_source_attributes():
    df = notes([(60, 0, 0.5), (62, 0.5, 1)])
    df["xml_id"] = ["a", "b"]
    df["Voice"] = "soprano"
    ok, reconstructed = round_trip_sanity_check(df)
    assert ok
    assert set(reconstructed) == {"MIDI", "Global Onset", "Duration"}


def test_span_sources_explain_merging_and_retain_original_identifiers():
    bundle = create_binary_matrix_bundle(make_roundtrip_example(), resolution_method="manual", manual_resolution=0.25)
    spans = describe_binary_span_sources(bundle)
    assert spans["source_count"].sum() == 9
    merged = spans[spans["source_count"] > 1]
    assert len(merged) == 3
    unison = merged[merged["MIDI"] == 60].iloc[0]
    assert unison["source_xml_ids"] == ["toy-0", "toy-1"]
    assert unison["source_voices"] == ["lower", "echo"]


def test_reconstructed_events_render_as_new_notation(monkeypatch):
    from xml.etree import ElementTree as ET
    from camat import music21_render

    monkeypatch.setattr(music21_render, "display", lambda *_: None)
    # Reproduce the preceding use of an MEI toolkit in a notebook session.
    import verovio
    original_toolkit = verovio.toolkit()
    original_toolkit.setInputFrom("mei")
    bundle = create_binary_matrix_bundle(make_roundtrip_example(), resolution_method="manual", manual_resolution=0.25)
    score = music21_render.df_to_music21(bundle.reconstructed_df)
    xml = music21_render.music21_to_musicxml_string(score)
    mei, pages = music21_render.render_with_verovio_from_musicxml(xml)
    root = ET.fromstring(mei)
    assert root.findall(".//{http://www.music-encoding.org/ns/mei}note")
    assert pages and all("<svg" in page for page in pages)
    assert "toy-0" not in mei


def test_failed_musicxml_import_does_not_silently_return_empty_render(monkeypatch):
    from unittest.mock import Mock
    from camat import music21_render

    toolkit = Mock()
    toolkit.loadData.return_value = False
    monkeypatch.setattr(music21_render.verovio, "toolkit", lambda: toolkit)
    with pytest.raises(ValueError, match="could not load"):
        music21_render.render_with_verovio_from_musicxml("rejected input")


def test_toy_mei_preserves_every_event_voice_and_source_id():
    from pathlib import Path
    from camat import parse_files

    path = Path(__file__).resolve().parents[1] / "camat/examples/binary_roundtrip_voices.mei"
    results, _, _ = parse_files([str(path)], backend="none", include_xml_ids=True,
                                display_preview_df_pitch=False, display_preview_df_events=False,
                                quiet_native_warnings=True)
    actual = results[0]["df_pitch"].set_index("xml_id").sort_index()
    expected = make_roundtrip_example().set_index("xml_id").sort_index()
    assert actual.index.tolist() == expected.index.tolist()
    np.testing.assert_allclose(actual[["MIDI", "Global Onset", "Duration"]].to_numpy(float),
                               expected[["MIDI", "Global Onset", "Duration"]].to_numpy(float))
    assert actual["Voice"].str.split(" - ").str[0].str.lower().tolist() == expected["Voice"].tolist()


def test_pickup_notes_and_measure_lines_share_rebased_origin():
    source = notes([(60, -1, 0.5), (62, -0.5, 0.5), (64, 0, 1)])
    original = source.copy(deep=True)
    rebased, offsets, origin = prepare_binary_timeline(source, [-1, 0, 4])
    assert origin == -1
    assert offsets == [0, 1, 5]
    assert rebased["Global Onset"].tolist() == [0, 0.5, 1]
    assert rebased["Source Global Onset"].tolist() == [-1, -0.5, 0]
    pd.testing.assert_frame_equal(source, original)
    bundle = create_binary_matrix_bundle(rebased, measure_offsets=offsets, manual_resolution=0.5, resolution_method="manual")
    assert bundle.matrix.sum() == 4
    assert audit_binary_roundtrip(bundle)["events_equal"]


@pytest.mark.parametrize("order", ["high_to_low", "low_to_high"])
def test_voice_search_cannot_assemble_melody_across_voices(order):
    bundle = create_binary_matrix_bundle(make_roundtrip_example(), resolution_method="manual",
                                         manual_resolution=0.25, row_order=order)
    voices = split_binary_voices(bundle)
    assert all(v.matrix.shape == bundle.matrix.shape for v in voices.values())
    np.testing.assert_array_equal(np.maximum.reduce([v.matrix for v in voices.values()]), bundle.matrix)
    kernel = np.array([[0, 0, 1, 1], [0, 0, 0, 0], [1, 1, 0, 0]])
    if order == "low_to_high":
        kernel = kernel[::-1]
    merged = find_binary_matches(bundle, kernel)
    assert merged["matches"].iloc[0]["score"] == 1.0
    for voice in voices.values():
        assert find_binary_matches(voice, kernel)["matches"].iloc[0]["score"] == 0.5
    hit = merged["matches"].iloc[0]
    trace = binary_match_sources(bundle, kernel, hit["row"], hit["col"])
    assert trace["score"] == hit["score"] and not trace["missing_cells"]
    assert set(trace["matched_notes"]["xml_id"]) == {"toy-0", "toy-3"}
    assert "toy-2" in set(trace["window_notes"]["xml_id"])  # the earlier D4 is not required by the query


@pytest.mark.parametrize("order", ["high_to_low", "low_to_high"])
def test_musical_plot_pitch_and_window_geometry_agree(order):
    from matplotlib import pyplot as plt
    from camat.music_utils import plot_binary_matrix

    bundle = create_binary_matrix_bundle(notes([(60, 0, 1), (62, 1, 1)]), row_order=order)
    fig = plot_binary_comparison({"test": bundle})
    assert fig.axes[0].get_ylim() == (59.5, 62.5)
    plt.close(fig)
    window = bundle.slice(row_start=0, n_rows=1, n_cols=1)
    fig = window.plot(backend="plt", show=False)
    # The plotting API returns a figure for both backends.
    ax = fig.axes[0]
    assert list(ax.images[0].get_extent()) == [0, 2.0, 59.5, 62.5]
    expected_midi = bundle.meta["row_axis_values"][0]
    assert ax.patches[0].get_y() == expected_midi - 0.5
    plt.close(fig)
    bokeh_plot = window.plot(backend="bokeh", show=False, hover_fields=["row", "midi"])
    assert (bokeh_plot.y_range.start, bokeh_plot.y_range.end) == (59.5, 62.5)
    hover = next(renderer.data_source.data for renderer in bokeh_plot.renderers
                 if hasattr(renderer, "data_source") and "midi" in renderer.data_source.data)
    assert sorted(hover["y"]) == [60.0, 62.0]


def test_search_preserves_source_time_and_handles_oversize_kernel():
    bundle = create_binary_matrix_bundle(notes([(60, 0, 1)]))
    bundle.meta["source_time_origin"] = -1
    result = find_binary_matches(bundle, np.ones((1, 1)))
    assert result["matches"].iloc[0]["source_onset_QL"] == -1
    assert find_binary_matches(bundle, np.ones((2, 2)))["matches"].empty
    with pytest.raises(ValueError, match="active cell"):
        find_binary_matches(bundle, np.zeros((1, 1)))


@pytest.mark.parametrize("order", ["high_to_low", "low_to_high"])
def test_extraction_includes_sustains_preserves_rests_and_retains_origin(order):
    bundle = create_binary_matrix_bundle(
        make_roundtrip_example(), resolution_method="manual", manual_resolution=0.25,
        row_order=order, y_mode="full",
    )
    voice = split_binary_voices(bundle)["lower"]
    extracted = extract_binary_kernel(voice, 0.6, 3.5)
    assert extracted["grid_span_QL"] == (0.5, 3.5)
    assert extracted["col"] == 2
    kernel = extracted["kernel"]
    assert kernel.shape == (5, 12)
    assert kernel[:, 0].sum() == 1  # C4 started before the requested window
    assert not kernel[:, -2:].any()  # preserve its final half-QL of silence
    row = extracted["row"]
    np.testing.assert_array_equal(kernel, voice.matrix[row:row+5, 2:14])
    trace = binary_match_sources(voice, kernel, row, 2)
    assert set(trace["matched_notes"]["xml_id"]) == {"toy-0", "toy-5"}
    kernel[:] = 0  # extraction is an independent copy
    assert voice.matrix.any()
    with pytest.raises(ValueError, match="no active"):
        extract_binary_kernel(voice, 3.0, 3.5)


@pytest.mark.parametrize("order", ["high_to_low", "low_to_high"])
def test_rank_maps_use_stride_labels_and_metric_specific_plot_scale(order):
    from matplotlib import pyplot as plt
    from camat.pattern_search import run_pattern_search

    bundle = create_binary_matrix_bundle(
        notes([(60, 0, 2), (64, 3, 1)]), row_order=order,
        resolution_method="manual", manual_resolution=0.25,
    )
    bundle.meta["source_time_origin"] = -1
    kernel = np.array([[1, 0], [0, 1]])
    all_maps, _, key, _ = run_pattern_search(
        bundle.matrix, kernel, metrics_to_run=["normalized_cross_correlation"],
        stride_x=3, stride_y=2, backend="none", top_n_matches=0,
    )
    metric = "normalized_cross_correlation"
    frame = all_maps[key][metric]
    result = rank_binary_matches(bundle, kernel, frame, metric=metric)
    for hit in result["matches"].itertuples():
        assert frame.loc[hit.row, hit.col] == hit.score
        assert hit.row % 2 == 0 and hit.col % 3 == 0
        assert hit.source_onset_QL == hit.col * 0.25 - 1
    fig = plot_binary_search_trace(bundle, kernel, result)
    assert fig.axes[1].images[0].get_clim() == (-1, 1)
    extent = fig.axes[1].images[0].get_extent()
    assert extent[0] == -0.375  # half of the actual 3-column stride
    plt.close(fig)


def test_rank_filters_near_duplicate_windows_and_source_time_not_heatmap():
    bundle = create_binary_matrix_bundle(notes([(60, 0, 12)]), resolution_method="manual", manual_resolution=1)
    frame = pd.DataFrame([[1, 1, 0.99, 0.98, 0.97, 0.96, 0.95, np.nan, 0.93]])
    kernel = np.ones((1, 4))
    raw = rank_binary_matches(bundle, kernel, frame, top_n=3)
    assert raw["matches"]["col"].tolist() == [0, 1, 2]
    filtered = rank_binary_matches(bundle, kernel, frame, top_n=3, max_window_iou=0.5,
                                   min_score=0.94, exclude_time_span=(0, 4))
    assert filtered["matches"]["col"].tolist() == [4, 6]
    np.testing.assert_array_equal(filtered["scores"], frame.to_numpy())
    assert rank_binary_matches(bundle, kernel, frame, min_score=1.1)["matches"].empty
    with pytest.raises(ValueError, match="padding='valid'"):
        rank_binary_matches(bundle, kernel, frame.rename(columns={0: -1}))
