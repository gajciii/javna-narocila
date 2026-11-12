import hashlib
from django.core.management.base import BaseCommand
from botocore.exceptions import ClientError
from django.conf import settings
from tenders.models import Document
from tenders.pipeline_storage import client, store
from pathlib import Path


class Command(BaseCommand):
    help = 'Ustvari zasebno S3 vedro in po izbiri prenese obstoječe lokalne dokumente.'

    def add_arguments(self, parser):
        parser.add_argument('--migrate-files', action='store_true')

    def handle(self, *args, **options):
        s3 = client()
        try:
            s3.head_bucket(Bucket=settings.PIPELINE_S3_BUCKET)
        except ClientError as exc:
            if exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 404:
                raise
            s3.create_bucket(Bucket=settings.PIPELINE_S3_BUCKET)
        moved = 0
        if options['migrate_files']:
            for document in Document.objects.exclude(path__startswith='s3://').iterator():
                path = Path(document.path)
                if not path.is_file():
                    self.stderr.write(f'Manjka lokalna datoteka za {document.pk}.')
                    continue
                h = hashlib.sha256()
                with path.open('rb') as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b''):
                        h.update(block)
                document.path = store(path, h.hexdigest())
                document.sha256 = h.hexdigest()
                document.save(update_fields=['path', 'sha256'])
                moved += 1
        self.stdout.write(f'Skupna shramba je pripravljena; prenesenih {moved} datotek.')
