import { useRef, useState } from 'react';
import { Globe, Sparkles, LoaderCircle, AlertCircle, Check, ExternalLink, Building2 } from 'lucide-react';
import { post } from './api';
import type { Profile, WebsiteAnalysis, WebsiteSuggestion } from './types';

type ListKey = 'expertise' | 'technologies' | 'keywords';
export type WebsitePatch = Partial<Pick<Profile, 'website' | 'activity' | 'description' | ListKey>>;

const groups: [ListKey, string][] = [['expertise', 'Strokovna področja'], ['technologies', 'Tehnologije'], ['keywords', 'Ključne besede']];
const path = (url: string) => { try { const u = new URL(url); return u.hostname.replace(/^www\./, '') + (u.pathname === '/' ? '' : u.pathname); } catch { return url; } };

function Evidence({ item }: { item: WebsiteSuggestion }) {
    return <details className="website-evidence"><summary>Vir</summary>{item.evidence.map((e, i) => <p key={i}>{e.kind === 'code' ? <em>{e.quote}</em> : <>»{e.quote}«</>} <a href={e.url} target="_blank" rel="noreferrer">{path(e.url)}<ExternalLink size={11}/></a></p>)}</details>;
}

export default function WebsiteImport({ initial, onUrlChange, onApply, registrationNumber, onRegistry, registryBusy }: {
    initial: string;
    onUrlChange?: (url: string) => void;
    onApply: (patch: WebsitePatch) => void;
    /** Current form identity (10 digits); a number already in the form is not offered again. */
    registrationNumber: string;
    onRegistry: (number: string) => void;
    registryBusy: boolean;
}) {
    const [url, setUrl] = useState(initial);
    const [result, setResult] = useState<WebsiteAnalysis | null>(null);
    const [picked, setPicked] = useState<Set<string>>(new Set());
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const requestId = useRef(0);
    const run = async () => {
        if (busy || url.trim().length < 4) return;
        const id = ++requestId.current;
        setBusy(true); setResult(null); setError('');
        try {
            const response = await post<WebsiteAnalysis>('/profile/website', { url: url.trim() });
            if (id !== requestId.current) return;
            const s = response.suggestions;
            setResult(response);
            setPicked(new Set([...(s.activity ? ['activity'] : []), ...(s.description ? ['description'] : []), ...groups.flatMap(([k]) => s[k].map(i => `${k}:${i.value}`))]));
        } catch (e) { if (id === requestId.current) setError((e as Error).message); }
        finally { if (id === requestId.current) setBusy(false); }
    };
    const toggle = (key: string) => setPicked(old => { const next = new Set(old); if (next.has(key)) next.delete(key); else next.add(key); return next; });
    const apply = () => {
        if (!result) return;
        const s = result.suggestions;
        const patch: WebsitePatch = { website: result.final_url };
        if (s.activity && picked.has('activity')) patch.activity = s.activity.value;
        if (s.description && picked.has('description')) patch.description = s.description.value;
        groups.forEach(([k]) => { patch[k] = s[k].filter(i => picked.has(`${k}:${i.value}`)).map(i => i.value); });
        onApply(patch);
        setResult(null);
    };
    const s = result?.suggestions;
    const empty = s && !s.activity && !s.description && groups.every(([k]) => !s[k].length);
    return <div className="company-lookup website-import">
        <div className="company-lookup-heading"><Globe size={21}/><div><small className="lookup-step">Korak 2</small><strong>Preberite svojo spletno stran</strong><p>Iz javne spletne strani predlagamo dejavnost, opis, področja in tehnologije. Vsak predlog ima citat in povezavo do vira.</p></div></div>
        <label className="field"><span>Spletna stran podjetja</span><div className="company-lookup-input"><input value={url} maxLength={500} placeholder="https://podjetje.si" onChange={e => { setUrl(e.target.value); onUrlChange?.(e.target.value); setError(''); }} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); run(); } }}/><button className="button primary" type="button" onClick={run} disabled={busy || url.trim().length < 4}>{busy ? <LoaderCircle size={17} className="spin"/> : <Sparkles size={17}/>}{busy ? 'Berem …' : 'Preberi stran'}</button></div></label>
        {error && <div className="info-box company-lookup-error" role="alert"><AlertCircle size={17}/><p>{error}</p></div>}
        {result && s && <div className="website-results" aria-live="polite">
            <p className="company-result-count">{result.message}</p>
            {result.warning && <p className="company-lookup-warning">{result.warning}</p>}
            {(result.registration_numbers || []).filter(n => n.value !== registrationNumber).slice(0, 1).map(n => <div className="info-box website-registry" key={n.value}><Building2 size={17}/><div><p>Na strani je navedena matična številka <strong>{n.value}</strong>. Iz AJPES lahko prevzamete uradni naziv in naslov; predlogi s spletne strani ostanejo.</p><Evidence item={n}/></div><button className="button small" type="button" disabled={registryBusy} onClick={() => onRegistry(n.value)}>{registryBusy ? <LoaderCircle size={15} className="spin"/> : <Building2 size={15}/>}Prevzemi iz AJPES</button></div>)}
            {!empty && <>
                {s.activity && <label className="website-choice"><input type="checkbox" checked={picked.has('activity')} onChange={() => toggle('activity')}/><span><b>Dejavnost</b>{s.activity.value}<Evidence item={s.activity}/></span></label>}
                {s.description && <label className="website-choice"><input type="checkbox" checked={picked.has('description')} onChange={() => toggle('description')}/><span><b>Opis (zamenja trenutnega)</b>{s.description.value}<Evidence item={s.description}/></span></label>}
                {groups.map(([k, label]) => s[k].length > 0 && <div className="website-group" key={k}><b>{label}</b><div>{s[k].map(item => <label key={item.value} className={`website-chip ${picked.has(`${k}:${item.value}`) ? 'on' : ''}`} title={item.evidence.map(e => e.quote).join('\n')}><input type="checkbox" checked={picked.has(`${k}:${item.value}`)} onChange={() => toggle(`${k}:${item.value}`)}/>{picked.has(`${k}:${item.value}`) && <Check size={12}/>}{item.value}{item.evidence[0]?.kind === 'code' && <small>iz kode strani</small>}</label>)}</div></div>)}
                <p className="company-source-note">Prebrane strani: {result.pages.map(p => path(p.url)).join(', ')}. Področja se dodajo obstoječim in ostanejo tudi, če nato izberete podjetje v AJPES; reference, kadri in certifikati se s spletne strani ne sklepajo.</p>
                <div className="modal-actions"><button className="button" type="button" onClick={() => setResult(null)}>Zavrzi</button><button className="button primary" type="button" onClick={apply}><Check size={16}/>Prenesi izbrano v obrazec</button></div>
            </>}
        </div>}
    </div>;
}
