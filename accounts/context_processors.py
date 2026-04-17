"""Дополнительный контекст шаблонов."""

from .models import UserProfile


def user_nav_profile(request):
    """Аватар в шапке для авторизованных пользователей."""
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}
    profile = UserProfile.objects.filter(user_id=request.user.pk).first()
    return {'nav_user_profile': profile}
