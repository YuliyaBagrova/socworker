"""Роли и доступ к разделу инвентаризации."""
from __future__ import annotations

from typing import Optional

from .inv_user_sql import inv_role_code_for_user


def inventory_role(user) -> Optional[str]:
    """
    Код роли: warehouse_keeper | department_head | employee.
    Суперпользователь — завхоз. Без записи в inv_roles — сотрудник.
    """
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'warehouse_keeper'
    code = inv_role_code_for_user(user.pk)
    if not code:
        return 'employee'
    return code


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
