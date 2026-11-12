from django.core.management.base import BaseCommand

from tenders.matching import effective_status
from tenders.models import Tender
from tenders.tender_conditions import extract_conditions


class Command(BaseCommand):
    help = 'Izlušči pogoje za sodelovanje iz že indeksirane dokumentacije (privzeto le odprti razpisi).'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='Vključi tudi zaprte razpise.')
        parser.add_argument('--force', action='store_true', help='Ponovi tudi že izluščene pogoje.')
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--tender', help='Samo en razpis (ID).')

    def handle(self, *args, **options):
        tenders = Tender.objects.filter(document_records__indexed_content__isnull=False).distinct().order_by('pk')
        if options['tender']:
            tenders = tenders.filter(pk=options['tender'])
        done = {}
        for tender in tenders.iterator():
            if not options['all'] and effective_status(tender.data) != 'open':
                continue
            record = extract_conditions(tender, force=options['force'])
            done[record.mode] = done.get(record.mode, 0) + 1
            self.stdout.write(f'{tender.pk}: {record.mode}, {len(record.conditions)} pogojev')
            if options['limit'] and sum(done.values()) >= options['limit']:
                break
        self.stdout.write(self.style.SUCCESS(f'Končano: {done}'))
