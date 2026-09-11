"""Search independently defined MIDI/chroma queries on compatible binary grids.

MIDI placement preserves each requested pitch (plus an explicit transposition).
Chroma preserves all 12 pitch classes and transposes by circular row rotation.
The query's origin and resolution come from its metadata, not from a host crop.
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.colors import to_rgba
from matplotlib.patches import Rectangle

from .music_utils import BinaryMatrixBundle
from .pattern_search import compute_metrics_for_variant, resize_kernel

__all__ = ["search_binary_query", "rank_query_matches", "plot_query_heatmaps",
           "plot_binary_query_match", "plot_query_loss_examples"]

_METRICS = ("normalized_overlap", "normalized_cross_correlation", "cross_covariance")
_MATCH_COLUMNS = ["score", "time_scale", "transpose_semitones", "row", "col",
                  "grid_onset_QL", "grid_end_QL", "source_onset_QL", "source_end_QL",
                  "required_cells", "shared_cells", "missing_cells", "overlap", "loss_fraction"]


def rank_query_matches(placements: pd.DataFrame, *, top_n=None, min_score=None, max_time_iou=0.5):
    """Filter and rank saved query placements without recomputing the search.

    Use ``result['placements']`` for the full pool, including scores below the
    search's original threshold. Thresholds are inclusive on unrounded scores.
    ``top_n=None`` removes the display cap. Greedy time-IoU filtering suppresses
    overlaps across pitch shifts and time scales; its output is a collection of
    retained windows, not a count of independent musical occurrences. Ties keep
    the input order, as in ``search_binary_query``. Input data remains unchanged.
    """
    if top_n is not None and (not np.isfinite(top_n) or int(top_n) != top_n or top_n < 1):
        raise ValueError("top_n must be a positive integer or None.")
    if top_n is not None:
        top_n = int(top_n)
    if min_score is not None and not np.isfinite(min_score):
        raise ValueError("min_score must be finite or None.")
    if max_time_iou is not None and not 0 <= max_time_iou <= 1:
        raise ValueError("max_time_iou must be within [0, 1] or None.")
    required = {"score", "grid_onset_QL", "grid_end_QL"}
    if not required.issubset(placements.columns):
        raise ValueError(f"Placements require columns {sorted(required)}.")
    keep = np.isfinite(placements["score"].to_numpy(dtype=float))
    if min_score is not None:
        keep &= placements["score"].to_numpy(dtype=float) >= min_score
    ranked = placements.loc[keep].sort_values("score", ascending=False, kind="stable")
    if max_time_iou is None:
        return ranked.iloc[:top_n].reset_index(drop=True)
    starts = ranked["grid_onset_QL"].to_numpy(dtype=float)
    ends = ranked["grid_end_QL"].to_numpy(dtype=float)
    if not (np.isfinite(starts).all() and np.isfinite(ends).all() and (ends > starts).all()):
        raise ValueError("Placement time windows must have finite, increasing bounds.")
    chosen = []
    for i, (start, end) in enumerate(zip(starts, ends)):
        if chosen:
            overlap = np.maximum(0, np.minimum(end, ends[chosen]) - np.maximum(start, starts[chosen]))
            union = end - start + ends[chosen] - starts[chosen] - overlap
            if (overlap / union > max_time_iou).any():
                continue
        chosen.append(i)
        if top_n is not None and len(chosen) == top_n:
            break
    return ranked.iloc[chosen].reset_index(drop=True)


def search_binary_query(
    host: BinaryMatrixBundle, query: BinaryMatrixBundle, *,
    time_scales=(1.0,), transpositions=(0,), metric="normalized_overlap",
    stride_x=1, top_n=5, min_score=None, max_time_iou=0.5,
) -> dict:
    """Search an independent query over time, tempo scales and pitch placements.

    Both bundles must have the same resolution and either MIDI axes (minmax/full)
    or complete chroma axes. Opposite row orders are aligned automatically.
    MIDI queries trim silent pitch margins, retaining their absolute pitch
    labels. ``transpositions="all"`` searches every valid MIDI row in the host
    (uniform semitone shifts of the entire voicing), or all 12 circular chroma
    shifts. The default ``(0,)`` fixes the query's original pitches/classes.
    Chroma queries retain all 12 rows and rotate them modulo 12; octave
    equivalents of a transposition are evaluated once. No linear pitch sliding
    or pitch-axis stretching is performed on chroma.

    Time scaling uses binary event boundaries with nearest/halves-to-even
    rounding. Silent time margins remain part of the query. The grid remains a
    quantized occupancy query, not a chord-label or harmonic-function detector.

    Returns labeled ``maps`` (variant rows, raw host column labels), ``variants``
    (actual kernels and host rows), ``matches`` (ranked MIDI/chroma-independent
    time coordinates), and ``skipped`` (empty, oversized or out-of-register
    variants). ``placements`` retains every finite scored placement BEFORE
    thresholding, overlap suppression and top-N selection; use
    ``rank_query_matches`` to explore other cutoffs without rescoring. Both
    placement tables include shared/required/missing active-cell counts,
    ``overlap=shared/required`` and ``loss_fraction=missing/required``. Extra host
    notes do not increase this loss. Only for normalized-overlap scoring does
    ``loss_fraction == 1-score``; correlation/covariance are different metrics.
    Maps retain every score; optional greedy ``max_time_iou`` filtering
    suppresses candidates sharing more than that time interval IoU with a prior
    hit, across scales and transpositions. Set it to None to retain neighbors.
    Only valid, completely contained placements are scored. A short/empty host
    or strict threshold can produce no matches. Higher scores rank first.
    """
    for bundle, label in ((host, "host"), (query, "query")):
        matrix = np.asarray(bundle.matrix)
        if matrix.ndim != 2 or not matrix.size or not np.isin(matrix, [0, 1]).all():
            raise ValueError(f"The {label} must contain a nonempty binary 2D grid.")
        if bundle.meta.get("row_order") not in {"low_to_high", "high_to_low"}:
            raise ValueError("Use a bundle with explicit MIDI/chroma row-order metadata.")
    if not query.matrix.any():
        raise ValueError("The query must contain active cells.")
    chroma = host.meta["y_mode"] == "chroma"
    if chroma != (query.meta["y_mode"] == "chroma"):
        raise ValueError("Host and query must both use MIDI or both use chroma.")
    resolution = float(host.meta["resolution"])
    if not np.isclose(resolution, query.meta["resolution"], rtol=0, atol=1e-12):
        raise ValueError("Host and query need the same time resolution; regrid the query first.")
    if metric not in _METRICS:
        raise ValueError(f"Choose a metric from {_METRICS}.")
    if top_n is not None and (not np.isfinite(top_n) or int(top_n) != top_n or top_n < 1):
        raise ValueError("top_n must be a positive integer or None.")
    if int(stride_x) != stride_x or stride_x < 1:
        raise ValueError("stride_x must be a positive integer.")
    if min_score is not None and not np.isfinite(min_score):
        raise ValueError("min_score must be finite or None.")
    if max_time_iou is not None and not 0 <= max_time_iou <= 1:
        raise ValueError("max_time_iou must be within [0, 1] or None.")
    scales = list(dict.fromkeys(float(s) for s in time_scales))
    all_shifts = isinstance(transpositions, str) and transpositions == "all"
    if isinstance(transpositions, str) and not all_shifts:
        raise ValueError("Transpositions must be integer semitones or 'all'.")
    shifts = []
    for value in (() if all_shifts else transpositions):
        if not np.isfinite(value) or int(value) != value:
            raise ValueError("Transpositions must be integer semitones.")
        value = int(value) % 12 if chroma else int(value)
        if value not in shifts:
            shifts.append(value)
    if not scales or (not shifts and not all_shifts) or any(not np.isfinite(s) or s <= 0 for s in scales):
        raise ValueError("Provide positive finite time scales and at least one transposition.")
    base = np.asarray(query.matrix).copy()
    descending = host.meta["row_order"] == "high_to_low"
    if query.meta["row_order"] != host.meta["row_order"]:
        base = base[::-1]
    if chroma:
        if host.matrix.shape[0] != 12 or base.shape[0] != 12:
            raise ValueError("Chroma search requires all 12 rows, including silent classes.")
    else:
        query_axis = np.asarray(query.meta["row_axis_values"], dtype=int)
        if query.meta["row_order"] != host.meta["row_order"]:
            query_axis = query_axis[::-1]
        active_rows = np.flatnonzero(base.any(axis=1))
        first, last = int(active_rows[0]), int(active_rows[-1]) + 1
        base, query_axis = base[first:last], query_axis[first:last]
        host_axis = np.asarray(host.meta["row_axis_values"], dtype=int)
    if all_shifts:
        # Enumerate raw host rows, preserving the full interval pattern. This
        # also covers a query whose original absolute pitches lie off the host.
        shifts = list(range(12)) if chroma else [
            int(host_axis[row] - query_axis[0])
            for row in range(max(0, len(host_axis) - len(query_axis) + 1))
        ]
    series, variants, skipped, candidates = {}, {}, [], []
    for scale in scales:
        timed = resize_kernel(base, 1, scale, pitch_mode="fixed", time_mode="events")
        if not shifts:
            skipped.append({"time_scale": scale, "transpose_semitones": None,
                            "reason": "taller than host MIDI register"})
        for shift in shifts:
            key = (scale, shift)
            if chroma:
                kernel = np.roll(timed, -shift if descending else shift, axis=0)
                row = 0
            else:
                kernel = timed
                desired = query_axis + shift
                positions = np.flatnonzero(host_axis == desired[0])
                row = int(positions[0]) if positions.size else -1
                if row < 0 or not np.array_equal(host_axis[row:row+len(desired)], desired):
                    skipped.append({"time_scale": scale, "transpose_semitones": shift, "reason": "outside host MIDI register"})
                    continue
            if not kernel.any() or kernel.shape[1] > host.matrix.shape[1]:
                skipped.append({"time_scale": scale, "transpose_semitones": shift,
                                "reason": "empty after quantization" if not kernel.any() else "longer than host"})
                continue
            arrays, _, _, cols, _, _, _ = compute_metrics_for_variant(
                host.matrix[row:row+kernel.shape[0]], kernel,
                metrics=list(dict.fromkeys([metric, "normalized_overlap"])), stride_x=int(stride_x),
            )
            scores = arrays[metric][0]
            series[key] = pd.Series(scores, index=cols)
            variants[key] = {"kernel": kernel.copy(), "row": row}
            required_cells = int(kernel.sum())
            for col, score, overlap in zip(cols, scores, arrays["normalized_overlap"][0]):
                if not np.isfinite(score):
                    continue
                shared_cells = int(np.rint(overlap * required_cells))
                missing_cells = required_cells - shared_cells
                start, end = col * resolution, (col + kernel.shape[1]) * resolution
                origin = host.meta.get("source_time_origin", 0.0)
                candidates.append({"score": float(score), "time_scale": scale, "transpose_semitones": shift,
                                   "row": row, "col": col, "grid_onset_QL": start, "grid_end_QL": end,
                                   "source_onset_QL": start + origin, "source_end_QL": end + origin,
                                   "required_cells": required_cells, "shared_cells": shared_cells,
                                   "missing_cells": missing_cells, "overlap": shared_cells / required_cells,
                                   "loss_fraction": missing_cells / required_cells})
    maps = pd.DataFrame(series).T.sort_index(axis=1)
    maps.index = pd.MultiIndex.from_tuples(list(series), names=["time_scale", "transpose_semitones"])
    placements = pd.DataFrame(candidates, columns=_MATCH_COLUMNS)
    matches = rank_query_matches(placements, top_n=top_n, min_score=min_score, max_time_iou=max_time_iou)
    return {"maps": maps, "variants": variants, "matches": matches, "placements": placements,
            "skipped": pd.DataFrame(skipped, columns=["time_scale", "transpose_semitones", "reason"]),
            "metric": metric, "representation": "chroma" if chroma else "MIDI"}


def plot_query_heatmaps(results: Mapping[str, dict], resolution: float, *, rank=0,
                        aggregate_transpositions=False, colors=None):
    """Compare score maps, marking one rank or every shortlisted hit (rank=None).

    ``aggregate_transpositions=True`` shows the maximum across searched shifts
    at each time/scale, keeping large MIDI scans legible. The original maps and
    hit transpositions remain unchanged; this overview does not describe a
    single fixed transposition. ``colors`` assigns colors in shortlist order.
    """
    if not results:
        raise ValueError("Provide at least one search result to plot.")
    maps_to_plot = [result["maps"].groupby(level="time_scale", sort=False).max()
                    if aggregate_transpositions and not result["maps"].empty else result["maps"]
                    for result in results.values()]
    heights = [max(2.6, 1 + 0.25 * len(maps)) for maps in maps_to_plot]
    fig, axes = plt.subplots(len(results), 1, figsize=(12, sum(heights)),
                             gridspec_kw={"height_ratios": heights}, squeeze=False, layout="constrained")
    for ax, (name, result), maps in zip(axes.flat, results.items(), maps_to_plot):
        if maps.empty:
            ax.text(0.5, 0.5, f"{name}: no valid variants", transform=ax.transAxes, ha="center")
            ax.set_axis_off()
            continue
        times = np.asarray(maps.columns, dtype=float) * resolution
        step = times[1]-times[0] if len(times) > 1 else resolution
        metric = result["metric"]
        bounds = (0, 1) if metric == "normalized_overlap" else ((-1, 1) if metric == "normalized_cross_correlation" else (None, None))
        heat = ax.imshow(maps.to_numpy(), aspect="auto", interpolation="nearest", cmap="viridis",
                         vmin=bounds[0], vmax=bounds[1], origin="upper",
                         extent=(times[0]-step/2, times[-1]+step/2, len(maps)-0.5, -0.5))
        labels = ([f"time ×{s:g}" for s in maps.index] if aggregate_transpositions else
                  [f"time ×{s:g}; {t:+g} st" for s, t in maps.index])
        ax.set_yticks(range(len(maps)), labels)
        ax.set(title=name + (" — max over searched pitch shifts" if aggregate_transpositions else ""),
               xlabel="Window start on grid (QL)", ylabel="Query variant")
        ranks = range(len(result["matches"])) if rank is None else [rank]
        for selected_rank in ranks:
            if not 0 <= selected_rank < len(result["matches"]):
                continue
            hit = result["matches"].iloc[selected_rank]
            key = hit["time_scale"] if aggregate_transpositions else (hit["time_scale"], hit["transpose_semitones"])
            row = maps.index.get_loc(key)
            color = colors[selected_rank] if colors is not None else plt.get_cmap("tab10")(selected_rank % 10)
            ax.annotate(str(selected_rank + 1), (hit["grid_onset_QL"], row), ha="center", va="center",
                        color="white", fontsize=9, weight="bold",
                        bbox=dict(boxstyle="circle,pad=0.2", facecolor=color, edgecolor="white", linewidth=1))
        fig.colorbar(heat, ax=ax, label=metric.replace("_", " "))
    return fig


def plot_query_loss_examples(host: BinaryMatrixBundle, result: dict, placements: pd.DataFrame):
    """Compare missing requirements in actual windows of one fixed query variant.

    Select rows from ``result['placements']`` at one time scale and transposition.
    The first panel is the query; subsequent panels count shared/missing cells
    directly from the source matrix. Gray extra host cells do not increase
    occupancy loss. All panels use time relative to each window's start, with
    the absolute grid start in each title. Pitch axes remain musically ordered.
    """
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    if placements.empty or len(placements[["time_scale", "transpose_semitones"]].drop_duplicates()) != 1:
        raise ValueError("Select nonempty placements of one time scale and transposition.")
    first = placements.iloc[0]
    variant = result["variants"][(first["time_scale"], first["transpose_semitones"])]
    kernel, row = variant["kernel"], variant["row"]
    h, w = kernel.shape
    if (placements["row"] != row).any():
        raise ValueError("Placement rows must match the chosen variant.")
    descending = host.meta["row_order"] == "high_to_low"
    chroma = host.meta["y_mode"] == "chroma"
    pitches = ((np.arange(11, -1, -1) if descending else np.arange(12)) if chroma else
               np.asarray(host.meta["row_axis_values"]))[row:row+h]
    palette = ["#ffffff", "#258350", "#c82b35", "#bac2cb"]
    panels = [(kernel, "Query requirements", "Greys", 1)]
    for hit in placements.itertuples():
        col = int(hit.col)
        if col != hit.col or col < 0 or col + w > host.matrix.shape[1]:
            raise ValueError("Use valid, completely contained query placements.")
        actual = host.matrix[row:row+h, col:col+w]
        shared, missing = (kernel > 0) & (actual > 0), (kernel > 0) & (actual == 0)
        categories = np.zeros(kernel.shape, dtype=int)
        categories[shared], categories[missing] = 1, 2
        categories[(kernel == 0) & (actual > 0)] = 3
        score, loss = shared.sum() / kernel.sum(), missing.sum() / kernel.sum()
        title = (f"Start {col * host.meta['resolution']:g} QL; overlap {score:.3f}\n"
                 f"Missing {missing.sum()}/{kernel.sum():.0f} ({loss:.1%})")
        panels.append((categories, title, ListedColormap(palette), 3))
    fig, axes = plt.subplots(1, len(panels), figsize=(3 * len(panels), 4.3), sharey=True, layout="constrained")
    for ax, (values, title, cmap, maximum) in zip(axes, panels):
        ax.imshow(values[::-1] if descending else values, cmap=cmap, vmin=0, vmax=maximum,
                  interpolation="nearest", aspect="auto", origin="lower",
                  extent=(0, w * host.meta["resolution"], min(pitches)-0.5, max(pitches)+0.5))
        ax.set(title=title, xlabel="Time within window (QL)")
    if chroma:
        axes[0].set_yticks(range(12), ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"])
    axes[0].set_ylabel("Pitch class" if chroma else "MIDI pitch")
    fig.legend(handles=[Patch(facecolor=color, label=name) for color, name in zip(
        palette[1:], ["Shared requirement", "Missing requirement", "Extra source activity (no penalty)"])],
        loc="outside lower center", ncols=3, frameon=False)
    return fig


def plot_binary_query_match(host: BinaryMatrixBundle, result: dict, *, rank=0):
    """Plot the placed query and host cells, using MIDI or all twelve pitch classes.

    Magenta marks shared active cells, red crosses mark missing requirements.
    For chroma, source provenance is needed to recover MIDI notes and octaves.
    """
    if not 0 <= rank < len(result["matches"]):
        raise ValueError("Choose a rank in the returned matches.")
    hit = result["matches"].iloc[rank]
    variant = result["variants"][(hit["time_scale"], hit["transpose_semitones"])]
    kernel = variant["kernel"]
    row, col = int(hit["row"]), int(hit["col"])
    h, w = kernel.shape
    resolution = host.meta["resolution"]
    chroma = host.meta["y_mode"] == "chroma"
    descending = host.meta["row_order"] == "high_to_low"
    r0, r1 = max(0, row-2), min(host.matrix.shape[0], row+h+2)
    c0, c1 = max(0, col-4), min(host.matrix.shape[1], col+w+4)
    if chroma:
        numeric_axis = np.arange(11, -1, -1) if descending else np.arange(12)
    else:
        numeric_axis = np.asarray(host.meta["row_axis_values"], dtype=int)
    query_axis = numeric_axis[row:row+h]
    patch_axis = numeric_axis[r0:r1]
    patch = host.matrix[r0:r1, c0:c1]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    for ax, values, axis, start, end, title in [
        (axes[0], kernel, query_axis, col*resolution, (col+w)*resolution, "Placed query requirements"),
        (axes[1], patch, patch_axis, c0*resolution, c1*resolution, f"Host: score {hit['score']:.3f}"),
    ]:
        ax.imshow(values[::-1] if descending else values, origin="lower", interpolation="nearest",
                  cmap="Greys", vmin=0, vmax=1, aspect="auto",
                  extent=(start, end, min(axis)-0.5, max(axis)+0.5))
        if chroma:
            ax.set_yticks(range(12), ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"])
        else:
            ax.set_yticks(np.unique(np.linspace(min(axis), max(axis), min(8, len(axis)), dtype=int)))
        ax.set(title=title, xlabel="Grid time (QL)", ylabel="Pitch class (any octave)" if chroma else "MIDI pitch")
    axes[1].add_patch(Rectangle((col*resolution, min(query_axis)-0.5), w*resolution, h,
                                facecolor=to_rgba("#cf268c", 0.16), edgecolor="#cf268c", linewidth=2, linestyle="--"))
    for dr, dc in zip(*np.nonzero(kernel)):
        pitch, time = numeric_axis[row+dr], (col+dc)*resolution
        if host.matrix[row+dr, col+dc]:
            axes[1].add_patch(Rectangle((time, pitch-0.5), resolution, 1, fill=False,
                                       edgecolor="#ff38ac", linewidth=1.5))
        else:
            axes[1].plot(time+resolution/2, pitch, "x", color="#c82b35")
    return fig
