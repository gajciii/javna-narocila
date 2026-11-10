from urllib.parse import urlparse
from django.http import JsonResponse


class LocalOnlyMutationMiddleware:
    """Protect the unauthenticated local demo from cross-origin browser writes."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('Origin')
            if origin:
                host = urlparse(origin).hostname
                if host not in ('localhost', '127.0.0.1', '::1', 'testserver'):
                    return JsonResponse({'error': 'Ta lokalni demo ne sprejema zahtev z drugih spletnih strani.'}, status=403)
        return self.get_response(request)
