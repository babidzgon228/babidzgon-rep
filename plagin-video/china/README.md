# Plagin — «Жизнь в Китае»

Озвучка ElevenLabs (2 файла) → распознавание слов (Vosk, `../asr.py`) → сцены по таймингам.
Пиксель-арт сглаживается xBR, фото накладываются в полном качестве, субтитры — libass.

- `voiceover_china.txt` — текст для озвучки
- `script_china.py` — 72 сцены + точки деления на части
- `art3.py` — новые сцены
- `photos/` — фото (кампус, небоскрёбы, храмы, море)
- `out/plagin_china_full.mp4` — полная версия 5:36 (TikTok)
- `out/plagin_china_part1..3.mp4` — части ≤ 3 мин (Reels / Shorts)

```bash
python3 build_china.py --vo a.mp3 b.mp3 --words out/words_a.json out/words_b.json --outdir out --parts
```
