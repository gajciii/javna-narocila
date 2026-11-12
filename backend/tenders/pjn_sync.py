"""One bounded collection run, at most two starts per Slovenian calendar day."""
import logging
from datetime import timedelta
from time import monotonic, sleep

from django.db import IntegrityError, transaction
from django.utils import timezone

from django.db.models import Max

from .models import PastAward, SyncRun, SyncAttempt, Tender, TenderVersion, Notification
from .past_awards import from_pjn, import_notices
from .pjn_normalize import normalize_notice, timestamp
from .pjn_transport import fetch_json, safe_error
from .pjn_documents import download_documents

log = logging.getLogger(__name__)


def reserve_run(kind):
    for slot in (1, 2):
        try:
            with transaction.atomic():
                return SyncRun.objects.create(day=timezone.localdate(), slot=slot, kind=kind)
        except IntegrityError:
            continue
    return None


def finish(run, result):
    run.finished_at = timezone.now()
    run.result = {k: v for k, v in result.items() if k != 'tender'}
    run.save(update_fields=['finished_at', 'result'])
    return result


def status():
    latest = SyncRun.objects.order_by('-started_at').first()
    last_success = SyncAttempt.objects.filter(success=True, error='').order_by('-created_at').first()
    return {'provider': 'e-Naročanje', 'state': 'connected' if last_success else 'ready',
            'last_success': last_success.created_at.isoformat() if last_success else None,
            'runs_remaining': max(0, 2 - SyncRun.objects.filter(day=timezone.localdate()).count()),
            'latest_result': latest.result if latest else None,
            'real_count': Tender.objects.filter(data__source_type='real').count()}


def fallback(notice_id, warning):
    record = Tender.objects.filter(data__source_metadata__notice_id=str(notice_id)).first()
    if not record and str(notice_id) == '1144799':
        record = Tender.objects.filter(pk='ijs-archive').first()
    result = {'mode': 'snapshot' if record else 'unavailable', 'warning': warning,
              'message': 'Prikazan je shranjen zapis; svežega stanja vira ni bilo mogoče potrditi.' if record else 'Objave ni bilo mogoče uvoziti. Obstoječi podatki so ohranjeni.'}
    if record:
        result['tender'] = record
    return result


def persist_notice(data):
    from .matching import serialize_tender
    from .seed import get_profile
    meta = data['source_metadata']
    with transaction.atomic():
        record = Tender.objects.filter(pk=data['id']).first()
        created = record is None
        old = record.data if record else {}
        old_meta = old.get('source_metadata', {})
        old_time, new_time = timestamp(old_meta.get('published_timestamp')), timestamp(meta.get('published_timestamp'))
        # Importing an older URL must not roll back a correction or reopen an award.
        if old_time and new_time and new_time < old_time:
            return record, False, False
        compare_keys = ('title', 'buyer', 'region', 'kind', 'cpv', 'value', 'deadline', 'status', 'summary', 'criteria', 'lots')
        changed = created or any(data.get(k) != old.get(k) for k in compare_keys) or meta.get('notice_id') != old_meta.get('notice_id') or meta.get('attachment_url') != old_meta.get('attachment_url')
        if created:
            data['is_new'] = True
            record = Tender.objects.create(id=data['id'], data=data)
        elif changed:
            labels = {'title': 'Naslov', 'buyer': 'Naročnik', 'deadline': 'Rok za oddajo', 'status': 'Stanje', 'value': 'Vrednost', 'summary': 'Predmet', 'criteria': 'Merila', 'lots': 'Sklopi'}
            changes = [{'field': labels.get(k, k), 'before': str(old.get(k) if old.get(k) is not None else 'Ni podatka'),
                        'after': str(data.get(k) if data.get(k) is not None else 'Ni podatka'),
                        'impact': 'Preverite vpliv spremembe na pripravo prijave.'}
                       for k in compare_keys if old.get(k) != data.get(k)]
            if meta.get('attachment_url') != old_meta.get('attachment_url'):
                changes.append({'field': 'Dokumentacija', 'before': 'Prejšnja dokumentacija', 'after': 'Nova dokumentacija', 'impact': 'Pogoje je treba ponovno preveriti; prejšnja analiza ne potrjuje novih pogojev.'})
            if not changes:
                changes = [{'field': 'Objava', 'before': str(old_meta.get('notice_number') or 'Prejšnja objava'), 'after': str(meta.get('notice_number')), 'impact': meta.get('correction_description') or 'Objavljena je nova različica; preverite izvor.'}]
            data.update(version=old.get('version', 1) + 1, has_update=True, changes=old.get('changes', []) + changes, is_new=old.get('is_new', False))
            record.data = data
            record.save(update_fields=['data', 'updated_at'])
        else:
            # Refresh provenance without erasing document state or past changes.
            record.data = {**old, 'source_metadata': {**old_meta, 'fetched_at': meta['fetched_at'],
                **({'buyers': meta['buyers']} if 'buyers' in meta else {}),
                **({'submission_url': meta['submission_url']} if meta.get('submission_url') else {})}}
            record.save(update_fields=['data', 'updated_at'])
        if changed:
            TenderVersion.objects.create(tender=record, version=record.data['version'], data=record.data)
            # Keep bounded collection independent of external AI latency. The UI
            # calculates cached Gemini fit in one batch when the refreshed list opens.
            evaluated = serialize_tender(record, get_profile(), content_result={'mode': 'rules'})
            relevant = evaluated['status'] == 'open' and evaluated['match']['level'] != 'low' and evaluated['match']['recommendation'] != 'unsuitable'
            if (created and relevant) or (not created and record.following):
                deadline_changed = not created and old.get('deadline') != data.get('deadline')
                body = 'Predmet se ujema s profilom. Pogoje iz dokumentacije je treba še preveriti.'
                if not created:
                    body = 'Objavljena je sprememba spremljanega razpisa. ' + (f"Rok: {old.get('deadline') or 'Ni podatka'} → {data.get('deadline') or 'Ni podatka'}. " if deadline_changed else '') + (meta.get('correction_description') or 'Preglejte primerjavo in ponovno preverite pogoje.')
                Notification.objects.get_or_create(event_key=f'pjn:{record.id}:v{record.data["version"]}', defaults={
                    'tender': record, 'type': 'new' if created else 'deadline' if deadline_changed else 'correction',
                    'title': 'Nova relevantna objava' if created else 'Sprememba spremljanega razpisa', 'body': body[:3000], 'is_demo': False})
    return record, created, changed


def collect_notice(notice_id, download=True, accept=None):
    """``accept`` may reject the normalized notice; it is then neither stored nor downloaded."""
    attempt = SyncAttempt.objects.create(source_id=str(notice_id))
    try:
        raw = fetch_json(f'obrazec/objava/obrazecGet?id={notice_id}')
        attempt.raw = raw if isinstance(raw, dict) else {'response': raw}
        attempt.success = True
        attempt.save(update_fields=['raw', 'success'])
        record_awards(raw)
        normalized = normalize_notice(raw, notice_id)
        if accept and not accept(normalized):
            return {'mode': 'skipped', 'message': 'Objava ne ustreza izbranemu obsegu.'}
        record, created, changed = persist_notice(normalized)
        result = {'mode': 'live', 'tender': record, 'created': created, 'changed': changed,
                  'message': 'Pridobljeni so dejanski metapodatki iz e-Naročanja.'}
        if download or record.following:
            # Before downloading, so the queued index job already includes the portal Q&A.
            from .pjn_faq import try_sync
            faq = try_sync(record, requeue=not download)
            record.refresh_from_db()
            result['questions'] = faq['count']
        if download and (changed or not record.document_records.filter(version=record.data['version']).exists()):
            documents = download_documents(record)
            result.update(documents)
            result['message'] += f" Shranjenih prilog: {documents['downloaded']}."
        return result
    except Exception as exc:
        attempt.error = safe_error(exc)
        attempt.save(update_fields=['error'])
        return fallback(notice_id, attempt.error)


def record_awards(raw):
    """An award notice fetched for any reason also updates the past-awards table; never fails collection."""
    try:
        record = from_pjn(raw)
        return import_notices([record])['lots'] if record else 0
    except Exception as exc:  # noqa: BLE001 - the tender itself must still be collected
        log.warning('Award notice %s not recorded: %s', raw.get('id') if isinstance(raw, dict) else '?', type(exc).__name__)
        return 0


AWARD_PAGE = 100
AWARD_OVERLAP = timedelta(days=2)


def award_rows(since, until):
    """IDs of award notices (phase "Rezultat") published on days since..until inclusive."""
    offset = 0
    while True:
        grid = fetch_json('obrazec/objava/obrazecGetGrid', {
            'startRow': offset, 'endRow': offset + AWARD_PAGE, 'page': offset // AWARD_PAGE + 1, 'search': '',
            'idSifCpv': [], 'idSifPostopekFaza': [1], 'podrejeniCpv': True,
            'objavaDejanskaDatumOd': since.isoformat() + 'T00:00:00',
            'objavaDejanskaDatumDo': (until + timedelta(days=1)).isoformat() + 'T00:00:00',
            'sortModel': [{'colId': 'objavaDejanskaDatum', 'sort': 'asc'}]})
        rows = grid.get('data') if isinstance(grid, dict) else None
        total = grid.get('lastRow') if isinstance(grid, dict) else None
        if not isinstance(rows, list) or not isinstance(total, int):
            raise ValueError('Seznam objav nima pričakovane oblike.')
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get('idObrazec'), int):
                yield str(row['idObrazec'])
        offset += len(rows)
        if not rows or offset >= total:
            break


def sync_awards(since=None, until=None, max_notices=None, delay=0.3, progress=None):
    """Imports award notices missing from PastAward directly from PJN.

    Without ``since`` it continues from the newest stored award (with a short overlap for late
    publications), so a daily call keeps the table current and a longer window backfills it."""
    until = until or timezone.localdate()
    if since is None:
        newest = PastAward.objects.aggregate(newest=Max('published_on'))['newest']
        since = newest - AWARD_OVERLAP if newest else until - timedelta(days=30)
    if since > until:
        raise ValueError('Začetek obdobja je po koncu.')
    known = set(PastAward.objects.filter(published_on__gte=since).values_list('notice_id', flat=True))
    result = {'since': since.isoformat(), 'until': until.isoformat(), 'listed': 0, 'fetched': 0,
              'notices': 0, 'lots': 0, 'errors': []}
    batch = []

    def flush():
        if batch:
            imported = import_notices(batch)
            result['notices'] += imported['notices']
            result['lots'] += imported['lots']
            batch.clear()

    for notice_id in award_rows(since, until):
        result['listed'] += 1
        if notice_id in known:
            continue
        if max_notices is not None and result['fetched'] >= max_notices:
            break
        result['fetched'] += 1
        try:
            record = from_pjn(fetch_json(f'obrazec/objava/obrazecGet?id={notice_id}'))
            if record and str(record['id']) == notice_id:
                batch.append(record)
        except Exception as exc:  # noqa: BLE001 - one unavailable notice must not stop the window
            result['errors'].append({'notice_id': notice_id, 'message': safe_error(exc)})
        if len(batch) >= 50:
            flush()
        if progress:
            progress()
        if delay:
            sleep(delay)
    flush()
    return result


def import_single(value):
    from .importer import parse_notice_id
    notice_id = parse_notice_id(value)
    run = reserve_run('single')
    if not run:
        return fallback(notice_id, 'Dosežena je omejitev dveh zagonov zajema na dan. Naslednji zajem bo mogoč jutri.')
    return finish(run, collect_notice(notice_id))


def sync_recent(limit=20):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError('Izberite med 1 in 50 objavami.')
    run = reserve_run('recent')
    if not run:
        return {'mode': 'limited', 'message': 'Dosežena je omejitev dveh zagonov zajema na dan.', 'imported': 0, 'updated': 0, 'errors': []}
    result = {'mode': 'live', 'imported': 0, 'updated': 0, 'checked': 0, 'errors': [], 'tender_ids': []}
    started = monotonic()
    try:
        grid = fetch_json('obrazec/objava/obrazecGetGrid', {
            'startRow': 0, 'endRow': limit, 'page': 1, 'search': '', 'idSifCpv': [], 'idSifPostopekFaza': [], 'podrejeniCpv': True,
            'objavaDejanskaDatumOd': (timezone.localdate() - timedelta(days=7)).isoformat() + 'T00:00:00',
            'sortModel': [{'colId': 'objavaDejanskaDatum', 'sort': 'desc'}]})
        if not isinstance(grid, dict) or not isinstance(grid.get('data'), list):
            raise ValueError('Seznam objav nima pričakovane oblike.')
        ids = []
        seen_dossiers = set()
        for row in grid['data'][:limit]:
            if isinstance(row.get('idObrazec'), int) and row.get('idDosje') not in seen_dossiers:
                ids.append(row['idObrazec'])
                seen_dossiers.add(row.get('idDosje'))
        # A followed notice remains tracked even after it falls out of recommendations.
        followed = Tender.objects.filter(following=True, data__source_type='real')
        for tender in followed[:30]:
            if monotonic() - started > 60:
                result['errors'].append({'id': 'zajem', 'message': 'Časovna omejitev zajema; preostali spremljani dosjeji niso bili preverjeni.'})
                break
            dossier = tender.data.get('source_metadata', {}).get('dossier_id')
            if not isinstance(dossier, int) or dossier in seen_dossiers:
                continue
            try:
                versions = fetch_json(f'obrazec/objava/dosjeObrazecGetList?idDosje={dossier}')
                latest = max((x for x in versions if isinstance(x, dict) and isinstance(x.get('id'), int)), key=lambda x: x.get('objavaDejanskaDatum') or '', default=None)
                if latest:
                    ids.append(latest['id'])
            except Exception as exc:
                result['errors'].append({'id': tender.id, 'message': safe_error(exc)})
        for index, notice_id in enumerate(dict.fromkeys(ids)):
            if monotonic() - started > 60:
                result['errors'].append({'id': 'zajem', 'message': 'Časovna omejitev zajema; seznam je delno prenesen.'})
                break
            # Bound automatic attachment downloads; single URL import downloads its own files.
            item = collect_notice(str(notice_id), download=index < 3)
            result['checked'] += 1
            if item['mode'] == 'live':
                result['imported'] += int(item['created'])
                result['updated'] += int(item['changed'] and not item['created'])
                result['tender_ids'].append(item['tender'].id)
                if item.get('warning') and item.get('downloaded', 0) == 0:
                    result['errors'].append({'id': str(notice_id), 'message': item['warning']})
            else:
                result['errors'].append({'id': str(notice_id), 'message': item['warning']})
        if not result['tender_ids'] and result['errors']:
            result['mode'] = 'unavailable'
        elif result['errors']:
            result['mode'] = 'partial'
        result['message'] = f"Pregledanih objav: {result['checked']}. Novih razpisov: {result['imported']}. Posodobljenih: {result['updated']}."
        result['warning'] = 'Zajet je omejen nabor zadnjih objav in do 30 spremljanih dosjejev. Samodejno prenesemo priloge prvih treh objav; preostale lahko uvozite po URL-ju.'
    except Exception as exc:
        result.update(mode='unavailable', message=safe_error(exc))
    return finish(run, result)
