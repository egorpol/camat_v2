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

For MIDI, CAMAT scans exact raw note-on ticks before music21 import and extends
its baseline 32nd/triplet grid when common finer binary or triplet subdivisions
occur. It then separates staggered overlaps into music21 voices and fills their
gaps with visible rests before MusicXML export. This preserves short sequential
notes and voice offsets through Verovio instead of collapsing them into chords
or one MEI layer.

!!! warning "Do not run MIDI conversion as an unattended production pipeline"

    The MIDI → music21 → MusicXML → Verovio route is experimental and still
    produces incorrect notation in known cases. Reports and successful parsing
    prove technical completion, not musical correctness. Review the generated
    MEI measure by measure.

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
so its behaviour does not depend on where Jupyter was launched:

```python
from camat import (
    DownloadOptions,
    MidiImportOptions,
    convert_sources,
    expand_file_sources,
)

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
    midi_options=MidiImportOptions(),
    download_options=DownloadOptions(max_bytes=100 * 1024 * 1024),
    resume_policy="if-unchanged",
)
```

The direct Humdrum tutorial score comes from Craig Stuart Sapp's
[Beethoven piano-sonata encodings](https://github.com/craigsapp/beethoven-piano-sonatas);
the MIDI route uses the quantized score in the
[ASAP dataset](https://github.com/fosfrancesco/asap-dataset).

## Resuming safely

Every successful generated MEI has a `.camat.json` sidecar. With
`resume_policy="if-unchanged"`, CAMAT skips conversion only when all of these
still match:

- source SHA-256;
- detected format and conversion route;
- normalized MIDI, download, rendering, and Verovio options;
- relevant music21, MuseScore, and Verovio versions;
- report-schema version;
- generated MEI SHA-256.

The returned record remains `status="ok"` and sets `skipped=True` plus a
human-readable `resume_reason`. `resume_policy="force"` redownloads remote
sources and reconverts. The default `"never"` reconverts but may reuse an
already downloaded source.

## Download preflight and failure stages

Remote sources stream into a temporary file and replace the cache target only
after a successful, non-empty download. The default maximum is 100 MiB. HTML
responses are rejected because they usually indicate a GitHub `blob` page or
another landing page rather than a raw score. An optional content-type
allow-list supports exact values and wildcards such as `audio/*`.

Failure records retain partial provenance and expose `failure_stage` plus
`failure_code`, distinguishing download, format detection, music21 parsing,
MusicXML export, MuseScore export, Verovio conversion, and MEI validation.

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
  --n-jobs 1 \
  --resume
```

An explicit unusual MIDI grid and stricter download limit (the default grid is
`auto`):

```bash
camat-convert \
  --source path/to/scores.txt \
  --midi-grid 16,11,8,6,4,3 \
  --max-download-mb 50 \
  --resume
```

For a diagnostic score with each inferred local MIDI voice slot on a separate
staff, add `--midi-voices-to-staves`. MIDI has no persistent notated-voice
identity, so this layout must not be interpreted as automatic contrapuntal
voice tracking across measures.

Use `--no-midi-quantize` only as a score-import diagnostic. For genuine
microtiming, use `camat.read_midi_timing(...)` rather than MusicXML/MEI.

Generated MEI and `conversion_report.json` go under `converted_mei/` (gitignored).
Output filenames include a short source-URL/path hash, so sources such as the
ASAP files that are all named `midi_score.mid` cannot overwrite one another.
The JSON report records requested and resolved URLs, HTTP metadata, hashes and
sizes, normalized options, tool versions, stage durations, route diagnostics,
and generated MEI checks.

Validation remains explicitly layered:

```text
downloaded → converted → valid MEI → rendered → CAMAT-parsed → editorially inspected
```

Conversion fills the first four stages. A notebook or application can mark the
CAMAT parse with `set_validation_stage(...)`; editorial inspection remains a
deliberate human step rather than an automatic success flag.

For older checkout-based commands, `scripts/test_verovio_conversion.py`
remains a compatibility entry point; new code should use the package API or
installed command above.

## See also

- [Convert to MEI](formats.md)
- Next workflow: [Parse and represent MEI](parsing-representations.md)
- API: [conversion](../api/conversion.md) and
  [`vrv_convert_to_mei`](../api/verovio_render.md)
- Maintainer corpus probe: `testing_verovio_conversion.ipynb`
