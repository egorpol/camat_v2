---
title: Verovio backend
---

# Verovio backend

For common notation, source pitch extraction resolves standard key signatures
(`keysig`, legacy `key.sig`, and `keySig@sig`) and written accidentals carried
within a staff and octave until the barline. Staff-specific keys and changes,
cross-layer accidental carry, explicit gestural alterations and tied
continuations are handled before deriving MIDI and enharmonic pitch names.
Nonstandard key-signature declarations outside 0–7 sharps/flats are rejected
by this implicit-pitch resolver.

This is independent of the playback timeline: Verovio's MIDI output uses
encoded sounding accidental values such as `accid.ges`, which can be absent
on notes whose alteration is only implied by the written score.
See [Verovio's MIDI output reference](https://book.verovio.org/toolkit-reference/output-formats.html#midi).

::: camat.verovio_backend
