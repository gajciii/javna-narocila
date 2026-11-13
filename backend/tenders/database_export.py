"""Portable application-data fixture; authentication data never leaves the server."""
import gzip
import io
from itertools import chain
from tempfile import TemporaryFile

from django.apps import apps
from django.core.serializers.json import Serializer
from django.db import connection, transaction
from django.db.models import Q


class ApplicationSerializer(Serializer):
    def get_dump_object(self, obj):
        data = super().get_dump_object(obj)
        # The corresponding auth.User records are deliberately not exported.
        if 'owner' in data['fields']:
            data['fields']['owner'] = None
        if obj._meta.label_lower == 'tenders.pipelinerun':
            data['fields']['requested_by'] = None
        return data


def database_archive():
    """Return an open temporary gzip file. The caller must close it after download."""
    archive = TemporaryFile(mode='w+b')
    already_atomic = connection.in_atomic_block
    try:
        with transaction.atomic():
            if connection.vendor == 'postgresql' and not already_atomic:
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            from .models import CompanyProfile
            from .improvements import company_key
            legacy_keys = [company_key({**row.data, 'owner_id': None})
                           for row in CompanyProfile.objects.filter(owner__isnull=True)]

            def export_rows(model):
                fields = {field.name for field in model._meta.fields}
                rows = model._base_manager.all()
                if 'owner' in fields:
                    rows = rows.filter(owner__isnull=True)
                if 'company_key' in fields:
                    rows = rows.filter(Q(company_key='') | Q(company_key__in=legacy_keys))
                return rows.order_by(model._meta.pk.name).iterator(chunk_size=200)

            models = apps.get_app_config('tenders').get_models()
            records = chain.from_iterable(export_rows(model) for model in models
                                          if model._meta.model_name not in ('tenderfollow', 'notificationread'))
            with gzip.GzipFile(fileobj=archive, mode='wb', compresslevel=1, mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding='utf-8') as output:
                    ApplicationSerializer().serialize(records, stream=output, ensure_ascii=False)
        archive.seek(0)
        return archive
    except BaseException:
        archive.close()
        raise
