---
title: Notebook roadmap
---

# Notebook roadmap

The notebooks are executable companions to the conceptual guides. Each should
answer one main question, declare its input and output, and avoid relying on
state created by another notebook.

## Recommended order

| Order | Notebook | Workflow | Main result |
| --- | --- | --- | --- |
| 1 | [`camat_formats.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_formats.ipynb) | convert to MEI | corpus-backed MEI pass-through, direct Humdrum/MusicXML conversion, and a MIDI bridge |
| 2 | [`camat_batch_conversion.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_batch_conversion.ipynb) | convert to MEI | mixed-route MEI files, technical validation, and a JSON report |
| 3 | [`duration_semantics_examples.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/duration_semantics_examples.ipynb) | parse and represent MEI | note tables that distinguish segment, logical, and performed duration |

The conversion notebooks are alternatives after their shared introduction:
use the first for one score or for learning routes, and the second for a mixed
corpus.

## Coverage and next tutorials

| CAMAT workflow | Current coverage | Next documentation task |
| --- | --- | --- |
| Create MEI editions | notebooks in the separate `camat_corpus` repository | define a small hand-off example for one reviewed MEI page |
| Convert to MEI | corpus-backed single-file and batch notebooks, including MIDI via music21 | refine configurable quantization and resumable large-corpus conversion |
| Parse and represent MEI | duration semantics example only | add a general MEI-to-`df_pitch`/`df_events` notebook |
| Analyse representations | no focused showcase notebook yet | add DataFrame → piano roll → binary matrix → pattern match → score overlay |

## Notebook contract

A CAMAT showcase notebook should include:

1. its workflow number and a link to the companion guide;
2. a small offline input, with network or external-tool examples kept optional;
3. a short statement of what each representation means;
4. explicit names for the MEI source, `df_pitch`, `df_events`, matrix, and
   matrix metadata rather than a chain of ambiguous `df` variables;
5. a final “what was produced?” summary and the next notebook or guide;
6. a clean-kernel execution check before publication.

Maintainer probes such as `testing_verovio_conversion.ipynb` are deliberately
not part of this tutorial sequence. They test implementation behavior rather
than teach a user workflow.
