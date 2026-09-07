# Third-party notices

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

The source and reuse terms for the retained Buxtehude fixtures in
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
