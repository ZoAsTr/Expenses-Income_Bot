import aiohttp
from database.queries import get_cached_rate, save_rate
from config import EXCHANGE_API_URL, EXCHANGE_CACHE_HOURS


async def get_rate_rub(session, currency: str) -> float | None:
    """
    Получить курс: сколько рублей за 1 единицу валюты.
    
    Например: get_rate_rub(session, "USD") → 92.5 (рублей за 1 доллар)
    
    1. Проверяет кэш в БД (24ч)
    2. Если нет — запрашивает API
    3. Сохраняет в кэш
    4. При ошибке API — возвращает устаревший кэш (если есть)
    """
    if currency == "RUB":
        return 1.0
    
    # 1. Проверяем свежий кэш
    cached = await get_cached_rate(session, currency, EXCHANGE_CACHE_HOURS)
    if cached:
        return cached
    
    # 2. Запрашиваем API
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(EXCHANGE_API_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    raise Exception(f"API returned {resp.status}")
                
                data = await resp.json()
                rates = data.get("rates", {})
                
                # API отдаёт: "rates": {"USD": 0.0105} — сколько USD за 1 RUB
                # Нам нужно обратное: сколько RUB за 1 USD
                if currency not in rates:
                    raise Exception(f"Currency {currency} not in API response")
                
                rate_rub = 1.0 / rates[currency]
                await save_rate(session, currency, rate_rub)
                return rate_rub
    
    except Exception as e:
        # 3. Fallback: устаревший кэш
        stale = await get_cached_rate(session, currency, max_age_hours=999999)
        if stale:
            print(f"⚠️ API failed ({e}), using stale cache: {currency}={stale}")
            return stale
        print(f"❌ API failed and no cache: {e}")
        return None


async def convert_to_rub(session, amount: float, currency: str) -> float | None:
    """Конвертировать сумму в рубли"""
    if currency == "RUB":
        return amount
    
    rate = await get_rate_rub(session, currency)
    if not rate:
        return None
    
    return amount * rate


async def convert_from_rub(session, amount_rub: float, currency: str) -> float | None:
    """Конвертировать рубли в валюту"""
    if currency == "RUB":
        return amount_rub
    
    rate = await get_rate_rub(session, currency)
    if not rate:
        return None
    
    return amount_rub / rate


def format_money(amount: float, currency: str = "RUB") -> str:
    """Красивое форматирование суммы"""
    symbols = {"RUB": "₽", "USD": "$", "EUR": "€"}
    symbol = symbols.get(currency, currency)
    
    # Разделяем тысячи
    if abs(amount) >= 1000:
        formatted = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
        # Убираем копейки если они нулевые
        if formatted.endswith(",00"):
            formatted = formatted[:-3]
    else:
        formatted = f"{amount:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    
    return f"{formatted} {symbol}"