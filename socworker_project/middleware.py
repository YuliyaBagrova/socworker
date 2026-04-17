"""Промежуточное ПО проекта."""


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
