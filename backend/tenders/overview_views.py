from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .runtime_data import application_tenders
from .tender_overview import overview


@api_view(['GET'])
def overview_view(request, tender_id):
    return Response(overview(get_object_or_404(application_tenders(), pk=tender_id)))
