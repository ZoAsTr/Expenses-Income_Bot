"""
Обработчик статистики.

Показывает сводку за период: доход, расход, баланс + топ-5 категорий.
Кнопки: Сегодня / Неделя / Месяц / Год + По категориям + Экспорт.
"""

from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from database.queries import (
    get_period_bounds,
    get_totals,
    get_by_category,
    get_daily_trend,
    count_transactions,
)
from services.currency import convert_from_rub, format_money, get_rate_rub
from keyboards.inline import get_stats_period_kb

router = Router()


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ
# ============================================================================

PERIOD_LABELS = {
    "day": "📅 Сегодня",
    "week": "📆 Последние 7 дней",
    "month": "🗓 Этот месяц",
    "year": "📊 Этот год",
}


def format_period_dates(start: datetime, end: datetime, period: str) -> str:
    """Форматирует даты периода для заголовка."""
    # end - эксклюзивный, поэтому показываем end - 1 день
    if period == "day":
        return start.strftime("%d.%m.%Y")
    if period == "week":
        from datetime import timedelta
        real_end = end - timedelta(days=1)
        return f"{start.strftime('%d.%m')} — {real_end.strftime('%d.%m.%Y')}"
    if period == "month":
        return start.strftime("%B %Y").capitalize()
    if period == "year":
        return start.strftime("%Y")
    return ""


async def build_summary(
    session: AsyncSession,
    user: User,
    period: str
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Строит текст статистики за период.
    Возвращает (текст, клавиатура).
    """
    # Границы периода в UTC
    start, end = await get_period_bounds(session, user.user_id, period)
    
    # Сводка
    totals = await get_totals(session, user.user_id, start, end)
    
    # Топ категорий расходов
    expense_by_cat = await get_by_category(session, user.user_id, start, end, "expense")
    
    # Количество транзакций
    tx_count = await count_transactions(session, user.user_id, start, end)
    
    # Курс для конвертации (если валюта не RUB)
    display_currency = user.currency
    rate = None
    if display_currency != "RUB":
        rate = await get_rate_rub(session, display_currency)
    
    async def fmt(amount_rub: float) -> str:
        """Конвертирует и форматирует сумму в валюту отображения."""
        if display_currency == "RUB" or not rate:
            return format_money(amount_rub, "RUB")
        converted = amount_rub / rate
        return format_money(converted, display_currency)
    
    # Заголовок
    period_label = PERIOD_LABELS.get(period, period)
    dates = format_period_dates(start, end, period)
    
    lines = [
        f"<b>{period_label}</b>",
        f"<i>{dates}</i>",
        "",
        f"💚 Доход: <b>{await fmt(totals['income'])}</b>",
        f"❤️ Расход: <b>{await fmt(totals['expense'])}</b>",
    ]
    
    # Баланс с плюсом/минусом
    balance = totals["balance"]
    if balance > 0:
        balance_line = f"💰 Баланс: <b>+{await fmt(balance)}</b>"
    elif balance < 0:
        balance_line = f"💰 Баланс: <b>{await fmt(balance)}</b>"
    else:
        balance_line = f"💰 Баланс: <b>{await fmt(0)}</b>"
    lines.append(balance_line)
    
    # Топ категорий
    if expense_by_cat:
        lines.append("")
        lines.append("🔝 <b>Топ расходов:</b>")
        
        top = expense_by_cat[:5]
        total_expense = totals["expense"] or 1.0  # защита от деления на 0
        
        for cat in top:
            percent = cat["total"] / total_expense * 100
            lines.append(
                f"{cat['emoji']} {cat['name']} — {await fmt(cat['total'])} "
                f"<i>({percent:.0f}%)</i>"
            )
        
        # Если категорий больше 5
        if len(expense_by_cat) > 5:
            remaining = len(expense_by_cat) - 5
            lines.append(f"<i>...и ещё {remaining} категорий</i>")
    else:
        lines.append("")
        lines.append("<i>Пока нет расходов за этот период.</i>")
    
    if tx_count == 0:
        lines.append("")
        lines.append("<i>Всего транзакций: 0</i>")
    
    text = "\n".join(lines)
    
    # Клавиатура
    builder = InlineKeyboardBuilder()
    
    # Переключение периода
    period_row = []
    for p, label in [("day", "📅"), ("week", "📆"), ("month", "🗓"), ("year", "📊")]:
        mark = "✅" if p == period else ""
        period_row.append(InlineKeyboardButton(
            text=f"{mark}{label}",
            callback_data=f"stats:{p}"
        ))
    builder.row(*period_row)
    
    # Действия
    if expense_by_cat:
        builder.row(
            InlineKeyboardButton(text="📋 Все категории", callback_data=f"stats:all:{period}"),
            InlineKeyboardButton(text="📥 Excel", callback_data=f"stats:excel:{period}"),
        )
    
    # Смена валюты отображения
    currency_buttons = []
    for cur, label in [("RUB", "₽"), ("USD", "$"), ("EUR", "€")]:
        mark = "✅ " if cur == display_currency else ""
        currency_buttons.append(InlineKeyboardButton(
            text=f"{mark}{label}",
            callback_data=f"stats:cur:{cur}"
        ))
    builder.row(*currency_buttons)
    
    builder.row(InlineKeyboardButton(text="❌ Закрыть", callback_data="stats:close"))
    
    return text, builder.as_markup()


# ============================================================================
# ХЕНДЛЕРЫ
# ============================================================================

@router.message(F.text == "📊 Статистика")
async def on_stats_button(
    message: Message,
    session: AsyncSession,
    user: User
):
    """Нажали "📊 Статистика" → показываем за текущий месяц"""
    text, kb = await build_summary(session, user, "month")
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("stats:"))
async def on_stats_callback(
    cb: CallbackQuery,
    session: AsyncSession,
    user: User
):
    """Обработка всех callback'ов статистики"""
    parts = cb.data.split(":")
    action = parts[1]
    
    if action == "close":
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.answer()
        return
    
    if action == "cur":
        # Смена валюты отображения
        new_currency = parts[2]
        user.currency = new_currency
        await session.commit()
        
        # Перерисовываем текущий вид (по умолчанию — month)
        text, kb = await build_summary(session, user, "month")
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await cb.answer(f"Валюта: {new_currency}")
        return
    
    if action == "all":
        # Полный список категорий
        period = parts[2]
        await show_all_categories(cb, session, user, period)
        return
    
    if action == "excel":
        # Экспорт в Excel
        period = parts[2]
        await cb.answer("⏳ Генерирую Excel...")
        await export_to_excel(cb, session, user, period)
        return
    
    # Иначе — это выбор периода (day/week/month/year)
    period = action
    if period not in ("day", "week", "month", "year"):
        await cb.answer("❌ Неверный период", show_alert=True)
        return
    
    text, kb = await build_summary(session, user, period)
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


async def show_all_categories(
    cb: CallbackQuery,
    session: AsyncSession,
    user: User,
    period: str
):
    """Показывает ВСЕ категории расходов за период."""
    start, end = await get_period_bounds(session, user.user_id, period)
    expense_by_cat = await get_by_category(session, user.user_id, start, end, "expense")
    totals = await get_totals(session, user.user_id, start, end)
    
    if not expense_by_cat:
        await cb.answer("Нет данных за этот период", show_alert=True)
        return
    
    total_expense = totals["expense"] or 1.0
    
    lines = [
        f"<b>{PERIOD_LABELS.get(period, period)}</b>",
        f"<i>Все расходы по категориям</i>",
        "",
    ]
    
    for i, cat in enumerate(expense_by_cat, 1):
        percent = cat["total"] / total_expense * 100
        lines.append(
            f"{i}. {cat['emoji']} {cat['name']} — "
            f"{format_money(cat['total'])} ({percent:.0f}%)"
        )
    
    lines.append("")
    lines.append(f"<b>Итого: {format_money(totals['expense'])}</b>")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"stats:{period}")]
    ])
    
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=kb,
        parse_mode="HTML"
    )
    await cb.answer()


async def export_to_excel(
    cb: CallbackQuery,
    session: AsyncSession,
    user: User,
    period: str
):
    """
    Экспорт статистики в Excel.
    TODO: реализация в services/excel_generator.py (следующий шаг)
    """
    from services.excel_generator import generate_excel_report
    
    start, end = await get_period_bounds(session, user.user_id, period)
    
    try:
        file_path = await generate_excel_report(
            session, user, start, end, period
        )
        
        from aiogram.types import FSInputFile
        document = FSInputFile(file_path)
        
        await cb.message.answer_document(
            document,
            caption=f"📊 Отчёт: {PERIOD_LABELS.get(period, period)}"
        )
    except Exception as e:
        await cb.message.answer(f"❌ Ошибка генерации Excel: {e}")