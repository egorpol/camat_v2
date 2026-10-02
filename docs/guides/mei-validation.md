# General MEI validation and corpus publication checks

Use CAMAT's `run_mei_validation` or `camat-validate-mei` for read-only general
checks. A corpus adds its own work list and publication policy. The legacy
`camat-check-mei` and `run_editorial_checks` remain available, but an empty legacy
CSV does not establish that all conformance passes ran.

The validation API described here requires CAMAT 0.2.5 or newer. The repository's
MkDocs pages are the documentation source to maintain during the migration from
the earlier HfM Weimar wiki.

<a id="development-installation"></a>

## Installation

Install the validation extra in the Python environment that runs your corpus
command or notebook:

```sh
python -m pip install 'camat[validation]>=0.2.5'
```

`xmllint` must be available on PATH for RELAX NG. The extra adds lxml, SaxonC
and Pillow; the fixed SchXslt 1.10.1 XSLT compiler is bundled. No validator is
installed or downloaded during a validation run.

### Development checkout

```sh
python -m pip install -e '.[validation]'
```

Source changes in an editable checkout apply to the next Python invocation.
Restart a notebook kernel after changes. Record both the package version and
the actual installation commit/path; a branch name or commit title does not
identify the code imported by a running kernel. Historical pre-release identities
remain in the [dated validation assessment](../development/mei-validation-split.md).

## Run the general checks

```sh
camat-validate-mei test_corpus/validation_baseline/minimal-cmn-51.mei \
  --output-dir converted_mei/validation/minimal
```

```python
from pathlib import Path
from camat import MEI_CMN_51_SCHEMA, run_mei_validation

result = run_mei_validation(
    [Path("score.mei")], root=Path.cwd(), output_dir=Path("validation-output"),
    schema=MEI_CMN_51_SCHEMA, profile="MEI-5.1-CMN",
    document_mode="standalone", check_verovio=True, check_camat_parse=True,
)
print(result.record["conformance"])
```

The profile name describes the configured schema; it does not select an edition.
The default schema remains the unchanged official CMN 5.1 schema. An explicitly
supplied schema selects both RELAX NG and its embedded Schematron rules. A
self-contained `.sch` can also be passed to `run_schematron_validation` separately.
External Schematron include graphs are currently rejected so unrecorded dependent
rule files cannot be mistaken for a reproducible cached validator.

### What the checks tell you

Three layers answer different schema questions:

1. **XML/references:** can the document be read, does it have an MEI root and
   unique IDs, and do supported local pointers resolve in the selected context?
   For example, `startid="#missing"` is a broken reference even when its spelling
   is allowed by the schema.
2. **RELAX NG:** are the elements, attributes, values and nesting allowed by
   the selected MEI customization? `xmllint` checks this structure against the
   configured `.rng`. A file's `xml-model` processing instructions describe its
   intended validators; they do not execute those validators in CAMAT.
3. **Schematron:** do relationships expressed as assertions hold? The selected
   RNG also contains these rules, which CAMAT extracts and executes with
   SchXslt/SaxonC. A `<harm>` with no starting anchor is a regression example
   that passes RELAX NG and fails an embedded Schematron assertion. Structural
   validity alone therefore does not establish full conformance.

CMN means **Common Music Notation**, the configured MEI 5.1 customization.
It does not mean a DdT edition or a Buxtehude-specific schema. A broader
`mei-all` declaration in an input is not rewritten; CAMAT tests against the
schema explicitly selected for this run. Exact corpus declaration requirements
belong to the corpus policy. Changing the `profile` label alone changes no rules.

The remaining required passes check **resources** when supplied (local image
decoding and declared geometry) and **input hashes** before/after execution.
A score without facsimiles passes offline resource checks because there are
no supplied image resources to invalidate. An enabled HTTP check instead
reports `not-applicable` when it has no HTTP targets to test.

**Musical diagnostics** are review aids: missing/inconsistent meter or staff/layer
structure, missing or over/underfull written durations, basic pitch fields and
optional written-duration/PPQ comparison. They run alongside the general checks;
`check_ppq=False` disables the PPQ comparison, while `editorial_diagnostics`
and `group_diagnostics` opt into naming/numbering/term conventions and comparisons
between deliberately related inputs. A warning about an underfull layer is not
by itself proof of invalid MEI. See [the scope limits](../known-limitations.md#general-mei-validation-scope)
before interpreting editorial alternatives or unusual timing.

**Consumer checks** optionally ask whether Verovio can load/render the score and
CAMAT can produce event tables. **Image-network checks** optionally test HTTP
image reachability/content type. These can expose practical problems despite
schema conformance. **Publication acceptance** requires the corpus's explicit
metadata, source, editorial and review rules in addition to shared results.

### Read the printout and reports

Reports comprise `run.json`, `findings.json`, `findings.csv` and `schematron/` with
extracted rules, cached compiled validators and per-file SVRL. Namespace bindings
used only inside XPath expressions survive extraction. The cache identity
includes the original schema bytes, compiler files, processor identity and
extraction version. Generated stable assertion IDs supplement assertions without
IDs; the original RNG is never modified. The SVRL retains assertion test,
location, message and declared severity, with line/ID/context in findings.

The checking notebooks also retain convenient score-named CSV exports. These
are exact copies of `findings.csv`, including `origin`; optional score-named JSON
is copied from `findings.json`. They do not represent different checks or need
separate review. Older notebook exports used a reduced column list, so their
layout differed despite containing the same finding rows. The printed checks
table has one row per pass: `requested` means enabled, `required` means needed
by the configured acceptance gate, `status` describes execution, and `findings`
counts the individual rows emitted by that pass. A dash means the count was
not available, such as for a skipped or interrupted pass; it is not zero.
The printed finding summary groups the full finding rows by
severity/category/check, so its number of displayed groups can differ from
the number of executed checks and individual CSV rows. `run.json` holds execution/provenance details,
while CSV/JSON findings hold issues to review. An assembly page report concerns
the earlier prepared-page checks, rather than the combined score's validation.

The required general passes are XML/references, RELAX NG, Schematron, offline
resources and unchanged input hashes. Each execution status means:

- `passed`: the pass completed without findings that fail its policy; informational
  or advisory rows can still be present.
- `failed`: the pass completed and found a problem that fails its policy.
  Verovio/network checks treat warnings as failures of that particular pass.
- `skipped`: the option was disabled.
- `not-applicable`: the enabled check had nothing applicable to test; a reason
  and target/request counts explain this for image networking.
- `execution-error`: the check could not finish, for example because its validator
  is absent. While a pass is still running, consult `running`, `active_check` and
  `completion_status`; the checkpoint is not a completed result.

A required skipped, inapplicable or unavailable pass makes its summary
`incomplete`; completed failures make it `failed`. A schema's advisory
`role="warning"` is retained as a finding and does not become a conformance
error. A corpus may separately reject warnings for publication. Empty input
selection never passes. `required_checks_status` additionally accounts for any
consumer or network passes required by the caller; `result.passed` requires both
summaries to pass. `conformance` always uses the five general passes, even if
the caller changes `required_checks`. `consumer_diagnostics` summarizes Verovio
and CAMAT parsing; a disabled consumer leaves that summary incomplete rather
than claiming it passed. The CLI returns zero when `result.passed` is true,
so optional consumer/network failures alone do not change its exit code.
A corpus wrapper applies its own release gate.

Findings expose severity, category, origin, check ID, file and message, plus
line/element/ID/measure/staff/layer, expected/actual and context when available.
Blank location fields mean that information was not supplied by the check.
Preserve `origin` to distinguish CAMAT evidence from schema/consumer diagnostics.
Reusing the notebook's `TARGET_DIR/validation` replaces the current run reports;
older score-named copies can remain, so archive the complete run folder or choose
a fresh target directory when keeping validation evidence.

Musical checks and consumer results remain separate. Hummel retains rhythm/PPQ
diagnostics, while Hummel and Webern trigger Verovio warnings despite passing
CMN conformance. CAMAT parsing probes the chosen backend and records table-row
counts, not an asserted one-to-one correspondence with XML notes. Full Verovio
rendering is the default when requested; the notebook can explicitly choose
load-only and the record identifies that choice. Consumer parsing disables plots,
table previews and progress displays, so validation cannot wait for a notebook
piano-roll window to close.

For a plain-language explanation of each pass, its limits, and reading the
results, use [the consistency notebook](../../notebooks/mei_consistency_checks.ipynb).
It explains XML readability, RELAX NG structure, embedded Schematron relationships,
and why schema conformance and consumer warnings can differ.

### Why `saxonche` is a validation dependency

The `validation` extra already requires `saxonche>=12,<14`. CAMAT's Schematron
pass uses it to compile/run the bundled SchXslt XSLT and execute the extracted
rules with the needed XPath/XSLT capabilities. `xmllint` runs RELAX NG, not these
embedded rules. The free SaxonC-HE edition is sufficient for this pass; CAMAT
does not use Saxon's commercial XSD validation features. See the
[SaxonC package](https://pypi.org/project/saxonche/) and
[Saxonica's feature documentation](https://www.saxonica.com/html/products/feature-matrix-13.html).

Keep this dependency required in a validation environment and optional for the
rest of CAMAT. `camat[validation]` installs it; an ordinary `camat` installation
does not promise complete MEI validation. The processor is imported only when
Schematron runs. An absent processor yields `execution-error` and blocks a
complete conformance pass; disabling that required pass yields `incomplete`.
Adding it to core `requirements.txt` would make sense only if every ordinary
CAMAT installation were intended to provide full validation.

## References and facsimiles

Supported pointer attributes share one registry, including `resp`, `source`,
`decls`, event endpoints and URI lists. Inherited `xml:base`, escaped paths and
explicit local document fragments are resolved. Standalone bare fragments must
resolve locally; `assembly` can report a unique target in another selected page.
Ambiguous assembly targets fail. Explicit local documents are read when supplied;
remote references are listed in the record without an implicit fetch. This is
local/bundle integrity, not verification of every external authority URL.

Image checks accept local raster/SVG files, direct HTTP image URLs and multiple
graphics/resolutions. Local files are checked for existence and decoding. Zone
rectangles are compared with an explicitly declared surface coordinate space;
no coordinate-to-pixel mapping is guessed from the first graphic. Missing
facsimiles and nonnumeric surface labels are valid general cases. Explicit
`--network` checks HTTP reachability/content type, with failures in a separate
connectivity result. It does not prove image rights or musical accuracy.

When requested without any HTTP(S) image targets, `image_network` is
`not-applicable`, rather than a connectivity pass or an invalid-MEI finding.
The record explains whether no images are linked, only local files are linked,
or the linked URI schemes are outside the HTTP check. It records linked images,
HTTP targets, attempted requests and per-file counts; mixed batches test the
HTTP targets that are present. A disabled option remains `skipped`.
The network pass performs only connectivity/content-type checks; local decoding
and geometry findings belong to `resources`. General conformance does not
require images or networking. A caller explicitly requiring `image_network`
cannot satisfy that requirement with zero applicable targets.

Copy preparation and combination are explicit transformations. Known relative
resource pointers are rebased when copies move; explicit selected-page fragments
are rewritten when combined so deleting temporary pages does not break them.
Within-document duplicate IDs are rejected before ambiguous rewriting.

## DdT and version updates

The DdT corpus provides `scripts/validate_corpus.py`, `validation/profile.json`
and `validation/works.json`. It imports the installed CAMAT API, then adds its
source identities, licenses, annotation/event requirements, primary-page mapping
and review/release gates. The initial work list includes only the pilot; neither
BuxWV nor its staff arrangement becomes a general CAMAT condition.

The pilot's official Schematron warnings about external IIIF canvas URLs in
`surface/@corresp` remain pending publication review. Their general advisory
severity is preserved; no publication waiver has been introduced.

There is no permanent CAMAT pin during active development. Shared run records
contain module and distribution versions, actual module path, editable/VCS
installation metadata when present, branch/commit/status for a local checkout,
source hashes, tools, the descriptive profile, schema hash and selected-input
hashes. The corpus wrapper additionally records its policy-profile and work-list
hashes. A dirty commit needs saved working bytes to reproduce: hashes verify
bytes but do not restore them. Keep locally referenced documents and resources
alongside the inputs; selected-input hashes alone do not preserve those files.

An explicit Git install from `main` obtains merged code without requiring a PyPI
release. It is a snapshot, not continuous updating. Pip may retain an installed
package when version metadata stays unchanged; a deliberately forced reinstall
(or fresh environment) avoids assuming that `--upgrade` fetched new branch code.
Check the recorded installation commit after every update. A PyPI install needs
an actual published release that provides the required API version. Running
checks does not update or publish CAMAT. See [pip's editable installation documentation](https://pip.pypa.io/en/stable/topics/local-project-installs/)
and [VCS installation documentation](https://pip.pypa.io/en/stable/topics/vcs-support/).

Run records start as incomplete and are atomically checkpointed before and after
each pass. `completion_status`, `active_check` and the execution's `running` flag
identify a check that has not returned; its incomplete execution must not be
read as a completed failure or pass. An interrupted replacement run cannot leave
the prior completed result visible as the new attempt. Native passes do not yet
have automatic hard timeouts. Stop a stalled command and rerun into a fresh
output directory, keeping the incomplete record for diagnosis.
