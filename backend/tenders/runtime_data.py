"""Application data excludes legacy demonstration records. Fixtures are test-only."""
from django.conf import settings


def test_fixtures_enabled():
    return getattr(settings, 'TEST_FIXTURE_DATA', False)


def application_tenders():
    from .models import Tender
    rows = Tender.objects.all()
    return rows if test_fixtures_enabled() else rows.filter(data__source_type='real')


def application_records(rows):
    return rows if test_fixtures_enabled() else rows.filter(source_type='real')
