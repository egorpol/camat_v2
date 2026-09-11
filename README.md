# CAMAT

<p align="center">
  <a href="https://pypi.org/project/camat/"><img alt="PyPI" src="https://img.shields.io/pypi/v/camat.svg"></a>
  <a href="https://pypi.org/project/camat/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/camat.svg"></a>
  <a href="https://camat-v2.readthedocs.io/en/stable/"><img alt="Documentation" src="https://readthedocs.org/projects/camat-v2/badge/?version=stable"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green.svg"></a>
</p>

CAMAT (Computer-Assisted Music Analysis Toolbox) is an **MEI-centred Python
toolbox** for editorial and analytical work with symbolic music. MEI is the
durable score document; conversion, note tables, statistical analysis,
pattern search, and rendering all connect back to that file.

The four workflows can be used independently. An existing MEI edition can go
straight to parsing, while a MusicXML or Humdrum source first passes through
conversion.

| Workflow                 | Starts with                                                    | Produces                                                                   |
| ------------------------ | -------------------------------------------------------------- | -------------------------------------------------------------------------- |
| **Handle MEI**     | existing or draft MEI                                          | rendered scores, facsimile links, combined pages, editorial checks         |
| **Convert to MEI** | MusicXML, Humdrum, MuseScore, MIDI, and other symbolic formats | MEI suitable for inspection and parsing                                    |
| **Parse MEI**      | common-notation MEI                                            | note tables (`df_pitch`), event tables (`df_events`), piano-roll views |
| **Analyse**        | those tables or derived matrices                               | distributions, binary matrices, pattern matches, and score overlays        |

Tables and matrices are working representations. They do not replace the
edition; `xml:id` values are the bridge back to the score. Common-notation
MEI is the supported path; mensural and timeline backends are experimental.

Guides, notebooks, and the API live in the
[documentation](https://camat-v2.readthedocs.io/en/stable/).

## Install

Requires Python 3.11 or later.

```bash
python -m pip install camat
```

To run the showcase notebooks without cloning the whole repository:

```bash
camat-fetch-tutorials
```

That command copies `notebooks/` and `test_corpus/` into `camat_tutorials/`.
See [Cloud notebooks](https://camat-v2.readthedocs.io/en/stable/cloud-notebooks/)
for Jupyter4NFDI and Google Colab.

To work on CAMAT itself:

```bash
git clone https://github.com/egorpol/camat_v2.git
cd camat_v2
python -m pip install -e ".[notebooks]"
```

## Quick start

This example uses a tiny score shipped with CAMAT. After installation it runs
offline, without a corpus download or Jupyter.

```python
from importlib.resources import as_file, files
from camat import parse_files_quiet

example = files("camat").joinpath("examples", "facsimile_viewer_demo.mei")
with as_file(example) as score:
    results, _, _ = parse_files_quiet(
        [str(score)],
        backend="none",
        display_preview_df_pitch=False,
        display_preview_df_events=False,
        show_progress=False,
    )

notes = results[0]["df_pitch"]
print(f"Parsed {len(notes)} notes")
```

Expected output:

```text
Parsed 8 notes
```

`df_pitch` holds note rows; `df_events` holds non-note events. Verovio is the
default parser for common-notation MEI. Convert other formats first, then
parse the resulting MEI.

Command-line tools such as `camat-convert`, `camat-check-mei`, and
`camat-fetch-tutorials` are installed with the package.

## What's in this repository

The PyPI wheel is the `camat` package: library code, a few packaged example
scores, and the MEI 5.1 Common Music Notation schema. This git checkout also
holds tutorials, documentation sources, tests, and working corpora that are
not shipped on PyPI.

```text
camat_v2/
├── camat/            Installable package (conversion, parsers, analysis, rendering)
│   ├── examples/     Tiny MEI/SVG scores for offline demos
│   └── schemas/      MEI 5.1 CMN RELAX NG schema
├── notebooks/        Showcase tutorials, ordered in the documentation roadmap
├── docs/             MkDocs sources published on Read the Docs
├── tests/            Pytest suite and synthetic fixtures
├── scripts/          Release checks, docs hooks, and maintainer probes
├── test_corpus/      Local MEI fixtures and corpus URL manifests
├── CAMAT_old/        Development archive (not a supported API)
└── exports/          Retained generated artifacts
```

## Documentation

| Page                                                                             | What it covers                                                       |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| [Documentation home](https://camat-v2.readthedocs.io/en/stable/)                  | Workflow map and starting points                                     |
| [Getting started](https://camat-v2.readthedocs.io/en/stable/getting-started/)     | Install, offline example, and Jupyter setup                      |
| [Cloud notebooks](https://camat-v2.readthedocs.io/en/stable/cloud-notebooks/)     | Jupyter4NFDI and Colab: copy tutorials without a full clone      |
| [What CAMAT is](https://camat-v2.readthedocs.io/en/stable/overview/)              | How the four workflows fit together                                  |
| [Notebook roadmap](https://camat-v2.readthedocs.io/en/stable/notebooks/)          | Executable examples in recommended order                             |
| [API reference](https://camat-v2.readthedocs.io/en/stable/reference/)             | Python modules and entry points                                      |
| [Known limitations](https://camat-v2.readthedocs.io/en/stable/known-limitations/) | Supported notation and experimental features                         |

For bugs and suggestions, use [GitHub Issues](https://github.com/egorpol/camat_v2/issues).
See [Contributing](CONTRIBUTING.md) to work on the project.

## Authors and origins

Egor Polyakov — research and development; Martin Pfleiderer — supervision.
Pia Steuck — student assistant.

The acronym was chosen in 2021–2022 for a basic MusicXML parsing tool;
see the [earlier project and tutorials](https://analyse.hfm-weimar.de/doku.php?id=en:noten).
The current MEI-centred toolbox is a new implementation with a broader scope.

## Funding, citation, and license

Funded by the German Research Foundation (DFG), programme Library and
Information Services — E-Research Technologies (LIS), grant PF 669/18-1.

If you use CAMAT in research, cite the software and state the version.
[CITATION.cff](CITATION.cff) supplies the metadata; GitHub exposes it through
**Cite this repository**.

CAMAT's code is [MIT licensed](LICENSE).
Bundled material has [separate notices](THIRD_PARTY_NOTICES.md).
