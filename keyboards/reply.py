from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu() -> ReplyKeyboardMarkup:
    """Главное меню — всегда внизу"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Внести"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="💰 Лимиты"), KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Введи сумму или выбери действие..."
    )