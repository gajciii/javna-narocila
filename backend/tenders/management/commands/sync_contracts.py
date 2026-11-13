from django.core.management.base import BaseCommand

from tenders.models import Tender
from tenders.pjn_contracts import sync_contracts, supported
from tenders.pipeline_jobs import enqueue_index


class Command(BaseCommand):
    help = 'Osveži javne pogodbe in naroči indeksiranje tudi za že uvožene zaključene razpise.'

    def add_arguments(self, parser):
        parser.add_argument('--tender', action='append', help='ID razpisa; ponovljiv. Privzeto vsi razpisi PJN.')

    def handle(self, *args, **options):
        records = Tender.objects.order_by('pk')
        if options['tender']:
            records = records.filter(pk__in=options['tender'])
        queued = failed = 0
        for tender in records.iterator():
            if not supported(tender):
                continue
            try:
                files = sync_contracts(tender)
                if files:
                    job = enqueue_index(tender, retry=True)
                    queued += 1
                    self.stdout.write(f'{tender.pk}: contracts={len(files)} job={job.pk} state={job.state}')
            except Exception as exc:
                failed += 1
                self.stderr.write(f'{tender.pk}: {type(exc).__name__}; ponovite osvežitev.')
        self.stdout.write(f'Razpisi s pogodbami: {queued}; napake: {failed}.')
