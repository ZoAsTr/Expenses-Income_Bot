"""
Генерация Excel-отчёта с графиками.

Структура файла:
- Сводка       — общая картина за период
- Транзакции   — все операции списком
- Категории    — агрегация + pie chart
- Тренд        — динамика по дням + line chart
- Сравнение    — доход vs расход + bar chart
"""

import os
from datetime import datetime, timedelta
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import PieChart, LineChart, BarChart, Reference
from openpyxl.chart.label import DataLabelList
from sqlalchemy.ext.asyncio import AsyncSession

from config import EXCEL_EXPORT_DIR
from database.models import User
from database.queries import (
    get_totals,
    get_by_category,
    get_transactions_by_period,
)
from services.currency import get_rate_rub

# ============================================================================
# СТИЛИ
# ============================================================================

# Цвета (как в современных финансовых приложениях)
COLOR_INCOME = "21A67A"      # зелёный
COLOR_EXPENSE = "E0483F"     # красный
COLOR_HEADER = "1F2937"      # тёмно-серый
COLOR_HEADER_TEXT = "FFFFFF" # белый
COLOR_ACCENT = "3B82F6"      # синий акцент
COLOR_LIGHT_BG = "F3F4F6"    # светло-серый фон

THIN_BORDER = Border(
    left=Side(style="thin", color="D1D5DB"),
    right=Side(style="thin", color="D1D5DB"),
    top=Side(style="thin", color="D1D5DB"),
    bottom=Side(style="thin", color="D1D5DB"),
)


def style_header_row(ws, row: int, num_cols: int):
    """Оформляет строку как заголовок таблицы."""
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = Font(bold=True, color=COLOR_HEADER_TEXT, size=11)
        cell.fill = PatternFill("solid", fgColor=COLOR_HEADER)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER


def style_data_row(ws, row: int, num_cols: int, alt: bool = False):
    """Оформляет строку данных."""
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.border = THIN_BORDER
        if alt:
            cell.fill = PatternFill("solid", fgColor=COLOR_LIGHT_BG)


def auto_width(ws, min_width: int = 12, max_width: int = 40):
    """Автоширина колонок по содержимому."""
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = max(min_width, min(max_len + 3, max_width))


# ============================================================================
# ЛИСТ 1: СВОДКА
# ============================================================================

def build_summary_sheet(
    wb: Workbook,
    user: User,
    start: datetime,
    end: datetime,
    totals: dict,
    tx_count: int,
    period: str,
    rate: float | None,
):
    """Лист со сводкой за период."""
    ws = wb.create_sheet("Сводка", 0)
    
    display_currency = user.currency
    symbol = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(display_currency, display_currency)
    
    def convert(amount_rub: float) -> float:
        if display_currency == "RUB" or not rate:
            return amount_rub
        return amount_rub / rate
    
    # Заголовок
    period_titles = {
        "day": f"ОТЧЁТ ЗА {start.strftime('%d.%m.%Y')}",
        "week": f"ОТЧЁТ ЗА НЕДЕЛЮ\n{start.strftime('%d.%m')} — {(end - timedelta(days=1)).strftime('%d.%m.%Y')}",
        "month": f"ОТЧЁТ ЗА {start.strftime('%B %Y').upper()}",
        "year": f"ОТЧЁТ ЗА {start.strftime('%Y')} ГОД",
    }
    
    ws["A1"] = period_titles.get(period, "ОТЧЁТ")
    ws["A1"].font = Font(bold=True, size=18, color=COLOR_HEADER)
    ws.merge_cells("A1:D1")
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30
    
    ws["A2"] = f"Сформирован: {datetime.now().strftime('%d.%m.%Y %H:%M')}   |   Валюта: {symbol} {display_currency}"
    ws["A2"].font = Font(italic=True, size=9, color="6B7280")
    ws.merge_cells("A2:D2")
    ws["A2"].alignment = Alignment(horizontal="center")
    
    ws.row_dimensions[3].height = 8
    
    # Метрики
    metrics = [
        ("💚 Доходы", convert(totals["income"]), COLOR_INCOME),
        ("❤️ Расходы", convert(totals["expense"]), COLOR_EXPENSE),
        ("💰 Баланс", convert(totals["balance"]), COLOR_ACCENT),
    ]
    
    row = 4
    for label, amount, color in metrics:
        ws.cell(row=row, column=1, value=label).font = Font(bold=True, size=13)
        
        amount_cell = ws.cell(row=row, column=2, value=round(amount, 2))
        amount_cell.number_format = f'#,##0.00 "{symbol}"'
        amount_cell.font = Font(bold=True, size=13, color=color)
        amount_cell.alignment = Alignment(horizontal="right")
        
        ws.row_dimensions[row].height = 22
        row += 1
    
    # Доп. инфа
    row += 1
    ws.cell(row=row, column=1, value="Всего операций:").font = Font(size=11)
    ws.cell(row=row, column=2, value=tx_count).font = Font(bold=True, size=11)
    ws.merge_cells(f"A{row}:D{row}")
    
    # Средний расход в день
    days_in_period = max((end - start).days, 1)
    avg_daily = totals["expense"] / days_in_period
    
    row += 1
    ws.cell(row=row, column=1, value="Средний расход в день:").font = Font(size=11)
    avg_cell = ws.cell(row=row, column=2, value=round(convert(avg_daily), 2))
    avg_cell.number_format = f'#,##0.00 "{symbol}"'
    avg_cell.font = Font(bold=True, size=11)
    
    # Ширина колонок
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 15
    ws.column_dimensions["D"].width = 15
    
    return ws


# ============================================================================
# ЛИСТ 2: ТРАНЗАКЦИИ
# ============================================================================

def build_transactions_sheet(
    wb: Workbook,
    user: User,
    transactions: list,
    rate: float | None,
):
    """Лист со всеми транзакциями."""
    ws = wb.create_sheet("Транзакции")
    
    display_currency = user.currency
    symbol = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(display_currency, display_currency)
    
    def convert(amount_rub: float) -> float:
        if display_currency == "RUB" or not rate:
            return amount_rub
        return amount_rub / rate
    
    # Заголовки
    headers = ["Дата", "Время", "Тип", "Категория", "Сумма", "Описание"]
    ws.append(headers)
    style_header_row(ws, 1, len(headers))
    ws.row_dimensions[1].height = 22
    
    # Сортируем по дате (старые → новые)
    sorted_tx = sorted(transactions, key=lambda t: t.created_at)
    
    for i, tx in enumerate(sorted_tx, start=2):
        # Конвертируем UTC → локальное время
        import pytz
        tz = pytz.timezone(user.timezone)
        local_dt = tx.created_at.replace(tzinfo=pytz.UTC).astimezone(tz)
        
        type_label = "💚 Доход" if tx.type == "income" else "❤️ Расход"
        cat_name = f"{tx.category.emoji} {tx.category.name}" if tx.category else "—"
        
        amount = convert(tx.amount)
        # Доход положительный, расход отрицательный для наглядности
        display_amount = amount  # оставим положительными, тип в отдельной колонке
        
        ws.cell(row=i, column=1, value=local_dt.strftime("%d.%m.%Y"))
        ws.cell(row=i, column=2, value=local_dt.strftime("%H:%M"))
        ws.cell(row=i, column=3, value=type_label)
        
        cat_cell = ws.cell(row=i, column=4, value=cat_name)
        
        amt_cell = ws.cell(row=i, column=5, value=round(display_amount, 2))
        amt_cell.number_format = f'#,##0.00 "{symbol}"'
        # Цвет суммы по типу
        amt_cell.font = Font(
            color=COLOR_INCOME if tx.type == "income" else COLOR_EXPENSE,
            bold=True
        )
        
        ws.cell(row=i, column=6, value=tx.description or "")
        
        style_data_row(ws, i, len(headers), alt=(i % 2 == 0))
    
    auto_width(ws)
    
    # Freeze первой строки (заголовки всегда видны)
    ws.freeze_panes = "A2"
    
    # Автофильтр
    ws.auto_filter.ref = f"A1:F{len(sorted_tx) + 1}"
    
    return ws


# ============================================================================
# ЛИСТ 3: КАТЕГОРИИ + PIE CHART
# ============================================================================

def build_categories_sheet(
    wb: Workbook,
    user: User,
    expense_by_cat: list[dict],
    income_by_cat: list[dict],
    rate: float | None,
):
    """Лист с агрегацией по категориям и круговой диаграммой."""
    ws = wb.create_sheet("Категории")
    
    display_currency = user.currency
    symbol = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(display_currency, display_currency)
    
    def convert(amount_rub: float) -> float:
        if display_currency == "RUB" or not rate:
            return amount_rub
        return amount_rub / rate
    
    row = 1
    
    # ===== РАСХОДЫ =====
    ws.cell(row=row, column=1, value="РАСХОДЫ ПО КАТЕГОРИЯМ").font = Font(bold=True, size=14, color=COLOR_EXPENSE)
    row += 1
    
    headers = ["Категория", "Сумма", "Доля", "Операций"]
    for col, h in enumerate(headers, start=1):
        ws.cell(row=row, column=col, value=h)
    style_header_row(ws, row, len(headers))
    header_row_expense = row
    row += 1
    
    expense_start_row = row
    total_expense = sum(c["total"] for c in expense_by_cat) or 1.0
    
    for cat in expense_by_cat:
        ws.cell(row=row, column=1, value=f"{cat['emoji']} {cat['name']}")
        
        amt = ws.cell(row=row, column=2, value=round(convert(cat["total"]), 2))
        amt.number_format = f'#,##0.00 "{symbol}"'
        
        pct = ws.cell(row=row, column=3, value=cat["total"] / total_expense)
        pct.number_format = "0.0%"
        
        ws.cell(row=row, column=4, value=cat["count"])
        
        style_data_row(ws, row, len(headers), alt=(row % 2 == 0))
        row += 1
    
    expense_end_row = row - 1
    
    # Итого
    ws.cell(row=row, column=1, value="ИТОГО").font = Font(bold=True)
    total_cell = ws.cell(row=row, column=2, value=round(convert(total_expense), 2))
    total_cell.number_format = f'#,##0.00 "{symbol}"'
    total_cell.font = Font(bold=True, color=COLOR_EXPENSE)
    ws.cell(row=row, column=3, value=1.0).number_format = "0.0%"
    ws.cell(row=row, column=4, value=sum(c["count"] for c in expense_by_cat)).font = Font(bold=True)
    for col in range(1, 5):
        ws.cell(row=row, column=col).border = THIN_BORDER
        ws.cell(row=row, column=col).fill = PatternFill("solid", fgColor="E5E7EB")
    row += 2
    
    # ===== PIE CHART для расходов =====
    if expense_by_cat:
        pie = PieChart()
        pie.title = f"Структура расходов ({symbol})"
        pie.height = 12
        pie.width = 18
        
        # Данные — колонки A (названия) и B (суммы)
        labels = Reference(ws, min_col=1, min_row=expense_start_row, max_row=expense_end_row)
        data = Reference(ws, min_col=2, min_row=expense_start_row - 1, max_row=expense_end_row)  # -1 захватывает заголовок
        
        pie.add_data(data, titles_from_data=True)
        pie.set_categories(labels)
        
        # Подписи с процентами
        pie.dataLabels = DataLabelList()
        pie.dataLabels.showPercent = True
        
        # Размещаем график справа от таблицы
        ws.add_chart(pie, f"F{header_row_expense}")
    
    # ===== ДОХОДЫ =====
    ws.cell(row=row, column=1, value="ДОХОДЫ ПО КАТЕГОРИЯМ").font = Font(bold=True, size=14, color=COLOR_INCOME)
    row += 1
    
    for col, h in enumerate(headers, start=1):
        ws.cell(row=row, column=col, value=h)
    style_header_row(ws, row, len(headers))
    row += 1
    
    income_start_row = row
    total_income = sum(c["total"] for c in income_by_cat) or 1.0
    
    for cat in income_by_cat:
        ws.cell(row=row, column=1, value=f"{cat['emoji']} {cat['name']}")
        
        amt = ws.cell(row=row, column=2, value=round(convert(cat["total"]), 2))
        amt.number_format = f'#,##0.00 "{symbol}"'
        
        pct = ws.cell(row=row, column=3, value=cat["total"] / total_income)
        pct.number_format = "0.0%"
        
        ws.cell(row=row, column=4, value=cat["count"])
        style_data_row(ws, row, len(headers), alt=(row % 2 == 0))
        row += 1
    
    income_end_row = row - 1
    
    # Итого
    ws.cell(row=row, column=1, value="ИТОГО").font = Font(bold=True)
    total_cell = ws.cell(row=row, column=2, value=round(convert(total_income), 2))
    total_cell.number_format = f'#,##0.00 "{symbol}"'
    total_cell.font = Font(bold=True, color=COLOR_INCOME)
    ws.cell(row=row, column=3, value=1.0).number_format = "0.0%"
    for col in range(1, 5):
        ws.cell(row=row, column=col).border = THIN_BORDER
        ws.cell(row=row, column=col).fill = PatternFill("solid", fgColor="E5E7EB")
    
    # Ширина
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 12
    
    return ws


# ============================================================================
# ЛИСТ 4: ТРЕНД ПО ДНЯМ + LINE CHART
# ============================================================================

def build_trend_sheet(
    wb: Workbook,
    user: User,
    transactions: list,
    start: datetime,
    end: datetime,
    rate: float | None,
):
    """Динамика расходов по дням + линия тренда."""
    import pytz
    ws = wb.create_sheet("Тренд")
    
    display_currency = user.currency
    symbol = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(display_currency, display_currency)
    
    def convert(amount_rub: float) -> float:
        if display_currency == "RUB" or not rate:
            return amount_rub
        return amount_rub / rate
    
    tz = pytz.timezone(user.timezone)
    
    # Группируем по дням
    by_day_expense = defaultdict(float)
    by_day_income = defaultdict(float)
    
    for tx in transactions:
        local_dt = tx.created_at.replace(tzinfo=pytz.UTC).astimezone(tz)
        date_str = local_dt.strftime("%d.%m")
        
        if tx.type == "expense":
            by_day_expense[date_str] += tx.amount
        else:
            by_day_income[date_str] += tx.amount
    
    # Заполняем все дни периода (включая пустые)
    local_start = start.replace(tzinfo=pytz.UTC).astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = end.replace(tzinfo=pytz.UTC).astimezone(tz)
    
    all_days = []
    current = local_start
    while current < local_end:
        all_days.append(current.strftime("%d.%m"))
        current += timedelta(days=1)
    
    # Заголовки
    ws.append(["Дата", "Расход", "Доход", "Сальдо"])
    style_header_row(ws, 1, 4)
    ws.row_dimensions[1].height = 22
    
    row = 2
    for day in all_days:
        ws.cell(row=row, column=1, value=day)
        
        exp = ws.cell(row=row, column=2, value=round(convert(by_day_expense.get(day, 0)), 2))
        exp.number_format = f'#,##0.00 "{symbol}"'
        exp.font = Font(color=COLOR_EXPENSE)
        
        inc = ws.cell(row=row, column=3, value=round(convert(by_day_income.get(day, 0)), 2))
        inc.number_format = f'#,##0.00 "{symbol}"'
        inc.font = Font(color=COLOR_INCOME)
        
        balance = by_day_income.get(day, 0) - by_day_expense.get(day, 0)
        bal = ws.cell(row=row, column=4, value=round(convert(balance), 2))
        bal.number_format = f'#,##0.00 "{symbol}"'
        
        style_data_row(ws, row, 4, alt=(row % 2 == 0))
        row += 1
    
    last_row = row - 1
    
    # ===== LINE CHART =====
    line = LineChart()
    line.title = f"Динамика по дням ({symbol})"
    line.style = 12
    line.height = 12
    line.width = 28
    line.y_axis.title = f"Сумма ({symbol})"
    line.x_axis.title = "Дата"
    
    # Данные: колонки B (Расход) и C (Доход)
    data = Reference(ws, min_col=2, max_col=3, min_row=1, max_row=last_row)
    cats = Reference(ws, min_col=1, min_row=2, max_row=last_row)
    
    line.add_data(data, titles_from_data=True)
    line.set_categories(cats)
    
    ws.add_chart(line, f"F2")
    
    # Ширина
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 16
    ws.column_dimensions["D"].width = 16
    
    return ws


# ============================================================================
# ЛИСТ 5: СРАВНЕНИЕ (BAR CHART)
# ============================================================================

def build_comparison_sheet(
    wb: Workbook,
    user: User,
    totals: dict,
    expense_by_cat: list[dict],
    rate: float | None,
):
    """Bar chart: топ категорий расходов."""
    ws = wb.create_sheet("Сравнение")
    
    display_currency = user.currency
    symbol = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(display_currency, display_currency)
    
    def convert(amount_rub: float) -> float:
        if display_currency == "RUB" or not rate:
            return amount_rub
        return amount_rub / rate
    
    # Таблица для барчарта (топ-10 категорий)
    ws.append(["Категория", "Сумма"])
    style_header_row(ws, 1, 2)
    
    top10 = expense_by_cat[:10]
    row = 2
    for cat in top10:
        ws.cell(row=row, column=1, value=f"{cat['emoji']} {cat['name']}")
        amt = ws.cell(row=row, column=2, value=round(convert(cat["total"]), 2))
        amt.number_format = f'#,##0.00 "{symbol}"'
        style_data_row(ws, row, 2, alt=(row % 2 == 0))
        row += 1
    
    last_row = row - 1
    
    # ===== BAR CHART =====
    if top10:
        bar = BarChart()
        bar.type = "bar"  # горизонтальные бары (удобнее для категорий)
        bar.title = f"Топ-10 категорий расходов ({symbol})"
        bar.style = 11
        bar.height = 14
        bar.width = 22
        bar.y_axis.title = f"Сумма ({symbol})"
        
        data = Reference(ws, min_col=2, min_row=1, max_row=last_row)
        cats = Reference(ws, min_col=1, min_row=2, max_row=last_row)
        
        bar.add_data(data, titles_from_data=True)
        bar.set_categories(cats)
        
        ws.add_chart(bar, "D2")
    
    # ===== Сравнение доход/расход =====
    comp_row = last_row + 3
    ws.cell(row=comp_row, column=1, value="Сравнение").font = Font(bold=True, size=12)
    
    ws.cell(row=comp_row + 1, column=1, value="Доход")
    inc_cell = ws.cell(row=comp_row + 1, column=2, value=round(convert(totals["income"]), 2))
    inc_cell.number_format = f'#,##0.00 "{symbol}"'
    
    ws.cell(row=comp_row + 2, column=1, value="Расход")
    exp_cell = ws.cell(row=comp_row + 2, column=2, value=round(convert(totals["expense"]), 2))
    exp_cell.number_format = f'#,##0.00 "{symbol}"'
    
    # Мини pie для доход/расход
    pie2 = PieChart()
    pie2.title = "Доход vs Расход"
    pie2.height = 8
    pie2.width = 12
    
    data2 = Reference(ws, min_col=2, min_row=comp_row + 1, max_row=comp_row + 2)
    labels2 = Reference(ws, min_col=1, min_row=comp_row + 1, max_row=comp_row + 2)
    
    pie2.add_data(data2, titles_from_data=False)
    pie2.set_categories(labels2)
    pie2.dataLabels = DataLabelList()
    pie2.dataLabels.showPercent = True
    
    ws.add_chart(pie2, "D" + str(comp_row))
    
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 18
    
    return ws


# ============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================================

async def generate_excel_report(
    session: AsyncSession,
    user: User,
    start: datetime,
    end: datetime,
    period: str,
) -> str:
    """
    Генерирует Excel-отчёт и возвращает путь к файлу.
    """
    # Создаём директорию если нет
    os.makedirs(EXCEL_EXPORT_DIR, exist_ok=True)
    
    # 1. Собираем данные
    totals = await get_totals(session, user.user_id, start, end)
    expense_by_cat = await get_by_category(session, user.user_id, start, end, "expense")
    income_by_cat = await get_by_category(session, user.user_id, start, end, "income")
    transactions = await get_transactions_by_period(
        session, user.user_id, start, end, limit=100000
    )
    
    # Курс валюты (если надо)
    rate = None
    if user.currency != "RUB":
        rate = await get_rate_rub(session, user.currency)
    
    # 2. Создаём рабочую книгу
    wb = Workbook()
    # Удаляем дефолтный лист
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]
    
    # 3. Генерируем листы
    build_summary_sheet(wb, user, start, end, totals, len(transactions), period, rate)
    build_transactions_sheet(wb, user, transactions, rate)
    build_categories_sheet(wb, user, expense_by_cat, income_by_cat, rate)
    build_trend_sheet(wb, user, transactions, start, end, rate)
    build_comparison_sheet(wb, user, totals, expense_by_cat, rate)
    
    # 4. Сохраняем
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{period}_{timestamp}.xlsx"
    file_path = os.path.join(EXCEL_EXPORT_DIR, filename)
    
    wb.save(file_path)
    
    return file_path