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


def _coerce_float_format(float_format: Optional[str]) -> Optional[str]:
    if float_format is None:
        return None
    spec = str(float_format).strip()
    if not spec:
        return None
    # Accept shorthand like "3f" and turn it into Python's ".3f".
    if len(spec) >= 2 and spec[:-1].isdigit() and spec[-1].lower() in ('f', 'e', 'g', '%'):
        spec = f".{spec}"
    return spec


def _bokeh_tick_format_from_float_format(float_format: Optional[str]) -> Optional[str]:
    spec = _coerce_float_format(float_format)
    if spec is None or len(spec) < 2 or not spec.startswith('.'):
        return None
    precision = spec[1:-1]
    kind = spec[-1].lower()
    if not precision.isdigit():
        return None
    zeros = "0" * int(precision)
    if kind in ('f', 'g', 'e'):
        return f"0.{zeros}" if zeros else "0"
    if kind == '%':
        return f"0.{zeros}%" if zeros else "0%"
    return None


def _format_number_for_display(value: Any, float_format: Optional[str]) -> str:
    spec = _coerce_float_format(float_format)
    if spec is None:
        return str(value)
    try:
        if pd.isna(value):
            return str(value)
    except Exception:
        pass
    try:
        return format(float(value), spec)
    except Exception:
        return str(value)


def _format_table_for_display(table_df: pd.DataFrame, float_format: Optional[str]) -> pd.DataFrame:
    spec = _coerce_float_format(float_format)
    if spec is None:
        return table_df

    out = table_df.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].map(lambda v: _format_number_for_display(v, spec))
    return out


def _pitch_distribution_title(normalize: bool) -> str:
    if normalize:
        return 'Pitch Distribution (Normalized)'
    return 'Pitch Distribution'


def _duration_distribution_title(normalize: bool) -> str:
    if normalize:
        return 'Duration Distribution (Normalized)'
    return 'Duration Distribution'


def _pitch_class_distribution_title(kind: str, normalize: bool) -> str:
    title = f'Pitch Class Distribution ({kind})'
    if normalize:
        title = f'{title} (Normalized)'
    return title


def _resolve_pitch_class_order_axis(
    pitch_axis: Optional[str],
    order_axis_by: Optional[str],
) -> str:
    if order_axis_by is not None and str(order_axis_by).strip():
        return str(order_axis_by)

    axis = str(pitch_axis or '').strip().lower()
    if axis in ('midi', 'pitch real', 'pitch', 'real'):
        return 'midi'
    return 'pitch by name'


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
    float_format: Optional[str] = None,
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
        from matplotlib.ticker import FuncFormatter

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
        if _coerce_float_format(float_format) is not None:
            ax.yaxis.set_major_formatter(
                FuncFormatter(lambda v, _pos: _format_number_for_display(v, float_format))
            )
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
            if _coerce_float_format(float_format) is not None:
                data[f's{j}_display'] = [
                    _format_number_for_display(v, float_format) for v in series_values[j]
                ]

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
                            (
                                y_label,
                                f'@{field_name}_display'
                                if _coerce_float_format(float_format) is not None
                                else f'@{field_name}',
                            ),
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


def build_pitch_counts(
    df: pd.DataFrame,
    axis_option: str,
    normalize: bool = False,
) -> Tuple[pd.DataFrame, str]:
    series, display_col = _display_series_from_axis(df, axis_option)
    counts_df = (
        pd.DataFrame({display_col: series})
        .groupby(display_col, dropna=False)
        .size()
        .rename('count')
        .reset_index()
    )
    if normalize:
        counts_df['count_raw'] = counts_df['count']
        total = float(counts_df['count_raw'].sum())
        if total > 0.0:
            counts_df['count'] = counts_df['count_raw'].astype(float) / total
        else:
            counts_df['count'] = counts_df['count_raw'].astype(float)
    return counts_df, display_col


def _to_midi_for_sort(display_col: str, val) -> Optional[int]:
    if display_col == 'MIDI':
        try:
            return int(val)
        except Exception:
            return None
    midi_val = name_to_midi(val)
    if midi_val is not None:
        return midi_val

    letter, acc, _ = parse_pitch_name(str(val) if val is not None else None)
    if letter is None:
        return None
    return (_NOTE_TO_PC[letter] + _accidental_to_semitones(acc)) % 12


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
    y_label: str = 'Count',
    title: str = 'Pitch Distribution',
    float_format: Optional[str] = None,
):
    backend_opt = (backend or 'plt').strip().lower()
    x_labels = counts_df[display_col].astype(str).tolist()
    y_values = counts_df['count'].tolist()

    if backend_opt == 'plt':
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter

        fig, ax = plt.subplots(figsize=(plot_width / 100.0, plot_height / 100.0))
        ax.bar(x_labels, y_values, color=bar_color)
        ax.set_xlabel(display_col)
        ax.set_ylabel(y_label)
        ax.set_title(title)
        if _coerce_float_format(float_format) is not None:
            ax.yaxis.set_major_formatter(
                FuncFormatter(lambda v, _pos: _format_number_for_display(v, float_format))
            )
        plt.xticks(rotation=90)
        plt.tight_layout()
        plt.show()
        return None

    if backend_opt == 'bokeh':
        from bokeh.plotting import figure, show
        from bokeh.io import output_notebook
        from bokeh.models import ColumnDataSource, HoverTool

        output_notebook()
        source_data = dict(x=x_labels, count=y_values)
        if _coerce_float_format(float_format) is not None:
            source_data['count_display'] = [
                _format_number_for_display(v, float_format) for v in y_values
            ]
        source = ColumnDataSource(source_data)
        p = figure(
            x_range=x_labels,
            height=plot_height,
            width=plot_width,
            title=title,
            toolbar_location='right',
        )
        p.vbar(x='x', top='count', width=0.9, source=source, fill_color=bar_color)
        if show_hover:
            p.add_tools(
                HoverTool(
                    tooltips=[
                        ("Pitch", "@x"),
                        (
                            y_label,
                            '@count_display'
                            if _coerce_float_format(float_format) is not None
                            else '@count',
                        ),
                    ]
                )
            )
        p.xaxis.axis_label = display_col
        p.yaxis.axis_label = y_label
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
    normalize: bool = False,
    float_format: Optional[str] = None,
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
    normalize : bool
        When True, convert counts to per-source proportions that sum to 1.0.
        Raw counts are preserved in a `count_raw` column.
    float_format : str or None
        Optional Python-style float format for displayed values, e.g. '.3f'.
        Shorthand like '3f' is also accepted and treated as '.3f'.

    Returns
    -------
    pandas.DataFrame
        - Single-source call: the sorted counts DataFrame with columns
          [display_col, 'count'] (plus sort helper columns). When
          `normalize=True`, `count` contains proportions and `count_raw`
          stores the original counts.
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
        counts_df, display_col = build_pitch_counts(
            dfs[0],
            pitch_axis,
            normalize=bool(normalize),
        )
        counts_df = sort_pitch_counts(counts_df, display_col, order_axis_by)

        if show_table:
            table_df = counts_df[[display_col, 'count']].copy()
            if normalize and 'count_raw' in counts_df.columns:
                table_df.insert(1, 'count_raw', counts_df['count_raw'])
                table_df = table_df.rename(columns={'count': 'share'})
            table_df = _format_table_for_display(table_df, float_format)
            try:
                ipy_display(table_df.set_index(display_col))
            except Exception:
                print(table_df.set_index(display_col))

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
            y_label=('Proportion' if normalize else 'Count'),
            title=_pitch_distribution_title(bool(normalize)),
            float_format=float_format,
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
        counts_df_i, display_col_i = build_pitch_counts(
            df,
            pitch_axis,
            normalize=bool(normalize),
        )
        if display_col is None:
            display_col = display_col_i
        elif display_col_i != display_col:
            counts_df_i = counts_df_i.rename(columns={display_col_i: display_col})
        counts_df_i = sort_pitch_counts(counts_df_i, display_col, order_axis_by)
        per_source_counts[label] = counts_df_i

        if show_table:
            print(f"=== Pitch Distribution ({label}) ===")
            table_df_i = counts_df_i[[display_col, 'count']].copy()
            if normalize and 'count_raw' in counts_df_i.columns:
                table_df_i.insert(1, 'count_raw', counts_df_i['count_raw'])
                table_df_i = table_df_i.rename(columns={'count': 'share'})
            table_df_i = _format_table_for_display(table_df_i, float_format)
            try:
                ipy_display(table_df_i.set_index(display_col))
            except Exception:
                print(table_df_i.set_index(display_col))

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
        title=_pitch_distribution_title(bool(normalize)),
        x_label=display_col,
        y_label=('Proportion' if normalize else 'Count'),
        backend=(backend.lower() if isinstance(backend, str) else 'plt'),
        plot_width=plot_width,
        plot_height=plot_height,
        show_hover=bool(show_hover),
        bar_color=bar_color,
        default_palette=_DEFAULT_PITCH_PALETTE,
        float_format=float_format,
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
    order_axis_by: str = 'pitch by name',
    normalize: bool = False,
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
        according to `order_axis_by`. When `normalize=True`, `count` contains
        per-series proportions and `count_raw` stores the original counts.
        When the input series yields no valid pitch classes, both elements are None.
    """
    pc_series = name_series.dropna().map(_get_pitch_class_from_name).dropna()
    if pc_series.empty:
        return None, None

    counts_pc = pc_series.value_counts().rename('count').reset_index()
    counts_pc.columns = [pc_label, 'count']
    if normalize:
        counts_pc['count_raw'] = counts_pc['count']
        total = float(counts_pc['count_raw'].sum())
        if total > 0.0:
            counts_pc['count'] = counts_pc['count_raw'].astype(float) / total
        else:
            counts_pc['count'] = counts_pc['count_raw'].astype(float)
    counts_pc = sort_pitch_counts(counts_pc, pc_label, order_axis_by)
    return counts_pc, pc_label


def build_pitch_class_distributions(
    source_df: pd.DataFrame,
    pitch_axis: str = 'pitch enharmonic',
    order_axis_by: Optional[str] = None,
    normalize: bool = False,
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

    `pitch_axis` is used here only to resolve the default pitch-class ordering
    when `order_axis_by` is not provided. This function still builds both
    distributions when the required source columns are available.

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
    resolved_order = _resolve_pitch_class_order_axis(pitch_axis, order_axis_by)

    # Real pitch classes (collapse by sounding pitch)
    if 'Pitch' in source_df.columns:
        counts_real, label_real = build_pc_counts_from_names(
            source_df['Pitch'],
            'Pitch Class (Real)',
            order_axis_by=resolved_order,
            normalize=bool(normalize),
        )
    elif 'MIDI' in source_df.columns:
        real_names = source_df['MIDI'].dropna().map(midi_to_name)
        counts_real, label_real = build_pc_counts_from_names(
            real_names,
            'Pitch Class (Real from MIDI)',
            order_axis_by=resolved_order,
            normalize=bool(normalize),
        )

    # Enharmonic / written pitch classes (collapse by notation spelling)
    if 'Pitch Enharmonic' in source_df.columns:
        counts_enh, label_enh = build_pc_counts_from_names(
            source_df['Pitch Enharmonic'],
            'Pitch Class (Enharmonic)',
            order_axis_by=resolved_order,
            normalize=bool(normalize),
        )

    return counts_real, counts_enh, label_real, label_enh


def display_pitch_class_distributions(
    source_df: pd.DataFrame,
    *more_source_dfs: pd.DataFrame,
    pitch_axis: str = 'pitch enharmonic',
    order_axis_by: Optional[str] = None,
    backend: str = 'bokeh',
    plot_width: int = 1200,
    plot_height: int = 450,
    show_hover: bool = True,
    show_table: bool = True,
    bar_color: Union[str, Sequence[str]] = '#4682B4',
    source_labels: Optional[Sequence[str]] = None,
    normalize: bool = False,
    float_format: Optional[str] = None,
) -> Mapping[str, Any]:
    """
    Build and display pitch-class distributions (real + enharmonic) from a notes DataFrame.

    Parameters
    ----------
    source_df : pandas.DataFrame
        Notes DataFrame with at least one of: 'MIDI', 'Pitch', 'Pitch Enharmonic'.
    pitch_axis : str
        Used to resolve the default pitch-class x-axis ordering when
        `order_axis_by` is not provided. This function still displays both
        real and enharmonic pitch-class distributions when available.
    order_axis_by : str or None
        Sort order for pitch-class categories. If omitted, a default is chosen
        from `pitch_axis`.
    backend : {'plt', 'bokeh'}
        Plotting backend for the bar charts.
    plot_width, plot_height : int
        Plot dimensions in pixels.
    show_hover : bool
        Enable hover tooltips (Bokeh backend only).
    show_table : bool
        Whether to display the counts tables.
    normalize : bool
        When True, convert counts to per-source proportions that sum to 1.0.
        Raw counts are preserved in a `count_raw` column.
    float_format : str or None
        Optional Python-style float format for displayed values, e.g. '.3f'.
        Shorthand like '3f' is also accepted and treated as '.3f'.

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
    resolved_order = _resolve_pitch_class_order_axis(pitch_axis, order_axis_by)

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
        counts_real, counts_enh, label_real, label_enh = build_pitch_class_distributions(
            dfs[0],
            pitch_axis=pitch_axis,
            order_axis_by=resolved_order,
            normalize=bool(normalize),
        )

        any_done = False

        if counts_real is not None and label_real is not None:
            any_done = True
            print(f"=== {_pitch_class_distribution_title('Real', bool(normalize))} ===")
            if show_table:
                table_real = counts_real.copy()
                if normalize and 'count_raw' in table_real.columns:
                    table_real = table_real.rename(columns={'count': 'share'})
                table_real = _format_table_for_display(table_real, float_format)
                try:
                    ipy_display(table_real.set_index(label_real).T)
                except Exception:
                    print(table_real.set_index(label_real).T)

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
                y_label=('Proportion' if normalize else 'Count'),
                title=_pitch_class_distribution_title('Real', bool(normalize)),
                float_format=float_format,
            )

        if counts_enh is not None and label_enh is not None:
            any_done = True
            print(f"=== {_pitch_class_distribution_title('Enharmonic / Written', bool(normalize))} ===")
            if show_table:
                table_enh = counts_enh.copy()
                if normalize and 'count_raw' in table_enh.columns:
                    table_enh = table_enh.rename(columns={'count': 'share'})
                table_enh = _format_table_for_display(table_enh, float_format)
                try:
                    ipy_display(table_enh.set_index(label_enh).T)
                except Exception:
                    print(table_enh.set_index(label_enh).T)

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
                y_label=('Proportion' if normalize else 'Count'),
                title=_pitch_class_distribution_title('Enharmonic / Written', bool(normalize)),
                float_format=float_format,
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
        counts_real, counts_enh, label_real, label_enh = build_pitch_class_distributions(
            df,
            pitch_axis=pitch_axis,
            order_axis_by=resolved_order,
            normalize=bool(normalize),
        )

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
                print(f"=== {_pitch_class_distribution_title('Real', bool(normalize))} - {lbl} ===")
                table_real = real_counts_by_label[lbl].copy()
                if normalize and 'count_raw' in table_real.columns:
                    table_real = table_real.rename(columns={'count': 'share'})
                table_real = _format_table_for_display(table_real, float_format)
                try:
                    ipy_display(table_real.set_index(label_real_main).T)
                except Exception:
                    print(table_real.set_index(label_real_main).T)

        all_vals_real = pd.concat(
            [df[label_real_main] for df in real_counts_by_label.values()],
            ignore_index=True,
        ).drop_duplicates()
        tmp_real = pd.DataFrame({label_real_main: all_vals_real, 'count': [0] * len(all_vals_real)})
        tmp_real_sorted = sort_pitch_counts(tmp_real, label_real_main, resolved_order)
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
            title=_pitch_class_distribution_title('Real', bool(normalize)),
            x_label=label_real_main,
            y_label=('Proportion' if normalize else 'Count'),
            backend=backend_opt,
            plot_width=plot_width,
            plot_height=plot_height,
            show_hover=bool(show_hover),
            bar_color=bar_color,
            default_palette=_DEFAULT_PITCH_PALETTE,
            float_format=float_format,
        )

    # Enharmonic pitch-class tables + combined plot
    if label_enh_main is not None and enh_counts_by_label:
        if show_table:
            for lbl in labels:
                if lbl not in enh_counts_by_label:
                    continue
                print(f"=== {_pitch_class_distribution_title('Enharmonic / Written', bool(normalize))} - {lbl} ===")
                table_enh = enh_counts_by_label[lbl].copy()
                if normalize and 'count_raw' in table_enh.columns:
                    table_enh = table_enh.rename(columns={'count': 'share'})
                table_enh = _format_table_for_display(table_enh, float_format)
                try:
                    ipy_display(table_enh.set_index(label_enh_main).T)
                except Exception:
                    print(table_enh.set_index(label_enh_main).T)

        all_vals_enh = pd.concat(
            [df[label_enh_main] for df in enh_counts_by_label.values()],
            ignore_index=True,
        ).drop_duplicates()
        tmp_enh = pd.DataFrame({label_enh_main: all_vals_enh, 'count': [0] * len(all_vals_enh)})
        tmp_enh_sorted = sort_pitch_counts(tmp_enh, label_enh_main, resolved_order)
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
            title=_pitch_class_distribution_title('Enharmonic / Written', bool(normalize)),
            x_label=label_enh_main,
            y_label=('Proportion' if normalize else 'Count'),
            backend=backend_opt,
            plot_width=plot_width,
            plot_height=plot_height,
            show_hover=bool(show_hover),
            bar_color=bar_color,
            default_palette=_DEFAULT_PITCH_PALETTE,
            float_format=float_format,
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
    round_decimals: Optional[int] = 4,
    normalize: bool = False,
    duration_column: Optional[str] = None,
) -> Tuple[pd.DataFrame, str]:
    # Use an explicitly selected duration concept, or retain legacy detection.
    duration_col = duration_column
    if duration_col is not None and duration_col not in df.columns:
        raise ValueError(f"Duration column {duration_col!r} is not present in the DataFrame.")
    if duration_col is None:
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
    if normalize:
        counts_df['count_raw'] = counts_df['count']
        total = float(counts_df['count_raw'].sum())
        if total > 0.0:
            counts_df['count'] = counts_df['count_raw'].astype(float) / total
        else:
            counts_df['count'] = counts_df['count_raw'].astype(float)
    
    return counts_df, duration_col


def plot_duration_distribution(
    counts_df: pd.DataFrame,
    display_col: str,
    backend: str = 'bokeh',
    plot_width: int = 900,
    plot_height: int = 350,
    show_hover: bool = True,
    bar_color: str = '#2E8B57',
    y_label: str = 'Count',
    title: str = 'Duration Distribution',
    float_format: Optional[str] = None,
):
    backend_opt = (backend or 'plt').strip().lower()
    x_labels = counts_df[display_col].astype(str).tolist()
    y_values = counts_df['count'].tolist()

    if backend_opt == 'plt':
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter

        fig, ax = plt.subplots(figsize=(plot_width / 100.0, plot_height / 100.0))
        ax.bar(x_labels, y_values, color=bar_color)
        ax.set_xlabel(display_col)
        ax.set_ylabel(y_label)
        ax.set_title(title)
        if _coerce_float_format(float_format) is not None:
            ax.yaxis.set_major_formatter(
                FuncFormatter(lambda v, _pos: _format_number_for_display(v, float_format))
            )
        plt.xticks(rotation=90)
        plt.tight_layout()
        plt.show()
        return None

    if backend_opt == 'bokeh':
        from bokeh.plotting import figure, show
        from bokeh.io import output_notebook
        from bokeh.models import ColumnDataSource, HoverTool
        output_notebook()

        source_data = dict(x=x_labels, count=y_values)
        if _coerce_float_format(float_format) is not None:
            source_data['count_display'] = [
                _format_number_for_display(v, float_format) for v in y_values
            ]
        source = ColumnDataSource(source_data)
        p = figure(
            x_range=x_labels,
            height=plot_height,
            width=plot_width,
            title=title,
            toolbar_location='right',
        )
        p.vbar(x='x', top='count', width=0.9, source=source, fill_color=bar_color)
        if show_hover:
             p.add_tools(
                 HoverTool(
                     tooltips=[
                         ("Duration", "@x"),
                         (
                             y_label,
                             '@count_display'
                             if _coerce_float_format(float_format) is not None
                             else '@count',
                         ),
                     ]
                 )
             )
        
        p.xaxis.axis_label = display_col
        p.yaxis.axis_label = y_label
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
    normalize: bool = False,
    float_format: Optional[str] = None,
    duration_column: Optional[str] = None,
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
    normalize : bool
        When True, convert counts to per-source proportions that sum to 1.0.
        Raw counts are preserved in a `count_raw` column.
    float_format : str or None
        Optional Python-style float format for displayed values, e.g. '.3f'.
        Shorthand like '3f' is also accepted and treated as '.3f'.
    duration_column : str or None
        Explicit duration concept to analyze, for example ``'Duration'`` for
        metric segments or ``'Logical Duration'`` for tied logical notes.

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
        counts_df, display_col = build_duration_counts(
            dfs[0],
            drop_zero,
            round_decimals,
            normalize=bool(normalize),
            duration_column=duration_column,
        )

        if show_table:
            table_df = counts_df[[display_col, 'count']].copy()
            if normalize and 'count_raw' in counts_df.columns:
                table_df.insert(1, 'count_raw', counts_df['count_raw'])
                table_df = table_df.rename(columns={'count': 'share'})
            table_df = _format_table_for_display(table_df, float_format)
            try:
                ipy_display(table_df.set_index(display_col))
            except Exception:
                print(table_df.set_index(display_col))

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
            y_label=('Proportion' if normalize else 'Count'),
            title=_duration_distribution_title(bool(normalize)),
            float_format=float_format,
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
        counts_df_i, display_col_i = build_duration_counts(
            df,
            drop_zero,
            round_decimals,
            normalize=bool(normalize),
            duration_column=duration_column,
        )
        if display_col is None:
            display_col = display_col_i
        elif display_col_i != display_col:
            counts_df_i = counts_df_i.rename(columns={display_col_i: display_col})
        per_source_counts[label] = counts_df_i

        if show_table:
            print(f"=== Duration Distribution ({label}) ===")
            table_df_i = counts_df_i[[display_col, 'count']].copy()
            if normalize and 'count_raw' in counts_df_i.columns:
                table_df_i.insert(1, 'count_raw', counts_df_i['count_raw'])
                table_df_i = table_df_i.rename(columns={'count': 'share'})
            table_df_i = _format_table_for_display(table_df_i, float_format)
            try:
                ipy_display(table_df_i.set_index(display_col))
            except Exception:
                print(table_df_i.set_index(display_col))

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
        title=_duration_distribution_title(bool(normalize)),
        x_label=display_col,
        y_label=('Proportion' if normalize else 'Count'),
        backend=(backend.lower() if isinstance(backend, str) else 'plt'),
        plot_width=plot_width,
        plot_height=plot_height,
        show_hover=bool(show_hover),
        bar_color=bar_color,
        default_palette=_DEFAULT_DURATION_PALETTE,
        float_format=float_format,
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
    events_df: Optional[pd.DataFrame] = None,
    plot_parsed_barlines_with_voice_coloring: bool = False,
    plotting_backend: str = 'plt',
    plot_width: Optional[int] = None,
    plot_height: Optional[int] = None,
    colorize_voices: bool = False,
    palette: Optional[Union[str, Sequence[str]]] = None,
    preserve_voice_color_mapping: bool = True,
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
    events_df : pandas.DataFrame, optional
        Parsed events dataframe (typically `df_events`) used to overlay barlines.
        When None, this helper attempts to fetch matching events from `results`.
    plot_parsed_barlines_with_voice_coloring : bool
        If True, pass parsed barline events to `draw_piano_roll` and color them
        according to their Voice labels.
    plotting_backend : {'plt', 'bokeh'}
        Backend for `draw_piano_roll`.
    plot_width, plot_height : int, optional
        Plot dimensions passed through to `draw_piano_roll`.
    colorize_voices : bool
        If True, color notes by voice labels.
    palette : str | Sequence[str], optional
        Palette passed to `draw_piano_roll` when colorizing voices.
    preserve_voice_color_mapping : bool
        If True (default), keep voice-to-color mapping stable by using voice
        order from `source_df` even when plotting a filtered subset.
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

    # 8. Resolve event overlays (barlines)
    resolved_events_df: Optional[pd.DataFrame] = events_df
    if resolved_events_df is None and results is not None:
        try:
            matched_item = None
            for item in results:
                if item.get('df') is source_df or item.get('df_pitch') is source_df:
                    matched_item = item
                    break
            if matched_item is not None:
                candidate = matched_item.get('df_events')
                if isinstance(candidate, pd.DataFrame):
                    resolved_events_df = candidate
        except Exception:
            resolved_events_df = None

    visible_events_df: Optional[pd.DataFrame] = None
    if bool(plot_parsed_barlines_with_voice_coloring) and isinstance(resolved_events_df, pd.DataFrame):
        try:
            ev = resolved_events_df.copy()
            if 'type' in ev.columns:
                ev = ev[ev['type'].astype(str).str.lower() == 'barline']
            if 'Global Onset' in ev.columns:
                ev = ev[
                    (ev['Global Onset'] >= (plot_start - eps)) &
                    (ev['Global Onset'] <= (plot_end + eps))
                ]
            if voice_query is not None and 'Voice' in ev.columns:
                if isinstance(voice_query, (list, tuple, set)):
                    ev = ev[ev['Voice'].isin(list(voice_query))]
                else:
                    pattern = str(voice_query)
                    ev = ev[ev['Voice'].astype(str).str.contains(pattern, regex=True, na=False)]
            visible_events_df = ev
        except Exception:
            visible_events_df = None

    # When parsed barline overlays are enabled, prefer their onsets for measure guides.
    # This avoids mixing inferred/default grid lines with explicit MEI barline events.
    if bool(plot_parsed_barlines_with_voice_coloring) and isinstance(visible_events_df, pd.DataFrame) and not visible_events_df.empty:
        try:
            parsed_offsets = [
                float(x)
                for x in pd.unique(visible_events_df['Global Onset'])
                if np.isfinite(float(x))
            ]
            if parsed_offsets:
                visible_measure_offsets = sorted({round(x, 6) for x in parsed_offsets})
        except Exception:
            pass

    # 9. Plot
    backend = (plotting_backend or 'plt').strip().lower()
    voice_color_order: Optional[List[str]] = None
    if bool(colorize_voices) and bool(preserve_voice_color_mapping) and 'Voice' in source_df.columns:
        try:
            voice_color_order = [
                str(v)
                for v in pd.unique(source_df['Voice'].dropna())
                if str(v).strip()
            ]
        except Exception:
            voice_color_order = None
    draw_piano_roll(
        selection,
        measure_offsets=visible_measure_offsets,
        barline_events=visible_events_df,
        plot_parsed_barlines_with_voice_coloring=bool(plot_parsed_barlines_with_voice_coloring),
        backend=backend,
        plot_width=plot_width,
        plot_height=plot_height,
        colorize_voices=bool(colorize_voices),
        palette=palette,
        voice_color_order=voice_color_order,
        zoom_drag_dim=zoom_drag_dim,
        zoom_wheel_dim=zoom_wheel_dim,
        show_measure_lines=bool(show_measure_lines),
    )

    return selection


def _summarize_monophony_segments(
    notes: pd.DataFrame,
    *,
    onset_col: str,
    duration_col: str,
) -> dict[str, Any]:
    eps = 1e-12
    check = notes.copy()
    check["_start"] = pd.to_numeric(check[onset_col], errors="coerce")
    check["_dur"] = pd.to_numeric(check[duration_col], errors="coerce")
    check["_end"] = check["_start"] + check["_dur"]
    check = check[
        check["_start"].notnull()
        & check["_end"].notnull()
        & (check["_end"] > check["_start"] + eps)
    ].copy()

    if check.empty:
        return {
            "note_count": 0,
            "valid_note_count": 0,
            "is_monophonic": True,
            "max_polyphony": 0,
            "num_overlap_spans": 0,
            "first_overlap": None,
        }

    events: list[tuple[float, int]] = []
    for row in check[["_start", "_end"]].itertuples(index=False):
        events.append((float(row[0]), 0))
        events.append((float(row[1]), 1))
    events.sort(key=lambda item: (item[0], item[1]))

    active_count = 0
    max_polyphony = 0
    num_overlap_spans = 0
    first_overlap: Optional[dict[str, Any]] = None
    last_t: Optional[float] = None

    for t, kind in events:
        if last_t is not None and t > last_t + eps:
            max_polyphony = max(max_polyphony, active_count)
            if active_count > 1:
                num_overlap_spans += 1
                if first_overlap is None:
                    first_overlap = {
                        "start": last_t,
                        "end": t,
                        "active_count": active_count,
                    }
        if kind == 0:
            active_count += 1
        else:
            active_count = max(0, active_count - 1)
        last_t = t

    return {
        "note_count": int(len(notes)),
        "valid_note_count": int(len(check)),
        "is_monophonic": num_overlap_spans == 0,
        "max_polyphony": max_polyphony,
        "num_overlap_spans": num_overlap_spans,
        "first_overlap": first_overlap,
    }


def check_monophonic_input(
    notes: pd.DataFrame,
    *,
    label: str = "selection",
    onset_candidates: Sequence[str] = ("Global Onset", "Onset", "global_onset", "Local Onset", "local_onset"),
    duration_candidates: Sequence[str] = ("Duration", "duration"),
    voice_candidates: Sequence[str] = ("Voice", "voice"),
    by_voice: bool = True,
    raise_on_polyphony: bool = False,
) -> Mapping[str, Any]:
    """
    Check whether the analyzed note stream is monophonic.

    When `by_voice=True` and a matching voice column exists, the check is
    performed separately for each voice. This allows multiple voices to
    overlap in time while still enforcing monophony within each individual
    melodic stream.

    Returns a summary dict with per-group diagnostics. If
    `raise_on_polyphony=True`, a `ValueError` is raised when overlap is found.
    """
    if notes is None or len(notes) == 0:
        return {
            "label": label,
            "is_monophonic": True,
            "checked_by_voice": False,
            "onset_column": None,
            "duration_column": None,
            "voice_column": None,
            "note_count": 0,
            "valid_note_count": 0,
            "max_polyphony": 0,
            "num_overlap_spans": 0,
            "first_overlap": None,
            "groups": [],
        }

    onset_col = None
    for c in onset_candidates:
        if c in notes.columns:
            onset_col = c
            break
    if onset_col is None:
        raise ValueError(f"Could not find an onset column. Tried: {list(onset_candidates)}")

    duration_col = None
    for c in duration_candidates:
        if c in notes.columns:
            duration_col = c
            break
    if duration_col is None:
        raise ValueError(f"Could not find a duration column. Tried: {list(duration_candidates)}")

    voice_col = None
    for c in voice_candidates:
        if c in notes.columns:
            voice_col = c
            break

    use_voice_groups = bool(by_voice and voice_col is not None)
    if use_voice_groups:
        grouped_iter = list(notes.groupby(voice_col, dropna=False))
    else:
        grouped_iter = [(None, notes)]

    group_summaries: list[dict[str, Any]] = []
    first_overlap: Optional[dict[str, Any]] = None
    max_polyphony = 0
    num_overlap_spans = 0
    valid_note_count = 0

    for group_name, group_df in grouped_iter:
        summary = _summarize_monophony_segments(
            group_df,
            onset_col=onset_col,
            duration_col=duration_col,
        )
        group_summary = {
            "group": group_name,
            **summary,
        }
        group_summaries.append(group_summary)
        valid_note_count += int(summary["valid_note_count"])
        max_polyphony = max(max_polyphony, int(summary["max_polyphony"]))
        num_overlap_spans += int(summary["num_overlap_spans"])
        if first_overlap is None and summary["first_overlap"] is not None:
            first_overlap = {
                "group": group_name,
                **dict(summary["first_overlap"]),
            }

    is_monophonic = all(bool(item["is_monophonic"]) for item in group_summaries)
    result = {
        "label": label,
        "is_monophonic": is_monophonic,
        "checked_by_voice": use_voice_groups,
        "onset_column": onset_col,
        "duration_column": duration_col,
        "voice_column": voice_col,
        "note_count": int(len(notes)),
        "valid_note_count": valid_note_count,
        "max_polyphony": max_polyphony,
        "num_overlap_spans": num_overlap_spans,
        "first_overlap": first_overlap,
        "groups": group_summaries,
    }

    if raise_on_polyphony and not is_monophonic:
        overlap = first_overlap or {}
        start = overlap.get("start")
        end = overlap.get("end")
        group_name = overlap.get("group")
        scope = f"voice {group_name!r}" if use_voice_groups else "the analyzed stream"
        raise ValueError(
            f"Non-monophonic input detected for {label!r}: overlap found in {scope}. "
            f"First overlap span: [{start}, {end}] with max polyphony {max_polyphony}."
        )

    return result


def melodic_interval_distribution(
    notes: pd.DataFrame,
    *,
    label: str = "selection",
    onset_candidates: Sequence[str] = ("Global Onset", "Onset", "global_onset", "Local Onset", "local_onset"),
    duration_candidates: Sequence[str] = ("Duration", "duration"),
    midi_candidates: Sequence[str] = ("MIDI", "midi"),
    voice_candidates: Sequence[str] = ("Voice", "voice"),
    by_voice: bool = True,
    require_monophonic: bool = True,
) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Compute melodic interval distribution from successive notes.

    Intervals are measured in semitones between consecutive notes. When
    `by_voice=True` and a matching voice column exists, successive intervals
    are computed separately per voice and pooled into one distribution.

    If `require_monophonic=True`, each analyzed stream must be monophonic.
    This uses `check_monophonic_input(...)` and raises when overlaps are
    detected in the active analysis stream(s).
    """
    if notes is None or len(notes) == 0:
        raise ValueError("Empty notes selection.")

    df = notes.copy()

    onset_col = None
    for c in onset_candidates:
        if c in df.columns:
            onset_col = c
            break
    midi_col = None
    for c in midi_candidates:
        if c in df.columns:
            midi_col = c
            break
    duration_col = None
    for c in duration_candidates:
        if c in df.columns:
            duration_col = c
            break
    voice_col = None
    for c in voice_candidates:
        if c in df.columns:
            voice_col = c
            break

    if onset_col is None or midi_col is None:
        raise ValueError("Need onset and MIDI columns for interval analysis.")

    df["_onset"] = pd.to_numeric(df[onset_col], errors="coerce")
    df["_midi"] = pd.to_numeric(df[midi_col], errors="coerce")
    df = df[df["_onset"].notnull() & df["_midi"].notnull()].copy()
    if df.empty:
        raise ValueError("No valid onset/MIDI rows after filtering.")

    if require_monophonic:
        if duration_col is None:
            raise ValueError(
                "Could not verify monophony safely because no duration column was found. "
                f"Tried: {list(duration_candidates)}"
            )
        check_monophonic_input(
            df,
            label=label,
            onset_candidates=(onset_col,),
            duration_candidates=(duration_col,),
            voice_candidates=((voice_col,) if voice_col is not None else ()),
            by_voice=bool(by_voice),
            raise_on_polyphony=True,
        )

    if by_voice and voice_col is not None and voice_col in df.columns:
        groups_iter = list(df.groupby(voice_col, dropna=False))
    else:
        groups_iter = [(None, df)]

    interval_values: list[float] = []
    for _group_name, group_df in groups_iter:
        g = group_df.sort_values(["_onset", "_midi"], kind="mergesort").reset_index(drop=True)
        if len(g) < 2:
            continue
        diffs = g["_midi"].diff().dropna()
        interval_values.extend(float(v) for v in diffs.tolist())

    intervals = pd.Series(interval_values, name="interval_semitones", dtype=float)

    def label_interval(semitones: float) -> str:
        """
        Map semitone distance to a signed interval label like +M3 or -P8.

        Compound intervals are folded into octaves and keep their direction.
        """
        if pd.isna(semitones):
            return "?"

        if semitones > 0:
            sign = "+"
        elif semitones < 0:
            sign = "-"
        else:
            sign = ""

        n = int(round(abs(float(semitones))))
        if n == 0:
            return f"{sign}P1"

        base_map = {
            0: ("P", 1),
            1: ("m", 2),
            2: ("M", 2),
            3: ("m", 3),
            4: ("M", 3),
            5: ("P", 4),
            6: ("d", 5),
            7: ("P", 5),
            8: ("m", 6),
            9: ("M", 6),
            10: ("m", 7),
            11: ("M", 7),
        }

        octaves, rem = divmod(n, 12)
        if rem == 0:
            quality, simple_number = ("P", 1)
        else:
            quality, simple_number = base_map.get(rem, (None, None))

        if quality is None or simple_number is None:
            return f"{sign}{n} st"

        interval_number = simple_number + 7 * octaves
        return f"{sign}{quality}{interval_number}"

    if intervals.empty:
        dist_df = pd.DataFrame(
            columns=["interval", "count", "mean_semitones"]
        )
        return dist_df, intervals

    labels = intervals.map(label_interval)
    order = intervals.round().astype(int)

    dist_df = (
        pd.DataFrame({"interval": labels, "order": order})
        .groupby("interval")
        .agg(count=("order", "size"), mean_semitones=("order", "mean"))
        .reset_index()
    )
    dist_df = dist_df.sort_values("mean_semitones").reset_index(drop=True)

    return dist_df, intervals


def _melodic_interval_distribution_title(normalize: bool) -> str:
    if normalize:
        return "Melodic Interval Distribution (Normalized)"
    return "Melodic Interval Distribution"


def _normalize_melodic_interval_counts(counts_df: pd.DataFrame, normalize: bool) -> pd.DataFrame:
    out = counts_df.copy()
    if normalize:
        out["count_raw"] = out["count"]
        total = float(out["count_raw"].sum())
        if total > 0.0:
            out["count"] = out["count_raw"].astype(float) / total
        else:
            out["count"] = out["count_raw"].astype(float)
    return out


def _sort_melodic_interval_counts(counts_df: pd.DataFrame) -> pd.DataFrame:
    out = counts_df.copy()
    if "mean_semitones" in out.columns:
        return out.sort_values(["mean_semitones", "interval"], kind="mergesort").reset_index(drop=True)
    return out.sort_values(["interval"], kind="mergesort").reset_index(drop=True)


def display_melodic_interval_distribution(
    source_df: pd.DataFrame,
    *more_source_dfs: pd.DataFrame,
    source_labels: Optional[Sequence[str]] = None,
    onset_candidates: Sequence[str] = ("Global Onset", "Onset", "global_onset", "Local Onset", "local_onset"),
    duration_candidates: Sequence[str] = ("Duration", "duration"),
    midi_candidates: Sequence[str] = ("MIDI", "midi"),
    voice_candidates: Sequence[str] = ("Voice", "voice"),
    by_voice: bool = True,
    require_monophonic: bool = True,
    normalize: bool = False,
    backend: str = "plt",
    plot_width: int = 900,
    plot_height: int = 350,
    show_hover: bool = True,
    show_table: bool = True,
    bar_color: Union[str, Sequence[str]] = "#4682B4",
    float_format: Optional[str] = None,
) -> Union[pd.DataFrame, Mapping[str, pd.DataFrame]]:
    """
    Build and display a melodic interval distribution table and plot.

    Single-source calls return one interval distribution DataFrame. Multi-source
    calls return a mapping of source label -> interval distribution DataFrame.
    When `normalize=True`, counts are converted to per-source proportions and
    raw counts are preserved in `count_raw`.
    """
    if not more_source_dfs and not isinstance(source_df, pd.DataFrame):
        if isinstance(source_df, (list, tuple)):
            dfs = list(source_df)
        else:
            dfs = [source_df]
    else:
        dfs = [source_df] + list(more_source_dfs)

    if source_labels is not None:
        labels = list(source_labels)[:len(dfs)]
        if len(labels) < len(dfs):
            labels.extend(_guess_labels_for_dfs(dfs[len(labels):], default_prefix="Source"))
    else:
        labels = _guess_labels_for_dfs(dfs, default_prefix="Source")

    if len(dfs) == 1:
        counts_df, _intervals = melodic_interval_distribution(
            dfs[0],
            label=labels[0],
            onset_candidates=onset_candidates,
            duration_candidates=duration_candidates,
            midi_candidates=midi_candidates,
            voice_candidates=voice_candidates,
            by_voice=bool(by_voice),
            require_monophonic=bool(require_monophonic),
        )
        counts_df = _normalize_melodic_interval_counts(counts_df, bool(normalize))
        counts_df = _sort_melodic_interval_counts(counts_df)

        if show_table:
            table_df = counts_df[["interval", "count", "mean_semitones"]].copy()
            if normalize and "count_raw" in counts_df.columns:
                table_df.insert(1, "count_raw", counts_df["count_raw"])
                table_df = table_df.rename(columns={"count": "share"})
            table_df = _format_table_for_display(table_df, float_format)
            try:
                ipy_display(table_df.set_index("interval"))
            except Exception:
                print(table_df.set_index("interval"))

        if not isinstance(bar_color, str):
            try:
                bar_color_single = str(list(bar_color)[0])  # type: ignore[arg-type]
            except Exception:
                bar_color_single = "#4682B4"
        else:
            bar_color_single = bar_color

        plot_pitch_distribution(
            counts_df,
            "interval",
            backend=(backend.lower() if isinstance(backend, str) else "plt"),
            plot_width=plot_width,
            plot_height=plot_height,
            show_hover=bool(show_hover),
            bar_color=bar_color_single,
            y_label=("Proportion" if normalize else "Count"),
            title=_melodic_interval_distribution_title(bool(normalize)),
            float_format=float_format,
        )
        return counts_df

    per_source_counts: dict[str, pd.DataFrame] = {}
    category_mean: dict[str, float] = {}

    for df, label in zip(dfs, labels):
        counts_df_i, _intervals_i = melodic_interval_distribution(
            df,
            label=label,
            onset_candidates=onset_candidates,
            duration_candidates=duration_candidates,
            midi_candidates=midi_candidates,
            voice_candidates=voice_candidates,
            by_voice=bool(by_voice),
            require_monophonic=bool(require_monophonic),
        )
        counts_df_i = _normalize_melodic_interval_counts(counts_df_i, bool(normalize))
        counts_df_i = _sort_melodic_interval_counts(counts_df_i)
        per_source_counts[label] = counts_df_i

        if "mean_semitones" in counts_df_i.columns:
            for row in counts_df_i[["interval", "mean_semitones"]].itertuples(index=False):
                if row[0] not in category_mean:
                    category_mean[str(row[0])] = float(row[1])

        if show_table:
            print(f"=== Melodic Interval Distribution ({label}) ===")
            table_df_i = counts_df_i[["interval", "count", "mean_semitones"]].copy()
            if normalize and "count_raw" in counts_df_i.columns:
                table_df_i.insert(1, "count_raw", counts_df_i["count_raw"])
                table_df_i = table_df_i.rename(columns={"count": "share"})
            table_df_i = _format_table_for_display(table_df_i, float_format)
            try:
                ipy_display(table_df_i.set_index("interval"))
            except Exception:
                print(table_df_i.set_index("interval"))

    if not per_source_counts:
        return {}

    categories = sorted(
        category_mean.keys(),
        key=lambda k: (category_mean.get(k, 0.0), k),
    )

    series_values: list[list[float]] = []
    for label in labels:
        df_i = per_source_counts[label].set_index("interval")["count"]
        series_values.append([float(df_i.get(cat, 0.0)) for cat in categories])

    _plot_multi_bar(
        categories=categories,
        series_values=series_values,
        series_labels=labels,
        title=_melodic_interval_distribution_title(bool(normalize)),
        x_label="interval",
        y_label=("Proportion" if normalize else "Count"),
        backend=(backend.lower() if isinstance(backend, str) else "plt"),
        plot_width=plot_width,
        plot_height=plot_height,
        show_hover=bool(show_hover),
        bar_color=bar_color,
        default_palette=_DEFAULT_PITCH_PALETTE,
        float_format=float_format,
    )

    return per_source_counts


def display_successive_pitch_transition_heatmaps(
    source: Union[pd.DataFrame, Sequence[pd.DataFrame]],
    *,
    source_labels: Optional[Sequence[str]] = None,
    onset_candidates: Sequence[str] = ("Global Onset", "Onset", "global_onset", "Local Onset", "local_onset"),
    duration_candidates: Sequence[str] = ("Duration", "duration"),
    midi_candidates: Sequence[str] = ("MIDI", "midi"),
    voice_candidates: Sequence[str] = ("Voice", "voice"),
    by_voice: bool = True,
    normalize: Union[bool, str, None] = False,  # False/'count' | True/'row' | 'column' | 'all'
    normalize_rows: Optional[bool] = None,
    require_monophonic: bool = True,
    max_pitches: Optional[int] = None,
    backend: str = "bokeh",
    plot_width: int = 1000,
    plot_height_pitch: int = 700,
    plot_height_pc: int = 450,
    show_hover: bool = True,
    show_table: bool = True,
    float_format: Optional[str] = None,
):
    """
    Build and visualize successive-pitch transition matrices (bigram heatmaps):
    - absolute pitch (by MIDI -> rendered as pitch labels like C#4)
    - pitch class (0..11)

    The matrix is: rows = previous, cols = next.

    normalize:
      Primary normalization control:
      - `False`, `None`, or 'count': raw counts (no normalization)
      - `True` or 'row': row-normalized probabilities (P(next | prev))
      - 'column': column-normalized probabilities (P(prev | next))
      - 'all': global-normalized probabilities over the full heatmap
      Default is `False` (raw counts).
    normalize_rows:
      Backwards-compatible boolean alias.
      - `True` forces row-normalized probabilities.
      - `False` forces raw counts.
      - `None` leaves `normalize` unchanged.
      If provided, this takes precedence over `normalize`.
    require_monophonic:
      If True, validate that each analyzed stream is monophonic before
      building bigrams. When `by_voice=True` and a voice column exists,
      the check is applied separately per voice; overlaps across different
      voices are then allowed. If no duration column is available, the
      function raises because monophony cannot be verified safely.
    float_format:
      Optional Python-style float format for displayed values, e.g. '.3f'.
      Shorthand like '3f' is also accepted and treated as '.3f'.
    """

    def _pick_first_existing(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    def _as_df_list(src: Union[pd.DataFrame, Sequence[pd.DataFrame]]) -> list[pd.DataFrame]:
        if isinstance(src, pd.DataFrame):
            return [src]
        return [df for df in src]

    def _normalize_matrix(mat: pd.DataFrame, mode: Union[bool, str, None]) -> pd.DataFrame:
        if mode is True:
            m = "row"
        elif mode is False or mode is None:
            m = "count"
        else:
            m = str(mode).strip().lower()
        if m in ("count", "counts", "none", ""):
            return mat
        if mat.empty:
            return mat
        if m in ("row", "rows", "rowwise"):
            mat_float = mat.astype(float)
            denom = mat_float.sum(axis=1).astype(float).replace(0.0, float("nan"))
            return mat_float.div(denom, axis=0).fillna(0.0)
        if m in ("column", "columns", "col", "cols", "colwise", "columnwise"):
            mat_float = mat.astype(float)
            denom = mat_float.sum(axis=0).astype(float).replace(0.0, float("nan"))
            return mat_float.div(denom, axis=1).fillna(0.0)
        if m in ("all", "global", "total"):
            mat_float = mat.astype(float)
            total = float(mat_float.values.sum())
            return (mat_float / total) if total > 0 else mat_float * 0.0
        raise ValueError(
            "Unsupported normalize="
            f"{mode!r}. Use False/None/'count', True/'row', 'column', or 'all'."
        )

    def _bokeh_heatmap(
        mat: pd.DataFrame,
        *,
        title: str,
        x_label: str,
        y_label: str,
        plot_width_: int,
        plot_height_: int,
        show_hover_: bool,
        float_format_: Optional[str],
    ):
        from bokeh.plotting import figure, show
        from bokeh.io import output_notebook
        from bokeh.models import (
            ColumnDataSource,
            HoverTool,
            LinearColorMapper,
            ColorBar,
            BasicTicker,
            NumeralTickFormatter,
        )
        from bokeh.palettes import Viridis256

        output_notebook()

        if mat is None or mat.empty:
            print(f"{title}: empty matrix -> nothing to plot.")
            return None

        xs = [str(c) for c in mat.columns.tolist()]
        ys = [str(r) for r in mat.index.tolist()]

        df_long = (
            mat.stack()
            .rename("value")
            .reset_index()
            .rename(columns={"level_0": "prev", "level_1": "next"})
        )
        df_long["prev"] = df_long["prev"].astype(str)
        df_long["next"] = df_long["next"].astype(str)
        if _coerce_float_format(float_format_) is not None:
            df_long["value_display"] = df_long["value"].map(
                lambda v: _format_number_for_display(v, float_format_)
            )

        vmin = float(df_long["value"].min()) if len(df_long) else 0.0
        vmax = float(df_long["value"].max()) if len(df_long) else 0.0
        if vmax == vmin:
            vmax = vmin + 1e-12

        mapper = LinearColorMapper(palette=Viridis256, low=vmin, high=vmax)

        p = figure(
            title=title,
            x_range=xs,
            y_range=ys,
            height=plot_height_,
            width=plot_width_,
            toolbar_location="right",
            x_axis_label=x_label,
            y_axis_label=y_label,
        )
        src = ColumnDataSource(df_long)
        r = p.rect(
            x="next",
            y="prev",
            width=1,
            height=1,
            source=src,
            line_color=None,
            fill_color={"field": "value", "transform": mapper},
        )

        if show_hover_:
            p.add_tools(
                HoverTool(
                    renderers=[r],
                    tooltips=[
                        ("prev", "@prev"),
                        ("next", "@next"),
                        (
                            "value",
                            "@value_display"
                            if _coerce_float_format(float_format_) is not None
                            else "@value{0.000}",
                        ),
                    ],
                )
            )

        p.xaxis.major_label_orientation = 1.0
        p.xgrid.grid_line_color = None
        p.ygrid.grid_line_color = None

        color_bar = ColorBar(
            color_mapper=mapper,
            ticker=BasicTicker(desired_num_ticks=10),
            location=(0, 0),
        )
        bokeh_tick_format = _bokeh_tick_format_from_float_format(float_format_)
        if bokeh_tick_format is not None:
            color_bar.formatter = NumeralTickFormatter(format=bokeh_tick_format)
        p.add_layout(color_bar, "right")
        show(p)
        return p

    def _plt_heatmap(
        mat: pd.DataFrame,
        *,
        title: str,
        x_label: str,
        y_label: str,
        plot_width_: int,
        plot_height_: int,
        float_format_: Optional[str],
    ):
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.ticker import FuncFormatter

        if mat is None or mat.empty:
            print(f"{title}: empty matrix -> nothing to plot.")
            return None

        fig, ax = plt.subplots(figsize=(plot_width_ / 100.0, plot_height_ / 100.0))
        data = mat.to_numpy(dtype=float)
        im = ax.imshow(data, aspect="auto", origin="lower", cmap="viridis")

        ax.set_title(title)
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)

        ax.set_xticks(np.arange(len(mat.columns)))
        ax.set_xticklabels([str(c) for c in mat.columns], rotation=90)
        ax.set_yticks(np.arange(len(mat.index)))
        ax.set_yticklabels([str(r) for r in mat.index])

        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        if _coerce_float_format(float_format_) is not None:
            cbar.ax.yaxis.set_major_formatter(
                FuncFormatter(lambda v, _pos: _format_number_for_display(v, float_format_))
            )
        plt.tight_layout()
        plt.show()
        return fig

    dfs = _as_df_list(source)
    if source_labels is not None:
        labels = list(source_labels)[:len(dfs)]
        if len(labels) < len(dfs):
            labels.extend(_guess_labels_for_dfs(dfs[len(labels):], default_prefix="Source"))
    else:
        labels = _guess_labels_for_dfs(dfs, default_prefix="Source")
    backend_opt = (backend or "bokeh").strip().lower()
    if normalize_rows is True:
        normalize_mode: Union[bool, str, None] = "row"
    elif normalize_rows is False:
        normalize_mode = "count"
    else:
        normalize_mode = normalize

    outputs: list[dict[str, Any]] = []

    for df, lbl in zip(dfs, labels):
        if df is None or len(df) == 0:
            print(f"=== Successive Pitch Transitions ({lbl}) ===")
            print("Empty selection -> nothing to analyze.")
            outputs.append({"label": lbl, "pitch_matrix": None, "pc_matrix": None})
            continue

        onset_col = _pick_first_existing(df, onset_candidates)
        duration_col = _pick_first_existing(df, duration_candidates)
        midi_col = _pick_first_existing(df, midi_candidates)
        voice_col = _pick_first_existing(df, voice_candidates)
        if onset_col is None:
            raise ValueError(f"Could not find an onset column. Tried: {list(onset_candidates)}")
        if midi_col is None:
            raise ValueError(f"Could not find a MIDI column. Tried: {list(midi_candidates)}")

        work = df.copy()
        work["_onset"] = pd.to_numeric(work[onset_col], errors="coerce")
        work["_midi"] = pd.to_numeric(work[midi_col], errors="coerce")
        work = work[work["_onset"].notnull() & work["_midi"].notnull()].copy()
        if work.empty:
            print(f"=== Successive Pitch Transitions ({lbl}) ===")
            print("No valid onset/MIDI rows after filtering -> nothing to analyze.")
            outputs.append({"label": lbl, "pitch_matrix": None, "pc_matrix": None})
            continue

        if require_monophonic:
            if duration_col is None:
                raise ValueError(
                    "Could not verify monophony safely because no duration column was found. "
                    f"Tried: {list(duration_candidates)}"
                )
            monophony_check = check_monophonic_input(
                work,
                label=lbl,
                onset_candidates=(onset_col,),
                duration_candidates=(duration_col,),
                voice_candidates=((voice_col,) if voice_col is not None else ()),
                by_voice=bool(by_voice),
                raise_on_polyphony=False,
            )
            if not bool(monophony_check["is_monophonic"]):
                first_overlap = monophony_check.get("first_overlap") or {}
                start = first_overlap.get("start")
                end = first_overlap.get("end")
                max_polyphony = monophony_check.get("max_polyphony")
                overlap_group = first_overlap.get("group")
                scope = (
                    f"voice {overlap_group!r}"
                    if bool(monophony_check.get("checked_by_voice"))
                    else "the analyzed stream"
                )
                raise ValueError(
                    "Successive pitch bigrams require monophonic input, but overlapping notes "
                    f"were detected in {scope} for source {lbl!r}. "
                    f"First overlap span: [{start}, {end}] with max polyphony {max_polyphony}. "
                    "Set require_monophonic=False to bypass this safety check."
                )

        # Collect successive pairs (prev -> next)
        pairs_midi: list[tuple[int, int]] = []
        if by_voice and voice_col is not None and voice_col in work.columns:
            grouped = work.groupby(voice_col, dropna=False)
            groups_iter = grouped
        else:
            groups_iter = [(None, work)]

        for _voice, g in groups_iter:
            g2 = g.sort_values(["_onset", "_midi"], kind="mergesort")
            midis = g2["_midi"].round().astype(int).tolist()
            for a, b in zip(midis, midis[1:]):
                pairs_midi.append((a, b))

        if not pairs_midi:
            print(f"=== Successive Pitch Transitions ({lbl}) ===")
            print("Not enough notes to form successive transitions.")
            outputs.append({"label": lbl, "pitch_matrix": None, "pc_matrix": None})
            continue

        prev_m = pd.Series([a for a, _ in pairs_midi], name="prev_midi")
        next_m = pd.Series([b for _, b in pairs_midi], name="next_midi")

        mat_pitch = pd.crosstab(prev_m, next_m)

        # Optional pitch-limit (keep the most frequent pitch classes in transitions)
        if max_pitches is not None:
            try:
                k = int(max_pitches)
            except Exception:
                k = None
            if k is not None and k > 0:
                freq = pd.concat([prev_m, next_m]).value_counts()
                keep = set(freq.head(k).index.tolist())
                mat_pitch = mat_pitch.loc[[i for i in mat_pitch.index if i in keep], [c for c in mat_pitch.columns if c in keep]]

        # Make square for consistent axes
        all_midis = sorted(set(mat_pitch.index.tolist()) | set(mat_pitch.columns.tolist()))
        mat_pitch = mat_pitch.reindex(index=all_midis, columns=all_midis, fill_value=0)

        # Relabel MIDI -> pitch name
        idx_names = [midi_to_name(int(m)) or str(int(m)) for m in mat_pitch.index.tolist()]
        col_names = [midi_to_name(int(m)) or str(int(m)) for m in mat_pitch.columns.tolist()]
        mat_pitch_named = mat_pitch.copy()
        mat_pitch_named.index = idx_names
        mat_pitch_named.columns = col_names
        mat_pitch_named = _normalize_matrix(mat_pitch_named.astype(float), normalize_mode)

        # Pitch class matrix
        prev_pc = (prev_m % 12).astype(int)
        next_pc = (next_m % 12).astype(int)
        mat_pc = pd.crosstab(prev_pc, next_pc).reindex(index=list(range(12)), columns=list(range(12)), fill_value=0)
        mat_pc_named = mat_pc.copy()
        mat_pc_named.index = [_PC_TO_NOTE[i] for i in range(12)]
        mat_pc_named.columns = [_PC_TO_NOTE[i] for i in range(12)]
        mat_pc_named = _normalize_matrix(mat_pc_named.astype(float), normalize_mode)

        print(f"=== Successive Pitch Transitions ({lbl}) ===")
        if show_table:
            print("Absolute pitch transition matrix (rows=prev, cols=next):")
            ipy_display(_format_table_for_display(mat_pitch_named, float_format))
            print("Pitch-class transition matrix (rows=prev, cols=next):")
            ipy_display(_format_table_for_display(mat_pc_named, float_format))

        if normalize_mode is True:
            norm_tag = "row"
        elif normalize_mode is False or normalize_mode is None:
            norm_tag = "count"
        else:
            norm_tag = str(normalize_mode).strip().lower() or "count"
        pitch_title = f"Successive pitch transitions — {lbl} ({norm_tag})"
        pc_title = f"Successive pitch-class transitions — {lbl} ({norm_tag})"

        if backend_opt == "plt":
            _plt_heatmap(
                mat_pitch_named,
                title=pitch_title,
                x_label="Next pitch",
                y_label="Previous pitch",
                plot_width_=plot_width,
                plot_height_=plot_height_pitch,
                float_format_=float_format,
            )
            _plt_heatmap(
                mat_pc_named,
                title=pc_title,
                x_label="Next pitch class",
                y_label="Previous pitch class",
                plot_width_=plot_width,
                plot_height_=plot_height_pc,
                float_format_=float_format,
            )
        elif backend_opt == "bokeh":
            _bokeh_heatmap(
                mat_pitch_named,
                title=pitch_title,
                x_label="Next pitch",
                y_label="Previous pitch",
                plot_width_=plot_width,
                plot_height_=plot_height_pitch,
                show_hover_=bool(show_hover),
                float_format_=float_format,
            )
            _bokeh_heatmap(
                mat_pc_named,
                title=pc_title,
                x_label="Next pitch class",
                y_label="Previous pitch class",
                plot_width_=plot_width,
                plot_height_=plot_height_pc,
                show_hover_=bool(show_hover),
                float_format_=float_format,
            )
        elif backend_opt == "none":
            pass
        else:
            raise ValueError(f"Unsupported plotting backend: {backend}. Use 'plt', 'bokeh', or 'none'.")

        outputs.append({"label": lbl, "pitch_matrix": mat_pitch_named, "pc_matrix": mat_pc_named})

    return outputs


# --------------------------------------------------------------------
# Onset-position-within-measure histogram
# --------------------------------------------------------------------

_ONSET_DEFAULT_BAR_COLOR: Tuple[str, ...] = ('#4682B4', '#adf542')

_ONSET_PICKUP_TYPES = frozenset({'upbeat', 'pickup', 'anacrusis'})
_ONSET_NONCONFORMING_METCON = frozenset({'false', '0', 'no'})

_ONSET_COUNTS_COLUMNS = (
    'source',
    'meter_group',
    'time_signature_info',
    'measure_count',
    'total_distance_quarters',
    'measure_start_source',
    'measure_span_quarters',
    'measure_handling',
    'onset_within_measure',
    'count_raw',
    'share',
    'count',
)


def _onset_first_existing_column(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _onset_clean_meta(value: Any) -> str:
    if value is None:
        return ''
    try:
        if pd.isna(value):
            return ''
    except Exception:
        pass
    return str(value).strip().lower()


def _onset_meter_label(span: Any, float_format: Optional[str]) -> str:
    try:
        ql = float(span)
    except Exception:
        return 'unknown meter span'
    ql_text = _format_number_for_display(ql, float_format)
    if abs(ql - round(ql)) < 1e-6 and ql > 0:
        return f'~{int(round(ql))}/4 ({ql_text} quarter lengths)'
    eighths = ql * 2.0
    if abs(eighths - round(eighths)) < 1e-6 and eighths > 0:
        return f'~{int(round(eighths))}/8 ({ql_text} quarter lengths)'
    return f'{ql_text} quarter lengths'


def _onset_regular_span(spans: Sequence[Any]) -> float:
    import numpy as np
    clean = pd.Series([
        round(float(span), 6)
        for span in spans
        if pd.notna(span) and np.isfinite(float(span))
    ])
    if clean.empty:
        return float('nan')
    return float(clean.value_counts().idxmax())


def _onset_positive_min_step(values: Sequence[Any]) -> float:
    clean = sorted({round(float(v), 6) for v in values if pd.notna(v)})
    if len(clean) < 2:
        return float('nan')
    diffs = [round(b - a, 6) for a, b in zip(clean, clean[1:]) if b - a > 1e-6]
    return min(diffs) if diffs else float('nan')


def _onset_source_total_distance(reference_df: Optional[pd.DataFrame], starts: Sequence[float]) -> float:
    if reference_df is None or len(reference_df) == 0:
        return float('nan')
    global_col = _onset_first_existing_column(reference_df, ['Global Onset', 'global_onset', 'Onset'])
    duration_col = _onset_first_existing_column(reference_df, ['Duration', 'duration'])
    if global_col is None:
        return float('nan')
    onset = pd.to_numeric(reference_df[global_col], errors='coerce')
    if duration_col is not None:
        duration = pd.to_numeric(reference_df[duration_col], errors='coerce').fillna(0.0)
        end = (onset + duration).max()
    else:
        end = onset.max()
    if pd.isna(end):
        return float('nan')
    start = min(starts) if starts else onset.min()
    if pd.isna(start):
        return float('nan')
    return round(float(end - start), 6)


def _onset_fallback_measure_starts(reference_df: Optional[pd.DataFrame]) -> list[float]:
    if reference_df is None:
        return []
    measure_col = _onset_first_existing_column(reference_df, ['Measure', 'measure'])
    global_col = _onset_first_existing_column(reference_df, ['Global Onset', 'global_onset', 'Onset'])
    if measure_col is None or global_col is None:
        return []
    ref = reference_df[[measure_col, global_col]].copy()
    ref['_measure'] = pd.to_numeric(ref[measure_col], errors='coerce')
    ref['_global_onset'] = pd.to_numeric(ref[global_col], errors='coerce')
    ref = ref.dropna(subset=['_measure', '_global_onset'])
    if ref.empty:
        return []
    return sorted(ref.groupby('_measure')['_global_onset'].min().round(6).unique().tolist())


def _onset_resolve_measure_starts(
    reference_df: Optional[pd.DataFrame],
    measure_offsets: Optional[Sequence[Any]],
) -> Tuple[list[float], str]:
    import numpy as np
    if measure_offsets:
        clean: list[float] = []
        for value in measure_offsets:
            try:
                v = float(value)
            except Exception:
                continue
            if np.isfinite(v):
                clean.append(round(v, 6))
        if clean:
            return sorted(set(clean)), 'measure_offsets'
    fallback = _onset_fallback_measure_starts(reference_df)
    if fallback:
        return fallback, 'first_onset_per_measure'
    return [], 'unavailable'


def _onset_metadata_by_measure_start(
    events_df: Optional[pd.DataFrame],
    use_measure_metadata: bool,
) -> dict:
    if not use_measure_metadata or events_df is None or not isinstance(events_df, pd.DataFrame):
        return {}
    required = {'type', 'Global Onset'}
    if not required.issubset(set(events_df.columns)):
        return {}
    measures = events_df[events_df['type'].astype(str).str.lower() == 'measure'].copy()
    if measures.empty:
        return {}
    measures['_measure_start_key'] = pd.to_numeric(measures['Global Onset'], errors='coerce').round(6)
    measures = measures.dropna(subset=['_measure_start_key'])
    metadata: dict[float, dict[str, Any]] = {}
    for _, row in measures.iterrows():
        key = float(row['_measure_start_key'])
        metadata[key] = {
            'measure_type': row.get('measure_type', pd.NA),
            'measure_metcon': row.get('measure_metcon', pd.NA),
            'measure_join': row.get('measure_join', pd.NA),
            'measure_n': row.get('measure_n', pd.NA),
        }
    return metadata


def _onset_classify_measure(
    row: Mapping[str, Any],
    regular_span: float,
    first_measure_index: int,
    last_measure_index: int,
    edge_mode: str,
    use_measure_metadata: bool,
) -> str:
    span = row.get('measure_span_quarters', float('nan'))
    measure_type = _onset_clean_meta(row.get('measure_type'))
    metcon = _onset_clean_meta(row.get('measure_metcon'))
    measure_index = int(row.get('inferred_measure_index'))
    is_short = pd.notna(span) and pd.notna(regular_span) and float(span) < float(regular_span) - 1e-6
    is_nonconforming = metcon in _ONSET_NONCONFORMING_METCON
    is_pickup_type = measure_type in _ONSET_PICKUP_TYPES

    if is_short and measure_index == first_measure_index:
        if use_measure_metadata and (is_pickup_type or is_nonconforming):
            return 'pickup_right_aligned'
        if edge_mode == 'merge_to_regular':
            return 'pickup_right_aligned_inferred'
    if is_short and measure_index == last_measure_index:
        if use_measure_metadata and is_nonconforming:
            return 'incomplete_final_left_aligned'
        if edge_mode == 'merge_to_regular':
            return 'incomplete_final_left_aligned_inferred'
    if is_short and not (measure_index == first_measure_index or measure_index == last_measure_index):
        if edge_mode == 'merge_to_regular':
            return 'short_internal_merged'
        return 'short_internal_split_as_meter'
    return 'regular'


def _onset_pack_internal_runs(
    work: pd.DataFrame,
    regular_span: float,
) -> pd.DataFrame:
    """Offset onsets in runs of consecutive `short_internal_merged` measures so that
    they pack into a virtual regular-sized measure (e.g. a 3+1 split becomes 0..3)."""
    internal_merged_mask = work['measure_handling'] == 'short_internal_merged'
    if not internal_merged_mask.any() or pd.isna(regular_span):
        return work

    measure_info = (
        work[['inferred_measure_index', 'measure_span_quarters', 'measure_handling']]
        .drop_duplicates(subset='inferred_measure_index')
        .sort_values('inferred_measure_index')
        .reset_index(drop=True)
    )
    cumulative_offset: dict[int, float] = {}
    run_offset = 0.0
    prev_idx: Optional[int] = None
    prev_handling: Optional[str] = None
    prev_span = 0.0
    for _, info_row in measure_info.iterrows():
        idx = int(info_row['inferred_measure_index'])
        handling = info_row['measure_handling']
        span_value = float(info_row['measure_span_quarters']) if pd.notna(info_row['measure_span_quarters']) else 0.0
        if handling == 'short_internal_merged':
            if prev_handling == 'short_internal_merged' and prev_idx is not None and idx == prev_idx + 1:
                candidate = run_offset + prev_span
                if candidate + span_value > float(regular_span) + 1e-6:
                    candidate = 0.0
                run_offset = candidate
            else:
                run_offset = 0.0
            cumulative_offset[idx] = run_offset
        else:
            run_offset = 0.0
        prev_idx = idx
        prev_handling = handling
        prev_span = span_value

    offsets_series = (
        work.loc[internal_merged_mask, 'inferred_measure_index']
        .map(cumulative_offset)
        .astype(float)
    )
    work.loc[internal_merged_mask, 'onset_within_measure_raw'] = (
        work.loc[internal_merged_mask, 'onset_within_measure_raw'].astype(float) + offsets_series
    ).round(6)
    return work


def build_onset_position_counts(
    df: pd.DataFrame,
    *,
    label: str = 'Source',
    reference_df: Optional[pd.DataFrame] = None,
    events_df: Optional[pd.DataFrame] = None,
    measure_offsets: Optional[Sequence[Any]] = None,
    bin_size: float = 0.25,
    normalize: bool = True,
    edge_measure_mode: str = 'merge_to_regular',
    use_measure_metadata: bool = True,
    float_format: Optional[str] = None,
) -> Tuple[pd.DataFrame, dict]:
    """Compute an onset-within-measure histogram for a single source.

    Parameters
    ----------
    df : pandas.DataFrame
        Notes/pitches DataFrame (must contain a `Global Onset` column).
    label : str
        Label used to identify the source in the returned counts table.
    reference_df : pandas.DataFrame, optional
        Full source DataFrame used as a reference for measure-start fallback
        and total-distance computation. Defaults to `df`.
    events_df : pandas.DataFrame, optional
        Events DataFrame containing `type='measure'` rows with `measure_type`,
        `measure_metcon`, `measure_join`, `measure_n` metadata. Used when
        `use_measure_metadata` is True.
    measure_offsets : sequence of float, optional
        Pre-parsed barline offsets (e.g. `result['measure_offsets']`). Preferred
        over inferring measure starts from the DataFrame.
    bin_size : float
        Rhythmic grid in quarter lengths (e.g. 0.25 for sixteenth notes).
    normalize : bool
        When True the `count` column holds proportions per (source, meter_group).
    edge_measure_mode : {'merge_to_regular', 'split_by_span'}
        How to handle short edge / split-internal measures. With
        `merge_to_regular`, pickups are right-aligned, incomplete finals
        left-aligned, and runs of consecutive short internal measures are
        packed into a virtual regular-sized measure.
    use_measure_metadata : bool
        When True, MEI measure metadata in `events_df` is consulted to detect
        pickups and incomplete final measures.
    float_format : str or None
        Optional Python-style float format for the meter group label.

    Returns
    -------
    counts : pandas.DataFrame
        Long-form histogram with one row per (meter_group, onset_within_measure).
    summary : dict
        Diagnostic summary with measure-start source, regular span, warnings,
        and a per-measure debug DataFrame.
    """
    import numpy as np

    edge_mode = str(edge_measure_mode).strip().lower()
    if edge_mode not in {'merge_to_regular', 'split_by_span'}:
        raise ValueError("edge_measure_mode must be 'merge_to_regular' or 'split_by_span'.")

    global_col = _onset_first_existing_column(df, ['Global Onset', 'global_onset', 'Onset'])
    if global_col is None:
        raise ValueError(f'{label}: no Global Onset column found.')

    if reference_df is None:
        reference_df = df
    starts, start_source = _onset_resolve_measure_starts(reference_df, measure_offsets)
    if not starts:
        raise ValueError(f'{label}: could not determine measure starts.')

    metadata_by_start = _onset_metadata_by_measure_start(events_df, use_measure_metadata)
    starts_arr = np.array(starts, dtype=float)
    source_distance = _onset_source_total_distance(reference_df, starts)
    spans_arr = np.diff(starts_arr) if len(starts_arr) > 1 else np.array([], dtype=float)
    if starts and pd.notna(source_distance):
        source_end = float(min(starts)) + float(source_distance)
        if source_end > float(starts_arr[-1]) + 1e-6:
            spans_arr = np.append(spans_arr, round(source_end - float(starts_arr[-1]), 6))
    regular_span = _onset_regular_span(spans_arr)

    empty = pd.DataFrame(columns=list(_ONSET_COUNTS_COLUMNS))

    work = df.copy()
    work['_global_onset'] = pd.to_numeric(work[global_col], errors='coerce')
    work = work.dropna(subset=['_global_onset'])
    if work.empty:
        return empty, {}

    onset_values = work['_global_onset'].to_numpy(dtype=float)
    measure_idx = np.searchsorted(starts_arr, onset_values, side='right') - 1
    valid = measure_idx >= 0
    if len(spans_arr):
        valid = valid & (measure_idx < len(spans_arr))
    work = work.loc[valid].copy()
    measure_idx = measure_idx[valid]
    onset_values = onset_values[valid]
    if work.empty:
        return empty, {}

    work['inferred_measure_index'] = measure_idx + 1
    work['inferred_measure_start'] = starts_arr[measure_idx]
    work['onset_within_measure_raw'] = (onset_values - starts_arr[measure_idx]).round(6)
    work.loc[work['onset_within_measure_raw'].abs() < 1e-6, 'onset_within_measure_raw'] = 0.0
    if len(spans_arr):
        work['measure_span_quarters'] = np.round(spans_arr[measure_idx], 6)
    else:
        work['measure_span_quarters'] = np.nan

    meta_rows = (
        work['inferred_measure_start']
        .round(6)
        .map(metadata_by_start)
        .map(lambda value: value if isinstance(value, dict) else {})
    )
    work['measure_type'] = meta_rows.map(lambda v: v.get('measure_type', pd.NA))
    work['measure_metcon'] = meta_rows.map(lambda v: v.get('measure_metcon', pd.NA))
    work['measure_join'] = meta_rows.map(lambda v: v.get('measure_join', pd.NA))
    work['measure_n'] = meta_rows.map(lambda v: v.get('measure_n', pd.NA))

    first_measure_index = int(np.nanmin(work['inferred_measure_index']))
    last_measure_index = int(np.nanmax(work['inferred_measure_index']))
    work['measure_handling'] = work.apply(
        lambda row: _onset_classify_measure(
            row, regular_span, first_measure_index, last_measure_index, edge_mode, use_measure_metadata,
        ),
        axis=1,
    )

    pickup_mask = work['measure_handling'].astype(str).str.startswith('pickup_right_aligned')
    if pickup_mask.any() and pd.notna(regular_span):
        work.loc[pickup_mask, 'onset_within_measure_raw'] = (
            work.loc[pickup_mask, 'onset_within_measure_raw']
            + (float(regular_span) - work.loc[pickup_mask, 'measure_span_quarters'].astype(float))
        ).round(6)

    work = _onset_pack_internal_runs(work, regular_span)

    step = float(bin_size)
    smallest_onset_step = _onset_positive_min_step(work['onset_within_measure_raw'])
    bin_warning: Optional[str] = None
    if pd.notna(smallest_onset_step) and step > float(smallest_onset_step) + 1e-9:
        bin_warning = (
            f"Warning: bin_size={step:g} is coarser than the smallest detected "
            f"onset-position step in {label!r} ({smallest_onset_step:g}). Some positions will be merged."
        )

    work['onset_within_measure'] = ((work['onset_within_measure_raw'] / step).round() * step).round(6)

    display_span = work['measure_span_quarters'].copy()
    edge_mask = work['measure_handling'].astype(str).str.startswith(
        ('pickup_right_aligned', 'incomplete_final_left_aligned', 'short_internal_merged')
    )
    if edge_mode == 'merge_to_regular' and pd.notna(regular_span):
        display_span = display_span.mask(edge_mask, float(regular_span))
    work['display_span_quarters'] = display_span
    work['meter_group'] = work['display_span_quarters'].map(
        lambda value: _onset_meter_label(value, float_format) if pd.notna(value) else 'unknown meter span'
    )

    represented_meter_groups = work['meter_group'].dropna().unique().tolist()
    multi_meter_warning: Optional[str] = None
    if len(represented_meter_groups) > 1:
        multi_meter_warning = (
            f"Warning: {label!r} contains multiple inferred measure spans/time signatures after "
            f"metadata handling: {', '.join(str(group) for group in represented_meter_groups)}. "
            'Histograms will be drawn separately by time signature.'
        )

    measure_debug = (
        work.groupby('inferred_measure_index', dropna=False)
        .agg(
            measure_start=('inferred_measure_start', 'first'),
            measure_span_quarters=('measure_span_quarters', 'first'),
            display_span_quarters=('display_span_quarters', 'first'),
            measure_handling=('measure_handling', 'first'),
            measure_type=('measure_type', 'first'),
            measure_metcon=('measure_metcon', 'first'),
            measure_join=('measure_join', 'first'),
            measure_n=('measure_n', 'first'),
            first_onset_within_measure=('onset_within_measure', 'min'),
            last_onset_within_measure=('onset_within_measure', 'max'),
            onset_count=('onset_within_measure', 'size'),
        )
        .reset_index()
    )

    metadata_hits = int(
        work[['measure_type', 'measure_metcon', 'measure_join', 'measure_n']]
        .notna()
        .any(axis=1)
        .sum()
    )

    counts = (
        work.groupby(['meter_group', 'onset_within_measure'], dropna=False)
        .size()
        .rename('count_raw')
        .reset_index()
        .sort_values(['meter_group', 'onset_within_measure'])
        .reset_index(drop=True)
    )
    counts.insert(0, 'source', label)

    measure_counts = work.groupby('meter_group')['inferred_measure_index'].nunique().to_dict()
    span_values = work.groupby('meter_group')['display_span_quarters'].first().to_dict()
    handling_values = (
        work.groupby('meter_group')['measure_handling']
        .apply(lambda values: ', '.join(sorted({str(v) for v in values})))
        .to_dict()
    )
    counts.insert(2, 'time_signature_info', counts['meter_group'])
    counts.insert(3, 'measure_count', counts['meter_group'].map(measure_counts).astype(int))
    counts.insert(4, 'total_distance_quarters', source_distance)
    counts.insert(5, 'measure_start_source', start_source)
    counts.insert(6, 'measure_span_quarters', counts['meter_group'].map(span_values))
    counts.insert(7, 'measure_handling', counts['meter_group'].map(handling_values))
    counts['share'] = counts.groupby(['source', 'meter_group'])['count_raw'].transform(
        lambda series: series / series.sum()
    )
    counts['count'] = counts['share'] if normalize else counts['count_raw']

    measure_metadata_rows = 0
    if events_df is not None and isinstance(events_df, pd.DataFrame):
        type_series = events_df.get('type', pd.Series(dtype=object))
        measure_metadata_rows = int((type_series.astype(str).str.lower() == 'measure').sum())

    summary = {
        'label': label,
        'measure_start_source': start_source,
        'total_distance_quarters': source_distance,
        'meter_groups': represented_meter_groups,
        'smallest_onset_step': smallest_onset_step,
        'regular_span_quarters': regular_span,
        'measure_metadata_rows': measure_metadata_rows,
        'measure_metadata_note_hits': metadata_hits,
        'measure_handling': sorted({str(v) for v in work['measure_handling'].dropna().tolist()}),
        'edge_measure_mode': edge_mode,
        'bin_size': step,
        'normalize': bool(normalize),
        'measure_debug': measure_debug,
        'bin_warning': bin_warning,
        'multi_meter_warning': multi_meter_warning,
    }
    return counts, summary


def _onset_resolve_source_metadata(
    source_dfs: Sequence[pd.DataFrame],
    *,
    dfs_by_name: Optional[Mapping[str, pd.DataFrame]] = None,
    results: Optional[Sequence[Mapping[str, Any]]] = None,
    selection: Optional[pd.DataFrame] = None,
    full_df: Optional[pd.DataFrame] = None,
) -> Tuple[list[Optional[pd.DataFrame]], list[Optional[pd.DataFrame]], list[Optional[list[float]]]]:
    """Best-effort resolution of `(reference_df, events_df, measure_offsets)` per
    source by inspecting the standard parsed-result structures used by the
    notebook tutorials (`dfs_by_name`, `results`, `selection`, full source DF).
    """
    refs: list[Optional[pd.DataFrame]] = []
    events: list[Optional[pd.DataFrame]] = []
    offsets: list[Optional[list[float]]] = []
    for df in source_dfs:
        ref = df
        if selection is not None and full_df is not None and df is selection:
            ref = full_df
        result_name: Optional[str] = None
        if dfs_by_name is not None:
            for key, value in dfs_by_name.items():
                if key.endswith('_pitch') and value is ref:
                    result_name = key[:-6]
                    break
        ev_df: Optional[pd.DataFrame] = None
        offs: Optional[list[float]] = None
        if result_name and results is not None:
            for result in results:
                if result.get('name') == result_name:
                    candidate = result.get('df_events')
                    if isinstance(candidate, pd.DataFrame):
                        ev_df = candidate
                    raw_offsets = result.get('measure_offsets') or []
                    if raw_offsets:
                        offs = list(raw_offsets)
                    break
        if ev_df is None and result_name and dfs_by_name is not None:
            candidate = dfs_by_name.get(f'{result_name}_events')
            if isinstance(candidate, pd.DataFrame):
                ev_df = candidate
        refs.append(ref)
        events.append(ev_df)
        offsets.append(offs)
    return refs, events, offsets


def display_onset_position_histogram(
    source_df: Union[pd.DataFrame, Sequence[pd.DataFrame]],
    *more_source_dfs: pd.DataFrame,
    source_labels: Optional[Sequence[str]] = None,
    reference_dfs: Optional[Sequence[Optional[pd.DataFrame]]] = None,
    events_dfs: Optional[Sequence[Optional[pd.DataFrame]]] = None,
    measure_offsets: Optional[Sequence[Optional[Sequence[Any]]]] = None,
    dfs_by_name: Optional[Mapping[str, pd.DataFrame]] = None,
    results: Optional[Sequence[Mapping[str, Any]]] = None,
    selection: Optional[pd.DataFrame] = None,
    full_df: Optional[pd.DataFrame] = None,
    bin_size: float = 0.25,
    normalize: bool = True,
    edge_measure_mode: str = 'merge_to_regular',
    use_measure_metadata: bool = True,
    backend: str = 'bokeh',
    plot_width: int = 1200,
    plot_height: int = 350,
    show_hover: bool = True,
    show_table: bool = True,
    show_measure_debug: bool = True,
    bar_color: Union[str, Sequence[str]] = _ONSET_DEFAULT_BAR_COLOR,
    float_format: Optional[str] = None,
) -> Union[pd.DataFrame, Mapping[str, pd.DataFrame]]:
    """Build and display an onset-within-measure histogram for one or more sources.

    Per-source measurement metadata can either be passed explicitly via
    `reference_dfs` / `events_dfs` / `measure_offsets`, or auto-resolved by
    inspecting the notebook's `dfs_by_name`, `results`, `selection`, and
    full-source DataFrame (`full_df`, typically `SOURCE_DF`).

    With `edge_measure_mode='merge_to_regular'`:
      - Pickup measures are right-aligned into the regular grid.
      - Incomplete final measures are left-aligned.
      - Consecutive short internal measures whose spans sum to the regular span
        are packed into a single virtual regular measure.

    Returns the counts DataFrame for a single source, or a dict mapping label
    to counts DataFrame for multiple sources.
    """
    if not more_source_dfs and not isinstance(source_df, pd.DataFrame):
        if isinstance(source_df, (list, tuple)):
            dfs = list(source_df)
        else:
            dfs = [source_df]
    else:
        dfs = [source_df] + list(more_source_dfs)

    n_sources = len(dfs)
    if source_labels is not None:
        labels = list(source_labels)[:n_sources]
        if len(labels) < n_sources:
            labels.extend(_guess_labels_for_dfs(dfs[len(labels):], default_prefix='Source'))
    else:
        labels = _guess_labels_for_dfs(dfs, default_prefix='Source')

    needs_resolve = reference_dfs is None or events_dfs is None or measure_offsets is None
    if needs_resolve:
        auto_refs, auto_events, auto_offsets = _onset_resolve_source_metadata(
            dfs,
            dfs_by_name=dfs_by_name,
            results=results,
            selection=selection,
            full_df=full_df,
        )
    else:
        auto_refs = [None] * n_sources
        auto_events = [None] * n_sources
        auto_offsets = [None] * n_sources

    def _pick(seq, fallback):
        if seq is None:
            return list(fallback)
        chosen = list(seq)[:n_sources]
        chosen.extend(fallback[len(chosen):])
        return chosen

    refs_list = _pick(reference_dfs, auto_refs)
    events_list = _pick(events_dfs, auto_events)
    offsets_list = _pick(measure_offsets, auto_offsets)

    counts_by_label: dict[str, pd.DataFrame] = {}
    summaries: dict[str, dict] = {}

    for label, df, ref, ev, offs in zip(labels, dfs, refs_list, events_list, offsets_list):
        counts, summary = build_onset_position_counts(
            df,
            label=label,
            reference_df=ref if ref is not None else df,
            events_df=ev,
            measure_offsets=offs,
            bin_size=bin_size,
            normalize=normalize,
            edge_measure_mode=edge_measure_mode,
            use_measure_metadata=use_measure_metadata,
            float_format=float_format,
        )
        counts_by_label[label] = counts
        summaries[label] = summary

        if summary.get('bin_warning'):
            print(summary['bin_warning'])
        if summary.get('multi_meter_warning'):
            print(summary['multi_meter_warning'])

        if show_table:
            print(f'=== Onset Position Histogram ({label}) ===')
            represented_total = (
                int(counts[['meter_group', 'measure_count']].drop_duplicates()['measure_count'].sum())
                if len(counts)
                else 0
            )
            print(f'Measures represented: {represented_total}')
            print(f"Measure start source: {summary.get('measure_start_source', 'unavailable')}")
            print(f"Time signature / measure span(s): {', '.join(summary.get('meter_groups') or ['unknown'])}")
            print(
                'Regular inferred span: '
                f"{_format_number_for_display(summary.get('regular_span_quarters'), float_format)} quarter lengths"
            )
            print(
                'Total loaded-source distance: '
                f"{_format_number_for_display(summary.get('total_distance_quarters'), float_format)} quarter lengths"
            )
            print(f"MEI measure metadata rows: {summary.get('measure_metadata_rows', 0)}")
            print(f"Edge measure mode: {summary.get('edge_measure_mode', 'unknown')}")
            print(f"Metadata-informed handling: {', '.join(summary.get('measure_handling') or ['none'])}")
            smallest_step = summary.get('smallest_onset_step', float('nan'))
            if pd.notna(smallest_step):
                print(
                    'Smallest detected onset-position step: '
                    f'{_format_number_for_display(smallest_step, float_format)} quarter lengths'
                )
            debug_df = summary.get('measure_debug')
            if show_measure_debug and isinstance(debug_df, pd.DataFrame) and len(debug_df):
                print('Measure handling debug:')
                try:
                    ipy_display(_format_table_for_display(debug_df, float_format))
                except Exception:
                    print(_format_table_for_display(debug_df, float_format))
            if len(counts):
                table_cols = [
                    'source', 'time_signature_info', 'measure_count',
                    'total_distance_quarters', 'measure_start_source',
                    'measure_handling', 'onset_within_measure',
                    'count_raw', 'share', 'count',
                ]
                table_df = counts[table_cols].copy()
                try:
                    ipy_display(_format_table_for_display(table_df, float_format))
                except Exception:
                    print(_format_table_for_display(table_df, float_format))

    if summaries:
        all_meter_groups = sorted(set().union(*[set(s.get('meter_groups') or []) for s in summaries.values()]))
        if len(all_meter_groups) > 1:
            print(
                'Warning: selected sources include multiple inferred time signatures/measure spans: '
                + ', '.join(all_meter_groups)
                + '. Combined histograms will be split by time signature.'
            )

    backend_opt = (backend or 'bokeh').strip().lower()
    if backend_opt != 'none' and counts_by_label:
        meter_groups_in_counts = sorted(set().union(*[
            set(df['meter_group'].dropna().tolist())
            for df in counts_by_label.values()
        ]))
        for meter_group in meter_groups_in_counts:
            group_counts = {
                lab: df[df['meter_group'] == meter_group].copy()
                for lab, df in counts_by_label.items()
            }
            group_counts = {lab: df for lab, df in group_counts.items() if not df.empty}
            if not group_counts:
                continue
            active_labels = [lab for lab in labels if lab in group_counts]
            categories = sorted(set().union(*[
                set(df['onset_within_measure'].tolist())
                for df in group_counts.values()
            ]))
            x_labels = [f'{float(value):.3g}' for value in categories]
            title = f'Onset Position Histogram - {meter_group}'
            if len(meter_groups_in_counts) > 1:
                print(f'Drawing separate combined plot for {meter_group}.')
            series_values: list[list[float]] = []
            for lab in active_labels:
                indexed = group_counts[lab].set_index('onset_within_measure')['count']
                series_values.append([float(indexed.get(value, 0.0)) for value in categories])
            _plot_multi_bar(
                categories=x_labels,
                series_values=series_values,
                series_labels=active_labels,
                title=title,
                x_label='Onset within Measure (quarter lengths)',
                y_label=('Proportion' if normalize else 'Count'),
                backend=backend_opt,
                plot_width=plot_width,
                plot_height=plot_height,
                show_hover=bool(show_hover),
                bar_color=bar_color,
                default_palette=_DEFAULT_PITCH_PALETTE,
                float_format=float_format,
            )

    if len(counts_by_label) == 1:
        return next(iter(counts_by_label.values()))
    return counts_by_label


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
    'check_monophonic_input',
    'melodic_interval_distribution',
    'display_melodic_interval_distribution',
    'display_successive_pitch_transition_heatmaps',
    'build_onset_position_counts',
    'display_onset_position_histogram',
]
