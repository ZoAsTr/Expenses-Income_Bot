"""
Управление категориями (полный CRUD).

Возможности:
- Просмотр категорий (доходы / расходы отдельно)
- Создание новых
- Переименование
- Смена эмодзи
- Скрытие / показ
- Удаление (только если нет транзакций)
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
    add_custom_category,
    update_category,
    hide_category,
    delete_category,
    count_transactions,
)
from keyboards.inline import get_type_kb

router = Router()


# ============================================================================
# FSM СОСТОЯНИЯ
# ============================================================================

class CategoryForm(StatesGroup):
    viewing_list = State()           # просмотр списка
    choosing_type = State()          # выбор типа при создании
    entering_name = State()          # ввод имени
    choosing_emoji = State()         # выбор эмодзи (пресеты)
    entering_custom_emoji = State()  # ввод своего эмодзи
    renaming = State()               # переименование
    changing_emoji = State()         # смена эмодзи
    confirming_delete = State()      # подтверждение удаления


# ============================================================================
# ПРЕСЕТЫ ЭМОДЗИ (по темам)
# ============================================================================

EMOJI_PRESETS = {
    "popular": [
        "🍔", "🍕", "🚕", "🏠", "💊", "🎮", "👕", "📱",
        "📚", "🎁", "✈️", "🐾", "💡", "🏋️", "💰", "💼",
        "📈", "🎀", "❓", "📌",
    ],
    "food": [
        "🍔", "🍕", "🍜", "🍣", "🍱", "🥗", "🍰", "☕",
        "🍺", "🍷", "🥤", "🍫", "🥐", "🍳",
    ],
    "transport": [
        "🚕", "🚌", "🚇", "🚗", "⛽", "🛵", "🚲", "✈️",
        "🚆", "⛵",
    ],
    "home": [
        "🏠", "💡", "🔧", "🧺", "🛋️", "🪑", "🚿", "🧹",
        "🪑", "🛏️",
    ],
    "health": [
        "💊", "🏥", "🩺", "💉", "🦷", "👓", "🧘", "🏋️",
    ],
    "fun": [
        "🎮", "🎬", "🎵", "🎨", "🎭", "🍿", "🎪", "🎯",
    ],
    "money": [
        "💰", "💵", "💳", "💼", "📈", "🏦", "💎", "🪙",
    ],
}


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

async def build_categories_message(
    session: AsyncSession,
    user: User,
    show_hidden: bool = False
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Строит сообщение со списком всех категорий.
    Разбито на два блока: доходы и расходы.
    """
    # Загружаем всё (включая скрытые, если надо)
    all_categories = await get_categories(
        session, user.user_id, include_hidden=show_hidden
    )
    
    income_cats = [c for c in all_categories if c.type == "income"]
    expense_cats = [c for c in all_categories if c.type == "expense"]
    
    # Загружаем скрытые отдельно (чтобы показывать кнопку "Показать скрытые")
    hidden_all = await get_categories(session, user.user_id, include_hidden=True)
    hidden_count = sum(1 for c in hidden_all if c.is_hidden)
    
    lines = ["📁 <b>Категории</b>", ""]
    
    lines.append(f"<b>💚 Доходы ({len(income_cats)})</b>")
    if income_cats:
        for cat in income_cats:
            lines.append(f"  {cat.emoji} {cat.name}")
    else:
        lines.append("  <i>нет категорий</i>")
    
    lines.append("")
    lines.append(f"<b>❤️ Расходы ({len(expense_cats)})</b>")
    if expense_cats:
        for cat in expense_cats:
            lines.append(f"  {cat.emoji} {cat.name}")
    else:
        lines.append("  <i>нет категорий</i>")
    
    if hidden_count > 0 and not show_hidden:
        lines.append("")
        lines.append(f"<i>🙈 Скрытых категорий: {hidden_count}</i>")
    
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="➕ Создать", callback_data="cat:create"),
    )
    
    builder.row(
        InlineKeyboardButton(text="✏️ Доходы", callback_data="cat:manage:income"),
        InlineKeyboardButton(text="✏️ Расходы", callback_data="cat:manage:expense"),
    )
    
    if hidden_count > 0:
        toggle_text = "🙈 Скрыть" if show_hidden else "👁 Показать скрытые"
        builder.row(
            InlineKeyboardButton(
                text=toggle_text,
                callback_data=f"cat:viewhidden:{0 if show_hidden else 1}"
            )
        )
    
    builder.row(
        InlineKeyboardButton(text="❌ Закрыть", callback_data="cat:close")
    )
    
    return "\n".join(lines), builder.as_markup()


def build_category_list_kb(categories: list[Category]) -> InlineKeyboardMarkup:
    """Список категорий для управления (по одной в ряд, с эмодзи)."""
    builder = InlineKeyboardBuilder()
    for cat in categories:
        mark = "🙈 " if cat.is_hidden else ""
        builder.button(
            text=f"{mark}{cat.emoji} {cat.name}",
            callback_data=f"cat:view:{cat.id}"
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="cat:back")
    )
    return builder.as_markup()


def build_category_edit_kb(cat: Category, has_transactions: bool) -> InlineKeyboardMarkup:
    """Меню действий с категорией."""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"cat:rename:{cat.id}"),
        InlineKeyboardButton(text="🎨 Эмодзи", callback_data=f"cat:emoji:{cat.id}"),
    )
    
    # Скрытие / показ
    hide_text = "👁 Показать" if cat.is_hidden else "🙈 Скрыть"
    builder.row(
        InlineKeyboardButton(text=hide_text, callback_data=f"cat:hide:{cat.id}")
    )
    
    # Удаление — только если нет транзакций
    if not has_transactions:
        builder.row(
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"cat:delete:{cat.id}")
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text="🗑 Удалить (есть транзакции)",
                callback_data=f"cat:deleteblocked:{cat.id}"
            )
        )
    
    # Кнопка "назад" куда? В зависимости от типа
    builder.row(
        InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"cat:manage:{cat.type}"
        )
    )
    
    return builder.as_markup()


def build_emoji_picker(
    category_id: int,
    theme: str = "popular"
) -> InlineKeyboardMarkup:
    """Сетка эмодзи по теме."""
    builder = InlineKeyboardBuilder()
    
    emojis = EMOJI_PRESETS.get(theme, EMOJI_PRESETS["popular"])
    
    # Определяем callback prefix в зависимости от контекста:
    # "ccemoji:" для создания, "edemoji:" для редактирования
    prefix = "edemoji" if category_id else "ccemoji"
    
    for emoji in emojis:
        builder.button(
            text=emoji,
            callback_data=f"{prefix}:{category_id or 0}:{emoji}"
        )
    builder.adjust(5)  # по 5 в ряд
    
    # Темы
    theme_buttons = [
        ("Популярные", "popular"),
        ("🍔 Еда", "food"),
        ("🚕 Транспорт", "transport"),
        ("🏠 Дом", "home"),
        ("💊 Здоровье", "health"),
        ("🎮 Развлечения", "fun"),
        ("💰 Деньги", "money"),
    ]
    
    theme_row1 = [
        InlineKeyboardButton(text="Популярные", callback_data=f"cctheme:{category_id or 0}:popular"),
        InlineKeyboardButton(text="🍔 Еда", callback_data=f"cctheme:{category_id or 0}:food"),
        InlineKeyboardButton(text="🚕 Транспорт", callback_data=f"cctheme:{category_id or 0}:transport"),
    ]
    theme_row2 = [
        InlineKeyboardButton(text="🏠 Дом", callback_data=f"cctheme:{category_id or 0}:home"),
        InlineKeyboardButton(text="💊 Здоровье", callback_data=f"cctheme:{category_id or 0}:health"),
        InlineKeyboardButton(text="🎮 Развлечения", callback_data=f"cctheme:{category_id or 0}:fun"),
    ]
    theme_row3 = [
        InlineKeyboardButton(text="💰 Деньги", callback_data=f"cctheme:{category_id or 0}:money"),
        InlineKeyboardButton(text="✏️ Свой", callback_data=f"{prefix}:custom:{category_id or 0}"),
    ]
    
    builder.row(*theme_row1)
    builder.row(*theme_row2)
    builder.row(*theme_row3)
    
    # Отмена/назад
    if category_id:
        builder.row(
            InlineKeyboardButton(text="◀️ Назад", callback_data=f"cat:view:{category_id}")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="⏭ Без эмодзи", callback_data="ccemoji:skip:0"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cat:cancel"),
        )
    
    return builder.as_markup()


# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

@router.callback_query(F.data == "settings:categories")
async def on_open_categories(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Открытие меню категорий из настроек"""
    await state.clear()
    await state.set_state(CategoryForm.viewing_list)
    
    text, kb = await build_categories_message(session, user)
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "cat:back")
async def on_back_to_list(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Возврат к общему списку"""
    await state.set_state(CategoryForm.viewing_list)
    text, kb = await build_categories_message(session, user)
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "cat:close")
async def on_close(
    cb: CallbackQuery,
    state: FSMContext
):
    """Закрытие меню категорий"""
    await state.clear()
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.answer()


@router.callback_query(F.data == "cat:cancel")
async def on_cancel(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Отмена текущего действия → к списку"""
    await state.set_state(CategoryForm.viewing_list)
    text, kb = await build_categories_message(session, user)
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer("Отменено")


@router.callback_query(F.data.startswith("cat:viewhidden:"))
async def on_view_hidden(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Показать/скрыть скрытые категории"""
    show = cb.data.split(":")[2] == "1"
    text, kb = await build_categories_message(session, user, show_hidden=show)
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


# ============================================================================
# СПИСОК ПО ТИПУ (доходы / расходы)
# ============================================================================

@router.callback_query(F.data.startswith("cat:manage:"))
async def on_manage_type(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Управление категориями определённого типа"""
    cat_type = cb.data.split(":")[2]
    if cat_type not in ("income", "expense"):
        await cb.answer("❌ Неверный тип", show_alert=True)
        return
    
    categories = await get_categories(session, user.user_id, type=cat_type)
    
    if not categories:
        await cb.answer(f"Нет категорий", show_alert=True)
        return
    
    type_label = "💚 Доходы" if cat_type == "income" else "❤️ Расходы"
    
    await cb.message.edit_text(
        f"📁 <b>{type_label}</b>\n\n"
        f"Выбери категорию для управления:",
        reply_markup=build_category_list_kb(categories),
        parse_mode="HTML"
    )
    await cb.answer()


# ============================================================================
# ПРОСМОТР / РЕДАКТИРОВАНИЕ КАТЕГОРИИ
# ============================================================================

@router.callback_query(F.data.startswith("cat:view:"))
async def on_view_category(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Просмотр одной категории + действия"""
    cat_id = int(cb.data.split(":")[2])
    category = await get_category_by_id(session, cat_id)
    
    if not category or category.user_id != user.user_id:
        await cb.answer("❌ Категория не найдена", show_alert=True)
        return
    
    await state.set_state(CategoryForm.viewing_list)
    await state.update_data(current_category_id=cat_id)
    
    # Проверяем есть ли транзакции
    tx_count = await count_transactions_in_category(session, cat_id)
    has_tx = tx_count > 0
    
    lines = [
        f"{category.emoji} <b>{category.name}</b>",
        "",
        f"Тип: {'💚 Доход' if category.type == 'income' else '❤️ Расход'}",
        f"Тип категории: {'⭐ Системная' if not category.is_custom else '👤 Своя'}",
        f"Статус: {'🙈 Скрыта' if category.is_hidden else '✅ Активна'}",
    ]
    
    if has_tx:
        lines.append(f"Операций: {tx_count}")
    
    if category.keywords:
        keywords_preview = ", ".join(category.keywords[:5])
        if len(category.keywords) > 5:
            keywords_preview += f" и ещё {len(category.keywords) - 5}"
        lines.append(f"🔑 Ключевые слова: <i>{keywords_preview}</i>")
    
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=build_category_edit_kb(category, has_tx),
        parse_mode="HTML"
    )
    await cb.answer()


async def count_transactions_in_category(session: AsyncSession, category_id: int) -> int:
    """Считает транзакции в категории (для проверки удаления)"""
    from sqlalchemy import select, func
    from database.models import Transaction
    
    result = await session.execute(
        select(func.count(Transaction.id)).where(Transaction.category_id == category_id)
    )
    return result.scalar() or 0


# ============================================================================
# СОЗДАНИЕ КАТЕГОРИИ
# ============================================================================

@router.callback_query(F.data == "cat:create")
async def on_create_start(
    cb: CallbackQuery,
    state: FSMContext
):
    """Создание категории — выбор типа"""
    await state.set_state(CategoryForm.choosing_type)
    await cb.message.edit_text(
        "➕ <b>Создание категории</b>\n\n"
        "Шаг 1/3: тип категории",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="💚 Доход", callback_data="catnew:income"),
                InlineKeyboardButton(text="❤️ Расход", callback_data="catnew:expense"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cat:cancel")],
        ]),
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(CategoryForm.choosing_type, F.data.startswith("catnew:"))
async def on_create_type(
    cb: CallbackQuery,
    state: FSMContext
):
    """Выбрали тип → вводим имя"""
    cat_type = cb.data.split(":")[1]
    if cat_type not in ("income", "expense"):
        await cb.answer("❌ Неверный тип", show_alert=True)
        return
    
    await state.update_data(new_category_type=cat_type)
    await state.set_state(CategoryForm.entering_name)
    
    type_label = "💚 Доход" if cat_type == "income" else "❤️ Расход"
    
    await cb.message.edit_text(
        f"➕ Создание категории\n"
        f"Тип: {type_label}\n\n"
        f"Шаг 2/3: введи название",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cat:cancel")]
        ]),
        parse_mode="HTML"
    )
    await cb.answer()


@router.message(CategoryForm.entering_name, F.text)
async def on_create_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Ввели имя → выбор эмодзи"""
    name = message.text.strip()
    
    if len(name) < 2:
        await message.answer("❌ Название должно быть от 2 символов")
        return
    
    if len(name) > 64:
        await message.answer("❌ Слишком длинное название (макс 64)")
        return
    
    # Проверяем, нет ли категории с таким же именем и типом
    data = await state.get_data()
    cat_type = data["new_category_type"]
    
    existing = await get_categories(session, user.user_id, type=cat_type)
    if any(c.name.lower() == name.lower() for c in existing):
        await message.answer(f"❌ Категория «{name}» уже существует. Введи другое имя.")
        return
    
    await state.update_data(new_category_name=name)
    await state.set_state(CategoryForm.choosing_emoji)
    
    await message.answer(
        f"➕ Создание категории\n"
        f"Название: <b>{name}</b>\n\n"
        f"Шаг 3/3: выбери эмодзи",
        reply_markup=build_emoji_picker(category_id=0, theme="popular"),
        parse_mode="HTML"
    )


@router.callback_query(CategoryForm.choosing_emoji, F.data.startswith("ccemoji:"))
async def on_create_emoji(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Выбрали эмодзи → создаём категорию"""
    parts = cb.data.split(":")
    
    if parts[2] == "custom":
        # Пользователь хочет ввести свой эмодзи
        await state.set_state(CategoryForm.entering_custom_emoji)
        await cb.message.edit_text(
            "✏️ Отправь свой эмодзи (1 символ):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cat:cancel")]
            ])
        )
        await cb.answer()
        return
    
    if parts[1] == "skip":
        emoji = "📌"
    else:
        emoji = parts[2]
    
    await _finalize_create(cb, state, session, user, emoji)


@router.message(CategoryForm.entering_custom_emoji, F.text)
async def on_custom_emoji_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Пользователь ввёл свой эмодзи текстом"""
    text = message.text.strip()
    
    if not text:
        await message.answer("❌ Отправь хотя бы один символ")
        return
    
    # Берём первый символ (грубо, но работает)
    emoji = text[0]
    
    await _finalize_create(message, state, session, user, emoji, is_message=True)


async def _finalize_create(
    target,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    emoji: str,
    is_message: bool = False
):
    """Создаёт категорию и показывает обновлённый список"""
    data = await state.get_data()
    
    try:
        category = await add_custom_category(
            session,
            user.user_id,
            data["new_category_name"],
            data["new_category_type"],
            emoji=emoji,
            keywords=[],
        )
    except Exception as e:
        error_text = f"❌ Ошибка: {e}"
        if is_message:
            await target.answer(error_text)
        else:
            await target.message.edit_text(error_text)
        return
    
    await state.set_state(CategoryForm.viewing_list)
    await state.update_data(new_category_name=None, new_category_type=None)
    
    type_label = "💚 Доход" if category.type == "income" else "❤️ Расход"
    success_text = (
        f"✅ <b>Категория создана!</b>\n\n"
        f"{emoji} <b>{category.name}</b>\n"
        f"Тип: {type_label}"
    )
    
    text, kb = await build_categories_message(session, user)
    
    if is_message:
        await target.answer(success_text, parse_mode="HTML")
        await target.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.message.edit_text(success_text, parse_mode="HTML")
        await target.message.answer(text, reply_markup=kb, parse_mode="HTML")
        await target.answer("✅ Создано")


# ============================================================================
# ПЕРЕИМЕНОВАНИЕ
# ============================================================================

@router.callback_query(F.data.startswith("cat:rename:"))
async def on_rename_start(
    cb: CallbackQuery,
    state: FSMContext
):
    """Начало переименования"""
    cat_id = int(cb.data.split(":")[2])
    await state.update_data(editing_category_id=cat_id)
    await state.set_state(CategoryForm.renaming)
    
    await cb.message.edit_text(
        "✏️ Введи новое название категории:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cat:view:{cat_id}")]
        ])
    )
    await cb.answer()


@router.message(CategoryForm.renaming, F.text)
async def on_rename_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Получили новое имя"""
    new_name = message.text.strip()
    
    if len(new_name) < 2 or len(new_name) > 64:
        await message.answer("❌ Название должно быть от 2 до 64 символов")
        return
    
    data = await state.get_data()
    cat_id = data["editing_category_id"]
    
    category = await get_category_by_id(session, cat_id)
    if not category:
        await message.answer("❌ Категория не найдена")
        await state.clear()
        return
    
    # Проверка на дубликат (в том же типе)
    existing = await get_categories(session, user.user_id, type=category.type)
    if any(c.id != cat_id and c.name.lower() == new_name.lower() for c in existing):
        await message.answer(f"❌ Категория «{new_name}» уже существует")
        return
    
    old_name = category.name
    
    # Если категория системная — она становится кастомной после переименования
    was_system = not category.is_custom
    
    await update_category(
        session, cat_id,
        name=new_name,
        is_custom=True,
    )
    
    await state.set_state(CategoryForm.viewing_list)
    
    note = ""
    if was_system:
        note = "\n<i>(системная категория стала твоей персональной)</i>"
    
    await message.answer(
        f"✅ Переименовано: «{old_name}» → «{new_name}»{note}",
        parse_mode="HTML"
    )
    
    # Возвращаемся к просмотру категории
    category = await get_category_by_id(session, cat_id)
    tx_count = await count_transactions_in_category(session, cat_id)
    
    lines = [
        f"{category.emoji} <b>{category.name}</b>",
        "",
        f"Тип: {'💚 Доход' if category.type == 'income' else '❤️ Расход'}",
        f"Тип категории: {'⭐ Системная' if not category.is_custom else '👤 Своя'}",
        f"Статус: {'🙈 Скрыта' if category.is_hidden else '✅ Активна'}",
    ]
    
    await message.answer(
        "\n".join(lines),
        reply_markup=build_category_edit_kb(category, tx_count > 0),
        parse_mode="HTML"
    )


# ============================================================================
# СМЕНА ЭМОДЗИ
# ============================================================================

@router.callback_query(F.data.startswith("cat:emoji:"))
async def on_emoji_start(
    cb: CallbackQuery,
    state: FSMContext
):
    """Меню выбора эмодзи для существующей категории"""
    cat_id = int(cb.data.split(":")[2])
    await state.update_data(editing_category_id=cat_id)
    await state.set_state(CategoryForm.changing_emoji)
    
    await cb.message.edit_text(
        "🎨 Выбери эмодзи для категории:",
        reply_markup=build_emoji_picker(category_id=cat_id, theme="popular")
    )
    await cb.answer()


@router.callback_query(CategoryForm.changing_emoji, F.data.startswith("cctheme:"))
async def on_emoji_theme(
    cb: CallbackQuery,
    state: FSMContext
):
    """Смена темы эмодзи"""
    parts = cb.data.split(":")
    cat_id = int(parts[1])
    theme = parts[2]
    
    await cb.message.edit_reply_markup(
        reply_markup=build_emoji_picker(category_id=cat_id, theme=theme)
    )
    await cb.answer()


@router.callback_query(CategoryForm.changing_emoji, F.data.startswith("edemoji:"))
async def on_emoji_selected(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Выбрали эмодзи → сохраняем"""
    parts = cb.data.split(":")
    
    if parts[1] == "custom":
        # Пользователь вводит свой
        cat_id = int(parts[2])
        await state.update_data(editing_category_id=cat_id)
        await state.set_state(CategoryForm.entering_custom_emoji)
        await cb.message.edit_text(
            "✏️ Отправь свой эмодзи:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"cat:view:{cat_id}")]
            ])
        )
        await cb.answer()
        return
    
    cat_id = int(parts[1])
    emoji = parts[2]
    
    await _save_emoji(cb, state, session, user, cat_id, emoji)


@router.message(CategoryForm.entering_custom_emoji, F.text)
async def on_custom_emoji_edit(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """
    Пользователь ввёл свой эмодзи для существующей категории.
    (Общий хендлер с созданием, но различаем по наличию editing_category_id)
    """
    data = await state.get_data()
    cat_id = data.get("editing_category_id")
    
    if not cat_id:
        # Это создание новой категории — обрабатывается выше
        return
    
    text = message.text.strip()
    if not text:
        await message.answer("❌ Отправь хотя бы один символ")
        return
    
    emoji = text[0]
    await _save_emoji(message, state, session, user, cat_id, emoji, is_message=True)


async def _save_emoji(
    target,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    cat_id: int,
    emoji: str,
    is_message: bool = False
):
    """Сохраняет новый эмодзи"""
    category = await get_category_by_id(session, cat_id)
    if not category:
        error = "❌ Категория не найдена"
        if is_message:
            await target.answer(error)
        else:
            await target.message.edit_text(error)
        return
    
    await update_category(session, cat_id, emoji=emoji)
    await state.set_state(CategoryForm.viewing_list)
    
    success_text = f"✅ Эмодзи обновлён: {emoji} <b>{category.name}</b>"
    
    if is_message:
        await target.answer(success_text, parse_mode="HTML")
    else:
        await target.message.edit_text(success_text, parse_mode="HTML")
        await target.answer("✅ Готово")
    
    # Возвращаемся к просмотру категории
    category = await get_category_by_id(session, cat_id)
    tx_count = await count_transactions_in_category(session, cat_id)
    
    lines = [
        f"{category.emoji} <b>{category.name}</b>",
        "",
        f"Тип: {'💚 Доход' if category.type == 'income' else '❤️ Расход'}",
        f"Тип категории: {'⭐ Системная' if not category.is_custom else '👤 Своя'}",
        f"Статус: {'🙈 Скрыта' if category.is_hidden else '✅ Активна'}",
    ]
    
    target_message = target if is_message else target.message
    await target_message.answer(
        "\n".join(lines),
        reply_markup=build_category_edit_kb(category, tx_count > 0),
        parse_mode="HTML"
    )


# ============================================================================
# СКРЫТИЕ / ПОКАЗ
# ============================================================================

@router.callback_query(F.data.startswith("cat:hide:"))
async def on_toggle_hide(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Скрыть/показать категорию"""
    cat_id = int(cb.data.split(":")[2])
    category = await get_category_by_id(session, cat_id)
    
    if not category:
        await cb.answer("❌ Категория не найдена", show_alert=True)
        return
    
    # Нельзя скрыть последнюю в типе
    all_in_type = await get_categories(
        session, user.user_id, type=category.type, include_hidden=False
    )
    if not category.is_hidden and len(all_in_type) <= 1:
        await cb.answer(
            "❌ Нельзя скрыть последнюю категорию этого типа",
            show_alert=True
        )
        return
    
    new_state = not category.is_hidden
    await update_category(session, cat_id, is_hidden=new_state)
    
    # Обновлённые данные
    category = await get_category_by_id(session, cat_id)
    tx_count = await count_transactions_in_category(session, cat_id)
    
    action = "скрыта" if new_state else "показана"
    
    lines = [
        f"{category.emoji} <b>{category.name}</b>",
        "",
        f"Тип: {'💚 Доход' if category.type == 'income' else '❤️ Расход'}",
        f"Тип категории: {'⭐ Системная' if not category.is_custom else '👤 Своя'}",
        f"Статус: {'🙈 Скрыта' if category.is_hidden else '✅ Активна'}",
    ]
    
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=build_category_edit_kb(category, tx_count > 0),
        parse_mode="HTML"
    )
    await cb.answer(f"{'🙈' if new_state else '👁'} {action.capitalize()}")


# ============================================================================
# УДАЛЕНИЕ
# ============================================================================

@router.callback_query(F.data.startswith("cat:deleteblocked:"))
async def on_delete_blocked(
    cb: CallbackQuery
):
    """Попытка удалить категорию с транзакциями"""
    await cb.answer(
        "❌ В категории есть транзакции. Сначала удали их или скрой категорию.",
        show_alert=True
    )


@router.callback_query(F.data.startswith("cat:delete:"))
async def on_delete_start(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Подтверждение удаления"""
    cat_id = int(cb.data.split(":")[2])
    category = await get_category_by_id(session, cat_id)
    
    if not category:
        await cb.answer("❌ Категория не найдена", show_alert=True)
        return
    
    # Ещё раз проверяем на транзакции
    tx_count = await count_transactions_in_category(session, cat_id)
    if tx_count > 0:
        await cb.answer(
            f"❌ Нельзя удалить: {tx_count} транзакций",
            show_alert=True
        )
        return
    
    await state.set_state(CategoryForm.confirming_delete)
    await state.update_data(deleting_category_id=cat_id)
    
    await cb.message.edit_text(
        f"🗑 <b>Удалить категорию?</b>\n\n"
        f"{category.emoji} <b>{category.name}</b>\n\n"
        f"Это действие необратимо.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"catdel:yes:{cat_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"cat:view:{cat_id}"),
            ]
        ]),
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(CategoryForm.confirming_delete, F.data.startswith("catdel:yes:"))
async def on_delete_confirm(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Финальное удаление"""
    cat_id = int(cb.data.split(":")[2])
    category = await get_category_by_id(session, cat_id)
    
    if not category:
        await cb.answer("❌ Категория не найдена", show_alert=True)
        return
    
    cat_name = f"{category.emoji} {category.name}"
    
    try:
        await delete_category(session, cat_id)
    except ValueError as e:
        # Кто-то добавил транзакцию пока мы показывали подтверждение
        await cb.answer(f"❌ {e}", show_alert=True)
        return
    
    await state.set_state(CategoryForm.viewing_list)
    
    text, kb = await build_categories_message(session, user)
    
    await cb.message.edit_text(
        f"✅ Категория «{cat_name}» удалена\n\n" + text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await cb.answer("🗑 Удалено")