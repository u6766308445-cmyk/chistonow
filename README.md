# Chistonow

Telegram-бот и мини-приложение для заказа химчистки мягкой мебели
(Петроградский район, Крестовский и Каменный острова, Петровская коса).

- `bot.py` — бот на aiogram 3
- `docs/index.html` — мини-приложение (публикуется через GitHub Pages)

## Запуск

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # заполните BOT_TOKEN, ADMIN_CHAT_ID, WEBAPP_URL
python bot.py
```

Токен бота хранится только в `.env`, этот файл в репозиторий не попадает.
