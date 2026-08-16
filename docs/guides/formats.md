---
title: File formats
---
# File formats

This is **CAMAT workflow 2: convert sources to MEI**. It creates the input for
the parsing workflow; it does not turn an imported score into a reviewed
edition.

CAMAT analyzes **MEI**. `parse_files(...)` expects common-notation MEI and
defaults to the Verovio parser. Convert other encodings to MEI first, then
parse the converted file.

Companion notebook: [`notebooks/camat_formats.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_formats.ipynb).
Open that file in Jupyter or Cursor from the checkout. It selects real MEI,
Humdrum, MusicXML, and MIDI URLs from the `test_corpus` manifests; it is not
executed as part of this docs build.

## Conversion routes

Verovio always writes the MEI that CAMAT parses. The steps before that depend
on the source format:

![CAMAT conversion routes to MEI](../assets/format-conversion.svg)

| Source                 | Typical extensions                                                       | Route                                        |
| ---------------------- | ------------------------------------------------------------------------ | -------------------------------------------- |
| Already MEI            | `.mei`                                                                 | Parse directly. No conversion.               |
| Verovio-native         | `.musicxml`, `.xml` (MusicXML), `.mxl`, `.krn`, `.abc`, …     | `vrv_convert_to_mei(...)`                  |
| Other music21-readable | `.mid`, `.midi`, and anything music21 can import that Verovio cannot | music21 exports MusicXML, then Verovio       |
| MuseScore              | `.mscz`, `.mscx`                                                     | MuseScore CLI exports MusicXML, then Verovio |

`.xml` is ambiguous (MEI or MusicXML). CAMAT sniffs the file contents rather
than trusting the suffix.

## Already MEI

```python
from camat import parse_files

results, dfs_by_name, df_pitch = parse_files(["path/to/score.mei"])
```

Keep the original file. Conversion is an import step, not an archival
replacement.

## Verovio-native formats

Use the public helper. It loads the source into Verovio, returns MEI as a
string, and leaves that score in the toolkit for rendering:

```python
from pathlib import Path
from camat import vrv_convert_to_mei, vrv_guess_input_from, vrv_quiet

source = "path/to/score.musicxml"
print(vrv_guess_input_from(source))

with vrv_quiet():
    mei_text = vrv_convert_to_mei(source)

Path("score.mei").write_text(mei_text, encoding="utf-8")
```

Native Verovio inputs include MEI, MusicXML / compressed MusicXML, Humdrum,
ABC, PAE, DARMS, EsAC, and Volpiano.

## Remote sources

For a direct internet source, use a raw file URL and pass `is_url=True`. A
GitHub repository or `blob` page is HTML and is not a score source. Public
MEI and mixed-format corpora used in CAMAT tests are listed in
[Test sources](sources.md).

```python
from pathlib import Path
from camat import vrv_convert_to_mei, vrv_quiet

url = (
    "https://raw.githubusercontent.com/craigsapp/beethoven-piano-sonatas/"
    "master/kern/sonata14-1.krn"
)

with vrv_quiet():
    mei_text = vrv_convert_to_mei(url, is_url=True, timeout=30)

Path("sonata14-1.mei").write_text(mei_text, encoding="utf-8")
```

The example is one of the Beethoven piano-sonata Humdrum sources in
`test_corpus/non_mei_test_copora_links.txt`. The notebook reads that manifest
rather than embedding an independent source list. Set
`CAMAT_RUN_NETWORK_EXAMPLES=0` to inspect the notebook structure without
downloading scores.

## music21 bridge

Formats Verovio cannot identify, including MIDI, go through music21. Export
MusicXML, then convert that MusicXML with Verovio so the analysis file is
still Verovio MEI. The public converter applies the complete bridge:

```python
from camat import convert_sources

records = convert_sources(
    ["path/to/score.mid"],
    output_dir="converted_mei/my_import",
)
print(records[0]["output_mei"])
```

The companion notebook executes this route with the ASAP BWV 846 score MIDI
from `test_corpus/non_mei_test_copora_links.txt`. Its downloaded MIDI and
intermediate MusicXML are retained as working/provenance files beside the MEI.
The converter expands music21's default post-quantization grid from `(4, 3)` to
`(8, 6, 4, 3)`: straight 32nds such as the adjacent G/F ornament in BWV 846
remain sequential, while binary and triplet subdivisions are retained. It
applies voice reconstruction only to measures containing staggered overlapping
notes. `fillGaps=True` is important: it exports visible rests rather than
hidden MusicXML rests that Verovio would represent as MEI `<space>` elements.

MIDI in particular is lossy: spelling, voices, meter, and articulations are
reconstructed. Inspect the MEI before treating it as ground truth.

## MuseScore files

`.mscz` / `.mscx` are not Verovio inputs. If MuseScore Studio or the `mscore`
CLI is on `PATH` (or `MUSESCORE_BIN` points at it), export MusicXML with
MuseScore, then convert with Verovio. Without MuseScore, convert the file to
MusicXML or MEI in the editor first.

`convert_sources(...)` implements that route. The batch notebook selects a real
`.mscz` URL from the test manifest and records a clear failure if MuseScore is
unavailable.

## After conversion

Point `parse_files(...)` at the generated `.mei`, not at the original MusicXML
or MIDI:

```python
from camat import parse_files

results, dfs_by_name, df_pitch = parse_files(["score.mei"])
```

This also applies to downloaded scores: parse the saved MEI rather than passing
a remote Humdrum or MusicXML URL directly to the default MEI parser.

Generated `xml:id` values are stable for a fixed Verovio version and options.
They are not permanent scholarly identifiers across Verovio upgrades. Keep the
source file next to the MEI.

## See also

- Next workflow: [Parse and represent MEI](parsing-representations.md)
- Tutorial notebook: [`notebooks/camat_formats.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_formats.ipynb)
- Batch conversion: [Batch conversion](batch-conversion.md) and
  [`notebooks/camat_batch_conversion.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_batch_conversion.ipynb)
- API: [`vrv_convert_to_mei`](../api/verovio_render.md)
