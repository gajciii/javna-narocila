import { useEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, Bell, CalendarDays, Check, CheckCheck, CircleHelp, FileText, Lightbulb, LoaderCircle, Plus, Save, ShieldCheck, Sparkles, Trash2, X } from 'lucide-react';
import { api, post } from './api';
import type { Bootstrap, Condition, ImprovementAction, ImprovementEvaluation, ImprovementImpact, ImprovementPlan, Notification } from './types';

type Props = { data: Bootstrap; refresh: () => Promise<void>; notify: (message: string, error?: boolean) => void };
const stateNames = { met: 'Izpolnjen', unknown: 'Potrebno preveriti', unmet: 'Ni izpolnjen' };
const recommendationNames = { recommended: 'Priporočeno za pregled', review: 'Potrebno preveriti', unsuitable: 'Ni primerno', closed: 'Zaključen razpis' };
const eventNames = { new: 'Nova priložnost', correction: 'Sprememba pogojev', deadline: 'Sprememba roka', improvement: 'Predlog za razvoj' };
const formatDate = (value: string) => new Date(value).toLocaleString('sl-SI', { timeZone: 'Europe/Ljubljana', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

function Evidence({ condition }: { condition: Condition }) {
    return <div className="improvement-evidence">{condition.document_id && <a href={`/api/documents/${condition.document_id}#page=${condition.page || 1}`} target="_blank" rel="noreferrer"><FileText size={13}/>Dokument, str. {condition.page || 1}<ArrowUpRight size={12}/></a>}{condition.quote && <details className="quiet-disclosure"><summary>Izvorno besedilo</summary><blockquote>»{condition.quote}«</blockquote></details>}</div>;
}

function ImpactCard({ row }: { row: ImprovementImpact }) {
    return <article className="impact-card">
        <a className="impact-title" href={`#/razpisi/${row.id}`}>{row.title}<ArrowUpRight size={16}/></a>
        {row.status === 'open' ? <div className="recommendation-comparison"><span>{recommendationNames[row.before_recommendation]}</span><ArrowRight size={14}/><strong>{recommendationNames[row.after_recommendation]}</strong></div> : <p className="muted small-text">Pretekli razpis · primerjava z današnjim profilom</p>}
        {row.changes.map(change => <div className="condition-comparison" key={`${change.before.document_id}-${change.before.id}`}>
            <strong>{change.before.title}</strong>
            <div className="condition-columns"><div><small>ZDAJ</small><span className={`condition-state ${change.before.status}`}>{stateNames[change.before.status]}</span><p>{change.before.company_value}</p></div><ArrowRight size={16}/><div><small>PO IZBOLJŠAVI · PREDPOSTAVKA</small><span className={`condition-state ${change.after.status}`}>{change.improved ? 'Izpolnjen ob predpostavki' : 'Manjka podatek'}</span><p>{change.after.company_value}</p></div></div>
            <Evidence condition={change.before}/>
        </div>)}
        {row.remaining_conditions.length > 0 && <div className="remaining-conditions"><strong><CircleHelp size={15}/>Kaj še ostaja odprto?</strong><ul>{row.remaining_conditions.map(c => <li key={`${c.document_id}-${c.id}`}>{c.title} <span>— {stateNames[c.status]}</span><Evidence condition={c}/></li>)}</ul></div>}
        {row.documentation_incomplete && <p className="improvement-caution">Celotna dokumentacija še ni preverjena; izpolnitve vseh pogojev ni mogoče potrditi.</p>}
    </article>;
}

function Summary({ result }: { result: ImprovementEvaluation }) {
    const summary = result.summary.open;
    return <div className="improvement-stats"><div><strong>{summary.affected_tenders}</strong><span>odprtih razpisov z dodatno izpolnjenim pogojem</span></div><div><strong>{summary.newly_recommended}</strong><span>novo priporočenih za pregled</span></div><div><strong>{summary.needs_data}</strong><span>odprtih razpisov z manjkajočimi podatki</span></div></div>;
}

export default function NotificationsPage({ data, refresh, notify }: Props) {
    const [tab, setTab] = useState('all');
    const [combining, setCombining] = useState(false);
    const [source, setSource] = useState('all');
    const [busy, setBusy] = useState(false);
    const [plans, setPlans] = useState<ImprovementPlan[]>([]);
    const [plansError, setPlansError] = useState('');
    const [selected, setSelected] = useState<number[]>([]);
    const [inspection, setInspection] = useState<{ result: ImprovementEvaluation; planId?: number } | null>(null);
    const [name, setName] = useState('');
    const [impactTab, setImpactTab] = useState<'open' | 'historical'>('open');
    const [deleting, setDeleting] = useState<number | null>(null);
    const closeRef = useRef<HTMLButtonElement>(null);
    const identity = data.profile.registration_number || `${data.profile.name}|${data.profile.address}`;
    const loadPlans = async () => { try { setPlans(await api<ImprovementPlan[]>('/improvement-plans')); setPlansError(''); } catch (e) { setPlansError((e as Error).message); } };
    useEffect(() => { setInspection(null); setSelected([]); setPlans([]); void loadPlans(); }, [identity]);
    useEffect(() => { if (tab === 'plans') void loadPlans(); }, [tab]);
    useEffect(() => {
        if (!inspection) return;
        const previous = document.activeElement as HTMLElement | null;
        closeRef.current?.focus();
        const key = (event: KeyboardEvent) => {
            if (event.key === 'Escape' && !busy) setInspection(null);
            if (event.key === 'Tab') {
                const dialog = closeRef.current?.closest('[role="dialog"]');
                const nodes = dialog?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled)');
                if (!nodes?.length) return;
                const first = nodes[0], last = nodes[nodes.length - 1];
                if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
                else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
            }
        };
        document.addEventListener('keydown', key);
        return () => { document.removeEventListener('keydown', key); previous?.focus(); };
    }, [!!inspection, busy]);
    const run = async (operation: () => Promise<void>) => { setBusy(true); try { await operation(); } catch (e) { notify((e as Error).message, true); } finally { setBusy(false); } };
    const suggestions = data.notifications.filter(n => n.type === 'improvement');
    const chosen = suggestions.filter(n => selected.includes(n.id));
    const unread = data.notifications.filter(n => !n.read).length;
    const notifications = data.notifications.filter(n => (tab === 'all' || tab === 'unread' && !n.read || tab === 'improvements' && n.type === 'improvement') && (source === 'all' || (n.is_demo ? 'demo' : 'real') === source));
    const read = (id?: number) => run(async () => { await post('/notifications/read', id === undefined ? {} : { id }); await refresh(); });
    const show = (items: Notification[]) => run(async () => {
        if (!items.length) return;
        const sourceType = items[0].improvement!.source_type;
        if (items.some(n => n.improvement?.source_type !== sourceType)) throw new Error('Demo in resnične predloge združite v ločena načrta.');
        const result = await post<ImprovementEvaluation>('/improvements/evaluate', { source_type: sourceType, actions: items.flatMap(n => n.improvement!.actions) });
        for (const item of items) if (!item.read) await post('/notifications/read', { id: item.id });
        await refresh(); setInspection({ result }); setName(items.length === 1 ? items[0].title.slice(0, 100) : 'Načrt razvoja kompetenc'); setImpactTab(result.open.length ? 'open' : 'historical');
    });
    const openPlan = (id: number) => run(async () => { const plan = await api<ImprovementPlan>(`/improvement-plans/${id}`); setInspection({ result: plan.evaluation, planId: plan.id }); setName(plan.name); setImpactTab(plan.evaluation.open.length ? 'open' : 'historical'); });
    const save = () => run(async () => {
        if (!inspection) return;
        const payload = { name, actions: inspection.result.actions, source_type: inspection.result.source_type };
        const plan = inspection.planId ? await api<ImprovementPlan>(`/improvement-plans/${inspection.planId}`, { method: 'PUT', body: JSON.stringify(payload) }) : await post<ImprovementPlan>('/improvement-plans', payload);
        setInspection({ result: plan.evaluation, planId: plan.id }); await loadPlans(); await refresh(); notify('Razvojni načrt je shranjen. Dejanski profil ostaja nespremenjen.');
    });
    const removeAction = (index: number) => run(async () => {
        if (!inspection || inspection.result.actions.length <= 1) return;
        const result = await post<ImprovementEvaluation>('/improvements/evaluate', { source_type: inspection.result.source_type, actions: inspection.result.actions.filter((_, i) => i !== index) });
        setInspection({ ...inspection, result });
    });
    const addToPlan = (plan: ImprovementPlan) => run(async () => {
        const actions: ImprovementAction[] = [...plan.actions, ...chosen.flatMap(n => n.improvement!.actions)];
        const result = await post<ImprovementEvaluation>('/improvements/evaluate', { source_type: plan.source_type, actions });
        setInspection({ planId: plan.id, result }); setName(plan.name); setImpactTab('open');
    });
    return <>
        <div className="page-heading"><div><h1>Obvestila</h1><p>Spremembe razpisov in predlogi, kako izboljšati primernost podjetja.</p></div><button className="button ghost" disabled={busy || !unread} onClick={() => read()}><CheckCheck size={17}/>Označi vse kot prebrano</button></div>
        <div className="tabs notification-tabs">{[['all', 'Vsa', data.notifications.length], ['unread', 'Neprebrana', unread], ['improvements', 'Predlogi za razvoj', suggestions.length], ['plans', 'Shranjeni načrti', plans.length]].map(([value, title, count]) => <button key={value} className={tab === value ? 'active' : ''} aria-pressed={tab === value} onClick={() => { setTab(String(value)); setCombining(false); setSelected([]); }}>{title}<span>{count}</span></button>)}</div>
        <div className="improvement-toolbar"><label>Vir podatkov <select aria-label="Vir obvestil" value={source} onChange={e => { setSource(e.target.value); setSelected([]); }}><option value="all">Vsi viri</option><option value="real">Resnični razpisi</option><option value="demo">Demo primeri</option></select></label>{tab === 'improvements' && suggestions.length > 1 && <button className="button small" onClick={() => { setCombining(!combining); setSelected([]); }}>{combining ? 'Prekliči izbor' : 'Združi predloge'}<Plus size={14}/></button>}{chosen.length > 0 && <button className="button primary small" disabled={busy} onClick={() => show(chosen)}><Plus size={16}/>Združi izbrane ({chosen.length})</button>}</div>
        {chosen.length > 0 && plans.some(p => p.source_type === chosen[0].improvement?.source_type) && <div className="plan-merge-row"><span>Ali dodajte v načrt:</span>{plans.filter(p => p.source_type === chosen[0].improvement?.source_type).map(p => <button className="button small" key={p.id} disabled={busy} onClick={() => addToPlan(p)}>{p.name}<Plus size={13}/></button>)}</div>}
        <div className="notification-layout"><section className="notifications-list">
            {tab === 'plans' ? <>{plansError && <div className="error-banner">{plansError}<button onClick={loadPlans}>Poskusi znova</button></div>}{plans.filter(p => source === 'all' || p.source_type === source).map(plan => <article className="notification-card saved-plan" key={plan.id}><div className="notification-type-icon improvement"><Save size={21}/></div><div className="notification-content"><div className="notification-meta"><span className="badge purple">Razvojni načrt</span><span className="demo-tag">{plan.source_type === 'demo' ? 'DEMO PODATKI' : 'RESNIČNI RAZPISI'}</span></div><h3>{plan.name}</h3><p>{plan.evaluation.labels.join(' · ')}</p><p>{plan.evaluation.summary.open.affected_tenders} odprtih razpisov z dodatno izpolnjenim pogojem · {plan.evaluation.summary.historical.affected_tenders} preteklih razpisov</p><div className="notification-actions"><button className="text-link" disabled={busy} onClick={() => openPlan(plan.id)}>Odpri in preračunaj<ArrowRight size={14}/></button><button className="subtle-link" disabled={busy} onClick={() => setDeleting(plan.id)}><Trash2 size={14}/>Izbriši</button></div>{deleting === plan.id && <div className="plan-delete"><span>Izbrišem shranjeni načrt?</span><button className="button small" onClick={() => setDeleting(null)}>Prekliči</button><button className="button small" disabled={busy} onClick={() => run(async () => { await api(`/improvement-plans/${plan.id}`, { method: 'DELETE' }); setDeleting(null); await loadPlans(); await refresh(); })}>Izbriši načrt</button></div>}</div></article>)}{!plans.filter(p => source === 'all' || p.source_type === source).length && !plansError && <div className="empty-state"><Save size={28}/><h3>Vaši naslednji koraki, na enem mestu.</h3><p>Odprite predlog za razvoj in ga shranite. Več predlogov lahko združite v skupen načrt.</p><button className="button" onClick={() => setTab('improvements')}>Poglej predloge</button></div>}</> : <>{notifications.map(notification => <article className={`notification-card ${notification.read ? 'read' : 'unread'}`} key={notification.id}><div className={`notification-type-icon ${notification.type}`}>{notification.type === 'improvement' ? <Lightbulb size={21}/> : notification.type === 'new' ? <Sparkles size={21}/> : notification.type === 'deadline' ? <CalendarDays size={21}/> : <FileText size={21}/>}</div><div className="notification-content"><div className="notification-meta"><span className={`badge ${notification.type === 'improvement' ? 'purple' : 'blue'}`}>{eventNames[notification.type]}</span>{notification.is_demo && <span className="demo-tag">DEMO {notification.type === 'improvement' ? 'PODATKI' : 'DOGODEK'}</span>}<time>{formatDate(notification.created_at)}</time></div><h3>{notification.title}</h3><p>{notification.body}</p>{notification.improvement && notification.improvement.summary.historical.affected_tenders > 0 && <p className="historical-note">Pretekli razpisi z dodatnim učinkom: {notification.improvement.summary.historical.affected_tenders}.</p>}<div className="notification-actions">{notification.type === 'improvement' ? <><button className="text-link" disabled={busy} onClick={() => show([notification])}>Poglej učinek<ArrowRight size={14}/></button></> : <button className="text-link" disabled={busy} onClick={() => run(async () => { await post('/notifications/read', { id: notification.id }); await refresh(); window.location.hash = `/razpisi/${notification.tender_id}${notification.type !== 'new' ? '?tab=changes' : ''}`; })}>Poglej razpis in spremembe<ArrowRight size={14}/></button>}{!notification.read && <button className="subtle-link" disabled={busy} onClick={() => read(notification.id)}><Check size={14}/>Prebrano</button>}</div>{notification.improvement && combining && <label className="checkbox-row combine-improvement"><input type="checkbox" checked={selected.includes(notification.id)} disabled={chosen.length > 0 && chosen[0].improvement?.source_type !== notification.improvement.source_type} onChange={e => setSelected(e.target.checked ? [...selected, notification.id] : selected.filter(id => id !== notification.id))}/><span>Izberi za skupni načrt</span></label>}</div>{!notification.read && <span className="unread-dot"/>}</article>)}{!notifications.length && <div className="empty-state"><CheckCheck size={28}/><h3>{tab === 'unread' ? 'Vse ste pregledali.' : 'Trenutno ni obvestil za ta izbor.'}</h3><p>Predlogi nastanejo iz preverljivih pogojev obdelanih razpisov. Neobdelana dokumentacija še ne omogoča presoje izboljšav.</p></div>}</>}
        </section></div><details className="quiet-disclosure notification-help"><summary>Kako nastanejo predlogi za razvoj?</summary><p>Iz obdelanih pogojev izračunamo, katere izboljšave bi vam pomagale. Manjkajoči podatki ostanejo neznani. Načrt ne spreminja profila in ne zagotavlja uspeha prijave.</p><a href="#/profil" className="text-link">Dopolni profil<ArrowRight size={14}/></a></details>
        {inspection && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget && !busy) setInspection(null); }}><section className="modal improvement-modal" role="dialog" aria-modal="true" aria-labelledby="improvement-title"><div className="modal-heading"><div><h2 id="improvement-title">Učinek izboljšave</h2><p>{data.profile.name} · primerjava s trenutnim profilom</p></div><button ref={closeRef} className="icon-button" disabled={busy} aria-label="Zapri učinek izboljšave" onClick={() => setInspection(null)}><X size={20}/></button></div>
            <span className={`badge ${inspection.result.source_type === 'demo' ? 'amber' : 'green'}`}>{inspection.result.source_type === 'demo' ? 'Demo podatki · izmišljeni razpisi' : 'Resnični razpisi · shranjena dokumentacija'}</span>
            <div className="scenario-actions">{inspection.result.labels.map((label, i) => <div key={i}><Lightbulb size={16}/><span>{label}</span>{inspection.result.actions.length > 1 && <button className="icon-button" disabled={busy} aria-label={`Odstrani izboljšavo ${label}`} onClick={() => removeAction(i)}><X size={14}/></button>}</div>)}</div>
            <Summary result={inspection.result}/>
            <div className="tabs"><button className={impactTab === 'open' ? 'active' : ''} onClick={() => setImpactTab('open')}>Odprti razpisi<span>{inspection.result.open.length}</span></button><button className={impactTab === 'historical' ? 'active' : ''} onClick={() => setImpactTab('historical')}>Pretekli razpisi<span>{inspection.result.historical.length}</span></button></div>
            {impactTab === 'historical' && <p className="improvement-caution">Primerjava današnjega profila s pogoji preteklih razpisov. To niso odprte priložnosti ali napoved prihodnjih objav.</p>}
            <div className="impact-list">{inspection.result[impactTab].map(row => <ImpactCard row={row} key={row.id}/>)}{!inspection.result[impactTab].length && <div className="empty-state compact"><CheckCheck size={24}/><h3>Trenutno ni dodatnega učinka.</h3><p>Izboljšava je morda že dosežena ali pa v shranjenih razpisih ni ustreznega pogoja.</p></div>}</div>
            <details className="improvement-assumptions"><summary>Predpostavke izračuna in omejitve</summary><ul>{inspection.result.assumptions.map(a => <li key={a}>{a}</li>)}</ul><small>Izračun: {formatDate(inspection.result.evaluated_at)}</small></details>
            <div className="plan-save"><label className="field"><span>Ime razvojnega načrta</span><input aria-label="Ime razvojnega načrta" maxLength={100} value={name} onChange={e => setName(e.target.value)}/></label><button className="button primary" disabled={busy || !name.trim()} onClick={save}>{busy ? <LoaderCircle size={16} className="spin"/> : <Save size={16}/>} {inspection.planId ? 'Shrani spremembe načrta' : 'Shrani načrt'}</button></div><p className="plan-save-note"><ShieldCheck size={13}/>Shrani se načrt, dejanski profil podjetja ostane nespremenjen.</p>
        </section></div>}
    </>;
}
