"""Дополнительный контекст шаблонов."""

from .models import UserProfile


def user_nav_profile(request):
    """Аватар в шапке для авторизованных пользователей."""
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}
    profile = UserProfile.objects.filter(user_id=request.user.pk).first()
    return {
        'nav_user_profile': profile,
        'sw_portal_admin_menu': bool(profile and profile.admin_panel_access),
    }


def admin_portal_shell(request):
    """Отдельная шапка без рабочих вкладок на URL панели администратора."""
    path = getattr(request, 'path', '') or ''
    if path.startswith('/accounts/admin-portal'):
        return {'sw_admin_portal_shell': True}
    return {'sw_admin_portal_shell': False}
