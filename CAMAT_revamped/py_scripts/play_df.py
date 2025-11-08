from music21 import stream, note, tempo

def play_dataframe(df, bpm=120):
    """
    Play dataframe with proper polyphony and tempo.
    
    df: DataFrame with 'MIDI', 'Global Onset', 'Duration', and 'Voice' columns
    bpm: tempo in beats per minute
    """
    score = stream.Score()
    
    # Set tempo
    # score.insert(0, tempo.MetronomeMark(number=bpm))
    
    # Group by voice
    voices = df['Voice'].unique()
    
    for voice_name in voices:
        voice_df = df[df['Voice'] == voice_name].sort_values('Global Onset')
        part = stream.Part()
        part.partName = voice_name
        
        for _, row in voice_df.iterrows():
            midi_num = int(row['MIDI'])
            onset = float(row['Global Onset'])
            duration = float(row['Duration'])
            
            n = note.Note()
            n.pitch.midi = midi_num
            n.quarterLength = duration
            
            part.insert(onset, n)  # Use insert instead of append
        
        score.append(part)
    
    score.show('midi')
