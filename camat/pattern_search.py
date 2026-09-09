from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


__all__ = [
    "resize_kernel",
    "pad_for_same",
    "kernel_placement_starts",
    "count_kernel_placements",
    "score_kernel_at",
    "convolution_map",
    "summarize_best",
    "top_matches",
    "apply_threshold",
    "finite_bounds",
    "plot_matplotlib_single",
    "plot_bokeh_single",
    "plot_kernel",
    "build_scale_variants",
    "compute_metrics_for_variant",
    "run_pattern_search",
]


def _augmentation_options(method, pitch_mode, time_mode, rounding):
    options = []
    for value, name, choices in (
        (method, "method", ("nearest", "bilinear", "area")),
        (pitch_mode, "pitch_mode", ("stretch", "intervals", "fixed")),
        (time_mode, "time_mode", ("resample", "events")),
        (rounding, "rounding", ("nearest", "floor", "ceil")),
    ):
        value = str(value).strip().lower()
        if value not in choices:
            raise ValueError(f"{name} must be one of {choices}; received {value!r}.")
        options.append(value)
    return tuple(options)


def _quantize_coordinates(values, rounding):
    # 'nearest' follows Python/NumPy's half-to-even rule, including output size.
    operation = {"nearest": np.rint, "floor": np.floor, "ceil": np.ceil}[rounding]
    return operation(values).astype(int)


def _resample_axis(arr, size, axis, method):
    """Resample cell values on one axis; pitch and time policies stay separate."""
    source_size = arr.shape[axis]
    if size == source_size:
        return arr.copy()
    if method == "nearest":
        indices = ((2 * np.arange(size) + 1) * source_size) // (2 * size)
        return np.take(arr, indices, axis=axis)
    values = np.moveaxis(arr, axis, -1)
    if method == "bilinear":
        # The separable version of the original corner-aligned 2D interpolation.
        positions = np.linspace(0, source_size - 1, size)
        lo = np.floor(positions).astype(int)
        hi = np.minimum(lo + 1, source_size - 1)
        weight = positions - lo
        result = (1 - weight) * values[..., lo] + weight * values[..., hi]
    else:  # area: average the source coverage of each output cell.
        result = np.empty((*values.shape[:-1], size), dtype=float)
        # Measure overlap in integer units (one source cell spans `size`).
        # This keeps exact half-coverage at 0.5, independent of float edge drift.
        for j in range(size):
            left, right = j * source_size, (j + 1) * source_size
            lo, hi = left // size, (right + size - 1) // size
            cells = np.arange(lo, hi)
            weights = np.minimum((cells + 1) * size, right) - np.maximum(cells * size, left)
            result[..., j] = (values[..., lo:hi] * weights).sum(axis=-1) / source_size
    return np.moveaxis(result, -1, axis)


def _scale_time_events(arr, scale_x, rounding):
    """Scale boundaries of binary runs, dropping runs that quantize to no time."""
    if not np.all((arr == 0) | (arr == 1)):
        raise ValueError("time_mode='events' requires a binary (0/1) kernel.")
    edges = _quantize_coordinates(np.arange(arr.shape[1] + 1) * scale_x, rounding)
    result = np.zeros((arr.shape[0], max(1, int(edges[-1]))), dtype=float)
    for row, values in enumerate(arr):
        changes = np.diff(np.pad(values, (1, 1)))
        starts, = np.nonzero(changes == 1)
        ends, = np.nonzero(changes == -1)
        for start, end in zip(starts, ends):
            # Shared boundaries always map identically: no artificial overlap
            # between consecutive notes, and no forced one-cell extensions.
            result[row, edges[start]:edges[end]] = 1
    return result


def resize_kernel(
    arr: np.ndarray,
    scale_y: float,
    scale_x: float,
    *,
    method: str = "nearest",
    pitch_mode: str = "stretch",
    time_mode: str = "resample",
    rounding: str = "nearest",
) -> np.ndarray:
    """Augment a pitch × time kernel with explicit pitch and time policies.

    Parameters
    ----------
    arr : numpy.ndarray
        Nonempty 2D grid. Binary values or nonnegative finite weights.
    scale_y, scale_x : float
        Finite positive pitch and time factors. Row 0 and time boundary 0 are
        the anchors. The result has local coordinates, independent of MIDI labels.
    method : {"nearest", "bilinear", "area"}
        Sampling for stretched pitch rows and resampled time columns.
        ``nearest`` uses cell centres and repeats cells exactly at integer
        enlargement. ``bilinear`` retains legacy corner-aligned interpolation.
        ``area`` averages source-cell coverage; fractional results are weights.
        The method never interpolates pitch rows in ``intervals`` or ``fixed``.
    pitch_mode : {"stretch", "intervals", "fixed"}
        ``stretch`` (backward-compatible default) resizes row thickness and the
        box to ``max(1, round(H * scale_y))`` rows. ``intervals`` maps each source
        row once to ``quantize(row * scale_y)``: notes stay one row thick, chords
        remain chords, and collisions merge by maximum. Height is the mapped
        last row plus one: six rows at ×2 become eleven, spanning ten intervals.
        ``fixed`` retains original pitch rows and ignores ``scale_y``.
    time_mode : {"resample", "events"}
        ``resample`` uses ``method`` and ``max(1, round(W * scale_x))`` columns.
        ``events`` requires binary input and scales each active run's start/end
        boundaries before rasterizing. The same rounding is applied to all
        boundaries, including the output width. Zero-duration results are dropped.
        This preserves monophony when combined with ``intervals`` or ``fixed``;
        resampling with bilinear/area can blend successive notes across time.
    rounding : {"nearest", "floor", "ceil"}
        Quantization for interval coordinates and event boundaries. ``nearest``
        rounds halves to even. This does not change geometric box rounding or
        the sampling positions used by ``method``.

    Notes
    -----
    Time is transformed first, then pitch. Returned weights are not thresholded;
    :func:`run_pattern_search` can apply ``binarize_scaled_kernel`` afterwards.
    For strictly one-pitch-per-note behavior, use ``pitch_mode="intervals"``
    (or ``"fixed"``) with ``time_mode="events"``. It preserves existing polyphony,
    not voice identities: a binary grid cannot distinguish consecutive repeated
    notes at the same pitch. Fractional compression can merge pitches or drop
    short notes; finer source grids reduce time quantization loss.

    The defaults preserve exact block repetition:
    ``resize_kernel(K, 2, 2) == K.repeat(2, 0).repeat(2, 1)`` elementwise.
    The result is always an independent float array.
    """
    arr = np.asarray(arr, dtype=float)
    if arr.ndim != 2 or arr.size == 0:
        raise ValueError("kernel must be a nonempty 2D array.")
    if not np.isfinite(arr).all() or np.any(arr < 0):
        raise ValueError("kernel values must be finite and nonnegative.")
    scale_y, scale_x = float(scale_y), float(scale_x)
    if not all(math.isfinite(s) and s > 0 for s in (scale_y, scale_x)):
        raise ValueError("Scale factors must be finite and positive.")
    method, pitch_mode, time_mode, rounding = _augmentation_options(
        method, pitch_mode, time_mode, rounding
    )
    if time_mode == "events":
        timed = _scale_time_events(arr, scale_x, rounding)
    else:
        width = max(1, int(round(arr.shape[1] * scale_x)))
        timed = _resample_axis(arr, width, 1, method)
    if pitch_mode == "fixed":
        return timed
    if pitch_mode == "intervals":
        rows = _quantize_coordinates(np.arange(arr.shape[0]) * scale_y, rounding)
        result = np.zeros((int(rows[-1]) + 1, timed.shape[1]), dtype=float)
        np.maximum.at(result, rows, timed)
        return result
    height = max(1, int(round(arr.shape[0] * scale_y)))
    return _resample_axis(timed, height, 0, method)

def summarize_best(name: str, data: np.ndarray, labels_y: List, labels_x: List) -> Optional[Tuple[float, int, int]]:
    finite_mask = np.isfinite(data)
    if not finite_mask.any():
        print(f"{name}: no finite values to summarise.")
        return None
    flat_index = np.nanargmax(data)
    r, c = divmod(int(flat_index), data.shape[1])
    print(f"{name} best: {data[r, c]:.3f} at top-left (row={labels_y[r]}, col={labels_x[c]})")
    return float(data[r, c]), int(r), int(c)


def top_matches(name: str, data: np.ndarray, labels_y: List, labels_x: List, top_n: Optional[int], threshold: Optional[float] = None) -> List[Tuple[float, int, int]]:
    if top_n is None or top_n <= 0:
        return []
    flat = data.reshape(-1)
    mask = np.isfinite(flat)
    if threshold is not None:
        mask &= flat >= threshold
    indices = np.nonzero(mask)[0]
    if indices.size == 0:
        print(f"{name}: no entries meet the threshold.")
        return []
    ranked = indices[np.argsort(flat[indices])[::-1]]
    limit = min(int(top_n), ranked.size)
    results: List[Tuple[float, int, int]] = []
    print(f"{name} top {limit} positions:")
    for idx in ranked[:limit]:
        val = float(flat[idx])
        r, c = divmod(int(idx), data.shape[1])
        print(f"  score={val:.3f} at row={labels_y[r]}, col={labels_x[c]}")
        results.append((val, r, c))
    return results


def apply_threshold(data: np.ndarray, threshold: Optional[float]):
    if threshold is None:
        return data
    return np.where(data >= threshold, data, np.nan)


def finite_bounds(data: np.ndarray) -> Tuple[float, float]:
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return 0.0, 1.0
    low = float(np.min(finite))
    high = float(np.max(finite))
    if low == high:
        high = low + 1e-9
    return low, high


def plot_matplotlib_single(title: str, data: np.ndarray, *, threshold: Optional[float] = None, color_bounds: Optional[Tuple[float, float]] = None, cmap: str = "viridis") -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 6))
    masked = apply_threshold(data, threshold)
    if color_bounds is None:
        vmin, vmax = None, None
    else:
        vmin, vmax = color_bounds
    im = ax.imshow(masked, cmap=cmap, origin='upper', aspect='auto', vmin=vmin, vmax=vmax)
    ax.set_title(title)
    ax.set_xlabel('time offset (columns)')
    ax.set_ylabel('pitch offset (rows)')
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    plt.show()


_BOKEH_NOTEBOOK_INITIALIZED = False


def plot_bokeh_single(title: str, data: np.ndarray, *, threshold: Optional[float] = None, color_bounds: Optional[Tuple[float, float]] = None) -> None:
    global _BOKEH_NOTEBOOK_INITIALIZED
    # Initialize inline output once when running in a notebook
    if not _BOKEH_NOTEBOOK_INITIALIZED:
        try:
            from IPython import get_ipython  # type: ignore
            ip = get_ipython()
        except Exception:
            ip = None
        if ip is not None:
            try:
                from bokeh.io import output_notebook
                output_notebook(hide_banner=True)
                _BOKEH_NOTEBOOK_INITIALIZED = True
            except Exception:
                pass
    from bokeh.plotting import figure, show
    from bokeh.models import LinearColorMapper, ColorBar
    from bokeh.palettes import Viridis256

    masked = apply_threshold(data, threshold)
    if color_bounds is None:
        low, high = finite_bounds(masked)
    else:
        low, high = color_bounds
    fig = figure(
        title=title,
        x_range=(0, masked.shape[1]),
        y_range=(0, masked.shape[0]),
        width=900,
        height=600,
        tools='pan,wheel_zoom,reset,save',
    )
    mapper = LinearColorMapper(palette=Viridis256, low=low, high=high)
    fig.image(image=[np.flipud(masked)], x=0, y=0, dw=masked.shape[1], dh=masked.shape[0], color_mapper=mapper)
    fig.add_layout(ColorBar(color_mapper=mapper), 'right')
    fig.xaxis.axis_label = 'time offset (columns)'
    fig.yaxis.axis_label = 'pitch offset (rows, top=high)'
    show(fig)


def plot_kernel(title: str, kernel: np.ndarray, *, backend: str = "plt", cmap: str = "viridis") -> None:
    if backend in ("plt", "both"):
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 6))
        im = ax.imshow(kernel, cmap=cmap, origin='upper', aspect='auto')
        ax.set_title(title)
        ax.set_xlabel('kernel columns')
        ax.set_ylabel('kernel rows')
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        plt.show()
    if backend in ("bokeh", "both"):
        from bokeh.plotting import figure, show
        from bokeh.models import LinearColorMapper, ColorBar
        from bokeh.palettes import Viridis256

        low, high = finite_bounds(kernel)
        fig = figure(
            title=title,
            x_range=(0, kernel.shape[1]),
            y_range=(0, kernel.shape[0]),
            width=900,
            height=600,
            tools='pan,wheel_zoom,reset,save',
        )
        mapper = LinearColorMapper(palette=Viridis256, low=low, high=high)
        fig.image(image=[np.flipud(kernel)], x=0, y=0, dw=kernel.shape[1], dh=kernel.shape[0], color_mapper=mapper)
        fig.add_layout(ColorBar(color_mapper=mapper), 'right')
        fig.xaxis.axis_label = 'kernel columns'
        fig.yaxis.axis_label = 'kernel rows (top=high)'
        show(fig)


def pad_for_same(matrix: np.ndarray, kernel: np.ndarray) -> Tuple[np.ndarray, int, int]:
    """Zero-pad so valid convolution on the result has the host shape at stride 1.

    Output cell ``(i, j)`` corresponds to kernel top-left at host
    ``(i - pad_y, j - pad_x)``, which may be negative (kernel hangs off the edge).
    Missing cells are silence (0).
    """
    M = np.asarray(matrix, dtype=float)
    K = np.asarray(kernel, dtype=float)
    if M.ndim != 2 or K.ndim != 2:
        raise ValueError("matrix and kernel must be 2D.")
    r, c = K.shape
    pad_y = r // 2
    pad_x = c // 2
    Mp = np.pad(M, ((pad_y, r - 1 - pad_y), (pad_x, c - 1 - pad_x)))
    return Mp, int(pad_y), int(pad_x)


def _normalize_padding(padding: str) -> str:
    mode = str(padding).strip().lower()
    if mode not in {"valid", "same"}:
        raise ValueError("padding must be 'valid' or 'same'.")
    return mode


def kernel_placement_starts(
    host_shape: Tuple[int, int],
    kernel_shape: Tuple[int, int],
    *,
    padding: str = "valid",
    stride_y: int = 1,
    stride_x: int = 1,
) -> Tuple[List[int], List[int]]:
    """Return row and column top-lefts for kernel placements.

    For ``padding="valid"`` the coordinates live on the host. For
    ``padding="same"`` they live on the zero-padded canvas, whose valid
    placement grid has the host shape at stride 1.
    """
    mode = _normalize_padding(padding)
    H, W = (int(host_shape[0]), int(host_shape[1]))
    h, w = (int(kernel_shape[0]), int(kernel_shape[1]))
    sy = max(1, int(stride_y))
    sx = max(1, int(stride_x))
    if mode == "valid":
        n_row = H - h + 1
        n_col = W - w + 1
    else:
        n_row = H
        n_col = W
    if n_row <= 0 or n_col <= 0:
        return [], []
    return list(range(0, n_row, sy)), list(range(0, n_col, sx))


def count_kernel_placements(
    host_shape: Tuple[int, int],
    kernel_shape: Tuple[int, int],
    *,
    padding: str = "valid",
    stride_y: int = 1,
    stride_x: int = 1,
) -> Tuple[int, int, int]:
    """Return ``(n_row, n_col, n_total)`` kernel top-lefts for this padding/stride."""
    rows, cols = kernel_placement_starts(
        host_shape,
        kernel_shape,
        padding=padding,
        stride_y=stride_y,
        stride_x=stride_x,
    )
    return len(rows), len(cols), len(rows) * len(cols)


def score_kernel_at(
    matrix: np.ndarray,
    kernel: np.ndarray,
    i: int,
    j: int,
    *,
    normalize: bool = True,
) -> Tuple[np.ndarray, np.ndarray, float, float]:
    """Score one kernel placement with top-left ``(i, j)`` on ``matrix``.

    Returns ``(window, product, raw, normalised)``. ``raw`` is the sum of
    ``window * kernel`` (shared ``1``s on binary grids). ``normalised`` divides
    by the kernel sum when ``normalize`` is true and that sum is nonzero.
    """
    M = np.asarray(matrix, dtype=float)
    K = np.asarray(kernel, dtype=float)
    if M.ndim != 2 or K.ndim != 2:
        raise ValueError("matrix and kernel must be 2D.")
    r, c = K.shape
    i = int(i)
    j = int(j)
    if i < 0 or j < 0 or i + r > M.shape[0] or j + c > M.shape[1]:
        raise ValueError(
            f"Placement (i={i}, j={j}) with kernel {K.shape} "
            f"does not fit matrix {M.shape}."
        )
    window = M[i : i + r, j : j + c]
    product = window * K
    raw = float(product.sum())
    denom = float(K.sum())
    norm = raw / denom if denom and normalize else raw
    return window, product, raw, norm


def _sampled_windows(matrix, kernel_shape, stride_y, stride_x):
    """View only the placements requested by the search stride."""
    windows = np.lib.stride_tricks.sliding_window_view(matrix, kernel_shape)
    return windows[::max(1, int(stride_y)), ::max(1, int(stride_x))]


def _window_overlap(windows, kernel):
    # Contract directly, without allocating an output_rows × output_cols × H × W
    # product. Keep optimize=False: a BLAS reshape can copy the strided windows.
    return np.einsum("ijuv,uv->ij", windows, kernel, optimize=False)


def convolution_map(
    matrix: np.ndarray,
    kernel: np.ndarray,
    *,
    stride_y: int = 1,
    stride_x: int = 1,
    normalize: bool = True,
    padding: str = "valid",
) -> Tuple[np.ndarray, List[int], List[int], Dict[str, object]]:
    """Return a sliding-window overlap map for one kernel.

    ``padding="valid"`` (default) matches :func:`run_pattern_search`.
    ``padding="same"`` zero-pads so the score map can match the host shape at
    stride 1. Placement coordinates are top-lefts on the working (possibly
    padded) grid.

    Returns ``(scores, rows, cols, meta)`` where ``meta`` has ``pad_y``,
    ``pad_x``, and ``padded_shape``.
    """
    M = np.asarray(matrix, dtype=float)
    K = np.asarray(kernel, dtype=float)
    if M.ndim != 2 or K.ndim != 2:
        raise ValueError("matrix and kernel must be 2D.")
    mode = _normalize_padding(padding)
    if mode == "same":
        work, pad_y, pad_x = pad_for_same(M, K)
    else:
        work, pad_y, pad_x = M, 0, 0
    rows, cols = kernel_placement_starts(
        work.shape,
        K.shape,
        padding="valid",
        stride_y=stride_y,
        stride_x=stride_x,
    )
    meta: Dict[str, object] = {
        "pad_y": int(pad_y),
        "pad_x": int(pad_x),
        "padded_shape": work.shape,
    }
    if not rows or not cols:
        return np.full((len(rows), len(cols)), np.nan), rows, cols, meta
    windows = _sampled_windows(work, K.shape, stride_y, stride_x)
    scores = _window_overlap(windows, K)
    if normalize:
        weight = float(K.sum())
        if weight:
            scores = scores / weight
    return scores, rows, cols, meta


def _host_axis_labels(full_labels: List, positions: List[int], pad: int) -> List:
    n = len(full_labels)
    labels: List = []
    for pos in positions:
        host_i = int(pos) - int(pad)
        if 0 <= host_i < n:
            labels.append(full_labels[host_i])
        else:
            labels.append(host_i)
    return labels


def build_scale_variants(kernel_scale_axes: List[str], kernel_scale_factors: List[float]) -> List[Dict[str, float]]:
    scale_variants: List[Dict[str, float]] = []
    seen_scales: set[Tuple[float, float]] = set()
    for axis in kernel_scale_axes:
        axis_norm = str(axis).lower()
        if axis_norm not in {"x", "y", "both"}:
            raise ValueError(f"Unsupported axis {axis!r} in KERNEL_SCALE_AXES; use 'x', 'y', or 'both'.")
        for factor in kernel_scale_factors:
            factor = float(factor)
            if not math.isfinite(factor) or factor <= 0:
                raise ValueError(f"Scale factor must be finite and positive; received {factor}.")
            scale_y = factor if axis_norm in {"y", "both"} else 1.0
            scale_x = factor if axis_norm in {"x", "both"} else 1.0
            key = (round(scale_y, 6), round(scale_x, 6))
            if key in seen_scales:
                continue
            seen_scales.add(key)
            label = f"axis={axis_norm}, factor={factor:g}, scale_y={scale_y:.3f}, scale_x={scale_x:.3f}"
            scale_variants.append({"axis": axis_norm, "factor": factor, "scale_y": scale_y, "scale_x": scale_x, "label": label})
    return scale_variants


def compute_metrics_for_variant(
    matrix: np.ndarray,
    scaled_kernel: np.ndarray,
    *,
    stride_y: int = 1,
    stride_x: int = 1,
    metrics: List[str] = None,
    padding: str = "valid",
) -> Tuple[Dict[str, np.ndarray], Dict[str, pd.DataFrame], List[int], List[int], int, int, np.ndarray]:
    metrics = list(metrics or [])
    mode = _normalize_padding(padding)
    work = np.asarray(matrix, dtype=float)
    kernel = np.asarray(scaled_kernel, dtype=float)
    pad_y = pad_x = 0
    if mode == "same":
        work, pad_y, pad_x = pad_for_same(work, kernel)
    elif kernel.shape[0] > work.shape[0] or kernel.shape[1] > work.shape[1]:
        raise ValueError("Scaled kernel is larger than the source matrix.")

    window_shape = kernel.shape
    out_rows = work.shape[0] - window_shape[0] + 1
    out_cols = work.shape[1] - window_shape[1] + 1
    if out_rows <= 0 or out_cols <= 0:
        raise ValueError("Kernel cannot slide within the source matrix.")

    windows = _sampled_windows(work, window_shape, stride_y, stride_x)
    conv_scores = _window_overlap(windows, kernel)

    row_positions = list(range(0, out_rows, max(1, int(stride_y))))
    col_positions = list(range(0, out_cols, max(1, int(stride_x))))

    metric_arrays: Dict[str, np.ndarray] = {}
    metric_dfs: Dict[str, pd.DataFrame] = {}

    if 'normalized_overlap' in metrics:
        kernel_weight = float(scaled_kernel.sum())
        if kernel_weight != 0.0:
            conv_norm = conv_scores / kernel_weight
        else:
            conv_norm = conv_scores.copy()
        metric_arrays['normalized_overlap'] = conv_norm
        metric_dfs['normalized_overlap'] = pd.DataFrame(conv_norm)

    needs_cross = any(m in metrics for m in ('cross_covariance', 'normalized_cross_correlation'))
    if needs_cross:
        windows_flat = windows.reshape(len(row_positions), len(col_positions), -1)
        kernel_flat = scaled_kernel.reshape(-1)
        kernel_mean = kernel_flat.mean()
        kernel_zero_mean = kernel_flat - kernel_mean
        kernel_norm_val = float(np.linalg.norm(kernel_zero_mean))
        window_means = windows_flat.mean(axis=2, keepdims=True)
        windows_zero_mean = windows_flat - window_means
        window_norms = np.linalg.norm(windows_zero_mean, axis=2)
        cross_cov_full = np.tensordot(windows_zero_mean, kernel_zero_mean, axes=([2], [0]))

        if 'cross_covariance' in metrics:
            cross_cov = cross_cov_full
            metric_arrays['cross_covariance'] = cross_cov
            metric_dfs['cross_covariance'] = pd.DataFrame(cross_cov)

        if 'normalized_cross_correlation' in metrics:
            denominator = window_norms * kernel_norm_val
            norm_cross_full = np.divide(
                cross_cov_full,
                denominator,
                out=np.zeros_like(cross_cov_full),
                where=denominator > 0,
            )
            norm_cross = norm_cross_full
            metric_arrays['normalized_cross_correlation'] = norm_cross
            metric_dfs['normalized_cross_correlation'] = pd.DataFrame(norm_cross)

    return metric_arrays, metric_dfs, row_positions, col_positions, pad_y, pad_x, work


def run_pattern_search(
    matrix_source: pd.DataFrame | np.ndarray,
    kernel_source: pd.DataFrame | np.ndarray,
    *,
    metrics_to_run: List[str],
    stride_y: int = 1,
    stride_x: int = 1,
    kernel_scale_factors: List[float] = (1.0,),
    kernel_scale_axes: List[str] = ("x",),
    kernel_resize_method: str = "nearest",
    kernel_pitch_mode: str = "stretch",
    kernel_time_mode: str = "resample",
    kernel_rounding: str = "nearest",
    binarize_scaled_kernel: bool = True,
    binarize_threshold: float = 0.5,
    share_y_scaling: bool = True,
    plot_thresholds: Optional[Dict[str, Optional[float]]] = None,
    backend: str = "plt",
    mpl_cmap: str = "viridis",
    plot_scaled_kernels: bool = False,
    top_n_matches: Optional[int] = 20,
    padding: str = "valid",
) -> Tuple[Dict[str, Dict[str, pd.DataFrame]], Dict[str, np.ndarray], Optional[str], Optional[pd.DataFrame]]:
    """Slide ``kernel_source`` over ``matrix_source`` and score each placement.

    ``padding="valid"`` (default) keeps only placements where the kernel fits
    inside the host. ``padding="same"`` zero-pads the host so the score map can
    match the host size at stride 1; hanging cells are silence (0). Result
    index/column labels are host top-left coordinates and may be negative
    under ``"same"``.

    Augmentation uses :func:`resize_kernel`. ``kernel_pitch_mode="intervals"``
    scales pitch distances while preserving one row per source pitch; ``"fixed"``
    keeps pitches unchanged, and ``"stretch"`` retains geometric row enlargement.
    ``kernel_time_mode="events"`` scales binary note boundaries; ``"resample"``
    uses ``kernel_resize_method`` (``"nearest"``, ``"bilinear"``, or ``"area"``).
    ``kernel_rounding`` controls interval/event quantization (``"nearest"``,
    ``"floor"``, ``"ceil"``). Defaults retain geometric nearest-cell resizing.
    Nondefault augmentation choices are recorded in variant keys.
    ``normalized_overlap`` measures the fraction of active kernel weight found
    in the host; extra host notes are not penalized. A score of 1 is containment,
    not necessarily equality. ``normalized_cross_correlation`` also uses zeros.
    """
    padding = _normalize_padding(padding)
    kernel_resize_method, kernel_pitch_mode, kernel_time_mode, kernel_rounding = (
        _augmentation_options(
            kernel_resize_method, kernel_pitch_mode, kernel_time_mode, kernel_rounding
        )
    )
    if isinstance(matrix_source, pd.DataFrame):
        matrix = matrix_source.to_numpy(dtype=float)
        row_labels_full = list(matrix_source.index)
        col_labels_full = list(matrix_source.columns)
    else:
        matrix = np.asarray(matrix_source, dtype=float)
        if matrix.ndim != 2:
            raise ValueError('matrix_source must be a 2D table or array.')
        row_labels_full = list(range(matrix.shape[0]))
        col_labels_full = list(range(matrix.shape[1]))

    if isinstance(kernel_source, pd.DataFrame):
        kernel_array = kernel_source.to_numpy(dtype=float)
    else:
        kernel_array = np.asarray(kernel_source, dtype=float)

    if kernel_array.ndim != 2:
        raise ValueError('kernel_source must be a 2D structure to act as a kernel.')
    if kernel_array.size == 0:
        raise ValueError('kernel_source is empty; draw a pattern before running the analysis.')

    available_metrics = {
        'normalized_overlap': {'label': 'Normalised overlap'},
        'cross_covariance': {'label': 'Cross-covariance'},
        'normalized_cross_correlation': {'label': 'Normalised cross-correlation'},
    }
    selected_metrics = [m for m in metrics_to_run if m in available_metrics]
    if not selected_metrics:
        raise ValueError('metrics_to_run does not include any supported metrics.')

    scale_variants = build_scale_variants(list(kernel_scale_axes), list(kernel_scale_factors))

    all_results: Dict[str, Dict[str, pd.DataFrame]] = {}
    scaled_kernels: Dict[str, np.ndarray] = {}
    last_variant_key: Optional[str] = None
    last_conv_raw_df: Optional[pd.DataFrame] = None

    shared_bounds: Dict[str, List[float]] = {m: [np.inf, -np.inf] for m in available_metrics.keys()}
    deferred_plots: List[Dict[str, object]] = []

    for variant in scale_variants:
        scale_y = float(variant['scale_y'])
        scale_x = float(variant['scale_x'])
        variant_key = str(variant['label'])
        if (kernel_resize_method, kernel_pitch_mode, kernel_time_mode, kernel_rounding) != (
            "nearest", "stretch", "resample", "nearest"
        ):
            variant_key += (
                f", pitch={kernel_pitch_mode}, time={kernel_time_mode}, "
                f"method={kernel_resize_method}, rounding={kernel_rounding}"
            )
        scaled_kernel = resize_kernel(
            kernel_array, scale_y, scale_x, method=kernel_resize_method,
            pitch_mode=kernel_pitch_mode, time_mode=kernel_time_mode,
            rounding=kernel_rounding,
        )
        if binarize_scaled_kernel:
            _thr = float(binarize_threshold)
            scaled_kernel = (scaled_kernel >= _thr).astype(float)

        if plot_scaled_kernels:
            plot_kernel(f"Scaled kernel ({variant_key})", scaled_kernel, backend=backend, cmap=mpl_cmap)

        if padding == "valid" and (
            scaled_kernel.shape[0] > matrix.shape[0] or scaled_kernel.shape[1] > matrix.shape[1]
        ):
            # Skip variants larger than source
            continue

        metric_arrays, metric_dfs, row_positions, col_positions, pad_y, pad_x, work = compute_metrics_for_variant(
            matrix,
            scaled_kernel,
            stride_y=stride_y,
            stride_x=stride_x,
            metrics=selected_metrics,
            padding=padding,
        )

        row_labels = _host_axis_labels(row_labels_full, row_positions, pad_y)
        col_labels = _host_axis_labels(col_labels_full, col_positions, pad_x)

        for metric_key in selected_metrics:
            metric_label = available_metrics[metric_key]['label']
            data = metric_arrays.get(metric_key)
            if data is None:
                continue
            threshold = None if plot_thresholds is None else plot_thresholds.get(metric_key)

            share_scale = bool(share_y_scaling) and len(scale_variants) > 1
            if share_scale:
                masked = apply_threshold(data, threshold)
                if np.isfinite(masked).any():
                    low, high = finite_bounds(masked)
                    bounds = shared_bounds.get(metric_key)
                    if bounds is not None:
                        bounds[0] = min(bounds[0], low)
                        bounds[1] = max(bounds[1], high)
                deferred_plots.append({
                    'metric_key': metric_key,
                    'metric_label': metric_label,
                    'data': data,
                    'threshold': threshold,
                    'row_labels': row_labels,
                    'col_labels': col_labels,
                })
            else:
                if backend == 'plt':
                    plot_matplotlib_single(metric_label, data, threshold=threshold, color_bounds=None, cmap=mpl_cmap)
                elif backend == 'bokeh':
                    plot_bokeh_single(metric_label, data, threshold=threshold, color_bounds=None)
                elif backend == 'both':
                    plot_matplotlib_single(metric_label, data, threshold=threshold, color_bounds=None, cmap=mpl_cmap)
                    plot_bokeh_single(metric_label, data, threshold=threshold, color_bounds=None)
                elif backend == 'none':
                    pass
                else:
                    print(f"Unknown backend {backend!r}. Defaulting to Matplotlib.")
                    plot_matplotlib_single(metric_label, data, threshold=threshold, color_bounds=None, cmap=mpl_cmap)

                summarize_best(metric_label, data, row_labels, col_labels)
                top_matches(metric_label, data, row_labels, col_labels, top_n_matches, threshold)

        # Convert metric arrays to DataFrames with labels for return
        labeled_metric_dfs: Dict[str, pd.DataFrame] = {}
        for k, arr in metric_arrays.items():
            labeled_metric_dfs[k] = pd.DataFrame(arr, index=row_labels, columns=col_labels)

        all_results[variant_key] = labeled_metric_dfs
        scaled_kernels[variant_key] = scaled_kernel
        last_variant_key = variant_key

        # Save last raw conv for convenience (same working matrix as the metrics)
        if 'normalized_overlap' in metric_arrays:
            windows = _sampled_windows(work, scaled_kernel.shape, stride_y, stride_x)
            conv_raw = _window_overlap(windows, scaled_kernel)
            last_conv_raw_df = pd.DataFrame(conv_raw, index=row_labels, columns=col_labels)

    # Deferred plots with shared color scale
    if bool(share_y_scaling) and len(scale_variants) > 1 and deferred_plots:
        final_bounds: Dict[str, Tuple[float, float]] = {}
        for m, (lo, hi) in shared_bounds.items():
            if np.isfinite(lo) and np.isfinite(hi) and lo < hi:
                final_bounds[m] = (float(lo), float(hi))
        for item in deferred_plots:
            metric_key = str(item['metric_key'])
            metric_label = str(item['metric_label'])
            data = np.asarray(item['data'])
            threshold = item['threshold']
            bounds = final_bounds.get(metric_key)
            if backend == 'plt':
                plot_matplotlib_single(metric_label, data, threshold=threshold, color_bounds=bounds, cmap=mpl_cmap)
            elif backend == 'bokeh':
                plot_bokeh_single(metric_label, data, threshold=threshold, color_bounds=bounds)
            elif backend == 'both':
                plot_matplotlib_single(metric_label, data, threshold=threshold, color_bounds=bounds, cmap=mpl_cmap)
                plot_bokeh_single(metric_label, data, threshold=threshold, color_bounds=bounds)
            elif backend == 'none':
                pass
            else:
                print(f"Unknown backend {backend!r}. Defaulting to Matplotlib.")
                plot_matplotlib_single(metric_label, data, threshold=threshold, color_bounds=bounds, cmap=mpl_cmap)

            summarize_best(metric_label, data, item['row_labels'], item['col_labels'])
            top_matches(metric_label, data, item['row_labels'], item['col_labels'], top_n_matches, threshold)

    return all_results, scaled_kernels, last_variant_key, last_conv_raw_df


