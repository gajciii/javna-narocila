from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from tenders.pipeline_storage import client


class Command(BaseCommand):
    help = 'Preveri zasebno povezavo spletnega strežnika do PostgreSQL-a in shrambe pipelinea.'

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql' or not settings.PIPELINE_REMOTE or not settings.PIPELINE_S3_ENDPOINT:
            raise CommandError('Nastavite PostgreSQL, PIPELINE_REMOTE=1 in zasebno S3 shrambo.')
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
        except Exception as exc:
            raise CommandError(f'PostgreSQL ni dosegljiv ({type(exc).__name__}). Preverite Tailscale in DATABASE_URL.') from None
        try:
            client().head_bucket(Bucket=settings.PIPELINE_S3_BUCKET)
        except Exception as exc:
            raise CommandError(f'Shramba ni dosegljiva ({type(exc).__name__}). Preverite zasebni naslov, vedro in dovoljenja.') from None
        self.stdout.write(self.style.SUCCESS('PostgreSQL in zasebna shramba sta dosegljiva.'))
