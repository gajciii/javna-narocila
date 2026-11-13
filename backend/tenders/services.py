from datetime import datetime, timedelta
from django.db import transaction
from django.db.models import Prefetch
from .models import Tender, CompanyProfile, Notification, DemoEvent, TenderVersion, SavedSearch, SyncAttempt
from .seed import get_profile, today
from .accounts import account_id, companies, searches
from .matching import serialize_tender
from .ai import ai_enabled, rules_mode
from .runtime_data import application_tenders, test_fixtures_enabled


def serialize_notification(item):
    return {'id': item.id, 'tender_id': item.tender_id, 'type': item.type, 'title': item.title,
            'body': item.body, 'read': item.read, 'created_at': item.created_at.isoformat(), 'is_demo': item.is_demo,
            'improvement': item.payload if item.type == 'improvement' else None}


def all_notifications():
    from .improvements import refresh_suggestions, visible_notifications
    refresh_suggestions()
    rows = list(visible_notifications())
    if not test_fixtures_enabled():
        rows = [row for row in rows if not row.is_demo]
    if account_id() is not None:
        from .models import NotificationRead
        read_ids = set(NotificationRead.objects.filter(owner_id=account_id()).values_list('notification_id', flat=True))
        for row in rows:
            if row.type != 'improvement':
                row.read = row.pk in read_ids
    return [serialize_notification(n) for n in rows]


def all_tenders(profile=None):
    profile = profile or get_profile()
    from .relevance import resolve_matches
    from .documents import document_metadata
    tenders = list(application_tenders().prefetch_related(Prefetch('document_records',
        queryset=document_metadata().order_by('id'), to_attr='_document_metadata')))
    if account_id() is not None:
        from .models import TenderFollow
        followed = set(TenderFollow.objects.filter(owner_id=account_id()).values_list('tender_id', flat=True))
        for tender in tenders:
            tender._account_following = tender.pk in followed
    matches = resolve_matches(tenders, profile)
    return [serialize_tender(t, profile, content_result=matches[t.pk]) for t in tenders]


def serialize_search(item):
    return {'id': item.id, 'name': item.name, 'filters': item.filters}


def bootstrap():
    from .pjn_sync import status as pjn_status
    from .ajpes import status as ajpes_status
    profile = get_profile()
    latest = SyncAttempt.objects.filter(success=True, error='').order_by('-created_at').first()
    return {'profiles': [{'id': item.pk, 'name': item.data.get('name', ''),
                          'registration_number': item.data.get('registration_number', '')}
                         for item in companies().order_by('pk')],
            'profile': profile, 'tenders': all_tenders(profile), 'notifications': all_notifications(),
            'saved_searches': [serialize_search(s) for s in searches()],
            'meta': {'demo': test_fixtures_enabled(), 'ai_mode': 'live' if ai_enabled() else rules_mode(), 'today': today().isoformat(),
                     'last_sync': latest.created_at.isoformat() if latest else None,
                     'integrations': {'pjn': pjn_status(), 'ajpes': ajpes_status()}}}


@transaction.atomic
def trigger_event(event_type):
    if event_type not in ['new', 'correction', 'deadline']:
        raise ValueError('Neznan demo dogodek.')
    _, created = DemoEvent.objects.get_or_create(key=event_type)
    if not created:
        return {'message': 'Ta demo dogodek je že prikazan. Za ponovitev ponastavite demo.', 'created': False,
                'notifications': all_notifications(), 'tenders': all_tenders()}
    profile = get_profile()
    tender = Tender.objects.select_for_update().get(pk='satellite' if event_type == 'correction' else 'energy-iot')
    before = serialize_tender(tender, profile)
    data = dict(tender.data)
    if event_type == 'correction':
        data['version'] = 2
        data['has_update'] = True
        data['changes'] = [{'field': 'Referenčni pogoj', 'before': 'Najmanj ena primerljiva zaključena referenca.',
            'after': 'Najmanj dve primerljivi zaključeni referenci.',
            'impact': 'Ponovno preverite število potrjenih referenc v profilu.', 'document_id': 'satellite-v2', 'page': 2}]
        title = 'Popravek je spremenil referenčni pogoj'
    elif event_type == 'deadline':
        old = data['deadline']
        data['deadline'] = (datetime.fromisoformat(old) + timedelta(days=7)).isoformat()
        data['version'] += 1
        data['has_update'] = True
        data['changes'] = data.get('changes', []) + [{'field': 'Rok za oddajo', 'before': old, 'after': data['deadline'], 'impact': 'Za pripravo ponudbe je na voljo sedem dodatnih dni.'}]
        title = 'Rok za oddajo je podaljšan'
    else:
        data['is_new'] = True
        data['published_at'] = today().isoformat()
        title = 'Nova priložnost za vaše podjetje'
    tender.data = data
    tender.save(update_fields=['data', 'updated_at'])
    TenderVersion.objects.get_or_create(tender=tender, version=data['version'], defaults={'data': data})
    after = serialize_tender(tender, profile)
    if event_type == 'correction':
        condition = next((c for c in after['match']['conditions'] if c['id'] == 'satellite-reference'), None)
        evidence = condition['company_value'] if condition else 'Pogoj še ni preverjen.'
        body = f'Zahtevani sta dve primerljivi referenci. Po trenutnem profilu: {evidence}. {after["match"]["open_question"]}'
        data['changes'][0]['impact'] = body
        tender.data = data
        tender.save(update_fields=['data'])
    elif event_type == 'deadline':
        body = 'Rok za oddajo je podaljšan za sedem dni. Odprite primerjavo prejšnjega in novega roka.'
    else:
        body = 'Objavljen je nov demo razpis. ' + after['match']['reasons'][0]
    relevant_new = after['status'] == 'open' and after['match']['level'] != 'low' and after['match']['recommendation'] not in ['unsuitable', 'closed']
    notify = relevant_new if event_type == 'new' else (tender.following or relevant_new)
    if notify:
        Notification.objects.get_or_create(event_key=f'demo:{event_type}', defaults={
            'tender': tender, 'type': event_type, 'title': title, 'body': body, 'is_demo': True})
    return {'message': 'Demo dogodek je prikazan.' if notify else 'Dogodek je obdelan; razpis ni ustrezna odprta priložnost, zato novo obvestilo ni ustvarjeno.',
            'created': True, 'notifications': all_notifications(), 'tenders': all_tenders()}
