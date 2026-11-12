"""Serve attachment evidence for the current profile and tender documents."""
import hashlib
import json
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .deep_extract import process_document
from .deep_relevance import analyse, document_fingerprint, historical_participants
from .documents import active_documents
from .models import AttachmentOpportunityCache, MonthlyScanItem, Tender
from .monthly_pipeline import profile_fingerprint
from .past_awards import ensure_past_awards
from .relevance import settings as gemini_settings
from .seed import ensure_seed, get_profile


@api_view(['GET', 'POST'])
def attachment_opportunities_view(request, tender_id):
    ensure_seed()
    tender = get_object_or_404(Tender, pk=tender_id)
    profile = get_profile()
    if settings.PIPELINE_REMOTE:
        return remote_opportunities(request, tender, profile)
    key, model = gemini_settings()
    active = active_documents(tender)
    documents = [doc for doc in active if doc.extraction.get('mode') != 'archive']
    failed_archives = sum(doc.status != 'processed' for doc in active if doc.extraction.get('mode') == 'archive')
    if request.method == 'POST':
        for doc in documents:
            process_document(doc)
    readable = [doc for doc in documents if doc.status == 'processed' and doc.pages]
    document_key = document_fingerprint(readable)
    profile_key = profile_fingerprint(profile, '', model, bool(key))
    version = tender.data.get('version', 1)
    fingerprint = hashlib.sha256(json.dumps([profile_key, version, document_key, tender.data.get('title')]).encode()).hexdigest()
    result = None
    if readable:
        cache = AttachmentOpportunityCache.objects.filter(tender=tender, fingerprint=fingerprint).first()
        if cache:
            result = cache.result
        else:
            notice_id = tender.data.get('source_metadata', {}).get('notice_id')
            archive = MonthlyScanItem.objects.filter(tender=tender, notice_id=notice_id, fingerprint=profile_key,
                result__version=version, result__documents_fingerprint=document_key).first() if notice_id else None
            if archive:
                result = archive.result
        if request.method == 'POST' and (result is None or result.get('warning')
                                        or (cache is None and key and result.get('ai_pending'))):
            result = analyse(tender, readable, profile, ai_budget=40, include_participants=False)
            AttachmentOpportunityCache.objects.update_or_create(tender=tender, defaults={
                'fingerprint': fingerprint, 'result': result})

    findings = []
    if result:
        if any(item['mode'] == 'gemini' for item in result['findings']):
            ensure_past_awards()
        for item in sorted(result['findings'], key=lambda item: item.get('confidence') or 0, reverse=True):
            findings.append({**item, 'historical_participants': historical_participants(tender, item['quote'])
                             if item['mode'] == 'gemini' else []})
    return Response({
        'analysed': result is not None,
        'document_count': len(documents),
        'unreadable_count': len(documents) - len(readable) + failed_archives,
        'findings': findings,
        'warning': result.get('warning') if result else None,
        'candidate_overflow': result.get('candidate_overflow', 0) if result else 0,
        'ai_pending': result.get('ai_pending', 0) if result else 0,
    })


def remote_opportunities(request, tender, profile):
    from .document_index import index_key
    from .models import PipelineJob
    from .pipeline_jobs import assessment_key, enqueue_assessment
    job = (enqueue_assessment(tender, profile) if request.method == 'POST' else
           PipelineJob.objects.filter(key=assessment_key(tender, profile)).first())
    result = job.result if job and job.state == 'complete' else {}
    active = [doc for doc in active_documents(tender, metadata_only=True) if doc.extraction.get('mode') != 'archive']
    if result and result.get('index_key') != index_key(active):
        result = {}
    findings = []
    for item in result.get('findings', []):
        findings.append({**item, 'historical_participants': historical_participants(tender, item['quote'])
            if item['mode'] == 'gemini' else []})
    pending = bool(job and job.state in ('pending', 'running'))
    index_job = PipelineJob.objects.filter(pk=job.payload.get('index_job')).first() if job else None
    if index_job and index_job.state in ('failed', 'superseded'):
        pending = False
    can_request = bool(active or tender.data.get('source_metadata', {}).get('attachment_url'))
    return Response({'analysed': bool(result),
        'pending': pending, 'job_state': job.state if job else None,
        'can_request': can_request,
        'document_count': result.get('document_count', len(active)),
        'unreadable_count': result.get('unreadable_count', 0), 'findings': findings,
        'warning': (job.error if job and job.error and not pending else None) or result.get('warning') or
            (index_job.error if index_job and index_job.state == 'failed' else None),
        'candidate_overflow': result.get('candidate_overflow', 0),
        'ai_pending': result.get('ai_pending', 0)}, status=202 if pending and request.method == 'POST' else 200)
