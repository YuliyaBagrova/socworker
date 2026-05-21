"""Промежуточное ПО проекта."""

from inventory.permissions import has_inventory_access

SW_NAV_SESSION_KEY = 'sw_nav_context'

_INVENTORY_AUTH_PREFIXES = (
    '/inventory/login/',
    '/inventory/register/',
    '/inventory/logout/',
    '/inventory/auth/',
    '/inventory/portal/',
)


def _is_inventory_auth_path(path: str) -> bool:
    return any(path.startswith(p) for p in _INVENTORY_AUTH_PREFIXES)


class SwNavContextMiddleware:
    """
    Запоминает, из какого раздела пользователь пришёл: основное приложение (/accounts/…)
    или инвентаризация (/inventory/…). Страница профиля контекст не перезаписывает —
    чтобы подпись роли на «О пользователе» совпадала с последним открытым разделом.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return response
        path = request.path or ''
        if path.startswith('/inventory/') and not _is_inventory_auth_path(path):
            if has_inventory_access(user):
                request.session[SW_NAV_SESSION_KEY] = 'inventory'
        elif path.startswith('/accounts/') and '/profile/' not in path:
            request.session[SW_NAV_SESSION_KEY] = 'accounts'
        return response


class DisableBrowserCacheForAuthenticatedHtmlMiddleware:
    """
    Чтобы данные, изменённые одним пользователем, не «залипали» в кэше браузера
    у другого при обновлении страницы: для авторизованных GET-запросов HTML отключаем кэш.
    (Данные по-прежнему из БД; это убирает устаревшие копии страниц из bfcache/диска.)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            return response
        if request.method != 'GET':
            return response
        content_type = (response.get('Content-Type') or '').lower()
        if 'text/html' not in content_type:
            return response
        if response.get('Cache-Control'):
            return response
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private, max-age=0'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response
