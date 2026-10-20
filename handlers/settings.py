"""
Настройки бота.

Разделы:
- 💱 Валюта отображения (RUB/USD/EUR)
- 🕐 Часовой пояс (пресеты + свой)
- 📁 Категории (переход в handlers/categories.py)
"""

from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from keyboards.inline import get_settings_kb, get_currency_kb

router = Router()


# ============================================================================
# FSM СОСТОЯНИЯ
# ============================================================================

class SettingsForm(StatesGroup):
    viewing = State()              # просмотр настроек
    choosing_currency = State()    # выбор валюты
    choosing_timezone = State()    # выбор часового пояса
    entering_custom_timezone = State()  # ввод своего пояса


# ============================================================================
# ДАННЫЕ
# ============================================================================

# Популярные пояса: (IANA, отображаемое имя, UTC offset)
TIMEZONES = [
    ("Europe/Kaliningrad",  "🇷🇺 Калининград",      "UTC+2"),
    ("Europe/Moscow",       "🇷🇺 Москва",           "UTC+3"),
    ("Europe/Samara",       "🇷🇺 Самара",           "UTC+4"),
    ("Asia/Yekaterinburg",  "🇷🇺 Екатеринбург",     "UTC+5"),
    ("Asia/Omsk",           "🇷🇺 Омск",             "UTC+6"),
    ("Asia/Krasnoyarsk",    "🇷🇺 Красноярск",       "UTC+7"),
    ("Asia/Irkutsk",        "🇷🇺 Иркутск",          "UTC+8"),
    ("Asia/Yakutsk",        "🇷🇺 Якутск",           "UTC+9"),
    ("Asia/Vladivostok",    "🇷🇺 Владивосток",      "UTC+10"),
    ("Asia/Magadan",        "🇷🇺 Магадан",          "UTC+11"),
    ("Asia/Kamchatka",      "🇷🇺 Камчатка",         "UTC+12"),
    # Международные
    ("Europe/Kyiv",         "🇺🇦 Киев",             "UTC+2/+3"),
    ("Asia/Almaty",         "🇰🇿 Алматы",           "UTC+5"),
    ("Asia/Tbilisi",        "🇬🇪 Тбилиси",          "UTC+4"),
    ("Asia/Dubai",          "🇦🇪 Дубай",            "UTC+4"),
    ("Europe/Berlin",       "🇩🇪 Берлин",           "UTC+1/+2"),
    ("Europe/London",       "🇬🇧 Лондон",           "UTC+0/+1"),
    ("America/New_York",    "🇺🇸 Нью-Йорк",         "UTC-5/-4"),
]

CURRENCY_INFO = {
    "RUB": ("₽", "Рубль"),
    "USD": ("$", "Доллар"),
    "EUR": ("€", "Евро"),
}


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ
# ============================================================================

def build_settings_message(user: User) -> str:
    """Текст с текущими настройками."""
    symbol, name = CURRENCY_INFO.get(user.currency, ("?", user.currency))
    
    # Человекочитаемое имя пояса
    tz_display = user.timezone
    for iana, display, offset in TIMEZONES:
        if iana == user.timezone:
            tz_display = f"{display} ({offset})"
            break
    
    return (
        f"⚙️ <b>Настройки</b>\n\n"
        f"💱 Валюта: <b>{symbol} {name}</b>\n"
        f"🕐 Часовой пояс: <b>{tz_display}</b>\n\n"
        f"<i>Валюта влияет на отображение сумм в статистике и отчётах. "
        f"Все данные хранятся в рублях.</i>"
    )


def build_timezones_kb(current: str, page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    """Список часовых поясов с пагинацией."""
    builder = InlineKeyboardBuilder()
    
    start = page * per_page
    end = start + per_page
    page_items = TIMEZONES[start:end]
    
    for iana, display, offset in page_items:
        mark = "✅ " if iana == current else ""
        builder.button(
            text=f"{mark}{display}  ({offset})",
            callback_data=f"settz:{iana}"
        )
    builder.adjust(1)
    
    # Пагинация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"tzpage:{page-1}"))
    if end < len(TIMEZONES):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"tzpage:{page+1}"))
    if nav:
        builder.row(*nav)
    
    # Действия
    builder.row(
        InlineKeyboardButton(text="✏️ Свой пояс", callback_data="settz:custom"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="settings:back"),
    )
    
    return builder.as_markup()


def validate_timezone(tz_str: str) -> bool:
    """Проверка, что пояс существует."""
    try:
        import pytz
        pytz.timezone(tz_str)
        return True
    except Exception:
        return False


# ============================================================================
# ГЛАВНЫЙ ХЕНДЛЕР — РЕПЛАЙ-КНОПКА "⚙️ Настройки"
# ============================================================================

@router.message(F.text == "⚙️ Настройки")
async def on_settings_button(
    message: Message,
    state: FSMContext,
    user: User
):
    """Открытие настроек"""
    await state.set_state(SettingsForm.viewing)
    
    await message.answer(
        build_settings_message(user),
        reply_markup=get_settings_kb(user.currency, user.timezone),
        parse_mode="HTML"
    )


# ============================================================================
# НАВИГАЦИЯ
# ============================================================================

@router.callback_query(F.data == "settings:close")
async def on_close(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data == "settings:back")
async def on_back(
    cb: CallbackQuery,
    state: FSMContext,
    user: User
):
    """Возврат к главному меню настроек"""
    await state.set_state(SettingsForm.viewing)
    
    await cb.message.edit_text(
        build_settings_message(user),
        reply_markup=get_settings_kb(user.currency, user.timezone),
        parse_mode="HTML"
    )
    await cb.answer()


# ============================================================================
# ВАЛЮТА
# ============================================================================

@router.callback_query(F.data == "settings:currency")
async def on_currency_menu(
    cb: CallbackQuery,
    state: FSMContext,
    user: User
):
    """Меню выбора валюты"""
    await state.set_state(SettingsForm.choosing_currency)
    
    await cb.message.edit_text(
        "💱 <b>Валюта отображения</b>\n\n"
        "Все данные хранятся в рублях. Валюта влияет только на <b>отображение</b> сумм "
        "(конвертация по текущему курсу).",
        reply_markup=get_currency_kb(user.currency),
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(F.data.startswith("setcurrency:"))
async def on_currency_selected(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Сохраняем выбранную валюту"""
    new_currency = cb.data.split(":")[1]
    
    if new_currency not in CURRENCY_INFO:
        await cb.answer("❌ Неверная валюта", show_alert=True)
        return
    
    # Сохраняем
    user.currency = new_currency
    await session.commit()
    
    # Обновляем
    user = await session.get(User, user.user_id)  # refresh
    await state.set_state(SettingsForm.viewing)
    
    symbol, name = CURRENCY_INFO[new_currency]
    
    await cb.message.edit_text(
        f"✅ Валюта изменена на <b>{symbol} {name}</b>\n\n"
        + build_settings_message(user),
        reply_markup=get_settings_kb(user.currency, user.timezone),
        parse_mode="HTML"
    )
    await cb.answer(f"{symbol} {name}")


# ============================================================================
# ЧАСОВОЙ ПОЯС
# ============================================================================

@router.callback_query(F.data == "settings:timezone")
async def on_timezone_menu(
    cb: CallbackQuery,
    state: FSMContext,
    user: User
):
    """Меню выбора часового пояса"""
    await state.set_state(SettingsForm.choosing_timezone)
    
    await cb.message.edit_text(
        "🕐 <b>Часовой пояс</b>\n\n"
        "Выбери свой регион. Это влияет на:\n"
        "• Границы периодов (день/неделя/месяц/год)\n"
        "• Отображение дат и времени в отчётах",
        reply_markup=build_timezones_kb(user.timezone, page=0),
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(F.data.startswith("tzpage:"))
async def on_timezone_page(
    cb: CallbackQuery,
    state: FSMContext,
    user: User
):
    """Пагинация поясов"""
    page = int(cb.data.split(":")[1])
    await cb.message.edit_reply_markup(
        reply_markup=build_timezones_kb(user.timezone, page=page)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("settz:"))
async def on_timezone_selected(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Выбрали пояс из списка (или хотим ввести свой)"""
    value = cb.data.split(":", 1)[1]
    
    if value == "custom":
        await state.set_state(SettingsForm.entering_custom_timezone)
        await cb.message.edit_text(
            "✏️ Введи название часового пояса в формате IANA:\n\n"
            "Примеры:\n"
            "<code>Europe/Moscow</code>\n"
            "<code>Asia/Novosibirsk</code>\n"
            "<code>America/Los_Angeles</code>\n\n"
            "Полный список: <a href='https://en.wikipedia.org/wiki/List_of_tz_database_time_zones'>Wiki</a>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="settings:timezone")]
            ]),
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        await cb.answer()
        return
    
    # Проверяем валидность
    if not validate_timezone(value):
        await cb.answer("❌ Неверный часовой пояс", show_alert=True)
        return
    
    # Сохраняем
    user.timezone = value
    await session.commit()
    
    await state.set_state(SettingsForm.viewing)
    
    # Ищем человекочитаемое имя
    display = value
    for iana, name, offset in TIMEZONES:
        if iana == value:
            display = f"{name} ({offset})"
            break
    
    # Проверяем текущее локальное время
    import pytz
    try:
        tz = pytz.timezone(value)
        local_time = datetime.now(tz).strftime("%H:%M")
    except Exception:
        local_time = "?"
    
    user = await session.get(User, user.user_id)
    
    await cb.message.edit_text(
        f"✅ Часовой пояс изменён на\n"
        f"<b>{display}</b>\n"
        f"Текущее время: {local_time}\n\n"
        + build_settings_message(user),
        reply_markup=get_settings_kb(user.currency, user.timezone),
        parse_mode="HTML"
    )
    await cb.answer("✅ Сохранено")


@router.message(SettingsForm.entering_custom_timezone, F.text)
async def on_custom_timezone(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Пользователь ввёл свой часовой пояс текстом"""
    value = message.text.strip()
    
    if not validate_timezone(value):
        await message.answer(
            f"❌ Не могу найти часовой пояс «{value}».\n"
            f"Проверь формат: <code>Europe/Moscow</code>",
            parse_mode="HTML"
        )
        return
    
    user.timezone = value
    await session.commit()
    
    await state.set_state(SettingsForm.viewing)
    
    import pytz
    local_time = datetime.now(pytz.timezone(value)).strftime("%H:%M")
    
    user = await session.get(User, user.user_id)
    
    await message.answer(
        f"✅ Часовой пояс: <b>{value}</b>\n"
        f"Текущее время: {local_time}\n\n"
        + build_settings_message(user),
        reply_markup=get_settings_kb(user.currency, user.timezone),
        parse_mode="HTML"
    )