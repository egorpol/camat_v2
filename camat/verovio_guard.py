from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

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
