---
title: Batch conversion
---

# Batch conversion

Single-file conversion uses the public helper `vrv_convert_to_mei(...)`.
Mixed corpora, MuseScore files, crash isolation, and a conversion report use
the checkout helper `scripts/test_verovio_conversion.py`.

Companion notebooks:

- Concepts and tiny examples: [`notebooks/camat_formats.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_formats.ipynb)
- Batch helper: [`notebooks/camat_batch_conversion.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_batch_conversion.ipynb)

The batch helper is not part of the installed wheel. Run it from a CAMAT
checkout.

## When to use which

| Task | Tool |
| --- | --- |
| One MusicXML / Kern / ABC file | `vrv_convert_to_mei(...)` |
| Many files, mixed formats, JSON report | `convert_sources(...)` in the script |
| `.mscz` / `.mscx` | MuseScore CLI, then Verovio (the batch helper does this) |
| MIDI and other music21-only formats | music21 → MusicXML → Verovio (the batch helper does this) |

Each Verovio import in the batch helper runs in a child process so a native
crash cannot take down the notebook kernel.

## Direct URLs and source-list files

The batch helper detects HTTP and HTTPS URLs automatically. Local `.txt` files
are expanded as newline-separated source manifests. They may mix URLs and local
paths, and blank lines plus lines beginning with `#` are ignored:

```text
# Local path
tests/fixtures/basic.musicxml

# Remote Humdrum score
https://raw.githubusercontent.com/craigsapp/bach-370-chorales/0fd9e00542445a522c6030c80c687b874aa569d5/kern/chor002.krn
```

When `source_base_dir` is supplied, both the manifest path and local entries in
the manifest resolve from that directory. The notebook uses the repository root,
so its behavior does not depend on where Jupyter was launched:

```python
from camat import expand_file_sources
from scripts.test_verovio_conversion import convert_sources

expanded = expand_file_sources(
    ["notebooks/data/batch_sources.txt"],
    base_dir=ROOT,
)
records = convert_sources(
    expanded,
    source_base_dir=ROOT,
    expand_txt_sources=False,
)
```

The remote tutorial score comes from Craig Stuart Sapp's
[Bach 370 Chorales](https://github.com/craigsapp/bach-370-chorales)
edition ([CC BY-NC-SA 4.0](https://github.com/craigsapp/bach-370-chorales/blob/main/LICENSE.txt)).

## Command line

From the repository root:

```bash
python scripts/test_verovio_conversion.py \
  --source tests/fixtures/basic.musicxml \
  --n-jobs 1
```

A newline-separated list of local paths or URLs:

```bash
python scripts/test_verovio_conversion.py \
  --source notebooks/data/batch_sources.txt \
  --n-jobs 1
```

Generated MEI and `conversion_report.json` go under `converted_mei/` (gitignored).
Do not overwrite the original sources. Parse the `.mei` files with
`parse_files(...)` after a quick inspection.

## See also

- [File formats](formats.md)
- API: [`vrv_convert_to_mei`](../api/verovio_render.md)
- Maintainer corpus probe: `testing_verovio_conversion.ipynb`
