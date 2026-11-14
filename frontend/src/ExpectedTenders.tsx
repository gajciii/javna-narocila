import { useState, type FormEvent } from 'react';
import { CalendarClock, LoaderCircle } from 'lucide-react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from './api';
import { queryKeys } from './queryClient';
import { ContractCard, contractDay } from './Incumbents';
import type { ExpectedTenders } from './types';
import { ContractsNavigation } from './Contracts';

export default function ExpectedTendersPage({ profileVersion }: { profileVersion: string }) {
    const [draft, setDraft] = useState({ months: '12', cpv: '', terms: '' });
    const [filters, setFilters] = useState({ ...draft, page: 1 });
    const query = new URLSearchParams({ ...filters, page: String(filters.page) }).toString();
    const result = useQuery({ queryKey: [...queryKeys.expectedTenders(query), profileVersion], queryFn: ({ signal }) => api<ExpectedTenders>(`/expected-tenders?${query}`, { signal }), placeholderData: keepPreviousData });
    const data = result.data;
    const loading = result.isFetching;
    const apply = (e: FormEvent) => { e.preventDefault(); setFilters({ ...draft, page: 1 }); };
    return <>
        <section className="page-intro simple-intro" aria-labelledby="expected-title"><div className="page-heading"><div><h1 id="expected-title">Pričakovani razpisi</h1><p>Podpisane pogodbe, ki kmalu potečejo in se ujemajo z vašim profilom. Naročnik bo storitev ali blago verjetno potreboval znova, zato se lahko na razpis pripravite pravočasno.</p></div></div></section>
        <ContractsNavigation expected/>
        <section className="surface detail-section expected-tenders" aria-busy={loading}>
            <form className="buyer-history-filters" onSubmit={apply}>
                <label className="field"><span>Pogodba poteče v</span><select value={draft.months} onChange={e => setDraft(old => ({ ...old, months: e.target.value }))}>{['3', '6', '12', '24'].map(m => <option key={m} value={m}>{m} mesecih</option>)}</select></label>
                <label className="field"><span>Področje CPV</span><input inputMode="numeric" pattern="[0-9]{2,8}" maxLength={8} placeholder="Npr. 4533" value={draft.cpv} onChange={e => setDraft(old => ({ ...old, cpv: e.target.value }))}/></label>
                <label className="field"><span>Dodatni izrazi</span><input maxLength={500} placeholder="Ločite z vejico" value={draft.terms} onChange={e => setDraft(old => ({ ...old, terms: e.target.value }))}/></label>
                <button className="button small" disabled={loading}>Uporabi</button>
            </form>
            {data && data.terms.length > 0 && <p className="section-help">Iščemo po izrazih iz profila: {data.terms.join(', ')}. <a href="#/profil">Uredi profil</a></p>}
            {loading && !data && <p role="status" className="past-awards-loading"><LoaderCircle className="spin"/>Iščemo pogodbe …</p>}
            {result.error && <div role="alert" className="error-banner">{result.error.message}<button className="button small" onClick={() => result.refetch()}>Poskusi znova</button></div>}
            {data && <>
                {data.message && <p role="status" className="info-box">{data.message}{data.mode === 'profile_missing' && <> <a href="#/profil">Odpri profil</a></>}</p>}
                {data.count > 0 && <h3 className="expected-count"><CalendarClock size={17}/>{data.count} {data.count === 1 ? 'pogodba poteče' : 'pogodb poteče'} v {data.months} mesecih</h3>}
                <div className="past-awards-list">{data.results.map(contract => <ContractCard key={contract.id} contract={contract}>
                    {contract.matched_terms.length > 0 && <p className="section-help">Ujemanje s profilom: {contract.matched_terms.join(', ')}</p>}
                    {contract.newer_contract && <p className="info-box amber">Naročnik je kasneje že sklenil sorodno pogodbo ({contract.newer_contract.title || 'brez naslova'}, {contractDay(contract.newer_contract.concluded_on)}{contract.newer_contract.contractors.length ? `, ${contract.newer_contract.contractors.join(', ')}` : ''}). Potreba je morda že pokrita.</p>}
                </ContractCard>)}</div>
                {data.count > data.page_size && <div className="buyer-pagination"><button className="button small" disabled={data.page <= 1} onClick={() => setFilters(old => ({ ...old, page: old.page - 1 }))}>Prejšnja</button><span>Stran {data.page} / {Math.ceil(data.count / data.page_size)}</span><button className="button small" disabled={data.page * data.page_size >= data.count} onClick={() => setFilters(old => ({ ...old, page: old.page + 1 }))}>Naslednja</button></div>}
                <details className="buyer-methodology"><summary>Kako nastane seznam?</summary>
                    <p>Prikazujemo pogodbe, katerih rok veljavnosti poteče v izbranem obdobju. Rok je najkasnejši rok iz pogodbe in njenih aneksov, saj aneks pogodbo pogosto podaljša. Pogodbe, sklenjene do izpolnitve obveznosti, nimajo roka in niso vključene.</p>
                    <p>Pogodba se ujema, če naslov pogodbe, naslov naročila ali opis CPV vsebuje vse besede izraza iz vašega profila (ključne besede in strokovna področja). Iztek pogodbe ne pomeni, da bo razpis zagotovo objavljen: naročnik lahko pogodbo podaljša, naročilo združi z drugim ali ga ne ponovi.</p>
                </details>
                <p className="past-awards-source">Vir: {data.dataset.attribution}. Zbranih pogodb: {data.dataset.contracts}, od tega {data.dataset.with_end} z rokom veljavnosti; objave {contractDay(data.dataset.coverage_from)} – {contractDay(data.dataset.coverage_to)}. Register se dopolnjuje z dnevnim zajemom.</p>
            </>}
        </section>
    </>;
}
