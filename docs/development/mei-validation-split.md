# Separating CAMAT MEI validation from DdT publication checks

## Implementation status — 2026-10-01

The shared `run_mei_validation` / `camat-validate-mei` engine now executes
RELAX NG and embedded Schematron, records execution/provenance/input hashes,
resolves local URI/base contexts and checks image resources. Both checking
notebooks use general mode with an explicit schema/profile. Copy/assembly
transforms remain explicit; optional consumer probes run without interactive
plots. Image-network checks with no HTTP targets report `not-applicable`.
Score-named exports copy the canonical findings exactly.

The DdT wrapper is implemented in the corpus with a pilot work list and
review/release rules. Its official IIIF canvas warnings remain pending review.
At this 2026-10-01 checkpoint, no permanent CAMAT pin or new package release had
been made; the local editable checkout was recorded by revision and source
hashes. The branch/commit title is not the package version.

Use [General MEI validation](../guides/mei-validation.md) and the
[API reference](../api/mei_consistency.md) for current behavior, and the corpus's
`validation/README.md` for publication policy. The
[dated baseline execution](../../test_corpus/validation_baseline/execution-2026-10-01.json)
is evidence for its recorded source/input bytes, not a regenerated certificate
for later edits. Remaining limits are documented under
[Known limitations](../known-limitations.md#general-mei-validation-scope).

## Historical assessment — 2026-09-30

Everything below preserves the original assessment and implementation proposals.
References to missing features or future stages describe that date, not the
current implementation. The initial inspection did not edit the checker,
notebook, corpus MEI or schema, and preserved existing uncommitted changes.

The inventory below describes that initial assessment. The first implementation
slice has since added the [frozen baseline](../../test_corpus/validation_baseline/README.md)
and separated the general checking path from optional conventions. General mode
now permits absent facsimiles, defaults to standalone references, checks local
`resp`/`source` fragments through a shared registry, and makes naming/numbering
and group comparisons optional. The notebook uses the portable Hummel baseline,
shows its selected schema/checks, and rejects check-only transformations.

At that first boundary-refactor stage, focused validation passed 27 regression
tests. Its baseline records independent
RELAX NG and Verovio results and unchanged source hashes. Hummel and Webern have
consumer warnings, retained as diagnostics. Schematron, URI/base resolution,
complete execution records, CAMAT parsing and the DdT entry point had not yet
landed at that stage. That earlier slice is not complete conformance or corpus
release evidence; later work is described above.

Context was recovered from the corpus chat **Assess MEI header and schema** and
checked against the then-current files in the
[DdT repository](https://github.com/egorpol/DdT_1_vol_11), especially
`docs/validation-workflow.md`, `docs/mei-encoding-profile.md` and
`docs/editorial-policy.md`. These paths identify corpus-owned documents, not
CAMAT validation dependencies.

## Recommendation

Use CAMAT for reusable validation mechanisms and consumer diagnostics. Use a
small DdT repository entry point for selecting release inputs, enforcing its
edition policy, and deciding publication acceptance. Keep the official MEI 5.1
CMN schema unchanged and retain CMN as CAMAT's configured default.

Directory selection determines which files are checked. It does not make those
files a uniform musical corpus. Staff-count, naming, page-layout, and editorial
requirements need an explicit group or edition profile. A batch of unrelated
MEI files must receive independent general results.

Report three results separately:

1. **MEI conformance:** XML, selected RELAX NG and Schematron, IDs and reference
   integrity in the declared document context.
2. **Musical and consumer diagnostics:** supported rhythm/pitch/anchor checks,
   Verovio loading/rendering, and optional CAMAT parsing. These findings are not
   automatically evidence of invalid MEI.
3. **DdT acceptance:** the local encoding and editorial policy, input/release
   scope, and reviewed exceptions. This result consumes the first two results.

The local wrapper should use an installed, tested CAMAT release or immutable
commit. Provide an explicit dependency-update operation to try the latest
build, run regression cases, and record the selected revision. Ordinary
validation should not run `git pull` or `pip install -U` automatically: that
would change the validator between otherwise identical runs. During development,
an editable installation from this checkout is useful; record its revision and
dirty source hashes.

## What the notebook did at the assessment date

At the assessment date, the notebook was already mostly orchestration:

- Cell 1 imports the package's checker, workflow, report, and transformation
  functions. Its cloud fallback can install an unpinned CAMAT release; the local
  `setup_camat` subsequently selects this checkout.
- Cell 3 actually selects the **Pisendel concerto in DdT volumes 29/30** and
  writes reports beside it. The introduction claims Buxtehude Op. II/4, and the
  closing notes claim the offline sample is active. Neither describes the active
  configuration. `RUN_PIPELINE` is false.
- Publication, RELAX NG, PPQ comparison, figured-bass conversion diagnostics,
  page-break checks, and full Verovio rendering are enabled. Network image
  checking and annotation export are disabled.
- Cell 7's check-only branch invokes `run_checker`, then `run_editorial_checks`,
  which invokes `run_checker` again. The base checks therefore run twice.
- The combine branch sets `page_csv = None`, so the described per-page report is
  currently not executed. It prepares copies, combines them, and checks the
  result. Restoring per-page checks requires explicit assembly semantics.
- `STRIP_PPQ` and `STRIP_ACCID_GES` call in-place cleanup in check-only mode.
  They are currently false, but the claim that listed inputs cannot change is
  conditional. Remove transformations from the validation execution path.
- Optional annotation export creates another MEI beside the checked file.
  Retain it as an explicit report-export operation, with a chosen output path.

The library's `run_editorial_checks` itself is read-only, but defaults
`publication_profile=True` and `check_fb_tstamp=True`. The command
`camat-check-mei` runs the base consistency checker, not the whole schema/render
suite; without `--fail-on` its zero exit status does not establish conformance.
It also currently exposes PPQ transformation flags.

Missing `xmllint` or Verovio currently raises an exception rather than silently
passing. However, the base CSV is written before later passes execute, so an
interrupted suite can leave a partial report without a complete run-status
record. Preserve the failure behavior and make incomplete execution explicit.

## Rule ownership inventory

The IDs below are the report IDs inspected at the assessment date. “General” means CAMAT owns the
mechanism. “Diagnostic” means CAMAT may offer it without making it a universal
MEI requirement. “DdT” means the local profile owns the expectation and severity.
Reusable helpers may stay in CAMAT even when DdT selects the policy.

### General conformance mechanisms

- `well_formed_xml`, `duplicate_xml_id`, `root_element`: keep in CAMAT.
- `mei_version`: keep, but compare with the explicitly selected schema instead
  of the current hardcoded “project files inspected here” comparison.
- `broken_internal_reference`, `empty_internal_reference`: keep and extend.
  The current registry omits `resp` and `source`; it also ignores explicit
  document-plus-fragment references and applicable `xml:base` resolution.
- `cross_file_internal_reference`: retain only as an **assembly diagnostic**.
  Currently selecting multiple files can downgrade a broken bare fragment to
  information when the ID exists in another file. In standalone mode, `#id`
  must resolve in its document. `other.mei#id` is a different case.
- `mei_51_cmn_relaxng`: keep the execution helper; expose a schema parameter
  through the top-level runner and use a schema-neutral rule label in the new
  API, preserving legacy report compatibility as needed.
- Add genuine Schematron execution. The existing `cmn_schematron_pi` rule checks
  only a declaration. It does not execute assertions. Preserve namespaces,
  support the embedded XPath 2 expressions, pin compiler/processor versions,
  and retain SVRL or equivalent structured diagnostics. A missing engine,
  compilation failure, or accidentally empty extraction must not produce a
  pass for a required Schematron check.

Use one schema-aware reference registry in checking, ID rewriting, and any
cleanup that protects referenced nodes. Both checker and workflow currently
maintain their own short `REFERENCE_ATTRS` set. Validate target semantics where
supported: generic `resp` handling should not require only `respStmt` targets;
DdT can select that narrower convention.

### Shared musical and consumer diagnostics

- `staffdef_n`, `missing_meter`, `mixed_staff_meters`,
  `extra_staff_in_measure`, `missing_staff_in_measure`: retain as contextual CMN
  diagnostics. Omitted staves and polymeter need interpretation, not blanket
  rejection.
- `missing_layer`, `duplicate_layer_n`, `empty_layer`, `missing_duration`,
  `rhythm_no_meter`, `layer_duration_underfull`, `layer_duration_overfull`:
  retain with declared semantic coverage. Account for pickups, `metcon`, grace
  events, tuplets, meter changes, and alternatives. The present `layer.iter()`
  walk can sum both branches of `choice`/`app`; choose a reading or mark that
  timing check unsupported. Duration defaults and additive durations also need
  explicit handling before claiming broad MEI support.
- `invalid_pname`, `invalid_octave`, `missing_pitch`: keep in the supported
  notation context; schema validity remains authoritative for allowed forms.
- `dur_ppq_mismatch`: keep optional. Remove its current assertion that written
  duration is authoritative “for this facsimile-based edition”; DdT owns that
  interpretation. PPQ presence and `accid.ges` are not universal errors.
- `verovio_log`: keep as an optional consumer result, including load failure
  and render execution status. Add CAMAT parsing as a separate optional probe;
  name its backend/reading/playback settings. Do not universally equate raw XML
  note counts with parsed rows.
- `fb_startid_to_tstamp`: split its meanings. An unresolved or inappropriate
  target is a general integrity/consumer issue. A valid anchor that could be
  converted is a style preference, enabled only by a selected profile.
  [MEI harm](https://music-encoding.org/guidelines/v5/elements/harm.html) supports
  `startid` and several timestamp forms.
- `misplaced_empty_accid`, `empty_chord`, `empty_annotation`,
  `empty_note_accidentals`: currently gated by `publication_profile`, although
  they contain reusable structural diagnostics. Move the supported checks to
  the general diagnostic layer. Respect schema content alternatives such as
  editorial wrappers; remove any claim that an empty node is always safe to
  delete without checking references and context.

### Optional conventions and group diagnostics

CAMAT can offer these mechanisms, but a general validation run should not treat
the expected convention as mandatory:

- `measure_number`, `measure_sequence`, `single_layer_not_numbered_one`:
  configurable edition/group conventions. Nonnumeric measure labels, numbering
  restarts, and retained voice numbers can be intentional.
- `empty_staff_label`, `generic_staff_label`, `generic_staff_abbr`,
  `missing_staff_name`, `missing_instrdef`: optional presentation/playback
  diagnostics. DdT's source labels and analytical staff-role mapping determine
  local acceptance; MIDI instruments are not required for every MEI.
- `empty_term`, `term_anchor`, `term_whitespace`,
  `term_spelling_variants_in_file`: keep optional inspection helpers, allowing
  valid nontextual content and supported alternate anchors. Spelling
  normalization is editorial policy.
- `corpus_staff_set_variants`, `corpus_staff_label_variants`,
  `corpus_staff_abbr_variants`, `corpus_midi_instrnum_variants`,
  `corpus_term_spelling_variants`: opt-in group comparisons. They currently run
  from `check_mei_files` automatically. A staff number in two unrelated scores
  does not imply the same instrument. Group related pages/works deliberately;
  do not use the directory majority to define correct instrumentation.

### Facsimile mechanisms versus DdT topology

Keep general reference/resource and geometry mechanisms; apply them only when
the relevant data is supplied and its meaning is known.

- `zone_coordinates`: general coordinate diagnostics, extending beyond only
  `type='measure'` and respecting the coordinate form in the selected schema.
- `zone_image_bounds`: general geometry after correcting the current assumption
  that the first graphic's pixel dimensions define every surface coordinate.
  Interpret the surface coordinate space and selected graphic mapping.
- `graphic_metadata`: generic metadata/resource checks where useful; requiring
  every listed attribute is a profile choice.
- `iiif_graphic_target`: replace the IIIF-only assumption with resource checks
  for local paths, direct HTTP images, and IIIF. Keep any IIIF-specific request
  check explicit. No facsimile means the resource pass is inapplicable, not a
  failed MEI. Network failures should be recorded as accessibility results.

Move the following default requirements to DdT's primary-facsimile policy:

- `measure_facs`, `measure_facs_zone_type`, `unused_measure_zone`:
  complete one-measure/measure-zone coverage and the local zone classification.
  The current `measure_facs` warning runs even with publication disabled.
- `surface_graphic_count`: DdT may adopt one access graphic per primary surface.
  General MEI permits multiple representations.
  [MEI surface](https://music-encoding.org/guidelines/v5/elements/surface.html)
  defines its coordinate space and multiple graphics;
  [MEI graphic](https://music-encoding.org/guidelines/v5/elements/graphic.html)
  defines URI targets and optional metadata.
- `surface_page_number`, `surface_page_sequence`, `surface_iiif_canvas`:
  DdT selects local numbering and the BSB canvas relationship. Current code
  calls `surface/@n` a printed-page number, whereas the DdT document requires a
  work-local sequence beginning at 1; printed pages belong in source metadata.
- `duplicate_measure_zone_use`, `page_break_per_surface`, `page_break_number`,
  `measure_page_context`, `system_break_zone_alignment`, `pb_facs_surface_link`:
  DdT's source-faithful primary page/system topology. Shared analyzers can
  provide evidence, but generic MEI need not use this exact topology. Zone-band
  inference of a system break is a heuristic requiring editorial review.

Support multiple facsimile sources and URI-list attributes; do not assume all
facsimile links are a single local zone ID. Supplementary Uppsala witnesses
need not introduce a competing page-break sequence.

### Publication/header rules owned by DdT

These current IDs belong to the local acceptance profile:

- `cmn_relaxng_pi`, `cmn_schematron_pi`, `cmn_meiversion`: exact MEI 5.1 CMN
  declaration requirements. General CAMAT compares supplied declarations with
  its selected schema; DdT requires both exact declarations. Replace substring
  matching that currently accepts the expected basename under a wrong version.
- `meihead`, `repository_alt_id`, `edition_statement`, `edition_version`,
  `publisher`, `mei_license`, `source_description`, `editorial_declaration`,
  `project_description`, `work_description`, `revision_history`:
  DdT's required metadata and release identity. Schema-required structure still
  belongs to schema validation. Scope the digital license to
  `fileDesc/pubStmt/availability`; a source-image license cannot satisfy it.
- `stable_identifier`, `iiif_manifest`: BuxWV and the correct DdT/BSB identities
  and manifest are corpus values, not universal MEI requirements.
- `application_provenance`: verify truthful provenance of tools actually used.
  Do not universally require musiconn.scoresearch, Verovio, and mei-friend.
- `mdiv_work_link`, `revision_order`, `revision_responsibility`: DdT selects its
  work-linkage and history conventions; generic helpers can inspect them.

Add local rules for the declared addressable-event ID set; stable edition-key,
working/final filename, URI, date and version mapping; BuxWV/work identity;
per-opus Uppsala source mapping; per-work staff roles; annotation categories,
targets, readings, evidence and responsibility; release inclusion and corpus
identity uniqueness; scan inventory, derivatives, rights, and exceptions.
Do not require every event ID to be globally unique across independent files:
the corpus address is a stable file identity plus its local fragment.

The pilot's five staves and analytical first-three-staff view are not mandatory
for every appendix work. Presence of editorial evidence can be checked
automatically; its musical adequacy still needs human review. A bibliographic
witness without public scans can be valid. Image-distribution checks apply to
images actually included in the release.

### Transformation-only findings and operations

`empty_accid_referenced`, `accid_conflict`, `tie_missing_endpoint`,
`tie_endpoint_not_note`, `tie_pitch_mismatch`, `tie_role_conflict`,
`tie_role_review`, `tie_cross_layer_note_roles` currently arise in cleanup
helpers, not the notebook's ordinary general-check pass. Extract any useful
read-only analysis into diagnostics; keep edits in explicit transformations.

Keep ID-copying, page combining, PPQ stripping, accidental removal,
figured-bass anchor conversion, page-break linking, measure/layer renumbering,
staff-label overrides, tie fixes, and MEI annotation export available as
separate operations. DdT selects when an operation is editorially appropriate.
Validation must never silently call them. `accid.ges` can preserve intentional
sounding-pitch information; blanket removal needs a reviewed transformation
policy and pitch checks.

## Assessment evidence and baseline

The companion [baseline record](mei-validation-baseline.json) contains the assessment-date
revisions, worktree state, hashes, and focused probe results. The original pilot
and source files had identical hashes before and after the probes.

- CAMAT HEAD: `eebcac61c6585ede868c3869aa5019c6a52f4895`, package metadata 0.2.4.
- DdT HEAD: `c17be260143c6da4921ad15022426153c8f25182`.
- Pilot: `buxtehude_op1_01_sonata_f_major_corr.mei`, SHA-256
  `3dd9d312905249e0dcf60b54b5596cbbdcf2420b235eb21988128bf3850c2d55`.
- Both local CMN schema copies have SHA-256
  `f6440d5eb59c3e903f2a7a64ea26518646186f8449b86096106846a269eb354b`.

These repositories already contain uncommitted work. HEAD alone does not
identify the notebook configuration or pilot bytes; retain the hashes and
snapshot the relevant changed inputs before implementation.

Focused results with PPQ comparison enabled:

- Pilot: zero base-check findings in general and legacy-publication modes;
  RELAX NG passed. This is not a complete release pass.
- Temporary pilot with facsimile elements and all `facs` attributes removed:
  RELAX NG passed; general checking reported 183 `measure_facs` warnings.
- Temporary pilot with a second graphic inserted before zones on one surface:
  RELAX NG passed; legacy publication checking reported one
  `surface_graphic_count` error.
- Temporary pilot with a broken `change/@resp`: RELAX NG passed; the general
  checker emitted no findings.
- Temporary pilot with all starting-anchor attributes removed from one `harm`:
  RELAX NG passed; the general checker emitted no findings. The embedded
  Schematron assertion requires an anchor; this is a useful regression candidate.
  Schematron was not executed in these assessment probes.
- A temporary CMN 5.1 adaptation of `tests/fixtures/basic.mei`, with a valid empty
  `pubStmt`: RELAX NG passed; two `measure_facs` warnings and one optional
  `missing_instrdef` information row occurred. The existing fixture is MEI 5.0
  and should not simply be relabelled as a known-valid CMN 5.1 fixture.
- The active Pisendel score passed RELAX NG but produced one broken-reference
  error plus musical/consumer diagnostics. Preserve it as a diagnostic case;
  curate a separate known-valid different-composer fixture for a clean-pass
  regression. Do not suppress its real pointer error to manufacture a pass.

No Verovio render, CAMAT consumer parse, network-resource pass, or new
Schematron run was performed here. The earlier corpus chat's full validation
evidence applies to its recorded input state, not automatically to future bytes.
The temporary probe script was at `/tmp/camat-mei-assessment/probe.py` in the
assessment environment; it is not a portable project artifact.

## Proposed minimal architecture

Introduce a focused CAMAT validation module with an explicit options object
and structured result. Names are proposals, not existing API:

```python
result = run_validation(
    files,
    schema=selected_schema,
    document_mode="standalone",
    diagnostics=selected_diagnostics,
    consumers=selected_consumers,
    resources=resource_options,
)
edition_findings = validate_ddt_policy(files, result, profile, work_list)
```

CAMAT owns execution, reusable analyzers, findings serialization, and a run
record. DdT owns the profile constants, Python policy rules, selected works,
exceptions, and review/release gate. No dynamic plugin framework is needed.

Proposed corpus paths:

- `scripts/validate_corpus.py`: CLI orchestration, shared checks first, then
  local rules; no validator reimplementation and no notebook dependency.
- `validation/profile.json`: schema pin, required checks, conventions and
  per-work policy configuration.
- `validation/rules.py`: scoped header, work/source, annotation, and release
  relationships.
- An initially small explicit work list. A full release manifest can grow from
  that once identity and release scope are settled.
- A pinned CAMAT requirement/commit and shared/local regression fixtures.

Reports should include findings plus run metadata: source hashes, CAMAT
revision/version and dirty hashes, schema/profile hashes, tool versions,
requested checks, executed checks and per-file statuses. Use `passed`, `failed`,
`skipped`, and `execution-error`, recording why a pass is inapplicable.
Required skipped/error checks and an empty input list must block acceptance.
An empty finding list cannot establish that all required validators ran.

Review mode reports incomplete edition requirements and accepts working
filenames. Release mode enforces the selected works' final identity, review
status, required pass execution, and documented exceptions. Fast offline and
full release checks should use the same entry point; network checks remain an
explicit accessibility pass.

Retain `MeiChecker`, `check_mei_files`, `run_checker`, `run_editorial_checks`, and
the current CSV columns, or document a migration. A new runner can expose
structured results while compatibility wrappers preserve older return types.
Warn about the legacy edition-specific publication boolean and give it a
documented transition; do not silently replace its meaning for existing users.
Separate/deprecate CLI transformation flags with an explicit migration route.

## Step-by-step implementation sequence

### 1. Freeze the assessment inputs and rule boundary

Work in both repositories. Save the pilot bytes and checksum, relevant dirty
notebook/configuration changes, schema checksum, code revision, and options.
Select the pilot, a genuinely schema-valid ordinary no-facsimile CMN 5.1 fixture,
and a known-valid other-composer score/excerpt. Keep Pisendel's current
diagnostic case separately. Use an explicit release input list instead of a
recursive repository glob.

Audit the legacy edition notebooks and scripts before retirement. Initial
inspection found local helper imports and policy settings rather than a new
validator engine: `mei_corrected_full_checks.ipynb` enables in-place PPQ and
`accid.ges` cleanup; `fb_startid_to_tstamp_workflow.ipynb` demonstrates anchor
and accidental normalization. Preserve any unique editorial choices in policy
documentation and any missing reusable transformation in CAMAT. The corpus
checker is a divergent copy: CAMAT adds a system-break diagnostic and a public
`check_mei_files` entry point. Replace the copy only after behavior/callers are
covered. Full legacy transformation equivalence remains an audit task.

**Done when:** rule ownership and input scope are agreed, relevant working bytes
can be restored, and no notebook is required for validation. No complete
manifest system is needed yet.

### 2. Make the CAMAT general path read-only and edition-neutral

Add the explicit schema/options/result boundary. Extract publication constants
and topology expectations. Gate optional naming, numbering, group comparisons,
and figured-bass style diagnostics. Separate all transforms from validation.
Share URI handling with ID rewriting and make standalone/assembly modes explicit.

**Done when:** valid no-facsimile and other-composer cases have no edition-policy
warnings; mixed-file batches do not enforce majority instrumentation; broken
standalone fragments fail; validation leaves all input hashes unchanged.

### 3. Complete shared execution and resources

Add XPath 2-capable Schematron execution with namespace-preserving extraction,
SVRL diagnostics, schema/tool pins and explicit failures. Extend declaration
comparison, image-resource handling and surface geometry. Add execution records
and optional CAMAT consumer parsing; preserve separate Verovio results.

**Done when:** a Schematron-only violation fails; unavailable required tools and
disabled required passes cannot yield acceptance; `resp`/`source`, URI lists,
document references and ID-rewrite preservation are covered; local images,
ordinary image URLs and valid multiple graphics have positive counterexamples.

### 4. Reduce the notebook to a visible interface

Select an honest portable example; show the actual profile, schema, paths and
requested/executed/skipped checks. Remove cleanup from the run cell, invoke the
base checks once, and make any per-page assembly check explicit. Link to separate
conversion/combine/export operations. Preserve the notebook's current user edits
while updating its configuration rather than replacing the file wholesale.

**Done when:** the notebook calls tested package functions, produces a clear run
summary, and cannot silently rewrite an input. Document migration and add CAMAT
release notes. Publish or pin the tested implementation revision.

### 5. Add the small DdT validator

Install/pin that CAMAT build. Implement the local entry point, profile, scoped
rules, and explicit work list. Use review mode on the pilot first, then add
release identity, annotation/source rules, event IDs, primary topology and
per-work roles. Handle appendix exceptions explicitly. Replace the duplicated
generic script with a small compatibility wrapper or retire it with updated
callers. Retire legacy notebooks after their audit, independently of validator
execution.

**Done when:** local and CI invocation use the same script; the pilot gets the
three distinct results; wrong digital-license scope, source mapping, filename,
event IDs, and incomplete annotations fail the intended DdT rules.

### 6. Prove the integration and establish the update routine

Run shared and local regression cases against the pinned CAMAT revision. Include
valid conjectures, appendix-specific mappings and witnesses without public
scans; reject missing required passes and empty release input selections.
Hash originals before/after and record all statuses. An explicit later CAMAT
update should rerun these cases and change the pin only after review.

**Done when:** the corpus has a reproducible acceptance result against recorded
bytes and tools, while ordinary general MEI checking works independently of DdT.
Human musical/source review remains part of publication acceptance.

The next implementation slice is step 2's minimal boundary and read-only path,
after preserving step 1's working inputs. Do that before building a larger local
manifest or integrating new scans.
