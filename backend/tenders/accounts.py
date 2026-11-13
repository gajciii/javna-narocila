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
    return CompanyProfile.objects.filter(owner_id=account_id())


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
