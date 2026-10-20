from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from database.queries import get_or_create_user


class UserMiddleware(BaseMiddleware):
    """
    Автоматически создаёт юзера при первом обращении.
    Кладёт объект User в data["user"].
    """
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Достаём telegram user
        if isinstance(event, Message):
            tg_user = event.from_user
        elif isinstance(event, CallbackQuery):
            tg_user = event.from_user
        else:
            tg_user = None
        
        if tg_user and "session" in data:
            user = await get_or_create_user(
                data["session"], 
                tg_user.id, 
                tg_user.username
            )
            data["user"] = user
        
        return await handler(event, data)