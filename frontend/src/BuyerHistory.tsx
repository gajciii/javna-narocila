import { useEffect, useState, type FormEvent } from 'react';
import { BarChart3, ExternalLink, LoaderCircle } from 'lucide-react';
import { api } from './api';
import type { BuyerHistory } from './types';

const day = (value: string | null) => value ? new Date(value).toLocaleDateString('sl-SI') : 'Ni podatka';
const money = (value: number | null, currency = 'EUR') => value == null ? 'Ni podatka' : new Intl.NumberFormat('sl-SI', { style: 'currency', currency, maximumFractionDigits: 0 }).format(value);
const percent = (value: number | null) => value == null ? 'Ni podatka' : `${(value * 100).toLocaleString('sl-SI', { maximumFractionDigits: 1 })} %`;

export default function BuyerHistoryPanel({ tenderId }: { tenderId: string }) {
    const [data, setData] = useState<BuyerHistory | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [revision, setRevision] = useState(0);
    const [draft, setDraft] = useState({ from: '', to: '', cpv: '' });
    const [filters, setFilters] = useState({ from: '', to: '', cpv: '', buyer: '0', supplier: '', page: 1 });
    const [sort, setSort] = useState<'wins' | 'value'>('wins');
    const query = new URLSearchParams({ ...filters, page: String(filters.page) }).toString();
    useEffect(() => {
        let active = true;
        setLoading(true); setError('');
        api<BuyerHistory>(`/tenders/${tenderId}/buyer-history?${query}`)
            .then(value => { if (active) setData(value); })
            .catch(e => { if (active) setError((e as Error).message); })
            .finally(() => { if (active) setLoading(false); });
        return () => { active = false; };
    }, [tenderId, query, revision]);
    const apply = (e: FormEvent) => { e.preventDefault(); setFilters(old => ({ ...old, ...draft, supplier: '', page: 1 })); };
    const selectSupplier = (supplier: string) => setFilters(old => ({ ...old, supplier, page: 1 }));
    const ranked = [...(data?.suppliers || [])].sort((a, b) => sort === 'value' ? b.value_eur - a.value_eur || b.wins - a.wins : b.wins - a.wins || b.value_eur - a.value_eur);
    const selected = data?.suppliers.find(s => s.key === filters.supplier);
    const s = data?.summary;
    return <section className="surface detail-section buyer-history" aria-busy={loading}>
        <div className="section-heading"><div><h2><BarChart3 size={19}/>Zgodovina naročnika</h2><p className="section-help">Kdo prejema posle pri tem naročniku, kakšni so deleži in koliko konkurence je pri oddajah.</p></div></div>
        {data?.buyer && <p><strong>{data.buyer.name}</strong>{data.buyer.registration_number && ` · MŠ ${data.buyer.registration_number}`}</p>}
        <form className="buyer-history-filters" onSubmit={apply}>
            {(data?.buyers.length || 0) > 1 && <label className="field"><span>Naročnik</span><select value={filters.buyer} disabled={loading} onChange={e => setFilters(old => ({ ...old, buyer: e.target.value, supplier: '', page: 1 }))}>{data?.buyers.map((b, i) => <option key={i} value={i}>{b.name}</option>)}</select></label>}
            <label className="field"><span>Objave od</span><input type="date" value={draft.from} onChange={e => setDraft(old => ({ ...old, from: e.target.value }))}/></label>
            <label className="field"><span>Objave do</span><input type="date" min={draft.from || undefined} value={draft.to} onChange={e => setDraft(old => ({ ...old, to: e.target.value }))}/></label>
            <label className="field"><span>Področje CPV</span><input inputMode="numeric" pattern="[0-9]{2,8}" maxLength={8} placeholder="Npr. 72 za IT" value={draft.cpv} onChange={e => setDraft(old => ({ ...old, cpv: e.target.value }))}/></label>
            <button className="button small" disabled={loading}>Uporabi</button>
            <button className="text-link" type="button" disabled={loading} onClick={() => { setDraft({ from: '', to: '', cpv: '' }); setFilters(old => ({ ...old, from: '', to: '', cpv: '', supplier: '', page: 1 })); }}>Celotna zbirka</button>
        </form>
        {loading && <p role="status" className="past-awards-loading"><LoaderCircle className="spin"/>Pripravljamo zgodovino naročnika …</p>}
        {error && <div role="alert" className="error-banner">{error}<button className="button small" onClick={() => setRevision(r => r + 1)}>Poskusi znova</button></div>}
        {data && !loading && !error && <>
            {data.message && <p role="status" className="info-box">{data.message}</p>}
            {s && s.lots > 0 && <>
                <p className="section-help">Zbrana zgodovina: {day(s.coverage_from)} – {day(s.coverage_to)}. Štejemo oddane sklope, zato ima lahko en razpis več poslov.</p>
                <div className="past-awards-stats">
                    <div><strong>{s.awarded_lots}</strong><span>oddanih sklopov · {s.not_awarded_lots} brez potrjene izbire</span></div>
                    <div><strong>{s.supplier_count}</strong><span>različnih prejemnikov</span></div>
                    <div><strong>{percent(s.single_bid_share)}</strong><span>z eno ponudbo · {s.single_bid_lots}/{s.known_bid_lots} oddaj z znanim številom ponudb</span></div>
                    <div><strong>{s.value_lots ? money(s.total_value_eur) : 'Ni podatka'}</strong><span>znana vrednost samostojnih oddaj v EUR · {s.value_lots}/{s.awarded_lots} sklopov</span></div>
                </div>
                <div className="buyer-signals"><strong>Signali za podrobnejši pregled</strong>{data.signals.map(signal => <p key={signal.kind}>{signal.text}</p>)}<p>Koncentracija poslov in ena sama ponudba sami po sebi ne dokazujeta favoriziranja. Preverite primerljiva področja, pogoje razpisov, velikost vzorca in izvorna obvestila. Zbirka ni popolna.</p></div>
                <div className="buyer-ranking-head"><h3>Največji prejemniki poslov</h3><label className="field"><span>Razvrsti po</span><select value={sort} onChange={e => setSort(e.target.value as typeof sort)}><option value="wins">Številu oddanih sklopov</option><option value="value">Znani vrednosti v EUR</option></select></label></div>
                <div className="buyer-bars" aria-label={sort === 'wins' ? 'Delež oddanih sklopov največjih prejemnikov' : 'Znana vrednost oddaj največjim prejemnikom'}>{ranked.slice(0, 8).map(supplier => {
                    const ratio = sort === 'wins' ? supplier.share || 0 : s.total_value_eur ? supplier.value_eur / s.total_value_eur : 0;
                    return <button className="buyer-bar" key={supplier.key} aria-pressed={filters.supplier === supplier.key} onClick={() => selectSupplier(filters.supplier === supplier.key ? '' : supplier.key)}><span>{supplier.name}</span><span className="buyer-bar-track" aria-hidden="true"><i style={{ width: `${ratio * 100}%` }}/></span><strong>{sort === 'wins' ? `${supplier.wins} · ${percent(supplier.share)}` : supplier.value_count ? money(supplier.value_eur) : 'Ni podatka'}</strong></button>;
                })}</div>
                <p className="section-help">Klik na prejemnika prikaže njegove posle spodaj. Pri skupni ponudbi se sklop šteje vsakemu prejemniku; deleži se zato lahko seštejejo nad 100 %.</p>
                <div className="buyer-table-scroll"><table className="buyer-table"><caption>Prejemniki v izbranem obdobju in področju</caption><thead><tr><th>Prejemnik</th><th>Sklopi / delež</th><th>Skupne ponudbe</th><th>Znana vrednost EUR / delež</th></tr></thead><tbody>{ranked.map(supplier => <tr key={supplier.key}><td><button className="text-link" aria-pressed={filters.supplier === supplier.key} onClick={() => selectSupplier(filters.supplier === supplier.key ? '' : supplier.key)}>{supplier.name}</button><small>{supplier.registration_number ? `MŠ ${supplier.registration_number}` : 'MŠ ni podatka · združeno po imenu'}</small></td><td>{supplier.wins} / {percent(supplier.share)}</td><td>{supplier.joint_wins}</td><td>{supplier.value_count ? <>{money(supplier.value_eur)}<small>{percent(supplier.value_share)} znane vrednosti · {supplier.value_count} sklopov</small></> : 'Ni podatka'}</td></tr>)}</tbody></table></div>
                <details className="buyer-methodology"><summary>Kako so izračunani deleži in vrednosti?</summary><p>Signal koncentracije izpostavimo pri prejemniku z vsaj 50 % oddanih sklopov in vzorcu vsaj 10 oddaj. Signal ene ponudbe izpostavimo pri vsaj 50 % takih oddaj in vsaj 10 oddajah z znanim številom ponudb. To sta orientacijska praga za pregled.</p><p>Delež prejemnika je število oddanih sklopov, pri katerih je naveden kot izbrani ponudnik, deljeno z vsemi oddanimi sklopi v izboru. Število ponudb je znano pri {s.known_bid_lots}/{s.awarded_lots} oddajah. Manjkajoče število ponudb ne pomeni ene ponudbe.</p><p>Vrednosti vključujejo samo znane pogodbene vrednosti v EUR za enega prejemnika, brez okvirnih sporazumov. To niso podatki o dejanskih izplačilih. Iz vrednostnih deležev je izključenih {s.excluded_value_lots} sklopov; v izboru je {s.joint_lots} skupnih oddaj in {s.framework_lots} okvirnih sporazumov.</p><p>Starejši zapis izločimo, kadar novejša objava izrecno navede prejšnjo objavo in se ime sklopa ujema. Izločenih je {s.superseded_lots} povezanih starejših zapisov pred filtrom obdobja. Popravkov brez povezave ali s spremenjenim imenom sklopa ne moremo zanesljivo združiti; ti lahko povečajo število poslov. Zapisi brez datuma ({s.undated_lots} v izboru) so ob filtru obdobja izključeni.</p><p>Naročnike povezujemo po matični številki, kadar je na voljo; sicer po točnem imenu. Prejemnike brez matične številke združujemo samo po imenu.{data.buyer?.matched_by === 'name' && ' Ta naročnik je povezan samo po imenu.'}</p></details>
                <div className="buyer-ranking-head"><h3>{selected ? `Posli: ${selected.name}` : 'Zgodovina vseh oddaj'} ({data.history_count})</h3>{filters.supplier && <button className="button small" onClick={() => selectSupplier('')}>Vsi prejemniki</button>}</div>
                <div className="past-awards-list">{data.results.map(award => <article className="past-award" key={award.id}><h4>{award.title}</h4>{award.lot_title && <p>{award.lot_title}</p>}<p className="section-help">{day(award.published_on)} · {award.procedure || 'Postopek ni naveden'}{award.framework && ' · okvirni sporazum'}</p><p><strong>{award.awarded ? award.winners.map(w => w.name).join(' · ') : 'Brez potrjene izbire'}</strong></p><p>Pogodbena vrednost: {award.awarded_value != null && award.currency ? money(award.awarded_value, award.currency) : 'Ni podatka'} · Prejetih ponudb: {award.tenders_received ?? 'Ni podatka'}</p><a className="text-link" href={award.notice_url} target="_blank" rel="noreferrer">Izvorno obvestilo {award.notice_number}<ExternalLink size={13}/></a></article>)}</div>
                <div className="buyer-pagination"><button className="button small" disabled={data.page <= 1} onClick={() => setFilters(old => ({ ...old, page: old.page - 1 }))}>Prejšnja</button><span>Stran {data.page} / {Math.max(1, Math.ceil(data.history_count / data.page_size))}</span><button className="button small" disabled={data.page * data.page_size >= data.history_count} onClick={() => setFilters(old => ({ ...old, page: old.page + 1 }))}>Naslednja</button></div>
            </>}
            <p className="past-awards-source">Vir: {data.dataset.attribution} · {data.dataset.license}. Zbirka: {data.dataset.lots} sklopov iz objav {day(data.dataset.coverage_from)} – {day(data.dataset.coverage_to)}. Podatki se dopolnjujejo z rednim zajemom preteklih oddaj.</p>
        </>}
    </section>;
}
