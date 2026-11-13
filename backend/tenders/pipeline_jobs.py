"""Shared work queue. Indexing is global; assessments belong to profile snapshots."""
import hashlib
import json
import logging
import uuid
import zipfile
from xml.etree.ElementTree import ParseError
from pypdf.errors import PyPdfError
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import Q, Case, When, Value, IntegerField, Exists, OuterRef
from django.utils import timezone

from .document_index import EXTRACTOR_VERSION, index_document, index_key, search_passages
from .documents import active_documents
from .models import PipelineJob, PipelineAttempt, PipelineRun, PipelineRunItem
from .relevance import profile_input, settings as gemini_settings

log = logging.getLogger(__name__)

LEASE_SECONDS = 300


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def index_identity(tender):
    uploaded = list(tender.document_records.filter(version__lte=tender.data.get('version', 1),
        id__startswith='upload-').order_by('pk').values_list('pk', 'sha256'))
    meta = tender.data.get('source_metadata', {})
    parts = ['index-contracts-v1', tender.pk, tender.data.get('version', 1), meta.get('attachment_url'), EXTRACTOR_VERSION, uploaded, meta.get('contracts_digest')]
    if meta.get('faq_digest'):
        # New portal answers re-run indexing and condition extraction without a new notice version.
        parts.append(['faq', meta['faq_digest']])
    return digest(parts)


def enqueue_index(tender, retry=False):
    job, _ = PipelineJob.objects.get_or_create(key=index_identity(tender), defaults={
        'kind': 'index', 'tender': tender, 'version': tender.data.get('version', 1), 'available_at': timezone.now()})
    if retry and job.state == 'failed':
        PipelineJob.objects.filter(pk=job.pk, state='failed').update(state='pending', attempts=0,
            available_at=timezone.now(), error='')
        job.refresh_from_db()
    return job


def assessment_key(tender, profile):
    key, model = gemini_settings()
    return digest(['assess-v1', index_identity(tender), profile_input(profile), model, bool(key)])


def enqueue_assessment(tender, profile):
    index = enqueue_index(tender, retry=True)
    # Interactive requests should not wait behind a full month's background downloads.
    if index.state in ('pending', 'running'):
        PipelineJob.objects.filter(pk=index.pk).update(payload={**index.payload, 'interactive': True})
    job, _ = PipelineJob.objects.get_or_create(key=assessment_key(tender, profile), defaults={
        'kind': 'assess', 'tender': tender, 'version': tender.data.get('version', 1),
        'payload': {'index_job': index.pk, 'profile': {k: profile.get(k, '') for k in
            ('activity', 'description', 'expertise', 'keywords', 'technologies')}}, 'available_at': timezone.now()})
    stale = job.state == 'complete' and job.result.get('index_key') != index_key(
        [d for d in active_documents(tender, metadata_only=True) if d.extraction.get('mode') != 'archive'])
    if job.state == 'failed' or stale:
        PipelineJob.objects.filter(pk=job.pk, state=job.state).update(state='pending', attempts=0,
            available_at=timezone.now(), error='')
        job.refresh_from_db()
    return job


def claim(worker=''):
    now = timezone.now()
    with transaction.atomic():
        jobs = PipelineJob.objects.filter(Q(state='pending', available_at__lte=now) |
            Q(state='running', lease_until__lt=now)).annotate(priority=Case(
                When(kind='assess', then=Value(0)), When(payload__interactive=True, then=Value(1)),
                default=Value(2), output_field=IntegerField())).order_by('priority', 'created_at')
        if connection.features.has_select_for_update_skip_locked:
            jobs = jobs.select_for_update(skip_locked=True)
        dependencies = dict(PipelineJob.objects.filter(kind='index').values_list('pk', 'state'))
        for job in jobs.iterator(chunk_size=100):
            if job.kind == 'assess':
                dependency = dependencies.get(job.payload['index_job'])
                if dependency is None or dependency in ('failed', 'superseded'):
                    job.state, job.error = 'failed', 'Indeksiranje dokumentacije ni uspelo.'
                    job.save(update_fields=['state', 'error'])
                    continue
                if dependency != 'complete':
                    continue
            job.state, job.lease = 'running', uuid.uuid4()
            job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
            job.attempts += 1
            job.save(update_fields=['state', 'lease', 'lease_until', 'attempts', 'updated_at'])
            PipelineAttempt.objects.filter(job=job, state='running').update(state='interrupted',
                finished_at=now, error='Najem je potekel; opravilo je prevzel drug delavec.')
            PipelineAttempt.objects.create(job=job, lease=job.lease, number=job.attempts, worker=worker)
            return job
    return None


def renew(job):
    return PipelineJob.objects.filter(pk=job.pk, lease=job.lease, state='running').update(
        lease_until=timezone.now() + timedelta(seconds=LEASE_SECONDS))


def close_processed_runs(runs):
    """Record when processing ended; later retries of the same jobs must not stretch it."""
    waiting = PipelineRunItem.objects.filter(run=OuterRef('pk'), job__state__in=('pending', 'running'))
    PipelineRun.objects.filter(pk__in=runs.values('pk'), processed_at__isnull=True).exclude(
        state__in=('queued', 'collecting')).exclude(Exists(waiting)).update(processed_at=timezone.now())


def finish(job, result, state='complete', error=''):
    now = timezone.now()
    with transaction.atomic():
        updated = PipelineJob.objects.filter(pk=job.pk, lease=job.lease, state='running').update(
            state=state, result=result, error=error, lease_until=None, lease=None, updated_at=now,
            available_at=now + timedelta(seconds=min(900, 30 * 2**job.attempts)))
        if updated:
            summary = {key: result[key] for key in ('document_count', 'unreadable_count', 'candidate_count', 'ai_questions') if key in result}
            summary['findings_count'] = len(result.get('findings', []))
            PipelineAttempt.objects.filter(job=job, lease=job.lease, state='running').update(
                state='retrying' if state == 'pending' else state, finished_at=now, error=error, summary=summary)
            if state != 'pending':
                close_processed_runs(PipelineRun.objects.filter(items__job=job))
    if updated:
        from .analytics import capture
        started = PipelineAttempt.objects.filter(job=job, lease=job.lease).values_list('started_at', flat=True).first()
        capture('pipeline_job_finished', kind=job.kind, state=state, attempt=job.attempts,
                duration_s=round((now - started).total_seconds(), 1) if started else None,
                documents=result.get('document_count'), unreadable=result.get('unreadable_count'),
                conditions=result.get('condition_count'), error=error[:200])
    return updated


def execute(job):
    from .deep_relevance import analyse
    from .pipeline_download import download
    tender = job.tender
    tender.refresh_from_db()
    if tender.data.get('version', 1) != job.version or index_identity(tender) != (
            job.key if job.kind == 'index' else PipelineJob.objects.get(pk=job.payload['index_job']).key):
        finish(job, {}, 'superseded')
        return
    try:
        if job.kind == 'index':
            download(tender)
            if not tender.data.get('source_metadata', {}).get('faq_synced_at'):
                from .pjn_faq import try_sync
                try_sync(tender)
                tender.refresh_from_db()
            documents = active_documents(tender, metadata_only=True)
            errors = []
            for document in documents:
                if document.extraction.get('mode') == 'archive':
                    continue
                try:
                    index_document(document)
                except (ValueError, OSError, zipfile.BadZipFile, ParseError, PyPdfError) as exc:
                    document.status = 'unprocessed'
                    document.error = f'Priloge ni mogoče indeksirati ({type(exc).__name__}); potreben je ročni pregled.'
                    document.save(update_fields=['status', 'error'])
                    errors.append(document.pk)
                renew(job)
            result = {'document_count': len(documents), 'unreadable_count': len(errors)}
            # Condition extraction is best effort; an AI outage must not fail or retry indexing.
            from .tender_conditions import extract_conditions
            try:
                result['condition_count'] = len(extract_conditions(tender).conditions)
            except Exception as exc:
                log.warning('Condition extraction failed: %s', type(exc).__name__)
        else:
            documents = [doc for doc in active_documents(tender, metadata_only=True)
                         if doc.extraction.get('mode') != 'archive']
            passages = search_passages(documents, job.payload['profile'])
            result = analyse(tender, documents, job.payload['profile'], ai_budget=40,
                include_participants=False, indexed_passages=passages)
            result.update(document_count=len(documents), unreadable_count=sum(not d.indexed_content_id for d in documents),
                          index_key=index_key(documents))
        tender.refresh_from_db()
        if tender.data.get('version', 1) != job.version:
            finish(job, {}, 'superseded')
        else:
            finish(job, result)
    except Exception as exc:
        # Exception messages from storage/database clients can contain credentials or private endpoints.
        finish(job, {}, 'pending' if job.attempts < 3 else 'failed',
               error=f'Obdelava ni uspela ({type(exc).__name__}).')
