from __future__ import annotations

from typing import Optional, Tuple, Sequence, Mapping, Any, Union

import random
import colorsys
import inspect

import pandas as pd
from IPython.display import display as ipy_display  # type: ignore

from .music_utils import draw_piano_roll


# --------------------------------------------------------------------
# Color + multi-series plotting helpers
# --------------------------------------------------------------------

_DEFAULT_PITCH_PALETTE = [
    '#4682B4',  # steel blue
    '#D2691E',  # chocolate
    '#2E8B57',  # sea green
    '#8B008B',  # dark magenta
    '#FF8C00',  # dark orange
    '#20B2AA',  # light sea green
    '#A0522D',  # sienna
    '#708090',  # slate gray
]

_DEFAULT_DURATION_PALETTE = [
    '#2E8B57',  # sea green
    '#8B4513',  # saddle brown
    '#1E90FF',  # dodger blue
    '#B22222',  # firebrick
    '#FF8C00',  # dark orange
    '#6A5ACD',  # slate blue
]


def _random_contrasting_color(existing_hex: Sequence[str]) -> str:
    """
    Generate a random bright-ish color in HEX, trying to avoid very close
    duplicates to the existing colors.
    """

    def _hex_to_rgb(h: str) -> Tuple[float, float, float]:
        h = h.lstrip('#')
        if len(h) != 6:
            return (0.0, 0.0, 0.0)
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return (r, g, b)

    def _dist(c1: Tuple[float, float, float], c2: Tuple[float, float, float]) -> float:
        return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5

    existing_rgb = [_hex_to_rgb(c) for c in existing_hex if isinstance(c, str)]

    for _ in range(32):
        # Use golden-ratio trick in HSV space for well-separated hues
        h = random.random()
        s = 0.6 + 0.4 * random.random()
        v = 0.7 + 0.3 * random.random()
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        candidate = '#%02X%02X%02X' % (int(r * 255), int(g * 255), int(b * 255))
        c_rgb = (r, g, b)
        if not existing_rgb:
            return candidate
        if all(_dist(c_rgb, e) > 0.25 for e in existing_rgb):
            return candidate

    # Fallback if we somehow fail to find a far-enough color
    return '#%06X' % random.randint(0, 0xFFFFFF)


def _normalize_color_input(
    bar_color: Union[str, Sequence[str], None],
    n_series: int,
    default_palette: Sequence[str],
) -> list[str]:
    """
    Turn a single color or a list of colors into a list of length n_series.

    - If bar_color is a string: use it for the first series, generate contrasting
      colors for the rest.
    - If bar_color is a sequence: use as many as available; when there are not
      enough unique colors, extend with random contrasting colors.
    - If bar_color is None/empty: start from default_palette and extend as needed.
    """
    colors: list[str] = []

    if isinstance(bar_color, str):
        colors = [bar_color]
    else:
        try:
            # Treat non-string sequence as list of color strings
            if bar_color is not None:
                colors = [str(c) for c in bar_color]  # type: ignore[arg-type]
        except TypeError:
            colors = []

    if not colors:
        colors = list(default_palette)

    # Ensure enough colors; extend with random contrasting ones if necessary.
    while len(colors) < n_series:
        colors.append(_random_contrasting_color(colors))

    return colors[:n_series]


def _guess_labels_for_dfs(
    dfs: Sequence[pd.DataFrame],
    default_prefix: str = "Source",
) -> list[str]:
    """
    Try to recover user-facing variable names for the given DataFrames by
    inspecting the caller's frame (locals + globals). When that fails, fall
    back to sequential labels like "Source 1", "Source 2", etc.
    """
    labels: list[Optional[str]] = [None] * len(dfs)

    try:
        frame = inspect.currentframe()
        caller = frame.f_back if frame is not None else None
        if caller is not None:
            id_to_index = {id(df): i for i, df in enumerate(dfs)}

            for scope in (caller.f_locals, caller.f_globals):
                for name, val in scope.items():
                    idx = id_to_index.get(id(val))
                    if idx is None:
                        continue
                    if labels[idx] is not None:
                        continue
                    # Skip internal/less informative names
                    if name.startswith('_'):
                        continue
                    if name in ('source', 'source_df'):
                        continue
                    labels[idx] = str(name)
    except Exception:
        # Best-effort only; silently fall back on failure
        pass

    out: list[str] = []
    for i, lbl in enumerate(labels):
        if lbl is None or not str(lbl).strip():
            out.append(f"{default_prefix} {i + 1}")
        else:
            out.append(str(lbl))
    return out


def _plot_multi_bar(
    *,
    categories: Sequence[Any],
    series_values: Sequence[Sequence[float]],
    series_labels: Sequence[str],
    title: str,
    x_label: str,
    y_label: str,
    backend: str,
    plot_width: int,
    plot_height: int,
    show_hover: bool,
    bar_color: Union[str, Sequence[str], None],
    default_palette: Sequence[str],
):
    """
    Generic grouped bar plotter for both Matplotlib and Bokeh.

    `categories` defines the x-axis categories.
    `series_values[j][i]` is the value for series j at category i.
    """
    backend_opt = (backend or 'plt').strip().lower()
    n_series = len(series_labels)
    colors = _normalize_color_input(bar_color, n_series, default_palette)
    x_labels = [str(c) for c in categories]

    if n_series == 0 or not x_labels:
        return None

    if backend_opt == 'plt':
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(plot_width / 100.0, plot_height / 100.0))
        x_indices = list(range(len(x_labels)))
        width = 0.8 / max(n_series, 1)
        offset_start = -0.5 * (n_series - 1) * width

        for j, label in enumerate(series_labels):
            offset = offset_start + j * width
            xs = [i + offset for i in x_indices]
            ys = list(series_values[j])
            ax.bar(xs, ys, width=width, label=label, color=colors[j])

        ax.set_xticks(x_indices)
        ax.set_xticklabels(x_labels, rotation=90)
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        ax.set_title(title)
        ax.legend()
        plt.tight_layout()
        plt.show()
        return None

    if backend_opt == 'bokeh':
        from bokeh.plotting import figure, show
        from bokeh.io import output_notebook
        from bokeh.models import ColumnDataSource, HoverTool
        from bokeh.transform import dodge

        output_notebook()

        # One categorical axis (pitch / duration), with grouped bars per category
        data = {'x': x_labels}
        for j, _label in enumerate(series_labels):
            data[f's{j}'] = [float(v) for v in series_values[j]]

        source = ColumnDataSource(data)

        p = figure(
            x_range=x_labels,
            height=plot_height,
            width=plot_width,
            title=title,
            toolbar_location='right',
        )

        width = 0.8 / max(n_series, 1)
        offset_start = -0.5 * (n_series - 1) * width
        hover_renderers = []

        for j, label in enumerate(series_labels):
            offset = offset_start + j * width
            field_name = f's{j}'
            r = p.vbar(
                x=dodge('x', offset, range=p.x_range),
                top=field_name,
                width=width,
                source=source,
                color=colors[j],
                legend_label=str(label),
            )
            hover_renderers.append((r, label, field_name))

        if show_hover:
            for r, label, field_name in hover_renderers:
                p.add_tools(
                    HoverTool(
                        renderers=[r],
                        tooltips=[
                            (x_label, '@x'),
                            ('Series', str(label)),
                            (y_label, f'@{field_name}'),
                        ],
                    )
                )

        p.xaxis.axis_label = x_label
        p.yaxis.axis_label = y_label
        p.xaxis.major_label_orientation = 1.0
        p.xgrid.grid_line_color = None
        p.y_range.start = 0
        show(p)
        return p

    raise ValueError(f"Unsupported plotting backend: {backend}. Use 'plt' or 'bokeh'.")


# Basic pitch maps
_NOTE_TO_PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
_PC_TO_NOTE = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
_LETTER_TO_INDEX = {'C': 0, 'D': 1, 'E': 2, 'F': 3, 'G': 4, 'A': 5, 'B': 6}

# Accidentals rank for enharmonic ordering (supports triple)
_ACC_RANK_MAP = {'bbb': 0, 'bb': 1, 'b': 2, '': 3, '#': 4, '##': 5, '###': 6}


def midi_to_name(midi_value: Optional[int]) -> Optional[str]:
    try:
        mv = int(midi_value)
    except Exception:
        return None
    if mv < 0 or mv > 127:
        return None
    pc = mv % 12
    octave = mv // 12 - 1
    return f"{_PC_TO_NOTE[pc]}{octave}"


def _normalize_accidental_string(acc_raw: str) -> str:
    if not acc_raw:
        return ''
    # Sum semitone shifts, support triple accidentals and glyphs
    shift = 0
    for ch in acc_raw:
        if ch in ['#', '♯']:
            shift += 1
        elif ch in ['b', '♭']:
            shift -= 1
        elif ch in ['x', '𝄪']:
            shift += 2
        elif ch in ['𝄫']:
            shift -= 2
        elif ch in ['♮']:
            shift = 0
        else:
            continue
    # Clamp to triple range
    if shift > 3:
        shift = 3
    if shift < -3:
        shift = -3
    if shift > 0:
        return '#' * shift
    if shift < 0:
        return 'b' * (-shift)
    return ''


def _accidental_to_semitones(acc: str) -> int:
    if not acc:
        return 0
    if set(acc) == {'#'}:
        return min(3, len(acc))
    if set(acc) == {'b'}:
        return -min(3, len(acc))
    return 0


def parse_pitch_name(name: Optional[str]) -> Tuple[Optional[str], str, Optional[int]]:
    if not isinstance(name, str) or len(name) == 0:
        return (None, '', None)
    s = name.strip()
    if not s:
        return (None, '', None)
    letter = s[0].upper()
    if letter not in _LETTER_TO_INDEX:
        return (None, '', None)
    idx = 1
    acc_raw = ''
    while idx < len(s) and s[idx] in ['#', 'b', 'x', '♯', '♭', '𝄪', '𝄫', '♮']:
        acc_raw += s[idx]
        idx += 1
    acc = _normalize_accidental_string(acc_raw)
    octave = None
    if idx < len(s):
        try:
            octave = int(s[idx:])
        except Exception:
            octave = None
    return (letter, acc, octave)


def name_to_midi(name: Optional[str]) -> Optional[int]:
    letter, acc, octave = parse_pitch_name(name)
    if letter is None or octave is None:
        return None
    midi_base = (octave + 1) * 12 + _NOTE_TO_PC[letter]
    m = midi_base + _accidental_to_semitones(acc)
    return m if 0 <= m <= 127 else None


def _display_series_from_axis(df: pd.DataFrame, axis_option: str) -> Tuple[pd.Series, str]:
    axis = str(axis_option).strip().lower()
    have_midi = 'MIDI' in df.columns
    have_pitch = 'Pitch' in df.columns
    have_pitch_enh = 'Pitch Enharmonic' in df.columns

    if axis == 'midi':
        if have_midi:
            return df['MIDI'], 'MIDI'
        if have_pitch:
            return df['Pitch'].map(name_to_midi), 'MIDI'
        if have_pitch_enh:
            return df['Pitch Enharmonic'].map(name_to_midi), 'MIDI'
    elif axis in ['pitch real', 'pitch', 'real']:
        if have_pitch:
            return df['Pitch'], 'Pitch'
        if have_midi:
            return df['MIDI'].map(midi_to_name), 'Pitch'
    elif axis in ['pitch enharmonic', 'enharmonic', 'pitch_enharmonic', 'pitch-enharmonic', 'pitch by name', 'pitch name', 'name']:
        if have_pitch_enh:
            return df['Pitch Enharmonic'], 'Pitch Enharmonic'
        if have_pitch:
            return df['Pitch'], 'Pitch'
        if have_midi:
            return df['MIDI'].map(midi_to_name), 'Pitch'

    # Fallbacks
    if have_midi:
        return df['MIDI'], 'MIDI'
    if have_pitch:
        return df['Pitch'], 'Pitch'
    if have_pitch_enh:
        return df['Pitch Enharmonic'], 'Pitch Enharmonic'
    raise ValueError("No pitch-related columns found. Expected 'MIDI' and/or 'Pitch' and/or 'Pitch Enharmonic'.")


def build_pitch_counts(df: pd.DataFrame, axis_option: str) -> Tuple[pd.DataFrame, str]:
    series, display_col = _display_series_from_axis(df, axis_option)
    counts_df = (
        pd.DataFrame({display_col: series})
        .groupby(display_col, dropna=False)
        .size()
        .rename('count')
        .reset_index()
    )
    return counts_df, display_col


def _to_midi_for_sort(display_col: str, val) -> Optional[int]:
    if display_col == 'MIDI':
        try:
            return int(val)
        except Exception:
            return None
    return name_to_midi(val)


def sort_pitch_counts(counts_df: pd.DataFrame, display_col: str, order_option: str) -> pd.DataFrame:
    order_opt = str(order_option).strip().lower().replace('-', ' ').replace('_', ' ')

    def pc_of(v):
        m = _to_midi_for_sort(display_col, v)
        return None if m is None else int(m) % 12

    def oct_of(v):
        m = _to_midi_for_sort(display_col, v)
        return None if m is None else int(m) // 12 - 1

    def letter_index_of(v):
        # Parse name from MIDI if necessary
        nm = midi_to_name(v) if display_col == 'MIDI' else (str(v) if isinstance(v, str) else None)
        letter, _, _ = parse_pitch_name(nm) if nm is not None else (None, '', None)
        return _LETTER_TO_INDEX.get(letter, None)

    def acc_rank_of(v):
        nm = midi_to_name(v) if display_col == 'MIDI' else (str(v) if isinstance(v, str) else None)
        _, acc, _ = parse_pitch_name(nm) if nm is not None else (None, '', None)
        return _ACC_RANK_MAP.get(acc, 3)

    def enh_octave_of(v):
        # Use the written octave in the name, ignoring semitone shifts from accidentals
        nm = midi_to_name(v) if display_col == 'MIDI' else (str(v) if isinstance(v, str) else None)
        _, _, octv = parse_pitch_name(nm) if nm is not None else (None, '', None)
        return octv

    # Work on a copy so we don't mutate caller data unexpectedly
    df = counts_df.copy()

    if order_opt in ['midi', 'pitch real', 'pitch', 'real']:
        df['sort_midi'] = df[display_col].map(lambda v: _to_midi_for_sort(display_col, v))
        df = df.sort_values(['sort_midi', display_col], na_position='last', kind='mergesort')
    elif order_opt in ['pitch by octave', 'pitch octave', 'octave pitch', 'pitch by octave real', 'octave real']:
        df['sort_oct'] = df[display_col].map(oct_of)
        df['sort_pc'] = df[display_col].map(pc_of)
        df = df.sort_values(['sort_oct', 'sort_pc', display_col], na_position='last', kind='mergesort')
    elif order_opt in ['pitch by octave enharmonic', 'octave enharmonic', 'octave name']:
        df['sort_oct_enh'] = df[display_col].map(enh_octave_of)
        df['sort_letter'] = df[display_col].map(letter_index_of)
        df['sort_acc'] = df[display_col].map(acc_rank_of)
        df = df.sort_values(['sort_oct_enh', 'sort_letter', 'sort_acc', display_col], na_position='last', kind='mergesort')
    elif order_opt in ['pitch by name', 'pitch enharmonic', 'enharmonic', 'enharmonic pitch', 'pitch enharmonic']:
        df['sort_letter'] = df[display_col].map(letter_index_of)
        df['sort_acc'] = df[display_col].map(acc_rank_of)
        df = df.sort_values(['sort_letter', 'sort_acc', display_col], na_position='last', kind='mergesort')
    else:
        # Default to MIDI order
        df['sort_midi'] = df[display_col].map(lambda v: _to_midi_for_sort(display_col, v))
        df = df.sort_values(['sort_midi', display_col], na_position='last', kind='mergesort')

    # Remove helper columns from the final DataFrame that is returned to callers.
    # User request: hide 'sort_letter' and 'sort_acc' from the final df.
    df = df.drop(columns=['sort_letter', 'sort_acc'], errors='ignore')
    return df


def plot_pitch_distribution(
    counts_df: pd.DataFrame,
    display_col: str,
    backend: str = 'bokeh',
    plot_width: int = 900,
    plot_height: int = 350,
    show_hover: bool = True,
    bar_color: str = '#4682B4',
):
    backend_opt = (backend or 'plt').strip().lower()
    x_labels = counts_df[display_col].astype(str).tolist()
    y_values = counts_df['count'].tolist()

    if backend_opt == 'plt':
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(plot_width / 100.0, plot_height / 100.0))
        ax.bar(x_labels, y_values, color=bar_color)
        ax.set_xlabel(display_col)
        ax.set_ylabel('Count')
        ax.set_title('Pitch Distribution')
        plt.xticks(rotation=90)
        plt.tight_layout()
        plt.show()
        return None

    if backend_opt == 'bokeh':
        from bokeh.plotting import figure, show
        from bokeh.io import output_notebook
        from bokeh.models import ColumnDataSource, HoverTool

        output_notebook()
        source = ColumnDataSource(dict(x=x_labels, count=y_values))
        p = figure(
            x_range=x_labels,
            height=plot_height,
            width=plot_width,
            title='Pitch Distribution',
            toolbar_location='right',
        )
        p.vbar(x='x', top='count', width=0.9, source=source, fill_color=bar_color)
        if show_hover:
            p.add_tools(HoverTool(tooltips=[("Pitch", "@x"), ("Count", "@count")]))
        p.xaxis.axis_label = display_col
        p.yaxis.axis_label = 'Count'
        p.xgrid.grid_line_color = None
        p.y_range.start = 0
        show(p)
        return p

    raise ValueError(f"Unsupported plotting backend: {backend}. Use 'plt' or 'bokeh'.")


def display_pitch_distribution(
    source_df: pd.DataFrame,
    *more_source_dfs: pd.DataFrame,
    pitch_axis: str,
    order_axis_by: str,
    backend: str = 'plt',
    plot_width: int = 900,
    plot_height: int = 350,
    show_hover: bool = True,
    show_table: bool = True,
    bar_color: Union[str, Sequence[str]] = '#4682B4',
    source_labels: Optional[Sequence[str]] = None,
) -> Union[pd.DataFrame, Mapping[str, pd.DataFrame]]:
    """
    Build and display a pitch distribution table and plot from a DataFrame.

    Parameters
    ----------
    source_df : pandas.DataFrame
        Input DataFrame containing at least one of: 'MIDI', 'Pitch', 'Pitch Enharmonic'.
    pitch_axis : str
        Which pitch representation to use on X axis (e.g., 'midi', 'pitch real', 'pitch enharmonic').
    order_axis_by : str
        How to order the X axis (e.g., 'midi', 'pitch by octave', 'pitch enharmonic').
    backend : {'plt', 'bokeh'}
        Plotting backend.
    plot_width : int
        Plot width in pixels.
    plot_height : int
        Plot height in pixels.
    show_hover : bool
        Enable hover tooltips (Bokeh only).
    show_table : bool
        Whether to display the counts table.

    Returns
    -------
    pandas.DataFrame
        - Single-source call: the sorted counts DataFrame with columns
          [display_col, 'count'] (plus sort helper columns).
        - Multi-source call: a dict mapping source label -> corresponding
          counts DataFrame.
    """
    # Allow either multiple positional DataFrames or a single tuple/list of
    # DataFrames passed as the first argument (e.g. source = (df1, df2)).
    if not more_source_dfs and not isinstance(source_df, pd.DataFrame):
        if isinstance(source_df, (list, tuple)):
            dfs = list(source_df)
        else:
            dfs = [source_df]
    else:
        dfs = [source_df] + list(more_source_dfs)

    # --------------------------
    # Single-source (backwards-compatible)
    # --------------------------
    if len(dfs) == 1:
        counts_df, display_col = build_pitch_counts(dfs[0], pitch_axis)
        counts_df = sort_pitch_counts(counts_df, display_col, order_axis_by)

        if show_table:
            try:
                ipy_display(counts_df[[display_col, 'count']].set_index(display_col))
            except Exception:
                print(counts_df[[display_col, 'count']].set_index(display_col))

        # If bar_color is a list in single-source mode, just use the first color.
        if not isinstance(bar_color, str):
            try:
                bar_color_single = str(list(bar_color)[0])  # type: ignore[arg-type]
            except Exception:
                bar_color_single = '#4682B4'
        else:
            bar_color_single = bar_color

        plot_pitch_distribution(
            counts_df,
            display_col,
            backend=(backend.lower() if isinstance(backend, str) else 'plt'),
            plot_width=plot_width,
            plot_height=plot_height,
            show_hover=bool(show_hover),
            bar_color=bar_color_single,
        )
        return counts_df

    # --------------------------
    # Multi-source: build per-source tables and combined bar plot
    # --------------------------
    n_sources = len(dfs)
    if source_labels is not None:
        labels = list(source_labels)[:n_sources]
        if len(labels) < n_sources:
            labels.extend(_guess_labels_for_dfs(dfs[len(labels):], default_prefix="Source"))
    else:
        labels = _guess_labels_for_dfs(dfs, default_prefix="Source")

    per_source_counts: dict[str, pd.DataFrame] = {}
    display_col: Optional[str] = None

    for idx, (df, label) in enumerate(zip(dfs, labels)):
        counts_df_i, display_col_i = build_pitch_counts(df, pitch_axis)
        if display_col is None:
            display_col = display_col_i
        elif display_col_i != display_col:
            counts_df_i = counts_df_i.rename(columns={display_col_i: display_col})
        counts_df_i = sort_pitch_counts(counts_df_i, display_col, order_axis_by)
        per_source_counts[label] = counts_df_i

        if show_table:
            print(f"=== Pitch Distribution ({label}) ===")
            try:
                ipy_display(counts_df_i[[display_col, 'count']].set_index(display_col))
            except Exception:
                print(counts_df_i[[display_col, 'count']].set_index(display_col))

    if display_col is None:
        return {}

    # Union of categories across all sources, ordered according to order_axis_by
    all_vals = pd.concat(
        [df_i[display_col] for df_i in per_source_counts.values()],
        ignore_index=True,
    ).drop_duplicates()
    tmp = pd.DataFrame({display_col: all_vals, 'count': [0] * len(all_vals)})
    tmp_sorted = sort_pitch_counts(tmp, display_col, order_axis_by)
    categories = tmp_sorted[display_col].tolist()

    series_values: list[list[float]] = []
    for label in labels:
        df_i = per_source_counts[label].set_index(display_col)['count']
        series_values.append([float(df_i.get(cat, 0.0)) for cat in categories])

    _plot_multi_bar(
        categories=categories,
        series_values=series_values,
        series_labels=labels,
        title='Pitch Distribution',
        x_label=display_col,
        y_label='Count',
        backend=(backend.lower() if isinstance(backend, str) else 'plt'),
        plot_width=plot_width,
        plot_height=plot_height,
        show_hover=bool(show_hover),
        bar_color=bar_color,
        default_palette=_DEFAULT_PITCH_PALETTE,
    )

    return per_source_counts


def _get_pitch_class_from_name(val: Any) -> Optional[str]:
    """
    Helper: collapse a pitch name like 'C#4' to a pitch class string 'C#'.
    """
    if val is None:
        return None
    letter, acc, _ = parse_pitch_name(str(val))
    return f"{letter}{acc}" if letter else None


def build_pc_counts_from_names(
    name_series: pd.Series,
    pc_label: str,
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Build a pitch-class counts table (C, C#, D, ...) from a series of pitch names.

    Parameters
    ----------
    name_series : pandas.Series
        Series of pitch names (e.g., 'Pitch', 'Pitch Enharmonic', or derived from MIDI).
    pc_label : str
        Column label for the resulting pitch-class category column.

    Returns
    -------
    (counts_df, label) : (pandas.DataFrame or None, str or None)
        When successful, `counts_df` has columns [pc_label, 'count'] and is ordered
        chromatically using 'pitch by name'. When the input series yields no valid
        pitch classes, both elements are None.
    """
    pc_series = name_series.dropna().map(_get_pitch_class_from_name).dropna()
    if pc_series.empty:
        return None, None

    counts_pc = pc_series.value_counts().rename('count').reset_index()
    counts_pc.columns = [pc_label, 'count']
    counts_pc = sort_pitch_counts(counts_pc, pc_label, 'pitch by name')
    return counts_pc, pc_label


def build_pitch_class_distributions(
    source_df: pd.DataFrame,
) -> Tuple[
    Optional[pd.DataFrame],
    Optional[pd.DataFrame],
    Optional[str],
    Optional[str],
]:
    """
    Compute pitch-class distributions for both real and enharmonic spellings,
    when possible, from a notes DataFrame.

    The function looks for:
    - 'Pitch' (real names) and/or 'MIDI' to build a real pitch-class histogram.
    - 'Pitch Enharmonic' to build a written/enharmonic pitch-class histogram.

    Returns
    -------
    counts_real, counts_enh, label_real, label_enh :
        - counts_real : DataFrame or None
        - counts_enh : DataFrame or None
        - label_real : str or None (column name for real pitch classes)
        - label_enh : str or None (column name for enharmonic pitch classes)
    """
    counts_real: Optional[pd.DataFrame] = None
    label_real: Optional[str] = None
    counts_enh: Optional[pd.DataFrame] = None
    label_enh: Optional[str] = None

    # Real pitch classes (collapse by sounding pitch)
    if 'Pitch' in source_df.columns:
        counts_real, label_real = build_pc_counts_from_names(
            source_df['Pitch'],
            'Pitch Class (Real)',
        )
    elif 'MIDI' in source_df.columns:
        real_names = source_df['MIDI'].dropna().map(midi_to_name)
        counts_real, label_real = build_pc_counts_from_names(
            real_names,
            'Pitch Class (Real from MIDI)',
        )

    # Enharmonic / written pitch classes (collapse by notation spelling)
    if 'Pitch Enharmonic' in source_df.columns:
        counts_enh, label_enh = build_pc_counts_from_names(
            source_df['Pitch Enharmonic'],
            'Pitch Class (Enharmonic)',
        )

    return counts_real, counts_enh, label_real, label_enh


def display_pitch_class_distributions(
    source_df: pd.DataFrame,
    *more_source_dfs: pd.DataFrame,
    backend: str = 'bokeh',
    plot_width: int = 1200,
    plot_height: int = 450,
    show_hover: bool = True,
    show_table: bool = True,
    bar_color: Union[str, Sequence[str]] = '#4682B4',
    source_labels: Optional[Sequence[str]] = None,
) -> Mapping[str, Any]:
    """
    Build and display pitch-class distributions (real + enharmonic) from a notes DataFrame.

    Parameters
    ----------
    source_df : pandas.DataFrame
        Notes DataFrame with at least one of: 'MIDI', 'Pitch', 'Pitch Enharmonic'.
    backend : {'plt', 'bokeh'}
        Plotting backend for the bar charts.
    plot_width, plot_height : int
        Plot dimensions in pixels.
    show_hover : bool
        Enable hover tooltips (Bokeh backend only).
    show_table : bool
        Whether to display the counts tables.

    Returns
    -------
    dict
        - Single-source:
            {
                'real': DataFrame or None,
                'enharmonic': DataFrame or None,
                'label_real': str or None,
                'label_enh': str or None,
            }
        - Multi-source:
            {
                'real': {label: DataFrame, ...} or {},
                'enharmonic': {label: DataFrame, ...} or {},
                'label_real': str or None,
                'label_enh': str or None,
            }
    """
    # Allow either multiple positional DataFrames or a single tuple/list of
    # DataFrames passed as the first argument.
    if not more_source_dfs and not isinstance(source_df, pd.DataFrame):
        if isinstance(source_df, (list, tuple)):
            dfs = list(source_df)
        else:
            dfs = [source_df]
    else:
        dfs = [source_df] + list(more_source_dfs)

    # --------------------------
    # Single-source (backwards-compatible)
    # --------------------------
    if len(dfs) == 1:
        counts_real, counts_enh, label_real, label_enh = build_pitch_class_distributions(dfs[0])

        any_done = False

        if counts_real is not None and label_real is not None:
            any_done = True
            print("=== Pitch Class Distribution (Real) ===")
            if show_table:
                try:
                    ipy_display(counts_real.set_index(label_real).T)
                except Exception:
                    print(counts_real.set_index(label_real).T)

            if not isinstance(bar_color, str):
                try:
                    bar_color_single = str(list(bar_color)[0])  # type: ignore[arg-type]
                except Exception:
                    bar_color_single = '#4682B4'
            else:
                bar_color_single = bar_color

            plot_pitch_distribution(
                counts_real,
                label_real,
                backend=backend,
                plot_width=plot_width,
                plot_height=plot_height,
                show_hover=show_hover,
                bar_color=bar_color_single,
            )

        if counts_enh is not None and label_enh is not None:
            any_done = True
            print("=== Pitch Class Distribution (Enharmonic / Written) ===")
            if show_table:
                try:
                    ipy_display(counts_enh.set_index(label_enh).T)
                except Exception:
                    print(counts_enh.set_index(label_enh).T)

            if not isinstance(bar_color, str):
                try:
                    bar_color_single = str(list(bar_color)[0])  # type: ignore[arg-type]
                except Exception:
                    bar_color_single = '#4682B4'
            else:
                bar_color_single = bar_color

            plot_pitch_distribution(
                counts_enh,
                label_enh,
                backend=backend,
                plot_width=plot_width,
                plot_height=plot_height,
                show_hover=show_hover,
                bar_color=bar_color_single,
            )

        if not any_done:
            print("No suitable pitch columns found (MIDI, Pitch, or Pitch Enharmonic) to extract pitch classes.")

        return {
            'real': counts_real,
            'enharmonic': counts_enh,
            'label_real': label_real,
            'label_enh': label_enh,
        }

    # --------------------------
    # Multi-source: group plots per distribution type (real / enharmonic)
    # --------------------------
    n_sources = len(dfs)
    if source_labels is not None:
        labels = list(source_labels)[:n_sources]
        if len(labels) < n_sources:
            labels.extend(_guess_labels_for_dfs(dfs[len(labels):], default_prefix="Source"))
    else:
        labels = _guess_labels_for_dfs(dfs, default_prefix="Source")

    real_counts_by_label: dict[str, pd.DataFrame] = {}
    enh_counts_by_label: dict[str, pd.DataFrame] = {}
    label_real_main: Optional[str] = None
    label_enh_main: Optional[str] = None

    for df, lbl in zip(dfs, labels):
        counts_real, counts_enh, label_real, label_enh = build_pitch_class_distributions(df)

        # Real
        if counts_real is not None and label_real is not None:
            if label_real_main is None:
                label_real_main = label_real
            if label_real != label_real_main:
                counts_real = counts_real.rename(columns={label_real: label_real_main})
            real_counts_by_label[lbl] = counts_real

        # Enharmonic
        if counts_enh is not None and label_enh is not None:
            if label_enh_main is None:
                label_enh_main = label_enh
            if label_enh != label_enh_main:
                counts_enh = counts_enh.rename(columns={label_enh: label_enh_main})
            enh_counts_by_label[lbl] = counts_enh

    # Combined bar plots
    backend_opt = (backend.lower() if isinstance(backend, str) else 'plt')

    # Real pitch-class tables + combined plot
    if label_real_main is not None and real_counts_by_label:
        if show_table:
            for lbl in labels:
                if lbl not in real_counts_by_label:
                    continue
                print(f"=== Pitch Class Distribution (Real) — {lbl} ===")
                try:
                    ipy_display(real_counts_by_label[lbl].set_index(label_real_main).T)
                except Exception:
                    print(real_counts_by_label[lbl].set_index(label_real_main).T)

        all_vals_real = pd.concat(
            [df[label_real_main] for df in real_counts_by_label.values()],
            ignore_index=True,
        ).drop_duplicates()
        tmp_real = pd.DataFrame({label_real_main: all_vals_real, 'count': [0] * len(all_vals_real)})
        tmp_real_sorted = sort_pitch_counts(tmp_real, label_real_main, 'pitch by name')
        categories_real = tmp_real_sorted[label_real_main].tolist()

        series_values_real: list[list[float]] = []
        for lbl in labels:
            if lbl not in real_counts_by_label:
                # series of zeros if this df had no real counts
                series_values_real.append([0.0 for _ in categories_real])
                continue
            df_i = real_counts_by_label[lbl].set_index(label_real_main)['count']
            series_values_real.append([float(df_i.get(cat, 0.0)) for cat in categories_real])

        _plot_multi_bar(
            categories=categories_real,
            series_values=series_values_real,
            series_labels=labels,
            title='Pitch Class Distribution (Real)',
            x_label=label_real_main,
            y_label='Count',
            backend=backend_opt,
            plot_width=plot_width,
            plot_height=plot_height,
            show_hover=bool(show_hover),
            bar_color=bar_color,
            default_palette=_DEFAULT_PITCH_PALETTE,
        )

    # Enharmonic pitch-class tables + combined plot
    if label_enh_main is not None and enh_counts_by_label:
        if show_table:
            for lbl in labels:
                if lbl not in enh_counts_by_label:
                    continue
                print(f"=== Pitch Class Distribution (Enharmonic / Written) — {lbl} ===")
                try:
                    ipy_display(enh_counts_by_label[lbl].set_index(label_enh_main).T)
                except Exception:
                    print(enh_counts_by_label[lbl].set_index(label_enh_main).T)

        all_vals_enh = pd.concat(
            [df[label_enh_main] for df in enh_counts_by_label.values()],
            ignore_index=True,
        ).drop_duplicates()
        tmp_enh = pd.DataFrame({label_enh_main: all_vals_enh, 'count': [0] * len(all_vals_enh)})
        tmp_enh_sorted = sort_pitch_counts(tmp_enh, label_enh_main, 'pitch by name')
        categories_enh = tmp_enh_sorted[label_enh_main].tolist()

        series_values_enh: list[list[float]] = []
        for lbl in labels:
            if lbl not in enh_counts_by_label:
                series_values_enh.append([0.0 for _ in categories_enh])
                continue
            df_i = enh_counts_by_label[lbl].set_index(label_enh_main)['count']
            series_values_enh.append([float(df_i.get(cat, 0.0)) for cat in categories_enh])

        _plot_multi_bar(
            categories=categories_enh,
            series_values=series_values_enh,
            series_labels=labels,
            title='Pitch Class Distribution (Enharmonic / Written)',
            x_label=label_enh_main,
            y_label='Count',
            backend=backend_opt,
            plot_width=plot_width,
            plot_height=plot_height,
            show_hover=bool(show_hover),
            bar_color=bar_color,
            default_palette=_DEFAULT_PITCH_PALETTE,
        )

    if not real_counts_by_label and not enh_counts_by_label:
        print("No suitable pitch columns found (MIDI, Pitch, or Pitch Enharmonic) to extract pitch classes.")

    return {
        'real': real_counts_by_label,
        'enharmonic': enh_counts_by_label,
        'label_real': label_real_main,
        'label_enh': label_enh_main,
    }


def build_duration_counts(
    df: pd.DataFrame,
    drop_zero: bool = True,
    round_decimals: Optional[int] = 4
) -> Tuple[pd.DataFrame, str]:
    # Detect duration column
    duration_col = None
    for candidate in ['Duration', 'duration', 'durations', 'Durations']:
        if candidate in df.columns:
            duration_col = candidate
            break
    
    if duration_col is None:
        raise ValueError("No duration column found. Checked: 'Duration', 'duration', 'durations', 'Durations'.")

    ser = df[duration_col].copy()
    # Coerce to numeric where possible
    ser = pd.to_numeric(ser, errors='coerce')
    ser = ser.dropna()
    
    if drop_zero:
        ser = ser[ser != 0]
    
    if round_decimals is not None:
        ser = ser.round(round_decimals)

    # Aggregate and sort by numeric value (ascending)
    counts = ser.value_counts().sort_index()
    
    counts_df = counts.rename('count').reset_index()
    # Ensure columns are named correctly (reset_index names the index column as 'index' if name is None)
    counts_df.columns = [duration_col, 'count']
    
    return counts_df, duration_col


def plot_duration_distribution(
    counts_df: pd.DataFrame,
    display_col: str,
    backend: str = 'bokeh',
    plot_width: int = 900,
    plot_height: int = 350,
    show_hover: bool = True,
    bar_color: str = '#2E8B57',
):
    backend_opt = (backend or 'plt').strip().lower()
    x_labels = counts_df[display_col].astype(str).tolist()
    y_values = counts_df['count'].tolist()

    if backend_opt == 'plt':
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(plot_width / 100.0, plot_height / 100.0))
        ax.bar(x_labels, y_values, color=bar_color)
        ax.set_xlabel(display_col)
        ax.set_ylabel('Count')
        ax.set_title('Duration Distribution')
        plt.xticks(rotation=90)
        plt.tight_layout()
        plt.show()
        return None

    if backend_opt == 'bokeh':
        from bokeh.plotting import figure, show
        from bokeh.io import output_notebook
        from bokeh.models import ColumnDataSource, HoverTool
        output_notebook()
        
        source = ColumnDataSource(dict(x=x_labels, count=y_values))
        p = figure(
            x_range=x_labels,
            height=plot_height,
            width=plot_width,
            title='Duration Distribution',
            toolbar_location='right',
        )
        p.vbar(x='x', top='count', width=0.9, source=source, fill_color=bar_color)
        if show_hover:
             p.add_tools(HoverTool(tooltips=[("Duration", "@x"), ("Count", "@count")]))
        
        p.xaxis.axis_label = display_col
        p.yaxis.axis_label = 'Count'
        p.xgrid.grid_line_color = None
        p.y_range.start = 0
        show(p)
        return p

    raise ValueError(f"Unsupported plotting backend: {backend}. Use 'plt' or 'bokeh'.")


def display_duration_distribution(
    source_df: pd.DataFrame,
    *more_source_dfs: pd.DataFrame,
    drop_zero: bool = True,
    round_decimals: Optional[int] = 4,
    backend: str = 'plt',
    plot_width: int = 900,
    plot_height: int = 350,
    show_hover: bool = True,
    show_table: bool = True,
    bar_color: Union[str, Sequence[str]] = '#2E8B57',
    source_labels: Optional[Sequence[str]] = None,
) -> Union[pd.DataFrame, Mapping[str, pd.DataFrame]]:
    """
    Build and display a duration distribution table and plot from a DataFrame.

    Parameters
    ----------
    source_df : pandas.DataFrame
        Input DataFrame containing 'Duration' or similar column.
    drop_zero : bool
        Whether to exclude 0.0 durations.
    round_decimals : int or None
        Number of decimals to round durations to.
    backend : {'plt', 'bokeh'}
        Plotting backend.
    plot_width : int
        Plot width in pixels.
    plot_height : int
        Plot height in pixels.
    show_hover : bool
        Enable hover tooltips (Bokeh only).
    show_table : bool
        Whether to display the counts table.

    Returns
    -------
    pandas.DataFrame
        - Single-source call: the sorted counts DataFrame.
        - Multi-source call: a dict mapping source label -> corresponding
          counts DataFrame.
    """
    # Allow either multiple positional DataFrames or a single tuple/list of
    # DataFrames passed as the first argument.
    if not more_source_dfs and not isinstance(source_df, pd.DataFrame):
        if isinstance(source_df, (list, tuple)):
            dfs = list(source_df)
        else:
            dfs = [source_df]
    else:
        dfs = [source_df] + list(more_source_dfs)

    # --------------------------
    # Single-source (backwards-compatible)
    # --------------------------
    if len(dfs) == 1:
        counts_df, display_col = build_duration_counts(dfs[0], drop_zero, round_decimals)

        if show_table:
            try:
                ipy_display(counts_df[[display_col, 'count']].set_index(display_col))
            except Exception:
                print(counts_df[[display_col, 'count']].set_index(display_col))

        if not isinstance(bar_color, str):
            try:
                bar_color_single = str(list(bar_color)[0])  # type: ignore[arg-type]
            except Exception:
                bar_color_single = '#2E8B57'
        else:
            bar_color_single = bar_color

        plot_duration_distribution(
            counts_df,
            display_col,
            backend=(backend.lower() if isinstance(backend, str) else 'plt'),
            plot_width=plot_width,
            plot_height=plot_height,
            show_hover=bool(show_hover),
            bar_color=bar_color_single,
        )

        return counts_df

    # --------------------------
    # Multi-source: build per-source tables and combined bar plot
    # --------------------------
    n_sources = len(dfs)
    if source_labels is not None:
        labels = list(source_labels)[:n_sources]
        if len(labels) < n_sources:
            labels.extend(_guess_labels_for_dfs(dfs[len(labels):], default_prefix="Source"))
    else:
        labels = _guess_labels_for_dfs(dfs, default_prefix="Source")

    per_source_counts: dict[str, pd.DataFrame] = {}
    display_col: Optional[str] = None

    for df, label in zip(dfs, labels):
        counts_df_i, display_col_i = build_duration_counts(df, drop_zero, round_decimals)
        if display_col is None:
            display_col = display_col_i
        elif display_col_i != display_col:
            counts_df_i = counts_df_i.rename(columns={display_col_i: display_col})
        per_source_counts[label] = counts_df_i

        if show_table:
            print(f"=== Duration Distribution ({label}) ===")
            try:
                ipy_display(counts_df_i[[display_col, 'count']].set_index(display_col))
            except Exception:
                print(counts_df_i[[display_col, 'count']].set_index(display_col))

    if display_col is None:
        return {}

    # Union of duration values across all sources, sorted numerically
    all_vals = pd.concat(
        [df_i[display_col] for df_i in per_source_counts.values()],
        ignore_index=True,
    ).drop_duplicates()
    try:
        categories = sorted(all_vals.tolist())
    except Exception:
        categories = [v for v in all_vals.tolist()]

    series_values: list[list[float]] = []
    for label in labels:
        df_i = per_source_counts[label].set_index(display_col)['count']
        series_values.append([float(df_i.get(cat, 0.0)) for cat in categories])

    _plot_multi_bar(
        categories=categories,
        series_values=series_values,
        series_labels=labels,
        title='Duration Distribution',
        x_label=display_col,
        y_label='Count',
        backend=(backend.lower() if isinstance(backend, str) else 'plt'),
        plot_width=plot_width,
        plot_height=plot_height,
        show_hover=bool(show_hover),
        bar_color=bar_color,
        default_palette=_DEFAULT_DURATION_PALETTE,
    )

    return per_source_counts


def extract_selected_xml_ids(selection: Optional[pd.DataFrame]) -> list[str]:
    """
    Given an optional selection DataFrame, return a list of MEI xml IDs
    formatted with a leading '#', e.g. ['#note-123', '#note-456'].

    This is a small convenience wrapper to keep notebook cells simple.
    """
    if selection is None or selection.empty:
        return []
    if 'xml_id' not in selection.columns:
        return []
    return ['#' + str(x) for x in selection['xml_id'].dropna().tolist()]


# --------------------------------------------------------------------
# Note selection + piano-roll helper (for interactive notebook usage)
# --------------------------------------------------------------------

def _parse_pitch_bound_for_filter(val):
    """
    Convert a single bound (name, MIDI number, or numeric string) to MIDI int or None.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip()
    if not s:
        return None
    # Try numeric first
    try:
        return int(float(s))
    except Exception:
        pass
    # Fallback to pitch name like "g3"
    try:
        return name_to_midi(s)
    except Exception:
        return None


def _parse_pitch_range_for_filter(spec):
    """
    Accept tuple/list of 2 values or a string like "g3-g5" / "60-72"; return (lo, hi) in MIDI or None.
    """
    if not spec:
        return None
    # Tuple/list form
    if isinstance(spec, (tuple, list)) and len(spec) == 2:
        lo = _parse_pitch_bound_for_filter(spec[0])
        hi = _parse_pitch_bound_for_filter(spec[1])
        return (lo, hi) if (lo is not None and hi is not None) else None
    # String form: "low-high"
    if isinstance(spec, str):
        parts = spec.split("-")
        if len(parts) == 2:
            lo = _parse_pitch_bound_for_filter(parts[0])
            hi = _parse_pitch_bound_for_filter(parts[1])
            return (lo, hi) if (lo is not None and hi is not None) else None
    return None


def display_filtered_piano_roll(
    source_df: pd.DataFrame,
    *,
    measure_range: Optional[Tuple[int, int]] = None,
    onset_range: Optional[Tuple[float, float]] = None,
    voice_query: Optional[Union[str, Sequence[str]]] = None,
    pitch_range: Optional[Union[str, Sequence[Any]]] = None,
    results: Optional[Sequence[Mapping[str, Any]]] = None,
    measure_offsets: Optional[Sequence[float]] = None,
    plotting_backend: str = 'plt',
    plot_width: Optional[int] = None,
    plot_height: Optional[int] = None,
    zoom_drag_dim: Optional[str] = None,
    zoom_wheel_dim: Optional[str] = None,
    show_measure_lines: bool = True,
    # DataFrame display controls
    display_selection: bool = True,
    display_mode: str = 'head',  # 'head', 'all', 'none'
    display_max_rows: int = 10,
) -> pd.DataFrame:
    """
    Filter a notes DataFrame and display both the selection and a piano-roll plot.

    Parameters
    ----------
    source_df : pandas.DataFrame
        Notes DataFrame containing at least: 'Global Onset', 'Duration', and usually 'MIDI', 'Measure', 'Voice'.
    measure_range : (int, int), optional
        Inclusive measure range (start, end). When None, do not filter by measure.
    onset_range : (float, float), optional
        Exclusive-at-end global onset range [start, end). When None, do not filter by onset.
    voice_query : str or sequence of str, optional
        - If list/tuple: matched via exact `isin` on the 'Voice' column.
        - If str: interpreted as a regex pattern for `str.contains`.
    pitch_range : tuple/list or "low-high" string, optional
        Pitch range filter in MIDI or names, e.g. (60, 72) or "g3-g5".
    results : sequence of dict, optional
        Optional `results` structure returned by the parsing helpers; used to pick
        pre-computed measure offsets matching `source_df`.
    measure_offsets : sequence of float, optional
        Explicit measure offsets. When provided, this overrides lookup via `results`
        or automatic grouping by 'Measure'.
    plotting_backend : {'plt', 'bokeh'}
        Backend for `draw_piano_roll`.
    plot_width, plot_height : int, optional
        Plot dimensions passed through to `draw_piano_roll`.
    zoom_drag_dim, zoom_wheel_dim : {"width", "height", "both"}, optional
        Zoom configuration forwarded to `draw_piano_roll` (Bokeh backend).
    show_measure_lines : bool
        Whether to show vertical measure guide lines when offsets are available.
    display_selection : bool
        If True, display the filtered selection DataFrame.
    display_mode : {'head', 'all', 'none'}
        - 'head': display up to `display_max_rows` rows (default).
        - 'all': display the entire selection.
        - 'none': skip DataFrame display (plot only).
    display_max_rows : int
        Maximum number of rows to display in 'head' mode.

    Returns
    -------
    pandas.DataFrame
        The filtered selection DataFrame (may be empty).
    """
    selection = source_df.copy()

    # 1. Measure filter
    if measure_range is not None:
        m_lo, m_hi = measure_range
        if 'Measure' in selection.columns:
            selection = selection[
                (selection['Measure'] >= m_lo) &
                (selection['Measure'] <= m_hi)
            ]
        print(f"Filtered by Measure [{m_lo}, {m_hi}]: {len(selection)} rows")

    # 2. Onset filter
    if onset_range is not None:
        o_lo, o_hi = onset_range
        if 'Global Onset' in selection.columns:
            selection = selection[
                (selection['Global Onset'] >= o_lo) &
                (selection['Global Onset'] < o_hi)
            ]
        print(f"Filtered by Global Onset [{o_lo}, {o_hi}): {len(selection)} rows")

    # 3. Pitch filter
    _pitch_range_midi = _parse_pitch_range_for_filter(pitch_range)
    if _pitch_range_midi and 'MIDI' in selection.columns:
        p_lo, p_hi = _pitch_range_midi
        selection = selection[
            (selection['MIDI'] >= p_lo) &
            (selection['MIDI'] <= p_hi)
        ]
        print(f"Filtered by Pitch MIDI [{p_lo}, {p_hi}]: {len(selection)} rows")
    elif pitch_range:
        print(f"Warning: could not interpret pitch_range={pitch_range!r}; skipping pitch filter.")

    # 4. Voice filter
    if voice_query is not None and 'Voice' in selection.columns:
        if isinstance(voice_query, (list, tuple, set)):
            selection = selection[selection['Voice'].isin(list(voice_query))]
            print(f"Filtered by Voice list ({len(list(voice_query))} voices): {len(selection)} rows")
        else:
            pattern = str(voice_query)
            selection = selection[
                selection['Voice'].astype(str).str.contains(pattern, regex=True, na=False)
            ]
            print(f"Filtered by Voice ~ /{pattern}/: {len(selection)} rows")

    # 5. Display DataFrame selection
    if display_selection:
        if selection.empty:
            print("Selection is empty!")
        else:
            mode = (display_mode or 'head').strip().lower()
            if mode == 'all':
                ipy_display(selection)
            elif mode == 'none':
                pass
            else:
                # Default: head
                max_rows = int(display_max_rows) if display_max_rows is not None else 10
                ipy_display(selection.head(max_rows))

    # 6. Determine plot window
    if onset_range is not None:
        plot_start, plot_end = onset_range
    else:
        target_for_bounds = selection if not selection.empty else source_df
        try:
            plot_start = float(target_for_bounds['Global Onset'].min())
            plot_end = float((target_for_bounds['Global Onset'] + target_for_bounds['Duration']).max())
        except Exception:
            plot_start, plot_end = 0.0, 10.0

    # 7. Measure guide lines
    measure_offsets_full: Sequence[float] = []
    if measure_offsets is not None:
        measure_offsets_full = list(measure_offsets)
    elif results is not None:
        try:
            res_idx = next(
                (i for i, item in enumerate(results) if item.get('df') is source_df),
                None,
            )
            if res_idx is not None:
                measure_offsets_full = list(results[res_idx]['measure_offsets'])
        except Exception:
            measure_offsets_full = []
    if not measure_offsets_full and 'Measure' in source_df.columns and 'Global Onset' in source_df.columns:
        try:
            measure_offsets_full = (
                source_df.groupby('Measure')['Global Onset']
                .min()
                .sort_values()
                .tolist()
            )
        except Exception:
            measure_offsets_full = []

    eps = 1e-6
    visible_measure_offsets = [
        float(m) for m in measure_offsets_full
        if (m >= plot_start - eps) and (m <= plot_end + eps)
    ]
    if visible_measure_offsets:
        visible_measure_offsets = sorted({round(float(m), 6) for m in visible_measure_offsets})

    # 8. Plot
    backend = (plotting_backend or 'plt').strip().lower()
    draw_piano_roll(
        selection,
        measure_offsets=visible_measure_offsets,
        backend=backend,
        plot_width=plot_width,
        plot_height=plot_height,
        zoom_drag_dim=zoom_drag_dim,
        zoom_wheel_dim=zoom_wheel_dim,
        show_measure_lines=bool(show_measure_lines),
    )

    return selection


__all__ = [
    'parse_pitch_name',
    'name_to_midi',
    'midi_to_name',
    'build_pitch_counts',
    'sort_pitch_counts',
    'plot_pitch_distribution',
    'display_pitch_distribution',
    'build_pc_counts_from_names',
    'build_pitch_class_distributions',
    'display_pitch_class_distributions',
    'build_duration_counts',
    'plot_duration_distribution',
    'display_duration_distribution',
    'extract_selected_xml_ids',
]
