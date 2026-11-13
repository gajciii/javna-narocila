import { useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, CircleHelp, Download, FileCheck2, FileText, LoaderCircle, Upload } from 'lucide-react';
import { api } from './api';
import './submission-review.css';

type State = 'covered' | 'partial' | 'missing' | 'unknown' | 'not_applicable';
type Evidence = { document_id: string; document_name: string; page: number; quote: string };
type Issue = { name: string; message: string };
type Report = {
    model: string; reviewed_at: string; version: number; result: 'covered' | 'needs_work' | 'incomplete';
    counts: Record<State, number>; source_issues: Issue[]; submission_issues: Issue[]; duplicates: string[];
    limitations: string; documents: { id: string; name: string; pages: number }[];
    items: { id: string; title: string; requirement: string; status: State; explanation: string; action: string; source: Evidence; evidence: Evidence[] }[];
};
const labels: Record<State, string> = { covered: 'Pokrito z dokazom', partial: 'Delno pokrito', missing: 'Manjka', unknown: 'Ročno preveri', not_applicable: 'Ni relevantno' };
const accept = '.zip,.pdf,.docx,.xlsx,.pptx,.odt,.ods,.txt,.csv,.xml,.json';

function Proof({ value, source = false }: { value: Evidence; source?: boolean }) {
    const stored = source && !value.document_id.startsWith('faq-');
    return <div className="submission-proof"><span><FileText size={14}/>{value.document_name} · str. {value.page}{stored && <a href={`/api/documents/${encodeURIComponent(value.document_id)}#page=${value.page}`} target="_blank" rel="noreferrer">Odpri vir ↗</a>}</span><blockquote>{value.quote}</blockquote></div>;
}

export default function SubmissionReview({ tenderId }: { tenderId: string }) {
    const fileRef = useRef<HTMLInputElement>(null);
    const [fileNames, setFileNames] = useState<string[]>([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [report, setReport] = useState<Report | null>(null);
    const [filter, setFilter] = useState<State | 'all'>('all');
    const [folder, setFolder] = useState('');
    const reviewFiles = async (files: File[]) => {
        if (busy || !files.length) return;
        setFileNames(files.map(file => file.name));
        setBusy(true); setError(''); setReport(null); setFilter('all');
        try {
            if (files.reduce((sum, file) => sum + file.size, 0) > 50 * 1024 ** 2) throw new Error('Dokumenti prijave lahko skupaj obsegajo največ 50 MB.');
            const body = new FormData();
            if (folder.trim()) body.append('submission_folder', folder.trim());
            files.forEach(file => body.append('submission_files', file));
            setReport(await api<Report>(`/tenders/${encodeURIComponent(tenderId)}/submission-review`, { method: 'POST', body }));
        } catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
    };
    const download = () => {
        const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
        const link = document.createElement('a'); link.href = url; link.download = `pregled-prijave-${tenderId}.json`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    return <section className="surface detail-section submission-review">
        <div className="section-heading"><div><h2><FileCheck2 size={20}/>Pregled pripravljene prijave</h2><p className="section-help">Primerjajte vsebino ponudbe z zahtevanimi obrazci, prilogami, dokazili in navodili razpisa.</p></div></div>
        <div className="submission-upload-action">
            <input ref={fileRef} className="sr-only" tabIndex={-1} aria-label="Izberi dokumente prijave" type="file" accept={accept} multiple disabled={busy} onChange={event => void reviewFiles(Array.from(event.target.files || []))}/>
            <button type="button" className="button primary" disabled={busy} onClick={() => { if (fileRef.current) { fileRef.current.value = ''; fileRef.current.click(); } }}>{busy ? <LoaderCircle className="spin" size={17}/> : <Upload size={17}/>} {busy ? 'AI pregleduje dokumente …' : 'Naloži in preveri prijavo'}</button>
            <p>Izberite ZIP ali več dokumentov prijave (skupaj največ 50 MB). Pregled se začne takoj po izbiri.</p>
            {fileNames.length > 0 && <small>Izbrano: {fileNames.join(', ')}</small>}
        </div>
        <details className="quiet-disclosure submission-folder"><summary>ZIP vsebuje več različic prijave?</summary><label className="field"><span>Mapa prijave v ZIP-u</span><input value={folder} disabled={busy} onChange={event => setFolder(event.target.value)} placeholder="Npr. PDF ali PDF/BREZ"/><small>Pred izbiro ZIP-a vpišite mapo. Pregledane bodo samo datoteke neposredno v njej.</small></label></details>
        <p className="section-help">Pregled uporabi razpisno dokumentacijo in pojasnila, ki so že shranjeni pri razpisu. Če dokumentacija manjka, jo najprej dodajte na zavihku Dokumenti. Besedilo prijave se pošlje modelu prek OpenRouterja. Poročilo prenesite, preden zaprete zavihek.</p>
        {busy && <p className="submission-progress" role="status">Pripravljamo kontrolni seznam in primerjamo dokazila. Pregled lahko traja do tri minute. Pustite zavihek odprt.</p>}
        {error && <div className="error-banner" role="alert"><AlertCircle size={20}/><p>{error}</p></div>}
        {report && <div className="submission-report" aria-live="polite">
            <div className={`submission-result ${report.result}`}><div>{report.result === 'covered' ? <CheckCircle2 size={25}/> : <CircleHelp size={25}/>}<div><h3>{report.result === 'covered' ? 'Izluščene zahteve so vsebinsko pokrite' : report.result === 'incomplete' ? 'Pregled ni popoln: del dokumentov zahteva ročni pregled' : 'Prijava potrebuje dopolnitve ali dodatno preverjanje'}</h3><p>{report.limitations}</p></div></div><button className="button small" onClick={download}><Download size={15}/>Prenesi poročilo</button></div>
            <p className="section-help">Model: {report.model} · Različica razpisa: {report.version} · {new Date(report.reviewed_at).toLocaleString('sl-SI', { timeZone: 'Europe/Ljubljana' })}</p>
            <div className="submission-filters" aria-label="Filtriraj ugotovitve"><button className="button small" aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>Vse ({report.items.length})</button>{(Object.keys(labels) as State[]).map(key => <button key={key} className={`button small ${filter === key ? 'selected' : ''}`} aria-pressed={filter === key} onClick={() => setFilter(key)}>{labels[key]} ({report.counts[key]})</button>)}</div>
            {[['Razpisna dokumentacija', report.source_issues], ['Dokumenti prijave', report.submission_issues]].map(([title, entries]) => (entries as Issue[]).length > 0 && <details className="submission-issues" open key={title as string}><summary>{title as string}: nepreverjeni deli ({(entries as Issue[]).length})</summary><ul>{(entries as Issue[]).map((issue, i) => <li key={i}><strong>{issue.name}</strong>: {issue.message}</li>)}</ul></details>)}
            {report.duplicates.length > 0 && <details className="quiet-disclosure"><summary>Podvojene datoteke ({report.duplicates.length})</summary><p>Enake datoteke so bile upoštevane samo enkrat.</p><ul>{report.duplicates.map((name, i) => <li key={i}>{name}</li>)}</ul></details>}
            <div className="submission-items">{report.items.filter(item => filter === 'all' || item.status === filter).map(item => <article key={item.id} className={`submission-item ${item.status}`}><div className="submission-item-heading"><h3>{item.title}</h3><span className="badge">{labels[item.status]}</span></div><p>{item.requirement}</p><p><strong>Ugotovitev: </strong>{item.explanation}</p>{item.action && <p className="submission-action"><strong>Naslednji korak: </strong>{item.action}</p>}<details><summary>Zahteva v razpisu</summary><Proof value={item.source} source/></details><details open={item.evidence.length > 0}><summary>Dokazi v prijavi ({item.evidence.length})</summary>{item.evidence.map((proof, i) => <Proof key={i} value={proof}/>)}{!item.evidence.length && <p className="section-help">V berljivem delu prijave ni potrjenega dokaza.</p>}</details></article>)}</div>
        </div>}
    </section>;
}
