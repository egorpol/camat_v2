from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional, Tuple

__all__ = ["guarded_load_into_verovio_toolkit", "python_executable"]


def python_executable() -> str:
    """Return a Python interpreter path that is safe to pass to ``subprocess``.

    Some host environments (Cursor's agent, some AppImage wrappers) rewrite
    ``sys.executable`` to a non-Python binary. Prefer that path when it still
    looks like Python; otherwise use the interpreter next to ``sys.prefix``.
    """
    current = Path(sys.executable)
    if _looks_like_python(current):
        return str(current)

    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    prefixes = (
        sys.prefix,
        getattr(sys, "base_prefix", sys.prefix),
        getattr(sys, "exec_prefix", sys.prefix),
    )
    candidates: list[Path] = []
    if os.name == "nt":
        for root in prefixes:
            root_path = Path(root)
            candidates.extend(
                (
                    root_path / "python.exe",
                    root_path / "Scripts" / "python.exe",
                )
            )
    else:
        for root in prefixes:
            bindir = Path(root) / "bin"
            candidates.extend(
                (
                    bindir / f"python{version}",
                    bindir / "python3",
                    bindir / "python",
                )
            )

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = str(candidate.resolve())
        except OSError:
            continue
        if resolved in seen or not candidate.is_file():
            continue
        seen.add(resolved)
        if os.access(candidate, os.X_OK) and _looks_like_python(candidate):
            return resolved
    return sys.executable


def _looks_like_python(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith("python")


_MEI_NS = "http://www.music-encoding.org/ns/mei"
_XML_NS = "http://www.w3.org/XML/1998/namespace"

_PROBE_SCRIPT = textwrap.dedent(
    """
    import pathlib
    import sys
    import verovio

    path = pathlib.Path(sys.argv[1])
    input_from = sys.argv[2]
    data = path.read_text(encoding="utf-8", errors="ignore")
    tk = verovio.toolkit()
    tk.setOptions({"inputFrom": input_from})
    tk.loadData(data)
    print(tk.getPageCount())
    """
)

_TIMING_PROBE_SCRIPT = textwrap.dedent(
    """
    import json
    import pathlib
    import sys
    import verovio

    mei_path = pathlib.Path(sys.argv[1])
    options_path = pathlib.Path(sys.argv[2])
    data = mei_path.read_text(encoding="utf-8", errors="ignore")
    options = json.loads(options_path.read_text(encoding="utf-8"))
    tk = verovio.toolkit()
    load_opts = dict(options)
    load_opts["inputFrom"] = "mei"
    tk.setOptions(load_opts)
    if not tk.loadData(data):
        sys.stderr.write("loadData failed\\n")
        sys.exit(1)
    # Options in force at the timing call decide expandNever (verovio#4533).
    tk.setOptions(options)
    tk.renderToTimemap()
    print("ok")
    """
)

# Only these native faults mean "this score crashes Verovio timing". Other
# signals (SIGTERM, SIGKILL/OOM, ...) must not be blamed on repeats or cached.
# SIGBUS is Unix-only; take whatever the platform defines so Windows imports.
_NATIVE_CRASH_RETURNCODES = frozenset(
    {
        *(
            -int(getattr(signal, name))
            for name in ("SIGSEGV", "SIGABRT", "SIGBUS", "SIGILL", "SIGFPE")
            if hasattr(signal, name)
        ),
        139,  # shell-style SIGSEGV (128 + 11)
        0xC0000005,  # Windows STATUS_ACCESS_VIOLATION (unsigned)
        -1073741819,  # same value as a signed 32-bit DWORD
    }
)

# Toolkits whose timing was prepared under a temporary expandNever=True pass.
# Verovio keeps that preparation after the option is restored, so public timing
# must reload once before trusting expanded (or user) options again.
_SOURCE_ORDER_TIMING_TOOLKIT_IDS: set[int] = set()


def _is_native_crash_returncode(returncode: Optional[int]) -> bool:
    if returncode is None:
        return False
    return int(returncode) in _NATIVE_CRASH_RETURNCODES


def _read_expand_never(toolkit: Any) -> bool:
    payload = toolkit.getOptions()
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = None
    if not isinstance(payload, Mapping):
        return False
    return bool(payload.get("expandNever", False))


def _mark_source_order_timing(toolkit: Any) -> None:
    _SOURCE_ORDER_TIMING_TOOLKIT_IDS.add(id(toolkit))


def _clear_source_order_timing(toolkit: Any) -> None:
    _SOURCE_ORDER_TIMING_TOOLKIT_IDS.discard(id(toolkit))


def _has_source_order_timing(toolkit: Any) -> bool:
    return id(toolkit) in _SOURCE_ORDER_TIMING_TOOLKIT_IDS


@contextmanager
def _temporary_expand_never(toolkit: Any, value: bool = True) -> Iterator[bool]:
    """Set ``expandNever`` for a call, then restore the previous value.

    The partitura backend can make ``verovio.toolkit()`` a process-wide
    singleton, so a leaked True would silently change later public timing.
    When this pass actually changes the option, mark the toolkit so a later
    public timing call can rebuild prepared timing lazily.
    """
    previous = _read_expand_never(toolkit)
    desired = bool(value)
    changed = previous != desired
    toolkit.setOptions({"expandNever": desired})
    try:
        yield previous
    finally:
        toolkit.setOptions({"expandNever": previous})
        if changed:
            _mark_source_order_timing(toolkit)


def _probe_verovio_load(data: str, *, input_from: str) -> Dict[str, Any]:
    suffix = ".mei" if input_from == "mei" else ".xml"
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="ignore") as handle:
            handle.write(data)
        proc = subprocess.run(
            [python_executable(), "-X", "faulthandler", "-c", _PROBE_SCRIPT, path, input_from],
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
        }
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _probe_verovio_timing(mei: str, *, options: Mapping[str, Any]) -> Dict[str, Any]:
    """Run ``renderToTimemap`` on ``mei`` under ``options`` in a child process."""
    mei_fd, mei_path = tempfile.mkstemp(suffix=".mei")
    opt_fd, opt_path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(mei_fd, "w", encoding="utf-8", errors="ignore") as handle:
            handle.write(mei)
        with os.fdopen(opt_fd, "w", encoding="utf-8") as handle:
            json.dump(dict(options), handle)
        try:
            proc = subprocess.run(
                [
                    python_executable(),
                    "-X",
                    "faulthandler",
                    "-c",
                    _TIMING_PROBE_SCRIPT,
                    mei_path,
                    opt_path,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            return {
                "ok": False,
                "crashed": False,
                "returncode": None,
                "stdout": "",
                "stderr": str(exc),
            }
        return {
            "ok": proc.returncode == 0,
            "crashed": _is_native_crash_returncode(proc.returncode),
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
        }
    finally:
        for path in (mei_path, opt_path):
            try:
                os.unlink(path)
            except OSError:
                pass


def _remove_mei_elements_by_local_name(data: str, *, local_name: str) -> Tuple[str, int]:
    ET.register_namespace("", _MEI_NS)
    ET.register_namespace("xml", _XML_NS)
    root = ET.fromstring(data)

    removed = 0

    def _recurse(node: Any) -> None:
        nonlocal removed
        for child in list(node):
            tag = str(getattr(child, "tag", ""))
            child_local_name = tag.rsplit("}", 1)[-1] if "}" in tag else tag
            if child_local_name == local_name:
                node.remove(child)
                removed += 1
                continue
            _recurse(child)

    _recurse(root)
    return ET.tostring(root, encoding="unicode"), removed


def _format_probe_error(result: Mapping[str, Any]) -> str:
    parts = [f"returncode={result.get('returncode')}"]
    stderr = str(result.get("stderr") or "").strip()
    stdout = str(result.get("stdout") or "").strip()
    if stderr:
        parts.append(f"stderr={stderr}")
    elif stdout:
        parts.append(f"stdout={stdout}")
    return ", ".join(parts)


def guarded_load_into_verovio_toolkit(
    toolkit: Any,
    data: str,
    *,
    input_from: str,
    options: Optional[Mapping[str, Any]] = None,
    source_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Load input data into a Verovio toolkit after probing in a subprocess.

    Some MEI files can segfault the Python process inside native Verovio code.
    To keep notebooks alive, probe the load in a subprocess first and apply
    narrow sanitizers for known crashers before touching the in-process toolkit.
    """
    normalized_input = str(input_from or "").strip().lower()
    opts = dict(options or {})
    opts["inputFrom"] = normalized_input
    source_label = os.path.basename(str(source_hint or "")) or "<memory>"

    probe = _probe_verovio_load(data, input_from=normalized_input)
    if probe["ok"]:
        toolkit.setOptions(opts)
        toolkit.loadData(data)
        return {
            "sanitized": False,
            "source": source_label,
        }

    if normalized_input == "mei" and "<custos" in data:
        sanitized_data, removed = _remove_mei_elements_by_local_name(data, local_name="custos")
        if removed > 0:
            sanitized_probe = _probe_verovio_load(sanitized_data, input_from=normalized_input)
            if sanitized_probe["ok"]:
                toolkit.setOptions(opts)
                toolkit.loadData(sanitized_data)
                return {
                    "sanitized": True,
                    "source": source_label,
                    "sanitizer": "strip_custos",
                    "removed_count": removed,
                    "message": (
                        f"Verovio crashed on {source_label} with <custos> present; "
                        f"reloaded after removing {removed} <custos> element(s)."
                    ),
                }

    raise RuntimeError(
        f"Verovio could not safely load {source_label} ({normalized_input}). "
        f"Probe details: {_format_probe_error(probe)}"
    )
