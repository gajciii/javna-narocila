import { Award, Check, ExternalLink, LoaderCircle, Plus } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import { queryKeys } from './queryClient';
import type { AwardReferences, CompanyReference } from './types';
import './award-references.css';

const money = (value: number | null) => value == null ? 'Vrednost ni objavljena' : new Intl.NumberFormat('sl-SI', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(value);
const day = (value: string | null) => value ? new Date(value).toLocaleDateString('sl-SI') : '';

export default function AwardReferencesPanel({ registrationNumber, references, onAdd }: { registrationNumber: string; references: CompanyReference[]; onAdd: (refs: CompanyReference[]) => void }) {
    const awards = useQuery({ queryKey: queryKeys.awardReferences(registrationNumber), queryFn: ({ signal }) => api<AwardReferences>('/profile/award-references', { signal }), staleTime: 10 * 60_000 });
    const data = awards.data;
    const present = new Set(references.flatMap(r => [r.id, r.project_identifier || '']).filter(Boolean));
    const pending = (data?.items || []).filter(item => !present.has(item.reference.id) && !present.has(item.reference.project_identifier || ''));
    return <div className="award-references">
        <div className="award-references-head"><div><strong><Award size={16}/>Zmage na javnih naročilih</strong><p>Naročila, pri katerih je bilo vaše podjetje izbrano (iskanje po matični številki{data?.registration_number ? ` ${data.registration_number}` : ''}). Uradno obvestilo o oddaji je dokazilo, zato se dodane reference štejejo kot potrjene.</p></div>{pending.length > 1 && <button type="button" className="button primary small" onClick={() => onAdd(pending.map(item => item.reference))}><Plus size={15}/>Dodaj vse ({pending.length})</button>}</div>
        {awards.isPending && <LoaderCircle className="spin"/>}
        {awards.error && <div role="alert" className="error-banner">{awards.error.message}<button type="button" className="button small" onClick={() => awards.refetch()}>Poskusi znova</button></div>}
        {data?.message && <p className="award-references-note">{data.message}</p>}
        {data && !data.message && !data.items.length && <p className="award-references-note">Med objavljenimi obvestili o oddaji{data.covered_from ? ` od ${day(data.covered_from)}` : ''} ni zmag vašega podjetja.</p>}
        {!!data?.items.length && <ul>{data.items.map(item => { const added = !pending.includes(item); return <li key={item.reference.id}>
            <div><span className="award-references-title">{item.reference.title}</span><small>{item.buyer} · {day(item.published_on)} · {money(item.reference.value)}{item.joint && ' · skupna ponudba'}</small><a href={item.reference.evidence_url} target="_blank" rel="noopener noreferrer">Obvestilo o oddaji<ExternalLink size={12}/></a></div>
            {added ? <span className="award-references-added"><Check size={14}/>V referencah</span> : <button type="button" className="button small" onClick={() => onAdd([item.reference])}><Plus size={14}/>Dodaj</button>}
        </li>; })}</ul>}
        {!!data?.items.length && <p className="award-references-note">Podatki o oddajah so zajeti{data.covered_from ? ` od ${day(data.covered_from)}` : ''}. Dodane reference se upoštevajo po shranjevanju profila. Leto reference je leto oddaje; po potrebi ga popravite na leto zaključka del.</p>}
    </div>;
}
