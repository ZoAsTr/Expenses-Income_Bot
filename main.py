"""
Точка входа бота.

Собирает:
- Bot + Dispatcher
- Middlewares (DB, User)
- Все роутеры
- Фоновые задачи (APScheduler)
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

from config import BOT_TOKEN
from database.db import init_db
from middlewares.db import DbSessionMiddleware
from middlewares.user import UserMiddleware

# Роутеры
from handlers import start, transactions, stats, limits, categories, settings

# Планировщик
from scheduler.tasks import setup_scheduler


# ============================================================================
# ЛОГИРОВАНИЕ
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================================

async def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не задан. Создайте файл .env рядом с main.py "
            "и добавьте строку BOT_TOKEN=ваш_токен."
        )

    # 1. Инициализация БД
    await init_db()
    logger.info("✅ БД инициализирована")
    
    # 2. Бот
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    
    # 3. Диспетчер (in-memory FSM — переживёт рестарт? нет, потеряет состояния)
    dp = Dispatcher(storage=MemoryStorage())
    
    # 4. Middlewares (порядок важен!)
    dp.message.middleware(DbSessionMiddleware())
    dp.message.middleware(UserMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(UserMiddleware())
    
    # 5. Роутеры (порядок важен!)
    #    1. Команды
    dp.include_router(start.router)
    #    2. Reply-кнопки + транзакции
    dp.include_router(transactions.router)
    #    3. Статистика
    dp.include_router(stats.router)
    #    4. Лимиты
    dp.include_router(limits.router)
    #    5. Категории (обрабатывает callback "settings:categories")
    dp.include_router(categories.router)
    #    6. Настройки
    dp.include_router(settings.router)
    
    # 6. Планировщик
    scheduler = AsyncIOScheduler(timezone=pytz.UTC)
    setup_scheduler(scheduler, bot)
    scheduler.start()
    logger.info("✅ Планировщик запущен (3 задачи)")
    
    # 7. Запуск polling
    logger.info("🚀 Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("👋 Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Прервано")