"""
Обработчик транзакций (доходы и расходы).

Три сценария ввода:
1. Быстрый ввод текстом: "450 макдак" → классификация → подтверждение
2. Пошаговый ввод кнопками: [Внести] → [Расход] → [Категория] → [Сумма]
3. Гибрид: выбрал тип кнопкой, потом написал текст
"""

import re

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from database.queries import (
    get_categories,
    get_category_by_id,
    add_transaction,
    add_custom_category,
)
from services.classifier import parse_amount, classify_by_keywords
from services.currency import format_money
from services.limits_checker import check_and_format
from keyboards.inline import (
    get_type_kb,
    get_categories_kb,
    get_confirm_kb,
)

router = Router()


# ============================================================================
# FSM СОСТОЯНИЯ
# ============================================================================

class TxForm(StatesGroup):
    choosing_type = State()         # выбор доход/расход
    choosing_category = State()     # выбор категории кнопками
    entering_amount = State()       # ввод суммы (категория уже выбрана)
    entering_new_category_name = State()  # ввод имени новой категории
    confirming = State()            # подтверждение


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def extract_description(text: str) -> str | None:
    """
    Убирает первое число из текста, возвращает остаток как описание.
    "450 макдак у метро" → "макдак у метро"
    "450" → None
    """
    # Убираем пробелы между цифрами: "1 200 макдак" → "1200 макдак"
    normalized = re.sub(r'(\d)\s+(\d)', r'\1\2', text.strip())
    # Убираем первое число (с запятой/точкой) и мусор вокруг
    cleaned = re.sub(r'^\s*\d+(?:[.,]\d{1,2})?\s*(?:руб|р|₽)?\s*', '', normalized)
    cleaned = cleaned.strip()
    return cleaned if cleaned else None


async def build_suggestion(
    session: AsyncSession,
    user: User,
    tx_type: str,
    description: str | None
):
    """
    Определяет категорию для транзакции.
    Возвращает Category или None.
    """
    categories = await get_categories(session, user.user_id, type=tx_type)
    if not categories:
        return None
    
    # Пробуем классифицировать по описанию
    suggested = None
    if description:
        suggested = classify_by_keywords(description, categories)
    
    # Fallback: "Другое" для расходов, первая для доходов
    if not suggested:
        if tx_type == "expense":
            suggested = next((c for c in categories if c.name == "Другое"), None)
        if not suggested:
            suggested = categories[0]
    
    return suggested


async def show_confirmation(
    message_or_cb,
    state: FSMContext,
    session: AsyncSession,
    user: User,
    tx_type: str,
    amount: float,
    category,
    description: str | None,
    was_suggested: bool,
):
    """
    Показывает экран подтверждения транзакции.
    Работает и для Message, и для CallbackQuery.
    """
    await state.update_data(
        type=tx_type,
        amount=amount,
        category_id=category.id,
        category_name=category.name,
        category_emoji=category.emoji,
        description=description,
    )
    await state.set_state(TxForm.confirming)
    
    type_label = "💚 Доход" if tx_type == "income" else "❤️ Расход"
    desc_line = f"\n📝 {description}" if description else ""
    
    text = (
        f"{type_label}\n"
        f"{category.emoji} <b>{category.name}</b> — {format_money(amount)}"
        f"{desc_line}\n\n"
        f"Записать?"
    )
    kb = get_confirm_kb(suggested=was_suggested)
    
    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message_or_cb.answer(text, reply_markup=kb, parse_mode="HTML")


# ============================================================================
# СЦЕНАРИЙ 1: БЫСТРЫЙ ВВОД (свободный текст без активного FSM)
# ============================================================================

@router.message(StateFilter(None),F.text.regexp(r'^\s*[+-]?\d'))
async def handle_quick_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """
    Юзер пишет "450 макдак" или "+50000 зарплата" без всяких меню.
    Определяем тип по знаку: "+" → доход, остальное → расход.
    """
    text = message.text.strip()
    
    # Определяем тип
    if text.startswith("+"):
        tx_type = "income"
        text = text[1:].strip()
    elif text.startswith("-"):
        tx_type = "expense"
        text = text[1:].strip()
    else:
        tx_type = "expense"
    
    amount = parse_amount(text)
    if not amount:
        await message.answer(
            "🤔 Не могу разобрать сумму.\n"
            "Попробуй так: <code>450 фастфуд</code>",
            parse_mode="HTML"
        )
        return
    
    description = extract_description(text)
    category = await build_suggestion(session, user, tx_type, description)
    
    if not category:
        await message.answer("❌ Нет доступных категорий. Проверь настройки.")
        return
    
    await show_confirmation(
        message, state, session, user,
        tx_type, amount, category, description,
        was_suggested=bool(description)
    )


# ============================================================================
# СЦЕНАРИЙ 2: ПОШАГОВЫЙ ВВОД (кнопки)
# ============================================================================

@router.message(F.text == "➕ Внести")
async def start_entry(
    message: Message,
    state: FSMContext,
    user: User
):
    """Начало пошагового ввода — выбор типа"""
    await state.clear()
    await state.set_state(TxForm.choosing_type)
    await message.answer("Что вносим?", reply_markup=get_type_kb())


@router.callback_query(TxForm.choosing_type, F.data.startswith("type:"))
async def on_type_selected(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Выбрали тип → показываем категории + подсказка про свободный ввод"""
    tx_type = cb.data.split(":")[1]
    if tx_type not in ("income", "expense"):
        await cb.answer("❌ Неверный тип", show_alert=True)
        return
    
    await state.update_data(type=tx_type)
    await state.set_state(TxForm.choosing_category)
    
    categories = await get_categories(session, user.user_id, type=tx_type)
    
    if not categories:
        await cb.message.edit_text("❌ Нет категорий. Добавь хотя бы одну в настройках.")
        await cb.answer()
        return
    
    type_label = "💚 Доход" if tx_type == "income" else "❤️ Расход"
    
    await cb.message.edit_text(
        f"{type_label}\n\n"
        f"Выбери категорию <b>или напиши</b> сумму с описанием:\n"
        f"<code>450 макдак</code>",
        reply_markup=get_categories_kb(categories, page=0),
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(TxForm.choosing_category, F.data == "cat:new")
async def on_new_category(
    cb: CallbackQuery,
    state: FSMContext
):
    """Создание новой категории во время ввода"""
    await state.set_state(TxForm.entering_new_category_name)
    
    await cb.message.edit_text(
        "✏️ Напиши название новой категории:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="tx:cancel")]
        ])
    )
    await cb.answer()


@router.message(TxForm.entering_new_category_name, F.text)
async def on_new_category_name(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Юзер ввёл имя новой категории"""
    name = message.text.strip()
    
    if len(name) < 2 or len(name) > 64:
        await message.answer("Название должно быть от 2 до 64 символов. Попробуй ещё:")
        return
    
    data = await state.get_data()
    tx_type = data["type"]
    
    # Создаём категорию
    new_cat = await add_custom_category(
        session, user.user_id, name, tx_type, emoji="📌"
    )
    
    # Сразу переходим к вводу суммы
    await state.update_data(
        category_id=new_cat.id,
        category_name=new_cat.name,
        category_emoji=new_cat.emoji,
    )
    await state.set_state(TxForm.entering_amount)
    
    await message.answer(
        f"✅ Категория «{name}» создана\n\n"
        f"📌 <b>{name}</b>\n\n"
        f"Введи сумму (можно с описанием):\n"
        f"<code>450</code> или <code>450 шаурма у метро</code>",
        parse_mode="HTML"
    )


@router.callback_query(TxForm.choosing_category, F.data.startswith("catpage:"))
async def on_category_page(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Переключение страницы категорий"""
    page = int(cb.data.split(":")[1])
    data = await state.get_data()
    
    categories = await get_categories(session, user.user_id, type=data["type"])
    
    await cb.message.edit_reply_markup(
        reply_markup=get_categories_kb(categories, page=page)
    )
    await cb.answer()


@router.callback_query(TxForm.choosing_category, F.data.startswith("cat:"))
async def on_category_selected(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession
):
    """Выбрали категорию → просим сумму"""
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
    await state.set_state(TxForm.entering_amount)
    
    await cb.message.edit_text(
        f"{category.emoji} <b>{category.name}</b>\n\n"
        f"Введи сумму (можно с описанием):\n"
        f"<code>450</code> или <code>450 шаурма у метро</code>",
        parse_mode="HTML"
    )
    await cb.answer()


@router.message(TxForm.entering_amount, F.text)
async def on_amount_entered(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Юзер ввёл сумму после выбора категории"""
    text = message.text.strip()
    amount = parse_amount(text)
    
    if not amount:
        await message.answer(
            "🤔 Не могу разобрать сумму. Попробуй:\n"
            "<code>450</code> или <code>450 описание</code>",
            parse_mode="HTML"
        )
        return
    
    description = extract_description(text)
    data = await state.get_data()
    
    # Создаём "легковесный" объект категории для отображения
    class _CatStub:
        def __init__(self, id, name, emoji):
            self.id = id
            self.name = name
            self.emoji = emoji
    
    category = _CatStub(
        data["category_id"],
        data["category_name"],
        data["category_emoji"]
    )
    
    await show_confirmation(
        message, state, session, user,
        data["type"], amount, category, description,
        was_suggested=False
    )


# ============================================================================
# СЦЕНАРИЙ 3: ГИБРИД (юзер в режиме выбора категории пишет текст)
# ============================================================================

@router.message(TxForm.choosing_category, F.text.regexp(r'^\s*\d'))
async def on_text_in_choosing_category(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """
    Юзер выбрал тип кнопкой, но вместо категории написал текст "450 макдак".
    Тип уже известен из state, поэтому просто классифицируем и переходим к подтверждению.
    """
    data = await state.get_data()
    tx_type = data["type"]
    
    text = message.text.strip()
    amount = parse_amount(text)
    
    if not amount:
        return  # не наш случай, пусть обрабатывают другие хендлеры
    
    description = extract_description(text)
    category = await build_suggestion(session, user, tx_type, description)
    
    if not category:
        await message.answer("❌ Нет доступных категорий.")
        return
    
    await show_confirmation(
        message, state, session, user,
        tx_type, amount, category, description,
        was_suggested=True
    )


# ============================================================================
# ПОДТВЕРЖДЕНИЕ / СМЕНА КАТЕГОРИИ / ОТМЕНА
# ============================================================================

@router.callback_query(TxForm.confirming, F.data == "confirm:yes")
async def on_confirm(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Записываем транзакцию в БД"""
    data = await state.get_data()
    
    # Защита от двойного нажатия
    if not data.get("category_id") or not data.get("amount"):
        await cb.answer("❌ Данные потеряны, начни заново", show_alert=True)
        await state.clear()
        return
    
    await add_transaction(
        session,
        user_id=user.user_id,
        type=data["type"],
        amount=data["amount"],
        category_id=data["category_id"],
        description=data.get("description")
    )
    
    # Проверяем лимиты (только для расходов)
    warning = None
    if data["type"] == "expense":
        warning = await check_and_format(
            session, user.user_id, data["category_id"], data["amount"]
        )
    
    type_label = "💚 Доход" if data["type"] == "income" else "❤️ Расход"
    text = (
        f"✅ <b>Записано!</b>\n\n"
        f"{type_label}\n"
        f"{data['category_emoji']} {data['category_name']} — "
        f"{format_money(data['amount'])}"
    )
    if warning:
        text += warning
    
    await cb.message.edit_text(text, parse_mode="HTML")
    await state.clear()
    await cb.answer("✅ Записано")


@router.callback_query(TxForm.confirming, F.data == "confirm:change")
async def on_change_category(
    cb: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    user: User
):
    """Юзер хочет сменить категорию — возвращаем в выбор категорий"""
    data = await state.get_data()
    tx_type = data["type"]
    
    categories = await get_categories(session, user.user_id, type=tx_type)
    await state.set_state(TxForm.choosing_category)
    
    await cb.message.edit_text(
        f"Выбери другую категорию.\n"
        f"Сумма {format_money(data['amount'])} сохранится.",
        reply_markup=get_categories_kb(categories, page=0),
        parse_mode="HTML"
    )
    await cb.answer()


@router.callback_query(F.data == "tx:cancel")
async def on_cancel(
    cb: CallbackQuery,
    state: FSMContext
):
    """Отмена любого этапа ввода"""
    await state.clear()
    try:
        await cb.message.edit_text("❌ Отменено")
    except Exception:
        await cb.message.answer("❌ Отменено")
    await cb.answer()