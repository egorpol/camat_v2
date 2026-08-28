# CAMAT

[![PyPI version](https://img.shields.io/pypi/v/camat.svg)](https://pypi.org/project/camat/)
[![Python versions](https://img.shields.io/pypi/pyversions/camat.svg)](https://pypi.org/project/camat/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/egorpol/camat_v2/blob/main/LICENSE)

CAMAT is an MEI-centered toolbox for editorial and analytical work with
symbolic music. The broader project covers edition-building, format conversion,
Python representations, DataFrame and matrix analysis, pattern search, and
score rendering.

This repository contains conversion, parsing, representation, analysis, and
rendering code. Edition-building and corpus-production tools currently live in
the separate [`camat_corpus`](https://github.com/egorpol/camat_corpus)
repository; the projects are intended to be joined later.

Supports Python 3.11+

## Installation

```bash
pip install camat
```

## What Is Included

- Conversion routes from symbolic formats to analysis MEI.
- Verovio-backed common-notation MEI parsing (the default parser).
- Compatibility parsers for `partitura` and `music21`.
- Timeline/rap Humdrum parsing with rhythm-only duration and onset-position summaries.
- Note and event DataFrames linked to the source MEI through `xml:id`.
- DataFrame distributions and piano-roll views.
- Binary pitch/time matrices with optional source-row provenance.
- Pattern search and similarity utilities.
- Match overlay helpers.
- A read-only MEI viewer for local files or URLs, with a full-width score fallback, optional
  measure-to-facsimile linking, and reload controls for active editing.
- Verovio-based rendering utilities.

## Parser Guidance

For common music notation, CAMAT now defaults to the `verovio` backend. The
analysis pipeline is MEI-first, so call `parse_files(...)` without a
`parsing_backend` for `.mei` sources, or select it explicitly with
`parsing_backend="verovio"` / `"vrv"`.

Convert non-MEI sources before parsing. Verovio-native inputs are converted
directly; other music21-readable formats go through
`music21 -> MusicXML -> Verovio -> MEI`. MuseScore-native files use MuseScore
for the MusicXML export. The conversion workflow is available in
`docs/guides/formats.md` and `notebooks/camat_formats.ipynb`. The corpus
converter is available as `camat.convert_sources(...)` and the installed
`camat-convert` command; `scripts/test_verovio_conversion.py` is retained only
as a compatibility entry point.

MIDI score conversion automatically detects common fine binary/triplet grids
from exact raw note-on ticks before music21 groups chords. `MidiImportOptions`
also accepts explicit grids for unusual tuplets and an optional diagnostic
layout that expands inferred local voice slots to separate staves.
Performance-oriented tick and tempo-map data is kept separate through
`camat.read_midi_timing(...)`, without MusicXML/MEI quantization. Batch
conversion supports safe streaming downloads, provenance sidecars, layered
validation records, and exact `resume_policy="if-unchanged"` reuse.

> [!WARNING]
> MIDI → music21 → MusicXML → Verovio conversion is experimental. It is useful
> for exploration and diagnostics, but it is known to produce incorrect rhythm,
> chord grouping, voices, rests, ties, or notation in some scores. Do not treat
> its MEI output as a reliable edition without measure-by-measure review.

The `partitura` backend remains the ground-truth/reference implementation for
parser parity tests. The `music21` backend remains available for compatibility
and as the converter's import bridge, but neither is the registry default.

For MCFlow-style rap Humdrum timelines, use `parse_files(..., parsing_backend="timeline")`. This returns `df_timeline` rows with stable MEI
ids and optional rhythm-analysis columns suitable for timeline MEI rendering.

## Documentation

This repo includes an MkDocs project in `docs/` and a Read the Docs config in
`.readthedocs.yaml`.

Local preview (install the docs extras into the same environment that can
import `camat`, then call MkDocs as a module so you do not pick up a bare
`mkdocs` on `PATH` that is missing Material):

```bash
pip install -r docs/requirements.txt
python -m mkdocs serve
```

Then open `http://127.0.0.1:8000/`.

Public score corpora used in tests are listed in
[Test sources](docs/guides/sources.md). The main MEI URL manifest is
`test_corpus/mei_test_copora_links.txt`.

Confirmed constraints are documented under
[Known limitations](docs/known-limitations.md). Track actionable defects and
feature requests in [GitHub Issues](https://github.com/egorpol/camat_v2/issues);
the repository includes structured issue templates for reproducible reports.

For the four workflows and the boundary between source MEI and derived
representations, start with [What CAMAT is](docs/overview.md). The
[notebook roadmap](docs/notebooks.md) maps each showcase notebook to its
workflow.

Workflow one now includes reusable inspection and validation components. Open
`notebooks/mei_facsimile_viewer.ipynb` for linked score/facsimile inspection,
or use `mei_corrected_full_checks.ipynb` as the maintainer probe for schema,
publication-profile, musical-consistency, page-link, and Verovio checks.
`single_mei_iiif_integration.ipynb` and `run_pipeline_workflow.ipynb` wrap the
packaged single-page and batch IIIF/measure-zone pipeline. Corpus data and run
configuration remain in `camat_corpus`.

## Release Testing

The release gate builds the wheel and installs it into fresh virtual
environments for Python 3.11 through 3.14:

```bash
python scripts/test_release_matrix.py
```

See [Release testing](docs/releasing.md) for interpreter discovery, partial
matrix commands, smoke-test coverage, and the tag-to-PyPI checklist.

## Repository Layout

- `camat/`: package source used for PyPI distribution.
- `CAMAT_old/`: legacy development notebooks and experiments.
- `CHANGELOG.md`: release notes.
- `test_corpus/`: URL manifests for public score corpora (no checked-in
  scores). See [Test sources](docs/guides/sources.md).

## License

MIT (see `LICENSE`).
