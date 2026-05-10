"""Роли и доступ к разделу инвентаризации."""
from __future__ import annotations

from typing import Optional

from .inv_user_sql import inv_role_code_for_user, inv_role_id_for_user
from .models import InvRole

INVENTORY_ACCOUNTABLE_CODE = 'inventory_accountable'


def inventory_role(user) -> Optional[str]:
    """Название роли инвентаризации для подписей в интерфейсе (из БД)."""
    if not user.is_authenticated:
        return None
    if user.is_superuser and inv_role_id_for_user(user.pk) is None:
        return 'Администратор'
    code = inv_role_code_for_user(user.pk)
    if not code:
        return 'Администратор' if user.is_superuser else None
    role = InvRole.objects.filter(code=code).first()
    return role.name if role else code


def can_manage_inventory(user) -> bool:
    """Отделения, список пользователей инвентаризации, назначение ответственных."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    code = inv_role_code_for_user(user.pk)
    return code in ('warehouse_keeper', INVENTORY_ACCOUNTABLE_CODE)


def can_view_department_inventory(user) -> bool:
    r = inventory_role(user)
    return bool(r)


def has_inventory_access(user) -> bool:
    """Доступ к панели инвентаризации: профиль inv_role_id в учётной записи или суперпользователь."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return inv_role_id_for_user(user.pk) is not None


def is_inventory_manager_interface_user(user) -> bool:
    """
    Роль «Управляющий инвентарём» в UI: только код инвентаризации inventory_accountable,
    без Django admin / панели администратора приложения.
    Заведующий отделением (department_head) с доступом к инвентаризации сюда не входит.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return False
    from accounts.admin_portal_permissions import has_admin_panel_access

    if has_admin_panel_access(user):
        return False
    code = inv_role_code_for_user(user.pk)
    return code == INVENTORY_ACCOUNTABLE_CODE


def can_create_inventory_unit(user) -> bool:
    """Создавать единицу учёта может любой пользователь с доступом к разделу."""
    return has_inventory_access(user)


def users_share_inventory_inv_role(user_a_id: int, user_b_id: int) -> bool:
    """Одинаковый inv_role_id в auth_user (включая оба NULL)."""
    return inv_role_id_for_user(user_a_id) == inv_role_id_for_user(user_b_id)


def can_modify_inventory_unit(user, unit) -> bool:
    """
    Правка / удаление / фото: нельзя для записей, созданных другим пользователем
    с той же ролью инвентаризации (inv_role_id). Суперпользователь — без ограничений.
    Старые записи без created_by доступны всем для правки.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    creator_id = getattr(unit, 'created_by_id', None)
    if not creator_id:
        return True
    if creator_id == user.pk:
        return True
    if users_share_inventory_inv_role(creator_id, user.pk):
        return False
    return True
