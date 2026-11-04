# -*- coding: utf-8 -*-
"""Распознавание озвучки с таймингами слов (Vosk, vosk-model-small-ru-0.22).

    ffmpeg -i voice.mp3 -ac 1 -ar 16000 -f s16le voice16.raw
    python3 asr.py /path/vosk-model-small-ru-0.22 voice16.raw words.json
"""
import json, sys
from vosk import Model, KaldiRecognizer, SetLogLevel
SetLogLevel(-1)
m = Model(sys.argv[1]); r = KaldiRecognizer(m, 16000); r.SetWords(True)
words = []
with open(sys.argv[2], "rb") as f:
    while True:
        b = f.read(16000)
        if not b: break
        if r.AcceptWaveform(b):
            words += json.loads(r.Result()).get("result", [])
words += json.loads(r.FinalResult()).get("result", [])
json.dump(words, open(sys.argv[3], "w"), ensure_ascii=False)
print(len(words))
