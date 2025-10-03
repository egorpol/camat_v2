from __future__ import annotations

import os
import tempfile
from typing import List, Tuple, Optional, Dict, Any, Iterable

import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from music21 import note, chord, pitch as pitch_module
try:
    from tqdm.auto import tqdm as _tqdm  # Notebook/terminal-friendly progress bar
except Exception:  # pragma: no cover - optional dependency at runtime
    _tqdm = None


__all__ = [
    "get_file_path",
    "extract_voice_data",
    "filter_and_adjust_durations",
    "get_measure_offsets",
    "draw_piano_roll",
    "create_piano_roll",
    "parse_files",
    "create_binary_matrix",
    "plot_binary_matrix",
    "orient_binary_matrix",
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


def get_file_path(file_source: str, *, timeout_seconds: int = 30) -> str:
    """
    Resolve a local path from a URL or verify a local path exists.

    Parameters
    ----------
    file_source : str
        URL or local file path.
    timeout_seconds : int, optional
        Timeout for downloading remote files (seconds). Default is 30.

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
    show_measure_lines: bool = True,
    pitch_labels: bool = True,
    show: bool = True,
    plot_width: Optional[int] = None,
    plot_height: Optional[int] = None,
    dpi: float = 100.0,
    zoom_drag_dim: Optional[str] = None,
    zoom_wheel_dim: Optional[str] = None,
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
    show_measure_lines : bool
        Whether to draw vertical red measure separation lines when measure offsets are provided.
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

    if backend == "plt":
        # Convert pixels to inches for matplotlib
        width_inches = width_pixels / dpi
        height_inches = height_pixels / dpi
        fig, ax = plt.subplots(figsize=(width_inches, height_inches))
        for _, row in df.iterrows():
            ax.barh(
                row["MIDI"],
                width=row["Duration"],
                left=row["Global Onset"],
                height=0.6,
                color="skyblue",
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
                ax.axvline(x=m_offset, color="red", linestyle="--", linewidth=0.8)

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
            from bokeh.models import Span, ColumnDataSource, BoxZoomTool, WheelZoomTool, PanTool
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
                        output_notebook(hide_banner=True)
                        BOKEH_NOTEBOOK_INITIALIZED = True
                    except Exception:
                        # If initialization fails, continue; show() may open a new tab
                        pass
        except ImportError as exc:
            raise ImportError("Bokeh is not installed. Install bokeh to use the 'bokeh' backend.") from exc

        source = ColumnDataSource(
            data={
                "y": df["MIDI"],
                "left": df["Global Onset"],
                "right": df["Global Onset"] + df["Duration"],
                "pitch": df["Pitch"],
            }
        )

        y_min = int(min(midi_values)) - 1
        y_max = int(max(midi_values)) + 1

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

        p = figure(
            height=height_pixels,
            width=width_pixels,
            title="Piano Roll Visualization",
            x_axis_label="Global Onset (Quarter Lengths)",
            y_axis_label="Pitch",
            y_range=(y_min, y_max),
            tools="pan,reset,save",
        )
        p.hbar(y="y", left="left", right="right", height=0.6, source=source, fill_color="#87CEEB")

        # Configure tools: keep pan active by default, wheel zoom active for scroll
        try:
            # Ensure wheel/box are present with requested dimensions
            box_tool = BoxZoomTool(dimensions=drag_dim)
            wheel_tool = WheelZoomTool(dimensions=wheel_dim)
            p.add_tools(box_tool, wheel_tool)

            # Prefer existing pan tool if present; otherwise add one
            pan_tool = p.select_one(PanTool)
            if pan_tool is None:
                pan_tool = PanTool()
                p.add_tools(pan_tool)

            p.toolbar.active_drag = pan_tool
            p.toolbar.active_scroll = wheel_tool
        except Exception:
            pass

        if show_measure_lines and measure_offsets is not None:
            for m_offset in measure_offsets:
                p.add_layout(Span(location=m_offset, dimension="height", line_color="red", line_dash="dashed", line_width=1))

        if pitch_labels:
            p.yaxis.ticker = midi_values
            p.yaxis.major_label_overrides = {m: midi_to_pitch[m] for m in midi_values}

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
    df_processed = df.copy()

    if filter_zero_duration:
        df_processed = df_processed[df_processed["Duration"] > 0]

    if adjust_fractional_duration:
        df_processed["Duration"] = df_processed["Duration"].round(3)
        df_processed["Local Onset"] = df_processed["Local Onset"].round(3)
        df_processed["Global Onset"] = df_processed["Global Onset"].round(3)

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
                        show=True,
                        plot_width=plot_width,
                        plot_height=plot_height,
                        zoom_drag_dim=zoom_drag_dim,
                        zoom_wheel_dim=zoom_wheel_dim,
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


def create_binary_matrix(
    df: pd.DataFrame,
    *,
    resolution_method: str = "auto",
    manual_resolution: Optional[float] = None,
    y_mode: str = "minmax",  # "full" | "minmax" | "chroma"
    midi_low: Optional[int] = None,
    midi_high: Optional[int] = None,
    row_order: str = "low_to_high",
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

    Returns
    -------
    (matrix, meta)
        matrix : np.ndarray of shape (num_pitches, num_cols), dtype=int
        meta : dict with keys: resolution, num_cols, time_end, y_mode, y_min, y_max,
               midi_low, midi_high, row_order, origin, pitch_class_labels (when chroma)
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

    # Fill matrix
    for _, row in df.iterrows():
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

    meta: Dict[str, Any] = {
        "resolution": resolution,
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
        **({"pitch_class_labels": pitch_class_labels} if pitch_class_labels is not None else {}),
    }

    return matrix, meta


def plot_binary_matrix(
    matrix: np.ndarray,
    meta: Dict[str, Any],
    *,
    backend: str = "plt",
    measure_offsets: Optional[List[float]] = None,
    show_measure_lines: bool = True,
    cmap: str = "gray_r",
    show: bool = True,
    plot_width: Optional[int] = None,
    plot_height: Optional[int] = None,
    dpi: float = 100.0,
    zoom_drag_dim: Optional[str] = None,
    zoom_wheel_dim: Optional[str] = None,
) -> Any:
    """
    Visualize a binary matrix using Matplotlib or Bokeh, similar to draw_piano_roll.

    Parameters
    ----------
    matrix : np.ndarray
        Binary matrix (rows=pitches, cols=time steps).
    meta : dict
        Metadata returned by create_binary_matrix.
    backend : {"plt", "bokeh"}
        Plotting backend to use.
    measure_offsets : list[float], optional
        Global onset times where measures start. Drawn as vertical lines when provided.
    show_measure_lines : bool
        Whether to draw measure lines when offsets are provided.
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

    Returns
    -------
    Any
        Backend-specific figure object.
    """
    backend = (backend or "plt").lower()

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

    matrix_for_display = matrix if origin == "lower" else np.flipud(matrix)
    labels_display = meta.get("pitch_class_labels", [])
    if labels_display:
        labels_display = list(labels_display)
        if origin == "upper":
            labels_display.reverse()

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
                ax.axvline(x=m_offset, color="red", linestyle="--", linewidth=0.8)

        cbar = fig.colorbar(plt.cm.ScalarMappable(cmap=cmap), ax=ax, ticks=[0, 1])
        cbar.set_label("Note On/Off")
        fig.tight_layout()
        if show:
            plt.show()
        return fig

    if backend == "bokeh":
        try:
            from bokeh.plotting import figure, show as bokeh_show
            from bokeh.models import Span, LinearColorMapper, ColorBar, BasicTicker, BoxZoomTool, WheelZoomTool, PanTool
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
                        output_notebook(hide_banner=True)
                        BOKEH_NOTEBOOK_INITIALIZED = True
                    except Exception:
                        pass
        except ImportError as exc:
            raise ImportError("Bokeh is not installed. Install bokeh to use the 'bokeh' backend.") from exc

        matrix_for_bokeh = np.ascontiguousarray(matrix_for_display)

        p = figure(
            height=height_pixels,
            width=width_pixels,
            title="Binary Matrix Representation",
            x_axis_label="Time (in duration units)",
            y_axis_label=("Pitch Class" if y_mode == "chroma" else "MIDI Number"),
            tools="pan,wheel_zoom,box_zoom,reset,save",
        )

        color_mapper = LinearColorMapper(palette=["#ffffff", "#000000"], low=0, high=1)

        # Ensure y-range covers one unit per row so that integer ticks align with row indices
        rows, cols = matrix_for_bokeh.shape
        p.y_range.start = y_min
        p.y_range.end = y_min + rows
        p.x_range.start = 0
        p.x_range.end = time_end

        p.image(
            image=[matrix_for_bokeh],
            x=0,
            y=y_min,
            dw=time_end,
            dh=rows,
            color_mapper=color_mapper,
        )

        if show_measure_lines and measure_offsets is not None:
            for m_offset in measure_offsets:
                p.add_layout(Span(location=m_offset, dimension="height", line_color="red", line_dash="dashed", line_width=1))

        # Configure y-axis ticks/labels
        if y_mode == "chroma":
            if labels_display:
                p.yaxis.ticker = BasicTicker(desired_num_ticks=len(labels_display))
                p.yaxis.major_label_overrides = {i: lbl for i, lbl in enumerate(labels_display)}
        else:
            # Let Bokeh auto-decide ticks; when possible it will align to integers
            pass

        color_bar = ColorBar(color_mapper=color_mapper, label_standoff=8, location=(0, 0))
        p.add_layout(color_bar, "right")

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

        # Configure tools: keep pan active by default, wheel zoom active for scroll
        try:
            # Ensure wheel/box are present with requested dimensions
            box_tool = BoxZoomTool(dimensions=drag_dim)
            wheel_tool = WheelZoomTool(dimensions=wheel_dim)
            p.add_tools(box_tool, wheel_tool)

            # Prefer existing pan tool if present; otherwise add one
            pan_tool = p.select_one(PanTool)
            if pan_tool is None:
                pan_tool = PanTool()
                p.add_tools(pan_tool)

            p.toolbar.active_drag = pan_tool
            p.toolbar.active_scroll = wheel_tool
        except Exception:
            pass

        if show:
            bokeh_show(p)
        return p

    raise ValueError("Unsupported backend. Choose from 'plt' or 'bokeh'.")

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


def binary_matrix_to_df_from_meta(matrix: np.ndarray, meta: dict, *, flipped: bool = False) -> pd.DataFrame:
    """
    Convenience wrapper to convert a matrix back to DataFrame using meta from create_binary_matrix.
    - flipped=False for raw data matrices (row 0 is lowest MIDI at the top)
    - flipped=True for views like np.flipud(matrix) where bottom is lowest MIDI
    """
    resolution = float(meta["resolution"])
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

    flat_stream = s.flat
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
        m21 = converter.parseData(text, format="humdrum")
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

