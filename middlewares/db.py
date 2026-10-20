from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from database.db import AsyncSessionLocal


class DbSessionMiddleware(BaseMiddleware):
    """
    Создаёт AsyncSession для каждого апдейта.
    Сессия доступна в хендлерах через аргумент `session`.
    """
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        async with AsyncSessionLocal() as session:
            data["session"] = session
            return await handler(event, data)