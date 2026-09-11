import numpy as np
import pandas as pd
import pytest

from camat.binary_query import (search_binary_query, rank_query_matches, plot_query_heatmaps,
                                plot_binary_query_match, plot_query_loss_examples)
from camat.binary_roundtrip import binary_match_sources, plot_matched_source, plot_matched_sources
from camat.binary_convolution import binary_score_details
from camat.music_utils import create_binary_matrix_bundle
from camat.pattern_search import compute_metrics_for_variant


def bundle(notes, mode, order="high_to_low", resolution=0.25):
    return create_binary_matrix_bundle(notes, y_mode=mode, row_order=order,
                                       resolution_method="manual", manual_resolution=resolution,
                                       include_provenance=True)


def progression(start=0, shift=0, revoice=False):
    rows = []
    for chord, pitches in enumerate([(62, 66, 69), (57, 61, 64), (62, 66, 69)]):
        for voice, pitch in enumerate(pitches):
            rows.append((pitch + shift + ([12, -12, 24][voice] if revoice else 0),
                         start + chord, 1, f"voice-{voice}", f"note-{start}-{chord}-{voice}"))
    return pd.DataFrame(rows, columns=["MIDI", "Global Onset", "Duration", "Voice", "xml_id"])


@pytest.mark.parametrize("order", ["high_to_low", "low_to_high"])
def test_chroma_revoicing_transposition_and_provenance_across_octaves(order):
    query_notes = progression()
    host_notes = pd.concat([progression(4, revoice=True), progression(8, shift=2, revoice=True)], ignore_index=True)
    # An octave doubling contributes another source ID to the same class cell.
    doubled = host_notes.iloc[[0]].copy()
    doubled["MIDI"] += 12
    doubled["xml_id"] = "octave-double"
    host_notes = pd.concat([host_notes, doubled], ignore_index=True)
    host = bundle(host_notes, "chroma", order)
    query = bundle(query_notes, "chroma", "low_to_high" if order == "high_to_low" else "high_to_low")
    result = search_binary_query(host, query, transpositions=[0, 12, 2, -10], max_time_iou=None)
    assert list(result["maps"].index) == [(1.0, 0), (1.0, 2)]
    assert result["maps"].loc[(1.0, 0), 16] == 1
    assert result["maps"].loc[(1.0, 2), 32] == 1
    trace = binary_match_sources(host, result["variants"][(1.0, 0)]["kernel"], 0, 16)
    assert len(trace["matched_notes"]) == 10
    assert "octave-double" in set(trace["matched_notes"]["xml_id"])
    assert not trace["missing_cells"]
    # The same pitch classes do not satisfy the specified absolute MIDI voicing.
    midi_result = search_binary_query(bundle(host_notes, "full", order), bundle(query_notes, "minmax", order))
    assert midi_result["maps"].loc[(1.0, 0), 16] < 1


def test_midi_explicit_transposition_scale_stride_and_source_times():
    source = progression(2, shift=2)
    source["Global Onset"] = (source["Global Onset"]-2)*2+2
    source["Duration"] *= 2
    host = bundle(source, "full")
    host.meta["source_time_origin"] = -1
    query = bundle(progression(), "minmax", "low_to_high")
    result = search_binary_query(host, query, time_scales=[1, 2], transpositions=[0, 2], stride_x=2)
    hit = result["matches"].iloc[0]
    assert hit["score"] == 1
    assert (hit["time_scale"], hit["transpose_semitones"], hit["col"]) == (2, 2, 8)
    assert (hit["grid_onset_QL"], hit["grid_end_QL"]) == (2, 8)
    assert (hit["source_onset_QL"], hit["source_end_QL"]) == (1, 7)
    assert all(int(col) % 2 == 0 for col in result["maps"].columns)


def test_empty_filtered_results_and_skipped_variants_preserve_maps():
    host = bundle(progression(), "minmax")
    query = bundle(progression(), "minmax")
    result = search_binary_query(host, query, time_scales=[0.01, 1, 20], transpositions=[0, 100], min_score=1.1)
    assert result["matches"].empty and not result["maps"].empty
    assert set(result["skipped"]["reason"]) == {"empty after quantization", "longer than host", "outside host MIDI register"}
    all_skipped = search_binary_query(host, query, time_scales=[20])
    assert all_skipped["maps"].empty and all_skipped["matches"].empty


@pytest.mark.parametrize("metric", ["normalized_overlap", "normalized_cross_correlation", "cross_covariance"])
def test_full_placement_pool_and_loss_counts_are_independent_of_shortlist_and_metric(metric):
    host = bundle(progression(1).iloc[1:], "minmax")
    query = bundle(progression(), "minmax")
    result = search_binary_query(host, query, metric=metric, time_scales=[0.5, 1], min_score=1e9)
    assert result["matches"].empty
    pool = result["placements"]
    assert len(pool) == np.isfinite(result["maps"].to_numpy()).sum()
    for hit in pool.itertuples():
        kernel = result["variants"][(hit.time_scale, hit.transpose_semitones)]["kernel"]
        actual = host.matrix[hit.row:hit.row+kernel.shape[0], hit.col:hit.col+kernel.shape[1]]
        assert hit.required_cells == kernel.sum()
        assert hit.shared_cells == (kernel * actual).sum()
        assert hit.missing_cells == np.count_nonzero((kernel == 1) & (actual == 0))
        assert hit.loss_fraction == pytest.approx(1 - hit.overlap)
        if metric == "normalized_overlap":
            assert hit.loss_fraction == pytest.approx(1 - hit.score)
    reranked = rank_query_matches(pool, min_score=None, top_n=3, max_time_iou=0.25)
    direct = search_binary_query(host, query, metric=metric, time_scales=[0.5, 1], top_n=3, max_time_iou=0.25)
    pd.testing.assert_frame_equal(reranked, direct["matches"])


def test_query_ranking_threshold_inclusion_uncapped_counts_and_time_suppression():
    pool = pd.DataFrame({"score": [1, 0.9, 2/3, 0.5, 0],
                         "grid_onset_QL": [0, 0.25, 2, 4, 6],
                         "grid_end_QL": [1, 1.25, 3, 5, 7]})
    before = pool.copy()
    assert len(rank_query_matches(pool, top_n=None, max_time_iou=None)) == 5
    assert len(rank_query_matches(pool, min_score=2/3, max_time_iou=None)) == 3
    assert len(rank_query_matches(pool, min_score=2/3, max_time_iou=0.25)) == 2
    assert len(rank_query_matches(pool, min_score=0.667, max_time_iou=0.25)) == 1
    kept = rank_query_matches(pool, top_n=None, max_time_iou=0.25)
    for threshold in [0, 0.5, 2/3, 1]:
        pd.testing.assert_frame_equal(kept[kept.score >= threshold].reset_index(drop=True),
                                      rank_query_matches(pool, min_score=threshold, max_time_iou=0.25))
    pd.testing.assert_frame_equal(pool, before)
    with pytest.raises(ValueError, match="top_n"):
        rank_query_matches(pool, top_n=0)


def test_loss_examples_use_actual_cells_and_reject_mixed_variants():
    from matplotlib import pyplot as plt
    host = bundle(progression(1), "chroma")
    result = search_binary_query(host, bundle(progression(), "chroma"), time_scales=[0.5, 1], top_n=None)
    examples = result["placements"].query("time_scale == 1").iloc[[0, -1]]
    fig = plot_query_loss_examples(host, result, examples)
    for ax, hit in zip(fig.axes[1:], examples.itertuples()):
        categories = ax.images[0].get_array()
        assert np.count_nonzero(categories == 1) == hit.shared_cells
        assert np.count_nonzero(categories == 2) == hit.missing_cells
    plt.close(fig)
    with pytest.raises(ValueError, match="one time scale"):
        plot_query_loss_examples(host, result, result["placements"])


def test_query_rejects_incompatible_axes_and_resolution():
    notes = progression()
    with pytest.raises(ValueError, match="both use"):
        search_binary_query(bundle(notes, "chroma"), bundle(notes, "minmax"))
    with pytest.raises(ValueError, match="same time resolution"):
        search_binary_query(bundle(notes, "chroma"), bundle(notes, "chroma", resolution=0.5))
    with pytest.raises(ValueError, match="integer semitones"):
        search_binary_query(bundle(notes, "chroma"), bundle(notes, "chroma"), transpositions=[0.5])


@pytest.mark.parametrize("order", ["high_to_low", "low_to_high"])
def test_all_midi_positions_equal_full_matrix_search(order):
    # The query's original register is outside this host; an unconstrained
    # placement must still discover the uniformly transposed copy.
    host = bundle(progression(2, shift=-24), "minmax", order)
    query = bundle(progression(), "full", "low_to_high")
    result = search_binary_query(host, query, transpositions="all", stride_x=2, max_time_iou=None)
    assert result["matches"].iloc[0]["transpose_semitones"] == -24
    assert result["matches"].iloc[0]["score"] == 1
    # Widen the host so row enumeration and opposite row orders are exercised.
    host = bundle(pd.concat([progression(2, shift=-24), progression(6, shift=-17)]), "minmax", order)
    result = search_binary_query(host, query, transpositions="all", stride_x=2, max_time_iou=None)
    kernel = next(iter(result["variants"].values()))["kernel"]
    arrays, _, rows, cols, *_ = compute_metrics_for_variant(host.matrix, kernel, metrics=["normalized_overlap"], stride_x=2)
    assert len(result["maps"]) == host.matrix.shape[0] - kernel.shape[0] + 1
    for key, variant in result["variants"].items():
        row = variant["row"]
        np.testing.assert_allclose(result["maps"].loc[key].to_numpy(), arrays["normalized_overlap"][list(rows).index(row)])
    assert result["maps"].loc[(1, -24), 8] == 1
    assert result["maps"].loc[(1, -17), 24] == 1
    assert list(result["maps"].columns) == list(cols)
    # Original-pitch placements are a subset of the moving-MIDI search.
    fixed = search_binary_query(host, query, transpositions=[-24], stride_x=2)
    np.testing.assert_allclose(fixed["maps"].loc[(1, -24)], result["maps"].loc[(1, -24)])


def test_all_transpositions_chroma_and_too_tall_midi():
    query = bundle(progression(), "chroma")
    result = search_binary_query(bundle(progression(2, shift=5, revoice=True), "chroma"), query, transpositions="all")
    assert set(result["maps"].index.get_level_values(1)) == set(range(12))
    assert result["matches"].iloc[0]["transpose_semitones"] == 5
    assert result["matches"].iloc[0]["score"] == 1
    narrow = bundle(progression().query('MIDI == 62'), "minmax")
    result = search_binary_query(narrow, bundle(progression(), "minmax"), transpositions="all")
    assert result["maps"].empty and result["matches"].empty
    assert set(result["skipped"]["reason"]) == {"taller than host MIDI register"}


def test_all_hits_plots_preserve_membership_and_aggregate_only_display():
    from matplotlib import pyplot as plt
    from matplotlib.colors import to_rgba
    host = bundle(progression(), "full")
    result = search_binary_query(host, bundle(progression(), "minmax"), transpositions=[0, 7], max_time_iou=None)
    before = result["maps"].copy()
    traces = [binary_match_sources(host, result["variants"][(hit.time_scale, hit.transpose_semitones)]["kernel"], hit.row, hit.col)
              for hit in result["matches"].itertuples()]
    colors = ["#0072b2", "#d55e00"]
    piano = plot_matched_sources(host, traces, colors=colors)
    assert len(piano.axes[0].patches) == len(host.source_df) + len(traces)
    assert len(piano.axes[0].texts) == len(traces)
    for patch, color in zip(piano.axes[0].patches[-len(traces):], colors):
        assert patch.get_facecolor() == to_rgba(color, 0.2)
    assert any(patch.get_facecolor() == to_rgba("#595959", 0.95) for patch in piano.axes[0].patches[:len(host.source_df)])
    heat = plot_query_heatmaps({"all": result}, 0.25, rank=None, aggregate_transpositions=True, colors=colors)
    assert len(heat.axes[0].texts) == len(result["matches"])
    np.testing.assert_allclose(heat.axes[0].images[0].get_array(), before.groupby(level="time_scale").max())
    pd.testing.assert_frame_equal(before, result["maps"])
    plt.close(piano)
    plt.close(heat)


@pytest.mark.parametrize("case, expected", [("exact", (4, 0, 0, 1, 1)), ("extra", (4, 4, 0, 1, 0.5)),
                                             ("missing", (3, 0, 1, 0.75, np.sqrt(2/3)))])
def test_score_explanations_reproduce_search_math(case, expected):
    k = np.array([[1, 1, 0, 0], [0, 0, 0, 0], [0, 0, 1, 1]])
    w = k.copy()
    if case == "extra":
        w[1, :] = 1
    elif case == "missing":
        w[2, -1] = 0
    details = binary_score_details(k, w)
    assert tuple(details[key] for key in ["shared", "extra", "missing"]) == expected[:3]
    assert details["normalized_overlap"] == expected[3]
    assert details["normalized_cross_correlation"] == pytest.approx(expected[4])
    metrics = ["normalized_overlap", "normalized_cross_correlation", "cross_covariance"]
    arrays, *_ = compute_metrics_for_variant(w, k, metrics=metrics)
    for metric in metrics:
        assert details[metric] == pytest.approx(arrays[metric][0, 0])
    assert details["cells"]["centered product"].sum() == pytest.approx(details["cross_covariance"])
    constant = binary_score_details(np.ones((1, 2)), np.ones((1, 2)))
    assert constant["normalized_cross_correlation"] == 0


@pytest.mark.parametrize("mode", ["full", "chroma"])
def test_trace_plot_uses_correct_source_window_and_visible_fill(mode):
    from matplotlib import pyplot as plt
    notes = progression()
    host = bundle(notes, mode)
    query = bundle(notes, mode)
    result = search_binary_query(host, query)
    hit = result["matches"].iloc[0]
    variant = result["variants"][(hit["time_scale"], hit["transpose_semitones"])]
    trace = binary_match_sources(host, variant["kernel"], hit["row"], hit["col"])
    piano = plot_matched_source(host, trace)
    rectangle = piano.axes[0].patches[-1]
    assert rectangle.get_x() == 0 and rectangle.get_width() == 3
    assert rectangle.get_y() == notes["MIDI"].min() - 0.5
    assert rectangle.get_facecolor()[3] == pytest.approx(0.2)
    assert piano.axes[0].patches[0].get_alpha() == 0.95
    plt.close(piano)
    plt.close(plot_query_heatmaps({mode: result}, 0.25))
    plt.close(plot_binary_query_match(host, result))
