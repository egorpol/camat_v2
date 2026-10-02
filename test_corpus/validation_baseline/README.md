# Frozen MEI validation baseline

This is a small input set for separating general CAMAT checks from edition
acceptance. It does not replace the broader URL manifests or act as a corpus
release manifest. Inputs, provenance and SHA-256 values are in
[manifest.json](manifest.json).

The selected inputs are:

- `minimal-cmn-51.mei`: a CAMAT-authored two-measure score with no facsimiles,
  useful for exact pointer and hash-preservation tests. Derived from the existing
  MEI 5.0 smoke fixture with an explicitly valid CMN 5.1 header; the original
  fixture is unchanged.
- `Hummel_Preludes_Op67_No11.mei`: the complete prelude encoding in MEI's sample
  collection. Its music has seven measures, plus a separate metadata incipit;
  useful for ordinary keyboard MEI, no facsimiles, meter changes and tuplets.
- `Webern_Variations_for_Piano_Op27_No2.mei`: the collection's second-movement
  encoding, with twelve music measures plus metadata incipit content. This is a
  compact different-composer case with rests, accidentals, articulation, repeats
  and no facsimiles. Test the supplied encoding; do not infer corpus completeness
  or editorial accuracy from its presence here.
- `local/buxtehude_op1_01_sonata_f_major_corr.mei`: an unchanged working-tree
  snapshot of the corrected DdT pilot, with 183 music measures and ten surfaces.
  This local integration input is ignored by Git and is optional in portable
  tests. Its source revision and exact working checksum are recorded. It is
  distinct from the OMR page files used for assembly examples.

Hummel and Webern were copied byte-for-byte from links already in
`mei_test_copora_links.txt`, pinned to upstream commit
`f3f1baba02e32279b25dad660b82c834bac034b4`. Preserve their original MEI headers;
record future changes separately. The upstream repository is ECL-2.0 licensed;
its license is retained in [LICENSE.sample-encodings](LICENSE.sample-encodings),
and the encodings' own rights statements remain intact. Source:
[MEI Sample Encodings](https://github.com/music-encoding/sample-encodings).
These fixtures, like the rest of `test_corpus`, are excluded from CAMAT's wheel
and source distribution.

The upstream scores declare MEI 5.1 `mei-all.rng`; their content also passes the
explicitly selected packaged CMN 5.1 RELAX NG schema. The declarations were not
rewritten to pretend that they originally selected CMN. Exact DdT CMN declaration
requirements belong to the local publication profile.

The smaller Aguado waltz, J. C. Bach Fughette No. 2 and Schumann Landmann were
also inspected. Although their content passed CMN RELAX NG, they contain
unresolved local header references. Retain their existing links for regression
coverage; do not treat them as clean reference-integrity passes or suppress their
errors to simplify the baseline. Beethoven's Hymn to Joy is a larger candidate
for later orchestral/choral coverage.

[before.json](before.json) records the pre-refactor base checker and explicit
CMN RELAX NG results. The ignored `local/pre-refactor/` directory preserves
the original checker, workflow, notebook and consistency-test bytes, including
the notebook's working configuration. [after.json](after.json) records the first
boundary refactor and optional Verovio checks. An `incomplete` overall status is
intentional for that historical stage: Schematron execution and CAMAT consumer
probing had not yet landed. Those passes are now implemented and recorded in
the later execution snapshot below. Musical warnings are diagnostic evidence,
not automatically invalid MEI.

The external examples also exercise consumer limitations: the recorded Verovio
run reported 26 findings for Hummel and 29 for Webern, while the synthetic score
and pilot had none. These are unchanged upstream samples, not warning-free
rendering gold standards. Inspect the recorded messages and the later
Schematron results before deciding which cases qualify as full conformance passes.

Run the focused checks offline from the repository root:

```sh
python -m pip install -e '.[test,validation]'
python -m pytest tests/test_mei_validation_boundary.py tests/test_mei_consistency.py tests/test_mei_validation_execution.py tests/test_edition_pipeline.py -q
```

Use an environment with CAMAT's validation dependencies and pytest installed. The RELAX NG
integration test requires `xmllint`; it reports a test skip if the executable is
absent. Such a skip is not a release-validation pass.


The later execution snapshot is [execution-2026-10-01.json](execution-2026-10-01.json).
It records real Schematron, resources, Verovio and CAMAT parser results. The three
portable scores pass general conformance. The pilot retains ten schema warnings
for external IIIF canvas `corresp` values; these remain advisory in general
conformance and require a publication disposition in the corpus profile.
Run the execution regressions with `tests/test_mei_validation_execution.py` in
addition to the earlier boundary tests. Install the `validation` extra for the
real SaxonC tests; skipped optional test dependencies are not validation evidence.
This snapshot belongs to its recorded implementation and input hashes. Later
edits require a new execution record; keep the existing dated evidence intact.
