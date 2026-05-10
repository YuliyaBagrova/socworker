"""Служебное хранение пароля для отображения администратору портала и уведомления о смене."""

from inventory.inv_user_sql import user_ids_with_inv_role_assigned
from inventory.permissions import is_inventory_manager_interface_user

from .admin_portal_staff_queries import user_is_soc_department_manager
from .models import AdminPortalPasswordChangeNotification, UserProfile


def user_matches_admin_portal_password_tables(user) -> bool:
    """
    Те же ограничения, что при построении таблиц панели администратора:
    вкладки инвентаризации — пользователь с назначенной inv_role_id (в том числе staff);
    первая таблица («Заведующие…» в смысле панели) — не staff, не суперпользователь,
    без пометки admin_panel_access у профиля, без назначенной роли инвентаризации.
    """
    if not user or getattr(user, 'is_anonymous', False):
        return False
    pk_raw = getattr(user, 'pk', None)
    if pk_raw is None:
        return False
    try:
        pid = int(pk_raw)
    except (TypeError, ValueError):
        return False
    if user.is_superuser:
        return False
    inv_rows = user_ids_with_inv_role_assigned()
    inv_norm = {_normalized_user_pk(x) for x in inv_rows if _normalized_user_pk(x) is not None}
    if pid in inv_norm:
        return True
    if user.is_staff:
        return False
    if UserProfile.objects.filter(user_id=pid, admin_panel_access=True).exists():
        return False
    return True


def _normalized_user_pk(raw):
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def remember_plaintext_password_if_missing_for_panel_tables(user, plaintext) -> None:
    """
    Сохранить пароль для колонки панели, если копии ещё нет (первый успешный вход или регистрация).
    Не перезаписывает уже сохранённое значение (чтобы сохранять пароль первого сохранённого входа).
    """
    if plaintext is None:
        return
    raw = plaintext if isinstance(plaintext, str) else str(plaintext)
    if raw == '':
        return
    if not user or not getattr(user, 'pk', None):
        return
    if not user_matches_admin_portal_password_tables(user):
        return
    prof = UserProfile.objects.filter(user=user).first()
    if prof and (prof.admin_portal_password_plaintext or '').strip():
        return
    store_plaintext_password_for_admin_panel(user, raw)


def store_plaintext_password_for_admin_panel(user, plaintext) -> None:
    """Последний заданный пароль (панель или форма смены) для колонки «Пароль»."""
    if not user or not getattr(user, 'pk', None):
        return
    if plaintext is None:
        return
    blob = plaintext if isinstance(plaintext, str) else str(plaintext)
    if not blob:
        return
    prof, _ = UserProfile.objects.get_or_create(user=user)
    prof.admin_portal_password_plaintext = blob[:256]
    prof.save(update_fields=['admin_portal_password_plaintext', 'updated_at'])


def record_self_password_change_for_admin_notifications(user, new_plaintext: str) -> None:
    """После успешной смены пароля пользователем: сохранить копию и при необходимости — уведомление."""
    store_plaintext_password_for_admin_panel(user, new_plaintext)

    role_label = None
    if is_inventory_manager_interface_user(user):
        role_label = 'Управляющий инвентарём'
    elif user_is_soc_department_manager(user):
        role_label = 'Заведующий отделением'
    else:
        return

    AdminPortalPasswordChangeNotification.objects.create(
        user=user,
        username=user.get_username() or '',
        role_label=role_label,
        new_password_plaintext=(new_plaintext or '')[:256],
    )


def plaintext_password_map_for_user_ids(user_ids):
    """user_id → сохранённая строка для таблицы панели (ключи — int)."""
    ids = []
    for i in user_ids:
        nk = _normalized_user_pk(i)
        if nk is not None:
            ids.append(nk)
    if not ids:
        return {}
    return dict(
        UserProfile.objects.filter(user_id__in=ids).values_list(
            'user_id', 'admin_portal_password_plaintext',
        ),
    )
