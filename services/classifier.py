import re
from database.models import Category


def parse_amount(text: str) -> float | None:
    """
    Парсит сумму из текста.
    Принимает: "450", "450.50", "450,50", "450р", "450 руб", "1 200"
    Возвращает float или None.
    """
    if not text:
        return None
    
    # Убираем пробелы между цифрами (1 200 → 1200)
    text = re.sub(r'(\d)\s+(\d)', r'\1\2', text.strip())
    
    # Ищем первое число (с точкой или запятой)
    match = re.search(r'(\d+(?:[.,]\d{1,2})?)', text)
    if not match:
        return None
    
    # Заменяем запятую на точку
    amount_str = match.group(1).replace(',', '.')
    
    try:
        amount = float(amount_str)
        if amount <= 0:
            return None
        return amount
    except ValueError:
        return None


def classify_by_keywords(
    text: str,
    categories: list[Category]
) -> Category | None:
    """
    Гибридный классификатор по ключевым словам.
    Возвращает Category или None.
    
    Алгоритм:
    1. Нормализуем текст
    2. Для каждой категории считаем сколько ключевых слов найдено
    3. Учитываем длину ключа (длинные важнее)
    4. Возвращаем категорию с лучшим счётом
    """
    if not text:
        return None
    
    text_lower = text.lower().strip()
    best_match = None
    best_score = 0.0
    
    for cat in categories:
        if not cat.keywords:
            continue
        
        score = 0.0
        for keyword in cat.keywords:
            kw_lower = keyword.lower()
            if kw_lower in text_lower:
                # Вес ключа = его длина (длинные ключи точнее)
                # + бонус за совпадение с начала слова
                weight = len(kw_lower)
                if text_lower.startswith(kw_lower):
                    weight += 2.0
                score += weight
        
        if score > best_score:
            best_score = score
            best_match = cat
    
    return best_match if best_score > 0 else None


def suggest_category_by_amount(
    amount: float,
    categories: list[Category],
    recent_transactions_by_category: dict
) -> Category | None:
    """
    Альтернатива: если нет ключевых слов, но есть история —
    не используется пока, оставлено на будущее.
    """
    return None