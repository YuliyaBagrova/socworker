"""
Общая логика: кратность посещения ↔ дни недели, проверка дат для визитов.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from collections import OrderedDict
from typing import Dict, List, Optional

RU_MONTHS = (
    '', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
    'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
)

RU_WEEKDAYS_SHORT = ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс')


def visits_per_week_from_frequency(visit_frequency: str) -> int:
    if visit_frequency == 'daily':
        return 7
    if visit_frequency in ('1', '2', '3', '4', '5'):
        return int(visit_frequency)
    return 0


def visit_weekday_flags(visit_days) -> List[bool]:
    """Пн–Вс (индекс 0 = понедельник)."""
    flags = [False] * 7
    if not visit_days or not str(visit_days).strip():
        return flags
    t = str(visit_days).lower().replace('ё', 'е')
    for part in t.replace(';', ',').split(','):
        p = part.strip()
        if not p:
            continue
        if p.startswith('пн') or 'понедельник' in p:
            flags[0] = True
        if p.startswith('вт') or 'вторник' in p:
            flags[1] = True
        if p.startswith('ср') or p == 'среда' or 'среду' in p or 'среды' in p:
            flags[2] = True
        if p.startswith('чт') or 'четверг' in p:
            flags[3] = True
        if p.startswith('пт') or 'пятниц' in p:
            flags[4] = True
        if p.startswith('сб') or 'суббот' in p:
            flags[5] = True
        if p.startswith('вс') or 'воскресен' in p:
            flags[6] = True
    if not any(flags):
        if 'пн' in t or 'понедельник' in t:
            flags[0] = True
        if 'вт' in t or 'вторник' in t:
            flags[1] = True
        if 'ср' in t or 'среда' in t or 'среду' in t:
            flags[2] = True
        if 'чт' in t or 'четверг' in t:
            flags[3] = True
        if 'пт' in t or 'пятниц' in t:
            flags[4] = True
        if 'сб' in t or 'суббот' in t:
            flags[5] = True
        if 'вс' in t or 'воскресен' in t:
            flags[6] = True
    return flags


def count_marked_weekdays(visit_days) -> int:
    return sum(visit_weekday_flags(visit_days))


def validate_visit_frequency_and_days(visit_frequency: Optional[str], visit_days) -> Optional[str]:
    """
    Проверка согласованности кратности и перечисленных дней.
    None — всё в порядке; иначе текст ошибки для пользователя.
    """
    if not visit_frequency:
        return None
    vd = (visit_days or '').strip()
    flags = visit_weekday_flags(visit_days)
    n = sum(flags)
    exp = visits_per_week_from_frequency(visit_frequency)

    if visit_frequency == 'daily':
        if not vd:
            return None
        if n != 7:
            return (
                'При кратности «Ежедневно» оставьте «Дни посещений» пустыми '
                '(считаются все дни) или укажите все семь дней недели. '
                f'Сейчас распознано дней: {n}.'
            )
        return None

    if not vd:
        return (
            f'Укажите дни посещений через запятую (например: Пн, Ср, Пт). '
            f'Число дней должно совпадать с кратностью: {exp} раз(а) в неделю.'
        )

    if n != exp:
        return (
            f'Кратность — {exp} раз(а) в неделю, а в «Днях посещений» распознано '
            f'{n} дн. Числа должны совпадать.'
        )
    if n == 0:
        return 'Не удалось распознать дни недели в «Днях посещений». Используйте: Пн, Вт, Ср, …'
    return None


def plan_day_entries(rec_list: list, d: date, planned_by_date: Optional[Dict[date, list]] = None) -> list:
    """
    Объединяет визиты по графику подопечного и строки PlannedVisit на дату.
    Каждый элемент: dict с ключами recipient, worker, from_schedule (bool), planned_visit (или None).
    """
    if planned_by_date is None:
        planned_by_date = {}
    by_rid = OrderedDict()
    for r in rec_list:
        if recipient_visits_on_date(r, d):
            by_rid[r.pk] = {
                'recipient': r,
                'worker': r.social_worker,
                'from_schedule': True,
                'planned_visit': None,
            }
    for pv in planned_by_date.get(d, ()):
        rid = pv.recipient_id
        if rid in by_rid:
            by_rid[rid]['planned_visit'] = pv
            by_rid[rid]['worker'] = pv.social_worker
        else:
            by_rid[rid] = {
                'recipient': pv.recipient,
                'worker': pv.social_worker,
                'from_schedule': False,
                'planned_visit': pv,
            }
    entries = list(by_rid.values())
    entries.sort(key=lambda e: (
        (e['worker'].last_name or '') if e['worker'] else '',
        (e['worker'].first_name or '') if e['worker'] else '',
        e['recipient'].last_name or '',
        e['recipient'].first_name or '',
        e['planned_visit'].pk if e['planned_visit'] else 0,
    ))
    return entries


def recipient_visits_on_date(recipient, d: date) -> bool:
    """Есть ли у подопечного визит в этот календарный день (по правилам графика)."""
    wd = d.weekday()
    flags = visit_weekday_flags(recipient.visit_days)

    if recipient.visit_frequency == 'daily':
        if not any(flags):
            return True
        return flags[wd]

    if not any(flags):
        return False
    return flags[wd]


def week_start_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def add_months(d: date, delta: int) -> date:
    m = d.month - 1 + delta
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


def ru_month_year(d: date) -> str:
    return f'{RU_MONTHS[d.month]} {d.year}'


def calendar_month_grid(year: int, month: int, rec_list: list, planned_by_date=None):
    """Список недель; каждая ячейка — dict: date, in_month, count, is_weekend."""
    first = date(year, month, 1)
    start = week_start_monday(first)
    last_day_num = monthrange(year, month)[1]
    last = date(year, month, last_day_num)
    end_sunday = last + timedelta(days=6 - last.weekday())

    weeks = []
    cur = start
    while cur <= end_sunday:
        row = []
        for i in range(7):
            d = cur + timedelta(days=i)
            cnt = len(plan_day_entries(rec_list, d, planned_by_date))
            row.append({
                'date': d,
                'in_month': d.month == month,
                'count': cnt,
                'is_weekend': d.weekday() >= 5,
            })
        weeks.append(row)
        cur += timedelta(days=7)
    return weeks
