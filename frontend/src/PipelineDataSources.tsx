import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Database, FileText, Upload } from 'lucide-react';
import { request } from './pipelineAdminApi';

export type DataSourceStats = {
    erar?: { transactions: number; recipients: number; payers: number; with_procedure: number; with_award: number;
        eur_amount: string; other_currencies: number; first_payment_on: string | null; last_payment_on: string | null; last_export_on: string | null };
    ocr?: { documents: number; indexed: number; ocr_documents: number; ocr_contents: number; ocr_pages: number };
};
type Payment = { source_id: string; paid_on: string; amount: string; currency: string; payer: string; recipient: string;
    procedure: string; award_id: string; exported_on: string };
type Document = { id: string; title: string; tender_id: string; tender_title: string; status: string; error: string;
    version: number; has_ocr: boolean; indexed_content_id: string | null; original_url: string; text_url: string };
type Page<T> = { results: T[]; count: number; page: number };
const number = (value: number) => new Intl.NumberFormat('sl-SI').format(value);
const day = (value: string | null) => value ? new Date(`${value}T12:00:00`).toLocaleDateString('sl-SI') : '—';
const amount = (value: string, currency = 'EUR') => new Intl.NumberFormat('sl-SI', { style: 'currency', currency }).format(Number(value));
const today = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Ljubljana', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());

function Pages({ page, count, change }: { page: number; count: number; change: (page: number) => void }) {
    const total = Math.max(1, Math.ceil(count / 25));
    return <div className="pipeline-pagination"><span>{number(count)} zapisov · stran {page} od {total}</span><div>
        <button className="button small" disabled={page === 1} onClick={() => change(page - 1)}>Prejšnja</button>
        <button className="button small" disabled={page >= total} onClick={() => change(page + 1)}>Naslednja</button>
    </div></div>;
}

export default function PipelineDataSources({ stats, csrf, revision, onChange, onError }: {
    stats: DataSourceStats; csrf: string; revision: number; onChange: () => void; onError: (error: unknown) => void;
}) {
    const [tab, setTab] = useState<'erar' | 'documents' | null>(null);
    const [page, setPage] = useState(1);
    const [draft, setDraft] = useState('');
    const [query, setQuery] = useState('');
    const [ocrOnly, setOcrOnly] = useState(true);
    const [payments, setPayments] = useState<Page<Payment> | null>(null);
    const [documents, setDocuments] = useState<Page<Document> | null>(null);
    const [file, setFile] = useState<File | null>(null);
    const [exportedOn, setExportedOn] = useState(today);
    const [busy, setBusy] = useState(false);
    const [loading, setLoading] = useState(false);
    const [message, setMessage] = useState('');
    const [listError, setListError] = useState('');
    const errorHandler = useRef(onError);
    errorHandler.current = onError;
    useEffect(() => {
        if (!tab) return;
        const controller = new AbortController();
        setLoading(true); setListError(''); setPayments(null); setDocuments(null);
        const params = new URLSearchParams({ page: String(page), q: query, ocr: ocrOnly ? '1' : '0' });
        const load = async () => {
            try {
                if (tab === 'erar') {
                    const data = await request<Page<Payment>>(`/erar?${params}`, { signal: controller.signal });
                    if (!controller.signal.aborted) setPayments(data);
                } else {
                    const data = await request<Page<Document>>(`/documents?${params}`, { signal: controller.signal });
                    if (!controller.signal.aborted) setDocuments(data);
                }
            } catch (error) {
                if (!controller.signal.aborted) { setListError((error as Error).message); errorHandler.current(error); }
            } finally { if (!controller.signal.aborted) setLoading(false); }
        };
        void load();
        return () => controller.abort();
    }, [tab, page, query, ocrOnly, revision]);
    const select = (next: 'erar' | 'documents') => {
        setTab(tab === next ? null : next); setPage(1); setQuery(''); setDraft('');
    };
    const search = (event: FormEvent) => { event.preventDefault(); setPage(1); setQuery(draft.trim()); };
    const upload = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault(); if (!file) return;
        const form = event.currentTarget;
        setBusy(true); setMessage('');
        try {
            const body = new FormData(); body.set('file', file); body.set('exported_on', exportedOn);
            const result = await request<{ imported: number }>('/erar', { method: 'POST', body }, csrf);
            setMessage(`Obdelanih transakcij: ${number(result.imported)}. Ponovni uvoz iste transakcije je ne podvoji.`);
            setFile(null); form.reset(); setTab('erar'); setPage(1); setQuery(''); setDraft(''); onChange();
        } catch (error) { onError(error); } finally { setBusy(false); }
    };
    return <section className="surface pipeline-panel" aria-label="Podatki ERAR in dokumenti OCR">
        <div className="section-heading"><h2><Database size={18}/>ERAR in OCR dokumenti</h2></div>
        <div className="pipeline-metrics pipeline-award-metrics">
            <div><span>Transakcije ERAR</span><strong>{number(stats.erar?.transactions || 0)}</strong><small>{number(stats.erar?.recipients || 0)} prejemnikov · {number(stats.erar?.payers || 0)} plačnikov</small></div>
            <div><span>ERAR s sklicem na naročilo</span><strong>{number(stats.erar?.with_procedure || 0)}</strong><small>{number(stats.erar?.with_award || 0)} z vnesenim ID sklopa</small></div>
            <div><span>Dokumenti z besedilom OCR</span><strong>{number(stats.ocr?.ocr_documents || 0)}</strong><small>{number(stats.ocr?.ocr_contents || 0)} različnih vsebin · {number(stats.ocr?.ocr_pages || 0)} strani OCR</small></div>
            <div><span>Dokumenti z indeksom</span><strong>{number(stats.ocr?.indexed || 0)}</strong><small>od {number(stats.ocr?.documents || 0)} dokumentov brez arhivskih ovojnic</small></div>
        </div>
        <p className="section-help">OCR šteje dokumente, kjer je bilo uspešno prepoznano besedilo na vsaj eni strani. Enaka vsebina pri več razpisih šteje kot več dokumentov; strani OCR štejemo po različnih vsebinah.</p>
        {stats.erar && <p className="section-help">ERAR: plačila {day(stats.erar.first_payment_on)} – {day(stats.erar.last_payment_on)} · zadnji izvoz {day(stats.erar.last_export_on)} · vsota EUR {amount(stats.erar.eur_amount)}.{stats.erar.other_currencies > 0 && ` Iz vsote izključenih ${number(stats.erar.other_currencies)} transakcij v drugih valutah.`} Sklic na naročilo še ne potrjuje pripadnosti plačila posameznemu projektu. Statistika se osveži v največ 30 sekundah.</p>}
        <details className="quiet-disclosure"><summary><Upload size={15}/> Uvozi podatke ERAR</summary>
            <p className="section-help">Naložite javni izvoz ERAR CSV ali XLSX do 20 MB. Podatki se shranijo v bazo tega strežnika. Zneskov podjetja brez povezave z naročilom ne pripisujemo razpisu.</p>
            <form className="pipeline-erar-upload" onSubmit={upload}>
                <label className="field"><span>Izvoz ERAR</span><input type="file" accept=".csv,.xlsx" required onChange={event => setFile(event.target.files?.[0] || null)}/></label>
                <label className="field"><span>Datum izvoza</span><input type="date" value={exportedOn} max={today()} required onChange={event => setExportedOn(event.target.value)}/></label>
                <button className="button primary" disabled={busy || !file}>{busy ? 'Uvažam …' : 'Uvozi v strežniško bazo'}</button>
            </form>
        </details>
        {message && <p className="pipeline-message" role="status">{message}</p>}
        <div className="pipeline-actions"><button className="button small" aria-expanded={tab === 'erar'} onClick={() => select('erar')}>Transakcije ERAR</button><button className="button small" aria-expanded={tab === 'documents'} onClick={() => select('documents')}><FileText size={15}/>Dokumenti in vsebina</button></div>
        {tab && <>
            <form className="pipeline-source-search" onSubmit={search}><label className="field"><span>{tab === 'erar' ? 'Matična številka, številka JN ali ID transakcije' : 'Naziv dokumenta ali razpisa'}</span><input value={draft} maxLength={200} onChange={event => setDraft(event.target.value)}/></label><button className="button small">Išči</button></form>
            {tab === 'documents' && <label className="checkbox-row"><input type="checkbox" checked={ocrOnly} onChange={event => { setOcrOnly(event.target.checked); setPage(1); }}/><span>Samo dokumenti z besedilom OCR</span></label>}
            {loading && <p role="status">Nalagam podatke …</p>}
            {listError && <p role="alert">{listError}</p>}
            {tab === 'erar' && payments && <><div className="pipeline-table-wrap"><table className="pipeline-table"><thead><tr><th>Plačilo</th><th>Znesek</th><th>Plačnik (MŠ)</th><th>Prejemnik (MŠ)</th><th>Naročilo / sklop</th><th>Izvoz</th></tr></thead><tbody>{payments.results.map(row => <tr key={row.source_id}>
                <td>{day(row.paid_on)}<small>{row.source_id}</small></td><td>{amount(row.amount, row.currency)}</td><td>{row.payer || '—'}</td><td>{/^\d{10}$/.test(row.recipient) ? <a className="pipeline-link" href={`https://erar.si/podjetje/${row.recipient}/profil/transakcije`} target="_blank" rel="noopener noreferrer">{row.recipient}</a> : row.recipient || '—'}</td><td>{row.procedure || 'Brez sklica'}<small>{row.award_id}</small></td><td>{day(row.exported_on)}</td>
            </tr>)}</tbody></table>{!payments.count && <p className="pipeline-empty">Za izbrano iskanje ni transakcij ERAR.</p>}</div><Pages page={page} count={payments.count} change={setPage}/></>}
            {tab === 'documents' && documents && <><div className="pipeline-table-wrap"><table className="pipeline-table"><thead><tr><th>Dokument</th><th>Razpis</th><th>Obdelava</th><th>Ogled</th></tr></thead><tbody>{documents.results.map(row => <tr key={row.id}>
                <td>{row.title}<small>Različica {row.version} · {row.id}</small></td><td><a className="pipeline-link" href={`#/razpisi/${encodeURIComponent(row.tender_id)}`}>{row.tender_title}</a></td><td>{row.has_ocr ? 'Besedilo OCR' : row.indexed_content_id ? 'Besedilni indeks' : 'Brez indeksa'}<small>{row.error}</small></td><td><a className="pipeline-link" href={row.original_url} target="_blank" rel="noopener noreferrer">Izvirni dokument</a>{(row.indexed_content_id || row.status === 'processed') && <p><a className="pipeline-link" href={row.text_url} target="_blank" rel="noopener noreferrer">Izluščeno besedilo</a></p>}</td>
            </tr>)}</tbody></table>{!documents.count && <p className="pipeline-empty">Za izbrani filter ni dokumentov.</p>}</div><Pages page={page} count={documents.count} change={setPage}/></>}
        </>}
    </section>;
}
