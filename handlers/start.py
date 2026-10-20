from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from keyboards.reply import get_main_menu
from database.models import User

router = Router()


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    session: AsyncSession,
    user: User  # ← из UserMiddleware
):
    """Приветствие + главное меню"""
    
    text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Я бот для учёта доходов и расходов.\n\n"
        f"<b>Что я умею:</b>\n"
        f"➕ Записывать доходы и расходы\n"
        f"📊 Показывать статистику (день/неделя/месяц/год)\n"
        f"💰 Следить за лимитами по категориям\n"
        f"💱 Конвертировать в $ и €\n"
        f"📥 Выгружать в Excel с графиками\n\n"
        f"<b>Как быстро внести трату:</b>\n"
        f"Просто напиши сумму и что это, например:\n"
        f"<code>450 фастфуд</code>\n"
        f"<code>1200 продукты</code>\n"
        f"<code>50000 зарплата</code>\n\n"
        f"Или жми <b>➕ Внести</b> внизу 👇"
    )
    
    await message.answer(text, reply_markup=get_main_menu(), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Справка по командам"""
    text = (
        "<b>📖 Помощь</b>\n\n"
        "<b>Быстрый ввод:</b>\n"
        "• <code>450 фастфуд</code> — расход\n"
        "• <code>+50000 зарплата</code> — доход (плюс вначале)\n\n"
        "<b>Кнопки:</b>\n"
        "• ➕ Внести — пошаговый ввод\n"
        "• 📊 Статистика — отчёты по периодам\n"
        "• 💰 Лимиты — настроить лимиты\n"
        "• ⚙️ Настройки — валюта, категории, экспорт\n"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu())