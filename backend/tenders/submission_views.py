import logging

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, parser_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response

from .models import Tender
from .submission_review import read_uploads, review
from .submission_review import MAX_FILE

log = logging.getLogger(__name__)


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def submission_review_view(request, tender_id):
    tender = get_object_or_404(Tender, pk=tender_id)
    files = request.FILES.getlist('submission_files')
    if not files:
        raise ValidationError('Dodajte dokumente pripravljene prijave (PDF ali ZIP).')
    if sum(f.size for _, group in request.FILES.lists() for f in group) > MAX_FILE:
        raise ValidationError('Prijava in dodatni razpisni dokumenti lahko skupaj obsegajo največ 10 MB.')
    folder = request.data.get('submission_folder', '')
    if not isinstance(folder, str) or len(folder) > 300:
        raise ValidationError('Neveljavna mapa prijave.')
    submissions, submission_issues, duplicates = read_uploads(files, 'bid', folder=folder)
    additions, source_issues, _ = read_uploads(request.FILES.getlist('source_files'), 'source')
    try:
        return Response(review(tender, submissions, additions, source_issues, submission_issues, duplicates))
    except ValidationError:
        raise
    except Exception as exc:
        log.warning('Submission review unavailable: %s', type(exc).__name__)
        return Response({'error': 'AI pregleda ni bilo mogoče dokončati ali potrditi dokazov. Poskusite znova. Prijava ni označena kot ustrezna.'}, status=503)
