"""Compatibility entry point for the package conversion CLI.

New code should import :func:`camat.convert_sources` or run ``camat-convert``.
This path remains executable for existing checkout-based commands.
"""

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from camat.conversion import (
    DEFAULT_SOURCES,
    DownloadOptions,
    MidiImportOptions,
    _file_fingerprint,
    _output_mei_path,
    _prepare_midi_score_for_export,
    convert_sources,
    main,
    print_conversion_summary,
)

_print_summary = print_conversion_summary

__all__ = [
    "DEFAULT_SOURCES",
    "DownloadOptions",
    "MidiImportOptions",
    "convert_sources",
    "main",
    "print_conversion_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
