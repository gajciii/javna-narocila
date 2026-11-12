"""Serve attachment evidence for the current profile and tender documents."""
import hashlib
import json
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
