---
title: CAMAT Documentation
---

# CAMAT

CAMAT is a Python toolkit for symbolic music parsing, analysis, pattern search, and score rendering.

## Backend Guidance

For common music notation, prefer the `partitura` backend. It is the primary
parser in CAMAT and has the strongest support for MEI, `xml_id` tracking,
explicit event extraction, and backend parity across the notebook workflows.

The `music21` backend is retained for legacy compatibility. It can still parse
common-notation files and now exposes the same high-level result shape
(`df_pitch` and `df_events`), but it should be treated as a secondary option.

## Contents

- [Tutorial](tutorial.md)
- [Reference](reference.md)
