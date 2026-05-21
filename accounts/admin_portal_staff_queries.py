"""Выборки пользователей для панели администратора портала."""

from django.contrib.auth import get_user_model

from inventory.inv_user_sql import user_ids_with_inv_role_assigned
from inventory.permissions import has_inventory_access

from .admin_portal_permissions import has_admin_panel_access
from .models import UserProfile

User = get_user_model()

# Совпадает с подписью на «О пользователе» (см. profile_interface_role): не staff/superuser,
# нет доступа к панели администратора и нет роли инвентаризации в auth_user.
SOC_DEPARTMENT_MANAGER_ROLE_CODE = 'soc_department_manager'


def user_is_soc_department_manager(user) -> bool:
    """Тот же смысл, что вариант роли «department» в профиле — основное приложение (соцработники и др.)."""
    if not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser or user.is_staff:
        return False
    if has_admin_panel_access(user):
        return False
    if has_inventory_access(user):
        return False
    return True


def soc_department_managers_rows_for_admin_panel():
    """
    Учётные записи заведующих отделением в смысле основного приложения (управление соцработниками и т.д.).
    """
    inv_assigned = set(user_ids_with_inv_role_assigned())
    portal_admin_ids = set(
        UserProfile.objects.filter(admin_panel_access=True).values_list('user_id', flat=True)
    )
    qs = User.objects.filter(is_superuser=False, is_staff=False).order_by(
        'last_name', 'first_name', 'username',
    )
    rows = []
    for u in qs.iterator():
        if u.pk in portal_admin_ids:
            continue
        if u.pk in inv_assigned:
            continue
        rows.append({
            'id': u.pk,
            'username': u.username or '',
            'email': u.email or '',
            'is_active': bool(u.is_active),
            'first_name': u.first_name or '',
            'last_name': u.last_name or '',
            'role_code': SOC_DEPARTMENT_MANAGER_ROLE_CODE,
            'role_name': 'Заведующий отделением',
            'department_name': '—',
        })
    return rows
