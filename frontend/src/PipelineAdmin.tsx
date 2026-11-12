import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Activity, ArrowLeft, CheckCircle2, Clock3, Database, LockKeyhole, LogOut, Play, RefreshCw, Server, ShieldCheck, XCircle } from 'lucide-react';
import './pipeline-admin.css';

type Session = { authenticated: boolean; username: string; csrf_token: string };
type Counts = { total: number; reused: number; pending: number; running: number; complete: number; failed: number; superseded: number };
type Run = { id: number; source: string; mode: string; period: string; max_notices: number | null; state: string;
    status: string; requested_by: string | null; listed_count: number; error_count: number; error: string;
    created_at: string; started_at: string | null; collection_finished_at: string | null; jobs: Counts };
type Job = { id: number; kind: string; state: string; tender_id: string; title: string; version: number; attempts: number;
    error: string; created_at: string; updated_at: string; available_at: string; lease_until: string | null;
    document_count: number | null; unreadable_count: number | null; findings_count: number };
type Attempt = { id: number; number: number; state: string; worker: string; started_at: string;
    finished_at: string | null; error: string; summary: Record<string, number> };
type Overview = { remote_enabled: boolean; server_time: string; queue: Record<string, number>;
    index: { documents: number; chunks: number }; schedule: { enabled: boolean; next_run_at: string };
    agents: { id: string; role: string; hostname: string; online: boolean; state: string; last_seen: string; job_id: number | null; run_id: number | null }[];
    history_note: string };
type RunDetail = { run: Run; errors: { notice_id: string; message: string }[]; jobs: Job[]; count: number; page: number };
type JobDetail = { job: Job; attempts: Attempt[]; attempt_count: number };

const names: Record<string, string> = { queued: 'Čaka na zajem', collecting: 'Zajem objav', processing: 'Obdelava prilog',
    collected: 'Zajem zaključen', complete: 'Zaključeno', partial: 'Delno uspešno', failed: 'Napaka', imported: 'Prejšnja opravila',
    pending: 'V čakalni vrsti', running: 'V obdelavi', superseded: 'Novejša različica', interrupted: 'Prekinjeno', retrying: 'Čaka na ponovitev',
    manual: 'Ročno', scheduled: 'Dnevni urnik', cli: 'Ukazna vrstica', index: 'Indeksiranje', assess: 'Presoja',
    worker: 'Delavec', scheduler: 'Scheduler' };
const formatDate = (value?: string | null) => value ? new Date(value).toLocaleString('sl-SI', { timeZone: 'Europe/Ljubljana', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';
const number = (value: number) => new Intl.NumberFormat('sl-SI').format(value);
const month = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Ljubljana', year: 'numeric', month: '2-digit' }).format(new Date());

class AdminError extends Error { constructor(message: string, public status: number) { super(message); } }
async function request<T>(path: string, options: RequestInit = {}, csrf = ''): Promise<T> {
    const response = await fetch(`/api/admin/pipeline${path}`, { ...options, credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRFToken': csrf } : {}), ...options.headers } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new AdminError(data.error || data.detail || 'Zahteve ni bilo mogoče zaključiti.', response.status);
    return data as T;
}
function State({ value }: { value: string }) { return <span className={`pipeline-state ${value}`}>{names[value] || value}</span>; }
function JobTable({ jobs, select }: { jobs: Job[]; select: (id: number) => void }) {
    return <div className="pipeline-table-wrap"><table className="pipeline-table"><thead><tr><th>Opravilo</th><th>Razpis</th><th>Stanje</th><th>Poskusi</th><th>Dokumenti</th><th>Opomba</th></tr></thead><tbody>{jobs.map(job => <tr key={job.id}>
        <td><button className="pipeline-link" onClick={() => select(job.id)}>#{job.id} · {names[job.kind]}</button><small>{formatDate(job.created_at)}</small></td>
        <td><a className="pipeline-link" href={`#/razpisi/${encodeURIComponent(job.tender_id)}`}>{job.title}</a><small>Različica {job.version}</small></td>
        <td><State value={job.state}/></td><td>{job.attempts}</td><td>{job.document_count ?? '—'}{(job.unreadable_count || 0) > 0 && <small>{job.unreadable_count} za ročni pregled</small>}</td><td>{job.error || '—'}</td>
    </tr>)}</tbody></table>{!jobs.length && <p className="pipeline-empty">Ni opravil za izbrani filter.</p>}</div>;
}
function Pagination({ page, count, size, change }: { page: number; count: number; size: number; change: (page: number) => void }) {
    const total = Math.max(1, Math.ceil(count / size));
    return <div className="pipeline-pagination"><span>{number(count)} zapisov · stran {page} od {total}</span><div>
        <button className="button small" disabled={page <= 1} onClick={() => change(page - 1)}>Prejšnja</button>
        <button className="button small" disabled={page >= total} onClick={() => change(page + 1)}>Naslednja</button>
    </div></div>;
}

export default function PipelineAdmin() {
    const [session, setSession] = useState<Session | null>(null);
    const [username, setUsername] = useState('admin');
    const [password, setPassword] = useState('');
    const [overview, setOverview] = useState<Overview | null>(null);
    const [runs, setRuns] = useState<{ results: Run[]; count: number }>({ results: [], count: 0 });
    const [source, setSource] = useState('');
    const [listing, setListing] = useState<'runs' | 'jobs'>('runs');
    const [allJobs, setAllJobs] = useState<{ results: Job[]; count: number }>({ results: [], count: 0 });
    const [allJobState, setAllJobState] = useState('');
    const [allJobKind, setAllJobKind] = useState('');
    const [allJobPage, setAllJobPage] = useState(1);
    const [page, setPage] = useState(1);
    const [selected, setSelected] = useState<number | null>(null);
    const [detail, setDetail] = useState<RunDetail | null>(null);
    const [jobState, setJobState] = useState('');
    const [jobPage, setJobPage] = useState(1);
    const [jobId, setJobId] = useState<number | null>(null);
    const [jobDetail, setJobDetail] = useState<JobDetail | null>(null);
    const [mode, setMode] = useState('monthly');
    const [period, setPeriod] = useState(month);
    const [maximum, setMaximum] = useState('50');
    const [busy, setBusy] = useState('');
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const [revision, setRevision] = useState(0);
    const submissionKey = useRef('');
    const authenticated = !!session?.authenticated;

    const fail = (e: unknown) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setError((e as Error).message);
        if (e instanceof AdminError && (e.status === 401 || e.status === 403)) {
            request<Session>('/session').then(setSession).catch(() => setSession(null));
        }
    };
    useEffect(() => { request<Session>('/session').then(setSession).catch(fail); }, []);
    useEffect(() => {
        if (!authenticated) return;
        const controller = new AbortController(); let fetching = false;
        const load = async () => {
            if (fetching) return; fetching = true;
            try {
                const [nextOverview, nextRuns] = await Promise.all([
                    request<Overview>('/overview', { signal: controller.signal }),
                    request<{ results: Run[]; count: number }>(`/runs?page=${page}&source=${source}`, { signal: controller.signal }),
                ]);
                if (!controller.signal.aborted) { setOverview(nextOverview); setRuns(nextRuns); }
            } catch (e) { if (!controller.signal.aborted) fail(e); }
            finally { fetching = false; }
        };
        load(); const timer = setInterval(load, 5000);
        return () => { controller.abort(); clearInterval(timer); };
    }, [authenticated, page, source, revision]);
    useEffect(() => {
        if (!authenticated || listing !== 'jobs') return;
        const controller = new AbortController(); let fetching = false;
        const load = async () => {
            if (fetching) return; fetching = true;
            try {
                const next = await request<{ results: Job[]; count: number }>(`/jobs?page=${allJobPage}&state=${allJobState}&kind=${allJobKind}`, { signal: controller.signal });
                if (!controller.signal.aborted) setAllJobs(next);
            } catch (e) { if (!controller.signal.aborted) fail(e); }
            finally { fetching = false; }
        };
        load(); const timer = setInterval(load, 5000);
        return () => { controller.abort(); clearInterval(timer); };
    }, [authenticated, listing, allJobPage, allJobState, allJobKind, revision]);
    useEffect(() => {
        if (!authenticated || selected == null) return;
        const controller = new AbortController(); let fetching = false;
        const load = async () => {
            if (fetching) return; fetching = true;
            try {
                const next = await request<RunDetail>(`/runs/${selected}?page=${jobPage}&state=${jobState}`, { signal: controller.signal });
                if (!controller.signal.aborted) setDetail(next);
            } catch (e) { if (!controller.signal.aborted) fail(e); }
            finally { fetching = false; }
        };
        load(); const timer = setInterval(load, 5000);
        return () => { controller.abort(); clearInterval(timer); };
    }, [authenticated, selected, jobPage, jobState, revision]);
    useEffect(() => {
        if (!authenticated || jobId == null) return;
        const controller = new AbortController();
        request<JobDetail>(`/jobs/${jobId}`, { signal: controller.signal }).then(setJobDetail).catch(e => { if (!controller.signal.aborted) fail(e); });
        return () => controller.abort();
    }, [authenticated, jobId, revision]);

    async function signIn(event: FormEvent) {
        event.preventDefault(); setBusy('login'); setError('');
        try {
            const current = session || await request<Session>('/session');
            setSession(await request<Session>('/login', { method: 'POST', body: JSON.stringify({ username, password }) }, current.csrf_token));
            setPassword('');
        } catch (e) { fail(e); } finally { setBusy(''); }
    }
    async function action(name: string, operation: () => Promise<void>) {
        setBusy(name); setError(''); setMessage('');
        try { await operation(); setRevision(v => v + 1); } catch (e) { fail(e); } finally { setBusy(''); }
    }
    async function startRun(event: FormEvent) {
        event.preventDefault();
        await action('run', async () => {
            submissionKey.current ||= crypto.randomUUID();
            const run = await request<Run>('/runs', { method: 'POST', body: JSON.stringify({ mode,
                period: mode === 'monthly' ? period : '', max_notices: maximum ? Number(maximum) : null,
                request_key: submissionKey.current }) }, session!.csrf_token);
            submissionKey.current = ''; setSource(''); setPage(1); setListing('runs'); setSelected(run.id); setJobPage(1); setJobState(''); setDetail(null);
            setMessage(`Zagon #${run.id} je v vrsti. Izvedel ga bo scheduler na strežniku.`);
        });
    }
    function selectRun(id: number) { setSelected(id); setDetail(null); setJobState(''); setJobPage(1); setJobId(null); setJobDetail(null); }
    function selectJob(id: number) { setJobId(id); setJobDetail(null); }

    if (!session) return <section className="surface pipeline-login"><ShieldCheck size={28}/><h1>Administracija</h1><p>{error || 'Preverjam administratorski dostop …'}</p></section>;
    if (!authenticated) return <section className="surface pipeline-login"><div className="pipeline-login-icon"><LockKeyhole size={28}/></div>
        <h1>Administracija pipelinea</h1><p>Prijavite se za pregled obdelave in upravljanje zagonov.</p>
        <form onSubmit={signIn}><label className="field"><span>Uporabniško ime</span><input autoComplete="username" required value={username} onChange={e => setUsername(e.target.value)}/></label>
            <label className="field"><span>Geslo</span><input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)}/></label>
            {error && <p className="error-banner" role="alert">{error}</p>}<button className="button primary" disabled={!!busy}>{busy ? 'Prijavljam …' : 'Prijava'}</button>
        </form></section>;

    return <div className="pipeline-admin">
        <section className="page-intro"><div className="page-heading"><div><div className="pipeline-eyebrow"><ShieldCheck size={16}/>Administracija</div><h1>Pregled pipelinea</h1><p>Zagoni, obdelava dokumentacije in stanje strežnika.</p></div>
            <div className="pipeline-actions"><button className="button" onClick={() => setRevision(v => v + 1)}><RefreshCw size={16}/>Osveži</button><button className="button" disabled={!!busy} onClick={() => action('logout', async () => {
                setSession(await request<Session>('/logout', { method: 'POST', body: '{}' }, session.csrf_token)); setOverview(null); setDetail(null);
            })}><LogOut size={16}/>Odjava · {session.username}</button></div></div></section>
        {error && <div className="error-banner" role="alert">{error}</div>}
        {message && <div className="pipeline-message" role="status"><CheckCircle2 size={18}/>{message}</div>}
        {!overview ? <section className="surface pipeline-panel">Nalagam stanje pipelinea …</section> : <>
            {!overview.remote_enabled && <div className="info-box">Ločeni pipeline v tem okolju ni omogočen. Pregled zgodovine je na voljo, ročni zagon je onemogočen.</div>}
            <div className="pipeline-metrics">
                <div className="surface"><Clock3 size={20}/><span>V čakalni vrsti</span><strong>{number(overview.queue.pending || 0)}</strong></div>
                <div className="surface"><Activity size={20}/><span>V obdelavi</span><strong>{number(overview.queue.running || 0)}</strong></div>
                <div className="surface"><XCircle size={20}/><span>Neuspešna opravila</span><strong>{number(overview.queue.failed || 0)}</strong></div>
                <div className="surface"><Database size={20}/><span>Indeksirani dokumenti</span><strong>{number(overview.index.documents)}</strong><small>{number(overview.index.chunks)} odlomkov</small></div>
            </div>
            <div className="pipeline-top-grid">
                <section className="surface pipeline-panel"><div className="section-heading"><h2><Play size={18}/>Ročni zagon</h2></div><form onSubmit={startRun} className="pipeline-run-form">
                    <label className="field"><span>Obseg</span><select value={mode} onChange={e => { setMode(e.target.value); submissionKey.current = ''; }}><option value="monthly">Objave izbranega meseca</option><option value="existing">Že shranjeni razpisi</option></select></label>
                    {mode === 'monthly' && <label className="field"><span>Mesec objav</span><input type="month" max={month()} value={period} required onChange={e => { setPeriod(e.target.value); submissionKey.current = ''; }}/></label>}
                    <label className="field"><span>Največ objav</span><input type="number" min="1" max="5000" placeholder="Vse objave" value={maximum} onChange={e => { setMaximum(e.target.value); submissionKey.current = ''; }}/><small>Prazno pomeni celoten izbor. Že indeksirana vsebina se uporabi ponovno.</small></label>
                    <button className="button primary" disabled={!!busy || !overview.remote_enabled}><Play size={16}/>{busy === 'run' ? 'Dodajam v vrsto …' : 'Zaženi pipeline'}</button>
                </form></section>
                <section className="surface pipeline-panel"><div className="section-heading"><h2><Server size={18}/>Storitve in urnik</h2></div>
                    {(['worker', 'scheduler'] as const).map(role => {
                        const agents = overview.agents.filter(a => a.role === role), current = agents.find(a => a.online) || agents[0];
                        return <div className="pipeline-service" key={role}><div><strong>{names[role]}</strong><small>{current ? `Zadnji odziv: ${formatDate(current.last_seen)}` : 'Odziv še ni zabeležen.'}</small>
                            {current?.online && current.job_id && <small>Obdeluje opravilo #{current.job_id}</small>}{current?.online && current.run_id && <small>Zajema objave zagona #{current.run_id}</small>}</div>
                            <span className={`pipeline-state ${current?.online ? 'complete' : 'failed'}`}>{current?.online ? 'Dosegljiv' : 'Brez odziva'}</span></div>;
                    })}
                    <div className="pipeline-service"><div><strong>Dnevni zajem</strong><small>{overview.schedule.enabled ? `Naslednji: ${formatDate(overview.schedule.next_run_at)}` : 'Samodejni zagoni so ustavljeni.'}</small></div>
                        <button className="button small" disabled={!!busy} onClick={() => action('schedule', async () => { await request('/schedule', { method: 'POST', body: JSON.stringify({ enabled: !overview.schedule.enabled }) }, session.csrf_token); setMessage(overview.schedule.enabled ? 'Dnevni urnik je ustavljen. Ročni zagoni ostanejo na voljo.' : 'Dnevni urnik je omogočen.'); })}>{overview.schedule.enabled ? 'Ustavi urnik' : 'Omogoči urnik'}</button></div>
                    <p className="section-help">Ustavitev urnika ne prekine obdelave že oddanih opravil. Pregled se samodejno osvežuje vsakih 5 sekund.</p>
                </section>
            </div>
            <section className="surface pipeline-panel"><div className="pipeline-list-tabs"><button className={`button small ${listing === 'runs' ? 'primary' : ''}`} onClick={() => setListing('runs')}>Zgodovina zagonov</button><button className={`button small ${listing === 'jobs' ? 'primary' : ''}`} onClick={() => setListing('jobs')}>Vsa opravila</button></div>
                {listing === 'runs' ? <><div className="section-heading"><h2>Zgodovina zagonov</h2><label className="pipeline-inline-filter">Vir <select value={source} onChange={e => { setSource(e.target.value); setPage(1); }}><option value="">Vsi zagoni</option><option value="manual">Ročno</option><option value="scheduled">Dnevni urnik</option><option value="cli">Ukazna vrstica</option><option value="imported">Prejšnja opravila</option></select></label></div>
                <p className="section-help">{overview.history_note}</p><div className="pipeline-table-wrap"><table className="pipeline-table"><thead><tr><th>Zagon</th><th>Obseg</th><th>Začetek zajema</th><th>Stanje</th><th>Opravila</th><th>Napake</th></tr></thead><tbody>
                    {runs.results.map(run => <tr key={run.id} className={selected === run.id ? 'selected' : ''}><td><button className="pipeline-link" onClick={() => selectRun(run.id)}>#{run.id} · {names[run.source]}</button><small>{run.requested_by || (run.source === 'scheduled' ? 'Samodejno' : '')}</small></td>
                        <td>{run.mode === 'existing' ? 'Shranjeni razpisi' : run.mode === 'retry' ? 'Ponovitev opravila' : run.period}<small>{run.max_notices ? `Do ${number(run.max_notices)} objav` : 'Celoten izbor'}</small></td><td>{formatDate(run.started_at)}</td><td><State value={run.status}/></td>
                        <td>{number(run.jobs.complete)} / {number(run.jobs.total)}<small>{run.jobs.pending + run.jobs.running ? `${number(run.jobs.pending + run.jobs.running)} v vrsti ali obdelavi` : `${number(run.jobs.reused)} ponovno uporabljenih`}</small></td><td>{number(run.jobs.failed + run.error_count)}</td></tr>)}
                </tbody></table>{!runs.results.length && <p className="pipeline-empty">Zagoni še niso zabeleženi.</p>}</div><Pagination page={page} count={runs.count} size={20} change={setPage}/></> : <>
                    <div className="section-heading"><h2>Vsa opravila</h2><div className="pipeline-actions"><label className="pipeline-inline-filter">Vrsta <select value={allJobKind} onChange={e => { setAllJobKind(e.target.value); setAllJobPage(1); }}><option value="">Vse vrste</option><option value="index">Indeksiranje</option><option value="assess">Presoja</option></select></label><label className="pipeline-inline-filter">Stanje <select value={allJobState} onChange={e => { setAllJobState(e.target.value); setAllJobPage(1); }}>{[['', 'Vsa stanja'], ['pending', 'V čakalni vrsti'], ['running', 'V obdelavi'], ['complete', 'Zaključeno'], ['failed', 'Napaka'], ['superseded', 'Novejša različica']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div></div>
                    <p className="section-help">Vključuje skupno indeksiranje in presoje prilog, sprožene iz aplikacije. Kliknite opravilo za časovnico poskusov.</p><JobTable jobs={allJobs.results} select={selectJob}/><Pagination page={allJobPage} count={allJobs.count} size={25} change={setAllJobPage}/>
                </>}
            </section>
        </>}
        {selected != null && <section className="surface pipeline-panel" aria-label={`Podrobnosti zagona ${selected}`}><div className="section-heading"><h2>Zagon #{selected}</h2><button className="button small" onClick={() => { setSelected(null); setDetail(null); setJobId(null); }}>Zapri podrobnosti</button></div>
            {!detail ? <p>Nalagam podrobnosti …</p> : <>
                <div className="pipeline-run-summary"><State value={detail.run.status}/>{detail.run.source !== 'imported' && <><span>{number(detail.run.listed_count)} pregledanih objav</span><span>Zajem zaključen: {formatDate(detail.run.collection_finished_at)}</span></>}</div>
                <p className="section-help">Spodaj so trenutna stanja povezanih opravil. Čas zaključka zajema pomeni zaključek zbiranja objav; obdelava prilog lahko še poteka.</p>
                {detail.run.error && <p className="error-banner">{detail.run.error}</p>}{detail.errors.length > 0 && <details className="quiet-disclosure"><summary>Napake pri zajemu ({detail.run.error_count})</summary><ul>{detail.errors.map((e, i) => <li key={i}>{e.notice_id}: {e.message}</li>)}</ul></details>}
                <label className="pipeline-inline-filter">Stanje opravila <select value={jobState} onChange={e => { setJobState(e.target.value); setJobPage(1); }}>{[['', 'Vsa stanja'], ['pending', 'V čakalni vrsti'], ['running', 'V obdelavi'], ['complete', 'Zaključeno'], ['failed', 'Napaka'], ['superseded', 'Novejša različica']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                <JobTable jobs={detail.jobs} select={selectJob}/><Pagination page={jobPage} count={detail.count} size={25} change={setJobPage}/>
            </>}
        </section>}
        {jobId != null && <section className="surface pipeline-panel"><div className="section-heading"><h2>Poskusi opravila #{jobId}</h2><button className="button small" onClick={() => { setJobId(null); setJobDetail(null); }}>Zapri</button></div>
            {!jobDetail ? <p>Nalagam časovnico …</p> : <><div className="pipeline-run-summary"><State value={jobDetail.job.state}/><span>{jobDetail.job.title}</span>{jobDetail.job.state === 'failed' && <button className="button small" disabled={!!busy} onClick={() => action('retry', async () => {
                await request(`/jobs/${jobId}`, { method: 'POST', body: '{}' }, session.csrf_token); setMessage(`Opravilo #${jobId} je ponovno v vrsti.`);
            })}><RefreshCw size={15}/>Ponovi opravilo</button>}</div>
                {!jobDetail.attempts.length && <p className="section-help">Časovnica poskusov za to opravilo še ni zabeležena. Opravilo je lahko nastalo pred uvedbo dnevnika ali še čaka na obdelavo.</p>}
                <ol className="pipeline-attempts">{jobDetail.attempts.map(attempt => <li key={attempt.id}><div><strong>Poskus {attempt.number}</strong><State value={attempt.state}/></div><p>{formatDate(attempt.started_at)} → {formatDate(attempt.finished_at)}</p><small>Delavec: {attempt.worker || 'Ni podatka'}</small>{attempt.error && <p className="pipeline-attempt-error">{attempt.error}</p>}{attempt.summary.document_count != null && <small>{attempt.summary.document_count} dokumentov · {attempt.summary.unreadable_count || 0} za ročni pregled</small>}</li>)}</ol>
                {jobDetail.attempt_count > 100 && <p className="section-help">Prikazanih je zadnjih 100 od {jobDetail.attempt_count} poskusov.</p>}
                <button className="button small" onClick={() => setRevision(v => v + 1)}><RefreshCw size={15}/>Osveži časovnico</button>
            </>}
        </section>}
        <a className="pipeline-back" href="#/razpisi"><ArrowLeft size={16}/>Nazaj na razpise</a>
    </div>;
}
