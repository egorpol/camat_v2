---
title: MEI consistency and cleanup
---

# MEI consistency and cleanup

The checker and report helpers are read-only. Functions that can change an MEI
file expose an explicit `apply` argument or are named as cleanup/copy
operations. `run_relaxng_validation(...)` uses the packaged schema and requires
the `xmllint` executable. New integrations should use `run_mei_validation(...)`
for separate pass statuses, actual Schematron execution and input/provenance
records; see the [validation guide](../guides/mei-validation.md).

## General mode and edition conventions

`check_mei_files(...)` and `run_checker(...)` default to independent standalone
files. General mode does not require facsimiles, complete measure-zone coverage,
numbering or instrument-label conventions, or majority instrumentation in a
batch. It checks local `resp` and `source` fragments using the same supported
pointer registry as ID-copy preparation. Musical duration/pitch diagnostics
remain distinct from schema validity. Score traversal excludes header incipits.

Set `document_mode="assembly"` for a selected page set whose fragments may
resolve across pages; ambiguous targets are errors. A bare `#id` in standalone
mode must resolve in its own file, even if another selected document has that ID.
Explicit local document fragments, escaped paths and inherited `xml:base` share
the same URI resolver. Remote references are recorded without an implicit fetch.

Set `editorial_diagnostics=True` for naming, numbering and term conventions,
and `group_diagnostics=True` for comparisons within a deliberately related
group. `publication_profile=True` retains the legacy DdT-specific rules and
enables those conventions by default. It is a compatibility mode, not a general
MEI publication profile.

`run_editorial_checks(...)` retains its legacy publication default for existing
callers. Select `publication_profile=False` for general checking. In that mode,
figured-bass conversion preferences and page-break topology checks default off;
they can be requested explicitly with `check_fb_tstamp` and `check_pb_facs`.
Use `schema=...` to choose the RELAX NG schema explicitly; packaged CMN 5.1
remains the default. Both `mei_check_report.ipynb` and
`mei_consistency_checks.ipynb` use the general `run_mei_validation(...)` API,
show their configured schema/profile and execution statuses, and apply no DdT
publication rules. The consistency notebook rejects stripping flags in
check-only mode; conversion and assembly are explicit transformations.

The general API executes RELAX NG and embedded Schematron, saves execution and
input-hash records, and supports optional CAMAT/Verovio consumer probing. Missing
or skipped required validators block a conformance pass. Publication acceptance
belongs to the corpus wrapper. A clean CSV alone does not prove checks ran.
See the [baseline](../../test_corpus/validation_baseline/README.md) and
[implementation plan](../development/mei-validation-split.md).

Check results are meant to be reviewed from **CSV/JSON reports** produced by
`run_mei_validation(...)`, or the legacy `run_checker(...)` and
`run_editorial_checks(...)`. The new API additionally writes `run.json` so
findings can be interpreted alongside the checks that actually ran. CAMAT also integrates
`annotate_mei_from_report(...)` to write selected rows into MEI `<annot>`
elements, but mei-friend's per-score annotation display limit (default 100)
makes CSV the practical hand-off for large reports; see
[Editing music with the MEI data format — Check, combine, and review reports](../guides/edition-building.md#annot-export-integrated-csv-preferred).

## Execution-record validation API

`run_mei_validation` selects no corpus policy. `schema` supplies the actual
RELAX NG and embedded Schematron rules; `profile` is a descriptive label. Five
checks always define `conformance`: `xml_references`, `relaxng`, `schematron`,
`resources` and `input_hashes`. `required_checks` additionally defines the
caller's acceptance gate, exposed as `required_checks_status`.
`ValidationResult.passed` requires both summaries to pass. Consumer warnings
remain separate unless those consumers are explicitly required by the caller.

Results expose `findings` and `record` and are saved under `output_dir`.
The CLI returns zero only when `ValidationResult.passed` is true; optional
consumer/network findings alone do not change that exit status. Corpus wrappers
must apply their publication gate separately. Existing legacy entry points
retain their return types and publication defaults.

::: camat.mei_validation
    options:
      members:
        - DEFAULT_REQUIRED
        - ValidationResult
        - run_mei_validation
        - camat_provenance

### Schematron execution

`run_schematron_validation` accepts the configured RNG with embedded rules,
or a self-contained `.sch`. It saves extracted rules, compiled XSLT and per-file
SVRL and retains declared warning severity. Its dictionary contains `rows`,
rule/assertion counts, processor/compiler/cache identities and SVRL paths.
It raises for missing processors, empty extraction and unsupported external
includes; the orchestration API records these as execution errors.

::: camat.mei_schematron
    options:
      members:
        - extract_schematron
        - run_schematron_validation

### Image resources

`image_resource_rows` returns a dictionary of finding `rows`, resource records
and image/request counts. Its default is offline raster/SVG and declared
coordinate checking. Set `check_network=True, network_only=True` for a separate
HTTP HEAD pass, which can return `applicable=False` with a reason when no HTTP
targets exist. `iiif_graphic_target_rows` remains a compatibility name/rule ID
for generalized local/direct-HTTP checks.

::: camat.mei_resources
    options:
      members:
        - image_resource_rows

## Consistency checker

::: camat.check_mei_consistency
    options:
      members:
        - Finding
        - MeiChecker
        - check_mei_files
        - strip_ppq_text
        - strip_accid_ges_text
        - main

## Workflow and report helpers

::: camat.mei_consistency_workflow
    options:
      members:
        - MEI_CMN_51_SCHEMA
        - CleanupResult
        - SchemaValidationResult
        - VerovioLogResult
        - resolve_mei_inputs
        - prepare_pages_for_combine
        - combine_meis
        - apply_safe_cleanup
        - normalize_single_layer_number_copies
        - run_checker
        - run_editorial_checks
        - facsimile_graphic_targets
        - iiif_graphic_target_rows
        - figured_bass_report_rows
        - page_break_facs_report_rows
        - run_relaxng_validation
        - run_verovio_warning_check
        - annotate_mei_from_report
        - load_report
        - report_summary
        - source_snippet

## Figured-bass anchors

::: camat.convert_harm_startid_to_tstamp
    options:
      members:
        - HarmConversion
        - ConversionResult
        - convert_file
        - normalize_figured_bass_accidentals
        - main

## Page-break facsimile links

::: camat.link_pb_to_surface
    options:
      members:
        - PbSurfaceRow
        - PbSurfaceResult
        - analyze_file
        - link_file
        - main
