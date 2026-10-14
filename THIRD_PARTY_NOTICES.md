# Third-party notices

## SchXslt 1.10.1

CAMAT bundles the unmodified SchXslt XSLT 2.0 compiler under
`camat/schemas/schxslt`, copyright 2018–2021 David Maus, under the MIT license.
See `LICENSES/SchXslt-MIT.txt` and the bundled README for the fixed release
URL and archive checksum. SaxonC is an optional, separately installed processor.

CAMAT's own code is licensed under the [MIT license](LICENSE). The following
material retains its own terms.

## MEI 5.1 Common Music Notation schema

- Bundled file: `camat/schemas/mei-CMN-5.1.rng`.
- Upstream project: [Music Encoding Initiative](https://github.com/music-encoding/music-encoding).
- Source description: generated from MEI ODD source; the schema header records
  a generation date of 2025-01-22 and identifies ECL-2.0 as its license.
- License: [Educational Community License 2.0](LICENSES/ECL-2.0.txt), copied
  from the [upstream license](https://github.com/music-encoding/music-encoding/blob/develop/LICENSE).

The schema's existing header is preserved. Both this notice and the complete
ECL-2.0 text are included in CAMAT's wheel and source distribution. The package
license expression is `MIT AND ECL-2.0` to describe these combined contents;
CAMAT's own code remains MIT licensed.

## Score fixtures and generated exports

### DdT_1_vol_11 Buxtehude Suite fixture

- Fixture: [`test_corpus/Buxtehude-DdT11-app01-suite.mei`](test_corpus/Buxtehude-DdT11-app01-suite.mei)
- Upstream: [egorpol/DdT_1_vol_11](https://github.com/egorpol/DdT_1_vol_11),
  file `11_buxtehude_sonatas_final/buxtehude_app_01_suite_to_op1_04_corr.mei`
  at commit `63bdb24379c8c8def62696b6be862868ebc9e5bb`
- Modification: CAMAT's `scripts/strip_facsimile.py` removed the IIIF
  `<facsimile>` block and the `@facs` tokens that pointed into it; every
  other byte is unchanged
- License: MIT, Copyright (c) 2026 contributors to DdT_1_vol_11; verbatim
  text in [`LICENSES/DdT_1_vol_11-MIT.txt`](LICENSES/DdT_1_vol_11-MIT.txt)
- Distribution: excluded from the wheel and source distribution with the
  rest of `test_corpus/`

### Other local fixtures

The source and reuse terms for the remaining Buxtehude fixtures in
[`test_corpus/`](test_corpus/README.md) and the timeline exports in
[`exports/timeline/`](exports/timeline/README.md) have not yet been
recorded. They are excluded from the wheel and source distribution. Their
provenance must be resolved before a public repository release.

These files are not covered by a blanket grant of CAMAT's MIT license.
Generated MEI retains the rights associated with its source material.

## Remote corpora and notebook outputs

[Test sources](docs/guides/sources.md) identifies the external encoding
projects referenced by the URL manifests. A source URL or downloadable score
does not by itself establish reuse terms: consult the originating project.
Saved notebook outputs may also contain rendered or derived source material;
their source terms still apply. Historical outputs are retained in
[`CAMAT_old/`](CAMAT_old/README.md).
