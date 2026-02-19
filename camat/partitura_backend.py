from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union, Sequence

import numpy as np
import pandas as pd


def _ensure_pkg_resources_shim() -> None:
    """
    Provide the tiny subset of pkg_resources functionality that partitura needs
    without importing the real (deprecated) pkg_resources module.
    """
    if "pkg_resources" in sys.modules:
        return
    try:
        from importlib import metadata as _metadata
        from importlib import resources as _resources
    except Exception:  # pragma: no cover - fallback: real pkg_resources will be used
        return

    class _Distribution:
        __slots__ = ("_name",)

        def __init__(self, name: str) -> None:
            self._name = name

        @property
        def version(self) -> str:
            return _metadata.version(self._name)

    def _get_distribution(dist_name: str) -> _Distribution:
        return _Distribution(dist_name)

    def _resource_filename(package: str, resource: str) -> str:
        ref = _resources.files(package).joinpath(resource)
        with _resources.as_file(ref) as path:
            return str(path)

    shim = types.ModuleType("pkg_resources")
    shim.get_distribution = _get_distribution  # type: ignore[attr-defined]
    shim.resource_filename = _resource_filename  # type: ignore[attr-defined]
    shim.DistributionNotFound = _metadata.PackageNotFoundError  # type: ignore[attr-defined]
    shim.PackageNotFoundError = _metadata.PackageNotFoundError  # type: ignore[attr-defined]
    sys.modules["pkg_resources"] = shim


_ensure_pkg_resources_shim()

try:  # pragma: no cover - optional dependency
    import partitura as pt
    from partitura.io import importkern, importmusicxml
except ImportError as exc:  # pragma: no cover - handled at runtime
    raise ImportError(
        "The 'partitura' package is required for the partitura backend. "
        "Install it with `pip install partitura`."
    ) from exc

from .music_utils import (  # type: ignore
    draw_piano_roll,
    filter_and_adjust_durations,
    get_file_path,
    canonicalize_pitch_name,
    accidental_rank_from_name,
)
from .mensural_utils import (
    DEFAULT_MENSURAL_DURATION_MAP,
    DEFAULT_METER_COUNT,
    DEFAULT_METER_UNIT,
    normalize_mensural_mei_for_partitura_text,
)

try:  # pragma: no cover - optional dependency
    from tqdm.auto import tqdm as _tqdm
except Exception:  # pragma: no cover
    _tqdm = None

__all__ = ["partitura_score_to_dataframe", "parse_files_partitura"]

_PITCH_CLASS_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_TEXTUAL_EXTENSIONS = {".xml", ".musicxml", ".mei", ".krn", ".kern", ".hum"}
_MENSURAL_DURATION_TOKENS = set(DEFAULT_MENSURAL_DURATION_MAP.keys())


def _midi_to_pitch_name(midi: int) -> str:
    """
    Convert MIDI pitch number to a textual pitch name (e.g., 60 -> C4).
    """
    octave = (midi // 12) - 1
    pc = _PITCH_CLASS_NAMES[midi % 12]
    return f"{pc}{octave}"


def _exception_chain_text(exc: BaseException) -> str:
    parts: List[str] = []
    seen: set[int] = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        try:
            msg = str(cur)
        except Exception:
            msg = repr(cur)
        parts.append(msg)
        cur = cur.__cause__ if cur.__cause__ is not None else cur.__context__
    return " | ".join(parts).lower()


def _is_mensural_duration_error(exc: BaseException) -> bool:
    if isinstance(exc, KeyError):
        try:
            key = str(exc).strip("'\"").lower()
        except Exception:
            key = ""
        if key in _MENSURAL_DURATION_TOKENS:
            return True
    text = _exception_chain_text(exc)
    return any(token in text for token in _MENSURAL_DURATION_TOKENS)


def _is_missing_time_signature_error(exc: BaseException) -> bool:
    return "time signature is not encoded" in _exception_chain_text(exc)


def _is_partitura_unsupported_mei_structure_error(exc: BaseException) -> bool:
    text = _exception_chain_text(exc)
    return "is not yet supported" in text and "element" in text


def _convert_mei_with_verovio_for_partitura(
    source_path: str,
    *,
    mensural_to_cmn: bool = True,
    duration_equivalence: Optional[float] = None,
    mensural_score_up: bool = False,
) -> Tuple[str, Optional[Callable[[], None]], int, int]:
    """
    Convert MEI to a partitura-friendlier MEI with a local Verovio toolkit instance.

    Returns a temporary file path and cleanup callback.
    """
    try:
        import verovio  # type: ignore
    except Exception as exc:
        raise RuntimeError("verovio is required for MEI structure conversion") from exc

    with open(source_path, "r", encoding="utf-8", errors="ignore") as f:
        mei_text = f.read()

    options: Dict[str, Any] = {
        "inputFrom": "mei",
        "outputFormatRaw": True,
        "removeIds": False,
        "mensuralToCmn": bool(mensural_to_cmn),
    }
    if duration_equivalence is not None:
        duration_equivalence_value = float(duration_equivalence)
        if not np.isfinite(duration_equivalence_value) or duration_equivalence_value <= 0:
            raise ValueError("duration_equivalence must be a finite positive number")
        options["durationEquivalence"] = duration_equivalence_value
    if mensural_score_up:
        options["mensuralScoreUp"] = True

    tk = verovio.toolkit()
    tk.setOptions(options)
    tk.loadData(mei_text)
    converted_mei = tk.getMEI()
    if not isinstance(converted_mei, str) or not converted_mei.strip():
        raise RuntimeError("Verovio conversion returned empty MEI data")

    converted_mei, removed_annots, wrapped_staff_groups = _postprocess_mei_for_partitura(
        converted_mei
    )

    tmp = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".mei")
    try:
        tmp.write(converted_mei)
    finally:
        tmp.close()

    def _cleanup() -> None:
        try:
            os.remove(tmp.name)
        except OSError:
            pass

    return tmp.name, _cleanup, removed_annots, wrapped_staff_groups


def _postprocess_mei_for_partitura(mei_text: str) -> Tuple[str, int, int]:
    """
    Post-process MEI text for better partitura compatibility.

    - Remove unsupported <annot> elements.
    - Wrap section-level <staff> runs into synthetic <measure> elements.

    Returns:
        (updated_mei_text, removed_annot_count, wrapped_staff_group_count)
    """
    try:
        from lxml import etree  # type: ignore
    except Exception:
        import re

        no_annot = re.sub(r"<annot\\b[^>]*>.*?</annot>", "", mei_text, flags=re.DOTALL)
        no_annot = re.sub(r"<annot\\b[^>]*/>", "", no_annot)
        removed = 1 if no_annot != mei_text else 0
        return no_annot, removed, 0

    parser = etree.XMLParser(recover=True, remove_blank_text=False, huge_tree=True)
    root = etree.fromstring(mei_text.encode("utf-8", errors="ignore"), parser=parser)
    ns = etree.QName(root.tag).namespace

    def _lname(el: Any) -> str:
        try:
            return etree.QName(el.tag).localname
        except Exception:
            return str(el.tag)

    def _tag(local: str) -> str:
        return f"{{{ns}}}{local}" if ns else local

    removed_annot = 0
    for annot_el in root.xpath(".//*[local-name()='annot']"):
        parent = annot_el.getparent()
        if parent is None:
            continue
        parent.remove(annot_el)
        removed_annot += 1

    wrapped_staff_groups = 0
    for section_el in root.xpath(".//*[local-name()='section']"):
        original_children = list(section_el)
        if not original_children:
            continue

        # continue numbering after existing numeric measure labels
        existing_numbers: List[int] = []
        for ch in original_children:
            if _lname(ch) != "measure":
                continue
            n_val = ch.get("n")
            if n_val is None:
                continue
            try:
                existing_numbers.append(int(str(n_val)))
            except Exception:
                continue
        next_measure_number = (max(existing_numbers) + 1) if existing_numbers else 1

        new_children: List[Any] = []
        i = 0
        while i < len(original_children):
            child = original_children[i]
            if _lname(child) != "staff":
                new_children.append(child)
                i += 1
                continue

            measure_el = etree.Element(_tag("measure"))
            measure_el.set("n", str(next_measure_number))
            next_measure_number += 1

            while i < len(original_children) and _lname(original_children[i]) == "staff":
                measure_el.append(original_children[i])
                i += 1

            new_children.append(measure_el)
            wrapped_staff_groups += 1

        if new_children != original_children:
            section_el[:] = new_children

    out = etree.tostring(root, encoding="unicode")
    return out, removed_annot, wrapped_staff_groups


def _looks_mensural_mei_text(mei_text: str) -> bool:
    """
    Heuristic detector for mensural MEI content.
    """
    import re

    text = (mei_text or "").lower()
    if "<mensur" in text:
        return True
    if re.search(
        r"\b(?:tempus|prolatio|modusmaior|modusminor)\s*=\s*['\"][^'\"]+['\"]",
        text,
    ):
        return True
    if re.search(
        r"\bdur\s*=\s*['\"](?:maxima|longa?|brevis|semibrevis|minima|semiminima|fusa|semifusa)['\"]",
        text,
    ):
        return True
    return False


def _file_looks_mensural_mei(path: str) -> bool:
    if Path(path).suffix.lower() != ".mei":
        return False
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return _looks_mensural_mei_text(text)


def _slugify_name(text: str) -> str:
    """
    Convert text to a filesystem-friendly slug: lowercase, alphanumeric and underscores.
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
        base = base.split("?")[0].split("#")[0]
    stem, _ = os.path.splitext(base)
    return f"{index:02d}_" + _slugify_name(stem)


def _format_voice_label(part_label: str, voice: Union[int, str, None]) -> str:
    """
    Produce a human-readable voice label combining part information with voice index.
    """
    base = part_label.strip() if part_label else ""
    if voice is None or (isinstance(voice, (int, float)) and int(voice) < 0):
        return base or "Voice"
    try:
        voice_int = int(voice)
        if voice_int < 0:
            raise ValueError
        voice_suffix = f"Voice {voice_int}"
    except Exception:
        voice_suffix = str(voice).strip()
    if not base:
        return voice_suffix
    if not voice_suffix:
        return base
    return f"{base} - {voice_suffix}"


def _sanitize_source_for_partitura(
    source_path: str,
    *,
    normalize_mensural_durations: bool = False,
    inject_missing_meter_signature: bool = False,
    default_meter_count: int = DEFAULT_METER_COUNT,
    default_meter_unit: int = DEFAULT_METER_UNIT,
) -> Tuple[str, Optional[Callable[[], None]], int, int]:
    """
    Clean up textual score files before feeding them into partitura to avoid parser warnings.

    Returns:
        path_to_use, optional_cleanup_callback, mensural_replacement_count, meter_injection_count
    """
    path = Path(source_path)
    suffix = path.suffix.lower()
    if suffix not in _TEXTUAL_EXTENSIONS or not path.exists():
        return source_path, None, 0, 0

    try:
        original_text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return source_path, None, 0, 0

    text = original_text.lstrip("\ufeff")

    # Drop leading empty lines to keep numpy/genfromtxt happy.
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)

    if suffix in {".krn", ".kern", ".hum"}:
        while lines and lines[0].lstrip().startswith("!"):
            lines.pop(0)
        cleaned: List[str] = []
        for line in lines:
            tokens = [tok for tok in line.split("\t") if tok]
            if tokens and all(tok.startswith("*part") for tok in tokens):
                continue
            cleaned.append(line)
        lines = cleaned

    if original_text.endswith(("\r", "\n")):
        trailing_newline = "\n"
    else:
        trailing_newline = ""

    sanitized = "\n".join(lines) + trailing_newline
    filtered = "".join(
        ch for ch in sanitized if not (0xF000 <= ord(ch) <= 0xF8FF)
    )
    if filtered != sanitized:
        sanitized = filtered

    mensural_replacement_count = 0
    meter_injection_count = 0
    is_mensural_mei = suffix == ".mei" and _looks_mensural_mei_text(sanitized)
    if is_mensural_mei and (normalize_mensural_durations or inject_missing_meter_signature):
        # Keep mensural preprocessing isolated from common-notation MEI.
        sanitized, mensural_replacement_count, _, meter_injection_count = (
            normalize_mensural_mei_for_partitura_text(
                sanitized,
                meter_count=default_meter_count,
                meter_unit=default_meter_unit,
            )
        )
        if not normalize_mensural_durations:
            mensural_replacement_count = 0
        if not inject_missing_meter_signature:
            meter_injection_count = 0

    if sanitized == original_text:
        return source_path, None, mensural_replacement_count, meter_injection_count

    tmp = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=suffix)
    try:
        tmp.write(sanitized)
    finally:
        tmp.close()

    def _cleanup() -> None:
        try:
            os.remove(tmp.name)
        except OSError:
            pass

    return tmp.name, _cleanup, mensural_replacement_count, meter_injection_count


def _load_partitura_score(file_path: str):
    suffix = Path(file_path).suffix.lower()
    if suffix in {".krn", ".kern"}:
        return importkern.load_kern(file_path, force_same_part=True)
    if suffix == ".xml":
        try:
            return importmusicxml.load_musicxml(file_path)
        except Exception:
            # Fallback to the generic loader if load_musicxml fails.
            return pt.load_score(file_path)
    return pt.load_score(file_path)


def _part_to_rows(part, *, parse_enharmonic: bool = False, include_xml_ids: bool = False) -> List[Dict[str, Any]]:
    """
    Convert a single partitura Part into a list of row dictionaries compatible with CAMAT dataframes.
    """
    rows: List[Dict[str, Any]] = []
    note_array = part.note_array(
        include_metrical_position=True, include_divs_per_quarter=True
    )
    if note_array.size == 0:
        return rows

    measure_map = part.measure_map
    quarter_map = part.quarter_map
    measure_number_map = part.measure_number_map
    part_label = (
        getattr(part, "part_name", None)
        or getattr(part, "name", None)
        or getattr(part, "id", None)
        or ""
    )

    fields = set(note_array.dtype.names or ())
    has_divs = "divs_pq" in fields
    has_rel = "rel_onset_div" in fields
    has_voice = "voice" in fields

    # Build lookup maps for enharmonic spelling
    id_to_spelling: Dict[Any, str] = {}
    spelled_sequence: List[str] = []

    if parse_enharmonic:
        try:
            # Collect all note info first
            note_info = []
            for n in getattr(part, "notes", []):
                step = getattr(n, "step", None)
                octave = getattr(n, "octave", None)
                alter = getattr(n, "alter", None)
                if alter is None:
                    acc_name = str(getattr(n, "accidental", "") or "").lower()
                    if acc_name:
                        if acc_name in {"sharp", "sharp1"}:
                            alter = 1
                        elif acc_name in {"flat", "flat1"}:
                            alter = -1
                        elif acc_name in {"double-sharp", "sharp2"}:
                            alter = 2
                        elif acc_name in {"double-flat", "flat2"}:
                            alter = -2
                        else:
                            alter = 0

                acc = ""
                try:
                    a = int(round(float(alter))) if alter is not None else 0
                except Exception:
                    a = 0
                if a > 0:
                    acc = "#" * a
                elif a < 0:
                    acc = "b" * (-a)

                spelled = None
                if step is not None and octave is not None:
                    spelled = f"{str(step).upper()}{acc}{int(octave)}"

                if spelled:
                    # ID lookup
                    nid = getattr(n, "id", None) or getattr(n, "xml_id", None)
                    if nid is not None:
                        id_to_spelling[nid] = spelled

                    # Sorting info
                    start_t = getattr(getattr(n, "start", None), "t", 0)
                    midi_p = getattr(n, "midi_pitch", 0)
                    note_info.append((start_t, midi_p, spelled))

            # Sort by onset then pitch to match note_array order
            note_info.sort(key=lambda x: (x[0], x[1]))
            spelled_sequence = [x[2] for x in note_info]

        except Exception:
            id_to_spelling = {}
            spelled_sequence = []

    spelled_idx = 0
    for note_row in note_array:
        onset_q = float(note_row["onset_quarter"])
        duration_q = float(note_row["duration_quarter"])
        if not np.isfinite(onset_q) or not np.isfinite(duration_q):
            continue

        try:
            measure_bounds = measure_map(onset_q)
            measure_start_t = measure_bounds[0]
            measure_start_q = quarter_map(measure_start_t)
            if isinstance(measure_start_q, np.ndarray):
                measure_start_q = measure_start_q.item()
            measure_start_q = float(measure_start_q)
            if not np.isfinite(measure_start_q):
                raise ValueError
        except Exception:
            # Fallback: derive from relative onset if available
            divs_per_q = float(note_row["divs_pq"]) if has_divs else 0.0
            rel_div = float(note_row["rel_onset_div"]) if has_rel else 0.0
            rel_q = rel_div / divs_per_q if divs_per_q else 0.0
            measure_start_q = onset_q - rel_q

        local_onset = onset_q - measure_start_q
        try:
            measure_num_raw = measure_number_map(onset_q)
            if isinstance(measure_num_raw, np.ndarray):
                measure_num_raw = measure_num_raw.item()
            measure_num = int(measure_num_raw)
        except Exception:
            measure_num = 0

        midi_pitch = int(note_row["pitch"])
        voice_value = note_row["voice"] if has_voice else None
        voice_label = _format_voice_label(part_label, voice_value)

        # Optional xml:id extraction (MEI)
        xml_id_value: Optional[str] = None
        if include_xml_ids:
            # Try a variety of common field names present in note_array dtypes
            for fid in ("xml_id", "xmlid", "id", "note_id", "noteid", "xml:id"):
                try:
                    candidate = note_row[fid]  # type: ignore[index]
                except Exception:
                    candidate = None
                if candidate is None:
                    continue
                try:
                    s = str(candidate).strip()
                except Exception:
                    s = ""
                if s:
                    if s.startswith("#"):
                        s = s[1:]
                    xml_id_value = s
                    break

        row: Dict[str, Any] = {
            "Measure": measure_num,
            "Local Onset": float(local_onset),
            "Global Onset": onset_q,
            "Duration": duration_q,
            "Pitch": _midi_to_pitch_name(midi_pitch),
            "MIDI": midi_pitch,
            "Voice": voice_label,
        }
        if include_xml_ids:
            row["xml_id"] = xml_id_value
        if parse_enharmonic:
            spelled: Optional[str] = None

            # Try ID lookup first
            nid = None
            for fid in ("id", "note_id", "xml_id", "xmlid"):
                try:
                    val = note_row[fid]  # type: ignore[index]
                    if val is not None:
                        nid = val
                        break
                except Exception:
                    pass

            if nid in id_to_spelling:
                spelled = id_to_spelling[nid]

            # Fallback to sequential if ID failed but sequence exists
            # (Advance index regardless to stay in sync if mixing methods)
            seq_spelled = None
            if spelled_sequence and spelled_idx < len(spelled_sequence):
                seq_spelled = spelled_sequence[spelled_idx]
                spelled_idx += 1

            if not spelled and seq_spelled:
                spelled = seq_spelled

            if spelled:
                row["Pitch Enharmonic"] = spelled
        rows.append(row)

    return rows


def partitura_score_to_dataframe(score, *, parse_enharmonic: bool = False, include_xml_ids: bool = False) -> pd.DataFrame:
    """
    Convert a partitura Score into a CAMAT-compatible dataframe.
    """
    all_rows: List[Dict[str, Any]] = []
    for part in getattr(score, "parts", []):
        all_rows.extend(_part_to_rows(part, parse_enharmonic=parse_enharmonic, include_xml_ids=include_xml_ids))

    # Build DataFrame; include optional column when present
    df = pd.DataFrame(all_rows)
    if parse_enharmonic and "Pitch Enharmonic" not in df.columns:
        # Ensure column exists (left as None) to reflect requested output schema
        df["Pitch Enharmonic"] = None
    expected = [
        "Measure",
        "Local Onset",
        "Global Onset",
        "Duration",
        "Pitch",
        "MIDI",
        "Voice",
    ]
    if include_xml_ids and "xml_id" in df.columns:
        # Place xml_id immediately after 'Voice'
        try:
            expected.insert(expected.index("Voice") + 1, "xml_id")
        except Exception:
            expected.append("xml_id")
    if parse_enharmonic and "Pitch Enharmonic" in df.columns:
        expected.insert(5, "Pitch Enharmonic")
    # Reorder if all present; otherwise let pandas keep available columns
    if set(expected).issubset(df.columns):
        df = df[expected]
    if len(df):
        df = df.sort_values(["Global Onset", "MIDI"]).reset_index(drop=True)
    return df


def _partitura_measure_offsets(score) -> List[float]:
    """
    Compute measure start offsets (in quarter units) using the first part of the score.
    """
    parts = getattr(score, "parts", None)
    if not parts:
        return []

    primary_part = parts[0]
    quarter_map = primary_part.quarter_map
    offsets: List[float] = []
    seen: set[float] = set()
    for measure in getattr(primary_part, "measures", []):
        try:
            start_q = quarter_map(measure.start.t)
            if isinstance(start_q, np.ndarray):
                start_q = start_q.item()
            start_quarter = float(start_q)
        except Exception:
            continue
        key = round(start_quarter, 6)
        if not np.isfinite(start_quarter) or key in seen:
            continue
        seen.add(key)
        offsets.append(start_quarter)
    return sorted(offsets)


def parse_files_partitura(
    file_sources: Iterable[str],
    *,
    filter_zero_duration: bool = True,
    adjust_fractional_duration: bool = True,
    parse_enharmonic: bool = False,
    backend: str = "plt",
    show_measure_lines: bool = True,
    measure_line_color: str = "red",
    show_hover: bool = True,
    hover_fields: Optional[List[str]] = None,
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
    strip_ties: Optional[bool] = None,
    align_accident_schema: bool = False,
    colorize_voices: bool = False,
    palette: Optional[Union[str, Sequence[str]]] = None,
    include_xml_ids: bool = True,
    normalize_mensural_durations: bool = True,
    inject_missing_meter_signature: bool = True,
    default_meter_count: int = DEFAULT_METER_COUNT,
    default_meter_unit: int = DEFAULT_METER_UNIT,
    try_verovio_mei_conversion: bool = True,
    prefer_verovio_for_mensural: bool = True,
    verovio_mensural_to_cmn: bool = True,
    verovio_duration_equivalence: Optional[float] = None,
    verovio_mensural_score_up: bool = False,
    allow_music21_fallback: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Parse multiple symbolic music files using partitura, producing CAMAT-ready dataframes.

    Parameters mirror camat.music_utils.parse_files for drop-in compatibility.
    For mensural MEI files:
    - `normalize_mensural_durations=True` rewrites mensural duration labels
      (e.g. `semibrevis`) to partitura-compatible values.
    - `inject_missing_meter_signature=True` injects default meter attributes
      when missing (`meter.count` / `meter.unit`).
    For common-notation MEI files these options are intentionally ignored.
    - `prefer_verovio_for_mensural=True` runs mensural MEI through Verovio first
      (before regex-based duration/meter patching).
    - `try_verovio_mei_conversion=True` retries unsupported MEI structures by
      converting through Verovio and then parsing with partitura.
    - `verovio_duration_equivalence` forwards Verovio's duration scaling option.
    - `verovio_mensural_score_up` forwards Verovio's mensural score-up option.
    """
    results: List[Dict[str, Any]] = []
    dfs_by_name: Dict[str, pd.DataFrame] = {}
    last_df: Optional[pd.DataFrame] = None

    try:
        from IPython.display import display as ipy_display  # type: ignore
    except Exception:  # pragma: no cover - notebook only
        ipy_display = None

    sources: List[str] = list(file_sources)
    use_progress = bool(show_progress) and (_tqdm is not None) and (len(sources) > 1)
    pbar = (
        _tqdm(total=len(sources), desc=(progress_desc or "Parsing files"), unit="file")
        if use_progress
        else None
    )
    log = _tqdm.write if use_progress else print

    try:
        for idx, file_source in enumerate(sources):
            file_path: Optional[str] = None
            try:
                if idx > 0 and len(sources) > 1:
                    # Separate the previous file's preview/output from the next file header.
                    log("")
                name = _source_to_name(file_source, idx)
                short_name = os.path.basename(file_source).split("?")[0].split("#")[0]
                log(f"Processing (partitura): {short_name} -> {name}")
                if pbar is not None:
                    pbar.set_postfix_str(short_name)

                file_path = get_file_path(file_source)
                conversion_cleanup_fns: List[Callable[[], None]] = []
                conversion_source_path = file_path
                is_mei_source = Path(file_path).suffix.lower() == ".mei"
                is_mensural_source = _file_looks_mensural_mei(file_path)
                if (
                    is_mei_source
                    and not is_mensural_source
                    and (normalize_mensural_durations or inject_missing_meter_signature)
                ):
                    log(
                        "Detected common-notation MEI. "
                        "Skipping mensural duration/meter preprocessing."
                    )
                if (
                    try_verovio_mei_conversion
                    and prefer_verovio_for_mensural
                    and is_mensural_source
                ):
                    log(
                        "Detected mensural MEI markers. "
                        "Applying Verovio conversion before partitura parsing."
                    )
                    try:
                        (
                            conversion_source_path,
                            converted_cleanup_fn,
                            removed_annots,
                            wrapped_staff_groups,
                        ) = _convert_mei_with_verovio_for_partitura(
                            file_path,
                            mensural_to_cmn=verovio_mensural_to_cmn,
                            duration_equivalence=verovio_duration_equivalence,
                            mensural_score_up=verovio_mensural_score_up,
                        )
                        if converted_cleanup_fn:
                            conversion_cleanup_fns.append(converted_cleanup_fn)
                        if removed_annots > 0:
                            log(
                                "Verovio MEI postprocess: removed "
                                f"{removed_annots} <annot> element(s)."
                            )
                        if wrapped_staff_groups > 0:
                            log(
                                "Verovio MEI postprocess: wrapped "
                                f"{wrapped_staff_groups} section-level staff group(s) "
                                "into synthetic measure elements."
                            )
                    except Exception as conv_exc:
                        log(
                            "Warning: Verovio-first mensural conversion failed "
                            f"('{conv_exc}'). Continuing with text normalization fallback."
                        )

                (
                    sanitized_path,
                    cleanup_fn,
                    mensural_replacements,
                    meter_injections,
                ) = _sanitize_source_for_partitura(
                    conversion_source_path,
                    normalize_mensural_durations=normalize_mensural_durations,
                    inject_missing_meter_signature=inject_missing_meter_signature,
                    default_meter_count=default_meter_count,
                    default_meter_unit=default_meter_unit,
                )
                try:
                    if mensural_replacements > 0:
                        log(
                            "Normalized "
                            f"{mensural_replacements} mensural duration token(s) "
                            "for partitura compatibility."
                        )
                    if meter_injections > 0:
                        log(
                            "Injected default meter signature into "
                            f"{meter_injections} tag(s): "
                            f"{default_meter_count}/{default_meter_unit}."
                        )
                    try:
                        score = _load_partitura_score(sanitized_path)
                    except Exception as load_exc:
                        is_mei_source = str(sanitized_path).lower().endswith(".mei")
                        if (
                            try_verovio_mei_conversion
                            and is_mei_source
                            and _is_partitura_unsupported_mei_structure_error(load_exc)
                        ):
                            log(
                                "Warning: partitura hit unsupported MEI structure "
                                f"('{load_exc}'). Retrying after Verovio MEI conversion."
                            )
                            (
                                converted_path,
                                converted_cleanup_fn,
                                removed_annots,
                                wrapped_staff_groups,
                            ) = _convert_mei_with_verovio_for_partitura(
                                sanitized_path,
                                mensural_to_cmn=verovio_mensural_to_cmn,
                                duration_equivalence=verovio_duration_equivalence,
                                mensural_score_up=verovio_mensural_score_up,
                            )
                            if converted_cleanup_fn:
                                conversion_cleanup_fns.append(converted_cleanup_fn)
                            if removed_annots > 0:
                                log(
                                    "Verovio MEI postprocess: removed "
                                    f"{removed_annots} <annot> element(s)."
                                )
                            if wrapped_staff_groups > 0:
                                log(
                                    "Verovio MEI postprocess: wrapped "
                                    f"{wrapped_staff_groups} section-level staff group(s) "
                                    "into synthetic measure elements."
                                )
                            score = _load_partitura_score(converted_path)
                        else:
                            raise
                finally:
                    if cleanup_fn:
                        cleanup_fn()
                    for _fn in conversion_cleanup_fns:
                        _fn()

                # Only include xml_id when MEI source detected and option enabled
                is_mei = str(sanitized_path).lower().endswith(".mei")
                want_xml_ids = bool(include_xml_ids)
                include_ids_this_score = want_xml_ids and is_mei
                df_raw = partitura_score_to_dataframe(
                    score,
                    parse_enharmonic=parse_enharmonic,
                    include_xml_ids=include_ids_this_score,
                )
                # Optionally align accidental schema prior to duration filtering (no extra rank column)
                excess_clamped = 0
                if align_accident_schema:
                    source_col = "Pitch Enharmonic" if parse_enharmonic else "Pitch"
                    if source_col in df_raw.columns:
                        if parse_enharmonic:
                            def _canon(v: Any) -> Tuple[Any, bool]:
                                # Keep None/NaN untouched
                                if v is None or (isinstance(v, float) and np.isnan(v)):
                                    return v, False
                                if not isinstance(v, str):
                                    try:
                                        v = str(v)
                                    except Exception:
                                        return v, False
                                # Only canonicalize plausible pitch names
                                if not v or v[0].upper() not in "ABCDEFG":
                                    return v, False
                                return canonicalize_pitch_name(v, max_accidentals=5)
                            canon_series = df_raw[source_col].apply(_canon)
                            df_raw[source_col] = canon_series.map(lambda t: t[0])
                            try:
                                excess_clamped = int(canon_series.map(lambda t: 1 if t[1] else 0).sum())
                            except Exception:
                                excess_clamped = 0
                        if excess_clamped > 0:
                            log(f"Warning: {excess_clamped} note(s) exceeded ±5 accidentals; clamped to 5.")
                df_processed = filter_and_adjust_durations(
                    df_raw,
                    filter_zero_duration=filter_zero_duration,
                    adjust_fractional_duration=adjust_fractional_duration,
                ).sort_values("Global Onset").reset_index(drop=True)

                if want_xml_ids and not include_ids_this_score and "xml_id" not in df_processed.columns:
                    df_processed["xml_id"] = pd.NA

                measure_offsets = _partitura_measure_offsets(score)

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
                    log(
                        f"Rows: {len(df_processed)}, unique pitches: {df_processed['MIDI'].nunique()}"
                    )

                result_entry: Dict[str, Any] = {
                    "name": name,
                    "source": file_source,
                    "df": df_processed,
                    "measure_offsets": measure_offsets,
                }
                if return_plots:
                    result_entry["plot"] = plot_obj
                results.append(result_entry)
                dfs_by_name[name] = df_processed
                last_df = df_processed

            except Exception as exc:
                should_try_music21_fallback = (
                    allow_music21_fallback
                    and (
                        _is_mensural_duration_error(exc)
                        or _is_missing_time_signature_error(exc)
                        or _is_partitura_unsupported_mei_structure_error(exc)
                    )
                )
                if should_try_music21_fallback:
                    try:
                        _dur_label = str(exc).strip("'\"")
                    except Exception:
                        _dur_label = str(exc)
                    if _is_missing_time_signature_error(exc):
                        log(
                            "Warning: partitura failed because meter info is missing "
                            f"('{_dur_label}'). "
                            "Falling back to the music21 backend for this file."
                        )
                    elif _is_partitura_unsupported_mei_structure_error(exc):
                        log(
                            "Warning: partitura failed on unsupported MEI structure "
                            f"('{_dur_label}'). "
                            "Falling back to the music21 backend for this file."
                        )
                    else:
                        log(
                            "Warning: partitura cannot parse mensural duration labels "
                            f"(e.g. '{_dur_label}'). "
                            "Falling back to the music21 backend for this file."
                        )
                    try:
                        from .music21_backend import parse_files as _parse_files_music21

                        fallback_results, _, _ = _parse_files_music21(
                            [file_source],
                            filter_zero_duration=filter_zero_duration,
                            adjust_fractional_duration=adjust_fractional_duration,
                            parse_enharmonic=parse_enharmonic,
                            backend=backend,
                            show_measure_lines=show_measure_lines,
                            measure_line_color=measure_line_color,
                            show_hover=show_hover,
                            hover_fields=hover_fields,
                            display_preview=False,
                            preview_rows=preview_rows,
                            cleanup_remote=cleanup_remote,
                            return_plots=return_plots,
                            plot_width=plot_width,
                            plot_height=plot_height,
                            zoom_drag_dim=zoom_drag_dim,
                            zoom_wheel_dim=zoom_wheel_dim,
                            show_progress=False,
                            progress_desc=None,
                            strip_ties=True if strip_ties is None else bool(strip_ties),
                            align_accident_schema=align_accident_schema,
                            colorize_voices=colorize_voices,
                            palette=palette,
                            include_xml_ids=include_xml_ids,
                        )
                        if fallback_results:
                            fb_entry = fallback_results[0]
                            fb_df = fb_entry.get("df")
                            if isinstance(fb_df, pd.DataFrame):
                                fb_entry["name"] = name
                                fb_entry["source"] = file_source
                                results.append(fb_entry)
                                dfs_by_name[name] = fb_df
                                last_df = fb_df
                                if display_preview and ipy_display is not None:
                                    ipy_display(fb_df.head(preview_rows))
                                    log(
                                        f"Rows: {len(fb_df)}, unique pitches: {fb_df['MIDI'].nunique()}"
                                    )
                                continue
                        log(
                            "Fallback to music21 returned no parsed data for "
                            f"{file_source}."
                        )
                    except Exception as fallback_exc:
                        log(
                            f"Fallback to music21 failed for {file_source}: {fallback_exc}"
                        )
                elif (
                    _is_mensural_duration_error(exc)
                    or _is_missing_time_signature_error(exc)
                    or _is_partitura_unsupported_mei_structure_error(exc)
                ) and not allow_music21_fallback:
                    log(
                        "Note: music21 fallback is disabled "
                        "(allow_music21_fallback=False)."
                    )
                log(f"An error occurred while processing {file_source}: {exc}")
            finally:
                if (
                    cleanup_remote
                    and file_path
                    and file_source.startswith(("http://", "https://"))
                ):
                    try:
                        os.remove(file_path)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        pass
                if pbar is not None:
                    pbar.update(1)
    finally:
        if pbar is not None:
            pbar.close()

    return results, dfs_by_name, last_df
