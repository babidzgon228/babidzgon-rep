# Бесплатный запуск бота 24/7

Уведомления приходят, только пока бот запущен, поэтому ему нужна машина, которая работает постоянно.
Ниже три бесплатных варианта, от простого к надёжному.

> Почему не Render, Railway или Koyeb: на бесплатных тарифах они «засыпают» без трафика
> и стирают диск при перезапуске. Напоминания будут теряться, а база данных — пропадать.

---

## Вариант 1. Свой ноутбук, старый компьютер или Android-телефон (проще всего)

Подойдёт любое устройство, которое можно не выключать.

**Если устройство в Китае**, Telegram там заблокирован. У тебя уже есть VPN-клиент (Clash, V2RayN, Shadowrocket и т. п.),
а у него обычно есть локальный прокси. Посмотри его порт в настройках клиента и впиши в `.env`:
```
TELEGRAM_PROXY=http://127.0.0.1:7890
```
(Для socks5 нужен ещё `pip install aiohttp-socks`, тогда пиши `socks5://127.0.0.1:1080`.)

**Windows / macOS / Linux:**
```bash
git clone https://github.com/babidzgon228/babidzgon-rep.git && cd babidzgon-rep
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # впиши токен и свой ID
python -m bot
```
Чтобы бот стартовал сам после перезагрузки: на Windows добавь `start_bot.bat` в «Автозагрузку»,
на macOS и Linux используй `crontab -e` → `@reboot cd ~/babidzgon-rep && .venv/bin/python -m bot`.

**Android (Termux, бесплатно из F-Droid):**
```bash
pkg install python git && git clone https://github.com/babidzgon228/babidzgon-rep.git
cd babidzgon-rep && pip install -r requirements.txt && cp .env.example .env && nano .env
termux-wake-lock && python -m bot
```

---

## Вариант 2. Oracle Cloud Always Free (самый мощный бесплатный сервер)

Сервер в Европе или Японии, поэтому прокси не нужен. Бесплатно навсегда: до 4 ядер ARM и 24 ГБ RAM,
этого хватит даже на распознавание голосовых.

1. Зарегистрируйся на [oracle.com/cloud/free](https://www.oracle.com/cloud/free/). Карта нужна только для проверки,
   деньги не списываются. Регион выбери вне Китая: Frankfurt, Amsterdam, Tokyo и т. п.
2. Create Instance → образ **Ubuntu 22.04**, форма **Ampere A1** (Always Free) → скачай SSH-ключ.
3. Подключись: `ssh -i key.pem ubuntu@<IP>` и выполни:
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker
git clone https://github.com/babidzgon228/babidzgon-rep.git && cd babidzgon-rep
cp .env.example .env && nano .env        # токен, ID, ключ Claude
docker compose up -d --build
docker compose logs -f                   # проверить, что бот запустился
```
Docker сам перезапустит бота после сбоя или перезагрузки сервера.

**Обновить бота** после новых изменений: `git pull && docker compose up -d --build`.

---

## Вариант 3. Google Cloud Free Tier (e2-micro)

Бесплатная VM на 1 ГБ RAM в регионах США (us-west1, us-central1, us-east1). Тоже нужна карта для проверки.
Установка такая же, как в варианте 2. Голосовые на 1 ГБ лучше не включать.

---

## Голосовые сообщения
```bash
pip install -r requirements-voice.txt     # без Docker
```
В Docker добавь в `Dockerfile` строку `RUN pip install faster-whisper`. Модель выбирается в `.env`
(`WHISPER_MODEL=base`, около 1 ГБ RAM; `tiny` легче, но ошибается чаще).

## Резервная копия
Вся информация хранится в одном файле `data/bot.db`. Копируй его время от времени
(в боте будет команда `/backup`: бот сам пришлёт тебе файл базы).
