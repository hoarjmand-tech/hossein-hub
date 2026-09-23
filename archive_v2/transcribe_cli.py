"""CLI adapter for local Persian speech-to-text. Prints transcript only."""
import os
import sys
from faster_whisper import WhisperModel

if len(sys.argv)!=2:
    raise SystemExit('usage: transcribe_cli.py AUDIO')

model=WhisperModel(os.getenv('WHISPER_MODEL','small'),device='cpu',compute_type='int8',download_root='/data/models/whisper')
segments,_=model.transcribe(sys.argv[1],language='fa',vad_filter=True,beam_size=5)
print(' '.join(segment.text.strip() for segment in segments if segment.text.strip()))
