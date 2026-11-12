import hashlib
from pathlib import Path
import uuid
from django.conf import settings
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from .models import CompanyProfile, Tender, SavedSearch, Notification, Document
from .seed import ensure_seed, get_profile, demo_profile
from .matching import serialize_tender
from .filtering import apply_filters, validate_filters
from .validation import validate_profile
from .services import bootstrap, all_tenders, all_notifications, serialize_search, trigger_event
from .documents import extract_pages, serialize_document, active_documents
from .ai import chat, suggest_filters, analyze_document


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
            record = CompanyProfile.objects.select_for_update().get(pk=1)
            record.data = validate_profile(request.data, record.data)
            record.save()
    return Response(get_profile())


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
    if provider != 'demo':
        raise ValidationError('Izberite vir ajpes ali demo.')
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
    results = apply_filters(all_tenders(), filters)
    return Response({'results': results, 'count': len(results)})


@api_view(['GET'])
def tender_view(request, tender_id):
    ensure_seed()
    return Response(serialize_tender(get_object_or_404(Tender, pk=tender_id), get_profile()))


@api_view(['POST'])
def follow_view(request, tender_id):
    ensure_seed()
    tender = get_object_or_404(Tender, pk=tender_id)
    following = request.data.get('following')
    if not isinstance(following, bool):
        raise ValidationError({'following': 'Pričakovana je logična vrednost.'})
    tender.following = following
    tender.save(update_fields=['following'])
    return Response(serialize_tender(tender, get_profile()))


@api_view(['GET', 'POST'])
def searches_view(request):
    ensure_seed()
    if request.method == 'POST':
        name = request.data.get('name', '')
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValidationError({'name': 'Vnesite ime iskanja do 100 znakov.'})
        filters = validate_filters(request.data.get('filters', {}))
        item = SavedSearch.objects.create(name=name.strip(), filters=filters)
        return Response(serialize_search(item), status=201)
    return Response([serialize_search(s) for s in SavedSearch.objects.all()])


@api_view(['DELETE'])
def search_view(request, search_id):
    get_object_or_404(SavedSearch, pk=search_id).delete()
    return Response(status=204)


@api_view(['POST'])
def filter_suggestion_view(request):
    return Response(suggest_filters(message_input(request.data)))


@api_view(['POST'])
def chat_view(request):
    ensure_seed()
    message = message_input(request.data)
    ids = request.data.get('tender_ids', [])
    if not isinstance(ids, list) or len(ids) > 10 or not all(isinstance(i, str) for i in ids):
        raise ValidationError({'tender_ids': 'Neveljaven seznam razpisov.'})
    history = request.data.get('history', [])
    if not isinstance(history, list) or len(history) > 40:
        raise ValidationError({'history': 'Neveljavna zgodovina pogovora.'})
    clean_history = []
    for item in history[-6:]:
        if not isinstance(item, dict) or item.get('role') not in ['user', 'assistant'] or not isinstance(item.get('content'), str):
            raise ValidationError({'history': 'Neveljavno sporočilo zgodovine.'})
        clean_history.append({'role': item['role'], 'content': item['content'][:8000]})
    return Response(chat(message, all_tenders(), get_profile(), ids, clean_history))


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
    queryset.update(read=True)
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
    return {'name': name.strip(), 'source_type': source,
            'actions': clean_actions(data.get('actions', current.actions if current else None))}


@api_view(['GET', 'POST'])
def improvement_plans_view(request):
    from .models import ImprovementPlan
    from .improvements import company_key, serialize_plan, snapshot
    ensure_seed()
    if request.method == 'POST':
        plan = ImprovementPlan.objects.create(company_key=company_key(), **plan_values(request.data))
        return Response(serialize_plan(plan), status=201)
    context = snapshot()
    return Response([serialize_plan(p, context) for p in ImprovementPlan.objects.filter(company_key=company_key(context[0])).order_by('-updated_at')])


@api_view(['GET', 'PUT', 'DELETE'])
def improvement_plan_view(request, plan_id):
    from .models import ImprovementPlan
    from .improvements import company_key, serialize_plan
    ensure_seed()
    plan = get_object_or_404(ImprovementPlan, pk=plan_id, company_key=company_key())
    if request.method == 'DELETE':
        plan.delete()
        return Response(status=204)
    if request.method == 'PUT':
        for key, value in plan_values(request.data, plan).items():
            setattr(plan, key, value)
        plan.save()
    return Response(serialize_plan(plan))


@api_view(['POST'])
def event_view(request):
    ensure_seed()
    try:
        return Response(trigger_event(request.data.get('type')))
    except ValueError as exc:
        raise ValidationError(str(exc))


@api_view(['POST'])
def reset_view(request):
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
    tender = get_object_or_404(Tender, pk=tender_id)
    outcomes = [analyze_document(doc) for doc in active_documents(tender)]
    result = serialize_tender(tender, get_profile())
    result['analysis'] = outcomes or [{'mode': 'demo', 'message': 'Za analizo najprej dodajte besedilni PDF.'}]
    return Response(result)


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def document_upload_view(request, tender_id):
    ensure_seed()
    tender = get_object_or_404(Tender, pk=tender_id)
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
    return Response({**serialize_document(doc), 'analysis': outcome}, status=201)


@api_view(['GET'])
def document_view(request, document_id):
    ensure_seed()
    doc = get_object_or_404(Document, pk=document_id)
    path = Path(doc.path)
    roots = [settings.DEMO_DOCUMENTS_ROOT.resolve(), settings.MEDIA_ROOT.resolve()]
    if not any(path.resolve().is_relative_to(root) for root in roots) or not path.is_file():
        return Response({'error': 'Dokument ni na voljo.'}, status=404)
    content_type = 'application/pdf' if path.suffix == '.pdf' else 'application/octet-stream'
    filename = doc.title + ('.pdf' if content_type == 'application/pdf' and not doc.title.lower().endswith('.pdf') else '')
    response = FileResponse(path.open('rb'), content_type=content_type, as_attachment=content_type != 'application/pdf', filename=filename)
    response['X-Content-Type-Options'] = 'nosniff'
    # CSP sandbox disables Chrome's PDF viewer. Keep resource restrictions while
    # allowing the browser's built-in isolated viewer to display PDF evidence.
    response['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'self'"
    return response


@api_view(['GET'])
def similar_awards_view(request, tender_id):
    from .past_awards import similar_awards
    ensure_seed()
    return Response(similar_awards(get_object_or_404(Tender, pk=tender_id)))
