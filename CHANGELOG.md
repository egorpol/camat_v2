# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.7] - 2026-03-15

### Added

- Added mensural rest timing extraction as `rest` rows in `df_events`, with a staff/layer-local symbolic-duration fallback for cases where Verovio does not expose rest timings directly.
- Added a repository-level `mkdocs.yml` plus Markdown-based docs pages so the project docs now build through MkDocs Material with `mkdocstrings`.
- Added common-notation parser guidance to the docs, making `partitura` the recommended primary backend and documenting `music21` as the legacy-compatible alternative.
- Added binary-matrix provenance and coordinate helpers in `camat.music_utils`, including per-cell / per-window source-row lookup, raw row/column mapping helpers, and slice decoding that preserves original matrix coordinates.
- Added notebook-facing binary refactor helpers in `camat.music_utils`, including `create_binary_matrix_bundle(...)`, `BinaryMatrixBundle.slice(...)`, and `BinaryMatrixSliceBundle`, so binary exploration cells can stay declarative while reusing shared summary, slice-table, highlight, and plotting logic.

### Changed

- Migrated the documentation toolchain away from Sphinx to MkDocs, updated `docs/requirements.txt` to the verified MkDocs package versions, and pointed `.readthedocs.yaml` at the MkDocs build on Python 3.10.
- Removed the legacy Sphinx config and generated `.rst` API pages from `docs/`, and refreshed the README / project metadata so MkDocs + Read the Docs is the documented default.
- Updated the `music21` backend to expose `df_pitch` / `df_events`, parse note ids into `xml_id`, emit rest events, and reuse the MEI event extraction path for common-notation files when available.
- Removed the legacy `display_preview` alias from the parser backends in favor of the explicit `display_preview_df_pitch` and `display_preview_df_events` controls.
- Expanded `plot_binary_matrix(...)` with shared parser-style plotting controls, optional highlight overlays, sectioned binary/selected-area/source-data hover tooltips, configurable hover cell scope (`active`, `active_or_highlighted`, `all`), and matching `plt`/`bokeh` show-return behavior.
- Refreshed `testing_binary_representations.ipynb` so the binary showcase uses raw matrix row/column semantics explicitly, provenance-aware slice decoding, and the same binary plotting backend configuration as the main parse/plot workflow.
- Further simplified `testing_binary_representations.ipynb` so its binary setup and showcase cells are now mostly parameter blocks plus high-level bundle calls, with repetitive summary printing, hover normalization, slice bookkeeping, and highlight-window assembly moved into shared `camat.music_utils` helpers.

### Fixed

- Fixed mensural barline anchoring after nested containers such as `<ligature>` and after trailing rest sequences, so direct mensural parsing now stays aligned with the corresponding Verovio score render.
- Fixed the `partitura` fallback-to-`music21` path so it preserves the fallback backend's `df_events` output instead of replacing it with an empty event dataframe.
- Fixed binary slice reconstruction for row-sliced matrix windows so decoded pitch/time spans stay aligned with the original raw matrix coordinates instead of being reinterpreted as if the slice started at row 0.

## [0.1.6] - 2026-03-08

### Added

- Added `camat.verovio_guard.guarded_load_into_verovio_toolkit(...)` to probe Verovio loads in a subprocess before touching the in-process toolkit, so native Verovio crashes during MEI import surface as normal Python errors instead of killing the notebook kernel.
- Added a dedicated `mensural` parser backend and public `parse_files_mensural(...)` wrapper so render-aligned mensural parsing no longer depends on the common `partitura` path.

### Changed

- Updated the mensural backend to load MEI timing data through the new Verovio guard path, including targeted recovery for files that crash Verovio when `<custos>` elements are present.
- Updated Verovio score loading helpers (`vrv_load_data(...)`, `vrv_load_from_file(...)`, `vrv_load_from_url(...)`) to use the same guarded load path and emit explicit warnings when a sanitized retry is used.
- Refreshed `testing_parser_mensural.ipynb` so follow-up cells resolve the active `dfs_by_name` pitch/event keys dynamically instead of relying on stale hard-coded dataframe names from an older example.
- Split direct mensural parsing into `camat.mensural_backend`, while keeping `parse_files_partitura(..., use_verovio_mensural_timing=True)` as a backward-compatible delegation path instead of a second embedded implementation.
- Registered the dedicated mensural backend in `parser_registry` (`parsing_backend='mensural'`, plus the `mens` synonym) and exported `parse_files_mensural(...)` at the package top level.
- Added an explicit parser warning when the common `partitura` path detects mensural MEI, steering users toward the dedicated mensural commands for Verovio-render-aligned results.
- Simplified the notebook entry cells so `testing_parser_mensural.ipynb` is mensural-only and `testing_events_parse.ipynb` no longer carries mensural-only parser knobs.

### Fixed

- Fixed a reproducible native Verovio segfault on certain mensural MEI files during `loadFile(...)` / `loadData(...)` by retrying after stripping `<custos>` elements when that specific crash signature is detected.
- Prevented `testing_parser_mensural.ipynb` from failing after a successful parse due to outdated hard-coded dataframe names in the preview and filtered piano-roll cells.
- Fixed mensural note/event alignment drift against the original Verovio render by keeping dedicated mensural parsing on the source-MEI timeline instead of mixing source barlines with CMN-converted note timing.
- Fixed collapsing of distinct mensural barlines that lacked `xml:id` by using a stronger MEI event merge key with per-staff ordering and neighboring note anchors.
- Filled inferred `Measure` / `Local Onset` values for parsed barline events when a usable measure grid exists, improving event dataframe consistency in the common parser path.

## [0.1.5] - 2026-03-04

### Fixed

- Fixed GitHub release-note extraction in `.github/workflows/release.yml` so tagged releases correctly capture the body of the matching changelog section instead of treating it as empty.

## [0.1.4] - 2026-03-04

### Added

- Added a repository-level `.readthedocs.yaml` so Read the Docs can build the bundled project docs without extra project-specific setup.
- Added `check_monophonic_input(...)` in `camat.analysis_utils` for reusable monophony validation, including per-voice checks when a voice column is available.
- Added `melodic_interval_distribution(...)` in `camat.analysis_utils` for successive melodic interval analysis, with optional per-voice pooling and the same monophony safety checks used by the successive pitch bigram utilities.
- Added `display_melodic_interval_distribution(...)` in `camat.analysis_utils` as a notebook-facing wrapper for interval distribution tables and bar plots, with multi-source support, optional normalization, and display-only float formatting.

### Changed

- Added project URL metadata in `pyproject.toml` to improve the PyPI project sidebar links.
- Refreshed the README header and docs section with badges, corrected Python support wording, and updated local documentation preview instructions.
- Expanded `camat.analysis_utils` notebook plotting helpers:
  `display_pitch_distribution(...)`, `display_duration_distribution(...)`, and `display_pitch_class_distributions(...)` now support per-source normalization, explicit normalized plot titles, and configurable display-only float formatting for tables and plot labels/hover values.
- Updated pitch-class distribution helpers to accept `pitch_axis` / `order_axis_by` controls and improved octave-less pitch-class sorting so chromatic ordering via MIDI semantics works for labels such as `C#`, `Db`, and similar spellings.
- Updated `display_successive_pitch_transition_heatmaps(...)` so `normalize` is the primary normalization control (`False`/`'count'`, `'row'`, `'column'`, `'all'`), added display-only float formatting, and made monophony validation enabled by default via `require_monophonic=True`.

### Fixed

- Removed a pandas future warning in successive-pitch heatmap row normalization by avoiding object-dtype `fillna(...)` during matrix division.

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

[Unreleased]: https://github.com/egorpol/camat_v2/compare/v0.1.7...HEAD
[0.1.7]: https://github.com/egorpol/camat_v2/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/egorpol/camat_v2/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/egorpol/camat_v2/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/egorpol/camat_v2/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/egorpol/camat_v2/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/egorpol/camat_v2/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/egorpol/camat_v2/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/egorpol/camat_v2/releases/tag/v0.1.0
