---
title: Batch conversion
---

# Batch conversion

This is **CAMAT workflow 2: convert sources to MEI**, scaled to a corpus. The
output MEI files are inputs to parsing and still require inspection.

Single-file conversion uses the public helper `vrv_convert_to_mei(...)`.
Mixed corpora, MuseScore files, crash isolation, and a conversion report use
the public `convert_sources(...)` API or `camat-convert` command.

Companion notebooks:

- Corpus-backed direct conversion: [`notebooks/camat_formats.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_formats.ipynb)
- Batch conversion: [`notebooks/camat_batch_conversion.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_batch_conversion.ipynb)

## When to use which

| Task | Tool |
| --- | --- |
| One MusicXML / Kern / ABC file | `vrv_convert_to_mei(...)` |
| Many files, mixed formats, JSON report | `convert_sources(...)` / `camat-convert` |
| `.mscz` / `.mscx` | MuseScore CLI, then Verovio (`convert_sources(...)` does this) |
| MIDI and other music21-only formats | music21 → MusicXML → Verovio (`convert_sources(...)` does this) |

Each Verovio import in the batch helper runs in a child process so a native
crash cannot take down the notebook kernel.

For MIDI, CAMAT quantizes through straight 32nd notes as well as triplet grids,
then separates staggered overlaps into music21 voices and fills their gaps with
visible rests before MusicXML export. This preserves short sequential notes and
voice offsets through Verovio instead of collapsing them into chords or one MEI
layer.

## Direct URLs and source-list files

The batch helper detects HTTP and HTTPS URLs automatically. Local `.txt` files
are expanded as newline-separated source manifests. They may mix URLs and local
paths, and blank lines plus lines beginning with `#` are ignored. The corpora
behind those lists are documented in [Test sources](sources.md).

```text
# A local path is allowed
path/to/local-score.musicxml

# A remote Humdrum score from the canonical test manifest
https://raw.githubusercontent.com/craigsapp/beethoven-piano-sonatas/master/kern/sonata14-1.krn
```

When `source_base_dir` is supplied, both the manifest path and local entries in
the manifest resolve from that directory. The notebook uses the repository root,
so its behavior does not depend on where Jupyter was launched:

```python
from camat import convert_sources, expand_file_sources

expanded = expand_file_sources(
    ["test_corpus/non_mei_test_copora_links.txt"],
    base_dir=ROOT,
)
# Select a deliberately mixed tutorial subset instead of converting all entries.
selected = [
    next(source for source in expanded if "sonata14-1.krn" in source),
    next(source for source in expanded if "Schubert_D911-07.xml" in source),
    next(source for source in expanded if "Amazing_grace.mscz" in source),
    next(source for source in expanded if "Bach/Prelude/bwv_846/midi_score.mid" in source),
    next(source for source in expanded if "Bach/Fugue/bwv_846/midi_score.mid" in source),
]
records = convert_sources(
    selected,
    source_base_dir=ROOT,
    expand_txt_sources=False,
)
```

The direct Humdrum tutorial score comes from Craig Stuart Sapp's
[Beethoven piano-sonata encodings](https://github.com/craigsapp/beethoven-piano-sonatas);
the MIDI route uses the quantized score in the
[ASAP dataset](https://github.com/fosfrancesco/asap-dataset).

## Command line

From an environment with CAMAT installed:

```bash
camat-convert \
  --source https://raw.githubusercontent.com/craigsapp/beethoven-piano-sonatas/master/kern/sonata14-1.krn \
  --n-jobs 1
```

A newline-separated list of local paths or URLs:

```bash
camat-convert \
  --source test_corpus/non_mei_test_copora_links.txt \
  --n-jobs 1
```

Generated MEI and `conversion_report.json` go under `converted_mei/` (gitignored).
Output filenames include a short source-URL/path hash, so sources such as the
ASAP files that are all named `midi_score.mid` cannot overwrite one another.
The JSON report records SHA-256 hashes and byte sizes for the downloaded source
and generated MEI. Parse the `.mei` files with `parse_files(...)` after a quick
inspection.

For older checkout-based commands, `scripts/test_verovio_conversion.py`
remains a compatibility entry point; new code should use the package API or
installed command above.

## See also

- [File formats](formats.md)
- Next workflow: [Parse and represent MEI](parsing-representations.md)
- API: [`vrv_convert_to_mei`](../api/verovio_render.md)
- Maintainer corpus probe: `testing_verovio_conversion.ipynb`
