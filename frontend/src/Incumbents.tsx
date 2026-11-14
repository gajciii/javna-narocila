import { useState, type ReactNode } from 'react';
import { ArrowRight, ExternalLink, FileSignature, LoaderCircle, RefreshCw } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, post } from './api';
import { queryKeys } from './queryClient';
import type { Incumbents, SignedContract } from './types';

export const contractDay = (value: string | null) => value ? new Date(value).toLocaleDateString('sl-SI') : 'Ni podatka';
export const contractMoney = (value: number | null) => value == null ? 'Ni podatka' : new Intl.NumberFormat('sl-SI', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(value);
const levels: Record<number, string> = { 8: 'enak CPV', 5: 'ista kategorija CPV', 4: 'isti razred CPV', 3: 'ista skupina CPV' };
const statusLabel = { active: 'V veljavi', ended: 'Potekla', unknown: 'Rok ni objavljen' };

export function ContractEnd({ contract }: { contract: SignedContract }) {
    if (!contract.effective_end) return <span>Rok veljavnosti ni objavljen</span>;
    return <span>Velja do {contractDay(contract.effective_end)}{contract.extended && ` · podaljšano z aneksom (prvotno ${contractDay(contract.valid_to)})`}{contract.days_left != null && contract.days_left >= 0 && ` · še ${contract.days_left} dni`}</span>;
}

export function ContractCard({ contract, children }: { contract: SignedContract; children?: ReactNode }) {
    return <article className="past-award contract-card">
        <p className="past-award-meta">{contract.buyer} · sklenjena {contractDay(contract.concluded_on)}{contract.framework && ' · okvirni sporazum'}</p>
        <h4>{contract.procurement_title || contract.title}</h4>
        {contract.procurement_title && contract.title !== contract.procurement_title && <p>{contract.title}</p>}
        <p><strong>{contract.contractors.length ? contract.contractors.map(c => c.name).join(' · ') : 'Izvajalec ni naveden'}</strong>{contract.contractors.length > 1 && ' (skupna ponudba)'}</p>
        <p className="section-help"><ContractEnd contract={contract}/>{contract.addenda_count > 0 && ` · aneksov: ${contract.addenda_count}`}</p>
        <p className="section-help">Vrednost: {contractMoney(contract.value)} · CPV {contract.cpv}{contract.cpv_label && ` ${contract.cpv_label}`}</p>
        {children}
        <p className="contract-links">{contract.files.map(file => <a key={file.url} className="text-link" href={file.url} target="_blank" rel="noreferrer">{file.title}<ExternalLink size={13}/></a>)}<small>{contract.notice_number}</small></p>
    </article>;
}

/** `compact` shows only the current contractor and links to the full list in the buyer history tab. */
export default function IncumbentsPanel({ tenderId, compact = false, openFull }: { tenderId: string; compact?: boolean; openFull?: () => void }) {
    const client = useQueryClient();
    const [busy, setBusy] = useState(false);
    const [refreshError, setRefreshError] = useState('');
    const query = useQuery({ queryKey: queryKeys.incumbents(tenderId), queryFn: ({ signal }) => api<Incumbents>(`/tenders/${tenderId}/incumbents`, { signal }), staleTime: 30 * 60_000 });
    const data = query.data;
    const refresh = async () => {
        setBusy(true); setRefreshError('');
        try { client.setQueryData(queryKeys.incumbents(tenderId), await post<Incumbents>(`/tenders/${tenderId}/incumbents`)); }
        catch (error) { setRefreshError(error instanceof Error ? error.message : 'Osvežitev ni uspela.'); }
        finally { setBusy(false); }
    };
    const headline = data?.headline;
    const names = headline?.contractors.map(c => c.name).join(', ');
    if (compact) {
        if (!headline) return null;
        return <section className="surface detail-section incumbent-summary">
            <div className="section-heading"><h2><FileSignature size={19}/>{headline.kind === 'active' ? 'Trenutni izvajalec' : 'Zadnji izvajalec'}</h2><button className="text-link" onClick={openFull}>Pogodbe naročnika <ArrowRight size={14}/></button></div>
            <p><strong>{names}</strong></p>
            <p className="section-help">{headline.kind === 'active' ? `Ima veljavno pogodbo pri tem naročniku (${levels[headline.cpv_level] || 'sorodni CPV'})${headline.end ? ` do ${contractDay(headline.end)}` : ''}.` : `Zadnja sorodna pogodba (${levels[headline.cpv_level] || 'sorodni CPV'}) je potekla ${contractDay(headline.end)}.`} Povezano po matični številki naročnika in kodi CPV; predmet ni nujno enak.</p>
        </section>;
    }
    return <section className="surface detail-section incumbents" aria-busy={query.isFetching || busy}>
        <div className="section-heading"><div><h2><FileSignature size={19}/>Podpisane pogodbe naročnika za sorodni predmet</h2><p className="section-help">Kdo že izvaja podobna naročila pri tem naročniku in do kdaj veljajo pogodbe. Vir so objavljene pogodbe in aneksi.</p></div>
            <button className="button small" disabled={busy} onClick={refresh}>{busy ? <LoaderCircle className="spin" size={14}/> : <RefreshCw size={14}/>}Osveži s portala</button></div>
        {query.isLoading && <p role="status" className="past-awards-loading"><LoaderCircle className="spin"/>Nalagamo pogodbe …</p>}
        {(query.error || refreshError) && <div role="alert" className="error-banner">{refreshError || query.error?.message}</div>}
        {data?.refresh && <p role="status" className="info-box">{data.refresh.skipped ? 'Pogodbe tega naročnika so bile osvežene pred kratkim.' : `Prenesenih pogodb: ${data.refresh.fetched}.${data.refresh.remaining ? ` Preostalih: ${data.refresh.remaining}; osvežite znova za nadaljevanje.` : ''}${data.refresh.errors ? ` Neuspelih: ${data.refresh.errors}.` : ''}`}</p>}
        {data && <>
            {data.message && <p role="status" className="info-box">{data.message}</p>}
            {headline && <div className="buyer-signals"><strong>{headline.kind === 'active' ? 'Trenutni izvajalec' : 'Zadnji izvajalec'}: {names}</strong><p>{headline.kind === 'active' ? `Veljavna pogodba${headline.end ? ` do ${contractDay(headline.end)}` : ''} (${levels[headline.cpv_level] || 'sorodni CPV'}).` : `Nobena sorodna pogodba ni več v veljavi; zadnja je potekla ${contractDay(headline.end)}.`} Pogodbe povezujemo po matični številki naročnika in prvih treh števkah CPV, zato predmet ni nujno enak. Preverite naslov pogodbe.</p></div>}
            {data.results.length > 0 && <div className="past-awards-list">{data.results.map(contract => <ContractCard key={contract.id} contract={contract}><p className="section-help">{statusLabel[contract.status]} · {levels[contract.cpv_level] || 'sorodni CPV'}</p></ContractCard>)}</div>}
            {(data.total || 0) > data.results.length && <p className="section-help">Prikazanih je {data.results.length} od {data.total} sorodnih pogodb.</p>}
            <p className="past-awards-source">Vir: {data.dataset.attribution}. {data.synced_at ? `Pogodbe naročnika osvežene ${contractDay(data.synced_at)}.` : 'Pogodbe naročnika še niso v celoti zajete.'} Upoštevamo pogodbe zadnjih petih let; rok veljavnosti je najkasnejši rok iz pogodbe in njenih aneksov.</p>
        </>}
    </section>;
}
