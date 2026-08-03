from __future__ import annotations

import os
import io
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from importlib import import_module
from typing import Any, Callable, Dict, List, Mapping, Tuple

from .parser_utils import print_parsed_summary
from .quiet_utils import suppress_native_output

__all__ = ["get_parse_files", "list_parsers", "normalize_backend_name", "parse_files", "parse_files_quiet"]


# Map canonical backend names to (module, attribute)
_BACKEND_MAP: Dict[str, Tuple[str, str]] = {
    "music21": ("camat.music21_backend", "parse_files"),
    "partitura": ("camat.partitura_backend", "parse_files_partitura"),
    "mensural": ("camat.mensural_backend", "parse_files_mensural"),
    "timeline": ("camat.timeline_backend", "parse_files_timeline"),
    "verovio": ("camat.verovio_backend", "parse_files_verovio"),
}

# Common synonyms for convenience
_SYNONYMS: Dict[str, str] = {
    "m21": "music21",
    "music-21": "music21",
    "pt": "partitura",
    "part": "partitura",
    "mens": "mensural",
    "rap": "timeline",
    "humdrum-rap": "timeline",
    "vrv": "verovio",
}


def normalize_backend_name(name: str | None) -> str:
    """
    Normalize a backend name or None using environment default.

    Resolution order:
      1) Provided name
      2) Environment variable CAMAT_PARSER
      3) Fallback to "music21"
    """
    if not name:
        name = os.environ.get("CAMAT_PARSER", "") or "music21"
    key = str(name).strip().lower()
    return _SYNONYMS.get(key, key)


def list_parsers() -> List[str]:
    """Return the list of supported parser backend names."""
    return sorted(_BACKEND_MAP.keys())


def get_parse_files(backend: str | None = None) -> Callable:
    """
    Return the backend-specific parse_files callable without importing unused backends.

    Example:
        parse_files = get_parse_files("music21")
        results, dfs_by_name, last_df = parse_files([...])
    """
    name = normalize_backend_name(backend)
    if name not in _BACKEND_MAP:
        raise ValueError(
            f"Unknown backend '{backend}'. Choose from: {', '.join(list_parsers())}"
        )

    module_name, func_name = _BACKEND_MAP[name]
    try:
        module = import_module(module_name)
    except ImportError as exc:
        hint = ""
        if name == "partitura":
            hint = " Install 'partitura' via 'pip install partitura'."
        elif name == "mensural":
            hint = " Install 'verovio' via 'pip install verovio'."
        elif name == "verovio":
            hint = " Install 'verovio' via 'pip install verovio'."
        elif name == "timeline":
            hint = " Timeline parsing requires pandas, included in CAMAT dependencies."
        elif name == "music21":
            hint = " Install 'music21' via 'pip install music21'."
        raise ImportError(
            f"Failed to import backend '{name}' from {module_name}:{func_name}.{hint}"
        ) from exc

    try:
        func = getattr(module, func_name)
    except AttributeError as exc:
        raise ImportError(
            f"Backend '{name}' does not expose '{func_name}' in {module_name}"
        ) from exc

    return func


def parse_files(file_sources, *,
                parsing_backend: str | None = None,
                **kwargs):
    """
    Dispatch to the selected backend's parse_files function.

    Usage:
        from camat.parser_registry import parse_files
        results, dfs_by_name, last_df = parse_files(
            FILE_SOURCES,
            parsing_backend='partitura',  # or 'music21' (optional; env default applies)
            backend='bokeh',              # plotting backend is forwarded to the concrete parser
            print_parsed_summary=True,    # auto-print a quick summary (bool or mapping of kwargs)
            **other_kwargs
        )

    Additional keyword arguments
    ----------------------------
    print_parsed_summary : bool | Mapping[str, Any], optional
        When provided, automatically print a quick summary using
        ``parser_utils.print_parsed_summary``. Supplying a mapping allows
        overriding the helper's keyword arguments.
    """
    summary_option = kwargs.pop("print_parsed_summary", False)
    summary_enabled = False
    summary_kwargs: Dict[str, Any] = {}
    if isinstance(summary_option, Mapping):
        summary_enabled = True
        summary_kwargs = dict(summary_option)
    else:
        summary_enabled = bool(summary_option)

    func = get_parse_files(parsing_backend)
    outputs = func(file_sources, **kwargs)

    if summary_enabled and isinstance(outputs, (list, tuple)) and outputs:
        result_list = outputs[0]
        if isinstance(result_list, list):
            # Always separate summary header from parser logs for readability.
            print("")
            print_parsed_summary(result_list, **summary_kwargs)

    return outputs


def parse_files_quiet(file_sources, *,
                      parsing_backend: str | None = None,
                      quiet_native_warnings: bool = True,
                      suppress_stdout: bool = True,
                      suppress_stderr: bool = True,
                      **kwargs):
    """
    Convenience wrapper around parse_files that suppresses noisy native backend
    stdout/stderr output. For the partitura backend it also enables the backend's
    targeted native warning suppression.
    """
    backend_name = normalize_backend_name(parsing_backend)
    if backend_name == "partitura":
        kwargs.setdefault("quiet_native_warnings", bool(quiet_native_warnings))
    stdout_cm = redirect_stdout(io.StringIO()) if suppress_stdout else nullcontext()
    stderr_cm = redirect_stderr(io.StringIO()) if suppress_stderr else nullcontext()
    with stdout_cm, stderr_cm:
        with suppress_native_output(
            enabled=bool(quiet_native_warnings),
            suppress_stdout=bool(suppress_stdout),
            suppress_stderr=bool(suppress_stderr),
        ):
            return parse_files(file_sources, parsing_backend=parsing_backend, **kwargs)


