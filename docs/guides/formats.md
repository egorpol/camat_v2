---
title: Convert to MEI
---
# Convert to MEI

This is **CAMAT workflow 2**. It converts MusicXML, Humdrum, MIDI, MuseScore,
and other symbolic formats to MEI. Conversion creates input for parsing; it
does not turn an imported score into a reviewed edition.

CAMAT analyses **MEI**. `parse_files(...)` expects common-notation MEI and
defaults to the Verovio parser. Convert other encodings to MEI first, then
parse the converted file.

Companion notebook: [`notebooks/camat_formats.ipynb`](https://github.com/egorpol/camat_v2/blob/main/notebooks/camat_formats.ipynb).
Open that file in Jupyter or Cursor from the checkout. It selects real MEI,
Humdrum, MusicXML, and MIDI URLs from the `test_corpus` manifests; it is not
executed as part of this docs build.

## Conversion routes

Verovio always writes the MEI that CAMAT parses. The steps before that depend
on the source format:

```mermaid
%%{init: {"flowchart": {"htmlLabels": true, "nodeSpacing": 28, "rankSpacing": 48}, "themeVariables": {"fontSize": "18px"}}}%%
flowchart TB
    A[Verovio-supported format] --> V[Verovio]
    B[Other music21-readable format] --> M21[music21]
    M21 --> X[MusicXML]
    C[MuseScore format] --> MS[MuseScore]
    MS --> X
    X --> V
    V --> MEI[MEI]
```

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

!!! warning "Experimental MIDI route"

    MIDI → music21 → MusicXML → Verovio is an experimental import route. It is
    known to produce incorrect rhythm, chord grouping, voices, rests, ties, or
    notation in some files, even when quantization diagnostics look good. Use
    it for exploration and regression work, not unattended edition production;
    inspect every generated MEI measure before analysis or publication.

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
The converter starts from `(8, 6, 4, 3)`, then scans exact raw note-on ticks for
common finer binary/triplet grids before music21 groups notes into chords.
Straight 32nds such as the adjacent G/F ornament in BWV 846 remain sequential,
and a score containing exact 64ths automatically adds divisor `16`. It applies
voice reconstruction only to measures containing staggered overlapping notes.
`fillGaps=True` is important: it exports visible rests rather than hidden
MusicXML rests that Verovio would represent as MEI `<space>` elements.

MIDI in particular is lossy: spelling, voices, meter, and articulations are
reconstructed. The automatic grid reduces specific failures but does not make
the route notation-reliable. See [Known limitations](../known-limitations.md).

### MIDI ticks and quantization grids

For ordinary PPQ-based MIDI, music21 first accumulates delta times into
absolute ticks, then calculates:

```text
onset quarter length = onset tick / ticks per quarter
duration quarter length = (off tick - on tick) / ticks per quarter
```

It groups sufficiently close events into candidate chords before snapping
offsets and durations to the nearest configured subdivision. The finest grid
therefore affects both rhythmic precision and chord grouping.

CAMAT's default `MidiImportOptions()` infers common divisors `12`, `16`, `24`,
`32`, `48`, or `64` when exact note-on positions or adjacent onset intervals
require them. It deliberately ignores note-off ticks: score MIDI commonly
shortens those by one tick for articulation, which is not evidence of a finer
notated value. One-tick and other nonstandard onset denominators are also not
promoted automatically, avoiding an extreme grid for ordinary performance
jitter.

| Smallest straight note | Quarter length | Divisor |
| --- | ---: | ---: |
| 16th | 1/4 | 4 |
| 32nd | 1/8 | 8 |
| 64th | 1/16 | 16 |
| 128th | 1/32 | 32 |

Override automatic detection for a file or corpus with `MidiImportOptions`:

```python
from camat import MidiImportOptions, convert_sources

records = convert_sources(
    ["path/to/score.mid"],
    midi_options=MidiImportOptions(
        quarter_length_divisors=(16, 12, 11, 8, 6, 4, 3),
    ),
)
```

Divisor `11` permits multiples of 1/11 quarter length, which music21 can
encode as 11:8 time modification when the durations support that ratio. It
does not infer a global rhythmic interpretation or guaranteed tuplet grouping.
Every event independently chooses its nearest candidate, so only include grids
that are plausible for the source.

The report records the effective grid, exact onset/interval evidence used by
automatic detection, PPQ, chord-grouping tolerance, and summary statistics for
music21's offset and duration quantization errors.

### MIDI tracks, channels, voices, and staves

MIDI files encode tracks, channels, and note events; they do not encode MEI or
MusicXML-style contrapuntal voice identities. music21 normally maps MIDI tracks
to score parts/staves, then infers local voices where notes overlap. For
example, the ASAP BWV 846 Prelude and Fugue files used by CAMAT are type-1 MIDI
with two tracks, but both tracks use channel 1. Those tracks broadly provide
the two piano staves; they are not four persistent Bach voices.

By default, inferred voices remain layers on their source staff. For a
diagnostic voice-isolated view, put every inferred per-measure voice slot on a
separate staff:

```python
from camat import MidiImportOptions, convert_sources

records = convert_sources(
    ["path/to/score.mid"],
    midi_options=MidiImportOptions(voice_layout="separate_staves"),
)
```

This uses music21's local voice ordering, not identities stored in MIDI. A
staff labelled `voice slot 1` can therefore represent a different musical
voice after the texture changes. Treat this mode as a diagnostic or
voice-isolated analysis representation, not an automatic editorial voice
assignment. The normal `voice_layout="layers"` output remains the production
default.

### Raw MIDI timing and microtiming

Disabling quantization does not make the score-conversion route lossless:
music21 still groups near-simultaneous events before returning its score, and
MusicXML/MEI are notation-oriented representations. Use the separate raw timing
reader for performance analysis:

```python
from camat import read_midi_timing

timing = read_midi_timing("path/to/performance.mid")
display(timing.notes.head())
display(timing.tempo_map)
```

`timing.notes` preserves note-on/off ticks, PPQ-derived exact quarter-length
fractions, tempo-aware seconds, track, channel, pitch, and velocity. SMPTE MIDI
uses its timecode basis for seconds and leaves metric quarter lengths empty.

## MuseScore files

`.mscz` / `.mscx` are not Verovio inputs. If MuseScore Studio or the `mscore`
CLI is on `PATH` (or `MUSESCORE_BIN` points at it), export MusicXML with
MuseScore, then convert with Verovio. Without MuseScore, convert the file to
MusicXML or MEI in the editor first.

`convert_sources(...)` implements that route. Both conversion notebooks select
the real `Amazing_grace.mscz` demo from the test manifest and record a clear
failure if MuseScore is unavailable; the single-file notebook continues with
the other routes rather than aborting.

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
- Public corpora used in the notebooks: [Test sources](sources.md)
- API: [conversion](../api/conversion.md), [MIDI timing](../api/midi_timing.md),
  and [`vrv_convert_to_mei`](../api/verovio_render.md)
