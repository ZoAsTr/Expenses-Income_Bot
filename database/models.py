from datetime import datetime
from sqlalchemy import (
    BigInteger, String, Integer, Float, Boolean, 
    DateTime, ForeignKey, JSON, Text
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class User(Base):
    """ Пользователь """
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    created_at: Mapped[str] = mapped_column(DateTime, default=datetime.utcnow)

    categories = relationship("Category", back_populates="user", lazy="selectin")
    transactions = relationship("Transaction", back_populates="user")
    limits = relationship("Limit", back_populates="user", lazy="selectin")


class Category(Base):
    """ Категория траназакции (доход или расход) """
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"))

    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(10))
    emoji: Mapped[str] = mapped_column(String(8), default="")
    keywords: Mapped[list] = mapped_column(JSON, default=list)

    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)

    user = relationship("User", back_populates="categories")


class Transaction(Base):
    """ Транзакция (доход или расход) """
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))

    type: Mapped[str] = mapped_column(String(10))
    amount: Mapped[float] = mapped_column(Float) # Всегда в рублях
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="transactions")
    category = relationship("Category", lazy="joined")


class Limit(Base):
    """ Лимит по категориям """
    __tablename__ = "limits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))

    period: Mapped[str] = mapped_column(String(10)) # "day"|"week"|"month"|"year"
    # Keep the legacy DB column name so existing databases continue to work.
    max_amount: Mapped[float] = mapped_column("max_ammount", Float)
    alert_percent: Mapped[int] = mapped_column(Integer, default=20)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user = relationship("User", back_populates="limits")
    category = relationship("Category", lazy="joined")

class Rate(Base):
    """ Кэш курсов валют """
    __tablename__ = "rates"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate_rub: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)