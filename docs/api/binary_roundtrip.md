# Binary roundtrip experiments

Deterministic examples, occupancy/event audits, source-span provenance, and
comparison plots for the
[`binary_roundtrip.ipynb`](../../notebooks/binary_roundtrip.ipynb) and
[`binary_pattern_search.ipynb`](../../notebooks/binary_pattern_search.ipynb) notebooks.

`extract_binary_kernel` retains the actual source window and its silent time
columns. `rank_binary_matches` adapts labeled search maps to MIDI/time coordinates,
with optional source-passage exclusion and suppression of overlapping windows.
Its provenance trace supports valid placements; use the convolution API directly
for padded edge experiments.

::: camat.binary_roundtrip
    options:
      members:
        - make_roundtrip_example
        - compare_binary_resolutions
        - audit_binary_roundtrip
        - compare_voice_roundtrips
        - describe_binary_span_sources
        - plot_binary_comparison
        - plot_note_comparison
        - prepare_binary_timeline
        - split_binary_voices
        - find_binary_matches
        - extract_binary_kernel
        - rank_binary_matches
        - binary_match_sources
        - plot_binary_search_trace
