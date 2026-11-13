from .runtime_data import application_tenders
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .espd import build_espd, clean_answers, initial_answers
from .improvements import company_key
from .models import EspdDraft, Tender
from .seed import ensure_seed, get_profile


@api_view(['GET', 'PUT', 'DELETE'])
def tender_espd_view(request, tender_id):
    """One ESPD draft per company and tender. GET never writes; PUT saves validated answers."""
    ensure_seed()
    tender = get_object_or_404(application_tenders(), pk=tender_id)
    profile = get_profile()
    key = company_key(profile)
    draft = EspdDraft.objects.filter(company_key=key, tender=tender).first()
    if request.method == 'DELETE':
        if draft:
            draft.delete()
        return Response(status=204)
    if request.method == 'PUT':
        answers = clean_answers(request.data, tender)
        draft, _ = EspdDraft.objects.update_or_create(company_key=key, tender=tender, defaults={'answers': answers})
        return Response(build_espd(tender, profile, draft.answers, draft.updated_at))
    if draft:
        # A corrected notice may remove lots; keep the rest of the saved answers.
        stored = dict(draft.answers)
        lot_ids = {lot.get('id') for lot in tender.data.get('lots', [])}
        participation = dict(stored.get('participation') or {})
        participation['lots'] = [lot for lot in participation.get('lots') or [] if lot in lot_ids]
        stored['participation'] = participation
        return Response(build_espd(tender, profile, clean_answers(stored, tender), draft.updated_at))
    latest = EspdDraft.objects.filter(company_key=key).order_by('-updated_at').first()
    return Response(build_espd(tender, profile, initial_answers(tender, latest.answers if latest else None)))
