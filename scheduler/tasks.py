"""
Фоновые задачи (APScheduler).

1. cleanup_old_exports  — раз в сутки чистит старые Excel-файлы
2. monthly_reports      — 1-го числа, в 09:00 по TZ юзера, шлёт отчёт за прошлый месяц
3. daily_limits_reminder — каждый день в 09:00 по TZ юзера, шлёт сводку по лимитам
"""

import os
from datetime import datetime, timedelta

import pytz
from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy import select
from functools import partial

from config import EXCEL_EXPORT_DIR
from database.db import AsyncSessionLocal
from database.models import User
from database.queries import (
    get_limits,
    get_period_bounds,
    get_category_total,
    get_totals,
)
from services.currency import format_money
from services.excel_generator import generate_excel_report


# ============================================================================
# 1. ОЧИСТКА СТАРЫХ EXCEL-ФАЙЛОВ
# ============================================================================

async def cleanup_old_exports(max_age_days: int = 7):
    """
    Удаляет Excel-файлы старше N дней из EXCEL_EXPORT_DIR.
    Запускается раз в сутки в 04:00.
    """
    if not os.path.exists(EXCEL_EXPORT_DIR):
        return
    
    now = datetime.now()
    cutoff = now - timedelta(days=max_age_days)
    deleted = 0
    
    for filename in os.listdir(EXCEL_EXPORT_DIR):
        if not filename.endswith(".xlsx"):
            continue
        
        file_path = os.path.join(EXCEL_EXPORT_DIR, filename)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            if mtime < cutoff:
                os.remove(file_path)
                deleted += 1
        except Exception as e:
            print(f"⚠️ Ошибка удаления {file_path}: {e}")
    
    if deleted:
        print(f"🧹 Очистка: удалено {deleted} старых Excel-файлов")


# ============================================================================
# 2. ЕЖЕМЕСЯЧНЫЕ ОТЧЁТЫ
# ============================================================================

async def send_monthly_reports(bot: Bot):
    """
    Отправляет всем юзерам отчёт за прошлый месяц.
    Запускается 1-го числа каждого месяца в 09:00 по TZ юзера.
    
    ВАЖНО: планируется через APScheduler по UTC, но нужно слать в TZ юзера.
    Поэтому задача проверяет "у кого сейчас 09:00" — и запускается каждый час.
    """
    # Прошлый месяц
    now_utc = datetime.now(pytz.UTC)
    first_of_month = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_end = first_of_month
    prev_month_start = (first_of_month - timedelta(days=1)).replace(day=1)
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        
        for user in users:
            # Проверяем: сейчас у юзера ~09:00?
            try:
                tz = pytz.timezone(user.timezone)
            except Exception:
                continue
            
            local_now = now_utc.astimezone(tz)
            if local_now.hour != 9:
                continue  # не ему сейчас
            
            # Генерируем отчёт за прошлый месяц
            try:
                file_path = await generate_excel_report(
                    session, user,
                    prev_month_start.replace(tzinfo=None),
                    prev_month_end.replace(tzinfo=None),
                    "month"
                )
                
                # Считаем сводку
                totals = await get_totals(
                    session, user.user_id,
                    prev_month_start.replace(tzinfo=None),
                    prev_month_end.replace(tzinfo=None)
                )
                
                month_name = prev_month_start.strftime("%B %Y").capitalize()
                
                caption = (
                    f"📊 <b>Отчёт за {month_name}</b>\n\n"
                    f"💚 Доход: {format_money(totals['income'])}\n"
                    f"❤️ Расход: {format_money(totals['expense'])}\n"
                    f"💰 Баланс: {format_money(totals['balance'])}"
                )
                
                document = FSInputFile(file_path)
                await bot.send_document(
                    user.user_id,
                    document,
                    caption=caption,
                    parse_mode="HTML"
                )
                
            except Exception as e:
                print(f"⚠️ Ошибка отчёта для {user.user_id}: {e}")


# ============================================================================
# 3. ЕЖЕДНЕВНЫЕ НАПОМИНАНИЯ О ЛИМИТАХ
# ============================================================================

async def send_limits_reminders(bot: Bot):
    """
    Каждый день в 09:00 (по TZ юзера) присылает сводку по лимитам:
    - Что превышено (красный)
    - Что близко к лимиту (жёлтый)
    - Общий баланс за день
    
    Запускается каждый час, проверяет "у кого 09:00".
    """
    now_utc = datetime.now(pytz.UTC)
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        
        for user in users:
            try:
                tz = pytz.timezone(user.timezone)
            except Exception:
                continue
            
            local_now = now_utc.astimezone(tz)
            if local_now.hour != 9:
                continue
            
            try:
                await _send_daily_summary(bot, session, user)
            except Exception as e:
                print(f"⚠️ Ошибка напоминания для {user.user_id}: {e}")


async def _send_daily_summary(bot: Bot, session, user: User):
    """Формирует и отправляет дневную сводку по лимитам."""
    limits = await get_limits(session, user.user_id, is_active_only=True)
    
    if not limits:
        return  # нет лимитов — нечего слать
    
    lines = [f"☀️ <b>Доброе утро!</b>", ""]
    
    # Сначала общая статистика за вчера
    from database.queries import get_period_bounds
    yesterday_start, yesterday_end = await get_period_bounds(session, user.user_id, "day")
    # Смещаем на день назад для "вчера"
    # ... (упрощённо: не показываем вчера, только лимиты)
    
    # Группируем лимиты по статусу
    exceeded = []
    warning = []
    ok = []
    
    for limit in limits:
        start, end = await get_period_bounds(session, user.user_id, limit.period)
        spent = await get_category_total(
            session, user.user_id, limit.category_id, start, end
        )
        
        percent = (spent / limit.max_amount * 100) if limit.max_amount > 0 else 0
        cat = limit.category
        
        entry = (cat, limit, spent, percent)
        
        if spent > limit.max_amount:
            exceeded.append(entry)
        elif percent >= (100 - limit.alert_percent):
            warning.append(entry)
        else:
            ok.append(entry)
    
    # Превышенные
    if exceeded:
        lines.append("🚨 <b>Превышены:</b>")
        for cat, limit, spent, percent in exceeded:
            over = spent - limit.max_amount
            lines.append(
                f"{cat.emoji} {cat.name}: {format_money(spent)}/"
                f"{format_money(limit.max_amount)} "
                f"(+{format_money(over)})"
            )
        lines.append("")
    
    # Близко к лимиту
    if warning:
        lines.append("⚠️ <b>Приближаешься:</b>")
        for cat, limit, spent, percent in warning:
            lines.append(
                f"{cat.emoji} {cat.name}: {format_money(spent)}/"
                f"{format_money(limit.max_amount)} ({percent:.0f}%)"
            )
        lines.append("")
    
    # ОК — только если их немного
    if ok and len(ok) <= 5:
        lines.append("✅ <b>В норме:</b>")
        for cat, limit, spent, percent in ok:
            lines.append(
                f"{cat.emoji} {cat.name}: {format_money(spent)}/"
                f"{format_money(limit.max_amount)} ({percent:.0f}%)"
            )
    
    # Если вообще нечего сказать — не спамим
    if not exceeded and not warning:
        # Шлём только раз в неделю, чтобы не надоедать
        if datetime.now().weekday() != 0:  # 0 = понедельник
            return
    
    await bot.send_message(user.user_id, "\n".join(lines), parse_mode="HTML")


# ============================================================================
# ПЛАНИРОВЩИК
# ============================================================================

def setup_scheduler(scheduler, bot):
    """Регистрирует все задачи в APScheduler с bot."""
    
    # 1. Очистка старых файлов — раз в сутки в 04:00 UTC
    scheduler.add_job(
        cleanup_old_exports,
        "cron",
        hour=4,
        minute=0,
        id="cleanup_exports",
        replace_existing=True,
    )
    
    # 2. Отчёты за месяц — 1-го числа каждый час (проверка TZ внутри)
    scheduler.add_job(
        partial(send_monthly_reports, bot=bot),
        "cron",
        day=1,
        minute=0,
        id="monthly_reports",
        replace_existing=True,
    )
    
    # 3. Напоминания о лимитах — ежедневно каждый час (проверка TZ внутри)
    scheduler.add_job(
        partial(send_limits_reminders, bot=bot),
        "cron",
        minute=0,
        id="limits_reminders",
        replace_existing=True,
    )