# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Credited Egor Polyakov (research and development) and Martin Pfleiderer
  (supervision), and documented the 2021–2022 MusicXML tool as CAMAT's predecessor.
- Credited Pia Steuck as CAMAT's student assistant and the six student
  assistants supporting its edition corpora.
- Added an offline getting-started guide, Jupyter setup, contribution guidance,
  citation metadata, and archive/provenance notes.
- Bundled the MEI schema's ECL-2.0 license and third-party notices in package
  distributions, and added a JupyterLab `notebooks` installation extra.
- Release checks now validate dated notes before publication, mark GitHub
  prereleases explicitly, and retain tested dependency versions as CI artifacts.

### Changed

- Simplified the README, documentation home, and API index; linked the README
  and package metadata to the deployed Read the Docs site, with stable and
  development documentation distinguished explicitly.
- Updated notebook link labels and stale fixture/viewer descriptions while
  preserving all saved notebook outputs.
- Excluded the incomplete test subset from source distributions; contributors
  run tests from a Git checkout with its fixtures and archived probes.

## [0.2.1] - 2026-09-07

### Added

- Added full checkout regression tests and a strict documentation build to CI,
  including beta branch pushes and the existing tag-to-PyPI release gate.
- Documentation now displays the checkout's package version and resolves
  repository links against the build commit, with checked relative links that
  also work when reading the Markdown on GitHub.

- Added Workflow 4 notebook `notebooks/binary_convolution_explained.ipynb`:
  toy host/kernel placements, then a Bach sliding-window convolution explainer
  with animation, stride / padding (`valid` vs `same`), and kernel time-scale
  demos. Cross-linked from `binary_pattern_search` and the analysis guide.

- Added Workflow 4 binary notebooks `notebooks/binary_roundtrip.ipynb` (MEI →
  `df_pitch` / piano roll → binary → reconstruct → MEI highlight) and
  `notebooks/binary_pattern_search.ipynb` (Bach motif / chord / texture kernels
  with scaled-window normalised-overlap search). Docs: home Workflow 4,
  notebook roadmap, and [Analyse representations](docs/guides/analysis.md).

- Added Workflow 4 tutorial notebook `notebooks/df_statistics.ipynb` (CMN):
  self-contained parse of the Bach *Ein feste Burg* sample to `df_pitch` /
  `df_events`, then pitch, duration, pitch-class, transition, interval, and
  onset-position distributions. Docs: home Workflow 4 section, notebook
  roadmap, and [Analyse representations](docs/guides/analysis.md).
  `display_successive_pitch_transition_heatmaps` is exported from the package
  root alongside the other distribution helpers.

- Added Workflow 3 tutorial notebooks `notebooks/mei_parse_tables.ipynb` (parse
  one CMN MEI file to `df_pitch` / `df_events` and a filtered piano roll) and
  `notebooks/mei_annotate_selection.ipynb` (multi-voice selection, `plist` /
  `tstamp` annotations, and optional saved selection MEI). Docs: home Workflow 3
  section, notebook roadmap, and
  [Parse and represent MEI](docs/guides/parsing-representations.md).

- Added `launch_interactive_mei_renderer` with on-screen score zoom controls
  for the paste-and-render notebook. The renderer uses an A4-like Verovio page
  so the staff stays readable; CSS zoom then enlarges the notation rather than
  stretching a very wide, short page.
- Added packaged helpers for a single-file IIIF job: `parse_bsb_viewer_url`,
  `resolve_iiif_image_url`, `download_facsimile_image`, and `stage_mei_copy`.
  `detect_and_integrate_mei` now accepts an explicit `graphic_target` so the
  IIIF link does not have to come from the MEI filename.
- Added `camat.iiif_page` (`plan_iiif_pages`, `integrate_iiif_pages`) and
  `notebooks/mei_batch_iiif_integration.ipynb` for the same IIIF job over a
  list of files. Extra Buxtehude example pages live in `test_corpus/`.
- Added `prepare_pages_for_combine` and `run_editorial_checks` so the
  combine-and-check notebook can run the corrected-full-MEI suite without
  defining helpers. Example pages are in `test_corpus/buxtehude_pages/`.
- Added beginner notebooks `notebooks/mei_combine_pages.ipynb` (join page
  files into one score) and `notebooks/mei_check_report.ipynb` (editorial
  checks and a CSV report). `notebooks/mei_consistency_checks.ipynb` remains
  the full combine/check toolkit.

### Changed

- Dropped the extra `requirements-test.txt` and `requirements-release.txt`
  files. Pytest is the package `test` extra; the release runner installs
  `build` and `twine` directly.

- Convolution explainer notebook: denser toy host/kernel catalog, nonempty
  random windows, a labelled overlap heatmap, and valid vs same padding on
  those same toy placements before the Bach demos. Large animation outputs
  are no longer stored in the notebook file.

- `run_pattern_search(..., padding="valid"|"same")` exposes the convolution
  boundary mode used in the explainer (`valid` remains the default).

- `resolve_mei_source` / `resolve_mei_source_info` accept `fetch=False` (return
  ``None`` for an uncached remote URL instead of downloading) and
  `shared_cache=True` (use the same download cache as `parse_files`). Workflow 3
  notebooks call the packaged helper instead of defining a local copy.

- The facsimile notebook viewer now lives in a single widget iframe instead of
  an ``Output`` HTML display. That stops Cursor/VS Code from drawing a second
  stacked copy, while zone hovers still run on the first render.
- The single-file IIIF notebook uses `test_corpus/Buxtehude-Anhang-S._185_musicxml_verovio.mei`,
  no longer depends on `camat_corpus`, and can take a pasted IIIF image URL.
  The batch notebook uses the same helpers for several pages.
- The combine-and-check notebook no longer depends on `camat_corpus`.
- The MkDocs home page is now a starting map for all four workflows. Test
  sources sit under Convert to MEI. The conversion guide title is Convert to MEI.
- Docs now point at the work-in-progress edition repositories
  ([DdT vol. 11](https://github.com/egorpol/DdT_1_vol_11),
  [DdT vol. 29/30](https://github.com/egorpol/DdT_1_vol_29_30)) via
  [Edition corpora](docs/guides/edition-corpora.md) instead of a
  `camat_corpus` repository.
- The overview mermaid chart is top-to-bottom with a larger font so it stays
  readable in the docs content column. The Convert to MEI route diagram uses
  the same layout instead of a wide SVG.
- Documented that common-notation MEI (MEI 5.1 CMN) is the supported schema.
  Mensural and timeline/rap backends are experimental and not thoroughly tested.
- The home page and README record DFG funding for the whole CAMAT project
  (LIS, grant PF 669/18-1), not only the edition corpora.

### Fixed

- Restored offline defaults in the facsimile viewer and consistency-check
  tutorials, cleared saved outputs, and moved report output back into the
  checkout's ignored directory. Updated tests and documentation links for
  maintainer notebooks moved into `CAMAT_old/`.

- `compute_top_matches_df` no longer passes `dropna=` to `DataFrame.stack()`,
  which pandas 2.2+/3 rejects. NA scores are dropped after stacking instead.

- Bokeh piano-roll hover no longer lists fields that are missing from the
  note table (for example `Pitch Enharmonic` when `parse_enharmonic` is
  off), which previously showed as `???`.

- `combine_meis` no longer drops later pages' opening `<scoreDef>` (staff list
  and meter). Those headers sit beside `<section>`, so a section-only join lost
  mid-piece meter and scoring changes. The join now copies a later page's
  opening `<scoreDef>` into the combined section when staffing, meter, key, or
  clefs differ. Identical page headers are omitted.
  `CombineResult.inserted_page_score_defs` reports how many were copied; the
  consistency notebook prints that count. Pass `include_page_score_defs=False`
  to restore the old join.

## [0.2.1b1] - 2026-08-29

### Added

- Integrated Workflow 1 MEI consistency, cleanup, figured-bass anchor,
  page-break/facsimile, RELAX NG, and Verovio checks into the installable
  `camat` package. Added the packaged MEI 5.1 CMN schema, three CLI entry
  points, and a read-only-by-default corrected-full-MEI maintainer notebook.
- Migrated the remaining `camat_corpus` IIIF acquisition, measure-detection,
  annotation-integration, page-coverage, validation, metadata, cleanup, and
  batch-pipeline helpers into `camat`, together with opt-in single-file and
  batch Workflow 1 maintainer notebooks.

### Changed

- MIDI score conversion now infers common finer binary and triplet grids from
  exact raw note-on ticks before music21 chord grouping. Explicit
  `quarter_length_divisors` still override inference, and conversion reports
  include the evidence and effective grid. This preserves the 64th-note run in
  Beethoven Op. 13/i, measure 9, instead of collapsing adjacent notes into
  chords.
- Documented the MIDI → music21 → MusicXML → Verovio route as experimental and
  added a versioned known-limitations page plus GitHub bug/feature templates.
- Simplified the facsimile notebook to one local-path-or-URL `MEI_SOURCE`, with
  a public CAMAT corpus edition as its default. Source resolution (GitHub
  `blob` pages, remote download, and checkout-relative paths) now lives in
  `camat.facsimile_viewer.resolve_mei_source`, so the notebook no longer
  defines helper functions. Verovio layout warnings such as
  "Justification is highly compressed" are hidden unless
  `SHOW_VEROVIO_WARNINGS` is True. Viewer instances now use unique DOM ids and defer
  JavaScript initialization until notebook output is attached, so score-page
  controls work on the initial render.
- Added multi-surface facsimile navigation: changing the rendered Verovio page
  now switches to the surface referenced by that page's measures, while direct
  measure interaction selects the exact linked surface. Facsimile frames reserve
  image dimensions and scrollbar space so selection does not resize the pane.
- Added independent client-side score and facsimile zoom controls, configurable
  initial percentages, step, and range, and documented Verovio's non-visual
  handling of `@plist`- and `@tstamp`-anchored `<annot>` text.

## [0.2.0] - 2026-08-17

### Added

- Integrated the read-only MEI facsimile viewer from `camat_corpus` as
  `camat.facsimile_viewer`, including top-level parsing, cached Verovio
  rendering, interactive measure-zone linking, local-image embedding, optional
  file watching, tests, API guidance, and a workflow-one notebook.
- Added configurable score-oriented MIDI import through `MidiImportOptions`
  and `--midi-grid`, including explicit 64th/higher-resolution and unusual
  tuplet-grid support, quantization-error diagnostics, and per-conversion
  voice/gap-rest controls. The optional `voice_layout="separate_staves"` /
  `--midi-voices-to-staves` diagnostic layout expands inferred local voice
  slots to separate staves while explicitly recording that MIDI provides no
  persistent notated-voice identity.
- Added `read_midi_timing(...)` for performance-oriented MIDI analysis without
  score quantization or chord grouping. It preserves raw note-on/off ticks and
  exposes exact PPQ quarter-length fractions, tempo-aware seconds, and the
  tempo map as DataFrames.
- Added safe batch resumption with provenance sidecars. Outputs are skipped
  only when source and output hashes, route, normalized options, report schema,
  and relevant tool versions are unchanged.
- Added streaming download limits and content-type checks, resolved-URL and
  tool-version provenance, stage timings, stable failure stage/code fields,
  and an explicit validation progression from download through editorial
  inspection.
- Expanded `test_corpus/mei_test_copora_links.txt` with complete-work MEI from
  CRIM, TROMPA encodings, Measuring Polyphony, The Beggar's Opera, and iFolk,
  and added a MkDocs [Test sources](docs/guides/sources.md) page that documents
  every corpus.
- Added an optional `highlight_style="mei-friend"` treatment to Verovio
  annotation rendering, using mei-friend's familiar blue selection color and
  short pulse animation. The pulse color can be customized with `pulse_color`.
- Added `vrv_crop_svg_to_ids(...)` and `vrv_crop_svgs_to_ids(...)` for visual
  Verovio excerpts that can start or end within a measure while retaining the
  selected staves and omitting pages without selected elements.
- Added `vrv_mask_mei_to_ids(...)` and `vrv_render_selection_excerpt(...)` for
  rendering selected source notes on otherwise blank staves. Unselected events
  become duration-preserving MEI spaces, partial beams are safely unwrapped,
  and the previously loaded Verovio score is restored after rendering.
- Added `vrv_render_symbolic_selection(...)`, which accepts a `df_pitch`
  selection directly, uses its `xml_id` values to retain source-MEI notation,
  and keeps the selected staff's clef, key signature, and meter in the rendered
  excerpt. Inline clef/key/meter changes active at the selection are promoted
  into its opening context, and the helper can also return the generated
  standalone excerpt MEI.

### Changed

- Reorganized the MkDocs site around CAMAT's four MEI-centered workflows,
  clarified the boundary with `camat_corpus`, and added workflow, notebook,
  source-corpus, parsing/representation, and analysis guidance.
- Expanded the file-format and batch-conversion notebooks with real MuseScore
  and MIDI examples from the non-MEI test manifest, configurable MIDI-grid and
  raw-timing inspection, resumable runs, and report-backed validation stages;
  added a focused MIDI → music21 → Verovio regression notebook for inspecting
  quantization, voice reconstruction, and alternative staff layouts.
- Promoted mixed-format conversion from the repository test script to the
  supported `camat.conversion` package API. `convert_sources(...)` is now
  importable directly from `camat`, and installed environments provide the
  `camat-convert` command; the former script path remains a compatibility
  entry point.
- Renamed `test_corpus/test_corpus_links.txt` to
  `test_corpus/non_mei_test_copora_links.txt` and dropped the overlapping MEI
  sample-encoding URLs already covered by `mei_test_copora_links.txt`.
- Cleared checked-in scores from `test_corpus/`. That directory now holds URL
  manifests only.
- Added CC0 OpenScore and official MuseScore demo files to
  `test_corpus/non_mei_test_copora_links.txt` for the MuseScore conversion
  path.
- Added quantized score MIDI from ASAP and complete Playford dances from
  the Nottingham Music Database to
  `test_corpus/non_mei_test_copora_links.txt` for the music21 conversion
  path.

### Removed

- Removed local MusicXML, MuseScore, MIDI, and MEI files from `test_corpus/`,
  plus `small_corpus.txt` and `verovio_only_regression_sources.txt`.

### Fixed

- Resynchronized the packaged duration-semantics MEI with its canonical test
  fixture so installed-wheel release checks and the documented expressive-note
  example use identical data.
- Made the MEI facsimile notebook and interactive API accept scores without
  facsimile records. They now render a full-width score-only view, retain
  strict parsing for editorial validation, and can switch to the linked view
  after facsimile records are added without rerendering unchanged notation.
- Expanded music21 MIDI post-quantization through straight 32nd notes while
  retaining triplet grids. Sequential ornaments such as the G4/F4 figures in
  the BWV 846 Fugue no longer collapse into simultaneous 16th-note chords.
- Reconstructed staggered MIDI overlaps as music21 voices with visible gap
  rests before MusicXML export. This preserves delayed voices such as the BWV
  846 Prelude's lower-staff sixteenth rest followed by E4 when Verovio creates
  MEI.
- Made batch-conversion output names source-unique so same-basename inputs such
  as ASAP's `midi_score.mid` files cannot overwrite one another, and added
  source/output SHA-256 plus byte-size provenance to conversion reports.
- Scoped annotation highlight CSS to a unique attribute on each rendered SVG,
  preventing repeated MEI/SVG ids from applying one notebook cell's selection
  highlights to other cell outputs. High-level annotation helpers no longer
  persist their highlight rules in the shared Verovio toolkit, and the
  annotation notebook now reloads the source score at the start of each
  independent render cell to avoid carrying annotations between cells.

## [0.1.13] - 2026-08-11

### Added

- Exposed the backend-dispatching `parse_files(...)` function directly from
  `camat`, while retaining `camat.parser_registry.parse_files` as the original
  import path.
- Bundled the duration-semantics MEI example as package data so
  `duration_semantics_examples.ipynb` can run from a fresh wheel installation
  without relying on the repository's `tests/fixtures` directory.
- Added explicit `Logical Duration` and nullable `Performed Duration` columns
  to Verovio-backed `df_pitch` output. `Logical Duration` is recorded once per
  logical note and sums every segment in a tie chain exactly once, while
  `Performed Duration` remains unset until a separate empirical or rule-based
  performance model supplies it.
- Added `duration_semantics_examples.ipynb`, an offline tutorial showing how to
  render the local example score, parse metric segments with
  `collapse_tied_pitch_events=False`, parse logical notes with
  `collapse_tied_pitch_events=True`, inspect duration-neutral note metadata,
  attach optional performed durations, and build distributions for an
  explicitly selected duration concept.
- Added an offline duration-semantics MEI fixture, focused pytest coverage, and
  `scripts/diagnose_duration_semantics.py` for dotted notes, container and span
  tuplets, grace notes, explicit and attribute-encoded tie chains, attachment
  metadata, and collapsed/uncollapsed duration invariants.

### Changed

- Defined Verovio `df_pitch.Duration` consistently as the metric duration of
  the represented encoded segment, including dots and tuplet ratios. Collapsing
  tied pitch events now removes continuation rows without overwriting the chain
  head's segment duration; the complete tie-chain value is available separately
  in `Logical Duration`.
- Added an explicit `duration_column` selector to `build_duration_counts(...)`
  and `display_duration_distribution(...)`, and exposed logical/performed
  duration fields in piano-roll hover data.
- Expanded MEI note-attachment extraction so compact note/chord `@tie`
  encodings populate `tied`, and every note covered by a `tupletSpan` is marked
  as `start`, `member`, or `stop` rather than only marking its endpoints.

### Fixed

- Fixed Verovio grace-note timing so grace notes have zero metric duration and
  do not advance the encoded layer cursor.
- Fixed `tupletSpan` timing so `num`/`numbase` ratios are included in metric
  duration, while avoiding a second ratio application when notes are already
  inside an equivalent `<tuplet>` container.
- Fixed collapsed multi-segment and compact `@tie` chains so continuation
  durations are summed exactly once and uncollapsed rows retain their original
  segment durations.

## [0.1.12] - 2026-08-09

### Added

- Added an installed-wheel release test pipeline for Python 3.11 through 3.14,
  including fresh local virtual environments, offline package smoke fixtures,
  a GitHub Actions compatibility matrix, and a publishing gate that requires
  all supported Python versions to pass before a tagged release is built.
- Raised the minimum supported Python version to 3.11 so every supported
  interpreter can install a current Verovio wheel.
- Added a Verovio-backed common-notation MEI parser via `parse_files(..., parsing_backend="verovio")` and the `"vrv"` alias. It preserves CAMAT's `df_pitch` / `df_events` result shape for MEI sources, keeps Partitura as the parity reference, and includes `scripts/test_verovio_common_parser.py` as its structural comparison harness.

### Changed

- Made the Verovio MEI parser the registry default. Partitura remains the
  ground-truth backend for parity testing, while non-MEI analysis sources are
  expected to be converted to MEI first.
- Generalized the converter's music21 bridge from MIDI-only input to any format
  music21 can read: unsupported source -> MusicXML -> Verovio -> MEI. Verovio
  still performs the final conversion, and conversion reports now record the
  selected route.
- Normalized `df_pitch.Measure` and `df_pitch.Local Onset` against CAMAT's shared `measure_offsets` grid after parsing, so Partitura and Verovio outputs use the same encoded-measure ordinal and right-aligned initial-pickup convention instead of leaking backend-specific measure labels.
- Replaced the ambiguous `strip_ties` parser option with `collapse_tied_pitch_events`, which controls only whether tied continuations are collapsed in `df_pitch`; MEI tie rows remain part of the complete `df_events` event parse. The deprecated `strip_ties` keyword is still accepted as a compatibility alias.
- Made Partitura parsing honor `collapse_tied_pitch_events=False` by building `df_pitch` from source note segments instead of Partitura's tied-note `note_array()` view, allowing untied Verovio/Partitura comparisons to align.
- Aligned the Verovio backend's collapsed tied-note handling with Partitura for note-level MEI tie continuations (`tie="m"` / `tie="t"`), including orphan continuation rows without explicit `<tie startid="..." endid="...">` links.
- Corrected common-notation MEI note timing in the Partitura backend from source symbolic durations when Partitura's importer drifts, fixing the Mozart fugue double-dotted duration at `d1e26843` and the resulting one-quarter onset shift.

## [0.1.11] - 2026-07-07

### Added

- Added MuseScore-native `.mscz` / `.mscx` support to the Verovio conversion workflow via an optional MuseScore Studio/CLI export step: MuseScore sources are converted to intermediate MusicXML, then passed through the existing Verovio-to-MEI pipeline. The conversion report now records the intermediate MusicXML path and emits a clear optional-dependency message when MuseScore is unavailable.

### Fixed

- Restored the NumPy `row_stack` alias before importing Partitura so Partitura 1.9.0 can run under newer NumPy builds that no longer expose `np.row_stack`.

## [0.1.10] - 2026-06-07

### Added

- Added the timeline/rap Humdrum parser as a first-class parser backend via `parse_files(..., parsing_backend="timeline")`, with `rap` and `humdrum-rap` aliases, top-level exports, and stable `df_timeline` result entries.
- Added timeline-native rhythm analysis helpers: `build_timeline_duration_counts(...)`, `build_timeline_onset_position_counts(...)`, and `add_timeline_rhythm_analysis(...)`. The timeline schema now reserves duration/onset distribution columns so rhythm-only analyses can be carried into MEI lyric/annotation views without requiring pitch data.
- Added `scripts/test_timeline_backend.py`, an offline py310 smoke test covering timeline parsing, rhythm-schema enrichment, MEI generation, duplicate `xml:id` checks, and Verovio loading.
- Added timeline backend API docs and tutorial/reference guidance for parsing MCFlow-style rap Humdrum sources.

### Changed

- Refreshed `testing_timeline.ipynb` so the timeline workflow computes duration and onset-position summaries from `df_timeline`, enriches `df_timeline_rhythm`, and renders rhythm-share fields through configurable lyric-info lines.
- Added an `ACTIVE_SOURCE` selector to `testing_timeline.ipynb` so different MCFlow timeline sources can drive the same MEI export and statistics cells without rewriting downstream code.
- Reworked the timeline onset-position notebook plot to reuse `display_onset_position_histogram(...)` with timeline-derived measure offsets instead of a separate custom plotting path.
- Added automatic timeline onset binning via `bin_size="auto"` / `onset_bin_size="auto"`, which uses the smallest positive timeline duration and avoids manually hard-coding grids such as `0.125`.
- Updated the timeline Verovio notebook settings to encode four measures per system and use a wider page, preventing every measure from being forced onto its own line and reducing distorted pickup/final-measure spacing.
- Added `lyric_info_value_formats` and `lyric_info_max_value_chars` to timeline MEI export so analysis values such as duration share (`D`) and onset-position share (`O`) can be rendered as compact percentages instead of long raw floats.
- Exposed existing duration-distribution helpers (`build_duration_counts`, `plot_duration_distribution`, `display_duration_distribution`) from the top-level `camat` package.
- Preserved source order for `parse_files_partitura(..., n_jobs > 1)` results instead of returning entries in worker completion order.

### Fixed

- Fixed timeline onset-position grouping so rest-filtered histograms infer measure/meter spans from the full timeline context instead of creating spurious `3.75` / `4.25` meter groups in otherwise `4/4` sources.
- Fixed MEI note-attachment extraction after common-notation MEI sanitization/conversion so `df_pitch` attachment columns such as `fermata`, `slurred`, `articulations`, and `ornaments` are populated from the persistent source MEI when temporary parser files have already been cleaned up.
- Fixed `scripts/test_mei_coverage.py` so it resolves CAMAT's hashed remote-download cache filenames, allowing the coverage test to run after normal cached parsing.

## [0.1.9] - 2026-05-05

### Added

- Added MEI measure metadata extraction to `df_events`, including dedicated `type == "measure"` rows and `measure_type`, `measure_metcon`, `measure_join`, and `measure_n` columns for measure-aware analysis.
- Added `build_onset_position_counts(...)` and `display_onset_position_histogram(...)` in `camat.analysis_utils` (re-exported from the top-level `camat` package), with combined multi-source plotting, time-signature/span summaries, bin-size warnings, per-measure debug output, and metadata-aware pickup/incomplete-measure handling through `edge_measure_mode='merge_to_regular' | 'split_by_span'`. Auto-resolves per-source `reference_df` / `events_df` / `measure_offsets` from the notebook's `dfs_by_name`, `results`, `selection`, and full-source DataFrame when not passed explicitly.
- Added an onset-position beat histogram cell to `testing_annot_stats.ipynb` that drives the new helper with `ONSET_BIN_SIZE`, `ONSET_NORMALIZE`, `ONSET_EDGE_MEASURE_MODE`, `ONSET_USE_MEASURE_METADATA`, `ONSET_SHOW_MEASURE_DEBUG`, `ONSET_BAR_COLOR`, and `ONSET_FLOAT_FORMAT`.
- Added a Verovio-to-MEI conversion pipeline in `testing_verovio_conversion.ipynb` backed by `scripts/test_verovio_conversion.py`, with conversion reports, downloaded-source caching, XML ID / note / measure sanity checks, optional first-page SVG smoke tests, and subprocess isolation around native Verovio imports.
- Added support for converting plain MusicXML (`.xml`, `.musicxml`), compressed MusicXML (`.mxl`), Humdrum/Kern (`.krn`, `.kern`, `.hum`), and existing MEI sources into MEI for downstream parser analysis.
- Added an opt-in MIDI import path for `.mid` / `.midi` sources through `music21 -> MusicXML -> Verovio`, recording the intermediate MusicXML file in the conversion report so lossy notation inference can be inspected.
- Added compressed MusicXML loading to the shared Verovio helpers in `camat.verovio_render`, so `.mxl` files are auto-detected and handled by `vrv_load_from_file(...)`, `vrv_load_from_url(...)`, and `vrv_convert_to_mei(...)`.
- Added TXT source-list expansion to the Verovio conversion workflow, reusing `camat.parser_utils.expand_file_sources(...)` so `testing_verovio_conversion.ipynb` and `scripts/test_verovio_conversion.py --source test_corpus/test_corpus_links.txt` can convert newline-separated corpora directly.

### Fixed

- Fixed the onset-position histogram producing a separate plot per inferred measure span when `edge_measure_mode='merge_to_regular'` and the source contained internal MEI barline splits (e.g. a 4/4 piece with a 3+1 split mid-piece). Runs of consecutive short internal measures whose spans sum to the regular meter span are now packed into a single virtual regular-sized measure (the second in the run is offset by the first's span), so the combined plot stays unified. With `edge_measure_mode='split_by_span'` the legacy per-span plots are preserved.

## [0.1.8] - 2026-04-17

### Added

- Added `n_jobs`, `use_remote_cache`, and `remote_cache_dir` parameters to `parse_files_partitura` / `parse_files_mensural` so multi-file runs can parse in a thread pool and reuse downloaded URL sources from `~/.cache/camat/downloads` (overridable via `CAMAT_DOWNLOAD_CACHE_DIR`). Plot and DataFrame display remain serialized to keep notebook output deterministic.
- Added `get_download_cache_dir(...)` and `is_cached_download(...)` helpers plus a `use_cache=True` option on `camat.music_utils.get_file_path`.
- Added a `PARALLEL_N_JOBS` / `USE_REMOTE_CACHE` / `REMOTE_CACHE_DIR` parameter block to `testing_annot_stats.ipynb` so the demo cell exposes the new options directly.
- Extended the partitura backend's MEI event extractor to cover ornaments (`trill`, `mordent`, `turn`, `ornam`, `bTrem`, `fTrem`), articulations / fingering / bend (`artic`, `fing`, `bend`), continuous markings (`pedal`, `octave`, `ending`, `beamSpan`, `tupletSpan`), mid-piece definition changes (`clef`, `keySig`, `meterSig` — tagged as `scope="setup"` vs `scope="change"` depending on whether they sit inside `scoreDef`/`staffDef`), whole-measure and invisible rests (`mRest`, `multiRest`, `space`), `custos`, and standalone `accid`. Note-internal `<accid>` children are explicitly suppressed since the pitch row already carries the accidental.
- Added `include_note_attachments` (default `True`) to `parse_files_partitura` / `partitura_score_to_dataframe`. When enabled on MEI sources, `df_pitch` gains `grace`, `tied`, `slurred`, `tuplet`, `fermata`, `articulations`, `ornaments`, and `technical` columns joined on `xml_id`. The attachments are sourced by walking the MEI XML directly (via the new `_extract_mei_note_attachments` helper) because partitura 1.8's MEI importer does not currently hydrate `slur_starts` / `fermata` / `articulations` onto its `Note` objects.
- Added `scripts/test_mei_coverage.py`, an autotest that parses the 3 MEI examples now active in `testing_annot_stats.ipynb` and cross-checks every music-relevant MEI element against `df_events.type` counts and every note-attachment column against the raw XML. The test fails loudly if any music-relevant element is silently dropped.
- Added the Beethoven Op.31 No.3 MEI (trompa HenleUrtext) to `FILE_SOURCES` in `testing_annot_stats.ipynb` so the common-notation notebook exercises all 3 MEI test examples end-to-end.

### Changed

- Vectorized the partitura note-array → DataFrame conversion (`_part_to_dataframe`) using NumPy column extraction, a MIDI→pitch-name LUT, and unique-onset measure anchoring, removing the per-note Python hot path inside `partitura_score_to_dataframe`.
- Switched enharmonic spelling to partitura's `include_pitch_spelling=True` note-array output when available, keeping the legacy `part.notes` traversal as a fallback.
- Cached MEI event extraction by `(path, mtime, size)` and precomputed per-layer subtree indexes so repeated `_extract_mei_events` calls on the same file reuse the result and barline anchoring no longer re-walks sibling subtrees per barline.
- Simplified `filter_and_adjust_durations` to avoid the unconditional deep-copy and to round the three onset/duration columns in a single operation; dropped the redundant second sort after filtering in `parse_files_partitura`.

### Fixed

- Fixed `n_jobs > 1` parsing failing with "Bravura font could not be loaded" / "Document is empty" for every MEI source. Verovio loads its font resources at `verovio.toolkit(...)` construction time via code that is not thread-safe; constructing a toolkit from any non-main thread permanently breaks the global C++ font tables for the whole process, and serialising construction with a mutex is not enough. partitura's own MEI importer unconditionally creates a fresh toolkit on every `load_score(...)`, which is the call that was breaking under the thread pool. The partitura backend now builds a single Verovio toolkit on the main thread at import time and monkey-patches `verovio.toolkit` to hand that singleton out instead, so partitura (and our own `_convert_mei_with_verovio_for_partitura`) reuse the healthy main-thread instance from every worker. `_VEROVIO_LOCK` serializes actual `setOptions`/`loadData`/`getMEI` use of that shared toolkit, and `_load_partitura_score` additionally acquires it for `.mei` inputs so partitura's internal Verovio transaction is held as a single critical section. `suppress_native_output` and `_suppress_partitura_dependency_output` serialize fd-level and `sys.stdout` / `sys.stderr` redirection through a shared `threading.RLock` so the Verovio C++ logs no longer clobber each other.
- Added `scripts/test_parallel_parse.py` as a runnable autotest that exercises the parser at `n_jobs=1` and `n_jobs=2` against a fixed set of remote MEI sources, records per-thread timings for `partitura.load_score`, and asserts that no two threads are simultaneously inside the partitura/Verovio critical sections.
- Separated `testing_annot_stats.ipynb` from the mensural code paths: added a scope comment, removed the commented-out Dufay mensural URL from `FILE_SOURCES`, and explicitly passes `normalize_mensural_durations=False`, `inject_missing_meter_signature=False`, `prefer_verovio_for_mensural=False`, and `use_verovio_mensural_timing=False` to `parse_files(...)` so the partitura backend stays on the common-notation fast path regardless of its defaults. Added `scripts/test_common_notation_only.py` as a matching autotest that runs the same kwargs and asserts the parser log contains no mensural lines.

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

[Unreleased]: https://github.com/egorpol/camat_v2/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/egorpol/camat_v2/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/egorpol/camat_v2/compare/v0.1.13...v0.2.0
[0.1.13]: https://github.com/egorpol/camat_v2/compare/v0.1.12...v0.1.13
[0.1.12]: https://github.com/egorpol/camat_v2/compare/v0.1.11...v0.1.12
[0.1.11]: https://github.com/egorpol/camat_v2/compare/v0.1.10...v0.1.11
[0.1.10]: https://github.com/egorpol/camat_v2/compare/v0.1.9...v0.1.10
[0.1.9]: https://github.com/egorpol/camat_v2/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/egorpol/camat_v2/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/egorpol/camat_v2/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/egorpol/camat_v2/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/egorpol/camat_v2/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/egorpol/camat_v2/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/egorpol/camat_v2/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/egorpol/camat_v2/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/egorpol/camat_v2/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/egorpol/camat_v2/releases/tag/v0.1.0
