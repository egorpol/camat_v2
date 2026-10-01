---
title: MEI consistency and cleanup
---

# MEI consistency and cleanup

The checker and report helpers are read-only. Functions that can change an MEI
file expose an explicit `apply` argument or are named as cleanup/copy
operations. `run_relaxng_validation(...)` uses the packaged schema and requires
the `xmllint` executable. The Workflow 1 guide explains how these layers fit
together.

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
Full URI/base-URI and schema-aware target resolution are planned extensions;
this first boundary change handles local fragments.

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
remains the default. The notebook now selects general mode and shows its schema
and options, and rejects stripping flags in check-only mode.

There is not yet a complete conformance/release result: actual Schematron
execution, complete run-status records and CAMAT consumer probing are the next
stage. A clean CSV or skipped integration test does not prove those checks ran.
See the [baseline](../../test_corpus/validation_baseline/README.md) and
[implementation plan](../development/mei-validation-split.md).

Check results are meant to be reviewed from **CSV/JSON reports** produced by
`run_checker(...)` and `run_editorial_checks(...)`. CAMAT also integrates
`annotate_mei_from_report(...)` to write selected rows into MEI `<annot>`
elements, but mei-friend's per-score annotation display limit (default 100)
makes CSV the practical hand-off for large reports; see
[Editing music with the MEI data format — Check, combine, and review reports](../guides/edition-building.md#annot-export-integrated-csv-preferred).

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
