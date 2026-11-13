from django.core.management.base import BaseCommand, CommandError

from tenders.embeddings import embed_pending, enabled, pending_counts


class Command(BaseCommand):
    help = 'Izračuna manjkajoče semantične vektorje (delavec to sicer počne v prostem času).'

    def add_arguments(self, parser):
        parser.add_argument('--status', action='store_true', help='Samo izpiše število manjkajočih vektorjev.')
        parser.add_argument('--max-batches', type=int, default=0, help='0 pomeni do konca.')

    def handle(self, *args, **options):
        if options['status']:
            self.stdout.write(str(pending_counts()))
            return
        if not enabled():
            raise CommandError('Vektorji zahtevajo PostgreSQL s pgvector in OPENROUTER_API_KEY.')
        batches = filled = 0
        while not options['max_batches'] or batches < options['max_batches']:
            done = embed_pending()
            if not done:
                break
            batches += 1
            filled += done
            if batches % 50 == 0:
                self.stdout.write(f'{filled} vektorjev, manjka {pending_counts()}')
        self.stdout.write(f'Končano: {filled} vektorjev v {batches} paketih.')
