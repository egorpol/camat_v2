"""Probe Verovio conversion from common source formats to MEI.

Run from the repository root, preferably in the Python 3.11 environment:

    conda run -n py311 python scripts/test_verovio_conversion.py

If your shell exposes a py311 launcher, this should also work:

    py311 scripts/test_verovio_conversion.py

The script downloads the configured test sources, converts non-MEI inputs to
MEI in a subprocess, passes existing MEI through unchanged, writes generated
MEI files under converted_mei/, and emits a compact JSON report plus a terminal
summary. Formats supported by Verovio are converted directly. MuseScore-native
files use MuseScore -> MusicXML -> Verovio; any other format that music21 can
read uses music21 -> MusicXML -> Verovio. Verovio therefore always performs the
final MEI conversion. The subprocess boundary is intentional: Verovio is native
code, and this keeps a single failing score from taking down the whole test run.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("MPLCONFIGDIR", "/tmp/camat-matplotlib")
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

from camat.parser_utils import expand_file_sources  # noqa: E402
from camat.verovio_render import vrv_guess_input_from  # noqa: E402


DEFAULT_SOURCES: List[str] = [
    "https://analyse.hfm-weimar.de/database/02/PrJode_Jos0302_COM_1-5_MissaDapac_002_00006.xml",
    "https://raw.githubusercontent.com/humdrum-tools/bach-wtc-fugues/refs/heads/master/kern/wtc1f04.krn",
    "https://raw.githubusercontent.com/humdrum-tools/bach-wtc/refs/heads/main/kern/wtc1f22.krn",
    "https://raw.githubusercontent.com/piasteuck/winterreise-analysis/refs/heads/main/Schubert_Winterreise_Dataset_v2-0/01_RawData/score_musicxml/Schubert_D911-20.xml",
]

XML_ID_ATTR = "{http://www.w3.org/XML/1998/namespace}id"
MUSESCORE_REQUIRED_MESSAGE = (
    "MSCZ input requires MuseScore Studio/CLI. Please install MuseScore or convert "
    "the file to MusicXML/MXL/MEI before using CAMAT."
)
MUSESCORE_EXTENSIONS = {".mscz", ".mscx", ".musescore", ".mscore", ".ms"}
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
import pathlib
import sys

import verovio

source_path = pathlib.Path(sys.argv[1])
input_from = sys.argv[2]
output_path = pathlib.Path(sys.argv[3])
render_first_page = sys.argv[4] == "1"

tk = verovio.toolkit()
options = {
    "removeIds": False,
    "xmlIdSeed": 0,
    "breaks": "auto",
}
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
output_path.write_text(mei, encoding="utf-8")

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
    return output_dir / f"{_safe_stem(source)}_{input_from}_verovio{suffix}{timestamp}.mei"


def _fetch_source(source: str, source_dir: Path, timeout: int) -> Path:
    if not source.startswith(("http://", "https://")):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Local file does not exist: {source}")
        return path

    import requests

    source_dir.mkdir(parents=True, exist_ok=True)
    target = source_dir / f"{_safe_stem(source)}_{_sha12(source)}{_source_suffix(source)}"
    if target.exists() and target.stat().st_size > 0:
        return target

    response = requests.get(source, timeout=timeout)
    response.raise_for_status()
    target.write_bytes(response.content)
    return target


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


def _music21_to_musicxml_path(source_path: Path, output_dir: Path) -> Path:
    try:
        from music21 import converter  # type: ignore
    except Exception as exc:
        raise ImportError(
            "This source format requires music21. Install it or convert the source "
            "to MusicXML before running Verovio."
        ) from exc

    intermediate_dir = output_dir / "_intermediate_musicxml"
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    target = intermediate_dir / f"{_safe_stem(str(source_path))}_{_sha12(str(source_path.resolve()))}.musicxml"

    # Run music21 in the parent process so import/export errors are reported
    # directly. Verovio still performs the final MEI conversion below.
    score = converter.parse(str(source_path))
    if hasattr(score, "makeNotation"):
        score.makeNotation(inPlace=True)
    written = score.write("musicxml", fp=str(target))
    musicxml_path = Path(written) if written else target
    if not musicxml_path.exists() or musicxml_path.stat().st_size == 0:
        raise RuntimeError(f"music21 did not produce a MusicXML file for source: {source_path}")
    return musicxml_path


def _musescore_to_musicxml_path(source_path: Path, output_dir: Path, timeout: int) -> Path:
    musescore_bin = _find_musescore_executable()
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
        raise RuntimeError(
            f"{MUSESCORE_REQUIRED_MESSAGE} MuseScore command failed "
            f"(returncode={child_info.get('returncode', proc.returncode)}, command={' '.join(failed_cmd)}"
            f"{', stderr=' + detail if detail else ''})"
        )
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError(
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
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "source": source,
        "status": "fail",
        "input_from": None,
        "local_source": None,
        "output_mei": None,
        "converted": False,
        "overwritten": False,
        "message": None,
        "error": None,
        "intermediate_musicxml": None,
        "conversion_route": None,
    }
    try:
        source_path = _fetch_source(source, output_dir / "_sources", timeout)
        source_text = None if _is_binary_score_source(source_path) else source_path.read_text(encoding="utf-8", errors="ignore")
        input_from = _guess_source_format(source_path, source_text)
        if input_from is None:
            input_from = "music21"

        if input_from == "mei" and _source_extension(source_path) == ".mei":
            stats = _mei_stats(source_path)
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
                    **stats,
                }
            )
            return record

        child_source_path = source_path
        child_input_from = input_from
        musicxml_intermediate: Optional[Path] = None
        if input_from == "musescore":
            musicxml_intermediate = _musescore_to_musicxml_path(source_path, output_dir, timeout)
            child_source_path = musicxml_intermediate
            child_input_from = "musicxml"
            conversion_route = "musescore-musicxml-verovio"
        elif input_from not in NATIVE_VEROVIO_INPUTS:
            musicxml_intermediate = _music21_to_musicxml_path(source_path, output_dir)
            child_source_path = musicxml_intermediate
            child_input_from = "musicxml"
            conversion_route = "music21-musicxml-verovio"
        else:
            conversion_route = "verovio-direct"

        mei_path = _output_mei_path(
            source,
            output_dir=output_dir,
            input_from=input_from,
            output_suffix=output_suffix,
            timestamp_label=timestamp_label,
        )
        overwritten = mei_path.exists()
        proc = subprocess.run(
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
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "Verovio subprocess failed "
                f"(returncode={proc.returncode}, stderr={proc.stderr.strip() or proc.stdout.strip()})"
            )
        child_info = json.loads((proc.stdout or "{}").strip().splitlines()[-1])
        stats = _mei_stats(mei_path)
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
                **child_info,
                **stats,
            }
        )
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
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
) -> List[Dict[str, Any]]:
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


def _print_summary(records: Iterable[Dict[str, Any]]) -> None:
    rows = list(records)

    def fmt(value: Any) -> str:
        return "" if value is None else str(value)

    print("\n=== Verovio Conversion Capability Probe ===\n")
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
            print(f"        error: {row['error']}")
    print()

    print("Output paths:")
    for row in rows:
        path = row.get("output_mei") or row.get("local_source") or ""
        source = _shorten(str(row.get("source") or ""), max_len=90)
        if row.get("status") != "ok":
            print(f"  FAIL: {source}")
            continue
        if row.get("converted"):
            action = "OVERWROTE" if row.get("overwritten") else "created"
            print(f"  {action}: {path}")
        else:
            print(f"  not converted, already MEI: {path}")
        print(f"    source: {source}")
    print()


def main(argv: Optional[List[str]] = None) -> int:
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
    args = parser.parse_args(argv)

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
    )

    report_path = output_dir / "conversion_report.json"
    report_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    _print_summary(records)
    print(f"Report: {report_path}")

    return 0 if all(row.get("status") == "ok" for row in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
