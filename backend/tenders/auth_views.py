"""Account registration and session authentication; staff uses the same Django session."""
import json

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods


def session_data(request):
    user = request.user
    authenticated = user.is_authenticated and user.is_active
    return {'authenticated': authenticated, 'csrf_token': get_token(request),
            'user': {'id': user.pk, 'username': user.username, 'email': user.email,
                     'is_staff': user.is_staff} if authenticated else None}


def payload(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, UnicodeDecodeError):
        raise ValueError('Neveljavna zahteva.')


def claim_legacy_workspace(user):
    """Only existing staff can inherit the old shared workspace, never a registrant."""
    if not user.is_staff:
        return
    from .models import (CompanyProfile, SavedSearch, Partner, ImprovementPlan, EspdDraft,
                         Notification, EmailNotificationSettings, NotificationEmail, Tender, TenderFollow)
    from .improvements import company_key
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        if CompanyProfile.objects.filter(owner=user).exists():
            return
        records = list(CompanyProfile.objects.select_for_update().filter(owner__isnull=True))
        if not records:
            return
        for record in records:
            old = company_key({**record.data, 'owner_id': None})
            new = company_key({**record.data, 'owner_id': user.pk})
            for model in (Partner, ImprovementPlan, EspdDraft, Notification):
                model.objects.filter(company_key=old).update(company_key=new)
        already_active = CompanyProfile.objects.filter(owner=user, is_active=True).exists()
        CompanyProfile.objects.filter(pk__in=[r.pk for r in records]).update(owner=user)
        if already_active:
            CompanyProfile.objects.filter(pk__in=[r.pk for r in records]).update(is_active=False)
        SavedSearch.objects.filter(owner__isnull=True).update(owner=user)
        if not EmailNotificationSettings.objects.filter(owner=user).exists():
            EmailNotificationSettings.objects.filter(owner__isnull=True).update(owner=user)
            NotificationEmail.objects.filter(owner__isnull=True).update(owner=user)
        TenderFollow.objects.bulk_create([TenderFollow(owner=user, tender=t) for t in Tender.objects.filter(following=True)], ignore_conflicts=True)


@never_cache
@ensure_csrf_cookie
@require_http_methods(['GET'])
def session_view(request):
    return JsonResponse(session_data(request))


@never_cache
@csrf_protect
@require_http_methods(['POST'])
def register_view(request):
    key = 'account-register:' + request.META.get('REMOTE_ADDR', '')
    attempts = cache.get(key, 0)
    if attempts >= 10:
        return JsonResponse({'error': 'Preveč poskusov registracije. Poskusite čez eno uro.'}, status=429)
    cache.set(key, attempts + 1, 3600)
    try:
        data = payload(request)
        email, password = data.get('email', ''), data.get('password', '')
        if not isinstance(email, str) or not isinstance(password, str) or len(email) > 150 or len(password) > 1024:
            raise ValueError('Preverite e-poštni naslov in geslo.')
        email = email.strip().lower()
        validate_email(email)
        if password != data.get('password_confirm'):
            raise ValueError('Gesli se ne ujemata.')
        user = get_user_model()(username=email, email=email)
        validate_password(password, user)
        with transaction.atomic():
            if get_user_model().objects.filter(email__iexact=email).exists():
                raise ValueError('Registracija s tem e-poštnim naslovom ni mogoča. Poskusite s prijavo.')
            user.set_password(password)
            user.save()
    except IntegrityError:
        return JsonResponse({'error': 'Registracija s tem e-poštnim naslovom ni mogoča. Poskusite s prijavo.'}, status=400)
    except (ValueError, ValidationError) as exc:
        return JsonResponse({'error': exc.messages if isinstance(exc, ValidationError) else str(exc)}, status=400)
    login(request, user)
    return JsonResponse(session_data(request), status=201)


@never_cache
@csrf_protect
@require_http_methods(['POST'])
def login_view(request):
    key = 'account-login:' + request.META.get('REMOTE_ADDR', '')
    failures = cache.get(key, 0)
    if failures >= 10:
        return JsonResponse({'error': 'Preveč neuspešnih prijav. Poskusite čez 15 minut.'}, status=429)
    try:
        data = payload(request)
        username, password = data.get('username', ''), data.get('password', '')
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 150 or len(password) > 1024:
            raise ValueError('Vnesite e-pošto in geslo.')
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    username = username.strip()
    if '@' in username:
        username = username.lower()
    user = authenticate(request, username=username, password=password)
    if not user or not user.is_active:
        cache.set(key, failures + 1, 900)
        return JsonResponse({'error': 'Prijava ni uspela. Preverite prijavne podatke.'}, status=403)
    cache.delete(key)
    claim_legacy_workspace(user)
    login(request, user)
    return JsonResponse(session_data(request))


@never_cache
@csrf_protect
@require_http_methods(['POST'])
def logout_view(request):
    logout(request)
    return JsonResponse(session_data(request))
