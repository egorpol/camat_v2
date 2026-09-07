---
title: Test sources
---

# Test sources

These public corpora feed **workflow 2** (conversion) and parser tests.
Remote entries are **raw file URLs**, not GitHub HTML pages. Local `.txt`
manifests ignore blank lines and lines that start with `#`.

Companion lists live in [`test_corpus/`](../../test_corpus).
That directory holds URL manifests and local Buxtehude MEI fixtures, including
page files used by the editorial notebooks. See its
[fixture and provenance notes](../../test_corpus/README.md).
Pass a list file to `scripts/test_verovio_parser_robustness.py` or
`camat-convert` with `--source`.

## How the lists are organized

| File | Role |
| --- | --- |
| [`test_corpus/mei_test_copora_links.txt`](../../test_corpus/mei_test_copora_links.txt) | Main MEI robustness corpus. Complete works and complete movements from public encoding projects (**1739** raw URLs). |
| [`test_corpus/verovio_partitura_parity_sources.txt`](../../test_corpus/verovio_partitura_parity_sources.txt) | Small, diverse set for Verovio / Partitura parser parity. One source per encoding family, not another movement from an already-covered corpus. |
| [`test_corpus/non_mei_test_copora_links.txt`](../../test_corpus/non_mei_test_copora_links.txt) | Conversion probe for non-MEI formats: Humdrum, MusicXML, MuseScore, and MIDI (**56** raw URLs). |
| [`notebooks/data/batch_sources.txt`](../../notebooks/data/batch_sources.txt) | Small URL-only source-list example copied from the canonical non-MEI manifest. |

The MEI list prefers complete works. Incipits, single-voice extracts, measure-position stubs, expanded/OMR duplicates, and demo files are omitted even when the same repo contains them.

## MEI encoding projects

Counts are the number of raw URLs currently in `mei_test_copora_links.txt`.

| Project | Repository | Files | What it is |
| --- | --- | --- | --- |
| Freischütz Digital | [Freischuetz-Digital/data-music](https://github.com/Freischuetz-Digital/data-music) | 32 | Weber's *Der Freischütz* in MEI 2013 stored as `.xml`. Core edition movements 0–16 plus source witnesses. |
| MEI Sample Encodings | [music-encoding/sample-encodings](https://github.com/music-encoding/sample-encodings) | 91 | Official MEI reference scores. Full MEI 5.1 complete-example set, a few older-schema complete examples, and a handful of feature snippets. |
| SEILS | [SEILSdataset/SEILSdataset](https://github.com/SEILSdataset/SEILSdataset) | 95 | Thirty madrigals from *Il Lauro Secco* (1582): choral diplomatic MEI, Marenzio particellas, and paired modern-notation / annotated files. |
| Marenzio Online Digital Edition | [marenzio/marenzio.github.io](https://github.com/marenzio/marenzio.github.io) | 66 | Luca Marenzio madrigal books I a 4, I a 5, IV a 6, and VI a 5. |
| Beethovens Werkstatt | [BeethovensWerkstatt/data](https://github.com/BeethovensWerkstatt/data) | 21 | Genetic/source-critical encodings: module-2 arrangements, further works as MEI 4.0 `.xml`, Diabelli Op. 120, and Symphony No. 9 mvt. 1. |
| CRIM | [CRIM-Project/CRIM-online](https://github.com/CRIM-Project/CRIM-online) | 318 | Citations: The Renaissance Imitation Mass. MEI 4.0 models and mass movements under `crim/static/mei/MEI_4.0/`. |
| TROMPA encodings | [trompamusic-encodings](https://github.com/trompamusic-encodings) | 57 | Complete Beethoven piano works (Henle Urtext and Breitkopf & Härtel), Clara Schumann's A-minor Romance, and Mahler Symphony No. 4 mvt. 1 in a four-hand arrangement. One GitHub repo per work. |
| Measuring Polyphony | [MeasuringPolyphony/measuring_polyphony_jekyll](https://github.com/MeasuringPolyphony/measuring_polyphony_jekyll) | 128 | Thirteenth- and fourteenth-century motets as common-notation MEI and paired mensural encodings. |
| The Beggar's Opera | [BeggarsOpera/TEI-MEI](https://github.com/BeggarsOpera/TEI-MEI) | 70 | Complete airs and overture from the digital edition (`mei/` folder). |
| iFolk | [EA-Digifolk/iFolk](https://github.com/EA-Digifolk/iFolk) | 861 | Complete Spanish, Portuguese, and Italian folk tunes in MEI. |

Example raw URLs:

```text
https://raw.githubusercontent.com/CRIM-Project/CRIM-online/master/crim/static/mei/MEI_4.0/CRIM_Model_0008.mei
https://raw.githubusercontent.com/trompamusic-encodings/Beethoven_Op31_No3_HenleUrtext/master/Beethoven_Op31_No3_3-HenleUrtext.mei
https://raw.githubusercontent.com/MeasuringPolyphony/measuring_polyphony_jekyll/master/assets/mei/adesto.mei
```

## Non-MEI conversion sources

`non_mei_test_copora_links.txt` is a smaller list used when testing conversion
into MEI. MEI already covered by `mei_test_copora_links.txt` is not repeated
here. It currently includes:

| Format | Repository | Contents |
| --- | --- | --- |
| Humdrum (`.krn`) | [craigsapp/beethoven-piano-sonatas](https://github.com/craigsapp/beethoven-piano-sonatas) | Beethoven Opp. 106, 111, 110, and 27/2. |
| Humdrum (`.krn`) | [pl-wnifc/humdrum-chopin-first-editions](https://github.com/pl-wnifc/humdrum-chopin-first-editions) | Chopin Études Opp. 10 and 25, Ballades Opp. 23 and 52. |
| Humdrum (`.krn`) | [craigsapp/bach-wtc](https://github.com/craigsapp/bach-wtc) | WTC I preludes and fugues in C-sharp minor, G-sharp minor, B-flat minor, and B minor. |
| Humdrum (`.krn`) | [craigsapp/mozart-piano-sonatas](https://github.com/craigsapp/mozart-piano-sonatas) | Mozart K. 310 and K. 457. |
| MusicXML | [piasteuck/winterreise-analysis](https://github.com/piasteuck/winterreise-analysis) | Schubert *Winterreise* songs 7, 8, 15, and 20. |
| MuseScore (`.mscz` / `.mscx`) | [musescore/MuseScore](https://github.com/musescore/MuseScore) | Official demos: Goldberg Variations, *Amazing Grace*, *Adeste Fideles*, and a string-quartet fugue. |
| MuseScore (`.mscx` / `.mscz`) | [OpenScore/Lieder](https://github.com/OpenScore/Lieder) | Complete songs: Clara Schumann Op. 13/1, Fanny Hensel *Schwanenlied*, Schubert *Winterreise* No. 8 (CC0). |
| MuseScore (`.mscx`) | [OpenScore/StringQuartets](https://github.com/OpenScore/StringQuartets) | Beethoven *Große Fuge*, Op. 133 (CC0). |
| MuseScore (`.mscz`) | [MarkGotham/Hauptstimme](https://github.com/MarkGotham/Hauptstimme) | Amy Beach, *Gaelic Symphony* Op. 32, movement 1 (OpenScore Orchestra, CC0). |
| MIDI (`.mid`) | [fosfrancesco/asap-dataset](https://github.com/fosfrancesco/asap-dataset) | Quantized score MIDI (`midi_score.mid`, CC BY-NC-SA 4.0): Bach WTC I BWV 846 and 863, Beethoven *Pathétique* Op. 13, Chopin Ballade Op. 23, Mozart Fantasie K. 475. |
| MIDI (`.mid`) | [jukedeck/nottingham-dataset](https://github.com/jukedeck/nottingham-dataset) | Complete Playford dances (GPL-3.0): *The Alderman's Hat*, *Nonesuch*, *Rufty Tufty*. |

ASAP folders also contain pianist-named performance MIDIs; the manifest uses
only the quantized score files. Mutopia's GitHub tree is LilyPond source, not
committed MIDI. Craig Sapp's Humdrum repos generate MIDI with `make midi`
rather than storing `.mid` files.

The conversion notebooks select their executable examples from these canonical
manifests: an MEI sample encoding, a Beethoven sonata in Humdrum, Schubert *Winterreise*
MusicXML, an official MuseScore demo, and ASAP score MIDI. The smaller
`notebooks/data/batch_sources.txt` repeats four of those URLs only to
demonstrate the source-list file format.

## Local fixtures

Tiny scores used by unit tests and tutorials live under `tests/fixtures/` and
in the installed package. They are not part of the public corpora.

| File | Role |
| --- | --- |
| `tests/fixtures/basic.mei` | Tiny MEI used by unit tests. |
| `tests/fixtures/basic.musicxml` | Tiny MusicXML used by unit tests. |
| `tests/fixtures/duration_semantics.mei` | Offline duration-semantics fixture for pytest. |
| `camat/examples/duration_semantics.mei` | Packaged example shipped with the wheel so notebooks run from a fresh install. |

Generated conversion output goes under `converted_mei/` (gitignored) and is not
an archival source.

## What is not in the MEI list

These projects encode music in MEI, or are often cited as MEI corpora, but they
do not currently provide a clean GitHub tree of complete-work files:

- **Measuring Polyphony**
  [`mp-music-files`](https://github.com/MeasuringPolyphony/mp-music-files):
  Sibelius and MusicXML only. The MEI used above comes from
  [`measuring_polyphony_jekyll`](https://github.com/MeasuringPolyphony/measuring_polyphony_jekyll).
- **Digital Mozart Edition / DIME**: served from
  [dme.mozarteum.at](https://dme.mozarteum.at).
- **Lost Voices / Du Chemin**: MEI is linked from
  [digitalduchemin.org](https://digitalduchemin.org), not stored as a GitHub
  corpus.
- **[WeGA](https://weber-gesamtausgabe.de)** and the
  [Weber clarinet quintet edition](https://klarinettenquintett.weber-gesamtausgabe.de):
  [Zenodo packages](https://zenodo.org/records/13759841) and a
  [Paderborn GitLab repo](https://git.uni-paderborn.de/wega/klarinettenquintett-edirom).
- **[DCM Nielsen](https://www.kb.dk/dcm/cnw.html) /
  [MerMEId](https://github.com/kb-dk/MerMEId) catalogues** and
  **[Corpus monodicum](https://corpus-monodicum.de)**: metadata or editor
  platforms rather than downloadable complete scores.
- **[Rebalancing the Music Canon](https://github.com/annakijas1/rebalancing-music-canon)**:
  hundreds of MEI **incipits**, not complete works.
- **[DDMAL mei-test-set](https://github.com/DDMAL/mei-test-set)**: complete
  examples overlap [`sample-encodings`](https://github.com/music-encoding/sample-encodings);
  the rest are notation-feature snippets.

Inside repos that *are* listed, the MEI manifest still skips mass-head files
without notes (CRIM), tiny TROMPA wrappers and `*-expanded.mei` duplicates,
Beggar's Opera `*_endings.mei`, Measuring Polyphony part extracts, and the
Marenzio `-demo` file.

## Running a list

```bash
conda run -n py311 python scripts/test_verovio_parser_robustness.py \
    --source test_corpus/mei_test_copora_links.txt
```

For conversion of mixed formats, see [Batch conversion](batch-conversion.md).
For a single URL, pass `is_url=True` to `vrv_convert_to_mei(...)` as shown in
[Convert to MEI](formats.md).
