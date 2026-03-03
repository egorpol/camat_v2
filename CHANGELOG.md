# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.3] - 2026-03-03

### Added

- Expanded partitura MEI event extraction beyond barlines to include annotations, lyrics, slurs, ties, fermatas, and additional semantic event tags such as `tempo`, `reh`, `harm`, `phrase`, `repeatMark`, `breath`, `caesura`, `gliss`, `arpeg`, and `harpPedal`.
- Lyric (`<syl>`) extraction as `lyric` events anchored to their parent note/chord, including dedicated lyric metadata fields.
- Added quiet helpers for noisy native output: `vrv_quiet(...)` for Verovio rendering calls and `parse_files_quiet(...)` / `quiet_native_warnings=True` for the partitura parser path.

### Changed

- Reworked `df_events` into an event-only schema with normalized columns such as `subtype`, `text_role`, `staff_raw`, `layer_raw`, `tstamp_raw`, `tstamp2_raw`, `verse_n`, `wordpos`, `con`, `mm`, `mm_unit`, `mm_dots`, and `extra`.
- Removed note-specific columns (`Pitch`, `Pitch Enharmonic`, `MIDI`) from `df_events`.
- Stopped overloading `form` for lyric metadata; `form` now preserves actual MEI `@form` values while lyric- and tag-specific metadata are stored in dedicated columns.
- Added a `dedupe_weaker_text_events` option to the partitura parser so weak duplicate text events can be dropped by default or preserved for raw inspection.
- Limited measure-spacing diagnostics to mensural MEI parsing, so common-notation files no longer emit irrelevant grid messages.
- Tightened event dataframe assembly to avoid pandas concat deprecation warnings when one event frame is empty.
- Deferred `requests` imports used for URL loading and suppressed dependency warnings during `requests` / `music21` import so normal local-file workflows no longer emit environment-level `RequestsDependencyWarning` noise.
- Improved Verovio plist highlighting so selected beamed notes also color their beam shapes, while preserving note-local targeting for the rest of the SVG.

### Fixed

- Preserved source-file MEI events when Verovio conversion strips unsupported `<annot>` elements, preventing annotation text from disappearing from `df_events`.
- Extended `quiet_native_warnings=True` to suppress partitura import `UserWarning`s in addition to native Verovio/partitura stdout/stderr noise.
- Avoided redundant page-1 Verovio renders during annotation processing, which previously duplicated parser/layout warnings in notebook output.
- Stopped emitting Verovio `Unsupported option 'svgAdditionalCSS'` errors on builds that do not expose that option by falling back to inline SVG highlight CSS only.
- Made `vrv_process_annotations(...)` assign stable internal annotation ids when `xml_id` is omitted, preventing repeated notebook runs from stacking duplicate tstamp-based annotations.

## [0.1.2] - 2025-03-02

### Added

- Read the Docs template integration.
- Diagnostics for effective post-parse measure spacing (in quarter units), including warnings when injected meter (e.g., `4/4`) diverges from observed spacing (e.g., ternary-expanded `6`-quarter spans).
- MEI barline event extraction in the partitura backend, including barline `form` (e.g., `dashed`), onset mapping, and staff/layer context.
- Event-to-pitch voice alignment for barline events so event `Voice` labels match parsed `df_pitch` voice labels.
- Split parse outputs for partitura: `df_pitch` and `df_events`, with auto-named entries in `dfs_by_name` as `..._pitch` and `..._events` (`df` remains a compatibility alias to `df_pitch`).
- Dedicated preview controls: `display_preview_df_pitch` and `display_preview_df_events` (legacy `display_preview` is still supported for compatibility).
- Optional piano-roll overlay of parsed barlines with voice-based coloring via `plot_parsed_barlines_with_voice_coloring`.

### Changed

- Improved parser printout readability (summary now consistently separated from parser logs by a blank line).
- Clarified mensural + partitura behavior when Verovio-first conversion is enabled: mensural preprocessing (including optional meter injection) is still applied for sources detected as mensural, even if converted MEI no longer exposes explicit mensural markers.
- Updated `display_filtered_piano_roll` to accept/resolve `events_df` and render parsed barline overlays in filtered views, including voice and onset-window filtering.
- Updated filtered plotting to prefer parsed barline onsets for guide lines when barline overlays are enabled, avoiding mixed inferred-vs-parsed grid artifacts.
- Improved barline onset anchoring for mensural MEI by using staff/layer-local context and neighboring timed elements before fallback heuristics.

### Fixed

- Voice color consistency between full and filtered plots by preserving a global voice-to-color mapping order (`preserve_voice_color_mapping`).

## [0.1.1] - 2025-02-01

### Added

- Verovio mensural options passthrough in partitura backend: `verovio_duration_equivalence` and `verovio_mensural_score_up`.

### Changed

- Mensural parsing flow now prefers Verovio-first conversion when mensural MEI markers are detected.
- Kept regex duration normalization and default meter injection as fallback compatibility steps after conversion.

## [0.1.0] - 2025-01-01

### Added

- Packaging metadata via `pyproject.toml` and `MANIFEST.in`.
- Mensural MEI preprocessing helpers and a dedicated script (`scripts/normalize_mensural_mei.py`) for partitura compatibility, including optional default meter injection for files missing time signatures.
- Partitura-first retry path that converts unsupported MEI structures through Verovio before parsing (reducing reliance on the legacy music21 fallback).

### Changed

- Refactor for PyPI release (`pip install camat`).
- Copied package modules from `CAMAT_revamped/py_scripts` to `camat/`.
- Updated internal package references from `py_scripts.*` to `camat.*` / relative imports.
- Aligned `requirements.txt` with imports used by `camat/*.py`.
- Reformatted `README.md` for PyPI project page readability.

---

[Unreleased]: https://github.com/egorpol/camat_v2/compare/v0.1.3...HEAD
[0.1.3]: https://github.com/egorpol/camat_v2/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/egorpol/camat_v2/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/egorpol/camat_v2/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/egorpol/camat_v2/releases/tag/v0.1.0
