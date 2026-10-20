"""
Обработчик управления лимитами.

Показывает список лимитов, позволяет добавлять/редактировать/удалять.
Всё через пошаговый FSM (кнопки + ввод текста).
"""

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User, Category
from database.queries import (
    get_categories,
    get_category_by_id,
    get_limits,
    get_limit_for_category,
    add_limit,
    update_limit,
    delete_limit,
    get_category_total,
    get_period_bounds,
)
from services.currency import format_money
from services.classifier import parse_amount

router = Router()


# ============================================================================
# FSM СОСТОЯНИЯ
# ============================================================================

class LimitForm(StatesGroup):
    choosing_action = State()          # смотрим список / выбрали действие
    choosing_category = State()        # выбор категории для нового лимита
    choosing_period = State()          # выбор периода
    entering_amount = State()          # ввод суммы
    entering_alert_percent = State()   # ввод порога (кнопки + custom)
    editing_field = State()            # редактирование лимита (сумма/alert/период)
    confirming_delete = State()        # подтверждение удаления


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ
# ============================================================================

PERIOD_LABELS = {
    "day": "📅 День",
    "week": "📆 Неделя",
    "month": "🗓 Месяц",
    "year": "📊 Год",
}

PERIOD_LABELS_SHORT = {
    "day": "дн.",
    "week": "нед.",
    "month": "мес.",
    "year": "год",
}


async def build_limits_message(
    session: AsyncSession,
    user: User
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Строит сообщение со списком всех активных лимитов.
    Для каждого лимита показывает прогресс-бар.
    """
    limits = await get_limits(session, user.user_id, is_active_only=True)
    
    if not limits:
        text = (
            "💰 <b>Лимиты</b>\n\n"
            "У тебя пока нет лимитов.\n"
            "Добавь — и я буду предупреждать, когда тратишь много."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить лимит", callback_data="lim:add")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="lim:close")],
        ])
        return text, kb
    
    lines = ["💰 <b>Твои лимиты</b>", ""]
    builder = InlineKeyboardBuilder()
    
    for i, limit in enumerate(limits):
        # Получаем категорию
        cat = limit.category
        
        # Считаем сколько уже потрачено за текущий период лимита
        start, end = await get_period_bounds(session, user.user_id, limit.period)
        spent = await get_category_total(
            session, user.user_id, limit.category_id, start, end
        )
        
        # Прогресс-бар
        percent = min(spent / limit.max_amount * 100, 100) if limit.max_amount > 0 else 0
        
        # Визуальный прогресс-бар (10 сегментов)
        filled = int(percent / 10)
        if percent > 100:
            bar = "🟥" * 10  # превышен
        elif percent >= (100 - limit.alert_percent):
            bar = "🟨" * filled + "⬜" * (10 - filled)  # предупреждение
        else:
            bar = "🟩" * filled + "⬜" * (10 - filled)  # ок
        
        lines.append(
            f"{cat.emoji} <b>{cat.name}</b> — "
            f"{format_money(limit.max_amount)}/{PERIOD_LABELS_SHORT[limit.period]}"
        )
        lines.append(
            f"{bar} {format_money(spent)} ({percent:.0f}%)"
        )
        lines.append("")
        
        # Кнопки для этого лимита
        builder.row(
            InlineKeyboardButton(
                text=f"✏️ {cat.emoji} {cat.name}",
                callback_data=f"lim:edit:{limit.id}"
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"lim:del:{limit.id}"
            )
        )
    
    # Общие кнопки
    builder.row(
        InlineKeyboardButton(text="➕ Добавить лимит", callback_data="lim:add"),
        InlineKeyboardButton(text="❌ Закрыть", callback_data="lim:close"),
    )
    
    return "\n".join(lines), builder.as_markup()


def get_expense_categories_kb(categories: list[Category]) -> InlineKeyboardMarkup:
    """Кнопки выбора категории (только расходы, по 2 в ряд, без пагинации для лимитов)."""
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.button(
            text=f"{cat.emoji} {cat.name}",
            callback_data=f"limcat:{cat.id}"
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="lim:cancel")
    )
    return builder.as_markup()


def get_period_kb() -> InlineKeyboardMarkup:
    """Выбор периода"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 День", callback_data="limperiod:day")
    builder.button(text="📆 Неделя", callback_data="limperiod:week")
    builder.button(text="🗓 Месяц", callback_data="limperiod:month")
    builder.button(text="📊 Год", callback_data="limperiod:year")
    builder.button(text="❌ Отмена", callback_data="lim:cancel")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def get_alert_percent_kb() -> InlineKeyboardMarkup:
    """Выбор порога уведомления"""
    builder = InlineKeyboardBuilder()
    for pct in [15, 20, 25, 30]:
        builder.button(text=f"{pct}%", callback_data=f"limalert:{pct}")
    builder.button(text="✏️ Свой", callback_data="limalert:custom")
    builder.button(text="❌ Отмена", callback_data="lim:cancel")
    builder.adjust(4, 1, 1)
    return builder.as_markup()


def get_edit_kb(limit_id: int) -> InlineKeyboardMarkup:
    """Редактирование лимита"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Изменить сумму", callback_data=f"limedit:amount:{limit_id}")],
        [InlineKeyboardButton(text="📅 Изменить период", callback_data=f"limedit:period:{limit_id}")],
        [InlineKeyboardButton(text="🔔 Изменить порог", callback_data=f"limedit:alert:{limit_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="lim:back")],
    ])


def get_delete_confirm_kb(limit_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"limdel:yes:{limit_id}"),
            InlineKeyboardButton(text="◀️ Отмена", callback_data="lim:back"),
        ]
    ])


# ============================================================================
# ГЛАВНЫЙ ХЕНДЛЕР — РЕПЛАЙ-КНОПКА "💰 Лимиты"
# ============================================================================

@router.message(F.text == "💰 Лимиты")
async def on_limits_button(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Показываем список лимитов"""
    await state.clear()
    text, kb = await build_limits_message(session, user)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# ============================================================================
# ОБЩИЕ CALLBACK: закрыть / назад / отмена
# ============================================================================

@router.callback_query(F.data == "lim:close")
async def on_close(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data == "lim:back")
async def on_back(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Возврат к списку лимитов"""
    await state.clear()
    text, kb = await build_limits_message(session, user)
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "lim:cancel")
async def on_cancel(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Отмена действия → возврат к списку"""
    await state.clear()
    text, kb = await build_limits_message(session, user)
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer("Отменено")


# ============================================================================
# ДОБАВЛЕНИЕ НОВОГО ЛИМИТА
# ============================================================================

@router.callback_query(F.data == "lim:add")
async def on_add_limit(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Шаг 1: выбор категории"""
    # Только расходы — лимиты на доходы смысла не имеют
    categories = await get_categories(session, user.user_id, type="expense")
    
    if not categories:
        await cb.answer("❌ Нет категорий расходов", show_alert=True)
        return
    
    # Убираем "Другое" — лимит на неё бессмыслен
    categories = [c for c in categories if c.name != "Другое"]
    
    if not categories:
        await cb.answer("❌ Нет подходящих категорий", show_alert=True)
        return
    
    await state.set_state(LimitForm.choosing_category)
    
    await cb.message.edit_text(
        "💰 <b>Новый лимит</b>\n\n"
        "Шаг 1/4: выбери категорию",
        reply_markup=get_expense_categories_kb(categories),
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(LimitForm.choosing_category, F.data.startswith("limcat:"))
async def on_category_chosen(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Шаг 2: выбор периода"""
    category_id = int(cb.data.split(":")[1])
    category = await get_category_by_id(session, category_id)
    
    if not category:
        await cb.answer("❌ Категория не найдена", show_alert=True)
        return
    
    await state.update_data(
        category_id=category.id,
        category_name=category.name,
        category_emoji=category.emoji,
    )
    await state.set_state(LimitForm.choosing_period)
    
    await cb.message.edit_text(
        f"💰 Новый лимит\n"
        f"{category.emoji} <b>{category.name}</b>\n\n"
        f"Шаг 2/4: за какой период?",
        reply_markup=get_period_kb(),
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(LimitForm.choosing_period, F.data.startswith("limperiod:"))
async def on_period_chosen(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Шаг 3: ввод суммы"""
    period = cb.data.split(":")[1]
    if period not in ("day", "week", "month", "year"):
        await cb.answer("❌ Неверный период", show_alert=True)
        return
    
    await state.update_data(period=period)
    await state.set_state(LimitForm.entering_amount)
    
    data = await state.get_data()
    
    await cb.message.edit_text(
        f"💰 Новый лимит\n"
        f"{data['category_emoji']} <b>{data['category_name']}</b> — "
        f"{PERIOD_LABELS[period]}\n\n"
        f"Шаг 3/4: введи сумму лимита\n"
        f"Например: <code>5000</code>",
        parse_mode="HTML"
    )
    await cb.answer()


@router.message(LimitForm.entering_amount, F.text)
async def on_amount_entered(
    message: Message,
    state: FSMContext,
    user: User
):
    """Получили сумму → шаг 4 (порог уведомления)"""
    amount = parse_amount(message.text)
    
    if not amount:
        await message.answer(
            "🤔 Не могу разобрать сумму. Попробуй: <code>5000</code>",
            parse_mode="HTML"
        )
        return
    
    if amount < 1:
        await message.answer("❌ Сумма должна быть больше 0")
        return
    
    await state.update_data(max_amount=amount)
    await state.set_state(LimitForm.entering_alert_percent)
    
    data = await state.get_data()
    
    await message.answer(
        f"💰 Новый лимит\n"
        f"{data['category_emoji']} <b>{data['category_name']}</b> — "
        f"{format_money(amount)}/{PERIOD_LABELS_SHORT[data['period']]}\n\n"
        f"Шаг 4/4: за сколько % до лимита предупредить?\n"
        f"<i>(по умолчанию: 20%)</i>",
        reply_markup=get_alert_percent_kb(),
        parse_mode="HTML"
    )


@router.callback_query(LimitForm.entering_alert_percent, F.data.startswith("limalert:"))
async def on_alert_chosen(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Финал: сохраняем лимит"""
    value = cb.data.split(":")[1]
    
    if value == "custom":
        # Ждём ввод кастомного значения
        await cb.message.edit_text(
            "Введи процент (5–50):\n"
            "Например: <code>25</code>",
            parse_mode="HTML"
        )
        await cb.answer()
        return  # остаёмся в том же состоянии
    
    try:
        alert_percent = int(value)
    except ValueError:
        await cb.answer("❌ Неверное значение", show_alert=True)
        return
    
    await save_limit(cb, state, session, user, alert_percent)


@router.message(LimitForm.entering_alert_percent, F.text)
async def on_custom_alert(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Кастомный ввод процента"""
    text = message.text.strip()
    try:
        alert_percent = int(text)
    except ValueError:
        await message.answer("❌ Введи целое число, например 20")
        return
    
    if not 5 <= alert_percent <= 50:
        await message.answer("❌ Процент должен быть от 5 до 50")
        return
    
    await save_limit(message, state, session, user, alert_percent, is_message=True)


async def save_limit(
    target,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    alert_percent: int,
    is_message: bool = False
):
    """
    Сохраняет лимит в БД.
    target — Message или CallbackQuery
    """
    data = await state.get_data()
    
    # Проверяем, нет ли уже лимита на эту категорию+период
    existing = await get_limit_for_category(
        session, user.user_id, data["category_id"], data["period"]
    )
    
    if existing:
        # Обновляем
        await update_limit(
            session, existing.id,
            max_amount=data["max_amount"],
            alert_percent=alert_percent,
            is_active=True,
        )
        action = "обновлён"
    else:
        # Создаём новый
        await add_limit(
            session,
            user_id=user.user_id,
            category_id=data["category_id"],
            period=data["period"],
            max_amount=data["max_amount"],
            alert_percent=alert_percent,
        )
        action = "создан"
    
    await state.clear()
    
    # Формируем ответ
    text = (
        f"✅ <b>Лимит {action}!</b>\n\n"
        f"{data['category_emoji']} <b>{data['category_name']}</b>\n"
        f"💰 {format_money(data['max_amount'])} / {PERIOD_LABELS[data['period']]}\n"
        f"🔔 Предупреждение за {alert_percent}% до конца"
    )
    
    # Показываем обновлённый список
    limits_text, limits_kb = await build_limits_message(session, user)
    
    if is_message:
        await target.answer(text, parse_mode="HTML")
        await target.answer(limits_text, reply_markup=limits_kb, parse_mode="HTML")
    else:
        await target.message.edit_text(text, parse_mode="HTML")
        await target.message.answer(limits_text, reply_markup=limits_kb, parse_mode="HTML")
        await target.answer("✅ Готово")


# ============================================================================
# РЕДАКТИРОВАНИЕ ЛИМИТА
# ============================================================================

@router.callback_query(F.data.startswith("lim:edit:"))
async def on_edit_limit(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Показываем меню редактирования"""
    limit_id = int(cb.data.split(":")[2])
    
    # Загружаем лимит
    limits = await get_limits(session, user.user_id, is_active_only=False)
    limit = next((l for l in limits if l.id == limit_id), None)
    
    if not limit:
        await cb.answer("❌ Лимит не найден", show_alert=True)
        return
    
    cat = limit.category
    
    await state.set_state(LimitForm.editing_field)
    
    await cb.message.edit_text(
        f"✏️ <b>Редактирование лимита</b>\n\n"
        f"{cat.emoji} <b>{cat.name}</b>\n"
        f"💰 {format_money(limit.max_amount)} / {PERIOD_LABELS[limit.period]}\n"
        f"🔔 Предупреждение за {limit.alert_percent}%\n\n"
        f"Что изменить?",
        reply_markup=get_edit_kb(limit_id),
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(LimitForm.editing_field, F.data.startswith("limedit:"))
async def on_edit_field(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Выбрали что редактировать"""
    parts = cb.data.split(":")
    field = parts[1]
    limit_id = int(parts[2])
    
    await state.update_data(editing_limit_id=limit_id, editing_field=field)
    
    if field == "amount":
        await cb.message.edit_text(
            "💰 Введи новую сумму лимита:",
            parse_mode="HTML"
        )
        await cb.answer()
        return
    
    if field == "period":
        await cb.message.edit_text(
            "📅 Выбери новый период:",
            reply_markup=get_period_kb().model_copy(
                update={"inline_keyboard": [
                    [InlineKeyboardButton(text="📅 День", callback_data=f"limeditp:day:{limit_id}")],
                    [InlineKeyboardButton(text="📆 Неделя", callback_data=f"limeditp:week:{limit_id}")],
                    [InlineKeyboardButton(text="🗓 Месяц", callback_data=f"limeditp:month:{limit_id}")],
                    [InlineKeyboardButton(text="📊 Год", callback_data=f"limeditp:year:{limit_id}")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data=f"lim:edit:{limit_id}")],
                ]}
            ),
            parse_mode="HTML"
        )
        await cb.answer()
        return
    
    if field == "alert":
        await cb.message.edit_text(
            "🔔 Выбери новый порог уведомления:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="15%", callback_data=f"limedita:15:{limit_id}"),
                    InlineKeyboardButton(text="20%", callback_data=f"limedita:20:{limit_id}"),
                    InlineKeyboardButton(text="25%", callback_data=f"limedita:25:{limit_id}"),
                ],
                [
                    InlineKeyboardButton(text="30%", callback_data=f"limedita:30:{limit_id}"),
                    InlineKeyboardButton(text="◀️ Назад", callback_data=f"lim:edit:{limit_id}"),
                ],
            ]),
            parse_mode="HTML"
        )
        await cb.answer()
        return


@router.message(LimitForm.editing_field, F.text)
async def on_edit_amount_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Ввод новой суммы при редактировании"""
    data = await state.get_data()
    
    if data.get("editing_field") != "amount":
        return
    
    amount = parse_amount(message.text)
    if not amount:
        await message.answer("🤔 Не могу разобрать сумму. Попробуй: <code>5000</code>")
        return
    
    limit_id = data["editing_limit_id"]
    await update_limit(session, limit_id, max_amount=amount)
    
    await state.clear()
    
    await message.answer(f"✅ Сумма лимита изменена на {format_money(amount)}")
    
    # Показываем обновлённый список
    limits_text, limits_kb = await build_limits_message(session, user)
    await message.answer(limits_text, reply_markup=limits_kb, parse_mode="HTML")


@router.callback_query(LimitForm.editing_field, F.data.startswith("limeditp:"))
async def on_edit_period_value(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Выбрали новый период при редактировании"""
    parts = cb.data.split(":")
    period = parts[1]
    limit_id = int(parts[2])
    
    await update_limit(session, limit_id, period=period)
    await state.clear()
    
    limits_text, limits_kb = await build_limits_message(session, user)
    await cb.message.edit_text(limits_text, reply_markup=limits_kb, parse_mode="HTML")
    await cb.answer(f"✅ Период: {PERIOD_LABELS[period]}")


@router.callback_query(LimitForm.editing_field, F.data.startswith("limedita:"))
async def on_edit_alert_value(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Выбрали новый порог при редактировании"""
    parts = cb.data.split(":")
    alert_percent = int(parts[1])
    limit_id = int(parts[2])
    
    await update_limit(session, limit_id, alert_percent=alert_percent)
    await state.clear()
    
    limits_text, limits_kb = await build_limits_message(session, user)
    await cb.message.edit_text(limits_text, reply_markup=limits_kb, parse_mode="HTML")
    await cb.answer(f"✅ Порог: {alert_percent}%")


# ============================================================================
# УДАЛЕНИЕ ЛИМИТА
# ============================================================================

@router.callback_query(F.data.startswith("lim:del:"))
async def on_delete_limit(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Подтверждение удаления"""
    limit_id = int(cb.data.split(":")[2])
    
    limits = await get_limits(session, user.user_id, is_active_only=False)
    limit = next((l for l in limits if l.id == limit_id), None)
    
    if not limit:
        await cb.answer("❌ Лимит не найден", show_alert=True)
        return
    
    await state.set_state(LimitForm.confirming_delete)
    await state.update_data(deleting_limit_id=limit_id)
    
    cat = limit.category
    
    await cb.message.edit_text(
        f"🗑 <b>Удалить лимит?</b>\n\n"
        f"{cat.emoji} <b>{cat.name}</b> — "
        f"{format_money(limit.max_amount)}/{PERIOD_LABELS_SHORT[limit.period]}\n\n"
        f"Транзакции не пострадают, только лимит исчезнет.",
        reply_markup=get_delete_confirm_kb(limit_id),
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(LimitForm.confirming_delete, F.data.startswith("limdel:yes:"))
async def on_delete_confirm(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Удаляем лимит"""
    limit_id = int(cb.data.split(":")[2])
    
    await delete_limit(session, limit_id)
    await state.clear()
    
    limits_text, limits_kb = await build_limits_message(session, user)
    await cb.message.edit_text(limits_text, reply_markup=limits_kb, parse_mode="HTML")
    await cb.answer("🗑 Лимит удалён")