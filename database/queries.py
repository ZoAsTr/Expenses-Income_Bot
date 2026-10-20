from datetime import datetime, timedelta, UTC
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
import pytz

from database.models import User, Category, Transaction, Limit, Rate
from database.system_categories import SYSTEM_CATEGORIES

async def get_period_bounds(
        session: AsyncSession,
        user_id: int,
        period: str,
        reference_date: datetime | None = None
) -> tuple[datetime, datetime]:

    user = await get_user(session, user_id)
    if not user:
        tz = pytz.timezone("Europe/Moscow")
    else:
        tz = pytz.timezone(user.timezone)

    if reference_date is None:
        reference_date = datetime.now(tz)
    else:
        reference_date = reference_date.replace(tzinfo=tz)

    local_date = reference_date.date()
    local_start = tz.localize(datetime.combine(local_date, datetime.min.time()))

    if period == "day":
        start_local = local_start
        end_local = start_local + timedelta(days=1)

    elif period == "week":
        start_local = local_start - timedelta(days=6)
        end_local = local_start + timedelta(days=1)

    elif period == "month":
        start_local = tz.localize(datetime(local_date.year, local_date.month, 1, 0, 0, 0))
        if local_date.month == 12:
            end_local = tz.localize(datetime(local_date.year + 1, 1, 1, 0, 0, 0))
        else:
            end_local = tz.localize(datetime(local_date.year, local_date.month + 1, 1, 0, 0, 0))

    elif period == "year":
        start_local = tz.localize(datetime(local_date.year, 1, 1, 0, 0, 0))
        end_local = tz.localize(datetime(local_date.year + 1, 1, 1, 0, 0, 0))
    
    else:
        raise ValueError(f"Unknown period: {period}")

    # Конвертация в UTS
    start_uts = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
    end_uts = end_local.astimezone(pytz.UTC).replace(tzinfo=None)

    return start_uts, end_uts


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    """ Получить юзера по ID """
    result = await session.execute(
        select(User).where(User.user_id == user_id)
    )
    return result.scalar_one_or_none()

async def create_user_with_defaults(
        session: AsyncSession,
        user_id: int,
        username: str | None = None,
        timezone: str = "Europe/Moscow",
        currency: str = "RUB"
) -> User:
    """ Создаёт юзера и копирует все системные категории в его профиль """

    user = User(
        user_id=user_id,
        username=username,
        timezone=timezone,
        currency=currency
    )
    session.add(user)
    await session.flush()

    # Копируем системные категории
    for sys_cat in SYSTEM_CATEGORIES:
        category = Category(
            user_id=user_id,
            name=sys_cat["name"],
            type=sys_cat["type"],
            emoji=sys_cat["emoji"],
            keywords=sys_cat["keywords"],
            is_custom=False,
            is_hidden=False
        )
        session.add(category)
    
    await session.commit()
    return user

async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    username: str | None = None
) -> User:
    """Получить юзера или создать, если его нет"""
    user = await get_user(session, user_id)
    if not user:
        user = await create_user_with_defaults(session, user_id, username)
    return user


async def get_categories(
        session: AsyncSession,
        user_id: int,
        type: str | None = None,
        include_hidden: bool = False
) -> list[Category]:
    
    """ Получение категории юзера """

    query = select(Category).where(Category.user_id == user_id)

    if not include_hidden:
        query = query.where(Category.is_hidden == False)

    if type:
        query = query.where(Category.type == type)
    

    result = await session.execute(query)
    return result.scalars().all()


async def get_category_by_id(session: AsyncSession, category_id: int) -> Category | None:
    """ Получить категорию по его ID """

    result = await session.execute(
        select(Category).where(Category.id == category_id)
    )

    return result.scalar_one_or_none()

async def add_custom_category(
        session: AsyncSession,
        user_id: int,
        name: str,
        type: str,
        empji: str = "",
        keywords: list = None
) -> Category:
    """ Добавление кастомной категории """

    if keywords is None:
        keywords = []

    category = Category(
        user_id=user_id,
        name=name,
        type=type,
        emoji=empji,
        keywords=keywords,
        is_custom=True,
        is_hidden=False
    )
    session.add(category)
    await session.commit()
    return category

async def update_category(
        session: AsyncSession,
        category_id: int,
        **fields
) -> Category:

    category = await get_category_by_id(session, category_id)
    if not category:
        raise ValueError(f"Category {category_id} not found")

    for key, value in fields.items():
        if hasattr(category, key):
            setattr(category, key, value)

    await session.commit()
    return category


async def hide_category(session: AsyncSession, category_id: int) -> None:
    await update_category(session, category_id, is_hidden=True)

async def delete_category(session: AsyncSession, category_id: int) -> None:
    # Проверяет, есть ли транзакция в этой категории
    count_result = await session.execute(
        select(func.count(Transaction.id)).where(Transaction.category_id == category_id) 
    )

    count = count_result.scalar()

    if count > 0:
        raise ValueError(f"Cannot delete category with {count} transactions. Hide it instead.")

    category = await get_category_by_id(session, category_id)
    if category:
        await session.delete(category)
        await session.commit()


async def add_transaction(
        session: AsyncSession,
        user_id: int,
        type: str,
        amount: float,
        category_id: int,
        description: str | None = None
) -> Transaction:
    """ Добавить транзакцию """
    transaction = Transaction(
        user_id=user_id,
        type=type,
        amount=amount,
        category_id=category_id,
        description=description,
        created_at=datetime.now(UTC).replace(tzinfo=None)
    )
    session.add(transaction)
    await session.commit()
    await session.refresh(transaction)
    return transaction


async def get_transaction_by_id(
        session: AsyncSession,
        tr_id: int
) -> Transaction | None:
    """ Получение транзакции по ID """
    result = await session.execute(
        select(Transaction).where(Transaction.id == tr_id)
    )
    return result.scalar_one_or_none()


async def get_transactions_by_period(
        session: AsyncSession,
        user_id: int,
        start: datetime,
        end: datetime,
        type: str | None = None,
        category_id: int | None = None,
        limit: int = 50,
        offset: int = 0
) -> list[Transaction]:
    """ Получить транзакцию за период """
    query = select(Transaction).where(
        and_(
            Transaction.user_id == user_id,
            Transaction.created_at >= start,
            Transaction.created_at < end
        )
    )

    if type:
        query = query.where(Transaction.type == type)

    if category_id:
        query = query.where(Transaction.category_id == category_id)

    query = query.order_by(Transaction.created_at.desc())
    query = query.limit(limit).offset(offset)

    result = await session.execute(query)
    return result.scalars().all()


async def update_transaction(
    session: AsyncSession,
    tr_id: int,
    **fields
) -> Transaction:
    """Обновить транзакцию"""
    transaction = await get_transaction_by_id(session, tr_id)
    if not transaction:
        raise ValueError(f"Transaction {tr_id} not found")
    
    for key, value in fields.items():
        if hasattr(transaction, key):
            setattr(transaction, key, value)
    
    await session.commit()
    return transaction


async def delete_transaction(session: AsyncSession, tr_id: int) -> None:
    """Удалить транзакцию"""
    transaction = await get_transaction_by_id(session, tr_id)
    if transaction:
        await session.delete(transaction)
        await session.commit()


async def get_totals(
    session: AsyncSession,
    user_id: int,
    start: datetime,
    end: datetime
) -> dict:
    """Получить сумму доходов и расходов за период"""
    result = await session.execute(
        select(
            Transaction.type,
            func.sum(Transaction.amount).label("total")
        ).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.created_at >= start,
                Transaction.created_at < end
            )
        ).group_by(Transaction.type)
    )
    
    rows = result.all()
    income = 0.0
    expense = 0.0
    
    for row in rows:
        if row[0] == "income":
            income = float(row[1]) if row[1] else 0.0
        elif row[0] == "expense":
            expense = float(row[1]) if row[1] else 0.0
    
    return {
        "income": income,
        "expense": expense,
        "balance": income - expense
    }


async def get_by_category(
    session: AsyncSession,
    user_id: int,
    start: datetime,
    end: datetime,
    type: str
) -> list[dict]:
    """Получить расходы/доходы по категориям (для pie chart)"""
    result = await session.execute(
        select(
            Category.id,
            Category.name,
            Category.emoji,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count")
        ).join(
            Transaction,
            Category.id == Transaction.category_id
        ).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.type == type,
                Transaction.created_at >= start,
                Transaction.created_at < end
            )
        ).group_by(
            Category.id,
            Category.name,
            Category.emoji
        ).order_by(func.sum(Transaction.amount).desc())
    )
    
    rows = result.all()
    return [
        {
            "category_id": row[0],
            "name": row[1],
            "emoji": row[2],
            "total": float(row[3]) if row[3] else 0.0,
            "count": int(row[4]) if row[4] else 0
        }
        for row in rows
    ]


async def get_daily_trend(
    session: AsyncSession,
    user_id: int,
    start: datetime,
    end: datetime,
    type: str
) -> list[dict]:
    """Получить тренд по дням (для line chart)"""
    # Тянем все транзакции за период
    transactions = await get_transactions_by_period(
        session, user_id, start, end, type=type, limit=10000
    )
    
    # Юзер
    user = await get_user(session, user_id)
    tz = pytz.timezone(user.timezone if user else "Europe/Moscow")
    
    # Группируем по локальной дате
    from collections import defaultdict
    by_date = defaultdict(float)
    
    for tr in transactions:
        local_dt = tr.created_at.replace(tzinfo=pytz.UTC).astimezone(tz)
        local_date = local_dt.date().isoformat()
        by_date[local_date] += tr.amount
    
    # Сортируем по дате
    result = [
        {"date": date_str, "total": total}
        for date_str, total in sorted(by_date.items())
    ]
    
    return result


async def get_category_total(
    session: AsyncSession,
    user_id: int,
    category_id: int,
    start: datetime,
    end: datetime
) -> float:
    """Получить сумму по конкретной категории за период"""
    result = await session.execute(
        select(func.sum(Transaction.amount)).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.category_id == category_id,
                Transaction.created_at >= start,
                Transaction.created_at < end
            )
        )
    )
    
    total = result.scalar()
    return float(total) if total else 0.0


async def count_transactions(
    session: AsyncSession,
    user_id: int,
    start: datetime,
    end: datetime
) -> int:
    """Считать транзакции за период"""
    result = await session.execute(
        select(func.count(Transaction.id)).where(
            and_(
                Transaction.user_id == user_id,
                Transaction.created_at >= start,
                Transaction.created_at < end
            )
        )
    )
    return result.scalar() or 0


async def add_limit(
    session: AsyncSession,
    user_id: int,
    category_id: int,
    period: str,
    max_amount: float,
    alert_percent: int = 20
) -> Limit:
    """Добавить лимит"""
    limit = Limit(
        user_id=user_id,
        category_id=category_id,
        period=period,
        max_amount=max_amount,
        alert_percent=alert_percent,
        is_active=True
    )
    session.add(limit)
    await session.commit()
    return limit


async def get_limits(
    session: AsyncSession,
    user_id: int,
    is_active_only: bool = True
) -> list[Limit]:
    """Получить лимиты юзера"""
    query = select(Limit).where(Limit.user_id == user_id)
    
    if is_active_only:
        query = query.where(Limit.is_active == True)
    
    result = await session.execute(query)
    return result.scalars().all()


async def get_limit_for_category(
    session: AsyncSession,
    user_id: int,
    category_id: int,
    period: str
) -> Limit | None:
    """Получить лимит для конкретной категории и периода"""
    result = await session.execute(
        select(Limit).where(
            and_(
                Limit.user_id == user_id,
                Limit.category_id == category_id,
                Limit.period == period,
                Limit.is_active == True
            )
        )
    )
    return result.scalar_one_or_none()


async def update_limit(
    session: AsyncSession,
    limit_id: int,
    **fields
) -> Limit:
    """Обновить лимит"""
    result = await session.execute(
        select(Limit).where(Limit.id == limit_id)
    )
    limit = result.scalar_one_or_none()
    
    if not limit:
        raise ValueError(f"Limit {limit_id} not found")
    
    for key, value in fields.items():
        if hasattr(limit, key):
            setattr(limit, key, value)
    
    await session.commit()
    return limit


async def delete_limit(session: AsyncSession, limit_id: int) -> None:
    """Удалить лимит"""
    result = await session.execute(
        select(Limit).where(Limit.id == limit_id)
    )
    limit = result.scalar_one_or_none()
    
    if limit:
        await session.delete(limit)
        await session.commit()


async def check_limit(
    session: AsyncSession,
    user_id: int,
    category_id: int,
    amount_to_add: float,
    period_start: datetime,
    period_end: datetime
) -> dict:
    """
    Проверить лимит при добавлении новой транзакции.
    Возвращает dict с информацией о статусе лимита.
    """
    # Ищем лимит (определяем период из dates)
    # Нужно определить, какой период это (day/week/month/year)
    # Пока универсально — проверяем все активные лимиты для этой категории
    
    result = await session.execute(
        select(Limit).where(
            and_(
                Limit.user_id == user_id,
                Limit.category_id == category_id,
                Limit.is_active == True
            )
        )
    )
    
    limits = result.scalars().all()
    
    # Если лимитов нет — OK
    if not limits:
        return {
            "has_limit": False,
            "status": "ok"
        }
    
    # Проверяем каждый лимит
    statuses = []
    
    for limit in limits:
        # Считаем текущие траты за период
        spent_before = await get_category_total(
            session, user_id, category_id,
            period_start, period_end
        )
        spent_after = spent_before + amount_to_add
        percent_after = (spent_after / limit.max_amount * 100) if limit.max_amount > 0 else 0
        
        if spent_after > limit.max_amount:
            status = "exceeded"
        elif percent_after >= (100 - limit.alert_percent):
            status = "warning"
        else:
            status = "ok"
        
        statuses.append({
            "limit_id": limit.id,
            "limit": limit.max_amount,
            "spent_before": spent_before,
            "spent_after": spent_after,
            "percent_after": percent_after,
            "alert_percent": limit.alert_percent,
            "status": status
        })
    
    # Находим наихудший статус (exceeded > warning > ok)
    worst_status = "ok"
    for s in statuses:
        if s["status"] == "exceeded":
            worst_status = "exceeded"
            break
        elif s["status"] == "warning":
            worst_status = "warning"
    
    return {
        "has_limit": True,
        "status": worst_status,
        "limits_check": statuses
    }


async def save_rate(
    session: AsyncSession,
    currency: str,
    rate_rub: float
) -> Rate:
    """Сохранить курс валюты"""
    # Проверяем, есть ли уже такой курс
    result = await session.execute(
        select(Rate).where(Rate.currency == currency)
    )
    rate = result.scalar_one_or_none()
    
    if rate:
        rate.rate_rub = rate_rub
        rate.updated_at = datetime.now(UTC).replace(tzinfo=None)
    else:
        rate = Rate(
            currency=currency,
            rate_rub=rate_rub,
            updated_at=datetime.now(UTC).replace(tzinfo=None)
        )
        session.add(rate)
    
    await session.commit()
    return rate


async def get_cached_rate(
    session: AsyncSession,
    currency: str,
    max_age_hours: int = 24
) -> float | None:
    """Получить кэшированный курс, если он свежий"""
    result = await session.execute(
        select(Rate).where(Rate.currency == currency)
    )
    rate = result.scalar_one_or_none()
    
    if not rate:
        return None
    
    # Проверяем, не устарел ли кэш
    age = (datetime.now(UTC).replace(tzinfo=None) - rate.updated_at).total_seconds() / 3600
    
    if age > max_age_hours:
        return None  # Кэш устарел
    
    return rate.rate_rub