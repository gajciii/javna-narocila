"""Request-local account scope, shared by views and profile-dependent services."""
from contextlib import contextmanager
from contextvars import ContextVar

_account_id = ContextVar('account_id', default=None)


def account_id():
    return _account_id.get()


@contextmanager
def account_scope(user_id):
    token = _account_id.set(user_id)
    try:
        yield
    finally:
        _account_id.reset(token)


def companies():
    from .models import CompanyProfile
    from django.db.models import Q
    from .runtime_data import test_fixtures_enabled
    rows = CompanyProfile.objects.filter(owner_id=account_id())
    if not test_fixtures_enabled():
        rows = rows.exclude(Q(data__has_key='source', data__source='demo') |
                            Q(data__has_key='registration_number', data__registration_number__startswith='DEMO'))
    return rows


def searches():
    from .models import SavedSearch
    return SavedSearch.objects.filter(owner_id=account_id())


def lock_account():
    from django.contrib.auth import get_user_model
    from .models import CompanyProfile
    if account_id() is not None:
        get_user_model().objects.select_for_update().get(pk=account_id())
    else:
        CompanyProfile.objects.select_for_update().filter(owner__isnull=True).first()


def following(tender):
    from .models import TenderFollow
    if account_id() is None:
        return tender.following
    if hasattr(tender, '_account_following'):
        return tender._account_following
    return TenderFollow.objects.filter(owner_id=account_id(), tender=tender).exists()


def ignored(tender):
    from .models import TenderIgnore
    if hasattr(tender, '_account_ignored'):
        return tender._account_ignored
    return TenderIgnore.objects.filter(owner_id=account_id(), tender=tender).exists()
