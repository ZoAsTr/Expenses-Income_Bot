"""
Проверка лимитов при добавлении транзакции.

ВАЖНО: у каждого лимита свой период (день/неделя/месяц/год).
Поэтому для каждой транзакции проверяем ВСЕ активные лимиты категории,
для каждого считаем границы его периода отдельно.
"""

from database.queries import (
    get_limits,
    get_period_bounds,
    get_category_total,
)
from services.currency import format_money


async def check_and_format(
    session,
    user_id: int,
    category_id: int,
    amount_to_add: float,
) -> str | None:
    """
    Проверяет ВСЕ активные лимиты для категории.
    Возвращает форматированное предупреждение или None.
    
    Например, если у Фастфуда лимит "5000/месяц" — считаем траты за текущий месяц.
    Если ещё есть "500/день" — считаем траты за сегодня отдельно.
    """
    # Все активные лимиты для этой категории
    all_limits = await get_limits(session, user_id, is_active_only=True)
    category_limits = [l for l in all_limits if l.category_id == category_id]
    
    if not category_limits:
        return None
    
    warnings = []
    
    for limit in category_limits:
        # Границы ИМЕННО ЭТОГО периода
        start, end = await get_period_bounds(session, user_id, limit.period)
        
        # Траты до и после
        spent_before = await get_category_total(
            session, user_id, category_id, start, end
        )
        spent_after = spent_before + amount_to_add
        percent_after = (spent_after / limit.max_amount * 100) if limit.max_amount > 0 else 0
        
        # Статус
        if spent_after > limit.max_amount:
            status = "exceeded"
        elif percent_after >= (100 - limit.alert_percent):
            status = "warning"
        else:
            status = "ok"
        
        if status == "ok":
            continue
        
        period_labels = {
            "day": "за день",
            "week": "за неделю",
            "month": "за месяц",
            "year": "за год",
        }
        period_label = period_labels.get(limit.period, limit.period)
        
        if status == "exceeded":
            over = spent_after - limit.max_amount
            warnings.append(
                f"\n\n🚨 <b>Лимит превышен!</b> ({period_label})\n"
                f"Лимит: {format_money(limit.max_amount)}\n"
                f"Потрачено: {format_money(spent_after)}\n"
                f"Перерасход: <b>{format_money(over)}</b>"
            )
        elif status == "warning":
            remaining = limit.max_amount - spent_after
            warnings.append(
                f"\n\n⚠️ <b>Приближаешься к лимиту</b> ({period_label})\n"
                f"Потрачено: {format_money(spent_after)} "
                f"из {format_money(limit.max_amount)} "
                f"({percent_after:.0f}%)\n"
                f"Осталось: <b>{format_money(remaining)}</b>"
            )
    
    if not warnings:
        return None
    
    return "".join(warnings)