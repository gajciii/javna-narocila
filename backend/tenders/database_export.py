"""Portable application-data fixture; authentication data never leaves the server."""
import gzip
import io
from itertools import chain
from tempfile import TemporaryFile

from django.apps import apps
from django.core.serializers.json import Serializer
from django.db import connection, transaction


class ApplicationSerializer(Serializer):
    def get_dump_object(self, obj):
        data = super().get_dump_object(obj)
        # The corresponding auth.User records are deliberately not exported.
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
            models = apps.get_app_config('tenders').get_models()
            records = chain.from_iterable(
                model._base_manager.order_by(model._meta.pk.name).iterator(chunk_size=200)
                for model in models)
            with gzip.GzipFile(fileobj=archive, mode='wb', compresslevel=1, mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding='utf-8') as output:
                    ApplicationSerializer().serialize(records, stream=output, ensure_ascii=False)
        archive.seek(0)
        return archive
    except BaseException:
        archive.close()
        raise
