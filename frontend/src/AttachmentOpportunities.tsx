import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ExternalLink, FileText, Search } from 'lucide-react';
import { api, post } from './api';
import { queryClient, queryKeys } from './queryClient';
import type { PastAwardParticipant } from './types';

type Finding = {
    document_id: string;
    document_title: string;
    document_url: string;
    page: number | null;
    locator: string;
    quote: string;
    kind: 'separate_lot' | 'supplier_or_subcontractor' | 'needs_review';
    historical_participants: (PastAwardParticipant & { past_award_id: string; past_notice_url: string })[];
};

type OpportunityResult = {
    pending?: boolean;
    can_request?: boolean;
    analysed: boolean;
    document_count: number;
    unreadable_count: number;
    findings: Finding[];
    warning: string | null;
    candidate_overflow: number;
    ai_pending: number;
};

const explanations = {
    separate_lot: 'V odlomku je naveden sklop, ki bi se lahko ujemal z dejavnostjo podjetja.',
    supplier_or_subcontractor: 'Odlomek opisuje del naročila, ki bi ga vaše podjetje lahko dobavilo ali izvedlo.',
    needs_review: 'V odlomku se pojavijo izrazi iz profila. Preverite, ali gre za ustrezno postavko.',
};

function Evidence({ finding }: { finding: Finding }) {
    const source = `${finding.document_url}${finding.page ? `#page=${finding.page}` : ''}`;
    const groups = new Map<string, Finding['historical_participants']>();
    for (const person of finding.historical_participants) {
        const people = groups.get(person.past_award_id) ?? [];
        people.push(person);
        groups.set(person.past_award_id, people);
    }
    return <article className="lot-card">
        <h3>{finding.kind === 'separate_lot' ? 'Možen samostojen sklop' : finding.kind === 'needs_review' ? 'Za ročni pregled' : 'Možna dobava ali podizvajanje'}</h3>
        <p>{explanations[finding.kind]}</p>
        <blockquote className="attachment-opportunity-quote">»{finding.quote}«</blockquote>
        <a className="text-link" href={source} target="_blank" rel="noreferrer">
            <FileText size={15}/>{finding.document_title} · {finding.locator}<ExternalLink size={13}/>
        </a>
        {finding.historical_participants.length > 0 && <details className="quiet-disclosure">
            <summary>Znani ponudniki pri podobnih oddajah</summary>
            {[...groups.entries()].map(([awardId, people]) => <div key={awardId}>
                <a href={people[0].past_notice_url} target="_blank" rel="noreferrer">Obvestilo o oddaji</a>
                <ul>{people.map((p, i) => <li key={`${p.registration_number || p.name}-${i}`}>
                    <strong>{p.name}</strong> · {p.label} · <a href={p.source_url} target="_blank" rel="noreferrer">Vir</a>
                </li>)}</ul>
            </div>)}
            <p className="section-help">Seznam prikazuje ponudnike, za katere imamo zapis.</p>
        </details>}
    </article>;
}

/** `revision` changes whenever the tender, its documents or the company profile change, so stale results are not reused. */
export default function AttachmentOpportunities({ tenderId, revision }: { tenderId: string; revision: string }) {
    const [busy, setBusy] = useState(false);
    const [checkError, setError] = useState('');
    const path = `/tenders/${encodeURIComponent(tenderId)}/attachment-opportunities`;
    const queryKey = queryKeys.attachmentOpportunities(tenderId, revision);
    // While the server is still processing, poll every 4 s until results arrive.
    const opportunities = useQuery({ queryKey, queryFn: ({ signal }) => api<OpportunityResult>(path, { signal }), refetchInterval: query => query.state.data?.pending ? 4000 : false });
    const result = opportunities.data ?? null;
    const error = checkError || (opportunities.isFetching ? '' : opportunities.error?.message ?? '');

    async function checkAttachments() {
        setBusy(true);
        setError('');
        try {
            queryClient.setQueryData(queryKey, await post<OpportunityResult>(path));
        } catch (err) {
            setError((err as Error).message);
        } finally {
            setBusy(false);
        }
    }

    return <section className="surface detail-section">
        <div className="section-heading">
            <h2><Search size={19}/>Priložnost za dobavo ali podizvajanje</h2>
            {result && (result.document_count > 0 || result.can_request) && (!result.analysed || result.warning) &&
                <button className="button small" disabled={busy || result.pending} onClick={checkAttachments}>{busy || result.pending ? 'Obdelava poteka …' : 'Preveri priloge'}</button>}
        </div>
        {error && <p className="error-banner" role="alert">{error}</p>}
        {!result && !error && <p className="section-help">Nalagamo pregled prilog …</p>}
        {result?.pending && <p className="section-help" role="status">Dokumentacija je v vrsti ali se že obdeluje na strežniku. Rezultati se bodo prikazali samodejno.</p>}
        {result && !result.document_count && !result.can_request && <p className="section-help">Najprej uvozite razpisno dokumentacijo ali dodajte prilogo na zavihku Dokumenti.</p>}
        {result && result.document_count > 0 && !result.analysed && <p className="section-help">Preverite, ali dokumentacija vsebuje postavke, ki ustrezajo trenutnemu profilu podjetja.</p>}
        {result?.warning && <p className="section-help" role="status">{result.warning}</p>}
        {result?.unreadable_count ? <p className="section-help">Neberljive priloge: {result.unreadable_count}.</p> : null}
        {result?.candidate_overflow ? <p className="section-help">Odlomki zunaj izbora za analizo: {result.candidate_overflow}.</p> : null}
        {result?.ai_pending ? <p className="section-help">Odlomki za ročni pregled: {result.ai_pending}.</p> : null}
        {result?.analysed && !result.findings.length && <p className="section-help">V pregledanih odlomkih ni bilo zaznanega ujemanja.</p>}
        {result?.findings.slice(0, 5).map((finding, i) => <Evidence key={`${finding.document_id}-${i}`} finding={finding}/>)}
        {result && result.findings.length > 5 && <details className="quiet-disclosure">
            <summary>Prikaži še {result.findings.length - 5} odlomkov</summary>
            {result.findings.slice(5).map((finding, i) => <Evidence key={`${finding.document_id}-${i}`} finding={finding}/>)}
        </details>}
    </section>;
}
