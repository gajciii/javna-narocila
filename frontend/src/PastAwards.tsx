import { Fragment } from 'react';
import { Building2, ExternalLink, History, LoaderCircle, Trophy, XCircle } from 'lucide-react';
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
const percent = (value: number | null) => value == null ? '—' : `${Math.round(value * 100)} %`;
const changePercent = new Intl.NumberFormat('sl-SI', { style: 'percent', maximumFractionDigits: 1, signDisplay: 'exceptZero' });
const differenceLabel = (difference: number, currency: string) =>
    difference === 0 ? 'Enako oceni' : `${amount(Math.abs(difference), currency)} ${difference < 0 ? 'pod' : 'nad'} oceno`;

function Outcome({ award }: { award: PastAward }) {
    if (!award.awarded) return <div className="past-award-outcome none"><XCircle size={18}/><div><strong>Naročilo ni bilo oddano</strong><span>Naročnik ni izbral ponudnika.</span></div></div>;
    const comparison = award.value_comparison;
    const awardCurrency = award.award_currency === undefined ? award.currency : award.award_currency;
    const estimateCurrency = award.estimate_currency === undefined ? award.currency : award.estimate_currency;
    return <div className="past-award-outcome">
        <Trophy size={18}/>
        <div>
            <span className="past-award-label">{award.winners.length > 1 ? 'Zmagali (skupna ponudba)' : 'Zmagal'}</span>
            {award.winners.map(w => <strong key={w.registration_number || w.name}>{w.name}{w.registration_number && <small> · MŠ {w.registration_number}</small>}</strong>)}
        </div>
        <div className="past-award-price">
            <span className="past-award-label">Pogodbena vrednost</span>
            <strong>{amount(award.awarded_value, awardCurrency)}</strong>
            {award.estimated_value != null && <small>Ocenjena vrednost {amount(award.estimated_value, estimateCurrency)}</small>}
            {comparison && <small>{differenceLabel(comparison.difference, comparison.currency)}{comparison.difference !== 0 && ` (${changePercent.format(comparison.ratio - 1)})`}</small>}
        </div>
    </div>;
}

function ValueOverview({ summary }: { summary: SimilarAwards['summary'] }) {
    const totals = summary.value_totals;
    return <div className="past-award">
        <h3>Ocenjena in pogodbena vrednost</h3>
        {totals ? <>
            <div className="past-awards-stats">
                <div><strong>{amount(totals.estimated, 'EUR')}</strong><span>Skupna ocenjena vrednost</span></div>
                <div><strong>{amount(totals.contracted, 'EUR')}</strong><span>Skupna pogodbena vrednost</span></div>
                <div><strong>{changePercent.format(totals.ratio - 1)}</strong><span>{differenceLabel(totals.difference, 'EUR')}</span></div>
            </div>
            <p className="past-awards-note">{summary.price_to_estimate_count} od {summary.awarded} prikazanih oddanih sklopov ima primerljivi vrednosti v EUR. {totals.below} pod oceno · {totals.equal} enako oceni · {totals.above} nad oceno.</p>
        </> : <p className="past-awards-note">Med prikazanimi oddajami ni sklopov s primerljivima vrednostma v EUR.</p>}
        <p className="past-awards-note">Vir primerjave je obvestilo o oddaji na PJN. Primerjava izključuje okvirne sporazume. Pri posamezni oddaji so prikazana tudi povezana plačila iz uvoženega izvoza ERAR, kadar so na voljo.</p>
    </div>;
}

function Award({ award }: { award: PastAward }) {
    const offers = award.lowest_offer && award.highest_offer && award.highest_offer !== award.lowest_offer
        ? `${amount(award.lowest_offer, award.currency)} – ${amount(award.highest_offer, award.currency)}` : null;
    const winners = new Set(award.winners.map(w => w.registration_number || w.name));
    const others = (award.participants || []).filter(p => !winners.has(p.registration_number || p.name));
    return <article className="past-award">
        <div className="past-award-head">
            <div>
                <p className="past-award-meta"><Building2 size={13}/>{award.buyer} · objavljeno {day(award.published_on)}{award.framework && ' · okvirni sporazum'}</p>
                <h3>{award.title}</h3>
                {award.lot_title && award.lot_title !== award.title && <p className="past-award-lot">Sklop: {award.lot_title}</p>}
            </div>
            {award.awarded && <span className="badge" title="Kako podoben je predmet tega naročila vašemu razpisu">Podobnost {Math.round(award.similarity * 100)} %</span>}
        </div>
        <Outcome award={award}/>
        <ul className="past-award-details">
            {award.erar_payments && <li className="wide"><span>Izplačano po uvoženih podatkih ERAR</span>
                <strong>{amount(award.erar_payments.amount, 'EUR')}</strong>
                <small>{award.erar_payments.count} transakcij · zadnje plačilo {day(award.erar_payments.latest_payment_on)} · izvoz {day(award.erar_payments.latest_export_on)}</small>
            </li>}
            <li><span>Prejetih ponudb</span>{award.tenders_received ?? 'ni podatka'}{award.tenders_received === 1 && <em className="past-award-single">samo ena ponudba</em>}</li>
            {offers && <li><span>Razpon dopustnih ponudb</span>{offers}</li>}
            {award.winners.flatMap(winner => {
                const url = erarRecipient(winner.registration_number);
                return url ? [<li className="wide" key={url}><a className="text-link" href={url} target="_blank" rel="noreferrer">ERAR · javna plačila podjetju {winner.name}<ExternalLink size={13}/></a></li>] : [];
            })}
            {others.length > 0 && <li className="wide"><span>Drugi ponudniki</span>{others.map((p, i) => <Fragment key={`${p.registration_number || p.name}-${i}`}>{i > 0 && ', '}<a href={p.source_url} target="_blank" rel="noreferrer" title="Vir zapisa o ponudniku">{p.name}</a> <small>({p.label.toLowerCase()})</small></Fragment>)}</li>}
            <li><a className="text-link" href={award.notice_url} target="_blank" rel="noreferrer">Obvestilo o oddaji {award.notice_number}<ExternalLink size={13}/></a></li>
        </ul>
    </article>;
}

export default function PastAwardsPanel({ tenderId }: { tenderId: string }) {
    // Historical award data rarely changes, so keep it cached for the session.
    const query = useQuery({ queryKey: queryKeys.similarAwards(tenderId), queryFn: ({ signal }) => api<SimilarAwards>(`/tenders/${tenderId}/similar-awards`, { signal }), staleTime: 30 * 60_000 });
    const data = query.data ?? null;
    const error = query.isFetching ? '' : query.error?.message ?? '';
    const s = data?.summary;
    return <section className="surface detail-section past-awards">
        <div className="section-heading"><div><h2><History size={19}/>Podobna pretekla naročila</h2><p className="section-help">Kdo je zmagal pri podobnih naročilih, koliko ponudb je prejel naročnik in po kakšni ceni.</p></div>{data && data.mode !== 'empty' && <span className="badge purple">{data.mode === 'ai' ? 'Podobnost presodil Gemini' : data.matching === 'semantic' ? 'Pomensko ujemanje' : 'Besedilno ujemanje'}</span>}</div>
        {error && <div role="alert" className="error-banner">{error}<button className="button small" onClick={() => query.refetch()}>Poskusi znova</button></div>}
        {!data && !error && <div className="past-awards-loading"><LoaderCircle className="spin"/>Iščemo podobne oddaje …</div>}
        {data && <>
            {data.warning && <div className="info-box amber"><p>{data.warning}</p></div>}
            {data.message && <div className="empty-state compact"><History size={26}/><p>{data.message}</p></div>}
            {s && s.count > 0 && <>
                <h3 className="past-awards-list-title">Povzetek {s.count} podobnih naročil</h3>
                <div className="past-awards-stats">
                    <div><strong>{s.awarded}</strong><span>oddanih naročil{s.not_awarded ? ` (${s.not_awarded} neoddano)` : ''}</span></div>
                    <div><strong>{s.median_tenders ?? '—'}</strong><span>mediana prejetih ponudb</span></div>
                    <div><strong>{percent(s.single_bid_share)}</strong><span>z eno samo ponudbo</span></div>
                    <div><strong>{s.median_price_to_estimate == null ? '—' : percent(s.median_price_to_estimate)}</strong><span>Mediana razmerja pogodbene do ocenjene vrednosti{s.price_to_estimate_count ? ` (n = ${s.price_to_estimate_count})` : ''}</span></div>
                    <div><strong>{s.median_offer_spread == null ? '—' : `+${percent(s.median_offer_spread)}`}</strong><span>najvišja nad najnižjo ponudbo{s.offer_spread_count ? ` (n = ${s.offer_spread_count})` : ''}</span></div>
                </div>
                <ValueOverview summary={s}/>
                {s.top_winners.length > 0 && <div className="past-awards-winners"><h3><Trophy size={15}/>Najpogostejši izbrani ponudniki</h3><ol>{s.top_winners.map(w => <li key={w.registration_number || w.name}><span>{w.name}</span><small>{w.registration_number ? `MŠ ${w.registration_number} · ` : ''}{w.wins}×</small></li>)}</ol></div>}
                <h3 className="past-awards-list-title">Posamezna naročila</h3>
                <div className="past-awards-list">{data.results.map(award => <Award key={award.id} award={award}/>)}</div>
            </>}
            <p className="past-awards-note">Podobnost ni ocena vaših možnosti za uspeh. Zmagovalci izhajajo iz obvestil o oddaji, drugi ponudniki iz dodatnih zapisnikov z navedenim virom. Mediane so izračunane iz zgoraj prikazanih oddaj.</p>
            <p className="past-awards-source">Vir: {data.dataset.attribution}, {data.dataset.label}, {data.dataset.license}. Zbirka zajema {data.dataset.lots} sklopov iz obvestil, objavljenih {day(data.dataset.coverage_from)} – {day(data.dataset.coverage_to)}, in ni popolna.</p>
        </>}
    </section>;
}
