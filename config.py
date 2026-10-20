import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")

# База данных
DATABASE_URL = f"sqlite+aiosqlite:///{BASE_DIR / 'expense_bot.db'}"

# Валюты
DEFAULT_CURRENCY = "RUB"
SUPPORTED_CURRENCIES = ["RUB", "USD", "EUR"]

# API для курсов валют
EXCHANGE_API_URL = "https://api.exchangerate-api.com/v4/latest/RUB"
EXCHANGE_CACHE_HOURS = 24

# Часовой пояс по умолчанию
DEFAULT_TIMEZONE = "Europe/Moscow"

# Excel
EXCEL_EXPORT_DIR = str(BASE_DIR / "exports")