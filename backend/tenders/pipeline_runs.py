"""Audited collection requests consumed by the scheduler, never by the web request."""
import socket
import time
import uuid
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import PipelineAgent, PipelineControl, PipelineRun, PipelineRunItem, Tender
from .monthly_pipeline import grid_entries, month_dates
from .pipeline_jobs import close_processed_runs, enqueue_index, index_identity
from .pjn_sync import collect_notice, sync_awards


def register_agent(role):
    return PipelineAgent.objects.create(role=role, hostname=socket.gethostname()[:160])


def beat_agent(agent, state='idle', job_id=None, run_id=None):
    PipelineAgent.objects.filter(pk=agent.pk).update(last_seen=timezone.now(), state=state,
        job_id=job_id, run_id=run_id)


def deadline_ahead(data):
    """True when the tender states a submission deadline that has not passed yet."""
    try:
        return datetime.fromisoformat(data['deadline']) > timezone.now()
    except (KeyError, TypeError, ValueError):
        return False


def create_run(*, source, mode='monthly', period='', max_notices=None, requested_by=None, request_key=None,
               open_only=False):
    if mode not in ('monthly', 'existing'):
        raise ValueError('Izberite zajem meseca ali obstoječe razpise.')
    if mode == 'monthly':
        period = period or timezone.localdate().strftime('%Y-%m')
        month_dates(period)
    else:
        period = ''
    if max_notices is not None and (isinstance(max_notices, bool) or not isinstance(max_notices, int) or not 1 <= max_notices <= 5000):
        raise ValueError('Omejitev mora biti celo število od 1 do 5000 ali prazna.')
    if not isinstance(open_only, bool):
        raise ValueError('Neveljavna izbira odprtih razpisov.')
    defaults = dict(source=source, mode=mode, period=period, max_notices=max_notices, requested_by=requested_by,
                    open_only=open_only)
    if request_key:
        run, created = PipelineRun.objects.get_or_create(request_key=request_key, defaults=defaults)
        if not created and (run.mode, run.period, run.max_notices, run.open_only, run.requested_by_id) != (
                mode, period, max_notices, open_only, requested_by.pk if requested_by else None):
            raise ValueError('Identifikator zahteve je že uporabljen za drug zagon.')
        return run
    return PipelineRun.objects.create(**defaults)


def claim_run(schedule=False):
    now = timezone.now()
    with transaction.atomic():
        control, _ = PipelineControl.objects.get_or_create(pk=1)
        control = PipelineControl.objects.select_for_update().get(pk=control.pk)
        if PipelineRun.objects.filter(state='collecting', lease_until__gt=now).exists():
            return None
        run = PipelineRun.objects.filter(Q(state='queued') |
            Q(state='collecting', lease_until__lte=now)).order_by('created_at').first()
        if run is None and schedule and control.schedule_enabled and control.next_run_at <= now:
            # Closed procedures cannot be bid on; skipping them keeps the daily run small.
            run = create_run(source='scheduled', open_only=True)
            control.next_run_at = now + timedelta(days=1)
            control.save(update_fields=['next_run_at'])
        if run:
            run.state, run.lease = 'collecting', uuid.uuid4()
            run.lease_until = now + timedelta(minutes=5)
            run.started_at = run.started_at or now
            run.save(update_fields=['state', 'lease', 'lease_until', 'started_at'])
        return run


def collect_run(run, agent=None):
    """Replays safely after interruption; a run links each shared job only once."""
    listed, skipped, errors, log = 0, 0, 0, []
    owned = lambda: PipelineRun.objects.filter(pk=run.pk, lease=run.lease, state='collecting')

    def progress():
        updated = owned().update(listed_count=listed, skipped_count=skipped, error_count=errors, error_log=log[-20:],
            lease_until=timezone.now() + timedelta(minutes=5))
        if agent:
            beat_agent(agent, 'working', run_id=run.pk)
        if not updated:
            raise RuntimeError('Zagon je prevzel drug scheduler.')

    try:
        if run.mode == 'existing':
            from .runtime_data import application_tenders
            records = application_tenders().order_by('pk')
            if run.max_notices:
                records = records[:run.max_notices]
            iterable = records.iterator()
        else:
            iterable = grid_entries(run.period)
        progress()
        for value in iterable:
            if run.max_notices is not None and listed >= run.max_notices:
                break
            listed += 1
            if run.mode == 'existing':
                tender = value
            elif run.open_only and value.get('sifPostopekFazaNaziv') == 'Rezultat':
                # Award notices never carry a submission deadline; skip them without fetching.
                skipped += 1
                progress()
                continue
            else:
                value = str(value['idObrazec'])
                tender = Tender.objects.filter(data__source_metadata__notice_id=value).first()
                if tender is None:
                    result = collect_notice(value, download=False,
                                            accept=deadline_ahead if run.open_only else None)
                    time.sleep(0.5)
                    if result.get('mode') == 'skipped':
                        skipped += 1
                        progress()
                        continue
                    if result.get('mode') != 'live':
                        errors += 1
                        log.append({'notice_id': value, 'message': 'Metapodatkov objave ni bilo mogoče pridobiti.'})
                        progress()
                        continue
                    tender = result['tender']
            if run.open_only and not deadline_ahead(tender.data):
                skipped += 1
                progress()
                continue
            # Buyers keep answering questions until the deadline; a changed answer set re-indexes the tender.
            from .pjn_faq import supported, try_sync
            if supported(tender) and (deadline_ahead(tender.data) or 'faq_synced_at' not in tender.data.get('source_metadata', {})):
                if try_sync(tender).get('changed'):
                    tender.refresh_from_db()
                time.sleep(0.3)
            from .pjn_contracts import sync_contracts
            sync_contracts(tender)
            from .models import PipelineJob
            reused = PipelineJob.objects.filter(key=index_identity(tender)).exists()
            job = enqueue_index(tender, retry=True)
            PipelineRunItem.objects.get_or_create(run=run, job=job, defaults={'reused': reused})
            progress()
        if run.mode == 'monthly':
            # Award notices of this month are recorded while collecting; this fills the days since the
            # newest stored award (month boundaries, notices collected before awards were recorded).
            try:
                awards = sync_awards(progress=progress)
                if awards['errors']:
                    log.append({'notice_id': 'oddaje', 'message': f"Obvestil o oddaji, ki jih ni bilo mogoče prenesti: {len(awards['errors'])}."})
            except ValueError as exc:
                log.append({'notice_id': 'oddaje', 'message': f'Zajem obvestil o oddaji ni uspel: {str(exc)[:200]}'})
        owned().update(state='partial' if errors else 'collected', finished_at=timezone.now(),
                       lease=None, lease_until=None, listed_count=listed, skipped_count=skipped, error_count=errors,
                       error_log=log[-20:], error='')
    except Exception as exc:
        owned().update(state='failed', finished_at=timezone.now(), lease=None, lease_until=None,
            listed_count=listed, skipped_count=skipped, error_count=errors, error_log=log[-20:],
            error=f'Zajem se ni zaključil ({type(exc).__name__}).')
    finally:
        # Runs whose jobs were all indexed earlier never see a job finish.
        close_processed_runs(PipelineRun.objects.filter(pk=run.pk))
        if agent:
            beat_agent(agent)
    run.refresh_from_db()
    return run
