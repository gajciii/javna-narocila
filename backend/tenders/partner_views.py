from .runtime_data import application_tenders, application_records
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from .models import Partner, Tender
from .seed import ensure_seed
from .improvements import company_key
from .partners import (ensure_demo_partners, partner_values, serialize_partner,
                       partner_recommendations, certification_catalog)


@api_view(['GET', 'POST'])
def partners_view(request):
    ensure_seed()
    ensure_demo_partners()
    if request.method == 'POST':
        partner = Partner.objects.create(company_key=company_key(), **partner_values(request.data))
        return Response(serialize_partner(partner), status=201)
    return Response([serialize_partner(p) for p in application_records(Partner.objects.filter(company_key=company_key())).order_by('-updated_at', 'id')])


@api_view(['GET', 'PUT', 'DELETE'])
def partner_view(request, partner_id):
    ensure_seed()
    partner = get_object_or_404(application_records(Partner.objects.all()), pk=partner_id, company_key=company_key())
    if request.method == 'DELETE':
        partner.delete()
        return Response(status=204)
    if request.method == 'PUT':
        for key, value in partner_values(request.data, partner).items():
            setattr(partner, key, value)
        partner.save()
    return Response(serialize_partner(partner))


@api_view(['GET'])
def tender_partners_view(request, tender_id):
    ensure_seed()
    tender = get_object_or_404(application_tenders(), pk=tender_id)
    partner_id = request.query_params.get('partner_id')
    if partner_id is not None:
        if not partner_id.isdigit():
            raise ValidationError('Neveljaven identifikator partnerja.')
        partner_id = int(partner_id)
    return Response(partner_recommendations(tender, partner_id))


@api_view(['GET'])
def certifications_view(request):
    ensure_seed()
    return Response(certification_catalog())
