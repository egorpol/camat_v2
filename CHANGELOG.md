## 0.1.0 - first release

- Refactor for PyPI release (`pip install camat`).
- Copied package modules from `CAMAT_revamped/py_scripts` to `camat/`.
- Updated internal package references from `py_scripts.*` to `camat.*` / relative imports.
- Aligned `requirements.txt` with imports used by `camat/*.py`.
- Added packaging metadata via `pyproject.toml` and `MANIFEST.in`.
- Reformatted `README.md` for PyPI project page readability.
- Added mensural MEI preprocessing helpers and a dedicated script (`scripts/normalize_mensural_mei.py`) for partitura compatibility, including optional default meter injection for files missing time signatures.
- Added a partitura-first retry path that converts unsupported MEI structures through Verovio before parsing (reducing reliance on the legacy music21 fallback).

## 0.1.1

- Updated mensural parsing flow to prefer Verovio-first conversion when mensural MEI markers are detected.
- Added Verovio mensural options passthrough in partitura backend: `verovio_duration_equivalence` and `verovio_mensural_score_up`.
- Kept regex duration normalization and default meter injection as fallback compatibility steps after conversion.

## 0.1.2

- Read the Docs template integration
- Improved parser printout readability (summary now consistently separated from parser logs by a blank line).
- Clarified mensural + partitura behavior when Verovio-first conversion is enabled: mensural preprocessing (including optional meter injection) is still applied for sources detected as mensural, even if converted MEI no longer exposes explicit mensural markers.
- Added diagnostics for effective post-parse measure spacing (in quarter units), including warnings when injected meter (e.g., `4/4`) diverges from observed spacing (e.g., ternary-expanded `6`-quarter spans).
- Added MEI barline event extraction in the partitura backend, including barline `form` (e.g., `dashed`), onset mapping, and staff/layer context.
- Added event-to-pitch voice alignment for barline events so event `Voice` labels match parsed `df_pitch` voice labels.
- Added split parse outputs for partitura: `df_pitch` and `df_events`, with auto-named entries in `dfs_by_name` as `..._pitch` and `..._events` (`df` remains a compatibility alias to `df_pitch`).
- Added dedicated preview controls: `display_preview_df_pitch` and `display_preview_df_events` (legacy `display_preview` is still supported for compatibility).
- Added optional piano-roll overlay of parsed barlines with voice-based coloring via `plot_parsed_barlines_with_voice_coloring`.
- Updated `display_filtered_piano_roll` to accept/resolve `events_df` and render parsed barline overlays in filtered views, including voice and onset-window filtering.
- Updated filtered plotting to prefer parsed barline onsets for guide lines when barline overlays are enabled, avoiding mixed inferred-vs-parsed grid artifacts.
- Improved barline onset anchoring for mensural MEI by using staff/layer-local context and neighboring timed elements before fallback heuristics.
- Fixed voice color consistency between full and filtered plots by preserving a global voice-to-color mapping order (`preserve_voice_color_mapping`).