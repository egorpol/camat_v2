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

Two other paths exist but have **not been tested thoroughly**:

- **mensural** — a specialized mensural-MEI backend and duration-normalization
  helpers;
- **timeline** — a rap-Humdrum backend (MCFlow-style examples) that produces
  `df_timeline` rather than `df_pitch`.

Treat those backends as prototypes. Do not rely on them for production
editions or unattended analysis. The APIs are documented under
[Backend and specialized parsing](tutorial.md).

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
surface. Remote MEI and remote `<graphic>` targets require network access when
they are first loaded.

Verovio preserves `<annot>` records anchored by `@plist` or `@tstamp`, but does
not engrave their paragraph text. CAMAT supplies an annotation list and score
highlights in its viewer, controlled by `show_annotations`; see
[annotation rendering](api/facsimile_viewer.md#annotation-rendering).
