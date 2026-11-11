from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from tenders.models import Tender
from tenders.relevance_eval import (DEFAULT_FILE, EVAL_PROFILES, LABELS, dumps, export_rows, gemini_settings,
                                    read_rows, run)

APPROACHES = ['rules', 'llm', 'gemini']


def pct(value):
    return '—' if value is None else f'{value * 100:.0f} %'


class Command(BaseCommand):
    help = ('Primerjava pristopov za vsebinsko ujemanje na ročno označenem naboru. '
            '"export" pripravi CSV za označevanje, "run" izmeri pravila, LLM in Gemini Decisions API.')

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='action', required=True)
        export = sub.add_parser('export', help='Zapiše pare izmišljen profil × resničen razpis; obstoječe oznake ostanejo.')
        export.add_argument('--file', default=str(DEFAULT_FILE))
        export.add_argument('--profiles', help='Seznam profilov, ločen z vejico: ' + ', '.join(EVAL_PROFILES))
        evaluate = sub.add_parser('run', help='Izmeri pristope na označenih vrsticah.')
        evaluate.add_argument('--file', default=str(DEFAULT_FILE))
        evaluate.add_argument('--approaches', default=','.join(APPROACHES))
        evaluate.add_argument('--out', help='Shrani metrike in napovedi po vrsticah v JSON.')
        evaluate.add_argument('--show-errors', action='store_true', help='Izpiše vrstice, kjer se pristop moti.')

    def handle(self, *args, **options):
        if options['action'] == 'export':
            return self.export(options)
        return self.evaluate(options)

    def export(self, options):
        profile_ids = [p.strip() for p in options['profiles'].split(',')] if options['profiles'] else None
        unknown = set(profile_ids or []) - set(EVAL_PROFILES)
        if unknown:
            raise CommandError('Neznan profil: ' + ', '.join(sorted(unknown)))
        try:
            rows = export_rows(Tender.objects.order_by('pk'), options['file'], profile_ids)
        except ValueError as exc:
            raise CommandError(str(exc))
        labelled = sum(1 for r in rows if r['label'])
        self.stdout.write(f"Zapisano {len(rows)} vrstic v {options['file']} ({labelled} že označenih). "
                          f"V stolpec label vpišite: {', '.join(LABELS)} (ali n/d/p).")

    def evaluate(self, options):
        if not Path(options['file']).exists():
            raise CommandError(f"Datoteke {options['file']} ni. Najprej zaženite: relevance_eval export")
        approaches = [a.strip() for a in options['approaches'].split(',') if a.strip()]
        if set(approaches) - set(APPROACHES):
            raise CommandError('Dovoljeni pristopi: ' + ', '.join(APPROACHES))
        try:
            rows = read_rows(options['file'])
        except ValueError as exc:
            raise CommandError(str(exc))
        labelled = [r for r in rows if r['label']]
        if not labelled:
            raise CommandError('Nobena vrstica še ni označena.')
        key, model = gemini_settings()
        try:
            results = run(rows, approaches, key, model)
        except Exception as exc:  # noqa: BLE001 - surface provider failures without payloads or keys
            raise CommandError(f'Primerjava ni uspela: {type(exc).__name__}: {exc}')
        counts = {label: sum(1 for r in labelled if r['label'] == label) for label in LABELS}
        self.stdout.write(f"Označenih {len(labelled)} od {len(rows)} vrstic: " + ', '.join(f'{k} {v}' for k, v in counts.items()))
        self.stdout.write(f"{'pristop':<8} {'točnost':>8} {'makro F1':>9} {'prim. natančnost':>17} {'prim. priklic':>14} {'hude napake':>12} {'Brier':>6}")
        for approach, result in results.items():
            if 'skipped' in result:
                self.stdout.write(f'{approach:<8} preskočeno ({result["skipped"]})')
                continue
            m = result['metrics']
            brier = f"{m['brier']:.3f}" if 'brier' in m else '—'
            self.stdout.write(f"{approach:<8} {pct(m['accuracy']):>8} {pct(m['macro_f1']):>9} {pct(m['fit_precision']):>17} "
                              f"{pct(m['fit_recall']):>14} {m['severe_errors']:>12} {brier:>6}")
            if m['predicted'] < m['labelled']:
                self.stdout.write(f"         brez napovedi za {m['labelled'] - m['predicted']} vrstic")
        if options['show_errors']:
            for approach, result in results.items():
                for row in labelled:
                    pred = result.get('predictions', {}).get(f"{row['profile_id']}/{row['tender_id']}")
                    if pred and pred['label'] != row['label']:
                        self.stdout.write(f"[{approach}] {row['profile_id']} · {row['title'][:70]}: "
                                          f"oznaka {row['label']}, napoved {pred['label']}")
        if options['out']:
            Path(options['out']).write_text(dumps(results), encoding='utf-8')
            self.stdout.write(f"Rezultati: {options['out']}")
