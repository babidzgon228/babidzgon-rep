# Plagin — пиксель-ролик про студента и ИИ-агентов

Вертикальное видео 1080x1920, ~68 сек, для TikTok / Reels / Shorts.
Пиксель-арт рисуется кодом, озвучка — локальный нейро-синтез Piper (русский мужской голос),
музыка и звуки тоже генерируются кодом (без чужих треков, без проблем с авторскими правами).

- `script.py` — сценарий: сцены, реплики озвучки, субтитры (мат в субтитрах со звёздочкой)
- `art.py` — пиксель-арт: Плагин, агенты-кубики, все сцены
- `audio.py` — озвучка, lo-fi музыка, звуковые эффекты
- `build.py` — сборка в mp4
- `out/plagin.mp4` — готовый ролик
- `out/voice_*.mp3` — пробы голосов (ruslan — в ролике, dmitri, denis)

## Сборка

```bash
pip install piper-tts numpy pillow
python3 build.py --voice /path/to/ru_RU-ruslan-medium.onnx --out out/plagin.mp4
```

Модель голоса (`ru_RU-ruslan-medium.onnx` + `.onnx.json`) — из набора голосов Piper (rhasspy/piper-voices).
Чтобы поменять текст — правь `script.py`; длительность сцен подстраивается под озвучку автоматически.

## Своя озвучка (ElevenLabs и т.п.)

Текст для озвучки — `voiceover.txt` (30 реплик, через пустую строку).

```bash
# один общий файл — нарезается по паузам между репликами автоматически
python3 build.py --vo elevenlabs.mp3 --out out/plagin.mp4

# или папка с отдельными файлами 01.mp3 ... 30.mp3 (по одному на реплику)
python3 build.py --vo vo_dir/ --out out/plagin.mp4
```

## Длинная версия (4.5 мин) под озвучку ElevenLabs

- `script_long.py` — 77 сцен и текст озвучки (восстановлен распознаванием речи)
- `art2.py` — новые сцены: препод, декан, робот-пылесос, будильник в галстуке, коты, суд и т.д.
- `asr.py` — распознавание озвучки с таймингами слов (Vosk, `vosk-model-small-ru-0.22`)
- `build_long.py` — выравнивает текст по распознанным словам, режет субтитры и собирает видео
- `out/plagin_long.mp4` — готовый ролик

```bash
ffmpeg -i voice.mp3 -ac 1 -ar 16000 -f s16le voice16.raw
python3 asr.py /path/vosk-model-small-ru-0.22 voice16.raw words.json
python3 build_long.py --vo voice.mp3 --words words.json --out out/plagin_long.mp4
```

## Две части по ≤ 3 мин (Reels / Shorts)

```bash
python3 build_parts.py --vo voice.mp3 --words words.json --split agent_pointer --outdir out
```

- `out/plagin_part1.mp4` — 2:04, заканчивается на «Староста, бл*дь!» + заставка «Продолжение в части 2»
- `out/plagin_part2.mp4` — 2:34, начинается с заставки «Часть 2»
