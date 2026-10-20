from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.models import Category


def get_type_kb() -> InlineKeyboardMarkup:
    """Выбор типа: доход/расход"""
    builder = InlineKeyboardBuilder()
    builder.button(text="💚 Доход", callback_data="type:income")
    builder.button(text="❤️ Расход", callback_data="type:expense")
    builder.button(text="❌ Отмена", callback_data="tx:cancel")
    builder.adjust(2, 1)
    return builder.as_markup()


def get_categories_kb(
    categories: list[Category], 
    page: int = 0,
    per_page: int = 6
) -> InlineKeyboardMarkup:
    """
    Кнопки категорий с пагинацией.
    callback_data: "cat:<category_id>"
    """
    builder = InlineKeyboardBuilder()
    
    # Пагинация
    start = page * per_page
    end = start + per_page
    page_cats = categories[start:end]
    
    for cat in page_cats:
        builder.button(
            text=f"{cat.emoji} {cat.name}",
            callback_data=f"cat:{cat.id}"
        )
    
    # Раскладка по 2 в ряд
    builder.adjust(2)
    
    # Навигация
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"catpage:{page-1}"))
    if end < len(categories):
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"catpage:{page+1}"))
    
    if nav_row:
        builder.row(*nav_row)
    
    # Доп. кнопки
    builder.row(
        InlineKeyboardButton(text="➕ Своя категория", callback_data="cat:new"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="tx:cancel")
    )
    
    return builder.as_markup()


def get_confirm_kb(suggested: bool = False) -> InlineKeyboardMarkup:
    """
    Подтверждение транзакции.
    suggested=True → это предложение классификатора
    suggested=False → юзер выбрал категорию сам
    """
    builder = InlineKeyboardBuilder()
    
    if suggested:
        builder.button(text="✅ Да, верно", callback_data="confirm:yes")
        builder.button(text="✏️ Сменить", callback_data="confirm:change")
    else:
        builder.button(text="✅ Записать", callback_data="confirm:yes")
        builder.button(text="✏️ Сменить", callback_data="confirm:change")
    
    builder.button(text="❌ Отмена", callback_data="tx:cancel")
    builder.adjust(2, 1)
    return builder.as_markup()


def get_stats_period_kb() -> InlineKeyboardMarkup:
    """Выбор периода для статистики"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Сегодня", callback_data="stats:day")
    builder.button(text="📆 Неделя", callback_data="stats:week")
    builder.button(text="🗓 Месяц", callback_data="stats:month")
    builder.button(text="📊 Год", callback_data="stats:year")
    builder.button(text="❌ Закрыть", callback_data="stats:close")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_settings_kb(user_currency: str, user_timezone: str) -> InlineKeyboardMarkup:
    """Настройки"""
    builder = InlineKeyboardBuilder()
    builder.button(text="💱 Валюта", callback_data="settings:currency")
    builder.button(text="🕐 Часовой пояс", callback_data="settings:timezone")
    builder.button(text="📁 Категории", callback_data="settings:categories")
    builder.button(text="📥 Экспорт в Excel", callback_data="settings:export")
    builder.button(text="❌ Закрыть", callback_data="settings:close")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_currency_kb(current: str) -> InlineKeyboardMarkup:
    """Выбор валюты"""
    builder = InlineKeyboardBuilder()
    for cur, name in [("RUB", "₽ Рубль"), ("USD", "$ Доллар"), ("EUR", "€ Евро")]:
        mark = "✅ " if cur == current else ""
        builder.button(text=f"{mark}{name}", callback_data=f"setcurrency:{cur}")
    builder.button(text="◀️ Назад", callback_data="settings:back")
    builder.adjust(1)
    return builder.as_markup()