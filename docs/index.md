---
title: CAMAT
---

# CAMAT

CAMAT (Computer-Assisted Music Analysis Toolbox) is an **MEI-centred Python
toolbox for editorial and analytical work with symbolic music**. Inspect and
prepare a musical document, convert other formats to MEI, then explore its
notes through tables, matrices, and notation.

Start with [Getting started](getting-started.md) for installation, an offline
example, and Jupyter setup. Use [Cloud notebooks](cloud-notebooks.md) on
Jupyter4NFDI or Colab. The [notebook roadmap](notebooks.md) collects the
executable tutorials in order.

## Choose a workflow

### 1. Handle MEI files

Render and inspect scores, link measures to facsimiles, combine page files,
and run editorial checks.

[Handling MEI files](guides/edition-building.md) ·
[MEI and XML introduction](guides/mei-introduction.md)

### 2. Convert to MEI

Import MusicXML, Humdrum, MuseScore, and other symbolic formats, from one
score or a mixed corpus. MIDI notation conversion is experimental.

[Convert to MEI](guides/formats.md) · [Batch conversion](guides/batch-conversion.md)

### 3. Parse and represent MEI

Turn common-notation MEI into note and event tables, explore a piano roll,
and link selections back to the score through MEI identifiers.

[Parse and represent MEI](guides/parsing-representations.md)

### 4. Analyse representations

Explore pitch and rhythm distributions, construct binary matrices, and search
for musical patterns with overlays on the original score.

[Analyse representations](guides/analysis.md)

## Go further

- [What CAMAT is](overview.md) explains how the four workflows fit together.
- [Known limitations](known-limitations.md) describes supported notation and experimental paths.
- [API reference](reference.md) maps the Python modules and entry points.
- [Edition corpora](guides/edition-corpora.md) introduces the working editions behind the editorial tools.
- [About CAMAT](about.md) covers funding, citation, and licenses.

These docs describe their source checkout. See
[package and documentation versions](releasing.md#documentation-and-package-versions)
when using an older release or a development branch.
