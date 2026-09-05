---
title: Known limitations
---

# Known limitations and issue tracking

This page records broad, confirmed constraints users need to see before using
CAMAT. Actionable bugs, proposed fixes, and feature work belong in
[GitHub Issues](https://github.com/egorpol/camat_v2/issues), where they can be
assigned, discussed, linked to pull requests, and closed with an auditable
history.

Git itself tracks source changes; it is not an issue tracker. A professional
repository workflow uses both:

- this page for stable user-facing limitations;
- one GitHub issue per reproducible defect or bounded enhancement;
- labels such as `bug`, `enhancement`, `workflow:midi`, and
  `workflow:facsimile` for filtering;
- milestones only when an issue is committed to a particular release;
- pull requests that close issues with `Fixes #123` when the fix is verified.

The repository's **Bug report** and **Feature request** templates collect the
minimum context needed for triage. Do not put vague future ideas into source
comments or a growing TODO file; open an issue once the work is concrete enough
to describe and verify.

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
not engrave their paragraph text. The facsimile viewer currently has no custom
annotation popover or overlay, so annotation text is not visible.
