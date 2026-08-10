from __future__ import annotations

import io
import os
import sys
import tempfile
import threading
import types
import warnings
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple, Union, Sequence

import numpy as np
import pandas as pd

from .quiet_utils import _NATIVE_FD_LOCK, suppress_native_output


def _ensure_numpy_compat_aliases() -> None:
    """Restore NumPy aliases still used by supported dependency versions."""
    if not hasattr(np, "row_stack") and hasattr(np, "vstack"):
        np.row_stack = np.vstack  # type: ignore[attr-defined]


_ensure_numpy_compat_aliases()


# -- Verovio main-thread singleton + monkey-patch ---------------------------
#
# Verovio's Python toolkit loads its font resources (Bravura, Leipzig, text
# fonts) at construction time via native code that is NOT thread-safe: every
# `verovio.toolkit()` call constructed on a non-main thread leaves the global
# C++ font tables in a permanently broken state, after which every subsequent
# `loadData` returns empty MEI ("Document is empty" / "Bravura font could not
# be loaded"). Serializing construction with a mutex is *not* sufficient -
# the failure mode is per-thread, not per-concurrent-call. The only reliable
# fix is to construct a toolkit on the main thread exactly once and reuse it
# from every worker thread under a lock.
#
# partitura's own MEI importer (`partitura.io.importmei`) unconditionally does
# `tk = verovio.toolkit(True)` on every `load_score(...)` for an .mei file,
# so we cannot just "be careful" in our own Verovio callsites - we have to
# make `verovio.toolkit(...)` itself return the main-thread singleton so any
# third party that constructs a toolkit from a worker thread still ends up
# sharing the healthy one.
#
# The `_VEROVIO_LOCK` then serializes actual method calls on the shared
# toolkit so concurrent workers don't stomp on each other's `setOptions` /
# `loadData` / `getMEI` state mid-transaction.
_VEROVIO_LOCK = threading.RLock()
_SHARED_VRV_TOOLKIT: Any = None
_VEROVIO_ORIGINAL_FACTORY: Any = None


def _install_verovio_main_thread_shim() -> None:
    """Construct a Verovio toolkit on the main thread and replace
    `verovio.toolkit` with a factory that hands out that singleton. Must be
    called exactly once, from the main thread, at module import time."""
    global _SHARED_VRV_TOOLKIT, _VEROVIO_ORIGINAL_FACTORY
    if _SHARED_VRV_TOOLKIT is not None:
        return
    try:
        import verovio  # type: ignore
    except Exception:  # pragma: no cover - verovio is optional
        return
    _VEROVIO_ORIGINAL_FACTORY = verovio.toolkit
    try:
        _SHARED_VRV_TOOLKIT = verovio.toolkit()
    except Exception:  # pragma: no cover
        _SHARED_VRV_TOOLKIT = None
        return

    def _shared_toolkit_factory(*_args: Any, **_kwargs: Any) -> Any:
        return _SHARED_VRV_TOOLKIT

    verovio.toolkit = _shared_toolkit_factory  # type: ignore[assignment]


_install_verovio_main_thread_shim()


# partitura's MEI/MusicXML importers use lxml with some module-level state
# (e.g. namespace tables) and also surface UserWarnings via the global warnings
# filter machinery. Running many imports concurrently is not a supported mode,
# so we serialize score loading too. Downloads, sanitization, DataFrame assembly
# and MEI event extraction still run in parallel, which is where most of the
# wallclock savings come from.
_PARTITURA_LOAD_LOCK = threading.Lock()


@contextmanager
def _suppress_partitura_user_warnings(enabled: bool):
    """
    Optionally suppress noisy UserWarnings emitted by partitura during MEI import.
    """
    if not enabled:
        yield
        return

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=UserWarning,
            module=r"partitura(\.|$)",
        )
        yield


@contextmanager
def _suppress_partitura_dependency_output(enabled: bool):
    """
    Optionally suppress print()/stderr chatter from dependency code while leaving CAMAT logs alone.
    """
    if not enabled:
        yield
        return

    # `redirect_stdout`/`redirect_stderr` mutate the process-global `sys.stdout`/
    # `sys.stderr` references; two parallel workers entering this context would
    # clobber each other's save/restore pair. Hold the same RLock used by
    # `suppress_native_output` so fd-level and Python-level redirection both
    # behave as a single critical section.
    sink = io.StringIO()
    with _NATIVE_FD_LOCK:
        with redirect_stdout(sink), redirect_stderr(sink), suppress_native_output(enabled=True):
            yield


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
    get_download_cache_dir,
    is_cached_download,
    canonicalize_pitch_name,
    accidental_rank_from_name,
)
from .parser_utils import (
    reanchor_to_measure_offsets,
    reject_unexpected_kwargs,
    resolve_collapse_tied_pitch_events,
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
_MEI_EVENT_TYPE_MAP = {
    # Already-handled core control / text / span elements.
    "annot": "annot",
    "arpeg": "arpeg",
    "barLine": "barline",
    "breath": "breath",
    "caesura": "caesura",
    "dir": "direction",
    "dynam": "dynamic",
    "fermata": "fermata",
    "gliss": "gliss",
    "harm": "harm",
    "hairpin": "hairpin",
    "harpPedal": "harp_pedal",
    "phrase": "phrase",
    "reh": "reh",
    "repeatMark": "repeat_mark",
    "syl": "lyric",
    "slur": "slur",
    "tempo": "tempo",
    "tie": "tie",
    # Ornaments.
    "trill": "trill",
    "mordent": "mordent",
    "turn": "turn",
    "ornam": "ornament",
    "bTrem": "btrem",
    "fTrem": "ftrem",
    # Articulation / fingering / bend (usually note-attached).
    "artic": "artic",
    "fing": "fingering",
    "bend": "bend",
    # Continuous / ranged markings.
    "pedal": "pedal",
    "octave": "octave",
    "ending": "ending",
    "beamSpan": "beam_span",
    "tupletSpan": "tuplet_span",
    # Mid-piece definition changes (also captured for setup in scoreDef/staffDef).
    "clef": "clef",
    "keySig": "key_sig",
    "meterSig": "meter_sig",
    # Whole-measure / invisible rests.
    "mRest": "mrest",
    "multiRest": "multirest",
    "space": "space",
    # Standalone notational markers.
    "custos": "custos",
    "accid": "accid",
}
# Tags that should be suppressed when they appear as children of a note/chord —
# the information is already represented on the pitch row, so emitting another
# event row would be redundant. When NOT inside a note/chord they become
# standalone events (e.g. editorial accidentals hanging off a layer).
_MEI_NOTE_INTERNAL_TAGS: Set[str] = {"accid"}
# Tags that are typically *attached* to a note/chord but still warrant an event
# row — we mark these with scope="note_attached" and mirror the parent's xml_id
# into start_xml_id so downstream joins stay simple.
_MEI_NOTE_ATTACHED_TAGS: Set[str] = {"artic", "fing", "bend"}
# Ancestors that turn clef/keySig/meterSig into *setup* rather than a mid-piece
# change event.
_MEI_DEFINITION_ANCESTORS: Set[str] = {"scoreDef", "staffDef"}
_EVENT_DF_COLUMNS = [
    "type",
    "subtype",
    "Measure",
    "Local Onset",
    "Global Onset",
    "Duration",
    "Voice",
    "xml_id",
    "start_xml_id",
    "end_xml_id",
    "staff_n",
    "staff_raw",
    "layer_n",
    "layer_raw",
    "scope",
    "text",
    "text_role",
    "form",
    "place",
    "func",
    "plist",
    "tstamp_raw",
    "tstamp2_raw",
    "verse_n",
    "wordpos",
    "con",
    "mm",
    "mm_unit",
    "mm_dots",
    "measure_type",
    "measure_metcon",
    "measure_join",
    "measure_n",
    "extra",
]


def _midi_to_pitch_name(midi: int) -> str:
    """
    Convert MIDI pitch number to a textual pitch name (e.g., 60 -> C4).
    """
    octave = (midi // 12) - 1
    pc = _PITCH_CLASS_NAMES[midi % 12]
    return f"{pc}{octave}"


# Precomputed MIDI (0..127) -> pitch name lookup used to vectorize per-note naming.
_MIDI_PITCH_LUT: Tuple[str, ...] = tuple(_midi_to_pitch_name(i) for i in range(128))


def _midi_to_pitch_name_array(midi_values: np.ndarray) -> np.ndarray:
    """
    Vectorized MIDI -> pitch name resolution. Values outside 0..127 fall back to the
    scalar helper so unusual inputs still produce a usable label.
    """
    midi_int = np.asarray(midi_values, dtype=np.int64)
    in_range = (midi_int >= 0) & (midi_int < 128)
    out = np.empty(midi_int.shape, dtype=object)
    if in_range.any():
        lut = np.asarray(_MIDI_PITCH_LUT, dtype=object)
        out[in_range] = lut[midi_int[in_range]]
    if (~in_range).any():
        out[~in_range] = [_midi_to_pitch_name(int(v)) for v in midi_int[~in_range]]
    return out


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
    quiet_native_warnings: bool = False,
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

    # Verovio's font/glyph tables are shared C++ state; serialize the entire
    # toolkit lifecycle so concurrent workers cannot race during font loading.
    with _VEROVIO_LOCK:
        tk = verovio.toolkit()
        with suppress_native_output(enabled=quiet_native_warnings):
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
    mei_text, _ = _copy_staffgrp_symbol_for_partitura(mei_text)

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


def _copy_staffgrp_symbol_for_partitura(mei_text: str) -> Tuple[str, int]:
    """
    Ensure every <staffGrp> has the symbol value partitura expects.

    Verovio may emit MEI with a child <grpSym> carrying the brace/bracket symbol
    while partitura 1.8.0 expects the symbol attribute directly on every nested
    staffGrp. Keep child elements intact and add the parent attribute only when
    it is missing. If a nested group has no own <grpSym>, inherit the nearest
    ancestor symbol; top-level unsymbolized groups receive "none".
    """
    try:
        from lxml import etree  # type: ignore
    except Exception:
        return mei_text, 0

    parser = etree.XMLParser(recover=True, remove_blank_text=False, huge_tree=True)
    try:
        root = etree.fromstring(mei_text.encode("utf-8", errors="ignore"), parser=parser)
    except Exception:
        return mei_text, 0

    def _lname(el: Any) -> str:
        try:
            return etree.QName(el.tag).localname
        except Exception:
            return str(el.tag)

    def _direct_grpsym_symbol(el: Any) -> Optional[str]:
        for child in el:
            if _lname(child) == "grpSym" and child.get("symbol"):
                return str(child.get("symbol"))
        return None

    changed = 0
    for staffgrp_el in root.xpath(".//*[local-name()='staffGrp']"):
        if staffgrp_el.get("symbol"):
            continue
        symbol = _direct_grpsym_symbol(staffgrp_el)
        if symbol is None:
            for ancestor in staffgrp_el.iterancestors():
                if _lname(ancestor) != "staffGrp":
                    continue
                symbol = ancestor.get("symbol") or _direct_grpsym_symbol(ancestor)
                if symbol:
                    break
        if symbol is None:
            symbol = "none"
        staffgrp_el.set("symbol", symbol)
        changed += 1

    if changed == 0:
        return mei_text, 0
    return etree.tostring(root, encoding="unicode"), changed


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
    force_mensural_processing: bool = False,
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

    if suffix == ".mei":
        sanitized, _ = _copy_staffgrp_symbol_for_partitura(sanitized)

    mensural_replacement_count = 0
    meter_injection_count = 0
    is_mensural_mei = suffix == ".mei" and _looks_mensural_mei_text(sanitized)
    should_process_as_mensural = bool(is_mensural_mei or (suffix == ".mei" and force_mensural_processing))
    if should_process_as_mensural and (normalize_mensural_durations or inject_missing_meter_signature):
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


@contextmanager
def _null_ctx():
    yield


def _load_partitura_score(file_path: str):
    suffix = Path(file_path).suffix.lower()
    # Serialize partitura's importers; they share lxml parser state and surface
    # warnings via the global `warnings` filter stack, neither of which is safe
    # to run concurrently across our thread pool. For MEI files we additionally
    # hold `_VEROVIO_LOCK` because partitura's importmei internally uses the
    # (shimmed) main-thread Verovio singleton and multiple workers must not
    # stomp on its setOptions/loadData/getMEI transaction.
    is_mei = suffix == ".mei"
    vrv_ctx = _VEROVIO_LOCK if is_mei else _null_ctx()
    with _PARTITURA_LOAD_LOCK, vrv_ctx:
        if suffix in {".krn", ".kern"}:
            return importkern.load_kern(file_path, force_same_part=True)
        if suffix == ".xml":
            try:
                return importmusicxml.load_musicxml(file_path)
            except Exception:
                # Fallback to the generic loader if load_musicxml fails.
                return pt.load_score(file_path)
        return pt.load_score(file_path)


def _clean_xml_id_value(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    try:
        s = str(raw).strip()
    except Exception:
        return None
    if not s:
        return None
    if s.startswith("#"):
        s = s[1:]
    return s or None


def _resolve_xml_id_field(fields: Iterable[str]) -> Optional[str]:
    field_set = set(fields)
    for candidate in ("xml_id", "xmlid", "id", "note_id", "noteid", "xml:id"):
        if candidate in field_set:
            return candidate
    return None


def _spelling_from_note_array(
    note_array: np.ndarray,
    fields: Iterable[str],
) -> Optional[np.ndarray]:
    """
    Vectorized enharmonic spelling using note_array fields when available.
    Returns None if required fields are missing.
    """
    field_set = set(fields)
    if not {"step", "octave"}.issubset(field_set):
        return None

    steps = np.asarray(note_array["step"]).astype(str)
    steps = np.char.upper(steps)
    octaves = np.asarray(note_array["octave"], dtype=np.int64)
    alters = (
        np.asarray(note_array["alter"], dtype=float)
        if "alter" in field_set
        else np.zeros(octaves.shape, dtype=float)
    )
    alters = np.nan_to_num(alters, nan=0.0, posinf=0.0, neginf=0.0).astype(np.int64)

    out = np.empty(steps.shape, dtype=object)
    for idx in range(steps.size):
        a = int(alters[idx])
        if a > 0:
            acc = "#" * a
        elif a < 0:
            acc = "b" * (-a)
        else:
            acc = ""
        out[idx] = f"{steps[idx]}{acc}{int(octaves[idx])}"
    return out


def _spelling_from_part_notes(part: Any) -> Tuple[Dict[Any, str], List[Tuple[float, int, str]]]:
    """
    Legacy spelling lookup: derive from part.notes when note_array lacks spelling fields.
    Returns (id_to_spelling, ordered_spellings_with_sort_key).
    """
    id_to_spelling: Dict[Any, str] = {}
    sort_info: List[Tuple[float, int, str]] = []
    try:
        notes = list(getattr(part, "notes", []) or [])
    except Exception:
        return id_to_spelling, sort_info

    for n in notes:
        step = getattr(n, "step", None)
        octave = getattr(n, "octave", None)
        alter = getattr(n, "alter", None)
        if alter is None:
            acc_name = str(getattr(n, "accidental", "") or "").lower()
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
        try:
            a = int(round(float(alter))) if alter is not None else 0
        except Exception:
            a = 0
        if a > 0:
            acc = "#" * a
        elif a < 0:
            acc = "b" * (-a)
        else:
            acc = ""
        if step is None or octave is None:
            continue
        spelled = f"{str(step).upper()}{acc}{int(octave)}"
        nid = getattr(n, "id", None) or getattr(n, "xml_id", None)
        if nid is not None:
            id_to_spelling[nid] = spelled
        start_t = getattr(getattr(n, "start", None), "t", 0) or 0
        midi_p = getattr(n, "midi_pitch", 0) or 0
        try:
            sort_info.append((float(start_t), int(midi_p), spelled))
        except Exception:
            sort_info.append((0.0, 0, spelled))
    sort_info.sort(key=lambda x: (x[0], x[1]))
    return id_to_spelling, sort_info


def _measure_anchors_for_unique_onsets(
    unique_onsets: np.ndarray,
    measure_map: Any,
    quarter_map: Any,
    measure_number_map: Any,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute (measure_start_q, measure_num) per unique onset. NaN measure_start marks
    lookup failures so callers can substitute a fallback from rel_onset_div.
    """
    n = unique_onsets.shape[0]
    starts = np.full(n, np.nan, dtype=float)
    nums = np.zeros(n, dtype=np.int64)
    if n == 0:
        return starts, nums

    def _scalar(value: Any) -> Any:
        if isinstance(value, np.ndarray):
            try:
                return value.item()
            except Exception:
                return value[()] if value.shape == () else value.flat[0]
        return value

    for i in range(n):
        onset = float(unique_onsets[i])
        try:
            bounds = measure_map(onset)
            start_t = bounds[0] if hasattr(bounds, "__getitem__") else bounds
            sq = _scalar(quarter_map(start_t))
            sq_f = float(sq)
            if np.isfinite(sq_f):
                starts[i] = sq_f
        except Exception:
            pass
        try:
            mn = _scalar(measure_number_map(onset))
            nums[i] = int(mn)
        except Exception:
            nums[i] = 0
    return starts, nums


def _part_note_attachments_by_xml_id(
    part: Any,
    *,
    use_tied_notes: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """
    Collect per-note attachment metadata from a partitura Part.

    Used as the fallback source for non-MEI scores. Partitura's MEI importer
    (as of v1.8) does not populate ``slur_starts`` / ``fermata`` /
    ``articulations`` on Note objects, so the MEI-backed pipeline relies on
    :func:`_extract_mei_note_attachments` instead.
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        from partitura.score import GraceNote as _GraceNote  # type: ignore
    except Exception:  # pragma: no cover - very old partitura versions
        _GraceNote = None  # type: ignore

    if use_tied_notes:
        notes_iter = getattr(part, "notes_tied", None) or getattr(part, "notes", [])
    else:
        notes_iter = getattr(part, "notes", None) or []

    for note in notes_iter or []:
        try:
            nid = _clean_xml_id_value(getattr(note, "id", None))
        except Exception:
            nid = None
        if not nid:
            continue
        info: Dict[str, Any] = {}
        if _GraceNote is not None and isinstance(note, _GraceNote):
            info["grace"] = True
        artic = getattr(note, "articulations", None) or []
        if artic:
            info["articulations"] = " ".join(sorted({str(a) for a in artic}))
        orn = getattr(note, "ornaments", None) or []
        if orn:
            info["ornaments"] = " ".join(sorted({str(o) for o in orn}))
        tech = getattr(note, "technical", None) or []
        if tech:
            info["technical"] = " ".join(sorted({str(t) for t in tech}))
        if getattr(note, "fermata", None) is not None:
            info["fermata"] = True
        tie_prev = getattr(note, "tie_prev", None)
        tie_next = getattr(note, "tie_next", None)
        if tie_prev is not None or tie_next is not None:
            if tie_prev is not None and tie_next is not None:
                info["tied"] = "middle"
            elif tie_next is not None:
                info["tied"] = "start"
            else:
                info["tied"] = "stop"
        slur_starts = getattr(note, "slur_starts", None) or []
        slur_stops = getattr(note, "slur_stops", None) or []
        if slur_starts or slur_stops:
            if slur_starts and slur_stops:
                info["slurred"] = "both"
            elif slur_starts:
                info["slurred"] = "start"
            else:
                info["slurred"] = "stop"
        tuplet_starts = getattr(note, "tuplet_starts", None) or []
        tuplet_stops = getattr(note, "tuplet_stops", None) or []
        if tuplet_starts or tuplet_stops:
            if tuplet_starts and tuplet_stops:
                info["tuplet"] = "both"
            elif tuplet_starts:
                info["tuplet"] = "start"
            else:
                info["tuplet"] = "stop"
        if info:
            out[nid] = info
    return out


_NOTE_ATTACHMENTS_CACHE: Dict[Tuple[Any, ...], Dict[str, Dict[str, Any]]] = {}
_NOTE_ATTACHMENTS_CACHE_MAX = 64


def _mei_note_attachments_cache_key(mei_path: str) -> Optional[Tuple[Any, ...]]:
    try:
        stat = os.stat(mei_path)
    except OSError:
        return None
    return (os.path.realpath(mei_path), stat.st_mtime_ns, stat.st_size)


def _extract_mei_note_attachments(mei_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Build a ``note xml:id -> attachment dict`` map by walking the MEI XML.

    This is the authoritative source of per-note slur/tie/fermata/articulation
    / ornament / grace / tuplet membership for MEI inputs — partitura's
    importer does not currently expose these reliably on Note objects.
    """
    if Path(mei_path).suffix.lower() != ".mei":
        return {}
    cache_key = _mei_note_attachments_cache_key(mei_path)
    if cache_key is not None:
        cached = _NOTE_ATTACHMENTS_CACHE.get(cache_key)
        if cached is not None:
            return {nid: dict(info) for nid, info in cached.items()}

    try:
        import xml.etree.ElementTree as ET

        root = ET.parse(mei_path).getroot()
    except Exception:
        return {}

    def _lname(tag: Any) -> str:
        raw = str(tag)
        return raw.rsplit("}", 1)[-1] if "}" in raw else raw

    xml_id_key = "{http://www.w3.org/XML/1998/namespace}id"

    def _xid(el: Any) -> Optional[str]:
        if el is None:
            return None
        raw = el.attrib.get(xml_id_key) or el.attrib.get("xml:id")
        if raw is None:
            return None
        value = str(raw).strip()
        if not value:
            return None
        return value[1:] if value.startswith("#") else value

    def _ids_from_plist(raw: Any) -> List[str]:
        if raw is None:
            return []
        tokens = str(raw).strip().split()
        out: List[str] = []
        for tok in tokens:
            tok = tok.strip()
            if not tok:
                continue
            out.append(tok[1:] if tok.startswith("#") else tok)
        return out

    parent_map = {child: parent for parent in root.iter() for child in parent}
    ordered_note_ids = [
        note_id
        for candidate in root.iter()
        if _lname(candidate.tag) == "note"
        and (note_id := _xid(candidate)) is not None
    ]
    note_position = {note_id: index for index, note_id in enumerate(ordered_note_ids)}
    attachments: Dict[str, Dict[str, Any]] = {}

    def _bucket(nid: str) -> Dict[str, Any]:
        if nid not in attachments:
            attachments[nid] = {}
        return attachments[nid]

    def _mark(nid: str, key: str, value: Any) -> None:
        b = _bucket(nid)
        if key in {"articulations", "ornaments", "technical"}:
            existing = b.get(key)
            seen = set(existing.split()) if isinstance(existing, str) else set()
            for tok in str(value).split():
                if tok:
                    seen.add(tok)
            if seen:
                b[key] = " ".join(sorted(seen))
        elif key in {"tied", "slurred", "tuplet"}:
            cur = b.get(key)
            order = {"start": 1, "stop": 2, "middle": 3, "member": 4, "both": 5}
            if cur is None:
                b[key] = value
            elif cur != value and {cur, value} == {"start", "stop"}:
                b[key] = "both"
            elif order.get(value, 0) > order.get(cur, 0):
                b[key] = value
        else:
            b[key] = value

    def _note_ids_in(el: Any) -> List[str]:
        ids: List[str] = []
        for ch in el.iter():
            if _lname(ch.tag) in {"note", "chord"}:
                xid = _xid(ch)
                if xid:
                    ids.append(xid)
        return ids

    def _chord_child_note_ids(chord_el: Any) -> List[str]:
        return [
            _xid(ch)
            for ch in chord_el
            if _lname(ch.tag) == "note" and _xid(ch) is not None
        ]  # type: ignore[misc]

    for el in root.iter():
        tag = _lname(el.tag)

        if tag == "note":
            nid = _xid(el)
            if not nid:
                continue
            parent = parent_map.get(el)
            parent_tag = _lname(parent.tag) if parent is not None else ""
            if el.attrib.get("grace"):
                _mark(nid, "grace", True)
            artic_attr = el.attrib.get("artic")
            if artic_attr:
                _mark(nid, "articulations", artic_attr)
            # Ornaments / articulations / fermata encoded as attributes on a
            # note (rare but legal).
            if el.attrib.get("ornam"):
                _mark(nid, "ornaments", el.attrib["ornam"])
            if el.attrib.get("fermata"):
                _mark(nid, "fermata", True)
            tie_attr = el.attrib.get("tie")
            if tie_attr is None and parent_tag == "chord" and parent is not None:
                tie_attr = parent.attrib.get("tie")
            tie_tokens = {
                token
                for token in str(tie_attr or "").lower().replace(",", " ").split()
                if token
            }
            if tie_tokens & {"i", "initial", "start"}:
                _mark(nid, "tied", "start")
            if tie_tokens & {"m", "medial", "middle"}:
                _mark(nid, "tied", "middle")
            if tie_tokens & {"t", "terminal", "stop"}:
                _mark(nid, "tied", "stop")
            # Children like <artic>, <trill>, <mordent>, <turn>, <ornam>.
            for child in el:
                ctag = _lname(child.tag)
                if ctag == "artic":
                    val = child.attrib.get("artic") or child.attrib.get("value") or ctag
                    _mark(nid, "articulations", val)
                elif ctag in {"trill", "mordent", "turn", "ornam"}:
                    _mark(nid, "ornaments", ctag)
                elif ctag == "fermata":
                    _mark(nid, "fermata", True)
                elif ctag == "bend":
                    _mark(nid, "technical", "bend")
            # Inherit chord-level articulation attribute to member notes so
            # "chord slur" encodings still annotate each pitch row.
            if parent_tag == "chord" and parent is not None:
                chord_artic = parent.attrib.get("artic")
                if chord_artic:
                    _mark(nid, "articulations", chord_artic)
                if parent.attrib.get("grace"):
                    _mark(nid, "grace", True)

        elif tag in {"slur", "tie"}:
            field = "tied" if tag == "tie" else "slurred"
            startid = el.attrib.get("startid")
            endid = el.attrib.get("endid")
            if startid:
                sid = startid.lstrip("#").strip()
                if sid:
                    _mark(sid, field, "start")
            if endid:
                eid = endid.lstrip("#").strip()
                if eid:
                    _mark(eid, field, "stop")
            for pid in _ids_from_plist(el.attrib.get("plist")):
                _mark(pid, field, "start")

        elif tag == "fermata":
            startid = el.attrib.get("startid")
            if startid:
                sid = startid.lstrip("#").strip()
                if sid:
                    _mark(sid, "fermata", True)

        elif tag in {"trill", "mordent", "turn", "ornam", "arpeg", "gliss"}:
            startid = el.attrib.get("startid")
            if startid:
                sid = startid.lstrip("#").strip()
                if sid:
                    _mark(sid, "ornaments", tag)

        elif tag == "tuplet":
            for nid in _note_ids_in(el):
                _mark(nid, "tuplet", "member")

        elif tag == "tupletSpan":
            startid = el.attrib.get("startid")
            endid = el.attrib.get("endid")
            sid = startid.lstrip("#").strip() if startid else ""
            eid = endid.lstrip("#").strip() if endid else ""
            if sid in note_position and eid in note_position:
                start_position = note_position[sid]
                end_position = note_position[eid]
                if start_position < end_position:
                    for member_id in ordered_note_ids[start_position + 1 : end_position]:
                        _mark(member_id, "tuplet", "member")
            if startid:
                if sid:
                    _mark(sid, "tuplet", "start")
            if endid:
                if eid:
                    _mark(eid, "tuplet", "stop")
            for pid in _ids_from_plist(el.attrib.get("plist")):
                if pid not in {sid, eid}:
                    _mark(pid, "tuplet", "member")

    if cache_key is not None:
        if len(_NOTE_ATTACHMENTS_CACHE) >= _NOTE_ATTACHMENTS_CACHE_MAX:
            try:
                oldest = next(iter(_NOTE_ATTACHMENTS_CACHE))
                _NOTE_ATTACHMENTS_CACHE.pop(oldest, None)
            except StopIteration:
                pass
        _NOTE_ATTACHMENTS_CACHE[cache_key] = {
            nid: dict(info) for nid, info in attachments.items()
        }

    return attachments


def _apply_note_attachments_to_pitch_df(
    df_pitch: pd.DataFrame,
    attachments: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    """
    Merge a ``xml_id -> attachment dict`` mapping into ``df_pitch`` as the
    standard note-attachment columns. Columns are always added (NA-filled) so
    downstream schema is stable even when the source had no attachments.
    """
    if "xml_id" not in df_pitch.columns:
        for col in _NOTE_ATTACHMENT_COLUMNS:
            if col not in df_pitch.columns:
                df_pitch[col] = pd.NA
        return df_pitch

    if attachments:
        id_series = df_pitch["xml_id"].tolist()
        for col in _NOTE_ATTACHMENT_COLUMNS:
            df_pitch[col] = [
                attachments.get(str(nid), {}).get(col, pd.NA) if nid else pd.NA
                for nid in id_series
            ]
    else:
        for col in _NOTE_ATTACHMENT_COLUMNS:
            if col not in df_pitch.columns:
                df_pitch[col] = pd.NA
    return df_pitch


# Columns appended to df_pitch when note-attachment enrichment runs. Keep the
# order stable so downstream consumers can depend on it.
_NOTE_ATTACHMENT_COLUMNS: Tuple[str, ...] = (
    "grace",
    "tied",
    "slurred",
    "tuplet",
    "fermata",
    "articulations",
    "ornaments",
    "technical",
)


def _part_to_dataframe(
    part: Any,
    *,
    parse_enharmonic: bool = False,
    include_xml_ids: bool = False,
    include_note_attachments: bool = False,
    collapse_tied_pitch_events: bool = True,
) -> pd.DataFrame:
    """
    Convert a single partitura Part into a CAMAT-compatible DataFrame.

    Vectorized over the part's note_array to avoid per-note Python overhead.
    When collapse_tied_pitch_events is False, build from part.notes so tied
    continuation segments remain visible instead of using partitura's collapsed
    note_array.
    """
    if not collapse_tied_pitch_events:
        return _part_notes_to_dataframe(
            part,
            parse_enharmonic=parse_enharmonic,
            include_xml_ids=include_xml_ids,
            include_note_attachments=include_note_attachments,
        )

    note_array_kwargs: Dict[str, Any] = dict(
        include_metrical_position=True,
        include_divs_per_quarter=True,
    )
    if parse_enharmonic:
        note_array_kwargs["include_pitch_spelling"] = True
    try:
        note_array = part.note_array(**note_array_kwargs)
    except TypeError:
        # Older partitura versions may not accept include_pitch_spelling.
        note_array_kwargs.pop("include_pitch_spelling", None)
        note_array = part.note_array(**note_array_kwargs)
    if getattr(note_array, "size", 0) == 0:
        return pd.DataFrame()

    fields = set(note_array.dtype.names or ())
    onsets = np.asarray(note_array["onset_quarter"], dtype=float)
    durations = np.asarray(note_array["duration_quarter"], dtype=float)
    finite_mask = np.isfinite(onsets) & np.isfinite(durations)
    if not finite_mask.all():
        note_array = note_array[finite_mask]
        if note_array.size == 0:
            return pd.DataFrame()
        onsets = onsets[finite_mask]
        durations = durations[finite_mask]
    midi = np.asarray(note_array["pitch"], dtype=np.int64)

    measure_map = part.measure_map
    quarter_map = part.quarter_map
    measure_number_map = part.measure_number_map
    part_label = (
        getattr(part, "part_name", None)
        or getattr(part, "name", None)
        or getattr(part, "id", None)
        or ""
    )
    part_label_str = str(part_label) if part_label else ""

    unique_onsets, inverse = np.unique(onsets, return_inverse=True)
    starts_u, nums_u = _measure_anchors_for_unique_onsets(
        unique_onsets, measure_map, quarter_map, measure_number_map
    )
    measure_starts = starts_u[inverse]
    measure_nums = nums_u[inverse]

    nan_mask = ~np.isfinite(measure_starts)
    if nan_mask.any():
        if "divs_pq" in fields and "rel_onset_div" in fields:
            divs = np.asarray(note_array["divs_pq"], dtype=float)
            rel = np.asarray(note_array["rel_onset_div"], dtype=float)
            safe_divs = np.where(divs > 0, divs, 1.0)
            fallback_start = onsets - (rel / safe_divs)
            measure_starts = np.where(nan_mask, fallback_start, measure_starts)
        else:
            measure_starts = np.where(nan_mask, onsets, measure_starts)

    local_onsets = onsets - measure_starts

    has_voice = "voice" in fields
    if has_voice:
        voice_raw = np.asarray(note_array["voice"]).tolist()
        voice_labels = [
            _format_voice_label(part_label_str, v) for v in voice_raw
        ]
    else:
        default_voice = _format_voice_label(part_label_str, None)
        voice_labels = [default_voice] * len(onsets)

    pitch_names = _midi_to_pitch_name_array(midi)

    data: Dict[str, Any] = {
        "Measure": measure_nums.astype(np.int64),
        "Local Onset": local_onsets.astype(float),
        "Global Onset": onsets.astype(float),
        "Duration": durations.astype(float),
        "Pitch": pitch_names,
        "MIDI": midi.astype(np.int64),
        "Voice": voice_labels,
    }

    xml_id_field = _resolve_xml_id_field(fields) if include_xml_ids else None
    if include_xml_ids:
        if xml_id_field is not None:
            raw_ids = np.asarray(note_array[xml_id_field]).tolist()
            data["xml_id"] = [_clean_xml_id_value(v) for v in raw_ids]
        else:
            data["xml_id"] = [None] * len(onsets)

    if parse_enharmonic:
        spelled_arr = _spelling_from_note_array(note_array, fields)
        if spelled_arr is None:
            id_to_spelling, sort_info = _spelling_from_part_notes(part)
            spelled_sequence = [entry[2] for entry in sort_info]
            xml_id_for_spelling = xml_id_field or _resolve_xml_id_field(fields)
            id_column: Optional[List[Any]] = None
            if xml_id_for_spelling is not None and id_to_spelling:
                id_column = np.asarray(note_array[xml_id_for_spelling]).tolist()
            spelled_list: List[Optional[str]] = []
            seq_idx = 0
            for i in range(len(onsets)):
                spelled: Optional[str] = None
                if id_column is not None:
                    nid = id_column[i]
                    if nid in id_to_spelling:
                        spelled = id_to_spelling[nid]
                if spelled is None and seq_idx < len(spelled_sequence):
                    spelled = spelled_sequence[seq_idx]
                if seq_idx < len(spelled_sequence):
                    seq_idx += 1
                spelled_list.append(spelled)
            data["Pitch Enharmonic"] = spelled_list
        else:
            data["Pitch Enharmonic"] = spelled_arr

    df_part = pd.DataFrame(data)

    if include_note_attachments:
        attachments = _part_note_attachments_by_xml_id(part, use_tied_notes=True)
        # Always add the columns (NA-filled) so downstream schema is stable
        # whether or not a particular part yielded any attachment rows.
        id_series = df_part["xml_id"] if "xml_id" in df_part.columns else None
        for col in _NOTE_ATTACHMENT_COLUMNS:
            if id_series is None or not attachments:
                df_part[col] = pd.NA
                continue
            df_part[col] = [
                attachments.get(nid, {}).get(col, pd.NA) if nid else pd.NA
                for nid in id_series
            ]

    return df_part


def _part_notes_to_dataframe(
    part: Any,
    *,
    parse_enharmonic: bool = False,
    include_xml_ids: bool = False,
    include_note_attachments: bool = False,
) -> pd.DataFrame:
    """
    Convert source Note objects into a CAMAT-compatible dataframe.

    Partitura's note_array is based on notes_tied and therefore collapses tied
    chains. This slower path is used only when callers explicitly request the
    untied source segmentation.
    """
    try:
        notes = list(getattr(part, "notes", []) or [])
    except Exception:
        notes = []
    if not notes:
        return pd.DataFrame()

    quarter_map = part.quarter_map
    measure_map = part.measure_map
    measure_number_map = part.measure_number_map
    part_label = (
        getattr(part, "part_name", None)
        or getattr(part, "name", None)
        or getattr(part, "id", None)
        or ""
    )
    part_label_str = str(part_label) if part_label else ""

    rows: List[Dict[str, Any]] = []
    id_to_spelling: Dict[Any, str] = {}
    if parse_enharmonic:
        id_to_spelling, _ = _spelling_from_part_notes(part)

    for note in notes:
        try:
            start_t = getattr(getattr(note, "start", None), "t")
            end_t = getattr(getattr(note, "end", None), "t")
            onset_q = quarter_map(start_t)
            end_q = quarter_map(end_t)
            if isinstance(onset_q, np.ndarray):
                onset_q = onset_q.item()
            if isinstance(end_q, np.ndarray):
                end_q = end_q.item()
            onset = float(onset_q)
            duration = float(end_q) - onset
        except Exception:
            continue
        if not np.isfinite(onset) or not np.isfinite(duration):
            continue

        try:
            midi = int(getattr(note, "midi_pitch"))
        except Exception:
            continue

        try:
            bounds = measure_map(onset)
            measure_start_t = bounds[0] if hasattr(bounds, "__getitem__") else bounds
            measure_start_q = quarter_map(measure_start_t)
            if isinstance(measure_start_q, np.ndarray):
                measure_start_q = measure_start_q.item()
            measure_start = float(measure_start_q)
        except Exception:
            measure_start = onset

        try:
            measure_num_raw = measure_number_map(onset)
            if isinstance(measure_num_raw, np.ndarray):
                measure_num_raw = measure_num_raw.item()
            measure_num = int(measure_num_raw)
        except Exception:
            measure_num = 0

        raw_id = getattr(note, "id", None) or getattr(note, "xml_id", None)
        xml_id = _clean_xml_id_value(raw_id)
        voice = _format_voice_label(part_label_str, getattr(note, "voice", None))
        row: Dict[str, Any] = {
            "Measure": measure_num,
            "Local Onset": float(onset - measure_start),
            "Global Onset": onset,
            "Duration": duration,
            "Pitch": _midi_to_pitch_name(midi),
            "MIDI": midi,
            "Voice": voice,
        }
        if include_xml_ids:
            row["xml_id"] = xml_id
        if parse_enharmonic:
            spelled = None
            if raw_id is not None:
                spelled = id_to_spelling.get(raw_id)
            if spelled is None and xml_id is not None:
                spelled = id_to_spelling.get(xml_id)
            row["Pitch Enharmonic"] = spelled or row["Pitch"]
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df_part = pd.DataFrame(rows)
    if include_note_attachments:
        attachments = _part_note_attachments_by_xml_id(part, use_tied_notes=False)
        id_series = df_part["xml_id"] if "xml_id" in df_part.columns else None
        for col in _NOTE_ATTACHMENT_COLUMNS:
            if id_series is None or not attachments:
                df_part[col] = pd.NA
                continue
            df_part[col] = [
                attachments.get(nid, {}).get(col, pd.NA) if nid else pd.NA
                for nid in id_series
            ]

    return df_part


def _part_to_rows(
    part: Any,
    *,
    parse_enharmonic: bool = False,
    include_xml_ids: bool = False,
    include_note_attachments: bool = False,
    collapse_tied_pitch_events: bool = True,
) -> List[Dict[str, Any]]:
    """
    Thin backward-compatible wrapper around _part_to_dataframe.
    """
    df = _part_to_dataframe(
        part,
        parse_enharmonic=parse_enharmonic,
        include_xml_ids=include_xml_ids,
        include_note_attachments=include_note_attachments,
        collapse_tied_pitch_events=collapse_tied_pitch_events,
    )
    if df.empty:
        return []
    return df.to_dict(orient="records")


def _partitura_rest_events_to_dataframe(score, *, include_xml_ids: bool = False) -> pd.DataFrame:
    """
    Extract rest timing rows from a partitura score into the standard event schema.
    """
    rows: List[Dict[str, Any]] = []

    for part_index, part in enumerate(getattr(score, "parts", []) or [], start=1):
        try:
            rest_array = part.rest_array(include_metrical_position=True)
        except Exception:
            continue
        if getattr(rest_array, "size", 0) == 0:
            continue

        measure_map = part.measure_map
        quarter_map = part.quarter_map
        measure_number_map = part.measure_number_map
        part_label = (
            getattr(part, "part_name", None)
            or getattr(part, "name", None)
            or getattr(part, "id", None)
            or ""
        )
        staff_n = str(part_index)
        fields = set(rest_array.dtype.names or ())
        has_voice = "voice" in fields

        for rest_row in rest_array:
            onset_q = float(rest_row["onset_quarter"])
            duration_q = float(rest_row["duration_quarter"])
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
                measure_start_q = onset_q

            local_onset = onset_q - measure_start_q
            try:
                measure_num_raw = measure_number_map(onset_q)
                if isinstance(measure_num_raw, np.ndarray):
                    measure_num_raw = measure_num_raw.item()
                measure_num = int(measure_num_raw)
            except Exception:
                measure_num = 0

            voice_value = rest_row["voice"] if has_voice else None
            voice_label = _format_voice_label(part_label, voice_value)

            xml_id_value: Optional[str] = None
            if include_xml_ids:
                for fid in ("xml_id", "xmlid", "id", "note_id", "noteid", "xml:id"):
                    try:
                        candidate = rest_row[fid]  # type: ignore[index]
                    except Exception:
                        candidate = None
                    if candidate is None:
                        continue
                    try:
                        value = str(candidate).strip()
                    except Exception:
                        value = ""
                    if value:
                        xml_id_value = value[1:] if value.startswith("#") else value
                        break

            rows.append(
                {
                    "type": "rest",
                    "subtype": "rest",
                    "Measure": measure_num,
                    "Local Onset": float(local_onset),
                    "Global Onset": onset_q,
                    "Duration": duration_q,
                    "Voice": voice_label,
                    "xml_id": xml_id_value if include_xml_ids else pd.NA,
                    "start_xml_id": pd.NA,
                    "end_xml_id": pd.NA,
                    "staff_n": staff_n,
                    "staff_raw": pd.NA,
                    "layer_n": pd.NA,
                    "layer_raw": pd.NA,
                    "scope": "timeline",
                    "text": pd.NA,
                    "text_role": pd.NA,
                    "form": pd.NA,
                    "place": pd.NA,
                    "func": pd.NA,
                    "plist": pd.NA,
                    "tstamp_raw": pd.NA,
                    "tstamp2_raw": pd.NA,
                    "verse_n": pd.NA,
                    "wordpos": pd.NA,
                    "con": pd.NA,
                    "mm": pd.NA,
                    "mm_unit": pd.NA,
                    "mm_dots": pd.NA,
                    "extra": pd.NA,
                }
            )

    if not rows:
        return _empty_event_dataframe()

    df_events = pd.DataFrame(rows)
    for col in _EVENT_DF_COLUMNS:
        if col not in df_events.columns:
            df_events[col] = pd.NA
    df_events = df_events[_EVENT_DF_COLUMNS]
    return df_events.sort_values("Global Onset", na_position="last").reset_index(drop=True)


def partitura_score_to_dataframe(
    score,
    *,
    parse_enharmonic: bool = False,
    include_xml_ids: bool = False,
    include_note_attachments: bool = False,
    collapse_tied_pitch_events: bool = True,
) -> pd.DataFrame:
    """
    Convert a partitura Score into a CAMAT-compatible dataframe.
    """
    frames: List[pd.DataFrame] = []
    for part in getattr(score, "parts", []):
        part_df = _part_to_dataframe(
            part,
            parse_enharmonic=parse_enharmonic,
            include_xml_ids=include_xml_ids,
            include_note_attachments=include_note_attachments,
            collapse_tied_pitch_events=collapse_tied_pitch_events,
        )
        if not part_df.empty:
            frames.append(part_df)

    if not frames:
        df = pd.DataFrame()
    elif len(frames) == 1:
        df = frames[0]
    else:
        df = pd.concat(frames, ignore_index=True, sort=False, copy=False)

    if parse_enharmonic and "Pitch Enharmonic" not in df.columns:
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
        try:
            expected.insert(expected.index("Voice") + 1, "xml_id")
        except Exception:
            expected.append("xml_id")
    if parse_enharmonic and "Pitch Enharmonic" in df.columns:
        expected.insert(5, "Pitch Enharmonic")
    if include_note_attachments:
        for col in _NOTE_ATTACHMENT_COLUMNS:
            if col in df.columns and col not in expected:
                expected.append(col)
    if set(expected).issubset(df.columns):
        df = df[expected]

    if len(df):
        df = df.sort_values(["Global Onset", "MIDI"], kind="stable").reset_index(drop=True)
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


def _mei_local_name(tag: Any) -> str:
    raw = str(tag)
    return raw.rsplit("}", 1)[-1] if "}" in raw else raw


def _mei_xml_id(el: Any) -> Optional[str]:
    if el is None:
        return None
    raw = el.attrib.get("{http://www.w3.org/XML/1998/namespace}id") or el.attrib.get("xml:id")
    return _normalize_xml_ref(raw)


def _mei_music_measures(root: Any) -> List[Any]:
    """Return performed-score measures, excluding header incipits/examples."""
    music_nodes = [el for el in root.iter() if _mei_local_name(el.tag) == "music"]
    if music_nodes:
        body_nodes = [
            el
            for music in music_nodes
            for el in music.iter()
            if _mei_local_name(el.tag) == "body"
        ]
        search_roots = body_nodes or music_nodes
        measures = [
            el
            for search_root in search_roots
            for el in search_root.iter()
            if _mei_local_name(el.tag) == "measure"
        ]
        if measures:
            return measures
    return [el for el in root.iter() if _mei_local_name(el.tag) == "measure"]


def _source_staff_index_to_part_label_map_from_mei(root: Any) -> Dict[str, str]:
    """Return canonical performed-score part labels keyed by MEI staff number."""
    music_nodes = [el for el in root.iter() if _mei_local_name(el.tag) == "music"]
    body_nodes = [
        el
        for music in music_nodes
        for el in music.iter()
        if _mei_local_name(el.tag) == "body"
    ]
    search_roots = body_nodes or music_nodes or [root]
    staff_defs = [
        el
        for search_root in search_roots
        for el in search_root.iter()
        if _mei_local_name(el.tag) == "staffDef"
    ]

    mapping: Dict[str, str] = {}
    for idx, staff_def in enumerate(staff_defs, start=1):
        staff_n = str(staff_def.attrib.get("n") or idx).strip()
        if not staff_n or staff_n in mapping:
            continue
        label_text = None
        for child in list(staff_def):
            if _mei_local_name(child.tag) != "label":
                continue
            text = " ".join(" ".join(child.itertext()).split())
            if text:
                label_text = text
                break
        mapping[staff_n] = str(label_text or _mei_xml_id(staff_def) or f"P{staff_n}").strip()
    return mapping


def _mei_initial_meter_span(root: Any, fallback: float = 4.0) -> float:
    """Read the initial performed-score meter as a quarter-note span."""
    music_nodes = [el for el in root.iter() if _mei_local_name(el.tag) == "music"]
    search_roots = music_nodes or [root]
    for search_root in search_roots:
        for el in search_root.iter():
            if _mei_local_name(el.tag) not in {"scoreDef", "staffDef", "meterSig"}:
                continue
            count = el.attrib.get("meter.count") or el.attrib.get("count")
            unit = el.attrib.get("meter.unit") or el.attrib.get("unit")
            if count is None or unit is None:
                continue
            try:
                count_f = sum(float(token) for token in str(count).split("+") if token.strip())
                unit_f = float(unit)
            except Exception:
                continue
            if count_f > 0 and unit_f > 0:
                return float(count_f * (4.0 / unit_f))
    return float(fallback)


def _mei_measure_meter_spans(
    root: Any,
    measures: Optional[Sequence[Any]] = None,
    *,
    fallback: float = 4.0,
) -> Dict[int, float]:
    """Map performed MEI measures to the meter active at their start.

    MEI represents mid-score meter changes with a ``scoreDef`` between two
    measures (and commonly repeats the same ``meterSig`` in every staffDef).
    Looking up only the first meter therefore produces a drifting measure grid.
    The map is keyed by ``id(measure)`` so callers can retain their existing
    ElementTree elements without relying on source ``xml:id`` availability.
    """

    target_measures = list(measures) if measures is not None else _mei_music_measures(root)
    if not target_measures:
        return {}
    target_ids = {id(measure) for measure in target_measures}

    music_nodes = [el for el in root.iter() if _mei_local_name(el.tag) == "music"]
    body_nodes = [
        el
        for music in music_nodes
        for el in music.iter()
        if _mei_local_name(el.tag) == "body"
    ]
    search_roots = body_nodes or music_nodes or [root]

    def _span_from_element(el: Any) -> Optional[float]:
        count = el.attrib.get("meter.count") or el.attrib.get("count")
        unit = el.attrib.get("meter.unit") or el.attrib.get("unit")
        if count is None or unit is None:
            return None
        try:
            count_f = sum(float(token) for token in str(count).split("+") if token.strip())
            unit_f = float(unit)
        except Exception:
            return None
        if count_f <= 0 or unit_f <= 0:
            return None
        return float(count_f * (4.0 / unit_f))

    active_span = float(fallback)
    spans: Dict[int, float] = {}
    for search_root in search_roots:
        for el in search_root.iter():
            name = _mei_local_name(el.tag)
            if name in {"scoreDef", "staffDef", "meterSig"}:
                declared_span = _span_from_element(el)
                if declared_span is not None:
                    active_span = declared_span
                continue
            if name != "measure" or id(el) not in target_ids:
                continue

            # A definition embedded at the beginning of a measure applies to
            # that measure. The iterator will encounter it again afterward,
            # keeping the value active for subsequent measures as well.
            for descendant in el.iter():
                if _mei_local_name(descendant.tag) not in {"scoreDef", "staffDef", "meterSig"}:
                    continue
                declared_span = _span_from_element(descendant)
                if declared_span is not None:
                    active_span = declared_span
                    break
            spans[id(el)] = float(active_span)

    # Defensive fallback for unusual documents whose performed measures are
    # outside the first music/body subtree selected above.
    for measure in target_measures:
        spans.setdefault(id(measure), float(active_span or fallback))
    return spans


def _mei_duration_to_quarters(
    el: Any,
    *,
    inherited_dur: Optional[str] = None,
    inherited_dots: Optional[str] = None,
    fallback: Optional[float] = None,
) -> Optional[float]:
    dur_raw = el.attrib.get("dur") or inherited_dur
    if dur_raw is None:
        return fallback
    token = str(dur_raw).strip().lower()
    base_map = {
        "maxima": 32.0,
        "long": 16.0,
        "longa": 16.0,
        "breve": 8.0,
        "brevis": 8.0,
        "1": 4.0,
        "2": 2.0,
        "4": 1.0,
        "8": 0.5,
        "16": 0.25,
        "32": 0.125,
        "64": 0.0625,
        "128": 0.03125,
        "256": 0.015625,
    }
    if token in base_map:
        base = base_map[token]
    else:
        try:
            denom = float(token)
        except Exception:
            return fallback
        if denom <= 0:
            return fallback
        base = 4.0 / denom

    dots_raw = el.attrib.get("dots")
    if dots_raw is None:
        dots_raw = inherited_dots
    try:
        dots = int(float(dots_raw)) if dots_raw is not None else 0
    except Exception:
        dots = 0
    multiplier = 1.0
    add = 0.5
    for _ in range(max(0, dots)):
        multiplier += add
        add *= 0.5
    return base * multiplier


def _extract_mei_symbolic_note_timing(
    mei_path: str,
) -> Tuple[Dict[str, Dict[str, Any]], List[float]]:
    """
    Extract source-MEI note timing from symbolic durations.

    This intentionally covers the common-notation constructs CAMAT currently
    compares against Verovio: measures, staves, layers, beams, tuplets, chords,
    notes, rests, spaces, and mRests. It lets the Partitura backend avoid known
    importer timing drift while keeping Partitura's pitch/spelling parsing.
    """
    if Path(mei_path).suffix.lower() != ".mei":
        return {}, []

    try:
        import xml.etree.ElementTree as ET

        root = ET.parse(mei_path).getroot()
    except Exception:
        return {}, []

    timing: Dict[str, Dict[str, Any]] = {}
    idless_note_order = 0
    measure_offsets: List[float] = []
    current_offset = 0.0
    measures = _mei_music_measures(root)
    initial_meter_span = _mei_initial_meter_span(root)
    meter_spans = _mei_measure_meter_spans(
        root,
        measures,
        fallback=initial_meter_span,
    )
    regular_span = initial_meter_span
    previous_regular_span: Optional[float] = None

    def _children_named(el: Any, name: str) -> List[Any]:
        return [child for child in list(el) if _mei_local_name(child.tag) == name]

    def _store_note_timing(
        note: Any,
        *,
        cursor: float,
        duration: float,
        staff_n: Optional[str],
        layer_n: Optional[str],
    ) -> None:
        nonlocal idless_note_order
        nid = _mei_xml_id(note)
        source_idless = not bool(nid)
        if source_idless:
            idless_note_order += 1
            nid = f"__camat_internal_idless_note_{idless_note_order:08d}"
        timing[str(nid)] = {
            "Measure": float(len(measure_offsets)),
            "Local Onset": float(cursor),
            "Global Onset": float(current_offset + cursor),
            "Duration": float(duration),
            "staff_n": staff_n,
            "layer_n": layer_n,
            "_source_idless": source_idless,
            "_source_order": idless_note_order if source_idless else -1,
        }

    def _walk_timed(
        el: Any,
        cursor: float,
        *,
        inherited_dur: Optional[str] = None,
        inherited_dots: Optional[str] = None,
        duration_scale: float = 1.0,
        staff_n: Optional[str] = None,
        layer_n: Optional[str] = None,
    ) -> float:
        name = _mei_local_name(el.tag)

        if name in {"beam", "bTrem", "fTrem"}:
            for child in list(el):
                cursor = _walk_timed(
                    child,
                    cursor,
                    inherited_dur=inherited_dur,
                    inherited_dots=inherited_dots,
                    duration_scale=duration_scale,
                    staff_n=staff_n,
                    layer_n=layer_n,
                )
            return cursor

        if name == "tuplet":
            scale = duration_scale
            try:
                num = float(el.attrib.get("num", ""))
                numbase = float(el.attrib.get("numbase", ""))
                if num > 0 and numbase > 0:
                    scale *= numbase / num
            except Exception:
                pass
            for child in list(el):
                cursor = _walk_timed(
                    child,
                    cursor,
                    inherited_dur=el.attrib.get("dur") or inherited_dur,
                    inherited_dots=el.attrib.get("dots") or inherited_dots,
                    duration_scale=scale,
                    staff_n=staff_n,
                    layer_n=layer_n,
                )
            return cursor

        if name == "chord":
            dur = _mei_duration_to_quarters(
                el,
                inherited_dur=inherited_dur,
                inherited_dots=inherited_dots,
                fallback=0.0,
            )
            dur = float(dur or 0.0) * duration_scale
            for note in _children_named(el, "note"):
                note_dur = _mei_duration_to_quarters(
                    note,
                    inherited_dur=el.attrib.get("dur") or inherited_dur,
                    inherited_dots=el.attrib.get("dots") or inherited_dots,
                    fallback=dur / duration_scale if duration_scale else dur,
                )
                _store_note_timing(
                    note,
                    cursor=cursor,
                    duration=float(note_dur or 0.0) * duration_scale,
                    staff_n=staff_n,
                    layer_n=layer_n,
                )
            return cursor + dur

        if name == "note":
            dur = _mei_duration_to_quarters(
                el,
                inherited_dur=inherited_dur,
                inherited_dots=inherited_dots,
                fallback=0.0,
            )
            dur = float(dur or 0.0) * duration_scale
            _store_note_timing(
                el,
                cursor=cursor,
                duration=dur,
                staff_n=staff_n,
                layer_n=layer_n,
            )
            return cursor + dur

        if name in {"rest", "space"}:
            dur = _mei_duration_to_quarters(
                el,
                inherited_dur=inherited_dur,
                inherited_dots=inherited_dots,
                fallback=0.0,
            )
            return cursor + (float(dur or 0.0) * duration_scale)

        if name in {"mRest", "multiRest"}:
            dur = _mei_duration_to_quarters(
                el,
                inherited_dur=inherited_dur,
                inherited_dots=inherited_dots,
                fallback=regular_span,
            )
            return cursor + (float(dur or regular_span) * duration_scale)

        for child in list(el):
            cursor = _walk_timed(
                child,
                cursor,
                inherited_dur=inherited_dur,
                inherited_dots=inherited_dots,
                duration_scale=duration_scale,
                staff_n=staff_n,
                layer_n=layer_n,
            )
        return cursor

    for measure_index, measure in enumerate(measures):
        regular_span = meter_spans.get(id(measure), regular_span)
        meter_changed = (
            previous_regular_span is not None
            and abs(float(regular_span) - float(previous_regular_span)) > 1e-6
        )
        measure_offsets.append(float(current_offset))
        layer_spans: List[float] = []
        for staff_index, staff in enumerate(_children_named(measure, "staff"), start=1):
            staff_n = str(staff.attrib.get("n") or staff_index).strip()
            for layer_index, layer in enumerate(_children_named(staff, "layer"), start=1):
                layer_n = str(layer.attrib.get("n") or layer_index).strip()
                span = _walk_timed(
                    layer,
                    0.0,
                    staff_n=staff_n,
                    layer_n=layer_n,
                )
                if np.isfinite(span) and span > 0:
                    layer_spans.append(float(span))
        actual_span = max(layer_spans) if layer_spans else 0.0
        # Humdrum-to-MEI conversion uses an unnumbered measure for short
        # transition/anacrusis fragments even when it omits @metcon="false".
        # Treating those as a full bar shifts every later onset.
        is_irregular = (
            str(measure.attrib.get("metcon", "")).strip().lower() == "false"
            or not str(measure.attrib.get("n", "")).strip()
        )
        is_initial_pickup = measure_index == 0 and 0 < actual_span < regular_span
        is_section_boundary = str(measure.attrib.get("right", "")).strip().lower() in {
            "dbl",
            "end",
        }
        content_defines_span = (
            is_irregular
            or is_initial_pickup
            or is_section_boundary
            or actual_span > regular_span + 1e-6
            or (meter_changed and 0 < actual_span < regular_span - 1e-6)
        )
        if content_defines_span and actual_span > 0:
            measure_span = actual_span
        else:
            measure_span = regular_span
        current_offset += float(measure_span)
        previous_regular_span = regular_span

    return timing, measure_offsets


def _extract_mei_tie_next_map(mei_path: str) -> Dict[str, str]:
    if Path(mei_path).suffix.lower() != ".mei":
        return {}
    try:
        import xml.etree.ElementTree as ET

        root = ET.parse(mei_path).getroot()
    except Exception:
        return {}
    out: Dict[str, str] = {}
    for el in root.iter():
        if _mei_local_name(el.tag) != "tie":
            continue
        start = _normalize_xml_ref(el.attrib.get("startid"))
        end = _normalize_xml_ref(el.attrib.get("endid"))
        if start and end:
            out[start] = end
    return out


def _apply_mei_symbolic_timing_to_pitch_df(
    df_pitch: pd.DataFrame,
    timing: Mapping[str, Mapping[str, float]],
    *,
    collapse_tied_pitch_events: bool,
    tie_next: Optional[Mapping[str, str]] = None,
) -> pd.DataFrame:
    if (
        not isinstance(df_pitch, pd.DataFrame)
        or df_pitch.empty
        or "xml_id" not in df_pitch.columns
        or not timing
    ):
        return df_pitch

    out = df_pitch.copy()
    tie_next = tie_next or {}

    def _collapsed_duration(xml_id: str, base_duration: float) -> float:
        if not collapse_tied_pitch_events:
            return base_duration
        total = base_duration
        current = xml_id
        seen = {xml_id}
        while current in tie_next:
            nxt = tie_next[current]
            if nxt in seen:
                break
            seen.add(nxt)
            nxt_info = timing.get(nxt)
            if nxt_info is None:
                break
            try:
                total += float(nxt_info.get("Duration", 0.0))
            except Exception:
                break
            current = nxt
        return total

    for idx, raw_id in out["xml_id"].items():
        xml_id = _clean_xml_id_value(raw_id)
        if not xml_id:
            continue
        info = timing.get(xml_id)
        if info is None:
            continue
        try:
            out.at[idx, "Measure"] = int(float(info["Measure"]))
            out.at[idx, "Local Onset"] = float(info["Local Onset"])
            out.at[idx, "Global Onset"] = float(info["Global Onset"])
            out.at[idx, "Duration"] = _collapsed_duration(
                xml_id,
                float(info["Duration"]),
            )
        except Exception:
            continue

    return out


def _apply_mei_idless_symbolic_timing_to_pitch_df(
    df_pitch: pd.DataFrame,
    timing: Mapping[str, Mapping[str, Any]],
    *,
    staff_to_part: Mapping[str, str],
) -> pd.DataFrame:
    """Correct and anonymize Partitura rows generated from idless MEI notes.

    Partitura assigns transient ids to source notes without ``xml:id``. Match
    those rows within each canonical voice by stable musical order, apply the
    source-symbolic timing, and restore ``NA`` so CAMAT does not expose a
    backend-generated identifier as if it came from the MEI document.
    """
    if (
        not isinstance(df_pitch, pd.DataFrame)
        or df_pitch.empty
        or "xml_id" not in df_pitch.columns
        or not timing
    ):
        return df_pitch

    idless_infos = [
        dict(info)
        for info in timing.values()
        if bool(info.get("_source_idless"))
    ]
    if not idless_infos:
        return df_pitch

    source_ids = {
        str(xml_id)
        for xml_id, info in timing.items()
        if not bool(info.get("_source_idless"))
    }
    out = df_pitch.copy()
    candidate_indices = [
        idx
        for idx, raw_id in out["xml_id"].items()
        if (_clean_xml_id_value(raw_id) or "") not in source_ids
    ]
    if not candidate_indices:
        return out

    source_groups: Dict[str, List[Dict[str, Any]]] = {}
    for info in idless_infos:
        staff_n = str(info.get("staff_n") or "").strip()
        layer_n = str(info.get("layer_n") or "1").strip() or "1"
        part_label = str(staff_to_part.get(staff_n, f"P{staff_n}")).strip()
        voice = _format_voice_label(part_label, layer_n)
        source_groups.setdefault(voice, []).append(info)

    parsed_groups: Dict[str, List[Any]] = {}
    for idx in candidate_indices:
        voice = str(out.at[idx, "Voice"]).strip()
        parsed_groups.setdefault(voice, []).append(idx)

    for key, infos in source_groups.items():
        indices = parsed_groups.get(key, [])
        if len(indices) != len(infos):
            continue
        infos.sort(
            key=lambda info: (
                float(info.get("Global Onset", 0.0)),
                int(info.get("_source_order", 0)),
            )
        )
        indices.sort(
            key=lambda idx: (
                float(out.at[idx, "Global Onset"]),
                float(out.at[idx, "MIDI"]) if "MIDI" in out.columns else 0.0,
                int(idx) if isinstance(idx, (int, np.integer)) else 0,
            )
        )
        for idx, info in zip(indices, infos):
            try:
                out.at[idx, "Measure"] = int(float(info["Measure"]))
                out.at[idx, "Local Onset"] = float(info["Local Onset"])
                out.at[idx, "Global Onset"] = float(info["Global Onset"])
                out.at[idx, "Duration"] = float(info["Duration"])
                out.at[idx, "xml_id"] = pd.NA
            except Exception:
                continue
    return out


def _apply_mei_source_voice_labels_to_pitch_df(
    df_pitch: pd.DataFrame,
    timing: Mapping[str, Mapping[str, Any]],
    *,
    staff_to_part: Mapping[str, str],
) -> pd.DataFrame:
    """Derive note voices from source staff/layer membership, keyed by xml:id."""
    if (
        not isinstance(df_pitch, pd.DataFrame)
        or df_pitch.empty
        or "xml_id" not in df_pitch.columns
        or "Voice" not in df_pitch.columns
    ):
        return df_pitch
    out = df_pitch.copy()
    for idx, raw_id in out["xml_id"].items():
        xml_id = _clean_xml_id_value(raw_id)
        info = timing.get(xml_id or "")
        if not info or bool(info.get("_source_idless")):
            continue
        staff_n = str(info.get("staff_n") or "").strip()
        if not staff_n:
            continue
        layer_n = str(info.get("layer_n") or "1").strip() or "1"
        part_label = str(staff_to_part.get(staff_n, f"P{staff_n}")).strip()
        out.at[idx, "Voice"] = _format_voice_label(part_label, layer_n)
    return out


def _remap_pitch_part_labels(
    df_pitch: pd.DataFrame,
    parsed_staff_to_part: Mapping[str, str],
    source_staff_to_part: Mapping[str, str],
) -> pd.DataFrame:
    """Replace importer-generated part labels with canonical source labels."""
    if not isinstance(df_pitch, pd.DataFrame) or df_pitch.empty or "Voice" not in df_pitch:
        return df_pitch
    replacements = {
        str(parsed_staff_to_part[staff_n]).strip(): str(source_label).strip()
        for staff_n, source_label in source_staff_to_part.items()
        if staff_n in parsed_staff_to_part
        and str(parsed_staff_to_part[staff_n]).strip() != str(source_label).strip()
    }
    if not replacements:
        return df_pitch
    out = df_pitch.copy()
    for idx, raw_voice in out["Voice"].items():
        voice = str(raw_voice)
        for old_label, new_label in replacements.items():
            prefix = f"{old_label} - Voice "
            if voice.startswith(prefix):
                out.at[idx, "Voice"] = f"{new_label} - Voice {voice[len(prefix):]}"
                break
    return out


def _count_mei_symbolic_timing_mismatches(
    df_pitch: pd.DataFrame,
    timing: Mapping[str, Mapping[str, float]],
    *,
    collapse_tied_pitch_events: bool,
    tie_next: Optional[Mapping[str, str]] = None,
    onset_shift: float = 0.0,
    tolerance: float = 1e-6,
) -> Tuple[int, int]:
    if (
        not isinstance(df_pitch, pd.DataFrame)
        or df_pitch.empty
        or "xml_id" not in df_pitch.columns
        or not {"Duration", "Global Onset"}.issubset(df_pitch.columns)
        or not timing
    ):
        return 0, 0

    tie_next = tie_next or {}

    def _source_duration(xml_id: str, base_duration: float) -> float:
        if not collapse_tied_pitch_events:
            return base_duration
        total = base_duration
        current = xml_id
        seen = {xml_id}
        while current in tie_next:
            nxt = tie_next[current]
            if nxt in seen:
                break
            seen.add(nxt)
            nxt_info = timing.get(nxt)
            if nxt_info is None:
                break
            total += float(nxt_info.get("Duration", 0.0))
            current = nxt
        return total

    duration_mismatches = 0
    onset_mismatches = 0
    for _, row in df_pitch.iterrows():
        xml_id = _clean_xml_id_value(row.get("xml_id"))
        if not xml_id:
            continue
        info = timing.get(xml_id)
        if info is None:
            continue
        try:
            parsed_duration = float(row.get("Duration"))
            expected_duration = _source_duration(xml_id, float(info["Duration"]))
            parsed_onset = float(row.get("Global Onset"))
            expected_onset = float(info["Global Onset"]) + float(onset_shift)
        except Exception:
            continue
        if abs(parsed_duration - expected_duration) > tolerance:
            duration_mismatches += 1
        if abs(parsed_onset - expected_onset) > tolerance:
            onset_mismatches += 1
    return duration_mismatches, onset_mismatches


def _normalize_xml_ref(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    try:
        value = str(raw).strip()
    except Exception:
        return None
    if not value:
        return None
    return value.lstrip("#")


def _clean_string(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    try:
        value = str(raw).strip()
    except Exception:
        return None
    return value or None


def _coerce_number(raw: Any) -> Any:
    text = _clean_string(raw)
    if text is None:
        return None
    try:
        value = float(text)
    except Exception:
        return text
    if not np.isfinite(value):
        return text
    if float(value).is_integer():
        return int(value)
    return float(value)


def _event_voice_label(staff_n: Any, layer_n: Any) -> Any:
    if staff_n is None:
        return pd.NA
    staff_s = str(staff_n).strip()
    if not staff_s:
        return pd.NA
    voice_label = f"Staff {staff_s}"
    if layer_n is not None:
        layer_s = str(layer_n).strip()
        if layer_s:
            voice_label = f"{voice_label} - Layer {layer_s}"
    return voice_label


def _empty_event_dataframe() -> pd.DataFrame:
    return pd.DataFrame(columns=list(_EVENT_DF_COLUMNS))


def _mei_event_merge_key(event: Mapping[str, Any]) -> Tuple[str, ...]:
    """
    Build a stable merge key for source/converted MEI events.

    Barline events often lack xml:id and measure markup in mensural sources, so
    include their per-staff ordering and neighboring note anchors to avoid
    collapsing distinct barlines into one row.
    """

    def _norm(value: Any) -> str:
        cleaned = _clean_string(value)
        return cleaned if cleaned is not None else ""

    event_type = _norm(event.get("event")).lower()
    parts = [
        event_type,
        _norm(event.get("subtype")),
        _norm(event.get("xml_id")),
        _norm(event.get("start_xml_id")),
        _norm(event.get("end_xml_id")),
        _norm(event.get("measure_index")),
        _norm(event.get("measure")),
        _norm(event.get("measure_xml_id")),
        _norm(event.get("staff_n")),
        _norm(event.get("layer_n")),
        _norm(event.get("tstamp_raw")),
        _norm(event.get("tstamp2_raw")),
        _norm(event.get("text")),
        _norm(event.get("verse_n")),
        _norm(event.get("wordpos")),
        _norm(event.get("con")),
        _norm(event.get("form")),
    ]
    if event_type == "barline":
        parts.extend(
            [
                _norm(event.get("barline_ordinal")),
                _norm(event.get("prev_note_xml_id")),
                _norm(event.get("next_note_xml_id")),
                _norm(event.get("prev_note_ordinal_staff")),
            ]
        )
    return tuple(parts)


def _dedupe_mei_events_prefer_anchored(
    events: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Drop weaker duplicate lyric/text events when the same semantic event appears
    both with and without usable anchors in the source MEI.
    """
    if not events:
        return [], 0

    keyed_indices: Dict[Tuple[str, str, str, str, str, str, str, str], List[int]] = {}
    out: List[Dict[str, Any]] = [dict(evt) for evt in events]

    for idx, event in enumerate(out):
        event_type = str(event.get("event", "") or "").strip().lower()
        if event_type not in {"lyric", "direction", "dynamic", "tempo", "reh", "harm"}:
            continue
        key = (
            event_type,
            str(event.get("measure", "") or "").strip(),
            str(event.get("staff_n", "") or "").strip(),
            str(event.get("layer_n", "") or "").strip(),
            str(event.get("text", "") or "").strip(),
            str(event.get("verse_n", "") or "").strip(),
            str(event.get("wordpos", "") or "").strip(),
            str(event.get("con", "") or "").strip(),
        )
        keyed_indices.setdefault(key, []).append(idx)

    drop_indices: set[int] = set()

    def _anchor_rank(event: Mapping[str, Any]) -> int:
        rank = 0
        if _clean_string(event.get("start_xml_id")):
            rank += 4
        if _clean_string(event.get("end_xml_id")):
            rank += 2
        if _clean_string(event.get("xml_id")):
            rank += 1
        if _clean_string(event.get("tstamp_raw")):
            rank += 1
        if _clean_string(event.get("tstamp2_raw")):
            rank += 1
        return rank

    for indices in keyed_indices.values():
        if len(indices) < 2:
            continue
        ranks = [_anchor_rank(out[i]) for i in indices]
        best_rank = max(ranks)
        if best_rank <= 0:
            continue
        for idx, rank in zip(indices, ranks):
            if rank <= 0:
                drop_indices.add(idx)

    if not drop_indices:
        return out, 0

    filtered = [evt for idx, evt in enumerate(out) if idx not in drop_indices]
    return filtered, len(drop_indices)


def _event_row(
    *,
    event: Mapping[str, Any],
    event_type: str,
    global_onset: Any,
    duration: Any,
    local_onset: Any,
    text_role: Any = pd.NA,
) -> Dict[str, Any]:
    start_xml_id = _normalize_xml_ref(event.get("start_xml_id"))
    end_xml_id = _normalize_xml_ref(event.get("end_xml_id"))
    mm_value = event.get("mm")
    mm_unit = event.get("mm_unit", pd.NA)
    mm_dots = event.get("mm_dots", pd.NA)
    return {
        "type": event_type,
        "subtype": event.get("subtype", pd.NA),
        "Measure": event.get("measure"),
        "Local Onset": local_onset,
        "Global Onset": global_onset,
        "Duration": duration,
        "Voice": _event_voice_label(event.get("staff_n"), event.get("layer_n")),
        "xml_id": event.get("xml_id", pd.NA),
        "start_xml_id": start_xml_id if start_xml_id else pd.NA,
        "end_xml_id": end_xml_id if end_xml_id else pd.NA,
        "staff_n": event.get("staff_n", pd.NA),
        "staff_raw": event.get("staff_raw", pd.NA),
        "layer_n": event.get("layer_n", pd.NA),
        "layer_raw": event.get("layer_raw", pd.NA),
        "scope": event.get("scope", pd.NA),
        "text": event.get("text", pd.NA),
        "text_role": text_role,
        "form": event.get("form", pd.NA),
        "place": event.get("place", pd.NA),
        "func": event.get("func", pd.NA),
        "plist": event.get("plist", pd.NA),
        "tstamp_raw": event.get("tstamp_raw", pd.NA),
        "tstamp2_raw": event.get("tstamp2_raw", pd.NA),
        "verse_n": event.get("verse_n", pd.NA),
        "wordpos": event.get("wordpos", pd.NA),
        "con": event.get("con", pd.NA),
        "mm": mm_value if mm_value is not None else pd.NA,
        "mm_unit": mm_unit,
        "mm_dots": mm_dots,
        "measure_type": event.get("measure_type", pd.NA),
        "measure_metcon": event.get("measure_metcon", pd.NA),
        "measure_join": event.get("measure_join", pd.NA),
        "measure_n": event.get("measure_n", pd.NA),
        "extra": event.get("extra", pd.NA),
    }


def _measure_start_from_offsets(
    measure_index: Any,
    measure_offsets: Sequence[float],
) -> Optional[float]:
    offsets: List[float] = []
    for value in measure_offsets:
        try:
            fval = float(value)
        except Exception:
            continue
        if np.isfinite(fval):
            offsets.append(fval)
    if not offsets:
        return None

    try:
        idx = int(measure_index)
    except Exception:
        return None
    if idx <= 0:
        return None
    if idx <= len(offsets):
        return float(offsets[idx - 1])

    if len(offsets) >= 2:
        step = offsets[-1] - offsets[-2]
        if np.isfinite(step) and step > 0:
            return float(offsets[-1] + step * (idx - len(offsets)))
    return None


def _infer_measure_position_from_global_onset(
    global_onset: Any,
    measure_offsets: Sequence[float],
) -> Tuple[Optional[int], float]:
    offsets: List[float] = []
    for value in measure_offsets:
        try:
            fval = float(value)
        except Exception:
            continue
        if np.isfinite(fval):
            offsets.append(fval)
    if not offsets:
        return None, np.nan

    try:
        onset = float(global_onset)
    except Exception:
        return None, np.nan
    if not np.isfinite(onset):
        return None, np.nan

    idx = int(np.searchsorted(offsets, onset, side="right") - 1)
    if idx < 0:
        idx = 0
    if idx >= len(offsets):
        idx = len(offsets) - 1
    measure_start = offsets[idx]
    return idx + 1, float(onset - measure_start)


def _resolve_measure_tstamp(
    measure_index: Any,
    tstamp_value: Any,
    measure_offsets: Sequence[float],
) -> Optional[float]:
    measure_start = _measure_start_from_offsets(measure_index, measure_offsets)
    if measure_start is None or tstamp_value is None:
        return None
    try:
        beat = float(str(tstamp_value).strip())
    except Exception:
        return None
    if not np.isfinite(beat):
        return None
    rel = beat if beat < 1.0 else beat - 1.0
    return float(measure_start + rel)


def _resolve_measure_tstamp2(
    measure_index: Any,
    tstamp2_value: Any,
    measure_offsets: Sequence[float],
) -> Optional[float]:
    if tstamp2_value is None:
        return None
    import re

    text = str(tstamp2_value).strip()
    if not text:
        return None
    match = re.fullmatch(r"(?:(\d+)m\+)?([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return None
    measure_delta = int(match.group(1) or "0")
    beat = float(match.group(2))
    if not np.isfinite(beat):
        return None
    try:
        base_index = int(measure_index)
    except Exception:
        return None
    target_index = base_index + measure_delta
    measure_start = _measure_start_from_offsets(target_index, measure_offsets)
    if measure_start is None:
        return None
    rel = beat if beat < 1.0 else beat - 1.0
    return float(measure_start + rel)


def _note_timing_maps(df_pitch: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, float]]:
    if "xml_id" not in df_pitch.columns:
        return {}, {}
    work = df_pitch[["xml_id", "Global Onset", "Duration"]].copy()
    work["xml_id"] = work["xml_id"].astype(str).str.strip().str.lstrip("#")
    work = work[(work["xml_id"] != "") & work["xml_id"].notna()]
    if work.empty:
        return {}, {}
    grouped = work.groupby("xml_id", dropna=True)
    onset_map = grouped["Global Onset"].min().to_dict()
    work["end_onset"] = work["Global Onset"] + work["Duration"]
    end_map = work.groupby("xml_id", dropna=True)["end_onset"].max().to_dict()
    return onset_map, end_map


def _count_event_anchor_xml_id_overlap(
    events: Sequence[Mapping[str, Any]],
    df_pitch: pd.DataFrame,
    *,
    anchor_keys: Sequence[str] = (
        "prev_note_xml_id",
        "next_note_xml_id",
        "start_xml_id",
        "end_xml_id",
    ),
) -> Tuple[int, int]:
    if not events or "xml_id" not in df_pitch.columns:
        return 0, 0

    pitch_ids = {
        value
        for value in (
            _normalize_xml_ref(raw)
            for raw in df_pitch["xml_id"].dropna().astype(str)
        )
        if value
    }
    if not pitch_ids:
        return 0, 0

    event_anchor_ids = {
        value
        for event in events
        for value in (_normalize_xml_ref(event.get(key)) for key in anchor_keys)
        if value
    }
    if not event_anchor_ids:
        return 0, 0

    return len(event_anchor_ids & pitch_ids), len(event_anchor_ids)


_MEI_EVENTS_CACHE_MAX = 32
_MEI_EVENTS_CACHE: Dict[Tuple[str, float, int], List[Dict[str, Any]]] = {}


def _mei_events_cache_key(mei_path: str) -> Optional[Tuple[str, float, int]]:
    try:
        st = os.stat(mei_path)
    except OSError:
        return None
    return (os.path.abspath(mei_path), float(st.st_mtime), int(st.st_size))


def _clone_mei_events(events: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Return shallow copies of cached event dicts so callers can mutate freely."""
    out: List[Dict[str, Any]] = []
    for evt in events:
        clone = dict(evt)
        extra = clone.get("extra")
        if isinstance(extra, dict):
            clone["extra"] = dict(extra)
        out.append(clone)
    return out


def _extract_mei_events(mei_path: str) -> List[Dict[str, Any]]:
    """
    Extract supported MEI control/text elements as lightweight event dictionaries.

    Results are cached per (path, mtime, size) so repeated calls on the same
    file (common when partitura loads a sanitized copy pointing at the same
    bytes) don't re-walk the XML tree.
    """
    if Path(mei_path).suffix.lower() != ".mei":
        return []

    cache_key = _mei_events_cache_key(mei_path)
    if cache_key is not None:
        cached = _MEI_EVENTS_CACHE.get(cache_key)
        if cached is not None:
            return _clone_mei_events(cached)

    try:
        import xml.etree.ElementTree as ET

        root = ET.parse(mei_path).getroot()
    except Exception:
        return []

    def _local_name(tag: Any) -> str:
        raw = str(tag)
        return raw.rsplit("}", 1)[-1] if "}" in raw else raw

    def _get_xml_id(el: Any) -> Optional[str]:
        if el is None:
            return None
        raw = el.attrib.get(xml_id_key) or el.attrib.get("xml:id")
        return _normalize_xml_ref(raw)

    def _first_token(raw: Any) -> Optional[str]:
        if raw is None:
            return None
        try:
            tokens = [tok for tok in str(raw).strip().split() if tok]
        except Exception:
            return None
        return tokens[0] if tokens else None

    def _ancestor(el: Any, local_name: str) -> Any:
        cur = parent_map.get(el)
        while cur is not None and _local_name(cur.tag) != local_name:
            cur = parent_map.get(cur)
        return cur

    def _nearest_note_or_chord(el: Any) -> Any:
        cur = parent_map.get(el)
        while cur is not None:
            if _local_name(cur.tag) in {"note", "chord"}:
                return cur
            cur = parent_map.get(cur)
        return None

    def _first_note_or_chord_in_subtree(el: Any) -> Any:
        if el is None:
            return None
        for child in el.iter():
            if _local_name(child.tag) in {"note", "chord"}:
                return child
        return None

    def _last_note_or_chord_in_subtree(el: Any) -> Any:
        if el is None:
            return None
        last = None
        for child in el.iter():
            if _local_name(child.tag) in {"note", "chord"}:
                last = child
        return last

    def _count_note_or_chord_in_subtree(el: Any) -> int:
        if el is None:
            return 0
        count = 0
        for child in el.iter():
            if _local_name(child.tag) in {"note", "chord"}:
                count += 1
        return count

    def _first_timed_anchor_in_subtree(el: Any) -> Any:
        if el is None:
            return None
        for child in el.iter():
            if _local_name(child.tag) in {"note", "chord", "rest"}:
                return child
        return None

    def _last_timed_anchor_in_subtree(el: Any) -> Any:
        if el is None:
            return None
        last = None
        for child in el.iter():
            if _local_name(child.tag) in {"note", "chord", "rest"}:
                last = child
        return last

    def _count_timed_anchor_in_subtree(el: Any) -> int:
        if el is None:
            return 0
        count = 0
        for child in el.iter():
            if _local_name(child.tag) in {"note", "chord", "rest"}:
                count += 1
        return count

    def _clean_text(el: Any) -> Optional[str]:
        try:
            text = " ".join(" ".join(el.itertext()).split())
        except Exception:
            return None
        return text or None

    def _collect_extra_attrs(el: Any, consumed_keys: Sequence[str]) -> Dict[str, Any]:
        consumed = set(consumed_keys)
        out: Dict[str, Any] = {}
        for raw_key, raw_value in el.attrib.items():
            if raw_key == xml_id_key:
                continue
            key_name = _local_name(raw_key)
            if key_name in consumed:
                continue
            cleaned = _clean_string(raw_value)
            if cleaned is not None:
                out[key_name] = cleaned
        return out

    def _measure_metadata(measure_el: Any) -> Dict[str, Any]:
        if measure_el is None:
            return {}
        metadata: Dict[str, Any] = {}
        measure_type = _clean_string(measure_el.attrib.get("type"))
        measure_metcon = _clean_string(measure_el.attrib.get("metcon"))
        measure_join = _clean_string(measure_el.attrib.get("join"))
        measure_n = _clean_string(measure_el.attrib.get("n"))
        if measure_type is not None:
            metadata["measure_type"] = measure_type
        if measure_metcon is not None:
            metadata["measure_metcon"] = measure_metcon
        if measure_join is not None:
            metadata["measure_join"] = measure_join
        if measure_n is not None:
            metadata["measure_n"] = measure_n
        return metadata

    xml_id_key = "{http://www.w3.org/XML/1998/namespace}id"
    parent_map = {child: parent for parent in root.iter() for child in parent}
    measure_elements = [el for el in root.iter() if _local_name(el.tag) == "measure"]
    measure_index_map = {id(el): idx for idx, el in enumerate(measure_elements, start=1)}
    events: List[Dict[str, Any]] = []
    barline_ordinal = 0

    for measure_el in measure_elements:
        measure_index = measure_index_map.get(id(measure_el))
        measure_number: Optional[int] = None
        try:
            measure_number = int(str(measure_el.attrib.get("n")))
        except Exception:
            measure_number = measure_index
        measure_event: Dict[str, Any] = {
            "event": "measure",
            "scope": "measure",
        }
        if measure_index is not None:
            measure_event["measure_index"] = measure_index
        if measure_number is not None:
            measure_event["measure"] = measure_number
        measure_xml_id = _get_xml_id(measure_el)
        if measure_xml_id:
            measure_event["xml_id"] = measure_xml_id
            measure_event["measure_xml_id"] = measure_xml_id
        measure_event.update(_measure_metadata(measure_el))
        events.append(measure_event)

    # Per-layer precomputed indexes used by barline lookups. Without this, each
    # barline triggers multiple full subtree walks over its sibling children; the
    # combined work becomes quadratic in the number of notes in the layer.
    layer_index_cache: Dict[int, Dict[str, Any]] = {}

    def _layer_index(layer_el: Any) -> Dict[str, Any]:
        key = id(layer_el)
        cached = layer_index_cache.get(key)
        if cached is not None:
            return cached
        children = list(layer_el)
        child_info: List[Dict[str, Any]] = []
        cum_note = 0
        cum_timed = 0
        cum_notes: List[int] = []
        cum_timeds: List[int] = []
        for ch in children:
            first_note = None
            last_note = None
            first_timed = None
            last_timed = None
            note_count = 0
            timed_count = 0
            for sub in ch.iter():
                sub_name = _local_name(sub.tag)
                if sub_name in {"note", "chord"}:
                    if first_note is None:
                        first_note = sub
                    last_note = sub
                    note_count += 1
                    if first_timed is None:
                        first_timed = sub
                    last_timed = sub
                    timed_count += 1
                elif sub_name == "rest":
                    if first_timed is None:
                        first_timed = sub
                    last_timed = sub
                    timed_count += 1
            child_info.append(
                {
                    "first_note_id": _get_xml_id(first_note),
                    "last_note_id": _get_xml_id(last_note),
                    "first_timed_id": _get_xml_id(first_timed),
                    "last_timed_id": _get_xml_id(last_timed),
                    "note_count": note_count,
                    "timed_count": timed_count,
                }
            )
            cum_notes.append(cum_note)
            cum_timeds.append(cum_timed)
            cum_note += note_count
            cum_timed += timed_count
        # Map each child's python id to its sibling index for O(1) lookup.
        index_by_id = {id(ch): i for i, ch in enumerate(children)}
        cached = {
            "children": children,
            "child_info": child_info,
            "cum_notes_before": cum_notes,
            "cum_timed_before": cum_timeds,
            "index_by_id": index_by_id,
        }
        layer_index_cache[key] = cached
        return cached

    for el in root.iter():
        tag_name = _local_name(el.tag)
        if tag_name not in _MEI_EVENT_TYPE_MAP:
            continue

        # Note-internal markers (e.g. <accid> on a <note>) are already represented
        # by the pitch row; suppress them here to avoid duplicate events.
        if tag_name in _MEI_NOTE_INTERNAL_TAGS:
            parent_el = parent_map.get(el)
            parent_tag = _local_name(parent_el.tag) if parent_el is not None else ""
            if parent_tag in {"note", "chord"}:
                continue

        event_type = _MEI_EVENT_TYPE_MAP[tag_name]
        staff_el = _ancestor(el, "staff")
        layer_el = _ancestor(el, "layer")
        measure_el = _ancestor(el, "measure")

        staff_raw = _clean_string(el.attrib.get("staff"))
        layer_raw = _clean_string(el.attrib.get("layer"))
        staff_n = _first_token(staff_raw)
        if staff_n is None and staff_el is not None:
            staff_n = _first_token(staff_el.attrib.get("n"))
        layer_n = _first_token(layer_raw)
        if layer_n is None and layer_el is not None:
            layer_n = _first_token(layer_el.attrib.get("n"))

        measure_index: Optional[int] = None
        measure_number: Optional[int] = None
        if measure_el is not None:
            measure_index = measure_index_map.get(id(measure_el))
            try:
                measure_number = int(str(measure_el.attrib.get("n")))
            except Exception:
                measure_number = measure_index

        event: Dict[str, Any] = {
            "event": event_type,
            "scope": "point",
        }
        xml_id = _get_xml_id(el)
        if xml_id:
            event["xml_id"] = xml_id
        if measure_index is not None:
            event["measure_index"] = measure_index
        if measure_number is not None:
            event["measure"] = measure_number
        if measure_el is not None:
            measure_xml_id = _get_xml_id(measure_el)
            if measure_xml_id:
                event["measure_xml_id"] = measure_xml_id
            event.update(_measure_metadata(measure_el))
        if staff_n is not None:
            event["staff_n"] = staff_n
        if staff_raw is not None:
            event["staff_raw"] = staff_raw
        if layer_n is not None:
            event["layer_n"] = layer_n
        if layer_raw is not None:
            event["layer_raw"] = layer_raw

        start_xml_id = _normalize_xml_ref(el.attrib.get("startid"))
        end_xml_id = _normalize_xml_ref(el.attrib.get("endid"))
        if tag_name == "syl" and not start_xml_id:
            note_like_el = _nearest_note_or_chord(el)
            start_xml_id = _get_xml_id(note_like_el)
        if start_xml_id:
            event["start_xml_id"] = start_xml_id
        if end_xml_id:
            event["end_xml_id"] = end_xml_id

        tstamp = el.attrib.get("tstamp")
        if tstamp is not None:
            event["tstamp_raw"] = str(tstamp).strip()
        tstamp2 = el.attrib.get("tstamp2")
        if tstamp2 is not None:
            event["tstamp2_raw"] = str(tstamp2).strip()

        raw_type_value = _clean_string(el.attrib.get("type"))
        if raw_type_value is not None:
            event["subtype"] = raw_type_value

        form_value = el.attrib.get("form")
        if form_value is not None:
            form_s = str(form_value).strip()
            if form_s:
                event["form"] = form_s

        func_value = _clean_string(el.attrib.get("func"))
        if func_value is not None:
            event["func"] = func_value

        plist_value = _clean_string(el.attrib.get("plist"))
        if plist_value is not None:
            event["plist"] = plist_value

        mm_value = _coerce_number(el.attrib.get("mm"))
        if mm_value is not None:
            event["mm"] = mm_value

        mm_unit_value = _clean_string(el.attrib.get("mm.unit"))
        if mm_unit_value is not None:
            event["mm_unit"] = mm_unit_value

        mm_dots_value = _coerce_number(el.attrib.get("mm.dots"))
        if mm_dots_value is not None:
            event["mm_dots"] = mm_dots_value

        place_value = el.attrib.get("place")
        if place_value is None and tag_name in {"slur", "tie"}:
            place_value = el.attrib.get("curvedir")
        if place_value is not None:
            place_s = str(place_value).strip()
            if place_s:
                event["place"] = place_s

        text_value = _clean_text(el)
        if text_value:
            event["text"] = text_value
            event["text_role"] = event_type

        if tag_name == "syl":
            verse_el = _ancestor(el, "verse")
            verse_n = None if verse_el is None else _first_token(verse_el.attrib.get("n"))
            if verse_n:
                event["verse_n"] = verse_n
            wordpos = _clean_string(el.attrib.get("wordpos"))
            if wordpos:
                event["wordpos"] = wordpos
            con = _clean_string(el.attrib.get("con"))
            if con:
                event["con"] = con
            event["subtype"] = event.get("subtype", "syllable")
            event["text_role"] = "lyric"
            event["scope"] = "note_attached"

        if tag_name == "barLine":
            barline_ordinal += 1
            event["scope"] = "measure_end"
            event["form"] = str(el.attrib.get("form", "single")).strip() or "single"
            event["subtype"] = event.get("subtype", event["form"])
            event["barline_ordinal"] = barline_ordinal
            if layer_el is not None:
                try:
                    layer_idx = _layer_index(layer_el)
                except Exception:
                    layer_idx = None
                bar_idx = (
                    layer_idx["index_by_id"].get(id(el))
                    if layer_idx is not None
                    else None
                )
                if layer_idx is not None and bar_idx is not None:
                    child_info = layer_idx["child_info"]
                    cum_notes_before = layer_idx["cum_notes_before"]
                    cum_timed_before = layer_idx["cum_timed_before"]
                    n_children = len(child_info)

                    prev_note_id: Optional[str] = None
                    next_note_id: Optional[str] = None
                    prev_timed_id: Optional[str] = None
                    next_timed_id: Optional[str] = None

                    for j in range(bar_idx - 1, -1, -1):
                        candidate = child_info[j].get("last_note_id")
                        if candidate:
                            prev_note_id = candidate
                            break
                    for j in range(bar_idx - 1, -1, -1):
                        candidate = child_info[j].get("last_timed_id")
                        if candidate:
                            prev_timed_id = candidate
                            break
                    for j in range(bar_idx + 1, n_children):
                        candidate = child_info[j].get("first_note_id")
                        if candidate:
                            next_note_id = candidate
                            break
                    for j in range(bar_idx + 1, n_children):
                        candidate = child_info[j].get("first_timed_id")
                        if candidate:
                            next_timed_id = candidate
                            break

                    # Prefix-sum lookup: counts notes/timed anchors strictly before
                    # the barline child, matching the original sum() semantics.
                    prev_note_ordinal = (
                        cum_notes_before[bar_idx] if 0 <= bar_idx < n_children else 0
                    )
                    prev_timed_ordinal = (
                        cum_timed_before[bar_idx] if 0 <= bar_idx < n_children else 0
                    )

                    if prev_note_id:
                        event["prev_note_xml_id"] = prev_note_id
                    if next_note_id:
                        event["next_note_xml_id"] = next_note_id
                    if prev_note_ordinal > 0:
                        event["prev_note_ordinal_staff"] = int(prev_note_ordinal)
                    if prev_timed_id:
                        event["prev_timed_xml_id"] = prev_timed_id
                    if next_timed_id:
                        event["next_timed_xml_id"] = next_timed_id
                    if prev_timed_ordinal > 0:
                        event["prev_timed_ordinal_staff"] = int(prev_timed_ordinal)
        elif tag_name in {"slur", "tie", "hairpin", "phrase", "gliss"}:
            event["scope"] = "span"
            if tag_name == "hairpin" and "form" in event and "subtype" not in event:
                event["subtype"] = event["form"]
        elif tag_name in {"annot", "dynam", "dir", "tempo", "harm", "repeatMark", "harpPedal"} and "tstamp2_raw" in event:
            event["scope"] = "span"
        elif tag_name in _MEI_NOTE_ATTACHED_TAGS:
            # <artic>, <fing>, <bend> inside a <note>/<chord>: mirror the parent
            # note id into start_xml_id so downstream joins to df_pitch succeed,
            # and mark scope so consumers can filter note-attached vs. free events.
            parent_el = parent_map.get(el)
            parent_tag = _local_name(parent_el.tag) if parent_el is not None else ""
            if parent_tag in {"note", "chord"}:
                event["scope"] = "note_attached"
                if not event.get("start_xml_id"):
                    parent_id = _get_xml_id(parent_el)
                    if parent_id:
                        event["start_xml_id"] = parent_id
            attr_val = _clean_string(el.attrib.get("artic")) if tag_name == "artic" else None
            if attr_val is None and tag_name == "fing":
                attr_val = _clean_string(el.attrib.get("value"))
            if attr_val and "subtype" not in event:
                event["subtype"] = attr_val
            if attr_val and not event.get("text"):
                event["text"] = attr_val
                event["text_role"] = event_type
        elif tag_name in {"trill", "mordent", "turn", "ornam", "bTrem", "fTrem"}:
            event["scope"] = "note_attached" if start_xml_id else "point"
            glyph = _clean_string(el.attrib.get("glyph.name")) or _clean_string(
                el.attrib.get("form")
            )
            if glyph and "subtype" not in event:
                event["subtype"] = glyph
        elif tag_name == "pedal":
            pedal_dir = _clean_string(el.attrib.get("dir"))
            if pedal_dir and "subtype" not in event:
                event["subtype"] = pedal_dir
            event["scope"] = "span" if "tstamp2_raw" in event or end_xml_id else "point"
        elif tag_name == "octave":
            dis_val = _clean_string(el.attrib.get("dis"))
            dis_place = _clean_string(el.attrib.get("dis.place"))
            if dis_val and "subtype" not in event:
                event["subtype"] = f"{dis_val}{dis_place or ''}"
            event["scope"] = "span"
        elif tag_name == "ending":
            event["scope"] = "span"
            n_val = _clean_string(el.attrib.get("n"))
            if n_val and "form" not in event:
                event["form"] = n_val
        elif tag_name in {"beamSpan", "tupletSpan"}:
            event["scope"] = "span"
        elif tag_name in {"clef", "keySig", "meterSig"}:
            ancestor_tags: Set[str] = set()
            cur = parent_map.get(el)
            # Walk up at most ~6 ancestors; scoreDef/staffDef lives shallow.
            hops = 0
            while cur is not None and hops < 8:
                ancestor_tags.add(_local_name(cur.tag))
                cur = parent_map.get(cur)
                hops += 1
            is_setup = bool(ancestor_tags & _MEI_DEFINITION_ANCESTORS)
            event["scope"] = "setup" if is_setup else "change"
            # Inherit staff from the surrounding <staffDef n="..."> when the
            # element has no explicit staff/@layer.
            if staff_n is None and "staffDef" in ancestor_tags:
                staff_def = _ancestor(el, "staffDef")
                if staff_def is not None:
                    staff_n = _first_token(staff_def.attrib.get("n"))
                    if staff_n is not None:
                        event["staff_n"] = staff_n
            # Capture the interesting attributes into subtype/form/extra.
            if tag_name == "clef":
                shape = _clean_string(el.attrib.get("shape"))
                line = _clean_string(el.attrib.get("line"))
                dis = _clean_string(el.attrib.get("dis"))
                dis_place = _clean_string(el.attrib.get("dis.place"))
                parts = []
                if shape:
                    parts.append(shape)
                if line:
                    parts.append(line)
                if dis:
                    parts.append(f"{dis}{dis_place or ''}")
                if parts and "subtype" not in event:
                    event["subtype"] = "-".join(parts)
            elif tag_name == "keySig":
                sig = _clean_string(el.attrib.get("sig"))
                mode = _clean_string(el.attrib.get("mode"))
                if sig and "subtype" not in event:
                    event["subtype"] = sig if not mode else f"{sig}-{mode}"
            elif tag_name == "meterSig":
                count = _clean_string(el.attrib.get("count"))
                unit = _clean_string(el.attrib.get("unit"))
                sym = _clean_string(el.attrib.get("sym"))
                if count and unit and "subtype" not in event:
                    event["subtype"] = f"{count}/{unit}"
                elif sym and "subtype" not in event:
                    event["subtype"] = sym
        elif tag_name in {"mRest", "multiRest", "space"}:
            event["scope"] = "timeline"
            if tag_name == "multiRest":
                num_val = _coerce_number(el.attrib.get("num"))
                if num_val is not None:
                    event["form"] = str(int(num_val)) if float(num_val).is_integer() else str(num_val)
                    event["extra"] = {"measures": int(num_val)} if float(num_val).is_integer() else {"measures": num_val}
            if tag_name == "space":
                event["subtype"] = event.get("subtype", "space")
        elif tag_name == "custos":
            event["scope"] = "point"
            pname = _clean_string(el.attrib.get("pname"))
            octv = _clean_string(el.attrib.get("oct"))
            if pname and "subtype" not in event:
                event["subtype"] = f"{pname.upper()}{octv or ''}"
        elif tag_name == "accid":
            event["scope"] = "point"
            accid_val = _clean_string(el.attrib.get("accid")) or _clean_string(
                el.attrib.get("accid.ges")
            )
            if accid_val and "subtype" not in event:
                event["subtype"] = accid_val

        extra_attrs = _collect_extra_attrs(
            el,
            consumed_keys=[
                "staff",
                "layer",
                "startid",
                "endid",
                "tstamp",
                "tstamp2",
                "type",
                "form",
                "place",
                "curvedir",
                "func",
                "plist",
                "mm",
                "mm.unit",
                "mm.dots",
                "wordpos",
                "con",
                "n",
                # clef / keySig / meterSig
                "shape",
                "line",
                "dis",
                "dis.place",
                "sig",
                "mode",
                "count",
                "unit",
                "sym",
                # multiRest / space
                "num",
                # ornaments / articulations / bend
                "artic",
                "value",
                "glyph.name",
                # pedal
                "dir",
                # accid
                "accid",
                "accid.ges",
                # custos
                "pname",
                "oct",
            ],
        )
        if extra_attrs:
            event["extra"] = extra_attrs

        events.append(event)

    if cache_key is not None:
        if len(_MEI_EVENTS_CACHE) >= _MEI_EVENTS_CACHE_MAX:
            # FIFO-ish eviction; keeps the cache bounded across long notebook sessions.
            try:
                oldest_key = next(iter(_MEI_EVENTS_CACHE))
                _MEI_EVENTS_CACHE.pop(oldest_key, None)
            except StopIteration:
                pass
        _MEI_EVENTS_CACHE[cache_key] = _clone_mei_events(events)

    return events


def _extract_mei_barline_events(mei_path: str) -> List[Dict[str, Any]]:
    return [evt for evt in _extract_mei_events(mei_path) if evt.get("event") == "barline"]


def _attach_barline_event_offsets(
    barline_events: Sequence[Dict[str, Any]],
    measure_offsets: Sequence[float],
) -> List[Dict[str, Any]]:
    """
    Add global onset estimates to barline events using parsed measure starts.
    """
    offsets = [float(x) for x in measure_offsets if np.isfinite(float(x))]
    if not offsets or not barline_events:
        return [dict(evt) for evt in barline_events]

    out: List[Dict[str, Any]] = []
    n_offsets = len(offsets)
    last_step: Optional[float] = None
    if n_offsets >= 2:
        step = offsets[-1] - offsets[-2]
        if np.isfinite(step) and step > 0:
            last_step = float(step)

    local_counters: Dict[Tuple[str, str], int] = {}
    for event in barline_events:
        enriched = dict(event)
        try:
            existing = float(enriched.get("global_onset"))
            if np.isfinite(existing):
                out.append(enriched)
                continue
        except Exception:
            pass
        staff_key = str(event.get("staff_n", "") or "").strip()
        layer_key = str(event.get("layer_n", "") or "").strip()
        group_key = (staff_key, layer_key)
        local_counters[group_key] = local_counters.get(group_key, 0) + 1
        local_ordinal = local_counters[group_key]
        if staff_key:
            enriched["barline_ordinal_staff"] = local_ordinal
        try:
            measure_index = int(event.get("measure_index", 0))
        except Exception:
            measure_index = 0

        if 1 <= measure_index < n_offsets:
            enriched["global_onset"] = float(offsets[measure_index])
        elif measure_index == n_offsets and last_step is not None:
            enriched["global_onset"] = float(offsets[-1] + last_step)
        else:
            # Prefer local staff/layer ordinal to avoid cross-staff drift.
            if staff_key and 1 <= local_ordinal < n_offsets:
                enriched["global_onset"] = float(offsets[local_ordinal])
                out.append(enriched)
                continue
            if staff_key and local_ordinal == n_offsets and last_step is not None:
                enriched["global_onset"] = float(offsets[-1] + last_step)
                out.append(enriched)
                continue
            try:
                ordinal = int(event.get("barline_ordinal", 0))
            except Exception:
                ordinal = 0
            if 1 <= ordinal < n_offsets:
                enriched["global_onset"] = float(offsets[ordinal])
            elif ordinal == n_offsets and last_step is not None:
                enriched["global_onset"] = float(offsets[-1] + last_step)

        out.append(enriched)
    return out


def _attach_barline_event_onsets_from_pitch_df(
    barline_events: Sequence[Dict[str, Any]],
    df_pitch: pd.DataFrame,
    *,
    staff_to_part_label: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    """
    Anchor barline onsets using neighboring timed xml:ids in the provided timeline.
    """
    if not barline_events:
        return []
    if "xml_id" not in df_pitch.columns:
        return [dict(evt) for evt in barline_events]

    work = df_pitch[["xml_id", "Global Onset", "Duration"]].copy()
    work["xml_id"] = work["xml_id"].astype(str).str.strip().str.lstrip("#")
    work = work[(work["xml_id"] != "") & work["xml_id"].notna()]
    if work.empty:
        return [dict(evt) for evt in barline_events]

    grouped = work.groupby("xml_id", dropna=True)
    onset_map = grouped["Global Onset"].min().to_dict()
    work["end_onset"] = work["Global Onset"] + work["Duration"]
    end_map = work.groupby("xml_id", dropna=True)["end_onset"].max().to_dict()

    out: List[Dict[str, Any]] = []
    voice_event_cache: Dict[str, pd.DataFrame] = {}

    def _voice_events_for_staff(staff_n: str) -> pd.DataFrame:
        key = str(staff_n or "").strip()
        if key in voice_event_cache:
            return voice_event_cache[key]
        subset = pd.DataFrame()
        if "Voice" in df_pitch.columns:
            part_label = ""
            if staff_to_part_label is not None:
                part_label = str(staff_to_part_label.get(key, "")).strip()
            if part_label:
                voice_series = df_pitch["Voice"].astype(str)
                voice_mask = (voice_series == part_label) | voice_series.str.startswith(part_label + " - ")
                subset = df_pitch.loc[voice_mask].copy()
        if subset.empty:
            subset = df_pitch.copy()
        sort_columns = [col for col in ("Global Onset", "Duration", "MIDI") if col in subset.columns]
        if sort_columns:
            subset = subset.sort_values(sort_columns).reset_index(drop=True)
        else:
            subset = subset.reset_index(drop=True)
        if "xml_id" in subset.columns:
            ids = subset["xml_id"].astype(str).str.strip()
            has_ids = ids.replace("", np.nan).notna().any()
            if has_ids:
                subset = subset.assign(_xml_norm=ids.str.lstrip("#"))
                subset = subset[subset["_xml_norm"] != ""]
                subset = subset.drop_duplicates("_xml_norm", keep="first")
                subset = subset.drop(columns=["_xml_norm"])
            else:
                subset = subset.drop_duplicates(["Global Onset", "Duration"], keep="first")
        else:
            subset = subset.drop_duplicates(["Global Onset", "Duration"], keep="first")
        subset = subset.reset_index(drop=True)
        voice_event_cache[key] = subset
        return subset

    for event in barline_events:
        enriched = dict(event)
        assigned = False
        for key, use_end in (
            ("prev_timed_xml_id", True),
            ("next_timed_xml_id", False),
            ("prev_note_xml_id", True),
            ("next_note_xml_id", False),
        ):
            raw = event.get(key)
            if raw is None:
                continue
            note_id = str(raw).strip().lstrip("#")
            if not note_id:
                continue
            if use_end and note_id in end_map:
                enriched["global_onset"] = float(end_map[note_id])
                assigned = True
                break
            if (not use_end) and note_id in onset_map:
                enriched["global_onset"] = float(onset_map[note_id])
                assigned = True
                break
        if not assigned:
            prev_ord = 0
            for ordinal_key in ("prev_timed_ordinal_staff", "prev_note_ordinal_staff"):
                try:
                    prev_ord = int(event.get(ordinal_key, 0))
                except Exception:
                    prev_ord = 0
                if prev_ord > 0:
                    break
            staff_key = str(event.get("staff_n", "") or "").strip()
            if prev_ord > 0 and staff_key:
                voice_events = _voice_events_for_staff(staff_key)
                idx = prev_ord - 1
                if 0 <= idx < len(voice_events):
                    try:
                        onset = float(voice_events.iloc[idx]["Global Onset"])
                        dur = float(voice_events.iloc[idx]["Duration"])
                        if np.isfinite(onset) and np.isfinite(dur):
                            enriched["global_onset"] = onset + dur
                            assigned = True
                    except Exception:
                        pass
        if not assigned:
            # keep unresolved; grid-based fallback may set this later
            pass
        out.append(enriched)
    return out


def _barline_events_to_dataframe(
    barline_events: Sequence[Dict[str, Any]],
    *,
    measure_offsets: Sequence[float],
) -> pd.DataFrame:
    """
    Convert extracted barline events to a uniform event DataFrame schema.
    """
    if not barline_events:
        return _empty_event_dataframe()
    rows: List[Dict[str, Any]] = []
    for event in barline_events:
        enriched_event = dict(event)
        global_onset = event.get("global_onset", np.nan)
        inferred_measure, inferred_local_onset = _infer_measure_position_from_global_onset(
            global_onset,
            measure_offsets,
        )
        if inferred_measure is not None and pd.isna(enriched_event.get("measure")):
            enriched_event["measure"] = inferred_measure
        rows.append(
            _event_row(
                event=enriched_event,
                event_type="barline",
                global_onset=global_onset,
                duration=0.0,
                local_onset=inferred_local_onset,
            )
        )

    df_events = pd.DataFrame(rows)
    for col in _EVENT_DF_COLUMNS:
        if col not in df_events.columns:
            df_events[col] = pd.NA
    df_events = df_events[_EVENT_DF_COLUMNS]
    if len(df_events) and "Global Onset" in df_events.columns:
        df_events = df_events.sort_values("Global Onset").reset_index(drop=True)
    return df_events


def _other_mei_events_to_dataframe(
    events: Sequence[Dict[str, Any]],
    df_pitch: pd.DataFrame,
    *,
    measure_offsets: Sequence[float],
) -> pd.DataFrame:
    """
    Convert extracted non-barline MEI events to the uniform event DataFrame schema.
    """
    if not events:
        return _empty_event_dataframe()

    onset_map, end_map = _note_timing_maps(df_pitch)
    rows: List[Dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("event", "") or "").strip().lower()
        if not event_type or event_type == "barline":
            continue

        global_onset = np.nan
        start_xml_id = _normalize_xml_ref(event.get("start_xml_id"))
        end_xml_id = _normalize_xml_ref(event.get("end_xml_id"))

        if event_type == "measure":
            measure_start = _measure_start_from_offsets(event.get("measure_index"), measure_offsets)
            if measure_start is not None and np.isfinite(measure_start):
                global_onset = float(measure_start)
        elif start_xml_id and start_xml_id in onset_map:
            global_onset = float(onset_map[start_xml_id])
        else:
            resolved = _resolve_measure_tstamp(
                event.get("measure_index"),
                event.get("tstamp_raw"),
                measure_offsets,
            )
            if resolved is not None:
                global_onset = float(resolved)

        global_end: Optional[float] = None
        if end_xml_id and end_xml_id in end_map:
            global_end = float(end_map[end_xml_id])
        elif end_xml_id and end_xml_id in onset_map:
            global_end = float(onset_map[end_xml_id])
        else:
            resolved_end = _resolve_measure_tstamp2(
                event.get("measure_index"),
                event.get("tstamp2_raw"),
                measure_offsets,
            )
            if resolved_end is not None:
                global_end = float(resolved_end)

        duration = 0.0
        if event_type == "measure" and np.isfinite(global_onset):
            measure_index = event.get("measure_index")
            try:
                next_measure_index = int(measure_index) + 1
            except Exception:
                next_measure_index = None
            if next_measure_index is not None:
                next_measure_start = _measure_start_from_offsets(
                    next_measure_index,
                    measure_offsets,
                )
                if next_measure_start is not None and np.isfinite(next_measure_start):
                    duration = max(0.0, float(next_measure_start - global_onset))
        elif np.isfinite(global_onset) and global_end is not None and np.isfinite(global_end):
            duration = max(0.0, float(global_end - global_onset))

        local_onset = np.nan
        if event_type == "measure" and np.isfinite(global_onset):
            local_onset = 0.0
        elif np.isfinite(global_onset):
            measure_start = _measure_start_from_offsets(event.get("measure_index"), measure_offsets)
            if measure_start is not None and np.isfinite(measure_start):
                local_onset = float(global_onset - measure_start)

        rows.append(
            _event_row(
                event=event,
                event_type=event_type,
                global_onset=global_onset,
                duration=duration,
                local_onset=local_onset,
                text_role=event.get("text_role", pd.NA),
            )
        )

    if not rows:
        return _empty_event_dataframe()

    df_events = pd.DataFrame(rows)
    for col in _EVENT_DF_COLUMNS:
        if col not in df_events.columns:
            df_events[col] = pd.NA
    df_events = df_events[_EVENT_DF_COLUMNS]
    if len(df_events):
        df_events = df_events.sort_values("Global Onset", na_position="last").reset_index(drop=True)
    return df_events


def _staff_index_to_part_label_map(score: Any) -> Dict[str, str]:
    """
    Infer MEI staff index -> part label mapping from partitura score part order.
    """
    mapping: Dict[str, str] = {}
    parts = getattr(score, "parts", None) or []
    for idx, part in enumerate(parts, start=1):
        label = (
            getattr(part, "part_name", None)
            or getattr(part, "name", None)
            or getattr(part, "id", None)
            or ""
        )
        label_s = str(label).strip()
        if label_s:
            mapping[str(idx)] = label_s
    return mapping


def _align_event_voices_to_pitch_df(
    df_events: pd.DataFrame,
    df_pitch: pd.DataFrame,
    *,
    staff_to_part_label: Mapping[str, str],
) -> pd.DataFrame:
    """
    Align event Voice labels to the same naming space used by df_pitch Voice labels.
    """
    if df_events.empty or "Voice" not in df_events.columns:
        return df_events
    if "staff_n" not in df_events.columns:
        return df_events
    if "Voice" not in df_pitch.columns:
        return df_events

    out = df_events.copy()
    pitch_voice_values = [
        str(v).strip()
        for v in pd.unique(df_pitch["Voice"].dropna())
        if str(v).strip()
    ]
    if not pitch_voice_values:
        return out

    # Build a preferred voice token per part label, favoring "... - Voice 1" when present.
    part_to_voice: Dict[str, str] = {}
    for voice in pitch_voice_values:
        part_prefix = voice.split(" - Voice", 1)[0].strip()
        if not part_prefix:
            continue
        prev = part_to_voice.get(part_prefix)
        if prev is None:
            part_to_voice[part_prefix] = voice
        elif " - Voice 1" in voice and " - Voice 1" not in prev:
            part_to_voice[part_prefix] = voice

    resolved: List[Any] = []
    for _, row in out.iterrows():
        raw_staff = row.get("staff_n")
        staff_key = str(raw_staff).strip() if raw_staff is not None else ""
        part_label = staff_to_part_label.get(staff_key, "")

        replacement = None
        if part_label:
            replacement = part_to_voice.get(part_label)
            if replacement is None:
                for voice in pitch_voice_values:
                    if voice.startswith(part_label + " - "):
                        replacement = voice
                        break
            if replacement is None:
                replacement = part_label
        if replacement is None:
            replacement = row.get("Voice", pd.NA)
        resolved.append(replacement)

    out["Voice"] = resolved
    return out


def _log_measure_grid_diagnostics(
    log: Callable[[str], None],
    measure_offsets: Sequence[float],
    *,
    default_meter_count: int,
    default_meter_unit: int,
    meter_injections: int,
    used_verovio: bool,
) -> None:
    """
    Emit diagnostics to explain effective measure spacing after parsing.
    """
    if len(measure_offsets) < 2:
        return

    offsets = np.asarray(sorted(float(x) for x in measure_offsets), dtype=float)
    deltas = np.diff(offsets)
    deltas = deltas[np.isfinite(deltas) & (deltas > 0)]
    if deltas.size == 0:
        return

    median_span = float(np.median(deltas))
    prefix = "Post-Verovio" if used_verovio else "Parsed"
    msg = (
        f"{prefix} measure spacing: median={median_span:.3f} quarter units "
        f"(sample count={int(deltas.size)})."
    )
    ratio = (
        median_span / float(default_meter_count)
        if default_meter_count > 0 and np.isfinite(median_span)
        else np.nan
    )
    if np.isfinite(ratio):
        if abs(ratio - 1.5) <= 0.2:
            msg += " Likely ternary mensural expansion (~3:2 against the injected meter grid)."
        elif abs(ratio - 1.0) <= 0.15:
            msg += " Close to the injected/default meter grid."
        else:
            msg += " Indicates non-trivial mensural/grid scaling."
    log(msg)

    if meter_injections > 0 and np.isfinite(ratio) and abs(ratio - 1.0) > 0.15:
        log(
            "Warning: injected meter "
            f"{default_meter_count}/{default_meter_unit} differs from effective parsed span "
            f"({median_span:.3f} quarter units)."
        )


def parse_files_partitura(
    file_sources: Iterable[str],
    *,
    filter_zero_duration: bool = True,
    adjust_fractional_duration: bool = True,
    parse_enharmonic: bool = False,
    backend: str = "plt",
    show_measure_lines: bool = True,
    measure_line_color: str = "red",
    plot_parsed_barlines_with_voice_coloring: bool = False,
    show_hover: bool = True,
    hover_fields: Optional[List[str]] = None,
    display_preview_df_pitch: bool = True,
    display_preview_df_events: bool = True,
    preview_rows: int = 20,
    cleanup_remote: bool = True,
    return_plots: bool = False,
    plot_width: Optional[int] = None,
    plot_height: Optional[int] = None,
    zoom_drag_dim: Optional[str] = None,
    zoom_wheel_dim: Optional[str] = None,
    show_progress: bool = True,
    progress_desc: Optional[str] = None,
    collapse_tied_pitch_events: Optional[bool] = None,
    align_accident_schema: bool = False,
    colorize_voices: bool = False,
    palette: Optional[Union[str, Sequence[str]]] = None,
    include_xml_ids: bool = True,
    include_note_attachments: bool = True,
    normalize_mensural_durations: bool = True,
    inject_missing_meter_signature: bool = True,
    default_meter_count: int = DEFAULT_METER_COUNT,
    default_meter_unit: int = DEFAULT_METER_UNIT,
    try_verovio_mei_conversion: bool = True,
    prefer_verovio_for_mensural: bool = True,
    verovio_mensural_to_cmn: bool = True,
    verovio_duration_equivalence: Optional[float] = None,
    verovio_mensural_score_up: bool = False,
    use_verovio_mensural_timing: bool = False,
    allow_music21_fallback: bool = True,
    dedupe_weaker_text_events: bool = True,
    quiet_native_warnings: bool = False,
    use_remote_cache: bool = True,
    remote_cache_dir: Optional[str] = None,
    n_jobs: int = 1,
    **deprecated_kwargs: Any,
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
    - `use_verovio_mensural_timing=True` keeps mensural note timing on the
      original source-MEI Verovio timeline instead of the converted partitura one.
    - `plot_parsed_barlines_with_voice_coloring=True` overlays parsed barline events
      (when available) in the piano roll using voice-based colors.
    - `dedupe_weaker_text_events=True` drops duplicate text-like MEI events when a
      stronger anchored copy and an unanchored copy are both present in the source.
      Set it to False to preserve the raw extracted event set.
    - `collapse_tied_pitch_events=True` collapses tied continuations in `df_pitch`
      into the tie-start row. Set it to False to preserve source note segments.
    - `quiet_native_warnings=True` suppresses noisy dependency stdout/stderr chatter
      and partitura-emitted `UserWarning`s during loading/conversion while
      preserving CAMAT logs.
    - `use_remote_cache=True` stores downloaded URL sources in a persistent cache
      (``~/.cache/camat/downloads`` by default) so re-runs skip the download step.
      When a source was served from the cache, `cleanup_remote` is ignored for
      that file to preserve the cached copy.
    - `remote_cache_dir` overrides the cache location (also honored via the
      ``CAMAT_DOWNLOAD_CACHE_DIR`` environment variable).
    - `n_jobs` controls parallel parsing of multiple files. ``1`` keeps the current
      serial behavior; ``>1`` or ``-1`` spawns a ``ThreadPoolExecutor`` (-1 picks a
      sensible default based on CPU count). Display/plot work is always executed
      serially in input order to keep notebook output stable.
    """
    collapse_tied_pitch_events = resolve_collapse_tied_pitch_events(
        collapse_tied_pitch_events,
        deprecated_kwargs,
    )
    reject_unexpected_kwargs(deprecated_kwargs, "parse_files_partitura")

    if use_verovio_mensural_timing:
        from .mensural_backend import parse_files_mensural

        return parse_files_mensural(
            file_sources,
            filter_zero_duration=filter_zero_duration,
            adjust_fractional_duration=adjust_fractional_duration,
            parse_enharmonic=parse_enharmonic,
            backend=backend,
            show_measure_lines=show_measure_lines,
            measure_line_color=measure_line_color,
            plot_parsed_barlines_with_voice_coloring=plot_parsed_barlines_with_voice_coloring,
            show_hover=show_hover,
            hover_fields=hover_fields,
            display_preview_df_pitch=display_preview_df_pitch,
            display_preview_df_events=display_preview_df_events,
            preview_rows=preview_rows,
            cleanup_remote=cleanup_remote,
            return_plots=return_plots,
            plot_width=plot_width,
            plot_height=plot_height,
            zoom_drag_dim=zoom_drag_dim,
            zoom_wheel_dim=zoom_wheel_dim,
            show_progress=show_progress,
            progress_desc=progress_desc,
            collapse_tied_pitch_events=collapse_tied_pitch_events,
            align_accident_schema=align_accident_schema,
            colorize_voices=colorize_voices,
            palette=palette,
            include_xml_ids=include_xml_ids,
            normalize_mensural_durations=normalize_mensural_durations,
            inject_missing_meter_signature=inject_missing_meter_signature,
            default_meter_count=default_meter_count,
            default_meter_unit=default_meter_unit,
            try_verovio_mei_conversion=try_verovio_mei_conversion,
            prefer_verovio_for_mensural=prefer_verovio_for_mensural,
            verovio_mensural_to_cmn=verovio_mensural_to_cmn,
            verovio_duration_equivalence=verovio_duration_equivalence,
            verovio_mensural_score_up=verovio_mensural_score_up,
            use_verovio_mensural_timing=True,
            allow_music21_fallback=allow_music21_fallback,
            dedupe_weaker_text_events=dedupe_weaker_text_events,
            quiet_native_warnings=quiet_native_warnings,
            use_remote_cache=use_remote_cache,
            remote_cache_dir=remote_cache_dir,
            n_jobs=n_jobs,
        )

    import threading as _threading
    from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor, as_completed as _as_completed

    results_by_index: Dict[int, Dict[str, Any]] = {}
    dfs_by_name: Dict[str, pd.DataFrame] = {}

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
    raw_log = _tqdm.write if use_progress else print

    # Resolve parallelism request. n_jobs == 1 keeps the serial code path to
    # preserve deterministic display ordering in notebooks. Values != 1 enable
    # a thread pool; plotting + ipy_display are serialized with a lock so the
    # notebook output never interleaves mid-call.
    if n_jobs is None:
        effective_n_jobs = 1
    elif n_jobs < 0:
        try:
            cpu = os.cpu_count() or 1
        except Exception:
            cpu = 1
        effective_n_jobs = max(1, cpu)
    else:
        effective_n_jobs = max(1, int(n_jobs))
    if len(sources) <= 1:
        effective_n_jobs = 1

    _display_lock = _threading.Lock()
    _state_lock = _threading.Lock()

    def log(msg: str) -> None:
        with _display_lock:
            raw_log(msg)

    def _process_one(idx: int, file_source: str) -> None:
        # The extra `if True:` keeps the body's historical indentation stable
        # so the per-file logic below (originally nested inside the serial for
        # loop) can live here without a mass-reindent.
        if True:
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

                file_path = get_file_path(
                    file_source,
                    use_cache=bool(use_remote_cache),
                    cache_dir=remote_cache_dir,
                )
                conversion_cleanup_fns: List[Callable[[], None]] = []
                conversion_source_path = file_path
                is_mei_source = Path(file_path).suffix.lower() == ".mei"
                is_mensural_source = _file_looks_mensural_mei(file_path)
                source_mei_events = _extract_mei_events(file_path) if is_mei_source else []
                used_verovio_conversion = False
                if (
                    is_mei_source
                    and not is_mensural_source
                    and (normalize_mensural_durations or inject_missing_meter_signature)
                ):
                    log(
                        "Detected common-notation MEI. "
                        "Skipping mensural duration/meter preprocessing."
                    )
                if is_mensural_source:
                    log(
                        "Warning: mensural MEI detected. "
                        "Use parse_files_mensural(...) or "
                        "parse_files(..., parsing_backend='mensural') "
                        "for render-aligned mensural parsing."
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
                            quiet_native_warnings=quiet_native_warnings,
                        )
                        used_verovio_conversion = True
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
                    force_mensural_processing=is_mensural_source,
                )
                want_xml_ids = bool(include_xml_ids)
                extracted_mei_events: List[Dict[str, Any]] = []
                converted_barline_count = 0
                staff_to_part: Dict[str, str] = {}
                measure_offsets: List[float] = []
                score_source_path = sanitized_path
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
                        warning_ctx = _suppress_partitura_user_warnings(quiet_native_warnings)
                        output_ctx = _suppress_partitura_dependency_output(quiet_native_warnings)
                        with warning_ctx, output_ctx:
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
                                quiet_native_warnings=quiet_native_warnings,
                            )
                            used_verovio_conversion = True
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
                            warning_ctx = _suppress_partitura_user_warnings(quiet_native_warnings)
                            output_ctx = _suppress_partitura_dependency_output(quiet_native_warnings)
                            with warning_ctx, output_ctx:
                                score = _load_partitura_score(converted_path)
                            score_source_path = converted_path
                        else:
                            raise
                    if str(score_source_path).lower().endswith(".mei"):
                        extracted_mei_events = _extract_mei_events(score_source_path)
                        converted_barline_count = sum(
                            1
                            for evt in extracted_mei_events
                            if str(evt.get("event", "")).strip().lower() == "barline"
                        )
                finally:
                    if cleanup_fn:
                        cleanup_fn()
                    for _fn in conversion_cleanup_fns:
                        _fn()

                is_mei = str(sanitized_path).lower().endswith(".mei")
                include_ids_this_score = want_xml_ids and is_mei
                warning_ctx = _suppress_partitura_user_warnings(quiet_native_warnings)
                output_ctx = _suppress_partitura_dependency_output(quiet_native_warnings)
                with warning_ctx, output_ctx:
                    df_raw = partitura_score_to_dataframe(
                        score,
                        parse_enharmonic=parse_enharmonic,
                        include_xml_ids=include_ids_this_score,
                        include_note_attachments=include_note_attachments
                        and include_ids_this_score,
                        collapse_tied_pitch_events=collapse_tied_pitch_events,
                    )
                # For MEI sources, derive note attachments from the XML directly
                # because partitura's importer does not hydrate slur/fermata/
                # articulation/ornament onto its Note objects. This overwrites
                # the (weaker) partitura-derived columns added above.
                if (
                    include_note_attachments
                    and include_ids_this_score
                    and isinstance(df_raw, pd.DataFrame)
                    and not df_raw.empty
                ):
                    mei_attachments = {}
                    attachment_paths: List[str] = []
                    for candidate_path in (score_source_path, sanitized_path, file_path):
                        candidate_text = str(candidate_path)
                        if not candidate_text.lower().endswith(".mei"):
                            continue
                        if candidate_text in attachment_paths:
                            continue
                        attachment_paths.append(candidate_text)
                    for attachment_path in attachment_paths:
                        try:
                            mei_attachments = _extract_mei_note_attachments(attachment_path)
                        except Exception:
                            mei_attachments = {}
                        if mei_attachments:
                            break
                    if mei_attachments is not None:
                        df_raw = _apply_note_attachments_to_pitch_df(df_raw, mei_attachments)
                warning_ctx = _suppress_partitura_user_warnings(quiet_native_warnings)
                output_ctx = _suppress_partitura_dependency_output(quiet_native_warnings)
                with warning_ctx, output_ctx:
                    measure_offsets = _partitura_measure_offsets(score)
                staff_to_part = _staff_index_to_part_label_map(score)
                if is_mei and isinstance(df_raw, pd.DataFrame) and not df_raw.empty:
                    try:
                        import xml.etree.ElementTree as ET

                        source_root = ET.parse(file_path).getroot()
                        source_staff_to_part = _source_staff_index_to_part_label_map_from_mei(
                            source_root
                        )
                    except Exception:
                        source_staff_to_part = {}
                    if source_staff_to_part:
                        df_raw = _remap_pitch_part_labels(
                            df_raw,
                            staff_to_part,
                            source_staff_to_part,
                        )
                        staff_to_part = source_staff_to_part
                if (
                    is_mei_source
                    and not is_mensural_source
                    and not used_verovio_conversion
                    and include_ids_this_score
                    and isinstance(df_raw, pd.DataFrame)
                    and not df_raw.empty
                ):
                    source_timing, source_measure_offsets = _extract_mei_symbolic_note_timing(file_path)
                    if source_timing:
                        df_raw = _apply_mei_source_voice_labels_to_pitch_df(
                            df_raw,
                            source_timing,
                            staff_to_part=staff_to_part,
                        )
                        idless_note_count = sum(
                            1
                            for info in source_timing.values()
                            if bool(info.get("_source_idless"))
                        )
                        source_tie_next = _extract_mei_tie_next_map(file_path)
                        anchor_shift = 0.0
                        if source_measure_offsets and measure_offsets:
                            anchor_shift = float(measure_offsets[0]) - float(
                                source_measure_offsets[0]
                            )
                            if not np.isfinite(anchor_shift):
                                anchor_shift = 0.0
                        duration_mismatches, onset_mismatches = (
                            _count_mei_symbolic_timing_mismatches(
                                df_raw,
                                source_timing,
                                collapse_tied_pitch_events=collapse_tied_pitch_events,
                                tie_next=source_tie_next,
                                onset_shift=anchor_shift,
                            )
                        )
                        if duration_mismatches > 0 or onset_mismatches > 0 or idless_note_count > 0:
                            # Source-symbolic timing is constructed from zero,
                            # whereas Partitura right-aligns an initial pickup
                            # before zero. Preserve that authoritative anchor
                            # when correcting durations/onsets; otherwise the
                            # correction itself silently changes pickup
                            # semantics for only those scores that happen to
                            # contain a duration mismatch.
                            if source_measure_offsets and measure_offsets:
                                if abs(anchor_shift) > 1e-9:
                                    source_timing = {
                                        note_id: {
                                            **values,
                                            "Global Onset": float(values["Global Onset"])
                                            + anchor_shift,
                                        }
                                        for note_id, values in source_timing.items()
                                    }
                                    source_measure_offsets = [
                                        float(offset) + anchor_shift
                                        for offset in source_measure_offsets
                                    ]
                            df_raw = _apply_mei_symbolic_timing_to_pitch_df(
                                df_raw,
                                source_timing,
                                collapse_tied_pitch_events=collapse_tied_pitch_events,
                                tie_next=source_tie_next,
                            )
                            df_raw = _apply_mei_idless_symbolic_timing_to_pitch_df(
                                df_raw,
                                source_timing,
                                staff_to_part=staff_to_part,
                            )
                            if source_measure_offsets:
                                measure_offsets = source_measure_offsets
                            log(
                                "Corrected Partitura MEI timing from source symbolic durations: "
                                f"{duration_mismatches} duration mismatch(es), "
                                f"{onset_mismatches} onset mismatch(es), "
                                f"{idless_note_count} idless note(s)."
                            )
                if is_mensural_source:
                    _log_measure_grid_diagnostics(
                        log,
                        measure_offsets,
                        default_meter_count=default_meter_count,
                        default_meter_unit=default_meter_unit,
                        meter_injections=meter_injections,
                        used_verovio=used_verovio_conversion,
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
                # df_raw is already sorted by (Global Onset, MIDI) in partitura_score_to_dataframe.
                # filter_and_adjust_durations preserves row order, so no resort is needed here.
                df_processed = filter_and_adjust_durations(
                    df_raw,
                    filter_zero_duration=filter_zero_duration,
                    adjust_fractional_duration=adjust_fractional_duration,
                ).reset_index(drop=True)
                df_processed = reanchor_to_measure_offsets(
                    df_processed,
                    measure_offsets,
                )

                include_ids_this_score = (want_xml_ids and "xml_id" in df_processed.columns)
                if want_xml_ids and not include_ids_this_score and "xml_id" not in df_processed.columns:
                    df_processed["xml_id"] = pd.NA
                if source_mei_events:
                    merged_events: List[Dict[str, Any]] = []
                    seen_event_keys: set[Tuple[str, ...]] = set()
                    for raw_event in list(extracted_mei_events) + list(source_mei_events):
                        event = dict(raw_event)
                        key = _mei_event_merge_key(event)
                        if key in seen_event_keys:
                            continue
                        seen_event_keys.add(key)
                        merged_events.append(event)
                    extracted_mei_events = merged_events
                if dedupe_weaker_text_events:
                    extracted_mei_events, weak_dupe_count = _dedupe_mei_events_prefer_anchored(
                        extracted_mei_events
                    )
                    if weak_dupe_count > 0:
                        log(
                            "Dropped weaker duplicate MEI text events: "
                            f"{weak_dupe_count} row(s) without usable anchors."
                        )

                df_pitch = df_processed
                source_barline_events = [
                    dict(evt) for evt in source_mei_events
                    if str(evt.get("event", "")).strip().lower() == "barline"
                ]
                if used_verovio_conversion and converted_barline_count == 0 and source_barline_events:
                    shared_anchor_ids, total_anchor_ids = _count_event_anchor_xml_id_overlap(
                        source_barline_events,
                        df_pitch,
                    )
                    if total_anchor_ids > 0 and shared_anchor_ids == 0:
                        log(
                            "Warning: source MEI barlines have no xml:id anchor overlap with the "
                            "Verovio-converted pitch timeline. Barlines will be placed via "
                            "staff-order fallback and will not match vrv_render_page() on the "
                            "original mensural MEI."
                        )
                barline_events = [
                    dict(evt) for evt in extracted_mei_events
                    if str(evt.get("event", "")).strip().lower() == "barline"
                ]
                other_events = [
                    dict(evt) for evt in extracted_mei_events
                    if str(evt.get("event", "")).strip().lower() != "barline"
                ]
                barline_events = _attach_barline_event_onsets_from_pitch_df(
                    barline_events,
                    df_pitch,
                    staff_to_part_label=staff_to_part,
                )
                barline_events = _attach_barline_event_offsets(barline_events, measure_offsets)
                if barline_events:
                    forms = sorted({str(evt.get("form", "single")) for evt in barline_events})
                    log(
                        "Extracted MEI barline events: "
                        f"{len(barline_events)} event(s), forms={forms}."
                    )
                if other_events:
                    types = sorted({str(evt.get("event", "")).strip().lower() for evt in other_events})
                    log(
                        "Extracted non-barline MEI events: "
                        f"{len(other_events)} event(s), types={types}."
                    )
                df_rests = _partitura_rest_events_to_dataframe(
                    score,
                    include_xml_ids=include_ids_this_score,
                )
                if not df_rests.empty:
                    log(f"Extracted rest timing events: {len(df_rests)} event(s).")
                df_barlines = _barline_events_to_dataframe(
                    barline_events,
                    measure_offsets=measure_offsets,
                )
                df_other_events = _other_mei_events_to_dataframe(
                    other_events,
                    df_pitch,
                    measure_offsets=measure_offsets,
                )
                event_frames = [frame for frame in (df_barlines, df_rests, df_other_events) if not frame.empty]
                if not event_frames:
                    df_events = _empty_event_dataframe()
                elif len(event_frames) == 1:
                    df_events = event_frames[0].copy()
                else:
                    df_events = pd.concat(
                        event_frames,
                        ignore_index=True,
                        sort=False,
                    )
                if df_events.empty:
                    df_events = _empty_event_dataframe()
                else:
                    for col in _EVENT_DF_COLUMNS:
                        if col not in df_events.columns:
                            df_events[col] = pd.NA
                    df_events = df_events[_EVENT_DF_COLUMNS]
                    df_events = df_events.sort_values(
                        "Global Onset",
                        na_position="last",
                    ).reset_index(drop=True)
                df_events = _align_event_voices_to_pitch_df(
                    df_events,
                    df_pitch,
                    staff_to_part_label=staff_to_part,
                )
                pitch_name = f"{name}_pitch"
                events_name = f"{name}_events"

                plot_obj = None
                if return_plots or backend != "none":
                    # Plot libraries are not thread-safe; serialize the call so
                    # concurrent workers cannot interleave matplotlib/Bokeh state.
                    with _display_lock:
                        plot_obj = draw_piano_roll(
                            df_processed,
                            measure_offsets=measure_offsets,
                            backend=backend,
                            barline_events=df_events,
                            plot_parsed_barlines_with_voice_coloring=plot_parsed_barlines_with_voice_coloring,
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

                if display_preview_df_pitch and ipy_display is not None:
                    with _display_lock:
                        ipy_display(df_processed.head(preview_rows))
                    log(
                        f"Rows: {len(df_processed)}, unique pitches: {df_processed['MIDI'].nunique()}"
                    )
                if display_preview_df_events and ipy_display is not None:
                    with _display_lock:
                        ipy_display(df_events.head(preview_rows))
                    log(f"Event rows: {len(df_events)}")

                result_entry: Dict[str, Any] = {
                    "name": name,
                    "source": file_source,
                    "df": df_pitch,
                    "df_pitch": df_pitch,
                    "df_events": df_events,
                    "df_name_pitch": pitch_name,
                    "df_name_events": events_name,
                    "measure_offsets": measure_offsets,
                    "barline_events": barline_events,
                }
                if return_plots:
                    result_entry["plot"] = plot_obj
                with _state_lock:
                    results_by_index[idx] = result_entry
                    dfs_by_name[pitch_name] = df_pitch
                    dfs_by_name[events_name] = df_events

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
                            plot_parsed_barlines_with_voice_coloring=False,
                            show_hover=show_hover,
                            hover_fields=hover_fields,
                            display_preview_df_pitch=False,
                            display_preview_df_events=False,
                            preview_rows=preview_rows,
                            cleanup_remote=cleanup_remote,
                            return_plots=return_plots,
                            plot_width=plot_width,
                            plot_height=plot_height,
                            zoom_drag_dim=zoom_drag_dim,
                            zoom_wheel_dim=zoom_wheel_dim,
                            show_progress=False,
                            progress_desc=None,
                            collapse_tied_pitch_events=collapse_tied_pitch_events,
                            align_accident_schema=align_accident_schema,
                            colorize_voices=colorize_voices,
                            palette=palette,
                            include_xml_ids=include_xml_ids,
                        )
                        if fallback_results:
                            fb_entry = fallback_results[0]
                            fb_df = fb_entry.get("df_pitch", fb_entry.get("df"))
                            fb_events = fb_entry.get("df_events")
                            if isinstance(fb_df, pd.DataFrame):
                                fb_entry["name"] = name
                                fb_entry["source"] = file_source
                                fb_entry["df_pitch"] = fb_df
                                if not isinstance(fb_events, pd.DataFrame):
                                    fb_events = _empty_event_dataframe()
                                fb_entry["df_events"] = fb_events
                                fb_entry["df_name_pitch"] = f"{name}_pitch"
                                fb_entry["df_name_events"] = f"{name}_events"
                                fb_entry["barline_events"] = fb_entry.get("barline_events", [])
                                with _state_lock:
                                    results_by_index[idx] = fb_entry
                                    dfs_by_name[f"{name}_pitch"] = fb_df
                                    dfs_by_name[f"{name}_events"] = fb_events
                                if display_preview_df_pitch and ipy_display is not None:
                                    with _display_lock:
                                        ipy_display(fb_df.head(preview_rows))
                                    log(
                                        f"Rows: {len(fb_df)}, unique pitches: {fb_df['MIDI'].nunique()}"
                                    )
                                if display_preview_df_events and ipy_display is not None:
                                    with _display_lock:
                                        ipy_display(fb_events.head(preview_rows))
                                    log(f"Event rows: {len(fb_events)}")
                                return
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
                    and not is_cached_download(file_path, remote_cache_dir)
                ):
                    try:
                        os.remove(file_path)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        pass
                if pbar is not None:
                    with _display_lock:
                        pbar.update(1)

    try:
        if effective_n_jobs == 1:
            for idx, file_source in enumerate(sources):
                _process_one(idx, file_source)
        else:
            with _ThreadPoolExecutor(max_workers=effective_n_jobs) as pool:
                futures = [
                    pool.submit(_process_one, i, src)
                    for i, src in enumerate(sources)
                ]
                for fut in _as_completed(futures):
                    try:
                        fut.result()
                    except Exception as exc:  # pragma: no cover - defensive
                        raw_log(f"Parallel worker raised: {exc}")
    finally:
        if pbar is not None:
            pbar.close()

    results = [results_by_index[idx] for idx in sorted(results_by_index)]
    last_df = results[-1]["df"] if results else None
    return results, dfs_by_name, last_df
