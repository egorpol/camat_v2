from __future__ import annotations

import numpy as np
import pytest

from camat.pattern_search import (
    compute_metrics_for_variant,
    convolution_map,
    count_kernel_placements,
    kernel_placement_starts,
    pad_for_same,
    resize_kernel,
    run_pattern_search,
    score_kernel_at,
)


MATRIX = np.array([[1, 0, 1, 0], [0, 1, 0, 1]], dtype=float)
KERNEL = np.array([[1, 0], [0, 1]], dtype=float)


def _overlap(padding: str):
    results, scaled, variant, raw = run_pattern_search(
        MATRIX,
        KERNEL,
        metrics_to_run=["normalized_overlap"],
        backend="none",
        top_n_matches=1,
        padding=padding,
    )
    return results, scaled, variant, raw


def test_valid_padding_keeps_previous_shape() -> None:
    results, scaled, variant, raw = _overlap("valid")
    assert variant is not None
    df = results[variant]["normalized_overlap"]
    assert df.shape == (1, 3)
    assert raw is not None and raw.shape == (1, 3)
    assert list(df.index) == [0]
    assert list(df.columns) == [0, 1, 2]
    assert df.loc[0, 0] == pytest.approx(1.0)
    assert scaled[variant].shape == KERNEL.shape


def test_same_padding_matches_host_shape_and_interior_scores() -> None:
    results_v, _, variant_v, _ = _overlap("valid")
    results_s, _, variant_s, raw_s = _overlap("same")
    df_v = results_v[variant_v]["normalized_overlap"]
    df_s = results_s[variant_s]["normalized_overlap"]
    assert df_s.shape == MATRIX.shape
    assert raw_s is not None and raw_s.shape == MATRIX.shape
    # Host top-left (0, 0) is interior; score matches valid convolution.
    assert df_s.loc[0, 0] == pytest.approx(float(df_v.loc[0, 0]))
    assert -1 in list(df_s.index)
    assert -1 in list(df_s.columns)


def test_count_kernel_placements_valid_and_same() -> None:
    assert count_kernel_placements((2, 4), (2, 2), padding="valid") == (1, 3, 3)
    assert count_kernel_placements((2, 4), (2, 2), padding="same") == (2, 4, 8)
    assert count_kernel_placements((2, 4), (2, 2), padding="valid", stride_x=2) == (1, 2, 2)


def test_pad_for_same_output_size() -> None:
    padded, pad_y, pad_x = pad_for_same(MATRIX, KERNEL)
    assert pad_y == 1 and pad_x == 1
    assert padded.shape == (3, 5)
    assert np.array_equal(padded[1:3, 1:5], MATRIX)


def test_invalid_padding_raises() -> None:
    with pytest.raises(ValueError, match="padding"):
        run_pattern_search(
            MATRIX,
            KERNEL,
            metrics_to_run=["normalized_overlap"],
            backend="none",
            padding="full",
        )


def test_convolution_map_matches_run_pattern_search() -> None:
    for padding in ("valid", "same"):
        scores, rows, cols, meta = convolution_map(MATRIX, KERNEL, padding=padding)
        results, _, variant, _ = _overlap(padding)
        df = results[variant]["normalized_overlap"]
        assert scores.shape == df.shape
        assert np.allclose(scores, df.to_numpy(dtype=float))
        assert len(rows) == scores.shape[0]
        assert len(cols) == scores.shape[1]
        if padding == "valid":
            assert meta["pad_y"] == 0 and meta["pad_x"] == 0
            assert meta["padded_shape"] == MATRIX.shape
        else:
            assert meta["padded_shape"][0] > MATRIX.shape[0]


def test_score_kernel_at_perfect_diagonal() -> None:
    window, product, raw, norm = score_kernel_at(MATRIX, KERNEL, 0, 0)
    assert window.shape == KERNEL.shape
    assert raw == pytest.approx(2.0)
    assert norm == pytest.approx(1.0)
    assert np.array_equal(product, KERNEL)


def test_kernel_placement_starts_valid_and_same() -> None:
    rows, cols = kernel_placement_starts((2, 4), (2, 2), padding="valid")
    assert rows == [0]
    assert cols == [0, 1, 2]
    rows_s, cols_s = kernel_placement_starts((2, 4), (2, 2), padding="same")
    assert rows_s == [0, 1]
    assert cols_s == [0, 1, 2, 3]
    n_row, n_col, n_total = count_kernel_placements((2, 4), (2, 2), padding="same")
    assert (n_row, n_col, n_total) == (len(rows_s), len(cols_s), 8)


def test_resize_kernel_legacy_bilinear_is_explicit() -> None:
    kernel = np.array([[1, 0, 1, 0, 1, 0]], dtype=float)
    # 6 * 0.75 = 4.5 → Python 3 rounds halves to even → 4 columns.
    compressed = resize_kernel(kernel, 1.0, 0.75, method="bilinear")
    assert compressed.shape == (1, 4)
    identity = resize_kernel(kernel, 1.0, 1.0)
    assert np.array_equal(identity, kernel)
    doubled = resize_kernel(kernel, 1.0, 2.0, method="bilinear")
    assert doubled.shape == (1, 12)
    assert doubled[0, 0] == pytest.approx(1.0)
    assert doubled[0, -1] == pytest.approx(0.0)
    # Corner-preserving bilinear is not nearest-neighbour block repeat.
    assert not np.allclose(doubled, np.repeat(kernel, 2, axis=1))


def _bach_motif() -> np.ndarray:
    # Opening V1 motif from the explainer, without parsing/network dependencies.
    kernel = np.zeros((6, 16))
    kernel[0, :8] = 1
    kernel[5, 8:10] = 1
    kernel[3, 10:12] = 1
    kernel[2, 12:] = 1
    return kernel


@pytest.mark.parametrize("scale_y,scale_x", [(1, 2), (2, 1), (2, 2), (3, 2)])
def test_integer_enlargement_repeats_every_cell(scale_y, scale_x) -> None:
    kernel = _bach_motif()
    expected = kernel.repeat(scale_y, axis=0).repeat(scale_x, axis=1)
    enlarged = resize_kernel(kernel, scale_y, scale_x)
    np.testing.assert_array_equal(enlarged, expected)
    assert enlarged.sum() == 16 * scale_y * scale_x
    assert not np.shares_memory(enlarged, kernel)
    np.testing.assert_array_equal(
        resize_kernel(enlarged, 1 / scale_y, 1 / scale_x), kernel
    )


def test_nearest_fractional_resize_and_singleton_axes() -> None:
    # 6 * .75 = 4.5 rounds to 4; output centres select source columns 0,2,3,5.
    kernel = np.array([[1, 0, 1, 0, 1, 0]])
    np.testing.assert_array_equal(resize_kernel(kernel, 1, .75), [[1, 1, 0, 0]])
    # Exact boundary ties select the higher source index, including size 1.
    np.testing.assert_array_equal(resize_kernel(kernel, 1, .01), [[0]])
    np.testing.assert_array_equal(resize_kernel([[1]], 2, 3), np.ones((2, 3)))
    identity = resize_kernel(kernel, 1, 1)
    np.testing.assert_array_equal(identity, kernel)
    assert not np.shares_memory(identity, kernel)


@pytest.mark.parametrize("factor", [0, -1, np.nan, np.inf, -np.inf])
def test_invalid_resize_factors_fail_in_both_entry_points(factor) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        resize_kernel(KERNEL, factor, 1)
    with pytest.raises(ValueError, match="finite and positive"):
        run_pattern_search(
            MATRIX, KERNEL, metrics_to_run=["normalized_overlap"],
            kernel_scale_factors=[factor], backend="none",
        )


@pytest.mark.parametrize("kernel", [[], [1, 0], np.empty((0, 2)), np.ones((1, 1, 1))])
def test_resize_rejects_empty_or_non_matrix_kernel(kernel) -> None:
    with pytest.raises(ValueError, match="nonempty 2D"):
        resize_kernel(kernel, 2, 2)


def test_resize_rejects_unknown_method_even_at_identity() -> None:
    with pytest.raises(ValueError, match="method"):
        resize_kernel(KERNEL, 1, 1, method="typo")


@pytest.mark.parametrize("padding", ["valid", "same"])
@pytest.mark.parametrize("method", ["nearest", "bilinear"])
def test_search_finds_independently_planted_doubled_motif(padding, method) -> None:
    kernel = _bach_motif()
    expected = kernel.repeat(2, axis=0).repeat(2, axis=1)
    # At (2,4), the plant is on both stride lattices, including the same border.
    host = np.zeros((18, 40))
    host[2:14, 4:36] = expected
    results, kernels, key, raw = run_pattern_search(
        host, kernel,
        metrics_to_run=["normalized_overlap", "normalized_cross_correlation"],
        kernel_scale_factors=[2], kernel_scale_axes=["both"],
        kernel_resize_method=method, stride_y=2, stride_x=2,
        padding=padding, backend="none", top_n_matches=0,
    )
    assert results[key]["normalized_overlap"].loc[2, 4] == pytest.approx(1)
    ncc = results[key]["normalized_cross_correlation"].loc[2, 4]
    if method == "nearest":
        np.testing.assert_array_equal(kernels[key], expected)
        assert raw.loc[2, 4] == 64
        assert ncc == pytest.approx(1)
    else:
        # Legacy loses four 1s. Containment alone cannot detect this distortion.
        assert np.count_nonzero(kernels[key] != expected) == 4
        assert raw.loc[2, 4] == 60
        assert ncc < 1


def test_normalized_overlap_allows_extra_host_notes() -> None:
    scores, *_ = convolution_map(np.ones((2, 2)), KERNEL)
    assert scores[0, 0] == 1
    assert not np.array_equal(np.ones((2, 2)), KERNEL)


@pytest.mark.parametrize("padding", ["valid", "same"])
@pytest.mark.parametrize("stride", [(1, 1), (2, 3)])
@pytest.mark.parametrize("weighted", [False, True])
def test_all_metrics_match_direct_window_reference(padding, stride, weighted) -> None:
    rng = np.random.default_rng(31)
    host = (rng.random((7, 11)) > .6).astype(float)
    kernel = rng.random((3, 4)) if weighted else (rng.random((3, 4)) > .6).astype(float)
    names = ["normalized_overlap", "cross_covariance", "normalized_cross_correlation"]
    arrays, _, rows, cols, py, px, work = compute_metrics_for_variant(
        host, kernel, metrics=names, padding=padding,
        stride_y=stride[0], stride_x=stride[1],
    )
    expected = {name: np.zeros((len(rows), len(cols))) for name in names}
    centered_kernel = kernel - kernel.mean()
    for ri, row in enumerate(rows):
        for ci, col in enumerate(cols):
            window = work[row:row + 3, col:col + 4]
            centered_window = window - window.mean()
            cov = (centered_window * centered_kernel).sum()
            denom = np.linalg.norm(centered_window) * np.linalg.norm(centered_kernel)
            expected["normalized_overlap"][ri, ci] = (window * kernel).sum() / kernel.sum()
            expected["cross_covariance"][ri, ci] = cov
            expected["normalized_cross_correlation"][ri, ci] = cov / denom if denom else 0
    for name in names:
        np.testing.assert_allclose(arrays[name], expected[name], atol=1e-12)
    scores, *_ = convolution_map(
        host, kernel, padding=padding, stride_y=stride[0], stride_x=stride[1],
    )
    np.testing.assert_allclose(scores, expected["normalized_overlap"], atol=1e-12)
    raw, *_ = convolution_map(
        host, kernel, padding=padding, stride_y=stride[0], stride_x=stride[1], normalize=False,
    )
    np.testing.assert_allclose(raw, expected["normalized_overlap"] * kernel.sum(), atol=1e-12)


def test_convolution_map_empty_when_kernel_does_not_fit() -> None:
    scores, rows, cols, _ = convolution_map(
        np.ones((2, 2)), np.ones((3, 2)), padding="valid"
    )
    assert scores.shape == (0, 0)
    assert rows == []
    assert cols == []
