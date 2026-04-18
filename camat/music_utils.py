from __future__ import annotations

from dataclasses import dataclass, field
import os
import tempfile
import warnings
from typing import List, Tuple, Optional, Dict, Any, Iterable, Sequence, Union
import textwrap

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from music21 import note, chord, pitch as pitch_module
try:
    from tqdm.auto import tqdm as _tqdm  # Notebook/terminal-friendly progress bar
except Exception:  # pragma: no cover - optional dependency at runtime
    _tqdm = None


__all__ = [
    "get_file_path",
    "get_download_cache_dir",
    "is_cached_download",
    "extract_voice_data",
    "filter_and_adjust_durations",
    "get_measure_offsets",
    "draw_piano_roll",
    "canonicalize_pitch_name",
    "accidental_rank_from_name",
    "create_piano_roll",
    "parse_files",
    "create_binary_matrix",
    "plot_binary_matrix",
    "prepare_binary_hover_fields",
    "describe_binary_matrix",
    "print_binary_matrix_summary",
    "BinaryMatrixBundle",
    "BinaryMatrixSliceBundle",
    "create_binary_matrix_bundle",
    "create_binary_matrix_slice_bundle",
    "orient_binary_matrix",
    "get_binary_row_info",
    "get_binary_col_info",
    "get_binary_cell_provenance",
    "get_binary_window_provenance",
    "binary_slice_to_df",
    "binary_matrix_to_df",
    "binary_matrix_to_df_from_meta",
    "binary_matrix_to_df_from_bounds",
    "round_trip_sanity_check",
    "parse_prototype_notation",
    "parse_notation",
    "create_prototype_binary_matrix",
    "plot_prototype_binary_matrix",
]

BOKEH_NOTEBOOK_INITIALIZED = False


def _get_requests_module():
    """
    Import requests lazily so local-only workflows do not emit dependency warnings.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import requests  # type: ignore
    return requests


def get_download_cache_dir(cache_dir: Optional[str] = None) -> str:
    """
    Resolve and ensure the persistent download cache directory exists.

    Precedence:
        1. Explicit ``cache_dir`` argument
        2. ``CAMAT_DOWNLOAD_CACHE_DIR`` environment variable
        3. ``~/.cache/camat/downloads``
    """
    if cache_dir is None:
        cache_dir = os.environ.get("CAMAT_DOWNLOAD_CACHE_DIR") or os.path.join(
            os.path.expanduser("~"), ".cache", "camat", "downloads"
        )
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _cached_download_filename(file_source: str) -> str:
    """
    Build a filesystem-safe filename for a remote ``file_source``.

    Uses a sha1 digest of the URL + the original extension so cached files remain
    inspectable and the path collides deterministically on re-use.
    """
    import hashlib

    digest = hashlib.sha1(file_source.encode("utf-8", errors="ignore")).hexdigest()[:16]
    _, ext = os.path.splitext(file_source.split("?", 1)[0].split("#", 1)[0])
    return f"{digest}{ext}"


def is_cached_download(path: str, cache_dir: Optional[str] = None) -> bool:
    """Return True when ``path`` lives under the persistent download cache."""
    if not path:
        return False
    try:
        base = os.path.abspath(get_download_cache_dir(cache_dir))
        return os.path.abspath(path).startswith(base + os.sep)
    except Exception:
        return False


def get_file_path(
    file_source: str,
    *,
    timeout_seconds: int = 30,
    use_cache: bool = False,
    cache_dir: Optional[str] = None,
) -> str:
    """
    Resolve a local path from a URL or verify a local path exists.

    Parameters
    ----------
    file_source : str
        URL or local file path.
    timeout_seconds : int, optional
        Timeout for downloading remote files (seconds). Default is 30.
    use_cache : bool, optional
        When True, remote files are stored in a persistent cache keyed by a
        sha1 of the URL. Repeated calls with the same URL return the cached
        path without re-downloading. Default is False to preserve backward
        compatible behavior.
    cache_dir : str, optional
        Override the cache location. Falls back to ``CAMAT_DOWNLOAD_CACHE_DIR``
        and ``~/.cache/camat/downloads``.

    Returns
    -------
    str
        Local filesystem path to the file.

    Raises
    ------
    ValueError
        If there's an issue downloading a remote file.
    FileNotFoundError
        If the local file does not exist.
    """
    if file_source.startswith(("http://", "https://")):
        if use_cache:
            resolved_dir = get_download_cache_dir(cache_dir)
            cached_path = os.path.join(resolved_dir, _cached_download_filename(file_source))
            if os.path.exists(cached_path) and os.path.getsize(cached_path) > 0:
                return cached_path
            requests = _get_requests_module()
            try:
                response = requests.get(file_source, stream=True, timeout=timeout_seconds)
                response.raise_for_status()
                tmp_path = cached_path + ".part"
                with open(tmp_path, "wb") as fh:
                    fh.write(response.content)
                os.replace(tmp_path, cached_path)
                return cached_path
            except requests.RequestException as exc:
                raise ValueError(f"Error downloading the file: {exc}") from exc

        requests = _get_requests_module()
        try:
            response = requests.get(file_source, stream=True, timeout=timeout_seconds)
            response.raise_for_status()
            _, file_extension = os.path.splitext(file_source)
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_extension)
            with temp_file as tf:
                tf.write(response.content)
            return temp_file.name
        except requests.RequestException as exc:
            raise ValueError(f"Error downloading the file: {exc}") from exc
    else:
        if os.path.exists(file_source):
            return file_source
        raise FileNotFoundError(f"Local file does not exist: {file_source}")


def extract_voice_data(score) -> List[Tuple[int, float, float, float, str, str]]:
    """
    Extract measure number, onset, duration, pitch, and voice/channel labels from a music21 score.

    Parameters
    ----------
    score : music21.stream.Score
        The music21 score object.

    Returns
    -------
    list[tuple]
        Each tuple contains (Measure, Local Onset, Global Onset, Duration, Pitch, Voice).
    """

    def _resolve_voice_label(element: Any) -> str:
        labels: List[str] = []

        part = element.getContextByClass("Part")
        if part is not None:
            part_name = getattr(part, "partName", None) or getattr(part, "partAbbreviation", None) or getattr(part, "id", None)
            if part_name:
                part_label = str(part_name).strip()
                if part_label and part_label not in labels:
                    labels.append(part_label)

        try:
            instrument_obj = element.getInstrument(returnDefault=False)
        except Exception:
            instrument_obj = None

        if instrument_obj is not None:
            inst_name = getattr(instrument_obj, "instrumentName", None) or getattr(instrument_obj, "partName", None) or getattr(instrument_obj, "instrumentAbbreviation", None)
            if inst_name:
                inst_label = str(inst_name).strip()
                if inst_label and inst_label not in labels:
                    labels.append(inst_label)

        voice_ctx = element.getContextByClass("Voice")
        voice_label = None
        if voice_ctx is not None:
            raw_voice = getattr(voice_ctx, "id", None) or getattr(voice_ctx, "name", None)
            if raw_voice:
                voice_label = str(raw_voice).strip()
                if voice_label.isdigit():
                    voice_label = f"Voice {voice_label}"
            else:
                voice_index = getattr(voice_ctx, "index", None)
                if voice_index is not None:
                    voice_label = f"Voice {voice_index}"
                else:
                    voice_label = "Voice"
            if voice_label and voice_label not in labels:
                labels.append(voice_label)

        if not labels:
            return "Unknown"

        return " / ".join(labels)

    voice_data: List[Tuple[int, float, float, float, str, str]] = []
    notes_and_chords = score.flatten().notesAndRests.stream()

    for element in notes_and_chords:
        if isinstance(element, (note.Note, chord.Chord)):
            # Get the measure context
            measure = element.getContextByClass("Measure")
            if measure is not None:
                measure_num = measure.number
                measure_offset = measure.offset
            else:
                # If measure context is not found, default to 0
                measure_num = 0
                measure_offset = 0.0

            global_onset = element.offset
            local_onset = global_onset - measure_offset
            duration = element.duration.quarterLength

            # Handle notes and chords
            if isinstance(element, note.Note):
                pitches = [str(element.pitch)]
            else:
                pitches = [str(p) for p in element.pitches]

            voice_label = _resolve_voice_label(element)

            # Append data for each pitch
            for p in pitches:
                voice_data.append((measure_num, local_onset, global_onset, duration, p, voice_label))

    return voice_data


def draw_piano_roll(
    df: pd.DataFrame,
    measure_offsets: Optional[List[float]] = None,
    *,
    backend: str = "plt",
    barline_events: Optional[pd.DataFrame] = None,
    plot_parsed_barlines_with_voice_coloring: bool = False,
    show_measure_lines: bool = True,
    measure_line_color: str = "red",
    show_hover: bool = True,
    hover_fields: Optional[Sequence[str]] = None,
    pitch_labels: bool = True,
    show: bool = True,
    plot_width: Optional[int] = None,
    plot_height: Optional[int] = None,
    dpi: float = 100.0,
    zoom_drag_dim: Optional[str] = None,
    zoom_wheel_dim: Optional[str] = None,
    save_html: Optional[bool] = None,
    save_html_path: Optional[str] = None,
    save_png_path: Optional[str] = None,
    open_html_after_save: bool = False,
    colorize_voices: bool = False,
    palette: Optional[Union[str, Sequence[str]]] = None,
    voice_color_order: Optional[Sequence[str]] = None,
) -> Any:
    """
    Draw a piano roll visualization using the selected backend.

    Parameters
    ----------
    df : pandas.DataFrame
        Must contain 'Global Onset', 'Duration', 'MIDI', and 'Pitch'.
    measure_offsets : list[float], optional
        Global onset times where measures start. Vertical lines drawn at these positions.
    backend : {"plt", "bokeh"}
        Plotting backend to use.
    barline_events : pandas.DataFrame, optional
        Event DataFrame (typically `df_events`) containing parsed barlines.
        Expected fields include 'type', 'Global Onset', 'Voice', and 'form'.
    plot_parsed_barlines_with_voice_coloring : bool
        If True, overlay parsed barline events and color them by Voice labels.
    show_measure_lines : bool
        Whether to draw vertical red measure separation lines when measure offsets are provided.
    measure_line_color : str
        Color for the vertical measure lines when show_measure_lines is True.
        Accepts any Matplotlib/Bokeh color string (e.g., 'crimson', '#ff0000').
    show_hover : bool
        When backend == 'bokeh', add a HoverTool with configurable fields. Default True.
    hover_fields : Sequence[str], optional
        List of fields to show in the hover tooltip (bokeh only). Supported keys:
        ['pitch', 'midi', 'voice', 'measure', 'global_onset', 'local_onset', 'duration', 'xml_id'].
        Defaults to a sensible ordering when None.
    pitch_labels : bool
        Whether to use pitch names on the y-axis when supported.
    show : bool
        Whether to immediately show the plot (where applicable).
    plot_width : int, optional
        Width in pixels for both backends. If None, defaults to 900.
    plot_height : int, optional
        Height in pixels for both backends. If None, defaults to 600.
    dpi : float, optional
        DPI for matplotlib backend (used to convert pixels to inches). Default is 100.
    zoom_drag_dim : {"width", "height", "both"}, optional
        Dimension for box zoom drag tool (Bokeh only). None defaults to "both".
    zoom_wheel_dim : {"width", "height", "both"}, optional
        Dimension for wheel zoom tool (Bokeh only). None defaults to "both".
    save_html : bool, optional
        If None (default), behaves like legacy mode: saves HTML when save_html_path is provided.
        If True, saves HTML to save_html_path if provided, otherwise to "piano_roll.html".
        If False, disables HTML saving regardless of save_html_path.
    save_html_path : str, optional
        When backend == 'bokeh', if provided, saves the plot as a standalone HTML file.
    save_png_path : str, optional
        When backend == 'bokeh', if provided, attempts to export a PNG. Requires selenium
        and a compatible webdriver installed (e.g., chromedriver or geckodriver).
    open_html_after_save : bool, optional
        If True and save_html_path is provided, attempts to open the saved HTML in a browser.
    colorize_voices : bool, optional
        When True and a 'Voice' column is present in df, color notes by voice/part.
        Defaults to False (uniform color).
    palette : str | Sequence[str], optional
        Color palette to use when colorizing voices. Accepts:
          - A sequence of color strings (hex or named), or
          - A palette name:
              * For Matplotlib (plt): any valid colormap name (e.g., 'tab20', 'tab10', 'Set3')
              * For Bokeh: any key in bokeh.palettes.all_palettes (e.g., 'Category10', 'Category20')
        If not provided, a sensible categorical default is used.
    voice_color_order : Sequence[str], optional
        Optional global voice ordering used for stable color assignment across
        filtered subsets. When provided, voices in `df['Voice']` use colors
        based on this order instead of first appearance in `df`.

    Returns
    -------
    Any
        A backend-specific figure object when show=False; None when show=True.
    """
    backend = (backend or "plt").lower()

    # Unique MIDI to pitch mapping for ticks/labels
    midi_to_pitch = df.drop_duplicates("MIDI").sort_values("MIDI").set_index("MIDI")["Pitch"].to_dict()
    midi_values = list(midi_to_pitch.keys())

    # Set default dimensions if not provided
    width_pixels = plot_width or 900
    height_pixels = plot_height or 600

    # ----------------------------
    # Voice-based color resolution
    # ----------------------------
    def _default_categorical_colors() -> List[str]:
        # Matplotlib tab10 colors as sane default usable in both backends
        return [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
            "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
        ]

    def _resolve_palette_matplotlib(pal: Optional[Union[str, Sequence[str]]], n: int) -> List[str]:
        from matplotlib import colors as mcolors  # local import to avoid global dependency elsewhere
        # Map common cross-backend names to Matplotlib equivalents
        def _pal_alias(name: str) -> str:
            key = name.strip().lower()
            if key in {"category10"}:
                return "tab10"
            if key in {"category20"}:
                return "tab20"
            return name
        if pal is None:
            base = _default_categorical_colors()
            if n <= len(base):
                return base[:n]
            # Repeat if necessary
            reps = (n + len(base) - 1) // len(base)
            return (base * reps)[:n]
        if isinstance(pal, (list, tuple)):
            base = [str(c) for c in pal]
            if n <= len(base):
                return base[:n]
            reps = (n + len(base) - 1) // len(base)
            return (base * reps)[:n]
        # Treat as a Matplotlib colormap name
        try:
            cmap = plt.get_cmap(_pal_alias(str(pal)))
            if n <= 1:
                return [mcolors.to_hex(cmap(0.0))]
            return [mcolors.to_hex(cmap(i / max(1, n - 1))) for i in range(n)]
        except Exception:
            base = _default_categorical_colors()
            if n <= len(base):
                return base[:n]
            reps = (n + len(base) - 1) // len(base)
            return (base * reps)[:n]

    def _resolve_palette_bokeh(pal: Optional[Union[str, Sequence[str]]], n: int) -> List[str]:
        # Avoid importing bokeh unless necessary
        def _pal_alias(name: str) -> str:
            key = name.strip().lower()
            if key in {"tab10"}:
                return "Category10"
            if key in {"tab20"}:
                return "Category20"
            return name
        if pal is None:
            base = _default_categorical_colors()
            if n <= len(base):
                return base[:n]
            reps = (n + len(base) - 1) // len(base)
            return (base * reps)[:n]
        if isinstance(pal, (list, tuple)):
            base = [str(c) for c in pal]
            if n <= len(base):
                return base[:n]
            reps = (n + len(base) - 1) // len(base)
            return (base * reps)[:n]
        # Palette name: try bokeh.palettes
        try:
            from bokeh.palettes import all_palettes  # type: ignore
            pal_name = _pal_alias(str(pal))
            if pal_name in all_palettes:
                sizes = sorted(all_palettes[pal_name].keys())
                # Pick the largest available size not exceeding n, else the largest overall
                size_choice = max([s for s in sizes if s <= max(n, 3)], default=max(sizes))
                base = list(all_palettes[pal_name][size_choice])
                if n <= len(base):
                    return base[:n]
                reps = (n + len(base) - 1) // len(base)
                return (base * reps)[:n]
            # Some palettes (e.g., 'Viridis256') may be exposed differently
            try:
                from bokeh import palettes as _pal_mod  # type: ignore
                base = getattr(_pal_mod, pal_name, None)
                if isinstance(base, (list, tuple)):
                    base = list(base)
                    if n <= len(base):
                        return base[:n]
                    reps = (n + len(base) - 1) // len(base)
                    return (base * reps)[:n]
            except Exception:
                pass
        except Exception:
            # Fallback to default if bokeh not available or palette not found
            pass
        base = _default_categorical_colors()
        if n <= len(base):
            return base[:n]
        reps = (n + len(base) - 1) // len(base)
        return (base * reps)[:n]

    def _voice_color_mapping(for_backend: str) -> Optional[List[str]]:
        if not colorize_voices or "Voice" not in df.columns:
            return None
        voices_series = df["Voice"].astype(str)
        unique_voices = list(pd.unique(voices_series))
        if not unique_voices:
            return None
        if voice_color_order is not None:
            preferred_full = [str(v) for v in voice_color_order if str(v)]
            all_groups = list(dict.fromkeys(preferred_full + unique_voices))
            if for_backend == "plt":
                all_colors = _resolve_palette_matplotlib(palette, len(all_groups))
            else:
                all_colors = _resolve_palette_bokeh(palette, len(all_groups))
            global_map: Dict[str, str] = {
                v: all_colors[i % len(all_colors)] for i, v in enumerate(all_groups)
            }
            return [global_map.get(v, "#87CEEB") for v in voices_series.tolist()]
        num_groups = len(unique_voices)
        if for_backend == "plt":
            group_colors = _resolve_palette_matplotlib(palette, num_groups)
        else:
            group_colors = _resolve_palette_bokeh(palette, num_groups)
        color_map: Dict[str, str] = {v: group_colors[i % len(group_colors)] for i, v in enumerate(unique_voices)}
        return [color_map[v] for v in voices_series.tolist()]

    def _voice_color_dict(for_backend: str, voices: Sequence[str]) -> Dict[str, str]:
        unique_voices = [str(v) for v in dict.fromkeys(voices) if str(v)]
        if not unique_voices:
            return {}
        if voice_color_order is not None:
            preferred_full = [str(v) for v in voice_color_order if str(v)]
            all_groups = list(dict.fromkeys(preferred_full + unique_voices))
            if for_backend == "plt":
                all_colors = _resolve_palette_matplotlib(palette, len(all_groups))
            else:
                all_colors = _resolve_palette_bokeh(palette, len(all_groups))
            global_map = {
                v: all_colors[i % len(all_colors)] for i, v in enumerate(all_groups)
            }
            return {v: global_map[v] for v in unique_voices if v in global_map}
        if for_backend == "plt":
            group_colors = _resolve_palette_matplotlib(palette, len(unique_voices))
        else:
            group_colors = _resolve_palette_bokeh(palette, len(unique_voices))
        return {
            voice: group_colors[i % len(group_colors)]
            for i, voice in enumerate(unique_voices)
        }

    def _barline_dash_style(form_value: Any, for_backend: str) -> Any:
        key = str(form_value or "").strip().lower()
        if key in {"dashed", "dash"}:
            return "dashed"
        if key in {"dotted", "dot"}:
            return "dotted"
        if key in {"double"}:
            return (0, (6, 2)) if for_backend == "plt" else "dashed"
        return "solid"

    def _iter_barline_events() -> List[Dict[str, Any]]:
        if not plot_parsed_barlines_with_voice_coloring or barline_events is None:
            return []
        try:
            ev_df = pd.DataFrame(barline_events).copy()
        except Exception:
            return []
        if ev_df.empty or "Global Onset" not in ev_df.columns:
            return []
        if "type" in ev_df.columns:
            ev_df = ev_df[ev_df["type"].astype(str).str.lower() == "barline"]
        if ev_df.empty:
            return []
        out_events: List[Dict[str, Any]] = []
        for _, erow in ev_df.iterrows():
            try:
                onset = float(erow.get("Global Onset"))
            except Exception:
                continue
            if not np.isfinite(onset):
                continue
            voice = erow.get("Voice", "")
            form = erow.get("form", "solid")
            out_events.append(
                {
                    "Global Onset": onset,
                    "Voice": str(voice).strip() if voice is not None else "",
                    "form": form,
                }
            )
        return out_events

    if backend == "plt":
        # Convert pixels to inches for matplotlib
        width_inches = width_pixels / dpi
        height_inches = height_pixels / dpi
        fig, ax = plt.subplots(figsize=(width_inches, height_inches))
        row_colors = _voice_color_mapping("plt")
        for idx, (_, row) in enumerate(df.iterrows()):
            color_val = (row_colors[idx] if row_colors is not None else "skyblue")
            ax.barh(
                row["MIDI"],
                width=row["Duration"],
                left=row["Global Onset"],
                height=0.6,
                color=color_val,
                edgecolor="black",
            )

        if pitch_labels:
            ax.set_yticks(midi_values)
            ax.set_yticklabels([midi_to_pitch[m] for m in midi_values])
        ax.set_xlabel("Global Onset (Quarter Lengths)")
        ax.set_ylabel("Pitch")
        ax.set_title("Piano Roll Visualization")

        if show_measure_lines and measure_offsets is not None:
            for m_offset in measure_offsets:
                ax.axvline(x=m_offset, color=str(measure_line_color), linestyle="--", linewidth=0.8)

        barline_plot_events = _iter_barline_events()
        if barline_plot_events:
            voice_order = [evt["Voice"] for evt in barline_plot_events if evt["Voice"]]
            voice_colors = _voice_color_dict("plt", voice_order)
            for evt in barline_plot_events:
                color = voice_colors.get(evt["Voice"], str(measure_line_color))
                ax.axvline(
                    x=evt["Global Onset"],
                    color=str(color),
                    linestyle=_barline_dash_style(evt.get("form"), "plt"),
                    linewidth=1.1,
                    alpha=0.9,
                )

        ax.grid(True, axis="x", linestyle="--", alpha=0.7)
        fig.tight_layout()
        if show:
            plt.show()
            # Prevent Jupyter from auto-displaying the returned figure again
            plt.close(fig)
            return None
        return fig

    if backend == "bokeh":
        try:
            from bokeh.plotting import figure, show as bokeh_show
            from bokeh.models import Span, ColumnDataSource, BoxZoomTool, WheelZoomTool, PanTool, HoverTool
            # Initialize inline output in notebooks once
            global BOKEH_NOTEBOOK_INITIALIZED
            if not BOKEH_NOTEBOOK_INITIALIZED:
                try:
                    from IPython import get_ipython  # type: ignore
                    ip = get_ipython()
                except Exception:
                    ip = None
                if ip is not None:
                    try:
                        from bokeh.io import output_notebook
                        # Force inline resources to avoid CDN issues in restricted/offline environments
                        try:
                            from bokeh.resources import INLINE
                        except Exception:
                            INLINE = "inline"
                        output_notebook(hide_banner=True, resources=INLINE)
                        BOKEH_NOTEBOOK_INITIALIZED = True
                    except Exception:
                        # If initialization fails, continue; show() may open a new tab
                        pass
        except ImportError as exc:
            raise ImportError("Bokeh is not installed. Install bokeh to use the 'bokeh' backend.") from exc

        y_min = int(min(midi_values)) - 1
        y_max = int(max(midi_values)) + 1

        row_colors = _voice_color_mapping("bokeh")
        voices_col = df["Voice"].astype(str).tolist() if ("Voice" in df.columns) else None
        xml_id_col = df["xml_id"].astype(str).tolist() if ("xml_id" in df.columns) else None
        source_data = {
            "y": df["MIDI"],
            "left": df["Global Onset"],
            "right": df["Global Onset"] + df["Duration"],
            "pitch": df["Pitch"],
            "midi": df["MIDI"],
            "global_onset": df["Global Onset"],
            "local_onset": df["Local Onset"] if "Local Onset" in df.columns else df["Global Onset"],
            "duration": df["Duration"],
        }
        if "Measure" in df.columns:
            source_data["measure"] = df["Measure"]
        if row_colors is not None:
            source_data["color"] = row_colors
        if voices_col is not None:
            source_data["voice"] = voices_col
        if xml_id_col is not None:
            source_data["xml_id"] = xml_id_col
        if "Pitch Enharmonic" in df.columns:
            source_data["pitch_enharmonic"] = df["Pitch Enharmonic"].fillna("").tolist()

        # Normalize zoom dimension options
        def _norm_dim(val: Optional[str]) -> str:
            if val is None:
                return "both"
            v = str(val).strip().lower()
            if v in {"x", "width"}:
                return "width"
            if v in {"y", "height"}:
                return "height"
            return "both"

        drag_dim = _norm_dim(zoom_drag_dim)
        wheel_dim = _norm_dim(zoom_wheel_dim)

        def _build_plot() -> Any:
            src = ColumnDataSource(data=source_data)
            plot = figure(
                height=height_pixels,
                width=width_pixels,
                title="Piano Roll Visualization",
                x_axis_label="Global Onset (Quarter Lengths)",
                y_axis_label="Pitch",
                y_range=(y_min, y_max),
                tools="pan,reset,save",
            )
            try:
                plot.output_backend = "canvas"
            except Exception:
                pass
            plot.hbar(y="y", left="left", right="right", height=0.6, source=src, fill_color="#87CEEB")
            if row_colors is not None:
                # Re-render with color field and optional legend by voice
                try:
                    # Remove the previous glyph renderer if any
                    plot.renderers = [r for r in plot.renderers if getattr(r, "glyph", None) is None]
                except Exception:
                    pass
                kwargs: Dict[str, Any] = {"fill_color": "color"}
                if voices_col is not None:
                    kwargs["legend_field"] = "voice"
                plot.hbar(y="y", left="left", right="right", height=0.6, source=src, **kwargs)

            # Optional hover
            if bool(show_hover):
                # Build tooltips from requested fields
                supported = {
                    "pitch": ("Pitch", "@pitch"),
                    "midi": ("MIDI", "@midi"),
                    "voice": ("Voice", "@voice"),
                    "measure": ("Measure", "@measure"),
                    "xml_id": ("xml-id", "@xml_id"),
                    "global_onset": ("Global Onset", "@global_onset"),
                    "local_onset": ("Local Onset", "@local_onset"),
                    "duration": ("Duration", "@duration"),
                    "pitch_enharmonic": ("Pitch (Enharmonic)", "@pitch_enharmonic"),
                }
                default_order = ["pitch", "pitch_enharmonic", "voice", "measure", "xml_id", "global_onset", "local_onset", "duration", "midi"]
                fields = [f for f in (list(hover_fields) if hover_fields is not None else default_order) if f in supported]
                tooltips = [supported[f] for f in fields]
                try:
                    hover_tool = HoverTool(tooltips=tooltips)
                    plot.add_tools(hover_tool)
                except Exception:
                    pass

            try:
                box_tool = BoxZoomTool(dimensions=drag_dim)
                wheel_tool = WheelZoomTool(dimensions=wheel_dim)
                plot.add_tools(box_tool, wheel_tool)
                pan_tool = plot.select_one(PanTool)
                if pan_tool is None:
                    pan_tool = PanTool()
                    plot.add_tools(pan_tool)
                plot.toolbar.active_drag = pan_tool
                plot.toolbar.active_scroll = wheel_tool
            except Exception:
                pass

            if show_measure_lines and measure_offsets is not None:
                for m_offset in measure_offsets:
                    plot.add_layout(Span(location=m_offset, dimension="height", line_color=str(measure_line_color), line_dash="dashed", line_width=1))

            barline_plot_events = _iter_barline_events()
            if barline_plot_events:
                voice_order = [evt["Voice"] for evt in barline_plot_events if evt["Voice"]]
                voice_colors = _voice_color_dict("bokeh", voice_order)
                for evt in barline_plot_events:
                    color = voice_colors.get(evt["Voice"], str(measure_line_color))
                    plot.add_layout(
                        Span(
                            location=evt["Global Onset"],
                            dimension="height",
                            line_color=str(color),
                            line_dash=_barline_dash_style(evt.get("form"), "bokeh"),
                            line_width=1.2,
                        )
                    )

            if pitch_labels:
                plot.yaxis.ticker = midi_values
                plot.yaxis.major_label_overrides = {m: midi_to_pitch[m] for m in midi_values}

            return plot

        # Build the plot used for display/return
        p = _build_plot()

        # Optional explicit saves using separate plot instances to avoid doc ownership conflicts
        # Determine whether to save HTML (supports explicit toggle with back-compat)
        do_save_html = (bool(save_html) if save_html is not None else (save_html_path is not None))
        if do_save_html:
            try:
                from bokeh.embed import file_html  # type: ignore
                from bokeh.resources import INLINE  # type: ignore
                html = file_html(_build_plot(), INLINE, title="Piano Roll")
                import io, os
                from datetime import datetime
                html_target = str(save_html_path) if save_html_path else "piano_roll.html"
                abs_path = os.path.abspath(html_target)
                with io.open(abs_path, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"Data saved successfully to {abs_path} at {datetime.now().isoformat(timespec='seconds')}.")
                if open_html_after_save:
                    try:
                        import webbrowser
                        webbrowser.open_new_tab(abs_path)
                    except Exception:
                        pass
            except Exception as _exc:
                print(f"Warning: Failed to save HTML to '{save_html_path or 'piano_roll.html'}': {_exc}")

        if save_png_path:
            try:
                from bokeh.io import export_png  # type: ignore
                import os
                from datetime import datetime
                abs_png = os.path.abspath(str(save_png_path))
                export_png(_build_plot(), filename=abs_png)
                print(f"Data saved successfully to {abs_png} at {datetime.now().isoformat(timespec='seconds')}.")
            except Exception as _exc:
                print(
                    "Warning: Failed to export PNG. Install 'selenium' and a webdriver (e.g., chromedriver). "
                    f"Error: {_exc}"
                )

        if show:
            bokeh_show(p)
            return None
        return p

    raise ValueError("Unsupported backend. Choose from 'plt' or 'bokeh'.")



def create_piano_roll(df: pd.DataFrame, measure_offsets: Optional[List[float]] = None) -> Any:
    """
    Backward-compatible wrapper that draws using matplotlib backend.
    Shows and returns the Matplotlib figure.

    Note: In Jupyter, returning a figure as the last expression will display it.
    To avoid duplicate display, assign the return value to a variable.
    """
    fig = draw_piano_roll(df, measure_offsets=measure_offsets, backend="plt", show=False)
    # Show after obtaining the figure so we can still return it
    plt.show()
    return fig


def filter_and_adjust_durations(
    df: pd.DataFrame,
    *,
    filter_zero_duration: bool = True,
    adjust_fractional_duration: bool = True,
) -> pd.DataFrame:
    """
    Filter out zero-duration notes and adjust fractional durations.

    Parameters
    ----------
    df : pandas.DataFrame
        Original DataFrame.
    filter_zero_duration : bool, optional
        If True, removes rows with Duration <= 0. Default is True.
    adjust_fractional_duration : bool, optional
        If True, rounds 'Duration', 'Local Onset', and 'Global Onset' to 3 decimal places. Default is True.

    Returns
    -------
    pandas.DataFrame
        Processed DataFrame.
    """
    if filter_zero_duration and "Duration" in df.columns:
        df_processed = df.loc[df["Duration"] > 0]
    else:
        df_processed = df

    if adjust_fractional_duration:
        round_cols = [c for c in ("Duration", "Local Onset", "Global Onset") if c in df_processed.columns]
        if round_cols:
            # Ensure we don't mutate the caller's frame when no filter ran.
            if df_processed is df:
                df_processed = df_processed.copy()
            df_processed.loc[:, round_cols] = df_processed[round_cols].round(3)

    return df_processed


def get_measure_offsets(score) -> List[float]:
    """
    Compute global onset offsets for each measure in the first part of the score.

    Parameters
    ----------
    score : music21.stream.Score
        The music21 score object.

    Returns
    -------
    list[float]
        List of measure start offsets (global onsets). Empty if unavailable.
    """
    try:
        parts = getattr(score, "parts", None)
        if not parts:
            return []
        measures = parts[0].getElementsByClass("Measure")
        return [m.offset for m in measures]
    except Exception:
        return []


# -----------------------------
# Accidentals normalization API
# -----------------------------
_ACCIDENTAL_RANK_MAP = {
    "bbb": 0,
    "bb": 1,
    "b": 2,
    "": 3,  # natural
    "#": 4,
    "##": 5,
    "###": 6,
}


def _parse_note_name_components(name: str) -> tuple[str, str, str]:
    """
    Split a note name into (letter, accidental token(s), octave_part).
    Accepts a variety of accidental glyphs, music21 flats as '-' characters, and 'x' for double-sharp.
    """
    if not isinstance(name, str):
        return "", "", ""
    s = name.strip()
    if not s:
        return "", "", ""
    letter = s[0].upper() if s[0].upper() in {"A", "B", "C", "D", "E", "F", "G"} else ""
    if not letter:
        return "", "", ""
    idx = 1
    acc_raw = []
    while idx < len(s):
        ch = s[idx]
        if ch in {"#", "b", "-", "x", "♯", "♭", "𝄪", "𝄫", "♮"}:
            acc_raw.append(ch)
            idx += 1
        else:
            break
    octave_part = s[idx:] if idx < len(s) else ""
    return letter, "".join(acc_raw), octave_part


def _acc_raw_to_semitone_shift(acc_raw: str) -> int:
    """
    Convert a raw accidental string (which may contain '-', 'x', and glyphs) to a net semitone shift.
    Handles natural (♮) as a reset to zero.
    """
    if not acc_raw:
        return 0
    shift = 0
    natural_seen = False
    for ch in acc_raw:
        if ch in {"#", "♯"}:
            shift += 1
        elif ch in {"b", "-","♭"}:
            shift -= 1
        elif ch in {"x", "𝄪"}:
            shift += 2
        elif ch in {"𝄫"}:
            shift -= 2
        elif ch == "♮":
            # Natural cancels other accidentals in the same token
            shift = 0
            natural_seen = True
        else:
            continue
    # If natural appeared alone (or with others), we've already reset to 0
    return 0 if natural_seen else shift


def canonicalize_pitch_name(name: str, *, max_accidentals: int = 5) -> tuple[str, bool]:
    """
    Return a canonicalized pitch name where accidentals are expressed as repeated '#' or 'b',
    clamped to at most max_accidentals (default 5). Returns (canonical_name, exceeded_limit_flag).

    Examples:
      'Bb4' -> ('Bb4', False)
      'B-4' -> ('Bb4', False)
      'Fx5' -> ('F##5', False)
      'E#######6' -> ('E#####6', True)  # exceeds max 5, clamped and flagged
    """
    letter, acc_raw, octave_part = _parse_note_name_components(str(name))
    if not letter:
        # Return original string and no exceed flag; downstream callers can keep as-is
        return str(name), False
    shift = _acc_raw_to_semitone_shift(acc_raw)
    exceeded = abs(shift) > int(max_accidentals)
    if shift > 0:
        acc = "#" * min(int(max_accidentals), shift)
    elif shift < 0:
        acc = "b" * min(int(max_accidentals), -shift)
    else:
        acc = ""
    return f"{letter}{acc}{octave_part}", bool(exceeded)


def _acc_token_from_name(name: str) -> str:
    """
    Extract the accidental token (limited to triple range for ranking) from a pitch name.
    Returns one of {'bbb','bb','b','','#','##','###'} based on the net shift.
    """
    letter, acc_raw, _ = _parse_note_name_components(str(name))
    if not letter:
        return ""
    net = _acc_raw_to_semitone_shift(acc_raw)
    if net > 0:
        return "#" * min(3, net)
    if net < 0:
        return "b" * min(3, -net)
    return ""


def accidental_rank_from_name(name: str) -> int:
    """
    Compute the accidental rank using the fixed ordering:
      bbb < bb < b < natural < # < ## < ###
    Returns an integer in [0..6].
    """
    tok = _acc_token_from_name(name)
    return int(_ACCIDENTAL_RANK_MAP.get(tok, 3))


def _slugify_name(text: str) -> str:
    """
    Convert text to a filesystem and variable friendly slug: lowercase, alnum and underscores.
    """
    import re

    base = text.strip().lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    base = re.sub(r"_+", "_", base)
    return base.strip("_")


def _source_to_name(file_source: str, index: int) -> str:
    """
    Build a stable name for a parsed file: 2-digit index + slugified basename without extension.
    Example: 00_wtc1f01
    """
    base = os.path.basename(file_source)
    if "/" in file_source or "\\" in file_source:
        # URLs will still work with basename; ensure we trim fragments/query
        base = base.split("?")[0].split("#")[0]
    stem, _ = os.path.splitext(base)
    return f"{index:02d}_" + _slugify_name(stem)


def parse_files(
    file_sources: Iterable[str],
    *,
    filter_zero_duration: bool = True,
    adjust_fractional_duration: bool = True,
    backend: str = "plt",
    show_measure_lines: bool = True,
    measure_line_color: str = "red",
    show_hover: bool = True,
    hover_fields: Optional[Union[Sequence[str], None]] = None,
    display_preview: bool = True,
    preview_rows: int = 20,
    cleanup_remote: bool = True,
    return_plots: bool = False,
    plot_width: Optional[int] = None,
    plot_height: Optional[int] = None,
    zoom_drag_dim: Optional[str] = None,
    zoom_wheel_dim: Optional[str] = None,
    show_progress: bool = True,
    progress_desc: Optional[str] = None,
    colorize_voices: bool = False,
    palette: Optional[Union[str, Sequence[str]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Parse multiple symbolic music files, build DataFrames and optionally render piano rolls.

    Naming convention for multiple DataFrames: Each result is assigned a 'name'
    of the form 'NN_basename', where NN is a zero-padded index starting at 00
    and 'basename' is the slugified filename without extension. Use the returned
    'dfs_by_name' mapping for convenient access.

    Parameters
    ----------
    file_sources : Iterable[str]
        URLs or local file paths.
    filter_zero_duration : bool
        Remove rows with non-positive duration.
    adjust_fractional_duration : bool
        Round durations and onsets to 3 decimals.
    backend : {"plt", "bokeh", "none"}
        Plot backend for piano roll visualization. Use 'none' to disable plotting.
    show_measure_lines : bool
        If True, draw vertical red measure separation lines where measure offsets exist.
    display_preview : bool
        If True, display a small head() preview and summary for each file.
    preview_rows : int
        Number of rows to show in previews.
    cleanup_remote : bool
        If True, delete downloaded temp files after processing.
    return_plots : bool
        If True, include the created plot objects in results under 'plot'.
    plot_width : int, optional
        Width (pixels) for the Bokeh plot. If None, defaults to library default.
    plot_height : int, optional
        Height (pixels) for the Bokeh plot. If None, defaults to library default.
    zoom_drag_dim : {"width", "height", "both"}, optional
        Dimension for box zoom drag tool.
    zoom_wheel_dim : {"width", "height", "both"}, optional
        Dimension for wheel zoom tool.
    show_progress : bool
        If True and multiple files provided, show a tqdm progress bar. Default True.
    progress_desc : str, optional
        Custom description for the progress bar (default: "Parsing files").

    Returns
    -------
    (results, dfs_by_name, last_df)
        results: list of dicts with keys: name, source, df, measure_offsets[, plot]
        dfs_by_name: dict mapping name -> df
        last_df: the last successfully processed DataFrame (or None)
    """
    results: List[Dict[str, Any]] = []
    dfs_by_name: Dict[str, pd.DataFrame] = {}
    last_df: Optional[pd.DataFrame] = None

    # Lazy import to avoid hard dependency when used outside notebooks
    try:
        from IPython.display import display as ipy_display  # type: ignore
    except Exception:
        ipy_display = None  # Not in a notebook

    sources: List[str] = list(file_sources)
    use_progress = bool(show_progress) and (_tqdm is not None) and (len(sources) > 1)
    pbar = _tqdm(total=len(sources), desc=(progress_desc or "Parsing files"), unit="file") if use_progress else None
    log = (_tqdm.write if use_progress else print)

    try:
        for idx, file_source in enumerate(sources):
            try:
                name = _source_to_name(file_source, idx)
                short_name = os.path.basename(file_source).split("?")[0].split("#")[0]
                log(f"Processing: {short_name} -> {name}")
                if pbar is not None:
                    pbar.set_postfix_str(short_name)

                file_path = get_file_path(file_source)
                from music21 import converter as _converter
                score = _converter.parse(file_path)

                voice_data = extract_voice_data(score)
                df = pd.DataFrame(
                    voice_data,
                    columns=["Measure", "Local Onset", "Global Onset", "Duration", "Pitch", "Voice"],
                )
                df["MIDI"] = df["Pitch"].apply(lambda p: pitch_module.Pitch(p).midi)
                df = df[["Measure", "Local Onset", "Global Onset", "Duration", "Pitch", "MIDI", "Voice"]]
                df = df.sort_values("Global Onset").reset_index(drop=True)

                df_processed = filter_and_adjust_durations(
                    df,
                    filter_zero_duration=filter_zero_duration,
                    adjust_fractional_duration=adjust_fractional_duration,
                )
                df_processed = df_processed.sort_values("Global Onset").reset_index(drop=True)

                measure_offsets = get_measure_offsets(score)

                plot_obj = None
                if return_plots or backend != "none":
                    plot_obj = draw_piano_roll(
                        df_processed,
                        measure_offsets=measure_offsets,
                        backend=backend,
                        show_measure_lines=show_measure_lines,
                        measure_line_color=measure_line_color,
                        show_hover=show_hover,
                        hover_fields=hover_fields,
                        show=True,
                        plot_width=plot_width,
                        plot_height=plot_height,
                        zoom_drag_dim=zoom_drag_dim,
                        zoom_wheel_dim=zoom_wheel_dim,
                        colorize_voices=colorize_voices,
                        palette=palette,
                    )

                if display_preview and ipy_display is not None:
                    ipy_display(df_processed.head(preview_rows))
                    log(f"Rows: {len(df_processed)}, unique pitches: {df_processed['MIDI'].nunique()}")

                results.append({
                    "name": name,
                    "source": file_source,
                    "df": df_processed,
                    "measure_offsets": measure_offsets,
                    **({"plot": plot_obj} if return_plots else {}),
                })
                dfs_by_name[name] = df_processed
                last_df = df_processed

                if cleanup_remote and file_source.startswith(("http://", "https://")):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass

            except Exception as exc:
                log(f"An error occurred while processing {file_source}: {exc}")
            finally:
                if pbar is not None:
                    pbar.update(1)
    finally:
        if pbar is not None:
            pbar.close()

    return results, dfs_by_name, last_df
def _determine_resolution(
    df: pd.DataFrame,
    *,
    resolution_method: str = "auto",
    manual_resolution: Optional[float] = None,
) -> float:
    """
    Determine time resolution from the DataFrame and options.

    Parameters
    ----------
    df : pandas.DataFrame
        Must contain 'Duration'.
    resolution_method : {"auto", "manual", "standard"}
        How to pick resolution. 'auto' uses min positive duration; 'manual' uses provided value;
        'standard' uses a fixed musical grid (0.25 quarter notes).
    manual_resolution : float, optional
        Required when resolution_method == 'manual'.

    Returns
    -------
    float
        Positive resolution value.
    """
    method = (resolution_method or "auto").lower()
    if method == "auto":
        # Use smallest positive duration
        positive_durations = df.loc[df["Duration"] > 0, "Duration"]
        if positive_durations.empty:
            raise ValueError("No positive durations found to determine automatic resolution.")
        resolution = float(positive_durations.min())
    elif method == "manual":
        if manual_resolution is None:
            raise ValueError("manual_resolution must be provided when resolution_method is 'manual'.")
        resolution = float(manual_resolution)
    elif method == "standard":
        resolution = 0.25
    else:
        raise ValueError("Invalid resolution_method. Choose from 'auto', 'manual', 'standard'.")

    if resolution <= 0:
        raise ValueError("Resolution must be a positive number.")
    return resolution


def _serialize_binary_meta_value(value: Any) -> Any:
    """
    Convert values stored in binary metadata/provenance to plain Python scalars when possible.
    """
    if isinstance(value, np.generic):
        return value.item()
    if pd.isna(value):
        return None
    return value


def _format_binary_hover_value(value: Any) -> str:
    """
    Compact hover formatting without forced fixed precision.
    """
    plain = _serialize_binary_meta_value(value)
    if plain is None:
        return ""
    if isinstance(plain, bool):
        return str(plain)
    if isinstance(plain, int):
        return str(plain)
    if isinstance(plain, float):
        if np.isfinite(plain) and float(plain).is_integer():
            return str(int(plain))
        return f"{plain:.12g}"
    return str(plain)


def _normalize_binary_hover_field_name(name: Any) -> str:
    text = str(name or "").strip().lower()
    normalized = []
    last_was_sep = False
    for ch in text:
        if ch.isalnum():
            normalized.append(ch)
            last_was_sep = False
        elif not last_was_sep:
            normalized.append("_")
            last_was_sep = True
    return "".join(normalized).strip("_")


def _binary_cell_key(row: int, col: int) -> str:
    return f"{int(row)},{int(col)}"


def _binary_row_axis_value_from_meta(meta: Dict[str, Any], row: int) -> Any:
    y_mode = str(meta.get("y_mode", "minmax")).lower()
    row_order = str(meta.get("row_order", "low_to_high")).lower()
    y_min = int(meta.get("y_min", 0))
    y_max = int(meta.get("y_max", max(y_min, row)))
    row_idx = int(row)
    if y_mode == "chroma":
        labels = list(meta.get("pitch_class_labels", []))
        if labels and 0 <= row_idx < len(labels):
            return labels[row_idx]
        if row_order == "high_to_low":
            return int(11 - row_idx)
        return int(row_idx)
    if row_order == "high_to_low":
        return int(y_max - row_idx)
    return int(y_min + row_idx)


def _binary_row_axis_label_from_meta(meta: Dict[str, Any], row: int) -> str:
    axis_value = _binary_row_axis_value_from_meta(meta, row)
    y_mode = str(meta.get("y_mode", "minmax")).lower()
    if y_mode == "chroma":
        return _format_binary_hover_value(axis_value)
    try:
        return str(pitch_module.Pitch(int(axis_value)).nameWithOctave)
    except Exception:
        return _format_binary_hover_value(axis_value)


def _binary_meta_source_rows(meta: Dict[str, Any], source_positions: Sequence[int]) -> List[Dict[str, Any]]:
    provenance = meta.get("provenance")
    if not isinstance(provenance, dict):
        return []
    source_records = list(provenance.get("source_records", []))
    source_index_values = list(provenance.get("source_index_values", []))
    source_rows: List[Dict[str, Any]] = []
    for pos in source_positions:
        source_pos = int(pos)
        if not (0 <= source_pos < len(source_records)):
            continue
        record = dict(source_records[source_pos])
        record["source_row_position"] = source_pos
        record["source_df_index"] = (
            source_index_values[source_pos]
            if source_pos < len(source_index_values)
            else source_pos
        )
        source_rows.append(record)
    return source_rows


def prepare_binary_hover_fields(
    hover_fields: Optional[Sequence[str]] = None,
    *,
    provenance_columns: Optional[Sequence[str]] = None,
    default_fields: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Normalize requested binary hover fields and append safe defaults.

    Parameters
    ----------
    hover_fields : sequence of str, optional
        Requested hover fields, using either canonical binary names or source DataFrame
        column names.
    provenance_columns : sequence of str, optional
        Source DataFrame columns available through provenance metadata. Their normalized
        snake_case aliases are accepted as hover fields.
    default_fields : sequence of str, optional
        Extra fields appended after ``hover_fields`` when supported. Defaults to
        ``["row", "col"]``.
    """
    hover_field_aliases = {
        "pitch_row": "row",
        "time_col": "col",
    }
    supported = {
        "row",
        "col",
        "time",
        "midi",
        "selected_area",
        "source_count",
        "source_rows",
        "source_df",
    }
    for source_col in provenance_columns or []:
        alias = _normalize_binary_hover_field_name(source_col)
        if alias:
            supported.add(alias)

    merged_fields = list(hover_fields or [])
    merged_fields.extend(list(default_fields or ["row", "col"]))

    normalized_hover_fields: List[str] = []
    for field_name in merged_fields:
        normalized = hover_field_aliases.get(
            _normalize_binary_hover_field_name(field_name),
            _normalize_binary_hover_field_name(field_name),
        )
        if normalized in supported and normalized not in normalized_hover_fields:
            normalized_hover_fields.append(normalized)

    if normalized_hover_fields:
        return normalized_hover_fields

    fallback = ["row", "col"]
    if provenance_columns:
        fallback.extend(["source_count", "source_rows"])
    return [field_name for field_name in fallback if field_name in supported]


def describe_binary_matrix(matrix: np.ndarray, meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return compact binary matrix statistics suitable for notebook summaries.
    """
    mat = np.asarray(matrix)
    active_cell_count = int(np.count_nonzero(mat))
    total_cells = int(mat.size)
    provenance = meta.get("provenance") if isinstance(meta.get("provenance"), dict) else {}
    return {
        "shape": tuple(int(dim) for dim in mat.shape),
        "dtype": str(mat.dtype),
        "cell_count": total_cells,
        "active_cell_count": active_cell_count,
        "active_cell_ratio": (
            float(active_cell_count / total_cells)
            if total_cells > 0
            else 0.0
        ),
        "source_row_count": provenance.get("source_row_count"),
    }


def print_binary_matrix_summary(matrix: np.ndarray, meta: Dict[str, Any]) -> None:
    """
    Print the binary metadata block and a compact activity summary.
    """
    stats = describe_binary_matrix(matrix, meta)
    print("--- Metadata (create_binary_matrix) ---")
    for key, value in sorted(meta.items()):
        if key == "provenance" and isinstance(value, dict):
            print("  provenance:")
            print(f"    source_row_count: {value.get('source_row_count')}")
            print(f"    active_cell_count: {value.get('active_cell_count')}")
            print(f"    source_columns: {value.get('source_columns')}")
            continue
        print(f"  {key}: {value}")
    print("\n--- Raw binary stats ---")
    print(f"  shape (rows=pitch bins, cols=time steps): {stats['shape']}")
    print(f"  dtype: {stats['dtype']}")
    print(
        "  active cells (1s): "
        f"{stats['active_cell_count']} / {stats['cell_count']} "
        f"({100 * stats['active_cell_ratio']:.2f}%)"
    )


@dataclass
class BinaryMatrixSliceBundle:
    """
    Notebook-friendly view over a selected raw binary matrix window.
    """
    matrix: np.ndarray = field(repr=False)
    meta: Dict[str, Any] = field(repr=False)
    row_start: int
    row_end: int
    col_start: int
    col_end: int
    matrix_slice: np.ndarray = field(repr=False)
    row_coord_df: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    col_coord_df: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    active_spans_df: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    selection_name: str = ""
    highlight_windows: List[Dict[str, Any]] = field(default_factory=list)
    measure_offsets: Optional[List[float]] = None
    hover_fields: List[str] = field(default_factory=list)

    def print_summary(self) -> None:
        """
        Print the compact slice summary used in notebook showcase cells.
        """
        stats = describe_binary_matrix(self.matrix, self.meta)
        print("Shape (rows=pitch bins, cols=time steps):", stats["shape"])
        print("dtype:", stats["dtype"])
        print(
            "Sparsity: "
            f"{stats['active_cell_count']}/{stats['cell_count']} = "
            f"{100 * stats['active_cell_ratio']:.2f}% active"
        )
        print(
            f"\nSlice [rows {self.row_start}:{self.row_end}, cols {self.col_start}:{self.col_end}] as 0/1:"
        )
        print(self.matrix_slice)

    def display_tables(
        self,
        *,
        row_preview_rows: int = 10,
        col_preview_rows: int = 10,
        active_preview_rows: int = 20,
        display_fn: Optional[Any] = None,
    ) -> None:
        """
        Display the helper tables for this slice in notebooks or plain Python.
        """
        resolved_display = display_fn
        if resolved_display is None:
            try:
                from IPython.display import display as ipy_display  # type: ignore
            except Exception:
                ipy_display = None
            resolved_display = ipy_display

        def _show(df: pd.DataFrame, preview_rows: int) -> None:
            preview = df.head(preview_rows)
            if resolved_display is not None:
                resolved_display(preview)
            else:
                print(preview)

        print("\nRow coordinate mapping for this slice (top -> bottom raw matrix rows):")
        _show(self.row_coord_df, row_preview_rows)
        print("\nColumn coordinate mapping for this slice (left -> right raw matrix cols):")
        _show(self.col_coord_df, col_preview_rows)
        print("\nDecoded active spans in that slice (first 20):")
        _show(self.active_spans_df, active_preview_rows)

    def plot(self, **kwargs: Any) -> Any:
        """
        Plot the full matrix while highlighting this slice selection.
        """
        plot_kwargs = dict(kwargs)
        plot_kwargs.setdefault("measure_offsets", self.measure_offsets)
        plot_kwargs.setdefault(
            "hover_fields",
            list(self.hover_fields) if self.hover_fields else None,
        )
        plot_kwargs.setdefault("highlight_windows", list(self.highlight_windows))
        return plot_binary_matrix(self.matrix, self.meta, **plot_kwargs)


def create_binary_matrix_slice_bundle(
    matrix: np.ndarray,
    meta: Dict[str, Any],
    *,
    row_start: int = 0,
    col_start: int = 0,
    n_rows: int = 12,
    n_cols: int = 24,
    selection_name: Optional[str] = None,
    selection_color: str = "#ff4fc3",
    selection_alpha: float = 0.22,
    selection_line_color: str = "#b0007a",
    selection_line_width: float = 2.0,
    measure_offsets: Optional[List[float]] = None,
    hover_fields: Optional[Sequence[str]] = None,
) -> BinaryMatrixSliceBundle:
    """
    Build a notebook-friendly summary of one raw binary matrix slice.
    """
    total_rows, total_cols = np.asarray(matrix).shape
    row_start_idx = max(0, int(row_start))
    col_start_idx = max(0, int(col_start))
    row_end_idx = max(row_start_idx, min(row_start_idx + int(n_rows), total_rows))
    col_end_idx = max(col_start_idx, min(col_start_idx + int(n_cols), total_cols))

    matrix_slice = matrix[row_start_idx:row_end_idx, col_start_idx:col_end_idx]
    row_coord_df = pd.DataFrame(
        [get_binary_row_info(meta, row_idx) for row_idx in range(row_start_idx, row_end_idx)]
    )
    col_coord_df = pd.DataFrame(
        [get_binary_col_info(meta, col_idx) for col_idx in range(col_start_idx, col_end_idx)]
    )
    active_spans_df = binary_slice_to_df(
        matrix_slice,
        meta,
        row_start=row_start_idx,
        col_start=col_start_idx,
    )

    resolved_selection_name = str(selection_name or "selection")
    highlight_windows = [
        {
            "name": resolved_selection_name,
            "row_start": row_start_idx,
            "row_stop": row_end_idx,
            "col_start": col_start_idx,
            "col_stop": col_end_idx,
            "color": str(selection_color),
            "alpha": float(selection_alpha),
            "line_color": str(selection_line_color),
            "line_width": float(selection_line_width),
        }
    ]

    return BinaryMatrixSliceBundle(
        matrix=matrix,
        meta=meta,
        row_start=row_start_idx,
        row_end=row_end_idx,
        col_start=col_start_idx,
        col_end=col_end_idx,
        matrix_slice=matrix_slice,
        row_coord_df=row_coord_df,
        col_coord_df=col_coord_df,
        active_spans_df=active_spans_df,
        selection_name=resolved_selection_name,
        highlight_windows=highlight_windows,
        measure_offsets=measure_offsets,
        hover_fields=list(hover_fields or []),
    )


@dataclass
class BinaryMatrixBundle:
    """
    Notebook-friendly container for a binary matrix plus the helper data around it.
    """
    source_name: str
    source_df: pd.DataFrame = field(repr=False)
    matrix: np.ndarray = field(repr=False)
    meta: Dict[str, Any] = field(repr=False)
    measure_offsets: Optional[List[float]] = None
    hover_fields: List[str] = field(default_factory=list)
    decoded_df: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    reconstructed_df: Optional[pd.DataFrame] = field(default=None, repr=False)

    def describe(self) -> Dict[str, Any]:
        return describe_binary_matrix(self.matrix, self.meta)

    def print_summary(self) -> None:
        print_binary_matrix_summary(self.matrix, self.meta)

    def slice(
        self,
        *,
        row_start: int = 0,
        col_start: int = 0,
        n_rows: int = 12,
        n_cols: int = 24,
        selection_name: Optional[str] = None,
        selection_color: str = "#ff4fc3",
        selection_alpha: float = 0.22,
        selection_line_color: str = "#b0007a",
        selection_line_width: float = 2.0,
    ) -> BinaryMatrixSliceBundle:
        """
        Build a highlighted slice/showcase view from this binary matrix bundle.
        """
        return create_binary_matrix_slice_bundle(
            self.matrix,
            self.meta,
            row_start=row_start,
            col_start=col_start,
            n_rows=n_rows,
            n_cols=n_cols,
            selection_name=selection_name,
            selection_color=selection_color,
            selection_alpha=selection_alpha,
            selection_line_color=selection_line_color,
            selection_line_width=selection_line_width,
            measure_offsets=self.measure_offsets,
            hover_fields=self.hover_fields,
        )

    def plot(self, **kwargs: Any) -> Any:
        """
        Plot the bundle's matrix while reusing stored measure offsets and hover fields.
        """
        plot_kwargs = dict(kwargs)
        plot_kwargs.setdefault("measure_offsets", self.measure_offsets)
        plot_kwargs.setdefault(
            "hover_fields",
            list(self.hover_fields) if self.hover_fields else None,
        )
        return plot_binary_matrix(self.matrix, self.meta, **plot_kwargs)


def create_binary_matrix_bundle(
    source: Union[str, pd.DataFrame],
    *,
    dfs_by_name: Optional[Dict[str, pd.DataFrame]] = None,
    results: Optional[Sequence[Dict[str, Any]]] = None,
    source_name: Optional[str] = None,
    resolution_method: str = "auto",
    manual_resolution: Optional[float] = None,
    y_mode: str = "minmax",
    midi_low: Optional[int] = None,
    midi_high: Optional[int] = None,
    row_order: str = "low_to_high",
    include_provenance: bool = True,
    provenance_columns: Optional[Sequence[str]] = None,
    hover_fields: Optional[Sequence[str]] = None,
    default_hover_fields: Optional[Sequence[str]] = None,
) -> BinaryMatrixBundle:
    """
    Build a binary matrix together with decoded helper DataFrames and plotting context.

    Parameters
    ----------
    source : str or pandas.DataFrame
        Either a source name present in ``dfs_by_name`` or a processed note DataFrame.
    dfs_by_name : dict, optional
        Mapping returned by ``parse_files`` when ``source`` is a source name.
    results : sequence of dict, optional
        Parsed results returned by ``parse_files``. Used to recover measure offsets.
    source_name : str, optional
        Explicit display name when ``source`` is a DataFrame.
    default_hover_fields : sequence of str, optional
        Safe fields appended after ``hover_fields``. Defaults to
        ``["row", "col", "selected_area", "source_rows"]``.
    """
    if isinstance(source, pd.DataFrame):
        source_df = source
        resolved_source_name = str(source_name or getattr(source, "name", None) or "binary_source")
    else:
        resolved_source_name = str(source)
        if dfs_by_name is None:
            raise ValueError("dfs_by_name is required when source is given as a source name.")
        if resolved_source_name not in dfs_by_name:
            available_sources = sorted(dfs_by_name.keys())
            raise KeyError(
                f"Unknown source name {resolved_source_name!r}. "
                f"Available sources: {available_sources}"
            )
        source_df = dfs_by_name[resolved_source_name]

    measure_offsets: Optional[List[float]] = None
    if results is not None:
        for item in results:
            if item.get("name") != resolved_source_name:
                continue
            offsets = item.get("measure_offsets")
            if offsets is not None:
                measure_offsets = [float(offset) for offset in offsets]
            break

    matrix, meta = create_binary_matrix(
        source_df,
        resolution_method=resolution_method,
        manual_resolution=manual_resolution,
        y_mode=y_mode,
        midi_low=midi_low,
        midi_high=midi_high,
        row_order=row_order,
        include_provenance=include_provenance,
        provenance_columns=provenance_columns,
    )

    provenance = meta.get("provenance") if isinstance(meta.get("provenance"), dict) else {}
    normalized_hover_fields = prepare_binary_hover_fields(
        hover_fields,
        provenance_columns=provenance.get("source_columns"),
        default_fields=default_hover_fields or ["row", "col", "selected_area", "source_rows"],
    )

    decoded_df = binary_slice_to_df(matrix, meta)
    reconstructed_df = None
    if str(meta.get("y_mode", "minmax")).lower() != "chroma":
        reconstructed_df = binary_matrix_to_df_from_meta(matrix, meta)

    return BinaryMatrixBundle(
        source_name=resolved_source_name,
        source_df=source_df,
        matrix=matrix,
        meta=meta,
        measure_offsets=measure_offsets,
        hover_fields=normalized_hover_fields,
        decoded_df=decoded_df,
        reconstructed_df=reconstructed_df,
    )


def create_binary_matrix(
    df: pd.DataFrame,
    *,
    resolution_method: str = "auto",
    manual_resolution: Optional[float] = None,
    y_mode: str = "minmax",  # "full" | "minmax" | "chroma"
    midi_low: Optional[int] = None,
    midi_high: Optional[int] = None,
    row_order: str = "low_to_high",
    include_provenance: bool = False,
    provenance_columns: Optional[Sequence[str]] = None,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Convert a processed DataFrame to a binary piano-roll-like matrix.

    Parameters
    ----------
    df : pandas.DataFrame
        Must contain 'MIDI', 'Global Onset', and 'Duration'.
    resolution_method : {"auto", "manual", "standard"}
        Grid size to discretize time. See _determine_resolution.
    manual_resolution : float, optional
        Used when resolution_method == 'manual'.
    y_mode : {"full", "minmax", "chroma"}
        Controls the pitch axis:
        - "full": rows for all MIDI 0..127
        - "minmax": rows from min(df.MIDI)..max(df.MIDI) (or overridden by midi_low/high)
        - "chroma": 12 pitch classes (C..B), folding octaves
    midi_low : int, optional
        Override lower MIDI bound when y_mode == 'minmax'. Ignored otherwise.
    midi_high : int, optional
        Override upper MIDI bound when y_mode == 'minmax'. Ignored otherwise.
    row_order : {"low_to_high", "high_to_low"}
        Controls how MIDI rows are ordered in the matrix. "low_to_high" stores the
        lowest MIDI pitch at row 0 (matrix origin at the bottom). "high_to_low" stores
        the highest MIDI pitch at row 0 (matrix origin at the top).
    include_provenance : bool, optional
        If True, include a cell-to-source-row provenance map and serialized source rows
        in the returned metadata. This enables linking binary cells back to the original
        DataFrame and richer hover tooltips.
    provenance_columns : sequence of str, optional
        Subset of DataFrame columns to store in provenance. Defaults to all columns when
        include_provenance is True.

    Returns
    -------
    (matrix, meta)
        matrix : np.ndarray of shape (num_pitches, num_cols), dtype=int
        meta : dict with keys: resolution, num_cols, time_end, y_mode, y_min, y_max,
               midi_low, midi_high, row_order, origin, pitch_class_labels (when chroma),
               and optional provenance metadata when include_provenance is True
    """
    required_columns = {"MIDI", "Global Onset", "Duration"}
    missing = required_columns.difference(df.columns)
    if missing:
        raise ValueError(f"DataFrame is missing required columns: {sorted(missing)}")

    resolution = _determine_resolution(
        df,
        resolution_method=resolution_method,
        manual_resolution=manual_resolution,
    )

    # Determine time axis
    total_duration = float(df["Global Onset"].max() + df["Duration"].max())
    num_cols = int(np.ceil(total_duration / resolution))
    time_end = num_cols * resolution

    # Compute smallest positive duration in data for reporting
    positive_durations = df.loc[df["Duration"] > 0, "Duration"]
    min_positive_duration = float(positive_durations.min()) if not positive_durations.empty else 0.0

    # Determine pitch axis
    mode = (y_mode or "minmax").lower()
    if mode not in {"full", "minmax", "chroma"}:
        raise ValueError("y_mode must be one of {'full', 'minmax', 'chroma'}")

    row_order_normalized = (row_order or "low_to_high").lower()
    if row_order_normalized not in {"low_to_high", "high_to_low"}:
        raise ValueError("row_order must be 'low_to_high' or 'high_to_low'.")
    origin = "lower" if row_order_normalized == "low_to_high" else "upper"

    if mode == "full":
        y_min = 0
        y_max = 127
        num_rows = y_max - y_min + 1
        if row_order_normalized == "low_to_high":
            row_index_for_midi = lambda m: int(m) - y_min  # noqa: E731
        else:
            row_index_for_midi = lambda m: y_max - int(m)  # noqa: E731
        pitch_class_labels: Optional[List[str]] = None
        midi_low_final = y_min
        midi_high_final = y_max
    elif mode == "minmax":
        data_low = int(df["MIDI"].min())
        data_high = int(df["MIDI"].max())
        y_min = int(midi_low) if midi_low is not None else data_low
        y_max = int(midi_high) if midi_high is not None else data_high
        if y_min > y_max:
            y_min, y_max = y_max, y_min
        num_rows = y_max - y_min + 1
        if row_order_normalized == "low_to_high":
            row_index_for_midi = lambda m: int(m) - y_min  # noqa: E731
        else:
            row_index_for_midi = lambda m: y_max - int(m)  # noqa: E731
        pitch_class_labels = None
        midi_low_final = y_min
        midi_high_final = y_max
    else:  # chroma
        y_min = 0
        y_max = 11
        num_rows = 12
        if row_order_normalized == "low_to_high":
            row_index_for_midi = lambda m: int(m) % 12  # noqa: E731
            pitch_class_labels = [
                "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
            ]
        else:
            row_index_for_midi = lambda m: 11 - (int(m) % 12)  # noqa: E731
            pitch_class_labels = [
                "B", "A#", "A", "G#", "G", "F#", "F", "E", "D#", "D", "C#", "C",
            ]
        midi_low_final = None
        midi_high_final = None

    matrix = np.zeros((num_rows, num_cols), dtype=int)

    provenance: Optional[Dict[str, Any]] = None
    if include_provenance:
        selected_columns = (
            [str(col) for col in provenance_columns]
            if provenance_columns is not None
            else [str(col) for col in df.columns]
        )
        missing_provenance = [col for col in selected_columns if col not in df.columns]
        if missing_provenance:
            raise ValueError(
                f"provenance_columns are missing from DataFrame: {sorted(missing_provenance)}"
            )
        selected_df = df[selected_columns]
        provenance = {
            "source_columns": selected_columns,
            "source_index_name": (
                str(df.index.name) if df.index.name is not None else None
            ),
            "source_index_values": [
                _serialize_binary_meta_value(idx) for idx in selected_df.index.tolist()
            ],
            "source_records": [
                {
                    str(col): _serialize_binary_meta_value(val)
                    for col, val in row.items()
                }
                for row in selected_df.to_dict(orient="records")
            ],
            "active_cell_map": {},
        }

    # Fill matrix
    for source_pos, (_, row) in enumerate(df.iterrows()):
        midi_value = int(row["MIDI"])
        if mode != "chroma" and not (y_min <= midi_value <= y_max):
            # Ignore notes outside requested range
            continue
        r = row_index_for_midi(midi_value)
        start_col = int(np.floor(float(row["Global Onset"]) / resolution))
        end_col = int(np.ceil(float(row["Global Onset"] + row["Duration"]) / resolution))
        if end_col <= start_col:
            end_col = start_col + 1
        end_col = min(end_col, num_cols)
        if 0 <= r < num_rows:
            matrix[r, start_col:end_col] = 1
            if provenance is not None:
                active_cell_map = provenance["active_cell_map"]
                for c in range(start_col, end_col):
                    key = _binary_cell_key(r, c)
                    active_cell_map.setdefault(key, []).append(int(source_pos))

    row_axis_values = [_binary_row_axis_value_from_meta(
        {
            "y_mode": mode,
            "row_order": row_order_normalized,
            "y_min": y_min,
            "y_max": y_max,
            **({"pitch_class_labels": pitch_class_labels} if pitch_class_labels is not None else {}),
        },
        row_idx,
    ) for row_idx in range(num_rows)]
    row_axis_labels = [_binary_row_axis_label_from_meta(
        {
            "y_mode": mode,
            "row_order": row_order_normalized,
            "y_min": y_min,
            "y_max": y_max,
            **({"pitch_class_labels": pitch_class_labels} if pitch_class_labels is not None else {}),
        },
        row_idx,
    ) for row_idx in range(num_rows)]

    meta: Dict[str, Any] = {
        "resolution": resolution,
        "num_rows": num_rows,
        "num_cols": num_cols,
        "time_end": time_end,
        "total_duration": total_duration,
        "min_positive_duration": min_positive_duration,
        "y_mode": mode,
        "y_min": y_min,
        "y_max": y_max,
        "midi_low": midi_low_final,
        "midi_high": midi_high_final,
        "row_order": row_order_normalized,
        "origin": origin,
        "binary_coordinate_system": "raw_matrix_indices",
        "binary_row_index_direction": "top_to_bottom",
        "binary_col_index_direction": "left_to_right",
        "row_axis_values": row_axis_values,
        "row_axis_labels": row_axis_labels,
        **({"pitch_class_labels": pitch_class_labels} if pitch_class_labels is not None else {}),
        **(
            {
                "provenance": {
                    **provenance,
                    "active_cell_count": len(provenance["active_cell_map"]),
                    "source_row_count": len(provenance["source_records"]),
                }
            }
            if provenance is not None
            else {}
        ),
    }

    return matrix, meta


def plot_binary_matrix(
    matrix: np.ndarray,
    meta: Dict[str, Any],
    *,
    backend: str = "plt",
    measure_offsets: Optional[List[float]] = None,
    show_measure_lines: bool = True,
    measure_line_color: str = "red",
    show_hover: bool = True,
    hover_fields: Optional[Sequence[str]] = None,
    cmap: str = "gray_r",
    show: bool = True,
    plot_width: Optional[int] = None,
    plot_height: Optional[int] = None,
    dpi: float = 100.0,
    zoom_drag_dim: Optional[str] = None,
    zoom_wheel_dim: Optional[str] = None,
    pitch_labels: bool = True,
    hover_cell_scope: str = "active",
    highlight_windows: Optional[Sequence[Dict[str, Any]]] = None,
    save_html: Optional[bool] = None,
    save_html_path: Optional[str] = None,
    save_png_path: Optional[str] = None,
    open_html_after_save: bool = False,
) -> Any:
    """
    Visualize a binary matrix using Matplotlib or Bokeh, similar to draw_piano_roll.

    Parameters
    ----------
    matrix : np.ndarray
        Binary matrix (rows=pitches, cols=time steps).
    meta : dict
        Metadata returned by create_binary_matrix.
    backend : {"plt", "bokeh", "none"}
        Plotting backend to use. Use "none" to skip plotting.
    measure_offsets : list[float], optional
        Global onset times where measures start. Drawn as vertical lines when provided.
    show_measure_lines : bool
        Whether to draw measure lines when offsets are provided.
    measure_line_color : str
        Color for the vertical measure lines when show_measure_lines is True.
    cmap : str
        Matplotlib colormap for imshow.
    show : bool
        Whether to immediately show the plot.
    plot_width : int, optional
        Width in pixels for both backends. If None, defaults to 900.
    plot_height : int, optional
        Height in pixels for both backends. If None, defaults to 600.
    dpi : float, optional
        DPI for matplotlib backend (used to convert pixels to inches). Default is 100.
    zoom_drag_dim : {"width", "height", "both"}, optional
        Dimension for box zoom drag tool (Bokeh only). None defaults to "both".
    zoom_wheel_dim : {"width", "height", "both"}, optional
        Dimension for wheel zoom tool (Bokeh only). None defaults to "both".
    show_hover : bool, optional
        When backend is 'bokeh', add a HoverTool showing binary-axis and optional
        provenance information. Default True.
    hover_fields : sequence of str, optional
        Fields to show in hover (Bokeh only). Core fields: "row", "col",
        "time", "midi", "source_count", "source_rows", "source_df". When
        provenance metadata is present, lower_snake_case versions of source DataFrame
        column names are also supported (e.g. "measure", "voice", "xml_id").
        Legacy aliases "pitch_row" -> "row" and "time_col" -> "col" are accepted.
        If None, defaults to raw matrix coordinates plus provenance counts when available.
    pitch_labels : bool, optional
        For Bokeh: whether to use pitch names or indices on the y-axis when supported.
    hover_cell_scope : {"active", "active_or_highlighted", "all"}, optional
        Controls which binary cells get a hover target in the Bokeh backend.
        - "active": only cells with value 1 (fastest)
        - "active_or_highlighted": active cells plus cells covered by highlight_windows
        - "all": every raw matrix cell, including empty cells (slowest)
    highlight_windows : sequence of dict, optional
        Optional highlight overlays defined in raw binary matrix coordinates. Each item may
        contain: row_start, row_stop, col_start, col_stop (half-open indices), optional
        name, and optional styling keys color, alpha, line_color, line_width.
    save_html : bool, optional
        If None (default), behaves like legacy mode: saves HTML when save_html_path is provided.
        If True, saves HTML to save_html_path if provided, otherwise to "binary_matrix.html".
        If False, disables HTML saving regardless of save_html_path.
    save_html_path : str, optional
        When backend == 'bokeh', if provided (and save_html is True or None), saves the plot as standalone HTML.
    save_png_path : str, optional
        When backend == 'bokeh', if provided, attempts to export a PNG. Requires selenium and webdriver.
    open_html_after_save : bool, optional
        If True and HTML is saved, attempts to open it in a browser.

    Returns
    -------
    Any
        A backend-specific figure object when show=False; None when show=True or backend="none".
    """
    backend = (backend or "plt").lower()

    if backend == "none":
        return None

    # Set default dimensions if not provided
    width_pixels = plot_width or 900
    height_pixels = plot_height or 600

    time_end = float(meta["time_end"]) if "time_end" in meta else matrix.shape[1]
    y_min = int(meta.get("y_min", 0))
    y_max = int(meta.get("y_max", matrix.shape[0] - 1))
    y_mode = str(meta.get("y_mode", "minmax"))
    origin = str(meta.get("origin", "lower")).lower()
    if origin not in {"lower", "upper"}:
        origin = "lower"
    hover_scope = str(hover_cell_scope or "active").strip().lower()
    if hover_scope in {"active_or_selected", "active_or_highlighted_area"}:
        hover_scope = "active_or_highlighted"
    if hover_scope not in {"active", "active_or_highlighted", "all"}:
        hover_scope = "active"

    matrix_for_display = matrix if origin == "lower" else np.flipud(matrix)
    labels_display = meta.get("pitch_class_labels", [])
    if labels_display:
        labels_display = list(labels_display)
        if origin == "upper":
            labels_display.reverse()

    def _normalized_highlight_windows() -> List[Dict[str, Any]]:
        if not highlight_windows:
            return []
        normalized: List[Dict[str, Any]] = []
        total_rows, total_cols = matrix.shape
        for item in highlight_windows:
            if item is None:
                continue
            row_start = int(item.get("row_start", 0))
            row_stop = int(item.get("row_stop", row_start + 1))
            col_start = int(item.get("col_start", 0))
            col_stop = int(item.get("col_stop", col_start + 1))
            row_start = max(0, min(row_start, total_rows))
            row_stop = max(0, min(row_stop, total_rows))
            col_start = max(0, min(col_start, total_cols))
            col_stop = max(0, min(col_stop, total_cols))
            if row_stop <= row_start or col_stop <= col_start:
                continue
            if origin == "upper":
                display_row_start = total_rows - row_stop
            else:
                display_row_start = row_start
            normalized.append(
                {
                    "row_start": row_start,
                    "row_stop": row_stop,
                    "col_start": col_start,
                    "col_stop": col_stop,
                    "x_start": float(col_start * float(meta.get("resolution", 1.0))),
                    "x_end": float(col_stop * float(meta.get("resolution", 1.0))),
                    "y_start": float(y_min + display_row_start),
                    "y_end": float(y_min + display_row_start + (row_stop - row_start)),
                    "name": str(item.get("name", "")).strip(),
                    "color": str(item.get("color", "#ff00ff")),
                    "alpha": float(item.get("alpha", 0.2)),
                    "line_color": str(item.get("line_color", item.get("color", "#ff00ff"))),
                    "line_width": float(item.get("line_width", 1.5)),
                }
            )
        return normalized

    highlight_specs = _normalized_highlight_windows()

    if backend == "plt":
        # Convert pixels to inches for matplotlib
        width_inches = width_pixels / dpi
        height_inches = height_pixels / dpi
        fig, ax = plt.subplots(figsize=(width_inches, height_inches))
        extent = [0, time_end, y_min, y_max]
        ax.imshow(
            matrix_for_display,
            aspect="auto",
            origin="lower",
            cmap=cmap,
            interpolation="nearest",
            extent=extent,
        )
        ax.set_xlabel("Time (in duration units)")
        ax.set_ylabel("Pitch Class" if y_mode == "chroma" else "MIDI Number")
        ax.set_title("Binary Matrix Representation")

        if y_mode == "chroma":
            ax.set_yticks(list(range(0, matrix_for_display.shape[0])))
            if labels_display:
                ax.set_yticklabels(labels_display)

        if show_measure_lines and measure_offsets is not None:
            for m_offset in measure_offsets:
                ax.axvline(x=m_offset, color=str(measure_line_color), linestyle="--", linewidth=0.8)

        if highlight_specs:
            from matplotlib.patches import Rectangle
            for spec in highlight_specs:
                ax.add_patch(
                    Rectangle(
                        (spec["x_start"], spec["y_start"]),
                        spec["x_end"] - spec["x_start"],
                        spec["y_end"] - spec["y_start"],
                        facecolor=spec["color"],
                        edgecolor=spec["line_color"],
                        linewidth=spec["line_width"],
                        alpha=spec["alpha"],
                    )
                )

        fig.tight_layout()
        if show:
            plt.show()
            plt.close(fig)
            return None
        return fig

    if backend == "bokeh":
        try:
            from bokeh.plotting import figure, show as bokeh_show
            from bokeh.models import (
                Span,
                LinearColorMapper,
                BasicTicker,
                BoxZoomTool,
                WheelZoomTool,
                PanTool,
                ColumnDataSource,
                HoverTool,
            )
            # Initialize inline output in notebooks once
            global BOKEH_NOTEBOOK_INITIALIZED
            if not BOKEH_NOTEBOOK_INITIALIZED:
                try:
                    from IPython import get_ipython  # type: ignore
                    ip = get_ipython()
                except Exception:
                    ip = None
                if ip is not None:
                    try:
                        from bokeh.io import output_notebook
                        # Force inline resources to avoid CDN issues in restricted/offline environments
                        try:
                            from bokeh.resources import INLINE
                        except Exception:
                            INLINE = "inline"
                        output_notebook(hide_banner=True, resources=INLINE)
                        BOKEH_NOTEBOOK_INITIALIZED = True
                    except Exception:
                        pass
        except ImportError as exc:
            raise ImportError("Bokeh is not installed. Install bokeh to use the 'bokeh' backend.") from exc

        matrix_for_bokeh = np.ascontiguousarray(matrix_for_display)
        resolution = float(meta.get("resolution", 1.0))
        provenance = meta.get("provenance") if isinstance(meta.get("provenance"), dict) else None
        provenance_columns = list(provenance.get("source_columns", [])) if provenance else []
        hover_field_aliases = {
            "pitch_row": "row",
            "time_col": "col",
        }
        supported_hover_labels: Dict[str, str] = {
            "row": "Row",
            "col": "Col",
            "time": "Time",
            "midi": "MIDI",
            "selected_area": "Name",
            "source_count": "Source row count",
            "source_rows": "Source df rows",
            "source_df": "Source df info",
        }
        provenance_field_map: Dict[str, str] = {}
        for source_col in provenance_columns:
            alias = _normalize_binary_hover_field_name(source_col)
            if alias and alias not in supported_hover_labels:
                provenance_field_map[alias] = str(source_col)
        for alias, source_col in provenance_field_map.items():
            supported_hover_labels.setdefault(alias, source_col)
        default_hover_fields = ["row", "col"]
        if provenance is not None:
            default_hover_fields.extend(["source_count", "source_rows"])
        requested_hover_fields = (
            list(hover_fields) if hover_fields is not None else list(default_hover_fields)
        )
        normalized_hover_fields = []
        for field in requested_hover_fields:
            normalized = hover_field_aliases.get(
                _normalize_binary_hover_field_name(field),
                _normalize_binary_hover_field_name(field),
            )
            if normalized in supported_hover_labels and normalized not in normalized_hover_fields:
                normalized_hover_fields.append(normalized)
        if not normalized_hover_fields:
            normalized_hover_fields = list(default_hover_fields)
        binary_section_fields = [
            field_name for field_name in normalized_hover_fields
            if field_name in {"row", "col", "time", "midi"}
        ]
        selected_area_fields = [
            field_name for field_name in normalized_hover_fields
            if field_name in {"selected_area"}
        ]
        df_section_fields = [
            field_name for field_name in normalized_hover_fields
            if field_name not in {"row", "col", "time", "midi", "selected_area"}
        ]
        requested_provenance_aliases = [
            field_name for field_name in df_section_fields if field_name in provenance_field_map
        ]

        hover_source_data: Optional[Dict[str, List[Any]]] = None
        total_rows, total_cols = matrix.shape
        if total_rows and total_cols:
            hover_source_data = {
                "x": [],
                "y": [],
                "w": [],
                "h": [],
                "row": [],
                "col": [],
                "time": [],
                "midi": [],
                **({"selected_area": [], "selected_area_display": []} if selected_area_fields else {}),
                **({"source_df_display": []} if df_section_fields else {}),
                **({"source_count": []} if "source_count" in df_section_fields else {}),
                **({"source_rows": []} if "source_rows" in df_section_fields else {}),
                **({"source_df": []} if "source_df" in df_section_fields else {}),
            }
            for field_name in requested_provenance_aliases:
                hover_source_data[field_name] = []

            def _join_unique(values: Sequence[Any]) -> str:
                seen: set[str] = set()
                joined: List[str] = []
                for value in values:
                    text = _format_binary_hover_value(value)
                    if not text or text in seen:
                        continue
                    seen.add(text)
                    joined.append(text)
                return " | ".join(joined)

            active_cell_map = provenance.get("active_cell_map", {}) if provenance is not None else {}
            if hover_scope == "all":
                hover_cells = (
                    (raw_row, col)
                    for raw_row in range(total_rows)
                    for col in range(total_cols)
                )
            elif hover_scope == "active_or_highlighted":
                hover_cell_set = {
                    (int(raw_row), int(col))
                    for raw_row, col in zip(*np.nonzero(np.asarray(matrix)))
                }
                for spec in highlight_specs:
                    for raw_row in range(int(spec["row_start"]), int(spec["row_stop"])):
                        for col in range(int(spec["col_start"]), int(spec["col_stop"])):
                            hover_cell_set.add((raw_row, col))
                hover_cells = iter(sorted(hover_cell_set))
            else:
                hover_cells = (
                    (int(raw_row), int(col))
                    for raw_row, col in zip(*np.nonzero(np.asarray(matrix)))
                )

            for raw_row, col in hover_cells:
                display_row = raw_row if origin == "lower" else (total_rows - 1 - raw_row)
                axis_value = _binary_row_axis_value_from_meta(meta, raw_row)
                time_start = col * resolution
                time_end_cell = (col + 1) * resolution
                source_positions = list(active_cell_map.get(_binary_cell_key(raw_row, col), []))
                source_rows = _binary_meta_source_rows(meta, source_positions) if source_positions else []
                selected_area_names = [
                    spec["name"]
                    for spec in highlight_specs
                    if spec.get("name")
                    and spec["row_start"] <= raw_row < spec["row_stop"]
                    and spec["col_start"] <= col < spec["col_stop"]
                ]

                hover_source_data["x"].append(float(time_start + (resolution / 2.0)))
                hover_source_data["y"].append(float(y_min + display_row + 0.5))
                hover_source_data["w"].append(float(resolution))
                hover_source_data["h"].append(1.0)
                hover_source_data["row"].append(str(int(raw_row)))
                hover_source_data["col"].append(str(int(col)))
                hover_source_data["time"].append(
                    f"[{_format_binary_hover_value(time_start)}, {_format_binary_hover_value(time_end_cell)})"
                )
                hover_source_data["midi"].append(_format_binary_hover_value(axis_value))

                if selected_area_fields:
                    hover_source_data["selected_area"].append(" | ".join(selected_area_names))
                    hover_source_data["selected_area_display"].append(
                        "block" if selected_area_names else "none"
                    )

                if df_section_fields:
                    hover_source_data["source_df_display"].append(
                        "block" if source_positions else "none"
                    )
                if "source_count" in df_section_fields:
                    hover_source_data["source_count"].append(str(len(source_positions)))
                if "source_rows" in df_section_fields:
                    hover_source_data["source_rows"].append(
                        ", ".join(_format_binary_hover_value(item.get("source_df_index")) for item in source_rows)
                    )
                if "source_df" in df_section_fields:
                    if source_rows:
                        hover_source_data["source_df"].append(
                            " || ".join(
                                f"[{_format_binary_hover_value(item.get('source_df_index'))}] "
                                + "; ".join(
                                    f"{col_name}={_format_binary_hover_value(item.get(col_name))}"
                                    for col_name in provenance_columns
                                    if _format_binary_hover_value(item.get(col_name))
                                )
                                for item in source_rows
                            )
                        )
                    else:
                        hover_source_data["source_df"].append("")

                for alias in requested_provenance_aliases:
                    source_col = provenance_field_map[alias]
                    values_here = [row_info.get(source_col) for row_info in source_rows]
                    hover_source_data[alias].append(_join_unique(values_here))

        # Normalize zoom dimension options
        def _norm_dim(val: Optional[str]) -> str:
            if val is None:
                return "both"
            v = str(val).strip().lower()
            if v in {"x", "width"}:
                return "width"
            if v in {"y", "height"}:
                return "height"
            return "both"

        drag_dim = _norm_dim(zoom_drag_dim)
        wheel_dim = _norm_dim(zoom_wheel_dim)

        def _build_plot() -> Any:
            color_mapper = LinearColorMapper(palette=["#ffffff", "#000000"], low=0, high=1)
            rows, cols = matrix_for_bokeh.shape
            plot = figure(
                height=height_pixels,
                width=width_pixels,
                title="Binary Matrix Representation",
                x_axis_label="Time (in duration units)",
                y_axis_label=("Pitch Class" if y_mode == "chroma" else "MIDI Number"),
                tools="pan,reset,save",
            )
            try:
                plot.output_backend = "canvas"
            except Exception:
                pass

            # Ranges
            plot.y_range.start = y_min
            plot.y_range.end = y_min + rows
            plot.x_range.start = 0
            plot.x_range.end = time_end

            # Image
            plot.image(
                image=[matrix_for_bokeh],
                x=0,
                y=y_min,
                dw=time_end,
                dh=rows,
                color_mapper=color_mapper,
            )

            if highlight_specs:
                plot.quad(
                    left=[spec["x_start"] for spec in highlight_specs],
                    right=[spec["x_end"] for spec in highlight_specs],
                    bottom=[spec["y_start"] for spec in highlight_specs],
                    top=[spec["y_end"] for spec in highlight_specs],
                    fill_color=[spec["color"] for spec in highlight_specs],
                    fill_alpha=[spec["alpha"] for spec in highlight_specs],
                    line_color=[spec["line_color"] for spec in highlight_specs],
                    line_width=[spec["line_width"] for spec in highlight_specs],
                )

            # Measure lines
            if show_measure_lines and measure_offsets is not None:
                for m_offset in measure_offsets:
                    plot.add_layout(
                        Span(
                            location=m_offset,
                            dimension="height",
                            line_color=str(measure_line_color),
                            line_dash="dashed",
                            line_width=1,
                        )
                    )

            # Y-axis labels
            if y_mode == "chroma":
                if labels_display:
                    plot.yaxis.ticker = BasicTicker(desired_num_ticks=len(labels_display))
                    plot.yaxis.major_label_overrides = {i: lbl for i, lbl in enumerate(labels_display)}
            else:
                if pitch_labels and labels_display:
                    plot.yaxis.ticker = BasicTicker()
                    plot.yaxis.major_label_overrides = {i + y_min: lbl for i, lbl in enumerate(labels_display)}

            # Tools configuration (mirror draw_piano_roll)
            try:
                box_tool = BoxZoomTool(dimensions=drag_dim)
                wheel_tool = WheelZoomTool(dimensions=wheel_dim)
                plot.add_tools(box_tool, wheel_tool)
                pan_tool = plot.select_one(PanTool)
                if pan_tool is None:
                    pan_tool = PanTool()
                    plot.add_tools(pan_tool)
                plot.toolbar.active_drag = pan_tool
                plot.toolbar.active_scroll = wheel_tool
            except Exception:
                pass

            # Optional hover (Bokeh only): time, pitch row index, and/or MIDI (from row via meta)
            if show_hover:
                if hover_source_data is not None:
                    hover_src = ColumnDataSource(data=hover_source_data)
                    hover_renderer = plot.rect(
                        x="x",
                        y="y",
                        width="w",
                        height="h",
                        source=hover_src,
                        fill_alpha=0.0,
                        line_alpha=0.0,
                    )
                    tooltip_parts: List[str] = []
                    if binary_section_fields:
                        tooltip_parts.append(
                            "<div style='margin-bottom:6px;'><span style='font-weight:600;'>Binary</span></div>"
                        )
                        for field_name in binary_section_fields:
                            tooltip_parts.append(
                                f"<div><span style='font-weight:600;'>{supported_hover_labels[field_name]}:</span> @{field_name}</div>"
                            )
                    if selected_area_fields:
                        tooltip_parts.append(
                            "<div style='display:@selected_area_display; margin-top:8px;'>"
                            "<div style='margin-bottom:6px;'><span style='font-weight:600;'>Selected Area</span></div>"
                        )
                        for field_name in selected_area_fields:
                            tooltip_parts.append(
                                f"<div><span style='font-weight:600;'>{supported_hover_labels[field_name]}:</span> @{field_name}</div>"
                            )
                        tooltip_parts.append("</div>")
                    if df_section_fields:
                        tooltip_parts.append(
                            "<div style='display:@source_df_display; margin-top:8px;'>"
                            "<div style='margin-bottom:6px;'><span style='font-weight:600;'>Source DF</span></div>"
                        )
                        for field_name in df_section_fields:
                            tooltip_parts.append(
                                f"<div><span style='font-weight:600;'>{supported_hover_labels[field_name]}:</span> @{field_name}</div>"
                            )
                        tooltip_parts.append("</div>")
                    tooltip_html = "<div>" + "".join(tooltip_parts) + "</div>"
                    if tooltip_parts:
                        hover_tool = HoverTool(tooltips=tooltip_html, renderers=[hover_renderer])
                        plot.add_tools(hover_tool)

            return plot

        # Build the plot used for display/return (complete plot)
        p = _build_plot()

        # Determine whether to save HTML (explicit toggle with back-compat)
        do_save_html = (bool(save_html) if save_html is not None else (save_html_path is not None))
        if do_save_html:
            try:
                from bokeh.embed import file_html  # type: ignore
                from bokeh.resources import INLINE  # type: ignore
                html = file_html(_build_plot(), INLINE, title="Binary Matrix")
                import io, os
                from datetime import datetime
                html_target = str(save_html_path) if save_html_path else "binary_matrix.html"
                abs_path = os.path.abspath(html_target)
                with io.open(abs_path, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"Data saved successfully to {abs_path} at {datetime.now().isoformat(timespec='seconds')}.")
                if open_html_after_save:
                    try:
                        import webbrowser
                        webbrowser.open_new_tab(abs_path)
                    except Exception:
                        pass
            except Exception as _exc:
                print(f"Warning: Failed to save HTML to '{save_html_path or 'binary_matrix.html'}': {_exc}")

        if save_png_path:
            try:
                from bokeh.io import export_png  # type: ignore
                import os
                from datetime import datetime
                abs_png = os.path.abspath(str(save_png_path))
                export_png(_build_plot(), filename=abs_png)
                print(f"Data saved successfully to {abs_png} at {datetime.now().isoformat(timespec='seconds')}.")
            except Exception as _exc:
                print(
                    "Warning: Failed to export PNG. Install 'selenium' and a webdriver (e.g., chromedriver). "
                    f"Error: {_exc}"
                )

        if show:
            bokeh_show(p)
            return None
        return p

    raise ValueError("Unsupported backend. Choose from 'plt', 'bokeh', or 'none'.")


def get_binary_cell_provenance(
    meta: Dict[str, Any],
    row: int,
    col: int,
    *,
    as_dataframe: bool = False,
) -> Dict[str, Any]:
    """
    Return axis coordinates and source DataFrame rows linked to one binary cell.

    Parameters
    ----------
    meta : dict
        Metadata returned by create_binary_matrix with include_provenance=True.
    row, col : int
        Raw matrix coordinates (same orientation as the matrix returned by create_binary_matrix).
    as_dataframe : bool, optional
        If True, include a pandas DataFrame under 'source_df'.
    """
    row_idx = int(row)
    col_idx = int(col)
    resolution = float(meta.get("resolution", 1.0))
    source_rows = _binary_meta_source_rows(
        meta,
        list(
            (
                meta.get("provenance", {})
                if isinstance(meta.get("provenance"), dict)
                else {}
            ).get("active_cell_map", {}).get(_binary_cell_key(row_idx, col_idx), [])
        ),
    )
    out: Dict[str, Any] = {
        "row": row_idx,
        "col": col_idx,
        "time_start": float(col_idx * resolution),
        "time_end": float((col_idx + 1) * resolution),
        "axis_value": _binary_row_axis_value_from_meta(meta, row_idx),
        "axis_label": _binary_row_axis_label_from_meta(meta, row_idx),
        "source_rows": source_rows,
        "source_count": len(source_rows),
    }
    if as_dataframe:
        out["source_df"] = pd.DataFrame(source_rows)
    return out


def get_binary_row_info(meta: Dict[str, Any], row: int) -> Dict[str, Any]:
    """
    Return raw binary row coordinates plus the corresponding axis value/label.
    """
    row_idx = int(row)
    axis_value = _binary_row_axis_value_from_meta(meta, row_idx)
    out: Dict[str, Any] = {
        "row": row_idx,
        "axis_value": axis_value,
        "axis_label": _binary_row_axis_label_from_meta(meta, row_idx),
    }
    if str(meta.get("y_mode", "minmax")).lower() != "chroma":
        try:
            out["midi"] = int(axis_value)
        except Exception:
            pass
    return out


def get_binary_col_info(meta: Dict[str, Any], col: int) -> Dict[str, Any]:
    """
    Return raw binary column coordinates plus the corresponding time bounds.
    """
    col_idx = int(col)
    resolution = float(meta.get("resolution", 1.0))
    return {
        "col": col_idx,
        "time_start": float(col_idx * resolution),
        "time_end": float((col_idx + 1) * resolution),
    }


def get_binary_window_provenance(
    meta: Dict[str, Any],
    row_start: int,
    row_stop: int,
    col_start: int,
    col_stop: int,
    *,
    unique: bool = True,
    as_dataframe: bool = False,
) -> Dict[str, Any]:
    """
    Collect source DataFrame rows linked to a binary window.

    Parameters
    ----------
    meta : dict
        Metadata returned by create_binary_matrix with include_provenance=True.
    row_start, row_stop, col_start, col_stop : int
        Half-open raw matrix window bounds.
    unique : bool, optional
        If True, de-duplicate source rows across all cells in the window.
    as_dataframe : bool, optional
        If True, include a pandas DataFrame under 'source_df'.
    """
    provenance = meta.get("provenance")
    active_cell_map = provenance.get("active_cell_map", {}) if isinstance(provenance, dict) else {}
    collected_positions: List[int] = []
    for row_idx in range(int(row_start), int(row_stop)):
        for col_idx in range(int(col_start), int(col_stop)):
            collected_positions.extend(active_cell_map.get(_binary_cell_key(row_idx, col_idx), []))
    if unique:
        seen_positions: set[int] = set()
        ordered_positions: List[int] = []
        for pos in collected_positions:
            source_pos = int(pos)
            if source_pos in seen_positions:
                continue
            seen_positions.add(source_pos)
            ordered_positions.append(source_pos)
        collected_positions = ordered_positions
    source_rows = _binary_meta_source_rows(meta, collected_positions)
    out: Dict[str, Any] = {
        "row_window": (int(row_start), int(row_stop)),
        "col_window": (int(col_start), int(col_stop)),
        "source_rows": source_rows,
        "source_count": len(source_rows),
    }
    if as_dataframe:
        out["source_df"] = pd.DataFrame(source_rows)
    return out


def binary_slice_to_df(
    matrix: np.ndarray,
    meta: Dict[str, Any],
    *,
    row_start: int = 0,
    col_start: int = 0,
) -> pd.DataFrame:
    """
    Decode a raw binary matrix slice while preserving its original matrix coordinates.

    Parameters
    ----------
    matrix : np.ndarray
        A raw binary matrix or submatrix using the same orientation as the output of
        create_binary_matrix.
    meta : dict
        Metadata returned by create_binary_matrix.
    row_start, col_start : int, optional
        Raw matrix offsets of the provided slice inside the full matrix.

    Returns
    -------
    pandas.DataFrame
        One row per contiguous active span with raw matrix coordinates and decoded
        time/axis information.
    """
    mat = np.asarray(matrix)
    if mat.ndim != 2:
        raise ValueError("matrix must be 2D (rows, cols)")
    resolution = float(meta.get("resolution", 1.0))
    rows, cols = mat.shape
    mat_bin = (mat > 0).astype(int)
    records: List[Dict[str, Any]] = []
    for local_row in range(rows):
        raw_row = int(row_start) + local_row
        row_info = get_binary_row_info(meta, raw_row)
        row_data = mat_bin[local_row]
        c = 0
        while c < cols:
            if row_data[c] != 1:
                c += 1
                continue
            start_local = c
            while c < cols and row_data[c] == 1:
                c += 1
            end_local = c
            raw_col_start = int(col_start) + start_local
            raw_col_end = int(col_start) + end_local
            record: Dict[str, Any] = {
                "Binary Row": raw_row,
                "Binary Col Start": raw_col_start,
                "Binary Col End": raw_col_end,
                "Global Onset": float(raw_col_start * resolution),
                "Time End": float(raw_col_end * resolution),
                "Duration": float((raw_col_end - raw_col_start) * resolution),
                "Axis Value": row_info["axis_value"],
                "Axis Label": row_info["axis_label"],
            }
            if "midi" in row_info:
                record["MIDI"] = row_info["midi"]
            records.append(record)
    out = pd.DataFrame(records)
    if len(out):
        sort_cols = ["Global Onset", "Binary Row"]
        out = out.sort_values(sort_cols).reset_index(drop=True)
    return out


def orient_binary_matrix(
    matrix: np.ndarray,
    meta: Dict[str, Any],
    *,
    target_origin: str = "lower",
) -> np.ndarray:
    """
    Return a binary matrix oriented for the requested origin.

    Parameters
    ----------
    matrix : np.ndarray
        Matrix returned by create_binary_matrix.
    meta : dict
        Metadata dictionary returned alongside the matrix.
    target_origin : {"lower", "upper"}
        Desired orientation. "lower" keeps the lowest MIDI pitch at the bottom;
        "upper" places the lowest MIDI pitch at the top.

    Returns
    -------
    np.ndarray
        Matrix oriented toward the requested origin. When a flip is required the
        returned view shares data via numpy.flipud.
    """
    current_origin = str(meta.get("origin", "lower")).lower()
    requested_origin = str(target_origin or "lower").lower()
    valid = {"lower", "upper"}
    if current_origin not in valid:
        current_origin = "lower"
    if requested_origin not in valid:
        raise ValueError("target_origin must be 'lower' or 'upper'.")
    if current_origin == requested_origin:
        return matrix
    return np.flipud(matrix)



# ----------------------------------------
# Binary matrix -> DataFrame (inverse ops)
# ----------------------------------------
def binary_matrix_to_df(
    matrix: np.ndarray,
    bottom_left_midi: int,
    resolution: float,
    *,
    increasing_upwards: bool = True,
) -> pd.DataFrame:
    """
    Parse a binary piano-roll matrix into a DataFrame using a bottom-left MIDI anchor and time resolution.

    Orientation:
    - If the matrix is a display/view (e.g., flipped with bottom being low MIDI), set increasing_upwards=True
      and pass bottom_left_midi = lowest MIDI (y_min).
    - If the matrix is a data matrix from create_binary_matrix (row 0 is low MIDI at the top),
      set increasing_upwards=False and pass bottom_left_midi = highest MIDI (y_max).

    Assumptions:
    - matrix shape is (num_rows, num_cols) where columns are time steps and rows are pitch bins.
    - The bottom-left cell corresponds to MIDI == bottom_left_midi at time 0.
    - Each column spans 'resolution' time units (e.g., quarterLength multiples).
    - Contiguous 1s in the same row form a note with Duration = (#cols) * resolution.
    """
    if resolution <= 0:
        raise ValueError("resolution must be a positive number")

    mat = np.asarray(matrix)
    if mat.ndim != 2:
        raise ValueError("matrix must be 2D (rows, cols)")

    rows, cols = mat.shape
    # Treat any positive value as 1
    mat_bin = (mat > 0).astype(int)

    midi_values: list[int] = []
    onsets: list[float] = []
    durations: list[float] = []

    # Iterate rows top-to-bottom in the array, but map to MIDI bottom-up
    for row_top in range(rows):
        row_from_bottom = rows - 1 - row_top
        if increasing_upwards:
            midi_value = int(bottom_left_midi + row_from_bottom)
        else:
            midi_value = int(bottom_left_midi - row_from_bottom)
        row_data = mat_bin[row_top]

        c = 0
        while c < cols:
            if row_data[c] == 1:
                start_c = c
                while c < cols and row_data[c] == 1:
                    c += 1
                end_c = c  # exclusive
                midi_values.append(midi_value)
                onsets.append(float(start_c * resolution))
                durations.append(float((end_c - start_c) * resolution))
            else:
                c += 1

    df = pd.DataFrame({
        "MIDI": midi_values,
        "Global Onset": onsets,
        "Duration": durations,
    })
    if len(df):
        df = df.sort_values(["Global Onset", "MIDI"]).reset_index(drop=True)
    return df


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["MIDI"] = out["MIDI"].astype(int)
    out["Global Onset"] = out["Global Onset"].astype(float).round(6)
    out["Duration"] = out["Duration"].astype(float).round(6)
    return out.sort_values(["Global Onset", "MIDI"]).reset_index(drop=True)


def binary_matrix_to_df_from_meta(
    matrix: np.ndarray,
    meta: dict,
    *,
    flipped: Optional[bool] = None,
) -> pd.DataFrame:
    """
    Convenience wrapper to convert a matrix back to DataFrame using meta from create_binary_matrix.
    - flipped=None (default) auto-detects the raw matrix orientation from ``meta["origin"]``
    - flipped=False for matrices whose top row maps to the lowest MIDI
    - flipped=True for matrices whose top row maps to the highest MIDI, or for flipped views
    """
    resolution = float(meta["resolution"])
    if flipped is None:
        flipped = str(meta.get("origin", "lower")).lower() == "upper"
    if flipped:
        return binary_matrix_to_df(
            matrix,
            bottom_left_midi=int(meta["y_min"]),
            resolution=resolution,
            increasing_upwards=True,
        )
    return binary_matrix_to_df(
        matrix,
        bottom_left_midi=int(meta["y_max"]),
        resolution=resolution,
        increasing_upwards=False,
    )


def binary_matrix_to_df_from_bounds(
    matrix: np.ndarray,
    *,
    resolution: float,
    midi_low: int | None = None,
    midi_high: int | None = None,
    flipped: bool = False,
) -> pd.DataFrame:
    """
    Convert without meta by specifying either midi_low (lowest MIDI) or midi_high (highest MIDI).
    - flipped=False for raw data matrices where row 0 is visually "top" and corresponds to lowest MIDI.
    - flipped=True for UI/display matrices where the bottom row is lowest MIDI (e.g., np.flipud view).
    Provide at least one of midi_low or midi_high. If one is missing, it will be inferred from the other.
    """
    rows = int(np.asarray(matrix).shape[0])
    if resolution <= 0:
        raise ValueError("resolution must be positive")

    if flipped:
        if midi_low is None and midi_high is None:
            raise ValueError("Provide midi_low or midi_high when flipped=True")
        if midi_low is None:
            midi_low = int(midi_high) - (rows - 1)
        return binary_matrix_to_df(matrix, bottom_left_midi=int(midi_low), resolution=resolution, increasing_upwards=True)

    # Not flipped: raw data orientation
    if midi_low is None and midi_high is None:
        raise ValueError("Provide midi_low or midi_high when flipped=False")
    if midi_high is None:
        midi_high = int(midi_low) + (rows - 1)
    return binary_matrix_to_df(matrix, bottom_left_midi=int(midi_high), resolution=resolution, increasing_upwards=False)


def round_trip_sanity_check(sample_df: pd.DataFrame, *, resolution: float = 0.5) -> tuple[bool, pd.DataFrame]:
    """
    Convert df -> binary (at resolution) -> df and report equality after normalization.
    Returns (ok, reconstructed_df).
    """
    mat, meta = create_binary_matrix(
        sample_df,
        resolution_method="manual",
        manual_resolution=resolution,
        y_mode="minmax",
    )
    # Try both orientations to be robust
    df_back_data = binary_matrix_to_df_from_meta(mat, meta, flipped=False)
    df_back_view = binary_matrix_to_df_from_meta(np.flipud(mat), meta, flipped=True)
    if _normalize_df(sample_df).equals(_normalize_df(df_back_data)):
        return True, df_back_data
    if _normalize_df(sample_df).equals(_normalize_df(df_back_view)):
        return True, df_back_view
    # Fallback: return the data-oriented reconstruction
    return False, df_back_data



# -----------------------------
# Notation parsing utilities
# -----------------------------
def parse_prototype_notation(notation: str) -> pd.DataFrame:
    """
    Parse a custom prototype notation string into a DataFrame with columns:
    'MIDI', 'Global Onset', 'Duration'.

    Token format: NOTE:ONSET:DURATION
      - NOTE: e.g., C4, D#5, Bb3
      - ONSET: float or fraction (e.g., 1.5 or 3/4)
      - DURATION: float or fraction
    Tokens can be separated by commas, semicolons, or newlines.
    """
    import re
    from fractions import Fraction
    from music21 import note as m21note

    pattern = re.compile(
        r"^\s*([A-Ga-g][#b]?-?\d+)\s*:\s*([\-+]?(?:\d+(?:\.\d+)?|\.\d+|\d+\/\d+))\s*:\s*([\-+]?(?:\d+(?:\.\d+)?|\.\d+|\d+\/\d+))\s*$"
    )

    def to_number(text: str) -> float:
        s = text.strip()
        return float(Fraction(s)) if "/" in s else float(s)

    tokens = [t.strip() for t in re.split(r"[\,\n;]+", notation) if t.strip()]

    midi_numbers = []
    onsets = []
    durations = []

    for tok in tokens:
        m = pattern.match(tok)
        if not m:
            raise ValueError(f"Invalid notation token: '{tok}' (expected NOTE:ONSET:DURATION)")
        note_name, onset_str, dur_str = m.groups()
        midi_num = m21note.Note(note_name).pitch.midi
        midi_numbers.append(int(midi_num))
        onsets.append(to_number(onset_str))
        durations.append(to_number(dur_str))

    prototype_df = pd.DataFrame({
        "MIDI": midi_numbers,
        "Global Onset": onsets,
        "Duration": durations,
    })
    if len(prototype_df):
        prototype_df = prototype_df.sort_values(["Global Onset", "MIDI"]).reset_index(drop=True)
    return prototype_df


def _stream_to_df(m21_stream) -> pd.DataFrame:
    """
    Convert a music21 Stream to a DataFrame with columns:
    'MIDI', 'Global Onset', 'Duration'.
    - Expands chords to individual pitches.
    - Merges ties if possible.
    """
    s = m21_stream
    try:
        s = s.stripTies(inPlace=False)
    except Exception:
        pass

    flat_stream = s.flatten()
    rows = []
    for el in flat_stream.notes:
        onset = float(el.offset)
        dur = float(el.duration.quarterLength)
        if getattr(el, "isChord", False):
            for p in el.pitches:
                rows.append((int(p.midi), onset, dur))
        else:
            rows.append((int(el.pitch.midi), onset, dur))

    df = pd.DataFrame(rows, columns=["MIDI", "Global Onset", "Duration"])
    if len(df):
        df = df.sort_values(["Global Onset", "MIDI"]).reset_index(drop=True)
    return df


def _preprocess_humdrum_text(text: str) -> str:
    """
    Normalize Humdrum/**kern text coming from triple-quoted, indented notebook cells:
    - Remove common indentation
    - Normalize newlines to \n
    - Trim leading/trailing spaces on each line
    - Drop empty lines
    - Ensure a trailing newline (some parsers expect it)
    """
    # Remove common indentation and normalize newlines
    normalized = textwrap.dedent(text).replace("\r\n", "\n").replace("\r", "\n")
    # Left/right trim each line and drop empties
    lines = [ln.strip() for ln in normalized.split("\n") if ln.strip()]
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    return result

def parse_notation(text: str, syntax: str, *, return_meta: bool = False) -> pd.DataFrame:
    """
    Unified notation parser.

    Parameters
    ----------
    text : str
        Notation text content.
    syntax : str
        One of {'prototype', 'tinynotation', 'humdrum', 'abc', 'lilypond'}.

    Returns
    -------
    pandas.DataFrame
        DataFrame with columns ['MIDI', 'Global Onset', 'Duration'] (quarterLength units).
    """
    from music21 import converter

    s = (syntax or "").strip().lower()
    fmt = None
    df: Optional[pd.DataFrame] = None

    if s in ("prototype", "proto", "custom"):
        fmt = "prototype"
        df = parse_prototype_notation(text)
    elif s in ("tinynotation", "tiny", "tn"):
        fmt = "tinynotation"
        m21 = converter.parse(f"tinynotation: {text}")
        df = _stream_to_df(m21)
    elif s in ("humdrum", "kern"):
        fmt = "humdrum"
        processed = _preprocess_humdrum_text(text)
        m21 = converter.parseData(processed, format="humdrum")
        df = _stream_to_df(m21)
    elif s == "abc":
        fmt = "abc"
        m21 = converter.parseData(text, format="abc")
        df = _stream_to_df(m21)
    elif s in ("lilypond", "ly", "lily"):
        fmt = "lilypond"
        try:
            m21 = converter.parseData(text, format="lilypond")
        except Exception as exc:
            raise RuntimeError(
                "Failed to parse LilyPond. Ensure LilyPond is installed and on PATH."
            ) from exc
        df = _stream_to_df(m21)
    else:
        raise ValueError(
            f"Unsupported syntax '{syntax}'. Choose from: prototype, tinynotation, humdrum, abc, lilypond"
        )

    if return_meta:
        return df, {"parsed_format": fmt}  # type: ignore[return-value]
    return df  # type: ignore[return-value]

    raise ValueError(
        f"Unsupported syntax '{syntax}'. Choose from: prototype, tinynotation, humdrum, abc, lilypond"
    )


def create_prototype_binary_matrix(
    prototype_df: pd.DataFrame,
    *,
    resolution: float = 0.5,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Convert a prototype DataFrame into a binary matrix.

    This is a thin wrapper around create_binary_matrix using a manual resolution
    and the 'minmax' y-axis mode.

    Returns (matrix, meta) in the same structure as create_binary_matrix.
    """
    return create_binary_matrix(
        prototype_df,
        resolution_method="manual",
        manual_resolution=resolution,
        y_mode="minmax",
    )


def plot_prototype_binary_matrix(
    matrix: np.ndarray,
    meta: Dict[str, Any],
    *,
    backend: str = "plt",
    measure_offsets: Optional[List[float]] = None,
    show_measure_lines: bool = True,
    show: bool = True,
) -> Any:
    """
    Visualize a prototype binary matrix using the selected backend.
    """
    return plot_binary_matrix(
        matrix,
        meta,
        backend=backend,
        measure_offsets=measure_offsets,
        show_measure_lines=show_measure_lines,
        show=show,
    )
