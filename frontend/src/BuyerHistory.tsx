import { useState, type FormEvent, type ReactNode } from 'react';
import { BarChart3, Building2, ChevronDown, LoaderCircle, X } from 'lucide-react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from './api';
import { queryKeys } from './queryClient';
import { HistoricalAward } from './PastAwards';
import type { BuyerHistory } from './types';
import './buyer-history.css';

const day = (value: string | null) => value ? new Date(value).toLocaleDateString('sl-SI') : 'Ni podatka';
const money = (value: number | null) => value == null ? 'Ni podatka' : new Intl.NumberFormat('sl-SI', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(value);
const percent = (value: number | null) => value == null ? 'Ni podatka' : `${(value * 100).toLocaleString('sl-SI', { maximumFractionDigits: 1 })} %`;

export default function BuyerHistoryPanel({ tenderId, children }: { tenderId: string; children?: ReactNode }) {
    const [draft, setDraft] = useState({ from: '', to: '', cpv: '' });
    const [filters, setFilters] = useState({ from: '', to: '', cpv: '', buyer: '0', supplier: '', page: 1 });
    const [sort, setSort] = useState<'wins' | 'value'>('wins');
    const query = new URLSearchParams({ ...filters, page: String(filters.page) }).toString();
    const history = useQuery({ queryKey: queryKeys.buyerHistory(tenderId, query), queryFn: ({ signal }) => api<BuyerHistory>(`/tenders/${tenderId}/buyer-history?${query}`, { signal }), staleTime: 30 * 60_000, placeholderData: keepPreviousData });
    const data = history.data ?? null;
    const loading = history.isFetching;
    const error = history.isFetching ? '' : history.error?.message ?? '';
    const apply = (event: FormEvent) => { event.preventDefault(); setFilters(old => ({ ...old, ...draft, supplier: '', page: 1 })); };
    const reset = () => { setDraft({ from: '', to: '', cpv: '' }); setFilters(old => ({ ...old, from: '', to: '', cpv: '', supplier: '', page: 1 })); };
    const selectSupplier = (supplier: string) => setFilters(old => ({ ...old, supplier, page: 1 }));
    const ranked = [...(data?.suppliers || [])].sort((a, b) => sort === 'value' ? b.value_eur - a.value_eur || b.wins - a.wins : b.wins - a.wins || b.value_eur - a.value_eur);
    const selected = data?.suppliers.find(supplier => supplier.key === filters.supplier);
    const s = data?.summary;
    const hasFilters = Boolean(filters.from || filters.to || filters.cpv);
    return <section className="surface detail-section buyer-history" aria-busy={loading}>
        <div className="section-heading"><div><h2><BarChart3 size={20}/>Zgodovina naročnika</h2><p className="section-help">Komu je naročnik oddal posle in za kakšno vrednost? Izberite ponudnika in preglejte njegove pretekle posle.</p></div></div>
        {data?.buyer && <div className="buyer-identity"><Building2 size={20}/><div><strong>{data.buyer.name}</strong>{data.buyer.registration_number && <span>MŠ {data.buyer.registration_number}</span>}</div></div>}
        {(data?.buyers.length || 0) > 1 && <label className="field buyer-picker"><span>Izberite naročnika</span><select value={filters.buyer} disabled={loading} onChange={event => setFilters(old => ({ ...old, buyer: event.target.value, supplier: '', page: 1 }))}>{data?.buyers.map((buyer, index) => <option key={index} value={index}>{buyer.name}</option>)}</select></label>}
        <details className="buyer-filter-disclosure"><summary>Filtriraj obdobje in področje{hasFilters && <span className="buyer-filter-active">Filtri vključeni</span>}<ChevronDown size={17}/></summary>
            <form className="buyer-history-filters" onSubmit={apply}>
                <label className="field"><span>Objave od</span><input type="date" value={draft.from} onChange={event => setDraft(old => ({ ...old, from: event.target.value }))}/></label>
                <label className="field"><span>Objave do</span><input type="date" min={draft.from || undefined} value={draft.to} onChange={event => setDraft(old => ({ ...old, to: event.target.value }))}/></label>
                <label className="field"><span>Področje CPV</span><input inputMode="numeric" pattern="[0-9]{2,8}" maxLength={8} placeholder="Npr. 72 za IT" value={draft.cpv} onChange={event => setDraft(old => ({ ...old, cpv: event.target.value }))}/></label>
                <button className="button small" disabled={loading}>Uporabi filtre</button><button className="text-link" type="button" disabled={loading} onClick={reset}>Ponastavi</button>
            </form>
        </details>
        {hasFilters && <div className="buyer-applied-filters"><span>{filters.from && `Od ${day(filters.from)}`}{filters.from && filters.to && ' · '}{filters.to && `Do ${day(filters.to)}`}{filters.cpv && `${filters.from || filters.to ? ' · ' : ''}CPV ${filters.cpv}`}</span><button className="text-link" disabled={loading} onClick={reset}>Počisti filtre<X size={14}/></button></div>}
        {loading && <p role="status" className="past-awards-loading"><LoaderCircle className="spin"/>Pripravljamo zgodovino naročnika …</p>}
        {error && <div role="alert" className="error-banner">{error}<button className="button small" onClick={() => history.refetch()}>Poskusi znova</button></div>}
        {data && !loading && !error && <>
            {data.message && <p role="status" className="info-box">{data.message}</p>}
            {s && s.lots > 0 && <>
                <div className="buyer-overview" aria-label="Povzetek zgodovine naročnika">
                    <div><strong>{s.awarded_lots}</strong><span>oddanih poslov</span></div>
                    <div><strong>{s.supplier_count}</strong><span>različnih izbranih ponudnikov</span></div>
                    <div><strong>{s.value_lots ? money(s.total_value_eur) : 'Ni podatka'}</strong><span>znana pogodbena vrednost<small>Za {s.value_lots} od {s.awarded_lots} poslov; brez skupnih ponudb in okvirnih sporazumov.</small></span></div>
                </div>
                <p className="buyer-coverage">Obdobje: {day(s.coverage_from)} – {day(s.coverage_to)}. Posel pomeni posamezen oddan sklop naročila.</p>
                {ranked.length > 0 && <>
                    <div className="buyer-ranking-head"><div><h3>{sort === 'wins' ? 'Najpogosteje izbrani ponudniki' : 'Kdo je prejel največjo znano vrednost poslov?'}</h3><p>Klik na ponudnika prikaže njegove posle spodaj.</p></div><label className="similar-awards-sort"><span>Razvrsti</span><select value={sort} onChange={event => setSort(event.target.value as typeof sort)}><option value="wins">Po številu poslov</option><option value="value">Po znani vrednosti</option></select></label></div>
                    <div className="buyer-supplier-list">{ranked.slice(0, 5).map(supplier => {
                        const share = sort === 'wins' ? supplier.share || 0 : s.total_value_eur ? supplier.value_eur / s.total_value_eur : 0;
                        return <button className="buyer-supplier" key={supplier.key} aria-pressed={filters.supplier === supplier.key} onClick={() => selectSupplier(filters.supplier === supplier.key ? '' : supplier.key)}>
                            <span className="buyer-supplier-name"><strong>{supplier.name}</strong><span className="buyer-supplier-track" aria-hidden="true"><i style={{ width: `${Math.min(100, Math.max(0, share * 100))}%` }}/></span></span>
                            <span className="buyer-supplier-count"><strong>{supplier.wins}</strong><span>poslov · {percent(supplier.share)}</span></span>
                            <span className="buyer-supplier-value"><strong>{supplier.value_count ? money(supplier.value_eur) : 'Ni podatka'}</strong><span>znana vrednost</span></span>
                        </button>;
                    })}</div>
                    <details className="similar-awards-disclosure buyer-all-suppliers"><summary>Vsi ponudniki in podrobnosti ({ranked.length})<ChevronDown size={18}/></summary><div className="buyer-table-scroll"><table className="buyer-table"><caption>Izbrani ponudniki v izbranem obdobju in področju</caption><thead><tr><th>Ponudnik</th><th>Posli / delež</th><th>Skupne ponudbe</th><th>Znana vrednost EUR / delež</th></tr></thead><tbody>{ranked.map(supplier => <tr key={supplier.key}><td><button className="text-link" aria-pressed={filters.supplier === supplier.key} onClick={() => selectSupplier(filters.supplier === supplier.key ? '' : supplier.key)}>{supplier.name}</button><small>{supplier.registration_number ? `MŠ ${supplier.registration_number}` : 'MŠ ni podatka · združeno po imenu'}</small></td><td>{supplier.wins} / {percent(supplier.share)}</td><td>{supplier.joint_wins}</td><td>{supplier.value_count ? <>{money(supplier.value_eur)}<small>{percent(supplier.value_share)} znane vrednosti · {supplier.value_count} poslov</small></> : 'Ni podatka'}</td></tr>)}</tbody></table></div></details>
                </>}
                <div className="buyer-history-list-heading"><div><h3>Pretekli posli{selected ? ' izbranega ponudnika' : ''} <span>({data.history_count})</span></h3>{selected && <p>{selected.name}</p>}</div>{filters.supplier && <button className="button small" onClick={() => selectSupplier('')}>Prikaži vse posle<X size={14}/></button>}</div>
                <p className="buyer-list-help">Klik na posel odpre uradno objavo v novem zavihku.</p>
                {data.results.length ? <div className="similar-tenders-list">{data.results.map(award => <HistoricalAward key={award.id} award={award}/>)}</div> : <p className="empty-state compact">Za ta izbor ni poslov. Izberite drugega ponudnika ali počistite filtre.</p>}
                {data.history_count > data.page_size && <div className="buyer-pagination"><button className="button small" disabled={data.page <= 1} onClick={() => setFilters(old => ({ ...old, page: old.page - 1 }))}>Prejšnja</button><span>Stran {data.page} / {Math.max(1, Math.ceil(data.history_count / data.page_size))}</span><button className="button small" disabled={data.page * data.page_size >= data.history_count} onClick={() => setFilters(old => ({ ...old, page: old.page + 1 }))}>Naslednja</button></div>}
                <details className="similar-awards-disclosure buyer-method"><summary>Viri in način izračuna<ChevronDown size={18}/></summary><div className="similar-awards-method">
                    <div><h4>Konkurenca pri oddajah</h4><p>{s.single_bid_lots} od {s.known_bid_lots} oddaj z znanim številom ponudb je prejelo eno ponudbo ({percent(s.single_bid_share)}). Manjkajoče število ponudb ne pomeni ene ponudbe.</p></div>
                    {data.signals.length > 0 && <div><h4>Podatki za podrobnejši pregled</h4>{data.signals.map(signal => <p key={signal.kind}>{signal.text}</p>)}<p>Koncentracija poslov in ena ponudba sami po sebi ne dokazujeta favoriziranja.</p></div>}
                    <p>Delež ponudnika je število njegovih oddanih sklopov, deljeno z vsemi oddanimi sklopi v izboru. Pri skupni ponudbi se posel šteje vsakemu izbranemu ponudniku, zato se lahko deleži seštejejo nad 100 %.</p>
                    <p>Vrednosti vključujejo samo znane pogodbene vrednosti v EUR za enega prejemnika, brez okvirnih sporazumov. To niso dejanska izplačila. Iz vrednosti je izključenih {s.excluded_value_lots} poslov; v izboru je {s.joint_lots} skupnih oddaj in {s.framework_lots} okvirnih sporazumov.</p>
                    <p>Starejši zapis izločimo, kadar novejša objava izrecno navede prejšnjo objavo in se ime sklopa ujema. Izločenih je {s.superseded_lots} povezanih starejših zapisov pred filtrom obdobja. Drugih popravkov ne moremo zanesljivo združiti. Zapisi brez datuma ({s.undated_lots}) so ob filtru obdobja izključeni.</p>
                    <p>Naročnike povezujemo po matični številki, sicer po točnem imenu. Ponudnike brez matične številke združujemo po imenu.{data.buyer?.matched_by === 'name' && ' Ta naročnik je povezan samo po imenu.'} Signala koncentracije in ene ponudbe izpostavimo pri najmanj 50-odstotnem deležu in vzorcu vsaj 10 ustreznih oddaj.</p>
                </div></details>
            </>}
            {!s?.lots && !data.message && <p className="empty-state compact">Za izbrano obdobje in področje ni shranjenih poslov.</p>}
            <p className="buyer-data-source">Vir: {data.dataset.attribution} · {data.dataset.license}. Zbirka zajema {data.dataset.lots} sklopov, objavljenih {day(data.dataset.coverage_from)} – {day(data.dataset.coverage_to)}, in se dopolnjuje z rednim zajemom.</p>
        </>}
        {children && <details className="similar-awards-disclosure buyer-contracts"><summary>Pogodbe in trenutni izvajalci<ChevronDown size={18}/></summary><p className="buyer-list-help">Podpisane pogodbe in aneksi za soroden predmet pri tem naročniku.</p>{children}</details>}
    </section>;
}
