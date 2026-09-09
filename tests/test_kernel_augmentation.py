from __future__ import annotations

import numpy as np
import pytest

from camat.pattern_search import resize_kernel, run_pattern_search


@pytest.fixture
def motif():
    kernel = np.zeros((6, 16))
    kernel[0, :8] = 1
    kernel[5, 8:10] = 1
    kernel[3, 10:12] = 1
    kernel[2, 12:] = 1
    return kernel


@pytest.mark.parametrize("method", ["nearest", "bilinear", "area"])
@pytest.mark.parametrize("factor,height,destinations", [(1.5, 9, [0, 8, 4, 3]), (2, 11, [0, 10, 6, 4])])
def test_interval_scaling_moves_each_note_once(motif, method, factor, height, destinations):
    expected = np.zeros((height, 16))
    for dest, source in zip(destinations, [0, 5, 3, 2]):
        expected[dest] = motif[source]
    result = resize_kernel(motif, factor, 1, pitch_mode="intervals", method=method)
    np.testing.assert_array_equal(result, expected)
    assert result.sum() == 16
    np.testing.assert_array_equal(result.sum(axis=0), np.ones(16))


@pytest.mark.parametrize("method", ["nearest", "bilinear", "area"])
def test_fixed_pitch_does_not_move_or_thicken_notes(motif, method):
    result = resize_kernel(motif, 2.5, 1, pitch_mode="fixed", method=method)
    np.testing.assert_array_equal(result, motif)
    assert not np.shares_memory(result, motif)


@pytest.mark.parametrize("rounding,height,row", [("nearest", 9, 4), ("floor", 8, 4), ("ceil", 9, 5)])
def test_pitch_quantization_is_explicit(rounding, height, row):
    kernel = np.zeros((6, 1))
    kernel[3, 0] = 1
    result = resize_kernel(kernel, 1.5, 1, pitch_mode="intervals", rounding=rounding)
    assert result.shape == (height, 1)
    assert result[row, 0] == 1
    assert result.sum() == 1


def test_compressed_pitch_collisions_merge_by_maximum():
    # Source rows 0 and 1 both quantize to row 0; row 2 maps to row 1.
    kernel = np.array([[.4, .1], [.7, .6], [.3, .8]])
    result = resize_kernel(kernel, .5, 1, pitch_mode="intervals")
    np.testing.assert_array_equal(result, [[.7, .6], [.3, .8]])


def test_line_preservation_does_not_remove_chord_tones():
    kernel = np.array([[1, 0], [1, 1], [0, 1]])
    result = resize_kernel(kernel, 2, 1, pitch_mode="intervals", time_mode="events")
    np.testing.assert_array_equal(result, [[1, 0], [0, 0], [1, 1], [0, 0], [0, 1]])
    np.testing.assert_array_equal(result.sum(axis=0), kernel.sum(axis=0))


@pytest.mark.parametrize("rounding", ["nearest", "floor", "ceil"])
@pytest.mark.parametrize("scale_y,scale_x", [(.5, .5), (1.5, .75), (2, 1.5), (2, 2)])
def test_event_scaling_preserves_monophony(motif, rounding, scale_y, scale_x):
    result = resize_kernel(
        motif, scale_y, scale_x, pitch_mode="intervals", time_mode="events",
        method="bilinear", rounding=rounding,
    )
    assert np.all((result == 0) | (result == 1))
    # The input has no rests: common boundary mapping still partitions time.
    np.testing.assert_array_equal(result.sum(axis=0), np.ones(result.shape[1]))


@pytest.mark.parametrize("method", ["bilinear", "area"])
def test_event_mode_avoids_time_interpolation_chord(method):
    kernel = np.eye(2)
    interpolated = resize_kernel(kernel, 1, 1.5, pitch_mode="fixed", method=method)
    np.testing.assert_array_equal(interpolated[:, 1], [.5, .5])
    assert (interpolated[:, 1] >= .5).sum() == 2
    events = resize_kernel(kernel, 1, 1.5, pitch_mode="fixed", time_mode="events")
    np.testing.assert_array_equal(events, [[1, 1, 0], [0, 0, 1]])


def test_event_compression_drops_collapsed_notes_without_extending_them():
    kernel = np.array([[1, 1, 1, 0], [0, 0, 0, 1]])
    result = resize_kernel(kernel, 1, .5, pitch_mode="fixed", time_mode="events")
    np.testing.assert_array_equal(result, [[1, 1], [0, 0]])


@pytest.mark.parametrize("rounding,expected", [
    ("nearest", [[1, 1, 0], [0, 0, 1]]),
    ("floor", [[1, 0, 0], [0, 1, 1]]),
    ("ceil", [[1, 1, 0], [0, 0, 1]]),
])
def test_event_rounding_controls_shared_note_boundary(rounding, expected):
    result = resize_kernel(np.eye(2), 1, 1.5, pitch_mode="fixed", time_mode="events", rounding=rounding)
    np.testing.assert_array_equal(result, expected)


def test_event_mode_preserves_rests_and_separated_runs():
    result = resize_kernel([[1, 0, 1]], 1, 2, pitch_mode="fixed", time_mode="events")
    np.testing.assert_array_equal(result, [[1, 1, 0, 0, 1, 1]])


def test_area_sampling_retains_fractional_coverage_of_short_notes():
    kernel = np.array([[1, 0, 0, 0]])
    np.testing.assert_array_equal(resize_kernel(kernel, 1, .5), [[0, 0]])
    np.testing.assert_allclose(resize_kernel(kernel, 1, .5, method="area"), [[.5, 0]])
    np.testing.assert_allclose(resize_kernel([[1, 0, 1]], 1, 2/3, method="area"), [[2/3, 2/3]])


def test_area_resize_repeats_at_integer_scales_and_preserves_mean_coverage(motif):
    np.testing.assert_array_equal(resize_kernel(motif, 2, 2, method="area"), motif.repeat(2, 0).repeat(2, 1))
    resized = resize_kernel(motif, .75, 1.5, method="area")
    assert resized.mean() == pytest.approx(motif.mean())


@pytest.mark.parametrize("pitch_mode", ["fixed", "intervals", "stretch"])
def test_one_pitch_and_one_time_cell_are_well_defined(pitch_mode):
    result = resize_kernel([[1]], 2, 2, pitch_mode=pitch_mode, time_mode="events")
    np.testing.assert_array_equal(result, np.ones((2 if pitch_mode == "stretch" else 1, 2)))


@pytest.mark.parametrize("padding", ["valid", "same"])
def test_search_finds_planted_interval_and_time_augmentation(motif, padding):
    expected = np.zeros((11, 32))
    expected[0, :16] = 1
    expected[10, 16:20] = 1
    expected[6, 20:24] = 1
    expected[4, 24:] = 1
    host = np.zeros((15, 38))
    host[2:13, 3:35] = expected
    results, kernels, key, raw = run_pattern_search(
        host, motif, metrics_to_run=["normalized_overlap", "normalized_cross_correlation"],
        kernel_scale_factors=[2], kernel_scale_axes=["both"],
        kernel_pitch_mode="intervals", kernel_time_mode="events", kernel_rounding="floor",
        kernel_resize_method="area", padding=padding, backend="none", top_n_matches=0,
    )
    assert "pitch=intervals, time=events, method=area, rounding=floor" in key
    np.testing.assert_array_equal(kernels[key], expected)
    assert raw.loc[2, 3] == 32
    assert results[key]["normalized_overlap"].loc[2, 3] == 1
    assert results[key]["normalized_cross_correlation"].loc[2, 3] == pytest.approx(1)


def test_search_can_keep_area_weights_or_threshold_them():
    kernel = np.array([[1, 0, 0, 0]])
    host = np.array([[1, 0]])
    for binarize, expected in [(False, [[.5, 0]]), (True, [[1, 0]])]:
        results, kernels, key, raw = run_pattern_search(
            host, kernel, metrics_to_run=["normalized_overlap"],
            kernel_scale_factors=[.5], kernel_resize_method="area",
            kernel_pitch_mode="fixed", binarize_scaled_kernel=binarize,
            backend="none", top_n_matches=0,
        )
        np.testing.assert_allclose(kernels[key], expected)
        assert results[key]["normalized_overlap"].iloc[0, 0] == 1
        assert raw.iloc[0, 0] == expected[0][0]


@pytest.mark.parametrize("option", ["pitch_mode", "time_mode", "rounding"])
def test_invalid_policy_rejected_by_resize_and_search(option):
    with pytest.raises(ValueError, match=option):
        resize_kernel([[1]], 1, 1, **{option: "typo"})
    with pytest.raises(ValueError, match=option):
        run_pattern_search(
            [[1]], [[1]], metrics_to_run=["normalized_overlap"],
            backend="none", **{"kernel_" + option: "typo"},
        )


def test_events_rejects_soft_values_even_at_identity():
    with pytest.raises(ValueError, match="binary"):
        resize_kernel([[.5]], 1, 1, time_mode="events")


@pytest.mark.parametrize("value", [np.nan, np.inf, -1])
def test_invalid_weights_rejected(value):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        resize_kernel([[value]], 1, 1)
