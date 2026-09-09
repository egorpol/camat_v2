"""Small, deterministic experiments for understanding binary representations.

These helpers audit occupancy and note events separately. Provenance describes
the source of the original grid; it is never attached to reconstructed notes.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .music_utils import (
    BinaryMatrixBundle,
    _binary_grid_positions,
    binary_matrix_to_df_from_meta,
    binary_slice_to_df,
    create_binary_matrix,
    create_binary_matrix_bundle,
    get_binary_window_provenance,
    get_binary_cell_provenance,
)

__all__ = [
    "make_roundtrip_example", "audit_binary_roundtrip", "compare_voice_roundtrips",
    "compare_binary_resolutions", "plot_binary_comparison",
    "describe_binary_span_sources", "plot_note_comparison",
    "prepare_binary_timeline", "split_binary_voices", "find_binary_matches",
    "extract_binary_kernel", "rank_binary_matches",
    "binary_match_sources", "plot_binary_search_trace",
]


def make_roundtrip_example() -> pd.DataFrame:
    """Nine notes exposing repetition, unisons, chords, octave folding and rests.

    The shortest duration is 0.5 QL, but some boundaries require 0.25 QL.
    ``xml_id`` values identify notes in ``examples/binary_roundtrip_voices.mei``.
    """
    rows = [
        (60, 0.0, 2.0, "lower", "held C4"),
        (60, 0.5, 0.5, "echo", "overlapping unison"),
        (62, 0.0, 0.5, "upper", "first D4"),
        (62, 0.5, 0.5, "upper", "repeated D4, no gap"),
        (67, 1.25, 0.75, "upper", "off-grid onset at resolution 0.5"),
        (64, 2.0, 1.0, "lower", "chord: E4"),
        (67, 2.0, 1.0, "upper", "chord: G4, touches previous G4"),
        (72, 1.5, 0.5, "echo", "C5 above held C4"),
        (67, 3.25, 0.5, "upper", "G4 after a rest"),
    ]
    df = pd.DataFrame(rows, columns=["MIDI", "Global Onset", "Duration", "Voice", "Case"])
    df["xml_id"] = [f"toy-{i}" for i in range(len(df))]
    return df


def prepare_binary_timeline(notes: pd.DataFrame, measure_offsets=()):
    """Rebase source notes and barlines together so pickups fit a zero-based grid.

    Returns ``(grid_notes, grid_measure_offsets, source_origin)``. Original
    onsets remain in ``Source Global Onset``; MIDI, durations, voices, local
    onsets and source IDs are unchanged. Source time = grid time + source_origin.
    Pass the original source table, before discarding negative-onset notes.
    """
    if notes.empty:
        raise ValueError("Provide source notes before rebasing the timeline.")
    onsets = notes["Global Onset"].to_numpy(float)
    offsets = np.asarray(list(measure_offsets) if measure_offsets is not None else [], dtype=float)
    if not np.isfinite(onsets).all() or not np.isfinite(offsets).all():
        raise ValueError("Source onsets and measure offsets must be finite.")
    origin = float(min(0.0, onsets.min(), offsets.min() if offsets.size else 0.0))
    rebased = notes.copy()
    rebased["Source Global Onset"] = notes["Global Onset"]
    rebased["Global Onset"] = onsets - origin
    return rebased, (offsets - origin).tolist(), origin


def split_binary_voices(bundle: BinaryMatrixBundle) -> dict[str, BinaryMatrixBundle]:
    """Build one occupancy grid per Voice on the parent's exact pitch/time axes.

    Provenance remains specific to each voice. This prevents a query from
    assembling a match across voices; touching repeats still merge within a
    voice. Unassigned voices share one group. The original bundle is unchanged.
    """
    if "Voice" not in bundle.source_df:
        raise ValueError("Voice labels are required for independent voice grids.")
    voices = {}
    for voice, notes in bundle.source_df.groupby("Voice", sort=False, dropna=False):
        if not ((notes["Duration"] > 0) & (notes["Global Onset"] + notes["Duration"] > 0)).any():
            continue
        label = "(unassigned)" if pd.isna(voice) else str(voice)
        single = create_binary_matrix_bundle(
            notes, source_name=label, measure_offsets=bundle.measure_offsets,
            resolution_method="manual", manual_resolution=bundle.meta["resolution"],
            y_mode=bundle.meta["y_mode"], midi_low=bundle.meta["y_min"], midi_high=bundle.meta["y_max"],
            row_order=bundle.meta["row_order"], include_provenance=True,
        )
        width = bundle.matrix.shape[1]
        single.matrix = np.pad(single.matrix[:, :width], ((0, 0), (0, max(0, width - single.matrix.shape[1]))))
        single.meta.update(num_cols=width, time_end=width * bundle.meta["resolution"],
                           source_time_origin=bundle.meta.get("source_time_origin", 0.0))
        single.decoded_df = binary_slice_to_df(single.matrix, single.meta)
        single.reconstructed_df = (None if bundle.meta["y_mode"] == "chroma" else
                                   binary_matrix_to_df_from_meta(single.matrix, single.meta))
        voices[label] = single
    return voices


def _event_counts(df: pd.DataFrame) -> Counter:
    return Counter(
        (int(midi), round(float(onset), 9), round(float(duration), 9))
        for midi, onset, duration in df[["MIDI", "Global Onset", "Duration"]].itertuples(index=False, name=None)
    )


def audit_binary_roundtrip(bundle: BinaryMatrixBundle) -> dict:
    """Compare source events and reconstructed occupancy on the original grid.

    Event equality compares MIDI, onset and duration, including multiplicity;
    Voice, spelling, articulation, and xml:id are not encoded in binary values.
    Chroma has no unique MIDI reconstruction, so event/grid reconstruction
    results are ``None``. Use decoded pitch-class spans and provenance instead.
    """
    summary = {"source_notes": len(bundle.source_df), "shape": bundle.matrix.shape}
    if bundle.meta["y_mode"] == "chroma":
        return {**summary, "reconstructed_spans": None, "unchanged_events": None,
                "events_equal": None, "changed_cells": None, "grid_equal": None}
    reconstructed = binary_matrix_to_df_from_meta(bundle.matrix, bundle.meta)
    original_events, reconstructed_events = _event_counts(bundle.source_df), _event_counts(reconstructed)
    rebuilt = np.zeros_like(bundle.matrix, dtype=int)
    outside_cells = 0
    if not reconstructed.empty:
        encoded, _ = create_binary_matrix(
            reconstructed, resolution_method="manual",
            manual_resolution=bundle.meta["resolution"], y_mode=bundle.meta["y_mode"],
            midi_low=bundle.meta["y_min"], midi_high=bundle.meta["y_max"],
            row_order=bundle.meta["row_order"],
        )
        common_cols = min(encoded.shape[1], rebuilt.shape[1])
        rebuilt[:, :common_cols] = encoded[:, :common_cols]
        outside_cells = int(np.count_nonzero(encoded[:, common_cols:]))
    changed_cells = int(np.count_nonzero((bundle.matrix != 0) != (rebuilt != 0))) + outside_cells
    return {
        **summary, "reconstructed_spans": len(reconstructed),
        "unchanged_events": sum((original_events & reconstructed_events).values()),
        "events_equal": original_events == reconstructed_events,
        "changed_cells": changed_cells, "grid_equal": changed_cells == 0,
    }


def compare_voice_roundtrips(bundle: BinaryMatrixBundle) -> pd.DataFrame:
    """Audit merged/separate voices with the same pitch axes and time step."""
    rows = [{"scope": "all voices merged", **audit_binary_roundtrip(bundle)}]
    if "Voice" in bundle.source_df:
        for voice, single in split_binary_voices(bundle).items():
            rows.append({"scope": voice, **audit_binary_roundtrip(single)})
    return pd.DataFrame(rows).set_index("scope")


def describe_binary_span_sources(bundle: BinaryMatrixBundle) -> pd.DataFrame:
    """Attach source counts/IDs to contiguous spans, including merged events.

    Several source notes can contribute to one span after unioning their cells;
    these are references to the original table, not reconstructed event
    identities. Requires a bundle with provenance to report source counts.
    """
    spans = binary_slice_to_df(bundle.matrix, bundle.meta)
    counts, identities, voices = [], [], []
    for _, span in spans.iterrows():
        sources = get_binary_window_provenance(
            bundle.meta, int(span["Binary Row"]), int(span["Binary Row"]) + 1,
            int(span["Binary Col Start"]), int(span["Binary Col End"]),
        )["source_rows"]
        counts.append(len(sources))
        identities.append([source["xml_id"] for source in sources if source.get("xml_id")])
        voices.append(list(dict.fromkeys(source.get("Voice") for source in sources)))
    return spans.assign(source_count=counts, source_xml_ids=identities, source_voices=voices)


def plot_note_comparison(tables: Mapping[str, pd.DataFrame], *, highlighted_ids=()):
    """Compare note events on shared musical axes; outlines preserve boundaries.

    Notes are colored by voice, or blue when no voice is known. Selected source
    xml:ids receive a magenta outline; reconstructed notes have no source IDs.
    """
    from matplotlib.patches import Rectangle

    if not tables or any(table.empty for table in tables.values()):
        raise ValueError("Provide nonempty note tables to compare.")
    all_notes = pd.concat(tables.values(), ignore_index=True)
    voices = list(dict.fromkeys(all_notes.get("Voice", pd.Series(dtype=str)).dropna().astype(str)))
    colors = {voice: plt.get_cmap("tab10")(i % 10) for i, voice in enumerate(voices)}
    selected = set(highlighted_ids)
    fig, axes = plt.subplots(len(tables), 1, figsize=(12, 2.6 * len(tables)),
                             sharex=True, sharey=True, squeeze=False, constrained_layout=True)
    for ax, (label, table) in zip(axes.flat, tables.items()):
        for _, event in table.iterrows():
            highlight = event.get("xml_id") in selected
            ax.add_patch(Rectangle(
                (event["Global Onset"], event["MIDI"] - 0.38), event["Duration"], 0.76,
                facecolor=colors.get(str(event.get("Voice")), "#4b83b7"), alpha=0.75,
                edgecolor="#c00080" if highlight else "#152b3c", linewidth=2.5 if highlight else 0.8,
            ))
        ax.set(title=f"{label} ({len(table)} events)", ylabel="MIDI pitch")
        ax.grid(axis="x", alpha=0.2)
    axes[-1, 0].set(
        xlabel="Time (quarter lengths)",
        xlim=(min(0, all_notes["Global Onset"].min()), (all_notes["Global Onset"] + all_notes["Duration"]).max() + 0.1),
        ylim=(all_notes["MIDI"].min() - 1, all_notes["MIDI"].max() + 1),
    )
    return fig


def compare_binary_resolutions(
    notes: pd.DataFrame, resolutions=(0.125, 0.25, 0.5, 1.0), *, row_order="high_to_low",
) -> tuple[pd.DataFrame, dict[str, BinaryMatrixBundle]]:
    """Compare manual grids and the automatic minimum-duration grid.

    Errors measure each source event's rasterized boundaries before unioning
    overlapping cells. Occupied pitch-time measures the union, in pitch × QL.
    """
    rows, bundles = [], {}
    for value in [*resolutions, None]:
        label = "auto (min duration)" if value is None else f"{value:g} QL"
        bundle = create_binary_matrix_bundle(
            notes, source_name=label,
            resolution_method="auto" if value is None else "manual",
            manual_resolution=value, row_order=row_order,
        )
        resolution = bundle.meta["resolution"]
        onsets = notes["Global Onset"].to_numpy(float)
        ends = onsets + notes["Duration"].to_numpy(float)
        keep = (notes["Duration"].to_numpy(float) > 0) & (ends > 0)
        onsets, ends = onsets[keep], ends[keep]
        starts_grid = np.maximum(0, np.floor(_binary_grid_positions(onsets, resolution))) * resolution
        ends_grid = np.ceil(_binary_grid_positions(ends, resolution)) * resolution
        rows.append({
            "grid": label, "resolution_QL": resolution, "columns": bundle.matrix.shape[1],
            "occupied_pitch_QL": np.count_nonzero(bundle.matrix) * resolution,
            "max_onset_error_QL": float(np.max(np.abs(starts_grid - onsets))),
            "max_end_error_QL": float(np.max(np.abs(ends_grid - ends))),
            **{k: v for k, v in audit_binary_roundtrip(bundle).items()
               if k in ("reconstructed_spans", "events_equal", "grid_equal")},
        })
        bundles[label] = bundle
    return pd.DataFrame(rows).set_index("grid"), bundles


def plot_binary_comparison(
    bundles: Mapping[str, BinaryMatrixBundle], *, ncols=2, title=None,
):
    """Plot musical pitch increasing upwards, regardless of raw storage order.

    Full MIDI grids show 0 at the bottom and 127 at the top. Raw row indices
    remain available in metadata; they are not substituted for MIDI labels.
    Returns a Matplotlib figure without displaying it.
    """
    if not bundles:
        raise ValueError("Provide at least one bundle to plot.")
    ncols = min(max(1, int(ncols)), len(bundles))
    nrows = (len(bundles) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 3.1 * nrows), squeeze=False,
                             constrained_layout=True)
    for ax, (label, bundle) in zip(axes.flat, bundles.items()):
        height, width = bundle.matrix.shape
        low, high = bundle.meta["y_min"], bundle.meta["y_max"]
        reverse = bundle.meta["row_order"] == "high_to_low"
        mat = bundle.matrix[::-1] if reverse else bundle.matrix
        labels = bundle.meta["row_axis_labels"][::-1] if reverse else bundle.meta["row_axis_labels"]
        ax.imshow(mat, cmap="Greys", interpolation="nearest", origin="lower", vmin=0, vmax=1,
                  aspect="auto", extent=(0, width * bundle.meta["resolution"], low - 0.5, high + 0.5))
        ticks = np.unique(np.linspace(low, high, min(8, height), dtype=int))
        chroma = bundle.meta["y_mode"] == "chroma"
        ax.set_yticks(ticks, [labels[i - low] if chroma else f"{i}: {labels[i - low]}" for i in ticks])
        ax.set(xlabel="Time (quarter lengths)", ylabel="Pitch class" if chroma else "MIDI pitch",
               title=f"{label}\n{height} × {width}; active cells = {np.count_nonzero(bundle.matrix)}")
    for ax in list(axes.flat)[len(bundles):]:
        ax.set_visible(False)
    if title:
        fig.suptitle(title, fontsize=14)
    return fig


def extract_binary_kernel(bundle: BinaryMatrixBundle, start_ql: float, end_ql: float) -> dict:
    """Copy a time window, trim silent pitch margins, and retain its origin.

    Use a bundle from ``split_binary_voices`` to extract a single voice. Slicing
    the existing grid includes notes sounding before the requested start and
    preserves silent time columns. Non-grid boundaries expand to the covering
    cells; the returned window records the actual bounds, clipped to the host.
    """
    if bundle.meta["y_mode"] == "chroma":
        raise ValueError("MIDI kernel extraction requires minmax/full, not chroma.")
    start_ql, end_ql = float(start_ql), float(end_ql)
    if not np.isfinite([start_ql, end_ql]).all() or not 0 <= start_ql < end_ql:
        raise ValueError("Choose finite times with 0 <= start_ql < end_ql.")
    edges = _binary_grid_positions(np.array([start_ql, end_ql]), bundle.meta["resolution"])
    c0 = min(bundle.matrix.shape[1], int(np.floor(edges[0])))
    c1 = min(bundle.matrix.shape[1], int(np.ceil(edges[1])))
    patch = bundle.matrix[:, c0:c1]
    rows = np.flatnonzero(patch.any(axis=1))
    if not len(rows):
        raise ValueError("The selected time window contains no active cells.")
    r0, r1 = int(rows[0]), int(rows[-1]) + 1
    window = bundle.slice(row_start=r0, col_start=c0, n_rows=r1-r0, n_cols=c1-c0)
    return {"kernel": window.matrix_slice.copy(), "row": r0, "col": c0, "window": window,
            "grid_span_QL": (c0 * bundle.meta["resolution"], c1 * bundle.meta["resolution"]),
            "anchor_MIDI": bundle.meta["row_axis_values"][r0]}


def rank_binary_matches(
    bundle: BinaryMatrixBundle, kernel: np.ndarray, score_map: pd.DataFrame, *,
    top_n=5, min_score=None, max_window_iou=None, exclude_time_span=None,
    metric="normalized_overlap",
) -> dict:
    """Rank a labeled score map from ``run_pattern_search`` at valid placements.

    Index/column labels are raw host coordinates, including when using strides.
    Ties sort by raw row then column. ``max_window_iou`` optionally suppresses
    windows whose rectangle intersection-over-union exceeds that value with an
    already selected window. ``exclude_time_span=(start, end)`` excludes every
    window overlapping that grid-time span, in any register. Filters affect the
    returned matches, while the heatmap retains all computed scores.

    This MIDI/provenance adapter supports ``padding='valid'`` only; it rejects
    padded coordinates rather than wrapping negative indices into the source.
    All supported CAMAT metrics rank higher scores first.
    """
    kernel = np.asarray(kernel)
    if kernel.ndim != 2 or not kernel.size or not np.isfinite(kernel).all() or np.any(kernel < 0) or not kernel.any():
        raise ValueError("Provide a nonempty, nonnegative kernel with active weight.")
    if bundle.meta["y_mode"] == "chroma":
        raise ValueError("This MIDI trace uses minmax/full; chroma needs pitch-class placement semantics.")
    if int(top_n) < 1:
        raise ValueError("top_n must be positive.")
    if min_score is not None and not np.isfinite(min_score):
        raise ValueError("min_score must be finite.")
    if max_window_iou is not None and not 0 <= max_window_iou <= 1:
        raise ValueError("max_window_iou must be within [0, 1].")
    if exclude_time_span is not None:
        a, b = exclude_time_span
        if not np.isfinite([a, b]).all() or a >= b:
            raise ValueError("exclude_time_span needs finite start < end in grid QL.")
    if not score_map.index.is_unique or not score_map.columns.is_unique:
        raise ValueError("Score-map coordinates must be unique.")
    frame = score_map.sort_index().sort_index(axis=1)
    h, w = kernel.shape
    rows, cols = list(frame.index), list(frame.columns)
    for positions, limit in ((rows, bundle.matrix.shape[0] - h), (cols, bundle.matrix.shape[1] - w)):
        if any(not np.isfinite(p) or int(p) != p or not 0 <= p <= limit for p in positions):
            raise ValueError("Score-map labels must be valid host coordinates; use padding='valid'.")
    scores = frame.to_numpy(dtype=float)
    resolution = bundle.meta["resolution"]
    records = []
    for flat in np.argsort(-scores.ravel(), kind="stable"):
        i, j = np.unravel_index(flat, scores.shape)
        score = float(scores[i, j])
        if not np.isfinite(score) or (min_score is not None and score < min_score):
            continue
        row, col = int(rows[i]), int(cols[j])
        if exclude_time_span is not None and col * resolution < b and (col + w) * resolution > a:
            continue
        if max_window_iou is not None:
            intersections = [max(0, h - abs(row - hit["row"])) * max(0, w - abs(col - hit["col"]))
                             for hit in records]
            if any(area / (2 * h * w - area) > max_window_iou for area in intersections):
                continue
        records.append({
            "score": score, "row": row, "col": col,
            "grid_onset_QL": col * resolution,
            "source_onset_QL": col * resolution + bundle.meta.get("source_time_origin", 0.0),
            "anchor_MIDI": bundle.meta["row_axis_values"][row],
        })
        if len(records) == int(top_n):
            break
    return {"scores": scores, "rows": rows, "cols": cols, "metric": metric,
            "matches": pd.DataFrame(records, columns=["score", "row", "col", "grid_onset_QL", "source_onset_QL", "anchor_MIDI"])}


def find_binary_matches(bundle: BinaryMatrixBundle, kernel: np.ndarray, *, top_n=5) -> dict:
    """Search a binary kernel with normalized overlap and valid placements.

    Returns the heatmap, raw placement coordinates and ranked matches. Scores
    measure containment: extra host notes are not penalized. Ties sort by raw
    row then column; adjacent placements are retained for inspection.
    """
    from .pattern_search import convolution_map

    kernel = np.asarray(kernel)
    if kernel.ndim != 2 or not kernel.size or not np.isin(kernel, [0, 1]).all() or not kernel.any():
        raise ValueError("Provide a nonempty binary kernel with at least one active cell.")
    scores, rows, cols, _ = convolution_map(bundle.matrix, kernel, padding="valid")
    # An oversized kernel has no valid placements, including on either axis.
    if not scores.size:
        rows, cols, scores = [], [], np.empty((0, 0))
    return rank_binary_matches(bundle, kernel, pd.DataFrame(scores, index=rows, columns=cols), top_n=top_n)


def binary_match_sources(bundle: BinaryMatrixBundle, kernel: np.ndarray, row: int, col: int) -> dict:
    """Trace one valid placement to window notes and query-contributing notes.

    Only occupied host cells required by the kernel contribute matching source
    IDs. The complete rectangle can also contain unrelated accompaniment.
    Source notes keep their full durations, even when only part overlaps a cell.
    """
    from .pattern_search import score_kernel_at

    kernel = np.asarray(kernel)
    row, col = int(row), int(col)
    _, _, raw, score = score_kernel_at(bundle.matrix, kernel, row, col)
    window = bundle.slice(row_start=row, col_start=col, n_rows=kernel.shape[0], n_cols=kernel.shape[1])
    window_notes = get_binary_window_provenance(
        bundle.meta, window.row_start, window.row_end, window.col_start, window.col_end, as_dataframe=True,
    )["source_df"]
    contributors = {}
    missing = []
    for dr, dc in zip(*np.nonzero(kernel)):
        r, c = row + int(dr), col + int(dc)
        if not bundle.matrix[r, c]:
            missing.append((r, c))
            continue
        for source in get_binary_cell_provenance(bundle.meta, r, c)["source_rows"]:
            contributors[source["source_row_position"]] = source
    return {"window": window, "window_notes": window_notes,
            "matched_notes": pd.DataFrame(contributors.values()), "missing_cells": missing,
            "raw_overlap": raw, "score": score}


def plot_binary_search_trace(bundle: BinaryMatrixBundle, kernel: np.ndarray, result: dict, *, rank=0, title=None):
    """Show query → heatmap peak → the same placement on a musical binary plot.

    Axes use QL and MIDI, while the title reports the corresponding raw indices.
    Magenta outlines mark occupied query cells, red crosses mark missing cells.
    Pass ``binary_match_sources``' matching notes to Verovio for the next link.
    """
    from matplotlib.patches import Rectangle

    if result["matches"].empty:
        raise ValueError("The kernel has no valid placements in this host.")
    hit = result["matches"].iloc[int(rank)]
    row, col = int(hit["row"]), int(hit["col"])
    kernel = np.asarray(kernel)
    h, w = kernel.shape
    resolution = bundle.meta["resolution"]
    reverse = bundle.meta["row_order"] == "high_to_low"
    metric = result.get("metric", "normalized_overlap")
    metric_label = metric.replace("_", " ").capitalize()
    if metric == "normalized_overlap":
        bounds = (0, 1)
    elif metric == "normalized_cross_correlation":
        bounds = (-1, 1)
    else:
        finite = np.asarray(result["scores"])[np.isfinite(result["scores"])]
        bounds = (float(finite.min()), float(finite.max()))
    fig, axes = plt.subplots(1, 3, figsize=(15, 3.8), gridspec_kw={"width_ratios": [1, 1.6, 1.6]},
                             constrained_layout=True)
    axes[0].imshow(kernel[::-1] if reverse else kernel, origin="lower", cmap="Greys", vmin=0, vmax=1,
                   interpolation="nearest", aspect="auto", extent=(0, w * resolution, -0.5, h - 0.5))
    axes[0].set(title="Query kernel", xlabel="Relative time (QL)", ylabel="Semitones above kernel bottom")
    axes[0].set_yticks(np.unique(np.linspace(0, h - 1, min(8, h), dtype=int)))
    anchors = np.asarray([bundle.meta["row_axis_values"][r] for r in result["rows"]])
    times = np.asarray(result["cols"]) * resolution
    scores = result["scores"][::-1] if reverse else result["scores"]
    time_step = times[1] - times[0] if len(times) > 1 else resolution
    pitch_step = abs(anchors[1] - anchors[0]) if len(anchors) > 1 else 1
    heat = axes[1].imshow(scores, origin="lower", aspect="auto", cmap="viridis", vmin=bounds[0], vmax=bounds[1],
                         interpolation="nearest", extent=(times.min() - time_step / 2, times.max() + time_step / 2,
                                                           anchors.min() - pitch_step / 2, anchors.max() + pitch_step / 2))
    axes[1].scatter([hit["grid_onset_QL"]], [hit["anchor_MIDI"]], s=90, facecolors="none", edgecolors="#ff38ac", linewidths=2)
    # Leave room for the peak marker even at the first/last valid placement.
    x_margin = max(time_step, (times.max() - times.min()) * 0.02)
    axes[1].set_xlim(times.min() - x_margin, times.max() + x_margin)
    axes[1].set_ylim(anchors.min() - 1, anchors.max() + 1)
    axes[1].set_yticks(np.unique(np.linspace(anchors.min(), anchors.max(), min(8, len(anchors)), dtype=int)))
    axes[1].set(title=f"Heatmap: selected score = {hit['score']:.2f}", xlabel="Placement time (grid QL)",
                ylabel="MIDI at kernel raw row 0")
    fig.colorbar(heat, ax=axes[1], label=metric_label, shrink=0.8)
    r0, r1 = max(0, row - 3), min(bundle.matrix.shape[0], row + h + 3)
    c0, c1 = max(0, col - 4), min(bundle.matrix.shape[1], col + w + 4)
    pitch_values = bundle.meta["row_axis_values"][r0:r1]
    patch = bundle.matrix[r0:r1, c0:c1]
    axes[2].imshow(patch[::-1] if reverse else patch, origin="lower", aspect="auto", cmap="Greys", vmin=0, vmax=1,
                   interpolation="nearest", extent=(c0 * resolution, c1 * resolution, min(pitch_values) - 0.5, max(pitch_values) + 0.5))
    query_pitches = bundle.meta["row_axis_values"][row:row+h]
    axes[2].add_patch(Rectangle((col * resolution, min(query_pitches) - 0.5), w * resolution, h,
                               fill=False, edgecolor="#cf268c", linewidth=2, linestyle="--"))
    for dr, dc in zip(*np.nonzero(kernel)):
        midi = bundle.meta["row_axis_values"][row + int(dr)]
        start = (col + int(dc)) * resolution
        if bundle.matrix[row + dr, col + dc]:
            axes[2].add_patch(Rectangle((start, midi - 0.5), resolution, 1, fill=False,
                                       edgecolor="#ff38ac", linewidth=1.8))
        else:
            axes[2].plot(start + resolution / 2, midi, "x", color="#d62728")
    axes[2].set(title=f"Host window: raw row={row}, col={col}", xlabel="Grid time (QL)", ylabel="MIDI pitch")
    if title:
        fig.suptitle(title, fontsize=14)
    return fig
