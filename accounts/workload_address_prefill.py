"""
Автозаполнение «Расчёта нагрузки» из карточки подопечного: поиск пункта и типа жилья по полю «Адрес».
"""
from __future__ import annotations

import re
from typing import Optional, TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from .models import ServiceRecipient


def housing_type_from_address(address: str) -> Optional[str]:
    """
    'apartment' | 'house' | None.
    None — в тексте нет уверенных маркеров, брать ServiceRecipient.housing_type.
    """
    if not address or not str(address).strip():
        return None
    t = ' '.join(str(address).lower().split())
    if _looks_like_apartment(t):
        return 'apartment'
    if _looks_like_house(t):
        return 'house'
    return None


def _looks_like_apartment(t: str) -> bool:
    if re.search(r'квартир', t) or re.search(r'кв\.?\s*№\s*\d', t) or re.search(r'кв\.?\d', t):
        return True
    if re.search(r'(?<![а-яёa-zа-я])кв[.\s]', t) or re.search(r'\bкв\s', t):
        return True
    if 'кварти' in t:
        return True
    return False


def _looks_like_house(t: str) -> bool:
    if re.search(r'частн(ый|ого|о)?\s+д', t):
        return True
    if 'коттедж' in t:
        return True
    if 'садов' in t and 'това' not in t:
        return True
    if re.search(r'снт|днп|д\.?п\.', t):
        return True
    if re.search(r'домовлад', t):
        return True
    if re.search(r'(?<![а-яёa-z/])дом(?![а-яёa-z0-9])', t) and 'кварт' not in t and 'кв.' not in t and not re.search(r'кв\.\d', t):
        return True
    return False


def location_id_from_address(address: str, locations: Sequence) -> Optional[int]:
    """
    Ищет по справочнику населённых пунктов: имя пункта входит в текст адреса.
    Предпочтение — самая длинная из подходящих подстрок, чтобы «Минск» не конкурировал с «О».
    """
    if not address or not str(address).strip() or not locations:
        return None
    low = str(address).lower()
    best_id = None
    best_len = 0
    for loc in locations:
        n = (getattr(loc, 'name', None) or '').strip().lower()
        if len(n) < 2:
            continue
        if n in low and len(n) > best_len:
            best_id = int(loc.pk)
            best_len = len(n)
    return best_id


def resolve_workload_prefill_for_recipient(
    r: 'ServiceRecipient',
    all_locations: Sequence,
) -> tuple[Optional[int], str, str]:
    """
    location_id, housing_type, location_label (для JSON формы нагрузки).
    Пункт: в первую очередь по вхождению названия из «Адрес», иначе поле location.
    Тип жилья: в первую очередь эвристика по «Адрес», иначе поле housing_type.
    """
    addr = (r.address or '').strip()
    loc_id: Optional[int] = None
    if addr:
        loc_id = location_id_from_address(addr, all_locations)
    if loc_id is None:
        loc_id = r.location_id
    loc_obj = r.location
    if loc_id is not None and (loc_obj is None or int(loc_obj.pk) != int(loc_id)):
        loc_obj = next((x for x in all_locations if int(x.pk) == int(loc_id)), None)
    if loc_id is None:
        loc_obj = None
    if loc_obj is not None:
        label = f'{loc_obj.get_location_type_display()} {loc_obj.name}'
    else:
        label = ''
    h_type = (r.housing_type or 'apartment')
    if addr:
        h_from = housing_type_from_address(addr)
        if h_from:
            h_type = h_from
    return (loc_id, h_type, label)
