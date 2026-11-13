from urllib.parse import urlparse
from django.http import JsonResponse
from django.conf import settings
from rest_framework.authentication import CSRFCheck


class HostedAccessMiddleware:
    """Require an account for app data and bind its scope for downstream services."""
    public_paths = {'/api/health', '/api/auth/session', '/api/auth/register', '/api/auth/login', '/api/auth/logout',
                    '/api/admin/pipeline/session', '/api/admin/pipeline/login', '/api/admin/pipeline/logout'}
    staff_mutations = {'/api/demo/reset', '/api/demo/event', '/api/import', '/api/sources/pjn/sync'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .accounts import account_scope
        user = request.user
        authenticated = user.is_authenticated and user.is_active
        protected = request.path.startswith('/api/') and request.path not in self.public_paths
        if protected:
            if (settings.ACCOUNT_REQUIRE_LOGIN or settings.HOSTED_REQUIRE_LOGIN) and not authenticated:
                return JsonResponse({'code': 'login_required', 'error': 'Za dostop do aplikacije se prijavite.'}, status=401)
            if request.path in self.staff_mutations and authenticated and not user.is_staff:
                return JsonResponse({'error': 'To dejanje je na voljo samo skrbnikom.'}, status=403)
            if authenticated and request.method not in ('GET', 'HEAD', 'OPTIONS', 'TRACE'):
                check = CSRFCheck(lambda request: None)
                check.process_request(request)
                if check.process_view(request, None, (), {}):
                    return JsonResponse({'error': 'Varnostni žeton ni veljaven. Osvežite stran in ponovite zahtevo.'}, status=403)
        with account_scope(user.pk if authenticated else None):
            response = self.get_response(request)
        if protected:
            response['Cache-Control'] = 'private, no-store'
        return response


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
