"""Helpers for converting binary matrices to music21/Verovio outputs."""
from __future__ import annotations

from typing import Optional

import pandas as pd
from IPython.display import SVG, display
import verovio
from music21 import chord, clef, meter, metadata, note, pitch, stream

__all__ = ['df_to_music21', 'music21_to_musicxml_string', 'render_with_verovio_from_musicxml']

def df_to_music21(
    df: pd.DataFrame,
    *,
    time_signature: str = '4/4',
    unit_quarter_length: float = 1.0,
    piece_title: Optional[str] = None,
    clef_config: str = 'G',           # 'G', 'F', 'GF', or 'AUTO'
    split_midi: int | None = 60,      # routing threshold for GF/AUTO: <= goes to bass, > to treble
    voices_per_stave: int = 2,
    enforce_accidentals: bool = False,
) -> stream.Score:
    """
    Convert a DataFrame with columns ['MIDI', 'Global Onset', 'Duration'] into a music21 Score.
    - unit_quarter_length: how many DataFrame time units equal one quarter note (default: 1.0)
    - piece_title: optional title to assign to the resulting score.
    - clef_config: explicit clef layout ('G', 'F', 'GF') or 'AUTO' to infer from pitch spread.
    - voices_per_stave: maximum number of independent voices that share the same stave.

    Polyphony: Notes that overlap in time are split into independent voices that
    keep their rhythmic continuity. Additional staves are created as needed when
    the voices-per-stave limit is exceeded; clefs for spillover staves are picked
    using each voice's average pitch relative to the split threshold. Notes with
    identical onset and duration are rendered as chords.
    - enforce_accidentals: force explicit accidentals on every pitch.
    """
    required_cols = {'MIDI', 'Global Onset', 'Duration'}
    if not required_cols.issubset(df.columns):
        raise ValueError(f"DataFrame must include columns {required_cols}")

    # Normalize and sort
    df2 = df.copy()
    df2['MIDI'] = df2['MIDI'].astype(int)
    df2['Global Onset'] = df2['Global Onset'].astype(float)
    df2['Duration'] = df2['Duration'].astype(float)
    df2 = df2.sort_values(['Global Onset', 'Duration', 'MIDI']).reset_index(drop=True)

    sc = stream.Score(id='Score')
    if piece_title:
        sc.metadata = metadata.Metadata()
        sc.metadata.title = piece_title

    eps = 1e-6
    total_length_ql = 0.0
    thr = 60 if split_midi is None else int(split_midi)
    max_voices_per_stave = max(1, int(voices_per_stave or 1))

    midi_values = df2['MIDI'].tolist()
    has_low = any(m <= thr for m in midi_values)
    has_high = any(m > thr for m in midi_values)

    cfg = (clef_config or 'G').upper()
    if cfg == 'AUTO':
        if has_low and has_high:
            cfg = 'GF'
        elif has_low:
            cfg = 'F'
        elif has_high:
            cfg = 'G'
        else:
            cfg = 'G'
    if cfg not in {'G', 'F', 'GF'}:
        cfg = 'G'

    if cfg == 'G':
        part_templates = [{'clef': 'G', 'label': 'Treble'}]
        route = lambda midi: 0
    elif cfg == 'F':
        part_templates = [{'clef': 'F', 'label': 'Bass'}]
        route = lambda midi: 0
    else:
        part_templates = [{'clef': 'G', 'label': 'Treble'}, {'clef': 'F', 'label': 'Bass'}]
        route = lambda midi, thr=thr: 1 if int(midi) <= thr else 0

    grouped_per_part = [dict() for _ in part_templates]

    def enforce_note_accidentals(target):
        if not enforce_accidentals:
            return

        def _ensure(note_obj):
            acc = note_obj.pitch.accidental
            if acc is None:
                acc = pitch.Accidental('natural')
                note_obj.pitch.accidental = acc
            acc.displayStatus = True

        if isinstance(target, chord.Chord):
            for n in target.notes:
                _ensure(n)
        else:
            _ensure(target)

    onset_idx = int(df2.columns.get_loc('Global Onset'))
    dur_idx = int(df2.columns.get_loc('Duration'))
    midi_idx = int(df2.columns.get_loc('MIDI'))

    for row in df2.itertuples(index=False, name=None):
        midi_val = int(row[midi_idx])
        part_idx = route(midi_val)
        onset_ql = float(row[onset_idx]) / float(unit_quarter_length)
        dur_ql = float(row[dur_idx]) / float(unit_quarter_length)
        end_ql = onset_ql + dur_ql
        total_length_ql = max(total_length_ql, end_ql)
        if dur_ql <= eps:
            continue
        key = (round(onset_ql, 9), round(dur_ql, 9))
        grouped_per_part[part_idx].setdefault(key, []).append(midi_val)

    def assign_voices(events):
        voices = []
        for ev in events:
            ev_pitch = sum(ev['midis']) / len(ev['midis'])
            candidates = []
            for idx, voice in enumerate(voices):
                if ev['onset'] >= voice['end'] - eps:
                    gap = ev['onset'] - voice['end']
                    pitch_diff = abs(ev_pitch - voice['avg_pitch'])
                    candidates.append((gap, pitch_diff, idx))
            if candidates:
                candidates.sort(key=lambda item: (item[0], item[1]))
                chosen = voices[candidates[0][2]]
                chosen['events'].append(ev)
                chosen['end'] = max(chosen['end'], ev['end'])
                chosen['sum_pitch'] += ev_pitch
                chosen['count'] += 1
                chosen['avg_pitch'] = chosen['sum_pitch'] / chosen['count']
                chosen['min_pitch'] = min(chosen['min_pitch'], min(ev['midis']))
                chosen['max_pitch'] = max(chosen['max_pitch'], max(ev['midis']))
            else:
                voices.append({
                    'events': [ev],
                    'end': ev['end'],
                    'sum_pitch': ev_pitch,
                    'count': 1,
                    'avg_pitch': ev_pitch,
                    'min_pitch': min(ev['midis']),
                    'max_pitch': max(ev['midis']),
                })
        return voices

    final_parts: list[stream.Part] = []

    def clef_for_voice(avg_pitch: float, default_clef: str, is_base_slot: bool) -> str:
        if is_base_slot:
            return default_clef
        return 'F' if avg_pitch <= thr else 'G'

    def make_part(slot_label: str, slot_index: int, clef_code: str, voices_in_slot: list[dict]):
        part_id = f"{slot_label}_{slot_index}".replace(' ', '_')
        prt = stream.Part(id=part_id)
        part_name = slot_label if slot_index == 1 else f"{slot_label} {slot_index}"
        prt.partName = part_name
        prt.insert(0, meter.TimeSignature(time_signature))
        if clef_code == 'F':
            prt.insert(0, clef.BassClef())
        else:
            prt.insert(0, clef.TrebleClef())

        voices_in_slot.sort(key=lambda v: v['avg_pitch'])
        voice_count = len(voices_in_slot)
        for local_idx, voice_data in enumerate(voices_in_slot, start=1):
            voice_number = local_idx
            stem_dir = None
            if voice_count == 2:
                stem_dir = 'down' if local_idx == 1 else 'up'
            events_sorted = sorted(voice_data['events'], key=lambda e: (e['onset'], -e['duration'], e['midis']))
            cursor = 0.0
            for ev in events_sorted:
                gap = ev['onset'] - cursor
                if gap > eps:
                    r = note.Rest()
                    r.duration.quarterLength = gap
                    r.voice = voice_number
                    prt.insert(cursor, r)
                    cursor = ev['onset']
                if len(ev['midis']) == 1:
                    obj = note.Note(ev['midis'][0])
                else:
                    obj = chord.Chord([int(m) for m in ev['midis']])
                obj.duration.quarterLength = ev['duration']
                enforce_note_accidentals(obj)
                if stem_dir:
                    obj.stemDirection = stem_dir
                obj.voice = voice_number
                prt.insert(ev['onset'], obj)
                cursor = max(cursor, ev['end'])
            tail_gap = total_length_ql - cursor
            if tail_gap > eps:
                r = note.Rest()
                r.duration.quarterLength = tail_gap
                r.voice = voice_number
                prt.insert(cursor, r)

        try:
            prt.makeMeasures(inPlace=True)
        except Exception:
            pass
        try:
            for meas in prt.recurse().getElementsByClass(stream.Measure):
                meas.makeVoices(inPlace=True)
        except Exception:
            pass

        final_parts.append(prt)

    def make_empty_part(template: dict, index: int = 1):
        part_id = f"{template['label']}_{index}".replace(' ', '_')
        prt = stream.Part(id=part_id)
        part_name = template['label'] if index == 1 else f"{template['label']} {index}"
        prt.partName = part_name
        prt.insert(0, meter.TimeSignature(time_signature))
        if template['clef'] == 'F':
            prt.insert(0, clef.BassClef())
        else:
            prt.insert(0, clef.TrebleClef())
        rest_length = total_length_ql if total_length_ql > eps else 4.0
        rest = note.Rest()
        rest.duration.quarterLength = rest_length
        rest.voice = 1
        prt.insert(0, rest)
        try:
            prt.makeMeasures(inPlace=True)
        except Exception:
            pass
        final_parts.append(prt)

    for template, grouped in zip(part_templates, grouped_per_part):
        events = []
        for (onset_ql, dur_ql), midis in grouped.items():
            midis_sorted = sorted(int(m) for m in midis)
            events.append({
                'onset': float(onset_ql),
                'duration': float(dur_ql),
                'end': float(onset_ql + dur_ql),
                'midis': midis_sorted,
            })
        events.sort(key=lambda e: (e['onset'], -e['duration'], e['midis']))
        voices = assign_voices(events)
        if not voices:
            make_empty_part(template)
            continue

        slot_list: list[dict] = []
        for voice in sorted(voices, key=lambda v: v['avg_pitch']):
            target_slot = None
            for slot in slot_list:
                if len(slot['voices']) < max_voices_per_stave:
                    target_slot = slot
                    break
            if target_slot is None:
                slot_index = len(slot_list) + 1
                clef_code = clef_for_voice(voice['avg_pitch'], template['clef'], slot_index == 1)
                target_slot = {
                    'label': template['label'],
                    'index': slot_index,
                    'clef': clef_code,
                    'voices': [],
                }
                slot_list.append(target_slot)
            target_slot['voices'].append(voice)

        for slot in slot_list:
            make_part(slot['label'], slot['index'], slot['clef'], slot['voices'])

    for prt in final_parts:
        sc.append(prt)

    try:
        sc.makeNotation(inPlace=True)
    except Exception:
        pass
    return sc

def music21_to_musicxml_string(s: stream.Score) -> str:
    from music21.musicxml.m21ToXml import GeneralObjectExporter
    exporter = GeneralObjectExporter(s)
    xml_bytes = exporter.parse()
    try:
        return xml_bytes.decode('utf-8')
    except AttributeError:
        return str(xml_bytes)



def render_with_verovio_from_musicxml(musicxml_str: str, *, scale: int = 55) -> tuple[str, list[str]]:
    """
    Render MusicXML with Verovio and display SVG pages in the notebook.
    Returns (mei_string, svg_pages)
    """
    tk = verovio.toolkit()
    tk.setInputFrom('musicxml')
    tk.setOptions({'scale': int(scale), 'adjustPageHeight': True})
    if not tk.loadData(musicxml_str):
        raise ValueError("Verovio could not load the MusicXML input.")
    if tk.getPageCount() == 0:
        raise ValueError("Verovio produced no pages from the MusicXML input.")
    mei_str = tk.getMEI()
    svg_pages = []
    for p in range(1, tk.getPageCount() + 1):
        svg_pages.append(tk.renderToSVG(p))
    for svg in svg_pages:
        display(SVG(svg))
    return mei_str, svg_pages


