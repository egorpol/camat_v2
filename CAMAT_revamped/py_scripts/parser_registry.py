from __future__ import annotations

import os
from importlib import import_module
from typing import Callable, Dict, Tuple, List

__all__ = ["get_parse_files", "list_parsers", "normalize_backend_name", "parse_files"]


# Map canonical backend names to (module, attribute)
_BACKEND_MAP: Dict[str, Tuple[str, str]] = {
    "music21": ("py_scripts.music21_backend", "parse_files"),
    "partitura": ("py_scripts.partitura_backend", "parse_files_partitura"),
}

# Common synonyms for convenience
_SYNONYMS: Dict[str, str] = {
    "m21": "music21",
    "music-21": "music21",
    "pt": "partitura",
    "part": "partitura",
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
        from py_scripts.parser_registry import parse_files
        results, dfs_by_name, last_df = parse_files(
            FILE_SOURCES,
            parsing_backend='partitura',  # or 'music21' (optional; env default applies)
            backend='bokeh',              # plotting backend is forwarded to the concrete parser
            **other_kwargs
        )
    """
    func = get_parse_files(parsing_backend)
    return func(file_sources, **kwargs)


