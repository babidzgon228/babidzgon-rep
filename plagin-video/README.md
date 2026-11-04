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
