# Offline parser robustness set

This small set is used by the installed-wheel smoke tests on Python 3.11–3.14
and by the standalone Verovio robustness runner. It currently selects:

- `Bach-JS_Ein_feste_Burg.mei`: the MEI 5.0 chorale used by the binary notebooks,
  with 236 notes, four voices and 14 music measures, including its pickup.
- `../validation_baseline/Hummel_Preludes_Op67_No11.mei`: the existing MEI 5.1
  keyboard example, with 202 source notes, including 25 grace notes, and seven
  music measures. The configured parser excludes the zero-duration grace notes,
  leaving 177 pitch rows.
- `../../tests/fixtures/basic.mei`: the existing CAMAT-authored synthetic score,
  with five notes and two measures.

The Bach file was copied byte-for-byte from the same upstream revision already
used for Hummel: `f3f1baba02e32279b25dad660b82c834bac034b4`. Its MEI header and
rights statements remain intact. The upstream project's license is retained in
[LICENSE.sample-encodings](../validation_baseline/LICENSE.sample-encodings).
[manifest.json](manifest.json) records the exact source URLs, revisions, sizes,
SHA-256 checksums and expected parser counts for all three inputs. Paths in the
manifest and [sources.txt](sources.txt) are relative to the repository root.

Run the set offline from the repository root:

```bash
python scripts/test_verovio_parser_robustness.py \
  --source test_corpus/parser_robustness/sources.txt \
  --json .release-runs/parser-robustness.json
```

Each score runs in its own subprocess. The runner reports selected, tested,
passed and failed counts. Empty selections and missing source lists fail with
exit code 2 and replace the previous JSON report with an empty list; parsing
failures, crashes, timeouts and incomplete batches fail with exit code 1.
Success requires a nonempty batch and a passing result for every selected score.
Source note counts retain grace notes, while expected pitch counts account for
the configured filtering, including grace chords.

The installed-wheel tests check the recorded input hashes, expected pitch and
measure counts, positive finite durations and input byte preservation. They use
these checked-in inputs directly without a network fetch or notebook cache.
This is an initial regression set that can be refined in later releases.

These test inputs are excluded from the wheel and source distribution. The
binary notebooks retain their own source selection controls.
