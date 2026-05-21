"""Доступ к панели администратора (управление учётными записями инвентаризации)."""
from __future__ import annotations

from accounts.models import UserProfile


def has_admin_panel_access(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return UserProfile.objects.filter(user_id=user.pk, admin_panel_access=True).exists()


def user_has_admin_panel_flag(user_id: int) -> bool:
    return UserProfile.objects.filter(user_id=user_id, admin_panel_access=True).exists()
