"""Эффективные секретные коды: переопределение из БД или настройки Django (окружение)."""

from django.conf import settings

from .models import PortalAuthenticationCodes


def get_inventory_authentication_code() -> str:
    row = PortalAuthenticationCodes.objects.filter(pk=1).first()
    if row and (row.inventory_code_override or '').strip():
        return row.inventory_code_override.strip()
    raw = getattr(settings, 'INVENTORY_AUTHENTICATION_CODE', None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return 'admin'


def get_admin_panel_authentication_code() -> str:
    row = PortalAuthenticationCodes.objects.filter(pk=1).first()
    if row and (row.admin_panel_code_override or '').strip():
        return row.admin_panel_code_override.strip()
    raw = getattr(settings, 'ADMIN_PANEL_AUTHENTICATION_CODE', None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return 'administrator'
