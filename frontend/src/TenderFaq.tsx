import { useState } from 'react';
import { ExternalLink, LoaderCircle, MessageCircleQuestion, Search } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import { queryKeys } from './queryClient';
import type { TenderFaq } from './types';
import './tender-faq.css';

const when = (value: string | null) => value ? new Date(value).toLocaleString('sl-SI', { day: 'numeric', month: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
const fold = (value: string) => value.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

export default function TenderFaqPanel({ tenderId }: { tenderId: string }) {
    const [query, setQuery] = useState('');
    const faq = useQuery({ queryKey: queryKeys.tenderFaq(tenderId), queryFn: ({ signal }) => api<TenderFaq>(`/tenders/${tenderId}/faq`, { signal }), staleTime: 10 * 60_000 });
    const data = faq.data;
    const items = (data?.items || []).filter(item => !query.trim() || fold(`${item.question} ${item.answer}`).includes(fold(query.trim())));
    const unanswered = (data?.items || []).filter(item => item.kind === 'question' && !item.answer).length;
    return <section className="surface detail-section tender-faq" aria-busy={faq.isFetching}>
        <div className="section-heading"><div><h2><MessageCircleQuestion size={19}/>Vprašanja, odgovori in pojasnila</h2><p className="section-help">Vprašanja ponudnikov in odgovori naročnika, objavljeni na portalu e-Naročanje. Odgovori so del razpisne dokumentacije.</p></div>{data?.source_url && <a className="button small" href={data.source_url} target="_blank" rel="noreferrer">Odpri na e-Naročanju<ExternalLink size={13}/></a>}</div>
        {faq.isPending && <LoaderCircle className="spin"/>}
        {(faq.error || data?.error) && <div role="alert" className="error-banner">{data?.error || faq.error?.message}<button className="button small" onClick={() => faq.refetch()}>Poskusi znova</button></div>}
        {data?.warning && <div className="info-box amber"><p>{data.warning}</p></div>}
        {data?.available && data.synced_at && <p className="tender-faq-synced">Shranjeno ob zajemu: {when(data.synced_at)}{data.document_id && <> · <a href={`/api/documents/${encodeURIComponent(data.document_id)}`} target="_blank" rel="noreferrer">Indeksirano besedilo</a> (uporabljeno pri analizi pogojev)</>}</p>}
        {data && !data.available && <p className="section-help">{data.message}</p>}
        {data?.available && !data.error && !data.items.length && <p className="tender-faq-empty">Naročnik še ni objavil nobenega vprašanja ali pojasnila.</p>}
        {!!data?.items.length && <>
            <div className="tender-faq-toolbar"><label className="tender-faq-search"><Search size={15}/><input type="search" aria-label="Išči po vprašanjih in odgovorih" placeholder="Išči po vprašanjih in odgovorih …" value={query} onChange={e => setQuery(e.target.value)}/></label><span>{data.items.length} {data.items.length === 1 ? 'objava' : data.items.length === 2 ? 'objavi' : data.items.length < 5 ? 'objave' : 'objav'}{unanswered > 0 && ` · ${unanswered} brez odgovora`}</span></div>
            {!items.length && <p className="tender-faq-empty">Ni zadetkov za »{query}«.</p>}
            <ol className="tender-faq-list">{items.map(item => <li key={item.id} className="tender-faq-item">
                <div className="tender-faq-meta"><span className={`badge ${item.kind === 'clarification' ? 'purple' : 'neutral'}`}>{item.kind === 'clarification' ? 'Pojasnilo naročnika' : 'Vprašanje'}</span><time dateTime={item.published_at || undefined}>{when(item.published_at)}</time></div>
                <p className="tender-faq-question">{item.question}</p>
                {item.kind === 'question' && (item.answer ? <div className="tender-faq-answer"><strong>Odgovor naročnika</strong><p>{item.answer}</p></div> : <div className="tender-faq-answer pending">Naročnik še ni odgovoril.</div>)}
            </li>)}</ol>
        </>}
    </section>;
}
