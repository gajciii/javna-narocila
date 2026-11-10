import { useRef, useState } from 'react';
import { Building2, Search, ArrowRight, ExternalLink, LoaderCircle, AlertCircle } from 'lucide-react';
import { api } from './api';
import type { CompanySearchResult } from './types';

const date = (value: string | null) => value ? new Date(value).toLocaleDateString('sl-SI', { timeZone: 'Europe/Ljubljana' }) : 'ni podatka';

export default function CompanySearch({ onSelect, selecting }: { onSelect: (number: string) => void; selecting: boolean }) {
    const [query, setQuery] = useState('');
    const [result, setResult] = useState<CompanySearchResult | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const requestId = useRef(0);
    const search = async () => {
        if (busy || query.trim().length < 2) return;
        const id = ++requestId.current;
        setBusy(true); setResult(null); setError('');
        try {
            const response = await api<CompanySearchResult>(`/companies/search?q=${encodeURIComponent(query.trim())}`);
            if (id === requestId.current) setResult(response);
        } catch (e) { if (id === requestId.current) setError((e as Error).message); }
        finally { if (id === requestId.current) setBusy(false); }
    };
    return <div className="company-lookup">
        <div className="company-lookup-heading"><Building2 size={21}/><div><strong>Poiščite podjetje v AJPES</strong><p>Predizpolnite naziv, matično številko in naslov iz odprte zbirke PRS na OPSI.</p></div></div>
        <label className="field"><span>Ime podjetja ali matična številka</span><div className="company-lookup-input"><input value={query} maxLength={160} placeholder="Vnesite ime ali 7- oziroma 10-mestno matično številko" onChange={e => { setQuery(e.target.value); setResult(null); setError(''); requestId.current++; setBusy(false); }} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); search(); } }}/><button className="button primary" type="button" onClick={search} disabled={busy || selecting || query.trim().length < 2}>{busy ? <LoaderCircle size={17} className="spin"/> : <Search size={17}/>}Išči</button></div></label>
        {error && <div className="info-box company-lookup-error" role="alert"><AlertCircle size={17}/><p>{error} Podatke lahko vnesete ročno.</p></div>}
        {result && <div className="company-lookup-results" aria-live="polite">
            <div className="company-result-count">{result.total ? `Zadetkov: ${result.total}${result.total > result.results.length ? ` · prikazanih prvih ${result.results.length}` : ''}` : 'Ni zadetkov. Poskusite s celo besedo v imenu ali matično številko.'}</div>
            {result.warning && <p className="company-lookup-warning">{result.warning}</p>}
            {result.results.map(company => <button key={company.registration_number} className="company-result" type="button" disabled={selecting} onClick={() => onSelect(company.registration_number)} aria-label={`Izberi ${company.name}, ${company.registration_number}`}><span><strong>{company.name}</strong><span>{company.address || 'Naslov ni naveden'}</span><small>Matična: {company.registration_number} · {company.legal_form || 'Oblika ni navedena'}</small></span><ArrowRight size={18}/></button>)}
            <p className="company-source-note">{result.mode === 'live' ? 'Pridobljeno iz OPSI' : 'Shranjeni podatki OPSI'} · Prevzem: {date(result.source.retrieved_at)} · Posodobitev zbirke: {date(result.source.dataset_updated_at)}</p>
        </div>}
        <p className="company-source-note">Podatki se osvežujejo dvakrat mesečno. Dejavnost, reference in sposobnosti dopolnite sami. <a href="https://podatki.gov.si/dataset/poslovni-register-slovenije" target="_blank" rel="noreferrer">Vir: AJPES / OPSI · CC BY 4.0 <ExternalLink size={12}/></a></p>
    </div>;
}
