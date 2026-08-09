---
title: CAMAT Documentation
---

# CAMAT

CAMAT is a Python toolkit for symbolic music parsing, analysis, pattern search, and score rendering.

## Backend Guidance

For common music notation, CAMAT defaults to the `verovio` backend and treats
MEI as the analysis format. Calling `parse_files(...)` without selecting a
backend therefore parses common-notation MEI with Verovio.

Partitura remains the reference backend for parser parity tests. Music21 is
retained for compatibility and as an import bridge in the conversion workflow.

Convert non-MEI inputs first. Verovio-native formats convert directly; other
music21-readable formats follow `music21 -> MusicXML -> Verovio -> MEI`.

## Contents

- [Tutorial](tutorial.md)
- [Reference](reference.md)
