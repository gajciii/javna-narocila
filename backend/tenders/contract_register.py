"""Read-only browsing of stored signed contracts; never fetches the portal or invokes AI."""
import re
from datetime import timedelta

from django.db.models import DecimalField, F, Q, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, NullIf
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .contract_insights import PAGE_SIZE, dataset_info, serialize
from .models import Contract
from .seed import today


def register_options(params):
    query = (params.get('q') or '').strip()
    if len(query) > 200 or len(query.split()) > 8:
        raise ValidationError({'q': 'Vnesite največ 200 znakov oziroma 8 iskalnih besed.'})
    cpv = (params.get('cpv') or '').strip()
    if cpv and not re.fullmatch(r'\d{2,8}', cpv):
        raise ValidationError({'cpv': 'Vnesite od 2 do 8 začetnih števk CPV.'})
    year = params.get('year') or ''
    if year and (not re.fullmatch(r'\d{4}', year) or not 1900 <= int(year) <= today().year + 1):
        raise ValidationError({'year': 'Vnesite veljavno leto objave.'})
    state = params.get('status') or 'all'
    if state not in ('all', 'active', 'ended', 'unknown', 'expiring'):
        raise ValidationError({'status': 'Neveljaven izbor veljavnosti.'})
    sort = params.get('sort') or 'newest'
    if sort not in ('newest', 'ending', 'value'):
        raise ValidationError({'sort': 'Neveljavno razvrščanje.'})
    page = params.get('page') or '1'
    if not re.fullmatch(r'\d{1,4}', page) or int(page) < 1:
        raise ValidationError({'page': 'Neveljavna stran.'})
    return {'q': query, 'cpv': cpv, 'year': year, 'status': state, 'sort': sort, 'page': int(page)}


def contract_register(params):
    options = register_options(params)
    on = today()
    rows = Contract.objects.filter(is_addendum=False)
    for word in options['q'].split():
        rows = rows.filter(Q(data__title__icontains=word) | Q(data__procurement_title__icontains=word)
            | Q(data__buyers__icontains=word) | Q(data__contractors__icontains=word)
            | Q(buyer_registration__icontains=word) | Q(data__notice_number__icontains=word))
    if options['cpv']:
        rows = rows.filter(cpv__startswith=options['cpv'])
    if options['year']:
        rows = rows.filter(published_at__year=int(options['year']))
    if options['status'] in ('active', 'expiring'):
        rows = rows.filter(effective_end__gte=on)
        if options['status'] == 'expiring':
            rows = rows.filter(effective_end__lte=on + timedelta(days=365))
    elif options['status'] == 'ended':
        rows = rows.filter(effective_end__lt=on)
    elif options['status'] == 'unknown':
        rows = rows.filter(effective_end__isnull=True)
    count = rows.count()
    if options['sort'] == 'value':
        rows = rows.annotate(signed_value=Cast(NullIf(KeyTextTransform('value', 'data'), Value('null')),
            DecimalField(max_digits=30, decimal_places=2))).order_by(F('signed_value').desc(nulls_last=True), '-pk')
    elif options['sort'] == 'ending':
        rows = rows.order_by(F('effective_end').asc(nulls_last=True), '-pk')
    else:
        rows = rows.order_by(F('published_at').desc(nulls_last=True), '-pk')
    start = (options['page'] - 1) * PAGE_SIZE
    return {'results': [serialize(row, on) for row in rows[start:start + PAGE_SIZE]],
            'count': count, 'page': options['page'], 'page_size': PAGE_SIZE,
            'filters': options, 'dataset': dataset_info()}


@api_view(['GET'])
def contracts_view(request):
    return Response(contract_register(request.query_params))
