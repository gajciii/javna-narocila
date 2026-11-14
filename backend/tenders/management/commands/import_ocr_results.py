import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from tenders.ocr_import import import_results


class Command(BaseCommand):
    help = 'Ciljno vključi shranjene OCR rezultate v lokalni indeks, brez AI ali embeddingov.'

    def add_arguments(self, parser):
        parser.add_argument('directory')
        parser.add_argument('--apply', action='store_true', help='Brez te zastavice samo preveri obseg sprememb.')
        parser.add_argument('--backup', help='JSONL varnostna kopija spremenjenih dokumentov; obvezna z --apply.')
        parser.add_argument('--report', help='Pot za JSON poročilo.')

    def handle(self, *args, **options):
        if not Path(options['directory']).is_dir():
            raise CommandError('Mapa z OCR rezultati ne obstaja.')
        if options['apply'] and not options['backup']:
            raise CommandError('--apply zahteva --backup.')
        handle = open(options['backup'], 'x') if options['apply'] else None
        try:
            def backup(row):
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
                handle.flush()

            def progress(report):
                if report.get('groups_processed', 0) % 100 == 0:
                    self.stderr.write(f"groups={report['groups_processed']}/{report['groups']} "
                                      f"documents={report['documents_updated']}")

            report = import_results(options['directory'], apply=options['apply'],
                                    before_update=backup if handle else None, progress=progress)
        finally:
            if handle:
                handle.close()
        if options['report']:
            Path(options['report']).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        self.stdout.write(json.dumps(report, ensure_ascii=False))
