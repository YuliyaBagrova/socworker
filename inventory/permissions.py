"""Роли и доступ к разделу инвентаризации."""
from __future__ import annotations

from typing import Optional

from django.contrib.auth import get_user_model

User = get_user_model()


def inventory_role(user) -> Optional[str]:
    """
    Возвращает роль: warehouse_keeper | department_head | employee.
    Без профиля инвентаризации пользователь считается сотрудником (видит только свои единицы).
    Суперпользователь — завхоз.
    """
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'warehouse_keeper'
    profile = getattr(user, 'inventory_profile', None)
    if not profile:
        return 'employee'
    return profile.role


def can_manage_inventory(user) -> bool:
    return inventory_role(user) == 'warehouse_keeper'


def can_view_department_inventory(user) -> bool:
    r = inventory_role(user)
    return r in ('warehouse_keeper', 'department_head')


def has_inventory_access(user) -> bool:
    """Раздел доступен любому вошедшему пользователю."""
    return bool(user.is_authenticated)


def can_create_inventory_unit(user) -> bool:
    """Создавать единицу учёта может любой пользователь с доступом к разделу."""
    return has_inventory_access(user)
