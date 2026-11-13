"""Public contracts and addenda listed separately from tender documentation on PJN."""
import hashlib
import json

from django.utils import timezone

from .pjn_transport import fetch_json, official_url


def supported(tender):
    return (tender.data.get('source_type') == 'real'
            and type(tender.data.get('source_metadata', {}).get('dossier_id')) is int)


def sync_contracts(tender):
    """Refresh the complete manifest; failed responses never replace the stored manifest."""
    if not supported(tender):
        return []
    dossier = tender.data['source_metadata']['dossier_id']
    forms = fetch_json(f'obrazec/objava/dosjeObrazecGetList?idDosje={dossier}')
    if not isinstance(forms, list):
        raise ValueError('Neveljaven seznam objav dosjeja.')
    files, seen = {}, set()
    for form in forms:
        contract_id = form.get('idPogodba')
        if (type(contract_id) is not int or contract_id in seen
                or form.get('idObrazecStatus') != 100):
            continue
        seen.add(contract_id)
        contract = fetch_json(f'pogodba/pogodbaGet?id={contract_id}')
        if (not isinstance(contract, dict) or contract.get('id') != contract_id
                or contract.get('idDosje') != dossier or not isinstance(contract.get('datoteka'), list)):
            raise ValueError('Pogodba se ne ujema z dosjejem ali nima seznama datotek.')
        for item in contract['datoteka']:
            url = item.get('url')
            if not isinstance(url, str) or not official_url(url, attachment=True):
                raise ValueError('Pogodba vsebuje neveljavno povezavo do datoteke.')
            files[url] = {'url': url, 'title': item.get('ime') or 'Pogodba.pdf',
                          'contract_id': contract_id, 'notice_number': form.get('objavaIdent', '')}
    manifest = sorted(files.values(), key=lambda item: item['url'])
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    tender.refresh_from_db()
    previous = tender.data.get('source_metadata', {})
    tender.data = {**tender.data, 'source_metadata': {**tender.data.get('source_metadata', {}),
        'contracts_seen': bool(manifest or previous.get('contract_files') or previous.get('contracts_seen')),
        'contract_files': manifest, 'contracts_digest': digest, 'contracts_synced_at': timezone.now().isoformat()}}
    tender.save(update_fields=['data'])
    return manifest
