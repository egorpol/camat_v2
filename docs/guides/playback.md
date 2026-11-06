---
title: Playback data
---
# Playback data

An MEI file can look right and still sound wrong. Verovio's MIDI output and
music21's MEI import use only what the file states: they do not work out a
note's pitch from the key signature, and they cannot guess an instrument or
a speed. OMR output adds its own errors, such as a piano on nearly every part
and tempo numbers the print does not have.

This guide shows how to prepare an MEI file so that it plays correctly. Three
kinds of data matter:

| What you hear | Where it is in the MEI | If it is missing |
| --- | --- | --- |
| [Pitch](#sounding-pitch) | `@accid.ges` on notes | Verovio and music21 play some notes at the wrong pitch |
| [Instrument](#instruments) | `@midi.instrnum` on `instrDef` | The MIDI file names no instrument, and most players use a piano |
| [Speed](#tempo) | `@midi.bpm`, or `@mm` on `tempo` | Verovio plays at quarter note = 120 |

CAMAT's analyses do not need the instrument and tempo values: adding them
leaves `df_pitch` unchanged. CAMAT also works out pitch from the notation, so
its results are right without `@accid.ges`. An explicit value overrides that
result, though, so a wrong value changes them too.

The behaviour described here was tested with Verovio 6.3.0 and 6.4.1 and with
music21 10.5.0. Later versions may differ.

## Sounding pitch

Verovio and music21 take a note's pitch only from its own `@accid` or
`@accid.ges`. They ignore the key signature and any accidental carried through
the bar. Under a one-flat key signature, an unmarked B4 plays as B natural.
After a written F sharp, the next F4 in that bar plays as F natural.

`@accid.ges` corrects this, and CAMAT 0.2.9 or newer writes it from the
notation, so nobody has to enter values by hand. A note without a written
accidental gets a value when it sounds altered, and every other note gets
none. Values that OMR left behind are replaced, because a wrong one misleads
every program that reads it.

[`combine_meis`](../api/mei_consistency.md#sounding-pitch-and-gestural-accidentals)
does this by default when it assembles a work. Any later edit to notes,
accidentals, key signatures or ties can leave the values out of date. List the
differences without changing the file:

```sh
camat-check-mei score.mei --check-accid-ges --output pitch-review.csv
```

Each difference is an `accid_ges_mismatch` warning. To rewrite the values:

```python
from pathlib import Path

from camat import regenerate_accid_ges_text

path = Path("score.mei")
text, report = regenerate_accid_ges_text(path.read_bytes().decode("utf-8"))
path.write_bytes(text.encode("utf-8"))
print(report.added, report.removed, report.unresolved)
```

Only `accid.ges` attributes change. Notes CAMAT cannot resolve stay as they
are and appear in `report.unresolved`.

A value that contradicts the notation does not survive this step. If a note
should sound different from the print, encode a written accidental with an
editorial annotation, as the DdT edition does.

## Instruments

Give each part a General MIDI program in an `instrDef`:

```xml
<staffDef n="1" lines="5" clef.shape="G" clef.line="2">
  <instrDef midi.channel="0" midi.instrnum="40"/>
</staffDef>
```

`midi.instrnum` counts from 0: 0 is piano, 6 harpsichord, 40 violin, 41 viola,
42 cello and 43 contrabass. OMR tends to leave `0`: in the DdT page files, 690
of 732 instrument definitions have it.

- **Use the number.** Verovio ignores `midi.instrname`, and MEI allows only one
  of the two.
- **Set it in the opening `scoreDef`.** Verovio ignores instruments in later
  ones, so a change of instrument within a work does not sound. Repeat the
  same values in any later `scoreDef`.
- **One instrument on two staves:** put the `instrDef` on the `staffGrp` that
  holds both.
- **Channels:** number the parts 0, 1, 2 and so on, and skip 9, which General
  MIDI keeps for percussion.

CAMAT does not write these values, so set them from what each staff is. Two
checks help:

```sh
camat-check-mei score.mei --editorial-diagnostics --output instruments.csv
camat-check-mei work1.mei work2.mei --group-diagnostics --output instruments.csv
```

The first reports `missing_instrdef` for a staff with no instrument. The second
reports `corpus_midi_instrnum_variants` when the same staff number has
different programs across the files. Neither can tell that a `0` left by OMR
is wrong.

## Tempo

Verovio takes speed from numbers only. Tempo words such as "Adagio" have no
effect, and a file without numbers plays at quarter note = 120. What to encode
depends on the print:

| The print has | Encode |
| --- | --- |
| Tempo words only | The words, with no numbers. Remove any `midi.bpm`, `midi.mspb`, `mm`, `mm.unit` and `mm.dots` that OMR left. |
| A metronome mark | The printed text in `tempo`, with `mm`, `mm.unit` and `mm.dots`, plus `midi.bpm` as described below. |

The DdT volume, for example, prints no metronome marks, yet its OMR pages carry
values such as `midi.bpm="190"`. Its edition removes them and leaves the speed
to the player. It keeps its
[suggested speeds](https://github.com/egorpol/DdT_1_vol_11/blob/main/playback/tempo-guide/README.md)
outside the MEI, since they are not part of the print.

`midi.bpm` counts quarter notes per minute, whatever the meter. Movement I of
Webern's Op. 27 is marked "♪. = ca 40", which is 30 quarter notes per minute:

```xml
<scoreDef midi.bpm="30">
  ...
</scoreDef>
...
<tempo staff="1" tstamp="1" mm="40" mm.unit="8" mm.dots="1" midi.bpm="30">Sehr mäßig ♪. = ca 40</tempo>
```

This example has both values because of how Verovio behaves:

- **First bar:** `scoreDef/@midi.bpm` sets the speed of the MIDI file, but a
  `tempo` in the first bar sets the time map, which players use to highlight
  notes. If the two differ, the highlighting drifts away from the sound. Give
  both the same value, or leave `midi.bpm` off the `scoreDef`.
- **Dotted units:** Verovio multiplies `mm` by 4/3 for one dot and 8/5 for two.
  The correct factors are 3/2 and 7/4, so "♪. = 40" becomes 26.67 instead
  of 30. `midi.bpm` on the `tempo` takes priority, so put the correct value
  there.
- **Changes within a bar:** a tempo change applies from the start of its bar,
  whatever its `tstamp`.
- **`midi.mspb`:** Verovio ignores it on `scoreDef`.

## Listen to the result

Write a MIDI file and open it in any MIDI player:

```python
import verovio

toolkit = verovio.toolkit()
toolkit.loadFile("score.mei")
toolkit.renderToMIDIFile("score.mid")
```

The [web-edition template](web-edition.md) has no audio player yet.
