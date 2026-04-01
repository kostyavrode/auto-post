# Auto News Poster

Система автоматического парсинга новостей и публикации готовых постов в Telegram-канал.
Парсит RSS, обычные сайты и Telegram-каналы каждые 30 минут, переводит при необходимости,
генерирует посты через Deepseek AI по твоим примерам и публикует с картинкой.

---

## Содержание

1. [Подготовка токенов и ключей](#1-подготовка-токенов-и-ключей)
2. [Подготовка сервера](#2-подготовка-сервера)
3. [Загрузка проекта на сервер](#3-загрузка-проекта-на-сервер)
4. [Настройка .env](#4-настройка-env)
5. [Первый запуск](#5-первый-запуск)
6. [Авторизация Telethon](#6-авторизация-telethon-только-если-нужны-tg-каналы-как-источники)
7. [Добавление источников](#7-добавление-источников)
8. [Загрузка примеров постов](#8-загрузка-примеров-постов)
9. [Проверка работы](#9-проверка-работы)
10. [Управление через бота](#10-управление-через-бота)
11. [Обслуживание и обновление](#11-обслуживание-и-обновление)

---

## 1. Подготовка токенов и ключей

Перед деплоем нужно получить 5 значений. Лучше сделать это заранее и держать под рукой.

### Telegram Bot Token

1. Открыть Telegram, найти **@BotFather**
2. Написать `/newbot`
3. Ввести имя бота (например `My News Bot`)
4. Ввести username бота (например `my_news_123_bot`) — должен заканчиваться на `bot`
5. BotFather выдаст токен вида `7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

Сохранить — это `TELEGRAM_BOT_TOKEN`.

### ID своего Telegram-аккаунта

1. Найти в Telegram бота **@userinfobot**
2. Написать ему `/start`
3. Он ответит: `Id: 123456789`

Это `ADMIN_TELEGRAM_ID` — только с этого аккаунта бот будет принимать команды.

### ID канала для публикации

**Вариант А — username канала** (если канал публичный):
Просто взять `@your_channel_name` — это и есть ID.

**Вариант Б — числовой ID** (для приватных каналов):
1. Переслать любое сообщение из канала боту **@username_to_id_bot**
2. Он вернёт числовой ID вида `-1001234567890`

Это `TELEGRAM_CHANNEL_ID`.

### Telegram API ID и Hash (только если нужны TG-каналы как источники)

Нужны для чтения чужих Telegram-каналов через Telethon.
Если источники — только RSS и сайты, этот шаг можно пропустить.

1. Открыть [my.telegram.org/apps](https://my.telegram.org/apps) в браузере
2. Войти по номеру телефона
3. Нажать **Create application** (если нет приложения)
4. Заполнить любые данные (App title, Short name)
5. Скопировать **App api_id** (число) и **App api_hash** (строка)

Это `TELEGRAM_API_ID` и `TELEGRAM_API_HASH`.

### Deepseek API Key

1. Зарегистрироваться на [platform.deepseek.com](https://platform.deepseek.com)
2. Перейти в раздел **API Keys**
3. Нажать **Create new API key**
4. Скопировать ключ вида `sk-xxxxxxxxxxxxxxxxxxxxxxxx`

Это `DEEPSEEK_API_KEY`. На аккаунте должны быть средства (баланс).

---

## 2. Подготовка сервера

### Установка Docker

Подключиться к серверу по SSH:
```bash
ssh user@your-server-ip
```

Установить Docker одной командой:
```bash
curl -fsSL https://get.docker.com | sh
```

Добавить текущего пользователя в группу docker (чтобы не писать sudo):
```bash
sudo usermod -aG docker $USER
newgrp docker
```

Проверить, что Docker работает:
```bash
docker --version
docker compose version
```

Должно вывести версии без ошибок.

---

## 3. Загрузка проекта на сервер

### Вариант А — через Git (рекомендуется)

Если проект в Git-репозитории:
```bash
git clone https://github.com/your-username/auto-post.git /opt/auto-post
cd /opt/auto-post
```

### Вариант Б — через SCP (загрузка с локального компьютера)

На **локальном компьютере** (в папке с проектом):
```bash
scp -r . user@your-server-ip:/opt/auto-post
```

После загрузки подключиться к серверу и перейти в папку:
```bash
ssh user@your-server-ip
cd /opt/auto-post
```

### Вариант В — создать папку вручную

```bash
mkdir -p /opt/auto-post
cd /opt/auto-post
```

Затем создать все файлы вручную или скопировать через редактор.

---

## 4. Настройка .env

Перейти в папку проекта:
```bash
cd /opt/auto-post
```

Создать `.env` из шаблона:
```bash
cp .env.example .env
```

Открыть для редактирования:
```bash
nano .env
```

Файл выглядит так — нужно заменить все значения на свои:

```dotenv
TELEGRAM_BOT_TOKEN=7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHANNEL_ID=@your_channel_name
ADMIN_TELEGRAM_ID=123456789
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
TARGET_LANGUAGE=ru
```

Сохранить в nano: `Ctrl+O` → `Enter` → `Ctrl+X`.

> Если Telegram-каналы как источники не нужны — `TELEGRAM_API_ID` и
> `TELEGRAM_API_HASH` можно оставить пустыми, система просто пропустит этот режим.

---

## 5. Первый запуск

Запустить сборку и старт контейнера:
```bash
docker compose up -d --build
```

Флаг `-d` запускает в фоне. `--build` собирает образ.
Первый раз займёт 2–3 минуты (скачивание Python, установка библиотек).

Проверить, что контейнер запустился:
```bash
docker compose ps
```

Должно показать:
```
NAME         STATUS    PORTS
auto-post    running
```

Посмотреть логи в реальном времени:
```bash
docker compose logs -f
```

Нормальный вывод при старте:
```
[INFO] Initializing database…
[INFO] Starting scheduler (every 30 minutes)…
[INFO] Starting Telegram bot…
[INFO] Bot is polling.
```

Выйти из логов: `Ctrl+C` (контейнер продолжит работать).

---

## 6. Авторизация Telethon (только если нужны TG-каналы как источники)

Telethon требует одноразовой авторизации через номер телефона.
Это нужно сделать **один раз** — потом сессия сохраняется навсегда.

Остановить основной контейнер:
```bash
docker compose stop
```

Запустить интерактивную авторизацию:
```bash
docker compose run --rm auto-post python -c "
import asyncio, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from telethon import TelegramClient

async def main():
    client = TelegramClient(
        str(Path('data/telethon_session')),
        int(os.environ['TELEGRAM_API_ID']),
        os.environ['TELEGRAM_API_HASH']
    )
    await client.start()
    print('Authorized successfully!')
    await client.disconnect()

asyncio.run(main())
"
```

Процесс авторизации:
1. Введи номер телефона в международном формате: `+79001234567`
2. Telegram пришлёт код в приложение — введи его
3. Если включена двухфакторная аутентификация — введи пароль
4. Появится `Authorized successfully!`

Файл сессии сохранится в `data/telethon_session.session`.

Запустить основной контейнер обратно:
```bash
docker compose up -d
```

---

## 7. Добавление источников

### Через Telegram-бота (рекомендуется)

Открыть бота в Telegram (тот, что создал @BotFather) и написать:

**RSS-лента:**
```
/add_source https://feeds.bbci.co.uk/news/rss.xml BBC News
```

**Обычный сайт (без RSS):**
```
/add_source https://habr.com/ru/news/ Хабр
/add_source https://techcrunch.com TechCrunch
```
Система сама найдёт статьи и извлечёт текст — никаких дополнительных настроек.

**Telegram-канал как источник:**
```
/add_tg @rian_ru РИА Новости
/add_tg @bbcrussian BBC Русская служба
```

Проверить список источников:
```
/list_sources
```

### Через config/sources.yml

Открыть файл на сервере:
```bash
nano /opt/auto-post/config/sources.yml
```

Заполнить по примеру:
```yaml
sources:
  - name: "BBC News"
    type: rss
    url: "http://feeds.bbci.co.uk/news/rss.xml"
    enabled: true

  - name: "Хабр"
    type: scraper
    url: "https://habr.com/ru/news/"
    enabled: true
    max_articles: 10

  - name: "РИА Новости"
    type: telegram
    channel: "@rian_ru"
    enabled: true
```

Перезапустить контейнер для применения:
```bash
docker compose restart
```

> Источники из YAML импортируются один раз при первом старте.
> Для дальнейшего управления удобнее использовать бота.

---

## 8. Загрузка примеров постов

Примеры — это готовые посты в том стиле, который ты хочешь получать.
AI будет генерировать новые посты максимально похоже на них.

**Рекомендация:** загрузи 3–5 примеров для лучшего результата.

### Через бота

1. Написать боту: `/upload_example`
2. Следующим сообщением отправить текст примера поста

Например:
```
⚡️ Заголовок новости

Короткий пересказ самого важного — 2–3 предложения. Акцент на цифре или неожиданном факте.

Читать полностью →

#технологии #ии
```

Повторить для каждого примера. Посмотреть загруженные:
```
/list_examples
```

### Вручную на сервере

Создать файл прямо в папке `examples/`:
```bash
nano /opt/auto-post/examples/example_002.txt
```

Написать текст примера, сохранить (`Ctrl+O`, `Enter`, `Ctrl+X`).
Перезапуск не нужен — файлы читаются при каждой генерации.

---

## 9. Проверка работы

### Запустить первый цикл вручную (не ждать 30 минут)

Перезапустить контейнер — при старте сразу запускается первый цикл:
```bash
docker compose restart
```

Следить за логами:
```bash
docker compose logs -f
```

Нормальная работа выглядит так:
```
[INFO] Starting scheduled job…
[INFO] RSS BBC News: fetched 20 articles
[INFO] Auto-scraper Хабр: found 15 candidate links
[INFO] Auto-scraper Хабр: extracted 8 articles
[INFO] Queued article: https://habr.com/ru/articles/...
[INFO] Published post to @your_channel
[INFO] Scheduled job complete.
```

### Проверить статистику через бота

```
/status
```

Покажет:
```
Status: ✅ Running
Active sources: 3
Articles fetched: 24
Posts published: 5
Posts pending: 2
```

### Посмотреть очередь

```
/queue
```

---

## 10. Управление через бота

Все команды пишутся боту в **личные сообщения**.

| Команда | Описание |
|---|---|
| `/add_source <url> [название]` | Добавить RSS или сайт |
| `/add_tg <@канал> [название]` | Добавить Telegram-канал как источник |
| `/list_sources` | Список всех источников с ID |
| `/del_source <id>` | Удалить источник |
| `/toggle_source <id>` | Включить/выключить источник |
| `/upload_example` | Загрузить пример поста |
| `/list_examples` | Показать загруженные примеры |
| `/del_example <имя файла>` | Удалить пример |
| `/pause` | Приостановить публикацию |
| `/resume` | Возобновить публикацию |
| `/status` | Статистика системы |
| `/queue` | Первые 5 постов в очереди |

---

## 11. Обслуживание и обновление

### Просмотр логов

```bash
# Последние 100 строк
docker compose logs --tail=100

# В реальном времени
docker compose logs -f

# Только ошибки
docker compose logs | grep ERROR
```

### Перезапуск

```bash
docker compose restart
```

### Остановка и запуск

```bash
docker compose stop
docker compose start
```

### Обновление кода (если используешь Git)

```bash
cd /opt/auto-post
git pull
docker compose up -d --build
```

### Резервная копия данных

Все данные хранятся в папке `data/` и `examples/`. Для бэкапа достаточно скопировать их:

```bash
# Создать архив
tar -czf backup-$(date +%Y%m%d).tar.gz /opt/auto-post/data /opt/auto-post/examples

# Скопировать на локальный компьютер
scp user@your-server-ip:~/backup-*.tar.gz ./
```

### Просмотр базы данных вручную

```bash
docker compose exec auto-post sqlite3 data/db.sqlite3

# Полезные SQL-запросы:
.tables
SELECT * FROM sources;
SELECT COUNT(*) FROM articles;
SELECT * FROM posts WHERE status='pending' LIMIT 5;
.quit
```

### Если контейнер падает — посмотреть причину

```bash
docker compose logs --tail=50
```

Частые причины:
- `KeyError: 'TELEGRAM_BOT_TOKEN'` — не заполнен `.env`
- `Unauthorized` — неверный токен бота
- `Chat not found` — бот не добавлен в канал как администратор

---

## Структура файлов на сервере

```
/opt/auto-post/
├── .env                  ← секреты (не коммитить!)
├── config/
│   ├── settings.yml      ← настройки интервала, лимитов, модели
│   └── sources.yml       ← источники (можно редактировать)
├── examples/
│   ├── example_001.txt   ← примеры стиля постов
│   └── example_002.txt
└── data/
    ├── db.sqlite3               ← база данных
    ├── images/                  ← скачанные картинки
    └── telethon_session.session ← сессия Telegram (если используется)
```

Папки `data/` и `examples/` — это Docker volumes. Они **не удаляются** при пересборке образа.
