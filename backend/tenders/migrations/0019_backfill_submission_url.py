from django.db import migrations


def backfill(apps, schema_editor):
    from tenders.pjn_transport import submission_url
    Tender = apps.get_model('tenders', 'Tender')
    SyncAttempt = apps.get_model('tenders', 'SyncAttempt')
    wanted = {}
    for tender in Tender.objects.filter(data__source_type='real').only('pk', 'data').iterator():
        meta = tender.data.get('source_metadata') or {}
        if meta.get('notice_id') and not meta.get('submission_url'):
            wanted[str(meta['notice_id'])] = tender.pk
    if not wanted:
        return
    found = {}
    # Stored portal responses already hold the link; the newest attempt per notice wins.
    for source_id, url in SyncAttempt.objects.filter(success=True, source_id__in=list(wanted)).order_by('pk').values_list(
            'source_id', 'raw__elektronskaPredlozitevURL').iterator():
        if submission_url(url):
            found[source_id] = submission_url(url)
    for notice_id, url in found.items():
        tender = Tender.objects.get(pk=wanted[notice_id])
        tender.data = {**tender.data, 'source_metadata': {**tender.data.get('source_metadata', {}), 'submission_url': url}}
        tender.save(update_fields=['data'])


class Migration(migrations.Migration):
    dependencies = [('tenders', '0018_tender_questions')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
