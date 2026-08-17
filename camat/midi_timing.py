"""Lossless tick-domain MIDI timing tables for performance-oriented analysis.

This module deliberately does not route MIDI through music21's score importer,
MusicXML, or MEI. It pairs raw note-on/note-off events while preserving their
tick positions, then derives metric quarter lengths and tempo-aware seconds.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


NOTE_COLUMNS = [
    "track",
    "track_name",
    "channel",
    "pitch",
    "velocity",
    "onset_tick",
    "offset_tick",
    "duration_ticks",
    "onset_quarter_length",
    "duration_quarter_length",
    "onset_seconds",
    "offset_seconds",
    "duration_seconds",
]

TEMPO_COLUMNS = [
    "tick",
    "quarter_length",
    "seconds",
    "microseconds_per_quarter",
    "quarter_bpm",
]


@dataclass
class MidiTimingResult:
    """Raw note timing and tempo-map tables from one MIDI file."""

    source: Path
    ticks_per_quarter_note: Optional[int]
    ticks_per_second: Optional[int]
    format: int
    track_count: int
    notes: pd.DataFrame
    tempo_map: pd.DataFrame

    @property
    def timing_basis(self) -> str:
        """Return ``"ppq"`` for metric MIDI or ``"smpte"`` for timecode MIDI."""
        return "smpte" if self.ticks_per_second is not None else "ppq"


def _track_name(timed_events: List[Tuple[int, Any]], encoding: str) -> str:
    from music21.midi.base import MetaEvents  # type: ignore

    for _, event in timed_events:
        if event.type != MetaEvents.SEQUENCE_TRACK_NAME:
            continue
        if isinstance(event.data, bytes):
            return event.data.decode(encoding, errors="replace")
        return str(event.data or "")
    return ""


def _tempo_events(
    tracks_with_events: List[Tuple[int, List[Tuple[int, Any]]]],
) -> List[Tuple[int, int]]:
    from music21.midi.base import MetaEvents  # type: ignore

    by_tick: Dict[int, int] = {}
    for _, timed_events in tracks_with_events:
        for tick, event in timed_events:
            if event.type != MetaEvents.SET_TEMPO or not isinstance(event.data, bytes):
                continue
            if not event.data:
                continue
            by_tick[int(tick)] = int.from_bytes(event.data, byteorder="big")
    if 0 not in by_tick:
        by_tick[0] = 500_000  # Standard MIDI default: 120 quarter notes per minute.
    return sorted(by_tick.items())


def _build_ppq_tempo_map(
    tempo_events: List[Tuple[int, int]],
    ticks_per_quarter: int,
) -> Tuple[pd.DataFrame, Any]:
    segment_ticks: List[int] = []
    segment_seconds: List[float] = []
    segment_tempi: List[int] = []
    rows: List[Dict[str, Any]] = []
    previous_tick = 0
    elapsed_seconds = 0.0
    active_microseconds = 500_000

    for tick, microseconds_per_quarter in tempo_events:
        elapsed_seconds += (
            (tick - previous_tick)
            * active_microseconds
            / (1_000_000 * ticks_per_quarter)
        )
        previous_tick = tick
        active_microseconds = microseconds_per_quarter
        segment_ticks.append(tick)
        segment_seconds.append(elapsed_seconds)
        segment_tempi.append(active_microseconds)
        rows.append(
            {
                "tick": tick,
                "quarter_length": Fraction(tick, ticks_per_quarter),
                "seconds": elapsed_seconds,
                "microseconds_per_quarter": active_microseconds,
                "quarter_bpm": 60_000_000 / active_microseconds,
            }
        )

    def tick_to_seconds(tick: int) -> float:
        index = max(0, bisect_right(segment_ticks, tick) - 1)
        return segment_seconds[index] + (
            (tick - segment_ticks[index])
            * segment_tempi[index]
            / (1_000_000 * ticks_per_quarter)
        )

    return pd.DataFrame(rows, columns=TEMPO_COLUMNS), tick_to_seconds


def _build_smpte_tempo_map(
    tempo_events: List[Tuple[int, int]],
    ticks_per_second: int,
) -> Tuple[pd.DataFrame, Any]:
    rows = [
        {
            "tick": tick,
            "quarter_length": pd.NA,
            "seconds": tick / ticks_per_second,
            "microseconds_per_quarter": microseconds,
            "quarter_bpm": 60_000_000 / microseconds,
        }
        for tick, microseconds in tempo_events
    ]

    def tick_to_seconds(tick: int) -> float:
        return tick / ticks_per_second

    return pd.DataFrame(rows, columns=TEMPO_COLUMNS), tick_to_seconds


def read_midi_timing(
    source: str | Path,
    *,
    encoding: str = "utf-8",
) -> MidiTimingResult:
    """Read raw MIDI note timings without score quantization or chord grouping.

    For PPQ MIDI, exact :class:`fractions.Fraction` quarter-length values are
    calculated directly from ticks. Seconds are integrated over the tempo map.
    SMPTE/timecode MIDI retains seconds but leaves quarter-length columns empty
    because it does not define a beat grid.
    """
    from music21.midi import MidiFile, translate  # type: ignore

    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"MIDI file does not exist: {source_path}")

    midi_file = MidiFile()
    midi_file.open(source_path)
    try:
        midi_file.read()
    finally:
        midi_file.close()

    tracks_with_events = [
        (index, translate.getTimeForEvents(track))
        for index, track in enumerate(midi_file.tracks)
    ]
    tempo_events = _tempo_events(tracks_with_events)
    ticks_per_second = (
        int(midi_file.ticksPerSecond)
        if midi_file.ticksPerSecond is not None
        else None
    )
    ticks_per_quarter = (
        int(midi_file.ticksPerQuarterNote)
        if ticks_per_second is None
        else None
    )
    if ticks_per_second is not None:
        tempo_map, tick_to_seconds = _build_smpte_tempo_map(
            tempo_events,
            ticks_per_second,
        )
    else:
        assert ticks_per_quarter is not None
        tempo_map, tick_to_seconds = _build_ppq_tempo_map(
            tempo_events,
            ticks_per_quarter,
        )

    rows: List[Dict[str, Any]] = []
    for track_index, timed_events in tracks_with_events:
        name = _track_name(timed_events, encoding)
        for timed_note in translate.getNotesFromEvents(timed_events):
            onset_tick = int(timed_note.onTime)
            offset_tick = int(timed_note.offTime)
            onset_seconds = tick_to_seconds(onset_tick)
            offset_seconds = tick_to_seconds(offset_tick)
            rows.append(
                {
                    "track": track_index,
                    "track_name": name,
                    "channel": timed_note.event.channel,
                    "pitch": timed_note.event.pitch,
                    "velocity": timed_note.event.velocity,
                    "onset_tick": onset_tick,
                    "offset_tick": offset_tick,
                    "duration_ticks": offset_tick - onset_tick,
                    "onset_quarter_length": (
                        Fraction(onset_tick, ticks_per_quarter)
                        if ticks_per_quarter is not None
                        else pd.NA
                    ),
                    "duration_quarter_length": (
                        Fraction(offset_tick - onset_tick, ticks_per_quarter)
                        if ticks_per_quarter is not None
                        else pd.NA
                    ),
                    "onset_seconds": onset_seconds,
                    "offset_seconds": offset_seconds,
                    "duration_seconds": offset_seconds - onset_seconds,
                }
            )

    notes = pd.DataFrame(rows, columns=NOTE_COLUMNS)
    if not notes.empty:
        notes = notes.sort_values(
            ["onset_tick", "track", "channel", "pitch"],
            kind="stable",
            ignore_index=True,
        )

    return MidiTimingResult(
        source=source_path,
        ticks_per_quarter_note=ticks_per_quarter,
        ticks_per_second=ticks_per_second,
        format=int(midi_file.format),
        track_count=len(midi_file.tracks),
        notes=notes,
        tempo_map=tempo_map,
    )


__all__ = ["MidiTimingResult", "read_midi_timing"]
