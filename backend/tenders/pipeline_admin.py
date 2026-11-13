"""Staff-only pipeline administration, using Django sessions and CSRF protection."""
import json
import logging
import uuid
from functools import wraps
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.db.models import Count, Exists, Max, Min, OuterRef, Q, Sum
from django.db.models.functions import TruncMonth
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from .models import (Document, PipelineAgent, PipelineAttempt, PipelineControl, PipelineJob, PipelineRun, PipelineRunItem,
                     IndexedContent, DocumentChunk, PastAward, Tender)
from .pipeline_runs import create_run
from . import storage_usage


@never_cache
@ensure_csrf_cookie
@require_http_methods(['GET'])
def session_view(request):
    staff = bool(request.user.is_authenticated and request.user.is_active and request.user.is_staff)
    return JsonResponse({'authenticated': staff, 'username': request.user.username if staff else '',
                         'csrf_token': get_token(request)})


@never_cache
@csrf_protect
@require_http_methods(['POST'])
def login_view(request):
    key = 'pipeline-login:' + request.META.get('REMOTE_ADDR', '')
    failures = cache.get(key, 0)
    if failures >= 10:
        return JsonResponse({'error': 'Preveč neuspešnih prijav. Poskusite čez 15 minut.'}, status=429)
    try:
        data = json.loads(request.body)
        username, password = data.get('username'), data.get('password')
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 150 or len(password) > 1024:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({'error': 'Vnesite uporabniško ime in geslo.'}, status=400)
    user = authenticate(request, username=username, password=password)
    if not user or not user.is_staff or not user.is_active:
        cache.set(key, failures + 1, 900)
        return JsonResponse({'error': 'Prijava ni uspela. Preverite administratorske prijavne podatke.'}, status=403)
    cache.delete(key)
    login(request, user)
    return JsonResponse({'authenticated': True, 'username': user.username, 'csrf_token': get_token(request)})


@never_cache
@csrf_protect
@require_http_methods(['POST'])
def logout_view(request):
    logout(request)
    return JsonResponse({'authenticated': False, 'username': '', 'csrf_token': get_token(request)})


def admin_endpoint(methods):
    def decorate(function):
        @wraps(function)
        def checked(request, *args, **kwargs):
            if request.method == 'POST' and not isinstance(request.data, dict):
                return Response({'error': 'Pričakovan je objekt z nastavitvami zahteve.'}, status=400)
            return function(request, *args, **kwargs)
        return never_cache(api_view(methods)(authentication_classes([SessionAuthentication])(
            permission_classes([IsAdminUser])(checked))))
    return decorate


def timestamp(value):
    return value.isoformat() if value else None


@admin_endpoint(['GET'])
def database_export_view(request):
    from .database_export import database_archive
    try:
        archive = database_archive()
    except Exception:
        logging.getLogger(__name__).exception('Application database export failed')
        return Response({'error': 'Izvoz baze ni uspel. Poskusite znova ali preverite dnevnik strežnika.'}, status=500)
    filename = 'razpizi-data-' + timezone.now().strftime('%Y%m%d-%H%M%S') + '.json.gz'
    response = FileResponse(archive, as_attachment=True, filename=filename, content_type='application/gzip')
    response['X-Content-Type-Options'] = 'nosniff'
    logging.getLogger(__name__).info('Application database exported by staff user %s', request.user.pk)
    return response


def run_rows(query):
    return query.select_related('requested_by').annotate(
        total_jobs=Count('items'), reused_jobs=Count('items', filter=Q(items__reused=True)),
        pending_jobs=Count('items', filter=Q(items__job__state='pending')),
        running_jobs=Count('items', filter=Q(items__job__state='running')),
        complete_jobs=Count('items', filter=Q(items__job__state='complete')),
        failed_jobs=Count('items', filter=Q(items__job__state='failed')),
        superseded_jobs=Count('items', filter=Q(items__job__state='superseded')))


def run_data_volume(run):
    """Bytes of the files behind the run's indexed tenders; archives count once, by their members."""
    indexed = PipelineRunItem.objects.filter(run=run, job__kind='index', job__state='complete',
        job__tender=OuterRef('tender'), job__version=OuterRef('version'))
    totals = Document.objects.filter(Exists(indexed)).exclude(extraction__mode='archive').aggregate(
        bytes=Sum('size_bytes'), files=Count('pk'), measured=Count('size_bytes'))
    return {'bytes': totals['bytes'] or 0, 'files': totals['files'], 'unmeasured_files': totals['files'] - totals['measured']}


def serialize_run(run):
    counts = {key: getattr(run, f'{key}_jobs') for key in
              ('total', 'reused', 'pending', 'running', 'complete', 'failed', 'superseded')}
    if run.state in ('queued', 'collecting', 'failed', 'imported'):
        status = run.state
    elif counts['pending'] or counts['running']:
        status = 'processing'
    elif run.error_count or counts['failed']:
        status = 'partial'
    else:
        status = 'complete'
    return {'id': run.pk, 'source': run.source, 'mode': run.mode, 'period': run.period,
        'max_notices': run.max_notices, 'open_only': run.open_only, 'skipped_count': run.skipped_count,
        'state': run.state, 'status': status,
        'requested_by': run.requested_by.username if run.requested_by else None,
        'listed_count': run.listed_count, 'error_count': run.error_count, 'error': run.error,
        'created_at': timestamp(run.created_at), 'started_at': timestamp(run.started_at),
        'collection_finished_at': timestamp(run.finished_at), 'processed_at': timestamp(run.processed_at),
        'duration_seconds': round((run.processed_at - run.started_at).total_seconds())
            if run.processed_at and run.started_at else None,
        'data': run_data_volume(run), 'jobs': counts}


def serialize_job(job):
    result = job.result or {}
    return {'id': job.pk, 'kind': job.kind, 'state': job.state, 'tender_id': job.tender_id,
        'title': job.tender.data.get('title') or job.tender_id, 'version': job.version,
        'attempts': job.attempts, 'error': job.error, 'created_at': timestamp(job.created_at),
        'updated_at': timestamp(job.updated_at), 'available_at': timestamp(job.available_at),
        'lease_until': timestamp(job.lease_until),
        'document_count': result.get('document_count'), 'unreadable_count': result.get('unreadable_count'),
        'findings_count': len(result.get('findings', []))}


def page_number(request):
    try:
        page = int(request.query_params.get('page', '1'))
        if not 1 <= page <= 100000:
            raise ValueError
        return page
    except (ValueError, TypeError):
        return None


@admin_endpoint(['GET'])
def overview_view(request):
    now = timezone.now()
    control = PipelineControl.objects.get(pk=1)
    agents = PipelineAgent.objects.filter(last_seen__gte=now - timedelta(days=7)).order_by('-last_seen')[:20]
    return Response({'remote_enabled': settings.PIPELINE_REMOTE, 'server_time': timestamp(now),
        'queue': {row['state']: row['count'] for row in PipelineJob.objects.values('state').annotate(count=Count('pk'))},
        'index': {'documents': IndexedContent.objects.count(), 'chunks': DocumentChunk.objects.count()},
        'past_awards': past_award_stats(),
        'semantic_index': semantic_index_stats(),
        'storage_usage': storage_usage_stats(),
        'schedule': {'enabled': control.schedule_enabled, 'next_run_at': timestamp(control.next_run_at)},
        'agents': [{'id': str(agent.pk), 'role': agent.role, 'hostname': agent.hostname,
            'online': agent.last_seen >= now - timedelta(seconds=90) and agent.state != 'stopped',
            'state': agent.state, 'last_seen': timestamp(agent.last_seen),
            'job_id': agent.job_id, 'run_id': agent.run_id} for agent in agents],
        'history_note': 'Prejšnja opravila so vključena. Posamezni poskusi se beležijo od uvedbe portala.'})


def storage_usage_stats():
    usage = storage_usage.current()
    return {**usage, 'measured_at': timestamp(usage['measured_at']), 'next_refresh_at': timestamp(usage['next_refresh_at'])}


def semantic_index_stats():
    """Vector coverage per source; the worker fills missing vectors whenever it is idle."""
    from django.db import connection
    from . import embeddings
    extension = False
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            extension = cursor.fetchone() is not None
    sources = (('tenders', 'Razpisi', Tender), ('chunks', 'Odlomki dokumentov', DocumentChunk), ('awards', 'Pretekle oddaje', PastAward))
    items = []
    for key, label, model in sources:
        totals = model.objects.aggregate(total=Count('pk'), embedded=Count('pk', filter=Q(embedding__isnull=False)))
        items.append({'key': key, 'label': label, **totals})
    return {'enabled': extension and embeddings.enabled(), 'extension': extension,
            'model': embeddings.MODEL, 'dimensions': embeddings.DIMENSIONS, 'items': items}


def past_award_stats():
    totals = PastAward.objects.aggregate(
        notices=Count('notice_id', distinct=True), lots=Count('pk'),
        awarded_lots=Count('pk', filter=Q(data__awarded=True)),
        first_published_on=Min('published_on'), last_published_on=Max('published_on'),
        last_imported_at=Max('imported_at'), undated_lots=Count('pk', filter=Q(published_on__isnull=True)))
    months = (PastAward.objects.filter(published_on__isnull=False).annotate(month=TruncMonth('published_on'))
        .values('month').annotate(notices=Count('notice_id', distinct=True), lots=Count('pk'),
                                 awarded_lots=Count('pk', filter=Q(data__awarded=True))).order_by('-month'))
    return {**totals, 'first_published_on': timestamp(totals['first_published_on']),
        'last_published_on': timestamp(totals['last_published_on']),
        'last_imported_at': timestamp(totals['last_imported_at']),
        'months': [{**row, 'month': row['month'].strftime('%Y-%m')} for row in months]}


@admin_endpoint(['GET', 'POST'])
def runs_view(request):
    if request.method == 'POST':
        if not settings.PIPELINE_REMOTE:
            return Response({'error': 'Ločeni pipeline ni omogočen.'}, status=409)
        data = request.data
        try:
            request_key = uuid.UUID(str(data.get('request_key')))
            if not isinstance(data.get('period', ''), str):
                raise ValueError('Neveljaven mesec.')
            run = create_run(source='manual', mode=data.get('mode', 'monthly'), period=data.get('period', ''),
                max_notices=data.get('max_notices'), requested_by=request.user, request_key=request_key,
                open_only=data.get('open_only', False))
        except (ValueError, TypeError, AttributeError) as exc:
            return Response({'error': str(exc) if str(exc) and 'UUID' not in str(exc) else 'Neveljavni podatki zagona.'}, status=400)
        return Response(serialize_run(run_rows(PipelineRun.objects.filter(pk=run.pk)).get()), status=202)
    page = page_number(request)
    if page is None:
        return Response({'error': 'Neveljavna stran.'}, status=400)
    query = PipelineRun.objects.all()
    source = request.query_params.get('source')
    if source:
        if source not in ('manual', 'scheduled', 'cli', 'imported'):
            return Response({'error': 'Neveljaven vir.'}, status=400)
        query = query.filter(source=source)
    return Response({'results': [serialize_run(run) for run in run_rows(query).order_by('-created_at')[(page-1)*20:page*20]],
                     'count': query.count(), 'page': page})


@admin_endpoint(['GET'])
def run_view(request, run_id):
    run = get_object_or_404(run_rows(PipelineRun.objects.filter(pk=run_id)))
    page = page_number(request)
    if page is None:
        return Response({'error': 'Neveljavna stran.'}, status=400)
    jobs = run.jobs.select_related('tender').order_by('-created_at')
    state = request.query_params.get('state')
    if state:
        if state not in ('pending', 'running', 'complete', 'failed', 'superseded'):
            return Response({'error': 'Neveljavno stanje.'}, status=400)
        jobs = jobs.filter(state=state)
    return Response({'run': serialize_run(run), 'errors': run.error_log,
        'jobs': [serialize_job(job) for job in jobs[(page-1)*25:page*25]], 'count': jobs.count(), 'page': page})


@admin_endpoint(['GET', 'POST'])
def job_view(request, job_id):
    job = get_object_or_404(PipelineJob.objects.select_related('tender'), pk=job_id)
    if request.method == 'POST':
        if not settings.PIPELINE_REMOTE:
            return Response({'error': 'Ločeni pipeline ni omogočen.'}, status=409)
        now = timezone.now()
        with transaction.atomic():
            if not PipelineJob.objects.filter(pk=job.pk, state='failed').update(
                    state='pending', attempts=0, available_at=now, error=''):
                return Response({'error': 'Ponoviti je mogoče samo neuspešno opravilo.'}, status=409)
            retry = PipelineRun.objects.create(source='manual', mode='retry', requested_by=request.user,
                max_notices=1, listed_count=1, state='collected', started_at=now, finished_at=now)
            PipelineRunItem.objects.create(run=retry, job=job)
        job.refresh_from_db()
    attempts = job.execution_history.order_by('-started_at')[:100]
    return Response({'job': serialize_job(job), 'attempts': [{'id': a.pk, 'number': a.number,
        'state': a.state, 'worker': a.worker, 'started_at': timestamp(a.started_at),
        'finished_at': timestamp(a.finished_at), 'error': a.error, 'summary': a.summary} for a in attempts],
        'attempt_count': job.execution_history.count()})


@admin_endpoint(['GET'])
def jobs_view(request):
    page = page_number(request)
    if page is None:
        return Response({'error': 'Neveljavna stran.'}, status=400)
    jobs = PipelineJob.objects.select_related('tender').order_by('-created_at')
    state, kind = request.query_params.get('state'), request.query_params.get('kind')
    if state:
        if state not in ('pending', 'running', 'complete', 'failed', 'superseded'):
            return Response({'error': 'Neveljavno stanje.'}, status=400)
        jobs = jobs.filter(state=state)
    if kind:
        if kind not in ('index', 'assess'):
            return Response({'error': 'Neveljavna vrsta opravila.'}, status=400)
        jobs = jobs.filter(kind=kind)
    return Response({'results': [serialize_job(job) for job in jobs[(page-1)*25:page*25]],
                     'count': jobs.count(), 'page': page})


@admin_endpoint(['POST'])
def schedule_view(request):
    enabled = request.data.get('enabled')
    if not isinstance(enabled, bool):
        return Response({'error': 'Izberite omogočeno ali ustavljeno.'}, status=400)
    PipelineControl.objects.filter(pk=1).update(schedule_enabled=enabled)
    return Response({'enabled': enabled})
