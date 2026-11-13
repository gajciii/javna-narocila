import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Radar, Users, LayoutGrid, Sparkles, Building2, Search, SlidersHorizontal, ArrowUpRight, ArrowRight, Globe, Pencil, ChevronDown, Check, Plus, X, Bookmark, CalendarDays, MapPin, CircleHelp, CheckCircle2, AlertCircle, FileText, ExternalLink, RefreshCw, LoaderCircle, Menu, ArrowLeft, Save, Trash2, Link2, ShieldCheck, Eye, EyeOff, Coins, ArrowDownUp, UserRound, Hash, LogOut } from 'lucide-react';
import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query';
import { api, post, filterQuery } from './api';
import { queryClient, queryKeys } from './queryClient';
import CompanySearch from './CompanySearch';
import CompanyDataSources from './CompanyDataSources';
import CertificationSelect from './CertificationSelect';
import { PartnersPanel, PartnerManager } from './Partners';
import NotificationsPage from './NotificationsPage';
import AccountPage from './AccountPage';
import WebsiteImport, { type WebsitePatch } from './WebsiteImport';
import SubmissionReview from './SubmissionReview';
import PastAwardsPanel from './PastAwards';
import BuyerHistoryPanel from './BuyerHistory';
import IncumbentsPanel from './Incumbents';
import ExpectedTendersPage from './ExpectedTenders';
import AwardReferencesPanel from './AwardReferences';
import AttachmentOpportunities from './AttachmentOpportunities';
import TenderOverview from './TenderOverview';
import PipelineAdmin from './PipelineAdmin';
import { track } from './analytics';
import type { Bootstrap, TenderList, Filters, KeywordMatch, Profile, Tender, Notification, MatchLevel, ConditionState, CompanyReference, TenderCondition } from './types';
const money = (value: number | null | undefined) => value == null ? 'Ni podatka' : new Intl.NumberFormat('sl-SI', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(value);
const date = (value?: string | null, options?: Intl.DateTimeFormatOptions) => value && !Number.isNaN(new Date(value).getTime()) ? new Date(value).toLocaleDateString('sl-SI', { timeZone: 'Europe/Ljubljana', ...(options || { day: 'numeric', month: 'short', year: 'numeric' }) }) : 'Ni podatka';
const labels: Record<string, string> = { real: 'e-Naročanje', high: 'Visoko ujemanje', medium: 'Srednje ujemanje', low: 'Nizko ujemanje', met: 'Izpolnjen', unmet: 'Ni izpolnjen', unknown: 'Potrebna dopolnitev', services: 'Storitve', goods: 'Blago', works: 'Gradnje', open: 'Odprt', closed: 'Zaključen', cancelled: 'Ustavljen', unconfirmed: 'Stanje ni potrjeno', recommended: 'Priporočeno za pregled', review: 'Potrebno preveriti', unsuitable: 'Ni primerno', correction: 'Sprememba pogojev', deadline: 'Sprememba roka', new: 'Nova priložnost' };
const companyIdentity = (value: string) => { const compact = value.replace(/\s+/g, ''); return /^\d{7}$/.test(compact) ? `${compact}000` : compact; };
// Website suggestions apply on top of any company identity, so AJPES and website imports work in either order.
const mergeWebsite = <T extends WebsitePatch>(base: T, patch: WebsitePatch): T => ({ ...base, ...patch,
    expertise: [...new Set([...(base.expertise || []), ...(patch.expertise || [])])],
    technologies: [...new Set([...(base.technologies || []), ...(patch.technologies || [])])],
    keywords: [...new Set([...(base.keywords || []), ...(patch.keywords || [])])] });
const defaults: Filters = { view: 'recommended', sort: 'match', include_unknown: true };
const cpvOptions = [['72000000', 'IT storitve'], ['72230000', 'Razvoj po meri'], ['72262000', 'Programska oprema'], ['72316000', 'Analiza podatkov'], ['45000000', 'Gradbena dela'], ['48000000', 'Programski paketi']];
function navigate(path: string) { window.location.hash = path; }
function useRoute() { const [route, setRoute] = useState(window.location.hash.slice(1) || '/razpisi'); useEffect(() => { const update = () => { setRoute(window.location.hash.slice(1) || '/razpisi'); window.scrollTo(0, 0); }; window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update); }, []); return route; }
function Spinner({ small = false }: {
    small?: boolean;
}) { return <LoaderCircle size={small ? 16 : 22} className="spin" aria-label="Nalaganje"/>; }
function UserMenu({ username, initials, accountActive, signOut }: { username: string; initials: string; accountActive: boolean; signOut: () => Promise<void> }) {
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);
    useEffect(() => {
        if (!open) return;
        const away = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
        const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
        document.addEventListener('mousedown', away); document.addEventListener('keydown', key);
        return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', key); };
    }, [open]);
    return <div className="user-menu" ref={ref}>
        <button type="button" className="avatar user-menu-button" aria-haspopup="menu" aria-expanded={open} aria-label="Uporabniški meni" onClick={() => setOpen(!open)}>{initials}</button>
        {open && <div className="user-menu-panel" role="menu">
            <div className="user-menu-who"><span>Prijavljeni ste kot</span><strong>{username}</strong></div>
            <a role="menuitem" href="#/racun" className={accountActive ? 'active' : ''} onClick={() => setOpen(false)}><UserRound size={16}/>Profil</a>
            <button role="menuitem" type="button" onClick={() => { setOpen(false); void signOut(); }}><LogOut size={16}/>Odjava</button>
        </div>}
    </div>;
}
function Badge({ children, tone = 'neutral' }: {
    children: ReactNode;
    tone?: string;
}) { return <span className={`badge ${tone}`}>{children}</span>; }
function MatchBadge({ level, score }: {
    level: MatchLevel;
    score?: number;
}) { return <span className={`match-badge ${level}`}><span className="match-bars"><i /><i /><i /></span>{labels[level]}{score !== undefined && <b title="Ocena vsebinskega ujemanja, ne verjetnost uspeha">{Math.round(score)}</b>}</span>; }
type ConditionAnswerValue = 'met' | 'unmet' | null;
function ConditionAnswerControl({ item, busy, onAnswer }: {
    item: TenderCondition;
    busy: boolean;
    onAnswer: (item: TenderCondition, answer: ConditionAnswerValue) => void;
}) {
    const saved = item.profile_answer;
    // Clicking the active answer removes it, unless it was inherited from another tender; then it is confirmed here.
    const choose = (answer: 'met' | 'unmet') => onAnswer(item, saved?.answer === answer && !saved.inherited ? null : answer);
    return <div className="condition-answer">
        <div className="condition-answer-row"><span className="condition-answer-label">Ali izpolnjujete ta pogoj?</span><div className="condition-answer-buttons" role="group" aria-label={`Ali izpolnjujete pogoj: ${item.title}`}>
            <button type="button" className={`condition-answer-button met${saved?.answer === 'met' ? ' active' : ''}`} aria-pressed={saved?.answer === 'met'} disabled={busy} onClick={() => choose('met')}><Check size={14}/>Izpolnjujemo</button>
            <button type="button" className={`condition-answer-button unmet${saved?.answer === 'unmet' ? ' active' : ''}`} aria-pressed={saved?.answer === 'unmet'} disabled={busy} onClick={() => choose('unmet')}><X size={14}/>Ne izpolnjujemo</button>
            {busy && <Spinner small/>}
        </div></div>
        {saved && <p className="condition-answer-note">{saved.inherited
            ? <>Upoštevano iz profila podjetja: podoben pogoj ste označili pri razpisu <a href={`#/razpisi/${encodeURIComponent(saved.tender_id)}`}>{saved.tender_title || 'drugem razpisu'}</a>.</>
            : 'Shranjeno v profil podjetja. Upoštevamo ga tudi pri drugih razpisih s podobnim pogojem.'} <button type="button" className="condition-answer-remove" disabled={busy} onClick={() => onAnswer(item, null)}>Odstrani iz profila</button></p>}
    </div>;
}
function TenderConditionList({ data, answering, onAnswer }: {
    data?: Tender['tender_conditions'];
    /** Id of the condition whose answer is being saved. */
    answering?: string;
    onAnswer?: (item: TenderCondition, answer: ConditionAnswerValue) => void;
}) {
    if (!data || !data.items.length) {
        const message = data?.message || 'Pogoji bodo izluščeni ob indeksiranju dokumentacije.';
        return <EmptyState title="Pogoji razpisa še niso izluščeni." icon={<FileText size={25}/>}>{message} Z gumbom »Osveži analizo« jih lahko izluščite takoj.</EmptyState>;
    }
    const groups = data.items.reduce<Record<string, TenderCondition[]>>((all, item) => ({ ...all, [item.category_label]: [...(all[item.category_label] || []), item] }), {});
    return <div className="tender-condition-groups">{data.current === false && <div className="info-box amber"><CircleHelp size={18}/><p>Dokumentacija se je spremenila; pogoji bodo ob naslednjem indeksiranju posodobljeni.</p></div>}{Object.entries(groups).map(([label, items]) => <details key={label} className="tender-condition-group"><summary><h3>{label}<span>{items.length}</span></h3><ChevronDown size={18}/></summary>{items.map(item => <div className="tender-condition" key={item.id}><div className="tender-condition-head"><strong>{item.title}</strong>{item.status === 'manual' ? <span className="condition-state manual"><CircleHelp size={15}/>Preverite sami</span> : <StateBadge status={item.status} reason={item.profile_answer ? undefined : item.company_value}/>}</div>{item.requirement !== item.title && <p>{item.requirement}</p>}{item.auto_status !== 'manual' && item.company_value && <p className="tender-condition-company"><Building2 size={13}/>{item.company_value}</p>}<div className="tender-condition-source"><a target="_blank" rel="noreferrer" href={`/api/documents/${encodeURIComponent(item.document_id)}${item.page ? `#page=${item.page}` : ''}`}><FileText size={12}/>{item.document_title} · {item.page ? `str. ${item.page}` : item.locator}<ArrowUpRight size={12}/></a><details className="evidence-quote"><summary>Izvorno besedilo</summary><blockquote>»{item.quote}«</blockquote></details></div>{onAnswer && <ConditionAnswerControl item={item} busy={answering === item.id} onAnswer={onAnswer}/>}</div>)}</details>)}</div>;
}
function StateBadge({ status, reason }: {
    status: ConditionState;
    reason?: string;
}) {
    const tipId = useId();
    const Icon = status === 'met' ? CheckCircle2 : status === 'unmet' ? AlertCircle : CircleHelp;
    if (status !== 'unknown') return <span className={`condition-state ${status}`}><Icon size={15}/>{labels[status]}</span>;
    return <span className="condition-state unknown has-tooltip" tabIndex={0} aria-describedby={tipId}><Icon size={15}/>{labels[status]}<span role="tooltip" id={tipId} className="state-tooltip"><strong>Zakaj potrebna dopolnitev?</strong>S podatki v vašem profilu tega pogoja ne moremo niti potrditi niti zavrniti.{reason && <span className="state-tooltip-reason">{reason}</span>}<small>Dopolnite profil (reference, certifikate, kadre) ali preverite dokazila v dokumentaciji.</small></span></span>;
}
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
}) {
    const root = useRef<HTMLElement>(null);
    const onClose = useRef(close); onClose.current = close;
    useEffect(() => {
        const previous = document.activeElement as HTMLElement | null;
        const scroll = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        const focusable = () => Array.from(root.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex="0"]') || []).filter(el => el.getClientRects().length);
        (root.current?.querySelector<HTMLElement>('[autofocus]') || focusable()[0] || root.current)?.focus();
        const listener = (event: KeyboardEvent) => {
            if (event.key === 'Escape') { event.preventDefault(); onClose.current(); }
            if (event.key !== 'Tab') return;
            const elements = focusable(), first = elements[0], last = elements.at(-1);
            if (!first) { event.preventDefault(); root.current?.focus(); return; }
            if (!root.current?.contains(document.activeElement) || (!event.shiftKey && document.activeElement === last)) { event.preventDefault(); first.focus(); }
            else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        };
        document.addEventListener('keydown', listener);
        return () => { document.removeEventListener('keydown', listener); document.body.style.overflow = scroll; previous?.focus(); };
    }, []);
    return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) close(); }}><section ref={root} tabIndex={-1} className="modal" role="dialog" aria-modal="true" aria-label={title}><div className="modal-heading"><div><h2>{title}</h2>{description && <p>{description}</p>}</div><button className="icon-button" onClick={close} aria-label="Zapri okno"><X size={20}/></button></div>{children}</section></div>;
}
function Field({ label, hint, tag, tagTitle, filled, children, className = '' }: {
    label: string;
    hint?: string;
    tag?: string;
    tagTitle?: string;
    filled?: boolean;
    children: ReactNode;
    className?: string;
}) { return <label className={`field ${className}${filled ? ' is-filled' : ''}`}><span>{label}{tag && <em className="field-tag" title={tagTitle}>{tag}</em>}</span>{children}{hint && <small>{hint}</small>}</label>; }
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
const partnerOpportunity = (tender: Tender) => tender.status === 'open' && tender.match.level !== 'low' && tender.match.conditions.some(c => c.status !== 'met');

type Shared = {
    data: Bootstrap;
    refresh: () => Promise<void>;
    notify: (message: string, error?: boolean) => void;
};
const bootstrapQuery = queryOptions({ queryKey: queryKeys.bootstrap, queryFn: ({ signal }) => api<Bootstrap>('/bootstrap', { signal }) });
const tendersQuery = (query: string) => queryOptions({ queryKey: queryKeys.tenders(query), queryFn: ({ signal }) => api<TenderList>(`/tenders?${query}`, { signal }),
    // After a profile change the server scores relevance in the background; poll until it is done.
    refetchInterval: query => query.state.data?.relevance_pending ? 4000 : false });
/** A tender already loaded by any list query, shown while its detail loads. */
const listedTender = (id: string) => queryClient.getQueriesData<TenderList>({ queryKey: ['tenders'] })
    .flatMap(([, list]) => list?.results ?? []).find(t => t.id === id);
/** Put a profile returned by PUT /profile or POST /profiles into the workspace and refetch what depends on it. */
function applySavedProfile(saved: Profile) {
    const entry = { id: saved.id, name: saved.name, registration_number: saved.registration_number };
    queryClient.setQueryData<Bootstrap>(queryKeys.bootstrap, old => old && {
        ...old, profile: saved,
        profiles: old.profiles.some(p => p.id === saved.id) ? old.profiles.map(p => p.id === saved.id ? entry : p) : [...old.profiles, entry],
    });
    void queryClient.invalidateQueries({ predicate: query => query.queryKey[0] !== 'bootstrap' });
    // Improvement suggestions are recomputed on the server in the background.
    setTimeout(() => { void api<Notification[]>('/notifications').then(notifications => queryClient.setQueryData<Bootstrap>(queryKeys.bootstrap, old => old && { ...old, notifications })).catch(() => { }); }, 6000);
}
/** Put a profile whose condition answers changed into the workspace; tender lists and other tender details depend on them. */
function applyConditionAnswers(saved: Profile, currentTender?: string) {
    queryClient.setQueryData<Bootstrap>(queryKeys.bootstrap, old => old && { ...old, profile: saved });
    void queryClient.invalidateQueries({ predicate: query => query.queryKey[0] === 'tenders' || (query.queryKey[0] === 'tender' && query.queryKey[1] !== currentTender) });
}
/** Reload workspace data after a change. Tender lists, details and partner matches depend on it, so they are refetched too. */
async function refreshWorkspace() {
    await queryClient.cancelQueries({ predicate: query => query.queryKey[0] !== 'bootstrap' });
    await queryClient.invalidateQueries({ predicate: query => query.queryKey[0] !== 'bootstrap', refetchType: 'none' });
    await queryClient.fetchQuery({ ...bootstrapQuery, staleTime: 0 });
    await queryClient.invalidateQueries({ predicate: query => query.queryKey[0] !== 'bootstrap' });
}
export default function App({ user, signOut }: { user: { username: string; is_staff: boolean }; signOut: () => Promise<void> }) {
    const route = useRoute();
    const isAdministration = route.startsWith('/administracija');
    useEffect(() => {
        const page = route.split('?')[0];
        if (!isAdministration && !page.startsWith('/razpisi/') && !['/razpisi', '/profil', '/profil/uredi', '/obvestila', '/racun'].includes(page)) {
            window.location.replace('#/razpisi');
        }
    }, [route, isAdministration]);
    const bootstrap = useQuery({ ...bootstrapQuery, enabled: !isAdministration });
    const data = bootstrap.data ?? null;
    const error = bootstrap.isFetching ? '' : bootstrap.error?.message ?? '';
    const [toast, setToast] = useState<{
        message: string;
        error: boolean;
    } | null>(null);
    const [mobileNav, setMobileNav] = useState(false);
    const [filters, setFilters] = useState<Filters>(defaults);
    const [importOpen, setImportOpen] = useState(false);
    const refresh = refreshWorkspace;
    const notify = (message: string, isError = false) => { setToast({ message, error: isError }); };
    useEffect(() => { if (!toast)
        return; const timer = setTimeout(() => setToast(null), 5500); return () => clearTimeout(timer); }, [toast]);
    useEffect(() => { if (isAdministration) return; const timer = setInterval(() => { api<Notification[]>('/notifications').then(notifications => queryClient.setQueryData<Bootstrap>(queryKeys.bootstrap, old => old ? { ...old, notifications } : old)).catch(() => { }); }, 30000); return () => clearInterval(timer); }, [isAdministration]);
    useEffect(() => { setMobileNav(false); }, [route]);
    useEffect(() => {
        const closeMenus = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return;

            if (mobileNav) {
                setMobileNav(false);
                document.querySelector<HTMLButtonElement>('.mobile-menu')?.focus();
            }
        };
        window.addEventListener('keydown', closeMenus);
        return () => window.removeEventListener('keydown', closeMenus);
    }, [mobileNav]);
    if (isAdministration) return <div className="app-shell"><header className="topbar"><a className="brand topbar-brand" href="#/razpisi" aria-label="RazpIzi, razpisi"><Radar size={28} strokeWidth={1.8}/><span>Razp<span>Izi</span></span></a><div className="topbar-actions"><a className="button" href="#/razpisi"><ArrowLeft size={16}/>Razpisi</a></div></header><div className="workspace"><main className="main-content">{user.is_staff ? <PipelineAdmin/> : <p>Administracija je dostopna samo skrbnikom.</p>}</main></div></div>;
    if (!data)
        return <div className="boot-screen"><div className="boot-brand"><Radar size={36}/><strong>Razp<span>Izi</span></strong></div>{error ? <><h2>Povezava še ni pripravljena</h2><p>{error}</p><p className="muted">Preverite, ali Django strežnik deluje na vratih 8001.</p><button className="button primary" onClick={() => void bootstrap.refetch()}><RefreshCw size={16}/>Poskusi ponovno</button></> : <><Spinner /><p>Pripravljamo vaše priložnosti …</p></>}</div>;
    const unread = data.notifications.filter(n => !n.read).length;
    const shared: Shared = { data, refresh, notify };
    const section = route.startsWith('/profil') ? 'Profil podjetja' : route.startsWith('/obvestila') ? 'Obvestila' : route.startsWith('/racun') ? 'Moj račun' : route.startsWith('/pricakovani') ? 'Pričakovani razpisi' : 'Razpisi';
    return <div className="app-shell">
    <a className="skip-link" href="#main-content" onClick={e => { e.preventDefault(); document.getElementById('main-content')?.focus(); }}>Preskoči na vsebino</a>
    {mobileNav && <div className="nav-scrim" onClick={() => setMobileNav(false)}/>}
    <header className="topbar">
      <a className="brand topbar-brand" href="#/" aria-label="RazpIzi, domača stran"><Radar size={28} strokeWidth={1.8}/><span>Razp<span>Izi</span></span></a>
      <nav id="main-navigation" className={`main-nav ${mobileNav ? 'open' : ''}`} aria-label="Glavna navigacija">
        <a href="#/razpisi" aria-current={section === 'Razpisi' ? 'page' : undefined} className={section === 'Razpisi' ? 'active' : ''} onClick={() => setFilters(f => ({ ...f, view: 'recommended' }))}>Razpisi</a>
        <a href="#/obvestila" aria-current={section === 'Obvestila' ? 'page' : undefined} className={section === 'Obvestila' ? 'active' : ''}>Obvestila{unread > 0 && <span className="nav-count notification-count">{unread}</span>}</a>
        <a href="#/profil" aria-current={section === 'Profil podjetja' ? 'page' : undefined} className={section === 'Profil podjetja' ? 'active' : ''}>Podjetje</a>
        {user.is_staff && <a href="#/administracija">Administracija</a>}
      </nav>
      <div className="topbar-actions">{user.is_staff && <button className="button sync-button" onClick={() => setImportOpen(true)} aria-label="Osveži razpise"><RefreshCw size={17}/><span>Osveži</span></button>}<UserMenu username={user.username} initials={(data.profile.name || user.username || '?').slice(0, 2).toUpperCase()} accountActive={section === 'Moj račun'} signOut={signOut}/><button className="icon-button mobile-menu" aria-controls="main-navigation" aria-expanded={mobileNav} onClick={() => setMobileNav(!mobileNav)} aria-label={mobileNav ? 'Zapri navigacijo' : 'Odpri navigacijo'}>{mobileNav ? <X size={24}/> : <Menu size={24}/>}</button></div>
    </header>
    <div className="workspace">
      <main id="main-content" className="main-content" tabIndex={-1}>
        <div className="page-transition" key={`${route}:${data.profile.id}`}>
        {route.startsWith('/razpisi/') ? <TenderDetail key={route} {...shared} id={decodeURIComponent(route.split('/')[2].split('?')[0])}/> : route === '/profil' ? <ProfileOverview {...shared}/> : route.startsWith('/profil/uredi') ? <ProfilePage {...shared}/> : route === '/obvestila' ? <NotificationsPage {...shared}/> : route === '/racun' ? <AccountPage user={user} signOut={signOut}/> : route === '/pricakovani' ? <ExpectedTendersPage profileVersion={`${data.profile.id}:${data.profile.updated_at}`}/> : <TendersPage {...shared} filters={filters} setFilters={setFilters}/>}
        </div>
      </main>

    </div>
    {toast && <div role="status" className={`toast ${toast.error ? 'error' : ''}`}>{toast.error ? <AlertCircle size={19}/> : <CheckCircle2 size={19}/>}<span>{toast.message}</span><button onClick={() => setToast(null)} aria-label="Zapri obvestilo"><X size={16}/></button></div>}
    {importOpen && <ImportModal {...shared} close={() => setImportOpen(false)}/>}
  </div>;
}
function ImportModal({ data, refresh, notify, close }: Shared & { close: () => void }) {
    const [input, setInput] = useState('');
    const [tab, setTab] = useState<'recent' | 'single'>('recent');
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState<{ message: string; warning?: string; mode: string; tender?: Tender; imported?: number; updated?: number; errors?: { id: string; message: string }[] } | null>(null);
    const connection = data.meta.integrations?.pjn;
    const submit = async (e: FormEvent) => {
        e.preventDefault(); setBusy(true); setResult(null);
        try {
            const response = await post<NonNullable<typeof result>>(tab === 'recent' ? '/sources/pjn/sync' : '/import', tab === 'recent' ? { limit: 20 } : { url_or_id: input });
            setResult(response); await refresh();
        } catch (e) { notify((e as Error).message, true); }
        finally { setBusy(false); }
    };
    return <Modal title="Povezava z e-Naročanjem" description="Dejanske javne objave, njihove različice in dokumentacija." close={close}>
        <div className="info-box"><Link2 size={18}/><div><strong>{connection?.state === 'connected' ? 'Povezava je preverjena' : 'Javni API e-Naročanje'}</strong><p>{connection?.last_success ? `Zadnji uspešni zajem: ${date(connection.last_success)}` : 'Podatki se pridobijo neposredno z uradnega portala.'}</p><small>Preostalih zagonov danes: {connection?.runs_remaining ?? 2} od 2</small></div></div>
        <div className="modal-actions"><button className={`button ${tab === 'recent' ? 'primary' : ''}`} onClick={() => { setTab('recent'); setResult(null); }}>Nove objave</button><button className={`button ${tab === 'single' ? 'primary' : ''}`} onClick={() => { setTab('single'); setResult(null); }}>Po povezavi</button></div>
        <form onSubmit={submit}>
            {tab === 'single' ? <Field label="Povezava ali ID objave"><input value={input} onChange={e => setInput(e.target.value)} required placeholder="https://www.enarocanje.si/#/pregled-objav/…"/></Field> : <p>Pridobimo zadnjih 20 objav iz zadnjih sedmih dni ter preverimo do 30 spremljanih dosjejev. Ujemanje se izračuna glede na vaš profil. Priloge prvih treh objav se prenesejo samodejno.</p>}
            <p className="muted small-text">Vir: Javne informacije Slovenije – portal javnih naročil. Omejitev dveh zagonov dnevno velja skupaj za oba načina.</p>
            {result && <div className="import-result" role="status"><Badge tone={result.mode === 'live' ? 'green' : 'amber'}>{result.mode === 'live' ? 'Pridobljeno iz vira' : result.mode === 'partial' ? 'Delno pridobljeno' : result.mode === 'snapshot' ? 'Shranjeni podatki' : result.mode === 'limited' ? 'Dnevna omejitev' : 'Uvoz ni uspel'}</Badge><p>{result.message}</p>{result.warning && <p className="muted">{result.warning}</p>}{result.errors && result.errors.length > 0 && <details><summary>Podrobnosti ({result.errors.length})</summary>{result.errors.map((error, i) => <p key={i}>{error.id}: {error.message}</p>)}</details>}{result.tender && <a className="text-link" href={`#/razpisi/${result.tender.id}`} onClick={close}>Odpri uvoženo objavo <ArrowRight size={15}/></a>}</div>}
            <div className="modal-actions"><button className="button" type="button" onClick={close}>Zapri</button><button className="button primary" disabled={busy || (tab === 'single' && !input.trim())}>{busy ? <Spinner small/> : <RefreshCw size={16}/>} {busy ? 'Zajem poteka …' : tab === 'recent' ? 'Osveži e-Naročanje' : 'Uvozi objavo in priloge'}</button></div>
        </form>
    </Modal>;
}
function TendersPage({ data, refresh, notify, filters, setFilters }: Shared & {
    filters: Filters;
    setFilters: (filters: Filters | ((old: Filters) => Filters)) => void;
}) {
    const [showFilters, setShowFilters] = useState(false);
    const [saveOpen, setSaveOpen] = useState(false);
    const [saveName, setSaveName] = useState('');
    const [saving, setSaving] = useState(false);
    // Keyword expansion runs in two steps; the list keeps showing the old search until both finish.
    const [keywordPhase, setKeywordPhase] = useState<'' | 'suggest' | 'compare'>('');
    const keywordBusy = keywordPhase !== '';
    const [keywordResult, setKeywordResult] = useState<{
        query: string; message: string; before: number; after: number; added: string[]; counts: Record<string, number>;
        suggestions: { term: string; reason: string; evidence: { document_id: string; document_title: string; page: number | null; locator: string; quote: string; document_url?: string } }[];
    } | null>(null);
    const keywordRequest = useRef(0);
    const addedTerms = new Set((keywordResult?.suggestions || []).map(item => fold(item.term)));
    useEffect(() => { setKeywordPhase(''); return () => { keywordRequest.current++; }; }, [filters.q]);
    const expandKeywords = async () => {
        const query = filters.q || '';
        const request = ++keywordRequest.current;
        setKeywordPhase('suggest');
        setKeywordResult(null);
        try {
            const response = await post<{ suggestions: NonNullable<typeof keywordResult>['suggestions']; message: string }>('/searches/expand-keywords', { q: query });
            if (request !== keywordRequest.current) return;
            const expanded = [query.trim(), ...response.suggestions.map(item => item.term)].join(', ');
            if (expanded.length > 2000) { notify('Iskanje je predolgo za dodajanje izrazov. Skrajšajte ključne besede.', true); return; }
            // Compare the same filters with and without the added terms to show what the expansion found.
            if (response.suggestions.length) setKeywordPhase('compare');
            const found = (q: string) => queryClient.fetchQuery(tendersQuery(filterQuery({ ...filters, q }))).then(r => r.results);
            const [beforeResults, afterResults] = response.suggestions.length ? await Promise.all([found(query), found(expanded)]) : [[], []];
            if (request !== keywordRequest.current) return;
            const beforeIds = beforeResults.map(t => t.id), afterIds = afterResults.map(t => t.id);
            const known = new Set(beforeIds);
            // Tenders each suggested term finds with the current filters, so a term that finds nothing is visible.
            const counts: Record<string, number> = {};
            for (const tender of afterResults) for (const match of tender.keyword_matches || []) counts[fold(match.term)] = (counts[fold(match.term)] || 0) + 1;
            setFilters(old => old.q === query ? { ...old, q: expanded } : old);
            setKeywordResult({ ...response, query: expanded, before: beforeIds.length, after: afterIds.length, added: afterIds.filter(id => !known.has(id)), counts });
            track('keywords_expanded', { query, suggestions: response.suggestions.length, tenders_before: beforeIds.length, tenders_after: afterIds.length });
        } catch (e) {
            if (request === keywordRequest.current) notify((e as Error).message, true);
        } finally {
            if (request === keywordRequest.current) setKeywordPhase('');
        }
    };
    const [aiText, setAiText] = useState('');
    const [aiOpen, setAiOpen] = useState(false);
    const [aiBusy, setAiBusy] = useState(false);
    const [suggestion, setSuggestion] = useState<{
        filters: Filters;
        explanation: string;
        mode: string;
    } | null>(null);
    const filterKey = JSON.stringify(filters);
    // Debounce typing, then serve each filter combination from the shared cache.
    const [listFilters, setListFilters] = useState(filters);
    useEffect(() => { const timer = setTimeout(() => setListFilters(filters), 180); return () => clearTimeout(timer); }, [filterKey]);
    const tenderList = useQuery({ ...tendersQuery(filterQuery(listFilters)), placeholderData: keepPreviousData });
    const results = tenderList.data?.results ?? [];
    const scoring = tenderList.data?.relevance_pending ?? false;
    // Background polls while scoring refresh the list quietly; only user-driven loads show progress.
    const loading = (tenderList.isFetching && (tenderList.isPlaceholderData || !scoring)) || filterKey !== JSON.stringify(listFilters);
    const pending = loading || keywordBusy;
    const error = tenderList.error?.message ?? '';
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
        track('tender_follow_toggled', { tender_id: tender.id, following: !tender.following, from: 'list' });
        await refresh();
        notify(tender.following ? 'Razpis ne spremljate več.' : 'Razpis spremljate. Ob spremembah boste obveščeni.');
    }
    catch (e) {
        notify((e as Error).message, true);
    } };
    const ignore = async (tender: Tender) => { try {
        await post(`/tenders/${tender.id}/ignore`, { ignored: !tender.ignored });
        track('tender_ignore_toggled', { tender_id: tender.id, ignored: !tender.ignored, from: 'list' });
        await refresh();
        notify(tender.ignored ? 'Razpis je spet prikazan v seznamih.' : 'Razpis je skrit. Najdete ga v zavihku Skriti.');
    }
    catch (e) {
        notify((e as Error).message, true);
    } };
    const counts = tenderList.data?.counts;
    return <>
    <section className="page-intro image-intro tender-intro"><div className="page-heading opportunities-heading"><h1>Razpisi za vas</h1><a className="current-company" href="#/profil"><Building2 size={17}/>{data.profile.name}<ArrowUpRight size={15}/></a></div><img className="corporate-photo" src="/corporate-building.webp" alt="Velika poslovna stavba s stekleno fasado" width="660" height="220" fetchPriority="high"/></section>
    <div className="opportunities-columns"><div className="opportunities-main">
    <div className="list-navigation"><div className="tabs" aria-label="Pogled razpisov">{[['recommended', 'Za vas', counts?.recommended], ['all', 'Vsi razpisi', counts?.all], ['following', 'Spremljam', counts?.following], ['ignored', 'Skriti', counts?.ignored]].map(([view, label, count]) => <button className={(filters.view || 'recommended') === view ? 'active' : ''} key={view} aria-pressed={(filters.view || 'recommended') === view} onClick={() => set({ view: view as Filters['view'] })}>{label}{count != null && <span>{count}</span>}</button>)}</div><span className="updated-at"><span />{data.meta.last_sync ? `Posodobljeno ${date(data.meta.last_sync, { day: 'numeric', month: 'short' })}` : 'Shranjene objave'}</span></div>
    <div className="search-toolbar"><div className="search-input"><Search size={19}/><input aria-label="Išči razpise" placeholder="Naslov, področje ali ključne besede" value={filters.q || ''} onChange={e => set({ q: e.target.value })}/>{filters.q && <button onClick={() => set({ q: '' })} aria-label="Počisti iskanje"><X size={16}/></button>}</div><button type="button" className="button keyword-expand" disabled={keywordBusy || (filters.q || '').trim().length < 2 || (filters.q || '').trim().length > 1000} onClick={expandKeywords} title="Dodaj sorodne izraze iz indeksirane dokumentacije">{keywordBusy ? <Spinner small/> : <Sparkles size={17}/>}{keywordBusy ? 'Dodajam ključne besede …' : 'samodejno dodaj ključne besede'}</button><button className={`button filter-toggle ${showFilters ? 'selected' : ''}`} aria-expanded={showFilters} aria-controls="tender-filters" onClick={() => setShowFilters(!showFilters)}><SlidersHorizontal size={17}/>Filtri{activeCount > 0 && <b>{activeCount}</b>}</button><button className="button" onClick={() => setSaveOpen(true)}><Bookmark size={16}/>Shrani iskanje</button></div>
    {keywordBusy && <div className="keyword-pending" role="status" aria-live="polite"><Spinner small/><div><strong>Ključne besede še niso dodane</strong><p>Rezultati spodaj še veljajo za iskanje »{(filters.q || '').trim()}«. Seznam se posodobi, ko so nove besede dodane.</p><ol className="keyword-steps"><li className={keywordPhase === 'suggest' ? 'active' : 'done'}>{keywordPhase === 'suggest' ? <LoaderCircle size={13} className="spin"/> : <Check size={13}/>}Iskanje sorodnih izrazov v dokumentaciji</li><li className={keywordPhase === 'compare' ? 'active' : ''}>{keywordPhase === 'compare' ? <LoaderCircle size={13} className="spin"/> : <span className="step-dot"/>}Iskanje razpisov z novimi besedami</li></ol></div></div>}
    {keywordResult && keywordResult.query === filters.q && <div className="keyword-expansion" role="status">{keywordResult.suggestions.length > 0 && <div className={`keyword-gain ${keywordResult.added.length ? 'positive' : ''}`}><strong>{keywordResult.added.length ? `+${keywordResult.added.length} ${razpisi(keywordResult.added.length)} več` : 'Ni novih razpisov'}</strong><span>z dodanimi ključnimi besedami · prej {keywordResult.before}, zdaj {keywordResult.after}{keywordResult.added.length > 0 && ' · novi so v seznamu označeni'}</span></div>}<p>{keywordResult.message}</p>{keywordResult.suggestions.length > 0 && <ul className="keyword-counts" aria-label="Dodane besede in število razpisov pri trenutnih filtrih" title="Število razpisov pri trenutnih filtrih">{keywordResult.suggestions.map(item => { const n = keywordResult.counts[fold(item.term)] || 0; return <li key={item.term} className={n ? '' : 'empty'}>{item.term} <span>· {n} {razpisi(n)}</span></li>; })}</ul>}{keywordResult.suggestions.length > 0 && <details><summary>Dodane besede in viri ({keywordResult.suggestions.length})</summary><div className="keyword-evidence-list">{keywordResult.suggestions.map(item => <div key={item.term}><strong>{item.term}</strong><p>{item.reason}</p><blockquote>»{item.evidence.quote}«</blockquote><a href={item.evidence.document_id ? `/api/documents/${encodeURIComponent(item.evidence.document_id)}${item.evidence.page ? `#page=${item.evidence.page}` : ''}` : item.evidence.document_url} target="_blank" rel="noreferrer">{item.evidence.document_title} · {item.evidence.page ? `str. ${item.evidence.page}` : item.evidence.locator}<ExternalLink size={12}/></a></div>)}</div></details>}</div>}
    <div className="search-secondary"><button className="text-link" aria-expanded={aiOpen} onClick={() => setAiOpen(!aiOpen)}><Sparkles size={14}/>Iskanje z opisom<ChevronDown size={13}/></button><details className="saved-search-disclosure"><summary><Bookmark size={14}/>Shranjena iskanja ({data.saved_searches.length})<ChevronDown size={13}/></summary><div className="saved-searches"><span><Bookmark size={14}/>Shranjena iskanja</span>{data.saved_searches.length ? data.saved_searches.map(saved => <div className="saved-search" key={saved.id}><button onClick={() => setFilters({ ...defaults, ...saved.filters })}>{saved.name}<ArrowUpRight size={12}/></button><button className="delete-search" aria-label={`Izbriši iskanje ${saved.name}`} onClick={async () => { try {
        await api(`/searches/${saved.id}`, { method: 'DELETE' });
        await refresh();
    }
    catch (e) {
        notify((e as Error).message, true);
    } }}><X size={11}/></button></div>) : <span className="saved-empty">Vaši priljubljeni filtri na enem mestu.</span>}<button className="save-search-link" onClick={() => setSaveOpen(true)}><Plus size={14}/>Shrani iskanje</button></div></details></div>
    {aiOpen && <div className="ai-filter-box"><div className="ai-filter-intro"><Sparkles size={19}/><div><strong>Opišite, katere razpise iščete.</strong><p>Na primer: spletne platforme in IoT, brez dobave računalnikov.</p></div></div><form onSubmit={suggest} className="ai-filter-form"><input aria-label="Opis želenih razpisov" placeholder="Opišite svojo naslednjo priložnost …" value={aiText} onChange={e => setAiText(e.target.value)}/><button className="button primary small" disabled={aiBusy || !aiText.trim()}>{aiBusy ? <Spinner small/> : <Sparkles size={15}/>}Predlagaj filtre</button></form>{suggestion && <div className="filter-proposal"><p>{suggestion.explanation}</p><div className="proposal-tags">{Object.entries(suggestion.filters).filter(([, v]) => v !== '' && v !== undefined).map(([k, v]) => <span key={k}>{filterLabel(k)}: {Array.isArray(v) ? v.map(x => labels[x] || x).join(', ') : typeof v === 'boolean' ? v ? 'da' : 'ne' : v}</span>)}</div><div className="proposal-footer"><small>{suggestion.mode === 'live' ? 'AI predlog' : 'Predlog po pravilih'} · Uporabi se šele po vaši potrditvi.</small><button className="button primary small" onClick={() => { setFilters({ ...defaults, ...suggestion.filters }); setSuggestion(null); notify('Predlagani filtri so uporabljeni.'); }}>Uporabi filtre<Check size={15}/></button></div></div>}</div>}
    {activeCount > 0 && <div className="active-filter-list" aria-label="Aktivni filtri">{Object.entries(filters).filter(([key, value]) => !['view', 'sort', 'include_unknown'].includes(key) && value !== undefined && value !== '' && value !== false && (!Array.isArray(value) || value.length)).map(([key, value]) => key === 'q' ? <div className="keyword-filter" key={key} role="group" aria-label="Ključne besede v iskanju"><b>Ključne besede<span>{searchTerms(String(value)).length}</span></b><div className="keyword-chips">{searchTerms(String(value)).map(term => { const added = addedTerms.has(fold(term)); return <span key={term} className={added ? 'added' : ''} title={added ? 'Samodejno dodana iz dokumentacije' : undefined}>{added && <Sparkles size={11}/>}{term}<button aria-label={`Odstrani ključno besedo ${term}`} onClick={() => set({ q: searchTerms(String(value)).filter(other => other !== term).join(', ') })}><X size={12}/></button></span>; })}</div>{searchTerms(String(value)).length > 1 && <button className="keyword-clear" onClick={() => set({ q: '' })}>Počisti</button>}</div> : <span key={key}><b>{filterLabel(key)}</b>{Array.isArray(value) ? value.map(item => labels[item] || item).join(', ') : value === true ? '' : String(value)}<button aria-label={`Odstrani filter ${filterLabel(key)}`} onClick={() => set({ [key]: undefined })}><X size={12}/></button></span>)}</div>}
    <div className={`tenders-layout ${showFilters ? 'filters-open' : ''}`}>{showFilters && <aside id="tender-filters" className="filter-panel mobile-open"><div className="filter-panel-title"><h3><SlidersHorizontal size={17}/>Filtri {activeCount > 0 && <span>{activeCount}</span>}</h3><button onClick={() => setFilters({ ...defaults, view: filters.view })}>Ponastavi</button></div><FilterPanel filters={filters} set={set} facets={tenderList.data?.facets}/><div className="filter-panel-foot"><ShieldCheck size={15}/><p>Priporočila temeljijo na vašem profilu.<a href="#/profil">Uredi profil <ArrowUpRight size={12}/></a></p></div></aside>}
    <section className={`tender-results ${pending ? 'is-pending' : ''}`} aria-label="Rezultati iskanja" aria-busy={pending}>{pending && <div className="results-progress" aria-hidden="true"><span/></div>}<div className="results-heading"><div><strong className="results-count" aria-live="polite">{keywordBusy ? <><Spinner small/>Dodajamo ključne besede …</> : loading ? <><Spinner small/>Iščemo razpise …</> : `Razpisi za pregled · ${results.length}`}</strong>{scoring && !loading && !keywordBusy && <small className="relevance-pending"><Spinner small/>AI posodablja oceno ujemanja …</small>}</div><label className="sort-control"><ArrowDownUp size={14}/><select aria-label="Razvrsti razpise" value={filters.sort || 'match'} onChange={e => set({ sort: e.target.value as Filters['sort'] })}><option value="match">Najboljše ujemanje</option><option value="deadline">Najbližji rok</option><option value="newest">Najnovejše objave</option><option value="value">Najvišja vrednost</option></select></label></div>{error ? <div className="error-banner"><AlertCircle size={20}/><div><strong>Razpisov ni bilo mogoče naložiti.</strong><p>{error}</p></div></div> : pending && !results.length ? <div className="card-skeletons">{[1, 2, 3].map(i => <div className="card-skeleton" key={i}><i /><i /><i /></div>)}</div> : !results.length && filters.view === 'ignored' && activeCount === 0 ? <EmptyState title="Ni skritih razpisov." icon={<EyeOff size={25}/>}>Razpis, ki ga ne želite več videti, skrijete z gumbom »Skrij« na kartici ali v podrobnostih razpisa.</EmptyState> : !results.length ? <EmptyState title="Za te filtre ni zadetkov." action={<button className="button" onClick={() => setFilters({ ...defaults, view: 'all' })}>Prikaži vse razpise</button>}>Poskusite odstraniti posamezen filter ali vključiti razpise z neznanimi podatki.</EmptyState> : <div className={`tender-list ${pending ? 'refreshing' : ''}`}>{pending && <div className="results-stale-note"><LoaderCircle size={14} className="spin"/>{keywordBusy ? 'Prikazani so rezultati brez novih ključnih besed.' : 'Prikazani so prejšnji rezultati, nalagamo nove …'}</div>}{results.map(tender => <TenderCard key={tender.id} tender={tender} today={data.meta.today} follow={follow} ignore={ignore} search={filters.q || ''} fromKeywords={!!keywordResult && keywordResult.query === filters.q && keywordResult.added.includes(tender.id)} addedTerms={addedTerms}/>)}</div>}<div className="results-note"><ShieldCheck size={14}/><span>Ocena ujemanja je pomoč pri pregledu. Pogoje vedno preverite v izvorni dokumentaciji.</span></div></section></div>
    </div></div>
    {saveOpen && <Modal title="Shranite to iskanje" description="Ponovno uporabite izbrane filtre z enim klikom." close={() => setSaveOpen(false)}><form onSubmit={save}><Field label="Ime iskanja"><input autoFocus required maxLength={80} placeholder="Na primer: IoT in spletne platforme" value={saveName} onChange={e => setSaveName(e.target.value)}/></Field><div className="modal-actions"><button className="button" type="button" onClick={() => setSaveOpen(false)}>Prekliči</button><button className="button primary" disabled={saving || !saveName.trim()}>{saving ? <Spinner small/> : <Bookmark size={16}/>}Shrani iskanje</button></div></form></Modal>}
  </>;
}
const fold = (value: string) => value.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
/** Comma separated search terms, deduplicated the same way as the backend. */
function searchTerms(query: string) {
    const seen = new Set<string>();
    return query.split(',').map(term => term.trim().replace(/\s+/g, ' ')).filter(term => term && !seen.has(fold(term)) && !!seen.add(fold(term)));
}
const documentLink = (evidence: NonNullable<KeywordMatch['evidence']>, term: string) => `/api/documents/${encodeURIComponent(evidence.document_id)}/text?q=${encodeURIComponent(term)}${evidence.page ? `#page-${evidence.page}` : ''}`;
function QuoteWithMatch({ evidence }: { evidence: NonNullable<KeywordMatch['evidence']> }) {
    const { quote, match_start: start, match_end: end } = evidence;
    if (start == null || end == null) return <>{quote}</>;
    return <>{quote.slice(0, start)}<mark>{quote.slice(start, end)}</mark>{quote.slice(end)}</>;
}
function CardKeywords({ tender, addedTerms, search }: { tender: Tender; addedTerms: Set<string>; search: string }) {
    const matches = tender.keyword_matches || [];
    if (!matches.length) return null;
    const cited = matches.filter(item => item.evidence);
    return <div className="card-keywords">
      <div className="card-keyword-links" role="group" aria-label="Ključne besede, najdene v razpisu"><span className="card-keywords-label">Najdeno:</span>{matches.map(item => { const added = addedTerms.has(fold(item.term)); const content = <>{added && <Sparkles size={10}/>}<span>{item.term}</span><small>{item.evidence ? (item.evidence.page ? `str. ${item.evidence.page}` : 'dokument') : item.fields[0]}</small></>; return item.evidence
        ? <a key={item.term} className={added ? 'added' : ''} href={documentLink(item.evidence, item.term)} target="_blank" rel="noreferrer" title={`${item.evidence.document_title}${item.evidence.page ? `, str. ${item.evidence.page}` : ''}: »${item.evidence.quote}«`}>{content}<ExternalLink size={11}/></a>
        : <a key={item.term} className={added ? 'added' : ''} href={tenderLink(tender.id, search)} title={`Najdeno v ${item.fields.join(', ')}`}>{content}</a>; })}</div>
      {cited.length > 0 && <details className="card-keyword-quotes"><summary>Citati iz dokumentacije ({cited.length})<ChevronDown size={13}/></summary>{cited.map(item => <div key={item.term}><blockquote>»<QuoteWithMatch evidence={item.evidence!}/>«</blockquote><a href={documentLink(item.evidence!, item.term)} target="_blank" rel="noreferrer"><FileText size={12}/>{item.evidence!.document_title}{item.evidence!.page ? ` · str. ${item.evidence!.page}` : ''}<ExternalLink size={11}/></a></div>)}</details>}
    </div>;
}
/** Search keywords found in an opened tender, each with the passage and document page it comes from. */
function TenderKeywords({ tender, search }: { tender: Tender; search: string }) {
    const terms = searchTerms(search);
    if (!terms.length) return null;
    const matches = tender.keyword_matches;
    const found = new Set((matches || []).map(item => fold(item.term)));
    const missing = terms.filter(term => !found.has(fold(term)));
    return <section className="surface detail-section tender-keywords" aria-labelledby="tender-keywords-title">
      <div className="section-heading"><div><h2 id="tender-keywords-title"><Search size={19}/>Ključne besede v razpisu</h2><p className="section-help">Iz iskanja »{terms.join(', ')}«. Pri vsaki besedi je vir, kjer se pojavi, da lahko zadetek preverite.</p></div>{matches && <Badge tone={matches.length ? 'green' : 'neutral'}>{matches.length}/{terms.length} najdenih</Badge>}</div>
      {!matches ? <div className="keyword-loading"><Spinner small/>Iščemo ključne besede v dokumentaciji …</div> : <>
      {matches.length > 0 && <div className="tender-keyword-list">{matches.map(item => <div className="tender-keyword" key={item.term}>
        <div className="tender-keyword-head"><strong>{item.term}</strong>{item.fields.length > 0 && <span className="muted small-text">v {item.fields.join(', ')}</span>}</div>
        {item.evidence ? <><blockquote>»<QuoteWithMatch evidence={item.evidence}/>«</blockquote><a className="tender-keyword-source" href={documentLink(item.evidence, item.term)} target="_blank" rel="noreferrer"><FileText size={13}/>{item.evidence.document_title} · {item.evidence.page ? `str. ${item.evidence.page}` : item.evidence.locator}<ExternalLink size={12}/></a></>
          : <p className="muted small-text">Najdeno v podatkih objave ({item.fields.join(', ')}), ne v obdelani dokumentaciji.{tender.source_url && <> <a href={tender.source_url} target="_blank" rel="noreferrer">Odpri objavo<ExternalLink size={11}/></a></>}</p>}
      </div>)}</div>}
      {missing.length > 0 && <p className="tender-keywords-missing"><CircleHelp size={14}/>Ni najdeno: {missing.join(', ')}</p>}
      </>}
    </section>;
}
function filterLabel(key: string) { return ({ min_score: 'Najmanjše ujemanje', include_partner_opportunities: 'Vključi priložnosti s partnerjem', q: 'Ključne besede', exclude: 'Izključeno', cpv: 'CPV', source_types: 'Izvor podatkov', kinds: 'Vrsta', min_value: 'Najmanj EUR', max_value: 'Največ EUR', min_days: 'Dni do roka', levels: 'Ujemanje', include_unknown: 'Vključi neznane', statuses: 'Stanje', regions: 'Lokacije', view: 'Pogled', condition_states: 'Pogoji', only_new: 'Samo nove', only_updates: 'Popravki', only_following: 'Spremljam', buyers: 'Naročniki', published_from: 'Objava od', published_to: 'Objava do', deadline_from: 'Rok od', deadline_to: 'Rok do' } as Record<string, string>)[key] || key; }
function FilterSection({ title, count = 0, initiallyOpen = false, children }: { title: string; count?: number; initiallyOpen?: boolean; children: ReactNode }) {
    const [open, setOpen] = useState(initiallyOpen);
    return <details className="filter-section" open={open} onToggle={e => setOpen(e.currentTarget.open)}><summary>{title}{count > 0 && <span>{count}</span>}<ChevronDown size={14}/></summary><div className="filter-section-body">{children}</div></details>;
}
function FilterPanel({ filters, set, facets }: {
    filters: Filters;
    set: (patch: Partial<Filters>) => void;
    facets?: TenderList['facets'];
}) {
    const toggle = (key: keyof Filters, value: string) => { const values = (filters[key] as string[] | undefined) || []; set({ [key]: values.includes(value) ? values.filter(v => v !== value) : [...values, value] }); };
    const check = (key: keyof Filters, value: string, text: string) => <label className="checkbox-row" key={value}><input type="checkbox" checked={((filters[key] as string[]) || []).includes(value)} onChange={() => toggle(key, value)}/><span>{text}</span></label>;
    const count = (...keys: (keyof Filters)[]) => keys.reduce((total, key) => { const value = filters[key]; return total + (Array.isArray(value) ? value.length : value !== undefined && value !== false && value !== '' ? 1 : 0); }, 0);
    const regions = facets?.regions ?? [];
    const buyers = facets?.buyers ?? [];
    return <>
        <div className="match-threshold"><label htmlFor="min-match-score">Najmanjše vsebinsko ujemanje</label><div><input id="min-match-score" aria-label="Najmanjše vsebinsko ujemanje" type="range" min="0" max="100" step="1" value={filters.min_score || 0} onChange={e => set({ min_score: Number(e.target.value) || undefined, levels: undefined })}/><input aria-label="Najmanjše ujemanje, število od 0 do 100" type="number" min="0" max="100" step="1" value={filters.min_score || 0} onChange={e => set({ min_score: Math.max(0, Math.min(100, Math.round(Number(e.target.value)))) || undefined, levels: undefined })}/><span>/100</span></div><small>{filters.min_score ? `Prikaži ujemanje najmanj ${filters.min_score}/100.` : 'Brez dodatne omejitve ujemanja.'}</small><details className="quiet-disclosure"><summary>Kaj pomeni ocena?</summary><p>Podobnost dejavnosti podjetja in predmeta naročila, ne verjetnost uspeha. Pogoje preverjamo ločeno.</p></details><label className="checkbox-row partner-opportunity-toggle"><input type="checkbox" checked={filters.include_partner_opportunities || false} onChange={e => set({ include_partner_opportunities: e.target.checked })}/><span>Vključi priložnosti s partnerjem<small className="partner-toggle-hint">Razširi pogled Za vas.</small></span></label></div>
        <FilterSection title="Področje / CPV" count={count('cpv')} initiallyOpen>{cpvOptions.map(([code, label]) => check('cpv', code, label))}<OtherCpvCodes values={filters.cpv || []} onChange={cpv => set({ cpv })}/></FilterSection>
        <FilterSection title="Vrsta naročila" count={count('kinds')}>{['services', 'goods', 'works'].map(kind => check('kinds', kind, labels[kind]))}</FilterSection>
        <FilterSection title="Izpolnjevanje pogojev" count={count('condition_states')}>{(['met', 'unknown', 'unmet'] as const).map(state => check('condition_states', state, state === 'met' ? 'Izpolnjeni' : state === 'unknown' ? 'Potrebno preveriti' : 'Neizpolnjen pogoj'))}</FilterSection>
        <FilterSection title="Vrednost naročila" count={count('min_value', 'max_value')}><div className="range-inputs"><label><span>Od (€)</span><input type="number" min="0" aria-label="Najnižja vrednost" placeholder="Brez meje" value={filters.min_value ?? ''} onChange={e => set({ min_value: e.target.value === '' ? undefined : Number(e.target.value) })}/></label><label><span>Do (€)</span><input type="number" min="0" aria-label="Najvišja vrednost" placeholder="Brez meje" value={filters.max_value ?? ''} onChange={e => set({ max_value: e.target.value === '' ? undefined : Number(e.target.value) })}/></label></div></FilterSection>
        <FilterSection title="Rok za prijavo" count={count('min_days', 'deadline_from', 'deadline_to')}><Field label="Najmanj dni do roka"><input type="number" min="0" placeholder="Na primer 14" value={filters.min_days ?? ''} onChange={e => set({ min_days: e.target.value === '' ? undefined : Number(e.target.value) })}/></Field><Field label="Rok od"><input type="date" value={filters.deadline_from || ''} onChange={e => set({ deadline_from: e.target.value })}/></Field><Field label="Rok do"><input type="date" value={filters.deadline_to || ''} onChange={e => set({ deadline_to: e.target.value })}/></Field></FilterSection>
        <FilterSection title="Lokacija" count={count('regions')}>{regions.map(region => check('regions', region, region))}</FilterSection>
        <FilterSection title="Naročnik" count={count('buyers')}>{buyers.map(buyer => check('buyers', buyer, buyer))}</FilterSection>
        <FilterSection title="Stanje razpisa" count={count('statuses')}>{['open', 'closed', 'cancelled', 'unconfirmed'].map(status => check('statuses', status, labels[status]))}</FilterSection>
        <FilterSection title="Datum objave" count={count('published_from', 'published_to')}><Field label="Objava od"><input type="date" value={filters.published_from || ''} onChange={e => set({ published_from: e.target.value })}/></Field><Field label="Objava do"><input type="date" value={filters.published_to || ''} onChange={e => set({ published_to: e.target.value })}/></Field></FilterSection>
        <FilterSection title="Dodatne omejitve" count={count('exclude', 'only_new', 'only_updates')}><Field label="Izključene besede" hint="Ločite z vejico."><input placeholder="licence, tiskalniki" value={filters.exclude || ''} onChange={e => set({ exclude: e.target.value })}/></Field><label className="checkbox-row"><input type="checkbox" checked={filters.only_new || false} onChange={e => set({ only_new: e.target.checked })}/><span>Samo nove objave</span></label><label className="checkbox-row"><input type="checkbox" checked={filters.only_updates || false} onChange={e => set({ only_updates: e.target.checked })}/><span>Samo s popravki</span></label></FilterSection>
        <label className="checkbox-row unknown-filter"><input type="checkbox" checked={filters.include_unknown !== false} onChange={e => set({ include_unknown: e.target.checked })}/><span>Vključi neznano vrednost ali rok</span></label>
    </>;
}
function razpisi(n: number) {
    const mod = n % 100;
    return mod === 1 ? 'razpis' : mod === 2 ? 'razpisa' : mod === 3 || mod === 4 ? 'razpisi' : 'razpisov';
}
/** Detail link that carries the current search, so the detail page can show the keywords found in the tender. */
const tenderLink = (id: string, search = '', tab = '') => { const params = new URLSearchParams(); if (tab) params.set('tab', tab); if (search.trim()) params.set('q', search.trim()); const query = params.toString(); return `#/razpisi/${encodeURIComponent(id)}${query ? `?${query}` : ''}`; };
function TenderCard({ tender, today, follow, ignore, search = '', fromKeywords = false, addedTerms = new Set<string>() }: {
    tender: Tender;
    today: string;
    follow: (tender: Tender) => Promise<void>;
    ignore: (tender: Tender) => Promise<void>;
    search?: string;
    fromKeywords?: boolean;
    addedTerms?: Set<string>;
}) {
    const [busy, setBusy] = useState(false);
    const [hiding, setHiding] = useState(false);
    const days = daysLeft(tender.deadline, today);
    const recommendationLabel = partnerOpportunity(tender) && tender.match.conditions.some(c => c.status === 'unmet')
        ? 'Manjkajo pogoji' : tender.match.recommendation === 'review' ? null : labels[tender.match.recommendation];
    return <article className={`tender-card ${tender.status !== 'open' ? 'inactive' : ''}`}>
    <div className="card-topline"><div className="card-tags">{fromKeywords && <Badge tone="green"><Sparkles size={10}/>Z novo ključno besedo</Badge>}{tender.source_type === 'real' && <Badge tone="blue">e-Naročanje</Badge>}{tender.status !== 'open' ? <Badge>{labels[tender.status]}</Badge> : tender.has_update ? <Badge tone="amber"><RefreshCw size={10}/>Popravek</Badge> : tender.is_new ? <Badge tone="green"><span className="tiny-dot"/>Novo</Badge> : null}</div><div className="card-match"><span className={`card-content-score ${tender.match.level}`} title="Vsebinsko ujemanje, ne verjetnost uspeha"><Radar size={14}/><strong>{Math.round(tender.match.score)}</strong><span>/100</span></span>{recommendationLabel && <Badge tone={tender.match.recommendation === 'recommended' ? 'green' : 'neutral'}>{recommendationLabel}</Badge>}<button className={`icon-button bookmark-button ${tender.following ? 'saved' : ''}`} disabled={busy} onClick={async () => { setBusy(true); await follow(tender); setBusy(false); }} aria-label={tender.following ? `Prenehaj spremljati: ${tender.title}` : `Spremljaj: ${tender.title}`} title={tender.following ? 'Spremljate razpis' : 'Spremljaj razpis'}>{busy ? <Spinner small/> : <Bookmark size={19} fill={tender.following ? 'currentColor' : 'none'}/>}</button></div></div>
    <a href={tenderLink(tender.id, search)} className="tender-title"><h2>{tender.title}</h2><ArrowUpRight size={19}/></a><div className="tender-buyer"><Building2 size={15}/><span>{tender.buyer}</span></div>
    <CardKeywords tender={tender} addedTerms={addedTerms} search={search}/>
    <details className="card-fit-details"><summary>Zakaj ta ocena? <small>{tender.match.mode === 'gemini' ? 'AI presoja' : 'Pravila'}</small><ChevronDown size={13}/></summary><div className="match-reasons">{tender.match.reasons.slice(0, 2).map((reason, i) => <span key={i}><Check size={12}/>{reason}</span>)}</div>{tender.match.warning && <p className="muted small-text">{tender.match.warning}</p>}
    {tender.match.open_question && <div className={`open-question ${tender.match.conditions.some(c => c.status === 'unmet') ? 'unmet' : ''}`}><CircleHelp size={15}/><span>{tender.match.open_question}</span></div>}
    </details>{partnerOpportunity(tender) && <div className="partner-card-actions">{tender.match.conditions.some(c => c.status === 'unknown') && <a href="#/profil/uredi" className="text-link">Dopolni profil</a>}<a className="text-link" href={tenderLink(tender.id, search, 'partners')}><Users size={14}/>Poišči partnerja<ArrowRight size={13}/></a></div>}<div className="card-footer"><div className="card-metadata">{tender.value != null && <div className="card-value"><span>Vrednost</span><strong>{money(tender.value)}</strong></div>}<div className="card-deadline"><span>Rok</span><strong>{date(tender.deadline, { day: 'numeric', month: 'short' })}{tender.status === 'open' && days !== null && <small className={`card-days-left${days <= 14 ? ' urgent' : ''}`}>{days >= 0 ? `še ${days} dni` : 'rok je potekel'}</small>}</strong></div></div><div className="card-actions"><button className="text-link card-ignore" disabled={hiding} onClick={async () => { setHiding(true); await ignore(tender); setHiding(false); }} title={tender.ignored ? 'Razpis bo spet prikazan v seznamih' : 'Razpis ne bo več prikazan v seznamih'}>{hiding ? <Spinner small/> : tender.ignored ? <Eye size={15}/> : <EyeOff size={15}/>}{tender.ignored ? 'Prikaži znova' : 'Skrij'}</button><a className="card-detail-link" href={tenderLink(tender.id, search)}>Preveri razpis<ArrowRight size={16}/></a></div></div>
  </article>;
}
function TenderDetail({ id, data, refresh, notify }: Shared & {
    id: string;
}) {
    // The search that opened this tender; the API then reports which of its keywords the tender contains.
    const [search] = useState(() => new URLSearchParams(window.location.hash.split('?')[1] || '').get('q') || '');
    const detail = useQuery<Tender>({ queryKey: queryKeys.tender(id, search), queryFn: ({ signal }) => api<Tender>(`/tenders/${encodeURIComponent(id)}${search ? `?q=${encodeURIComponent(search)}` : ''}`, { signal }), placeholderData: () => listedTender(id) });
    const tender = detail.data ?? null;
    const error = detail.error?.message ?? '';
    const [tab, setTab] = useState('conditions');
    const [busy, setBusy] = useState('');
    const [answering, setAnswering] = useState('');
    useEffect(() => { const requested = new URLSearchParams(window.location.hash.split('?')[1] || '').get('tab'); setTab(requested && ['overview', 'conditions', 'partners', 'submission', 'history', 'buyer-history'].includes(requested) ? requested : 'conditions'); }, [id]);
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
    // Count the same conditions shown below; extracted conditions replace the legacy checks.
    const displayedConditions = tender.tender_conditions?.items.length ? tender.tender_conditions.items : conditions;
    const conditionCounts = { met: 0, unknown: 0, unmet: 0 };
    for (const condition of displayedConditions) {
        conditionCounts[condition.status === 'manual' ? 'unknown' : condition.status]++;
    }
    const manualConditions = displayedConditions.filter(condition => condition.status === 'manual').length;
    const days = daysLeft(tender.deadline, data.meta.today);
    const ignore = () => act('ignore', async () => { await post(`/tenders/${id}/ignore`, { ignored: !tender.ignored }); track('tender_ignore_toggled', { tender_id: id, ignored: !tender.ignored, from: 'detail' }); await refresh(); notify(tender.ignored ? 'Razpis je spet prikazan v seznamih.' : 'Razpis je skrit in ga ne boste več videli v seznamih. Najdete ga v zavihku Skriti.'); });
    const follow = () => act('follow', async () => { await post(`/tenders/${id}/follow`, { following: !tender.following }); track('tender_follow_toggled', { tender_id: id, following: !tender.following, from: 'detail' }); await refresh(); notify(tender.following ? 'Spremljanje je izključeno.' : 'Spremljanje je vključeno. Obvestili vas bomo o spremembah.'); });
    const answerCondition = async (item: TenderCondition, answer: ConditionAnswerValue) => {
        setAnswering(item.id);
        try {
            const result = await post<{ tender: Tender; profile: Profile }>(`/tenders/${encodeURIComponent(id)}/conditions/${encodeURIComponent(item.id)}/answer`, { answer, profile_id: data.profile.id });
            queryClient.setQueryData(queryKeys.tender(id, search), { ...result.tender, keyword_matches: tender.keyword_matches });
            applyConditionAnswers(result.profile, id);
            track('condition_answered', { tender_id: id, category: item.category, answer: answer ?? 'removed', inherited: !!item.profile_answer?.inherited });
            notify(answer === null ? 'Oznaka je odstranjena iz profila podjetja.' : 'Shranjeno v profil podjetja. Upoštevamo ga tudi pri drugih razpisih s podobnim pogojem.');
        }
        catch (e) {
            notify((e as Error).message, true);
        }
        finally {
            setAnswering('');
        }
    };
    const analyze = () => act('analyze', async () => { const result = await post<Tender & {
        analysis?: {
            mode: string;
            message: string;
        }[];
        message?: string;
    }>(`/tenders/${id}/analyze`); queryClient.setQueryData(queryKeys.tender(id, search), { ...result, keyword_matches: tender.keyword_matches }); await refresh(); notify(result.analysis?.map(item => item.message).filter(Boolean).join(' ') || result.message || 'Analiza je osvežena. Preverite pogoje in navedene vire.'); });
    return <>
    <a className="back-link" href="#/razpisi"><ArrowLeft size={16}/>Nazaj na razpise</a>
    <div className="detail-header"><div><div className="card-tags"><Badge>{labels[tender.kind]}</Badge><Badge tone={tender.status === 'open' ? 'green' : 'neutral'}>{labels[tender.status]}</Badge><span className="detail-version">Različica {tender.version}</span></div><h1>{tender.title}</h1><div className="tender-buyer"><Building2 size={15}/>{tender.buyer}<i /><MapPin size={15}/>{tender.region}</div>{tender.source_type === 'real' && <div className="tender-source-links">{tender.source_metadata?.submission_url && ['open', 'unconfirmed'].includes(tender.status) && <a className="button primary small" href={tender.source_metadata.submission_url} target="_blank" rel="noopener noreferrer" title="Ponudbo oddate v sistemu e-JN; potrebna je prijava v e-JN.">Oddaj ponudbo na e-JN<ExternalLink size={14}/></a>}{tender.source_url && <a className="text-link" href={tender.source_url} target="_blank" rel="noopener noreferrer">Objava na e-Naročanju<ExternalLink size={13}/></a>}</div>}</div><div className="detail-actions"><button className={`button ${tender.following ? 'following' : ''}`} disabled={!!busy} onClick={follow}>{busy === 'follow' ? <Spinner small/> : <Bookmark size={17} fill={tender.following ? 'currentColor' : 'none'}/>}{tender.following ? 'Spremljam razpis' : 'Spremljaj razpis'}</button><button className="button" disabled={!!busy} onClick={ignore} title={tender.ignored ? 'Razpis bo spet prikazan v seznamih' : 'Razpis ne bo več prikazan v seznamih'}>{busy === 'ignore' ? <Spinner small/> : tender.ignored ? <Eye size={17}/> : <EyeOff size={17}/>}{tender.ignored ? 'Prikaži znova' : 'Skrij razpis'}</button></div></div>
    <div className="detail-layout"><div className="detail-main"><div className="tender-facts"><div className="detail-metrics"><div><Coins size={18}/><span>Ocenjena vrednost<strong>{money(tender.value)}</strong></span></div><div><CalendarDays size={18}/><span>Rok za oddajo<strong>{date(tender.deadline)}{tender.status === 'open' && days != null && <small>{days >= 0 ? `še ${days} dni` : 'rok je potekel'}</small>}</strong></span></div></div><div className="detail-metrics detail-metadata" aria-label="Podatki o objavi"><div><LayoutGrid size={18}/><span>Področja<strong>{tender.topics.length ? [...new Set(tender.topics)].join(' · ') : 'Ni podatka'}</strong></span></div><div><Hash size={18}/><span>CPV<strong>{tender.cpv.length ? tender.cpv.join(' · ') : 'Ni podatka'}</strong></span></div><div><CalendarDays size={18}/><span>Datum objave<strong>{date(tender.published_at)}</strong></span></div></div></div><div className="tabs detail-tabs">{[['conditions', `Pogoji (${tender.tender_conditions?.items.length || conditions.length})`], ['partners', 'Partnerji'], ...(tender.source_type === 'real' ? [['history', 'Podobni razpisi'], ['buyer-history', 'Zgodovina naročnika']] : []), ['submission', 'Preveri prijavo z AI']].map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} aria-pressed={tab === key} onClick={() => setTab(key)}>{label}</button>)}</div>
      {tab === 'overview' && <><section className="surface detail-section"><div className="section-heading"><h2><FileText size={19}/>Kaj naročnik potrebuje?</h2></div><TenderOverview tenderId={tender.id} revision={JSON.stringify([tender.version, tender.summary, tender.description, tender.documents])}/>{tender.description && tender.description !== tender.summary && <details className="quiet-disclosure"><summary>Celoten opis</summary><p className="muted prose">{tender.description}</p></details>}</section><TenderKeywords tender={tender} search={search}/><AttachmentOpportunities key={tender.id} tenderId={tender.id} revision={JSON.stringify([tender.version, data.profile.updated_at, tender.documents])}/><section className="surface detail-section"><div className="section-heading"><h2><Sparkles size={19}/>Zakaj je zanimiv za vas?</h2></div><div className="reason-list">{tender.match.reasons.map((reason, index) => <div key={index}><span><Check size={15}/></span><p>{reason}</p></div>)}</div>{tender.match.open_question && <div className="info-box amber"><CircleHelp size={18}/><p>{tender.match.open_question}</p></div>}</section>{tender.lots.length > 0 && <section className="surface detail-section"><h2><LayoutGrid size={19}/>Ujemanje po sklopih</h2>{tender.lots.map(lot => <div className="lot-card" key={lot.id}><div><h3>{lot.title}</h3><MatchBadge level={lot.match_level}/></div><p>{lot.summary}</p></div>)}</section>}</>}
    </div><aside className="detail-aside"><section className="decision-card"><div className="decision-label">AI PRESOJA ZA VAŠE PODJETJE</div><p className="detail-content-score">Ujemanje: <strong>{tender.match.score}/100</strong>{tender.match.warning && <small>{tender.match.warning}</small>}</p>{(tender.source_metadata?.attachment_url || tender.source_url) && <a className="button primary full-width" href={tender.source_metadata?.attachment_url || tender.source_url || undefined} target="_blank" rel="noopener noreferrer"><FileText size={16}/>Razpisna dokumentacija<ExternalLink size={14}/></a>}<button className="button full-width" onClick={() => setTab('submission')}><FileText size={16}/>Preveri prijavo</button></section></aside></div>
      {tab === 'submission' && <SubmissionReview key={tender.id} tenderId={tender.id}/>}
      {tab === 'history' && <PastAwardsPanel tenderId={tender.id}/>}
      {tab === 'buyer-history' && <BuyerHistoryPanel key={tender.id} tenderId={tender.id}><IncumbentsPanel key={`contracts-${tender.id}`} tenderId={tender.id}/></BuyerHistoryPanel>}
      {tab === 'partners' && <PartnersPanel tenderId={tender.id} companyId={`${data.profile.registration_number}:${data.profile.updated_at}`}/>}
      {tab === 'conditions' && <><section className="surface detail-section"><div className="condition-summary">{(['met', 'unknown', 'unmet'] as const).map(status => <div key={status}><strong>{displayedConditions.length ? conditionCounts[status] : '—'}</strong><StateBadge status={status}/></div>)}</div><p className="section-help">{displayedConditions.length ? `Število pogojev iz obdelane dokumentacije: ${displayedConditions.length}.${manualConditions ? ' Pogoji z oznako »Preverite sami« so vključeni med pogoje, ki potrebujejo dopolnitev oziroma preverjanje.' : ''}` : 'Statistika bo na voljo, ko bodo pogoji izluščeni iz dokumentacije.'}</p></section><section className="surface detail-section"><div className="section-heading"><div><h2>Pogoji razpisa</h2><p className="section-help">Vsi pogoji za sodelovanje iz dokumentacije, vsak z izvornim citatom. Kjer je mogoče, je pogoj preverjen s profilom podjetja.</p></div><button className="button small" disabled={!!busy} onClick={analyze}>{busy === 'analyze' ? <Spinner small/> : <RefreshCw size={14}/>}Osveži analizo</button></div><TenderConditionList data={tender.tender_conditions} answering={answering} onAnswer={(item, answer) => void answerCondition(item, answer)}/>{conditions.length > 0 && !tender.tender_conditions?.items.length && <><h3 className="conditions-subheading">Ali izpolnjujete pogoje?</h3><div className="conditions-table"><div className="conditions-header"><span>Pogoj iz dokumentacije</span><span>Vaše podjetje</span><span>Ugotovitev</span></div>{conditions.map(condition => <div className="condition-row" key={condition.id}><div><strong>{condition.title}</strong>{condition.document_id && condition.page && <a target="_blank" rel="noreferrer" href={`/api/documents/${condition.document_id}#page=${condition.page}`}><FileText size={12}/>Dokument, str. {condition.page}<ArrowUpRight size={12}/></a>}{condition.quote && <details className="evidence-quote"><summary>Poglej izvorno besedilo</summary><blockquote>»{condition.quote}«</blockquote></details>}</div><div>{condition.company_value || 'Podatek še ni na voljo'}</div><div><StateBadge status={condition.status} reason={condition.company_value}/></div></div>)}</div></>}<a href="#/profil" className="profile-callout"><Building2 size={19}/><div><strong>Manjka podatek o vašem podjetju?</strong><span>Dopolnite reference ali zmogljivosti in ponovno preverite ujemanje.</span></div><ArrowRight size={18}/></a></section></>}
  </>;
}
function ProfileOverview({ data, notify }: Shared) {
    const p = data.profile;
    const [removing, setRemoving] = useState('');
    const answers = [...(p.condition_answers ?? [])].reverse();
    const removeAnswer = async (answerId: string) => {
        setRemoving(answerId);
        try { applyConditionAnswers(await api<Profile>(`/profile/condition-answers/${encodeURIComponent(answerId)}`, { method: 'DELETE' })); notify('Oznaka pogoja je odstranjena iz profila.'); }
        catch (e) { notify((e as Error).message, true); }
        finally { setRemoving(''); }
    };
    const registry = p.registry_source;
    const Row = ({ label, children }: { label: string; children?: ReactNode }) => <div className="ov-row"><dt>{label}</dt><dd>{children || <span className="ov-empty">Ni podatka</span>}</dd></div>;
    const Chips = ({ items }: { items: string[] }) => items.length ? <span className="ov-chips">{items.map(i => <span key={i} className="ov-chip">{i}</span>)}</span> : null;
    const range = p.min_value != null || p.max_value != null ? `${p.min_value != null ? money(p.min_value) : '—'} – ${p.max_value != null ? money(p.max_value) : '—'}` : '';
    if (!p.name && !p.registration_number) return <>
        <section className="page-intro building-intro profile-intro" aria-labelledby="company-overview-title"><div className="page-heading"><div><h1 id="company-overview-title">Profil podjetja</h1><p>Podatki, s katerimi preverjamo ustreznost razpisov.</p></div></div></section>
        <section className="ov-empty-state"><Building2 size={28}/><h2>Podatkov o podjetju še ni</h2><p>Poiščite podjetje v AJPES ali preberite svojo spletno stran, da lahko pripravimo priporočila razpisov.</p><a className="button primary" href="#/profil/uredi"><Pencil size={16}/>Izpolni podatke o podjetju</a></section>
    </>;
    return <>
        <section className="page-intro building-intro profile-intro" aria-labelledby="company-overview-title"><div className="page-heading"><div><h1 id="company-overview-title">Profil podjetja</h1><p>Podatki, s katerimi preverjamo ustreznost razpisov.</p></div></div>
            <div className="profile-identity"><Building2 size={20}/><strong>{p.name || 'Vaše podjetje'}</strong></div><a className="button ov-edit-corner" href="#/profil/uredi" style={{ right: 16 + Math.max(0, window.innerWidth - document.documentElement.clientWidth) }}><Pencil size={15}/>Uredi podjetje</a></section>
        <div className="ov-grid">
            <div className="ov-col">
            <section className="surface ov-card"><h2>Podjetje</h2><dl>
                <Row label="Naziv">{p.name}</Row><Row label="Matična številka">{p.registration_number}</Row><Row label="Naslov">{p.address}</Row>
                <Row label="Spletna stran">{p.website && <a href={p.website} target="_blank" rel="noreferrer">{p.website}<ExternalLink size={12}/></a>}</Row>
            </dl>{registry && <small className="ov-source">Osnovni podatki: AJPES / OPSI · prevzeto {date(registry.retrieved_at)}</small>}</section>
            <section className="surface ov-card"><h2>Dejavnost in opis</h2><dl><Row label="Dejavnost">{p.activity}</Row><Row label="Kaj podjetje počne">{p.description}</Row></dl></section>
            <section className="surface ov-card"><h2>Ekipa in zmogljivosti</h2><dl>
                <Row label="Razpoložljivi strokovnjaki">{p.staff_count != null ? String(p.staff_count) : ''}</Row><Row label="Razpoložljivi od">{p.available_from ? date(p.available_from) : ''}</Row>
                <Row label="Certifikati"><Chips items={p.certifications}/></Row><Row label="Kapacitete">{p.capacity}</Row>
            </dl></section>
            </div>
            <div className="ov-col">
            <section className="surface ov-card"><h2>Področje delovanja</h2><dl>
                <Row label="Strokovna področja"><Chips items={p.expertise}/></Row><Row label="Tehnologije"><Chips items={p.technologies}/></Row><Row label="Ključne besede"><Chips items={p.keywords}/></Row>
                <Row label="Izključena področja"><Chips items={p.excluded_keywords}/></Row><Row label="Lokacije izvedbe"><Chips items={p.regions}/></Row><Row label="Želena vrednost razpisov">{range}</Row>
            </dl></section>
            </div>
            <section className="surface ov-card ov-wide"><div className="ov-card-head"><h2>Reference <span>{p.references.length}</span></h2></div>
                {p.references.length ? <ul className="ov-refs">{p.references.map(r => <li key={r.id}><div><strong>{r.title || 'Brez naslova'}</strong>{r.description && <p>{r.description}</p>}</div><div className="ov-ref-meta"><span>{r.year ?? 'Leto ni znano'}</span><span>{money(r.value)}</span>{r.confirmed ? <Badge tone="green">Potrjeno</Badge> : <Badge tone="amber">Nepotrjeno</Badge>}</div></li>)}</ul> : <p className="ov-empty">Referenc še ni. <a href="#/profil/uredi">Dodajte prvo referenco</a></p>}
            </section>
            <section className="surface ov-card ov-wide"><div className="ov-card-head"><h2>Označeni pogoji razpisov <span>{answers.length}</span></h2></div>
                <p className="section-help">Pogoji, za katere ste pri razpisih označili, ali jih izpolnjujete. Upoštevamo jih tudi pri drugih razpisih s podobnim pogojem z enakimi pragovi.</p>
                {answers.length ? <ul className="ov-refs ov-condition-answers">{answers.map(a => <li key={a.id}><div><strong>{a.title}</strong>{a.requirement && a.requirement !== a.title && <p>{a.requirement}</p>}<p>Označeno pri razpisu <a href={`#/razpisi/${encodeURIComponent(a.tender_id)}`}>{a.tender_title || a.tender_id}</a> · {date(a.updated_at)}</p></div><div className="ov-ref-meta"><span className={`condition-state ${a.answer}`}>{a.answer === 'met' ? <CheckCircle2 size={15}/> : <AlertCircle size={15}/>}{a.answer === 'met' ? 'Izpolnjujemo' : 'Ne izpolnjujemo'}</span><button type="button" className="icon-button" aria-label={`Odstrani oznako: ${a.title}`} title="Odstrani iz profila" disabled={removing === a.id} onClick={() => void removeAnswer(a.id)}>{removing === a.id ? <Spinner small/> : <Trash2 size={16}/>}</button></div></li>)}</ul> : <p className="ov-empty">Še niste označili nobenega pogoja. Pri pregledu pogojev razpisa izberite »Izpolnjujemo« ali »Ne izpolnjujemo«.</p>}
            </section>
        </div>
    </>;
}
function ProfilePage({ data, refresh, notify }: Shared) {
    const [profileTab, setProfileTab] = useState('basic');
    const [isNew, setIsNew] = useState(false);
    const [partnerManager, setPartnerManager] = useState(false);
    const [draft, setDraft] = useState<Profile>(() => structuredClone(data.profile));
    const [busy, setBusy] = useState(false);
    const [prefillBusy, setPrefillBusy] = useState(false);
    const [importStep, setImportStep] = useState<'ajpes' | 'web'>('ajpes');
    const [replacingCompany, setReplacingCompany] = useState(false);
    // Unsaved website suggestions; kept when an AJPES lookup replaces the company identity.
    const [websitePatch, setWebsitePatch] = useState<WebsitePatch | null>(null);
    const [prefill, setPrefill] = useState<{
        profile: Profile;
        source: string;
        message: string;
        warning?: string;
        mode?: string;
    } | null>(null);
    const registry = draft.registry_source && companyIdentity(draft.registration_number) === draft.registry_source.registration_number ? draft.registry_source : undefined;
    const origin = (key: 'name' | 'address' | 'registration_number') => registry && (key === 'registration_number' ? companyIdentity(draft[key]) === registry[key] : draft[key] === registry[key]) ? `AJPES / OPSI · prevzeto ${date(registry.retrieved_at)}` : 'Uporabniški vnos';
    const sameCompany = prefill?.source === 'ajpes' && companyIdentity(draft.registration_number) === prefill.profile.registration_number && (registry?.registration_number === prefill.profile.registration_number || companyIdentity(data.profile.registration_number) === prefill.profile.registration_number);
    const applyPrefill = () => {
        if (!prefill) return;
        if (sameCompany) setDraft({ ...draft, name: prefill.profile.name, registration_number: prefill.profile.registration_number, address: prefill.profile.address, registry_source: prefill.profile.registry_source });
        else if (prefill.source === 'ajpes') {
            // A different company drops the previous company's data, but not what was just read from its website.
            const typedWebsite = draft.website !== data.profile.website ? { website: draft.website } : {};
            const base = { ...structuredClone(prefill.profile), ...typedWebsite };
            setDraft(websitePatch ? mergeWebsite(base, websitePatch) : base);
        }
        else { setDraft(structuredClone(prefill.profile)); setWebsitePatch(null); }
        setPrefill(null);
        if (prefill.source === 'ajpes') setImportStep('web');
        notify('Podatki so v obrazcu. Preverite jih in shranite profil.');
    };
    const applyWebsite = (patch: WebsitePatch) => {
        setWebsitePatch(old => old ? mergeWebsite(old, patch) : patch);
        setDraft(old => mergeWebsite(old, patch));
        notify('Predlogi s spletne strani so v obrazcu. Preverite jih in shranite profil.');
    };
    useEffect(() => { setDraft(structuredClone(data.profile)); setWebsitePatch(null); }, [data.profile.id, data.profile.updated_at]);
    const discardChanges = () => (JSON.stringify(draft) === JSON.stringify(data.profile) && !isNew) || window.confirm('Neshranjene spremembe bodo zavržene. Nadaljujem?');
    const startNew = () => {
        setIsNew(true); setProfileTab('basic'); setWebsitePatch(null); setPrefill(null);
        setDraft({ id: 0, name: '', registration_number: '', activity: '', address: '', website: '', description: '', expertise: [], technologies: [], keywords: [], excluded_keywords: [], regions: [], min_value: null, max_value: null, available_from: '', staff_count: null, certifications: [], capacity: '', source: 'user', references: [] });
    };
    useEffect(() => { if (window.location.hash.includes('novo')) startNew(); }, []);
    const switchCompany = async (id: string) => {
        if (!discardChanges()) return;
        if (Number(id) === data.profile.id) { setIsNew(false); setDraft(structuredClone(data.profile)); setWebsitePatch(null); setPrefill(null); return; }
        setBusy(true);
        try { await post(`/profiles/${id}/activate`); await refresh(); notify('Podjetje je izbrano. Priporočila so osvežena.'); }
        catch (e) { notify((e as Error).message, true); }
        finally { setBusy(false); }
    };
    useEffect(() => { setReplacingCompany(false); }, [registry?.registration_number]);
    const set = <K extends keyof Profile>(key: K, value: Profile[K]) => setDraft(old => ({ ...old, [key]: value }));
    const setRef = (index: number, patch: Partial<CompanyReference>) => setDraft(old => ({ ...old, references: old.references.map((ref, i) => i === index ? { ...ref, ...patch } : ref) }));
    const filled = [draft.name, draft.description, draft.expertise.length, draft.technologies.length, draft.staff_count != null, draft.references.length > 0 && draft.references.every(r => r.confirmed && r.value != null && r.year != null), draft.capacity, draft.regions.length].filter(Boolean).length;
    const completeness = Math.round(filled / 8 * 100);
    const save = async (e: FormEvent) => { e.preventDefault(); setBusy(true); try {
        const firstSave = isNew || data.profile.source !== 'user';
        const saved = await api<Profile>(isNew ? '/profiles' : '/profile', { method: isNew ? 'POST' : 'PUT', body: JSON.stringify({ ...draft, id: isNew ? 0 : data.profile.id, source: 'user' }) });
        setIsNew(false);
        track('profile_saved', { references: draft.references.length, completeness });
        // The response is the saved profile, so the workspace updates without reloading /bootstrap.
        // Tender lists refetch in the background; AI relevance and suggestions follow shortly after.
        applySavedProfile(saved);
        notify('Profil je shranjen. Priporočila se posodabljajo.');
        navigate(firstSave ? '/razpisi' : '/profil');
    }
    catch (e) {
        notify((e as Error).message, true);
    }
    finally {
        setBusy(false);
    } };
    const loadPrefill = async (provider: 'ajpes', number?: string) => { setPrefillBusy(true); try {
        setPrefill(await post('/profile/prefill', { provider, registration_number: number }));
    }
    catch (e) {
        notify((e as Error).message, true);
    }
    finally {
        setPrefillBusy(false);
    } };
    return <><section className="page-intro building-intro profile-intro" aria-labelledby="company-profile-title"><div className="page-heading"><div><a className="back-link" href="#/profil"><ArrowLeft size={16}/>Nazaj na pregled profila</a><h1 id="company-profile-title">Urejanje profila</h1><p>Podatki, s katerimi preverjamo ustreznost razpisov.</p></div></div>{(data.profiles.length > 1 || isNew) && <div className="saved-companies"><label className="field"><span>Shranjena podjetja</span><select aria-label="Izberi shranjeno podjetje" value={isNew ? 'new' : data.profile.id} disabled={busy || prefillBusy} onChange={e => void switchCompany(e.target.value)}>{isNew && <option value="new" disabled>Novo podjetje</option>}{data.profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name || 'Novo podjetje'}{profile.registration_number ? ` · ${profile.registration_number}` : ''}</option>)}</select></label>{isNew && <button className="button" type="button" disabled={busy} onClick={() => void switchCompany(String(data.profile.id))}>Prekliči</button>}</div>}<div className="profile-identity"><Building2 size={20}/><strong>{draft.name || 'Vaše podjetje'}</strong><Badge tone="neutral">{registry ? 'AJPES / OPSI' : 'Uporabniški podatki'}</Badge>{(isNew || data.profile.source !== 'user') && <span>{completeness} % izpolnjeno</span>}</div></section><div className="tabs profile-tabs" aria-label="Deli profila">{[['basic', 'Osnovni podatki'], ['expertise', 'Področje delovanja'], ['references', 'Reference'], ['team', 'Ekipa in certifikati']].map(([key, label]) => <button key={key} className={profileTab === key ? 'active' : ''} aria-pressed={profileTab === key} onClick={() => setProfileTab(key)}>{label}{key === 'references' && <span>{draft.references.length}</span>}</button>)}</div><div className="profile-layout"><form id="company-profile-form" className="profile-form" onSubmit={save} onInvalidCapture={e => { const field = e.target as HTMLInputElement; const panel = field.closest<HTMLElement>('[data-profile-section]')?.dataset.profileSection; if (panel) { setProfileTab(panel); requestAnimationFrame(() => field.focus()); } }}><section className="surface profile-section" data-profile-section="basic" hidden={profileTab !== 'basic'}><div className="section-heading"><h2><span className="step-number">1</span>Osnovni podatki</h2><Badge tone="amber">{registry ? 'AJPES + dopolnitve' : 'Uporabniški profil'}</Badge></div><div className="import-panel"><div className="import-steps" role="tablist" aria-label="Predizpolnitev profila">{([['ajpes', 'Poiščite podjetje v AJPES', Building2], ['web', 'Preberite svojo spletno stran', Globe]] as const).map(([key, label, Icon], i) => <button key={key} type="button" role="tab" aria-selected={importStep === key} className={importStep === key ? 'active' : ''} onClick={() => setImportStep(key)}><span className="import-step-num">{key === 'ajpes' && registry ? <Check size={13}/> : i + 1}</span><Icon size={15}/>{label}</button>)}</div>
<div className="import-body" hidden={importStep !== 'ajpes'}><p className="import-hint">Uvozite naziv, matično številko in naslov iz uradnega registra.</p>{registry && !replacingCompany ? <div className="company-summary"><div><strong>{registry.name || draft.name}</strong><span>{draft.address}</span><small>Matična: {registry.registration_number} · AJPES / OPSI</small></div><button type="button" className="button small" onClick={() => setReplacingCompany(true)}>Zamenjaj</button></div> : <CompanySearch selecting={prefillBusy} onSelect={number => loadPrefill('ajpes', number)}/>}{registry && !replacingCompany && <button type="button" className="button small primary import-next" onClick={() => setImportStep('web')}>Naprej: spletna stran<ArrowRight size={14}/></button>}</div>
<div className="import-body" hidden={importStep !== 'web'}><p className="import-hint">Iz javne spletne strani predlagamo dejavnost, opis, področja in tehnologije. Vsak predlog ima citat in povezavo do vira.</p><WebsiteImport key={`${data.profile.id}:${data.profile.website}`} initial={draft.website} onUrlChange={v => set('website', v)} onApply={applyWebsite} registrationNumber={companyIdentity(draft.registration_number)} registryBusy={prefillBusy} onRegistry={number => loadPrefill('ajpes', number)}/></div></div>
<div className="form-group"><h3 className="form-group-title">Podjetje</h3><div className="form-grid"><Field label="Naziv podjetja" filled={!!draft.name.trim()} tag={registry && origin('name').startsWith('AJPES') ? 'AJPES' : undefined} tagTitle={origin('name')}><input required value={draft.name} onChange={e => set('name', e.target.value)}/></Field><Field label="Matična številka" filled={!!draft.registration_number.trim()} tag={registry && origin('registration_number').startsWith('AJPES') ? 'AJPES' : undefined} tagTitle={origin('registration_number')}><input value={draft.registration_number} onChange={e => {
        const value = e.target.value;
        setDraft(old => companyIdentity(value) === companyIdentity(old.registration_number)
            ? { ...old, registration_number: value }
            : { ...old, registration_number: value, employment_report: null });
    }}/></Field><Field label="Naslov" filled={!!draft.address.trim()} tag={registry && origin('address').startsWith('AJPES') ? 'AJPES' : undefined} tagTitle={origin('address')} className="span-two"><input value={draft.address} onChange={e => set('address', e.target.value)}/></Field></div></div>
<div className="form-group"><h3 className="form-group-title">Dejavnost in opis</h3><div className="form-grid"><Field label="Dejavnost" filled={!!draft.activity.trim()} hint="AJPES tega podatka ne vsebuje; predlagamo ga lahko s spletne strani." className="span-two"><input value={draft.activity} onChange={e => set('activity', e.target.value)}/></Field><Field label="Kaj vaše podjetje počne?" filled={!!draft.description.trim()} hint="Opišite storitve in probleme, ki jih rešujete. Konkretni primeri pomagajo pri vsebinskem ujemanju." className="span-two"><textarea rows={4} value={draft.description} onChange={e => set('description', e.target.value)}/></Field></div></div></section><section className="surface profile-section" data-profile-section="expertise" hidden={profileTab !== 'expertise'}><div className="section-heading"><h2><span className="step-number">2</span>Področje delovanja</h2><Badge>Uporabniški vnos</Badge></div><div className="form-grid"><Field label="Strokovna področja" className="span-two"><ChipInput label="Strokovna področja" value={draft.expertise} onChange={v => set('expertise', v)} placeholder="Na primer: spletne aplikacije, IoT, energetika"/></Field><Field label="Tehnologije" className="span-two"><ChipInput label="Tehnologije" value={draft.technologies} onChange={v => set('technologies', v)}/></Field><Field label="Ključne besede"><ChipInput label="Ključne besede podjetja" value={draft.keywords} onChange={v => set('keywords', v)}/></Field><Field label="Kaj vas ne zanima?"><ChipInput label="Izključena področja podjetja" value={draft.excluded_keywords} onChange={v => set('excluded_keywords', v)} placeholder="Na primer: samo dobava licenc"/></Field><Field label="Lokacije izvedbe" className="span-two"><ChipInput label="Lokacije izvedbe" value={draft.regions} onChange={v => set('regions', v)}/></Field><Field label="Želena najmanjša vrednost (€)"><input type="number" min="0" value={draft.min_value ?? ''} onChange={e => set('min_value', e.target.value === '' ? null : Number(e.target.value))}/></Field><Field label="Želena največja vrednost (€)"><input type="number" min="0" value={draft.max_value ?? ''} onChange={e => set('max_value', e.target.value === '' ? null : Number(e.target.value))}/></Field></div></section><section className="surface profile-section" id="reference" data-profile-section="references" hidden={profileTab !== 'references'}><div className="section-heading"><div><h2><span className="step-number">3</span>Reference in izkušnje</h2><p className="section-help">Vrednost in leto zaključka omogočata preverjanje referenčnih pogojev.</p></div><button type="button" className="button small" onClick={() => set('references', [...draft.references, { id: `ref-${Date.now()}`, title: '', description: '', domain: '', value: null, year: null, confirmed: false }])}><Plus size={15}/>Dodaj referenco</button></div>{!isNew && <AwardReferencesPanel key={data.profile.registration_number} registrationNumber={data.profile.registration_number} references={draft.references} onAdd={refs => { track('award_references_added', { count: refs.length }); set('references', [...draft.references, ...refs]); }}/>}{draft.references.map((ref, index) => <div className="reference-editor" key={ref.id}><div className="reference-title"><span><FileText size={16}/>Referenca {index + 1}</span><button type="button" className="icon-button danger-hover" aria-label={`Odstrani referenco ${index + 1}`} onClick={() => set('references', draft.references.filter((_, i) => i !== index))}><Trash2 size={16}/></button></div><div className="form-grid"><Field label="Ime projekta" className="span-two"><input value={ref.title} onChange={e => setRef(index, { title: e.target.value })}/></Field><Field label="Področje"><select value={ref.domain} onChange={e => setRef(index, { domain: e.target.value })}><option value="">Izberite področje</option><option value="energy">Energetika in IoT</option><option value="sport">Športne platforme</option><option value="satellite">Satelitski podatki</option><option value="software">Razvoj programske opreme</option><option value="construction">Gradbeništvo</option><option value="other">Drugo</option>{ref.domain && !['energy', 'sport', 'satellite', 'software', 'construction', 'other'].includes(ref.domain) && <option value={ref.domain}>{ref.domain}</option>}</select></Field><Field label="Leto zaključka"><input type="number" min="1900" max="2100" placeholder="Ni podatka" value={ref.year ?? ''} onChange={e => setRef(index, { year: e.target.value === '' ? null : Number(e.target.value) })}/></Field><Field label="Vrednost izvedenih del (€)" className="span-two"><input type="number" min="0" placeholder="Ni podatka" value={ref.value ?? ''} onChange={e => setRef(index, { value: e.target.value === '' ? null : Number(e.target.value) })}/></Field><Field label="Vaša vloga in opravljena dela" className="span-two"><textarea rows={2} value={ref.description} onChange={e => setRef(index, { description: e.target.value })}/></Field></div><details className="quiet-disclosure reference-evidence-fields"><summary>Identifikator projekta in dokazilo za skupno prijavo</summary><div className="form-grid"><Field label="Identifikator projekta" hint="Enaka oznaka za isti projekt pri obeh podjetjih."><input value={ref.project_identifier || ''} onChange={e => setRef(index, { project_identifier: e.target.value })}/></Field><Field label="Vir dokazila"><input value={ref.evidence_source || ''} onChange={e => setRef(index, { evidence_source: e.target.value })}/></Field><Field label="Povezava do dokazila"><input type="url" value={ref.evidence_url || ''} onChange={e => setRef(index, { evidence_url: e.target.value })}/></Field></div></details><label className="checkbox-row reference-confirm"><input type="checkbox" checked={ref.confirmed} onChange={e => setRef(index, { confirmed: e.target.checked })}/><span>Podatki o referenci so uporabniško potrjeni.</span></label>{(ref.value == null || ref.year == null) && <div className="reference-warning"><CircleHelp size={14}/>Dopolnite {ref.value == null && ref.year == null ? 'vrednost in leto' : ref.value == null ? 'vrednost' : 'leto'} reference za natančnejšo presojo.</div>}</div>)}</section><section className="surface profile-section" data-profile-section="team" hidden={profileTab !== 'team'}><div className="section-heading"><h2><span className="step-number">4</span>Ekipa in zmogljivosti</h2></div><div className="form-grid"><Field label="Število razpoložljivih strokovnjakov"><input type="number" min="0" placeholder="Ni podatka" value={draft.staff_count ?? ''} onChange={e => set('staff_count', e.target.value === '' ? null : Number(e.target.value))}/></Field><Field label="Letno povprečje zaposlenih iz AJPES (JOLP)" hint="Uporabite podatek na podlagi delovnih ur iz letnega poročila.">
        <input type="number" min="0" max="1000000000000" step="0.01" placeholder="Ni podatka" required={draft.employment_report?.year != null} value={draft.employment_report?.average ?? ''} onChange={e => {
            const average = e.target.value === '' ? null : Number(e.target.value);
            const year = draft.employment_report?.year ?? null;
            set('employment_report', average === null && year === null ? null : { average, year });
        }}/>
    </Field><Field label="Leto poročila AJPES">
        <input type="number" min="1900" max={new Date().getFullYear()} placeholder="Ni podatka" required={draft.employment_report?.average != null} value={draft.employment_report?.year ?? ''} onChange={e => {
            const year = e.target.value === '' ? null : Number(e.target.value);
            const average = draft.employment_report?.average ?? null;
            set('employment_report', average === null && year === null ? null : { average, year });
        }}/>
    </Field><Field label="Razpoložljivi od"><input type="date" value={draft.available_from || ''} onChange={e => set('available_from', e.target.value)}/></Field><div className="field span-two"><span>Certifikati in dokazila</span><CertificationSelect key={data.profile.registration_number} value={draft.certifications} onChange={v => set('certifications', v)}/></div><Field label="Dodatne informacije o kapacitetah" className="span-two"><textarea rows={3} value={draft.capacity} onChange={e => set('capacity', e.target.value)} placeholder="Na primer: vzporedno lahko izvedemo dva srednje velika projekta."/></Field></div><div className="profile-partners"><div><strong>Partnerji za skupno prijavo</strong><p>Podjetja in dokazila za dopolnitev manjkajočih pogojev.</p></div><button type="button" className="button small" disabled={isNew || companyIdentity(draft.registration_number).toLowerCase() !== companyIdentity(data.profile.registration_number).toLowerCase() || (!draft.registration_number && (draft.name !== data.profile.name || draft.address !== data.profile.address))} title="Partnerji so vezani na shranjeno identiteto podjetja. Ob menjavi najprej shranite profil." onClick={() => setPartnerManager(true)}><Users size={16}/>Upravljaj partnerje</button></div></section><div className="profile-savebar"><div><ShieldCheck size={16}/><span>Spremembe se uporabijo po shranjevanju.</span></div><button className="button primary" disabled={busy}>{busy ? <Spinner small/> : <Save size={17}/>}Shrani profil</button></div></form>{!isNew && <CompanyDataSources key={JSON.stringify([data.profile.id, data.profile.registration_number])} profileId={data.profile.id} registrationNumber={data.profile.registration_number}/>}<details className="quiet-disclosure profile-source"><summary>Od kod so podatki?</summary><div className="source-card"><h4><Building2 size={15}/>O tem profilu</h4><p>{registry ? 'Označena osnovna polja izvirajo iz AJPES prek OPSI. Reference, tehnologije in zmogljivosti so uporabniško vnesene.' : 'Podatki so uporabniško vneseni.'}</p>{registry && <><a href={registry.url} target="_blank" rel="noreferrer">{registry.attribution}<ExternalLink size={13}/></a><small>Prevzeto: {date(registry.retrieved_at)} · {registry.license}</small><small>Posodobitev zbirke: {date(registry.dataset_updated_at)}</small></>}</div></details></div>{partnerManager && <PartnerManager key={`${data.profile.registration_number}:${data.profile.name}:${data.profile.address}`} close={() => setPartnerManager(false)}/>}{prefill && <Modal title="Preverite predizpolnjeni profil" description={prefill.message} close={() => setPrefill(null)}><Badge tone={prefill.source === 'ajpes' ? 'green' : 'amber'}>AJPES / OPSI · pravi podatki</Badge><div className="prefill-preview"><h3>{prefill.profile.name}</h3><p>Matična številka: {prefill.profile.registration_number}</p><p>{prefill.profile.address}</p>{prefill.profile.registry_source && <><p>{prefill.profile.registry_source.legal_form}</p><small>Prevzeto: {date(prefill.profile.registry_source.retrieved_at)} · Posodobitev zbirke: {date(prefill.profile.registry_source.dataset_updated_at)}</small></>}</div>{prefill.warning && <div className="info-box"><AlertCircle size={17}/><p>{prefill.warning}</p></div>}<div className="info-box"><CircleHelp size={17}/><p>{sameCompany ? 'Osvežili se bodo osnovni podatki istega podjetja. Vaše dopolnitve in reference ostanejo v obrazcu.' : prefill.source === 'ajpes' ? (websitePatch ? 'Izbirate drugo podjetje. Predlogi s spletne strani ostanejo v obrazcu; prejšnje reference, kadri in zmogljivosti bodo odstranjeni, da jih ne pripišemo drugemu podjetju.' : 'Izbirate drugo podjetje. Trenutne reference, tehnologije in zmogljivosti bodo iz obrazca odstranjene, da jih ne pripišemo drugemu podjetju.') : 'Podatki bodo zamenjali trenutni obrazec.'} V bazo se shrani šele z gumbom »Shrani profil«.</p></div><div className="modal-actions"><button className="button" onClick={() => setPrefill(null)}>Prekliči</button><button className="button primary" onClick={applyPrefill}><Check size={16}/>Uporabi podatke</button></div></Modal>}</>;
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
