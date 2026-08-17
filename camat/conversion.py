"""Convert common symbolic-music sources to MEI.

Use :func:`convert_sources` from Python or the ``camat-convert`` command-line
entry point. Formats supported by Verovio are converted directly.
MuseScore-native files use MuseScore -> MusicXML -> Verovio; any other format
that music21 can read uses music21 -> MusicXML -> Verovio. Verovio therefore
always performs the final MEI conversion.

MIDI import uses a configurable score-oriented quantization grid whose default
includes 32nd notes. Before MIDI is exported to MusicXML, staggered overlaps
are separated into music21 voices with visible gap rests so their timing
survives as MEI layers. Performance-oriented MIDI timing is exposed separately
by :func:`camat.midi_timing.read_midi_timing`. Verovio runs in a subprocess so
one malformed score cannot terminate a batch.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

from .parser_utils import expand_file_sources
from .verovio_render import vrv_guess_input_from


DEFAULT_SOURCES: List[str] = [
    "https://analyse.hfm-weimar.de/database/02/PrJode_Jos0302_COM_1-5_MissaDapac_002_00006.xml",
    "https://raw.githubusercontent.com/humdrum-tools/bach-wtc-fugues/refs/heads/master/kern/wtc1f04.krn",
    "https://raw.githubusercontent.com/humdrum-tools/bach-wtc/refs/heads/main/kern/wtc1f22.krn",
    "https://raw.githubusercontent.com/piasteuck/winterreise-analysis/refs/heads/main/Schubert_Winterreise_Dataset_v2-0/01_RawData/score_musicxml/Schubert_D911-20.xml",
]

XML_ID_ATTR = "{http://www.w3.org/XML/1998/namespace}id"
CONVERSION_REPORT_SCHEMA_VERSION = 1
MUSESCORE_REQUIRED_MESSAGE = (
    "MSCZ input requires MuseScore Studio/CLI. Please install MuseScore or convert "
    "the file to MusicXML/MXL/MEI before using CAMAT."
)
MUSESCORE_EXTENSIONS = {".mscz", ".mscx", ".musescore", ".mscore", ".ms"}
# music21 defaults to (4, 3), which cannot represent straight 32nd notes and
# can collapse two adjacent ornaments into a single 16th-note chord.
MIDI_QUARTER_LENGTH_DIVISORS = (8, 6, 4, 3)
DEFAULT_VEROVIO_OPTIONS: Dict[str, Any] = {
    "removeIds": False,
    "xmlIdSeed": 0,
    "breaks": "auto",
}
VALIDATION_STAGES = (
    "downloaded",
    "converted",
    "valid_mei",
    "rendered",
    "camat_parsed",
    "editorially_inspected",
)
NATIVE_VEROVIO_INPUTS = {
    "abc",
    "cmme.xml",
    "darms",
    "esac",
    "humdrum",
    "mei",
    "musicxml",
    "musicxml-zip",
    "pae",
    "volpiano",
}
_MUSESCORE_LOCK = threading.Lock()
_VERSION_LOCK = threading.Lock()
_TOOL_VERSION_CACHE: Dict[str, str] = {}


@dataclass(frozen=True)
class MidiImportOptions:
    """Control music21's score-oriented MIDI import and notation recovery.

    ``quarter_length_divisors`` are subdivisions of one quarter note: ``8``
    represents straight 32nd notes, ``16`` represents 64th notes, and ``11``
    permits multiples of one eleventh of a quarter. They are candidates used
    independently for each offset and duration, not a global meter inference.

    ``voice_layout="layers"`` retains reconstructed voices as layers on their
    source MIDI-track staff. ``"separate_staves"`` expands each local voice
    slot to its own staff for diagnostics; MIDI does not supply persistent
    notated-voice identities, so slot continuity across measures is inferred.
    """

    quantize: bool = True
    quarter_length_divisors: Tuple[int, ...] = MIDI_QUARTER_LENGTH_DIVISORS
    reconstruct_voices: bool = True
    fill_gaps: bool = True
    voice_layout: str = "layers"

    def __post_init__(self) -> None:
        divisors: List[int] = []
        for raw_divisor in self.quarter_length_divisors:
            if isinstance(raw_divisor, bool) or not isinstance(raw_divisor, int):
                raise TypeError("MIDI quantization divisors must be positive integers.")
            if raw_divisor <= 0:
                raise ValueError("MIDI quantization divisors must be positive integers.")
            if raw_divisor not in divisors:
                divisors.append(raw_divisor)
        if self.quantize and not divisors:
            raise ValueError("At least one MIDI divisor is required when quantization is enabled.")
        if self.voice_layout not in {"layers", "separate_staves"}:
            raise ValueError(
                "voice_layout must be 'layers' or 'separate_staves'."
            )
        object.__setattr__(self, "quarter_length_divisors", tuple(divisors))

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe, deterministic representation."""
        return {
            "quantize": self.quantize,
            "quarter_length_divisors": list(self.quarter_length_divisors),
            "reconstruct_voices": self.reconstruct_voices,
            "fill_gaps": self.fill_gaps,
            "voice_layout": self.voice_layout,
        }


@dataclass(frozen=True)
class DownloadOptions:
    """Control safe HTTP downloads used by conversion batches."""

    max_bytes: int = 100 * 1024 * 1024
    chunk_size: int = 64 * 1024
    allowed_content_types: Tuple[str, ...] = ()
    reject_html: bool = True

    def __post_init__(self) -> None:
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be greater than zero.")
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero.")
        normalized = tuple(
            dict.fromkeys(
                str(value).strip().lower()
                for value in self.allowed_content_types
                if str(value).strip()
            )
        )
        object.__setattr__(self, "allowed_content_types", normalized)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe, deterministic representation."""
        data = asdict(self)
        data["allowed_content_types"] = list(self.allowed_content_types)
        return data


class ConversionStageError(RuntimeError):
    """Conversion failure carrying a stable stage and machine-readable code."""

    def __init__(self, stage: str, code: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code

MUSESCORE_EXPORT_CHILD = r"""
import json
import pathlib
import subprocess
import sys

musescore_bin = sys.argv[1]
source_path = pathlib.Path(sys.argv[2])
target_path = pathlib.Path(sys.argv[3])
target_path.parent.mkdir(parents=True, exist_ok=True)

cmd = [
    musescore_bin,
    "-o",
    str(target_path),
    str(source_path),
    "-f",
]
proc = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    check=False,
)
ok = proc.returncode == 0 and target_path.exists() and target_path.stat().st_size > 0
print(json.dumps({
    "ok": ok,
    "returncode": proc.returncode,
    "stdout": proc.stdout,
    "stderr": proc.stderr,
    "command": cmd,
    "output": str(target_path),
}))
raise SystemExit(0 if ok else 1)
"""

CONVERT_CHILD = r"""
import base64
import json
import os
import pathlib
import sys

import verovio

source_path = pathlib.Path(sys.argv[1])
input_from = sys.argv[2]
output_path = pathlib.Path(sys.argv[3])
render_first_page = sys.argv[4] == "1"
options = json.loads(sys.argv[5])

tk = verovio.toolkit()
if input_from != "musicxml-zip":
    options["inputFrom"] = input_from
tk.setOptions(options)

if input_from == "musicxml-zip":
    data_bytes = source_path.read_bytes()
    if hasattr(tk, "loadZipDataBase64"):
        load_result = tk.loadZipDataBase64(base64.b64encode(data_bytes).decode("ascii"))
    elif hasattr(tk, "loadZipDataBuffer"):
        load_result = tk.loadZipDataBuffer(data_bytes, len(data_bytes))
    else:
        raise RuntimeError("This Verovio build does not expose a compressed MusicXML loader")
else:
    data = source_path.read_text(encoding="utf-8", errors="ignore")
    load_result = tk.loadData(data)
page_count = int(tk.getPageCount())
mei = tk.getMEI()
if isinstance(mei, bytes):
    mei = mei.decode("utf-8", errors="ignore")
mei = str(mei or "")
if not mei.strip():
    raise RuntimeError("Verovio returned empty MEI")
output_path.parent.mkdir(parents=True, exist_ok=True)
temporary_path = output_path.with_name(
    f".{output_path.name}.{os.getpid()}.tmp"
)
try:
    temporary_path.write_text(mei, encoding="utf-8")
    temporary_path.replace(output_path)
finally:
    temporary_path.unlink(missing_ok=True)

svg_ok = None
if render_first_page and page_count > 0:
    svg = tk.renderToSVG(1)
    if isinstance(svg, bytes):
        svg = svg.decode("utf-8", errors="ignore")
    svg_ok = "<svg" in str(svg)

print(json.dumps({
    "load_result": load_result,
    "page_count": page_count,
    "output_chars": len(mei),
    "svg_ok": svg_ok,
    "verovio_version": tk.getVersion() if hasattr(tk, "getVersion") else "",
}))
"""


def _sha12(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text beside its target and atomically replace the final path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    temporary.replace(path)


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True))


def _normalized_verovio_options(
    options: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    merged = dict(DEFAULT_VEROVIO_OPTIONS)
    if options:
        if "inputFrom" in options:
            raise ValueError("Verovio inputFrom is selected from the source route and cannot be overridden.")
        merged.update(dict(options))
    try:
        return json.loads(json.dumps(merged, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise TypeError("verovio_options must contain JSON-serializable values.") from exc


def _conversion_options_payload(
    *,
    midi_options: MidiImportOptions,
    download_options: DownloadOptions,
    verovio_options: Mapping[str, Any],
    render_first_page: bool,
) -> Dict[str, Any]:
    return {
        "midi": midi_options.to_dict(),
        "download": download_options.to_dict(),
        "verovio": dict(verovio_options),
        "render_first_page": bool(render_first_page),
    }


def _conversion_signature(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _new_validation_stages(*, is_remote: bool, render_requested: bool) -> Dict[str, Dict[str, Any]]:
    return {
        "downloaded": {
            "status": "pending" if is_remote else "not_applicable",
            "details": None if is_remote else "Local source; no download required.",
        },
        "converted": {"status": "pending", "details": None},
        "valid_mei": {"status": "pending", "details": None},
        "rendered": {
            "status": "pending" if render_requested else "not_requested",
            "details": None,
        },
        "camat_parsed": {"status": "not_run", "details": None},
        "editorially_inspected": {"status": "not_run", "details": None},
    }


def set_validation_stage(
    record: Dict[str, Any],
    stage: str,
    status: str,
    details: Optional[str] = None,
) -> None:
    """Update one explicit validation stage in a conversion record."""
    if stage not in VALIDATION_STAGES:
        raise ValueError(f"Unknown validation stage: {stage!r}")
    stages = record.setdefault("validation_stages", {})
    stages[stage] = {"status": str(status), "details": details}


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _cached_tool_version(key: str, probe: Any) -> str:
    with _VERSION_LOCK:
        cached = _TOOL_VERSION_CACHE.get(key)
        if cached is not None:
            return cached
        try:
            value = str(probe() or "").strip()
        except Exception:
            value = "unknown"
        _TOOL_VERSION_CACHE[key] = value or "unknown"
        return _TOOL_VERSION_CACHE[key]


def _music21_version() -> str:
    def probe() -> str:
        import music21  # type: ignore

        return str(music21.__version__)

    return _cached_tool_version("music21", probe)


def _verovio_version() -> str:
    def probe() -> str:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import verovio; print(verovio.toolkit().getVersion())",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout)
        return proc.stdout.strip().splitlines()[-1]

    return _cached_tool_version("verovio", probe)


def _musescore_version(executable: str) -> str:
    def probe() -> str:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        output = (proc.stdout or proc.stderr or "").strip()
        if proc.returncode != 0 and not output:
            raise RuntimeError(f"MuseScore version probe returned {proc.returncode}")
        return output.splitlines()[0] if output else "unknown"

    return _cached_tool_version(f"musescore:{executable}", probe)


def _file_fingerprint(path: Path) -> Dict[str, Any]:
    """Return stable provenance fields for a local source or generated file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def _safe_stem(source: str) -> str:
    parsed = urlparse(source)
    name = Path(parsed.path).name if parsed.scheme else Path(source).name
    stem = Path(name).stem or "score"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return stem or f"score_{_sha12(source)}"


def _safe_suffix(value: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._-")
    if not suffix:
        return ""
    return suffix if suffix.startswith("_") else f"_{suffix}"


def _source_suffix(source: str) -> str:
    parsed = urlparse(source)
    suffix = Path(parsed.path).suffix if parsed.scheme else Path(source).suffix
    return suffix or ".score"


def _source_extension(path: Path) -> str:
    return path.suffix.lower()


def _is_binary_score_source(path: Path) -> bool:
    return _source_extension(path) in {".mxl", ".mid", ".midi", ".mscz"}


def _guess_source_format(path: Path, source_text: Optional[str]) -> Optional[str]:
    ext = _source_extension(path)
    if ext in MUSESCORE_EXTENSIONS:
        return "musescore"
    if ext == ".mxl":
        return "musicxml-zip"
    if ext in {".mid", ".midi"}:
        return "midi"
    # Unknown formats are deliberately left unknown here. _convert_one routes
    # them through music21 rather than guessing a Verovio inputFrom value.
    return vrv_guess_input_from(str(path), source_text)


def _find_musescore_executable() -> str:
    configured = os.environ.get("MUSESCORE_BIN")
    candidates = [
        configured,
        "musescore4",
        "mscore4",
        "musescore",
        "mscore",
        "MuseScore-Studio",
        "MuseScore",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        candidate_path = Path(candidate).expanduser()
        if candidate_path.exists() and os.access(candidate_path, os.X_OK):
            return str(candidate_path)
    raise RuntimeError(MUSESCORE_REQUIRED_MESSAGE)


def _resolve_n_jobs(n_jobs: int, item_count: int) -> int:
    if item_count <= 1:
        return 1
    if n_jobs < 0:
        return max(1, os.cpu_count() or 1)
    return max(1, int(n_jobs))


def _timestamp_label(enabled: bool) -> str:
    if not enabled:
        return ""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _output_mei_path(
    source: str,
    *,
    output_dir: Path,
    input_from: str,
    output_suffix: str = "",
    timestamp_label: str = "",
) -> Path:
    suffix = _safe_suffix(output_suffix)
    timestamp = _safe_suffix(timestamp_label)
    source_key = _sha12(source)
    return output_dir / (
        f"{_safe_stem(source)}_{source_key}_{input_from}_verovio{suffix}{timestamp}.mei"
    )


def _content_type_allowed(content_type: str, allowed: Sequence[str]) -> bool:
    if not allowed:
        return True
    for candidate in allowed:
        if candidate.endswith("/*") and content_type.startswith(candidate[:-1]):
            return True
        if content_type == candidate:
            return True
    return False


def _validate_download_content_type(
    content_type: str,
    options: DownloadOptions,
) -> None:
    if options.reject_html and content_type in {"text/html", "application/xhtml+xml"}:
        raise ConversionStageError(
            "download",
            "html_instead_of_score",
            f"Remote source returned {content_type or 'HTML'} instead of a score file.",
        )
    if content_type and not _content_type_allowed(content_type, options.allowed_content_types):
        raise ConversionStageError(
            "download",
            "content_type_rejected",
            f"Content type {content_type!r} is not in the configured allow-list.",
        )


def _fetch_source(
    source: str,
    source_dir: Path,
    timeout: int,
    *,
    options: Optional[DownloadOptions] = None,
    force_download: bool = False,
) -> Tuple[Path, Dict[str, Any]]:
    options = options or DownloadOptions()
    if not source.startswith(("http://", "https://")):
        path = Path(source)
        if not path.exists():
            raise ConversionStageError(
                "download",
                "local_source_missing",
                f"Local file does not exist: {source}",
            )
        guessed_type, _ = mimetypes.guess_type(str(path))
        return path, {
            "requested_url": None,
            "resolved_url": None,
            "redirect_history": [],
            "http_status": None,
            "content_type": guessed_type,
            "content_length_header": None,
            "downloaded_bytes": path.stat().st_size,
            "download_cache_hit": False,
        }

    import requests

    source_dir.mkdir(parents=True, exist_ok=True)
    target = source_dir / f"{_safe_stem(source)}_{_sha12(source)}{_source_suffix(source)}"
    metadata_path = target.with_name(f"{target.name}.download.json")
    if not force_download and target.exists() and target.stat().st_size > 0:
        if target.stat().st_size > options.max_bytes:
            raise ConversionStageError(
                "download",
                "cached_source_too_large",
                f"Cached source exceeds max_bytes={options.max_bytes}: {target}",
            )
        metadata = _read_json(metadata_path) or {
            "requested_url": source,
            "resolved_url": source,
            "redirect_history": [],
            "http_status": None,
            "content_type": mimetypes.guess_type(urlparse(source).path)[0],
            "content_length_header": None,
            "downloaded_bytes": target.stat().st_size,
        }
        _validate_download_content_type(
            str(metadata.get("content_type") or "").lower(),
            options,
        )
        metadata["download_cache_hit"] = True
        return target, metadata

    temporary: Optional[Path] = None
    try:
        with requests.get(source, timeout=timeout, stream=True, allow_redirects=True) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            content_length_text = response.headers.get("Content-Length")
            content_length = int(content_length_text) if content_length_text and content_length_text.isdigit() else None
            if content_length is not None and content_length > options.max_bytes:
                raise ConversionStageError(
                    "download",
                    "content_length_exceeded",
                    f"Remote source declares {content_length} bytes; limit is {options.max_bytes}.",
                )
            _validate_download_content_type(content_type, options)

            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=source_dir,
                prefix=f".{target.name}.",
                suffix=".part",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                downloaded_bytes = 0
                for chunk in response.iter_content(chunk_size=options.chunk_size):
                    if not chunk:
                        continue
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > options.max_bytes:
                        raise ConversionStageError(
                            "download",
                            "download_size_exceeded",
                            f"Remote source exceeded max_bytes={options.max_bytes} while streaming.",
                        )
                    handle.write(chunk)

            if downloaded_bytes == 0:
                raise ConversionStageError(
                    "download",
                    "empty_download",
                    f"Remote source returned no bytes: {source}",
                )
            temporary.replace(target)
            temporary = None
            metadata = {
                "requested_url": source,
                "resolved_url": str(response.url),
                "redirect_history": [str(item.url) for item in response.history],
                "http_status": response.status_code,
                "content_type": content_type or None,
                "content_length_header": content_length,
                "downloaded_bytes": downloaded_bytes,
                "download_cache_hit": False,
            }
            _atomic_write_json(metadata_path, metadata)
            return target, metadata
    except ConversionStageError:
        raise
    except requests.RequestException as exc:
        raise ConversionStageError("download", "http_error", str(exc)) from exc
    except OSError as exc:
        raise ConversionStageError("download", "download_io_error", str(exc)) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _mei_stats(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    root = ET.fromstring(text)
    ids: List[str] = []
    counts: Dict[str, int] = {}
    for element in root.iter():
        name = _local_name(str(element.tag))
        counts[name] = counts.get(name, 0) + 1
        xml_id = element.attrib.get(XML_ID_ATTR)
        if xml_id:
            ids.append(xml_id)

    duplicate_ids = len(ids) - len(set(ids))
    return {
        "xml_id_count": len(ids),
        "duplicate_xml_id_count": duplicate_ids,
        "note_count": counts.get("note", 0),
        "rest_count": counts.get("rest", 0) + counts.get("mRest", 0) + counts.get("multiRest", 0),
        "measure_count": counts.get("measure", 0),
        "mei_version": root.attrib.get("meiversion", ""),
    }


def _measure_has_staggered_note_overlaps(measure: Any) -> bool:
    """Return whether a later note starts before an earlier note has ended."""
    events = []
    for element in measure.recurse().notes:
        start = float(element.getOffsetInHierarchy(measure))
        events.append((start, start + float(element.quarterLength)))
    events.sort()

    for index, left in enumerate(events):
        for right in events[index + 1:]:
            if right[0] >= left[1] - 1e-9:
                break
            if right[0] > left[0] + 1e-9:
                return True
    return False


def _prepare_midi_score_for_export(
    score: Any,
    *,
    reconstruct_voices: bool = True,
    fill_gaps: bool = True,
) -> Dict[str, int]:
    """Reconstruct notated voices and visible gap rests before MIDI export."""
    from music21 import stream as m21_stream  # type: ignore

    measures = [
        measure
        for part in score.parts
        for measure in part.getElementsByClass(m21_stream.Measure)
    ]
    overlap_measures = [
        measure for measure in measures if _measure_has_staggered_note_overlaps(measure)
    ]
    voice_measures_before = sum(bool(measure.voices) for measure in measures)
    visible_rests_before = sum(
        bool(element.isRest) and not bool(element.style.hideObjectOnPrint)
        for element in score.recurse().notesAndRests
    )

    if reconstruct_voices:
        for measure in overlap_measures:
            measure.makeVoices(inPlace=True, fillGaps=fill_gaps)
    score.makeNotation(inPlace=True)

    return {
        "staggered_overlap_measures": len(overlap_measures),
        "voice_measures_before": voice_measures_before,
        "voice_measures_after": sum(bool(measure.voices) for measure in measures),
        "visible_rests_added": sum(
            bool(element.isRest) and not bool(element.style.hideObjectOnPrint)
            for element in score.recurse().notesAndRests
        )
        - visible_rests_before,
    }


def _midi_voices_to_separate_staves(score: Any) -> Tuple[Any, Dict[str, Any]]:
    """Expand each source part's local voice slots into separate parts/staves.

    MIDI stores tracks, channels, and note events rather than persistent
    notated-voice identities. music21's ``voicesToParts`` therefore aligns
    voices by their ordinal position inside each measure. The result is useful
    for diagnostics and voice-isolated analysis, but a slot is not guaranteed
    to represent the same contrapuntal voice throughout the piece.
    """
    from music21 import stream as m21_stream  # type: ignore

    source_parts = list(score.parts)
    voice_slots_per_source_part = []
    for part in source_parts:
        measures = part.getElementsByClass(m21_stream.Measure)
        voice_slots_per_source_part.append(
            max(1, max((len(measure.voices) for measure in measures), default=0))
        )

    separated = score.voicesToParts(separateById=False)
    if getattr(score, "metadata", None) is not None:
        separated.metadata = copy.deepcopy(score.metadata)

    output_index = 0
    for source_index, (source_part, slot_count) in enumerate(
        zip(source_parts, voice_slots_per_source_part),
        start=1,
    ):
        source_name = source_part.partName or f"MIDI track {source_index}"
        for voice_index in range(1, slot_count + 1):
            output_part = separated.parts[output_index]
            output_part.id = f"midi-track-{source_index}-voice-{voice_index}"
            output_part.partName = f"{source_name} — voice slot {voice_index}"
            output_part.partAbbreviation = f"T{source_index}V{voice_index}"
            output_index += 1

    return separated, {
        "voice_layout": "separate_staves",
        "source_part_count": len(source_parts),
        "voice_slots_per_source_part": voice_slots_per_source_part,
        "output_staff_count": len(separated.parts),
        "voice_identity_warning": (
            "MIDI has no persistent notated-voice identity; staves follow "
            "music21's local per-measure voice-slot order."
        ),
    }


def _midi_header_timing(source_path: Path) -> Dict[str, Any]:
    from music21.midi import MidiFile  # type: ignore

    midi_file = MidiFile()
    midi_file.open(source_path)
    try:
        midi_file.read()
    finally:
        midi_file.close()
    return {
        "ticks_per_quarter_note": (
            int(midi_file.ticksPerQuarterNote)
            if midi_file.ticksPerSecond is None
            else None
        ),
        "ticks_per_second": (
            int(midi_file.ticksPerSecond)
            if midi_file.ticksPerSecond is not None
            else None
        ),
        "track_count": len(midi_file.tracks),
    }


def _quantization_error_summary(score: Any) -> Dict[str, Any]:
    def summarize(attribute: str) -> Dict[str, Any]:
        values = []
        for element in score.recurse().notesAndRests:
            value = getattr(element.editorial, attribute, None)
            if value is not None:
                values.append(abs(float(value)))
        ordered = sorted(values)
        percentile_95 = (
            ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
            if ordered
            else 0.0
        )
        return {
            "affected_event_count": len(values),
            "max_abs_quarter_length": max(values, default=0.0),
            "mean_abs_quarter_length": (
                sum(values) / len(values) if values else 0.0
            ),
            "p95_abs_quarter_length": percentile_95,
        }

    return {
        "offset": summarize("offsetQuantizationError"),
        "duration": summarize("quarterLengthQuantizationError"),
    }


def _load_music21_score(
    source_path: Path,
    midi_options: Optional[MidiImportOptions] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """Load a source with CAMAT's format-specific music21 import policy."""
    try:
        from music21 import converter  # type: ignore
    except Exception as exc:
        raise ConversionStageError(
            "music21_parse",
            "music21_unavailable",
            "This source format requires music21. Install it or convert the source "
            "to MusicXML before running Verovio."
        ) from exc

    started = time.perf_counter()
    try:
        if _source_extension(source_path) in {".mid", ".midi"}:
            options = midi_options or MidiImportOptions()
            score = converter.parse(
                str(source_path),
                quantizePost=options.quantize,
                quarterLengthDivisors=options.quarter_length_divisors,
            )
            finest_divisor = (
                max(options.quarter_length_divisors)
                if options.quantize
                else 16
            )
            diagnostics = {
                "quantize_post": options.quantize,
                "quantization_quarter_length_divisors": (
                    list(options.quarter_length_divisors)
                    if options.quantize
                    else None
                ),
                "chord_grouping_tolerance_quarter_length": 1 / finest_divisor,
                "reconstruct_voices": options.reconstruct_voices,
                "fill_gaps": options.fill_gaps,
                "voice_layout": options.voice_layout,
                "quantization_errors": (
                    _quantization_error_summary(score)
                    if options.quantize
                    else None
                ),
                **_midi_header_timing(source_path),
                "music21_parse_seconds": round(time.perf_counter() - started, 6),
            }
            if not options.quantize:
                diagnostics["microtiming_warning"] = (
                    "music21 still groups near-simultaneous events before returning "
                    "the score; use camat.read_midi_timing for raw tick analysis."
                )
            return score, diagnostics

        return converter.parse(str(source_path)), {
            "music21_parse_seconds": round(time.perf_counter() - started, 6)
        }
    except ConversionStageError:
        raise
    except Exception as exc:
        raise ConversionStageError("music21_parse", "music21_parse_failed", str(exc)) from exc


def _music21_to_musicxml_path(
    source_path: Path,
    output_dir: Path,
    *,
    midi_options: Optional[MidiImportOptions] = None,
) -> Tuple[Path, Dict[str, Any]]:
    intermediate_dir = output_dir / "_intermediate_musicxml"
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    target = intermediate_dir / f"{_safe_stem(str(source_path))}_{_sha12(str(source_path.resolve()))}.musicxml"

    # Run music21 in the parent process so import/export errors are reported
    # directly. Verovio still performs the final MEI conversion below.
    score, diagnostics = _load_music21_score(source_path, midi_options=midi_options)
    if _source_extension(source_path) in {".mid", ".midi"}:
        options = midi_options or MidiImportOptions()
        started = time.perf_counter()
        diagnostics.update(
            _prepare_midi_score_for_export(
                score,
                reconstruct_voices=options.reconstruct_voices,
                fill_gaps=options.fill_gaps,
            )
        )
        if options.voice_layout == "separate_staves":
            score, voice_layout_diagnostics = _midi_voices_to_separate_staves(score)
            diagnostics.update(voice_layout_diagnostics)
        else:
            diagnostics.update(
                {
                    "voice_layout": "layers",
                    "source_part_count": len(score.parts),
                    "voice_slots_per_source_part": None,
                    "output_staff_count": len(score.parts),
                    "voice_identity_warning": None,
                }
            )
        diagnostics["music21_notation_seconds"] = round(
            time.perf_counter() - started,
            6,
        )
    elif hasattr(score, "makeNotation"):
        score.makeNotation(inPlace=True)
    try:
        started = time.perf_counter()
        written = score.write("musicxml", fp=str(target))
        diagnostics["music21_export_seconds"] = round(
            time.perf_counter() - started,
            6,
        )
    except Exception as exc:
        raise ConversionStageError("music21_export", "musicxml_export_failed", str(exc)) from exc
    musicxml_path = Path(written) if written else target
    if not musicxml_path.exists() or musicxml_path.stat().st_size == 0:
        raise ConversionStageError(
            "music21_export",
            "musicxml_output_missing",
            f"music21 did not produce a MusicXML file for source: {source_path}",
        )
    return musicxml_path, diagnostics


def _musescore_to_musicxml_path(
    source_path: Path,
    output_dir: Path,
    timeout: int,
    *,
    executable: Optional[str] = None,
) -> Path:
    musescore_bin = executable or _find_musescore_executable()
    intermediate_dir = output_dir / "_intermediate_musicxml"
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    target = intermediate_dir / f"{_safe_stem(str(source_path))}_{_sha12(str(source_path.resolve()))}.musicxml"

    cmd = [
        sys.executable,
        "-c",
        MUSESCORE_EXPORT_CHILD,
        musescore_bin,
        str(source_path),
        str(target),
    ]
    with _MUSESCORE_LOCK:
        proc = None
        for _attempt in range(2):
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if proc.returncode == 0:
                break
    assert proc is not None
    if proc.returncode != 0:
        child_info: Dict[str, Any] = {}
        try:
            child_info = json.loads((proc.stdout or "{}").strip().splitlines()[-1])
        except Exception:
            child_info = {}
        if child_info:
            detail = str(child_info.get("stderr") or child_info.get("stdout") or "").strip()
        else:
            detail = (proc.stderr or proc.stdout or "").strip()
        failed_cmd = child_info.get("command") or cmd
        raise ConversionStageError(
            "musescore_export",
            "musescore_export_failed",
            f"{MUSESCORE_REQUIRED_MESSAGE} MuseScore command failed "
            f"(returncode={child_info.get('returncode', proc.returncode)}, command={' '.join(failed_cmd)}"
            f"{', stderr=' + detail if detail else ''})"
        )
    if not target.exists() or target.stat().st_size == 0:
        raise ConversionStageError(
            "musescore_export",
            "musescore_output_missing",
            f"{MUSESCORE_REQUIRED_MESSAGE} MuseScore did not produce MusicXML for source: {source_path}"
        )
    return target


def _shorten(value: str, max_len: int = 74) -> str:
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


def _convert_one(
    source: str,
    *,
    output_dir: Path,
    timeout: int,
    render_first_page: bool,
    output_suffix: str = "",
    timestamp_label: str = "",
    midi_options: Optional[MidiImportOptions] = None,
    download_options: Optional[DownloadOptions] = None,
    verovio_options: Optional[Mapping[str, Any]] = None,
    resume_policy: str = "never",
) -> Dict[str, Any]:
    midi_options = midi_options or MidiImportOptions()
    download_options = download_options or DownloadOptions()
    normalized_verovio_options = _normalized_verovio_options(verovio_options)
    is_remote = source.startswith(("http://", "https://"))
    conversion_options = _conversion_options_payload(
        midi_options=midi_options,
        download_options=download_options,
        verovio_options=normalized_verovio_options,
        render_first_page=render_first_page,
    )
    started_total = time.perf_counter()
    stage_durations: Dict[str, float] = {}
    record: Dict[str, Any] = {
        "report_schema_version": CONVERSION_REPORT_SCHEMA_VERSION,
        "source": source,
        "status": "fail",
        "input_from": None,
        "local_source": None,
        "output_mei": None,
        "converted": False,
        "overwritten": False,
        "skipped": False,
        "resume_policy": resume_policy,
        "resume_reason": None,
        "message": None,
        "error": None,
        "error_type": None,
        "failure_stage": None,
        "failure_code": None,
        "intermediate_musicxml": None,
        "conversion_route": None,
        "source_size_bytes": None,
        "source_sha256": None,
        "output_size_bytes": None,
        "output_sha256": None,
        "music21_diagnostics": None,
        "download": None,
        "resolved_url": None,
        "tool_versions": {
            "music21": None,
            "musescore": None,
            "verovio": None,
        },
        "conversion_options": conversion_options,
        "options_fingerprint": _conversion_signature(conversion_options),
        "conversion_signature": None,
        "stage_durations_seconds": stage_durations,
        "conversion_duration_seconds": None,
        "validation_stages": _new_validation_stages(
            is_remote=is_remote,
            render_requested=render_first_page,
        ),
    }
    current_stage = "download"

    def timed(stage: str, callback: Any) -> Any:
        nonlocal current_stage
        current_stage = stage
        started = time.perf_counter()
        try:
            return callback()
        finally:
            stage_durations[stage] = round(time.perf_counter() - started, 6)

    try:
        source_path, download_metadata = timed(
            "download",
            lambda: _fetch_source(
                source,
                output_dir / "_sources",
                timeout,
                options=download_options,
                force_download=resume_policy == "force",
            ),
        )
        record["download"] = download_metadata
        record["resolved_url"] = download_metadata.get("resolved_url")
        if is_remote:
            set_validation_stage(
                record,
                "downloaded",
                "passed",
                "Used cached download."
                if download_metadata.get("download_cache_hit")
                else "Downloaded with streaming size checks.",
            )

        source_fingerprint = timed("source_fingerprint", lambda: _file_fingerprint(source_path))
        record.update(
            {
                "local_source": str(source_path.resolve()),
                "source_size_bytes": source_fingerprint["size_bytes"],
                "source_sha256": source_fingerprint["sha256"],
            }
        )
        current_stage = "format_detection"
        source_text = (
            None
            if _is_binary_score_source(source_path)
            else source_path.read_text(encoding="utf-8", errors="ignore")
        )
        input_from = timed(
            "format_detection",
            lambda: _guess_source_format(source_path, source_text),
        )
        if input_from is None:
            input_from = "music21"
        record["input_from"] = input_from

        if input_from == "mei" and _source_extension(source_path) == ".mei":
            stats = timed("mei_validation", lambda: _mei_stats(source_path))
            record.update(
                {
                    "status": "ok",
                    "input_from": input_from,
                    "local_source": str(source_path.resolve()),
                    "output_mei": str(source_path.resolve()),
                    "converted": False,
                    "overwritten": False,
                    "svg_ok": None,
                    "message": "MEI source was not converted because it is already MEI.",
                    "conversion_route": "mei-pass-through",
                    "source_size_bytes": source_fingerprint["size_bytes"],
                    "source_sha256": source_fingerprint["sha256"],
                    "output_size_bytes": source_fingerprint["size_bytes"],
                    "output_sha256": source_fingerprint["sha256"],
                    **stats,
                }
            )
            set_validation_stage(
                record,
                "converted",
                "not_applicable",
                "Source is already MEI.",
            )
            set_validation_stage(record, "valid_mei", "passed", "MEI XML parsed successfully.")
            if render_first_page:
                set_validation_stage(
                    record,
                    "rendered",
                    "not_run",
                    "MEI pass-through does not invoke the conversion render smoke test.",
                )
            record["conversion_duration_seconds"] = round(
                time.perf_counter() - started_total,
                6,
            )
            return record

        child_source_path = source_path
        child_input_from = input_from
        musicxml_intermediate: Optional[Path] = None
        music21_diagnostics: Dict[str, Any] = {}
        musescore_bin: Optional[str] = None
        if input_from == "musescore":
            try:
                musescore_bin = _find_musescore_executable()
            except Exception as exc:
                raise ConversionStageError(
                    "musescore_export",
                    "musescore_unavailable",
                    str(exc),
                ) from exc
            record["tool_versions"]["musescore"] = _musescore_version(musescore_bin)
            record["tool_versions"]["verovio"] = _verovio_version()
            conversion_route = "musescore-musicxml-verovio"
        elif input_from not in NATIVE_VEROVIO_INPUTS:
            record["tool_versions"]["music21"] = _music21_version()
            record["tool_versions"]["verovio"] = _verovio_version()
            conversion_route = "music21-musicxml-verovio"
        else:
            record["tool_versions"]["verovio"] = _verovio_version()
            conversion_route = "verovio-direct"

        record["conversion_route"] = conversion_route
        mei_path = _output_mei_path(
            source,
            output_dir=output_dir,
            input_from=input_from,
            output_suffix=output_suffix,
            timestamp_label=timestamp_label,
        )
        sidecar_path = mei_path.with_name(f"{mei_path.name}.camat.json")
        signature_payload = {
            "report_schema_version": CONVERSION_REPORT_SCHEMA_VERSION,
            "source_sha256": source_fingerprint["sha256"],
            "input_from": input_from,
            "conversion_route": conversion_route,
            "conversion_options": conversion_options,
            "tool_versions": record["tool_versions"],
        }
        signature = _conversion_signature(signature_payload)
        record["conversion_signature"] = signature

        if resume_policy == "if-unchanged":
            previous = _read_json(sidecar_path)
            previous_record = previous.get("record") if previous else None
            if (
                isinstance(previous_record, dict)
                and previous.get("conversion_signature") == signature
                and mei_path.exists()
            ):
                output_fingerprint = _file_fingerprint(mei_path)
                if output_fingerprint.get("sha256") == previous_record.get("output_sha256"):
                    preserved = dict(previous_record)
                    preserved.update(
                        {
                            "status": "ok",
                            "converted": False,
                            "overwritten": False,
                            "skipped": True,
                            "resume_policy": resume_policy,
                            "resume_reason": "source, route, options, tool versions, and output hash are unchanged",
                            "message": "Skipped unchanged conversion.",
                            "download": download_metadata,
                            "resolved_url": download_metadata.get("resolved_url"),
                            "stage_durations_seconds": stage_durations,
                            "conversion_duration_seconds": round(
                                time.perf_counter() - started_total,
                                6,
                            ),
                        }
                    )
                    return preserved

        if input_from == "musescore":
            musicxml_intermediate = timed(
                "musescore_export",
                lambda: _musescore_to_musicxml_path(
                    source_path,
                    output_dir,
                    timeout,
                    executable=musescore_bin,
                ),
            )
            child_source_path = musicxml_intermediate
            child_input_from = "musicxml"
        elif input_from not in NATIVE_VEROVIO_INPUTS:
            musicxml_intermediate, music21_diagnostics = timed(
                "music21_bridge",
                lambda: _music21_to_musicxml_path(
                    source_path,
                    output_dir,
                    midi_options=midi_options,
                ),
            )
            child_source_path = musicxml_intermediate
            child_input_from = "musicxml"
        overwritten = mei_path.exists()
        proc = timed(
            "verovio_conversion",
            lambda: subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "faulthandler",
                    "-c",
                    CONVERT_CHILD,
                    str(child_source_path),
                    child_input_from,
                    str(mei_path),
                    "1" if render_first_page else "0",
                    json.dumps(normalized_verovio_options, sort_keys=True),
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            ),
        )
        if proc.returncode != 0:
            raise ConversionStageError(
                "verovio_conversion",
                "verovio_subprocess_failed",
                "Verovio subprocess failed "
                f"(returncode={proc.returncode}, stderr={proc.stderr.strip() or proc.stdout.strip()})"
            )
        try:
            child_info = json.loads((proc.stdout or "{}").strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise ConversionStageError(
                "verovio_conversion",
                "invalid_verovio_report",
                "Verovio subprocess did not return a valid JSON report.",
            ) from exc
        stats = timed("mei_validation", lambda: _mei_stats(mei_path))
        output_fingerprint = timed("output_fingerprint", lambda: _file_fingerprint(mei_path))
        record.update(
            {
                "status": "ok",
                "input_from": input_from,
                "local_source": str(source_path.resolve()),
                "output_mei": str(mei_path.resolve()),
                "converted": True,
                "overwritten": overwritten,
                "message": (
                    "Converted source to MusicXML with music21, then converted to MEI with Verovio."
                    if conversion_route == "music21-musicxml-verovio"
                    else "Converted MuseScore source to MusicXML with MuseScore, then converted with Verovio."
                    if conversion_route == "musescore-musicxml-verovio"
                    else "Converted with Verovio."
                ),
                "intermediate_musicxml": str(musicxml_intermediate.resolve()) if musicxml_intermediate else None,
                "conversion_route": conversion_route,
                "music21_diagnostics": music21_diagnostics or None,
                "source_size_bytes": source_fingerprint["size_bytes"],
                "source_sha256": source_fingerprint["sha256"],
                "output_size_bytes": output_fingerprint["size_bytes"],
                "output_sha256": output_fingerprint["sha256"],
                **child_info,
                **stats,
            }
        )
        set_validation_stage(record, "converted", "passed", conversion_route)
        set_validation_stage(record, "valid_mei", "passed", "MEI XML parsed successfully.")
        if render_first_page:
            set_validation_stage(
                record,
                "rendered",
                "passed" if child_info.get("svg_ok") is True else "failed",
                "First-page SVG smoke test.",
            )
        record["conversion_duration_seconds"] = round(
            time.perf_counter() - started_total,
            6,
        )
        timed(
            "provenance_write",
            lambda: _atomic_write_json(
                sidecar_path,
                {
                    "report_schema_version": CONVERSION_REPORT_SCHEMA_VERSION,
                    "conversion_signature": signature,
                    "signature_payload": signature_payload,
                    "record": record,
                },
            ),
        )
    except Exception as exc:
        if isinstance(exc, ConversionStageError):
            failure_stage = exc.stage
            failure_code = exc.code
        else:
            failure_stage = current_stage
            failure_code = re.sub(r"(?<!^)(?=[A-Z])", "_", type(exc).__name__).lower()
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["error_type"] = type(exc).__name__
        record["failure_stage"] = failure_stage
        record["failure_code"] = failure_code
        if failure_stage == "download":
            set_validation_stage(record, "downloaded", "failed", str(exc))
        else:
            set_validation_stage(record, "converted", "failed", str(exc))
    finally:
        record["conversion_duration_seconds"] = round(
            time.perf_counter() - started_total,
            6,
        )
    return record


def convert_sources(
    sources: Iterable[str],
    *,
    output_dir: Path | str = Path("converted_mei/verovio_conversion_tests"),
    timeout: int = 90,
    render_first_page: bool = True,
    n_jobs: int = 1,
    output_suffix: str = "",
    timestamp: bool = False,
    show_progress: bool = True,
    expand_txt_sources: bool = True,
    source_base_dir: Path | str | None = None,
    midi_options: Optional[MidiImportOptions] = None,
    download_options: Optional[DownloadOptions] = None,
    verovio_options: Optional[Mapping[str, Any]] = None,
    resume_policy: str = "never",
) -> List[Dict[str, Any]]:
    """Convert local paths or URLs to MEI and return one report per source.

    Verovio-native sources are converted directly. MIDI and other
    music21-readable formats pass through MusicXML; MuseScore-native formats
    require the MuseScore CLI. Existing ``.mei`` files pass through unchanged.

    Parameters
    ----------
    sources
        Score paths, raw-file URLs, or newline-separated ``.txt`` manifests.
    output_dir
        Directory for downloaded sources, intermediates, generated MEI, and
        optional CLI reports.
    timeout
        Per-download or converter-subprocess timeout in seconds.
    render_first_page
        Render the first MEI page as a conversion smoke test.
    n_jobs
        Parallel conversion workers; ``-1`` uses the available CPU count.
    output_suffix
        Extra label inserted before each generated ``.mei`` suffix.
    timestamp
        Add one batch timestamp to generated filenames.
    show_progress
        Display tqdm progress when available.
    expand_txt_sources
        Expand ``.txt`` inputs as source manifests.
    source_base_dir
        Base directory for relative source and manifest paths.
    midi_options
        Score-oriented MIDI quantization and voice-reconstruction policy.
    download_options
        Streaming, file-size, and content-type download policy.
    verovio_options
        JSON-serializable Verovio options merged over CAMAT's stable defaults.
        ``inputFrom`` is route-controlled and cannot be supplied here.
    resume_policy
        ``"never"`` converts again using cached downloads, ``"if-unchanged"``
        reuses an output only when its source, route, options, tool versions,
        schema, and output hash match, and ``"force"`` redownloads and converts.

    Returns
    -------
    list of dict
        Ordered conversion records containing the route, output path,
        fingerprints, structural checks, diagnostics, and any error.
    """
    if resume_policy not in {"never", "if-unchanged", "force"}:
        raise ValueError("resume_policy must be 'never', 'if-unchanged', or 'force'.")
    effective_midi_options = midi_options or MidiImportOptions()
    effective_download_options = download_options or DownloadOptions()
    effective_verovio_options = _normalized_verovio_options(verovio_options)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    if expand_txt_sources:
        source_list = expand_file_sources(
            sources,
            base_dir=source_base_dir,
            verbose=show_progress,
        )
    else:
        source_root = (
            Path(source_base_dir).resolve()
            if source_base_dir is not None
            else Path.cwd().resolve()
        )
        source_list = []
        for raw_source in sources:
            source = str(raw_source).strip()
            if not source:
                continue
            if source.startswith(("http://", "https://")):
                source_list.append(source)
                continue
            source_path = Path(source)
            if not source_path.is_absolute():
                source_path = source_root / source_path
            source_list.append(str(source_path.resolve()))
    effective_n_jobs = _resolve_n_jobs(n_jobs, len(source_list))
    stamp = _timestamp_label(timestamp)

    try:
        from tqdm.auto import tqdm
    except Exception:
        tqdm = None

    def run_one(source: str) -> Dict[str, Any]:
        return _convert_one(
            source,
            output_dir=output_path,
            timeout=timeout,
            render_first_page=render_first_page,
            output_suffix=output_suffix,
            timestamp_label=stamp,
            midi_options=effective_midi_options,
            download_options=effective_download_options,
            verovio_options=effective_verovio_options,
            resume_policy=resume_policy,
        )

    if effective_n_jobs == 1:
        iterator = source_list
        if show_progress and tqdm is not None and len(source_list) > 1:
            iterator = tqdm(source_list, desc="Converting with Verovio", unit="file")
        return [run_one(source) for source in iterator]

    records: List[Optional[Dict[str, Any]]] = [None] * len(source_list)
    with ThreadPoolExecutor(max_workers=effective_n_jobs) as executor:
        futures = {
            executor.submit(run_one, source): idx
            for idx, source in enumerate(source_list)
        }
        completed = as_completed(futures)
        if show_progress and tqdm is not None and len(source_list) > 1:
            completed = tqdm(completed, total=len(source_list), desc="Converting with Verovio", unit="file")
        for future in completed:
            idx = futures[future]
            records[idx] = future.result()

    return [record for record in records if record is not None]


def print_conversion_summary(records: Iterable[Dict[str, Any]]) -> None:
    """Print a compact terminal summary of conversion records."""
    rows = list(records)

    def fmt(value: Any) -> str:
        return "" if value is None else str(value)

    print("\n=== CAMAT Conversion Summary ===\n")
    header = (
        f"{'status':<7} {'input':<12} {'pages':>5} {'measures':>8} "
        f"{'notes':>7} {'xml:id':>7} {'dupe':>5}  source"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row.get('status', ''):<7} "
            f"{fmt(row.get('input_from')):<12} "
            f"{fmt(row.get('page_count')):>5} "
            f"{fmt(row.get('measure_count')):>8} "
            f"{fmt(row.get('note_count')):>7} "
            f"{fmt(row.get('xml_id_count')):>7} "
            f"{fmt(row.get('duplicate_xml_id_count')):>5}  "
            f"{_shorten(str(row.get('source') or ''))}"
        )
        if row.get("error"):
            stage = row.get("failure_stage") or "unknown"
            code = row.get("failure_code") or "unknown"
            print(f"        error [{stage}/{code}]: {row['error']}")
    print()

    print("Output paths:")
    for row in rows:
        path = row.get("output_mei") or row.get("local_source") or ""
        source = _shorten(str(row.get("source") or ""), max_len=90)
        if row.get("status") != "ok":
            print(f"  FAIL: {source}")
            continue
        if row.get("skipped"):
            print(f"  skipped unchanged: {path}")
        elif row.get("converted"):
            action = "OVERWROTE" if row.get("overwritten") else "created"
            print(f"  {action}: {path}")
        else:
            print(f"  not converted, already MEI: {path}")
        print(f"    source: {source}")
    print()


def _parse_midi_grid(value: str) -> Tuple[int, ...]:
    try:
        parsed = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "MIDI grid must be comma-separated positive integers, for example 16,8,6,4,3."
        ) from exc
    try:
        return MidiImportOptions(quarter_length_divisors=parsed).quarter_length_divisors
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main(argv: Optional[List[str]] = None) -> int:
    """Run the ``camat-convert`` command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="converted_mei/verovio_conversion_tests",
        help="Directory for downloaded sources, converted MEI files, and report JSON.",
    )
    parser.add_argument("--timeout", type=int, default=90, help="Download and conversion timeout in seconds.")
    parser.add_argument(
        "--source",
        action="append",
        help=(
            "Override default source list. May be passed multiple times. "
            "Local .txt files are expanded as newline-separated source lists."
        ),
    )
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="Skip first-page SVG render smoke test after conversion.",
    )
    parser.add_argument(
        "--n-jobs",
        type=int,
        default=1,
        help="Parallel conversion workers. Use -1 for os.cpu_count().",
    )
    parser.add_argument(
        "--output-suffix",
        default="",
        help="Optional custom suffix inserted before .mei in converted output filenames.",
    )
    parser.add_argument(
        "--timestamp",
        action="store_true",
        help="Append a batch timestamp to converted output filenames.",
    )
    parser.add_argument(
        "--midi-grid",
        type=_parse_midi_grid,
        default=MIDI_QUARTER_LENGTH_DIVISORS,
        help=(
            "Comma-separated quarter-note divisors used for MIDI score quantization "
            "(default: 8,6,4,3; use 16 for straight 64th notes)."
        ),
    )
    parser.add_argument(
        "--no-midi-quantize",
        action="store_true",
        help="Disable music21 post-quantization; not a lossless microtiming mode.",
    )
    parser.add_argument(
        "--no-midi-voice-reconstruction",
        action="store_true",
        help="Do not separate staggered MIDI overlaps into notated voices.",
    )
    parser.add_argument(
        "--no-midi-fill-gaps",
        action="store_true",
        help="When reconstructing MIDI voices, leave gap rests implicit/hidden.",
    )
    parser.add_argument(
        "--midi-voices-to-staves",
        action="store_true",
        help=(
            "Put each inferred local MIDI voice slot on a separate staff. "
            "This is diagnostic: MIDI does not encode persistent voice identities."
        ),
    )
    parser.add_argument(
        "--max-download-mb",
        type=float,
        default=100.0,
        help="Maximum permitted size of one downloaded source (default: 100 MiB).",
    )
    parser.add_argument(
        "--allow-content-type",
        action="append",
        default=[],
        help="Optional HTTP content-type allow-list entry; may be repeated and supports type/*.",
    )
    parser.add_argument(
        "--allow-html",
        action="store_true",
        help="Allow text/html downloads (normally rejected as likely repository/blob pages).",
    )
    parser.add_argument(
        "--verovio-options-json",
        default="{}",
        help="JSON object merged into the stable Verovio conversion options.",
    )
    resume_group = parser.add_mutually_exclusive_group()
    resume_group.add_argument(
        "--resume",
        action="store_true",
        help="Skip outputs whose source, route, options, versions, and output hash are unchanged.",
    )
    resume_group.add_argument(
        "--force",
        action="store_true",
        help="Redownload remote sources and reconvert even when cached artifacts exist.",
    )
    args = parser.parse_args(argv)

    if args.max_download_mb <= 0:
        parser.error("--max-download-mb must be greater than zero")
    try:
        cli_verovio_options = json.loads(args.verovio_options_json)
    except json.JSONDecodeError as exc:
        parser.error(f"--verovio-options-json is invalid JSON: {exc}")
    if not isinstance(cli_verovio_options, dict):
        parser.error("--verovio-options-json must decode to a JSON object")

    midi_options = MidiImportOptions(
        quantize=not args.no_midi_quantize,
        quarter_length_divisors=args.midi_grid,
        reconstruct_voices=not args.no_midi_voice_reconstruction,
        fill_gaps=not args.no_midi_fill_gaps,
        voice_layout="separate_staves" if args.midi_voices_to_staves else "layers",
    )
    download_options = DownloadOptions(
        max_bytes=int(args.max_download_mb * 1024 * 1024),
        allowed_content_types=tuple(args.allow_content_type),
        reject_html=not args.allow_html,
    )
    resume_policy = "force" if args.force else "if-unchanged" if args.resume else "never"

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = args.source or DEFAULT_SOURCES

    records = convert_sources(
        sources,
        output_dir=output_dir,
        timeout=args.timeout,
        render_first_page=not args.no_render,
        n_jobs=args.n_jobs,
        output_suffix=args.output_suffix,
        timestamp=args.timestamp,
        show_progress=True,
        midi_options=midi_options,
        download_options=download_options,
        verovio_options=cli_verovio_options,
        resume_policy=resume_policy,
    )

    report_path = output_dir / "conversion_report.json"
    _atomic_write_json(report_path, records)
    print_conversion_summary(records)
    print(f"Report: {report_path}")

    return 0 if all(row.get("status") == "ok" for row in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
