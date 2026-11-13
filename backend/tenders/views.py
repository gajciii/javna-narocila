import hashlib
from pathlib import Path
import time
import uuid
from django.conf import settings
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from .accounts import account_id, companies, searches, lock_account
from .analytics import capture
from .models import CompanyProfile, Tender, SavedSearch, Notification, Document
from .seed import ensure_seed, get_profile, demo_profile, get_active_company, empty_profile
from .runtime_data import application_tenders, application_records, test_fixtures_enabled
from .matching import serialize_tender
from .filtering import apply_filters, keyword_matches, search_terms, validate_filters
from .validation import validate_profile
from .services import bootstrap, scored_tenders, all_notifications, schedule_suggestions, serialize_search, trigger_event
from .documents import extract_pages, serialize_document, active_documents
from .ai import suggest_filters, analyze_document


def message_input(data):
    message = data.get('message', '')
    if not isinstance(message, str) or not message.strip() or len(message) > 8000:
        raise ValidationError({'message': 'Vnesite sporočilo do 8.000 znakov.'})
    return message.strip()


@api_view(['GET'])
def bootstrap_view(request):
    ensure_seed()
    return Response(bootstrap())


@api_view(['GET', 'PUT'])
def profile_view(request):
    ensure_seed()
    if request.method == 'PUT':
        with transaction.atomic():
            lock_account()
            record = get_active_company()
            if request.data.get('id', record.pk) != record.pk:
                return Response({'message': 'Izbrano podjetje se je spremenilo. Osvežite stran.'}, status=409)
            record.data = validate_profile(request.data, record.data)
            validate_unique_company(record.data, exclude=record.pk)
            record.save()
        schedule_suggestions(force=True)
    return Response(get_profile())


@api_view(['GET'])
def annual_report_view(request, profile_id):
    from .annual_reports import latest_report
    profile = get_object_or_404(companies(), pk=profile_id)
    return Response(latest_report(profile.data.get('registration_number')))


@api_view(['GET'])
def erar_payments_view(request, profile_id):
    from .erar import recipient_payments
    profile = get_object_or_404(companies(), pk=profile_id)
    return Response(recipient_payments(profile.data.get('registration_number')))


def validate_unique_company(data, exclude=None):
    from .improvements import company_key
    key = company_key(data)
    if any(company_key(item.data) == key for item in companies().exclude(pk=exclude)):
        raise ValidationError('To podjetje je že shranjeno. Izberite ga med shranjenimi podjetji.')


@api_view(['POST'])
def profiles_view(request):
    ensure_seed()
    with transaction.atomic():
        lock_account()
        # Start with empty fields; a new company must never inherit demo capabilities.
        empty = empty_profile()
        data = validate_profile(request.data, empty)
        validate_unique_company(data)
        companies().filter(is_active=True).update(is_active=False)
        CompanyProfile.objects.create(owner_id=account_id(), data=data, is_active=True)
    schedule_suggestions(force=True)
    return Response(get_profile(), status=201)


@api_view(['POST'])
def activate_profile_view(request, profile_id):
    ensure_seed()
    with transaction.atomic():
        lock_account()
        record = get_object_or_404(companies(), pk=profile_id)
        companies().filter(is_active=True).update(is_active=False)
        record.is_active = True
        record.save(update_fields=['is_active'])
    schedule_suggestions(force=True)
    return Response(get_profile())


@api_view(['GET'])
def award_references_view(request):
    from .award_references import company_awards
    from .past_awards import ensure_past_awards
    ensure_seed()
    ensure_past_awards()
    return Response(company_awards(get_profile()))


@api_view(['POST'])
def prefill_view(request):
    query = request.data.get('query', '')
    if not isinstance(query, str) or len(query) > 300:
        raise ValidationError('Neveljavno iskanje podjetja.')
    provider = request.data.get('provider', 'ajpes')
    if provider == 'ajpes':
        from .ajpes import preview, RegistryUnavailable
        try:
            return Response(preview(request.data.get('registration_number', query)))
        except ValueError as exc:
            raise ValidationError(str(exc))
        except LookupError as exc:
            return Response({'message': str(exc)}, status=404)
        except RegistryUnavailable as exc:
            return Response({'code': 'ajpes_unavailable', 'message': str(exc)}, status=503)
    if provider != 'demo' or not test_fixtures_enabled():
        raise ValidationError('Izberite vir AJPES.')
    profile = demo_profile()
    return Response({'profile': profile, 'source': 'demo', 'message': 'Prikazan je izmišljeni demo profil Lumina digital. To niso podatki iz AJPES. Podatke preverite in shranite izrecno.'})


@api_view(['POST'])
def website_profile_view(request):
    from .website import analyze, WebsiteUnavailable
    try:
        return Response(analyze(request.data.get('url', '')))
    except ValueError as exc:
        raise ValidationError(str(exc))
    except WebsiteUnavailable as exc:
        return Response({'code': 'website_unavailable', 'message': str(exc)}, status=502)


@api_view(['GET'])
def company_search_view(request):
    from .ajpes import lookup, RegistryUnavailable
    try:
        return Response(lookup(request.query_params.get('q', '')))
    except ValueError as exc:
        raise ValidationError(str(exc))
    except RegistryUnavailable as exc:
        return Response({'code': 'ajpes_unavailable', 'message': str(exc)}, status=503)


@api_view(['GET'])
def tenders_view(request):
    ensure_seed()
    filters = {key: ','.join(request.query_params.getlist(key)) for key in request.query_params}
    hits = {}
    # Uncached AI relevance is scored in the background; the client refetches while pending.
    tenders, pending = scored_tenders(wait=False)
    results = apply_filters(tenders, filters, keyword_hits=hits)
    if filters.get('q', '').strip():
        results = [{**tender, 'keyword_matches': keyword_matches(tender, filters['q'], hits.get(tender['id'], {}))}
                   for tender in results]
    return Response({'results': results, 'count': len(results), 'counts': tab_counts(tenders, filters),
                     'facets': {'regions': unique_values(tenders, 'region'), 'buyers': unique_values(tenders, 'buyer')},
                     'relevance_pending': pending})


def tab_counts(tenders, filters):
    """Tab badges over all tenders, independent of the other list filters."""
    visible = [t for t in tenders if not t.get('ignored')]
    partner = {'include_partner_opportunities': filters['include_partner_opportunities']} if 'include_partner_opportunities' in filters else {}
    return {'recommended': len(apply_filters(tenders, {'view': 'recommended', **partner})), 'all': len(visible),
            'following': sum(1 for t in visible if t.get('following')), 'ignored': len(tenders) - len(visible)}


def unique_values(tenders, key):
    return list(dict.fromkeys(t[key] for t in tenders if t.get(key)))


@api_view(['POST'])
def keyword_expansion_view(request):
    from .keyword_expansion import expand
    query = request.data.get('q', '')
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 1000:
        raise ValidationError({'q': 'Vnesite ključne besede od 2 do 1.000 znakov.'})
    started = time.monotonic()
    result = expand(query.strip())
    capture('keyword_expansion', mode=result['mode'], suggestions=len(result['suggestions']),
            from_awards=sum(1 for s in result['suggestions'] if not s['evidence'].get('document_id')),
            duration_ms=round((time.monotonic() - started) * 1000))
    return Response(result)


def tender_detail(tender, profile):
    from .tender_conditions import conditions_payload
    conditions = conditions_payload(tender, profile)
    unmet = next((item['title'] for item in conditions['items'] if conditions['mode'] == 'live'
                  and (item.get('profile_answer') or {}).get('answer') == 'unmet'), None)
    return {**serialize_tender(tender, profile, unmet_condition=unmet), 'tender_conditions': conditions}


def store_condition_answers(company, answers):
    # Saved without touching updated_at: the client keys AI work (attachment opportunities, partner
    # matches) on it, and condition answers do not affect those results.
    company.data = {**company.data, 'condition_answers': answers}
    CompanyProfile.objects.filter(pk=company.pk).update(data=company.data)


@api_view(['POST'])
def condition_answer_view(request, tender_id, condition_id):
    """Record in the company profile whether the company meets a tender condition.

    The answer also applies to similar conditions in other tenders; ``answer: null`` removes it.
    """
    from .models import TenderConditions
    from .tender_conditions import save_answer, ANSWERS, profile_answers
    ensure_seed()
    tender = get_object_or_404(application_tenders(), pk=tender_id)
    answer = request.data.get('answer') if isinstance(request.data, dict) else 'invalid'
    if answer is not None and answer not in ANSWERS:
        raise ValidationError({'answer': 'Izberite, ali pogoj izpolnjujete ali ne.'})
    record = get_object_or_404(TenderConditions, tender=tender)
    item = next((c for c in record.conditions if c.get('id') == condition_id), None)
    if item is None:
        return Response({'message': 'Pogoja ni več v seznamu. Osvežite stran.'}, status=404)
    with transaction.atomic():
        lock_account()
        company = get_active_company()
        if request.data.get('profile_id', company.pk) != company.pk:
            return Response({'message': 'Izbrano podjetje se je spremenilo. Osvežite stran.'}, status=409)
        answers = save_answer(profile_answers(company.data), tender, item, answer)
        store_condition_answers(company, answers)
    profile = get_profile()
    return Response({'tender': tender_detail(tender, profile), 'profile': profile})


@api_view(['DELETE'])
def condition_answer_delete_view(request, answer_id):
    from .tender_conditions import profile_answers
    ensure_seed()
    with transaction.atomic():
        lock_account()
        company = get_active_company()
        answers = profile_answers(company.data)
        remaining = [a for a in answers if not isinstance(a, dict) or a.get('id') != answer_id]
        if len(remaining) == len(answers):
            return Response({'message': 'Oznake ni več v profilu.'}, status=404)
        store_condition_answers(company, remaining)
    return Response(get_profile())


@api_view(['GET'])
def tender_view(request, tender_id):
    ensure_seed()
    data = tender_detail(get_object_or_404(application_tenders(), pk=tender_id), get_profile())
    # The search that led here, so the detail page can show which keywords the tender contains and where.
    query = request.query_params.get('q', '')
    if len(query) > 2000:
        raise ValidationError({'q': 'Besedilo je predolgo ali neveljavno.'})
    if query.strip():
        from .keyword_expansion import document_keyword_hits
        hits = document_keyword_hits(list(search_terms(query)), [data['id']]).get(data['id'], {})
        data['keyword_matches'] = keyword_matches(data, query, hits)
    return Response(data)


@api_view(['POST'])
def follow_view(request, tender_id):
    ensure_seed()
    tender = get_object_or_404(application_tenders(), pk=tender_id)
    following = request.data.get('following')
    if not isinstance(following, bool):
        raise ValidationError({'following': 'Pričakovana je logična vrednost.'})
    if account_id() is None:
        tender.following = following
        tender.save(update_fields=['following'])
    else:
        from .models import TenderFollow
        if following:
            TenderFollow.objects.get_or_create(owner_id=account_id(), tender=tender)
        else:
            TenderFollow.objects.filter(owner_id=account_id(), tender=tender).delete()
    if following:
        from .models import TenderIgnore
        TenderIgnore.objects.filter(owner_id=account_id(), tender=tender).delete()
    return Response(tender_detail(tender, get_profile()))


@api_view(['POST'])
def ignore_view(request, tender_id):
    ensure_seed()
    tender = get_object_or_404(application_tenders(), pk=tender_id)
    ignored = request.data.get('ignored')
    if not isinstance(ignored, bool):
        raise ValidationError({'ignored': 'Pričakovana je logična vrednost.'})
    from .models import TenderFollow, TenderIgnore
    if ignored:
        TenderIgnore.objects.get_or_create(owner_id=account_id(), tender=tender)
        # An ignored tender is no longer of interest, so stop following it too.
        if account_id() is None:
            if tender.following:
                tender.following = False
                tender.save(update_fields=['following'])
        else:
            TenderFollow.objects.filter(owner_id=account_id(), tender=tender).delete()
    else:
        TenderIgnore.objects.filter(owner_id=account_id(), tender=tender).delete()
    return Response(tender_detail(tender, get_profile()))


@api_view(['GET', 'POST'])
def searches_view(request):
    ensure_seed()
    if request.method == 'POST':
        name = request.data.get('name', '')
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValidationError({'name': 'Vnesite ime iskanja do 100 znakov.'})
        filters = validate_filters(request.data.get('filters', {}))
        item = SavedSearch.objects.create(owner_id=account_id(), name=name.strip(), filters=filters)
        return Response(serialize_search(item), status=201)
    return Response([serialize_search(s) for s in searches()])


@api_view(['DELETE'])
def search_view(request, search_id):
    get_object_or_404(searches(), pk=search_id).delete()
    return Response(status=204)


@api_view(['POST'])
def filter_suggestion_view(request):
    return Response(suggest_filters(message_input(request.data)))


@api_view(['GET'])
def notifications_view(request):
    ensure_seed()
    return Response(all_notifications())


@api_view(['POST'])
def notifications_read_view(request):
    from .improvements import visible_notifications
    queryset = visible_notifications()
    if request.data.get('id') is not None:
        item = get_object_or_404(queryset, pk=request.data['id'])
        queryset = queryset.filter(pk=item.pk)
    if account_id() is None:
        queryset.update(read=True)
    else:
        from .models import NotificationRead
        queryset.filter(type='improvement').update(read=True)
        queryset = queryset.exclude(type='improvement')
        NotificationRead.objects.bulk_create([NotificationRead(owner_id=account_id(), notification_id=pk)
                                             for pk in queryset.values_list('pk', flat=True)], ignore_conflicts=True)
    return Response(all_notifications())


@api_view(['POST'])
def improvement_evaluate_view(request):
    from .improvements import evaluate
    ensure_seed()
    if not isinstance(request.data, dict):
        raise ValidationError('Pričakovan je objekt.')
    return Response(evaluate(request.data.get('actions'), request.data.get('source_type')))


def plan_values(data, current=None):
    from .improvements import clean_actions
    if not isinstance(data, dict):
        raise ValidationError('Pričakovan je objekt.')
    name = data.get('name', current.name if current else '')
    source = data.get('source_type', current.source_type if current else '')
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValidationError('Načrt poimenujte z največ 100 znaki.')
    if source not in ('real', 'demo'):
        raise ValidationError('Demo in resnične razpise shranite v ločena načrta.')
    if source != 'real' and not test_fixtures_enabled():
        raise ValidationError('Načrt lahko temelji samo na resničnih razpisih.')
    return {'name': name.strip(), 'source_type': source,
            'actions': clean_actions(data.get('actions', current.actions if current else None))}


@api_view(['GET', 'POST'])
def improvement_plans_view(request):
    from .models import ImprovementPlan
    from .improvements import company_key, serialize_plan, snapshot
    ensure_seed()
    if request.method == 'POST':
        plan = ImprovementPlan.objects.create(company_key=company_key(), **plan_values(request.data))
        schedule_suggestions(force=True)
        return Response(serialize_plan(plan), status=201)
    context = snapshot()
    return Response([serialize_plan(p, context) for p in application_records(ImprovementPlan.objects.filter(company_key=company_key(context[0]))).order_by('-updated_at')])


@api_view(['GET', 'PUT', 'DELETE'])
def improvement_plan_view(request, plan_id):
    from .models import ImprovementPlan
    from .improvements import company_key, serialize_plan
    ensure_seed()
    plan = get_object_or_404(application_records(ImprovementPlan.objects.all()), pk=plan_id, company_key=company_key())
    if request.method == 'DELETE':
        plan.delete()
        schedule_suggestions(force=True)
        return Response(status=204)
    if request.method == 'PUT':
        for key, value in plan_values(request.data, plan).items():
            setattr(plan, key, value)
        plan.save()
        schedule_suggestions(force=True)
    return Response(serialize_plan(plan))


@api_view(['POST'])
def event_view(request):
    if not test_fixtures_enabled():
        return Response({'message': 'Demo način ni več na voljo.'}, status=410)
    ensure_seed()
    try:
        return Response(trigger_event(request.data.get('type')))
    except ValueError as exc:
        raise ValidationError(str(exc))


@api_view(['POST'])
def reset_view(request):
    if not test_fixtures_enabled():
        return Response({'message': 'Demo način ni več na voljo.'}, status=410)
    ensure_seed(reset=True)
    return Response(bootstrap())


@api_view(['POST'])
def import_view(request):
    ensure_seed()
    from .importer import import_notice
    try:
        result = import_notice(request.data.get('url_or_id', ''))
    except ValueError as exc:
        raise ValidationError(str(exc))
    if result.get('tender') is not None:
        result['tender'] = serialize_tender(result['tender'], get_profile())
    return Response(result)


@api_view(['POST'])
def sync_view(request):
    ensure_seed()
    from .pjn_sync import sync_recent
    try:
        return Response(sync_recent(request.data.get('limit', 20)))
    except ValueError as exc:
        raise ValidationError(str(exc))


@api_view(['POST'])
def analyze_view(request, tender_id):
    ensure_seed()
    tender = get_object_or_404(application_tenders(), pk=tender_id)
    from .tender_conditions import extract_conditions
    outcomes = [analyze_document(doc) for doc in active_documents(tender)]
    record = extract_conditions(tender, force=True)
    if record.mode == 'live':
        outcomes.append({'mode': 'live', 'message': f'Izluščenih pogojev razpisa: {len(record.conditions)}.'})
    elif record.message:
        outcomes.append({'mode': 'demo', 'message': record.message})
    schedule_suggestions(force=True)
    result = tender_detail(tender, get_profile())
    result['analysis'] = outcomes or [{'mode': 'demo', 'message': 'Za analizo najprej dodajte besedilni PDF.'}]
    return Response(result)


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def document_upload_view(request, tender_id):
    ensure_seed()
    tender = get_object_or_404(application_tenders(), pk=tender_id)
    uploaded = request.FILES.get('file')
    if not uploaded:
        raise ValidationError({'file': 'Izberite dokument.'})
    if uploaded.size > 10 * 1024 * 1024:
        raise ValidationError({'file': 'Največja dovoljena velikost je 10 MB.'})
    payload = uploaded.read()
    digest = hashlib.sha256(payload).hexdigest()
    previous = Document.objects.filter(tender=tender, sha256=digest).first()
    if previous:
        return Response(serialize_document(previous))
    supported = uploaded.name.lower().endswith('.pdf') and payload.startswith(b'%PDF-')
    doc_id = 'upload-' + uuid.uuid4().hex[:16]
    directory = settings.MEDIA_ROOT / 'documents'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (doc_id + ('.pdf' if supported else '.bin'))
    target.write_bytes(payload)
    if settings.PIPELINE_REMOTE:
        from .pipeline_storage import store
        from .pipeline_jobs import enqueue_index
        reference = store(target, digest)
        doc = Document.objects.create(id=doc_id, tender=tender, title=Path(uploaded.name).name[:300],
            path=reference, version=tender.data.get('version', 1), sha256=digest,
            extraction={'mode': 'unprocessed', 'requirements': [], 'criteria': []})
        enqueue_index(tender)
        return Response({**serialize_document(doc), 'analysis': {'mode': 'queued',
            'message': 'Dokument je v vrsti za indeksiranje na strežniku.'}}, status=201)
    pages, error = [], ''
    if supported:
        try:
            pages = extract_pages(target)
            if sum(len(p['text'].strip()) for p in pages) < 50:
                error = 'PDF nima dovolj berljivega besedila. Potreben je OCR, ki ni vključen v prototip.'
        except Exception:
            error = 'Besedila PDF ni bilo mogoče varno prebrati. Preverite dokument.'
    else:
        error = 'Ta vrsta priloge še ni podprta. Dodajte besedilni PDF.'
    doc = Document.objects.create(id=doc_id, tender=tender, title=Path(uploaded.name).name[:300], path=str(target),
        version=tender.data.get('version', 1), status='unprocessed' if error else 'processed', pages=pages, sha256=digest, error=error,
        extraction={'mode': 'unprocessed', 'requirements': [], 'criteria': [], 'summary': ''})
    outcome = analyze_document(doc) if not error else {'mode': 'demo', 'message': error}
    doc.refresh_from_db()
    schedule_suggestions(force=True)
    return Response({**serialize_document(doc), 'analysis': outcome}, status=201)


@api_view(['GET'])
def document_text_view(request, document_id):
    from .document_preview import preview
    return preview(get_object_or_404(Document.objects.select_related('indexed_content').filter(tender__in=application_tenders()), pk=document_id), request)


@api_view(['GET'])
def document_view(request, document_id):
    ensure_seed()
    doc = get_object_or_404(Document.objects.select_related('indexed_content').filter(tender__in=application_tenders()), pk=document_id)
    def missing_original():
        if request.query_params.get('download') == '1':
            return Response({'error': 'Izvirna datoteka ni na voljo v lokalni shrambi. Na voljo je lahko izluščeno besedilo.',
                             'text_url': f'/api/documents/{doc.pk}/text'}, status=404)
        from .document_preview import preview
        return preview(doc, request, original_missing=True)
    if doc.path.startswith('s3://'):
        from .pipeline_storage import stream
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            body = stream(doc.path)
        except (BotoCoreError, ClientError, ValueError):
            return missing_original()
        content_type = ('application/pdf' if doc.title.lower().endswith('.pdf') or doc.extraction.get('format') == 'pdf'
                        else 'text/plain; charset=utf-8' if doc.extraction.get('source') == 'pjn-faq' else 'application/octet-stream')
        filename = doc.title + ('.pdf' if content_type == 'application/pdf' and not doc.title.lower().endswith('.pdf') else '')
        response = FileResponse(body, filename=filename, content_type=content_type,
                                as_attachment=content_type == 'application/octet-stream')
        response['X-Content-Type-Options'] = 'nosniff'
        response['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'self'"
        return response
    path = Path(doc.path)
    roots = [settings.DEMO_DOCUMENTS_ROOT.resolve(), settings.MEDIA_ROOT.resolve()]
    if not any(path.resolve().is_relative_to(root) for root in roots) or not path.is_file():
        return missing_original()
    content_type = 'application/pdf' if path.suffix == '.pdf' else 'text/plain; charset=utf-8' if doc.extraction.get('source') == 'pjn-faq' else 'application/octet-stream'
    filename = doc.title + ('.pdf' if content_type == 'application/pdf' and not doc.title.lower().endswith('.pdf') else '')
    response = FileResponse(path.open('rb'), content_type=content_type, as_attachment=content_type == 'application/octet-stream', filename=filename)
    response['X-Content-Type-Options'] = 'nosniff'
    # CSP sandbox disables Chrome's PDF viewer. Keep resource restrictions while
    # allowing the browser's built-in isolated viewer to display PDF evidence.
    response['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'self'"
    return response


@api_view(['GET'])
def similar_awards_view(request, tender_id):
    from .past_awards import ensure_past_awards, similar_awards
    ensure_seed()
    ensure_past_awards()
    started = time.monotonic()
    result = similar_awards(get_object_or_404(application_tenders(), pk=tender_id))
    capture('similar_awards', mode=result['mode'], matching=result.get('matching'), results=len(result['results']),
            warning=bool(result.get('warning')), duration_ms=round((time.monotonic() - started) * 1000))
    return Response(result)


@api_view(['GET'])
def tender_faq_view(request, tender_id):
    from .pjn_faq import tender_faq
    return Response(tender_faq(get_object_or_404(application_tenders(), pk=tender_id)))


@api_view(['GET'])
def buyer_history_view(request, tender_id):
    from .buyer_history import history
    from .past_awards import ensure_past_awards
    ensure_past_awards()
    return Response(history(get_object_or_404(application_tenders(), pk=tender_id), request.query_params))


@api_view(['GET', 'POST'])
def incumbents_view(request, tender_id):
    """GET reads stored contracts; POST first refreshes the buyer's related contracts from PJN (bounded)."""
    from .contract_insights import incumbents
    tender = get_object_or_404(application_tenders(), pk=tender_id)
    refresh = None
    if request.method == 'POST':
        from .pjn_contracts import sync_tender_buyers
        results = sync_tender_buyers(tender, max_details=15)
        refresh = {'fetched': sum(r['fetched'] for r in results), 'remaining': sum(r['remaining'] for r in results),
                   'errors': sum(len(r['errors']) for r in results),
                   'skipped': bool(results) and all(r['mode'] in ('fresh', 'skipped') for r in results)}
    return Response({**incumbents(tender), 'refresh': refresh})


@api_view(['GET'])
def expected_tenders_view(request):
    from .contract_insights import expected_tenders
    return Response(expected_tenders(get_profile(), request.query_params))


@api_view(['POST'])
def notification_email_test_view(request):
    from django.core.cache import cache
    from .accounts import account_id
    from .email_notifications import send_test
    # One test per account per minute is enough to check settings and keeps the button from mailing in bulk.
    if not cache.add(f'email-test:{account_id()}', 1, 60):
        return Response({'sent': False, 'message': 'Testno sporočilo lahko pošljete enkrat na minuto.'}, status=429)
    return Response(send_test())


@api_view(['GET', 'PUT'])
def notification_email_settings_view(request):
    from .email_notifications import save_settings, status
    return Response(save_settings(request.data) if request.method == 'PUT' else status())
