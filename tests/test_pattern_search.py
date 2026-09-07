from __future__ import annotations

import numpy as np
import pytest

from camat.pattern_search import (
    count_kernel_placements,
    pad_for_same,
    run_pattern_search,
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
