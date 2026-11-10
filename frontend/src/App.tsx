import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Radar, LayoutGrid, Sparkles, Building2, Bell, Search, SlidersHorizontal, ArrowUpRight, ArrowRight, ChevronDown, ChevronRight, ChevronLeft, Check, Plus, X, Bookmark, Clock3, CalendarDays, MapPin, CircleHelp, CheckCircle2, AlertCircle, FileText, ExternalLink, RefreshCw, LoaderCircle, Send, CheckCheck, Menu, ArrowLeft, FlaskConical, Settings2, Save, Trash2, Upload, Link2, ShieldCheck, Bot, TriangleAlert, Eye, Satellite, Zap, Code2, Lightbulb, Coins, ArrowDownUp } from 'lucide-react';
import { api, post, filterQuery } from './api';
import type { Bootstrap, ChatMessage, ChatResponse, Filters, Profile, Tender, Notification, SavedSearch, MatchLevel, ConditionState, CompanyReference } from './types';
const money = (value: number | null | undefined) => value == null ? 'Ni podatka' : new Intl.NumberFormat('sl-SI', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(value);
const date = (value?: string | null, options?: Intl.DateTimeFormatOptions) => value && !Number.isNaN(new Date(value).getTime()) ? new Date(value).toLocaleDateString('sl-SI', { timeZone: 'Europe/Ljubljana', ...(options || { day: 'numeric', month: 'short', year: 'numeric' }) }) : 'Ni podatka';
const labels: Record<string, string> = { high: 'Visoko ujemanje', medium: 'Srednje ujemanje', low: 'Nizko ujemanje', met: 'Izpolnjen', unmet: 'Ni izpolnjen', unknown: 'Potrebna dopolnitev', services: 'Storitve', goods: 'Blago', works: 'Gradnje', open: 'Odprt', closed: 'Zaključen', cancelled: 'Ustavljen', recommended: 'Priporočeno za pregled', review: 'Potrebno preveriti', unsuitable: 'Ni primerno', correction: 'Sprememba pogojev', deadline: 'Sprememba roka', new: 'Nova priložnost' };
const defaults: Filters = { view: 'recommended', sort: 'match', include_unknown: true };
const cpvOptions = [['72000000', 'IT storitve'], ['72230000', 'Razvoj po meri'], ['72262000', 'Programska oprema'], ['72316000', 'Analiza podatkov'], ['45000000', 'Gradbena dela'], ['48000000', 'Programski paketi']];
function navigate(path: string) { window.location.hash = path; }
function useRoute() { const [route, setRoute] = useState(window.location.hash.slice(1) || '/razpisi'); useEffect(() => { const update = () => { setRoute(window.location.hash.slice(1) || '/razpisi'); window.scrollTo(0, 0); }; window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update); }, []); return route; }
function Spinner({ small = false }: {
    small?: boolean;
}) { return <LoaderCircle size={small ? 16 : 22} className="spin" aria-label="Nalaganje"/>; }
function Badge({ children, tone = 'neutral' }: {
    children: ReactNode;
    tone?: string;
}) { return <span className={`badge ${tone}`}>{children}</span>; }
function MatchBadge({ level, score }: {
    level: MatchLevel;
    score?: number;
}) { return <span className={`match-badge ${level}`}><span className="match-bars"><i /><i /><i /></span>{labels[level]}{score !== undefined && <b title="Ocena vsebinskega ujemanja, ne verjetnost uspeha">{Math.round(score)}</b>}</span>; }
function StateBadge({ status }: {
    status: ConditionState;
}) { const Icon = status === 'met' ? CheckCircle2 : status === 'unmet' ? AlertCircle : CircleHelp; return <span className={`condition-state ${status}`}><Icon size={15}/>{labels[status]}</span>; }
function EmptyState({ icon, title, children, action }: {
    icon?: ReactNode;
    title: string;
    children: ReactNode;
    action?: ReactNode;
}) { return <div className="empty-state"><div className="empty-icon">{icon || <Search size={27}/>}</div><h3>{title}</h3><p>{children}</p>{action}</div>; }
function Modal({ title, description, children, close }: {
    title: string;
    description?: string;
    children: ReactNode;
    close: () => void;
}) { useEffect(() => { const listener = (e: KeyboardEvent) => { if (e.key === 'Escape')
    close(); }; window.addEventListener('keydown', listener); return () => window.removeEventListener('keydown', listener); }, [close]); return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget)
    close(); }}><section className="modal" role="dialog" aria-modal="true" aria-label={title}><div className="modal-heading"><div><h2>{title}</h2>{description && <p>{description}</p>}</div><button className="icon-button" onClick={close} aria-label="Zapri okno"><X size={20}/></button></div>{children}</section></div>; }
function Field({ label, hint, children, className = '' }: {
    label: string;
    hint?: string;
    children: ReactNode;
    className?: string;
}) { return <label className={`field ${className}`}><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>; }
function ChipInput({ value, onChange, placeholder, label }: {
    value: string[];
    onChange: (value: string[]) => void;
    placeholder?: string;
    label: string;
}) { const [draft, setDraft] = useState(''); const add = () => { const terms = draft.split(',').map(v => v.trim()).filter(Boolean); if (terms.length)
    onChange([...new Set([...value, ...terms])]); setDraft(''); }; return <div className="chip-input"><div className="chip-values">{value.map(v => <span className="input-chip" key={v}>{v}<button type="button" onClick={() => onChange(value.filter(x => x !== v))} aria-label={`Odstrani ${v}`}><X size={12}/></button></span>)}</div><input aria-label={label} placeholder={placeholder || 'Dodajte in pritisnite Enter'} value={draft} onChange={e => setDraft(e.target.value)} onBlur={add} onKeyDown={e => { if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault();
    add();
} }}/></div>; }
function daysLeft(deadline: string | null, today: string) { if (!deadline || Number.isNaN(new Date(deadline).getTime()))
    return null; const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Ljubljana', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(deadline)); const value = (part: string) => Number(parts.find(p => p.type === part)?.value); const [year, month, day] = today.split('-').map(Number); return Math.round((Date.UTC(value('year'), value('month') - 1, value('day')) - Date.UTC(year, month - 1, day)) / 86400000); }
function tenderIcon(tender: Tender) { return tender.topics.some(x => /iot|energ/i.test(x)) ? <Zap size={22}/> : tender.id === 'satellite' ? <Satellite size={22}/> : tender.kind === 'goods' ? <Coins size={22}/> : <Code2 size={22}/>; }
type Shared = {
    data: Bootstrap;
    refresh: () => Promise<void>;
    notify: (message: string, error?: boolean) => void;
};
export default function App() {
    const route = useRoute();
    const [data, setData] = useState<Bootstrap | null>(null);
    const [error, setError] = useState('');
    const [toast, setToast] = useState<{
        message: string;
        error: boolean;
    } | null>(null);
    const [mobileNav, setMobileNav] = useState(false);
    const [demoOpen, setDemoOpen] = useState(false);
    const [demoBusy, setDemoBusy] = useState('');
    const [resetConfirm, setResetConfirm] = useState(false);
    const [filters, setFilters] = useState<Filters>(defaults);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [chatSelection, setChatSelection] = useState<string[]>([]);
    const [importOpen, setImportOpen] = useState(false);
    const refresh = async () => { const next = await api<Bootstrap>('/bootstrap'); setData(next); setError(''); };
    const notify = (message: string, isError = false) => { setToast({ message, error: isError }); };
    useEffect(() => { refresh().catch(e => setError(e.message)); }, []);
    useEffect(() => { if (!toast)
        return; const timer = setTimeout(() => setToast(null), 5500); return () => clearTimeout(timer); }, [toast]);
    useEffect(() => { const timer = setInterval(() => { api<Notification[]>('/notifications').then(notifications => setData(old => old ? { ...old, notifications } : old)).catch(() => { }); }, 30000); return () => clearInterval(timer); }, []);
    useEffect(() => { setMobileNav(false); setDemoOpen(false); }, [route]);
    const event = async (type: string) => { setDemoOpen(false); setDemoBusy(type); try {
        const result = type === 'reset' ? await post<Bootstrap>('/demo/reset') : await post<{
            message: string;
        }>('/demo/event', { type });
        await refresh();
        if (type === 'reset') {
            setFilters(defaults);
            setMessages([]);
            navigate('/razpisi');
        }
        notify('message' in result ? result.message : 'Demo je pripravljen na nov začetek.');
        setResetConfirm(false);
    }
    catch (e) {
        notify((e as Error).message, true);
    }
    finally {
        setDemoBusy('');
    } };
    if (!data)
        return <div className="boot-screen"><div className="boot-brand"><Radar size={36}/><strong>razpisni<span>radar</span></strong></div>{error ? <><h2>Povezava še ni pripravljena</h2><p>{error}</p><p className="muted">Preverite, ali Django strežnik deluje na vratih 8001.</p><button className="button primary" onClick={() => refresh().catch(e => setError(e.message))}><RefreshCw size={16}/>Poskusi ponovno</button></> : <><Spinner /><p>Pripravljamo vaše priložnosti …</p></>}</div>;
    const unread = data.notifications.filter(n => !n.read).length;
    const shared: Shared = { data, refresh, notify };
    const section = route.startsWith('/profil') ? 'Profil podjetja' : route.startsWith('/svetovalec') ? 'AI svetovalec' : route.startsWith('/obvestila') ? 'Obvestila' : 'Razpisi';
    const goChat = (ids: string[] = []) => { setChatSelection(ids); navigate('/svetovalec'); };
    return <div className="app-shell">
    {mobileNav && <div className="nav-scrim" onClick={() => setMobileNav(false)}/>}
    <aside className={`sidebar ${mobileNav ? 'open' : ''}`}>
      <a className="brand" href="#/razpisi" aria-label="Razpisni radar, začetna stran"><div className="brand-icon"><Radar size={25} strokeWidth={1.7}/></div><div>razpisni<span>radar<span className="brand-dot">.</span></span></div></a>
      <div className="workspace-label">VAŠ DELOVNI PROSTOR</div>
      <nav className="main-nav" aria-label="Glavna navigacija">
        <a href="#/razpisi" className={section === 'Razpisi' && filters.view !== 'following' ? 'active' : ''} onClick={() => setFilters(f => ({ ...f, view: 'recommended' }))}><LayoutGrid size={19}/>Razpisi<span className="nav-count">{data.tenders.filter(t => t.status === 'open').length}</span></a>
        <a href="#/svetovalec" className={section === 'AI svetovalec' ? 'active' : ''}><Sparkles size={19}/>AI svetovalec<span className="nav-ai">AI</span></a>
        <a href="#/obvestila" className={section === 'Obvestila' ? 'active' : ''}><Bell size={19}/>Obvestila{unread > 0 && <span className="nav-count notification-count">{unread}</span>}</a>
        <a href="#/profil" className={section === 'Profil podjetja' ? 'active' : ''}><Building2 size={19}/>Profil podjetja</a>
      </nav>
      <div className="sidebar-line"/>
      <div className="workspace-label">ORGANIZACIJA</div>
      <nav className="main-nav"><a href="#/razpisi" className={section === 'Razpisi' && filters.view === 'following' ? 'active' : ''} onClick={() => setFilters({ ...defaults, view: 'following' })}><Bookmark size={18}/>Spremljani razpisi<span className="plain-count">{data.tenders.filter(t => t.following).length}</span></a></nav>
      <div className="sidebar-note"><div className="note-icon"><Sparkles size={18}/></div><h4>Boljši profil.<br />Boljše priložnosti.</h4><p>Dopolnite svoje reference za natančnejša priporočila.</p><a href="#/profil">Dopolni profil <ArrowUpRight size={14}/></a></div>
      <div className="sidebar-bottom"><div className="demo-indicator"><span />HACKATHON DEMO</div><a href="#/profil" className="company-switch"><div className="avatar">{data.profile.name.slice(0, 2).toUpperCase()}</div><div><strong>{data.profile.name}</strong><small>Demo podjetje</small></div><Settings2 size={16}/></a></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" onClick={() => setMobileNav(!mobileNav)} aria-label="Odpri navigacijo"><Menu size={21}/></button><span>Delovni prostor</span><ChevronRight size={14}/><strong>{section}</strong>{route.startsWith('/razpisi/') && <><ChevronRight size={14}/><span>Podrobnosti</span></>}</div><div className="topbar-actions"><span className="data-status"><span />Podatki pripravljeni</span><div className="demo-dropdown"><button className={`button ghost small ${demoOpen ? 'selected' : ''}`} onClick={() => setDemoOpen(!demoOpen)}><FlaskConical size={15}/>Demo dogodki<ChevronDown size={14}/></button>{demoOpen && <div className="dropdown-menu"><div className="dropdown-label">SIMULACIJA DOGODKOV</div><p>Prikažite potencial na pripravljenih primerih.</p>{[['new', 'Nova priložnost', <Plus size={16}/>], ['correction', 'Popravek referenčnega pogoja', <FileText size={16}/>], ['deadline', 'Podaljšanje roka', <CalendarDays size={16}/>]].map(([type, label, icon]) => <button key={String(type)} disabled={!!demoBusy} onClick={() => event(String(type))}>{demoBusy === type ? <Spinner small/> : icon}{label}</button>)}<div className="dropdown-divider"/><button onClick={() => { setImportOpen(true); setDemoOpen(false); }}><Link2 size={16}/>Uvozi pravo objavo</button><button onClick={() => { setResetConfirm(true); setDemoOpen(false); }}><RefreshCw size={16}/>Ponastavi demo</button></div>}</div><button className="notification-button icon-button" onClick={() => navigate('/obvestila')} aria-label={`Obvestila, ${unread} neprebranih`}><Bell size={20}/>{unread > 0 && <i />}</button><div className="topbar-avatar">DP</div></div></header>
      <main className="main-content">
        {route.startsWith('/razpisi/') ? <TenderDetail key={route} {...shared} id={decodeURIComponent(route.split('/')[2].split('?')[0])} goChat={goChat}/> : route === '/profil' ? <ProfilePage {...shared}/> : route === '/svetovalec' ? <ChatPage {...shared} messages={messages} setMessages={setMessages} selection={chatSelection} setSelection={setChatSelection} applyFilters={suggested => { setFilters({ ...defaults, ...suggested }); navigate('/razpisi'); }}/> : route === '/obvestila' ? <NotificationsPage {...shared}/> : <TendersPage {...shared} filters={filters} setFilters={setFilters} goChat={goChat}/>}
      </main>
      <footer className="app-footer"><span>Razpisni radar <span className="footer-dot">·</span> Od objave do odločitve.</span><span>Demo podatki so jasno označeni <ShieldCheck size={13}/></span></footer>
    </div>
    {toast && <div role="status" className={`toast ${toast.error ? 'error' : ''}`}>{toast.error ? <AlertCircle size={19}/> : <CheckCircle2 size={19}/>}<span>{toast.message}</span><button onClick={() => setToast(null)} aria-label="Zapri obvestilo"><X size={16}/></button></div>}
    {resetConfirm && <Modal title="Ponastavimo demo?" description="Profil, shranjena iskanja, obvestila in dogodki se vrnejo v začetno stanje." close={() => setResetConfirm(false)}><div className="modal-actions"><button className="button" onClick={() => setResetConfirm(false)}>Prekliči</button><button className="button primary" disabled={!!demoBusy} onClick={() => event('reset')}>{demoBusy ? <Spinner small/> : <RefreshCw size={16}/>}Ponastavi</button></div></Modal>}
    {importOpen && <ImportModal {...shared} close={() => setImportOpen(false)}/>}
  </div>;
}
function ImportModal({ refresh, notify, close }: Shared & {
    close: () => void;
}) {
    const [input, setInput] = useState('1144799');
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState<{
        message: string;
        warning?: string;
        mode?: string;
        tender?: Tender;
    } | null>(null);
    const submit = async (e: FormEvent) => { e.preventDefault(); setBusy(true); try {
        const response = await post<typeof result>('/import', { url_or_id: input });
        setResult(response);
        await refresh();
    }
    catch (e) {
        notify((e as Error).message, true);
    }
    finally {
        setBusy(false);
    } };
    return <Modal title="Uvoz iz e-Naročanja" description="Vnesite povezavo ali ID objave. Izvorni podatki se shranijo za nadaljnjo obdelavo." close={close}><form onSubmit={submit}><Field label="Povezava ali ID objave"><input value={input} onChange={e => setInput(e.target.value)} required placeholder="https://www.enarocanje.si/#/pregled-objav/…"/></Field><div className="info-box"><CircleHelp size={18}/><p>Primer 1144799 je resnična arhivska objava IJS. Ustavljene objave niso prikazane kot nove priložnosti. Zajem je omejen na največ dva zagona dnevno.</p></div>{result && <div className="import-result"><Badge tone={result.mode === 'live' ? 'green' : 'amber'}>{result.mode === 'live' ? 'Pridobljeno iz vira' : result.mode === 'unavailable' ? 'Uvoz ni uspel' : 'Shranjeni podatki'}</Badge><p>{result.message}</p>{result.warning && <p className="muted">{result.warning}</p>}{result.tender && <a className="text-link" href={`#/razpisi/${result.tender.id}`} onClick={close}>Odpri uvoženo objavo <ArrowRight size={15}/></a>}</div>}<div className="modal-actions"><button className="button" type="button" onClick={close}>Zapri</button><button className="button primary" disabled={busy || !input.trim()}>{busy ? <Spinner small/> : <Link2 size={16}/>}Uvozi objavo</button></div></form></Modal>;
}
function TendersPage({ data, refresh, notify, filters, setFilters, goChat }: Shared & {
    filters: Filters;
    setFilters: (filters: Filters | ((old: Filters) => Filters)) => void;
    goChat: (ids?: string[]) => void;
}) {
    const [results, setResults] = useState<Tender[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [showFilters, setShowFilters] = useState(false);
    const [saveOpen, setSaveOpen] = useState(false);
    const [saveName, setSaveName] = useState('');
    const [saving, setSaving] = useState(false);
    const [aiText, setAiText] = useState('');
    const [aiOpen, setAiOpen] = useState(false);
    const [aiBusy, setAiBusy] = useState(false);
    const [suggestion, setSuggestion] = useState<{
        filters: Filters;
        explanation: string;
        mode: string;
    } | null>(null);
    const filterKey = JSON.stringify(filters);
    useEffect(() => { let active = true; setLoading(true); const timer = setTimeout(() => { api<{
        results: Tender[];
        count: number;
    }>(`/tenders?${filterQuery(filters)}`).then(r => { if (active) {
        setResults(r.results);
        setError('');
    } }).catch(e => { if (active)
        setError(e.message); }).finally(() => { if (active)
        setLoading(false); }); }, 180); return () => { active = false; clearTimeout(timer); }; }, [filterKey, data.tenders]);
    const set = (patch: Partial<Filters>) => setFilters(old => ({ ...old, ...patch }));
    const activeCount = Object.entries(filters).filter(([k, v]) => !['view', 'sort', 'include_unknown'].includes(k) && v !== undefined && v !== '' && v !== false && (!Array.isArray(v) || v.length)).length;
    const save = async (e: FormEvent) => { e.preventDefault(); setSaving(true); try {
        await post('/searches', { name: saveName, filters });
        await refresh();
        setSaveOpen(false);
        setSaveName('');
        notify('Iskanje je shranjeno. Vedno ga lahko odprete z enim klikom.');
    }
    catch (e) {
        notify((e as Error).message, true);
    }
    finally {
        setSaving(false);
    } };
    const suggest = async (e: FormEvent) => { e.preventDefault(); setAiBusy(true); try {
        setSuggestion(await post('/filters/suggest', { message: aiText }));
    }
    catch (e) {
        notify((e as Error).message, true);
    }
    finally {
        setAiBusy(false);
    } };
    const follow = async (tender: Tender) => { try {
        await post(`/tenders/${tender.id}/follow`, { following: !tender.following });
        await refresh();
        notify(tender.following ? 'Razpis ne spremljate več.' : 'Razpis spremljate. Ob spremembah boste obveščeni.');
    }
    catch (e) {
        notify((e as Error).message, true);
    } };
    const suitable = data.tenders.filter(t => t.status === 'open' && !['unsuitable', 'closed'].includes(t.match.recommendation)).length;
    const upcoming = data.tenders.filter(t => t.status === 'open' && (daysLeft(t.deadline, data.meta.today) ?? 99) <= 14).length;
    return <>
    <div className="page-heading"><div><div className="eyebrow">MANJ ISKANJA. VEČ PRILOŽNOSTI.</div><h1>Priložnosti, ki ustrezajo vam<span className="accent-dot">.</span></h1><p>Najdite prave razpise. Razumite pogoje. Odločite se z zaupanjem.</p></div><button className="button primary" onClick={() => goChat()}><Sparkles size={17}/>Vprašaj AI svetovalca</button></div>
    <div className="metric-grid"><div className="metric-card"><div className="metric-icon purple"><Radar size={22}/></div><div><span>Priložnosti za vaše podjetje</span><strong>{suitable}<small>primernih za pregled</small></strong></div><span className="metric-corner"><ArrowUpRight size={18}/></span></div><div className="metric-card"><div className="metric-icon blue"><Bookmark size={21}/></div><div><span>Razpisi, ki jih spremljate</span><strong>{data.tenders.filter(t => t.following).length}<small>na vašem radarju</small></strong></div><button className="metric-corner icon-button" onClick={() => setFilters({ ...defaults, view: 'following' })} aria-label="Prikaži spremljane razpise"><ArrowUpRight size={18}/></button></div><div className="metric-card"><div className="metric-icon amber"><Clock3 size={21}/></div><div><span>Roki v naslednjih 14 dneh</span><strong>{upcoming}<small>čas za naslednji korak</small></strong></div><span className="metric-corner"><CalendarDays size={17}/></span></div></div>
    <div className="list-navigation"><div className="tabs" aria-label="Pogled razpisov">{[['recommended', 'Priporočeno zame', suitable], ['all', 'Vsi razpisi', data.tenders.length], ['following', 'Spremljam', data.tenders.filter(t => t.following).length]].map(([view, label, count]) => <button className={(filters.view || 'recommended') === view ? 'active' : ''} key={view} onClick={() => set({ view: view as Filters['view'] })}>{label}<span>{count}</span></button>)}</div><span className="updated-at"><span />{data.meta.last_sync ? `Posodobljeno ${date(data.meta.last_sync, { day: 'numeric', month: 'short' })}` : 'Demo nabor je pripravljen'}</span></div>
    <div className="saved-searches"><span><Bookmark size={14}/>Shranjena iskanja</span>{data.saved_searches.length ? data.saved_searches.map(saved => <div className="saved-search" key={saved.id}><button onClick={() => setFilters({ ...defaults, ...saved.filters })}>{saved.name}<ArrowUpRight size={12}/></button><button className="delete-search" aria-label={`Izbriši iskanje ${saved.name}`} onClick={async () => { try {
        await api(`/searches/${saved.id}`, { method: 'DELETE' });
        await refresh();
    }
    catch (e) {
        notify((e as Error).message, true);
    } }}><X size={11}/></button></div>) : <span className="saved-empty">Vaši priljubljeni filtri na enem mestu.</span>}<button className="save-search-link" onClick={() => setSaveOpen(true)}><Plus size={14}/>Shrani iskanje</button></div>
    <div className="search-toolbar"><div className="search-input"><Search size={19}/><input aria-label="Išči razpise" placeholder="Iščite po naslovu, vsebini ali ključnih besedah …" value={filters.q || ''} onChange={e => set({ q: e.target.value })}/>{filters.q && <button onClick={() => set({ q: '' })} aria-label="Počisti iskanje"><X size={16}/></button>}</div><button className={`button ai-search-button ${aiOpen ? 'selected' : ''}`} onClick={() => setAiOpen(!aiOpen)}><Sparkles size={16}/>Opišite, kaj iščete</button><button className="button filter-toggle" onClick={() => setShowFilters(!showFilters)}><SlidersHorizontal size={17}/>Filtri{activeCount > 0 && <b>{activeCount}</b>}</button></div>
    {aiOpen && <div className="ai-filter-box"><div className="ai-filter-intro"><Sparkles size={19}/><div><strong>Vaše besede postanejo natančni filtri.</strong><p>Na primer: Iščemo spletne platforme in IoT, brez same dobave računalnikov.</p></div><Badge tone="purple">AI pomočnik</Badge></div><form onSubmit={suggest} className="ai-filter-form"><input aria-label="Opis želenih razpisov" placeholder="Opišite svojo naslednjo priložnost …" value={aiText} onChange={e => setAiText(e.target.value)}/><button className="button primary small" disabled={aiBusy || !aiText.trim()}>{aiBusy ? <Spinner small/> : <Sparkles size={15}/>}Predlagaj filtre</button></form>{suggestion && <div className="filter-proposal"><p>{suggestion.explanation}</p><div className="proposal-tags">{Object.entries(suggestion.filters).filter(([, v]) => v !== '' && v !== undefined).map(([k, v]) => <span key={k}>{filterLabel(k)}: {Array.isArray(v) ? v.map(x => labels[x] || x).join(', ') : typeof v === 'boolean' ? v ? 'da' : 'ne' : v}</span>)}</div><div className="proposal-footer"><small>{suggestion.mode === 'demo' ? 'Predlog iz demo načina' : 'AI predlog'} · Uporabi se šele po vaši potrditvi.</small><button className="button primary small" onClick={() => { setFilters({ ...defaults, ...suggestion.filters }); setSuggestion(null); notify('Predlagani filtri so uporabljeni.'); }}>Uporabi filtre<Check size={15}/></button></div></div>}</div>}
    {activeCount > 0 && <div className="active-filter-list" aria-label="Aktivni filtri">{Object.entries(filters).filter(([key, value]) => !['view', 'sort', 'include_unknown'].includes(key) && value !== undefined && value !== '' && value !== false && (!Array.isArray(value) || value.length)).map(([key, value]) => <span key={key}><b>{filterLabel(key)}</b>{Array.isArray(value) ? value.map(item => labels[item] || item).join(', ') : value === true ? '' : String(value)}<button aria-label={`Odstrani filter ${filterLabel(key)}`} onClick={() => set({ [key]: undefined })}><X size={12}/></button></span>)}</div>}
    <div className="tenders-layout"><aside className={`filter-panel ${showFilters ? 'mobile-open' : ''}`}><div className="filter-panel-title"><h3><SlidersHorizontal size={17}/>Filtri {activeCount > 0 && <span>{activeCount}</span>}</h3><button onClick={() => setFilters({ ...defaults, view: filters.view })}>Ponastavi</button></div><FilterPanel filters={filters} set={set} tenders={data.tenders}/><div className="filter-panel-foot"><ShieldCheck size={15}/><p>Priporočila temeljijo na vašem profilu.<a href="#/profil">Uredi profil <ArrowUpRight size={12}/></a></p></div></aside>
    <section className="tender-results" aria-label="Rezultati iskanja"><div className="results-heading"><div><strong>{loading ? 'Iščemo …' : `${results.length} ${results.length === 1 ? 'priložnost' : results.length === 2 ? 'priložnosti' : results.length < 5 ? 'priložnosti' : 'priložnosti'}`}</strong><span>{filters.view === 'following' ? 'Spremljane spremembe na enem mestu' : 'Razvrščeno glede na vaše podjetje'}</span></div><label className="sort-control"><ArrowDownUp size={14}/><select aria-label="Razvrsti razpise" value={filters.sort || 'match'} onChange={e => set({ sort: e.target.value as Filters['sort'] })}><option value="match">Najboljše ujemanje</option><option value="deadline">Najbližji rok</option><option value="newest">Najnovejše objave</option><option value="value">Najvišja vrednost</option></select></label></div>{error ? <div className="error-banner"><AlertCircle size={20}/><div><strong>Razpisov ni bilo mogoče naložiti.</strong><p>{error}</p></div></div> : loading && !results.length ? <div className="card-skeletons">{[1, 2, 3].map(i => <div className="card-skeleton" key={i}><i /><i /><i /></div>)}</div> : !results.length ? <EmptyState title="Za te filtre ni zadetkov." action={<button className="button" onClick={() => setFilters({ ...defaults, view: 'all' })}>Prikaži vse razpise</button>}>Poskusite odstraniti posamezen filter ali vključiti razpise z neznanimi podatki.</EmptyState> : <div className={`tender-list ${loading ? 'refreshing' : ''}`}>{results.map((tender, i) => <TenderCard key={tender.id} tender={tender} today={data.meta.today} follow={follow} index={i}/>)}</div>}<div className="results-note"><ShieldCheck size={14}/><span>Ocena ujemanja je pomoč pri pregledu. Pogoje vedno preverite v izvorni dokumentaciji.</span></div></section></div>
    {saveOpen && <Modal title="Shranite to iskanje" description="Ponovno uporabite izbrane filtre z enim klikom." close={() => setSaveOpen(false)}><form onSubmit={save}><Field label="Ime iskanja"><input autoFocus required maxLength={80} placeholder="Na primer: IoT in spletne platforme" value={saveName} onChange={e => setSaveName(e.target.value)}/></Field><div className="modal-actions"><button className="button" type="button" onClick={() => setSaveOpen(false)}>Prekliči</button><button className="button primary" disabled={saving || !saveName.trim()}>{saving ? <Spinner small/> : <Bookmark size={16}/>}Shrani iskanje</button></div></form></Modal>}
  </>;
}
function filterLabel(key: string) { return ({ q: 'Ključne besede', exclude: 'Izključeno', cpv: 'CPV', kinds: 'Vrsta', min_value: 'Najmanj EUR', max_value: 'Največ EUR', min_days: 'Dni do roka', levels: 'Ujemanje', include_unknown: 'Vključi neznane', statuses: 'Stanje', regions: 'Lokacije', view: 'Pogled', condition_states: 'Pogoji', only_new: 'Samo nove', only_updates: 'Popravki', only_following: 'Spremljam', buyers: 'Naročniki', published_from: 'Objava od', published_to: 'Objava do', deadline_from: 'Rok od', deadline_to: 'Rok do' } as Record<string, string>)[key] || key; }
function FilterPanel({ filters, set, tenders }: {
    filters: Filters;
    set: (patch: Partial<Filters>) => void;
    tenders: Tender[];
}) {
    const toggle = (key: keyof Filters, value: string) => { const values = (filters[key] as string[] | undefined) || []; set({ [key]: values.includes(value) ? values.filter(v => v !== value) : [...values, value] }); };
    const check = (key: keyof Filters, value: string, text: string, count?: number) => <label className="checkbox-row" key={value}><input type="checkbox" checked={((filters[key] as string[]) || []).includes(value)} onChange={() => toggle(key, value)}/><span>{text}</span>{count !== undefined && <small>{count}</small>}</label>;
    const regions = [...new Set(tenders.map(t => t.region))].filter(Boolean);
    const buyers = [...new Set(tenders.map(t => t.buyer))].filter(Boolean);
    return <>
    <div className="filter-group"><h4>Vrsta naročila</h4>{['services', 'goods', 'works'].map(kind => check('kinds', kind, labels[kind], tenders.filter(t => t.kind === kind).length))}</div>
    <div className="filter-group"><h4>Vsebinsko ujemanje<CircleHelp size={13}><title>Vsebinska podobnost s profilom podjetja</title></CircleHelp></h4>{(['high', 'medium', 'low'] as const).map(level => <label className="checkbox-row" key={level}><input type="checkbox" checked={(filters.levels || []).includes(level)} onChange={() => toggle('levels', level)}/><span className={`level-dot ${level}`}/><span>{labels[level].replace(' ujemanje', '')}</span></label>)}</div>
    <div className="filter-group"><h4>Področje / CPV</h4>{cpvOptions.map(([code, label]) => check('cpv', code, label))}<OtherCpvCodes values={filters.cpv || []} onChange={cpv => set({ cpv })}/></div>
    <div className="filter-group"><h4>Ocenjena vrednost</h4><div className="range-inputs"><label><span>Od</span><input type="number" min="0" aria-label="Najnižja vrednost" placeholder="0 €" value={filters.min_value ?? ''} onChange={e => set({ min_value: e.target.value === '' ? undefined : Number(e.target.value) })}/></label><span>–</span><label><span>Do</span><input type="number" min="0" aria-label="Najvišja vrednost" placeholder="Brez meje" value={filters.max_value ?? ''} onChange={e => set({ max_value: e.target.value === '' ? undefined : Number(e.target.value) })}/></label></div><label className="checkbox-row compact"><input type="checkbox" checked={filters.include_unknown !== false} onChange={e => set({ include_unknown: e.target.checked })}/><span>Vključi neznane podatke</span></label></div>
    <div className="filter-group"><h4>Lokacija izvedbe</h4>{regions.map(region => check('regions', region, region))}</div>
    <div className="filter-group"><h4>Pogoji sodelovanja</h4>{(['met', 'unknown', 'unmet'] as const).map(status => check('condition_states', status, status === 'met' ? 'Izpolnjeni pogoji' : status === 'unknown' ? 'Potrebna dopolnitev' : 'Neizpolnjen pogoj'))}</div>
    <details className="filter-more"><summary>Več filtrov<ChevronDown size={15}/></summary><div className="filter-group"><Field label="Izključene besede" hint="Ločite z vejico."><input placeholder="licence, tiskalniki" value={filters.exclude || ''} onChange={e => set({ exclude: e.target.value })}/></Field><Field label="Najmanj dni do roka"><input type="number" min="0" placeholder="Na primer 14" value={filters.min_days ?? ''} onChange={e => set({ min_days: e.target.value ? Number(e.target.value) : undefined })}/></Field></div><div className="filter-group"><h4>Naročnik</h4>{buyers.map(buyer => check('buyers', buyer, buyer))}</div><div className="filter-group"><h4>Datum objave</h4><Field label="Od"><input type="date" value={filters.published_from || ''} onChange={e => set({ published_from: e.target.value })}/></Field><Field label="Do"><input type="date" value={filters.published_to || ''} onChange={e => set({ published_to: e.target.value })}/></Field></div><div className="filter-group"><h4>Rok prijave</h4><Field label="Od"><input type="date" value={filters.deadline_from || ''} onChange={e => set({ deadline_from: e.target.value })}/></Field><Field label="Do"><input type="date" value={filters.deadline_to || ''} onChange={e => set({ deadline_to: e.target.value })}/></Field></div><div className="filter-group"><h4>Stanje razpisa</h4>{['open', 'closed', 'cancelled'].map(status => check('statuses', status, labels[status]))}</div></details>
    <div className="filter-group quick-filters"><h4>Hitri filtri</h4><label className="checkbox-row"><input type="checkbox" checked={filters.only_new || false} onChange={e => set({ only_new: e.target.checked })}/><span>Samo nove objave</span></label><label className="checkbox-row"><input type="checkbox" checked={filters.only_updates || false} onChange={e => set({ only_updates: e.target.checked })}/><span>Samo s popravki</span></label></div>
  </>;
}
function TenderCard({ tender, today, follow, index }: {
    tender: Tender;
    today: string;
    follow: (tender: Tender) => Promise<void>;
    index: number;
}) {
    const [busy, setBusy] = useState(false);
    const days = daysLeft(tender.deadline, today);
    return <article className={`tender-card ${tender.status !== 'open' ? 'inactive' : ''}`} style={{ animationDelay: `${index * 45}ms` }}>
    <div className="card-topline"><div className="card-tags"><Badge>{labels[tender.kind]}</Badge>{tender.source_type === 'demo' ? <span className="demo-tag">DEMO</span> : <Badge tone="blue">Izvorna objava</Badge>}{tender.status !== 'open' ? <Badge>{labels[tender.status]}</Badge> : tender.has_update ? <Badge tone="amber"><RefreshCw size={10}/>Popravek</Badge> : tender.is_new ? <Badge tone="green"><span className="tiny-dot"/>Novo</Badge> : null}</div><div className="card-match"><MatchBadge level={tender.match.level} score={tender.match.score}/><button className={`icon-button bookmark-button ${tender.following ? 'saved' : ''}`} disabled={busy} onClick={async () => { setBusy(true); await follow(tender); setBusy(false); }} aria-label={tender.following ? `Prenehaj spremljati: ${tender.title}` : `Spremljaj: ${tender.title}`} title={tender.following ? 'Spremljate razpis' : 'Spremljaj razpis'}>{busy ? <Spinner small/> : <Bookmark size={19} fill={tender.following ? 'currentColor' : 'none'}/>}</button></div></div>
    <a href={`#/razpisi/${tender.id}`} className="tender-title"><h2>{tender.title}</h2><ArrowUpRight size={19}/></a><div className="tender-buyer"><Building2 size={13}/><span>{tender.buyer}</span><i /><MapPin size={13}/><span>{tender.region || 'Lokacija ni navedena'}</span></div><p className="tender-summary">{tender.summary}</p>
    <div className="match-reasons">{tender.match.reasons.slice(0, 2).map((reason, i) => <span key={i}><Check size={12}/>{reason}</span>)}</div>
    {tender.match.open_question && <div className={`open-question ${tender.match.conditions.some(c => c.status === 'unmet') ? 'unmet' : ''}`}><CircleHelp size={15}/><span>{tender.match.open_question}</span></div>}
    <div className="card-footer"><div className="card-metadata"><div><span>Ocenjena vrednost</span><strong>{money(tender.value)}</strong></div><div><span>Rok za oddajo</span><strong>{date(tender.deadline, { day: 'numeric', month: 'short' })}{tender.status === 'open' && days !== null && <small className={days <= 14 ? 'urgent' : ''}>{days >= 0 ? `še ${days} dni` : 'rok je potekel'}</small>}</strong></div></div><a className="card-detail-link" href={`#/razpisi/${tender.id}`}>Poglej razpis<ArrowRight size={16}/></a></div>
  </article>;
}
function TenderDetail({ id, data, refresh, notify, goChat }: Shared & {
    id: string;
    goChat: (ids: string[]) => void;
}) {
    const [tender, setTender] = useState<Tender | null>(data.tenders.find(t => t.id === id) || null);
    const [error, setError] = useState('');
    const [tab, setTab] = useState('overview');
    const [busy, setBusy] = useState('');
    const [checklist, setChecklist] = useState(false);
    const fileRef = useRef<HTMLInputElement>(null);
    useEffect(() => { let active = true; api<Tender>(`/tenders/${encodeURIComponent(id)}`).then(t => { if (active) {
        setTender(t);
        setError('');
    } }).catch(e => { if (active)
        setError(e.message); }); return () => { active = false; }; }, [id, data.tenders]);
    useEffect(() => { setTab(window.location.hash.includes('tab=changes') ? 'changes' : 'overview'); setChecklist(false); }, [id]);
    const act = async (kind: string, callback: () => Promise<void>) => { setBusy(kind); try {
        await callback();
    }
    catch (e) {
        notify((e as Error).message, true);
    }
    finally {
        setBusy('');
    } };
    if (error)
        return <EmptyState title="Razpisa ni mogoče odpreti." action={<a className="button" href="#/razpisi">Nazaj na razpise</a>}>{error}</EmptyState>;
    if (!tender)
        return <div className="page-loading"><Spinner /><p>Nalagamo podrobnosti …</p></div>;
    const conditions = tender.match.conditions;
    const missing = conditions.filter(c => c.status !== 'met');
    const days = daysLeft(tender.deadline, data.meta.today);
    const follow = () => act('follow', async () => { await post(`/tenders/${id}/follow`, { following: !tender.following }); await refresh(); notify(tender.following ? 'Spremljanje je izključeno.' : 'Spremljanje je vključeno. Obvestili vas bomo o spremembah.'); });
    const analyze = () => act('analyze', async () => { const result = await post<Tender & {
        analysis?: {
            mode: string;
            message: string;
        }[];
        message?: string;
    }>(`/tenders/${id}/analyze`); setTender(result); await refresh(); notify(result.analysis?.map(item => item.message).filter(Boolean).join(' ') || result.message || 'Analiza je osvežena. Preverite pogoje in navedene vire.'); });
    const upload = (file: File) => act('upload', async () => { const form = new FormData(); form.append('file', file); const result = await api<{
        status: string;
        message?: string;
        analysis?: {
            mode: string;
            message: string;
        };
        error?: string;
    }>(`/tenders/${id}/documents`, { method: 'POST', body: form }); await refresh(); notify(result.analysis?.message || result.error || result.message || (result.status === 'processed' ? 'Besedilo dokumenta je pripravljeno za analizo.' : 'Dokument je shranjen, vendar zahteva dodatno obdelavo.')); if (fileRef.current)
        fileRef.current.value = ''; });
    return <>
    <a className="back-link" href="#/razpisi"><ArrowLeft size={16}/>Nazaj na razpise</a>
    <div className="detail-header"><div><div className="card-tags"><Badge>{labels[tender.kind]}</Badge><Badge tone={tender.status === 'open' ? 'green' : 'neutral'}>{labels[tender.status]}</Badge>{tender.source_type === 'demo' && <span className="demo-tag">DEMO RAZPIS</span>}<span className="detail-version">Različica {tender.version}</span></div><h1>{tender.title}</h1><div className="tender-buyer"><Building2 size={15}/>{tender.buyer}<i /><MapPin size={15}/>{tender.region}</div></div><button className={`button ${tender.following ? 'following' : ''}`} disabled={!!busy} onClick={follow}>{busy === 'follow' ? <Spinner small/> : <Bookmark size={17} fill={tender.following ? 'currentColor' : 'none'}/>}{tender.following ? 'Spremljam razpis' : 'Spremljaj razpis'}</button></div>
    {tender.source_type === 'demo' && <div className="demo-banner"><FlaskConical size={15}/><span>Prikaz na izmišljenem primeru. Pogoji, vrednosti in podatki podjetja so namenjeni demonstraciji.</span></div>}
    <div className="detail-metrics"><div><Coins size={18}/><span>Ocenjena vrednost<strong>{money(tender.value)}</strong></span></div><div><CalendarDays size={18}/><span>Rok za oddajo<strong>{date(tender.deadline)}{tender.status === 'open' && days != null && <small>{days >= 0 ? `še ${days} dni` : 'rok je potekel'}</small>}</strong></span></div><div><Clock3 size={18}/><span>Objavljeno<strong>{date(tender.published_at)}</strong></span></div><div><FileText size={18}/><span>Dokumentacija<strong>{tender.documents.length} {tender.documents.length === 1 ? 'dokument' : 'dokumenti'}</strong></span></div></div>
    <div className="detail-layout"><div className="detail-main"><div className="tabs detail-tabs">{[['overview', 'Pregled'], ['conditions', `Pogoji (${conditions.length})`], ['documents', 'Dokumenti'], ['changes', 'Spremembe']].map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}{key === 'changes' && tender.changes.length > 0 && <span>{tender.changes.length}</span>}</button>)}</div>
      {tab === 'overview' && <><section className="surface detail-section"><div className="section-heading"><h2><FileText size={19}/>Kaj naročnik potrebuje?</h2><Badge tone="purple">Povzetek</Badge></div><p className="detail-summary">{tender.summary}</p>{tender.description && tender.description !== tender.summary && <p className="muted prose">{tender.description}</p>}<div className="topic-tags">{tender.topics.map(topic => <span key={topic}>{topic}</span>)}</div><div className="cpv-line"><span>CPV</span>{tender.cpv.map(code => <code key={code}>{code}</code>)}</div></section><section className="surface detail-section"><div className="section-heading"><h2><Sparkles size={19}/>Zakaj je zanimiv za vas?</h2></div><div className="reason-list">{tender.match.reasons.map((reason, index) => <div key={index}><span><Check size={15}/></span><p>{reason}</p></div>)}</div>{tender.match.open_question && <div className="info-box amber"><CircleHelp size={18}/><p>{tender.match.open_question}</p></div>}</section>{tender.lots.length > 0 && <section className="surface detail-section"><h2><LayoutGrid size={19}/>Ujemanje po sklopih</h2>{tender.lots.map(lot => <div className="lot-card" key={lot.id}><div><h3>{lot.title}</h3><MatchBadge level={lot.match_level}/></div><p>{lot.summary}</p></div>)}</section>}<section className="surface detail-section"><div className="section-heading"><h2><ShieldCheck size={19}/>Pogoji na enem mestu</h2><button className="text-link" onClick={() => setTab('conditions')}>Vsi pogoji <ArrowRight size={14}/></button></div><div className="condition-summary">{(['met', 'unknown', 'unmet'] as const).map(status => <div key={status}><strong>{conditions.filter(c => c.status === status).length}</strong><StateBadge status={status}/></div>)}</div><p className="section-help">Prikaz velja za pogoje, izluščene iz obdelane dokumentacije.</p></section></>}
      {tab === 'conditions' && <section className="surface detail-section"><div className="section-heading"><div><h2>Ali izpolnjujete pogoje?</h2><p className="section-help">Vsaka ugotovitev je povezana s podatkom v profilu in dokazom.</p></div><button className="button small" disabled={!!busy} onClick={analyze}>{busy === 'analyze' ? <Spinner small/> : <RefreshCw size={14}/>}Osveži analizo</button></div>{conditions.length ? <div className="conditions-table"><div className="conditions-header"><span>Pogoj iz dokumentacije</span><span>Vaše podjetje</span><span>Ugotovitev</span></div>{conditions.map(condition => <div className="condition-row" key={condition.id}><div><strong>{condition.title}</strong>{condition.document_id && condition.page && <a target="_blank" rel="noreferrer" href={`/api/documents/${condition.document_id}#page=${condition.page}`}><FileText size={12}/>Dokument, str. {condition.page}<ArrowUpRight size={12}/></a>}{condition.quote && <details className="evidence-quote"><summary>Poglej izvorno besedilo</summary><blockquote>»{condition.quote}«</blockquote></details>}</div><div>{condition.company_value || 'Podatek še ni na voljo'}</div><div><StateBadge status={condition.status}/></div></div>)}</div> : <EmptyState title="Pogoji še niso analizirani." icon={<FileText size={25}/>}>Dodajte besedilni PDF in zaženite analizo. Nepreverjeni pogoji se ne štejejo kot izpolnjeni.</EmptyState>}<a href="#/profil" className="profile-callout"><Building2 size={19}/><div><strong>Manjka podatek o vašem podjetju?</strong><span>Dopolnite reference ali zmogljivosti in ponovno preverite ujemanje.</span></div><ArrowRight size={18}/></a></section>}
      {tab === 'documents' && <section className="surface detail-section"><div className="section-heading"><div><h2>Razpisna dokumentacija</h2><p className="section-help">Izvorne datoteke, iz katerih izhajajo ugotovitve.</p></div><button className="button small" disabled={!!busy} onClick={() => fileRef.current?.click()}>{busy === 'upload' ? <Spinner small/> : <Upload size={15}/>}Dodaj PDF</button><input ref={fileRef} type="file" accept=".pdf,application/pdf" className="sr-only" aria-label="Naloži PDF dokumentacijo" onChange={e => { const file = e.target.files?.[0]; if (file)
        upload(file); }}/></div>{tender.documents.length ? <div className="documents-list">{tender.documents.map(doc => <div className="document-row" key={doc.id}><div className="pdf-icon"><FileText size={23}/><small>PDF</small></div><div><strong>{doc.title}</strong><span>{doc.pages || '—'} strani · Različica {doc.version}</span><Badge tone={doc.status === 'processed' ? 'green' : 'amber'}>{doc.status === 'processed' ? 'Besedilo obdelano' : 'Potrebna dodatna obdelava'}</Badge></div><a className="button small" target="_blank" rel="noreferrer" href={doc.url || `/api/documents/${doc.id}`}><Eye size={15}/>Odpri</a></div>)}</div> : <EmptyState title="Dokumentov še ni." icon={<FileText size={25}/>}>Naložite besedilni PDF. Skenirani dokumenti se označijo za dodatno obdelavo.</EmptyState>}<div className="info-box"><CircleHelp size={17}/><p>Uvoz besedila in analiza pogojev sta ločena koraka. Po dodajanju dokumenta osvežite analizo na zavihku Pogoji.</p></div></section>}
      {tab === 'changes' && <section className="surface detail-section"><div className="section-heading"><div><h2>Kaj se je spremenilo?</h2><p className="section-help">Spremembe in njihov vpliv na odločitev za prijavo.</p></div><Badge>Različica {tender.version}</Badge></div>{tender.changes.length ? tender.changes.map((change, i) => <div className="change-card" key={i}><h3>{change.field}</h3><div className="change-comparison"><div><span>PREJ</span><p>{change.before}</p></div><ArrowRight size={18}/><div><span>ZDAJ</span><p>{change.after}</p></div></div><div className="change-impact"><AlertCircle size={16}/><p>{change.impact}</p></div>{change.document_id && <a className="text-link" href={`/api/documents/${change.document_id}#page=${change.page || 1}`} target="_blank" rel="noreferrer">Odpri popravek, str. {change.page || 1}<ExternalLink size={13}/></a>}</div>) : <EmptyState title="Za zdaj brez sprememb." icon={<CheckCircle2 size={26}/>}>Vključite spremljanje in obvestili vas bomo, ko se spremenijo pogoji ali roki.</EmptyState>}</section>}
      {tab !== 'changes' && tender.criteria.length > 0 && <section className="surface detail-section"><div className="section-heading"><h2><Coins size={19}/>Merila za izbor</h2><span className="muted small-text">Ločeno od pogojev sodelovanja</span></div><div className="criteria-list">{tender.criteria.map((criterion, i) => <div key={i}><div><span>{criterion.title}</span><strong>{criterion.weight} %</strong></div><div className="progress-track"><span style={{ width: `${Math.max(0, Math.min(100, criterion.weight))}%` }}/></div></div>)}</div></section>}
    </div><aside className="detail-aside"><section className="decision-card"><div className="decision-label"><Sparkles size={17}/>VAŠE UJEMANJE</div><div className={`match-score ${tender.match.level}`}><strong>{Math.round(tender.match.score)}</strong><span>/ 100</span></div><MatchBadge level={tender.match.level}/><p className="score-explanation">Ocena vsebinskega ujemanja s profilom podjetja.</p><div className="decision-divider"/><strong className="recommendation-title">{labels[tender.match.recommendation]}</strong><p>{tender.status !== 'open' ? 'Razpis ni odprt za nove prijave.' : missing.length ? `${missing.length} ${missing.length === 1 ? 'pogoj potrebuje' : 'pogoji potrebujejo'} dodatno pozornost.` : 'Med obdelanimi pogoji ni zaznanih odprtih vprašanj.'}</p><button className="button primary full-width" onClick={() => goChat([tender.id])}><Sparkles size={16}/>Pogovor o razpisu</button><button className="button full-width" onClick={() => setChecklist(!checklist)}><CheckCheck size={16}/>Kaj še preveriti?</button>{checklist && <div className="checklist"><strong>Pred naslednjim korakom</strong>{(missing.length ? missing.map(c => c.title) : ['Preverite celotno izvorno dokumentacijo.', 'Potrdite razpoložljivost ekipe in reference.', 'Preverite rok in način oddaje ponudbe.']).map((text, i) => <label key={i}><input type="checkbox"/><span>{text}</span></label>)}</div>}</section><section className="source-card"><h4><Link2 size={15}/>Izvor podatkov</h4><p>{tender.source_type === 'demo' ? 'Pripravljen demo primer z izmišljeno dokumentacijo.' : 'Javne informacije Slovenije – portal javnih naročil'}</p>{tender.source_url && <a href={tender.source_url} target="_blank" rel="noreferrer">Odpri izvorno objavo<ExternalLink size={13}/></a>}<small>Neznan podatek ni izpolnjen pogoj.</small></section></aside></div>
  </>;
}
function ProfilePage({ data, refresh, notify }: Shared) {
    const [draft, setDraft] = useState<Profile>(() => structuredClone(data.profile));
    const [busy, setBusy] = useState(false);
    const [prefillBusy, setPrefillBusy] = useState(false);
    const [query, setQuery] = useState('');
    const [prefill, setPrefill] = useState<{
        profile: Profile;
        source: string;
        message: string;
    } | null>(null);
    useEffect(() => setDraft(structuredClone(data.profile)), [data.profile]);
    const set = <K extends keyof Profile>(key: K, value: Profile[K]) => setDraft(old => ({ ...old, [key]: value }));
    const setRef = (index: number, patch: Partial<CompanyReference>) => setDraft(old => ({ ...old, references: old.references.map((ref, i) => i === index ? { ...ref, ...patch } : ref) }));
    const filled = [draft.name, draft.description, draft.expertise.length, draft.technologies.length, draft.staff_count != null, draft.references.length > 0 && draft.references.every(r => r.confirmed && r.value != null && r.year != null), draft.capacity, draft.regions.length].filter(Boolean).length;
    const completeness = Math.round(filled / 8 * 100);
    const save = async (e: FormEvent) => { e.preventDefault(); setBusy(true); try {
        await api('/profile', { method: 'PUT', body: JSON.stringify({ ...draft, source: 'user' }) });
        await refresh();
        notify('Profil je shranjen. Priporočila so ponovno izračunana.');
    }
    catch (e) {
        notify((e as Error).message, true);
    }
    finally {
        setBusy(false);
    } };
    const loadPrefill = async () => { setPrefillBusy(true); try {
        setPrefill(await post('/profile/prefill', { query: query || draft.name }));
    }
    catch (e) {
        notify((e as Error).message, true);
    }
    finally {
        setPrefillBusy(false);
    } };
    return <><div className="page-heading"><div><div className="eyebrow">TEMELJ DOBRIH PRIPOROČIL</div><h1>Vaše podjetje, v pravem kontekstu<span className="accent-dot">.</span></h1><p>Povejte nam, kaj znate, kaj iščete in kje ste najmočnejši.</p></div><Badge tone="purple"><Building2 size={13}/>Profil podjetja</Badge></div><div className="profile-layout"><form className="profile-form" onSubmit={save}><section className="surface profile-section"><div className="section-heading"><h2><span className="step-number">1</span>Osnovni podatki</h2><Badge tone="amber">Demo podjetje</Badge></div><div className="prefill-box"><div><Building2 size={19}/><div><strong>Začnite z obstoječimi podatki</strong><p>Predizpolnite profil in nato preverite, kaj želite shraniti.</p></div></div><div className="prefill-search"><input aria-label="Poišči podjetje za predizpolnitev" placeholder="Naziv ali matična številka podjetja" value={query} onChange={e => setQuery(e.target.value)}/><button className="button small" type="button" disabled={prefillBusy} onClick={loadPrefill}>{prefillBusy ? <Spinner small/> : <Search size={15}/>}Poišči</button></div><small>Demo predizpolnitev · Pravi dostop Bizi se poveže z odobrenim API računom.</small></div><div className="form-grid"><Field label="Naziv podjetja"><input required value={draft.name} onChange={e => set('name', e.target.value)}/></Field><Field label="Matična številka"><input value={draft.registration_number} onChange={e => set('registration_number', e.target.value)}/></Field><Field label="Dejavnost"><input value={draft.activity} onChange={e => set('activity', e.target.value)}/></Field><Field label="Spletna stran"><input type="url" placeholder="https://" value={draft.website} onChange={e => set('website', e.target.value)}/></Field><Field label="Naslov" className="span-two"><input value={draft.address} onChange={e => set('address', e.target.value)}/></Field><Field label="Kaj vaše podjetje počne?" hint="Opišite storitve in probleme, ki jih rešujete. Konkretni primeri pomagajo pri vsebinskem ujemanju." className="span-two"><textarea rows={4} value={draft.description} onChange={e => set('description', e.target.value)}/></Field></div></section><section className="surface profile-section"><div className="section-heading"><h2><span className="step-number">2</span>Znanje in želene priložnosti</h2><Badge>Uporabniški vnos</Badge></div><div className="form-grid"><Field label="Strokovna področja" className="span-two"><ChipInput label="Strokovna področja" value={draft.expertise} onChange={v => set('expertise', v)} placeholder="Na primer: spletne aplikacije, IoT, energetika"/></Field><Field label="Tehnologije" className="span-two"><ChipInput label="Tehnologije" value={draft.technologies} onChange={v => set('technologies', v)}/></Field><Field label="Ključne besede"><ChipInput label="Ključne besede podjetja" value={draft.keywords} onChange={v => set('keywords', v)}/></Field><Field label="Kaj vas ne zanima?"><ChipInput label="Izključena področja podjetja" value={draft.excluded_keywords} onChange={v => set('excluded_keywords', v)} placeholder="Na primer: samo dobava licenc"/></Field><Field label="Lokacije izvedbe" className="span-two"><ChipInput label="Lokacije izvedbe" value={draft.regions} onChange={v => set('regions', v)}/></Field><Field label="Želena najmanjša vrednost (€)"><input type="number" min="0" value={draft.min_value ?? ''} onChange={e => set('min_value', e.target.value === '' ? null : Number(e.target.value))}/></Field><Field label="Želena največja vrednost (€)"><input type="number" min="0" value={draft.max_value ?? ''} onChange={e => set('max_value', e.target.value === '' ? null : Number(e.target.value))}/></Field></div></section><section className="surface profile-section" id="reference"><div className="section-heading"><div><h2><span className="step-number">3</span>Reference in izkušnje</h2><p className="section-help">Vrednost in leto zaključka omogočata preverjanje referenčnih pogojev.</p></div><button type="button" className="button small" onClick={() => set('references', [...draft.references, { id: `ref-${Date.now()}`, title: '', description: '', domain: '', value: null, year: null, confirmed: false }])}><Plus size={15}/>Dodaj referenco</button></div>{draft.references.map((ref, index) => <div className="reference-editor" key={ref.id}><div className="reference-title"><span><FileText size={16}/>Referenca {index + 1}</span><button type="button" className="icon-button danger-hover" aria-label={`Odstrani referenco ${index + 1}`} onClick={() => set('references', draft.references.filter((_, i) => i !== index))}><Trash2 size={16}/></button></div><div className="form-grid"><Field label="Ime projekta" className="span-two"><input value={ref.title} onChange={e => setRef(index, { title: e.target.value })}/></Field><Field label="Področje"><select value={ref.domain} onChange={e => setRef(index, { domain: e.target.value })}><option value="">Izberite področje</option><option value="energy">Energetika in IoT</option><option value="sport">Športne platforme</option><option value="satellite">Satelitski podatki</option><option value="software">Razvoj programske opreme</option><option value="construction">Gradbeništvo</option><option value="other">Drugo</option>{ref.domain && !['energy', 'sport', 'satellite', 'software', 'construction', 'other'].includes(ref.domain) && <option value={ref.domain}>{ref.domain}</option>}</select></Field><Field label="Leto zaključka"><input type="number" min="1900" max="2100" placeholder="Ni podatka" value={ref.year ?? ''} onChange={e => setRef(index, { year: e.target.value === '' ? null : Number(e.target.value) })}/></Field><Field label="Vrednost izvedenih del (€)" className="span-two"><input type="number" min="0" placeholder="Ni podatka" value={ref.value ?? ''} onChange={e => setRef(index, { value: e.target.value === '' ? null : Number(e.target.value) })}/></Field><Field label="Vaša vloga in opravljena dela" className="span-two"><textarea rows={2} value={ref.description} onChange={e => setRef(index, { description: e.target.value })}/></Field></div><label className="checkbox-row reference-confirm"><input type="checkbox" checked={ref.confirmed} onChange={e => setRef(index, { confirmed: e.target.checked })}/><span>Podatki o referenci so uporabniško potrjeni.</span></label>{(ref.value == null || ref.year == null) && <div className="reference-warning"><CircleHelp size={14}/>Dopolnite {ref.value == null && ref.year == null ? 'vrednost in leto' : ref.value == null ? 'vrednost' : 'leto'} reference za natančnejšo presojo.</div>}</div>)}</section><section className="surface profile-section"><div className="section-heading"><h2><span className="step-number">4</span>Ekipa in zmogljivosti</h2></div><div className="form-grid"><Field label="Število razpoložljivih strokovnjakov"><input type="number" min="0" placeholder="Ni podatka" value={draft.staff_count ?? ''} onChange={e => set('staff_count', e.target.value === '' ? null : Number(e.target.value))}/></Field><Field label="Razpoložljivi od"><input type="date" value={draft.available_from || ''} onChange={e => set('available_from', e.target.value)}/></Field><Field label="Certifikati in dokazila" className="span-two"><ChipInput label="Certifikati" value={draft.certifications} onChange={v => set('certifications', v)}/></Field><Field label="Dodatne informacije o kapacitetah" className="span-two"><textarea rows={3} value={draft.capacity} onChange={e => set('capacity', e.target.value)} placeholder="Na primer: vzporedno lahko izvedemo dva srednje velika projekta."/></Field></div></section><div className="profile-savebar"><div><ShieldCheck size={16}/><span>Spremembe se uporabijo po shranjevanju.</span></div><button className="button primary" disabled={busy}>{busy ? <Spinner small/> : <Save size={17}/>}Shrani in osveži priporočila</button></div></form><aside className="profile-aside"><section className="profile-completion"><div className="company-profile-icon"><Building2 size={29}/></div><h3>{draft.name || 'Vaše podjetje'}</h3><p>{draft.activity || 'Dopolnite svojo dejavnost'}</p><div className="completion-title"><span>Izpolnjenost profila</span><strong>{completeness} %</strong></div><div className="progress-track"><span style={{ width: `${completeness}%` }}/></div><p className="completion-help">Več preverjenih podatkov pomeni manj odprtih vprašanj.</p><div className="completion-checks">{[['Osnovni podatki', !!draft.name], ['Področja in tehnologije', !!draft.expertise.length && !!draft.technologies.length], ['Preverjene reference', draft.references.every(r => r.value != null && r.year != null && r.confirmed) && !!draft.references.length], ['Podatki o ekipi', draft.staff_count != null]].map(([label, complete]) => <div key={String(label)}>{complete ? <CheckCircle2 size={16}/> : <CircleHelp size={16}/>}<span>{label}</span></div>)}</div></section><div className="profile-tip"><Lightbulb size={21}/><h4>Opis naj pove več kot panoga.</h4><p>»Razvijamo platforme za zajem podatkov iz senzorjev« pove več kot »ukvarjamo se z informatiko«.</p></div><div className="source-card"><h4><FlaskConical size={15}/>O tem profilu</h4><p>Gre za izmišljeno podjetje. Predizpolnjene reference in zmogljivosti so demo podatki.</p><small>Vir zadnjega vnosa: {data.profile.source === 'demo' ? 'demo predloga' : 'uporabniška dopolnitev'}.</small></div></aside></div>{prefill && <Modal title="Preverite predizpolnjeni profil" description={prefill.message} close={() => setPrefill(null)}><Badge tone="amber">Demo predizpolnitev</Badge><div className="prefill-preview"><h3>{prefill.profile.name}</h3><p>{prefill.profile.activity}</p><p>{prefill.profile.address}</p><p>{prefill.profile.description}</p></div><div className="info-box"><CircleHelp size={17}/><p>Predloga bo zamenjala trenutni obrazec. V bazo se shrani šele z gumbom »Shrani in osveži priporočila«.</p></div><div className="modal-actions"><button className="button" onClick={() => setPrefill(null)}>Prekliči</button><button className="button primary" onClick={() => { setDraft(structuredClone(prefill.profile)); setPrefill(null); notify('Predloga je v obrazcu. Preverite podatke in jih shranite.'); }}><Check size={16}/>Uporabi predlogo</button></div></Modal>}</>;
}
function ChatPage({ data, refresh, notify, messages, setMessages, selection, setSelection, applyFilters }: Shared & {
    messages: ChatMessage[];
    setMessages: (messages: ChatMessage[] | ((old: ChatMessage[]) => ChatMessage[])) => void;
    selection: string[];
    setSelection: (ids: string[]) => void;
    applyFilters: (filters: Filters) => void;
}) {
    const [input, setInput] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [showContext, setShowContext] = useState(false);
    const [applyBusy, setApplyBusy] = useState('');
    const endRef = useRef<HTMLDivElement>(null);
    useEffect(() => { if (messages.length)
        endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [messages.length, busy]);
    const send = async (text: string) => { if (!text.trim() || busy)
        return; const userMessage: ChatMessage = { id: `user-${Date.now()}`, role: 'user', content: text }; setMessages(old => [...old, userMessage]); setInput(''); setBusy(true); setError(''); try {
        const response = await post<ChatResponse>('/chat', { message: text, tender_ids: selection, history: messages.slice(-12).map(({ role, content }) => ({ role, content })) });
        setMessages(old => [...old, { ...response, id: `assistant-${Date.now()}`, role: 'assistant', content: response.answer }]);
    }
    catch (e) {
        setError((e as Error).message);
    }
    finally {
        setBusy(false);
    } };
    const applyProfile = async (message: ChatMessage) => { if (!message.profile_patch)
        return; setApplyBusy(message.id); try {
        await api('/profile', { method: 'PUT', body: JSON.stringify({ ...data.profile, ...message.profile_patch, source: 'user' }) });
        await refresh();
        setMessages(old => old.map(m => m.id === message.id ? { ...m, applied: true } : m));
        notify('Dopolnitev profilu je shranjena in priporočila so osvežena.');
    }
    catch (e) {
        notify((e as Error).message, true);
    }
    finally {
        setApplyBusy('');
    } };
    const questions = ['Kateri trije razpisi so najbolj zanimivi za nas?', 'Katere reference moramo dopolniti?', 'Primerjaj razpisa za IoT in športno platformo.', 'Razvijamo tudi rešitve za spremljanje senzorjev. Posodobi predlog profila.'];
    return <><div className="page-heading"><div><div className="eyebrow">VAŠ PARTNER PRI ODLOČANJU</div><h1>Vprašajte. Raziščite. Odločite se<span className="accent-dot">.</span></h1><p>Pogovor, ki pozna vaše podjetje in navaja svoje vire.</p></div><Badge tone={data.meta.ai_mode === 'live' ? 'green' : 'amber'}><span className="tiny-dot"/>{data.meta.ai_mode === 'live' ? 'AI je povezan' : 'Demo način'}</Badge></div><div className="chat-layout"><section className="chat-panel surface"><div className="chat-panel-header"><div className="assistant-avatar"><Sparkles size={20}/></div><div><strong>Razpisni svetovalec</strong><span>Profil podjetja + obdelana dokumentacija</span></div><button className="button ghost small" onClick={() => setShowContext(!showContext)}><SlidersHorizontal size={15}/>Kontekst{selection.length > 0 && <b>{selection.length}</b>}</button></div>{showContext && <div className="chat-context"><div><strong>Razpisi za pogovor</strong><button className="text-link" onClick={() => setSelection([])}>Počisti izbor</button></div><p>Brez izbora svetovalec uporabi vse razpise. Za primerjavo izberite dva.</p>{data.tenders.map(t => <label className="checkbox-row" key={t.id}><input type="checkbox" checked={selection.includes(t.id)} onChange={e => setSelection(e.target.checked ? [...selection, t.id] : selection.filter(id => id !== t.id))}/><span>{t.title}</span></label>)}</div>}{selection.length > 0 && <div className="selected-context"><Link2 size={13}/>{selection.map(id => <span key={id}>{data.tenders.find(t => t.id === id)?.title || id}<button aria-label="Odstrani iz konteksta" onClick={() => setSelection(selection.filter(x => x !== id))}><X size={12}/></button></span>)}</div>}<div className={`chat-messages ${messages.length ? 'has-messages' : ''}`}>{!messages.length && <div className="chat-welcome"><div className="chat-orbit"><Sparkles size={33}/><i /><i /><i /></div><span className="eyebrow">PRAVA VPRAŠANJA. JASNEJŠE ODLOČITVE.</span><h2>Katera priložnost je prava za vas?</h2><p>Pomagam razumeti razpise, primerjati pogoje in odkriti, kaj je treba še preveriti.</p><div className="chat-suggestions">{questions.slice(0, 3).map((q, i) => <button key={q} onClick={() => send(q)}>{i === 0 ? <Radar size={17}/> : i === 1 ? <FileText size={17}/> : <LayoutGrid size={17}/>}<span>{q}</span><ArrowUpRight size={15}/></button>)}</div></div>}{messages.map(message => <div className={`chat-message ${message.role}`} key={message.id}><div className={message.role === 'assistant' ? 'assistant-avatar' : 'user-chat-avatar'}>{message.role === 'assistant' ? <Sparkles size={18}/> : 'VI'}</div><div className="message-content"><div className="message-author">{message.role === 'assistant' ? 'Razpisni svetovalec' : 'Vi'}{message.role === 'assistant' && <span className={`message-mode ${message.mode === 'live' ? 'live' : ''}`}>{message.mode === 'live' ? 'AI analiza' : 'Demo odgovor'}</span>}</div><div className="message-text"><AnswerText text={message.content}/></div>{message.warning && <div className="chat-warning"><AlertCircle size={14}/>{message.warning}</div>}{!!message.citations?.length && <div className="message-citations"><span>VIRI IN PODROBNOSTI</span>{message.citations.map((citation, i) => <div className="citation-item" key={i}><a href={`#/razpisi/${citation.tender_id}`}><span>{i + 1}</span>{citation.title}<ArrowUpRight size={13}/></a>{citation.document_id && <a className="document-citation" href={`/api/documents/${citation.document_id}#page=${citation.page || 1}`} target="_blank" rel="noreferrer"><FileText size={12}/>Dokument, str. {citation.page || 1}</a>}{citation.quote && <blockquote>»{citation.quote}«</blockquote>}</div>)}</div>}{message.profile_patch && <div className="chat-proposal"><div><Building2 size={17}/><strong>Predlog dopolnitve profila</strong></div><div className="proposal-tags">{Object.entries(message.profile_patch).map(([key, value]) => <span key={key}>{({ technologies: 'Tehnologije', expertise: 'Strokovna področja', keywords: 'Ključne besede', description: 'Opis' } as Record<string, string>)[key] || key}: {Array.isArray(value) ? value.map(v => typeof v === 'object' ? JSON.stringify(v) : v).join(', ') : String(value)}</span>)}</div><button className="button primary small" disabled={message.applied || applyBusy === message.id} onClick={() => applyProfile(message)}>{applyBusy === message.id ? <Spinner small/> : <Check size={14}/>}{message.applied ? 'Shranjeno v profil' : 'Potrdi in shrani'}</button></div>}{message.filters && <div className="chat-proposal"><div><SlidersHorizontal size={17}/><strong>Predlog filtrov</strong></div><div className="proposal-tags">{Object.entries(message.filters).map(([k, v]) => <span key={k}>{filterLabel(k)}: {Array.isArray(v) ? v.join(', ') : String(v)}</span>)}</div><button className="button primary small" onClick={() => applyFilters(message.filters!)}>Uporabi in prikaži razpise<ArrowRight size={14}/></button></div>}</div></div>)}{busy && <div className="chat-message assistant"><div className="assistant-avatar"><Sparkles size={18}/></div><div className="thinking"><span /><span /><span /><small>Preverjam profil in dokumentacijo …</small></div></div>}{error && <div className="error-banner"><AlertCircle size={18}/><p>{error} Poskusite znova.</p></div>}<div ref={endRef}/></div><form className="chat-compose" onSubmit={e => { e.preventDefault(); send(input); }}><div><textarea aria-label="Sporočilo svetovalcu" placeholder="Vprašajte o razpisu ali opišite, kaj iščete …" rows={2} value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        send(input);
    } }}/><button className="send-button" disabled={busy || !input.trim()} aria-label="Pošlji sporočilo">{busy ? <Spinner small/> : <ArrowUpRight size={21}/>}</button></div><small><ShieldCheck size={12}/>Odgovori temeljijo na razpoložljivih virih. Vedno preverite izvorne pogoje.<span>Enter za pošiljanje</span></small></form></section><aside className="chat-aside"><div className="surface context-profile"><div className="section-heading"><h3><Building2 size={17}/>Kontekst podjetja</h3><a href="#/profil" className="icon-button" aria-label="Uredi profil"><ArrowUpRight size={16}/></a></div><strong>{data.profile.name}</strong><p>{data.profile.description}</p><div className="topic-tags">{data.profile.expertise.slice(0, 4).map(t => <span key={t}>{t}</span>)}</div><div className="context-facts"><span><FileText size={14}/>{data.profile.references.length} reference</span><span><CheckCircle2 size={14}/>{data.profile.staff_count ?? '—'} strokovnjakov</span></div><Badge tone="amber">Demo podatki</Badge></div><div className="chat-guide"><Lightbulb size={22}/><h3>Začnite s konkretnim vprašanjem.</h3><p>»Ali imamo dovolj referenc za ta razpis?« je dober začetek. Svetovalec pokaže tudi, katere informacije manjkajo.</p><button onClick={() => send(questions[3])}>Pomagaj dopolniti profil<ArrowUpRight size={14}/></button></div><div className="chat-mode-info"><ShieldCheck size={17}/><p>{data.meta.ai_mode === 'live' ? 'AI uporablja podatke iz vašega profila in obdelanih dokumentov.' : 'Brez API ključa so na voljo pripravljeni odgovori nad demo podatki. Ne gre za odgovor zunanjega jezikovnega modela.'}</p></div></aside></div></>;
}
function AnswerText({ text }: {
    text: string;
}) { return <>{text.split('\n').map((line, index) => { if (!line.trim())
    return <div className="message-spacer" key={index}/>; const parts = line.replace(/^#{1,4}\s*/, '').split(/(\*\*.*?\*\*)/g); return <p className={/^[-•]\s/.test(line) ? 'answer-list-line' : ''} key={index}>{parts.map((part, i) => part.startsWith('**') && part.endsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : part)}</p>; })}</>; }
function NotificationsPage({ data, refresh, notify }: Shared) {
    const [tab, setTab] = useState('all');
    const [busy, setBusy] = useState(false);
    const notifications = data.notifications.filter(n => tab === 'all' || !n.read);
    const unread = data.notifications.filter(n => !n.read).length;
    const read = async (id?: number, tenderId?: string, openChanges = false) => { setBusy(true); try {
        await post('/notifications/read', id === undefined ? {} : { id });
        await refresh();
        if (tenderId)
            navigate(`/razpisi/${tenderId}${openChanges ? '?tab=changes' : ''}`);
    }
    catch (e) {
        notify((e as Error).message, true);
    }
    finally {
        setBusy(false);
    } };
    return <><div className="page-heading"><div><div className="eyebrow">NIČ POMEMBNEGA NE UIDE</div><h1>Vedno korak pred spremembami<span className="accent-dot">.</span></h1><p>Nove priložnosti in popravki, ki vplivajo na vaše odločitve.</p></div><button className="button" disabled={busy || !unread} onClick={() => read()}>{busy ? <Spinner small/> : <CheckCheck size={17}/>}Označi vse kot prebrano</button></div><div className="notification-overview"><div className="notification-overview-icon"><Bell size={25}/></div><div><strong>{unread ? `${unread} ${unread === 1 ? 'obvestilo čaka' : 'obvestila čakajo'} na vaš pregled` : 'Vse ste pregledali.'}</strong><p>Spremljamo nove objave, referenčne pogoje in pomembne roke.</p></div><Badge tone="purple">Obvestila v aplikaciji</Badge></div><div className="tabs notification-tabs"><button className={tab === 'all' ? 'active' : ''} onClick={() => setTab('all')}>Vsa obvestila<span>{data.notifications.length}</span></button><button className={tab === 'unread' ? 'active' : ''} onClick={() => setTab('unread')}>Neprebrana<span>{unread}</span></button></div><div className="notification-layout"><section className="notifications-list">{notifications.length ? notifications.map(notification => <article className={`notification-card ${notification.read ? 'read' : 'unread'}`} key={notification.id}><div className={`notification-type-icon ${notification.type}`}>{notification.type === 'new' ? <Sparkles size={21}/> : notification.type === 'deadline' ? <CalendarDays size={21}/> : <FileText size={21}/>}</div><div className="notification-content"><div className="notification-meta"><Badge tone={notification.type === 'new' ? 'green' : notification.type === 'deadline' ? 'blue' : 'amber'}>{labels[notification.type]}</Badge>{notification.is_demo && <span className="demo-tag">DEMO DOGODEK</span>}<time>{date(notification.created_at, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</time></div><h3>{notification.title}</h3><p>{notification.body}</p><div className="notification-actions"><button className="text-link" disabled={busy} onClick={() => read(notification.id, notification.tender_id, notification.type !== 'new')}>Poglej razpis in spremembe<ArrowRight size={14}/></button>{!notification.read && <button className="subtle-link" disabled={busy} onClick={() => read(notification.id)}><Check size={14}/>Označi kot prebrano</button>}</div></div>{!notification.read && <span className="unread-dot"/>}</article>) : <EmptyState icon={<CheckCheck size={28}/>} title={tab === 'unread' ? 'Vse pomembno ste že pregledali.' : 'Vaš radar je pripravljen.'}>Ko prispe nova relevantna objava ali se spremeni spremljan razpis, boste obvestilo našli tukaj. Demo dogodek lahko sprožite v zgornjem meniju.</EmptyState>}</section><aside className="notifications-aside"><div className="surface"><h3><Radar size={20}/>Kaj spremljamo za vas?</h3><div><Sparkles size={17}/><p><strong>Nove priložnosti</strong>Razpisi, ki se ujemajo z vašim profilom.</p></div><div><FileText size={17}/><p><strong>Spremembe pogojev</strong>Popravki in njihov vpliv na primernost.</p></div><div><CalendarDays size={17}/><p><strong>Pomembne roke</strong>Podaljšanja ali spremembe roka prijave.</p></div><a href="#/razpisi" className="button full-width">Poišči razpise<ArrowRight size={15}/></a></div><p className="notification-hint"><CircleHelp size={15}/>Spremljani razpisi ostanejo na radarju tudi, če po popravku niso več primerni.</p></aside></div></>;
}
function OtherCpvCodes({ values, onChange }: {
    values: string[];
    onChange: (values: string[]) => void;
}) {
    const key = values.filter(code => !cpvOptions.some(([known]) => known === code)).join(', ');
    const [draft, setDraft] = useState(key);
    useEffect(() => setDraft(key), [key]);
    const apply = () => onChange([...values.filter(code => cpvOptions.some(([known]) => known === code)), ...draft.split(',').map(code => code.trim()).filter(Boolean)]);
    return <Field label="Druge CPV kode" hint="Kode ali predpone, ločene z vejico. Potrdite z Enter."><input aria-label="Druge CPV kode" placeholder="Na primer 4521, 73000000" value={draft} onChange={event => setDraft(event.target.value)} onBlur={apply} onKeyDown={event => { if (event.key === 'Enter') {
        event.preventDefault();
        apply();
    } }}/></Field>;
}
