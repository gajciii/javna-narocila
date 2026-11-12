from urllib.parse import urlparse
from django.http import JsonResponse
from django.conf import settings
from rest_framework.authentication import CSRFCheck


class HostedAccessMiddleware:
    """The hosted single-company application uses the existing staff login."""
    public_paths = {'/api/health', '/api/admin/pipeline/session', '/api/admin/pipeline/login', '/api/admin/pipeline/logout'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.HOSTED_REQUIRE_LOGIN and request.path.startswith('/api/') and request.path not in self.public_paths:
            user = request.user
            if not (user.is_authenticated and user.is_active and user.is_staff):
                return JsonResponse({'code': 'login_required', 'error': 'Za dostop do aplikacije se prijavite.'}, status=401)
            if request.method not in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
                check = CSRFCheck(lambda request: None)
                check.process_request(request)
                if check.process_view(request, None, (), {}):
                    return JsonResponse({'error': 'Varnostni žeton ni veljaven. Osvežite stran in ponovite zahtevo.'}, status=403)
        return self.get_response(request)


class LocalOnlyMutationMiddleware:
    """Protect the unauthenticated local demo from cross-origin browser writes."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('Origin')
            if origin:
                if settings.PUBLIC_APP_URL:
                    if origin not in settings.CSRF_TRUSTED_ORIGINS:
                        return JsonResponse({'error': 'Izvor zahteve ni dovoljen.'}, status=403)
                    return self.get_response(request)
                host = urlparse(origin).hostname
                if host not in ('localhost', '127.0.0.1', '::1', 'testserver'):
                    return JsonResponse({'error': 'Ta lokalni demo ne sprejema zahtev z drugih spletnih strani.'}, status=403)
        return self.get_response(request)
