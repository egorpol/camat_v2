---
title: Known limitations
---

# Known limitations and issue tracking

These are the current scope limits and confirmed constraints. Report a
reproducible defect or propose an improvement through
[GitHub Issues](https://github.com/egorpol/camat_v2/issues).

## Common-notation MEI is the supported schema

**Status:** MEI 5.1 Common Music Notation (CMN) is the schema CAMAT is built
and tested against. Mensural MEI and timeline/rap Humdrum are experimental.

Editorial checks, IIIF/facsimile integration, page combine, the facsimile
viewer, conversion to analysis MEI, and the default Verovio parser all assume
**common-notation MEI**. Workflow 1 notebooks and the packaged MEI 5.1 CMN
RELAX NG schema follow that contract.

General validation accepts an explicit alternative schema, but this does not
establish support for every notation customization in the musical diagnostics,
assembly helpers or consumers. The configured schema and descriptive profile
are recorded; a directory or composer never selects a DdT profile implicitly.

Two other paths exist but have **not been tested thoroughly**:

- **mensural** — a specialized mensural-MEI backend and duration-normalization
  helpers;
- **timeline** — a rap-Humdrum backend (MCFlow-style examples) that produces
  `df_timeline` rather than `df_pitch`.

Treat those backends as prototypes. Do not rely on them for production
editions or unattended analysis. The APIs are documented under
[Backend and specialized parsing](tutorial.md).

## General MEI validation scope

The [validation guide](guides/mei-validation.md) describes the passes and result
categories. Current limits include:

- Local/bundle references are checked; remote authority references are recorded
  without fetching their documents. Schematron inputs must be self-contained;
  external include graphs are rejected.
- Rhythm diagnostics cover common written durations, dots, enclosing tuplets,
  meter changes, grace exclusion and `metcon="false"`. Timing through editorial
  alternatives such as `choice`/`app`, duration defaults and additive durations
  is not comprehensively supported. Review those findings in their score context.
  Separate tie-continuity, accidental-consistency and source-comparison passes
  are not implemented.
- CAMAT parsing verifies that a consumer returns nonempty tables and records
  their row counts. It does not prove an exact match between each XML event and
  the parsed music. Verovio warnings can occur on schema-conformant scores.
- HTTP image checks use HEAD reachability/content type, without downloading or
  decoding the remote image. Geometry uses declared surface bounds and does
  not infer a coordinate mapping from the first graphic's pixel dimensions.
- Interrupted runs retain incomplete progress records, but native validator and
  consumer calls do not yet have automatic hard timeouts.

General conformance does not decide editorial fidelity, licensing or corpus
publication acceptance. Those require the corpus policy and editorial review.

## Experimental MIDI conversion

**Status:** experimental; not suitable for unattended edition production.

The MIDI → music21 → MusicXML → Verovio route can produce musically incorrect
MEI while completing without a software error. Known failure classes include:

- sequential notes collapsed into chords, or chords split into sequences;
- incorrect quantized durations, rests, ties, tuplets, or measure filling;
- unstable or editorially implausible voice reconstruction;
- loss of spelling, articulation, and other notation MIDI does not encode.

Automatic grid inference and diagnostics reduce specific failures but cannot
resolve MIDI's semantic ambiguity. Inspect generated MEI measure by measure.
For performance timing, use `read_midi_timing(...)` instead of the notation
conversion route.

## Facsimile viewer scope

The linked viewer switches among MEI `<surface>` elements according to the
measure links on the active Verovio page. If one rendered score page contains
measures from multiple surfaces, it initially shows the surface referenced by
the most measures; hovering or clicking a linked measure selects its exact
surface. Remote MEI is downloaded and cached. The interactive viewer also
downloads remote `<graphic>` targets at a display width and inlines them,
because Jupyter and VS Code/Cursor notebook widget iframes cannot fetch
third-party IIIF URLs. Pass `embed_remote_graphics=False` only for standalone
HTML in a normal browser; that pane then needs network access for as long as
it is open.

Verovio preserves `<annot>` records anchored by `@plist` or `@tstamp`, but does
not engrave their paragraph text. CAMAT supplies an annotation list and score
highlights in its viewer, controlled by `show_annotations`; see
[annotation rendering](api/facsimile_viewer.md#annotation-rendering).
