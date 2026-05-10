"""Ограничение отчётов для роли «Управляющий инвентарём» (только инвентаризация)."""
from django.contrib import messages
from django.shortcuts import redirect

from inventory.permissions import is_inventory_manager_interface_user

INV_MANAGER_REPORT_MSG = (
    'Для роли «Управляющий инвентарём» доступен только отчёт по инвентаризации.'
)


def reject_inv_manager_unless_inventory_report(request, report_type: str):
    """Разрешён тип «inventory». Иначе — редирект на страницу выбора отчётов."""
    if not is_inventory_manager_interface_user(request.user):
        return None
    if report_type == 'inventory':
        return None
    messages.warning(request, INV_MANAGER_REPORT_MSG)
    return redirect('accounts:report_select')


def reject_inv_manager_soc_report(request):
    """Панельные PDF/CSV и прочие отчёты, не связанные с блоком Инвентаризация на /reports/."""
    if not is_inventory_manager_interface_user(request.user):
        return None
    messages.warning(request, INV_MANAGER_REPORT_MSG)
    return redirect('accounts:report_select')
