import { useEffect, useState } from 'react';
import { ExternalLink, History, LoaderCircle, Trophy } from 'lucide-react';
import { api } from './api';
import type { PastAward, SimilarAwards } from './types';

const day = (value: string | null) => value ? new Date(value).toLocaleDateString('sl-SI', { day: 'numeric', month: 'numeric', year: 'numeric' }) : 'Ni podatka';
const amount = (value: number | null, currency: string | null) => value == null ? 'Ni podatka' : new Intl.NumberFormat('sl-SI', { style: 'currency', currency: currency || 'EUR', maximumFractionDigits: 0 }).format(value);
const percent = (value: number | null) => value == null ? '—' : `${Math.round(value * 100)} %`;
const winnerLabel = (award: PastAward) => !award.awarded ? 'Ni oddano' : award.winners.map(w => w.name).join(' · ');

function Award({ award }: { award: PastAward }) {
    const spread = award.lowest_offer && award.highest_offer && award.highest_offer !== award.lowest_offer ? `${amount(award.lowest_offer, award.currency)} – ${amount(award.highest_offer, award.currency)}` : amount(award.lowest_offer, award.currency);
    return <article className="past-award">
        <div className="past-award-head"><div><h3>{award.title}</h3>{award.lot_title && <p className="past-award-lot">{award.lot_title}</p>}<p className="past-award-meta">{award.buyer} · {day(award.published_on)}{award.framework && ' · okvirni sporazum'}</p></div><span className={`badge ${award.awarded ? '' : 'amber'}`}>{award.awarded ? `Podobnost ${Math.round(award.similarity * 100)} %` : 'Ni oddano'}</span></div>
        <dl className="past-award-facts"><div><dt>Zmagovalec</dt><dd>{winnerLabel(award)}</dd></div><div><dt>Prejetih ponudb</dt><dd>{award.tenders_received ?? 'Ni podatka'}</dd></div><div><dt>Pogodbena vrednost</dt><dd>{amount(award.awarded_value, award.currency)}</dd></div><div><dt>Ocenjena vrednost</dt><dd>{amount(award.estimated_value, award.currency)}</dd></div><div><dt>Dopustne ponudbe</dt><dd>{spread}</dd></div></dl>
        <a className="text-link" href={award.notice_url} target="_blank" rel="noreferrer">Obvestilo o oddaji {award.notice_number}<ExternalLink size={13}/></a>
        <div className="past-award-participants"><h4>Znani ponudniki in izid</h4>
            <ul>{(award.participants || []).map((p, i) => <li key={`${p.registration_number || p.name}-${i}`}>
                <strong>{p.name}</strong> — {p.label}{p.registration_number && ` · MŠ ${p.registration_number}`} ·{' '}
                <a href={p.source_url} target="_blank" rel="noreferrer">{p.provenance === 'award_notice' ? 'Obvestilo o oddaji' : 'Vir uvoženega zapisnika'}</a>
            </li>)}</ul>
            <p className="section-help">{award.participant_coverage === 'winners_only'
                ? 'Imena drugih prijavljenih ponudnikov za ta sklop še niso pridobljena.'
                : 'Prikazani so ponudniki iz razpoložljivih zapisnikov. Seznam ni nujno popoln; nepotrjen izid ne pomeni poraza.'}</p>
        </div>
    </article>;
}

export default function PastAwardsPanel({ tenderId }: { tenderId: string }) {
    const [data, setData] = useState<SimilarAwards | null>(null);
    const [error, setError] = useState('');
    const [revision, setRevision] = useState(0);
    useEffect(() => { let active = true; setData(null); setError(''); api<SimilarAwards>(`/tenders/${tenderId}/similar-awards`).then(value => { if (active) setData(value); }).catch(e => { if (active) setError((e as Error).message); }); return () => { active = false; }; }, [tenderId, revision]);
    const s = data?.summary;
    return <section className="surface detail-section past-awards">
        <div className="section-heading"><div><h2><History size={19}/>Podobna pretekla naročila</h2><p className="section-help">Kdo je zmagal pri podobnih naročilih, koliko ponudb je prejel naročnik in po kakšni ceni.</p></div>{data && data.mode !== 'empty' && <span className="badge purple">{data.mode === 'ai' ? 'Podobnost presodil Gemini' : 'Besedilno ujemanje'}</span>}</div>
        {error && <div role="alert" className="error-banner">{error}<button className="button small" onClick={() => setRevision(r => r + 1)}>Poskusi znova</button></div>}
        {!data && !error && <div className="past-awards-loading"><LoaderCircle className="spin"/>Iščemo podobne oddaje …</div>}
        {data && <>
            {data.warning && <div className="info-box amber"><p>{data.warning}</p></div>}
            {data.message && <div className="empty-state compact"><History size={26}/><p>{data.message}</p></div>}
            {s && s.count > 0 && <>
                <div className="past-awards-stats">
                    <div><strong>{s.count}</strong><span>podobnih oddaj{s.not_awarded ? `, ${s.not_awarded} brez izbire` : ''}</span></div>
                    <div><strong>{s.median_tenders ?? '—'}</strong><span>mediana prejetih ponudb</span></div>
                    <div><strong>{percent(s.single_bid_share)}</strong><span>z eno samo ponudbo</span></div>
                    <div><strong>{s.median_price_to_estimate == null ? '—' : percent(s.median_price_to_estimate)}</strong><span>pogodbena / ocenjena vrednost{s.price_to_estimate_count ? ` (n = ${s.price_to_estimate_count})` : ''}</span></div>
                    <div><strong>{s.median_offer_spread == null ? '—' : `+${percent(s.median_offer_spread)}`}</strong><span>najvišja nad najnižjo ponudbo{s.offer_spread_count ? ` (n = ${s.offer_spread_count})` : ''}</span></div>
                </div>
                {s.top_winners.length > 0 && <div className="past-awards-winners"><h3><Trophy size={15}/>Najpogostejši izbrani ponudniki</h3><ol>{s.top_winners.map(w => <li key={w.registration_number || w.name}><span>{w.name}</span><small>{w.registration_number ? `MŠ ${w.registration_number} · ` : ''}{w.wins}×</small></li>)}</ol></div>}
                <div className="past-awards-list">{data.results.map(award => <Award key={award.id} award={award}/>)}</div>
            </>}
            <p className="past-awards-note">Podobnost ni ocena vaših možnosti za uspeh. Zmagovalci izhajajo iz obvestil o oddaji, drugi ponudniki iz dodatnih zapisnikov z navedenim virom. Mediane so izračunane iz zgoraj prikazanih oddaj.</p>
            <p className="past-awards-source">Vir: {data.dataset.attribution}, {data.dataset.label}, {data.dataset.license}. Zbirka zajema {data.dataset.lots} sklopov iz obvestil, objavljenih {day(data.dataset.coverage_from)} – {day(data.dataset.coverage_to)}, in ni popolna.</p>
        </>}
    </section>;
}
