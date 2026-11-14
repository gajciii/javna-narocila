import { useState, type FormEvent } from 'react';
import { FileSignature, LoaderCircle, Search } from 'lucide-react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from './api';
import { queryKeys } from './queryClient';
import { ContractCard, contractDay } from './Incumbents';
import type { ContractRegister } from './types';

export function ContractsNavigation({ expected = false }: { expected?: boolean }) {
    return <nav className="contracts-navigation" aria-label="Pregled pogodb">
        <a href="#/pogodbe" aria-current={!expected ? 'page' : undefined}>Register pogodb</a>
        <a href="#/pricakovani" aria-current={expected ? 'page' : undefined}>Pričakovani razpisi</a>
    </nav>;
}

const initial = { q: '', cpv: '', year: '', status: 'all', sort: 'newest' };
const number = (value?: number) => value == null ? '—' : new Intl.NumberFormat('sl-SI').format(value);
const statusLabels = { active: 'Rok še ni potekel', ended: 'Pogodba je potekla', unknown: 'Rok ni objavljen' };

export default function ContractsPage() {
    const [draft, setDraft] = useState(initial);
    const [filters, setFilters] = useState({ ...initial, page: 1 });
    const query = new URLSearchParams({ ...filters, page: String(filters.page) }).toString();
    const result = useQuery({ queryKey: queryKeys.contracts(query),
        queryFn: ({ signal }) => api<ContractRegister>(`/contracts?${query}`, { signal }), placeholderData: keepPreviousData });
    const data = result.data;
    const busy = result.isFetching;
    const submit = (event: FormEvent) => { event.preventDefault(); setFilters({ ...draft, page: 1 }); };
    const reset = () => { setDraft(initial); setFilters({ ...initial, page: 1 }); };
    const hasFilters = Boolean(filters.q || filters.cpv || filters.year || filters.status !== 'all' || filters.sort !== 'newest');
    return <>
        <section className="page-intro simple-intro" aria-labelledby="contracts-title">
            <div className="page-heading"><div><h1 id="contracts-title">Pogodbe</h1>
                <p>Kdo izvaja javna naročila, kakšna je podpisana vrednost in kdaj pogodbe potečejo. Podatki iz objavljenih pogodb in aneksov.</p></div></div>
        </section>
        <ContractsNavigation/>
        <section className="surface detail-section contract-register" aria-busy={busy}>
            {data && <dl className="contract-register-metrics">
                <div><dt>Podpisane pogodbe</dt><dd>{number(data.dataset.contracts)}</dd></div>
                <div><dt>Objavljeni aneksi</dt><dd>{number(data.dataset.addenda)}</dd></div>
                <div><dt>Iztek v naslednjih 12 mesecih</dt><dd>{number(data.dataset.expiring_12m)}</dd></div>
            </dl>}
            <form className="contract-register-filters" onSubmit={submit}>
                <label className="field contract-register-search"><span>Iskanje</span><input type="search" maxLength={200}
                    placeholder="Predmet, naročnik, izvajalec ali številka objave" value={draft.q}
                    onChange={e => setDraft(old => ({ ...old, q: e.target.value }))}/></label>
                <label className="field"><span>Področje CPV</span><input inputMode="numeric" pattern="[0-9]{2,8}" maxLength={8}
                    placeholder="Npr. 4533" value={draft.cpv} onChange={e => setDraft(old => ({ ...old, cpv: e.target.value }))}/></label>
                <label className="field"><span>Leto objave</span><input inputMode="numeric" pattern="[0-9]{4}" maxLength={4}
                    placeholder="Vsa leta" value={draft.year} onChange={e => setDraft(old => ({ ...old, year: e.target.value }))}/></label>
                <label className="field"><span>Veljavnost</span><select value={draft.status} onChange={e => setDraft(old => ({ ...old, status: e.target.value }))}>
                    <option value="all">Vse pogodbe</option><option value="active">Rok še ni potekel</option>
                    <option value="expiring">Poteče v 12 mesecih</option><option value="ended">Potekle pogodbe</option>
                    <option value="unknown">Brez objavljenega roka</option></select></label>
                <label className="field"><span>Razvrsti po</span><select value={draft.sort} onChange={e => setDraft(old => ({ ...old, sort: e.target.value }))}>
                    <option value="newest">Najnovejši objavi</option><option value="ending">Najbližjem izteku</option>
                    <option value="value">Najvišji vrednosti</option></select></label>
                <div className="contract-filter-actions"><button className="button primary" disabled={busy}><Search size={16}/>Poišči</button>
                    {hasFilters && <button className="button" type="button" onClick={reset} disabled={busy}>Počisti filtre</button>}</div>
            </form>
            {result.isLoading && <p role="status" className="past-awards-loading"><LoaderCircle className="spin"/>Nalagamo pogodbe …</p>}
            {result.error && <div role="alert" className="error-banner">{result.error.message}<button className="button small" onClick={() => void result.refetch()}>Poskusi znova</button></div>}
            {data && <>
                <div className="contract-result-heading"><h2><FileSignature size={19}/>Najdene pogodbe <span>{number(data.count)}</span></h2>
                    {busy && <span role="status"><LoaderCircle size={15} className="spin"/>Posodabljamo izbor …</span>}</div>
                {!data.count && <div className="info-box" role="status">Za izbrane filtre ni pogodb. Poskusite s širšim izrazom ali odstranite filter.</div>}
                <div className="past-awards-list">{data.results.map(contract => <ContractCard key={contract.id} contract={contract}>
                    <p className="section-help">{statusLabels[contract.status]}</p>
                </ContractCard>)}</div>
                {data.count > data.page_size && <div className="buyer-pagination">
                    <button className="button small" disabled={busy || data.page <= 1} onClick={() => setFilters(old => ({ ...old, page: old.page - 1 }))}>Prejšnja</button>
                    <span>Stran {data.page} / {number(Math.ceil(data.count / data.page_size))}</span>
                    <button className="button small" disabled={busy || data.page * data.page_size >= data.count} onClick={() => setFilters(old => ({ ...old, page: old.page + 1 }))}>Naslednja</button>
                </div>}
                <p className="past-awards-source">Vir: {data.dataset.attribution}. Objave {contractDay(data.dataset.coverage_from)} – {contractDay(data.dataset.coverage_to)}. Aneksi so upoštevani pri roku veljavnosti. Podpisana vrednost ni podatek o dejanskih izplačilih.</p>
            </>}
        </section>
    </>;
}
