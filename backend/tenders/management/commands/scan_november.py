import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from tenders.monthly_pipeline import run


class Command(BaseCommand):
    help = 'Zajame novembrske objave 2026 s prilogami in poišče dobaviteljske/podizvajalske priložnosti.'

    def add_arguments(self, parser):
        parser.add_argument('--max-notices', type=int, help='Omejen pilot; brez parametra obdela ves mesec do danes.')
        parser.add_argument('--terms', default='', help='Dodatni iskalni izrazi za profil, ločeni z vejico.')
        parser.add_argument('--profile', help='JSON profil podjetja za analizo, brez spremembe profila v aplikaciji.')
        parser.add_argument('--max-ai-questions', type=int, default=1000)
        parser.add_argument('--delay', type=float, default=0.5, help='Premor med objavami v sekundah.')
        parser.add_argument('--refresh', action='store_true', help='Ponovno obdela tudi zaključene objave.')
        parser.add_argument('--output', help='Pot do poročila JSON.')

    def handle(self, *args, **options):
        if settings.PIPELINE_REMOTE:
            raise CommandError('Za ločeni strežnik uporabite enqueue_pipeline --period 2026-11; '
                               'pregled prilog posameznega podjetja naročite v aplikaciji.')
        if options['max_notices'] is not None and options['max_notices'] < 1:
            raise CommandError('--max-notices mora biti pozitiven.')
        if options['max_ai_questions'] < 0 or options['delay'] < 0:
            raise CommandError('Omejitve in premor ne smejo biti negativni.')
        try:
            profile = None
            if options['profile']:
                profile = json.loads(Path(options['profile']).read_text(encoding='utf-8'))
                if not isinstance(profile, dict) or not isinstance(profile.get('activity'), str):
                    raise ValueError('Profil JSON mora vsebovati besedilno polje activity.')
                for field in ('expertise', 'keywords', 'technologies'):
                    value = profile.setdefault(field, [])
                    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                        raise ValueError(f'Polje {field} mora biti seznam besedil.')
            result = run(max_notices=options['max_notices'], extra_terms=options['terms'],
                         max_ai_questions=options['max_ai_questions'], delay=options['delay'],
                         refresh=options['refresh'], output=options['output'], supplied_profile=profile)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=True))
