import { useState } from 'react';
import { Building2, ChevronDown, ExternalLink, History, LoaderCircle, Trophy } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import { queryKeys } from './queryClient';
import { erarRecipient } from './CompanyDataSources';
import type { PastAward, SimilarAwards } from './types';

const day = (value: string | null) => value ? new Date(value).toLocaleDateString('sl-SI', { day: 'numeric', month: 'numeric', year: 'numeric' }) : 'Ni podatka';
const amount = (value: number | null, currency: string | null) => {
    if (value == null) return 'Ni podatka';
    if (!currency) return `${value.toLocaleString('sl-SI')} (valuta ni navedena)`;
    return new Intl.NumberFormat('sl-SI', { style: 'currency', currency, minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(value);
};
const changePercent = new Intl.NumberFormat('sl-SI', { style: 'percent', maximumFractionDigits: 1, signDisplay: 'exceptZero' });
const differenceLabel = (difference: number, currency: string) =>
    difference === 0 ? 'Enako oceni' : `${amount(Math.abs(difference), currency)} ${difference < 0 ? 'pod' : 'nad'} oceno`;

function WinnerRanking({ winners }: { winners: SimilarAwards['summary']['top_winners'] }) {
    const ranked = [...winners].sort((a, b) => b.wins - a.wins);
    const rank = (wins: number) => ranked.findIndex(winner => winner.wins === wins) + 1;
    const selectionLabel = (wins: number) => wins % 100 === 1 ? 'izbira' : wins % 100 === 2 ? 'izbiri' : [3, 4].includes(wins % 100) ? 'izbire' : 'izbir';
    return <div className="past-awards-winners">
        <h3><Trophy size={20}/>Najpogostejši izbrani ponudniki</h3>
        <ol className="winner-podium" data-count={Math.min(ranked.length, 3)} role="list">
            {ranked.slice(0, 3).map(winner => <li className={winner.wins === ranked[0].wins ? 'leading' : ''} key={winner.registration_number || winner.name}>
                <div className="winner-info"><span className="winner-place">{rank(winner.wins)}. mesto</span><strong>{winner.name}</strong><small>{winner.registration_number ? `MŠ ${winner.registration_number}` : 'Matična številka ni navedena'}</small></div>
                <div className="winner-step"><strong>{winner.wins}</strong><span>{selectionLabel(winner.wins)}</span></div>
            </li>)}
        </ol>
        <p className="winner-ranking-note">Število izbir med prikazanimi podobnimi naročili. Enako število pomeni deljeno mesto.</p>
    </div>;
}

export function HistoricalAward({ award }: { award: Omit<PastAward, 'similarity'> & { similarity?: number } }) {
    const awardCurrency = award.award_currency === undefined ? award.currency : award.award_currency;
    const estimateCurrency = award.estimate_currency === undefined ? award.currency : award.estimate_currency;
    const comparison = award.value_comparison;
    const winners = new Set(award.winners.map(w => w.registration_number || w.name));
    const others = (award.participants || []).filter(p => !winners.has(p.registration_number || p.name));
    const offers = award.lowest_offer != null && award.highest_offer != null && award.highest_offer !== award.lowest_offer
        ? `${amount(award.lowest_offer, awardCurrency)} – ${amount(award.highest_offer, awardCurrency)}` : null;
    return <article className="similar-tender">
        <a className="similar-tender-link" href={award.notice_url} target="_blank" rel="noopener noreferrer" aria-label={`${award.title} – odpri uradno objavo v novem zavihku`}>
            <div className="similar-tender-subject">
                <div className="similar-tender-meta">{award.similarity != null && <span>Podobnost predmeta {Math.round(award.similarity * 100)} %</span>}<span>{day(award.published_on)}</span>{award.framework && <span>Okvirni sporazum</span>}</div>
                <h4>{award.title}</h4>
                {award.lot_title && award.lot_title !== award.title && <p className="similar-tender-lot">Sklop: {award.lot_title}</p>}
                <p className="similar-tender-buyer"><Building2 size={15}/>{award.buyer}</p>
            </div>
            <div className="similar-tender-winner"><span className="similar-tender-label">{award.awarded ? (award.winners.length > 1 ? 'Izbrani ponudniki' : 'Izbrani ponudnik') : 'Izid naročila'}</span>
                {!award.awarded ? <strong className="similar-tender-unawarded">Brez izbranega ponudnika</strong> : award.winners.length ? award.winners.map(winner => <strong key={winner.registration_number || winner.name}>{winner.name}</strong>) : <strong>Podatek ni objavljen</strong>}
            </div>
            <div className="similar-tender-price"><span className="similar-tender-label">Pogodbena vrednost</span><strong>{award.awarded ? amount(award.awarded_value, awardCurrency) : '—'}</strong><span>{award.tenders_received == null ? 'Število ponudb ni objavljeno' : `Prejetih ponudb: ${award.tenders_received}`}</span></div>
            <span className="similar-tender-open"><ExternalLink size={20}/><span>Odpri objavo</span></span>
        </a>
        <details className="similar-tender-details"><summary>Več podatkov<ChevronDown size={16}/></summary><div className="similar-tender-extra">
            <dl><div><dt>Ocenjena vrednost</dt><dd>{amount(award.estimated_value, estimateCurrency)}</dd></div>{comparison && <div><dt>Razlika glede na ocenjeno vrednost</dt><dd>{differenceLabel(comparison.difference, comparison.currency)}{comparison.difference !== 0 && ` (${changePercent.format(comparison.ratio - 1)})`}</dd></div>}<div><dt>Postopek</dt><dd>{award.procedure || 'Ni podatka'}</dd></div>{offers && <div><dt>Razpon dopustnih ponudb</dt><dd>{offers}</dd></div>}{award.cpv.length > 0 && <div><dt>CPV</dt><dd>{award.cpv.join(' · ')}</dd></div>}<div><dt>Obvestilo o oddaji</dt><dd>{award.notice_number || 'Ni podatka'}</dd></div></dl>
            {award.erar_payments && <div><h5>Izplačano po uvoženih podatkih ERAR</h5><p><strong>{amount(award.erar_payments.amount, 'EUR')}</strong> · {award.erar_payments.count} transakcij</p><p>Zadnje plačilo {day(award.erar_payments.latest_payment_on)} · izvoz {day(award.erar_payments.latest_export_on)}</p></div>}
            {award.winners.flatMap(winner => {
                const url = erarRecipient(winner.registration_number);
                return url ? [<p key={url}><a href={url} target="_blank" rel="noopener noreferrer">ERAR · javna plačila podjetju {winner.name}<ExternalLink size={13}/></a></p>] : [];
            })}
            {award.winners.some(w => w.registration_number) && <div><h5>Matične številke izbranih ponudnikov</h5>{award.winners.filter(w => w.registration_number).map(w => <p key={w.registration_number}>{w.name} · MŠ {w.registration_number}</p>)}</div>}
            {others.length > 0 && <div><h5>Drugi ponudniki</h5><ul>{others.map((participant, index) => <li key={`${participant.registration_number || participant.name}-${index}`}><a href={participant.source_url} target="_blank" rel="noopener noreferrer">{participant.name}<ExternalLink size={12}/></a> · {participant.label}</li>)}</ul></div>}
        </div></details>
    </article>;
}

export default function PastAwardsPanel({ tenderId }: { tenderId: string }) {
    // Historical award data rarely changes, so keep it cached for the session.
    const query = useQuery({ queryKey: queryKeys.similarAwards(tenderId), queryFn: ({ signal }) => api<SimilarAwards>(`/tenders/${tenderId}/similar-awards`, { signal }), staleTime: 30 * 60_000 });
    const [sort, setSort] = useState('similarity');
    const data = query.data ?? null;
    const error = query.isFetching ? '' : query.error?.message ?? '';
    const s = data?.summary;
    const results = [...(data?.results || [])].sort((a, b) => sort === 'newest'
        ? (b.published_on || '').localeCompare(a.published_on || '') : b.similarity - a.similarity);
    const knownBids = results.filter(award => award.tenders_received != null);
    const singleBids = knownBids.filter(award => award.tenders_received === 1).length;
    return <section className="surface detail-section past-awards">
        <div className="section-heading"><div><h2><History size={19}/>Analiza podobnih preteklih razpisov</h2><p className="section-help">Poglejte, kdo je bil izbran pri podobnih naročilih, za kakšno vrednost in koliko ponudb je prejel naročnik.</p></div></div>
        {error && <div role="alert" className="error-banner">{error}<button className="button small" onClick={() => query.refetch()}>Poskusi znova</button></div>}
        {!data && !error && <div className="past-awards-loading" role="status"><LoaderCircle className="spin"/>Iščemo podobne razpise …</div>}
        {data && <>
            {data.warning && <div className="info-box amber"><p>{data.warning}</p></div>}
            {!results.length && <div className="empty-state compact"><History size={26}/><p>{data.message || 'Podobnih preteklih razpisov še ni v shranjenih podatkih.'}</p></div>}
            {results.length > 0 && <>
                <div className="similar-awards-overview" aria-label="Povzetek podobnih razpisov">
                    <div><strong>{results.length}</strong><span>podobnih preteklih razpisov</span></div>
                    <div><strong>{s?.median_tenders == null ? '—' : new Intl.NumberFormat('sl-SI').format(s.median_tenders)}</strong><span>ponudb na naročilo <small>(mediana)</small></span></div>
                    <div><strong>{knownBids.length ? <>{singleBids}<small> od {knownBids.length}</small></> : '—'}</strong><span>naročil z eno samo ponudbo</span></div>
                </div>
                <div className="similar-awards-list-heading"><div><h3>Podobni razpisi</h3><p>Klik na razpis odpre uradno objavo v novem zavihku. To so pretekla naročila, na katera se ne morete več prijaviti.</p></div><label className="similar-awards-sort"><span>Razvrsti</span><select value={sort} onChange={event => setSort(event.target.value)}><option value="similarity">Najbolj podobni</option><option value="newest">Najnovejši</option></select></label></div>
                <div className="similar-tenders-list">{results.map(award => <HistoricalAward key={award.id} award={award}/>)}</div>
                {s && s.top_winners.length > 0 && <WinnerRanking winners={s.top_winners}/>}
            </>}
            <details className="similar-awards-disclosure"><summary>Viri in način primerjave<ChevronDown size={18}/></summary><div className="similar-awards-method">
                <p>{data.mode === 'ai' ? 'Podobnost predmeta je presodil Gemini.' : data.matching === 'semantic' ? 'Primerjava uporablja pomensko ujemanje predmeta naročila.' : 'Primerjava uporablja besedilno ujemanje predmeta naročila.'} Prikazana podobnost primerja predmeta naročil, ne ustreznosti vašega podjetja.</p>
                <p>Izbrani ponudniki so povzeti iz obvestil o oddaji. Drugi ponudniki izhajajo iz dodatnih zapisnikov z navedenim virom. Lestvica prikazuje število izbir samo med zgornjimi podobnimi naročili.</p>
                <p>Vir: {data.dataset.attribution}, {data.dataset.label}, {data.dataset.license}. Zbirka zajema {data.dataset.lots} sklopov iz obvestil, objavljenih {day(data.dataset.coverage_from)} – {day(data.dataset.coverage_to)}, in ni popolna.</p>
            </div></details>
        </>}
    </section>;
}
